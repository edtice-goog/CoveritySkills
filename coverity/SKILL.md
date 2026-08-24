---
name: coverity
description: >
  General-purpose skill for working with Coverity Static Analysis: orienting
  in an installation, understanding what an intermediate directory contains,
  and -- above all -- verifying that a capture actually captured the code
  before anyone believes an analysis result. Use this skill for any Coverity
  question that is not already owned by a specialist skill: "did my scan
  work?", "why did Coverity only find N files?", "is this idir any good?",
  "what does cov-build's percentage mean?", "what should I check before
  trusting this report?", as well as general orientation questions about
  Coverity commands, the intermediate directory, and the capture-to-analysis
  pipeline. Also use it as the entry point that routes to the specialist
  skills for compiler configuration, build fidelity, and defect
  detectability. Carries the standing rules (RULES.md) that apply to any
  Coverity work regardless of the question being asked -- read them before
  running any Coverity command. Requires a local Coverity Analysis
  installation; this skill interrogates real intermediate directories rather
  than reasoning about what should have happened.
---

# Coverity

The umbrella skill. It owns what the specialist skills all depend on: where
the installation is, what an intermediate directory means, and whether the
capture under discussion is trustworthy enough to reason from.

## The rules

`RULES.md` is the standing list: the things that hold regardless of which
Coverity question you are answering. Each exists because ignoring it produces
a *confident wrong answer* rather than an error message. Read it before
running a Coverity command; read the full entry for any rule you are about to
lean on.

The two that come first:

1. **Always use a template compiler configuration.** `cov-configure
   --template` (or a language shortcut, which is already a template). A
   configure-time probe describes one invocation and is then applied to all of
   them; data captured under such a config is tainted, and it does not
   announce itself.
2. **Verify capture fidelity before believing any result.** *No Coverity
   result means anything until capture is verified.* Every downstream question
   silently assumes the code reached the analyzer, and that assumption fails
   often, fails quietly, and fails in the direction of looking *good*: a
   capture that emitted nothing reports 100%, produces no errors, and finishes
   fast. The check is short when things are fine.

The rest, in one line each -- full entries, with the failure mode and the
evidence, in `RULES.md`:

| # | Rule |
|---|---|
| 3 | Pin exactly one installation for the whole session; do not scan the disk |
| 4 | Read defaults and checker behaviour from the installation, not from memory |
| 5 | Configure every compiler-shaped executable the build invokes |
| 6 | Regenerate a tainted configuration, never patch it -- and replace the idir with it |
| 7 | `template-<name>-config-N` directories multiplying is the mechanism working |
| 8 | Capture into a fresh intermediate directory |
| 9 | Make sure the build under capture actually builds |
| 10 | Never quote a bare capture percentage -- report expected/captured/analyzable |
| 11 | `< 100%` is a question, not a verdict -- and 100% of nothing is still 100% |
| 12 | Always pass `--all` to `coverity list` |
| 13 | Use `cov-manage-emit list-capture-diagnostics` for per-TU truth |
| 14 | Empty `unconfigured-compilers` is a pass; missing `scan-transparency/` is not |
| 15 | Binary equivalence alone never proves capture worked |
| 16 | Locate where the pipeline narrowed before debating checkers |
| 17 | Run it; do not reason about whether a checker "should" fire |
| 18 | Security (taint) checkers need two switches |
| 19 | Several defaults suppress reports in ways that look like misses |
| 20 | Never let capture doubt leak into a "not found" verdict |
| 21 | Verdict first, then the evidence |
| 22 | Say what you did not check |
| 23 | Distinguish measured from reasoned |
| 24 | `coverity capture` runs buildless capture too — always pass the build command for C/C++ |
| 25 | On a CLI capture, read `output/cli-diagnostics.json` |
| 26 | Triage a sample of the results before anyone trusts the run |
| 27 | Never take the connection target from an auth key file |

Numbers are stable and citable. New rules take the next free number and are
filed under the section they belong to; a rule that turns out to be wrong is
marked superseded in place rather than renumbered.

## Where the specialist skills take over

| Question | Skill |
|---|---|
| "How do I set up `cov-configure`?" / unconfigured compilers / tainted config | `coverity-compiler-configuration` |
| "Did wrapping the build in `cov-build` change the binaries?" / release gating on binary equivalence | `coverity-build-fidelity` |
| "Can Coverity find *this* defect?" / which checker, which option, which taint flag | `coverity-defect-detectability` |
| Anything else, or you do not yet know which | here |

Hand off explicitly rather than half-doing a specialist's job. Capture
verification is the shared prerequisite for all three, and lives here so that
none of them has to own it.

## Step 0: Pin the installation

Ask the user, or check project notes and memory. **Do not scan the disk.**

Multiple versions side by side is the normal state of a Coverity user's
machine, not an anomaly -- pin exactly one for the whole session and record
which, because emit databases are version-sensitive and mixing tool versions
against one intermediate directory is its own failure mode.

`$BIN` below means `<install>/bin`. Useful landmarks inside an installation:

- `bin/` -- `cov-build`, `cov-analyze`, `cov-manage-emit`, `cov-configure`,
  and `coverity` (the CLI front end; a different, higher-level interface)
- `doc/en/help/*.help.txt` -- per-command reference, greppable, authoritative
- `doc/en/cov_checker_ref.html` -- checker documentation
- `doc/en/checker-enablement-and-option-defaults.html` -- what is on by default
- `VERSION` -- confirm the version you think you pinned

Read option tables and checker behaviour **from the installation**, not from
memory. Defaults move between releases.

## The pipeline, and where trust leaks out of it

Source on disk does not reach a checker in one step. It passes through a
chain of narrowing, and every arrow can drop things silently:

```
files in the tree
  -> files the build actually compiles         (build system decides)
  -> compilations Coverity intercepts          (compiler configuration decides)
  -> translation units emitted                 (cov-emit decides)
  -> TUs with a usable AST                     (parse success decides)
  -> functions analyzed                        (cov-analyze scope decides)
  -> defects reported                          (checkers and options decide)
```

Most "Coverity missed it" reports are a break in an early arrow being
diagnosed as a problem in the last one. Establish where the chain narrowed
before debating checkers. `references/capture-fidelity.md` measures the first
four arrows; `coverity-defect-detectability` owns the last two.

## Verifying capture: three methods, run independently

The core procedure. Full detail in `references/capture-fidelity.md`; the
shape of it:

1. **Method C -- independent expectation.** From the source tree and the
   build alone, *before looking at the intermediate directory*, state what
   should have been compiled. Freeze it to disk.
2. **Method A -- the capture inventory.** Ask Coverity what it has:
   `coverity list`, backed by `cov-manage-emit list-capture-diagnostics`.
3. **Method B -- scan transparency.** Read `idir/scan-transparency/`, which
   is derived from watching the build's process tree rather than from the
   emit database, and is therefore genuinely independent evidence.

Then adjudicate. **Method C must be produced and written down first**, because
it is the only one of the three that can be contaminated: once you have read
the emit inventory you will "expect" precisely what you just read, and the
corroboration becomes circular. A and B are mechanical and may run in either
order.

`tools/capture_fidelity.py` collects the evidence and enforces the freeze --
one subcommand per step, pure stdlib, no `pip install` on a build machine:

```bash
python3 tools/capture_fidelity.py expect     --project-dir <src>
# review the scaffold by hand, set decisions and reasons, mark it reviewed
python3 tools/capture_fidelity.py method-a   --bin $BIN --dir <idir> --project-dir <src>
python3 tools/capture_fidelity.py method-b   --dir <idir>
python3 tools/capture_fidelity.py adjudicate -o adjudication.md
```

The `expect` scaffold is a starting point for judgment, not a substitute for
it: it buckets files by pattern and marks everything non-obvious `REVIEW`.
Adjudicating against an unreviewed scaffold is flagged in the output, because
an auto-generated expectation corroborating an auto-generated inventory is
not evidence of anything.

The verdict is a triple -- expected, captured, analyzable -- plus a grade,
never a percentage on its own. Agreement between the three methods is the
evidence; the *pattern of disagreement* is the diagnosis, and
`references/capture-fidelity.md` carries the table that reads it.

`references/worked-example-vacuous-capture.md` is the calibration run behind
rule 9: the same project captured three ways -- no-op build, partial build,
clean build -- adjudicated against one frozen expectation, with what
`cov-build` said about each. Read it for what a real `VACUOUS` and a real
`SHORTFALL` look like, and for why the partial build is the dangerous one.

## Reading an intermediate directory

`references/idir-anatomy.md` maps the files and says what each one is
evidence of. Two things worth knowing before you open one:

- **A reused intermediate directory makes a broken capture look perfect.**
  Yesterday's translation units are still there. Capture into a fresh idir,
  or prove freshness from `build-cwd.txt` and file timestamps before
  reasoning from its contents. This is the exact counterpart of the
  build-fidelity trap where a capture that emitted nothing yields binaries
  byte-identical to native.
- **Emitted is not analyzable, and analyzable is not analyzed.** `cov-build`
  prints both "Emitted N ... successfully" and "N ... are ready for analysis"
  because they are different numbers; `output/summary.txt` prints a third,
  what cov-analyze actually consumed.

## Reporting

Shared conventions across this project's skills:

- **Verdict first.** Lead with the answer, then the evidence for it.
- **Expressiveness on disk, verdict in chat.** A `report.md` a person can
  act on, plus a machine-readable sidecar for downstream inference.
- **Formal register.** These reports travel to people who were not in the
  room; state scope limits explicitly, and never let a green result imply
  more than it measured.
- **Say what you did not check.** "Capture verified for the C/C++ product
  sources; the vendored `libfoo` was prebuilt and never captured" is a
  useful, honest result. An unqualified green check is not.
