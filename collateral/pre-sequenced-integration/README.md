# Pre-sequenced, branch-predicted integration

An essay and two diagrams on fitting slow, whole-program verification such
as Coverity into a pipeline fed by coding agents. Merges are pre-sequenced
into slots, each branch is verified on its own in a private agent loop, and
the next slot is verified against both outcomes of the one ahead, so main
only ever fast-forwards to a verified state.

| file | |
|---|---|
| `pre-sequenced-integration.md` | the essay: why the usual pipelines fail when the slowest verifier takes 20 to 60 minutes, seven principles, and the lifecycle of a feature branch |
| `merge-train-flowchart.mmd` | the merge train as a flowchart: sequencing, the private agent loop, dual-track verification, the fast-forward gate |
| `merge-train-sequence.mmd` | the same flow as a sequence diagram, with the commands each slot runs |

The diagrams are mermaid source; nothing to build.

The skills that carry pieces of the private agent loop are
[`coverity-recreate-from-emit`](../../coverity-recreate-from-emit/README.md)
(incremental reuse of an intermediate directory),
[`coverity-test-advisor`](../../coverity-test-advisor/README.md) (the change's
untested behaviour, before it is pushed) and
[`coverity-triage`](../../coverity-triage/README.md) (verdicts on what the
analyzer reports).
