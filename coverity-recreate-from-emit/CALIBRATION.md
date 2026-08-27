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

## Model provenance is keyed to the TU, not the file -- and the tool gets it wrong

Measured 2026-08-25 on the preserved FFmpeg idir. This both **retracts** an
earlier claim of mine and identifies a real defect in
`tools/model_provenance.py`.

**What I claimed, and retract.** Reading `output/callgraph-metrics.json.gz`, I
found 205 of 2,252 distinct `file` values were headers and wrote that "Coverity
attributes the model to the header." That was wrong. `file` is the location of
the source *text*, not the attribution.

**What the data actually shows.** The user proposed that the real association is
to the primary source file (PSF), with the header shown as a convenience, and
that `--enable-callgraph-metrics` would expose it. Both were correct.

- The flag adds **no fields to the JSON**. It writes `callgraph-metrics.csv`
  and `callgraph-metrics.txt`, and the CSV carries a **`TU`** column.
- The text form is unambiguous:
  `static inline uint32_t av_bswap32(uint32_t): implemented in TU 931` --
  the same function whose JSON `file` is `libavutil/bswap.h`.
- Cross-checked against `cov-manage-emit list-json`:

  ```
  distinct implementing TUs      : 1989
  TUs in emit                    : 2060
  implementing TUs found in emit : 1989 / 1989   (100%)
  primaryFilename extensions     : .c 1989       (zero headers)
  ```

- `TU = -1` on 672 records: unimplemented, modelled from `builtin-models.db`.
- The duplicate records are explained too. `get_bits1` appeared five times with
  identical file, line and mangled name because it was compiled into five TUs.
  Sampling 500 duplicated identifiers: 153 shared file+line (one header inline,
  many TUs), 347 differed (distinct `static` functions sharing a name).

**The defect this exposes.** `model_provenance.py` reads the JSON `file` field
and tests whether that path still exists. That is a **proxy** for the real
question, and it is wrong for any header-defined function: the header can be
gone while the TU is fine, or present while the TU is gone. It worked on the
`snowdsp.c` case only because there the text location and the TU primary were
the same file, so the proxy coincided with the truth.

The correct check is now available: analyze with `--enable-callgraph-metrics`,
read the CSV's `TU` column, resolve through `cov-manage-emit list-json` to a
`primaryFilename`, and test *that*. Rewrite pending -- **the tool's current
verdicts should be treated as indicative, not authoritative.**

Side effect: the generated-header worry is moot. A `.inc` can never be an
implementing TU, so generated headers cannot produce false ghosts under the
corrected check.

Not measured: what `--enable-callgraph-metrics` costs on its own. The 983s run
here was a *full* analysis forced by a win64-to-linux64 binary change, so it
says nothing about the flag's own overhead.

## A measurement harness must distinguish "I produced this" from "I found this"

Recorded 2026-08-25 because it is the second time this class of error has
appeared, in a new disguise.

The overnight run's kernel stage reported:

```
KERNEL T1 (first) rc=2 wall=0s
Files analyzed      : 5775 Total
Functions analyzed  : 82675
Defect occurrences  : 10583 Total
KERNEL incremental speedup = 0.0x
```

Every number is real. The claim they imply is false. The analysis **never ran**
-- `rc=2`, zero seconds, because no local install could read emit format 355.
The figures came from a completed analysis already present in the supplied
tarball, and the script grepped `output/summary.txt` without checking whether
its own run had succeeded.

The general rule, alongside the vacuous-oracle note earlier in this file:

- **Gate every reported figure on the exit status of the run that was supposed
  to produce it.** Print nothing on failure.
- When operating on an artifact that may already contain results, **move them
  aside first** (`output` -> `output.as-shipped`), so a failed run cannot
  silently inherit someone else's numbers.

Both fixes are in `postrun.sh`.

## Timing precision: one decimal place, and why

All wall-clock figures in this file were taken **inside a WSL2 guest** on a
laptop whose host was doing other light work. The guest cannot observe host
scheduling, so every duration carries noise it cannot measure or subtract.

**Rule adopted 2026-08-25: report ratios to one decimal place, never more.**
These runs are order-of-magnitude evidence -- "capture is about twice the
build", "re-analysis is about ten times faster" -- and a second decimal place
asserts precision the method does not have.

- Do not quote `1.97x` when the honest claim is `2.0x`.
- Do not treat a gap between, say, 3.8x and 4.1x across two subjects as a
  finding. It may be host noise.
- Differences of a **factor** are what these runs support. The 9x recovery from
  fixing job parallelism, and a 10x incremental-analysis speedup, are safely
  above the noise. A 5% gap is not.
- The driver scripts print two decimals; that is a `printf` artefact, not a
  precision claim. Round when reporting.

Hardware, so no figure is carried off this box: AMD Ryzen 7 PRO 6850U, **8
physical cores** (16 logical, SMT), a 15-28W mobile part that thermally
throttles under sustained all-core load. WSL2 guest with 24GB RAM after the
2026-08-25 reconfiguration. Only the ratios travel; absolute times do not.

## Wall clock is not measurement on a machine that can sleep

Learned the expensive way, 2026-08-25/26. Two independent timers agreed with
each other and both were wrong.

The LLVM first-analysis stage began at 21:13 and the host slept overnight.

| source | reported | reality |
|---|---|---|
| driver's `date +%s` delta | 66,145 s (18.4 h) | calendar time |
| Coverity's `Time taken by analysis` | **18:22:16** | calendar time |
| reconstructed compute | **~4.5 h** | actual work |

**`Time taken by analysis` in `summary.txt` is wall-clock and is corrupted by
host suspension exactly as an external timer is.** It is not a safe fallback.
Agreement between the two proved only that both measured the same wrong thing.

Reconstruction used suspension-immune sources: guest `uptime` (which does not
advance while suspended) minus the daytime stages, cross-checked against
cumulative CPU time from `/proc/<pid>/stat` -- 30.1 CPU-hours, implying ~9.6
cores busy, consistent with 16 workers on 8 SMT cores.

**Rules adopted:**

- For any run that may span an unattended window, record **CPU time**
  (`utime+stime+cutime+cstime`) alongside wall clock. CPU time cannot advance
  while suspended.
- Prefer to schedule timed stages when someone is awake, or on a host that will
  not idle. A measurement that needs an asterisk is worth less than a shorter
  one that does not.
- Treat agreement between two wall-clock sources as **no evidence at all** of
  validity when both derive from the same clock.

### A second, avoidable loss: the summary was overwritten

The first-analysis figures were nearly lost outright. `summary.txt` is
**rewritten by the next analysis of the same idir**, and the driver's grep did
not include `Time taken by analysis`, so the value survived only because
`cov-analyze` also prints it to stdout, which was being logged.

- **Copy `output/summary.txt` aside the moment a stage finishes.** Do not
  assume it will still be there.
- Log analysis stdout to a file per stage; it carries figures the summary may
  no longer hold.

## Measured: capture cost and incremental analysis, LLVM and FFmpeg, 2026-08-26

Hardware and precision caveats in the timing-precision section above. Ratios to
one decimal place.

### Capture cost: C/B = 2.2 on LLVM

LLVM + clang, X86 only, Release, gcc 13.3.0, `-j8`, 3,558 C++ TUs, quiet box.

| | wall | vs plain build |
|---|---|---|
| plain `ninja` build (B) | 6,256 s | 1.0 |
| `cov-build` capture (C) | 13,494 s | **2.2** |

The plain build was **97.6% compilation** (linking and archiving under 2.5%),
at 8.1x average parallelism against `-j8`, so this is close to a pure
frontend-vs-frontend comparison. **Only 10 compiler config directories** were
probed, so compiler probing is negligible here -- which leaves it available as
an explanation for other projects rather than this one.

### The capture ratio is a function of TU size

The single most useful result. Per-edge, over 3,558 compile edges present in
both builds:

| plain TU cost | count | plain s | capture s | ratio |
|---|---|---|---|---|
| 0-1 s | 119 | 51 | 577 | **11.3** |
| 1-3 s | 450 | 903 | 3,514 | 3.9 |
| 3-10 s | 1,371 | 8,545 | 24,565 | 2.9 |
| 10-30 s | 1,204 | 21,189 | 48,932 | 2.3 |
| >30 s | 368 | 18,716 | 29,009 | **1.5** |
| all | 3,558 | 49,255 | 107,015 | **2.2** |

Monotonic over two orders of magnitude. Small TUs cost ~11x to capture, large
ones ~1.5x. Consistent with a substantial per-translation-unit cost that the
compiler amortises and Coverity repeats -- the repository owner's observation
that gcc spawns one `cc1plus` per compilation line while Coverity appears to
launch one `cov-emit` per file.

This explains, without either measurement being wrong, why the Linux kernel
shows **3.8** (many small C files) and LLVM shows **2.2** (huge C++ TUs). It
also means **a project can predict its own capture ratio from its TU size
distribution**, which `.ninja_log` gives for free.

Do **not** over-model it: a least-squares fit gives `capture = 1.2 x plain +
13.2 s`, but the intercept is dominated by large TUs and back-solving from the
buckets gives ~4-5 s for sub-second TUs. The bucket table is the artifact; the
linear fit is not.

### Incremental analysis: ~24x on FFmpeg

Three arms, one idir, one variable. FFmpeg, 2,810 files, ~27,000 functions.

| arm | wall | `analysis binary changed` |
|---|---|---|
| WARMUP (win64-analyzed idir, re-analyzed by linux64) | 863 s | **1** |
| INCREMENTAL (same binary, nothing changed) | **35 s** | 0 |
| FULL (`--force`) | 832 s | -- |

- **Incremental is ~24x faster than full.**
- **The cross-binary penalty equals a full analysis**: warmup 863 s vs force
  832 s, within 4%. Gate 0 is now quantified, not merely inferred.
- **The warmup arm was methodologically necessary.** Without it the experiment
  compares warmup to force -- 863 vs 832, a ratio of **1.0** -- and concludes
  incremental analysis does nothing. The first run under a new binary is forced
  full, so it must be spent before measuring.

### Incremental analysis does not show up in summary.txt

LLVM T1 (first) and T2 (immediate re-analysis, zero changes) reported
**identical** scope:

```
                   T1          T2
Files analyzed     7172        7172
Functions analyzed 1657265     1657265
Paths analyzed     25836887    25836887
Defects            9868        9868
Time taken         18:22:16    01:11:26
```

**"Functions analyzed" describes the idir's scope, not work performed.** You
cannot verify that incremental analysis engaged by reading the summary. The
available signals are elapsed time and the *absence* of the binary-changed
notice.

T1's time is **contaminated** (host slept; see the wall-clock section) --
reconstructed compute ~4.5 h. T2 at 4,292 s is clean, and its Coverity timer
(01:11:26 = 4,286 s) agrees with the external clock to within 6 s, which is
what honest agreement looks like.

**Open:** LLVM's reconstructed incremental speedup is ~3.8x against FFmpeg's
24x. Hypothesis, untested: the fixed cost of loading and walking the callgraph
dominates at scale -- 1.66 M functions against 27 K. A clean `--force` run on
the LLVM idir is queued to settle it.

## `df` inside WSL does not measure available space

Cost a multi-hour run on 2026-08-26/27. Recorded because the number looks
authoritative and is checked reflexively.

A WSL2 guest's root filesystem lives in a **sparse `ext4.vhdx` on the host
drive**. `df` reports the vhdx's *virtual* size -- 1 TB here -- not the host's
free space. The guest cannot see the host disk at all.

Observed at the moment WSL failed to start:

```
df -h / inside WSL :  830 GB free      <- virtual, meaningless
C: actual free     :  2.69 GB          <- the real constraint
ext4.vhdx          :  167.8 GB
```

The failure mode is not a clean "disk full" error. It was
`Wsl/Service/CreateInstance/E_FAIL, error code 6` on **every** subsequent
`wsl` invocation, with all running work killed. Diagnosing it from inside the
guest is impossible, because the guest is what stopped starting.

**Two rules:**

1. When sizing work on WSL, check the **host** drive
   (`Get-PSDrive C`), never `df` inside the guest. Budget against host free
   space minus a safety margin.
2. **Deleting files inside the guest returns nothing to the host.** The vhdx
   does not shrink on its own. Reclaiming requires compaction, which needs
   elevation:

   ```
   wsl --shutdown
   diskpart> select vdisk file="<path>\ext4.vhdx"
             attach vdisk readonly
             compact vdisk
             detach vdisk
   ```

   Do **not** use `wsl --manage <distro> --set-sparse true --allow-unsafe` as a
   shortcut. WSL disables that path by default for **potential data
   corruption**, and an idir is exactly the kind of large artifact you cannot
   cheaply rebuild.

Related trap, same session: a Windows Coverity binary invoked *from inside WSL*
fails with `cannot find current executable 'cov-analyze.exe', cannot set bin
path` (rc 4). Cross-OS invocation through `/mnt/c` breaks the tool's own path
resolution -- drive Windows binaries from Windows.

## Incremental analysis speedup varied widely across subjects (provisional)

Three subjects, measured 2026-08-26/27 on 2026.6.x. **Provisional -- the
kernel row may reflect a product regression (see below), so the trend is not
yet established.** Read this before quoting any incremental figure.

| subject | functions | full (`--force`) | incremental | speedup |
|---|---|---|---|---|
| FFmpeg | 27,008 | 832 s | 35 s | **24x** |
| Linux kernel | 82,675 | 1,176 s | 396 s | **3.0x** *(disputed -- see below)* |
| LLVM + clang | 1,657,265 | 11,655 s | 4,292 s | **2.7x** |

Per-function cost shows the mechanism:

```
incremental:   1.3 / 4.8 / 2.6 ms per function   <- roughly flat
full:         30.8 / 14.2 / 7.0 ms per function  <- cheaper at scale
```

**Full analysis has economies of scale; incremental does not.** The two
converge, so the ratio between them shrinks as a project grows. Plausibly the
flat term is loading and walking the callgraph, which incremental must do
before it can decide what to skip -- untested.

**FFmpeg's 24x is the outlier, not the rule.** Two of three subjects sit near
3x, and the kernel -- squarely in this skill's target audience -- is one of
them.

Consequences:

- Do **not** quote a general incremental multiplier. It ranged from 24x to 2.7x
  across three subjects on 2026.6.x. Whatever explains that spread, quoting one
  number as typical is not supportable from this evidence.
- **Do not attribute the spread to callgraph size.** That was the working
  hypothesis and it is not established -- one of the three points is suspected
  of being a version regression, which would undercut the trend it appeared to
  support.
- **Report both halves.** Whatever the analysis figure turns out to be, do not
  let a capture saving stand for the whole improvement. At LLVM scale capture
  was 13,494 s and a no-op re-analysis 4,292 s -- a third of it, not a rounding
  error, and a user quoted only the capture number would be misled.
- **Tell users to measure it themselves.** It is cheap -- analyze twice, compare
  -- and it is the only figure that is true for their project, their version and
  their checker configuration. This is more useful than any number this file
  could carry, and it does not go stale.

**Report the estimate; do not pronounce on acceptability.** Whether a given
total is fast enough for a pre-commit hook, a pull-request gate, or only for a
later stage of the SSDLC depends on the team, the codebase and the process --
none of which this skill can see. The useful output is the *relative*
improvement plus both absolute halves, so the reader can decide.

Worked example, the kernel, using measured numbers:

| | capture | analysis | total |
|---|---|---|---|
| full rebuild + full analysis | 17m34s | ~20m | **~37 min** |
| reuse + incremental analysis | 5m42s | 6m36s | **~12 min** |

Roughly **3x on total time**. A team for whom 37 minutes was impossible may
find 12 minutes routine; another may need it under a minute and conclude this
belongs later in the pipeline. Both are legitimate readings of the same
measurement, and the skill's job is to supply the measurement.

**The kernel row may reflect a product regression, not a property of
incremental analysis.** Recorded, but do **not** generalize from it.

The repository owner has prior kernel runs showing materially faster
incremental times, and notes that **incremental analysis is designed to deliver
considerably more than a 3x speedup**. That makes a **2026.6 regression** the
leading explanation rather than a misconfiguration on my part. They intend to
investigate; that is a product question and is out of scope here.

My run is reported as measured, with its exact conditions, because the number
is real on that version:

- analyzer `cov-analysis-win64-2026.6.0`, idir captured by **2026.6.1**
- **no flags** (631 checkers); the shipped analysis used `--all --rule
  --preview --enable-callgraph-metrics -j auto` plus ~18 explicit `--enable`
  (672 checkers)
- both runs took the incremental path (`Loading topological sort from disk
  (118996 functions)`), neither log contains a cache-invalidation message,
  both used 16 workers
- logs retained at `C:\analysis\kernel-results\k-t1.log` and `k-t2.log`

**What this means for the scaling claim above.** The trend across three
subjects may be measuring a version-specific defect rather than an inherent
relationship between callgraph size and incremental speedup. Treat the curve as
**provisional**. In particular:

- Do not tell a user their incremental speedup *will* shrink with project size.
- Do not quote a specific multiplier as a general expectation.
- Do direct them to **measure it on their own project and version**, which is
  cheap: analyze twice and compare.

Separating the concerns deliberately: whether 2026.6 has a regression is for
the product to answer. What this skill owes its users is an honest statement
that the figure varies, a way to measure it themselves, and no claim that
outlives the version it was taken on.

### Kernel run details

`cov-analysis-win64-2026.6.0`, Windows-native. 3,779 TUs, 5,775 files,
5,748,189 paths. Coverity's own timer agreed with the external clock (19:31 vs
1,176 s; 06:25 vs 396 s).

The tarball shipped its own analysis for comparison: **20:12 and 10,583
defects** against my **19:31 and 6,564**. The difference is checker
configuration, not a discrepancy -- the shipped run used `--all --rule
--preview` plus ~18 explicit `--enable` flags (672 checkers) against my
defaults (631). Notably the *times* are close despite 41 more checkers, so
checker count is not the dominant cost.

## CORRECTNESS: reuse produced identical results to a fresh capture

The result the technique stands or falls on, measured 2026-08-27. Speed is
irrelevant if the answer differs.

**The test**, as specified by the repository owner: analyze an older tag, pull
the idir forward to a later commit, analyze again -- then independently
full-build and analyze the later tag, and check the two agree.

Subject: **proftpd v1.3.8 -> v1.3.9**, a real release delta of **443 files, 186
of them `.c`** against a 90-TU emit. Not a token edit. All three arms ran in the
**same directory**, so capture paths were identical and path normalization was
removed as a variable.

| arm | files | functions | defects |
|---|---|---|---|
| 1. full capture + analyze at v1.3.8 (reference) | 149 | 2,088 | 148 |
| 2. rolled to v1.3.9, **idir reused**, incremental capture | 149 | 2,102 | **147** |
| 3. independent clean capture + analyze at v1.3.9 (oracle) | 149 | 2,102 | **147** |

```
in both: 147    only in reused: 0    only in oracle: 0
VERDICT: IDENTICAL
```

Arm 1's 148 defects independently reproduces a figure recorded in an earlier,
unrelated session ("proftpd v1.3.8: 148 occurrences"), from a fresh clone,
configure and capture.

### The staleness gate flipped correctly

Same tool, same idir, either side of the incremental capture:

```
BEFORE:  OK 34   STALE 56   -> STALE,   do not analyze   (rc 1)
AFTER :  OK 90   STALE  0   -> CURRENT, safe to analyze  (rc 0)
```

The capture re-emitted exactly the 56 stale TUs and left the other 34 alone.
Zero false `ORPHAN`, zero false `PATH_DIVERGED`.

### Every guard fired, and one caught a real error

- **TU floor**: 90 TUs in all three arms.
- **Build-log scan**: zero `exited with code` / `make: ***`.
- **Parse cross-check**: 147 parsed against 147 in `summary.txt`, both sides.
- **Self-test**: removing one finding was DETECTED -- the oracle demonstrated
  it could disagree before it was allowed to agree.
- **The TU floor caught my own error.** The first run omitted `--config` from
  `cov-build`. The build exited 0, logged no failures, and captured **zero
  TUs**; nothing in the output said anything was wrong. Rule 1 is not optional,
  and a percentage of nothing is still 100%.

### What this does NOT establish

Scope honestly:

- **C, not C++.** proftpd is C. Header-carried code and template instantiation
  are the interesting cases and are untested here.
- **Small.** 90 TUs. Nothing about behaviour at LLVM or Chromium scale.
- **One build system.** autoconf/make. Not ninja, not MSBuild.
- **No path divergence.** All arms shared a directory *deliberately*. The
  imported-idir case, where the reference records another machine's roots, is
  untested by this run.
- **Fast-forward only.** This is the tag-to-tag case. The *Local update* case
  -- uncommitted working-tree changes -- is not covered.
- **One delta, one project.** A single pass, not a distribution.

The C++/scale version is `benchmarks/exp-partb.sh`, which has both arms and has
not yet run to completion.

## Limits of the evidence

These are the boundaries of what has been measured, kept here so a claim's
provenance is never guessed at (rule 23). They are limits of the evidence,
not missing pieces of the skill: the procedure is complete and each item
below tells you which specific claim to treat as reasoned rather than
measured, and what would settle it.

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
- **`delete` is documented** -- in the sub-command section of the command
  reference, though not in the synopsis's COMMANDS list ("Delete all TUs that satisfy the specified translation
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

### Limits of the evidence -- reuse

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
