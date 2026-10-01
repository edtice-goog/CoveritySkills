# Authenticating to Coverity Connect

How to get a working authentication key, keep it, check it, and get rid of
it. Rules 28 and 37 in `RULES.md` are the short form; this is the procedure
and the evidence behind it.

Everything below marked *measured* was run on 2026-10-01 against Coverity
Connect 2026.9.0 at `http://localhost:8080`, from
`cov-analysis-win64-2026.9.0` on Windows 11. See the Connect authentication
entry in `CALIBRATION.md`.

## The short version

```bash
# 1. Create -- needs the user's Connect password, once
python3 tools/connect_auth.py create --url <connect-url> --bin $BIN \
    --user <connect-user> --passphrase-file <file holding the password>

# 2. Check -- before relying on any key, including one you just found on disk
python3 tools/connect_auth.py check --url <connect-url> --auth-key-file <key>

# 3. Use -- every cov-* command takes the key explicitly
cov-commit-defects --url <connect-url> --auth-key-file <key> ...
```

`create` writes the key to `~/.coverity/ak-<host>-<port>`
(`C:\Users\<you>\.coverity\ak-localhost-8080` on Windows), refuses to
overwrite an existing file, and checks the new key before reporting success.
`check` prints `VALID`, `REJECTED` or `UNREACHABLE` and exits 0, 1 or 2.

The URL always comes from the user or the project configuration. Never read
it from the key (rule 28).

## Creating a key

Use the command line. The Connect UI can also make a key (*\<user\> >
Authentication Keys > Create and Download*), but an agent driving that page
in a browser is a long detour around one command. That detour is the failure
this file exists to prevent.

The underlying command, if you are not using the tool:

```
COV_USER=<connect-user> COVERITY_PASSPHRASE_FILE=<file> \
  cov-manage-im --url <connect-url> --mode auth-key --create \
    --output-file <key> \
    --set description:"<what it is for>" \
    --set expiration:after_90_days
```

- **The password goes in a file, never on the command line.** Command lines
  are visible to other users of the machine. `COVERITY_PASSPHRASE_FILE` is
  documented; a trailing LF or CRLF in the file is tolerated (*measured*), so
  `echo` is fine. Ask the user for the password, write the file somewhere
  temporary, and delete it once the key exists.
- **Name the user explicitly.** Without `--user`, a URL username or
  `COV_USER`, `cov-manage-im` falls back through `$USER` to the operating
  system login (your Windows user name rather than `admin`). That fails
  silently; see
  *Checking a key*.
- **The directory must exist.** `--output-file` does not create it. Worse,
  the key is created on the server before the file is written, so a missing
  directory leaves **a live key that nothing holds** (*measured*: Connect's
  `usageLog.log` recorded an `AuthenticationKeyCreationEvent` for a key whose
  file write had just failed). `connect_auth.py create` makes the directory
  first. If you do orphan one, revoke it by id (see *Revoking a key*).
- **A key cannot create a key.** Authenticated with a key, `--create` is
  refused: *"This operation is not permitted when using an authentication
  key. Username and password are required"* (*measured*). Creation is the
  one step that needs the password.
- Expiration accepts `after_N_days`, `after_N.M_days`, `YYYY-MM-DD` and
  `YYYY-MM-DDThh:mm[:ss]` (a space instead of `T` is an error). The server
  caps it at `cim.authkey.expiration.duration`, default 30 years.
- Each `cov-manage-im` call takes roughly 13 seconds to start (*measured*).
  Do not mistake that for a hang.

**When password login is disabled** (reverse-proxy authentication with
password-based WS access turned off), the command line cannot create keys.
The documentation says so explicitly. Ask the user to create one in the
Connect UI and save it under `~/.coverity/`.

## Where a key lives

**In the user's home directory, under `~/.coverity/`.** Never in a
repository, a workspace, or anything that gets copied, committed, or shared.

`~/.coverity/ak-<host>-<port>` is the documented default `auth-key-file` of
the `coverity` CLI, so a key stored under that name is found by `coverity
analyze` and `coverity commit` without configuration. **The `cov-*` commands
do not look there** (*measured*): `cov-manage-im` with no `--auth-key-file`
ignores it and falls back to a password prompt for the OS user, which in a
non-interactive session ends in `[Error] No password was given.` Always pass
`--auth-key-file`.

On a machine with several instances or users, name keys so they cannot be
confused, e.g. `ak-localhost-8080` for the default and
`ak-localhost-8080-<purpose>` beside it.

Treat the contents as a secret. Never print the `key` field in chat, a log,
or a report; quoting `id`, `username` and the `comments` block is harmless.

The key file holds:

```json
{
 "type": "Coverity authentication key",
 "version": 2,
 "id": 10003,
 "username": "admin",
 "domain": "local",
 "key": "<32 characters -- the secret>",
 "comments": {
  "host": "localhost", "port": "8080", "ssl": "false",
  "description": "...", "creationDate": "...", "expirationDate": "..."
 }
}
```

`comments` is a comment. The host there is never a connection target (rule
28). The expiration date there is a useful hint when a key stops working,
but it is not authoritative.

**File permissions.** The documentation says a key created by `cov-manage-im`
is readable only by its creator, and that the `cov-*` tools stop accepting it
if that changes. On Windows the created file carries explicit ACEs for the
user, SYSTEM and Administrators, and **granting `Everyone` or `Users` read
access did not stop `cov-manage-im` 2026.9.0 accepting it** (*measured*). The
POSIX case was not reproduced: WSL cannot reach this machine's Connect. Keep
the file private either way; on Linux, `chmod 600`.

## Checking a key

**Check over REST, not with `cov-manage-im --show`.**
`cov-manage-im --mode ... --show` cannot tell a dead key from an empty
result (*measured*):

| Situation | stdout | stderr | exit |
|---|---|---|---|
| Valid key, `--mode streams --show`, no streams | header row only | empty | **1** |
| Expired key, `--mode projects --show` | header row only | empty | **1** |
| Key from a previous install, `--mode projects --show` | header row only | empty | **1** |
| Right password, wrong username | header row only | empty | **1** |
| Valid key (`admin`), `--mode projects --show` | header + `Developer Streams` | empty | 0 |
| Connect not reachable | | `Connection refused` | 2 |

Authentication failures are silent; `--verbose 4` adds nothing, and
`cim.log` stays empty. Only an unreachable server is loud. So exit 1 tells
you nothing, and a probe that relies on it will call a dead key "an empty
instance".

REST gives a clean answer. `connect_auth.py check` sends one
`GET /api/v2/serverInfo/version` with HTTP Basic `username:key`, which the
REST reference documents as the way to authenticate with a key:

| Request | Status (*measured*) |
|---|---|
| valid key | **200**, JSON with `externalVersion` |
| expired, revoked, or wrong-instance key | **401**, body `Authentication failed.` |
| no credentials at all | **302** to the sign-in page |

**The 302 is the trap.** Python's `urllib` and `requests` follow redirects by
default, as does `curl -L`, so an unauthenticated probe lands on the sign-in
page with a **200** and HTML. That looks like success. The tool refuses
redirects and insists on a JSON body for that reason.

A 401 cannot tell you *why* a key was refused. The candidates are:

- expired;
- revoked;
- created on a different instance, or on this one before a reinstall or a
  database restore to a backup that predates it (`coverity-demo-data` relies
  on this: restoring an older backup deletes keys made since);
- the user was renamed (documented: keys must then be regenerated).

None of these is fixable from the key file. Create a new key.

Check a key **before** any long run that ends in a commit, and whenever you
find one on disk that you did not just create. A key from a previous install
looks exactly like a good one until the server refuses it.

## Using a key

| Consumer | How |
|---|---|
| `cov-commit-defects`, `cov-manage-im`, `cov-run-desktop` | `--auth-key-file <key>` (documented) |
| `cov-generate-cvss-report` and the other report generators | `--auth-key-file <key>` instead of `--password` (documented) |
| `coverity analyze` / `coverity commit` | `auth-key-file` in the CLI configuration; defaults to `~/.coverity/ak-<host>-<port>` (documented) |
| REST (`/api/v2/...`) | HTTP Basic, `username` and `key` from the key file (*measured*) |
| SOAP (`/ws/v9/...`) | WS-Security `UsernameToken`, `key` as the password (in use by `coverity-recreate-from-emit/tools/estimate_from_connect.py`) |

The documentation also says keys work for every administrative action
available as a web service: creating projects, streams and triage stores.

## Revoking a key

```bash
python3 tools/connect_auth.py revoke --url <connect-url> --bin $BIN \
    --auth-key-file <key> [--delete]
```

This runs `cov-manage-im --mode auth-key --revoke <id>`, authenticated with
**the key being revoked**, then confirms the server now returns 401 before it
deletes anything (*measured*). Facts behind it:

- **A key may revoke itself, and other keys of the same user, by id.** Only
  creation needs the password.
- Revocation takes effect immediately, and the key is deleted, not flagged:
  revoking the same id again fails with *"Authentication key N not found"*,
  exit 2.
- **Ids restart with each installation.** A key file left over from a
  previous install carried id 10002, and on the fresh instance 10002 was a
  different, live key (*measured*). So never revoke by the id in a file using
  some *other* credential. Authenticating with the file's own key makes this
  safe: a stale key is refused before the revoke runs.
- An orphaned key (created, file never written) can only be revoked by id.
  Find the id in Connect's `logs/usageLog.log`
  (`AuthenticationKeyCreationEvent`, with `keyId` and timestamp) or in the
  UI, and revoke it with another key of the same user.

The UI lists a user's active keys under *\<user\> > Authentication Keys*.
There is no REST endpoint for that list.

## What was not measured

- LDAP users: how `domain` and the username combine for REST Basic auth.
- The documented POSIX file-mode rejection.
- That the `coverity` CLI picks up `~/.coverity/ak-<host>-<port>`
  unconfigured. The default is documented; it was not exercised.
- Creation and use over HTTPS, with `--on-new-cert` or `--certs`.
