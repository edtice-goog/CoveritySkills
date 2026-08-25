# Worked example: proftpd, three releases across three years

The calibration session that established this skill's mechanics. Analysis
2025.9.0 (Linux capture, Windows analyze/commit) into Connect 2025.12.0.

## Setup

proftpd was chosen for real release history: 39 tags spanning 2015-05-27 to
2025-03-14, `configure` committed at each tag (so no `autoreconf`, no autoconf
skew across a decade), and a build that needs no heroics.

The project builds only on Unix; Connect was reachable only from Windows. So:
capture under WSL with the idir on `/mnt/c`, then analyze and commit with the
Windows tools. Intermediate directories are platform-independent, and the two
installs were confirmed to be the same version by comparing the internal build
string (`477d3c5ddd p-2025.9-push-57`) on both sides.

Build tree: a dedicated clone at a fixed path, each tag checked out in place.

## Two bugs found during calibration

Both are the reason Step 1 reads the way it does.

**The build was not parallel-safe.** Under `make -j16`, proftpd's `lib/Makefile`
races: `prbase.a` is archived before its own objects finish. v1.3.8a captured
**77** compilation units instead of 90.

**`cov-build` reported that failure as success.** It exited **0** and printed
`Emitted 77 C/C++ compilation units (100%) successfully`. The percentage is of
units *attempted*. Nothing in the exit status or the summary indicated that
`make` had died.

Had that snapshot been committed, thirteen compilation units' worth of defects
would have vanished from v1.3.8a and reappeared in v1.3.9 -- a fabricated fix
event followed by a fabricated regression, in a dataset whose entire purpose is
that its deltas mean something. Worse, the race was intermittent: v1.3.8 built
cleanly with the same command.

Fix: serial builds, plus explicit log inspection for `make: ***` and the
`[WARNING] Build command ... exited with code` line. Both versions then
captured 90 CUs.

## Phase 2 output

```
[ok] v1.3.8 -> v1.3.8a: 112 shared merge keys (99% of v1.3.8)
[ok] v1.3.8a -> v1.3.9: 111 shared merge keys (99% of v1.3.8a)

version       total    new  persist  fixed
v1.3.8          113    113        -      -
v1.3.8a         112      0      112      1
v1.3.9          112      1      111      1
```

Note 113 merge keys against 148 defect *occurrences* -- multiple occurrences
share a merge key, and Connect assigns CIDs per merge key. Report the merge-key
number; it is what the UI will show.

## Phase 3

Three commits, oldest first:

```
--backdate 20221204    proftpd 1.3.8     -> snapshot 10001
--backdate 20231008    proftpd 1.3.8a    -> snapshot 10002
--backdate 20250314    proftpd 1.3.9     -> snapshot 10003
```

The first attempt used `--backdate 2022-12-04` and was rejected:
`"2022-12-04" doesn't look like a yyyymmdd date`.

Result:

```
  id   | snapshot_date |  description   | backdated
-------+---------------+----------------+-----------
 10001 | 2022-12-04    | proftpd 1.3.8  | t
 10002 | 2023-10-08    | proftpd 1.3.8a | t
 10003 | 2025-03-14    | proftpd 1.3.9  | t

 first_detected | count
----------------+-------
 2022-12-04     |   113
 2025-03-14     |     1
```

Phase 2 predicted 113 CIDs and exactly one new defect *before any commit*, and
Connect matched. That is the evidence for treating Phase 2 as a faithful
preview rather than an estimate.

## Phase 4: the audit that mattered

The one new defect -- CID 10114, `NULL_FIELD` at `src/fsio.c:6116` in
`pr_fsio_realpath` -- is exactly what a story builder would feature, being the
only new finding at the tip.

```c
/* Find the first non-NULL custom realpath handler.  If there are none,
 * use the system realpath
 */
while (fs && fs->fs_next && !fs->realpath) {
  fs = fs->fs_next;
}
res = (fs->realpath)(fs, p, path);
```

The loop exits when `fs->fs_next` is NULL regardless of whether a handler was
found, and the fallback promised by the comment is not implemented. So the code
does contradict itself.

**Verdict: unresolved, leaning global invariant. Not a demo item.**
Reachability depends on the terminal `pr_fs_t` in the chain having a NULL
`realpath`. If the terminal element *is* the system realpath handler, the code
keeps its promise after all and this is an in-code global invariant -- but that
was not confirmed by reading the fs-chain construction, so `unresolved` is the
honest verdict rather than a dismissal. Coverity's own evidence is the
statistical `checked 1 out of 1 times`, which is thin.

The disqualifying property is not correctness but **legibility**: an
experienced reader needed several minutes to reach a confident opinion. On
stage that reads as tool equivocation. See `selection.md`.

Note what a per-checker sample would have done here: `NULL_FIELD` fired 51
times in this dataset, so a sample of a few would almost certainly have missed
this one -- while it is simultaneously the single most likely defect to end up
on screen. That asymmetry is why story-surfaced defects get audited
unconditionally.

## The full corpus: 24 releases, 2015-2025

Extending the calibration to every proftpd release. All 24 captured (one,
`v1.3.6d`, needed a retry -- see below), all analyzed under the single pinned
2025.9.0 analyzer.

**Capture determinism held across the whole corpus.** Compilation-unit counts
are constant within each release line and step only between lines:

| line | CUs |
|---|---|
| v1.3.5a-e | 88 |
| v1.3.6-v1.3.6e | 94 |
| v1.3.7-v1.3.7f | 103 |
| v1.3.8-v1.3.9 | 90 |

Not one anomaly in 24 builds. With the parallel-make race still in place these
would have been ragged, and every raggedness would have entered the dataset as
a fabricated fix or regression.

**Per-stream populations are nearly flat**, which is what maintenance branches
actually look like -- targeted fixes, not sweeping change:

```
=== proftpd-1.3.5 ===        === proftpd-1.3.7 ===
v1.3.5a  176                 v1.3.7   113
v1.3.5e  178                 v1.3.7f  115
```

**The story is across streams, and in the first-detected projection:**

```
Projected first-detected distribution after Phase 3
  2015-05-27    176
  2017-04-09     33
  2020-07-20      6
  ... 222 distinct CIDs total

Defects in v1.3.9 (2025-03-14) by first-detected date:
  2015-05-27     78     <- outstanding for nearly ten years
  2017-04-09     21
  2025-03-14      1
```

Total population falls 176 -> 112 across the decade, and **78 defects first
seen in May 2015 are still present in the March 2025 release.** That is the
aging story, and it is real rather than constructed.

### Two process failures worth recording

**A transient one.** `v1.3.6d` failed with a bash syntax error, not a build
error: git rewrote `capture.sh` in the working tree (`core.autocrlf=true`)
while WSL bash was executing it, mid-sweep. Re-capturing produced 94 CUs,
matching its line exactly. Two design choices contained it -- the sweep was
non-fail-fast, so one release was lost rather than the run, and `.gitattributes`
now pins `*.sh` to LF. The general lesson: do not run a long sweep out of a
working tree you are actively committing to.

**A tooling one.** The first full-corpus Phase 2 run treated all 24 releases as
one linear chain, and reported 76 defects "fixed" at v1.3.6 -- an artifact of
comparing the 1.3.6 line's first release against the 1.3.5 line's last. That is
precisely the flattening rule 29 warns about, reproduced by the analysis tool
rather than by the commit. `phase2.py --tags` now reports per-stream.

## Phase 3: the real commit sweep

Reset to the key-only backup, five streams created, 24 backdated commits in
global date order. Every commit passed the earlier-dates-unchanged invariant.

```
[2015-05-27] v1.3.5a -> proftpd-1.3.5   176 newly-originated CID(s)
[2017-04-09] v1.3.5e -> proftpd-1.3.5     1
[2017-04-09] v1.3.6  -> proftpd-1.3.6    32   <- same date, different stream
[2020-07-20] v1.3.6e -> proftpd-1.3.6     0
[2020-07-20] v1.3.7  -> proftpd-1.3.7     6   <- same date, different stream
[2025-03-14] v1.3.8d -> proftpd-1.3.8     0
[2025-03-14] v1.3.9  -> proftpd-1.3.9     1
```

Final state: 24 snapshots, 222 CIDs, five streams.

| stream | snapshots | first | last |
|---|---|---|---|
| proftpd-1.3.5 | 5 | 2015-05-27 | 2017-04-09 |
| proftpd-1.3.6 | 6 | 2017-04-09 | 2020-07-20 |
| proftpd-1.3.7 | 7 | 2020-07-20 | 2022-12-04 |
| proftpd-1.3.8 | 5 | 2022-12-04 | 2025-03-14 |
| proftpd-1.3.9 | 1 | 2025-03-14 | 2025-03-14 |

**The committed first-detected distribution matched the Phase 2 projection
exactly, line for line.** That is the strongest available evidence for the
architecture in this skill: offline merge-key algebra predicts the outcome of
the irreversible phase precisely enough to plan against, so the one-shot commit
holds no surprises.

Note the same-date, different-stream pairs (`v1.3.5e`/`v1.3.6`,
`v1.3.6e`/`v1.3.7`, `v1.3.7f`/`v1.3.8`, `v1.3.8d`/`v1.3.9`). Committed into one
stream these would have read as fix-then-reintroduce churn; as separate streams
they are simply two lines shipping on the same day, which is what happened.

### Operational notes from the run

- `cov-admin-db restore` requires the database **up** and the application
  **down**: `cov-im-ctl maintenance` starts the database alone. Plain `stop`
  takes the database down too, and restore then fails.
- The restore point earned itself twice over. The backup taken *after* auth-key
  creation meant the key survived the reset; a factory `empty.bak` would have
  deleted it.
- Check who else is using the instance before restoring. This run found four
  snapshots from a concurrent session's analyzer-comparison calibration, which
  the reset would have destroyed silently; they were backed up first.
