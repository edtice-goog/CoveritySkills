# Calibration status

This project's standard is that factual claims in a skill were established by
real runs. This file records where `coverity-issue-transition-inference` stands,
so that nothing unverified reads as measured.

Environment for everything marked verified: Windows 11 host with several
Coverity installations side by side, WSL2 Ubuntu with gcc 13.3.0, and a local
Coverity Connect 2025.12.0. Subject: proftpd v1.3.8 and v1.3.9, each checked
out in place in one build tree, serial `make`, 90 TUs per cell at 100%.
Analyzer versions 2024.12.1 and 2025.12.2. Run 2026-08-24.

Full narrative in `references/worked-example-proftpd.md`.

## Verified by direct execution

- **The full 2x2 was built and labelled.** 117 CIDs; 57 `UNCHANGED`, 54
  `VERSION_ATTRIBUTABLE`, 3 `DROPPED_BY_VERSION`, 2 `RESOLVED_BY_CODE`, 1
  `CODE_ATTRIBUTABLE`. Only five presence patterns occurred and every one is
  interpretable.
- **`CONTROL_FAILURE` was empty.** No diagonal-only pattern occurred, matching
  what the code-sameness evidence predicts.
- **Configuration dominates the version delta.** Of 54 findings new on identical
  code, 50 were `NULL_FIELD`, whose enablement moved Optional -> Default. The
  prediction was made from the installation's own documentation *before* any
  analysis was run.
- **The enablement diff overstates.** 213 rows changed between the two installs;
  nearly all were the rename `All Security` -> `Recommended Security Checkers`.
  Only 1 C-language checker genuinely changed enablement and 1 arrived new and
  default-on.
- **A real new defect hid inside the configuration wave.** `CID 10114`,
  `NULL_FIELD` in `src/fsio.c:pr_fsio_realpath`, a function added wholesale in
  v1.3.9 (`git diff` confirms). Present only in `(C2,A2)`; cell `(C1,A2)` is
  what proves the code, not the analyzer, introduced it. The old analyzer never
  reports it, so a `(C2,A1)` diagonal cannot see it at all.
- **Findings were dropped in the other direction.** 3 `FORWARD_NULL` in
  `lib/hanson-tpl.c`, present in both code versions, reported only by the old
  analyzer.
- **The anchor step reproduces exactly.** An independent rebuild of v1.3.8 under
  2024.12.1 gave 96 occurrences / 62 merge keys with an **identical merge-key
  set** to the first run.
- **Merge keys are path-independent.** The same defect built in `alpha/` and in
  `a-much-longer-dir-name/` carried the identical key
  `c7fb1f1a2f52dd0cc9b11c9916b1c357`. Different path lengths, so this is not
  length-invariance masking a path component.
- **Patch level and analysis platform do not perturb defect identity.** One idir
  analyzed by win64 2024.12.0 and linux64 2024.12.1 produced identical
  merge-key sets (96 occurrences, 62 keys, zero either way).
- **Build fidelity: `K` empty.** `D(native1, coverity)` was offset-for-offset
  identical to the control `D(native1, native2)`. proftpd is *not*
  bit-reproducible -- an embedded `Built:` timestamp and the 20-byte ELF
  build-id differ every run -- so the floor was measured, not assumed.
- **Capture equivalence across cells.** 90 TUs, identical `primaryFilename`
  sets, zero `primaryFileSizeInBytes` differences, 90/90 AST-complete.
- **`primaryFileHash` is not a same-code gate.** It matched on only 16 of 90
  provably identical files, independently reproducing
  `coverity-recreate-from-emit`'s measured negative.
- **Capture is licence-free; analysis is not.** `cov-build` emitted all 90 TUs
  under an install whose `license.dat` expired 2025-12-31;
  `cov-analyze` then refused with `License authorization failure`.
  `--security-file` / `-sf` supplies a licence explicitly, works cross-platform
  (a win64 `license.dat` drove a linux64 install), and `cov-format-errors`
  needs it too -- it checks *after* the analysis summary prints.
- **Emit format is the compatibility key.** linux64 2024.12.1 writes format 343
  and only win64 2024.12.0 read it; linux64 2025.12.2 writes 352 and only win64
  2025.12.0 read it. Every other install refused with exit 2.
- **A WSL-written idir analyzes on Windows without `reset-host-name`.**

## Measured, and it corrected another skill

`coverity-demo-data` stated that the source path is part of the defect merge
key, and used that to justify building every version at the same absolute path.
**That rationale is false** -- see the path-independence result above. The
practice of one tree checked out in place is still right, for contamination
reasons (stale generated files between versions), and the claim has been
corrected in `coverity-demo-data/SKILL.md`, `tools/capture.sh`, and `README.md`.

## Measured at scale: raw merge keys did not move across a second version pair

A second pair was screened offline, with no new captures: the same 24 releases
of one C project analyzed at **2025.9.0** and at **2026.9.0**, comparing the
per-release finding exports of the older column against the published
merge-key record of the newer one.

Both inputs are sealed published artifacts, not working copies, so the figures
below can be re-derived rather than taken on trust. The screen was run twice --
once against a run workspace and once against the sealed copy of the same
column -- and returned identical figures; the 24 export files were also
compared byte for byte across the two locations and are identical.

```
3134 key-releases shared      7 gained      0 lost
union: 222 keys old / 223 new  -- shared 222, old-only 0, new-only 1
```

- **Zero keys were lost**, across 24 releases and a twelve-month, two-version
  gap. Every key the older analyzer reported was reported by the newer one.
- **Analyzer churn was 7 of 3141 key-releases, 0.2%.** This is the
  low-churn-by-design property showing up as a measurement rather than a claim.
- **The configuration share was predicted before the data was read.** Diffing
  the two installations' enablement tables gave exactly one C change: a new
  default-on checker, `INCONSISTENT_UNION_ACCESS`. It accounts for 3 of the 7
  gains. The other 4 are one checker whose enablement did not change, so they
  are candidate analyzer-behaviour changes.

**This is a screen, not a correspondence.** It diffs raw merge keys between two
local result sets, which cannot distinguish "newly reported" from "same
finding, re-keyed" (rule 27). The result is therefore read as: there is almost
nothing here for an antecedent relationship to explain, because 222 of 222 keys
are present in both columns.

So it raises the empirical floor under rule 27's premise considerably -- key
stability now holds over 222 keys and two version pairs rather than 59 keys and
one -- while still **not** demonstrating the antecedent mechanism, which only
does anything when a key does move. Limit 1 below stands.

## Limits of the evidence

These are the boundaries of what has been measured, kept here so a claim's
provenance is never guessed at (rule 23). They are limits of the evidence,
not missing pieces of the skill: the procedure is complete and each item
below tells you which specific claim to treat as reasoned rather than
measured, and what would settle it.

1. **Rule 27 is still unexercised.** Raw merge keys and Connect CIDs agreed
   exactly (59/59) on the first pair, and the second pair found 222 of 222 keys
   present in both columns, so the antecedent-merge-key path has never fired.
   Two pairs of measured stability are not evidence that the mechanism works
   when a key *does* move -- they are evidence that it rarely has to. Until a
   moving key is found, "compare through Connect" rests on stated domain
   knowledge rather than a demonstration. Finding one plausibly needs a wider
   version gap, a larger corpus, or a project whose code churns harder than the
   ones measured here.
2. **The production procedure has only been run in pieces.** The anchor step was
   validated against a result this project produced, not against a customer's
   pre-existing automated snapshot. The end-to-end shape -- user supplies build
   instructions and an existing result -- is untested.
3. **Annotation has not been performed.** Step 6 is written but no defect has
   been annotated in Connect through this skill, and the mechanism (native
   triage fields versus a custom attribute) varies per installation.
4. **One version pair, one project, one language.** 2024.12.1 -> 2025.12.2 on a
   C autoconf project. Whether label distributions hold across a longer version
   gap (2021.9 -> 2026.6 is available on Windows), across C++, or on a project
   with a larger code delta is unknown. A larger jump is the obvious next run.
5. **`DROPPED_BY_VERSION` findings were not triaged.** The 3 `FORWARD_NULL`
   findings are labelled but nobody has read the traces to say whether the old
   analyzer was right. The label reports a transition; it does not claim the
   defect is real.
6. **The four-cell form was used to validate the three-cell form.** The claim
   that the production three-cell procedure suffices rests on the four-cell run
   showing no `CONTROL_FAILURE`. That has been observed once. Note that a
   three-cell run cannot detect `CONTROL_FAILURE` itself -- both its patterns
   involve the fourth cell -- so it inherits that assurance rather than
   re-establishing it.
7. **No eval set.** Unlike `coverity-defect-detectability`, this skill has not
   been tested by giving the task to a model with and without it.
