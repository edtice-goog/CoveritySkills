# Anatomy of an intermediate directory

What is in an `idir`, and what each thing is evidence *of*. Layout observed
on Coverity 2026.6.0 (win64); paths are stable across recent releases but
confirm against the installation in hand.

```
idir/
  BUILD.metrics.xml        capture run metadata + counts
  build-log.txt            the full capture log, including native command lines
  build-cwd.txt            the directory cov-build ran in
  build-timings.txt        per-step timing
  tu-timings.txt           per-translation-unit timing
  security-da-log.txt      dynamic analyzer log
  scan-transparency/       process-tree observations (Method B)
    unconfigured-compilers
  emit/<HOST>/             the emit database itself
    config/<md5>/          the compiler configs actually used, per argument set
    emit-db
  output/                  written by cov-analyze, not by cov-build
  telemetry/
  tmp/
```

## The capture side

### `BUILD.metrics.xml`

Machine-readable summary of the capture run. The fields worth reading:

| Field | Evidence of |
|---|---|
| `successes`, `failures`, `recoverable-errors` | capture outcome counts |
| `buildcmd` | **the build command actually wrapped** |
| `args` | the full `cov-build` command line, including `--config` |
| `cwd`, `intermediatedir`, `emitdir` | where this happened |
| `ident` | the exact Coverity build that produced it |
| `time` | wall time; a suspiciously fast capture is a hint of a no-op build |

`buildcmd` and `cwd` together settle more arguments than anything else in the
directory. When someone says "the scan covered the whole product", this is
the field that says what was actually run.

### `build-log.txt`

Verbose, and the single richest artifact for diagnosing a capture. It
contains:

- the **native** compiler command lines the build issued
- the `cov-emit` command line Coverity derived from each, including every
  `--sys_include`, `-D`, and language-standard flag
- `Emit for file '...' (TU N) complete.` per translation unit
- the closing headline block

Two headline lines, and they are different numbers:

```
Emitted 1 C/C++ compilation units (100%) successfully
1 C/C++ compilation units (100%) are ready for analysis
```

`cov-build` also reports near the end whether it detected unconfigured
compilers; that text and `scan-transparency/unconfigured-compilers` are the
same finding in two places.

**Security note.** Command lines are logged. Environment variables are not,
unless `COVERITY_LOG_ENVIRONMENT_VARIABLES=1` or `--debug-flags envvars` --
but a Makefile that runs `sh -c "TOKEN=... cmd"` puts the secret on a command
line, and it lands here. Environment variables *are* recorded in the emit
database; `COVERITY_FILTER_ENVVARS_DENYLIST` excludes named ones. Before
sending an idir or a build log to anyone, including support, check it.

### `emit/<HOST>/config/<md5>/`

The compiler configurations that were actually used, one subdirectory per
distinct argument set the build presented. This is where compiler
configuration becomes checkable after the fact:

- `template-<name>-config-N` subdirectories mean a template configuration was
  used and probing happened per argument set -- correct.
- Bare `<name>-config-N` means a configure-time probe -- suspect, and the
  data captured under it is tainted.

Multiplying `template-*-config-N` directories during a build is the mechanism
working, not a fault. See `coverity-compiler-configuration`.

### `build-cwd.txt`

The directory the capture ran in. Cheap, decisive freshness and provenance
evidence when an idir is reused or moved.

## The CLI capture side

Present only when capture went through the `coverity` CLI (`coverity capture`
or `coverity scan`). A `cov-build` idir has none of it, and its absence tells
you which path produced the directory.

```
idir/
  capture-files-log.txt        buildless-capture log
  coverity-cli/
    build-compiler-configs/       template configs for the build capture
    buildless-compiler-configs/   configs for the buildless pass
    capture-file-list-<n>          what buildless capture was asked to emit
    timestamps.json                uncaptured files, with timestamps
    strip-path, capture-platform   the project root recorded for path stripping
    config-hash                    effective-configuration hash
    coverity-cli-log.txt
    analyze-mode                   written by `coverity analyze`
  output/cli-diagnostics.json  see below
```

`coverity-cli/build-compiler-configs/` is worth knowing about: the CLI
generates its *own* template configuration set covering many languages
(`template-gcc-config-N`, `template-msvc-config-0`, `template-javac-config-0`,
…), so on the CLI path you do not supply `--config` and there is no separate
`cfg/` directory to inspect. The template-vs-probed check from
`coverity-compiler-configuration` applies here instead.

`timestamps.json` records files the CLI knew about and did not capture; it is
`[]` on a complete capture and names the uncaptured sources otherwise.

### `output/cli-diagnostics.json`

The richest single provenance record in any intermediate directory, and CLI
only. Two top-level sections, written at different times:

- `capture` — `primary-capture-mode` (`Build` vs buildless), `capture-rate`,
  `capture-summary`, the effective `build-command`, `project-directory`,
  `intermediate-directory`, `configuration-hash`, and `command-info`.
- `analysis` — appended by `coverity analyze`: its command line, working
  directory, effective configuration, and its own `command-info`.

For C/C++, read `primary-capture-mode` first. Buildless capture does not
handle compiled languages, so a mode other than `Build` on a C/C++ project
means the compiled sources were never captured, whatever the counts say.

**Security.** `command-info` embeds full environment blocks including `PATH`,
in plain JSON. Same handling caution as `build-log.txt`.

## The analysis side

`output/` appears only after `cov-analyze` and describes analysis, not
capture. Do not read capture conclusions from it.

| File | Evidence of |
|---|---|
| `summary.txt` | **the cov-analyze command line**, files analyzed, total LoC, functions analyzed, paths analyzed, defect counts by checker |
| `analysis-settings.json` | resolved settings for the run |
| `enabled-checkers.json` | which checkers actually ran -- settles "was that checker even on?" |
| `analysis-warnings.json` | analysis-time warnings; empty array when clean |
| `annotation-info.json` | annotation usage, including unused annotations |
| `ANALYSIS.metrics.xml` | run metrics |
| `<CHECKER>.errors.xml` | per-checker findings |
| `callgraph-metrics.json.gz` | one record per function in the callgraph: `identifier`, `mangledName`, `file`, `line`, `hasImplementation`, `models`, `importance`. See below -- richer with `--enable-callgraph-metrics` |
| `models/`, `exported-summaries/` | function summaries and models |

`summary.txt` is the fastest way to see the third denominator:

```
Files analyzed                 : 1 Total
Total LoC input to cov-analyze : 5370
Functions analyzed             : 1
```

Note that LoC input counts headers, so it is not comparable to the
`LINES OF CODE` figure from `coverity list`.

## Incremental analysis, and the one message that explains a slow run

`cov-analyze` is incremental by default: an idir that already carries analysis
state re-analyzes only what changed. `--force` disables that.

The cache is **not** keyed on the product version alone. It is invalidated when
the analysis binary itself differs, and `cov-analyze` says so:

```
[STATUS] Incremental analysis could not be used because
analysis binary changed.  This may take a while.
```

**Measured, 2026-08-25.** An idir analyzed by `cov-analysis-win64-2025.9.0` and
then re-analyzed by `cov-analysis-linux64-2025.9.0` -- *identical product
version* -- printed exactly that and performed a full analysis.

This is conservative on purpose: reusing state a different binary may have
computed differently would risk wrong results, so the cache is discarded
instead. Treat it as correct behaviour, not a defect. The cost is **time, not
accuracy** -- the analysis that follows is complete and correct.

You can tell which binary last analyzed an idir without running anything: line
1 of `output/summary.txt` is the full `cov-analyze` command line, install path
included.

```bash
head -1 <idir>/output/summary.txt
```

Compare that path's platform against the install you are about to use; that
predicts whether incrementality survives.

### What "same platform" means here

The test is the OS that **runs the build and the analysis** -- not the OS of the
developer's laptop. This distinction decides whether idir reuse is applicable
at all:

- CI analyzes on Linux, developer analyzes on Linux (bare metal, WSL, or a
  Linux container) -- **same platform, incrementality survives.**
- CI analyzes on Linux, developer works in VS Code with **remote development
  into a Linux container** -- the guest OS matches CI, so this is a **valid
  case** even though the workstation is Windows or macOS. This is the common
  modern arrangement, adopted precisely so local builds do not diverge from CI.
- CI analyzes on Linux, developer analyzes natively on Windows -- **different
  platform; idir reuse for speed is not applicable.** Capture still ports
  (idirs are platform-independent), but every analysis pays full price.

If the platforms differ, do not design around it -- say so and stop. This is an
enumerated limitation, not a problem to engineer past.

## Reading order for a cold intermediate directory

Someone hands you an idir and a claim. In order:

0. Does `coverity-cli/` exist? That tells you whether this came from the CLI
   or from `cov-build`, and therefore which evidence is available at all.
   If it does, `output/cli-diagnostics.json` answers most of steps 1-2 at once.
1. `BUILD.metrics.xml` -- what command was wrapped, where, with which
   Coverity, how many successes and failures.
2. `build-cwd.txt` and file timestamps -- is this idir from the run being
   discussed, or a survivor of an earlier one?
3. `scan-transparency/unconfigured-compilers` -- does the directory even
   exist, and is it empty? If non-empty, **check whether each named path
   exists on disk**: a clean CLI capture has been observed listing a
   non-existent `<project-dir>\gcc`.
4. `cov-manage-emit --dir <idir> list-capture-diagnostics` -- per-file
   capture percentage and AST presence.
5. `emit/<HOST>/config/` -- template configurations or probed ones?
6. `output/summary.txt`, if analysis ran -- what the analyzer actually
   consumed, and under which command line.

Steps 1-4 are the capture-fidelity check in its compressed form. When the
answer matters, run the full three-method procedure in
`capture-fidelity.md` instead of trusting this shortcut.

## Things that are not in the idir

Worth stating, because their absence is regularly misread as a Coverity
failure:

- Source files the build never compiled leave no trace here at all. Their
  absence looks identical to their never having existed.
- Prebuilt third-party libraries are linked, not compiled, so they produce
  link-unit inputs with no translation unit behind them.
- A compiler cache that served a hit means no compiler ran, so nothing was
  intercepted, so nothing is here.
