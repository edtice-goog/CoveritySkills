"""Localize and characterize byte differences between two binaries.

The job here is to NARROW AND PRESENT, not to judge. Each differing region is
reduced to (offset, length), mapped to its containing section, matched against
the fast-path table of fields that are ephemeral by construction, and packaged
with the surrounding strings from BOTH sides in ASCII and UTF-16LE.

Judging is left to the caller (a model, or a human): a .rdata region whose two
sides both resolve to English paths or timestamps is cheap to classify, while a
region inside an executable section is marked presumed_code and must not be
waved off without disassembly-level evidence.
"""
import json
import re
import sys

import pe

ASCII_RUN = re.compile(rb"[\x20-\x7e]{4,}")
UTF16_RUN = re.compile(rb"(?:[\x20-\x7e]\x00){4,}")
DEFAULT_GAP = 16
DEFAULT_WINDOW = 192


def diff_regions(a, b, gap=DEFAULT_GAP):
    """Runs of differing bytes, coalescing runs separated by < gap equal bytes.

    Coalescing matters: without it a single 16-byte GUID whose middle bytes
    happen to collide is reported as three findings instead of one.
    """
    n = min(len(a), len(b))
    out = []
    start = None
    last_diff = None
    for i in range(n):
        if a[i] != b[i]:
            if start is None:
                start = i
            last_diff = i
        elif start is not None and i - last_diff >= gap:
            out.append((start, last_diff - start + 1))
            start = None
    if start is not None:
        out.append((start, last_diff - start + 1))
    if len(a) != len(b):
        out.append((n, max(len(a), len(b)) - n))
    return out


def strings_near(data, lo, hi):
    """ASCII and UTF-16LE strings intersecting [lo, hi)."""
    lo = max(0, lo)
    hi = min(len(data), hi)
    if lo >= hi:
        return []
    chunk = data[lo:hi]
    found = []
    for m in ASCII_RUN.finditer(chunk):
        found.append({"enc": "ascii", "off": lo + m.start(),
                      "text": m.group().decode("ascii", "replace")})
    for m in UTF16_RUN.finditer(chunk):
        found.append({"enc": "utf-16le", "off": lo + m.start(),
                      "text": m.group().decode("utf-16-le", "replace")})
    found.sort(key=lambda s: s["off"])
    return found


def _render(raw):
    """Best-effort human rendering of the raw differing bytes themselves."""
    out = {"hex": raw[:64].hex()}
    if len(raw) > 64:
        out["hex"] += "..."
    txt = raw.decode("ascii", "replace")
    if raw and all(0x20 <= c <= 0x7E for c in raw):
        out["ascii"] = txt
    if len(raw) >= 8 and raw[1::2].count(0) > len(raw) // 4:
        try:
            w = raw.decode("utf-16-le")
            if all(c.isprintable() for c in w):
                out["utf16"] = w
        except UnicodeDecodeError:
            pass
    return out


def _field_index(p):
    if p is None:
        return []
    return [(o, o + n, name) for o, n, name in p.ephemeral_fields()]


def _known_fields(index, off, length):
    hits = []
    for lo, hi, name in index:
        if off < hi and lo < off + length:
            hits.append(name)
    return hits


def compare(path_a, path_b, gap=DEFAULT_GAP, window=DEFAULT_WINDOW,
            max_regions=400):
    with open(path_a, "rb") as fh:
        a = fh.read()
    with open(path_b, "rb") as fh:
        b = fh.read()

    result = {
        "a": path_a, "b": path_b,
        "size_a": len(a), "size_b": len(b),
        "size_mismatch": len(a) != len(b),
        "identical": a == b,
        "regions": [],
    }
    if a == b:
        return result

    pa = pb = None
    for src, key in ((a, "fmt_a"), (b, "fmt_b")):
        try:
            obj = pe.inspect(src)
        except Exception as ex:                       # malformed, not fatal
            obj = None
            result.setdefault("warnings", []).append(
                "%s parse failed: %s" % (key, ex))
        if key == "fmt_a":
            pa = obj
        else:
            pb = obj
    result["format"] = pa.summary().get("format", "opaque") if pa else "opaque"
    if pa:
        result["fmt_a"] = pa.summary()
    if pb:
        result["fmt_b"] = pb.summary()

    idx_a, idx_b = _field_index(pa), _field_index(pb)
    regions = diff_regions(a, b, gap)
    result["region_count"] = len(regions)
    result["differing_bytes"] = sum(n for _, n in regions)

    for off, length in regions[:max_regions]:
        sec = pa.section_at(off) if pa else None
        known = sorted(set(_known_fields(idx_a, off, length) +
                           _known_fields(idx_b, off, length)))
        r = {
            "off": off, "len": length,
            "section": sec["name"] if sec else None,
            "presumed_code": bool(sec and (sec.get("executable") or sec.get("code"))),
            "known_fields": known,
            "a": _render(a[off:off + length]),
            "b": _render(b[off:off + length]),
        }
        if not known:
            # Only pay for string context where the fast path did not resolve it.
            r["strings_a"] = strings_near(a, off - window, off + length + window)
            r["strings_b"] = strings_near(b, off - window, off + length + window)
        result["regions"].append(r)

    if len(regions) > max_regions:
        result["truncated"] = len(regions) - max_regions
    result["unresolved_regions"] = sum(
        1 for r in result["regions"] if not r["known_fields"])
    return result


def main(argv):
    if len(argv) < 3:
        print("usage: bindiff.py A B [--json OUT] [--gap N] [--quiet]")
        return 2
    a, b = argv[1], argv[2]
    out = None
    gap = DEFAULT_GAP
    quiet = "--quiet" in argv
    if "--json" in argv:
        out = argv[argv.index("--json") + 1]
    if "--gap" in argv:
        gap = int(argv[argv.index("--gap") + 1])

    res = compare(a, b, gap=gap)
    if out:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2)

    if res["identical"]:
        print("IDENTICAL  %s" % a)
        return 0
    print("DIFFER     %s" % a)
    print("  sizes    : %d vs %d%s" % (res["size_a"], res["size_b"],
                                       "  <-- SIZE MISMATCH" if res["size_mismatch"] else ""))
    print("  regions  : %d  (%d differing bytes, %d unresolved)" % (
        res["region_count"], res["differing_bytes"], res["unresolved_regions"]))
    if not quiet:
        for r in res["regions"][:40]:
            tag = ",".join(r["known_fields"]) if r["known_fields"] else (
                "CODE?" if r["presumed_code"] else "unresolved")
            print("   0x%08x +%-6d %-10s %s" % (
                r["off"], r["len"], r["section"] or "-", tag))
            if not r["known_fields"]:
                sa = r["a"].get("ascii") or r["a"].get("utf16") or r["a"]["hex"]
                sb = r["b"].get("ascii") or r["b"].get("utf16") or r["b"]["hex"]
                print("        a: %s" % sa[:110])
                print("        b: %s" % sb[:110])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
