# Use cases and workflows

What you can do with these skills, organized by what you are trying to do
rather than by skill. Each use case names the skills involved, in order, and
where one hands to the next. Every skill does one job; when a question
belongs to another skill, it hands over explicitly instead of doing half of
that skill's work.

## How the skills fit together

```mermaid
flowchart TB
    subgraph setup["Set up and capture"]
        CC["coverity-compiler-configuration"]
        CV["coverity<br/>rules, capture fidelity, Connect auth"]
        BF["coverity-build-fidelity"]
    end
    subgraph analyzer["Questions about the analyzer"]
        DD["coverity-defect-detectability"]
        MM["coverity-missing-models"]
        PO["coverity-pathout"]
        FS["coverity-function-slice"]
    end
    subgraph verdicts["Verdicts on findings"]
        TR["coverity-triage"]
        TS["coverity-triage-server"]
        VE["coverity-verify"]
    end
    subgraph history["History and upgrades"]
        DM["coverity-demo-data"]
        IT["coverity-issue-transition-inference"]
        RE["coverity-recreate-from-emit"]
    end
    subgraph changes["Changes and tests"]
        TA["coverity-test-advisor"]
    end
    CVSS["coverity-cvss-report"]

    CC -->|"configuration"| CV
    BF -->|"changed files captured"| TA
    TA -.->|"a finding in the changed code"| TR
    CV -->|"verified capture"| BF
    PO -->|"body"| FS
    PO -->|"candidates"| TR
    TR -->|"false positives:<br/>a function's behaviour"| MM
    DM -.->|"a published dataset,<br/>triaged separately"| TR
    TR -->|"execution method"| VE
    TS -.->|"same lanes, table<br/>and reading rules"| TR
    VE -->|"slice set, TU manifest"| FS
    BF -->|"build held constant"| IT
    RE -->|"old code, new analyzer"| IT
```

`coverity` sits under all of them: its rules apply to any Coverity work,
it owns capture verification and Connect authentication, and it routes a
question it does not own to the skill that does.

## Get a scan you can trust

**You want:** a capture that models your real toolchain, and evidence that
the analysis covered the code before anyone acts on its results.

```mermaid
flowchart LR
    A["coverity-compiler-configuration<br/>template configuration, cross-compilers, wrappers"] --> B["build under cov-build"]
    B --> C["coverity<br/>verify capture: counts, diagnostics,<br/>three methods, independently"]
    C --> D["cov-analyze"]
    D --> E["coverity-triage<br/>a stratified sample, in lanes"]
    C -.->|"release gating"| F["coverity-build-fidelity<br/>did cov-build change the product?"]
```

- `coverity-compiler-configuration` sets up `cov-configure` with templates, so
  the compiler is probed per invocation, the way the build actually runs it.
- `coverity` verifies the capture: what reached the analyzer, measured three
  ways, and reported as counts rather than a bare percentage.
- `coverity-triage` checks a sample of the results (rule 26) before the
  report leaves your hands.
- For a release gate, `coverity-build-fidelity` shows that wrapping the build
  in `cov-build` left the product unchanged, paired with capture coverage so
  the result means something in both directions.

## Triage findings by the kind of claim they make

**You want:** each finding sorted into a lane by what it claims, judged by a
method suited to that lane, with the verdict in Coverity Connect's own triage
fields and a record of which lane and method produced it.

```mermaid
flowchart LR
    IN["Findings<br/>a sample, a story's findings,<br/>or another skill's batch"] --> P{"Plan chosen?<br/>which findings,<br/>which method per lane"}
    P -->|"no"| Q["ask when interactive;<br/>otherwise report and stop"]
    P -->|"yes"| A{"Assign a lane<br/>checker table first,<br/>inference where it varies"}
    A -.->|"no row"| PC["a custom checker:<br/>place it once,<br/>in a table you keep"]
    PC -.-> A
    A -->|"construction"| L1["Construction lane<br/>is the construct there?"]
    A -->|"intent"| LI["Intent lane<br/>did the author mean this?"]
    A -->|"contract"| L2["Contract lane<br/>what does the callee promise?"]
    A -->|"value or path"| L3["Value-or-path lane<br/>is the path feasible, the value handled?"]
    A -->|"policy"| PO["Policy<br/>a rule-set match: never triaged"]
    A -->|"other"| O["Other<br/>no method, no verdict"]
    L1 & LI & L2 & L3 --> M["Method<br/>your choice for the finding,<br/>else the checker's own,<br/>else the lane's"]
    M -.->|"execution"| VE["coverity-verify"]
    M & VE --> R[("Records<br/>Classification, Action, Severity, Comment<br/>+ Defect Category, Triage Method")]
    PO & O --> R
```

- `coverity-triage` does this, in six lanes:
  - **Construction:** the construct does the wrong thing, or something
    undefined, for some input it can receive, whatever input actually
    arrives. It is real when the construct is there, and is never dismissed
    by arguing that the bad input is unlikely.
  - **Intent:** the code is well-defined, but a pattern suggests it may not do
    what its author meant, which the checker cannot know (a copy-paste slip, a
    missing `break`, a `sizeof` of the wrong thing, dead code).
  - **Contract:** a call ignores a failure its callee can report, or uses a
    result that can be invalid.
  - **Value or path:** a value or state reaches a point, along a path, that
    does not handle it.
  - **Policy:** a match against a rule set, a list of calls not to make or a
    threshold, with no claim that the code misbehaves. The record carries the
    lane and nothing else.
  - **Other:** none of the above fits, or the finding is not a claim about
    the code at all (a parse error is a capture problem, for the `coverity`
    skill); no verdict.
- Most checkers make one kind of claim, so a checker table assigns the lane;
  only the findings of the few checkers whose claims vary are assigned by
  reading the events.
- A custom checker the table does not know is placed once, before anything
  runs: from rows its producer ships, from the built-in checker it stands in
  for, or from its description. You see the proposed rows, and they go into a
  table file you keep, so the next run asks nothing.
- Each lane has a recommended method, kept in the skill: a reading for
  Construction, Contract and Intent (a stronger model for Intent), and
  execution through `coverity-verify` for Value or path. Where execution is
  not available or not wanted, a stronger reading in lieu of execution is
  recorded as just that. The plan stays your choice: a checker built for one
  method keeps it whatever its lane, and your choice for a single finding
  overrides both. No lane rules a method out. Policy takes no method, ever;
  Other takes none unless you give one to a finding, with the reason.
- On request, readers are also given Coverity's derived models of the
  callees the events name, taken from the intermediate directory, so a
  reading can check what a callee does without its body.
- Nothing runs until you have chosen which findings and which methods, because
  every method costs time per finding. Run unattended, it assigns what the
  table can, then reports the plan it needs and stops.
- A skill that hands its findings over can say which lane it expects. A
  finding that lands elsewhere is reported to you before any method runs.
- The output is a records file in Connect's attribute names. Applying it to
  Connect, with or without the two custom attributes, is up to whoever owns the
  instance. The two custom attributes are pick lists that must exist first; a
  setup tool in the skill checks for them and, on request, creates them over
  REST. It writes the attribute definitions only, never a verdict.
- A defect a reader notices while judging a different finding (a by-catch)
  goes to a `bycatch/` folder of its own, never into the records or the
  report, so nothing that travels with the verdicts carries it.

## Triage from inside a service that holds the findings

**You want:** a service that keeps a stream's findings to interpret one when
someone asks, by the same lanes, methods and reading rules as
`coverity-triage`, though the service has no source tree, no build and no way
to run the code.

```mermaid
flowchart LR
    REQ["a request to interpret<br/>a finding, or a selection"] --> L["lane<br/>from the same checker table"]
    L --> M{"method"}
    M -->|"execution"| STOP["record the lane and the method;<br/>no verdict"]
    M -->|"a reading"| RD["read the events with<br/>the stored source and<br/>the callees' derived models"]
    M -->|"none: Policy, Other"| LANE["the lane, and any<br/>action set by rule"]
    RD --> V{"rests on code<br/>the service holds?"}
    V -->|"yes"| VER["verdict, action and comment,<br/>in coverity-triage's field names"]
    V -->|"no"| UN["unresolved,<br/>naming the code it needs"]
```

- `coverity-triage-server` does this. Its evidence is the finding, the source
  the service stores, and Coverity's derived models of the callees. It names
  no particular service: any backend that holds that evidence can run it.
- It triages by the same lanes, checker table and reading rules as
  `coverity-triage`, which it reads from that skill's folder, so it needs
  `coverity-triage` beside it. The lane and method are the same; the verdict
  can differ, because the service reads on less evidence, and where
  `coverity-triage` would settle a finding the service may come out
  unresolved. The two answers mean the same thing.
- When the method is execution, it records the lane and the method and stops;
  the claim is settled by running the code elsewhere. It reads instead only
  when the person asking chooses a reading in lieu of execution, and says so.
- A verdict that would rest on code the service does not hold, such as a
  guard in the callers, comes out unresolved and names that code.
- Each reading costs model time: a request for one finding is the decision to
  spend it, and a request over many gives the count first.
- How the answer is stored, and whom it is credited to, is the service's
  business.

## Settle one finding by running it

**You want:** a definitive answer on one finding (a CID, an entry in a
findings file) instead of a debate about it; or, for a finding that
disappeared between two versions, whether the change fixed the defect or
only silenced the analyzer.

```mermaid
flowchart LR
    F["A finding<br/>CID or findings-file entry"] --> D{"A claim a sanitizer or<br/>an assertion can judge?"}
    D -->|"no: injection, resource,<br/>concurrency"| X["suggest external verification"]
    D -->|"yes"| RT{"Router: does the caller's<br/>preferred route apply?<br/>(harness by default)"}
    RT -->|"harness"| H["the whole translation unit,<br/>compiled with its recorded flags,<br/>a driver linked in; model stubs<br/>only for what it does not define"]
    RT -->|"extraction"| S["coverity-function-slice<br/>the slice set, standalone;<br/>model stubs outside it"]
    RT -->|"it does not apply"| Q["ask when interactive;<br/>otherwise report and stop"]
    H & S --> Z["fuzz: focused, then free"]
    Z --> V["verdict with its tier,<br/>the route and the evidence"]
    FX["a fix in hand"] -.-> K["the fix check:<br/>fixed, or silenced?"]
    V -.-> K
```

- `coverity-verify` does this. Its one method runs on one of two routes,
  with the same verdict tiers on both:
  - **Harness:** the translation unit's real source, compiled as the build
    compiled it, with a driver linked in and the original function run
    unchanged. Only the externals the unit does not define are stubbed, from
    Coverity's own models of them. It is the cheaper route and the default.
  - **Extraction:** the slice set from the emit, printed by
    `coverity-function-slice`, with every callee outside the set stubbed from
    its model. It is the route `coverity-pathout`'s shapes were built for, and
    the one for a program the harness route cannot take, or a defect type
    that has been shown to need it.
- The caller names the route it prefers: `coverity-pathout`'s shapes prefer
  extraction, other callers harness. A user whose program does not suit the
  harness route overrides it for that program. When the preferred route
  does not apply, the router never switches on its own: it asks in an
  interactive session, and otherwise reports why and stops.
- Run on a batch, verification is one method of `coverity-triage`, and a
  checker's table row can carry the route it prefers.

## Look where the analyzer reached its path bound

**You want:** to know which functions reached the per-function path limit,
which checker it cut short, what the analyzer did not examine there, and what
raising the bound would cost.

```mermaid
flowchart LR
    L["analysis log<br/>PATHOUT notices"] --> W["coverity-pathout<br/>which functions, which checker<br/>(--print-paths)"]
    W --> FS["coverity-function-slice<br/>the body, re-analyzed alone"]
    W --> M["measure: cost of a higher --paths,<br/>or restructure the function"]
    W --> SC["path-insensitive shape catalogue<br/>over the idir, kept to those functions"]
    SC --> C["candidates"]
    C --> A{"coverity-triage<br/>a lane from pathout's shape table;<br/>the row names the method"}
    A -->|"the row's method"| VE["coverity-verify<br/>extraction route"]
    A -->|"lands elsewhere"| Q{"Told before anything runs;<br/>you choose"}
    Q -->|"verify anyway,<br/>where realistic"| VE
    Q -->|"that lane's reader"| RD["reading"]
    Q -->|"leave it"| SK["untriaged"]
```

- `coverity-pathout` finds the functions and the checker, runs the shape
  catalogue there, and measures what a higher bound costs. With many
  functions at the bound, it pilots one, prices the rest (triage of each
  candidate included) and asks before going on.
- Its candidates are built to be run. `coverity-pathout` ships a row per shape
  for `coverity-triage`'s table, naming the lane of the built-in checker the
  shape stands in for and the method, execution through `coverity-verify` on
  the extraction route, the chain the shapes were built for. A row's method
  overrides its lane, so a
  candidate standing in for a Contract or Construction checker still goes to
  `coverity-verify`.
- They still pass through `coverity-triage`'s lane assignment, which is cheap
  and checks that each candidate's claim is what the shape assumed. A
  candidate that lands elsewhere is reported before any method runs, and you
  choose: verify it anyway where that is realistic, run that
  lane's reader, or leave it untriaged. Any choice is fine; none happens by
  surprise, and the record says which one you made.

## Answer "can Coverity find this?"

**You want:** an empirical verdict on whether Coverity reports a specific
defect, the minimal configuration that does, and a command to reproduce it.
Typical cases are comparing against another tool, answering an RFP, or
investigating a miss.

- `coverity-defect-detectability`: capture, run the defaults, escalate only
  while the answer is still "not found", then narrow to the minimal setting.
  It checks that the verdict carries over to the real code.

## Teach the analyzer what a function does

**You want:** fewer false positives, or defects the analyzer starts
reporting, because it now knows what one function really does: it never
returns, frees or keeps its argument, never returns NULL, initializes its
output.

```mermaid
flowchart LR
    FP["false positives from coverity-triage<br/>traced to what a function does"] --> Q{"A model question?"}
    ESC["a defect a later phase caught<br/>fuzzing, review, pen test, production"] --> Q
    Q -->|"no: an invariant no single function states;<br/>for an escape: capture, checker or option, path bound"| OTHER["the finding stays triaged;<br/>coverity, coverity-defect-detectability,<br/>coverity-pathout"]
    Q -->|"yes"| B["what the analyzer believes now<br/>callgraph metrics, derived models"]
    B --> W["the smallest model"]
    W --> RA["re-analyze a copy of the idir"]
    RA --> C["check: model applied, same code,<br/>target changed, canary did not,<br/>every other finding that moved"]
    C --> O{"The owner decides:<br/>keep or drop"}
    C -.->|"new findings, if you want verdicts"| TR["coverity-triage"]
    C -.->|"a finding to run"| VE["coverity-verify"]
```

- `coverity-missing-models` does this. Two things start it: false positives
  that `coverity-triage` traced to what a function does, and a defect that a
  later phase caught because the analyzer did not know a function's behaviour.
- For a false positive, it first checks that the invariant is a fact about
  one function. One that is not, such as a relation between the caller's
  values, stays a triaged finding.
- For an escape, it first rules out the cheaper answers: the capture
  (`coverity`), the checker or option (`coverity-defect-detectability`), the
  path bound (`coverity-pathout`).
- It proves what the model changed on a copy of the intermediate directory,
  and the owner decides whether to keep it. Each re-analysis is a full
  analysis of that copy, so it asks before each one; unattended, it writes and
  builds the model and stops. Triaging the findings a model
  surfaces is `coverity-triage`'s job and is opt-in: it is offered, with the
  count.
- What it learns is kept in the skill's `references/idioms.md`. It is the
  detection loop's *write a model or fact, feed it back as analyzer input*
  step ([`collateral/detection-loop/`](collateral/detection-loop/README.md)).

## Find the changed behaviour your tests don't exercise

**You want:** before pushing a change, to know which of the behaviour it
introduces no test exercises, including when line coverage says the changed
lines ran.

```mermaid
flowchart LR
    BASE["base idir<br/>the commit the change starts from"] --> P{"Preflight: same analysis<br/>on both sides, each idir<br/>from its commit, C or Java"}
    HEAD["head idir<br/>built and analyzed<br/>with the base's commands"] --> P
    BF["coverity-build-fidelity<br/>capture coverage: the changed<br/>files reached the head"] --> P
    COV["coverage of the head's tests<br/>gcov JSON or JaCoCo XML"] --> P
    P -->|"fails"| STOP["stops, with the reason"]
    P -->|"passes"| A["affected functions<br/>code changed, a callee's derived<br/>model changed, or its own model<br/>changed with no line changed"]
    A --> R["fixed rules settle the clear cases<br/>the function never ran, or a changed line,<br/>or its call into a changed function, never ran"]
    R --> J{"judge the rest against the tests?<br/>priced, and asked first"}
    J -->|"yes"| JU["did a test exercise the<br/>changed behaviour, or only<br/>run the lines?"]
    J -->|"no, or unattended"| OUT
    JU --> OUT[("report, and a local errors.xml<br/>one issue per gap,<br/>with a suggested test")]
```

- `coverity-test-advisor` does this. A function is affected when its code
  changed, when it calls an affected function whose Coverity derived model
  changed (a callee that now may return NULL changes every caller, though
  their code did not change), or when its own model changed though none of
  its lines did (a header macro, an inline function or a type it uses).
- You bring two analyzed intermediate directories, the base and the head,
  analyzed with the same commands and Coverity version, plus coverage of the
  head's tests. It builds nothing and runs no tests.
- It needs `coverity-build-fidelity`'s capture-coverage check of the head
  first, because a changed file the capture missed would look like a clean
  result. Build fidelity's binary comparison applies only when the tests ran
  on the build made under `cov-build`, and runs only when you ask.
- Judging reads the tests function by function, so it is priced and asked
  before it runs. Unattended, the skill stops after the fixed rules.
- Each gap is a report entry and a Coverity issue
  (`TA.INSUFFICIENT_TEST_COVERAGE`) in a local `errors.xml`, with the reason
  and a suggested test. Nothing is committed to Coverity Connect.
- This version covers C and Java, gcov JSON (measured on GCC 14) or JaCoCo
  XML, and Coverity Analysis 2026.9.0 on Linux. C++ is refused, because callers through
  a base class would be missed. A Connect snapshot as the base, clang
  coverage, and other versions are not in it yet.
- Whether a Coverity finding in the changed code is real is
  `coverity-triage`'s question.

## Adopt Coverity on a codebase that already has history

**You want:** findings dated to the release they arrived in, rather than to
the day the tool was installed. The same applies when migrating from another
tool, or preparing a demo, POC or training instance.

```mermaid
flowchart LR
    C["capture and analyze<br/>every release"] --> P["select versions and streams<br/>offline (merge-key arithmetic)"]
    P --> K["commit oldest-first<br/>--backdate"]
    K --> PUB["publish the dataset"]
    PUB -.->|"verdicts, if you want them:<br/>run separately"| TR["coverity-triage"]
```

- `coverity-demo-data` builds the history: one stream per branch, commits in
  global date order, the commit phase guarded because first-detected dates can
  be written only once.
- It does not triage. If you want verdicts on a published dataset's findings,
  run `coverity-triage` against it yourself.

## Upgrade Coverity without confusing tool changes with code changes

**You want:** for each finding that appeared or disappeared across an
analyzer upgrade, whether the code changed or the analyzer did.

```mermaid
flowchart LR
    A["old code, old analyzer<br/>(the result you have)"] --> X["coverity-issue-transition-inference"]
    B["old code, new analyzer<br/>(the control)"] --> X
    C["new code, new analyzer"] --> X
    B1["coverity-build-fidelity<br/>build held constant"] -.-> B
    B2["coverity-recreate-from-emit<br/>when the old build cannot run"] -.-> B
    X --> L["per finding: code change<br/>or analyzer change"]
```

- `coverity-issue-transition-inference` adds the missing control run, the old
  code under the new analyzer, which splits one confounded delta into two.
  The control decides both directions: for a finding that appeared, whether
  you wrote it or the analyzer changed; for one that disappeared, whether you
  fixed it or the analyzer stopped reporting it.
- When the old build can still be run, `coverity-build-fidelity` keeps it
  constant. When it cannot, `coverity-recreate-from-emit` rebuilds an
  analyzable intermediate directory from the old one.

## Reuse or recover an intermediate directory

**You want:** to analyze an old capture with a newer analyzer when the build
is gone; or to avoid a slow capture by bringing an existing idir up to date
with your tree.

- `coverity-recreate-from-emit` covers three situations:
  - **Recreate:** the build cannot run.
  - **Fast-forward:** catch a CI idir up to `HEAD`.
  - **Local update:** include uncommitted work.
- Fast-forward and Local update reuse an idir on purpose, against the usual
  rule. The skill runs the gates that decide when that is safe, and says no
  when it is not.

## Get one function as the analyzer saw it

**You want:** a single function out of an intermediate directory, as a file
that compiles and analyzes on its own. Typical uses are a minimal reproducer,
iterating without a rebuild, or a support ticket, with an obfuscated twin
that is proven to analyze identically.

- `coverity-function-slice` does this.

## Put CVSS scores on findings, and know which scores were judged

**You want:** the CVSS report, and to know which of its zeros were deliberate
and which came from a CWE with no mapping.

- `coverity-cvss-report` runs the report the documented way. It audits every
  score into decided-zero, scored, or unmapped, and records that in a triage
  attribute.

## Connect to Coverity Connect

**You want:** an authentication key that works, kept where it belongs.

- `coverity` creates the key, checks it over REST, and revokes it. The key
  never lives in a repository, and the connection URL is taken from you, never
  from the key file.

## What each skill does, and does not

| Skill | Does | Does not | Hands off to |
|---|---|---|---|
| `coverity` | standing rules; pinning one installation; reading an idir; verifying capture three ways; Connect authentication; routing | a specialist's job; explaining a noisy sample beyond re-checking capture | the specialist skill the question belongs to |
| `coverity-compiler-configuration` | template configurations; cross-compilers, embedded toolchains and wrappers; diagnosing and regenerating a tainted configuration | verifying the capture; judging the build | `coverity` (capture verification) |
| `coverity-build-fidelity` | native vs `cov-build` comparison of the product; capture coverage; a release-gate verdict and a profile draft | guessing at unexplained differences (it escalates to a person); work where the build cannot run | `coverity-recreate-from-emit` when the build cannot run |
| `coverity-defect-detectability` | an empirical detectability verdict; the minimal configuration; a repro command | triaging real findings; speculating about what a checker would do instead of running it | `coverity-triage` for verdicts on findings |
| `coverity-missing-models` | the smallest user model for a function whose behaviour the analyzer gets wrong; proof on a re-analyzed copy (model applied, same code, target, canary, every other finding that moved); what was learned, in `references/idioms.md` | deciding to keep a model (the owner does); triaging the findings a model surfaces; capture, checker selection and the path bound (ruled out first) | `coverity-triage` (new findings, opt-in), `coverity-verify` (a finding to run) |
| `coverity-demo-data` | a multi-version history with real release dates; streams per branch; guarded oldest-first commits; a self-contained published dataset that keeps each release's findings export and capture inventory | triaging, on request or otherwise (run `coverity-triage` on a published dataset yourself); the customer narrative; backdating triage history | nothing: triage is run separately |
| `coverity-pathout` | which functions reached the path bound and which checker; the shape catalogue there; the cost of raising the bound; restructuring; a priced pilot before a large run | judging its candidates; analyzing an idir from a version that is not installed (it stops and asks) | `coverity-function-slice` for bodies; `coverity-triage` for candidates, through its own shape table (method: execution through `coverity-verify`, extraction route); anything that lands elsewhere goes to the user |
| `coverity-function-slice` | one function from the AST; a standalone file that compiles and analyzes; an obfuscated twin with proof; a manifest of a whole translation unit for the harness route | deciding whether a finding is real | `coverity-pathout`, `coverity-verify` (its callers) |
| `coverity-verify` | an execution verdict on one finding, on the caller's preferred route (harness by default, or extraction), with its tier, the route and the evidence; the fix check | injection, resource and concurrency claims (it suggests external verification); switching route on its own; triaging a batch by reading | `coverity-function-slice` for the slice set and the translation-unit manifest |
| `coverity-triage` | triage you start, with the tree and execution at hand: a lane per finding (construction, intent, contract, value or path, policy, other), from a checker table where the checker decides it; a custom checker placed once, in a table you keep; a recommended method per lane, which a checker's own method overrides; readers given the callees' derived models on request; records in Connect's fields plus Defect Category (the lane) and Triage Method; policy findings recorded, not triaged | choosing the findings; writing verdicts to Connect (it creates its two attribute definitions only, on request); severity beyond "low"; exploitability; Connect's AI-Assisted Triage; demo-worthiness | `coverity-verify` for the execution method |
| `coverity-triage-server` | triage from inside a service that holds the findings, the stored source and the derived models: the same lane and method as `coverity-triage`, and a reading when the method is one; unresolved, naming the missing code, when a verdict would rest on code the service does not hold | running the code (an execution method stops after the lane and method); reading code it was not given; bundles, release chains, records files, applying to Connect; naming or assuming a particular service | `coverity-triage` (the lanes, table and reading rules it uses, beside it) |
| `coverity-issue-transition-inference` | the control run; per-finding code-vs-analyzer attribution; annotation, after asking how | comparing raw merge keys (Connect lines findings up); vendor-level cause as the headline | `coverity-build-fidelity`, `coverity-recreate-from-emit` for the control |
| `coverity-recreate-from-emit` | an analyzable idir without the original build; fast-forward and local-update reuse, behind gates | reuse when a gate fails; the default path when the build can run | `coverity-issue-transition-inference` (its consumer) |
| `coverity-cvss-report` | the report per the documentation; an audit of which scores were judged; the CVSS_Audited attribute | writing a security profile; judging exploitability | `coverity-verify` for whether a finding is real and reachable |
| `coverity-test-advisor` | every function a change can affect (code changed, a callee's derived model changed, or its own model changed with none of its lines); fixed-rule verdicts, and judged ones behind a priced ask; a report and a local errors.xml with a reason and a suggested test per gap | building or running the tests; committing to Connect; a Connect snapshot as the base; C++; clang coverage; versions other than 2026.9.0 on Linux | `coverity-build-fidelity` (capture coverage of the head, required); `coverity-triage` (a finding in the changed code) |
