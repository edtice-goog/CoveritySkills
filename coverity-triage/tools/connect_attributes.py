#!/usr/bin/env python3
"""Create the two custom triage attributes that coverity-triage's records set.

  connect_attributes.py check --url <url> [--key-file <f>] [--records triage.json]
                              [--model "Sonnet 5.5" ...] [--json]
  connect_attributes.py setup --url <url> [--key-file <f>] [--records triage.json]
                              [--model "Sonnet 5.5" ...] [--yes] [--json]

Defect Category holds a finding's lane; Triage Method holds the method that
produced its verdict (references/records.md). Both are pick lists, and a
record can set only a value its list already has. Triage Method needs one
"LLM: <model>" value per model, given with --model or read from the methods
a triage.json uses.

check reads the instance and reports what is missing. setup without --yes
prints the same plan and changes nothing; with --yes it creates the missing
attributes and adds the missing values. Nothing here deletes or renames an
attribute or a value, or changes an attribute's type. An attribute that
exists with another type, or a needed value marked deprecated, is reported,
and the tool stops.

Exit codes: 0 nothing is missing (or setup --yes made it so); 3 something is
missing (check, or setup without --yes); 1 an error or a refusal.

REST, measured on Connect 2026.9.0: /api/v2/triageAttributes (the REST
reference names /api/v2/attributes, which that server does not serve).
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

API = "/api/v2/triageAttributes"
LANES = ("Construction", "Intent", "Contract", "Value or path", "Policy", "Other")
LANE_DEFAULT = "Unassigned"
METHOD_BASE = ("None", "Execution: coverity-verify", "Human")
METHOD_DEFAULT = "None"
DESCRIPTIONS = {
    "Defect Category": "The finding's lane in coverity-triage: the kind of claim it makes",
    "Triage Method": "The method that produced the finding's triage verdict",
}


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
            with urllib.request.urlopen(req, timeout=60, context=self.ctx) as r:
                text = r.read().decode("utf-8", "replace")
                return r.status, json.loads(text) if text.strip() else None
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(text)
            except ValueError:
                return e.code, text

    def get_attribute(self, name):
        s, body = self.call("GET", API + "/" + urllib.parse.quote(name))
        if s == 200:
            return body.get("attributes", [body])[0] if "attributes" in body else body
        if s == 404:
            return None
        raise Refusal("GET " + name + ": HTTP " + str(s) + " " + str(body)[:300])


def needed_values(models, records):
    methods = list(METHOD_BASE)
    for m in models:
        m = m.strip()
        if not m:
            continue
        v = m if m.startswith("LLM: ") else "LLM: " + m
        if v not in methods:
            methods.append(v)
    if records:
        doc = json.loads(pathlib.Path(records).read_text(encoding="utf-8"))
        for r in doc.get("records", []):
            v = (r.get("triageState") or {}).get("customTriage", {}).get("Triage Method")
            if v and v not in methods:
                methods.append(v)
            lane = (r.get("triageState") or {}).get("customTriage", {}).get("Defect Category")
            if lane and lane not in LANES:
                raise Refusal(records + ": a record carries Defect Category " + repr(lane)
                              + ", which is not a lane")
    return {"Defect Category": (LANE_DEFAULT, [LANE_DEFAULT] + list(LANES)),
            "Triage Method": (METHOD_DEFAULT, methods)}


def plan(conn, needs):
    """-> list of (name, action, detail, request body or None) for what is missing."""
    out = []
    for name, (default, values) in needs.items():
        a = conn.get_attribute(name)
        if a is None:
            out.append((name, "create", values, {
                "name": name, "description": DESCRIPTIONS[name],
                "attributeType": "LIST_OF_VALUES", "showInTriage": True,
                "defaultValueName": default,
                "attributeValues": [{"name": v} for v in values]}))
            continue
        if a.get("attributeType") != "LIST_OF_VALUES":
            raise Refusal(name + " exists as " + str(a.get("attributeType"))
                          + ", not a pick list (LIST_OF_VALUES); change it in Connect, or remove "
                          "it there, then run setup again")
        have = {v.get("name"): v for v in a.get("attributeValues") or []}
        stale = [v for v in values if v in have and have[v].get("deprecated")]
        if stale:
            raise Refusal(name + ": value(s) " + ", ".join(stale) + " are deprecated on the "
                          "instance; restore them in Connect first")
        missing = [v for v in values if v not in have]
        if missing:
            # A PUT replaces the value list (measured: a value left out is removed),
            # so the whole definition goes back with every value it already has,
            # ids included, plus the new ones.
            body = {k: a[k] for k in ("name", "description", "attributeType", "showInTriage",
                                      "defaultValueName") if k in a}
            body["attributeValues"] = list(a.get("attributeValues") or []) + \
                [{"name": v} for v in missing]
            out.append((name, "add values", missing, body))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("check", "setup"):
        p = sub.add_parser(c)
        p.add_argument("--url", required=True, help="the Connect's URL, from you, never from a key file")
        p.add_argument("--key-file", help="auth key file (default: ~/.coverity/ak-<host>-<port>)")
        p.add_argument("--cafile", help="a CA bundle for an instance whose certificate the "
                                        "system does not trust")
        p.add_argument("--records", help="a triage.json whose lanes and methods must all be values")
        p.add_argument("--model", action="append", default=[],
                       help="a model whose LLM verdicts the instance will record; repeatable")
        p.add_argument("--json", action="store_true", help="print one JSON object, for scripts")
        if c == "setup":
            p.add_argument("--yes", action="store_true", help="make the changes (default: plan only)")
    args = ap.parse_args()
    result = {"url": args.url, "changes": [], "applied": False}
    try:
        key_file = args.key_file or default_key_path(args.url)
        conn = Connect(args.url, key_file, args.cafile)
        changes = plan(conn, needed_values(args.model, args.records))
        result["changes"] = [{"attribute": n, "action": act, "values": vals}
                             for n, act, vals, _ in changes]
        if changes and args.cmd == "setup" and args.yes:
            for name, action, vals, body in changes:
                if action == "create":
                    s, resp = conn.call("POST", API, body)
                else:
                    s, resp = conn.call("PUT", API + "/" + urllib.parse.quote(name), body)
                if s >= 300:
                    raise Refusal(action + " " + name + ": HTTP " + str(s) + " " + str(resp)[:300])
            result["applied"] = True
            changes = plan(conn, needed_values(args.model, args.records))
            if changes:
                raise Refusal("after setup, still missing: " + "; ".join(
                    n + " " + ", ".join(v) for n, _, v, _ in changes))
            result["changes_left"] = []
    except (Refusal, OSError, ValueError) as e:
        result["error"] = str(e)
        if args.json:
            print(json.dumps(result, indent=1))
        else:
            print("[ERROR] " + str(e), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=1))
    elif not result["changes"]:
        print("nothing missing: Defect Category and Triage Method have every value needed")
    else:
        for ch in result["changes"]:
            print(("done: " if result["applied"] else "missing: ") + ch["attribute"] + ": "
                  + ch["action"] + ": " + ", ".join(ch["values"]))
        if not result["applied"]:
            print("nothing changed" + (" (run setup --yes to make these changes)"
                                       if args.cmd == "setup" else ""))
    return 0 if (not result["changes"] or result["applied"]) else 3


if __name__ == "__main__":
    sys.exit(main())
