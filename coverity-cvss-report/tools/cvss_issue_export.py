#!/usr/bin/env python3
"""Export a project's issues, with their CWEs, from Connect's REST v2 API.

This is what `cvss_profile_audit.py audit --issues` wants, and the reason a
separate tool is needed: the generator's own WRITE_ISSUES_JSON does NOT
contain the CWE.  Its `optCweId` serializes as
`{"empty": false, "present": true}` -- the Optional's bean properties with
the value dropped -- so it can verify the arithmetic (see `verify`) and
cannot tell you which CWE produced a score.  cov-manage-im has no CWE
field either.

Three things about this API that cost time to find out:

  * the custom attributes are keyed `column_custom_<Name>`, so the CVSS
    ones are `column_custom_CVSS_Vector` and friends;
  * `snapshotScope.show.scope: "last"` returns zero rows -- pass a real
    snapshot id (`cvss_attributes.py snapshots <stream>` lists them);
  * the `name` query parameter on /api/v2/projects and /api/v2/streams is
    ignored, so filter client-side.

Credentials come from COV_USER and COVERITY_PASSPHRASE_FILE, never the
command line.  COV_HOST overrides the base URL.

    COV_SNAPSHOT=<id> cvss_issue_export.py <project> [col,col,...]
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request

HOST = os.environ.get("COV_HOST", "http://localhost:8080")

DEFAULT_COLUMNS = ["cid", "checker", "displayType", "cwe", "displayFile",
                   "displayImpact", "column_custom_CVSS_Vector",
                   "column_custom_CVSS_Score",
                   "column_custom_CVSS_Severity",
                   "column_custom_CVSS_Audited"]


def creds():
    user = os.environ.get("COV_USER", "admin")
    path = os.environ.get("COVERITY_PASSPHRASE_FILE")
    if not path:
        sys.exit("set COVERITY_PASSPHRASE_FILE to a file holding the password")
    with open(path, "r", encoding="utf-8") as f:
        return user, f.read().strip("\r\n")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    project = sys.argv[1]
    cols = sys.argv[2].split(",") if len(sys.argv) > 2 else DEFAULT_COLUMNS
    scope = os.environ.get("COV_SNAPSHOT", "last")
    body = {
        "filters": [{
            "columnKey": "project",
            "matchMode": "oneOrMoreMatch",
            "matchers": [{"class": "Project", "name": project,
                          "type": "nameMatcher"}],
        }],
        "columns": cols,
        "snapshotScope": {"show": {"scope": scope,
                                   "includeOutdatedSnapshots": False}},
    }
    url = (HOST + "/api/v2/issues/search?includeColumnLabels=true"
                  "&locale=en_us&offset=0&queryType=bySnapshot"
                  "&rowCount=" + os.environ.get("COV_ROWS", "10000") +
           "&sortOrder=asc")
    user, pw = creds()
    tok = base64.b64encode(("%s:%s" % (user, pw)).encode()).decode()
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json",
                 "Authorization": "Basic " + tok})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            doc = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit("HTTP %d: %s"
                 % (e.code, e.read().decode("utf-8", "replace")[:800]))

    rows = doc.get("rows", [])
    out = []
    for row in rows:
        d = {}
        for cell in row:
            d[cell.get("key")] = cell.get("value")
        out.append(d)
    if not out and scope == "last":
        sys.stderr.write("0 rows with scope 'last' -- this API needs an "
                         "explicit snapshot id; set COV_SNAPSHOT.\n")
    dest = os.environ.get("COV_ISSUES_OUT", "issues_rest.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print("%d row(s) of %s -> %s" % (len(out), doc.get("totalRows"), dest))

    keys = [c for c in cols if any(c in d for d in out)]
    print("\t".join(k.replace("column_custom_", "") for k in keys))
    for d in sorted(out, key=lambda d: str(d.get("checker"))):
        print("\t".join(str(d.get(k, "")) for k in keys))
    return 0


if __name__ == "__main__":
    sys.exit(main())
