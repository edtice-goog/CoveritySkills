# Worked example: the build that compiled nothing (and the one that compiled 20%)

Calibration run for rule 9, *make sure the build under capture actually
builds*. It reproduces the two failure modes deliberately, measures what
Coverity says about each, and adjudicates all of them against one frozen
expectation.

**Headline result: the fully vacuous build is the *safe* one.** `cov-build`
2026.6.0 warns loudly when it emits zero translation units. The build that
compiles *some* of the project is the dangerous one — it prints `100%` three
different ways and `The cov-build utility completed successfully.`

## Environment

- Coverity 2026.6.0 (win64), `C:\Coverity\cov-analysis-win64-2026.6.0`
- gcc 13.2.0 (MinGW-W64 x86_64-ucrt-posix-seh), GNU make as `gmake`
- Windows 11, scratch project outside any repository

## The project

Five C sources, each compiled to an object and linked into one executable by
an ordinary Makefile (`OBJS = src/a.o src/b.o src/c.o src/d.o src/main.o`).
Nothing exotic: the point is that the *build system*, not Coverity, decides
what gets compiled.

Configuration per rule 1, and checked per rule 1:

```bash
cov-configure --config cfg/coverity_config.xml --gcc
grep -c template cfg/coverity_config.xml     # 8
ls cfg | grep -c '^template-'                # 8
```

## Method C, frozen first

Produced from the Makefile alone, **before any intermediate directory
existed**, reviewed by hand, `reviewed: true`, then copied to
`method-c.frozen.json`:

```
5 candidate source files; 5 auto-bucketed as product
reviewed: True | expected: 5
```

Reason recorded on every row: *named in Makefile OBJS; compiled into app.exe
by the default target*. The same frozen expectation adjudicates all three
runs — that is what makes them comparable.

## The runs

Each run captured into a **fresh** intermediate directory (rule 8), against
the same config, from the same source tree.

| Run | Tree state before | Build command | TUs emitted |
|---|---|---|---|
| A | fully built | `gmake` (nothing to do) | 0 |
| B | `touch src/b.c` only | `gmake` | 1 |
| C | `gmake clean` | `gmake` | 5 |

### A — the no-op build

```
gmake: Nothing to be done for 'all'.
Attempting to detect unconfigured compilers in build
[WARNING] No files were emitted. This may be due to a problem with your configuration
or because no files were actually compiled by your build command.
Please make sure you have configured the compilers actually used in the compilation.
```

Exit status **0**. No `Emitted N …` line, no percentage. `BUILD.metrics.xml`:
`successes = 0`, `failures = 0`, `recoverable-errors = 0` — the flattering
signature, zero failures, because nothing was attempted.

`coverity list --all` on that idir:

```
Capture summary:
    SUCCEEDED: 0
    INCOMPLETE: 0
    FAILED: 0
    IGNORED: 12
    FILES CAPTURED: 0
    LINES OF CODE: 0
```

Note what the summary does *not* do: it never names the five uncompiled
sources. They are inside `IGNORED: 12`, alongside object files and the
executable, and `coverity list` has no option to enumerate the ignored set.
The count is the only signal.

`cov-manage-emit list` prints nothing at all.

### B — the partial build

One source touched, so `make` recompiles exactly one object and relinks:

```
gcc -c -o src/b.o src/b.c
gcc -o app.exe src/a.o src/b.o src/c.o src/d.o src/main.o
Attempting to detect unconfigured compilers in build
Emitted 1 C/C++ compilation units (100%) successfully

1 C/C++ compilation units (100%) are ready for analysis
The cov-build utility completed successfully.
```

**This is the rule.** Four fifths of the project is missing from the emit and
every headline number reads perfect: `100%` emitted, `100%` ready for
analysis, "completed successfully", `failures = 0`, no warning of any kind.
The percentage's denominator is *what the build attempted*, not what the
project contains — so a build that attempts one file and captures it scores
100%.

```
Capture summary:
    SUCCEEDED: 1
    ...
    FILES CAPTURED: 1
```

`cov-manage-emit list` → exactly one translation unit, `src/b.c`.

### C — the control

Clean tree, full build: `Emitted 5 C/C++ compilation units (100%)
successfully`, five TUs in the emit, `FILES CAPTURED: 5`.

## Adjudication, one frozen expectation against all three

```bash
python3 tools/capture_fidelity.py adjudicate -c method-c.json -a X-method-a.json -b X-method-b.json
```

| Run | Grade | Expected / captured / analyzable | Named |
|---|---|---|---|
| A | `VACUOUS` | 5 / 0 / 0 | all five sources |
| B | `SHORTFALL` | 5 / 1 / 1 | `src/a.c`, `src/c.c`, `src/d.c`, `src/main.c` |
| C | `CONSISTENT` | 5 / 5 / 5 | — |

Both failures were caught, and in both cases the *specific missing files* were
named — which neither `cov-build`'s output nor `coverity list`'s summary does
on its own. This is the first time the `VACUOUS` branch has been exercised
against a real intermediate directory rather than synthesized input.

The adjudication for B is also the right diagnosis, not merely the right
grade:

> 4 expected source(s) not captured with no unconfigured compiler to explain
> it. The build most likely never compiled them: incremental build,
> compiler-cache hits, wrong target, or an early failure the build continued
> past. Clean and re-capture.

## Side finding: a phantom entry in `unconfigured-compilers`

Measured across the runs, plus two extra probes:

| Run | How gcc was invoked | `unconfigured-compilers` |
|---|---|---|
| A | not invoked (no-op build) | empty (0 bytes) |
| B | by `gmake` | `<build-cwd>\gcc` (129 bytes) |
| C | by `gmake` | `<build-cwd>\gcc` |
| D | by `gmake`, compile only, no link | `<build-cwd>\gcc` |
| E | `cov-build … gcc -c …` directly | empty (0 bytes) |

The **fully correct control run (C) has a non-empty
`unconfigured-compilers`.** The entry names `<build-cwd>\gcc`, a path that
does not exist on disk; gcc was configured, was matched by
`template-gcc-config-*`, and emitted all five translation units under that
very configuration. Runs D and E isolate the trigger: it is not the link step
(D has none and still reports it), it is invocation *through make* — where the
child process is spawned as bare `gcc` and the detector resolves the name
against the build's working directory.

So rule 14 needs its converse stated carefully: **empty is a pass, missing is
not a pass, and non-empty is not automatically a fault.** The discriminator is
whether the named path exists:

- **Exists** — a real unconfigured compiler. Measured elsewhere in this
  project: `--gcc` alone on a Debian-family CMake build listed
  `/usr/bin/x86_64-linux-gnu-gcc-13` and `/usr/libexec/gcc/…/cc1`, and zero
  TUs were captured.
- **Does not exist** — a phantom, as here. Corroborate with the emit: if the
  named compiler's translation units are present, it was configured.

`capture_fidelity.py method-b` already makes this distinction
(`UNCONFIGURED_COMPILERS_PHANTOM_ONLY`), which is why run C still graded
`CONSISTENT` rather than being dragged down by its own scan-transparency file.

## Open question: "outside of the project directory" on cov-build idirs

On all three runs, `coverity list --project-dir <proj> --all` reported every
captured file under **Captured files outside of the project directory**, even
though the files are `<proj>\src\*.c` and `--project-dir` was `<proj>`. The
module section (`Files for module: <proj>\Makefile`) was empty in the same
listing.

Confirmed not to be a path-style artifact: native backslash `--project-dir`,
forward-slash `--project-dir`, and defaulting to the current directory all
behave identically. Distinguish this from the genuine case, which is
reproducible by pointing `--project-dir` at a renamed workspace root and which
this project has also measured.

Practical effect: on a `cov-build`-produced intermediate directory, that
section is not currently a reliable "outside the project" signal, and the
adjudicator's caveat about the project-directory denominator fires on healthy
captures. Do not read it as a fault without independent corroboration.
