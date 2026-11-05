"""What must be true of Test Advisor's output on the gap fixture (evals/run.sh).

    python3 check_gap.py analyze <out>    after `ta.run analyze`
    python3 check_gap.py finish <out>     after `ta.run finish` without verdicts

Prints PASS or FAIL per case and exits 1 if any failed.
"""
import json
import os
import sys

F = "src/strutil.c:"
failed = False


def check(name, ok):
    global failed
    print(("PASS " if ok else "FAIL ") + name)
    failed |= not ok


def analyze(out):
    a = json.load(open(os.path.join(out, "analysis.json")))
    aff = a["affected"]
    check("S0 is parse_len and strutil_name", set(a["s0"]) == {F + "parse_len", F + "strutil_name"})
    check("parse_len's derived model changed", "parse_len" in a["model_changes"])
    check("strutil_name's derived model did not change", "strutil_name" not in a["model_changes"])
    check("parse_len: INSUFFICIENT by the fixed rules (its new return -1 never ran)",
          aff.get(F + "parse_len", {}).get("triage") == "INSUFFICIENT")
    check("field_len is affected: it calls parse_len, whose model changed",
          any(r[0] == "calls" and r[1] == F + "parse_len" for r in aff.get(F + "field_len", {}).get("reasons", [])))
    check("field_len goes to the judge: its call to parse_len ran",
          aff.get(F + "field_len", {}).get("triage") == "JUDGE")
    check("strutil_name goes to the judge: its changed line ran", aff.get(F + "strutil_name", {}).get("triage") == "JUDGE")
    check("strutil_name is a boundary: its model did not change, so its callers are not walked from it",
          aff.get(F + "strutil_name", {}).get("boundary") is True
          and not any(r[0] == "calls" and r[1] == F + "strutil_name"
                      for v in aff.values() for r in v.get("reasons", [])))
    check("record_size is affected: it calls field_len, whose model changed in turn",
          any(r[0] == "calls" and r[1] == F + "field_len" for r in aff.get(F + "record_size", {}).get("reasons", [])))
    check("describe: its model changed with none of its lines changed, so it is affected for that reason alone",
          "describe" in a["model_changes"] and aff.get(F + "describe", {}).get("reasons") == [["model"]])
    check("describe goes to the judge: no line carries its change, and it ran",
          aff.get(F + "describe", {}).get("triage") == "JUDGE")
    packet = aff.get(F + "describe", {}).get("packet")
    text = open(os.path.join(out, packet)).read() if packet else ""
    check("describe's evidence names the change outside every function as a candidate cause (strutil.h line 4)",
          "outside every analysed function" in text and "src/strutil.h" in text and "4" in text.split("src/strutil.h", 1)[-1][:20])
    check("no model change is left unreached", not a.get("unexplained_model_changes"))
    um = [u for u in a["unmapped_changes"] if u["file"] == "src/strutil.h"]
    check("the STRUTIL_VERSION line is listed as in no function", any(4 in u["lines"] for u in um))
    judge = [l for l in open(os.path.join(out, "judge.txt")) if l.strip()]
    check("judge.txt holds every JUDGE function", len(judge) == sum(v["triage"] == "JUDGE" for v in aff.values()))
    status = json.load(open(os.path.join(out, "status.json")))
    check("status.json: ok, exit 0, the judge count", status["status"] == "ok" and status["exit"] == 0
          and status["judge"] == len(judge))


def finish(out):
    r = json.load(open(os.path.join(out, "report.json")))
    v = {k: x["verdict"] for k, x in r["verdicts"].items()}
    check("report.json: parse_len INSUFFICIENT", v.get(F + "parse_len") == "INSUFFICIENT")
    check("report.json: every function the judge did not see is NOT_JUDGED",
          all(v.get(k) == "NOT_JUDGED" for k in (F + "field_len", F + "record_size", F + "strutil_name", F + "describe")))
    check("report.md written", os.path.exists(os.path.join(out, "report.md")))
    xml_path = os.path.join(out, "TA.INSUFFICIENT_TEST_COVERAGE.errors.xml")
    xml = open(xml_path).read() if os.path.exists(xml_path) else ""
    check("errors.xml: one issue, for parse_len, subcategory insufficient",
          xml.count("<checker>TA.INSUFFICIENT_TEST_COVERAGE</checker>") == 1 and "parse_len" in xml
          and "insufficient" in xml)
    check("the issues were imported into a copy of the head idir",
          os.path.isdir(os.path.join(out, "ta-idirs", "head")))


if __name__ == "__main__":
    {"analyze": analyze, "finish": finish}[sys.argv[1]](sys.argv[2])
    sys.exit(1 if failed else 0)
