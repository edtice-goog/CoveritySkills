# Reusing an intermediate directory for speed

The second use of an idir you did not capture: not "the build is gone" but
"the build is *slow*". Take a reference idir from a full build -- CI, a
release job, another checkout -- and bring it up to date with a working tree,
re-emitting only what changed.

**This deliberately violates rule 8** (capture into a fresh intermediate
directory). Rule 8 exists because a reused idir makes a broken capture look
perfect. This procedure reuses one anyway, in exchange for speed, and
therefore has to earn that exception with checks rule 8 would otherwise make
unnecessary.

## When it is worth doing, and when it is not

The payoff is proportional to build-plus-analyze time. On a four-file project
it is noise. On a codebase that takes hours to build and analyze, re-emitting
three translation units instead of ten thousand is the difference between a
feedback loop and a nightly job.

The cost is that every safeguard in rule 8 is now yours to enforce.

### Where the saving actually comes from

Two phases, and they have **different granularity**:

- **Capture works on files**, because that is what build systems operate on.
  A build system recompiles whole translation units, so a changed header
  forces every TU that includes it back through `cov-emit`.
- **Analysis works on functions.** `cov-analyze` is incremental by default and
  caches per-function results in the idir.

That gap is what makes reuse pay even when the recompile is broad. The most
common header edit adds a prototype or a macro that the dependent TUs do not
otherwise use: every one of them recompiles, but their *functions* are
unchanged, so the analysis cache still hits. (This is the same observation
behind the old habit of hand-compiling a single file when you knew you had
only added a prototype.)

So do not judge the technique by the recompile count alone. A run can
re-emit most of the project and still finish far faster than a cold analysis,
because the expensive phase is the one working at function granularity. And
preserving the idir is what preserves that cache -- capturing into a fresh one
throws it away by definition.

Measured on FFmpeg (2053 TUs, 16 cores, full detail in `CALIBRATION.md`):

| scenario | capture | analyze | total |
|---|---|---|---|
| cold -- fresh idir, no cache | 373s | 794s | **1167s** |
| release tag -> master (99% of TUs re-emitted) | 344s | 407s | **751s** |
| current idir + 3 edited files | **8s** | **78s** | **86s** |

Read the middle row carefully: capture saved almost nothing, and the run was
still 36% faster. Read the last row for what the technique is actually for --
19.5 minutes down to 1.4.

### The deployment this is really for

The realistic setup is not a months-old release tag. It is an idir published
by a **post-merge CI job** -- a GitHub Action that captures and analyzes on
every merge to the mainline -- so a developer picks up an idir that is hours
old, with a delta of a handful of files and a build cache that is already
~99% warm.

That is the case to optimise for and the case to quote numbers from. A large
delta against an old tag is the worst case, useful mainly for finding the
break-even point below.

### What a full capture actually costs, relative to the build

The number that drives every estimate below. **Budget 2x to 4x the plain build,
and expect the upper half of that range.** Two independent measurements:

| Subject | Plain build | Full `cov-build` | Ratio |
|---|---|---|---|
| Linux kernel (CI, three runs: 17:33 / 17:38 / 17:30) | 4 m 34 s | 17 m 34 s | **3.8** |
| LLVM + clang, gcc 13.3, `-j8` | 1 h 44 m | -- | **3.1** measured per-edge |

The LLVM figure is a per-edge ratio over 1,123 identical ninja edges completed
by both builds (27,467 s of capture edge-time against 8,975 s plain), not an
extrapolation of wall-clock.

**Why not 2x?** The floor argument is sound: capture is essentially a
compilation, so if the frontends were equally efficient the cost would double.
For clang builds Coverity's frontend *is* clang, emitting an AST instead of
object code; for other compilers it is the EDG frontend, comparable in
performance to the underlying compiler. That reasoning gives 2x, and 2x is
reliably a **lower bound** rather than a prediction.

The gap above it is not fully explained, and this skill does not pretend
otherwise. Contributing factors, in rough order of confidence:

1. **Compiler probes.** A new set of compiler options forces Coverity to
   re-probe. The first build therefore pays twice -- probing *and* parsing.
   Projects with many distinct option sets (the kernel especially) pay more.
   `emit/<HOST>/config/<md5>/` holds one directory per probed configuration, so
   this is countable: count it before blaming anything else.
2. **Process model.** gcc spawns one `cc1`/`cc1plus` per compilation line;
   Coverity appears to launch one `cov-emit` per file, which would repeat
   per-process overhead that the compiler amortises. *Plausible, not verified
   here.*
3. **Cache asymmetry, when comparing against a cached build.** `ccache` can
   accelerate the plain build while capture re-emits anyway -- the kernel's
   pervasive `__FILE__`/`__LINE__` use keeps its re-emit rate high even on an
   unchanged tree. A ratio measured against a warm cache is inflated and is not
   a frontend-vs-frontend comparison. Say which you measured.

None of these indicate misconfiguration. A ratio in the 3-4 range is normal;
treat a ratio far *outside* 2-4 as the signal worth investigating.

**The consequence for this procedure.** Capture, not analysis, is the long
pole, and it scales with the build. On the kernel, reuse took the same work
from **17 m 34 s to 5 m 42 s -- a 3.1x capture saving**, landing at 1.2x the
plain build instead of 3.8x. That is the entire value proposition in one row of
someone else's CI dashboard.

### The yardstick is the inner loop, not the clean build

Easy to measure against the wrong baseline. Beating a *clean capture* is not
the bar. Nobody working on code runs a clean build -- they run an **incremental**
one, and that is the cost they have already accepted.

The Linux kernel numbers make the point. A clean build is **4 m 34 s** and a
full capture **17 m 34 s**; reuse brings capture to **5 m 42 s**, a 3.1x saving
and only 1.2x the clean build. Excellent against the wrong denominator --
and still **too slow**, because the developer's actual inner loop is an
incremental build measured in seconds.

A common shape of work, though not everyone's: write code to confirm the
strategy without worrying about edge cases; go back and clean it up; then, when
it looks ready, run the tools to validate before committing or opening a pull
request. At *that* moment the tool is standing between the developer and a
commit they already believe in. **Minutes is too long.** Several minutes on
every pre-commit hook or PR check is how a tool gets disabled.

So state the target properly:

> Bring the idir current in time proportional to **what actually changed**,
> comparable to the incremental build the developer just ran -- not
> proportional to the size of the project.

Consequences that should shape every choice in this procedure:

- **Re-emit only the changed translation units.** Anything that re-emits
  broadly has already failed, even when it beats a clean capture. "Faster than
  a full recapture" is not the same as "fast enough to run before every
  commit".
- **Judge cost against `git diff`, not against the emit size.** Five changed
  files should cost roughly five files' worth of capture. If it costs a
  thousand files' worth, report that -- the header cascade, not the file count,
  is what went wrong.
- **The analysis side is already there.** `cov-analyze` is incremental and
  caches per-function results, so a re-analysis after a small delta is a small
  fraction of the first one. Capture is the half that needs this procedure.

This is also why the reuse path exists at all rather than telling people to run
a clean capture on a fast machine. Hardware does not fix a workflow problem: a
17-minute capture on a 4x faster box is still four minutes, and four minutes is
still too long to sit in front of.

### The break-even point

The saving is proportional to how *small* the delta is. Past some fraction of
the codebase, updating an idir stops being cheaper than capturing a new one --
you pay the copy, the surgery, and the reconciliation, and still rebuild most
of the project.

Compute the ratio before starting and say it out loud:

```bash
changed=$(git diff --name-only <tag> | grep -cE '\.(c|cc|cpp|cxx)$')
total=$(cov-manage-emit --dir <ref-idir> list | grep -c '^[0-9]* ->')
```

A handful of files against thousands is the case this procedure was built for.
A delta approaching the size of the emit is a recapture wearing a disguise --
do the clean capture instead, and get rule 8's guarantees back for free.

Judge the result against the **incremental build**, not the clean one (see
above). If bringing the idir current takes materially longer than the
incremental build the developer just ran, the procedure has not delivered what
it exists to deliver, however favourably it compares to a full recapture.

There is no single threshold worth hard-coding, because the real cost driver
is how far the *header* changes cascade, not the file count. Report the ratio,
and if the delta capture ends up recompiling most of the project anyway, say
so and prefer the fresh capture next time.

**Do not use this for anything anyone will rely on**: no release gates, no
compliance evidence, no "the scan is clean" claim. It is a developer
iteration tool. When the answer matters, capture fresh.

## Three applicability gates, checked before anything else

All are pass/fail. If any fails, the technique does not apply -- say so
and use a fresh idir. Knowing when it does not apply is half of this skill.

### Gate 0: the analyzing platform must match

Cheapest gate, so check it first. `cov-analyze` is incremental by default, but
the cache is invalidated when the **analysis binary** differs -- not merely the
version. Measured 2026-08-25: an idir analyzed by `cov-analysis-win64-2025.9.0`
and re-analyzed by `cov-analysis-linux64-2025.9.0`, *identical product
version*, printed

```
[STATUS] Incremental analysis could not be used because
analysis binary changed.  This may take a while.
```

and performed a full analysis. This is correct, conservative behaviour: the
results are right, but the re-analysis saving is gone.

The idir names its own last analyzer -- line 1 of `output/summary.txt` is the
full `cov-analyze` command line including the install path:

```bash
head -1 <reference-idir>/output/summary.txt
```

**The test is the OS that runs the build and the analysis, not the OS of the
developer's workstation.** That difference decides real cases:

| CI analyzes on | developer analyzes on | verdict |
|---|---|---|
| Linux | Linux (bare metal, WSL, or a Linux container) | **applies** |
| Linux | VS Code **remote development into a Linux container** | **applies** -- guest OS matches CI, workstation OS is irrelevant |
| Linux | Windows, natively | **does not apply** |

The container row is not an edge case; it is the common modern arrangement,
adopted so local builds do not diverge from CI. Do not reject it by looking at
the laptop.

When this gate fails, **say so and stop.** Capture still ports -- idirs are
platform-independent, and that is unchanged -- but every analysis pays full
price, which removes the reason to reuse. This is an enumerated limitation of
the technique, not something to engineer around.

A case worth calling out because it is the *best* one for this technique: two
branches in **two containers on the same host**, from the same base image,
shuffling one idir between them. The analysis binary is byte-identical, so
Gate 0 passes cleanly and incremental analysis survives every hop.

**When you control the environments, normalize the checkout path.** If both
containers mount the source at the same absolute path -- `/workspace`, `/src`,
whatever -- then the paths recorded in the idir are already correct in the
other environment, and an entire class of problem disappears:

- no capture-root inference, and no chance of inferring it wrongly
- the staleness check compares like with like
- model provenance resolves directly instead of via a remap
- generated files under a build directory resolve too, since that path matches
  as well

This costs nothing to arrange up front, and there is **no equivalent fix
afterwards**. In particular, do **not** reach for `--strip-path`: it changes
the paths *presented in Coverity Connect*, and has **no effect on the idir's
contents**. The emit database still holds the original absolute paths, so
every idir-side consumer -- the staleness check, model provenance, capture-root
inference -- sees exactly what it saw before. `--strip-path` solves a reporting
problem, not a portability one.

Divergent paths are a nuisance rather than a blocker, because the tools here
infer and remap a capture root. But that inference is a heuristic, and a
heuristic is worth avoiding when a shared mount point would have made it
unnecessary.


### Gate 1: the build system must track header dependencies

The procedure hands the "what does this change affect?" question to the build
system. A build system that cannot answer it will answer *nothing* and look
successful doing so.

**The probe.** Pick a header the reference idir says is widely included, touch
it, capture the incremental build, and compare what got recompiled against
what the idir says includes it:

```bash
cov-manage-emit --dir <ref-idir> --tu-pattern 'header("shared\.h$")' list   # expectation
touch include/shared.h
cov-build --dir <probe-idir> --config <cfg> <build command>                 # reality
cov-manage-emit --dir <probe-idir> list
```

Measured, both outcomes:

| build system | idir says include it | build recompiled | verdict |
|---|---|---|---|
| CMake + make (generates `.o.d` files) | 3 | **3**, exactly the right three | **applies** |
| proftpd, hand-written recursive make | 71 | **0** | **does not apply** |

Agreement means the build system knows its dependency graph and you can trust
it. Disagreement means it does not, and the reused idir would silently keep
stale ASTs for every affected TU.

`cov-build` does warn on the failing case -- `[WARNING] No files were emitted`
-- which is rule 9's loud variant. Treat a delta capture that emits **zero**
TUs while files demonstrably changed as a hard stop, never as "nothing to do".

**This is the one place the include closure is consulted, and it is used as a
check on the build system, not as an invalidation set.** Computing "what does
this header affect" and re-emitting that set is a fool's errand -- in C++
headers carry code, and the surface is enormous and subtle. Once the gate
passes, the build system is the authority.

Rules of thumb before running the probe: ninja, MSBuild, Bazel, and
CMake-generated makefiles track header dependencies. Hand-written recursive
make usually does not, and an unused `depend:` target with no `.d` files on
disk is a strong tell. Run the probe anyway; it is cheap and it is evidence.

### Gate 2: the reference idir must have a known git identity

You cannot compute a correct delta without knowing what the idir was built
from. **If the idir does not come with a commit or tag, do not use this
skill.** Guessing the base revision produces a delta that is wrong in both
directions -- files re-emitted that did not need it, and files left stale that
did.

Insist on the identity, then **verify the claim** rather than trusting it.
`primaryFileHash` cannot do this (see `CALIBRATION.md` -- it is not a hash of
the source), but `primaryFileSizeInBytes` matches the on-disk file exactly, so:

```bash
git show <tag>:<path> | wc -c        # against primaryFileSizeInBytes from list-json
```

A mismatch means the idir was not built from the revision you were told. Stop.

## Routing: which path applies

Compute the delta against the recorded tag:

```bash
git --no-pager diff <tag> --name-only
```

Then, for each changed file, ask one question: **is it the primary source file
of exactly one TU in the reference idir?**

- **Every changed file is a changed primary TU** -> the fast path. No build
  recording needed.
- **Anything else** -- a changed header, a new file, a deleted file, a rename,
  or a file matching zero or several TUs -> the build-recording path.

That question is already answered by the same lookup the fast path needs, so
routing costs nothing extra.

## The fast path: changed primary TUs only

Validated end to end against a full-recapture oracle (see below).

1. **Copy the idir.** Never operate on the original.
2. **`cov-manage-emit --dir <copy> reset-host-name`.** A no-op when the idir
   was made on this machine; required when it came from another host, because
   the emit is keyed by hostname (`emit/<HOSTNAME>/`).
3. For each changed file, locate its TU and capture the recorded invocation:
   ```bash
   cov-manage-emit --dir <copy> --tu-pattern 'file("/src/foo\.c$")' \
       print-compilation-info --detailed
   ```
   This prints the `cov-emit` line, the `cov-translate` line, the `cov-build`
   line, and the **working directory** for each. It is the direct route --
   `list-capture-invocations` carries the same data but needs parsing.
4. **Delete the stale TU** -- `cov-manage-emit --dir <copy> --tu <id> delete`.
   See *Stale TUs* below; this step is not optional and not reorderable.
5. **Re-emit** by running the recorded `cov-emit` argv from the *new* tree's
   corresponding working directory, with idir paths rewritten.
6. Reconcile the TU inventory, then analyze.

### What actually needs rewriting

Fewer things than expected, when the build uses relative includes. On the
calibration project only **three tokens** referenced the old idir:

```
--dir=<ref-idir>                                  -> the copy
--pre_preinclude <ref-idir>/emit/<host>/config/<hash>/gcc-config-0/coverity-macro-compat.h
--pre_preinclude <ref-idir>/.../coverity-compiler-compat.h
```

The source argument was `lastlog.c` and the includes were `-I.. -I../include`
-- all relative, so they follow from running in the new location's working
directory. A build that uses absolute paths will need more rewriting; diff the
recorded line against what you construct and check.

## The build-recording path: everything else

Let the build system determine what a change affects.

1. Copy the idir; `reset-host-name`.
2. **Touch the changed files** in the working tree.
3. **Capture an incremental build into a separate, fresh idir:**
   ```bash
   cov-build --dir <delta-idir> --config <cfg> <build command>
   ```
   The build recompiles what it believes the change affects; Coverity captures
   exactly that. If this emits **zero** TUs, gate 1 was wrong -- stop.

   **Check the build's exit code, not just the emitted count.** `cov-emit`
   parses independently of the compiler's warnings-as-errors settings, so a
   capture can report *"Emitted N compilation units (100%) successfully"* for a
   compile the real toolchain rejected. Measured: FFmpeg builds with
   `-Werror=missing-prototypes`; a source edit that tripped it made `gcc` fail
   and `make` abort, while Coverity emitted the TU regardless. `cov-build`
   flags this separately -- *"[WARNING] Build command ... exited with code 2"* --
   and that warning is the only signal. This is rule 9 inverted: the familiar
   trap is a green build that captured nothing; here the capture was fine and
   the build was broken. A reused idir updated from a half-finished build is
   stale in exactly the places the build did not reach.
4. **Delete the corresponding stale TUs from the copy** (matching by
   repo-relative path, since the absolute paths differ between locations).
5. **Transplant:** `cov-manage-emit --dir <copy> add <delta-idir>`.
   Documented caution: *"Combining intermediate directories can cause defect
   reports to appear or disappear, because the information in one intermediate
   directory can affect the information in another."* That is precisely what
   you are doing deliberately, which is why the oracle check matters.
6. Reconcile and analyze.

## Multiple build targets in one idir

An ideal deployment captures and analyzes **one target at a time**: a build
producing both `-m32` and `-m64` should be two Coverity analyses. Real idirs
are not always built that way -- which is precisely why `--one-tu-per-psf`
exists and defaults to true.

**Detect this at import, before anything else looks at the emit.**

```bash
python3 tools/build_targets.py --bin <bin> --dir <idir>
```

Targets are fingerprinted by the **type model** the front end was given, not by
grepping the compiler argv. Measured on gcc:

| flag | `-m64` | `-m32` |
|---|---|---|
| `--type_sizes` | `e16Pdlx8fi4s2` | `e12dx8Pfil4s2` |
| `--size_t_type` | `m` | `j` |
| `--ptrdiff_t_type` | `l` | `i` |

The type model generalises to cross-compilers and other architectures, and it
is the thing that actually changes how the code is read.

**Then one question: does the local build produce every target the idir
contains?**

- **Yes** -- nothing to do. The delta capture refreshes each of them.
- **No** -- **strip the others at import** (`--strip-keep N`). Left in place
  they are never rebuilt, go stale, and `--one-tu-per-psf` then chooses between
  a fresh TU and a stale one by an algorithm the documentation warns "might
  make different choices" between runs.

### Why this broke the staleness check

Measured on a 3-file, 2-target idir: **6 TUs, but `--tus-per-psf=latest`
reports 3.** This skill's own staleness check was written against `latest` and
would therefore have examined half the emit and called it clean -- and the
unexamined half is exactly the target the local build does not rebuild.

The check now lists **all** TUs and reports when sources carry more than one.
Any tool that reasons about "the TUs" in an imported idir has to decide this
consciously; `latest` is a convenience that silently discards a build target.

## Remember the determinations, per project

Several facts here are expensive to derive and stable across sessions: the
build targets and which to keep, the capture root, whether the build system
tracks header dependencies (gate 1), the stream, and the cost estimate that
chose the method. Recomputing them every session wastes minutes and, worse,
invites a different answer each time.

Cache them per project, and record what invalidates each:

| determination | invalidated by |
|---|---|
| build targets / strip choice | a new baseline idir, or a build-system change |
| capture root | a new baseline from a different machine or path |
| gate 1 (header deps) | build-system change |
| stream / url | `coverity.yaml` changing |
| cost estimate + chosen method | new snapshots -- re-check periodically, see SKILL.md |

The estimate is the one to re-derive on a schedule rather than cache
indefinitely: it is the input to a decision that should be revisited.

## The staleness check: mandatory, between capture and analysis

Every other safeguard here is a *policy* — fetch this baseline, route that way,
delete before adding. Policies can be wrong. This step is the one that catches
it when they are, so **run it after the delta capture and before every
analysis**, regardless of how the idir was obtained.

The invariant, scoped to builds that do not generate source:

> Every TU's primary source file must be **present on disk**, and its size must
> match what was emitted.

Presence is the test — **not git tracking**. A file you created and have not
added yet is ordinary work in progress, and the analysis of it is valid.

| bucket | meaning | action |
|---|---|---|
| `OK` | present, size matches the emit | analyze |
| `STALE` | present, size differs | re-emit the TU |
| `ORPHAN` | **absent from the tree** | **delete the TU** |
| `UNTRACKED` | present but not in git | fine — see the note below |

`ORPHAN` is the one the build system can never report. A source file deleted
upstream leaves its TU behind in the idir, and nothing in a build tells you to
remove it. It is then analyzed **as if the code were still there**.

**Repairing it is a plain delete, and it is safe.** Measured on the FFmpeg
case: `cov-manage-emit --dir <idir> --tu <id> delete`, then re-analyze. The
defect set lost **exactly the orphan's own finding and nothing else** -- 935
sites to 934, zero new findings, every other result identical.

That held even though the deletion was a nasty one. Upstream had replaced the C
with **assembly** and relocated the init function to a new file, so the idir
carried a *stale duplicate definition* of `ff_dwt_init_x86` -- live at
`snowdsp_init.c:332`, stale at the deleted `snowdsp.c:881` -- for a function
actively called from `snow_dwt.c:858`. Removal still subtracted cleanly.

One number worth noting: that single orphaned TU defined **14 functions**.
Orphans withdraw more from the analyzable set than their file count suggests.

Measured on FFmpeg: updating a `n8.2-dev` idir to master left
`libavcodec/x86/snowdsp.c` in the emit — deleted upstream in commit
`5c830fccf4` — and it **contributed a DEADCODE finding to the results**. Three
`.c` files were deleted across that range; one had been captured. A two-month
delta on a real project produced exactly this, silently.

The `UNTRACKED` note is informational, not a failure: `git diff` cannot report
changes to an untracked file, so the delta computation will not see it move.
For work in progress that is harmless — you are editing it and rebuilding
anyway. For a **build-generated** source it is the hazard that puts the project
outside this skill's scope.

This check is also what makes the fetch policy purely economic. A baseline that
is newer than your checkout is *detectably* wrong rather than silently wrong,
so choosing not to fetch one is a decision about resources, not correctness.

## After analysis: check where the models came from

The staleness check works at **file** granularity and runs *before* analysis.
This one works at **model** granularity and runs *after* it, and is strictly
stronger -- it asks the question that actually matters: *where did the model
for each analyzed function come from?*

`output/callgraph-metrics.json.gz` answers it directly. Each entry has
`identifier`, `file`, `line`, `hasImplementation` and `models`, and the count of
implementation models matches `Functions analyzed` in `summary.txt` exactly. A
model whose `file` no longer exists is a function analyzed from code that is
gone.

```bash
python3 tools/model_provenance.py --dir <analyzed-idir> --tree <working-tree>
```

Measured on FFmpeg, before and after repairing one orphaned TU: **11 function
implementations** were being served from a file deleted upstream, and after
deleting the orphan, zero. The file-level view showed the same problem as a
single orphan.

That gap is the point. A ghost model is not just extra findings in dead code:
**it is handed to every caller of that function**, so it can change results in
files that are perfectly current. And when the function also exists in a live
file -- as `ff_dwt_init_x86` did, live at `snowdsp_init.c:332` and stale at the
deleted `snowdsp.c:881` -- the emit holds two definitions of one actively
called symbol, and nothing at file granularity shows you that.

Sources outside the capture root (system headers with inline functions, 10
functions in the measured run) are checked at their own absolute path rather
than remapped, since they legitimately live outside the tree.

## Renames need no special handling

A rename is a delete plus an add, and both halves are already covered: the old
path's TU becomes an `ORPHAN` and is deleted, the new path is a new file and is
captured. **Nothing needs to recognise the two halves as related.**

Defect continuity across a rename is Coverity Connect's job, via antecedent
merge keys (`coverity/RULES.md` rule 27) -- not this skill's, and not something
to reimplement by matching up added and removed files.

The only cost of a large move is analysis time: moved files are re-emitted
because their paths changed. That is a performance property, not a correctness
one, and special-casing it would buy nothing while adding exactly the kind of
subtle bug this procedure cannot afford.

## Stale TUs: the rule this procedure exists to enforce

**The danger is path divergence, not reuse itself.** Which case you are in
decides how much work you have to do:

**Same paths — Coverity handles it.** If the working tree is at the same
absolute path the reference idir was captured from, just capture the
incremental build *into* the preserved idir. A re-emitted TU **supersedes** its
predecessor for that primary source file. Measured on FFmpeg: an idir holding
2053 TUs, re-captured after 2027 recompiles plus 7 genuinely new files, came
out at **2060 TUs, not 4080**, with `--tus-per-psf=latest` equal to the total.
No duplicates, no manual deletion.

**Different paths — you must delete first.** Two TUs whose primary source
files sit at different absolute paths are *different primary source files*, so
`--one-tu-per-psf` will not deduplicate them. Both get analyzed. This is the
case when the idir came from CI, another host, or another checkout — which is
the whole premise of importing one, so it is the common case in practice.

Measured, on a four-file project where the reference contained an array
overrun that the working copy **fixed**:

| idir | defects | files analyzed | reported in |
|---|---|---|---|
| reference (unfixed) | 1 | 4 | `<ref>/src/alpha.c` |
| **transplant without deleting** | **1** | **5** | **`<ref>/src/alpha.c`** |
| delete, then transplant | **0** | 4 | -- |

The middle row is the failure this procedure exists to prevent: **a defect the
developer already fixed, resurrected from a stale translation unit**, reported
against a path in a tree they are not working in. Nothing errors. The count
looks plausible. It is simply wrong, in the direction that wastes the most
time.

If you ever do end up with two TUs for one primary source file at the *same*
path, `--one-tu-per-psf` picks one by an algorithm the documentation warns
"might make different choices and the results might vary, even though the code
appears to be unchanged" -- so prefer superseding (re-capture) or deleting over
leaving duplicates around.

`--tus-per-psf=non-latest delete` prunes superseded TUs. It does **not** clean
up after a transplant across differing paths -- those are not superseded, they
are duplicates, and nothing but an explicit delete removes them.

**How to tell which case you are in:** compare the reference idir's recorded
primary paths against your working tree's root. If they share a root, you are
in the same-path case and can capture straight into the copy. If they do not,
you are transplanting, and every refreshed file needs its stale TU deleted by
repo-relative path first.

## Verifying the result

The technique is only trustworthy because it can be checked. Build the same
working tree with a **full clean capture** and compare -- once, when
calibrating on a new project or build system, not on every iteration.

Measured on the proftpd fast path, reference idir vs surgically updated vs
full recapture of the working tree:

```
105 distinct defect sites, 155 records
in oracle only  : 0
in surgical only: 0
IDENTICAL after path normalisation
```

including the planted canary defect. On the CMake project's build-recording
path, the transplanted idir matched the oracle exactly (4 files analyzed, same
single OVERRUN, same file).

**Normalise paths before comparing.** Unchanged TUs keep the *reference*
location's absolute paths, so a naive diff reports every pre-existing finding
as different. This is also a real usability wart: defect reports for
untouched files point into a tree the developer is not editing.

**Use a canary.** Plant a defect in a changed file and confirm it appears. A
canary in code the build does not compile proves nothing while looking like
success -- one calibration run here planted a defect inside `#undef
PR_USE_LASTLOG` and every arm agreed, on a probe that was never analyzed.
Confirm the target is live before trusting it.

## Iterating

The steady state: the idir is associated with a git identity, and each update
diffs the working tree against it and re-applies the procedure.

Keep the association with the **original reference tag** and re-derive the
full delta from it each time, rather than tracking increments. It is
idempotent and self-correcting -- a file changed and then reverted simply
stops appearing in the diff. Tracking only what you applied last time leaves
reverted files stale in the idir, which is the same stale-TU failure by
another route.

The re-emit set therefore grows over a working session. That is fine; it is
bounded by the size of the branch, and it is still far smaller than a full
capture.

## Relationship to Coverity's own incremental analysis

`cov-analyze` is incremental **by default**; `--force` disables it and forces
full re-analysis. So a reused idir carries analysis state as well as emit
state, and re-analysis makes its own judgement about what changed.

Measured: after a fast-path swap on an idir that already carried a completed
analysis, both the default and `--force` produced the same result and picked
up the change (the delete-and-re-emit gives the TU a new identity, which is
the likely reason). One data point on one version -- if a surgical result ever
looks stale, `--force` is the first thing to try, and the discrepancy is worth
reporting.
