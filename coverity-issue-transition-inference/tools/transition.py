#!/usr/bin/env python3
"""Attribute a finding delta across a 2x2 factorial of (code x analyzer).

Correspondence comes from Coverity Connect: a finding present in several cells
carries one CID because Connect's commit process applies antecedent merge keys
(rule 27). Raw local merge keys are read too, but ONLY to measure how often they
move where Connect still lines the finding up. They are never the correspondence.

Cells, with C1/C2 the old/new code and A1/A2 the old/new analyzer:

    a = (C1,A1)   b = (C1,A2)
    c = (C2,A1)   d = (C2,A2)

The delta the user actually asks about is a -> d, in which code and analyzer
moved together. b and c are the controls that split it.
"""
import argparse, csv, io, json, os, subprocess, sys
from collections import defaultdict

CELLS = ["a", "b", "c", "d"]


def cim(args, conn):
    out = subprocess.run(
        [conn["cim"], "--host", conn["host"], "--port", conn["port"],
         "--auth-key-file", conn["key"]] + args,
        capture_output=True, text=True, timeout=600)
    if out.returncode != 0:
        raise SystemExit(f"cov-manage-im failed: {out.stderr[:400]}")
    return out.stdout


def stream_defects(stream, conn):
    """CID -> metadata, for one committed stream."""
    txt = cim(["--mode", "defects", "--show", "--stream", stream,
               "--fields", "cid,checker,file,function,status"], conn)
    rows = {}
    for r in csv.DictReader(io.StringIO(txt)):
        cid = (r.get("CID") or r.get("cid") or "").strip()
        if cid.isdigit():
            rows[int(cid)] = {k.lower(): (v or "").strip() for k, v in r.items()}
    return rows


def local_keys(path):
    """mergeKey -> (checker, file, line) from a cov-format-errors export."""
    with open(path, encoding="utf-8", errors="replace") as f:
        d = json.load(f)
    out = {}
    for i in d.get("issues", []):
        out[i["mergeKey"]] = (i.get("checkerName", ""),
                              i.get("strippedMainEventFilePathname")
                              or i.get("mainEventFilePathname", ""),
                              i.get("mainEventLineNumber"))
    return out


def label(p, config_checkers, checker):
    """One label per CID from its four-cell presence pattern.

    The user's question is binary: did I write this, or did the version change?
    That is the primary axis. Whether a version-attributable finding came from a
    newly-default checker, a smarter checker, or a front-end change is a
    tool-vendor distinction -- real, but it does not change what the user does
    next, so it is a sub-field and never the headline.

    INTERACTION is the label a single diagonal cannot produce: the finding needs
    BOTH the new code and the new analyzer, so neither control alone explains it.
    """
    a, b, c, d = (p["a"], p["b"], p["c"], p["d"])

    if d and not a:                       # appeared across the upgrade
        if b and c:  lab, why = "VERSION_ATTRIBUTABLE", "present in old code under both analyzers"
        elif b:      lab, why = "VERSION_ATTRIBUTABLE", "old code, new analyzer reports it"
        elif c:      lab, why = "CODE_ATTRIBUTABLE", "old analyzer reports it in the new code"
        else:        lab, why = "CODE_ATTRIBUTABLE", "absent from the old code EVEN under the new analyzer"
    elif a and not d:                     # disappeared across the upgrade
        if c and not b:  lab, why = "DROPPED_BY_VERSION", "still in the new code under the old analyzer"
        elif b and not c: lab, why = "RESOLVED_BY_CODE", "still reported on old code by the new analyzer"
        elif b and c:    lab, why = "CONTROL_FAILURE", "both controls report it; only the corner does not"
        else:            lab, why = "RESOLVED_BY_CODE", "absent from the new code under both analyzers"
    elif a and d:
        lab, why = ("UNCHANGED", "present throughout") if (b and c) else                    ("UNSTABLE_PRESENT", "present at both ends, absent from a control")
    else:
        lab, why = "ABSENT_BOTH_ENDS", "not reported at either end"

    # Sub-attribution: detail for whoever wants it, never the headline.
    sub = None
    if lab == "VERSION_ATTRIBUTABLE":
        sub = "checker_enablement" if checker in config_checkers else "analyzer_behaviour"
    elif lab == "CODE_ATTRIBUTABLE" and not p["c"]:
        # New code whose defect only the new analyzer can see. The old analyzer
        # would never have shown it, so an upgrade-blind comparison misses a
        # real bug -- and lumping it with same-checker version noise buries it.
        sub = "visible_only_to_new_analyzer"
    return lab, why, sub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cim", required=True)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", default="8080")
    ap.add_argument("--key", required=True)
    ap.add_argument("--stream", nargs=4, required=True,
                    metavar=("A", "B", "C", "D"), help="streams for cells a b c d")
    ap.add_argument("--local", nargs=4, required=True,
                    metavar=("A", "B", "C", "D"), help="cov-format-errors JSON per cell")
    ap.add_argument("--config-checkers", default="",
                    help="comma-separated checkers that changed enablement (config, not capability)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    conn = {"cim": args.cim, "host": args.host, "port": args.port, "key": args.key}
    cfg = {s.strip() for s in args.config_checkers.split(",") if s.strip()}

    per = {cell: stream_defects(s, conn) for cell, s in zip(CELLS, args.stream)}
    loc = {cell: local_keys(p) for cell, p in zip(CELLS, args.local)}

    all_cids = sorted(set().union(*[set(v) for v in per.values()]))
    findings, counts = [], defaultdict(int)
    for cid in all_cids:
        p = {c: cid in per[c] for c in CELLS}
        meta = next(per[c][cid] for c in CELLS if p[c])
        lab, why, sub = label(p, cfg, meta.get("checker", ""))
        counts[lab] += 1
        findings.append({"cid": cid, "checker": meta.get("checker", ""),
                         "file": meta.get("file", ""), "function": meta.get("function", ""),
                         "presence": p, "label": lab, "evidence": why,
                         "sub_attribution": sub})

    # Rule-27 residue: local merge keys that moved between analyzer versions.
    mk = {c: set(loc[c]) for c in CELLS}
    residue = {
        "local_mergekeys": {c: len(mk[c]) for c in CELLS},
        "old_code_kept_key_a_to_b": len(mk["a"] & mk["b"]),
        "old_code_key_only_in_a": len(mk["a"] - mk["b"]),
        "old_code_key_only_in_b": len(mk["b"] - mk["a"]),
        "connect_cids_shared_a_b": sum(1 for f in findings if f["presence"]["a"] and f["presence"]["b"]),
    }

    report = {"cells": dict(zip(CELLS, args.stream)), "counts": dict(counts),
              "mergekey_residue": residue, "findings": findings}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"CIDs across all cells: {len(all_cids)}")
    for k in sorted(counts, key=lambda x: -counts[x]):
        print(f"  {counts[k]:4d}  {k}")
    print("\nlocal merge keys per cell:", residue["local_mergekeys"])
    print("old code, key kept a->b:", residue["old_code_kept_key_a_to_b"],
          "| only-a:", residue["old_code_key_only_in_a"],
          "| only-b:", residue["old_code_key_only_in_b"])
    print("Connect CIDs shared a&b:", residue["connect_cids_shared_a_b"])


main()
