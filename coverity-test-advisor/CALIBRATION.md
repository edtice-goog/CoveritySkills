# Calibration status

This project's standard is that factual claims in a skill were established
by real runs. This file records what was run for `coverity-test-advisor`,
on what, and what is taken from the documentation or reasoned rather than
measured.

Every measurement below was made by the Test Advisor project, whose modules
this skill's tools are copied from, on two open-source projects with
`cov-analysis-linux64-2026.9.0` under Linux (WSL 2, Ubuntu 24.04),
`cov-analyze` at default options, Python 3.12.

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
| jackson-core 3.2.3 to 3.2.4 | | 365 | 421 | 415 judged, 60 WEAK; 402 of 421 needed the judge |

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
- **Changed lines outside every function** are listed. On jansson v2.15.1:
  14 changed functions, plus version macros, a build-file line and three
  prototypes listed as outside any function.
- **Model dumps:** one `cov-find-function --save` run per idir, 2-8 s each,
  for 1,230 functions (jansson) and 3,050 (jackson-core).
- **The concurrency module is ignored.** On jackson-core, 18 of 365 model
  changes were concurrency-only; ignoring them took 6 functions out of the
  affected set.
- **The walk:** on jansson every model change was reached from the changed
  functions. On jackson-core, 20 model changes were not reached, and the
  report lists them. The deepest chain was 6 on jackson-core and 1 on
  jansson, so neither hit the depth cap of 8 or the fan-out cap of 200.
- **Coverage join:** JaCoCo method names map to Coverity's for 2,687 of
  2,691 methods.
- **The JaCoCo rule** (a 0 on or after a call line goes to the judge) moved
  161 of 173 fixed-rule verdicts to the judge on jackson-core, and three
  judging rounds confirmed it.
- **`errors.xml`** was produced for both projects with `cov-import-results
  --append` into a copy of the head idir, and read with
  `cov-format-errors`.
- **The judge:** every judged verdict so far was made by Claude following
  the brief, in-session or by subagents. 415 verdicts on jackson-core, 15
  on jansson.

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

- **The call graph** is read from the emit database's cross-reference
  data, a format reverse-engineered by the Test Advisor project and checked
  byte for byte on 2026.9.0 linux64 only. Direct calls were checked
  complete against independent counts. The skill refuses any other
  version. `cov-manage-emit find --print-callees`, documented in
  2026.9.0, lists the functions each function calls; whether it can supply
  the edges, and the call-site lines the fixed rules need, is being
  measured.

## Not measured

- **The preflight** (same version and options, idir built from the named
  commit, coverage matching the capture). The measured runs were
  consistent because of how the datasets were built: one installation, one
  `cov-analyze` command line.
- **C++.** Refused.
- **Windows**, other Coverity versions, clang/llvm-cov coverage, Bullseye.
- **Coverage built under `cov-build`.** Both projects' coverage came from
  a separate build, so `coverity-build-fidelity`'s binary comparison was
  never needed, and whether GCC 14's `-fcondition-coverage` is captured
  under `cov-build` is not known.
- **A large C project.** Neither project came near the caps, and dump
  times on a project with tens of thousands of functions are not measured
  here.
- **This skill's own evals.** Not yet run.
