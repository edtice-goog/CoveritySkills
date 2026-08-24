"""Recover build-time filesystem paths embedded in a binary.

Needed because in production the reference artifact comes from a CI system
whose working directory we do not control, and offsets only stay aligned if we
reproduce that path -- or, failing that, its LENGTH.

Evidence sources, in descending order of reliability:
  1. PE debug directory CODEVIEW/RSDS record -- the full PDB path. Present in
     any build that emits a PDB; absent in CMake Release, which emits none.
  2. Embedded source paths: __FILE__ from assert/_wassert, and the source file
     names COFF objects carry in their debug records.
  3. Bulk string scan for anything path-shaped, ASCII and UTF-16LE.

Nothing here decides the answer. It produces ranked candidates plus the
evidence for each, so the caller (model or human) can choose, and so the choice
can be VERIFIED afterwards by rebuilding and re-scanning.
"""
import os
import re
import sys
from collections import Counter

import pe

# The (?![\\/]) guard rejects URL schemes: "http://host/" satisfies the
# drive-letter shape otherwise, and zlib.dll's embedded homepage URL was
# reported as a build root during calibration.
WIN_PATH = re.compile(rb"[A-Za-z]:[\\/](?![\\/])[^\x00-\x1f\"<>|*?]{2,200}")
NIX_PATH = re.compile(rb"/(?:home|build|work|src|opt|usr|mnt|tmp|var)/"
                      rb"[^\x00-\x1f\"<>|*?:]{2,200}")
WIDE_WIN = re.compile((rb"(?:[A-Za-z]\x00:\x00[\\/]\x00(?![\\/]\x00)"
                       rb"(?:[^\x00][\x00]){2,200})"))

# CI systems put builds in recognizable places. A partial string plus one of
# these is usually enough to reconstruct the full original root.
CI_SIGNATURES = [
    (re.compile(r"^[A-Za-z]:[\\/]a[\\/]\d+[\\/]s", re.I), "Azure DevOps (default agent workspace)"),
    (re.compile(r"^[A-Za-z]:[\\/]a[\\/][^\\/]+[\\/][^\\/]+", re.I), "GitHub Actions (D:\\a\\<repo>\\<repo>)"),
    (re.compile(r"[\\/]jenkins[\\/]workspace[\\/]", re.I), "Jenkins"),
    (re.compile(r"[\\/]BuildAgent[\\/]work[\\/]", re.I), "TeamCity"),
    (re.compile(r"[\\/]builds[\\/][^\\/]+[\\/][^\\/]+", re.I), "GitLab CI"),
    (re.compile(r"[\\/]__w[\\/]", re.I), "GitHub Actions (container runner)"),
    (re.compile(r"[\\/]workspace[\\/]", re.I), "generic CI workspace"),
]

SOURCE_EXT = (".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".asm", ".rc")


def _decode(raw, wide):
    try:
        return raw.decode("utf-16-le" if wide else "ascii", "strict").rstrip("\x00")
    except UnicodeDecodeError:
        return raw.decode("latin-1", "replace")


def scan(data):
    hits = []
    for rx, wide in ((WIN_PATH, False), (NIX_PATH, False), (WIDE_WIN, True)):
        for m in rx.finditer(data):
            txt = _decode(m.group(), wide).strip()
            txt = txt.split("\x00")[0]
            if len(txt) < 6:
                continue
            hits.append({"off": m.start(), "enc": "utf-16le" if wide else "ascii",
                         "text": txt})
    seen = set()
    out = []
    for h in sorted(hits, key=lambda x: x["off"]):
        if h["text"] in seen:
            continue
        seen.add(h["text"])
        out.append(h)
    return out


def structured_evidence(path):
    """High-confidence evidence from parsed structure rather than raw strings."""
    ev = []
    with open(path, "rb") as fh:
        data = fh.read()
    try:
        obj = pe.inspect(data)
    except Exception:
        obj = None
    if isinstance(obj, pe.PE):
        for e in obj.debug_entries:
            if "pdb_path" in e:
                ev.append({"source": "debug.CODEVIEW.RSDS.PdbPath",
                           "confidence": "high", "value": e["pdb_path"]})
        if not ev:
            ev.append({"source": "debug directory", "confidence": "n/a",
                       "value": None,
                       "note": "no CODEVIEW/RSDS record -- build emitted no PDB "
                               "reference, so this artifact carries no PDB path"})
    return ev, data


def dirname_of(p):
    p = p.replace("/", "\\")
    if p.lower().endswith(SOURCE_EXT) or "." in os.path.basename(p):
        p = p.rsplit("\\", 1)[0]
    return p


def common_roots(texts, min_depth=2, min_support=1):
    """Cluster path strings by shared prefix to propose build roots."""
    counter = Counter()
    for t in texts:
        parts = dirname_of(t).split("\\")
        for i in range(min_depth, len(parts) + 1):
            counter["\\".join(parts[:i])] += 1
    roots = []
    for root, n in counter.items():
        if n < min_support or len(root) < 6:
            continue
        roots.append((n, len(root), root))
    roots.sort(key=lambda r: (-r[0], -r[1]))
    return roots


def classify_ci(root):
    for rx, name in CI_SIGNATURES:
        if rx.search(root):
            return name
    return None


def report(path):
    ev, data = structured_evidence(path)
    strings = scan(data)
    print("=== %s  (%d bytes)" % (path, len(data)))
    print("-- structured evidence")
    if ev:
        for e in ev:
            print("   [%s] %s: %s" % (e["confidence"], e["source"],
                                      e.get("value") or e.get("note")))
    else:
        print("   (none)")

    print("-- path-shaped strings: %d" % len(strings))
    for s in strings[:25]:
        print("   0x%08x %-8s %s" % (s["off"], s["enc"], s["text"][:120]))
    if len(strings) > 25:
        print("   ... %d more" % (len(strings) - 25))

    roots = common_roots([s["text"] for s in strings])
    print("-- candidate build roots (by supporting string count)")
    if not roots:
        print("   (none -- no path evidence in this artifact)")
    for n, ln, root in roots[:8]:
        ci = classify_ci(root)
        print("   %2d strings  len=%-3d %s%s" % (n, ln, root,
                                                 ("   <- %s" % ci) if ci else ""))
    return roots


def main(argv):
    if len(argv) < 2:
        print("usage: paths.py FILE [FILE...]")
        return 2
    for p in argv[1:]:
        report(p)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
