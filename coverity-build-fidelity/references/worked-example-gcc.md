# Worked example: gcc / ELF, and a live false pass

zlib 1.3.1, gcc 13.3.0, CMake + Ninja, Release, on Linux. Small and fast, run
to establish how the method behaves on ELF rather than PE.

Two results matter. ELF/gcc turns out to be the *easy* case. And the run
produced a genuine **false pass** -- byte-identical binaries from a capture
that emitted nothing -- which is the failure mode this skill exists to catch,
caught in practice rather than in theory.

## ELF/gcc builds are bit-reproducible with no effort

Two native builds, same directory, nothing special configured:

```
identical: 21   differing: 0
```

All 21 artifacts -- shared library, static archive, two executables, and every
`.o` -- byte-for-byte equal. **`D(N,N') = empty`.**

This is qualitatively different from PE. A PE image carries a COFF
`TimeDateStamp` that changes on every link, so a Windows noise floor is never
empty without `/Brepro`. ELF has no mandatory timestamp field, and
`.note.gnu.build-id` is a *content hash* rather than a clock reading, so it is
stable whenever the content is.

**Consequence: on gcc/ELF the shape algebra is usually unnecessary.** With an
empty noise floor, `cmp` is a sufficient comparison and any difference is
immediately meaningful. Reach for region diffing only if a plain compare
disagrees.

## The false pass

First Coverity attempt, configured with the `--gcc` language shortcut:

```
K = D(native, coverity):  identical: 21   differing: 0
```

A perfect fidelity result. And completely worthless:

```
[WARNING] ... no files were actually compiled by your build command
BUILD.metrics.xml:  failures 0   successes 0
```

Nothing was captured. The fidelity arm cannot distinguish this from success,
because **a capture that emits nothing perturbs nothing.** Only the capture arm
sees it.

### Root cause: CMake compiles with `cc`

```
CMAKE_C_COMPILER:FILEPATH=/usr/bin/cc
--gcc matches: *-g++ *-gcc ar g++ g++-* gcc gcc-* ld
scan-transparency/unconfigured-compilers:
    /usr/bin/x86_64-linux-gnu-gcc-13
    /usr/libexec/gcc/x86_64-linux-gnu/13/cc1
```

`cc` is not in the match list. Neither is `x86_64-linux-gnu-gcc-13`, which is
where Debian's alternatives chain lands: the patterns are `*-gcc` and `gcc-*`,
and that name ends in `-13` while not starting with `gcc`.

So the single most common Linux configuration -- a CMake project on a
Debian-family host -- is **not** covered by `cov-configure --gcc` alone. See
`coverity-compiler-configuration`.

### After adding the missing names

```bash
cov-configure --config "$CFG" --gcc
cov-configure --config "$CFG" --template --compiler cc                    --comptype gcc
cov-configure --config "$CFG" --template --compiler x86_64-linux-gnu-gcc-13 --comptype gcc
cov-configure --config "$CFG" --template --compiler c++                   --comptype g++
cov-configure --config "$CFG" --template --compiler x86_64-linux-gnu-g++-13 --comptype g++
```

```
Emitted 42 C/C++ compilation units (100%) successfully
unconfigured-compilers: (empty)
K = D(native, coverity):  identical: 21   differing: 0
```

12 template config directories, 0 probed. **Capture 100%, `K` empty, and this
time the empty `K` means something.**

## What to take from this

- On gcc/ELF, expect a bit-reproducible baseline. If two native builds are not
  identical, that is itself worth reporting before going further.
- `cmp` is the right first tool. Do not reach for region diffing until a plain
  compare fails.
- **Never report fidelity without capture.** The same 21/21 result appeared
  both when capture worked and when it captured nothing at all. The arms are
  not redundant; one of them is load-bearing exactly when the other looks best.
- `scan-transparency/unconfigured-compilers` is the fastest diagnosis for a
  zero-emit capture. An empty file is a pass; an absent file means the check
  did not run.

## Tooling note

Nothing PE-specific was needed here, and nothing new was written. `cmp`,
`readelf`, and `objdump` are present on any Linux build host and are the right
instruments for ELF. The `tools/` in this skill exist because PE's ephemeral
fields are awkward to reach without a parser; ELF does not have that problem.
