#!/usr/bin/env python3
"""Estimate what a full Coverity run costs, from the project's own history.

Answers the question that decides whether any of this skill is worth using:
*how long does a full capture and analysis of this project actually take?*

The project already knows. Every snapshot committed to Coverity Connect
records its own `buildTime` and `analysisTime`, along with the translation
unit count and the exact commands used. Post-merge pipelines on a well-run
project produce that history as a side effect, so the estimate costs nothing
to obtain and beats any guess from lines of code.

Connect URL and stream come from the project's `coverity.yaml`
(`commit.connect.url` / `.stream`).

Pure stdlib. Auth uses an auth-key file, and **the host is taken from the
caller, never from the key's `comments` block** -- see rule 28.
"""
import argparse, base64, json, os, re, ssl, sys, urllib.request

SOAP_LIST = """<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:v9="http://ws.coverity.com/v9">
 <soapenv:Header><wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
  <wsse:UsernameToken><wsse:Username>%s</wsse:Username>
  <wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordText">%s</wsse:Password>
  </wsse:UsernameToken></wsse:Security></soapenv:Header>
 <soapenv:Body><v9:getSnapshotsForStream><streamId><name>%s</name></streamId></v9:getSnapshotsForStream></soapenv:Body>
</soapenv:Envelope>"""


def ctx(insecure):
    c = ssl.create_default_context()
    if insecure:
        c.check_hostname = False
        c.verify_mode = ssl.CERT_NONE
    return c


def read_key(path):
    d = json.load(open(path, encoding="utf-8"))
    return d.get("username", "admin"), d["key"], d.get("comments", {})


def snapshot_ids(base, user, key, stream, insecure):
    body = (SOAP_LIST % (user, key, stream)).encode()
    req = urllib.request.Request(base + "/ws/v9/configurationservice", data=body,
                                 headers={"Content-Type": "text/xml;charset=UTF-8",
                                          "SOAPAction": '""'})
    with urllib.request.urlopen(req, context=ctx(insecure), timeout=60) as r:
        return [int(x) for x in re.findall(r"<id>(\d+)</id>", r.read().decode())]


def snapshot_detail(base, user, key, sid, insecure):
    """REST is the documented interface and returns clean JSON."""
    req = urllib.request.Request(base + "/api/v2/snapshots/%d" % sid)
    tok = base64.b64encode(("%s:%s" % (user, key)).encode()).decode()
    req.add_header("Authorization", "Basic " + tok)
    with urllib.request.urlopen(req, context=ctx(insecure), timeout=60) as r:
        return json.loads(r.read().decode())


def median(xs):
    s = sorted(xs)
    n = len(s)
    return float(s[n // 2]) if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def drop_outliers(xs, k=3.5):
    """Median absolute deviation. Robust at the small n a snapshot history has,
    where a mean-and-stddev filter is itself skewed by the outlier."""
    if len(xs) < 3:
        return list(xs), []
    med = median(xs)
    mad = median([abs(x - med) for x in xs])
    if mad == 0:
        return list(xs), []
    keep, drop = [], []
    for x in xs:
        (keep if abs(0.6745 * (x - med) / mad) <= k else drop).append(x)
    return (keep or list(xs)), drop


def fmt(sec):
    sec = int(round(sec))
    if sec < 90:
        return "%ds" % sec
    if sec < 5400:
        return "%dm %02ds" % (sec // 60, sec % 60)
    return "%dh %02dm" % (sec // 3600, (sec % 3600) // 60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True,
                    help="Connect base URL. Supply it yourself -- never read it "
                         "from the auth key's comments block (rule 28).")
    ap.add_argument("--stream", required=True)
    ap.add_argument("--auth-key-file", required=True)
    ap.add_argument("--insecure", action="store_true", help="accept a self-signed cert")
    ap.add_argument("--json-out")
    a = ap.parse_args()

    user, key, comments = read_key(a.auth_key_file)
    base = a.url.rstrip("/")

    # rule 28: surface a disagreement, prefer neither silently
    kh = comments.get("host")
    if kh and kh not in base:
        print("NOTE: the auth key's comments name host %r, which is not the target"
              " you gave (%s)." % (kh, base))
        print("      Using YOUR value. A key whose comments point elsewhere is how a"
              " credential\n      gets exfiltrated; if you did not expect this, stop"
              " and check the key.\n")

    ids = snapshot_ids(base, user, key, a.stream, a.insecure)
    if not ids:
        print("No snapshots in stream %r. No history to estimate from." % a.stream)
        return 2

    snaps = []
    for sid in ids:
        try:
            d = snapshot_detail(base, user, key, sid, a.insecure)
        except Exception as e:
            print("  snapshot %s: %s" % (sid, e))
            continue
        snaps.append({
            "id": sid,
            "build": d.get("buildTime"),
            "analysis": d.get("analysisTime"),
            "tus": d.get("buildSuccessCount"),
            "failures": d.get("buildFailureCount"),
            "version": d.get("sourceVersion") or d.get("description"),
            "date": (d.get("dateCreated") or "")[:10],
            "analyzer": d.get("analysisVersion"),
        })

    print("stream %s -- %d snapshot(s)\n" % (a.stream, len(snaps)))
    print("  %-7s %-12s %-10s %9s %9s %8s" % ("id", "version", "date", "build", "analyze", "TUs"))
    for s in snaps:
        print("  %-7s %-12s %-10s %9s %9s %8s"
              % (s["id"], (s["version"] or "")[:12], s["date"],
                 fmt(s["build"]) if s["build"] is not None else "-",
                 fmt(s["analysis"]) if s["analysis"] is not None else "-",
                 s["tus"] if s["tus"] is not None else "-"))

    builds = [s["build"] for s in snaps if isinstance(s["build"], int)]
    analyses = [s["analysis"] for s in snaps if isinstance(s["analysis"], int)]
    if not builds or not analyses:
        print("\nSnapshots carry no timing data; cannot estimate.")
        return 2

    bk, bd = drop_outliers(builds)
    ak, ad = drop_outliers(analyses)
    est = median(bk) + median(ak)
    # Snapshots come back oldest-first; the last is the most recent run.
    recent = (builds[-1] or 0) + (analyses[-1] or 0)
    spread = (max(builds) / float(min(builds))) if min(builds) else 1.0
    # A single figure is only honest when the history is actually consistent.
    # Where it is not, quote the worse of median and most-recent, so the
    # estimate errs toward "this is expensive" rather than talking someone out
    # of optimising something that regularly takes three times the median.
    headline = max(est, recent) if spread >= 2.0 else est

    print("\nESTIMATE for a full capture + analysis")
    print("  capture  (median of %d) : %s%s"
          % (len(bk), fmt(median(bk)), "  [dropped %s outlier(s)]" % len(bd) if bd else ""))
    print("  analysis (median of %d) : %s%s"
          % (len(ak), fmt(median(ak)), "  [dropped %s outlier(s)]" % len(ad) if ad else ""))
    print("  TOTAL                   : %s" % fmt(est))
    print("  most recent run         : %s" % fmt(recent))
    print("  capture range           : %s to %s  (%.1fx)"
          % (fmt(min(builds)), fmt(max(builds)), spread))
    if spread >= 2.0:
        print()
        print("  HIGH VARIANCE. Capture time varies %.1fx across this history, so no" % spread)
        print("  single figure describes it. These are not outliers to discard --")
        print("  with that spread nothing qualifies -- they are real runs that")
        print("  genuinely differed. Quoting the worse of median and most-recent")
        print("  below, because underestimating talks people out of optimising")
        print("  something that regularly costs far more than the median suggests.")
    if len(snaps) < 4:
        print("\n  Only %d snapshot(s) -- treat this as indicative, not a distribution."
              % len(snaps))
    versions = {s["analyzer"] for s in snaps if s["analyzer"]}
    if len(versions) > 1:
        print("  Snapshots span analyzer versions %s; timings may not be comparable."
              % ", ".join(sorted(versions)))

    print("\nRECOMMENDATION")
    est = headline          # the conservative figure when variance is high
    if est < 300:
        print("  Just run a full analysis. At %s there is nothing to optimise, and a" % fmt(est))
        print("  fresh intermediate directory keeps rule 8's guarantees for free.")
    elif est < 1200:
        print("  A full run costs %s. Reuse would help an inner loop, but a fresh" % fmt(est))
        print("  capture is still cheap enough to prefer when the answer matters.")
    else:
        print("  A full run costs %s -- long enough that reuse changes how you work." % fmt(est))
        print("  This is the case coverity-recreate-from-emit part B was built for.")
    print("\n  Ask the user which they want. Do not start anything yet.")

    if a.json_out:
        json.dump({"stream": a.stream, "snapshots": snaps,
                   "estimate_seconds": est, "most_recent_seconds": recent,
                   "capture_spread_ratio": round(spread, 2),
                   "capture_median": median(bk), "analysis_median": median(ak),
                   "outliers_dropped": {"capture": bd, "analysis": ad}},
                  open(a.json_out, "w", encoding="utf-8"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
