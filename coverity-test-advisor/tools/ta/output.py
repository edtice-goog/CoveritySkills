"""Output: each gap as a Coverity defect through cov-import-results, and the report.

The defect: checker TA.INSUFFICIENT_TEST_COVERAGE, subcategory = verdict, extra = the function's name (its link
name in C), and the reasoning in the events. Sources are exported from git at the head commit, so the markers
land on the head's code whatever the capture tree holds now.
"""
import collections
import json
import os
import re
import shutil
import subprocess

CHECKER = "TA.INSUFFICIENT_TEST_COVERAGE"
DEFECT = {"UNTESTED": "High", "INSUFFICIENT": "Medium", "WEAK": "Medium", "UNKNOWN": "Low"}
LONG = {
    "UNTESTED": "No test reaches this function, and it changed or calls a function whose behaviour changed.",
    "INSUFFICIENT": "Lines that carry the change never ran in any test.",
    "WEAK": "The changed lines ran, but no test exercises the behaviour that changed.",
    "UNKNOWN": "Test Advisor could not judge this function: coverage or other evidence is missing.",
}
MAX_EVENT = 400
NOT_GAPS = ("SUFFICIENT", "NOT_JUDGED", "UNREACHABLE_HERE")


def _clip(s):
    return s if len(s) <= MAX_EVENT else s[:MAX_EVENT - 3] + "..."


def final_verdicts(analysis, verdicts):
    """A function that reached the judge and has no verdict is UNKNOWN ("not judged"), or, when verdicts.json says
    "_unjudged": "omit" (the judging was capped by hand), NOT_JUDGED: listed in the report, no defect."""
    out = {}
    omit = verdicts.get("_unjudged") == "omit"
    for fid, r in analysis["affected"].items():
        if r["triage"] == "JUDGE":
            if omit and not verdicts.get(fid):
                out[fid] = {"verdict": "NOT_JUDGED", "reason": "reached the judge; judging was capped", "line": r["start"]}
                continue
            v = dict(verdicts.get(fid) or {"verdict": "UNKNOWN", "reason": "not judged"})
        elif (verdicts.get(fid) or {}).get("verdict") == "UNREACHABLE_HERE":
            # The judge showed the code cannot run in this module (no caller; a default every subclass here
            # overrides). That outranks "no test ran it": it is reported, not a defect.
            v = dict(verdicts[fid])
        else:
            detail = r["detail"]
            missed = detail if isinstance(detail, list) else []
            reason = (f"Line(s) {', '.join(map(str, missed))} carry the change and never ran in any test."
                      if missed else detail)
            v = {"verdict": r["triage"], "reason": reason, "line": missed[0] if missed else r["start"],
                 "uncovered": [f"{r['file']}:{n}: never ran" for n in missed]}
            note = verdicts.get(fid) or {}
            if note.get("note"):
                v["reason"] += " " + note["note"]
            if note.get("suggested_test"):
                v["suggested_test"] = note["suggested_test"]
        out[fid] = v
    return out


SRC_ROW = re.compile(r"^([> ])\s*(\d+)\s+(\S+)\s+(br \d+/\d+)?\s*\|")
def plain(text):
    """Event text on one line: the judge's line breaks and doubled spaces removed."""
    return text.replace("\n", " ").replace("  ", " ")


def line_counts(run, packet):
    """{line: "ran" | "0" | count} for the instrumented lines of a packet's function."""
    out = {}
    for line in open(f"{run}/{packet}", encoding="utf-8", errors="replace"):
        m = SRC_ROW.match(line)
        if m and m[3] != "-":
            out[int(m[2])] = m[3]
    return out


def short_delta(lines, cut=220):
    """A model delta in a sentence: the generic module first (it carries the behaviour), then the rest."""
    lines = sorted(lines, key=lambda l: not l.startswith("generic:"))
    text = " | ".join(lines)
    text = re.sub(r"\s+", " ", text.replace("\n", " "))
    return text if len(text) <= cut else text[:cut - 3] + "..."


def gap_notes(final, analysis):
    """{(file basename, line): [(fid, what, suggested_test)]} from the judged verdicts, whose words for an
    unexercised line can explain the same line in a rule-decided defect."""
    a = analysis["affected"]
    out = collections.defaultdict(list)
    for fid, v in final.items():
        if a[fid]["triage"] != "JUDGE" or v["verdict"] in NOT_GAPS:
            continue
        for u in v.get("uncovered", []):
            m = LOC_RE.match(u)
            what = m[3].strip() if m else ""
            if m and what and what != "never ran" and not what.startswith("same "):
                out[(m[1], int(m[2]))].append((fid, what, v.get("suggested_test", "")))
    return out


def events(fid, r, v, analysis, src_dir, run, notes):
    """The defect's events in three kinds, each saying which it is: the verdict and the lines no test
    exercises ("Not tested"), why the function was examined ("Why affected", every call site saying whether it
    ran), and context (what the callee changed, a suggested test, the tests that run the function)."""
    a = analysis["affected"]
    path = lambda f: os.path.join(src_dir, f)
    counts = line_counts(run, r["packet"])
    ran = lambda n: counts.get(n, "0") != "0"
    main = v.get("line") or r["start"]
    rule = r["triage"] != "JUDGE"
    how = "fixed rule: coverage alone" if rule else "judged"
    ev = [{"tag": "test_advisor", "main": True, "file": path(r["file"]), "line": main,
           "description": _clip(f"{v['verdict']} ({how}): {plain(v['reason'])}")}]
    for reason in r["reasons"]:
        if reason[0] == "changed":
            lines = sorted(int(n) for n, why in r["targets"].items() if why == "changed")
            if lines:
                n_ran = sum(1 for n in lines if ran(n))
                ev.append({"tag": "why_affected", "file": path(r["file"]), "line": lines[0],
                           "description": f"Why affected: this function's own code changed in this release "
                                          f"(lines {', '.join(map(str, lines))}); {n_ran} of {len(lines)} ran in the tests."})
            continue
        callee = reason[1]
        cname = callee.split(":", 1)[1]
        short = cname.split("(")[0].split(".")[-1] + "()"
        sites = sorted(int(n) for n, why in r["targets"].items() if why == f"calls {cname}")
        if not sites:
            continue  # a model change with no call site in this function would only be noise here
        n_ran = sum(1 for n in sites if ran(n))
        if len(sites) == 1:
            where = f"line {sites[0]}, {'ran' if n_ran else 'never ran'}"
        else:
            listed = ", ".join(map(str, sites[:-1])) + f" and {sites[-1]}"
            state = "all ran" if n_ran == len(sites) else ("none ran" if not n_ran else f"{n_ran} ran")
            where = f"lines {listed}, {state}"
        delta = analysis["model_changes"].get(cname, {}).get("lines", [])
        ev.append({"tag": "why_affected", "file": path(r["file"]), "line": sites[0],
                   "description": _clip(f"Why affected: calls {short} here ({where}); "
                                        f"what {short} does changed in this release.")})
        if callee in a and callee != fid:
            ev.append({"tag": "context", "file": path(a[callee]["file"]), "line": a[callee]["start"],
                       "description": _clip(f"Context: how {short} changed, in Coverity's derived model: "
                                            f"{short_delta(delta)}")})
    files = {os.path.basename(x["file"]): x["file"] for x in a.values()}
    borrowed, gaps = None, []
    for u in v.get("uncovered", [])[:10]:
        m = LOC_RE.match(u)  # "<file or basename>:<line>[-<line>]: <what>", as judges write it
        f = m and (r["file"] if m[1] == os.path.basename(r["file"]) else files.get(m[1]))
        if not f:
            continue
        n, what = int(m[2]), m[3].strip()
        if not what or what == "never ran":
            other = notes.get((m[1], n), [])
            if other:
                ofid, what, test = other[0]
                borrowed = borrowed or (ofid, test, what)
            else:
                what = ""
        if gaps and not what and gaps[-1]["file"] == f and gaps[-1]["last"] == n - 1:
            gaps[-1]["last"] = n      # an adjacent line with nothing new to say joins the gap above
            continue
        gaps.append({"file": f, "line": n, "last": n, "what": what})
    for g in gaps:
        span = f"line {g['line']}" if g["last"] == g["line"] else f"lines {g['line']}-{g['last']}"
        text = f"{span}: {g['what']}" if g["what"] else f"{span} carry the change and never ran in any test"
        ev.append({"tag": "not_tested", "file": path(g["file"]), "line": g["line"],
                   "description": _clip(f"Not tested: {plain(text)}")})
    if rule and borrowed:
        ev[0]["description"] = _clip(f"{v['verdict']} ({how}): {plain(v['reason'])} That is: {plain(borrowed[2])}.")
    test = v.get("suggested_test")
    label = "Suggested test"
    if not test and borrowed and borrowed[1]:
        test = borrowed[1]
        label = f"Suggested test (from the verdict on {a[borrowed[0]]['name'].split('(')[0].split('.')[-1]}(), which reaches the same lines)"
    if test:
        ev.append({"tag": "suggested_test", "file": path(r["file"]), "line": main,
                   "description": _clip(f"{label}: {plain(test)}")})
    if r["tests"]:
        units = ", ".join(sorted(r["tests"]))
        ev.append({"tag": "context", "file": path(r["file"]), "line": r["start"],
                   "description": _clip(f"Context: tests that run this function: {units}.")})
    return ev


def finish(run, ds):
    analysis = json.load(open(f"{run}/analysis.json"))
    verdicts = json.load(open(f"{run}/verdicts.json")) if os.path.exists(f"{run}/verdicts.json") else {}
    final = final_verdicts(analysis, verdicts)
    notes = gap_notes(final, analysis)
    head = analysis["head"]
    ver = ds.prepare(head["tag"])
    clone, src_dir = ds.clone, ver.export_root

    issues, files = [], set()
    for fid, v in sorted(final.items()):
        if v["verdict"] not in DEFECT:
            continue
        r = analysis["affected"][fid]
        ev = events(fid, r, v, analysis, src_dir, run, notes)
        files.update(e["file"] for e in ev)
        issues.append({
            "checker": CHECKER, "extra": r["name"], "file": os.path.join(src_dir, r["file"]),
            "function": r["name"], "subcategory": v["verdict"].lower(),
            "properties": {"type": "Insufficient test coverage", "category": "Test Advisor",
                           "impact": DEFECT[v["verdict"]], "cwe": 0, "longDescription": LONG[v["verdict"]],
                           "localEffect": "The changed behaviour can reach users untested.",
                           "issueKind": "QUALITY"},
            "events": ev,
        })

    for f in files:
        rel = os.path.relpath(f, src_dir)
        os.makedirs(os.path.dirname(f), exist_ok=True)
        open(f, "w").write(subprocess.run(["git", "-C", clone, "show", f"{head['sha']}:{rel}"], check=True,
                                          capture_output=True, text=True).stdout)
    imp = {"header": {"version": 1, "format": "cov-import-results input"},
           "sources": [{"file": f, "encoding": ds.encoding} for f in sorted(files)], "issues": issues}
    json.dump(imp, open(f"{run}/import.json", "w"), indent=1)

    xml = None
    stale = f"{run}/{CHECKER}.errors.xml"   # a previous run's issues must not outlive a run that has none
    if os.path.exists(stale):
        os.remove(stale)
    shutil.rmtree(ver.ta_idir, ignore_errors=True)
    if issues:
        ta_idir = ver.ta_idir
        os.makedirs(os.path.dirname(ta_idir), exist_ok=True)
        subprocess.run(["cp", "-a", ver.idir, ta_idir], check=True)
        subprocess.run([f"{ds.cov_bin}/cov-import-results", "--dir", ta_idir, ds.flags["import"], "--append",
                        f"{run}/import.json"], check=True, capture_output=True, text=True)
        xml = f"{run}/{CHECKER}.errors.xml"
        shutil.copy(f"{ta_idir}/output/{CHECKER}.errors.xml", xml)

    report(run, analysis, final)
    print(f"{len(issues)} defects; report: {run}/report.md" + (f"; xml: {xml}" if xml else ""))


LOC_RE = re.compile(r"\s*(?:[\w./$-]*/)?([\w$]+\.\w+):(\d+)(?:-\d+)?:?\s*(.*)")


def gap_clusters(analysis, final, window=12):
    """The unexercised locations of all gaps, clustered per file (lines within `window` of each other), each with
    the functions whose verdict names it. A function appears under every cluster it reaches, so one root gap is
    listed once however many callers it has."""
    hits = collections.defaultdict(list)          # (file, line) -> [(fid, what)]
    for fid, v in final.items():
        if v["verdict"] in NOT_GAPS:
            continue
        for u in v.get("uncovered", []):
            m = LOC_RE.match(u)
            if m:
                hits[(m[1], int(m[2]))].append((fid, m[3]))
    clusters = []
    for file in sorted({f for f, _ in hits}):
        lines = sorted(n for f, n in hits if f == file)
        cur = [lines[0]]
        for n in lines[1:]:
            if n - cur[-1] <= window:
                cur.append(n)
            else:
                clusters.append((file, cur))
                cur = [n]
        clusters.append((file, cur))
    out = []
    for file, lines in clusters:
        fids, what = [], ""
        for n in lines:
            for fid, w in hits[(file, n)]:
                if fid not in fids:
                    fids.append(fid)
                what = what or w
        out.append({"file": file, "lines": lines, "what": what, "functions": fids,
                    "verdicts": sorted({final[f]["verdict"] for f in fids}),
                    "suggested_test": next((final[f]["suggested_test"] for f in fids if final[f].get("suggested_test")), "")})
    return sorted(out, key=lambda c: -len(c["functions"]))


def report(run, analysis, final):
    a, b, h = analysis["affected"], analysis["base"], analysis["head"]
    counts = {}
    for v in final.values():
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
    order = ["UNTESTED", "INSUFFICIENT", "WEAK", "UNKNOWN", "NOT_JUDGED", "UNREACHABLE_HERE", "SUFFICIENT"]
    out = [f"# Test Advisor: {analysis.get('dataset') or 'the project'} {b['tag']} to {h['tag']}", "",
           f"Base {b['sha'][:10]}, head {h['sha'][:10]}. "
           f"{len(analysis['s0'])} functions changed, {len(analysis['model_changes'])} derived models changed, "
           f"{len(a)} functions affected.", "",
           "| verdict | functions |", "|---|---:|"]
    out += [f"| {k} | {counts[k]} |" for k in order if k in counts]
    gaps = [(fid, v) for fid, v in final.items() if v["verdict"] not in NOT_GAPS]
    clusters = gap_clusters(analysis, final)
    if clusters:
        out += ["", "## Gaps by location", "",
                f"{len(clusters)} places in the code that the change reaches and no test exercises, with every affected "
                "function whose verdict names them (a function can reach several).", "",
                "| where | not exercised | verdicts | functions |", "|---|---|---|---:|"]
        for c in clusters:
            where = f"{c['file']}:{c['lines'][0]}" + (f"-{c['lines'][-1]}" if len(c["lines"]) > 1 else "")
            out.append(f"| {where} | {c['what'][:140]} | {', '.join(c['verdicts'])} | {len(c['functions'])} |")
    out += ["", "## Gaps", ""]
    if not gaps:
        out.append("None.")
    for fid, v in sorted(gaps, key=lambda kv: order.index(kv[1]["verdict"])):
        r = a[fid]
        out += [f"### {v['verdict']}: `{r['name']}` ({r['file']}:{r['start']})", "", v["reason"], ""]
        if v.get("suggested_test"):
            out += [f"**Suggested test:** {v['suggested_test']}", ""]
        if r["tests"]:
            out += [f"Tests that run it: {', '.join(sorted(r['tests']))}.", ""]
    unreachable = sorted((a[fid]["name"], v["reason"]) for fid, v in final.items() if v["verdict"] == "UNREACHABLE_HERE")
    if unreachable:
        out += ["## Not reachable in this module", "",
                f"{len(unreachable)} affected functions cannot run inside this module: nothing calls them, or every "
                "subclass here overrides them. No test here can reach them, so they carry no defect. Code outside the "
                "module (another library subclassing these classes) may still run them.", ""]
        out += [f"- `{n}`: {r}" for n, r in unreachable] + [""]
    unjudged = sorted(a[fid]["name"] for fid, v in final.items() if v["verdict"] == "NOT_JUDGED")
    if unjudged:
        out += ["## Not judged", "",
                f"{len(unjudged)} functions reached the judge and were not judged (the judging was capped); they carry no defect:", ""]
        out += [f"- `{n}`" for n in unjudged] + [""]
    unmapped = analysis.get("unmapped_changes", [])
    if unmapped:
        out += ["## Changes no analysed function contains", "",
                "These changed lines are in no function the Coverity capture measured, so no model, call graph or "
                "verdict covers them: a file the build did not compile (check the capture with build fidelity), or "
                "lines outside any function body (declarations, fields, macros, initializers).", "",
                "| file | lines | kind |", "|---|---|---|"]
        for u in unmapped:
            ls = u["lines"]
            shown = ", ".join(map(str, ls[:12])) + (f" and {len(ls) - 12} more" if len(ls) > 12 else "")
            out.append(f"| {u['file']} | {shown} | {u['kind']} |")
        out.append("")
    out += ["## Covered", "", "| function | why it is affected | reason |", "|---|---|---|"]
    for fid, v in sorted(final.items()):
        if v["verdict"] == "SUFFICIENT":
            r = a[fid]
            why = "; ".join("changed" if x[0] == "changed" else f"calls {x[1].split(':')[1]}"
                            for x in r["reasons"])
            out.append(f"| `{r['name']}` | {why} | {v['reason']} |")
    out += ["", "## The walk", "",
            f"- Changed functions (S0): {', '.join(f'`{f.split(':')[1]}`' for f in analysis['s0'])}.",
            "- Boundaries (affected, model unchanged, callers not walked): "
            + (", ".join(f"`{r['name']}`" for r in a.values() if r["boundary"]) or "none") + ".",
            "- Model changes the walk never reached: "
            + (", ".join(f"`{n}`" for n in analysis["unexplained_model_changes"]) or "none") + ".",
            "- Stopped by the depth or fan-out cap (callers not walked; the walk is incomplete here): "
            + (", ".join(f"`{r['name']}`" for r in a.values() if r.get("truncated")) or "none") + ".",
            "- Affected functions whose address is taken, so callers through that pointer are not in the walk: "
            + (", ".join(f"`{r['name']}`" for r in a.values() if r.get("address_taken")) or "none") + ".",
            f"- Call graph: {analysis['graph']['edges']} edges; {len(analysis['graph']['address_taken'])} functions "
            "in the program have their address taken.",
            f"- Per-test coverage units: {len(analysis['per_test_units'])}.", "",
            "## Model changes", ""]
    for n, d in analysis["model_changes"].items():
        out.append(f"- `{n}` ({d['status']})")
        out += [f"  - {line}" for line in d["lines"]]
    open(f"{run}/report.md", "w").write("\n".join(out) + "\n")
    json.dump({"base": b, "head": h, "verdicts": final}, open(f"{run}/report.json", "w"), indent=1)
