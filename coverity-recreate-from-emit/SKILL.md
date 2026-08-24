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
  rather than on the assumption that the translation is unchanged. Requires
  local Coverity installations -- both the version that wrote the idir and the
  version you want to analyze with.
---

# Recreate from emit

`coverity-build-fidelity` assumes you can run the build. Often you cannot. When
the build is unavailable, **the intermediate directory is the surviving record
of it** -- and it is a better record than it first appears.

The deliverable is an idir that a *newer* analyzer will accept, plus evidence
that it corresponds to the same code as the original, plus an honest grade when
it does not.

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

Do not skip this because the transformation "is obviously identity". On the
first pair this procedure was ever run against, it was not:

```
--c11   ->   --c17
```

One token in sixty. The default C language level moved, which changes parsing
and predefined macros. That is precisely the kind of drift that otherwise gets
misattributed to "the analyzer got better".

`references/transformation-probe.md` has the method in full.
`references/invocation-anatomy.md` maps what the invocation record contains.

## Procedure

### Step 0. Rules, and pin two installations

Read `coverity/RULES.md`. Pin **two** installs and record both: the one whose
format matches the idir (the *old* side) and the one you want to analyze with
(the *new* side). Rule 3 says pin one; this skill is the exception that
requires exactly two, which is why they must be named explicitly in the report.

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

- the config directory differs from the one the original build used. In
  particular `user_nodefs.h` ships inside an install's own `config/` but is
  **not** created by `cov-configure --config <newdir>`, and its presence adds a
  `--preinclude` to the emit line. It is user-modifiable content and a real
  semantic input -- carry it over.
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
| semantic | changes what the front end accepts or predefines | decide explicitly |

`--c11 -> --c17` is semantic. There are two defensible responses, and they
answer different questions:

- **Accept it** -- you want the new analyzer's current behaviour, drift included.
- **Pin it back** -- append the old flag to hold the language level constant, so
  the only variable is the analyzer's checkers.

For downstream issue-transition inference, pinning is usually right: it keeps
`(C1,A2)` differing from `(C1,A1)` in *one* input. Say which you chose. An
unstated choice here silently redefines what the comparison measures.

### Step 7. Replay, then reconcile

Replay the recorded translate invocations under the new install into a **fresh**
idir (rule 8), from the recorded working directory, against the original
sources.

Then reconcile against the Step 2 inventory. This is not optional:

- TU count, replayed vs original
- per-TU `primaryFilename` set -- name every file that did not come back
- `hasASTs` / `astFidelityPercent` on the replayed side

**An incomplete replay looks exactly like an improvement.** Findings disappear,
counts drop, nothing errors. Same shape as the vacuous-capture trap, and it
needs the same treatment -- verify the denominator, and never report a delta
without it.

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

## Related

- `coverity` -- standing rules, idir anatomy, the three-method capture-fidelity
  check. Read `RULES.md` first.
- `coverity-build-fidelity` -- the preferred path when the build still runs.
- `coverity-issue-transition-inference` -- the consumer: separates "the code
  changed" from "the analyzer got better", and needs the `(C1,A2)` cell this
  skill produces.
