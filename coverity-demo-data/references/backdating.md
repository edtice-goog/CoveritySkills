# What `--backdate` actually does

Accepted by `cov-commit-defects` in at least 2025.9.0 and 2026.6.0, and
transmitted to Connect as a `&backdate=` query parameter on the commit URL.
It does not appear in `cov-commit-defects --help` or in the shipped doc set of
those releases, so verify the behaviour below against your own version rather
than assuming it is stable.

Everything below was measured against a live instance (analysis 2025.9.0 ->
Connect 2025.12.0), not inferred.

## Format

**`yyyymmdd`, and nothing else.**

```
--backdate 2022-12-04    ->  "2022-12-04" doesn't look like a yyyymmdd date
--backdate 20221204      ->  accepted
```

This is a *different parser* from `--first-detected-after` and
`--first-detected-before`, which accept full ISO forms with time zones. Do not
generalize between them; the similarity is a trap.

No time-of-day component is accepted.

## What it sets

| Field | Effect |
|---|---|
| `snapshot.date_created` | Set to the backdate. **Date portion only** -- the time of day remains the real wall-clock commit time |
| `snapshot.backdated` | Set to `true`. Backdating is recorded in the schema, not disguised |
| `merged_defect.date_originated` | The per-CID global first-detected. Set from the backdate **for merge keys not previously seen** |

## What it does NOT set

| Field | Behavior |
|---|---|
| `snapshot.code_version_date` | Tracks source file mtimes; shows the real build date |
| Triage history, ownership, comments | Not backdated at all. A demo needing aged triage needs another mechanism |

## The write-once property

`merged_defect.date_originated` is keyed to the merge key and set on first
sight. A later backdated commit **cannot** move it -- which is the whole reason
commits must run oldest-first.

Verified across three snapshots committed in order (2022-12-04, 2023-10-08,
2025-03-14) from a real project's release history:

```
 first_detected | count
----------------+-------
 2022-12-04     |   113     <- every CID from the first commit kept its date
 2025-03-14     |     1     <- the one genuinely new defect got the new date
```

Both halves matter. Persistence gives the aging story; correct dating of new
defects gives the "introduced here" story. A pipeline that gets only the first
right looks fine until someone filters by first-detected.

Note also that a defect which *disappears* in a later version keeps its
original `date_originated`. Its CID persists; only its presence in the latest
snapshot changes. That is what makes fix-rate stories work.

## Verification queries

Run after every commit. `cov-admin-db psql` accepts SQL on stdin.

Snapshot dates and the backdated flag:

```sql
SELECT id, backdated, date_created, description FROM snapshot ORDER BY id;
```

First-detected distribution -- the single most useful check:

```sql
SELECT date_originated::date AS first_detected, count(*)
FROM merged_defect GROUP BY 1 ORDER BY 1;
```

Identify defects dated to a specific version, e.g. to find what is new at the
tip:

```sql
SELECT md.display_cid AS cid, md.date_originated::date, c.name AS checker
FROM merged_defect md JOIN checker c ON c.id = md.checker_id
WHERE md.date_originated::date > '<previous version date>';
```

Confirm `--strip-path` produced clean display paths:

```sql
SELECT pathname FROM file_path ORDER BY id LIMIT 5;
```

Expect `/src/fsio.c`, not `/home/you/build/src/fsio.c`.

## Creating the project and streams

`cov-manage-im --mode streams --add` does **not** accept a `project:` setting;
passing one fails with `Invalid --set value`. Streams are created standalone
and then attached to a project from the *project* side:

```
cov-manage-im --url <url> --auth-key-file <key>     --mode projects --add --set name:<project>

cov-manage-im --url <url> --auth-key-file <key>     --mode streams  --add --set name:<stream> --set lang:cpp

cov-manage-im --url <url> --auth-key-file <key>     --mode projects --update --name <project> --insert stream:<stream>
```

Verify with `--mode streams --show`, which prints the stream's primary project
and triage store. Repeat the last two commands per branch (rule 29).

Note there is no `--mode snapshots`; snapshot state is not exposed through
`cov-manage-im`. Use the SQL above.

## Connectivity notes

- Plain HTTP against the Connect port works and is simplest for a local demo
  box. The SSL port will fail on a self-signed certificate unless
  `--on-new-cert trust` is passed.
- `--host` is deprecated in favour of `--url`; both work, but `--url` avoids a
  warning on every commit.
