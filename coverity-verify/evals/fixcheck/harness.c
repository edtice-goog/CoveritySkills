/* Harness for the fix check on the fixture: the same as ../harness.c, plus
 * the real body of rec_id(), the callee the silencing change introduced
 * (see rec_id.c; it is compiled in as real code, never stubbed). */
int unknown(int x) { (void)x; return fz_take(); }
void sink(int x) { (void)x; }
int rec_id(struct rec *r) { return r->id; }

int LLVMFuzzerTestOneInput(const fz_u8 *data, unsigned long size) {
  FZ_BEGIN(data, size);
  FZ_PINS_DEFAULT();
  { int id = fz_take(); int flag = fz_take();
    (void)escaped(id, flag); }
  return 0;
}
