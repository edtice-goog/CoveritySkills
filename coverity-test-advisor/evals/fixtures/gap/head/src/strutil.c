#include <stdio.h>
#include "strutil.h"

/* The digits at the start of s, as a number; -1 when there is no s. */
int parse_len(const char *s)
{
    int n = 0;
    if (s == NULL)
        return -1;
    while (*s >= '0' && *s <= '9')
        n = n * 10 + (*s++ - '0');
    return n;
}

/* A field is its length prefix plus one separator. */
int field_len(const char *rec)
{
    return parse_len(rec) + 1;
}

/* A record holds two fields. */
int record_size(const char *rec)
{
    return 2 * field_len(rec);
}

const char *strutil_name(void)
{
    return "strutil-lib";
}

int describe(char *buf, int size)
{
    return snprintf(buf, size, "%s %d", strutil_name(), STRUTIL_VERSION);
}
