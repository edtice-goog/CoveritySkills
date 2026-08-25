#!/usr/bin/env python3
"""Detect -- and optionally strip -- multiple build targets in an idir.

An ideal deployment captures and analyzes ONE target at a time: a build that
produces both `-m32` and `-m64` should be two Coverity analyses. Real idirs are
not always built that way, which is exactly why `--one-tu-per-psf` exists and
defaults to true.

That matters here because an imported multi-target idir breaks the reuse
procedure in a way nothing reports:

- **`--tus-per-psf=latest` hides it.** A 3-file, 2-target idir lists 6 TUs but
  only 3 under `latest`. Any check written against `latest` -- including this
  skill's own staleness check, originally -- examines half the emit and calls
  it clean.
- **If the local build produces only one target**, the other target's TUs are
  never refreshed. They go stale, and `--one-tu-per-psf` then picks between a
  fresh TU and a stale one by an algorithm the documentation warns "might make
  different choices" between runs.

Targets are fingerprinted by the **type model** the front end was given --
`--type_sizes`, `--type_alignments`, `--size_t_type`, `--ptrdiff_t_type`.
Measured for gcc:

    -m64   type_sizes=e16Pdlx8fi4s2  size_t=m  ptrdiff=l
    -m32   type_sizes=e12dx8Pfil4s2  size_t=j  ptrdiff=i

That is a better key than grepping `-m32` out of the compiler argv: it
generalises to cross-compilers and other architectures, and it is the thing
that actually changes how the code is read.

If the local build produces every target the idir contains, there is nothing to
do. If it produces only one, strip the rest at import time.
"""
import argparse, json, os, re, subprocess, sys

MODEL_FLAGS = ("--type_sizes", "--type_alignments", "--size_t_type",
               "--wchar_t_type", "--ptrdiff_t_type")


def run(argv):
    p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       universal_newlines=True)
    return p.returncode, p.stdout


def tool(bin_dir, name):
    for c in (os.path.join(bin_dir, name + ".exe"), os.path.join(bin_dir, name)):
        if os.path.isfile(c):
            return c
    return os.path.join(bin_dir, name)


def fingerprint(argv):
    """The type model, as an ordered tuple. Absent flags are recorded too, so
    two targets never collide just because one omits a flag."""
    vals = []
    for i, t in enumerate(argv):
        for f in MODEL_FLAGS:
            if t == f and i + 1 < len(argv):
                vals.append("%s=%s" % (f, argv[i + 1]))
            elif t.startswith(f + "="):
                vals.append(t)
    return tuple(sorted(set(vals)))


def collect(bin_dir, idir):
    cme = tool(bin_dir, "cov-manage-emit")
    rc, out = run([cme, "--dir", idir, "list-capture-invocations"])
    if rc != 0:
        sys.stderr.write(out)
        return None
    d = json.loads(out)
    files = {f["id"]: (f.get("case-preserved") or f.get("case-normalized") or "").replace("\\", "/")
             for f in d.get("files", [])}
    emits = {e["id"]: e["process-invocation"]["command-line"]
             for e in d.get("cov-emit-invocations", [])}
    trans = {t["id"]: t["process-invocation"]["command-line"]
             for t in d.get("cov-translate-invocations", [])}
    tus = []
    for tu in d.get("translation-units", []):
        eid, tid = tu.get("cov-emit-invocation-id"), tu.get("cov-translate-invocation-id")
        argv = emits.get(eid, [])
        tus.append({"id": tu.get("id"),
                    "primary": files.get(tu.get("primary-file-id"), ""),
                    "fp": fingerprint(argv),
                    "compiler": " ".join(trans.get(tid, [])[1:]) or ""})
    return tus


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--strip-keep", metavar="N",
                    help="delete every TU NOT in target N (1-based, as listed). "
                         "Use only when the local build produces one target.")
    ap.add_argument("--json-out")
    a = ap.parse_args()

    tus = collect(a.bin, a.dir)
    if tus is None:
        return 2

    groups = {}
    for t in tus:
        groups.setdefault(t["fp"], []).append(t)
    order = sorted(groups, key=lambda k: -len(groups[k]))

    psf = {}
    for t in tus:
        psf.setdefault(t["primary"], 0)
        psf[t["primary"]] += 1
    dupes = sum(1 for v in psf.values() if v > 1)

    print("idir %s" % a.dir)
    print("  translation units  : %d" % len(tus))
    print("  distinct sources   : %d" % len(psf))
    print("  sources with >1 TU : %d" % dupes)
    print("  build targets      : %d" % len(order))
    for i, fp in enumerate(order, 1):
        g = groups[fp]
        print("\n  [%d] %d TUs   e.g. %s" % (i, len(g), (g[0]["compiler"] or "")[:60]))
        for v in fp:
            print("       %s" % v)

    if len(order) <= 1:
        print("\nSINGLE TARGET. Nothing to strip.")
    else:
        print("\n" + "!" * 70)
        print("MULTIPLE BUILD TARGETS IN ONE INTERMEDIATE DIRECTORY")
        print("  Ideally each target is captured and analyzed separately. This idir")
        print("  was not, so `--tus-per-psf=latest` reports %d of %d TUs and any check"
              % (len(psf), len(tus)))
        print("  written against it examines only part of the emit.")
        print()
        print("  If your local build produces ALL %d targets, nothing needs doing --" % len(order))
        print("  the delta capture will refresh each of them.")
        print()
        print("  If it produces only ONE, strip the others at import time. Left in")
        print("  place they are never rebuilt, go stale, and --one-tu-per-psf then")
        print("  chooses between a fresh TU and a stale one non-deterministically.")
        print("!" * 70)

    if a.strip_keep:
        try:
            keep = order[int(a.strip_keep) - 1]
        except (ValueError, IndexError):
            print("\nERROR: --strip-keep must be 1..%d" % len(order), file=sys.stderr)
            return 2
        doomed = [t["id"] for t in tus if t["fp"] != keep]
        print("\nSTRIPPING: keeping target %s (%d TUs), deleting %d TUs"
              % (a.strip_keep, len(groups[keep]), len(doomed)))
        if doomed:
            cme = tool(a.bin, "cov-manage-emit")
            args = []
            for i in doomed:
                args += ["--tu", str(i)]
            rc, out = run([cme, "--dir", a.dir] + args + ["delete"])
            print("  delete rc=%d" % rc)
            if rc != 0:
                sys.stderr.write(out); return 2
            rc, out = run([cme, "--dir", a.dir, "list"])
            print("  TUs remaining: %d" % len(re.findall(r"^\d+ ->", out, re.M)))

    if a.json_out:
        json.dump({"tus": len(tus), "sources": len(psf), "targets": len(order),
                   "groups": [{"fingerprint": list(fp), "tus": len(groups[fp]),
                               "example": groups[fp][0]["compiler"]} for fp in order]},
                  open(a.json_out, "w", encoding="utf-8"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
