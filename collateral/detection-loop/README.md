# Detection, triage and tuning loop

Two companion write-ups on running static analysis as a loop: deterministic
analyzers do what they are best at, inference does what it is best at, and
every inference step leaves a record that can be audited.

| file | |
|---|---|
| `ssdlc-detection-loop.md` | the loop itself, one diagram per loop: inference on both sides of the analyzer, false-positive reasons as categories that each lead to an action, meta-triage that changes the configuration, sensitivity across SSDLC phases, and new defect classes |
| `ssdlc-starting-positions.md` | where an organization starts the loop, quiet first or targeted noise first, and why the starting point matters less than it seems |

Both are plain markdown with mermaid diagrams; nothing to build.

The skills that carry pieces of the loop are
[`coverity-triage`](../../coverity-triage/README.md) (verdicts in lanes, with a
record of the lane and the method),
[`coverity-verify`](../../coverity-verify/README.md) (execution as a triage
method) and
[`coverity-defect-detectability`](../../coverity-defect-detectability/README.md)
(the minimal configuration that reports a defect class).
