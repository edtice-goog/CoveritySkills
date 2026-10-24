# Behind the path bound: examining the residue, with or without a later-stage finding

A later stage (a fuzzer, a pen test, a customer) found a defect in a
function that pathed out: the checker that would have reported it reached
the per-function path bound in that function and stopped, as designed.
Raising the bound does not help. A function with a few hundred independent
decisions in a straight line has more states than any bound, and `--paths
200000` on a real case still pathed out, at 200,001.

The question worth answering is not "why was this one not reported" --
that is known, and it is the trade that makes the analyzer scale -- but
**where else in this codebase does the same shape sit behind the same
bound.** This page is the procedure, and it applies equally when no later
stage has reported anything yet: the residue behind the bound is worth
examining now that finding and chaining it no longer takes scarce expert
attention. It was run end to end against subversion (9,533 functions) and
against a fixture; the numbers below are from those runs
(`CALIBRATION.md`).

## The idea

Coverity's checkers are path-sensitive on purpose; that is what keeps them
quiet. Write a **path-insensitive** checker for the *shape* of the defect,
run it over the **whole** intermediate directory, and then throw away every
hit except the ones inside PATHOUT functions where the relevant native
checker reached the bound. Outside those functions the path-sensitive
checker finished, looked at the same code, and its silence is a verdict.
Inside them its verdict is "not examined". What survives is a short list of
candidates, and candidates are **confirmed or refuted by execution**, not
believed.

| stage | what | cost, subversion |
|---|---|---|
| 1 | a CodeXM checker for the shape, over the whole idir | 11 s, 503 hits (2,088 before the checker learned what "guarded" means) |
| 2 | keep only hits in PATHOUT functions | 115 hits (of 178 PATHOUT functions) |
| 3 | keep only where the relevant checker pathed out | **0** for `FORWARD_NULL`/`NULL_RETURNS`; 27 in 7 (function, variable) pairs when `REVERSE_INULL` is counted too |
| 4 | hand them to `coverity-triage`, expecting value or path with `coverity-verify` | per candidate: a lane check, then a slice, stubs and a fuzz run |

The whole-idir run is cheap because the checker is structural. The
filtering is the mechanism. Slicing is not needed for detection at all; it
comes back at stage 4 as the fuzz target, inside `coverity-verify`.

## Stage 1: the shape, as a path-insensitive checker

Derive the shape from the instance the later stage found, not from the defect class.
"FORWARD_NULL" is a class; "a pointer null-tested in an `if`, then
dereferenced outside that `if`, with the guard closing one statement too
early" is a shape, and it is what the checker looks for. Write it to match
the shape wherever it occurs and to reason about nothing: no feasibility,
no ordering, no reassignment. It will be noisy. That is the contract; the
filter and the confirmation stage are what make the noise affordable.

`references/candidate-checkers.md` is the CodeXM how-to, with the checker
written for this shape as the worked example (`evals/escape-hunt/
null_check_then_deref.cxm`) and the language gotchas that cost time.

Before writing one, look in the catalogue: `shapes/` in this skill holds
thirteen tested shape checkers (each with a fixture and, in
`shapes/README.md`, the components whose path-out makes its hits
relevant), and the shape at hand is often one of them or a small variant.

Run it alone, so the output is only candidates:

```bash
cov-analyze --dir <idir-copy> --disable-default --codexm <shape>.cxm
cov-format-errors --dir <idir-copy> --json-output-v10 candidates.json
```

Exclude the known instance by location when reading the result; it will be
there, and it is not what you are looking for.

**When no later stage has reported anything** -- a PATHOUT is known and that is all --
there is no instance to derive a shape from, so run the whole catalogue in
one pass (`shapes/bin/run_all.sh <install>/bin <idir-copy> <outdir>`,
one `cov-analyze` with thirteen `--codexm`) and let the filter apply each
checker's own relevance list (`--relevant auto`). The hit counts are
larger, the survivors after the relevance filter are not: every shape only
survives in functions where its own checker was cut off.

## Stage 2 and 3: filter to where the checker reached the bound

The PATHOUT set comes from a `--print-paths` run of the same idir with the
**original** options (`references/analysis-log.md`; on a large project the
plain log names almost none of them). Its `Pathed out` lines carry the
function *and* the checker that was cut off in it.

```bash
python3 tools/pathout_filter.py --findings candidates.json --log <print-paths idir>/output/analysis-log.txt \
    --relevant FORWARD_NULL,NULL_RETURNS --json survivors.json
```

`--relevant` matches component names by prefix, so `FORWARD_NULL` covers
`FORWARD_NULL_pass1` and `FORWARD_NULL_pass2` alike. That is deliberate:
the two passes are one checker, and if either reached the bound the
checker did not finish the function. Do not decide relevance from one
pass's count; a real defect was once got backwards that way.

`--relevant` is the step that matters most. A candidate for a null
dereference in a function where only `BUFFER_SIZE` pathed out is not a
candidate: `FORWARD_NULL` finished that function and rejected it with full
path sensitivity. On subversion that one filter took 115 down to 0. Name
the checkers that would have reported the defect; for a
check-then-dereference shape that is `FORWARD_NULL` and `NULL_RETURNS`.
`REVERSE_INULL` is the opposite shape (dereference, then test), but since
the shape checker is order-blind it finds that shape too, so counting
`REVERSE_INULL` as relevant is a legitimate second pass; on subversion it
yields 27 more candidates in 7 (function, variable) pairs.

Two things the filter does not do, and says so: it keeps every candidate in
a relevant function even though the checker did explore ~5,000 paths there
before stopping, so some of them were in fact examined; and it does not
pull in callers of functions whose *derivers* pathed out, although a
truncated model weakens every caller. The second is an accepted limit
rather than a to-do: it only matters when one PATHOUT function calls
another, and the shape checkers use no models. The filter prints a note
with the counts whenever a deriver is among the pathed-out components, so
the report can carry them. Should a later-stage finding ever sit in such a
caller, an issue at https://github.com/edtice-goog/CoveritySkills/issues
with the counts and component names (nothing from the codebase) is the
signal to build the callers tier.

## Stage 4: confirm or refute -- in `coverity-triage`

The survivors leave this skill here. `tools/pathout_filter.py --json
survivors.json --run-json run.json` writes them in cov-format-errors v10
shape and a plan whose `expected` block says what they were built for:
lane *value or path*, method `Execution: coverity-verify`. `coverity-triage`
bundles them, assigns a lane to each (cheap, and the one check that the
claim is what the shape assumed), and its `records.py check-lanes` lists
every candidate that landed elsewhere, with lane and reason, before any
method runs. The user then chooses per candidate: verify anyway where
that is realistic, run that lane's reader, or leave it untriaged; the
choice is an override in `run.json` with its reason, and each record
names the method that produced its verdict. For the value-or-path
candidates `coverity-verify` runs: the slice, stubs from the derived
models, a sanitizer as the oracle, a verdict with its tier.

**What reading finds, and why it is not this skill's method.** When the
27 subversion survivors were examined by reading, every one was refuted,
and the reasons are the catalogue of what a path-insensitive checker
cannot know:

| refuted by | example |
|---|---|
| reassignment between test and use | `bufpt` in `sqlite3_str_vappendf`: null-tested where it came from `printfTempBuf`, dereferenced where it had just been assigned a stack array |
| the function's own precondition | `parent_node` in `write_entry`: dereferenced unguarded under three `switch` cases, but `WRITE_ENTRY_ASSERT(parent_node \|\| entry->schedule == svn_wc_schedule_normal)` at the top says a null parent only arrives with the fourth. (The first reading missed the assertion and called this one real; the checker, which treats an assertion as an exit guard, had already dropped it.) |
| allocate-if-null | `actual_node = MAYBE_ALLOC(actual_node, pool)` then `actual_node->x`: the macro is `(x) ? (x) : apr_pcalloc(...)`, so the test the checker saw is the allocation |
| an invariant between two variables | `left_dirent`/`right_dirent` in `inner_dir_diff`: both come from hashes whose key union is being iterated, so they cannot both be null; `pUsing` in `selectExpander` is set whenever `fg.isUsing` is; `pTab` in `lookupName` is asserted |
| a loop-condition guard | `for (i = 0; moved_nodes && i < moved_nodes->nelts; i++)`: at the time the checker knew `if`, `?:`, `&&` and `\|\|` as guards, not loop conditions (it does now: `whileLoop` and `forLoopSimple` conditions guard their bodies) |
| two variables with one name | `t_entry` in `delta_dirs`, `work` in `write_entry`: an inner declaration shadows the tested one; the front end had no mangled name for the locals, so the identifier fallback conflated them |

The last one is a checker gap, recorded in `candidate-checkers.md`; the
loop-condition gap and the exit-guard gap (an expanded `assert`, an
`exit`) were closed by teaching the checkers. That is what this list is
for: each row is a thing the catalogue can learn to drop structurally. It
is not a step in the procedure. Reading is inference, and the candidates
exist because inference, the analyzer's and a reader's alike, could not
finish the function; so their verdict comes from execution, through
`coverity-triage`, and a reading verdict appears only where the user chose
that lane's reader for a candidate the lane check moved.

**What execution does.** The slice makes the function executable on its
own, the derived models make its callees behave exactly as the analyzer
believes they do, and a sanitizer is the oracle. A crash at the
candidate's dereference, reached through a stub taking its `returnsnull`
branch, is the confirmation; the analyzer would have accepted that path
as feasible had it reached it. `coverity-verify/references/fuzz-confirmation.md`
has the recipe, the verdict tiers, and the fixture where the whole chain
runs in about a minute: candidate flagged, sliced, stubbed from the model,
built with clang-cl and ASan, crashing at the right line on a four-byte
input.

## What to hand back

- The shape, as a checker file, because the next defect of the same class
  reuses it.
- The survivor list with, per candidate: function, line, the checker that
  pathed out there, the lane it was assigned, the method that judged it
  (`Execution: coverity-verify`, a named reader by the user's choice, or
  `None`), and the verdict with its tier (`confirmed by crash under model
  stubs`, `unconfirmed after N seconds`, `reachable only if a caller
  passes NULL`, `model says impossible`).
- For confirmed ones, the crashing input and the stub choices it made:
  that is the reproduction, and the callee behaviours it relied on are the
  thing to check against the real callees.

## Limits

- The shape checker is order-blind (CodeXM's `sourceloc` exposes nothing)
  and reassignment-blind. Both are by design; both are why the survivors
  are candidates, not findings, and why their verdict comes from running
  them.
- A stub is the analyzer's belief about a callee. A crash that needs a
  behaviour the model does not have is a model gap, not a confirmed
  defect, and belongs to the enrichment loop.
- Sanitizers catch crashes. A shape whose consequence does not crash
  (`REVERSE_INULL`, `DEADCODE`) needs an assertion derived from the
  finding as its oracle.
