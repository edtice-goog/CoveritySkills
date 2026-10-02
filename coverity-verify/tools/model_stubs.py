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
    """'struct rec *lookup(int, const char *);' -> (ret, name, [param types]).
    A trailing '...' is dropped from the list and reported by is_variadic()."""
    m = re.match(r"^\s*(.*?)\b(\w+)\s*\((.*)\)\s*;\s*$", proto.strip())
    ret, name, params = m.group(1).strip(), m.group(2), m.group(3).strip()
    plist = [] if params in ("", "void") else [p.strip() for p in split_params(params)]
    plist = [p for p in plist if p != "..."]
    return ret, name, plist


def split_params(params):
    """Split a parameter list at top-level commas only: a function-pointer
    parameter `void (*)(const void *, void *)` carries commas of its own."""
    out, depth, cur = [], 0, []
    for ch in params:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def declare(t, a):
    """`T a` for an ordinary type, `R (*a)(...)` for a function-pointer type."""
    t = t.strip()
    if "(*)" in t:
        return t.replace("(*)", "(*%s)" % a, 1)
    return "%s %s" % (t, a)


def is_variadic(proto):
    return re.search(r",\s*\.\.\.\s*\)", proto) is not None


def behaviour(path):
    """One root-to-final path of the automaton, as what the stub must do.
    Scalar returns are constrained too: `<return value> <- == K` pins the
    value, `<- != K` / `<- < K` / `<- > K` bound it, `negative_return` /
    `zero_return` name the class; a stub that returns any byte where the
    model says -1 or 0 would give the fuzzer behaviours the analyzer never
    granted the callee."""
    b = {"null": False, "nonnull": False, "identity": None, "alloc": False,
         "deref": set(), "writes": [], "pre": [], "ret_eq": None, "ret_ne": [],
         "ret_lt": None, "ret_gt": None, "negative": False, "zero": False}
    for lab in path:
        if lab.startswith("returnsnull") or lab == "<return value> <- == 0":
            b["null"] = True
            b["zero"] = True
        elif lab == "<return value> <- != 0":
            b["nonnull"] = True
            b["ret_ne"].append(0)
        elif lab.startswith("identity(<arg "):
            b["identity"] = int(re.search(r"<arg (\d+)>", lab).group(1))
        elif lab.startswith("afm_alloc("):
            b["alloc"] = True
        elif lab.startswith("dereference(<arg "):
            b["deref"].add(int(re.search(r"<arg (\d+)>", lab).group(1)))
        elif lab.startswith("write("):
            # only writes the model marks as storing a non-null pointer are
            # reproducible without knowing the field's type
            if "write_notnull -> true" in lab:
                b["writes"].append(lab.split(":")[0][len("write("):-1])
        elif re.match(r"^<arg \d+>(->\w+)? (!=|==|>|<) ", lab):
            b["pre"].append(lab)
        elif lab.startswith("negative_return("):
            b["negative"] = True
        elif lab.startswith("zero_return("):
            b["zero"] = True
        else:
            m = re.match(r"^<return value> <- (==|!=|<|>) (-?\d+)$", lab)
            if m:
                op, k = m.group(1), int(m.group(2))
                if op == "==":
                    b["ret_eq"] = k
                elif op == "!=":
                    b["ret_ne"].append(k)
                elif op == "<":
                    b["ret_lt"] = k if b["ret_lt"] is None else min(b["ret_lt"], k)
                else:
                    b["ret_gt"] = k if b["ret_gt"] is None else max(b["ret_gt"], k)
    return b


def scalar_return(b, ret):
    """The C expression a scalar-returning stub returns for behaviour b."""
    if b["ret_eq"] is not None:
        return "return (%s)%d;   /* model: <return value> <- == %d */" % (ret, b["ret_eq"], b["ret_eq"])
    if b["ret_lt"] is not None and b["ret_gt"] is not None:
        lo, hi = b["ret_gt"] + 1, b["ret_lt"] - 1
        return ("return (%s)(%d + __stub_choice(%d));   /* model: %d < v < %d */"
                % (ret, lo, max(1, hi - lo + 1), b["ret_gt"], b["ret_lt"]))
    if b["ret_lt"] is not None:
        return "return (%s)(%d - 1 - __stub_choice(0));   /* model: <return value> <- < %d */" % (ret, b["ret_lt"], b["ret_lt"])
    if b["ret_gt"] is not None:
        return "return (%s)(%d + 1 + __stub_choice(0));   /* model: <return value> <- > %d */" % (ret, b["ret_gt"], b["ret_gt"])
    if b["negative"]:
        return "return (%s)-1;   /* model: negative_return */" % ret
    if b["zero"]:
        return "return (%s)0;   /* model: zero_return */" % ret
    if b["ret_ne"]:
        ne = sorted(set(b["ret_ne"]))
        return ("return (%s)(__stub_choice(0) %s);   /* model: <return value> <- != %s */"
                % (ret, " ".join("== %d ? %d :" % (k, k + 1) for k in ne) + " __stub_choice(0)",
                   ",".join(str(k) for k in ne))).replace(":  __stub_choice", ": __stub_choice")
    return "return (%s)__stub_choice(0);   /* model: value unconstrained */" % ret


def stub(proto, dot):
    ret, name, plist = parse_prototype(proto)
    edges, finals = parse_dot(dot)
    behs = []
    seen = set()
    for p in paths(edges, finals):
        b = behaviour(p)
        key = (b["null"], b["nonnull"], b["identity"], b["alloc"], tuple(sorted(b["deref"])),
               b["ret_eq"], tuple(sorted(set(b["ret_ne"]))), b["ret_lt"], b["ret_gt"], b["negative"], b["zero"])
        if key in seen:
            continue
        seen.add(key)
        behs.append(b)
    args = ["a%d" % i for i in range(len(plist))]
    params = ", ".join(declare(t, a) for t, a in zip(plist, args))
    if is_variadic(proto):
        params = (params + ", ...") if params else "..."
    sig = "%s %s(%s)" % (ret, name, params or "void")
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
    # one body per behaviour; behaviours that come out identical (they differed
    # only in preconditions the stub cannot act on) are folded, so the choice
    # index the trace reports is one of genuinely distinct behaviours
    bodies = []
    for b in behs:
        body = []
        # write(<arg N>->f) / write(global): the model says the callee stores
        # into it; write_notnull says the stored value is a non-null pointer.
        # Store a pointer to a valid object there, so a caller that relies on
        # the callee having filled a global or an out-parameter sees it filled
        # (delay_shutdown_ev relies on delay_table_load writing delay_tab.dt_data).
        for w in b["writes"]:
            target = w
            for i, an in enumerate(args):
                target = target.replace("<arg %d>" % i, an)
            if "<" in target or ">" in target and "->" not in target:
                continue                          # a form the stub cannot spell
            body.append("*(void **)&(%s) = __stub_object(64);   /* model: write(%s) */" % (target, w))
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
            body.append(scalar_return(b, ret))
        else:
            body.append("return;")
        if body not in bodies:
            bodies.append(body)
    out[0] = "/* stub for %s, from its derived generic model: %d behaviour(s) */" % (name, len(bodies))
    # ONE choice per call, then a chain: a fresh __stub_choice() in every `if`
    # would consume a byte per branch and could take none of them
    out.append("  int __k = __stub_choice(%d);" % len(bodies))
    for k, body in enumerate(bodies):
        cond = ("if" if k == 0 else "else if") + " (__k == %d)" % k if k < len(bodies) - 1 else "else"
        if len(bodies) == 1:
            cond = ""
        out.append(("  %s {" % cond) if cond else "  {")
        out += ["    " + l for l in body]
        out.append("  }")
    out.append("}")
    return "\n".join(out)


if __name__ == "__main__":
    print(stub(sys.argv[1], sys.argv[2]))
