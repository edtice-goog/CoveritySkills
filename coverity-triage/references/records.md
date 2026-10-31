# The files, and the records

The checker table and four inputs feed `tools/records.py assemble`, which
writes one output. All JSON is UTF-8. Every finding is identified by its
**merge key**. CIDs are labels local to one Connect database, and appear
nowhere in these files (rule 27).

```
<out>/
├── NNN-CHECKER.md, INDEX.md, index.json    # tools/bundle.py
├── run.json                                # the plan: written before any method runs
├── lanes.json                              # tools/lanes.py, then inference for what it left pending
├── verdicts/<lane>-<n>.json                # one per reader batch (or per verify run)
├── triage.json                             # tools/records.py assemble
└── TRIAGE-REPORT.md                        # tools/records.py assemble
```

## The checker table

`references/checker-lanes.json` holds the skill's own rows. An
organization's table, or a producer's rows for its own checkers, has the
same format and is passed with `lanes.py assign --table`. A later file's row
replaces an earlier one for the same checker. `lanes.py check-table <file>`
validates a table.

```json
{
 "format": "coverity-triage-checker-lanes",
 "schema": 1,
 "checkers": {
  "SIZEOF_MISMATCH": {"lane": "Intent", "why": "a sizeof that does not match the pointer beside it"},
  "NEGATIVE_RETURNS": {"lanes": ["Contract", "Value or path"],
                       "decide": "Contract when the negative value is a callee's return; Value or path when it is a variable tested negative along the path"},
  "MY_SHAPE_NULL_DEREF": {"lane": "Value or path", "why": "a path-insensitive stand-in for FORWARD_NULL",
                          "method": "Execution: coverity-verify", "route": "harness"}
 }
}
```

| field | rule |
|---|---|
| `lane` | a fixed lane, one of the six. Give `lane` or `lanes`, never both |
| `why` | required with `lane`: what the checker claims, in a phrase. It becomes the finding's lane reason |
| `lanes` | two or more candidate lanes, all from Construction, Intent, Contract and Value or path. Inference chooses among them per finding |
| `decide` | required with `lanes`: what tells the candidates apart |
| `method` | optional: the method the checker was built for (`LLM: <model>`, `Execution: coverity-verify` or `Human`). It overrides the lane's method in the plan. Never on a Policy or Other row; a checker that is never triaged is Policy |
| `route` | optional, only beside `Execution: coverity-verify`: `harness` or `extraction`, the route verify should prefer |

## `run.json`: the plan

Written when the plan is fixed, before any lane method runs, so the plan
that was agreed is the plan on record.

```json
{
 "date": "2026-10-28",
 "selection": "per-checker sample of 2, plus 1 named merge key",
 "assigner": "LLM: Sonnet 5.5",
 "lanes": {"Construction": "LLM: Sonnet 5.5",
           "Intent": "LLM: Sonnet 5.5",
           "Contract": "LLM: Opus 5.5",
           "Value or path": "Execution: coverity-verify"},
 "verify_route": "extraction",
 "who": "4 local subagents in Claude Code",
 "connect_ai_triage": false,
 "expected": {"by": "coverity-pathout", "lane": "Value or path",
              "method": "Execution: coverity-verify"},
 "overrides": [
  {"mergeKey": "9c1d...", "method": "Execution: coverity-verify", "route": "harness",
   "reason": "a closer look at this one finding"},
  {"mergeKey": "41aa...", "method": "None",
   "reason": "assigned Other; user chose to leave it untriaged"}
 ]
}
```

- **`lanes`** names a method for each of the four method lanes. A lane
  left out of the plan has `"None"`, written down: a missing lane is
  refused, never defaulted. Policy and Other are never listed.
- **A method** is one of `LLM: <model>`, `Execution: coverity-verify`,
  `Human` or `None`. `<model>` is the model's display name (`Opus 5.5`,
  `Sonnet 5.5`, `Haiku 5.5`). Any method may be planned for any of the four
  lanes.
- **`assigner`** is the method for inference on findings left pending. It
  is `"None"` when the table settles every lane.
- **`verify_route`** (optional) is the user's route for every finding verify
  runs in this plan, for an application whose situation does not suit a
  row's preference. It beats the rows' `route`, and loses to an override's.
- **`who`** says who and where, in words. `connect_ai_triage` is `false`,
  because this skill never uses it.
- **`expected`** (optional) is the lane and method the calling skill built
  its findings for. A finding is off-lane when its lane differs and its
  checker's own method differs too; off-lane findings are reported to the
  user before any method runs. Policy findings are never off-lane, since
  there is no choice to make for them.
- **`overrides`** (optional) are the user's choices for single findings. Each
  is a method from the four forms, with the reason, and a `route` when the
  method is verify. An override is the strongest choice there is: it beats
  the checker's own method and the lane's. It is also the only way a finding
  in Other gets a method. A Policy finding takes none.

## `lanes.json`: the assignment

`tools/lanes.py assign` writes it. Every finding whose checker has a fixed
lane is under `lanes`. Every other finding is under `pending`, either with
its candidates or marked `unplaced`.

```json
{
 "tables": ["references/checker-lanes.json", "acme-checkers.json"],
 "lanes": [
  {"mergeKey": "6b0b0c...", "checker": "NULL_RETURNS", "lane": "Contract",
   "reason": "a callee's NULL return is used", "assigned_by": "checker table"}
 ],
 "pending": [
  {"mergeKey": "3fe1...", "checker": "NEGATIVE_RETURNS",
   "candidates": ["Contract", "Value or path"], "decide": "..."},
  {"mergeKey": "77aa...", "checker": "ACME_NEW_CHECK", "unplaced": true}
 ]
}
```

Inference moves each pending finding into `lanes`, with `lane` (one of its
`candidates`), `reason` and `assigned_by` (the plan's `assigner`). An
unplaced checker gets a row in a table file, and `assign` runs again. Before
`assemble`, `pending` must be empty.

| field | rule |
|---|---|
| `lane` | one of `Construction`, `Intent`, `Contract`, `Value or path`, `Policy`, `Other` |
| `reason` | required: the row's `why`, or the sentence inference wrote naming the events |
| `assigned_by` | `checker table`, the plan's `assigner` (with `candidates`, and a lane among them), `Human` (a person moving a finding, with the reason), or `compiler header` (always lane `Other`, and only for a finding `index.json` marks with `compiler_header`) |
| `method`, `route` | copied from the checker's row, when it has them |

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
| `lane`, `method` | the lane the findings were assigned to, and the method each finding takes: its override's, its checker's own, or the plan's for the lane, in that order. A file holds findings of one lane and one method |
| `model` | the model id the reader actually ran on, as it reports it |
| `verdict` | a word from the verdict set (`reading.md`) |
| `reason` | required: the argument, with `file:line` for each claim about the code. A reader that thinks the lane is wrong uses `unresolved`, and starts the reason with `wrong lane: <lane>` |
| `invariant`, `enforced_at`, `breaks_if` | required and non-empty for `false positive - global invariant`; ignored otherwise |
| `sites_read` | the code read, as `path:line` or `path:first-last` |
| `executed` | `true` only when the verdict rests on running the code (the execution method) |
| `route`, `route_reason`, `as_code`, `stubbed` | from `coverity-verify`'s record: the route that ran and why, what ran as code, and what was stubbed. Carried into the record's evidence |

A finding in a lane whose method is `Human` may have no verdict yet. Its
record says it is awaiting a person, and a later verdict file from that
person (method `Human`) completes it.

## From `coverity-verify` to a verdict

The execution method reports a tier for each finding (`coverity-verify`,
Step 4). Both routes, harness and extraction, report the same tiers.
Translate the tier into the verdict set before writing the verdict file:

| verify's tier | verdict |
|---|---|
| *confirmed by crash under model stubs*, with every stub behaviour the crash relied on checked against the real callee | `real` |
| *confirmed by crash under model stubs*, with a relied-on behaviour not yet checked against the real callee | `unresolved`: the confirmation rests on a model of the callee |
| *refuted by execution*; *refuted by execution, a path the analyzer missed* | `false positive - global invariant`: the claim that held as the invariant, the line and the reach count under the budget as `enforced_at` |
| *model says impossible* | `false positive - global invariant`: no callee model on the path produces the bad value; the models are `enforced_at` |
| *model over-approximates the callee*; *model gap* | `false positive - global invariant`: what the real callee does, and where in its code, as `enforced_at` |
| *refuted by reading* | `false positive - global invariant` with the guard's location, marked `executed: false` |
| *parameter-, global-, hook-sourced*; *unconfirmed after N seconds*; *not a fuzz-triage candidate*; *not verified: <route> does not apply* | `unresolved`, with verify's tier as the reason |

Every case needs `breaks_if` as well: the change that would make the claim
reachable.

- Mark the verdict `executed: true`, except where the table notes otherwise.
- Put the tier, and the reach count or the crash evidence, in `reason`.
- Copy verify's `route`, `route_reason`, `as_code` and `stubbed`.

A *bycatch* tier is not a verdict on the finding. It goes to the by-catch
directory (next section), never into `reason`.

## By-catch: never in the records

By-catch is a defect noticed while working on a different finding: a crash
verify's free run hit elsewhere, or a bug a reader saw in code it read. In
your own code it is usually just another defect to fix. In code that is not
yours (a vendored library, an open-source dependency), it may be an
unreported vulnerability.

The records are what people pass around: `triage.json` gets applied to
Connect and the report gets shared. By-catch has no CID for Connect to
attach to, and may not be yours to share. So it is kept out of the records
entirely:

- not in `reason`, nor in any other verdict field, a verdict file or
  `run.json`;
- not in `triage.json` or `TRIAGE-REPORT.md`, not even as a count;
- not in the bundles.

`records.py assemble` refuses a verdict that carries a by-catch field, or a
`reason` written in the usual by-catch phrasing ("side observation",
"aside, not part of this finding", "present but unreported", "worth its
own check", "bycatch"). That refusal is a backstop: by-catch described in
other words passes it, and the convention is what protects you.

**Where it goes: the `bycatch/` folder of the run** (`<out>/bycatch/`),
beside the records but never inside them. A caller can name another folder
instead (`--bycatch-dir`), such as a security team's intake folder.

- **What the readers write.** One file per reader batch or verify run, named
  `<lane>-<n>.json` or `verify-<n>.json`:

  ```json
  {
   "noticed_by": "LLM: Sonnet 5.5",
   "model": "claude-sonnet-5-5",
   "items": [
    {"site": "<path>:<line>",
     "claim": "<what looks wrong there, in one sentence, with file:line>",
     "noticed_while": "<merge key of the finding being read>",
     "sites_read": ["<path>:<first>-<last>"]}
   ]
  }
  ```

- **What `assemble` adds.** It checks every by-catch file (each item needs a
  `site`, a `claim`, and a `noticed_while` naming a bundled finding). It
  writes `bycatch.json` in the same folder, with every item and the file it
  came from. It also prints one line a script can read:

  ```
  by-catch: 2 item(s) in <out>/bycatch/bycatch.json
  ```

  With no by-catch, it writes no `bycatch.json`, and prints `by-catch: none`.

```json
{
 "format": "coverity-triage-bycatch",
 "schema": 1,
 "tag": "v2.0",
 "items": [
  {"site": "...", "claim": "...", "noticed_while": "...", "sites_read": ["..."],
   "noticed_by": "LLM: Sonnet 5.5", "model": "claude-sonnet-5-5", "file": "Contract-1.json"}
 ]
}
```

An item is a note, not a verdict: nobody has verified it. In your own code,
treat it like any other defect report. In code that is not yours, hand it to
whoever handles unreported vulnerabilities there (a product security team,
or the upstream project's security contact). Sharing the whole run folder
shares `bycatch/` with it, and the folder's name says so.

## `triage.json`: the records

```json
{
 "format": "coverity-triage-records",
 "schema": 1,
 "run": { ...run.json..., "tables": ["references/checker-lanes.json"],
          "source": {"issues": "v1.3.9.json", "git_repo": "...", "tag": "v1.3.9",
                     "source": {"mode": "git", "repo": "...", "rev": "v1.3.9"},
                     "strip_prefix": "/home/me/proftpd"} },
 "records": [
  {"mergeKey": "6b0b0c...",
   "checker": "NULL_RETURNS",
   "judged": {"tag": "v1.3.9",
              "sites": [{"file": "modules/mod_log.c", "line": 1324, "function": "log_openfile"}]},
   "lane": "Contract",
   "lane_reason": "a callee's NULL return is used",
   "lane_assigned_by": "checker table",
   "method": "LLM: Sonnet 5.5",
   "verdict": "false positive - global invariant",
   "triageState": {"classification": "False Positive", "action": "Ignore",
                   "severity": null,
                   "comment": "False positive (global invariant): The else branch ...\n[coverity-triage 2026-10-28] Lane: Contract (assigned by checker table). Method: LLM: Sonnet 5.5, read, not executed.",
                   "customTriage": {"Defect Category": "Contract",
                                    "Triage Method": "LLM: Sonnet 5.5"}},
   "evidence": {"reason": "...", "invariant": "...", "enforced_at": "...", "breaks_if": "...",
                "sites_read": ["..."], "executed": false, "model": "claude-sonnet-5-5",
                "bundle": "013-NULL_RETURNS.md"}}
 ]
}
```

- **`run.source.source`** says where the bundles' source came from:
  `{"mode": "git", "repo", "rev"}` by default, or `{"mode": "idir", "idir",
  "coverity"}` when there was no git source.
- **`run.tables`** lists the checker tables the lanes came from.
- **`triageState`** uses the attribute names of Connect's triage-store
  export: `classification`, `action`, `severity`, `comment`, and
  `customTriage` for custom attributes. **`null` means leave that
  attribute alone** on the target.
- **`judged.sites`** lists every site the merge key was reported at in
  this version. A merge key does not depend on the file, so copy-pasted
  code in two files can share one key; a verdict on it covers all of them,
  and the reader is shown all of them.
- **`evidence`** is for people, and is never applied. When the method is
  verify, `route_preference` is the route the finding was sent with: the
  override's, the plan's `verify_route`, or the row's `route`, in that
  order. `route` and the fields beside it are what verify reports actually
  ran.
- **`method_reason`** appears when the method did not come from the plan's
  lane. It carries the override's reason, or "the checker's own method
  (checker table)".

### The mapping

| verdict | classification | action | severity |
|---|---|---|---|
| `real` | Bug | Fix Required | null |
| `real, low severity` | Bug | Fix Required | Minor |
| `intentional` | Intentional | Ignore | null |
| `false positive - global invariant` | False Positive | Ignore | null |
| `false positive - heuristic misfire` | False Positive | Ignore | null |
| `unresolved`; Policy; Other; method `None`; awaiting a person | null | null | null |
| a compiler header (Other, by rule) | Intentional | Ignore | null |

The comment is set on every record that has a verdict, `unresolved`
included, so the argument reaches whoever opens the finding. A record with
no verdict sets only the two custom attributes: Policy, Other, method `None`,
or awaiting a person.

**A finding in a compiler header** is the one record with a verdict and no
method. `assemble` writes it without a verdict file: lane `Other`,
`lane_assigned_by` `compiler header`, method `None`, verdict `intentional`,
and a comment naming the header. Classification Intentional takes it out of
every view of outstanding findings for good. A tracker with no Intentional
classification takes False Positive instead.

### The comment

```
<Label>: <reason>
[coverity-triage <date>] Lane: <lane> (assigned by <checker table | assigner>). Method: <method>, <read, not executed | executed>.
```

with `<Label>` one of *Real defect*, *Real defect, low severity*,
*Intentional*, *False positive (global invariant)*, *False positive
(heuristic misfire)*, *Unresolved*.

- For a global invariant, the reason is followed by `Invariant: ...
  Enforced at: ... Breaks if: ...`.
- The comment is at most 4,000 characters. The reason is shortened to fit,
  with a note.
- It carries no control character other than tab, LF and CR. A NUL copied
  from a C literal such as `'\0'` has been measured to make Connect answer
  HTTP 500 to the whole triage write.

## The two custom attributes

| attribute | Connect type | default | values |
|---|---|---|---|
| `Defect Category` | pick list | `Unassigned` | `Unassigned`, `Construction`, `Intent`, `Contract`, `Value or path`, `Policy`, `Other` |
| `Triage Method` | pick list | `None` | `None`, `Execution: coverity-verify`, `Human`, `LLM: <model>` (one value per model used) |

Connect gives every pick list a default, which is what a finding nobody has
triaged shows. `Unassigned` is not a lane, and the records never set it.
`None` means no method ran, which is also true of a finding nobody has
triaged.

`Defect Category` holds the finding's lane. It is not Connect's built-in
Category, which is the checker's category (for example "Null pointer
dereferences"), and the two are set independently.

They must exist on the instance, with every value the records use, before
anything can set them. Whoever applies the records chooses, per apply,
whether to set them or only the standard attributes. The records always
carry both, so the choice is made at apply time (`--standard-only`).

**Creating them: `tools/connect_attributes.py`** (SKILL.md, *Step 6*).

- **The API it uses.** It works over REST at `/api/v2/triageAttributes`:
  POST creates an attribute, and GET or PUT on
  `/api/v2/triageAttributes/<name>` reads or changes one. That is what a
  Connect 2026.9.0 server serves. Its REST reference names the path
  `/api/v2/attributes`, and the same server answered GET and OPTIONS there
  with 404. The tool therefore uses the path the server was measured to
  serve.
- **Requests.**
  - **Create:** a POST carrying `name`, `description`, `attributeType`
    (`LIST_OF_VALUES`), `showInTriage`, `defaultValueName` and
    `attributeValues` (`[{"name": ...}]`).
  - **Add a value:** a PUT sending the definition back, with every value it
    already has (ids included) plus the new ones. A PUT replaces the value
    list, so a value left out of it is removed. Existing values keep their
    ids.
- **What it will not do:** delete or rename an attribute or a value, or
  change an attribute's type. An attribute that already exists with another
  type, or a needed value marked deprecated, stops it with a message.

## Applying the records: `tools/connect_apply.py`

SKILL.md, *Step 6*, gives the command and when to run it. Here is what it
sends.

- **Finding each record's finding.** A POST to `/api/v2/issues/search`,
  filtered by the project and the stream, returns every finding in the
  stream with its CID, merge key, Classification, Action, Severity, last
  triage comment and the two custom attributes, in pages of 200. A merge key
  that comes back with two CIDs stops the apply. The search names no
  snapshot scope, so it returns only the findings in the stream's latest
  snapshot (measured on 2026.9.0). A merge key last reported in an earlier
  snapshot is reported as not found.
- **The triage store.** A GET on `/api/v2/streams/<name>` gives the stream's
  `triageStoreName`, and the write goes to that store.
- **The write.** A PUT to `/api/v2/issues/triage?triageStoreName=<store>`
  with `{"cids": [...], "attributeValuesList": [{"attributeName": ...,
  "attributeValue": ...}]}`. The comment is the attribute `Comment`. One
  request carries every finding that gets the same values.
- **What each field becomes.** `triageState.classification`, `action`,
  `severity` and `comment` go to Classification, Action, Severity and
  Comment, and `customTriage` to the two custom attributes, by name. A null
  is not sent.
- **What counts as someone's triage.** Any value other than the attribute's
  default: `Unclassified`, `Undecided`, `Unspecified`, `Unassigned` and
  `None`. A comment is never a conflict. It is posted when it differs from
  the finding's last triage comment, ignoring line endings and surrounding
  white space.
- **The read-back.** After the write, the same search runs again, and each
  finding written must now hold every value its record sets.
