#!/usr/bin/env python3
"""Run a Coverity CVSS report so the reader knows what they got.

The generator scores every defect, including the ones it has no judgement
for, and the report does not mark the difference.  This drives the whole
sequence and uses CVSS_Audited to record that difference where the user
will actually see it -- in Connect, next to the score.

    0. attributes   the four CVSS_* attributes exist   (cvss_attributes.py)
       selftest     OPTIONAL but recommended once per Reports build: does it
                    honour CVSS_Audited at all?  In 2025.3.0 it does not.
    1. config       write and validate config.yaml
    2. scores       cov-generate-cvss-report --scores   (the calculation)
    3. mark         CVSS_Audited=Yes where a mapping judged the CWE,
                    left No where the zero is nobody's decision
    4. infer        OPTIONAL: propose vectors for what step 3 left No
    5. report       cov-generate-cvss-report --report   (the PDF)

`status` prints where a project stands at any point, and `reset` puts
CVSS_Audited back to No.

Two things to understand before running `mark`:

  * The guide says CVSS_Audited=Yes stops the generator updating that
    defect's vector.  In Reports 2025.3.0 it does NOT: --scores rewrites all
    four CVSS_* attributes unconditionally, so a Yes becomes No and a
    hand-written vector is discarded.  Measured in both a custom and the
    Default triage store.  So `mark` and `infer --apply` must come after the
    final --scores run, and the CSVs are the durable record.  `selftest`
    re-measures this against your build, since a later one may fix it.
  * The rule for Yes is "a mapping judged this CWE": the CWE has its own
    entry in a profile, or the lookup produced a non-zero score.  A zero
    reached by inheriting a zero-impact ancestor is left No, because the
    judgement was about the ancestor, not this CWE.

Credentials: COV_USER and COVERITY_PASSPHRASE_FILE.  Never on the command
line.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cvss_profile_audit as audit  # noqa: E402

HOST = os.environ.get("COV_HOST", "http://localhost:8080")

#  The three cases that matter, decided per CWE as Coverity Connect
#  reports it, against the report generator actually in use.  Nothing here
#  consults a checker inventory: the Connect version, the Coverity Analysis
#  version that produced the snapshot, and any local Coverity install can
#  all differ, so the only sound population is the CWEs the snapshot really
#  carries.
#
#    (b) non-zero mapping  -- a mapping judged this CWE and gave it impact
#    (a) zero mapping      -- a mapping judged this CWE and gave it none
#    (c) no mapping        -- nothing judged this CWE; the zero is accidental
#
CASE_B = "(b) non-zero mapping"
CASE_A = "(a) zero mapping, deliberate"
CASE_C = "(c) NO mapping -- zero by accident"
CASE_NOCWE = "no CWE from Connect -- zero, no lookup"

#  A direct profile entry is a judgement about this CWE.  A non-zero score
#  reached through an ancestor is also a mapping doing its job.  A zero
#  reached through an ancestor is not a judgement about this CWE, so it is
#  case (c): had the generator known this CWE, it might have scored it.
def case_of(res):
    if res["class"] == audit.DESIGN:
        return CASE_A
    if res["raw"] > 0:
        return CASE_B
    return CASE_C


# --------------------------------------------------------------------------
# Connect


def creds():
    user = os.environ.get("COV_USER", "admin")
    path = os.environ.get("COVERITY_PASSPHRASE_FILE")
    if not path:
        sys.exit("set COVERITY_PASSPHRASE_FILE to a file holding the password")
    with open(path, "r", encoding="utf-8") as f:
        return user, f.read().strip("\r\n")


def rest(method, path, body=None, attempts=3):
    """One REST call, retrying 5xx.

    A Connect instance is usually shared, and a busy one returns a bare 500
    with an event id now and then.  Retrying twice costs nothing and saves a
    half-finished marking run.
    """
    user, pw = creds()
    tok = base64.b64encode(("%s:%s" % (user, pw)).encode()).decode()
    data = json.dumps(body).encode() if body is not None else None
    last = (None, None)
    for attempt in range(attempts):
        req = urllib.request.Request(
            HOST + path, data=data, method=method,
            headers={"Content-Type": "application/json",
                     "Accept": "application/json",
                     "Authorization": "Basic " + tok})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                raw = r.read().decode("utf-8", "replace")
                return r.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as e:
            last = (e.code, e.read().decode("utf-8", "replace")[:1000])
            if e.code < 500 or attempt == attempts - 1:
                return last
            time.sleep(2 * (attempt + 1))
        except urllib.error.URLError as e:
            last = (None, str(e))
            if attempt == attempts - 1:
                return last
            time.sleep(2 * (attempt + 1))
    return last


COLUMNS = ["cid", "checker", "displayType", "cwe", "displayFile",
           "displayCategory", "displayImpact", "displayIssueKind",
           "column_custom_CVSS_Vector", "column_custom_CVSS_Score",
           "column_custom_CVSS_Severity", "column_custom_CVSS_Audited"]


def issues(project, snapshot):
    """Rows for a project at a snapshot.  scope 'last' returns nothing, so
    the snapshot id is required rather than optional."""
    body = {"filters": [{"columnKey": "project",
                         "matchMode": "oneOrMoreMatch",
                         "matchers": [{"class": "Project", "name": project,
                                       "type": "nameMatcher"}]}],
            "columns": COLUMNS,
            "snapshotScope": {"show": {"scope": str(snapshot),
                                       "includeOutdatedSnapshots": False}}}
    status, doc = rest("POST", "/api/v2/issues/search?includeColumnLabels=true"
                               "&locale=en_us&offset=0&queryType=bySnapshot"
                               "&rowCount=10000&sortOrder=asc", body)
    if status != 200:
        sys.exit("issues/search failed: HTTP %s %s" % (status, doc))
    out = []
    for row in doc.get("rows", []):
        d = {}
        for cell in row:
            k = cell.get("key", "")
            d[k.replace("column_custom_", "")] = cell.get("value")
        out.append(d)
    if not out:
        sys.exit("no issues for project %r at snapshot %r -- check the "
                 "snapshot id (cvss_attributes.py snapshots <stream>)"
                 % (project, snapshot))
    return out


def triage_store_for(project):
    status, doc = rest("GET", "/api/v2/streams")
    if status != 200:
        sys.exit("cannot list streams: HTTP %s" % status)
    stores = []
    for st in doc.get("streams", []):
        if st.get("primaryProjectName") == project:
            stores.append(st.get("triageStoreName"))
    stores = sorted(set(s for s in stores if s))
    if not stores:
        sys.exit("no stream of project %r found, so no triage store" % project)
    if len(stores) > 1:
        sys.exit("project %r spans triage stores %s -- pass --triage-store"
                 % (project, stores))
    return stores[0]


def set_attributes(store, cids, values, batch=200):
    """PUT /api/v2/issues/triage, in batches."""
    avl = [{"attributeName": k, "attributeValue": v}
           for k, v in values.items()]
    done = 0
    for i in range(0, len(cids), batch):
        chunk = [int(c) for c in cids[i:i + batch]]
        status, doc = rest(
            "PUT", "/api/v2/issues/triage?triageStoreName="
                   + urllib.request.quote(store),
            {"cids": chunk, "attributeValuesList": avl})
        if status not in (200, 204):
            sys.exit("triage update failed at cid %s: HTTP %s %s"
                     % (chunk[0], status, doc))
        done += len(chunk)
    return done


# --------------------------------------------------------------------------
# the mapping verdict per defect


def classify(rows, args):
    """Attach the audit's verdict to each row.  No writes."""
    master, tax = audit.load_install(args.reports_dir)
    user = audit.Profile(args.profile) if args.profile else None
    graph = audit.build_graph(args, tax)
    cache = {}
    for r in rows:
        cwe = str(r.get("cwe") or "").strip()
        if not cwe.isdigit():
            #  Connect gave this defect no CWE, so no lookup happens at
            #  all and the generator writes its hardcoded zero vector.
            r["_case"] = CASE_NOCWE
            r["_class"] = "no CWE at all"
            r["_audited"] = False
            continue
        if cwe not in cache:
            cache[cwe] = audit.resolve(cwe, master, user, tax, graph)
        res = cache[cwe]
        r["_case"] = case_of(res)
        r["_class"] = res["class"]
        r["_audited"] = r["_case"] in (CASE_A, CASE_B)
        r["_predicted"] = res
    return rows, (master, tax, user, graph)


def summarise(rows):
    """Print the (a)/(b)/(c) split by CWE, then by issue count."""
    per_cwe = {}
    for r in rows:
        key = (r["_case"], r.get("cwe") or "(none)")
        per_cwe[key] = per_cwe.get(key, 0) + 1
    order = {CASE_B: 0, CASE_A: 1, CASE_C: 2}
    cases = {}
    for (case, cwe), n in per_cwe.items():
        cases.setdefault(case, []).append((cwe, n))
    print("  %-38s %6s %8s  %s" % ("case", "CWEs", "issues", "audited"))
    for case in sorted(cases, key=lambda c: order.get(c, 9)):
        rows_c = cases[case]
        print("  %-38.38s %6d %8d  %s"
              % (case, len(rows_c), sum(n for _, n in rows_c),
                 "Yes" if case in (CASE_A, CASE_B) else "No"))
    unaudited = [r for r in rows if not r["_audited"]]
    return unaudited


# --------------------------------------------------------------------------
# steps


def cmd_config(args):
    """Write a config.yaml the generator will accept.

    Every mandatory key is mandatory: the generator refuses the file rather
    than defaulting, and it validates project-contact-email as an email, so
    a .invalid placeholder is rejected.
    """
    missing = [k for k in ("project", "company_name", "org_unit",
                           "prepared_by", "prepared_for", "email")
               if not getattr(args, k, None)]
    if missing:
        sys.exit("need %s (see --help); these are mandatory to the generator"
                 % ", ".join("--" + m.replace("_", "-") for m in missing))
    #  The generator validates this with commons-validator, which checks the
    #  top-level domain against a real list.  The RFC-reserved test TLDs all
    #  fail, and the error it gives back ("was not a valid email") does not
    #  say why, so catch it here instead.
    RESERVED = ("invalid", "test", "example", "localhost", "local")
    addr = args.email.strip()
    dom = addr.split("@")[-1] if "@" in addr else ""
    tld = dom.rsplit(".", 1)[-1].lower() if "." in dom else ""
    if "@" not in addr or not tld:
        sys.exit("--email must be an address with a domain")
    if tld in RESERVED:
        sys.exit("--email %r will be rejected by the generator: it validates "
                 "the address with commons-validator, which checks the TLD, "
                 "and .%s is an RFC-reserved test TLD. Use a real domain "
                 "(example.com validates)." % (addr, tld))
    snapshot = args.snapshot
    lines = [
        "version:",
        "    schema-version: 7",
        "connection:",
        "    url: %s/" % HOST.rstrip("/"),
        "    username: %s" % os.environ.get("COV_USER", "admin"),
        "project: %s" % args.project,
        "title-page:",
        "    company-name: %s" % args.company_name,
        "    project-name: %s" % (args.project_name or args.project),
        "    project-version: %s" % args.project_version,
        "    organizational-unit-name: %s" % args.org_unit,
        "    organizational-unit-term: %s" % args.org_term,
        "    prepared-for: %s" % args.prepared_for,
        "    prepared-by: %s" % args.prepared_by,
        "    project-contact-email: %s" % args.email,
        "issue-cutoff-count: %d" % args.cutoff,
    ]
    if snapshot:
        lines.append("snapshot-id: %s" % snapshot)
    else:
        lines.append("# snapshot-id: unset -- the report follows each "
                     "stream's latest snapshot, so runs are not reproducible")
    if args.owasp or args.sans:
        lines.append("report-cwe-version:")
        if args.owasp:
            lines.append("    owasp: %s" % args.owasp)
        if args.sans:
            lines.append("    sans: %s" % args.sans)
    text = "\n".join(lines) + "\n"
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote %s" % args.out)
    print(text)
    if not snapshot:
        print("Consider --snapshot: without it this report is not "
              "reproducible.")
    return 0


def generator(args, extra):
    exe = os.path.join(args.reports_bin, "cov-generate-cvss-report")
    if os.name == "nt" and not os.path.exists(exe):
        exe += ".exe"
    pw = os.environ.get("COVERITY_PASSPHRASE_FILE")
    cmd = [exe, "--password", "file:" + pw, "--project", args.project]
    cmd += extra + [args.config]
    env = dict(os.environ)
    if args.issues_json:
        env["WRITE_ISSUES_JSON"] = args.issues_json
    print("+ %s" % " ".join(["cov-generate-cvss-report"] + cmd[1:]))
    r = subprocess.run(cmd, env=env)
    return r.returncode


def cmd_scores(args):
    """Step 2: the calculation phase."""
    rc = generator(args, ["--scores"])
    if rc != 0:
        return rc
    print("")
    print("Scores written.  Nothing distinguishes a judged zero from an "
          "unjudged one yet -- that is step 3.")
    return 0


def cmd_report(args):
    """Step 5: the PDF."""
    extra = ["--report"]
    if args.output:
        extra += ["--output", args.output]
    return generator(args, extra)


def provenance(args):
    """Say which pieces produced this verdict.  Three versions are in play
    and they need not agree: the Connect instance, the Coverity Analysis
    that wrote the snapshot, and the Coverity Reports doing the mapping."""
    ver = "unknown"
    vf = os.path.join(args.reports_dir, "VERSION")
    try:
        with open(vf, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("externalVersion="):
                    ver = line.split("=", 1)[1].strip()
                    break
    except OSError:
        pass
    print("  report generator : %s (%s)" % (ver, args.reports_dir))
    print("  Connect          : %s" % HOST)
    print("  snapshot         : %s of project %s"
          % (args.snapshot, args.project))
    print("  The analysis version that wrote this snapshot may differ from "
          "both, which")
    print("  is why the CWEs come from Connect and not from a local checker "
          "list.")


def cmd_status(args):
    rows = issues(args.project, args.snapshot)
    rows, _ = classify(rows, args)
    provenance(args)
    print("")
    print("%s at snapshot %s: %d issue(s)"
          % (args.project, args.snapshot, len(rows)))
    marked = sum(1 for r in rows if str(r.get("CVSS_Audited")) == "Yes")
    print("  CVSS_Audited=Yes in Connect right now: %d" % marked)
    print("")
    print("what the mapping in %s says:" % os.path.basename(args.reports_dir))
    summarise(rows)
    print("")
    print("Read this as: (a) and (b) were judged by the generator you are")
    print("running; (c) was not, and its zero is an artifact of that build's")
    print("mapping rather than a decision.  A later Coverity Reports release")
    print("may map some of (c) -- re-run this against it to find out.")
    return 0


def cmd_mark(args):
    """Step 3: record which scores a mapping actually judged."""
    rows = issues(args.project, args.snapshot)
    rows, _ = classify(rows, args)
    print("%s at snapshot %s: %d issue(s)"
          % (args.project, args.snapshot, len(rows)))
    print("")
    unaudited = summarise(rows)
    print("")
    to_yes = [r["cid"] for r in rows if r["_audited"]]
    if args.audited == "inferred-only":
        print("--audited inferred-only: marking nothing now, so a future "
              "Coverity Reports")
        print("release can still improve any of these mappings.  Only "
              "vectors this tool")
        print("writes in step 4 will be marked Yes.")
        to_yes = []
    store = args.triage_store or triage_store_for(args.project)
    if to_yes and not args.dry_run:
        n = set_attributes(store, to_yes, {"CVSS_Audited": "Yes"})
        print("marked CVSS_Audited=Yes on %d issue(s) in triage store %r"
              % (n, store))
        print("NOTE: in Reports 2025.3.0 the next --scores run resets these "
              "to No and")
        print("discards any vector written by hand -- run `selftest` to check "
              "your build.")
        print("Treat the CSV as the durable record, not the attribute.")
    elif to_yes:
        print("would mark CVSS_Audited=Yes on %d issue(s) (dry run)"
              % len(to_yes))

    print("")
    if not unaudited:
        print("Nothing left No: every score in this snapshot came from a "
              "mapping that")
        print("judged the CWE.  Go to step 5 and run the report.")
        return 0
    unmapped = [r for r in unaudited if r["_case"] == CASE_C]
    nocwe = [r for r in unaudited if r["_case"] == CASE_NOCWE]
    print("%d issue(s) are left No." % len(unaudited))
    if unmapped:
        print("")
        print("  %d have a CWE this Reports build has no judgement for, so "
              "the zero is" % len(unmapped))
        print("  an artifact of its mapping rather than a decision:")
        seen = {}
        for r in unmapped:
            key = (r.get("cwe"), r.get("checker"))
            seen[key] = seen.get(key, 0) + 1
        for (cwe, checker), n in sorted(seen.items(),
                                       key=lambda kv: -kv[1])[:25]:
            print("    CWE-%-6s %-34.34s %d" % (cwe, checker, n))
    if nocwe:
        print("")
        print("  %d carry no CWE from Connect at all, so no lookup ran and "
              "nothing could" % len(nocwe))
        print("  have judged them.  Parse warnings are the usual case.  This "
              "is not a")
        print("  mapping gap and there is nothing for a newer Reports build "
              "to fix:")
        seen = {}
        for r in nocwe:
            seen[r.get("checker")] = seen.get(r.get("checker"), 0) + 1
        for checker, n in sorted(seen.items(), key=lambda kv: -kv[1])[:10]:
            print("    %-41.41s %d" % (checker, n))
    print("")
    if unmapped:
        print("Step 4 is now a choice, and it is the user's:")
        print("  (a) run the report as it stands -- the zeros stay, and you "
              "can")
        print("      point at this list to say which ones nobody judged; or")
        print("  (b) `infer` a vector for them, which is this tool's guess "
              "and")
        print("      is labelled as such.  Review it before applying.")
    else:
        print("There is no step 4 to do here: nothing is left No for want of "
              "a mapping.")
        print("Go to step 5 and run the report, and say in the cover note "
              "that the")
        print("unscored issues are ones Coverity gave no CWE.")
    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as f:
            f.write("cid,checker,cwe,category,impact,class,score\n")
            for r in unaudited:
                f.write('%s,"%s",%s,"%s",%s,"%s",%s\n'
                        % (r["cid"], r.get("checker"), r.get("cwe") or "",
                           r.get("displayCategory"), r.get("displayImpact"),
                           r["_class"], r.get("CVSS_Score")))
        print("")
        print("wrote %s" % args.csv)
    return 0


def cmd_selftest(args):
    """Does THIS Reports build honour CVSS_Audited?  Measure, do not assume.

    The reports guide says setting CVSS_Audited to Yes stops the generator
    updating that defect's vector.  In Reports 2025.3.0 it does not: --scores
    rewrites all four CVSS_* attributes unconditionally, CVSS_Audited among
    them, so a Yes is reset to No and any vector written by hand is
    discarded.  That may be fixed in a later build, and the answer decides
    whether marking survives, so this runs the experiment:

        pick a defect, save its values, write a distinctive vector with
        CVSS_Audited=Yes, run --scores, read it back, restore.

    It runs --scores, which writes to every defect in the project.  Run it on
    a project you are allowed to score.
    """
    rows = issues(args.project, args.snapshot)
    zero = [r for r in rows if str(r.get("CVSS_Score")) in ("0.0", "0", "0.00")]
    pick = (zero or rows)[0]
    cid = pick["cid"]
    store = args.triage_store or triage_store_for(args.project)
    before = {"CVSS_Vector": pick.get("CVSS_Vector") or "",
              "CVSS_Score": pick.get("CVSS_Score") or "",
              "CVSS_Severity": pick.get("CVSS_Severity") or "None",
              "CVSS_Audited": pick.get("CVSS_Audited") or "No"}
    probe = "CVSS:3.0/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H"
    print("probing with CID %s in triage store %r" % (cid, store))
    print("  before : %s / %s / %s"
          % (before["CVSS_Score"], before["CVSS_Severity"],
             before["CVSS_Audited"]))
    set_attributes(store, [cid], {"CVSS_Vector": probe,
                                  "CVSS_Score": "9.89",
                                  "CVSS_Severity": "Critical",
                                  "CVSS_Audited": "Yes"})
    print("  wrote  : 9.89 / Critical / Yes")
    rc = generator(args, ["--scores"])
    if rc != 0:
        print("  --scores failed; restoring and giving up")
        set_attributes(store, [cid], before)
        return rc
    after = None
    for r in issues(args.project, args.snapshot):
        if r["cid"] == cid:
            after = r
            break
    held = (after and str(after.get("CVSS_Audited")) == "Yes"
            and str(after.get("CVSS_Score")) == "9.89")
    print("  after  : %s / %s / %s"
          % (after.get("CVSS_Score"), after.get("CVSS_Severity"),
             after.get("CVSS_Audited")))
    print("")
    if held:
        print("HONOURED: this build leaves an audited defect alone, so marks")
        print("and inferred vectors survive later --scores runs.")
    else:
        print("NOT HONOURED: --scores overwrote the audited defect, including")
        print("CVSS_Audited itself.  So in this build:")
        print("  * `mark` must be the step AFTER your final --scores run;")
        print("  * `infer --apply` likewise;")
        print("  * any later --scores silently discards both -- keep the CSVs.")
    set_attributes(store, [cid], before)
    print("")
    print("restored CID %s to its previous values" % cid)
    return 0


def cmd_reset(args):
    rows = issues(args.project, args.snapshot)
    cids = [r["cid"] for r in rows
            if str(r.get("CVSS_Audited")) == "Yes"]
    if not cids:
        print("nothing is marked Yes")
        return 0
    store = args.triage_store or triage_store_for(args.project)
    if args.dry_run:
        print("would set CVSS_Audited=No on %d issue(s)" % len(cids))
        return 0
    n = set_attributes(store, cids, {"CVSS_Audited": "No"})
    print("set CVSS_Audited=No on %d issue(s); the next --scores run will "
          "recompute their vectors" % n)
    return 0


# --------------------------------------------------------------------------
# step 4: inference
#
# Inference is a guess and the tool says so everywhere.  The rule is chosen
# to lean on Coverity's own judgements rather than on ours: score an
# unjudged defect like the JUDGED defects that Coverity files under the
# same category in this same snapshot.  That keeps the guess inside the
# vendor's own frame of reference, and where the snapshot gives no basis
# for one, the tool declines instead of inventing a number.


def infer_for(rows, unaudited):
    """Basis: EVERY judged defect in the category, zero-impact ones included.

    Leaving the zeros out was a real bug, caught by running this: in a MISRA
    snapshot 79 of the 95 judged defects were judged to have no impact, and
    excluding them made the most common *non-zero* triple look typical, so
    every unjudged coding-standard violation came out at 7.39 High.  A
    judgement of "no impact" is a judgement, and in that snapshot it is the
    overwhelming majority one.  Including it makes the inference say what the
    vendor's own mapping says about that category."""
    basis = {}
    for r in rows:
        if not r["_audited"]:
            continue
        pred = r.get("_predicted")
        if not pred:
            continue
        m = audit.parse_vector(pred["vector"])
        triple = (m["S"], m["C"], m["I"], m["A"])
        cat = r.get("displayCategory")
        basis.setdefault(cat, {})
        basis[cat][triple] = basis[cat].get(triple, 0) + 1

    out = []
    for r in unaudited:
        if r["_case"] == CASE_NOCWE:
            #  No CWE means no weakness classification to reason from.  The
            #  category alone is too thin a basis to put a number on, and a
            #  newer mapping will not change it either, so decline.
            out.append((r, None, "no CWE from Connect -- nothing to reason "
                                 "from but the category; declined"))
            continue
        cat = r.get("displayCategory")
        cands = basis.get(cat)
        if cands:
            # most common triple in this category; ties broken toward the
            # lower score, so inference does not inflate.
            best = sorted(cands.items(),
                          key=lambda kv: (-kv[1],
                                          audit.base_score(
                                              {"AV": "N", "AC": "L",
                                               "PR": "L", "UI": "N",
                                               "S": kv[0][0], "C": kv[0][1],
                                               "I": kv[0][2],
                                               "A": kv[0][3]})[0]))[0][0]
            out.append((r, best, "same category (%s) as %d judged issue(s)"
                        % (cat, sum(cands.values()))))
        else:
            out.append((r, None,
                        "no judged issue in category %r to reason from" % cat))
    return out


def cmd_infer(args):
    rows = issues(args.project, args.snapshot)
    rows, ctx = classify(rows, args)
    master, tax, user, graph = ctx
    unaudited = [r for r in rows if not r["_audited"]]
    if not unaudited:
        print("nothing to infer: every score was judged by a mapping")
        return 0
    if all(r["_case"] == CASE_NOCWE for r in unaudited):
        print("nothing to infer: the %d unjudged issue(s) carry no CWE from "
              "Connect," % len(unaudited))
        print("so there is no weakness classification to reason from.")
        return 0
    proposals = infer_for(rows, unaudited)
    g = (user or master).globals
    print("INFERRED vectors -- this tool's guess, not a Coverity mapping")
    print("Rule: score an unjudged defect like the judged defects Coverity "
          "files under")
    print("the same category in this snapshot.  Ties go to the lower score.")
    print("")
    applied = []
    declined = 0
    zeros = 0
    for r, triple, why in proposals:
        if triple is None:
            declined += 1
            continue
        vec = ("CVSS:3.0/AV:%s/AC:%s/PR:%s/UI:%s/S:%s/C:%s/I:%s/A:%s"
               % (g["AV"], g["AC"], g["PR"], g["UI"],
                  triple[0], triple[1], triple[2], triple[3]))
        raw, spec = audit.base_score(audit.full_metrics(g, {
            "S": triple[0], "C": triple[1], "I": triple[2], "A": triple[3]}))
        if raw == 0:
            zeros += 1
        applied.append((r, vec, raw, spec, why))
    for r, vec, raw, spec, why in applied[:40]:
        print("  CID %-7s CWE-%-6s %-22.22s %s  %.2f (%s)"
              % (r["cid"], r.get("cwe") or "-", r.get("checker"), vec, raw,
                 audit.severity_of(spec)))
        print("            because: %s" % why)
    if len(applied) > 40:
        print("  ... %d more" % (len(applied) - 40))
    print("")
    print("%d proposed, %d declined for want of a basis" % (len(applied),
                                                            declined))
    if zeros:
        print("%d of the proposals are themselves zero -- the judged defects "
              "in that" % zeros)
        print("category were judged to have no impact, so the inference says "
              "the same.")
        print("Applying those changes no score; it records that the zero is "
              "now a decision")
        print("by analogy rather than an absence of one.")
    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as f:
            f.write("cid,checker,cwe,inferred_vector,score,reason\n")
            for r, vec, raw, spec, why in applied:
                f.write('%s,"%s",%s,%s,%.2f,"%s"\n'
                        % (r["cid"], r.get("checker"), r.get("cwe") or "",
                           vec, raw, why))
        print("wrote %s" % args.csv)
    if not args.apply:
        print("")
        print("Nothing was written.  Re-run with --apply to write these "
              "vectors and mark")
        print("them CVSS_Audited=Yes so the next --scores run does not "
              "revert them.")
        return 0
    store = args.triage_store or triage_store_for(args.project)
    n = 0
    for r, vec, raw, spec, why in applied:
        n += set_attributes(store, [r["cid"]], {
            "CVSS_Vector": vec,
            "CVSS_Score": "%.2f" % raw,
            "CVSS_Severity": audit.severity_of(spec),
            "CVSS_Audited": "Yes",
        })
    print("")
    print("wrote inferred vectors on %d issue(s) and marked them Yes" % n)
    print("They are inference, not vendor mapping.  Keep the CSV with the "
          "report.")
    return 0


# --------------------------------------------------------------------------


def main():
    #  Common options live on a parent parser so they work either side of
    #  the subcommand -- an end user should not have to learn argparse's
    #  ordering rule to run this.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--reports-dir", default=None,
                        help="Coverity Reports install (for the mapping)")
    common.add_argument("--reports-bin", default=None,
                        help="its bin/ (defaults to <reports-dir>/bin)")
    common.add_argument("--project")
    common.add_argument("--snapshot")
    common.add_argument("--config", default="cvss_config.yaml")
    common.add_argument("--profile",
                        help="user <security-profile>.json, if any")
    common.add_argument("--graph",
                        help="graph from cvss_profile_audit.py graph")
    common.add_argument("--triage-store")
    common.add_argument("--issues-json",
                        help="set WRITE_ISSUES_JSON for the run")
    common.add_argument("--csv")
    common.add_argument("--dry-run", action="store_true")

    p = argparse.ArgumentParser(
        description=__doc__, parents=[common],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    c = sub.add_parser("config", help="step 1: write config.yaml",
                       parents=[common])
    c.add_argument("--out", default="cvss_config.yaml")
    c.add_argument("--company-name")
    c.add_argument("--project-name")
    c.add_argument("--project-version", default="1.0")
    c.add_argument("--org-unit")
    c.add_argument("--org-term", default="Team")
    c.add_argument("--prepared-by")
    c.add_argument("--prepared-for")
    c.add_argument("--email")
    c.add_argument("--cutoff", type=int, default=200)
    c.add_argument("--owasp", choices=["2017", "2021"])
    c.add_argument("--sans", choices=["2012", "2021", "2022", "2023"])
    c.set_defaults(func=cmd_config)

    for name, fn, helptext in (
            ("scores", cmd_scores, "step 2: run the calculation"),
            ("mark", cmd_mark, "step 3: record which zeros were judged"),
            ("infer", cmd_infer, "step 4: propose vectors for the rest"),
            ("report", cmd_report, "step 5: produce the PDF"),
            ("status", cmd_status, "where this project stands"),
            ("selftest", cmd_selftest,
             "does this Reports build honour CVSS_Audited? (runs --scores)"),
            ("reset", cmd_reset, "set CVSS_Audited back to No")):
        s = sub.add_parser(name, help=helptext, parents=[common])
        if name == "mark":
            s.add_argument("--audited", default="mapped",
                           choices=["mapped", "inferred-only"],
                           help="mapped (default): Yes wherever a mapping "
                                "judged the CWE. inferred-only: mark "
                                "nothing now, so future vendor mappings "
                                "stay live")
        if name == "infer":
            s.add_argument("--apply", action="store_true",
                           help="actually write the inferred vectors")
        if name == "report":
            s.add_argument("--output", help="output PDF path")
        s.set_defaults(func=fn)

    args = p.parse_args()
    if not getattr(args, "func", None):
        p.print_help()
        return 2
    args.reports_dir = audit.find_reports_dir(args.reports_dir)
    if args.cmd != "config" and not args.reports_dir:
        sys.exit("give --reports-dir: the Coverity Reports install")
    if not args.reports_bin and args.reports_dir:
        args.reports_bin = os.path.join(args.reports_dir, "bin")
    if args.cmd in ("scores", "mark", "infer", "report", "status", "reset"):
        if not args.project:
            sys.exit("--project is required")
        if args.cmd in ("mark", "infer", "status", "reset") \
                and not args.snapshot:
            sys.exit("--snapshot is required (the issues API returns nothing "
                     "for scope 'last')")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
