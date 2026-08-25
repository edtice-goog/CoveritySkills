# CoveritySkills

Skills that teach an AI coding assistant how to use
[Coverity Static Analysis](https://www.blackduck.com/static-analysis-tools-sast/coverity.html)
properly — built for Claude, and useful to read even if you never run them.

## Why you would want these

Coverity is a good tool that fails in a bad way: **its most common failure
modes are silent, and they look like success.**

A build that compiled nothing still reports `100%`. A compiler configured the
wrong way still captures data — just data that describes a compiler your build
never invoked. An intermediate directory left over from yesterday answers
today's questions perfectly well. In every one of those cases the scan
finishes, the exit code is zero, and somebody signs off on a clean result that
measured nothing.

Point an AI assistant at Coverity without help and it walks into these
confidently. These skills stop that. They carry:

- **The rules that prevent the expensive mistakes** — configure this way,
  never that way; verify before you believe; what a percentage does and does
  not mean.
- **Procedures that produce evidence instead of opinions** — "can Coverity
  find this bug?" answered by running it, with the command line to reproduce.
- **The undocumented details** that cost an afternoon to discover — flags
  that exist but aren't in the manual, fields that mean something other than
  their name, defaults that suppress the very finding you are looking for.

The practical payoff: scans you can trust, mistakes you never make twice, and
a lot of time not spent re-running a four-hour build to find out why a report
looked wrong.

## Start here: the rules

The [`coverity`](coverity/README.md) skill carries **`RULES.md`** — the
standing list that applies to any Coverity work, whatever you are doing. It is
worth reading on its own. A sample:

> **1.** Always use a template compiler configuration — a configure-time probe
> describes one invocation and is then applied to all of them.
>
> **2.** Verify capture fidelity before believing any result — no Coverity
> result means anything until capture is verified.
>
> **9.** Make sure the build under capture actually builds — the partial build
> is the dangerous one: it reports 100% and "completed successfully" while
> four fifths of your project is missing.

Each rule says what goes wrong, how to check, and whether the claim was
verified by running it or reasoned from mechanism.

## The skills

| Skill | Use it when | What it gets you |
|---|---|---|
| [coverity](coverity/README.md) | Any Coverity question — start here | The rules, plus the capture-fidelity check every other skill depends on |
| [coverity-compiler-configuration](coverity-compiler-configuration/README.md) | Setting up `cov-configure`, especially cross-compilers and wrappers | A configuration that captures your real build, not a guess about it |
| [coverity-defect-detectability](coverity-defect-detectability/README.md) | "Why didn't Coverity find this?" / "Which checker catches it?" | An empirical verdict, the minimal setting that reports the defect, and a repro command |
| [coverity-build-fidelity](coverity-build-fidelity/README.md) | Release gating: did wrapping the build in `cov-build` change the product? | Proof that the binaries are equivalent — paired with capture coverage, so an empty scan can't pass |
| [coverity-recreate-from-emit](coverity-recreate-from-emit/README.md) | The build can't be re-run, or is too slow to re-run | An analyzable intermediate directory without the original toolchain — or a fast incremental update instead of a full rebuild |
| [coverity-issue-transition-inference](coverity-issue-transition-inference/README.md) | After an upgrade: "did I write this bug, or did the tool change?" | The missing control — old code analyzed by the new analyzer — which splits a confounded delta in two |
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

Then just ask in plain language — "did my scan actually capture anything?",
"can Coverity find the bug in this file?", "set up cov-configure for our ARM
toolchain" — and the matching skill triggers.

Take `coverity` even if you only want one of the others: it owns the
capture-verification step the rest depend on.

## How this project treats facts

The standard here is that a factual claim in a skill was **established by
running the command**, not remembered. Where that has not happened yet, the
text says so: each skill's `CALIBRATION.md` separates what was measured from
what is reasoned from mechanism, and keeps a queue of the experiments still
outstanding. When one of those runs and contradicts the guess, the guess gets
corrected — rule 9 was rewritten that way after measurement showed the
dangerous case was the opposite of the assumed one.

If you are betting something important on a claim in here, check the
calibration file before you do.

---

Not affiliated with or endorsed by Black Duck Software. "Coverity" is their
trademark; this is an independent set of notes and tools for using their
product well.
