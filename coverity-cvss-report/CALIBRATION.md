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

## Reasoned, not yet measured

- **Which CWE a multi-CWE issue type actually receives.** The taxonomy
  gives `overrun:write` six CWEs and `integer_overflow` three, the defect
  carries exactly one, and the spread between them is 7.39 versus 0.00.
  Which one Connect attaches is not decidable from the generator's files;
  it takes a run. This is the single most consequential open question in
  the skill, and the fixtures exist to settle it.
- **That Connect's CWE assignment can name a CWE absent from the 2017
  graph.** The 49-CWE list is derived from the generator's own taxonomy;
  demonstrating that a real defect lands on one of them (CWE-1164 from
  `deadcode` is the cheapest candidate) needs the run.
- **The procedure in SKILL.md Steps 2-4** — creating the four triage
  attributes, `config.yaml`, `--scores`, `--report`, `WRITE_ISSUES_JSON`
  — follows the reports guide for 2025.12 and the `--help` output, and
  has **not been executed**. The claim that `--scores` writes attributes
  onto every non-audited defect in the project comes from the
  documentation and from `generateCVSSVector` iterating
  `defectHolder.defectInfoList` unfiltered; it has not been observed
  against an instance.
- **Whether a newer Reports release changes any of this.** Only 2025.3.0
  was audited. The audit is re-runnable against any install, which is the
  point of it being a tool rather than a table.

## Not yet verified

No Coverity Connect instance was written to. No project, stream,
snapshot, triage attribute, or report was created. Every number above
comes from reading the installed generator, disassembling it, or
analyzing local fixtures.
