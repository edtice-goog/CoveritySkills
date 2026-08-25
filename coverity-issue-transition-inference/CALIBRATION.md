# Calibration status

This project's standard is that factual claims in a skill were established by
real runs. This file records where `coverity-issue-transition-inference` stands,
so that nothing unverified reads as measured.

Environment for everything marked verified: Windows 11 with Coverity
installations under `C:\Coverity\`, WSL2 Ubuntu with gcc 13.3.0, and a local
Coverity Connect 2025.12.0. Subject: proftpd v1.3.8 and v1.3.9 built from a
fixed tree at `~/iti/proftpd`, serial `make`, 90 TUs per cell at 100%. Analyzer
versions 2024.12.1 and 2025.12.2. Session run 2026-08-24.

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

## Limits of the evidence

These are the boundaries of what has been measured, kept here so a claim's
provenance is never guessed at (rule 23). They are limits of the evidence,
not missing pieces of the skill: the procedure is complete and each item
below tells you which specific claim to treat as reasoned rather than
measured, and what would settle it.

1. **Rule 27 is still unexercised.** Raw merge keys and Connect CIDs agreed
   exactly (59/59), so the antecedent-merge-key path never fired. The exception
   rate is measured at 0 of 59 *for this version pair*, which is not evidence
   that the mechanism works. A case where a key genuinely moves is still owed,
   and until one is found, "compare through Connect" rests on stated domain
   knowledge rather than a demonstration.
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
6. **The four-cell form was used to validate the two-cell form.** The claim that
   the production two-cell procedure suffices rests on the four-cell run showing
   no `CONTROL_FAILURE`. That has been observed once.
7. **No eval set.** Unlike `coverity-defect-detectability`, this skill has not
   been tested by giving the task to a model with and without it.
