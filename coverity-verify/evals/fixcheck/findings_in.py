"""Print the findings in one function from a cov-format-errors --json-output-v10 file.

usage: findings_in.py <findings.json> <function>
"""
import json
import sys

issues = json.load(open(sys.argv[1]))["issues"]
hits = [(i["checkerName"], i["mainEventLineNumber"]) for i in issues
        if i.get("functionDisplayName") == sys.argv[2]]
print(", ".join("%s at line %d" % h for h in hits) if hits else "no finding in %s" % sys.argv[2])
