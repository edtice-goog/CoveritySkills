"""Call graph from the cross-reference data in an idir's emit database.

Uses the blob parser in ta/xref_format.py: a call reference (kind 04) holds the callee entity and the entity whose body holds the call. Functions are identified as
"<repo-relative definition file>:<name>", matching changes.Fn.fid.

Java blobs (header 00 00) differ in two ways, and `load` handles both:
  - `ctx` is the same for every reference, so the caller is the innermost function of the same file whose line range
    (changes.functions, from FUNCTION.metrics) holds the call line;
  - a call links to the method declared on the receiver's static type, so a call through a base class or an
    interface is an edge to every override of it: the walk then reaches the
    callers of every method an affected override overrides. The class hierarchy is read from the same blobs: the
    class references between a class's declaration line and its first member are its supertypes.
"""
import collections
import glob
import zlib

from . import xref_format as F
from .models import strip_return

from . import emitdb as XL  # the SQLite access; the blob format is xref_format

FUNC, VAR, CLASS = 3, 2, 7
CALL, ADDR, TYPE_USE = 0x04, 0x02, 14
STATIC = 15
JAVA_HEADER = b"\x00\x00"


class Graph:
    def __init__(self):
        self.callers = collections.defaultdict(set)      # callee fid -> {caller fid}
        self.sites = collections.defaultdict(set)        # (caller fid, callee fid) -> {line}
        self.indirect = collections.defaultdict(set)     # caller fid -> {line} of calls through a pointer
        self.address_taken = collections.defaultdict(set)  # fid -> {fid of the function taking its address}
        self.virtual = collections.defaultdict(set)      # (caller fid, callee fid) -> {declared method called}
        self.supers = {}                                 # Java: class -> {direct supertypes}
        self.unresolved = collections.Counter()


def load(idir, roots, fns):
    """Graph over the functions in `fns` (changes.functions of the same idir)."""
    from .changes import rel
    by_name = collections.defaultdict(list)
    by_file = collections.defaultdict(list)
    for f in fns:
        by_name[f.name].append(f.file)
        by_file[f.file].append(f)

    def resolve(name, static, here):
        files = by_name.get(name, [])
        if len(files) == 1:
            return f"{files[0]}:{name}"
        if here in files and (static or len(files) > 1):
            return f"{here}:{name}"
        return None

    def caller_fid(ents, syms, ctx, here):
        e = ents.get(ctx)
        while e is not None and e["kind"] != FUNC:
            e = ents.get(e["parent"]) if e["parent"] else None
        if e is None:
            return None
        return resolve(syms[e["name"]], STATIC in e.get("sub", []), here)

    g = Graph()
    declared = _Declared()
    db = glob.glob(f"{idir}/emit/*/emit-db")[0]
    con = XL.connect(db)
    root = roots[0].rstrip("/") + "/"
    for _, path, xr in XL.rows(con, lambda p: p.startswith(root)):
        if xr == -1:
            continue
        here = rel(path, roots)
        blob = con.execute("select info from Xrefs where XrefsId=?", (xr,)).fetchone()[0]
        r = F.parse(zlib.decompress(blob))
        ents, syms = {e["idx"]: e for e in r["entities"]}, r["symbols"]
        if r["header"] == JAVA_HEADER:
            _java_file(g, declared, r, ents, syms, here, by_file.get(here, ()), resolve)
            continue
        for x in r["refs"]:
            t = ents.get(x["ent"])
            if t is None or x["kind"] not in (CALL, ADDR):
                continue
            caller = caller_fid(ents, syms, x["ctx"], here)
            if t["kind"] == VAR and x["kind"] == CALL and caller:
                g.indirect[caller].add(x["line"])
                continue
            if t["kind"] != FUNC:
                continue
            callee = resolve(syms[t["name"]], STATIC in t.get("sub", []), here)
            if callee is None:
                g.unresolved[syms[t["name"]]] += 1
                continue
            if x["kind"] == ADDR:
                g.address_taken[callee].add(caller or "<file scope>")
            elif caller:
                g.callers[callee].add(caller)
                g.sites[(caller, callee)].add(x["line"])
    con.close()
    if g.supers:
        _overrides(g, declared, fns)
    return g


class _Declared:
    """Java: every call by the name of the method it declares, resolved or not (a base method may have no body)."""

    def __init__(self):
        self.callers = collections.defaultdict(set)   # declared name -> {caller fid}
        self.sites = collections.defaultdict(set)     # (caller fid, declared name) -> {line}


def _java_file(g, declared, r, ents, syms, here, file_fns, resolve):
    spans = sorted(file_fns, key=lambda f: (f.start, -f.end))

    def enclosing(line):
        best = None
        for f in spans:
            if f.start > line:
                break
            if line <= f.end and (best is None or f.end - f.start <= best.end - best.start):
                best = f
        return best

    for x in r["refs"]:
        t = ents.get(x["ent"])
        if t is None or x["kind"] != CALL or t["kind"] != FUNC:
            continue
        name = strip_return(syms[t["link"]] if t["link"] >= 0 else syms[t["name"]])
        caller = enclosing(x["line"])
        if caller is None:
            g.unresolved["<call outside any function>"] += 1
            continue
        declared.callers[name].add(caller.fid)
        declared.sites[(caller.fid, name)].add(x["line"])
        callee = resolve(name, False, here)
        if callee is None:
            g.unresolved[name] += 1
            continue
        g.callers[callee].add(caller.fid)
        g.sites[(caller.fid, callee)].add(x["line"])

    # supertypes: type references between a class's declaration line and its first member
    path = r["files"][0] if r["files"] else None
    own = lambda e: e["file"] >= 0 and r["files"][e["file"]] == path
    classes = [e for e in r["entities"] if e["kind"] == CLASS and own(e) and e["line"] > 0]
    member_lines = sorted({e["line"] for e in r["entities"] if e["kind"] in (VAR, FUNC) and own(e) and e["line"] > 0}
                          | {c["line"] for c in classes})
    for c in classes:
        end = next((n for n in member_lines if n > c["line"]), c["line"] + 1)
        mine = syms[c["link"]]
        for x in r["refs"]:
            t = ents.get(x["ent"])
            if x["kind"] == TYPE_USE and t is not None and t["kind"] == CLASS and c["line"] <= x["line"] < end:
                sup = syms[t["link"]]
                if sup != mine:
                    g.supers.setdefault(mine, set()).add(sup)


def _overrides(g, declared, fns):
    """An edge from every call of a declared method to each override of it that has a body."""
    memo = {}

    def closure(cls):
        if cls not in memo:
            memo[cls] = set()
            for s in g.supers.get(cls, ()):
                memo[cls] |= {s} | closure(s)
        return memo[cls]

    for f in fns:
        paren = f.name.find("(")
        if paren < 0:
            continue
        dot = f.name.rfind(".", 0, paren)
        cls, key = f.name[:dot], f.name[dot + 1:]
        if key.startswith("<"):          # <init>, <clinit>, <instance_field_initializations>: not overridden
            continue
        for sup in closure(cls):
            base = f"{sup}.{key}"
            for caller in declared.callers.get(base, ()):
                if caller == f.fid:
                    continue
                g.callers[f.fid].add(caller)
                g.sites[(caller, f.fid)] |= declared.sites[(caller, base)]
                g.virtual[(caller, f.fid)].add(base)
