# coverity-defect-detectability

Part of [CoveritySkills](../README.md).

Answers "Can Coverity find this defect?" empirically — by capturing the code
and running real `cov-analyze` escalation runs until the defect is reported
(or the ladder is exhausted), then minimizing to the exact checker, option,
or taint flag responsible. The deliverable is a verdict backed by actual
analysis runs plus the command line to reproduce it.

Built for people who **have Coverity installed** and field questions like:

- "Another tool flags this — why doesn't Coverity?"
- "Which checker (and which option) catches this?"
- "An RFP sample got zero defects at defaults — what do we turn on?"
- "A colleague claims Coverity can't detect this. True?"

Many such questions come from synthetic test suites that aren't
representative of real code — but they arrive en masse, and this skill exists
to answer them quickly, correctly, and reproducibly on a mid-tier model
(developed and tested end-to-end with Claude Opus subagents).

## What the skill knows that saves time

- An escalation ladder from bare defaults through aggressiveness levels,
  `--all`, audit mode, and targeted enablement — with the false-positive cost
  of each rung
- Security (taint) checkers need **two** switches: checker enablement *and* a
  `--distrust-*` source (and stdin counts as *filesystem* taint)
- A table of deliberate default suppressions that masquerade as misses
  (`RESOURCE_LEAK:allow_main`, `UNINIT:enable_write_context`, statistical
  `stat_threshold` checkers, default-off `STRING_OVERFLOW`, ...)
- Capture tactics for code that doesn't build: prototype fast-path, real
  build capture, the canary-defect probe, and why capture doubt must never
  leak into a "not found" verdict
- Report craft: verdicts that lead with the answer, annotated traces instead
  of tool dumps, formal register (reports travel), and honest handling of
  test files whose planted defect isn't quite a defect

## Requirements

- A local Coverity Analysis installation (developed against 2026.6.0; the
  skill reads option tables and checker docs from the installation itself, so
  other recent versions should work)
- Claude Code (or another Claude agent harness with shell access)
- For C code that includes system headers: any real compiler (gcc/clang/MSVC)
  that `cov-configure` can wrap

## Install

Copy `coverity-defect-detectability/` into your skills directory, e.g.:

```bash
cp -r coverity-defect-detectability ~/.claude/skills/
```

Then ask Claude things like "can Coverity find the bug in this file?" — the
skill triggers on detectability questions and walks the procedure.

## Layout

```
coverity-defect-detectability/
├── SKILL.md                    # the procedure (locate install → pin defect →
│                               #   capture → escalate → minimize → report)
├── references/
│   ├── escalation.md           # ladder details, security two-switch rule,
│   │                           #   statistical checkers, frequent culprits
│   ├── capture.md              # cov-emit vs cov-build, stubbing safely,
│   │                           #   canary probe, capture-doubt principle
│   ├── worked-example-uninit.md# real end-to-end session
│   └── csharp.md               # C# capture route
└── evals/
    ├── evals.json              # test prompts + assertions used to develop it
    └── fixtures/               # the defect samples the evals run against
```

## Development notes

The skill was developed iteratively: every factual claim in the references
was verified by real runs against Coverity 2026.6.0 on Windows, and each
revision was tested by giving Opus subagents realistic detectability
questions (with and without the skill) and grading the verdicts against
ground truth established beforehand. `evals/` contains the test set; the
fixture in `fixtures/rfi-insecure.c` comes from
[UlrikeHeidler/hud-rfi](https://github.com/UlrikeHeidler/hud-rfi).

Scope: C and C++ are the validated path, and the escalation ladder,
suppression table and report craft are language-independent. `references/csharp.md`
carries the C# capture route (`csc.exe`, `cov-emit-cs`, `cov-build`) for when
the question arrives in that language.
