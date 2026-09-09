# Where the PATHOUT notice lives, and how to read it

Everything about the path limit is in **`<idir>/output/analysis-log.txt`**.
Nothing about it reaches the console (checked with and without
`--print-paths`, on 2025.9.0 and 2026.6.0), the `*.errors.xml` files,
`FUNCTION.metrics.xml.gz`, the `stats` SQLite database, or `tus`. If a
report says "PATHOUT", someone read the log.

## The four kinds of line

### 1. The count -- always present

```
summary: paths_exceeded count: 4
```

Number of functions in which at least one component hit the limit. Zero on
a clean run. Grep this first.

### 2. The warning -- present only when the share is high

```
summary: Exceeded path limit of 5000 paths in 1.91% of functions (normally up to 5% of functions encounter this limitation)
```

Names the limit in force and the share of functions affected. It appeared
at 1.11%, 1.91%, 16.67% and 50.00%; it did **not** appear on a run with 4
functions out of 2102 (0.19%). Its absence is not evidence of zero; the
count line is.

### 3. The per-function work-unit line -- names the function, when there is one

```
wur: gen1059 4 102632 4703 7340 4703 5001 PATHOUT=1 n: setup_env in TU 77
wur: gen4 2 4070 5578 343 5547 5001 PATHOUT=1 n: _ZN4demo6Widget1fEi in TU 2
```

- `gen1059`: phase (`gen` main analysis, `stat` statistical checkers,
  `conc` concurrency, `fnsaftertus` post-TU work) and work-unit id.
- the number before `PATHOUT=`: paths explored, the **maximum over the
  components** that walked the function, not the sum (verified: 39
  components summing to 31,365 gave a line saying 6003, `REVERSE_INULL`'s
  own count). At the limit it reads `5001`; `10001` also occurs (twice the
  limit plus one -- seen on `_pass2` components and on one proftpd
  function; observed, not explained).
- `PATHOUT=1`: the flag.
- `n: <name> in TU <n>`: the function -- **plain identifier for C, mangled
  name for C++** -- and its translation unit. Both go straight into
  `cov-manage-emit find` (`references/function-extraction.md`).
- `mem=... max=...` appears on some lines and is memory, not paths. The
  other integers are timing and size fields; none is needed for this.

Lines without a `PATHOUT=` flag are the functions that finished:

```
wur: gen1061 4 30873 93 1413 93 104 n: auth_pass in TU 77
```

### 4. The batch line -- does not name the function

```
wur: gen646 15 1058527 33094 3593 33016 mem=126263296 max=167362560 38650 PATHOUT=4 nr=20 n: batch 645
```

Under a heavier configuration on a larger project the `gen` phase groups
functions into work units of `nr=20`, and a batch that hit the limit reports
only how many of its functions did (`PATHOUT=4`). Measured on subversion
plus the sqlite amalgamation (9533 functions, 2026.3.0):

| options | named `PATHOUT` lines | batch `PATHOUT` lines | `paths_exceeded count` |
|---|---|---|---|
| defaults | 17 | 0 | 16 |
| `--all --aggressiveness-level high` + models | 3 | 130 (`PATHOUT=` summing to 193) | 189 |

So on exactly the runs where the notice matters most, the log names three
functions out of 189. The batch totals do not reconcile exactly with the
count either (193 + 3 vs 189); treat them as indicative. **The function
names come from `--print-paths`.**

## `--print-paths`: which function, and which checker

Re-run `cov-analyze` with `--print-paths` (scope it with `--tu` to the TUs
you care about; a whole-project re-run costs what the original analysis
cost -- 4.5 minutes for the subversion run above). Every component then logs
its path count per function, and the ones that hit the limit are flagged:

```
wur_diagnostics: 4956 paths traversed by DEADCODE_pass2 in "setup_env(pool *, cmd_rec *, char const *, char *)"
wur_diagnostics: Pathed out: 5001 paths traversed by REVERSE_INULL in "setup_env(pool *, cmd_rec *, char const *, char *)"
```

- The function is named by its **demangled signature**, in both C and C++
  (`"demo::Widget::f(int)"`). To get from that to a `find` query, use the
  identifier and pick the right overload from the listing.
- `Pathed out:` marks the components that exceeded the limit. Everything
  else on the line is the same.
- This works inside batches. The heavy subversion run above logged 481
  `Pathed out` lines naming 181 distinct functions; the batch lines named
  none.
- The same component can be logged twice for one function
  (`DEADCODE_pass2` at 10001, twice, for `sqlite3_str_vappendf`).
  `tools/pathout_report.py` folds those.
- The console gets the same lines with a phase prefix
  (`wur_diagnostics: gen36: Pathed out: ...`) interleaved with the progress
  stars. Read the log, not the console.
- One function was logged `Pathed out` (`DEADCODE_pass2`, 10001) while its
  `wur:` line said 735 paths and carried no `PATHOUT=` flag. The two
  signals agree almost everywhere but not exactly; when they disagree,
  the `Pathed out` line is the one that names a checker.

### `--path-log-threshold`

Documented as "if a function has more than `<number>` paths, this count is
output to the log file". Tried at 100 (fixture) and 1000 (proftpd, `--tu
77`): no line in the log or on the console changed. Not useful for this;
`--print-paths` is.

## Sanity checks on any log

- The log's first line is the exact `cov-analyze` command, and the
  `cmdline: parsed cmdline:` block after it lists every option in force,
  including `--paths` if it was raised. Check that before comparing two
  logs.
- `summary.txt` in the same directory has `Paths analyzed : N` for the whole
  run, `Functions analyzed : N` (the denominator of the percentage) and
  `Time taken by analysis`.
- A `--tu`-scoped run rewrites `output/` for that scope. Copy the idir, or
  at least save the original log, before re-running.

## Grep cheat-sheet

```bash
L=<idir>/output/analysis-log.txt
grep -E '^summary: (paths_exceeded|Exceeded path limit)' $L    # is there a problem, how big
grep 'PATHOUT=.*in TU' $L                                       # named functions + TU ids
grep -c 'PATHOUT=.*n: batch' $L                                 # unnamed ones (re-run --print-paths)
grep 'Pathed out' $L | sed 's/.* in "\(.*\)"$/\1/' | sort -u    # names, from a --print-paths run
grep 'Pathed out' $L | sed 's/.*traversed by \([^ ]*\) in.*/\1/' | sort | uniq -c | sort -rn   # which checkers
```

Or `python3 tools/pathout_report.py --dir <idir>` for all of it at once.
