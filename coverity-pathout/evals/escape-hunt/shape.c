/* Fixture for the path-insensitive candidate checker.
 *
 * The shape: a pointer is null-tested in an if condition, and later
 * dereferenced outside that if statement. Path-insensitively that is a
 * candidate whether or not any real path reaches it with a null.
 */
struct inner { int f7; };
struct rec { struct inner *link; int other; };
extern struct rec *lookup(void *ctx, unsigned idx);
extern void log_it(unsigned, unsigned, const char *, int, int);
extern int unknown(int);

/* 1. THE SHAPE: guard closes one statement too early -> candidate */
int shape_escaped(void *ctx, unsigned idx) {
  int v = 0;
  struct rec *r = lookup(ctx, idx);
  if (r && r->link) {
    v = r->link->f7;
  }
  log_it(2U, 4294967295U, "queued", r->other, v);   /* deref outside the guard */
  return v;
}

/* 2. CONTROL: same code with the call inside the guard -> no candidate */
int shape_guarded(void *ctx, unsigned idx) {
  int v = 0;
  struct rec *r = lookup(ctx, idx);
  if (r && r->link) {
    v = r->link->f7;
    log_it(2U, 4294967295U, "queued", r->other, v);
  }
  return v;
}

/* 3. CONTROL: negative test with an early return -> guarded, no candidate */
int shape_early_return(void *ctx, unsigned idx) {
  struct rec *r = lookup(ctx, idx);
  if (!r)
    return -1;
  return r->other;
}

/* 4. CONTROL: negative test, deref in the else branch -> guarded */
int shape_else(void *ctx, unsigned idx) {
  struct rec *r = lookup(ctx, idx);
  if (r == 0) {
    return -1;
  } else {
    return r->other;
  }
}

/* 5. THE SHAPE again, through a cast and a plain *p -> candidate */
int shape_cast(void *p) {
  struct rec *r = (struct rec *)p;
  if (r != 0) {
    unknown(1);
  }
  return *(int *)r;
}
