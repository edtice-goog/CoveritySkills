# Capturing code that isn't a clean, self-contained file

The goal of capture is an intermediate directory (`idir`) containing a
faithful representation of the defective code. For a single self-contained
file, `cov-emit --dir idir file.c` is all you need. This file covers
everything messier.

## cov-emit basics

`cov-emit` is Coverity's compiler front end, invoked directly — no build
system, no native compiler, no `cov-configure`. Useful flags:

- `--c` — parse as C. **cov-emit defaults to C++ mode even for `.c` files.**
  Usually harmless, but C++ changes semantics (e.g. `const` linkage, stricter
  conversions, different aggregate rules) — if the defect could be
  language-sensitive, pass `--c` for C code.
- `--c++17` / `--c++14` / `--c++11` — pick a C++ standard when the code needs it.
- `-I <dir>` and `-D name=value` — include paths and macro definitions, same
  as a compiler.
- Multiple files: run cov-emit once per translation unit into the same
  `idir`; cov-analyze links their summaries for interprocedural analysis.

Parse errors from cov-emit read like compiler errors. Fix them the same way —
but see the stubbing rules below before changing anything.

## System headers: bare cov-emit has none

`cov-emit` invoked directly has **no system include paths at all** — even
`#include <stdlib.h>` fails with "could not open source file". Two ways out;
pick by what the answer is for:

1. **Hand-declare just what the code uses — the fast path for trivial
   snippets.** For a small file calling a handful of libc functions, replace
   the `#include` lines with correct prototypes (`void *malloc(size_t);`,
   `int printf(const char *, ...);`, a `typedef` for `FILE`, ...) and keep
   using bare cov-emit. Coverity's built-in library models key on function
   *names*, so `malloc`/`free`/`fopen`/`system` are still recognized as
   allocators, sinks, etc. This skips compiler configuration entirely and is
   usually the quickest route to a verdict. The one discipline it demands:
   get the signatures right. Wrong or conflicting declarations produce
   "recoverable errors" during emit, and functions involved in them may be
   silently dropped from analysis — defects then disappear for reasons that
   have nothing to do with checker capability. If the emit output mentions
   recoverable errors, fix the declarations before trusting any "not found"
   result.
2. **Use a real compiler (cov-configure + cov-build, below) when fidelity or
   presentation matters** — the output will be distributed (an RFP response,
   a report to a customer) and "captured with the real toolchain, source
   unmodified" reads better than "headers replaced by hand"; or the code
   leans on many headers/macros where hand-declaring gets error-prone; or the
   prototype route keeps producing recoverable errors. First-time
   `cov-configure` of a toolchain costs minutes; hand prototypes cost
   seconds.

## Making a snippet compilable without destroying the experiment

This is the dangerous part. The defect you're testing is often a property of
*exactly* the code structure the user gave you; "fixing" the snippet so it
compiles can erase the defect or fabricate a different one. Rules:

1. **Change nothing inside the function(s) containing the defect.** If the
   defect path runs through lines you touched, the experiment no longer
   answers the user's question. If you truly must edit those lines to get a
   parse, tell the user and get agreement first.

2. **Missing types**: prefer minimal typedefs/struct definitions with
   plausible member types over including a real header, unless the real
   header is available. Field count and types can matter to checkers that
   reason about sizes (OVERRUN, BAD_ALLOC_*) — note any guess you made in the
   final report as a caveat.

3. **Missing functions — think before stubbing.** Coverity treats a function
   that is *declared but has no body* very differently from one with an empty
   body. For an unimplemented callee, checkers use conservative modeling
   (several checkers have options like `UNINIT:allow_unimpl` governing
   exactly this). An empty-body stub, by contrast, is a *definition* that
   provably does nothing — e.g. it provably never initializes its out-param,
   which can make UNINIT fire where the real code wouldn't, or suppress a
   leak the real code has.

   - If the callee is irrelevant plumbing: leave it declared-but-undefined.
   - If the callee's behavior is part of the defect story (it sometimes
     initializes / sometimes allocates / sometimes returns null): write a
     stub that preserves that conditional structure, like the real code's
     simplified shape. The user's description of the real behavior is your
     spec.

4. **Keep the defect reachable.** Checkers may skip paths they can prove
   dead. If you hard-code a condition that the real program decides at
   runtime, you may have just proven the defect path dead. Use an opaque
   condition instead (e.g., a call to an undefined `int config(void);`)
   rather than a constant.

Whatever you stub, list the stubs and assumptions in the final report — they
are caveats on the verdict.

## When to use cov-configure + cov-build instead

Use the real-build route when any of these hold:

- The user has an actual build (Makefile, CMake, MSBuild) and the defect may
  depend on real headers, real macros, or compiler-specific behavior.
- The code heavily uses platform headers (windows.h, kernel headers) that are
  impractical to stub.
- cov-emit's parse diverges from what the real compiler accepts.

Sequence (example for gcc; use `cl` for MSVC, etc.):

```
$BIN/cov-configure --gcc                       # once per compiler type
$BIN/cov-build --dir idir gcc -c main.c        # wraps the real compile
$BIN/cov-analyze --dir idir ...
```

`cov-configure --list-configured-compilers` shows what's already configured.
This route requires the compiler to actually exist on the machine — check
before committing to it, and prefer whatever compiler the user's team really
uses, since parse behavior follows the emulated compiler.

## Verifying capture before analyzing

cov-emit prints `Emit for file '...' (TU n) complete.` per translation unit —
if you don't see it, nothing was captured and cov-analyze will analyze
nothing (or stale contents from a previous emit into the same idir). When in
doubt, start a fresh idir; emits accumulate, and a leftover TU from an earlier
experiment can produce confusing extra findings.

A broader principle behind all the choices in this file: **it is genuinely
hard to tell a capture problem from a real miss** — both look like "0
defects". Every shortcut taken during capture (hand prototypes, stubs,
skipped headers) adds doubt that contaminates a "not found" verdict. You can
audit a capture after the fact — `cov-manage-emit --dir idir list` shows what
was actually emitted, and `cov-find-function` confirms whether a specific
function made it into the analysis — but that is debugging, and it is slow.
When there is any doubt about the capture, paying the one-time cost of real
build capture (`cov-configure` + `cov-build` with the real compiler) is
cheaper than the investigation, and a NOT DETECTED verdict built on it is
worth far more.

**The canary shortcut.** For trivial examples there is a faster probe than
the diagnostic tools: temporarily insert an unmistakable defect into the
function in question — a guaranteed null dereference (`int *canary = 0;
*canary = 1;`) or similar something-a-default-checker-cannot-miss — re-emit,
re-analyze with defaults, and see whether it's reported. Reported: the
function is captured and analyzed, so a silent target defect is a real miss
(or a configuration question). Not reported: the capture is broken, and no
verdict about the target defect is trustworthy yet. Remove the canary before
any run you quote in the final report, and never leave it in the emit that
produces the quoted results (re-emit the clean source — emits accumulate).
