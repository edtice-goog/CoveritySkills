# Worked example: two archived proftpd idirs

The calibration session behind this skill. Run 2026-08-24 against real archived
intermediate directories that nobody had planned to reuse.

Reported for the *shape* of the results and the reasoning, not as values to
look up. Emit formats and compiler defaults move nearly every release; run the
probe for the pair you actually have.

## Environment

Windows 11, Coverity installations under `C:\Coverity\` (many versions side by
side -- the normal state of a Coverity user's machine). WSL2 Ubuntu with
gcc 13.3.0 available.

The subject: `C:\analysis\proftpd\idir1.3.8` and `idir1.3.9`. Both were
produced on 2025-05-19 by `cov-analysis-linux64-2024.12.1` running under WSL
from `/home/etice/proftpd`, each emitting 90 C translation units at 100%, and
each already carrying a completed analysis from that same version:

| idir | source rev | TUs | defects |
|---|---|---|---|
| idir1.3.8 | proftpd 1.3.8 | 90 | 93 |
| idir1.3.9 | proftpd 1.3.9 | 90 | 92 |

Both analyses were `cov-analyze --dir <idir>` with no further arguments, so
checker configuration is constant between them.

This is the transition-inference setup in miniature: two snapshots, one
analyzer, a one-defect delta -- and no way to ask what a *newer* analyzer would
have said about the older code without re-analyzing it.

All work was done on **copies**. `cov-analyze` and `cov-manage-emit` write into
the idir; the originals were left untouched.

## Step 1 -- identification, and the refusal

```bash
cat idir1.3.8/emit/version
```
```
# Version file created with Prevent version 2024.12.1
343
```

The idir names its own creator. Line 2 is the emit format number.

Pointing the newest installed analyzer at it:

```bash
/c/Coverity/cov-analysis-win64-2026.6.0/bin/cov-manage-emit.exe --dir <copy> list
```
```
Version mismatch in .../emit:
Expected version number is 355, but this directory has version 343.
The given directory was created with a different version of this software and
is incompatible with the current version.  It must be removed and then
re-created with the current version in order to proceed.
```

Exit code **2**. Loud, specific, no partial output. Worth naming explicitly
because it is unusual for this problem domain: most of the failure modes in
`coverity/RULES.md` succeed-looking-wrong, and this one simply refuses.

## Step 1b -- which installs can read it

Sweeping every installed win64 version and recording the "Expected version
number is N" it reported gave a strictly monotonic sequence across releases,
with adjacent patch releases sometimes sharing a format. Exactly one install
opened the idir.

**Two results worth keeping, neither of which is a table:**

- **The compatibility window is zero.** Exact format match only. There is no
  "reads N-2" range to exploit.
- **The compatibility key is the format, not the product version, and not the
  platform.** The install that read it was **win64 2024.12.0** -- a different
  product version *and* a different operating system from the
  **linux64 2024.12.1** that wrote it. It listed all 90 TUs, matching the build
  log.

The second point is the useful one operationally: you do not need the exact
build machine, or even its OS, to open an archived idir. You need something
speaking format 343.

This is why the skill tells you to probe your installs rather than consult a
matrix -- the matrix would be ten rows that go stale, and it would also have
hidden the cross-platform result behind an assumption about platform tags.

## Step 2 -- the capture was sound

`cov-build`'s own log for both runs: `Emitted 90 C/C++ compilation units
(100%) successfully`, then `90 ... are ready for analysis`. `list-json` showed
`hasASTs: true`, `isFailure: false`, `astFidelityPercent: 100` throughout, and
`metrics` reported `tu-count: 90, tu-failures: 0`.

So there is no vacuous-capture problem here, and a faithful replay is worth
attempting. Had this been the partial-build case from
`coverity/references/worked-example-vacuous-capture.md`, replaying it perfectly
would have reproduced the hole.

## Step 3 -- extraction

```bash
cov-manage-emit --dir <copy> list-capture-invocations > inv.json     # 3.1 MB
```

```
files                        413
environment-variables         68   in 5 blocks (29, 61, 59, 59, 59)
cov-build-invocations          1
cov-translate-invocations     90
cov-emit-invocations          90
translation-units             90   (input-files: 222 for TU 1)
link-units                     0
metrics                       tu-count 90, tu-failures 0, lu-count 0
```

The recorded input for TU 1:

```
cov-translate gcc -DHAVE_CONFIG_H -DLINUX -I.. -I../include -I../include -g2 -O2
              -Wall -fno-omit-frame-pointer -fno-strict-aliasing
              -c pr_fnmatch.c -o pr_fnmatch.o
```

cwd `/home/etice/proftpd/lib`. The recorded output was a 61-token `cov-emit`
line carrying `--comp_ver 13.3.0`, `--gnu_version 130300`,
`--type_sizes=e16Pdlx8fi4s2`, four `--sys_include` paths, and
`--coverity_config_md5=b577f776b05173caa21361c7ea6c1f1d`.

## Step 4 -- the control

The proftpd sources were still present in WSL (at 1.3.9), and gcc was still
13.3.0 -- matching the recorded `--comp_ver` exactly. So the control could run
on the same platform as the original capture.

```bash
: > /tmp/rfe/proftpd/lib/empty.c
cd /tmp/rfe/proftpd/lib
<2024.12.1>/bin/cov-translate --dir /tmp/rfe/idir_old --config <cfg>/coverity_config.xml \
    --dryrun gcc <recorded flags> -c empty.c -o empty.o
```

Also confirmed here: `--dryrun` and a real run emit the same `cov-emit` line,
differing only in the per-session `--ignore_path`. The probe therefore costs
nothing and emits nothing.

Normalized comparison against the recorded line: **61 recorded tokens vs 59
generated**, with one residual --

```
- --preinclude
- <install>/config/template-gcc-config-0/../user_nodefs.h
```

### Running down the residual

This looked like a version difference and was not. `BUILD.metrics.xml` records
the original build's configuration:

```
<metric><name>config</name>
  <value>/mnt/c/Coverity/cov-analysis-linux64-2024.12.1/config/coverity_config.xml</value>
```

The original build used the **install's own** config directory, which ships a
`user_nodefs.h` (1440 bytes, dated with the install). The probe used a fresh
`cov-configure --config /tmp/...` directory -- which contains
`coverity_config.xml`, `configure-log.txt`, and eight `template-*-config-N`
directories, but **no `user_nodefs.h`**. No file, no `--preinclude`.

So the control **passes**: same-version regeneration is exact, once the config
layout is accounted for.

**The fix was not to mask the token.** The pre-includes and nodefs are pulled
from the same product version as `cov-emit` -- each run supplies its own from
the install it is using -- so the right handling is a **path transform** that
keeps `--preinclude` and rewrites only its root. Masking it made the control
pass for the wrong reason and would have hidden a genuine presence asymmetry.
With the transform, and `user_nodefs.h` seeded from the install being probed,
the control is `IDENTITY` at **61 tokens including the `--preinclude`** rather
than 59 with it dropped.

Corroborating detail: `--coverity_config_md5` came out
`b577f776b05173caa21361c7ea6c1f1d` in both the May 2025 production build and
the August 2026 regeneration -- identical config identity across fifteen
months and two different config directories.

This residual earned `user_nodefs.h` its own note in
`transformation-probe.md`, and it is the reason the normalization set
distinguishes MASK from TRANSFORM at all.

## Step 5 -- the cross-version delta

Same recorded input, newer install. Equal token counts after normalization.

```
--- 2024.12.1
+++ 2025.12.2
   --builtin_emulation
   --gcc
 - --c11
 + --c17
   --gnu_version
   130300
```

Everything else identical: `--comp_ver 13.3.0`, `--gnu_version 130300`, the
whole type model (`--type_sizes`, `--type_alignments`, `--size_t_type`,
`--wchar_t_type`, `--ptrdiff_t_type`), all four `--sys_include` paths, every
`-D` and `-I`, and the entire builtin/emulation block.

Note the line contains `--c11` twice in the original; only the one in the
trailing `--gcc --c11 --gnu_version` group changed.

**One token, and it is semantic.** The C language level the front end is told
to use moved from C11 to C17. That changes what the front end accepts and what it
predefines, before any checker runs -- so "same code, newer analyzer" would
have been false in a way nothing would have reported.

This is the result that justifies the whole procedure. The transformation was
*almost* identity, which is precisely the condition under which people stop
checking. The first pair ever put through this probe was not identity.

### Which version was right

The delta says the versions disagree; it does not say who is correct. The
compiler does. proftpd's recorded command line passes no `-std=`, so:

```
$ echo | gcc -dM -E -x c - | grep __STDC_VERSION__
#define __STDC_VERSION__ 201710L        # C17
$ echo | gcc -std=c11 -dM -E -x c - | grep __STDC_VERSION__
#define __STDC_VERSION__ 201112L
```

gcc 13.3.0's real default is **C17**. So `--c11` was a **defect in Coverity's
model of gcc**, and `--c17` is the fix. Coverity has to reproduce each
compiler's flag handling by hand; that is human work and it can be wrong.

This inverts the obvious response. Pinning `--c11` back to "hold the front end
constant" would reproduce a known-wrong parse and dress it up as a control. The
correct handling is to **accept the correction** and treat the findings it
moves exactly as you would treat findings from a newly added checker -- an
analyzer improvement, not code change and not drift.

It also explains why a bug like this can live for releases: it only bites
builds that omit `-std=`, and most builds pass it. proftpd is in the minority
that does not, which is the only reason this probe caught it.

## What this session revised

The stub this skill grew from proposed gating replay on `primaryFileHash`,
described as an MD5 proving you have the exact source revision. **That does not
work, and the measurement was unambiguous:**

- `lib/pr_fnmatch.c` has the same path, the same size (13692 bytes), and the
  same `last-modified` (`2025-05-19T20:04:11+0000`) in both idirs -- and a
  different `primaryFileHash` (`1da77d10...` vs `bb0d38df...`). A value that
  changes while the file demonstrably does not is not a function of the file.
- Tested against the real bytes: `md5`, `sha1[:32]`, `sha256[:32]`,
  `md5(path+content)`, `md5(content+path)`, `md5(path)`, and both line-ending
  normalizations. None reproduced either recorded value.
- Not mtime-driven either: 57 of 90 files differ in `last-modified` while 86 of
  90 differ in hash, and the two sets are not the same set.

What *does* hold up: `primaryFileSizeInBytes` matches the on-disk file exactly,
`code-line-count` is recorded per file, and `input-files` enumerates the full
include closure. The revision gate has to be built from those plus VCS
identity. The construction of `primaryFileHash` remains unknown and is in
`CALIBRATION.md`.

## Steps 6-8: the replay

Run against `idir1.3.9`, whose sources were still present in WSL at 1.3.9.

**The source-identity gate first.** With `primaryFileHash` ruled out, the gate
is `primaryFileSizeInBytes` against disk: **all 90 primaries present, all
byte-exact**, fifteen months after capture. That is what licensed the replay.

**Choosing the new side.** The first attempt used 2025.12.2 and failed at the
last step -- `[FATAL] No license files ... found`, rc 47 -- *after* a
successful 90/90 replay. The second attempt used 2025.9.0, whose Linux licence
had expired (rc 2). Both replays were completely healthy; only analysis
refused. This produced the Step 0 licence pre-flight, and the note that replay
needs no licence at all.

The run completed by emitting under linux64 2025.9.0 in WSL and analyzing with
**win64 2025.9.0** -- the same emit format (350), a different operating system.
That is the format-not-platform finding paying for itself.

**The probe, before replaying.** 2024.12.1 -> 2025.9.0 came back `IDENTITY` at
61 tokens across three pairs. So on this pair there was no drift to accept or
pin, and the analyzer became the only variable -- unlike the 2025.12.2 pair
measured earlier. Same starting version, different answer.

**The replay.** All 90 recorded `cov-translate` invocations re-run from their
recorded working directories against the real sources: **90/90 rc=0, 90/90
emitted, 114s.** The first TU costs ~24s (the build-time template probe fires),
the rest ~1s each.

Run in place in the original tree, which is safe: verified separately that
`cov-translate` without `--run-compile` writes nothing to the working
directory. Running in place keeps the recorded paths, which makes
reconciliation a straight set comparison instead of a prefix-mapping exercise.

**Reconciliation.**

```
original 90 / replayed 90
missing 0 | extra 0 | size mismatches 0
TUs without ASTs 0 | isFailure 0 | astFidelityPercent 100 throughout
```

Graded `CONSISTENT`.

**Analysis.** `cov-analyze --dir <replayed>` under win64 2025.9.0, rc=0. Files
analyzed 149, functions 2086, classes 159 -- identical to the archived
2024.12.1 analysis of the same code. `Total LoC input` moved 98481 -> 98488,
a 7-line difference with files and functions equal; unexplained, and on the
queue.

The defect count moved as well. Attributing that movement is
`coverity-issue-transition-inference`'s job, not this skill's; what this
session establishes is that the artifact it needs can be produced from an
archived idir without rebuilding.

## What the dogfooding changed

Running the procedure as written found four things the first draft got wrong
or missed:

1. **The tool had no `replay` step.** The procedure described Steps 7-8 and the
   tool stopped at `delta`.
2. **The version-owned includes were masked, not transformed.** Dropping the
   `--preinclude user_nodefs.h` token hid a real presence asymmetry. They are
   pulled from the same product version as `cov-emit`, so the correct handling
   is a path transform -- keep the token, rewrite the root. This also removed
   the need to copy files between config directories.
3. **No licence pre-flight.** Two full replays completed before the missing and
   expired licences surfaced, both at the last step.
4. **The `--c11 -> --c17` delta was over-generalized.** It is specific to the
   2025.12.2 pair; 2024.12.1 -> 2025.9.0 is identity. Drift cannot be predicted
   from version numbers, which strengthens rather than weakens the case for
   probing.

## Not done in this session

- **The degraded path** -- replaying a recorded `cov-emit` argv directly when
  the compiler is gone -- remains untested. Every measurement here had gcc
  13.3.0 still installed and matching `--comp_ver`.
- **Only C.** The `g++` arm is a separate template config and may drift
  differently; `--c11`/`--c17` is a C-mode flag.
- **Only clean outcomes.** Every reconciliation was perfect, so the shortfall
  path has never fired. The claim that an incomplete replay is silent is still
  reasoned from the vacuous-capture measurement in `coverity`, not measured
  here.
- **Two version pairs**, from one starting version, on one project.
