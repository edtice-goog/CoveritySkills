/* One fixture per checker: the shape, then its nearest non-shapes.
 * Expected hits are marked HIT; everything else must stay silent. */
extern int unknown(int);
extern void sink(int);
extern void *malloc(unsigned long);
extern void free(void *);
extern char *strcpy(char *, const char *);
extern char *strncpy(char *, const char *, unsigned long);
extern int sprintf(char *, const char *, ...);
extern int snprintf(char *, unsigned long, const char *, ...);
extern void keep(void *);

/* ---- zero_check_then_divide ---- */
int div_shape(int total, int n) {
  int avg = 0;
  if (n != 0) {
    avg = total / n;             /* guarded */
  }
  return total % n;              /* HIT: unguarded divisor after a zero test */
}
int div_guarded(int total, int n) {
  if (n == 0)
    return 0;
  return total / n;              /* exit guard */
}
int div_ternary(int total, int n) {
  return n ? total / n : 0;      /* ternary guard */
}
int div_positive(int total, int n) {
  if (n > 0) {
    return total / n;            /* n > 0 guards */
  }
  return 0;
}
extern void abort(void);
int div_abort_guard(int total, int n) {
  if (n == 0)
    abort();                     /* a call that never returns is an exit guard */
  return total / n;
}

/* ---- double_free ---- */
void free_shape(int flag) {
  char *p = (char *)malloc(16);
  if (flag) {
    free(p);                     /* HIT (pair) */
  }
  free(p);                       /* HIT (pair) */
}
void free_once(void) {
  char *p = (char *)malloc(16);
  free(p);
}
void free_two_vars(void) {
  char *p = (char *)malloc(16);
  char *q = (char *)malloc(16);
  free(p);
  free(q);
}

/* ---- unbounded_copy_into_fixed_buffer ---- */
void copy_shape(const char *s) {
  char buf[16];
  strcpy(buf, s);                /* HIT */
  sink(buf[0]);
}
void copy_bounded(const char *s) {
  char buf[16];
  strncpy(buf, s, sizeof buf - 1);
  snprintf(buf, sizeof buf, "%s", s);
  sink(buf[0]);
}
void copy_heap(const char *s) {
  char *buf = (char *)malloc(64);
  strcpy(buf, s);                /* not a fixed array: not this shape */
  free(buf);
}

/* ---- alloc_never_released ---- */
int leak_shape(int n) {
  char *p = (char *)malloc(n);   /* HIT: never freed, passed, returned or stored */
  if (!p)
    return -1;
  p[0] = 1;
  return n;
}
int leak_freed(int n) {
  char *p = (char *)malloc(n);
  free(p);
  return n;
}
char *leak_returned(int n) {
  char *p = (char *)malloc(n);
  return p;
}
int leak_kept(int n) {
  char *p = (char *)malloc(n);
  keep(p);
  return n;
}
static char *g_saved;
int leak_stored(int n) {
  char *p = (char *)malloc(n);
  g_saved = p;
  return n;
}
