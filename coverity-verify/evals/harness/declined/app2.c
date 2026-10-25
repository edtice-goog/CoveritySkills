/* Harness-route fixture where the router DECLINES: the TU includes a project
 * header that lives outside its own directory (a generated or build-tree
 * header, found at capture time through -I). The manifest cannot supply it,
 * so tu.c does not compile from the manifest, and the target is static
 * besides. The router falls back to extraction with the reason recorded; the
 * slice of handle2() still emits, because the slicer prints the declarations
 * it needs from the emit. */
#include "local.h"

extern const char *lookup_cfg(const char *key);

static int handle2(const char *key) {
  const char *v = lookup_cfg(key);
  struct cfg_entry e;
  e.len = LOCAL_LEN(v);             /* the finding's line: v may be NULL */
  return e.len;
}

int entry2(const char *key) { return handle2(key); }
