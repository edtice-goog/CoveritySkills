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
4. **Delete the corresponding stale TUs from the copy** (matching by
   repo-relative path, since the absolute paths differ between locations).
5. **Transplant:** `cov-manage-emit --dir <copy> add <delta-idir>`.
   Documented caution: *"Combining intermediate directories can cause defect
   reports to appear or disappear, because the information in one intermediate
   directory can affect the information in another."* That is precisely what
   you are doing deliberately, which is why the oracle check matters.
6. Reconcile and analyze.

## Stale TUs: the rule this procedure exists to enforce

**Delete the stale TU before adding the fresh one. Always.**

Two TUs whose primary source files are at *different absolute paths* are
different primary source files, so `--one-tu-per-psf` will not deduplicate
them. Both get analyzed.

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

The same-path case is subtler but no safer: `--one-tu-per-psf` picks one TU by
an algorithm the documentation explicitly warns "might make different choices
and the results might vary, even though the code appears to be unchanged."
Deleting first removes the ambiguity instead of gambling on it.

`--tus-per-psf=non-latest delete` prunes superseded TUs, but do not rely on it
to clean up after a transplant across differing paths -- those are not
superseded, they are duplicates.

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
