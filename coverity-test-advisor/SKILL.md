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

<!-- DRAFT on the coverity-test-advisor branch: tools/ and evals/fixtures
are added when the Test Advisor driver is done; commands follow its
proposed interface. Remove this comment before landing. -->

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

## What this version covers, and what it does not

| covered | not in this version |
|---|---|
| base: an analyzed idir of the commit the change starts from | a Coverity Connect snapshot as the base |
| head: an idir of the changed tree, built and analyzed with the base's commands, by you | building, analyzing or running the tests itself |
| C and Java | C++: it stops (Step 1) |
| coverage of the head's test run: GCC 14 gcov JSON, JaCoCo XML | clang / llvm-cov, Bullseye |
| `report.md`, `report.json`, and a local `errors.xml` viewed with `cov-format-errors` | committing to Coverity Connect |
| Coverity Analysis 2026.9.0 on Linux | other versions (Step 1); Windows, not measured |

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

## Step 1: Check that this version applies

Stop and say why, before anything runs, when:

- **The project has C++ translation units.** Calls through a base class are
  expanded to their overrides for Java only, so a C++ run would miss the
  callers of every overridden method, and the report would look cleaner
  than the code is.
- **Either idir was analyzed with a version other than 2026.9.0** (each
  idir's `output/version`). The call graph reads the emit database's
  cross-reference data, an undocumented format whose parser has been
  checked byte for byte on 2026.9.0 only. A different version could parse
  into a wrong graph without an error.
- **The two idirs differ in Coverity version or `cov-analyze` options**
  (the command line in each idir's `output/analysis-log.txt`). A
  difference in either shows up as model changes the code did not cause.
- **The coverage is in a format this version does not read.**

Name both commits: the base idir's and the head's. An idir does not
reliably record the commit it was built from.

## Step 2: Capture coverage of the head (the `coverity-build-fidelity` dependency)

Test Advisor needs three things from the capture:

1. **The changed files were compiled into the head capture.** A changed
   file the capture missed has no functions, no models, no call edges and
   no coverage join, so its changes would read as "not built", which looks
   like a clean result.
   - This is the capture-coverage arm of `coverity-build-fidelity` (its
     Step 6, which runs the `coverity` skill's three-way capture-fidelity
     check). It reads the idir and the source tree and runs no build.
   - Have a capture-coverage verdict for the head idir already? Use it.
     Otherwise run that check first.
   - With it, every changed line outside every analyzed function (Step 4)
     gets a cause: the build does not compile that code in this
     configuration, or it was compiled and the capture missed it.
2. **The coverage build compiled the same sources as the Coverity build.**
   The join is on path and line.
   - The preflight (Step 3) checks the files in the coverage against the
     files captured, and the coverage tool's function extents against the
     capture's.
   - `coverity-build-fidelity`'s binary comparison applies only when the
     tests ran on the build made under `cov-build`. When coverage comes
     from a separate build, it does not apply, and the report says so. It
     costs at least two full builds, so it runs only when you ask for it.
3. **The base and head were analyzed with the same options and Coverity
   version.** That is Step 1's check, not build fidelity's.

**When fidelity cannot be established for a file,** the skill does not
judge it. Its changed lines are listed as **not covered by any verdict**,
never as untested and never as not built, and the report's opening lines
name those files and the reason. Without a capture-coverage verdict at all,
the report opens with "capture not verified", and the lines outside every
analyzed function carry no cause.

Adding coverage flags to the build under `cov-build` is one way to lose a
file: an unsupported compiler option stops a translation unit being
captured while the real compiler still runs (measured; see
`coverity/references/capture-fidelity.md`). Whether GCC 14's
`-fcondition-coverage` is such an option has not been measured.

## Step 3: Analyze

```bash
python3 tools/test_advisor.py analyze --bin $BIN \
  --base-idir <base-idir> --base-commit <sha> \
  --head-idir <head-idir> --head-commit <sha> \
  --repo <repo> --coverage <file> --coverage-format gcov|jacoco \
  --out <out-dir>
```

It runs a preflight first, and refuses or warns:

- base and head carry the same Coverity version and `cov-analyze` options;
- each idir was built from the commit you named: the MD5 of every source
  as captured, against `git show <commit>:<file>`;
- the coverage matches the capture: the same files, and the same function
  extents.

Then, deterministically, with no model involved:

1. **Changed functions.** `git diff -U0` hunks are mapped onto the function
   extents in the head idir's `output/FUNCTION.metrics.xml.gz`. **Every
   changed line no analyzed function contains is listed, not dropped:** a
   file the build did not compile, a header of declarations, a prototype,
   a field.
2. **Model diff.** One `cov-find-function --dir <idir> --save --output
   <dir> .` per idir dumps every function's derived models. A script
   compares the `.dot` edges module by module, ignoring source positions
   (any edit shifts the lines below it) and the concurrency module (a unit
   test cannot exercise a concurrency change). Each changed model comes
   with its delta: the edges added and removed, which say in Coverity's
   own terms what changed.
3. **Call graph and impact walk.** Callers come from the head idir's
   cross-reference data. The walk applies the rule above, up to a depth of
   8 and 200 callers of one function; a function past either cap is marked
   truncated and its callers are not walked.
   - **C:** a call through a function pointer has no known target, so its
     callers are not walked. Every affected function whose address is
     taken is flagged, in the report and in the judge's evidence.
   - **Java:** calls through a base type are expanded to every override.
     Method references and lambdas are not recorded at all, and nothing
     flags them.
   - **The check that costs nothing:** a model that changed but that the
     walk never reaches from `S0` is listed. It means an analysis mismatch
     between the sides, a call edge the graph misses (a function pointer,
     a lambda), or a module that changes on edits that change no
     behaviour.
4. **Coverage join** on path relative to the repository root, and line:
   the coverage root is stripped on one side and the capture root on the
   other, so the two trees can sit anywhere.
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

It writes the fixed-rule verdicts, one evidence packet per function left,
and the count left for the judge.

## Step 4: Price the judge, and ask

The judge reads tests function by function, and most affected functions
reach it: on a release-to-release change of a Java library, 402 of 421.
Before it runs, say how many functions are left and that each is read
against the test sources.

- **Interactive:** ask. The user can judge all of them, a subset (a
  directory, the `S0` functions only), or none.
- **Not interactive, or unsure:** report the fixed-rule verdicts, the
  count, and the command that resumes (Step 5 on the packets in
  `<out-dir>`), and stop.

## Step 5: Judge

The skill's own model follows **`references/judge-brief.md`** for each
packet, and records for each verdict the model's exact id, the brief's
version, and every source it read beyond the packet: test files, searches,
and any probe it compiled in a scratch folder. That record is the point. After a
defect escapes, the requirement, the derived models, the model and the
context it had can all be examined and adjusted.

| verdict | meaning | a defect? |
|---|---|---|
| SUFFICIENT | a test exercises the changed behaviour through this function | no |
| WEAK | tests reach the function, but a specific changed behaviour reachable through it is not exercised | yes |
| INSUFFICIENT | a line carrying the change is never reached by any test | yes |
| UNTESTED | nothing reaches the function | yes |
| UNKNOWN | the evidence is not enough; the verdict says what is missing | yes, so the gap in the data is visible |
| UNREACHABLE_HERE | the code cannot run in this module: no caller, or every subclass here overrides it | no; reported |

The judge may add a note and a suggested test to a fixed-rule verdict
without changing it.

**A defect the judge notices in the code is by-catch,** not a test gap.
Reading tests and callees closely finds real defects. Write each one to
`<out-dir>/bycatch/`, one file per defect, and never into a verdict, the
report or the `errors.xml`, so nothing that travels with the results
carries it. Tell the user how many there are and where; whether to act on
them is theirs.

## Step 6: Write the output

```bash
python3 tools/test_advisor.py finish --bin $BIN --out <out-dir> \
  --verdicts <out-dir>/verdicts.json
```

- **`report.md`** leads with the verdict counts and the files not covered
  by any verdict, then the gaps grouped by location, the walk, the model
  changes, the truncated and address-taken functions, and the model
  changes the walk never reached. **`report.json`** carries the same.
- **`errors.xml`**: each gap becomes a Coverity issue through the Third
  Party Integration Toolkit. The skill writes an import JSON, and
  `cov-import-results --append` imports it into **a copy** of the head
  idir, which writes `TA.INSUFFICIENT_TEST_COVERAGE.errors.xml` in the
  same format as Coverity's own checkers. View it with `cov-format-errors`.
  - **Always `--append`, always on a copy.** Without `--append`,
    `cov-import-results` deletes every issue in the idir before importing
    (2026.9.0 help).
  - Checker `TA.INSUFFICIENT_TEST_COVERAGE`. The subcategory is the
    verdict: `untested` and impact High; `insufficient` and `weak`,
    Medium; `unknown`, Low. SUFFICIENT and UNREACHABLE_HERE make no issue.
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
- functions truncated by the depth or fan-out cap;
- affected functions whose address is taken (C), and the Java blind spot
  for method references and lambdas;
- model changes the walk never reached;
- functions the user chose not to judge.

## When to stop and hand over

- C++, a version outside 2026.9.0, or mismatched analysis options: Step 1.
- The preflight refuses: report what it found, and stop.
- Fidelity of the coverage build, when the tests ran on the build made
  under `cov-build` and the user wants it shown: `coverity-build-fidelity`.
- Judging whether a Coverity finding in the changed code is real is not
  this skill's job: `coverity-triage`.
