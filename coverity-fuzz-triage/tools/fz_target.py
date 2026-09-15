#!/usr/bin/env python3
"""Assemble a fuzz target from a slice, the derived models of its callees, and a
harness snippet.

    fz_target.py --slice <fn>.slice.c --models <dir with index.txt> --harness harness.c \
                 --claim '<expr>' --before '<regex of the finding line>' --out target.c

The slice's callee prototypes are classified: libc names are left to the real
library; project callees get a stub printed from their derived model
(model_stubs.py); callees with no saved model get a generic stub and are
listed, because a verdict that relied on one is weaker. The finding's claim is
inserted as __fz_claim(<expr>) before the first slice line matching --before,
so the run reports "reached N times, never false" or crashes with the stub
choices that made it false.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # model_stubs.py sits beside this file
import model_stubs  # noqa: E402

LIBC = set("""strchr strrchr strcmp strncmp strcasecmp strncasecmp strlen strnlen strcpy strncpy
strcat strncat memcpy memset memcmp memmove memchr strerror qsort malloc calloc realloc free
__errno_location strspn strcspn strstr strpbrk strtol strtoul strtoll atoi atol sprintf snprintf
vsnprintf vsprintf printf fprintf vfprintf puts fputs getenv abort exit memchr strdup strndup
isspace isdigit isalpha isalnum tolower toupper fopen fclose fread fwrite fgets time
gettimeofday getpid getuid geteuid getgid getegid setuid seteuid setgid setegid
mempcpy __mempcpy getlogin getpwnam getpwuid stat lstat fstat access __ctype_b_loc __assert_fail
putenv setenv unsetenv sigaction sigemptyset siginterrupt signal read write close open
__builtin_expect __builtin_trap""".split())


def parse_callees(slice_text):
    m = re.search(r"/\* callees.*?\*/\n(.*?)\n/\* the function", slice_text, re.S)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("//") or not line.endswith(";"):
            continue
        nm = re.match(r"^.*?\b(\w+)\s*\(", line)
        if nm:
            out.append((nm.group(1), line))
    return out


def generic_stub(proto):
    ret, name, plist = model_stubs.parse_prototype(re.sub(r",\s*\.\.\.", "", proto))
    variadic = "..." in proto
    args = ["a%d" % i for i in range(len(plist))]
    params = ", ".join(model_stubs.declare(t, a) for t, a in zip(plist, args)) or "void"
    if variadic:
        params = params + ", ..." if params != "void" else "..."
    sig = "%s %s(%s)" % (ret, name, params)
    body = []
    r = ret.strip()
    if r.endswith("*"):
        body.append("  return __stub_choice(2) ? (%s)__stub_object(64) : 0;   /* NO MODEL: null or a static object */" % r)
    elif r != "void":
        body.append("  return (%s)__stub_choice(0);   /* NO MODEL: value unconstrained */" % r)
    return "/* stub for %s: NO SAVED MODEL, generic */\n%s {\n%s\n}" % (name, sig, "\n".join(body))


def model_stub(proto, dot, slice_text=""):
    s = model_stubs.stub(proto, dot)
    # a write(<arg N>->field) needs the parameter's struct to be defined in the
    # slice; a forward-declared one (the slice only needed the pointer) cannot
    # be stored through, so the write is dropped with a note
    ret, name, plist = model_stubs.parse_prototype(proto)
    out = []
    for line in s.split("\n"):
        m = re.search(r"\*\(void \*\*\)&\(a(\d+)->(\w+)\)", line)
        if m:
            i = int(m.group(1))
            t = plist[i] if i < len(plist) else ""
            if not type_is_complete(t, slice_text):
                out.append("    /* model: write(<arg %d>->%s) not reproduced: %s is incomplete in the slice */" % (i, m.group(2), t.strip()))
                continue
        out.append(line)
    return "\n".join(out)


def type_is_complete(t, slice_text):
    """Is the pointee of parameter type t a struct/union whose body the slice
    carries? Resolves one level of typedef (`typedef struct pool_rec pool;`)."""
    base = re.sub(r"\b(const|volatile|restrict|struct|union)\b", " ", t).replace("*", " ").strip()
    if not base:
        return False
    m = re.search(r"typedef\s+(struct|union)\s+(\w+)\s+%s\s*;" % re.escape(base), slice_text)
    tag = m.group(2) if m else base
    return re.search(r"^(struct|union)\s+%s\s*\{" % re.escape(tag), slice_text, re.M) is not None


# pool-based copy/alloc helpers whose derived model cannot express "the result
# equals the source": given their real semantics on request (--semantic)
SEMANTIC = {
    "pstrdup":  "  return (RET)fz_sem_strdup(a1);",
    "pstrndup": "  return (RET)fz_sem_strndup(a1, (unsigned long)a2);",
    "pcalloc":  "  return (RET)fz_alloc((unsigned long)a1 ? (unsigned long)a1 : 1);",
    "palloc":   "  return (RET)fz_alloc((unsigned long)a1 ? (unsigned long)a1 : 1);",
    "pstrcat":  "  return (RET)fz_sem_vcat(a0, __builtin_va_arg_pack_placeholder);",
}


def semantic_stub(name, proto):
    if name not in SEMANTIC:
        return None
    ret, _, plist = model_stubs.parse_prototype(proto)
    args = ["a%d" % i for i in range(len(plist))]
    params = ", ".join(model_stubs.declare(t, a) for t, a in zip(plist, args)) or "void"
    if name == "pstrcat":
        # variadic: concatenate the string arguments up to the NULL terminator
        return ("/* SEMANTIC stub for pstrcat: concatenation of its arguments */\n"
                "%s pstrcat(%s, ...) {\n  __builtin_va_list ap; char *r; __builtin_va_start(ap, a0);\n"
                "  r = fz_sem_vcat(ap); __builtin_va_end(ap); return (%s)r;\n}" % (ret, params, ret))
    body = SEMANTIC[name].replace("RET", ret)
    return "/* SEMANTIC stub for %s: real copy/alloc behaviour */\n%s %s(%s) {\n%s\n}" % (name, ret, name, params, body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", required=True)
    ap.add_argument("--models", required=True, help="directory holding <base>.dot files and index.txt (name base defs=N)")
    ap.add_argument("--harness", required=True)
    ap.add_argument("--claim", help="the finding's claim, as a C expression that must hold (e.g. 'ptr != NULL')")
    ap.add_argument("--before", help="regex of the slice line the claim is checked before")
    ap.add_argument("--keep", default="", help="comma-separated callees to leave undefined (the harness defines them)")
    ap.add_argument("--semantic", default="",
                    help="comma-separated callees given their real string/allocation semantics instead of the "
                         "model (pstrdup, pstrcat, pcalloc, palloc, pstrndup): the derived model of a copy "
                         "function does not say the copy equals its source, and a stub that returns an "
                         "unrelated buffer confirms claims the real callee cannot produce")
    ap.add_argument("--pin-normal", action="store_true",
                    help="focused mode: pin every model stub to its first normal behaviour (non-null, "
                         "allocating, zero or positive return) except the callees named in --free, which "
                         "stay fuzz-driven. Without it every stub is free and the run usually ends on a "
                         "bycatch null return before the finding's line is reached.")
    ap.add_argument("--free", default="", help="comma-separated callees left free under --pin-normal")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    free = set(x for x in a.free.split(",") if x)
    pins = []

    slice_text = open(a.slice, encoding="utf-8").read()
    index = {}
    ip = os.path.join(a.models, "index.txt")
    if os.path.exists(ip):
        for line in open(ip):
            parts = line.split()
            if len(parts) >= 2:
                index[parts[0]] = parts[1]
    keep = set(x for x in a.keep.split(",") if x)

    if a.claim and a.before:
        pat = re.compile(a.before)
        lines = slice_text.split("\n")
        for i, l in enumerate(lines):
            if pat.search(l):
                indent = re.match(r"\s*", l).group(0)
                lines.insert(i, "%s__fz_claim(%s);   /* the finding's claim, checked where the finding is */" % (indent, a.claim))
                break
        else:
            sys.exit("--before matched no slice line: %s" % a.before)
        slice_text = "\n".join(lines)

    semantic = set(x for x in a.semantic.split(",") if x)
    stubs, report = [], []
    for name, proto in parse_callees(slice_text):
        if name in keep:
            report.append("%-28s harness" % name)
            continue
        if name in semantic:
            s = semantic_stub(name, proto)
            if s:
                report.append("%-28s SEMANTIC stub (real copy/alloc behaviour, not the model)" % name)
                stubs.append(s)
                continue
            report.append("%-28s no semantic stub known; falling back" % name)
        if name in LIBC:
            report.append("%-28s real libc" % name)
            continue
        base = index.get(name)
        dot = os.path.join(a.models, base + ".dot") if base else None
        if dot and os.path.exists(dot):
            s = model_stub(proto, dot, slice_text)
            n = re.search(r"(\d+) behaviour", s).group(1)
            # the behaviour list with its indices, so a harness can FZ_PIN() by number
            behs = [re.sub(r"\s+", " ", m.strip()) for m in re.findall(r"/\* model: (.*?) \*/", s)
                    if not m.strip().startswith("dereference(")]      # the unconditional touch is not a choice
            report.append("%-28s model stub, %s behaviour(s): %s" % (name, n, "  ".join("%d=%s" % (i, b) for i, b in enumerate(behs))))
            stubs.append(s)
            if a.pin_normal and name not in free and len(behs) > 1:
                bad = ("returnsnull", "negative_return", "<- == -1", "<- < 0")
                normal = [i for i, b in enumerate(behs) if not any(x in b for x in bad)]
                if normal:
                    pins.append((name, normal[0], behs[normal[0]]))
        else:
            report.append("%-28s NO MODEL -> generic stub" % name)
            stubs.append(generic_stub(proto))

    harness = open(a.harness, encoding="utf-8").read()
    pin_fn = ["/* focused mode: every stub held to its normal behaviour except --free ones */",
              "static void fz_pins_default(void) {"]
    for name, k, desc in pins:
        pin_fn.append('  FZ_PIN("%s", %d);   /* %s */' % (name, k, desc))
    pin_fn.append("}")
    pin_fn.append("#define FZ_PINS_DEFAULT() do { if (fz_pin_n == 0) fz_pins_default(); } while (0)")
    out = ["/* ==== fuzz-triage support (before the slice: __fz_claim is used inside it) ==== */",
           '#include "fz_support.h"', slice_text,
           "\n/* ==== callee stubs from derived models ==== */", "\n\n".join(stubs),
           "\n".join(pin_fn),
           "\n/* ==== harness ==== */", harness]
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))
    print("written %s%s" % (a.out, "  (focused: %d stubs pinned, free: %s)" % (len(pins), ",".join(sorted(free)) or "none") if a.pin_normal else "  (free mode)"))
    for r in report:
        print("  " + r)


if __name__ == "__main__":
    main()
