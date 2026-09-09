/* PATHOUT fixture, C++: the exploding function is one overload of two.
 *
 * In the analysis log the function is named by its MANGLED name
 * (`n: _ZN4demo6Widget1fEi in TU 2`); the --print-paths diagnostics use the
 * demangled signature (`demo::Widget::f(int)`). `cov-manage-emit find`
 * matches its regex against the mangled name and prints both:
 *
 *   Matching function: demo::Widget::f(int)   (mangled: _ZN4demo6Widget1fEi)
 *
 * so the way to pick an overload is `find '_ZN4demo6Widget1fEi$'`, never
 * `find f`.
 */
extern int unknown(int);

namespace demo {
struct Widget {
  int f(int v);     /* explodes: 13 ifs from a known start */
  int f(double v);  /* trivial */
};

int Widget::f(int v) {
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
  return acc + v;
}

int Widget::f(double v) { return unknown((int)v); }
}  // namespace demo
