#!/usr/bin/env python3
"""Audit the CWE->CVSS mapping a Coverity CVSS report will use.

The CVSS Report Generator turns each defect's CWE into a CVSS vector by a
documented lookup (cov_reports_guide, "CVSS report profile"):

    1. the CWE itself in the user profile, else
    2. the ancestor of it with the highest CVSS score in the user profile, else
    3. the CWE itself in the master profile, else
    4. the ancestor of it with the highest CVSS score in the master profile, else
    5. a vector whose score is zero.

Every defect therefore gets a vector; the question is whether it gets a
*meaningful* one.  This tool runs that lookup offline, for every CWE the
installed generator knows a Coverity checker for (or for the CWEs actually
observed in a run, with --issues), and classifies each zero result by cause.

A zero is not automatically a bug.  Quality CWEs are mapped to C:N/I:N/A:N
deliberately -- a dead-code finding is not a vulnerability, and scoring it as
one would be the real error.  The distinction this tool draws is between

    ZERO-BY-DESIGN   the CWE is in a profile, with no impact.  Intended.
    ZERO-BY-DEFAULT  no profile entry, and no mapped ancestor either, so the
                     lookup fell off the end.  Nobody decided this.

and the second class is the one worth escalating, because it is silent: the
report shows a vector and a score for it like any other row.

    graph       dump the generator's real ancestor graph (needs a JDK)
    audit       classify every CWE; print the gap report
    checkers    which of Coverity's findings can be scored at all, by
                Quality/Security -- the denominator-safe view, and the one
                to answer "can we trust this report" with
    resolve     explain the lookup for particular CWEs, step by step
    verify      check a finished run's own scores against the specification
    score       compute the CVSS base score of a vector (spec vs. reported)

Run `graph` first and pass its output to `audit --graph`.  Without it the
ancestor walk is approximated from the checker taxonomy, which over-counts
ancestors and so under-reports the gap.

Pure standard library.  Reads the installed generator; changes nothing.
"""

import argparse
import glob
import json
import math
import os
import re
import subprocess
import sys
import zipfile

# --------------------------------------------------------------------------
# CVSS v3.x base score
#
# The generator emits CVSS:3.0 vectors.  The equations below are from the
# v3.1 specification section 7.1; v3.0 and v3.1 differ only in the rounding
# function, which is exactly what this tool is here to make visible.

_AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.20}
_AC = {"L": 0.77, "H": 0.44}
_PR_U = {"N": 0.85, "L": 0.62, "H": 0.27}
_PR_C = {"N": 0.85, "L": 0.68, "H": 0.50}
_UI = {"N": 0.85, "R": 0.62}
_CIA = {"H": 0.56, "L": 0.22, "N": 0.00}


def roundup(x):
    """CVSS v3.1 Appendix A roundup: smallest 1-decimal value >= x."""
    i = int(round(x * 100000))
    if i % 10000 == 0:
        return i / 100000.0
    return (math.floor(i / 10000) + 1) / 10.0


def base_score(m):
    """Raw (unrounded) and spec-rounded base score for a metric dict.

    m needs AV, AC, PR, UI, S, C, I, A.  Returns (raw, rounded).
    """
    scope_changed = m["S"] == "C"
    iss = 1 - ((1 - _CIA[m["C"]]) * (1 - _CIA[m["I"]]) * (1 - _CIA[m["A"]]))
    if scope_changed:
        impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15
    else:
        impact = 6.42 * iss
    expl = (8.22 * _AV[m["AV"]] * _AC[m["AC"]]
            * (_PR_C if scope_changed else _PR_U)[m["PR"]] * _UI[m["UI"]])
    if impact <= 0:
        return 0.0, 0.0
    if scope_changed:
        raw = min(1.08 * (impact + expl), 10.0)
    else:
        raw = min(impact + expl, 10.0)
    return raw, roundup(raw)


def parse_vector(v):
    """CVSS:3.0/AV:N/... -> metric dict."""
    m = {}
    for part in v.split("/"):
        if ":" not in part:
            continue
        k, _, val = part.partition(":")
        if k.startswith("CVSS"):
            continue
        m[k] = val
    return m


def vector_of(profile_globals, metrics):
    """Assemble the vector string the generator would write."""
    return "CVSS:3.0/AV:%s/AC:%s/PR:%s/UI:%s/S:%s/C:%s/I:%s/A:%s" % (
        profile_globals["AV"], profile_globals["AC"], profile_globals["PR"],
        profile_globals["UI"], metrics["S"], metrics["C"], metrics["I"],
        metrics["A"])


def full_metrics(profile_globals, metrics):
    d = dict(metrics)
    for k in ("AV", "AC", "PR", "UI"):
        d[k] = profile_globals[k]
    return d


def severity_of(score):
    """CVSS v3.x qualitative rating, the values CVSS_Severity takes."""
    if score == 0:
        return "None"
    if score < 4.0:
        return "Low"
    if score < 7.0:
        return "Medium"
    if score < 9.0:
        return "High"
    return "Critical"


# --------------------------------------------------------------------------
# the installed generator


class Profile(object):
    """A CVSS profile: the four CWE-independent metrics and the cweMap."""

    def __init__(self, path):
        self.path = path
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
        # The guide says comments are allowed in a user profile.
        text = re.sub(r"(?m)^\s*//.*$", "", text)
        d = json.loads(text)
        self.version = d.get("version")
        self.type = d.get("type")
        self.globals = {}
        for k in ("AV", "AC", "PR", "UI"):
            if k in d:
                self.globals[k] = d[k]
        self.cwe_map = {}
        for e in d.get("cweMap", []):
            self.cwe_map[str(e["cwe"])] = e["cvssMetrics"]

    def score_for(self, cwe):
        """Score of this profile's own entry for cwe, or None."""
        m = self.cwe_map.get(str(cwe))
        if m is None:
            return None
        return base_score(full_metrics(self.globals, m))[0]


class Taxonomy(object):
    """The checker-to-CWE mapping shipped inside the generator.

    This answers "which CWEs can a Coverity defect carry", which is the
    population the audit runs over.  Its `child-taxa` links are NOT the
    ancestor graph: they include category membership, and the generator's
    findAncestors() follows `ChildOf` edges only, over a different, older
    dataset.  Pass a graph from `cvss_profile_audit.py graph` to resolve
    against the real edges; without one this class's links are used as an
    approximation, and the audit says so.
    """

    def __init__(self, jar_path):
        self.jar_path = jar_path
        with zipfile.ZipFile(jar_path) as z:
            d = json.loads(z.read("unresolved/cwe.json"))
        self.version = d.get("extra", {}).get("version")
        self.date = d.get("extra", {}).get("date-generated")
        self.taxa = {}
        for t in d["taxa"]:
            self.taxa[t["id"]] = t
        self.parents = {}
        for t in d["taxa"]:
            for c in t.get("child-taxa", []):
                self.parents.setdefault(c, []).append(t["id"])

    def knows(self, cwe):
        return str(cwe) in self.taxa

    def name(self, cwe):
        t = self.taxa.get(str(cwe))
        if not t:
            return "(not in this taxonomy)"
        return t.get("name", {}).get("en", "")

    def kind(self, cwe):
        t = self.taxa.get(str(cwe))
        return t.get("extra", {}).get("kind", "") if t else ""

    def checkers(self, cwe):
        t = self.taxa.get(str(cwe))
        return t.get("issue-types", []) if t else []

    def ancestors(self, cwe):
        """All ancestors, breadth-first.  Cycles and diamonds are real here."""
        out = []
        seen = set([str(cwe)])
        queue = [str(cwe)]
        while queue:
            node = queue.pop(0)
            for p in self.parents.get(node, []):
                if p in seen:
                    continue
                seen.add(p)
                out.append(p)
                queue.append(p)
        return out

    def cwes_with_checkers(self):
        ids = [t["id"] for t in self.taxa.values()
               if t.get("issue-types") and t["id"].isdigit()]
        return sorted(ids, key=int)


class ChildOfGraph(object):
    """The real ancestor graph, as dumped by CweGraphDump.

    Keys are the CWEs that have a node at all.  A CWE absent from it has no
    ancestors in the generator's eyes, so its lookup ends at the hardcoded
    zero vector no matter what any profile contains.
    """

    approximate = False

    def __init__(self, path):
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        self.parents = {}
        for k, v in raw.items():
            self.parents[str(k)] = [str(x) for x in v]

    def knows(self, cwe):
        return str(cwe) in self.parents

    def ancestors(self, cwe):
        out = []
        seen = set([str(cwe)])
        queue = [str(cwe)]
        while queue:
            for p in self.parents.get(queue.pop(0), []):
                if p in seen:
                    continue
                seen.add(p)
                out.append(p)
                queue.append(p)
        return out


class ApproximateGraph(object):
    """Fallback: the taxonomy jar's links, which over-count ancestors."""

    approximate = True

    def __init__(self, tax):
        self.tax = tax

    def knows(self, cwe):
        return self.tax.knows(cwe)

    def ancestors(self, cwe):
        return self.tax.ancestors(cwe)


def find_jdk(explicit):
    """A JDK with javac.  The Coverity Analysis install ships one."""
    if explicit:
        return explicit
    for pat in (r"C:\Coverity\cov-analysis-win64-*\jdk*",
                r"C:\Coverity\cov-analysis-*\jdk*",
                "/opt/coverity/analysis/jdk*"):
        for d in sorted(glob.glob(pat), reverse=True):
            javac = os.path.join(d, "bin", "javac.exe")
            if not os.path.exists(javac):
                javac = os.path.join(d, "bin", "javac")
            if os.path.exists(javac):
                return d
    return None


def find_reports_dir(explicit):
    if explicit:
        return explicit
    candidates = [r"C:\Program Files\Coverity\Coverity Reports",
                  "/opt/coverity/reports"]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return None


def load_install(reports_dir):
    """(master Profile, Taxonomy) for an installed report generator."""
    cfg = os.path.join(reports_dir, "config")
    masters = [p for p in glob.glob(os.path.join(cfg, "*.json"))
               if "CWE_CVSS" in os.path.basename(p)]
    if not masters:
        sys.exit("no master CWE/CVSS profile in %s" % cfg)
    jars = glob.glob(os.path.join(reports_dir, "lib",
                                  "issue-type-taxonomies-*.jar"))
    if not jars:
        sys.exit("no issue-type-taxonomies jar in %s/lib" % reports_dir)
    return Profile(masters[0]), Taxonomy(jars[0])


# --------------------------------------------------------------------------
# the documented lookup

ZERO_VECTOR = "CVSS:3.0/AV:N/AC:L/PR:L/UI:N/S:U/C:N/I:N/A:N"

ORPHAN = "ZERO-BY-DEFAULT (no entry, no mapped ancestor)"
UNKNOWN = "ZERO-BY-DEFAULT (CWE has no node in the ancestor graph)"
INHERIT_ZERO = "ZERO-BY-DEFAULT (inherited from a zero-impact ancestor)"
DESIGN = "ZERO-BY-DESIGN (mapped, no impact)"
SCORED_DIRECT = "scored (own entry)"
SCORED_INHERIT = "scored (inherited)"

CLASS_ORDER = [SCORED_DIRECT, SCORED_INHERIT, DESIGN, INHERIT_ZERO, ORPHAN,
               UNKNOWN]


def resolve(cwe, master, user, tax, graph=None):
    """Run the five-step lookup.  Returns a dict describing the outcome."""
    cwe = str(cwe)
    if graph is None:
        graph = ApproximateGraph(tax)
    steps = []
    chosen = None
    for label, prof in (("user profile", user), ("master profile", master)):
        if prof is None:
            continue
        if cwe in prof.cwe_map:
            steps.append("%s: direct entry for CWE-%s" % (label, cwe))
            chosen = (prof, cwe, "direct")
            break
        cands = []
        for a in graph.ancestors(cwe):
            if a in prof.cwe_map:
                cands.append((prof.score_for(a), a))
        steps.append("%s: no entry for CWE-%s; %d mapped ancestor(s)"
                     % (label, cwe, len(cands)))
        if cands:
            best = max(cands, key=lambda t: (t[0], -int(t[1])))
            steps.append("%s: highest-scoring ancestor is CWE-%s (%.2f)"
                         % (label, best[1], best[0]))
            chosen = (prof, best[1], "ancestor")
            break

    if chosen is None:
        metrics = {"S": "U", "C": "N", "I": "N", "A": "N"}
        cls = ORPHAN if graph.knows(cwe) else UNKNOWN
        via = None
        prof = user or master
    else:
        prof, via, how = chosen
        metrics = prof.cwe_map[via]
        raw = base_score(full_metrics(prof.globals, metrics))[0]
        if raw > 0:
            cls = SCORED_DIRECT if how == "direct" else SCORED_INHERIT
        else:
            cls = DESIGN if how == "direct" else INHERIT_ZERO
        via = None if how == "direct" else via

    g = (user or master).globals
    m = full_metrics(g, metrics)
    raw, rounded = base_score(m)
    # When the lookup finds nothing the generator writes a hardcoded string,
    # NOT a vector assembled from the profile's own AV/AC/PR/UI.  A profile
    # that sets, say, AV:L still gets AV:N on these rows.
    vector = ZERO_VECTOR if chosen is None else vector_of(g, metrics)
    return {"cwe": cwe,
            "name": tax.name(cwe),
            "kind": tax.kind(cwe),
            "checkers": tax.checkers(cwe),
            "class": cls,
            "via": via,
            "vector": vector,
            "raw": raw,
            "rounded": rounded,
            "severity": severity_of(rounded),
            "steps": steps}


# --------------------------------------------------------------------------
# inputs describing a real run


def load_issue_dump(path):
    """Read an issue export.  Returns (kind, docs).

    Two different files turn up here and they carry different things:

    REST export -- rows from Connect's /api/v2/issues/search with the `cwe`
    column.  Has the CWE per defect, which is what an audit needs.

    WRITE_ISSUES_JSON -- what the generator itself dumps.  Carries
    `cvssVector`, `cvssScore` and `cvssSeverity` per defect, but NOT the
    CWE: `optCweId` serializes as {"empty": false, "present": true}, the
    Optional's bean properties with the value dropped.  So it can verify
    what the generator computed and cannot tell you which CWE produced it.
    """
    with open(path, "r", encoding="utf-8-sig") as f:
        doc = json.load(f)
    if isinstance(doc, dict) and "defectInfoList" in doc:
        return "generator", doc["defectInfoList"]
    if isinstance(doc, dict):
        for k in ("rows", "issues", "defects"):
            if isinstance(doc.get(k), list):
                return "rest", doc[k]
    if isinstance(doc, list):
        return "rest", doc
    sys.exit("%s is neither a REST issue export nor a WRITE_ISSUES_JSON dump"
             % path)


def cwes_from_issues(path):
    """CWEs observed in a run, counted, from a REST issue export.

    Needs the `cwe` column: request it from /api/v2/issues/search.  The
    generator's own WRITE_ISSUES_JSON cannot serve this -- see
    load_issue_dump -- and is rejected with that explanation rather than
    silently returning nothing.
    """
    kind, rows = load_issue_dump(path)
    if kind == "generator":
        sys.exit("%s is the generator's WRITE_ISSUES_JSON dump, which drops "
                 "the CWE value (optCweId serializes without it). Use a REST "
                 "export including the `cwe` column for --issues, and this "
                 "file with `verify`." % path)
    found = {}

    def note(value):
        s = str(value).upper().replace("CWE-", "").strip()
        if s.isdigit() and s != "0":
            found[s] = found.get(s, 0) + 1

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k.lower().replace("_", "") in ("cwe", "cwevalue", "cweid"):
                    if v not in (None, "", 0, "0"):
                        note(v)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    # A REST row may be a list of {"key": ..., "value": ...} cells.
    for row in rows:
        if isinstance(row, list):
            for cell in row:
                if isinstance(cell, dict) and cell.get("key") == "cwe":
                    if cell.get("value") not in (None, "", 0, "0"):
                        note(cell["value"])
        else:
            walk(row)
    if not found:
        sys.exit("no CWE values found in %s -- request the `cwe` column"
                 % path)
    return found


def build_graph(args, tax):
    if getattr(args, "graph", None):
        return ChildOfGraph(args.graph)
    return ApproximateGraph(tax)


def cmd_graph(args):
    """Compile and run CweGraphDump against the installed generator."""
    jdk = find_jdk(args.jdk)
    if not jdk:
        sys.exit("no JDK found; pass --jdk <dir> (a Coverity Analysis "
                 "install ships one under jdk*/)")
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "CweGraphDump.java")
    if not os.path.exists(src):
        sys.exit("CweGraphDump.java is missing from %s" % os.path.dirname(src))
    cp = os.path.join(args.reports_dir, "lib", "*")
    out = args.out or "cwe_childof.json"
    tmp = os.path.join(os.path.dirname(os.path.abspath(out)) or ".",
                       "_cwegraph_classes")
    javac = os.path.join(jdk, "bin", "javac")
    java = os.path.join(jdk, "bin", "java")
    sep = ";" if os.name == "nt" else ":"
    r = subprocess.run([javac, "-nowarn", "-proc:none", "-cp", cp,
                        "-d", tmp, src],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        sys.exit("javac failed: " + r.stdout.decode("utf-8", "replace"))
    # OWASP/SANS are read with System.getProperty and dereferenced without a
    # null check, so the dump throws NPE unless both are set.  The values do
    # not affect the ChildOf edges.
    r = subprocess.run([java, "-DOWASP=2017", "-DSANS=2019",
                        "-DlogLevel=ERROR",
                        "-cp", tmp + sep + cp, "CweGraphDump"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    body = None
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith("{"):
            body = line
    if body is None:
        sys.exit("CweGraphDump produced no graph: "
                 + r.stderr.decode("utf-8", "replace")[-2000:])
    with open(out, "w", encoding="utf-8") as f:
        f.write(body)
    g = ChildOfGraph(out)
    roots = sum(1 for v in g.parents.values() if not v)
    print("wrote %s" % out)
    print("  %d CWE nodes, %d of them with no ChildOf parent"
          % (len(g.parents), roots))
    print("  a CWE absent from this file has no ancestors in the generator's")
    print("  eyes, and so can only ever receive the hardcoded zero vector.")
    return 0


def cmd_audit(args):
    master, tax = load_install(args.reports_dir)
    user = Profile(args.profile) if args.profile else None
    graph = build_graph(args, tax)

    if args.issues:
        observed = cwes_from_issues(args.issues)
        population = sorted(observed, key=int)
        origin = "%d CWE(s) observed in %s" % (len(population), args.issues)
    else:
        observed = {}
        population = tax.cwes_with_checkers()
        origin = ("%d CWE(s) with a Coverity checker in the generator's own "
                  "taxonomy" % len(population))

    rows = [resolve(c, master, user, tax, graph) for c in population]

    print("CVSS mapping audit")
    print("  generator    : %s" % args.reports_dir)
    print("  master       : %s (%d CWE entries, version %s, type %r)"
          % (os.path.basename(master.path), len(master.cwe_map),
             master.version, master.type))
    if user:
        print("  user profile : %s (%d CWE entries)"
              % (user.path, len(user.cwe_map)))
    print("  taxonomy     : %s" % os.path.basename(tax.jar_path))
    print("                 CWE version %s, generated %s"
          % (tax.version, tax.date))
    if graph.approximate:
        print("  ancestors    : APPROXIMATED from the taxonomy's parent links.")
        print("                 Run `graph` and pass --graph for the real")
        print("                 ChildOf edges; this run UNDER-reports the gap.")
    else:
        print("  ancestors    : %s (%d nodes, ChildOf edges as the generator "
              "walks them)" % (args.graph, len(graph.parents)))
    print("  population   : %s" % origin)
    g = (user or master).globals
    print("  CWE-independent metrics: AV:%s/AC:%s/PR:%s/UI:%s"
          % (g["AV"], g["AC"], g["PR"], g["UI"]))
    print("")

    buckets = {}
    for k in CLASS_ORDER:
        buckets[k] = []
    for r in rows:
        buckets[r["class"]].append(r)

    print("summary")
    for k in CLASS_ORDER:
        print("  %-5d %s" % (len(buckets[k]), k))
    print("")

    gaps = buckets[ORPHAN] + buckets[UNKNOWN] + buckets[INHERIT_ZERO]
    if not gaps:
        print("No gap: every CWE in the population either scores, or is "
              "mapped to zero impact deliberately.")
    else:
        print("GAP: %d CWE(s) score zero without a profile entry saying they "
              "should." % len(gaps))
        print("Each appears in the report with a vector and a score like any "
              "other row.")
        print("")
        for r in sorted(gaps, key=lambda r: (r["class"], int(r["cwe"]))):
            print("  CWE-%-5s %-50.50s %s"
                  % (r["cwe"], r["name"], r["class"]))
            if observed:
                print("            %d issue(s) in this run"
                      % observed[r["cwe"]])
            elif r["checkers"]:
                print("            %d checker(s), e.g. %s"
                      % (len(r["checkers"]),
                         ", ".join(sorted(r["checkers"])[:4])))

    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as f:
            f.write("cwe,name,class,inherited_from,vector,raw_score,"
                    "spec_score,severity,checkers,issues_in_run\n")
            for r in sorted(rows, key=lambda r: int(r["cwe"])):
                f.write('%s,"%s","%s",%s,%s,%.2f,%.1f,%s,%d,%s\n'
                        % (r["cwe"], r["name"].replace('"', "'"), r["class"],
                           r["via"] or "", r["vector"], r["raw"], r["rounded"],
                           r["severity"], len(r["checkers"]),
                           observed.get(r["cwe"], "")))
        print("")
        print("wrote %s" % args.csv)
    return 0


def cmd_resolve(args):
    master, tax = load_install(args.reports_dir)
    user = Profile(args.profile) if args.profile else None
    graph = build_graph(args, tax)
    for cwe in args.cwe:
        cwe = str(cwe).upper().replace("CWE-", "")
        r = resolve(cwe, master, user, tax, graph)
        print("CWE-%s  %s" % (r["cwe"], r["name"]))
        print("  kind in taxonomy : %s" % (r["kind"] or "ABSENT"))
        for s in r["steps"]:
            print("  %s" % s)
        if r["via"]:
            print("  inherited from CWE-%s" % r["via"])
        print("  class  : %s" % r["class"])
        print("  vector : %s" % r["vector"])
        print("  score  : %.2f unrounded, %.1f per the CVSS v3.x roundup, "
              "severity %s" % (r["raw"], r["rounded"], r["severity"]))
        if r["checkers"]:
            print("  checkers (%d): %s"
                  % (len(r["checkers"]), ", ".join(sorted(r["checkers"])[:8])))
        print("")
    return 0


def cmd_score(args):
    for v in args.vector:
        m = parse_vector(v)
        raw, rounded = base_score(m)
        print("%s" % v)
        print("  unrounded          : %.4f" % raw)
        print("  CVSS v3.x roundup  : %.1f  (%s)"
              % (rounded, severity_of(rounded)))
        print("  truncated to 2 dp  : %.2f" % (math.floor(raw * 100) / 100.0))
    return 0


def cmd_checkers(args):
    """Which of Coverity's own findings can be scored at all.

    `audit` counts CWEs, and a CWE is only a problem if Coverity can
    actually put it on a defect.  It cannot always: an issue type is
    associated with several CWEs in the taxonomy but a defect carries
    exactly one, so an unmapped CWE may simply never be assigned.  Counting
    those inflates the gap.

    This asks the question the other way round, per issue type, so the
    answer does not depend on knowing which CWE Connect picks:

        if EVERY CWE associated with an issue type resolves to zero, that
        issue type cannot score, whichever one it gets.

    and splits the result by Coverity's own Quality/Security
    classification, because a quality finding scoring zero is the intended
    behaviour and a security finding scoring zero is not.
    """
    master, tax = load_install(args.reports_dir)
    user = Profile(args.profile) if args.profile else None
    graph = build_graph(args, tax)

    with zipfile.ZipFile(tax.jar_path) as z:
        kinds = json.loads(z.read("unresolved/issue-kind.json"))
    kind_of = {}
    for t in kinds["taxa"]:
        for it in t.get("issue-types", []):
            kind_of[it] = t["id"]

    it2cwe = {}
    for t in tax.taxa.values():
        if not t["id"].isdigit():
            continue
        for it in t.get("issue-types", []):
            it2cwe.setdefault(it, []).append(t["id"])

    cls = {}
    for c in set(c for v in it2cwe.values() for c in v):
        cls[c] = resolve(c, master, user, tax, graph)["class"]
    zero_default = set([ORPHAN, UNKNOWN, INHERIT_ZERO])
    zero_any = zero_default | set([DESIGN])

    counts = {}
    unscorable = {}
    for it, cwes in it2cwe.items():
        kind = kind_of.get(it, "unclassified")
        seen = set(cls[c] for c in cwes)
        if seen <= zero_default:
            verdict = "cannot score, nobody decided that"
            unscorable.setdefault(kind, []).append((it, cwes))
        elif seen <= zero_any:
            verdict = "cannot score, at least one decided zero"
        else:
            verdict = "can score"
        counts[(kind, verdict)] = counts.get((kind, verdict), 0) + 1

    print("Scoreability by issue type")
    print("  generator : %s" % args.reports_dir)
    if graph.approximate:
        print("  ancestors : APPROXIMATED -- pass --graph for the real edges")
    print("  %d issue type(s) carry a CWE in the taxonomy" % len(it2cwe))
    print("")
    for kind in ("security", "quality", "license", "unclassified"):
        rows = [(v, n) for (k, v), n in counts.items() if k == kind]
        if not rows:
            continue
        print("  %s" % kind)
        for v, n in sorted(rows, key=lambda r: -r[1]):
            print("    %-42s %d" % (v, n))
    print("")

    sec = unscorable.get("security", [])
    if not sec:
        print("No security issue type is unscoreable by accident.")
        return 0
    print("SECURITY issue types that cannot score, with nobody having "
          "decided so: %d" % len(sec))
    print("These are the ones to escalate: Coverity calls them security "
          "findings, and")
    print("the report prices them at 0.0 whatever CWE they are given.")
    print("")
    by_cwe = {}
    for it, cwes in sec:
        by_cwe.setdefault(tuple(sorted(cwes, key=int)), []).append(it)
    for cwes, its in sorted(by_cwe.items(), key=lambda kv: -len(kv[1])):
        label = ",".join("CWE-" + c for c in cwes)
        fams = {}
        for i in its:
            f = i.split(":")[0].split("|")[0]
            fams[f] = fams.get(f, 0) + 1
        top = ", ".join("%s(%d)" % (f, n) for f, n in
                        sorted(fams.items(), key=lambda kv: -kv[1])[:3])
        print("  %-22s %5d issue type(s)  %s" % (label, len(its), top))
    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as f:
            f.write("kind,issue_type,cwes,verdict\n")
            for kind, rows in unscorable.items():
                for it, cwes in sorted(rows):
                    f.write('%s,"%s","%s",cannot score - nobody decided\n'
                            % (kind, it, " ".join(cwes)))
        print("")
        print("wrote %s" % args.csv)
    return 0


def cmd_verify(args):
    """Check what a run actually wrote, from its WRITE_ISSUES_JSON dump.

    Recomputes the base score from each defect's own vector and compares it
    with the score the generator recorded.  This is how the rounding
    behaviour shows up on your own data rather than on a claim in a
    document.
    """
    kind, rows = load_issue_dump(args.issues)
    if kind != "generator":
        sys.exit("verify wants the generator's WRITE_ISSUES_JSON dump; %s "
                 "looks like a REST export (use it with `audit --issues`)"
                 % args.issues)
    n = 0
    zero = 0
    audited = 0
    mismatch_spec = []
    mismatch_2dp = []
    band = []
    for d in rows:
        vec = d.get("cvssVector")
        if not vec:
            continue
        n += 1
        if str(d.get("cvssAudited", "")).lower() == "yes":
            audited += 1
        reported = d.get("cvssScore")
        m = parse_vector(vec)
        try:
            raw, spec = base_score(m)
        except KeyError:
            print("unparsable vector on %s: %s" % (d.get("optCid"), vec))
            continue
        if raw == 0:
            zero += 1
        two = math.floor(raw * 100 + 0.5) / 100.0
        if reported is not None:
            if abs(float(reported) - spec) > 0.001:
                mismatch_spec.append((d, vec, reported, raw, spec))
            if abs(float(reported) - two) > 0.001:
                mismatch_2dp.append((d, vec, reported, raw, two))
            if severity_of(float(reported)) != severity_of(spec):
                band.append((d, vec, reported, spec))
    print("verify %s" % args.issues)
    print("  %d defect(s) with a vector; %d scored zero; %d frozen with "
          "CVSS_Audited=Yes" % (n, zero, audited))
    print("  %d disagree with the CVSS v3 specified roundup" % len(mismatch_spec))
    print("  %d disagree with half-up-to-2-decimals" % len(mismatch_2dp))
    print("  %d land in a different severity band than the spec gives"
          % len(band))
    if mismatch_spec and not mismatch_2dp:
        print()
        print("  Every reported score matches half-up-to-2-decimals and none")
        print("  matches the specified roundup: this build rounds the way")
        print("  CVSSBaseScoreCalculator does, not the way CVSS v3 says.")
        d, vec, reported, raw, spec = mismatch_spec[0]
        print("  e.g. %s -> reported %s, unrounded %.4f, spec %.1f"
              % (vec, reported, raw, spec))
    if band:
        print()
        print("  These change severity, which is the case that matters:")
        for d, vec, reported, spec in band[:10]:
            print("    %s reported %s (%s) vs spec %.1f (%s)"
                  % (vec, reported, severity_of(float(reported)), spec,
                     severity_of(spec)))
    return 0


def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--reports-dir", default=None,
                   help="Coverity Reports install directory")
    sub = p.add_subparsers(dest="cmd")

    g = sub.add_parser("graph", help="dump the real ancestor graph (needs a JDK)")
    g.add_argument("--jdk", help="JDK directory; autodetected from a Coverity "
                                 "Analysis install if omitted")
    g.add_argument("--out", help="output path (default cwe_childof.json)")
    g.set_defaults(func=cmd_graph)

    a = sub.add_parser("audit", help="classify every CWE; print the gap report")
    a.add_argument("--graph", help="graph from the `graph` subcommand")
    a.add_argument("--profile", help="user <security-profile>.json, if any")
    a.add_argument("--issues",
                   help="WRITE_ISSUES_JSON output from a real run; restricts "
                        "the audit to the CWEs seen in it")
    a.add_argument("--csv", help="write the full per-CWE table here")
    a.set_defaults(func=cmd_audit)

    r = sub.add_parser("resolve", help="explain the lookup for particular CWEs")
    r.add_argument("cwe", nargs="+")
    r.add_argument("--profile")
    r.add_argument("--graph", help="graph from the `graph` subcommand")
    r.set_defaults(func=cmd_resolve)

    c = sub.add_parser("checkers", help="which of Coverity's own findings "
                                        "can be scored at all")
    c.add_argument("--profile", help="user <security-profile>.json, if any")
    c.add_argument("--graph", help="graph from the `graph` subcommand")
    c.add_argument("--csv", help="write the unscoreable issue types here")
    c.set_defaults(func=cmd_checkers)

    v = sub.add_parser("verify", help="check a run's own scores against the "
                                      "CVSS specification")
    v.add_argument("issues", help="WRITE_ISSUES_JSON from the run")
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("score", help="score a CVSS vector")
    s.add_argument("vector", nargs="+")
    s.set_defaults(func=cmd_score)

    args = p.parse_args()
    if not getattr(args, "func", None):
        p.print_help()
        return 2
    if args.cmd not in ("score", "verify"):
        args.reports_dir = find_reports_dir(args.reports_dir)
        if not args.reports_dir or not os.path.isdir(args.reports_dir):
            sys.exit("give --reports-dir: the Coverity Reports install")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
