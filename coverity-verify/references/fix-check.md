# The fix check: fixed, or silenced?

A finding is present in version A of the code and absent in version B.
The usual reading is "B fixed it". There is a second reading: B changed
the code in a way the analyzer can no longer follow, and the defect is
still there. An initializer, a cast, a helper the analyzer has no model
for, a guard that returns without reporting, an annotation: each removes
the finding, and only some of them remove the defect. Upstream commit
messages say it in their own words ("false positives, but better to be rid
of the issue permanently"). Reading the diff and trusting the message is
how this is settled today. Verification settles it by execution, and the
second run is cheap because the first one built everything.

This is also the answer to a quieter risk. A silencing change on a false
positive costs nothing today but is not something to recommend: it can
break code, and it can confuse a later reader or a later tool. A
silencing change on a **true** positive removes the evidence and keeps
the defect. The fix check tells the two apart, and tells both apart from
a fix.

It is a step on request. Most people who verify a finding, fix it and
trust the fix will not run it, and need not. It is for the fix someone
else made that you have reason to doubt, and for a batch of findings that
disappeared between two versions where the question is which changes
deserve a second look. A few will run it on their own fixes; the
procedure does not change.

## Inputs, and the one shape they reduce to

| the user has | what to do |
|---|---|
| two intermediate directories (A, B) and a merge key present in A's findings and absent from B's (the demo-data output; a release-to-release comparison) | slice the function from both; the change is the token-level diff of the two bodies |
| one idir (A) and a patch or a pull request ("is this change a fix or a silencer?") | slice the function from A; apply the hunk to the slice to make B's copy |
| one idir (B) and the commit that removed the finding | slice from B; reverse the hunk on the slice to make A's copy |

Every case ends with **two copies of the function that differ only in the
change**. Check that first: diff the bodies, and diff the blamed callee's
body too. On OpenSSL the 3.0.7 function equalled the 3.2.0 function minus
one initializer, token for token, and `DES_cfb_encrypt` was unchanged, so
every conclusion about the toggle copy was a conclusion about 3.0.7. When
the bodies differ in more than the change, name the other differences and
either fold them into "the change" or say the check covers only part of
the diff.

## Which fixes to check

Given two versions, every finding that disappeared can be checked; the
cost is one slice, one emit and one fuzz run per finding beyond the
verification of A. What a doubting reviewer mostly wants is for the skill
to pick the **suspicious** ones. For each merge key in A and not in B,
where the function still exists in B, diff the two bodies and sort:

| the diff | decision |
|---|---|
| touches only the finding's variable or line, and is one of: an initializer, `memset`, or default assignment (`UNINIT`, `FORWARD_NULL`); a cast or a `(void)`; a null or range test whose only effect is `return`/`continue`/`break` with nothing reported; the use moved into a helper, a macro, or a call through a pointer; a `/* coverity[...] */` or other suppression annotation; a `volatile` or a copy through an opaque function | **check it** |
| the finding's line and variable are unchanged; something else removed the finding (a callee, a header, an option, a model) | **check it**, and expect *not this change* |
| the commit message or PR text says silence, quiet, appease, warning, false positive, or names the analyzer | **check it**, whatever the diff looks like |
| adds a handling path that does something (reports an error, frees, resizes, retries), changes a size computation, changes the callee's contract, or removes the use | **not suspicious**: report "fix not checked: the change alters what the code does", unless the user asked for every one |
| the function is gone or renamed in B | **not checkable this way**; say so |

"Suspicious" is a sorting rule, not a verdict. A guard that returns silently
is sometimes the right fix; the check is what says so.

## The procedure

1. **Verify F on A.** Steps 0-4 of the skill, as for any finding. The
   outcome is a tier and, for a confirmed finding, the crashing input `c`
   and the stub choices behind it. Keep the claim, the stubs and the
   harness: B uses the same ones.
2. **Toggle.** Copy B's function and revert only the change (or copy A's
   and apply it). `cov-emit` and `cov-analyze` both copies with the
   recorded emit flags (`<slice>/cov-emit.flags`), default checkers. The
   finding must be in the reverted copy and absent from B's. If it is in
   neither, the change is not what removed it: *not this change*. "The
   merge key is gone in B" is weaker evidence than the toggle, because many
   other lines changed between releases.
3. **Re-arm the claim for B.** The claim that confirmed or refuted F on A
   can become vacuous on B, and a vacuous claim is the failure mode of this
   whole check, because it reports every silencing change as a fix.
   - **A callee the change introduced is real code, never a stub.** The
     analyzer lost the finding because it could not see into that callee;
     a stub printed from a missing model, or pinned to its normal
     behaviour, is as blind as the analyzer was. Slice it, or compile its
     body into the harness (`--keep` it out of the stubs). Measured on the
     fixture: with `rec_id()` real, the hidden dereference crashes on `c`
     exactly as the original did.
   - **A change that satisfies the claim by construction** (an initializer
     for an `UNINIT` claim; a default assignment for a null claim) makes
     the claim true whether or not the callee does its job. Move the
     check past it, or poison past it: `__msan_poison(d, 1)` immediately
     before the callee call turns "is `d` initialised at the read" back
     into "did *this* call write `d`". On OpenSSL that re-armed claim still
     never failed over 124 M reaches, which is the refutation; without the
     re-arm the same 124 M reaches would have proved nothing.
   - **To detect a vacuous claim** rather than recognise it: run B with the
     blamed callee pinned to the behaviour that made the claim false on A
     (`returnsnull`, "writes nothing"). If the claim still never fails, the
     change satisfies it by itself, and the verdict has to come from the
     differential and functional oracles below. (Stated from mechanism;
     the OpenSSL case was recognised by reading.)
4. **Run B** with the re-armed claim: replay `c`, then fuzz under the same
   budget as A, same seeds.
5. **Differential run, A against B.** Two copies of the function in one
   file, the unfixed one renamed, both called from one harness on the same
   input and the same starting state, real callees where the claim depends
   on them, and a trap when outputs or state differ afterwards. For a true
   positive the question is whether B differs from A on `c` and is right
   there; for a false positive, whether B differs from A anywhere. "Right"
   needs a functional oracle when one exists (for a cipher, the shipped
   library); without one the most that can be said is that B behaves
   differently on `c` and its claim holds.

## The verdicts

| F on A | the change, by execution | verdict on the change |
|---|---|---|
| confirmed (input `c`) | B's re-armed claim never fails; B differs from A on `c` and is right there | **fixed** |
| confirmed | B's re-armed claim fails on `c`, or B is identical to A on `c`, or B is still wrong on `c` | **silenced, not fixed** |
| refuted | identical to A everywhere in the differential run | **silencing change, behaviour-neutral**: harmless, nothing to fix, not a pattern to recommend |
| refuted | differs from A somewhere | **the "fix" changed behaviour**: review it as a code change, because it was one |
| any | the toggle shows the finding absent from the reverted copy too | **not this change**: something else in B removed the finding; name what, if the diff says |
| any | not taken past the sorting rule | **fix not checked**, with the reason |

A silencing change is not an accusation. Upstream may have known exactly
what it was doing, as OpenSSL did. The verdict says what the change did to
the code, and leaves what to do about it to the people who own it.

## Measured

**The fixture** (`evals/run_fixcheck.sh`, Coverity 2026.6.0, clang-cl,
2026-10-07). A = `use.c`, `FORWARD_NULL` at the dereference after the
guard, confirmed on A with `lookup=1` (`returnsnull`) on `0a 0a 41 0a`.
B1 adds `if (r == 0) return -1;`: no finding; replaying `c` returns before
the line (reached 0 times); 20 s of fuzzing reached the line 4.4 M times
over 6.0 M inputs, claim never false: **fixed**. B2 moves the dereference
into `rec_id()`, a helper outside the capture: no finding; with `rec_id`
compiled in as real code the claim fails on `c` at once: **silenced, not
fixed**. A first attempt at B2 that laundered the pointer through an
unmodelled helper (`r = keep(r)`) did **not** silence the analyzer: the
finding keys on the explicit null test, not on where the pointer came
from. What counts as a silencer is measured, not assumed.

**OpenSSL** (`CoveritySkillsTesting/covdemo-openssl/ws/verify/fix320`,
2026-10-05..07, Coverity 2026.9.0 under WSL, clang 18 and gcc 13.3; the
run that produced this page, done in the testing workspace, outputs kept
there): `cipher_hw_des_cfb1_cipher`, `UNINIT` on `d[0]`, merge key
`e93ca9ad...`, A = 3.0.7, B = 3.2.0 (`unsigned char d[1] = {0};`).
F on A: refuted by execution with the real callee, 151 M reaches over
2.3 M inputs; re-poisoned per call, 124 M over 1.9 M, never false (the
model stub and the length-0 control both caught at the first reach: a
model gap, the derived model never records the write to `out`). Toggle:
B's copy no findings, B minus the initializer `UNINIT` at the read. Body
equality: 3.0.7 == 3.2.0 minus the initializer, and the callee unchanged.
Differential under MemorySanitizer with the real 3.2.0 callees: 746,679
inputs, 75.6 M bits, 0 mismatches. Verdict: **silencing change,
behaviour-neutral**, which is what upstream's commit message says. Three
siblings (CIDs 12591, 12308, 12374) gave the same result.

## Not measured

- The *the "fix" changed behaviour* row (a false positive whose "fix"
  alters behaviour) and the *not this change* row: described from
  mechanism, no instance yet.
- Automatic detection of a vacuous claim (step 3, third bullet).
