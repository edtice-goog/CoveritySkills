"""Read-only access to an idir's emit-db (SQLite): open it, and list its input files with their paths.

Opens the database immutable and read only.
"""
import sqlite3


def connect(db):
    return sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)


def paths(con):
    names = {r[0]: (r[1], r[2]) for r in con.execute("select FileNameId, parent, component from FileName")}
    cache = {}

    def path_of(fid):
        if fid in cache:
            return cache[fid]
        parts, f = [], fid
        while f in names and f != -1:
            p, c = names[f]
            parts.append(c)
            f = p
        cache[fid] = "/".join(reversed(parts))
        return cache[fid]
    return path_of


def rows(con, want):
    """(InputFileId, path, XrefsId) for InputFile rows whose path satisfies want(path)."""
    path_of = paths(con)
    out = []
    for iid, fn, xr in con.execute("select InputFileId, filename, xrefs from InputFile"):
        p = path_of(fn)
        if want(p):
            out.append((iid, p, xr))
    return out
