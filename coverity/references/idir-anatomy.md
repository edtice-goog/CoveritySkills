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

### `callgraph-metrics` -- and why the `file` field is not attribution

Without flags, `cov-analyze` writes `output/callgraph-metrics.json.gz`: one
record per function in the callgraph, with `identifier`, `mangledName`, `file`,
`line`, `hasImplementation`, `models`, `importance`.

**Do not read `file` as "where the model came from."** It is the location of the
source *text*. Measured on an FFmpeg idir (27,008 implemented functions), 205 of
2,252 distinct `file` values were **headers** -- `static inline` definitions in
`get_bits.h`, `bswap.h` and friends. The same identifier also appears many
times: `get_bits1` had **five** records with identical file, line and mangled
name, differing only in `importance`.

Passing **`--enable-callgraph-metrics`** to `cov-analyze` explains that. It adds
no fields to the JSON, but writes two more files:

| File | Contents |
|---|---|
| `callgraph-metrics.csv` | `call_count, name, unmangled_name, **TU**, qualifiers, cycle_id`, then repeating `module, model_type, model_file` triples per analysis module |
| `callgraph-metrics.txt` | the same, human-readable: `... : implemented in TU 931, generic=no model, security=...` |

The `TU` column is the real key. Measured on that same idir:

```
distinct implementing TUs      : 1989
TUs in emit                    : 2060
implementing TUs found in emit : 1989 / 1989   (100%)
primaryFilename extensions     : .c 1989       (zero headers)
```

**Every implementing TU resolves to an emit TU, and every one is a primary
source file.** `av_bswap32`, whose JSON `file` is `libavutil/bswap.h`, is
recorded in the CSV as *implemented in TU 931*.

This is why the emit database exists rather than a filesystem mirror: a header
can compile to different functions, or differently-behaving ones, depending on
which TU includes it (conditional compilation). Models must therefore be keyed
to the **primary source file**, not to the text's location. `TU = -1` marks
functions with no implementation in this emit -- built-ins and library
functions served by `builtin-models.db`.

**Practical rule:** to ask "does the code behind this model still exist?", use
`--enable-callgraph-metrics` and resolve the CSV's `TU` column through
`cov-manage-emit list-json`. Testing the JSON `file` path answers a different
and weaker question, and gives a wrong answer for any header-defined function.

### The emit is stamped with the capturing host, and that blocks import

`emit/<HOST>/` is not decoration. `<HOST>` is the machine that ran the capture,
and a **different** machine will refuse to read the idir until it is reset:

```
Please run
    cov-manage-emit --dir <intermediate-directory> reset-host-name
```

Measured 2026-08-27 on a Linux-kernel idir captured on `sig-os003039191` and
opened on `BD-46312`:

| | before | after |
|---|---|---|
| `emit/<HOST>/` | `sig-os003039191` | `BD-46312` |
| `cov-manage-emit list-json` TUs | **0** | **3779** |
| `cov-analyze` | **rc 2** | runs |

The fix is one command and takes seconds:

```bash
cov-manage-emit --dir <idir> reset-host-name
```

**Two traps worth knowing.**

*It fails quietly in the wrong place.* `list-json` returned **zero TUs** rather
than an error, so a script that counts TUs sees an empty idir and reports it as
such. The clear diagnostic appears only when `cov-analyze` runs. If an imported
idir looks empty, suspect the host stamp before suspecting the capture.

*It is not the same as the analysis-binary check.* That one invalidates the
incremental **cache** and still produces correct results; this one **blocks
reading the emit at all**. An idir moved between machines may need both
addressed: `reset-host-name` to open it, and a full analysis because the cache
does not travel.

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
