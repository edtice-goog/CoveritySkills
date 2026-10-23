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

Clone once into a **dedicated** tree, separate from any working checkout. A
single fixed path is not required for defect continuity, but it is the cheapest
way to make one `--strip-path` prefix work for every version (see below):

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

**Per-version directories are allowed, but they cost you something.** They do
*not* break defect continuity -- merge keys are path-independent, so CIDs track
across differently-named checkouts (measured: identical merge key sets for one
version built in two directories). What they affect is **`--strip-path`**.

`--strip-path` is per-commit, and each idir records its own build root in
`build-cwd.txt`, so differing build paths are workable: strip each version's own
root. What matters is that the **stripped** paths agree across versions. If they
do not, Coverity Connect **declines to line files up across versions at all**,
and you lose the ability to move forward and backward through a file's history
in the UI.

That is a deliberate product choice rather than a bug. Lining up paths is
ill-posed in general -- a project can hold `foo/my_file.c` and `bar/my_file.c`,
builds can sit at different roots, and files move between directories between
releases. Declining to offer navigation beats offering it inconsistently, and
everything else in the UI keeps working.

For a multi-version demo dataset that navigation is much of the point, so get
the stripped paths consistent. One fixed build tree is simply the cheapest way
to guarantee it: a single `--strip-path` prefix then cleans every version.

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

## Capture only what ships

Coverity analyzes what the build compiles, so **the build defines the scope of
the dataset**. A stock `./configure && make` often builds test programs and
fuzz harnesses alongside the product, and those findings then sit in the
dataset looking exactly like product findings.

Measured on a published OpenSSL dataset built with stock `./config && make`:
**190 of 923 merge keys -- 21% -- had their main event in `test/` (180) or
`fuzz/` (10).** The findings are real; they are simply not in shipped code.

This matters because what reaches triage is a scope decision made *before*
triage. Code in the build counts as shipped, so test code being analyzed is a
process problem, not something for a triager to sort out one defect at a time.
A demo dataset that is one-fifth test harness also misrepresents the product's
defect density, which is often the thing a demo is meant to show.

So configure the build to omit test programs. The mechanism is per-project --
OpenSSL has a `no-tests` configure option, autotools projects often have
`--disable-tests`, and otherwise build the install targets rather than `all`.
Confirm it worked; do not assume the option covered everything.

**Do not filter by path or filename.** It looks easy and it is wrong. alsa-utils
ships `speaker-test/speaker-test.c` as an installed program -- a filename
filter drops a shipped component. Scope comes from **build targets**, which the
project defines, not from patterns that happen to match. For the same reason
this skill reports capture scope and never edits it: `publish_dataset.py`
prints translation units by top-level directory and records them in
`MANIFEST.json` under `capture`, so the shape is visible before publishing and
visible to anyone browsing the archive afterwards. Deciding what belongs is the
builder's call.

If a dataset does include test code deliberately -- to demonstrate exactly this
process problem, for instance -- say so in `--description`. An honest dataset
with a stated scope is useful; an unstated one invites someone to quote its
density as if it were the product's.
