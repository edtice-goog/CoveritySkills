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


def stream_aware(args):
    """Multi-stream corpus: per-stream tables plus what Connect will show.

    Rule 29 puts each branch in its own stream, so population deltas are only
    meaningful WITHIN a stream -- comparing the last release of one line
    against the first of the next measures a branch change, not a fix rate.

    First detected, by contrast, is global per merge key across the whole
    instance. A defect carried into a new branch keeps the date it was first
    seen anywhere, so a stream's opening snapshot can be full of defects dated
    years earlier. That projection is the last column of evidence before the
    one-shot commit phase.
    """
    bindir = pathlib.Path(args.bindir)
    root = pathlib.Path(args.idirs_root)
    rows = []
    for line in pathlib.Path(args.tags).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        rows.append((parts[0], parts[1], parts[2] if len(parts) > 2 else "default"))
    rows.sort(key=lambda r: (r[1], r[0]))

    sets = {}
    for tag, _, _ in rows:
        idir = root / tag
        if not idir.exists():
            print(f"[ERROR] no such idir: {idir}", file=sys.stderr)
            return 1
        sets[tag] = load(export(idir, bindir))

    for stream in sorted({r[2] for r in rows}):
        chain = [r for r in rows if r[2] == stream]
        print()
        print(f"=== {stream} ===")
        print(f"{'version':<12} {'date':<12} {'total':>6} {'new':>6} "
              f"{'persist':>8} {'fixed':>6}")
        prev = None
        for tag, date, _ in chain:
            cur = sets[tag]
            if prev is None:
                print(f"{tag:<12} {date:<12} {len(cur):>6} {len(cur):>6} "
                      f"{'-':>8} {'-':>6}")
            else:
                print(f"{tag:<12} {date:<12} {len(cur):>6} "
                      f"{len(cur.keys() - prev.keys()):>6} "
                      f"{len(cur.keys() & prev.keys()):>8} "
                      f"{len(prev.keys() - cur.keys()):>6}")
            prev = cur

    # Global first detected: earliest date any version contained the key.
    first = {}
    for tag, date, _ in rows:
        for mk in sets[tag]:
            if mk not in first or date < first[mk]:
                first[mk] = date
    print()
    print("Projected first-detected distribution after Phase 3")
    print("(what Connect will show; global per merge key, not per stream):")
    dist = collections.Counter(first.values())
    for date in sorted(dist):
        print(f"  {date}   {dist[date]:>4}")
    print(f"  total distinct CIDs: {len(first)}")

    latest = rows[-1][0]
    still = collections.Counter(first[mk] for mk in sets[latest])
    print()
    print(f"Defects in {latest} ({rows[-1][1]}) by first-detected date:")
    for date in sorted(still):
        print(f"  {date}   {still[date]:>4}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bindir", required=True,
                    help="Coverity Analysis bin directory")
    ap.add_argument("versions", nargs="*",
                    help="tag=idir pairs, in CHRONOLOGICAL order")
    ap.add_argument("--tags",
                    help="file of '<tag> <YYYY-MM-DD> [stream]' lines. Enables "
                         "stream-aware reporting: per-stream population tables "
                         "plus the global first-detected projection.")
    ap.add_argument("--idirs-root", default="idirs")
    args = ap.parse_args()

    if args.tags:
        return stream_aware(args)
    if not args.versions:
        ap.error("give tag=idir pairs, or --tags")

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
