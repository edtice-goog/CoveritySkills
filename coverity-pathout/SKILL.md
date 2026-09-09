---
name: coverity-pathout
description: >
  Diagnose a Coverity PATHOUT notice -- a function that exceeded the
  analyzer's per-function path limit ("Exceeded path limit of 5000 paths",
  "paths_exceeded count", PATHOUT=1 in analysis-log.txt, cov-analyze --paths)
  -- and get the affected function in front of you without touching a
  preprocessed file. Use this skill when someone asks which functions hit
  the path limit, why a particular function did, what it cost in missed
  defects, whether to raise --paths, or how to restructure the function; and
  for the general chore it depends on: pulling one function's definition out
  of an intermediate directory ("extract this function from the idir",
  "show me what the analyzer saw for foo()"), which is done from the AST with
  cov-manage-emit find --print-definitions in under a second -- and for
  turning that function into a file that compiles and analyzes on its own
  ("re-analyze just this function", "make a standalone reproducer",
  "iterate on this function without rebuilding"), with every typedef, struct,
  global and callee prototype it needs printed back out of the same emit,
  re-emitted with the TU's recorded flags and re-analyzed in seconds. The central
  fact is that the limit counts paths x tracked state, not control-flow
  paths, so cyclomatic complexity does not explain a PATHOUT and the
  analyzer's own --print-paths output does. Requires a local Coverity
  Analysis installation of the version that wrote the intermediate
  directory.
---

# Coverity PATHOUT

`cov-analyze` bounds the work it will do on any one function: `--paths`,
default 5000. A function that exceeds it is logged as `PATHOUT`, and the
checker that exceeded it stops walking that function. This skill finds
those functions, gets each one in front of you as the analyzer saw it, names
the checker that ran out, and measures what the cut-off cost -- so the
answer is "raise the limit to N, verified on the translation unit" or "split
it at these seams", not a guess.

Read `coverity/RULES.md` first (rules 3, 8, 21-23 bear directly). The two
rules this skill adds are 35 and 36.

## What "paths" means

**The limit counts paths x state.** The engine walks the same code again
whenever it arrives in a state a checker considers different, and merges
paths that rejoin in the same state. Two functions with identical control
flow, 14 independent `if`s each, cyclomatic complexity 15, static path count
16,384: the one whose accumulator starts at a known constant explores 16,384
paths and trips the limit; the one whose accumulator starts unknown explores
106 and finishes (`evals/fixtures/ifs_known_vs_unknown.c`, measured). So:

- cyclomatic complexity and the acyclic path count (APC) in
  `FUNCTION.metrics.xml.gz` rank candidates and size them; they do not
  explain a PATHOUT (APC 6.4e9 finished in 3845 paths; APC 31104 did not
  finish in 5000).
- every checker and model deriver has its **own** count; the log's number is
  the maximum over them, and the limit trips when one exceeds it.
- which checker that is names the kind of state that multiplied --
  `REVERSE_INULL` means pointer nullness, `OVERRUN` means index/size values,
  `DEADCODE_pass2` means condition outcomes under false-path pruning.

Details and every measurement: `references/path-explosion.md`.

## Step 0: Pin the installation and protect the idir

Line 1 of `<idir>/emit/version` names the version that wrote it. **Use that
version's `bin/`** for every command here; another version refuses the emit
outright (`Expected version number is 355, but this directory has version
350`). Rule 3.

A re-run of `cov-analyze` rewrites `<idir>/output/`, including the log you
are diagnosing. Copy the idir (or at least `output/analysis-log.txt`) before
Step 2.

## Step 1: Read the log

The notice lives only in `<idir>/output/analysis-log.txt`. Nothing about it
reaches the console, the `*.errors.xml` files, the metrics, or Connect.

```bash
python3 tools/pathout_report.py --dir <idir>
```

or by hand (`references/analysis-log.md` has the anatomy):

```bash
L=<idir>/output/analysis-log.txt
grep -E '^summary: (paths_exceeded|Exceeded path limit)' $L   # count; warning appears only when the share is high
grep 'PATHOUT=.*in TU' $L                                      # named functions with TU ids
grep -c 'PATHOUT=.*n: batch' $L                                # batched work units -- functions NOT named
```

Three outcomes:

| you see | it means | next |
|---|---|---|
| `paths_exceeded count: 0` | no function hit the limit on this run | done; if someone saw a notice, it was a different run or configuration |
| named lines `... 5001 PATHOUT=1 n: setup_env in TU 77` | the function and its TU | Step 2 for the checker, Step 3 for the body |
| batch lines `... PATHOUT=4 nr=20 n: batch 645` | up to 20 functions per line, none named | Step 2 is mandatory -- `--print-paths` names them |

On a large project under a heavy configuration (`--all
--aggressiveness-level high`) nearly all PATHOUT lines are batch lines: 3
named out of 189 on subversion. The count is a property of the
configuration as much as the code -- the same idir at defaults had 16.

## Step 2: Ask the analyzer which checker, with `--print-paths`

```bash
$BIN/cov-analyze --dir <idir-copy> --tu <N>[,<N>...] --print-paths
```

`--tu` scopes the run to the translation units that hold the functions; it
reproduces the PATHOUT in isolation (verified on proftpd: 15 s for one TU
against 32 s for the project) and it is how you make Step 5 cheap. Without
`--tu` the run costs what the original analysis cost; that is still the
right call when the log has batch lines and you need every name.

The log then carries, per function and per component:

```
wur_diagnostics: 4956 paths traversed by DEADCODE_pass2 in "setup_env(pool *, cmd_rec *, char const *, char *)"
wur_diagnostics: Pathed out: 5001 paths traversed by REVERSE_INULL in "setup_env(pool *, cmd_rec *, char const *, char *)"
```

`Pathed out:` marks the culprit(s). These lines name the function by its
demangled signature and appear whether or not it sat in a batch.
`tools/pathout_report.py` on the re-run's idir joins everything.

`--path-log-threshold` sounds like the tool for this and is not: at 100 and
at 1000 it changed nothing in the log.

## Step 3: Get the function from the AST

```bash
$BIN/cov-manage-emit --dir <idir> --ticker-mode none --tu <N> \
    find '^<name>$' --kind f --print-definitions > <name>.txt
```

- `<name>` is exactly what the log printed after `n:` -- the identifier for
  C, the **mangled** name for C++ (`_ZN4demo6Widget1fEi`). The regex is
  matched against the mangled name, so anchor it and use the mangled form to
  pick an overload. From a demangled signature, list candidates first:
  `find '<identifier>' --kind f` prints `demo::Widget::f(int)
  /*_ZN4demo6Widget1fEi*/` for each match.
- `--tu` matters: `find` prints every definition that matches, and proftpd
  has seven functions called `main`.
- 0.4 s; 509 lines for a 963-line function. A miss prints nothing and exits
  0 -- check for the `Matching function` header.
- The body is what the analyzer saw: **macros expanded**, `sizeof` folded
  (`4UL /* sizeof (gid_t) */`), `errno` as `*__errno_location()`, types
  canonical. Branches hidden in macros are visible here and nowhere else.
  Line numbers are not preserved inside the body; the header's `declared
  at:` is the anchor, and `--tu N print-source` gives the captured source
  with a three-line header offset for a side-by-side.

**Never** extract the file, preprocess it, and cut the function out of the
`.i` text. The emit already holds the tree; a pretty-print of it is exact,
compact, and instant. `references/function-extraction.md` covers C++,
duplicates, the metrics join, and the other `find` outputs (`--print-debug`
for one construct's exact source location; `--print-callees`).

### Make it compile on its own

The body alone will not re-emit: it names typedefs, structs, globals and
callees that came from headers. The same emit holds all of those -- the
function's `--print-debug` tree carries every callee's prototype, every
global's type and every typedef's target, and `find --kind c --print-debug`
gives each struct's fields -- and the slicer closes over them:

```bash
python3 tools/slice_function.py --dir <idir> --bin $BIN --tu <N> --name <name> --emit --analyze
```

That writes `<name>.slice.c` (declarations printed from the tree in
dependency order, then the body), re-emits it with the flags recorded for
the original TU minus include paths, analyzes the one-file idir with
`--print-paths`, and prints the function's `wur:` and `Pathed out` lines.
`setup_env`: 906 lines, clean emit, `REVERSE_INULL` pathed out at 5001 as in
the original -- in 15 seconds, editable, repeatable. That is the loop for
Steps 4 and 5. C++ needs the preprocessed-TU route instead; both are in
`references/standalone-reproducer.md`.

Add `--obfuscate` when the slice has to go somewhere the code may not:
project names are renamed by kind (`fn_3`, `v_12`, `S_2`, `f_17`), string
literals are masked to same-length placeholders, library names and every
constant stay, and with `--analyze` the tool proves the analyzer cannot tell
the twin from the original (`verify : obfuscation preserved the analysis`).
The map file stays local. A `DIFFERS` verdict means the twin is not fit to
represent the function; a `review :` line lists identifiers to check by
hand before it leaves.

## Step 4: Diagnose -- read the body with the checker in mind

You know the multiplier (Step 2) and you have the body (Step 3). Look for
the structure that makes *that* state multiply along a straight line:

- a long sequence of independent decisions, each leaving a tracked value
  in a different state -- lookups followed by null checks, option flags
  tested one after another, error ladders of `goto fail`
- the same pointer or value re-tested many times (`c ? c->subset :
  main_server->conf` seven times in `setup_env`)
- conditionals that live inside macros and appear once per use
- `switch` chains and `&&`/`||` short-circuits, each a branch
- known constants flowing into many branches (the fixture's whole lesson)

Loops are rarely it: the engine fixpoints them. `setup_env` has 95 `if`s,
55 NULL comparisons, 22 `goto`s and no loop at all
(`references/worked-example-setup-env.md`).

Say which of these you found and which component it feeds. "CCM is 152" is
a size, not a diagnosis.

## Step 5: Decide and measure

Two levers, and both are measurable on the scoped TU in seconds:

**Raise the limit.** `--paths <N>` on the same `--tu` run. The log then says
how many paths the culprit actually needed (`setup_env`: 6003 -- it had
been cut off with a fifth of its work left). Then compare defects between
the default and the raised run with `cov-format-errors --json-output-v10`
on each idir copy: same set, or new findings? That difference *is* the cost
of the notice for this function, measured. (For `setup_env`: none.)

**Restructure.** Name the seams. A function that does five things in
sequence with independent state is five functions; a re-tested expression is
one local. The metrics (`ml`, `lc`) and the `declared at:` line give the
reader the place. Do not recommend touching logging macros or loops unless
Step 4 showed they contribute. **Try the edit on the slice** before
recommending it: change `<name>.slice.c`, re-run `slice_function.py
--emit --analyze`, and report the path count it produced rather than the
one you expected.

Raising `--paths` globally is legitimate -- the log itself says up to 5% of
functions normally hit the limit -- but it is paid on every function on
every run. Prefer a value the measurement justifies (`setup_env` needs
10000, not 200000) and say what it cost in time.

## Reporting

Verdict first (rule 21): the function, the checker that pathed out, the
structural cause, what the limit cost in defects (measured or "not
measured"), and the recommendation with its price. Then the evidence: the
log lines, the `--print-paths` line, the counts from the body, the defect
diff. Mark measured vs reasoned (rule 23). Say which PATHOUT functions you
did *not* take past Step 1 (rule 22).

## Anti-patterns

- Diagnosing from cyclomatic complexity, APC, or the source-level shape
  alone. The fixture disproves each one.
- Parsing `cov-preprocess` / `--preprocess-native` output to find a
  function. Slow, brittle, and still not what the analyzer saw.
- Re-emitting a pretty-printed body on its own, or hand-writing the
  declarations it needs. The tree has them all; `slice_function.py` prints
  them. (For C++, the preprocessed TU is the container, not a hand-built
  one.)
- Using a different Coverity version than the one that wrote the idir.
- Re-running `cov-analyze` into the only copy of the idir and losing the
  original log.
- Reading batch lines as "there is no function name to be had". There is;
  it is behind `--print-paths`.
- Reporting `paths_exceeded count: 0` as "no PATHOUT ever" when the user's
  notice came from a run with more checkers enabled.

## Where other skills take over

| Question | Skill |
|---|---|
| "Was the function even captured?" / the file is not in the emit | `coverity` (capture fidelity, rule 34) |
| "Would checker X have found the bug the cut-off hid?" | `coverity-defect-detectability` |
| The idir is from a version you no longer have | `coverity-recreate-from-emit` |

## Layout

```
coverity-pathout/
├── SKILL.md
├── README.md
├── CALIBRATION.md                       # what was measured, on what, and what was not
├── references/
│   ├── analysis-log.md                  # the four kinds of line, batches, --print-paths
│   ├── function-extraction.md           # cov-manage-emit find: C, C++, duplicates, output shape
│   ├── standalone-reproducer.md         # the slice: declarations from the tree, re-emit, re-analyze
│   ├── path-explosion.md                # paths x state, the fixture evidence, which checkers
│   └── worked-example-setup-env.md      # proftpd, end to end, with the defect diff
├── tools/
│   ├── pathout_report.py                # log + metrics join, optional AST extraction
│   └── slice_function.py                # one function as a file that compiles; --emit --analyze
└── evals/
    ├── fixture.sh                       # builds, analyzes and checks the fixtures
    ├── evals.json
    └── fixtures/
        ├── ifs_known_vs_unknown.c       # same CFG, one explodes, one does not
        └── overloads.cpp                # C++: mangled names, one overload explodes
```
