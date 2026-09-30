/* Sample defects whose CWE has its own entry in the master CVSS profile.
 *
 * These are the controls: if the pipeline works at all, every one of these
 * should come back from the CVSS report with a non-zero CVSS_Score.  They
 * are deliberately trivial and nothing here is exploitable -- each is a
 * textbook shape chosen because a named checker reports it, not because it
 * does anything interesting.
 *
 *   sc_null_deref        CWE-476  NULL Pointer Dereference
 *   sc_uninit_scalar     CWE-457  Use of Uninitialized Variable
 *   sc_memory_leak       CWE-401  Missing Release of Memory
 *   sc_overrun           CWE-119/125  out-of-bounds access
 *   sc_string_overflow   CWE-120  Buffer Copy without Checking Size
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* CWE-476: the NULL case is noticed and then fallen through into. */
int sc_null_deref(int n)
{
    int v;
    int *p = (int *)malloc(n * sizeof(int));
    if (p == NULL) {
        fprintf(stderr, "out of memory\n");
    }
    p[0] = 1;                 /* FORWARD_NULL */
    v = p[0];
    free(p);
    return v;
}

/* CWE-457: v is only assigned on one branch and read on both. */
int sc_uninit_scalar(int flag)
{
    int v;
    if (flag) {
        v = 7;
    }
    return v;                 /* UNINIT */
}

/* CWE-401: the early return loses the only pointer to the block. */
int sc_memory_leak(int flag)
{
    char *buf = (char *)malloc(64);
    if (buf == NULL) {
        return -1;
    }
    if (flag) {
        return 0;             /* RESOURCE_LEAK */
    }
    free(buf);
    return 1;
}

/* CWE-119/125: the index is one past the end of a fixed array. */
int sc_overrun(void)
{
    int a[8];
    int i;
    for (i = 0; i < 8; i++) {
        a[i] = i;
    }
    return a[8];              /* OVERRUN */
}

/* CWE-120: the source is longer than the destination. */
void sc_string_overflow(void)
{
    char small[4];
    const char *big = "0123456789";
    strcpy(small, big);       /* STRING_OVERFLOW */
    printf("%s\n", small);
}
