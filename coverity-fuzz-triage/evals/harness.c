/* libFuzzer harness: the fuzz input feeds (a) the target's scalar arguments
   and (b) every __stub_choice() made inside the model-derived stubs. */
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
static const uint8_t *cur; static size_t left;
static int take(void) { if (left == 0) return 0; left--; return *cur++; }
int __stub_nondet(void) { return take(); }
void *__stub_alloc(int n) { return calloc(1, n > 0 ? n : 1); }
void *__stub_object(int n) { static char obj[4096]; return obj; }
int unknown(int x) { return take(); }
void sink(int x) { (void)x; }
int escaped(int id, int flag);
int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
  cur = data; left = size;
  int id = take(); int flag = take();
  (void)escaped(id, flag);
  return 0;
}
