"""A condensed reading list for the judge, for a batch of functions.

    python3 -m ta.judgeview runs/<pair> <fids.txt> <out.md>

Packets list every line of a function, which for a long parser method is 90 KB. This keeps what a verdict rests on:

- once per batch, each changed callee the batch calls: its own diff, and which of its changed lines ran;
- per function: why it is affected (model deltas cut short), the tests that reach it, and its source reduced to the
  target lines with two lines either side, plus every unrun or half-covered line, with gaps marked `...`.

The packet stays the evidence of record (its path and digest are in analysis.json); this is a view of it.
"""
import json
import re
import sys

SRC_RE = re.compile(r"^([> ])\s*(\d+)\s+(\S+)\s+(br \d+/\d+)?\s*\| ?(.*)$")
DELTA_CUT = 260


def sections(text):
    out, cur = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out[cur] = []
        elif cur:
            out[cur].append(line)
    return out


def source_rows(lines):
    rows = []
    for line in lines:
        m = SRC_RE.match(line)
        if m:
            mark, n, cnt, br, code = m.groups()
            rows.append({"target": mark == ">", "n": int(n), "count": cnt, "br": br or "", "code": code,
                         "line": line})
    return rows


def weak(r):
    if r["count"] == "0":
        return True
    if r["br"]:
        a, b = map(int, r["br"].split()[1].split("/"))
        return a < b
    return False


def condensed_source(rows, cap=40):
    keep = set()
    for i, r in enumerate(rows):
        if r["target"]:
            keep.update(range(max(0, i - 2), min(len(rows), i + 3)))
    extra = [i for i, r in enumerate(rows) if weak(r) and i not in keep]
    keep.update(extra[:cap])
    out, prev = [], None
    for i in sorted(keep):
        if prev is not None and i != prev + 1:
            out.append("   ...")
        out.append(rows[i]["line"])
        prev = i
    if len(extra) > cap:
        out.append(f"   ... and {len(extra) - cap} more unrun or half-covered lines in this function")
    return out


def diff_blocks(why):
    out, inside = [], False
    for line in why:
        if line.startswith("```diff"):
            inside = True
            continue
        if line.startswith("```") and inside:
            inside = False
            continue
        if inside and not line.startswith(("--- a/", "+++ b/")):
            out.append(line)
    return out


def cut(line):
    return line if len(line) <= DELTA_CUT else line[:DELTA_CUT] + " ..."


def main():
    run, fids_file, out_path = sys.argv[1:4]
    a = json.load(open(f"{run}/analysis.json"))
    A = a["affected"]
    fids = [l.strip() for l in open(fids_file) if l.strip()]
    out = [f"# Judge view: {len(fids)} functions, {a['base']['tag']} -> {a['head']['tag']}", ""]

    callees = []
    for fid in fids:
        for x in A[fid]["reasons"]:
            if x[0] == "calls" and x[1] not in callees:
                callees.append(x[1])
    out += ["## Changed callees this batch calls", ""]
    for c in callees:
        r = A.get(c)
        if r is None:
            out += [f"### {c}", "(not in the affected set)", ""]
            continue
        text = open(f"{run}/{r['packet']}").read()
        why = sections(text).get("Why affected", [])
        own = diff_blocks(why) if any(x[0] == "changed" for x in r["reasons"]) else []
        rows = source_rows(sections(text).get("Source with coverage (whole suite)", []))
        out += [f"### {c} [{r['file'].split('/')[-1]} {r['start']}-{r['end']}] verdict so far: {r['triage']}"]
        if own:
            out += ["own diff:", "```diff", *own[:80], "```"]
            if len(own) > 80:
                out.append(f"(diff cut: {len(own) - 80} more lines in {r['packet']})")
            changed = [row for row in rows if row["target"]]
            out.append("its changed lines: " + (", ".join(f"{row['n']} {row['count']}" for row in changed) or "none"))
        others = [y[1].split(":", 1)[1] for y in r["reasons"] if y[0] == "calls"]
        if others:
            out.append("its model also changed through: " + ", ".join(others[:8]) + (" ..." if len(others) > 8 else ""))
        out.append("")

    roots, seen, stack = [], set(), list(callees)
    while stack:
        c = stack.pop(0)
        if c in seen or c not in A:
            continue
        seen.add(c)
        if any(y[0] in ("changed", "model") for y in A[c]["reasons"]):
            roots.append(c)
        stack += [y[1] for y in A[c]["reasons"] if y[0] == "calls"]
    out += ["## Root changes: the methods whose own code changed, at the bottom of those chains", ""]
    for c in roots:
        if c in callees:
            out.append(f"### {c}: own diff shown above")
            out.append("")
            continue
        r = A[c]
        text = open(f"{run}/{r['packet']}").read()
        own = diff_blocks(sections(text).get("Why affected", []))
        rows = source_rows(sections(text).get("Source with coverage (whole suite)", []))
        changed = [row for row in rows if row["target"]]
        out += [f"### {c} [{r['file'].split('/')[-1]} {r['start']}-{r['end']}] verdict so far: {r['triage']}",
                "```diff", *own[:60], "```"]
        if len(own) > 60:
            out.append(f"(diff cut: {len(own) - 60} more lines in {r['packet']})")
        out += ["its changed lines: " + (", ".join(f"{row['n']} {row['count']}" for row in changed) or "none"), ""]

    out += ["## Functions to judge", ""]
    for k, fid in enumerate(fids, 1):
        r = A[fid]
        text = open(f"{run}/{r['packet']}").read()
        sec = sections(text)
        out += [f"### {k}. {fid}", f"packet: {r['packet']}; lines {r['start']}-{r['end']}; "
                f"depth {r['depth']}; triage {r['triage']}; targets {sorted(map(int, r['targets']))}"]
        why = [l for l in sec.get("Why affected", []) if l.strip()]
        inside = False
        for line in why:
            if line.startswith("```"):
                inside = not inside
                out.append(line)
                continue
            out.append(line if inside else cut(line))
        tests = [l for l in sec.get("Tests that reach it", []) if l.startswith("- The")]
        out += tests
        out += ["```", *condensed_source(source_rows(sec.get("Source with coverage (whole suite)", []))), "```", ""]
    open(out_path, "w").write("\n".join(out) + "\n")
    print(out_path, len("\n".join(out)), "chars")


if __name__ == "__main__":
    main()
