# Confirming a candidate by execution

A candidate from the shape checker is a claim about structure. The
analyzer could not say whether any path reaches it; a fuzzer can, by
reaching it. The pieces: the slice (the function as one file), stubs for
its callees generated from Coverity's own derived models, a harness that
lets the fuzz input choose both the function's arguments and every
behaviour the stubs may take, and a sanitizer as the oracle.

## Why the derived model is the stub

The slice's callees are prototypes. A fuzzer needs definitions, and the
wrong definitions give wrong verdicts: a stub that returns NULL where the
real callee never can confirms nothing. Coverity has already derived, for
every function it analyzed, exactly what it believes that function does:

```bash
cov-find-function --dir <idir> --save -of models --module generic <callee>
```

writes `<key>.generic.dot`, an automaton whose edge labels are the
behaviours: `returnsnull(<return value>)`, `<return value> <- != 0`,
`identity(<arg 1>)` (returns its argument), `afm_alloc(<return value>)`
(returns a fresh allocation), `dereference(<arg 0>)`, `write(<arg 0>->x)`,
`escape`/`noescape`. A quarter of a second per callee. When a name has
several definitions the output lists one model per definition with its
source file; pick by file. Builtins have models too (`--include-builtins`),
but link libc for real.

`tools/model_stubs.py <prototype line> <model.dot>` prints the stub: one
branch per distinct behaviour path through the automaton, selected by
`__stub_choice(n)`; `returnsnull` returns 0, `identity` returns the
argument, `afm_alloc` allocates, an unconstrained non-null return hands out
a static object, and every `dereference(<arg N>)` edge becomes an
**unconditional** dereference of that argument. Unconditional matters twice
over: for the analyzer, a guarded dereference makes the callee look
null-safe and the finding disappears (measured); for the fuzzer, the
unguarded dereference on the null branch *is* the crash that confirms a
candidate whose consequence lives in the callee.

Both ends of a call chain need their models. On subversion,
`fetch_conflict_details` passes `svn_dirent_skip_ancestor(...)`, which may
return NULL, into `relpath_depth`, which dereferences it; with only the
first stubbed the finding stayed absent, with both it came back with the
original event chain. Stub every callee on the candidate's path.

## The harness

`evals/harness.c` is the pattern. One byte stream feeds
everything:

```c
static const uint8_t *cur; static size_t left;
static int take(void) { if (left == 0) return 0; left--; return *cur++; }
int __stub_nondet(void) { return take(); }            /* every stub choice */
void *__stub_alloc(int n) { return calloc(1, n > 0 ? n : 1); }
void *__stub_object(int n) { static char obj[4096]; return obj; }
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
  cur = data; left = size;
  int id = take(); int flag = take();                  /* the target's scalar arguments */
  (void)escaped(id, flag);
  return 0;
}
```

The slice, the stubs and the harness compile together:

```bash
clang-cl -fsanitize=fuzzer,address -Zi -Od target.c harness.c -Fe:fuzz.exe
./fuzz.exe -max_total_time=60
```

Two Windows specifics, both measured: write the MSVC-style flags with a
dash (`-Zi`, `-Od`, `-Fe:`), because Git Bash rewrites `/Zi` into a path;
and put `LLVM\lib\clang\<ver>\lib\windows` on `PATH` or the binary exits
with 127 before running, for want of `clang_rt.asan_dynamic-x86_64.dll`.
`-fsanitize=fuzzer` links libFuzzer; ASan is the oracle for null
dereferences, overruns and use-after-free. MemorySanitizer is not available
on this toolchain, so an UNINIT shape needs another oracle.

## Measured

Fixture (`evals/lookup.c` + `use.c`, 2026.6.0): `lookup`
returns NULL when its argument is out of range; `escaped` null-tests the
result inside `if (r && r->value)` and dereferences it after the closing
brace. The shape checker flags `use.c:18`. The slice of `escaped` has two
prototypes; the stub for `lookup` comes out of its model with two
behaviours (non-null object, `returnsnull`). Built and run: ASan
access-violation at address 0 in `escaped`, on the line
`sink(r->id + v);`, within the first second, on the input
`0a 0a 41 0a` -- two argument bytes, then a choice byte that is odd, which
selects the `returnsnull` branch. That is the confirmation, and the choice
byte says which callee behaviour it relied on.

The full native analysis of that fixture reports the FORWARD_NULL itself,
because the fixture is small enough to finish; the point of the exercise
is the chain, which does not depend on the analyzer finishing.

## Verdicts, and their tiers

| verdict | meaning |
|---|---|
| **refuted by reading** | the finding's variable is reassigned, asserted, or otherwise guarded in a way the analyzer did not see; say what |
| **refuted by execution** | focused run: the finding's line reached N times, the claim never false, with real libc or `--semantic` copies where the claim depended on them. Evidence, not proof: say N and the budget |
| **refuted by execution, a path the analyzer missed** | the claim was false at the line in a way that refutes the *finding* (a REVERSE_INULL check reached with NULL is not redundant) |
| **model says impossible** | no callee model on the path has an edge that produces the bad value; needs no build |
| **confirmed by crash under model stubs** | the claim was false at the line; list the stub choices and check each against the real callee. Only when every behaviour relied on is one the real callee has is this a defect |
| **model over-approximates the callee** | the crash relied on a stub behaviour the real callee cannot have (`pstrdup` returning a buffer without its source's slash). Refuted; `--semantic` or a user model closes it |
| **model gap** | the crash relied on the model's silence: a global the callee writes and the generic model does not record (`session.d`, `delay_tab.dt_data`). Refuted for the finding; the gap is the analyzer's false positive too, and a user model fixes both |
| **parameter-, global-, hook-sourced** | the harness supplied the NULL (a parameter, `main_server`, a `fatal` hook that returns). A question about callers and configuration, not this function |
| **unconfirmed after N seconds** | the line was reached but not often, or not at all; say which. Not a refutation |
| **bycatch** | a crash elsewhere in the function under a model-permitted behaviour (an unchecked `returnsnull`; an overflow in another branch). Report it separately; on proftpd one of them was real |

Keep the harness-sourced tiers separate. A harness can hand NULL to any
parameter or global and make any hook return, which would confirm every
such candidate; the tiers are what stop that from masquerading as
evidence.

## The proftpd batch, and what it taught the tooling

`CALIBRATION.md` has the ten verdicts. What they taught, in the order the
tooling had to learn it: build a Linux capture under WSL; no system
headers in the support code; one stub choice per call; scalar returns
follow the model's return edges; variadic and function-pointer prototypes;
`write(...)` edges reproduced only for complete structs; `pstrdup`'s model
cannot say the copy equals the source, hence `--semantic`; a zeroed object
asserts NULL fields and a pointer-filled one makes integers huge, so the
harness sets the integers that bound loops; the arena and
`-detect_leaks=0` for long runs; seeds on the analyzer's path; and above
all **focused mode**: with every stub free, each run ended on a bycatch
`returnsnull` of some pool allocator before the finding's line, three in a
row on one function.

## What is not built yet

The stub generator handles the generic module's return, identity,
allocation, dereference and non-null write edges. It does not read the
`uninit` module, does not size allocations from types, and cannot record
global writes because the generic model does not carry them. Harnesses
are written per target from the pattern in `evals/harness.c`; generating
the argument block from the target's signature (scalars, strings, objects,
and a choice byte where the finding is about the parameter) is the next
step, and variadic targets are outside it.
