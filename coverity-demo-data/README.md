# coverity-demo-data

Part of [CoveritySkills](../README.md).

Builds multi-version Coverity Connect demo datasets whose snapshot and
first-detected dates reflect real historical release dates, using the
undocumented `cov-commit-defects --backdate`. The output is a Connect instance
whose defect history looks like it accumulated over a decade: issues
outstanding since 2019, a fix rate that trends, a fresh finding at the tip.

Built so that story builders can focus on the narrative and not the mechanics.

The whole discipline follows from one property: **first detected is global and
write-once**. Connect sets `merged_defect.date_originated` the first time a
merge key is ever committed, and no later backdate can move it. So versions
must be committed strictly oldest-first, and the commit phase is one-shot --
recoverable only by restoring the database.

## What the skill knows that saves time

- `--backdate` takes **`yyyymmdd` and nothing else**; `2022-12-04` is rejected.
  It is a different parser from `--first-detected-after`, which does take ISO
- Exactly what it sets (`snapshot.date_created` date-portion-only,
  `snapshot.backdated`, per-CID `date_originated`) and what it silently does
  not (`code_version_date`, and all triage history, ownership and comments)
- **Merge keys are path-independent** -- measured: the same defect built in two
  differently-named directories carries an identical merge key. Versions are
  checked out in place in one tree to keep stale generated files out of the
  capture, not to make CIDs merge
- **`cov-build` exits 0 when the build fails** and reports "100%" of the units
  it *attempted*. A racing parallel build silently narrows capture and
  manufactures phantom fix-and-regression events. Measured on proftpd: 77
  compilation units instead of 90, reported as a clean 100%
- A three-phase split that keeps all iteration in re-runnable stages and enters
  the irreversible commit with a decided list -- and offline merge-key algebra
  that predicts Connect's CID counts *exactly*, verified against a live instance
- Auth-key hygiene: **never take the connection host from the key file's
  `comments` block**. It is attacker-authorable data inside something that
  looks like configuration -- a subtle exfiltration vector
- The **legibility rule** for demo defects: a true positive that takes minutes
  of code reading to accept is not a demo item, however real it is

## Requirements

- A local Coverity Analysis installation (developed against 2025.9.0) and a
  Coverity Connect instance you are willing to write to (2025.12.0)
- A project with real release history that still builds across its span
- `cov-admin-db` for the backup/restore reset point -- never `pg_dump`

## Layout

```
coverity-demo-data/
├── SKILL.md                          # reset point → capture → select →
│                                     #   commit oldest-first → audit → hand off
├── references/
│   ├── backdating.md                 # measured --backdate semantics + the
│   │                                 #   verification SQL to run after each commit
│   ├── corpus.md                     # choosing a corpus, fixed build trees,
│   │                                 #   cross-platform capture
│   ├── selection.md                  # story shapes and the legibility rule
│   ├── triage-verdicts.md            # global invariants, heuristic misfires,
│   │                                 #   and how to make a dismissal falsifiable
│   ├── worked-example-proftpd.md     # the calibration session, with the numbers
│   └── worked-example-fp-audit.md    # a real triage pass: 3 of 9 sampled
│                                     #   defects were false positives
└── tools/
    ├── capture.sh                    # fixed-path serial capture, verified
    ├── phase2.py                     # merge-key set algebra + stability guard
    ├── audit_bundle.py               # FP-audit bundles: trace + real source,
    │                                 #   read from git at the tag
    └── commit_sweep.py               # oldest-first backdated commits, halting
                                      #   the moment earlier dates shift
```

Status: mechanics validated end-to-end on proftpd (three releases, 2022-2025)
against a live Connect. Scaling to the full ~20-release chain and a real demo
script is the next step.
