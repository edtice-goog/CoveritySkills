# coverity-cvss-report

Part of [CoveritySkills](../README.md).

Runs the Coverity CVSS report the way the documentation says, and then
audits what it produced. The audit is the part worth having: **every
defect in a CVSS report carries a CVSS vector, including the ones the
generator could not score, and the report does not distinguish them.**

On the shipped configuration, of the 502 CWEs that Coverity checkers can
assign, **209 resolve to a zero score that nobody chose.** That is a
ceiling over the whole checker inventory, though, and the measured picture
is more specific and more useful:

| population | gap |
|---|---|
| four ordinary C/C++ projects (this repo's fixtures, proftpd, Contiki-NG, subversion) | **none** |
| the same fixtures re-analyzed under MISRA C 2012 | **35 of 130 issues**, across 8 CWEs |

So: plain quality-and-security analysis is well covered by the master
profile. The gap bites when the CWEs in play postdate the generator's CWE
data — coding standards (MISRA, AUTOSAR, CERT), software composition
(CWE-1395), and the cloud/IaC checkers. Ask what the customer runs before
telling them they have a problem, and run the audit against the CWEs their
project actually produced rather than quoting the ceiling.

## Why a weakness report needs auditing before it becomes a score

Coverity finds weaknesses. CVSS prices vulnerabilities. The generator
bridges the two by assuming every weakness is exploitable and looking up
impact metrics by CWE — a reasonable thing to want when a compliance
package needs a number in the column, and the customer's call to make.

The part that is not the customer's call is what happens when the lookup
finds nothing. The documented rule is: the CWE's own entry, else the
highest-scoring mapped ancestor, else a zero vector. That last clause is
not an error path anybody sees. It produces a row that looks exactly like
a deliberate zero.

So the useful question is never "what score did this get" but **"which of
three things is this zero?"**

| | |
|---|---|
| **Zero by design** | The CWE is in the mapping with `C:N/I:N/A:N`. Someone decided a quality finding is not a vulnerability. Correct, and usually the answer. |
| **Zero by default** | No entry, no mapped ancestor. The lookup ran out. |
| **No CWE at all** | Parse warnings and some checkers carry none, so the lookup never runs. |

`tools/cvss_profile_audit.py` sorts every CWE into those buckets offline —
no Connect instance, no project, no defects, just the installed generator.
Most customer questions about a missing CVSS score are answered in the
first minute of using it.

## What the audit turned up

Reading the installed generator (Reports 2025.3.0) and disassembling the
classes that do the work:

- **The ancestor walk runs on a 2017 snapshot of CWE.** The graph has 1040
  nodes and its highest weakness id is 1039; the XML schema package is
  literally named `cwe2017`. **49 of the CWEs Coverity checkers map to
  have no node in it at all**, so they cannot inherit from anything.
  Among them is `CWE-1395 Dependency on Vulnerable Third-Party
  Component` — 2302 checkers. A known-vulnerable-dependency finding
  scores 0.0 in the report whose subject is vulnerabilities.
- **`findAncestors` follows `ChildOf` edges only**, which the
  documentation does not say. Category membership is not ancestry here, so
  the real gap is larger than a naive reading of the docs predicts (209
  rather than 190).
- **The zero vector is a hardcoded string**, not built from the profile's
  own `AV`/`AC`/`PR`/`UI`. A custom profile setting `AV:L` still emits
  `AV:N` on every unmapped row.
- **`CVSS_Score` is not a conforming CVSS score.** The generator computes
  `Math.round(score * 100) / 100.0f`; CVSS v3.0 and v3.1 both specify
  rounding *up* to one decimal. The mapped CWE-190 entry reports **4.91**
  where a conforming calculator says **5.0**. With the master profile's
  fixed exploitability metrics only 12 scores are reachable and none of
  them crosses a severity boundary, so this is a conformance defect rather
  than a severity one — but a custom profile can reach scores where it is
  both.
- **The mapping is not monotone down the hierarchy.** CWE-125
  (out-of-bounds read) has its own entry worth 4.25 while its children 126
  and 127 have none and inherit 7.39 from CWE-119 — the more specific
  finding scores higher than the general one.
- **One thing that looked worse than it is.** The taxonomy lists several
  CWEs per issue type — `overrun:write` under CWE-119, 121, 122, 123, 124
  *and* 193, whose scores range from 7.39 to 0.00 — which reads like the
  same checker might score anything. Across 149 observed issues it did
  not: each issue type carried one stable CWE, and where a checker spans
  CWEs the subcategory decides it (`OVERRUN` write → 119, read → 125). The
  many-to-many listing is a weaker signal than it appears, and it is
  recorded that way rather than kept as the scarier version.

Every prediction above was checked against a real run: 19 defects in one
snapshot and 130 in another, CWE, vector, score and severity each time.
The audit was exact on all of them.

`references/cvss-report-mechanics.md` has the evidence for each.

## The usual customer question

*"Certain CWEs don't get a CVSS score."* Usually those are CWE-561, 563,
570, 398 and 704 — dead code, unused assignment, always-false expression,
code quality, bad cast — showing `None` and `0` in a DISA-STIG severity
report.

They are all in the master profile, mapped to `C:N/I:N/A:N` on purpose.
The score is not missing; it is zero because a quality finding is not a
vulnerability. That is the answer, it is a good one, and a profile entry
overrides it per project if the customer disagrees. The zeros worth
escalating are the other kind, and the audit tells you which is which.

## What it deliberately does not do

It does not generate a `<security-profile>.json`. The audit says which
CWEs are unscored; deciding what they are worth is a security team's
judgement, and a profile is a durable artifact that silently overrides the
master on every future run — including for mappings the vendor later
fixes. A generated one would be a guess wearing the costume of a policy.

## Layout

| Path | What it is |
|---|---|
| `SKILL.md` | the procedure: audit, stand up, run, re-audit, answer |
| `references/cvss-report-mechanics.md` | how the score is really computed, with provenance |
| `tools/cvss_profile_audit.py` | `graph`, `audit`, `resolve`, `verify`, `score` |
| `tools/CweGraphDump.java` | dumps the generator's real `ChildOf` graph |
| `tools/cvss_attributes.py` | creates the four triage attributes Connect needs first |
| `tools/cvss_issue_export.py` | exports a project's CWEs, which the generator's own dump omits |
| `evals/fixtures/*.c` | sample defects: scored, zero-by-design, and the gap cases |
| `CALIBRATION.md` | what was run, on what, and what is reasoned rather than measured |
