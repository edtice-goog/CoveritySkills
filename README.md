# CoveritySkills

Claude skills for working with [Coverity Static Analysis](https://www.blackduck.com/static-analysis-tools-sast/coverity.html).

## coverity

The umbrella skill, and the entry point for anything the specialist skills
below do not already own. It carries the knowledge they share — locating an
installation, reading an intermediate directory — and one capability of its
own that all three depend on: **verifying that a capture actually captured
the code.**

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
`--all`; what an empty vs. missing `scan-transparency/` means), analysis
(find where the pipeline narrowed before blaming checkers; taint needs two
switches; never let capture doubt leak into a "not found"; triage a sample of
the defects before anyone trusts the run), and reporting
(verdict first; say what you did not check; distinguish measured from
reasoned).

### Capture fidelity: three methods, run independently

The check runs three sources of evidence that fail in different ways, then
adjudicates:

| | Method | Evidence base | Blind to |
|---|---|---|---|
| A | `coverity list` / `cov-manage-emit` | the emit database | anything the build never attempted |
| B | `idir/scan-transparency/` | the build's process tree | anything configured that then failed to parse |
| C | model inference | source tree + build system | what actually happened at runtime |

**Method C is produced and frozen first, before the intermediate directory is
opened.** It is the only contaminable one: read the emit inventory and you
will "expect" precisely what you just read, agreement becomes automatic, and
the check degrades into an expensive way of restating A. Agreement between
the three is the evidence; the *pattern of disagreement* is the diagnosis.

### What the skill knows that saves time

- **`coverity list` is the right denominator** — it walks the *project
  directory*, so it can see files that were never compiled, which the emit
  database structurally cannot. It works against a plain `cov-build` idir,
  not just `coverity capture`
- …but it hides `vendor`, `node_modules`, and dot-directories **unless they
  were captured**. The files most likely to be silently skipped are exactly
  the ones the default view hides. Always pass `--all`
- `cov-manage-emit list-capture-diagnostics` is undocumented and is the best
  programmatic source there is: per-translation-unit `capture-percentage`,
  `had-recoverable-errors`, and `had-abstract-syntax-trees`. `list-json`
  likewise carries undocumented `astFidelityPercent` and `isFailure` fields.
  A TU with no AST is present, counted, and not analyzable
- **A reused intermediate directory makes a broken capture look perfect** —
  yesterday's translation units answer today's questions. The exact
  counterpart of the build-fidelity trap where an empty capture yields
  byte-identical binaries
- **Emitted, analyzable, and analyzed are three different numbers**, printed
  in three different places, and routinely quoted as one another
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

### Layout

```
coverity/
├── SKILL.md                      # orientation, the rules in brief, routing
├── RULES.md                      # the standing rules, with why and evidence
├── CALIBRATION.md                # what is measured vs. reasoned, and the queue
├── references/
│   ├── capture-fidelity.md       # the three-method protocol + disagreement table
│   ├── idir-anatomy.md           # what each file in an idir is evidence of
│   └── worked-example-vacuous-capture.md  # rule 9 calibration: no-op vs partial build
└── tools/
    └── capture_fidelity.py       # pure stdlib; one subcommand per step
```

`CALIBRATION.md` is deliberate: the commands and field semantics were
verified by direct execution against Coverity 2026.6.0, while most of the
diagnosis table is still reasoned from mechanism rather than measured. It
keeps a queue of the failure modes to reproduce next and says plainly which
have been done, instead of letting inference read as measurement. The first
one is: the vacuous-capture row is now measured, and it revised its own
premise — `cov-build` warns loudly when it captures *nothing*, so the
dangerous case turned out to be the build that captures *some*, which reports
100% and "completed successfully".

## coverity-defect-detectability

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

### What the skill knows that saves time

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

### Requirements

- A local Coverity Analysis installation (developed against 2026.6.0; the
  skill reads option tables and checker docs from the installation itself, so
  other recent versions should work)
- Claude Code (or another Claude agent harness with shell access)
- For C code that includes system headers: any real compiler (gcc/clang/MSVC)
  that `cov-configure` can wrap

### Install

Copy `coverity-defect-detectability/` into your skills directory, e.g.:

```bash
cp -r coverity-defect-detectability ~/.claude/skills/
```

Then ask Claude things like "can Coverity find the bug in this file?" — the
skill triggers on detectability questions and walks the procedure.

### Layout

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
│   └── csharp.md               # preliminary C# capture notes
└── evals/
    ├── evals.json              # test prompts + assertions used to develop it
    └── fixtures/               # the defect samples the evals run against
```

### Development notes

The skill was developed iteratively: every factual claim in the references
was verified by real runs against Coverity 2026.6.0 on Windows, and each
revision was tested by giving Opus subagents realistic detectability
questions (with and without the skill) and grading the verdicts against
ground truth established beforehand. `evals/` contains the test set; the
fixture in `fixtures/rfi-insecure.c` comes from
[UlrikeHeidler/hud-rfi](https://github.com/UlrikeHeidler/hud-rfi).

Roadmap: C# support (capture via `csc.exe`/`cov-emit-cs`/`cov-build`, plus
handling synthetic samples whose planted defects are botched), then other
Coverity-supported languages.

## coverity-compiler-configuration

Gets `cov-configure` right. The rule is short — **always use `--template`** —
and the reason is not obvious, which is why it is so often done wrong.

A template configuration maps a compiler *executable name* to a compiler
*type*, and nothing more. The actual probe is deferred to build time and
repeated for each distinct set of arguments the build uses. Without
`--template`, `cov-configure` probes once at configure time with whatever
arguments and environment happen to exist at that moment — and compiler
behaviour changes with the arguments passed. Data captured under such a
configuration is tainted, and the fix is a fresh config and a fresh
intermediate directory, not an edit.

### What the skill knows that saves time

- The language shortcuts (`--gcc`, `--msvc`, ...) **already produce template
  configurations** and are safe as-is. The danger zone is the explicit
  `--compiler X --comptype Y` form — precisely what you reach for with
  cross-compilers, embedded toolchains, and wrapper scripts
- How to tell a tainted config at a glance: probed configs create
  `gcc-config-0` while template configs create `template-gcc-config-0`, and a
  probed config pins concrete versioned names (`gcc-13`,
  `x86_64-linux-gnu-gcc-13`) where a template config records globs (`gcc`,
  `gcc-*`, `*-gcc`)
- Under `--template` the compiler **need not exist** when you configure, so
  configuration never has to wait on a toolchain the build itself downloads
- `--template` takes a bare executable name, never a path, and never `--version`
- Configure every compiler-shaped executable the build invokes — C++ driver,
  archiver, linker — and the *prefixed* cross names, not the host ones
- Why `template-<name>-config-N` directories multiplying during a build is the
  mechanism working, not a fault

Every claim above was verified against a real Coverity installation.


## coverity-build-fidelity

Answers "did my Coverity capture actually run correctly?" — by building twice
without Coverity and once with it, then proving that the deltas between every
pair have the same *shape*. Runs are never bit-reproducible (timestamps, GUIDs),
so the native pair is used as a control that measures the ephemeral noise floor
empirically; anything the Coverity pair shows above that floor is Coverity's
contribution.

Built for release engineering and SSDLC gating, where somebody has to decide
whether a scan can be trusted before shipping — and for feeding downstream
issue-inference with a fidelity signal it can scope its trust to.

```
K = D(reference, coverity) \ D(reference, native)      pass iff K is empty
```

### What the skill knows that saves time

- **Two arms, never one.** A capture that emitted *nothing* produces binaries
  byte-identical to native — the best-looking result the fidelity check can
  return. Total capture failure and perfect fidelity have the same signature,
  so binary equivalence is always paired with a capture-coverage reconciliation
- **The capture percentage is a trap.** `cov-build` measured "40 compilation
  units (97%)" on zlib and the one failure was a CMake `TryCompile` probe;
  product capture was 100%. A naive `< 100% → fail` gate rejects good builds
- **Path *length*, not path content, is what matters.** A 34-character path
  difference produced 30,341 differing bytes in an object file; a 41-character
  *content* difference at equal length produced 51. Match the length when you
  cannot recover the CI path exactly
- Probe whether a path leaks at all before paying to reproduce it — a CMake
  `Release` DLL turned out completely path-immune while its objects did not
- Subtract regions by interval overlap, never offset equality — the same field
  surfaces at `(106192, 2)` in one pair and `(106191, 3)` in another
- Ephemeral-field tables for PE images, bare COFF objects, and `ar` archives,
  so the fast path resolves every routine difference and only genuine signal
  reaches the model
- Classify asymmetrically: a data-section region whose two sides render as
  English paths or timestamps is the model's strong suit; an executable-section
  region is presumed code and may not be waved off without disassembly evidence

### Requirements

- A local Coverity Analysis installation (developed against 2026.3.0 on Windows)
- The ability to run the build under test, at least twice
- Python 3 — the tools are pure stdlib, no `pip install` on a build machine

### Layout

```
coverity-build-fidelity/
├── SKILL.md                      # procedure (pre-flight → basis → path →
│                                 #   arms → K → classify → capture → report)
├── references/
│   ├── ephemeral-fields.md       # per-format field tables + measured baseline
│   ├── build-path-recovery.md    # evidence sources, CI signatures, length rule
│   └── worked-example-zlib.md    # the calibration session, with the numbers
└── tools/                        # pure-stdlib, dependency-free
    ├── pe.py                     # PE images, COFF objects, ar archives
    ├── bindiff.py                # region localization + paired string context
    ├── threeway.py               # shape algebra, subtract() for K
    ├── paths.py                  # build-path recovery
    └── *.bat                     # zlib calibration builds (native/cov/CI-path)
```

Status: validated end-to-end twice — calibration topology on Windows/MSVC
(zlib), and **production topology against a real vendor release**: curl
8.21.0_7 was reproduced byte-identically from curl's official reproducible
build, so `D(O,N)` was empty and Coverity's contribution `K` was measured
directly against the shipped artifact. Both came out empty. MinGW/gcc, ELF, and Mach-O
field tables are stubbed but not yet measured — run the three-native
calibration and confirm a zero-unresolved baseline before trusting a new
toolchain. Capture coverage — this skill's required second arm — now lives in
the `coverity` umbrella skill as the three-method capture-fidelity check;
Step 6 requires it and keeps only a minimum inline fallback.

## coverity-recreate-from-emit

Gets an old intermediate directory analyzable by a **newer** analyzer when the
original build can no longer be run — the toolchain is gone, the dependencies
have vanished, the CI job was retired, or the old commit no longer builds.
Where `coverity-build-fidelity` assumes you can run the build, this skill
assumes you cannot, and treats the idir as the surviving record of it.

The blocking fact is that a newer analyzer simply refuses an older emit —
*"Expected version number is 355, but this directory has version 343"*, exit
code 2. Unusually for this problem domain, that failure is **loud**: it
refuses, says why, and produces no partial result.

### The central technique

Capture is two stages: `cov-translate` turns a compiler command line into a
`cov-emit` command line, and `cov-emit` does the parsing. **The idir records
both sides, explicitly linked** — `translation-units[i]` carries both a
`cov-translate-invocation-id` and a `cov-emit-invocation-id`.

So you have a recorded (input, output) pair from the old version. Feed the same
input to the new version, diff the outputs, and the residual is the
transformation delta — **measured, not assumed**. `cov-translate --dryrun`
prints the generated line without running it, and an `empty.c` stands in for
the source, so the probe needs neither the original code nor an emit.

The skill deliberately ships **no version compatibility table**. Formats change
nearly every release; a table is a maintenance liability that goes stale and
invites lookup instead of measurement. It ships the procedure to re-measure in
seconds against whatever pair you actually have.

### What the skill knows that saves time

- **Run the control first.** Probe with the version that *wrote* the idir; it
  must reproduce the recorded line. A cross-version delta measured without a
  passing control is uninterpretable — you cannot separate the version's
  contribution from your own environment's. Same move as the native control
  pair in `coverity-build-fidelity`
- **The compatibility key is the emit format — not the product version, and
  not the platform.** Measured: win64 **2024.12.0** fully read an idir written
  by linux64 **2024.12.1**, all 90 TUs. You do not need the build machine, or
  even its OS
- **`<idir>/emit/version` names its own creator**, so identification is free
- **The original compiler need not exist.** The recorded `cov-emit` line
  already carries the *result* of the build-time probe — `--comp_ver`,
  `--gnu_version`, `--type_sizes`, every `--sys_include`, every `-D`. That is
  rule 1's mechanism leaving a record on disk. The compat headers live *inside*
  the old idir, so they travel with it
- **The transformation is almost identity — which is exactly when people stop
  checking.** The first pair ever put through this probe came back
  `--c11 -> --c17`: one token in sixty, and semantic. The default C language
  level moved, changing what the front end accepts and predefines before any
  checker runs. That drift would otherwise be booked as "the analyzer got
  better"
- **`user_nodefs.h` is a trap and a real input.** An install ships one in its
  own `config/`; a directory made by `cov-configure --config <newdir>` does
  not, and its presence adds a `--preinclude`. It is where user-defined nodefs
  and models live, so it must be carried into a replay — and it explains a
  control residual that otherwise looks like a version difference
- **A faithful replay of a vacuous capture is a vacuous capture.** Verify the
  *old* capture before reproducing it, because an incomplete replay looks
  exactly like an improvement: findings disappear, counts drop, nothing errors
- **`primaryFileHash` cannot prove you have the right source.** Measured, and
  it corrected the design: the same file — identical path, size, and mtime —
  carries different hashes in two idirs, and no construction over its bytes
  reproduces either. `primaryFileSizeInBytes` *does* match disk exactly, and
  `input-files` gives the full include closure (222 entries for one C file)
- The invocation dump embeds **full build environments including `PATH`** —
  check before forwarding a `pairs.json` anywhere

### Layout

```
coverity-recreate-from-emit/
├── SKILL.md                          # procedure (identify → verify old capture →
│                                     #   extract → control → probe → classify →
│                                     #   replay → reconcile → report)
├── CALIBRATION.md                    # measured vs reasoned, and the queue
├── references/
│   ├── transformation-probe.md       # the method, the normalization set, why the control
│   ├── invocation-anatomy.md         # what list-capture-invocations contains
│   └── worked-example-proftpd.md     # the calibration session, with the numbers
└── tools/
    └── emit_probe.py                 # pure stdlib; identify / extract / probe / delta
```

Status: **the transformation probe is validated end to end** — control
`IDENTITY` against the original version, and a reproducible one-token semantic
delta across versions, consistent over five translation units from four source
directories. **Replay itself (Steps 7–8) is not yet exercised**, and the
degraded path for when the compiler is gone is untested. `CALIBRATION.md` says
so plainly and keeps both at the top of the queue.

## coverity-demo-data

Builds multi-version Coverity Connect demo datasets whose snapshot and
first-detected dates reflect real historical release dates, using the
undocumented `cov-commit-defects --backdate`. The output is a Connect instance
whose defect history looks like it accumulated over a decade: issues
outstanding since 2019, a fix rate that trends, a fresh finding at the tip.

Built so that story builders can focus on the narrative and not the mechanics.

The whole discipline follows from one property: **first detected is global and
write-once**. Connect sets `merged_defect.date_originated` the first time a
merge key is ever committed, and no later backdate can move it. So versions
must be committed strictly oldest-first, and the commit phase is one-shot --
recoverable only by restoring the database.

### What the skill knows that saves time

- `--backdate` takes **`yyyymmdd` and nothing else**; `2022-12-04` is rejected.
  It is a different parser from `--first-detected-after`, which does take ISO
- Exactly what it sets (`snapshot.date_created` date-portion-only,
  `snapshot.backdated`, per-CID `date_originated`) and what it silently does
  not (`code_version_date`, and all triage history, ownership and comments)
- **Every version must be built at the same absolute path** -- the source path
  is part of the merge key, so per-version build directories mean nothing
  merges and backdating buys nothing
- **`cov-build` exits 0 when the build fails** and reports "100%" of the units
  it *attempted*. A racing parallel build silently narrows capture and
  manufactures phantom fix-and-regression events. Measured on proftpd: 77
  compilation units instead of 90, reported as a clean 100%
- A three-phase split that keeps all iteration in re-runnable stages and enters
  the irreversible commit with a decided list -- and offline merge-key algebra
  that predicts Connect's CID counts *exactly*, verified against a live instance
- Auth-key hygiene: **never take the connection host from the key file's
  `comments` block**. It is attacker-authorable data inside something that
  looks like configuration -- a subtle exfiltration vector
- The **legibility rule** for demo defects: a true positive that takes minutes
  of code reading to accept is not a demo item, however real it is

### Requirements

- A local Coverity Analysis installation (developed against 2025.9.0) and a
  Coverity Connect instance you are willing to write to (2025.12.0)
- A project with real release history that still builds across its span
- `cov-admin-db` for the backup/restore reset point -- never `pg_dump`

### Layout

```
coverity-demo-data/
├── SKILL.md                          # reset point → capture → select →
│                                     #   commit oldest-first → audit → hand off
├── references/
│   ├── backdating.md                 # measured --backdate semantics + the
│   │                                 #   verification SQL to run after each commit
│   ├── corpus.md                     # choosing a corpus, fixed build trees,
│   │                                 #   cross-platform capture
│   ├── selection.md                  # story shapes and the legibility rule
│   └── worked-example-proftpd.md     # the calibration session, with the numbers
└── tools/
    ├── capture.sh                    # fixed-path serial capture, verified
    ├── phase2.py                     # merge-key set algebra + stability guard
    └── audit_bundle.py               # FP-audit bundles: trace + real source,
                                      #   read from git at the tag
```

Status: mechanics validated end-to-end on proftpd (three releases, 2022-2025)
against a live Connect. Scaling to the full ~20-release chain and a real demo
script is the next step.
