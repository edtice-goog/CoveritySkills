#!/usr/bin/env python3
"""Phase 4: build self-contained audit bundles for false-positive review.

Emits one markdown file per selected defect containing the checker, the full
event trace, and the real source around every event -- enough for a reviewer
(human or model) to reach a verdict without access to this machine.

Two selection modes, matching the two audit passes in SKILL.md:

  --per-checker N   sample N defects of every checker that fires. Rule 26
                    applied to a multi-version dataset: confidence in a
                    checker generalizes across its instances far better than
                    across checkers.
  --merge-key KEY   audit specific defects unconditionally. Use for anything
                    the story surfaces; those get audited whether or not the
                    sample happened to cover them.

SOURCE COMES FROM GIT, NOT THE WORKING TREE. A demo corpus is built by
checking many tags out of one fixed directory, so the working tree holds
whatever version was built last -- the wrong source for every defect but one,
and wrong in a way that reads as entirely plausible. Pass --git-repo and the
tag the version was built from; source is read via `git show <tag>:<path>`.
"""
import argparse
import collections
import json
import pathlib
import subprocess
import sys


def load(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return {i["mergeKey"]: i for i in data.get("issues", []) if i.get("mergeKey")}


def rel(pathname, strip):
    """Recorded absolute build path -> repository-relative path."""
    p = (pathname or "?").replace("\\", "/")
    s = (strip or "").replace("\\", "/").rstrip("/")
    if s and p.startswith(s):
        p = p[len(s):]
    return p.lstrip("/")


class Source:
    """Reads file contents from a git tag, with caching."""

    def __init__(self, repo, tag):
        self.repo, self.tag, self.cache = repo, tag, {}

    def lines(self, relpath):
        if relpath not in self.cache:
            try:
                out = subprocess.run(
                    ["git", "-C", self.repo, "show", self.tag + ":" + relpath],
                    check=True, capture_output=True)
                self.cache[relpath] = out.stdout.decode("utf-8", "replace").splitlines()
            except subprocess.CalledProcessError:
                self.cache[relpath] = None
        return self.cache[relpath]


def merge_ranges(nums, context):
    """Line numbers -> merged (start, end) windows with context."""
    spans = sorted((max(1, n - context), n + context) for n in nums)
    out = []
    for lo, hi in spans:
        if out and lo <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def legibility(issue):
    """Signals for the legibility rule -- a demo defect must read in seconds."""
    events = issue.get("events", [])
    files = {e.get("strippedFilePathname") for e in events}
    notes = [str(len(events)) + " events", str(len(files)) + " file(s)"]
    if len(files) > 1:
        notes.append("**interprocedural**")
    if any("out of" in (e.get("eventDescription") or "") for e in events):
        notes.append("**statistical evidence** (checked N out of M)")
    return ", ".join(notes)


def render(issue, src, strip, context):
    events = issue.get("events", [])
    main_file = rel(issue.get("strippedMainEventFilePathname")
                    or issue.get("mainEventFilePathname"), strip)
    L = []
    L.append("# " + str(issue.get("checkerName")) + " -- " + main_file
             + ":" + str(issue.get("mainEventLineNumber")))
    L.append("")
    L.append("- **Function:** `" + str(issue.get("functionDisplayName", "?")) + "`")
    L.append("- **Merge key:** `" + issue["mergeKey"] + "`")
    L.append("- **Legibility:** " + legibility(issue))
    L.append("")
    L.append("## Verdict")
    L.append("")
    L.append("_Verdict (see references/triage-verdicts.md):_")
    L.append("")
    L.append("- `real` / `real, low severity` / `intentional`")
    L.append("- `false positive - global invariant` -- name the invariant, say")
    L.append("  WHERE it is enforced (file:line, or the mechanism), and what")
    L.append("  would break it. No location, no dismissal.")
    L.append("- `false positive - heuristic misfire` -- the checker matched a")
    L.append("  shape, not a path, and the shape is correct.")
    L.append("- `unresolved` -- use this whenever the argument depends on code")
    L.append("  you have not read. It applies to confirmations as well as")
    L.append("  dismissals; a caveat is not a verdict.")
    L.append("")
    L.append("Demo-worthiness is a separate question: a finding that needs")
    L.append("minutes of code reading, or an invariant the audience cannot see,")
    L.append("should not be the defect on screen whatever its verdict.")
    L.append("")
    L.append("## Event trace")
    L.append("")
    for e in events:
        f = rel(e.get("strippedFilePathname"), strip)
        L.append("- `" + f + ":" + str(e.get("lineNumber")) + "` **["
                 + str(e.get("eventTag")) + "]** " + str(e.get("eventDescription")))
    L.append("")
    L.append("## Source")
    L.append("")

    by_file = collections.defaultdict(set)
    for e in events:
        by_file[rel(e.get("strippedFilePathname"), strip)].add(e.get("lineNumber") or 0)
    marked = {(rel(e.get("strippedFilePathname"), strip), e.get("lineNumber"))
              for e in events}

    for f, nums in sorted(by_file.items()):
        lines = src.lines(f)
        L.append("### " + f)
        L.append("")
        if lines is None:
            L.append("_Source unavailable: `git show " + src.tag + ":" + f
                     + "` failed._")
            L.append("")
            continue
        for lo, hi in merge_ranges({n for n in nums if n}, context):
            L.append("```c")
            for n in range(lo, min(hi, len(lines)) + 1):
                mark = ">>" if (f, n) in marked else "  "
                L.append(mark + format(n, "6d") + "  " + lines[n - 1])
            L.append("```")
            L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--issues", required=True,
                    help="JSON v10 from cov-format-errors (or phase2.py)")
    ap.add_argument("--git-repo", required=True)
    ap.add_argument("--tag", required=True,
                    help="tag this version was built from -- source is read "
                         "from git at this tag, never from the working tree")
    ap.add_argument("--strip-prefix", default="",
                    help="build path prefix to remove, e.g. /home/me/demo/proj")
    ap.add_argument("--out", required=True)
    ap.add_argument("--context", type=int, default=12)
    ap.add_argument("--per-checker", type=int, default=0,
                    help="sample N defects of each checker (rule 26)")
    ap.add_argument("--merge-key", action="append", default=[],
                    help="audit this defect unconditionally; repeatable")
    args = ap.parse_args()

    issues = load(pathlib.Path(args.issues))
    src = Source(args.git_repo, args.tag)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    selected, reason = {}, {}
    for mk in args.merge_key:
        if mk not in issues:
            print("[ERROR] merge key not present in this version: " + mk,
                  file=sys.stderr)
            return 1
        selected[mk] = issues[mk]
        reason[mk] = "story-surfaced (unconditional)"

    if args.per_checker:
        by_checker = collections.defaultdict(list)
        for mk, i in issues.items():
            by_checker[i.get("checkerName", "?")].append(mk)
        for checker, mks in sorted(by_checker.items()):
            # Deterministic sample: sorted by merge key rather than random, so
            # a re-run audits the same defects and verdicts stay comparable.
            for mk in sorted(mks)[:args.per_checker]:
                if mk not in selected:
                    selected[mk] = issues[mk]
                    reason[mk] = "per-checker sample (" + checker + ")"

    if not selected:
        print("[ERROR] nothing selected: pass --per-checker and/or --merge-key",
              file=sys.stderr)
        return 1

    index = ["# Audit bundle", "",
             "- Version: `" + args.tag + "`",
             "- Source: `git show " + args.tag + ":<path>` from `"
             + args.git_repo + "`",
             "- Defects to review: " + str(len(selected)), "",
             "| # | checker | location | why selected |",
             "|---|---|---|---|"]
    ordered = sorted(selected.items(), key=lambda kv: kv[1].get("checkerName", ""))
    for n, (mk, issue) in enumerate(ordered, 1):
        name = format(n, "03d") + "-" + str(issue.get("checkerName", "?")) + ".md"
        (out / name).write_bytes(
            render(issue, src, args.strip_prefix, args.context).encode("utf-8"))
        loc = (rel(issue.get("strippedMainEventFilePathname"), args.strip_prefix)
               + ":" + str(issue.get("mainEventLineNumber")))
        index.append("| [" + format(n, "03d") + "](" + name + ") | "
                     + str(issue.get("checkerName")) + " | `" + loc + "` | "
                     + reason[mk] + " |")
    index += ["", "Every defect the story surfaces must be audited regardless of",
              "whether the per-checker sample covered it -- the new defect at the",
              "tip is the most likely to be demoed and the least likely to be",
              "sampled out of a checker that fired fifty times."]
    (out / "INDEX.md").write_bytes(("\n".join(index) + "\n").encode("utf-8"))

    missing = 0
    for mk in selected:
        f = rel(selected[mk].get("strippedMainEventFilePathname"), args.strip_prefix)
        if src.lines(f) is None:
            missing += 1
    print("wrote " + str(len(selected)) + " bundles to " + str(out) + "/ (INDEX.md)")
    if missing:
        print("[WARN] " + str(missing) + " bundle(s) missing source -- check "
              "--git-repo, --tag and --strip-prefix", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
