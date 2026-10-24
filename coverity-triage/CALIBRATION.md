# Calibration status

This project's standard is that factual claims in a skill were established by
real runs. This file records what was run for `coverity-triage`, on what, and
what is reasoned rather than measured.

## Verified by direct execution

- **The tools, on a generated fixture** (`evals/test_tools.py`, git and
  Python 3 only). `bundle.py`: `--plan` writes nothing; the selection is
  deterministic; source comes from `git show <tag>:<path>`, not the working
  tree (the fixture changes the working tree after tagging); a form feed in
  the source does not shift excerpts; a merge key reported at two sites
  bundles both; nothing selected, or a merge key not in the findings, is
  refused. `records.py`: one good assembly; thirteen refusals, each
  writing nothing (a global invariant with no location, a word outside the
  verdict set, a NUL in a comment, a missing verdict, a verdict read in the
  wrong lane, an unassigned finding, an unknown lane, a verdict for Other, a
  method that is not the plan's, execution planned for the contract lane,
  `executed` claimed by a reader, an off-lane finding with no recorded
  choice, an override with no reason); overrides for verify-anyway, another
  lane's method and leave-untriaged; `check-lanes` listing every off-lane
  finding; a comment over 4,000 characters shortened.

- **One end-to-end reading run, 2026-10-24.** proftpd v1.3.9 findings
  (`cov-format-errors --json-output-v10`, Coverity 2025.9.0, analysis
  defaults: 147 reports, 112 merge keys, 13 checkers); source from a clone at
  tag `v1.3.9`. Selection `--per-checker 2`: 24 findings, 4 of them merge keys
  reported at more than one site. Lane assignment and all three reading lanes
  on Sonnet 5.5, one subagent for the assignment and four readers (one each
  for construction and contract, two batches of seven for value or path).
  `records.py assemble` and `validate` passed on the first attempt; every
  global-invariant dismissal carried its three parts.

  | lane | findings | real, low severity | intentional | false positive - global invariant | no verdict |
  |---|---|---|---|---|---|
  | Construction | 5 | 4 | 1 | 0 | 0 |
  | Contract | 4 | 2 | 0 | 2 | 0 |
  | Value or path | 14 | 2 | 4 | 8 | 0 |
  | Other | 1 | | | | 1 |

  No `real`, no `unresolved`, no `wrong lane` from any reader. Other held
  the one COPY_PASTE_ERROR.

  **Cost, measured:** about 1.04 M subagent tokens for the 24 findings,
  roughly 43 k per finding; the lane assignment alone was 198 k. Wall clock
  per reader batch: 5 to 13 minutes, the longest the seven value-or-path
  findings that needed the most callee reading.

## What the run showed that the text must answer

- **The lane decides the question, so it can decide the verdict.** The
  assigner put Y2K38_SAFETY, SIZEOF_MISMATCH and MISSING_BREAK in
  Construction, because each claim holds whatever data reaches the code. The
  construction reader, told feasibility does not enter, graded both
  Y2K38_SAFETY findings `real, low severity`; read in value or path, the
  same truncation of an uptime is a global invariant (about 68 years of
  uptime). The construction lane is meant for constructs the organization
  has chosen to disallow; `references/lanes.md` question 1 is broader than
  that and needs narrowing, or the organization's checker table has to place
  such checkers. Open.
- **Readers were not independent of the examples.** Several examples in
  `references/reading.md` and `references/lanes.md` come from the same
  corpus the run read. A reader given the shape of an answer is not a blind
  reader. Examples should come from the skill's own fixtures. Open.
- **Side findings have no field.** One reader reported two possible defects
  next to the findings it was given. Records carry verdicts on the selected
  findings only; a side finding today can only go in `reason`. Open.

## Reasoned, not measured

- **Accuracy.** No verdict here was compared with a reference. The run tested
  the mechanics, not whether the verdicts are right.
- **The execution method end to end.** The mapping from `coverity-verify`'s
  tiers (`references/records.md`) is written from verify's documented tiers;
  no finding has yet gone through triage into verify and back.
- **Applying records to Connect.** The records use the attribute names of
  Connect's triage-store export and the REST triage write; no apply was run
  from this skill, which writes files only. The two custom attributes must
  exist, with every value, before anything can set them.
- **Model choice per lane.** One model was used for every step. Whether a
  cheaper model suffices for some lanes is untested.
