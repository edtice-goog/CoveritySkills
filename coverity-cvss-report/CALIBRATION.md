# Calibration status

This project's standard is that factual claims in a skill were established
by real runs. This file records what was run for `coverity-cvss-report`,
on what, and what is reasoned rather than measured.

Environment: Windows 11, installations under `C:\Coverity\`. All dates
2026-09-17.

| Component | Version | Role |
|---|---|---|
| Coverity Reports | **2025.3.0**, `C:\Program Files\Coverity\Coverity Reports` | the generator under audit |
| Coverity Connect | 2025.12.0, `C:\Coverity\Platform` | not yet used; see "Not yet verified" |
| Coverity Analysis | 2025.12.0 win64 | capture and analysis of the fixtures, and the JDK the graph dump uses |
| Compiler | gcc (Strawberry Perl toolchain), templated config | fixture capture |

The version skew is itself a finding in miniature: Reports installs
separately from Connect and does not track it, so the generator scoring a
2025.12 instance's defects was nine months older than the instance. The
audit is therefore always of *an install*, never of "Coverity".

## Verified by direct execution

**The mapping and the graph** (read from the 2025.3.0 install):

- The master profile `config/Master_CWE_CVSS_Base_Score_Profile_V1.json`
  holds **148 CWE entries** with global `AV:N/AC:L/PR:L/UI:N`.
- The checker taxonomy `lib/issue-type-taxonomies-1.6.479.jar` maps
  Coverity issue types to **502 CWEs**, and self-reports CWE version
  **2.10, generated 2017-01-19**.
- The ancestor graph, deserialized from
  `serialised_cwe_files/Serialised_2017_en_US` via
  `CweDataProvider.getCwe2017()` (`tools/CweGraphDump.java`), has **1040
  nodes, 233 of them with no `ChildOf` parent, highest weakness id 1039**.
- **49 of the 502 CWEs with checkers have no node in that graph**,
  including CWE-1395 (2302 checkers), 1177 (95), 1076 (92), 1164 (43),
  1104 (21), 1275 (8), 1204 (2), 1241 (1), 1327 (1).
- Running the documented lookup over the real graph classifies the 502 as:
  116 scored from their own entry, 146 scored by inheritance, 31 zero by
  design, 27 zero by inheriting a zero, 133 zero with no mapped ancestor,
  49 zero with no node at all. **209 zeros that no mapping chose.**
- With the taxonomy's own parent links instead of the real `ChildOf`
  edges, the same audit reports 190 — the approximation under-reports the
  gap by 19 CWEs, which is why `graph` exists.

**The implementation** (disassembly of `lib/cov-reports.jar` with
`javap -c`):

- `CVSSReport.generateCVSSVector` reads a single `optCweId` per defect,
  skips defects whose `CVSS_Audited` is not `No`, and writes the literal
  `CVSS:3.0/AV:N/AC:L/PR:L/UI:N/S:U/C:N/I:N/A:N` when no CWE is present.
- `assignCVSSVector` tries the direct entry, then `findAncestors`, then
  the same literal. `findAncestors` follows **`ChildOf` edges only**.
- `CVSSBaseScoreCalculator` uses the CVSS v3 constants (8.22, 6.42, 7.52,
  0.029, 3.25, 0.02, 15, 1.08) and rounds with
  `Math.round(min(score,10.0) * 100) / 100.0f` — half-up to two decimals,
  where CVSS v3.0 and v3.1 specify rounding up to one decimal.
- `CweGraphDump` needs `-DOWASP` and `-DSANS` set: `getCwe2017` calls
  `System.getProperty` on both and dereferences the result without a null
  check. The values do not affect the `ChildOf` edges.

**The arithmetic, cross-checked against real customer output.** A
DISA-STIG severity report supplied by the user showed CWE-190 as
`CVSS:3.0/AV:N/AC:L/PR:L/UI:N/S:C/C:N/I:N/A:L`, score **4.91**. An
independent implementation of the v3.1 equations
(`cvss_profile_audit.py score`) gives **4.9096** unrounded, **4.91** at
two decimals half-up, **5.0** under the specified roundup. The
reimplementation reproduces the generator exactly, which is what licenses
the rest of the offline analysis.

Also verified from the same output: the blank-CWE row carrying a full
vector is the no-`optCweId` path, and `PW.EXPR_HAS_NO_EFFECT` is an issue
type with no CWE in the taxonomy — one such defect appears in the
fixtures.

**Severity-band impact of the rounding, measured rather than assumed.**
Because `AV`/`AC`/`PR`/`UI` are fixed per profile, only **12 distinct
scores are reachable** with the master profile. None of them lies in a
range where two-decimal rounding and the specified roundup fall in
different severity bands, so with the shipped profile the defect is
conformance-only. A custom profile with different exploitability metrics
can reach such scores.

**The fixtures** (`evals/fixtures/*.c`, captured with a templated gcc
config, 3 compilation units at 100%, analyzed 2025.12.0 win64):

- `--all` produces 16 defects. Adding `--enable-audit-mode` changes
  nothing (still 16); adding `--aggressiveness-level high` produces 19,
  the difference including the 2 `UNUSED_VALUE` occurrences that carry
  CWE-563. **UNUSED_VALUE needs `--aggressiveness-level high` on these
  shapes**, and its absence looks like a mapping failure rather than an
  analysis setting. The two flags were measured separately after a first
  run conflated them.
- Issue types produced, and the CWEs the taxonomy gives them:
  `buffer_size:overflow` → 120; `deadcode` → 561, 1164;
  `no_effect:unsigned_compare` → 570; `no_effect:no_effect_test` → 482;
  `overrun:write` → 119, 121, 122, 123, 124, 193; `overrun:read` → 125,
  126, 127; `resource_leak` → 404; `string_overflow:likely_overflow` →
  120; `tainted_scalar:allocation` → 789; `forward_null` → 476;
  `overflow_before_widen` → 190; `unused_value` → 563;
  `PW.EXPR_HAS_NO_EFFECT` → none.
- Predicted scores for those: 120 → 9.89, 119/121/122/123/124 → 7.39,
  193 → **0.00**, 125 → 4.25 but 126/127 → 7.39, 404 → 5.35, 789 → 7.39,
  476 → 7.39, 190 → 4.91, 482 → 5.35, 457 → 6.30, 561/563/570 → 0.00 by
  design, 1164 → 0.00 by absence.

**Fixture shapes that did not work, and were kept as notes rather than
quietly fixed:**

- `long c = a * b` produces no OVERFLOW_BEFORE_WIDEN on LLP64 Windows,
  where `long` is 32 bits. `long long` is needed for the widening to be
  real on every platform.
- A `malloc` result dereferenced with no check at all did not produce
  NULL_RETURNS; noticing the NULL case and falling through it produces
  FORWARD_NULL, which is what the fixture does now.
- `int x; float *f = (float *)&x; return *f;` produced no
  INCOMPATIBLE_CAST, nor did the `short` narrowing variant. **CWE-704 has
  no sample defect.** It does not need one — CWE-704 is in the master
  profile with `C:N/I:N/A:N`, read directly from the file.
- Writing through `int *p = (int *)&c` where `c` is a `char` reports as
  OVERRUN, not INCOMPATIBLE_CAST. Coverity says the more specific thing.

## The live run

Against Connect 2025.12.0 at `localhost:8080`, Reports 2025.3.0, in a
project created for this (`cvss-audit-sample`) with its own triage store
(`cvss-audit-triage`) so nothing written here reaches another project's
defects.

**Standing it up.** The four attributes cannot be created by
`cov-manage-im` (it sets attribute *values* on defects) nor by REST
(`/api/v2/checkerAttributes` exposes only `displayType`,
`displayCategory`, `checker`). `createAttribute` on the v9 SOAP
configuration service works, with `attributeType` `STRING` and
`LIST_OF_VALUES` — **not** the lowercase spellings; the accepted values
are in the API reference's "Attribute type (attributeType)" table, not in
the reports guide. `--mode triage` creates a triage store, not
`--mode triage-stores`. `project-contact-email` is validated as an email,
so `example.invalid` is rejected.

**Snapshot 10037, 19 defects, plain `--all --aggressiveness-level high`.**
`--scores` then `--report` both completed. Every one of the 19 predictions
the offline audit made was exact — CWE, vector, score and severity:

| CWE | checker | vector impact | score | severity |
|---|---|---|---|---|
| 120 | BUFFER_SIZE, STRING_OVERFLOW | S:C/C:H/I:H/A:H | 9.89 | Critical |
| 676 | DC.STRING_BUFFER | S:U/C:N/I:H/A:N | 6.43 | Medium |
| 119 | OVERRUN (write) | S:C/C:L/I:L/A:L | 7.39 | High |
| 125 | OVERRUN (read) | S:U/C:L/I:N/A:N | 4.25 | Medium |
| 476 | FORWARD_NULL | S:C/C:L/I:L/A:L | 7.39 | High |
| 789 | TAINTED_SCALAR | S:C/C:L/I:L/A:L | 7.39 | High (inherited from 400) |
| 457 | UNINIT | S:C/C:N/I:L/A:L | 6.3 | Medium |
| 404 | RESOURCE_LEAK | S:U/C:L/I:N/A:L | 5.35 | Medium |
| 482 | NO_EFFECT (test/assign) | S:U/C:N/I:L/A:L | 5.35 | Medium |
| 190 | OVERFLOW_BEFORE_WIDEN | S:C/C:N/I:N/A:L | **4.91** | Medium |
| 561, 563, 570 | DEADCODE, UNUSED_VALUE, NO_EFFECT | all N | 0.0 | None by design |
| (none) | PW.EXPR_HAS_NO_EFFECT | all N | 0.0 | None |

- **The rounding defect, on live data.** CWE-190 is recorded as `4.91`,
  not the specified `5.0`. `cvss_profile_audit.py verify` on the run's own
  `WRITE_ISSUES_JSON`: 13 of 19 disagree with the CVSS v3 roundup, 0
  disagree with half-up-to-two-decimals, 0 change severity band.
- **The no-CWE path, in the product's own words.** The run printed
  `Assigning a CVSS vector whose CVSS score is zero, for defect:
  Optional[13702] as there isn't any cwe associated for this defect.`
  CID 13702 is the `PW.EXPR_HAS_NO_EFFECT`.
- **`WRITE_ISSUES_JSON` does not contain the CWE.** `optCweId` serializes
  as `{"empty": false, "present": true}` — the Optional's bean properties
  with the value dropped. It carries `cvssVector`, `cvssScore` and
  `cvssSeverity`, so it can verify the arithmetic and cannot drive a
  per-project CWE audit. That needs a REST export with the `cwe` column.
- **Custom attributes in REST are `column_custom_<Name>`** —
  `column_custom_CVSS_Score` and so on. `cov-manage-im --mode defects`
  has no CWE field at all, and the issues search returns 0 rows for
  `snapshotScope.show.scope: "last"`; an explicit snapshot id works.

**The gap, measured on four real populations.** Read-only REST exports of
the CWEs each project actually carries, audited against the mapping:

| population | CWEs | gap |
|---|---|---|
| `cvss-audit-sample`, 19 defects | 13 | **none** |
| proftpd 1.3.9, 112 issues | 12 | **none** |
| Contiki-NG, 39 issues | 8 | **none** |
| subversion + sqlite, 130 issues | 13 | **none** |

So on ordinary C/C++ quality-and-security analysis the master profile
covers what Connect assigns. **The 209-of-502 figure is a ceiling over the
whole checker inventory, not a prediction for a project**, and saying
otherwise would overstate it.

**Snapshot 10038: the same code under MISRA C 2012**
(`--coding-standard-config misrac2012-all.config`), 130 issues, 22 CWEs —
and the gap appears, because MISRA's CWEs are the ones that postdate the
2017 graph:

- **114 of 130 issues scored 0.0.** 79 of those are zero by design
  (CWE-710 ×66 "Improper Adherence to Coding Standards", 704 ×7, 561 ×5,
  570 ×1 — entirely reasonable for MISRA). **35 are zero by default**,
  across 8 CWEs, and the audit named all 8 in advance:
  CWE-1177 ×16 (Rules 21.3, 21.6, Directive 4.12), 691 ×6 (Rule 15.5),
  664 ×4 (Rules 10.3, 10.6), 1164 ×3 (Rule 17.7), 1076 ×2 (Rule 14.4),
  682 ×2 (Rule 10.4), 696 ×1 (Directive 4.13), 908 ×1 (Rule 9.1).
- 1177, 1164 and 1076 have **no node in the 2017 graph**; 664, 682, 691,
  696 and 908 have nodes but no mapped ancestor along `ChildOf`.
- The generator says so itself: `Assigning a CVSS vector whose CVSS score
  is zero, as corresponding cwe: "Optional[1164]" isn't available in
  either profile or master cwe - cvss mappings json file`.

**One claim this run retired.** The taxonomy lists several CWEs per issue
type, and I had expected that to mean the same checker could score 7.39 or
0.00 depending on which CWE it drew. It does not: across 149 observed
issues every issue type — checker plus subcategory — carried one stable
CWE, and where a checker spans CWEs it is the subcategory that decides
(`OVERRUN` write → 119, read → 125). The gap CWEs all arrived from MISRA
rules, not from a familiar checker changing its mind. The many-to-many
taxonomy listing is therefore a weaker signal than it looks, and the
skill says so rather than keeping the scarier version.

## The documented CVSS_Audited override does not work (Reports 2025.3.0)

The reports guide says setting `CVSS_Audited` to `Yes` prevents the vector
being updated on later runs. It does not, and this was measured rather than
inferred:

1. CID 13721 (CWE-1177, case (c), scoring 0.0) was given
   `CVSS:3.0/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H`, `CVSS_Score` 9.89,
   `CVSS_Severity` Critical, `CVSS_Audited` Yes, via
   `PUT /api/v2/issues/triage`. Read back: 9.89 / Yes.
2. `cov-generate-cvss-report --scores` was re-run.
3. Read back: **0.0 / No.** Every one of the 130 defects in the snapshot had
   `CVSS_Audited` reset to `No`, including the 95 `mark` had set to `Yes`.

Repeated on a second project (`cvss-audit-default`, snapshot 10039) whose
stream sits in the **Default Triage Store**, with the same outcome, so it is
not an artifact of using a custom store.

The mechanism agrees: `CVSSReport.getDefectStateSpecDataObj` builds a
`DefectStateSpecDataObj` containing all four attributes — `CVSS_Audited`
among them — and writes back `CVSSDefectInfo.cvssAudited`, the value it
loaded. Since every defect came back `No`, the load never saw the `Yes` that
Connect was holding.

Consequences, now baked into the workflow rather than the prose:

- `mark` and `infer --apply` must run **after** the final `--scores`.
- Any later `--scores` discards both silently, so `unjudged.csv` and
  `inferred.csv` are the durable record and the attributes are a
  convenience.
- `cvss_run.py selftest` performs the experiment above against whatever
  Reports build is installed, and restores the probed defect, so the skill
  measures this rather than trusting either the guide or this file.

This is a design limitation of the current implementation, not something a
skill can repair: a CVSS vector derived from a CWE belongs to a stream or a
project rather than to each defect, and a mapping change ought to clear the
scores for recalculation.

## Withdrawn: every claim that counted a global inventory

Three numbers appeared in earlier versions of this skill and are gone. All
three were the same mistake, and it is worth naming because the tooling now
structurally prevents it.

| withdrawn claim | why it was wrong |
|---|---|
| "209 of 502 CWEs resolve to a zero nobody chose" | Counted CWEs the taxonomy *associates* with a checker. A defect carries exactly one CWE, so an unmapped CWE may be one Coverity never assigns. CWE-193 is associated with `overrun:write` and was never once assigned to it. |
| "2357 security issue types cannot score" | Same, one level up, and worse: the `issue-type-taxonomies` jar covers a far wider Black Duck product family than Coverity SAST. 2302 of the 2357 were `sigma.vulnerable_software` — software composition, which Coverity does not do, so it never surfaces those findings at all. |
| "12 of them are reachable in this install" | Filtered the above by `cov-analyze --list-checkers`. That describes the analyzer on this machine, which need not be the analyzer that produced any given snapshot. |

**The Connect version, the Coverity Analysis version that wrote the
snapshot, and any local Coverity install can all differ.** No inventory on
the local machine is therefore evidence about a project's defects. The only
sound population is the CWEs Connect actually reports for a snapshot, read
over REST, classified against the Reports install doing the mapping — and
the verdict has to name that Reports version, because a later one can
change it.

`cvss_profile_audit.py` now prints a caveat when run without `--issues`,
saying in as many words that it is inventorying the mapping and not making
a finding about any project. The `checkers` subcommand that produced the
second and third numbers has been removed rather than caveated: it invited
exactly the claim it could not support.

Everything in "The live run" above survives this, because every population
there came from Connect over REST in the first place.

## The workflow, run end to end

`cvss_run.py` was run through on snapshot 10038 (the MISRA one, 130 issues,
22 CWEs):

- `status` — reproduced the split unaided: 16 issues case (b), 79 case (a),
  35 case (c).
- `mark` — set `CVSS_Audited=Yes` on 95 and left 35 `No`. Verified by an
  independent REST export: 35 `No` all scoring 0.0, 79 `Yes` scoring 0.0, 16
  `Yes` scoring non-zero. That is the split visible in Connect, which is the
  point of the step.
- `infer` — **found a real bug in its own rule.** The first version built its
  basis only from judged defects with a *non-zero* score, so it ignored the
  79 defects in the same category that were judged to have *no* impact, and
  proposed 7.39 (High) for every unjudged MISRA violation. Including the
  zero-impact judgements — they are judgements, and there the majority ones
  — the rule proposes **0.00 for all 35**, by analogy with 83 judged
  coding-standard issues. That is the defensible answer for MISRA and it is
  the vendor's own judgement being extended, not ours.
- `infer --apply` — wrote all 35 and marked them, confirmed 130/130 `Yes`.
- `report` — produced the PDF. `--report` does **not** write the attributes
  (130 still `Yes` afterwards); only `--scores` does.
- `selftest` — reported NOT HONOURED and restored the probed defect.

Also found: the PDF prints `CVSS Audited: No` for defects that were `Yes` in
Connect, which is the same read failure as above surfacing in the output.

## Reasoned, not yet measured

- **A user `<security-profile>.json` overriding the master.** The lookup's
  profile-first branch was read in the bytecode and is implemented in the
  audit tool, but no run used a profile, so the precedence is verified by
  disassembly only.
- **That `--scores` writes every non-audited defect in a project.** Both
  runs here scored every defect in their snapshot, and
  `generateCVSSVector` iterates `defectHolder.defectInfoList` unfiltered,
  but no run was made where `CVSS_Audited` was `Yes` on some defects to
  watch them be skipped. All 19 and all 130 were `No`.
- **Whether a newer Reports release changes any of this.** Only 2025.3.0
  was audited, against a 2025.12.0 instance. The audit is re-runnable
  against any install, which is the point of it being a tool rather than a
  table.
- **Non-C languages.** Everything run here is C. Whether a Java, JS or C#
  snapshot produces case (c) at all is unmeasured, and cannot be predicted
  from the taxonomy for the reasons in "Withdrawn" above — it takes a
  snapshot of such a project in Connect and a `mark` run against it.
- **Non-C languages, still.** Whether a Java, JS or C# snapshot produces
  case (c) is unmeasured, and cannot be predicted from the taxonomy for the
  reasons in "Withdrawn" above.
