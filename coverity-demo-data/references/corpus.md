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

## Expect a target-poor environment

**A project mature enough to be a credible demo has probably already fixed the
defects you want to show.** Anything with a following runs static analysis, and
since roughly 2023 also runs AI review on commits -- Copilot on GitHub pull
requests at minimum. Those tools are good at exactly the findings that make
good demo material: the short, legible, obviously-real ones. What survives into
the tip of a well-tended project is the residue that a decade of tooling and
human review declined to act on, and that residue is enriched for false
positives, intentional code, and findings too marginal to be worth fixing.

Taken to the limit the point is stark: **if every real defect has been fixed,
the false-positive rate of what remains is 100%.** Not because the analyzer got
worse, but because you are looking at the set of things nobody chose to fix.

proftpd shows the effect cleanly. Tooling arrives, and the population stops
falling:

| release | date | tooling in repo | defects |
|---|---|---|---|
| v1.3.5a | 2015 | `.travis.yml` (CI only) | 176 |
| v1.3.6 | 2017 | `.travis.yml` | 134 |
| v1.3.7 | 2020 | + `.cirrus.yml`, `.codacy.yml` | 113 |
| v1.3.8 | 2022 | + `.clang-tidy`, 2 workflows | 113 |
| v1.3.9 | 2025 | + `.codeql.yml`, 4 workflows | 112 |

The population falls 36% over the decade and then flattens exactly as static
analysis lands. And the survivors are old: **78 of the 112 defects in the 2025
release were first detected in the 2015 release** -- they are, by definition,
the ones a decade of tooling and review left alone. A stratified audit of nine
of them found four false positives. That is the expected result, not a bad run.

### What to do about it

- **Check what the project already runs** before choosing it. Look for
  `.github/workflows/`, `.codeql.yml`, `.codacy.yml`, `.clang-tidy`, a Coverity
  Scan badge in the README, `SECURITY.md`. proftpd itself is a Coverity Scan
  project -- which is precisely why its tip is thin.
- **Prefer a corpus with deep history**, ideally reaching back before the
  project adopted modern tooling. The older releases are where the real defects
  still live, and backdating puts them on the timeline honestly.
- **Mine the fix history as a real-defect oracle.** A defect present in one
  release and gone in the next was, in most cases, *fixed by the maintainers* --
  which is strong independent evidence that it was real. Phase 2 already
  computes exactly this set (the `fixed` column). Those are the best demo
  candidates available, and they cost nothing extra to find.
- **Do not judge a corpus by its tip.** A project can look barren at HEAD and be
  rich three releases back.
