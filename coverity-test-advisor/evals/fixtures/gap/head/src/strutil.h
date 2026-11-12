#ifndef STRUTIL_H
#define STRUTIL_H

#define STRUTIL_VERSION 2

int parse_len(const char *s);
int field_len(const char *rec);
int record_size(const char *rec);
const char *strutil_name(void);
int describe(char *buf, int size);

#endif
