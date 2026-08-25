# coverity-issue-transition-inference

Part of [CoveritySkills](../README.md).

Answers the question a team asks the morning after a Coverity upgrade:
**did I write this bug, or did the tool change?** — and its neglected mirror,
*did I actually fix this, or did the tool stop reporting it?*

A finding delta after an upgrade confounds two causes at once, so it cannot be
attributed from the two snapshots a user has. The skill produces the cell they
don't have — **the old code analyzed by the new analyzer** — which splits one
confounded delta into two clean ones. Same shape as `coverity-build-fidelity`:
no attribution without a control.

The production procedure is anchored to the user's own reality: reproduce their
last automated result with the old analyzer *first*. A delta measured against a
result you could not reproduce is uninterpretable.

## What the skill knows that saves time

- **The user's question is binary.** Whether a version-attributable finding came
  from a newly-default checker, a smarter checker, or a front-end change is a
  tool-vendor distinction — real, but it doesn't change what anyone does next.
  It is a sub-field, never the headline
- **Configuration masquerades as capability, at scale.** Measured across one
  upgrade: 54 findings new on *identical code*, **50 of them one checker**
  moving Optional → Default. 93% of an apparent improvement was a default flip,
  predictable from the installation's own docs before any analysis ran
- **…and a real bug can hide inside that wave.** The 51st `NULL_FIELD` was a
  genuine new defect in a function added that release. Filtering by checker —
  the obvious heuristic when 50/51 are noise — discards it. **Only the control
  run finds it**: the old analyzer never reports it at all, so the cheaper
  `(C2,A1)` diagonal cannot see it
- **Merge keys are path-independent** — measured, and it corrected a claim in
  `coverity-demo-data`. A field reproduction does not have to rebuild at the CI
  path, which makes the anchor step far more practical than it first appears
- **The anchor reproduces exactly.** An independent rebuild gave an identical
  merge-key *set*, not merely an identical count
- **Capture is licence-free by design; analysis is not.** That is what makes
  capture-on-an-ephemeral-agent / analyze-on-a-licensed-host supported. Point
  `cov-analyze` at a licence with `--security-file`; licence files are
  cross-platform, and `cov-format-errors` needs it too
- **Never diff raw merge keys between local result sets** (rule 27) — that path
  cannot see antecedent keys and manufactures the false transitions this skill
  exists to prevent. Let Connect line them up
- A four-cell factorial that makes the labels **falsifiable**: with the code
  proven constant, no finding can require *both* the new code and the new
  analyzer, so a diagonal-only pattern is a control failure, not a finding

## Layout

```
coverity-issue-transition-inference/
├── SKILL.md                          # anchor → rebuild → analyze → attribute
│                                     #   → annotate → report
├── CALIBRATION.md                    # measured vs reasoned, and the queue
├── references/
│   └── worked-example-proftpd.md     # the 2x2 calibration, with the numbers
└── tools/
    ├── transition.py                 # CID-by-cell matrix from Connect + labels
    └── checker_defaults.py           # enablement diff between two installs
```

Status: validated on a full 2×2 factorial — proftpd v1.3.8/v1.3.9 × Coverity
2024.12.1/2025.12.2, 117 CIDs labelled, build fidelity `K` empty and capture
equivalence established per cell. **Rule 27 remains unexercised**: raw merge
keys and Connect CIDs agreed exactly (59/59), so the antecedent path never
fired — the exception rate is measured at 0 of 59 for this version pair, which
is not evidence that the mechanism works. A wider version jump and a real
customer snapshot as the anchor are the next runs.
