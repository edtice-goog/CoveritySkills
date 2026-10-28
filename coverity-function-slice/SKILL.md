---
name: coverity-function-slice
description: >
  Get one function out of a Coverity intermediate directory exactly as the
  analyzer saw it, and turn it into a file that compiles and analyzes on
  its own. Use this skill for "extract this function from the idir", "show
  me what the analyzer saw for foo()", "re-analyze just this function",
  "make a standalone reproducer", "iterate on this function without
  rebuilding", "give me a file I can cov-emit by itself", and for the
  uncommon follow-on "obfuscate / anonymize it so I can send it to the
  vendor or to another model". The function comes from the AST with
  cov-manage-emit find --print-definitions in under a second -- never from
  a preprocessed file; every typedef, struct, global and callee prototype
  it needs is printed back out of the same emit; the file is re-emitted
  with the translation unit's recorded flags and re-analyzed in seconds;
  and --obfuscate renames identifiers by kind, masks strings, keeps library
  names and constants, and proves by analyzing both copies that the twin
  analyzes identically. Requires the Coverity Analysis installation of the
  version that wrote the intermediate directory. Used by coverity-pathout
  (the function that hit the path limit) and coverity-verify (the
  fuzz target), and on its own whenever one function is the question.
---

# Coverity function slice

The intermediate directory holds the abstract syntax tree the analyzer used.
This skill pulls one function out of it, as the analyzer saw it, and makes
that function a file that compiles and analyzes alone. Two commands, three
outcomes: the body (Step 1), the standalone file (Step 2), and, only when
asked, the obfuscated twin that can leave the building (Step 3).

Read `coverity/RULES.md` first (rules 3 and 35 bear directly).

**This skill is one of a bundle of three** in the CoveritySkills
repository, beside `coverity-pathout` (which calls this one for the body
of a function that hit the path limit) and `coverity-verify` (which
uses the slice as its fuzz target). It stands alone, but if you have only
this file, clone the repository and work from the clone so the rules and
the siblings are where the text says they are:

```bash
git clone https://github.com/edtice-goog/CoveritySkills
```

## Step 0: Pin the installation

Line 1 of `<idir>/emit/version` names the version that wrote the idir.
**Use that version's `bin/`** for every command here; another version
refuses the emit outright (`Expected version number is 355, but this
directory has version 350`). Rule 3. Nothing in this skill writes into the
idir except under `<idir>/output/pathout/` (or wherever `--out` points), so
no copy is needed.

## Step 1: The body, from the AST

```bash
$BIN/cov-manage-emit --dir <idir> --ticker-mode none --tu <N> \
    find '^<name>$' --kind f --print-definitions > <name>.txt
```

- `<name>` is the identifier for C and the **mangled** name for C++
  (`_ZN4demo6Widget1fEi`). The regex is matched against the mangled name,
  so anchor it and use the mangled form to pick an overload. From a
  demangled signature, list candidates first: `find '<identifier>' --kind
  f` prints `demo::Widget::f(int) /*_ZN4demo6Widget1fEi*/` for each match.
- `--tu` matters: `find` prints every definition that matches, and proftpd
  has seven functions called `main`. A Coverity analysis log names the TU
  on its `wur:` lines (`in TU 77`); `--print-callees` and the
  `FUNCTION.metrics.xml.gz` join (`references/function-extraction.md`) give
  it otherwise.
- 0.4 s; 509 lines for a 963-line function. A miss prints nothing and exits
  0 -- check for the `Matching function` header.
- The body is what the analyzer saw: **macros expanded**, `errno` as
  `*__errno_location()`, types canonical. The printer folds `sizeof` to the
  capture's constant (`4UL /* sizeof (gid_t) */`); the slicer restores the
  expression from that comment, so a sizeof-class finding survives
  re-analysis and a build with another pointer size computes its own value
  (`--fold-sizeof` keeps the constant). Branches hidden in macros are
  visible here and nowhere else.
  Line numbers are not preserved inside the body; the header's `declared
  at:` is the anchor, and `--tu N print-source` gives the captured source
  with a three-line header offset for a side-by-side.

**Never** extract the file, preprocess it, and cut the function out of the
`.i` text. The emit already holds the tree; a pretty-print of it is exact,
compact, and instant. `references/function-extraction.md` covers C++,
duplicates, the metrics join, and the other `find` outputs (`--print-debug`
for one construct's exact source location; `--print-callees`).

## Step 2: Make it compile on its own

The body alone will not re-emit: it names typedefs, structs, globals and
callees that came from headers. The same emit holds all of those -- the
function's `--print-debug` tree carries every callee's prototype, every
global's type and every typedef's target, and `find --kind c --print-debug`
gives each struct's fields -- and the slicer closes over them:

```bash
python3 tools/slice_function.py --dir <idir> --bin $BIN --tu <N> --name <name> --emit --analyze
```

That writes `<name>.slice.c` (declarations printed from the tree in
dependency order, then the body) under `<idir>/output/pathout/slice-<name>/`
or `--out`, re-emits it with the flags recorded for the original TU minus
include paths, analyzes the one-file idir with `--print-paths`, and prints
the function's `wur:` line. `setup_env`: 906 lines, clean emit, analyzed
in 15 seconds, editable, repeatable. A random sample of 40 proftpd
functions re-emitted 40 for 40; all 18 nginx PATHOUT functions slice and
analyze.

**Read the two result lines.** `cov-emit: emitted` with no recoverable
errors, then `analysis: wur: ... n: <name> in TU 1`. If instead it prints
`cov-emit: emitted ... NOT EMITTED: function "<name>"` and `analysis: COULD
NOT VERIFY` (exit 2), cov-emit accepted the file but dropped the function
on a parse diagnostic, and there is no result yet: read the quoted
diagnostics, fix the slice (or the slicer -- the forms seen so far,
`for (; true; )`, a function-local `enum <anonymous>`, `struct fn::tag`,
transparent-union arguments, `NULL`/`va_*`, a comma initializer, a
`[[attribute]]` in C, the lowered `__atomic_*` form, are rewritten), and
re-run. Never report that run's `paths_exceeded count: 0` as a result.

**One printer form compiles and means something else.** `--print-definitions`
prints every subscript base bare: `(*table())[c]` comes out as
`*table()[c]`, `(*pp)[1]` as `*pp[1]`, `((T *)p)[i]` as `(T *)p[i]`,
`(p + 1)[c]` as `p + 1[c]`. The first two type-check, so `cov-emit:
emitted` passes and the slice indexes a different object; the others fail
to parse. The slicer repairs all of them from the `--print-debug` tree,
which keeps the structure, and prints a `repaired:` line naming each base
and its source line. Read the `note:` lines too: a base whose printed text
also occurs with the other meaning, or whose form the slicer cannot spell
(a conditional, a comma expression), is left as printed and named by
source line for a hand check.

**What is different from the original, and say so**: callees are
prototypes with no models, globals are `extern`, static callees lose
`static`, anonymous types get tags, bit-fields become full fields. For a
function whose behaviour depends on what its callees are modelled to do
(a PATHOUT count, a NULL_RETURNS finding) the standalone numbers can
differ; five of nginx's eighteen PATHOUT functions finish under the limit
as slices for exactly that reason. `coverity-verify` puts the callee
models back as stubs when execution is the question.

**C++.** Free functions work, including calls to static members of classes
with nested enums (the declarations are placed back inside the class). A
**non-static method** as the target, or a namespace, is where the slicer
stops and the preprocessed-TU route takes over (`cov-manage-emit --tu N
preprocess`, then `cov-emit` the `.i` with the same flags). Both are in
`references/standalone-reproducer.md`.

### A set of functions in one file

When the question spans more than one function -- a finding whose event
path runs from a caller into a callee, a pair that recurse into each
other -- a prototype standing in for the other function is the wrong
container: whatever analyzes or executes the slice then sees a model of
that function, not its code. Repeat `--name` and every named function is
sliced **as real code into the same file**:

```bash
python3 tools/slice_function.py --dir <idir> --bin $BIN --tu <N> \
    --name <caller> --name <callee> [--name <other>@<M>] --emit --analyze
```

- **Which functions.** Every function that carries a primary event in the
  finding's chain. Callees outside that set stay prototypes, as before.
- **Another translation unit.** `--tu` is the TU for every `--name`; a
  member elsewhere is written `name@tu` (`--name ngx_foo@79`). The slice
  is re-emitted with the first member's recorded flags. If the TUs declare
  the same typedef or struct differently the slicer prints `conflict:` for
  each, `analysis: COULD NOT VERIFY`, and exits 2 rather than pick one;
  split the set by TU.
- **What the file looks like.** Line 1 is `/* slice-set: a, b, c */`, the
  members in `--name` order, so a consumer can tell the slice's own
  definitions from its prototypes without parsing C; then the shared
  declarations; then a prototype for **every** member (definition order and
  mutual recursion never matter); then the definitions. A member that was
  `static` in the original keeps its definition and loses only the keyword,
  the treatment callee prototypes have always had, so a sliced caller can
  reach a sliced file-local callee. The output says which: `members : 2
  defined as code; static in the original, now reachable across the set:
  set_callee`. The file is `<first>.set.slice.c` under `slice-<first>-set/`.
- **What the output says.** `set     :` lists the members (one name for a
  single `--name`). `--analyze` reports one `wur:` line per member,
  prefixed with its name, and `COULD NOT VERIFY` names the member that was
  dropped; exit 2 if any was. `--obfuscate` renames the members `fn_0`,
  `fn_1`, ... in `--name` order, puts the new names on line 1 of the twin
  (`obf-set :` on the console), lists them under `set` in the map, and
  verifies per member. Members that call each other are one strongly
  connected component, and which one the analyzer walks first decides how
  the paths split between them; when per-member counts differ but the
  set's counts match as a whole, `verify` says `preserved up to analysis
  order within the set` and names both numbers.

One `--name` behaves exactly as before: same filenames, same lines, same
exit codes, same map, plus the line-1 comment.

### Two routes to a verification, both from the emit

The slice is one container for executing a function: the pretty-printed
body with declarations printed back from the tree, and model stubs for
every callee outside the slice set (`coverity-verify` calls this
**extraction-verification**). The other container is the translation unit
itself: its **real source compiled as-is with the recorded flags**, a
driver linked in, the target run unchanged, every function the TU defines
being real code and only the externals stubbed (**harness-verification**).
The router in `coverity-verify` chooses between them; this skill supplies
the facts it decides on:

```bash
python3 tools/tu_manifest.py --dir <idir> --bin $BIN --tu <N> --name <fn> --out <dir> [--models <saved models>]
```

It writes `manifest.json`, `tu.c` (the primary source, the stored bytes),
and `files/`, every file the TU read, system and compat headers included,
in the layout the capture saw (`files/<path without drive letter and
leading slash>`). The manifest carries the recorded compile line and its
parts (`flags`, `include_paths`, `sys_includes`, `pre_preinclude`,
`defines_from_build`), the capture's working directory and platform, every
function the TU defines with `static` and location, the externals (called,
not defined; `library` or `project` by declaring path; with `--models`,
whether a saved derived model exists), the target, and `notes`: the facts
that predict the route will fail (a `static` target a driver cannot name,
a target defined in a header, a C++ member, a capture platform that is
not this one, project externals without a model). It never slices or
rewrites, and it exits 0 with notes rather than deciding; `references/
standalone-reproducer.md`, *The whole TU as the container*, records what
the emit can and cannot supply for this (the headers it holds are the
ones its own front end opened; a real compiler at `-O` may want one more).

**This is where most requests end.** Report the slice path, the line
counts, the `cov-emit: emitted` line, and the `wur:` line if `--analyze`
was run. Step 3 is only for the uncommon case where the file has to be
shown outside the project. Do not run it unasked.

## Step 3 (uncommon): Obfuscate it before it leaves

Use this step only when the user **asks** for the function to be seen by
someone who must not see the source: another model, a vendor, a colleague
outside the project. The request may be phrased as "obfuscate",
"anonymize", "rename the variables", "strip the identifying parts", or
"make a version I can send". The case it exists for: a function that
must be discussed outside the environment that holds the source, for
example in a support ticket or with a model that may not see the code.

The structure is what the outside reader needs and the names are what
identify the codebase, so the tool renames and masks, keeps everything the
analyzer reasons about, and then **proves** the analyzer treats the twin
like the original. Do not obfuscate by hand or with `sed`; a rename that
misses one position produces a file that looks fine and analyzes
differently.

```bash
python3 tools/slice_function.py --dir <idir> --bin $BIN --tu <N> --name <name> --obfuscate --emit --analyze
```

**It writes three files:**

| file | what | where it may go |
|---|---|---|
| `<name>.slice.c` | the plain slice, real names | stays |
| `fn_0.obf.c` | the twin: project identifiers renamed by kind, strings masked, comments gone. Named after the *new* name on purpose: a C++ mangled `--name` would put the function and its parameter types in the filename | this is the only file that leaves |
| `<name>.obf.map.json` | every new name with what it was; every kept name with why | stays; it is how the outside reader's advice about `fn_0` and `L_1` is translated back |

**Read four lines of the output before handing anything over:**

1. `obfusc.  cov-emit: emitted` with no recoverable errors. Errors mean the
   twin is not even the same program.
2. `verify : obfuscation preserved the analysis -- same path count (N),
   same PATHOUT flag, same pathed-out checkers`. This is the acceptance
   test. `DIFFERS` means the twin does not represent the function: stop,
   and report the two files as a tool bug. `COULD NOT VERIFY` means one of
   the two was not analyzed at all: also a stop. Do not hand over a twin
   that differs and do not explain it away.
3. `review : ... identifiers neither renamed nor classified as library`.
   Usually absent. If present, look at each name in `fn_0.obf.c`: it is
   something the tool could not attribute, and a human decides whether it
   identifies the project. Renaming it by hand *and re-running the
   verification* is fine; skipping the verification is not.
4. `kept : N library names` -- open the map's `kept` section and skim it.
   Every entry should read as libc, POSIX, Win32 or the compiler. A project
   name there means it was declared under a path the tool took for a
   system path; say so and treat it as a `review` item.

**What the twin still carries, and say so to the user**: control flow,
struct shapes, numeric constants, string *lengths* and `%` directives, and
the library calls. Someone who knows the codebase can recognize a function
by its shape. Names, string contents, file paths and comments are gone.
Numeric constants are kept on purpose: known constants are the state a
path-sensitive analyzer multiplies on, and changing them would change what
is being looked at.

**Hand over** `fn_0.obf.c` alone. Not the map, not the plain slice, not
the analysis log (it contains the real name). The tool's own `obfusc.
analysis:` lines are safe to quote because they name only the new name and
the checker.

Mechanism, measurements and limits: `references/standalone-reproducer.md`,
*Obfuscating the slice so it can leave the building*.

## Reporting

Verdict first (rule 21): the function, the TU, where the slice is, whether
it emitted and analyzed, and the caveat about unmodeled callees. Mark
measured vs reasoned (rule 23). If `--obfuscate` was run, quote the
`verify` line verbatim.

## Anti-patterns

- Parsing `cov-preprocess` / `--preprocess-native` output to find a
  function. Slow, brittle, and still not what the analyzer saw.
- Re-emitting a pretty-printed body on its own, or hand-writing the
  declarations it needs. The tree has them all; `slice_function.py` prints
  them. (For C++ methods, the preprocessed TU is the container, not a
  hand-built one.)
- Reading a slice's `paths_exceeded count: 0` or an empty defect list as a
  result without a `wur:` line for the function. A function cov-emit
  dropped (`warning #1563: function "<name>" not emitted`) has no line; the
  tool says `COULD NOT VERIFY` for exactly this.
- Obfuscating with `sed`, a word list, or by hand, and sending the result
  without the `verify` line. Renaming `malloc` changes the analysis;
  missing one `->` access breaks the file; neither is visible by reading.
- Sending the plain slice, the map, or the analysis log along with the
  obfuscated twin. Only `fn_0.obf.c` leaves.
- Using a different Coverity version than the one that wrote the idir.

## Where other skills take over

| Question | Skill |
|---|---|
| "Why did this function exceed the path limit, and what did it cost?" | `coverity-pathout` (it calls this skill for the body) |
| "Is this finding real? Run it." | `coverity-verify` (the slice is its target; the callee models come back as stubs) |
| "Was the function even captured?" / the file is not in the emit | `coverity` (capture fidelity, rule 34) |
| The idir is from a version you do not have installed | stop and ask: name the version `emit/version` requires and let the user install it or re-capture. `coverity-recreate-from-emit` is expensive and is a last resort the user must ask for |

## Layout

```
coverity-function-slice/
├── SKILL.md
├── README.md
├── CALIBRATION.md                       # what was measured, on what, and what was not
├── references/
│   ├── function-extraction.md           # cov-manage-emit find: C, C++, duplicates, output shape
│   └── standalone-reproducer.md         # the slice: declarations from the tree, re-emit, rewrites, obfuscation, C++ boundary
├── tools/
│   ├── slice_function.py                # one function (or a set) as a file that compiles; --emit --analyze --obfuscate
│   └── tu_manifest.py                   # the whole TU for harness-verification: manifest.json, tu.c, files/
└── evals/
    ├── fixture.sh                       # emits the fixtures, extracts by mangled name, slices and verifies
    ├── evals.json
    └── fixtures/
        ├── local_enum_forever.c         # for(;;) and function-local unnamed types (the nginx forms)
        ├── pretty_forms.c               # bare subscript bases, folded sizeof, and the zstd/redis forms
        ├── slice_set.c                  # a set: caller + static callee, mutual recursion, a non-member callee
        ├── slice_set_tu2.c              # a second TU that defines the same struct differently (the conflict case)
        ├── overloads.cpp                # C++: mangled names, picking one overload
        └── nested_members.cpp           # C++ free function: static member, nested enum, __func__
```
