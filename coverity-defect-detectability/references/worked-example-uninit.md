# Worked example: interprocedural possibly-uninitialized read

A real end-to-end session with Coverity 2026.6.0 on Windows. The user asked:
"another tool misses this — can Coverity report the uninitialized read of
`value` at the `if (value == 1)` line?"

## The code (main.c, simplified from real software)

```c
/* Might set *value to 42. Not every path through fill_int sets *value,
 * instead leaving it unchanged. In the real software, value might or might
 * not be updated depending on configuration values loaded at run-time. */
static void fill_int(int* value)
{
    static int b = 0;
    if (b == 1)
    {
        *value = 1;
    }
}

int main(void)
{
    int value;

    fill_int(&value);
    if (value == 1)      /* <-- possibly-uninitialized read: the target */
    {
        return 0;
    }
    return 1;
}
```

Step 1 analysis: this is an uninitialized scalar read → checker **UNINIT**.
Success = a UNINIT report at the `if (value == 1)` line. The interesting
feature is that it's *interprocedural*: `fill_int` initializes `*value` on
one path and not the other, so any purely local view of `main` can't decide.

## Step 2: Capture

```
$BIN/cov-emit --dir idir main.c
→ Emit for file '.../main.c' (TU 1) complete.
```

## Step 3: Ladder

Rung 1 — defaults:

```
$BIN/cov-analyze --dir idir
→ Defect occurrences found       : 0
```

Not found. Rung 2 — medium aggressiveness:

```
$BIN/cov-analyze --dir idir --aggressiveness-level medium
→ Defect occurrences found       : 1 UNINIT
$BIN/cov-format-errors --dir idir --emacs-style
→ main.c:41:5: Type: Uninitialized scalar variable (UNINIT)
→   1. var_decl:   Declaring variable "value" without initializer.  (line 37)
→   2. uninit_use: Using uninitialized value "value".               (line 41)
```

Right type, right line — found at medium. Stop climbing; start minimizing.

## Step 4: Minimize

The low→medium table in `cov-analyze --help` flips exactly two UNINIT
options: `check_arguments` and `enable_write_context`. The checker reference
(`doc/en/cov_checker_ref.html`) says about `enable_write_context`:

> By default, UNINIT does not distinguish the interprocedural context under
> which a callee can initialize a parameter or parameter field. To avoid too
> many false positives, UNINIT does not report a defect if it finds an
> initialization of a parameter along at least one path in the callee. This
> option relaxes this restriction and tracks the context of interprocedural
> initializations.

That is precisely this code's shape — `fill_int` initializes on *one* path,
so default UNINIT stays quiet. Confirm it is sufficient alone, at default
aggressiveness:

```
$BIN/cov-analyze --dir idir --checker-option UNINIT:enable_write_context:true
→ Defect occurrences found       : 1 UNINIT
```

Minimal trigger identified.

## Step 5: Verdict as reported

**Verdict: DETECTED with configuration**

- **Checker:** UNINIT (Uninitialized scalar variable)
- **Minimal configuration:**
  `cov-analyze --dir idir --checker-option UNINIT:enable_write_context:true`
- **Why defaults miss it:** default UNINIT suppresses the report because
  `fill_int` initializes `*value` on at least one path; it doesn't track
  *which* paths, by design, to hold down false positives.
- **Tradeoffs:** per the checker docs, enabling `enable_write_context`
  "reports more defects and possibly more false positives because of
  approximations in interprocedural context tracking". Far cheaper than
  running everything at medium aggressiveness (~50% more false positives
  across all checkers), which also flips this option.
- **Reproduce:** the four commands above, in order.
