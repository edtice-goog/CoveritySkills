# Choosing the versions and the story

This is Phase 2: pure set algebra over merge keys, no Coverity Connect
involvement, freely re-runnable. It is where story builders should spend their
time, and where mechanics should stay out of their way.

## The population table

`tools/phase2.py` produces the shape of the dataset before anything is
committed:

```
version       total    new  persist  fixed
v1.3.8          113    113        -      -
v1.3.8a         112      0      112      1
v1.3.9          112      1      111      1
```

Because it keys on merge key -- the same identity Connect uses to assign CIDs
-- these numbers are what Connect will show, not an approximation. Verified
exactly against a live instance.

## Story shapes and what they need

| Story | What the version set must contain |
|---|---|
| **Aging / SLA pressure** | Defects present in the earliest version and still present at the tip, with a long real-time gap between them |
| **Fix rate / trend** | Versions where `fixed` is consistently non-zero; a visible slope matters more than magnitude |
| **Regression caught** | A defect that is fixed in version N and reappears at N+k -- rare but powerful; search for it explicitly |
| **New at the gate** | A defect first appearing in the newest version, ideally a checker the audience cares about |
| **Density improving** | Total trending down while LoC holds or grows |

Most corpora will not offer all of these. Pick the story the data actually
supports rather than forcing the data to a predetermined narrative -- a demo
dataset that has to be explained away is worse than a smaller honest one.

## The legibility rule

**A defect featured in a demo must be understandable in seconds.**

This is independent of whether it is a true positive. A real defect whose
argument runs "the loop exits when the tail pointer is null, so the handler
pointer may still be null, unless the terminal element always carries a valid
handler, which it probably does" is a *correct* finding and a *bad* demo item.
The audience is evaluating the tool through the defect; a defect that takes
minutes of code reading makes the tool look equivocal.

Filter story-surfaced defects on:

- **Short trace.** A handful of events beats a twenty-event interprocedural path
- **Self-evident harm.** A dereference of a known-null pointer reads instantly;
  a statistical `checked N out of M times` argument does not
- **Familiar code shape.** The audience should recognize the pattern without
  learning the project's abstractions first
- **No invariant argument required.** If accepting the defect requires
  reasoning about a global invariant the audience cannot see, drop it

A defect that fails legibility can still live in the dataset -- it just should
not be the one on screen.

## Branches become streams, not rows in one stream

Where a project maintains several release lines at once, do not flatten them.
Each line gets its own stream (rule 29), every release is committed, and the
commit order is globally chronological across all streams because first
detected is global per merge key.

This is usually the better demo as well as the more correct one: cross-stream
comparison ("what did 1.3.8 fix that 1.3.7 still carries?") is a more
interesting question than any single timeline supports.

Watch for the tell that a project has concurrent lines: two releases tagged on
the same day. proftpd tags `v1.3.6e` and `v1.3.7` on 2020-07-20, and `v1.3.7f`
and `v1.3.8` on 2022-12-04 -- backports shipping alongside new releases.

## Selecting version count

More versions is not better. Each one costs a build and adds a row the audience
must read. Enough versions to make the trend visible, spread across enough real
time for the dates to carry weight, is the target. A decade of history in six
snapshots reads better than two years in twenty.

Prefer a project's actual release chain over arbitrary commits: releases have
real dates the audience can sanity-check, and real user-visible version
numbers.

## Before leaving Phase 2

Confirm all of:

- Merge-key overlap between adjacent versions is high (the tool aborts at zero)
- Compilation-unit counts are stable except where real code change explains it
- The chosen story is visible in the population table
- Story-surfaced defects are identified by merge key, ready for the Phase 4
  audit
