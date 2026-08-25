# Calibration status

This project's standard is that factual claims in a skill were established by
real runs. This file records where `coverity-recreate-from-emit` stands, so
that nothing unverified reads as measured.

Environment for everything marked verified: Windows 11 with Coverity
installations under `C:\Coverity\` (2021.9.0 through 2026.6.0, win64), WSL2
Ubuntu with `cov-analysis-linux64-2024.12.1`, `-2025.6.2`, `-2025.9.0`,
`-2025.12.2` and gcc 13.3.0. Subject idirs: two archived proftpd captures
(`C:\analysis\proftpd\idir1.3.8`, `idir1.3.9`), both written 2025-05-19 by
`cov-analysis-linux64-2024.12.1` under WSL, 90 TUs each at 100%, each carrying
a completed analysis from that same version. Session run 2026-08-24. All work
performed on copies.

Full narrative in `references/worked-example-proftpd.md`.

# Recreate -- analyzing an old emit with a new analyzer

## Verified by direct execution

- **A newer analyzer refuses an older emit, loudly.** `cov-manage-emit --dir
  <2024.12.1 idir> list` under 2026.6.0: *"Expected version number is 355, but
  this directory has version 343."* **Exit code 2**, no partial output. The
  true exit code was checked separately from the piped run, because `$?` after
  a pipe reports the last stage.
- **`<idir>/emit/version` identifies its own creator.** Line 1 is a comment
  naming the product version (`# Version file created with Prevent version
  2024.12.1`); line 2 is the emit format number.
- **The compatibility window is zero.** Ten win64 installs were swept against
  one idir; exactly one opened it, and every other reported a different
  expected format. Formats were strictly monotonic across releases, with two
  adjacent patch releases sharing one. *The specific numbers are deliberately
  not published as a table -- they go stale, and the procedure re-measures
  them in seconds.*
- **The compatibility key is the emit format, not the product version and not
  the platform.** win64 **2024.12.0** fully read an idir written by linux64
  **2024.12.1**: 90 TUs listed, matching the build log's `Emitted 90`. This is
  the single most useful operational finding in the skill.
- **A win64 tool reading a Linux emit renders paths with backslashes**
  (`\home\etice\proftpd\lib\pr_fnmatch.c`). Separators come from the reading
  tool, not the writing one.
- **`list-capture-invocations` structure**, on a 90-TU C capture (3.1 MB of
  JSON): `files` 413, `environment-variables` 68 in 5 blocks (sizes 29, 61,
  59, 59, 59), `cov-build-invocations` 1, `cov-translate-invocations` 90,
  `cov-emit-invocations` 90, `translation-units` 90, `link-units` 0,
  `metrics {tu-count: 90, tu-failures: 0, lu-count: 0, lu-failures: 0}`.
  `process-invocation` carries hostname, pid, start/end time, exit-code,
  platform, username, `command-line` (a real argv array),
  `working-directory-id`, `environment-variable-block-id`.
- **`translation-units[]` explicitly links the transformation pair** via
  `cov-translate-invocation-id` and `cov-emit-invocation-id`. The (input,
  output) correspondence is recorded, not inferred.
- **`input-files` is the full include closure** -- 222 entries, all
  `kind: "source file"`, for one C primary.
- **The recorded `cov-emit` line carries the resolved compiler model**:
  `--comp_ver 13.3.0`, `--gnu_version 130300`, `--type_sizes=e16Pdlx8fi4s2`,
  `--type_alignments`, `--size_t_type/--wchar_t_type/--ptrdiff_t_type`, four
  `--sys_include` paths, `-D` set including `-D__OPTIMIZE__`, and two
  `--pre_preinclude` compat headers located *inside the idir*.
- **`cov-translate --dryrun` prints the generated `cov-emit` line without
  running it**, and it matches a real run except for the per-session
  `--ignore_path` temp directory.
- **The control passes.** Re-running the recorded translate argv under the
  original 2024.12.1 reproduced the recorded `cov-emit` line exactly after
  normalization -- `IDENTITY` at **61 tokens** once the version-owned includes
  are transformed rather than dropped.
- **The one control residual was diagnosed, and it corrected the design.**
  `--preinclude <install>/config/template-gcc-config-0/../user_nodefs.h`
  first appeared on the recorded side only. Cause: the original build used the
  install's own config directory (`BUILD.metrics.xml` -> `<metric><name>config`),
  which ships `user_nodefs.h` (1440 bytes); a directory created by
  `cov-configure --config <newdir>` contains `coverity_config.xml`,
  `configure-log.txt` and eight `template-*-config-N` directories but **no**
  `user_nodefs.h`. The right handling is not to mask the token: the
  pre-includes and nodefs are owned by whichever product version is running and
  are always pulled from it, so the correct treatment is a **path transform**
  that keeps the token and rewrites its root. Masking would have hidden a
  genuine presence asymmetry.
- **`--coverity_config_md5` was identical** (`b577f776b05173caa21361c7ea6c1f1d`)
  between the May 2025 production build and the August 2026 regeneration, from
  two different config directories.
- **The `--c11` -> `--c17` delta is a Coverity bug fix, not a behaviour
  change.** gcc 13.3.0 with the recorded flags (no `-std=`) reports
  `__STDC_VERSION__ 201710L`; `-std=c11` reports `201112L`. C17 is the
  compiler's real default, so 2024.12.1's `--c11` mis-modelled gcc and
  2025.12.2 corrected it. Consequence for the procedure: a semantic delta must
  be adjudicated **against the compiler**, not between the two Coverity
  versions, and a correction is accepted rather than pinned -- pinning would
  reproduce a known-wrong parse. Such an error is invisible on builds that
  pass `-std=` explicitly, which is most of them.
- **Cross-version transformation delta, 2024.12.1 -> 2025.12.2: `--c11` ->
  `--c17`.** One token in sixty, reproduced identically on five pairs drawn
  from four different source directories (`lib/`, `src/`, `modules/`,
  `utils/`). Everything else identical after normalization.
- **`tools/emit_probe.py` end to end**, all six subcommands: `identify`
  (reproduced the manual ten-install sweep and named the compatible install),
  `extract` (90 pairs), `probe` (control and cross-version), `delta`
  (`IDENTITY` on the control, `DELTA` with a SEMANTIC classification on the
  cross-version arm), `replay` (licence warning fires on an unlicensed install
  while the replay still succeeds; rule-8 guard refuses a non-empty idir), and
  `reconcile` (`CONSISTENT`, 90/90/90, matching the hand reconciliation).

- **Replay end to end, and the analysis it produced.** All 90 recorded
  `cov-translate` invocations from `idir1.3.9` were re-run under
  `cov-analysis-linux64-2025.9.0` from their recorded working directories
  against the real sources: **90/90 rc=0, 90/90 emitted**, 135s under 2025.12.2
  and 114s under 2025.9.0. Reconciliation against the original inventory:
  **90 original / 90 replayed, 0 missing, 0 extra, 0 size mismatches, 0 TUs
  without ASTs, 0 `isFailure`, `astFidelityPercent` 100 throughout** -- graded
  `CONSISTENT`.
- **`cov-translate` writes nothing into the working directory** without
  `--run-compile`. Verified on a scratch directory: only `t.c` before and
  after. Replay is therefore non-mutating and can run in place against the
  original source tree, which preserves the recorded paths exactly.
- **The source-identity gate works.** All 90 primary sources were present on
  disk with byte-exact `primaryFileSizeInBytes` matches, 15 months after
  capture. This is the replacement for the `primaryFileHash` gate below.
- **The transformation delta is version-pair-specific, not monotonic.**
  2024.12.1 -> 2025.9.0 is `IDENTITY` (61 tokens, three pairs); 2024.12.1 ->
  2025.12.2 is the `--c11` -> `--c17` delta. The drift enters between 2025.9.0
  and 2025.12.2. **You cannot predict which pair drifts -- probe the one you
  have.**
- **The version-owned includes are a path transform, not a mask.** With
  `user_nodefs.h` seeded from the install being probed, recorded and
  regenerated lines match at **61 tokens including `--preinclude`**, rather
  than 59 with the token dropped. Confirmed by construction: adding
  `user_nodefs.h` to a probe config directory made the `--preinclude`
  reappear. The 2024.12.1, 2025.9.0 and 2025.12.2 installs ship byte-identical
  stock copies (`fc2bb8f0...`), so it was not a semantic variable here -- but
  it is user-modifiable and would be.
- **Analysis can run on a different platform from the replay.** The idir
  emitted by linux64 2025.9.0 under WSL (format 350) was analyzed by **win64
  2025.9.0** with rc=0. Corroborates the format-not-platform finding, and it is
  what made the run possible at all (see the licence entry).
- **Capture does not need a licence; `cov-analyze` does.** All 90 TUs replayed
  successfully under two installs whose licences were absent or expired. The
  failure appears only at analysis: `[FATAL] No license files ... found`
  (rc=**47**) with none present, and `[FATAL] License authorization failure:
  License has expired.` (rc=**2**) with an expired one. A replay can therefore
  look completely healthy and still be unanalyzable.

### The replayed idir analyzes cleanly

Proof that the replay produced something a newer analyzer actually consumes,
and that it consumed the *same* code. `cov-analyze` under win64 2025.9.0,
rc=0, against the archived 2024.12.1 analysis of the same idir:

| | original (2024.12.1) | replayed (2025.9.0) |
|---|---|---|
| Files analyzed | 149 | 149 |
| Functions analyzed | 2086 | 2086 |
| Classes/structs | 159 | 159 |
| Total LoC input | 98481 | 98488 |
| Defect occurrences | 92 | 145 |

**The structural denominators are identical** -- same files, same functions,
same classes. That is this skill's deliverable: evidence that the replayed
idir corresponds to the same code as the original, so a downstream comparison
is licensed. **LoC differs by 7** with files and functions equal, which is
unexplained and stays on the queue rather than being waved off.

The defect count moved 92 -> 145. **Attributing that movement is not this
skill's job** -- it belongs to `coverity-issue-transition-inference`, which
consumes exactly this artifact. Recorded here only as evidence that the
replayed idir analyzes, not as a finding about the analyzer.

## Measured negative result: `primaryFileHash` is not a source-identity gate

The stub this skill grew from proposed using `primaryFileHash` as an MD5
proving that a source file matches what the idir captured. **It does not work.**

- `lib/pr_fnmatch.c` carries identical `primaryFilename`,
  `primaryFileSizeInBytes` (13692) and `last-modified`
  (`2025-05-19T20:04:11+0000`) in both idirs, and **different**
  `primaryFileHash` (`1da77d10...` vs `bb0d38df...`).
- Tested against the real file bytes: `md5`, `sha1[:32]`, `sha256[:32]`,
  `md5(path+content)`, `md5(content+path)`, `md5(path)`, and CRLF/LF
  normalizations. None reproduced either recorded value.
- Not mtime-derived: 57 of 90 files differ in `last-modified` while 86 of 90
  differ in hash; the sets are not equal.

What holds up instead: `primaryFileSizeInBytes` matches disk exactly,
`code-line-count` is recorded per file, and `input-files` enumerates the
include closure.

**The construction of `primaryFileHash` is unknown.** Until it is pinned, do
not use it to argue that two idirs captured the same source, and do not use it
against a file on disk at all.

## Sizing the analysis host: stated by the user, not measured here

Recorded because the natural instinct -- "a huge C++ codebase needs a huge
machine" -- is wrong, and acting on it would send users shopping for hardware
they do not need. Attributed, not measured: this came from the user during the
Chromium exercise on 2026-08-25 and is **not** yet backed by a run of mine.

- `cov-analyze` is built to fit a **small** memory footprint. It ran on 32-bit
  operating systems, where 2GB was the entire addressable space.
- The working rule of thumb: **~1GB of overhead** on a 64-bit platform, plus
  **~0.5GB per core**. So an 8-core analysis lands near **5GB**, and will not
  approach 16GB.
- Under memory pressure the analysis **reduces its own parallelism** rather
  than failing or swapping. Memory is a throughput input, not a correctness
  cliff.
- Reference point offered for scale: the **Linux kernel analyzes in about ten
  minutes** on this hardware.

Consequence for this skill: **do not treat RAM as the binding constraint** on
whether a large C++ project can be analyzed, and do not tell a user their box
is too small. The binding constraint is cores and wall-clock.

**Correction, same day.** An earlier draft of this section said "if analysis is
cheap". That was my paraphrase and it was wrong twice over, so it is recorded
here rather than quietly deleted:

1. The user's claim was that analysis is **incremental**, not that it is cheap.
   A *first* analysis of a large C++ codebase is not cheap. A *re-analysis* of
   an idir that already carries analysis state is much faster, because
   `cov-analyze` caches per-function results and re-does only what changed.
   Those are different claims and only the second one was made.
2. The draft then said this "cuts against the case for idir reuse". It does the
   opposite. Reuse exists to avoid re-**capture**; cheap re-analysis
   does not compete with that, it means the capture saving is the *whole*
   saving rather than being diluted.

The load-bearing point is about **capture, not analysis**: capture time is
routinely the long pole, and it is worst in the naive CI pattern of a **clean
build and full rebuild** performed solely to guarantee the idir is current.
That is the cost reuse removes. It also follows that for a **smaller** project,
idir reuse plus judicious rebuild minimization is frequently *more than fast
enough* on its own -- reaching for anything more elaborate is premature.

Still to measure: peak RSS of a real `cov-analyze` on a C++ codebase at
Chromium scale; whether the per-core figure holds at 16 cores; and **the
re-analysis speedup itself**, which the skill asserts in two places
(`idir-reuse.md` lines 30 and 522) but has never quantified.

## TLS interception: measured, 2026-08-25, during the Chromium setup

Found by hitting it, not by anticipating it. Every claim below is from a run on
this box, which sits behind a **Zscaler** inspecting proxy.

- **Interception is selective.** Same machine, same minute, default trust store:
  `github.com` returned **200** while `chromium.googlesource.com` failed. So
  "the network is fine" and "TLS is fine" both look true while one host is dead.
- **Go ignores `CURL_CA_BUNDLE`.** With curl and git fixed and both working,
  depot_tools' `fetch` still hung: `fetch.py` blocked on `anon_pipe_read`,
  **empty output directory, nothing on stderr, for 13 minutes**. The child was
  cipd (a Go binary) failing a handshake. Proof, same host, one variable:

  ```
  cipd host, SYSTEM trust store  -> http=000
  cipd host, SCOPED bundle       -> http=200
  ```

  `SSL_CERT_FILE` fixes it; after setting it, the fetch bootstrapped vpython and
  reached `gclient sync`.
- **Coverity ships its own JDKs, and they are a separate store.**
  `cov-analysis-linux64-2025.12.2` carries **three** (`jre/`, `jdk21/`,
  `jdk25/`), each `lib/security/cacerts` holding **109 trusted certs and zero**
  Zscaler entries. The system `cacerts` had zero as well.
- **A Coverity JVM therefore fails an intercepted host**, measured directly with
  `HttpsURLConnection` under `jdk21/bin/java`:
  `SSLHandshakeException: (certificate_unknown) PKIX path building failed`
  for googlesource, `OK ... http=200` for github in the same run.
- **Both fixes verified.** Copying the bundled `cacerts`, importing the root
  with `keytool`, then either `-Djavax.net.ssl.trustStore=...` **or**
  `JAVA_TOOL_OPTIONS=...` turned that same call into `http=200`.
  `JAVA_TOOL_OPTIONS` is preferred: it needs no change to any Coverity command
  line and no edit to the install. It emits one `Picked up JAVA_TOOL_OPTIONS:`
  line on stderr.

Written up as `references/corporate-tls.md`, linked from Step 0.

**Not yet measured:** whether Coverity Connect traffic on this network is
actually intercepted. The local Connect is an **internal** address and proxies
commonly bypass those, so the JVM gap may be latent rather than active here.
The store contents and the handshake failure are measured; *that Connect
specifically breaks* is not, and the skill does not claim it.

## Not yet calibrated -- the priority queue

1. ~~**Replay end to end.**~~ **DONE** -- see above. 90/90 replayed,
   reconciled `CONSISTENT`, analyzed clean, and the defect delta attributed.
   What remains unexercised is the *failure* side: every reconciliation so far
   has been perfect, so the shortfall path has never fired (item 5).
2. ~~**The degraded path.**~~ **DESCOPED, deliberately.** Whether a newer
   `cov-emit` accepts an older version's flag set verbatim is still unmeasured,
   and stays that way. The skill solves "the build cannot be run repeatably";
   "the toolchain no longer exists" is a different and much harder class, and
   usually a non-problem because the compiler is open source and obtainable.

   The idir carries enough to identify what to fetch. Measured on `idir_pA`'s
   `build-log.txt`: `/usr/bin/x86_64-linux-gnu-gcc-13` and
   `/usr/libexec/gcc/x86_64-linux-gnu/13/cc1` give vendor, target triple and
   major version, and `13.3.0` appears 110 times. With `--comp_ver` from the
   recorded emit line that is an install command, not a research project.

   The resolution is therefore **obtain the compiler**, never reverse-engineer
   Coverity's model of it -- which also preserves the control run, without
   which nothing downstream can be graded.
3. **C++ and other argument sets.** Only a C argument set was probed.
   `--c11`/`--c17` is a C-mode flag; the `g++` arm is a separate template
   config and may drift differently. Also untested: `-m32`, mixed `-std`, and
   cross-compilers.
4. **Delta growth with version distance.** One version pair was measured.
   Whether deltas accumulate across larger gaps (2021.9 -> 2026.6) is unknown.
5. **Reconciliation behaviour.** The Step 7 shortfall path has never fired,
   so the claim that an incomplete replay is silent is reasoned from the
   vacuous-capture measurement in `coverity`, not measured here.
6. **`primaryFileHash` construction** -- see above. Candidate approaches:
   diff two idirs built from a deliberately unchanged tree, and one where a
   single byte changes in one header.
7. **The 7-LoC difference.** Same files, same functions, same classes, but
   `Total LoC input to cov-analyze` moved 98481 -> 98488. Almost certainly a
   counting change in the newer front end -- but "almost certainly" is not this
   project's standard.
8. **Licence as a precondition.** Replay needs none; analysis does. The skill
   discovers this at the *last* step, after minutes of replay. Worth a
   pre-flight check on the new-side install.
9. **Non-gcc toolchains.** MSVC records a different compiler model; the
   normalization set was derived from gcc output only and may be incomplete
   (for example, MSVC-specific temp or response-file handling).

This skill now **measures the transformation reliably and has completed a
verified replay end to end** -- on one project, one language, one version pair,
with the original compiler still available. The degraded path (item 2) and
every failure mode (item 5) remain unmeasured. Say so if it matters.

## The coverity.yaml prerequisite

- **`coverity.yaml` / `.yml` / `.json` is the Coverity CLI's own config**, and
  its documented default lookup is those three names under the project
  directory. `commit.connect.stream` and `commit.connect.url` are **both
  required** by the published schema, so "properly formed" is the product's
  definition.
- **Adding our own top-level key to it is tolerated but noisy.** A key the CLI
  does not know produces *"'idirBaseline' is not a recognized setting"* and
  `[WARN] ... has issues which may need to be addressed` -- on **rc=0**, so it
  does not break anything, but every CLI invocation in the project would print
  it. Reason enough not to extend the file.
- **The CLI's own tolerance for a bad config, measured on 2025.9.0:**

  | config state | result |
  |---|---|
  | malformed YAML | rc=**1**, `[ERROR] Failed to parse the configuration file.` |
  | valid YAML, unknown key or missing required section | rc=**0** + `[WARN]` |

  So the CLI hard-refuses a parse failure but only warns about a config that
  parses and names no stream. Our gate is deliberately stricter there: that
  file would otherwise fail later, at whichever command first needs the stream.
- **`connect.auth-key-file` defaults to `$HOME/.coverity/ak-<hostname>-<port>`**
  (documented), so on a developer machine the auth key generally need not be
  asked for.

## The estimator against a real snapshot history

24 snapshots across five proftpd release-line streams on a local Connect, each
run captured into a clean intermediate directory. The first real distribution
the estimator has seen, and it corrected the design.

| stream | snapshots | capture range | spread |
|---|---|---|---|
| proftpd-1.3.5 | 5 | 4m22 - 7m10 | 1.6x |
| proftpd-1.3.6 | 6 | 4m06 - 7m30 | 1.8x |
| **proftpd-1.3.7** | **7** | **5m48 - 20m26** | **3.5x** |
| proftpd-1.3.8 | 5 | 4m03 - 4m34 | 1.1x |
| proftpd-1.3.9 | 1 | - | - |

TU counts are constant within each stream (88 / 94 / 103 / 90), so the spread
is not the codebase growing.

**A single figure was not honest, and the first version reported one.** On
1.3.7 the median-of-all came to 8m 55s while the most recent run took 16m 31s
-- an understatement in exactly the direction that talks somebody out of
optimising. Three of the four multi-snapshot streams are well behaved, so this
is not a universal drift; it is one stream with genuinely high variance.

**MAD was right to drop nothing there.** With values 348/358/369/535/1226/665/957
the modified z-score of 1226 is 2.63, inside the 3.5 threshold. Those are not
outliers to discard, they are real runs that differed. The filter was working;
the *summary* was wrong.

The estimator now reports median, most-recent, and the full range with its
ratio, and when capture time varies >= 2x it says so plainly and quotes **the
worse of median and most-recent**. Verified both ways: 1.3.7 now recommends
against a 16m 31s figure rather than 9m 32s, while 1.3.8 (1.1x) is unchanged
at 4m 54s and prints no variance warning.

This is also the first evidence for the recommendation thresholds themselves:
at 4-7 minutes the honest answer really is "capture fresh", which is what four
of five streams produce.

## Orphan repair, validated on a real deletion

The staleness check found `libavcodec/x86/snowdsp.c` orphaned in an FFmpeg idir
updated from `n8.2-dev` to master. Repairing it:

1. `cov-manage-emit --dir <idir> --tu 1887 delete` -> 2060 TUs became 2059.
2. The staleness check then graded **CURRENT**, 2059/2059 OK, zero orphans.
3. Full `--force` re-analysis: 2809 files (was 2810), **26997 functions (was
   27011)**, 1211 defects (was 1212).
4. Defect sets compared: **935 sites -> 934, 1212 records -> 1211. Exactly one
   disappearance -- the orphan's own DEADCODE -- and zero appearances.**

Removal subtracts cleanly. Nothing else in the analysis moved.

Note the function count: the orphan defined **14** functions, not one. A single
orphaned TU can withdraw a good deal from the analyzable set.

### The boundary case this happened to be

The deletion was not an ordinary one. Upstream replaced the C intrinsics with
**assembly** (`snowdsp.asm`, `cglobal snow_inner_add_yblock`) *and* relocated
the init function to a new file. So in the un-repaired idir:

- `ff_dwt_init_x86` was defined **twice** -- stale, at `snowdsp.c:881`, and
  live, at `snowdsp_init.c:332` (TU 2058, a file that exists)
- and it is actively called, from `snow_dwt.c:858`

That is worse than a plain orphan: a stale duplicate definition of a live,
called function, where nothing in the idir makes it obvious which model a
caller was analyzed against. It was also worth testing because `.c` replaced by
`.asm` moves a function out of Coverity's analyzable world entirely, rather
than to another `.c`.

**It still subtracted cleanly** -- the six `NEGATIVE_RETURNS` in `snow_dwt.c`
and the `OVERFLOW_BEFORE_WIDEN` in `snowenc.c` were unchanged. So Coverity's
handling of TU deletion is robust even against a duplicated, actively-called
symbol. Good news, and measured rather than assumed.

## Model provenance: callgraph-metrics

- **`output/callgraph-metrics.json.gz` records where every function model came
  from.** One JSON object with `functions[]`, each carrying `mangledName`,
  `identifier`, `ownerClassIdentifier`, `file`, `line`, `hasImplementation`,
  `models` and `importance`. On the FFmpeg run: 27668 entries, `models` taking
  only two values -- implementation (26997) and built-in (214) -- across 2281
  distinct source files.
- **The implementation count equals `Functions analyzed` in `summary.txt`
  exactly** (26997 both), so the file is a complete account of what was
  modelled and from where.
- **It exposes ghost models that file-level checks understate.** Before
  repairing one orphaned TU, **11 function implementations** were sourced from
  the deleted `libavcodec/x86/snowdsp.c`; after deletion, zero. The file-level
  staleness view showed the same problem as a single orphan -- an
  eleven-to-one difference in what was actually affected.
- **This is the check that catches a stale duplicate of a live symbol.**
  `ff_dwt_init_x86` appeared live at `snowdsp_init.c:332` and stale at the
  deleted `snowdsp.c:881`. A ghost model is handed to every *caller*, so it can
  perturb files that are entirely current.
- `tools/model_provenance.py` implements it, run after analysis as the
  complement to the pre-analysis staleness check. Root inference anchors on the
  most-referenced source and walks its ancestors; `commonprefix` is useless
  because model sources mix the project root with system headers, making the
  common prefix `/`. Sources outside the root (10 functions in the measured
  run) are checked at their own absolute path rather than remapped. Verified
  GHOST MODELS before repair, SOUND after.
- **Correction:** an earlier claim in this repo that the idir does not show
  which model a caller received was wrong. It does, at function granularity.

## The preview report, and its side effects

- **`previewCommit` is a distinct Connect permission** from `commitToStream`
  (`/api/v2/permissions` lists "Preview Commit" and "Commit to a stream"
  separately), so preview can be granted without snapshot-commit rights.
- **It works from an imported idir with foreign paths.** `cov-commit-defects
  --preview-report-v3` against an idir whose primaries are `/tmp/pA/...`, on a
  stream whose captures came from entirely different roots: **rc=0 in 2
  seconds**, 146 KB report. Intermediate directories are self-contained for
  this; a failure here would be a bug, not a limit.
- **Attribution is exact.** proftpd 1.3.9 clean -> 111 issues, every one
  `presentInComparisonSnapshot: true`, `firstDetectedDateTime` values as old as
  2017-04-10 from the backdated corpus. The same tree with one planted
  `FORWARD_NULL` -> **112 issues: 111 true, 1 false**, and the false one is the
  planted defect in `/tmp/pB/lib/sstrncpy.c`, function `sstrncpy`.
- **Per-issue payload:** `cid`, `mergeKey`, `presentInComparisonSnapshot`,
  `firstDetectedDateTime`, `triage` (severity, owner, classification, action,
  fixTarget, legacy), `customTriage`, `ownerLdapServerName`. `analysisInfo`
  carries the chosen `comparisonSnapshotId` and `ownerAssignmentRule`.
- **It is NOT side-effect-free, and an earlier claim in this repo that it was
  is retracted.** No snapshot is created (the next snapshot id 404s), but
  running the same preview twice returned **identical CIDs for all 112 merge
  keys**, and the newly-seen defect kept `cid=10223` *and* its original
  `firstDetectedDateTime` across both runs. The merge-key -> CID mapping and
  the first-detection timestamp are allocated by the preview and persist.
- **Therefore first-detected is set by whoever previews first**, not by the CI
  commit -- a real consequence for anyone reporting defect age. And test
  previews leave CIDs behind; they are invisible to snapshot-scoped queries
  (there is no snapshot) but permanent. Explore against a scratch stream.

## Connect interfaces, measured on two independent servers

- **`GET /api/v2/snapshots/<id>` is REST and returns clean JSON** -- timings,
  TU counts, command lines, hosts, analyzer version, `sourceVersion`.
- **Listing a stream's snapshots has no working REST form found.** The
  documented `/api/v2/streams/stream/snapshots` returns **400** (route exists,
  parameter wrong) for `name`, `stream`, `streamId`, `streamName`, `id`, with
  and without `locale`; `/api/v2/streams/<name>/snapshots` returns 404. SOAP
  `getSnapshotsForStream` works and is the stopgap. Reproduced on a local
  2025.12 Connect and on a hosted field-test server.
- **Swagger is not reachable with an auth key.** `/swagger/cim/index.html` and
  every spec path tried return **403 whose body is the sign-in page**
  ("JavaScript and Cookies are Required") under basic auth on both servers. A
  form login yielded a `JSESSIONID` but no access. It wants a browser session.
- **Snapshot records carry no lines-of-code and no defect counts.**
  `getSnapshotInformation` has `buildTime`, `analysisTime`,
  `buildSuccessCount`, `buildFailureCount`, commands, hosts, versions and
  `enabledCheckers` -- but neither LOC nor new/fixed/existing. Those live
  elsewhere and are not needed for a time estimate.
- **Enumerating streams to find history does not scale.** A SOAP sweep of 200
  streams on the hosted server exceeded 10 minutes. Take the stream from
  `coverity.yaml` instead of discovering it.

# Reuse -- an existing idir, brought up to date for speed

Environment: the same Coverity 2025.9.0 pair (linux64 in WSL for capture,
win64 for analysis). Two subjects, deliberately chosen to fail and pass the
applicability gate: **proftpd** (hand-written recursive make, two checkouts at
`/tmp/pA` and `/tmp/pB`) and a purpose-built **CMake + make** project
(`/tmp/cA`, `/tmp/cB`; four TUs, one shared header included by three of them).

### Verified by direct execution

- **Gate 1, both outcomes measured.** Touch a header, capture the incremental
  build, compare against the TUs the idir says include it:

  | build system | idir says | build recompiled | verdict |
  |---|---|---|---|
  | CMake + make (emits `.o.d`) | 3 | **3**, exactly those three | applies |
  | proftpd hand-written make | 71 | **0** | does not apply |

  On the failing case `cov-build` printed `[WARNING] No files were emitted`.
  `main.c`, which does not include the header, was correctly excluded on the
  passing case.
- **`cov-manage-emit` surgical sub-commands**, all exercised: `reset-host-name`
  (silent no-op on the same host), `--tu <id> delete` (90 -> 89, TU gone),
  `--tu-pattern 'file(...)'` / `'header(...)'`, `print-compilation-info
  --detailed` (prints the cov-emit line, the compiler line, the cov-build line
  and the **working directory** for each), and `add <int_dir>` (*"Successfully
  merged in 3 TUs"*).
- **`delete` is real but absent from the synopsis** -- it appears only in
  the sub-command body ("Delete all TUs that satisfy the specified translation
  unit filter") and requires a `--tu` / `--tu-pattern` filter.
- **The fast path reproduces a full recapture exactly.** proftpd, one changed
  primary TU (`lib/sstrncpy.c`, planted FORWARD_NULL). Reference idir copied,
  TU 2 deleted, re-emitted from `/tmp/pB/lib`:

  ```
  105 distinct defect sites, 155 records
  in oracle only  : 0
  in surgical only: 0
  IDENTICAL after path normalisation
  ```
  with the planted defect present in both. Reference (no defect) 145 defects;
  oracle and surgical both 146.
- **Only three tokens needed rewriting** on that path -- `--dir=` and the two
  `--pre_preinclude` compat-header paths. The source argument (`lastlog.c`) and
  the includes (`-I..`, `-I../include`) are relative, so they follow from the
  new working directory.
- **`cov-translate` writes nothing into the working directory** without
  `--run-compile`, so the fast path can run in place against the developer's
  tree without touching it.
- **Stale TUs are analyzed, and they resurrect fixed defects.** CMake project,
  reference containing an array overrun that the working copy **fixes**:

  | idir | defects | files analyzed | reported in |
  |---|---|---|---|
  | reference (unfixed) | 1 | 4 | `/tmp/cA/src/alpha.c` |
  | transplant **without** deleting | **1** | **5** | **`/tmp/cA/src/alpha.c`** |
  | delete, then transplant | **0** | 4 | -- |

  Nothing errors; the count is plausible; the answer is wrong in the
  time-wasting direction. Two TUs at different absolute paths are different
  primary source files, so `--one-tu-per-psf` does not deduplicate them -- an
  earlier header-change run analyzed **7 TUs in a 4-TU project** for the same
  reason.
- **The build-recording path matches its oracle.** Header-only change
  (`SHARED_CAP` 16 -> 64, overrunning a fixed `buf[16]` in `beta.c` without
  touching `beta.c`): delta capture emitted exactly the 3 dependent TUs;
  delete-then-`add` produced 4 files analyzed and the same single OVERRUN in
  the same file as a full clean capture.
- **`cov-analyze` is incremental by default**; `--force` disables it. After a
  fast-path swap on an idir that already carried a completed analysis, both
  the default and `--force` returned 146 and reported the planted defect --
  the swap was noticed. One version, one data point.
- **Rule 5 reproduced incidentally.** CMake selected `/usr/bin/cc`, absent from
  a `--gcc` template config, so the first calibration build emitted nothing and
  `unconfigured-compilers` named `/usr/bin/x86_64-linux-gnu-gcc-13` and `cc1`.
  Adding `--template --compiler cc --comptype gcc` fixed it.

### Timing, measured on FFmpeg

The premise of reuse is speed, so it needed a subject where speed is visible.
**FFmpeg**, 16 cores, `cov-analysis-linux64-2025.9.0` capturing under WSL and
`win64 2025.9.0` analyzing (the Linux licences on this machine are expired).
Configured `--disable-x86asm --disable-doc --disable-programs`; **2053
translation units**, 2798 files and ~27000 functions analyzed.

Chosen because its build tracks header dependencies properly (`DEPFLAGS`,
`-include $(OBJS:.o=.d)`), so it passes gate 1 by construction.

| scenario | capture | analyze | total | vs cold |
|---|---|---|---|---|
| **cold** -- full capture, fresh idir, no cache | 373s | 794s | **1167s** | 1x |
| **worst case** -- release tag -> master, 2 months, 99% of TUs re-emitted | 344s | 407s | **751s** | **1.55x** |
| **realistic** -- current idir + 3 locally edited `.c` files | **8s** | **78s** | **86s** | **13.6x** |

Three things this establishes.

**The saving is in analysis, not capture.** In the worst case the capture
barely moved (344s vs 373s) because `config.h` changed and forced 2027 of 2053
TUs to recompile -- and the run *still* came in 36% faster overall, entirely
from the analysis phase halving. That is the file-granularity vs
function-granularity gap doing the work: nearly every file was re-emitted, but
the functions inside them were unchanged, so the per-function cache hit.

**The realistic case is an order of magnitude.** Three edited files: capture
dropped from 373s to **8s**, and analysis from 794s to **78s**. 19.5 minutes
becomes 1.4 minutes. This is the post-merge-CI-artifact scenario the technique
is actually for.

**Even the worst case is worth doing, but only just.** A tag-to-master jump is
the "essentially a recapture" case -- 875 changed files, 506 `.c` -- and it
still returned 1.55x. The break-even is further out than the recompile count
suggests, precisely because the recompile count is the wrong thing to measure.

**Correctness: the incremental result is identical to a full one.** The
speed number is only worth having if the answer matches, so the updated idir
was copied and re-analyzed with `--force` (full re-analysis of *identical* emit
content):

| | wall | files | functions | defects |
|---|---|---|---|---|
| incremental (reused idir) | **78s** | 2810 | 27011 | 1212 |
| `--force` (same emit, no cache) | **734s** | 2810 | 27011 | 1212 |

Comparing the defect records themselves, keyed on checker + file + function +
line: **935 distinct sites, 1212 records, and zero differences in either
direction.** All three planted `OVERRUN`s appear in both. So the analysis phase
alone is **9.4x faster for an identical answer**.

(A first attempt at this comparison keyed on a `<mergeKey>` element that does
not exist in `*.errors.xml`, so it compared two empty sets and reported
"IDENTICAL" -- a reminder that an oracle which finds nothing agrees with
everything. The real schema is `<error>` records carrying `checker`, `file`,
`function` and per-event `line`.)

Further signals from the fast run: functions analyzed went 27008 -> 27011
(+3, the three probe functions) and defects 1209 -> 1212 (+3), and none of the
probes appeared in the prior analysis.

**A capture can succeed on a compile that failed.** The probe functions
planted for this run had no prototypes, and FFmpeg builds with
`-Werror=missing-prototypes`, so `gcc` rejected `libavformat/id3v2.o` and
`make -j16` aborted. `cov-build` nonetheless reported *"Emitted 3 C/C++
compilation units (100%) successfully"* -- **`cov-emit` parses independently of
the compiler's warnings-as-errors settings**, so the emit was complete while
the build was not. `cov-build` did flag it: *"[WARNING] Build command make -j16
exited with code 2. Please verify that the build completed successfully."*

This is rule 9 inverted -- the usual trap is a build that succeeds while
capturing nothing; here capture succeeded while the build broke. Both matter,
and both are caught only by reading `cov-build`'s exit-code warning rather than
its percentage. The delta-capture timing above is unaffected (all three target
TUs were emitted before make stopped), but the run was not green, and a clean
re-run is on the queue.

**Also measured incidentally:** capturing into a preserved idir at the *same
paths* **supersedes** per primary source file rather than accumulating. 2053
TUs, re-captured over 2027 recompiles plus 7 new files, came out at **2060**,
with `--tus-per-psf=latest` equal to the total. Duplicate accumulation is a
path-divergence problem only.

### The staleness check, and a real orphan it caught

A pre-analysis check was built and exercised, on the principle that
correctness must come from *detection* rather than from the fetch policy being
right. Invariant: every TU's primary source file is present on disk and its
size matches the emit. **Presence is the test, not git tracking** -- an
untracked new file is ordinary work in progress.

Four cases, all behaving correctly:

| case | result |
|---|---|
| idir matches the tree | `CURRENT`, 4/4 OK |
| source file deleted from the tree | `ORPHAN` named, verdict STALE |
| source edited but not rebuilt | `STALE` named (emitted 136, disk 170) |
| new **untracked** source, captured | `CURRENT` + informational note |

**And it found a real one.** Updating the FFmpeg `n8.2-dev` idir to master left
`libavcodec/x86/snowdsp.c` in the emit (41150 bytes) with no file on disk --
deleted upstream in commit `5c830fccf4`. Three `.c` files were deleted across
that two-month range; one had been captured. **It contributed a DEADCODE
finding** to both the warm and the local-edit analyses.

**Correction to the timing section above.** Those runs therefore included one
phantom finding from a file that does not exist at master, so the absolute
counts (1209, 1212) are each one too high. The *comparison* is unaffected --
incremental and `--force` ran over the same emit and agreed exactly -- and the
timings are unaffected. But the numbers were reported before this check
existed, and they were not clean.

This is also the strongest available argument for the check being mandatory
rather than advisory: it was written to guard a hypothetical, and the first
real project it ran against was already wrong.

### Not yet calibrated -- reuse queue

1. **Gate 2 verification has not been exercised.** Insisting on a git tag and
   checking it via `primaryFileSizeInBytes` against `git show <tag>:<path>` is
   reasoned from the part-A measurement that those sizes match disk exactly;
   the check itself has not been run against a mismatched tag.
2. ~~**No timing measured.**~~ **DONE** -- see the FFmpeg table above: 13.6x on
   the realistic case, 1.55x on the worst case. What is still missing is a
   subject that takes *hours* rather than twenty minutes, and any non-gcc
   toolchain.
3. **Only same-host, same-version reuse.** `reset-host-name` was a no-op every
   time; a genuinely foreign idir has not been tried.
4. **Iteration has not been tested.** Re-deriving the delta from the tag on a
   second and third round, including a file changed and then reverted, is
   reasoned, not measured.
5. **C only, and only two build systems.** MSBuild and ninja are asserted to
   pass gate 1 on reputation, not measurement.
6. **Re-run the FFmpeg realistic arm on a green build.** The planted probes
   tripped `-Werror=missing-prototypes`, so `make` returned 2 even though all
   three TUs were captured. The timing stands but the run was not clean; add
   prototypes and repeat.
7. ~~**No deletions or renames.**~~ **DONE.** Deletion detected on a real
   project and the repair validated. **Renames need no separate work** -- a
   rename is a delete plus an add, both already covered, and nothing needs to
   relate the halves. An earlier note here claiming otherwise conflated the
   emit layer with the attribution layer, where a rename *can* look like
   fixed-plus-new; that continuity is Connect's job via antecedent merge keys
   (rule 27). The only cost of a large move is re-emit time.
