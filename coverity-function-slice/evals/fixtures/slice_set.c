/* Slice-set fixture: several functions of one translation unit sliced into
 * ONE file, each as real code, so that a finding whose path crosses from a
 * caller into a callee can be re-analyzed (and executed) without a stub
 * standing in for either. Three shapes, each with the check that proves it:
 *
 *   (a) caller + STATIC callee.  set_caller passes a pointer it has just
 *       null-tested to set_callee, which dereferences it unconditionally.
 *       Sliced alone, set_callee is a prototype and the analysis sees no
 *       dereference; sliced as a set, the callee is code with external
 *       linkage (the `static` is dropped so the caller can reach it) and
 *       the full analysis reports FORWARD_NULL in set_caller. That report
 *       is the proof the callee is reachable as code.
 *
 *   (b) mutual recursion.  set_even and set_odd (both static) call each
 *       other; only a prototype block ahead of the definitions makes the
 *       pair compile in either order.
 *
 *   (c) a member + a NON-member callee.  set_caller also calls set_helper,
 *       which is not in the set and must stay a prototype even though it is
 *       defined in this file.
 *
 * Build and analyze with evals/fixture.sh.
 */
struct rec { int value; int other; };
extern struct rec *lookup(int id);
extern void log_missing(int id);
extern void sink(int);

static int set_helper(int v) {              /* defined here, but never in the set */
  return v * 2;
}

static void set_callee(struct rec *r) {     /* dereferences unconditionally */
  r->other = set_helper(r->value);
}

int set_caller(int id) {
  struct rec *r = lookup(id);
  if (r == 0)
    log_missing(id);                        /* tested, not returned from */
  set_callee(r);                            /* FORWARD_NULL once set_callee is code in the slice */
  return r ? r->other : -1;
}

static int set_odd(int n);
static int set_even(int n) {
  if (n == 0) return 1;
  return set_odd(n - 1);
}
static int set_odd(int n) {
  if (n == 0) return 0;
  return set_even(n - 1);
}

int set_parity_entry(int n) {
  return set_even(n) + set_odd(n);
}
