# Calibration status

This project's standard is that factual claims in a skill were established
by real runs. This file records what was run for `coverity-test-advisor`,
on what, and what is taken from the documentation or reasoned rather than
measured.

`tools/ta/` is Test Advisor release v1.4, copied unchanged apart from line
endings, which the repository stores as LF. Except for the
gap fixture's section, every measurement below was made by the Test
Advisor project, on two open-source projects with
`cov-analysis-linux64-2026.9.0` under Linux (WSL 2, Ubuntu 24.04),
`cov-analyze` at default options (jackson-core: `--java`), Python 3.12.

- **jansson**, a C library: four base/head pairs, one release to the next
  and three single commits. Coverage from GCC 14, `-O0 -g --coverage
  -fcondition-coverage`, read with `gcov-14 --json-format
  --branch-probabilities --conditions` (format version 2), from a separate
  build tree of the same commit.
- **jackson-core**, a Java library: 3.2.3 to 3.2.4. Java capture of a Maven
  build on JDK 21; JaCoCo 0.8.14 coverage of the whole test suite.

## Verified by direct execution

### Results per pair

| pair | changed | models changed | affected | verdicts |
|---|---|---|---|---|
| jansson v2.15.0 to v2.15.1 | 14 | 12 | 15 | 13 SUFFICIENT, 2 WEAK; all 15 went to the judge |
| jansson, `json_dump_file` checks `fclose` (one commit) | 1 | 0 | 1 | 1 INSUFFICIENT, from the fixed rules |
| jansson, `json_pack` scanner (one commit) | 1 | 14 | 16 | 2 INSUFFICIENT, 14 SUFFICIENT |
| jansson, `json_array_grow` uses realloc (one commit) | 4 | 1 | 4 | 4 SUFFICIENT |
| jackson-core 3.2.3 to 3.2.4 | 160 | 365, of which 347 count | 421 | 237 SUFFICIENT, 60 WEAK, 77 INSUFFICIENT, 36 UNTESTED, 11 not reachable in the module; 402 of 421 went to the judge; 173 issues |

On jackson-core, 18 of the 365 model changes were concurrency-only and do
not count (below).

- **The two WEAK verdicts on v2.15.1.** The recursion-depth limit came with
  tests, all of which nest arrays. `json_object_deep_copy` and
  `json_object_equal` take the new depth parameter and pass depth + 1, and
  no test nests objects past the limit. Every line ran.
- **The `json_dump_file` gap:** the `return -1` after a failed `fclose`
  never ran. The suggested test writes to `/dev/full`, where `fclose`
  fails with `ENOSPC`.
- **The scanner change shows the walk at full width.** `next_token`'s model
  changed, and every function that reads a format string calls it, so
  their models changed in turn. The walk stopped at `json_pack_ex` and
  `json_unpack`, whose models did not change. The two INSUFFICIENT
  verdicts: the `*` modifier inside an array or object (`[s*]`,
  `{s:s*}`) is never packed.
- **Models name the change.** On v2.15.1, `do_dump`, `do_deep_copy` and
  `do_equal` gained `<arg 2> < 2048`, the new depth limit; the unpack
  functions gained `noescape(<arg 3>)`, the key parameter.

### The pieces

- **Function extents** from `output/FUNCTION.metrics.xml.gz` equal gcov's
  own function start and end lines (jansson, measured once). Java method
  names join Coverity's after dropping the return type: 2,842 of 2,842.
- **Changed lines outside every function** are listed. On jansson v2.15.1,
  besides the 14 changed functions: version macros, a build-file line, two
  preprocessor lines of a header with no function bodies, and three
  prototypes.
- **Model dumps:** one `cov-find-function --save` run per idir, 2-8 s each,
  for 1,230 functions (jansson) and 3,050 (jackson-core).
- **The concurrency module is ignored.** On jackson-core, 18 of 365 model
  changes were concurrency-only; ignoring them took 6 functions out of the
  affected set.
- **The call graph:** on jansson 2.15.1 its 572 project call edges are the
  same 572 that documented `cov-manage-emit find --print-callees` lists,
  compared by function name, with none missing on either side.
- **The walk:** on jansson every model change was reached from the changed
  functions. On jackson-core, up to release v1.1, 20 model changes were
  not reached and were only listed; release v1.2 walks from each such
  function. On jackson-core none remain (no seeds), and the 17 unreached
  model changes are removed functions, whose callers changed and are
  walked. The deepest chain was 6 on jackson-core and 1 on
  jansson, so neither hit the depth cap of 8 or the fan-out cap of 200.
- **Java method references:** the compiler generates a function for a
  method reference, with the reference's line as its whole extent. Up to
  release v1.1, that function took the call the real method makes on its
  line, so one call edge was lost and three overloads of one jackson-core
  method had model changes the walk never reached. Release v1.2
  attributes each call to the innermost real method: the three are
  reached through the real edge and judged (all SUFFICIENT), the
  generated function is no longer affected, 404 functions go to the judge
  instead of 402, and the issue count stays 173. Under v1.2 jackson-core
  has 423 affected functions.
- **Coverage join:** JaCoCo method names map to Coverity's for 2,687 of
  2,691 methods.
- **The JaCoCo rule** (a 0 on or after a call line goes to the judge) moved
  161 fixed-rule verdicts to the judge on jackson-core. The judges found
  34 of them exercised (a call that threw) and 127 real gaps, now with a
  reason: 14 WEAK, 66 INSUFFICIENT, 47 UNTESTED. A later fix to the call
  test (`if (` and `while (` lines are not calls) returned 7 to the fixed
  rules. Most of the moved verdicts were gaps; the rule made each of them
  get checked.
- **`errors.xml`:** `cov-format-errors --dir <out>/ta-idirs/head
  --json-output-v10` on jansson v2.15.1 gives 57 issues, among them the 2
  Test Advisor issues with their events. Committed with
  `cov-commit-defects` to a Coverity Connect 2026.9 test instance, a
  function's issue kept its CID across three recommits of the same
  version. Test Advisor sets `extra` to the function's name, so the
  issue's identity does not depend on its event text; how Connect matches
  imported issues was not measured.
- **Events at the capture path** (release v1.4): with every file an
  event names stored by the capture exactly as at the head commit, every
  event names its file at the capture root and no source is exported from
  git:
  5 issues over jansson's four pairs, and 173 issues with 1,197 events on
  jackson-core. One import with the capture tree checked out at another
  version still attached the issues to the stored files.
- **The judge:** the verdicts were made by Claude from the evidence and the
  tests, in-session or by subagents: Opus 5.5, with Sonnet 5.5 for the
  first 56 jackson-core verdicts. 33 judged verdicts on jansson, and 402
  on jackson-core under the final rules. `references/judge-brief.md`
  distils those rounds; it was not the prompt for most of them.

### The driver and its preflight

- **`analyze`:** the jansson v2.15.0 to v2.15.1 pair (gcov JSON) exits 0
  with 15 functions left for the judge, in 4.5 s; the jackson-core pair
  (JaCoCo) exits 0 with 402 left, in 69 s, mostly the two model dumps
  (404 with release v1.2). A
  pair settled by the fixed rules alone exits 0 with none left.
- **`finish`** reproduces the earlier runs' verdicts and issues exactly on
  both projects: 2 issues on jansson, 173 on jackson-core.
- **Each refusal,** on a scratch copy: a wrong commit exits 3, differing
  `cov-analyze` options exit 3, an idir analyzed by 2026.6.0 exits 4, and
  a C++ capture exits 5.
- **"Built from its commit"** compares the "MD5 sum" that documented
  `cov-manage-emit --dir <idir> --tu-pattern 'file(".*")'
  print-source-files-stats` reports for each stored source with `git show
  <commit>:<file>`. It is the MD5 of the stored file: equal for all 19
  project files of jansson 2.15.1, 6 of them headers, and all 138 of
  jackson-core.
  - `list-json`'s documented `primaryFileHash` is a different digest: it
    matched the file at the commit for 0 of 26 jansson translation units.

### This skill's eval: the gap fixture

`evals/run.sh` on `cov-analysis-linux64-2026.9.0` under WSL 2, with
`tools/ta/` as copied from Test Advisor release v1.4, gcc 13 for the
Coverity build and gcc-14/gcov-14 for the coverage build. `analyze` exits
0 in about 20 s (the install and the work directory both on a Windows
drive; most of a full run's time is `cov-configure` and the two analyses
over that drive):

- `S0` is `parse_len` and `strutil_name`. `parse_len`'s new `return -1`
  never ran: INSUFFICIENT from the fixed rules.
- `parse_len`'s model changed (`dereference(<arg 0>)` gone; `<arg 0> ==
  0`, `<return value> <- == -1` and `negative_return` added), so
  `field_len`, its caller, is affected; `field_len`'s model changed in
  turn, so `record_size` is affected. Both calls ran: both go to the
  judge.
- `strutil_name`'s model did not change: it goes to the judge, and is a
  boundary, so its caller `describe` is not walked from it.
- `describe`'s model changed anyway (`ptr_arith: + ptr_arith(<arg 0>)`)
  with none of its lines changed. It is affected for that reason alone,
  and goes to the judge; its evidence shows the delta and lists this
  change's lines outside every function (`src/strutil.h`, line 4) as
  candidate causes. Release v1.1 only listed it as a model change the
  walk never reached; from v1.2 none is left unreached.
- The `STRUTIL_VERSION` line in `strutil.h` is listed as in no function.
- `finish` without verdicts writes one issue, `parse_len`'s, subcategory
  `insufficient`, imported into a copy of the head idir; the other four
  are NOT_JUDGED. Its events name `strutil.c` at the head capture path,
  and no source is exported from git into the import.
- A copy of the head idir re-analyzed with `--all` exits 3, options
  differ; the head idir given the base's commit exits 3, not from its
  commit.
- 30 of 30 cases as expected on a clean run with release v1.4,
  2026-11-05.

## Read from the 2026.9.0 documentation, not re-measured

- **`cov-import-results` without `--append`** deletes every issue in the
  intermediate directory before importing.
- **The density limit:** a file with more than 100 issues that also
  averages more than one issue per ten lines has all its issues excluded,
  with a console warning.
- **`cov-find-function --save`** is documented as writing
  `<key>.<module>.models.xml`, `<key>.<module>.model_edges` and a `.ps`
  file, and as requiring Graphviz. On 2026.9.0 it writes `.dot`, `.json`,
  `.actions` and `.traces` per module, and the skill compares the `.dot`
  edges (as `coverity-verify` and `coverity-missing-models` also read
  them).

## Undocumented, and gated

**The call graph's cross-reference data.** The skill reads it from the
emit database directly (SQLite, read only), in a format reverse-engineered
by the Test Advisor project and checked byte for byte on 2026.9.0 linux64
only, and refuses any other Coverity version.

Documented `cov-manage-emit find --print-callees` was measured as the
alternative, and does not replace it yet:

- **C:** the same 572 edges on jansson 2.15.1, in 0.07 s for the whole
  idir.
- **Java:** on jackson-core 3.2.4, in 1.5 s, it marks dynamic dispatch
  ("Virtual call to:" on 5,143 of 8,376 call lines). The two graphs share
  4,330 edges; `--print-callees` has 198 the cross-reference graph lacks,
  and that graph has 2,751 it lacks, 2,420 of them override edges Test
  Advisor adds itself. Most of the gap is naming: `--print-callees` names
  an inherited method by the receiver's class, the cross-reference data by
  the defining class. It is not reconciled.
- **Call-site lines:** `--print-callees` gives none, only where each callee
  is declared, and the fixed rules and the evidence need the line of each
  call. Searching each caller's lines for `<callee>(` finds the same lines
  for 500 of 572 jansson edges; it misses calls made through macros.
  `find --print-debug` carries a location per call node, in an AST dump
  whose format is not described.

## Not measured

- **The preflight on inputs that were not built consistently,** beyond
  the scratch copies above. The measured pairs were consistent because of
  how the datasets were built: one installation, one `cov-analyze` command
  line.
- **C++.** Refused.
- **gcov JSON from a GCC other than 14.** It is not rejected. GCC 13's
  JSON has no condition records, which Test Advisor's reader treats as
  optional, so it would be read with less detail.
- **Windows**, other Coverity versions, clang/llvm-cov coverage, Bullseye.
- **Coverage built under `cov-build`.** Both projects' coverage came from
  a separate build, so `coverity-build-fidelity`'s binary comparison was
  never needed, and whether GCC 14's `-fcondition-coverage` is captured
  under `cov-build` is not known.
- **A large C project.** Neither project came near the caps, and dump
  times on a project with tens of thousands of functions are not measured
  here.
- **The brief as the prompt for a whole run.** It distils the measured
  rounds, and was not the prompt for most of their verdicts.
- **What changed `describe`'s model:** the macro value it passes or the
  string its callee returns. Not isolated.
- **The behaviour evals in `evals/evals.json`.** Not yet run.
