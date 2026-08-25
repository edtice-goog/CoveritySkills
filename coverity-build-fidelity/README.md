# coverity-build-fidelity

Part of [CoveritySkills](../README.md).

Answers "did my Coverity capture actually run correctly?" — by building twice
without Coverity and once with it, then proving that the deltas between every
pair have the same *shape*. Runs are never bit-reproducible (timestamps, GUIDs),
so the native pair is used as a control that measures the ephemeral noise floor
empirically; anything the Coverity pair shows above that floor is Coverity's
contribution.

Built for release engineering and SSDLC gating, where somebody has to decide
whether a scan can be trusted before shipping — and for feeding downstream
issue-inference with a fidelity signal it can scope its trust to.

```
K = D(reference, coverity) \ D(reference, native)      pass iff K is empty
```

## What the skill knows that saves time

- **Two arms, never one.** A capture that emitted *nothing* produces binaries
  byte-identical to native — the best-looking result the fidelity check can
  return. Total capture failure and perfect fidelity have the same signature,
  so binary equivalence is always paired with a capture-coverage reconciliation
- **The capture percentage is a trap.** `cov-build` measured "40 compilation
  units (97%)" on zlib and the one failure was a CMake `TryCompile` probe;
  product capture was 100%. A naive `< 100% → fail` gate rejects good builds
- **Path *length*, not path content, is what matters.** A 34-character path
  difference produced 30,341 differing bytes in an object file; a 41-character
  *content* difference at equal length produced 51. Match the length when you
  cannot recover the CI path exactly
- Probe whether a path leaks at all before paying to reproduce it — a CMake
  `Release` DLL turned out completely path-immune while its objects did not
- Subtract regions by interval overlap, never offset equality — the same field
  surfaces at `(106192, 2)` in one pair and `(106191, 3)` in another
- Ephemeral-field tables for PE images, bare COFF objects, and `ar` archives,
  so the fast path resolves every routine difference and only genuine signal
  reaches the model
- Classify asymmetrically: a data-section region whose two sides render as
  English paths or timestamps is the model's strong suit; an executable-section
  region is presumed code and may not be waved off without disassembly evidence

## Requirements

- A local Coverity Analysis installation (developed against 2026.3.0 on Windows)
- The ability to run the build under test, at least twice
- Python 3 — the tools are pure stdlib, no `pip install` on a build machine

## Layout

```
coverity-build-fidelity/
├── SKILL.md                      # procedure (pre-flight → basis → path →
│                                 #   arms → K → classify → capture → report)
├── references/
│   ├── ephemeral-fields.md       # per-format field tables + measured baseline
│   ├── build-path-recovery.md    # evidence sources, CI signatures, length rule
│   └── worked-example-zlib.md    # the calibration session, with the numbers
└── tools/                        # pure-stdlib, dependency-free
    ├── pe.py                     # PE images, COFF objects, ar archives
    ├── bindiff.py                # region localization + paired string context
    ├── threeway.py               # shape algebra, subtract() for K
    ├── paths.py                  # build-path recovery
    └── *.bat                     # zlib calibration builds (native/cov/CI-path)
```

Status: validated end-to-end twice — calibration topology on Windows/MSVC
(zlib), and **production topology against a real vendor release**: curl
8.21.0_7 was reproduced byte-identically from curl's official reproducible
build, so `D(O,N)` was empty and Coverity's contribution `K` was measured
directly against the shipped artifact. Both came out empty. MinGW/gcc, ELF, and Mach-O
field tables are stubbed but not yet measured — run the three-native
calibration and confirm a zero-unresolved baseline before trusting a new
toolchain. Capture coverage — this skill's required second arm — now lives in
the `coverity` umbrella skill as the three-method capture-fidelity check;
Step 6 requires it and keeps only a minimum inline fallback.
