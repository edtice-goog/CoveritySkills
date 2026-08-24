# coverity-issue-transition-inference — starting document

**Status: stub.** Written to hand off to a fresh session. Nothing here has
been validated by a run. Treat every claim as a hypothesis to test, in the
style of the other skills in this repo, where every factual statement was
produced by a real execution.

## The problem

A team adopts a new analyzer version — or a new tool entirely — and the
finding count moves. Someone has to answer, per finding:

> Is this new because **the code changed**, or new because **the analyzer
> got better**?

Teams cannot answer it today, so they either treat every new finding as a
regression (and drown), or discount the whole delta (and miss real defects).
Both are expensive, and the second is dangerous.

## The core inference

The same shape as `coverity-build-fidelity`: you cannot attribute a delta
without a control. Findings are a function of at least five inputs —

```
findings = f(code, analyzer version, configuration, capture, analysis nondeterminism)
```

— and the situation users bring you has **all of them varying at once**: an
old snapshot `(C1, A1)` and a new one `(C2, A2)`.

The move is to fill in a cell they don't have. Analyzing the **old code with
the new analyzer** — `(C1, A2)` — splits one confounded delta into two clean
ones:

```
(C1,A1) -> (C1,A2)    code held constant   => analyzer-attributable
(C1,A2) -> (C2,A2)    analyzer held constant => code-attributable
```

`(C2, A1)` works symmetrically if the old analyzer is still available and the
new code still builds under it. Either diagonal breaks the confound; pick
whichever is cheaper to produce.

**This is the whole skill.** Everything else is making that extra run
trustworthy and matching findings across it.

## Prerequisite: the runs must be comparable

The inference is worthless if the two runs did not analyze the same code.
Two failure modes, both silent:

1. **Different capture.** If run A captured 1180 TUs and run B captured 900,
   the finding delta is partly a coverage delta. Establish capture
   equivalence first — this is exactly what `coverity` (capture fidelity) and
   `coverity-build-fidelity` exist to provide. A finding that is "new"
   because its file was finally captured is not an analyzer improvement.
2. **Different configuration.** Checker sets, aggressiveness, and defaults
   move between analyzer versions. A new default-on checker is an analyzer
   change; a locally enabled checker is a configuration change. They need
   separate labels because they need separate decisions.

## Two paths to the extra run

### Path A — rebuild (preferred)

If the build is repeatable, re-run it at the old commit and analyze with the
new analyzer. `coverity-build-fidelity` validates that the rebuild is
faithful, so `(C1, A2)` is genuinely the same code as `(C1, A1)`.

Evidence from this repo that this is realistic: curl 8.21.0_7 was reproduced
**byte-identically** from its official release, and gcc/ELF builds were
bit-reproducible unaided. Many shops are closer to this than they think.

### Path B — recreate from emit (fallback)

Old code often will not build any more: the toolchain is gone, dependencies
have vanished, the CI job was retired. The intermediate directory is then the
only surviving record of the build.

`cov-manage-emit --dir <idir> list-capture-invocations` carries the capture
invocations — and `--no-process-details` suppresses process details, which
implies the details are there by default. If those are the real compiler
command lines, the old build can be replayed against a new analyzer without
reconstructing the old build environment.

This is the `coverity-recreate-from-emit` skill. See its stub for the
interface this skill needs from it.

**Unverified and load-bearing** — settle before designing around it:

- Do capture invocations include full argv, cwd, and environment?
- Does the emit retain enough to re-emit, or are original sources required?
  `primaryFileHash` (MD5 per TU) can prove you have the right revision.
- Can a newer `cov-emit` consume an older emit directly, and across how many
  versions?

## Matching findings across runs — let Connect do it

Attribution needs a correspondence between findings in two runs. **Do not
build one.**

Merge keys are designed to be constant over time, and when a key genuinely has
to change Coverity creates an **antecedent merge key** so the old and new
identities line up. **Coverity Connect's commit process applies this
automatically**, so REST API queries against committed snapshots do not report
spurious new defects caused by a key change.

The failure mode is self-inflicted: **comparing raw merge keys by hand between
two local result sets.** That path never sees the antecedent relationship, so
an unchanged finding reads as new — manufacturing precisely the false
transitions this skill exists to prevent. Anyone diffing two analyzer versions'
local output directly will hit it.

So the design consequence is a simplification, not a complication:

- commit both runs to Connect; compare through it or the REST API against the
  committed snapshots
- do **not** treat a raw merge-key difference between local result sets as
  evidence of a new finding
- do **not** invent a correspondence mechanism; the platform already has one

Exceptions have occurred, so a small residue of genuine key movement is
possible — treat it as a rare case to investigate, not the default assumption.

See `coverity/RULES.md` rule 27. Note its provenance line: this is stated
domain knowledge, not measured in this repo, and the exception rate in
particular is worth a calibration run before anything depends on it.

## Proposed attribution taxonomy

Per finding, one label plus evidence. Draft — expect it to change on contact:

| Label | Meaning |
|---|---|
| `NEW_CODE` | introduced by a source change |
| `ANALYZER_IMPROVED` | present in the old code, found only by the newer analyzer |
| `CHECKER_ENABLED` | configuration, not capability |
| `NEWLY_CAPTURED` | the code is newly reaching the analyzer at all |
| `REKEYED` | the same finding under a different identity — should be rare if comparison goes through Connect; a cluster of these is a signal the comparison path is wrong, not that the analyzer churned |
| `FIXED` | genuinely resolved by a source change |
| `LOST` | no longer reported, and not because it was fixed — a regression in the tool, worth surfacing |
| `INDETERMINATE` | the evidence does not decide |

`LOST` and `INDETERMINATE` matter as much as the rest. A skill that only
explains new findings will be used to dismiss them.

## Output

Follow the convention already used in this repo: a human-facing `report.md`
that leads with the verdict, plus machine-readable JSON. Per-finding labels
with evidence, never a bare count. Scope the claim explicitly — this
attributes a finding delta; it does not certify that either analysis was
complete.

## Open questions for the new session

1. Which diagonal is cheaper in practice, `(C1,A2)` or `(C2,A1)`? Availability
   of old analyzer versions may decide it.
2. Confirm rule 27 by measurement: commit two analyzer versions' runs over
   identical code to Connect and verify the REST results show no spurious new
   defects. Quantify the exception rate rather than assuming it is zero.
3. Is there a Coverity-native transition/triage-state mechanism that already
   does part of this, and should this skill drive it rather than duplicate it?
4. Does this generalize to a *different vendor's* tool as the second analyzer,
   or is cross-tool correspondence a distinct and much harder problem?
5. What is the minimum evidence a user must supply — two idirs, two snapshots,
   or source access as well?

## What already exists here

- `coverity` — capture fidelity (three-method check), standing rules
- `coverity-compiler-configuration` — `--template`; a tainted config
  invalidates comparisons between runs
- `coverity-build-fidelity` — proves a captured build matches the delivered
  build; supplies Path A and the control-pair reasoning this skill reuses
- `coverity-defect-detectability` — whether a given defect is findable at all,
  and the minimal configuration that reports it

Read `coverity/RULES.md` before running anything.
