---
name: coverity-recreate-from-emit
description: >
  Get an old Coverity intermediate directory analyzable by a newer analyzer
  when the original build can no longer be run -- the toolchain is gone, the
  dependencies have vanished, the CI job was retired, or the old commit no
  longer builds. Use this skill when a newer Coverity version refuses an older
  intermediate directory ("Expected version number is N, but this directory
  has version M"), when someone needs to re-analyze an archived idir, when
  asked to reproduce or replay an old capture without its build environment,
  or when downstream issue-transition inference needs an old snapshot analyzed
  by a new analyzer and rebuilding is not an option. The central technique is
  a probe that *measures* how a given Coverity version turns a compiler
  command line into a cov-emit command line, so replay rests on evidence
  rather than on the assumption that the translation is unchanged.

  ALSO covers the second use of a foreign intermediate directory: reusing one
  for speed. Use it when someone wants to avoid re-capturing a slow build --
  copying an idir from CI, a release job, or another checkout and bringing it
  up to date with a working tree by re-emitting only the changed translation
  units; when asked how to make Coverity analysis fast enough for active
  development or an inner loop; or when an idir is being reused and someone
  needs to know whether that is safe. That path deliberately violates the
  fresh-intermediate-directory rule and carries two applicability gates (the
  build system must track header dependencies, and the idir must come with a
  known git commit or tag), so it also answers "can I reuse this idir?" with
  a measured no.

  Requires local Coverity installations -- for the recreate path, both the
  version that wrote the idir and the version you want to analyze with.
---

# Recreate from emit

Working from an intermediate directory you did not capture, instead of
capturing a fresh one. **The idir is a far better record of its build than it
first appears** -- it carries the original compiler command lines, the
resolved compiler model, and the full include closure of every translation
unit.

Two situations, sharing that machinery:

| | Situation | Procedure |
|---|---|---|
| **A** | The build **cannot be run** -- toolchain gone, CI retired, old commit no longer builds -- and a newer analyzer refuses the old emit | *Recreate*, below |
| **B** | The build **can** be run but is **too slow** to repeat; you want a reference idir brought up to date with a working tree | *Reuse*, see `references/idir-reuse.md` |

A is about recovering analyzability across a version gap. B is about speed
during active development, and **deliberately violates rule 8** -- read its
two applicability gates before starting, because knowing when it does not
apply is most of that procedure.

Both deliver the same thing: an idir a chosen analyzer will accept, evidence
that it corresponds to the code you think it does, and an honest grade when it
does not.

---

# A. Recreate: the build cannot be run

`coverity-build-fidelity` assumes you can run the build. Often you cannot. When
the build is unavailable, the intermediate directory is the surviving record
of it.

## The constraint

A newer analyzer cannot read an older emit. There is no compatibility window:
the emit format must match **exactly**.

```
Expected version number is 355, but this directory has version 343.
```

Exit code 2. This is one of the few Coverity failure modes that is *loud* -- it
refuses, it says why, and it produces no partial result. Unlike most traps in
`coverity/RULES.md`, this one cannot be mistaken for success. That is the good
news; everything after it is the work.

Two things soften the constraint, and both are worth checking before any
replay:

- **The idir names its own creator.** `<idir>/emit/version` line 1 is a comment
  naming the product version that wrote it; line 2 is the format number. You
  never have to guess.
- **The compatibility key is the emit format -- not the product version, and
  not the platform.** A different product version whose format matches will
  read it, and so will a different operating system. Verify by running, not by
  assuming (Step 1).

## The asset: the idir records the transformation

Capture runs a two-stage pipeline. `cov-translate` intercepts a compiler
command line and turns it into a `cov-emit` command line; `cov-emit` does the
parsing. **The intermediate directory records both sides, explicitly linked.**

```
translation-units[i].cov-translate-invocation-id  ->  the original compiler argv
translation-units[i].cov-emit-invocation-id       ->  the cov-emit argv it produced
```

The `cov-emit` side already contains the *result* of the build-time compiler
probe -- `--comp_ver`, `--gnu_version`, `--type_sizes`, `--type_alignments`,
every `--sys_include`, every `-D`. This is rule 1's mechanism leaving a record.

**Consequence: the original compiler does not have to exist to replay.** Its
probed behaviour was distilled into flags at capture time. The
`--pre_preinclude` compat headers live *inside the old idir*, so they survive
with it.

What you still need is the original **sources** and the **system headers** the
`--sys_include` paths refer to.

## The core idea

You have a recorded (input, output) pair from the old version. Feed the same
input to the new version and see what output it produces. The difference is the
transformation delta -- **measured, not assumed.**

Do not skip this because the transformation "is obviously identity". Measured
across two version pairs from the *same* starting version:

```
2024.12.1 -> 2025.9.0     IDENTITY      (61 tokens, no difference at all)
2024.12.1 -> 2025.12.2    --c11 -> --c17
```

One token in sixty, and only on one of the two pairs -- yet it changes what the
front end accepts and predefines, before any checker runs.

Asking the compiler settles what it means: gcc 13.3.0, given these flags,
reports `__STDC_VERSION__ 201710L`. **C17 is gcc's real default here, so
2024.12.1's `--c11` was wrong.** Coverity models each compiler's behaviour by
hand, that modelling is human work, and this was a defect in it. The newer
version is not drifting; it is correcting.

Two lessons, and the second is the one people miss:

- **Differences are version-pair-specific and cannot be predicted from version
  numbers.** Probe the pair you actually have; it costs seconds.
- **A difference is not automatically drift to be neutralized.** It may be the
  new version getting the compiler right. A model fix changes findings for the
  same reason a new checker does, and belongs in the same bucket. Step 6 has
  the test that tells a correction from a change -- and why pinning a
  correction back is the wrong move.

`references/transformation-probe.md` has the method in full.
`references/invocation-anatomy.md` maps what the invocation record contains.

## Procedure

### Step 0. Rules, and pin two installations

Read `coverity/RULES.md`. Pin **two** installs and record both: the one whose
format matches the idir (the *old* side) and the one you want to analyze with
(the *new* side). Rule 3 says pin one; this skill is the exception that
requires exactly two, which is why they must be named explicitly in the report.

**Check the new side's licence now, before anything else.** Replay does not
need one -- `cov-translate` and `cov-emit` will happily emit all 90 TUs under
an install whose licence is missing or expired. Only `cov-analyze` checks, so
without this pre-flight you discover the problem *after* the replay, at the
last step:

```bash
ls <new-install>/bin/license.dat <new-install>/bin/license*.json 2>/dev/null
grep -oE '20[0-9]{2}-[0-9]{2}-[0-9]{2}' <new-install>/bin/license.dat | sort -u | tail -1
```

Measured failure modes: `[FATAL] No license files ... found` (rc 47) when
absent, `[FATAL] License authorization failure: License has expired.` (rc 2)
when stale. Installs frequently share one licence file, so check the *file*,
not the install.

### Step 1. Identify the idir, and find an install that can read it

```bash
cat <idir>/emit/version
```

Line 1 names the creating version; line 2 is the format number. Then confirm by
running -- a version that *claims* to match still has to prove it:

```bash
python3 tools/emit_probe.py identify --dir <idir> --installs "/path/to/coverity/*"
```

This runs `cov-manage-emit list` under each candidate and reports which exit 0.
Do not build a version-to-format table; formats change nearly every release and
a table goes stale within months. Probe the installs you actually have.

If no install matches, stop and say so. Obtaining the matching version is the
user's decision, not something to work around.

### Step 2. Verify the *old* capture before reproducing it

Run the three-method capture-fidelity check from `coverity` against the old
idir, using the old-side install. **A faithful replay of a vacuous capture is a
vacuous capture.** If the original build compiled 1 of 5 sources, reproducing
it perfectly reproduces the hole -- and the hole reads downstream as "defects
fixed".

Record the original TU inventory now; Step 7 reconciles against it.

### Step 3. Extract the invocation pairs

```bash
python3 tools/emit_probe.py extract --bin <old-bin> --dir <idir> --out pairs.json
```

This must run under the **old-side** install -- no other version can open the
idir. Note that a win64 tool reading a Linux emit renders paths with
backslashes; the tool normalizes this, but naive path matching breaks on it.

**Handling caution.** The invocation record embeds full process environments,
including `PATH` and anything else passed at build time. Treat `pairs.json`
like the idir itself: check before forwarding it anywhere. See
`coverity/references/idir-anatomy.md`.

### Step 4. Run the control -- the step that makes this an experiment

Probe with the **old** install, the one that wrote the idir. It must reproduce
the recorded `cov-emit` line, modulo the normalization set.

```bash
python3 tools/emit_probe.py probe --pairs pairs.json --bin <old-bin> --work <scratch> --out ctrl.json
python3 tools/emit_probe.py delta --pairs pairs.json --generated ctrl.json
```

Expected result: `IDENTITY`.

**If the control does not pass, stop.** A cross-version delta measured without
a passing control is uninterpretable -- you cannot separate the version's
contribution from your own environment's. Common causes, all fixable:

- the config directory lacks the version-owned includes. `user_nodefs.h`
  ships inside an install's own `config/` but is **not** created by
  `cov-configure --config <newdir>`, and its absence silently drops a
  `--preinclude` from the generated line. Seed it from the install being
  probed -- *that* install, not the old one: the pre-includes and nodefs are
  always pulled from the same product version as `cov-emit`, which is why the
  normalization path-transforms them rather than dropping them. `emit_probe.py
  probe` seeds it automatically and says so.
- the compiler on this machine differs from the one captured (compare
  `--comp_ver` in the recorded line).
- the compiler is gone entirely -- see *Degraded path* below.

### Step 5. Probe the new version

Same recorded input argv, new install:

```bash
python3 tools/emit_probe.py probe --pairs pairs.json --bin <new-bin> --work <scratch> --out new.json
python3 tools/emit_probe.py delta --pairs pairs.json --generated new.json
```

The residual is the transformation delta. Probe **more than one argument set** --
the template mechanism configures per distinct argument set, so C and C++, or
differing `-std` / `-m32` arms, can drift differently. `--index all` samples
across the recorded pairs.

### Step 6. Classify the delta before acting on it

Per differing token, decide and record:

| Class | Meaning | Action |
|---|---|---|
| environment | path, temp dir, config hash, source name | normalized away already |
| cosmetic | reordering, equivalent spelling | note, proceed |
| semantic | changes what the front end accepts or predefines | classify further, below |

For a semantic difference, the question is **not** "which version do I want?"
It is **which version models the compiler correctly?** Coverity has to
reproduce, by hand, what each compiler does with each flag. That modelling is
human work and it can simply be wrong. So a semantic delta is one of two
things:

- **CORRECTION** -- the new version models the compiler more faithfully than
  the old one did. The old behaviour was a defect.
- **CHANGE** -- both versions are defensible; a default genuinely moved.

**The tie-breaker is the compiler, not either Coverity version.** Ask it
directly:

```bash
echo | gcc -dM -E -x c - | grep __STDC_VERSION__     # with the build's own flags
```

Worked case. On the recorded proftpd argument set, which passes no `-std=`,
the probe reported `--c11` -> `--c17`. Asking gcc 13.3.0 what it actually does
with those flags: `__STDC_VERSION__ 201710L` -- C17. So **2024.12.1's `--c11`
was wrong** and 2025.12.2's `--c17` is a bug fix in Coverity's model of gcc.

That decides the response:

- **A CORRECTION is accepted, never pinned.** Pinning `--c11` back would
  reproduce a known-wrong parse of the code -- preserving a defect in the tool
  and calling it a control. It also means the *old* run was the anomaly, so
  differences it explains are properly attributed to the analyzer, in exactly
  the same bucket as a newly added checker. Treat a model fix and a new checker
  as the same kind of event.
- **A CHANGE is a real decision.** Accept it if you want current behaviour;
  pin it if you need the front end held constant while only checkers vary. Say
  which you chose -- an unstated choice silently redefines what a downstream
  comparison measures. `emit_probe.py replay --extra <flag>` applies a pin.

**Where this class of bug hides.** A wrong default only surfaces when the build
does *not* pass the flag explicitly. Most builds do pass `-std=`, which is why
such a mistake can survive for releases and affect only the minority of
projects that rely on the compiler's default -- proftpd being one. When you
choose which argument sets to probe (Step 5), deliberately include the ones
that pass the fewest explicit flags. That is where model errors live.

### Step 7. Replay, then reconcile

Replay the recorded translate invocations under the new install into a **fresh**
idir (rule 8), from the recorded working directory, against the original
sources. Replay is **non-mutating**: without `--run-compile`, `cov-translate`
writes nothing into the working directory, so it is safe to run in place
against the original tree -- which is worth doing, because it preserves the
recorded paths exactly and makes reconciliation a straight set comparison.

The analysis afterwards **need not run on the same platform as the replay**.
Emit compatibility is by format, not OS, so a WSL-emitted idir can be analyzed
by a Windows install of a version speaking that format. That is often what
makes the run possible at all when licences differ between platforms.

```bash
python3 tools/emit_probe.py replay --pairs pairs.json --bin <new-bin> \
        --dir <fresh-idir> --config <cfg>/coverity_config.xml --out replay.json
```

`replay` re-checks the licence before starting, refuses a non-empty idir
(rule 8), and reports a `SHORTFALL` line if any TU failed to emit. Pass
`--extra` to pin a flag identified in Step 6 as a genuine *change* — not a
correction. (`--extra --c11` on the worked example would be the wrong call:
Step 6 shows that one is a fix.)

Then reconcile — under an install that can read the *replayed* idir:

```bash
python3 tools/emit_probe.py reconcile --pairs pairs.json --bin <new-bin> --dir <fresh-idir>
```

It grades `CONSISTENT` / `REVIEW` / `SHORTFALL` and prints the verdict triple,
naming every TU that did not come back.

Then reconcile against the Step 2 inventory. This is not optional:

- TU count, replayed vs original
- per-TU `primaryFilename` set -- name every file that did not come back
- `hasASTs` / `astFidelityPercent` on the replayed side

**An incomplete replay looks exactly like an improvement.** Findings disappear,
counts drop, nothing errors. Same shape as the vacuous-capture trap, and it
needs the same treatment -- verify the denominator, and never report a delta
without it.

#### What is expected to break replay

*Reasoned from mechanism, not yet measured -- Step 7 is unexercised (see
`CALIBRATION.md`). Treat these as the first places to look, not as a known
failure list.*

- **Generated headers that no longer exist.** `config.h`, `version.h`,
  `buildstamp.h` and friends are build products. The recorded `input-files`
  closure names them, which is the fastest way to find out whether you have
  them before the replay tells you the hard way.
- **Absolute paths that have moved.** `--sys_include` points at a sysroot that
  may be gone or upgraded; `--pre_preinclude` points inside the old idir, so
  keep the idir rather than extracting only the JSON.
- **Compiler wrappers.** `ccache`, `distcc`, and bespoke shell scripts appear
  in the recorded translate argv as what the build actually invoked, and must
  be configured or bypassed on the replay side (rule 5).
- **`-include` of build-time files**, and response files, which may have been
  temporary.
- **A sysroot that upgraded underneath you.** Same `--sys_include` path, newer
  headers. This one is silent and would be attributed to the analyzer.

### Step 8. Report

Verdict first. State both installs by version, the control result, the
transformation delta verbatim, the accept-or-pin decision, and the
reconciliation triple (original / replayed / analyzable). Then state what you
did not check.

## Degraded path: the compiler is gone

`cov-translate` probes the compiler at build time, so if the compiler no longer
exists, Steps 4-5 cannot run. You can still replay by taking the **recorded
`cov-emit` argv directly** and retargeting `--dir` and the `--pre_preinclude`
paths -- the compiler model is already baked into those flags.

What you lose is the control, and with it the ability to distinguish a
transformation delta from an environment difference. Whether a newer `cov-emit`
accepts an older version's flag set verbatim is **not yet measured** -- treat it
as an open question, test it before relying on it, and grade any result from
this path as unverified. Do not let it pass for the probed path.

## Traps

- **`primaryFileHash` does not prove you have the right source.** It is not a
  hash of the source file. Measured: the same file, with identical path, size,
  and mtime, carries different hashes in two idirs, and no construction over
  the file's bytes reproduces it. `primaryFileSizeInBytes` *does* match disk
  exactly, and `code-line-count` is available -- use those plus VCS identity.
  See `CALIBRATION.md`.
- **A faithful replay of a bad capture is a bad capture.** Step 2 exists
  because reproducing a hole reproduces it silently.
- **The config directory changes the emit line.** Not only its contents -- its
  identity. Reproduce the original's layout, or normalize deliberately and say
  that you did.
- **Two installs in play means two chances to quote the wrong one.** Name both
  in every artifact.

---

# B. Reuse: the build is too slow to repeat

Full procedure in **`references/idir-reuse.md`**. The shape of it:

**Two gates first -- both pass/fail, both before any work.**

1. **The build system must track header dependencies.** The procedure hands
   "what does this change affect?" to the build system; one that cannot answer
   returns *nothing* and looks successful. Probe it: touch a header the idir
   says is widely included, capture the incremental build, and compare.
   Measured -- CMake+make recompiled exactly the right 3 of 4; proftpd's
   hand-written make recompiled **0 of 71**.
2. **The reference idir must come with a git commit or tag**, or you cannot
   compute a correct delta. Insist on it, then verify the claim with
   `primaryFileSizeInBytes` against `git show <tag>:<path>` -- `primaryFileHash`
   cannot do this.

**Then route on one question**: is every changed file the primary source of
exactly one TU in the idir? If yes, re-emit those TUs directly. If anything
else changed -- a header, a new file, a deletion, a rename -- touch the changed
files, capture an incremental build into a separate idir, and transplant.
Never compute the affected set yourself.

**And in both cases, delete the stale TU before adding the fresh one.**
Measured: transplanting without deleting reported an array overrun *the
developer had already fixed*, from a stale TU, against the reference tree's
path -- 1 defect where the correct answer was 0.

Do not use this path for release gates or compliance evidence. It buys
iteration speed by spending rule 8's safety margin.

---

## Related

- `coverity` -- standing rules, idir anatomy, the three-method capture-fidelity
  check. Read `RULES.md` first.
- `coverity-build-fidelity` -- the preferred path when the build still runs.
- `coverity-issue-transition-inference` -- the consumer: separates "the code
  changed" from "the analyzer got better", and needs the `(C1,A2)` cell this
  skill produces.
