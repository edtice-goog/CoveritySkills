# coverity

Part of [CoveritySkills](../README.md).

The umbrella skill, and the entry point for anything a specialist skill does
not already own. It carries the knowledge they all share — locating an
installation, reading an intermediate directory — and one capability of its
own that every other skill here depends on: **verifying that a capture
actually captured the code.**

Take this one even if you only want one of the others.

It also carries **the rules** — `RULES.md`, the standing list that applies to
any Coverity work regardless of the question being asked. It is the thing to
read first, and it is maintained: numbers are stable and citable, new rules
take the next free number, and each entry carries a `Source:` line saying
whether it was verified by execution or reasoned from mechanism.

The first two set the tone. **#1 Always use a template compiler
configuration** — a configure-time probe describes one invocation and is then
applied to all of them, and data captured under such a config is tainted
without announcing itself. **#2 Verify capture fidelity before believing any
result** — *no Coverity result means anything until capture is verified*,
because that assumption fails quietly and in the flattering direction. A
capture that emitted nothing reports 100%, raises no errors, and finishes
fast.

The remaining rules cover configuration (pin one install; configure every
compiler-shaped executable; regenerate rather than patch), capture (fresh
idir; make sure the build actually builds; never quote a bare percentage;
`--all`; what an empty vs. missing `scan-transparency/` means; preserve
timestamps if you relocate an idir, because Coverity reads them as state),
analysis
(find where the pipeline narrowed before blaming checkers; taint needs two
switches; never let capture doubt leak into a "not found"; triage a sample of
the defects before anyone trusts the run), committing to Coverity Connect
(take the URL from the user, never from an auth key; mint keys with
`cov-manage-im` and check them over REST; strip paths; one stream per
branch), and reporting (verdict first; say what you did not check;
distinguish measured from reasoned).

## Connecting to Coverity Connect

Every skill here that commits or queries needs an authentication key, so the
procedure lives in this skill rather than being rediscovered by each of them.
`tools/connect_auth.py` does the three things a session needs:

| | |
|---|---|
| `create` | mints a key with `cov-manage-im --mode auth-key --create` (the one step that needs the password) and stores it under `~/.coverity/` in the user's home directory |
| `check` | one REST request, redirects refused: `VALID`, `REJECTED` or `UNREACHABLE` |
| `revoke` | revokes a key by the id inside it, authenticated as that key, and confirms the server now refuses it |

`check` exists because the obvious test is wrong. `cov-manage-im --show`
reports a rejected key as a header row and exit 1, which is exactly what it
prints for an empty list, so a dead key looks like an empty instance. And a
REST probe that follows redirects lands on the sign-in page with a 200. All
of it was measured against Connect 2026.9.0; see
`references/connect-auth.md`.

## Capture fidelity: three methods, run independently

The check runs three sources of evidence that fail in different ways, then
adjudicates:

| | Method | Evidence base | Blind to |
|---|---|---|---|
| A | `coverity list` / `cov-manage-emit` | the emit database | anything the build never attempted |
| B | `idir/scan-transparency/` | the capture's own compiler-detection heuristic | anything configured that then failed to parse — and compiler wrappers, which it is not guaranteed to name |
| C | model inference | source tree + build system | what actually happened at runtime |

**Method C is produced and frozen first, before the intermediate directory is
opened.** It is the only contaminable one: read the emit inventory and you
will "expect" precisely what you just read, agreement becomes automatic, and
the check degrades into an expensive way of restating A. Agreement between
the three is the evidence; the *pattern of disagreement* is the diagnosis.

## What the skill knows that saves time

- **`coverity list` is the right denominator** — it walks the *project
  directory*, so it can see files that were never compiled, which the emit
  database structurally cannot. It works against a plain `cov-build` idir,
  not just `coverity capture`
- …but it hides `vendor`, `node_modules`, and dot-directories **unless they
  were captured**. The files most likely to be silently skipped are exactly
  the ones the default view hides. Always pass `--all`
- `cov-manage-emit list-capture-diagnostics` is the best programmatic source
  for per-translation-unit truth: `capture-percentage`,
  `had-recoverable-errors`, `had-abstract-syntax-trees`. `list-json` adds
  `astFidelityPercent` and `isFailure`. A TU with no AST is present, counted,
  and not analyzable. Neither subcommand is listed in `cov-manage-emit
  --help` on 2026.6.0, so confirm the field names against your own
  installation
- **A reused intermediate directory makes a broken capture look perfect** —
  yesterday's translation units answer today's questions. The exact
  counterpart of the build-fidelity trap where an empty capture yields
  byte-identical binaries
- **Emitted, analyzable, and analyzed are three different numbers**, printed
  in three different places, and routinely quoted as one another
- **Capture is not all-or-nothing.** The front end recovers from parse errors
  and keeps going, so a file can be captured, carry ASTs, report
  `capture-percentage: 100` — and still be missing individual functions.
  Measured: a three-function file lost its middle function while every
  file-level count read clean, and `cov-analyze` reported 4 functions where
  the sources define 5. What sees it: `had-recoverable-errors`, `Incomplete`
  in `coverity list`, the ` (recoverable errors)` suffix from
  `cov-manage-emit list`, and the capture log's `#1563` warning — the only one
  that *names* the lost function. So verdicts carry four counts, not three:
  expected / captured / analyzable / **fully parsed**
- An empty `unconfigured-compilers` is a real positive result; a **missing**
  `scan-transparency/` directory is not — it means the method did not run
- **`scan-transparency/` is written at capture time, not by analysis**, and
  nothing needs committing to Connect for it to be populated — measured both
  ways round on 2026.6.0. How much it contains depends on the capture path:
  `coverity capture` also writes `cli-ignored-files`, `cov-build` does not, so
  on a `cov-build` idir that file's absence is structural rather than clean
- `coverity capture` runs **buildless capture** after the build command, which
  does not cover C/C++ — so a healthy `SUCCEEDED` count can sit right next to
  a C source the build never compiled. Always pass the build command
  explicitly, and keep the idir outside the project directory
- **A non-empty `unconfigured-compilers` is not proof of a hole.** A capture
  that emitted all three of its sources at `capture-rate: 100` still listed a
  `<project-dir>\gcc` that does not exist on disk. Check whether each named
  path exists before reporting it — Method B alone would have failed a perfect
  capture, which is the sharpest argument for adjudicating all three
- On the CLI path, `output/cli-diagnostics.json` is the best provenance record
  in the idir: capture mode, capture rate, the effective build command, config
  hash, and every command with its environment (so check it before sharing an
  idir)
- A disagreement table that separates the two failures that look identical
  from the headline percentage: a compiler that was never configured, versus
  a build that never compiled the files at all (incremental builds, compiler
  caches, wrong target — the more common of the two by far)

Verdicts are a triple — `expected 128 / captured 126 / analyzable 126` — plus
a grade, never a bare percentage.

## Layout

```
coverity/
├── SKILL.md                      # orientation, the rules in brief, routing
├── RULES.md                      # the standing rules, with why and evidence
├── CALIBRATION.md                # what is measured vs. reasoned, and the runs behind it
├── references/
│   ├── capture-fidelity.md       # the three-method protocol + disagreement table
│   ├── connect-auth.md           # create, store, check and revoke Connect auth keys
│   ├── idir-anatomy.md           # what each file in an idir is evidence of
│   └── worked-example-vacuous-capture.md  # rule 9 calibration: no-op vs partial build
└── tools/
    ├── capture_fidelity.py       # pure stdlib; one subcommand per step
    └── connect_auth.py           # pure stdlib; create / check / revoke
```

`CALIBRATION.md` is deliberate: it records the run behind each claim and the
environment it ran in, so that inference never reads as measurement. Every
row of the capture-fidelity diagnosis table has now been produced by a real
capture and adjudicated by the tool, and four of those runs changed the skill
rather than confirming it. The vacuous-capture row is the clearest example.
`cov-build` warns loudly when it captures *nothing*, so the dangerous case
turned out to be the build that captures *some*, which reports 100% and
"completed successfully". What is still reasoned rather than measured is
listed there plainly.
