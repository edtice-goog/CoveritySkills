/* PATHOUT fixture: identical control flow, different tracked state.
 *
 * Both functions have 14 independent `if`s, cyclomatic complexity 15 and a
 * static acyclic path count of 16384. Only one of them exceeds the default
 * 5000-path limit:
 *
 *   ifs_from_zero   acc starts at a KNOWN constant. Each branch leaves acc at
 *                   a different known value, so the engine has 2^k distinct
 *                   states after k ifs and cannot merge them. PATHOUT.
 *
 *   ifs_from_param  acc starts UNKNOWN. Adding constants to an unknown
 *                   leaves it unknown; branches rejoin into the same state.
 *                   Measured: 106 paths.
 *
 * This is the whole lesson: the path limit counts paths x state, and the
 * source-level shape of the function does not predict it.
 *
 * Build and analyze with evals/fixture.sh, or by hand:
 *   cov-emit --dir idir --c ifs_known_vs_unknown.c
 *   cov-analyze --dir idir --print-paths
 *   grep 'PATHOUT=\|Pathed out\|paths_exceeded' idir/output/analysis-log.txt
 */
extern int unknown(int);
extern void sink(int);

int ifs_from_zero(int a) {
  int acc = 0;
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
  sink(acc);
  return acc;
}

int ifs_from_param(int a) {
  int acc = a;
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
  sink(acc);
  return acc;
}
