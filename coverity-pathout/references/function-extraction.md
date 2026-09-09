# Getting a function out of an intermediate directory

The intermediate directory holds the abstract syntax tree the analyzer used.
`cov-manage-emit find` pretty-prints it, one function at a time, in well
under a second. That is the whole technique; everything else on this page is
how to aim it and how to read what comes back.

**Do not** extract the file with `extract-files`, preprocess it with
`cov-preprocess` or `--preprocess-native`, and then try to cut the function
out of the `.i` file by hand or with a script. That path is slow, it fights
macro expansion and line directives, and the text it produces is still not
what the analyzer saw. The AST is.

## The command

```bash
$BIN/cov-manage-emit --dir <idir> --ticker-mode none [--tu <N>] \
    find '<regex>' --kind f --print-definitions
```

- `$BIN` must be the **version that wrote the idir**. Line 1 of
  `<idir>/emit/version` names it. A different version refuses with
  `Version mismatch ... Expected version number is 355, but this directory has
  version 350` (measured: 2026.6.0 against a 2025.9.0 idir).
- `--ticker-mode none` keeps the progress bar out of the output.
- `--kind f` restricts to functions (`c` classes, `g` globals, `e` enums).
- `--tu <N>` restricts to one translation unit. The PATHOUT line in the log
  gives you the number (`in TU 77`); use it -- see *Duplicates* below.

Timing, measured on 2025.9.0 against a 149-file proftpd idir: `find` alone
3.0 s cold (index warm-up), `--print-definitions` 0.4 s after that.

## What the regex matches

The regex is matched against the **mangled** name for C++ and the plain
identifier for C. Anchor it. `^setup_env$` matches `setup_env` and not
`setup_env_ex`; an unanchored `f` matches every C++ function whose mangled
name contains an `f`, which is most of them.

**C.** The name in the log is the identifier:

```
wur: gen1059 ... 5001 PATHOUT=1 n: setup_env in TU 77
```

```bash
find '^setup_env$' --kind f --print-definitions
```

**C++.** The log names the function by its mangled name; the `--print-paths`
diagnostics use the demangled signature:

```
wur: gen4 ... 5001 PATHOUT=1 n: _ZN4demo6Widget1fEi in TU 2
wur_diagnostics: Pathed out: 5001 paths traversed by uninit_DERIVERS in "demo::Widget::f(int)"
```

Search by the mangled name, anchored at the end:

```bash
find '_ZN4demo6Widget1fEi$' --kind f --print-definitions
```

If you only have the demangled signature, list the candidates first and read
the mangled name off the listing -- it prints both:

```
$ cov-manage-emit --dir idir --ticker-mode none find 'Widget' --kind f
Matching function: demo::Widget::f(int) /*_ZN4demo6Widget1fEi*/
 declared at:
   .../overloads.cpp:21:13-.../overloads.cpp:21:13
 defined in TU 2 with row 5
Matching function: demo::Widget::f(double) /*_ZN4demo6Widget1fEd*/
 ...
```

Overloads are different mangled names, so `find` never confuses them once
you use the mangled form.

## Duplicates: static functions that share a name

`find` lists **every** definition that matches, each with its own body.
proftpd has seven `main`s (the daemon plus six utilities); `find '^main$'`
prints seven definitions, each headed by its file and TU:

```
Matching function: main
 declared at:
   /home/etice/demo/proftpd/src/main.c:2423:5-...
 defined in TU 14 with row 156
Matching function: main
 declared at:
   /home/etice/demo/proftpd/src/ftpdctl.c:371:5-...
 defined in TU 71 with row 1505
...
```

The PATHOUT line names the TU. Pass it: `--tu 14 find '^main$' ...` returns
one definition. A function defined in a header and included into many TUs
behaves the same way -- one listing per TU that holds a definition.

## A miss

A regex that matches nothing prints nothing and exits 0. Check for the
`Matching function` header before believing an empty file. (Measured on
2025.9.0.)

## Reading the output

The definition arrives with a header comment and then the function,
pretty-printed from the AST:

```c
/*
 * Matching function: setup_env
 * declared at:
 *   /home/etice/demo/proftpd/modules/mod_auth.c:1035:12-/home/etice/demo/proftpd/modules/mod_auth.c:1035:20
 * defined in TU 77 with row 1911
 */
static int setup_env(pool *p, cmd_rec *cmd, char const *user, char *pass) {
  ...
      session.gids = make_array(p, 2, 4UL /* sizeof (gid_t) */);
  ...
      if (*__errno_location() != 38) {
```

What the pretty-printer does, all of it visible in that excerpt:

| In the source | In the definition | Why it matters |
|---|---|---|
| `PRIVS_ROOT`, `pr_log_auth(PR_LOG_NOTICE, ...)`, `errno`, `ENOSYS` | expanded: the block, `pr_log_auth(5, ...)`, `*__errno_location()`, `38` | **Branches hidden in macros are in plain sight.** A logging macro that expands to `if (level > x) ...` contributes a branch per use, and only this view shows it. |
| `sizeof(gid_t)` | `4UL /* sizeof (gid_t) */` | constants are folded; the comment keeps the original readable |
| `const char *` | `char const *` | types are printed canonically |
| `if (x) stmt;` | `if (x) {` / `stmt;` / `}` (2025.9.0) or `if (x)` / indented `stmt;` (2026.6.0) | layout is the printer's, not the author's; formatting differs slightly between versions |
| 963 source lines | 509 printed lines, 20 KB | the comments and blank lines are gone; this is the compact form |

Line numbers are **not** preserved inside the body. The header's
`declared at:` is the only anchor. For a side-by-side with the original
source, take the captured file from the emit:

```bash
$BIN/cov-manage-emit --dir <idir> --ticker-mode none --tu 77 print-source
```

That prints the primary source of the TU **preceded by three header lines**
(`Translation unit:`, the TU line, `Primary SF :`), so a construct at source
line *L* is at output line *L + 3*. (Measured: `setup_env` declared at
`mod_auth.c:1035`, printed on line 1038.) The source on disk is the same
thing if the tree has not moved since capture.

## Cross-check with the metrics

`<idir>/output/FUNCTION.metrics.xml.gz` (written by `cov-analyze`) has one
entry per function, keyed by the same name the log uses:

```xml
<fnmetric>
<file>/home/etice/demo/proftpd/modules/mod_auth.c</file>
<names><![CDATA[fn:setup_env;]]></names>
<metrics>be:0;fe:448;bl:298;lc:963;on:249;ot:23;tn:1343;tt:1137;cc:152;pce:4.07238e+26;pcs:3.69356e+19;hf:234861;hr:4.63413;ml:1035</metrics>
</fnmetric>
```

`ml` is the first line of the definition and must agree with the header's
`declared at:` (1035 in both). `cc` is cyclomatic complexity (Connect calls
it CCM), `pce`/`pcs` the acyclic path counts (APC and APC-S, statements only),
`lc` lines of code, `hf`/`hr` Halstead effort/errors, `be`/`fe` back/forward
edge counts. The field-to-column mapping is inferred from Connect's *Functions
view* column definitions in the platform guide; the short keys themselves
are not documented. `tools/pathout_report.py` does this join for you.

## The other `find` outputs, and why they are not the tool for this

| Option | Output | Size for `setup_env` | Use it for |
|---|---|---|---|
| `--print-definitions` | pretty-printed source from the AST | 509 lines, 20 KB | **reading the function** |
| `--print-callees` | the functions it calls, with declaration sites | ~60 lines | seeing what is a call and what is a macro |
| `--print-debug` | the full AST, one node per line, every node with a `loc = file:line:col` | 75,102 lines, 3.6 MB | mapping one construct back to an exact source position when the pretty-print is not enough |
| `--print-codexm` | the AST as CodeXM patterns | 465,718 lines, 34 MB | writing a CodeXM checker; not this |

`--print-debug` is the one to reach for when you need "which source line is
this `if`?" for a single construct: grep the node and read its `loc`. Do not
open the whole thing.

## Related: cov-find-function

`cov-find-function --dir <idir> <name>` resolves a partial name to the
mangled names the analysis uses, and can show a function's *model*
(`--show`, `--module`). It answers "what is this function's summary?", not
"what does this function look like?". For the latter, `find
--print-definitions` above.
