# Triage vocabulary: saying why a finding is wrong

A false positive is rarely a *mistake* by the analyzer. Far more often the
analysis is locally correct and something it could not see makes the reported
path impossible. Triage is worth little if it cannot say precisely which, so
use these terms consistently and make every dismissal falsifiable.

## Global invariant

**The analyzer is right about the code it can see, and a fact outside that view
makes the path unreachable.** This is the most common reason a real checker
produces a wrong finding, and the category where a reasoning model reliably
beats static analysis -- the invariant is usually obvious to anyone who knows
the program or the machine, and invisible to a path-sensitive analysis.

Two kinds, and the distinction changes what you do about it.

### In-code invariant: a guard the analysis did not connect

The fact is present in the source, just not linked to the reported path.

```c
if (strncasecmp(lf->lf_filename, "syslog:", 7) != 0) {
  ...
} else {
  char *tmp = strchr(lf->lf_filename, ':');   /* NULL_RETURNS reported here */
  lf->lf_syslog_level = pr_log_str2sysloglevel(++tmp);
```

`strchr` genuinely can return NULL, and the checker's evidence is statistical
(`checked 68 out of 71 times`). But this branch is reached only when the string
begins with `"syslog:"`, so the colon is guaranteed. The path is infeasible.

Because the invariant is in the code, it is *actionable*: a model, an
assertion, or a code change can teach the analyzer about it, and the finding
stops recurring.

### Environment invariant: a fact about the world, not the program

The constraint lives outside the source entirely, so no amount of analysis
could find it.

- A loop searching for a free DMA channel can, on paper, exit with the result
  variable never assigned. It cannot in practice: a machine with no working
  DMA would not have finished POST, so the code is not running at all.
- `(int) uptime_secs` truncates a `time_t`. Overflow requires ~68 years of
  continuous process uptime.

These are not fixable by better analysis. They get triaged, annotated with the
invariant, and stay triaged.

## The discipline: name it, locate it, and say what would break it

"Global invariant" is also the easiest way to wave away a real defect, so a
dismissal is only acceptable when it is falsifiable. State three things:

1. **The invariant** -- as a concrete proposition, not a feeling.
   *"This branch is only reached when the filename begins with `syslog:`."*
2. **Where it is enforced** -- file and line for an in-code guard; the
   mechanism for an environment invariant.
   *"`modules/mod_log.c:1287`, the `strncasecmp` on the enclosing `if`."*
3. **What would break it** -- the change that would make the defect real.
   *"Any new caller reaching this `else` without that prefix check."*

If you cannot point at where the invariant is enforced, you do not have an
invariant, you have a hope. Report the finding as unresolved instead.

The asymmetry is deliberate: wrongly dismissing a real defect is far more
costly than wrongly keeping a false one, so the burden of proof sits on the
dismissal.

## Heuristic misfire

**The checker matched a shape, not a path, and the shape is fine.** No
feasibility argument is involved, so a global-invariant explanation would be
the wrong words entirely.

```c
if (child->next == child) problem("child->next == child (cycle)");
if (child->next == head)  problem("child->next == head (cycle)");
```

COPY_PASTE_ERROR suggests the second `child` "should be head". It should not:
these are two deliberate, distinct cycle checks, and the suggested edit would
produce `head->next == head`, which is strictly worse. The checker
pattern-matched adjacent similar lines.

Dismiss by explaining the intent the shape encodes, not by arguing
reachability.

## Intentional code

**The analysis is right, the code is deliberate, and the author would not
change it.** Defensive fallbacks after exhaustive switches; a deliberate
switch fallthrough carrying shared tail work. These are not false positives --
the detection is accurate -- and the honest classification is *intentional*,
not *false positive*. Where the language offers one, an annotation
(`/* FALLTHRU */`, an explicit default) is the real fix.

## The verdict set

Use these words, in this order of preference when several could apply:

| verdict | meaning |
|---|---|
| **real** | genuine defect, would fix |
| **real, low severity** | genuine, correctly reported, unlikely to matter |
| **intentional** | detection correct, code deliberate |
| **false positive - global invariant** | path infeasible; name and locate the invariant |
| **false positive - heuristic misfire** | shape matched, no path claim, shape is correct |
| **unresolved** | could not establish either way -- say so rather than guess |

`unresolved` is a legitimate result and much better than a confident wrong
call. Prefer it whenever the argument depends on code you did not read.

**The burden is symmetric.** It is tempting to apply the discipline only to
dismissals, since those are what hide real defects -- but an unverified
*confirmation* is exactly as unsound. Calling a finding real because the
checker's interprocedural claim sounds plausible, without reading the callee it
depends on, produces a true-positive verdict resting on nothing.

This happened in the proftpd audit. An OVERRUN was graded a true positive on
Coverity's claim that a callee accessed byte 27 of a 16-byte struct, with a
noted caveat that the callee had not been read. Reading it later showed the
function switches on a family field set two lines earlier, copies only 16
bytes, and the finding is a global invariant false positive. **A caveat is not
a verdict.** If the argument depends on code you have not read, the verdict is
`unresolved` -- in both directions.

## For demo data specifically

A finding correctly dismissed as a global invariant is still a **bad demo
item**, even though the dataset is fine. Explaining why a defect is not a
defect is not a story anyone wants told on stage, and an audience that has to
follow an invariant argument is being asked to take the tool on faith. Keep
these in the dataset; keep them off the screen. See the legibility rule in
`selection.md`.
