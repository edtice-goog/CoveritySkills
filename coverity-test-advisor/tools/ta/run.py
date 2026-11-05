"""Test Advisor on any base/head pair: the driver.

    python3 -m ta.run analyze --base-idir B --head-idir H --base-commit SHA --head-commit SHA --repo DIR \\
        --coverage PATH --coverage-format gcov|jacoco --cov-bin DIR --out DIR [--java-root R]... [--diff-path P]...
    python3 -m ta.run finish --out DIR [--cov-bin DIR]

analyze runs the preflight, dumps both idirs' models, maps the diff, walks the call graph, joins the coverage,
applies the fixed rules and writes OUT/packets/*.md, OUT/analysis.json and OUT/judge.txt (the functions left for the
judge, which follows the judge brief, references/judge-brief.md, and writes OUT/verdicts.json), then stops. finish turns the verdicts into
OUT/report.md, OUT/report.json, OUT/TA.INSUFFICIENT_TEST_COVERAGE.errors.xml and OUT/ta-idirs/head (a copy of the head
idir with the issues imported). Without OUT/verdicts.json, finish writes one that marks every function the judge
did not see as NOT_JUDGED (reported, no defect).

--coverage is a directory of gcov JSON files (`gcov --json-format --conditions`, .gcov.json or .gcov.json.gz) or a
JaCoCo XML report. --java-root (repeatable, default src/main/java) is where JaCoCo's packages live in the repository.
--diff-path (repeatable) limits the diff; the default is the directories the capture compiled sources from.

Every run writes OUT/status.json and ends with one line `TA-STATUS: <status> <reason>`. Exit codes:
    0 ok        analysis written, no warnings
    1 warned    analysis written; the preflight warned (see status.json and the report)
    2 usage     bad arguments
    3 refused   the inputs are inconsistent (options differ, an idir is not from its commit, coverage does not match)
    4 gate      a Coverity version the cross-reference reader is not checked on (2026.9.0 only)
    5 cxx       C++ sources: calls through a base class are not expanded for C++ yet
"""
import argparse
import json
import os
import subprocess
import sys

from . import changes, coverage, output, preflight
from .analyze import analyze as run_analysis
from .inputs import LANG_FLAGS, Version

EXIT = {"ok": 0, "warned": 1, "usage": 2, "refused": 3, "gate": 4, "cxx": 5}


def sh(*args, **kw):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kw).stdout


class RunDataset:
    """What analyze and output.finish need about a run, from the command line."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.name = cfg["name"]
        self.language = cfg["language"]
        self.work = cfg["out"]
        self.clone, self.cov_bin = cfg["repo"], cfg["cov_bin"]
        self.diff_paths = tuple(cfg["diff_paths"])
        self.encoding = "UTF-8"
        self.coverage_type = cfg["coverage_format"]
        self.per_test_note = None
        self.flags = LANG_FLAGS[self.language]

    def prepare(self, label):
        side = self.cfg[label]
        v = Version(self, label, side["idir"], f"{self.work}/models/{label}", side["sha"], side["capture_root"],
                    self.cfg.get("coverage_root") or side["capture_root"], label, {})
        if not os.path.exists(f"{v.dump}/list.txt"):
            os.makedirs(v.dump, exist_ok=True)
            out = sh(f"{self.cov_bin}/cov-find-function", "--dir", v.idir, *self.flags["find"], "--save", "-of",
                     v.dump, ".", cwd=v.dump)
            open(f"{v.dump}/list.txt", "w").write(out)
        return v

    def load_coverage(self, v):
        return load_coverage(self.cfg), {}


def load_coverage(cfg):
    if cfg["coverage_format"] == "gcov":
        return coverage.load(cfg["coverage"], cfg["coverage_root"])
    roots = cfg["java_roots"]
    cov = coverage.load_jacoco(cfg["coverage"], roots[0])
    files = set(cfg["head_files"])
    for key in [k for k in list(cov.lines) if k not in files]:   # a package under another source root
        rest = key[len(roots[0]) + 1:]
        for r in roots[1:]:
            if f"{r}/{rest}" in files:
                cov.lines[f"{r}/{rest}"] = cov.lines.pop(key)
                if key in cov.functions:
                    cov.functions[f"{r}/{rest}"] = cov.functions.pop(key)
                break
    return cov


def gcov_paths(cov_dir):
    """Every source path a gcov JSON directory names, absolute (joined to its working directory)."""
    import glob
    import gzip
    out = []
    for p in glob.glob(f"{cov_dir}/**/*.gcov.json*", recursive=True):
        d = json.load(gzip.open(p) if p.endswith(".gz") else open(p))
        cwd = d.get("current_working_directory", "")
        out += [os.path.normpath(os.path.join(cwd, f["file"])) for f in d.get("files", [])]
    return out


def finish_status(out, status, reason, checks, extra=None):
    doc = {"status": status, "exit": EXIT[status], "reason": reason, "checks": [c.as_dict() for c in checks]}
    doc.update(extra or {})
    os.makedirs(out, exist_ok=True)
    json.dump(doc, open(f"{out}/status.json", "w"), indent=1)
    for c in checks:
        print(f"  {c.result:6} {c.name}: {c.detail}")
    print(f"TA-STATUS: {status} {reason}")
    sys.exit(EXIT[status])


def analyze(args):
    for flag in ("base_idir", "head_idir", "repo", "coverage", "cov_bin"):
        if not os.path.exists(getattr(args, flag)):
            finish_status(args.out, "usage", f"--{flag.replace('_', '-')} {getattr(args, flag)} does not exist", [])
    try:
        args.base_commit = sh("git", "-C", args.repo, "rev-parse", f"{args.base_commit}^{{commit}}").strip()
        args.head_commit = sh("git", "-C", args.repo, "rev-parse", f"{args.head_commit}^{{commit}}").strip()
    except subprocess.CalledProcessError as e:
        finish_status(args.out, "usage", f"not a commit in {args.repo}: {e.stderr.strip()}", [])
    changed = set(sh("git", "-C", args.repo, "diff", "--name-only", args.base_commit, args.head_commit).split())

    checks, facts = preflight.run(args, changed)
    worst = next((c for c in checks if c.result in ("gate", "cxx", "refuse")), None)
    if worst:
        finish_status(args.out, {"gate": "gate", "cxx": "cxx", "refuse": "refused"}[worst.result],
                      f"{worst.name}: {worst.detail}", checks)

    lang, roots = facts["language"], facts["capture_roots"]
    head_files = sorted(preflight.git_files(args.repo, args.head_commit))
    java_roots = args.java_root or ["src/main/java"]
    if args.diff_path:
        diff_paths = args.diff_path
    elif lang == "java":
        diff_paths = [r for r in java_roots if any(f.startswith(r + "/") for f in head_files)]
    else:
        tus = preflight.list_json(args.cov_bin, args.head_idir)
        diff_paths = sorted({t["primaryFilename"][len(roots["head"]) + 1:].split("/")[0] for t in tus
                             if t["primaryFilename"].startswith(roots["head"] + "/")})
    cfg = {"name": os.path.basename(os.path.abspath(args.repo)), "language": lang, "out": os.path.abspath(args.out),
           "repo": os.path.abspath(args.repo), "cov_bin": args.cov_bin, "diff_paths": diff_paths,
           "coverage": os.path.abspath(args.coverage), "coverage_format": args.coverage_format,
           "java_roots": java_roots, "head_files": head_files,
           "base": {"idir": os.path.abspath(args.base_idir), "sha": args.base_commit, "capture_root": roots["base"]},
           "head": {"idir": os.path.abspath(args.head_idir), "sha": args.head_commit, "capture_root": roots["head"]}}
    if args.coverage_format == "gcov":
        root = preflight.infer_root(gcov_paths(args.coverage), set(head_files))
        if root is None:
            checks.append(preflight.Check("coverage root", "refuse",
                                          "no file in the gcov JSON exists in the repository at the head commit"))
            finish_status(args.out, "refused", "coverage root: no gcov file matches the repository", checks)
        cfg["coverage_root"] = root

    cov = load_coverage(cfg)
    head_fns = changes.functions(args.head_idir, [roots["head"]])
    # A file whose only "function" is a Java static initializer of constants (an interface of constants) has no
    # bytecode JaCoCo can measure: the compiler inlines the constants. It is not a coverage gap.
    real = [f for f in head_fns if not (lang == "java" and f.name.endswith((".<clinit>()", "<clinit>")))]
    captured = {f.file for f in real if any(f.file.startswith(p.rstrip("/") + "/") for p in diff_paths)}
    checks += preflight.coverage_checks(cov, captured, head_fns, args.coverage_format == "gcov")
    worst = next((c for c in checks if c.result == "refuse"), None)
    if worst:
        finish_status(args.out, "refused", f"{worst.name}: {worst.detail}", checks)

    os.makedirs(args.out, exist_ok=True)
    json.dump(cfg, open(f"{args.out}/run.json", "w"), indent=1)
    run_analysis(RunDataset(cfg), "base", "head", os.path.abspath(args.out))
    judge = [l for l in open(f"{args.out}/judge.txt") if l.strip()]
    warned = [c for c in checks if c.result == "warn"]
    status = "warned" if warned else "ok"
    finish_status(args.out, status, f"{len(judge)} functions left for the judge (judge.txt)"
                  + (f"; {len(warned)} warning(s)" if warned else ""), checks,
                  {"judge": len(judge), "language": lang, "coverity_version": facts.get("coverity_version")})


def finish(args):
    cfg_path = f"{args.out}/run.json"
    if not os.path.exists(cfg_path):
        finish_status(args.out, "usage", f"{cfg_path} missing: run analyze first", [])
    cfg = json.load(open(cfg_path))
    if args.cov_bin:
        cfg["cov_bin"] = args.cov_bin
    vpath = f"{args.out}/verdicts.json"
    if not os.path.exists(vpath):
        json.dump({"_unjudged": "omit", "_unjudged_reason": "no verdicts were given: finish ran without the judge",
                   "_judge": "not judged: finish ran without verdicts"}, open(vpath, "w"))
    output.finish(os.path.abspath(args.out), RunDataset(cfg))
    xml = f"{args.out}/{output.CHECKER}.errors.xml"
    issues = open(xml).read().count("<error>") if os.path.exists(xml) else 0
    verdicts = json.load(open(f"{args.out}/report.json"))["verdicts"].values()
    unjudged = sum(1 for v in verdicts if v["verdict"] == "NOT_JUDGED")
    print("TA-STATUS: ok report.md and report.json written; "
          + (f"{output.plural(issues, 'issue')} in {output.CHECKER}.errors.xml and {args.out}/ta-idirs/head" if issues
             else "no issues, so no errors.xml")
          + (f"; {output.plural(unjudged, 'function')} not judged" if unjudged else ""))
    sys.exit(0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze")
    for flag in ("base-idir", "head-idir", "base-commit", "head-commit", "repo", "coverage", "cov-bin", "out"):
        a.add_argument(f"--{flag}", required=True)
    a.add_argument("--coverage-format", required=True, choices=("gcov", "jacoco"))
    a.add_argument("--java-root", action="append")
    a.add_argument("--diff-path", action="append")
    f = sub.add_parser("finish")
    f.add_argument("--out", required=True)
    f.add_argument("--cov-bin")
    try:
        args = ap.parse_args()
    except SystemExit as e:
        sys.exit(EXIT["usage"] if e.code else 0)
    (analyze if args.cmd == "analyze" else finish)(args)


if __name__ == "__main__":
    main()
