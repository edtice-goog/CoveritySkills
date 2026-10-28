# Calibration status

This project's standard is that factual claims in a skill were established by
real runs. This file records what was run for `coverity-verify` (formerly
`coverity-fuzz-triage`), on what,
and what is reasoned rather than measured.

Environment: Windows 11, installations under `C:\Coverity\`. Three analyzer
versions were used, each against an idir it wrote:

| idir | written by | size | analyzed with |
|---|---|---|---|
| proftpd 1.3.9 (a cov-build capture under WSL), 149 C files, 2102 functions | 2025.9.0 (cov-build, gcc, WSL) | 2 GB | 2025.9.0 win64, scratch copy |
| subversion 1.14 + sqlite amalgamation, 9533 functions | 2026.3.0 | 185 MB | 2026.3.0 win64, scratch copy |
| fixtures (`evals/fixtures/*`), emitted with bare `cov-emit --c` / `--c++` | 2026.6.0 | -- | 2026.6.0 win64 |

All dates 2026-09-09.

## Verified by direct execution

- **Fuzz confirmation on the fixture** (`lookup.c` + `use.c`, 2026.6.0,
  clang-cl from `C:\Program Files\LLVM`, LLVM 22): candidate at `use.c:18`;
  slice of `escaped` (2 prototypes); `lookup`'s generic model has two
  behaviours (non-null, `returnsnull`); harness + stub built with
  `-fsanitize=fuzzer,address -Zi -Od`; ASan access-violation at address 0
  in `escaped` at `sink(r->id + v);` within the first second; crashing
  input `0a 0a 41 0a`. `evals/run.sh` reproduces the chain.
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

### The proftpd batch (2026-09-15)

Ten ordinary findings from the demo-data proftpd 1.3.9 idir (2025.9.0,
WSL/gcc capture; 147 findings in all: 52 NULL_FIELD, 47 FORWARD_NULL, 16
SIZEOF_MISMATCH, 9 DEADCODE, ...), chosen to span the tiers: three
NULL_RETURNS on libc string functions, five FORWARD_NULL of different
flavours, one REVERSE_INULL, one OVERRUN. Each: slice (2025.9.0),
`cov-find-function --save` for every project callee (~3.5 s each, 60
models), `fz_target.py`, clang 18 under WSL with `-fsanitize=fuzzer,
address`, 30-90 s budgets, `-detect_leaks=0 -timeout=10`.

| finding | verdict | evidence |
|---|---|---|
| NULL_RETURNS parser.c:1231 `parse_config_path2` | refuted by execution; under the bare model it "confirms" through a behaviour the callee cannot have | `pstrdup`'s model (allocates, may return null, contents unconstrained) made `strrchr` return NULL on the first input; with `--semantic pstrdup`: 13.8M inputs, line reached 373,813 times, never false |
| NULL_RETURNS mod_log.c:339 `set_extendedlog` | refuted by execution | real `strncasecmp` + `strchr`: 21.2M inputs, reached 24,587-418,819 times, never false |
| NULL_RETURNS mod_log.c:1324 `log_sess_init` | refuted by execution | 7.35M inputs, reached 119,861 times, never false |
| FORWARD_NULL hanson-tpl.c:260 `tpl_node_new` | hook-sourced | claim false on the empty input with `malloc -> NULL`, `fatal -> returns`; the project's default `tpl_fatal` exits. Same class by reading: hanson-tpl.c:637 and most of the file's 40 FORWARD_NULLs (`fatal_oom()`) |
| FORWARD_NULL mod_core.c:6664 `core_post_pass` | global-sourced | `main_server == NULL` is the harness's choice; nothing in the function decides it |
| FORWARD_NULL data.c:576 `pr_data_open` | model gap, refuted | claim false with `data_active_open = zero_return`; its generic model records no write of `session.d`; data.c:271 and :392 assign it |
| FORWARD_NULL mod_delay.c:2177 `delay_shutdown_ev` | model gap, refuted | claim false with `delay_table_load = zero_return`; no write of `delay_tab.dt_data` in the model; mod_delay.c:730 mmaps into it |
| REVERSE_INULL mod_ls.c:1931 `dolist` | refuted by execution, a path the analyzer missed | `opt == NULL`, `have_options` returns 0 (its model has no dereference of `arg 1`; the source stats it), the check `if (arg && *arg)` reached with NULL on the first input: the check is not redundant |
| OVERRUN glibc-glob.c:786 `glob_limited` | refuted by execution; **bycatch: a real 1-byte stack overflow** | focused on `~/`: 9.1M inputs, the named alloca reached 3,130,966 times, no ASan report (the `dirlen` copy from `dirname + 1` includes the NUL). Free run: `dynamic-stack-buffer-overflow` at the `~user` copy, `alloca(end_name - dirname)` then `mempcpy` of that many bytes plus a NUL (glibc-glob.c:809-811, the HAVE_MEMPCPY branch; the memcpy branch is correct). Not among Coverity's 147 findings |

Totals: 0 confirmed, 5 refuted by execution, 2 model gaps, 2 sourced by
the harness (hook, global), 1 by reading; 1 real defect as bycatch; 2 of
the 12 chosen not taken (`tpl_map_va`, `tpl_peek`: variadic targets).

- **Bycatch class.** Under the models every pool allocator (`make_array`,
  `push_array`, `pdircat`, `add_config_param`, `pstrcat`, `mod_create_ret`)
  has a `returnsnull` edge and the code checks none of them; in free mode
  each run ended on one of those before the finding's line (three in a
  row on `parse_config_path2`, at `file_list->nelts`, `*push_array(...)`,
  `c->argv[0]`). They are the NULL_RETURNS the analyzer suppresses
  statistically. Focused mode (`--pin-normal`) is what made the runs
  answer the question asked.
- **Tooling facts, in the order they were paid for**: WSL is the build
  platform for a Linux capture (LP64, glibc: `__errno_location`,
  `strncasecmp`); the support header may include no system header (the
  slice defines `struct stat`, `struct timespec`, `size_t`) and must
  precede the slice (`__fz_claim` is used inside it); one `__stub_choice`
  per call (a fresh call in every `if` consumed a byte per branch); scalar
  returns follow the model's `== K` / `negative_return` / `zero_return`
  edges; variadic prototypes; function-pointer parameters (`void
  (*)(const void *, void *)`) must not be split on their commas;
  `write(<arg N>->f)` edges are reproduced only when the struct is complete
  in the slice; a zeroed non-null object crashes the first `c->argv[0]`, a
  pointer-filled one walks `c->argc` off the end (the harness sets the
  integers that bound loops); LeakSanitizer and libFuzzer's RSS limit both
  end long runs on stub allocations (`-detect_leaks=0`, per-input arena);
  a seed on the analyzer's path took a line from once in 7,617 inputs to
  hundreds of thousands.
- The work products (slices, models, harnesses, the per-finding results)
  are not in the repository; the tools and this record are.

- **The CID entry point, measured 2026-10-02** against a hosted Connect
  2026.9.0 (HTTPS, an administrator's authentication key, five proftpd streams, 112
  issues in `proftpd-1.3.9`'s newest snapshot 10024). `connect_auth.py
  check`: VALID. `getSnapshotsForStream` over SOAP with the key as the
  WS-Security password: works over HTTPS. `issues/search`: a `cid`
  `idMatcher` filter **alone** is accepted with HTTP 200 and returns
  `totalRows -1`, no rows (the same for `id` as a string or without
  `class`); an `intRangeMatcher` on `cid` is a 400 and a `keyMatcher` a
  500; **beside a stream filter it returns exactly the one row**. Column
  keys `cid`, `checker`, `displayType`, `displayImpact`, `displayFile`,
  `displayFunction`, `lineNumber`, `mergeKey`, `firstSnapshotId`, `cwe`,
  `status`, `classification` come back; `stream`, `project` and
  `lastSnapshotId` are accepted and absent from the rows. End to end: CID
  10206 -> `NULL_RETURNS`, `/src/parser.c`, `parse_config_path2`, line
  1231, merge key `ddde6577...`; `select` on the local v1.3.9 idir's
  findings by that merge key printed the same issue with its events,
  which is the hand-off into Step 0. Lookup by `--project proftpd
  --snapshot 10024` works the same way. The tool now sends stream (or
  project) and cid filters together and scans only if the row still does
  not come back. A CID lookup needs no skill, any REST client does it; the tool is a convenience so the merge key lands in the
  right place.

### The fix check (2026-10-07)

- **The fixture** (`evals/run_fixcheck.sh`, 2026.6.0 win64, clang-cl):
  A = `use.c`, `FORWARD_NULL` at line 18, confirmed on A with `lookup=1`
  on `0a 0a 41 0a`. B1 (`fixcheck/use_fixed.c`, `if (r == 0) return -1;`):
  no finding in `escaped`; replaying `c` reaches the line 0 times; 20 s of
  fuzzing: 6,038,165 inputs, line reached 4,435,314 times, claim never
  false. **Fixed.** B2 (`fixcheck/use_silenced.c`, the dereference moved
  into `rec_id()`, a helper outside the capture): no finding in `escaped`;
  with `rec_id` compiled in as real code (`--keep rec_id`, body in the
  harness) the claim fails on `c` at once, replayed and fuzzed. **Silenced,
  not fixed.** A first candidate silencer, `r = keep(r)` through an
  unmodelled helper, did **not** silence: `FORWARD_NULL` keys on the
  explicit null test, not on where the pointer came from, and the toggle
  still showed the finding (at line 23). Whole run: about four minutes.
- **OpenSSL 3.0.7 vs 3.2.0** (2026-10-05..07, the run that motivated the
  fix check: 2026.9.0 linux64 under WSL, clang 18, gcc 13.3; its outputs
  are kept outside the repository and were read, not re-run, for this
  record): `cipher_hw_des_cfb1_cipher`, `UNINIT` on `d[0]`, merge key
  `e93ca9ad...`; the change `unsigned char d[1] = {0};`. F on A: refuted
  by execution with the real callee (151,417,888 reaches / 2,315,328
  inputs; re-poisoned per call 124,267,264 / 1,905,085, never false; the
  model stub and the length-0 control caught at the first reach: model
  gap, the derived model never records the write to `out`). Body
  equality: 3.0.7 == 3.2.0 minus the initializer, callee unchanged.
  Toggle: `fixed.c` no findings, `unfixed.c` `UNINIT` at the read.
  Differential under MemorySanitizer with the real 3.2.0 callees: 746,679
  inputs, 75,614,760 bits, 0 mismatches. **Silencing change,
  behaviour-neutral**, which matches the
  upstream commit message. Three siblings (CIDs 12591, 12308, 12374)
  gave the same result. The vacuous-claim pitfall was found here: the
  original MSan claim is true by construction after the initializer.

### The slice set (2026-10-24)

- **The fixture** (`evals/run_sliceset.sh`, 2026.6.0 win64, clang-cl,
  `evals/sliceset/pair.c`): `get_value` dereferences `pick`'s result
  without a test; `pick` returns NULL for a negative id and `get_value`
  never passes one. Both carry a primary event of the finding. `pick`'s
  derived model: `<arg 0> < 0` then `returnsnull`, `<arg 0> > -1` then
  `!= 0` -- a precondition the stub cannot act on, so as a stub the null
  branch is a free choice. The default analysis reports nothing here (the
  path-sensitive run honours the precondition), which does not matter to
  the test: the question is what verification does with the two shapes.
  Slice set `--name get_value --name pick`: line 1 `/* slice-set:
  get_value, pick */`, two members as code, `cov-emit: emitted`.
  Assembled with `pick`'s model deliberately in the index: the log says
  `slice-set member: compiled as code; its saved model is IGNORED`; 20 s,
  5,865,663 inputs, the finding's line reached 5,865,663 times, claim
  never false: **refuted by execution**. The control, `get_value` alone
  with `pick` as its model stub: the claim fails on the first input with
  `pick=0` (`returnsnull`): the stub adjudicates a false positive as real,
  which is the circularity the rule exists for. The two existing evals
  (`run.sh`, `run_fixcheck.sh`) pass unchanged with the new assembler:
  their single-name slices carry a one-member set on line 1.
- **The proftpd batch re-read for cross-function paths** (2026-10-24,
  2025.9.0 win64 against the same idir): for each of the ten findings,
  the path events (every event except the `example_*` ones, which are
  the statistical evidence a `NULL_RETURNS` cites from other call sites
  and other files, and name no function on the path) were taken from the
  v10 entry, and the emit was asked, per TU (`find . --kind f`), which
  functions are declared inside the events' line range. C functions do
  not nest, so an empty answer means every path event is in the home
  function. All ten came back empty: every path lay inside its home
  function (`parse_config_path2` 1165-1231, `set_extendedlog` 323-339,
  `log_sess_init` 1194-1328, `tpl_node_new` 257-260, `core_post_pass`
  6640-6664, `pr_data_open` 523-576, `delay_shutdown_ev` 2133-2177,
  `dolist` 1921-1947, `glob_limited` 447-918, `tpl_free_keep_map`
  586-667). The slice set of each is its home function, the batch's
  verdicts stand as made, and nothing was re-verified. The `example_*`
  events of the three `NULL_RETURNS` do point into five other files
  each; a first, naive owner pass that counted them would have named a
  five-function "set" for every one, which is why the resolution step in
  Step 0 excludes them.

### The router and the harness route (2026-10-25)

- **The fixtures** (`evals/run_harness.sh`, 2026.6.0 win64, clang-cl).
  A: `evals/harness/app.c` (handle copies `lookup_cfg`'s result without a
  test; a static helper and a real `<string.h>` in the TU) beside
  `cfg.c` (`lookup_cfg` returns NULL for an unknown key) in one idir. The
  TU manifest (`coverity-function-slice`'s `tu_manifest.py`): 2 functions
  defined, 3 externals (`lookup_cfg` with a model; `strlen`, `strncpy`
  libc), no notes. Router, preferred harness (the default), with a
  compile attempt: **applies**. `fz_harness.py`: the TU included with one inserted line
  (the claim), `trim` and `handle` as code, `lookup_cfg` a 2-behaviour
  model stub, libc real; built with clang-cl against the real header; the
  claim failed on the first inputs through `lookup_cfg=0`
  (`returnsnull`), which the real `lookup_cfg` has: confirmed, route
  harness, compile mode source tree, record `as_code [trim, handle] /
  stubbed [lookup_cfg]`. The manifest tool's externals carry `kind`
  (`library`/`project`) and `model`; the prototypes for the stubs come
  from the emit (`fz_harness.py --dir --bin`), the manifest's `signature`
  being filled for the target.
  B: `evals/harness/declined/app2.c` includes a header found only
  through `-I` at capture time, and its target is static. The manifest is
  built with `--no-files` (as when `extract-files` is unavailable; with
  the files the header is under `files/` and the second compile attempt
  would find it), so it cannot supply the header; the compile attempt fails with `fatal error:
  'local.h' file not found`; the router finds harness **does not apply**, with that diagnostic
  as the reason, notes that the static target alone would not have (the
  TU is included, not linked), and the run **stops**: `route null`,
  `applicable false`, the blocker in the record, no extraction run; the
  eval checks that nothing ran unasked. Preferred extraction on A's
  manifest is honoured as given. The three earlier evals pass unchanged
  with the changed support header. **Harness sufficed** for A, the one
  public-fixture finding tried on it so far.

- **proftpd, public code, the route is open.** The capture's own
  compiler invocation is recorded per TU (`print-compilation-info`:
  `gcc -DHAVE_CONFIG_H -DLINUX -I.. -I../include ... -c data.c`), the
  working directory is not, and it is the source file's directory here.
  From that directory, with the source tree the capture was built in
  still present (its `config.h` is a build product), four TUs compiled
  under WSL clang 18 with `-fsyntax-only` and the recovered flags: data.c,
  mod_core.c, hanson-tpl.c, glibc-glob.c. The manifest of data.c (TU 44,
  home of the batch's `pr_data_open` FORWARD_NULL): 22 functions defined,
  77 externals (19 with a model in the batch's saved set, 11 libc, the
  rest project functions whose models the batch had not saved; `fcntl`,
  `recv`, `select`, `sendfile` are libc the LIBC list does not yet name),
  5 data externals the driver would define (`session`, `main_server`,
  `resp_list`, `resp_err_list`, `ServerUseReverseDNS`), no notes; the
  router, preferred harness with a compile attempt: applies; preferred
  extraction: honoured. **Not done**: a driver for `pr_data_open` and the run
  itself; the route's cost on a TU of this size is the driver's state
  (five globals of the server's types) and the models for 40-odd
  externals, each `cov-find-function --save` at a few seconds.

## Reasoned, not measured

- That the slice set is the right target in general. The rule follows
  from what a stub is (the analyzer's belief about a callee): a stub for a
  function on the finding's own path lets a model edge produce the claimed
  state by construction. The fixture above shows it happening once; the
  proftpd batch (below) had no finding whose path crossed functions, so
  it neither confirms nor contradicts the rule on real code.

- The automatic detection of a vacuous claim in a fix check (B with the
  blamed callee pinned to the behaviour that made the claim false on A):
  stated from mechanism; the OpenSSL case was recognised by reading.
- That a stub printed from the derived model can only take behaviours the
  analyzer granted the callee, so a crash through it is a path the analyzer
  would have accepted. Follows from what the model is; the subversion
  NULL_RETURNS experiment is consistent with it.
- The assertion oracle for claims that do not crash (`REVERSE_INULL`,
  `DEADCODE`): described from mechanism, not run.

## Not verified

- Variadic targets (`tpl_map_va`, `tpl_peek`): the harness pattern does
  not cover them.
- A confirmed finding on real code: the batch produced none, so the
  "confirmed by crash under model stubs, every behaviour real" tier has
  been exercised only on the fixture.
- MemorySanitizer, and an `alloc_never_released` claim with the real
  allocator (the arena hides leaks by design).
- The `uninit` model module as a stub source; whether any model module
  records writes to globals (the generic one does not, which is the
  `model gap` tier).
- A DEADCODE claim through the assertion oracle.
- clang-cl on an MSVC-captured idir with the new assembler (the fixture
  run covers the toolchain; no MSVC-captured finding was taken).
- Fix-check rows without an instance: a false positive whose "fix"
  changes behaviour, and *not this change* (the toggle finding nothing in
  either copy).
