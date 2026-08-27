#!/usr/bin/env python3
"""Compare two analyzed idirs and decide whether they found the same defects.

This is the instrument that answers the only question that matters for idir
reuse: **did the reused idir produce the same answer as a fresh capture?**
Timing is worthless if the answer is different.

`summary.txt` counts are NOT sufficient. Identical totals hide a defect
appearing in one place and vanishing in another, and that is exactly the error
this procedure could introduce.

## The key

`<error>` records in `output/<CHECKER>.errors.xml` carry no mergeKey and no CID
-- Connect assigns those, cov-analyze does not. So the key is constructed:

    (checker, subtype, path-normalized file, function, event-shape)

`event-shape` is a hash of the ordered `(tag, line)` pairs, which distinguishes
two findings of the same checker in the same function. Paths are normalized
because a reused idir records the *capture-time* root, which differs from a
fresh capture's.

## The vacuity guard, and why it exists

An oracle that finds nothing agrees with everything. During development of this
skill an earlier comparison keyed on a `<mergeKey>` element that **does not
exist**, compared two empty sets, and reported `IDENTICAL: True`. It was
completely wrong and completely convincing.

So this tool REFUSES to report agreement unless it can show it was capable of
disagreement:

  * both sides must yield a non-zero defect count
  * `--self-test` perturbs one side and asserts the difference is detected

Never trust a green result from this tool without `--self-test` having passed
on the same inputs.
"""
import argparse, os, sys, glob, re, hashlib, collections
import xml.etree.ElementTree as ET


def norm_path(p, root):
    p = (p or "").replace("\\", "/")
    if root:
        r = root.replace("\\", "/").rstrip("/")
        if p.startswith(r + "/"):
            return p[len(r) + 1:]
    # fall back: drop everything up to a recognisable source root marker
    return p


def infer_root(paths):
    """Longest common directory prefix of the defect files."""
    paths = [p.replace("\\", "/") for p in paths if p]
    if not paths:
        return ""
    parts = [p.split("/") for p in paths]
    common = []
    for i in range(min(len(x) for x in parts)):
        seg = parts[0][i]
        if all(x[i] == seg for x in parts):
            common.append(seg)
        else:
            break
    return "/".join(common)


def load(idir, root=None):
    """Return {key: record} for every <error> in the idir's errors.xml files."""
    out = {}
    files = sorted(glob.glob(os.path.join(idir, "output", "*.errors.xml")))
    raw = []
    for fn in files:
        # errors.xml is NOT a well-formed document: it is a CONCATENATION of
        # <error> elements with no single root, so ET.parse() fails on nearly
        # every one with "junk after document element". Only files holding a
        # single <error> parse by accident -- which is worse than total
        # failure, because it yields a small non-empty set that looks valid.
        try:
            with open(fn, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
            body = re.sub(r"<[?]xml[^>]*[?]>", "", body)
            tree = ET.fromstring("<covroot>" + body + "</covroot>")
        except ET.ParseError as e:
            sys.stderr.write("WARN: unparsable %s: %s\n" % (fn, e))
            continue
        for err in tree.iter("error"):
            g = lambda t: (err.findtext(t) or "").strip()
            events = [((e.findtext("tag") or "").strip(),
                       (e.findtext("line") or "").strip())
                      for e in err.findall("event")]
            raw.append({"checker": g("checker"), "subtype": g("subtype"),
                        "file": g("file"), "function": g("function"),
                        "events": events})
    if root is None:
        root = infer_root([r["file"] for r in raw])
    for r in raw:
        shape = hashlib.md5(("|".join("%s@%s" % e for e in r["events"]))
                            .encode()).hexdigest()[:12]
        r["rel"] = norm_path(r["file"], root)
        key = (r["checker"], r["subtype"], r["rel"], r["function"], shape)
        # a genuine duplicate key means two identical findings; keep a counter
        n = 0
        while (key + (n,)) in out:
            n += 1
        out[key + (n,)] = r
    return out, root, len(files)



def expected_count(idir):
    """`Defect occurrences found` from summary.txt -- an authority the parser
    does not compute, so it can catch a parser that silently under-reads."""
    p = os.path.join(idir, "output", "summary.txt")
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            m = re.search(r"Defect occurrences found\s*:\s*(\d+)", fh.read())
        return int(m.group(1)) if m else None
    except OSError:
        return None


def summarize(tag, d, root, nfiles):
    print("  %-8s %6d defects  across %d checker files" % (tag, len(d), nfiles))
    print("           inferred root: %s" % (root or "(none)"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="idir A (e.g. the reused one)")
    ap.add_argument("--b", required=True, help="idir B (e.g. the fresh oracle)")
    ap.add_argument("--root-a", help="capture root of A; inferred if omitted")
    ap.add_argument("--root-b", help="capture root of B; inferred if omitted")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the comparison can detect a difference")
    ap.add_argument("--show", type=int, default=12, help="max differences to list")
    a = ap.parse_args()

    A, ra, na = load(a.a, a.root_a)
    B, rb, nb = load(a.b, a.root_b)
    print("COMPARE")
    summarize("A", A, ra, na)
    summarize("B", B, rb, nb)
    print()

    # ---- vacuity guard -------------------------------------------------
    # "non-zero" is NOT sufficient. Measured during development: a broken parser
    # read 5 of 1209 defects -- the files that happened to hold a single <error>
    # and so were accidentally well-formed -- and the comparison cheerfully
    # reported IDENTICAL on 0.4% of the data. Cross-check against an authority
    # the parser does not compute.
    if not A or not B:
        print("REFUSING TO COMPARE: one side has zero defects.")
        print("  An oracle that finds nothing agrees with everything.")
        return 2
    bad = False
    for tag, d, idir in (("A", A, a.a), ("B", B, a.b)):
        exp = expected_count(idir)
        if exp is None:
            print("REFUSING: %s has no readable summary.txt; cannot verify the parse." % tag)
            bad = True
        elif len(d) != exp:
            print("REFUSING: %s parsed %d defects but summary.txt says %d."
                  % (tag, len(d), exp))
            print("  The parser is not reading everything. Any verdict would be")
            print("  drawn from a subset and is worthless.")
            bad = True
    if bad:
        return 2

    only_a = set(A) - set(B)
    only_b = set(B) - set(A)
    same = set(A) & set(B)

    if a.self_test:
        # Remove one real finding from A and confirm the comparison notices.
        victim = next(iter(A))
        probe = dict(A); probe.pop(victim)
        detected = len(set(B) - set(probe)) > len(only_b)
        print("SELF-TEST: removed one finding from A -> difference %s"
              % ("DETECTED" if detected else "MISSED"))
        if not detected:
            print("  The comparison cannot detect a known difference. Its verdict")
            print("  is meaningless. Fix the key before trusting any result.")
            return 2
        print()

    print("RESULT")
    print("  in both      : %d" % len(same))
    print("  only in A    : %d" % len(only_a))
    print("  only in B    : %d" % len(only_b))
    print()

    if not only_a and not only_b:
        print("VERDICT: IDENTICAL -- every defect in A appears in B and vice versa.")
        if not a.self_test:
            print("  NOTE: run with --self-test to confirm this comparison was")
            print("        capable of detecting a difference at all.")
        return 0

    by_checker = collections.Counter()
    for k in only_a: by_checker[("A-only", k[0])] += 1
    for k in only_b: by_checker[("B-only", k[0])] += 1
    print("  differences by checker:")
    for (side, chk), n in by_checker.most_common(20):
        print("    %-8s %-34s %d" % (side, chk, n))
    print()
    for tag, s, d in (("ONLY IN A", only_a, A), ("ONLY IN B", only_b, B)):
        if not s: continue
        print("  %s (first %d):" % (tag, min(a.show, len(s))))
        for k in list(sorted(s))[:a.show]:
            r = d[k]
            print("    %-26s %-40s %s" % (r["checker"], r["rel"][-40:], r["function"]))
        print()
    print("VERDICT: DIFFERENT -- %d only in A, %d only in B."
          % (len(only_a), len(only_b)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
