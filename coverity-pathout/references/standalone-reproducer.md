# A function that compiles on its own

Printing the function is not the goal. The goal is to **re-run the analysis
on just that function, repeatedly, while you change it** -- to see which
edit brings the path count under the limit, or whether raising `--paths`
is the cheaper answer. That needs a file `cov-emit` will accept, and a
pretty-printed body on its own is not one: it names typedefs, structs,
globals and callees that live in headers the body no longer includes.

The declarations are the hard part, and they are also in the emit.

## What the emit knows about the function's surroundings

`cov-manage-emit find <fn> --print-debug` dumps the function's tree, and
that tree is self-describing: every node that names something carries the
thing's type.

| the body needs | where the tree has it |
|---|---|
| a callee's prototype | every call carries a `function_t` with `name`, `dflags`, and a full `function_type_t` (return, parameters, `has_C_ellipsis`) -- **including callees that are only declared**, like `strlen`, which `find` itself cannot look up |
| a global's declaration | `global_variable_t` with `name`, `type`, `dflags` |
| a typedef | `typedef_type_t` with `name` and `target`, wherever the typedef is used |
| a struct or union tag | `class_type_t` with `name` and `classKey` |
| a struct's fields | `find <tag> --kind c --print-debug`: `internal_defined_class_type_t` with `fields`, each with `name`, `type`, `index`, `offset` |
| an enum's values | `find <name> --kind e --print-debug`: `enumerators` with `name`, `value` |

Anonymous types have synthetic names (`_Z$Uu9session_t_` for the unnamed
struct behind `typedef ... session_t`, `_ZN12json_node_st$Ua5bool__E` for an
unnamed union member, `_Z$Ua8_ISupper_` for an unnamed enum); types declared
inside the function are named `_ZZ9ext_matchE11patternlist`, and an *unnamed*
type declared inside the function combines the two:
`_ZZ26ngx_http_parse_complex_uriE$Uu5state_` is the `enum {...} state;` of
that function (`$Uu` + the variable; `$Ua` + the first enumerator when there
is no variable). All of them are findable by exact name (escape the `$`).

So the slice is a closure computation over trees, not a text problem: walk
the function's tree, collect what it references, fetch the fields of every
struct used by value or through a field access, walk those, repeat. Then
print C declarations back out of the tree in dependency order and append
the body.

`tools/slice_function.py` does exactly that.

## Using it

```bash
python3 tools/slice_function.py --dir <idir> --bin <install>/bin --tu 77 --name setup_env --emit --analyze
```

```
slice   : <idir>/output/pathout/slice-setup_env/setup_env.slice.c  (906 lines)
contents: 42 typedefs, 18 struct definitions (+13 forward-declared only), 0 enums, 9 globals, 74 prototypes
cov-emit: emitted
analysis: wur: gen1 1 27029 6766 7395 6766 5001 PATHOUT=1 n: setup_env in TU 1
analysis: Pathed out: 5001 paths traversed by REVERSE_INULL in "setup_env(pool *, cmd_rec *, char const *, char *)"
analysis: summary: paths_exceeded count: 1
```

- `--name` and `--tu` are what the analysis log printed (`n: setup_env in
  TU 77`); for C++ the mangled name.
- `--emit` re-runs `cov-emit` on the slice with the **flags recorded for
  the original TU** (`print-compilation-info`), minus `-I`, `-D` and
  `--sys_include`: there is nothing left to include. The compiler-compat
  headers (`--pre_preinclude`) live inside the idir and are kept; when the
  idir was written under WSL the `/mnt/c/...` paths are mapped back.
  Everything that made the original parse what it was -- `--gnu_version`,
  `--type_sizes`, `--size_t_type`, the language standard -- is preserved,
  so the slice is parsed the way the original was.
- `--analyze` runs `cov-analyze --print-paths` on the resulting one-file
  idir and prints the function's `wur:` line and its `Pathed out` lines.
  `--paths N` passes the limit through. **No `wur:` line for the function
  is reported as a failure**, not as "no PATHOUT": the tool prints
  `analysis: COULD NOT VERIFY -- no wur: line for <fn> in the one-file idir`
  with the reason, and exits 2. The usual reason is that `cov-emit`
  accepted the file but dropped the function (`warning #1563: function
  "<fn>" not emitted`, after a parse diagnostic in its body); the
  `cov-emit:` line then says `NOT EMITTED` and quotes the first
  diagnostics. Before this check, a dropped function produced only
  `paths_exceeded count: 0`, which reads as a clean result -- eight of
  nginx's eighteen PATHOUT functions were "verified" that way.
- Output goes under `<idir>/output/pathout/slice-<name>/` unless `--out`
  says otherwise: the slice, `cov-emit.flags`, `cov-emit.log`,
  `cov-analyze.log`, and the idir.

The loop is then: edit the slice, re-run with `--emit --analyze`
(about 15 seconds for `setup_env`, most of it `cov-analyze` start-up), read
the two lines.

## What the slice looks like

```c
#define NULL ((void *)0)
#define va_arg(ap, type) __builtin_va_arg(ap, type)     /* and va_start/va_end/va_copy */

/* forward declarations */
struct cmd_struc;
struct config_struc;
...
/* types */                                   /* typedefs and complete structs, dependency-ordered */
typedef long __time_t;
struct timeval { __time_t tv_sec; __suseconds_t tv_usec; };
typedef struct config_struc config_rec;
struct config_struc { ... config_rec *parent; ... };
struct __cov_anon_s5 { struct pool_rec *p; int xfer_type; ... };   /* the unnamed struct of session.xfer */
...
/* globals (all extern, so their values stay unknown to the analysis) */
extern session_t session;
extern server_rec *main_server;
...
/* callees (prototypes only: the analysis sees them as unmodeled) */
char *getenv(const char *);
int pr_auth_getgroups(pool *, const char *, array_header **, array_header **);
...
/* the function */
static int setup_env(pool *p, cmd_rec *cmd, char const *user, char *pass) {
```

Five things the body needed rewriting for, because the pretty-printer
emits them in a form that is not C:

- `NULL` and the `va_*` family stay in macro form (defined at the top).
- `for (;;)` is printed as `for (; true; )` (and `for (i = 0; ; i++)` as
  `for (i = 0; true; i++)`). `true` is a keyword in C++ but a `<stdbool.h>`
  macro in C, and the slice includes nothing, so `cov-emit --c17` said
  `identifier "true" is undefined` and dropped the function. A C slice
  now carries `#define true 1` / `#define false 0` next to `NULL`
  (seen in six nginx functions: `ngx_init_cycle`,
  `ngx_http_fastcgi_process_header`, `ngx_http_header_filter`,
  `ngx_http_ssi_parse`, `ngx_http_upstream_process_header`,
  `ngx_http_upstream_process_upgraded`).
- A struct declared inside the function is printed as `struct
  ext_match::patternlist` with its definition dropped and a bare `struct
  patternlist;` left behind: the definition is hoisted to file scope, the
  uses qualify-stripped, the shadowing re-declaration removed.
- An *unnamed* enum, struct or union declared inside the function is
  printed as `enum <anonymous>;` followed by `enum
  ngx_http_parse_complex_uri::[unnamed type of 'state'] state;`. Its
  definition is in the tree under `_ZZ..E$Uu5state_` (enumerators
  included) and is rendered at file scope under a synthetic tag like any
  other anonymous type; the body's `fn::[unnamed type of 'var']` is
  respelled to that tag and the `<anonymous>;` declaration dropped (seen
  in nginx's `ngx_http_parse_complex_uri` and
  `ngx_http_parse_request_line`; regression-tested by
  `evals/fixtures/local_enum_forever.c`, which also covers an unnamed
  struct and an enum with no variable).
- A transparent-union argument comes out as `__SOCKADDR_ARG({.__sockaddr__
  = &peer})` (rewritten to the compound literal `(__SOCKADDR_ARG){...}`).

## What is different from the original, and why it does not matter here

- **Callees have no bodies.** In the original analysis every callee had a
  model derived from its own body; in the slice they are unmodeled
  prototypes. That changes what some checkers know about return values and
  side effects, so a path count in the slice is not guaranteed to equal the
  original's. Measured: `setup_env` pathed out on `REVERSE_INULL` at 5001 in
  both; `tpl_map_va` on `DEADCODE_pass2` at 10001 in both; `listfile` and
  `facts_mlinfo_fmt` pathed out in both. The structural cause survives the
  loss of callee models, which is what you are iterating on.
- **Globals are `extern`, even file-static ones.** A tentative definition
  would give the analysis a known initial value of zero; `extern` keeps
  it unknown, as it is when the function is entered in the real program.
- **Static callees lose `static`.** A prototype is a prototype.
- **Anonymous types get tags** (`__cov_anon_s5`). Named fields of anonymous
  type reference the tag; true anonymous members are defined in place,
  untagged. An unnamed type declared inside the function moves to file
  scope under such a tag, so its enumerators become file-scope names --
  which is where the body's uses of them already resolved.
- **Struct layout is reconstructed from field types**, not copied. Bit-field
  widths are not carried by the tree (no width key exists in the field
  nodes seen), so a bit-field becomes a full field; `sizeof` of such a
  struct differs. Nothing in the proftpd sample had one.

## Measured

All against the proftpd idir (2025.9.0), `--emit` and, for the PATHOUT
four, `--analyze`:

| function | slice | emit | analysis |
|---|---|---|---|
| `setup_env` | 906 lines; 42 typedefs, 18 structs, 9 globals, 74 prototypes | clean | `REVERSE_INULL` pathed out at 5001, as in the original |
| `listfile` | | clean | pathed out (`generic_DERIVERS`, `uninit_DERIVERS`, `DEADCODE_pass1`) |
| `tpl_map_va` (variadic, `va_arg`) | 470 lines | clean | `DEADCODE_pass2` pathed out at 10001, as in the original |
| `facts_mlinfo_fmt` | | clean | pathed out (`generic_DERIVERS`, `uninit_DERIVERS`) |
| `main` (556 lines, 67 callees, transparent union) | | clean | 656 paths, no PATHOUT |
| `ext_match` (function-local struct) | 127 lines | clean | 0 paths (loop-free trivial) |
| `pr_auth_cache_set` | 108 lines | clean | 1025 paths, as in the original |
| random sample, 15 functions across 15 TUs | | 15 clean after the fixes above (11 before) | not run |

A second random sample of 40 functions, taken after those fixes, emitted 40
of 40 cleanly (85 s in total). Details in `CALIBRATION.md`.

## Obfuscating the slice so it can leave the building

A slice is a single function with everything it needs, which makes it the
natural thing to hand to someone outside -- a more capable model, a
colleague at the vendor -- for a second opinion on the structure. Names
and strings are what identify it. `--obfuscate` writes a twin,
`fn_0.obf.c` (named after the new name, never the real one), with the
structure intact and the identity removed, and proves the analyzer cannot
tell the two apart.

```bash
python3 tools/slice_function.py --dir <idir> --bin $BIN --tu 77 --name setup_env --obfuscate --emit --analyze
```

```
obfusc. : .../fn_0.obf.c  (895 lines)
renamed : 125 field, 66 function, 9 global, 1 label, 39 local, 4 param, 15 struct, 1 target, 12 typedef
kept    : 87 library names (listed with reasons in the map); map, keep it local: .../setup_env.obf.map.json
slice     analysis: Pathed out: 5001 paths traversed by REVERSE_INULL
obfusc.   analysis: Pathed out: 5001 paths traversed by REVERSE_INULL
verify  : obfuscation preserved the analysis -- same path count (5001), same PATHOUT flag, same pathed-out checkers
```

What changes, and what deliberately does not:

| | treatment | why |
|---|---|---|
| project functions, globals, typedefs, struct tags, fields, enumerators, parameters, locals, labels, the function itself | renamed by kind: `fn_3`, `g_1`, `T_4`, `S_2`, `f_17`, `e_1`, `p_2`, `v_12`, `L_1`, `fn_0` | the kind prefix keeps the code readable as structure |
| functions, structs, fields, typedefs declared in a **system header** (`strlen`, `struct passwd`, `pw_uid`, `size_t`) | kept | Coverity models library functions by name; renaming `malloc` would change what RESOURCE_LEAK knows. "System" means declared under a recorded `--sys_include` path, `/usr/include`, Program Files, or the Coverity compat headers |
| string literals | same length, same escapes, same `%` directives, everything else `x`; a small index keeps distinct literals distinct (`"6xxxx%sxxxx%i"`) | log messages and config keys are the biggest identity leak; length and format directives are what checkers use |
| numeric constants | kept | known constants are exactly the state that multiplies; see `path-explosion.md` |
| control flow, types' shapes, struct layout | kept | that is what the reader is meant to reason about |
| comments, the provenance header | removed | file paths and the real name |

"Project" versus "library" is decided per symbol from where the emit says
it was declared, not from a name list: a wrapper called `xmalloc` declared
in the project is renamed; `malloc` is not. Two kinds of symbol have no
declaring file to judge by and get a list instead: a typedef (there is no
`find --kind t`, and judging by the *target* kept
`typedef std::unordered_map<...> PROJECT_NAME_MAP` on a real C++ TU), and a
global that is only ever declared `extern` (`find --kind g` does not index
it). Both are renamed unless the name is in `STD_TYPEDEFS` /
`STD_GLOBALS` (`size_t`, `FILE`, `stdin`, `optarg`, ...); a project name
that slips through costs exactly what the mode exists to prevent, while
renaming a library one costs the analysis nothing, since the slice declares
globals `extern` and unmodelled anyway. A function with no declaring file
at all is neither renamed nor kept: it lands on the `review` line.
Positional renaming means a field, a struct tag and a variable that share a
spelling get separate new names (`p` the parameter and `p` the field of
`struct pool_rec` do not collide); a typedef that shares its spelling with
its struct tag (`typedef struct tpl_node {...} tpl_node;`) is renamed
through the tag's new name, so the map records it once, as a struct.

C++ adds spellings: the emit keys a function by its mangled name while the
body calls it by its source name, an enumerator likewise, and a nested type
is keyed `_ZN...E` but written `Outer::Inner`. Every spelling is pointed at
the same new name, `class` counts as an elaborated specifier alongside
`struct`, a mangled template instantiation is never treated as a library
name (it spells out the project types it was instantiated on), and the
twin is written as `fn_0.obf.cpp` -- naming it after the mangled `--name`
would put the function and its parameter types in the filename.

**The verification is the point.** With `--analyze`, both files are emitted
and analyzed and the tool compares path count, `PATHOUT` flag and the set
of pathed-out checkers. It prints `verify : obfuscation preserved the
analysis` or `verify : DIFFERS`, and a `DIFFERS` twin should not leave.
During development that line caught a broken tokenizer that had renamed
struct fields in declarations but not in `->` accesses; the analyzer saw
50 recoverable errors and no function.

Measured: `setup_env`, `listfile`, `tpl_map_va`, `main`, `ext_match` and
the fixture all verified identical (5001/REVERSE_INULL, 5001/three
derivers, 10001/DEADCODE_pass2, 656, 0, 5001/four components).

**What still leaks.** Shape. Ninety-five `if`s, twenty-two `goto`s to one
label and a call pattern of lookup-then-null-check is recognisable to
someone who knows the codebase. The kept library calls narrow it further
(`setuid`, `setgid`, `strcasecmp` say "a login routine on POSIX"). The
`review :` line lists any identifier the tool could neither rename nor
attribute to a library, for a human to look at before the file goes
anywhere. The map file (`<name>.obf.map.json`: every new name with what it
was, every kept name with the reason) stays local; it is what turns the
outside reader's "split `fn_0` at `L_1`" back into advice about
`setup_env`.

## When the slice is not the right container

**C++ methods and namespaces.** A C++ *free function* slices: callees are
declared under their source spelling (the tree carries `id` beside the
mangled `name`), a static member function it calls is declared back inside
its class together with any nested enum that member's parameters use, a
flexible array member prints as `[]`, and the `__func__` static that
logging macros build prints with a name. That was established against a
large real-world C++ function (2026.3.0, C++17) --
76 recoverable errors before, clean after, and the slice reproduced the
TU's `FORWARD_NULL_pass2` PATHOUT -- and is regression-tested here by
`evals/fixtures/nested_members.cpp` (2026.6.0). What the slicer still does
not do: the target being a **non-static method** (its class would need its
method declarations, and possibly its namespace and templates,
reconstructed; the fixture's `demo::Widget::f(int)` emits with "function
not emitted" and leaks `demo` and `Widget` through the `review` line). For
those, use the whole preprocessed TU:

```bash
cov-manage-emit --dir <idir> --ticker-mode none --tu <N> preprocess
#  -> <idir>/output/preprocessed/<file>.<N>.i
cov-emit --dir <new-idir> <recorded flags minus -I/-D/--sys_include> <file>.<N>.i
cov-analyze --dir <new-idir> --print-paths
```

Verified on a Windows-built subversion idir (2026.3.0): `preprocess` took
7 s, the `.i` re-emitted with the recorded flags (32 of them, after
dropping include paths -- note that `print-compilation-info` prints argv
unquoted, so `C:/Program Files/...` arrives split; the tool's splitter
re-joins it), and `cov-analyze` analyzed the 12 functions in it. The
function is editable in place in the `.i`; the price is a much larger file
and the whole TU being analyzed each time. (`preprocess` needs the recorded
`cov-emit` to be runnable on this machine: an idir written under WSL
records a Linux binary.)

**A struct with bit-fields or packing pragmas whose layout matters** to
the checker in question (`OVERRUN` on a byte-exact buffer): compare the
slice's `sizeof` against the original before trusting a count.

## Sources

Everything on this page was established by running it; the tool and the
fixture script are the reproducible form. `--print-debug` field names are
undocumented and were read off the output; they held across 2025.9.0,
2026.3.0 and 2026.6.0.
