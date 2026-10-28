/* Driver for the harness-route fixture: calls the original handle() in the
 * included TU with a key the fuzzer chooses. lookup_cfg() is the TU's one
 * external and is stubbed from its model. */
int LLVMFuzzerTestOneInput(const fz_u8 *data, unsigned long size) {
  FZ_BEGIN(data, size);
  FZ_PINS_DEFAULT();
  { char kb[13]; const char *key = fz_string(kb, sizeof kb);
    (void)handle(key); }
  return 0;
}
