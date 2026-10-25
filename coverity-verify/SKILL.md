---
name: coverity-verify
description: >
  Verify a Coverity finding by execution: confirm or refute it by running
  it, instead of by reading it. Verification is the general capability;
  the one method here is fuzzing the slice set -- every function that
  carries a primary event of the finding, as real code -- under stubs from
  Coverity's own derived models for the callees outside it, which is deterministic and uses the analyzer's own
  data. The skill first decides whether a finding is a candidate for that
  method -- claims a sanitizer or an assertion can judge inside one
  function -- and reports the rest (injection classes, anything a clang
  harness cannot instrument) as "not a fuzz-triage candidate; suggest
  external verification", with the reason, instead of attempting them.
  The method runs on one of two routes: harness-verification (the TU's
  real source compiled as-is with its recorded flags, a driver, model stubs
  only for the externals the TU does not define; the default, being the
  less expensive) or extraction-verification (the slice set from the emit,
  model stubs outside it). The caller names the route it prefers; the
  router checks whether it applies to the program and, when it does not,
  asks in an interactive session and reports and stops in a
  non-interactive one, never switching route on its own. Formerly
  coverity-fuzz-triage, which remains
  as an alias. The finding
  may be a Connect CID ("verify CID 12345"), an entry in a
  cov-format-errors findings file, or a candidate from a path-insensitive
  shape checker. Use this skill for "verify this finding", "verification",
  "run the verify skill", "is this defect real",
  "confirm the candidates", "can this null actually arrive", "fuzz this
  function", "verify the report before I file it", "give me execution
  verdicts", and for the question behind them all: whether an analyzer
  claim about a function, or a short chain of them, is reachable in
  execution. It also answers
  "was this fixed or just silenced?", "check this fix", "the finding is
  gone in the new version -- did the change fix it?", "is this PR a fix
  or a suppression?": the fix check (Step 5) verifies the finding on the
  old code, re-runs the same verification on the new code with the claim
  re-armed past the change, and says whether the change fixed the defect,
  silenced the analyzer on a real one, or quieted a false positive without
  changing behaviour. The method, fuzz
  under model stubs: the slice set as one standalone file
  (coverity-function-slice), a stub for every callee outside the set,
  generated from Coverity's OWN derived model of it
  (cov-find-function --save, so the callees behave exactly as the analyzer
  believed they do), a libFuzzer harness whose one input chooses both the
  arguments and every stub behaviour, the finding's own claim checked and
  counted at its line, and a sanitizer as the oracle. A crash at the
  finding's line, with the stub choices that produced it, is a
  confirmation the analyzer would have accepted -- and those choices are
  the list of callee behaviours to check against the real callees, which
  is where most of the false positives in a real batch were settled. Ten
  proftpd findings went through it: none confirmed, eight refuted with
  execution evidence, and one real overflow found next to a false one.
  Requires the Coverity installation that wrote the intermediate
  directory and clang with libFuzzer and AddressSanitizer: under WSL for
  an idir captured on Linux (LP64 and glibc, like the capture), clang-cl
  on Windows for one captured with MSVC.
---

# Coverity verify

A finding is a claim: *some path reaches this line in this state*. The
analyzer reported it under a bound on its own work; a fuzzer can settle it
by reaching the line. This skill turns one finding into an executable
question and lets execution answer it. **It is the verification stage**,
and execution-based verification is the general capability: a Connect CID
a user hands over, a batch from a findings file, or the candidates
`coverity-pathout` collects from functions that reached the path bound are
all the same input once Step 0 has named the claim. One method is built,
fuzzing under model stubs, and the first thing the skill does is decide
whether the finding is a candidate for it (*Methods*); the rest are
reported, not attempted. Run on a batch, verification is the execution
method of `coverity-triage`, which assigns each finding a lane and hands
the value-or-path ones here when the plan says so. On a real batch the
method was better than a reading triage in one specific way: every refutation came with the
behaviour the analyzer had assumed, and one real defect came out beside a
false one. The same machinery, run twice, answers a second question that
reading cannot: when a finding disappears between two versions, did the
change fix the defect or silence the analyzer (Step 5).

**The common case is a definitive answer on one finding, in place of
triage.** Neither a human nor a model classifier is perfect, and setting
models to debate a defect costs more time and tokens than running the
code. So "run the coverity verify skill" on an open finding means: verify
it, now, and report the tier. **The skill exists to accomplish a task,
not to hold a conversation about it.** The mode is read from the input:
a finding that is still open is verified (Steps 0-4); a proposed fix in
hand (a patch, a pull request, a commit, a second version of the code or
a second idir) means the fix check (Step 5). The Coverity version is in
the idir, the platform follows the capture, the claim comes from the
events, the budget has a default. Decide those, state the decision in the report,
and run. What the skill cannot decide -- which idir, when none was named
and none is findable; whether to pay for the other route when the
preferred one does not apply -- is a question **only in an interactive
session**. Non-interactive (an API call, a scheduled or CI run), or unsure
which: report exactly what is needed, record the finding as not verified
for that reason, and stop; never default into the more expensive option.
An interactive session can always be prompted to continue; an unattended
one cannot be asked, so it is told.

This skill was `coverity-fuzz-triage`; that directory is now an alias
pointing here.

Read `coverity/RULES.md` first (rules 3, 21-23, 35).

**This skill is one of a bundle of three** in the CoveritySkills
repository. It needs `coverity-function-slice` beside it (Step 1 calls its
slicer by relative path) and is called by `coverity-pathout` for the
candidates it collects from functions the analyzer did not finish. If you
have only this file, clone the repository and work from the clone:

```bash
git clone https://github.com/edtice-goog/CoveritySkills
```

## Methods: decide first

One method is built: **fuzz under model stubs** (Steps 1-4). It is a
sensible Coverity skill because it is deterministic and runs on the
analyzer's own data: the slice set as the emit holds it, the callees
outside it as the derived models describe them, the claim as the checker
stated it.
Before Step 1, decide whether the finding is a candidate for it:

| the finding's claim | decision |
|---|---|
| a property of one function's own state that a sanitizer or an inserted assertion can judge at a line: null dereference (`FORWARD_NULL`, `NULL_RETURNS`, `REVERSE_INULL`), overrun and underrun (`OVERRUN`, `STRING_OVERFLOW`, `BUFFER_SIZE`), `DIVIDE_BY_ZERO`, `USE_AFTER_FREE`, double free, `NEGATIVE_RETURNS`, `INTEGER_OVERFLOW` feeding a size, `DEADCODE` and `UNUSED_VALUE` through an assertion, and every candidate from the shape catalogue | **a fuzz-triage candidate**: continue with Step 1 |
| untrusted data reaching a sink unneutralised (`SQLI`, `OS_CMD_INJECTION`, `PATH_MANIPULATION`, `XSS`, the `TAINTED_*` family), a property of a resource outside the process (`RESOURCE_LEAK` across a connection, a file-system race), a concurrency claim (`LOCK`, `ATOMICITY`, `MISSING_LOCK`), or anything else a clang harness cannot instrument and no sanitizer judges | **not a fuzz-triage candidate; suggest external verification.** Report that as the verdict, with the reason (which sink, which property, what a harness cannot observe), and stop. Do not deliver a payload, drive a server, or improvise an oracle |

The second row is deliberate, not a gap to fill here: delivering an SQL
injection payload is a job for the specialty tools that exist for it, and
not a good use of a Coverity skill. **Open item**: whether and how other
verifications are suggested, named, or wired in is under discussion and
not designed; nothing in this skill should be read as a plan for it. Until
that is settled the output for such a finding is the verdict tier above.

### Then the route: the caller's preference, and whether it applies

The one method runs on one of two routes. Both end in the same Step 4
tiers; the verdict record names the route, what ran as code and what was
stubbed.

| route | what runs as code | what is stubbed | cost and fit |
|---|---|---|---|
| **harness-verification** (`tools/fz_harness.py`; the default) | the whole TU, its real source compiled as-is with the compiler flags the capture recorded, a driver linked in, the original function run unchanged | only the externals the TU does not define, from their derived models (libc stays real) | the less expensive route: no slicing, one compile, and the real callees in the same file carry their own semantics instead of their models'. It is extraction with the slice set widened to the whole TU and the pretty-printer taken out, so the slice-set rule holds unchanged: nothing on the finding's path is a stub, and a stub list naming a function the finding's events touch is malformed here too |
| **extraction-verification** (Steps 1-3 as written) | the slice set, printed from the emit by `coverity-function-slice` | every callee outside the set, from its derived model | the route for a program the harness route cannot take, or a defect class the table has learned needs it: the function alone, with the stubs' choices as the point |

**The caller names the route it prefers.** A batch from `coverity-triage`
carries it in the table row behind the method `Execution:
coverity-verify`; a CID or a findings-file entry given directly takes it
as `--route harness|extraction`. **The shipped default is harness**, for
every caller including `coverity-pathout`'s shapes, because the cheaper
route is preferred until evidence says a defect type needs the other; the
table moves on that evidence, and `CALIBRATION.md` records, per public
finding tried, whether harness sufficed. A user whose program is not
amenable overrides the preference for that program.

`tools/verify_route.py --manifest <dir> [--route harness|extraction]
--compile` checks whether the preferred route **applies** to this program
and records the reason; it does not pick a route. For harness, in order:

1. **The TU manifest's notes** (`coverity-function-slice`'s
   `tu_manifest.py`: the TU's source from `print-source`, its recorded
   compiler invocation, the functions it defines, its externals and
   whether each has a model, the target and whether it is static). A note
   about captured headers the emit could not supply, or C++ construction
   the driver cannot reproduce, means harness does not apply.
2. **A compile attempt.** `clang -fsyntax-only` on the TU with the
   recovered flags, from the TU's own directory so relative `-I` paths
   resolve (under WSL for a Linux capture). A failure is recorded in the
   compiler's words and means harness does not apply. Measured on
   proftpd: the TUs compile this way from the source tree the capture was
   built in.
3. **Externals without a model** are a count in the record, never a
   reason: they get generic stubs, which weakens a verdict that leans on
   them, and the record says so.

A static target does not stop the harness route: `fz_harness.py`
`#include`s the TU into the target file instead of linking it, so the
driver can call the function, and the record says the TU was included.

**When the preferred route does not apply, the skill never switches route
on its own.** The other route costs more, and whether to pay is the
caller's call:

- **Interactive session** (a person is at the prompt): state why the
  preferred route does not apply, in the compiler's or the manifest's
  words, and ask whether to run the other route. Run it only on a yes.
- **Non-interactive** (an API call, a scheduled or CI run, a batch nobody
  is watching), **or unsure which**: report the reason, record the
  finding as *not verified: <preferred route> does not apply: <reason>*,
  and stop. A later interactive session can continue from the record.

On the harness route the only edit to the TU's text is the inserted claim
line (`tu.fz.c`, one line, recorded with its line number), and the driver
defines the globals the TU reads but does not define, exactly as a harness
defines a slice's `extern` globals.

## What makes the method honest

Four things, and each one is the answer to a way this could lie:

- **The stubs are the analyzer's models, not guesses.** Coverity has
  already derived, for every function it analyzed, what it believes that
  function does. A stub written from that model can only take behaviours
  the analyzer already granted the callee, so a crash through the stub is
  a path the analyzer would have accepted as feasible. A hand-written stub
  that returns NULL where the real callee never can confirms nothing.
- **A function on the finding's own path is code, never a stub.** The
  target is a *slice set*: every function that carries a primary event
  in the finding's event chain, sliced as real code into one file. Only
  functions outside that set are stubbed. A stub for a function on the
  path reproduces the analyzer's belief about it, not its code, and a
  model edge can make the stub do exactly what the finding claims; a
  confirmation through it is circular, and a refutation through it is
  the analyzer re-reading its own summary. One function is the common
  case; a caller-and-callee pair where both carry events is the case
  the rule exists for. (A callee that carries no primary event stays a
  stub: the subversion case below, where two stubbed callees on the
  chain brought a NULL_RETURNS back, is unchanged.)
- **One input chooses everything, and every choice is traced.** The fuzz
  input feeds the target's arguments *and* every stub's branch choice, and
  the run prints the choices behind a crash. Those are the callee
  behaviours the confirmation relies on. On proftpd every "confirmation"
  relied on one that the real callee cannot have (a copy that does not
  equal its source; a loader that does not write the global it loads
  into), because the model over-approximates or is silent. The trace is
  what makes that checkable.
- **The finding's claim is checked at its own line, and counted.** A run
  that reaches the line 300,000 times and never finds the claim false is
  evidence, not silence; a run that never reaches the line is not.
- **Values the harness supplies get their own tiers.** A harness can hand
  NULL to any parameter, any global, and make any function-pointer hook
  return. Those are reported as *parameter-sourced*, *global-sourced*,
  *hook-sourced*, never as confirmed.

## Step 0: Pin the installation, the platform, and the claim

**From a CID.** A real user hands over a Connect CID, not a findings file.
The CID lives in Connect; the events live in the intermediate directory
that produced the stream's snapshot. Two commands bridge them:

```bash
python3 tools/cid_lookup.py lookup --url <connect-url> --cid 12345 --stream <stream>     # key: ~/.coverity/ak-<host>-<port>
$BIN/cov-format-errors --dir <the idir behind that snapshot> --json-output-v10 findings.json
python3 tools/cid_lookup.py select --findings findings.json --merge-key <from lookup>
```

A CID lookup needs no skill -- any REST client, or the Connect UI, gives
the same five fields -- so do it however is quickest; the tool exists so
the merge key lands where Step 0 wants it. `lookup` asks Connect over REST
(HTTP Basic with an authentication key,
exactly as the `coverity` skill's *Connecting to Coverity Connect*
describes: key under `~/.coverity/`, never in a repository; URL from the
user, never from the key; check the key first with `connect_auth.py
check`) for the stream, checker, file, function, line and **merge key** of
the CID in a snapshot (the stream, or project, filter must accompany the
cid filter: alone the cid filter returns nothing, measured). `select` finds the same issue in the idir's own
findings by merge key (stable across runs, rule 27) and prints the events.
The idir is the one the user analyzed and committed; if only Connect has
the snapshot, re-analyze the same capture with the same version and
options (`cov-format-errors` reads an idir, not a server). From here on a
CID is a findings-file entry.

`<idir>/emit/version` line 1 names the Coverity version; use its `bin/`
(rule 3). The build platform follows the capture: an idir captured under
Linux or WSL is built and fuzzed **under WSL** (`clang -fsanitize=fuzzer,
address`; the slice's types are LP64 and its libc is glibc, and clang-cl
would silently change `long` to 4 bytes and lose `__errno_location`); an
MSVC capture uses clang-cl on Windows. Then, per finding, write down
before building anything:

| from | you need |
|---|---|
| the finding (a CID via `cid_lookup.py`, a `cov-format-errors --json-output-v10` entry, or the shape checker's candidate) | the **slice set**, the TU of each member, and the **claim as a C expression that must hold** at the finding's line (a line in one member, the finding's home function): `ptr != NULL` before `*ptr = 0`; `delay_tab.dt_data != NULL` before the `memcpy`; for an OVERRUN, `1` (a reach counter; ASan is the oracle) |
| the events | the **primary-event functions**: each event in a v10 entry (and in `cid_lookup.py select`'s listing) has a file and a line but no function name, and `functionDisplayName` names only the finding's home, so resolve each event's `file:line` to the function whose definition contains it -- `cov-manage-emit --dir <idir> --tu <N> find '^<name>$' --kind f --print-definitions` prints `declared at: file:line` for a candidate, and `--tu <N> print-source` gives the captured file to read the definitions from; the owner is the last definition in that file declared at or before the event's line, and the quick test for a whole finding is `--tu <N> find . --kind f`: C functions do not nest, so when no definition in the file is declared inside the path events' line range, every event is in the home function. **Skip the `example_*` events**: they are the statistical evidence a `NULL_RETURNS` or `CHECKED_RETURN` cites from other call sites, usually in other files, and name no function on the path (counting them turns every such finding into a five-function "set"). The distinct owners are the slice set. Then the callee the finding **blames** (the one whose return or effect makes the claim false), the branches the analyzer took, and a seed input that follows them |
| the checker | the oracle: ASan for dereferences, overruns and use-after-free; the claim check for anything that does not crash (`REVERSE_INULL`: the analyzer's claim is "never NULL at the check", so `arg != NULL` before the check) |

Read the slice set once, so the claim and the blamed callee are right.
Then build. "Run the verify skill" asks for an execution verdict, and a
refutation by reading goes beside it as a note, not in its place; the
only findings that skip the build are the ones routed out in *Methods*
and the *model says impossible* tier, where no model edge can produce the
bad value.

## Step 1: The slice set as a file

```bash
python3 ../coverity-function-slice/tools/slice_function.py --dir <idir> --bin $BIN --tu <N> \
    --name <home fn> [--name <member>[@<tu>] ...] --out <work>/<fn> --emit
```

One `--name` per member of the slice set, the home function first; a
member in another TU is `name@tu`. One member writes `<fn>.slice.c`, a set
writes `<first>.set.slice.c`: the shared declarations, a prototype for
every member, then every member's definition as real code, each seeing
the others. Line 1 is `/* slice-set: a, b */` in `--name` order, and that
line is what Step 3's assembler reads; callees outside the set stay
prototypes in the `/* callees */` block, and a member never appears there.
`cov-emit: emitted` is the check; `NOT EMITTED` means a pretty-printer form to hand-edit first
(`coverity-function-slice`, Step 2: dropped cast parentheses, a VLA
printed as `char a[]` with its dimension in a comment).

## Step 2: Models for every callee

```bash
$BIN/cov-find-function --dir <idir> --save -of <work>/models --module generic <callee>   # per callee, ~3 s
```

Do it for every project callee the slice's `/* callees */` block lists
that is **outside the slice set** -- never for a member: a member's model
must not be in the index, and if one is, the build log must say it was
ignored -- and keep an `index.txt` of `name <key>.generic defs=N` lines (the
assembler reads it; a callee with several definitions lists one model per
definition, pick by source file). libc names are left to the real
library. `--save` writes `<key>.generic.dot`, an automaton whose edges are
what the analyzer derived: `returnsnull`, `<return value> <- == -1`,
`negative_return`, `identity(<arg 1>)`, `afm_alloc(...)`, `dereference(<arg
0>)`, `write(<arg 0>->last)`.

Two things the generic model does not carry, and they decided four of ten
proftpd findings: **it never says a copy equals its source** (`pstrdup`'s
model is "allocates, may return null"), and **it records no writes to
globals** (`delay_table_load` mmaps into `delay_tab.dt_data`; the model
has no edge for it). The first is answered by `--semantic`; the second is
the *model gap* verdict below. A third gap is not the model's but the
run's: a model used for a function that carries a primary event. That is
not a gap in what the analyzer knew, it is the analyzer's belief standing
in for code on the very path under test, and no verdict survives it; the
function goes into the slice set and the run is repeated.

## Step 3: Assemble, build, run -- focused first, then free

On the harness route Steps 1 and 2 change shape: there is no slice (the
TU is the code) and models are saved only for the externals the manifest
lists; `fz_harness.py --manifest <dir> --models <dir> --driver driver.c
--claim .. --before .. --out <dir>` writes `tu.fz.c`, `target.c`,
`route.json` and the build command (`build.sh` from the TU's directory;
`build.bat` for a Windows capture). The focused/free discipline, the
seeds and the reading of the run are the same from here on.

```bash
python3 tools/fz_target.py --slice <fn>.slice.c --models <work>/models --harness harness.c \
    --claim '<expr>' --before '<regex of the finding line in the slice>' \
    --pin-normal --free <blamed callee>[,..] [--semantic pstrdup,pstrcat] --out target.c
clang -g -O1 -fsanitize=fuzzer,address -Wno-everything -I tools target.c -o fz     # WSL; clang-cl -fsanitize=fuzzer,address -Zi -Od on Windows
./fz -max_total_time=60 -seed=1 -detect_leaks=0 -timeout=10 [seeds/]
```

`fz_target.py` reads the slice set from the slice's first line
(`--slice-set a,b` overrides it), compiles every member as code and never
stubs one -- a model saved for a member is ignored and the log says so --
then classifies every callee outside the set (real libc / model stub with
its behaviours listed by index / `NO MODEL` generic stub), inserts
`__fz_claim(<expr>)` before the first line matching `--before`, and
appends the harness. Its log begins with `slice set: ...`; a member named
there without a definition in the slice is reported and the target will
not link until it is sliced into the set. `tools/fz_support.h` supplies the byte stream, the
choice trace, the pins, the per-input arena and the claim counter.

- **Focused mode** (`--pin-normal`) holds every stub to its normal
  behaviour (non-null, allocating, zero or positive return) and leaves only
  the `--free` callees fuzz-driven. This is the run that answers the
  question: without it, every proftpd run ended on a *bycatch* -- some
  pool allocator's `returnsnull` edge, unchecked by the code, crashing at
  `c->argv[0]` before the finding's line was ever reached. Three in a row
  on one function.
- **Free mode** (no `--pin-normal`) is the bycatch run: what else the
  models allow. It found a real one-byte stack overflow next to a false
  OVERRUN in `glob_limited`, in a branch Coverity had not reported.
- **`--semantic`** gives named copy/alloc helpers their real semantics
  (`pstrdup`, `pstrndup`, `pstrcat`, `palloc`, `pcalloc`), because a stub
  that returns an unrelated buffer where the code copied a string
  confirms claims the callee cannot produce.
- **Seeds**: put an input that follows the analyzer's events in `seeds/`
  (a `"syslog:"` prefix took the finding's line from once in 7,617 inputs
  to hundreds of thousands of times).

The harness is per target and its entry point is the finding's home
function (the member whose line carries the claim); `evals/harness.c` and
the proftpd ones in the calibration are the pattern: `FZ_BEGIN(data, size); FZ_PINS_DEFAULT();`,
then define every global the slice declares `extern`, then build the
arguments -- scalars from `fz_take()`, strings from `fz_string()`, pointer
parameters from `__stub_object(64)` (memory filled with pointers to
itself, so every field points somewhere valid; set the **integer fields
that bound loops** yourself, they read as large values), and a choice byte
only where the finding is about the parameter, the global or the hook
itself.

## Step 4: Read the run and give the verdict its tier

| verdict | meaning |
|---|---|
| **not a fuzz-triage candidate; suggest external verification** | decided before Step 1 (*Methods*): the claim is about a sink, a resource outside the process, or anything a clang harness cannot instrument. Say which, and what an external verification would have to observe. The skill stops here for this finding |
| **refuted by reading** | the finding's variable is reassigned, asserted, or otherwise guarded in a way the analyzer did not see; say what |
| **refuted by execution** | focused run: the finding's line reached N times, the claim never false, with real libc semantics or `--semantic` copies where the claim depended on them. Evidence, not proof: say N and the budget |
| **refuted by execution, a path the analyzer missed** | the claim was false at the line in a way that refutes the *finding* (REVERSE_INULL on `dolist`: the check is reachable with `arg == NULL`, so it is not redundant) |
| **model says impossible** | no callee model on the path has an edge that produces the bad value; needs no build |
| **confirmed by crash under model stubs** | the claim was false at the line; **list the stub choices**, then check each against the real callee. Only when every behaviour relied on is one the real callee has is this a defect. A stub list that names a member of the slice set makes the record malformed: say so and re-run with that function as code |
| **model over-approximates the callee** | the crash relied on a stub behaviour the real callee cannot have (a copy without its source's slash). Refuted; `--semantic` or a user model closes it |
| **model gap** | the crash relied on the model's silence: a global the callee writes and the model does not record (`session.d`, `delay_tab.dt_data`). Refuted for the finding; the gap is the analyzer's false positive too, and a user model fixes both |
| **parameter-, global-, hook-sourced** | the harness supplied the NULL (a parameter, `main_server`, `tpl_hook.fatal` returning). A question about callers and configuration, not this function |
| **unconfirmed after N seconds** | the line was reached but not often, or not at all; say which. Not a refutation |
| **bycatch** | a crash elsewhere in the slice set under a model-permitted behaviour (an unchecked `returnsnull`, an overflow in another branch). Report it separately; it may be real |

For a confirmed finding the reproduction is the crashing input plus the
stub choices, and the thing to check against the real callees is the list
of behaviours those choices selected. For a refuted one the reason and
the reach count are the deliverable. Every verdict record names the
**route** with its reason, what ran **as code** (the slice set, or the TU
with the functions it defines) and, separately, the **stubbed callees**
with the branch choices taken; the two lists never share a name, and a
record in which they do is malformed on either route.

## Step 5: The fix check -- fixed, or silenced?

A finding present in version A and absent in version B has two readings:
B fixed the defect, or B changed the code in a way the analyzer can no
longer follow and the defect is still there. An initializer, a cast, a
guard that returns without reporting, a helper the analyzer has no model
for, an annotation: each removes the finding, and only some of them remove
the defect. On a false positive that is harmless, and still not a pattern
to recommend (it can break code, and it leaves a later reader or tool a
line that does nothing). On a true positive it removes the evidence and
keeps the defect. The fix check runs the verification twice and reads the
two runs together; the second run is cheap because the first built
everything. `references/fix-check.md` has the full procedure, the OpenSSL
case that produced it and the fixture that calibrates it.

**This step is selected by the input, not offered as an option.** A
proposed fix in hand (a patch, a pull request, a commit, a second version
or a second idir) means the fix check; an open finding with no fix in
hand means Steps 0-4 and nothing more; "do you also want the fix
checked?" is not a question to ask. Someone who verified a finding, fixed it and trusts the
fix has no need of this; it is for the reviewer doubting a fix someone
else made, and for a batch of findings that disappeared between two
versions where the question is which changes deserve a second look.

**Inputs.** Two idirs and a merge key present in A's findings and absent
from B's; or one idir and a patch or PR; or one idir and the commit that
removed the finding. Each reduces to **two copies of the slice set that
differ only in the change**: slice both, or slice one and apply (or
reverse) the hunk. Diff the bodies and the blamed callee's body first, and
say so if they differ in more than the change.

**Which fixes.** A user can check every finding that disappeared; most
will want the suspicious ones picked out. Check a change when it touches
only the finding's variable or line and is an initializer, `memset` or
default assignment, a cast or `(void)`, a guard whose only effect is a
silent `return`/`continue`, a use moved into a helper, macro or call
through a pointer, a `/* coverity[...] */` or other suppression, or a copy
through an opaque function; when the finding's line is unchanged and
something else removed the finding; and whenever the commit message says
silence, quiet, appease, warning, false positive, or names the analyzer.
Report "fix not checked: the change alters what the code does" for a
change that adds real handling, changes a size or a contract, or removes
the use, unless the user asked for every one; and "not checkable this
way" when the home function is gone from B.

**Procedure.**

1. Verify F on A (Steps 0-4); keep the claim, the stubs, the harness and,
   for a confirmed finding, the crashing input `c`.
2. **Toggle**: `cov-emit` and `cov-analyze` B's copy and B's copy with
   the change reverted, with the recorded emit flags. The finding must be
   in the reverted copy and absent from B's; in neither means *not this
   change*. "The merge key is gone" is weaker than this.
3. **Re-arm the claim for B.** A vacuous claim is the failure mode of the
   whole check: it reports every silencing change as a fix. A callee the
   change introduced is **real code, never a stub** (slice it, or `--keep`
   it and compile its body in; a stub for a function the analyzer could
   not see is as blind as the analyzer was). A change that satisfies the
   claim by construction (an initializer for an `UNINIT` claim) is poisoned
   or checked past: `__msan_poison(d, 1)` before the callee call turns "is
   `d` initialised at the read" back into "did this call write `d`". To
   detect rather than recognise a vacuous claim, run B with the blamed
   callee pinned to the behaviour that made the claim false on A; if the
   claim still never fails, the change satisfies it by itself.
4. Run B with the re-armed claim: replay `c`, then fuzz under A's budget.
5. **Differential run**, A against B: both copies in one file, the old one
   renamed, the same input and starting state into both, real callees
   where the claim depends on them, a trap when outputs or state differ.
   For a true positive: does B differ from A on `c`, and is it right there
   (a functional oracle when one exists)? For a false positive: does B
   differ from A anywhere?

| F on A | the change, by execution | verdict on the change |
|---|---|---|
| confirmed (input `c`) | B's re-armed claim never fails; B differs from A on `c` and is right there | **fixed** |
| confirmed | B's re-armed claim fails on `c`, or B is identical to A on `c`, or still wrong there | **silenced, not fixed** |
| refuted | identical to A everywhere in the differential run | **silencing change, behaviour-neutral**: harmless; nothing to fix; not a pattern to recommend |
| refuted | differs from A somewhere | **the "fix" changed behaviour**: review it as the code change it was |
| any | the toggle shows the finding absent from the reverted copy too | **not this change**: something else in B removed the finding |
| any | not taken past the sorting rule | **fix not checked**, with the reason |

The verdict says what the change did to the code. Upstream may have known
exactly what it was doing, as OpenSSL did when it quieted a false
positive with an initializer; whether to keep such a change is the
owners' call, and the report gives them the evidence for it.

## Reporting

Per finding: the claim, the route with its reason (and the compile
attempt's outcome when there was one), what ran as code, the stubbed
callees with their choices, the verdict with its tier, and the evidence line
(reach count and inputs; the crash frame and input with the stub choices;
the model edge that is missing; the source line that refutes it). Then
the totals: how many confirmed, refuted by execution, refuted by reading,
model gaps, sourced-by-harness, unconfirmed under what budget, bycatch,
how many were not fuzz-triage candidates (with the class each fell in),
and how many were not taken past Step 0 (rule 22). Mark measured vs
reasoned (rule 23). For a fix check, per finding: the verdict on A, the
toggle result, how the claim was re-armed, the differential count, and
the verdict on the change from the Step 5 table; then the totals: fixed,
silenced not fixed, silencing but behaviour-neutral, behaviour changed,
not this change, not checked with the reason.

## Anti-patterns

- Asking which mode, whether to fuzz, what budget, which platform, or
  anything else the finding, the idir and the request already settle.
  "Run the verify skill" on an open finding is a complete instruction;
  a question is for what blocks the run, not for company.
- Attempting a finding the decision step routed out: building a payload,
  standing up the server, inventing an oracle for a sink. The verdict for
  it is "suggest external verification", and that is the whole output.
- Hand-writing stubs that return NULL or garbage. A stub is the analyzer's
  belief about the callee, printed from its model, or it proves nothing.
- Stubbing a function that carries one of the finding's primary events.
  Its model can make the stub do exactly what the finding claims, so the
  confirmation is the analyzer agreeing with itself. It is slice-set code.
- Switching route on your own when the preferred one does not apply, or
  running extraction "while we are at it" after harness confirmed. The
  caller's preference is honoured; a route it did not ask for is a
  question in an interactive session and a report-and-stop otherwise.
- Declaring harness inapplicable without a compile attempt, or because
  the target is static. The record carries the manifest's note or the
  compiler's diagnostic, and a static target is reached by including the TU.
- Guarding a stub's dereference (`if (a0) *a0`). It makes the callee look
  null-safe to the analyzer and hides the finding's consequence from the
  fuzzer; measured to make a real finding vanish.
- Reporting a crash as confirmed without reading the stub choices behind
  it. Every proftpd "confirmation" fell to that step.
- Counting a crash on a parameter, global or hook the harness itself set
  as a confirmation.
- Running free mode first and reading its first crash as the answer. It
  is a bycatch until the focused run has reached the finding's line.
- Building a Linux capture's slice with clang-cl. LP64 becomes LLP64 and
  glibc becomes MSVCRT; the numbers are about a different program.
- Reporting "no crash in 60 seconds" without the reach count.
- Using a different Coverity version than the one that wrote the idir for
  `cov-find-function`; the models are per emit.
- In a fix check, running A's claim unchanged on B and calling "never
  false" a fix. An initializer makes an `UNINIT` claim true by
  construction; a default assignment does the same to a null claim.
  Re-arm it, or every silencing change reports as a fix.
- In a fix check, stubbing a callee the change introduced. The analyzer
  lost the finding because it could not see into that callee; a stub
  for it is as blind. Measured: with the helper compiled in as real code
  the hidden dereference crashed on the same input as the original.
- Calling a change "silenced" because the finding is gone and the diff is
  small. The toggle and the re-armed run are the evidence; OpenSSL's
  initializer was a silencing change on a false positive, and the report
  says that, not "silenced".

## Where other skills take over

| Question | Skill |
|---|---|
| The finding is a candidate from a function that reached the path bound, or you need the candidate list | `coverity-pathout` |
| The slice does not emit, or the target is a C++ method; the TU manifest for the harness route (`tu_manifest.py`) | `coverity-function-slice` |
| "Would checker X have found this at all?" | `coverity-defect-detectability` |
| Triage a set of findings: which lane each belongs in, a method per lane, records in Connect's fields | `coverity-triage` (it calls this skill for the execution method) |

## Layout

```
coverity-verify/                         # formerly coverity-fuzz-triage; that directory is an alias stub
├── SKILL.md
├── README.md
├── CALIBRATION.md                       # what was measured, on what, and what was not
├── references/
│   ├── fuzz-confirmation.md             # models as stubs, the harness, the proftpd batch, verdict tiers, what is not built
│   └── fix-check.md                     # fixed, or silenced? inputs, which fixes to check, re-arming the claim, the verdicts, OpenSSL and the fixture
├── tools/
│   ├── cid_lookup.py                    # a Connect CID -> stream, checker, file, function, merge key; then the idir's events
│   ├── model_stubs.py                   # a callee stub from its cov-find-function model
│   ├── fz_target.py                     # extraction route: slice set + models + harness -> target.c; members are code, never stubs; focused/free, --semantic, claim insertion
│   ├── fz_harness.py                    # harness route: the TU as-is + driver + stubs for its externals -> target.c, build command, route.json
│   ├── verify_route.py                  # the router: origin, manifest notes, compile attempt -> extraction or harness, with the reason
│   └── fz_support.h                     # byte stream, choice trace, pins, arena, pointer-filled objects, __fz_claim
└── evals/
    ├── run.sh                           # candidate -> slice -> model stub -> fuzz, on the fixture, about a minute
    ├── run_fixcheck.sh                  # the fix check on the fixture: a fix and a silencer, toggled, replayed, fuzzed; a few minutes
    ├── run_sliceset.sh                  # the slice set on a caller/callee pair: the callee as code refutes, the same callee as a stub "confirms"
    ├── run_harness.sh                   # the router and the harness route: one TU that compiles (harness, confirmed), one that cannot (declined, extraction)
    ├── evals.json
    ├── lookup.c, use.c                  # a callee with a derived model, a caller with an unguarded dereference
    ├── harness.c                        # the harness pattern
    ├── fixcheck/                        # use_fixed.c (a fix), use_silenced.c + rec_id.c (the dereference moved out of the capture), harness.c
    ├── sliceset/                        # pair.c (get_value and pick both carry a primary event), harness.c
    └── harness/                         # app.c + cfg.c (the TU and its one external), driver.c, declined/ (a header the manifest cannot supply), manifest_stub.py (stands in for tu_manifest.py)
```
