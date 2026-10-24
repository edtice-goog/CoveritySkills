# The reading method

A reader is an LLM (or a person) given **one lane's** bundles, that lane's
questions below, and the verdict set. It returns one verdict per finding
with the argument behind it. It reads the real source in the bundle and,
where the argument depends on code the bundle does not show (a callee the
events go through, a guard further up), it reads that too, from the same
version.

What the reader is not given: verdicts from other readers, other lanes'
questions, or anything about why the findings were selected. A verdict
stands on the code.

## The questions, by lane

### Construction

The claim is that a construct is present: something built in a way that
is disallowed whatever data reaches it.

1. **Is the construct the checker names actually there?** For an
   injection-construction checker: is the string reaching the interpreter
   call really assembled from a part that is not a compile-time constant,
   and is the call really the interpreter? Read the operand back to where
   it is built.
2. **Feasibility does not enter.** Whether attacker data can reach the
   site is a different claim; this one holds whatever data arrives. Do not
   dismiss a construction finding by arguing about callers.

Verdicts: the construct is present → `real`. It is present and the code
shows it is deliberate (a documented exception at the site) →
`intentional`. The checker misread the code and the construct is not
there (the operand is constant after all; the call is not the
interpreter) → `false positive - heuristic misfire`.

### Contract

The claim is that a call ignores a failure its callee can report, or uses
a result that can be invalid.

1. **What is the callee's contract, and where is it stated?** Its
   documentation, its header, its own code, or Coverity's model of it.
   Give the location. Statistical evidence ("checked 68 out of 71 times")
   is the analyzer's belief that the result matters, not the contract:
   read the callee.
2. **Can the callee fail, or return the invalid value, for this call?**
   With these arguments, in this state. A precondition that rules the
   failure out for this call (the argument is known to contain the
   character being searched for) is an invariant, and is argued as one.
3. **Does the caller rely on success?** It uses the result, or carries on
   as if the call worked.

Verdicts: the failure is possible for this call and the caller relies on
success → `real` (`real, low severity` when the consequence is cosmetic,
such as a log line). The failure is impossible for this call →
`false positive - global invariant`, with the precondition as the
invariant. The caller deliberately does not depend on the outcome (a
best-effort call whose failure changes nothing) → `intentional`.

### Value or path

The claim is that a value or state reaches a point, along a path, that
does not handle it.

1. **Is the path feasible?** Follow the events in order against the
   source. A branch the events take that cannot be taken in that state, or
   a value the events assume that cannot occur there, makes the path
   infeasible: a `false positive - global invariant`, argued with all
   three parts below.
2. **Is the value handled at the point?** A guard, a clamp, a defined
   behaviour for that value (a library call documented to accept NULL), a
   resource released on every exit. Handled → the finding is wrong about
   the point.
3. **Interprocedural claims depend on the callee.** If the events say a
   callee returns NULL, writes past a buffer, or keeps a resource, read
   that callee at this version before agreeing or disagreeing.

Verdicts: feasible and unhandled → `real` or `real, low severity`.
Infeasible, or handled at the point by code the analysis did not connect
→ `false positive - global invariant`, with the guard or the handling as
the located invariant. The detection is accurate and the code is
deliberate (a DEADCODE on a defensive fallback after an exhaustive
switch) → `intentional`.

## The verdict set

Use these words, in this order of preference when several could apply:

| verdict | meaning |
|---|---|
| **real** | genuine defect, would fix |
| **real, low severity** | genuine, correctly reported, unlikely to matter |
| **intentional** | detection correct, code deliberate |
| **false positive - global invariant** | path infeasible; name and locate the invariant |
| **false positive - heuristic misfire** | shape matched, no path claim, shape is correct |
| **unresolved** | could not establish either way; say so rather than guess |

### Global invariant

**The analyzer is right about the code it can see, and a fact outside
that view makes the path unreachable.** This is the most common reason a
real checker produces a wrong finding, and the category where a reasoning
reader most often beats a path-sensitive analysis: the invariant is
usually obvious to anyone who knows the program or the machine.

Two kinds, and the distinction changes what is done about it:

- **In-code invariant**: a guard the analysis did not connect. A
  `NULL_RETURNS` on `strchr(s, ':')` inside a branch reached only when
  `strncasecmp(s, "syslog:", 7) == 0`: the colon is guaranteed. Actionable:
  a model, an assertion or a code change teaches the analyzer, and the
  finding stops recurring.
- **Environment invariant**: a fact about the world, not the program. A
  loop searching for a free DMA channel can, on paper, exit with its result
  unassigned; a machine with no working DMA never finished POST, so the
  code is not running. `(int) uptime_secs` truncates a `time_t` only after
  about 68 years of uptime. These get triaged, annotated with the
  invariant, and stay triaged.

**The discipline: name it, locate it, say what would break it.** "Global
invariant" is also the easiest way to wave away a real defect, so a
dismissal is acceptable only when it is falsifiable:

1. **the invariant**, as a concrete proposition: *"this branch is only
   reached when the filename begins with `syslog:`"*;
2. **where it is enforced**: file and line for an in-code guard, the
   mechanism for an environment invariant: *"`modules/mod_log.c:1287`, the
   `strncasecmp` on the enclosing `if`"*;
3. **what would break it**: *"any new caller reaching this `else` without
   that prefix check"*.

No location, no dismissal: report `unresolved`. The records tool refuses a
global-invariant verdict without all three.

### Heuristic misfire

**The checker matched a shape, not a path, and the shape is fine.** A
COPY_PASTE_ERROR on two deliberate, distinct adjacent checks
(`child->next == child` then `child->next == head`, two different cycle
tests) involves no feasibility argument, and taking the suggested edit
would make the code worse. Dismiss by explaining the intent the shape
encodes, not by arguing reachability.

### Intentional

**The analysis is right, the code is deliberate, and the author would not
change it**: a defensive fallback after an exhaustive switch, a commented
switch fallthrough carrying shared tail work. Not a false positive, since
the detection is accurate. Where the language offers an annotation
(`/* FALLTHRU */`, an explicit default), that is the real fix.

### The burden is symmetric

An unverified confirmation is as unsound as an unverified dismissal.
Calling a finding real because the checker's interprocedural claim sounds
plausible, without reading the callee it depends on, is a verdict resting
on nothing. An OVERRUN graded real on the analyzer's claim that a callee
reads byte 27 of a 16-byte struct, with the caveat that the callee had not
been read, turned out to be a global invariant once it was read: the
callee switched on a family field set two lines earlier and copied only 16
bytes. **A caveat is not a verdict.** If the argument depends on code that
was not read, the verdict is `unresolved`, in both directions.

`unresolved` is a legitimate result, and better than a confident wrong
call. Wrongly dismissing a real defect costs more than wrongly keeping a
false one, which is why the dismissal carries the extra burden of a
location.

## What a reader returns

One verdict file per reader, in the format in `records.md`: the lane, the
method (`LLM: <model>`), the model it ran on, and per finding the merge
key, the verdict, the argument (`reason`, with `file:line` for every claim
it makes about the code), the code it read (`sites_read`), and for a
global invariant the three parts. The reason is what a person reads in
Connect's Comment field: a paragraph, not an essay.
