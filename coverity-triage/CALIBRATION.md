# Calibration status

This project's standard is that factual claims in a skill were established by
real runs. This file records what was run for `coverity-triage`, on what, and
what is reasoned rather than measured.

## Verified by direct execution

- **The tools, on a generated fixture** (`evals/test_tools.py`, git and
  Python 3 only).
  - **`bundle.py`:**
    - `--plan` writes nothing, and the selection is deterministic.
    - Source comes from `git show <tag>:<path>`, not the working tree; the
      fixture changes the working tree after tagging.
    - A form feed in the source does not shift excerpts.
    - A merge key reported at two sites bundles both.
    - Refused: nothing selected; a merge key not in the findings; no source;
      both sources; `--idir` without `--cov-bin`; `--git-repo` without
      `--tag`.
  - **`lanes.py`:**
    - The skill's checker table validates.
    - Eleven malformed rows are refused: lane and candidates together, or
      neither; an unknown lane; one candidate; Policy as a candidate;
      candidates without `decide`; a fixed lane without `why`; a method on a
      Policy row; `None` as a row method; a route without verify; an unknown
      route.
    - `assign` fixes the table's lanes, including Intent, Policy and Other;
      leaves a candidate checker pending with its candidates; marks a checker
      no table has as unplaced; and, with a producer's table, places that
      checker with its own method and route.
  - **`records.py`:** one good assembly, and twenty-seven refusals, each
    writing nothing:
    - a global invariant with no location;
    - a word outside the verdict set;
    - a NUL in a comment;
    - a missing verdict;
    - a verdict read in the wrong lane;
    - an unassigned finding;
    - an unknown lane;
    - a finding still pending;
    - inference choosing outside the candidates;
    - inference by a model that is not the plan's assigner;
    - a table entry that carries candidates;
    - a verdict for Other;
    - a verdict for Policy;
    - an override on a Policy finding;
    - a plan without Intent;
    - a plan that lists Policy;
    - an unknown verify route;
    - a method that is not the finding's;
    - `executed` claimed by a reader;
    - an off-lane finding with no recorded choice;
    - an override with no reason;
    - a route on an override that is not verify;
    - a verdict carrying a by-catch field;
    - a reason written in by-catch phrasing ("Side observation: ...");
    - a by-catch item with no claim;
    - a by-catch item naming a finding that was not bundled;
    - a by-catch file with no method that noticed it.
  - **Compiler headers and a later release**, on a fixture of its own, in 15
    cases:
    - A finding in libstdc++ (`/usr/include/c++/13/...`) and one in MSVC's
      `VC/Tools/MSVC/<version>/include` are marked compiler headers. One in
      `/usr/include/stdio.h` is not, and one in a directory given with
      `--compiler-header` is.
    - Under `--per-checker 1`, a compiler header does not take its checker's
      sample.
    - `assign` gives them Other, by `compiler header`. `assemble` records
      them Intentional and Ignore, with method `None` and the header named in
      the comment.
    - Refused: a verdict for one, an override on one, the header lane on a
      finding not in a header, a table lane on one in a header, and a
      tampered record.
    - A second release with `--prior` (the first release's records) leaves
      out the keys with a verdict, a Policy key and a compiler header. It
      bundles again a key with no verdict, and a new one. A key named with
      `--merge-key` is bundled anyway, and a findings file passed as
      `--prior` is refused.

    Shown working:
    - by-catch collected into `bycatch/bycatch.json` (from the default
      folder, and from one named with `--bycatch-dir`), announced on stdout
      (`by-catch: 1 item(s) in ...`, or `by-catch: none`), and absent from
      `triage.json` and the report;
    - a checker's own method beats the lane's plan, and verify's route and
      inventory are carried into the evidence;
    - a plan-wide route beats a row's route;
    - verify planned for the Contract lane is accepted;
    - overrides for verify-anyway, another lane's method and
      leave-untriaged;
    - Policy is never off-lane;
    - `check-lanes` lists every off-lane finding;
    - a comment over 4,000 characters is shortened.

- **One end-to-end reading run, 2026-10-24**, before the lanes were revised.
  - **Corpus:** proftpd v1.3.9 findings (`cov-format-errors --json-output-v10`,
    Coverity 2025.9.0, analysis defaults: 147 reports, 112 merge keys, 13
    checkers), with source from a clone at tag `v1.3.9`.
  - **Selection:** `--per-checker 2`, 24 findings, 4 of them merge keys
    reported at more than one site.
  - **Lanes:** three method lanes plus Other, with an LLM assigning all 24.
    Lane assignment and all three reading lanes ran on Sonnet 5.5: one
    subagent for the assignment, and four readers (one each for construction
    and contract, two batches of seven for value or path).
  - **Assembly:** `records.py assemble` and `validate` passed on the first
    attempt, and every global-invariant dismissal carried its three parts.

  | lane | findings | real, low severity | intentional | false positive - global invariant | no verdict |
  |---|---|---|---|---|---|
  | Construction | 5 | 4 | 1 | 0 | 0 |
  | Contract | 4 | 2 | 0 | 2 | 0 |
  | Value or path | 14 | 2 | 4 | 8 | 0 |
  | Other | 1 | | | | 1 |

  No `real`, no `unresolved`, and no `wrong lane` came back from any reader.
  Other held the one COPY_PASTE_ERROR.

  **Cost, measured:** about 1.04 M subagent tokens for the 24 findings,
  roughly 43 k per finding. The lane assignment alone was 198 k. Wall clock
  per reader batch was 5 to 13 minutes, the longest being the seven
  value-or-path findings that needed the most callee reading.

- **The checker table, applied, 2026-10-28.** This measures lanes only; no
  verdict was re-run.
  - **All 112 proftpd v1.3.9 merge keys:** `lanes.py assign` placed 110 from
    the table. The 2 NEGATIVE_RETURNS findings are left for inference, and
    nothing is unplaced. The 2026-10-24 run spent 198 k tokens assigning 24
    findings by inference.
  - **The 2026-10-24 run's 24 bundles:** 22 placed from the table. 8 change
    lane, all to Intent:
    - COPY_PASTE_ERROR from Other;
    - MISSING_BREAK and both SIZEOF_MISMATCH from Construction;
    - both DEADCODE and both UNUSED_VALUE from value or path.

    The 2 NEGATIVE_RETURNS are pending, and the other 14 keep the lane the
    LLM gave them.

- **Creating the two custom attributes, 2026-10-28,** against a Connect
  2026.9.0 server, with its owner's agreement, using HTTP Basic with an auth
  key.
  - **The REST path.** The REST reference names `/api/v2/attributes`. That
    server answered it with 404 for GET and OPTIONS. GET was also tried with
    a trailing slash and with a name appended; OPTIONS only on the bare path;
    POST, PUT and DELETE were not sent.
    - A 404 on OPTIONS, which reports a path's methods, makes it very likely
      that the route is absent rather than limited to other methods. That is
      an inference: "every method" was not measured.
    - The server serves `/api/v2/triageAttributes` instead. OPTIONS on the
      collection returned `Allow: POST,GET,HEAD,OPTIONS`; POST and GET were
      used.
    - OPTIONS on `/api/v2/triageAttributes/<name>` returned
      `Allow: GET,HEAD,PUT,DELETE,OPTIONS`; GET and PUT were used, and DELETE
      was not called.
    `/api/v2/standardAttributes` holds the compliance standards, not triage
    attributes. The Swagger description needs a browser session, and turns
    away a key.
  - **Created.** POST, with `name`, `description`, `attributeType:
    LIST_OF_VALUES`, `showInTriage`, `defaultValueName` and `attributeValues`,
    returned 201 for both attributes. Read back, each had its type, default
    and values exactly.
  - **Checked.** `connect_attributes.py check` then found nothing missing,
    and `setup` without `--yes`, given a new model, planned one added value
    and changed nothing.
  - **Adding a value.** `setup --yes --model "Haiku 5.5"`, with the key at its
    default path, sent the PUT. The new value got a new id, and the five
    existing values kept theirs.
  - **Removing it again.** A PUT that left the value out removed it, and the
    list was back to five values with their original ids. So a PUT replaces
    the value list, which is why the tool sends every existing value back.
    Not tested: removing a value that findings already use.
  - **Fake Connect.** `evals/test_tools.py` runs the tool against a local fake
    Connect in 12 cases: plan only; create; check; add a value by PUT, with
    every existing value sent back; and refusals for a lane that is not a
    lane, a deprecated value, the wrong type, a wrong key, and a file that is
    not an auth key. A refused run writes nothing, and the key file's
    `comments.host` is never used.

- **The idir as the backup source, 2026-10-24.**
  - **Against git:** the same 24 proftpd v1.3.9 findings, bundled with
    `--idir` (the analyzed idir) and `--cov-bin` of the 2025.9.0 installation
    that wrote it, on Windows, came out byte-identical to the git-sourced
    bundles, in about a second. The extracted `modules/mod_log.c` was
    byte-identical to `git show v1.3.9:modules/mod_log.c`.
  - **Matching files:** `extract-files` did not match the recorded paths
    given as file names, but did match by `--regex`. The tool therefore
    matches by path suffix, and finds each file through the
    `emit-file-map.json` it writes.
  - **Refusals,** on a one-file idir emitted for the test: a `--cov-bin` of
    2026.9.0; a copy re-filed under another host name (with the tool's own
    `reset-host-name` message, leaving the copy unchanged); both sources; no
    source; `--idir` without `--cov-bin`.
  - **Not run:** a Linux installation reading a Linux capture.

## What the run showed, and what changed

- **The construction lane was answering two kinds of claim.** The run's
  assigner put Y2K38_SAFETY, SIZEOF_MISMATCH and MISSING_BREAK in
  Construction because none of them traces a path. Two corrections
  followed.
  - **Y2K38_SAFETY stays in Construction.** A construct that does the wrong
    thing for part of its input is a defect, and it is not dismissed by how
    large a value can get or how long that takes. The run's `real, low
    severity` on both Y2K38_SAFETY findings stands. The alternative reading,
    that truncating an uptime is an environment invariant because it needs
    decades of uptime, is the argument the lane rules out. `reading.md` no
    longer carries that example.
  - **Intent claims got a lane of their own:** well-defined code whose
    author's intent is in doubt. They are MISSING_BREAK, SIZEOF_MISMATCH,
    COPY_PASTE_ERROR (which the run left in Other, with no verdict), and
    DEADCODE and UNUSED_VALUE. The run's value-or-path reader had settled
    those last two as intent questions rather than path questions: 4 of its
    14 findings.
  - **Rule matches got Policy,** which takes no triage.
  - **Lane assignment moved to a checker table,** with inference kept for the
    checkers whose findings vary.
- **Readers were not independent of the examples.** Several examples in
  `references/reading.md`, `references/lanes.md` and `references/records.md`
  come from the same corpus the run read. A reader given the shape of an
  answer is not a blind reader, so examples should come from the skill's own
  fixtures. Open.
- **By-catch had no place, and went into `reason`.** One reader reported two
  possible defects beside the findings it was given, and the skill's own
  text said to mention a bycatch in `reason`.
  - **Why that was wrong:** `reason` travels with the records, into Connect
    and to whoever the report is shared with. By-catch has no CID, and in
    code that is not yours it may be an unreported vulnerability.
  - **The convention now:** by-catch goes to the run's `bycatch/` folder, or
    a folder the caller names (`references/records.md`, *By-catch*).
    `assemble` collects it into `bycatch.json` and prints one stdout line.
    The report says nothing about it.
  - **The backstop:** `records.py` refuses a verdict that carries a by-catch
    field or the usual by-catch phrasing, and a malformed by-catch file.
  - **Status:** measured on the fixture. That readers follow the convention
    is reasoned, since no reading run has used it yet.

## Reasoned, not measured

- **Accuracy.** No verdict here was compared with a reference. A second
  reading of the run's 23 verdicts, against the code and callees each one
  cites, found every argument held. That is a reading, not a reference. The
  run tested the mechanics.
- **The checker table.** Its 284 rows are exactly the checkers Coverity
  2026.9.0 lists (`cov-analyze --list-checkers`), in every language.
  Coding-standard rules (MISRA, AUTOSAR, CERT) are not in that list, and
  have no rows.
  - Its 96 C rows were placed from each checker's description in the
    2025.9.0 checker reference, not from findings. Only 13 of them have met
    real findings, all on proftpd.
  - Eleven C++-only rows were added when a C++ analysis (Coverity 2026.9.0,
    defaults plus `--security --distrust-all`) reported checkers the table
    did not have. Each was placed from its description in the 2026.9.0
    checker reference, with the events of one finding read. Four of them
    are performance checkers (COPY_INSTEAD_OF_MOVE, UNNECESSARY_STRING_COPY,
    AUTO_CAUSES_COPY, MISSING_MOVE_ASSIGNMENT), placed in Policy like
    PASS_BY_VALUE; UNINIT_CTOR is Intent, since it reports a member left
    unset, not a read of it.
  - The other 177 rows (C and C++, CUDA, Java and the JVM languages, C#,
    and the scripting and web languages) were placed from their
    descriptions in the 2026.9.0 checker reference. A model drafted them by
    language family with the tests in `references/lanes.md`, and each row
    was then reviewed. Two changed in review: DISTRUSTED_DATA_DESERIALIZATION
    went to Policy (its reference calls it an audit checker that claims no
    vulnerability), and CONFIG.ENABLED_DEBUG_MODE to Construction (like
    CONFIG.ENABLED_TRACE_MODE). None of the 177 has met a real finding.
  - Which checkers vary enough to need candidates, and which candidates
    they get, is reasoned from those descriptions.
  - A checker that is not in the table (one from a later release, a
    coding-standard rule, a custom checker) is unplaced, and its checker is
    placed once before anything runs.
- **Compiler headers.** The directory list is written from the compilers'
  documented layouts. On real findings only libstdc++'s and GCC's own were
  met: 18 of 225 merge keys in a C++ analysis on Linux, all in
  `/usr/include/c++/<version>/` or `/usr/lib/gcc/.../include/`. Clang's and
  MSVC's directories have met only the fixture.
- **Releases and the delta.** `--prior` has run only on the fixture. No
  multi-release dataset has been triaged release by release yet. Not
  measured: whether `connect_apply.py` finds a merge key that the stream's
  latest snapshot no longer reports. Its search names no snapshot, so that
  depends on Connect's default scope. Applying each release's records before
  the next release's snapshot is committed avoids the question.
- **The Intent lane's questions.** No reader has run them yet.
- **Policy.** No Policy finding has gone through; none fired on proftpd at
  analysis defaults.
- **The execution method end to end.**
  - The mapping from `coverity-verify`'s tiers (`references/records.md`) is
    written from verify's documented tiers, and no finding has yet gone
    through triage into verify and back.
  - The route preference and the carried-over route fields follow verify's
    documented record (`route`, `as_code`, `stubbed`).
- **Applying records to Connect.**
  - The records use the attribute names of Connect's triage-store export and
    the REST triage write.
  - `connect_apply.py` has run against the fake Connect in
    `evals/test_tools.py` only, in 13 cases. They cover a plan that writes
    nothing; an apply that skips a finding someone triaged; a second apply
    that writes nothing; `--overwrite`; a record not in the stream; a value
    that does not take, caught by the read-back; and refusals for a missing
    attribute or value, a file that is not a records file, an unknown
    stream, and a project name that is not the stream's.
  - On a real Connect 2026.9.0, a plan-only run (no `--yes`) of the tool
    itself was made against a stream of 112 findings. The records file was
    built for the test from 3 of the stream's merge keys and 1 that does not
    exist. The plan came out as expected: 2 to set, 1 left alone because it
    was already classified, and 1 not found. Nothing was written.
  - The same server answers a project name it does not know with HTTP 500
    and "Project <name> not found", not an empty result. The tool's refusal
    adds the stream's own primary project to that message.
  - The triage PUT itself has not been sent to a real server yet.
- **Other Connect versions.** The REST path and the request bodies were
  measured on one 2026.9.0 server only. An older Connect may serve
  `/api/v2/attributes` instead, or neither.
- **Model choice per lane.** One model was used for every step. Whether a
  cheaper model suffices for some lanes is untested.
