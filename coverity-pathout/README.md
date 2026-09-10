# coverity-pathout

Part of [CoveritySkills](../README.md).

Diagnoses a Coverity **PATHOUT** notice: a function on which `cov-analyze`
hit its per-function path limit (`--paths`, default 5000) and stopped. The
skill finds the functions, names the checker that ran out of paths, puts the
function in front of you exactly as the analyzer saw it, and measures what
the cut-off cost -- so the recommendation is "raise `--paths` to 10000,
verified on the translation unit, zero defects changed" or "split it here",
not a guess from cyclomatic complexity.

## The two things it knows that save the most time

**The limit counts paths x state, not control-flow paths.** Two functions
with identical control flow (14 independent `if`s, complexity 15, 16,384
static paths) behave completely differently: the one whose accumulator
starts at a known constant explores all 16,384 and trips the limit; the one
whose accumulator starts unknown explores 106. Every checker walks the
function with its own state and its own count; the limit trips when one of
them exceeds it. So the diagnosis comes from the analyzer's own
`--print-paths` output --

```
wur_diagnostics: Pathed out: 5001 paths traversed by REVERSE_INULL in "setup_env(pool *, cmd_rec *, char const *, char *)"
```

-- which names the function *and* the checker, and works even when the
log's own `PATHOUT=` lines are per-batch and name nothing (on a large
project under `--all --aggressiveness-level high`, that is 186 of 189).

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
analysis: Pathed out: 5001 paths traversed by REVERSE_INULL in "setup_env(pool *, cmd_rec *, char const *, char *)"
```

Fifteen seconds, and the notice reproduces on the one-file idir with the
same checker at the same count. Edit the slice, run again. All four proftpd
PATHOUT functions reproduce this way, and a random sample of 40 proftpd
functions re-emitted 40 for 40 with no recoverable errors. C++ uses the
preprocessed TU as its container instead.

For most users that is the whole job: the function is out, as the analyzer
saw it, and it compiles and analyzes alone. The rest is for two less common
needs -- diagnosing *why* it pathed out, and the one below.

**And, when it must, it can leave the building.** `--obfuscate` writes a twin with every
project identifier renamed by kind, every string literal masked to a
same-length placeholder, comments gone, and library names and constants
kept -- then emits and analyzes both and reports whether the analyzer
produced the same path count and the same pathed-out checkers. It did, for
every function tried. The map stays local; the twin can go to a frontier
model, or to the vendor, without carrying the codebase's name.

**When a defect escaped, it hunts the siblings.** A later tool found a bug
Coverity missed, and the reason was a PATHOUT. Raising the limit does not
help (a real case still pathed out at 200,001). Instead: a
*path-insensitive* CodeXM checker for the defect's shape runs over the
whole idir in seconds, its hits are filtered to the PATHOUT functions where
the relevant checker was cut off (on subversion: 503 hits, 115 in PATHOUT
functions, 27 where a null-tracking checker was the one cut off, all 27
refuted by reading), and each survivor is read, then fuzzed: the slice plus callee stubs generated from
Coverity's own derived models, built with clang-cl and ASan, so a crash at
the candidate's dereference is the confirmation. The fixture chain runs in
about a minute (`evals/escape-hunt/run.sh`).

## What is in it

| | |
|---|---|
| `SKILL.md` | the procedure: log -> `--print-paths` -> extract -> diagnose -> measure -> report |
| `references/analysis-log.md` | where the notice lives (only `output/analysis-log.txt`), the four kinds of line, batches, what `--path-log-threshold` does not do |
| `references/function-extraction.md` | `cov-manage-emit find` for C and C++, duplicates, reading the pretty-print, the metrics join, the other `find` outputs |
| `references/standalone-reproducer.md` | how the slice is built from the tree, what it rewrites, what differs from the original and why that is fine, the preprocessed-TU route for C++ |
| `references/path-explosion.md` | the evidence for paths x state, why APC and CCM do not predict it, which checkers path out most, what the limit costs |
| `references/worked-example-setup-env.md` | proftpd's `setup_env` end to end, including the raised-limit defect diff |
| `tools/pathout_report.py` | one command: log + `FUNCTION.metrics` join, batch detection, optional AST extraction of every affected function |
| `tools/slice_function.py` | one function as a standalone `.c` file, re-emitted with the TU's recorded flags and re-analyzed with `--print-paths` |
| `references/escape-hunt.md`, `candidate-checkers.md`, `fuzz-confirmation.md` | the escape hunt: shape checker over the idir, PATHOUT filter, read-then-fuzz confirmation with model-derived stubs |
| `tools/pathout_filter.py`, `tools/model_stubs.py`, `evals/escape-hunt/` | the filter, the stub generator, the tested checker, fixtures and harness |
| `evals/` | the two fixtures and a script that builds, analyzes and checks them on your installation |

## Requirements

- A local Coverity Analysis installation **of the version that wrote the
  intermediate directory** (`emit/version`, line 1). Developed and measured
  against 2025.9.0, 2026.3.0 and 2026.6.0 on Windows.
- Python 3 for the report tool (standard library only).

## Install

```bash
cp -r coverity-pathout ~/.claude/skills/
```

Then: "the analysis log says 189 functions exceeded the path limit -- which
ones, and is it a problem?" or "show me what Coverity saw for
`sqlite3_str_vappendf`".

## Development notes

Every claim was established by running it; `CALIBRATION.md` lists what, on
which version, and what was reasoned rather than measured. The fixtures were
written to falsify the obvious hypothesis (that branch count predicts
PATHOUT) and did; the subversion runs were repeated under two
configurations to establish that the notice count is a property of the
checker set; the worked example includes the measured defect difference at
a raised limit, which for that function was zero.
