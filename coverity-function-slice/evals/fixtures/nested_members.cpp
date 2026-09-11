/* PATHOUT fixture, C++ free function with the constructs the slicer had to
 * learn for C++ (from a run against a large real-world C++ TU):
 *
 *   - a callee that is a STATIC member function of a class, reached through
 *     the class name (`Collector::enqueue`), whose declaration therefore has
 *     to be printed inside the class body;
 *   - a NESTED enum used as that member's parameter type, which must precede
 *     the member declaration inside the class;
 *   - a struct with a FLEXIBLE ARRAY MEMBER, which the tree describes with an
 *     element count of `<unset>`;
 *   - a logging idiom built on `__func__`, which reaches the pretty-printer as
 *     a static array with no declarator.
 *
 * `drive` starts its accumulator at a known constant, so it also trips the
 * default path limit like the C fixture does.
 *
 *   cov-emit --dir idir --c++ nested_members.cpp
 *   cov-analyze --dir idir --print-paths
 *   slice_function.py --dir idir --bin ... --tu <N> --name _Z5drivei --obfuscate --emit --analyze
 */
extern int unknown(int);
extern void log_line(const char *who, const char *what);

struct Frame {
  unsigned len;
  unsigned char body[];   /* flexible array member */
};

class Collector {
 public:
  enum DIRECTION { INBOUND, OUTBOUND };
  static bool enqueue(DIRECTION d, Frame *f);
  static int depth();
};

int drive(int n) {
  int acc = 0;
  Frame *f = 0;
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
  if (Collector::enqueue(Collector::OUTBOUND, f)) {
    log_line(__func__, "queued");
    acc += Collector::depth();
  }
  return acc + n;
}
