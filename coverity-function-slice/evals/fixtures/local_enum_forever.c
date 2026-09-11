/* Slice fixture: two things the pretty-printer emits that are not C.
 *
 * `cov-manage-emit find --print-definitions` prints the body with macros
 * expanded and some constructs re-spelled. Two of those re-spellings do not
 * parse when the body is re-emitted on its own (found on nginx, 2026.6.0,
 * C17): eight of its eighteen PATHOUT functions silently produced no
 * analysis line at all, because cov-emit dropped the function.
 *
 *   for (;;)                     prints as   for (; true; )
 *   for (i = 0; ; i++)           prints as   for (i = 0; true; i++)
 *
 *     `true` is a keyword in C++ but a <stdbool.h> macro in C, and the slice
 *     includes nothing. cov-emit: `identifier "true" is undefined`, then
 *     `warning #1563: function "local_enum_forever" not emitted`. The
 *     slicer now #defines true/false for a C slice.
 *
 *   enum { st_start, ... } state;   prints as   enum <anonymous>;
 *                                               enum local_enum_forever::[unnamed type of 'state'] state;
 *
 *     The emit names that enum `_ZZ18local_enum_foreverE$Uu5state_` and has
 *     its enumerators; the slicer hoists it to file scope under a synthetic
 *     tag and points the body's spelling at that tag. The same goes for an
 *     unnamed struct (`tally`) and an unnamed enum with no variable (LIMIT).
 *
 * The function also paths out (acc starts known, as in ifs_known_vs_unknown.c)
 * so that a successful slice shows the usual PATHOUT=1 line -- and a dropped
 * function cannot be mistaken for "no PATHOUT": the slicer now reports
 * COULD NOT VERIFY when the analysis log has no line for it.
 *
 * Build and analyze with evals/fixture.sh, or by hand:
 *   cov-emit --dir idir --c local_enum_forever.c
 *   cov-analyze --dir idir --print-paths
 *   slice_function.py --dir idir --bin <bin> --tu 1 --name local_enum_forever --emit --analyze
 */
extern int unknown(int);
extern void sink(int);

int local_enum_forever(int a) {
  enum { st_start, st_run, st_done } state = st_start;
  enum { LIMIT = 3 };
  struct { int hits; int misses; } tally = { 0, 0 };
  int acc = 0;
  int i;

  for (;;) {
    switch (state) {
    case st_start:
      state = st_run;
      break;
    case st_run:
      if (unknown(0)) tally.hits++; else tally.misses++;
      state = st_done;
      break;
    case st_done:
      break;
    }
    if (state == st_done) break;
  }
  for (i = 0; ; i++) {
    if (i >= LIMIT) break;
    acc += tally.hits;
  }

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
  sink(acc + tally.misses);
  return acc;
}
