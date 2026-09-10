# When a defect escaped: hunting its siblings behind the path limit

A later stage found a defect (a fuzzer, a pen test, a customer) that static
analysis should have caught, and the diagnosis is that the function pathed
out: the checker that would have reported it was cut off at the path limit.
Raising the limit does not help. A function with a few hundred independent
decisions in a straight line has more states than any limit, and `--paths
200000` on a real case still pathed out, at 200,001.

The question worth answering is not "why was this one missed" -- that is
known -- but **where else in this codebase is the same shape hiding behind
the same limit.** This page is the procedure. It was run end to end against
subversion (9,533 functions) and against a fixture; the numbers below are
from those runs (`CALIBRATION.md`).

## The idea

Coverity's checkers are path-sensitive on purpose; that is what keeps them
quiet. Write a **path-insensitive** checker for the *shape* of the escaped
defect, run it over the **whole** intermediate directory, and then throw
away every hit except the ones inside PATHOUT functions where the relevant
native checker was cut off. Outside those functions the path-sensitive
checker finished, looked at the same code, and was right to say nothing.
Inside them nobody looked. What survives is a short list of candidates, and
candidates are **confirmed or refuted by execution**, not believed.

| stage | what | cost, subversion |
|---|---|---|
| 1 | a CodeXM checker for the shape, over the whole idir | 13 s, 2,088 hits in 442 functions |
| 2 | keep only hits in PATHOUT functions | 815 hits in 75 functions (of 178 PATHOUT) |
| 3 | keep only where the relevant checker pathed out | **1** candidate |
| 4 | read it; then fuzz what reading cannot settle | minutes per candidate |

The whole-idir run is cheap because the checker is structural. The
filtering is the mechanism. Slicing is not needed for detection at all; it
comes back at stage 4 as the fuzz target.

## Stage 1: the shape, as a path-insensitive checker

Derive the shape from the escaped instance, not from the defect class.
"FORWARD_NULL" is a class; "a pointer null-tested in an `if`, then
dereferenced outside that `if`, with the guard closing one statement too
early" is a shape, and it is what the checker looks for. Write it to match
the shape wherever it occurs and to reason about nothing: no feasibility,
no ordering, no reassignment. It will be noisy. That is the contract; the
filter and the confirmation stage are what make the noise affordable.

`references/candidate-checkers.md` is the CodeXM how-to, with the checker
written for this shape as the worked example (`evals/escape-hunt/
null_check_then_deref.cxm`) and the language gotchas that cost time.

Run it alone, so the output is only candidates:

```bash
cov-analyze --dir <idir-copy> --disable-default --codexm <shape>.cxm
cov-format-errors --dir <idir-copy> --json-output-v10 candidates.json
```

Exclude the known instance by location when reading the result; it will be
there, and it is not what you are looking for.

## Stage 2 and 3: filter to where nobody looked

The PATHOUT set comes from a `--print-paths` run of the same idir with the
**original** options (`references/analysis-log.md`; on a large project the
plain log names almost none of them). Its `Pathed out` lines carry the
function *and* the checker that was cut off in it.

```bash
python3 tools/pathout_filter.py --findings candidates.json --log <print-paths idir>/output/analysis-log.txt \
    --relevant FORWARD_NULL,NULL_RETURNS --json survivors.json
```

`--relevant` is the step that matters most. A candidate for a null
dereference in a function where only `BUFFER_SIZE` pathed out is not a
candidate: `FORWARD_NULL` finished that function and rejected it with full
path sensitivity. On subversion that one filter took 815 down to 1. Name
the checkers that would have reported the escaped defect; for a
check-then-dereference shape that is `FORWARD_NULL` and `NULL_RETURNS`, and
not `REVERSE_INULL`, which is the opposite shape.

Two things the filter does not do, and says so: it keeps every candidate in
a relevant function even though the checker did explore ~5,000 paths there
before stopping, so some of them were in fact examined; and it does not yet
pull in callers of functions whose *derivers* pathed out, although a
truncated model weakens every caller.

## Stage 4: confirm or refute

**Read first.** The subversion survivor, `bufpt` in `sqlite3_str_vappendf`,
is null-tested in some `switch` cases and dereferenced in another where it
had just been assigned a stack array. Same variable, different definition;
a path-insensitive checker cannot see the reassignment, and a reader
refutes it in under a minute. Do that before building anything.

**Then fuzz what reading cannot settle.** The slice makes the function
executable on its own, the derived models make its callees behave exactly
as the analyzer believes they do, and a sanitizer is the oracle. A crash at
the candidate's dereference, reached through a stub taking its
`returnsnull` branch, is the confirmation; the analyzer would have accepted
that path as feasible had it reached it. `references/fuzz-confirmation.md`
has the recipe, the verdict tiers, and the fixture where the whole chain
runs in about a minute: candidate flagged, sliced, stubbed from the model,
built with clang-cl and ASan, crashing at the right line on a four-byte
input.

## What to hand back

- The shape, as a checker file, because the next escape of the same class
  reuses it.
- The survivor list with, per candidate: function, line, the checker that
  pathed out there, and the verdict with its tier (`refuted by reading`,
  `confirmed by crash under model stubs`, `unconfirmed after N seconds`,
  `reachable only if a caller passes NULL`).
- For confirmed ones, the crashing input and the stub choices it made:
  that is the reproduction, and the callee behaviours it relied on are the
  thing to check against the real callees.

## Limits

- The shape checker is order-blind (CodeXM's `sourceloc` exposes nothing)
  and reassignment-blind. Both are by design; both are why reading comes
  before fuzzing.
- A stub is the analyzer's belief about a callee. A crash that needs a
  behaviour the model does not have is a model gap, not a confirmed
  defect, and belongs to the enrichment loop.
- Sanitizers catch crashes. A shape whose consequence does not crash
  (`REVERSE_INULL`, `DEADCODE`) needs an assertion derived from the
  finding as its oracle.
