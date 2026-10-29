#!/usr/bin/env python3
"""Step 2: assign lanes from the checker table (references/lanes.md).

  lanes.py assign --bundles <dir> [--table <file> ...] --out <dir>/lanes.json
  lanes.py check-table <file> [<file> ...]

assign reads index.json (tools/bundle.py) and the checker table: the
skill's own references/checker-lanes.json, then each --table in order, a
later row replacing an earlier one for the same checker (an organization's
table, or a producer's rows for its own checkers). A finding whose checker
has a fixed lane takes it here, with no model. A finding whose checker
lists candidate lanes is left pending, for inference to choose among them.
A finding whose checker has no row is unplaced: the skill determines a row
for that checker once, adds it to a table file, and runs assign again.

Nothing here spends model time, asks a question, or looks at a terminal:
it writes lanes.json and prints what is done and what the next step needs.
"""
import argparse
import collections
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_TABLE = HERE.parent / "references" / "checker-lanes.json"
METHOD_LANES = ("Construction", "Intent", "Contract", "Value or path")
POLICY, OTHER = "Policy", "Other"
ALL_LANES = METHOD_LANES + (POLICY, OTHER)
ROW_METHOD = re.compile(r"^(LLM: \S.*|Execution: coverity-verify|Human)$")
ROUTES = ("harness", "extraction")
TABLE = "checker table"


def read_json(path, errors, what):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        errors.append(what + ": cannot read " + str(path) + ": " + str(e))
        return None


def row_problems(name, row):
    """What is wrong with one table row; [] when it is sound."""
    p = []
    fixed, cands = row.get("lane"), row.get("lanes")
    if (fixed is None) == (cands is None):
        p.append(name + ": give either 'lane' (fixed) or 'lanes' (candidates), not both or neither")
    elif fixed is not None and fixed not in ALL_LANES:
        p.append(name + ": lane " + repr(fixed) + " is not one of " + ", ".join(ALL_LANES))
    elif cands is not None:
        if (not isinstance(cands, list) or len(cands) < 2 or len(set(cands)) != len(cands)
                or any(c not in METHOD_LANES for c in cands)):
            p.append(name + ": 'lanes' needs two or more distinct method lanes ("
                     + ", ".join(METHOD_LANES) + ")")
        if not (row.get("decide") or "").strip():
            p.append(name + ": candidate lanes need 'decide', what tells them apart")
    if fixed is not None and not (row.get("why") or "").strip():
        p.append(name + ": a fixed lane needs 'why'")
    m = row.get("method")
    if m is not None:
        if not ROW_METHOD.match(m):
            p.append(name + ": method " + repr(m) + " is not LLM: <model>, Execution: "
                     "coverity-verify or Human (a checker that is never triaged is Policy)")
        if fixed in (POLICY, OTHER):
            p.append(name + ": a " + fixed + " row takes no method")
    r = row.get("route")
    if r is not None and (r not in ROUTES or m != "Execution: coverity-verify"):
        p.append(name + ": route is harness or extraction, and only beside the method "
                 "Execution: coverity-verify")
    return p


def load_tables(extra, errors):
    """The skill's table, then each extra one; later rows replace earlier ones."""
    rows, sources = {}, []
    for path in [DEFAULT_TABLE] + [pathlib.Path(t) for t in extra]:
        doc = read_json(path, errors, "table")
        if doc is None:
            continue
        if doc.get("format") != "coverity-triage-checker-lanes" or doc.get("schema") != 1:
            errors.append(str(path) + ": format/schema must be coverity-triage-checker-lanes / 1")
            continue
        for name, row in (doc.get("checkers") or {}).items():
            bad = row_problems(name, row)
            if bad:
                errors.extend(str(path) + ": " + b for b in bad)
            else:
                rows[name] = row
        sources.append(str(path) if path != DEFAULT_TABLE else "references/checker-lanes.json")
    return rows, sources


def assign(args):
    errors = []
    bdir = pathlib.Path(args.bundles)
    index = read_json(bdir / "index.json", errors, "index")
    rows, sources = load_tables(args.table, errors)
    if errors:
        return fail(errors)
    fixed, pending, unplaced = [], [], collections.defaultdict(list)
    for b in index.get("bundles", []):
        mk, checker = b["mergeKey"], b.get("checker")
        row = rows.get(checker)
        if row is None:
            unplaced[checker].append(b)
            pending.append({"mergeKey": mk, "checker": checker, "unplaced": True})
        elif "lane" in row:
            entry = {"mergeKey": mk, "checker": checker, "lane": row["lane"],
                     "reason": row["why"].strip(), "assigned_by": TABLE}
            for k in ("method", "route"):
                if k in row:
                    entry[k] = row[k]
            fixed.append(entry)
        else:
            entry = {"mergeKey": mk, "checker": checker, "candidates": row["lanes"],
                     "decide": row["decide"].strip()}
            for k in ("method", "route"):
                if k in row:
                    entry[k] = row[k]
            pending.append(entry)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps({"tables": sources, "lanes": fixed, "pending": pending},
                                indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    counts = collections.Counter(e["lane"] for e in fixed)
    n_inf = sum(1 for e in pending if not e.get("unplaced"))
    print("wrote " + str(out) + ": " + str(len(fixed)) + " lane(s) from the checker table ("
          + ", ".join(l + " " + str(counts.get(l, 0)) for l in ALL_LANES) + "); "
          + str(n_inf) + " need inference; "
          + str(sum(len(v) for v in unplaced.values())) + " unplaced")
    if n_inf:
        print("needs inference (choose among the candidates, per finding):")
        for e in pending:
            if not e.get("unplaced"):
                print("  " + e["mergeKey"] + "  " + e["checker"] + "  "
                      + " | ".join(e["candidates"]) + "  -- " + e["decide"])
    if unplaced:
        print("unplaced checkers (no row in any table; determine one row per checker, add it "
              "to a table file, and run assign again with --table):")
        for c, bs in sorted(unplaced.items()):
            print("  " + str(c) + "  (" + str(len(bs)) + " finding(s))")
    return 0


def check_table(args):
    errors = []
    for t in args.tables:
        doc = read_json(t, errors, "table")
        if doc is None:
            continue
        if doc.get("format") != "coverity-triage-checker-lanes" or doc.get("schema") != 1:
            errors.append(t + ": format/schema must be coverity-triage-checker-lanes / 1")
            continue
        for name, row in (doc.get("checkers") or {}).items():
            errors.extend(t + ": " + b for b in row_problems(name, row))
    if errors:
        return fail(errors)
    print("valid: " + ", ".join(args.tables))
    return 0


def fail(errors):
    for e in errors:
        print("[ERROR] " + e, file=sys.stderr)
    print("[FATAL] " + str(len(errors)) + " problem(s); nothing written", file=sys.stderr)
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("assign")
    a.add_argument("--bundles", required=True, help="tools/bundle.py --out directory")
    a.add_argument("--table", action="append", default=[],
                   help="another checker table, after the skill's own; repeatable, later wins")
    a.add_argument("--out", required=True, help="lanes.json to write")
    c = sub.add_parser("check-table", help="validate checker table files")
    c.add_argument("tables", nargs="+")
    args = ap.parse_args()
    return assign(args) if args.cmd == "assign" else check_table(args)


if __name__ == "__main__":
    sys.exit(main())
