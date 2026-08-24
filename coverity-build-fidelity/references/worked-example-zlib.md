# Worked example: calibrating on zlib (MSVC 2022, Ninja, Release)

The session that established this skill's baseline. Every number here came
from a real run; three of the design decisions in SKILL.md exist because a run
contradicted the plan.

Target: zlib from `C:\Data\repo-monitoring-workspace\stage3\src\zlib`,
MSVC 2022 (14.44.35207), CMake + Ninja, `Release`, built into a dedicated
`build-fid` directory so existing trees were never touched.
Coverity 2026.3.0.

## 1. Three native builds -- does the premise hold?

Same directory each time, artifacts snapshotted between runs (5 binaries + 34
objects = 39 artifacts).

```
files=39  identical=1  shape_agrees=38  shape_differs=0
files with unresolved regions: 0
```

The premise holds: pairwise delta shapes agree. Baseline signature in
`ephemeral-fields.md`.

### What went wrong first

**35 of 39 files came back unresolved** on the first pass -- a single region at
offset 4, length 1. That is the COFF `TimeDateStamp` of a *bare object file*,
which has no `MZ`/`PE` wrapper. The parser only handled PE images. Without
object and archive support the fast path would dump 35 files of noise onto the
model every run.

**`zlibstatic.lib` reported a shape mismatch that was not one.** The same
archive timestamp appeared as `(106192, 2)` in one pair and `(106191, 3)` in
the others -- different bytes of the field happened to collide in different
runs. Exact-offset region keys call that divergence. Switching to interval
overlap with +/-8 bytes of slack resolved it. This is why
`threeway.subtract()` is overlap-based; the same failure would otherwise
manufacture a false `K` in production.

## 2. Refactor control

Both arms must run the identical inner build script, so the build was
refactored into `zlib_build_inner.bat` with native and Coverity wrappers. A
fourth native build through the new wrapper still shape-agreed with runs 1
and 2 -- confirming the refactor changed nothing.

## 3. The Coverity arm

`cov-configure --msvc`, then `cov-build` wrapping *the same inner script*.

```
files=39  identical=1  shape_agrees=38  shape_differs=0
files with unresolved regions: 0
```

**`K` is empty.** `cov-build` perturbed nothing: every byte that differs
between the Coverity build and the natives falls in the same ephemeral fields
the two natives differ in.

## 4. Capture coverage -- the headline number is a trap

```
Emitted 40 C/C++ compilation units (97%) successfully
[WARNING] Recoverable errors were encountered during 1 of these
```

A `< 100% -> fail` gate rejects this build. It should not. The failing TU was
`CheckIncludeFile.c` under `CMakeFiles/CMakeScratch/TryCompile-3nazsv/` -- a
CMake configure-time feature probe. `OFF64_T.c` supplied the recoverable
errors, also a probe.

Reconciled via `cov-manage-emit list`:

| | |
|---|---|
| Emitted CUs | 40 |
| build-system probes (TryCompile, CompilerId, ShowIncludes) | 8 |
| product TUs | 32 |
| product objects built (34 total - 2 build-system) | 32 (match) |
| unique product sources emitted / compiled | 17 / 17 (match) |

32 TUs from 17 sources because zlib compiles each into both `zlib.dir` and
`zlibstatic.dir`. **Product capture: 100%.**

Note the denominator trap: object count (32) and unique-source count (17) are
both correct answers to different questions. Comparing across them
manufactures a discrepancy.

## 5. Path sensitivity

`paths.py` on the shipped DLL:

```
[n/a] debug directory: no CODEVIEW/RSDS record -- build emitted no PDB
      reference, so this artifact carries no PDB path
path-shaped strings: 1   ->  p://www.zlib.net/     (a URL, false positive)
```

Two fixes: URL schemes satisfy the drive-letter shape and needed a
`(?![\\/])` guard; and a single embedded path is still evidence, so the
"needs two supporting strings" threshold was wrong.

The same scan on `deflate.c.obj` found the full build path in `.debug$S`.

### The experiment

zlib was staged at `C:\a\1\s\zlib` (Azure DevOps shape, 15 chars vs the local
49) and rebuilt, standing in for an official CI build.

| Artifact | Result |
|---|---|
| `zlib.dll` | 2 differing bytes, both timestamps, 0 unresolved -- **path-immune** |
| `deflate.c.obj` | size -36, 154 regions, **30,341 differing bytes**, 153 unresolved |

Then rebuilt at a *wrong but equal-length* path
(`C:\a\1\padpad...pad\zlib`, 49 chars):

| Comparison | Regions | Differing bytes |
|---|---|---|
| local(49) vs CI(15) | 154 | 30,341 |
| local(49) vs equal-length(49) | 3 | **51** |

Survivors in the equal-length case:

```
0x00001558 +41  .debug$S   a: Data\repo-monitoring-workspace\stage3\src
                           b: a\1\padpadpadpadpadpadpadpadpadpadpadpadp
0x00006115 +8   .chks64    a: 77639e153e3dbea1   b: 3672ed8dcfa37192
```

Matching path *length* collapsed the diff by a factor of 600, and what
remained was the path text -- legible English on both sides -- plus a derived
checksum. This is the case model adjudication handles well and a human with a
hex editor does not.

## Reproducing

```
tools/build_zlib_fid.bat      # native arm
tools/build_zlib_cov.bat      # Coverity arm (same inner script)
tools/build_zlib_ci.bat       # stand-in official build at a CI-shaped path
python tools/threeway.py SNAP_A SNAP_B SNAP_C --json out.json
python tools/paths.py ARTIFACT
python tools/bindiff.py A B
```

## Carried forward

- Shipping-image comparisons on this toolchain may need no path work at all;
  object comparisons always do.
- The zero-unresolved baseline is what makes the model's job small. Establish
  it on any new toolchain before running production comparisons.
- Both arms were necessary. `K` empty alone would also be the signature of a
  capture that emitted nothing.
