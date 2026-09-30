---
name: coverity-cvss-report
description: >
  Generate a Coverity CVSS report and tell the reader which of its scores
  were actually judged. Use this skill for "generate a CVSS report", "score
  our Coverity findings with CVSS", "set up cov-generate-cvss-report",
  "create the CVSS triage attributes", "why does this CWE have no CVSS
  score", "why is this issue scored 0", "why is CVSS_Severity None", "our
  DISA-STIG report shows no CVSS score", and "can I trust these CVSS
  numbers". Coverity finds weaknesses, not vulnerabilities; the report
  prices every weakness by its CWE, and when it has no mapping for a CWE it
  writes a zero that looks exactly like a deliberate one. This skill runs
  the calculation phase first, sorts every defect into (a) a zero mapping
  somebody chose, (b) a non-zero mapping, or (c) NO mapping -- a zero by
  accident -- records that in the CVSS_Audited attribute so it is visible in
  Connect, and only then produces the PDF. Needs Coverity Connect, the
  Coverity Reports package, and four custom triage attributes that must
  exist before the first run. Note that --scores WRITES triage attributes
  onto every matching defect in the project.
---

# Coverity CVSS report

Coverity reports **weaknesses**. CVSS scores **vulnerabilities**. The
report generator bridges the two by pricing each weakness from its CWE —
reasonable when a compliance package needs a number in the column, and the
customer's call to make.

The problem this skill solves is narrower and entirely mechanical. **When
the generator has no mapping for a CWE it still writes a vector**, a zero
one, and the PDF shows it exactly like a zero somebody chose. So a reader
cannot tell "we assessed this and it is not a vulnerability" from "this
build of the report generator had never heard of this CWE". This skill
makes that difference visible before anyone signs the report.

Read `coverity/RULES.md` first (rules 3 and 26 carry the weight here).

## The three cases

Every defect in the report is one of these, decided by its CWE:

| | Meaning | What to tell the reader |
|---|---|---|
| **(b) non-zero mapping** | A mapping judged this CWE and gave it impact. | The score is the vendor's judgement. Use it. |
| **(a) zero mapping** | The CWE has its own entry with no impact — a quality weakness. | Assessed, and assessed as not a vulnerability. This is the usual answer when a customer asks why CWE-561, 563, 570, 398 or 704 scored zero. |
| **(c) no mapping** | Nothing judged this CWE. The zero is an artifact of this build. | Not assessed. Say so, or fill it in deliberately (step 4). |

A defect Connect gave **no CWE at all** — parse warnings, some checkers —
is a fourth, smaller case: no lookup runs and the hardcoded zero vector is
written. That is the blank-CWE row with a populated vector beside it.

## Where the CWE must come from, and why it matters

**Get the CWE from Coverity Connect over REST.** Not from a local checker
list, not from `cov-analyze --list-checkers`, not from the report
generator's own taxonomy.

Three versions are in play and none of them has to agree with the others:
the Connect instance, the Coverity Analysis that produced the snapshot, and
the Coverity Reports package doing the mapping. A checker inventory on the
machine you happen to be standing on describes none of them reliably. The
CWE that will be looked up is the one Connect holds for that defect, so
that is the one to ask about — `tools/cvss_issue_export.py`, or
`cvss_run.py`, which does it for you.

The same reasoning applies to the mapping: classify against **the Reports
install you are actually running**, and record its version with the result.
A later Coverity Reports release may map CWEs that this one does not, which
turns case (c) into (a) or (b) with no change on your side. Re-running the
classification against the new build is how you find out.

## Step 0: the four attributes

They must exist in Connect before the first run, spelled exactly:
`CVSS_Audited`, `CVSS_Score`, `CVSS_Severity`, `CVSS_Vector`.

```bash
python3 tools/cvss_attributes.py setup
```

Idempotent, so it is safe against an instance that already has some. It
uses `createAttribute` on the v9 SOAP configuration service, because
nothing else can: `cov-manage-im` sets attribute *values* on defects, not
definitions, and REST exposes only the built-in checker attributes. The
accepted `attributeType` spellings are `STRING` and `LIST_OF_VALUES`.

Credentials come from `COV_USER` and `COVERITY_PASSPHRASE_FILE` throughout.
Never put a password on a command line (rule 3).

## Step 1: the configuration file

```bash
python3 tools/cvss_run.py config --project <p> --snapshot <id> \
    --company-name "..." --org-unit "..." --org-term Division \
    --prepared-by "..." --prepared-for "..." --email you@yourdomain.com \
    --out cvss_config.yaml
```

Every field it asks for is mandatory *to the generator*, which refuses the
file rather than defaulting. Two traps it checks for you:

- **`project-contact-email` is validated with commons-validator**, which
  checks the top-level domain. `nobody@example.invalid` is rejected and the
  error only says "was not a valid email". `example.com` validates.
- **`snapshot-id` is what makes the run reproducible.** Without it the
  report follows each stream's latest snapshot, so the same command gives a
  different report next week. The tool warns if you leave it out.

## Step 2: the calculation phase

The generator runs in two phases and they are separate invocations. Do the
calculation alone first, so that if it writes something unexpected you have
not also produced a report asserting it.

```bash
python3 tools/cvss_run.py scores --project <p> --config cvss_config.yaml \
    --issues-json issues.json
```

This is `cov-generate-cvss-report --scores`. It **writes** `CVSS_Vector`,
`CVSS_Score` and `CVSS_Severity` onto every defect in the project whose
`CVSS_Audited` is not `Yes`. There is no dry run. Keep its stdout: it names
each defect it could not score and says which of the two reasons applied.

## Step 3: mark what was actually judged

```bash
python3 tools/cvss_run.py mark --project <p> --snapshot <id> \
    --graph cwe_childof.json --csv unjudged.csv
```

For each defect it takes the CWE from Connect, runs the generator's own
documented lookup against the installed mapping, and sets **`CVSS_Audited`
= `Yes`** for cases (a) and (b) — a mapping judged that CWE. Case (c) is
**left `No`**.

That is the whole point: afterwards, a reader in Connect can sort on
`CVSS_Audited` and see immediately which scores were assessed and which
were not. It prints the (a)/(b)/(c) split with issue counts, and `--csv`
lists every case (c) defect with its CWE and checker.

**Two consequences to understand before running it.**

`CVSS_Audited = Yes` stops the generator updating that defect's vector on
every later run. For an inferred vector that is exactly what you want. For
a vendor-mapped one it means the defect will **not** pick up an improved
mapping from a future Reports release. If that matters more than the
at-a-glance view, `--audited inferred-only` marks nothing here and leaves
every vendor mapping live; `reset` undoes either.

The `Yes` is also a claim. It says a mapping judged this CWE — not that a
human reviewed this defect. Say which you mean when you hand the report
over.

## Step 4: the choice, which is the user's

If step 3 left nothing `No`, go to step 5.

If it did, the person who owns the report decides between:

**(a) Run the report as it stands.** The zeros stay. You have
`unjudged.csv` to say exactly which findings nobody assessed and why. This
is the honest default and usually the right one — particularly if a newer
Reports release is coming, since it will map some of them for you.

**(b) Infer vectors for them.**

```bash
python3 tools/cvss_run.py infer --project <p> --snapshot <id> \
    --graph cwe_childof.json --csv inferred.csv        # review first
python3 tools/cvss_run.py infer ... --apply            # then write
```

The rule is deliberately narrow and stays inside Coverity's own frame of
reference: **score an unjudged defect like the judged defects Coverity
files under the same category in this same snapshot**, ties going to the
lower score. Where the snapshot gives no basis, it declines rather than
inventing a number. Nothing is written without `--apply`, and what it
writes is marked `CVSS_Audited = Yes` so the next `--scores` run does not
revert it.

This is inference and the skill says so everywhere. Keep `inferred.csv`
with the report; it is the only record of which numbers are guesses.

## Step 5: the report

```bash
python3 tools/cvss_run.py report --project <p> --config cvss_config.yaml \
    --output cvss.pdf
```

## What to hand over with the PDF

The PDF alone does not carry the distinction — its per-issue block prints
severity, score, vector and audited flag, and **not the CWE**. So send:

- the PDF,
- `unjudged.csv` (and `inferred.csv` if you inferred),
- the Reports version the mapping came from, and the snapshot id,
- one sentence on what `CVSS_Audited` means in this report.

`cvss_run.py status` prints all of that for a project at any time.

## Answering "why did this CWE get no score"

Run step 3 and read the case off it.

- **(a)** — it was assessed and given no impact. CWE-561, 563, 570, 398 and
  704 are all in the shipped mapping with no impact: dead code, an unused
  assignment, an always-false expression, a code-quality finding, a bad
  cast. None is a vulnerability, so zero is correct. A per-project profile
  entry overrides it if the customer disagrees.
- **(c)** — nothing judged it. Worth reporting, with the CWE, the checkers
  producing it, and the Reports version. Check whether a newer Reports
  release maps it before calling it a product defect.
- **no CWE** — the lookup never ran. Nothing to map.

## What this skill does not do

**It does not write a `<security-profile>.json`.** A profile silently
overrides the master mapping on every future run, including for CWEs the
vendor later fixes, and it makes whoever shipped it answerable for every
score in it. That is a security team's decision to make once, deliberately.
Step 4 fills gaps per defect instead, where it is visible and reversible.

**It does not judge whether a weakness is exploitable.** A CVSS score here
is an upper bound derived from a CWE, not a finding about the code. For
whether a specific defect is real and reachable, that is
`coverity-fuzz-triage`, and its answer is evidence rather than a score.

## Reference

`references/cvss-report-mechanics.md` has the lookup as implemented, the
CWE datasets the generator carries and their vintages, the rounding, and
what a real run confirmed. `tools/cvss_profile_audit.py` is the analysis
layer — `graph`, `audit`, `resolve`, `verify`, `score` — for explaining a
particular CWE's fate rather than running the workflow.
