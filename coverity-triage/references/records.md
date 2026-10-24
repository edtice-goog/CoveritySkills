# The files, and the records

Four inputs to `tools/records.py assemble`, one output. All JSON is UTF-8.
Every finding is identified by its **merge key**; CIDs are labels local to
one Connect database and appear nowhere in these files (rule 27).

```
<out>/
├── NNN-CHECKER.md, INDEX.md, index.json    # tools/bundle.py
├── run.json                                # the plan: written before any method runs
├── lanes.json                              # the assignment
├── verdicts/<lane>-<n>.json                # one per reader batch (or per verify run)
├── triage.json                             # tools/records.py assemble
└── TRIAGE-REPORT.md                        # tools/records.py assemble
```

## `run.json`: the plan

Written when the plan is fixed, before any lane method runs, so the plan
that was agreed is the plan on record.

```json
{
 "date": "2026-10-24",
 "selection": "per-checker sample of 2, plus 1 named merge key",
 "assigner": "LLM: Sonnet 5.5",
 "lanes": {"Construction": "LLM: Opus 5.5",
           "Contract": "LLM: Sonnet 5.5",
           "Value or path": "Execution: coverity-verify"},
 "who": "4 local subagents in Claude Code",
 "connect_ai_triage": false,
 "expected": {"by": "coverity-pathout", "lane": "Value or path",
              "method": "Execution: coverity-verify"},
 "overrides": [
  {"mergeKey": "9c1d...", "method": "Execution: coverity-verify",
   "reason": "assigned Contract; user chose to run it anyway"},
  {"mergeKey": "41aa...", "method": "None",
   "reason": "assigned Other; user chose to leave it untriaged"}
 ]
}
```

- `lanes` names the method for each of the three method lanes. A lane left
  out of the plan has `"None"`. Other is never listed: it is always `None`.
- A method is one of `LLM: <model>`, `Execution: coverity-verify`,
  `Human`, `None`. `<model>` is the model's display name (`Opus 5.5`,
  `Sonnet 5.5`, `Haiku 5.5`).
- `who` says who and where, in words; `connect_ai_triage` is `false`
  because this skill never uses it.
- `expected` (optional) is the lane and method the calling skill built its
  findings for. Findings assigned elsewhere are reported to the user before
  any method runs.
- `overrides` (optional) are the user's per-finding choices for those
  findings, or for any other: a method from the four forms and the reason.
  An override is the only way a finding takes a method other than its
  lane's, and the only way a finding in Other gets one. `Execution:
  coverity-verify` is allowed on any lane's finding through an override;
  verify then decides for itself whether the claim is one it can run.

## `lanes.json`: the assignment

```json
{
 "assigned_by": "LLM: Sonnet 5.5",
 "lanes": [
  {"mergeKey": "6b0b0c...", "lane": "Contract",
   "reason": "NULL_RETURNS on strchr; evidence is statistical (checked 68 of 71)"}
 ]
}
```

Every finding in `index.json` appears exactly once. `lane` is one of
`Construction`, `Contract`, `Value or path`, `Other`.

## `verdicts/*.json`: one per reader batch

```json
{
 "lane": "Contract",
 "method": "LLM: Sonnet 5.5",
 "model": "claude-sonnet-5-5",
 "verdicts": [
  {"mergeKey": "6b0b0c...",
   "verdict": "false positive - global invariant",
   "reason": "The else branch is reached only when the filename begins with \"syslog:\" (modules/mod_log.c:1287), so strchr(..., ':') cannot return NULL at modules/mod_log.c:1324.",
   "invariant": "this branch is reached only when lf_filename begins with \"syslog:\"",
   "enforced_at": "modules/mod_log.c:1287",
   "breaks_if": "a new caller reaches the else branch without the prefix check",
   "sites_read": ["modules/mod_log.c:1275-1330"],
   "executed": false}
 ]
}
```

| field | rule |
|---|---|
| `lane`, `method` | the lane the findings were assigned to, and the method exactly as `run.json` names it for that lane, or as each finding's override names it. A file holds findings of one lane and one method |
| `model` | the model id the reader actually ran on, as it reports it |
| `verdict` | a word from the verdict set (`reading.md`) |
| `reason` | required; the argument, with `file:line` for each claim about the code. A reader that thinks the lane is wrong uses `unresolved` and starts the reason with `wrong lane: <lane>` |
| `invariant`, `enforced_at`, `breaks_if` | required, non-empty, for `false positive - global invariant`; ignored otherwise |
| `sites_read` | the code read, as `path:line` or `path:first-last` |
| `executed` | `true` only when the verdict rests on running the code (the execution method) |

A finding in a lane whose method is `Human` may have no verdict yet; its
record says it is awaiting a person. A later verdict file from that person
(method `Human`) completes it.

## From `coverity-verify` to a verdict

The execution method reports a tier per finding (`coverity-verify`, Step 4).
Translate it into the verdict set before writing the verdict file:

| verify's tier | verdict |
|---|---|
| *confirmed by crash under model stubs*, with every stub behaviour the crash relied on checked against the real callee | `real` |
| *confirmed by crash under model stubs*, with a relied-on behaviour not yet checked against the real callee | `unresolved`: the confirmation rests on a model of the callee |
| *refuted by execution*; *refuted by execution, a path the analyzer missed* | `false positive - global invariant`: the claim that held as the invariant, the line and the reach count under the budget as `enforced_at` |
| *model says impossible* | `false positive - global invariant`: no callee model on the path produces the bad value; the models are `enforced_at` |
| *model over-approximates the callee*; *model gap* | `false positive - global invariant`: what the real callee does, and where in its code, as `enforced_at` |
| *refuted by reading* | `false positive - global invariant` with the guard's location, marked `executed: false` |
| *parameter-, global-, hook-sourced*; *unconfirmed after N seconds*; *not a fuzz-triage candidate* | `unresolved`, with verify's tier as the reason |

Every case needs `breaks_if` too: the change that would make the claim
reachable. Mark the verdict `executed: true` except where noted, and put the
tier and the reach count or crash evidence in `reason`. A *bycatch* is not a
verdict on the finding; mention it in `reason` so a person sees it.

## `triage.json`: the records

```json
{
 "format": "coverity-triage-records",
 "schema": 1,
 "run": { ...run.json..., "assigned_by": "LLM: Sonnet 5.5",
          "source": {"issues": "v1.3.9.json", "git_repo": "...", "tag": "v1.3.9",
                     "strip_prefix": "/home/me/proftpd"} },
 "records": [
  {"mergeKey": "6b0b0c...",
   "checker": "NULL_RETURNS",
   "judged": {"tag": "v1.3.9",
              "sites": [{"file": "modules/mod_log.c", "line": 1324, "function": "log_openfile"}]},
   "lane": "Contract",
   "lane_reason": "NULL_RETURNS on strchr; evidence is statistical (checked 68 of 71)",
   "method": "LLM: Sonnet 5.5",
   "verdict": "false positive - global invariant",
   "triageState": {"classification": "False Positive", "action": "Ignore",
                   "severity": null,
                   "comment": "False positive (global invariant): The else branch ...\n[coverity-triage 2026-10-24] Lane: Contract (assigned by LLM: Sonnet 5.5). Method: LLM: Sonnet 5.5, read, not executed.",
                   "customTriage": {"Triage lane": "Contract",
                                    "Triage method": "LLM: Sonnet 5.5"}},
   "evidence": {"reason": "...", "invariant": "...", "enforced_at": "...", "breaks_if": "...",
                "sites_read": ["..."], "executed": false, "model": "claude-sonnet-5-5",
                "bundle": "013-NULL_RETURNS.md"}}
 ]
}
```

- **`triageState`** uses the attribute names of Connect's triage-store
  export: `classification`, `action`, `severity`, `comment`, and
  `customTriage` for custom attributes. **`null` means leave that
  attribute alone** on the target.
- **`judged.sites`** lists every site the merge key was reported at in
  this version. A merge key does not depend on the file, so copy-pasted
  code in two files can share one key; a verdict on it covers all of them,
  and the reader is shown all of them.
- **`evidence`** is for people and is never applied.
- **`method_reason`** appears on a record whose method came from an
  override, and carries the user's reason.

### The mapping

| verdict | classification | action | severity |
|---|---|---|---|
| `real` | Bug | Fix Required | null |
| `real, low severity` | Bug | Fix Required | Minor |
| `intentional` | Intentional | Ignore | null |
| `false positive - global invariant` | False Positive | Ignore | null |
| `false positive - heuristic misfire` | False Positive | Ignore | null |
| `unresolved`; Other; method `None`; awaiting a person | null | null | null |

The comment is set on every record that has a verdict, `unresolved`
included, so the argument reaches whoever opens the finding. A record with
no verdict (Other, `None`, awaiting a person) sets only the two custom
attributes.

### The comment

```
<Label>: <reason>
[coverity-triage <date>] Lane: <lane> (assigned by <assigner>). Method: <method>, <read, not executed | executed>.
```

with `<Label>` one of *Real defect*, *Real defect, low severity*,
*Intentional*, *False positive (global invariant)*, *False positive
(heuristic misfire)*, *Unresolved*. For a global invariant the reason is
followed by `Invariant: ... Enforced at: ... Breaks if: ...`. The comment
is at most 4,000 characters (the reason is shortened, with a note, to
fit) and carries no control character other than tab, LF and CR: a NUL
copied from a C literal such as `'\0'` has been measured to make Connect
answer HTTP 500 to the whole triage write.

## The two custom attributes

| attribute | Connect type | values |
|---|---|---|
| `Triage lane` | pick list | `Construction`, `Contract`, `Value or path`, `Other` |
| `Triage method` | pick list | `LLM: <model>` (one value per model used), `Execution: coverity-verify`, `Human`, `None` |

They must exist on the instance, with every value the records use, before
anything can set them. Whoever applies the records chooses per apply
whether to set them or only the standard attributes; the records always
carry both, so the choice is the applier's and not this skill's.
