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
  (the function that hit the path limit) and coverity-fuzz-triage (the
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
of a function that hit the path limit) and `coverity-fuzz-triage` (which
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
- The body is what the analyzer saw: **macros expanded**, `sizeof` folded
  (`4UL /* sizeof (gid_t) */`), `errno` as `*__errno_location()`, types
  canonical. Branches hidden in macros are visible here and nowhere else.
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
functions re-emitted 40 for 40; all 18 nginx PATHOUT functions but one
slice and analyze.

**Read the two result lines.** `cov-emit: emitted` with no recoverable
errors, then `analysis: wur: ... n: <name> in TU 1`. If instead it prints
`cov-emit: emitted ... NOT EMITTED: function "<name>"` and `analysis: COULD
NOT VERIFY` (exit 2), cov-emit accepted the file but dropped the function
on a parse diagnostic, and there is no result yet: read the quoted
diagnostics, fix the slice (or the slicer -- the forms seen so far,
`for (; true; )`, a function-local `enum <anonymous>`, `struct fn::tag`,
transparent-union arguments, `NULL`/`va_*`, are rewritten; a cast whose
parentheses the pretty-printer dropped, `((uint32_t *)m[1] & 65535)`, is
not and needs a hand edit), and re-run. Never report that run's
`paths_exceeded count: 0` as a result.

**What is different from the original, and say so**: callees are
prototypes with no models, globals are `extern`, static callees lose
`static`, anonymous types get tags, bit-fields become full fields. For a
function whose behaviour depends on what its callees are modelled to do
(a PATHOUT count, a NULL_RETURNS finding) the standalone numbers can
differ; five of nginx's eighteen PATHOUT functions finish under the limit
as slices for exactly that reason. `coverity-fuzz-triage` puts the callee
models back as stubs when execution is the question.

**C++.** Free functions work, including calls to static members of classes
with nested enums (the declarations are placed back inside the class). A
**non-static method** as the target, or a namespace, is where the slicer
stops and the preprocessed-TU route takes over (`cov-manage-emit --tu N
preprocess`, then `cov-emit` the `.i` with the same flags). Both are in
`references/standalone-reproducer.md`.

**This is where most requests end.** Report the slice path, the line
counts, the `cov-emit: emitted` line, and the `wur:` line if `--analyze`
was run. Step 3 is only for the uncommon case where the file has to be
shown outside the project. Do not run it unasked.

## Step 3 (uncommon): Obfuscate it before it leaves

Use this step only when the user **asks** for the function to be seen by
someone who must not see the source: another model, a vendor, a colleague
outside the project. The request may be phrased as "obfuscate",
"anonymize", "rename the variables", "strip the identifying parts", or
"make a version I can send". The case it was built for: taking a real
customer function out of a zero-retention environment so a larger workflow
could be tested on it.

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
| "Is this finding real? Run it." | `coverity-fuzz-triage` (the slice is its target; the callee models come back as stubs) |
| "Was the function even captured?" / the file is not in the emit | `coverity` (capture fidelity, rule 34) |
| The idir is from a version you no longer have | `coverity-recreate-from-emit` |

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
│   └── slice_function.py                # one function as a file that compiles; --emit --analyze --obfuscate
└── evals/
    ├── fixture.sh                       # emits the fixtures, extracts by mangled name, slices and verifies
    ├── evals.json
    └── fixtures/
        ├── local_enum_forever.c         # for(;;) and function-local unnamed types (the nginx forms)
        ├── overloads.cpp                # C++: mangled names, picking one overload
        └── nested_members.cpp           # C++ free function: static member, nested enum, __func__
```
