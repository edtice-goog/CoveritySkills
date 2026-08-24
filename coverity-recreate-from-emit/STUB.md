# coverity-recreate-from-emit — starting document

**Status: stub.** Nothing here is validated. Written to hand off to a fresh
session, alongside `coverity-issue-transition-inference/STUB.md`.

## Why this exists

`coverity-build-fidelity` assumes you can run the build. Often you cannot:
the toolchain is gone, dependencies have vanished, the CI job was retired,
or the old commit simply does not build any more.

When the build is unavailable, the **intermediate directory is the surviving
record of it**. This skill's job is to get from an old idir back to something
analyzable by a different (usually newer) analyzer — without reconstructing
the original build environment.

Its consumer is `coverity-issue-transition-inference`, which needs to analyze
old code with a new analyzer to separate "the code changed" from "the
analyzer got better". That skill uses `coverity-build-fidelity` when the
build is repeatable and this skill when it is not.

## The mechanism to investigate first

```bash
cov-manage-emit --dir <idir> list-capture-invocations
```

The existence of a `--no-process-details` flag implies process details are
included by default. If those details carry the real compiler command lines,
the original compilations can be replayed.

`cov-manage-emit --dir <idir> list-json` additionally gives per-TU
`primaryFilename` and `primaryFileHash` (MD5) — the latter is the only cheap
way to **prove** you have the exact source revision the idir was built from.
That check should gate everything downstream.

## Questions that decide whether this is viable

Answer these before designing anything. They are ordered so that a "no" early
saves the rest.

1. **What exactly is in a capture invocation?** Full argv? cwd? environment?
   Or a normalized/redacted form?
2. **Are the original sources required, or does the emit carry enough?**
   Coverity's emit stores derived data, not necessarily reconstructable
   source. If sources are required, this skill becomes "replay the recorded
   commands against a git checkout", and the `primaryFileHash` check becomes
   mandatory rather than advisory.
3. **Can a newer analyzer consume an older emit directly?** If `cov-analyze`
   from version N works against an idir emitted by version N-k, much of this
   skill collapses to a compatibility matrix — a far better outcome. Find the
   supported range of k.
4. **Does replay reproduce the same TU set?** The output must be verifiable,
   which means reconciling replayed TUs against the original emit inventory.
   `coverity`'s capture-fidelity methods apply directly, with the *original
   idir* serving as Method C's expectation.
5. **What breaks replay?** Generated headers no longer present, absolute paths
   that no longer exist, compiler wrappers, `-include` of build-time files.

## Interface this must provide

`coverity-issue-transition-inference` needs, from an old idir:

- an intermediate directory analyzable by the **new** analyzer version
- proof it corresponds to the same code as the original — ideally per-TU
  `primaryFileHash` equality
- a reconciliation of replayed TUs against the original inventory, with any
  shortfall named
- an honest grade when replay is partial, since a partial replay silently
  shrinks the analyzed set and would masquerade as "defects fixed"

That last point is the trap worth designing against from the start: **an
incomplete replay looks exactly like an improvement.** Findings disappear,
counts drop, and nothing errors. Same shape as the vacuous-capture problem in
`coverity`, and it needs the same treatment — verify the denominator, never
report a delta without it.

## Security note

Capture invocations and `build-log.txt` embed full environments including
`PATH`, and potentially secrets passed on command lines. `coverity`'s
`references/idir-anatomy.md` already flags this. Anything this skill extracts
or forwards inherits that exposure — check before sending an idir or a
replay script anywhere.

## Related

- `coverity` — capture fidelity, idir anatomy, standing rules. Read
  `RULES.md` first.
- `coverity-build-fidelity` — the preferred path when the build still runs
- `coverity-issue-transition-inference` — the consumer
