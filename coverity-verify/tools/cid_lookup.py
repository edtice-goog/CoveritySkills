#!/usr/bin/env python3
"""From a Coverity Connect CID to the thing coverity-verify verifies.

Two subcommands, because the CID lives in Connect and the events live in
the intermediate directory:

    lookup  ask Connect (REST v2 issues/search, HTTP Basic with an auth key)
            which stream, checker, file, function, line and merge key the CID
            is, and which snapshot last saw it
    select  find that issue in a `cov-format-errors --json-output-v10` file
            of the stream's idir, by merge key (stable across runs, rule 27)
            or by checker+file+function, and print the events

    python3 cid_lookup.py lookup --url <connect-url> --cid 12345 \
        [--auth-key-file ~/.coverity/ak-<host>-<port>] [--stream <s> | --project <p>] [--snapshot <id>]
    python3 cid_lookup.py select --findings findings.json --merge-key <key>
    python3 cid_lookup.py select --findings findings.json --checker FORWARD_NULL --file parser.c --function parse_config_path2

Connect facts this relies on (coverity/references/connect-auth.md and
coverity-cvss-report/tools/cvss_issue_export.py, both measured on 2026.9.0):
REST accepts HTTP Basic `username:key`; an unauthenticated request is a 302
to the sign-in page, so redirects are refused; `snapshotScope.show.scope:
"last"` returns zero rows for a project filter, so a snapshot id is asked for
and, failing that, the stream's snapshots are listed over SOAP
(getSnapshotsForStream, key as the WS-Security password) and the newest
used. The CID filter form (`cid` column, `idMatcher`) is from the REST
reference and NOT yet measured: on a 400 the tool falls back to a stream
or project filter (measured) and picks the CID client-side, and says so.

The URL comes from the caller, never from the key's comments (rule 28). The
key's secret is never printed. Pure standard library.
"""

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

COLUMNS = ["cid", "checker", "displayType", "displayImpact", "displayFile",
           "displayFunction", "lineNumber", "mergeKey", "stream", "project",
           "lastSnapshotId", "firstSnapshotId", "cwe", "status", "classification"]
WSSE = ("http://docs.oasis-open.org/wss/2004/01/"
        "oasis-200401-wss-wssecurity-secext-1.0.xsd")
PWTYPE = ("http://docs.oasis-open.org/wss/2004/01/"
          "oasis-200401-wss-username-token-profile-1.0#PasswordText")
NS = "http://ws.coverity.com/v9"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def default_key_path(url):
    u = urllib.parse.urlsplit(url)
    port = u.port or (443 if u.scheme == "https" else 80)
    return os.path.join(os.path.expanduser("~"), ".coverity", "ak-%s-%d" % (u.hostname, port))


def read_key(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if "username" not in d or "key" not in d:
        sys.exit("%s is not a Coverity authentication key file" % path)
    return d["username"], d["key"]


def rest(url, user, key, path, body=None):
    opener = urllib.request.build_opener(_NoRedirect)
    tok = base64.b64encode(("%s:%s" % (user, key)).encode()).decode()
    req = urllib.request.Request(url.rstrip("/") + path,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Accept": "application/json", "Content-Type": "application/json",
                                          "Authorization": "Basic " + tok})
    try:
        with opener.open(req, timeout=120) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def soap(url, user, key, body):
    env = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<S:Envelope xmlns:S="http://schemas.xmlsoap.org/soap/envelope/">'
           '<S:Header><wsse:Security xmlns:wsse="%s"><wsse:UsernameToken>'
           '<wsse:Username>%s</wsse:Username><wsse:Password Type="%s">%s</wsse:Password>'
           '</wsse:UsernameToken></wsse:Security></S:Header><S:Body>%s</S:Body></S:Envelope>'
           % (WSSE, user, PWTYPE, key, body))
    req = urllib.request.Request(url.rstrip("/") + "/ws/v9/configurationservice", data=env.encode("utf-8"),
                                 headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def newest_snapshot(url, user, key, stream):
    status, text = soap(url, user, key,
                        '<ns:getSnapshotsForStream xmlns:ns="%s"><streamId><name>%s</name></streamId>'
                        '</ns:getSnapshotsForStream>' % (NS, stream))
    if status != 200:
        f = re.search(r"(?s)<faultstring>(.*?)</faultstring>", text)
        sys.exit("getSnapshotsForStream(%s): HTTP %d %s" % (stream, status, f.group(1) if f else ""))
    ids = [int(x) for x in re.findall(r"<id>(\d+)</id>", text)]
    if not ids:
        sys.exit("stream %s has no snapshots" % stream)
    return max(ids)


def search(url, user, key, filters, columns, snapshot):
    body = {"filters": filters, "columns": list(columns),
            "snapshotScope": {"show": {"scope": str(snapshot), "includeOutdatedSnapshots": False}}}
    path = ("/api/v2/issues/search?includeColumnLabels=true&locale=en_us&offset=0"
            "&queryType=bySnapshot&rowCount=10000&sortOrder=asc")
    for _ in range(len(columns)):
        status, text = rest(url, user, key, path, body)
        if status == 200:
            return status, json.loads(text)
        m = re.search(r"column[^\"']*[\"']?(\w+)", text)
        # an unknown column key: drop it and retry, so one wrong guess does not end the lookup
        dropped = [c for c in body["columns"] if m and c == m.group(1)]
        if status == 400 and dropped:
            body["columns"] = [c for c in body["columns"] if c not in dropped]
            print("note: Connect rejected column %s; retrying without it" % dropped[0], file=sys.stderr)
            continue
        return status, text
    return status, text


def rows_to_dicts(doc):
    out = []
    for row in doc.get("rows", []):
        out.append({cell.get("key", ""): cell.get("value") for cell in row})
    return out


def cmd_lookup(a):
    user, key = read_key(a.auth_key_file or default_key_path(a.url))
    cid = int(a.cid)
    snapshot = a.snapshot
    if snapshot is None:
        if not a.stream:
            sys.exit("give --snapshot <id>, or --stream <name> so the newest snapshot can be looked up "
                     "(scope 'last' returns no rows on this API; measured)")
        snapshot = newest_snapshot(a.url, user, key, a.stream)
        print("snapshot: %d (newest of stream %s)" % (snapshot, a.stream), file=sys.stderr)

    # 1. the CID filter, as the REST reference describes it (not yet measured)
    filters = [{"columnKey": "cid", "matchMode": "oneOrMoreMatch",
                "matchers": [{"class": "Cid", "type": "idMatcher", "id": cid}]}]
    status, doc = search(a.url, user, key, filters, COLUMNS, snapshot)
    how = "cid filter"
    if status != 200:
        # 2. the measured form: filter by stream or project, pick the CID here
        if a.stream:
            filters = [{"columnKey": "streams", "matchMode": "oneOrMoreMatch",
                        "matchers": [{"class": "Stream", "name": a.stream, "type": "nameMatcher"}]}]
        elif a.project:
            filters = [{"columnKey": "project", "matchMode": "oneOrMoreMatch",
                        "matchers": [{"class": "Project", "name": a.project, "type": "nameMatcher"}]}]
        else:
            sys.exit("the cid filter was refused (HTTP %s: %s) and no --stream/--project was given to scan instead"
                     % (status, str(doc)[:300]))
        print("note: the cid filter was refused (HTTP %s); scanning the %s instead" % (status, "stream" if a.stream else "project"),
              file=sys.stderr)
        status, doc = search(a.url, user, key, filters, COLUMNS, snapshot)
        how = "stream/project scan"
        if status != 200:
            sys.exit("issues/search: HTTP %s: %s" % (status, str(doc)[:600]))
    if status == 302:
        sys.exit("redirected to the sign-in page: the request was not authenticated (check the key with connect_auth.py check)")
    rows = [r for r in rows_to_dicts(doc) if str(r.get("cid")) == str(cid)]
    if not rows:
        sys.exit("CID %d not found in snapshot %s (%s; %s rows returned). Is it in another stream, or an older snapshot?"
                 % (cid, snapshot, how, doc.get("totalRows")))
    r = rows[0]
    out = {"cid": cid, "snapshot": snapshot, "how": how,
           "stream": r.get("stream"), "project": r.get("project"), "checker": r.get("checker"),
           "type": r.get("displayType"), "impact": r.get("displayImpact"), "cwe": r.get("cwe"),
           "file": r.get("displayFile"), "function": r.get("displayFunction"), "line": r.get("lineNumber"),
           "mergeKey": r.get("mergeKey"), "status": r.get("status"), "classification": r.get("classification")}
    print(json.dumps(out, indent=1))
    print("\nnext: the events are in the idir that produced snapshot %s of stream %s:\n"
          "  cov-format-errors --dir <that idir> --json-output-v10 findings.json\n"
          "  python3 cid_lookup.py select --findings findings.json --merge-key %s"
          % (snapshot, out["stream"], out["mergeKey"] or "<see above>"), file=sys.stderr)
    return 0


def cmd_select(a):
    data = json.load(open(a.findings, encoding="utf-8"))
    hits = []
    for it in data.get("issues", []):
        if a.merge_key and it.get("mergeKey") == a.merge_key:
            hits.append(it)
        elif not a.merge_key and a.checker and it.get("checkerName") == a.checker \
                and (not a.file or os.path.basename(it.get("mainEventFilePathname", "")).endswith(a.file)) \
                and (not a.function or (it.get("functionDisplayName") or it.get("functionName") or "").startswith(a.function)):
            hits.append(it)
    if not hits:
        sys.exit("no issue matched in %s" % a.findings)
    for it in hits:
        print("%s  %s:%s  in %s  mergeKey %s" % (it.get("checkerName"), it.get("mainEventFilePathname"),
                                               it.get("mainEventLineNumber"), it.get("functionDisplayName") or it.get("functionName"),
                                               it.get("mergeKey")))
        for e in it.get("events", []):
            print("   %s%5s  %-16s %s" % ("*" if e.get("main") else " ", e.get("lineNumber"), e.get("eventTag", ""),
                                          e.get("eventDescription", "")[:140]))
        print()
    if len(hits) > 1:
        print("%d issues matched; the merge key from `lookup` picks one" % len(hits), file=sys.stderr)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lookup")
    p.add_argument("--url", required=True, help="Connect URL, from the user or the project (never from the key)")
    p.add_argument("--cid", required=True)
    p.add_argument("--auth-key-file", help="default ~/.coverity/ak-<host>-<port>")
    p.add_argument("--stream")
    p.add_argument("--project")
    p.add_argument("--snapshot", type=int)
    p.set_defaults(fn=cmd_lookup)
    p = sub.add_parser("select")
    p.add_argument("--findings", required=True, help="cov-format-errors --json-output-v10 file of the stream's idir")
    p.add_argument("--merge-key")
    p.add_argument("--checker")
    p.add_argument("--file")
    p.add_argument("--function")
    p.set_defaults(fn=cmd_select)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
