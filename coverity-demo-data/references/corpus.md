# Preparing a version corpus

## What makes a good corpus

- **Real release history with real dates.** The dates are the demo. A project
  whose tags span a decade gives the aging story for free
- **Builds without heroics across the whole span.** Old releases must still
  compile on a current toolchain, or the corpus is silently truncated to the
  recent end
- **A committed `configure` (or equivalent).** If the build system must be
  regenerated per version, autoconf/automake version skew across a ten-year
  span becomes its own project. Check with
  `git ls-tree <oldest-tag> --name-only | grep configure`
- **Enough defects to be interesting, few enough to comprehend.** A hundred or
  so CIDs reads well; ten thousand is a different demo
- **Recognizable to the audience.** A known open-source project carries
  credibility that a synthetic corpus cannot

## Preparing the build tree

Clone once into a **dedicated** tree at a **fixed path**, separate from any
working checkout:

```
git clone <source> ~/demo/<project>
```

Every version is then checked out *in place*:

```
git checkout -qf <tag>
git clean -xdfq
```

`git clean -xdfq` between versions is not optional -- stale generated files
from the previous version will otherwise be captured, and the deltas will
include artifacts of your own process.

**Never use per-version directories.** Worktrees, versioned unpack dirs, and
`/tmp/build-$TAG` all break merge-key continuity. See SKILL.md Step 1.

## Cross-platform capture

When the project builds on one OS and Connect is reachable from another,
capture and analysis can be split -- intermediate directories are
platform-independent, which is how Coverity SaaS operates.

Requirements:

- `cov-build` and `cov-analyze` must be the **same Coverity version**. Confirm
  a matching pair exists for both platforms *before* starting the corpus; not
  every version is shipped for every platform. Compare the internal build
  string from `--help` on both sides to be certain
- The idir must be written somewhere both sides can read (e.g. `/mnt/c/...`
  under WSL)
- Build performance is better on the native filesystem; if capture over a
  shared mount is slow, build to a local idir and copy it afterwards

## Selecting the tag list

List tags with their real dates:

```
git for-each-ref --sort=creatordate \
    --format='%(refname:short) %(creatordate:short)' refs/tags
```

Watch for interleaved release lines -- many projects tag a maintenance release
and a release candidate on the same day from different branches. Committing
both into one stream produces a confusing history. Pick a single coherent
chain, usually the stable release line.

## Capture hygiene per version

`tools/capture.sh` implements the rules; the essentials are:

1. Fixed path, in-place checkout, clean tree
2. One template `cov-configure`, created once and reused across versions
   (rule 1 -- always `--template`; see `coverity-compiler-configuration`)
3. **Serial** build
4. Explicit failure detection, because `cov-build` exits 0 on a failed build
5. Record the compilation-unit count for cross-version comparison

A version whose CU count differs sharply from its neighbours needs explanation
before it enters the dataset. Usually it is a build failure or a race, not a
finding.
