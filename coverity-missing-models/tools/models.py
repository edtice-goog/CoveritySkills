#!/usr/bin/env python3
"""What the analyzer believes about functions, and what a model changed.

    models.py inventory --idir <idir> [--name F ...]
    models.py compare --before <idir> --after <idir-copy> \
        --before-findings before.json --after-findings after.json \
        [--model-source models.c ...] [--expect gone|new|kept|silent=<spec> ...]

`inventory` reads output/callgraph-metrics.json.gz from an analyzed idir and
lists, per function, where its model came from:
  - user models applied (`models: ["userN", ...]`, with `modelFiles` naming N)
  - project code analyzed with a built-in model of the same name
    (`hasImplementation: true` with `built-in` in `models`): the built-in
    model wins over the code, so the code's own behaviour is not analyzed
  - functions with no model at all (`missingModels: ["all"]`): externals the
    analyzer knows nothing about, ranked by `importance`

`compare` checks a re-analysis with models against the run without them:
  - every function a model source defines took its user model; a model whose
    name matches nothing builds and analyzes without a word, and changes
    nothing
  - the same code was analyzed: files, LoC and functions from summary.txt
    (paths may differ; models change which paths are explored)
  - every finding that appeared or vanished, by merge key, per checker, and
    whether its trace runs through a user model
  - optional expectations: <spec> is a merge key or `path:line[:CHECKER]`,
    path matched as a suffix. gone = before and not after; new = after and
    not before; kept = both; silent = neither.
Exit status 1 when a model did not apply, the code analyzed differs, or an
expectation fails.

Findings are cov-format-errors --json-output-v10 files. Standard library only.
"""
import argparse, gzip, json, os, re, sys

USER_NOTE = "overridden by a user model"


def load_cgm(idir):
    path = os.path.join(idir, "output", "callgraph-metrics.json.gz")
    if not os.path.exists(path):
        sys.exit("no %s: analyze the idir first" % path)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        d = json.load(f)
    return d.get("functions", []), d.get("modelFiles") or {}


def by_identifier(functions):
    """One row per identifier: the same function can appear in several records."""
    rows = {}
    for f in functions:
        r = rows.setdefault(f.get("identifier"), {
            "identifier": f.get("identifier"), "file": f.get("file"), "line": f.get("line"),
            "hasImplementation": False, "models": [], "missingModels": [], "importance": 0})
        r["hasImplementation"] |= bool(f.get("hasImplementation"))
        for k in ("models", "missingModels"):
            for m in f.get(k) or []:
                if m not in r[k]:
                    r[k].append(m)
        r["importance"] = max(r["importance"], f.get("importance") or 0)
    return rows


def user_tags(row):
    return [m for m in row["models"] if m.startswith("user")]


def show(row):
    return "%-32s importance %-5s models %-28s %s:%s" % (
        row["identifier"], row["importance"], ",".join(row["models"]) or "-",
        os.path.basename(row["file"] or "?"), row["line"])


def inventory(a):
    functions, model_files = load_cgm(a.idir)
    rows = by_identifier(functions)
    if a.name:
        for n in a.name:
            print(show(rows[n]) if n in rows else "%-32s not in the callgraph" % n)
        return 0
    rank = lambda rs: sorted(rs, key=lambda r: (-r["importance"], r["identifier"]))
    user = rank(r for r in rows.values() if user_tags(r))
    clash = rank(r for r in rows.values()
                 if r["hasImplementation"] and "built-in" in r["models"] and not user_tags(r))
    none = rank(r for r in rows.values() if "all" in r["missingModels"])
    print("model files: %s" % (", ".join("%s=%s" % kv for kv in sorted(model_files.items())) or "none"))
    print("\n== user models applied: %d" % len(user))
    for r in user:
        print("  " + show(r))
    print("\n== project code analyzed with a built-in model of the same name: %d" % len(clash))
    for r in clash:
        print("  " + show(r))
    print("\n== no model at all (external, no implementation): %d" % len(none))
    for r in none[:a.limit]:
        print("  " + show(r))
    if len(none) > a.limit:
        print("  ... %d more (--limit)" % (len(none) - a.limit))
    return 0


def summary(idir):
    path = os.path.join(idir, "output", "summary.txt")
    out = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.match(r"\s*(Files analyzed|Total LoC input to cov-analyze|Functions analyzed|Paths analyzed)\s*:\s*(\d+)", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def model_names(paths):
    """Function names a model source defines (column-0 definitions, primitives excluded)."""
    names = []
    for p in paths:
        src = open(p, encoding="utf-8", errors="replace").read()
        src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
        src = re.sub(r"//[^\n]*", "", src)
        for m in re.finditer(r"(?m)^[A-Za-z_][\w \t\*&:<>,]*?\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?\{", src):
            n = m.group(1)
            if not n.startswith("__coverity_") and n not in names:
                names.append(n)
    return names


def load_findings(path):
    out = {}
    for i in json.load(open(path, encoding="utf-8"))["issues"]:
        ev = i.get("events") or []
        flat = []
        stack = list(ev)
        while stack:
            e = stack.pop()
            flat.append(e)
            stack.extend(e.get("events") or [])
        out.setdefault(i["mergeKey"], []).append({
            "checker": i["checkerName"], "subcategory": i.get("subcategory"),
            "file": (i.get("mainEventFilePathname") or "").replace("\\", "/"),
            "line": i.get("mainEventLineNumber"), "function": i.get("functionDisplayName"),
            "via_user_model": any(USER_NOTE in (e.get("eventDescription") or "") for e in flat)})
    return out


def matches(spec, key, occs):
    if re.fullmatch(r"[0-9a-f]{32}", spec):
        return spec == key
    m = re.fullmatch(r"(.+):(\d+)(?::([A-Z][A-Z_0-9]*))?", spec.replace("\\", "/"))
    if not m:
        sys.exit("an expectation names a merge key or path:line[:CHECKER], not %r" % spec)
    path, line, checker = m.groups()
    return any(o["file"].endswith(path) and str(o["line"]) == line and
               (checker is None or o["checker"] == checker) for o in occs)


def describe(key, occs):
    o = occs[0]
    return "%-18s %-24s %s:%s in %s%s  [%s]" % (
        o["checker"], o["subcategory"] or "", os.path.basename(o["file"]), o["line"],
        o["function"], "  via a user model" if any(x["via_user_model"] for x in occs) else "", key)


def compare(a):
    ok = True
    # 1. the models applied
    functions, model_files = load_cgm(a.after)
    rows = by_identifier(functions)
    print("== models applied (after): %s" %
          (", ".join("%s=%s" % kv for kv in sorted(model_files.items())) or "no model file listed"))
    for r in sorted((r for r in rows.values() if user_tags(r)), key=lambda r: r["identifier"]):
        print("  %-32s %s" % (r["identifier"], ",".join(user_tags(r))))
    expected = model_names(a.model_source or [])
    for n in expected:
        if n not in rows or not user_tags(rows[n]):
            ok = False
            print("  FAIL %s: defined in the model source, but no function took it%s" % (
                n, " (not in the callgraph)" if n not in rows else ""))
    if a.model_source and not model_files:
        ok = False
        print("  FAIL no model file in this run's callgraph-metrics: --model-file missing, or nothing matched")
    # 2. the same code
    sb, sa = summary(a.before), summary(a.after)
    print("\n== code analyzed (before -> after)")
    for k in ("Files analyzed", "Total LoC input to cov-analyze", "Functions analyzed", "Paths analyzed"):
        same = sb.get(k) == sa.get(k)
        if not same and k != "Paths analyzed":
            ok = False
        print("  %-32s %8s -> %-8s %s" % (k, sb.get(k), sa.get(k),
              "" if same else ("(paths may differ)" if k == "Paths analyzed" else "FAIL: different code")))
    # 3. the findings
    fb, fa = load_findings(a.before_findings), load_findings(a.after_findings)
    checkers = sorted({o["checker"] for d in (fb, fa) for occs in d.values() for o in occs})
    print("\n== findings per checker (before -> after)")
    for c in checkers:
        nb = sum(1 for occs in fb.values() for o in occs if o["checker"] == c)
        na = sum(1 for occs in fa.values() for o in occs if o["checker"] == c)
        print("  %-24s %4d -> %-4d %s" % (c, nb, na, "" if nb == na else "%+d" % (na - nb)))
    new = sorted(k for k in fa if k not in fb)
    gone = sorted(k for k in fb if k not in fa)
    print("\n== new: %d (read each: real, or caused by what the model left out)" % len(new))
    for k in new:
        print("  + " + describe(k, fa[k]))
    print("\n== gone: %d (read each: a false positive removed, or a real finding the model hid)" % len(gone))
    for k in gone:
        print("  - " + describe(k, fb[k]))
    # 4. expectations
    if a.expect:
        print("\n== expectations")
    for e in a.expect or []:
        kind, _, spec = e.partition("=")
        inb = any(matches(spec, k, v) for k, v in fb.items())
        ina = any(matches(spec, k, v) for k, v in fa.items())
        want = {"gone": (True, False), "new": (False, True), "kept": (True, True), "silent": (False, False)}.get(kind)
        if want is None:
            sys.exit("--expect takes gone|new|kept|silent=<spec>, not %r" % e)
        good = (inb, ina) == want
        ok &= good
        print("  %s %-6s %s  (before: %s, after: %s)" % ("ok  " if good else "FAIL", kind, spec,
              "yes" if inb else "no", "yes" if ina else "no"))
    print("\n%s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inventory", help="where each function's model came from")
    p.add_argument("--idir", required=True)
    p.add_argument("--name", action="append", help="show only these functions (repeatable)")
    p.add_argument("--limit", type=int, default=25, help="rows of functions with no model (default 25)")
    p = sub.add_parser("compare", help="what a re-analysis with models changed")
    p.add_argument("--before", required=True, help="the idir analyzed without the models")
    p.add_argument("--after", required=True, help="the copy analyzed with them")
    p.add_argument("--before-findings", required=True)
    p.add_argument("--after-findings", required=True)
    p.add_argument("--model-source", action="append", help="a model .c/.cpp file; every function it defines must take its model")
    p.add_argument("--expect", action="append", help="gone|new|kept|silent=<merge key or path:line[:CHECKER]>")
    a = ap.parse_args()
    return inventory(a) if a.cmd == "inventory" else compare(a)


if __name__ == "__main__":
    sys.exit(main())
