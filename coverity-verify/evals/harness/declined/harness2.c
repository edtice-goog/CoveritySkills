/* Harness for the extraction fallback of the declined fixture: the slice of
 * handle2() with lookup_cfg stubbed from its model. */
int LLVMFuzzerTestOneInput(const fz_u8 *data, unsigned long size) {
  FZ_BEGIN(data, size);
  FZ_PINS_DEFAULT();
  { char kb[13]; const char *key = fz_string(kb, sizeof kb);
    (void)handle2(key); }
  return 0;
}
