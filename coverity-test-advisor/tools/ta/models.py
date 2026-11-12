"""Derived models from `cov-find-function --save`, and their diff.

A dump directory holds one `<key>.<module>.dot` per function and module, plus `list.txt`, the command's stdout,
which names the function each key belongs to. A model is compared by its edges' labels (property, interface,
options) and by the label sequences from the initial state to a final state. Source positions never enter: the
.dot carries none, and build roots in option values are stripped.
"""
import collections
import os
import re

# "<file>:<name>", C++ adds " -> <mangled name>", C has the name only. A function from a dependency jar (Java) has no
# file: its head line is the name alone. The other two kinds of line in list.txt are not heads.
HEAD_RE = re.compile(r"^(?!module = |File name base:)(?:(/[^:]*):)?(.+?)(?: -> (\S+))?$")
BASE_RE = re.compile(r"^File name base: ([0-9a-f]{32})\.(\w+)$")
EDGE_RE = re.compile(r'^(\d+) -> (\d+) \[label="((?:[^"\\]|\\.)*)"\];$')
FINAL_RE = re.compile(r"^(\d+) \[label=\d+,style=filled\];$")
MAX_PATHS = 10000


class Model:
    def __init__(self, edges, finals):
        self.labels = collections.Counter(lab for _, _, lab in edges)
        self.paths = _paths(edges, finals)

    def __eq__(self, other):
        return self.labels == other.labels and self.paths == other.paths


def _paths(edges, finals):
    """Label sequences from state 0 to a final state; a state is not revisited within one path."""
    out_edges = collections.defaultdict(list)
    for a, b, lab in edges:
        out_edges[a].append((b, lab))
    found, stack = set(), [(0, (), frozenset([0]))]
    while stack and len(found) < MAX_PATHS:
        state, seq, seen = stack.pop()
        if state in finals:
            found.add(seq)
        for nxt, lab in out_edges[state]:
            if nxt not in seen:
                stack.append((nxt, seq + (lab,), seen | {nxt}))
    return frozenset(found)


def strip_return(name):
    """A Java name is "a.B.m(int, java.lang.String)void": the model names carry the return type, the function table
    (FUNCTION.metrics) does not. C and C++ names have no parentheses (C++ is keyed by its mangled name) and pass through."""
    i = name.rfind(")")
    return name if i < 0 or "(" not in name else name[:i + 1]


def _norm(label, roots):
    for r in roots:
        label = label.replace(r.rstrip("/") + "/", "")
    return label.replace('\\"', '"').strip()


def read_dot(path, roots):
    edges, finals = [], set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            m = EDGE_RE.match(line)
            if m:
                edges.append((int(m[1]), int(m[2]), _norm(m[3], roots)))
                continue
            m = FINAL_RE.match(line)
            if m:
                finals.add(int(m[1]))
    return Model(edges, finals)


def load(dump_dir, roots):
    """{mangled name: {module: Model}}. A name dumped more than once with different models is listed in
    `disagree` (inline copies in several TUs should agree)."""
    models, disagree = collections.defaultdict(dict), set()
    name = None
    with open(os.path.join(dump_dir, "list.txt")) as f:
        for line in f:
            line = line.rstrip("\n")
            m = HEAD_RE.match(line)
            if m:
                name = strip_return(m[3] or m[2])
                continue
            m = BASE_RE.match(line)
            if m and name:
                key, module = m.groups()
                model = read_dot(os.path.join(dump_dir, f"{key}.{module}.dot"), roots)
                prev = models[name].get(module)
                if prev is not None and not prev == model:
                    disagree.add(name)
                models[name][module] = model
    return dict(models), disagree


# Modules whose changes do not count as a change in behaviour that unit tests can check.
# concurrency: locking and threading properties; a unit test cannot exercise a concurrency change, so it must not
# make callers need a test.
IGNORED_MODULES = ("concurrency",)


def diff(base, head, ignore=IGNORED_MODULES):
    """{name: {"status": new|removed|changed, "modules": {module: {"added", "removed", "structure"}}}}, for the
    functions whose models differ in at least one module not in `ignore`."""
    out = {}
    for name in sorted(set(base) | set(head)):
        if name not in base:
            out[name] = {"status": "new", "modules": {}}
            continue
        if name not in head:
            out[name] = {"status": "removed", "modules": {}}
            continue
        mods = {}
        for module in sorted(set(base[name]) | set(head[name])):
            if module in ignore:
                continue
            b, h = base[name].get(module), head[name].get(module)
            bl = b.labels if b else collections.Counter()
            hl = h.labels if h else collections.Counter()
            if b is not None and h is not None and b == h:
                continue
            mods[module] = {
                "added": sorted((hl - bl).elements()),
                "removed": sorted((bl - hl).elements()),
                "structure": bl == hl,
            }
        if mods:
            out[name] = {"status": "changed", "modules": mods}
    return out


def describe(delta):
    """One line per module, for the evidence and the defect events."""
    if delta["status"] != "changed":
        return [f"function is {delta['status']}"]
    def counted(sign, labels):
        return [f"{sign} {lab}" + (f" (x{n})" if n > 1 else "") for lab, n in collections.Counter(labels).items()]

    lines = []
    for module, d in delta["modules"].items():
        parts = counted("+", d["added"]) + counted("-", d["removed"])
        if d["structure"]:
            parts.append("same properties, different order or branching")
        lines.append(f"{module}: " + "; ".join(parts))
    return lines
