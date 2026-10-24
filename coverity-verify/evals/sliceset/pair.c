/* Slice-set fixture: a caller and a callee that both carry a primary event.
 *
 * pick() returns NULL for a negative id, so its derived model has a
 * returnsnull edge. get_value() dereferences pick()'s result without a
 * test, which is the shape of a NULL_RETURNS, but it never passes a
 * negative id: the index is made non-negative first.
 *
 * As a STUB, pick's model lets the fuzzer pick returnsnull at will, and the
 * claim `r != NULL` fails on the first input: a false positive adjudicated
 * as real. As CODE, pick never returns NULL for what get_value passes, and
 * the claim never fails. The verdict has to come from pick's real body,
 * which is why a function that carries a primary event is in the slice set
 * and never a stub. */
struct rec { int id; int value; };
static struct rec table[4] = { {0, 10}, {1, 20}, {2, 30}, {3, 40} };
extern void sink(int);

struct rec *pick(int id) {
  if (id < 0)
    return 0;                       /* the callee's primary event: returning NULL */
  return &table[id % 4];
}

int get_value(int id, int flag) {
  int k = id < 0 ? -id : id;        /* never negative */
  struct rec *r = pick(k);
  if (flag)
    sink(k);
  return r->value;                  /* the finding's line: dereference without a test */
}
