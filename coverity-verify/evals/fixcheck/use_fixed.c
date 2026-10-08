/* use.c after a FIX: the null is handled before the dereference. */
struct rec { int id; int value; };
extern struct rec *lookup(int id);
extern int unknown(int);
extern void sink(int);

int checked_0(int id) { struct rec *r = lookup(id); if (r) return r->value + 0; return -1; }
int checked_1(int id) { struct rec *r = lookup(id); if (r) return r->value + 1; return -1; }
int checked_2(int id) { struct rec *r = lookup(id); if (r) return r->value + 2; return -1; }
int checked_3(int id) { struct rec *r = lookup(id); if (r) return r->value + 3; return -1; }

int escaped(int id, int flag) {
  int v = 0;
  struct rec *r = lookup(id);
  if (r == 0)
    return -1;              /* the fix */
  if (r && r->value) {
    v = r->value * 2;
  }
  sink(r->id + v);
  return v + flag;
}
