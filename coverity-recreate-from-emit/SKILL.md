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
  fresh-intermediate-directory rule and carries three applicability gates (the
  idir must have been analyzed on the same platform you will analyze on, the
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

| Path | Situation | Where |
|---|---|---|
| **Recreate** | *"Analyze an old capture with a new analyzer."* The build **cannot be run** -- toolchain gone, CI retired, old commit no longer builds -- and a newer analyzer refuses the old emit | below |
| **Fast-forward** | *"I have been away; catch my idir up."* A reference idir some distance behind the working tree, brought current across many commits. Typically CI or a PR gate | `references/idir-reuse.md` |
| **Local update** | *"Include what I have not committed yet."* An idir at a known commit, brought current with the **uncommitted** working tree, fast enough to run before committing | `references/idir-reuse.md` |

*Recreate* is about recovering analyzability across a version gap. The other
two are about speed during active development, and both **deliberately violate
rule 8** -- read the three applicability gates before starting, because knowing
when they do not apply is most of that procedure.

**Fast-forward and Local update are the same machinery with different deltas**,
and are documented together on purpose. Do not let them drift apart:

|  | Fast-forward | Local update |
|---|---|---|
| delta computed from | `git diff <idir-commit>..HEAD` | `git diff` / `git status` -- working tree |
| target has a commit identity | yes | **no**, it is uncommitted work |
| judged against | the full clean capture | the **incremental build** just run |
| typical cohort | CI, pull-request gate | desktop, pre-commit |
| tolerable cost | minutes | seconds |

Everything else -- the gates, the staleness check, the stale-TU rule, model
provenance, the analysis step -- is identical, and a change to one should be
made to both unless there is a stated reason it applies to only one. Gate 0 is the cheapest and rules out whole
deployments in one command: if the reference idir was analyzed on a different
**platform** than the one you will analyze on, incremental analysis is
discarded and the reason to reuse goes with it.

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

**If anything in this skill will talk to Connect, check TLS now too.** Fetching
a reference idir, the cost estimator, and `--preview-report-v3` all make TLS
connections, and on a network with an inspecting proxy they fail *after* you
have spent the setup effort. The trap is that there are **four independent
trust stores** and fixing the obvious ones is what makes you believe the
network is fine: Coverity ships its own JDKs, each with its own `cacerts` that
no environment variable touches. Measured on
`cov-analysis-linux64-2025.12.2`: three bundled JDKs, 109 trusted certs each,
**zero** corporate entries.

```bash
# Fails only for intercepted hosts, so test the Connect host specifically.
<install>/jdk21/bin/keytool -list   -keystore <install>/jdk21/lib/security/cacerts -storepass changeit | grep -ci <vendor>
```

`PKIX path building failed` means this JVM has never heard of your corporate
CA. Full procedure, including the Go/cipd case that hangs with **no error at
all**, in `references/corporate-tls.md`.

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

## If the compiler is missing, go and get it

**This skill solves "the build cannot be run repeatably". It does not try to
solve "the toolchain no longer exists anywhere".** Those are different problem
classes, and the second one is both much harder and much less interesting --
in most cases the compiler is open source and obtainable.

So when `cov-translate` cannot probe because the compiler is absent, the
answer is to **install the compiler**, not to reverse-engineer Coverity's model
of it. The idir tells you exactly which one to fetch.

Where the evidence lives, measured on a real idir:

| source | what it gives you |
|---|---|
| `build-log.txt` | the resolved executables -- `/usr/bin/x86_64-linux-gnu-gcc-13`, `/usr/libexec/gcc/x86_64-linux-gnu/13/cc1` -- so vendor, **target triple** and major version |
| `build-log.txt` | the probe's own version output; `13.3.0` appeared 110 times in the one examined |
| the recorded `cov-emit` line | `--comp_ver 13.3.0`, `--gnu_version 130300`, and every `--sys_include`, which also reveals the distro's header layout |
| `emit/<host>/config/<hash>/*/coverity_config.xml` | the probed model per configured compiler |

Between the target triple and the exact version that is an install command on
most systems. Match the version: `--comp_ver` is what the recorded emit line
asserts, and a different point release can model differently.

**Do not attempt to replay a recorded `cov-emit` line directly to route around
a missing compiler.** It looks tempting -- the compiler model is already baked
into those flags -- but it trades a solvable problem (obtain a compiler) for an
unverifiable one: with no compiler there is no control run, so the
transformation probe cannot execute and nothing downstream can be graded.
Whether a newer `cov-emit` even accepts an older version's flag set is
unmeasured, and deliberately left that way.

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

# Bootstrapping: noticing that a project uses Coverity

A `SessionStart` hook (`hooks/coverity-session-start.sh`) makes this skill
discoverable without the user having to remember it, and **without touching
projects that do not use Coverity**.

The trigger is the presence of the Coverity CLI's own config -- `coverity.yaml`,
`coverity.yml`, or `coverity.json` in the project directory. That file means
Coverity is enabled here. No file, no output, `exit 0`: installed globally, the
hook has zero effect on every other repository. That silence is the point --
a prompt in an unrelated project is a cost paid by everyone to help a few.

Install once in `~/.claude/settings.json`:

```json
{ "hooks": { "SessionStart": [ { "hooks": [
    { "type": "command",
      "command": "<repo>/coverity-recreate-from-emit/hooks/coverity-session-start.sh",
      "timeout": 10 } ] } ] } }
```

Output reaches the session as `hookSpecificOutput.additionalContext`.

**The hook computes nothing, and that is deliberate.** It does not read git,
inspect a cache, or contact anything. It tells the session the skill exists and
instructs it to *offer once*, then stop. Two reasons:

- The option space is not settled. Recommending a path before we know the
  tradeoffs would bake in guesses.
- **Importing a baseline is not always right.** On a small codebase a plain
  `cov-build` plus `cov-analyze` is simpler and finishes fast enough that the
  whole import apparatus is wasted motion. Deciding that needs a conversation,
  not a hook.

So the hook's contract is: announce, ask, recommend -- never act. Capture,
download, and analysis all wait for the user to choose.

*Do not extend it to fetch anything.* A baseline idir is on the order of
300 MB; downloading one on every session start would be far worse than the
problem it solves.

## The choice is revisable, and the skill should revisit it

The estimate picks a path; it does not settle one. A project that took six
minutes a year ago may take twenty-five now, and nobody re-runs the arithmetic
on their own. **Watch what the chosen method actually costs, and say when a
different one has become worth it.**

Two signals, and both are free:

- **The history keeps accumulating.** Every post-merge snapshot adds a data
  point, so re-running `tools/estimate_from_connect.py` later is a direct
  measurement of whether the project has outgrown its current method. Measured
  on proftpd: 4m03-4m34 on one release line, 5m48-20m26 on another. A project
  can move between those bands without anyone noticing.
- **The local run just told you.** Whatever path is in use, it reported its own
  elapsed time. Compare it against the estimate the decision was made on.

When to raise it:

| observed | if currently | suggest |
|---|---|---|
| full capture creeping past ~15 min | capturing fresh each time | importing a baseline -- the inner loop is now the bottleneck |
| delta capture recompiling most of the project | reusing | the delta has outgrown the technique; capture fresh (see break-even) |
| consistently a few minutes | reusing | drop back to fresh capture and reclaim rule 8's guarantees |

The last row matters as much as the first. **Upgrading is not the only useful
direction** -- a project that shrank, or whose build got faster, should shed the
apparatus rather than carry it out of habit.

Raise it once, with the number that changed, and let the user decide. Do not
switch methods on your own: the choice has consequences for what the results
mean, and rule 8's guarantees are the user's to spend.

## Prerequisite: a properly formed coverity.yaml. No file, no skill.

**This gate precedes everything, including the applicability gates for reuse.**

The project must carry a Coverity configuration -- `coverity.yaml`,
`coverity.yml`, or `coverity.json` -- and it must **name the Connect stream**.
Presence alone is not enough. The stream is where the snapshot history lives,
and that history is what decides whether any of this is worth doing.

"Properly formed" is the product's definition, not one invented here: the
Coverity CLI's own configuration schema makes `commit.connect.stream` and
`commit.connect.url` **both required**.

```bash
python3 tools/check_prerequisites.py --project-dir <project>
```

Exit 0 and it reports the stream, the URL, and where the developer's auth key
should live.

**Two gates of different hardness, and the difference matters:**

- **The file's presence is absolute.** No `coverity.yaml`, the skill does not
  run. That is what keeps it inert in projects that do not use Coverity.
- **What the file contains is softer.** No stream means abort *by default* --
  never invent one, never fall back to asking as though any answer will do.
  But a user may genuinely need a stream this file does not name, and it is
  their data. `--stream` / `--url` override, loudly and never silently.

The warning on override is not ceremony. **A stream is a destination**: get it
wrong and source code and defect data are committed somewhere they were never
meant to go, which noticing afterwards does not undo. That is rule 28's
auth-key-host failure arriving through a different door, and it deserves the
same treatment -- surface it, name the risk, proceed only on explicit intent.

**The Coverity CLI itself will not run on a broken config, so this gate is
predicting a failure rather than inventing a restriction** -- but it is stricter
than the CLI in the direction that matters. Measured on 2025.9.0:

| config state | `coverity` CLI |
|---|---|
| malformed YAML | **rc=1**, `[ERROR] Failed to parse the configuration file.` |
| valid YAML, unknown key or missing required section | **rc=0** with `[WARN] ... has issues which may need to be addressed` |

So a file the CLI merely *warns* about -- one that parses but names no stream --
would sail past the front door and fail later, at the point some command
actually needs the stream. Failing here instead costs a second and says exactly
what is wrong, rather than surfacing halfway through a capture.

### Coverity Scan projects: manual only, and here is why

Open-source projects on Coverity Scan follow an older convention that has not
been updated. Under it the configuration lived in **`.travis.yml`**, as an
`addons.coverity_scan` block plus an encrypted `COVERITY_SCAN_TOKEN`:

```yaml
env:
  global:
    # encrypted COVERITY_SCAN_TOKEN, via "travis encrypt"
    - secure: "cn1+7McUqDa+GLXnLqD/..."
addons:
  coverity_scan:
    project:
      name: ...
```

That is detectable in principle. What makes it unusable in practice is that the
mechanism died with Travis. proftpd is the worked case: it carried exactly that
block, then **deleted `.travis.yml` wholesale** when it moved to GitHub Actions
(*"Now that we've switched to GitHub Actions, we can remove the old Travis CI
configuration"*). Its current checkout retains a single modeling file,
`contrib/dist/coverity/modeling.c`, and **none of its four workflows mentions
Coverity at all**.

So the honest position is narrower than "Scan config is never in the repo":

- a project *still* on Travis-based Scan has a findable `addons.coverity_scan`
- a project that has moved on, as most have, leaves **nothing reliable behind**

Probing for the second case means searching for something that is usually
absent, on every session, in every repository. That is the argument against it:
not that it is slow, but that it is mostly a search for nothing.

The session-start hook therefore checks `coverity.yaml` and nothing else. A
Scan project stays silent, which is correct. **To use the skill there, invoke
it manually with `--stream` and `--url`** -- the same override path, with the
same destination warning, because nothing was cross-checked against the
project.

Commercial users are the expected audience and should have a `coverity.yaml`
regardless: the GitHub action depends on it. A project still on the older
mechanism should add one.

The same conservatism applies to reading the file. With no YAML parser
available the tool uses a narrow reader for the ordinary nesting and **refuses
on anything else** rather than guessing -- a wrong stream name is worse than no
answer.

It also derives the auth key path. The CLI documents the default as
`$HOME/.coverity/ak-<hostname>-<port>`, so on a developer machine the key
usually need not be asked for at all.

## Step 1 of any reuse decision: is it worth it?

Before proposing anything, find out what a full run actually costs. **The
project already knows.** Every snapshot committed to Coverity Connect records
its own `buildTime` and `analysisTime`, plus the translation-unit count and the
exact commands used. On a well-run pipeline that history is a side effect of
post-merge CI, so the estimate is free and beats any guess from lines of code.

`coverity.yaml` supplies the connection: `commit.connect.url` and
`commit.connect.stream`.

```bash
python3 tools/estimate_from_connect.py --url <connect-url> --stream <stream>         --auth-key-file <key> [--insecure]
```

It lists the stream's snapshots, reads each one's timings, drops outliers by
median-absolute-deviation (robust at the handful of snapshots a stream
actually has, where mean-and-stddev is skewed by the outlier it is meant to
find), and reports a median-based estimate with a recommendation.

Measured example -- proftpd, three snapshots: capture 5m36s / 6m17s / 5m17s,
analysis 74s / 56s / 69s, 90 TUs each. Estimate **6m 45s**, and the honest
recommendation at that size is *do not bother* -- a fresh capture keeps rule
8's guarantees and costs little. The reuse apparatus earns its keep when
this number runs to tens of minutes or hours.

**Take the host from the user, never from the auth key.** The tool prints a
warning when the key's `comments.host` disagrees with the URL supplied, and
uses the supplied one (rule 28).

Interface notes: `GET /api/v2/snapshots/<id>` is REST and returns clean JSON.
Listing a stream's snapshot ids still goes through SOAP
(`getSnapshotsForStream`) because the documented REST route
`/api/v2/streams/stream/snapshots` returns 400 for every parameter name tried
-- the route exists, the parameter is undetermined. The swagger UI at
`/swagger/cim/index.html` would settle it but requires a browser session;
basic auth returns the sign-in page. Open item.

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

# Attribution: which of these are mine?

Producing an idir is half the job. The other half is answering *what did I
break* -- and Coverity Connect answers it, so do not build a parallel
mechanism.

After a full `cov-analyze` on the updated idir:

```bash
cov-commit-defects --dir <idir> --url <connect-url> --stream <stream>     --auth-key-file <key> --preview-report-v3 report.json
```

The server returns, per issue: `cid`, `mergeKey`, **`presentInComparisonSnapshot`**,
**`firstDetectedDateTime`**, a full `triage` block (severity, owner,
classification, action, fixTarget, legacy), `customTriage`, and
`ownerLdapServerName`. `--comparison-snapshot-id` selects the baseline;
otherwise the most recent is used.

**Measured, from an imported idir with foreign paths:** 112 issues, 111
`presentInComparisonSnapshot: true` carrying first-detected dates as old as
2017, and exactly one `false` -- the single defect planted for the test, in the
right file and function. Two seconds. Attribution is a solved problem; use it.

Filter on `presentInComparisonSnapshot` plus owner, with `git blame` for code
Connect has not seen. Not on raw merge-key diffs between two local runs --
rule 27.

## Preview is not free, and the cost is permanent

`--preview-report` "sends only the defect occurrences" and creates **no
snapshot** (verified: the next snapshot id 404s afterwards). It is easy to read
that as side-effect-free. It is not.

**Measured.** Running the same preview twice returned **identical CIDs for all
112 merge keys**, and the newly-seen defect kept both its allocated
`cid=10223` and its original `firstDetectedDateTime` on the second run. So the
preview **allocates CIDs and records first-detection**, and that state persists.

Two consequences:

- **A defect's first-detected date is set by whoever previews it first**, not
  by the CI commit. Preview on Monday, have CI commit on Friday, and the record
  says Monday. Anyone using first-detected for age or SLA reporting should know
  that a developer's local run writes it.
- **Test previews leave CIDs behind.** They do not appear in snapshot-scoped
  queries -- there is no snapshot to scope to -- but the mapping is real and
  permanent. Do exploratory previews against a scratch stream, not a stream
  anyone reports from.

It also needs its own privilege: Connect exposes **`previewCommit` ("Preview
Commit") separately from `commitToStream` ("Commit to a stream")**, so a
developer can be granted preview without the ability to commit snapshots. Ask
for that permission specifically rather than full commit rights.

---

## Related

- `coverity` -- standing rules, idir anatomy, the three-method capture-fidelity
  check. Read `RULES.md` first.
- `coverity-build-fidelity` -- the preferred path when the build still runs.
- `coverity-issue-transition-inference` -- the consumer: separates "the code
  changed" from "the analyzer got better", and needs the `(C1,A2)` cell this
  skill produces.
- `references/corporate-tls.md` -- TLS-inspecting proxies: the four trust
  stores, why Go and the JVM fail differently, and how to fix both without
  modifying the Coverity install or the system trust store.
- `references/target-state.md` -- bringing an idir current **without knowing
  its provenance**: extract-files, what the recorded hash is and is not, and why
  this removes Gate 2 but not Gate 1.
