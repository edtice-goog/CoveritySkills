#!/usr/bin/env python3
"""Verify every function model came from code that still exists.

The staleness check works at *file* granularity: does each TU's primary source
still exist, and is it the same size. This works at **model** granularity, and
is strictly stronger, because it asks the question that actually matters to the
analysis: *where did the model for each analyzed function come from?*

`output/callgraph-metrics.json.gz` answers it directly. Each entry carries
`identifier`, `file`, `line`, `hasImplementation` and `models` -- and the count
of `models: ["implementation"]` matches `Functions analyzed` in `summary.txt`
exactly. So a model whose `file` no longer exists is a function being analyzed
from code that is gone.

Measured on the FFmpeg case: before repairing an orphaned TU, **11 function
implementations were sourced from `libavcodec/x86/snowdsp.c`**, a file deleted
upstream -- among them a stale second definition of `ff_dwt_init_x86`, which is
actively called. After deleting the orphaned TU: zero.

Run this **after analysis**, as the confirmation that what was analyzed was
real. It is the natural complement to the pre-analysis staleness check: that
one asks what is *about* to be analyzed, this one asks what *was*.

Paths are compared after mapping the capture root onto the working tree, since
an imported idir records another machine's roots.

PROVISIONAL -- THIS CHECK USES A PROXY, AND THE PROXY IS KNOWN TO BE WRONG
=========================================================================
Measured 2026-08-25: the JSON `file` field is the location of the source
*text*, NOT the translation unit a model is attributed to. Coverity keys models
to the primary source file. On an FFmpeg idir, 205 of 2,252 distinct `file`
values were headers holding `static inline` definitions, while all 1,989
implementing TUs resolved to `.c` primaries -- zero headers.

So "the file at this path is missing" is not the same question as "the TU this
model came from is gone". It happened to coincide for the snowdsp.c case that
validated this tool, because there the text location and the TU primary were the
same file. It will NOT coincide for a header-defined function.

The correct source exists: analyze with `--enable-callgraph-metrics`, read the
`TU` column of `output/callgraph-metrics.csv`, and resolve it through
`cov-manage-emit list-json` to a `primaryFilename`. Rewrite pending.

Until then treat GHOST verdicts as INDICATIVE, not authoritative, and confirm
any finding against the TU column before acting on it.
"""
import argparse, gzip, json, os, posixpath, subprocess, sys, collections


def run(argv, cwd=None):
    p = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True)
    return p.returncode, p.stdout


def slash(p):
    return p.replace("\\", "/") if p else p


def load_callgraph(idir):
    p = os.path.join(idir, "output", "callgraph-metrics.json.gz")
    if not os.path.isfile(p):
        return None
    with gzip.open(p, "rt", encoding="utf-8", errors="replace") as fh:
        return json.load(fh).get("functions", [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="an ANALYZED idir")
    ap.add_argument("--tree", required=True, help="working tree root")
    ap.add_argument("--capture-root", help="root recorded in the idir; inferred if omitted")
    ap.add_argument("--json-out")
    a = ap.parse_args()

    tree = slash(os.path.abspath(a.tree))
    fns = load_callgraph(a.dir)
    if fns is None:
        print("ABORT: no output/callgraph-metrics.json.gz in %s" % a.dir)
        print("       This check runs AFTER cov-analyze. Analyze first.")
        return 2

    impl = [f for f in fns if f.get("hasImplementation")]
    srcs = collections.Counter(slash(f.get("file")) for f in impl if f.get("file"))

    root = slash(a.capture_root) if a.capture_root else None
    if not root:
        # Anchor on the most frequently-referenced source and walk its ancestors.
        # commonprefix is useless here: model sources mix the project root with
        # system headers (/usr/include/...), so the common prefix is "/".
        anchor = srcs.most_common(1)[0][0]
        best, best_hit = None, 0.0
        cand = posixpath.dirname(anchor)
        while cand and cand != "/":
            hit = sum(n for s, n in srcs.items()
                      if s.startswith(cand + "/")
                      and os.path.isfile(os.path.join(tree, posixpath.relpath(s, cand))))
            frac = hit / float(sum(srcs.values()))
            if frac > best_hit:
                best, best_hit = cand, frac
            cand = posixpath.dirname(cand)
        root, conf = best, best_hit
        print("inferred capture root: %s  (%.0f%% of model sources resolve under the tree)"
              % (root, conf * 100))
        if not root or conf < 0.2:
            print("REFUSING: could not infer a capture root. Pass --capture-root.",
                  file=sys.stderr)
            return 2

    # A model source is a ghost only if it cannot be found EITHER remapped into
    # the working tree, or at its own recorded absolute path. The second case
    # covers system headers and anything outside the project root, which are
    # legitimately not under the tree.
    missing, outside = {}, 0
    for s, n in srcs.items():
        if s.startswith(root.rstrip("/") + "/"):
            if os.path.isfile(os.path.join(tree, posixpath.relpath(s, root))):
                continue
        else:
            outside += n
            if os.path.isfile(s):
                continue
        missing[s] = n

    print("MODEL PROVENANCE  (%s)" % a.dir)
    print("  [PROVISIONAL] this checks the source TEXT location, not the TU a")
    print("                model is attributed to. Confirm findings against the")
    print("                TU column of callgraph-metrics.csv. See docstring.")
    print("  functions in callgraph      : %d" % len(fns))
    print("  with an implementation      : %d" % len(impl))
    print("  distinct source files       : %d" % len(srcs))
    print("  models from outside the root: %d function(s)" % outside)
    print("  sources ABSENT from the tree: %d" % len(missing))

    ghost = sum(missing.values())
    if missing:
        print()
        for s, n in sorted(missing.items(), key=lambda kv: -kv[1])[:15]:
            print("    [GHOST] %-58s %d function(s)" % (s[-58:], n))

    print()
    if not missing:
        print("VERDICT: SOUND -- every analyzed implementation came from a file that")
        print("         still exists. Nothing was modelled from code that is gone.")
        return 0

    print("VERDICT: GHOST MODELS -- %d function(s) across %d file(s) were analyzed"
          % (ghost, len(missing)))
    print("         from source that is not in the working tree.")
    print()
    print("  These are not merely extra findings in dead files. A ghost model is")
    print("  handed to every CALLER of that function, so it can change results in")
    print("  files that are perfectly current. Worse, if the function also exists")
    print("  in a live file, the emit holds two definitions of one symbol.")
    print()
    print("  Fix by deleting the orphaned TUs (see the staleness check) and")
    print("  re-analyzing. Do not report results from an idir in this state.")

    if a.json_out:
        json.dump({"functions": len(fns), "with_implementation": len(impl),
                   "sources": len(srcs), "capture_root": root,
                   "ghosts": [{"file": s, "functions": n} for s, n in missing.items()]},
                  open(a.json_out, "w", encoding="utf-8"), indent=1)
    return 1


if __name__ == "__main__":
    sys.exit(main())
