/* Sample defects aimed at the zero-by-default path.
 *
 * The point of this file is one comparison.  `integer_overflow` is listed
 * in the report generator's own taxonomy under CWE-190, CWE-191 AND
 * CWE-128.  CWE-190 has an entry in the master profile and scores 4.91.
 * CWE-191 and CWE-128 have no entry, and no ancestor of theirs has one
 * either, so the lookup falls off the end and they score 0.00 -- with a
 * vector printed beside them like any other row.
 *
 * So: the same checker, on two arithmetic mistakes of the same severity,
 * may or may not produce a score depending only on which of its CWEs the
 * report picks.  These functions are how we find out which one it picks.
 *
 *   gp_overflow_widen    CWE-190  expected to score
 *   gp_tainted_overflow  CWE-190/191/128 -- the interesting one
 *   gp_tainted_underflow CWE-191/128 if the report distinguishes them
 *   gp_const_write       CWE-843, an inherited-zero case (via CWE-704)
 *
 * Nothing here is exploitable: the "tainted" input is a number read from
 * stdin and used as a size, which is the shape the checker looks for.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* CWE-190: the multiply happens in int, then widens.  `long` is 32-bit on
 * LLP64 Windows, so the wider type has to be `long long` for the widening
 * to be real on every platform this fixture runs on. */
long long gp_overflow_widen(int a, int b)
{
    long long c = a * b;      /* OVERFLOW_BEFORE_WIDEN */
    return c;
}

/* CWE-190: a tainted count is multiplied and used as an allocation size. */
char *gp_tainted_overflow(void)
{
    int n;
    if (scanf("%d", &n) != 1) {
        return NULL;
    }
    return (char *)malloc(n * 16);   /* INTEGER_OVERFLOW */
}

/* CWE-191: a tainted length is decremented below zero and used as a size. */
char *gp_tainted_underflow(void)
{
    int len;
    char *buf;
    if (scanf("%d", &len) != 1) {
        return NULL;
    }
    len = len - 32;                  /* INTEGER_OVERFLOW, underflow side */
    buf = (char *)malloc((size_t)len);
    if (buf != NULL) {
        memset(buf, 0, (size_t)len);
    }
    return buf;
}

/* CWE-843 via CWE-704: the const is cast away and the object written. */
int gp_const_write(void)
{
    const int k = 5;
    int *p = (int *)&k;
    *p = 6;                          /* WRITE_CONST_FIELD family */
    return k;
}
