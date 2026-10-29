# Idioms: what has been learned writing models

This file is where the skill's knowledge accumulates. Each idiom says how to
recognize it (in the code, in what the analyzer reports, and in what it
believes), the model that fixes it, what the model costs, how to check it,
the fixture that shows it, and which claims were measured and which were
reasoned or taken from the documentation (rule 23). "Measured" means on the
fixture named, on the versions in `CALIBRATION.md`.

New idioms are added as SKILL.md *Step 8* describes: in neutral words, with a
fixture under `evals/fixtures/` and a case in `evals/run.sh`.

## How a user model behaves (every idiom depends on this)

- **A user model replaces the function's model; it does not add to it.**
  Whatever the derived model knew and the user model does not say is gone
  for every caller. *Measured* (`arena`, below: a bare free drops an unlink,
  and a loop that terminated becomes a double free). The customizing guide
  states the replacement (*Model search order*).
- **Search order** (documentation, *Model search order*): user model files
  in `--model-file` order, then `config/user_models.xmldb`, then **built-in
  models**, then models derived from the code in this analysis. So a
  built-in model outranks the project's own code of the same name (idiom 2).
- **Matching is by name in C, by mangled name in C++** (documentation,
  *Adding a C++ model*): a C++ model must match the signature exactly.
- **Models do not do arithmetic.** Comparisons work; `+`, `-` and bitwise
  operators are not recognized (documentation, *Adding a custom model*).
  A size written `n + 1` in a model is not the size the analysis uses.
- **A model library is tied to its version.** A later Coverity cannot read
  a model library built by an earlier one: keep the model source in source
  control and rebuild it on every upgrade (documentation, *Models and
  primitives*).
- **primitives.h is already in scope when a model compiles.** Declaring a
  type it declares is an error: `typedef unsigned long size_t;` fails with
  `error #257: invalid redeclaration of type name "size_t"`, pointing at
  `library/primitives.h`. Use `size_t` without declaring it. *Measured*
  (`pitfalls/size_t.c`).
- **A model whose name matches no function is silent.** It builds (`1
  models successfully merged into output file.`), the analysis runs, and
  nothing changes, with no warning from either tool. *Measured*
  (`pitfalls/misspelled.c`). Only positive evidence shows a model applied:
  - in `output/callgraph-metrics.json.gz`, the function's `models` reads
    `["user1", "implementation"]`, and a top-level `modelFiles` maps
    `user1`, `user2`, ... to the libraries in `--model-file` order. With no
    model matched, `modelFiles` is absent. *Measured*.
  - every event that passes through the function carries *"[Note: The
    source code implementation of the function has been overridden by a
    user model.]"*. *Measured*. A false positive that disappears leaves no
    event to carry the note, so for that case the callgraph is the evidence.
- **`--output-file <name>` writes `<name>` as given,** with no suffix added.
  *Measured*. `--model-file` is the current option; `--user-model-file`,
  deprecated since 7.7.0, was still accepted. *Measured*.

Where to read what is available: `<install>/library/primitives.h` (the
declarations), the customizing guide's *Models and primitives* chapter
(`doc/en/cov_customizing.html`), and the shipped models under
`<install>/library/generic/` (for example `common/killpath.c`, `libc/`). The
guide says never to pass those shipped files to `cov-make-library`: copy
what you need into a file of your own.

## 1. A function that ends the path where the analyzer cannot see it

**Recognize it.** A function that never returns, but gets there through
something the analysis does not follow: a function pointer or hook, a
`longjmp`, an assembly routine, an exit through a table. The findings are
false positives after a check that calls it: `if (!p) stop_now(...); use(p);`
reported as `FORWARD_NULL`, and leaks or uninitialized values on the
abandoned path. Its derived model has no edge that ends the path
(`cov-find-function --save`: the fixture's model has only
`escape(<arg 0>)`). *Measured.*

**Model.** `__coverity_panic__()`, and nothing else:

```c
void fail_hard(const char *msg)
{
    __coverity_panic__();
}
```

**Check.** The false positive is gone, and a real finding of the same shape
in a function that does not call it is kept: `first_char_logged`, which
logs and carries on. *Measured* (`killpath`: FORWARD_NULL 2 -> 1, the one
kept is the real one).

**Costs.** Every path through the function now ends there. If it returns in
some build (a release build that logs instead of aborting), the model hides
real defects in that build. State the invariant in the model's header: what
guarantees it never returns, and what would break that.

**Also.** An aborting macro must first become a function call for the
analysis (`#nodef`, documented in the analysis guide), and function
annotations can mark a function as a killpath instead of a model
(documentation, *Model for adding a killpath to a function*). Neither is
measured here.

## 2. Project code that shares a name with a built-in model

**Recognize it.** The project defines a function whose name Coverity ships a
model for, and the two behave differently. Built-in models outrank derived
ones, so **the analyzer uses the library's model and ignores the project's
code**. The shipped killpath list (`library/generic/common/killpath.c`)
includes `panic`, `fatal`, `error`, `die`, `bug`, `stop`, `assert_fail` and
more: a project `error()` that logs and returns is analyzed as never
returning, and every path through it is pruned. That hides real defects:
an escape with no false positive to point at it.

`tools/models.py inventory` lists these: `hasImplementation: true` with
`built-in` in `models`. *Measured*: a project `fatal()` and a project
`error()` both showed `["built-in", "implementation"]`, and the null
dereference after `if (s == 0) error(...)` was not reported. The same
function renamed was reported.

**Model.** Restate what the project's function really does, so a user model
outranks the built-in one:

```c
void log_msg(const char *msg);

void error(const char *msg)
{
    log_msg(msg);
}
```

**Check.** The function's `models` reads `user1`, and the hidden finding is
reported. *Measured* (`collision`: FORWARD_NULL 0 -> 1).

**Costs.** Where the project's function really does end the path, the
built-in model was right: read the code before overriding it. Every name in
the list deserves the check, not only the killpaths: the inventory lists
every project function the analyzer models from the library instead.

## 3. An arena whose destroy keeps its blocks

**Recognize it.** A pool or arena allocator: objects are carved out of an
arena's blocks, and destroying the arena returns the blocks to a private
free list rather than freeing them. The analyzer sees no free anywhere, so
nothing used after its arena is destroyed is reported. The derived model of
the destroy function escapes the blocks to a global and frees nothing:
`escape_to_global(<arg 0>->blocks)`. *Measured* (`arena`).

### 3a. Model the owner, not the arena

`USE_AFTER_FREE` tracks the freed pointer and its aliases. An object
allocated inside an arena is not an alias of the arena, so **modeling the
arena's destroy as a free does not reach uses of the objects in it.**
*Measured*: with `arena_destroy()` modeled as `__coverity_free__(a)`, the
read of a doc after `doc_close()` was still not reported.

Model the function that releases an object which owns its arena: one whose
object is the arena's first allocation, so that destroying the arena
releases exactly that object. Keep the real function's early return:

```c
struct doc;

void doc_close(struct doc *d)
{
    if (d == 0)
        return;
    __coverity_free__(d);
}
```

*Measured*: the read after close is reported (`deref_read_after_free`),
the same read of a second doc that is still open stays silent, and nothing
else changes.

**Find the owners.** In the source, a release function that destroys
`obj->arena`, where the allocation function made `obj` the first allocation
of that arena. Confirm both ends by reading; the model is only faithful when
the object really lives in the arena it destroys.

### 3b. A bare model of the arena drops what the loop depends on

A destroy function usually does more than release memory: it unlinks the
arena from its parent's list of children, among other things. A model that
only frees drops that. A loop such as `while (a->subs) destroy(a->subs);`,
which terminates because each destroy unlinks its argument, then reads as
freeing the same pointer twice. *Measured*: the bare `arena_destroy()` model
produced a `USE_AFTER_FREE` double free in `arena_clear()`. Restating the
unlink in the model removed it:

```c
void arena_destroy(struct arena *a)
{
    if (a == 0)
        return;
    if (a->parent != 0 && a->parent->subs == a)
        a->parent->subs = a->sub_next;
    __coverity_free__(a);
}
```

*Measured*, with the owner model beside it: the read after close reported,
no double free, the open doc silent.

**Costs.** A model of the arena primitives changes reasoning for every
caller of the allocator: expect findings to move in checkers that read
sizes and null returns. Whether to model the primitives at all is a choice:
the owner model alone found the defect here. *Reasoned*: modeling the
arena's allocation as an allocation (`__coverity_alloc__`) would also make
every object whose arena is never destroyed by hand a leak, unless the
model escapes it (`__coverity_escape__`) to say the parent arena reclaims
it. Not measured here.

## Not a model

Some false positives and escapes look like model questions and are not:

- **A relation between values that no single function states.** A
  `NULL_RETURNS` on `strchr(s, ':')` reached only when `s` starts with
  `"syslog:"`: the colon is guaranteed, but no model of `strchr` can say
  so. That is an assertion, a code change, or a triaged finding.
- **An environment invariant** (the machine, the deployment). It is a
  design decision with an owner, recorded in triage, not a model.
- **A heuristic misfire**: a checker matching a shape, not a path. That is
  checker tuning or feedback to the vendor.
- **A capture gap, a checker that was off, an option, or the path bound.**
  A model cannot help code or paths the analysis never reached.
