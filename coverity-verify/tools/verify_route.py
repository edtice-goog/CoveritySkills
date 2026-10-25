#!/usr/bin/env python3
"""The router: does the PREFERRED route apply to this finding's program?

    verify_route.py --manifest <dir> [--route harness|extraction] [--compile] [--out route.json]

The caller names the route it prefers: coverity-triage's table row carries
it for a batch; a CID or a findings-file entry given directly takes it as
--route. The default is HARNESS, the less expensive route. The router does
not choose a route; it checks whether the preferred one applies to this
program, and records the reason when it does not. Inputs, in order:
  1. the manifest's notes (captured headers the emit could not supply; C++
     construction the driver cannot reproduce; anything the manifest tool
     flagged) -> harness does not apply.
  2. --compile: `clang -fsyntax-only` on tu.c with the recovered flags, from
     the TU's directory (under WSL for a Linux capture). A failure is recorded
     in the compiler's words -> harness does not apply.
  3. externals without a model: a count in the record, never a reason (they
     get generic stubs, which weakens a verdict that relies on them).
A static target does not stop the harness route: fz_harness.py includes the
TU instead of linking it, so the driver can call the function.

When the preferred route does not apply the router NEVER falls back on its
own: `applicable` is false, `route` is null, and the caller decides.
Interactive: say why, ask whether to run the other route. Non-interactive
(an API call, a scheduled task) or unsure: report the reason, record the
finding as not verified for that reason, stop. Exit 0 either way.
"""
import argparse
import json
import os
import re
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
    text = (p.stderr + p.stdout)
    diag = [l for l in text.splitlines() if "error" in l.lower()]
    first = text.strip().splitlines()[0] if text.strip() else "exit %d" % p.returncode
    return False, (diag[0].strip() if diag else first), " ".join(cmd)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--route", default="harness", choices=["harness", "extraction"],
                    help="the route the caller prefers (default harness, the less expensive one)")
    ap.add_argument("--compile", action="store_true", help="try compiling tu.c with the recovered flags and use the outcome")
    ap.add_argument("--out", help="write the decision as JSON here")
    a = ap.parse_args()
    man = json.load(open(os.path.join(a.manifest, "manifest.json"), encoding="utf-8"))
    externals = man.get("externals", [])
    n_ext = len(externals)
    n_mod = sum(1 for e in externals if isinstance(e, dict) and e.get("has_model"))
    n_libc = sum(1 for e in externals if isinstance(e, dict) and e.get("libc"))
    target = man.get("target") or {}
    notes = list(man.get("notes", []))
    rec = {"preferred": a.route, "tu": man.get("tu"), "target": target.get("name"), "target_static": bool(target.get("static")),
           "externals": n_ext, "externals_with_model": n_mod, "externals_libc": n_libc,
           "manifest_notes": notes, "compile_attempt": None}

    if a.route == "extraction":
        rec.update(route="extraction", applicable=True,
                   reason="the caller prefers extraction: the slice set from the emit, model stubs outside it")
    else:
        blockers = []
        if man.get("language") == "c++" and any("construct" in n.lower() for n in notes):
            blockers.append("C++ construction the driver cannot reproduce: " + "; ".join(n for n in notes if "construct" in n.lower()))
        compiled = None
        if a.compile:
            ok, why, cmd = try_compile(man, a.manifest)
            rec["compile_attempt"] = {"ok": ok, "outcome": why, "command": cmd}
            compiled = ok
            if not ok:
                blockers.append("the TU does not compile with the recovered flags: " + why)
        hdr = [n for n in notes if "header" in n.lower() and not (compiled is False and "did not compile" in n)]
        if hdr:
            blockers.append("; ".join(hdr))
        if blockers:
            rec.update(route=None, applicable=False, blockers=blockers,
                       reason="the preferred route, harness, does not apply to this program: " + "; ".join(blockers),
                       next_step="not decided here. Interactive session: ask whether to run extraction instead. "
                                 "Non-interactive, or unsure: record the finding as not verified for this reason and stop.")
        else:
            rec.update(route="harness", applicable=True,
                       reason="the preferred route applies: the TU compiles as-is%s; %d external%s (%d with a model, %d libc%s)"
                       % (" with the recovered flags" if a.compile else " (compile not tried: pass --compile)",
                          n_ext, "" if n_ext == 1 else "s", n_mod, n_libc,
                          "" if n_mod + n_libc >= n_ext else "; the rest get generic stubs, which weakens a verdict that relies on them"))
        if target.get("static"):
            rec["note"] = "the target is static: the harness route includes the TU rather than linking it, so the driver can call it"
    print("preferred : %s" % a.route)
    print("route     : %s" % (rec["route"] if rec.get("applicable") else "NONE -- the preferred route does not apply; stopping here is the default"))
    print("reason    : %s" % rec["reason"])
    if rec.get("compile_attempt"):
        print("compile   : %s" % rec["compile_attempt"]["outcome"])
    if rec.get("note"):
        print("note      : %s" % rec["note"])
    if not rec.get("applicable"):
        print("next step : %s" % rec["next_step"])
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rec, f, indent=1)


if __name__ == "__main__":
    main()
