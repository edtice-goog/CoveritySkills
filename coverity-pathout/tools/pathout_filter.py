#!/usr/bin/env python3
"""Keep only the findings that sit in PATHOUT functions.

    pathout_filter.py --findings <cov-format-errors --json-output-v10 file> \
                      --log <analysis-log.txt of a --print-paths run> [--callers] [--json out]

The intended input is the output of a path-insensitive candidate checker run
over the whole intermediate directory. The log of a `--print-paths` run of
the SAME idir (any checker set; it only has to name the functions) supplies
the PATHOUT set and, per function, the checkers that pathed out in it.
Findings outside PATHOUT functions are the noise a path-sensitive checker was
right to reject; they are dropped, with a count. Findings inside are the
candidates, annotated with which components pathed out there, for the
confirmation stage (fuzzing) and for triage.

--callers also keeps findings in direct callers of functions whose model
derivation pathed out (`*_DERIVERS`), since a truncated model weakens the
analysis of every caller. Needs the idir's callgraph; see the note in the
output when it is unavailable.

Pure standard library.
"""

import argparse
import json
import os
import re
import sys

RE_PATHED_OUT = re.compile(
    r"^wur_diagnostics: (?:\w+: )?Pathed out: (\d+) paths traversed by (\S+) in \"(.*)\"$")
RE_WUR_NAMED = re.compile(
    r"^wur: [a-z]+\d+ .*? (\d+) PATHOUT=(\d+) n: (.+?)(?: in TU (\d+))?(?: with extra_info)?$")

# --relevant auto: which pathed-out components make a hit of each shape checker
# in the pathout-shapes catalogue worth reading. A candidate only matters where
# the checker that would have caught it is the one that was cut off.
SHAPE_RELEVANCE = {
    "PATHOUT_CANDIDATE_NULL_CHECK_THEN_DEREF": ("FORWARD_NULL", "NULL_RETURNS", "REVERSE_INULL"),
    "PATHOUT_CANDIDATE_UNCHECKED_NULL_RETURN_DEREF": ("NULL_RETURNS", "FORWARD_NULL"),
    "PATHOUT_CANDIDATE_ZERO_CHECK_THEN_DIVIDE": ("DIVIDE_BY_ZERO",),
    "PATHOUT_CANDIDATE_DOUBLE_RELEASE": ("USE_AFTER_FREE",),
    "PATHOUT_CANDIDATE_UNBOUNDED_COPY_INTO_FIXED_BUFFER": ("STRING_OVERFLOW", "OVERRUN", "BUFFER_SIZE"),
    "PATHOUT_CANDIDATE_SOURCE_LENGTH_INTO_FIXED_BUFFER": ("STRING_OVERFLOW", "OVERRUN", "BUFFER_SIZE"),
    "PATHOUT_CANDIDATE_ALLOC_NEVER_RELEASED": ("RESOURCE_LEAK",),
    "PATHOUT_CANDIDATE_UNCHECKED_ARRAY_INDEX": ("OVERRUN", "NEGATIVE_RETURNS", "TAINTED_SCALAR"),
    "PATHOUT_CANDIDATE_OVERFLOW_BEFORE_ALLOC": ("INTEGER_OVERFLOW", "OVERFLOW_BEFORE_WIDEN", "TAINTED_SCALAR"),  # superseded, kept for old runs
    "PATHOUT_CANDIDATE_UNBOUNDED_ARITHMETIC_INTO_SINK": ("INTEGER_OVERFLOW", "OVERFLOW_BEFORE_WIDEN", "TAINTED_SCALAR"),
    "PATHOUT_CANDIDATE_NARROWING_CAST_OF_ARITHMETIC": ("INTEGER_OVERFLOW", "OVERFLOW_BEFORE_WIDEN"),
    "PATHOUT_CANDIDATE_FREE_OF_NONHEAP": ("BAD_FREE", "USE_AFTER_FREE"),
    "PATHOUT_CANDIDATE_NONLITERAL_FORMAT_STRING": ("PRINTF_ARGS", "FORMAT_STRING_INJECTION", "TAINTED_STRING"),
    "PATHOUT_CANDIDATE_SIZEOF_POINTER_AS_SIZE": ("SIZEOF_MISMATCH", "BAD_SIZEOF"),
}


def identifier_of_signature(sig):
    head = sig.split("(", 1)[0]
    return head.split("::")[-1].strip()


def pathout_functions(log_path):
    """identifier -> {signatures, components{name: paths}, wur, tus}"""
    out = {}
    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip()
            m = RE_PATHED_OUT.match(line)
            if m:
                paths, comp, sig = m.groups()
                ident = identifier_of_signature(sig)
                e = out.setdefault(ident, {"signatures": set(), "components": {}, "wur": False, "tus": set()})
                e["signatures"].add(sig)
                e["components"][comp] = max(e["components"].get(comp, 0), int(paths))
                continue
            m = RE_WUR_NAMED.match(line)
            if m and m.group(2) != "0" and not m.group(3).startswith("batch "):
                name = m.group(3)
                e = out.setdefault(name, {"signatures": set(), "components": {}, "wur": False, "tus": set()})
                e["wur"] = True
                if m.group(4):
                    e["tus"].add(int(m.group(4)))
    return out


def finding_function(issue):
    name = issue.get("functionDisplayName") or issue.get("functionName") or ""
    return identifier_of_signature(name)


def finding_file(issue):
    return (issue.get("mainEventFilePathname") or "").replace("\\", "/")


RE_DECLARED_AT = re.compile(r"declared at:\s*\n\s*(\S+?):\d+:\d+-", re.M)


def declaring_files(bin_dir, idir, name, tus):
    """The file(s) that define `name` in the given TUs, from the emit's own
    `find` header (`declared at: <file>:<line>`), about a second per call.
    Empty when --bin/--dir were not given or the name is not found."""
    import subprocess
    files = set()
    exe = os.path.join(bin_dir, "cov-manage-emit")
    for tu in sorted(tus) or [None]:
        cmd = [exe, "--dir", idir, "--ticker-mode", "none"]
        if tu is not None:
            cmd += ["--tu", str(tu)]
        cmd += ["find", "^%s$" % re.escape(name), "--kind", "f"]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
        except (OSError, subprocess.SubprocessError):
            return files
        files.update(f.replace("\\", "/") for f in RE_DECLARED_AT.findall(out))
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--findings", required=True)
    ap.add_argument("--log", help="analysis-log.txt of a --print-paths run of the same idir")
    ap.add_argument("--pathout-map", help="instead of --log: the --json output of an earlier run of this "
                                          "tool, whose pathout_functions map is reused")
    ap.add_argument("--json", help="write the kept findings here")
    ap.add_argument("--dir", help="the idir the findings came from; with --bin, a PATHOUT function name that "
                                  "several files define is resolved to the file the log's TU names, so a "
                                  "same-named function elsewhere (redis has five main()s) is not kept by mistake")
    ap.add_argument("--bin", help="<install>/bin of the version that wrote the idir (for --dir)")
    ap.add_argument("--callers", action="store_true", help="also keep direct callers of pathed-out derivers")
    ap.add_argument("--relevant", help="comma-separated checker-name prefixes; keep only findings in functions where "
                                       "one of these pathed out (e.g. FORWARD_NULL,NULL_RETURNS,REVERSE_INULL for a "
                                       "null-dereference shape). A candidate only matters where the checker that "
                                       "would have caught it is the one that was cut off. 'auto' looks the prefixes "
                                       "up per finding from its checker name, for the pathout-shapes catalogue "
                                       "(a whole-catalogue run with no escaped defect to key on).")
    a = ap.parse_args()
    auto = a.relevant == "auto"
    relevant = None if auto or not a.relevant else tuple(x.strip() for x in a.relevant.split(",") if x.strip())

    if a.log:
        po = pathout_functions(a.log)
    elif a.pathout_map:
        prev = json.load(open(a.pathout_map, encoding="utf-8"))
        po = {k: {"signatures": set(v.get("signatures", [])), "components": v["components"], "wur": False,
                  "tus": set(v.get("tus", []))}
              for k, v in prev["pathout_functions"].items()}
    else:
        sys.exit("give --log or --pathout-map")
    if not po:
        sys.exit("no PATHOUT function named in %s -- is it the log of a --print-paths run?" % (a.log or a.pathout_map))
    if (relevant or auto) and not any(v["components"] for v in po.values()):
        print("note: the log names PATHOUT functions but no components (not a --print-paths run), so "
              "relevance cannot be applied; every finding in a PATHOUT function is kept", file=sys.stderr)
        relevant, auto = None, False
    data = json.load(open(a.findings, encoding="utf-8"))
    issues = data.get("issues", [])
    # A PATHOUT function is named by identifier; findings carry a file. When
    # findings for one name come from more than one file, the name is
    # ambiguous: resolve it through the emit (--dir/--bin), else keep them all
    # and say so.
    files_by_fn = {}
    for it in issues:
        fn = finding_function(it)
        if fn in po:
            files_by_fn.setdefault(fn, set()).add(finding_file(it))
    ambiguous = {fn: fs for fn, fs in files_by_fn.items() if len(fs) > 1}
    resolved = {}
    if ambiguous and a.dir and a.bin:
        for fn in ambiguous:
            resolved[fn] = declaring_files(a.bin, a.dir, fn, po[fn]["tus"])
    unresolved = [fn for fn in ambiguous if not resolved.get(fn)]
    if unresolved:
        print("note: %d PATHOUT function name(s) match findings in more than one file (%s); "
              "%s" % (len(unresolved), ", ".join("%s in %d files" % (fn, len(ambiguous[fn])) for fn in unresolved),
                      "all are kept and marked ambiguous" if not (a.dir and a.bin)
                      else "the emit did not resolve them, all are kept and marked ambiguous"),
              file=sys.stderr)
        if not (a.dir and a.bin):
            print("      pass --dir <idir> --bin <install>/bin to resolve them through the emit", file=sys.stderr)
    kept, dropped, irrelevant, unknown_shape, wrong_file = [], 0, 0, 0, 0
    for it in issues:
        fn = finding_function(it)
        if fn in po:
            if fn in resolved and resolved[fn] and finding_file(it) not in resolved[fn]:
                wrong_file += 1
                continue
            comps = po[fn]["components"]
            rel = relevant
            if auto:
                rel = SHAPE_RELEVANCE.get(it.get("checkerName", ""))
                if rel is None:
                    unknown_shape += 1
            if rel and not any(c.startswith(rel) for c in comps):
                irrelevant += 1
                continue
            it2 = dict(it)
            it2["pathout"] = {
                "function": fn,
                "pathed_out_components": sorted(comps.items(), key=lambda kv: -kv[1]),
                "deriver_pathed_out": any(c.endswith("_DERIVERS") for c in comps),
                "ambiguous": fn in unresolved,
            }
            kept.append(it2)
        else:
            dropped += 1
    if wrong_file:
        print("note: %d finding(s) dropped because they sit in a same-named function in another file "
              "than the one the log's TU defines" % wrong_file, file=sys.stderr)
    if a.callers:
        print("note: --callers is not implemented; only findings inside PATHOUT functions are kept", file=sys.stderr)
    derivers = sorted(fn for fn, v in po.items() if any(c.endswith("_DERIVERS") for c in v["components"]))
    if derivers:
        # Known, accepted limit: a model deriver that pathed out leaves every
        # caller of that function analyzed against a weaker model, and those
        # callers are not PATHOUT functions themselves, so nothing here keeps
        # their hits. It only bites when one PATHOUT function calls another,
        # and the shape checkers do not use models. Say so, with numbers only.
        print("note: a model deriver pathed out in %d of the %d PATHOUT functions; their callers are analyzed "
              "with a weaker model and are NOT included here (known limit, not built). If a real escape "
              "turns out to sit in such a caller, report it at "
              "https://github.com/edtice-goog/CoveritySkills/issues with these counts and the component "
              "names -- no function names, no code." % (len(derivers), len(po)), file=sys.stderr)

    print("findings: %d total, %d in PATHOUT functions (kept), %d elsewhere (dropped)%s%s"
          % (len(issues), len(kept), dropped,
             ", %d in PATHOUT functions where no relevant checker pathed out (dropped)" % irrelevant
             if (relevant or auto) else "",
             ", %d of an unknown shape (kept unfiltered)" % unknown_shape if unknown_shape else ""))
    print("PATHOUT functions named in the log: %d" % len(po))
    by_fn = {}
    for it in kept:
        by_fn.setdefault(it["pathout"]["function"], []).append(it)
    for fn, lst in sorted(by_fn.items(), key=lambda kv: -len(kv[1])):
        comps = ", ".join("%s(%d)" % kv for kv in lst[0]["pathout"]["pathed_out_components"][:4])
        print("  %-36s %2d candidate(s)   pathed out: %s" % (fn[:36], len(lst), comps))
        for it in lst[:6]:
            print("      %s:%s  %s  %s" % (os.path.basename(it.get("mainEventFilePathname", "?")),
                                           it.get("mainEventLineNumber", "?"),
                                           it.get("checkerName", "").replace("PATHOUT_CANDIDATE_", "").lower(),
                                           (it.get("events") or [{}])[0].get("eventDescription", "")[:80]))
    if a.json:
        with open(a.json, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"source": a.findings, "log": a.log, "kept": kept,
                       "dropped": dropped, "pathout_functions": {k: {"components": v["components"],
                                                                     "signatures": sorted(v["signatures"])}
                                                                 for k, v in po.items()}}, f, indent=1)
        print("written: %s" % a.json)


if __name__ == "__main__":
    main()
