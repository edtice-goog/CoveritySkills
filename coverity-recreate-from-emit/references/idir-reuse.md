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

There is no single threshold worth hard-coding, because the real cost driver
is how far the *header* changes cascade, not the file count. Report the ratio,
and if the delta capture ends up recompiling most of the project anyway, say
so and prefer the fresh capture next time.

**Do not use this for anything anyone will rely on**: no release gates, no
compliance evidence, no "the scan is clean" claim. It is a developer
iteration tool. When the answer matters, capture fresh.

## Two applicability gates, checked before anything else

Both are pass/fail. If either fails, the technique does not apply -- say so
and use a fresh idir. Knowing when it does not apply is half of this skill.

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
