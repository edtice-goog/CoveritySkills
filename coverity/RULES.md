# The Coverity rules

The standing rules for anyone — human or model — driving Coverity Static
Analysis. They are the things that are true regardless of which question you
are answering, and each one exists because ignoring it produces a *confident
wrong answer* rather than an error message.

Read this list before running a Coverity command. Nothing here is optional
craft; every rule below has a failure mode attached that has actually
happened.

**How this list is maintained.** Numbers are stable and citable: rule 1 is
always the template-configuration rule. A new rule takes the next free number
and is filed under the section it belongs to, so numbers are not necessarily
in ascending order down the page. A rule that turns out to be wrong is marked
superseded in place rather than deleted or renumbered.

**Provenance.** Each rule ends with a `Source:` line. *Verified* means
established by direct execution against a real installation (see
`CALIBRATION.md` for the environment and the exact claims). *Reasoned* means
derived from documented mechanism but not yet reproduced deliberately — still
actionable, but say so if a reader is betting on it.

---

## The two that come first

### 1. Always use a template compiler configuration

`cov-configure --template`, or one of the language shortcuts (`--gcc`,
`--msvc`, `--java`, …), which already produce template configurations.

**Why.** A template configuration maps a compiler *executable name* to a
compiler *type* and defers the actual probe to build time, repeating it for
each distinct argument set the build uses. Without `--template`,
`cov-configure` probes once, at configure time, with whatever arguments and
environment happen to exist at that moment — and compiler behaviour changes
with the arguments passed (target, architecture, language standard, sysroot,
`-D` macros, `-m32/-m64`). One configure-time probe describes one invocation
and is then applied to all of them. **Data captured under such a configuration
is tainted**, and it does not announce itself.

**Do.**

```bash
cov-configure --config <cfg>/coverity_config.xml --template --compiler <bare-executable-name> --comptype <type>
```

`--compiler` takes a bare name, never a path; do not combine `--template`
with `--version`. The compiler need not exist yet, so configuration never has
to wait on a toolchain that the build itself downloads.

**Check.** `grep -c template <cfg>/coverity_config.xml` — `0` means probed.
`ls <cfg> | grep -c '^template-'` — `0` means probed. A probed config also
pins version-specific names (`gcc-13`, `x86_64-linux-gnu-gcc-13`) where a
template config records globs (`gcc`, `gcc-*`, `*-gcc`).

The danger zone is the explicit `--compiler X --comptype Y` form — exactly
what you reach for with cross-compilers, embedded toolchains, and wrapper
scripts. This is the single most common Coverity setup mistake.

Source: verified — `coverity-compiler-configuration`.

### 2. Verify capture fidelity before believing any result

Run the three-method capture-fidelity check (`references/capture-fidelity.md`,
`tools/capture_fidelity.py`) before answering any question that depends on
analysis output.

**Why.** Every downstream question — "why wasn't this defect found?", "is this
scan release-worthy?", "did the build change?" — silently assumes the code
reached the analyzer. That assumption fails often, fails quietly, and fails in
the flattering direction: **a capture that emitted nothing reports 100%,
raises no errors, and finishes fast.**

**Do.**

```bash
python3 tools/capture_fidelity.py expect --project-dir <src>
```

Review the scaffold by hand, set decisions and reasons, and mark it reviewed —
then:

```bash
python3 tools/capture_fidelity.py method-a --bin $BIN --dir <idir> --project-dir <src>
```

```bash
python3 tools/capture_fidelity.py method-b --dir <idir>
```

```bash
python3 tools/capture_fidelity.py adjudicate -o adjudication.md
```

Method C (the independent expectation) is produced and **frozen to disk
first**, before the intermediate directory is opened. It is the only
contaminable one: read the emit inventory and you will "expect" precisely what
you just read, agreement becomes automatic, and the check degrades into an
expensive way of restating the inventory. Agreement between the three methods
is the evidence; the *pattern of disagreement* is the diagnosis.

It is short when things are fine.

Source: verified end to end (tooling and commands); the disagreement table is
reasoned — see `CALIBRATION.md`.

---

## Configuration

### 3. Pin exactly one installation for the whole session

Ask the user, or check project notes and memory. **Do not scan the disk** —
installations are large, live in nonstandard places, and the user can answer
in seconds. Confirm what you found with `cov-analyze --help` and the `VERSION`
file.

Multiple versions side by side is the normal state of a Coverity user's
machine, not an anomaly. Emit databases are version-sensitive, and mixing tool
versions against one intermediate directory is its own failure mode. Record
which one you pinned.

Source: verified (multi-version installs; version-sensitive emit) —
`coverity`, `coverity-defect-detectability`.

### 4. Read defaults and checker behaviour from the installation, not from memory

`doc/en/help/*.help.txt` (per-command, greppable, authoritative),
`doc/en/cov_checker_ref.html`, and
`doc/en/checker-enablement-and-option-defaults.html` are inside the
installation you pinned in rule 3. Defaults, option names, and checker
coverage move between releases; a remembered default is a guess wearing a
fact's clothing.

Source: verified — `coverity`, `coverity-defect-detectability`.

### 5. Configure every compiler-shaped executable the build invokes

Not just the C compiler: the C++ driver, the archiver, and the linker where
relevant. For cross builds, configure the *prefixed* names
(`arm-none-eabi-gcc`), not the host ones. Wrappers — `ccache`, `distcc`,
`sccache`, bespoke shell scripts — are what the build actually invokes, so
they must be configured or bypassed.

Repeated `cov-configure` calls against the same `--config` accumulate; each
adds an `<include>`.

Source: verified — `coverity-compiler-configuration`.

### 6. Regenerate a tainted configuration, never patch it — and replace the idir with it

Probed per-compiler configs remain on disk and continue to be included, and
data already captured under the bad configuration is already affected;
reconfiguring does not retroactively correct an existing intermediate
directory. Fresh config directory, fresh idir, re-capture. Mixing translation
units captured under different configurations makes the analysis input
unreproducible.

Source: verified — `coverity-compiler-configuration`.

### 7. `template-<name>-config-N` directories multiplying during a build is the mechanism working

New argument sets are being discovered and configured per-invocation, which is
the entire point of rule 1. Do not clean them up, and do not report them as a
fault.

Source: verified — `coverity-compiler-configuration`.

---

## Capture

### 8. Capture into a fresh intermediate directory

**A reused intermediate directory makes a broken capture look perfect** —
yesterday's translation units answer today's questions. If you must reason
about an idir you did not create, prove freshness first from `build-cwd.txt`,
`BUILD.metrics.xml`, and file timestamps before believing anything in it.

This is the exact counterpart of the build-fidelity trap where a capture that
emitted nothing yields binaries byte-identical to native.

Source: verified — `coverity`, `references/idir-anatomy.md`.

### 9. Make sure the build under capture actually builds

An incremental build with nothing to do, a warm compiler cache, or the wrong
target compiles nothing — and `cov-build` reports success over it. Clean
first, or otherwise establish that real compilation happened. "The build never
compiled those files at all" is, by a wide margin, the most common cause of a
capture hole — ahead of misconfiguration, which is the one people reach for.

**The partial build is the dangerous one, not the empty one.** Measured on
2026.6.0 against a five-source Makefile project, one fresh idir per run,
`--gcc` template config:

| Tree state | Build | Emitted | What `cov-build` said |
|---|---|---|---|
| fully built | `gmake` (no-op) | 0 of 5 | `[WARNING] No files were emitted…`, no percentage, exit 0 |
| `touch` one source | `gmake` | 1 of 5 | `Emitted 1 … (100%) successfully`, `1 … ready for analysis`, `The cov-build utility completed successfully.` |
| clean | `gmake` | 5 of 5 | `Emitted 5 … (100%) successfully` |

The middle row is the rule. Four fifths of the project is missing and every
headline number reads perfect, because **the percentage's denominator is what
the build attempted**, not what the project contains. `BUILD.metrics.xml`
agrees: `successes = 1`, `failures = 0`, `recoverable-errors = 0`. There is no
warning anywhere in the output. The fully vacuous build, by contrast, is
loud — so the failure mode people picture is the one Coverity already catches,
and the one it does not catch is the one they do not picture.

Nor does the empty case name what is missing: `coverity list --all` reported
`FILES CAPTURED: 0` with the five uncompiled sources folded into `IGNORED: 12`
alongside object files, and there is no option to enumerate the ignored set.
Only the three-method adjudication named them — `VACUOUS` (5/0/0, all five
listed) and `SHORTFALL` (5/1/1, the four missing listed), against a control
run that graded `CONSISTENT` (5/5/5).

Source: verified against 2026.6.0 — see
`references/worked-example-vacuous-capture.md`.

### 10. Never quote a bare capture percentage — report the triple

**expected / captured / analyzable**, plus a grade. Emitted, analyzable, and
analyzed are three different numbers, printed in three different places, and
routinely quoted as one another: `cov-build` prints both "Emitted N …
successfully" and "N … are ready for analysis" because they are not the same
count, and `idir/output/summary.txt` prints a third — what `cov-analyze`
actually consumed. A translation unit with no AST is present, counted, and not
analyzable.

Source: verified — `coverity`, `CALIBRATION.md`.

### 11. `< 100%` is a question, not a verdict — and 100% of nothing is still 100%

The denominator includes the build system's own throwaway compilations (CMake
`TryCompile`, `CompilerId`, configure tests). Measured: `cov-build` reported
"40 compilation units (97%)" on zlib, where the single failure was a
`TryCompile` probe and product capture was 100%. A naive `< 100% → fail` gate
rejects good builds; a `= 100% → pass` gate accepts empty ones. Reconcile
against *product* translation units, in both directions.

Source: verified — `coverity-build-fidelity`.

### 12. Always pass `--all` to `coverity list`

The default view hides `vendor`, `node_modules`, `__MACOSX`, and
dot-directories **unless they were captured**. The files most likely to be
silently skipped are exactly the ones the default view hides.

`coverity list` is also the right denominator for method A, because it walks
the *project directory* and can therefore see files that were never compiled —
which the emit database structurally cannot. It works against a plain
`cov-build` idir, not only a `coverity capture` one.

Source: verified (runs against a `cov-build` idir; output structure). The
hiding behaviour is documented but not yet reproduced against such a tree.

### 13. Use `cov-manage-emit list-capture-diagnostics` for per-TU truth

Undocumented, and the best programmatic source there is: per-translation-unit
`capture-percentage`, `had-failures`, `had-recoverable-errors`,
`had-abstract-syntax-trees`, `code-line-count`. `cov-manage-emit list-json`
likewise carries undocumented `isFailure`, `hadRecoverableErrors`, and
`astFidelityPercent`.

Being undocumented, these field names are version-specific — confirm them
against the installation you pinned in rule 3 rather than assuming they
survived an upgrade.

Source: verified against 2026.6.0 (`format_version: 4`) — `CALIBRATION.md`.

### 14. An empty `unconfigured-compilers` is a pass; a missing `scan-transparency/` is not

`cov-build` writes `<idir>/scan-transparency/unconfigured-compilers` after
"Attempting to detect unconfigured compilers in build". Anything named there
was invoked but not configured, and its translation units are missing from the
emit. An **empty** file is a real positive result. A **missing** directory
means the check did not run — which is not the same as passing, and must never
be reported as one.

**`scan-transparency/` is written at capture time, not by analysis.** Measured
on 2026.6.0: running `cov-analyze` over a `cov-build` idir, and `coverity
analyze` over a `coverity capture` idir, each left the directory byte-for-byte
unchanged. Do not wait for analysis before reading it, and do not attribute
its contents to the analyzer. Nothing needs to be committed to Coverity
Connect for the local folder to be populated — the Connect-side
`scan.transparency.enabled` property governs only what the *server* stores and
displays.

**Its richness depends on the capture path, so absence of a file is not
absence of a problem.** Also measured on 2026.6.0:

| Capture path | `scan-transparency/` contents |
|---|---|
| `cov-build` | `unconfigured-compilers` only |
| `coverity capture` (CLI) | `unconfigured-compilers` **and** `cli-ignored-files` |

`cli-ignored-files` lists project files the CLI knew about and did not
capture — on a deliberately incomplete build it correctly named the source the
build never compiled. A `cov-build` idir has no equivalent file, so on that
path this evidence must come from Method A instead.

**The rule does not run in reverse: a non-empty `unconfigured-compilers` is
not proof of a hole.** Measured on 2026.6.0, a `coverity capture --dir <idir>
-- gmake` that captured all three product sources — `capture-rate: 100`,
`succeeded: 3`, all three TUs present in the emit — nonetheless wrote
`<project-dir>\gcc` into `unconfigured-compilers`. **That path does not
exist**; it appears to come from resolving the bare command name `gcc` against
the project directory rather than `PATH`.

The same phantom appears on the `cov-build` path, and its trigger has been
isolated. Across four runs of one project on 2026.6.0: gcc invoked **by
`gmake`** produced `<build-cwd>\gcc` every time — including in a run that
captured 5 of 5 sources and in a compile-only run with no link step — while
`cov-build … gcc -c …` invoking the compiler *directly* left the file empty,
as did a build that compiled nothing at all. So the trigger is invocation
through a build tool that spawns the compiler by bare name, it is independent
of the capture path, and it fires on healthy captures. See
`references/worked-example-vacuous-capture.md`.

So before reporting an entry as a finding, **check whether the named path
exists on disk**. A phantom path is an artifact. A real path is a candidate
hole, and even then it should be confirmed against Method A — a
compiler-shaped binary that compiled nothing product-relevant is benign. This
is precisely the disagreement the three-method adjudication exists to resolve,
and treating Method B as decisive on its own would have failed a perfect
capture.

Source: verified against 2026.6.0 — both capture paths, before and after
analysis, including a clean CLI capture that produced a phantom entry; and
against a 2024.12.1 `cov-build` idir (proftpd), which likewise carried only
`unconfigured-compilers`. See `CALIBRATION.md`.

### 24. `coverity capture` runs buildless capture too — always pass the build command for C/C++

The CLI capture path runs **buildless capture after the build command**, so
the captured set is not simply "what the build compiled". Buildless capture
does **not** cover C, C++, Objective-C, or Visual Basic; those languages
require a real build command.

Pass one explicitly and do not rely on inference:

```bash
coverity capture --project-dir <src> --dir <idir> -- gmake
```

Measured on 2026.6.0, same three-source C project both ways:

| Invocation | Result |
|---|---|
| build command compiles all sources | `primary-capture-mode: Build`, `capture-rate: 100`, 3 TUs |
| build command compiles 1 of 2 sources | `SUCCEEDED: 13` — buildless backfill of *other* file types, while the uncompiled C source was simply missed and landed in `cli-ignored-files` |

The second row is the trap: **a healthy-looking `SUCCEEDED` count can coexist
with a completely missed C file**, because the number counts what buildless
capture picked up, not what your build failed to compile.

**Keep the intermediate directory outside the project directory.** Buildless
capture walks the project directory and will capture configuration files
belonging to an idir nested inside it — pure denominator inflation. With the
idir moved outside, `IGNORED: 5` was exactly the `Makefile`, `app.exe`, and
three `.o` files, all legitimately ignored.

Source: verified against 2026.6.0 — `CALIBRATION.md`.

### 25. On a CLI capture, read `output/cli-diagnostics.json`

The `coverity` CLI writes a machine-readable diagnostics file that no
`cov-build` capture produces. It is the single best provenance record in the
intermediate directory, and it sits in `output/`, **not** in
`scan-transparency/`.

Under `capture`: `primary-capture-mode` (`Build` vs buildless),
`capture-rate`, `capture-summary` (`files-captured`, `succeeded`, `ignored`,
`lines-of-code`), the **effective build command actually used**,
`project-directory`, `intermediate-directory`, `configuration-hash`, and
`command-info` — every command run, with its working directory.

`coverity analyze` **appends an `analysis` section** to the same file rather
than writing new scan-transparency data. So the CLI does record analysis-side
diagnostics; they are just not where the name "scan transparency" suggests.

**Security.** `command-info` embeds full environment blocks, including `PATH`,
in plain JSON. Check it before sending an intermediate directory to anyone,
support included. Same caution as `build-log.txt`.

Source: verified against 2026.6.0 — `CALIBRATION.md`.

### 15. Binary equivalence alone never proves capture worked

If the question is whether wrapping the build in `cov-build` perturbed the
product, run `coverity-build-fidelity` — and note that it requires **two
arms**, never one. A capture that emitted *nothing* produces binaries
byte-identical to native, which is the best-looking result a fidelity check
can return. Total capture failure and perfect fidelity have the same
signature, so binary equivalence is always paired with a capture-coverage
reconciliation (rule 2).

Source: verified — `coverity-build-fidelity`.

---

## Analysis

### 16. Locate where the pipeline narrowed before debating checkers

```
files in the tree
  -> files the build actually compiles         (build system decides)
  -> compilations Coverity intercepts          (compiler configuration decides)
  -> translation units emitted                 (cov-emit decides)
  -> TUs with a usable AST                     (parse success decides)
  -> functions analyzed                        (cov-analyze scope decides)
  -> defects reported                          (checkers and options decide)
```

Most "Coverity missed it" reports are a break in an early arrow being
diagnosed as a problem in the last one. Establish which arrow narrowed before
arguing about checkers; the capture-fidelity check measures the first four.

Source: verified structure — `coverity`.

### 17. Run it; do not reason about whether a checker "should" fire

Detectability questions are answered empirically — capture, analyze, escalate
only while the answer is still "not found", then minimize back to the smallest
setting that reports it. The deliverable is a verdict plus the exact command
line to reproduce it. Speculation about checker coverage is not an answer, and
it is wrong often enough to be worth the minutes.

Source: verified — `coverity-defect-detectability`.

### 18. Security (taint) checkers need two switches

Checker enablement **and** a `--distrust-*` source. Enabling the checker alone
produces a silent nothing. Note that stdin counts as *filesystem* taint.

Source: verified — `coverity-defect-detectability/references/escalation.md`.

### 19. Several defaults suppress reports in ways that look like misses

`RESOURCE_LEAK:allow_main`, `UNINIT:enable_write_context`, the statistical
checkers' `stat_threshold` (which needs a corpus, not a snippet), default-off
`STRING_OVERFLOW`, and others. Check the deliberate-suppression table before
concluding a checker cannot see a defect.

Source: verified — `coverity-defect-detectability/references/escalation.md`.

### 20. Never let capture doubt leak into a "not found" verdict

If the code did not capture cleanly, "Coverity did not report it" is
unsupported — the checker may never have seen the code. Prove the analyzer saw
the function before reporting a negative: plant a canary defect of a class
that is on by default, confirm it is reported, then remove it. A negative
verdict without that step is an assertion, not a result.

Source: verified — `coverity-defect-detectability/references/capture.md`.

---

## Reporting

### 21. Verdict first, then the evidence

Lead with the answer. Annotated traces, not tool dumps. Expressiveness on disk
(a `report.md` a person can act on, plus a machine-readable sidecar for
downstream inference); verdict in chat.

Source: project convention — `coverity`.

### 22. Say what you did not check

"Capture verified for the C/C++ product sources; the vendored `libfoo` was
prebuilt and never captured" is a useful, honest result. An unqualified green
check is not. These reports travel to people who were not in the room: state
scope limits explicitly, keep the register formal, and never let a green
result imply more than it measured.

Source: project convention — `coverity`.

### 23. Distinguish measured from reasoned, in the report and in this repo

A claim established by running the command and a claim derived from mechanism
are different kinds of thing, and readers make decisions on them. Mark which
is which. `CALIBRATION.md` is this project's instance of the same rule, and
every rule added here carries a `Source:` line for it.

Source: project convention.
