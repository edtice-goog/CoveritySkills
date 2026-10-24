#!/usr/bin/env python3
"""Step 4: assemble and validate triage records (references/records.md).

  records.py assemble --bundles <dir> --lanes lanes.json --verdicts <dir> \
                      --run run.json --out <dir>/triage.json [--report <md>]
  records.py check-lanes --bundles <dir> --lanes lanes.json [--run run.json]
  records.py validate <triage.json>

assemble joins index.json (tools/bundle.py), the lane assignment and the
verdict files by merge key, maps each verdict onto Connect's triage fields,
and writes triage.json plus TRIAGE-REPORT.md. Every check runs before
anything is written; one failure writes nothing.
"""
import argparse
import collections
import json
import pathlib
import re
import sys

LANES = ("Construction", "Contract", "Value or path")
OTHER = "Other"
METHOD = re.compile(r"^(LLM: \S.*|Execution: coverity-verify|Human|None)$")
INVARIANT = "false positive - global invariant"
# verdict -> (classification, action, severity, comment label)
MAPPING = {
    "real": ("Bug", "Fix Required", None, "Real defect"),
    "real, low severity": ("Bug", "Fix Required", "Minor", "Real defect, low severity"),
    "intentional": ("Intentional", "Ignore", None, "Intentional"),
    INVARIANT: ("False Positive", "Ignore", None, "False positive (global invariant)"),
    "false positive - heuristic misfire": ("False Positive", "Ignore", None,
                                           "False positive (heuristic misfire)"),
    "unresolved": (None, None, None, "Unresolved"),
}
COMMENT_MAX = 4000
BAD_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def read_json(path, errors, what):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        errors.append(what + ": cannot read " + str(path) + ": " + str(e))
        return None


def comment_for(label, v, lane, assigner, method, date):
    executed = "executed" if v.get("executed") else "read, not executed"
    tail = ("\n[coverity-triage " + date + "] Lane: " + lane + " (assigned by "
            + assigner + "). Method: " + method + ", " + executed + ".")
    body = v["reason"].strip()
    if v["verdict"] == INVARIANT:
        body += ("\nInvariant: " + v["invariant"].strip() + "\nEnforced at: "
                 + v["enforced_at"].strip() + "\nBreaks if: " + v["breaks_if"].strip())
    head = label + ": "
    room = COMMENT_MAX - len(head) - len(tail)
    if len(body) > room:
        note = " ... [shortened; full text in triage.json evidence]"
        body = body[:room - len(note)].rstrip() + note
    return head + body + tail


def assemble(args):
    errors = []
    bdir = pathlib.Path(args.bundles)
    index = read_json(bdir / "index.json", errors, "index")
    lanes = read_json(args.lanes, errors, "lanes")
    run = read_json(args.run, errors, "run")
    if errors:
        return fail(errors)

    plan = run.get("lanes") or {}
    for lane in LANES:
        m = plan.get(lane)
        if m is None or not METHOD.match(m):
            errors.append("run.json: lanes[" + repr(lane) + "] must be a method "
                          "(LLM: <model> | Execution: coverity-verify | Human | None), got "
                          + repr(m))
    for lane in ("Construction", "Contract"):
        if str(plan.get(lane)).startswith("Execution"):
            errors.append("run.json: Execution: coverity-verify is a value-or-path "
                          "method, not a " + lane + " one")
    for k in plan:
        if k not in LANES:
            errors.append("run.json: unknown lane " + repr(k) + " (Other is never planned)")
    assigner = lanes.get("assigned_by") or ""
    if not METHOD.match(assigner) or assigner == "None":
        errors.append("lanes.json: assigned_by must name the assigner's method, got "
                      + repr(assigner))
    date = run.get("date") or ""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        errors.append("run.json: date must be YYYY-MM-DD, got " + repr(date))

    bundles = {b["mergeKey"]: b for b in index.get("bundles", [])}
    lane_of = {}
    for a in lanes.get("lanes", []):
        mk = a.get("mergeKey")
        if mk not in bundles:
            errors.append("lanes.json: " + str(mk) + " is not a bundled finding")
        elif mk in lane_of:
            errors.append("lanes.json: " + mk + " assigned twice")
        elif a.get("lane") not in LANES + (OTHER,):
            errors.append("lanes.json: " + mk + ": lane " + repr(a.get("lane"))
                          + " is not one of " + ", ".join(LANES + (OTHER,)))
        elif not (a.get("reason") or "").strip():
            errors.append("lanes.json: " + mk + ": no reason given for the lane")
        else:
            lane_of[mk] = a
    for mk in bundles:
        if mk not in lane_of and not any(e.startswith("lanes.json: " + mk) for e in errors):
            errors.append("lanes.json: " + mk + " (" + bundles[mk]["bundle"] + ") has no lane")

    overrides = read_overrides(run, bundles, errors)
    expected = run.get("expected")
    if expected is not None:
        if expected.get("lane") not in LANES or not METHOD.match(expected.get("method") or ""):
            errors.append("run.json: expected needs a method lane and a method, got " + repr(expected))
        else:
            for mk, a in lane_of.items():
                if a["lane"] != expected["lane"] and mk not in overrides:
                    errors.append(bundles[mk]["bundle"] + " (" + mk + "): assigned " + a["lane"]
                                  + ", not the expected " + expected["lane"] + ", and the user's "
                                  "choice is not recorded (add an override with its reason)")

    def method_for(mk):
        if mk in overrides:
            return overrides[mk][0]
        lane = lane_of.get(mk, {}).get("lane")
        return "None" if lane in (None, OTHER) else plan.get(lane, "None")

    verdict_of, model_of = {}, {}
    vdir = pathlib.Path(args.verdicts) if args.verdicts else None
    files = sorted(vdir.glob("*.json")) if vdir and vdir.is_dir() else []
    for f in files:
        doc = read_json(f, errors, "verdicts")
        if doc is None:
            continue
        lane, method = doc.get("lane"), doc.get("method")
        if lane not in LANES + (OTHER,):
            errors.append(f.name + ": lane " + repr(lane) + " is not a lane")
            continue
        if not METHOD.match(method or "") or method == "None":
            errors.append(f.name + ": method " + repr(method) + " did not produce verdicts")
            continue
        for v in doc.get("verdicts", []):
            mk = v.get("mergeKey")
            where = f.name + ": " + str(mk)
            if mk not in bundles:
                errors.append(where + " is not a bundled finding")
                continue
            if mk in verdict_of:
                errors.append(where + " has a second verdict (also in " + verdict_of[mk][1] + ")")
                continue
            if mk in lane_of and lane_of[mk]["lane"] != lane:
                errors.append(where + " was read in " + lane + " but assigned to "
                              + lane_of[mk]["lane"])
                continue
            if method != method_for(mk):
                errors.append(where + ": method " + method + " is not the one planned for it ("
                              + method_for(mk) + ")")
                continue
            if v.get("verdict") not in MAPPING:
                errors.append(where + ": verdict " + repr(v.get("verdict"))
                              + " is not in the verdict set")
                continue
            if not (v.get("reason") or "").strip():
                errors.append(where + ": no reason")
                continue
            if v["verdict"] == INVARIANT:
                gone = [k for k in ("invariant", "enforced_at", "breaks_if")
                        if not (v.get(k) or "").strip()]
                if gone:
                    errors.append(where + ": a global-invariant dismissal needs "
                                  + ", ".join(gone) + " (rule 30: no location, no dismissal)")
                    continue
            if v.get("executed") and not method.startswith("Execution"):
                errors.append(where + ": executed is true but the method is " + method)
                continue
            verdict_of[mk] = (v, f.name)
            model_of[mk] = doc.get("model")

    records = []
    for mk, b in sorted(bundles.items(), key=lambda kv: kv[1]["n"]):
        if mk not in lane_of:
            continue
        lane = lane_of[mk]["lane"]
        method = method_for(mk)
        v = verdict_of.get(mk, (None, None))[0]
        if v is None and method not in ("None", "Human"):
            errors.append(b["bundle"] + " (" + mk + "): " + lane + " finding ran " + method
                          + " but has no verdict")
            continue
        if v is not None and method == "None":
            errors.append(b["bundle"] + " (" + mk + "): a verdict for a finding whose method "
                          "did not run (" + lane + ", None)")
            continue
        state = {"classification": None, "action": None, "severity": None, "comment": None,
                 "customTriage": {"Triage lane": lane, "Triage method": method}}
        evidence = {"bundle": b["bundle"], "selected_because": b.get("selected_because")}
        if v is not None:
            cls, act, sev, label = MAPPING[v["verdict"]]
            state.update(classification=cls, action=act, severity=sev,
                         comment=comment_for(label, v, lane, assigner, method, date))
            if BAD_CHARS.search(state["comment"]):
                errors.append(b["bundle"] + " (" + mk + "): the comment carries a control "
                              "character (a NUL from a C '\\0' is the usual one); Connect "
                              "refuses the write")
                continue
            evidence.update({k: v.get(k) for k in ("reason", "invariant", "enforced_at",
                                                    "breaks_if", "sites_read")
                             if v.get(k) is not None})
            evidence["executed"] = bool(v.get("executed"))
            evidence["model"] = model_of.get(mk)
        elif method == "Human":
            evidence["status"] = "awaiting a person's verdict"
        rec = {"mergeKey": mk, "checker": b.get("checker"),
               "judged": {"tag": index.get("tag"), "sites": b.get("sites", [])},
               "lane": lane, "lane_reason": lane_of[mk]["reason"].strip(),
               "method": method, "verdict": v["verdict"] if v else None,
               "triageState": state, "evidence": evidence}
        if mk in overrides:
            rec["method_reason"] = overrides[mk][1]
        records.append(rec)

    if errors:
        return fail(errors)

    doc = {"format": "coverity-triage-records", "schema": 1,
           "run": dict(run, assigned_by=assigner,
                       source={k: index.get(k) for k in ("issues", "git_repo", "tag", "source",
                                                         "strip_prefix", "findings_in_file")}),
           "records": records}
    problems = check(doc)
    if problems:
        return fail(problems)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    report = pathlib.Path(args.report) if args.report else out.with_name("TRIAGE-REPORT.md")
    report.write_bytes(render_report(doc).encode("utf-8"))
    print("wrote " + str(len(records)) + " records to " + str(out) + " and " + str(report))
    return 0


def check(doc):
    """The invariants of a triage.json, whoever wrote it."""
    p = []
    if doc.get("format") != "coverity-triage-records" or doc.get("schema") != 1:
        p.append("format/schema must be coverity-triage-records / 1")
    seen = set()
    for r in doc.get("records", []):
        mk = r.get("mergeKey")
        w = str(mk) + ": "
        if not mk or mk in seen:
            p.append(w + "missing or duplicate merge key")
        seen.add(mk)
        lane, method, verdict = r.get("lane"), r.get("method"), r.get("verdict")
        st = r.get("triageState") or {}
        ct = st.get("customTriage") or {}
        if lane not in LANES + (OTHER,):
            p.append(w + "bad lane " + repr(lane))
        if not METHOD.match(method or ""):
            p.append(w + "bad method " + repr(method))
        if (lane == OTHER and (method != "None" or verdict is not None)
                and not r.get("method_reason")):
            p.append(w + "Other takes method None and no verdict, unless an override says why")
        if ct != {"Triage lane": lane, "Triage method": method}:
            p.append(w + "customTriage must carry exactly Triage lane and Triage method")
        if verdict is None:
            if any(st.get(k) is not None for k in ("classification", "action", "severity",
                                                   "comment")):
                p.append(w + "no verdict, so only the custom attributes may be set")
            continue
        if verdict not in MAPPING:
            p.append(w + "verdict " + repr(verdict) + " not in the verdict set")
            continue
        cls, act, sev, _ = MAPPING[verdict]
        if (st.get("classification"), st.get("action"), st.get("severity")) != (cls, act, sev):
            p.append(w + "triage state does not follow the mapping for " + repr(verdict))
        c = st.get("comment") or ""
        if not c or len(c) > COMMENT_MAX:
            p.append(w + "comment missing or longer than " + str(COMMENT_MAX))
        if BAD_CHARS.search(c):
            p.append(w + "comment carries a control character")
    return p


def render_report(doc):
    run, recs = doc["run"], doc["records"]
    src = run.get("source") or {}
    L = ["# Triage report", "",
         "- **Who and where:** " + str(run.get("who")) + "; Connect AI-Assisted Triage: "
         + ("yes" if run.get("connect_ai_triage") else "not used") + "; nothing written to Connect",
         "- **Version:** `" + str(src.get("tag")) + "`, " + str(len(recs)) + " of "
         + str(src.get("findings_in_file")) + " findings (" + str(run.get("selection")) + ")",
         "- **Lane assignment:** " + str(run.get("assigned_by")),
         "- **Plan:** " + "; ".join(l + ": " + str(run["lanes"].get(l)) for l in LANES)
         + "; Other: None", "",
         "## By lane", "",
         "| lane | method | findings | " + " | ".join(MAPPING) + " | no verdict |",
         "|---|---|---|" + "---|" * (len(MAPPING) + 1)]
    for lane in LANES + (OTHER,):
        rs = [r for r in recs if r["lane"] == lane]
        if not rs:
            continue
        c = collections.Counter(r["verdict"] for r in rs)
        methods = sorted({r["method"] for r in rs})
        L.append("| " + lane + " | " + ", ".join(methods) + " | " + str(len(rs)) + " | "
                 + " | ".join(str(c.get(v, 0)) for v in MAPPING) + " | " + str(c.get(None, 0)) + " |")
    L += ["", "## Findings", "",
          "| bundle | checker | site | lane | verdict | lane reason |", "|---|---|---|---|---|---|"]
    for r in recs:
        s = (r["judged"]["sites"] or [{}])[0]
        L.append("| " + r["evidence"]["bundle"] + " | " + str(r["checker"]) + " | `"
                 + str(s.get("file")) + ":" + str(s.get("line")) + "` | " + r["lane"] + " | "
                 + (r["verdict"] or ("awaiting a person" if r["method"] == "Human" else "-"))
                 + " | " + r["lane_reason"].replace("|", "\\|") + " |")
    L += ["", "A sample's counts describe the sample, not the run's false-positive rate (rule 26).", ""]
    return "\n".join(L)


def read_overrides(run, bundles, errors):
    """run.json overrides -> {merge key: (method, reason)}: the user's per-finding choices."""
    out = {}
    for o in run.get("overrides") or []:
        mk, m, why = o.get("mergeKey"), o.get("method"), (o.get("reason") or "").strip()
        if mk not in bundles:
            errors.append("run.json: override for " + str(mk) + ", which is not a bundled finding")
        elif mk in out:
            errors.append("run.json: two overrides for " + mk)
        elif not METHOD.match(m or ""):
            errors.append("run.json: override for " + mk + ": " + repr(m) + " is not a method")
        elif not why:
            errors.append("run.json: override for " + mk + " gives no reason")
        else:
            out[mk] = (m, why)
    return out


def check_lanes(args):
    """Before any method runs: the lane counts, and every finding outside the expected lane."""
    errors = []
    index = read_json(pathlib.Path(args.bundles) / "index.json", errors, "index")
    lanes = read_json(args.lanes, errors, "lanes")
    run = read_json(args.run, errors, "run") if args.run else {}
    if errors:
        return fail(errors)
    bundles = {b["mergeKey"]: b for b in index.get("bundles", [])}
    assigned = {a.get("mergeKey"): a for a in lanes.get("lanes", [])}
    counts = collections.Counter(a.get("lane") for a in assigned.values())
    print("lanes: " + ", ".join(l + " " + str(counts.get(l, 0)) for l in LANES + (OTHER,))
          + "; unassigned " + str(len(set(bundles) - set(assigned))))
    exp = (run or {}).get("expected")
    if not exp:
        print("no expected lane in run.json")
        return 0
    overrides = read_overrides(run, bundles, [])
    off = [(bundles[mk], a) for mk, a in assigned.items()
           if mk in bundles and a.get("lane") != exp.get("lane")]
    print("expected by " + str(exp.get("by")) + ": " + str(exp.get("lane")) + " with "
          + str(exp.get("method")) + "; " + str(len(off)) + " finding(s) landed elsewhere")
    for b, a in sorted(off, key=lambda x: x[0]["n"]):
        choice = overrides.get(a["mergeKey"])
        print("  " + b["bundle"] + "  " + str(a.get("lane")) + "  -- " + str(a.get("reason")))
        if choice:
            print("      user chose: " + choice[0] + " (" + choice[1] + ")")
        else:
            print("      not chosen yet: the expected method anyway, this lane's method, or None")
    return 0


def fail(errors):
    for e in errors:
        print("[ERROR] " + e, file=sys.stderr)
    print("[FATAL] " + str(len(errors)) + " problem(s); nothing written", file=sys.stderr)
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("assemble")
    a.add_argument("--bundles", required=True, help="tools/bundle.py --out directory")
    a.add_argument("--lanes", required=True)
    a.add_argument("--verdicts", help="directory of verdict files (none: every lane planned None or Human)")
    a.add_argument("--run", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--report", help="default: TRIAGE-REPORT.md beside --out")
    c = sub.add_parser("check-lanes", help="before any method runs: lanes, and what landed "
                                          "outside the caller's expected lane")
    c.add_argument("--bundles", required=True)
    c.add_argument("--lanes", required=True)
    c.add_argument("--run")
    v = sub.add_parser("validate")
    v.add_argument("records")
    args = ap.parse_args()
    if args.cmd == "assemble":
        return assemble(args)
    if args.cmd == "check-lanes":
        return check_lanes(args)
    errors = []
    doc = read_json(args.records, errors, "records")
    if errors:
        return fail(errors)
    problems = check(doc)
    if problems:
        return fail(problems)
    print("valid: " + str(len(doc["records"])) + " records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
