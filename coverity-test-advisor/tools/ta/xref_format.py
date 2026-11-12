"""Parser for Coverity emit-db Xrefs blobs (zlib-decompressed Xrefs.info), Coverity Analysis 2026.9.0.

The format is not documented by Coverity; this grammar was worked out from the blobs themselves and checked byte for
byte on Coverity Analysis 2026.9.0 for Linux only, so callers must refuse other versions.
  - The header is 01 01 for C and C++ blobs and 00 00 for Java blobs; parse() returns it as "header".
  - Strict by default: parse() raises if bytes are left after the last reference, so a changed format fails loudly.

Grammar:

  blob     := 01 01 | 00 00  strings(symbols)  strings(files)  entities  references
  strings  := v:count  { v:len  bytes[len] }
  entities := v:count  { entity }
  entity   := 04  v:dfile  v:dname                                   file entity (an #include target)
            | kind  v:n  v[n]:subkind  v:dfile v:dline v:dname v:dlink v:dparent v:dq
  references := v:count { ref }
  ref      := kind  v:n  v[n]:extra  v:dline  v:col  v:dent  v:dctx

Every v is a signed varint: 0xxxxxxx is 7-bit two's complement; 10xxxxxx + 1 byte is 14-bit; 110xxxxx + 2 bytes is
21-bit; 1110xxxx + 3 bytes is 28-bit; 11110000 + 4 bytes is 32-bit. All numbers big-endian.

All d* fields are deltas against a running cursor per field; the cursors are:
  dfile  -> index into the files list, starts at -1
  dline  -> line, starts at 1 (entities and references keep separate line cursors)
  dname, dlink -> one shared index into the symbol list, starts at -1 (-1 = no name)
  dparent, dq -> entity index, start at 0
  dent, dctx  -> entity index, start at 0
Entity indices: 0 and 1 are reserved (0 = file scope); the k-th entity in the list has index k + 2.
col is the 0-based column of the reference when dline != 0, else the offset from the previous reference's column.

Java blobs follow the same grammar, with two differences in what the fields hold: a function entity's `link` symbol is
the qualified name with erased parameter types and the return type ("a.B.m(int, java.lang.String)void"), and every
reference's `ctx` is 1, so the function that holds a call is not named (callgraph.py finds it from the line).
"""

HEADERS = (b"\x01\x01", b"\x00\x00")


def varint(b, i):
    x = b[i]
    if x < 0x80:
        v, w, i = x & 0x7F, 7, i + 1
    elif x < 0xC0:
        v, w, i = ((x & 0x3F) << 8) | b[i + 1], 14, i + 2
    elif x < 0xE0:
        v, w, i = ((x & 0x1F) << 16) | (b[i + 1] << 8) | b[i + 2], 21, i + 3
    elif x < 0xF0:
        v, w, i = ((x & 0x0F) << 24) | (b[i + 1] << 16) | (b[i + 2] << 8) | b[i + 3], 28, i + 4
    elif x == 0xF0:
        v, w, i = int.from_bytes(b[i + 1:i + 5], "big"), 32, i + 5
    else:
        raise ValueError(f"bad varint lead byte {x:#x} at {i:#x}")
    if v >= 1 << (w - 1):
        v -= 1 << w
    return v, i


def strings(b, i):
    n, i = varint(b, i)
    out = []
    for _ in range(n):
        ln, i = varint(b, i)
        out.append(b[i:i + ln].decode("utf-8", "replace"))
        i += ln
    return out, i


FILE_ENTITY = 4


def parse(b, strict=True):
    """Return dict(header, symbols, files, entities, refs). Entities and refs carry absolute (cursor-resolved) values."""
    if b[:2] not in HEADERS:
        raise ValueError(f"unexpected header {b[:2].hex()}")
    header = b[:2]
    i = 2
    syms, i = strings(b, i)
    files, i = strings(b, i)
    ne, i = varint(b, i)
    ents = []
    fcur, lcur, ncur, pcur, qcur = -1, 1, -1, 0, 0
    for k in range(ne):
        start = i
        kind, i = varint(b, i)
        if kind == FILE_ENTITY:
            df, i = varint(b, i)
            dn, i = varint(b, i)
            fcur += df
            ncur += dn
            ents.append({"idx": k + 2, "kind": kind, "file": fcur, "name": ncur, "at": start})
            continue
        n, i = varint(b, i)
        sub = []
        for _ in range(n):
            s, i = varint(b, i)
            sub.append(s)
        vals = []
        for _ in range(6):
            v, i = varint(b, i)
            vals.append(v)
        df, dl, dn, dk, dp, dq = vals
        fcur += df
        lcur += dl
        ncur += dn
        name = ncur
        ncur += dk
        pcur += dp
        qcur += dq
        ents.append({"idx": k + 2, "kind": kind, "sub": sub, "file": fcur, "line": lcur, "name": name,
                     "link": ncur, "parent": pcur, "q": qcur, "at": start})
    nr, i = varint(b, i)
    refs = []
    lcur, ccur, ecur, xcur = 1, 0, 0, 0
    for _ in range(nr):
        start = i
        kind, i = varint(b, i)
        n, i = varint(b, i)
        extra = []
        for _ in range(n):
            s, i = varint(b, i)
            extra.append(s)
        dl, i = varint(b, i)
        c, i = varint(b, i)
        de, i = varint(b, i)
        dx, i = varint(b, i)
        lcur += dl
        ccur = c if dl != 0 else ccur + c
        ecur += de
        xcur += dx
        refs.append({"kind": kind, "extra": extra, "line": lcur, "col": ccur, "ent": ecur, "ctx": xcur,
                     "at": start})
    if strict and i != len(b):
        raise ValueError(f"{len(b) - i} trailing bytes after {nr} refs (ends at {i:#x} of {len(b):#x})")
    return {"header": header, "symbols": syms, "files": files, "entities": ents, "refs": refs, "end": i}
