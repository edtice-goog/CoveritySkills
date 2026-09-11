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
| **refuted by reading** | the candidate's variable is reassigned or otherwise guarded in a way the shape checker cannot see; say what |
| **confirmed by crash under model stubs** | the sanitizer fired at the candidate's dereference; record the input and the stub branches it took, since those are the callee behaviours the crash relies on -- all of them are in the analyzer's model of those callees |
| **reachable only if a caller passes NULL** | the pointer is a parameter, so the harness supplied the null itself; whether any caller does is a question about the callers, not this function |
| **unconfirmed after N seconds** | nothing found under the budget; not a refutation, but if the producing callee's model has no `returnsnull` edge the analyzer's own knowledge says the null cannot arrive, which is a strong triage answer |
| **model gap** | the crash needed a behaviour outside the model; feed it back as a user model (tool-interop's enrichment loop), not as a confirmed defect |

Keep the parameter-sourced tier separate. A harness can hand NULL to any
parameter, which would confirm every such candidate; the tier is what
stops that from masquerading as evidence.

## What is not built yet

The stub generator handles the generic module's return, identity,
allocation, dereference and write edges. It does not yet read the `uninit`
module (which outputs a callee initializes), does not size allocations from
types, and emits stubs one callee at a time; wiring it into
`coverity-function-slice/tools/slice_function.py` as `--stubs`, producing `stubs.c` for every prototype
in a slice with the fuzz-driven `__stub_choice`, is the next step, and the
fixture above is its acceptance test.
