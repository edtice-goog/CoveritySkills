/* Fuzz-triage support, included by the target fz_target.py assembles.
 *
 *  - one byte stream feeds the target's arguments and every stub choice
 *  - every stub choice is traced, so a crash reports the callee behaviours it
 *    relied on (those are the things to check against the real callees)
 *  - the finding's own claim is checked at its line (__fz_claim) and counted,
 *    so "reached N times, claim never false" is evidence too
 *  - pins hold a stub to one behaviour: focused mode pins every callee to its
 *    normal behaviour except the one the finding blames, so a bycatch null
 *    return elsewhere does not end the run before the finding's line
 *  - stub and semantic allocations come from a per-input arena, reset at
 *    FZ_BEGIN, so a 20-million-input run does not leak 20 million blocks
 *  - a non-null object the model says nothing about is filled with pointers to
 *    itself: every pointer field points at valid memory (a zeroed object would
 *    assert every field is NULL, which the model never said); integer fields
 *    read as large values, so the harness sets the ones that bound loops
 *
 * No system headers: a slice carries its own copies of libc types (struct stat,
 * struct timespec, size_t) printed from the emit, and <stdlib.h> would collide
 * with them. The few libc functions used here are declared by hand, and the
 * message path is vsnprintf + write so it builds with clang on Linux and
 * clang-cl on Windows alike. */
#ifndef FZ_SUPPORT_H
#define FZ_SUPPORT_H
typedef unsigned char fz_u8;
void *calloc(unsigned long, unsigned long);
void abort(void);
int atexit(void (*)(void));
int strcmp(const char *, const char *);
unsigned long strlen(const char *);
void *memcpy(void *, const void *, unsigned long);
#ifdef _WIN32
int _write(int, const void *, unsigned int);
#define fz_write(b, n) _write(2, (b), (unsigned int)(n))
#else
long write(int, const void *, unsigned long);
#define fz_write(b, n) write(2, (b), (n))
#endif
void __sanitizer_set_death_callback(void (*)(void));

/* a formatter of its own (%s %d %u %llu %lld %%): the UCRT exports neither
   vsnprintf nor _vsnprintf as symbols under clang-cl, and glibc's would drag
   <stdio.h> in */
static void fz_put(char *buf, int *n, int cap, const char *s) { while (*s && *n < cap - 1) buf[(*n)++] = *s++; }
static void fz_putu(char *buf, int *n, int cap, unsigned long long v) {
  char t[24]; int i = 0; do { t[i++] = (char)('0' + v % 10); v /= 10; } while (v);
  while (i > 0 && *n < cap - 1) buf[(*n)++] = t[--i];
}
static void fz_msg(const char *fmt, ...) {
  char buf[512]; int n = 0; const int cap = (int)sizeof buf; __builtin_va_list ap; __builtin_va_start(ap, fmt);
  for (; *fmt; fmt++) {
    if (*fmt != '%') { if (n < cap - 1) buf[n++] = *fmt; continue; }
    fmt++;
    if (*fmt == 's') { const char *s = __builtin_va_arg(ap, const char *); fz_put(buf, &n, cap, s ? s : "(null)"); }
    else if (*fmt == 'd') { int v = __builtin_va_arg(ap, int); if (v < 0) { fz_put(buf, &n, cap, "-"); fz_putu(buf, &n, cap, (unsigned long long)(-(long long)v)); } else fz_putu(buf, &n, cap, (unsigned long long)v); }
    else if (*fmt == 'u') { fz_putu(buf, &n, cap, __builtin_va_arg(ap, unsigned int)); }
    else if (*fmt == 'l' && fmt[1] == 'l' && (fmt[2] == 'u' || fmt[2] == 'd')) {
      if (fmt[2] == 'u') fz_putu(buf, &n, cap, __builtin_va_arg(ap, unsigned long long));
      else { long long v = __builtin_va_arg(ap, long long); if (v < 0) { fz_put(buf, &n, cap, "-"); v = -v; } fz_putu(buf, &n, cap, (unsigned long long)v); }
      fmt += 2;
    }
    else if (*fmt == '%') { if (n < cap - 1) buf[n++] = '%'; }
    else { if (n < cap - 1) buf[n++] = '%'; if (*fmt && n < cap - 1) buf[n++] = *fmt; }
  }
  __builtin_va_end(ap);
  if (n > 0) fz_write(buf, n);
}

static const fz_u8 *fz_cur; static unsigned long fz_left;
static int fz_take(void) { if (fz_left == 0) return 0; fz_left--; return *fz_cur++; }

/* trace of stub choices for the current input */
#define FZ_TRACE_MAX 256
static const char *fz_trace_fn[FZ_TRACE_MAX]; static int fz_trace_choice[FZ_TRACE_MAX]; static int fz_trace_n;
static unsigned long long fz_reached, fz_inputs;

/* pins: callee name -> fixed behaviour index */
#define FZ_PIN_MAX 64
static const char *fz_pin_fn[FZ_PIN_MAX]; static int fz_pin_choice[FZ_PIN_MAX]; static int fz_pin_n;
#define FZ_PIN(name, k) do { if (fz_pin_n < FZ_PIN_MAX) { fz_pin_fn[fz_pin_n] = (name); fz_pin_choice[fz_pin_n] = (k); fz_pin_n++; } } while (0)
static int fz_pinned(const char *fn, int n) {
  int i;
  for (i = 0; i < fz_pin_n; i++) if (strcmp(fz_pin_fn[i], fn) == 0) return n > 0 ? fz_pin_choice[i] % n : fz_pin_choice[i];
  return -1;
}

/* per-input arena for stub and semantic allocations. Never returned to libc, so
   ASan sees overruns only at the arena's end; a leak claim needs the real
   allocator instead. */
#define FZ_ARENA_BYTES (64u << 20)
static char fz_arena[FZ_ARENA_BYTES]; static unsigned long fz_arena_used;
static void *fz_alloc(unsigned long n) {
  unsigned long m = (n + 15) & ~15ul; char *p;
  if (fz_arena_used + m + 16 > FZ_ARENA_BYTES) { fz_msg("== fz: arena exhausted\n"); abort(); }
  p = fz_arena + fz_arena_used; fz_arena_used += m + 16;     /* 16-byte gap between blocks */
  { unsigned long i; for (i = 0; i < m; i++) p[i] = 0; }
  return p;
}

int __stub_nondet(void) { return fz_take(); }
void *__stub_alloc(int n) { return fz_alloc(n > 0 ? (unsigned long)n : 1); }
#define FZ_OBJ_WORDS 65536
static void *fz_obj[FZ_OBJ_WORDS];
static void *fz_obj_ready;
void *__stub_object(int n) {
  if (!fz_obj_ready) { int i; for (i = 0; i < FZ_OBJ_WORDS; i++) fz_obj[i] = (void *)&fz_obj[(i * 7 + 64) % (FZ_OBJ_WORDS - 4096)]; fz_obj_ready = fz_obj; }
  return fz_obj;
}
void *__stub_zeroed(int n) { static char z[65536]; return z; }
static int __stub_choice_named(const char *fn, int n) {
  int k = fz_pinned(fn, n);
  if (k < 0) { int c = fz_take(); k = n > 0 ? (c % n + n) % n : c; }
  if (fz_trace_n < FZ_TRACE_MAX) { fz_trace_fn[fz_trace_n] = fn; fz_trace_choice[fz_trace_n] = k; fz_trace_n++; }
  return k;
}
/* model_stubs.py emits __stub_choice(n) inside each stub; __func__ names the stub in the trace */
#ifndef __stub_choice
#define __stub_choice(n) __stub_choice_named(__func__, (n))
#endif

/* a NUL-terminated string of up to max-1 bytes from the input (no embedded NULs) */
static char *fz_string(char *buf, unsigned long max) {
  unsigned long n = (unsigned long)fz_take() % max; unsigned long i;
  for (i = 0; i < n; i++) { int c = fz_take(); buf[i] = (char)(c ? c : 1); }
  buf[n] = 0; return buf;
}

/* semantic helpers for --semantic stubs (copy functions whose model cannot say
   "the result equals the source") */
static char *fz_sem_strdup(const char *s) { unsigned long n = s ? strlen(s) : 0; char *r = (char *)fz_alloc(n + 1); if (s) memcpy(r, s, n); return r; }
static char *fz_sem_strndup(const char *s, unsigned long m) { unsigned long n = s ? strlen(s) : 0; if (n > m) n = m; { char *r = (char *)fz_alloc(n + 1); if (s) memcpy(r, s, n); return r; } }
static char *fz_sem_vcat(__builtin_va_list ap) {
  char *r = (char *)fz_alloc(1); unsigned long len = 0; const char *s;
  while ((s = __builtin_va_arg(ap, const char *)) != 0) {
    unsigned long n = strlen(s); char *t = (char *)fz_alloc(len + n + 1);
    memcpy(t, r, len); memcpy(t + len, s, n); len += n; r = t;
  }
  return r;
}

static void fz_dump_trace(void) {
  int i;
  fz_msg("== fz: stub choices on this input:");
  for (i = 0; i < fz_trace_n; i++) fz_msg(" %s=%d", fz_trace_fn[i], fz_trace_choice[i]);
  fz_msg("\n== fz: finding line reached %llu times over %llu inputs before this\n", fz_reached, fz_inputs);
}
/* the finding's claim, checked where the finding is: false => abort (confirmed) */
#define __fz_claim(cond) do { fz_reached++; if (!(cond)) { fz_msg("== fz: CLAIM HOLDS at line %d: !(%s)\n", __LINE__, #cond); fz_dump_trace(); abort(); } } while (0)
static void fz_summary(void) { fz_msg("== fz: summary: %llu inputs, finding line reached %llu times, claim never false\n", fz_inputs, fz_reached); }
static void fz_init(void) { static int done; if (!done) { done = 1; __sanitizer_set_death_callback(fz_dump_trace); atexit(fz_summary); } }
#define FZ_BEGIN(data, size) do { fz_init(); fz_cur = (data); fz_left = (size); fz_trace_n = 0; fz_arena_used = 0; fz_inputs++; } while (0)
#endif
