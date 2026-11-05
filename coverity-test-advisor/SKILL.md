---
name: coverity-test-advisor
description: >
  Find the behaviour a code change introduced that the tests do not
  exercise. From two analyzed Coverity intermediate directories (the base
  and the head of a change), the git commits they were built from, and
  coverage of the head's test run, it finds every function the change can
  affect: those whose code changed, and the callers of functions whose
  Coverity derived model changed. It settles the clear cases by fixed rules
  (the function never ran; a changed line or a call into a changed function
  never ran) and has the rest judged against the tests: did a test exercise
  the changed behaviour, or only run the lines? Each gap becomes a report
  entry and a Coverity issue in a local errors.xml, with the reason and a
  suggested test. Use it for "which parts of this change aren't tested",
  "test gaps in this commit", "does this change need more tests", "Test
  Advisor", "Coverity Test Advisor", "what test is missing", "is the new
  error path tested", "line coverage says 100% but is the change tested",
  and before pushing a change. C and Java, coverage from GCC 14 gcov JSON
  or JaCoCo XML, Coverity Analysis 2026.9.0 on Linux. The judging step
  reads tests function by function, so it is priced and asked before it
  runs; unattended, the skill stops after the fixed rules. It commits
  nothing to Coverity Connect.
---

# Coverity Test Advisor

**This skill is part of the CoveritySkills repository.** It needs
`coverity` and `coverity-build-fidelity` beside it: Step 2 uses their
capture-coverage check, and `coverity/RULES.md` applies throughout. If you
have only this file, clone the repository and work from the clone:

```bash
git clone https://github.com/edtice-goog/CoveritySkills
```

## What it answers

A change can leave its own lines covered and still go untested. A callee
that now returns NULL changes every caller, and line coverage shows the
call ran without showing whether any test took the path where it returned
NULL. Coverity already describes that change: its **derived model** of
each function, the interface behaviour it infers (dereferences its
argument, may return NULL, a taint sink, `<arg 2> < 2048`), and every
caller sees it. When a function's derived model changes, its callers face
different behaviour, though their code did not change.

So the skill asks, for every function the change can affect, **whether the
tests exercise the behaviour that changed through that function**, not
whether its lines ran.

## The rule

- `S0` is the set of functions whose code changed.
- A function is **affected** if it is in `S0`, or if it calls an affected
  function whose derived model changed.
- Propagation continues through a function only if its own model changed.
  A caller whose model did not change is still judged, since it calls
  something that behaves differently, but its own callers are not.
- A function in `S0` whose model did not change (a refactor, a log line)
  is judged itself. Its callers are not.
- A function whose model changed although none of its lines did is
  affected too, and its callers are walked. The cause is outside it: a
  header macro, an inline function or a type it uses, or a call the graph
  missed.

## What this version covers, and what it does not

| covered | not in this version |
|---|---|
| base: an analyzed idir of the commit the change starts from | a Coverity Connect snapshot as the base |
| head: an idir of the changed tree, built and analyzed with the base's commands, by you | building, analyzing or running the tests itself |
| C and Java | C++: refused (Step 3, exit 5) |
| coverage of the head's tests: GCC 14 gcov JSON, JaCoCo XML | clang / llvm-cov, Bullseye |
| `report.md`, `report.json`, and a local `errors.xml` viewed with `cov-format-errors` | committing to Coverity Connect |
| Coverity Analysis 2026.9.0 on Linux | other versions: refused (exit 4); Windows, not measured |

## Step 0: Rules, installation, and who is there to answer

Read `coverity/RULES.md`. Rules 2 (verify capture before believing a
result), 3 (pin one installation), 22 (say what you did not check) and 38
(ask only when interactive; otherwise report and stop) govern this skill
directly.

Pin the installation that analyzed both idirs (rule 3): ask, check project
notes, do not scan the disk. `$BIN` is its `bin/`.

Two steps cost real time: the judge (Step 5) and, if you ask for it,
`coverity-build-fidelity`'s binary comparison (Step 2). Interactive, the
skill says what each costs and asks. Not interactive, or unsure, it stops
before them and says how to resume.

## Step 1: Inputs

- **The base idir** and the commit it was built from.
- **The head idir,** built and analyzed with the base's own build and
  `cov-analyze` commands, and the commit it was built from. A different
  option on one side shows up as model changes the code did not cause.
- **The repository,** with both commits. Tags or SHAs.
- **Coverage of the head's tests:** a directory of gcov JSON (`gcov
  --json-format --conditions`, `.gcov.json` or `.gcov.json.gz`; measured on
  GCC 14 only) for C, or a JaCoCo XML report for Java. It may come from the build made
  under `cov-build` or from a separate build of the same commit.

Ask for the commits: an idir does not reliably record the commit it was
built from. The build roots of the capture and of the coverage need not be
given; the driver finds them by matching their paths to the repository at
each commit.

## Step 2: Capture coverage of the head (the `coverity-build-fidelity` dependency)

Test Advisor needs three things from the capture:

1. **The changed files were compiled into the head capture.** A changed
   file the capture missed has no functions, no models, no call edges and
   no coverage join, so its changes would look like code the build does
   not compile, a clean result.
   - This is the capture-coverage arm of `coverity-build-fidelity` (its
     Step 6, which runs the `coverity` skill's three-way capture-fidelity
     check). It reads the idir and the source tree and runs no build.
   - Have a capture-coverage verdict for the head idir already? Use it.
     Otherwise run that check first.
   - With it, every changed line outside every analyzed function (Step 3)
     gets a cause: the build does not compile that code in this
     configuration, or it was compiled and the capture missed it.
2. **The coverage build compiled the same sources as the Coverity build.**
   The join is on path and line.
   - The preflight (Step 3) checks the files in the coverage against the
     files captured and, for gcov, the function extents against the
     capture's.
   - `coverity-build-fidelity`'s binary comparison applies only when the
     tests ran on the build made under `cov-build`. When coverage comes
     from a separate build, it does not apply, and the report says so. It
     costs at least two full builds, so it runs only when you ask for it.
3. **The base and head were analyzed with the same options and Coverity
   version.** That is the preflight's check, not build fidelity's.

**When fidelity cannot be established for a file,** the skill does not
judge it. Its changed lines are listed as **not covered by any verdict**,
never as untested and never as code the build does not compile, and the
report's opening lines name those files and the reason. Without a
capture-coverage verdict at all, the report opens with "capture not
verified", and the lines outside every analyzed function carry no cause.

Adding coverage flags to the build under `cov-build` is one way to lose a
file: an unsupported compiler option stops a translation unit being
captured while the real compiler still runs (measured; see
`coverity/references/capture-fidelity.md`). Whether GCC 14's
`-fcondition-coverage` is such an option has not been measured.

## Step 3: Analyze

```bash
PYTHONPATH=<skill-dir>/tools python3 -m ta.run analyze \
  --base-idir <base-idir> --base-commit <commit> \
  --head-idir <head-idir> --head-commit <commit> \
  --repo <repo> --coverage <dir-or-xml> --coverage-format gcov|jacoco \
  --cov-bin $BIN --out <out-dir>
```

For Java, `--java-root` (repeatable, default `src/main/java`) says where
JaCoCo's packages live in the repository. `--diff-path` (repeatable)
limits the diff; the default is the directories the capture compiled
sources from.

**The preflight runs first.** Every run writes `<out-dir>/status.json`
(status, exit, reason, every check's result and detail, the judge count)
and ends with one line, `TA-STATUS: <status> <reason>`. Read it before
anything else:

| exit | status | when | then |
|---|---|---|---|
| 0 | ok | analysis written, no warnings | Step 4 |
| 1 | warned | analysis written; a check warned | Step 4, and carry each warning into the report |
| 2 | usage | bad arguments, a missing path, not a commit | fix the call |
| 3 | refused | `cov-analyze` options differ; an idir is not from its commit; no captured file is in the coverage; no coverage root | report the check and stop |
| 4 | gate | either idir analyzed by a Coverity version other than 2026.9.0 | stop: the call graph's reader is checked on 2026.9.0 only |
| 5 | cxx | C++ sources in the head | stop: calls through a base class are not expanded for C++, so callers of overridden methods would be missed and the report would look cleaner than the code is |

The checks:

- **Coverity version** of each idir, from `output/version`: both 2026.9.0.
- **`cov-analyze` options,** from each idir's `output/analysis-log.txt`,
  ignoring `--dir` and the job count: the same on both sides.
- **Language,** from `cov-manage-emit list-json`: C or Java project
  sources, and no C++.
- **Each idir built from its commit:** the MD5 of each source as the
  capture stored it, headers included (`cov-manage-emit
  print-source-files-stats`), against `git show <commit>:<file>`. A
  changed file that differs refuses; an unchanged one that differs warns
  (a file generated or edited during the build). No stored source
  matching the commit at all refuses, however many files differ.
- **Coverage matches the capture:** no captured file in the coverage
  refuses; captured product files missing from it warn.
- **For gcov, the coverage's function extents against the capture's:** a
  disagreement warns.

Then, deterministically, with no model involved:

1. **Changed functions.** `git diff -U0` hunks are mapped onto the function
   extents in the head idir's `output/FUNCTION.metrics.xml.gz`. **Every
   changed line no analyzed function contains is listed, not dropped:** a
   file the build did not compile, a header of declarations, a prototype,
   a field.
2. **Model diff.** One `cov-find-function --save` run over every function
   of each idir dumps its derived models. A script compares the `.dot`
   edges module by module, ignoring source positions (any edit shifts the
   lines below it) and the concurrency module (a unit test cannot exercise
   a concurrency change). Each changed model comes with its delta: the
   edges added and removed, which say in Coverity's own terms what
   changed.
3. **Call graph and impact walk.** Callers come from the head idir's
   cross-reference data. The walk applies the rule above, up to a depth of
   8 and 200 callers of one function; a function past either cap is marked
   truncated and its callers are not walked.
   - **C:** a call through a function pointer has no known target, so a
     caller through a pointer is not walked. The report lists every
     affected function whose address is taken, and the judge's evidence
     says when a function's address is taken and when it calls through a
     pointer.
   - **Java:** calls through a base type are expanded to every override.
     Method references and lambdas are not recorded at all, and nothing
     flags them.
   - **Model changes the walk from `S0` does not reach** become seeds of
     their own: each such function is affected, with the reason that its
     model changed although none of its lines did, and its callers are
     walked. Its evidence shows the model delta. In the eval fixture,
     `describe` is one: none of its lines changed and its one changed
     callee's model did not, but the header macro it passes and the
     string its callee returns both changed, and so did its model. A seed
     can also mean an analysis mismatch between the sides, or a module
     that changes on edits that change no behaviour; the report lists the
     seeds, and each seed's evidence lists this change's lines outside
     every analyzed function as candidate causes. What is left unreached
     after that is removed functions, whose callers changed and are
     walked already, and in principle a function new to the head with no
     changed line; neither measured project had one.
4. **Coverage join** on path relative to the repository root, and line.
5. **Fixed rules:**
   - **UNTESTED:** the function never ran.
   - **INSUFFICIENT:** a changed line, or a call into a changed function,
     never ran.
   - Everything else goes to the judge.
   - **On JaCoCo, a 0 on a call line, or right after one, goes to the
     judge,** not to a rule. JaCoCo counts a line only when a probe after
     it runs, so a line whose call throws reads 0 although it ran. gcov
     counts a line on entry and needs no such exception.
6. **Evidence** for each function left: why it is affected (its diff, or
   the call sites of changed callees with each callee's model delta), the
   target lines, and its source with the coverage of each line.

It writes `analysis.json`, one evidence packet per function in
`packets/`, the functions left for the judge in `judge.txt` (one per
line), and `run.json`, which `finish` reads.

## Step 4: Price the judge, and ask

The judge reads tests function by function, and most affected functions
reach it: on a release-to-release change of a Java library, 402 of 421.
Say how many functions `judge.txt` holds (the count is in `status.json`)
and that each is read against the test sources.

- **Interactive:** ask. The user can have all of them judged, a subset (a
  directory, the `S0` functions only), or none.
- **Not interactive, or unsure:** run Step 6 without verdicts, so the
  report carries the fixed-rule verdicts and every function left as
  NOT_JUDGED; report the count, and how to resume (judge, then run
  `finish` again); and stop.

## Step 5: Judge

The skill's own model follows **`references/judge-brief.md`** for each
function in `judge.txt`, reading its packet, and writes
`<out-dir>/verdicts.json`, one entry per function keyed by its id. For a
subset, add `"_unjudged": "omit"`, and every function without an entry
becomes NOT_JUDGED.

Each verdict records the model's exact id, the brief's version, and every
source read beyond the packet: test files, searches, and any probe
compiled in a scratch folder. That record is the point. After a defect
escapes, the requirement, the derived models, the model and the context it
had can all be examined and adjusted.

| verdict | meaning | a defect? |
|---|---|---|
| SUFFICIENT | a test exercises the changed behaviour through this function | no |
| WEAK | tests reach the function, but a specific changed behaviour reachable through it is not exercised | yes |
| INSUFFICIENT | a line carrying the change is never reached by any test | yes |
| UNTESTED | nothing reaches the function | yes |
| UNKNOWN | the evidence is not enough; the verdict says what is missing | yes, so the gap in the data is visible |
| UNREACHABLE_HERE | the code cannot run in this module: no caller, or every subclass here overrides it | no; reported |
| NOT_JUDGED | it reached the judge, and was not judged | no; reported |

The judge may add a note and a suggested test to a fixed-rule verdict
without changing it.

**A defect the judge notices in the code is by-catch,** not a test gap.
Reading tests and callees closely finds real defects. Write each one to
`<out-dir>/bycatch/<short-name>.md` (the brief says what it holds), and
never into a verdict, the report or the `errors.xml`, so nothing that
travels with the results carries it. Tell the user how many there are and where; whether to act on
them is theirs.

## Step 6: Write the output

```bash
PYTHONPATH=<skill-dir>/tools python3 -m ta.run finish --out <out-dir> --cov-bin $BIN
```

Its last line says what it wrote, for example `TA-STATUS: ok report.md and
report.json written; 2 issues in TA.INSUFFICIENT_TEST_COVERAGE.errors.xml
and ./out/ta-idirs/head`, or `...; no issues, so no errors.xml; 15
functions not judged`. With no issues, it removes any `errors.xml` and head
copy an earlier run left in `<out-dir>`.

- **`report.md`** leads with the verdict counts and the changes not
  covered by any verdict, then the gaps grouped by location, the walk, the
  model changes, the truncated and address-taken functions, and the model
  changes the walk never reached. **`report.json`** carries the same.
- **`TA.INSUFFICIENT_TEST_COVERAGE.errors.xml`:** each gap becomes a
  Coverity issue through the Third Party Integration Toolkit. `finish`
  writes an import JSON, and `cov-import-results --append` imports it into
  `<out-dir>/ta-idirs/head`, **a copy** of the head idir, in the same
  format as Coverity's own checkers. View it with `cov-format-errors`
  against that copy.
  - Each event names its file at the capture path when the capture stored
    that file exactly as it is at the head commit (checked per file, for
    every file an event names, changed or not), and the issue attaches to
    the stored copy, so the copy needs no source tree beside it and one
    `--strip-path`, the capture root. Only a file stored differently, or
    not stored at all, is exported from git into the import, and then the
    copy needs a second `--strip-path`, the export's root.
  - **Always `--append`, always on a copy.** Without `--append`,
    `cov-import-results` deletes every issue in the idir before importing
    (2026.9.0 help).
  - Checker `TA.INSUFFICIENT_TEST_COVERAGE`. The subcategory is the
    verdict: `untested` and impact High; `insufficient` and `weak`,
    Medium; `unknown`, Low. SUFFICIENT, UNREACHABLE_HERE and NOT_JUDGED
    make no issue.
  - The issue's `extra` is the function's mangled name.
  - One issue per affected function with a gap. Each event says which kind
    it is, so context never reads as another deficiency:

    | event | where | says |
    |---|---|---|
    | verdict (main) | the first line not exercised, else the function's first line | the verdict, whether a fixed rule or the judge decided it, and the reason |
    | Not tested | each unexercised line | what no test exercises |
    | Why affected | the first changed line; each call site of a changed callee | its own code changed, or it calls a changed callee here |
    | Context | the callee's definition; the function's first line | how the callee's derived model changed |
    | Suggested test | the main line | a test anyone can write from the sentence alone |

  - `cov-import-results` drops every issue of a file with more than 100
    issues that also averages more than one per ten lines (2026.9.0 help).
    One issue per function stays far below that.

**Nothing is committed.** The skill runs before a change is pushed, and
its output stays local.

## Step 7: Report

Verdict first (rule 21): the counts, then the gaps. Then what the run did
not cover (rule 22), each with its count:

- changed lines not covered by any verdict, with their cause when capture
  coverage gave one;
- every preflight warning;
- functions truncated by the depth or fan-out cap;
- affected functions whose address is taken (C), and the Java blind spot
  for method references and lambdas;
- functions affected only because their model changed, with none of their
  lines changed, and any model change still unreached;
- functions NOT_JUDGED;
- the by-catch count, and where it is.

## When to stop and hand over

- Exit 2 to 5: Step 3's table.
- Fidelity of the coverage build, when the tests ran on the build made
  under `cov-build` and the user wants it shown: `coverity-build-fidelity`.
- Judging whether a Coverity finding in the changed code is real is not
  this skill's job: `coverity-triage`.
