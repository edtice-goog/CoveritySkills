#!/usr/bin/env python3
"""The router: extraction-verification or harness-verification for one finding.

    verify_route.py --manifest <dir> --origin pathout|native|bycatch [--compile] [--out route.json]

Decides AFTER the method decision (Methods: decide first). Inputs, in order:
  1. origin: a candidate from a path-insensitive shape (pathout) is a large
     function whose behaviour depends on values earlier calls produced; the
     slice set is the design for it -> extraction. A native checker's finding
     or a bycatch -> try harness first.
  2. the manifest's notes (C++ construction; captured headers the emit could
     not supply; anything the manifest tool flagged) -> decline harness.
  3. --compile: try `clang -fsyntax-only` on tu.c with the recovered flags,
     from the TU's directory. A failure is a legitimate routing input and is
     recorded verbatim (first diagnostic). On Windows a TU with POSIX paths is
     tried under WSL.
  4. externals: how many have models (a count, not a decline: unmodelled
     externals get generic stubs and weaken the verdict, and the record says so).
A static target does not decline the route: fz_harness.py includes the TU
rather than linking it, so the driver can call it.

Prints the decision and the reason; writes route.json when --out is given.
Exit 0 either way. The decision is advice to the run, which records it.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fz_harness import compiler_flags  # noqa: E402


def try_compile(man, mdir):
    lang = man.get("language", "c")
    tu = os.path.join(mdir, "tu.cpp" if lang == "c++" else "tu.c")
    source = man.get("source", "")
    cwd = man.get("cwd") or (os.path.dirname(source) if source else ".")
    flags = compiler_flags(man.get("compiler_invocation") or man.get("flags") or [])
    posix = source.startswith("/")
    if posix and os.name == "nt":
        tup = re.sub(r"^([A-Za-z]):[\\/]", lambda m: "/mnt/%s/" % m.group(1).lower(), os.path.abspath(tu)).replace("\\", "/")
        cmd = ["wsl", "--cd", cwd, "clang", "-fsyntax-only", "-Wno-everything"] + flags + [tup]
        run_cwd = None
    elif posix:
        cmd = ["clang", "-fsyntax-only", "-Wno-everything"] + flags + [tu]
        run_cwd = cwd
    else:
        cmd = ["clang-cl", "-fsyntax-only"] + flags + [os.path.abspath(tu)]
        run_cwd = cwd if os.path.isdir(cwd) else None
    try:
        p = subprocess.run(cmd, cwd=run_cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    except FileNotFoundError as e:
        return False, "compiler not found: %s" % e, " ".join(cmd)
    except subprocess.TimeoutExpired:
        return False, "compile attempt timed out", " ".join(cmd)
    if p.returncode == 0:
        return True, "compiles with the recovered flags", " ".join(cmd)
    diag = [l for l in (p.stderr + p.stdout).splitlines() if "error" in l.lower()]
    return False, (diag[0].strip() if diag else (p.stderr or p.stdout).strip().splitlines()[0] if (p.stderr or p.stdout).strip() else "exit %d" % p.returncode), " ".join(cmd)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--origin", required=True, choices=["pathout", "native", "bycatch"],
                    help="where the finding came from: a path-insensitive shape (pathout), a native checker, or a bycatch of a run")
    ap.add_argument("--compile", action="store_true", help="try compiling tu.c with the recovered flags and use the outcome")
    ap.add_argument("--out", help="write the decision as JSON here")
    a = ap.parse_args()
    man = json.load(open(os.path.join(a.manifest, "manifest.json"), encoding="utf-8"))
    externals = man.get("externals", [])
    n_ext = len(externals)
    n_mod = sum(1 for e in externals if isinstance(e, dict) and e.get("has_model"))
    target = man.get("target") or {}
    notes = list(man.get("notes", []))
    rec = {"origin": a.origin, "tu": man.get("tu"), "target": target.get("name"), "target_static": bool(target.get("static")),
           "externals": n_ext, "externals_with_model": n_mod, "manifest_notes": notes, "compile_attempt": None}

    if a.origin == "pathout":
        rec.update(route="extraction", reason="a candidate from a path-insensitive shape: a large function whose behaviour "
                   "depends on values earlier calls produced; the slice set is the design for it")
    else:
        declines = []
        if man.get("language") == "c++" and any("construct" in n.lower() for n in notes):
            declines.append("C++ construction the driver cannot reproduce: " + "; ".join(n for n in notes if "construct" in n.lower()))
        compiled = None
        if a.compile:
            ok, why, cmd = try_compile(man, a.manifest)
            rec["compile_attempt"] = {"ok": ok, "outcome": why, "command": cmd}
            compiled = ok
            if not ok:
                declines.append("tu.c does not compile with the recovered flags: " + why)
        # a manifest note about headers the emit could not supply, unless the
        # compile attempt already said the same thing in the compiler's words
        hdr = [n for n in notes if "header" in n.lower() and not (compiled is False and "did not compile" in n)]
        if hdr:
            declines.append("; ".join(hdr))
        if declines:
            rec.update(route="extraction", reason="harness declined (%s); falling back to extraction: the slice set from the emit"
                       % "; ".join(declines), harness_declined=declines)
        else:
            rec.update(route="harness", reason="a %s finding; the TU compiles as-is%s; %d external%s, %d with a model%s"
                       % (a.origin, " with the recovered flags" if a.compile else " (not tried: pass --compile)",
                          n_ext, "" if n_ext == 1 else "s", n_mod,
                          "" if n_mod == n_ext else " (the rest get generic stubs, which weakens a verdict that relies on them)"))
        if target.get("static"):
            rec["note"] = "the target is static: the harness route includes the TU rather than linking it, so the driver can call it"
    print("route   : %s" % rec["route"])
    print("reason  : %s" % rec["reason"])
    if rec.get("compile_attempt"):
        print("compile : %s" % rec["compile_attempt"]["outcome"])
    if rec.get("note"):
        print("note    : %s" % rec["note"])
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rec, f, indent=1)


if __name__ == "__main__":
    main()
