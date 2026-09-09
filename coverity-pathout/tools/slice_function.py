#!/usr/bin/env python3
"""Cut one function out of a Coverity intermediate directory as a file that
compiles on its own -- the function body plus every typedef, struct, enum,
global and callee prototype it needs -- so it can be re-emitted and
re-analyzed in seconds while you change it.

    slice_function.py --dir <idir> --bin <install>/bin --tu <N> --name <fn> \
        [--out <dir>] [--emit] [--analyze]

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
            return t.get("name", "?") + " " + inner
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
            dim = "[%s]" % count if count not in (None, "", "-1", "unknown") else "[]"
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
                if cls.get("fields") is None:
                    continue
                return cls
        return None

    def fetch_enum(self, name):
        out = manage_emit(self.bin, self.idir, ["find", find_regex(name), "--kind", "e", "--print-debug"])
        for header, root in parse_debug(out):
            en = root.get("enum")
            if isinstance(en, Node) and en.get("name") == name:
                return en
        return None

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
    def render(self, body_text, provenance):
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
        # forward declarations
        fwd = []
        for nm in sorted(self.classes):
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
            if node is None:
                en.append("enum %s { __cov_%s_unknown };" % (self.names.tag(nm, "e"), self.names.tag(nm, "e")))
                self.notes.append("enum %s: no definition found; emitted as a placeholder" % nm)
                continue
            vals = []
            for k, e in (node.get("enumerators") or []):
                vals.append("  %s = %s" % (e.get("name"), e.get("value", "0")))
            en.append("enum %s {\n%s\n};" % (self.names.tag(nm, "e"), ",\n".join(vals) if vals else "  __cov_empty"))
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
            if ft.get("is_method") == "true":
                self.notes.append("callee %s is a C++ method; not declared" % nm)
                continue
            pr.append("%s;" % P.decl(ft, nm))
        if pr:
            out.append("\n/* callees (prototypes only: the analysis sees them as unmodeled) */\n" + "\n".join(pr))
        out.append("\n/* the function */\n" + self.rewrite_body(body_text).rstrip() + "\n")
        return "\n".join(out)

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
            d = P.decl(ftype, fname)
            if width:
                d += " : " + width
            lines.append("%s  %s;" % (indent, d))
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
    skip = False
    for t in toks[1:-1]:
        if skip:
            skip = False
            continue
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
    return flags, {"exe": exe, "source": src, "lang": lang}


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

    if not (a.emit or a.analyze):
        return
    if flags is None:
        sys.exit("no recorded cov-emit invocation for TU %d; cannot re-emit" % a.tu)
    with open(os.path.join(out_dir, "cov-emit.flags"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(flags) + "\n")
    idir = os.path.join(out_dir, "idir")
    if os.path.isdir(idir):
        import shutil
        shutil.rmtree(idir)
    exe = os.path.join(a.bin, "cov-emit")
    if os.name == "nt" and os.path.exists(exe + ".exe"):
        exe += ".exe"
    cmd = [exe, "--dir", idir] + flags + [slice_path]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = p.stdout + p.stderr
    with open(os.path.join(out_dir, "cov-emit.log"), "w", encoding="utf-8", newline="\n") as f:
        f.write(" ".join(cmd) + "\n\n" + log)
    errs = re.findall(r'"[^"]*", line (\d+): error', log)
    rec = re.search(r"(\d+) recoverable errors", log)
    ok = "complete." in log and p.returncode == 0
    print("cov-emit: %s%s%s" % ("emitted" if ok else "FAILED (exit %d)" % p.returncode,
                                 "; %s recoverable errors" % rec.group(1) if rec else "",
                                 "; first errors at slice lines %s" % ", ".join(errs[:6]) if errs else ""))
    if not ok:
        for l in log.splitlines():
            if "error" in l.lower():
                print("    " + l[:200])
        print("    full log: %s" % os.path.join(out_dir, "cov-emit.log"))
        return
    if not a.analyze:
        return
    exe = os.path.join(a.bin, "cov-analyze")
    if os.name == "nt" and os.path.exists(exe + ".exe"):
        exe += ".exe"
    cmd = [exe, "--dir", idir, "--print-paths"]
    if a.paths:
        cmd += ["--paths", str(a.paths)]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    with open(os.path.join(out_dir, "cov-analyze.log"), "w", encoding="utf-8", newline="\n") as f:
        f.write(" ".join(cmd) + "\n\n" + p.stdout + p.stderr)
    logp = os.path.join(idir, "output", "analysis-log.txt")
    if p.returncode != 0 or not os.path.exists(logp):
        print("cov-analyze: FAILED (exit %d); see %s" % (p.returncode, os.path.join(out_dir, "cov-analyze.log")))
        return
    ident = a.name
    with open(logp, encoding="utf-8", errors="replace") as f:
        for l in f:
            l = l.rstrip()
            if l.startswith("wur: ") and l.endswith(" n: %s in TU 1" % a.name):
                print("analysis: " + re.sub(r" mem=\d+ max=\d+", "", l))
            elif "Pathed out" in l and (' in "%s(' % ident in l or "::%s(" % ident in l):
                print("analysis: " + l.split("wur_diagnostics: ", 1)[1])
            elif l.startswith("summary: paths_exceeded"):
                print("analysis: " + l)


if __name__ == "__main__":
    main()
