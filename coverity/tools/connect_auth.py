#!/usr/bin/env python3
"""Create, check and revoke Coverity Connect authentication keys.

Three subcommands, one per thing a session needs to do with a key.  The
procedure and the evidence behind it are in references/connect-auth.md.

    create   mint a key with cov-manage-im --mode auth-key --create, write it
             under ~/.coverity/, then check it.  Needs the user's password.
    check    one REST request, redirects refused: VALID, REJECTED, or
             UNREACHABLE.  Use this, not `cov-manage-im --show`, which
             reports a dead key exactly as it reports an empty list.
    revoke   revoke a key by the id inside it, confirm the server now refuses
             it, and optionally delete the file.  A key may revoke itself.

The Connect URL always comes from the caller, never from the key's `comments`
block (rule 28).  The password comes from a passphrase file, never the
command line.  Pure standard library.
"""

import argparse
import base64
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

EXIT_VALID, EXIT_REJECTED, EXIT_UNREACHABLE = 0, 1, 2

# --------------------------------------------------------------------------
# helpers


def run(cmd, env=None):
    """Run a command, returning (rc, stdout, stderr).  Never raises."""
    try:
        r = subprocess.run(
            cmd, env=env, capture_output=True, text=True, errors="replace",
            stdin=subprocess.DEVNULL, timeout=300,
        )
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"


def tool(bindir, name):
    exe = ".exe" if os.name == "nt" else ""
    return os.path.join(bindir, name + exe)


def default_key_path(url):
    """~/.coverity/ak-<host>-<port>: the `coverity` CLI's documented default
    for auth-key-file, so a key stored here is found without configuration.
    The cov-* commands do not look here; they still need --auth-key-file."""
    u = urllib.parse.urlsplit(url)
    port = u.port or (443 if u.scheme == "https" else 80)
    return os.path.join(os.path.expanduser("~"), ".coverity",
                        "ak-%s-%d" % (u.hostname, port))


def read_key(path):
    with open(path, encoding="utf-8") as f:
        try:
            d = json.load(f)
        except ValueError:
            d = {}
    if not isinstance(d, dict) or "key" not in d or "username" not in d:
        raise ValueError("%s is not a Coverity authentication key "
                         "(no username/key fields)" % path)
    return d


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def probe(url, keydata, insecure=False):
    """GET /api/v2/serverInfo/version with HTTP Basic username:key.

    Redirects are refused on purpose: Connect answers a request it does not
    consider authenticated with a 302 to the sign-in page, and a client that
    follows it receives a 200 HTML page that looks like success.
    Returns (verdict, detail)."""
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(
        _NoRedirect, urllib.request.HTTPSHandler(context=ctx))
    req = urllib.request.Request(url.rstrip("/") + "/api/v2/serverInfo/version")
    tok = "%s:%s" % (keydata["username"], keydata["key"])
    req.add_header("Authorization",
                   "Basic " + base64.b64encode(tok.encode()).decode())
    req.add_header("Accept", "application/json")
    try:
        with opener.open(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
            ctype = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return "REJECTED", "HTTP 401 (%s)" % e.read().decode(
                "utf-8", "replace").strip()
        if 300 <= e.code < 400:
            return "UNREACHABLE", (
                "HTTP %d redirect to %s -- the URL is probably not the Connect "
                "base URL (wrong scheme, port, or missing context path)"
                % (e.code, e.headers.get("Location")))
        return "UNREACHABLE", ("HTTP %d from %s -- no Connect REST API "
                               "answered at this URL" % (e.code, req.full_url))
    except (urllib.error.URLError, OSError) as e:
        return "UNREACHABLE", str(getattr(e, "reason", e))
    if "json" not in ctype:
        return "UNREACHABLE", "HTTP 200 but %s, not JSON -- not a Connect API" % ctype
    try:
        ver = json.loads(body).get("externalVersion", "?")
    except ValueError:
        ver = "?"
    return "VALID", "Connect %s" % ver


def report(url, path, keydata, verdict, detail):
    print("%-11s %s" % (verdict, detail))
    print("  key file : %s (id %s, user %s)" % (
        path, keydata.get("id", "?"), keydata["username"]))
    print("  target   : %s  (from the caller, never from the key)" % url)
    if verdict == "REJECTED":
        exp = keydata.get("comments", {}).get("expirationDate")
        print("  The server refused this key. Causes it cannot tell apart: "
              "expired, revoked,\n  created on another instance or before a "
              "database restore or reinstall, or\n  the user renamed. "
              "Create a new one.")
        if exp:
            print("  The key's own comments give expirationDate %s "
                  "(informational only)." % exp)


def verdict_exit(verdict):
    return {"VALID": EXIT_VALID, "REJECTED": EXIT_REJECTED}.get(
        verdict, EXIT_UNREACHABLE)


# --------------------------------------------------------------------------
# subcommands


def cmd_check(a):
    try:
        kd = read_key(a.auth_key_file)
    except (OSError, ValueError) as e:
        print("ERROR      %s" % e)
        return EXIT_UNREACHABLE
    verdict, detail = probe(a.url, kd, a.insecure)
    report(a.url, a.auth_key_file, kd, verdict, detail)
    return verdict_exit(verdict)


def cmd_create(a):
    pp = a.passphrase_file or os.environ.get("COVERITY_PASSPHRASE_FILE")
    if not pp or not os.path.isfile(pp):
        sys.exit("create needs the user's Connect password in a file: pass "
                 "--passphrase-file or set COVERITY_PASSPHRASE_FILE.\nAsk the "
                 "user for it, write it to a temporary file, and delete the "
                 "file afterwards.\nA key cannot create a key -- the server "
                 "requires a password for this one operation.")
    out = a.output_file or default_key_path(a.url)
    if os.path.exists(out) and not a.force:
        sys.exit("%s already exists. Check it first (`check`); pass --force "
                 "to replace it, or --output-file for another name." % out)
    # cov-manage-im will not create the directory itself.
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + ".new"
    if os.path.exists(tmp):
        os.remove(tmp)

    env = dict(os.environ, COVERITY_PASSPHRASE_FILE=pp, COV_USER=a.user)
    env.pop("COVERITY_PASSPHRASE", None)
    cmd = [tool(a.bin, "cov-manage-im"), "--url", a.url,
           "--mode", "auth-key", "--create", "--output-file", tmp,
           "--set", "description:" + a.description,
           "--set", "expiration:" + a.expiration]
    rc, so, se = run(cmd, env)
    if rc != 0 or not os.path.isfile(tmp):
        print((so + se).strip())
        sys.exit("cov-manage-im --mode auth-key --create failed (rc=%d)" % rc)
    os.replace(tmp, out)

    kd = read_key(out)
    verdict, detail = probe(a.url, kd, a.insecure)
    report(a.url, out, kd, verdict, detail)
    return verdict_exit(verdict)


def cmd_revoke(a):
    kd = read_key(a.auth_key_file)
    if "id" not in kd:
        sys.exit("%s carries no id; revoke it in the Connect UI "
                 "(<user> > Authentication Keys)" % a.auth_key_file)
    cmd = [tool(a.bin, "cov-manage-im"), "--url", a.url,
           "--auth-key-file", a.auth_key_file,
           "--mode", "auth-key", "--revoke", str(kd["id"])]
    rc, so, se = run(cmd)
    if rc != 0:
        print((so + se).strip())
        sys.exit("revoke failed (rc=%d)" % rc)
    verdict, detail = probe(a.url, kd, a.insecure)
    if verdict != "REJECTED":
        print("%-11s %s" % (verdict, detail))
        sys.exit("cov-manage-im reported success but the server did not "
                 "refuse the key afterwards; not deleting it")
    print("REVOKED    key id %s; the server now refuses it" % kd["id"])
    if a.delete:
        os.remove(a.auth_key_file)
        print("  deleted  %s" % a.auth_key_file)
    return EXIT_VALID


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--url", required=True,
                       help="Connect base URL, e.g. http://localhost:8080. "
                            "From the user -- never from the key (rule 28).")
        p.add_argument("--insecure", action="store_true",
                       help="accept a self-signed certificate (lab instances)")

    p = sub.add_parser("check", help="is this key accepted right now?")
    common(p)
    p.add_argument("--auth-key-file", required=True)
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("create", help="mint a key (needs the password)")
    common(p)
    p.add_argument("--bin", required=True,
                   help="<install>/bin of the pinned installation (rule 3)")
    p.add_argument("--user", required=True,
                   help="Connect user. Explicit, because cov-manage-im "
                        "otherwise falls back to the OS user name")
    p.add_argument("--passphrase-file",
                   help="file holding the password (default: "
                        "$COVERITY_PASSPHRASE_FILE)")
    p.add_argument("--output-file",
                   help="default: ~/.coverity/ak-<host>-<port>")
    p.add_argument("--description", default="created by connect_auth.py")
    p.add_argument("--expiration", default="after_90_days",
                   help="after_N_days, YYYY-MM-DD, or YYYY-MM-DDThh:mm")
    p.add_argument("--force", action="store_true",
                   help="replace an existing file at the output path")
    p.set_defaults(fn=cmd_create)

    p = sub.add_parser("revoke", help="revoke a key by the id inside it")
    common(p)
    p.add_argument("--bin", required=True)
    p.add_argument("--auth-key-file", required=True)
    p.add_argument("--delete", action="store_true",
                   help="delete the key file once the server refuses it")
    p.set_defaults(fn=cmd_revoke)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
