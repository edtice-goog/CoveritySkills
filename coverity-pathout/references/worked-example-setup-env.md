# Worked example: `setup_env` in proftpd

A real session against a real intermediate directory, kept as the template
for the procedure. proftpd 1.3.9, captured with `cov-build` (gcc, WSL) and
analyzed with **Coverity 2025.9.0** on Windows at defaults; 149 files, 2102
functions, 32 seconds. Every number below is from the run.

## 1. Is there a notice, and how big

```
$ grep -E '^summary: (paths_exceeded|Exceeded)' idir/output/analysis-log.txt
summary: paths_exceeded count: 4
```

Four functions (0.19%). No `Exceeded path limit ... % of functions` warning
line: the share is below whatever threshold prints it. Small, but the
question was *which* and *why*.

## 2. Which functions

```
$ grep 'PATHOUT=' idir/output/analysis-log.txt
wur: gen1059 4 102632 4703 7340 4703 5001 PATHOUT=1 n: setup_env in TU 77
wur: gen1756 13 55635 2563 7425 2547 5001 PATHOUT=1 n: listfile in TU 78
wur: gen608 5 18351 5719 7359 5703 10001 PATHOUT=1 n: tpl_map_va in TU 10
wur: gen1617 11 12934 17359 1296 17359 mem=... 5001 PATHOUT=1 n: facts_mlinfo_fmt in TU 82
```

All four named, with their TUs -- no batch lines on a run this size. Joined
with `FUNCTION.metrics.xml.gz` (`tools/pathout_report.py` does this):

| function | TU | CCM | APC | LOC | file:line |
|---|---|---|---|---|---|
| `setup_env` | 77 | 152 | 4.07e26 | 963 | `modules/mod_auth.c:1035` |
| `listfile` | 78 | 100 | 6.79e13 | 443 | `modules/mod_ls.c:466` |
| `tpl_map_va` | 10 | 80 | 75578 | 251 | `lib/hanson-tpl.c:315` |
| `facts_mlinfo_fmt` | 82 | 18 | 31104 | 126 | `modules/mod_facts.c:298` |

`facts_mlinfo_fmt` is the reminder that CCM does not predict this: 18 is a
modest function by any coding standard.

## 3. Which checker -- scoped re-run with `--print-paths`

Copy the idir (a re-run rewrites `output/`), then analyze **only TU 77**,
with stdout sent to a file (the diagnostics are one line per function per
component; nobody reads them, `grep 'Pathed out'` does):

```
$ cov-analyze --dir idir-copy --tu 77 --print-paths > idir-copy/analyze.stdout 2>&1
```

15 seconds instead of 32, and the notice reproduces in isolation. (It
did here because `setup_env`'s callees are in its own TU; on nginx the
same scoping lost 7 of 18 PATHOUTs, so the skill now measures on the
whole project.)

```
wur: gen36 4 33880 2266 7450 2266 5001 PATHOUT=1 n: setup_env in TU 77
wur_diagnostics: Pathed out: 5001 paths traversed by REVERSE_INULL in "setup_env(pool *, cmd_rec *, char const *, char *)"
wur_diagnostics: 4956 paths traversed by DEADCODE_pass2 in "setup_env(...)"
wur_diagnostics: 1796 paths traversed by REVERSE_NEGATIVE_pass1 in "setup_env(...)"
wur_diagnostics: 1720 paths traversed by FORWARD_NULL_pass1 in "setup_env(...)"
wur_diagnostics: 1627 paths traversed by generic_DERIVERS in "setup_env(...)"
... (39 components in all; most between 150 and 900)
```

One component hit the limit: `REVERSE_INULL`. `DEADCODE_pass2` was close.
The other 37 finished comfortably. The multiplier is **pointer nullness
state**, which is what `REVERSE_INULL` tracks (a pointer dereferenced, then
later compared with NULL).

## 4. The function, from the AST

```
$ cov-manage-emit --dir idir --ticker-mode none --tu 77 \
      find '^setup_env$' --kind f --print-definitions > setup_env.txt
```

0.4 seconds; 509 lines, 20 KB, for a 963-line function. Read it with the
checker in mind. Counts over the printed definition:

| construct | count |
|---|---|
| `if (` | 95 |
| `&&` / `\|\|` | 20 / 9 |
| `?:` | 12 |
| comparisons with `NULL` | 55 |
| distinct pointers compared with NULL | 20+ (`c` alone: 15 times) |
| `goto auth_failure` | 22 |
| `switch`/`case` | 14 |
| loops | **0** |
| `c ? c->subset : main_server->conf` | 7 |
| `find_config(...)` / `get_param_ptr(...)` lookups, each followed by a null check | 14 |

No loops, so fixpointing is not the story. The shape is a long
straight-line sequence of independent decisions -- anonymous-login
handling, root-login policy, group lookup, chroot resolution, wtmp/xferlog
setup, umask, display files -- each of which fetches a config value into a
pointer, null-checks it, and moves on; twenty-two of them bail to
`auth_failure`. Each such step at least doubles the nullness state
`REVERSE_INULL` carries, and the `c ? c->subset : main_server->conf` idiom
re-tests `c` seven more times. A checker whose state is "which pointers have
I seen dereferenced and which have I seen null-checked" walks this function
once per reachable combination.

The pretty-print also showed something the source hides: `PRIVS_ROOT` /
`PRIVS_RELINQUISH` (used three times) expand to blocks with their own `if`s
on `errno`, and `pr_log_auth(PR_LOG_NOTICE, ...)` is a plain call, not a
level-gated macro -- so the logging is *not* a contributor here, which is
worth knowing before anyone "fixes" it.

## 5. What it costs, measured

Raise the limit on the same scoped run:

```
$ cov-analyze --dir idir-copy --tu 77 --paths 200000
wur: gen36 1 33869 2062 7450 2062 6003 n: setup_env in TU 77
summary: paths_exceeded count: 0
```

`REVERSE_INULL` needed **6003** paths. The default limit cut it off with a
fifth of its work undone. Then compare defects (`cov-format-errors
--json-output-v10` on each run):

| | default limit | `--paths 200000` |
|---|---|---|
| defects in TU 77 | 2 | 2 |
| in `setup_env` | `DEADCODE` at line 1606 | `DEADCODE` at line 1606 |

Nothing changed. For this function, on this checker set, the notice cost no
findings. That is the measured answer; it is not a general one.

## 6. Verdict, as it would be reported

> `setup_env` (mod_auth.c:1035) exceeds the 5000-path limit in one checker,
> `REVERSE_INULL`, which needs ~6000 paths to finish it. The cause is
> structural: ~20 distinct configuration pointers each null-checked after
> lookup along a loop-free, 95-branch sequence. Raising the limit to 10000
> for this project completes the function and, measured on its translation
> unit, changes no defect. If the function is being refactored anyway, the
> natural seams are the anonymous-login, chroot and wtmp/xferlog blocks,
> and hoisting `c ? c->subset : main_server->conf` into one local removes
> seven redundant re-tests of `c`. The other three functions
> (`listfile`, `tpl_map_va`, `facts_mlinfo_fmt`) were not diagnosed in this
> session.

Say what you did not check. The other three got the same first two steps
and not the third.
