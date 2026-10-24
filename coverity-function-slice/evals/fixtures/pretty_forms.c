/* Slice fixture: pretty-printer forms found on zstd and redis (2026-09-11),
 * nginx and proftpd (2026-10-24) that do not parse, or parse as a different
 * expression, when the body is re-emitted on its own.
 *
 *   1e9                              prints as   1e+09. (then a comment)  (a `.` after the exponent)
 *   ((BYTE const *)p)[i]             prints as   (BYTE const *)p[i]  (cast parentheses dropped)
 *   (a - (b))[i]                     prints as   a - (b)[i]          (operand parentheses dropped)
 *   (*table())[c]                    prints as   *table()[c]         (indexes the pointer, then dereferences: compiles, means something else)
 *   (*pp)[1]                         prints as   *pp[1]              (likewise)
 *   (p + 1)[c]                       prints as   p + 1[c]            (does not compile)
 *   sizeof (x), sizeof (T)           prints as   8ULL /- sizeof (x) -/  (folded to the capture's constant)
 *   size_t x = (assert-macro, 1);    prints as   size_t x = ((void)0) , ((void)0) , 1;
 *   typedef enum {..} sc_e; sc_e s;  prints as   fn::sc_e s;          (function-local typedef qualified)
 *   __atomic_load(&g, &t, order)     prints as   __atomic_load(8UL, p, &t, order)  (size folded in)
 *
 * (A further one, `[[maybe_unused]]` on a C function, is stripped by the slicer
 * too, but bare `cov-emit --c` will not parse the attribute, so it is not in
 * this fixture; it was seen on zstd under a gcc configuration.)
 *
 * Every subscript whose base the printer leaves bare is parenthesized from
 * the --print-debug tree, which keeps the structure; the folded sizeof is
 * restored from the comment the printer leaves; the rest are rewritten
 * unconditionally. The function also paths out so a successful slice shows
 * the usual PATHOUT=1 line.
 *
 * Build and analyze with evals/fixture.sh.
 */
typedef unsigned char BYTE;
typedef unsigned long long size_t;   /* what a win64 cov-emit expects; a mismatch is only a warning */
typedef unsigned short ctype_t;
extern int unknown(int);
extern void sink(int);
extern void sinkd(double);
extern const ctype_t **ctype_table(void);
extern size_t grow(void *block, size_t bytes);

#define CHECK(c) ((void)0)
#define REPCODE_ONE (CHECK(1), CHECK(2), 1)
#define IS_SPACE(c) ((*ctype_table())[(unsigned char)(c)] & 1)

typedef struct { int hits; long long total; } tally_t;
extern long long g_counter;
#ifndef __ATOMIC_RELAXED
#define __ATOMIC_RELAXED 0      /* a gcc predefine; bare cov-emit --c has none */
#endif

static size_t pretty_forms(void const *src, size_t n, int idx, char **opt, tally_t **tp) {
  typedef enum { noChange, slower, faster } speedChange_e;
  speedChange_e speed = noChange;
  size_t offBase = REPCODE_ONE;
  BYTE const *start = (BYTE const *)src + n;
  int acc = 0;
  size_t i;
  long long snapshot;
  {
    long long *p = &g_counter;
    long long tmp;
    __atomic_load(p, &tmp, __ATOMIC_RELAXED);
    snapshot = tmp;
  }
  sinkd((double)n * 1e9 / (double)(snapshot + 1));
  for (i = 0; i < n; i++) {
    if (((BYTE const *)src)[i] != start[-(long)i - 1])
      acc += ((BYTE const *)src)[i];
    if (IS_SPACE(((BYTE const *)src)[i]))                 /* (*ctype_table())[c], the glibc ctype shape */
      acc += (*opt)[1] + (start + 1)[-(long)i - 2];        /* (*pp)[1] and (p + 1)[c] */
  }
  if (n > 3 && (start - (CHECK(3), (offBase - 3)))[-1] == 0)   /* prints as start - (...)[-1] */
    speed = slower;
  if (tp != 0 && *tp != 0)
    (*tp)->hits += (int)(grow(*tp, (n + 1) * sizeof (tally_t *)) / sizeof (**tp));   /* sizeof survives as an expression */
  if (unknown(1)) acc += 1;
  if (unknown(2)) acc += 2;
  if (unknown(3)) acc += 4;
  if (unknown(4)) acc += 8;
  if (unknown(5)) acc += 16;
  if (unknown(6)) acc += 32;
  if (unknown(7)) acc += 64;
  if (unknown(8)) acc += 128;
  if (unknown(9)) acc += 256;
  if (unknown(10)) acc += 512;
  if (unknown(11)) acc += 1024;
  if (unknown(12)) acc += 2048;
  if (unknown(13)) acc += 4096;
  if (unknown(14)) acc += 8192;
  sink(acc + (int)speed + idx);
  return offBase + (size_t)acc;
}

size_t pretty_forms_entry(void const *src, size_t n, char **opt, tally_t **tp) {
  return pretty_forms(src, n, 1, opt, tp);
}
