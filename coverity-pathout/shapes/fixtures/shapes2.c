/* Second fixture: one section per checker added on 2026-09-10. The shape,
 * then its nearest non-shapes. Expected hits are marked HIT. */
typedef unsigned long size_t;
extern int unknown(int);
extern void sink(int);
extern void sinkp(void *);
extern void *malloc(size_t);
extern void *realloc(void *, size_t);
extern void free(void *);
extern char *getenv(const char *);
extern char *strchr(const char *, int);
extern size_t strlen(const char *);
extern char *strncpy(char *, const char *, size_t);
extern void *memcpy(void *, const void *, size_t);
extern void *memset(void *, int, size_t);
extern int printf(const char *, ...);
extern int snprintf(char *, size_t, const char *, ...);
extern int read(int, void *, size_t);

/* ---- unchecked_null_return_deref ---- */
int nr_shape(void) {
  char *home = getenv("HOME");           /* HIT: never tested, dereferenced below */
  return home[0];
}
int nr_shape_assign(const char *s) {
  char *p;
  p = strchr(s, ':');                    /* HIT */
  return p[1];
}
int nr_tested(void) {
  char *home = getenv("HOME");
  if (home == 0)
    return -1;
  return home[0];
}
int nr_tested_and(void) {
  char *home = getenv("HOME");
  return home && home[0];
}
int nr_not_dereferenced(void) {
  char *home = getenv("HOME");
  sinkp(home);
  return 0;
}
int nr_tested_in_loop_assignment(const char *s) {
  char *p;
  int n = 0;
  while ((p = strchr(s, ':')) != 0) {   /* the test wraps the assignment */
    n += p[1];
    s = p + 1;
  }
  return n;
}
int nr_tested_in_if_assignment(const char *s) {
  char *p;
  int n = 0;
  if ((p = strchr(s, '/')))
    n += p[1];
  return n;
}

/* ---- nonliteral_format_string ---- */
void fmt_shape(const char *msg) {
  printf(msg);                            /* HIT */
}
void fmt_shape_snprintf(char *out, size_t n, const char *msg) {
  snprintf(out, n, msg);                  /* HIT */
}
void fmt_literal(const char *msg) {
  printf("%s", msg);
}
void fmt_with_args(const char *fmt, int v) {
  printf(fmt, v);                         /* wrapper style: not this shape */
}

/* ---- free_of_nonheap ---- */
void bf_shape_addr(void) {
  int x = 1;
  free(&x);                               /* HIT */
}
void bf_shape_array(void) {
  char buf[16];
  buf[0] = 0;
  free(buf);                              /* HIT */
}
void bf_shape_offset(void) {
  char *p = (char *)malloc(16);
  sinkp(p);
  free(p + 1);                            /* HIT */
}
void bf_heap(void) {
  char *p = (char *)malloc(16);
  free(p);
}

/* ---- unbounded_arithmetic_into_sink ---- */
void *ovf_shape(size_t n) {
  return malloc(n * sizeof(int));         /* HIT: n never compared */
}
void *ovf_shape_shift(size_t n) {
  return malloc(n << 4);                  /* HIT */
}
void *ovf_bounded(size_t n) {
  if (n > 1000)
    return 0;
  return malloc(n * sizeof(int));
}
void *ovf_constant(void) {
  return malloc(16 * sizeof(int));
}
void *ovf_no_arith(size_t n) {
  return malloc(n);                       /* no arithmetic: not this shape */
}
struct cell { int a; int *b; };
void *ovf_through_variable(int fd) {
  int y;
  read(fd, &y, 4);
  unsigned long long size = y * sizeof(struct cell);   /* (the reference writes `int size`; that would also be a narrowing cast) */
  if (size != 0)
    return malloc(size);                  /* HIT: the checker reference's own example; != 0 is not a bound */
  return 0;
}
void ovf_memcpy_length(char *dst, const char *src, size_t n, size_t hdr) {
  memcpy(dst, src, n + hdr);              /* HIT: a sum of two uncompared variables */
}
int ovf_index(int *table, int i, int stride) {
  return table[i * stride];               /* HIT: an array index */
}
void ovf_compound(char *dst, const char *src, size_t n, size_t extra) {
  size_t len = n;
  len += extra;
  memcpy(dst, src, len);                  /* HIT: len grows by an uncompared operand and is never compared */
}
void ovf_compound_bounded(char *dst, const char *src, size_t n, size_t extra) {
  size_t len = n;
  len += extra;
  if (len > 64)
    return;
  memcpy(dst, src, len);
}
int ovf_return_only(int a, int b) {
  return a * b;                           /* a return is not a sink here, on purpose */
}

/* ---- narrowing_cast_of_arithmetic ---- */
short nc_shape_explicit(int a, int b) {
  return (short)(a * b);                  /* HIT: 32-bit product into 16 bits */
}
int nc_shape_implicit(unsigned long long n, unsigned long long hdr) {
  int total = n + hdr;                    /* HIT: 64-bit sum into 32 bits, implicit (size_t is 32 bits on the default emit target) */
  return total;
}
unsigned char nc_shape_shift(unsigned x) {
  return (unsigned char)(x << 3);         /* HIT */
}
int nc_bounded(unsigned long long n, unsigned long long hdr) {
  if (n > 1000 || hdr > 1000)
    return -1;
  return (int)(n + hdr);
}
int nc_same_width(unsigned x, unsigned y) {
  return (int)(x - y);                    /* signedness only: not reported, on purpose */
}
long nc_widening(int a, int b) {
  return (long)(a * b);                   /* wider target: not this shape (the product wraps before the cast, which is OVERFLOW_BEFORE_WIDEN) */
}
int nc_no_arith(size_t n) {
  return (int)n;                          /* no arithmetic: not this shape */
}

/* ---- unchecked_array_index ---- */
int idx_shape(int fd) {
  char buf[16];
  int n = read(fd, buf, 16);
  return buf[n];                          /* HIT: n never compared */
}
int idx_loop(void) {
  char buf[16];
  int i, s = 0;
  for (i = 0; i < 16; i++)
    s += buf[i];
  return s;
}
int idx_pointer(char *p, int n) {
  return p[n];                            /* not a fixed array */
}
int idx_bounded(int n) {
  char buf[16];
  if (n >= 16)
    return 0;
  return buf[n];
}

/* ---- sizeof_pointer_as_size ---- */
void sz_shape(char *p) {
  memset(p, 0, sizeof(p));                /* HIT */
}
void *sz_shape_malloc(int *p) {
  return malloc(sizeof(p));               /* HIT */
}
void sz_array(void) {
  char buf[16];
  memset(buf, 0, sizeof(buf));
}
void sz_deref(int *p) {
  memset(p, 0, sizeof(*p));
}
void sz_pointer_value(void **slot, void *data) {
  memcpy(slot, &data, sizeof(data));      /* copies the pointer itself: not this shape */
}

/* ---- source_length_into_fixed_buffer ---- */
void cve_shape(const char *src) {
  char dest[16];
  size_t len = strlen(src);
  memset(dest, 0, sizeof(dest));
  strncpy(dest, src, len);                /* HIT: the incident shape */
}
void cve_shape_direct(const char *src) {
  char dest[16];
  memcpy(dest, src, strlen(src));         /* HIT */
}
void cve_shape_later(const char *src) {
  char dest[16];
  size_t len = 0;
  if (src != 0)
    len = strlen(src);
  if (len != 0)
    strncpy(dest, src, len);              /* HIT: != 0 is not a bound */
}
void cve_bounded(const char *src) {
  char dest[16];
  strncpy(dest, src, sizeof(dest) - 1);
}
void cve_clamped(const char *src) {
  char dest[16];
  size_t len = strlen(src);
  if (len > sizeof(dest) - 1)
    len = sizeof(dest) - 1;
  strncpy(dest, src, len);
}
void cve_heap(const char *src) {
  char *dest = (char *)malloc(strlen(src) + 1);
  strncpy(dest, src, strlen(src));        /* not a fixed array */
  free(dest);
}
