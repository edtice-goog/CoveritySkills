#include <stdio.h>
#include <string.h>
#include "../src/strutil.h"

/* The tests at the head: none passes NULL, so parse_len's new branch,
   and the new result it gives its callers, never run. */
int main(void)
{
    char buf[64];
    if (parse_len("12abc") != 12)
        return 1;
    if (field_len("7:x") != 8)
        return 1;
    if (record_size("3:abc") != 8)
        return 1;
    if (strcmp(strutil_name(), "strutil-lib") != 0)
        return 1;
    if (describe(buf, sizeof buf) <= 0)
        return 1;
    return 0;
}
