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
| 1 | a CodeXM checker for the shape, over the whole idir | 11 s, 503 hits (2,088 before the checker learned what "guarded" means) |
| 2 | keep only hits in PATHOUT functions | 115 hits (of 178 PATHOUT functions) |
| 3 | keep only where the relevant checker pathed out | **0** for `FORWARD_NULL`/`NULL_RETURNS`; 27 in 7 (function, variable) pairs when `REVERSE_INULL` is counted too |
| 4 | read them; then fuzz what reading cannot settle | the 27 took about an hour to read; all refuted |

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

Before writing one, look in the catalogue: https://github.com/edtice-goog/pathout-shapes
holds twelve tested shape checkers (each with a fixture and the components
whose path-out makes its hits relevant), and the escaped shape is often one
of them or a small variant.

Run it alone, so the output is only candidates:

```bash
cov-analyze --dir <idir-copy> --disable-default --codexm <shape>.cxm
cov-format-errors --dir <idir-copy> --json-output-v10 candidates.json
```

Exclude the known instance by location when reading the result; it will be
there, and it is not what you are looking for.

**When nothing has escaped yet** -- a PATHOUT is known and that is all --
there is no instance to derive a shape from, so run the whole catalogue in
one pass (`pathout-shapes/bin/run_all.sh <install>/bin <idir-copy> <outdir>`,
one `cov-analyze` with twelve `--codexm`) and let the filter apply each
checker's own relevance list (`--relevant auto`). The hit counts are
larger, the survivors after the relevance filter are not: every shape only
survives in functions where its own checker was cut off.

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
path sensitivity. On subversion that one filter took 115 down to 0. Name
the checkers that would have reported the escaped defect; for a
check-then-dereference shape that is `FORWARD_NULL` and `NULL_RETURNS`.
`REVERSE_INULL` is the opposite shape (dereference, then test), but since
the shape checker is order-blind it finds that shape too, so counting
`REVERSE_INULL` as relevant is a legitimate second pass; on subversion it
yields 27 more candidates in 7 (function, variable) pairs.

Two things the filter does not do, and says so: it keeps every candidate in
a relevant function even though the checker did explore ~5,000 paths there
before stopping, so some of them were in fact examined; and it does not yet
pull in callers of functions whose *derivers* pathed out, although a
truncated model weakens every caller.

## Stage 4: confirm or refute

**Read first.** Every subversion candidate was settled by reading, and the
reasons are the catalogue of what a path-insensitive checker cannot know:

| refuted by | example |
|---|---|
| reassignment between test and use | `bufpt` in `sqlite3_str_vappendf`: null-tested where it came from `printfTempBuf`, dereferenced where it had just been assigned a stack array |
| the function's own precondition | `parent_node` in `write_entry`: dereferenced unguarded under three `switch` cases, but `WRITE_ENTRY_ASSERT(parent_node \|\| entry->schedule == svn_wc_schedule_normal)` at the top says a null parent only arrives with the fourth. (The first reading missed the assertion and called this one real; the checker, which treats an assertion as an exit guard, had already dropped it.) |
| allocate-if-null | `actual_node = MAYBE_ALLOC(actual_node, pool)` then `actual_node->x`: the macro is `(x) ? (x) : apr_pcalloc(...)`, so the test the checker saw is the allocation |
| an invariant between two variables | `left_dirent`/`right_dirent` in `inner_dir_diff`: both come from hashes whose key union is being iterated, so they cannot both be null; `pUsing` in `selectExpander` is set whenever `fg.isUsing` is; `pTab` in `lookupName` is asserted |
| a loop-condition guard | `for (i = 0; moved_nodes && i < moved_nodes->nelts; i++)`: at the time the checker knew `if`, `?:`, `&&` and `\|\|` as guards, not loop conditions (it does now: `whileLoop` and `forLoopSimple` conditions guard their bodies) |
| two variables with one name | `t_entry` in `delta_dirs`, `work` in `write_entry`: an inner declaration shadows the tested one; the front end had no mangled name for the locals, so the identifier fallback conflated them |

The last one is a checker gap, recorded in `candidate-checkers.md`; the loop-condition gap was closed the same day. The
first four are what reading is for. Do it before building anything: it
took about an hour for 27 candidates, and left nothing to fuzz.

**Then fuzz what reading cannot settle.** The slice makes the function
executable on its own, the derived models make its callees behave exactly
as the analyzer believes they do, and a sanitizer is the oracle. A crash at
the candidate's dereference, reached through a stub taking its
`returnsnull` branch, is the confirmation; the analyzer would have accepted
that path as feasible had it reached it. `coverity-fuzz-triage/references/fuzz-confirmation.md`
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
