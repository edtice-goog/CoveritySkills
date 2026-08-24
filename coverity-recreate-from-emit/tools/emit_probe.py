#!/usr/bin/env python3
"""
emit_probe.py -- measure the cov-translate -> cov-emit transformation.

Pure stdlib. No pip install on a build machine.

The premise: an intermediate directory records, for every translation unit,
both the original compiler command line (cov-translate) and the resolved front
end command line it produced (cov-emit), explicitly linked. Feed the recorded
input to a different Coverity version and diff its output against the recorded
one. The residual is the transformation delta -- measured, not assumed.

Subcommands, in the order the procedure uses them:

  identify   what wrote this idir, and which installs can open it
  extract    pull the (translate, emit) pairs out of an idir
  probe      re-run recorded inputs under a given install, capture its output
  delta      normalize and diff recorded vs generated

Always run `probe` against the ORIGINAL version first. That control is what
separates the version's contribution from your environment's. See
../references/transformation-probe.md.
"""

import argparse
import glob as globmod
import json
import os
import re
import shutil
import subprocess
import sys

# --------------------------------------------------------------------------
# normalization
#
# Every entry masked here was observed to vary between two runs of the SAME
# version. Do not extend this set to make a delta disappear; find out why the
# new element varies first.
# --------------------------------------------------------------------------

CFG_INSTANCE_RE = re.compile(r"^.*/emit/[^/]+/config/[0-9a-f]{32}/(.*)$")
CONFIG_MD5_RE = re.compile(r"^--coverity_config_md5=[0-9a-fA-F]+$")

# Flags whose value materially changes what the front end accepts or
# predefines. A difference in any of these is a finding, never noise.
SEMANTIC_HINTS = (
    "--comp_ver", "--gnu_version", "--type_sizes", "--type_alignments",
    "--size_t_type", "--wchar_t_type", "--ptrdiff_t_type", "--sys_include",
    "--c8", "--c9", "--c1", "--c2", "--c+", "-D", "-I", "-U",
    "--gcc", "--microsoft", "--clang", "--std",
)


def _slash(tok):
    return tok.replace("\\", "/")


def normalize(tokens, source_name=None):
    """Mask environment-dependent tokens. Returns a new list."""
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        t = _slash(tokens[i])

        # argv[0]: the cov-emit binary path
        if i == 0 and t.endswith(("cov-emit", "cov-emit.exe")):
            out.append("<COV-EMIT>")
            i += 1
            continue

        # per-session temp dirs; the COUNT of these varies too, so drop them
        if t.startswith("--ignore_path="):
            i += 1
            continue

        if t.startswith("--dir="):
            out.append("--dir=<IDIR>")
            i += 1
            continue

        if CONFIG_MD5_RE.match(t):
            out.append("--coverity_config_md5=<MD5>")
            i += 1
            continue

        # --preinclude <...>/user_nodefs.h : present iff the config dir has one
        if t == "--preinclude" and i + 1 < n and _slash(tokens[i + 1]).endswith("user_nodefs.h"):
            i += 2
            continue

        m = CFG_INSTANCE_RE.match(t)
        if m:
            out.append("<CFGDIR>/" + m.group(1))
            i += 1
            continue

        if source_name and os.path.basename(t) == os.path.basename(source_name):
            out.append("<SOURCE>")
            i += 1
            continue

        out.append(t)
        i += 1
    return out


def classify(token):
    """Hint at whether a differing token is likely semantic. Advisory only."""
    for h in SEMANTIC_HINTS:
        if token.startswith(h):
            return "semantic"
    if token.startswith("<") or "<IDIR>" in token or "<CFGDIR>" in token:
        return "environment"
    return "unclassified"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def tool(bin_dir, name):
    for cand in (os.path.join(bin_dir, name + ".exe"), os.path.join(bin_dir, name)):
        if os.path.isfile(cand):
            return cand
    return os.path.join(bin_dir, name)


def run(cmd, cwd=None, env=None):
    p = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True)
    return p.returncode, p.stdout


def read_emit_version(idir):
    path = os.path.join(idir, "emit", "version")
    if not os.path.isfile(path):
        return None, None
    lines = [l.strip() for l in open(path, encoding="utf-8", errors="replace") if l.strip()]
    creator = None
    fmt = None
    for l in lines:
        if l.startswith("#"):
            m = re.search(r"version\s+(\S+)", l)
            if m:
                creator = m.group(1)
        elif re.fullmatch(r"\d+", l):
            fmt = l
    return creator, fmt


# --------------------------------------------------------------------------
# identify
# --------------------------------------------------------------------------

def cmd_identify(a):
    creator, fmt = read_emit_version(a.dir)
    if fmt is None:
        print("ERROR: no readable %s/emit/version" % a.dir, file=sys.stderr)
        return 2
    print("intermediate directory : %s" % a.dir)
    print("created by             : %s" % (creator or "(not recorded)"))
    print("emit format            : %s" % fmt)

    if not a.installs:
        print("\nPass --installs '<glob>' to test which installations can open it.")
        return 0

    print("\nNOTE: run this against a COPY. Coverity tools take write locks in the idir.")
    cands = []
    for g in a.installs:
        cands.extend(sorted(globmod.glob(g)))
    if not cands:
        print("no installs matched", file=sys.stderr)
        return 2

    print("\n%-42s %-10s %-5s %s" % ("INSTALL", "EXPECTS", "RC", "VERDICT"))
    ok = []
    for inst in cands:
        exe = tool(os.path.join(inst, "bin"), "cov-manage-emit")
        if not os.path.isfile(exe):
            continue
        rc, out = run([exe, "--dir", a.dir, "list"])
        m = re.search(r"Expected version number is (\d+)", out)
        expects = m.group(1) if m else fmt
        verdict = "COMPATIBLE" if rc == 0 else "refuses"
        if rc == 0:
            ok.append(inst)
        print("%-42s %-10s %-5s %s" % (os.path.basename(inst), expects, rc, verdict))

    print()
    if ok:
        print("Use as the OLD-side install: %s" % ok[0])
    else:
        print("No installed version can open this idir. Obtaining %s is the user's"
              % (creator or "the matching version"))
        print("decision -- do not work around it.")
    return 0


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------

def cmd_extract(a):
    exe = tool(a.bin, "cov-manage-emit")
    rc, out = run([exe, "--dir", a.dir, "list-capture-invocations"])
    if rc != 0:
        sys.stderr.write(out)
        print("\nERROR: cov-manage-emit rc=%d. Wrong version for this idir? "
              "Run `identify` first." % rc, file=sys.stderr)
        return 2
    try:
        d = json.loads(out)
    except ValueError:
        sys.stderr.write(out[:2000])
        print("\nERROR: output was not JSON.", file=sys.stderr)
        return 2

    files = {f["id"]: _slash(f.get("case-preserved") or f.get("case-normalized"))
             for f in d.get("files", [])}
    tr = {t["id"]: t for t in d.get("cov-translate-invocations", [])}
    em = {e["id"]: e for e in d.get("cov-emit-invocations", [])}

    pairs = []
    for tu in d.get("translation-units", []):
        ti = tu.get("cov-translate-invocation-id")
        ei = tu.get("cov-emit-invocation-id")
        if ti not in tr or ei not in em:
            continue
        T = tr[ti]["process-invocation"]
        E = em[ei]["process-invocation"]
        pairs.append({
            "tu_id": tu.get("id"),
            "kind": tu.get("kind"),
            "emit_failed": tu.get("emit-failed"),
            "primary": files.get(tu.get("primary-file-id")),
            "translate_cwd": files.get(T.get("working-directory-id")),
            "translate_argv": T.get("command-line"),
            "emit_argv": E.get("command-line"),
            "platform": T.get("platform"),
            "input_file_count": len(tu.get("input-files", [])),
        })

    meta = {
        "source_idir": a.dir,
        "dump_version": d.get("version"),
        "metrics": d.get("metrics"),
        "pair_count": len(pairs),
        "pairs": pairs,
    }
    if a.with_env:
        meta["environment_variables"] = d.get("environment-variables")
        meta["environment_variable_blocks"] = d.get("environment-variable-blocks")

    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)

    print("extracted %d pairs -> %s" % (len(pairs), a.out))
    print("metrics: %s" % json.dumps(d.get("metrics")))
    if a.with_env:
        print("\n*** --with-env included FULL BUILD ENVIRONMENTS (PATH and anything")
        print("*** else in scope, possibly secrets). Check before forwarding this file.")
    else:
        print("environments omitted; pass --with-env if you need them (see security note)")
    return 0


# --------------------------------------------------------------------------
# probe
# --------------------------------------------------------------------------

SOURCE_EXT = (".c", ".cc", ".cpp", ".cxx", ".c++", ".C", ".m", ".mm")


def select(pairs, index):
    if index == "all":
        return list(range(len(pairs)))
    return [int(x) for x in index.split(",")]


def build_probe_argv(pair, translate_exe, work_src, empty_name):
    """Recorded translate argv with argv[0] and the source swapped."""
    argv = list(pair["translate_argv"])
    argv[0] = translate_exe
    out = []
    for t in argv:
        base = os.path.basename(_slash(t))
        if base == os.path.basename(_slash(pair["primary"] or "")) or \
           (t.endswith(SOURCE_EXT) and not t.startswith("-")):
            out.append(empty_name)
        else:
            out.append(t)
    return out


def cmd_probe(a):
    meta = json.load(open(a.pairs, encoding="utf-8"))
    pairs = meta["pairs"]
    idxs = select(pairs, a.index)

    os.makedirs(a.work, exist_ok=True)
    translate_exe = tool(a.bin, "cov-translate")

    cfg = a.config
    if not cfg:
        cfg_dir = os.path.join(a.work, "cfg")
        os.makedirs(cfg_dir, exist_ok=True)
        cfg = os.path.join(cfg_dir, "coverity_config.xml")
        if not os.path.isfile(cfg):
            cc = tool(a.bin, "cov-configure")
            rc, out = run([cc, "--config", cfg, "--" + a.auto_config])
            if rc != 0:
                sys.stderr.write(out)
                print("ERROR: cov-configure rc=%d" % rc, file=sys.stderr)
                return 2
            print("created template config (%s) at %s" % (a.auto_config, cfg))
        # rule 1 / control fidelity: warn about user_nodefs.h asymmetry
        inst_cfg = os.path.join(os.path.dirname(a.bin.rstrip("/\\")), "config", "user_nodefs.h")
        if os.path.isfile(inst_cfg) and not os.path.isfile(
                os.path.join(os.path.dirname(cfg), "user_nodefs.h")):
            print("WARNING: this install ships config/user_nodefs.h but the probe config")
            print("         directory has none. If the original build used the install's")
            print("         own config dir, expect a spurious --preinclude difference.")
            print("         See references/transformation-probe.md.")

    results = []
    for i in idxs:
        p = pairs[i]
        cwd = p["translate_cwd"] or "/"
        leaf = os.path.basename(cwd.rstrip("/")) or "src"
        src_dir = os.path.join(a.work, "tree", leaf)
        os.makedirs(src_dir, exist_ok=True)

        # make relative -I targets exist so include resolution has the same shape
        for t in p["translate_argv"]:
            if t.startswith("-I") and len(t) > 2:
                rel = t[2:]
                if not os.path.isabs(rel) and not re.match(r"^[A-Za-z]:", rel):
                    try:
                        os.makedirs(os.path.normpath(os.path.join(src_dir, rel)), exist_ok=True)
                    except OSError:
                        pass

        empty = "empty" + (".cpp" if (p.get("kind") or "C").upper().startswith("C++") else ".c")
        open(os.path.join(src_dir, empty), "w").close()

        argv = build_probe_argv(p, translate_exe, src_dir, empty)
        argv = [argv[0], "--dir", os.path.join(a.work, "idir_probe"),
                "--config", cfg, "--dryrun"] + argv[1:]

        rc, out = run(argv, cwd=src_dir)
        emit_line = None
        for line in out.splitlines():
            s = line.strip()
            if "cov-emit" in s and (" --dir=" in s or s.startswith(("/", "\\")) or ":" in s[:3]):
                emit_line = s
        results.append({
            "pair_index": i,
            "tu_id": p["tu_id"],
            "primary": p["primary"],
            "kind": p["kind"],
            "rc": rc,
            "emit_argv": emit_line.split() if emit_line else None,
            "probe_source": empty,
            "stdout_tail": out.splitlines()[-6:] if emit_line is None else None,
        })
        status = "ok" if emit_line else "NO EMIT LINE (rc=%d)" % rc
        print("[%3d] tu=%-4s %-40s %s" % (i, p["tu_id"],
                                          os.path.basename(p["primary"] or "?"), status))

    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump({"bin": a.bin, "config": cfg, "results": results}, fh, indent=1)
    print("\nwrote %s" % a.out)
    miss = [r for r in results if not r["emit_argv"]]
    if miss:
        print("WARNING: %d probe(s) produced no cov-emit line. Inspect stdout_tail."
              % len(miss))
    return 0


# --------------------------------------------------------------------------
# delta
# --------------------------------------------------------------------------

def cmd_delta(a):
    import difflib
    meta = json.load(open(a.pairs, encoding="utf-8"))
    gen = json.load(open(a.generated, encoding="utf-8"))
    pairs = meta["pairs"]

    any_diff = False
    report = []
    for r in gen["results"]:
        if not r["emit_argv"]:
            print("pair %d (%s): NO GENERATED LINE -- probe failed" %
                  (r["pair_index"], r["primary"]))
            any_diff = True
            continue
        p = pairs[r["pair_index"]]
        rec = normalize(p["emit_argv"], p["primary"])
        new = normalize(r["emit_argv"], r["probe_source"])

        if rec == new:
            print("pair %-3d %-38s IDENTITY  (%d tokens)" %
                  (r["pair_index"], os.path.basename(p["primary"] or "?"), len(rec)))
            report.append({"pair_index": r["pair_index"], "verdict": "IDENTITY",
                           "tokens": len(rec), "diff": []})
            continue

        any_diff = True
        print("pair %-3d %-38s DELTA     (%d -> %d tokens)" %
              (r["pair_index"], os.path.basename(p["primary"] or "?"), len(rec), len(new)))
        diff = []
        for line in difflib.unified_diff(rec, new, "recorded", "generated",
                                         lineterm="", n=a.context):
            if line.startswith(("---", "+++", "@@")):
                continue
            print("    %s" % line)
            if line[:1] in "+-":
                diff.append({"side": "recorded" if line[0] == "-" else "generated",
                             "token": line[1:], "class": classify(line[1:])})
        for d in diff:
            if d["class"] == "semantic":
                print("    ^ %-14s SEMANTIC -- requires an explicit accept-or-pin decision"
                      % d["token"])
        report.append({"pair_index": r["pair_index"], "verdict": "DELTA",
                       "diff": diff})

    print()
    if not any_diff:
        print("VERDICT: IDENTITY across %d probed pair(s)." % len(gen["results"]))
        print("If this was the control, the normalization is sufficient; proceed.")
    else:
        print("VERDICT: DELTA. Classify every differing token before replaying.")
        print("If this was the CONTROL, stop -- fix the environment first;")
        print("a cross-version delta measured without a passing control is")
        print("uninterpretable. See references/transformation-probe.md.")

    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as fh:
            json.dump({"recorded_from": meta.get("source_idir"),
                       "generated_by": gen.get("bin"),
                       "results": report}, fh, indent=1)
        print("\nwrote %s" % a.json_out)
    return 0 if not any_diff else 1


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("identify", help="what wrote this idir, and who can open it")
    p.add_argument("--dir", required=True)
    p.add_argument("--installs", nargs="*", default=[],
                   help="glob(s) of installation roots, e.g. '/c/Coverity/cov-analysis-*'")
    p.set_defaults(fn=cmd_identify)

    p = sub.add_parser("extract", help="pull (translate, emit) pairs from an idir")
    p.add_argument("--bin", required=True, help="bin/ of an install matching the emit format")
    p.add_argument("--dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--with-env", action="store_true",
                   help="include full build environments (see security note)")
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("probe", help="re-run recorded inputs under an install")
    p.add_argument("--pairs", required=True)
    p.add_argument("--bin", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--index", default="0", help="'all', or comma-separated indices")
    p.add_argument("--config", help="existing coverity_config.xml; else one is created")
    p.add_argument("--auto-config", default="gcc",
                   help="language shortcut for the generated template config")
    p.set_defaults(fn=cmd_probe)

    p = sub.add_parser("delta", help="normalize and diff recorded vs generated")
    p.add_argument("--pairs", required=True)
    p.add_argument("--generated", required=True)
    p.add_argument("--context", type=int, default=2)
    p.add_argument("--json-out")
    p.set_defaults(fn=cmd_delta)

    a = ap.parse_args()
    if not getattr(a, "fn", None):
        ap.print_help()
        return 2
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
