#!/usr/bin/env python3
"""Create the four CVSS triage attributes in Coverity Connect.

The CVSS Report Generator requires CVSS_Audited, CVSS_Score, CVSS_Severity
and CVSS_Vector to exist before its first run, and nothing else can make
them: cov-manage-im sets attribute *values* on defects, not attribute
*definitions*, and the REST API exposes only displayType, displayCategory
and checker under /api/v2/checkerAttributes.  createAttribute on the v9
SOAP configuration service is the scriptable route, so this is a small
client for exactly that, plus the reads needed to check the result.

The accepted attributeType spellings are STRING and LIST_OF_VALUES, from
the platform API reference's "Attribute type (attributeType)" table -- not
the lowercase names the SDK's own enums use, and not "TEXT".

Credentials come from COV_USER and COVERITY_PASSPHRASE_FILE, never the
command line.  COV_WS_URL overrides the endpoint.

    cvss_attributes.py setup                 # create all four, idempotent
    cvss_attributes.py get <AttributeName>
    cvss_attributes.py snapshots <stream>    # snapshot ids, newest last
    cvss_attributes.py create-text <Name> [description]
    cvss_attributes.py create-list <Name> <default> <v1,v2,..> [description]
"""

import os
import re
import sys
import urllib.error
import urllib.request
from xml.sax.saxutils import escape

URL = os.environ.get("COV_WS_URL",
                     "http://localhost:8080/ws/v9/configurationservice")
NS = "http://ws.coverity.com/v9"
WSSE = ("http://docs.oasis-open.org/wss/2004/01/"
        "oasis-200401-wss-wssecurity-secext-1.0.xsd")
PWTYPE = ("http://docs.oasis-open.org/wss/2004/01/"
          "oasis-200401-wss-username-token-profile-1.0#PasswordText")

#  The four the generator requires.  CVSS_Audited defaults to No: a Yes
#  freezes CVSS_Vector against every later run, which is the reviewer's
#  override and must not be the starting state.
REQUIRED = [
    ("CVSS_Vector", "text", None, None,
     "CVSS base vector, set by cov-generate-cvss-report"),
    ("CVSS_Score", "text", None, None,
     "CVSS base score, computed from CVSS_Vector"),
    ("CVSS_Severity", "list", "None", "None,Low,Medium,High,Critical",
     "CVSS qualitative rating, computed from CVSS_Score"),
    ("CVSS_Audited", "list", "No", "No,Yes",
     "Yes freezes CVSS_Vector against later report runs"),
]


def creds():
    user = os.environ.get("COV_USER", "admin")
    path = os.environ.get("COVERITY_PASSPHRASE_FILE")
    if not path:
        sys.exit("set COVERITY_PASSPHRASE_FILE to a file holding the password")
    with open(path, "r", encoding="utf-8") as f:
        return user, f.read().strip("\r\n")


def call(body):
    user, pw = creds()
    env = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<S:Envelope xmlns:S="http://schemas.xmlsoap.org/soap/envelope/">'
           '<S:Header><wsse:Security xmlns:wsse="%s">'
           '<wsse:UsernameToken><wsse:Username>%s</wsse:Username>'
           '<wsse:Password Type="%s">%s</wsse:Password>'
           '</wsse:UsernameToken></wsse:Security></S:Header>'
           '<S:Body>%s</S:Body></S:Envelope>'
           % (WSSE, escape(user), PWTYPE, escape(pw), body))
    req = urllib.request.Request(
        URL, data=env.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def show(status, text):
    print("HTTP %d" % status)
    f = re.search(r"(?s)<faultstring>(.*?)</faultstring>", text)
    if f:
        print("FAULT: %s" % f.group(1))
        return 1
    stripped = re.sub(r"(?s)<[^>]+>", " ", text)
    print(" ".join(stripped.split()) or "(empty body)")
    return 0


def body_get(name):
    return ('<ns:getAttribute xmlns:ns="%s"><attributeDefinitionId>'
            '<name>%s</name></attributeDefinitionId></ns:getAttribute>'
            % (NS, escape(name)))


def body_create_text(name, desc):
    return ('<ns:createAttribute xmlns:ns="%s"><attributeDefinitionSpec>'
            '<attributeName>%s</attributeName>'
            '<attributeType>STRING</attributeType>'
            '<description>%s</description>'
            '<showInTriage>true</showInTriage>'
            '</attributeDefinitionSpec></ns:createAttribute>'
            % (NS, escape(name), escape(desc)))


def body_create_list(name, default, values, desc):
    vals = "".join('<attributeValues><name>%s</name>'
                   '<deprecated>false</deprecated></attributeValues>'
                   % escape(v) for v in values)
    return ('<ns:createAttribute xmlns:ns="%s"><attributeDefinitionSpec>'
            '<attributeName>%s</attributeName>'
            '<attributeType>LIST_OF_VALUES</attributeType>'
            '<attributeValueChangeSpec>%s</attributeValueChangeSpec>'
            '<defaultValue>%s</defaultValue>'
            '<description>%s</description>'
            '<showInTriage>true</showInTriage>'
            '</attributeDefinitionSpec></ns:createAttribute>'
            % (NS, escape(name), vals, escape(default), escape(desc)))


def body_snapshots(stream):
    return ('<ns:getSnapshotsForStream xmlns:ns="%s"><streamId>'
            '<name>%s</name></streamId></ns:getSnapshotsForStream>'
            % (NS, escape(stream)))


def cmd_setup():
    """Create any of the four that are missing.  Safe to re-run."""
    rc = 0
    for name, kind, default, values, desc in REQUIRED:
        _, text = call(body_get(name))
        if "No attribute found" not in text:
            print("%-14s already exists" % name)
            continue
        if kind == "text":
            b = body_create_text(name, desc)
        else:
            b = body_create_list(name, default, values.split(","), desc)
        status, text = call(b)
        if "<faultstring>" in text:
            print("%-14s FAILED" % name)
            show(status, text)
            rc = 1
        else:
            print("%-14s created" % name)
    return rc


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "setup":
        return cmd_setup()
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, name = sys.argv[1], sys.argv[2]
    if cmd == "get":
        body = body_get(name)
    elif cmd == "snapshots":
        body = body_snapshots(name)
    elif cmd == "create-text":
        body = body_create_text(name,
                                sys.argv[3] if len(sys.argv) > 3 else "")
    elif cmd == "create-list":
        body = body_create_list(name, sys.argv[3], sys.argv[4].split(","),
                                sys.argv[5] if len(sys.argv) > 5 else "")
    else:
        sys.exit("unknown command %r" % cmd)
    return show(*call(body))


if __name__ == "__main__":
    sys.exit(main())
