#!/usr/bin/env python3
"""Describe one translation unit of a Coverity intermediate directory for the
harness route of verification: the REAL source compiled as-is with its
recorded flags, a driver linked in, the target run unchanged, and stubs only
for what the TU does not define.

    tu_manifest.py --dir <idir> --bin <install>/bin --tu <N> --name <fn> --out <dir> [--models <dir>]

Writes, under --out:

    manifest.json   what the emit knows about the TU: the recorded compile
                    line and its parts, the working directory and platform
                    of the capture, every function the TU defines (with
                    `static` and its location), every function it calls but
                    does not define (the externals a driver must supply or
                    stub, marked library/project and, with --models, whether a
                    saved derived model exists), the target, and NOTES: facts
                    that predict the route will not work
    tu.c / tu.cpp   the primary source, byte for byte (the stored copy that
                    extract-files writes; print-source only as a fallback,
                    since its stdout is text-mode on Windows)
    files/          every file the TU read, from extract-files, in the
                    directory layout the capture saw (drive letter and
                    leading slash removed): the project headers, the system
                    headers, the configuration's compat headers

Nothing here slices or rewrites. The tool reports; the verification router
decides. It exits 0 with notes when the route looks unworkable, and non-zero
only when the TU or the function does not exist or a tool failed.

No name from --name reaches a filename. Pure standard library, plus the
sibling slice_function.py for the emit helpers.
"""

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from slice_function import (manage_emit, split_recorded_invocation, source_spelling,  # noqa: E402
                            is_system_path, RE_LOC, Slice)


def manage_emit_bytes(bin_dir, idir, args):
    exe = os.path.join(bin_dir, "cov-manage-emit")
    if os.name == "nt" and os.path.exists(exe + ".exe"):
        exe += ".exe"
    p = subprocess.run([exe, "--dir", idir, "--ticker-mode", "none"] + args, capture_output=True)
    return p.stdout


# --------------------------------------------------------------------------
# the recorded compilation

def compilation(bin_dir, idir, tu):
    # the plain form prints the three invocations; --detailed replaces them
    # with the process records (working directory, platform, exit code)
    out = manage_emit(bin_dir, idir, ["--tu", str(tu), "print-compilation-info"])
    out += "\n" + manage_emit(bin_dir, idir, ["--tu", str(tu), "print-compilation-info", "--detailed"])
    rec = {"cov_emit_invocation": None, "compiler_invocation": None, "build_invocation": None,
           "working_directory": None, "platform": None}
    for l in out.splitlines():
        s = l.strip()
        for key, pre in (("cov_emit_invocation", "cov-emit invocation:"),
                         ("compiler_invocation", "compiler invocation:"),
                         ("build_invocation", "build invocation:")):
            if s.startswith(pre) and rec[key] is None:
                rec[key] = s[len(pre):].strip()
        if s.startswith("Working directory:") and rec["working_directory"] is None:
            rec["working_directory"] = s.split(":", 1)[1].strip()
        if s.startswith("Platform:") and rec["platform"] is None:
            rec["platform"] = s.split(":", 1)[1].strip()
    if not rec["cov_emit_invocation"]:
        return None
    toks = split_recorded_invocation(rec["cov_emit_invocation"])
    rec["cov_emit"] = toks[0]
    rec["source_as_invoked"] = toks[-1]
    flags, includes, sys_inc, defines, pre = [], [], [], [], []
    skip = None
    for t in toks[1:-1]:
        if skip:
            kind, skip = skip, None
            {"I": includes, "S": sys_inc, "D": defines, "P": pre, "X": []}[kind].append(t)
            if kind != "X":
                flags.append(t)
            continue
        if t.startswith("--dir=") or t.startswith("--ignore_path="):
            continue
        if t in ("--dir", "--ignore_path"):
            skip = "X"
            continue
        if t.startswith("-I") and len(t) > 2:
            includes.append(t[2:])
        elif t == "-I":
            skip = "I"
        elif t.startswith("--sys_include="):
            sys_inc.append(t.split("=", 1)[1])
        elif t == "--sys_include":
            skip = "S"
        elif t.startswith("-D") and len(t) > 2:
            defines.append(t[2:])
        elif t == "-D":
            skip = "D"
        elif t.startswith("-U") and len(t) > 2:
            defines.append("-U" + t[2:])
        elif t == "--pre_preinclude":
            skip = "P"
        elif t.startswith("--pre_preinclude="):
            pre.append(t.split("=", 1)[1])
        flags.append(t)
    rec.update({"flags": flags, "include_paths": includes, "sys_includes": sys_inc,
                "defines_from_build": defines, "pre_preinclude": pre,
                "language": "c++" if "--c++" in flags else "c"})
    m = re.search(r"--comp_ver\s+(\S+)", rec["cov_emit_invocation"])
    rec["compiler_version"] = m.group(1) if m else None
    rec["compiler_family"] = ("gcc" if "--gcc" in flags else "msvc" if "--microsoft" in flags
                              else "clang" if "--clang" in flags else None)
    return rec


# --------------------------------------------------------------------------
# the TU's files

def source_files(bin_dir, idir, tu):
    out = manage_emit(bin_dir, idir, ["--tu", str(tu), "print-source-files"])
    primary, files = None, []
    for l in out.splitlines():
        m = re.match(r"^\s*(Primary SF|Source file)\s*:\s*(.*?)\s*\(row ID \d+\)", l)
        if m:
            p = m.group(2).strip()
            files.append(p)
            if m.group(1) == "Primary SF":
                primary = p
    return primary, files


def local_relative(path):
    """Where extract-files puts a captured path, relative to its output dir:
    the drive letter (if any) and the leading slash removed, '/' separators."""
    p = path.replace("\\", "/")
    p = re.sub(r"^[A-Za-z]:", "", p)
    return p.lstrip("/")


def extract_all(bin_dir, idir, tu, dest):
    out = manage_emit(bin_dir, idir, ["--tu", str(tu), "extract-files", "--output-dir", dest, "--regex", "."])
    return [l.split("Extracting", 1)[1].strip() for l in out.splitlines() if l.strip().startswith("Extracting")]


def primary_source_bytes(bin_dir, idir, tu):
    """print-source: three framing lines (`Translation unit:`, `N -> path`,
    `Primary SF : ...`), then the file. On Windows the tool's stdout is in
    text mode, so a CRLF source comes back as CR CR LF: not byte for byte.
    extract-files writes the stored bytes; this is the fallback."""
    raw = manage_emit_bytes(bin_dir, idir, ["--tu", str(tu), "print-source"])
    parts = raw.split(b"\n", 3)
    if len(parts) < 4 or not parts[2].lstrip().startswith(b"Primary SF"):
        return None
    body = parts[3]
    if os.name == "nt":
        body = body.replace(b"\r\r\n", b"\r\n")
    return body


def long_path(p):
    """A path Python can open past the 260-character limit on Windows."""
    if os.name == "nt" and len(p) > 240 and not p.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(p)
    return p


# --------------------------------------------------------------------------
# functions

HEADER_RE = re.compile(r"^ \* Matching function: (?P<disp>.+?)(?: /\*(?P<mangled>_Z[^*]+)\*/)?\s*$")


def functions_defined(bin_dir, idir, tu, primary):
    """Every function with a definition in the TU, from one
    --print-definitions dump: name, mangled name (C++), file, line, whether
    `static`, whether defined in the primary source or in a header, and the
    signature line."""
    out = manage_emit(bin_dir, idir, ["--tu", str(tu), "find", ".", "--kind", "f", "--print-definitions"])
    blocks = out.split("/*\n * Matching function: ")
    funcs = []
    for b in blocks[1:]:
        body = "/*\n * Matching function: " + b
        lines = body.split("\n")
        m = HEADER_RE.match(lines[1])
        if not m:
            continue
        disp, mangled = m.group("disp").strip(), m.group("mangled")
        loc = None
        for l in lines[2:6]:
            cand = l.strip().lstrip("*").strip()      # ` *   path:line:col-...`
            if RE_LOC.match(cand):
                loc = cand
                break
        file_, line = None, None
        if loc:
            lm = re.match(r"^(.*?):(\d+):\d+-", loc)
            if lm:
                file_, line = lm.group(1), int(lm.group(2))
        head, sig, rest = Slice.split_signature(Slice.respell_header(body))
        sig = " ".join(sig[:-1].split()) if sig else None
        static = bool(sig and re.match(r"^(?:(?:static|inline|__inline__|__inline)\s+)*static\b", sig))
        name = mangled or disp.split("(")[0].split("::")[-1].strip()
        funcs.append({"name": name, "display": disp, "mangled": mangled, "static": static,
                      "inline": bool(sig and re.search(r"\binline\b|\b__inline__?\b", sig.split("(")[0])),
                      "file": file_, "line": line, "in_primary": bool(file_ and primary and
                                                                      os.path.normcase(file_) == os.path.normcase(primary)),
                      "signature": sig})
    return funcs


def externals(bin_dir, idir, tu, defined_names, sys_includes):
    """Functions the TU calls but does not define, from one --print-callees
    dump: a callee entry without a `defined in TU` line."""
    out = manage_emit(bin_dir, idir, ["--tu", str(tu), "find", ".", "--kind", "f", "--print-callees"])
    ext = {}
    cur = None
    for l in out.splitlines():
        s = l.strip()
        if s.startswith("Matching function:"):
            cur = None
        elif s.startswith("Call to: "):
            sig = s[len("Call to: "):]
            mm = re.search(r"/\*(_Z[^*]+)\*/", sig)
            key = mm.group(1) if mm else sig.split(" /*")[0].split("(")[0].split("::")[-1].strip()
            cur = key
            if key not in defined_names:
                ext.setdefault(key, {"name": key, "display": sig.split(" /*")[0].strip(), "declared_at": None,
                                     "kind": "unknown", "defined_in_tu": False})
        elif cur and RE_LOC.match(s):
            if cur in ext and ext[cur]["declared_at"] is None:
                ext[cur]["declared_at"] = RE_LOC.match(s).group(1)
                ext[cur]["kind"] = "library" if is_system_path(ext[cur]["declared_at"], sys_includes) else "project"
        elif cur and s.startswith("defined in TU"):
            # defined in this TU after all (seen through a declaration site)
            ext.pop(cur, None)
    return sorted(ext.values(), key=lambda e: e["name"])


def models_available(models_dir):
    """Function names with a saved derived model under models_dir: the dot
    files say `digraph "name:module"` and `graph [label="name"]`."""
    names = {}
    if not models_dir or not os.path.isdir(models_dir):
        return names
    for fn in os.listdir(models_dir):
        if not fn.endswith(".dot"):
            continue
        try:
            with open(os.path.join(models_dir, fn), encoding="utf-8", errors="replace") as f:
                head = f.read(4096)
        except OSError:
            continue
        m = re.search(r'^digraph "([^":]+):(\w+)"', head, re.M)
        if m:
            names.setdefault(m.group(1), []).append(m.group(2))
    return names


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--bin", required=True, help="<install>/bin of the version that wrote the idir")
    ap.add_argument("--tu", required=True, type=int)
    ap.add_argument("--name", required=True, help="the target function, as the analysis log spells it")
    ap.add_argument("--out", required=True, help="output directory (manifest.json, tu.c, files/)")
    ap.add_argument("--models", help="directory of cov-find-function --save output; externals with a model are marked")
    ap.add_argument("--no-files", action="store_true", help="skip extract-files (manifest and tu.c only)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    notes = []

    rec = compilation(a.bin, a.dir, a.tu)
    if rec is None:
        sys.exit("no recorded cov-emit invocation for TU %d" % a.tu)
    primary, listed = source_files(a.bin, a.dir, a.tu)
    if primary is None:
        sys.exit("TU %d has no primary source file in the emit" % a.tu)
    lang = rec["language"]
    ext_ = ".cpp" if lang == "c++" else ".c"

    # every file the TU read, as stored
    files_dir = os.path.join(a.out, "files")
    extracted = []
    if not a.no_files:
        extracted = extract_all(a.bin, a.dir, a.tu, files_dir)
        missing = [p for p in listed if not os.path.exists(long_path(os.path.join(files_dir, local_relative(p))))]
        if missing:
            notes.append("%d of %d files the TU read are listed by the emit but could not be extracted: %s"
                         % (len(missing), len(listed), ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else "")))
        if len(a.out) + max((len(local_relative(p)) for p in listed), default=0) > 230:
            notes.append("files/ holds paths longer than 240 characters under this --out; a tool without long-path "
                         "support will not open them -- prefer a short --out")

    # the primary source: the extracted copy is the stored bytes; print-source
    # is the fallback (its stdout is text-mode on Windows)
    tu_path = os.path.join(a.out, "tu" + ext_)
    src_bytes = None
    source_of_tu = None
    lp = long_path(os.path.join(files_dir, local_relative(primary)))
    if extracted and os.path.exists(lp):
        with open(lp, "rb") as f:
            src_bytes = f.read()
        source_of_tu = "extract-files"
    else:
        src_bytes = primary_source_bytes(a.bin, a.dir, a.tu)
        source_of_tu = "print-source" if src_bytes is not None else None
        if src_bytes is not None:
            notes.append("tu%s was written from print-source, whose stdout may have translated line endings; "
                         "extract-files gives the stored bytes" % ext_)
    if src_bytes is None:
        notes.append("the emit returned no primary source; tu%s not written" % ext_)
    else:
        with open(tu_path, "wb") as f:
            f.write(src_bytes)

    # functions
    funcs = functions_defined(a.bin, a.dir, a.tu, primary)
    defined = {f["name"] for f in funcs} | {f["display"].split("(")[0].split("::")[-1] for f in funcs}
    ext = externals(a.bin, a.dir, a.tu, defined, rec["sys_includes"])
    models = models_available(a.models)
    for e in ext:
        e["model"] = (source_spelling(e["name"]) in models) or (e["name"] in models) if a.models else None
        e["model_modules"] = models.get(source_spelling(e["name"])) or models.get(e["name"]) if a.models else None

    # the target
    want = a.name
    target = None
    for f in funcs:
        if want in (f["name"], f["mangled"], f["display"].split("(")[0], source_spelling(f["name"])):
            target = f
            break
    if target is None:
        sys.exit("function %s is not defined in TU %d (the emit lists %d definitions there)" % (want, a.tu, len(funcs)))
    if target["static"]:
        notes.append("target is static: a driver linked against tu%s cannot call it by name; it needs a non-static "
                     "caller in the TU, or a wrapper appended to the source" % ext_)
    if not target["in_primary"]:
        notes.append("target is defined in a header (%s), not in the primary source; the harness route compiles the "
                     "TU, which includes it, but the definition is shared with every other TU that includes it"
                     % target["file"])
    if lang == "c++" and "::" in (target["display"] or ""):
        notes.append("C++ class member target: a driver has to construct the object the method runs on")
    if lang == "c++":
        notes.append("C++ translation unit: externals are mangled names; stubs must match the mangling")
    if rec["platform"] and os.name == "nt" and rec["platform"].lower().startswith("linux"):
        notes.append("captured on %s with %s %s: the files/ headers are that platform's; compile tu%s on it (or with the "
                     "recorded cov-emit), not with a Windows toolchain"
                     % (rec["platform"], rec["compiler_family"] or "a compiler", rec["compiler_version"] or "", ext_))
    if a.models:
        unmod = [e["name"] for e in ext if e["kind"] == "project" and not e["model"]]
        if unmod:
            notes.append("%d project external%s without a saved model under --models: %s"
                         % (len(unmod), "s" if len(unmod) > 1 else "", ", ".join(unmod[:8]) + (" ..." if len(unmod) > 8 else "")))
    notes.append("externals lists functions only; globals the TU reads but does not define are not enumerated "
                 "(the emit indexes defined globals, not references)")

    # the local layout: recorded paths -> under files/
    def local(p):
        return os.path.join("files", local_relative(p)).replace("\\", "/")
    cwd = rec["working_directory"]

    def resolve(p):
        if cwd and not re.match(r"^([A-Za-z]:)?[/\\]", p):
            return cwd.rstrip("/") + "/" + p
        return p

    manifest = {
        "tu": a.tu,
        "language": lang,
        "source": primary,
        "source_as_invoked": rec["source_as_invoked"],
        "working_directory": cwd,
        "platform": rec["platform"],
        "compiler": {"family": rec["compiler_family"], "version": rec["compiler_version"],
                     "invocation": rec["compiler_invocation"]},
        "cov_emit": rec["cov_emit"],
        "flags": rec["flags"],
        "include_paths": rec["include_paths"],
        "sys_includes": rec["sys_includes"],
        "pre_preinclude": rec["pre_preinclude"],
        "defines_from_build": rec["defines_from_build"],
        "tu_file": {"path": "tu" + ext_ if src_bytes is not None else None, "bytes_from": source_of_tu},
        "files": {
            "dir": "files" if extracted else None,
            "count_listed": len(listed),
            "count_extracted": len(extracted),
            "layout": "a captured path P is at files/<P without drive letter and leading slash>",
            "source_local": local(primary) if extracted else None,
            "include_paths_local": [local(resolve(p)) for p in rec["include_paths"]] if extracted else None,
            "sys_includes_local": [local(p) for p in rec["sys_includes"]] if extracted else None,
            "pre_preinclude_local": [local(p) for p in rec["pre_preinclude"]] if extracted else None,
        },
        # Two compile lines a harness can start from, both measured on an
        # nginx TU captured under Linux/gcc (CALIBRATION.md): the recorded
        # cov-emit flags with every path remapped under files/ re-emit the TU
        # from files/ alone; a real gcc builds an object from files/ alone at
        # -O0, and at -O needs the platform's own system include directories
        # appended after files/, because glibc opens extra headers under
        # optimization (bits/select2.h) that the capture's front end never saw.
        "compile_hints": {
            "cov_emit_local": ([rec["cov_emit"]] + [
                t for t in rec["flags"]
                if not (t.startswith("-I") or t.startswith("--sys_include") or t == "--pre_preinclude"
                        or t in rec["include_paths"] or t in rec["sys_includes"] or t in rec["pre_preinclude"])]
                + ["-I" + local(resolve(p)) for p in rec["include_paths"]]
                + ["--sys_include=" + local(p) for p in rec["sys_includes"]]
                + sum([["--pre_preinclude", local(p)] for p in rec["pre_preinclude"]], [])
                + [local(primary)]) if extracted else None,
            "gcc_from_files_only": (["gcc", "-c", "-O0", "-nostdinc"]
                                    + ["-D" + d for d in rec["defines_from_build"] if not d.startswith("-U")]
                                    + ["-I" + local(resolve(p)) for p in rec["include_paths"]]
                                    + sum([["-isystem", local(p)] for p in rec["sys_includes"]], [])
                                    + [local(primary)]) if extracted and rec["compiler_family"] == "gcc" else None,
            "note": "run on the capture platform; -O0 compiles from files/ alone, and -O needs the platform's "
                    "system include directories appended after the files/ ones (optimization-only glibc headers "
                    "are not in the capture); the recorded compiler invocation is under compiler.invocation",
        },
        "functions_defined": [{k: f[k] for k in ("name", "display", "static", "inline", "file", "line", "in_primary")}
                              for f in funcs],
        "globals_defined": [],
        "externals": ext,
        "target": {k: target[k] for k in ("name", "display", "static", "line", "file", "in_primary", "signature")},
        "notes": notes,
    }
    gout = manage_emit(a.bin, a.dir, ["--tu", str(a.tu), "find", ".", "--kind", "g"])
    cur = None
    for l in gout.splitlines():
        s = l.strip()
        if s.startswith("Matching global:"):
            cur = {"name": s.split(":", 1)[1].strip(), "line": None}
            manifest["globals_defined"].append(cur)
        elif cur and RE_LOC.match(s):
            lm = re.match(r"^(.*?):(\d+):\d+-", s)
            cur["line"] = int(lm.group(2)) if lm else None
            cur = None

    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)

    print("manifest: %s" % os.path.join(a.out, "manifest.json"))
    print("tu      : TU %d, %s, %s%s" % (a.tu, lang, primary,
                                         (" (tu%s from %s)" % (ext_, source_of_tu)) if src_bytes is not None else " (not written)"))
    print("capture : %s, %s %s, cwd %s" % (rec["platform"] or "?", rec["compiler_family"] or "?",
                                           rec["compiler_version"] or "", cwd or "?"))
    print("files   : %d listed, %d extracted under %s" % (len(listed), len(extracted), files_dir if extracted else "(skipped)"))
    print("defines : %d functions (%d static, %d in headers), %d globals"
          % (len(funcs), sum(1 for f in funcs if f["static"]), sum(1 for f in funcs if not f["in_primary"]),
             len(manifest["globals_defined"])))
    lib = sum(1 for e in ext if e["kind"] == "library")
    print("externs : %d called but not defined here: %d library, %d project%s"
          % (len(ext), lib, len(ext) - lib,
             (", %d with a saved model" % sum(1 for e in ext if e["model"])) if a.models else ""))
    print("target  : %s%s at %s:%s" % (target["display"], " (static)" if target["static"] else "",
                                        target["file"], target["line"]))
    for n in notes:
        print("note    : " + n)


if __name__ == "__main__":
    main()
