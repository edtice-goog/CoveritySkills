#!/usr/bin/env python3
"""A stand-in for coverity-function-slice/tools/tu_manifest.py, for this skill's
evals and measurements until that tool lands. Same interface, same output:

    manifest_stub.py --dir <idir> --bin <install>/bin --tu <N> --name <fn> --out <dir> [--models <dir>]

writes <out>/manifest.json and <out>/tu.c (print-source, byte for byte). It
does NOT copy captured headers (the real tool does when the emit can supply
them), so a TU that includes a header outside its -I paths will not compile
from the manifest: that is a legitimate routing input, and the router records
it. Externals are found by compiling tu.c to an object with the recovered flags
and listing its undefined symbols (llvm-nm -u); each is classified as a
function or data by asking the emit; functions get their prototype from the
emit's declaration so the stub printer can use it. Run with Windows clang-cl
for a Windows-captured TU; a POSIX-captured TU is compiled under WSL."""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "..", "tools")
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "coverity-function-slice", "tools"))
from fz_harness import compiler_flags, prototype_from_emit  # noqa: E402
from fz_target import LIBC  # noqa: E402
import slice_function as S  # noqa: E402


def manage(bin_dir, idir, args):
    return S.manage_emit(bin_dir, idir, args)


def compilation_info(bin_dir, idir, tu):
    out = manage(bin_dir, idir, ["--tu", str(tu), "print-compilation-info"])
    src = inv = None
    for l in out.splitlines():
        m = re.match(r"^\s*%d -> (.*)$" % tu, l)
        if m:
            src = m.group(1).strip()
        if "compiler invocation:" in l:
            inv = l.split("compiler invocation:", 1)[1].strip()
    return src, inv


def print_source(bin_dir, idir, tu):
    out = manage(bin_dir, idir, ["--tu", str(tu), "print-source"]).replace("\r\n", "\n")
    # the listing: "Translation unit:", "N -> path", "  Primary SF : path (row ID n)", then the contents
    lines = out.split("\n")
    for i, l in enumerate(lines[:6]):
        if re.match(r"^\s*Primary SF\s*:.*\(row ID \d+\)\s*$", l):
            return "\n".join(lines[i + 1:])
    return out


def defined_functions(bin_dir, idir, tu, text):
    out = manage(bin_dir, idir, ["--tu", str(tu), "find", ".", "--kind", "f"])
    res = []
    for blk in out.split("Matching function: ")[1:]:
        nm = blk.split("\n", 1)[0].strip()
        if "defined in TU %d" % tu not in blk:
            continue
        m = re.search(r"declared at:\s*\n\s*\*?\s*(.*?):(\d+):\d+-", blk)
        line = int(m.group(2)) if m else None
        static = bool(line and re.search(r"\bstatic\b", "\n".join(text.split("\n")[max(0, line - 3):line])))
        res.append({"name": nm, "static": static, "line": line})
    return res


def undefined_symbols(tu_path, flags, cwd, posix):
    obj = tu_path + ".o"
    if posix and os.name == "nt":
        tup = re.sub(r"^([A-Za-z]):[\\/]", lambda m: "/mnt/%s/" % m.group(1).lower(), os.path.abspath(tu_path)).replace("\\", "/")
        c = ["wsl", "--cd", cwd, "clang", "-c", "-Wno-everything"] + flags + [tup, "-o", tup + ".o"]
        n = ["wsl", "nm", "-u", tup + ".o"]          # binutils nm; llvm-nm is versioned under WSL
        run_cwd = None
    elif posix:
        c = ["clang", "-c", "-Wno-everything"] + flags + [tu_path, "-o", obj]; n = ["llvm-nm", "-u", obj]; run_cwd = cwd
    else:
        c = ["clang-cl", "-c", "-w"] + flags + [os.path.abspath(tu_path), "-Fo" + os.path.abspath(obj)]; n = ["llvm-nm", "-u", os.path.abspath(obj)]
        run_cwd = cwd if os.path.isdir(cwd) else None
    p = subprocess.run(c, cwd=run_cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        diag = [l for l in (p.stderr + p.stdout).splitlines() if "error" in l.lower()]
        return None, diag[0].strip() if diag else "compile failed"
    q = subprocess.run(n, capture_output=True, text=True, encoding="utf-8", errors="replace")
    syms = []
    for l in q.stdout.splitlines():
        parts = l.split()
        if parts:
            s = parts[-1]
            s = re.sub(r"^__imp_", "", s)
            # the compiler runtime's own symbols, supplied at link time
            if s.startswith(("__asan", "__sanitizer", "___", "__security", "__chkstk", "_fltused", "__stack_chk",
                             "__GSHandler", "__C_specific", "__cxa", "__gxx", "_Unwind", "__udivti", "__divti")):
                continue
            syms.append(s.lstrip("_") if os.name == "nt" and s.startswith("_") and not s.startswith("__") else s)
    return sorted(set(syms)), None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True); ap.add_argument("--bin", required=True)
    ap.add_argument("--tu", required=True, type=int); ap.add_argument("--name", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--models", help="models dir with index.txt, to mark has_model")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    src, inv = compilation_info(a.bin, a.dir, a.tu)
    text = print_source(a.bin, a.dir, a.tu)
    lang = "c++" if src and src.endswith((".cpp", ".cc", ".cxx", ".C")) else "c"
    tu_path = os.path.join(a.out, "tu.cpp" if lang == "c++" else "tu.c")
    with open(tu_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    notes = []
    posix = bool(src and src.startswith("/"))
    cwd = os.path.dirname(src) if src else "."
    funcs = defined_functions(a.bin, a.dir, a.tu, text)
    tgt = next((f for f in funcs if f["name"] == a.name), None)
    if tgt is None:
        notes.append("target %s is not defined in TU %d" % (a.name, a.tu))
        tgt = {"name": a.name, "static": False, "line": None}
    flags = compiler_flags(inv) if inv else []
    if not inv:
        notes.append("no compiler invocation recorded for this TU; flags unknown")
    syms, err = undefined_symbols(tu_path, flags, cwd, posix)
    externals, data = [], []
    if syms is None:
        notes.append("tu.c did not compile to an object with the recovered flags: %s (externals unknown; captured headers are not supplied by this stand-in)" % err)
    else:
        index = set()
        ip = os.path.join(a.models or "", "index.txt")
        if a.models and os.path.exists(ip):
            index = {l.split()[0] for l in open(ip) if l.strip()}
        defined_names = {f["name"] for f in funcs}
        callers = [f["name"] for f in funcs]
        for s in syms:
            if s in defined_names:
                continue
            if s in LIBC:
                externals.append({"name": s, "has_model": False, "libc": True})
                continue
            proto = prototype_from_emit(a.bin, a.dir, a.tu, s, callers=callers)
            if proto:
                externals.append({"name": s, "has_model": s in index, "signature": proto})
            else:
                data.append({"name": s})
    man = {"tu": a.tu, "language": lang, "source": src, "cwd": cwd, "compiler_invocation": inv,
           "functions_defined": funcs, "externals": externals, "externals_data": data,
           "target": {"name": tgt["name"], "static": tgt["static"], "line": tgt["line"]}, "notes": notes,
           "produced_by": "evals/harness/manifest_stub.py (stand-in for coverity-function-slice/tools/tu_manifest.py)"}
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(man, f, indent=1)
    print("manifest: %s  (TU %d, %s, %d functions defined, %d externals (%d with a model), %d data externals%s)"
          % (os.path.join(a.out, "manifest.json"), a.tu, os.path.basename(src or "?"), len(funcs), len(externals),
             sum(1 for e in externals if e["has_model"]), len(data), "; notes: " + " | ".join(notes) if notes else ""))


if __name__ == "__main__":
    main()
