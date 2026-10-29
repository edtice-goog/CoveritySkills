---
name: coverity-issue-transition-inference
description: >
  Decide, per finding, whether a Coverity result moved because the code changed
  or because the analyzer changed. Use this skill when a team upgrades Coverity
  and the defect count jumps or drops, when someone asks whether new findings
  are regressions they introduced, when a scan after a version upgrade needs
  triaging without treating every new defect as a bug they wrote, when defects
  disappear across an upgrade and someone needs to know whether they were
  actually fixed, or when a delta has to be annotated before it reaches a
  dashboard. The method is a control run -- the OLD code analyzed by the NEW
  analyzer -- which splits one confounded delta into two clean ones. Requires
  the ability to rebuild the old code (or an intermediate directory to replay),
  both analyzer versions, and a Coverity Connect instance to line findings up.
---

# Issue Transition Inference

A team upgrades Coverity. The finding count moves. Someone has to answer, per
finding:

> **Did I write this bug, or did the tool change?**

That is the whole question, and it is binary. Whether a version-attributable
finding came from a newly-default checker, a smarter checker, or a front-end
change is a real distinction, but it is a *tool-vendor* distinction: it does not
change what the user does next. Keep it as a sub-field; never lead with it.

The mirror question matters just as much and is easier to forget:

> **Did I actually fix this, or did the tool stop reporting it?**

A finding that vanishes on upgrade reads as progress in every dashboard.

## The inference

Findings are a function of several inputs at once:

```
findings = f(code, analyzer version, configuration, capture)
```

The situation users bring you has all of them moving together: an old snapshot
`(C1,A1)` and a new one `(C2,A2)`. You cannot attribute that delta, for the same
reason `coverity-build-fidelity` cannot attribute a binary delta without its
control pair.

**Produce the cell they do not have.** Analyze the *old* code with the *new*
analyzer:

```
(C1,A1) -> (C1,A2)     code held constant      => version-attributable
(C1,A2) -> (C2,A2)     analyzer held constant  => code-attributable
```

Everything else in this skill is making that extra run trustworthy.

## Procedure

### Ask only when interactive (rule 38)

Several steps below need a decision that is the user's to make. Ask for it only
in an interactive session. Otherwise -- and when you cannot tell -- **report
exactly what is needed to continue, and stop.**

**Do not infer interactivity from weak signals:** not a TTY, not an
environment variable, not the shape of the invocation. Unsure means stop.

Never default into the more expensive *or* the less reversible option. In this
skill those are different branches: the expensive one is a capture and
analysis, and the irreversible one is a write to someone's instance -- an
annotation, or worse a backdated commit, since `date_originated` is write-once
per merge key and no later commit can move it. The rule decides *when to ask*,
never that an answer may be assumed, so "not interactive" does not license
proceeding on whichever branch looks cheap or safe either.

| Step | Needs a decision | Unattended | Resumes with |
|---|---|---|---|
| 1 | build instructions, and which existing result is the anchor | report what is missing; capture nothing | the build command, and the stream and snapshot that is the anchor |
| 2 | the build does not run -- hand off to `coverity-recreate-from-emit`? | report that the build fails and what the hand-off would cost; do not start it | a working build command, or an explicit OK to replay from the old idir |
| 3 | the original run's analysis options are not recoverable | report it; do not guess options, which silently redefines what you measured | the option set to use on both sides, or the snapshot to read it from |
| 6 | the annotation scheme, and whether to backdate the commit | report the labels and the choices; write nothing | the scheme: classification and comment, a named custom attribute, or "we will write it ourselves" -- and the date to commit under, if any |
| -- | whether anyone wants the fourth cell | three cells is the baseline procedure, not a choice you made; the fourth is an extra capture and analysis, and is only ever run on request | an explicit yes, at the cost of one more capture and analysis |

**Stop without discarding the expensive part.** In this skill the costly
artifacts are produced early and the decisions come late, so a stop that throws
them away converts a one-line question into hours of recompute. Keep the
intermediate directories and the per-cell exports, name their paths in the
report, and say plainly what will *not* be redone: resuming at Step 6 re-reads
the exports and writes annotations -- it captures nothing.

A reported-and-stopped run is a useful result. Give the labels you could
derive, name the decision that blocked the rest, and state the answer or
command that continues it.

### Step 0. Rules, and pin two installations

Read `coverity/RULES.md`. Pin **two** installs and name both in every artifact:
the version that produced the existing result, and the version being adopted.
Rule 3 says pin one; this skill and `coverity-recreate-from-emit` are the
exceptions that require exactly two.

**Check both installs' licences before queuing anything.** Capture is
licence-free by design -- that is what makes capture-on-an-ephemeral-agent /
analyze-on-a-licensed-host a supported topology -- so `cov-build` will happily
emit a full project under an install whose `license.dat` lapsed, and only
`cov-analyze` objects. Point at a licence explicitly with `--security-file`
(`-sf`); licence files are cross-platform. `cov-format-errors` needs it too, and
checks *after* the analysis summary prints, which is the confusing order to hit.

### Step 1. The anchor -- reproduce the result they already have

This is the step that ties everything to the user's reality, and it comes first.

The user supplies build instructions and an existing Coverity result from their
automated run at the old version. Build that code, capture it, analyze it with
the **old** analyzer, and confirm it reproduces their last automated result.

- **It can reproduce exactly.** Measured: a fresh build into a fresh idir gave
  96 occurrences / 62 merge keys, an identical merge-key *set* to the earlier
  run of the same tag.
- **You do not have to rebuild at their CI path.** Merge keys are computed from
  properties of the parsed code and are **path-independent** by design -- that
  is what lets defects track across workspace checkouts. Measured: the same
  defect built in two differently-named directories carries an identical merge
  key. Do not spend effort recovering a build path for this purpose.

**If it does not reproduce, stop.** A delta measured against a result you could
not reproduce is uninterpretable -- you cannot separate the analyzer's
contribution from your own process error. Diagnose with rule 16 (find where the
pipeline narrowed) before going further.

### Step 2. Rebuild the same code with the new analyzer

Each analyzer version needs its own capture: the emit format is version-locked,
so one idir cannot serve both. That means `cov-build`/`cov-emit` move with the
checkers, and "the analyzer version" is not one variable.

**Prove the build did not change. Do not invent a check for this:**

- the build still runs -> `coverity-build-fidelity`, **both arms**. Fidelity
  (`K` empty) *and* capture coverage. One arm is not enough: a capture that
  emitted nothing produces byte-identical binaries.
- the build cannot be re-run -> `coverity-recreate-from-emit`.

**The front end travels with the analyzer, and which path you took decides
whether that is a problem.** `cov-translate` turns a compiler command line into
a `cov-emit` command line, and that translation is *not* identity across
versions -- `coverity-recreate-from-emit` measured `--c11` becoming `--c17`
between two releases, which changes parsing and predefined macros.

- **Rebuilding (this step).** The new version captures the code with its own
  front end. That is correct and wanted: the user is adopting the new analyzer
  whole, front end included, and "version-attributable" should mean exactly
  that. Nothing to pin.
- **Replaying from emit.** You choose whether to accept the drift or pin the old
  flags back, and the choice changes what the comparison measures. Decide
  explicitly and say which you chose -- an unstated choice silently varies two
  inputs where you meant to vary one. See that skill's Step 6.

### Step 3. Analyze, at the same configuration

Same options both sides. Differences in *your* configuration are a variable you
introduced; differences in the *product's* defaults are part of what you are
measuring, and get separated in Step 5.

### Step 4. Correspond through Connect, never by raw merge key

Commit both runs and compare through Connect or its REST API against the
committed snapshots. Connect's commit process applies antecedent merge keys, so
a finding whose key legitimately moves still lines up (rule 27).

**Do not diff raw merge keys between two local result sets.** That path cannot
see the antecedent relationship, so an unchanged finding reads as new --
manufacturing exactly the false transitions this skill exists to prevent.

`tools/transition.py` builds the CID-by-cell matrix from Connect and labels each
finding. It also reads the local exports, but *only* to measure how far the raw
keys drifted -- never as the correspondence.

### Step 5. Separate configuration from capability -- from the docs, not from guesswork

Diff `doc/en/checker-enablement-and-option-defaults.html` between the two
installs (rule 4):

```bash
python3 tools/checker_defaults.py <old-install> <new-install>
```

A checker that moved default-off to default-on, or arrived new and default-on,
produces findings that are **configuration**, not capability. This is cheap,
purely documentary, and can be done *before* any analysis -- which makes it a
prediction rather than a rationalization.

**Filter to real transitions.** The raw diff overstates badly: between two
versions one release apart, 213 rows changed and nearly all were a documentation
rename (`All Security` -> `Recommended Security Checkers`), not behaviour.

### Step 6. Ask how to record the attribution, then record it

The deliverable is not only a report -- it is the findings marked in Connect so
they do not read as regressions to whoever opens the dashboard next. There are
two axes to get right: what each finding is **labelled**, and what date it
**carries**.

**Ask the user how they want it done.** Installations vary: some will want a
classification and comment, some have a **custom attribute** for exactly this,
some want the write left to them. Do not assume a scheme, and do not write to
their triage store before they have chosen one.

**Unattended, annotate nothing.** Report the labels and the annotation choices
and stop. Triage state is shared, outward-facing, and read by people who were
not in the room: a scheme guessed by an unattended run is worse than no
annotation at all, because it looks deliberate.

When experimenting rather than servicing a real instance, create your own triage
store and project so nothing lands in theirs.

#### Fix the dates, not just the labels

A label explains a finding to whoever reads it. The **date** is what the
dashboard sorts and alerts on, and by default it is wrong: commit a
version-attributable finding today and Connect sets its first-detected to
today, because that merge key has never been seen before. Fifty findings that
were in the code all along arrive looking like this morning's regressions, and
no annotation undoes that.

`cov-commit-defects --backdate` sets it correctly. Commit the new-analyzer run
with the date the **code** is from, and the findings it reports for the first
time carry the date they were actually present.

**This is honest here, and almost nowhere else.** The defect was in that code
on that date; only the analyzer's ability to see it changed. What licenses the
claim is the code-sameness evidence from Step 2 -- without it you would be
asserting a first-detected date you cannot support, and backdating a genuinely
new defect is a falsification that survives in the database. So the attribution
comes first and the dates follow from it; never the other way round.

Three mechanics that decide whether it works, all of them measured in
`coverity-demo-data/references/backdating.md` -- read it rather than trusting
this summary:

- `--backdate` takes `yyyymmdd` and nothing else.
- `date_originated` is **per CID, global to the instance, and write-once** --
  set from the backdate only **for merge keys not previously seen**. So a
  column spanning several releases must be committed **oldest first**, each
  release carrying its own date.
- The snapshot's code must be pinned to one known date. Do not backdate a
  snapshot that mixes code versions -- within one release the code is fixed and
  the date is a fact; across releases it is a guess.

**Write-once is why this works, not a limitation of it.** The findings that
need a date are the version-attributable ones, whose merge keys the instance has
never seen -- so the backdate sets them. The findings already present under the
old analyzer keep the dates they already had, because a later backdate cannot
move them, and those dates were already correct. The no-op falls exactly on the
findings that did not need fixing.

**A separate stream is for rule 29, not for dates.** It does not give the new
column its own first-detected dates: `date_originated` hangs off the per-CID
record for the whole instance, and merge keys are mostly stable across analyzer
versions, so a shared finding carries one date no matter which stream or project
it is committed into. Genuinely independent dates would need a separate Connect
instance. What the separate stream buys is a timeline that does not lie: the
control run is *older code committed later*, so putting it in the user's
existing stream moves that stream backwards and makes every finding absent from
it read as fixed (rule 29).

That part is **reasoned, not measured.** The write-once behaviour was measured
across three snapshots in one stream; the cross-stream consequence follows from
where `date_originated` lives and has never been run. If a decision rests on
it, measure it first -- it is cheap.

### Step 7. Report

Verdict first (rule 21). Name both installs, the anchor result, the
build-fidelity grade and capture triple, the label counts, and every finding
that is not `UNCHANGED` with its evidence. Say what you did not check (rule 22).

Scope the claim explicitly: this attributes a finding delta. It does not certify
that either analysis was complete.

## The labels

One label per finding, from its presence across the cells. `a=(C1,A1)`,
`b=(C1,A2)`, `c=(C2,A1)`, `d=(C2,A2)`.

| Label | Pattern | What the user does |
|---|---|---|
| `UNCHANGED` | `ABCD` | nothing |
| `VERSION_ATTRIBUTABLE` | `.B.D` | you did not write this |
| `CODE_ATTRIBUTABLE` | `..CD`, `...D` | you wrote this -- fix it |
| `RESOLVED_BY_CODE` | `AB..` | your change fixed it |
| `DROPPED_BY_VERSION` | `A.C.` | **you did not fix this** -- the tool went quiet |
| `CONTROL_FAILURE` | `A..D`, `.BC.` | stop; the experiment is invalid |

`VERSION_ATTRIBUTABLE` carries a `sub_attribution` of `checker_enablement` or
`analyzer_behaviour` from Step 5. Detail, not headline.

### Three cells or four

The **production** case uses three: the anchor `(C1,A1)` you reproduced, the
control `(C1,A2)` you add, and `(C2,A2)` -- the result the user already has and
is asking about. Only one of the three is new work, which is what makes the
procedure affordable.

Every primary label is decidable from those three, and the discriminator is
usually `b`, not `c`:

- appeared, and `b` reports it on the old code -> `VERSION_ATTRIBUTABLE`
- appeared, and `b` does not -> `CODE_ATTRIBUTABLE`
- disappeared, and `b` still reports it on the old code -> `RESOLVED_BY_CODE`
- disappeared, and `b` does not -> `DROPPED_BY_VERSION`

The **four-cell** form adds `(C2,A1)`, the old analyzer on the new code. It buys
two things and is worth the extra capture when either matters: it confirms the
code-side labels independently, and it is the only way to detect
`CONTROL_FAILURE`, whose patterns both involve `c`. Run it when calibrating the
method, or when the code delta itself is under dispute -- and only when someone
has asked for it. It is a whole extra capture and analysis, so it is never the
unattended default; report that three cells cannot detect `CONTROL_FAILURE` and
let the user decide whether that matters to them.

### `CONTROL_FAILURE` must be empty

If the code is genuinely identical between `a`/`b` and between `c`/`d`, no
finding can be explained only by the *combination* of new code and new analyzer.
A diagonal-only pattern therefore means something varied that you failed to hold
constant. **Go back to Step 2 and prove code sameness; never report the bucket.**

Note the pattern that looks like this and is not: `...D`, a finding present only
in the newest corner. Cell `b` settles it -- if the new analyzer does not report
it on the *old* code, then the code is what changed, and it is
`CODE_ATTRIBUTABLE`.

## Traps

- **A wave of configuration findings can bury a real bug of the same checker.**
  Measured: 51 new `NULL_FIELD` findings across one upgrade, 50 of them from the
  checker flipping to default-on and **one a genuine new defect** in a function
  added in the new release. Discarding by checker would have thrown it away.
- **Only the control run finds that bug.** The old analyzer never reports it at
  all, because the checker is off by default there. A `(C2,A1)` diagonal does not
  merely bury it -- it cannot see it.
- **`DROPPED_BY_VERSION` is the dangerous half.** A new finding costs triage
  time; a silently dropped one costs a real defect, and it looks like progress.
- **Low analyzer churn is by design.** Keeping churn down is part of Coverity's
  development process, so a small capability delta is the expected result, not a
  discovery. It also means a *large* delta is almost never capability.
- **`primaryFileHash` will not prove two idirs captured the same source.**
  Measured here: it matched on only 16 of 90 provably identical files. See
  `coverity-recreate-from-emit`.
- **Capture and analysis need not share a platform.** Measured: a Linux-captured
  idir analyzed on Windows and on Linux produced identical merge-key sets. The
  emit *format* is the compatibility key, and it must match exactly.

## Related

- `coverity` -- standing rules, capture fidelity. Read `RULES.md` first.
- `coverity-build-fidelity` -- proves the code and build were held constant.
  Step 2 requires it.
- `coverity-recreate-from-emit` -- produces `(C1,A2)` when the build cannot run.
- `coverity-defect-detectability` -- why a specific finding is or is not
  reported under a given configuration.
