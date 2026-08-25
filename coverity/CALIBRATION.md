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
- `cov-manage-emit list-capture-diagnostics` exists, is **undocumented**, and
  returns `format_version: 4` with per-file `capture-percentage`,
  `had-failures`, `had-recoverable-errors`, `had-abstract-syntax-trees`,
  `code-line-count`, `last-modified`, `file-size-in-bytes`.
- `cov-manage-emit list-json` returns, beyond the documented fields, the
  **undocumented** `isFailure`, `isCreateEDGPCH`, `hadRecoverableErrors`,
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

## Not yet calibrated -- the priority queue

The adjudication table in `references/capture-fidelity.md` is reasoned from
mechanism, not measured. Each row below should be produced deliberately and
the three methods' actual output recorded, in the style of
`coverity-build-fidelity/references/worked-example-zlib.md`:

1. **Unconfigured compiler.** Capture a build using a renamed/wrapper
   compiler with no matching config. Confirm `unconfigured-compilers` names
   it and the TUs are absent. *(Expected: `SHORTFALL` + method B non-empty.)*
   Now more urgent than when first queued: a clean CLI capture has been seen
   producing a **phantom** entry, so the true-positive shape needs measuring
   to tell the two apart reliably. The existence check is a heuristic until
   then.
2. ~~**Vacuous capture.**~~ **DONE** -- see the rule 9 entry above and
   `references/worked-example-vacuous-capture.md`. Both the no-op build and
   the partial build were reproduced on `cov-build` and adjudicated against a
   frozen expectation; `VACUOUS` and `SHORTFALL` both behaved correctly. The
   result revised the premise: `cov-build` *does* warn on a zero-TU capture,
   so the dangerous case is the partial build, which reports 100% and
   "completed successfully". The CLI path is worse still (a build compiling
   one of two sources reported `SUCCEEDED: 13` via buildless backfill).
3. **Partial parse.** Capture a source with constructs the front end only
   partly understands; confirm `capture-percentage < 100` and check whether
   `coverity list` reports `Incomplete`.
4. **Missing AST.** Find a real path to `had-abstract-syntax-trees: false`
   and confirm how the other two methods present it.
5. **Compiler cache.** Capture with `ccache` warm; confirm the shape of the
   resulting hole and whether method B notices. Lower priority now: the
   incremental-build measurement above establishes the *shape* of a
   build-never-compiled-it hole (silent, 100%, `failures = 0`). What remains
   specific to `ccache` is whether the wrapper additionally appears in
   `unconfigured-compilers`.

6. **Stale idir.** Re-run `coverity list` after deleting a captured generated
   source; confirm *Captured files not found on disk* populates.
7. **Denominator inflation.** A CMake project, to reproduce the zlib "97%
   with a `TryCompile` failure" result under the three-method procedure and
   confirm it grades `SURPLUS`/`CONSISTENT_WITH_EXCLUSIONS` rather than
   failing.
8. **Link-unit reconciliation.** A project that actually links, to exercise
   the object-to-TU check and confirm `lu-count` behaviour.

9. **"Captured files outside of the project directory" on a `cov-build`
   idir.** On all three rule 9 runs, `coverity list --project-dir <proj>
   --all` filed every captured file under that heading although the files are
   `<proj>\src\*.c`, while the `Files for module: <proj>\Makefile` section sat
   empty. Not a path-style artifact: native-backslash, forward-slash, and
   cwd-default `--project-dir` all behaved identically. Distinct from the
   genuine case, which this project reproduced separately by pointing
   `--project-dir` at a renamed root. A `coverity capture` comparison was
   attempted and did not settle it -- on that project the CLI failed to find
   `make`, fell back to buildless capture, and emitted nothing (`No sources
   were recognized in the project directory`), so there was no captured set
   to classify. Until pinned, **that section is not a reliable "outside the
   project" signal on a `cov-build` idir**, and the adjudicator's
   project-directory caveat will fire on healthy captures.

10. **Rule 27: which check actually rejects a timestamp-mangled idir.**
    Needs a Coverity Connect instance. Probed offline and *not* settled:
    against an analyzed idir copied three ways -- `cp -a` (times preserved),
    `cp -r` (all mtimes rewritten to now), and `cp -a` plus `touch` on
    `emit/*/emit-db` (emit made newer than `output/`) -- `cov-commit-defects`
    behaved identically on all three, because it resolves and contacts the
    host before performing any local staleness check. `cov-format-errors` and
    a re-run of `cov-analyze` likewise did not distinguish them. So the
    mechanism is documented for *emit* decisions (the `--force` wording in
    `cov-emit-cs`/`-java`/`-vb`) but the commit-side refusal remains reported
    rather than measured. Repeat against a live Connect and record the exact
    message.

Until these are done, the skill's *commands and fields* are trustworthy and
its *diagnosis table* is a well-grounded hypothesis. Say so if it matters to
the reader.

**Deliberately not queued:** why an analysis is noisy. Rule 26 has the user
*detect* noise and re-check capture; diagnosing the rest is a methodology of
its own, outside what this skill covers, and belongs with Coverity support.
