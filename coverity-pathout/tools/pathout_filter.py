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
RE_WUR_NAMED = re.compile(r"^wur: [a-z]+\d+ .*? (\d+) PATHOUT=(\d+) n: (.+?) in TU (\d+)$")


def identifier_of_signature(sig):
    head = sig.split("(", 1)[0]
    return head.split("::")[-1].strip()


def pathout_functions(log_path):
    """identifier -> {signatures, components{name: paths}, from_wur_line}"""
    out = {}
    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip()
            m = RE_PATHED_OUT.match(line)
            if m:
                paths, comp, sig = m.groups()
                ident = identifier_of_signature(sig)
                e = out.setdefault(ident, {"signatures": set(), "components": {}, "wur": False})
                e["signatures"].add(sig)
                e["components"][comp] = max(e["components"].get(comp, 0), int(paths))
                continue
            m = RE_WUR_NAMED.match(line)
            if m:
                name = m.group(3)
                e = out.setdefault(name, {"signatures": set(), "components": {}, "wur": False})
                e["wur"] = True
    return out


def finding_function(issue):
    name = issue.get("functionDisplayName") or issue.get("functionName") or ""
    return identifier_of_signature(name)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--findings", required=True)
    ap.add_argument("--log", help="analysis-log.txt of a --print-paths run of the same idir")
    ap.add_argument("--pathout-map", help="instead of --log: the --json output of an earlier run of this "
                                          "tool, whose pathout_functions map is reused")
    ap.add_argument("--json", help="write the kept findings here")
    ap.add_argument("--callers", action="store_true", help="also keep direct callers of pathed-out derivers")
    ap.add_argument("--relevant", help="comma-separated checker-name prefixes; keep only findings in functions where "
                                       "one of these pathed out (e.g. FORWARD_NULL,NULL_RETURNS,REVERSE_INULL for a "
                                       "null-dereference shape). A candidate only matters where the checker that "
                                       "would have caught it is the one that was cut off.")
    a = ap.parse_args()
    relevant = tuple(x.strip() for x in a.relevant.split(",") if x.strip()) if a.relevant else None

    if a.log:
        po = pathout_functions(a.log)
    elif a.pathout_map:
        prev = json.load(open(a.pathout_map, encoding="utf-8"))
        po = {k: {"signatures": set(v.get("signatures", [])), "components": v["components"], "wur": False}
              for k, v in prev["pathout_functions"].items()}
    else:
        sys.exit("give --log or --pathout-map")
    if not po:
        sys.exit("no PATHOUT function named in %s -- is it the log of a --print-paths run?" % (a.log or a.pathout_map))
    data = json.load(open(a.findings, encoding="utf-8"))
    issues = data.get("issues", [])
    kept, dropped, irrelevant = [], 0, 0
    for it in issues:
        fn = finding_function(it)
        if fn in po:
            comps = po[fn]["components"]
            if relevant and not any(c.startswith(relevant) for c in comps):
                irrelevant += 1
                continue
            it2 = dict(it)
            it2["pathout"] = {
                "function": fn,
                "pathed_out_components": sorted(comps.items(), key=lambda kv: -kv[1]),
                "deriver_pathed_out": any(c.endswith("_DERIVERS") for c in comps),
            }
            kept.append(it2)
        else:
            dropped += 1
    if a.callers:
        print("note: --callers is not implemented yet; only findings inside PATHOUT functions are kept", file=sys.stderr)

    print("findings: %d total, %d in PATHOUT functions (kept), %d elsewhere (dropped)%s"
          % (len(issues), len(kept), dropped,
             ", %d in PATHOUT functions where none of [%s] pathed out (dropped)" % (irrelevant, a.relevant)
             if relevant else ""))
    print("PATHOUT functions named in the log: %d" % len(po))
    by_fn = {}
    for it in kept:
        by_fn.setdefault(it["pathout"]["function"], []).append(it)
    for fn, lst in sorted(by_fn.items(), key=lambda kv: -len(kv[1])):
        comps = ", ".join("%s(%d)" % kv for kv in lst[0]["pathout"]["pathed_out_components"][:4])
        print("  %-36s %2d candidate(s)   pathed out: %s" % (fn[:36], len(lst), comps))
        for it in lst[:6]:
            print("      %s:%s  %s" % (os.path.basename(it.get("mainEventFilePathname", "?")),
                                       it.get("mainEventLineNumber", "?"),
                                       (it.get("events") or [{}])[0].get("eventDescription", "")[:90]))
    if a.json:
        with open(a.json, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"source": a.findings, "log": a.log, "kept": kept,
                       "dropped": dropped, "pathout_functions": {k: {"components": v["components"],
                                                                     "signatures": sorted(v["signatures"])}
                                                                 for k, v in po.items()}}, f, indent=1)
        print("written: %s" % a.json)


if __name__ == "__main__":
    main()
