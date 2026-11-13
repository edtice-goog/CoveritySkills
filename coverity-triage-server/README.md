# coverity-triage-server

Part of [CoveritySkills](../README.md). **It needs
[coverity-triage](../coverity-triage/README.md) beside it**: its lanes,
checker table and reading rules are that skill's, in
`coverity-triage/references/`. Copy or clone the whole repository, not
this folder alone:

```bash
git clone https://github.com/edtice-goog/CoveritySkills
```

Triage of a Coverity finding from inside a service that holds the
findings, the source of the files that carry them, and Coverity's derived
models, with no source tree, no build and no way to run the code. It is
the server-initiated counterpart of `coverity-triage`, which a person runs
where the tree and execution are at hand.

For each finding it gives:

- **the lane**, from the same checker table;
- **the triage method**, from the checker's row or the service's plan;
- **a reading**, when the method is a reading: the verdict, the
  recommended action and a comment ending with what was triaged.

**When the method is execution, it stops** after the lane and the method,
and renders no verdict. A verdict that would rest on code the service does
not hold, most often the callers behind a dismissal, comes out
`unresolved`, naming that code.

## Layout

```
coverity-triage-server/
├── SKILL.md          # the procedure: lane, method, reading, answer
├── README.md
└── CALIBRATION.md    # what has run, and what has not
```

## Requirements

- `coverity-triage` beside it, for `references/`.
- What the service supplies: the finding and its events, the source it
  stores, and the derived models of the callees the events name.
