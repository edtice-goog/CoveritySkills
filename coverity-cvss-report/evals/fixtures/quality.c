/* Sample defects whose CWE is mapped to C:N/I:N/A:N in the master profile.
 *
 * These are the CWEs a customer reports as "getting no CVSS score".  They
 * do get one -- it is zero, and it is zero because somebody decided a
 * quality finding is not a vulnerability.  That is the answer, and these
 * fixtures are what demonstrates it rather than asserting it.
 *
 *   ql_deadcode          DEADCODE        -> CWE-561 / CWE-1164
 *   ql_unused_value      UNUSED_VALUE    -> CWE-563   (see note)
 *   ql_unused_status     UNUSED_VALUE    -> CWE-563   (see note)
 *   ql_always_false      NO_EFFECT       -> CWE-570
 *   ql_no_effect         NO_EFFECT       -> CWE-482
 *   ql_bad_pointer_cast  OVERRUN         -> CWE-119 family
 *   ql_narrowing_cast    (nothing)
 *
 * Two notes from actually running this, both worth keeping:
 *
 *   UNUSED_VALUE does not fire under plain `cov-analyze --all` on these
 *   shapes.  It needs `--aggressiveness-level high` -- and specifically
 *   that, not `--enable-audit-mode`, which changes nothing here.  Analyze
 *   the fixture with `--all --aggressiveness-level high` or CWE-563 will
 *   be missing and you will think the mapping lost it.
 *
 *   No trivial C shape here produced INCOMPATIBLE_CAST, so CWE-704 has no
 *   sample defect.  It does not need one: CWE-704 is in the master
 *   profile with C:N/I:N/A:N, which is read from the file and is the
 *   whole answer for it.
 */

#include <stdio.h>

/* CWE-561: the guarded block cannot be reached. */
int ql_deadcode(void)
{
    int x = 1;
    if (x > 2) {
        return 99;            /* DEADCODE */
    }
    return x;
}

/* Declared, not defined: the analyzer cannot see through it and prove the
 * call pointless, so the dead store is what gets reported. */
extern int ql_compute(int n);

/* CWE-563: the returned value is overwritten before it is ever read. */
int ql_unused_value(int n)
{
    int v = ql_compute(n);    /* UNUSED_VALUE */
    v = n + 1;
    return v;
}

/* CWE-570: an unsigned value is never less than zero. */
int ql_always_false(unsigned int u)
{
    if (u < 0) {              /* NO_EFFECT / CONSTANT_EXPRESSION_RESULT */
        return 1;
    }
    return 0;
}

/* CWE-398: the comparison result is computed and discarded. */
int ql_no_effect(int a, int b)
{
    a == b;                   /* NO_EFFECT */
    return a + b;
}

/* CWE-704: a one-byte object is written through a four-byte pointer.
 * Note this one reports as OVERRUN, not INCOMPATIBLE_CAST -- writing four
 * bytes into a one-byte object is an out-of-bounds write, and Coverity
 * says the more specific thing.  Kept because that is worth knowing. */
int ql_bad_pointer_cast(void)
{
    char c = 0;
    int *p = (int *)&c;
    *p = 1;                   /* OVERRUN, as it turns out */
    return c;
}

/* CWE-704: an int object read back through a pointer to a narrower type. */
int ql_narrowing_cast(int n)
{
    int x = n;
    short *s = (short *)&x;   /* INCOMPATIBLE_CAST */
    return *s;
}

/* CWE-563: a library call's status is stored and then thrown away. */
int ql_unused_status(const char *path)
{
    FILE *f = fopen(path, "r");
    int rc;
    if (f == NULL) {
        return -1;
    }
    rc = fclose(f);           /* UNUSED_VALUE */
    rc = 0;
    return rc;
}
