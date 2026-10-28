/* The header app2.c finds only through -I at capture time. */
struct cfg_entry { int len; };
static inline int local_len(const char *s) { int n = 0; while (s[n]) n++; return n; }
#define LOCAL_LEN(s) local_len(s)
