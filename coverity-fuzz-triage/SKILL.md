---
name: coverity-fuzz-triage
description: >
  Confirm or refute a Coverity finding -- or a candidate from a
  path-insensitive shape checker -- by running the function, instead of by
  reading it. Use this skill for "is this defect real", "triage these
  findings", "confirm the candidates", "can this null actually arrive",
  "fuzz this function", "verify the report before I file it", and for the
  question behind them all: whether an analyzer claim about one function is
  reachable in execution. The recipe: the function as a standalone file
  (coverity-function-slice), a stub for every callee generated from
  Coverity's OWN derived model of it (cov-find-function --save, so the
  callees behave exactly as the analyzer believed they do), a libFuzzer
  harness whose one input chooses both the arguments and every stub
  behaviour, and a sanitizer or a finding-derived assertion as the oracle.
  A crash at the finding's line, with the stub choices that produced it, is
  a confirmation the analyzer would have accepted; a callee model with no
  edge that can produce the bad value is a refutation in the analyzer's
  own terms. Requires the Coverity installation that wrote the intermediate
  directory and a clang with libFuzzer and AddressSanitizer (clang-cl from
  LLVM on Windows works).
---

# Coverity fuzz triage

A finding is a claim: *some path reaches this line in this state*. The
analyzer could not, or did not, prove it; a fuzzer can settle it by
reaching the line. This skill turns one finding into an executable
question and lets execution answer it. It is the confirmation stage of the
PATHOUT escape hunt (`coverity-pathout`), and it stands on its own for
ordinary triage: a batch of findings in, a verdict with evidence per
finding out.

Read `coverity/RULES.md` first (rules 3, 21-23, 35).

## What makes it honest

Three things, and each one is the answer to a way this could lie:

- **The stubs are the analyzer's models, not guesses.** Coverity has
  already derived, for every function it analyzed, what it believes that
  function does. A stub written from that model can only take behaviours
  the analyzer already granted the callee, so a crash through the stub is
  a path the analyzer would have accepted as feasible. A hand-written stub
  that returns NULL where the real callee never can confirms nothing.
- **One input chooses everything.** The fuzz input feeds the target's
  arguments *and* every stub's branch choice, so the crashing input is a
  complete record of what the confirmation relied on.
- **Parameter-sourced values get their own tier.** A harness can hand
  NULL to any pointer parameter, which would confirm every dereference of
  a parameter. That is reported as *reachable only if a caller passes
  NULL*, never as confirmed.

## Step 0: Pin the installation and name the target

`<idir>/emit/version` line 1 names the Coverity version; use its `bin/`
(rule 3). Then, per finding, write down three things before building
anything:

| from | you need |
|---|---|
| the finding (`cov-format-errors --json-output-v10`, or the shape checker's candidate) | the function, the TU, the main event's line, and the claim (null dereference of `r`; overrun of `buf` by `n`; divide by `n`) |
| the events | the callees on the path from the function's entry to that line, because each needs a stub, and the analyzer's own path is the seed for the fuzzer |
| the checker | the oracle: ASan for dereferences, overruns and use-after-free; an assertion for claims that do not crash (`REVERSE_INULL`, `DEADCODE`, `RESOURCE_LEAK` on Windows, where LeakSanitizer is unavailable) |

Read the function once before fuzzing it. On the PATHOUT hunt, every one
of 27 candidates fell to reading (preconditions, allocate-if-null macros,
invariants between variables, reassignment; the catalogue is in
`coverity-pathout/references/escape-hunt.md`). Reading is cheaper than a
build, and a refutation by reading is a verdict too.

## Step 1: The target as a file

```bash
python3 ../coverity-function-slice/tools/slice_function.py --dir <idir> --bin $BIN --tu <N> --name <fn> --out <work>/slice --emit
```

`<fn>.slice.c` is the function with every typedef, struct, global and
callee prototype it needs, printed from the emit. Its callees are
prototypes: that is what Step 2 fills in. `cov-emit: emitted` with no
recoverable errors is the check; `NOT EMITTED` means fix the slice first
(`coverity-function-slice`, Step 2).

## Step 2: Stubs from the derived models

For every callee on the finding's path (both ends of a chain: on
subversion, the null came out of `svn_dirent_skip_ancestor` and was
dereferenced inside `relpath_depth`, and the finding only came back with
both stubbed):

```bash
$BIN/cov-find-function --dir <idir> --save -of <work>/models --module generic <callee>
python3 tools/model_stubs.py '<prototype line from the slice>' <work>/models/<key>.generic.dot >> <work>/target.c
```

`--save` writes `<key>.generic.dot`, an automaton whose edge labels are the
behaviours the analyzer derived: `returnsnull(<return value>)`, `<return
value> <- != 0`, `identity(<arg 1>)`, `afm_alloc(<return value>)`,
`dereference(<arg 0>)`, `write(<arg 0>->x)`, `escape`/`noescape`. A quarter
of a second per callee; when a name has several definitions the output
lists one model per definition with its source file, so pick by file.
`model_stubs.py` prints one branch per distinct behaviour path, selected
by `__stub_choice(n)`; `returnsnull` returns 0, `identity` returns the
argument, `afm_alloc` allocates, an unconstrained non-null return hands
out a static object, and every `dereference(<arg N>)` edge becomes an
**unconditional** dereference of that argument -- unconditional so that a
null handed to a callee that the model says dereferences it crashes there,
which is the finding's consequence when it lives in the callee.

A callee whose model has **no** edge that can produce the bad value (no
`returnsnull`, say) is worth reporting on its own: the analyzer's own
knowledge says the value cannot arrive from there. That is the *model
says impossible* verdict, and it needs no build.

## Step 3: Harness and oracle

`evals/harness.c` is the pattern. One byte stream feeds everything:

```c
static const uint8_t *cur; static size_t left;
static int take(void) { if (left == 0) return 0; left--; return *cur++; }
int __stub_nondet(void) { return take(); }            /* every stub choice */
void *__stub_alloc(int n) { return calloc(1, n > 0 ? n : 1); }
void *__stub_object(int n) { static char obj[4096]; return obj; }
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
  cur = data; left = size;
  int id = take(); int flag = take();                  /* the target's scalar arguments */
  (void)escaped(id, flag);
  return 0;
}
```

Adapt the argument block to the target's signature: scalars from `take()`,
buffers from the remaining bytes, pointer parameters either from
`__stub_object` (the normal case) or, when the finding is about the
parameter itself, from a choice byte -- and then the verdict is
parameter-sourced by construction (see the tiers).

The oracle: `-fsanitize=address` catches dereferences of null, overruns
and use-after-free. For a claim that does not crash, add an assertion at
the finding's line that states the claim's negation (`assert(p != NULL)`
before the dereference `REVERSE_INULL` says is unguarded; `assert(0)` in
the branch `DEADCODE` says is dead); a failed assertion is then the crash.
MemorySanitizer is not available on the Windows toolchain, so an
uninitialised-read claim needs another oracle or a Linux build.

```bash
clang-cl -fsanitize=fuzzer,address -Zi -Od target.c harness.c -Fe:fuzz.exe
./fuzz.exe -max_total_time=60
```

Two Windows facts, both measured: write the MSVC-style flags with a dash
(`-Zi`, `-Od`, `-Fe:`), because Git Bash rewrites `/Zi` into a path; and
put `LLVM\lib\clang\<ver>\lib\windows` on `PATH` or the binary exits with
127 before running, for want of `clang_rt.asan_dynamic-x86_64.dll`.

Seed the corpus with the analyzer's own path when you can: the events
say which branches were taken and which callee behaviours were assumed,
and a seed that encodes those choices reaches the line on the first
iteration when the claim is true.

## Step 4: Read the crash and give the verdict its tier

| verdict | meaning |
|---|---|
| **refuted by reading** | the finding's variable is reassigned, asserted, or otherwise guarded in a way the analyzer (or the shape checker) did not see; say what |
| **model says impossible** | no callee model on the path has an edge that produces the bad value; the analyzer's own knowledge refutes the claim |
| **confirmed by crash under model stubs** | the sanitizer or the assertion fired at the finding's line; record the input and the stub branches it took, since those are the callee behaviours the crash relies on, and all of them are in the analyzer's model of those callees |
| **reachable only if a caller passes NULL** (or an out-of-range argument) | the harness supplied the bad value to a parameter; whether any caller does is a question about the callers, not this function |
| **unconfirmed after N seconds** | nothing found under the budget; not a refutation. Say the budget and the seed |
| **model gap** | the crash needed a behaviour outside the model; feed it back as a user model (the enrichment loop), not as a confirmed defect |

For a confirmed finding the reproduction is the crashing input plus the
stub choices, and the thing to check against the real callees is the list
of behaviours those choices selected. For a refuted one the reason is the
deliverable.

## Reporting

Per finding: the claim, the verdict with its tier, and the evidence line
(the crash frame and input; the assertion; the model edge that is
missing; the source line that refutes it). Then the totals: how many
confirmed, refuted by reading, refuted by model, unconfirmed under what
budget, and how many were not taken past Step 0 (rule 22). Mark measured
vs reasoned (rule 23).

## Anti-patterns

- Hand-writing stubs that return NULL or garbage. A stub is the analyzer's
  belief about the callee, printed from its model, or it proves nothing.
- Guarding a stub's dereference (`if (a0) *a0`). It makes the callee look
  null-safe to the analyzer and hides the finding's consequence from the
  fuzzer; measured to make a real finding vanish.
- Counting a crash on a parameter the harness itself set to NULL as a
  confirmation.
- Fuzzing before reading. Twenty-seven of twenty-seven PATHOUT candidates
  on subversion were settled by reading.
- Reporting "no crash in 60 seconds" as "not a defect".
- Using a different Coverity version than the one that wrote the idir for
  `cov-find-function`; the models are per emit.

## Where other skills take over

| Question | Skill |
|---|---|
| The finding is a candidate from behind the path limit, or you need the candidate list | `coverity-pathout` |
| The slice does not emit, or the target is a C++ method | `coverity-function-slice` |
| "Would checker X have found this at all?" | `coverity-defect-detectability` |

## Layout

```
coverity-fuzz-triage/
├── SKILL.md
├── README.md
├── CALIBRATION.md                       # what was measured, on what, and what was not
├── references/
│   └── fuzz-confirmation.md             # models as stubs, the harness, Windows facts, verdict tiers, what is not built
├── tools/
│   └── model_stubs.py                   # a callee stub from its cov-find-function model
└── evals/
    ├── run.sh                           # candidate -> slice -> model stub -> fuzz, on the fixture, about a minute
    ├── evals.json
    ├── lookup.c, use.c                  # a callee with a derived model, a caller with an unguarded dereference
    └── harness.c                        # libFuzzer harness: one input feeds args and stub choices
```
