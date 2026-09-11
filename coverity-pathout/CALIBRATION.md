# Calibration status

This project's standard is that factual claims in a skill were established by
real runs. This file records what was run for `coverity-pathout`, on what,
and what is reasoned rather than measured.

Environment: Windows 11, installations under `C:\Coverity\`. Three analyzer
versions were used, each against an idir it wrote:

| idir | written by | size | analyzed with |
|---|---|---|---|
| proftpd 1.3.9 (`coverity-demo-data-workspace/idirs/v1.3.9`), 149 C files, 2102 functions | 2025.9.0 (cov-build, gcc, WSL) | 2 GB | 2025.9.0 win64, scratch copy |
| subversion + sqlite amalgamation (`C:\Data\tool-interop\coverity\idirs\svn-augmented-post-enrichment`), 9533 functions | 2026.3.0 | 185 MB | 2026.3.0 win64, scratch copy |
| fixtures (`evals/fixtures/*`), emitted with bare `cov-emit --c` / `--c++` | 2026.6.0 | -- | 2026.6.0 win64 |

All dates 2026-09-09.

## Verified by direct execution

### Where the notice is

- `output/analysis-log.txt` carries `summary: paths_exceeded count: N` on
  every run (0 on clean runs: three fixture idirs).
- `summary: Exceeded path limit of 5000 paths in P% of functions (normally
  up to 5% of functions encounter this limitation)` appeared at P = 1.11,
  1.91, 16.67 and 50.00, and did **not** appear on the proftpd run with 4 of
  2102 functions (0.19%). Threshold not determined.
- Nothing on the console: `cov-analyze` stdout for the proftpd and fixture
  runs contains no `path limit` / `PATHOUT` text, with or without
  `--print-paths` (which adds `wur_diagnostics` lines to stdout, with a
  phase prefix, but no summary).
- Not in `*.errors.xml`, `FUNCTION.metrics.xml.gz`, `callgraph-metrics.json.gz`,
  the `stats` SQLite database (tables `version`, `Stat`, `InferredBehavior`;
  no PATHOUT in any column), or `tus` (grepped, subversion idir).

### Log line formats

- Per-function: `wur: gen1059 4 102632 4703 7340 4703 5001 PATHOUT=1 n:
  setup_env in TU 77`. C names plain; C++ names mangled
  (`n: _ZN4demo6Widget1fEi in TU 2`). Phases seen: `gen`, `stat`, `conc`,
  `conctd`, `fnsaftertus`.
- Batch: `wur: gen646 15 1058527 33094 3593 33016 mem=126263296
  max=167362560 38650 PATHOUT=4 nr=20 n: batch 645`. Subversion under
  `--all --aggressiveness-level high` + 5 model files: 130 batch lines
  (`PATHOUT=` values summing to 193), 3 named lines, count 189. Same idir
  at defaults: 0 batch lines, 17 named, count 16. A 600-function fixture at
  defaults produced batch work units (62) but no PATHOUT; with `-j 1`, no
  batch lines at all.
- The number before `PATHOUT=` is the maximum over components: for
  `setup_env` at `--paths 200000`, 39 `wur_diagnostics` lines summing to
  31,365; the `wur:` line said 6003 = `REVERSE_INULL`'s count.
- `5001` is the usual value at the limit; `10001` seen on `tpl_map_va`
  (proftpd) and on `DEADCODE_pass2` lines (subversion). One function
  (`sqlite3AtoF`) had `Pathed out: 10001 ... DEADCODE_pass2` while its
  `wur:` line said 735 with no `PATHOUT=` flag.
- `--print-paths` adds `wur_diagnostics: [Pathed out: ]N paths traversed by
  <component> in "<demangled signature>"`. Heavy subversion run: 481
  `Pathed out` lines, 181 distinct functions, 23 exact duplicate lines
  (same component logged twice for a function).
- `--path-log-threshold 100` (fixture) and `1000` (proftpd `--tu 77`): no
  change to the log or stdout.
- The log's first line is the full command; `cmdline: parsed cmdline:`
  lists options including `--paths` when given.

### Which components path out

- proftpd `setup_env` at defaults: `REVERSE_INULL` only (5001);
  `DEADCODE_pass2` 4956; 37 others between 1 and 1796.
- subversion at defaults (16 functions): `REVERSE_INULL` 11, `OVERRUN_pass1`
  6, `DEADCODE_pass2` 6, `INFINITE_LOOP` 4, then 2 each for
  `FORWARD_NULL_pass2`, `DIVIDE_BY_ZERO_pass2`, `UNUSED_VALUE`,
  `REVERSE_NEGATIVE_pass1`, `OVERLAPPING_COPY_INTERNAL`, `generic_DERIVERS`.
- subversion at `--all --aggressiveness-level high` (181 named): 
  `BUFFER_SIZE_pass1` 141, `TAINTED_SCALAR_pass1` 133,
  `STRING_OVERFLOW_pass1` 97, `REVERSE_INULL` 20, `INTEGER_OVERFLOW_pass1`
  14, `security_DERIVERS` 11, `OVERRUN_pass1` 11.
- fixture `ifs_from_zero` (and `many_ifs`, `demo::Widget::f(int)`):
  `generic_DERIVERS`, `uninit_DERIVERS`, `DEADCODE_pass1`, `OVERRUN_pass1`,
  all at 5001; with `--paths 200000` all four at exactly 16384.

### Paths x state

- `ifs_from_zero` (acc = 0): 5001, PATHOUT. `ifs_from_param` (acc = a):
  106, no PATHOUT. Same CFG, CCM 15, APC 16384 for both.
- An earlier C++ draft with `acc = v` (unknown) explored 92 paths for 13
  `if`s; changed to `acc = 0` it trips the limit.
- Negative results: 14 guarded `malloc`s freed at the end -- 172 paths; 14
  precomputed flags tested in 14 `if`s -- 217 paths. Neither tripped.
- APC vs explored across proftpd: `ls_nlst` APC 6.4e9 / 3845 paths;
  `facts_mlinfo_fmt` APC 31104 / > 5000; `pr_auth_cache_set` 526339 / 1025;
  of 2099 non-PATHOUT functions, explored == APC for 439 (small ones).

### Scoping and cost

- `cov-analyze --tu 77` on proftpd reproduces `setup_env`'s PATHOUT in
  isolation: 15 s vs 32 s for the full project. Subversion defaults full
  run 2 m 14 s; heavy configuration 4 m 27 s (both with `--print-paths`).
- `--paths 200000 --tu 77`: `setup_env` finished at 6003; `paths_exceeded
  count: 0`. `cov-format-errors --json-output-v10` on the default and raised
  runs: identical defect sets for TU 77 (2 issues; `DEADCODE` at
  `mod_auth.c:1606` in `setup_env` in both).

### The report tool

- `tools/pathout_report.py` run against all three idirs. proftpd: 4
  functions, metrics joined, 4 definitions extracted (509 / 295 / 353 / 92
  lines). C++ fixture: mangled name joined to `FUNCTION.metrics`
  (`fn:_ZN4demo6Widget1fEi`) and extracted by mangled regex. Subversion
  heavy log without `--print-paths`: 3 named, 129 batches flagged, advice
  printed; with `--print-paths`: the batch-hidden functions listed under
  their `Pathed out` signatures, duplicates folded.
- `evals/fixture.sh` end to end on 2026.6.0: both expected PATHOUT lines,
  `Pathed out` lines for four components each, `50.00%` summary line,
  zero console mentions, the C++ definition by mangled name, and the report.
  Re-run 2026-09-10 with the slice fixture `local_enum_forever.c` (now under
  `coverity-function-slice`) as a third TU: three PATHOUT
  lines, `60.00%`, count 3; the report lists all three; the new slice emits
  clean, reproduces its PATHOUT (5001; `OVERRUN_pass1`, `generic_DERIVERS`,
  `uninit_DERIVERS`) and its obfuscated twin verifies identical; the slice
  carries `#define true 1`, `enum __cov_anon_e3 state = st_start;`, `struct
  __cov_anon_s1 tally = {0, 0};` and `for (; true; ) {`.

### The escape hunt (2026-09-10)

- **Shape checker** (`evals/escape-hunt/null_check_then_deref.cxm`,
  CodeXM, 2026.6.0 and 2026.3.0): on `shape.c` reports the two intended
  sites (guard closing early; cast-and-star) and none of the three controls.
  Over the subversion idir with `--disable-default --codexm`: 13 s, 9,533
  functions, 2,088 hits in 442 functions.
- **CodeXM facts learned by compiling it**: `if..then..else..endif` and
  `elsif`; `??` is null-coalescing (`default` is not an operator);
  `stripCasts` needs an `expression`-typed argument; `variableReference.
  variable` is a record and cannot be `==`-compared (key by `mangledName ??
  identifier`); `innermostOwner(functionDefinition, ...)` is rejected and
  `outermostOwner(blockStatement, expr)` returns null, so the function is
  reached by walking `.parent`; `sourceloc` has no properties (no
  ordering); `if (p)` arrives as an implicit `p != 0` binaryOperator; `p->f`
  is `memberReference{objectExpression = pointerDereference{...}}`; a bogus
  property name makes the compiler list the real ones.
- **Filter** (`tools/pathout_filter.py`) against the `--print-paths` log of
  the heavy subversion run (178 PATHOUT functions named). First checker
  draft ("outside one testing if"): 815 of 2,088 hits in 75 PATHOUT
  functions; `--relevant FORWARD_NULL,NULL_RETURNS`: 1
  (`sqlite3_str_vappendf`, sqlite3.c:33692, `bufpt`); `--relevant
  REVERSE_INULL`: 306 in 31 (function, variable) pairs, 217 in
  `write_entry`. Reading those showed most were dereferences inside a guard
  of their own variable, flagged because another `if` tested it elsewhere.
  Second draft (structural "guarded": inside a testing if/ternary, right of
  `p &&` / `!p ||`, or anywhere given an `if (!p) <exit>`): 503 hits
  (11 s); 115 in PATHOUT functions; `FORWARD_NULL,NULL_RETURNS`: **0**;
  `REVERSE_INULL`: **27** in 7 pairs. Fixture unchanged (lines 20 and 59;
  controls silent).
- **The 27 read, all refuted**: `actual_node` x9 (`MAYBE_ALLOC` is
  allocate-if-null); `pTab` x7 (`assert(pTab!=0)`; `abort` is not an exit to
  the checker); `work` x5 and `t_entry` (inner declaration with the same
  name; locals had no `mangledName`, so the identifier fallback conflated
  them); `left_dirent`/`right_dirent` x3 (keys iterate the union of the two
  hashes, so both null is impossible); `pUsing` x2 (`fg.isUsing` implies it);
  `moved_nodes` (guarded by a `for` condition the checker does not treat as a
  guard). `parent_node` in `write_entry`, judged real on a first reading, is
  refuted by `WRITE_ENTRY_ASSERT(parent_node || entry->schedule ==
  svn_wc_schedule_normal)` at entries.c:1817, and the second checker draft
  had already dropped it on that basis. `bufpt` (first draft's survivor):
  reassigned to the stack array `buf` before the flagged dereference.
- **The whole catalogue, no escape to key on** (2026-09-10, the twelve
  checkers of https://github.com/edtice-goog/pathout-shapes in one
  `cov-analyze --disable-default` with twelve `--codexm`, then
  `pathout_filter.py --relevant auto` against the `--print-paths` log of
  the same idir; all captured with linux64-2026.6.0 and analyzed with
  win64-2026.6.0):

  | project | functions | PATHOUT | hits | in PATHOUT functions | relevant | analysis |
  |---|---|---|---|---|---|---|
  | nginx 1.26.0 | 1,374 | 18 | 159 | 4 | **2** | 15 s |
  | zstd 1.5.6 | 1,852 | 12 | 666 | 167 | 60 | 14 s |
  | redis 7.2.4 | 7,440 | 27 | 869 | 76 | **0** | 24 s |

  The two nginx survivors are one candidate (`params[index]` in
  `ngx_http_ssi_body_filter`, where `OVERRUN_SYMBOLIC` pathed out); 57 of
  zstd's 60 sit in `main` and most name the macro variable `__nb`, a
  same-name-local artefact of macro expansion (the checker keys locals by
  identifier). Neither was read or fuzzed here, so that the idirs stay
  usable for a blind trial of the skill.
- **Three checker defects found by reading hits, all fixed the same day**:
  an unparenthesized `exists .. where P || exists .. where Q` nests the
  second `exists` inside the first's `where` (an empty leading collection
  made three guards silently false; the fixtures had passed because every
  fixture function had an `if`); `p[i]` on a pointer is a dereference of
  `p + i`, not a `subscriptReference`, so every `p[0]` was invisible to the
  dereference matcher; and `while ((p = f()) != NULL)` was not a test of
  `p` because the operand is an assignment, which turned zstd's `readdir`
  and `strchr` loops into candidates. `sizeof_pointer_as_size` first
  reported 32 sites in redis, all `memcpy(&x, &p, sizeof p)` copying a
  pointer value on purpose; it now requires the pointer to be the direct
  destination or source, and reports 0 there.

## Reasoned, not measured

- That the `_pass2` suffix is the FPP-enabled second pass described in the
  Extend SDK guide (*Two-pass checking*). Consistent with `DEADCODE_pass2`
  running to ~5000 where `DEADCODE_pass1` needed ~700; not documented.
- That `REVERSE_INULL`'s state is what multiplies in `setup_env`: inferred
  from the checker's documented behaviour and the counts over the body (55
  NULL comparisons, `c` tested 15 times). The scoped run names the checker;
  it does not print the state.
- The `FUNCTION.metrics` short keys (`cc`, `pce`, `pcs`, `lc`, `ml`, `hf`,
  `hr`, `be`, `fe`): mapped to Connect's documented Functions-view columns
  (CCM, Acyclic Path Count, APC statements-only, Line Count, Halstead
  Effort/Errors, Backedge/Forwardedge Count) by value and name; `ml` verified
  against `declared at:`. The keys themselves are undocumented.
- That a pathed-out deriver (`*_DERIVERS`) leaves callers with a weaker
  model. Follows from what derivers are for; not measured.

## Not verified

- Whether Connect surfaces the notice anywhere (not checked against a
  commit).
- The threshold at which the `Exceeded path limit ... %` summary line
  appears (somewhere between 0.19% and 1.11%).
- Why some components report `10001` rather than `5001`.
- Any Java, C#, or other non-C/C++ language: all runs were C and C++.
- The coverity CLI's `analyze.cov-analyze-args` setting (documented in
  `doc/configuration-schema.json` as "Additional arguments to pass to
  cov-analyze") as the way to pass `--paths` / `--print-paths` through
  `coverity analyze` -- read in the schema, not exercised.
