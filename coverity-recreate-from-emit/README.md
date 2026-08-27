# coverity-recreate-from-emit

Part of [CoveritySkills](../README.md).

Works from an intermediate directory you did not capture, instead of capturing
a fresh one. The idir turns out to be a far better record of its build than it
looks: it carries the original compiler command lines, the fully resolved
compiler model, and the complete include closure of every translation unit.

Two situations use that:

- **A — the build cannot be run.** Toolchain gone, CI job retired, old commit
  no longer builds, and the newer analyzer refuses the old emit.
- **B — the build can be run but is too slow.** Copy a reference idir from CI
  or another checkout and bring it up to date with a working tree by
  re-emitting only what changed. This one **deliberately violates rule 8**, and
  most of the procedure is knowing when it does not apply.

## A. Recreate

Gets an old intermediate directory analyzable by a **newer** analyzer when the
original build can no longer be run — the toolchain is gone, the dependencies
have vanished, the CI job was retired, or the old commit no longer builds.
Where `coverity-build-fidelity` assumes you can run the build, this skill
assumes you cannot, and treats the idir as the surviving record of it.

The blocking fact is that a newer analyzer simply refuses an older emit —
*"Expected version number is 355, but this directory has version 343"*, exit
code 2. Unusually for this problem domain, that failure is **loud**: it
refuses, says why, and produces no partial result.

## The central technique

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

## What the skill knows that saves time

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
  `--c11 -> --c17`: one token in sixty, and semantic
- **…and a difference is not automatically drift.** Coverity models each
  compiler's flag handling by hand, and that modelling can be wrong. Asked
  directly, gcc 13.3.0 reports `__STDC_VERSION__ 201710L` for the recorded
  flags — C17 is its real default, so the *old* `--c11` was the defect and the
  new version is correcting it. So a semantic delta is adjudicated **against
  the compiler**, not between the two Coverity versions: a correction is
  accepted, never pinned, because pinning it reproduces a known-wrong parse and
  calls it a control. Errors of this kind hide on every build that passes
  `-std=` explicitly, so probe the argument sets with the *fewest* explicit
  flags
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

## B. Reuse for speed

The payoff scales with build-plus-analyze time — noise on a small project, the
difference between a feedback loop and a nightly job on one that takes hours.
It is a developer-iteration tool, not release evidence.

**Two gates, both pass/fail, both before any work:**

- **The build system must track header dependencies.** The procedure hands
  "what does this change affect?" to the build system, and one that cannot
  answer returns *nothing* while looking successful. The probe is measured in
  both directions: CMake+make recompiled exactly the right **3 of 4** TUs after
  a header touch; proftpd's hand-written recursive make recompiled **0 of 71**.
  Computing the affected set yourself is a fool's errand — in C++ headers carry
  code — so the include closure is used *once*, to grade the build system, and
  never to select what to re-emit.
- **The reference idir must come with a git commit or tag**, or the delta is
  guesswork. Insist on it and then verify the claim — `primaryFileHash` can't,
  but `primaryFileSizeInBytes` matches disk exactly, so `git show <tag>:<path>`
  settles it.

**Then one routing question:** is every changed file the primary source of
exactly one TU? If yes, delete those TUs and re-emit them directly — no build
recording needed. If anything else changed (header, new file, deletion,
rename), touch the changed files, capture an incremental build into a separate
idir, and transplant.

**And always delete the stale TU before adding the fresh one.** This is the
failure the whole procedure exists to prevent, and it is measured: with a
reference containing an array overrun that the working copy *fixes*,
transplanting without deleting still reported the defect — 1 where the correct
answer was 0, pointing at a path in a tree the developer isn't editing. Two
TUs at different absolute paths are different primary source files, so
`--one-tu-per-psf` never deduplicates them; an earlier run analyzed **7 TUs in
a 4-TU project** the same way.

Verified against full-recapture oracles on both paths: the fast path reproduced
a clean capture exactly (105 defect sites, 155 records, zero differences either
way, planted canary present), and the transplant path matched its oracle file
for file and defect for defect.

## Layout

```
coverity-recreate-from-emit/
├── SKILL.md                          # procedure (identify → verify old capture →
│                                     #   extract → control → probe → classify →
│                                     #   replay → reconcile → report)
├── CALIBRATION.md                    # measured vs reasoned, and the queue
├── references/
│   ├── transformation-probe.md       # the method, the normalization set, why the control
│   ├── invocation-anatomy.md         # what list-capture-invocations contains
│   ├── idir-reuse.md                 # reuse: three gates, routing, stale-TU rule,
│   │                                 #   capture cost, and the two cohort yardsticks
│   ├── target-state.md               # bringing an idir current WITHOUT known
│   │                                 #   provenance: extract-files, what the
│   │                                 #   recorded hash is and is not
│   ├── corporate-tls.md              # TLS-inspecting proxies: four trust stores,
│   │                                 #   and the two that fail silently
│   └── worked-example-proftpd.md     # the calibration session, with the numbers
├── tools/
│   ├── emit_probe.py                 # identify / extract / probe / delta /
│   │                                 #   replay / reconcile
│   ├── staleness.py                  # pre-analysis gate: OK / STALE / ORPHAN / ...
│   ├── model_provenance.py           # post-analysis: where models came from
│   │                                 #   (PROVISIONAL - see its docstring)
│   ├── build_targets.py              # detect and strip build targets in one idir
│   ├── check_prerequisites.py        # the coverity.yaml gate
│   └── estimate_from_connect.py      # cost estimate from snapshot history
└── benchmarks/                       # the harness that produced CALIBRATION's
                                      #   numbers, and the traps it encodes
```

All tools are pure standard library.

Status (A): **validated end to end** — probe, control, replay, reconciliation
and analysis, against a real archived idir written fifteen months earlier by a
version that the current analyzer refuses. All 90 translation units replayed
(90/90 rc=0), reconciled `CONSISTENT` (0 missing, 0 size mismatches, all ASTs
at 100% fidelity), and the result analyzed cleanly with the same file,
function and class counts as the original run.

Dogfooding the procedure changed it in four places: the tool had no replay
step; the version-owned includes were being masked when they should be path
-transformed; there was no licence pre-flight (two full replays finished
before a missing and an expired licence surfaced, both at the last step); and
the `--c11 → --c17` delta turned out both to be specific to one version pair
(2024.12.1 → 2025.9.0 is identity) and to be a **bug fix in Coverity's model of
gcc** rather than drift — which reversed the skill's advice from "pin it back"
to "accept it, and treat it like a new checker". Differences cannot be
predicted from version numbers, nor interpreted without asking the compiler.

Still unmeasured for A: the degraded path for when the compiler is gone,
anything other than C, and every *failure* mode — each reconciliation so far
has been perfect, so the shortfall path has never fired.

Status (B): both paths validated against oracles, both gate outcomes measured,
and **timing confirmed on FFmpeg** (2053 TUs, 16 cores): a full cold run costs
373s capture + 794s analyze = **19.5 min**; a current idir plus three edited
files costs 8s + 78s = **1.4 min**, a **13.6× speedup**. Even the worst case —
a release tag to master jump that forces 99% of TUs to re-emit — still returns
**1.55×**, because the saving lives in the function-granular analysis phase
rather than the file-granular capture.

Correctness at that scale was checked rather than assumed: re-analyzing the
updated idir with `--force` (full analysis of identical emit) took 734s against
the incremental 78s and produced **the same 935 defect sites and 1212 records,
with zero differences either way** — 9.4× faster for an identical answer. Still
untested: a genuinely foreign idir (`reset-host-name` was a no-op every time),
the git-tag verification, iteration across several rounds including a reverted
file, and deletions or renames. `CALIBRATION.md` keeps both queues.
