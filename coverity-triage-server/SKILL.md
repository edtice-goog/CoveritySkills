---
name: coverity-triage-server
description: >
  Triage one Coverity finding, or a selection, from inside a service that
  holds the analyzed findings, the source of the files that carry them, and
  Coverity's derived models of the functions the analysis saw, but has no
  source tree, no build and no way to run the code. It gives each finding
  the lane and the triage method coverity-triage would give it, from the
  same checker table, and a reading when the method is a reading: a
  verdict, a recommended action and a comment that ends with what was
  triaged. When the method is execution it stops after the lane and the
  method, and renders no verdict. Use this skill for a service's
  "interpret this finding" request, "triage this CID on the server", "what
  lane and method does this finding take", and any triage where the
  evidence is the event trace, the stored source and the derived models.
  For triage where the whole tree is at hand, or that needs execution, use
  coverity-triage.
---

# Coverity triage, server-initiated

**This skill is part of the CoveritySkills repository.** It needs
`coverity-triage` beside it: the lanes, the checker table and the reading
rules live there, in `coverity-triage/references/`, and this skill uses
them as they are. If you have only this file, clone the repository and
work from the clone:

```bash
git clone https://github.com/edtice-goog/CoveritySkills
```

## What it is for

A service keeps a stream's findings, the source of the files they are in,
and the derived models the analysis built. A person asks it to interpret a
finding. This skill is what the service runs for that request. Its
counterpart, `coverity-triage`, is run by a person where the whole tree,
the build and execution are at hand; both triage by the same lanes, table
and reading rules, so their answers mean the same thing.

## The evidence

- the finding: checker, events, main site, merge key;
- the source the service holds, which is often not every file;
- Coverity's derived models of the callees the events name.

That is all. There is no source tree, no build and no execution.

## Step 1: The lane

From the checker table, `coverity-triage/references/checker-lanes.json`,
then any table the service keeps, a later row replacing an earlier one
(`coverity-triage/references/lanes.md`). A finding whose main event is in a
compiler's own headers is lane Other and Intentional, by rule. A checker
whose row lists candidate lanes gets one chosen from the events, by the
row's `decide`. A checker with no row is placed by the tests in
*Deciding a lane*.

## Step 2: The method

The checker's own method from its row, else the method the service's plan
gives the lane. A plan starts from the recommendation per lane,
`coverity-triage/references/lane-methods.json`, in which Value or path
takes execution. Policy and Other take none.

**If the method is `Execution: coverity-verify`, record the lane and the
method, and stop.** No verdict, no action, no comment: the claim is settled
by running the code, which happens elsewhere. Only when the person asking
chooses a reading in lieu of execution does a reading run, and the answer
says it was read in lieu of execution, with their reason
(`coverity-triage/references/lanes.md`).

## Step 3: The reading

Read with `coverity-triage/references/reading.md`: the lane's questions,
the verdict set and its discipline, the recommended action, and *Reading a
callee's model*. The models stand in for the callees' bodies; the stored
source shows the function itself.

**A verdict that would rest on code the service does not hold is
`unresolved`**, and its reason names that code. The commonest case is a
dismissal whose guard is in the callers: the callers are not in the
evidence, and no model describes them.

## The answer

Per finding, in the field names of `coverity-triage`'s records
(`coverity-triage/references/records.md`):

- the lane, its reason, and what assigned it (the checker table, the
  inference model, or the compiler-header rule);
- the method;
- for a reading: the verdict, the action with its reason when it is not
  the verdict's default, and the comment in *The comment*'s form, ending
  with `Triaged against <project> <version> from <date>.`, the version
  and its date being the snapshot's.

It answers about the finding it was given, and nothing else. How the
answer is stored, and who it is recorded as coming from, are the service's.

## Cost

Each reading costs model time. A person's request for one finding is the
decision to spend it. A request over many findings gives the count, and
the readings run only once someone agrees to it, as `coverity-triage`'s
*Cost* section says.

## What it does not do

- **Run the code.** An execution method stops it after Step 2.
- **Read what it was not given.** Code outside the stored source makes the
  verdict `unresolved`, never an assumption.
- **Bundle, chain releases, write a records file or apply one.** Those are
  `coverity-triage`'s.

## Layout

```
coverity-triage-server/
├── SKILL.md          # this file
├── README.md
└── CALIBRATION.md    # what has run, and what has not
```
