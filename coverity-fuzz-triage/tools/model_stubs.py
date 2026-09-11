"""A C stub for one callee, generated from its Coverity derived model (.dot).

    cov-find-function --dir <idir> --save -of models --module generic <callee>
    python model_stubs.py '<prototype line from the slice>' models/<key>.generic.dot

Appended to a slice, the stub gives the callee exactly the behaviours the
analyzer believes it has, selected per call by __stub_choice(n) -- which a
libFuzzer harness feeds from the input (see evals/harness.c),
so the fuzzer explores the callee behaviours as well as the arguments.
See references/fuzz-confirmation.md.

The model is an automaton whose edge labels are the behaviours the analyzer
believes the callee has. Each root-to-final path is one behaviour set; the
stub picks one per call with __stub_choice() (fuzz-driven later) and does
exactly what the labels say: return NULL, return a non-null value (an
argument when the model says identity(<arg N>), a fresh allocation when it
says afm_alloc(<return value>), otherwise a static object), touch every
dereferenced argument, write every written output.
"""
import re
import sys


def parse_dot(path):
    edges = {}
    finals = set()
    for line in open(path, encoding="utf-8"):
        m = re.match(r'\s*(\d+) -> (\d+) \[label="(.*)"\];', line)
        if m:
            edges.setdefault(int(m.group(1)), []).append((int(m.group(2)), m.group(3)))
            continue
        m = re.match(r'\s*(\d+) \[label=\d+,style=filled\];', line)
        if m:
            finals.add(int(m.group(1)))
    return edges, finals


def paths(edges, finals, node=0, acc=None, seen=None):
    acc = acc or []
    seen = seen or set()
    if node in finals and not edges.get(node):
        yield list(acc)
        return
    for nxt, label in edges.get(node, []):
        if (node, nxt) in seen:
            continue
        yield from paths(edges, finals, nxt, acc + [label], seen | {(node, nxt)})
    if node in finals and edges.get(node):
        yield list(acc)


def parse_prototype(proto):
    """'struct rec *lookup(int, const char *);' -> (ret, name, [param types])"""
    m = re.match(r"^\s*(.*?)\b(\w+)\s*\((.*)\)\s*;\s*$", proto.strip())
    ret, name, params = m.group(1).strip(), m.group(2), m.group(3).strip()
    plist = [] if params in ("", "void") else [p.strip() for p in params.split(",")]
    return ret, name, plist


def behaviour(path):
    b = {"null": False, "nonnull": False, "identity": None, "alloc": False,
         "deref": set(), "writes": [], "pre": []}
    for lab in path:
        if lab.startswith("returnsnull") or lab == "<return value> <- == 0":
            b["null"] = True
        elif lab == "<return value> <- != 0":
            b["nonnull"] = True
        elif lab.startswith("identity(<arg "):
            b["identity"] = int(re.search(r"<arg (\d+)>", lab).group(1))
        elif lab.startswith("afm_alloc(<return value>)"):
            b["alloc"] = True
        elif lab.startswith("dereference(<arg "):
            b["deref"].add(int(re.search(r"<arg (\d+)>", lab).group(1)))
        elif lab.startswith("write("):
            b["writes"].append(lab.split(":")[0][len("write("):-1])
        elif re.match(r"^<arg \d+>(->\w+)? (!=|==|>|<) ", lab):
            b["pre"].append(lab)
    return b


def stub(proto, dot):
    ret, name, plist = parse_prototype(proto)
    edges, finals = parse_dot(dot)
    behs = []
    seen = set()
    for p in paths(edges, finals):
        b = behaviour(p)
        key = (b["null"], b["nonnull"], b["identity"], b["alloc"], tuple(sorted(b["deref"])))
        if key in seen:
            continue
        seen.add(key)
        behs.append(b)
    args = ["a%d" % i for i in range(len(plist))]
    sig = "%s %s(%s)" % (ret, name, ", ".join("%s %s" % (t, a) for t, a in zip(plist, args)) or "void")
    is_ptr = ret.rstrip().endswith("*")
    pointee = ret.rstrip()[:-1].strip() if is_ptr else None
    out = ["/* stub for %s, from its derived generic model: %d behaviour(s) */" % (name, len(behs)), sig + " {"]
    touch = set()
    for b in behs:
        touch |= b["deref"]
    for i in sorted(touch):
        if i < len(plist) and plist[i].rstrip().endswith("*"):
            # unconditional on purpose: the model says the callee dereferences it,
            # so the stub must too -- for the analyzer (a null here is the defect)
            # and for a fuzzer (a null here is the crash that confirms it)
            out.append("  { volatile char __t = *(volatile char *)%s; (void)__t; }   /* model: dereference(<arg %d>) */" % (args[i], i))
    for k, b in enumerate(behs):
        cond = "if (__stub_choice(%d) == %d)" % (len(behs), k) if k < len(behs) - 1 else "else"
        if k == 0:
            cond = "if (__stub_choice(%d) == 0)" % len(behs)
        body = []
        if b["null"] and is_ptr:
            body.append("return 0;   /* model: returnsnull */")
        elif is_ptr:
            if b["identity"] is not None and b["identity"] < len(plist):
                body.append("return (%s)%s;   /* model: identity(<arg %d>) */" % (ret, args[b["identity"]], b["identity"]))
            elif b["alloc"]:
                body.append("return (%s)__stub_alloc(64);   /* model: afm_alloc(<return value>) */" % ret)
            else:
                body.append("return (%s)__stub_object(64);   /* model: non-null return */" % ret)
        elif ret.strip() != "void":
            body.append("return (%s)__stub_choice(0);   /* model: value unconstrained */" % ret)
        else:
            body.append("return;")
        out.append("  %s {" % cond)
        out += ["    " + l for l in body]
        out.append("  }")
    out.append("}")
    return "\n".join(out)


if __name__ == "__main__":
    print(stub(sys.argv[1], sys.argv[2]))
