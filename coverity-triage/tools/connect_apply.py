#!/usr/bin/env python3
"""Step 6 (optional): apply coverity-triage records to a Coverity Connect.

  connect_apply.py --url <url> --records triage.json --project <name> --stream <name>
                   [--key-file <f>] [--cafile <f>] [--standard-only] [--overwrite]
                   [--yes] [--json]

Finds each record's finding in the stream by merge key, compares what the
record sets with the finding's current triage, and plans only what differs:

- a field the record leaves null (no verdict, no severity) is left alone;
- a field that already has the record's value is skipped;
- the comment is skipped when it is already the finding's last triage
  comment, so applying the same records twice does not post it twice;
- a finding whose Classification, Action, Severity or custom attribute
  already holds a value someone set (anything but the attribute's default)
  that differs from the record is not touched, unless --overwrite;
- with --standard-only, the custom attributes are neither checked nor set.

Without --yes it prints the plan and changes nothing. With --yes it writes
(one request per group of findings that get identical values), reads the
findings back, and fails if any value did not take.

Exit codes: 0 every record's finding now holds what the record sets; 3
changes still pending (no --yes), or a record skipped (not found in the
stream, or a value someone set, without --overwrite); 1 an error or a
refusal.

REST, measured on Connect 2026.9.0: POST /api/v2/issues/search (merge key
to CID, with the current triage), GET /api/v2/streams/<name> (the stream's
triage store), PUT /api/v2/issues/triage?triageStoreName=<store>.
Authentication is HTTP Basic with an auth key's username and key. The URL
comes from --url and never from the key file's comments (coverity rule 28).
"""
import argparse
import base64
import json
import pathlib
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

STANDARD = {"Classification": ("classification", "Unclassified"),
            "Action": ("action", "Undecided"),
            "Severity": ("severity", "Unspecified")}
CUSTOM = {"Defect Category": ("column_custom_Defect Category", "Unassigned"),
          "Triage Method": ("column_custom_Triage Method", "None")}
COMMENT_COLUMN = "lastTriageComment"
PAGE = 200


class Refusal(Exception):
    pass


def default_key_path(url):
    """~/.coverity/ak-<host>-<port>, where the coverity skill's connect_auth.py writes keys."""
    u = urllib.parse.urlsplit(url)
    port = u.port or (443 if u.scheme == "https" else 80)
    return pathlib.Path.home() / ".coverity" / ("ak-%s-%d" % (u.hostname, port))


class Connect:
    def __init__(self, url, key_file, cafile=None):
        key = json.loads(pathlib.Path(key_file).read_text(encoding="utf-8"))
        if not key.get("username") or not key.get("key"):
            raise Refusal(str(key_file) + " is not an auth key (no username and key)")
        self.base = url.rstrip("/")
        self.auth = "Basic " + base64.b64encode(
            (key["username"] + ":" + key["key"]).encode("utf-8")).decode("ascii")
        self.ctx = ssl.create_default_context(cafile=cafile) if self.base.startswith("https") else None

    def call(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Authorization": self.auth,
                                              "Accept": "application/json",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120, context=self.ctx) as r:
                text = r.read().decode("utf-8", "replace")
                return r.status, json.loads(text) if text.strip() else None
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(text)
            except ValueError:
                return e.code, text


def norm(v):
    return (v or "").replace("\r\n", "\n").strip()


def load_records(path):
    doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if doc.get("format") != "coverity-triage-records" or doc.get("schema") != 1:
        raise Refusal(str(path) + " is not a coverity-triage records file "
                      "(format coverity-triage-records, schema 1); run records.py validate")
    return doc.get("records", [])


def wanted(rec, standard_only):
    """{attribute name: value} the record sets; null means leave alone."""
    st = rec.get("triageState") or {}
    out = {}
    for name, key in (("Classification", "classification"), ("Action", "action"),
                      ("Severity", "severity"), ("Comment", "comment")):
        if st.get(key) is not None:
            out[name] = st[key]
    if not standard_only:
        for name in CUSTOM:
            v = (st.get("customTriage") or {}).get(name)
            if v is not None:
                out[name] = v
    return out


def triage_store(conn, stream):
    s, body = conn.call("GET", "/api/v2/streams/" + urllib.parse.quote(stream))
    if s != 200 or not (body or {}).get("streams"):
        raise Refusal("stream " + repr(stream) + ": HTTP " + str(s) + " " + str(body)[:200])
    st = body["streams"][0]
    if not st.get("triageStoreName"):
        raise Refusal("stream " + repr(stream) + " reports no triage store")
    return st["triageStoreName"], st.get("primaryProjectName")


def current_triage(conn, project, stream, standard_only):
    """{merge key: {column: value}} for every finding in the stream."""
    columns = ["cid", "mergeKey", COMMENT_COLUMN] + [c for c, _ in STANDARD.values()]
    if not standard_only:
        columns += [c for c, _ in CUSTOM.values()]
    filters = [{"columnKey": "project", "matchMode": "oneOrMoreMatch",
                "matchers": [{"class": "Project", "name": project, "type": "nameMatcher"}]},
               {"columnKey": "streams", "matchMode": "oneOrMoreMatch",
                "matchers": [{"class": "Stream", "name": stream, "type": "nameMatcher"}]}]
    found, offset, total = {}, 0, None
    while total is None or offset < total:
        s, body = conn.call("POST", "/api/v2/issues/search?offset=%d&rowCount=%d" % (offset, PAGE),
                            {"filters": filters, "columns": columns})
        if s != 200:
            raise Refusal("issue search: HTTP " + str(s) + " " + str(body)[:300])
        total = body.get("totalRows", 0)
        rows = body.get("rows") or []
        for row in rows:
            v = {c.get("key"): c.get("value") for c in row}
            mk = v.get("mergeKey")
            if mk in found and found[mk]["cid"] != v.get("cid"):
                raise Refusal("merge key " + mk + " maps to two CIDs in the stream ("
                              + found[mk]["cid"] + ", " + str(v.get("cid")) + ")")
            found[mk] = v
        if not rows:
            break
        offset += len(rows)
    return found


def check_custom_values(conn, records):
    needed = {name: set() for name in CUSTOM}
    for r in records:
        for name in CUSTOM:
            v = ((r.get("triageState") or {}).get("customTriage") or {}).get(name)
            if v is not None:
                needed[name].add(v)
    for name, values in needed.items():
        s, a = conn.call("GET", "/api/v2/triageAttributes/" + urllib.parse.quote(name))
        if s == 404:
            raise Refusal("the instance has no " + repr(name) + " attribute: run "
                          "connect_attributes.py setup --records <file> --yes first "
                          "(or apply with --standard-only)")
        if s != 200:
            raise Refusal("GET " + name + ": HTTP " + str(s) + " " + str(a)[:200])
        a = a.get("attributes", [a])[0] if "attributes" in a else a
        have = {v.get("name") for v in a.get("attributeValues") or [] if not v.get("deprecated")}
        missing = sorted(values - have)
        if missing:
            raise Refusal(repr(name) + " lacks value(s) " + ", ".join(missing)
                          + ": run connect_attributes.py setup --records <file> --yes first")


def plan(records, found, standard_only, overwrite):
    """-> one entry per record: status not-found | conflict | current | update."""
    out = []
    for r in records:
        mk = r.get("mergeKey")
        want = wanted(r, standard_only)
        cur = found.get(mk)
        entry = {"mergeKey": mk, "checker": r.get("checker"), "cid": None, "set": {},
                 "conflicts": {}}
        if cur is None:
            entry["status"] = "not-found"
            out.append(entry)
            continue
        entry["cid"] = cur["cid"]
        for name, value in want.items():
            if name == "Comment":
                if norm(cur.get(COMMENT_COLUMN)) != norm(value):
                    entry["set"][name] = value
                continue
            column, default = STANDARD.get(name) or CUSTOM[name]
            now = cur.get(column)
            if now == value:
                continue
            if now not in (None, "", default):
                entry["conflicts"][name] = {"now": now, "record": value}
            entry["set"][name] = value
        if entry["conflicts"] and not overwrite:
            entry["status"] = "conflict"
        elif entry["set"]:
            entry["status"] = "update"
        else:
            entry["status"] = "current"
        out.append(entry)
    return out


def apply_updates(conn, store, entries):
    groups = {}
    for e in entries:
        if e["status"] != "update":
            continue
        key = json.dumps(sorted(e["set"].items()))
        groups.setdefault(key, []).append(int(e["cid"]))
    for key, cids in groups.items():
        values = [{"attributeName": n, "attributeValue": v} for n, v in json.loads(key)]
        s, resp = conn.call("PUT", "/api/v2/issues/triage?triageStoreName="
                            + urllib.parse.quote(store), {"cids": cids, "attributeValuesList": values})
        if not 200 <= s < 300:
            raise Refusal("triage write for CIDs " + ", ".join(map(str, cids)) + ": HTTP "
                          + str(s) + " " + str(resp)[:300])
    return len(groups)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", required=True, help="the Connect's URL, from you, never from a key file")
    ap.add_argument("--records", required=True, help="triage.json from records.py assemble")
    ap.add_argument("--project", required=True, help="the Connect project the findings are in")
    ap.add_argument("--stream", required=True, help="the stream of the analyzed version; its "
                                                    "triage store is the one written")
    ap.add_argument("--key-file", help="auth key file (default: ~/.coverity/ak-<host>-<port>)")
    ap.add_argument("--cafile", help="a CA bundle for an instance whose certificate the system "
                                     "does not trust")
    ap.add_argument("--standard-only", action="store_true",
                    help="set only Classification, Action, Severity and Comment")
    ap.add_argument("--overwrite", action="store_true",
                    help="also change values someone already set on a finding")
    ap.add_argument("--yes", action="store_true", help="write (default: plan only)")
    ap.add_argument("--json", action="store_true", help="print one JSON object, for scripts")
    args = ap.parse_args()
    result = {"url": args.url, "project": args.project, "stream": args.stream,
              "applied": False, "verified": False}
    try:
        records = load_records(args.records)
        conn = Connect(args.url, args.key_file or default_key_path(args.url), args.cafile)
        store, primary = triage_store(conn, args.stream)
        result["triageStore"] = store
        if not args.standard_only:
            check_custom_values(conn, records)
        try:
            found = current_triage(conn, args.project, args.stream, args.standard_only)
        except Refusal as e:
            # Connect answers an unknown project with a bare HTTP 500; name the likely one.
            if primary and primary != args.project:
                raise Refusal(str(e) + " (the stream's primary project is " + repr(primary) + ")")
            raise
        entries = plan(records, found, args.standard_only, args.overwrite)
        if args.yes and any(e["status"] == "update" for e in entries):
            result["requests"] = apply_updates(conn, store, entries)
            result["applied"] = True
            after = plan(records, current_triage(conn, args.project, args.stream,
                                                 args.standard_only),
                         args.standard_only, args.overwrite)
            unchanged = [a for a, e in zip(after, entries)
                         if e["status"] == "update" and a["status"] != "current"]
            if unchanged:
                raise Refusal("after the write, " + str(len(unchanged)) + " finding(s) do not "
                              "hold the record's values: " + "; ".join(
                                  str(a["cid"]) + " " + ", ".join(sorted(a["set"]))
                                  for a in unchanged[:5]))
            result["verified"] = True
            entries = [dict(e, status="applied") if e["status"] == "update" else e
                       for e in entries]
        result["records"] = len(entries)
        result["plan"] = entries
    except (Refusal, OSError, ValueError, KeyError) as e:
        result["error"] = str(e)
        if args.json:
            print(json.dumps(result, indent=1, ensure_ascii=False))
        else:
            print("[ERROR] " + str(e), file=sys.stderr)
        return 1
    counts = {}
    for e in entries:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    result["counts"] = counts
    if args.json:
        print(json.dumps(result, indent=1, ensure_ascii=False))
    else:
        print("%d record(s) against %s / %s (triage store %s): %s" % (
            len(entries), args.project, args.stream, store,
            ", ".join("%s %d" % kv for kv in sorted(counts.items()))))
        for e in entries:
            if e["status"] == "not-found":
                print("  not found in the stream: " + str(e["mergeKey"]) + " " + str(e["checker"]))
            elif e["status"] == "conflict":
                print("  left alone (someone set it; --overwrite to change): CID " + e["cid"] + " "
                      + "; ".join("%s %s -> %s" % (n, c["now"], c["record"])
                                  for n, c in e["conflicts"].items()))
            elif e["status"] in ("update", "applied"):
                print("  %s CID %s: %s" % ("set" if e["status"] == "applied" else "would set",
                                            e["cid"], ", ".join(sorted(e["set"]))))
        if not result["applied"] and counts.get("update"):
            print("nothing written (run with --yes to apply)")
    done = all(e["status"] in ("current", "applied") for e in entries)
    return 0 if done else 3


if __name__ == "__main__":
    sys.exit(main())
