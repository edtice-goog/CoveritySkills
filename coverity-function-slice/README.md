# coverity-function-slice

Part of [CoveritySkills](../README.md).

Gets **one function** out of a Coverity intermediate directory exactly as
the analyzer saw it, and makes it a file that compiles and analyzes on its
own. Extraction is one command against the AST; the standalone file is one
more; an obfuscated twin that can leave the building is a flag on the
second, with proof that the analyzer treats it like the original.

## The three things it does

**The function comes out of the emit, from the AST, in under a second.**

```bash
cov-manage-emit --dir <idir> --ticker-mode none --tu 77 find '^setup_env$' --kind f --print-definitions
```

509 lines for a 963-line function, macros expanded, `sizeof` folded, types
canonical: what the checker actually walked, including the branches that
live inside macros. No `cov-preprocess`, no extracting files, no scripts
that parse `.i` text. C++ is addressed by mangled name, so overloads are
never confused; static functions with the same name are separated by `--tu`.

**And the function becomes a file that compiles and analyzes on its own.**
A body alone will not re-emit -- it needs the typedefs, structs, globals and
callee prototypes that came from headers. Those are in the emit too: the
function's own debug tree carries every callee's full prototype (including
ones `find` cannot look up, like `strlen`), every global's type and every
typedef's target, and each struct's fields are one more query away.
`tools/slice_function.py` closes over all of it, prints C declarations back
out of the tree in dependency order, appends the body, re-emits the file
with the flags recorded for the original translation unit, and re-analyzes
it:

```
$ python3 tools/slice_function.py --dir <idir> --bin <bin> --tu 77 --name setup_env --emit --analyze
slice   : .../setup_env.slice.c  (906 lines)
contents: 42 typedefs, 18 struct definitions (+13 forward-declared only), 0 enums, 9 globals, 74 prototypes
cov-emit: emitted
analysis: wur: gen1 ... 5001 PATHOUT=1 n: setup_env in TU 1
```

Fifteen seconds. Edit the slice, run again. Forty randomly chosen proftpd
functions re-emitted 40 for 40; seventeen of nginx's eighteen PATHOUT
functions slice and analyze (the eighteenth needs one hand edit, for a cast
whose parentheses the pretty-printer drops). A function cov-emit dropped is
reported as `COULD NOT VERIFY`, never as a clean result. C++ free functions
work; methods use the preprocessed TU as their container instead.

**And, when it must, it can leave the building.** `--obfuscate` writes a
twin with every project identifier renamed by kind, every string literal
masked to a same-length placeholder, comments gone, and library names and
constants kept -- then emits and analyzes both and reports whether the
analyzer produced the same path count and the same pathed-out checkers. It
did, for every function tried. The map stays local; the twin can go to a
frontier model, or to the vendor, without carrying the codebase's name.

## Who calls it

`coverity-pathout` uses it for the function that hit the path limit and
for restructuring experiments on the slice; `coverity-fuzz-triage` uses
the slice as its fuzz target and puts the callee models back as stubs. On
its own it answers "show me what Coverity saw for `foo`" and "give me a
file I can iterate on without rebuilding". The reason it is a separate
skill: this is the piece that belongs in the product.

## What is in it

| | |
|---|---|
| `SKILL.md` | the procedure: extract -> make it compile -> (on request) obfuscate |
| `references/function-extraction.md` | `cov-manage-emit find` for C and C++, duplicates, reading the pretty-print, the metrics join, the other `find` outputs |
| `references/standalone-reproducer.md` | how the slice is built from the tree, the five rewrites, what differs from the original and why that is fine, the obfuscation mechanism, the C++ boundary and the preprocessed-TU route |
| `tools/slice_function.py` | one function as a standalone `.c`/`.cpp` file; `--emit`, `--analyze`, `--obfuscate`; exit 2 when there is no result |
| `evals/` | three fixtures (a C function with `for(;;)` and function-local unnamed types; C++ overloads; a C++ free function calling a static member) and a script that emits, extracts, slices and verifies them on your installation |
| `CALIBRATION.md` | what was measured, on what, and what was not |

## Requirements

- A local Coverity Analysis installation **of the version that wrote the
  intermediate directory** (`emit/version`, line 1). Developed and measured
  against 2025.9.0, 2026.3.0 and 2026.6.0 on Windows, against idirs built
  on Windows (MSVC) and under WSL (gcc).
- Python 3 (standard library only).

## Install

```bash
cp -r coverity-function-slice ~/.claude/skills/
```

Then: "show me what Coverity saw for `sqlite3_str_vappendf`", or "give me
`setup_env` as a file I can cov-emit by itself".
