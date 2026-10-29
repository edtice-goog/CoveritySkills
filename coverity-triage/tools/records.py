#!/usr/bin/env python3
"""Step 4: assemble and validate triage records (references/records.md).

  records.py assemble --bundles <dir> --lanes lanes.json --verdicts <dir> \
                      --run run.json --out <dir>/triage.json [--report <md>]
  records.py check-lanes --bundles <dir> --lanes lanes.json [--run run.json]
  records.py validate <triage.json>

assemble joins index.json (tools/bundle.py), the lane assignment
(tools/lanes.py, then inference for the findings it left pending) and the
verdict files by merge key, maps each verdict onto Connect's triage fields,
and writes triage.json plus TRIAGE-REPORT.md. Every check runs before
anything is written; one failure writes nothing.
"""
import argparse
import collections
import json
import pathlib
import re
import sys

METHOD_LANES = ("Construction", "Intent", "Contract", "Value or path")
POLICY, OTHER = "Policy", "Other"
ALL_LANES = METHOD_LANES + (POLICY, OTHER)
METHOD = re.compile(r"^(LLM: \S.*|Execution: coverity-verify|Human|None)$")
ROW_METHOD = re.compile(r"^(LLM: \S.*|Execution: coverity-verify|Human)$")
EXECUTION = "Execution: coverity-verify"
ROUTES = ("harness", "extraction")
TABLE = "checker table"
HEADER = "compiler header"
INVARIANT = "false positive - global invariant"
# verdict -> (classification, action, severity, comment label)
MAPPING = {
    "real": ("Bug", "Fix Required", None, "Real defect"),
    "real, low severity": ("Bug", "Fix Required", "Minor", "Real defect, low severity"),
    "intentional": ("Intentional", "Ignore", None, "Intentional"),
    INVARIANT: ("False Positive", "Ignore", None, "False positive (global invariant)"),
    "false positive - heuristic misfire": ("False Positive", "Ignore", None,
                                           "False positive (heuristic misfire)"),
    "unresolved": (None, None, None, "Unresolved"),
}
# what coverity-verify's record says about the run, carried into evidence
VERIFY_FIELDS = ("route", "route_reason", "as_code", "stubbed")
COMMENT_MAX = 4000
BAD_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# By-catch never rides in a verdict: these are the fields and phrasings it
# usually arrives in. A backstop only; by-catch in other words passes.
BYCATCH_FIELDS = ("bycatch", "by_catch", "side_findings", "side_observations")
BYCATCH_WORDS = re.compile(r"by-?catch|side observation|aside, not part of this finding"
                           r"|present but unreported|worth its own check", re.I)
TEXT_FIELDS = ("reason", "invariant", "enforced_at", "breaks_if")


def read_json(path, errors, what):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        errors.append(what + ": cannot read " + str(path) + ": " + str(e))
        return None


def comment_for(label, v, lane, assigner, method, date):
    executed = "executed" if v.get("executed") else "read, not executed"
    tail = ("\n[coverity-triage " + date + "] Lane: " + lane + " (assigned by "
            + assigner + "). Method: " + method + ", " + executed + ".")
    body = v["reason"].strip()
    if v["verdict"] == INVARIANT:
        body += ("\nInvariant: " + v["invariant"].strip() + "\nEnforced at: "
                 + v["enforced_at"].strip() + "\nBreaks if: " + v["breaks_if"].strip())
    head = label + ": "
    room = COMMENT_MAX - len(head) - len(tail)
    if len(body) > room:
        note = " ... [shortened; full text in triage.json evidence]"
        body = body[:room - len(note)].rstrip() + note
    return head + body + tail


def read_lanes(lanes, bundles, run, errors):
    """lanes.json -> {merge key: entry}, checking every entry and that nothing is pending."""
    pending = lanes.get("pending") or []
    if pending:
        unplaced = sorted({str(p.get("checker")) for p in pending if p.get("unplaced")})
        errors.append("lanes.json: " + str(len(pending)) + " finding(s) still pending ("
                      + str(len(pending) - sum(1 for p in pending if p.get("unplaced")))
                      + " for inference" + ("; unplaced checkers: " + ", ".join(unplaced)
                                            if unplaced else "") + "); resolve them first")
    assigner = run.get("assigner")
    lane_of = {}
    for a in lanes.get("lanes", []):
        mk = a.get("mergeKey")
        who = a.get("assigned_by") or ""
        where = "lanes.json: " + str(mk)
        if mk not in bundles:
            errors.append(where + " is not a bundled finding")
        elif mk in lane_of:
            errors.append(where + " assigned twice")
        elif a.get("lane") not in ALL_LANES:
            errors.append(where + ": lane " + repr(a.get("lane")) + " is not one of "
                          + ", ".join(ALL_LANES))
        elif not (a.get("reason") or "").strip():
            errors.append(where + ": no reason given for the lane")
        elif who not in (TABLE, HEADER) and (not METHOD.match(who) or who == "None"):
            errors.append(where + ": assigned_by must be '" + TABLE + "', '" + HEADER
                          + "', an LLM or Human, got " + repr(who))
        elif (who == HEADER) != bool(bundles[mk].get("compiler_header")) or (
                who == HEADER and a.get("lane") != OTHER):
            errors.append(where + ": '" + HEADER + "' is the lane Other for, and only for, a "
                          "finding bundle.py marked as in a compiler header")
        elif who == TABLE and a.get("candidates"):
            errors.append(where + ": the checker table fixes one lane; candidates mean "
                          "inference chose")
        elif who.startswith("LLM") and who != assigner:
            errors.append(where + ": assigned by " + who + ", but the plan's assigner is "
                          + repr(assigner))
        elif who.startswith("LLM") and a["lane"] not in (a.get("candidates") or []):
            errors.append(where + ": inference chose " + a["lane"] + ", which is not among the "
                          "checker's candidate lanes " + repr(a.get("candidates")))
        elif a.get("method") is not None and (not ROW_METHOD.match(a["method"])
                                              or a["lane"] in (POLICY, OTHER)):
            errors.append(where + ": the checker's method " + repr(a.get("method"))
                          + " is not a method a " + a["lane"] + " finding can carry")
        elif a.get("route") is not None and (a["route"] not in ROUTES
                                             or a.get("method") != EXECUTION):
            errors.append(where + ": route is harness or extraction, beside the method "
                          + EXECUTION)
        else:
            lane_of[mk] = a
    for mk in bundles:
        if mk not in lane_of and not any(e.startswith("lanes.json: " + mk) for e in errors):
            errors.append("lanes.json: " + mk + " (" + bundles[mk]["bundle"] + ") has no lane")
    return lane_of


def assemble(args):
    errors = []
    bdir = pathlib.Path(args.bundles)
    index = read_json(bdir / "index.json", errors, "index")
    lanes = read_json(args.lanes, errors, "lanes")
    run = read_json(args.run, errors, "run")
    if errors:
        return fail(errors)

    plan = run.get("lanes") or {}
    for lane in METHOD_LANES:
        m = plan.get(lane)
        if m is None or not METHOD.match(m):
            errors.append("run.json: lanes[" + repr(lane) + "] must be a method "
                          "(LLM: <model> | Execution: coverity-verify | Human | None), got "
                          + repr(m))
    for k in plan:
        if k not in METHOD_LANES:
            errors.append("run.json: unknown lane " + repr(k)
                          + " (Policy and Other are never planned)")
    if not METHOD.match(run.get("assigner") or ""):
        errors.append("run.json: assigner must name the method for inference (None when "
                      "nothing needs it), got " + repr(run.get("assigner")))
    if run.get("verify_route") is not None and run["verify_route"] not in ROUTES:
        errors.append("run.json: verify_route is harness or extraction, got "
                      + repr(run["verify_route"]))
    date = run.get("date") or ""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        errors.append("run.json: date must be YYYY-MM-DD, got " + repr(date))
    if errors:
        return fail(errors)

    bundles = {b["mergeKey"]: b for b in index.get("bundles", [])}
    lane_of = read_lanes(lanes, bundles, run, errors)
    overrides = read_overrides(run, bundles, errors)
    for mk in overrides:
        if lane_of.get(mk, {}).get("lane") == POLICY:
            errors.append("run.json: override for " + mk + ": a Policy finding takes no "
                          "triage; the rule is the authority")
        if lane_of.get(mk, {}).get("assigned_by") == HEADER:
            errors.append("run.json: override for " + mk + ": a finding in a compiler header "
                          "is never triaged")

    def method_for(mk):
        """The user's choice, then the checker's own method, then the lane's."""
        if mk in overrides:
            return overrides[mk][0]
        a = lane_of.get(mk, {})
        if a.get("lane") in (None, POLICY, OTHER):
            return "None"
        return a.get("method") or plan.get(a["lane"], "None")

    def route_for(mk):
        """For verify: the user's choice for the finding, then for the plan, then the row's."""
        if method_for(mk) != EXECUTION:
            return None
        return (overrides.get(mk, (None, None, None))[2] or run.get("verify_route")
                or lane_of.get(mk, {}).get("route"))

    expected = run.get("expected")
    if expected is not None:
        if expected.get("lane") not in METHOD_LANES or not METHOD.match(expected.get("method") or ""):
            errors.append("run.json: expected needs a method lane and a method, got " + repr(expected))
        else:
            for mk, a in lane_of.items():
                if (a["lane"] not in (expected["lane"], POLICY) and mk not in overrides
                        and a.get("assigned_by") != HEADER
                        and method_for(mk) != expected["method"]):
                    errors.append(bundles[mk]["bundle"] + " (" + mk + "): assigned " + a["lane"]
                                  + ", not the expected " + expected["lane"] + ", and the user's "
                                  "choice is not recorded (add an override with its reason)")

    verdict_of, model_of = {}, {}
    vdir = pathlib.Path(args.verdicts) if args.verdicts else None
    files = sorted(vdir.glob("*.json")) if vdir and vdir.is_dir() else []
    for f in files:
        doc = read_json(f, errors, "verdicts")
        if doc is None:
            continue
        lane, method = doc.get("lane"), doc.get("method")
        if lane not in ALL_LANES:
            errors.append(f.name + ": lane " + repr(lane) + " is not a lane")
            continue
        if not METHOD.match(method or "") or method == "None":
            errors.append(f.name + ": method " + repr(method) + " did not produce verdicts")
            continue
        for v in doc.get("verdicts", []):
            mk = v.get("mergeKey")
            where = f.name + ": " + str(mk)
            if mk not in bundles:
                errors.append(where + " is not a bundled finding")
                continue
            if mk in verdict_of:
                errors.append(where + " has a second verdict (also in " + verdict_of[mk][1] + ")")
                continue
            if mk in lane_of and lane_of[mk]["lane"] != lane:
                errors.append(where + " was read in " + lane + " but assigned to "
                              + lane_of[mk]["lane"])
                continue
            if method != method_for(mk):
                errors.append(where + ": method " + method + " is not the one planned for it ("
                              + method_for(mk) + ")")
                continue
            if v.get("verdict") not in MAPPING:
                errors.append(where + ": verdict " + repr(v.get("verdict"))
                              + " is not in the verdict set")
                continue
            if not (v.get("reason") or "").strip():
                errors.append(where + ": no reason")
                continue
            carried = [k for k in BYCATCH_FIELDS if k in v]
            worded = [k for k in TEXT_FIELDS if BYCATCH_WORDS.search(str(v.get(k) or ""))]
            if carried or worded:
                errors.append(where + ": by-catch in a verdict (" + ", ".join(carried + worded)
                              + "); it goes to the by-catch folder, never into the records "
                              "(references/records.md, By-catch)")
                continue
            if v["verdict"] == INVARIANT:
                gone = [k for k in ("invariant", "enforced_at", "breaks_if")
                        if not (v.get(k) or "").strip()]
                if gone:
                    errors.append(where + ": a global-invariant dismissal needs "
                                  + ", ".join(gone) + " (rule 30: no location, no dismissal)")
                    continue
            if v.get("executed") and not method.startswith("Execution"):
                errors.append(where + ": executed is true but the method is " + method)
                continue
            verdict_of[mk] = (v, f.name)
            model_of[mk] = doc.get("model")

    records = []
    for mk, b in sorted(bundles.items(), key=lambda kv: kv[1]["n"]):
        if mk not in lane_of:
            continue
        a = lane_of[mk]
        lane = a["lane"]
        method = method_for(mk)
        v = verdict_of.get(mk, (None, None))[0]
        if a["assigned_by"] == HEADER:
            if v is not None:
                errors.append(b["bundle"] + " (" + mk + "): a verdict for a finding in a "
                              "compiler header, which is never triaged")
                continue
            records.append(header_record(b, a, index.get("tag"), date))
            continue
        if v is None and method not in ("None", "Human"):
            errors.append(b["bundle"] + " (" + mk + "): " + lane + " finding ran " + method
                          + " but has no verdict")
            continue
        if v is not None and method == "None":
            errors.append(b["bundle"] + " (" + mk + "): a verdict for a finding whose method "
                          "did not run (" + lane + ", None)")
            continue
        state = {"classification": None, "action": None, "severity": None, "comment": None,
                 "customTriage": {"Defect Category": lane, "Triage Method": method}}
        evidence = {"bundle": b["bundle"], "selected_because": b.get("selected_because")}
        if route_for(mk):
            evidence["route_preference"] = route_for(mk)
        if v is not None:
            cls, act, sev, label = MAPPING[v["verdict"]]
            state.update(classification=cls, action=act, severity=sev,
                         comment=comment_for(label, v, lane, a["assigned_by"], method, date))
            if BAD_CHARS.search(state["comment"]):
                errors.append(b["bundle"] + " (" + mk + "): the comment carries a control "
                              "character (a NUL from a C '\\0' is the usual one); Connect "
                              "refuses the write")
                continue
            evidence.update({k: v.get(k) for k in ("reason", "invariant", "enforced_at",
                                                    "breaks_if", "sites_read") + VERIFY_FIELDS
                             if v.get(k) is not None})
            evidence["executed"] = bool(v.get("executed"))
            evidence["model"] = model_of.get(mk)
        elif lane == POLICY:
            evidence["status"] = "not triaged: Policy"
        elif method == "Human":
            evidence["status"] = "awaiting a person's verdict"
        rec = {"mergeKey": mk, "checker": b.get("checker"),
               "judged": {"tag": index.get("tag"), "sites": b.get("sites", [])},
               "lane": lane, "lane_reason": a["reason"].strip(),
               "lane_assigned_by": a["assigned_by"],
               "method": method, "verdict": v["verdict"] if v else None,
               "triageState": state, "evidence": evidence}
        if mk in overrides:
            rec["method_reason"] = overrides[mk][1]
        elif a.get("method") and method == a["method"]:
            rec["method_reason"] = "the checker's own method (checker table)"
        records.append(rec)

    bc_dir = pathlib.Path(args.bycatch_dir) if args.bycatch_dir else bdir / "bycatch"
    bycatch = read_bycatch(bc_dir, bundles, errors)

    if errors:
        return fail(errors)

    doc = {"format": "coverity-triage-records", "schema": 1,
           "run": dict(run, tables=lanes.get("tables"),
                       source={k: index.get(k) for k in ("issues", "git_repo", "tag", "source",
                                                         "strip_prefix", "findings_in_file")}),
           "records": records}
    problems = check(doc)
    if problems:
        return fail(problems)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    report = pathlib.Path(args.report) if args.report else out.with_name("TRIAGE-REPORT.md")
    report.write_bytes(render_report(doc).encode("utf-8"))
    print("wrote " + str(len(records)) + " records to " + str(out) + " and " + str(report))
    if bycatch:
        bc_out = bc_dir / "bycatch.json"
        bc_out.write_bytes((json.dumps({"format": "coverity-triage-bycatch", "schema": 1,
                                        "tag": index.get("tag"), "items": bycatch},
                                       indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        print("by-catch: " + str(len(bycatch)) + " item(s) in " + str(bc_out))
    else:
        print("by-catch: none")
    return 0


def header_record(b, a, tag, date):
    """A finding in a compiler header: Intentional by rule, with no method."""
    cls, act, sev, label = MAPPING["intentional"]
    comment = (label + ": the main site is in a compiler header (" + b["compiler_header"]
               + "), outside the analyzed code: a residual false positive.\n[coverity-triage "
               + date + "] Lane: Other (" + HEADER + "). Method: None; classified by rule.")
    return {"mergeKey": b["mergeKey"], "checker": b.get("checker"),
            "judged": {"tag": tag, "sites": b.get("sites", [])},
            "lane": OTHER, "lane_reason": a["reason"].strip(), "lane_assigned_by": HEADER,
            "method": "None", "verdict": "intentional",
            "triageState": {"classification": cls, "action": act, "severity": sev,
                            "comment": comment,
                            "customTriage": {"Defect Category": OTHER, "Triage Method": "None"}},
            "evidence": {"bundle": b["bundle"], "selected_because": b.get("selected_because"),
                         "status": "compiler header: Intentional by rule",
                         "compiler_header": b["compiler_header"]}}


def read_bycatch(bc_dir, bundles, errors):
    """The by-catch folder's files -> one list of items; never part of the records."""
    items = []
    if not bc_dir.is_dir():
        return items
    for f in sorted(bc_dir.glob("*.json")):
        if f.name == "bycatch.json":
            continue
        doc = read_json(f, errors, "by-catch")
        if doc is None:
            continue
        if not METHOD.match(doc.get("noticed_by") or "") or doc.get("noticed_by") == "None":
            errors.append("by-catch " + f.name + ": noticed_by must be the method that noticed it")
            continue
        for n, it in enumerate(doc.get("items") or [], 1):
            where = "by-catch " + f.name + " item " + str(n)
            gone = [k for k in ("site", "claim") if not (it.get(k) or "").strip()]
            if gone:
                errors.append(where + ": needs " + ", ".join(gone))
            elif it.get("noticed_while") not in bundles:
                errors.append(where + ": noticed_while " + repr(it.get("noticed_while"))
                              + " is not a bundled finding")
            else:
                items.append(dict(it, noticed_by=doc["noticed_by"], model=doc.get("model"),
                                  file=f.name))
    return items


def check(doc):
    """The invariants of a triage.json, whoever wrote it."""
    p = []
    if doc.get("format") != "coverity-triage-records" or doc.get("schema") != 1:
        p.append("format/schema must be coverity-triage-records / 1")
    seen = set()
    for r in doc.get("records", []):
        mk = r.get("mergeKey")
        w = str(mk) + ": "
        if not mk or mk in seen:
            p.append(w + "missing or duplicate merge key")
        seen.add(mk)
        lane, method, verdict = r.get("lane"), r.get("method"), r.get("verdict")
        st = r.get("triageState") or {}
        ct = st.get("customTriage") or {}
        if lane not in ALL_LANES:
            p.append(w + "bad lane " + repr(lane))
        if not METHOD.match(method or ""):
            p.append(w + "bad method " + repr(method))
        if lane == POLICY and (method != "None" or verdict is not None):
            p.append(w + "Policy takes method None and no verdict")
        if r.get("lane_assigned_by") == HEADER:
            if (lane, method, verdict) != (OTHER, "None", "intentional"):
                p.append(w + "a finding in a compiler header is Other, method None, "
                         "verdict intentional")
        elif (lane == OTHER and (method != "None" or verdict is not None)
                and not r.get("method_reason")):
            p.append(w + "Other takes method None and no verdict, unless an override says why")
        if ct != {"Defect Category": lane, "Triage Method": method}:
            p.append(w + "customTriage must carry exactly Defect Category and Triage Method")
        if verdict is None:
            if any(st.get(k) is not None for k in ("classification", "action", "severity",
                                                   "comment")):
                p.append(w + "no verdict, so only the custom attributes may be set")
            continue
        if verdict not in MAPPING:
            p.append(w + "verdict " + repr(verdict) + " not in the verdict set")
            continue
        cls, act, sev, _ = MAPPING[verdict]
        if (st.get("classification"), st.get("action"), st.get("severity")) != (cls, act, sev):
            p.append(w + "triage state does not follow the mapping for " + repr(verdict))
        c = st.get("comment") or ""
        if not c or len(c) > COMMENT_MAX:
            p.append(w + "comment missing or longer than " + str(COMMENT_MAX))
        if BAD_CHARS.search(c):
            p.append(w + "comment carries a control character")
    return p


def render_report(doc):
    run, recs = doc["run"], doc["records"]
    src = run.get("source") or {}
    by_table = sum(1 for r in recs if r.get("lane_assigned_by") == TABLE)
    by_header = sum(1 for r in recs if r.get("lane_assigned_by") == HEADER)
    L = ["# Triage report", "",
         "- **Who and where:** " + str(run.get("who")) + "; Connect AI-Assisted Triage: "
         + ("yes" if run.get("connect_ai_triage") else "not used") + "; nothing written to Connect",
         "- **Version:** `" + str(src.get("tag")) + "`, " + str(len(recs)) + " of "
         + str(src.get("findings_in_file")) + " findings (" + str(run.get("selection")) + ")",
         "- **Lanes:** " + str(by_table) + " from the checker table ("
         + ", ".join(run.get("tables") or []) + "), " + str(by_header)
         + " in a compiler header (Other, Intentional by rule), "
         + str(len(recs) - by_table - by_header)
         + " by inference or a person (" + str(run.get("assigner")) + ")",
         "- **Plan:** " + "; ".join(l + ": " + str(run["lanes"].get(l)) for l in METHOD_LANES)
         + "; Policy: no triage; Other: None"
         + ("; verify route for this plan: " + run["verify_route"] if run.get("verify_route") else ""),
         "",
         "## By lane", "",
         "| lane | method | findings | " + " | ".join(MAPPING) + " | no verdict |",
         "|---|---|---|" + "---|" * (len(MAPPING) + 1)]
    for lane in ALL_LANES:
        rs = [r for r in recs if r["lane"] == lane]
        if not rs:
            continue
        c = collections.Counter(r["verdict"] for r in rs)
        methods = sorted({r["method"] for r in rs})
        L.append("| " + lane + " | " + ", ".join(methods) + " | " + str(len(rs)) + " | "
                 + " | ".join(str(c.get(v, 0)) for v in MAPPING) + " | " + str(c.get(None, 0)) + " |")
    untriaged = collections.Counter(r["lane"] for r in recs if r["verdict"] is None)
    if untriaged:
        L += ["", "No verdict: " + ", ".join(k + " " + str(n) for k, n in sorted(untriaged.items()))
              + " (Policy is never triaged; Other has no method; Human awaits a person; "
              "None was the plan's choice)."]
    L += ["", "## Findings", "",
          "| bundle | checker | site | lane | assigned by | method | verdict | lane reason |",
          "|---|---|---|---|---|---|---|---|"]
    for r in recs:
        s = (r["judged"]["sites"] or [{}])[0]
        if r.get("lane_assigned_by") == HEADER:
            shown = "intentional (compiler header, by rule)"
        elif r["verdict"]:
            shown = r["verdict"]
        elif r["lane"] == POLICY:
            shown = "not triaged (Policy)"
        elif r["method"] == "Human":
            shown = "awaiting a person"
        else:
            shown = "-"
        L.append("| " + r["evidence"]["bundle"] + " | " + str(r["checker"]) + " | `"
                 + str(s.get("file")) + ":" + str(s.get("line")) + "` | " + r["lane"] + " | "
                 + str(r.get("lane_assigned_by")) + " | " + r["method"] + " | " + shown
                 + " | " + r["lane_reason"].replace("|", "\\|") + " |")
    L += ["", "A sample's counts describe the sample, not the run's false-positive rate (rule 26).", ""]
    return "\n".join(L)


def read_overrides(run, bundles, errors):
    """run.json overrides -> {merge key: (method, reason, route)}: the user's per-finding choices."""
    out = {}
    for o in run.get("overrides") or []:
        mk, m, why = o.get("mergeKey"), o.get("method"), (o.get("reason") or "").strip()
        route = o.get("route")
        if mk not in bundles:
            errors.append("run.json: override for " + str(mk) + ", which is not a bundled finding")
        elif mk in out:
            errors.append("run.json: two overrides for " + mk)
        elif not METHOD.match(m or ""):
            errors.append("run.json: override for " + mk + ": " + repr(m) + " is not a method")
        elif not why:
            errors.append("run.json: override for " + mk + " gives no reason")
        elif route is not None and (route not in ROUTES or m != EXECUTION):
            errors.append("run.json: override for " + mk + ": route is harness or extraction, "
                          "beside the method " + EXECUTION)
        else:
            out[mk] = (m, why, route)
    return out


def check_lanes(args):
    """Before any method runs: the lane counts, and every finding outside the expected lane."""
    errors = []
    index = read_json(pathlib.Path(args.bundles) / "index.json", errors, "index")
    lanes = read_json(args.lanes, errors, "lanes")
    run = read_json(args.run, errors, "run") if args.run else {}
    if errors:
        return fail(errors)
    bundles = {b["mergeKey"]: b for b in index.get("bundles", [])}
    assigned = {a.get("mergeKey"): a for a in lanes.get("lanes", [])}
    pending = lanes.get("pending") or []
    counts = collections.Counter(a.get("lane") for a in assigned.values())
    print("lanes: " + ", ".join(l + " " + str(counts.get(l, 0)) for l in ALL_LANES)
          + "; pending " + str(len(pending)) + "; unassigned "
          + str(len(set(bundles) - set(assigned) - {p.get("mergeKey") for p in pending})))
    exp = (run or {}).get("expected")
    if not exp:
        print("no expected lane in run.json")
        return 0
    overrides = read_overrides(run, bundles, [])
    off = [(bundles[mk], a) for mk, a in assigned.items()
           if mk in bundles and a.get("lane") not in (exp.get("lane"), POLICY)
           and a.get("assigned_by") != HEADER and a.get("method") != exp.get("method")]
    print("expected by " + str(exp.get("by")) + ": " + str(exp.get("lane")) + " with "
          + str(exp.get("method")) + "; " + str(len(off)) + " finding(s) landed elsewhere")
    if counts.get(POLICY):
        print("  " + str(counts[POLICY]) + " in Policy: not triaged, and no choice to make")
    n_hdr = sum(1 for a in assigned.values() if a.get("assigned_by") == HEADER)
    if n_hdr:
        print("  " + str(n_hdr) + " in a compiler header: Intentional by rule, no choice to make")
    for b, a in sorted(off, key=lambda x: x[0]["n"]):
        choice = overrides.get(a["mergeKey"])
        print("  " + b["bundle"] + "  " + str(a.get("lane")) + "  -- " + str(a.get("reason")))
        if choice:
            print("      user chose: " + choice[0] + " (" + choice[1] + ")")
        else:
            print("      not chosen yet: the expected method anyway, this lane's method, or None")
    return 0


def fail(errors):
    for e in errors:
        print("[ERROR] " + e, file=sys.stderr)
    print("[FATAL] " + str(len(errors)) + " problem(s); nothing written", file=sys.stderr)
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("assemble")
    a.add_argument("--bundles", required=True, help="tools/bundle.py --out directory")
    a.add_argument("--lanes", required=True)
    a.add_argument("--verdicts", help="directory of verdict files (none: every lane planned None or Human)")
    a.add_argument("--run", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--report", help="default: TRIAGE-REPORT.md beside --out")
    a.add_argument("--bycatch-dir", help="the by-catch folder (default: <bundles>/bycatch); "
                                        "its files are checked and collected into bycatch.json")
    c = sub.add_parser("check-lanes", help="before any method runs: lanes, and what landed "
                                          "outside the caller's expected lane")
    c.add_argument("--bundles", required=True)
    c.add_argument("--lanes", required=True)
    c.add_argument("--run")
    v = sub.add_parser("validate")
    v.add_argument("records")
    args = ap.parse_args()
    if args.cmd == "assemble":
        return assemble(args)
    if args.cmd == "check-lanes":
        return check_lanes(args)
    errors = []
    doc = read_json(args.records, errors, "records")
    if errors:
        return fail(errors)
    problems = check(doc)
    if problems:
        return fail(problems)
    print("valid: " + str(len(doc["records"])) + " records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
