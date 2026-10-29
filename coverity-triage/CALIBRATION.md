# Calibration status

This project's standard is that factual claims in a skill were established by
real runs. This file records what was run for `coverity-triage`, on what, and
what is reasoned rather than measured.

## Verified by direct execution

- **The tools, on a generated fixture** (`evals/test_tools.py`, git and
  Python 3 only).
  - **`bundle.py`:**
    - `--plan` writes nothing, and the selection is deterministic.
    - Source comes from `git show <tag>:<path>`, not the working tree; the
      fixture changes the working tree after tagging.
    - A form feed in the source does not shift excerpts.
    - A merge key reported at two sites bundles both.
    - Refused: nothing selected; a merge key not in the findings; no source;
      both sources; `--idir` without `--cov-bin`; `--git-repo` without
      `--tag`.
  - **`lanes.py`:**
    - The skill's checker table validates.
    - Eleven malformed rows are refused: lane and candidates together, or
      neither; an unknown lane; one candidate; Policy as a candidate;
      candidates without `decide`; a fixed lane without `why`; a method on a
      Policy row; `None` as a row method; a route without verify; an unknown
      route.
    - `assign` fixes the table's lanes, including Intent, Policy and Other;
      leaves a candidate checker pending with its candidates; marks a checker
      no table has as unplaced; and, with a producer's table, places that
      checker with its own method and route.
  - **`records.py`:** one good assembly, and twenty-two refusals, each writing
    nothing:
    - a global invariant with no location;
    - a word outside the verdict set;
    - a NUL in a comment;
    - a missing verdict;
    - a verdict read in the wrong lane;
    - an unassigned finding;
    - an unknown lane;
    - a finding still pending;
    - inference choosing outside the candidates;
    - inference by a model that is not the plan's assigner;
    - a table entry that carries candidates;
    - a verdict for Other;
    - a verdict for Policy;
    - an override on a Policy finding;
    - a plan without Intent;
    - a plan that lists Policy;
    - an unknown verify route;
    - a method that is not the finding's;
    - `executed` claimed by a reader;
    - an off-lane finding with no recorded choice;
    - an override with no reason;
    - a route on an override that is not verify.

    Shown working:
    - a checker's own method beats the lane's plan, and verify's route and
      inventory are carried into the evidence;
    - a plan-wide route beats a row's route;
    - verify planned for the Contract lane is accepted;
    - overrides for verify-anyway, another lane's method and
      leave-untriaged;
    - Policy is never off-lane;
    - `check-lanes` lists every off-lane finding;
    - a comment over 4,000 characters is shortened.

- **One end-to-end reading run, 2026-10-24**, before the lanes were revised.
  - **Corpus:** proftpd v1.3.9 findings (`cov-format-errors --json-output-v10`,
    Coverity 2025.9.0, analysis defaults: 147 reports, 112 merge keys, 13
    checkers), with source from a clone at tag `v1.3.9`.
  - **Selection:** `--per-checker 2`, 24 findings, 4 of them merge keys
    reported at more than one site.
  - **Lanes:** three method lanes plus Other, with an LLM assigning all 24.
    Lane assignment and all three reading lanes ran on Sonnet 5.5: one
    subagent for the assignment, and four readers (one each for construction
    and contract, two batches of seven for value or path).
  - **Assembly:** `records.py assemble` and `validate` passed on the first
    attempt, and every global-invariant dismissal carried its three parts.

  | lane | findings | real, low severity | intentional | false positive - global invariant | no verdict |
  |---|---|---|---|---|---|
  | Construction | 5 | 4 | 1 | 0 | 0 |
  | Contract | 4 | 2 | 0 | 2 | 0 |
  | Value or path | 14 | 2 | 4 | 8 | 0 |
  | Other | 1 | | | | 1 |

  No `real`, no `unresolved`, and no `wrong lane` came back from any reader.
  Other held the one COPY_PASTE_ERROR.

  **Cost, measured:** about 1.04 M subagent tokens for the 24 findings,
  roughly 43 k per finding. The lane assignment alone was 198 k. Wall clock
  per reader batch was 5 to 13 minutes, the longest being the seven
  value-or-path findings that needed the most callee reading.

- **The checker table, applied, 2026-10-28.** This measures lanes only; no
  verdict was re-run.
  - **All 112 proftpd v1.3.9 merge keys:** `lanes.py assign` placed 110 from
    the table. The 2 NEGATIVE_RETURNS findings are left for inference, and
    nothing is unplaced. The 2026-10-24 run spent 198 k tokens assigning 24
    findings by inference.
  - **The 2026-10-24 run's 24 bundles:** 22 placed from the table. 8 change
    lane, all to Intent:
    - COPY_PASTE_ERROR from Other;
    - MISSING_BREAK and both SIZEOF_MISMATCH from Construction;
    - both DEADCODE and both UNUSED_VALUE from value or path.

    The 2 NEGATIVE_RETURNS are pending, and the other 14 keep the lane the
    LLM gave them.

- **The idir as the backup source, 2026-10-24.**
  - **Against git:** the same 24 proftpd v1.3.9 findings, bundled with
    `--idir` (the analyzed idir) and `--cov-bin` of the 2025.9.0 installation
    that wrote it, on Windows, came out byte-identical to the git-sourced
    bundles, in about a second. The extracted `modules/mod_log.c` was
    byte-identical to `git show v1.3.9:modules/mod_log.c`.
  - **Matching files:** `extract-files` did not match the recorded paths
    given as file names, but did match by `--regex`. The tool therefore
    matches by path suffix, and finds each file through the
    `emit-file-map.json` it writes.
  - **Refusals,** on a one-file idir emitted for the test: a `--cov-bin` of
    2026.9.0; a copy re-filed under another host name (with the tool's own
    `reset-host-name` message, leaving the copy unchanged); both sources; no
    source; `--idir` without `--cov-bin`.
  - **Not run:** a Linux installation reading a Linux capture.

## What the run showed, and what changed

- **The construction lane was answering two kinds of claim.** The run's
  assigner put Y2K38_SAFETY, SIZEOF_MISMATCH and MISSING_BREAK in
  Construction because none of them traces a path. Two corrections
  followed.
  - **Y2K38_SAFETY stays in Construction.** A construct that does the wrong
    thing for part of its input is a defect, and it is not dismissed by how
    large a value can get or how long that takes. The run's `real, low
    severity` on both Y2K38_SAFETY findings stands. The alternative reading,
    that truncating an uptime is an environment invariant because it needs
    decades of uptime, is the argument the lane rules out. `reading.md` no
    longer carries that example.
  - **Intent claims got a lane of their own:** well-defined code whose
    author's intent is in doubt. They are MISSING_BREAK, SIZEOF_MISMATCH,
    COPY_PASTE_ERROR (which the run left in Other, with no verdict), and
    DEADCODE and UNUSED_VALUE. The run's value-or-path reader had settled
    those last two as intent questions rather than path questions: 4 of its
    14 findings.
  - **Rule matches got Policy,** which takes no triage.
  - **Lane assignment moved to a checker table,** with inference kept for the
    checkers whose findings vary.
- **Readers were not independent of the examples.** Several examples in
  `references/reading.md`, `references/lanes.md` and `references/records.md`
  come from the same corpus the run read. A reader given the shape of an
  answer is not a blind reader, so examples should come from the skill's own
  fixtures. Open.
- **Side findings have no field.** One reader reported two possible defects
  next to the findings it was given. Records carry verdicts on the selected
  findings only, so a side finding today can only go in `reason`. Open.

## Reasoned, not measured

- **Accuracy.** No verdict here was compared with a reference. A second
  reading of the run's 23 verdicts, against the code and callees each one
  cites, found every argument held. That is a reading, not a reference. The
  run tested the mechanics.
- **The checker table.**
  - Its 96 rows were placed from each checker's description in the
    2025.9.0 checker reference, not from findings. Only 13 of them have met
    real findings, all on proftpd.
  - Which checkers vary enough to need candidates, and which candidates
    they get, is reasoned from those descriptions.
  - Checkers outside C (and C++-only checkers) have no rows yet. A finding
    from one is unplaced, and its checker is placed once before anything
    runs.
- **The Intent lane's questions.** No reader has run them yet.
- **Policy.** No Policy finding has gone through; none fired on proftpd at
  analysis defaults.
- **The execution method end to end.**
  - The mapping from `coverity-verify`'s tiers (`references/records.md`) is
    written from verify's documented tiers, and no finding has yet gone
    through triage into verify and back.
  - The route preference and the carried-over route fields follow verify's
    documented record (`route`, `as_code`, `stubbed`).
- **Applying records to Connect.**
  - The records use the attribute names of Connect's triage-store export and
    the REST triage write.
  - No apply was run from this skill, which writes files only.
  - The two custom attributes must exist, with every value, before anything
    can set them.
- **Model choice per lane.** One model was used for every step. Whether a
  cheaper model suffices for some lanes is untested.
