# Calibration status

This project's standard is that factual claims in a skill were established by
real runs. This file records what was run for `coverity-fuzz-triage`, on what,
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
- Work products under `C:\Data\fuzz-triage-work\proftpd\` (slices,
  models, harnesses, `RESULTS.md`); not in the repository.

## Reasoned, not measured

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
