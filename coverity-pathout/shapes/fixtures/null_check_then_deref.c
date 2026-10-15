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

/* ---- null_check_then_deref ---- */
/* 1. THE SHAPE: guard closes one statement too early -> candidate */
int shape_escaped(void *ctx, unsigned idx) {
  int v = 0;
  struct rec *r = lookup(ctx, idx);
  if (r && r->link) {
    v = r->link->f7;
  }
  log_it(2U, 4294967295U, "queued", r->other, v);   /* HIT: deref outside the guard */
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
  return *(int *)r;               /* HIT */
}

/* 6. CONTROL: a while / for condition guards its body like an if does */
int shape_loop_guard(void *ctx, unsigned n) {
  struct rec *r = lookup(ctx, 0);
  int v = 0;
  unsigned i;
  if (r == 0)
    unknown(0);
  while (r != 0) {
    v += r->other;                 /* guarded by the loop condition */
    r = lookup(ctx, ++n);
  }
  for (i = 0; r && i < n; i++)
    v += r->other;                 /* guarded by the loop condition */
  return v;
}

/* 8. CONTROL: a call that never returns is an exit guard, like a return.
 *    `if (!p) exit(1);` and an expanded assert (`if (!(p != 0)) __assert_fail(...)`)
 *    both guard everything after them. (57 of zstd's 60 survivors were these.) */
extern void exit(int);
extern void __assert_fail(const char *, const char *, unsigned, const char *);
int shape_exit_guard(void *ctx, unsigned n) {
  struct rec *r = lookup(ctx, n);
  if (r == 0)
    exit(1);
  return r->other;
}
int shape_assert_guard(void *ctx, unsigned n) {
  struct rec *r = lookup(ctx, n);
  if (!(r != 0))
    __assert_fail("r != 0", "f.c", 1, "shape_assert_guard");
  return r->other;
}
int shape_assert_glibc(void *ctx, unsigned n) {
  struct rec *r = lookup(ctx, n);
  if (r != 0);                      /* glibc's assert after expansion: */
  else                              /*   if (p != NULL); else __assert_fail(..) */
    __assert_fail("r != 0", "f.c", 3, "shape_assert_glibc");
  return r->other;
}
int shape_assert_ternary(void *ctx, unsigned n) {
  struct rec *r = lookup(ctx, n);
  if (n > 7)
    unknown(0);
  ((r != 0) ? (void)0 : __assert_fail("r != 0", "f.c", 2, "shape_assert_ternary"));   /* glibc's assert */
  return r->other;
}

/* 7. CONTROL: the test wraps an assignment -> still a test of r */
int shape_assign_in_test(void *ctx, unsigned n) {
  struct rec *r;
  int v = 0;
  if ((r = lookup(ctx, n)) != 0)
    v = r->other;
  if ((r = lookup(ctx, n + 1)))
    v += r->other;
  return v;
}
