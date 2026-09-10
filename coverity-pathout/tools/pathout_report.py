#!/usr/bin/env python3
"""PATHOUT report for a Coverity intermediate directory.

Reads what cov-analyze already wrote -- output/analysis-log.txt and
output/FUNCTION.metrics.xml.gz -- and, given the matching installation's
bin directory, pulls each affected function's definition straight out of
the emit with `cov-manage-emit find --print-definitions`.

    pathout_report.py --dir <idir> [--bin <install>/bin] [--out <dir>] [--json]

No text parsing of preprocessed files. The function text comes from the AST
the analyzer itself used.

Pure standard library.
"""

import argparse
import gzip
import json
import os
import re
import subprocess
import sys

# --------------------------------------------------------------------------
# analysis-log.txt

RE_CMDLINE = re.compile(r"^cmdline: command line: (.*)$")
RE_SUMMARY_PCT = re.compile(
    r"^summary: Exceeded path limit of (\d+) paths in ([\d.]+)% of functions")
RE_SUMMARY_COUNT = re.compile(r"^summary: paths_exceeded count: (\d+)")
# wur: gen1059 4 102632 4703 7340 4703 5001 PATHOUT=1 n: setup_env in TU 77
# wur: gen646 15 1058527 ... 38650 PATHOUT=4 nr=20 n: batch 645
RE_WUR = re.compile(
    r"^wur: ([a-z]+)(\d+) .*? (\d+) PATHOUT=(\d+)(?: nr=(\d+))? n: (.+?)(?: in TU (\d+))?(?: with extra_info)?$")
# wur_diagnostics: Pathed out: 5001 paths traversed by REVERSE_INULL in "setup_env(pool *, ...)"
RE_PATHED_OUT = re.compile(
    r"^wur_diagnostics: (?:\w+: )?Pathed out: (\d+) paths traversed by (\S+) in \"(.*)\"$")
RE_ANY_DIAG = re.compile(r"^wur_diagnostics: ")


def parse_log(path):
    info = {
        "cmdline": None, "limit": 5000, "print_paths": False,
        "summary_pct": None, "summary_count": None,
        "named": [], "batches": [], "pathed_out": {}, "diag_lines": 0,
    }
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\r\n")
            m = RE_CMDLINE.match(line)
            if m:
                info["cmdline"] = m.group(1).strip()
                toks = info["cmdline"].split()
                for i, t in enumerate(toks):
                    if t == "--paths" and i + 1 < len(toks):
                        try:
                            info["limit"] = int(toks[i + 1])
                        except ValueError:
                            pass
                    if t == "--print-paths":
                        info["print_paths"] = True
                continue
            m = RE_SUMMARY_PCT.match(line)
            if m:
                info["limit"] = int(m.group(1))
                info["summary_pct"] = float(m.group(2))
                continue
            m = RE_SUMMARY_COUNT.match(line)
            if m:
                info["summary_count"] = int(m.group(1))
                continue
            m = RE_WUR.match(line)
            if m:
                phase, wid, paths, pathout, nr, name, tu = m.groups()
                rec = {"phase": phase, "work_unit": phase + wid,
                       "paths": int(paths), "pathout": int(pathout)}
                if name.startswith("batch ") and tu is None:
                    rec["batch"] = name
                    rec["functions_in_batch"] = int(nr) if nr else None
                    info["batches"].append(rec)
                else:
                    rec["name"] = name
                    rec["tu"] = int(tu) if tu else None
                    info["named"].append(rec)
                continue
            m = RE_PATHED_OUT.match(line)
            if m:
                paths, component, sig = m.groups()
                lst = info["pathed_out"].setdefault(sig, [])
                # the same component can be logged more than once for a
                # function (re-analysis passes); keep one entry, count them
                for c in lst:
                    if c["component"] == component:
                        c["paths"] = max(c["paths"], int(paths))
                        c["times"] += 1
                        break
                else:
                    lst.append({"component": component, "paths": int(paths), "times": 1})
                continue
            if RE_ANY_DIAG.match(line):
                info["diag_lines"] += 1
    return info


# --------------------------------------------------------------------------
# FUNCTION.metrics.xml.gz

RE_FNMETRIC = re.compile(
    r"<file>(.*?)</file>\s*<names><!\[CDATA\[(.*?)\]\]></names>\s*<metrics>(.*?)</metrics>",
    re.S)


def parse_metrics(path):
    """name -> {file, metrics}. Names are as the analyzer keys them: plain
    identifiers for C, mangled for C++."""
    out = {}
    if not os.path.exists(path):
        return out
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        text = f.read()
    for fname, names, mets in RE_FNMETRIC.findall(text):
        fn = None
        for part in names.split(";"):
            if part.startswith("fn:"):
                fn = part[3:]
                break
        if not fn:
            continue
        d = {}
        for kv in mets.split(";"):
            if ":" in kv:
                k, v = kv.split(":", 1)
                d[k] = v
        out[fn] = {"file": fname, "metrics": d}
    return out


# --------------------------------------------------------------------------
# names

RE_MANGLED_SEG = re.compile(r"(\d+)")


def identifier_of(name):
    """The bare identifier of a logged function name.

    C names are already identifiers. C++ names in the log are Itanium-mangled
    (_ZN4demo6Widget1fEi); the last <len><chars> segment of the nested-name
    prefix is the identifier. Good enough to build a `find` query and to match
    a demangled "demo::Widget::f(int)" signature -- not a demangler.
    """
    if not name.startswith("_Z"):
        return name
    i = 2
    if i < len(name) and name[i] == "N":
        i += 1
    last = None
    while i < len(name):
        m = RE_MANGLED_SEG.match(name, i)
        if not m:
            break
        n = int(m.group(1))
        i = m.end()
        last = name[i:i + n]
        i += n
    return last or name


def identifier_of_signature(sig):
    """'demo::Widget::f(int)' -> 'f';  'setup_env(pool *, cmd_rec *)' -> 'setup_env'."""
    head = sig.split("(", 1)[0]
    return head.split("::")[-1].strip()


# --------------------------------------------------------------------------
# cov-manage-emit

def manage_emit(bin_dir, idir, args):
    exe = os.path.join(bin_dir, "cov-manage-emit")
    if os.name == "nt" and os.path.exists(exe + ".exe"):
        exe += ".exe"
    cmd = [exe, "--dir", idir, "--ticker-mode", "none"] + args
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, p.stdout, p.stderr, cmd


def extract_definition(bin_dir, idir, name, tu):
    """Return (text, command, error) for one function's pretty-printed AST.

    Anchored regex on the logged name. For a mangled C++ name that is exact;
    for a plain C identifier the anchor stops `setup_env` from matching
    `setup_env_ex`. `--tu` disambiguates static functions that share a name.
    """
    args = []
    if tu is not None:
        args += ["--tu", str(tu)]
    pattern = "^" + re.escape(name) + "$"
    args += ["find", pattern, "--kind", "f", "--print-definitions"]
    rc, out, err, cmd = manage_emit(bin_dir, idir, args)
    if rc != 0 or "Version mismatch" in out or "Version mismatch" in err:
        return None, cmd, (out + err).strip()
    if "Matching function" not in out:
        return None, cmd, "no function matched %s" % pattern
    return out, cmd, None


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s)


# --------------------------------------------------------------------------
# report

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, help="intermediate directory")
    ap.add_argument("--bin", help="<install>/bin of the SAME version that wrote the idir "
                                  "(emit/version line 1); enables definition extraction")
    ap.add_argument("--out", help="directory to write extracted definitions into "
                                  "(default: <idir>/output/pathout/)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args()

    idir = a.dir
    log = os.path.join(idir, "output", "analysis-log.txt")
    if not os.path.exists(log):
        sys.exit("no %s -- has cov-analyze run on this directory?" % log)
    info = parse_log(log)
    mets = parse_metrics(os.path.join(idir, "output", "FUNCTION.metrics.xml.gz"))
    emit_version = None
    vf = os.path.join(idir, "emit", "version")
    if os.path.exists(vf):
        with open(vf, encoding="utf-8", errors="replace") as f:
            emit_version = f.readline().strip().lstrip("# ")

    # Join: named wur lines <-> metrics <-> Pathed out lines
    rows = []
    seen_sigs = set()
    for rec in info["named"]:
        name = rec["name"]
        ident = identifier_of(name)
        m = mets.get(name, {})
        md = m.get("metrics", {})
        comps = []
        for sig, lst in info["pathed_out"].items():
            if identifier_of_signature(sig) == ident:
                comps.extend(lst)
                seen_sigs.add(sig)
        rows.append({
            "name": name, "identifier": ident, "tu": rec["tu"],
            "work_unit": rec["work_unit"], "paths": rec["paths"],
            "file": m.get("file"), "line": md.get("ml"),
            "ccm": md.get("cc"), "apc": md.get("pce"), "loc": md.get("lc"),
            "pathed_out": sorted(comps, key=lambda c: -c["paths"]),
        })
    # Pathed-out signatures with no named wur line (functions that sat in a batch)
    orphan_sigs = [s for s in info["pathed_out"] if s not in seen_sigs]

    # Extraction
    extracted = []
    if a.bin:
        out_dir = a.out or os.path.join(idir, "output", "pathout")
        os.makedirs(out_dir, exist_ok=True)
        for r in rows:
            text, cmd, err = extract_definition(a.bin, idir, r["name"], r["tu"])
            entry = {"name": r["name"], "command": " ".join(cmd)}
            if text is None:
                entry["error"] = err
            else:
                path = os.path.join(out_dir, "%s.tu%s.txt" % (safe_name(r["name"]), r["tu"])).replace("\\", "/")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                entry["path"] = path
                entry["lines"] = text.count("\n")
            r["definition"] = entry
            extracted.append(entry)
        for sig in orphan_sigs:
            ident = identifier_of_signature(sig)
            text, cmd, err = extract_definition(a.bin, idir, ident, None)
            entry = {"signature": sig, "command": " ".join(cmd),
                     "note": "no named wur line; matched by identifier across all TUs -- "
                             "check the 'Matching function' headers for the right overload/TU"}
            if text is None:
                entry["error"] = err
            else:
                path = os.path.join(out_dir, "%s.txt" % safe_name(ident)).replace("\\", "/")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                entry["path"] = path
                entry["lines"] = text.count("\n")
            extracted.append(entry)

    result = {
        "idir": idir, "emit_version": emit_version, "cmdline": info["cmdline"],
        "limit": info["limit"], "print_paths": info["print_paths"],
        "summary_pct": info["summary_pct"], "summary_count": info["summary_count"],
        "functions": rows,
        "batches": info["batches"],
        "unnamed_in_batches": sum(b["pathout"] for b in info["batches"]),
        "pathed_out_without_named_line": orphan_sigs,
        "extracted": extracted,
    }

    if a.json:
        print(json.dumps(result, indent=2))
        return

    # ---- human report
    print("PATHOUT report: %s" % idir)
    print("  emit written by : %s" % (emit_version or "?"))
    print("  cov-analyze     : %s" % (info["cmdline"] or "?"))
    print("  path limit      : %d%s" % (info["limit"], "" if info["limit"] == 5000 else "  (non-default)"))
    if info["summary_count"] is not None:
        line = "  functions over the limit : %d" % info["summary_count"]
        if info["summary_pct"] is not None:
            line += "  (%.2f%% of functions; the log calls up to 5%% normal)" % info["summary_pct"]
        print(line)
    if not info["print_paths"]:
        print("  --print-paths   : NOT used -- the log cannot say WHICH checker hit the limit.\n"
              "                    Re-run with --print-paths (scope with --tu) to get\n"
              "                    'Pathed out: N paths traversed by <CHECKER>' lines.")
    if info["batches"]:
        print("  batched work units that hit the limit : %d  (about %d functions; a batch line does not name them)"
              % (len(info["batches"]), result["unnamed_in_batches"]))
        if info["print_paths"]:
            print("                    --print-paths was on, so they are named by their 'Pathed out'\n"
                  "                    lines instead -- see the second list below.")
        else:
            print("                    Re-run with --print-paths: 'Pathed out' lines name the\n"
                  "                    function even inside a batch.")
    print()
    if not rows and not orphan_sigs:
        print("No PATHOUT function is named in the log.")
        return
    if rows:
        print("%-40s %5s %8s %6s %10s %6s  %s" % ("function", "TU", "paths", "CCM", "APC", "LOC", "file:line"))
        for r in rows:
            loc = ("%s:%s" % (r["file"], r["line"])) if r["file"] else "(no metrics entry)"
            print("%-40s %5s %8d %6s %10s %6s  %s" % (
                r["name"][:40], r["tu"], r["paths"], r["ccm"] or "?", r["apc"] or "?", r["loc"] or "?", loc))
            for c in r["pathed_out"]:
                times = ("  (x%d)" % c["times"]) if c["times"] > 1 else ""
                print("%-40s        %8d  pathed out in %s%s" % ("", c["paths"], c["component"], times))
            d = r.get("definition")
            if d:
                if "path" in d:
                    print("%-40s        definition: %s (%d lines)" % ("", d["path"], d["lines"]))
                else:
                    print("%-40s        definition: FAILED -- %s" % ("", d.get("error", "")[:200]))
    if orphan_sigs:
        print()
        print("Pathed out (from --print-paths) without a named wur line -- these sat in a batch (%d):"
              % len(orphan_sigs))
        for s in sorted(orphan_sigs, key=lambda x: -len(info["pathed_out"][x])):
            comps = ", ".join("%s(%d)" % (c["component"], c["paths"])
                              for c in sorted(info["pathed_out"][s], key=lambda c: -c["paths"]))
            print("  %s\n      %s" % (s, comps))
        for e in extracted:
            if "signature" in e:
                print("  -> %s" % (e.get("path") or ("FAILED: " + e.get("error", "")[:160])))
    print()
    print("APC = acyclic path count, the static estimate in FUNCTION.metrics; it is not what the\n"
          "engine explored. The engine's count is paths x tracked state -- see references/path-explosion.md.")


if __name__ == "__main__":
    main()
