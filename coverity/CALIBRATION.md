# Calibration status

This project's standard is that factual claims in a skill were established by
real runs. This file records where the `coverity` skill currently stands, so
that nothing unverified reads as measured.

Environment for everything marked verified: **Coverity 2026.6.0 (win64)**,
`C:\Coverity\cov-analysis-win64-2026.6.0`, Windows 11, against intermediate
directories in `coverity-defect-detectability-workspace/` and in scratch
projects built for a specific calibration (gcc 13.2.0, MinGW-W64 /
Strawberry; GNU make invoked as `gmake`).

## Verified by direct execution

- `coverity list` runs against an intermediate directory produced by plain
  `cov-build`, not only by `coverity capture`.
- `coverity list` output structure: the three diagnostic sections (*Files not
  in any module*, *Captured files not found on disk*, *Captured files outside
  of the project directory*) and the `Capture summary` block with
  `SUCCEEDED / INCOMPLETE / FAILED / IGNORED / FILES CAPTURED / LINES OF
  CODE`. Observed on a one-TU capture: `SUCCEEDED: 1`, `IGNORED: 14`.
- *Captured files outside of the project directory* fires when `--project-dir`
  does not match the root recorded in the idir. Reproduced by pointing the
  command at a renamed workspace path.
- `coverity list` internally invokes `cov-manage-emit list-capture-diagnostics`
  and `cov-manage-emit list-capture-invocations --coverity-cli-summary-only`
  (visible in its `[INFO] Executing command:` lines).
- `cov-manage-emit list-capture-diagnostics` exists and returns
  `format_version: 4` with per-file `capture-percentage`,
  `had-failures`, `had-recoverable-errors`, `had-abstract-syntax-trees`,
  `code-line-count`, `last-modified`, `file-size-in-bytes`.
- `cov-manage-emit list-json` returns, beyond the fields named in the
  reference, `isFailure`, `isCreateEDGPCH`, `hadRecoverableErrors`,
  `astFidelityPercent`, `isFromBootClassPathOrSystem`.
- `cov-manage-emit list-capture-invocations --no-process-details` output
  shape, including the `metrics` block and an empty `link-units` array for a
  compile-only (`gcc -c`) capture.
- `scan-transparency/unconfigured-compilers` is created by `cov-build` and is
  empty for a clean, correctly configured gcc capture **when `cov-build`
  invokes the compiler directly**. When the same compiler is invoked by a
  build tool it carries a phantom entry even on a perfect capture -- see the
  phantom entry below.
- Intermediate directory layout and `BUILD.metrics.xml` field set, including
  `buildcmd`, `successes`, `failures`, `recoverable-errors`, `ident`, `cwd`.
- `idir/output/` contents after `cov-analyze`, including `summary.txt`
  (command line, *Files analyzed*, *Total LoC input to cov-analyze*,
  *Functions analyzed*), `enabled-checkers.json`, `analysis-warnings.json`
  (empty array when clean), `annotation-info.json`.
- `build-log.txt` prints two distinct headline lines: `Emitted N C/C++
  compilation units (100%) successfully` and `N C/C++ compilation units
  (100%) are ready for analysis`.
- `tools/capture_fidelity.py` end to end: `expect`, `method-a`, `method-b`,
  `adjudicate`. On a workspace whose idir captured only `src/main.c` while
  the tree held `src/main.c` and `src2/main2.c`, it graded `SHORTFALL` and
  named `src2/main2.c`, matching ground truth (`cov-build ... gcc -c
  src/main.c`). The `NOT_RUN` branch was exercised with synthesized inputs;
  `VACUOUS` has since been exercised against a real idir (next entry).
- **Rule 9 -- the build that compiles nothing, and the build that compiles
  some.** Five-source Makefile project, `--gcc` template config, one fresh
  idir per run, one frozen Method C expectation adjudicating all of them.
  Full write-up in `references/worked-example-vacuous-capture.md`.
  - No-op build (`gmake` over an already-built tree): 0 TUs emitted,
    `[WARNING] No files were emitted...`, **no** `Emitted N` line and no
    percentage, exit 0, `successes = 0 / failures = 0`.
    `coverity list --all` -> `FILES CAPTURED: 0`, `SUCCEEDED: 0`, the five
    uncompiled sources folded silently into `IGNORED: 12`; `cov-manage-emit
    list` prints nothing. Graded `VACUOUS` (5/0/0) and all five named.
  - Partial build (one source touched): 1 of 5 TUs, and the output reads
    `Emitted 1 C/C++ compilation units (100%) successfully`, `1 ... are ready
    for analysis`, `The cov-build utility completed successfully.`, with
    `successes = 1 / failures = 0 / recoverable-errors = 0` and **no warning
    of any kind**. Graded `SHORTFALL` (5/1/1), naming the four missing
    sources, with the correct diagnosis ("the build most likely never
    compiled them").
  - Control (clean tree, full build): 5 of 5, graded `CONSISTENT` (5/5/5).
  - Conclusion: the percentage's denominator is what the build *attempted*.
    The fully vacuous capture is loud; the partial capture is silent, and it
    is the one that reaches a report.
- **The `unconfigured-compilers` phantom is not CLI-specific, and its trigger
  is invocation by a build tool.** Same project, 2026.6.0: gcc invoked by
  `gmake` wrote `<build-cwd>\gcc` on every run that compiled anything --
  including the 5-of-5 control and a compile-only run with no link step --
  while `cov-build ... gcc -c ...` invoking the compiler directly left the
  file empty, as did the no-op build. The named path does not exist on disk.
  Corroborates the CLI-side observation recorded under rule 14 and narrows
  the cause: a bare command name resolved against a directory rather than
  `PATH`, independent of capture path and independent of linking.

- `cov-format-errors` options on 2026.6.0: `--json-output-v10 <file>`,
  `--emacs-style` (documented as equivalent to `--text-output-style
  multiline`), `--html-output <dir>`, plus the filtering options. There is
  **no** `--text-output` option -- it is rejected with `[COMMAND LINE ERROR]
  Undefined option 'text-output'`. Worth recording because a loose grep of
  the help text for `--text-output` matches the *prefix* of
  `--text-output-style` and invents a plausible flag that does not exist.
- **`cov-format-errors --json-output-v10` produces JSON, confirmed by
  execution** -- not merely by `--help`. Run against an idir holding one real
  UNINIT report (`cov-emit --c` of `evals/fixtures/uninit-main.c`, then
  `cov-analyze --all --aggressiveness-level high`; the defect does not appear
  at defaults). It printed `Detected 1 defect occurrence that passes the
  filter criteria` and wrote a 3.9 KB file:
  - top level: `type`, `formatVersion`, `suppressedIssueCount`, `issues`,
    `desktopAnalysisSettings`, `error`, `warnings`
  - per issue: `checkerName`, `subtype`, `subcategory`, `domain`, `language`,
    `mainEventFilePathname`, `strippedMainEventFilePathname`,
    `mainEventLineNumber`, `mainEventColumnNumber`, `mergeKey`,
    `occurrenceCountForMK`, `functionDisplayName`, `checkerProperties`,
    `localTriage`, `stateOnServer`, `events`
  - per event: `eventNumber`, `eventTag`, `eventDescription`,
    `covLStrEventDescription`, `filePathname`, `lineNumber`, `columnNumber`,
    `main`, `eventSet`, `eventTreePosition`, `remediation`,
    `moreInformationId`, nested `events`
  Documented as the recommended JSON option (`v1`-`v9` are backward
  compatibility only), and the full schema is *Desktop Analysis JSON output
  syntax* in the Desktop Analysis User Guide.

- **Rule 34 -- a captured file can be missing functions.** Three-function C
  file, middle function referencing an undefined type, `cov-emit --c` on
  2026.6.0. The TU emitted and `cov-emit` warned `warning #1563: function
  "f2" not emitted, consider modeling it or review parse diagnostics to
  improve fidelity`, followed by `[WARNING] 2 recoverable errors detected`.
  `cov-analyze` then reported `Functions analyzed : 2`.
  - Caught it: `coverity list` -> status `Incomplete`, Notes `Recoverable
    Errors`, `INCOMPLETE: 1`; `cov-manage-emit list` -> TU suffixed
    ` (recoverable errors)`; `had-recoverable-errors` /
    `hadRecoverableErrors` -> `true`.
  - Missed it: `capture-percentage: 100`, `astFidelityPercent: 100`,
    `hasASTs: true`, `isFailure: false`, `FILES CAPTURED: 1` of 1.
  - So the per-TU percentage answers "did this TU parse at all", not "is all
    of it here". Recoverable errors are the function-level signal.
  - Reproduced independently while updating the tool, on a two-file project
    (a three-function file with an undefined type in `f2`, plus a clean
    two-function file). Same outcome, plus two further signals: `cov-build`'s
    closing block prints `Emitted 2 C/C++ compilation units (100%)
    successfully` immediately followed by `[WARNING] Recoverable errors were
    encountered during 1 of these C/C++ compilation units.`, and
    `cov-manage-emit list` suffixes the TU with ` (recoverable errors)`.
    `cov-analyze` reported `Functions analyzed : 4` against five functions
    written. The capture log carried
    `"src/part.c", line 5: warning #1563: function "f2" not emitted` — the
    only place the lost function is named.
  - `tools/capture_fidelity.py` now models this: TUs are classified
    complete / partial / unusable rather than clean / degraded, the report
    carries four counts (expected / captured / analyzable / fully parsed)
    plus `Functions analyzed`, and the `#1563` warnings are extracted from
    the capture logs and listed by name. Verified against this idir
    (`DEGRADED`, 2/2/2/1, naming `f2` at `src/part.c:5`) with the earlier
    `CONSISTENT` and `SHORTFALL` cases re-run as regressions.

## Not found in the shipped documentation (2026.6.0)

Recorded so the gap can be closed, not as a selling point: a command whose
behaviour is not in the reference has no stability contract, which is a cost
to the reader, not a discovery. Searched in each case: the tool's own
`--help`, `doc/en/help/*.help.txt`, and a recursive case-insensitive grep of
the entire `doc/en` tree, HTML and PDF included.

| Item | Used by | Search result |
|---|---|---|
| `cov-manage-emit list-capture-diagnostics` | capture fidelity, Method A2 | Absent from `cov-manage-emit --help`, which lists `list`, `list-capture-invocations`, `list-json`, `list-json-schema-versions`. Zero hits under `doc/en`. `coverity list` calls it internally |
| Its per-TU field names (`capture-percentage`, `had-abstract-syntax-trees`, `had-recoverable-errors`, `code-line-count`) and `list-json`'s `astFidelityPercent` / `isFailure` / `hadRecoverableErrors` | same | Zero hits under `doc/en` |
| `cov-commit-defects --backdate` | `coverity-demo-data` | Absent from `cov-commit-defects --help`; zero hits under `doc/en`, `cov_command_ref.html` included. Appears only in `Platform/bin/schema.sql`, as the `snapshot.backdated` column |

Until these appear in the reference, treat their names and output shapes as
version-specific and re-check them against the installation in use.

`list-capture-diagnostics` remains the default path in the skill -- one call,
per-TU, machine-readable. The substitutes below are the documented fallback
for a version where it is absent or reshaped, which the skill now names
explicitly so a failure there does not become an "unknown".

### Documented substitutes exist for nearly all of it

Checked against 2026.6.0. `cov-manage-emit list-diagnostics` does **not**
exist (`Error: invalid command list-diagnostics`), but `list-json` is fully
documented and covers most of what Method A2 currently takes from
`list-capture-diagnostics`:

| Needed | Undocumented source now used | Documented alternative |
|---|---|---|
| Is this TU analyzable? | `had-abstract-syntax-trees` | **`list-json` -> `hasASTs`**, documented with an example. Also `cov-manage-emit list`, which suffixes such a TU with ` (no ASTs)` -- the literal is present in the 2026.6.0 binary; the marker itself has not been triggered in a live run (queue item 4) and the `list` documentation mentions only ID and filename |
| Did this TU parse completely? | `capture-percentage`, `astFidelityPercent` | `coverity list` capture status **`Incomplete`** -- categorical rather than a percentage, but it is the actionable distinction |
| Did this TU fail? | `had-failures`, `isFailure` | `coverity list` status **`Failed`** and the `FAILED` count |
| Recoverable errors | `had-recoverable-errors` (per TU) | `BUILD.metrics.xml` `recoverable-errors` -- build-level only; no documented per-TU equivalent |
| Size / identity | `file-size-in-bytes`, `last-modified` | `list-json` `primaryFileSizeInBytes`, `primaryFileHash` |
| Lines of code | `code-line-count` | `coverity list` *Code Lines* column and `LINES OF CODE` |

The `list-json` documentation also states plainly: *"The output of this command
may contain additional attributes that are not documented here. For maximum
interoperability, please ignore any attribute that is not documented."* That
is explicit guidance against building on `astFidelityPercent`, `isFailure`,
and `hadRecoverableErrors`, all of which appear in real output.

Only two things have no documented per-TU equivalent: a numeric parse-fidelity
percentage, and recoverable errors per translation unit. Both have documented
categorical or aggregate forms.

## From documentation, not yet executed

- `coverity list --all` default-hides `vendor`, `node_modules`, `__MACOSX`,
  and dot-directories unless captured (from `coverity list --help`; the
  hiding behaviour itself was not reproduced against such a tree).
- Capture status semantics `Succeeded / Incomplete / Failed / Ignored`, and
  the documented causes of `Failed` (command reference).
- `--enable-scan-transparency-data` / `--disable-scan-transparency-data` on
  `cov-build` and `cov-analyze`; enabled by default.
- Coverity Connect's `scan.transparency.enabled=true` in `cim.properties`,
  the restart requirement, and the resulting *Source Files Captured* /
  *Functions Analyzed (with Models)* / *Number of Annotations* / *Number of
  Custom Models* fields plus the per-snapshot JSON download.

## Scan transparency: who writes it, and when

Run deliberately (2026.6.0, two-source C project, gcc 13.2). The question was
whether `cov-analyze` produces `scan-transparency/`, and whether a commit to
Coverity Connect is needed. **Neither. It is written at capture time, and no
commit is involved.**

| Step | `scan-transparency/` after |
|---|---|
| `cov-configure --gcc` + `cov-build` (2 TUs, clean) | directory created; `unconfigured-compilers`, empty |
| `cov-analyze --all` over that idir | **byte-for-byte unchanged** |
| `coverity capture` (build compiled 1 of 2 sources) | `unconfigured-compilers` (empty) + `cli-ignored-files` (522 B) |
| `coverity analyze` over that idir | **byte-for-byte unchanged** |

Corroboration on an older version: `C:\analysis\proftpd\idir1.3.9`, a real
full analysis under 2024.12.1, carries only an empty `unconfigured-compilers`.
That run was both older *and* clean, so on its own it cannot distinguish
"writes nothing" from "had nothing to write" -- which is why the 2026.6.0 run
above was given a deliberate hole.

`cli-ignored-files` on the CLI arm listed `app.exe`, `src/a.o`, `src/main.o`,
and `src/main.c` -- correctly naming the source the build never compiled,
mixed in with object files ignored by design.

### Also established by that run

- **`coverity capture` performs buildless capture after the build command.**
  With a build command that compiled one of two C sources, it still reported
  `SUCCEEDED: 13 / IGNORED: 4 / LINES OF CODE: 266`, having emitted the
  project's other supported files -- including configuration files belonging
  to the `cov-build` intermediate directory nested under the project
  directory. Buildless capture does **not** cover C/C++, so the uncompiled C
  source was genuinely missed while the headline count looked healthy.
- The CLI capture arm creates `idir/coverity-cli/` holding
  `build-compiler-configs/`, `buildless-compiler-configs/`, `timestamps.json`
  (recording uncaptured files), `strip-path`, and `config-hash`.
- The analysis-side transparency artifacts live in `idir/output/`
  (`analysis-warnings.json`, `annotation-info.json`, `enabled-checkers.json`,
  `summary.txt`), not in `scan-transparency/`.

### The clean CLI run, with an explicit build command

Third run, addressing the objection that the earlier CLI arm was confounded by
a deliberately incomplete build. Three-source C project, `Makefile`, idir
placed **outside** the project directory:

```
coverity capture --project-dir <proj> --dir <outside>/idir_cli2 -- gmake
coverity analyze --project-dir <proj> --dir <outside>/idir_cli2
```

Capture succeeded completely: `Emitted 3 C/C++ compilation units (100%)`,
`SUCCEEDED: 3 / IGNORED: 5 / LINES OF CODE: 22`, `capture-rate: 100`,
`primary-capture-mode: Build`, and `cov-manage-emit list` showing all three
sources. `IGNORED: 5` was exactly `Makefile`, `app.exe`, and three `.o` files
— confirming that the earlier denominator inflation came from the idir being
nested under the project directory, not from buildless capture generally.

**`unconfigured-compilers` was non-empty on this perfect capture.** It
contained one entry, `<project-dir>\gcc` — a path that does not exist on
disk, evidently the bare command name resolved against the project directory
rather than `PATH`. This is the sharpest result of the whole exercise: Method
B alone would have reported a configuration hole in a capture that was
complete. It is now rule 14's second half, and
`tools/capture_fidelity.py method-b` partitions entries into existing and
phantom.

**`output/cli-diagnostics.json` exists on the CLI path** — one of the
filenames previously listed as never observed. It is in `output/`, not
`scan-transparency/`. Its `capture` section carries `primary-capture-mode`,
`capture-rate`, `capture-summary`, the effective `build-command`,
`project-directory`, `intermediate-directory`, `configuration-hash`, and
`command-info` (every command, with cwd and **full environment including
`PATH`** — a handling caution). `coverity analyze` **appends an `analysis`
section** to the same file.

`scan-transparency/` was again byte-for-byte unchanged by `coverity analyze`
(md5-compared). The files analysis added were all under `output/` plus
`coverity-cli/analyze-mode`.

Other CLI-only artifacts recorded: `coverity-cli/` holding
`build-compiler-configs/` (the CLI generates its own multi-language template
config set, so no `--config` or `cfg/` is involved),
`buildless-compiler-configs/`, `timestamps.json` (`[]` on a complete capture;
it named the uncaptured source on the incomplete run), `strip-path`,
`capture-platform`, `config-hash`; and `output/strip-paths.json`.

### Still open

`cov-analyze.exe` and `cov-build.exe` both contain strings for
`successfully-captured-files`, `partially-captured-files`, `uncaptured-files`,
`ignored-files`, `analysis-ignored-duplicate-files`, and
`analysis-ignored-filtered-files`. None appeared on any of the three runs --
`cov-build`, an incomplete CLI capture, or a clean CLI capture. String
presence proves nothing about the writer: these symbols sit in a library
linked into nearly every binary in `bin/`. Remaining candidates are `coverity
scan`, duplicate or filtered translation units, and a genuine partial parse.
Until pinned, **the absence of these files is uninformative** and must not be
reported as evidence that nothing was ignored, duplicated, or filtered.

- **Rule 14 -- the unconfigured-compiler true positive, beside the phantom.**
  Two include-free C sources; `cov-configure --gcc` only; `gmake` compiling
  `src/configured.c` with `gcc` and `src/unconfigured.c` with
  `tools/mycc.exe`, a byte copy of the same gcc renamed so it matches none of
  `--gcc`'s globs (`*-g++ *-gcc ar g++ g++-* gcc gcc-* ld`). Nothing outside
  the scratch directory was modified; the copy needs `-B <libexec>` to find
  `cc1`, and include-free sources to avoid needing system header paths.
  - `cov-build` reported **`Emitted 1 C/C++ compilation units (100%)
    successfully`** with half the product uncaptured. The percentage is
    measured against what it *intercepted*, so an unconfigured compiler
    shrinks the denominator instead of lowering the rate.
  - `unconfigured-compilers` carried **both kinds of entry at once**:
    `<build-cwd>\gcc` (does not exist -- artifact; gcc *was* configured and
    its TU captured) and `<build-cwd>	ools\mycc.exe` (exists -- the real
    hole). The existence test sorted them correctly.
  - **The file is CRLF.** A shell existence loop (`while read -r line; do
    [ -e "$line" ]`) tests a path with a trailing `
` and reports *every*
    entry as non-existent, including the true positive -- silently converting
    a real hole into a dismissed artifact. Caught only because the shell check
    and the tool disagreed. `capture_fidelity.py` reads text-mode and strips,
    so it was unaffected.
  - **`coverity list` did not flag the miss**: `FAILED: 0`, and the uncaptured
    source folded into `IGNORED: 17` with no per-file row -- indistinguishable
    from a README, exactly as in the rule 9 vacuous-capture runs. Method A saw
    a gap in the count; only Method B named the cause. Neither alone
    sufficed.
  - Adjudicated `SHORTFALL` (2/1/1/1), naming `src/unconfigured.c`, the one
    existing unconfigured compiler, and the phantom separately.

- **Rule 8 -- a deleted captured source, and who notices.** Deleted one
  captured `.c` from the project tree and re-ran `coverity list --all`
  against the unchanged idir, on two capture paths. Sources restored
  afterwards.
  - **CLI-captured idir** (`coverity capture`): the file appeared under
    *Captured files not found on disk* as `src\util.c  Succeeded  4`, and
    *outside of the project directory* was empty. Correct behaviour.
  - **`cov-build` idir**: *Captured files not found on disk* stayed **empty**;
    the deleted file appeared under *Captured files outside of the project
    directory*. Reproduced on two projects -- one without any build-system
    manifest, one with a Makefile that `coverity list` *did* attribute as a
    module ("Files for module: ...\Makefile"). So the discriminator is the
    capture path, not module attribution. Likely mechanism: the CLI records a
    project root in `coverity-cli/strip-path`, `cov-build` records none, so
    absolute captured paths are never related to `--project-dir`.
  - **The capture summary is blind to it either way**: `SUCCEEDED: 3`,
    `FILES CAPTURED: 3`, with the deleted file still carrying `Succeeded` and
    its line count. Only the section names it.
  - Remediation found in the reference: `cov-build --delete-stale-tus`
    deletes TUs whose sources were removed or renamed, **off by default**.
- **`coverity list` mutates the intermediate directory.** It creates
  `coverity-cli/` in an idir produced by `cov-build` alone. Verified by
  checking a virgin `cov-build` idir (absent) against two on which
  `coverity list` had been run (present). It is not a read-only query --
  relevant to release gating, archival, and anything that hashes an idir.

- **Rules 11 and 13 -- denominator inflation, a failed TU, and no link
  units.** Three-source CMake project (static lib `mathy` + executable `app`)
  with `check_include_file("stdio.h")`, `check_include_file` for a header that
  does not exist, and `check_function_exists(strlen)`. Captured as
  `cov-build ... sh -c "cmake -S . -B build -G 'Unix Makefiles' && cmake
  --build build"` so configure-time probes are intercepted too.
  - `[WARNING] Emitted 7 C/C++ compilation units (87%) successfully`. Of 8
    TUs, **five were build-system scaffolding**: `CMakeCCompilerId.c`, two
    `CheckIncludeFile.c`, `CheckFunctionExists.c`, and `CMakeCCompilerABI.c`
    -- the last from `C:/Program Files/CMake/share/...`, outside the project
    tree. **Product capture was 3 of 3.** This is the zlib "97%" result
    reproduced from scratch.
  - CMake **deletes** its `CMakeFiles/CMakeScratch/TryCompile-*` directories
    after configure, so those TUs exist in the emit with no file on disk.
    They always present as surplus, and that is not staleness.
  - **Missing AST found here**: the failing probe emitted with
    `had-failures: true`, `had-abstract-syntax-trees: false`, and
    `capture-percentage: 100`. Combined with the rule 34 result, the
    percentage now has a measured 100 at *both* extremes -- a TU missing one
    function, and a TU containing nothing at all. It is not a health signal.
  - **Link units: none.** `lu-count: 0`, empty `link-units`, and zero
    `cov-emit-link` invocations -- despite the build producing `libmathy.a`
    and `app.exe`, and despite `ar` being configured and intercepted
    (`COMPILING: cov-translate.exe "ar.exe" qc ...` in the capture log).
    `cov-emit-link.exe` ships in `bin/` with no help file and no enabling
    option in `cov-build`/`cov-translate`. So the object-to-TU reconciliation
    the reference recommended is unavailable here, and `lu-count: 0` is the
    ordinary result rather than a finding. Claim corrected.
  - **Tool bug found and fixed.** The first adjudication graded `DEGRADED`,
    because the failed probe was counted as an unusable TU. Degradation is
    now split by whether the TU matched the expectation: the corrected run
    grades `SURPLUS` (3/8/7/7), states that every expected source was
    captured and fully parsed, and lists the failed probe as informational.
    A build probe designed to fail must not degrade the product verdict.

- **Rule 32 -- ccache, three ways.** Two-source Makefile project,
  `CC = ccache gcc`, `CCACHE_DIR` pointed at scratch so the real cache was
  untouched. One fresh idir per run.

  | `ccache` configured? | Cache state | Emitted |
  |---|---|---|
  | no (`--gcc` only) | fully warm, 2/2 hits | **0 TUs**, `[WARNING] No files were emitted…`, `successes = 0` |
  | no | partly warm, 1 hit / 1 miss | **1 of 2**, `Emitted 1 … (100%) successfully`, no warning, only the *miss* captured |
  | yes (`--template --compiler ccache --comptype prefix`) | fully warm, 2/2 hits, gcc never ran | **2 of 2, 100%**, `CONSISTENT` (2/2/2/2) |

  - **Method B is blind to it.** `scan-transparency/unconfigured-compilers`
    was **empty in all three runs**, including the one that captured nothing.
    `ccache` ran as the compiler driver, was unconfigured in two of the runs,
    and was never named. Rule 32's claim that checking that file "catches a
    missing prefix configuration" was wrong and is corrected.
  - The middle row is the one that reaches a report: a 50% capture presented
    as 100% success with every per-TU field healthy. Adjudicated `SHORTFALL`
    (2/1/1/1); the standing rationale already lists compiler-cache hits among
    the causes.
  - The third row settles the previously-assumed claim: with the prefix
    configured, a build in which the compiler **never executed** captured
    completely, and `emit/<host>/config/<md5>/prefix-config-0` records that
    the wrapper was seen through. The failure mode is the missing prefix
    configuration, not the cache -- so clearing the cache would have
    "worked" for the wrong reason.

- **Rule 33 -- the commit-side staleness check, measured live.** Coverity
  Connect at `http://localhost:8080` (HTTP, port 8080 -- the target the user
  gave, *not* the private address and port named inside the auth key;
  rule 28).
  One analyzed idir copied three ways, each committed to a throwaway stream
  `idir-staleness-test` under project `claude-idir-staleness`, with
  `--strip-path` per rule 31.

  | Copy | emit vs `output/` | Result |
  |---|---|---|
  | `cp -a` (times preserved) | output newer | committed, snapshot 10033 |
  | `cp -r` (all mtimes rewritten to now) | equal | **committed**, snapshot 10034 |
  | `cp -a` + `touch emit/*/emit-db` | emit newer | **refused, exit 2** |

  Exact refusal:

  ```
  [ERROR] Emit appears more recent than analysis results.
          Please read the documentation to determine the appropriate
          ordering in which to run the Coverity Prevent commands.
  ```

  - **The check is relative, not absolute.** It asks only whether the emit is
    *newer than* the analysis results. A wholesale mtime rewrite does not trip
    it, because everything lands equal -- which makes the uniform rewrite the
    more dangerous case: it passes while certifying an ordering that no longer
    means anything.
  - `cp -r` passing looks incidental rather than guaranteed: `emit/` sorts
    before `output/`, so a recursive copy touches `output/` last. A copy tool
    walking the tree in another order could leave emit newer and be refused.
    Inference from the ordering, not separately measured.
  - This **overturns the earlier offline finding.** The previous probe
    concluded the command contacts the host before any local staleness check,
    because all three copies behaved identically without a reachable host.
    They do not behave identically once there is one. Whether the check runs
    before or after the connection is still unsettled -- the refusal printed
    with no preceding `[STATUS]` connection lines, but authentication may be
    silent -- and nothing here depends on that ordering.
  - Incidental: `cov-commit-defects` warns `--host is deprecated, use --url
    instead`.

## The calibration runs, and what each settled

Every row below was produced deliberately and adjudicated by the tool. Four
of them changed the skill rather than confirming it.

The adjudication table in `references/capture-fidelity.md` is reasoned from
mechanism, not measured. Each row below should be produced deliberately and
the three methods' actual output recorded, in the style of
`coverity-build-fidelity/references/worked-example-zlib.md`:

1. ~~**Unconfigured compiler.**~~ **DONE** -- see the true-positive entry
   above. The existence check is no longer a heuristic without evidence: a
   single run produced a phantom and a true positive in the same file and
   sorted them correctly. It also turned up the CRLF trap, which is the more
   dangerous half of the finding.
2. ~~**Vacuous capture.**~~ **DONE** -- see the rule 9 entry above and
   `references/worked-example-vacuous-capture.md`. Both the no-op build and
   the partial build were reproduced on `cov-build` and adjudicated against a
   frozen expectation; `VACUOUS` and `SHORTFALL` both behaved correctly. The
   result revised the premise: `cov-build` *does* warn on a zero-TU capture,
   so the dangerous case is the partial build, which reports 100% and
   "completed successfully". The CLI path is worse still (a build compiling
   one of two sources reported `SUCCEEDED: 13` via buildless backfill).
3. ~~**Partial parse.**~~ **DONE**, and it revised its own premise -- see the
   rule 34 entry above. `coverity list` does report `Incomplete` (note:
   `Recoverable Errors`), but `capture-percentage` stayed at **100** while a
   function was missing from the emit, so the percentage is not the signal
   this row assumed it would be.
4. ~~**Missing AST.**~~ **DONE** -- a compilation that fails outright. Came
   free with the CMake run below: the deliberately-failing
   `check_include_file` probe emitted a TU with `had-failures: true`,
   `had-abstract-syntax-trees: false` and **`capture-percentage: 100`**.
   `cov-manage-emit list` labels it ` (no ASTs) (failure)`; `coverity list`
   gives status `Failed` with 12 code lines -- the only sighting of `Failed`
   in any run so far. Method B stayed silent.
5. ~~**Compiler cache.**~~ **DONE** -- see the ccache entry above. Method B
   does **not** notice: `unconfigured-compilers` was empty on every run,
   including one that captured nothing. The rule 32 claim that a warm cache
   is harmless once the prefix is configured is now measured, not assumed. Lower priority now: the
   incremental-build measurement above establishes the *shape* of a
   build-never-compiled-it hole (silent, 100%, `failures = 0`). What remains
   specific to `ccache` is whether the wrapper additionally appears in
   `unconfigured-compilers`.

6. ~~**Stale idir.**~~ **DONE** -- see the stale-source entry above. It
   populates on a CLI-captured idir and does **not** on a `cov-build` one,
   which is the opposite of the assumption this row was written under.
7. ~~**Denominator inflation.**~~ **DONE** -- reproduced at 87%, and it
   exposed a grading bug in the tool. See the entry above.
8. ~~**Link-unit reconciliation.**~~ **DONE, negative** -- link units are not
   produced on this toolchain at all, so the check cannot be built. See the
   entry above. Original wording follows.
   **Link-unit reconciliation.** A project that actually links, to exercise
   the object-to-TU check and confirm `lu-count` behaviour.

9. ~~**"Captured files outside of the project directory" on a `cov-build`
   idir.**~~ **DONE** -- the discriminator is the capture path; details below. On all three rule 9 runs, `coverity list --project-dir <proj>
   --all` filed every captured file under that heading although the files are
   `<proj>\src\*.c`, while the `Files for module: <proj>\Makefile` section sat
   empty. Not a path-style artifact: native-backslash, forward-slash, and
   cwd-default `--project-dir` all behaved identically. Distinct from the
   genuine case, which this project reproduced separately by pointing
   `--project-dir` at a renamed root.

   **SETTLED: the discriminator is the capture path.** The `coverity capture`
   comparison that failed before now exists -- a CLI capture driven by an
   explicit `-- gmake` build command, which emitted 3 of 3 sources. Same
   `coverity list --all` invocation against each:

   | Idir | Module section | Captured files filed under |
   |---|---|---|
   | `coverity capture` | populated (`src/a.c`, `src/main.c`) | nothing -- *outside* was empty |
   | `cov-build` (Makefile present) | **present but empty** | *outside of the project directory* |
   | `cov-build` (no build manifest) | absent | *outside of the project directory* |

   So it is not module attribution either: the middle row has a Makefile that
   `coverity list` names as a module and still files every captured file as
   outside. Likely mechanism: the CLI records a project root in
   `coverity-cli/strip-path` at capture time and `cov-build` records none, so
   absolute captured paths are never related to `--project-dir`.

   Two consequences, both measured: the *Captured files not found on disk*
   detector never fires on a `cov-build` idir (see the stale-source entry
   above), and the adjudicator's project-directory caveat fired on healthy
   captures. The caveat now recognises the all-captured-files-outside pattern
   on a `cov-build` idir and reports it as normal presentation, while still
   saying that the counts are not tree-comparable and that staleness cannot
   be detected from this run.

10. ~~**Rule 33: which check actually rejects a timestamp-mangled idir.**~~
    **DONE** -- run against a live Coverity Connect. See the entry above. The
    earlier offline conclusion (that no local staleness check is reachable)
    was an artifact of having no host: with one, the emit-newer case is
    refused outright.

**The queue is empty.** Every row above has been produced deliberately and
recorded, so the diagnosis table is no longer a well-grounded hypothesis: each
branch of it has been reached by a real capture and adjudicated by the tool.
Four rows changed the skill rather than confirming it -- the partial parse
revised its own premise, the stale-idir row inverted, link-unit reconciliation
came back negative and retracted a recommendation, and rule 33's commit check
overturned an earlier offline conclusion.

What remains reasoned rather than measured is narrower and worth stating
plainly when a reader is betting on it: the mechanism behind the
`unconfigured-compilers` phantom and behind the `cov-build` outside-project
bucketing (both are consistent inferences from `strip-path`, not confirmed
internals), whether the commit-side staleness check runs before or after the
connection, and the conditions under which `successfully-captured-files` and
its siblings are ever written. New rows belong here as they are found.

**Deliberately not queued:** why an analysis is noisy. Rule 26 has the user
*detect* noise and re-check capture; diagnosing the rest is a methodology of
its own, outside what this skill covers, and belongs with Coverity support.
