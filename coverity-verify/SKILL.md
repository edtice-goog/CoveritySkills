---
name: coverity-verify
description: >
  Verify a Coverity finding by execution -- "verify this finding", "verify
  CID 12345", "run the verify skill", "verification", "is this real, run it".
  This is an alias: the skill is coverity-fuzz-triage, in the directory
  beside this one. Open ../coverity-fuzz-triage/SKILL.md and follow it.
---

# coverity-verify

Execution-based verification of a Coverity finding is the general
capability; `coverity-fuzz-triage` is where it lives. This directory exists
so that a reader or a filename search looking for "verify" lands.

Go to [`../coverity-fuzz-triage/SKILL.md`](../coverity-fuzz-triage/SKILL.md).
Its Step 0 takes a Connect CID, a `cov-format-errors --json-output-v10`
file, or a candidate from `coverity-pathout`'s shape catalogue, and the rest
is the same: the function as a standalone file, callee stubs from Coverity's
own derived models, the finding's claim checked at its line under libFuzzer
and a sanitizer, and a verdict with its tier.
