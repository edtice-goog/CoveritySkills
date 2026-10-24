#!/usr/bin/env python3
"""Exercise tools/bundle.py and tools/records.py on a generated fixture.

    python3 -I evals/test_tools.py

Builds a throwaway git repository (one C file with a form feed in it, tagged
v1, then changed in the working tree so a working-tree read would be wrong),
a cov-format-errors-shaped findings file with four merge keys (one reported
at two sites), and runs: the plan, the bundles, one good assembly, and one
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
]}


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
        assert "selected: 4" in p.stdout and not (work / "b").exists(), p.stdout
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
        assert [x["mergeKey"] for x in index["bundles"]] == ["k3", "k4", "k2", "k1"], index
        k2 = next(x for x in index["bundles"] if x["mergeKey"] == "k2")
        assert [s["line"] for s in k2["sites"]] == [10, 11], k2
        nr = (b / next(x["bundle"] for x in index["bundles"] if x["mergeKey"] == "k1")).read_text()
        assert ">>     6      return p[1];" in nr, "form feed shifted the excerpt, or read the working tree"
        assert "working tree" not in nr
        fn = (b / k2["bundle"]).read_text()
        assert "Reported at 2 sites" in fn and ">>    11  int h" in fn, fn

        lanes = {"assigned_by": "LLM: Sonnet 5.5", "lanes": [
            {"mergeKey": "k1", "lane": "Contract", "reason": "statistical evidence on strchr"},
            {"mergeKey": "k2", "lane": "Value or path", "reason": "null reaches a dereference"},
            {"mergeKey": "k3", "lane": "Contract", "reason": "ignored return"},
            {"mergeKey": "k4", "lane": "Other", "reason": "a shape claim about copying"}]}
        runj = {"date": "2026-10-24", "selection": "per-checker sample of 1",
                "assigner": "LLM: Sonnet 5.5", "who": "test", "connect_ai_triage": False,
                "lanes": {"Construction": "None", "Contract": "LLM: Sonnet 5.5",
                          "Value or path": "Human"}}
        verdicts = {"lane": "Contract", "method": "LLM: Sonnet 5.5", "model": "test-model",
                    "verdicts": [GOOD_INVARIANT,
                                 {"mergeKey": "k3", "verdict": "real, low severity",
                                  "reason": "ignored; cosmetic at src/a.c:5"}]}

        def attempt(name, lanes_doc, run_doc, vdocs, ok):
            d = work / name
            (d / "v").mkdir(parents=True)
            wjson(d / "lanes.json", lanes_doc)
            wjson(d / "run.json", run_doc)
            for i, v in enumerate(vdocs):
                wjson(d / "v" / ("%d.json" % i), v)
            run(TOOLS / "records.py", "assemble", "--bundles", b, "--lanes", d / "lanes.json",
                "--verdicts", d / "v", "--run", d / "run.json", "--out", d / "triage.json", ok=ok)
            assert (d / "triage.json").exists() == ok, name + ": wrote output on refusal"
            return d

        d = attempt("good", lanes, runj, [verdicts], True)
        run(TOOLS / "records.py", "validate", d / "triage.json")
        recs = {r["mergeKey"]: r for r in json.loads((d / "triage.json").read_text())["records"]}
        assert recs["k1"]["triageState"]["classification"] == "False Positive"
        assert "Enforced at: src/a.c:4" in recs["k1"]["triageState"]["comment"]
        assert recs["k3"]["triageState"]["severity"] == "Minor"
        assert recs["k2"]["method"] == "Human" and recs["k2"]["verdict"] is None
        assert recs["k2"]["evidence"]["status"].startswith("awaiting")
        assert len(recs["k2"]["judged"]["sites"]) == 2
        assert recs["k4"]["triageState"] == {"classification": None, "action": None,
                                             "severity": None, "comment": None,
                                             "customTriage": {"Triage lane": "Other",
                                                              "Triage method": "None"}}
        assert "## By lane" in (d / "TRIAGE-REPORT.md").read_text()

        def with_v(**kw):
            v = dict(GOOD_INVARIANT, **kw)
            return [dict(verdicts, verdicts=[v, verdicts["verdicts"][1]])]

        attempt("no-location", lanes, runj, with_v(enforced_at=""), False)
        attempt("bad-word", lanes, runj, with_v(verdict="probably fine"), False)
        attempt("control-char", lanes, runj, with_v(reason="the literal '\x00' at src/a.c:5"), False)
        attempt("missing-verdict", lanes, runj,
                [dict(verdicts, verdicts=[GOOD_INVARIANT])], False)
        attempt("wrong-lane", dict(lanes, lanes=[dict(a, lane="Value or path")
                                                 if a["mergeKey"] == "k3" else a
                                                 for a in lanes["lanes"]]),
                runj, [verdicts], False)
        attempt("unassigned", dict(lanes, lanes=lanes["lanes"][1:]), runj, [verdicts], False)
        attempt("bad-lane", dict(lanes, lanes=[dict(lanes["lanes"][0], lane="Path")]
                                 + lanes["lanes"][1:]), runj, [verdicts], False)
        attempt("other-verdict", lanes, runj, [verdicts, {
            "lane": "Value or path", "method": "Human", "model": None,
            "verdicts": [{"mergeKey": "k4", "verdict": "real", "reason": "x"}]}], False)
        attempt("method-mismatch", lanes, runj, [dict(verdicts, method="LLM: Opus 5.5")], False)
        attempt("execution-in-contract", lanes,
                dict(runj, lanes=dict(runj["lanes"], Contract="Execution: coverity-verify")),
                [verdicts], False)
        attempt("executed-by-reader", lanes, runj, with_v(executed=True), False)
        # A caller that expects one lane (value or path, run through verify):
        # off-lane findings need the user's recorded choice before anything runs.
        exp_run = dict(runj, expected={"by": "test producer", "lane": "Value or path",
                                       "method": "Execution: coverity-verify"},
                       lanes={"Construction": "None", "Contract": "LLM: Sonnet 5.5",
                              "Value or path": "Execution: coverity-verify"})
        executed_k2 = {"lane": "Value or path", "method": "Execution: coverity-verify",
                       "model": None, "verdicts": [{
                           "mergeKey": "k2", "verdict": "real", "executed": True,
                           "reason": "crash at src/a.c:10 with q NULL; 412 reaches in 60 s"}]}
        executed_k1 = {"lane": "Contract", "method": "Execution: coverity-verify", "model": None,
                       "verdicts": [dict(GOOD_INVARIANT, executed=True)]}
        read_k3 = dict(verdicts, verdicts=[verdicts["verdicts"][1]])
        attempt("off-lane-unchosen", lanes, exp_run, [executed_k2, executed_k1, read_k3], False)
        chosen = dict(exp_run, overrides=[
            {"mergeKey": "k1", "method": "Execution: coverity-verify",
             "reason": "assigned Contract; user chose to run it anyway"},
            {"mergeKey": "k3", "method": "LLM: Sonnet 5.5",
             "reason": "assigned Contract; user chose the contract reader"},
            {"mergeKey": "k4", "method": "None",
             "reason": "assigned Other; user chose to leave it untriaged"}])
        d = attempt("off-lane-chosen", lanes, chosen, [executed_k2, executed_k1, read_k3], True)
        recs = {r["mergeKey"]: r for r in json.loads((d / "triage.json").read_text())["records"]}
        assert recs["k1"]["method"] == "Execution: coverity-verify" and recs["k1"]["lane"] == "Contract"
        assert "run it anyway" in recs["k1"]["method_reason"]
        assert recs["k4"]["method"] == "None" and recs["k4"]["verdict"] is None
        assert recs["k2"]["triageState"]["customTriage"]["Triage method"] == "Execution: coverity-verify"
        run(TOOLS / "records.py", "validate", d / "triage.json")
        attempt("override-no-reason", lanes,
                dict(chosen, overrides=[dict(o, reason="") if o["mergeKey"] == "k1" else o
                                        for o in chosen["overrides"]]),
                [executed_k2, executed_k1, read_k3], False)
        cl = run(TOOLS / "records.py", "check-lanes", "--bundles", b, "--lanes",
                 d / "lanes.json", "--run", work / "off-lane-unchosen" / "run.json").stdout
        assert "3 finding(s) landed elsewhere" in cl and cl.count("not chosen yet") == 3, cl

        long_reason = "x" * 5000
        d = attempt("long", lanes, runj, with_v(reason=long_reason), True)
        c = json.loads((d / "triage.json").read_text())["records"][-1]["triageState"]["comment"]
        assert len(c) <= 4000 and "shortened" in c

        print("ok: bundle plan, bundles (git at the tag, form feed, two sites), 6 bundle refusals, "
              "one assembly, 13 records refusals, expected-lane overrides, check-lanes, "
              "shortened comment")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
