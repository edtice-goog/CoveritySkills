/* A stand-in <string.h> for the EMIT only: bare `cov-emit --c` has no system
 * include path, and the real UCRT header pulls in the MSVC runtime headers.
 * The harness route's build does not see this file: clang-cl compiles the TU
 * as-is against the real <string.h>. */
#ifndef FIXTURE_STRING_H
#define FIXTURE_STRING_H
typedef unsigned long long size_t;
size_t strlen(const char *);
char *strncpy(char *, const char *, size_t);
#endif
