# Calibration status

This project's standard is that factual claims in a skill were established by
real runs. This file records what was run for `coverity-missing-models`, on
what, and what is taken from the documentation or reasoned rather than
measured.

## Verified by direct execution

**`evals/run.sh`, every case as expected, on `cov-analysis-win64-2026.9.0`
and `cov-analysis-win64-2026.6.0`** (Git Bash on Windows). The fixtures are
captured with bare `cov-emit --c` and analyzed at defaults; each model run
analyzes a `cp -a` copy of the baseline idir with `--model-file`, and
`tools/models.py compare` checks it. The results were the same on both
versions, merge keys included.

| case | model | before -> after | what must change | what must not |
|---|---|---|---|---|
| `killpath` | `fail_hard()` -> `__coverity_panic__()` | FORWARD_NULL 2 -> 1 | `fail_hard.c:22` gone | `fail_hard.c:29`, the real one, kept |
| `collision` | `error()` restated: calls `log_msg()`, returns | FORWARD_NULL 0 -> 1 | `report.c:19` new | |
| `arena` owner | `doc_close()` -> `__coverity_free__(d)` | USE_AFTER_FREE 0 -> 1 | `arena.c:164` new (`deref_read_after_free`) | `arena.c:177` (the open twin) and `arena.c:104` silent |
| `arena` destroy | `arena_destroy()` -> `__coverity_free__(a)` | USE_AFTER_FREE 0 -> 1 | `arena.c:104` new: a `double_free` in `arena_clear()`, caused by the model | `arena.c:164` silent: the arena model does not reach the doc |
| `arena` unlink + owner | `arena_destroy()` restating the unlink, plus `doc_close()` | USE_AFTER_FREE 0 -> 1 | `arena.c:164` new | `arena.c:104` and `arena.c:177` silent |
| `pitfall` misspelled | `fail_hrad()` | FORWARD_NULL 2 -> 2 | compare fails: no function took the model; `modelFiles` absent | |
| `pitfall` `size_t` | declares `size_t` | | `cov-make-library` fails: `error #257: invalid redeclaration of type name "size_t"`, declared in `library/primitives.h` | |

Also measured in every model run:

- `cov-make-library` prints `N models successfully merged into output
  file.` (1, and 2 for the two-file library), exits 0, and writes
  `--output-file <name>` as `<name>`, no suffix added.
- The function a model replaces shows `models: ["user1",
  "implementation"]` in `output/callgraph-metrics.json.gz`, and the file
  gains a top-level `modelFiles` mapping `user1` to the library. A
  misspelled model produced neither, and no warning from
  `cov-make-library` or `cov-analyze`.
- Every event through a replaced function carries *"[Note: The source code
  implementation of the function has been overridden by a user model.]"*.
- Files, lines of code and functions in `summary.txt` were identical before
  and after. Paths analyzed changed in every arena run (80 -> 86, 88 and
  92 on 2026.9.0) and in no other.
- Findings that did not move kept their merge keys.
- `models.py inventory` on the collision baseline lists `error()` under
  *project code analyzed with a built-in model*, and `log_msg()` under *no
  model at all* (`missingModels: ["all"]`, `hasImplementation: false`).

**Measured while building the fixtures, on 2026.9.0, not repeated by
`run.sh`:**

- The first version of the killpath fixture named its function `fatal()`.
  The false positive was not reported, and `fatal` showed `models:
  ["built-in", "implementation"]`. The same code with the function renamed
  `report_and_stop()` reported it. That is how idiom 2 was found: `fatal`
  is in the shipped `library/generic/common/killpath.c`, and so are
  `error`, `die`, `stop`, `bug`, `panic` and others.
- Derived models, read with `cov-find-function --save --module generic`:
  `arena_destroy()` has `escape(<arg 0>)`, `escape(<arg 0>->sub_next)`,
  `escape(<arg 0>->blocks)` and `escape_to_global(<arg 0>->blocks)`, and no
  free; `doc_close()` has `escape(<arg 0>->arena)` and `noescape(<arg 0>)`;
  `fail_hard()` has only `escape(<arg 0>)`, no edge that ends the path.
- `--user-model-file` was accepted by `cov-analyze` and had the same effect
  as `--model-file` (killpath: 2 -> 1, `fail_hard` took `user1`).
- The original command line is line 1 of `output/summary.txt`, and the
  `cmdline: command line:` entry of `output/analysis-log.txt`.

## C#: `evals/run_csharp.sh`

Idioms 4 and 5 were first measured by another contributor, working on a C#
detectability question, and reproduced here on this skill's own fixture.
The project is captured once with `cov-build` around `dotnet build`
(.NET SDK 9.0.305, `-p:UseSharedCompilation=false`, C# configured into a
config file in the workdir), and every run analyzes a copy with
`--enable UNSAFE_DESERIALIZATION --distrust-filesystem --trust-network`.
Every case as expected on `cov-analysis-win64-2026.9.0` and
`cov-analysis-win64-2026.6.0`, merge keys identical. After the change to
`compare`, `run.sh` was run again on 2026.9.0: every C case as expected.

| case | change | before -> after | what must change | what must not |
|---|---|---|---|---|
| baseline | | UNSAFE_DESERIALIZATION 1, FORWARD_NULL 1 | | `Handlers.cs:19`, the null dereference in the `MissingManifestResourceException` handler, not reported |
| `source` | `MemoryStream(byte[])` -> `Security.NetworkSource(this)` | UNSAFE_DESERIALIZATION 1 -> 0 | `Passthrough.cs:15` gone (file bytes into the stream) | `Handlers.cs:33` kept |
| `source-alias` | the same plus `Reference.Alias(this, buffer)` | UNSAFE_DESERIALIZATION 1 -> 0 | `Passthrough.cs:15` gone | |
| `entry-point` | `simple_entry_point` on `Passthrough::HandleRequest`, taint `http` | UNSAFE_DESERIALIZATION 1 -> 2 | `Passthrough.cs:23` new | `Passthrough.cs:15` kept |
| `ctor-tainted` | `method_returns_tainted_data` on the constructor | no change | console `[ERROR] Directive errors were discovered`; `directives.log`: the method "doesn't have a return" | `Passthrough.cs:23` silent |
| `throw` | `GetString` throws under `Util.Nondet()`, else returns null | NULL_RETURNS 0 -> 1 | `Handlers.cs:14` new: the model applied | `Handlers.cs:19` still silent; `Handlers.cs:33` kept |
| `throw-static` | `Path.GetFileName` throws `InvalidOperationException` under `Util.Nondet()`, else returns null | NULL_RETURNS 0 -> 1 | `Handlers.cs:42` new: the model applied | `Handlers.cs:47` still silent; `Handlers.cs:33` kept |

Also measured, on 2026.9.0:

- `cov-find-function --cs --include-builtins --exact --module security`
  on `System.IO.MemoryStream::.ctor(System.Byte[])System.Void`:
  `dataflow_param_merge(<arg 0>): from_iface -> <arg 1>`, then
  `noescape(<arg 1>)`. The same with `--model-file <lib>` added still
  saved the built-in model. With `--model-file` and without
  `--include-builtins`: `taint_source(<arg 0>): taint_type -> network`,
  then `noescape(<arg 1>)`, and no `dataflow_param_merge`. The contributor
  who found the idioms traced this: with both options, two models are
  saved under one file name, and the second overwrites the first.
- Read the same way (`--module exceptions --model-file`, no
  `--include-builtins`), both throwing models have
  `uncaught_except(<function>)` with the thrown type
  (`System.Resources.MissingManifestResourceException`,
  `System.InvalidOperationException`).
- In `callgraph-metrics.json.gz`, the constructor's and `Path.GetFileName`'s
  user models show as `user1`, with `modelFiles` listing the library. The
  `GetString` model applied (the new NULL_RETURNS), but `GetString` is not
  in the callgraph, `modelFiles` is absent, and the NULL_RETURNS events
  carry no user-model note. The contributor saw user models of other
  virtual methods listed (in `callgraph-metrics.txt`, with
  `--enable-callgraph-metrics`); why `GetString`'s is not is unknown.
  `compare` therefore checks no C# source by name.
- A directive named in the dotted form (`Passthrough.HandleRequest(...)`)
  matched nothing: console `[WARNING] Potential directive issues`, and
  `directives.log` says the directive "does not match any methods in the
  emit".
- `cov-make-library` compiled each `.cs` model with `cov-emit-cs` against
  `library/primitives.dll`, and reported `1 models successfully merged`.

## From the documentation, not measured here

The customizing guide of 2026.9.0 (`doc/en/cov_customizing.html`, *Models
and primitives*):

- the model search order: user model files in `--model-file` order,
  `config/user_models.xmldb`, built-in models, derived models, then
  previously derived model files;
- `--user-model-file` deprecated since 7.7.0 in favour of `--model-file`;
- models recognize comparisons but not arithmetic or bitwise operators;
- a later version cannot use a model library built by an earlier one;
  keep the source and rebuild;
- C++ models must match the mangled name;
- an aborting macro needs `#nodef` to become a call, and function
  annotations can mark a killpath;
- function-pointer models (`__coverity_fnptr_<...>`, `--fnptr-models`).

## Reasoned, not measured

- That modeling an arena's allocations as allocations would report leaks
  for objects the parent arena reclaims, unless the model escapes them
  (idiom 3b, *Costs*).
- That a model stronger than the code (never NULL, never returns) hides
  real defects. It follows from the mechanism; no fixture shows it yet.
- That a finding whose trace a model changes may get a new merge key, and
  show as one gone and one new. In the fixtures, findings that did not move
  kept their keys.

## Not run

- C++, Java or Go models; in C, the taint, concurrency and
  function-pointer primitives; in C#, anything beyond idioms 4 and 5.
- A large codebase: what one re-analysis iteration costs, and how the
  inventory reads on thousands of functions (`callgraph-metrics` records a
  function more than once on large idirs; `inventory` merges them by name).
- The Linux installations. `run.sh` is portable bash, but has only run on
  Windows.
- Starting from a real `coverity-triage` `triage.json`. The evals describe
  that hand-off; `run.sh` starts from the fixtures.
