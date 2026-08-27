# Benchmark harness

The scripts that produced the measurements in `../CALIBRATION.md`. Kept because
re-deriving them cost more than running them, and because several encode a
correctness trap that is not obvious from the outside.

**All paths are hardcoded to the box they ran on.** Edit `COV`, `LIC`, `SRC`
and the idir paths before use. They are evidence and starting points, not
turn-key tools.

| Script | What it measures | Status |
|---|---|---|
| `exp-ffmpeg-incr.sh` | incremental vs `--force` analysis, 3 arms | **validated** -- produced the ~24x result |
| `overnight.sh` | B (plain build), C (capture), T1, T2, then FFmpeg | **validated** -- produced C/B = 2.2 |
| `sequencer.sh` | strict serialization of post-run stages | **validated** |
| `llvm-capture.sh` | a single timed `cov-build` capture | validated |
| `exp-cgm.sh` | re-analysis with `--enable-callgraph-metrics` | validated |
| `exp-partb.sh` | **the reuse path, both cohorts** | **NEVER RUN TO COMPLETION** |

## Three traps these encode

**1. The warmup arm is mandatory** (`exp-ffmpeg-incr.sh`). The first analysis
under a *different binary* is forced full -- `analysis binary changed`. Measure
without spending that run first and you compare full-to-full, get **1.0x**, and
conclude incremental analysis does nothing. It was the difference between 1.0x
and 24x.

**2. Never report a figure without gating on exit status.** An early kernel
stage printed real file/function/defect counts after a run that returned `rc=2`
in zero seconds -- it had grepped a `summary.txt` that shipped inside the input
tarball. Move any pre-existing `output/` aside before running, and print nothing
on failure.

**3. Copy `summary.txt` aside the moment a stage ends.** It is rewritten by the
next analysis of the same idir. The first LLVM analysis's timing survived only
because `cov-analyze` also prints it to stdout, which happened to be logged.

## Serialization, and why it is not optional

Every stage is `-j8` and runs alone. On an 8-physical-core box, two concurrent
`-j16` jobs drove capture from **34 edges/min to 3.8** -- a 9x loss -- and later
into swap collapse that killed the WSL VM. Size `-j` to *physical* cores and
never overlap timed stages.

`sequencer.sh` exists because three chains once raced: a `--force` run fired
when the previous analysis ended, which was exactly when the next overnight
stage began.

## Known defects

- **`exp-partb.sh` has never completed.** It died to a full disk, not to a bug,
  but that means neither arm -- the 400-commit fast-forward nor the 3-file inner
  loop -- has produced a number. It is the largest outstanding measurement.
- The kernel stage in the retired `postrun.sh` invoked a **Windows**
  `cov-analyze.exe` from inside WSL and failed with `cannot find current
  executable ... cannot set bin path` (rc 4). Drive Windows binaries from
  Windows. That script is not included here for that reason.
- Wall-clock timing is unreliable across an unattended window; see the
  wall-clock section of `../CALIBRATION.md`. Record CPU time alongside it.
