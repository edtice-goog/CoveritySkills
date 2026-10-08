# coverity-verify

Part of [CoveritySkills](../README.md).

Verifies a Coverity finding by **executing it** instead of reading it.
Verification is the general capability; the one method here fuzzes the
function under stubs from Coverity's own derived models, which is
deterministic and uses the analyzer's own data. The skill decides first
whether a finding is a candidate for that method and reports the rest
(injection classes, anything a clang harness cannot instrument) as "not a
fuzz-triage candidate; suggest external verification" rather than
attempting them; what else "external" might mean is an open item, not a
plan. Formerly `coverity-fuzz-triage`, which remains as an alias
directory. The finding can be a Connect CID,
an entry in a `cov-format-errors` findings file, or a candidate from
`coverity-pathout`'s shape catalogue; Step 0 turns each into the same
thing, a claim at a line. The function becomes a standalone file
(`coverity-function-slice`), every callee becomes a stub printed from
Coverity's own derived model of it, a libFuzzer harness lets one input
choose the arguments and every stub behaviour, and a sanitizer (or an
assertion derived from the finding) is the oracle. A crash at the finding's
line is a confirmation the analyzer would have accepted, because every
behaviour it relied on is one the analyzer granted the callees; a model with
no edge that can produce the bad value is a refutation in the analyzer's
own terms.

## Why the stubs are the point

The fuzzer needs definitions for the callees, and the wrong definitions
give wrong verdicts: a stub that returns NULL where the real callee never
can confirms nothing. Coverity has already derived, for every function it
analyzed, what it believes that function does:

```bash
cov-find-function --dir <idir> --save -of models --module generic <callee>
```

writes an automaton whose edges are the behaviours -- `returnsnull`,
`identity(<arg 1>)`, `afm_alloc`, `dereference(<arg 0>)`, `write`,
`escape`. `tools/model_stubs.py` prints a stub with one branch per
behaviour, chosen by the fuzz input. On the fixture the whole chain --
candidate, slice, model, stub, build with clang-cl and ASan, crash at the
right line on a four-byte input -- runs in about a minute
(`evals/run.sh`). On subversion, a NULL_RETURNS finding that a bare slice
lost came back with the original event chain once both callees on the
chain were stubbed from their models.

## Where it fits

It is the verification stage. `coverity-pathout` sends it the candidates
it collects from functions that reached the path bound, and it stands on
its own: a CID or a batch of ordinary findings in, a verdict with evidence
per finding out.
The first real batch -- ten proftpd findings, `CALIBRATION.md` -- came
out 0 confirmed, 5 refuted with the finding's line reached hundreds of
thousands of times and the claim never false, 2 refuted as model gaps
(the analyzer's generic model records no writes to globals, and the stub
reproduced the analyzer's own false positive with the missing write
named), 2 reachable only through a value the harness supplied, and one
real one-byte stack overflow found next to a false OVERRUN. Every
"confirmation" on that batch fell to reading the stub choices behind it,
which is why the trace exists and why "confirmed" always lists them.

## Fixed, or silenced?

A finding that is present in one version and gone in the next was either
fixed or quieted: an initializer, a cast, a silent guard, a helper the
analyzer has no model for, an annotation. The fix check (`SKILL.md` Step
5, `references/fix-check.md`) verifies the finding on the old code, then
re-runs the same verification on the new code with the claim re-armed past
the change, and adds a differential run of old against new on the same
inputs. The verdict is on the change: fixed; silenced, not fixed; a
silencing change on a false positive that left behaviour alone; or a
"fix" that changed behaviour and should be reviewed as a code change. It
is a step on request, for a fix someone else made that you doubt or a
batch of findings that vanished between versions; the skill picks the
suspicious changes out of the batch, or checks every one when asked.
Measured on OpenSSL (an initializer that quieted an `UNINIT` false
positive: behaviour-neutral over 746,679 differential inputs) and on the
fixture (`evals/run_fixcheck.sh`: a
real fix and a dereference moved into an uncaptured helper, told apart by
execution in about four minutes).

## What is in it

| | |
|---|---|
| `SKILL.md` | the procedure: name the claim -> slice -> models -> assemble (focused, then free) -> verdict with tier |
| `references/fuzz-confirmation.md` | why the model is the stub, the harness, the proftpd batch, the verdict tiers, what is not built |
| `references/fix-check.md` | fixed, or silenced? the inputs, which fixes to check, re-arming a claim the change made vacuous, the differential run, the verdicts on the change, the OpenSSL case and the fixture |
| `tools/fz_target.py` | slice + saved models + harness snippet -> `target.c`: libc left real, model stubs with their behaviours listed, `--claim` inserted at the finding's line, `--pin-normal --free` focused mode, `--semantic` copy semantics |
| `tools/fz_support.h` | the byte stream, the per-stub choice trace printed on a crash, pins, the per-input arena, pointer-filled objects, the claim counter; builds with clang and clang-cl |
| `tools/cid_lookup.py` | a Connect CID to its stream, checker, file, function and merge key over REST, then the matching issue and its events out of the idir's findings |
| `tools/model_stubs.py` | a callee stub from its `cov-find-function --save` model |
| `evals/` | `lookup.c` (a callee with a model), `use.c` (a caller with an unguarded dereference), `harness.c`, and `run.sh`, which runs the chain end to end; `run_fixcheck.sh` with `fixcheck/` (a fix and a silencer of the same finding) runs the fix check end to end |
| `CALIBRATION.md` | what was measured, on what, and what was not |

## Requirements

- A local Coverity Analysis installation of the version that wrote the
  intermediate directory (`cov-find-function` reads the models out of it).
- `coverity-function-slice` installed beside this skill.
- clang with libFuzzer and AddressSanitizer. On Windows, LLVM's `clang-cl`
  with `LLVM\lib\clang\<ver>\lib\windows` on `PATH`.

## Install

```bash
cp -r coverity-function-slice coverity-verify ~/.claude/skills/
```

Then: "is this NULL_RETURNS in `fetch_conflict_details` real? run it."
