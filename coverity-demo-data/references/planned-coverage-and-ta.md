# Planned: coverage and Test Advisor data

**Status: not implemented.** These are design decisions and measurements
collected while building a dataset that carries gcov coverage. They were
measured on jansson: 34 releases plus 7 single commits, autotools. The tools in
this skill do not do any of this yet. Read this as the direction the skill is
taking, not as steps to follow. When a step lands, it moves into `SKILL.md` and
leaves this file.

## Coverage

### Decided

- **Every version gets coverage**, from **one whole-suite test run**. Runs are
  never merged or accumulated. A shipped figure means what one real test run
  exercised.
- **Per-test coverage is optional** and ships beside the whole-suite set. Totals
  always come from the whole-suite set.
- **It lives inside the idir**, at `idirs/<tag>/coverage/`. The publisher
  already copies each idir whole and checksums every file, so a `coverage/`
  folder ships and is verified with no tool change.
- **Connect does not consume it.** Coverage is data attached to the idir; a
  viewer outside Connect reads it.
- **No backdate.** Coverage belongs to its snapshot.
- **No scope filtering at build time.** Test programs' own coverage stays in
  the raw data. Hiding files that are not part of the snapshot is the
  consumer's job. This is why "capture only what ships" does not apply here.
- **No path rewriting.** Record the coverage tree's root and the capture's root
  per version, and let the consumer strip both and join on the repo-relative
  path.

### Build

- Use a **separate build tree at the same commit**, and refuse if the SHA
  differs from the capture's. Coverage flags change the compile commands, and
  the capture must stay the project's default build.
- Use the capture's own recipe, compatibility fixes included, plus
  `-O0 -g --coverage -fcondition-coverage`. **Put the flags in CFLAGS, never only
  in LDFLAGS.** A project's `Makefile.am` can replace LDFLAGS for its test links
  (for example `LDFLAGS = -static`). The links still get libgcov because libtool
  passes CFLAGS at link time.
- **GCC 14 or later** for condition coverage. GCC 13's JSON has no condition
  records. Line, function and branch counts are identical under both. The
  capture keeps the project's default compiler. If GCC 14 fails on a release, a
  fallback build may ship instead, but only one set ships per idir and
  `coverage.json` names it.
- **The object set must equal the capture's.** Coverage flags may change how
  code is built, never what is built. Diff the object lists and stop on a
  difference.

### Tests

- **Never accept a pass on its own.** A suite can report every test passing and
  still run nothing. In the measured case, a missing helper interpreter named in
  a shebang made the case loop run zero times, and the test exited 0. The
  detector: **any product source the build compiled that has no `.gcda` after
  the tests is a flag.** If a missing test-time dependency is the cause, supply
  it without editing the tests, for example through a read-only overlay in an
  unprivileged mount namespace. Otherwise record it. In the measured case the
  fix took one release from 22% to 82% of lines.
- **`make check`'s exit code is not the test result.** A docs target can fail
  after every test has passed. Record the harness result, the make exit code and
  the first failing target separately.
- **A failure can be a toolchain mismatch**, for example a symbol-list test
  reading `nm -D` output whose format has changed since the release. Record it;
  do not patch it. Coverage still exists for what ran.
- **Harness counts count drivers, not cases.** An automake harness can report
  "2 tests" for a driver that runs hundreds of cases. If case counts matter,
  read the suite's own output.
- **Coverage is not deterministic when the project randomises.** A hash seeded
  from `/dev/urandom` takes different paths every run. One file measured 83%,
  85% and 94% on three runs of one release. When other runs exist, record the
  files that move as known variability. In every case, `coverage.json` states
  how many runs shipped and whether they were merged.

### Collect

- **Collect per object directory.** libtool builds each source twice: PIC
  objects in `.libs/` and the static ones beside the source. Which set gets
  `.gcda` files depends on how the tests link. Run
  `gcov --json-format --branch-probabilities --conditions` separately in each
  directory, because the same source names collide otherwise. GCC 9 and later
  produce self-contained JSON, so lcov and gcovr are not needed.
- **Merge across directories**: sum line, function and branch counts, but take
  the **union** of condition outcomes. An outcome is covered if any directory
  covered it.
- **Report product coverage separately** from the test programs' own sources,
  with a **per-file table beside the total**. Vendored code can dominate a
  total: one release dropped from about 96% to 60% when a 1,900-line vendored
  file at 11% arrived.

### Per-test sets

- **Zero the counters from the tree root.** Zeroing relative to the test
  directory leaves the library's counters accumulating, and every unit then
  looks identical.
- **Each per-test set ships its own `.gcno` files.** A rebuild changes the
  stamps, and gcov refuses a mismatched pair.
- **Per-unit denominators differ** when tests link statically, because each
  binary holds only the objects it references. Never total across units.

### Per-version `coverage/` contents

- `coverage.json`. This holds:
  - tag, SHA, `coverage_root`, `capture_root`, `backdated: false`;
  - toolchain, and the fallback reason if a fallback set shipped;
  - build: the configure line, and the compiled set compared with the capture;
  - tests: harness result, make exit code, first failing target, missing
    commands, test compatibility rules, and product sources without `.gcda`;
  - `coverage_run`: runs shipped and merged or not;
  - `known_variability`;
  - product totals for lines, functions, branches and conditions;
  - the gcov JSON format version.
- Raw data:
  - a tar of the `.gcno`/`.gcda` files;
  - `json/<object dir>/*.gcov.json.gz`;
  - the test logs;
  - a summary with totals, then per file;
  - the toolchain;
  - the coverage root;
  - the SHA.
- Optional `per-test/`: an index, its own `.gcno` tar, and one directory per
  unit.

Cost on the measured corpus: about 25 s per release for build, tests and gcov.
It runs alongside the serial capture sweep without interference, because the
two trees share nothing.

### Open

- `cov-commit-defects` against an idir with `coverage/` inside is **not
  measured**. Listing, capture diagnostics, merge-key export and a full
  re-analysis are all unchanged with it present, but commit was not tried. The
  layout stays either way. A loader that finds commit objects moves the folder
  aside for the commit.

## Test Advisor runs

### Decided

- Demo data **creates Test Advisor runs** for each pair of a version and its
  predecessor whose tests can run. They ship as a companion to the dataset.
  Whoever loads it chooses analysis only, or analysis plus the Test Advisor
  streams.
- **Test Advisor idirs ship without a findings export.** The per-version
  findings export serves defect history across versions, and the triage that
  travels with it. Test Advisor defects carry no triage records, and this skill
  does not triage, so nothing would read one.

### Needed in the tools

- **Two strip paths at commit.** A Test Advisor idir needs `--strip-path` for
  both the capture root and the source export its events point into.
  `commit_sweep.py` takes one prefix today. It needs a repeatable
  `--strip-path`, with the "stripped nothing" guard applied per prefix.

### Open

- Confirm the tooling is the `coverity-test-advisor` skill, so demo data calls
  one thing.
- Confirm whether Test Advisor writes its defects into the idir, or only into
  separate results files.

## Related things learned

- **The findings export is a cache.** `phase2.py` and `publish_dataset.py`
  write `phase2-issues.json` only when it is missing. A step that adds defects
  to an idir afterwards leaves it stale without warning. Either write it last,
  or refuse a cached export that is older than the idir's analysis.
- **A dataset's identity is its `SHA256SUMS`**, not the hash of any archive
  made from it. A tar rebuilt from the same files can hash differently and
  still hold the same dataset.
- **Telling releases from commits:** a `git describe` label resolves through
  `git rev-parse --verify refs/tags/<label>` via its `-g<sha>` suffix. Use
  `git show-ref --verify refs/tags/<label>` to ask whether it is really a tag.
