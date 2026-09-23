---
name: coverity-pathout
description: >
  Diagnose a Coverity PATHOUT notice -- a function that exceeded the
  analyzer's per-function path limit ("Exceeded path limit of 5000 paths",
  "paths_exceeded count", PATHOUT=1 in analysis-log.txt, cov-analyze
  --paths) -- and find out what may be hiding behind it. Use this skill
  when someone asks which functions hit the path limit, why a particular
  function did, which checker was cut off in it, what the cut-off cost in
  missed defects, whether to raise --paths, how to restructure the
  function, or whether a defect that escaped Coverity ("a fuzzer / pen
  test / customer found a bug Coverity missed", "it was missed because the
  function pathed out", "are there more like it") has siblings behind the
  same limit. Its central facts: the limit counts paths x tracked state,
  not control-flow paths, so cyclomatic complexity does not explain a
  PATHOUT and the analyzer's own --print-paths output does; the checker
  that was cut off finished nowhere in that function, so the way to look
  there is a path-INSENSITIVE CodeXM shape checker over the whole idir,
  filtered to the PATHOUT functions where that checker stopped -- a
  catalogue of thirteen tested shapes is run whenever there is a PATHOUT,
  whether or not anything has escaped yet. Uses coverity-function-slice
  for the function body and coverity-fuzz-triage to confirm candidates by
  execution. Requires a local Coverity Analysis installation of the
  version that wrote the intermediate directory.
---

# Coverity PATHOUT

`cov-analyze` bounds the work it will do on any one function: `--paths`,
default 5000. A function that exceeds it is logged as `PATHOUT`, and the
checker that exceeded it stops walking that function. Nobody looked at the
rest of it. This skill finds those functions, names the checker that ran
out, runs a catalogue of path-insensitive shape checkers over the idir to
see what that checker might have found, gets the function in front of you
as the analyzer saw it, and measures what the cut-off cost -- so the answer
is a list of confirmed or refuted candidates and "raise the limit to N,
verified on the whole project" or "split it at these seams", not a guess.

Read `coverity/RULES.md` first (rules 3, 8, 21-23 bear directly). The rule
this skill adds is 36; rule 35 belongs to `coverity-function-slice`.

**This skill is one of a bundle of three**, and it calls the other two by
relative path: `coverity-function-slice` (the function body, the
standalone slice) and `coverity-fuzz-triage` (an execution verdict on a
candidate). If you have only this file -- fetched from a URL, or copied
alone -- clone the repository and work from the clone before starting:

```bash
git clone https://github.com/edtice-goog/CoveritySkills
```

The three sit side by side under `CoveritySkills/`, with `coverity/RULES.md`
above them. Do not substitute your own extraction, slicing or fuzzing for
the sibling skills; they carry the measured procedure and the tools.

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
outright. Rule 3.

A re-run of `cov-analyze` rewrites `<idir>/output/`, including the log you
are diagnosing. Copy the idir (or at least `output/analysis-log.txt`) before
Step 2, and do every re-analysis on a copy.

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
| named lines `... 5001 PATHOUT=1 n: setup_env in TU 77` | the function and its TU | Step 2 for the checker, Step 3 for what hid behind it |
| batch lines `... PATHOUT=4 nr=20 n: batch 645` | up to 20 functions per line, none named | Step 2 is mandatory -- `--print-paths` names them |

A `wur:` line with `PATHOUT=0`, or a second line for the same function
`with extra_info`, is not a hit. On a large project under a heavy
configuration (`--all --aggressiveness-level high`) nearly all PATHOUT
lines are batch lines: 3 named out of 189 on subversion. The count is a
property of the configuration as much as the code -- the same idir at
defaults had 16.

**If the count is more than a couple of dozen, read *Budget* (after Step
3) before doing anything per function.** Steps 1-3 cost the same whether
there are 18 PATHOUT functions or 4,000; Steps 4-6 and the survivor
verdicts cost per function, and 4,000 of them is not a run, it is a bill.

## Step 2: Ask the analyzer which checker, with `--print-paths`

```bash
$BIN/cov-analyze --dir <idir-copy> --print-paths > <idir-copy>/analyze.stdout 2>&1   # the original options, plus this
```

**Redirect it, and let the tools read it.** `--print-paths` writes one
diagnostic line per function per component: redis's log is 318,000 lines
and 33 MB, 295,000 of them diagnostics, and the same lines go to stdout.
The tools parse the log with regular expressions
(`tools/pathout_report.py`, `tools/pathout_filter.py`); by hand, `grep
'Pathed out'` gives the 80 lines that matter. When you do need to look
at the log -- an odd line, a function the tools did not join -- `grep`
for the function or the phrase and read those lines, not the file.

The log then carries, per function and per component:

```
wur_diagnostics: 4956 paths traversed by DEADCODE_pass2 in "setup_env(pool *, cmd_rec *, char const *, char *)"
wur_diagnostics: Pathed out: 5001 paths traversed by REVERSE_INULL in "setup_env(pool *, cmd_rec *, char const *, char *)"
```

`Pathed out:` marks the culprit(s). These lines name the function by its
demangled signature and appear whether or not it sat in a batch.
`tools/pathout_report.py` on the re-run's idir joins everything, and this
log is the input to the filter in Step 3.

**Whole project, not `--tu`, when the number matters.** `--tu <N>` scopes
the run to one translation unit and is fast (15 s against 32 s on
proftpd), but callees in other TUs lose their models, and models are part
of the state: on nginx a scoped run reproduced only 11 of 18 PATHOUTs. Use
`--tu` to get a checker name quickly on a small project; use the whole
project for the PATHOUT set, the filter, and the cost measurement in
Step 6. Run with the original options (the log's first line is the command
that produced it). `--path-log-threshold` sounds like the tool for this and
is not: at 100 and at 1000 it changed nothing in the log.

## Step 3: Look where nobody looked -- the shape catalogue

**Do this step whenever there is a PATHOUT, escape or no escape.** The
checker that pathed out finished nowhere in that function; a
path-INSENSITIVE checker for the shape of what it looks for, run over the
whole idir and filtered to those functions, is how you find out what it
might have said. Everywhere else the path-sensitive checker finished and
was right to stay quiet; inside a PATHOUT function nobody looked.

**No escaped defect to key on** (the usual case): every shape is a
hypothesis, so run the whole catalogue of tested shape checkers in one
pass, then filter with each checker's own relevance list:

```bash
git clone https://github.com/edtice-goog/pathout-shapes
pathout-shapes/bin/run_all.sh $BIN <idir-copy> <outdir>          # one cov-analyze, thirteen --codexm, seconds
python3 tools/pathout_filter.py --findings <outdir>/candidates.json \
    --log <print-paths idir>/output/analysis-log.txt --relevant auto --json survivors.json
```

Thirteen shapes: null-check-then-deref, unchecked null return, divide after
zero test, double release, unbounded copy into a fixed buffer, copy bounded
by the source's own length (CVE-2025-0282's shape), alloc never released,
unchecked array index, unbounded arithmetic into a size, length or index
(INTEGER_OVERFLOW's shape), a narrowing cast of such arithmetic, free of
non-heap, non-literal format string, sizeof of a pointer. Measured with the current catalogue:
nginx 155 hits over the idir, 2 in PATHOUT functions where the relevant
checker pathed out; zstd 488 / 3; redis 814 / 0 (before the catalogue
learned that `exit` and an expanded `assert` are exit guards, zstd had
60). The filter is the mechanism; the whole-idir run is cheap because the
checkers are structural.

**An escaped defect to key on**: derive the shape from the instance, not
the class ("null-tested in an `if`, dereferenced outside it", not
"FORWARD_NULL"). Take the catalogue's checker for it or write one --
`references/candidate-checkers.md` has the skeleton, the tree shapes and
the grammar traps, `evals/escape-hunt/null_check_then_deref.cxm` is a
tested one -- run it alone (`cov-analyze --disable-default --codexm
shape.cxm`, `cov-format-errors --json-output-v10`), and filter with
`--relevant <the checkers that would have caught it>`, e.g.
`FORWARD_NULL,NULL_RETURNS`. Subversion: 503 hits, 115 in PATHOUT
functions, **0** where `FORWARD_NULL` pathed out, 27 where `REVERSE_INULL`
did. Exclude the known instance.

**Then read each survivor**, and hand the ones reading cannot settle to
`coverity-fuzz-triage`. All 27 subversion survivors were refuted by
reading (preconditions, allocate-if-null macros, invariants between
variables, reassignment; `references/escape-hunt.md` has the catalogue).
Reading is inference, and it is what the skill exists to replace where
inference cannot reach a verdict; so when the user asks for execution
verdicts, or says the run is a test of the pipeline, send **every**
survivor to `coverity-fuzz-triage` and report the reading verdict beside
the execution verdict rather than instead of it.
A survivor list with a verdict and tier per entry is part of every PATHOUT
report; "the catalogue was not run" is a gap to state (rule 22). The
procedure with all the measurements: `references/escape-hunt.md`.

**One accepted limit, and what to do if it bites.** When a *model
deriver* (`generic_DERIVERS`, `uninit_DERIVERS`, ...) is what pathed out
in a function, every caller of that function was analyzed against a
weaker model, and those callers are not PATHOUT functions, so the filter
does not keep their hits. It only matters when one PATHOUT function calls
another, and the shape checkers use no models, so it is left as a known
limit; the filter prints a note with the counts whenever it applies. Put
the note's numbers in the report. If an escaped defect ever turns out to
sit in such a caller, open an issue at
https://github.com/edtice-goog/CoveritySkills/issues with the counts and
the component names only -- never a function name, a path, or code from
the idir -- and the authors will build the callers tier. Ask the user
before opening it; it is an outward action from their environment.

## Budget: pilot one function, price the rest, then ask

Everything up to here is per idir and cheap: the log, one `--print-paths`
run, one catalogue run, one filter. Everything from here on is per
function and paid in tokens and minutes: extracting a body and reading it
(a 900-line function is about 20 KB, roughly 5,000 tokens, read at least
once), slicing and re-analyzing it (20 s of tool time, few tokens), the
verdicts on its survivors (the body again, per survivor), a fuzz harness
(minutes of build and run), restructure experiments (many re-reads of
the body; the most expensive thing in this skill). On a log with 4,000
PATHOUT functions that is a bill the user did not ask for.

So, whenever the PATHOUT count is more than a couple of dozen:

1. **Rank, do not iterate.** From the filter's output, the functions with
   survivors are the ones that can hide a defect; everything else gets
   its one-line row from `pathout_report.py` and nothing more unless the
   user asks. Within the survivors, the function with the most, or with
   the highest path count, is the pilot.
2. **Run the whole per-function procedure on that one function** (Step 4
   through the verdicts on its survivors, Step 6 only if the user wants
   the cost of the limit) and write down what it cost: wall time, and
   tokens estimated from what was read -- the body's size (the report
   tool prints lines per extracted definition; about 12 tokens per line)
   times the number of times it was read, plus the tool output. Say the
   number and how it was estimated.
3. **Price the rest and stop.** Multiply by the number of functions that
   would get the same treatment, once for "survivors only" and once for
   "all", and put both in front of the user with the pilot's result:
   *"18 of 4,000 have survivors; the pilot took 11 minutes and about
   60,000 tokens; the 18 would be about 1.1 M tokens and three hours;
   all 4,000 about 240 M."* Then wait. Do not continue past the pilot
   without an answer, and do not silently take the cheaper option either;
   the choice is the user's.
4. **At scale, skip what does not scale.** Restructure experiments (Step
   6) and reading every dropped candidate are pilot-only unless asked.
   The cost-of-the-limit measurement (`--paths N` on the whole project) is
   one run, not per function, so it stays.

Say in the report which functions got the full treatment, which got only
the row, and what the user chose.

## Step 4: Get the function from the AST

The body is one command in `coverity-function-slice`:

```bash
$BIN/cov-manage-emit --dir <idir> --ticker-mode none --tu <N> \
    find '^<name>$' --kind f --print-definitions > <name>.txt
python3 ../coverity-function-slice/tools/slice_function.py --dir <idir> --bin $BIN --tu <N> --name <name> --emit --analyze
```

`<name>` is what the log printed after `n:` (the mangled name for C++);
`--tu` is from the same line. The first prints what the analyzer saw --
macros expanded, `sizeof` folded, 0.4 s. The second makes it a file that
compiles and analyzes on its own, which is the loop for Steps 5 and 6.
Read `cov-emit: emitted` and the `wur:` line; `COULD NOT VERIFY` means the
function was dropped and there is no result. A slice's callees have no
models, so a function whose count came from them finishes under the limit
as a slice (five of nginx's eighteen); the slice reproduces the PATHOUT
when the cause is local (the five `*_merge_loc_conf` ladders, `setup_env`).
Everything about extraction, slicing and the C++ boundary is that skill's.

**Never** extract the file, preprocess it, and cut the function out of the
`.i` text. The emit already holds the tree.

## Step 5: Diagnose -- read the body with the checker in mind

You know the multiplier (Step 2) and you have the body (Step 4). Look for
the structure that makes *that* state multiply along a straight line:

- a long sequence of independent decisions, each leaving a tracked value
  in a different state -- lookups followed by null checks, option flags
  tested one after another, error ladders of `goto fail`, configuration
  merge ladders (`if (conf->x == UNSET) conf->x = ...` 54 times)
- the same pointer or value re-tested many times (`c ? c->subset :
  main_server->conf` seven times in `setup_env`)
- conditionals that live inside macros and appear once per use
- `switch` chains and `&&`/`||` short-circuits, each a branch; a
  `switch (state)` inside a loop, with `state` assigned a known
  enumerator on every arm, re-enters the body once per known state
- known constants flowing into many branches (the fixture's whole lesson);
  an accumulator that starts from a constant and grows behind independent
  `if`s

Loops are rarely it: the engine fixpoints them. `setup_env` has 95 `if`s,
55 NULL comparisons, 22 `goto`s and no loop at all
(`references/worked-example-setup-env.md`). The exception is a loop whose
body is a nest of loops over indices that start from known constants: the
outer loop re-enters the nest in a new state each time (nginx's
`ngx_resolver_report_srv`, 106 lines, CCM 19, never finishes at 200,000).

Say which of these you found and which component it feeds. "CCM is 152" is
a size, not a diagnosis.

## Step 6: Decide and measure

Two levers, both measurable:

**Raise the limit.** `--paths <N> --print-paths` on a copy of the **whole
project** (Step 2 says why not `--tu`), stdout redirected as in Step 2.
The log then says how many paths each function actually needed
(`setup_env`: 6003): `pathout_report.py --dir <copy>` reads it, or `grep
'Pathed out\|PATHOUT=1'`. Then compare defects
between the default and the raised run with `cov-format-errors
--json-output-v10` on each idir copy: same set, or new findings? That
difference *is* the cost of the notice, measured. For `setup_env`: none.
For all of nginx at 50,000: none, and two functions still did not finish.

**Restructure.** Name the seams. A function that does five things in
sequence with independent state is five functions; a re-tested expression
is one local; a loop nest that the outer loop re-enters is a helper. The
metrics (`ml`, `lc`) and the `declared at:` line give the reader the place.
Do not recommend touching logging macros or loops unless Step 5 showed they
contribute. **Try the edit on the slice** before recommending it: change
`<name>.slice.c`, re-run `slice_function.py --emit --analyze`, and report
the path count it produced rather than the one you expected
(`ngx_resolver_report_srv`: 5001 unchanged with either inner construct
removed, **64** with the loop body moved into a helper).

Raising `--paths` globally is legitimate -- the log itself says up to 5% of
functions normally hit the limit -- but it is paid on every function on
every run, and it is not a remedy for a function that does not respond to
the limit (a real case still pathed out at 200,001). Prefer a value the
measurement justifies and say what it cost in time.

## Reporting

Verdict first (rule 21): the functions, the checker that pathed out in
each, what the shape catalogue found behind them (survivors, with verdict
and tier), the structural cause, what the limit cost in defects (measured
or "not measured"), and the recommendation with its price. Then the
evidence: the log lines, the `Pathed out` lines, the filter's counts, the
counts from the body, the defect diff. Mark measured vs reasoned (rule 23).
Say which PATHOUT functions you did *not* take past Step 1, whether the
catalogue was run, and, on a large log, what the pilot cost and what the
user chose to spend (rule 22).

## Anti-patterns

- Diagnosing from cyclomatic complexity, APC, or the source-level shape
  alone. The fixture disproves each one.
- Working every PATHOUT function on a large log without a pilot and a
  confirmed budget. Steps 4-6 are per function; the user decides how many
  functions, after seeing what one costs.
- Skipping the shape catalogue because "nothing has escaped". Nothing has
  escaped *yet*; the catalogue is how you find out. A blind run of this
  skill on nginx did exactly that, and the two survivors it would have
  found (an array indexed by an uncompared variable in
  `ngx_http_ssi_body_filter`, where `OVERRUN_SYMBOLIC` pathed out) went
  unread.
- Using `--tu` scoping for the PATHOUT set or the cost measurement. It
  drops cross-TU models and lost 7 of 18 on nginx.
- Raising `--paths` as the answer to an escaped defect. The checker that
  missed it may not finish at any limit.
- Parsing `cov-preprocess` / `--preprocess-native` output to find a
  function. The AST is one command away.
- Using a different Coverity version than the one that wrote the idir.
- Re-running `cov-analyze` into the only copy of the idir and losing the
  original log.
- Reading batch lines as "there is no function name to be had". There is;
  it is behind `--print-paths`.
- Opening a `--print-paths` log or its console output whole. It is
  hundreds of thousands of lines; the tools and `grep` read it, and a
  targeted `grep` is how to look when you need to.
- Reporting `paths_exceeded count: 0` as "no PATHOUT ever" when the user's
  notice came from a run with more checkers enabled.

## Where other skills take over

| Question | Skill |
|---|---|
| The function's body, a file that compiles alone, an obfuscated twin | `coverity-function-slice` |
| A survivor reading cannot settle: run it | `coverity-fuzz-triage` |
| "Was the function even captured?" / the file is not in the emit | `coverity` (capture fidelity, rule 34) |
| "Would checker X have found the bug the cut-off hid?" | `coverity-defect-detectability` |
| The idir is from a version you do not have installed | stop and ask. This skill is for current development, where the version that wrote the idir (`emit/version`, line 1) is installable; say which version is needed and let the user install it or re-run the capture. `coverity-recreate-from-emit` rebuilds an analyzable idir without the toolchain and is expensive; it is a last resort the user must ask for, not a step to take on your own |

The three skills are meant to sit side by side under the same skills
directory; the relative paths above assume that.

## Layout

```
coverity-pathout/
├── SKILL.md
├── README.md
├── CALIBRATION.md                       # what was measured, on what, and what was not
├── references/
│   ├── analysis-log.md                  # the four kinds of line, batches, --print-paths
│   ├── path-explosion.md                # paths x state, the fixture evidence, which checkers
│   ├── worked-example-setup-env.md      # proftpd, end to end, with the defect diff
│   ├── escape-hunt.md                   # shape checker -> PATHOUT filter -> read -> confirm; the measurements
│   └── candidate-checkers.md            # writing a path-insensitive CodeXM checker; the traps
├── tools/
│   ├── pathout_report.py                # log + metrics join, optional AST extraction
│   └── pathout_filter.py                # keep candidates in PATHOUT functions (--relevant auto / <checkers>)
└── evals/
    ├── fixture.sh                       # builds, analyzes and checks the fixture; runs the shape checker
    ├── evals.json
    ├── fixtures/
    │   └── ifs_known_vs_unknown.c       # same CFG, one explodes, one does not
    └── escape-hunt/
        ├── null_check_then_deref.cxm    # the tested shape checker (also in the pathout-shapes catalogue)
        └── shape.c                      # the shape and its three nearest non-shapes
```
