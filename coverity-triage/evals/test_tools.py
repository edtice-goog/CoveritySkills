#!/usr/bin/env python3
"""Exercise tools/bundle.py, tools/lanes.py and tools/records.py on a generated fixture.

    python3 -I evals/test_tools.py

Builds a throwaway git repository (one C file with a form feed in it, tagged
v1, then changed in the working tree so a working-tree read would be wrong),
a cov-format-errors-shaped findings file with eight merge keys (one reported
at two sites; one from a custom checker no table has), and runs: the plan,
the bundles, lanes from the checker table, one good assembly, and one
assembly per refusal. Needs git and Python 3; no Coverity installation.
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
TOOLS = HERE.parent / "tools"
ROOT = "/build/proj"

SRC_V1 = ("#include <string.h>\n"
          "\f\n"                                   # line 2: a form feed
          "int f(const char *s) {\n"               # 3
          "  if (strncmp(s, \"k:\", 2) == 0) {\n"  # 4
          "    char *p = strchr(s, ':');\n"        # 5
          "    return p[1];\n"                     # 6
          "  }\n"                                  # 7
          "  return 0;\n"                          # 8
          "}\n"                                    # 9
          "int g(int *q) { return *q; }\n"         # 10
          "int h(int *q) { return *q; }\n")        # 11


def issue(mk, checker, line, fn, events, occ=(1, 1), sub="none"):
    return {"mergeKey": mk, "checkerName": checker, "subcategory": sub,
            "functionDisplayName": fn, "mainEventLineNumber": line,
            "mainEventFilePathname": ROOT + "/src/a.c",
            "strippedMainEventFilePathname": ROOT + "/src/a.c",
            "occurrenceNumberInMK": occ[0], "occurrenceCountForMK": occ[1],
            "events": [{"eventTag": t, "eventDescription": d, "lineNumber": n,
                        "filePathname": ROOT + "/src/a.c",
                        "strippedFilePathname": ROOT + "/src/a.c", "main": m}
                       for (t, d, n, m) in events]}


FINDINGS = {"type": "Coverity issues", "formatVersion": 10, "issues": [
    issue("k1", "NULL_RETURNS", 6, "f", [
        ("returned_null", "strchr returns NULL (checked 9 out of 10 times)", 5, False),
        ("dereference", "Dereferencing a pointer that might be NULL p", 6, True)]),
    issue("k2", "FORWARD_NULL", 10, "g", [("deref", "Dereferencing null q", 10, True)],
          occ=(1, 2)),
    issue("k2", "FORWARD_NULL", 11, "h", [("deref", "Dereferencing null q", 11, True)],
          occ=(2, 2)),
    issue("k3", "CHECKED_RETURN", 5, "f", [("check_return", "strchr not checked", 5, True)]),
    issue("k4", "COPY_PASTE_ERROR", 4, "f", [("copy_paste", "looks copied", 4, True)]),
    issue("k5", "NEGATIVE_RETURNS", 6, "f", [("negative_returns", "p[1] may be negative", 6, True)]),
    issue("k6", "MISRA_CAST", 6, "f", [("misra_violation", "implicit conversion", 6, True)]),
    issue("k7", "ACME_SHAPE", 10, "g", [("shape", "q dereferenced, never tested", 10, True)]),
    issue("k8", "PARSE_ERROR", 1, "", [("parse_error", "cannot open include file", 1, True)]),
]}

# A producer's rows for its own checker: a fixed lane and the checker's own method.
CUSTOM_TABLE = {"format": "coverity-triage-checker-lanes", "schema": 1, "checkers": {
    "ACME_SHAPE": {"lane": "Value or path", "why": "a path-insensitive stand-in for FORWARD_NULL",
                   "method": "Execution: coverity-verify", "route": "harness"}}}


def run(*args, ok=True):
    p = subprocess.run([sys.executable, "-I", *map(str, args)], capture_output=True, text=True)
    if ok and p.returncode != 0:
        raise SystemExit("FAILED (expected success): " + " ".join(map(str, args))
                         + "\n" + p.stdout + p.stderr)
    if not ok and p.returncode == 0:
        raise SystemExit("FAILED (expected refusal): " + " ".join(map(str, args)) + "\n" + p.stdout)
    return p


def wjson(path, obj):
    path.write_text(json.dumps(obj, indent=1), encoding="utf-8")


GOOD_INVARIANT = {"mergeKey": "k1", "verdict": "false positive - global invariant",
                  "reason": "strncmp at src/a.c:4 guarantees the colon; p is not NULL at src/a.c:6.",
                  "invariant": "s begins with \"k:\" in this branch",
                  "enforced_at": "src/a.c:4", "breaks_if": "the strncmp guard is removed",
                  "sites_read": ["src/a.c:3-9"], "executed": False}


def main():
    work = pathlib.Path(tempfile.mkdtemp(prefix="covtriage-"))
    try:
        repo = work / "repo"
        (repo / "src").mkdir(parents=True)
        (repo / "src" / "a.c").write_bytes(SRC_V1.encode())
        g = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false"]
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(g + ["add", "."], check=True)
        subprocess.run(g + ["commit", "-qm", "v1"], check=True)
        subprocess.run(g + ["tag", "v1"], check=True)
        (repo / "src" / "a.c").write_text("/* working tree, not v1 */\n" * 20)
        fj = work / "findings.json"
        wjson(fj, FINDINGS)
        common = ["--issues", fj, "--git-repo", repo, "--tag", "v1", "--strip-prefix", ROOT]

        p = run(TOOLS / "bundle.py", *common, "--per-checker", "1", "--plan")
        assert "selected: 8" in p.stdout and not (work / "b").exists(), p.stdout
        run(TOOLS / "bundle.py", *common, "--plan", ok=False)          # nothing selected
        run(TOOLS / "bundle.py", *common, "--merge-key", "nope", "--plan", ok=False)
        # One source per run: git by default, the idir only as the backup.
        no_src = ["--issues", fj, "--strip-prefix", ROOT, "--all", "--out", work / "x"]
        run(TOOLS / "bundle.py", *no_src, ok=False)                                # no source
        run(TOOLS / "bundle.py", *no_src, "--git-repo", repo, "--tag", "v1",
            "--idir", work, "--cov-bin", work, ok=False)                           # both
        run(TOOLS / "bundle.py", *no_src, "--idir", work, ok=False)                # no --cov-bin
        run(TOOLS / "bundle.py", *no_src, "--git-repo", repo, ok=False)            # no --tag
        assert not (work / "x").exists(), "a refused run wrote bundles"

        b = work / "b"
        run(TOOLS / "bundle.py", *common, "--per-checker", "1", "--out", b)
        index = json.loads((b / "index.json").read_text())
        assert index["source"] == {"mode": "git", "repo": str(repo), "rev": "v1"}, index["source"]
        assert [x["mergeKey"] for x in index["bundles"]] == \
            ["k7", "k3", "k4", "k2", "k6", "k5", "k1", "k8"], index
        k2 = next(x for x in index["bundles"] if x["mergeKey"] == "k2")
        assert [s["line"] for s in k2["sites"]] == [10, 11], k2
        nr = (b / next(x["bundle"] for x in index["bundles"] if x["mergeKey"] == "k1")).read_text()
        assert ">>     6      return p[1];" in nr, "form feed shifted the excerpt, or read the working tree"
        assert "working tree" not in nr
        fn = (b / k2["bundle"]).read_text()
        assert "Reported at 2 sites" in fn and ">>    11  int h" in fn, fn

        # --- Step 2: lanes from the checker table --------------------------------
        run(TOOLS / "lanes.py", "check-table", HERE.parent / "references" / "checker-lanes.json")
        ct = work / "custom-table.json"
        wjson(ct, CUSTOM_TABLE)
        run(TOOLS / "lanes.py", "check-table", ct)
        for name, row in [("both", {"lane": "Intent", "lanes": ["Intent", "Contract"], "why": "x"}),
                          ("neither", {"why": "x"}),
                          ("bad-lane", {"lane": "Path", "why": "x"}),
                          ("one-candidate", {"lanes": ["Intent"], "decide": "x"}),
                          ("policy-candidate", {"lanes": ["Intent", "Policy"], "decide": "x"}),
                          ("no-decide", {"lanes": ["Intent", "Contract"]}),
                          ("no-why", {"lane": "Intent"}),
                          ("policy-method", {"lane": "Policy", "why": "x", "method": "Human"}),
                          ("none-method", {"lane": "Intent", "why": "x", "method": "None"}),
                          ("route-no-verify", {"lane": "Intent", "why": "x", "route": "harness"}),
                          ("bad-route", {"lane": "Value or path", "why": "x",
                                         "method": "Execution: coverity-verify", "route": "fast"})]:
            bad = work / ("bad-" + name + ".json")
            wjson(bad, dict(CUSTOM_TABLE, checkers={"X": row}))
            run(TOOLS / "lanes.py", "check-table", bad, ok=False)

        l0 = work / "lanes-no-custom.json"
        out = run(TOOLS / "lanes.py", "assign", "--bundles", b, "--out", l0).stdout
        assert "1 need inference" in out and "1 unplaced" in out and "ACME_SHAPE" in out, out
        doc0 = json.loads(l0.read_text())
        assert {e["mergeKey"] for e in doc0["pending"]} == {"k5", "k7"}, doc0
        assert next(e for e in doc0["pending"] if e["mergeKey"] == "k7")["unplaced"] is True
        lt = work / "lanes-table.json"
        out = run(TOOLS / "lanes.py", "assign", "--bundles", b, "--table", ct, "--out", lt).stdout
        assert "7 lane(s) from the checker table" in out and "0 unplaced" in out, out
        tdoc = json.loads(lt.read_text())
        by = {e["mergeKey"]: e for e in tdoc["lanes"]}
        assert by["k4"]["lane"] == "Intent" and by["k6"]["lane"] == "Policy"
        assert by["k8"]["lane"] == "Other" and by["k1"]["lane"] == "Contract"
        assert by["k7"]["method"] == "Execution: coverity-verify" and by["k7"]["route"] == "harness"
        assert all(e["assigned_by"] == "checker table" for e in tdoc["lanes"])
        (k5p,) = tdoc["pending"]
        assert k5p["candidates"] == ["Contract", "Value or path"], k5p
        # Inference chooses among the candidates for the one finding left pending.
        inferred = dict(k5p, lane="Value or path", assigned_by="LLM: Sonnet 5.5",
                        reason="p[1] is a value tested along the path, not a callee's return")
        inferred.pop("decide")
        lanes = dict(tdoc, lanes=tdoc["lanes"] + [inferred], pending=[])

        runj = {"date": "2026-10-28", "selection": "per-checker sample of 1",
                "assigner": "LLM: Sonnet 5.5", "who": "test", "connect_ai_triage": False,
                "lanes": {"Construction": "None", "Intent": "LLM: Sonnet 5.5",
                          "Contract": "LLM: Sonnet 5.5", "Value or path": "Human"}}
        verdicts = {"lane": "Contract", "method": "LLM: Sonnet 5.5", "model": "test-model",
                    "verdicts": [GOOD_INVARIANT,
                                 {"mergeKey": "k3", "verdict": "real, low severity",
                                  "reason": "ignored; cosmetic at src/a.c:5"}]}
        intent = {"lane": "Intent", "method": "LLM: Sonnet 5.5", "model": "test-model",
                  "verdicts": [{"mergeKey": "k4", "verdict": "false positive - heuristic misfire",
                                "reason": "the two checks at src/a.c:4 are distinct by design"}]}
        executed_k7 = {"lane": "Value or path", "method": "Execution: coverity-verify",
                       "model": None, "verdicts": [{
                           "mergeKey": "k7", "verdict": "real", "executed": True,
                           "reason": "crash at src/a.c:10 with q NULL; 412 reaches in 60 s",
                           "route": "harness", "route_reason": "the TU compiles as captured",
                           "as_code": ["g", "h"], "stubbed": []}]}
        good_v = [verdicts, intent, executed_k7]

        def attempt(name, lanes_doc, run_doc, vdocs, ok, extra=()):
            d = work / name
            (d / "v").mkdir(parents=True)
            wjson(d / "lanes.json", lanes_doc)
            wjson(d / "run.json", run_doc)
            for i, v in enumerate(vdocs):
                wjson(d / "v" / ("%d.json" % i), v)
            run(TOOLS / "records.py", "assemble", "--bundles", b, "--lanes", d / "lanes.json",
                "--verdicts", d / "v", "--run", d / "run.json", "--out", d / "triage.json",
                *extra, ok=ok)
            assert (d / "triage.json").exists() == ok, name + ": wrote output on refusal"
            return d

        d = attempt("good", lanes, runj, good_v, True)
        run(TOOLS / "records.py", "validate", d / "triage.json")
        recs = {r["mergeKey"]: r for r in json.loads((d / "triage.json").read_text())["records"]}
        assert recs["k1"]["triageState"]["classification"] == "False Positive"
        assert "Enforced at: src/a.c:4" in recs["k1"]["triageState"]["comment"]
        assert "assigned by checker table" in recs["k1"]["triageState"]["comment"]
        assert recs["k3"]["triageState"]["severity"] == "Minor"
        assert recs["k4"]["lane"] == "Intent" and recs["k4"]["triageState"]["classification"] == "False Positive"
        assert recs["k2"]["method"] == "Human" and recs["k2"]["verdict"] is None
        assert recs["k2"]["evidence"]["status"].startswith("awaiting")
        assert len(recs["k2"]["judged"]["sites"]) == 2
        assert recs["k5"]["lane_assigned_by"] == "LLM: Sonnet 5.5"
        assert recs["k6"]["triageState"] == {"classification": None, "action": None,
                                             "severity": None, "comment": None,
                                             "customTriage": {"Defect Category": "Policy",
                                                              "Triage Method": "None"}}
        assert recs["k6"]["evidence"]["status"] == "not triaged: Policy"
        assert recs["k8"]["lane"] == "Other" and recs["k8"]["method"] == "None"
        # The checker's own method wins over the lane's (Value or path is Human in this plan).
        assert recs["k7"]["method"] == "Execution: coverity-verify", recs["k7"]
        assert "checker's own method" in recs["k7"]["method_reason"]
        assert recs["k7"]["evidence"]["route"] == "harness" and recs["k7"]["evidence"]["as_code"] == ["g", "h"]
        assert recs["k7"]["evidence"]["route_preference"] == "harness"
        report = (d / "TRIAGE-REPORT.md").read_text()
        assert "## By lane" in report and "not triaged (Policy)" in report, report
        assert "7 from the checker table" in report, report

        # A route chosen for the whole plan beats the row's preference.
        d = attempt("plan-route", lanes, dict(runj, verify_route="extraction"), good_v, True)
        recs = {r["mergeKey"]: r for r in json.loads((d / "triage.json").read_text())["records"]}
        assert recs["k7"]["evidence"]["route_preference"] == "extraction"

        def with_v(**kw):
            v = dict(GOOD_INVARIANT, **kw)
            return [dict(verdicts, verdicts=[v, verdicts["verdicts"][1]]), intent, executed_k7]

        def with_lane(mk, **kw):
            return dict(lanes, lanes=[dict(a, **kw) if a["mergeKey"] == mk else a
                                      for a in lanes["lanes"]])

        refusals = 0

        def refuse(name, lanes_doc, run_doc, vdocs):
            nonlocal refusals
            refusals += 1
            attempt(name, lanes_doc, run_doc, vdocs, False)

        refuse("no-location", lanes, runj, with_v(enforced_at=""))
        refuse("bad-word", lanes, runj, with_v(verdict="probably fine"))
        refuse("control-char", lanes, runj, with_v(reason="the literal '\x00' at src/a.c:5"))
        refuse("missing-verdict", lanes, runj, [dict(verdicts, verdicts=[GOOD_INVARIANT]),
                                                intent, executed_k7])
        refuse("wrong-lane", with_lane("k3", lane="Value or path"), runj, good_v)
        refuse("unassigned", dict(lanes, lanes=lanes["lanes"][1:]), runj, good_v)
        refuse("bad-lane", with_lane("k1", lane="Path"), runj, good_v)
        refuse("pending-left", dict(lanes, pending=[k5p]), runj, good_v)
        refuse("outside-candidates", with_lane("k5", lane="Intent"), runj, good_v)
        refuse("another-assigner", with_lane("k5", assigned_by="LLM: Opus 5.5"), runj, good_v)
        refuse("table-with-candidates", with_lane("k5", assigned_by="checker table"), runj, good_v)
        refuse("other-verdict", lanes, runj, good_v + [{
            "lane": "Other", "method": "Human", "model": None,
            "verdicts": [{"mergeKey": "k8", "verdict": "real", "reason": "x"}]}])
        refuse("policy-verdict", lanes, runj, good_v + [{
            "lane": "Policy", "method": "Human", "model": None,
            "verdicts": [{"mergeKey": "k6", "verdict": "real", "reason": "x"}]}])
        refuse("policy-override", lanes, dict(runj, overrides=[
            {"mergeKey": "k6", "method": "Human", "reason": "a person wants to look"}]), good_v)
        refuse("plan-without-intent", lanes,
               dict(runj, lanes={k: v for k, v in runj["lanes"].items() if k != "Intent"}), good_v)
        refuse("plan-lists-policy", lanes, dict(runj, lanes=dict(runj["lanes"], Policy="None")), good_v)
        refuse("bad-route", lanes, dict(runj, verify_route="fast"), good_v)
        refuse("method-mismatch", lanes, runj, [dict(verdicts, method="LLM: Opus 5.5"),
                                                intent, executed_k7])
        refuse("executed-by-reader", lanes, runj, with_v(executed=True))
        # By-catch never rides in a verdict, as a field or in the usual phrasing.
        refuse("bycatch-field", lanes, runj, with_v(bycatch=[{"site": "src/a.c:10"}]))
        refuse("bycatch-words", lanes, runj, with_v(
            reason=GOOD_INVARIANT["reason"] + " Side observation: src/a.c:10 looks wrong too."))

        # By-catch goes to its own folder: checked, collected into bycatch.json,
        # announced on stdout, and absent from triage.json and the report.
        claim = "UNIQUE-BYCATCH-CLAIM at src/a.c:10"
        item = {"site": "src/a.c:10", "claim": claim, "noticed_while": "k1",
                "sites_read": ["src/a.c:10-11"]}

        def bycatch_dir(name, items, noticed_by="LLM: Sonnet 5.5"):
            bd = work / ("bc-" + name)
            bd.mkdir()
            wjson(bd / "Contract-1.json", {"noticed_by": noticed_by, "model": "test-model",
                                           "items": items})
            return bd

        bd = bycatch_dir("good", [item])
        d = attempt("bycatch-good", lanes, runj, good_v, True, extra=("--bycatch-dir", bd))
        bj = json.loads((bd / "bycatch.json").read_text())
        assert bj["format"] == "coverity-triage-bycatch" and bj["items"][0]["claim"] == claim, bj
        assert bj["items"][0]["file"] == "Contract-1.json"
        for f in ("triage.json", "TRIAGE-REPORT.md"):
            text = (d / f).read_text().lower()
            assert claim.lower() not in text and "by-catch" not in text and "bycatch" not in text, f
        out = run(TOOLS / "records.py", "assemble", "--bundles", b, "--lanes", d / "lanes.json",
                  "--verdicts", d / "v", "--run", d / "run.json", "--out", d / "again.json",
                  "--bycatch-dir", bd).stdout
        assert "by-catch: 1 item(s) in" in out, out
        out = run(TOOLS / "records.py", "assemble", "--bundles", b, "--lanes", d / "lanes.json",
                  "--verdicts", d / "v", "--run", d / "run.json", "--out", d / "none.json").stdout
        assert "by-catch: none" in out, out

        def refuse_bc(name, bd):
            nonlocal refusals
            refusals += 1
            attempt(name, lanes, runj, good_v, False, extra=("--bycatch-dir", bd))
            assert not (bd / "bycatch.json").exists(), name + ": wrote bycatch.json on refusal"

        refuse_bc("bycatch-no-claim", bycatch_dir("no-claim", [dict(item, claim="")]))
        refuse_bc("bycatch-unknown-finding", bycatch_dir("unknown", [dict(item, noticed_while="k99")]))
        refuse_bc("bycatch-no-noticer", bycatch_dir("no-noticer", [item], noticed_by="None"))
        # The default folder is <bundles>/bycatch/.
        (b / "bycatch").mkdir()
        wjson(b / "bycatch" / "Contract-1.json", {"noticed_by": "LLM: Sonnet 5.5", "items": [item]})
        attempt("bycatch-default", lanes, runj, good_v, True)
        assert json.loads((b / "bycatch" / "bycatch.json").read_text())["items"][0]["claim"] == claim
        shutil.rmtree(b / "bycatch")

        # No lane restricts methods: verify on the Contract lane is a plan's choice.
        exec_contract = {"lane": "Contract", "method": "Execution: coverity-verify", "model": None,
                         "verdicts": [dict(GOOD_INVARIANT, executed=True),
                                      {"mergeKey": "k3", "verdict": "real", "executed": True,
                                       "reason": "the error path at src/a.c:5 crashes"}]}
        d = attempt("execution-in-contract", lanes,
                    dict(runj, lanes=dict(runj["lanes"], Contract="Execution: coverity-verify")),
                    [exec_contract, intent, executed_k7], True)
        run(TOOLS / "records.py", "validate", d / "triage.json")

        # A caller that expects one lane (value or path, run through verify): an
        # off-lane finding needs the user's recorded choice before anything runs.
        # k7 is not off-lane (its checker's own method is the expected one), and
        # k6 is Policy, which has no choice to make.
        exp_run = dict(runj, expected={"by": "test producer", "lane": "Value or path",
                                       "method": "Execution: coverity-verify"},
                       lanes=dict(runj["lanes"], **{"Value or path": "Execution: coverity-verify"}))
        executed_k5 = {"lane": "Value or path", "method": "Execution: coverity-verify",
                       "model": None, "verdicts": [{
                           "mergeKey": "k5", "verdict": "unresolved", "executed": True,
                           "reason": "unconfirmed after 60 s"}]}
        executed_k2 = dict(executed_k5, verdicts=[{
            "mergeKey": "k2", "verdict": "real", "executed": True, "reason": "crash at src/a.c:10"}])
        exec_k1 = {"lane": "Contract", "method": "Execution: coverity-verify", "model": None,
                   "verdicts": [dict(GOOD_INVARIANT, executed=True)]}
        read_k3 = dict(verdicts, verdicts=[verdicts["verdicts"][1]])
        exp_v = [executed_k5, executed_k2, executed_k7, exec_k1, read_k3, intent]
        refuse("off-lane-unchosen", lanes, exp_run, exp_v)
        chosen = dict(exp_run, overrides=[
            {"mergeKey": "k1", "method": "Execution: coverity-verify",
             "reason": "assigned Contract; user chose to run it anyway"},
            {"mergeKey": "k3", "method": "LLM: Sonnet 5.5",
             "reason": "assigned Contract; user chose the contract reader"},
            {"mergeKey": "k4", "method": "LLM: Sonnet 5.5",
             "reason": "assigned Intent; user chose the intent reader"},
            {"mergeKey": "k8", "method": "None",
             "reason": "assigned Other; user chose to leave it untriaged"}])
        d = attempt("off-lane-chosen", lanes, chosen, exp_v, True)
        recs = {r["mergeKey"]: r for r in json.loads((d / "triage.json").read_text())["records"]}
        assert recs["k1"]["method"] == "Execution: coverity-verify" and recs["k1"]["lane"] == "Contract"
        assert "run it anyway" in recs["k1"]["method_reason"]
        assert recs["k8"]["method"] == "None" and recs["k8"]["verdict"] is None
        assert recs["k2"]["triageState"]["customTriage"]["Triage Method"] == "Execution: coverity-verify"
        run(TOOLS / "records.py", "validate", d / "triage.json")
        refuse("override-no-reason", lanes,
               dict(chosen, overrides=[dict(o, reason="") if o["mergeKey"] == "k1" else o
                                       for o in chosen["overrides"]]), exp_v)
        refuse("override-route-not-verify", lanes,
               dict(chosen, overrides=[dict(o, route="harness") if o["mergeKey"] == "k3" else o
                                       for o in chosen["overrides"]]), exp_v)
        cl = run(TOOLS / "records.py", "check-lanes", "--bundles", b, "--lanes",
                 d / "lanes.json", "--run", work / "off-lane-unchosen" / "run.json").stdout
        assert "4 finding(s) landed elsewhere" in cl and cl.count("not chosen yet") == 4, cl
        assert "1 in Policy" in cl, cl

        long_reason = "x" * 5000
        d = attempt("long", lanes, runj, with_v(reason=long_reason), True)
        c = next(r for r in json.loads((d / "triage.json").read_text())["records"]
                 if r["mergeKey"] == "k1")["triageState"]["comment"]
        assert len(c) <= 4000 and "shortened" in c

        print("ok: bundle plan, bundles (git at the tag, form feed, two sites), 6 bundle refusals, "
              "the checker table and 11 bad rows, lanes from the table (fixed, candidates, "
              "unplaced, a producer's row), one assembly, a plan-level route, "
              + str(refusals) + " records refusals, verify in the Contract lane, expected-lane "
              "overrides, check-lanes, shortened comment")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
