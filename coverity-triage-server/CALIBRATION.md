# Calibration status

This project's standard is that factual claims in a skill were established
by real runs. This file records what was run for `coverity-triage-server`,
and what is reasoned.

## Verified by direct execution

Nothing yet. No service has run this skill.

What it shares with `coverity-triage` was measured there
(`coverity-triage/CALIBRATION.md`): the checker table, the compiler-header
rule, the verdict set and the recommended actions on one real run, and the
derived models. `cov-find-function --save` produced readable models for
the callees of a 21-finding sample of a C project, and 9 of the 21 callees
had one; the rest were library functions.

## Reasoned, not measured

- **That the stored source and the models are enough** for the readings
  this skill renders, and that a reading stops at `unresolved` when they
  are not.
- **That the lane and the method a service gets here match**
  `coverity-triage`'s for the same finding. They come from the same table
  and rules, but no run has compared them.
