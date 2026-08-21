# Escalation ladder — details and tradeoffs

Facts below were verified against Coverity 2026.6.0. Option names and defaults
are stable across recent releases, but when something doesn't behave as
described, trust `cov-analyze --help` and the docs shipped inside the user's
installation over this file.

## Rung 1: The two "out of the box" baselines

```
$BIN/cov-analyze --dir idir
$BIN/cov-analyze --dir idir --recommended-security-checkers
```

The bare run is equivalent to `--aggressiveness-level low`: default checker
set, default options. A hit here means "yes, Coverity finds this out of the
box" — the strongest possible verdict.

Run `--recommended-security-checkers` as a second baseline because it is the
default the Coverity CLI (Polaris) passes — so for teams driving Coverity that
way, *this* is what "out of the box" actually reports, and the verdict should
say which baseline the user's pipeline corresponds to. Per the docs it equals
`--android-security --webapp-security` (plus the default Sigma set). Verified
caveat (2026.6.0): it does **not** enable the C-family injection checkers —
`system(argv[1])` stays unreported under it even with `--distrust-all`, while
`--security` finds it. On plain C/C++ command-line code it typically adds
nothing; when that's the outcome, saying so explicitly ("the CLI-default
security set targets web/mobile and does not cover this defect class") is a
useful part of the answer, not a wasted run.

**Security-class defect? Add `--security` to the first batch — don't wait.**
If the target defect is security-natured (injection, taint flow, risky
functions, buffer abuse used as an attack primitive) and the language is
C/C++, one thing is near-certain: without `--security` it will not be
reported, because the C-family security checkers simply aren't running. The
bare-defaults run is still worth doing (it establishes the "out of the box"
verdict honestly), but run `--security` in the same first batch rather than
discovering the miss and climbing aggressiveness rungs that were never going
to help. For injection classes specifically, pair it immediately with the
relevant `--distrust-*` flag (see the two-switches section) — `--security`
without a distrusted source is the classic half-configured miss.

## Rung 2: Aggressiveness levels

```
$BIN/cov-analyze --dir idir --aggressiveness-level medium
$BIN/cov-analyze --dir idir --aggressiveness-level high
```

Aggressiveness levels don't change *which* checkers run — they flip documented
sets of checker options toward more aggressive assumptions. The exact lists
are printed in `cov-analyze --help` as two tables: "Increasing aggressiveness
from 'low' to 'medium'" and "from 'medium' to 'high'". Examples from the
low→medium table: `UNINIT:enable_write_context`, `UNINIT:check_arguments`,
`FORWARD_NULL:aggressive_null_sources`, `CHECKED_RETURN:stat_threshold` 80→55.

Cost (from the vendor docs): aggregate false-positive rate is roughly 50%
higher at medium and 70% higher at high, across all non-parse-warning
checkers. That is why a hit at this rung must be minimized to a single option
(Step 4 in SKILL.md) before reporting.

Run medium before high: if medium finds it, the minimization search space is
the low→medium table only, which is much smaller.

## Rung 3: --all

```
$BIN/cov-analyze --dir idir --aggressiveness-level high --all
```

`--all` enables almost all checkers that are disabled by default. Per the
docs it is equivalent to combining `--concurrency`, `--enable-parse-warnings`,
`--security`, `--rule`, and enabling the remaining individually-disabled
checkers (a few exotic ones remain off; `cov-analyze --help` lists the
exceptions). Combine with high aggressiveness so this rung strictly dominates
rung 2 — if the defect isn't found here, no quality-checker configuration
short of audit mode will find it.

A hit at this rung that wasn't present at rung 2 means a disabled-by-default
*checker* (not option) is responsible. Identify it from the defect type in the
output, then confirm with a targeted run: default aggressiveness plus
`--enable <THAT_CHECKER>` alone.

## Rung 4: Audit-mode security checkers

```
$BIN/cov-analyze --dir idir --enable-audit-checkers
```

Audit mode targets security review: checkers and dataflow settings that favor
recall over precision (many more findings, many more false positives — not
meant for CI gating). Only relevant when the defect is security-flavored
(tainted data, injection, crypto misuse, information exposure). The docs
recommend `--enable-audit-checkers` first; add `--enable-audit-dataflow` in a
separate run only if you need deeper taint propagation. `--enable-audit-mode`
is the combination of both, and is slow.

For web/mobile-security defect classes there is also `--webapp-security` /
`--android-security`.

## Security (taint) checkers need two switches, not one

Injection and tainted-dataflow checkers — OS_CMD_INJECTION,
FORMAT_STRING_INJECTION, SQLI, PATH_MANIPULATION, TAINTED_* — only report when
**both** of these hold:

1. **The checker is enabled** — via `--security` (the C-family security set,
   also pulled in by `--all`) or a targeted `--enable <CHECKER>`.
2. **The relevant input source is marked untrusted** — via `--distrust-*`
   flags: `--distrust-command-line` (argv), `--distrust-filesystem` (file
   reads — and note stdin via `gets`/`fgets` counts as *filesystem*, not
   console), `--distrust-environment`, `--distrust-http`, ... or
   `--distrust-all` for everything.

High aggressiveness also flips source-trust defaults. That combination
produces a classic trap during minimization: a defect appears at
`--aggressiveness-level high --all`, but `--enable <CHECKER>` alone at default
aggressiveness cannot reproduce it. The missing ingredient is nearly always
source trust — retry with `--distrust-all`, then narrow to the single source
that matters.

Verified examples (2026.6.0): `system(argv[1])` reports OS_CMD_INJECTION with
`--enable OS_CMD_INJECTION --distrust-command-line`; `printf(buf)` where `buf`
came from `gets` reports FORMAT_STRING_INJECTION with
`--enable FORMAT_STRING_INJECTION --distrust-filesystem`. In both cases
`--enable` alone finds nothing.

## Frequent culprits: deliberate default suppressions

When "Coverity misses X" on a snippet, check these known-by-design defaults
before running long experiments — recognizing one can collapse the whole
ladder into a single targeted run:

| Symptom | Knob | Why it's off by default |
|---------|------|------------------------|
| Leak in `main` not reported | `RESOURCE_LEAK:allow_main:true` | OS reclaims memory at exit, so leak-until-exit is usually noise |
| Interprocedural possibly-uninitialized read missed | `UNINIT:enable_write_context:true` | Callee initializing on *some* path suppresses the report to hold down FPs |
| Unchecked `malloc`/return-value deref missed | NULL_RETURNS `stat_threshold` (default 80) | Statistical: respects the codebase's own checking convention — see the statistical-checkers section |
| `strcpy`/`sprintf` into smaller buffer missed | `--enable STRING_OVERFLOW` | Checker disabled by default (FP-prone on hand-verified copies) |
| Risky-function calls (`gets`, `strcpy`, ...) not flagged | `--security` or high aggressiveness (DC.* / SECURE_CODING checkers) | Style/hardening findings, not defects — off for quality-focused runs |
| Injection (argv/env/file → `system`, format string, ...) missed | enable checker **and** `--distrust-*` source | See the two-switches section above |

## Rung 5: Targeted enablement from the docs

When the generic rungs come up empty, or to confirm a suspicion precisely:

```
$BIN/cov-analyze --dir idir --enable <CHECKER>
$BIN/cov-analyze --dir idir --checker-option <CHECKER>:<option>:<value>
```

`--enable` turns on a checker that is off by default (case-insensitive).
`--checker-option` sets one option on one checker; repeat the flag for
multiple options. Both compose with everything above.

Finding candidates — the installation's own documentation is the source of
truth, and it is local, so use it:

- `<install>/doc/en/checker-enablement-and-option-defaults.html` — one giant
  table: every checker, every option, its default, per language, and whether
  the checker is enabled by default.
- `<install>/doc/en/cov_checker_ref.html` — the full checker reference. Each
  checker section describes what it detects, its options with rationale and
  false-positive implications, and code examples. This is where you find "is
  there a checker for X at all?"

Both files are multi-megabyte single-page HTML. Don't open them whole — grep
for the defect-class keyword (e.g. "uninitialized", "TOCTOU", "divide by
zero") or the checker name, or strip tags with a few lines of Python and
search the text.

## Statistical checkers: what raising aggressiveness quietly removes

Several checkers do not judge code against a fixed rule — they infer the
codebase's own conventions statistically and report *deviations* from them.
NULL_RETURNS is the canonical example: by default it reports an unchecked
dereference of a function's return value only when at least 80% of that
function's call sites check it for null (`stat_threshold`, refined by
`stat_bias` and `stat_min_checked`). CHECKED_RETURN and BAD_EQ work the same
way.

Aggressiveness levels work partly by lowering these thresholds:
NULL_RETURNS `stat_threshold` goes 80 (low) → 50 (medium) → **0 (high)**;
CHECKED_RETURN goes 80 → 55. At high, the statistics are effectively off —
every unchecked use is reported regardless of what the codebase normally does.

Two consequences for verdicts, both worth stating in the report when the
deciding checker has `stat_*` options:

- A finding that appears only at raised aggressiveness didn't come from deeper
  analysis — it came from *discarding a deliberate judgment*. Example: many C
  codebases consciously never check `malloc`, treating out-of-memory as
  unrecoverable (a crash on the null dereference is as good a response as
  any, and there may not even be memory left to report the error). Default
  NULL_RETURNS respects that convention; high aggressiveness overrides it.
  Report what was traded away, not just the extra defect.

- A one-function snippet gives the statistic almost nothing to measure — one
  or two call sites. The same defect embedded in the user's real codebase,
  where the function has many other call sites shifting the checked/unchecked
  ratio, can produce the opposite verdict at identical settings. Snippet
  verdicts for statistical checkers transfer weakly; say so.

## Interpreting "found" at any rung

Always confirm with `cov-format-errors --dir idir --emacs-style` that the
report is (a) the expected defect type, and (b) at the expected source
location, before declaring success. The event trace it prints (var_decl →
uninit_use, etc.) belongs in the final report — it shows the user exactly how
Coverity reasons about their defect.
