# CoveritySkills

Skills that teach an AI coding assistant how to use
[Coverity Static Analysis](https://www.blackduck.com/static-analysis-tools-sast/coverity.html)
properly — built for Claude, and useful to read even if you never run them.

## Why you would want these

Coverity is a deep and highly configurable analyzer. It is built to do
something sensible on any codebase out of the box, **and** to be tuned hard
for a particular one — a real toolchain, a specific defect class, a team's own
conventions. **The distance between those two is where the value is**, and
these skills are about closing it deliberately rather than by trial and error.

Most of that comes down to knowing where the leverage sits:

- **Setup decisions that compound.** Configure so the analyzer models every
  compiler invocation your build actually makes, and everything downstream
  gets more accurate for free.
- **Knowing what you measured.** Capture is a chain from source file to
  checker. Confirming how much of the project came through takes minutes, and
  it turns a result into a number you can put a scope on — *"verified across
  the C/C++ product sources; the vendored library was prebuilt and not
  captured."*
- **Tuning aimed at a question.** "Can Coverity find this bug?" answered by
  running it, then narrowed to the minimal checker and option that reports
  it — so you turn on what earns its keep instead of everything.
- **The undocumented details** that otherwise cost an afternoon: fields and
  flags that are not in the manual, and defaults that are off for good reasons
  you may not share.

The practical payoff is more real defects per run, results you can put your
name on, and much less time spent re-running long builds to work out why a
report looked off.

An AI assistant makes this materially easier — the checking and tuning is
exactly the patient, repetitive work it is good at — but only if it knows
these things. That is what the skills carry.

## Start here: the rules

The [`coverity`](coverity/README.md) skill carries **`RULES.md`** — the
standing list that applies to any Coverity work, whatever you are doing. It is
worth reading on its own. A sample:

> **1.** Always use a template compiler configuration — so the analyzer models
> each set of arguments your build actually compiles with, discovered from the
> build itself.
>
> **2.** Verify capture fidelity before interpreting a result — every
> conclusion downstream assumes the code reached the analyzer, and confirming
> it is quick.
>
> **9.** Make sure the build under capture actually builds — the capture
> percentage is measured against what the build attempted, so an incremental
> build can legitimately report 100% of a fraction of your project.

Each rule says what it buys you, how to check it, and whether the claim was
verified by running it or reasoned from mechanism.

## The skills

| Skill | Use it when | What it gets you |
|---|---|---|
| [coverity](coverity/README.md) | Any Coverity question — start here | The rules, plus the capture-fidelity check every other skill depends on |
| [coverity-compiler-configuration](coverity-compiler-configuration/README.md) | Setting up `cov-configure`, especially cross-compilers and wrappers | A configuration that models your real toolchain, including cross-compilers and wrappers |
| [coverity-defect-detectability](coverity-defect-detectability/README.md) | "Which checker catches this?" / tuning for a defect class you care about | An empirical verdict, the minimal setting that reports the defect, and a repro command |
| [coverity-build-fidelity](coverity-build-fidelity/README.md) | Release gating: did wrapping the build in `cov-build` change the product? | Evidence that the product is unchanged, paired with capture coverage so the result is meaningful in both directions |
| [coverity-recreate-from-emit](coverity-recreate-from-emit/README.md) | The build can't be re-run, or is too slow to re-run | An analyzable intermediate directory without the original toolchain — or a fast incremental update instead of a full rebuild |
| [coverity-issue-transition-inference](coverity-issue-transition-inference/README.md) | After an upgrade: separating new findings from new analyzer behaviour | The missing control — old code analyzed by the new analyzer — which splits a confounded delta in two |
| [coverity-demo-data](coverity-demo-data/README.md) | Building a demo or training dataset with realistic defect history | A Connect instance whose issue history looks like a decade of real development |

## Requirements

- A **local Coverity Analysis installation.** These skills interrogate real
  installations and real intermediate directories rather than reasoning about
  what should have happened. Developed against 2026.6.0 and 2026.3.0 on
  Windows; option tables and checker docs are read from your installation, so
  other recent versions should work.
- **Claude Code**, or another Claude agent harness with shell access.
- **Python 3** for the bundled tools — pure standard library, so there is
  nothing to `pip install` on a build machine.

## Install

Copy the skill directories you want into your skills directory:

```bash
cp -r coverity coverity-compiler-configuration ~/.claude/skills/
```

Then just ask in plain language — "how much of my project did that scan
cover?", "can Coverity find the bug in this file?", "set up cov-configure for
our ARM toolchain" — and the matching skill triggers.

Take `coverity` even if you only want one of the others: it owns the
capture-verification step the rest depend on.

## How this project treats facts

The standard here is that a factual claim in a skill was **established by
running the command**, not remembered. Where that has not happened yet, the
text says so: each skill's `CALIBRATION.md` separates what was measured from
what is reasoned from mechanism, and keeps a queue of the experiments still
outstanding. When one of those experiments contradicts what the text assumed,
the text changes — rule 9 was rewritten that way, after a calibration run
showed the mechanism behaving differently from the write-up.

If you are betting something important on a claim in here, check the
calibration file before you do.

---

Not affiliated with or endorsed by Black Duck Software. "Coverity" is their
trademark; this is an independent set of notes and tools for using their
product well.
