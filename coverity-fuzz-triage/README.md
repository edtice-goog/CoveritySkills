# coverity-fuzz-triage

Part of [CoveritySkills](../README.md).

Confirms or refutes a Coverity finding by **running the function** instead
of reading it. The function becomes a standalone file
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

It is the confirmation stage of the PATHOUT escape hunt
(`coverity-pathout` produces the candidates), and it stands on its own:
a batch of ordinary findings in, a verdict with evidence per finding out.
The first real batch -- ten proftpd findings, `CALIBRATION.md` -- came
out 0 confirmed, 5 refuted with the finding's line reached hundreds of
thousands of times and the claim never false, 2 refuted as model gaps
(the analyzer's generic model records no writes to globals, and the stub
reproduced the analyzer's own false positive with the missing write
named), 2 reachable only through a value the harness supplied, and one
real one-byte stack overflow found next to a false OVERRUN. Every
"confirmation" on that batch fell to reading the stub choices behind it,
which is why the trace exists and why "confirmed" always lists them.

## What is in it

| | |
|---|---|
| `SKILL.md` | the procedure: name the claim -> slice -> models -> assemble (focused, then free) -> verdict with tier |
| `references/fuzz-confirmation.md` | why the model is the stub, the harness, the proftpd batch, the verdict tiers, what is not built |
| `tools/fz_target.py` | slice + saved models + harness snippet -> `target.c`: libc left real, model stubs with their behaviours listed, `--claim` inserted at the finding's line, `--pin-normal --free` focused mode, `--semantic` copy semantics |
| `tools/fz_support.h` | the byte stream, the per-stub choice trace printed on a crash, pins, the per-input arena, pointer-filled objects, the claim counter; builds with clang and clang-cl |
| `tools/model_stubs.py` | a callee stub from its `cov-find-function --save` model |
| `evals/` | `lookup.c` (a callee with a model), `use.c` (a caller with an unguarded dereference), `harness.c`, and `run.sh`, which runs the chain end to end |
| `CALIBRATION.md` | what was measured, on what, and what was not |

## Requirements

- A local Coverity Analysis installation of the version that wrote the
  intermediate directory (`cov-find-function` reads the models out of it).
- `coverity-function-slice` installed beside this skill.
- clang with libFuzzer and AddressSanitizer. On Windows, LLVM's `clang-cl`
  with `LLVM\lib\clang\<ver>\lib\windows` on `PATH`.

## Install

```bash
cp -r coverity-function-slice coverity-fuzz-triage ~/.claude/skills/
```

Then: "is this NULL_RETURNS in `fetch_conflict_details` real? run it."
