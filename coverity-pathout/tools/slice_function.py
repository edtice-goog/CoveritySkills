#!/usr/bin/env python3
"""Cut one function out of a Coverity intermediate directory as a file that
compiles on its own -- the function body plus every typedef, struct, enum,
global and callee prototype it needs -- so it can be re-emitted and
re-analyzed in seconds while you change it.

    slice_function.py --dir <idir> --bin <install>/bin --tu <N> --name <fn> \
        [--out <dir>] [--emit] [--analyze] [--obfuscate]

Everything comes from the emit's own AST via `cov-manage-emit find`:

    --print-definitions   the function body, pretty-printed (macros expanded)
    --print-debug         the function's tree: every callee's prototype, every
                          global's type, every typedef's target, every struct
                          it touches -- and, for the structs, their fields

No preprocessed text is read. The declarations are printed back into C from
the tree, in dependency order, and the body is appended verbatim.

--emit re-runs cov-emit on the slice with the flags recorded for the original
translation unit (include paths and -D dropped: there is nothing left to
include). --analyze then runs cov-analyze --print-paths on that one-file idir
and reports the function's path count and any 'Pathed out' checkers.

--obfuscate also writes <fn>.obf.c: project identifiers renamed by kind,
string literals masked to same-length placeholders, comments dropped,
library names and all constants kept; with --analyze both files are
analyzed and compared, so the twin is proven to analyze like the original
before it leaves. The rename map (<fn>.obf.map.json) stays local.

Scope: C. C++ bodies extract fine, but classes with methods, templates and
namespaces are not reconstructed; for C++ use the preprocessed TU instead
(see references/standalone-reproducer.md).

Pure standard library.
"""

import argparse
import os
import re
import subprocess
import sys

# ==========================================================================
# cov-manage-emit

def manage_emit(bin_dir, idir, args):
    exe = os.path.join(bin_dir, "cov-manage-emit")
    if os.name == "nt" and os.path.exists(exe + ".exe"):
        exe += ".exe"
    cmd = [exe, "--dir", idir, "--ticker-mode", "none"] + args
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if "Version mismatch" in p.stdout or "Version mismatch" in p.stderr:
        sys.exit("cov-manage-emit: version mismatch -- use the installation named in "
                 "<idir>/emit/version:\n" + (p.stdout + p.stderr).strip())
    return p.stdout


def find_regex(name):
    """Anchored regex for a symbol name as cov-manage-emit find expects it."""
    return "^" + re.escape(name) + "$"


# ==========================================================================
# --print-debug tree parser
#
#   key = Tag:            node, children indented deeper
#   key = {               list, entries indented deeper, closed by '}'
#   key = value           scalar
#   dflags = {static}     inline set, scalar

class Node:
    __slots__ = ("tag", "items")

    def __init__(self, tag):
        self.tag = tag
        self.items = []          # list of (key, value); value: str | Node | list

    def get(self, key, default=None):
        for k, v in self.items:
            if k == key:
                return v
        return default

    def __repr__(self):
        return "Node(%s)" % self.tag


RE_LINE = re.compile(r"^(\s*)(\S[^=]*?) = (.*)$")


def parse_debug(text):
    """Parse one --print-debug output (possibly several matches) into a list
    of (header_lines, root Node)."""
    lines = [l.rstrip("\r\n") for l in text.splitlines()]
    roots = []
    i = 0
    n = len(lines)
    header = []

    def parse_block(indent):
        """Parse consecutive entries whose indentation == indent. Returns items."""
        nonlocal i
        items = []
        while i < n:
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            stripped = line.lstrip(" ")
            ind = len(line) - len(stripped)
            if ind < indent:
                return items
            if ind > indent:
                # stray deeper line (should not happen); skip
                i += 1
                continue
            if stripped == "}":
                return items
            m = RE_LINE.match(line)
            if not m:
                i += 1
                continue
            key, val = m.group(2), m.group(3)
            i += 1
            if val == "{":
                sub = parse_block(ind + 2)
                # consume closing brace
                while i < n and lines[i].strip() != "}":
                    if lines[i].strip():
                        break
                    i += 1
                if i < n and lines[i].strip() == "}":
                    i += 1
                items.append((key, sub))
            elif val.endswith(":") and re.match(r"^[A-Za-z_][A-Za-z_0-9]*:$", val):
                node = Node(val[:-1])
                node.items = parse_block(ind + 2)
                items.append((key, node))
            else:
                items.append((key, val))
        return items

    while i < n:
        line = lines[i]
        if line.startswith("/*") or line.startswith(" *"):
            header.append(line)
            i += 1
            continue
        if not line.strip():
            i += 1
            continue
        m = RE_LINE.match(line)
        if m and (len(line) - len(line.lstrip(" "))) == 0:
            items = parse_block(0)
            root = Node("__root__")
            root.items = items
            roots.append((header, root))
            header = []
        else:
            i += 1
    return roots


RE_LOC = re.compile(r"^(.*?):\d+:\d+-")


def declared_at(header_lines):
    """The file named on the `declared at:` line of a find header comment."""
    for i, l in enumerate(header_lines):
        if "declared at:" in l and i + 1 < len(header_lines):
            m = RE_LOC.match(header_lines[i + 1].lstrip(" *"))
            if m:
                return m.group(1)
    return None


def walk(value, fn, path=()):
    """Depth-first over every Node reachable from value."""
    if isinstance(value, Node):
        fn(value, path)
        for k, v in value.items:
            walk(v, fn, path + (value.tag, k))
    elif isinstance(value, list):
        for k, v in value:
            walk(v, fn, path)


# ==========================================================================
# names

def is_anonymous(name):
    # _Z$Uu9session_t_ (unnamed struct behind a typedef), _Z$Ua8_ISupper_
    # (unnamed enum), _ZN12json_node_st$Ua5bool__E (unnamed member union)
    return name.startswith("_Z$") or "$U" in name


NESTED_RE = re.compile(r"^_ZN((?:\d+[A-Za-z_]\w*)+)E$")


def nested_components(name):
    """`_ZN21PacketCollectorThread9DIRECTIONE` -> ('PacketCollectorThread',
    'DIRECTION'), for a type or enumerator declared inside a class. Those
    nodes carry only this Itanium nested name -- there is no `id` on a type
    node to fall back on -- and the thing has to be declared inside its class
    and referenced through it. Returns None for anything else, including a
    function-local `_ZZ...` name and an anonymous `$U` one.
    """
    m = NESTED_RE.match(name or "")
    if not m or is_anonymous(name):
        return None
    return _itanium_parts(m.group(1), least=2)


def _itanium_parts(rest, least=1):
    parts = []
    while rest:
        m = re.match(r"^(\d+)(.*)$", rest)
        if not m:
            return None
        n, tail = int(m.group(1)), m.group(2)
        if len(tail) < n:
            return None
        parts.append(tail[:n])
        rest = tail[n:]
    return tuple(parts) if len(parts) >= least else None


def source_spelling(name):
    """The source-level identifier behind a mangled name:
    `_Z15SipSgSendSipPdujt...` -> 'SipSgSendSipPdu', `_ZN4demo6Widget1fEi` ->
    'f'. A C name is not mangled and comes back unchanged.

    The emit keys a function by its linker name, but the pretty-printed body
    and the prototypes spell it the way the source did, so anything matching
    text against a function name needs this.
    """
    if not name or not name.startswith("_Z"):
        return name
    m = re.match(r"^_Z(\d+)(.*)$", name)
    if m and len(m.group(2)) >= int(m.group(1)):
        return m.group(2)[:int(m.group(1))]
    m = re.match(r"^_ZN(.*?)E", name)
    if m:
        parts = _itanium_parts(m.group(1))
        if parts:
            return parts[-1]
    return name


class Names:
    """Maps emit-side type names to the tags used in the slice."""

    def __init__(self, function_name=None):
        self.tags = {}
        self.n = 0
        self.function_name = function_name
        self.local_tags = []      # (qualified name, tag) for types local to the function

    def _local_of(self, name):
        """A type declared inside the function is named either `fn::tag` or,
        Itanium-style, `_ZZ<len>fnE<len>tag`. Return `tag` if it is local to
        our function, else None."""
        fn = self.function_name
        if name.startswith(fn + "::"):
            return name[len(fn) + 2:]
        m = re.match(r"^_ZZ(\d+)(.*)$", name)
        if m:
            n = int(m.group(1))
            rest = m.group(2)
            if rest[:n] == fn and rest[n:n + 1] == "E":
                m2 = re.match(r"^(\d+)(.*)$", rest[n + 1:])
                if m2:
                    k = int(m2.group(1))
                    return m2.group(2)[:k]
        return None

    def tag(self, name, kind="s"):
        if name in self.tags:
            return self.tags[name]
        if is_anonymous(name):
            self.n += 1
            t = "__cov_anon_%s%d" % (kind, self.n)
        elif self.function_name and self._local_of(name):
            # a struct/enum declared inside the function: hoist it to file scope
            # under its own tag; the body is rewritten to match (see rewrite_body)
            local = self._local_of(name)
            t = re.sub(r"[^A-Za-z0-9_]", "_", local)
            self.local_tags.append(("%s::%s" % (self.function_name, local), t))
        elif nested_components(name):
            # A nested type is spelled through its class everywhere it is
            # referenced; the definition itself uses the bare last component
            # and is emitted inside the class (see render_class).
            t = "::".join(nested_components(name))
        else:
            t = re.sub(r"[^A-Za-z0-9_]", "_", name.replace("::", "__"))
        self.tags[name] = t
        return t


# ==========================================================================
# C type printer (specifier + declarator, inside out)

class Printer:
    def __init__(self, names, complete_classes, enums, cxx=False):
        self.names = names
        self.complete = complete_classes
        self.enums = enums
        self.cxx = cxx

    def scalar(self, kind):
        if kind == "bool" and not self.cxx:
            return "_Bool"
        return kind

    def class_spec(self, node):
        key = node.get("classKey", "struct")
        if key == "class" and not self.cxx:
            key = "struct"
        return "%s %s" % (key, self.names.tag(node.get("name", "?"), "s"))

    def enum_spec(self, node):
        return "enum %s" % self.names.tag(node.get("name", "?"), "e")

    def decl(self, t, inner=""):
        """Declaration text of type t with declarator inner ('' for abstract)."""
        return self._build(t, inner).strip()

    def _build(self, t, inner):
        tag = t.tag if isinstance(t, Node) else None
        if tag == "scalar_type_t":
            return self.scalar(t.get("kind", "int")) + " " + inner
        if tag in ("class_type_t", "internal_defined_class_type_t"):
            return self.class_spec(t) + " " + inner
        if tag in ("enum_type_t", "internal_defined_enum_type_t"):
            return self.enum_spec(t) + " " + inner
        if tag == "typedef_type_t":
            nm = t.get("name", "?")
            # a nested type is referenced through its class, never by the
            # Itanium name the node carries
            parts = nested_components(nm)
            return ("::".join(parts) if parts else nm) + " " + inner
        if tag == "cv_wrapper_type_t":
            flags = (t.get("flags", "") or "").strip()
            target = t.get("target")
            if isinstance(target, Node) and target.tag == "pointer_type_t":
                # T *const inner
                return self._build(target.get("pointed_to"), "*" + flags + " " + inner
                                   if flags else "*" + inner)
            return flags + " " + self._build(target, inner) if flags else self._build(target, inner)
        if tag == "pointer_type_t":
            pointed = t.get("pointed_to")
            ptag = pointed.tag if isinstance(pointed, Node) else None
            inner2 = "*" + inner
            if ptag in ("array_type_t", "function_type_t"):
                inner2 = "(" + inner2 + ")"
            return self._build(pointed, inner2)
        if tag == "reference_type_t":
            pointed = t.get("pointed_to") or t.get("target")
            return self._build(pointed, "&" + inner)
        if tag == "array_type_t":
            count = t.get("element_count")
            # A flexible array member (`ULONG startOfPdu[];`) carries the
            # literal string "<unset>" as its element count, which is not a
            # sentinel the list below caught -- it went through as the bound
            # and `[<unset>]` is not an expression.
            dim = "[%s]" % count if count not in (None, "", "-1", "unknown", "<unset>") else "[]"
            if inner.startswith("*"):
                inner = "(" + inner + ")"
            return self._build(t.get("element_type"), inner + dim)
        if tag == "function_type_t":
            params = []
            for k, p in (t.get("parameters") or []):
                params.append(self.decl(p))
            if t.get("has_C_ellipsis") == "true":
                params.append("...")
            if not params and t.get("prototyped", "true") == "true":
                params = ["void"]
            return self._build(t.get("return"), inner + "(" + ", ".join(params) + ")")
        # unknown -- keep compiling
        return "int /* %s */ %s" % (tag, inner)


# ==========================================================================
# collection

class Slice:
    def __init__(self, bin_dir, idir, tu, name, cxx):
        self.bin = bin_dir
        self.idir = idir
        self.tu = tu
        self.name = name
        self.cxx = cxx
        self.typedefs = {}       # name -> typedef_type_t node (with target)
        self.classes = {}        # name -> classKey
        self.complete = set()    # class names that need a full definition
        self.class_defs = {}     # name -> internal_defined_class_type_t node
        self.enums = {}          # name -> internal_defined_enum_type_t node or None
        self.globals = {}        # name -> global_variable_t node
        self.functions = {}      # name -> function_t node
        self.names = Names(name)
        self.inlined = set()     # anonymous member types defined in place, not at file scope
        self.decl_loc = {}       # (kind, name) -> declaring file, for the obfuscator
        self.defined = {}        # (kind, name) -> has a definition in the emit
        self.locals = []         # local variable names, in tree order
        self.params = []         # parameter names, in tree order
        self.notes = []

    # ---- walking a tree -------------------------------------------------
    def collect(self, root):
        def visit(node, path):
            tag = node.tag
            if tag == "typedef_type_t":
                nm = node.get("name")
                if nm and nm not in self.typedefs and isinstance(node.get("target"), Node):
                    self.typedefs[nm] = node
            elif tag in ("class_type_t", "internal_defined_class_type_t"):
                nm = node.get("name")
                if nm:
                    self.classes.setdefault(nm, node.get("classKey", "struct"))
                    # complete unless we got here through a pointer
                    if not self._under_pointer(path):
                        self.complete.add(nm)
            elif tag in ("enum_type_t", "internal_defined_enum_type_t"):
                nm = node.get("name")
                if nm:
                    self.enums.setdefault(nm, None)
            elif tag == "enumerator_t":
                e = node.get("enum")
                if isinstance(e, Node) and e.get("name"):
                    self.enums.setdefault(e.get("name"), None)
            elif tag == "global_variable_t":
                nm = node.get("name")
                if nm and isinstance(node.get("type"), Node):
                    self.globals.setdefault(nm, node)
            elif tag == "function_t":
                nm = node.get("name")
                if nm and nm != self.name and isinstance(node.get("type"), Node):
                    self.functions.setdefault(nm, node)
            elif tag == "field_t":
                mc = node.get("memberOfClass")
                if isinstance(mc, Node) and mc.get("name"):
                    self.classes.setdefault(mc.get("name"), mc.get("classKey", "struct"))
                    self.complete.add(mc.get("name"))
            elif tag == "local_variable_t":
                nm = node.get("name")
                if nm and nm not in self.locals:
                    self.locals.append(nm)
            elif tag == "parameter_t":
                nm = node.get("name")
                if nm and nm not in self.params:
                    self.params.append(nm)
            elif tag == "Function":
                # `formals` names every parameter, including ones the body never
                # uses (which never appear as parameter_t nodes)
                for k, v in (node.get("formals") or []):
                    if isinstance(v, str) and v and v not in self.params:
                        self.params.append(v)
        walk(root, visit)

    @staticmethod
    def _under_pointer(path):
        # path is a tuple of (tag, key) pairs flattened: tag, key, tag, key ...
        tags = path[0::2]
        return "pointer_type_t" in tags or "reference_type_t" in tags

    # ---- closure over struct definitions --------------------------------
    def close(self):
        done = set()
        while True:
            todo = [c for c in self.complete if c not in done]
            if not todo:
                break
            for c in todo:
                done.add(c)
                node = self.fetch_class(c)
                if node is None:
                    self.notes.append("no definition found for %s -- forward-declared only" % c)
                    continue
                self.class_defs[c] = node
                # walk field types, marking by-value classes complete
                for k, f in (node.get("fields") or []):
                    self.collect(f)
        for e in list(self.enums):
            if self.enums[e] is None:
                self.enums[e] = self.fetch_enum(e)

    def fetch_class(self, name):
        out = manage_emit(self.bin, self.idir, ["find", find_regex(name), "--kind", "c", "--print-debug"])
        for header, root in parse_debug(out):
            cls = root.get("class")
            if isinstance(cls, Node) and cls.get("name") == name:
                self.decl_loc.setdefault(("class", name), declared_at(header))
                if cls.get("fields") is None:
                    continue
                return cls
        return None

    def fetch_enum(self, name):
        out = manage_emit(self.bin, self.idir, ["find", find_regex(name), "--kind", "e", "--print-debug"])
        for header, root in parse_debug(out):
            en = root.get("enum")
            if isinstance(en, Node) and en.get("name") == name:
                self.decl_loc.setdefault(("enum", name), declared_at(header))
                return en
        return None

    def lookup_loc(self, kind, name, flag):
        """Declaration file of a symbol via a plain `find`; None if the emit
        does not index it (library functions, for instance)."""
        key = (kind, name)
        if key in self.decl_loc:
            return self.decl_loc[key]
        out = manage_emit(self.bin, self.idir, ["find", find_regex(name), "--kind", flag])
        loc = None
        defined = False
        for line in out.splitlines():
            line = line.strip()
            if loc is None and RE_LOC.match(line):
                loc = RE_LOC.match(line).group(1)
            if line.startswith("defined in TU"):
                defined = True
        self.decl_loc[key] = loc
        self.defined[key] = defined
        return loc

    # ---- dependency order -------------------------------------------------
    def deps(self, t, under_ptr, acc):
        if not isinstance(t, Node):
            return
        tag = t.tag
        if tag == "typedef_type_t":
            acc.add(("typedef", t.get("name")))
            # a by-value use of a typedef also needs whatever the typedef names
            # to be complete (struct session { pr_netaddr_t data_addr; })
            if not under_ptr:
                td = self.typedefs.get(t.get("name"))
                if td is not None and td is not t:
                    self.deps(td.get("target"), False, acc)
                elif isinstance(t.get("target"), Node):
                    self.deps(t.get("target"), False, acc)
        elif tag in ("class_type_t", "internal_defined_class_type_t"):
            nm = t.get("name")
            if not under_ptr and nm in self.class_defs:
                acc.add(("class", nm))
        elif tag == "cv_wrapper_type_t":
            self.deps(t.get("target"), under_ptr, acc)
        elif tag in ("pointer_type_t", "reference_type_t"):
            self.deps(t.get("pointed_to") or t.get("target"), True, acc)
        elif tag == "array_type_t":
            self.deps(t.get("element_type"), under_ptr, acc)
        elif tag == "function_type_t":
            self.deps(t.get("return"), True, acc)
            for k, p in (t.get("parameters") or []):
                self.deps(p, True, acc)

    def ordered_decls(self):
        items = {}
        for nm, td in self.typedefs.items():
            if nm.startswith("__builtin_"):
                continue
            acc = set()
            target = td.get("target")
            # `typedef struct X Y;` needs only the forward declaration of X --
            # and X's own fields may use Y (struct config_struc { config_rec
            # *parent; }), so treating it as a hard dependency would be a cycle
            direct = target
            while isinstance(direct, Node) and direct.tag == "cv_wrapper_type_t":
                direct = direct.get("target")
            soft = isinstance(direct, Node) and direct.tag in (
                "class_type_t", "internal_defined_class_type_t", "enum_type_t", "internal_defined_enum_type_t")
            self.deps(target, soft, acc)
            items[("typedef", nm)] = acc
        for nm, cls in self.class_defs.items():
            acc = set()
            for k, f in (cls.get("fields") or []):
                self.deps(f.get("type"), False, acc)
            # a member declaration moved into this class body brings its own
            # dependencies with it, and they are not reachable through fields
            for ft in (getattr(self, "member_dep_types", {}).get(nm) or []):
                self.deps(ft, True, acc)
            items[("class", nm)] = acc
        # topological sort, stable by name; cycles broken in name order
        order = []
        state = {}

        def visit(it):
            st = state.get(it)
            if st == 2:
                return
            if st == 1:
                return  # cycle; emit in whatever order we are in
            state[it] = 1
            for d in sorted(items.get(it, ())):
                if d in items and d != it:
                    visit(d)
            state[it] = 2
            order.append(it)

        for it in sorted(items):
            visit(it)
        return order

    # ---- printing -----------------------------------------------------------
    def render(self, body_text, provenance, obf=None):
        self.obf = obf
        P = Printer(self.names, self.class_defs, self.enums, self.cxx)
        out = []
        out.append("/* Standalone slice of %s, generated by slice_function.py from the AST in\n"
                   " * %s (TU %s).\n"
                   " * Declarations were printed back from the emit; the body is the analyzer's\n"
                   " * own pretty-print (macros expanded). Anonymous types carry synthetic tags.\n"
                   " */" % (self.name, provenance, self.tu))
        # the pretty-printer keeps NULL and the va_* family in macro form;
        # nothing else survives as a macro
        out.append("\n#ifndef NULL\n#define NULL %s\n#endif\n"
                   "#define va_start(ap, last) __builtin_va_start(ap, last)\n"
                   "#define va_arg(ap, type) __builtin_va_arg(ap, type)\n"
                   "#define va_end(ap) __builtin_va_end(ap)\n"
                   "#define va_copy(dst, src) __builtin_va_copy(dst, src)"
                   % ("0" if self.cxx else "((void *)0)"))
        # C++ members. A nested enum and a static member function are only
        # declarable inside their class, so partition them out before anything
        # is rendered: render_class puts them back in the class body.
        self.nested_members = {}      # class name -> [declaration text]
        self.member_dep_types = {}    # class name -> [function_type_t]
        self.diverted = set()         # function keys handled as members
        for nm in sorted(self.functions):
            f = self.functions[nm]
            ft = f.get("type")
            mc = f.get("memberOfClass")
            if not isinstance(ft, Node) or ft.tag != "function_type_t":
                continue
            # A non-static method is left alone: its function_type_t may or may
            # not carry the implicit `this`, and the body reaches it through an
            # object rather than through the class.
            if not isinstance(mc, Node) or ft.get("is_method") == "true":
                continue
            if mc.get("name") not in self.class_defs:
                continue
            d = P.decl(ft, f.get("id") or nm)
            if "static" in (f.get("dflags") or ""):
                d = "static " + d
            self.nested_members.setdefault(mc.get("name"), []).append("%s;" % d)
            self.member_dep_types.setdefault(mc.get("name"), []).append(ft)
            self.diverted.add(nm)
        # forward declarations
        fwd = []
        for nm in sorted(self.classes):
            if nested_components(nm):
                continue      # a nested class cannot be forward-declared here
            key = self.classes[nm]
            if key == "class" and not self.cxx:
                key = "struct"
            fwd.append("%s %s;" % (key, self.names.tag(nm, "s")))
        if fwd:
            out.append("\n/* forward declarations */\n" + "\n".join(fwd))
        # enums
        en = []
        for nm in sorted(self.enums):
            node = self.enums[nm]
            parts = nested_components(nm)
            # inside its class the definition is spelled with the bare name
            spelling = parts[-1] if parts else self.names.tag(nm, "e")
            if node is None:
                text = "enum %s { __cov_%s_unknown };" % (spelling, re.sub(r"\W", "_", spelling))
                self.notes.append("enum %s: no definition found; emitted as a placeholder" % nm)
            else:
                vals = ["  %s = %s" % (e.get("id") or e.get("name"), e.get("value", "0"))
                        for k, e in (node.get("enumerators") or [])]
                text = "enum %s {\n%s\n};" % (spelling, ",\n".join(vals) if vals else "  __cov_empty")
            if parts:
                # nested enums come first in the class body: a member
                # declaration may use one as a parameter type.
                self.nested_members.setdefault(parts[0], []).insert(0, text)
            else:
                en.append(text)
        if en:
            out.append("\n/* enums */\n" + "\n".join(en))
        # typedefs and complete structs, in dependency order. Render the
        # structs first so that anonymous members are known (they are then
        # left out at file scope), then assemble in order.
        rendered = {}
        order = self.ordered_decls()
        for kind, nm in order:
            if kind == "class":
                rendered[nm] = self.render_class(P, self.class_defs[nm])
        decls = []
        for kind, nm in order:
            if kind == "typedef":
                if nested_components(nm):
                    # Coverity gives a nested enum a same-named typedef as well;
                    # `typedef enum C::E C::E;` is not a declaration, and the
                    # enum's own name already names the type in C++.
                    continue
                td = self.typedefs[nm]
                decls.append("typedef %s;" % P.decl(td.get("target"), nm))
            elif nm not in self.inlined:
                decls.append(rendered[nm])
        if decls:
            out.append("\n/* types */\n" + "\n".join(decls))
        # globals
        gl = []
        for nm in sorted(self.globals):
            g = self.globals[nm]
            if nm.startswith("__builtin_"):
                continue
            gl.append("extern %s;" % P.decl(g.get("type"), nm))
        if gl:
            out.append("\n/* globals (all extern, so their values stay unknown to the analysis) */\n" + "\n".join(gl))
        # prototypes
        pr = []
        for nm in sorted(self.functions):
            f = self.functions[nm]
            if nm.startswith("__builtin_"):
                continue
            ft = f.get("type")
            if not isinstance(ft, Node) or ft.tag != "function_type_t":
                continue
            if nm in self.diverted:
                continue          # declared inside its class instead
            mc = f.get("memberOfClass")
            if ft.get("is_method") == "true" or isinstance(mc, Node):
                self.notes.append(
                    "callee %s is a C++ %s of %s; not declared"
                    % (f.get("id") or nm,
                       "method" if ft.get("is_method") == "true" else "static member",
                       mc.get("name") if isinstance(mc, Node) else "?"))
                continue
            # `name` is the linker name -- for C++ the mangled one, which is not
            # what the body calls. `id` is the source spelling. Keying
            # self.functions on the mangled name already kept overloads apart,
            # so declaring each under its `id` re-creates the overload set.
            pr.append("%s;" % P.decl(ft, f.get("id") or nm))
        if pr:
            out.append("\n/* callees (prototypes only: the analysis sees them as unmodeled) */\n" + "\n".join(pr))
        out.append("\n/* the function */\n" + self.rewrite_body(body_text).rstrip() + "\n")
        return "\n".join(out)

    # A declaration whose declarator is missing: the token before `[` is a type
    # keyword or `*`/`&`, never an identifier, and a string literal initialises
    # it. `CHAR trunkGrpName[24];` and `static const char tag[4] = "ab";` both
    # end that run with an identifier, so neither matches.
    ANON_ARRAY_DECL = re.compile(
        r'^(?P<indent>[ \t]*)(?P<spec>[A-Za-z_][^;=\[\]]*?'
        r'(?:const|volatile|char|int|long|short|unsigned|signed|bool|double|float|wchar_t|\*|&))'
        r'[ \t]*\[(?P<dim>[^\]]*)\][ \t]*=[ \t]*(?P<init>"(?:[^"\\]|\\.)*")[ \t]*;[ \t]*$',
        re.M)

    def name_anonymous(self, body):
        """A compiler-generated static -- the string a logging macro builds out
        of `__func__` -- reaches the pretty-printer without a source name, so it
        prints as a declaration with no declarator
        (`static constexpr char const [16] = "SipSgSendSipPdu";`) and every use
        of it prints as `<anonymous>`. Neither is C++. Name the declaration and
        point the uses at it.
        """
        if "<anonymous>" not in body:
            return body
        named = []

        def name_decl(m):
            nm = "__cov_anon_%d" % len(named)
            named.append(nm)
            return "%s%s %s[%s] = %s;" % (m.group("indent"), m.group("spec").rstrip(),
                                          nm, m.group("dim"), m.group("init"))

        body = self.ANON_ARRAY_DECL.sub(name_decl, body)
        if len(named) == 1:
            body = body.replace("<anonymous>", named[0])
        else:
            # With two or more, a use cannot be tied to its declaration by
            # position alone; say so rather than guess.
            self.notes.append(
                "%d nameless declarations and %d `<anonymous>` uses left unresolved"
                % (len(named), body.count("<anonymous>")))
        return body

    @staticmethod
    def respell_header(body):
        """`--print-definitions` heads the body with a `/* ... */` block naming
        the function, and for C++ that name carries the mangled name in a
        `/*...*/` of its own. Block comments do not nest: the inner `*/` ends
        the header, and its remaining lines (` * declared at:` ...) reach the
        parser as code. Re-spell the header as line comments, which nest fine.
        """
        if not body.startswith("/*"):
            return body
        lines = body.split("\n")
        for end, ln in enumerate(lines):
            if ln.strip() == "*/":
                break
        else:
            return body
        head = ["// " + ln.strip().lstrip("*").strip()
                for ln in lines[1:end]]
        return "\n".join(head + lines[end + 1:])

    def rewrite_body(self, body):
        """Three constructs the pretty-printer emits that are not C:

        1. `struct fn::tag` for a struct declared inside the function, plus a
           bare `struct tag;` re-declaration in the body. The definition was
           hoisted to file scope under `tag`; qualify-strip the uses and drop
           the inner re-declaration (which would otherwise shadow the file-scope
           type with a new incomplete one).
        2. `TypeName({.member = value})` for a transparent-union argument
           (glibc's __SOCKADDR_ARG). C spells that `(TypeName){.member = value}`.
        3. NULL / va_arg: handled by the #defines at the top.
        """
        body = self.respell_header(body)
        body = self.name_anonymous(body)
        for qualified, tag in self.names.local_tags:
            body = re.sub(r"\b(struct|union|enum)\s+" + re.escape(qualified) + r"\b", r"\1 " + tag, body)
            body = re.sub(r"^\s*(struct|union|enum)\s+" + re.escape(tag) + r";\s*$\n?", "", body, flags=re.M)
        # TypeName({ ... }) -> (TypeName){ ... }
        out = []
        i = 0
        pat = re.compile(r"\b([A-Za-z_]\w*)\(\{")
        while True:
            m = pat.search(body, i)
            if not m:
                out.append(body[i:])
                break
            out.append(body[i:m.start()])
            depth = 0
            j = m.end() - 1          # at '{'
            k = j
            while k < len(body):
                if body[k] == "{":
                    depth += 1
                elif body[k] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            if k < len(body) and k + 1 < len(body) and body[k + 1] == ")":
                out.append("(%s)%s" % (m.group(1), body[j:k + 1]))
                i = k + 2
            else:
                out.append(body[m.start():m.end()])
                i = m.end()
        return "".join(out)

    def render_class(self, P, cls, indent="", tagless=False):
        key = cls.get("classKey", "struct")
        if key == "class" and not self.cxx:
            key = "struct"
        if tagless:
            lines = ["%s%s {" % (indent, key)]
        else:
            lines = ["%s%s %s {" % (indent, key, self.names.tag(cls.get("name"), "s"))]
        for k, f in (cls.get("fields") or []):
            fname = f.get("name") or ""
            if fname == "<anonymous>":
                fname = ""
            ftype = f.get("type")
            if isinstance(ftype, Node) and ftype.tag in ("class_type_t", "internal_defined_class_type_t") \
                    and is_anonymous(ftype.get("name", "")) and not fname:
                inner = self.class_defs.get(ftype.get("name"))
                if inner is not None:
                    # a C11 anonymous member: define it in place, without a tag.
                    # (A *named* field of unnamed type just references the
                    # synthetic tag defined at file scope.)
                    self.inlined.add(ftype.get("name"))
                    lines.append(self.render_class(P, inner, indent + "  ", tagless=True).rstrip(";") + ";")
                    continue
            width = f.get("bitfieldWidth") or f.get("bitWidth")
            if getattr(self, "obf", None) is not None:
                fname = self.obf.field_name(fname)
            d = P.decl(ftype, fname)
            if width:
                d += " : " + width
            lines.append("%s  %s;" % (indent, d))
        for text in (getattr(self, "nested_members", {}).get(cls.get("name")) or []):
            # `class` members default to private, and the body reaches these
            # through the class name.
            lines.append("%spublic:" % indent)
            lines += ["%s  %s" % (indent, ln) for ln in text.split("\n")]
        lines.append("%s};" % indent)
        return "\n".join(lines)


# ==========================================================================
# the recorded cov-emit command line

# flags whose value is the next token rather than attached with '='
VALUE_FLAGS = {"--dir", "--pre_preinclude", "--preinclude", "--gnu_version", "--microsoft_version",
               "--sys_include", "--ignore_path", "-I", "-D", "-U", "--clang_version",
               "--edg_version", "--config", "--comp_ver"}


def split_recorded_invocation(line):
    """print-compilation-info prints argv joined by single spaces, unquoted.
    A path containing spaces ("C:/Program Files/...") therefore arrives as
    several tokens. Re-join: a token that does not start with '-' belongs to
    the previous flag -- as its separate value if that flag takes one and has
    none yet, otherwise as a continuation of the previous token."""
    raw = line.split()
    # the trailing run of non-flag tokens holds the source file (and, if the
    # last flag takes a separate value, that value first)
    last_flag = max(i for i, t in enumerate(raw) if t.startswith("-") or i == 0)
    head, tail = raw[:last_flag + 1], raw[last_flag + 1:]
    toks = []
    expecting = False
    for i, t in enumerate(head):
        if i == 0:
            toks.append(t)
            continue
        if t.startswith("-"):
            toks.append(t)
            # a flag written without '=' takes the next token as its value
            # (--pre_preinclude X, --gnu_version N, --calling_convention_group L)
            expecting = "=" not in t
            continue
        if expecting:
            toks.append(t)
            expecting = False
            continue
        toks[-1] += " " + t
    if tail:
        if expecting and len(tail) > 1:
            toks.append(tail[0])
            tail = tail[1:]
        toks.append(" ".join(tail))
    return toks


def recorded_emit_flags(bin_dir, idir, tu):
    out = manage_emit(bin_dir, idir, ["--tu", str(tu), "print-compilation-info"])
    line = None
    for l in out.splitlines():
        if "cov-emit invocation:" in l:
            line = l.split("cov-emit invocation:", 1)[1].strip()
            break
    if not line:
        return None, None
    toks = split_recorded_invocation(line)
    exe = toks[0]
    src = toks[-1]
    flags = []
    sys_includes = []
    skip = False
    for i, t in enumerate(toks[1:-1]):
        if skip:
            skip = False
            continue
        if t == "--sys_include" and i + 2 < len(toks):
            sys_includes.append(toks[i + 2])
        if t.startswith("--sys_include="):
            sys_includes.append(t.split("=", 1)[1])
        if t in ("--dir", "--sys_include", "-I", "-D", "-U", "--ignore_path"):
            skip = True
            continue
        if t.startswith(("--dir=", "--ignore_path=", "--sys_include=", "-I", "-D", "-U")):
            continue
        flags.append(t)
    # WSL/Linux paths for files that live inside the idir -> local paths
    if os.name == "nt":
        mapped = []
        for t in flags:
            m = re.match(r"^/mnt/([a-z])/(.*)$", t)
            if m:
                cand = "%s:/%s" % (m.group(1).upper(), m.group(2))
                if os.path.exists(cand):
                    t = cand
            mapped.append(t)
        flags = mapped
    lang = "c++" if "--c++" in flags else "c"
    return flags, {"exe": exe, "source": src, "lang": lang, "sys_includes": sys_includes}


# ==========================================================================
# obfuscation: rename what the project defined, keep what the library defined,
# mask string literals, drop comments. Structure, constants and types' shapes
# are untouched, so the analyzer should not be able to tell the difference --
# and --analyze checks that it cannot.

C_KEYWORDS = set("""
auto break case char const continue default do double else enum extern float for goto if inline
int long register restrict return short signed sizeof static struct switch typedef union unsigned
void volatile while _Bool _Complex _Imaginary _Atomic _Alignas _Alignof _Generic _Noreturn
_Static_assert _Thread_local bool true false class namespace template typename this new delete
public private protected virtual operator using nullptr wchar_t char16_t char32_t
constexpr decltype noexcept static_assert thread_local explicit friend mutable export
const_cast dynamic_cast reinterpret_cast static_cast typeid throw try catch alignas alignof
""".split())

# standard / POSIX typedef names: recognisable to any reader and to library models
STD_TYPEDEFS = set("""
size_t ssize_t off_t off64_t time_t clock_t clockid_t timer_t uid_t gid_t pid_t mode_t dev_t ino_t
nlink_t socklen_t suseconds_t useconds_t va_list FILE DIR wchar_t wint_t ptrdiff_t intptr_t uintptr_t
intmax_t uintmax_t int8_t int16_t int32_t int64_t uint8_t uint16_t uint32_t uint64_t bool sig_atomic_t
fd_set sigset_t jmp_buf sigjmp_buf div_t ldiv_t locale_t blkcnt_t blksize_t fsblkcnt_t fsfilcnt_t
key_t id_t caddr_t u_char u_short u_int u_long quad_t u_quad_t sa_family_t in_addr_t in_port_t
regex_t regmatch_t pthread_t pthread_mutex_t pthread_cond_t pthread_attr_t pthread_key_t
DWORD WORD BYTE HANDLE BOOL LPVOID LPCSTR LPSTR SIZE_T ULONG LONG UINT INT CHAR WCHAR HRESULT
""".split())

RE_TOKEN = re.compile(r"""
    (?P<comment>/\*.*?\*/|//[^\n]*)
  | (?P<str>(?:L|u8|u|U)?"(?:\\.|[^"\\\n])*")
  | (?P<chr>(?:L|u|U)?'(?:\\.|[^'\\\n])+')
  | (?P<num>(?:0[xX][0-9a-fA-F']+|\d[\d']*\.?[\d']*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)[uUlLfF]*)
  | (?P<id>[A-Za-z_]\w*)
  | (?P<ws>\s+)
  | (?P<op>->|\+\+|--|<<=|>>=|<<|>>|<=|>=|==|!=|&&|\|\||\+=|-=|\*=|/=|%=|&=|\|=|\^=|\.\.\.)
  | (?P<other>.)
""", re.S | re.X)

RE_GENERATED = re.compile(r"^(?:fn|p|v|g|T|S|E|e|f|L)_\d+$")

RE_FMT = re.compile(r"%[-+ #0]*(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|h|ll|l|L|q|j|z|t)?[diouxXeEfFgGaAcspn%]")


def tokenize_c(text):
    for m in RE_TOKEN.finditer(text):
        yield m.lastgroup, m.group()


def mask_string(tok, index):
    """Same length, same escapes, same printf directives; everything else
    becomes x. A small index keeps distinct literals distinct."""
    m = re.match(r'^((?:L|u8|u|U)?")(.*)(")$', tok, re.S)
    if not m:
        return tok
    prefix, body, suffix = m.groups()
    keep = [False] * len(body)
    for mm in RE_FMT.finditer(body):
        for i in range(mm.start(), mm.end()):
            keep[i] = True
    i = 0
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            keep[i] = keep[i + 1] = True
            i += 2
        else:
            i += 1
    out = []
    tag = str(index)
    t = 0
    for i, ch in enumerate(body):
        if keep[i]:
            out.append(ch)
        elif t < len(tag):
            out.append(tag[t])
            t += 1
        else:
            out.append("x")
    return prefix + "".join(out) + suffix


def is_system_path(path, sys_includes):
    if not path:
        return False
    p = path.replace("\\", "/").lower()
    for s in sys_includes:
        s = s.replace("\\", "/").lower().rstrip("/")
        if s and p.startswith(s + "/"):
            return True
    for marker in ("/usr/include/", "/usr/lib/gcc/", "/usr/local/include/", "program files", "windows kits",
                   "cov-analysis", "coverity-compiler-compat", "coverity-macro-compat"):
        if marker in p:
            return True
    return False


class Obfuscator:
    """Builds the rename maps from the slice's own knowledge and applies them.

    Three maps, applied by position so that a field, a struct tag and a
    variable may share a spelling without sharing a new name:
      fields   -- after '.' or '->' in the body; field names in struct bodies
      tags     -- after 'struct' / 'union' / 'enum'
      general  -- everything else: functions, globals, typedefs, enumerators,
                  parameters, locals, labels, the function itself
    """

    PREFIX = {"function": "fn", "target": "fn", "param": "p", "local": "v", "global": "g",
              "typedef": "T", "struct": "S", "enum": "E", "enumerator": "e", "field": "f", "label": "L"}

    def __init__(self, sl, sys_includes, callees_text):
        self.sl = sl
        self.sys = sys_includes
        self.fields = {}          # old -> new
        self.tags = {}
        self.general = {}
        self.category = {}        # new -> category
        self.keep = set()
        self.reasons = {}
        self.counters = {}
        self.classify(callees_text)

    # ---- map building --------------------------------------------------
    def _map_for(self, category):
        if category == "field":
            return self.fields
        if category in ("struct", "enum"):
            return self.tags
        return self.general

    def _rename(self, name, category):
        if not name or name in C_KEYWORDS or name.startswith("__") or name.startswith("__cov_anon_"):
            return
        m = self._map_for(category)
        if name in m or name in self.keep:
            return
        n = self.counters.get(category, 0) + 1
        self.counters[category] = n
        new = "fn_0" if category == "target" else "%s_%d" % (self.PREFIX[category], n)
        m[name] = new
        self.category[new] = (category, name)

    def _also(self, alias, primary, category, into=None):
        """Point one more spelling at the new name `primary` already has.

        C++ separates the name the emit keys an entity by from the name the
        text spells it with: a callee is keyed by its mangled name but called
        by its `id`, an enumerator likewise, and a nested type is keyed by
        `_ZN...E` but written `Outer::Inner`. Every such spelling has to reach
        the same new name, or the original leaks into the twin.
        """
        src = self._map_for(category)
        dst = self._map_for(into) if into else src
        new = src.get(primary)
        if not alias or new is None or (alias == primary and dst is src):
            return
        if alias in dst or alias in self.keep or alias in C_KEYWORDS:
            return
        dst[alias] = new

    def _keep(self, name, why):
        if name:
            self.keep.add(name)
            self.reasons.setdefault(name, why)

    def classify(self, callees_text):
        sl = self.sl
        # callees: --print-callees gives each one's declaring file (a
        # 'defined in TU' line appears only for same-TU definitions, so it is
        # not the criterion; the declaring file is)
        callee_loc = {}
        cur = None
        for line in callees_text.splitlines():
            s = line.strip()
            if s.startswith("Call to: "):
                sig = s[len("Call to: "):]
                # `find` prints `name(params) /*mangled*/`, and sl.functions is
                # keyed by the mangled name, so key this by the same thing --
                # the demangled base name only matches for C, where there is no
                # mangled form to print.
                mm = re.search(r"/\*(_Z[^*]+)\*/", sig)
                cur = mm.group(1) if mm else sig.split(" /*")[0].split("(")[0].split("::")[-1]
            elif cur and RE_LOC.match(s) and cur not in callee_loc:
                callee_loc[cur] = RE_LOC.match(s).group(1)
        for nm in sl.functions:
            loc = callee_loc.get(nm)
            if loc is None:
                loc = sl.lookup_loc("function", nm, "f")
            # the prototype and the call site both spell the source name
            spelled = sl.functions[nm].get("id") or source_spelling(nm)
            if loc and not is_system_path(loc, self.sys):
                self._rename(nm, "function")
                self._also(spelled, nm, "function")
            elif loc:
                self._keep(nm, "library function (declared in %s); the analyzer models it by name" % loc)
                self._keep(spelled, "library function (source spelling of %s)" % nm)
            # No declaring file means the tool cannot tell a library name from a
            # project one. Saying "library" there would emit it unchanged on a
            # guess, so leave it unclassified instead: it is not renamed (the
            # analyzer may model it by name) but it is reported, and a human
            # decides before the file leaves.
        # globals
        for nm in sl.globals:
            loc = sl.lookup_loc("global", nm, "g")
            if loc and is_system_path(loc, self.sys):
                self._keep(nm, "library global (declared in %s)" % loc)
            else:
                # `find --kind g` does not index a global that is only declared
                # `extern`, so there is usually no location to judge by. Rename
                # rather than keep: the slice declares every global `extern` and
                # unmodelled, so a new name costs the analysis nothing, while
                # keeping a project name costs exactly what this mode exists to
                # prevent.
                self._rename(nm, "global")
        # structs/unions and their fields
        for nm in sl.classes:
            if is_anonymous(nm) or sl.names._local_of(nm):
                system = False
            else:
                loc = sl.decl_loc.get(("class", nm))
                if loc is None:
                    loc = sl.lookup_loc("class", nm, "c")
                system = is_system_path(loc, self.sys)
            tag = sl.names.tag(nm, "s")
            fields = [f.get("name") for k, f in ((sl.class_defs.get(nm) or Node("x")).get("fields") or [])]
            # A mangled instantiation name is not a library API name even when
            # the template is library code: it spells out the types it was
            # instantiated on, and those are the project's
            # (`_ZSt5dequeIN5boost10shared_ptrI22PacketCollectorRequestEE...`).
            if system and nm.startswith("_Z"):
                system = False
            if system:
                self._keep(tag, "library struct")
                for f in fields:
                    if f and f != "<anonymous>":
                        self._keep(f, "field of a library struct")
            else:
                self._rename(tag, "struct")
                # a class name is also written without an elaborated specifier,
                # in `Outer::member` and in a C++ cast or constructor call
                self._also(tag, tag, "struct", into="global")
                for f in fields:
                    if f and f != "<anonymous>":
                        self._rename(f, "field")
        # enums and enumerators
        for nm, node in sl.enums.items():
            loc = sl.decl_loc.get(("enum", nm))
            system = is_system_path(loc, self.sys) and not nm.startswith("_Z")
            tag = sl.names.tag(nm, "e")
            parts = nested_components(nm)
            enums_ = [(e.get("name"), e.get("id")) for k, e in ((node or Node("x")).get("enumerators") or [])]
            if system:
                self._keep(tag, "library enum")
                for v, vid in enums_:
                    self._keep(v, "library enumerator")
                    self._keep(vid, "library enumerator (source spelling of %s)" % v)
            else:
                self._rename(tag, "enum")
                if parts:
                    # written `Outer::Inner` at every use and bare `Inner` in
                    # the class body, never by the `_ZN...E` name it is keyed by
                    self._also(parts[-1], tag, "enum")
                    self._also(parts[-1], tag, "enum", into="global")
                for v, vid in enums_:
                    self._rename(v, "enumerator")
                    self._also(vid or source_spelling(v), v, "enumerator")
        # typedefs
        for nm, td in sl.typedefs.items():
            if nm in STD_TYPEDEFS or nm.startswith("__"):
                self._keep(nm, "standard typedef")
                continue
            # There is no `--kind t`, so a typedef's own declaring file is never
            # available; the target's location used to stand in for it. It does
            # not: `typedef std::unordered_map<...> SIPSG_LI_TARGET_GROUP_MAP;`
            # is a project name for a library type, and keeping it published the
            # name. A typedef is renamed unless it is recognisably standard,
            # which the STD_TYPEDEFS check above decides.
            self._rename(nm, "typedef")
        # the function, its parameters and locals
        self._rename(sl.name, "target")
        # the body declares the function by its source name, not the mangled
        # one the emit keys it by
        self._also(source_spelling(sl.name), sl.name, "target")
        for nm in sl.params:
            self._rename(nm, "param")
        for nm in sl.locals:
            self._rename(nm, "local")

    # ---- application ---------------------------------------------------
    def field_name(self, name):
        return self.fields.get(name, name)

    def new_name(self, old):
        return self.general.get(old, old)

    def apply(self, text):
        """Rename by position, mask strings, drop comments.
        Returns (new_text, mapping, unclassified identifiers)."""
        for m in re.finditer(r"\bgoto\s+([A-Za-z_]\w*)", text):
            self._rename(m.group(1), "label")
        out = []
        str_index = 0
        prev = None            # previous significant token text
        in_directive = False   # inside a #... line: ours, copied verbatim
        unclassified = set()
        for kind, tok in tokenize_c(text):
            if kind == "comment":
                continue
            if kind == "ws":
                out.append(tok)
                if "\n" in tok:
                    in_directive = False
                continue
            if tok == "#" and (prev is None or out and out[-1].endswith("\n")):
                in_directive = True
            if in_directive:
                out.append(tok)
                prev = tok
                continue
            if kind == "str":
                str_index += 1
                out.append(mask_string(tok, str_index))
                prev = tok
                continue
            if kind == "id":
                if prev in (".", "->"):
                    new = self.fields.get(tok)
                elif prev in ("struct", "union", "enum", "class"):
                    new = self.tags.get(tok)
                else:
                    new = self.general.get(tok)
                if new is None and tok not in self.keep and tok not in C_KEYWORDS \
                        and not tok.startswith("__") and tok not in ("NULL", "va_start", "va_arg", "va_end", "va_copy") \
                        and not RE_GENERATED.match(tok):
                    unclassified.add(tok)
                out.append(new or tok)
                prev = tok
                continue
            out.append(tok)
            prev = tok
        new_text = re.sub(r"\n{3,}", "\n\n", "".join(out))
        mapping = {new: {"was": old, "kind": cat} for new, (cat, old) in self.category.items()}
        return new_text, mapping, sorted(unclassified)


# ==========================================================================
# emit + analyze one file

def run_emit(bin_dir, flags, idir, slice_path, log_path):
    if os.path.isdir(idir):
        import shutil
        shutil.rmtree(idir)
    exe = os.path.join(bin_dir, "cov-emit")
    if os.name == "nt" and os.path.exists(exe + ".exe"):
        exe += ".exe"
    cmd = [exe, "--dir", idir] + flags + [slice_path]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = p.stdout + p.stderr
    with open(log_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(" ".join(cmd) + "\n\n" + log)
    errs = re.findall(r'"[^"]*", line (\d+): (?:error|warning #\d+)', log)
    rec = re.search(r"(\d+) recoverable error", log)
    ok = "complete." in log and p.returncode == 0
    return {"ok": ok, "rc": p.returncode, "recoverable": int(rec.group(1)) if rec else 0,
            "error_lines": errs[:6], "log": log}


def emit_symbol_name(bin_dir, idir, source_name):
    """How the analysis log's `n:` field will spell this function: for C++ the
    mangled name, which cannot be predicted for the obfuscated twin because
    its parameter types were renamed too. Ask the emit. For C the two are the
    same and the lookup is a no-op.
    """
    out = manage_emit(bin_dir, idir, ["find", source_name, "--kind", "f"])
    m = re.search(r"/\*(_Z[^*]+)\*/", out)
    return m.group(1) if m else source_name


def run_analyze(bin_dir, idir, fn_name, log_path, paths=None, emit_name=None):
    exe = os.path.join(bin_dir, "cov-analyze")
    if os.name == "nt" and os.path.exists(exe + ".exe"):
        exe += ".exe"
    cmd = [exe, "--dir", idir, "--print-paths"]
    if paths:
        cmd += ["--paths", str(paths)]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    with open(log_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(" ".join(cmd) + "\n\n" + p.stdout + p.stderr)
    res = {"rc": p.returncode, "wur": None, "paths": None, "pathout": False, "pathed_out": [], "count": None}
    logp = os.path.join(idir, "output", "analysis-log.txt")
    if p.returncode != 0 or not os.path.exists(logp):
        return res
    with open(logp, encoding="utf-8", errors="replace") as f:
        for l in f:
            l = l.rstrip()
            if l.startswith("wur: ") and l.endswith(" n: %s in TU 1" % (emit_name or fn_name)):
                res["wur"] = re.sub(r" mem=\d+ max=\d+", "", l)
                m = re.search(r" (\d+)( PATHOUT=\d+)? n: ", l)
                if m:
                    res["paths"] = int(m.group(1))
                    res["pathout"] = bool(m.group(2))
            elif "Pathed out" in l and (' in "%s(' % fn_name in l or "::%s(" % fn_name in l):
                m = re.search(r"Pathed out: (\d+) paths traversed by (\S+) in", l)
                if m:
                    res["pathed_out"].append((m.group(2), int(m.group(1))))
            elif l.startswith("summary: paths_exceeded count: "):
                res["count"] = int(l.rsplit(" ", 1)[1])
    res["pathed_out"] = sorted(set(res["pathed_out"]))
    return res


def report_emit(label, r):
    line = "%-9s cov-emit: %s" % (label, "emitted" if r["ok"] else "FAILED (exit %d)" % r["rc"])
    if r["recoverable"]:
        line += "; %d recoverable errors" % r["recoverable"]
    if r["error_lines"]:
        line += "; first diagnostics at lines " + ", ".join(r["error_lines"])
    print(line)
    if not r["ok"]:
        for l in r["log"].splitlines():
            if "error" in l.lower():
                print("    " + l[:200])


def report_analyze(label, r):
    if r["wur"]:
        print("%-9s analysis: %s" % (label, r["wur"]))
    for comp, n in r["pathed_out"]:
        print("%-9s analysis: Pathed out: %d paths traversed by %s" % (label, n, comp))
    if r["count"] is not None:
        print("%-9s analysis: paths_exceeded count: %d" % (label, r["count"]))
    if r["rc"] != 0:
        print("%-9s analysis: cov-analyze FAILED (exit %d)" % (label, r["rc"]))


# ==========================================================================
# main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--bin", required=True, help="<install>/bin of the version that wrote the idir")
    ap.add_argument("--tu", required=True, type=int)
    ap.add_argument("--name", required=True, help="function name exactly as the analysis log printed it")
    ap.add_argument("--out", help="output directory (default <idir>/output/pathout/slice-<name>)")
    ap.add_argument("--emit", action="store_true", help="re-emit the slice with the recorded flags")
    ap.add_argument("--analyze", action="store_true", help="also cov-analyze --print-paths the one-file idir")
    ap.add_argument("--paths", type=int, help="pass --paths N to the analysis")
    ap.add_argument("--obfuscate", action="store_true",
                    help="also write <name>.obf.c: project identifiers renamed, string literals masked, "
                         "comments dropped, library names kept; with --analyze, verify both slices analyze alike")
    a = ap.parse_args()

    out_dir = a.out or os.path.join(a.dir, "output", "pathout", "slice-" + re.sub(r"[^A-Za-z0-9_]", "_", a.name))
    os.makedirs(out_dir, exist_ok=True)

    flags, meta = recorded_emit_flags(a.bin, a.dir, a.tu)
    cxx = bool(meta and meta["lang"] == "c++")

    # 1. body
    body = manage_emit(a.bin, a.dir, ["--tu", str(a.tu), "find", find_regex(a.name), "--kind", "f", "--print-definitions"])
    if "Matching function" not in body:
        sys.exit("no function matched %s in TU %d" % (find_regex(a.name), a.tu))
    if body.count("Matching function") > 1:
        print("warning: several definitions matched; slicing the first", file=sys.stderr)
        body = body.split("/*\n * Matching function")[1]
        body = "/*\n * Matching function" + body
    # 2. tree
    dbg = manage_emit(a.bin, a.dir, ["--tu", str(a.tu), "find", find_regex(a.name), "--kind", "f", "--print-debug"])
    roots = parse_debug(dbg)
    if not roots:
        sys.exit("could not parse --print-debug output")
    header, root = roots[0]
    sl = Slice(a.bin, a.dir, a.tu, a.name, cxx)
    sl.collect(root)
    sl.close()
    text = sl.render(body, a.dir)

    ext = ".cpp" if cxx else ".c"
    slice_path = os.path.join(out_dir, re.sub(r"[^A-Za-z0-9_]", "_", a.name) + ".slice" + ext)
    with open(slice_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("slice   : %s  (%d lines)" % (slice_path, text.count("\n")))
    print("contents: %d typedefs, %d struct definitions (+%d forward-declared only), %d enums, %d globals, %d prototypes"
          % (len([t for t in sl.typedefs if not t.startswith("__builtin_")]), len(sl.class_defs),
             len(sl.classes) - len(sl.class_defs), len(sl.enums), len(sl.globals), len(sl.functions)))
    for n in sl.notes:
        print("note    : " + n)

    # ---- obfuscated twin
    obf_path = obf_name = None
    if a.obfuscate:
        callees = manage_emit(a.bin, a.dir, ["--tu", str(a.tu), "find", find_regex(a.name), "--kind", "f", "--print-callees"])
        ob = Obfuscator(sl, (meta or {}).get("sys_includes", []), callees)
        obf_text, mapping, unclassified = ob.apply(sl.render(body, a.dir, ob))
        obf_name = ob.new_name(a.name)
        obf_text = ("/* Obfuscated slice: project identifiers renamed by kind (fn_ p_ v_ g_ T_ S_ E_ e_ f_ L_),\n"
                    " * string literals masked to same-length placeholders, comments removed. Library\n"
                    " * functions, types and standard typedefs keep their names so the analyzer's models\n"
                    " * still apply. Numeric constants and all control flow are unchanged. */\n" + obf_text)
        # Named after the NEW name: this is the one file that leaves, and a C++
        # mangled name spells out the function and its parameter types, so
        # naming it after --name would publish in the filename exactly what the
        # contents just removed.
        obf_path = os.path.join(out_dir, re.sub(r"[^A-Za-z0-9_]", "_", obf_name) + ".obf" + ext)
        with open(obf_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(obf_text)
        map_path = os.path.join(out_dir, re.sub(r"[^A-Za-z0-9_]", "_", a.name) + ".obf.map.json")
        import json
        with open(map_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"function": a.name, "tu": a.tu, "idir": a.dir, "renamed": mapping,
                       "kept": {k: v for k, v in ob.reasons.items()},
                       "unclassified": unclassified}, f, indent=1, sort_keys=True)
        cats = {}
        for new, (cat, old) in ob.category.items():
            cats[cat] = cats.get(cat, 0) + 1
        print("obfusc. : %s  (%d lines)" % (obf_path, obf_text.count("\n")))
        print("renamed : " + ", ".join("%d %s" % (n, c) for c, n in sorted(cats.items())))
        print("kept    : %d library names (listed with reasons in the map); map, keep it local: %s"
              % (len(ob.keep), map_path))
        if unclassified:
            print("review  : %d identifiers neither renamed nor classified as library -- check them "
                  "before the file leaves: %s" % (len(unclassified), ", ".join(unclassified[:20])))

    if not (a.emit or a.analyze):
        return
    if flags is None:
        sys.exit("no recorded cov-emit invocation for TU %d; cannot re-emit" % a.tu)
    with open(os.path.join(out_dir, "cov-emit.flags"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(flags) + "\n")

    # the `Pathed out` lines name the function by its demangled signature, so
    # these are source spellings; the `wur:` line needs the emit's own name
    runs = [("slice", slice_path, source_spelling(a.name), os.path.join(out_dir, "idir"))]
    if obf_path:
        runs.append(("obfusc.", obf_path, obf_name, os.path.join(out_dir, "idir-obf")))
    results = {}
    for label, path, fn_name, idir in runs:
        suffix = "" if label == "slice" else "-obf"
        er = run_emit(a.bin, flags, idir, path, os.path.join(out_dir, "cov-emit%s.log" % suffix))
        report_emit(label, er)
        if not er["ok"] or not a.analyze:
            continue
        ar = run_analyze(a.bin, idir, fn_name, os.path.join(out_dir, "cov-analyze%s.log" % suffix), a.paths,
                         emit_name=emit_symbol_name(a.bin, idir, fn_name))
        report_analyze(label, ar)
        results[label] = ar
    if "slice" in results and "obfusc." in results:
        s, o = results["slice"], results["obfusc."]
        same = (s["paths"], s["pathout"], s["pathed_out"]) == (o["paths"], o["pathout"], o["pathed_out"])
        if same:
            print("verify  : obfuscation preserved the analysis -- same path count (%s), same PATHOUT flag, "
                  "same pathed-out checkers" % s["paths"])
        else:
            print("verify  : DIFFERS -- slice %s/%s/%s vs obfuscated %s/%s/%s; do not trust the obfuscated "
                  "copy for this question" % (s["paths"], s["pathout"], [c for c, n in s["pathed_out"]],
                                              o["paths"], o["pathout"], [c for c, n in o["pathed_out"]]))


if __name__ == "__main__":
    main()
