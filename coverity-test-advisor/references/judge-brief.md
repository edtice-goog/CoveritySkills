# Test Advisor judge brief (v1)

The instructions for Step 5 of [SKILL.md](../SKILL.md): the functions the
fixed rules could not settle. Distilled from three judging rounds on
jansson (C, gcov) and jackson-core (Java, JaCoCo), 415 verdicts. Cite this
file's version as `prompt_version` in every verdict.

## The question

Every function here is affected by the change: its own code changed, or it
calls a function whose Coverity derived model changed. The fixed rules
already handled the clear cases. What is left is: **do the tests exercise
the behaviour that changed, through this function?** Not whether its lines
ran.

## Inputs

- **The evidence packet** per function: why it is affected (its diff, or
  the call sites of changed callees and each callee's model delta), the
  target lines, and its source with coverage. A condensed view per batch,
  with each root change shown once, is easier to read when a batch shares
  callees.
- **The source tree and its tests** at the head commit. Search the tests
  (by error message, method name, input or feature flag) rather than
  reading whole files. You may write a small probe against the built code,
  in a scratch folder, to confirm a behaviour; list it in `sources_read`.

## What to look for

- **New branches in a root change:** a new error case, return value or
  exception. Did its new lines run? Can this function reach them? Is its
  handling of the new result exercised?
- **Duplicated implementations:** a fix that lands in several
  near-identical places (parser variants, platform back ends) but is
  tested in only some. Functions in the untested variants are WEAK. This
  is the most valuable finding.
- **Overrides and virtual calls:** a call through a base type reaches every
  override; for each override that changed, ask whether a test runs this
  caller with that implementation.
- **Delegates and wrappers:** a forwarder that adds no logic follows its
  root: SUFFICIENT if the root's new behaviour is exercised through the
  wrapper or the wrapper cannot change it, WEAK if not. Mark every
  function the gap is reachable through; the report groups them by
  location.
- **Tests that only check existence:** a test that checks by reflection
  that a method exists, or only asserts rejection when the change also
  added an accept path.

## Reading coverage

- **gcov** counts a line when it is entered: a 0 means it never ran.
- **JaCoCo** counts a line only when a probe after it runs, so:
  - a line whose call throws reads 0 although it ran;
  - so does the line after it (`return null; // never gets here`), and a
    method whose first statement is such a call;
  - a `throw` statement's 0 is real.

  When the guarding `if` shows every branch taken and the call line reads
  0, the call ran and threw. When a branch is missing, the line was not
  reached. When the line is entered by a jump (an `else`, a `case`, code
  after `break`), search the tests. JaCoCo has no counts and gives
  branches only as per-line totals.

## Verdicts

| verdict | when | needs |
|---|---|---|
| SUFFICIENT | a test exercises the changed behaviour through this function | the concrete reason; name the test if found |
| WEAK | tests reach the function, but a specific changed behaviour reachable through it is not exercised | `uncovered`, `suggested_test` |
| INSUFFICIENT | a line carrying the change is never reached by any test (you searched) | `uncovered`, `suggested_test`, the search done |
| UNTESTED | nothing reaches the function at all | `uncovered`, `suggested_test` |
| UNREACHABLE_HERE | the code cannot run in this module: no caller, or every subclass here overrides it | the evidence; it is reported, not a defect |
| UNKNOWN | the evidence is not enough | what is missing |

Never WEAK for "could test more": name the behaviour and the lines.

## Output

One entry per function, keyed by its id (the values here are made up):

```json
{"verdict": "WEAK",
 "reason": "1-3 specific sentences: lines, behaviour, which tests reach it and why they miss it",
 "line": 212,
 "uncovered": ["config.c:212: the branch taken when open_file returns NULL never ran"],
 "suggested_test": "a test anyone can write from this sentence alone",
 "model": "<your exact model id>",
 "prompt_version": "judge-brief v1",
 "sources_read": ["the packet or view", "every test file, search or probe used for this verdict"]}
```

The reason, `uncovered` and the suggested test become the defect's event
text: write them for a developer who has not seen the evidence. No
internal shorthand, no coverage jargon beyond what the sentence needs.
