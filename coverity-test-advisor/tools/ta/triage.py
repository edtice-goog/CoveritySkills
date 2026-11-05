"""Target lines, the deterministic verdicts, and the evidence packet for the judge."""
import re

from . import coverage as C
from . import models as M

CALL_RE = re.compile(r"([A-Za-z_$][\w$]*)\s*\(")
NOT_CALLS = {"if", "while", "for", "switch", "catch", "synchronized", "return", "throw", "new", "super", "this",
             "assert", "case", "else", "do", "try"}


def has_call(text):
    """A method call on the line: an identifier then "(", not a keyword (`if (`, `while (`) and not a constructor
    (`new X(` cannot throw silently before a probe in the same way as a call to a reporter)."""
    for m in CALL_RE.finditer(text):
        name = m[1]
        before = text[:m.start()].rstrip()
        if name not in NOT_CALLS and not before.endswith("new"):
            return True
    return False


def unprovable_miss(cov, source, n):
    """True when coverage cannot show that line n did not run. JaCoCo counts a line as run only when a probe after
    it runs, and a call that throws never reaches that probe: a line holding a call that threw reads 0 although it
    ran (`_reportInvalidChar(...)` and the like). A `throw` statement has a probe before it, so its 0 is real. gcov
    counts the line on entry, so it has no such case."""
    if getattr(cov, "counts", True) or not source or not 0 < n <= len(source):
        return False
    text = source[n - 1].strip()
    return not text.startswith("throw ") and has_call(text)


def target_lines(fid, info, s0, graph, cov, fn):
    """{line: why} for the lines that carry the change in this function. A line gcov does not instrument (a
    continuation of a statement, a parameter line) counts as the nearest instrumented line above it."""
    instrumented = cov.lines.get(fn.file, {})

    def anchor(n):
        while n >= fn.start and n not in instrumented:
            n -= 1
        return n if n >= fn.start else None

    out = {}
    for reason in info["reasons"]:
        if reason[0] == "model":
            continue          # no line carries this change; the judge reads the model delta
        if reason[0] == "changed":
            lines, why = s0[fid]["lines"], "changed"
        else:
            lines, why = graph.sites.get((fid, reason[1]), ()), f"calls {reason[1].split(':')[1]}"
        for n in lines:
            a = anchor(n)
            if a is not None:
                out.setdefault(a, why)
    return dict(sorted(out.items()))


def triage(fn, targets, cov, source=None):
    """(verdict, detail) for the clear cases, or ("JUDGE", ...) when every target line ran, or when the coverage
    tool cannot prove that a line did not run (see unprovable_miss); then the judge checks the tests."""
    if not cov.has(fn.file):
        return "UNKNOWN", "the file is not in the coverage build"
    rec = cov.functions[fn.file].get(fn.name)
    ran = rec["count"] if rec else max((cov.count(fn.file, n) or 0) for n in range(fn.start, fn.end + 1))
    if not ran:
        first = min((n for n in cov.lines.get(fn.file, {}) if fn.start <= n <= fn.end), default=None)
        if first is not None and unprovable_miss(cov, source, first):
            return "JUDGE", (f"coverage shows no line ran, but the first statement (line {first}) is a call, and a "
                             "call that throws leaves no trace in JaCoCo; the judge checks the tests")
        return "UNTESTED", "no test reaches this function"
    if not targets:
        return "JUDGE", ("no instrumented line carries the change (its model changed with none of its lines, or its "
                         "changed lines are not instrumented); the judge reads the model delta and the diff")
    missed = [n for n in targets if not cov.count(fn.file, n)]
    # A 0 right after an unprovable 0 is unprovable too: when that call always throws, the line after it
    # (`return null; // never gets here`) can never run, tested or not.
    instrumented = sorted(n for n in cov.lines.get(fn.file, {}) if fn.start <= n <= fn.end)
    unprovable = set()
    for n in instrumented:
        prev = instrumented[instrumented.index(n) - 1] if instrumented.index(n) else None
        if not cov.count(fn.file, n) and (unprovable_miss(cov, source, n) or
                                          (prev in unprovable and not getattr(cov, "counts", True))):
            unprovable.add(n)
    certain = [n for n in missed if n not in unprovable]
    if certain:
        return "INSUFFICIENT", certain
    if missed:
        return "JUDGE", (f"line(s) {', '.join(map(str, missed))} read as not run, but each is a call, and a call that "
                         "throws leaves no trace in JaCoCo; the judge checks the tests")
    return "JUDGE", f"all {len(targets)} target lines ran"


def tests_reaching(fn, lines, per_test):
    out = {}
    for unit, cov in per_test.items():
        hits = [n for n in lines if (cov.count(fn.file, n) or 0) > 0]
        if hits:
            out[unit] = len(hits)
    return out


def packet(fid, fn, info, s0, deltas, graph, cov, per_test, targets, triaged, source, per_test_note=None,
           unmapped=None):
    """Markdown for one function: why it is affected, the change, the tests, and its source with coverage."""
    out = [f"# {fid} (lines {fn.start}-{fn.end})", "", f"Triage: **{triaged[0]}**, {triaged[1]}", "",
           "## Why affected", ""]
    for reason in info["reasons"]:
        if reason[0] == "model":
            out.append("- Its derived model changed although none of its lines did, so the cause is outside it: a "
                       "header macro, an inline function or a type it uses, or a callee the call graph does not see:")
            out += [f"  - {line}" for line in M.describe(deltas[fn.name])]
            if unmapped:
                out.append("  - Changed lines outside every analysed function in this change, one of which may be the "
                           "cause (a macro, a type, an inline function in a header):")
                out += [f"    - {u['file']}: lines {', '.join(map(str, u['lines'][:12]))}"
                        + (" and more" if len(u["lines"]) > 12 else "") + f" ({u['kind']})" for u in unmapped]
            continue
        if reason[0] == "changed":
            out.append(f"- Its own code changed ({s0[fid]['kind']}):")
            for h in s0[fid]["hunks"]:
                out += ["", "```diff", *h["text"], "```"]
        else:
            callee = reason[1].split(":")[1]
            sites = sorted(graph.sites.get((fid, reason[1]), ()))
            via = sorted(graph.virtual.get((fid, reason[1]), ()))
            through = f" (the call is to `{'`, `'.join(via)}`, which this overrides)" if via else ""
            out.append(f"- Calls `{callee}`{through} at line {', '.join(map(str, sites))}, whose derived model changed:")
            out += [f"  - {line}" for line in M.describe(deltas[callee])]
    if info["address_taken"]:
        out.append(f"- Its address is taken in {', '.join(info['address_taken'])}; calls through the pointer "
                   "are not in the graph.")
    if graph.indirect.get(fid):
        out.append(f"- It calls through a function pointer at line(s) {sorted(graph.indirect[fid])}.")
    if per_test:
        whole = tests_reaching(fn, range(fn.start, fn.end + 1), per_test)
        tgt = tests_reaching(fn, list(targets), per_test)
        out += ["", "## Tests that reach it", "",
                f"- The function: {', '.join(f'{u} ({n} lines)' for u, n in sorted(whole.items())) or 'none'}",
                f"- The target lines: {', '.join(f'{u} ({n})' for u, n in sorted(tgt.items())) or 'none'}"]
        if per_test_note:
            out.append(f"- Note: {per_test_note}.")
    legend = ("count: times run (`-` not instrumented). br: branch arcs taken/total." if cov.counts else
              "count: `ran` or `0` (no instruction ran; JaCoCo gives no counts), `-` no executable code. "
              "br: branches covered/total.")
    out += ["", "## Source with coverage (whole suite)", "", f"`>` marks a target line. {legend}", "", "```"]
    for n in range(fn.start, fn.end + 1):
        rec = cov.lines.get(fn.file, {}).get(n)
        cnt = "-" if rec is None else str(rec["count"]) if cov.counts else ("ran" if rec["count"] else "0")
        br = ""
        if rec and rec["branches"]:
            br = f"br {sum(1 for b in rec['branches'] if b)}/{len(rec['branches'])}"
        mark = ">" if n in targets else " "
        code = source[n - 1] if n - 1 < len(source) else ""
        out.append(f"{mark}{n:5} {cnt:>7} {br:>9} | {code}")
        for c in (rec or {}).get("conditions", []):
            if c["covered"] < c["count"]:
                out.append(f"{'':25}   ^ {C.condition_text(c)}")
    out.append("```")
    return "\n".join(out) + "\n"
