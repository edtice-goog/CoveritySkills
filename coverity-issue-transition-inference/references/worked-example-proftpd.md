# Worked example: proftpd v1.3.8 -> v1.3.9, Coverity 2024.12.1 -> 2025.12.2

The calibration run that validated the method. A full **2x2 factorial** was
built rather than a single diagonal, so the labels could be checked against
something instead of asserted.

```
        A1 = 2024.12.1        A2 = 2025.12.2
C1 =    a  96 occ / 62 keys   b  148 occ / 113 keys
v1.3.8
C2 =    c  94 occ / 60 keys   d  147 occ / 112 keys
v1.3.9
```

Session run 2026-08-24. Capture in WSL2 (gcc 13.3.0), analysis in WSL with
`--security-file`, commit from Windows to a local Connect 2025.12.0. Fixed
build tree `~/iti/proftpd`, serial `make`, one fresh idir per cell, all 90 TUs
at 100% in every cell.

## What the user would have seen

Their own upgrade -- `a` to `d`, code and analyzer moving together:

```
before   96 occurrences,  62 findings
after   147 occurrences, 112 findings
```

Fifty new findings. The obvious readings are both wrong: "we introduced 50
bugs" and "the analyzer got much better."

## The attribution

117 CIDs across all four cells:

| Label | n | Meaning |
|---|---|---|
| `UNCHANGED` | 57 | present throughout |
| `VERSION_ATTRIBUTABLE` | 54 | not written by them |
| `DROPPED_BY_VERSION` | 3 | still in their code; the tool went quiet |
| `RESOLVED_BY_CODE` | 2 | their change fixed it |
| `CODE_ATTRIBUTABLE` | **1** | they wrote it |

Only five presence patterns occurred, all interpretable:

```
pattern  label                  n
ABCD     UNCHANGED             57
.B.D     VERSION_ATTRIBUTABLE  54
A.C.     DROPPED_BY_VERSION     3
AB..     RESOLVED_BY_CODE       2
...D     CODE_ATTRIBUTABLE      1
```

No diagonal-only pattern (`A..D`, `.BC.`) occurred, so `CONTROL_FAILURE` was
empty -- which is what the code-sameness evidence predicts.

## The prediction, registered before any analysis ran

Diffing `checker-enablement-and-option-defaults.html` between the two installs,
filtered to C:

| Change | Consequence |
|---|---|
| `NULL_FIELD` Optional -> **Default** | its findings are configuration |
| `INCOMPLETE_DEALLOCATOR` new, **Default** | same |
| nothing removed | -- |

Outcome: of 54 findings new on **identical code**, **50 were `NULL_FIELD`**.
93% of the apparent improvement was one checker being switched on.
`INCOMPLETE_DEALLOCATOR` fired zero times. The remaining 4 were 2
`FORWARD_NULL` and 2 `DEADCODE`.

The raw enablement diff showed **213 changed rows**; nearly all were a
documentation rename (`All Security` -> `Recommended Security Checkers`), not
behaviour. Filter to genuine default-on transitions or the diff reports a
sweeping configuration change that did not happen.

## The finding that justifies the skill

```
CID 10114   NULL_FIELD   src/fsio.c:pr_fsio_realpath   pattern ...D
```

A real new defect, in a function **added wholesale in v1.3.9** (confirmed by
`git diff v1.3.8 v1.3.9 -- src/fsio.c`: the entire function body is an
addition).

Every cheaper method loses it:

- Comparing the two snapshots they have: it sits among 50 other `NULL_FIELD`
  findings from the same checker on the same upgrade.
- Filtering by checker: `NULL_FIELD` is 50/51 configuration noise, so the
  obvious heuristic discards a genuine bug.
- Running the `(C2,A1)` diagonal instead: the old analyzer **never reports it**,
  because `NULL_FIELD` is off by default there. It is not buried, it is absent.

Only cell `b` resolves it, by proving the new analyzer does *not* report it on
v1.3.8. That is the cell users do not have, and producing it is the method.

## The other direction

```
A.C.  CID 10115  FORWARD_NULL  lib/hanson-tpl.c:tpl_gather_mem
A.C.  CID 10116  FORWARD_NULL  lib/hanson-tpl.c:tpl_extend_backbone
A.C.  CID 10117  FORWARD_NULL  lib/hanson-tpl.c:tpl_gather_nonblocking
```

Present in **both** code versions, reported only by the old analyzer. Nobody
fixed these; the tool stopped reporting them. In a dashboard they read as three
defects closed. Whether they are a regression or a deliberate false-positive
reduction is a question for the vendor -- but the user needs to know they were
not fixed.

## Controls, and what each one bought

**Native control pair (build reproducibility).** Two native v1.3.8 builds: 95 of
97 artifacts byte-identical. The two that differ are `src/main.o` (6 bytes) and
`proftpd` (26 bytes), from an embedded `Built: <date>` stamp, plus the 20-byte
ELF build-id at offset 889. proftpd is *not* bit-reproducible, and the floor has
to be measured rather than assumed.

**Fidelity arm.** `D(native1, a2024)` was **offset-for-offset identical** to the
control `D(native1, native2)` -- `{15643, 15645, 15646, 16558, 16560, 16561}` in
`main.o`. So `K` is empty: `cov-build` perturbed nothing.

Comparing the two *capture* arms to each other showed 8 differing bytes in
`main.o` rather than 6, at `{15642, 15643, 15645, 15646, 16557, 16558, 16560,
16561}` -- adjacent to the control's offsets, because a later build time changes
more digits of the same timestamp. This is exactly why the methodology subtracts
by **interval overlap, never offset equality**.

**Coverage arm.** Cells `a` and `b`: 90 TUs each, identical `primaryFilename`
sets, zero size differences, 90/90 AST-complete.

**Patch and platform control (unplanned, from a licence detour).** The same idir
analyzed by win64 2024.12.0 and by linux64 2024.12.1 produced **identical
merge-key sets** -- 96 occurrences, 62 keys, zero either-way. Patch-level drift
was nil, and analysis platform does not perturb defect identity.

**Anchor reproduction.** A second independent build of v1.3.8 under 2024.12.1
produced 96 occurrences / 62 keys, an **identical merge-key set** to the first.
The anchor step of the production procedure is achievable, not aspirational.

**Path independence.** The same defect built in `alpha/` and in
`a-much-longer-dir-name/` carried an identical merge key
(`c7fb1f1a2f52dd0cc9b11c9916b1c357`). Merge keys are path-independent, so a
field reproduction need not rebuild at the CI path.

## Rule 27 was not exercised

Raw local merge keys and Connect CIDs agreed **exactly** on the `a`/`b` pair:

```
local raw keys   59 shared, 3 only-a, 54 only-b
Connect CIDs     59 shared
```

So no key moved, and the antecedent-merge-key path never had to fire. This
measures the exception rate at **0 of 59 for this version pair**. It does not
demonstrate the mechanism works -- only that it was not needed here. On this
pair, hand-diffing raw merge keys would have given the right answer, which is
precisely why a case where it does not is still owed.

## Environment

- Capture: `cov-analysis-linux64-2024.12.1` (emit format 343) and
  `-2025.12.2` (format 352), WSL2 Ubuntu, gcc 13.3.0
- Analysis: the same two installs, with `-sf` pointing at a valid `license.dat`
  from a win64 install (the bundled Linux licences expired 2025-12-31)
- Commit: `cov-analysis-win64-2024.12.0` (format 343) and `-2025.12.0`
  (format 352) to Connect 2025.12.0 over `http://localhost:8080`
- Connect objects: triage store `iti-triage`, project
  `issue-transition-proftpd`, four streams, all created for this run
