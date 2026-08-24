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

Corroborating detail: `--coverity_config_md5` came out
`b577f776b05173caa21361c7ea6c1f1d` in both the May 2025 production build and
the August 2026 regeneration -- identical config identity across fifteen
months and two different config directories.

This residual earned `user_nodefs.h` its own note in
`transformation-probe.md`. It is user-modifiable content that feeds the front
end, so it is both a probe artifact *and* a real replay input.

## Step 5 -- the cross-version delta

Same recorded input, newer install. Both lines 60 tokens after normalization.

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

**One token in sixty, and it is semantic.** The default C language level moved
from C11 to C17. That changes what the front end accepts and what it
predefines, before any checker runs -- so "same code, newer analyzer" would
have been false in a way nothing would have reported.

This is the result that justifies the whole procedure. The transformation was
*almost* identity, which is precisely the condition under which people stop
checking. The first pair ever put through this probe was not identity.

For feeding `coverity-issue-transition-inference`, the right response here is
to pin the language level back to `--c11`, so that `(C1,A2)` differs from
`(C1,A1)` in the analyzer only.

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

## Not done in this session

- No replay was executed end to end; the probe and the control were the
  session's scope. Steps 7-8 of the procedure are unexercised.
- Only a C argument set was probed. The `g++` arm is a separate template
  config and may drift differently -- `--c11`/`--c17` is a C-mode flag.
- Only one version pair was measured. Whether deltas grow with distance is
  unmeasured.
- The degraded path (replaying a recorded `cov-emit` argv directly under a
  newer `cov-emit`) was not tested at all.
