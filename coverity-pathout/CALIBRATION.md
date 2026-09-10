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

### Function extraction

- `cov-manage-emit --dir idir --ticker-mode none --tu 77 find '^setup_env$'
  --kind f --print-definitions`: 0.4 s (3.0 s for the first `find` on a
  cold idir), 509 lines / 19,948 bytes for a 963-LOC function. Header
  comment with `declared at:` and `defined in TU 77 with row 1911`; body
  with macros expanded (`PRIVS_ROOT`, `errno` -> `*__errno_location()`,
  `ENOSYS` -> `38`, `PR_LOG_NOTICE` -> `5`), `sizeof(gid_t)` -> `4UL /*
  sizeof (gid_t) */`, `const char *` -> `char const *`.
- Regex is matched against the mangled name in C++: `find 'Widget' --kind f`
  lists `demo::Widget::f(int) /*_ZN4demo6Widget1fEi*/` and
  `demo::Widget::f(double) /*_ZN4demo6Widget1fEd*/`;
  `find '_ZN4demo6Widget1fEd$' --print-definitions` returns only that
  overload.
- `find '^main$'` on proftpd lists seven definitions (TUs 14, 71, 84, 87,
  88, 89, 90); `--tu 14` returns one.
- A miss (`^no_such_function_xyz$`) prints nothing, exit 0.
- Version mismatch: 2026.6.0's `cov-manage-emit` on the 2025.9.0 idir:
  `Expected version number is 355, but this directory has version 350`.
- `--tu 77 print-source` prints three header lines before the file:
  `setup_env` at source line 1035 appears on output line 1038.
- Sizes of the other outputs for `setup_env`: `--print-debug` 75,102
  lines / 3.6 MB; `--print-codexm` 465,718 lines / 34 MB.
- Definition-header line (1035) equals `ml` in `FUNCTION.metrics.xml.gz`.
- Bare `cov-emit --dir idir file.c` (no `--c`) emitted the C file in C++
  mode: names appear mangled (`_Z8many_ifsiiii`) in the log and metrics.
  `--c` gives plain names. The fixture script passes `--c` / `--c++`.

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

### The standalone slice (`tools/slice_function.py`)

- `--print-debug` node shapes read off the output and relied on:
  `function_t{name,dflags,type}`, `function_type_t{return,parameters,
  prototyped,has_C_ellipsis,is_method}`, `global_variable_t{name,dflags,
  type}`, `typedef_type_t{name,target}`, `class_type_t{name,classKey}`,
  `internal_defined_class_type_t{fields}` with `field_t{name,type,index,
  offset}` (`name = <anonymous>` for C11 anonymous members),
  `internal_defined_enum_type_t{enumerators}` with `enumerator_t{name,
  value}`, `pointer_type_t{pointed_to}`, `array_type_t{element_type,
  element_count}`, `cv_wrapper_type_t{target,flags}`, `scalar_type_t{kind}`.
  Same on 2025.9.0, 2026.3.0 and 2026.6.0. No bit-field width key was seen.
- Callees that are only declared (`strlen`, `getenv`) are not findable with
  `find` but their full prototypes are in the calling function's tree.
- `__builtin_va_list` is a typedef to `char *` in the emit; typedefs named
  `__builtin_*` are not re-emitted. `NULL` and `va_start/va_arg/va_end/
  va_copy` survive the pretty-print in macro form and are `#define`d.
- The pretty-printer emits `struct fn::tag` for a function-local struct and
  drops its definition (leaving `struct tag;`), and emits a transparent
  union argument as `TypeName({...})`. Both rewritten; both seen in proftpd
  (`ext_match`, `main`).
- `print-compilation-info` prints argv unquoted; a `--sys_include=C:/Program
  Files/...` arrives as two tokens. The splitter re-joins on the rule "a
  flag written without `=` takes the next token as its value; any further
  non-flag token continues the previous one". Verified on the MSVC-built
  subversion idir (32 flags, one containing a space) and the WSL-built
  proftpd idir (47 flags, `/mnt/c/` paths mapped to `C:/`).
- Emit + analysis results, proftpd 2025.9.0:
  `setup_env` 906-line slice, clean emit, `REVERSE_INULL` pathed out at 5001
  (original: same); `tpl_map_va` clean, `DEADCODE_pass2` at 10001 (original
  `wur:` line: 10001); `listfile` and `facts_mlinfo_fmt` clean and pathed
  out; `main`, `ext_match`, `pr_auth_cache_set` clean, no PATHOUT
  (`pr_auth_cache_set`: 1025 paths, original 1025). Random sample of 15
  functions across 15 TUs: 11 clean on the first run, 15 after fixing the
  anonymous-member and typedef-ordering bugs those 4 exposed. Second random
  sample of 40: see the line below.
- Second random sample, 40 functions (every 50th in `list-functions-v1`
  order, offset 31) across the proftpd TUs, `--emit` only: **40 of 40
  emitted with no recoverable errors**, 85 s in total (about 2 s per
  function, dominated by `cov-emit` start-up).
- Whole slice cycle for `setup_env` (`--emit --analyze`): 15-19 s, most of
  it `cov-analyze` start-up.
- **`--obfuscate`, verified by analyzing both files.** `setup_env`
  (125 fields, 66 functions, 9 globals, 39 locals, 4 params, 15 structs,
  12 typedefs, 1 label renamed; 87 library names kept, all libc/POSIX),
  `listfile`, `tpl_map_va`, `main`, `ext_match` and the fixture's
  `ifs_from_zero`: in every case the obfuscated twin emitted cleanly and
  produced the same path count, the same `PATHOUT` flag and the same set of
  pathed-out checkers as the plain slice (5001/`REVERSE_INULL`;
  5001/`DEADCODE_pass1`+`generic_DERIVERS`+`uninit_DERIVERS`;
  10001/`DEADCODE_pass2`; 656; 0; 5001/four components). The whole cycle
  for `setup_env`, both files, is about 60 s.
- The `DIFFERS` verdict fired during development when a tokenizer bug left
  `->` accesses unrenamed while struct fields were: 50 recoverable errors,
  no function analyzed, reported as `DIFFERS -- slice 5001/True/
  ['REVERSE_INULL'] vs obfuscated None/False/[]`.
- `--print-callees` marks `defined in TU` only for same-TU definitions, so
  project functions from other TUs (`pr_auth_getpwnam`) would have been kept
  under a "defined?" rule; the rule used is the declaring file's path.
- The `Function` node's `formals` list names every parameter, including
  unused ones that never appear as `parameter_t` in the body (the fixture's
  `int a`).
- C++ fixture (`demo::Widget::f(int)`, a non-static method): body
  extracts, slice emits with 3 recoverable errors because the class's
  methods are not reconstructed, and `--obfuscate` leaves `demo` and
  `Widget` on the `review` line. Documented as the boundary; the
  preprocessed-TU route is the path for methods.
- **C++ free functions (PR #1, from an Opus 5 run against a customer TU;
  merged 2026-09-10).** Reported there, not reproduced here: a 12-parameter
  free function in a large real-world C++ TU, 2026.3.0, `--c++`,
  a GCC 10 compiler configuration -- 76 recoverable errors before the change, clean
  after; slice `FORWARD_NULL_pass1` 2578 vs 2580 in the full TU,
  `FORWARD_NULL_pass2` pathed out at 5001 in both; `--obfuscate` went from
  2 of 36 callees renamed and 43 project identifiers left (with `verify`
  reporting `DIFFERS` for the wrong reason) to 36 of 36, 0 unclassified,
  identical analysis. Reproduced here on `evals/fixtures/nested_members.cpp`
  (2026.6.0): a free function calling a static member of a class with a
  nested enum, a flexible-array-member struct and a `__func__` static. The
  slicer places the enum and the static member declaration back inside the
  class body, prints `[]` for the flexible member, names the `__func__`
  static, and both files emit clean and verify identical (5001; four
  components). One fix was needed on top of the PR: the `__func__` static
  is spelled `constexpr`, which is not a keyword under a bare `--c++`
  (the PR's TU carried a C++17 flag), so the rewritten declaration drops it.
- The PR's C-side effects, re-run here on proftpd and the C fixture: all
  verify identical. Its fail-open-to-rename change for globals also renamed
  `stdin`, `stdout`, `optarg`, `optind`, `opterr`, `optopt` on `main`
  (16 -> 22 globals renamed); `STD_GLOBALS` keeps those, and `main` is
  back to 16. Its typedef change renames `typedef struct tpl_node {...}
  tpl_node;` through the struct alias -- the twin contains no `tpl_`, but
  the map lists it as a struct rename (13 -> 6 "typedef" entries for
  `tpl_map_va`).
- `verify` used to compare `(None, False, [])` against itself and call that
  preserved when neither file produced an analysis line. It now reports
  `COULD NOT VERIFY` in that case. Found by the fixture above, before the
  `constexpr` fix.
- Preprocessed-TU route: `cov-manage-emit --tu 1 preprocess` on the
  subversion idir (2026.3.0, MSVC) wrote `output/preprocessed/fs-util.c.1.i`
  in 7 s; `cov-emit` of that file with the recorded flags minus
  `-I/-D/--sys_include` succeeded; `cov-analyze` analyzed 12 functions.
  Not runnable for the WSL-built proftpd idir on Windows: the recorded
  `cov-emit` is a Linux binary.

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
- **Fuzz confirmation on the fixture** (`lookup.c` + `use.c`, 2026.6.0,
  clang-cl from `C:\Program Files\LLVM`, LLVM 22): candidate at `use.c:18`;
  slice of `escaped` (2 prototypes); `lookup`'s generic model has two
  behaviours (non-null, `returnsnull`); harness + stub built with
  `-fsanitize=fuzzer,address -Zi -Od`; ASan access-violation at address 0
  in `escaped` at `sink(r->id + v);` within the first second; crashing
  input `0a 0a 41 0a`. `evals/escape-hunt/run.sh` reproduces the chain.
- **Two Windows facts**: Git Bash rewrites `/Zi` to a path (use `-Zi`);
  the fuzzer exits 127 unless `LLVM\lib\clang\<ver>\lib\windows` (the ASan
  DLL) is on `PATH`.
- **Derived models as stubs** (subversion, 2026.3.0): `cov-find-function
  --save --module generic` takes ~0.25 s per callee and writes a `.dot`
  automaton; stubs for both `svn_dirent_skip_ancestor` and `relpath_depth`
  brought `fetch_conflict_details`'s NULL_RETURNS back in the slice with the
  original event chain; either alone did not; a stub that guarded its
  `dereference(<arg 0>)` with `if (a0)` made the finding vanish. The
  fixture's NULL_RETURNS needed `--checker-option NULL_RETURNS:stat_
  threshold:0` at defaults (one call site cannot satisfy the 80% rule); the
  subversion case under `--all --aggressiveness-level high` did not.

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
