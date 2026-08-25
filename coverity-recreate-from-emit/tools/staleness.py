#!/usr/bin/env python3
"""Pre-analysis staleness check for a reused intermediate directory.

Runs BETWEEN the delta capture and cov-analyze. Independent of how the idir
was obtained, so a baseline that is too new, too old, or simply wrong is
detected rather than assumed away.

PATHS DO NOT MATCH, AND THAT IS FINE.
An imported idir was captured somewhere else, so its recorded primary paths
carry the CI/other-host root. Leaving them mismatched is the point: an
unchanged file needs no re-emit, so its TU can keep the foreign path forever.
Everything here therefore compares on ROOT-RELATIVE paths.

The mismatch only matters when a file CHANGES. Re-emitting under the local
root creates a TU whose primary source file differs from the old one *by
path*, so Coverity APPENDS rather than supersedes, and both get analyzed.
Those must be deleted explicitly -- reported here as PATH_DIVERGED.

Scoped to builds that do not generate source, which keeps the delta decidable:
everything that moves is something `git diff` reports.

  OK            present, size matches
  STALE         present, size differs         -> re-emit
  PATH_DIVERGED stale AND path root differs   -> DELETE the old TU, then re-emit
  ORPHAN        absent from the tree          -> DELETE the TU
  UNTRACKED     present but not in git        -> fine; note on delta visibility

Presence is the test, not git tracking: a file created and not yet added is
ordinary work in progress.
"""
import argparse, json, os, posixpath, subprocess, sys


def run(argv, cwd=None):
    p = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True)
    return p.returncode, p.stdout


def slash(p):
    return p.replace("\\", "/") if p else p


def infer_capture_root(primaries, tree_root, tracked_rel):
    """Longest common directory prefix of the emit, validated against the tree.

    Verified by requiring that most resulting relative paths actually exist
    under tree_root -- an inferred root that does not resolve is worse than no
    inference at all.
    """
    if not primaries:
        return None, 0.0
    common = posixpath.dirname(os.path.commonprefix(primaries))
    best, best_hit = None, 0.0
    cand = common
    while cand and cand != "/":
        rels = [posixpath.relpath(p, cand) for p in primaries]
        hits = sum(1 for r in rels
                   if os.path.isfile(os.path.join(tree_root, r)) or r in tracked_rel)
        frac = hits / len(rels)
        if frac > best_hit:
            best, best_hit = cand, frac
        if best_hit == 1.0:
            break
        cand = posixpath.dirname(cand)
    return best, best_hit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", required=True)
    ap.add_argument("--dir", required=True, help="the reused idir")
    ap.add_argument("--tree", required=True, help="working tree root")
    ap.add_argument("--capture-root",
                    help="root the idir was captured at; inferred if omitted")
    ap.add_argument("--json-out")
    a = ap.parse_args()

    tree = slash(os.path.abspath(a.tree))
    exe = os.path.join(a.bin, "cov-manage-emit")
    # Deliberately NOT --tus-per-psf=latest. On a multi-target idir that hides
    # half the emit: a 3-file, 2-target directory lists 6 TUs but only 3 under
    # `latest`, and the unexamined half is exactly the target the local build
    # does not rebuild. Check everything; report duplicates.
    rc, out = run([exe, "--dir", a.dir, "list-json"])
    if rc != 0:
        sys.stderr.write(out)
        return 2
    tus = json.loads(out)
    primaries = [slash(t.get("primaryFilename")) for t in tus if t.get("primaryFilename")]

    rc, tracked_out = run(["git", "ls-files"], cwd=tree)
    tracked_rel = {l.strip() for l in tracked_out.splitlines() if l.strip()} if rc == 0 else set()

    root = slash(a.capture_root) if a.capture_root else None
    if not root:
        root, conf = infer_capture_root(primaries, tree, tracked_rel)
        print("inferred capture root: %s  (%.0f%% of primaries resolve under the tree)"
              % (root, conf * 100))
        if conf < 0.5:
            print("REFUSING: the inferred root does not resolve. Pass --capture-root.",
                  file=sys.stderr)
            return 2
    print("capture root : %s" % root)
    print("working tree : %s" % tree)
    diverged_root = (root.rstrip("/") != tree.rstrip("/"))
    print("path divergence: %s" % ("YES -- imported idir" if diverged_root else "no -- same root"))
    print()

    buckets = {"OK": [], "STALE": [], "PATH_DIVERGED": [], "ORPHAN": [], "UNTRACKED": []}
    for t in tus:
        p = slash(t.get("primaryFilename"))
        want = t.get("primaryFileSizeInBytes")
        if not p:
            continue
        rel = posixpath.relpath(p, root)
        local = os.path.join(tree, rel)
        if not os.path.isfile(local):
            buckets["ORPHAN"].append((rel, want, None))
            continue
        got = os.path.getsize(local)
        if got != want:
            # a changed file whose TU sits at a foreign path will be APPENDED
            # to, not superseded -- so it needs an explicit delete first
            buckets["PATH_DIVERGED" if diverged_root else "STALE"].append((rel, want, got))
        else:
            buckets["OK"].append((rel, want, got))
        if tracked_rel and rel not in tracked_rel:
            buckets["UNTRACKED"].append((rel, want, got))

    # More TUs than distinct sources means multiple build targets (or stray
    # duplicates). Either way a per-source check is not the whole story.
    per_src = {}
    for t in tus:
        p = slash(t.get("primaryFilename"))
        if p:
            per_src[p] = per_src.get(p, 0) + 1
    multi = sum(1 for v in per_src.values() if v > 1)
    if multi:
        print("MULTI-TARGET: %d TUs across %d distinct sources (%d sources have >1)."
              % (len(tus), len(per_src), multi))
        print("  This idir holds more than one build target. Run build_targets.py:")
        print("  if the local build produces only one of them, strip the rest before")
        print("  analyzing, or the unrebuilt target goes stale unnoticed.\n")

    print("STALENESS CHECK  (%d TUs, all targets)" % len(tus))
    for k in ("OK", "STALE", "PATH_DIVERGED", "ORPHAN", "UNTRACKED"):
        print("  %-14s %d" % (k, len(buckets[k])))
    for k in ("STALE", "PATH_DIVERGED", "ORPHAN", "UNTRACKED"):
        for rel, want, got in buckets[k][:12]:
            print("    [%s] %s  emitted=%s disk=%s" % (k, rel, want, got))

    bad = len(buckets["STALE"]) + len(buckets["ORPHAN"]) + len(buckets["PATH_DIVERGED"])
    print()
    if buckets["UNTRACKED"]:
        print("NOTE: %d TU(s) present on disk but untracked by git. Fine for work in"
              % len(buckets["UNTRACKED"]))
        print("      progress, but `git diff` will not report them moving. If these are")
        print("      build-generated sources, this skill does not cover that.\n")
    if bad == 0:
        print("VERDICT: CURRENT -- every TU matches the tree. Safe to analyze.")
        if diverged_root:
            print("         Foreign paths on unchanged TUs are expected and harmless.")
    else:
        print("VERDICT: STALE -- %d TU(s) do not match the working tree. Do NOT analyze."
              % bad)
        if buckets["PATH_DIVERGED"]:
            print("         %d changed under a FOREIGN path: delete those TUs before"
                  % len(buckets["PATH_DIVERGED"]))
            print("         re-emitting, or Coverity appends and analyzes both copies.")
        if buckets["ORPHAN"]:
            print("         %d orphaned: delete. An orphan is analyzed as if present."
                  % len(buckets["ORPHAN"]))

    if a.json_out:
        json.dump({"capture_root": root, "tree": tree,
                   "path_divergence": diverged_root,
                   "buckets": {k: [{"rel": r, "emitted": w, "disk": g} for r, w, g in v]
                               for k, v in buckets.items()}},
                  open(a.json_out, "w", encoding="utf-8"), indent=1)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
