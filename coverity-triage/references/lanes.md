# The lanes, and assigning one

A lane is the kind of claim a finding makes. The lane decides the question
triage has to answer, and so the method that answers it. Lanes exist for
checkers that cannot say on their own how their findings should be triaged.
A checker that does say (a custom checker built to have every finding
verified, for instance) takes its own method, and its lane only labels the
finding.

Most checkers make one kind of claim, so most findings get their lane from
a **checker table**, with no model involved. Inference is spent only where a
checker's findings can make more than one kind of claim, and it chooses
among that checker's candidate lanes.

## The six lanes

| lane | the claim | the question a reader answers |
|---|---|---|
| **Construction** | the construct does the wrong thing, or something undefined, for some input it can receive, whatever input actually arrives | is the construct there? |
| **Intent** | the code is well-defined, but a pattern suggests it may not be what its author meant, and the checker cannot know what was meant | what did the author mean, and does the code do it? |
| **Contract** | a call ignores a failure its callee can report, or uses a result that can be invalid | what does the callee promise, and does the caller rely on more? |
| **Value or path** | a value or state found along a path, or data from an untrusted source, reaches a point that does not handle it | is the path feasible, and is the value handled at the point? |
| **Policy** | a match against a rule set (MISRA), a don't-call list or a configured threshold, with no claim that the code misbehaves | none. Policy is never triaged: the rule's authors decided, and a reader would only be second-guessing them |
| **Other** | not a claim about the code (PARSE_ERROR is a capture problem), or a claim no lane fits | none: no method, no verdict |

**Construction findings are real when the construct is there.** A narrowing
that is safe only while a value stays small, a sizeof that holds only while
two types happen to agree: each is wrong for part of the input it can
receive. It is never dismissed by arguing that the bad input is unlikely,
far off, or not reachable today. That argument is expensive, and it has to
be made again every time the code or its environment changes. The one
exception is code whose algorithm defines the wrap or the truncation (a
hash, a checksum, some cryptography). That code is `intentional`, with the
place that says so.

**Policy and Other both take no method.** The difference matters in the
report: Policy is decided, Other is unplaced.

## Assigning: the checker table first

`tools/lanes.py assign` reads the bundles' `index.json` and the checker
table, then writes `lanes.json`:

1. **The table.** It starts from the skill's own `checker-lanes.json` (the
   checkers whose languages include C, Coverity 2025.9.0, and eleven
   C++-only checkers). Each `--table`
   file is read after it, in order, and a later row replaces an earlier one
   for the same checker. An organization keeps its own table this way, and a
   producer of custom checkers ships the rows for its own.
2. **A fixed lane** (`"lane"`) is the finding's lane. No model runs, and the
   entry says `"assigned_by": "checker table"`.
3. **Candidate lanes** (`"lanes"`, with `"decide"`) leave the finding
   pending. Inference reads the finding's events and code and chooses one of
   those candidates, never a lane outside them.
4. **An unplaced checker** (no row in any table) leaves its findings
   pending, marked `"unplaced"`. The skill determines one row for that
   checker (*Custom checkers*), adds it to a table file, and runs `assign`
   again with that file. A checker is placed once, not once per finding.

`records.py assemble` refuses a `lanes.json` with anything still pending.

Format of the table and of `lanes.json`: `records.md`.

## Deciding a lane

These are the tests for writing a row for a checker the table does not have,
and for choosing among a row's candidates. Take the first that answers yes.

1. **Is it a claim about the code at all?** If not, **Other**. PARSE_ERROR
   reports that the compiler front end could not parse a file, which is a
   capture question for the `coverity` skill.
2. **Is the report only a match against a rule, a list or a threshold, with
   no claim that the code misbehaves?** That is **Policy**. The test: if the
   checker asserts anything that could turn out untrue (that a value is a
   secret, that a path reaches a sink), it gets triage, and it is not
   Policy. A performance finding (a copy where a move would do, a large
   parameter passed by value) is Policy even when its premise could be
   checked: the code is correct either way, so triage has no question to
   answer.
3. **Is the behaviour wrong or undefined for some input the code can
   receive, judged from types, declared sizes or the shape of a call, with
   no particular value needed?** **Construction.** This includes a construct
   that is wrong under some thread schedule (locks taken in different
   orders) and a security construct wrong under some attacker input (a
   chroot jail with no chdir).
4. **Is the behaviour well-defined, so the only question is whether the
   author meant it?** **Intent.** A switch case that falls through, two
   adjacent checks that look copied, a branch no value can reach, a value
   stored and never used: if the intent were known, the question would be
   settled.
5. **Is the claim about a callee's failure or invalid result, which the
   caller ignores or uses?** **Contract.**
6. **Does the claim rest on a value or a range found along a path, or on
   data from an untrusted source?** **Value or path.**

**Candidate lanes: the events decide.** A checker gets candidates only when
its findings really do differ. NEGATIVE_RETURNS is one example: its negative
value is sometimes a callee's return (Contract) and sometimes a variable
tested negative (Value or path). Each row says what tells its candidates
apart, and the reason for the choice names the events that decided it.

## A checker's own method

A row may carry `"method"`, the triage method the checker was built for. It
**overrides the lane's preferred method** in the plan. A row whose method is
`Execution: coverity-verify` may also carry `"route"` (`harness` or
`extraction`): the route verify should prefer for that checker, passed to
verify's router (`coverity-verify`, *Then the route*). Precedence for a
finding's method:

1. the user's choice for that finding (an override in `run.json`, with its
   reason);
2. the checker's own method (its row);
3. the lane's method in the plan.

**No lane restricts methods.** A plan may run verify on Contract findings,
or have a person read any lane. The one exception is Policy, which takes no
method at all.

## Custom checkers

Expect custom checkers (CodeXM and the like) to be common. For each one with
no row, determine a row once, before anything runs, from the best evidence
available:

- **the producer's own rows**, when it ships a table: use them, through
  `--table`;
- **the built-in checker it stands in for**: a path-insensitive version of
  a built-in checker takes that built-in's lane;
- **its description**: apply *Deciding a lane*;
- **a method it was built for**: a checker that is noisy by design, with
  many hits per real defect, is useful only with an execution step behind
  it. Its row carries that method, so every finding is verified rather than
  read.

**Interactive**, show the proposed rows and ask. **Not interactive, or unsure
which**, report the proposed rows and stop (rule 38). Either way, write the
rows to a table file the user keeps, so the next run reads them and asks
nothing.

## What inference returns

For a pending finding, inference returns the entry `lanes.py` wrote, plus
three fields:

- `lane`, one of the entry's `candidates`;
- `reason`, one sentence that names the events which decided it;
- `assigned_by`, the plan's assigner (`LLM: <model>`).

```json
{"mergeKey": "6b0b...", "checker": "NEGATIVE_RETURNS",
 "candidates": ["Contract", "Value or path"],
 "lane": "Value or path", "assigned_by": "LLM: Sonnet 5.5",
 "reason": "var_tested_neg at the caller's test: the negative value is a variable on the path, not a callee's return"}
```

"It is a NEGATIVE_RETURNS" is not a reason.

## What the assigner never does

- **Give a verdict**, or let one shape the lane ("this is clearly a false
  positive, so Other"). Other means the claim fits no lane, not that the
  claim looks wrong.
- **Pick a lane by the method it would like.** The lane comes from the
  claim; the method comes from the row or the plan.
- **Overrule the table**, or choose a lane outside a row's candidates.
- **Skip a finding.** Every bundled finding gets a lane. One whose source is
  missing still gets the lane its checker and events support, and its reader
  returns `unresolved`.

## When a reader disagrees

A reader that believes a finding belongs in another lane returns
`unresolved`, with the reason `wrong lane: <lane>`. It does not answer the
other lane's question. Re-routing is then a deliberate second pass:

- **For a checker with candidates**, run inference again on that finding.
- **For a fixed-lane checker**, the table row itself is in question. Either
  a person moves the finding (`"assigned_by": "Human"`, with the reason), or
  the row changes for every later run.

The record keeps the lane the verdict was reached in.
