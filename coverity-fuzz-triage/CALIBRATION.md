# Calibration status

This project's standard is that factual claims in a skill were established by
real runs. This file records what was run for `coverity-fuzz-triage`, on what,
and what is reasoned rather than measured.

Environment: Windows 11, installations under `C:\Coverity\`. Three analyzer
versions were used, each against an idir it wrote:

| idir | written by | size | analyzed with |
|---|---|---|---|
| proftpd 1.3.9 (`coverity-demo-data-workspace/idirs/v1.3.9`), 149 C files, 2102 functions | 2025.9.0 (cov-build, gcc, WSL) | 2 GB | 2025.9.0 win64, scratch copy |
| subversion + sqlite amalgamation (`C:\Data\tool-interop\coverity\idirs\svn-augmented-post-enrichment`), 9533 functions | 2026.3.0 | 185 MB | 2026.3.0 win64, scratch copy |
| fixtures (`evals/fixtures/*`), emitted with bare `cov-emit --c` / `--c++` | 2026.6.0 | -- | 2026.6.0 win64 |

All dates 2026-09-09.

## Verified by direct execution

- **Fuzz confirmation on the fixture** (`lookup.c` + `use.c`, 2026.6.0,
  clang-cl from `C:\Program Files\LLVM`, LLVM 22): candidate at `use.c:18`;
  slice of `escaped` (2 prototypes); `lookup`'s generic model has two
  behaviours (non-null, `returnsnull`); harness + stub built with
  `-fsanitize=fuzzer,address -Zi -Od`; ASan access-violation at address 0
  in `escaped` at `sink(r->id + v);` within the first second; crashing
  input `0a 0a 41 0a`. `evals/run.sh` reproduces the chain.
- **Two Windows facts**: Git Bash rewrites `/Zi` to a path (use `-Zi`);
  the fuzzer exits 127 unless `LLVM\lib\clang\<ver>\lib\windows` (the ASan
  DLL) is on `PATH`.
- **Derived models as stubs** (subversion, 2026.3.0): `cov-find-function
  --save --module generic` takes ~0.25 s per callee and writes a `.dot`
  automaton; stubs for both `svn_dirent_skip_ancestor` and `relpath_depth`
  brought `fetch_conflict_details`'s NULL_RETURNS back in the slice with the
  original event chain; either alone did not; a stub that guarded its
  `dereference(<arg 0>)` with `if (a0)` made the finding vanish. The
  fixture's NULL_RETURNS needed `--checker-option NULL_RETURNS:stat_
  threshold:0` at defaults (one call site cannot satisfy the 80% rule); the
  subversion case under `--all --aggressiveness-level high` did not.
## Reasoned, not measured

- That a stub printed from the derived model can only take behaviours the
  analyzer granted the callee, so a crash through it is a path the analyzer
  would have accepted. Follows from what the model is; the subversion
  NULL_RETURNS experiment is consistent with it.
- The assertion oracle for claims that do not crash (`REVERSE_INULL`,
  `DEADCODE`): described from mechanism, not run.

## Not verified

- Triage of an ordinary Coverity finding (one with an event path, not a
  shape-checker candidate) end to end: the recipe was exercised on the
  fixture and on the subversion NULL_RETURNS restore only. The demo-data
  idirs are the intended first batch.
- Seeding the corpus from the finding's events.
- Any target with more than two scalar parameters or with buffer
  parameters; the fixture harness takes two bytes.
- Linux builds (`clang -fsanitize=fuzzer,address`, LeakSanitizer,
  MemorySanitizer).
- The `uninit` model module as a stub source; `--stubs` on the slicer
  (not built).
