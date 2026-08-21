---
name: coverity-defect-detectability
description: >
  Determine empirically whether Coverity static analysis can detect a specific
  defect in given code, and find the minimal configuration (checker,
  aggressiveness level, checker option) that reports it. Use this skill whenever
  the user asks "can Coverity find this?", "why didn't Coverity report this?",
  or "which checker catches this?"; shows a code snippet with a known or
  suspected defect in a Coverity context; compares Coverity against another
  static-analysis tool's finding; or wants to reproduce a defect that Coverity
  missed. Requires a local Coverity Analysis installation — this skill runs real
  cov-emit/cov-analyze test runs rather than reasoning theoretically about what
  Coverity might do.
---

# Coverity Defect Detectability

Answer "Can Coverity find this defect?" with evidence: capture the code into an
intermediate directory, run `cov-analyze` with progressively more aggressive
settings until the defect is reported (or the escalation ladder is exhausted),
then narrow back down to the *minimal* setting that triggers detection. The
deliverable is a verdict backed by actual analysis runs, plus the exact command
line the user can rerun to reproduce it.

The audience has Coverity installed and wants an empirical answer, not a
literature review. Do not speculate about whether a checker "should" fire —
run it and see.

Calibrate effort to the question. Most queries are small synthetic snippets —
often from static-analysis test suites — where the defect is plain to see by
reading the code. The user isn't asking what the bug is; they're asking
whether *Coverity* reports it, and with what configuration. Take the fastest
path to an empirical answer: capture, run defaults, escalate only while the
answer is still "not found". Save deeper experiments for when the verdict is
surprising, contested, or needs to transfer to real code (see Step 4b).

## Step 0: Locate the Coverity installation

Ask the user for the installation path if it isn't already known (check project
notes / CLAUDE.md / memory first — it may have been recorded from a previous
session). Do not go hunting across the filesystem: installations are large,
live in nonstandard places, and a disk scan wastes minutes answering a question
the user can answer in seconds.

Cheap checks that are fine to try before asking: `cov-analyze` already on PATH,
or an obvious root like `C:\Coverity\cov-analysis-*` or `/opt/coverity*`.
Confirm whatever you find actually works by running `cov-analyze --help`
(first ~5 lines) before relying on it.

Below, `$BIN` means `<install>/bin`. All Coverity tools referenced here live in
that directory.

## Step 1: Pin down the target defect

Before running anything, be precise about what "found" would mean:

- What kind of defect is it (uninitialized read, null dereference, resource
  leak, buffer overrun, use-after-free, ...)?
- Which line(s) should be flagged?
- Which Coverity checker(s) plausibly cover it (UNINIT, FORWARD_NULL,
  NULL_RETURNS, RESOURCE_LEAK, USE_AFTER_FREE, OVERRUN, ...)?

This matters because an analysis run can report *incidental* defects. Only a
report of the expected type at the expected location counts as success — state
the target before the first run so you don't fool yourself later.

If the user supplied code but never said what the defect is, analyze the code
yourself first and confirm your reading with them before burning analysis runs.

**When the planted defect isn't quite a defect.** Synthetic test files are
often written by authors who don't fully understand the vulnerability class
they're planting: code that hashes a string *literal* instead of a secret
(intending a sensitive-data leak), or that pattern-matches a `1==1` payload
without ever executing injectable SQL. When the claimed defect and the actual
code diverge, don't force a found/not-found verdict onto the claim. Answer in
three parts: what the code as written actually contains (and what Coverity
reports on that — sometimes a checker like weak-crypto still fires, making
the test "pass" for a reason the author didn't intend); what the author most
likely meant to plant; and how Coverity reports the intended defect in a
corrected version, which you can write and test in minutes. Keep the tone
gentle and matter-of-fact — the asker may be the test's author, or may be
scoring tools with it, and the report should educate without embarrassing
anyone.

Some questions are inventory-shaped — "what does Coverity find in this file?"
rather than "can it find this one defect?" For those, still enumerate the
defects you can see by reading (that list becomes the scorecard), but treat a
broad sweep (`--security --aggressiveness-level high`, or `--all` at high) as
a first-class step rather than a last rung: it can surface defects neither you
nor the user spotted by eye — a format-string vulnerability sitting quietly
next to a loud `gets()`, for instance. Anything the sweep finds beyond your
list gets added to the scorecard and minimized like the rest.

## Step 2: Capture the code

Work in a scratch directory (copy the source there; the intermediate directory
and result files land next to it). For a self-contained C/C++ file, skip
compilers and build systems entirely:

```
$BIN/cov-emit --dir idir main.c
```

No `cov-configure`, no `cov-build`, no compiler required. One caveat: cov-emit
parses files in C++ mode by default, even `.c` files — add `--c` when
C-specific semantics could matter to the defect.

If the code is *not* self-contained (missing headers, snippet of a larger
function, references to undefined functions), read
[references/capture.md](references/capture.md) before editing it into shape.
Careless stubbing can silently destroy or fabricate the defect you are testing
for — that file explains how to stub safely, and when to fall back to
`cov-configure` + `cov-build` with a real compiler.

## Step 3: Run the escalation ladder

Run the rungs in order until the target defect appears. Reuse the same
intermediate directory throughout — each `cov-analyze` run replaces the
previous results, and re-analysis of a small snippet takes seconds, so rungs
are cheap.

After every run, inspect what was found:

```
$BIN/cov-format-errors --dir idir --emacs-style
```

| Rung | Command | What it adds |
|------|---------|--------------|
| 1 | `$BIN/cov-analyze --dir idir`, then `... --recommended-security-checkers`; **security-class defect → also `... --security` now** | The "out of the box" baselines (bare defaults, Coverity CLI / Polaris default) — plus the C/C++ security set up front when the target defect is security-natured, because without `--security` a security defect is a near-certain miss |
| 2 | `... --aggressiveness-level medium`, then `high` | Flips documented sets of checker options toward more reporting |
| 3 | `... --aggressiveness-level high --all` | Enables almost all checkers that are off by default (concurrency, parse warnings, more) |
| 4 | `... --enable-audit-checkers` | Audit-mode security checkers (for security-flavored defects) |
| 5 | Targeted `--enable <CHECKER>` and `--checker-option <CHECKER>:<option>:<value>` | Anything the docs say covers this defect class but isn't on yet |

Rung details, false-positive tradeoffs, and how to pick rung-5 candidates are
in [references/escalation.md](references/escalation.md).

If the ladder is exhausted and the defect never appeared, don't stop at a bare
"no". Sanity-check by simplifying the code — e.g., make an interprocedural
defect intraprocedural — and rerun. If the simplified version *is* detected,
the honest verdict is "the checker exists but can't see through this code
structure", which is far more useful to the user than "not found". If even the
simplified version isn't detected, your checker mapping from Step 1 was
probably wrong — revisit it.

## Step 4: Minimize — identify the exact trigger

If the defect only appeared at an elevated rung, do not report "use high
aggressiveness" and call it done. Aggressiveness levels are just bundles of
checker-option flips, and the user can usually enable the *one* option that
matters:

1. `cov-analyze --help` contains tables listing exactly which checker options
   each aggressiveness step changes (low→medium and medium→high).
2. The install's own docs give per-checker option semantics and defaults:
   - `<install>/doc/en/checker-enablement-and-option-defaults.html` — every
     checker's options and defaults, per language
   - `<install>/doc/en/cov_checker_ref.html` — full checker reference,
     including why options are off by default and their false-positive cost
   These are large single-page HTML files; grep them or strip tags with a
   short Python script rather than reading them whole.
3. Test candidate options one at a time at *default* aggressiveness:
   `cov-analyze --dir idir --checker-option UNINIT:enable_write_context:true`

The point: "enable `UNINIT:enable_write_context`" is an actionable production
config change with a known, bounded false-positive cost. "Run at high
aggressiveness" (roughly 70% more false positives across all checkers) usually
is not.

## Step 4b: Check that the verdict transfers to the real code

Test snippets are usually simplified stand-ins for real software. Two things
commonly break the transfer from snippet to reality:

- **Constant guards.** Simplified repros often replace a runtime decision with
  a constant (`static int b = 0;` guarding the interesting path). The analysis
  may constant-fold what the real program decides at runtime — in either
  direction. If the snippet has this artifact, rerun once with the constant
  replaced by an opaque condition (a call to a declared-but-undefined
  `extern int config(void);`) and confirm the verdict holds. One extra run
  turns "works on the toy file" into an answer the user can rely on.

- **Statistical checkers.** Checkers like NULL_RETURNS and CHECKED_RETURN
  judge findings against how the *rest of the codebase* behaves; a
  one-function snippet gives that statistic almost nothing to work with, and
  raising aggressiveness partly works by discarding it. If the deciding
  checker has `stat_*` options, read the statistical-checkers section of
  [references/escalation.md](references/escalation.md) and carry its caveats
  into the report.

## Step 5: Report the verdict

Use this structure:

```
## Verdict: [DETECTED by default | DETECTED with configuration | NOT DETECTED]

**Checker:** <name> (<defect type string from the report>)
**Minimal configuration:** <exact cov-analyze command line>
**Defect trace:** <the event sequence from cov-format-errors>
**Why defaults miss it:** <explanation grounded in the checker docs>
**Tradeoffs:** <false-positive implications of enabling this in production>
**Reproduce:**
<full command sequence from cov-emit through cov-format-errors>
```

For NOT DETECTED, replace the middle sections with: the nearest relevant
checker, what the simplification experiment showed, and why the structure
defeats the analysis. Classify the miss in standard terms — most NOT DETECTED
verdicts are **application logic defects**: the code faithfully implements a
wrong rule, and the oracle that defines "wrong" (a spec, a pricing document,
a requirements sentence) exists only outside the codebase. Naming the
category tells the reader this is a boundary of static analysis as a
technique, not a Coverity gap.

On custom checkers (CodeXM): mentioning them as an option, with honest
tradeoffs, is fine. Writing one that encodes the *application's spec* as part
of the verdict is not — resist the temptation even though you could. A
working demo reads as "the tool can find this," when what actually found the
defect was you reading the specification; the checker detects one hand-coded
instance, not the defect class, and could only be written by someone who
already knew the answer. The demonstration misleads precisely because it
works.

Ordering matters for readability: lead with what happened on the code
*exactly as given* — the defect trace, or the explicit list of configurations
that reported nothing. Results from variants, stubs, or side experiments come
after, clearly labeled as such. The reader must never have to wonder whether
a printed trace came from the original code or from one of your experiments.

Proportionality: the report's length should track the verdict's complexity,
not the effort spent. A defect found at defaults or with one flag deserves a
short report — verdict, command, annotated trace, one paragraph of why —
because a long report of a simple "yes" buries the answer. Save the full
experiment matrix for verdicts that are contested, surprising, or genuinely
conditional; even then it belongs in a supporting file, not the narrative.

Present traces as annotated code, not tool dumps. Show the relevant source
lines with the checker's events beside them:

```c
int *buf = malloc(n * sizeof(int));   /* 1. alloc_fn: storage from malloc */
if (f == NULL) {
    return -1;                        /* 4. leaked_storage: buf leaks */
}
```

Raw `--emacs-style` output reads like a wall of compiler errors to most
readers, and raw JSON exports are worse — neither belongs in the report body.
Keep supporting artifacts consistent across runs: next to verdict.md, save
the human-readable `cov-format-errors` text for the configuration the verdict
quotes. Don't save raw JSON as primary evidence.

Register and tone — these reports travel. The person who asked is often not
the author of the code, and the verdict may be forwarded into an RFP
response, a support ticket, or an internal thread:

- Write formally about "the file" / "the code under analysis", not "your
  code" or "your bug".
- Report on the tool's behavior, never on people ("default settings do not
  enable this checker", not "your colleague is wrong").
- Stay in your lane on severity: the question answered is *detectability*.
  Ranking one defect as more dangerous than another, or assessing real-world
  exploitability, depends on deployment context the report doesn't have —
  offer at most a hedged note, or leave severity to the reader.

## Worked example

[references/worked-example-uninit.md](references/worked-example-uninit.md) —
a complete real session: an interprocedural possibly-uninitialized read that
default analysis misses, walked from capture through minimization to the
single checker option (`UNINIT:enable_write_context`) that detects it.

## Other languages

The escalation workflow (Steps 3-5) is language-independent; capture is not.
For C# questions, read [references/csharp.md](references/csharp.md) —
verified capture procedure (including the `cov-configure --cs` and
shared-compilation gotchas that otherwise produce a silent empty capture) and
a worked multi-defect example. Other languages (Java, JavaScript, ...) are
not yet covered — apply the same principles: prove the code compiles with the
real toolchain, prefer build capture whenever a "not found" verdict is on the
line, and never let capture doubt leak into a detectability verdict.
