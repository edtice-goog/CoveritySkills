# coverity-cvss-report

Part of [CoveritySkills](../README.md).

Generates a Coverity CVSS report and tells the reader **which of its scores
were actually judged.**

The generator prices each weakness from its CWE. When it has no mapping for
a CWE it still writes a vector — a zero one — and the PDF shows that
exactly like a zero somebody chose. "We assessed this and it is not a
vulnerability" and "this build had never heard of this CWE" look identical
on the page. This skill separates them, records the answer where a reader
will see it, and only then produces the report.

## The three cases

Decided per defect, from the CWE **Coverity Connect** holds for it, against
**the Coverity Reports install you are running**:

| | Meaning | Verdict |
|---|---|---|
| **(b) non-zero mapping** | a mapping judged this CWE and gave it impact | the score is the vendor's judgement |
| **(a) zero mapping** | the CWE has its own entry, no impact | assessed, and assessed as not a vulnerability |
| **(c) no mapping** | nothing judged this CWE | not assessed; the zero is an artifact of this build |

Case (a) is the answer to the question customers actually ask. CWE-561,
563, 570, 398 and 704 — dead code, unused assignment, always-false
expression, code quality, bad cast — are all in the shipped mapping with
`C:N/I:N/A:N`. The score is not missing; it is zero on purpose, because a
quality finding is not a vulnerability.

Case (c) is the one worth reporting, and the skill writes it into the
`CVSS_Audited` triage attribute so it is visible in Connect next to the
score rather than buried in a tool's output.

## Why the CWE has to come from Connect

Three versions are in play and none of them has to agree: the Connect
instance, the Coverity Analysis that produced the snapshot, and the Coverity
Reports package doing the mapping. So **no checker inventory on the local
machine describes what a given snapshot carries** — `cov-analyze
--list-checkers` answers a question about the analyzer in front of you, not
about the defects in the database.

The population is therefore always "the CWEs this snapshot actually has",
fetched over REST, and the mapping verdict is always attributed to a named
Reports version. A later Reports release can turn case (c) into (a) or (b)
with no change on your side; re-running the classification is how you find
out, which is why this is a tool and not a table.

## The workflow

| | |
|---|---|
| 0 | `cvss_attributes.py setup` — the four `CVSS_*` attributes Connect needs first |
| 1 | `cvss_run.py config` — write and validate `config.yaml` |
| 2 | `cvss_run.py scores` — the calculation phase, alone |
| 3 | `cvss_run.py mark` — the (a)/(b)/(c) split, written to `CVSS_Audited` |
| 4 | `cvss_run.py infer` — optional, for what step 3 left unjudged |
| 5 | `cvss_run.py report` — the PDF |

`SKILL.md` has the detail, including the two consequences of marking
`CVSS_Audited = Yes` and how to undo it.

## What a real run established

Two snapshots of the same C fixtures against Connect 2025.12.0 with Reports
2025.3.0, plus three unrelated projects on the same instance — every
population read from Connect over REST:

- **The offline classification was exact.** Every CWE, vector, score and
  severity matched on all 19 defects of one snapshot and all 22 CWEs of
  another.
- **Ordinary C/C++ analysis had no case (c) at all** — these fixtures,
  proftpd, Contiki-NG and subversion, 12 to 13 CWEs each.
- **The same fixtures under MISRA C 2012 did**: 114 of 130 issues scored
  0.0, of which 79 were case (a) and **35 were case (c)**, over 8 CWEs
  (1177, 691, 664, 1164, 1076, 682, 696, 908). The generator says so itself
  in its stdout: *"Assigning a CVSS vector whose CVSS score is zero, as
  corresponding cwe: 'Optional[1164]' isn't available in either profile or
  master cwe - cvss mappings json file"*.
- **`CVSS_Score` is not a conforming CVSS score.** The generator computes
  `Math.round(s*100)/100f`; CVSS v3.0 and v3.1 both specify rounding *up*
  to one decimal. CWE-190 is reported as **4.91** where a conforming
  calculator says **5.0**. With the shipped mapping only 12 scores are
  reachable and none crosses a severity boundary, so this is a conformance
  defect rather than a severity one; a custom profile can make it both.
- **The ancestor walk runs on a 2017 snapshot of CWE** — 1040 nodes, top
  weakness id 1039 — and follows `ChildOf` edges only, which the
  documentation does not say. That is the mechanism behind most case (c).
- **The PDF does not print the CWE**, so the distinction cannot be
  recovered from the report itself. It lives in the generator's stdout and
  in the triage attributes.

`CALIBRATION.md` records what was measured, what is derived, and which
earlier claims were withdrawn.

## What it deliberately does not do

It does not write a `<security-profile>.json`. A profile silently overrides
the master mapping on every future run, including for CWEs the vendor later
fixes, and makes whoever shipped it answerable for every score in it. Step 4
fills gaps per defect instead, where they are visible and reversible.

## Layout

| Path | What it is |
|---|---|
| `SKILL.md` | the workflow, step by step |
| `tools/cvss_run.py` | `config`, `scores`, `mark`, `infer`, `report`, `status`, `reset` |
| `tools/cvss_attributes.py` | creates the four triage attributes Connect needs first |
| `tools/cvss_issue_export.py` | exports a project's CWEs, which the generator's own dump omits |
| `tools/cvss_profile_audit.py` | analysis layer: `graph`, `audit`, `resolve`, `verify`, `score` |
| `tools/CweGraphDump.java` | dumps the generator's real `ChildOf` graph |
| `references/cvss-report-mechanics.md` | how the score is really computed, with provenance |
| `evals/fixtures/*.c` | sample defects spanning all three cases |
| `CALIBRATION.md` | what was run, what is reasoned, what was withdrawn |
