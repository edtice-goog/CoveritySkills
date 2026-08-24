---
name: coverity-build-fidelity
description: >
  Validate that a build captured by Coverity is faithful to the real build --
  that cov-build perturbed nothing and that capture actually covered the
  product code. Use this skill when the user asks whether a Coverity capture
  or scan "ran correctly", wants to compare a Coverity-wrapped build against a
  native or official release build, needs to gate a release on evidence that
  their SAST ran properly, asks why binaries differ between a normal and an
  instrumented build, or needs a trustworthy fidelity input for downstream
  issue-transition inference. Requires a local Coverity Analysis installation
  and the ability to run the build; this skill runs real builds and diffs real
  binaries rather than reasoning about what should have happened.
---

# Coverity Build Fidelity

Answer two questions with evidence, and keep them separate:

1. **Fidelity** -- did wrapping the build in `cov-build` change what the build
   produced?
2. **Coverage** -- did Coverity actually capture the product's translation
   units?

Neither alone is sufficient, and the reason is sharp: **a capture that emitted
nothing produces binaries byte-identical to native**, which is the best result
the fidelity check can report. Total capture failure and perfect fidelity have
the same signature. Never emit a verdict from one arm.

The deliverable is a report someone can act on -- a release gate decision, and
a machine-readable input for downstream inference -- not a boolean.

## The inference

Runs are not bit-reproducible; timestamps and GUIDs differ every time. So
compare delta *shape*, not delta *content*. Define `D(X,Y)` as the set of
differing regions between two artifacts. With `N`/`N'` native builds and `C`
the Coverity build:

```
D(N,N') = E                 the ephemeral noise floor -- measured, not assumed
D(N,C)  = E u K             everything above the floor is Coverity's
K       = D(N,C) \ D(N,E-control)
```

Pass iff `K` is empty, or every region in `K` is classified benign with
evidence. The control pair is what makes this an experiment rather than an
argument from plausibility -- without it, every difference merely *looks* like
a timestamp.

**Subtract by interval overlap, never offset equality.** The same field
surfaces as `(106192, 2)` in one pair and `(106191, 3)` in another, because
which bytes happen to collide varies run to run. `threeway.subtract()` uses
+/-8 bytes of slack. Exact keys generate false divergence.

## Two topologies

**Calibration** -- three local builds (two native, one Coverity), same
directory, path constant. Use this to validate tooling on a new toolchain, and
whenever production mode degrades.

**Production** -- an official binary `O` from CI plus local native `N` and
Coverity `C`. `O` takes the control role: `K = D(O,C) \ D(O,N)`. `O` need not
be reproducible, only *the same `O` in both comparisons*, so the whole
environment gap cancels. If `O` proves incomparable, **fall back to
calibration** and report the weaker honest claim: "could not tie to the
official build; established that Coverity does not perturb this build in this
environment."

## Step 0: Locate tools

Coverity install (ask the user; check project notes and memory first -- do not
scan the disk). `$BIN` below means `<install>/bin`. The skill's own tools live
in `tools/` and are pure stdlib -- no pip install:

- `pe.py` -- PE images, bare COFF objects, ar archives; ephemeral-field tables
- `bindiff.py` -- region localization, section mapping, paired string context
- `threeway.py` -- shape algebra, `subtract()` for `K`
- `paths.py` -- build-path recovery from embedded evidence

## Step 1: Pre-flight the reference artifact

Before spending builds, inspect `O` with `paths.py` and `pe.py`. Decide
whether comparison is even possible, and record answers in the report:

- **Toolset version.** A different MSVC/gcc version changes codegen wholesale
  and forces a coarser basis immediately. This is the most common blocker.
- **`/Brepro`?** An `IMAGE_DEBUG_TYPE_REPRO` debug entry means PE timestamps
  are content hashes, `E` collapses toward empty, and every remaining
  difference is meaningful.
- **Signed?** An official binary is usually Authenticode-signed and your
  rebuild will not be. The certificate table sits after the image and makes
  the reference larger, which trips the size-mismatch path and buries the real
  comparison. Excise it with `tools/pestrip.py IN OUT` -- truncates at the
  certificate offset, zeroes data directory 4 and the now-invalid checksum.
  Write beside the original; never overwrite the reference.
- **Stripped, or packaged in an installer?** Unpack first.
- **LTCG/PGO?** Profile-guided layout will not reproduce without the profile
  data. Expect to drop down the basis ladder.

## Step 2: Choose the comparison basis -- let the control pair choose it

Byte-region diffing is the finest basis but needs offset alignment. Compute
the control pair first. **If the control pair is a smear rather than a
localized set, drop a level and recompute:**

1. Byte regions `(file, offset, length)`
2. Per-section hashes and sizes
3. Symbol tables, export tables, per-function sizes
4. Normalized disassembly per function
5. Coarse metrics -- `.text` size, string table, import table

Whatever basis makes the *control* pair legible is the basis at which `K` is
evaluated. Report the basis with every verdict: `EQUIVALENT` at basis 1 is a
far stronger claim than the same word at basis 3, and downstream consumers
must not read them alike.

## Step 3: Decide scope, then probe whether path matters

Scope depends on what the user was given. Shipped images only, or objects and
libraries too? Objects localize a divergence to one translation unit and are
worth including when available -- but see the warning below.

**Probe before paying to reproduce the CI path.** Run `paths.py` on the
reference artifact. If it carries no build path, path mimicry is unnecessary
for that artifact and you can skip a lot of work. Measured on zlib:

| Artifact | Path leaks in? | Effect of a 34-char path difference |
|---|---|---|
| `zlib.dll` (CMake Release) | no | 2 differing bytes, both timestamps |
| `deflate.c.obj` | yes | 30,341 differing bytes, alignment destroyed |

If the path does leak, recover it (`references/build-path-recovery.md`) and
rebuild at that path. **If you cannot recover it exactly, match its LENGTH** --
alignment, not content, is what the algebra needs. Same measurement,
equal-length wrong path: 30,341 differing bytes drops to 51, and the survivors
are the path text itself plus a derived checksum.

## Step 3b: Expect the signing step to be absent from the capture build

Code signing is access-controlled by design -- the point of signing is that
only an authorised process may do it -- so it is commonly *not* part of the
build that Coverity captures. Many shops therefore run two builds: a capture
build and a production build, identical in every respect except that the
capture build skips signing. Sometimes it is the production build that carries
the instrumentation instead. Practice varies by shop, and how the access
controls are arranged is out of scope here.

What matters for this skill is the shape of the evidence, and it is the same
either way:

```
O_signed        the delivered artifact
N_unsigned      production build, signing step skipped   -- confirm N == O minus the signature
C_unsigned      the same build under cov-build           -- confirm C == N
```

Chained, those two comparisons say **what was analyzed is what was
delivered**, without ever needing to run Coverity over the signing step.

`tools/pestrip.py` exists to make the first comparison possible: excise the
certificate table from `O` so it can be compared against an unsigned build.
Validated end-to-end on curl (`references/worked-example-curl.md`), where
official, native and Coverity builds were all byte-identical once the
signature and the checksum it invalidates were normalized.

Do not try to bring the signing step *into* the capture. And note more
generally that transparent build wrappers can cause subtle failures in
tamper-resistant or integrity-checking build steps -- if a step behaves
differently under `cov-build`, excluding it and verifying by this chain is the
supported answer.

**This skill verifies reproducibility; it does not create it.** If a project's
builds are not repeatable, that is a finding to report, not a problem to fix
here.

## Step 4: Run the arms -- identical inner script

Both arms must invoke the **exact same inner build script**; the native arm
runs it directly, the Coverity arm runs it under `cov-build`. If the arms run
different command lines you are measuring the script difference, not
Coverity's effect. See `tools/zlib_build_inner.bat` for the pattern.

Hold constant: build directory, source path, environment, TZ, locale.
Snapshot each run's artifacts elsewhere before the next build overwrites them.
Exclude Coverity's own outputs (`idir/`, `emit/`, `build-log.txt`) from the
comparison.

## Step 5: Compute K, and classify what survives

Run `threeway.py`. The fast path resolves regions that are ephemeral by
construction (`references/ephemeral-fields.md`). **Everything it cannot
resolve goes to the model with paired string context, ASCII and UTF-16LE.**

This is where an LLM genuinely outperforms a release engineer: a `.rdata` or
`.debug$S` region whose two sides both render as English paths, timestamps, or
GUIDs is fast to adjudicate from the strings alone, and requires knowing which
sections hold data rather than code -- expert knowledge that turns a routine
gate into a research task for a human.

**Classify asymmetrically by section:**

- **Data sections** (`.rdata`, `.data`, `.debug$S`, archive headers) -- the
  model may classify confidently from the string pair. Record the evidence.
- **Executable sections** (`.text`, anything with the code characteristic) --
  presumed code. May **not** be waved off from strings. Requires
  disassembly-level evidence or escalation to a human expert.
- **Derived regions** -- a checksum or hash that differs *because* another
  region did (`.chks64` following a path change). Classify as derived only
  when you can name the region it depends on.

Categories: `ephemeral` / `environment` / `coverity-benign` /
`coverity-unexplained` / `derived` / `structural`. Structural findings --
a file present in one side and absent in the other, an added or removed
section -- are hard failures, not deltas.

## Step 6: Capture coverage (required)

**Run the `coverity` skill's capture-fidelity check** -- three independent
methods (`coverity list` / `cov-manage-emit` inventory, the
`scan-transparency/` process-tree readout, and an independent expectation
inferred from the source tree before the idir is opened), adjudicated
together. See that skill's `references/capture-fidelity.md`, and
`tools/capture_fidelity.py` to collect the evidence.

This is the second arm without which Step 5 is meaningless: an empty capture
yields byte-identical binaries and a clean `K`.

The minimum, if you are running the check by hand:

**Do not trust the headline percentage.** `cov-build` reports coverage against
a denominator that includes the build system's own throwaway compilations.
Measured on zlib: "40 compilation units (97%)" with one failure -- and the one
failure was `CheckIncludeFile.c`, a CMake `TryCompile` feature probe. Product
capture was 100%. A naive `< 100% -> fail` gate rejects a perfectly good
capture -- and passes an empty one, since 100% of nothing is 100%.

1. `$BIN/cov-manage-emit --dir <idir> list-capture-diagnostics` -> per-file
   capture percentage and AST presence (`list` alone tells you only that a
   record exists).
2. Partition into product sources and build-system probes (`TryCompile`,
   `CMakeScratch`, `CompilerId`, `ShowIncludes`, configure tests).
3. Compare product sources against what the build actually compiled.
4. Mind the denominator: a source built into two targets is **two TUs but one
   unique source**, and object count exceeds unique-source count accordingly.
5. **Check for a unity build before counting anything.** `CMAKE_UNITY_BUILD`
   batches many sources into one translation unit, so TU counts and source
   counts diverge by an order of magnitude. Measured on curl-for-win
   (`CMAKE_UNITY_BUILD=ON`, batch size 30): curl's entire tool and library
   appear as **7 unique product sources**, libssh2 as 2. Reconciling TUs
   against source files without accounting for this reports a catastrophic
   gap where none exists.
6. **Failures are not necessarily errors.** curl-for-win captured 1620 TUs at
   91% with `failures 153`, yet zero `[ERROR]` lines and zero non-zero
   `cov-emit` returns. Those 153 are compilations that produced no TU --
   overwhelmingly configure probes that fail *by design*. Read
   `BUILD.metrics.xml` (`failures`/`successes`/`recoverable-errors`) and the
   build log before treating a percentage as a defect.

**Capturing inside a container** keys the emit DB to the container hostname,
so reading the idir from the host fails with `No emit DB found for this host`.
Run `$BIN/cov-manage-emit --dir <idir> reset-host-name` first.

Report `capture_verified` as a **separate field**, carrying the capture
grade and the expected/captured/analyzable triple. Never fold it into the
fidelity grade -- the whole point of two arms is that they can disagree.

## Step 7: Report

Expressiveness belongs on disk; chat gets the verdict and pointers.

- `report.md` -- leads with the verdict, for a human at a release gate.
  Reports travel to people who were not in the room: formal register, state
  the scope limits, show suppressions.
- `fidelity.json` -- for downstream inference.

**Grade every artifact, then roll up.** A global verdict hides the one bad
component among ten and forces downstream to either discard good data or trust
bad data -- the cascading-confusion failure this skill exists to prevent.

Each artifact carries a **trust triple**:

- **Grade** -- `IDENTICAL` / `EQUIVALENT` (`K` empty) / `EQUIVALENT_WITH_NOTES`
  (`K` non-empty, all benign with evidence) / `DIVERGENT` / `INCOMPARABLE` /
  `MISSING` / `EXTRA`
- **Basis** -- which rung of Step 2 the verdict was reached at
- **Control quality** -- how clean the control pair was, and whether the noise
  floor was confirmed with a second control pair

Plus `capture_verified`, separately.

State the scope in the report itself: this validates that the wrapped build
produced equivalent output and that capture covered N of M product TUs. It
does **not** license "the analysis was complete." A release gate will
over-read a green check unless the artifact says so.

## Step 8: Emit a profile draft

Real applications carry knowledge the tool cannot infer -- an injected build
number, a licence blob, a prebuilt third-party DLL never built from source,
the CI path, the toolset pin. Emit `fidelity-profile.yaml` as a **draft** with
the regions you could not resolve and your best reading of each, for the user
to confirm. Read it on later runs so they get quieter and sharper.

**Suppressions are additive and always echoed.** A profile that can declare
regions benign is also a way to make failures vanish. Every applied rule
appears in the report -- "3 regions suppressed by profile rule `build-number`"
-- every run, never silently dropped. Otherwise the release-gate use case is
compromised by its own config file.

## When to escalate to a human

Say so plainly rather than guessing:

- Unresolved regions in an executable section
- A size change you cannot attribute to a string-length change
- Control pair illegible even at basis 5
- `K` non-empty and no profile rule or known class explains it

A "needs expert review" verdict naming the exact offsets is a useful result.
A confident wrong verdict is not.

## Intermittency

A single control pair is a *lower bound* on `E`. Parallel link order, hash
iteration order, and `-j` races are intermittent, so one pair can understate
the floor and manufacture a non-empty `K`. Do not pay for a second control
pair unconditionally -- add one only when `K` is non-empty, to test whether
the region is merely intermittent noise. Building `-j1` removes the largest
source at the cost of wall time.

## Worked examples

- `references/worked-example-zlib.md` -- calibration topology on MSVC/Ninja:
  three native builds establish the noise floor, a fourth under `cov-build`
  measures `K`. Also documents the two tooling errors the runs exposed.
- `references/worked-example-gcc.md` -- gcc/ELF. The noise floor is empty
  (builds are bit-reproducible unaided), so `cmp` suffices. Also documents a
  live **false pass**: byte-identical binaries from a capture that emitted
  nothing, because `--gcc` does not match CMake's `cc`.
- `references/worked-example-curl.md` -- **production topology against a real
  vendor release**. curl 8.21.0_7 reproduced byte-identically from the
  official reproducible build, giving `D(O,N)` empty and therefore `K =
  D(O,C)` with no noise floor at all. Both `K` and the reproduction came out
  empty. Documents the unity-build, container-hostname, and
  network/TLS-interception traps.
