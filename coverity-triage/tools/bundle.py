#!/usr/bin/env python3
"""Step 1: select findings and build self-contained triage bundles.

Emits one markdown file per selected finding containing the checker, every
site its merge key was reported at, the full event trace, and the real source
around every event -- enough for a reader (human or model) to assign a lane
and reach a verdict without access to the build machine. Also writes
INDEX.md for people and index.json for tools/records.py.

Selection (combine freely; nothing is selected by default):

  --merge-key KEY   this finding, unconditionally; repeatable.
  --per-checker N   N findings of every checker that fires (rule 26: a
                    stratified sample). Deterministic: sorted by merge key,
                    so a re-run bundles the same findings.
  --all             every finding. Say the count to whoever pays for it first.

  --plan            print what the selection holds and write nothing. Run it
                    before the plan is agreed: triage costs model time per
                    finding, and the count is the first thing to agree on.

SOURCE COMES FROM GIT, NOT THE WORKING TREE. A working tree holds whatever was
checked out last -- for a corpus built from many tags in one directory, the
wrong source for every version but one, and wrong in a way that reads as
entirely plausible. Pass --git-repo and the tag (or commit) the analyzed
version was built from; source is read via `git show <tag>:<path>`.
"""
import argparse
import collections
import json
import pathlib
import re
import subprocess
import sys


def load(path):
    """JSON v10 from cov-format-errors -> {merge key: [occurrences]}."""
    data = json.loads(path.read_text(encoding="utf-8"))
    by_key = collections.defaultdict(list)
    for i in data.get("issues", []):
        if i.get("mergeKey"):
            by_key[i["mergeKey"]].append(i)
    for occ in by_key.values():
        occ.sort(key=lambda i: i.get("occurrenceNumberInMK") or 0)
    return dict(by_key)


def rel(pathname, strip):
    """Recorded absolute build path -> repository-relative path."""
    p = (pathname or "?").replace("\\", "/")
    s = (strip or "").replace("\\", "/").rstrip("/")
    if s and p.startswith(s):
        p = p[len(s):]
    return p.lstrip("/")


def main_path(issue, strip):
    return rel(issue.get("strippedMainEventFilePathname")
               or issue.get("mainEventFilePathname"), strip)


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
                # Split on the line terminators a C compiler counts, and only
                # those. str.splitlines() also breaks on form feed, vertical
                # tab and other separators, so one ^L in a source file shifts
                # every excerpt after it a line away from the line numbers
                # Coverity reports -- plausibly wrong source next to each event.
                text = out.stdout.decode("utf-8", "replace")
                self.cache[relpath] = re.split(r"\r\n|\r|\n", text)
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


def shape(issue):
    """Facts about the evidence that bear on the lane and on how much reading
    a verdict needs: event count, files, interprocedural, statistical."""
    events = issue.get("events", [])
    files = {e.get("strippedFilePathname") or e.get("filePathname") for e in events}
    notes = [str(len(events)) + " events", str(len(files)) + " file(s)"]
    if len(files) > 1:
        notes.append("**interprocedural**")
    if any("out of" in (e.get("eventDescription") or "") for e in events):
        notes.append("**statistical evidence** (checked N out of M)")
    return ", ".join(notes)


def site(issue, strip):
    return {"file": main_path(issue, strip),
            "line": issue.get("mainEventLineNumber"),
            "function": issue.get("functionDisplayName")}


def render(occ, src, strip, context):
    issue = occ[0]
    events = issue.get("events", [])
    L = []
    L.append("# " + str(issue.get("checkerName"))
             + (" (" + issue["subcategory"] + ")" if issue.get("subcategory")
                and issue["subcategory"] != "none" else "")
             + " -- " + main_path(issue, strip)
             + ":" + str(issue.get("mainEventLineNumber")))
    L.append("")
    L.append("- **Function:** `" + str(issue.get("functionDisplayName", "?")) + "`")
    L.append("- **Merge key:** `" + issue["mergeKey"] + "`")
    L.append("- **Shape:** " + shape(issue))
    if len(occ) > 1:
        L.append("- **Reported at " + str(len(occ)) + " sites** (one merge key; "
                 "a verdict covers all of them):")
        for o in occ:
            s = site(o, strip)
            L.append("  - `" + s["file"] + ":" + str(s["line"]) + "` in `"
                     + str(s["function"]) + "`")
    L.append("")
    L.append("Lane: `references/lanes.md`. Questions and verdict set: "
             "`references/reading.md` (coverity-triage).")
    L.append("")
    L.append("## Event trace")
    L.append("")
    for e in events:
        f = rel(e.get("strippedFilePathname") or e.get("filePathname"), strip)
        L.append("- `" + f + ":" + str(e.get("lineNumber")) + "` **["
                 + str(e.get("eventTag")) + "]** " + str(e.get("eventDescription")))
    L.append("")
    L.append("## Source")
    L.append("")

    by_file = collections.defaultdict(set)
    marked = set()
    for o in occ:
        for e in o.get("events", []):
            f = rel(e.get("strippedFilePathname") or e.get("filePathname"), strip)
            by_file[f].add(e.get("lineNumber") or 0)
            if o is issue:
                marked.add((f, e.get("lineNumber")))
        if o is not issue:
            s = site(o, strip)
            by_file[s["file"]].add(s["line"] or 0)
            marked.add((s["file"], s["line"]))

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


def select(issues, args):
    selected = {}
    for mk in args.merge_key:
        if mk not in issues:
            raise SystemExit("[ERROR] merge key not present in these findings: " + mk)
        selected[mk] = "named (unconditional)"
    if args.per_checker:
        by_checker = collections.defaultdict(list)
        for mk, occ in issues.items():
            by_checker[occ[0].get("checkerName", "?")].append(mk)
        for checker, mks in sorted(by_checker.items()):
            for mk in sorted(mks)[:args.per_checker]:
                selected.setdefault(mk, "per-checker sample (" + checker + ")")
    if args.all:
        for mk in issues:
            selected.setdefault(mk, "all findings")
    return selected


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--issues", required=True,
                    help="JSON v10 from cov-format-errors")
    ap.add_argument("--git-repo", required=True)
    ap.add_argument("--tag", required=True,
                    help="tag or commit the analyzed version was built from -- "
                         "source is read from git at it, never from the working tree")
    ap.add_argument("--strip-prefix", default="",
                    help="build path prefix to remove, e.g. /home/me/demo/proj")
    ap.add_argument("--out", help="directory for the bundles (not needed with --plan)")
    ap.add_argument("--context", type=int, default=12)
    ap.add_argument("--per-checker", type=int, default=0,
                    help="sample N findings of each checker (rule 26)")
    ap.add_argument("--merge-key", action="append", default=[],
                    help="bundle this finding unconditionally; repeatable")
    ap.add_argument("--all", action="store_true", help="bundle every finding")
    ap.add_argument("--plan", action="store_true",
                    help="print what the selection holds; write nothing")
    args = ap.parse_args()

    issues = load(pathlib.Path(args.issues))
    selected = select(issues, args)
    if not selected:
        print("[ERROR] nothing selected: pass --merge-key, --per-checker or --all",
              file=sys.stderr)
        return 1

    ordered = sorted(selected, key=lambda mk: (issues[mk][0].get("checkerName", ""), mk))
    by_checker = collections.Counter(issues[mk][0].get("checkerName", "?") for mk in ordered)
    by_reason = collections.Counter(
        "per-checker sample" if r.startswith("per-checker") else r
        for r in selected.values())

    if args.plan:
        print("findings in the file: " + str(len(issues)) + " merge keys, "
              + str(len({i[0].get("checkerName") for i in issues.values()})) + " checkers")
        print("selected: " + str(len(ordered)))
        for r, n in sorted(by_reason.items()):
            print("  " + str(n).rjust(5) + "  " + r)
        print("by checker:")
        for c, n in sorted(by_checker.items()):
            print("  " + str(n).rjust(5) + "  " + c)
        return 0

    if not args.out:
        print("[ERROR] --out is required unless --plan", file=sys.stderr)
        return 1
    src = Source(args.git_repo, args.tag)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    index = ["# Triage bundles", "",
             "- Version: `" + args.tag + "`",
             "- Source: `git show " + args.tag + ":<path>` from `" + args.git_repo + "`",
             "- Findings: " + str(len(ordered)), "",
             "| # | checker | location | why selected |",
             "|---|---|---|---|"]
    records = []
    missing = 0
    for n, mk in enumerate(ordered, 1):
        occ = issues[mk]
        issue = occ[0]
        name = format(n, "03d") + "-" + str(issue.get("checkerName", "?")) + ".md"
        (out / name).write_bytes(render(occ, src, args.strip_prefix, args.context).encode("utf-8"))
        loc = main_path(issue, args.strip_prefix) + ":" + str(issue.get("mainEventLineNumber"))
        index.append("| [" + format(n, "03d") + "](" + name + ") | "
                     + str(issue.get("checkerName")) + " | `" + loc + "` | "
                     + selected[mk] + " |")
        if src.lines(main_path(issue, args.strip_prefix)) is None:
            missing += 1
        records.append({"n": n, "bundle": name, "mergeKey": mk,
                        "checker": issue.get("checkerName"),
                        "subcategory": issue.get("subcategory"),
                        "sites": [site(o, args.strip_prefix) for o in occ],
                        "selected_because": selected[mk]})
    (out / "INDEX.md").write_bytes(("\n".join(index) + "\n").encode("utf-8"))
    (out / "index.json").write_bytes((json.dumps({
        "issues": str(args.issues), "git_repo": str(args.git_repo), "tag": args.tag,
        "strip_prefix": args.strip_prefix, "findings_in_file": len(issues),
        "bundles": records}, indent=1) + "\n").encode("utf-8"))

    print("wrote " + str(len(ordered)) + " bundles to " + str(out) + "/ (INDEX.md, index.json)")
    if missing:
        print("[WARN] " + str(missing) + " bundle(s) missing source -- check "
              "--git-repo, --tag and --strip-prefix", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
