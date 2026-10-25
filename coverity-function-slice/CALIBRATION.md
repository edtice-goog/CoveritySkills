# Calibration status

This project's standard is that factual claims in a skill were established by
real runs. This file records what was run for `coverity-function-slice`, on what,
and what is reasoned rather than measured.

Environment: Windows 11, installations under `C:\Coverity\`. Three analyzer
versions were used, each against an idir it wrote:

| idir | written by | size | analyzed with |
|---|---|---|---|
| proftpd 1.3.9 (a cov-build capture under WSL), 149 C files, 2102 functions | 2025.9.0 (cov-build, gcc, WSL) | 2 GB | 2025.9.0 win64, scratch copy |
| subversion 1.14 + sqlite amalgamation, 9533 functions (an MSVC capture) | 2026.3.0 | 185 MB | 2026.3.0 win64, scratch copy |
| fixtures (`evals/fixtures/*`), emitted with bare `cov-emit --c` / `--c++` | 2026.6.0 | -- | 2026.6.0 win64 |

All dates 2026-09-09.

## Verified by direct execution

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
- **C++ free functions (PR #1, merged 2026-09-10).** Reported there, not
  reproduced here: a 12-parameter
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
- **Two pretty-printer forms that are not C, found on nginx (2026-09-10;
  nginx 1.26.0 idir captured with linux64-2026.6.0 under WSL, gcc 13.3,
  `--c17`; sliced with win64-2026.6.0).** Of the 18 PATHOUT functions,
  8 sliced to a file cov-emit accepted (`Emit ... complete.`) but with
  `warning #1563: function "<name>" not emitted`; the analysis log then had
  no `wur:` line for the function and the tool printed only
  `paths_exceeded count: 0`, which read as "no PATHOUT".
  - `for (;;)` is pretty-printed as `for (; true; )` and `for (i = 0; ;
    i++)` as `for (i = 0; true; i++)`. `true` is not a keyword in C17 and
    the slice includes no `<stdbool.h>`: `identifier "true" is undefined`.
    Six functions: `ngx_init_cycle` (TU 25),
    `ngx_http_fastcgi_process_header` (107), `ngx_http_header_filter` (83),
    `ngx_http_ssi_parse` (86), `ngx_http_upstream_process_header` and
    `ngx_http_upstream_process_upgraded` (79). Fixed by `#define true 1` /
    `#define false 0` in a C slice (not in C++, where they are keywords).
  - A function-local unnamed enum is pretty-printed as `enum <anonymous>;`
    and each use as `enum ngx_http_parse_complex_uri::[unnamed type of
    'state'] state;`. The emit names it
    `_ZZ26ngx_http_parse_complex_uriE$Uu5state_` (`find --kind e
    --print-debug` returns its `enumerators`), and the slicer already
    rendered it at file scope as `enum __cov_anon_e10 {...}`; only the
    body was wrong. Two functions, both in TU 73:
    `ngx_http_parse_complex_uri` and `ngx_http_parse_request_line`. Fixed
    by respelling the body's `fn::[unnamed type of 'var']` to the tag and
    dropping the `<anonymous>;` declaration. The same form covers an
    unnamed struct (`$Uu5tally_`) and an unnamed enum with no variable
    (`$Ua5LIMIT_`, listed by `find` as `[unnamed enclosing type of
    'LIMIT']`), both exercised by `evals/fixtures/local_enum_forever.c`.
  - After the fixes, 7 of the 8 emit clean and analyze:
    `ngx_http_header_filter` 5001 PATHOUT (`OVERRUN_pass1`,
    `generic_DERIVERS`; original: those two plus `FORWARD_NULL_pass2`,
    `OVERRUN_SYMBOLIC_pass1`, `uninit_DERIVERS`), `ngx_http_parse_complex_uri`
    PATHOUT on `DEADCODE_pass2` at 10001 (original: same),
    `ngx_init_cycle` 2683 paths, `ngx_http_fastcgi_process_header` 3603,
    `ngx_http_upstream_process_upgraded` 348,
    `ngx_http_upstream_process_header` 110, `ngx_http_ssi_parse` 0 (the
    originals of those five all pathed out at 5001 or, for `ssi_parse`,
    7151 on the `with extra_info` line: the loss of callee models is what
    the slice's caveat says it is, and for these five it takes the count
    under the limit).
  - **Still failing: `ngx_http_parse_request_line`.** A third form: nginx's
    `ngx_str6cmp` macro contains `(((uint32_t *) m)[1] & 0xffff)`, which the
    pretty-printer writes as `((uint32_t *)m[1] & 65535)` -- the
    parentheses around the cast are dropped, so the subscript binds first
    and cov-emit says `expression must have integral type` (slice lines 452
    and 456). At the time not rewritten, because the printed text is the
    same for a genuine `(T *)m[1]`; since 2026-10-24 the tree decides (the
    *subscript bases* entry below).
  - `--analyze` now reports the missing `wur:` line as `COULD NOT VERIFY`
    (with `function "<name>" not emitted, see cov-emit.log` when cov-emit
    said so), suppresses the misleading count line, and exits 2; the
    `cov-emit:` line says `NOT EMITTED` and quotes the first diagnostics.
    Exercised on the fixture slice with the `true`/`false` defines removed
    by hand: `NOT EMITTED: function "local_enum_forever" (warning #1563
    ...)`, `line 48: warning #20: identifier "true" is undefined`, `COULD NOT
    VERIFY`. Also exercised on the nginx slice above, whose diagnostics
    cov-emit wraps at 80 columns with the function name on the
    continuation line: the detector unwraps the log first.
  - Two Windows facts from the same run: cov-emit fails with `Could not
    create unique lock file ... emit-db.creation-lock-<32 hex>` when the
    output idir path is long (a 230-character `--out`; the same slices
    emitted from a 60-character path),
    and `evals/fixture.sh` must be given a short `workdir` for the same
    reason.
- **Struct and enum lookups are TU-scoped (found by the redis blind run,
  2026-09-11; fixed 2026-09-15).** `fetch_class`/`fetch_enum` searched the
  whole emit, so six of redis's thirty slices received another TU's
  definition of `dict` (hiredis's beside redis's), `dictType` or `config`
  (redis-cli's, for the benchmark `main`) and cov-emit dropped the
  function (`warning #136: struct "dict" has no field "ht_used"`, then
  `#1563 not emitted`). The lookup now tries `--tu <N>` first and falls
  back to the whole emit for tags the TU only declares. Verified here:
  `main` (TU 272) and `stats_arena_bins_print` (TU 168) emit clean; the
  fixture passes unchanged. The blind run's own four-line patch fixed
  five of its six; the sixth (`genRedisInfoString`) failed on
  `__atomic_load` with a folded `sizeof` (below).
- **Six pretty-printer forms from the zstd and redis blind runs
  (2026-09-11), rewritten 2026-09-15** and verified on the five real
  functions that had needed hand edits, each now emitting clean and
  reproducing its original PATHOUT as a slice (win64-2026.6.0 against the
  WSL-captured idirs): zstd `BMK_benchMemAdvancedNoAlloc` (`1e+09.` x2;
  four `(BYTE const *)srcBuffer[u]` sites rewritten after cov-emit
  rejected them; `OVERRUN_SYMBOLIC_pass1` 5001), `ZSTD_compressBlock_lazy_
  generic` (`[[maybe_unused]]`, `size_t offBase = ((void)0) , ((void)0) ,
  1;`, and `start - (...)[-1]` rewritten after a diagnostic;
  `DEADCODE_pass2` 10001), `FIO_compressZstdFrame`
  (`FIO_compressZstdFrame::speedChange_e`; 10001), redis
  `genRedisInfoString` (seven `__atomic_load(8UL, p, &tmp, order)` sites
  and the emitted `__atomic_load` prototype; `DEADCODE_pass2` 10001, as in
  the original), nginx `ngx_http_parse_request_line` (the `ngx_str6cmp`
  cast, the one PR #2 left; 5001 on the same seven components). The
  diagnostic-driven retry ran once for each of the three that needed it;
  the ambiguous form compiled nowhere as written, so no `note` fired.
  `evals/fixtures/pretty_forms.c` reproduces five of the six under bare
  `cov-emit --c` (`[[maybe_unused]]` does not parse there, so it is not in
  the fixture); `__ATOMIC_RELAXED` has to be defined in the fixture because
  bare mode has no gcc predefines.
- Preprocessed-TU route: `cov-manage-emit --tu 1 preprocess` on the
  subversion idir (2026.3.0, MSVC) wrote `output/preprocessed/fs-util.c.1.i`
  in 7 s; `cov-emit` of that file with the recorded flags minus
  `-I/-D/--sys_include` succeeded; `cov-analyze` analyzed 12 functions.
  Not runnable for the WSL-built proftpd idir on Windows: the recorded
  `cov-emit` is a Linux binary.
- **Subscript bases printed bare, and `sizeof` folded (2026-10-24).**
  Measured on a fixture (`evals/fixtures/pretty_forms.c`, `cov-emit --c`,
  2026.6.0, `--print-definitions` beside `--print-debug`): the printer
  parenthesizes by precedence everywhere except a subscript base, which it
  prints bare whatever it is. `(*rr)->id`, `(*fp)(a)`, `(a + b) * c` and
  `-(a + b)` all survive; `(*f())[c]` prints as `*f()[c]`, `(*p)[1]` as
  `*p[1]`, `(p + 1)[c]` as `p + 1[c]`, `((T *)p)[i]` as `(T *)p[i]`. The
  first two type-check as a different expression (index the pointer, then
  dereference), so the emit accepts them and a slice built from them
  computes something else; the others do not parse. The `--print-debug`
  tree keeps the structure, so the slicer renders each offending base from
  the tree the way the printer spells it, locates it as `<base>[` and
  parenthesizes it. The fixture's six sites repair and the slice emits with
  no diagnostic; its obfuscated twin verifies identical (`evals/fixture.sh`).
  Two limits, both exercised on the fixture: text that also occurs with
  the other meaning is counted, not guessed (`*opt[` twice for one site:
  reported by source line); a base the renderer cannot spell (a
  conditional, a comma expression) is reported by source line, and the
  comma form still goes through the diagnostic-driven rewrite. The folded
  `sizeof` is restored from the printer's own comment, `8ULL /* sizeof (&r)
  */` to `(sizeof (&r))`, so that a BAD_SIZEOF or SIZEOF_MISMATCH survives
  re-analysis and a slice built with another pointer size computes its own
  value; it stays folded when it names a struct the slice does not define,
  is folded back on a cov-emit diagnostic, and `--fold-sizeof` keeps the
  constant throughout. Re-run on real code the same day: nginx
  `ngx_http_parse_request_line` (TU 73; the `ngx_str6cmp` cast that needed
  the diagnostic round before now repairs from the tree, no round) and
  proftpd `parse_list_opts` (TU 78, 2025.9.0; glibc's `(*__ctype_b_loc())[c]`
  and `(*opt)[1]`, both of which had emitted as the wrong expression). The
  numbers are in the fixture run's transcript; nothing from a non-public
  codebase was used.

- **A set of functions in one file (2026-10-24).** `--name` repeated;
  `evals/fixtures/slice_set.c` (+ `slice_set_tu2.c` as TU 2), 2026.6.0,
  bare `cov-emit --c`:
  - caller + `static` callee (`set_caller`, `set_callee`): both defined,
    the callee's `static` dropped from prototype and definition; the
    one-file idir reports **FORWARD_NULL** in the caller (the null-tested
    pointer passed to the callee that dereferences it), which the caller
    sliced alone does not report (the callee is a prototype there, `0`
    FORWARD_NULL files). Twin verifies identical per member (4 and 1 paths).
  - mutual recursion (`set_odd`, `set_even`, both `static`): emits clean
    from the prototype block; per-member path counts came out 2/3 in the
    slice and 3/2 in the twin, 5 in both -- the analyzer's order within the
    pair decides the split, and `verify` reports `preserved up to analysis
    order within the set`.
  - one member + a non-member callee (`set_caller` alone): `set_callee` and
    `set_helper` stay prototypes; same filenames and lines as before the
    change, plus the line-1 comment.
  - two TUs defining `struct rec` differently (`set_caller`,
    `set_other@2`): `conflict: struct rec: defined differently in TU 1 and
    TU 2`, `COULD NOT VERIFY`, exit 2, the slice written with TU 1's shape
    for a reader.
  - nginx 1.26.0 (WSL capture, 2026.6.0, analyzed on win64): the static
    pair `ngx_http_upstream_send_response` + `ngx_http_upstream_finalize_
    request` (TU 79) slices to 1,449 lines (130 typedefs, 36 structs, 28
    prototypes) and emits and analyzes in 38 s end to end; the caller alone
    is 1,301 lines in 33 s (1443 vs 433 paths for the caller: the callee's
    code is now walked). A two-TU set, `ngx_http_parse_complex_uri` (TU 73)
    + `ngx_http_upstream_finalize_request@79`, emits clean with no conflict
    and reproduces the parser's `DEADCODE_pass2` 10001 PATHOUT.

- **The whole TU for the harness route (`tools/tu_manifest.py`,
  2026-10-25).** What the emit supplies, measured on nginx TU 79
  (`ngx_http_upstream.c`, Linux/gcc 13.3.0 capture) with win64-2026.6.0 and
  on the `slice_set.c` fixture (bare `cov-emit --c` on Windows):
  - `print-source-files --tu 79` lists 290 files: the primary, 69 project
    headers, 214 system headers (`/usr/include`, `/usr/lib/gcc`), the two
    configuration compat headers. `extract-files --tu 79 --regex .` writes
    all 290 under the output dir with drive letter and leading slash
    removed (`/home/x/...` -> `files/home/x/...`, `/mnt/c/...` ->
    `files/mnt/c/...`, `C:/Data/...` -> `files/Data/...`).
  - `print-source` is **not** byte-exact on Windows: its stdout is in text
    mode, so a CRLF source came back as CR CR LF (2,229 bytes for a 2,170
    byte fixture). The extracted copy is identical to the original file
    (`cmp`); `tu.c` is written from it, and `print-source` only when
    extraction was skipped.
  - One `find . --kind f --print-definitions` dump (136 KB, 93 functions)
    gives every definition's signature; `static` is read off it (85 of 93
    static; 4 defined in headers, `ngx_array_init` and the like). One
    `find . --kind f --print-callees` dump (76 KB, 301 callee entries, 152
    with a `defined in TU` line) gives the externals: 85 functions called
    and not defined, 8 of them library by declaring path, 77 project; with
    `--models` pointing at a `cov-find-function --save` directory holding
    one model, that one (`ngx_pnalloc`) is marked. Model `.dot` files name
    their function in `digraph "name:module"`.
  - `print-compilation-info --detailed` replaces the invocation lines with
    the process records (working directory, platform, exit code); the tool
    reads both forms. Working directory `/home/<user>/campaign/nginx`
    resolves the relative `-I` paths.
  - **Compiling from `files/` alone**: the recorded `cov-emit` flags with
    `-I`, `--sys_include` and `--pre_preinclude` remapped under `files/`
    re-emit the TU on Windows (exit 0, 93 functions). The real gcc 13.3.0 on
    the capture platform: `-fsyntax-only` exit 0 (55 s across the `/mnt/c`
    mount); `-c -O0 -nostdinc` with `files/` includes exit 0, object with 93
    defined and 104 undefined symbols; `-c -O -D__OPTIMIZE__` from `files/`
    alone **fails** on `bits/select2.h`, a glibc header opened only under
    optimization that the capture's front end never requested; with the
    platform's real system include directories appended after `files/`, or
    with `files/` for project headers and the platform for system headers,
    `-c -O` exits 0 (76 defined symbols: the optimizer inlined 17 statics).
    Recorded as `compile_hints` in the manifest.
  - A long `--out` on Windows: one compat header's extracted path exceeded
    260 characters and `os.path.exists` said it was missing although
    `extract-files` had written it; the tool now uses the long-path prefix
    and warns when the layout is within reach of the limit.
  - Fixture (`slice_set.c`, TU 1): 6 functions (4 static), 2 externals
    (`lookup`, `log_missing`, both project), target `set_callee` static ->
    the `static` note; `tu.c` identical to the fixture source; exit 0.
    A non-static target (`ngx_http_upstream_init`, `--no-files`) produced
    no failure note beyond the platform one.

## Reasoned, not measured

- That a slice whose callees are unmodeled prototypes can only *lose*
  path-sensitive facts relative to the original analysis, never gain them.
  Consistent with every measurement so far (five nginx functions under the
  limit as slices, none over); not proven.

## Not verified

- Any Java, C#, or other non-C/C++ language: all runs were C and C++.
- The slicer against an idir written by a version older than 2025.9.0.
- `--obfuscate` on a function whose strings carry the semantics (a parser
  keyed on literal keywords): the same-length masking keeps `%` directives
  and lengths, not contents, so a path that depends on a string comparison
  against a literal may change. Not measured.
