struct rec { int id; int value; };
extern struct rec *table_get(int slot);
extern int table_size(void);

/* Returns NULL when the id is out of range: the ONLY place that knowledge lives. */
struct rec *lookup(int id) {
  if (id < 0 || id >= table_size())
    return 0;
  return table_get(id);
}
