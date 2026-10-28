/* Harness for the slice-set fixture: the entry point is the finding's home
 * function, get_value(); pick() is in the slice set and runs as code. The
 * slice declares the file-static table extern, so the harness defines it
 * with the source's initializer. */
struct rec table[4] = { {0, 10}, {1, 20}, {2, 30}, {3, 40} };
void sink(int x) { (void)x; }

int LLVMFuzzerTestOneInput(const fz_u8 *data, unsigned long size) {
  FZ_BEGIN(data, size);
  FZ_PINS_DEFAULT();
  { int id = (int)fz_take() - 128; int flag = fz_take();
    (void)get_value(id, flag); }
  return 0;
}
