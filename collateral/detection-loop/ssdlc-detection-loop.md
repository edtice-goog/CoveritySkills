# Detection, Triage, and Tuning Loop

A process where deterministic analyzers do what they're best at, inference does what it's best at, and every inference step leaves a record that can be audited. Each diagram is one loop. They share the same triage records.

## 1. Defect loop: inference on both sides of the analyzer

Inference provides **facts as input** (things only reading the code reveals) and **judgments on the output**. The analyzer tracks the data flow between them.

```mermaid
flowchart LR
    code[Source code]
    inf["Inference: facts<br/>e.g. 'this variable holds PII'<br/>'query lacks join to user principal'"]
    facts[("Fact records<br/>versioned, auditable")]
    sa["Deterministic analyzer<br/>over-reports where it does not model"]
    findings[(Findings)]
    tri["Triage lane: LLM<br/>verdict + structured why"]
    rec[("Triage records<br/>method, category, reason")]
    fix[Code owner fixes]

    code --> inf --> facts --> sa
    code --> sa --> findings --> tri --> rec
    tri -->|real defect| fix
```

**Rule:** where the analyzer doesn't model a construct, it should over-report. The LLM can discard a false positive, but it can't recover a finding the analyzer never produced. Silent pruning inside the analyzer is how real defects get lost.

## 2. False-positive reasons are categories, and each one leads to an action

"Absurd" is one category among several. The list starts as free text and settles on a small fixed set.

```mermaid
flowchart TD
    fp[False positive verdict]
    fp --> absurd[Absurd construct]
    fp --> inv[Physical or protocol invariant]
    fp --> env[Environmental assumption<br/>e.g. host check safe because of mTLS]
    fp --> imp[Checker imprecision]
    fp --> other[Other: free text]

    absurd -->|test or benchmark code| none[No action]
    absurd -->|production code| anomaly[Investigate as anomaly]
    inv --> model[Write model or fact<br/>feed back as analyzer input]
    env --> dd[Design decision<br/>owner sign-off, revisit if environment changes]
    imp --> tune[Checker tuning or vendor feedback]
    other --> cluster[Periodic clustering<br/>promote recurring groups to categories]
```

The share of reasons that land in "other" shows whether the categories have settled.

## 3. Meta-triage: patterns across triage decisions change the configuration

```mermaid
flowchart LR
    rec[("Triage records")]
    agg[Aggregate by category,<br/>checker, codebase]
    rec --> agg

    agg -->|many environmental assumptions| cfg[Configuration does not match application<br/>adjust options or threat model]
    agg -->|repeated invariants| model[Missing model: add it]
    agg -->|imprecision concentrated in one checker| tune[Tune checker for this codebase]
    agg -->|absurd constructs in production| look[Investigate]

    cfg --> change["Recorded config decision<br/>linked to evidence group"]
    change --> trade["Measure the trade:<br/>what else did it drop? sample it"]
    trade --> owner{Owner accepts the loss?}
    owner -->|yes| keep[Keep]
    owner -->|no| revert[Revert]
```

Every configuration change drops some real findings. The trade can't be avoided. It must be visible, measured, and deliberately accepted.

## 4. Sensitivity across SSDLC phases

A catch in a later phase raises sensitivity in an earlier phase for that defect class. Settings stay only while they keep finding additional real defects.

```mermaid
flowchart LR
    p1[Phase 1<br/>nightly SAST / SCA]
    p2[Phase 2<br/>verification, fuzzing]
    p3[Phase 3<br/>review, pen test]
    prod[Production]
    p1 --> p2 --> p3 --> prod

    p2 -.->|catch| raise[Raise earlier-phase sensitivity<br/>for that class]
    p3 -.->|catch| raise
    prod -.->|escape| derive[Escaped-defect method:<br/>derive new control]
    derive --> raise

    raise --> q{Additional real defects found?}
    q -->|yes| hold[Keep setting<br/>recorded, with expiry]
    q -->|no| decay[Return to quiet default]
```

- Later phases act as cheap, early sensors for earlier ones, so sensitivity settles around very good values.
- A single-phase program gets only production escapes as its signal: rare, expensive, and late.
- **Ceiling:** the settled values can only be as good as what the last phase can see. A class that no phase detects never sends a signal.

## 5. New defect classes

Tuning improves detection you already have. New classes need their own input.

```mermaid
flowchart LR
    vendor[Tool vendor checkers]
    explore[Exploratory inference review]
    disclose[Public disclosures,<br/>research, curated data]
    cand[Candidate defect class]
    vendor --> cand
    explore --> cand
    disclose --> cand

    cand --> ctrl[Implement as deterministic check<br/>or input-side fact]
    ctrl --> run[Run on own code]
    run --> q{Additional real defects?}
    q -->|yes| adopt[Adopt: enters tuning loop]
    q -->|no| shelve[Shelve, record as tried]
```

An exploratory LLM review may give different answers each run. That's acceptable here, because its output is a hypothesis, not a finding to track. The hypothesis is accepted or rejected by the same measure as everything else: does it find additional real defects?

## Principles

- Inference produces **records you control**: facts on input, categorized judgments on output. It never produces silent decisions.
- Analyzers over-report what they don't model, and triage removes noise where it can be seen.
- Every trade between noise and missed defects is recorded, measured, and owned.
- Signals come from later phases of your own process, not from customers.
- A control is accepted because it finds **additional** defects, not because it re-finds the one that prompted it.
