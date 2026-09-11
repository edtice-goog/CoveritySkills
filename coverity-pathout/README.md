# coverity-pathout

Part of [CoveritySkills](../README.md).

Diagnoses a Coverity **PATHOUT** notice: a function on which `cov-analyze`
hit its per-function path limit (`--paths`, default 5000) and stopped. The
skill finds the functions, names the checker that ran out of paths, runs a
catalogue of path-insensitive shape checkers over the idir to see what that
checker might have said about the code it never finished walking, gets the
function in front of you as the analyzer saw it, and measures what the
cut-off cost -- so the recommendation is "two candidates behind the limit,
one confirmed by execution; raise `--paths` to 35,000, verified on the
whole project, zero defects changed" or "split it here", not a guess from
cyclomatic complexity.

## The three things it knows that save the most time

**The limit counts paths x state, not control-flow paths.** Two functions
with identical control flow (14 independent `if`s, complexity 15, 16,384
static paths) behave completely differently: the one whose accumulator
starts at a known constant explores all 16,384 and trips the limit; the one
whose accumulator starts unknown explores 106. Every checker walks the
function with its own state and its own count; the limit trips when one of
them exceeds it. So the diagnosis comes from the analyzer's own
`--print-paths` output --

```
wur_diagnostics: Pathed out: 5001 paths traversed by REVERSE_INULL in "setup_env(pool *, cmd_rec *, char const *, char *)"
```

-- which names the function *and* the checker, and works even when the
log's own `PATHOUT=` lines are per-batch and name nothing (on a large
project under `--all --aggressiveness-level high`, that is 186 of 189).

**Inside a PATHOUT function, nobody looked -- so look there with a checker
that does not need paths.** The checker that pathed out finished nowhere
in that function. A *path-insensitive* CodeXM checker for the shape of
what it looks for runs over the whole idir in seconds, and its hits are
filtered to the PATHOUT functions where that checker was the one cut off;
everywhere else the path-sensitive checker finished and was right to stay
quiet. Twelve tested shapes live in
[pathout-shapes](https://github.com/edtice-goog/pathout-shapes) and run in
one pass; the filter is `tools/pathout_filter.py --relevant auto`. On
nginx: 159 hits, 4 in PATHOUT functions, 2 where the relevant checker
pathed out. On subversion, keyed on an escaped null dereference: 503, 115,
0 (27 with the reverse shape counted; all 27 refuted by reading). The
survivors are read, and what reading cannot settle goes to
`coverity-fuzz-triage` to be run.

**The cost of the notice is measured, on the whole project.** `--paths N
--print-paths` on a copy says how many paths each function needed, and a
defect diff between the default and raised runs says what the cut-off hid.
Scoping with `--tu` is fast but drops the models of callees in other
translation units: on nginx it reproduced 11 of 18 PATHOUTs. On nginx at
50,000 the defect set was identical and two functions still did not
finish; one of them drops from 5001 to 64 paths when its loop nest moves
into a helper, measured on the slice.

## What is in it

| | |
|---|---|
| `SKILL.md` | the procedure: log -> `--print-paths` -> shape catalogue and filter -> body -> diagnose -> measure -> report |
| `references/analysis-log.md` | where the notice lives (only `output/analysis-log.txt`), the four kinds of line, batches, what `--path-log-threshold` does not do |
| `references/path-explosion.md` | the evidence for paths x state, why APC and CCM do not predict it, which checkers path out most, what the limit costs |
| `references/worked-example-setup-env.md` | proftpd's `setup_env` end to end, including the raised-limit defect diff |
| `references/escape-hunt.md` | shape checker over the idir, PATHOUT filter, the refutation catalogue, what to hand back |
| `references/candidate-checkers.md` | writing a path-insensitive CodeXM checker: the skeleton, the tree shapes, the grammar traps |
| `tools/pathout_report.py` | one command: log + `FUNCTION.metrics` join, batch detection, optional AST extraction of every affected function |
| `tools/pathout_filter.py` | keep the shape checkers' hits that sit in PATHOUT functions where a relevant checker pathed out (`--relevant auto` for the catalogue) |
| `evals/` | the paths-x-state fixture, the tested shape checker with its fixture, and a script that runs them on your installation |
| `CALIBRATION.md` | what was measured, on what, and what was not |

The function body, the standalone slice and the obfuscated twin are
[`coverity-function-slice`](../coverity-function-slice/README.md); running a
candidate to confirm or refute it is
[`coverity-fuzz-triage`](../coverity-fuzz-triage/README.md). This skill
calls both; install the three together.

## Requirements

- A local Coverity Analysis installation **of the version that wrote the
  intermediate directory** (`emit/version`, line 1). Developed and measured
  against 2025.9.0, 2026.3.0 and 2026.6.0 on Windows.
- Python 3 for the tools (standard library only).
- `git` to fetch the shape catalogue.

## Install

```bash
cp -r coverity-pathout coverity-function-slice coverity-fuzz-triage ~/.claude/skills/
```

Then: "the analysis log says 189 functions exceeded the path limit -- which
ones, and is it a problem?" or "here is my idir and there is a PATHOUT;
what is hiding behind it?"

## Development notes

Every claim was established by running it; `CALIBRATION.md` lists what, on
which version, and what was reasoned rather than measured. The fixtures were
written to falsify the obvious hypothesis (that branch count predicts
PATHOUT) and did; the subversion runs were repeated under two
configurations to establish that the notice count is a property of the
checker set; the worked example includes the measured defect difference at
a raised limit, which for that function was zero. A blind run of the skill
by another model on nginx (2026-09-10) did Steps 0-2 and 4-6 well and
skipped the catalogue because nothing had escaped; Step 3 is worded the way
it is because of that.
