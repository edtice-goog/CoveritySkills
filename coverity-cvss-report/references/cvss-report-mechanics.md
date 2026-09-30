# How the Coverity CVSS report actually computes a score

Everything below was established by reading the installed generator —
`config/Master_CWE_CVSS_Base_Score_Profile_V1.json`, the classes in
`lib/cov-reports.jar`, and the data resources beside them — and by running
the lookup offline against the same inputs the generator uses. Where a
claim rests on documentation rather than on the artifact, it says so.

The short version: **every defect gets a CVSS vector, and roughly two in
five of the CWEs Coverity can assign get a vector that nobody chose.**
Those rows are indistinguishable in the report from rows that were scored
deliberately at zero.

## 1. What produces the numbers

`cov-generate-cvss-report --scores` writes four custom triage attributes
back into Coverity Connect:

| Attribute | Type | Set from |
|---|---|---|
| `CVSS_Vector` | text | the CWE→CVSS lookup below |
| `CVSS_Score` | text | computed from `CVSS_Vector` |
| `CVSS_Severity` | pick list | computed from `CVSS_Score` |
| `CVSS_Audited` | pick list | the reviewer, by hand |

They must exist in Connect **before** the first run (Configuration →
Attributes), and `CVSS_Audited` should default to `No`. A defect whose
`CVSS_Audited` is `Yes` is skipped entirely on later runs — that is the
override mechanism, and it is per-defect, not per-CWE.

Other reports then *display* these attributes. The DISA-STIG report's
CVSS columns are read back from the triage attributes, so a zero there
originates in the CVSS report generator, not in the STIG report.

## 2. The lookup, exactly

`CVSSReport.generateCVSSVector` iterates the defects. Each defect carries
**one** CWE — the field is `optCweId`, a single `Optional<Integer>`, not a
set. Then:

```
if CVSS_Audited equalsIgnoreCase "No" and optCweId is present:
        assignCVSSVector(cwe, ...)      # profile first if one was given,
                                        # then the master
else:
        CVSS_Vector = "CVSS:3.0/AV:N/AC:L/PR:L/UI:N/S:U/C:N/I:N/A:N"
```

and `assignCVSSVector` is:

1. the CWE's own entry in the map, else
2. `findAncestors(cwe)`, keep those with an entry, take the
   highest-scoring one, else
3. the same hardcoded zero-vector string.

This matches the documented five-step rule in the reports guide, with two
details the documentation does not mention and that change what you
conclude:

- **`findAncestors` follows `ChildOf` edges only.** Not `memberOf`, not
  `hasMember`. A CWE whose only route to a mapped CWE is through a
  category is *not* connected as far as this walk is concerned.
- **The zero vector is a literal**, not assembled from the profile's own
  `AV`/`AC`/`PR`/`UI`. A profile that sets `AV:L` still emits `AV:N` on
  every unmapped row. The exploitability half of those vectors is
  therefore not yours even when you supply a profile.

*Source: verified — disassembly of `com.coverity.report.cvss.CVSSReport`
in `lib/cov-reports.jar` (Reports 2025.3.0).*

## 3. Three datasets, three vintages

This is where most of the surprise lives. The generator carries **three
separate CWE-related datasets**, and they do not agree with each other.

| Dataset | Where | What it drives |
|---|---|---|
| CWE→CVSS metrics, 148 entries | `config/Master_CWE_CVSS_Base_Score_Profile_V1.json` | the score |
| checker→CWE, 502 CWEs with checkers | `lib/issue-type-taxonomies-*.jar`, self-reported CWE version **2.10, generated 2017-01-19** | which CWE a defect can carry |
| the CWE graph, **1040 nodes, max weakness id 1039** | `serialised_cwe_files/Serialised_2017_en_US` inside `cov-reports.jar`, deserialized by `CweDataProvider.getCwe2017()` | the ancestor walk |

The XML schema package the graph deserializes into is literally named
`cwe.cwe2017`. The ancestor walk therefore runs on a 2017 snapshot of
CWE, while the analyzer has gone on assigning CWEs ever since.

**49 of the 502 CWEs that Coverity checkers map to have no node in that
graph at all.** They cannot inherit from anything, so they take the
hardcoded zero. Among them:

| CWE | | Checkers |
|---|---|---|
| 1395 | Dependency on Vulnerable Third-Party Component | 2302 |
| 1177 | Use of Prohibited Code | 95 |
| 1076 | Insufficient Adherence to Expected Conventions | 92 |
| 1164 | Irrelevant Code | 43 |
| 1104 | Use of Unmaintained Third Party Components | 21 |
| 1275 | Sensitive Cookie with Improper SameSite Attribute | 8 |
| 1204 | Generation of Weak Initialization Vector (IV) | 2 |
| 1241 | Use of Predictable Algorithm in Random Number Generator | 1 |
| 1327 | Binding to an Unrestricted IP Address | 1 |

CWE-1395 is the one to lead with when explaining this: a finding that says
*you depend on a component with a known vulnerability* scores 0.0 in the
report whose entire purpose is scoring vulnerabilities.

*Source: verified — node ids dumped from the serialized graph with
`tools/CweGraphDump.java`; checker counts from the taxonomy jar.*

## 4. The arithmetic

The equations are CVSS v3 as specified — `8.22`, `6.42`, `7.52`, `0.029`,
`3.25`, `0.02`, `15`, `1.08` all appear in
`CVSSBaseScoreCalculator`. One thing differs:

```java
Math.round(min(score, 10.0) * 100) / 100.0f
```

CVSS v3.0 and v3.1 both specify *round up to one decimal place*. The
generator rounds **half-up to two decimals** instead. So the vector
`CVSS:3.0/AV:N/AC:L/PR:L/UI:N/S:C/C:N/I:N/A:L` (CWE-190, the mapped
integer-overflow entry) is reported as **4.91** where every conforming
calculator says **5.0**.

How much this matters is worth stating precisely rather than
dramatising. `AV`/`AC`/`PR`/`UI` are fixed for the whole profile, so with
the master profile only **12 distinct scores are reachable at all**, and
none of them sits close enough to a band boundary for the rounding to
change `CVSS_Severity`. The defect is a conformance one: the number does
not round-trip against NVD, a customer calculator, or a CVSS library. A
*custom* profile with different exploitability metrics can reach scores
where the band does change, which is the case to check before shipping
one.

*Source: verified — disassembly of `CVSSBaseScoreCalculator`, and
reproduced independently by `tools/cvss_profile_audit.py score`.*

## 5. One checker, several CWEs

The taxonomy maps issue types to CWEs many-to-many, and the reports guide
acknowledges it:

> From report to report, there might be discrepancies in the CWE Top 25/40
> values assigned to issues, but both CWE values are valid.

That matters less than it first appears, and the honest version is worth
stating because the scary version is the tempting one. The defect carries
exactly one `optCweId`, and the mapped and unmapped CWEs of a single
checker can differ by the whole scale:

| Issue type | CWEs it maps to | Scores |
|---|---|---|
| `overrun:write` | 119, 121, 122, 123, 124, 193 | 7.39 for five of them, **0.00** for CWE-193 |
| `integer_overflow` | 190, 191, 128 | 4.91 for CWE-190, **0.00** for 191 and 128 |
| `deadcode` | 561, 1164 | 0.00 either way (561 by design, 1164 by absence) |
| `overrun:read` | 125, 126, 127 | **4.25** for the parent, 7.39 for both children |

**But an issue type does not draw from that list at random.** Across 149
issues observed in two real snapshots, every issue type carried one stable
CWE, and where a checker spans CWEs it is the *subcategory* that decides:
`OVERRUN` write → CWE-119 (7.39), `OVERRUN` read → CWE-125 (4.25),
`deadcode` → CWE-561 every time and never CWE-1164. So the table above is
the set of CWEs the taxonomy associates with a checker, not a set of
outcomes one defect might get. Treat the many-to-many listing as a place to
look, not as evidence of instability.

What is a real problem is the last row: CWE-125 has its own entry worth
4.25, while its children 126 and 127 have none and inherit 7.39 from
CWE-119. The mapping is not monotone down the hierarchy, so a *more
specific* finding can score higher than the general one it specialises.

*Source: verified — taxonomy jar for the issue-type→CWE lists, the audit
tool for the scores, and two committed snapshots for what Connect actually
assigns.*

## 6. What the customer asking "why is there no score" is seeing

Three different situations produce a zero, and they need three different
answers:

1. **Zero by design.** CWE-561, 563, 570, 398, 704 are all present in the
   master profile with `C:N/I:N/A:N`. Somebody decided a quality finding
   is not a vulnerability. That is defensible and it is the answer: the
   score is not missing, it is zero on purpose. If the customer wants
   them non-zero, a profile entry overrides it, which is exactly what
   profiles are for.
2. **Zero by default.** No entry and no mapped ancestor. Nobody decided
   this; the lookup ran out. 209 of 502 CWEs land here, 49 of them
   because the CWE postdates the graph.
3. **No CWE at all.** Parse warnings and some checkers carry no CWE —
   `PW.EXPR_HAS_NO_EFFECT` is one. `optCweId` is empty, so the hardcoded
   zero vector is written without any lookup. This is the blank-CWE row
   with a vector beside it that people notice in the DISA-STIG report.

Only the first is an answer the customer should accept. The second is a
product gap; the third is a documentation gap at best.

## 7. Documentation discrepancies worth knowing before you follow a procedure

- The guide calls the master file
  `config/Master_CWE_CVSS_Base_Score_Mapping-v1.json` in one place and
  `config/Master_CWE_CVSS_BASE_SCORE_PROFILE_V1.json` in another. The file
  on disk is `config/Master_CWE_CVSS_Base_Score_Profile_V1.json`. Three
  spellings, one file.
- The profile example in the guide writes the key as `"cweMap"` in the
  JSON and `"CWEMap"` in the prose. The code reads `cweMap`.
- `version` in a profile is the *profile schema* version, currently `1`.
  The guide warns against using the Coverity version number there; it is
  worth repeating because the failure is a hard exit, not a warning.

*Source: verified — reports guide 2025.12 against the Reports 2025.3.0
install.*

## 8. What a run confirms, and where the gap actually lives

Two snapshots of the same C fixtures, scored by the real generator against
Coverity Connect 2025.12.0.

**Plain analysis** (`--all --aggressiveness-level high`), 19 defects, 13
CWEs: every CWE, vector, score and severity matched what the offline audit
predicted, and **no CWE landed in a zero-by-default class**. The same held
for three unrelated C/C++ projects on the same instance — proftpd,
Contiki-NG, subversion — 12, 8 and 13 CWEs, no gap in any of them.

**The same fixtures under MISRA C 2012**, 130 issues, 22 CWEs: 114 of the
130 scored 0.0. Of those, 79 are zero by design and **35 are zero by
default**, over 8 CWEs the audit had named in advance:

| CWE | | issues | why zero |
|---|---|---|---|
| 1177 | Use of Prohibited Code | 16 | no node in the graph |
| 691 | Insufficient Control Flow Management | 6 | no mapped ancestor |
| 664 | Improper Control of a Resource Through its Lifetime | 4 | no mapped ancestor |
| 1164 | Irrelevant Code | 3 | no node in the graph |
| 1076 | Insufficient Adherence to Expected Conventions | 2 | no node in the graph |
| 682 | Incorrect Calculation | 2 | no mapped ancestor |
| 696 | Incorrect Behavior Order | 1 | no mapped ancestor |
| 908 | Use of Uninitialized Resource | 1 | no mapped ancestor |

The conclusion to carry into a customer conversation is not "the mapping is
broken". It is: **the mapping covers ordinary C/C++ defect analysis, and
runs out where the CWEs are newer than its 2017 data** — coding standards,
software composition (CWE-1395, 2302 checkers), and the cloud/IaC
checkers. The 209-of-502 ceiling is the size of the uncovered territory,
not the size of anyone's problem; which of the two you are looking at
depends entirely on what analyses they run.

One more thing the PDF itself settles: its per-issue block prints `CVSS
Severity`, `CVSS Score`, `CVSS Vector` and `CVSS Audited`, and **not the
CWE**. So within the report there is no way to tell a deliberate zero from
a zero the lookup fell into, and no way to tell which CWE produced either.
The scorecard's "Additional Quality Measures" table counts only issues
marked False Positive or Intentional, so it does not cover this. The
distinction exists in exactly two places: the generator's stdout, and the
triage attributes in Connect.

*Source: verified — snapshots 10037 and 10038 on `localhost:8080`,
Reports 2025.3.0, and the text of the generated PDF; see `CALIBRATION.md`
for the per-CWE tables.*
