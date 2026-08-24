"""Three-way delta-shape comparison.

Given three snapshots, compare the SHAPE of each pairwise delta. Region CONTENT
is expected to differ in every pair -- a timestamp holds a different value each
run -- so it is the shape that must agree.

Shape matching is by INTERVAL OVERLAP, not offset equality. Calibration on zlib
showed why: the same 4-byte archive timestamp surfaced as (106192, 2) in one
pair and (106191, 3) in another, because which bytes happened to collide varies
run to run. Exact keys report that as a shape mismatch; it is the same field.

Used two ways:
  calibration : three native builds; all three shapes should agree, which is
                what licenses the method in the first place.
  production  : shape(control) vs shape(test); K is what the test pair has that
                the control pair does not.
"""
import json
import os
import sys

import bindiff

SLACK = 8          # bytes of tolerance when matching unlabeled intervals


def shape(pa, pb):
    """(result, labeled-field set, unlabeled intervals)."""
    res = bindiff.compare(pa, pb)
    fields = {",".join(r["known_fields"]) for r in res["regions"]
              if r["known_fields"]}
    raws = [(r["section"], r["off"], r["len"]) for r in res["regions"]
            if not r["known_fields"]]
    return res, fields, raws


def _overlaps(iv, others, slack=SLACK):
    _s, off, ln = iv
    lo, hi = off - slack, off + ln + slack
    return any(o < hi and lo < o + l for (_x, o, l) in others)


def raws_agree(x, y, slack=SLACK):
    return (all(_overlaps(iv, y, slack) for iv in x) and
            all(_overlaps(iv, x, slack) for iv in y))


def subtract(test_raws, control_raws, slack=SLACK):
    """Unlabeled intervals present in test but not accounted for by control."""
    return [iv for iv in test_raws if not _overlaps(iv, control_raws, slack)]


def walk(root):
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(dirpath, f)
            out.append(os.path.relpath(p, root).replace("\\", "/"))
    return sorted(out)


def main(argv):
    if len(argv) < 4:
        print("usage: threeway.py SNAP_A SNAP_B SNAP_C [--json OUT]")
        return 2
    a, b, c = argv[1], argv[2], argv[3]
    out_path = argv[argv.index("--json") + 1] if "--json" in argv else None

    files = walk(a)
    report = {"snapshots": [a, b, c], "files": []}
    agree = disagree = identical = 0

    for rel in files:
        pa, pb, pc = (os.path.join(x, rel) for x in (a, b, c))
        if not (os.path.exists(pb) and os.path.exists(pc)):
            report["files"].append({"path": rel, "status": "MISSING"})
            continue
        rab, fab, wab = shape(pa, pb)
        rac, fac, wac = shape(pa, pc)
        rbc, fbc, wbc = shape(pb, pc)

        if not (fab or wab or fac or wac or fbc or wbc):
            identical += 1
            report["files"].append({"path": rel, "status": "IDENTICAL"})
            continue

        ok = (fab == fac == fbc and raws_agree(wab, wac)
              and raws_agree(wab, wbc))
        agree += ok
        disagree += (not ok)
        entry = {
            "path": rel,
            "status": "SHAPE_AGREES" if ok else "SHAPE_DIFFERS",
            "format": rab.get("format"),
            "sizes_stable": not (rab["size_mismatch"] or rac["size_mismatch"]
                                 or rbc["size_mismatch"]),
            "fields": sorted(fab),
            "unresolved": [list(iv) for iv in wab],
        }
        if not ok:
            entry["field_delta"] = {
                "only_AB": sorted(fab - (fac | fbc)),
                "only_AC": sorted(fac - (fab | fbc)),
                "only_BC": sorted(fbc - (fab | fac)),
            }
            entry["raw_delta"] = {
                "AC_not_in_AB": [list(i) for i in subtract(wac, wab)][:8],
                "BC_not_in_AB": [list(i) for i in subtract(wbc, wab)][:8],
            }
        report["files"].append(entry)

    report["totals"] = {"files": len(files), "identical": identical,
                        "shape_agrees": agree, "shape_differs": disagree}
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)

    print("files=%d  identical=%d  shape_agrees=%d  shape_differs=%d"
          % (len(files), identical, agree, disagree))
    for e in report["files"]:
        if e.get("status") == "SHAPE_DIFFERS":
            print("  MISMATCH %s" % e["path"])
            print("     fields: %s" % e.get("field_delta"))
            print("     raw   : %s" % e.get("raw_delta"))

    fieldsets = {}
    for e in report["files"]:
        if "fields" in e:
            fieldsets.setdefault(tuple(e["fields"]), []).append(e)
    print("\nephemeral field signatures observed:")
    for sig, entries in sorted(fieldsets.items(), key=lambda kv: -len(kv[1])):
        fmts = sorted({e.get("format") or "?" for e in entries})
        print("  %-2d files [%s]  %s" % (len(entries), ",".join(fmts),
                                         list(sig) or "<none resolved>"))
    unresolved = [e for e in report["files"] if e.get("unresolved")]
    print("\nfiles with unresolved regions: %d" % len(unresolved))
    for e in unresolved[:10]:
        print("  %-46s %s" % (e["path"], e["unresolved"][:3]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
