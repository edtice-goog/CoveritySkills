/* Harness-route fixture, the callee's TU: lookup_cfg() returns NULL for a key
 * it does not know. Its derived model has a returnsnull edge, and the real
 * function has that behaviour too. */
struct cfg { const char *key; const char *value; };
static struct cfg table[] = { {"host", "localhost"}, {"port", "21"}, {"root", "/srv/ftp"} };

const char *lookup_cfg(const char *key) {
  unsigned i;
  for (i = 0; i < sizeof table / sizeof table[0]; i++) {
    const char *a = table[i].key, *b = key;
    while (*a && *a == *b) { a++; b++; }
    if (*a == 0 && *b == 0)
      return table[i].value;
  }
  return 0;
}
