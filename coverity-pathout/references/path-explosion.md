# Why a function runs out of paths

The analysis limit is described as "the number of paths to traverse for each
function" (`cov-analyze --paths`, default 5000), and the log calls the event
`PATHOUT`. The word *paths* is the misleading part. **The engine explores the
cross product of control-flow paths and abstract state.** The same statements
are walked again whenever they are reached in a state the checker considers
different, and two paths that rejoin in the *same* state are merged and
walked once. A function with 2^14 control-flow paths can cost 100 paths or
16,000, depending entirely on what the checkers are tracking through it.

This page is the evidence for that, and what follows from it.

## The fixture: same control flow, different state

`evals/fixtures/ifs_known_vs_unknown.c` holds two functions with **identical
control flow**: 14 independent `if (unknown(k)) acc += 2^k;` statements.
Both have cyclomatic complexity 15 and a static acyclic path count of
16,384. They differ in one token.

```c
int ifs_from_zero(int a)  { int acc = 0; /* 14 ifs */ }
int ifs_from_param(int a) { int acc = a; /* 14 ifs */ }
```

Measured on 2026.6.0, default limit:

| function | CCM | APC | paths explored | result |
|---|---|---|---|---|
| `ifs_from_zero` | 15 | 16384 | **5001** | `PATHOUT=1`; `Pathed out` in `generic_DERIVERS`, `uninit_DERIVERS`, `DEADCODE_pass1`, `OVERRUN_pass1` |
| `ifs_from_param` | 15 | 16384 | **106** | completes |

With `--paths 200000`, `ifs_from_zero` completes at exactly 16,384 paths --
one per combination, because each branch leaves `acc` at a different *known*
constant and the engine has no reason to merge states that differ in a value
it is tracking. `ifs_from_param` starts from an unknown; adding constants to
an unknown yields an unknown, the states after each `if` are
indistinguishable, and the branches fold back together.

The C++ fixture repeats it: `demo::Widget::f(int)` explodes with `acc = 0`
and explored 92 paths in an earlier draft that started with `acc = v`.

A related negative result, worth knowing because it contradicts intuition:
14 independent `if (unknown(k)) p_k = malloc(8);` allocations, freed at the
end, explored 172 paths; 14 boolean flags computed up front and tested in
14 `if`s explored 217. Neither tripped the limit. Distinct allocations and
distinct flags did **not** multiply the way distinct constants did. Do not
predict this from the source; measure it.

## What the static numbers do and do not tell you

`FUNCTION.metrics.xml.gz` carries `cc` (cyclomatic complexity), `pce`
(acyclic path count) and `pcs` (acyclic path count, statements only). They
are structural, computed from the CFG, and they do not predict the engine's
count:

| function | CCM | APC | engine paths (limit raised) |
|---|---|---|---|
| proftpd `setup_env` | 152 | 4.07e26 | 6003 |
| proftpd `listfile` | 100 | 6.79e13 | > 5000 |
| proftpd `tpl_map_va` | 80 | 75578 | > 10000 |
| proftpd `facts_mlinfo_fmt` | 18 | 31104 | > 5000 |
| proftpd `ls_nlst` | 83 | 6.4e9 | 3845 (never hit the limit) |
| proftpd `pr_auth_cache_set` | 23 | 526339 | 1025 |
| fixture `ifs_from_zero` | 15 | 16384 | 16384 |
| fixture `ifs_from_param` | 15 | 16384 | 106 |

A function with APC 6.4e9 finished in 3845 paths; one with APC 31104 did
not finish in 5000. Across the 2099 non-PATHOUT functions of one proftpd
run, the engine's count equalled APC for 439 of them -- the small ones,
where nothing merges because there is nothing to merge. Use CCM and APC to
rank candidates and to see how big a function is. Do not use them to
explain a PATHOUT.

## Which checker is the multiplier

Every checker and model deriver walks the function with its own notion of
state, and each has its own path count. The `wur:` line's number is the
**maximum** over them, not the sum -- for `setup_env` at a raised limit, 39
components summed to 31,365 and the line said 6003, which was
`REVERSE_INULL`'s count exactly. The limit trips when *one* component
exceeds it; the others may have finished long before.

`--print-paths` reports each component's count and flags the ones that hit
the limit:

```
wur_diagnostics: 4956 paths traversed by DEADCODE_pass2 in "setup_env(pool *, cmd_rec *, char const *, char *)"
wur_diagnostics: Pathed out: 5001 paths traversed by REVERSE_INULL in "setup_env(pool *, cmd_rec *, char const *, char *)"
```

So the diagnosis has a shape: **the component names the kind of state that
multiplied.** `REVERSE_INULL` tracks pointers that were dereferenced and
later compared against NULL; a function that null-checks many distinct
pointers, repeatedly, on many paths, gives it a large state space.
`DEADCODE_pass2` tracks condition outcomes with false-path pruning on;
`OVERRUN` tracks index and size values; `uninit_DERIVERS` tracks which
variables are written. What multiplied for the fixture was the known
value of `acc`; what multiplied for `setup_env` was pointer nullness.

Which components trip most often on a real project (subversion plus the
sqlite amalgamation, 9533 functions, default checkers, 2026.3.0):

| component | functions it pathed out in |
|---|---|
| `REVERSE_INULL` | 11 |
| `OVERRUN_pass1` | 6 |
| `DEADCODE_pass2` | 6 |
| `INFINITE_LOOP` | 4 |
| `FORWARD_NULL_pass2`, `DIVIDE_BY_ZERO_pass2`, `UNUSED_VALUE`, `REVERSE_NEGATIVE_pass1`, `OVERLAPPING_COPY_INTERNAL`, `generic_DERIVERS` | 2 each |

The `_pass2` suffix is the second pass the Extend SDK guide describes: a
checker that is about to report restarts the function with the
false-path-pruning modules enabled, which is more expensive. (That reading
of the suffix is reasoned from the guide, not documented as such.)

## How many functions this affects depends on the checker set

Same subversion idir, same analyzer:

| cov-analyze options | functions over the limit |
|---|---|
| defaults | 16 (0.17%) |
| `--all --aggressiveness-level high` + model files | 189 (1.91%) |

More checkers means more components that can multiply, and higher
aggressiveness means checkers that track more. A PATHOUT count is a property
of the *configuration*, not just of the code. The log says what it considers
normal: `(normally up to 5% of functions encounter this limitation)`.

## What the limit costs

When a component exceeds the limit it stops walking that function
(`Exceeded max number of paths, aborting function` is the message string in
the binary). Whatever that checker would have found on the paths it did not
walk, it does not find. The other components are unaffected. The function
still gets a model from the derivers that finished, so callers are not
starved unless a deriver was the one that pathed out.

Measured cost for `setup_env`: analyzing its TU at the default limit and at
`--paths 200000` produced the **same two defects**, and `REVERSE_INULL`
finished at 6003 -- it had been cut off at 5001, with 20% of its work left.
That is one data point, not a rule: a function that needs 16,384 paths and
gets 5000 has lost most of them. The way to know is to raise the limit and
compare the defect sets, which is cheap when scoped to the TU
(`references/worked-example-setup-env.md`).

## Loops

Loops are not the usual cause. The engine iterates a loop until the state
stops changing (a fixpoint), and the Extend SDK guide's *Termination*
section is explicit that a loop is bounded by the abstraction, not by trip
count. `setup_env` has no loops at all. The multiplier is usually a long
straight sequence of independent decisions over values the checker is
tracking -- error-handling ladders, configuration lookups each followed by
a null check, option flags tested one after another.

## Sources

- `cov-analyze --paths`, `--print-paths`, `--path-log-threshold`:
  `doc/en/help/cov-analyze.help.txt`.
- Fixpoint and false-path pruning: *Coverity Extend SDK Checker Development
  Guide*, sections *False Path Pruning (FPP)*, *Two-pass checking*,
  *Termination* (`doc/en/cov_extend_sdk_checker_dev_guide.html`).
- Metric column definitions: *Coverity Platform User and Administrator
  Guide*, view filters/columns table (CCM, Acyclic Path Count, Halstead
  Effort, Backedge Count, ...).
- Everything measured: `CALIBRATION.md`.
