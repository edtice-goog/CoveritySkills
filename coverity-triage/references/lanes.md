# The lanes, and assigning one

A lane is the kind of claim a finding makes. The lane decides the question
triage has to answer, and so the method that answers it. The assignment is
made per finding, from the checker, the events and the code, by an LLM; it
returns a lane and a one-sentence reason, and never a verdict.

## The four values

| lane | what belongs in it | example checkers |
|---|---|---|
| **Construction** | the code is built in a way the organization has chosen to disallow, whatever data reaches it | SQL_NOT_CONSTANT, LDAP_NOT_CONSTANT |
| **Contract** | a call ignores a failure its callee can report, or uses a result that can be invalid | CHECKED_RETURN, NULL_RETURNS |
| **Value or path** | a value or state reaches a point, along a path, that does not handle it | FORWARD_NULL, OVERRUN, DIVIDE_BY_ZERO, UNINIT, NEGATIVE_RETURNS, RESOURCE_LEAK, DEADCODE |
| **Other** | anything that fits none of the three. No method is invoked and no verdict is returned; the finding stays in the normal triage flow untouched | none expected |

The example column is a starting point, not a mapping to apply blind. An
organization that keeps its own table (which checkers it has enabled, and
where it wants each) hands that table to the assigner instead.

## Deciding a lane

Ask what the finding says is wrong, in the checker's own words (the main
event and the events leading to it), and take the first question that
answers yes:

1. **Does the claim hold whatever data reaches the code?** The finding
   objects to how something is built: a query or command assembled from a
   non-constant part, a call the organization has ruled out, a construct
   that is wrong whatever values it sees. **Construction.**
2. **Is the claim about a callee's failure or invalid result that the
   caller ignores or uses?** The finding names a call, and a failure or an
   invalid return the callee can produce (an error code, NULL, a negative
   count), and objects to what the caller does with it. **Contract.**
3. **Is the claim that a value or state reaches a point along a path, and
   is not handled there?** The events trace a path: a value is set or
   tested, flows, and reaches a dereference, an index, a divisor, a use, a
   function exit holding a resource, or a branch that cannot be taken.
   **Value or path.**
4. **None of these.** **Other.** That is a legitimate answer, not a
   failure: forcing a finding into a lane that does not fit gives it the
   wrong method, and a misrouted verdict looks exactly like a routed one.

**The claim decides, not the checker name.** Most checkers make one kind
of claim, and the table holds. The events can show that a particular
finding makes another: a checker whose evidence for one finding is
statistical ("checked 68 out of 71 times") is stating a belief about the
callee's contract, whatever its name. When the events point elsewhere,
follow them and say which events in the reason.

**One finding, one lane.** If a finding seems to make two claims, take the
one its main event makes. The reason says what the other claim was, so a
reader can see it.

## What the assigner returns

```json
{"mergeKey": "6b0b...", "lane": "Contract",
 "reason": "NULL_RETURNS on strchr; evidence is statistical (checked 68 of 71), so the claim is about strchr's contract at this call"}
```

The full file format is in `records.md`. The reason is one sentence and
names the evidence; "it is a NULL_RETURNS" is not a reason.

## What the assigner never does

- **Give a verdict**, or let one shape the lane ("this is clearly a false
  positive, so Other"). Other means the kind of claim fits no lane, not
  that the claim looks wrong.
- **Pick a lane by the method it would like.** The lane comes from the
  claim; the method comes from the plan for that lane.
- **Skip a finding.** Every bundled finding gets a lane; one the assigner
  cannot read (a bundle with its source unavailable) still gets the lane
  its checker and events support, and the reader will return `unresolved`.

## When a reader disagrees

A reader in a lane that believes the finding belongs elsewhere returns
`unresolved` with the reason `wrong lane: <lane>`. It does not answer the
other lane's question. Re-routing is then a deliberate second pass: assign
those findings again (or move them by hand, with the reason), and run the
new lane's method on them. The record keeps the lane the verdict was
reached in.
