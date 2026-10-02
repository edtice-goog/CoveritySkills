---
name: coverity-verify
description: >
  Verify a Coverity finding by execution: confirm or refute it by running
  it, instead of by reading it. Verification is the general capability;
  fuzzing the function under stubs from Coverity's own derived models is
  its first method and the only one built so far, and payload delivery
  for injection classes (SQLI, OS_CMD_INJECTION, PATH_MANIPULATION) is the
  seam for the next. Formerly coverity-fuzz-triage, which remains as an
  alias. The finding may be a Connect CID ("verify CID 12345"), an entry in a
  cov-format-errors findings file, or a candidate from a path-insensitive
  shape checker. Use this skill for "verify this finding", "verification",
  "run the verify skill", "is this defect real", "triage these findings",
  "confirm the candidates", "can this null actually arrive", "fuzz this
  function", "verify the report before I file it", "give me execution
  verdicts", and for the question behind them all: whether an analyzer
  claim about one function is reachable in execution. Method 1, fuzz
  under model stubs: the function as a standalone file (coverity-function-slice), a stub for
  every callee generated from Coverity's OWN derived model of it
  (cov-find-function --save, so the callees behave exactly as the analyzer
  believed they do), a libFuzzer harness whose one input chooses both the
  arguments and every stub behaviour, the finding's own claim checked and
  counted at its line, and a sanitizer as the oracle. A crash at the
  finding's line, with the stub choices that produced it, is a
  confirmation the analyzer would have accepted -- and those choices are
  the list of callee behaviours to check against the real callees, which
  is where most of the false positives in a real batch were settled. Ten
  proftpd findings went through it: none confirmed, eight refuted with
  execution evidence, and one real overflow found next to a false one.
  Requires the Coverity installation that wrote the intermediate
  directory and clang with libFuzzer and AddressSanitizer: under WSL for
  an idir captured on Linux (LP64 and glibc, like the capture), clang-cl
  on Windows for one captured with MSVC.
---

# Coverity verify

A finding is a claim: *some path reaches this line in this state*. The
analyzer reported it under a bound on its own work; a fuzzer can settle it
by reaching the line. This skill turns one finding into an executable
question and lets execution answer it. **It is the verification stage**,
and execution-based verification is the general capability: a Connect CID
a user hands over, a batch from a findings file, or the candidates
`coverity-pathout` collects from functions that reached the path bound are
all the same input once Step 0 has named the claim. Fuzzing is one method
of it, the one built so far; for an injection finding the method is
delivering the payload (see *Methods*). On a real batch the fuzz method
was better than a reading triage in one specific way: every refutation
came with the behaviour the analyzer had assumed, and one real defect came
out beside a false one.

This skill was `coverity-fuzz-triage`; that directory is now an alias
pointing here.

Read `coverity/RULES.md` first (rules 3, 21-23, 35).

**This skill is one of a bundle of three** in the CoveritySkills
repository. It needs `coverity-function-slice` beside it (Step 1 calls its
slicer by relative path) and is called by `coverity-pathout` for the
candidates it collects from functions the analyzer did not finish. If you
have only this file, clone the repository and work from the clone:

```bash
git clone https://github.com/edtice-goog/CoveritySkills
```

## Methods

A verification method is a way to make the finding's claim executable and
observe whether it holds. Step 0 is shared: it names the claim, the line,
and the blamed callee or source. What differs is how the claim is reached.

| method | for | status |
|---|---|---|
| **1. Fuzz under model stubs** (Steps 1-4 below) | claims about one function's own state: null dereference, overrun, divide by zero, use after free, uninitialised use, a candidate from the shape catalogue. The function runs alone, callees behave as the analyzer's models say, the input drives everything | built; measured on ten proftpd findings and the fixture |
| **2. Payload delivery** | injection classes (SQLI, OS_CMD_INJECTION, PATH_MANIPULATION, XSS, TAINTED_STRING sinks): the claim is that untrusted data reaches a sink unneutralised, which a slice cannot show and a payload can. Verification is building the input the events describe, delivering it through the real entry point (or the request handler the finding's path starts at), and observing the sink: a marker in the query log, a file outside the root, a command that ran | not built. The seam: Step 0 names the source, the sink and the claim the same way; Steps 1-3 are replaced by "build the payload from the events, deliver it, instrument the sink"; Step 4's tiers apply with *reached the sink unneutralised* as the confirmation and *neutralised at line N* as the refutation |

Everything from here to Step 4 is method 1.

## What makes method 1 honest

Four things, and each one is the answer to a way this could lie:

- **The stubs are the analyzer's models, not guesses.** Coverity has
  already derived, for every function it analyzed, what it believes that
  function does. A stub written from that model can only take behaviours
  the analyzer already granted the callee, so a crash through the stub is
  a path the analyzer would have accepted as feasible. A hand-written stub
  that returns NULL where the real callee never can confirms nothing.
- **One input chooses everything, and every choice is traced.** The fuzz
  input feeds the target's arguments *and* every stub's branch choice, and
  the run prints the choices behind a crash. Those are the callee
  behaviours the confirmation relies on. On proftpd every "confirmation"
  relied on one that the real callee cannot have (a copy that does not
  equal its source; a loader that does not write the global it loads
  into), because the model over-approximates or is silent. The trace is
  what makes that checkable.
- **The finding's claim is checked at its own line, and counted.** A run
  that reaches the line 300,000 times and never finds the claim false is
  evidence, not silence; a run that never reaches the line is not.
- **Values the harness supplies get their own tiers.** A harness can hand
  NULL to any parameter, any global, and make any function-pointer hook
  return. Those are reported as *parameter-sourced*, *global-sourced*,
  *hook-sourced*, never as confirmed.

## Step 0: Pin the installation, the platform, and the claim

**From a CID.** A real user hands over a Connect CID, not a findings file.
The CID lives in Connect; the events live in the intermediate directory
that produced the stream's snapshot. Two commands bridge them:

```bash
python3 tools/cid_lookup.py lookup --url <connect-url> --cid 12345 --stream <stream>     # key: ~/.coverity/ak-<host>-<port>
$BIN/cov-format-errors --dir <the idir behind that snapshot> --json-output-v10 findings.json
python3 tools/cid_lookup.py select --findings findings.json --merge-key <from lookup>
```

`lookup` asks Connect over REST (HTTP Basic with an authentication key,
exactly as the `coverity` skill's *Connecting to Coverity Connect*
describes: key under `~/.coverity/`, never in a repository; URL from the
user, never from the key; check the key first with `connect_auth.py
check`) for the stream, checker, file, function, line and **merge key** of
the CID in a snapshot. `select` finds the same issue in the idir's own
findings by merge key (stable across runs, rule 27) and prints the events.
The idir is the one the user analyzed and committed; if only Connect has
the snapshot, re-analyze the same capture with the same version and
options (`cov-format-errors` reads an idir, not a server). From here on a
CID is a findings-file entry.

`<idir>/emit/version` line 1 names the Coverity version; use its `bin/`
(rule 3). The build platform follows the capture: an idir captured under
Linux or WSL is built and fuzzed **under WSL** (`clang -fsanitize=fuzzer,
address`; the slice's types are LP64 and its libc is glibc, and clang-cl
would silently change `long` to 4 bytes and lose `__errno_location`); an
MSVC capture uses clang-cl on Windows. Then, per finding, write down
before building anything:

| from | you need |
|---|---|
| the finding (a CID via `cid_lookup.py`, a `cov-format-errors --json-output-v10` entry, or the shape checker's candidate) | the function, the TU, and the **claim as a C expression that must hold** at the finding's line: `ptr != NULL` before `*ptr = 0`; `delay_tab.dt_data != NULL` before the `memcpy`; for an OVERRUN, `1` (a reach counter; ASan is the oracle) |
| the events | the callee the finding **blames** (the one whose return or effect makes the claim false) and the branches the analyzer took; a seed input that follows them |
| the checker | the oracle: ASan for dereferences, overruns and use-after-free; the claim check for anything that does not crash (`REVERSE_INULL`: the analyzer's claim is "never NULL at the check", so `arg != NULL` before the check) |

Read the function once. A refutation by reading is a verdict too, and it
is cheaper than a build. But when the user asks for execution verdicts, or
says the run is a test of the skill, build.

## Step 1 (method 1): The target as a file

```bash
python3 ../coverity-function-slice/tools/slice_function.py --dir <idir> --bin $BIN --tu <N> --name <fn> --out <work>/<fn> --emit
```

`<fn>.slice.c` is the function with every typedef, struct, global and
callee prototype it needs, printed from the emit. `cov-emit: emitted` is
the check; `NOT EMITTED` means a pretty-printer form to hand-edit first
(`coverity-function-slice`, Step 2: dropped cast parentheses, a VLA
printed as `char a[]` with its dimension in a comment).

## Step 2 (method 1): Models for every callee

```bash
$BIN/cov-find-function --dir <idir> --save -of <work>/models --module generic <callee>   # per callee, ~3 s
```

Do it for every project callee the slice's `/* callees */` block lists,
and keep an `index.txt` of `name <key>.generic defs=N` lines (the
assembler reads it; a callee with several definitions lists one model per
definition, pick by source file). libc names are left to the real
library. `--save` writes `<key>.generic.dot`, an automaton whose edges are
what the analyzer derived: `returnsnull`, `<return value> <- == -1`,
`negative_return`, `identity(<arg 1>)`, `afm_alloc(...)`, `dereference(<arg
0>)`, `write(<arg 0>->last)`.

Two things the generic model does not carry, and they decided four of ten
proftpd findings: **it never says a copy equals its source** (`pstrdup`'s
model is "allocates, may return null"), and **it records no writes to
globals** (`delay_table_load` mmaps into `delay_tab.dt_data`; the model
has no edge for it). The first is answered by `--semantic`; the second is
the *model gap* verdict below.

## Step 3 (method 1): Assemble, build, run -- focused first, then free

```bash
python3 tools/fz_target.py --slice <fn>.slice.c --models <work>/models --harness harness.c \
    --claim '<expr>' --before '<regex of the finding line in the slice>' \
    --pin-normal --free <blamed callee>[,..] [--semantic pstrdup,pstrcat] --out target.c
clang -g -O1 -fsanitize=fuzzer,address -Wno-everything -I tools target.c -o fz     # WSL; clang-cl -fsanitize=fuzzer,address -Zi -Od on Windows
./fz -max_total_time=60 -seed=1 -detect_leaks=0 -timeout=10 [seeds/]
```

`fz_target.py` classifies every callee (real libc / model stub with its
behaviours listed by index / `NO MODEL` generic stub), inserts
`__fz_claim(<expr>)` before the first line matching `--before`, and
appends the harness. `tools/fz_support.h` supplies the byte stream, the
choice trace, the pins, the per-input arena and the claim counter.

- **Focused mode** (`--pin-normal`) holds every stub to its normal
  behaviour (non-null, allocating, zero or positive return) and leaves only
  the `--free` callees fuzz-driven. This is the run that answers the
  question: without it, every proftpd run ended on a *bycatch* -- some
  pool allocator's `returnsnull` edge, unchecked by the code, crashing at
  `c->argv[0]` before the finding's line was ever reached. Three in a row
  on one function.
- **Free mode** (no `--pin-normal`) is the bycatch run: what else the
  models allow. It found a real one-byte stack overflow next to a false
  OVERRUN in `glob_limited`, in a branch Coverity had not reported.
- **`--semantic`** gives named copy/alloc helpers their real semantics
  (`pstrdup`, `pstrndup`, `pstrcat`, `palloc`, `pcalloc`), because a stub
  that returns an unrelated buffer where the code copied a string
  confirms claims the callee cannot produce.
- **Seeds**: put an input that follows the analyzer's events in `seeds/`
  (a `"syslog:"` prefix took the finding's line from once in 7,617 inputs
  to hundreds of thousands of times).

The harness is per target; `evals/harness.c` and the proftpd ones in the
calibration are the pattern: `FZ_BEGIN(data, size); FZ_PINS_DEFAULT();`,
then define every global the slice declares `extern`, then build the
arguments -- scalars from `fz_take()`, strings from `fz_string()`, pointer
parameters from `__stub_object(64)` (memory filled with pointers to
itself, so every field points somewhere valid; set the **integer fields
that bound loops** yourself, they read as large values), and a choice byte
only where the finding is about the parameter, the global or the hook
itself.

## Step 4: Read the run and give the verdict its tier

| verdict | meaning |
|---|---|
| **refuted by reading** | the finding's variable is reassigned, asserted, or otherwise guarded in a way the analyzer did not see; say what |
| **refuted by execution** | focused run: the finding's line reached N times, the claim never false, with real libc semantics or `--semantic` copies where the claim depended on them. Evidence, not proof: say N and the budget |
| **refuted by execution, a path the analyzer missed** | the claim was false at the line in a way that refutes the *finding* (REVERSE_INULL on `dolist`: the check is reachable with `arg == NULL`, so it is not redundant) |
| **model says impossible** | no callee model on the path has an edge that produces the bad value; needs no build |
| **confirmed by crash under model stubs** | the claim was false at the line; **list the stub choices**, then check each against the real callee. Only when every behaviour relied on is one the real callee has is this a defect |
| **model over-approximates the callee** | the crash relied on a stub behaviour the real callee cannot have (a copy without its source's slash). Refuted; `--semantic` or a user model closes it |
| **model gap** | the crash relied on the model's silence: a global the callee writes and the model does not record (`session.d`, `delay_tab.dt_data`). Refuted for the finding; the gap is the analyzer's false positive too, and a user model fixes both |
| **parameter-, global-, hook-sourced** | the harness supplied the NULL (a parameter, `main_server`, `tpl_hook.fatal` returning). A question about callers and configuration, not this function |
| **unconfirmed after N seconds** | the line was reached but not often, or not at all; say which. Not a refutation |
| **bycatch** | a crash elsewhere in the function under a model-permitted behaviour (an unchecked `returnsnull`, an overflow in another branch). Report it separately; it may be real |

For a confirmed finding the reproduction is the crashing input plus the
stub choices, and the thing to check against the real callees is the list
of behaviours those choices selected. For a refuted one the reason and
the reach count are the deliverable.

## Reporting

Per finding: the claim, the verdict with its tier, and the evidence line
(reach count and inputs; the crash frame and input with the stub choices;
the model edge that is missing; the source line that refutes it). Then
the totals: how many confirmed, refuted by execution, refuted by reading,
model gaps, sourced-by-harness, unconfirmed under what budget, bycatch,
and how many were not taken past Step 0 (rule 22). Mark measured vs
reasoned (rule 23).

## Anti-patterns

- Hand-writing stubs that return NULL or garbage. A stub is the analyzer's
  belief about the callee, printed from its model, or it proves nothing.
- Guarding a stub's dereference (`if (a0) *a0`). It makes the callee look
  null-safe to the analyzer and hides the finding's consequence from the
  fuzzer; measured to make a real finding vanish.
- Reporting a crash as confirmed without reading the stub choices behind
  it. Every proftpd "confirmation" fell to that step.
- Counting a crash on a parameter, global or hook the harness itself set
  as a confirmation.
- Running free mode first and reading its first crash as the answer. It
  is a bycatch until the focused run has reached the finding's line.
- Building a Linux capture's slice with clang-cl. LP64 becomes LLP64 and
  glibc becomes MSVCRT; the numbers are about a different program.
- Reporting "no crash in 60 seconds" without the reach count.
- Using a different Coverity version than the one that wrote the idir for
  `cov-find-function`; the models are per emit.

## Where other skills take over

| Question | Skill |
|---|---|
| The finding is a candidate from a function that reached the path bound, or you need the candidate list | `coverity-pathout` |
| The slice does not emit, or the target is a C++ method | `coverity-function-slice` |
| "Would checker X have found this at all?" | `coverity-defect-detectability` |

## Layout

```
coverity-verify/                         # formerly coverity-fuzz-triage; that directory is an alias stub
├── SKILL.md
├── README.md
├── CALIBRATION.md                       # what was measured, on what, and what was not
├── references/
│   └── fuzz-confirmation.md             # models as stubs, the harness, the proftpd batch, verdict tiers, what is not built
├── tools/
│   ├── cid_lookup.py                    # a Connect CID -> stream, checker, file, function, merge key; then the idir's events
│   ├── model_stubs.py                   # a callee stub from its cov-find-function model
│   ├── fz_target.py                     # slice + models + harness -> target.c; focused/free, --semantic, claim insertion
│   └── fz_support.h                     # byte stream, choice trace, pins, arena, pointer-filled objects, __fz_claim
└── evals/
    ├── run.sh                           # candidate -> slice -> model stub -> fuzz, on the fixture, about a minute
    ├── evals.json
    ├── lookup.c, use.c                  # a callee with a derived model, a caller with an unguarded dereference
    └── harness.c                        # the harness pattern
```
