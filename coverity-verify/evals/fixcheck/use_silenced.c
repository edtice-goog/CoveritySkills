/* use.c after a SILENCING change: the dereference moves into a helper that
 * lives outside the capture (a library the build links but does not
 * compile), so the analyzer sees no dereference and the finding disappears.
 * rec_id() reads r->id; a NULL r still crashes, one frame down. */
struct rec { int id; int value; };
extern struct rec *lookup(int id);
extern int rec_id(struct rec *);         /* defined in rec_id.c, which is not in the capture */
extern int unknown(int);
extern void sink(int);

int checked_0(int id) { struct rec *r = lookup(id); if (r) return r->value + 0; return -1; }
int checked_1(int id) { struct rec *r = lookup(id); if (r) return r->value + 1; return -1; }
int checked_2(int id) { struct rec *r = lookup(id); if (r) return r->value + 2; return -1; }
int checked_3(int id) { struct rec *r = lookup(id); if (r) return r->value + 3; return -1; }

int escaped(int id, int flag) {
  int v = 0;
  struct rec *r = lookup(id);
  if (r && r->value) {
    v = r->value * 2;
  }
  sink(rec_id(r) + v);      /* the "fix": the dereference is now in rec_id() */
  return v + flag;
}
