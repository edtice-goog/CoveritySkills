/* Second translation unit for the slice-set fixture: it defines `struct rec`
 * DIFFERENTLY from slice_set.c. A set that takes one member from each TU
 * (`--name set_caller --name set_other@2`) cannot carry both definitions,
 * and the slicer must say so (`conflict:` and COULD NOT VERIFY, exit 2)
 * rather than pick one. Emitted as TU 2 by evals/fixture.sh.
 */
struct rec { double value; char tag[8]; };
extern void sink(int);

int set_other(struct rec *r) {
  if (r == 0)
    return -1;
  sink((int)r->value);
  return r->tag[0];
}
