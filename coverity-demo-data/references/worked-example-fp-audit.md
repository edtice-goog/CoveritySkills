# FP audit: proftpd v1.3.9 demo dataset

Stratified per-checker sample (rule 26) from the committed corpus tip, 2 per
checker. Nine triaged against real source read from `git show v1.3.9:<path>`.

**Headline: 3 of 9 are false positives.** All three are checker-correct but
wrong in context, and all three would have been embarrassing on stage.

| # | checker | location | verdict |
|---|---|---|---|
| 019 | SIZEOF_MISMATCH | `src/configdb.c:933` | **true positive - real bug** |
| 016 | OVERRUN | `src/netaddr.c:567` | true positive - stack over-read |
| 017 | REVERSE_INULL | `modules/mod_ls.c:1610` | true positive |
| 001 | CHECKED_RETURN | `modules/mod_core.c:4749` | true positive, low severity |
| 004 | DEADCODE | `src/stash.c:596` | true positive, intentional code |
| 008 | MISSING_BREAK | `src/jot.c:2099` | true positive, probably intentional |
| 003 | COPY_PASTE_ERROR | `lib/ccan-json.c:1396` | **FALSE POSITIVE** |
| 013 | NULL_RETURNS | `modules/mod_log.c:1324` | **FALSE POSITIVE** |
| 023 | Y2K38_SAFETY | `utils/ftpwho.c:291` | **FALSE POSITIVE in practice** |

## The false positives

### 013 NULL_RETURNS - `modules/mod_log.c:1324` (definitive)

```c
if (strncasecmp(lf->lf_filename, "syslog:", 7) != 0) {
  ...
} else {
  char *tmp = strchr(lf->lf_filename, ':');
  lf->lf_syslog_level = pr_log_str2sysloglevel(++tmp);
```

The `else` branch is reached **only when the filename begins with `"syslog:"`**,
so `strchr(..., ':')` cannot return NULL -- the colon is guaranteed at index 6.
Coverity's evidence is statistical (`strchr returns NULL, checked 68 out of 71
times`) and ignores the guarding `strncasecmp`. The path is infeasible.

### 003 COPY_PASTE_ERROR - `lib/ccan-json.c:1396`

```c
for (child = head; child != NULL; last = child, child = child->next) {
    if (child->next == child) problem("child->next == child (cycle)");
    if (child->next == head)  problem("child->next == head (cycle)");
```

Coverity suggests `child` "should be head" on the second line. It should not:
these are two distinct, deliberate cycle checks -- self-loop, and loop back to
the list head. Taking the remediation advice would produce `head->next == head`,
which is strictly worse. The heuristic pattern-matched adjacent similar lines.

### 023 Y2K38_SAFETY - `utils/ftpwho.c:291`

```c
upminutes = (int) uptime_secs / 60;
```

Correct detection of a `time_t` narrowed to `int`, but `uptime_secs` is a
**duration**, not an epoch timestamp -- the surrounding code computes updays,
uphours, upminutes. Overflowing `int` needs ~68 years of continuous process
uptime. Technically right, practically impossible. Worth knowing that
Y2K38_SAFETY on durations is noise in this dataset.

## Best demo candidate: 019 SIZEOF_MISMATCH

```c
ptr = pr_table_pcalloc(config_tab, sizeof(unsigned int));      /* 4 bytes */
*ptr = ++config_id;
if (pr_table_add(config_tab, name, ptr, sizeof(unsigned int *)) < 0) {  /* 8 */
```

Allocates 4 bytes, registers the value with a length of 8. Any consumer reading
`valuelen` bytes over-reads by 4. Three adjacent lines, self-evident harm, no
invariant argument required, and the allocation sits directly above the bug for
contrast. **This passes the legibility rule comfortably** -- the strongest demo
item found.

## Also solid

- **016 OVERRUN** `src/netaddr.c:567` -- a 16-byte `struct sockaddr_in` on the
  stack is passed to a function Coverity says accesses byte offset 27, a
  12-byte stack over-read. Security-adjacent and legible. *Caveat: I did not
  read `pr_netaddr_set_sockaddr` itself, so severity is inferred from
  Coverity's interprocedural claim rather than confirmed. Confirm before
  demoing.*
- **001 CHECKED_RETURN** `modules/mod_core.c:4749` -- `pr_inet_set_block(...)`
  return discarded, while the very next line checks `pr_inet_listen(...)`. The
  side-by-side contrast makes it unusually legible for a low-severity finding.

## Do not demo

- **004 DEADCODE** and **008 MISSING_BREAK** are correct detections of
  *intentional* code (defensive fallback; deliberate switch fallthrough that
  adds the base byte count). Both invite "so what?" and both need the
  maintainer to adjudicate. Fine in the dataset, wrong on screen.

## What this says about the dataset

A ~33% false-positive rate in a stratified sample is unremarkable for C at
analysis defaults with no triage history -- these are unreviewed findings, not
a curated set. It matters only because a demo points at individual defects.

The audit cost is small and the failure mode is severe, which is the argument
for doing it with a strong model: every one of the three false positives is
*checker-correct*. Catching them required reading the guarding `strncasecmp`,
recognising a deliberate two-check idiom, and knowing that a duration is not a
timestamp. None of that is visible in the defect title, the checker name, or
the event trace alone.
