/* Harness-route fixture, the finding's TU: a native checker's shape. handle()
 * copies lookup_cfg()'s result without a test; lookup_cfg() may return NULL.
 * The TU includes a real system header and defines a helper of its own, so
 * the harness route compiles it as-is: handle() and trim() run as real code,
 * lookup_cfg() is the one external and gets its model stub. */
#include <string.h>

extern const char *lookup_cfg(const char *key);

static int trim(char *s) {
  size_t n = strlen(s);
  while (n > 0 && s[n - 1] == ' ')
    s[--n] = 0;
  return (int)n;
}

int handle(const char *key) {
  const char *v = lookup_cfg(key);
  char buf[16];
  strncpy(buf, v, 15);              /* the finding's line: v may be NULL */
  buf[15] = 0;
  return trim(buf);
}
