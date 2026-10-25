#!/usr/bin/env python3
"""The HARNESS route: assemble a fuzz target from the TU's real source, compiled
as-is with its recorded compiler flags, a driver, and model stubs only for the
externals the TU does not define.

    fz_harness.py --manifest <dir> --models <dir with index.txt> --driver driver.c \
                  --claim '<expr>' --before '<regex of the finding line>' --out <dir> \
                  [--dir <idir> --bin <install>/bin] [--keep a,b] [--semantic ..] [--pin-normal --free ..]

<dir>/manifest.json and <dir>/tu.c (or tu.cpp) come from the TU manifest
(coverity-function-slice/tools/tu_manifest.py). The route is extraction widened to the whole TU
without the pretty-printer: every function the TU defines runs as real code,
and the slice-set rule holds unchanged -- nothing on the finding's path is a
stub, and a stub list naming a function the finding's events touch is
malformed here too.

What is written to --out:
  tu.fz.c     the TU's source with ONE line inserted: the claim, before the
              first line matching --before at or after the target's line
  target.c    prelude (__fz_claim as a call), #include "tu.fz.c", fz_support.h,
              the stubs, the pins, the driver. The TU is INCLUDED, not linked,
              so a static target is callable; route.json records that
  build.sh / build.bat   the compile command, run from the TU's directory so
              relative -I paths resolve
  route.json  route, what ran as code, what was stubbed, the inserted line
"""
import argparse
import json
import os
import re
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import model_stubs  # noqa: E402
from fz_target import LIBC, generic_stub, model_stub, semantic_stub  # noqa: E402

KEEP_FLAG_PREFIXES = ("-D", "-U", "-I", "-std=", "-m32", "-m64", "-fshort-enums", "-fno-short-enums",
                      "-fsigned-char", "-funsigned-char", "-nostdinc", "-fms-extensions", "-fno-builtin")
FLAGS_WITH_ARG = ("-I", "-D", "-U", "-isystem", "-include", "-o", "-MF", "-MT", "-MQ", "-x", "-idirafter", "-iquote")


def manifest_invocation(man):
    """The recorded native compiler invocation (gcc/clang/cl), as the manifest
    carries it: `compiler.invocation` from tu_manifest.py, or a flat
    `compiler_invocation`. Never the cov-emit flags (`flags`): those are the
    front end's, not a compiler's."""
    return man.get("compiler_invocation") or (man.get("compiler") or {}).get("invocation") or ""


def manifest_cwd(man):
    src = man.get("source", "")
    return man.get("cwd") or man.get("working_directory") or (os.path.dirname(src) if src else ".")


def files_flags(man, mdir):
    """Include flags for compiling from the capture's own files (`files/`,
    which tu_manifest.py extracts in the layout the capture saw): the build's
    -I paths and system include directories, relocated under the manifest
    directory. Empty when the manifest carries no files."""
    files = man.get("files") or {}
    if not files.get("dir"):
        return []
    base = os.path.abspath(mdir)
    out = []
    for p in files.get("include_paths_local") or []:
        out.append("-I" + os.path.join(base, p))
    for p in files.get("sys_includes_local") or []:
        out += ["-isystem", os.path.join(base, p)]
    for p in files.get("pre_preinclude_local") or []:
        out += ["-include", os.path.join(base, p)]
    return out


def external_has_model(e):
    return bool(isinstance(e, dict) and (e.get("has_model") or e.get("model")))


def external_is_library(e):
    return bool(isinstance(e, dict) and (e.get("libc") or e.get("kind") == "library"))


def compiler_flags(invocation):
    """The preprocessor- and ABI-relevant part of a recorded compiler invocation:
    -D/-U/-I/-isystem/-include/-std/-m32/-m64 and the char/enum ABI flags. Code
    generation, warnings, debug, dependency and output flags are dropped; the
    compiler name and the source file are dropped."""
    if not invocation:
        return []
    toks = shlex.split(invocation) if isinstance(invocation, str) else list(invocation)
    out = []
    i = 1                                   # toks[0] is the compiler
    while i < len(toks):
        t = toks[i]
        if t in ("-isystem", "-include", "-idirafter", "-iquote") and i + 1 < len(toks):
            out += [t, toks[i + 1]]; i += 2; continue
        if t in ("-I", "-D", "-U") and i + 1 < len(toks):
            out.append(t + toks[i + 1]); i += 2; continue
        if t in ("-o", "-MF", "-MT", "-MQ", "-x") and i + 1 < len(toks):
            i += 2; continue
        if t.startswith(KEEP_FLAG_PREFIXES):
            out.append(t)
        i += 1
    return out


def prototype_from_emit(bin_dir, idir, tu, name, callers=()):
    """A prototype for an external the manifest did not sign, printed the way
    the slicer prints prototypes, from the emit: the function's definition in
    another TU if the capture has one, else the call to it inside one of
    `callers` (functions of this TU; the caller's tree carries the callee's
    type). None when the slicer is not beside this skill or the emit never
    saw the function (a library the build linked but did not compile, with
    no call to it in the functions named)."""
    sl_dir = os.path.join(HERE, "..", "..", "coverity-function-slice", "tools")
    if not os.path.exists(os.path.join(sl_dir, "slice_function.py")):
        return None
    sys.path.insert(0, sl_dir)
    try:
        import slice_function as S  # noqa: E402
    except Exception:
        return None
    P = S.Printer(S.Names(), {}, {}, cxx=False)

    def first_type(dbg):
        roots = S.parse_debug(dbg)
        if not roots:
            return None
        found = []

        def visit(node, path):
            if node.tag == "function_t" and node.get("name") == name and isinstance(node.get("type"), S.Node):
                found.append(node)
        S.walk(roots[0][1], visit)
        return found[0].get("type") if found else None

    queries = [["--tu", str(tu), "find", S.find_regex(name), "--kind", "f", "--print-debug"],
               ["find", S.find_regex(name), "--kind", "f", "--print-debug"]]
    queries += [["--tu", str(tu), "find", S.find_regex(c), "--kind", "f", "--print-debug"] for c in callers]
    for q in queries:
        try:
            dbg = S.manage_emit(bin_dir, idir, q)
        except SystemExit:
            return None
        if "Matching function" not in dbg:
            continue
        t = first_type(dbg)
        if t is not None:
            return P.decl(t, name) + ";"
    return None


def insert_claim(text, before, claim, start_line):
    lines = text.split("\n")
    pat = re.compile(before)
    for i in range(max(0, start_line - 1), len(lines)):
        if pat.search(lines[i]):
            indent = re.match(r"\s*", lines[i]).group(0)
            lines.insert(i, "%s__fz_claim(%s);   /* the finding's claim, checked where the finding is (inserted by fz_harness.py) */" % (indent, claim))
            return "\n".join(lines), i + 1
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True, help="directory holding manifest.json and tu.c|tu.cpp")
    ap.add_argument("--models", required=True, help="directory holding <base>.dot files and index.txt")
    ap.add_argument("--driver", required=True, help="the driver: LLVMFuzzerTestOneInput calling the target")
    ap.add_argument("--claim", help="the finding's claim, as a C expression that must hold")
    ap.add_argument("--before", help="regex of the TU line the claim is checked before (searched from the target's line)")
    ap.add_argument("--dir", help="the idir, for prototypes of externals the manifest does not sign")
    ap.add_argument("--bin", help="<install>/bin of the version that wrote the idir")
    ap.add_argument("--keep", default="", help="comma-separated externals the driver defines")
    ap.add_argument("--semantic", default="", help="comma-separated externals given real copy/alloc semantics")
    ap.add_argument("--pin-normal", action="store_true", help="focused mode: pin every stub to its normal behaviour except --free")
    ap.add_argument("--free", default="")
    ap.add_argument("--from-files", action="store_true",
                    help="compile against the capture's own files (the manifest's files/ directory) instead of the "
                         "source tree: use what the router recorded as compile_mode")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    mdir = a.manifest
    man = json.load(open(os.path.join(mdir, "manifest.json"), encoding="utf-8"))
    lang = man.get("language", "c")
    tu_src = os.path.join(mdir, "tu.cpp" if lang == "c++" else "tu.c")
    text = open(tu_src, encoding="utf-8", errors="replace").read()
    target = man.get("target") or {}
    tname = target.get("name") or man.get("name")
    defined = [f["name"] if isinstance(f, dict) else f for f in man.get("functions_defined", [])]
    externals = man.get("externals", [])
    ext_names = [e["name"] if isinstance(e, dict) else e for e in externals]
    ext_sig = {e["name"]: e.get("signature") for e in externals if isinstance(e, dict) and e.get("signature")}
    data_ext = [d["name"] if isinstance(d, dict) else d for d in man.get("externals_data", [])]
    os.makedirs(a.out, exist_ok=True)

    # 1. the claim, the only edit to the TU's text
    claim_line = None
    if a.claim and a.before:
        new, claim_line = insert_claim(text, a.before, a.claim, int(target.get("line") or 1))
        if new is None:
            sys.exit("--before matched no line of the TU at or after the target's line %s: %s" % (target.get("line"), a.before))
        text = new
    fz_src = os.path.join(a.out, "tu.fz.cpp" if lang == "c++" else "tu.fz.c")
    with open(fz_src, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

    # 2. stubs for the externals only
    index = {}
    ip = os.path.join(a.models, "index.txt")
    if os.path.exists(ip):
        for line in open(ip):
            parts = line.split()
            if len(parts) >= 2:
                index[parts[0]] = parts[1]
    keep = set(x for x in a.keep.split(",") if x)
    semantic = set(x for x in a.semantic.split(",") if x)
    free = set(x for x in a.free.split(",") if x)
    stubs, report, pins = [], [], []
    stubbed, real_libc, by_driver, unsigned_ext = [], [], [], []
    for name in defined:
        if name in index:
            report.append("%-28s defined in the TU: real code; its saved model is IGNORED" % name)
    for name in ext_names:
        if name in defined:
            report.append("%-28s listed as external but defined in the TU: real code" % name)
            continue
        ext = next((e for e in externals if isinstance(e, dict) and e.get("name") == name), {})
        if name in keep:
            report.append("%-28s driver" % name); by_driver.append(name); continue
        if name in LIBC or external_is_library(ext):
            report.append("%-28s real libc" % name); real_libc.append(name); continue
        proto = ext_sig.get(name)
        if proto is None and a.dir and a.bin:
            proto = prototype_from_emit(a.bin, a.dir, man.get("tu"), name)
        if proto is None:
            report.append("%-28s NO PROTOTYPE (manifest carries no signature; emit lookup failed): define it in the driver" % name)
            unsigned_ext.append(name); continue
        if name in semantic:
            s = semantic_stub(name, proto)
            if s:
                report.append("%-28s SEMANTIC stub" % name); stubs.append(s); stubbed.append((name, "semantic")); continue
        base = index.get(name)
        dot = os.path.join(a.models, base + ".dot") if base else None
        if dot and os.path.exists(dot):
            s = model_stub(proto, dot, text)
            n = re.search(r"(\d+) behaviour", s).group(1)
            behs = [re.sub(r"\s+", " ", m.strip()) for m in re.findall(r"/\* model: (.*?) \*/", s)
                    if not m.strip().startswith("dereference(")]
            report.append("%-28s model stub, %s behaviour(s): %s" % (name, n, "  ".join("%d=%s" % (i, b) for i, b in enumerate(behs))))
            stubs.append(s); stubbed.append((name, "model"))
            if a.pin_normal and name not in free and len(behs) > 1:
                bad = ("returnsnull", "negative_return", "<- == -1", "<- < 0")
                normal = [i for i, b in enumerate(behs) if not any(x in b for x in bad)]
                if normal:
                    pins.append((name, normal[0], behs[normal[0]]))
        else:
            report.append("%-28s NO MODEL -> generic stub" % name)
            stubs.append(generic_stub(proto)); stubbed.append((name, "generic"))

    # 3. the target file: the TU included, then the support, stubs, pins, driver
    pin_fn = ["/* focused mode: every stub held to its normal behaviour except --free ones */",
              "static void fz_pins_default(void) {"]
    for name, k, desc in pins:
        pin_fn.append('  FZ_PIN("%s", %d);   /* %s */' % (name, k, desc))
    pin_fn.append("}")
    pin_fn.append("#define FZ_PINS_DEFAULT() do { if (fz_pin_n == 0) fz_pins_default(); } while (0)")
    driver = open(a.driver, encoding="utf-8").read()
    out = ["/* ==== coverity-verify, harness route: the TU as-is, a driver, model stubs for its externals ==== */",
           "#define FZ_HARNESS 1",
           "void fz_claim_hook(int cond, int line, const char *text);",
           "#define __fz_claim(cond) fz_claim_hook(!!(cond), __LINE__, #cond)",
           '#include "%s"   /* the TU, included so a static target is callable; its only edit is the claim line */' % os.path.basename(fz_src),
           '#include "fz_support.h"',
           "\n/* ==== stubs for externals the TU does not define, from their derived models ==== */",
           "\n\n".join(stubs), "\n".join(pin_fn), "\n/* ==== driver ==== */", driver]
    tgt = os.path.join(a.out, "target.cpp" if lang == "c++" else "target.c")
    with open(tgt, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))

    # 4. the build command, from the TU's directory
    flags = compiler_flags(manifest_invocation(man))
    source = man.get("source", "")
    cwd = manifest_cwd(man)
    if a.from_files:
        flags = flags + files_flags(man, mdir)
        cwd = os.path.abspath(mdir)
    posix = source.startswith("/")
    tools = HERE
    if posix:
        tools = re.sub(r"^([A-Za-z]):[\\/]", lambda m: "/mnt/%s/" % m.group(1).lower(), tools).replace("\\", "/")
        outp = re.sub(r"^([A-Za-z]):[\\/]", lambda m: "/mnt/%s/" % m.group(1).lower(), os.path.abspath(a.out)).replace("\\", "/")
        cmd = ["clang", "-g", "-O1", "-fsanitize=fuzzer,address", "-Wno-everything"] + flags + \
              ["-I", tools, "-I", outp, outp + "/" + os.path.basename(tgt), "-o", outp + "/fz"]
        script = os.path.join(a.out, "build.sh")
        with open(script, "w", encoding="utf-8", newline="\n") as f:
            f.write("#!/bin/bash\n# harness route: compile the TU as-is from its own directory, so relative -I paths resolve\n")
            f.write("cd %s && %s\n" % (shlex.quote(cwd), " ".join(shlex.quote(c) for c in cmd)))
    else:
        cmd = ["clang-cl", "-fsanitize=fuzzer,address", "-Zi", "-Od"] + flags + \
              ['-I"%s"' % tools, '-I"%s"' % os.path.abspath(a.out), '"%s"' % os.path.abspath(tgt), '-Fe:"%s"' % os.path.join(os.path.abspath(a.out), "fz.exe")]
        script = os.path.join(a.out, "build.bat")
        with open(script, "w", encoding="utf-8", newline="\r\n") as f:
            f.write("@echo off\r\nrem harness route: compile the TU as-is from its own directory\r\ncd /d \"%s\"\r\n%s\r\n" % (cwd, " ".join(cmd)))

    record = {"route": "harness", "tu": man.get("tu"), "source": source, "target": tname,
              "target_static": bool(target.get("static")), "tu_included_not_linked": True,
              "claim_line_in_tu_fz": claim_line, "as_code": defined,
              "stubbed": [{"name": n, "kind": k} for n, k in stubbed], "real_libc": real_libc,
              "defined_by_driver": by_driver, "externals_without_prototype": unsigned_ext,
              "externals_data_for_driver": data_ext, "compiler_flags_used": flags, "cwd": cwd,
              "compile_mode": "capture_files" if a.from_files else "source_tree",
              "manifest_notes": man.get("notes", [])}
    with open(os.path.join(a.out, "route.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(record, f, indent=1)
    print("written %s (route: harness; %d functions of the TU as code; %d stubbed; %d real libc)%s"
          % (tgt, len(defined), len(stubbed), len(real_libc),
             "  (focused: %d stubs pinned, free: %s)" % (len(pins), ",".join(sorted(free)) or "none") if a.pin_normal else "  (free mode)"))
    print("  target: %s%s; the TU is #included (not linked)%s" % (tname, " (static)" if target.get("static") else "",
          "; claim inserted at %s line %d" % (os.path.basename(fz_src), claim_line) if claim_line else ""))
    for r in report:
        print("  " + r)
    if data_ext:
        print("  globals the TU reads but does not define; the driver must define them: %s" % ", ".join(data_ext))
    print("  build: %s" % script)


if __name__ == "__main__":
    main()
