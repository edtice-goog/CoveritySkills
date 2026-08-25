# Capture fidelity: three independent methods, then a judgment

The question is not "what percentage did `cov-build` print?" It is: **of the
code that should have been analyzed, how much reached the analyzer in a
usable state?**

Three sources can answer it. They draw on different evidence, so they fail
differently -- which is the entire point of running all three.

| | Method | Evidence base | Blind to |
|---|---|---|---|
| A | `coverity list` / `cov-manage-emit` | the emit database | anything the build never attempted |
| B | `idir/scan-transparency/` | the build's process tree | anything configured that then failed to parse |
| C | model inference | source tree + build system | what actually happened at runtime |

No single one is sufficient. A reports triumphantly on an empty idir. B is
clean when a correctly-configured compiler emitted garbage. C is confident
and wrong whenever the build does something the files do not say.

## The independence rule

Run them independently and **freeze each verdict to disk before starting the
next**. Order is not free:

> **Method C first, written down, before the intermediate directory is
> opened.**

C is the only contaminable method. Once you have read the emit inventory you
will "expect" exactly what you just read, agreement becomes automatic, and
the check degrades into an expensive way of restating A. A and B are
mechanical readouts and may run in either order.

Suggested layout, so the freeze is real rather than an intention:

```
capture-check/
  method-c-expected.json    # written first, not edited afterwards
  method-a-inventory.json
  method-b-transparency.json
  adjudication.md
```

If Method C turns out to have been wrong, say so in the adjudication and
explain what the tree failed to reveal. Do not quietly rewrite it -- a
corrected expectation with its reason is a finding; a silently edited one
destroys the experiment.

---

## Method A -- the capture inventory

### A1. `coverity list` (preferred)

```bash
$BIN/coverity list --project-dir <src> --dir <idir> --all
```

Walks the **project directory** and reports each file's capture status. This
is the denominator that matters: files on disk, not records in a database. It
works against an intermediate directory produced by plain `cov-build`, not
only by `coverity capture`.

**Always pass `--all`.** By default the command hides files under `vendor`,
`node_modules`, `__MACOSX`, and any dot-directory *unless they were
captured*. That default is a sensible browsing view and a terrible audit: the
files most likely to be silently skipped are exactly the ones it hides.

Per-file capture status:

| Status | Meaning |
|---|---|
| `Succeeded` | captured |
| `Incomplete` | partially captured -- parts of the file were not understood |
| `Failed` | capture attempted, nothing understood |
| `Ignored` | never attempted |

Then a summary block:

```
Capture summary:
    SUCCEEDED: 1
    INCOMPLETE: 0
    FAILED: 0
    IGNORED: 14
    FILES CAPTURED: 1
    LINES OF CODE: 21
```

`IGNORED` is normally large and normally benign -- it counts every README,
build script, and unsupported-language file in the tree. Do not report it as
a miss without partitioning it. `INCOMPLETE` and `FAILED` are the numbers
that matter, and for C/C++ `FAILED` most often means *the build system never
compiled the file*, not that Coverity choked on it.

The command also prints three diagnostic sections that the command reference
does not document. Each is a genuine signal:

- **Captured files not found on disk** -- the emit database references source
  that no longer exists. Generated code cleaned up after the build, a
  *reused stale idir*, or path drift. Treat a non-empty section as a reason
  to distrust the whole idir until explained.
- **Captured files outside of the project directory** -- either
  `--project-dir` is wrong, the build is out-of-tree, or the idir was
  captured under a different root. Benign once explained, but it means the
  project-directory denominator did not cover the captured set, so the
  `IGNORED` and `SUCCEEDED` counts are not comparable to the tree.
- **Files not in any module** -- files the build system does not claim.

### A2. `cov-manage-emit list-capture-diagnostics` (machine-readable)

The best programmatic source, and what `coverity list` calls internally. Not
listed in `cov-manage-emit --help` on 2026.6.0 -- check your own installation
before relying on the field names below.

```bash
$BIN/cov-manage-emit --dir <idir> list-capture-diagnostics
```

```json
{
  "type": "Coverity Capture Diagnostics",
  "format_version": 4,
  "captured-files": [
    {
      "file-path": ".../src/main.c",
      "last-modified": "2026-08-20T20:38:53+0000",
      "file-size-in-bytes": 1042,
      "code-line-count": 21,
      "translation-unit": {
        "id": 1,
        "source-language": "C",
        "capture-percentage": 100,
        "had-failures": false,
        "had-recoverable-errors": false,
        "had-abstract-syntax-trees": true
      }
    }
  ]
}
```

`capture-percentage` is per-translation-unit capture fidelity -- the thing
the headline number is usually mistaken for. Anything below 100 is a partial
parse: the TU exists, the analyzer will run on it, and some of the code is
simply not there. `had-abstract-syntax-trees: false` is worse and quieter --
a record with no AST is not analyzable at all.

`format_version` may move between releases, and there is no published schema
to pin it against. Check it and degrade to A3 rather than mis-parsing.

**If this subcommand is missing or its shape has moved, do not give up on the
question** -- A3's `list` and `list-json` answer the analyzable/not-analyzable
question in documented form, and `coverity list`'s per-file capture status
covers succeeded / incomplete / failed. The verdict then loses the numeric
parse percentage and per-TU recoverable-error flag, which the report should
say, but it keeps the part that decides whether a TU can be analyzed at
all.

### A3. Other `cov-manage-emit` readouts

```bash
$BIN/cov-manage-emit --dir <idir> list
$BIN/cov-manage-emit --dir <idir> list-json
$BIN/cov-manage-emit --dir <idir> list-capture-invocations --no-process-details
```

`cov-manage-emit list` is the smallest readout and carries one fidelity
signal of its own: a TU with no ASTs is printed with a ` (no ASTs)` suffix.

`list-json` per TU. Prefer the documented fields -- the reference explicitly
asks callers to ignore attributes it does not document -- and treat the rest
as corroboration rather than as the basis of a verdict:

| Field | Use |
|---|---|
| `primaryFilename` | the captured source |
| `primaryFileHash` | MD5 -- proves *which* revision was captured |
| `hasASTs` | **documented.** false = present but not analyzable |
| `isFailure`, `hadRecoverableErrors` | parse trouble (not in the reference) |
| `astFidelityPercent` | same quantity as `capture-percentage` (not in the reference) |
| `isFromBootClassPathOrSystem` | system/library code, not product |

`primaryFileHash` deserves emphasis: it is the only cheap way to prove the
idir holds the source you think it does. Against a stale idir, or a worktree
that moved under the build, it is decisive.

`list-capture-invocations` adds **link units** -- what got linked, from which
object files -- plus a metrics block:

```json
"metrics": { "tu-count": 500, "tu-failures": 3, "lu-count": 10, "lu-failures": 0 }
```

Link units enable the strongest build-system-agnostic reconciliation
available: for each linked artifact, every input object should correspond to
a captured TU. Objects with no TU behind them are holes, and they are located
precisely. `lu-count: 0` on a project that links is itself a finding.

### A4. `output/cli-diagnostics.json` -- only on a CLI capture

When capture went through the `coverity` CLI rather than `cov-build`, this
file is the best provenance record in the intermediate directory. Under
`capture`:

| Field | Use |
|---|---|
| `primary-capture-mode` | `Build` vs buildless -- **check this first for C/C++** |
| `capture-rate` | the headline rate, machine-readable |
| `capture-summary` | `files-captured`, `succeeded`, `ignored`, `lines-of-code` |
| `effective-configuration` &rarr; `build-command` | **the build command actually used** |
| `project-directory`, `intermediate-directory` | what the denominator covered |
| `configuration-hash` | pins the effective config across runs |
| `command-info` | every command run, with cwd and environment |

`coverity analyze` **appends an `analysis` section** to the same file. So the
CLI does record analysis-side diagnostics -- just not under a name containing
"scan transparency".

`primary-capture-mode` deserves the emphasis. For C, C++, Objective-C, and
Visual Basic, buildless capture does not apply, so a mode other than `Build`
on a C/C++ project means the compiled sources were never captured no matter
what the summary counts say. Pass the build command explicitly:

```bash
coverity capture --project-dir <src> --dir <idir> -- gmake
```

**Security.** `command-info` embeds full environment blocks, `PATH` included,
in plain JSON. Check it before sending an intermediate directory to anyone,
support included -- the same caution that applies to `build-log.txt`.

### A5. The headline numbers, and why they mislead

`cov-build` prints two different figures, and `cov-analyze` a third:

```
Emitted 1 C/C++ compilation units (100%) successfully
1 C/C++ compilation units (100%) are ready for analysis
```

```
Files analyzed : 1 Total
```

Three denominators, three meanings. Also in `idir/BUILD.metrics.xml`:
`successes`, `failures`, `recoverable-errors`, and the `buildcmd` actually
wrapped.

**The percentage is a trap in both directions.** Its denominator includes the
build system's own throwaway compilations, so a figure below 100% is often
entirely benign -- measured on zlib, "40 compilation units (97%)" with the
single failure being a CMake `TryCompile` feature probe, and product capture
at 100%. And 100% of nothing is 100%. A gate written as `< 100% -> fail`
rejects good builds and passes empty ones.

---

## Method B -- scan transparency

```bash
ls <idir>/scan-transparency/
cat <idir>/scan-transparency/unconfigured-compilers
```

`unconfigured-compilers` lists binaries that ran during the build, looked
like compilers, and were not configured as such. Its independence is why it
earns a separate method: it comes from **observing the build's process
tree**, not from the emit database. A capture can be completely empty and
still produce a truthful, informative `unconfigured-compilers`.

- Empty file: no compiler-shaped binary escaped configuration. This is a
  positive result, and it is *not* evidence that anything was captured.
- Non-empty: each entry is a *candidate* hole -- see the caveat immediately
  below before treating it as one. The usual real causes are cross-compiler
  prefixes, wrapper scripts, and `ccache`/`sccache`/`distcc`; route those to
  `coverity-compiler-configuration`.

### A non-empty `unconfigured-compilers` is not proof of a hole

Measured on 2026.6.0: a `coverity capture --dir <idir> -- gmake` that captured
**all three** product sources -- `capture-rate: 100`, `succeeded: 3`, three
TUs in the emit -- still wrote `<project-dir>\gcc` into
`unconfigured-compilers`. That path **does not exist**; it looks like the bare
command name `gcc` resolved against the project directory instead of `PATH`.

So: **check whether each named path exists on disk.** A phantom path is an
artifact. A real path is a candidate hole, and even then confirm against
Method A before reporting it -- a compiler-shaped binary that compiled nothing
product-relevant is benign.

Reading Method B as decisive on its own would have failed a perfect capture
here. This is exactly the disagreement the adjudication step exists to
resolve, and it is the strongest practical argument for running all three.
`tools/capture_fidelity.py method-b` partitions the list into
`unconfigured_compilers_existing` and `unconfigured_compilers_phantom` for
this reason.

Generation is on by default, controlled by `--enable-scan-transparency-data`
and `--disable-scan-transparency-data` on both `cov-build` and `cov-analyze`.
**A missing `scan-transparency/` directory means the method did not run, not
that it passed.** Check the directory exists before reporting a clean result
from it.

### It is written at capture time, and nothing needs committing

Measured on 2026.6.0, both ways round:

| Step | Effect on `scan-transparency/` |
|---|---|
| `cov-build` | creates the directory and `unconfigured-compilers` |
| `cov-analyze` over that idir | **no change** |
| `coverity capture` | creates `unconfigured-compilers` and `cli-ignored-files` |
| `coverity analyze` over that idir | **no change** |

So read it as soon as capture finishes -- there is no reason to wait for
analysis, and its contents are not the analyzer's testimony. A 2024.12.1
`cov-build` intermediate directory from a full, successful analysis likewise
carried only an empty `unconfigured-compilers`.

Nothing has to be committed to Coverity Connect for the local folder to be
populated. The server-side `scan.transparency.enabled=true` property in
`cim.properties` (plus a restart) governs only what *Connect* stores and
shows -- snapshot Build Details gaining *Source Files Captured*, Analysis
Details gaining *Functions Analyzed (with Models)*, *Number of Annotations*
and *Number of Custom Models*, and a per-snapshot JSON download. That is a
different, richer dataset than the local folder, and it is not a prerequisite
for this method.

### Richness depends on the capture path

The CLI capture path writes more than `cov-build` does:

- `unconfigured-compilers` -- both paths.
- `cli-ignored-files` -- **CLI path only.** Project files the CLI knew about
  and did not capture. On a deliberately incomplete build it correctly named
  the C source the build never compiled, alongside the object files and
  executable it ignored by design.

Two practical consequences. First, on a `cov-build` idir the absence of
`cli-ignored-files` is structural, not a clean bill of health -- that evidence
has to come from Method A instead. Second, `cli-ignored-files` mixes genuine
misses with entirely expected ones (`.o`, `.exe`), so it must be partitioned
before it means anything, exactly like `IGNORED` in Method A.

`cli-diagnostics.json` does get written on the CLI path -- but to `output/`,
not `scan-transparency/`. See A4 above; it is the best provenance record in
the whole intermediate directory.

The binaries also carry strings for `successfully-captured-files`,
`partially-captured-files`, `uncaptured-files`, `ignored-files`,
`analysis-ignored-duplicate-files`, and `analysis-ignored-filtered-files`.
None of these appeared on any path tried -- `cov-build`, a CLI capture with a
real hole, or a clean CLI capture. They are presumably conditional on
something not reproduced yet: `coverity scan`, duplicate or filtered TUs, or a
genuine partial parse. **Treat their absence as uninformative** rather than as
evidence that nothing was ignored, duplicated, or filtered.

### The other transparency data

`cov-analyze`'s own transparency output concerns analysis rather than
capture -- which functions might need models, which annotations went unused,
custom model counts. It does not go to `scan-transparency/`; the
analysis-side artifacts sit in `idir/output/` as `analysis-warnings.json`,
`annotation-info.json`, `enabled-checkers.json`, and `summary.txt`.

---

## Method C -- independent inference

Produce this **first**, from the source tree and the build, without opening
the intermediate directory.

Read, in rough order of authority:

1. **The build system's own manifest of what it compiles** --
   `compile_commands.json`, `CMakeLists.txt`, `Makefile`s, `*.vcxproj`,
   `build.gradle`, `*.csproj`. `compile_commands.json`, where it exists, is
   close to ground truth and is generated independently of Coverity.
2. **Build output on disk** -- object files, archives, libraries. An object
   file is proof that a compilation happened. This is the most under-used
   evidence in the procedure and the least corruptible.
3. **The source tree**, partitioned by judgment into:
   - product sources that should be captured
   - build-system probes: `TryCompile`, `CMakeScratch`, `CompilerId`,
     `ShowIncludes`, autoconf `conftest.c`
   - tests and fixtures -- capture may be in or out of scope; say which
   - vendored third-party, and specifically whether it is *built from source*
     here or shipped prebuilt
   - generated code, and whether generation ran before capture
   - platform- or feature-conditional files excluded by this configuration

Record the expectation as a set of paths plus, for each exclusion, the
reason. The exclusion reasons are as much the deliverable as the count is;
they are what makes a later shortfall interpretable.

**This is where a model genuinely outperforms a script.** Recognizing that
`CheckIncludeFile.c` is a CMake probe, that `third_party/libfoo` ships a
prebuilt `.a`, that `parser.c` is regenerated from `parser.y`, or that a
directory is `#ifdef`-ed out on this platform is judgment about software, not
a pattern match. Be equally honest about what the tree cannot tell you:
whether the build was incremental, whether a compiler cache served hits,
whether a target failed and the build continued anyway.

---

## Adjudication

Compare the three frozen results. Let **C** be the expected product set,
**A** the captured set, **B** the unconfigured-compiler list.

| Pattern | Diagnosis | Action |
|---|---|---|
| `A` matches `C`, B empty, every `capture-percentage` 100 | Capture is sound | `CONSISTENT` |
| `A` much smaller than `C`, B empty | **The build did not compile them.** Incremental build with nothing to do, compiler-cache hits, wrong target, or a build that failed early and continued | Clean the tree and re-capture. The most common real failure |
| `A` much smaller than `C`, B non-empty | Unconfigured compiler | `coverity-compiler-configuration` |
| `A` near zero while the build reported success, B empty | **Vacuous capture.** A no-op incremental build, a build delegating to a persistent daemon or compile server (MSBuild node reuse, Gradle daemon), or `--record-only` with no `--replay` | `VACUOUS`. Never report as a pass |
| `A` larger than `C` | Denominator inflation -- build probes, tests, generated or third-party sources | `SURPLUS`. Benign; name the surplus rather than celebrating the count |
| `A` matches `C` but `capture-percentage < 100` or `had-recoverable-errors` | Partial parse; the TU is analyzed with pieces missing | `DEGRADED`. A prime cause of "Coverity missed my defect" |
| `hasASTs` / `had-abstract-syntax-trees` false | Record present, not analyzable | `DEGRADED` |
| "Captured files not found on disk" non-empty | Stale idir, cleaned generated code, or path drift | Distrust the idir until explained |
| B non-empty but `A` matches `C` | A compiler-shaped binary that compiled nothing product-relevant | Usually benign; name it |
| Analyzed count much smaller than `A` | Capture fine; **analysis** scoped down | Not a capture defect. `coverity-defect-detectability` |

### Grades

- `CONSISTENT` -- three methods agree; capture covers the expected set
- `CONSISTENT_WITH_EXCLUSIONS` -- agree once named, justified exclusions are
  applied; the exclusions appear in the report every time, never silently
- `SHORTFALL` -- captured set is a strict subset of expected, unexplained
- `SURPLUS` -- captured beyond expected; benign but named
- `DEGRADED` -- captured but not fully analyzable
- `VACUOUS` -- essentially nothing captured while the build claimed success
- `INDETERMINATE` -- the methods disagree and the disagreement is unresolved

Report the **triple**, never a lone percentage:

```
expected 128 product sources / captured 126 / analyzable 126
```

An `INDETERMINATE` naming the exact disagreement is a useful result. A
confident green check laid over a disagreement is not.

## Traps, collected

1. **100% of nothing is 100%.** Empty capture is the best-looking result the
   headline number can produce.
2. **A reused intermediate directory hides everything.** Yesterday's TUs
   answer today's questions. Capture fresh, or prove freshness.
3. **The percentage's denominator includes build-system probes.** Below 100%
   is frequently correct.
4. **`coverity list` hides vendor and dot-directories by default.** Use
   `--all`.
5. **`IGNORED` is mostly noise** -- READMEs and scripts. Partition before
   reporting it.
6. **A TU is not a source file.** One source compiled into two targets is two
   TUs and one file; object counts and unique-source counts legitimately
   differ.
7. **Emitted, analyzable, and analyzed are three numbers.** Do not quote one
   as another.
8. **A missing `scan-transparency/` directory is not a clean result.**
9. **`FAILED` in `coverity list` usually means the build did not compile the
   file**, not that Coverity failed on it.
10. **Capture verification does not license "the analysis was complete."** It
    measures the first four arrows of the pipeline chain and nothing further.
