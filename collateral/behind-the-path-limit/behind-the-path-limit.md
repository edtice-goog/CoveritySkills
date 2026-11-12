# Behind the Path Limit

<!-- deck: label=A worked example | subtitle=One tool's enrichment is the next tool's target. | blurb=Static analysis records where it applied its per-function bound; a fuzzer goes exactly there, built from the analyzer's own intermediate directory and models. Nothing new in the lifecycle: the findings-out, enrichments-in architecture with the names filled in, and a twenty-year-old trade extended for the post-Mythos world. -->

**Status:** Draft
**Purpose:** A standalone worked example, in the style of the SSDLC in the Mythos Era series, of an earlier-stage tool enriching its output so that a later-stage tool can target what the earlier one deliberately bounded. The earlier tool is Coverity; the enrichment is the list of functions on which it exceeded its path limit, with the checker that stopped in each; the later tool is a fuzzer that targets those functions, using the analyzer's own intermediate directory for its target and the analyzer's own derived models for its stubs.

---

## Why This Exists

The series argues for a feedback architecture: findings flow out of each tool, enrichments flow in, and each tool is placed at the earliest stage whose time and resource budget it fits. That argument is abstract by design. This is one instance of it, small enough to follow end to end and concrete enough to run.

It is not an additional step. Static analysis already runs early; fuzzing already runs late. What is added is a single piece of data passed from one to the other, and the observation that the late-stage tool can be built from the early-stage tool's own infrastructure.

Nor is it a correction. Heuristic analyzers won over sound ones on large codebases because they bound the work per function, and that bound was the right trade for as long as the residue behind it needed scarce expert attention to find and chain. Frontier models removed the scarcity. The bound stays; the residue is now worth examining; and the analyzer already holds everything needed to examine it.

## The Pattern

<!-- slide: eyebrow=THE PATTERN | headline=An earlier stage records where it applied its bound. A later stage starts exactly there. | cols=3 -->

Static analysis bounds its work per function; that bound is what lets it scale to whole systems with near-sound detection rates. Where it applied the bound, it says so, in a log. Turn that line into an enrichment record and the next tool has a target list it could never have derived for itself.

**The enrichment.** For each function on which the analyzer applied its bound: its name, its translation unit, the checker that reached the bound in it, and so the kind of defect that checker would have looked for. All of it is data the analyzer already had.

**The consumer.** A fuzzer that targets each of those functions, with the few functions on the finding's path beside it, instead of the whole program. Late-stage cost spent only where the early stage recorded a bound.

**The reuse.** The fuzzer's target is cut out of the analyzer's intermediate directory, and its callee stubs are printed from the analyzer's derived models. The later tool runs on the earlier tool's infrastructure, and so its verdict is in the earlier tool's own terms.

Nothing in the lifecycle moves. Two tools that were already placed exchange one record, and the record is the point.

## The Method

<!-- slide: eyebrow=THE METHOD | headline=Find. Look. Slice. Fuzz. Then a verdict that carries its evidence. -->

### Find
<!-- col: icon=discover -->
- **Enrichment out.** The log names the function; a diagnostics re-run names the checker that reached the bound.

### Look
<!-- col: icon=eye | style=accent -->
- **Enrichment refined.** A shape checker that needs no paths, kept only where the relevant checker reached the bound.

### Slice
<!-- col: icon=code-dark -->
- **The target.** The functions on the finding's path, from the analyzer's syntax tree, as one file that compiles alone.

### Fuzz
<!-- col: icon=bolt -->
- **The consumer.** Stubs from the analyzer's derived models for everything outside the slice; one input chooses everything.

The verdict flows back: confirmed, refuted or unconfirmed, with the evidence that earns it and the tier that says how far to trust it.

## Find

<!-- slide: eyebrow=FIND: ENRICHMENT OUT | headline=The log names the function. The analyzer, asked properly, names the checker. | cols=3 -->

The notice is one log line: the function, its translation unit, and nothing about why.

**Ask for the diagnostics.** `cov-analyze --print-paths` writes, per function and per component, how many paths each traversed and where it applied the bound: `Pathed out: 5001 paths traversed by REVERSE_INULL in setup_env`. That names the state that multiplied: nullness, index values, condition outcomes.

**On the whole project, on a copy.** Scoping to one translation unit is fast and loses the models of callees elsewhere; on nginx it reproduced 11 of 18. The re-run rewrites the log being diagnosed, so it runs on a copy with the original options.

**Batches hide names; diagnostics do not.** Under a heavy configuration, 186 of subversion's 189 notices named only a batch of twenty. The diagnostics name every function by its signature regardless.

This is the enrichment record: function, unit, checker, paths needed. nginx: 18 of 1,374 functions, the URI and SSI parsers among them. Redis: 27.

## Look

<!-- slide: eyebrow=LOOK: ENRICHMENT REFINED | headline=A path-insensitive checker for the shape, kept only where the path-sensitive one stopped. | cols=3 -->

The checker that reached the bound would have reported a specific shape. Write that shape without paths, feasibility or ordering, run it everywhere, and throw away every hit the finished checkers already rejected.

**Shape, not class.** Not "a null dereference" but "a pointer null-tested in an if, dereferenced outside it". Derived from a later-stage finding when there is one; when there is not, every shape is a hypothesis, and a catalogue of thirteen tested shapes runs in one pass.

**The filter is the mechanism.** A hit is kept only inside a function that reached the bound, and only where the checker that would have caught it was the one that reached it. Subversion: 503 hits, 115 in such functions, zero where a null-tracking checker reached the bound, 27 counting the reverse shape.

**Hand on, do not judge.** The shape stage passes its survivors as a triage plan; reading and execution are the triage's methods, and what reading cannot settle goes to execution. On subversion all 27 fell to reading: preconditions, allocate-if-null macros, invariants between variables, reassignment. Nothing is believed on the strength of a structural match.

The enrichment is now a line, not a function: nginx, 159 hits, 4 in functions that hit the limit, 2 where the relevant checker stopped. Thirteen shapes, fifteen seconds.

## Slice

<!-- slide: eyebrow=SLICE: THE TARGET | headline=The fuzz target comes out of the analyzer's intermediate directory, as the analyzer saw it. | cols=3 -->

The intermediate directory holds the syntax tree the analyzer used. One command prints a function from it in under a second, macros expanded, types canonical. No preprocessing, no source checkout. When the finding's path crosses functions, every function carrying one of its events comes out together, in one file, each seeing the others; a file-local callee loses only its linkage.

**Closed over its declarations.** A body alone will not compile. The same tree carries every callee's prototype, global, typedef and struct field; the tool prints them ahead of the body, re-emits with the translation unit's recorded flags, and re-analyzes. Forty random functions: forty clean.

**What is different, and said so.** Callees outside the slice are prototypes without models, globals are extern. A function whose behaviour came from its callees finishes under the limit as a slice; five of nginx's eighteen did. The fuzz stage puts the models back.

**A twin that can leave the building.** On request the slice is obfuscated by kind, strings masked, library names and constants kept, and both files analyzed to prove the analyzer treats them alike. Only the twin leaves.

The later-stage tool did not need the build, the source tree or the compiler. It needed the earlier tool's artefact.

## Fuzz

<!-- slide: eyebrow=FUZZ: THE CONSUMER | headline=The callees behave exactly as the analyzer believed they do. That is what makes the crash count. | cols=3 -->

A fuzzer needs definitions for the callees, and the wrong definitions give wrong verdicts: a hand-written stub that returns null where the real callee never can confirms nothing.

**The model is the stub, outside the slice.** `cov-find-function --save` writes each callee's derived model: an automaton whose edges are returns-null, returns-its-argument, allocates, dereferences-argument, writes, escapes. A stub is printed from it, one branch per behaviour; it can only do what the analyzer granted the callee. A function on the finding's own path is never a stub: its model is the analyzer's belief about it, and a confirmation through that belief would be circular.

**One input chooses everything.** A libFuzzer harness feeds the target's arguments and every stub's branch choice from one byte stream. The crashing input is a complete record of the callee behaviours the crash relied on, all of them in the analyzer's model.

**The oracle.** AddressSanitizer for dereferences, overruns and use-after-free; for a claim that does not crash, an assertion at the finding's line stating its negation. On the fixture the chain runs in a minute and crashes at the right line on a four-byte input.

On subversion, a null-return finding a bare slice lost came back once both callees on the chain were stubbed from their models; neither carried an event of the finding.

## Verdict

<!-- slide: eyebrow=VERDICT: ENRICHMENT IN | headline=Six verdicts, each with the evidence that earns it. | cols=3 -->

**Refuted by reading.** The variable is reassigned, asserted or guarded in a way the structural checker could not see; the reason is the deliverable.

**Refuted by execution.** The line reached many times and the claim never false, within a stated budget. Reached rarely or never is **unconfirmed**, not a refutation.

**Model says impossible.** No callee model on the path has an edge that produces the bad value; the analyzer's own knowledge refutes the claim, no build needed.

**Confirmed by crash under model stubs.** The sanitizer fired at the finding's line. The input and the stub branches taken are the reproduction, to check against the real callees; a stub list naming a function on the finding's path is malformed.

**Sourced by the harness.** A parameter, a global or a hook the harness supplied carried the bad value. A question about the callers, kept apart so it cannot pose as confirmation.

**Model gap.** The crash needed a behaviour outside the model: a user model the analyzer should have had, the enrichment flowing back in.

## What Was Measured

<!-- slide: eyebrow=THE NUMBERS | headline=Measured on real codebases, and read before believed. | cols=2 -->

**The bound rarely costs a defect.** nginx at ten times the limit, whole project: 51 defects before, 51 after, two functions still unfinished. One drops from 5,001 paths to 64 when its loop nest moves into a helper, measured on the slice.

**The filter does the work.** Subversion: 2,088 hits from a first draft, 503 once the checker learned what a guard is, 115 in functions that hit the limit, zero where the relevant checker stopped. Redis: 869, 76, zero.

**Execution has run on real findings.** Ten ordinary proftpd findings under Linux sanitizers: none confirmed, five refuted by execution, two model gaps, two sourced by the harness, one by reading.

**Not yet measured.** A confirmed finding on real code: the batch produced none, so the top tier rests on the fixture. The slice set is measured on a fixture, where the stub confirms and the code refutes, and on nginx; the fix check, fixed or silenced, on a fixture and one OpenSSL change.

The calibration records say which claims were measured and which were reasoned.

## What It Shows

<!-- slide: eyebrow=WHAT IT SHOWS | headline=The architecture the series describes, names filled in. | cols=2 | lead=none -->

The series describes findings flowing out of each tool, enrichments flowing in, and interface properties a tool must have to take part. This example names each of those.

**Findings out.** The path-bound list is a finding about the analysis itself: here is where the bound was applied, and which checker reached it. Exposing it costs nothing; the analyzer already had it.

**Enrichments in.** Verdicts and model gaps flow back as user models and as triage records that cite their evidence. The earlier tool gets better at exactly the functions on which it applied its bound.

**Interface properties, concretely.** A machine-readable log, an intermediate directory that yields any function on demand, and exportable derived models. Those three properties are what let a later tool be built on an earlier one.

**Placement, concretely.** Expensive execution at the late stage, aimed by cheap data from the early stage. Nothing runs earlier or later than it did; one record moves between them.

The pattern generalizes past the path bound: any early-stage tool that records where it applied a trade hands the late stage a target list, and the trade stays as good as it was.
