/* libFuzzer harness for the fixture target `escaped(int id, int flag)`.
 * The pattern every harness follows: FZ_BEGIN, FZ_PINS_DEFAULT, define the
 * globals the slice declares extern, build the arguments from the byte
 * stream, call the target. tools/fz_support.h supplies fz_take, fz_string,
 * __stub_object and the claim counter; fz_target.py appends this file to the
 * slice and the model stubs. */
int unknown(int x) { (void)x; return fz_take(); }
void sink(int x) { (void)x; }

int LLVMFuzzerTestOneInput(const fz_u8 *data, unsigned long size) {
  FZ_BEGIN(data, size);
  FZ_PINS_DEFAULT();
  { int id = fz_take(); int flag = fz_take();
    (void)escaped(id, flag); }
  return 0;
}
