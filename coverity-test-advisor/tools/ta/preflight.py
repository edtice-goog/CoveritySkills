"""Checks before a Test Advisor run: is this a pair Test Advisor can
judge, and are the inputs from the commits they claim to be?

Each check returns a Check(name, result, detail): "ok", "warn" (the run goes on, the report says so), "refuse" (the
inputs are inconsistent), "gate" (a Coverity version the cross-reference parser has not been checked on) or "cxx"
(C++ code: calls through a base class are not expanded yet).
"""
import collections
import hashlib
import os
import re
import subprocess

GATED_VERSIONS = ("2026.9.0",)   # where ta/xref_format.py was checked byte for byte
PROJECT_LANGS = {"C": "c", "C++": "cxx", "Java source": "java"}


class Check:
    def __init__(self, name, result, detail):
        self.name, self.result, self.detail = name, result, detail

    def as_dict(self):
        return {"check": self.name, "result": self.result, "detail": self.detail}


def sh(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def git_files(repo, sha):
    return set(sh("git", "-C", repo, "ls-tree", "-r", "--name-only", sha).split("\n")) - {""}


def coverity_version(idir):
    try:
        line = open(f"{idir}/output/version").readline()
    except OSError:
        return None
    m = re.search(r"version (\d+\.\d+\.\d+)", line)
    return m[1] if m else None


def analyze_options(idir):
    """The cov-analyze options from output/analysis-log.txt, without --dir and the job count (results do not
    depend on it), as a sorted list; None when the log is missing."""
    try:
        log = open(f"{idir}/output/analysis-log.txt", errors="replace").read()
    except OSError:
        return None
    m = re.search(r"cov-analyze (.*)", log)
    if not m:
        return None
    toks, out, skip = m[1].split(), [], 0
    for i, t in enumerate(toks):
        if skip:
            skip -= 1
            continue
        if t in ("--dir", "--jobs", "-j"):
            skip = 1
            continue
        if t.startswith(("--dir=", "--jobs=")):
            continue
        out.append(t)
    return sorted(out)


def list_json(cov_bin, idir):
    import json
    return json.loads(sh(f"{cov_bin}/cov-manage-emit", "--dir", idir, "list-json"))


def infer_root(paths, repo_files):
    """The build root that, stripped from these absolute paths, leaves paths that exist in the repository at the
    commit; the most common one. None when no path matches."""
    votes = collections.Counter()
    for p in paths:
        parts = p.split("/")
        for k in range(1, len(parts)):
            if "/".join(parts[k:]) in repo_files:
                votes["/".join(parts[:k])] += 1
                break
    return votes.most_common(1)[0][0] if votes else None


def stored_sources(cov_bin, idir):
    """{absolute path: {md5 hex}} of every source the capture stored, from the documented
    `cov-manage-emit print-source-files-stats` (its "MD5 sum" is the MD5 of the stored file, headers included, so it
    equals git's file at the commit the idir was built from)."""
    text = sh(f"{cov_bin}/cov-manage-emit", "--dir", idir, "--tu-pattern", 'file(".*")', "print-source-files-stats")
    out, cur = collections.defaultdict(set), None
    for line in text.splitlines():
        m = re.match(r"\s*(?:Primary SF|Source file)\s*:\s*(\S+) \(row ID", line)
        if m:
            cur = m[1]
            continue
        m = re.match(r"\s*MD5 sum:\s*([0-9a-f]{32})", line)
        if m and cur:
            out[cur].add(m[1])
            cur = None
    return out


def built_from(cov_bin, idir, root, repo, sha, changed):
    """Does the idir hold the commit's sources? Compares the MD5 the capture stored with git's file at the commit.
    A changed file that differs means the idir is not from this commit (refuse); an unchanged one that differs is a
    warning (a file generated or edited during the build)."""
    files, same, differ = git_files(repo, sha), 0, []
    for p, hashes in stored_sources(cov_bin, idir).items():
        if not p.startswith(root + "/"):
            continue
        rel = p[len(root) + 1:]
        if rel not in files:
            continue
        blob = subprocess.run(["git", "-C", repo, "show", f"{sha}:{rel}"], capture_output=True).stdout
        if hashlib.md5(blob).hexdigest() in hashes:
            same += 1
        else:
            differ.append(rel)
    bad = [f for f in differ if f in changed]
    if bad or not same:
        return "refuse", f"{len(bad) or len(differ)} file(s) differ from commit {sha[:12]}: {', '.join((bad or differ)[:5])}"
    if differ:
        return "warn", f"{same} files match commit {sha[:12]}; {len(differ)} unchanged file(s) differ: {', '.join(differ[:5])}"
    return "ok", f"all {same} captured project files match commit {sha[:12]}"


def run(args, changed_files):
    """All checks, in order; stops at the first gate, cxx or refuse that makes the rest meaningless."""
    checks, facts = [], {}
    vb, vh = coverity_version(args.base_idir), coverity_version(args.head_idir)
    facts["coverity_version"] = vh
    if vh not in GATED_VERSIONS or vb not in GATED_VERSIONS:
        checks.append(Check("coverity version", "gate",
                            f"base {vb}, head {vh}: the cross-reference reader is checked on {', '.join(GATED_VERSIONS)} only"))
        return checks, facts
    checks.append(Check("coverity version", "ok", f"both {vh}"))

    ob, oh = analyze_options(args.base_idir), analyze_options(args.head_idir)
    if ob is None or oh is None:
        checks.append(Check("cov-analyze options", "warn", "output/analysis-log.txt missing or unreadable in "
                            + ("base" if ob is None else "head")))
    elif ob != oh:
        checks.append(Check("cov-analyze options", "refuse", f"base {' '.join(ob) or '(defaults)'}, "
                            f"head {' '.join(oh) or '(defaults)'}: models would differ for that reason alone"))
        return checks, facts
    else:
        checks.append(Check("cov-analyze options", "ok", " ".join(oh) or "defaults on both"))

    langs, roots = collections.Counter(), {}
    for side, idir, sha in (("base", args.base_idir, args.base_commit), ("head", args.head_idir, args.head_commit)):
        tus = list_json(args.cov_bin, idir)
        files = git_files(args.repo, sha)
        root = infer_root([t["primaryFilename"] for t in tus], files)
        if root is None:
            checks.append(Check(f"{side} capture root", "refuse",
                                f"no captured source of the {side} idir exists in the repository at {sha[:12]}"))
            return checks, facts
        roots[side] = root
        if side == "head":
            for t in tus:
                if t["primaryFilename"].startswith(root + "/"):
                    langs[PROJECT_LANGS.get(t["language"], t["language"])] += 1
    facts["capture_roots"] = roots
    if langs.get("cxx"):
        checks.append(Check("language", "cxx", f"{langs['cxx']} C++ translation units: calls through a base class "
                            "are not expanded for C++ yet, so callers of overridden methods would be missed"))
        return checks, facts
    lang = "java" if langs.get("java") else "c" if langs.get("c") else None
    if lang is None:
        checks.append(Check("language", "refuse", f"no C or Java project sources captured: {dict(langs)}"))
        return checks, facts
    facts["language"] = lang
    checks.append(Check("language", "ok", f"{lang}: {langs[lang]} project translation units in the head"))

    for side, idir, sha in (("base", args.base_idir, args.base_commit), ("head", args.head_idir, args.head_commit)):
        result, detail = built_from(args.cov_bin, idir, roots[side], args.repo, sha, changed_files)
        checks.append(Check(f"{side} idir built from its commit", result, detail))
        if result == "refuse":
            return checks, facts
    return checks, facts


def coverage_checks(cov, captured, head_fns, gcov):
    """The coverage against the capture: captured product files with no coverage (a coverage build that did not
    compile them, or other sources), and, for gcov, function extents that disagree with the capture's."""
    checks = []
    covered = set(cov.lines)
    missing = sorted(captured - covered)
    if not captured & covered:
        checks.append(Check("coverage matches the capture", "refuse",
                            "no captured product file appears in the coverage: wrong coverage file or source roots"))
        return checks
    if missing:
        checks.append(Check("coverage matches the capture", "warn",
                            f"{len(missing)} of {len(captured)} captured product files have no coverage: {', '.join(missing[:5])}"))
    else:
        checks.append(Check("coverage matches the capture", "ok", f"all {len(captured)} captured product files have coverage"))
    if gcov:
        off, n = [], 0
        for f in head_fns:
            rec = cov.functions.get(f.file, {}).get(f.name)
            if rec:
                n += 1
                if (rec["start"], rec["end"]) != (f.start, f.end):
                    off.append(f"{f.file}:{f.name}")
        if off:
            checks.append(Check("coverage built from the same sources", "warn",
                                f"{len(off)} of {n} functions have other extents in the coverage than in the capture: {', '.join(off[:5])}"))
        elif n:
            checks.append(Check("coverage built from the same sources", "ok", f"extents of all {n} shared functions agree"))
    return checks
