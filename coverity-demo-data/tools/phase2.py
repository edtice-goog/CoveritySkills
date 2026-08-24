#!/usr/bin/env python3
"""Phase 2: offline defect-set algebra over analyzed idirs.

Reads analyzed intermediate directories in chronological order and reports how
the defect population evolves: what is introduced, what persists, what gets
fixed. No Coverity Connect involvement and no commits -- this stage is freely
re-runnable, which is the whole point of separating it from the one-shot
backdated commit.

Defects are identified by mergeKey, the same identity Coverity Connect uses to
assign a CID across snapshots. That makes the counts here a faithful preview of
what Connect will show *provided* two conditions hold:

  1. every version was built at the same path, and
  2. every version was analyzed with the SAME pinned analyzer version.

The second condition is a precondition, not a nicety. Rule 27 warns against
comparing raw merge keys between local result sets because keys can move across
analyzer versions, with Connect's antecedent merge keys doing the reconciling.
Pinned to one analyzer, no key moves and no antecedent is created, so that
concern -- true in general -- simply does not arise here. Vary the analyzer and
this arithmetic silently becomes the mistake rule 27 describes.
"""
import argparse
import collections
import json
import pathlib
import subprocess
import sys


def export(idir: pathlib.Path, bindir: pathlib.Path) -> pathlib.Path:
    """Export analysis results to JSON v10, which carries mergeKey."""
    out = idir / "phase2-issues.json"
    if not out.exists():
        subprocess.run(
            [str(bindir / "cov-format-errors"), "--dir", str(idir),
             "--json-output-v10", str(out)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return out


def load(path: pathlib.Path) -> dict:
    """mergeKey -> (checker, file, function) for one version."""
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for issue in data.get("issues", []):
        mk = issue.get("mergeKey")
        if not mk:
            continue
        out[mk] = (issue.get("checkerName", "?"),
                   issue.get("strippedMainEventFilePathname")
                   or issue.get("mainEventFilePathname", "?"),
                   issue.get("functionDisplayName", "?"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bindir", required=True,
                    help="Coverity Analysis bin directory")
    ap.add_argument("versions", nargs="+",
                    help="tag=idir pairs, in CHRONOLOGICAL order")
    args = ap.parse_args()

    bindir = pathlib.Path(args.bindir)
    order, sets = [], {}
    for spec in args.versions:
        tag, _, d = spec.partition("=")
        idir = pathlib.Path(d)
        if not idir.exists():
            print(f"[ERROR] no such idir: {idir}", file=sys.stderr)
            return 1
        sets[tag] = load(export(idir, bindir))
        order.append(tag)

    # --- merge-key stability guard -------------------------------------
    # Adjacent releases of a mature project share most of their defects. Zero
    # overlap means merge keys did not line up -- almost always because the
    # versions were built at different paths -- and every defect would appear
    # newly introduced in every snapshot. Catch it here, before the one-shot
    # backdated commit burns first-detected dates that cannot be rewritten.
    for a, b in zip(order, order[1:]):
        shared = len(sets[a].keys() & sets[b].keys())
        if shared == 0:
            print(f"[FATAL] {a} and {b} share zero merge keys. Defects will "
                  f"not merge into stable CIDs. Check that every version was "
                  f"built at the SAME path.", file=sys.stderr)
            return 2
        pct = 100.0 * shared / max(len(sets[a]), 1)
        print(f"[ok] {a} -> {b}: {shared} shared merge keys "
              f"({pct:.0f}% of {a})")

    # --- population over time ------------------------------------------
    print(f"\n{'version':<12} {'total':>6} {'new':>6} {'persist':>8} {'fixed':>6}")
    prev = None
    for tag in order:
        cur = sets[tag]
        if prev is None:
            print(f"{tag:<12} {len(cur):>6} {len(cur):>6} {'-':>8} {'-':>6}")
        else:
            new = len(cur.keys() - prev.keys())
            persist = len(cur.keys() & prev.keys())
            fixed = len(prev.keys() - cur.keys())
            print(f"{tag:<12} {len(cur):>6} {new:>6} {persist:>8} {fixed:>6}")
        prev = cur

    # --- aging: how long each surviving defect has been present ---------
    latest = order[-1]
    first_seen = {}
    for tag in order:
        for mk in sets[tag]:
            first_seen.setdefault(mk, tag)

    print(f"\nSurviving defects in {latest}, by version first seen:")
    ages = collections.Counter(first_seen[mk] for mk in sets[latest])
    for tag in order:
        if ages[tag]:
            print(f"  first seen in {tag:<12} {ages[tag]:>4} still present")

    # --- checker coverage: drives the Phase 4 FP audit sample -----------
    print(f"\nCheckers firing in {latest} (audit a sample of each):")
    by_checker = collections.Counter(c for c, _, _ in sets[latest].values())
    for checker, n in sorted(by_checker.items(), key=lambda kv: -kv[1]):
        print(f"  {checker:<24} {n:>4}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
