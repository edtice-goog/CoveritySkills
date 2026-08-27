---
name: coverity-compiler-configuration
description: >
  Configure compilers for Coverity build capture correctly, using template
  configurations so compiler probes happen per-invocation during the build
  rather than once at configure time. Use this skill whenever running
  cov-configure, setting up a new Coverity capture, adding a compiler
  (especially a cross-compiler, embedded toolchain, or compiler wrapper),
  diagnosing "unconfigured compiler" or missing-translation-unit problems,
  reviewing an existing Coverity configuration for correctness, or when
  capture results look wrong and the configuration is suspect. Also use when
  asked what cov-configure --template does or why a Coverity config should be
  regenerated.
---

# Coverity Compiler Configuration

**Always configure with `--template`.** A template configuration maps a
compiler *executable name* to a compiler *type* and nothing more. The actual
compiler probe is deferred to build time and repeated for each distinct set of
arguments the build uses.

Without `--template`, `cov-configure` probes the compiler once, at configure
time, with whatever arguments and environment happen to exist at that moment.
Compiler behaviour changes with the arguments passed -- target, architecture,
language standard, sysroot, `-D` macros, `-m32/-m64` -- so a single
configure-time probe describes one invocation and is then applied to all of
them. **Data captured under such a configuration is tainted.**

This is the single most common Coverity setup mistake.

## The rule

```bash
cov-configure --config <cfg>/coverity_config.xml --template \
  --compiler <executable-name> --comptype <type>
```

`--compiler` takes a **bare executable name, not a path**. `--template`
rejects a full path:

```
COMMAND LINE ERROR: When using the template compiler, only specify an
executable name for the compiler, not a full path.
```

Do not combine `--template` with `--version`.

The compiler **need not exist** when you configure. This matters: it means
configuration never has to wait for a toolchain that the build itself
downloads or bootstraps. Configuring against a compiler that is not installed
succeeds and writes a valid config.

## Why deferred probing is the correct behaviour

From the `cov-configure` documentation for `--template`:

> Provides a template configuration for building with a related set of
> compilers. The necessary compiler configurations are generated with the
> required arguments as needed during the build process. For example, if a g++
> command that specified `-m64` was encountered, a g++ configuration would be
> generated specifying the `-m64` argument.

That is the whole point. One compiler binary invoked three ways is three
different compilers as far as preprocessing and semantics are concerned.
Template configuration produces a configuration per argument set, discovered
from the build itself. A configure-time probe cannot do this, because at
configure time the build has not run and the argument sets are unknown.

## You do not always need `--template`

The **language shortcut options already produce template configurations**:
`--gcc`, `--msvc`, `--java`, and friends. Verified:

```bash
cov-configure --config cfg/coverity_config.xml --gcc
# -> template-gcc-config-0, template-g++-config-{0,1,2}, template-ar-config-0, ...
# -> matches: *-g++ *-gcc ar g++ g++-* gcc gcc-* ld
```

So `--gcc` and `--msvc` are safe from the *probing* problem. **The danger zone
for probing is the explicit `--compiler X --comptype Y` form** -- exactly what
you reach for with cross-compilers, embedded toolchains, and wrapper scripts,
i.e. the cases where hand-rolling is most likely.

**But "template-based" is not the same as "sufficient".** A shortcut can be
correctly template-based and still miss the compiler your build actually
invokes -- see the next section, which is the more common failure in practice.

## `--gcc` does not cover `cc`, and that silently captures nothing

`--gcc` matches exactly:

```
*-g++  *-gcc  ar  g++  g++-*  gcc  gcc-*  ld
```

CMake's default C compiler on Linux is **`/usr/bin/cc`**, which appears in that
list nowhere. On a Debian-family host the alternatives chain then resolves to
**`x86_64-linux-gnu-gcc-13`**, which also matches nothing: the patterns are
`*-gcc` and `gcc-*`, and that name ends in `-13` without starting with `gcc`.

Measured on zlib 1.3.1 with gcc 13.3.0, CMake + Ninja, configured with `--gcc`
alone:

```
[WARNING] ... no files were actually compiled by your build command
BUILD.metrics.xml:  failures 0   successes 0
scan-transparency/unconfigured-compilers:
    /usr/bin/x86_64-linux-gnu-gcc-13
    /usr/libexec/gcc/x86_64-linux-gnu/13/cc1
```

**Zero translation units captured** -- from an ordinary CMake project on an
ordinary Linux host. This is worse than a loud failure, because the build
succeeds and its binaries are byte-identical to a native build. A fidelity
check alone reports a perfect pass.

The fix is to add the names the build really invokes:

```bash
cov-configure --config "$CFG" --gcc
cov-configure --config "$CFG" --template --compiler cc  --comptype gcc
cov-configure --config "$CFG" --template --compiler c++ --comptype g++
# plus the triplet-versioned names the alternatives chain resolves to
cov-configure --config "$CFG" --template --compiler x86_64-linux-gnu-gcc-13 --comptype gcc
cov-configure --config "$CFG" --template --compiler x86_64-linux-gnu-g++-13 --comptype g++
```

```
Emitted 42 C/C++ compilation units (100%) successfully
unconfigured-compilers: (empty)
```

**Do not guess the names -- read them.** `CMAKE_C_COMPILER` in
`CMakeCache.txt`, `CC`/`CXX` in the environment, `readlink -f $(command -v cc)`
to follow the alternatives chain, and after any capture,
`scan-transparency/unconfigured-compilers`.

## How to tell whether an existing config is tainted

Inspect the configuration directory. The signature is unambiguous:

| | Probed (tainted) | Template (correct) |
|---|---|---|
| Config subdirectories | `gcc-config-0`, `g++-config-0`, `ld-config-0` | `template-gcc-config-0`, `template-g++-config-1`, ... |
| String `template` in `coverity_config.xml` | absent | present in every `<include>` |
| Compilers matched | concrete and version-pinned: `gcc-13`, `x86_64-linux-gnu-gcc-13` | globs: `gcc`, `gcc-*`, `*-gcc`, `g++-*` |

Quick check:

```bash
grep -c template <cfg>/coverity_config.xml     # 0 means probed
ls <cfg> | grep -c '^template-'                # 0 means probed
```

Version-pinned compiler names are the tell. A probed config records the
compiler that was on `PATH` at configure time -- if the build uses a different
one, or the same one with different flags, the configuration is describing a
compiler the build never invoked.

## Remediation: regenerate, never patch

If a configuration was created without `--template` (outside the language
shortcuts), **create a fresh configuration directory and re-capture.** Do not
edit the existing config and do not reuse the directory:

- Probed per-compiler configs remain on disk and continue to be included.
- Emitted data captured under the bad configuration is already affected;
  reconfiguring does not retroactively correct an existing intermediate
  directory.

```bash
rm -rf cfg-old-tainted            # or simply use a new path
cov-configure --config cfg-new/coverity_config.xml --template \
  --compiler <name> --comptype <type>
cov-build --dir idir-new --config cfg-new/coverity_config.xml <build command>
```

Use a fresh intermediate directory too. Mixing translation units captured
under different configurations makes the analysis input unreproducible.

## Choosing `--comptype`

List them:

```bash
cov-configure --list-compiler-types
```

Common C/C++ values:

| comptype | For |
|---|---|
| `gcc` / `g++` | GCC C / C++ |
| `clangcc` / `clangcxx` | Clang C / C++ (autodetect family) |
| `clangclcc` / `clangclcxx` | clang-cl (MSVC-compatible driver) |
| `msvc` | Microsoft C/C++ |
| `armcc` / `armcpp` | ARM Clang |

Configure **every** compiler-shaped executable the build invokes, including
the C++ driver, the archiver, and the linker where relevant. Cross toolchains
use prefixed names -- configure the prefixed name, not the host one:

```bash
for cc in x86_64-w64-mingw32-clang aarch64-w64-mingw32-clang; do
  cov-configure --config cfg/coverity_config.xml --template \
    --compiler "$cc" --comptype clangcc
done
for cxx in x86_64-w64-mingw32-clang++ aarch64-w64-mingw32-clang++; do
  cov-configure --config cfg/coverity_config.xml --template \
    --compiler "$cxx" --comptype clangcxx
done
```

Repeated `cov-configure` calls against the same `--config` accumulate; each
adds an `<include>`.

## Wrappers: configure the prefix, never disable the wrapper

`ccache`, `distcc`, `sccache`, `icecc`, and bespoke launcher scripts are what
the build actually invokes — and build systems add them without being asked.
CMake wires ccache in as a compiler launcher whenever a project asks for it
and the binary is on `PATH`; pytorch does this out of the box, so a stock
`cmake && ninja` build of it routes every compile through the wrapper.
Coverity has a comptype for exactly this case:

```bash
cov-configure --config <cfg>/coverity_config.xml --template \
  --compiler ccache --comptype prefix
```

`prefix` tells cov-translate that a `ccache ...` invocation *wraps* a
compiler command line: the wrapper is stripped and the wrapped invocation is
matched against the compiler configurations as usual. The prefix entry is in
addition to the wrapped compilers' own entries, not a replacement for them.
It generates `template-prefix-config-N/` — named for the *comptype*, not the
compiler — and a capture that saw through the wrapper records
`prefix-config-0` under `emit/<host>/config/<md5>/`.

Confirm the comptype name against your installation (the umbrella skill's
rule 4): `cov-configure --list-compiler-types` lists

```
prefix,<no-def-name>,C,FAMILY HEAD,Prefix to a compiler (e.g. ccache)
```

(confirmed on 2025.9.0, linux64-2025.12.2, and win64-2026.6.0).

**Do not "solve" a wrapper by disabling it** — `CCACHE_DISABLE=1`, `CCACHE=`
on the make line, or stripping the launcher from the build files. The
umbrella skill's rule 32 owns the full argument; the short form: it changes
the build under capture (removing a cache the team added deliberately — the
exact perturbation `coverity-build-fidelity` exists to detect, imposed by
hand), it turns routine capture intolerably slow on exactly the trees big
enough to need a cache, and the "fix" does not transfer — CI and every
colleague's machine still have the wrapper, while the next reader inherits
cache-disabling as if it were a Coverity requirement.

Nor is a warm cache a problem once the prefix is configured — capture drives
`cov-emit` from the intercepted *invocation*, not from watching the real
compiler run. Measured (rule 32's calibration entry, 2026.6.0): with the
prefix configured and every compile a cache hit — the compiler never
executed — capture was complete (2 of 2, adjudicated `CONSISTENT`). The same
project with the wrapper *unconfigured* captured 0 of 2 fully warm, and,
worse, 1 of 2 partially warm while reporting `Emitted 1 (100%) successfully`
with no warning: only the cache miss was captured, because a miss execs the
real compiler as a child that `cov-build` intercepts, and a hit execs
nothing. A cold cache therefore makes an unconfigured wrapper *look* fine —
corroborated at scale on a pytorch capture, where a cold-cache build with
unconfigured ccache captured every TU — while the first warm rebuild
silently drops to rule 9's partial-build shape, with the cache as the
"nothing to do" agent.

## Verify after the build, not before

Configuration correctness shows up in the capture, so check there:

- `cov-build` reports **"Attempting to detect unconfigured compilers in
  build"** near the end, and writes the same finding to
  `<idir>/scan-transparency/unconfigured-compilers`. Anything named there was
  invoked but not configured, and its translation units are missing from the
  emit. An **empty** file is a real result for ordinary compilers — but it
  does **not** clear wrappers: measured (rule 32's calibration entry), an
  unconfigured ccache driving every compile was never named there, including
  in a run that captured nothing — though on another setup the same file
  *did* name the wrapper, so a named wrapper is a real signal even if its
  absence proves nothing (rule 32). So never let this file alone close the
  question: it is one of the three independent signals in the umbrella
  skill's capture-fidelity check — alongside the emit inventory and an
  independently-formed expectation — and an unhandled wrapper surfaces as
  their *disagreement* (this file clean, the other two short), resolved by
  the adjudication rather than by any single signal. A **missing**
  `scan-transparency/` directory means the check did not run, which is not
  the same as passing.
- Compare emitted translation units against what the build actually compiled.
  Do not trust the headline percentage: the denominator includes the build
  system's own throwaway compilations (CMake `TryCompile`, `CompilerId`,
  configure tests), so a figure below 100% is often benign -- and 100% of
  nothing is still 100%. Reconcile against *product* sources.

  The full procedure is the `coverity` skill's capture-fidelity check, which
  runs the emit inventory, the scan-transparency readout, and an independent
  expectation as three separate methods and then adjudicates. Its
  disagreement table is what distinguishes a configuration fault from the
  more common "the build never compiled those files at all".
- Under a correct template config, `template-<name>-config-N` directories
  multiply during the build as new argument sets are encountered. That growth
  is the mechanism working, not a problem.

See `coverity-build-fidelity` for the full reconciliation procedure and for
proving that wrapping the build in `cov-build` did not change its output.

## Common mistakes

1. **Omitting `--template`** with explicit `--compiler`/`--comptype`. The
   headline error.
2. **Passing a path to `--compiler` under `--template`.** Bare name only.
3. **Configuring only the C compiler.** C++ driver, archiver, and linker also
   need entries.
4. **Configuring the host compiler for a cross build.** Configure
   `arm-none-eabi-gcc`, not `gcc`.
5. **Reusing a config directory after fixing the flags.** Stale probed configs
   persist; start fresh.
6. **Assuming a wrapper is transparent — or disabling it instead of
   configuring it.** `ccache`, `distcc`, `sccache` and bespoke wrapper
   scripts are what the build actually invokes; configure them with
   `--comptype prefix` (see "Wrappers" above; the umbrella skill's rule 32
   has the measured behaviour). Disabling the cache changes the build under
   capture, forces full recompiles, and an unconfigured wrapper only appears
   to work while the cache is cold.
7. **Treating `< 100%` capture as failure.** Reconcile against product
   translation units first.
