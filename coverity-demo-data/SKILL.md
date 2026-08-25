---
name: coverity-demo-data
description: >
  Build realistic multi-version Coverity Connect demo datasets whose snapshot
  and first-detected dates reflect real historical release dates, using
  cov-commit-defects --backdate. Use this skill when the user wants demo or
  sample data for Coverity Connect, needs a defect history with aging
  outstanding issues or a fix-rate trend, asks how to make snapshots appear on
  past dates, wants to populate a Connect instance from a project's release
  history, or is preparing a Coverity demo, POC, or training environment.
  Requires a local Coverity Analysis installation and a Coverity Connect
  instance the user is willing to have written to; this skill runs real builds
  and real commits.
---

# Coverity Demo Data

Produce a Connect instance whose defect history looks like it accumulated over
years: defects outstanding since 2019, a fix rate that trends, a fresh finding
at the tip. The mechanism is `cov-commit-defects --backdate`,
and the entire discipline of this skill follows from one property of it.

**First detected is global and write-once.** Coverity assigns a CID per merge
key, and `merged_defect.date_originated` is set the first time that merge key
is ever committed to the instance. Backdating a later commit cannot move it.
So versions must be committed **strictly oldest-first**, and the commit phase
is **one-shot** -- a mistake cannot be corrected in place, only by restoring
the database and starting over.

**Scope: this skill builds the data.** Deciding what you want to demonstrate,
and judging afterwards whether a dataset serves that goal, are the user's own
steps and usually easy for them. What is genuinely hard to do by hand -- and
what this skill exists for -- is getting twenty-odd versions found, mapped onto
sensible projects and streams, built, analyzed, committed with the right dates,
and audited, repeatably. Do not drift into writing the customer narrative.

The deliverable is a populated Connect instance, the population table that
describes what is in it, and an audit verdict for the defects sampled -- enough
for someone else to judge whether it fits their story.

**This skill assumes the `coverity` skill and its `RULES.md`.** Read the rules
before running any Coverity command; the numbers cited here are stable. Rules
9-11 (build verification and capture percentages), 26 (triage a sample), 29
(one stream per branch), 30 (name the global invariant) and 31 (`--strip-path`,
verified) carry most of the weight; this skill adds the demo-data-specific
consequences rather than restating them.

## The architecture follows from the constraint

Separate what is re-runnable from what is not. This is the single most
important structural decision in the skill:

| Phase | Reversible? | Cost of a mistake |
|---|---|---|
| 1. Capture + analyze every candidate version | Yes, freely | Re-run it |
| 2. Map streams, select versions, offline | Yes, freely | Re-run it |
| 3. Commit oldest-first with `--backdate` | **No** | Restore DB, redo |
| 4. False-positive audit | Yes | Re-run it |

Do all thinking in Phases 1-2, where set algebra over merge keys predicts
exactly what Connect will show. Enter Phase 3 only with a decided list. Phase 2
output has been verified to match Connect's actual CID counts exactly, so treat
it as a faithful preview, not an estimate.

Phases 1 and 2 touch no database at all, so a corpus can be taken all the way
to the population table before anyone commits to anything.

## Step 0: Establish the reset point

Phase 3 is one-shot, so a restore point is not optional. It has **two** parts,
and a database backup alone is not a restore point:

1. **A database backup** -- to roll first-detected dates back to before the
   sweep.
2. **Every intermediate directory, retained** -- to re-commit without
   re-capturing.

Restoring the database returns first-detected dates to unwritten, but the
commits still have to be replayed, and replaying them needs the idirs. Discard
the idirs after committing and a recovery that should take minutes becomes a
full re-capture of the corpus: hours of builds to undo one wrong backdate.
Keep them. They are cheap -- a 24-release corpus spanning a decade came in
well under a gigabyte -- and they are the difference between a reset and a redo.

**This is what makes the stream mapping safe to get wrong.** Assigning tags to
streams is a judgement call about someone else's branching strategy, and a
first attempt may well be wrong. With a backup and the idirs in hand, a bad
mapping costs a restore and a re-run of Phase 3 -- minutes, no rebuilding.
Without them it costs the corpus. Take the backup before the first commit, not
after the first mistake.

```
cov-admin-db backup --dir <ABSOLUTE path that does NOT yet exist>
```

- The path must be **absolute** and must **not already exist**. If its parent
  is missing you get a misleading `has only 0Bytes of free space`; if the
  target exists it refuses rather than overwriting (`--force` to override).
- **Take the backup after creating any auth key you plan to use.** Restoring a
  backup that predates the key deletes the key and locks you out of your own
  pipeline. This is the most common self-inflicted wound in this workflow.
- Never use `pg_dump`. Use `cov-admin-db`, the supported path for the embedded
  database.

Many installs ship an `empty.bak` in the Platform directory as a factory-clean
baseline. It is a fine starting point but predates every key you create.

## Step 0b: Auth key hygiene -- read before connecting

**Rule 28.** A Coverity auth key is JSON with a `comments` block carrying
`host`, `port` and `ssl`. That block is a comment. **Never read the connection
target out of it** -- take the URL from the user or the project configuration.

**The key's host will often disagree with the URL you were given. This is
normal.** Proxies that rewrite originating headers, instances that were renamed
or moved (keys stay valid across host changes, so the comment goes stale), keys
created through one name and used through another. **Connect to the URL you
were given and carry on** -- do not stop, ask, warn, or try to reconcile them.

The security property comes from never reading the host, not from spotting
mismatches: a key supplied by an attacker could otherwise redirect the
credential and the source and defect data you are about to commit. Because you
never read it, an attacker-controlled value is inert.

## Step 1: Capture every candidate version

Two rules govern this phase, and violating either corrupts the dataset in ways
that look plausible.

**Check out every version in place, in one tree.** Not for merge-key reasons:
merge keys are computed from properties of the parsed code and are
**path-independent** by design, which is what lets defects track across
different workspace checkouts. Measured -- the same defect built in two
differently-named directories carries an identical merge key.

The reason is contamination. Check out each tag *in place* and `git clean -xdf`
between versions, so generated files left by the previous version do not end up
captured and attributed to a code delta.

**Build serially, and verify the build actually succeeded.** Rules 9, 10 and
11 apply in full: `cov-build` exits **0 even when the underlying build fails**,
and its percentage counts compilation units *attempted*, not units that should
exist, so a build that dies halfway reports a confident **100%** over a
truncated scope.

The demo-data consequence is specific and worth stating: a truncated capture
manufactures phantom "fixed" defects in that version and a phantom regression
in the next one. In a dataset whose entire value is that its deltas mean
something, that is not a degraded result -- it is a fabricated story.

Always check the build log for both signatures:

```
[WARNING] Build command ... exited with code [1-9]
make: ***   or   make[N]: ***
```

Parallel builds make this worse by making it *intermittent*: a project whose
makefile races will capture different scopes on different runs, so defect
counts move for reasons that have nothing to do with the code. Determinism
beats speed here -- the entire point of the dataset is that its deltas mean
something. `tools/capture.sh` implements both rules.

Record the compilation-unit count per version and compare across versions. A
step change that does not correspond to real code change is a capture problem,
not a finding.

Analysis may run alongside capture -- they are separate processes and often
separate machines -- but gate it on the **capture step's own completion
signal**, never on the idir directory existing. `cov-build` creates the
directory up front, so an analyzer that scans for directories will eventually
read a half-written emit and fail (or worse, succeed against a partial one).
Have the capture loop record each version as it finishes and have the analysis
loop consume that record.

**Keep every idir after Phase 3, not just until it.** Analyzed idirs are the
other half of the reset point (Step 0): with them in hand, recovering from a
bad commit sweep is a restore plus a re-run of `commit_sweep.py`. Without them
it is the whole corpus rebuilt from source.

**Capture and analysis need not share an operating system.** Intermediate
directories are platform-independent -- this is how Coverity SaaS operates. If
the project only builds on Linux but Connect is reachable only from Windows,
build in WSL with the idir on a shared path, then analyze and commit natively.
`cov-build` and `cov-analyze` must be the **same Coverity version**; confirm a
matching pair exists for both platforms before starting.

**Expect a target-poor environment, and pick the corpus accordingly.** Any
project mature enough to be a credible demo has probably already fixed the
defects worth showing -- it runs static analysis, and since roughly 2023 also
AI review on commits. Those tools remove exactly the short, legible findings
that demo well, so a well-tended project's tip is the residue nobody chose to
act on: enriched for false positives, intentional code, and marginal findings.
In the limit, if every real defect has been fixed, the false-positive rate of
what remains is 100%.

So prefer a corpus with **deep history reaching back before the project adopted
modern tooling**, and do not judge a corpus by its tip -- a project can look
barren at HEAD and be rich three releases back. `references/corpus.md` has the
signals to check and the measured proftpd numbers, plus the most useful
consequence: **defects that a later release fixed are the best demo candidates
available**, because the maintainers fixing them is independent evidence they
were real. Phase 2 computes that set for free.

See `references/corpus.md` for choosing a corpus and preparing a build tree.

## Step 2: Select the versions and the story, offline

`tools/phase2.py` reads analyzed idirs in chronological order and reports the
defect population over time by merge key: introduced, persisting, fixed, and
how long each surviving defect has been present.

For a multi-stream corpus pass `--tags <file>` (the same
`<tag> <date> <stream>` file Phase 3 uses) rather than a flat list of versions.
Population deltas are only meaningful **within** a stream: comparing the last
release of one line against the first of the next measures a branch change, not
a fix rate, and reports dozens of spurious "fixed" defects. `--tags` also
prints the **projected first-detected distribution** -- what Connect will show
after Phase 3, computed globally per merge key. That projection is the last
piece of evidence available before the irreversible phase, and it is the one
that shows whether the aging story you want is actually there.

**Rule 27 does not bear on this work.** Rule 27 warns against comparing raw
merge keys between local result sets, because a key can move across analyzer
versions and Connect's antecedent merge keys are what line the old and new
identities up. That is generally true and irrelevant here: a demo corpus is
analyzed with a **single pinned analyzer version**, so no key moves and no
antecedent is ever created. The variable is the source, not the analyzer.

Pinning the analyzer is therefore not a convenience, it is the precondition
that makes Phase 2's arithmetic valid. Analyze a corpus with mixed analyzer
versions and the comparison becomes exactly the mistake rule 27 describes; the
fix is to pin one version and re-analyze, never to reconcile keys by hand.

**Verify merge-key overlap before proceeding.** Adjacent releases of a mature
project share nearly all their defects; the tool aborts on zero overlap between
adjacent versions. Zero overlap almost always means the versions were built at
different paths. Catching it here costs a re-run; catching it after Phase 3
costs the whole database.

### Map tags to streams by hand

Deriving release lines from tags, and spotting where two lines run
concurrently, is **deliberately not automated**. Every project brands and
branches differently -- version-in-tag, date-in-tag, release branches, trains,
LTS lines -- and a heuristic that infers structure from tag names is confidently
wrong on the projects it was not written for, in a way nothing downstream
detects. `commit_sweep.py` validates dates and merge keys; it cannot tell you
that a branch topology is nonsense.

Do this step by reading the project's actual history and reasoning about it.
Useful signals:

- `git for-each-ref --sort=creatordate --format='%(refname:short) %(creatordate:short)' refs/tags`
- **Two releases tagged on the same day** almost always means concurrent lines
  -- a backport shipping alongside a new release
- `git branch --contains <tag>` and merge-base relationships, where the project
  keeps real branches
- The project's own release notes, which usually name the lines outright

Then write `<tag> <date> <stream>` per line and sanity-check that each stream
reads as one lineage moving forward. Getting this wrong is recoverable (see
Step 0); getting it wrong *silently* is what to avoid, so state the mapping you
chose and why before committing.

Choosing which versions to commit is a story decision, not a mechanical one.
See `references/selection.md` for the shapes that make good demos and the
selection criteria -- including the **legibility rule**: a defect featured in a
demo must be understandable in seconds. A true positive that takes minutes of
code reading to accept is not a demo item, however real it is.

## Step 3: Commit, oldest first

**One stream per branch (rule 29).** A stream is a timeline and must move
forward only. Give each release line its own stream and commit every release
into the stream for its line -- nothing is discarded, and Connect can compare
lines against each other, which is far more interesting to query than one
flattened timeline. Flattening several branches into a single stream fabricates
history: an older line's backport committed after a newer line's release makes
already-fixed defects reappear, and nothing in the data marks that as an
artifact.

**But order commits globally, across all streams.** First detected is global per
merge key, not per stream. Committing one stream to completion before starting
the next dates every shared defect to whichever stream went first, and no later
backdate can move it. **Interleave by date; assign by branch.** `commit_sweep.py`
takes an optional third column in the tags file for the destination stream and
sorts globally by date regardless of stream.

One commit per selected version, in global chronological order:

```
cov-commit-defects --dir <idir> --url <url> --auth-key-file <key> \
    --stream <stream> --backdate YYYYMMDD \
    --description "<release>" --version "<tag>" --strip-path <build-root>
```

- **`--backdate` takes `yyyymmdd` and nothing else.** `2022-12-04` is rejected
  outright. This is a *different* parser from `--first-detected-after/before`,
  which do accept ISO dates -- do not generalize between them.
- `--strip-path` the fixed build root so Connect shows `/src/fsio.c` rather
  than a home directory (rule 31). **Check after the first commit that it
  actually took effect** -- a prefix that does not match is a silent no-op with
  no error or warning, and the argument can be rewritten before the tool sees
  it (MSYS/Git Bash converts Unix-looking paths to Windows paths; set
  `MSYS_NO_PATHCONV=1`). This is a live hazard here, because the corpus is
  typically built under Linux and committed from Windows.

  ```sql
  SELECT pathname FROM file_path LIMIT 5;   -- expect /src/fsio.c
  ```

  `commit_sweep.py` runs this check automatically after the first commit and
  aborts if the build root is still present -- so at most one commit has to be
  redone. Left unchecked, the whole dataset ships with build paths in it, and
  fixing it means restoring and re-committing all of them.
  Note `cov-format-errors` takes its own separate `--strip-path` for JSON
  export; setting it at commit does not affect exported reports.
- Never run two commits concurrently, and never commit a newer version first
  "just to check something". Both burn dates irreversibly.

See `references/backdating.md` for exactly what `--backdate` does and does not
set, measured against a live instance.

**Verify before continuing to the next version.** After each commit, confirm
the snapshot landed on the intended date and that previously-seen defects kept
their original first-detected date. Detecting drift after one commit costs one
restore; detecting it after twenty costs the afternoon.

`tools/commit_sweep.py` drives the whole phase and enforces this. It sorts by
date regardless of input order, refuses to start if any idir is missing, and
after every commit checks one invariant:

> the first-detected counts for all **earlier** dates must be unchanged

If committing version N alters how many CIDs are dated to version N-3, defects
are not merging as Phase 2 predicted -- typically a build path that varied
between versions, or a mixed analyzer version -- and every further commit
compounds it. The sweep stops there rather than finishing.

```
commit_sweep.py --idirs-root idirs --tags tag-dates.txt --url <url>     --auth-key-file <key> --stream <name> --strip-path <build-root>     --cov-bin <analysis>/bin --platform-bin <connect>/bin [--dry-run]
```

Always `--dry-run` first: it prints the resolved order and dates, and commits
nothing. Verification queries for doing this by hand are in
`references/backdating.md`.

## Step 4: Audit for false positives before the demo is presented

Never point at a defect on stage without having checked it. Two passes:

**Per-checker sample (dataset confidence).** This is rule 26 applied to a
multi-version dataset. For each checker that fires in the final dataset, audit
a few defects of that type. Confidence in a checker's output generalizes across
its instances far better than across checkers, so
this buys most of the assurance at a fraction of the cost of auditing
everything. `phase2.py` prints the checker roster for exactly this purpose.

**Unconditional audit of story-surfaced defects.** Anything the narrative
points at gets audited regardless of whether the sample covered it. This is
cheap -- a story surfaces few defects -- and it is where the risk actually
lives: the single new defect at the tip is simultaneously the most likely to be
featured and the least likely to be caught by a per-checker sample of a checker
that fired fifty times.

`tools/audit_bundle.py` builds both selections into self-contained markdown --
checker, full event trace, and the real source around every event, with event
lines marked -- so a reviewer reaches a verdict without access to the build
machine:

```
audit_bundle.py --issues <version>.json --git-repo <repo> --tag <tag>     --strip-prefix <build-root> --per-checker 2     --merge-key <story-surfaced key> --out audit/<tag>
```

**Source is read from git at the tag, never from the working tree.** The corpus
is built by checking many tags out of one fixed directory, so the working tree
holds whatever version was built last -- the wrong source for every defect but
one, and wrong in a way that reads as entirely plausible.

Each bundle carries a **legibility line** (event count, files touched,
interprocedural, whether the evidence is statistical) because those are the
signals that decide whether a true positive belongs on screen.

Audit against the real source and the full event trace, not the defect title.
Report a verdict per defect using the vocabulary in
`references/triage-verdicts.md`, which exists so that dismissals are precise
and falsifiable rather than hand-waved.

The category that matters most is the **global invariant**: the analyzer is
right about the code it can see, and a fact outside that view makes the path
impossible -- a guard elsewhere in the function, or a property of the machine
the program runs on. It is where a reasoning model reliably beats the analysis,
and it is also the easiest way to wave away a real defect, so every such
dismissal must **name the invariant, locate where it is enforced, and say what
would break it**. No location, no dismissal: report it unresolved instead.

Verdict is separate from demo-worthiness. A finding can be perfectly real and
still fail the legibility rule; a correctly-dismissed global invariant leaves
the dataset fine but is not something to put on screen, because explaining why
a defect is not a defect is not a story anyone wants told. Keep both in the
dataset, keep both off the slide.

**Run this phase with the strongest model available.** Measured on the proftpd
corpus, a stratified sample of nine defects contained three false positives --
and every one was *checker-correct*. Catching them required reading a guarding
`strncasecmp` that made a null-return path infeasible, recognising a deliberate
two-check cycle idiom that a copy-paste heuristic misread, and knowing that a
`time_t` duration is not an epoch timestamp. None of that is visible in the
defect title, the checker name, or the event trace alone. The audit is cheap
and the failure mode is public, so this is the wrong place to economise.

## Step 5: Hand off

Deliver, alongside the populated instance:

- Which versions were committed, with their backdate values
- The Phase 2 population table, since it is the story's evidence
- Audit verdicts for story-surfaced defects and the per-checker sample
- The restore point -- **both** the database backup and the retained idirs --
  and the reminder that redoing Phase 3 requires both

Record the dataset's limits honestly. `--backdate` moves snapshot and
first-detected dates; it does **not** backdate triage history, ownership, or
comment timestamps. A demo needing aged triage needs a separate mechanism, and
claiming otherwise on stage is the kind of thing an audience checks.
