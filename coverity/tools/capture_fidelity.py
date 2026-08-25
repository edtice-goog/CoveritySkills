#!/usr/bin/env python3
"""Capture-fidelity evidence collection and adjudication.

Four subcommands, one per step of the protocol in
references/capture-fidelity.md. They are separate commands on purpose: the
protocol requires each method's result to be frozen to disk before the next
runs, and separate invocations make that structural rather than aspirational.

    expect      Method C scaffold -- walks the SOURCE TREE ONLY.  Run first.
    method-a    capture inventory from the intermediate directory.
    method-b    scan-transparency readout.
    adjudicate  compare the three frozen files, grade, and explain.

Pure standard library.  No pip install on a build machine.
"""

import argparse
import json
import os
import re
import subprocess
import sys

# --------------------------------------------------------------------------
# paths


def norm(p):
    """Comparison key for a path: forward slashes, lowercase, no trailing sep.

    Windows capture data mixes separators and cases freely -- the same file
    appears as C:\\Src\\Main.c and c:/src/main.c in different readouts.
    """
    if not p:
        return ""
    p = str(p).replace("\\", "/")
    while "//" in p:
        p = p.replace("//", "/")
    return p.rstrip("/").lower()


def run(cmd, cwd=None):
    """Run a command, returning (rc, stdout, stderr).  Never raises."""
    try:
        r = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            errors="replace", timeout=1800,
        )
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"


def tool(bindir, name):
    exe = ".exe" if os.name == "nt" else ""
    return os.path.join(bindir, name + exe)


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
    print("wrote %s" % path, file=sys.stderr)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def first_json(text):
    """Extract the first complete JSON value from mixed output.

    The CLI interleaves [INFO] lines with JSON; cov-manage-emit sometimes
    prefixes a banner.  Scan for the first { or [ and brace-match from there,
    ignoring braces inside strings.
    """
    start = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start is None:
        return None
    opens, closes = {"{": "}", "[": "]"}, {"}": "{", "]": "["}
    stack, in_str, esc = [], False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in opens:
            stack.append(opens[ch])
        elif ch in closes:
            if not stack or stack[-1] != ch:
                return None
            stack.pop()
            if not stack:
                try:
                    return json.loads(text[start:i + 1])
                except ValueError:
                    return None
    return None


# --------------------------------------------------------------------------
# Method C: expectation scaffold

# Ordered: the first pattern that matches wins.
CLASSIFIERS = [
    ("build-probe", r"(trycompile|cmakescratch|cmakefiles/[0-9.]+/compilerid|"
                    r"compilerid[a-z+]*\.(c|cpp|cxx)$|conftest\.c$|"
                    r"cmaketmp|checkinclude|checkfunctionexists|"
                    r"checksymbolexists|checktypesize)"),
    ("third-party", r"(^|/)(third[_-]?party|vendor|external|extern|deps|"
                    r"node_modules|\.git)(/|$)"),
    ("test", r"(^|/)(tests?|testing|spec|fixtures?|benchmarks?|examples?)(/|$)"),
    ("generated", r"(^|/)(generated|gen|build|out|cmake-build[^/]*|"
                  r"\.build)(/|$)|\.(pb|generated)\.(c|cc|cpp|h|hpp)$"),
]

SOURCE_EXT = {
    ".c": "C", ".h": "C-header", ".i": "C",
    ".cc": "C++", ".cpp": "C++", ".cxx": "C++", ".c++": "C++",
    ".hh": "C++-header", ".hpp": "C++-header", ".hxx": "C++-header",
    ".m": "Objective-C", ".mm": "Objective-C++",
    ".cs": "C#", ".java": "Java", ".kt": "Kotlin", ".scala": "Scala",
    ".go": "Go", ".rs": "Rust", ".swift": "Swift", ".dart": "Dart",
    ".py": "Python", ".rb": "Ruby", ".php": "PHP",
    ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".vb": "Visual Basic", ".f": "Fortran", ".f90": "Fortran",
}

# Headers are not translation units; they are captured as part of one.
HEADER_KINDS = {"C-header", "C++-header"}


def cmd_expect(args):
    root = os.path.abspath(args.project_dir)
    rootn = norm(root)
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", ".svn", ".hg")]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            kind = SOURCE_EXT.get(ext)
            if not kind:
                continue
            full = os.path.join(dirpath, fn)
            rel = norm(os.path.relpath(full, root))
            bucket = "product"
            for name, pat in CLASSIFIERS:
                if re.search(pat, rel, re.I):
                    bucket = name
                    break
            if kind in HEADER_KINDS:
                bucket = "header"
            files.append({
                "path": rel,
                "abs": norm(full),
                "language": kind,
                "bucket": bucket,
                "decision": "EXPECT" if bucket == "product" else "REVIEW",
                "reason": "" if bucket == "product"
                          else "auto-classified as %s -- confirm" % bucket,
            })
    files.sort(key=lambda d: d["path"])
    counts = {}
    for f in files:
        counts[f["bucket"]] = counts.get(f["bucket"], 0) + 1

    out = {
        "method": "C",
        "note": (
            "SCAFFOLD ONLY -- the automatic bucketing is a starting point, "
            "not the expectation. Review every REVIEW row, set decision to "
            "EXPECT or EXCLUDE, and give a reason for each EXCLUDE. Do this "
            "BEFORE opening the intermediate directory."
        ),
        "project_dir": rootn,
        "reviewed": False,
        "counts_by_bucket": counts,
        "files": files,
    }
    write_json(args.out, out)
    print("%d candidate source files; %d auto-bucketed as product"
          % (len(files), counts.get("product", 0)), file=sys.stderr)
    print("REVIEW the scaffold and set 'reviewed': true before adjudicating.",
          file=sys.stderr)
    return 0


# --------------------------------------------------------------------------
# Method A: capture inventory

CAPTURE_SUMMARY_RE = re.compile(
    r"^\s*(SUCCEEDED|INCOMPLETE|FAILED|IGNORED|FILES CAPTURED|LINES OF CODE)"
    r"\s*:\s*(\d+)\s*$", re.M)

SECTION_RE = re.compile(
    r"^(Files not in any module|Captured files not found on disk|"
    r"Captured files outside of the project directory)$", re.M)

# Per-file row:  <path>  Succeeded   2
#                <path>  Incomplete  10   Recoverable Errors
# The Notes column is the function-level signal and is easy to lose.
LIST_ROW_RE = re.compile(
    r"^\s+(?P<path>\S.*?)\s+"
    r"(?P<status>Succeeded|Incomplete|Failed|Ignored)"
    r"(?:\s+(?P<lines>\d+))?"
    r"(?:\s+(?P<notes>\S.*?))?\s*$")

# cov-emit names the function it dropped.  This is the only signal that says
# WHICH function is missing, which is why capture logs are worth keeping.
NOT_EMITTED_RE = re.compile(
    r'"(?P<file>[^"\n]+)",\s*line\s*(?P<line>\d+):\s*warning\s*#1563:\s*'
    r'function\s*"(?P<function>[^"\n]+)"\s*not emitted')

RECOVERABLE_IN_FILE_RE = re.compile(
    r'\[WARNING\]\s*(?P<count>\d+)\s+recoverable errors? detected in the '
    r'compilation of\s*"(?P<file>[^"\n]+)"')

RECOVERABLE_BUILD_RE = re.compile(
    r'\[WARNING\]\s*Recoverable errors were encountered during\s+'
    r'(?P<count>\d+)\s+of these')

SUMMARY_TXT_RE = re.compile(
    r"^(Files analyzed|Total LoC input to cov-analyze|Functions analyzed|"
    r"Paths analyzed)\s*:\s*(\d+)", re.M)


def parse_coverity_list(text):
    """Pull the summary counts, per-file rows, and diagnostic sections."""
    summary = {}
    for m in CAPTURE_SUMMARY_RE.finditer(text):
        summary[m.group(1).lower().replace(" ", "_")] = int(m.group(2))

    rows = []
    for line in text.splitlines():
        if line.lstrip().startswith("Filename"):
            continue                       # column header
        m = LIST_ROW_RE.match(line)
        if not m:
            continue
        notes = (m.group("notes") or "").strip()
        rows.append({
            "path": norm(m.group("path")),
            "raw_path": m.group("path"),
            "status": m.group("status"),
            "code_lines": int(m.group("lines")) if m.group("lines") else None,
            "notes": notes,
        })

    sections = {}
    marks = [(m.start(), m.group(1)) for m in SECTION_RE.finditer(text)]
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[pos + len(name):end]
        stop = re.search(r"^End " + re.escape(name), body, re.M | re.I)
        if stop:
            body = body[:stop.start()]
        srows = []
        for line in body.splitlines():
            line = line.strip()
            if (not line or line.startswith("=") or line.startswith("End ")
                    or line.startswith("File family:")
                    or line.startswith("File type:")
                    or line.startswith("Filename")
                    or line.startswith("Capture summary")):
                continue
            srows.append(line)
        sections[name] = srows
    return summary, sections, rows


def scan_capture_logs(idir):
    """Find function-level capture loss in the capture logs.

    A translation unit can emit, carry ASTs, report capture-percentage 100 and
    still be missing individual functions that failed to parse.  The log is the
    only place the dropped function is named.
    """
    out = {"functions_not_emitted": [], "recoverable_errors_by_file": {},
           "build_level_recoverable_tus": None, "logs_read": []}
    candidates = [
        os.path.join(idir, "build-log.txt"),
        os.path.join(idir, "capture-files-log.txt"),
        os.path.join(idir, "coverity-cli", "coverity-cli-log.txt"),
    ]
    seen = set()
    for path in candidates:
        if not os.path.isfile(path):
            continue
        out["logs_read"].append(os.path.basename(path))
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:                      # streamed: logs get big
                    m = NOT_EMITTED_RE.search(line)
                    if m:
                        key = (m.group("file"), m.group("line"),
                               m.group("function"))
                        if key not in seen:
                            seen.add(key)
                            out["functions_not_emitted"].append({
                                "file": m.group("file"),
                                "line": int(m.group("line")),
                                "function": m.group("function"),
                            })
                    m = RECOVERABLE_IN_FILE_RE.search(line)
                    if m:
                        out["recoverable_errors_by_file"][m.group("file")] = \
                            int(m.group("count"))
                    m = RECOVERABLE_BUILD_RE.search(line)
                    if m:
                        out["build_level_recoverable_tus"] = int(m.group("count"))
        except OSError as e:
            out.setdefault("errors", []).append("%s: %s" % (path, e))
    return out


def parse_analysis_summary(idir):
    """Function-level denominator from cov-analyze, when analysis has run."""
    path = os.path.join(idir, "output", "summary.txt")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    got = {m.group(1).lower().replace(" ", "_").replace("-", "_"): int(m.group(2))
           for m in SUMMARY_TXT_RE.finditer(text)}
    return got or None


def cmd_method_a(args):
    bindir = args.bin
    idir = os.path.abspath(args.dir)
    out = {"method": "A", "idir": norm(idir), "sources": {}}

    # A2 -- the machine-readable inventory.  Preferred.
    rc, so, se = run([tool(bindir, "cov-manage-emit"),
                      "--dir", idir, "list-capture-diagnostics"])
    diag = first_json(so) if rc == 0 else None
    out["sources"]["list-capture-diagnostics"] = {
        "rc": rc, "ok": diag is not None,
        "format_version": (diag or {}).get("format_version"),
        "stderr": se.strip()[:2000],
    }

    captured = []
    if diag:
        for f in diag.get("captured-files", []):
            tu = f.get("translation-unit") or {}
            captured.append({
                "path": norm(f.get("file-path")),
                "language": tu.get("source-language"),
                "capture_percentage": tu.get("capture-percentage"),
                "had_failures": tu.get("had-failures"),
                "had_recoverable_errors": tu.get("had-recoverable-errors"),
                "has_asts": tu.get("had-abstract-syntax-trees"),
                "code_lines": f.get("code-line-count"),
            })

    # A3 -- list-json, as a fallback and for the hashes.
    rc2, so2, se2 = run([tool(bindir, "cov-manage-emit"),
                         "--dir", idir, "list-json"])
    lj = first_json(so2) if rc2 == 0 else None
    out["sources"]["list-json"] = {"rc": rc2, "ok": lj is not None,
                                   "stderr": se2.strip()[:2000]}
    hashes = {}
    if isinstance(lj, list):
        for tu in lj:
            p = norm(tu.get("primaryFilename"))
            hashes[p] = tu.get("primaryFileHash")
            if not captured:  # degraded path: build the inventory from here
                captured.append({
                    "path": p,
                    "language": tu.get("language"),
                    "capture_percentage": tu.get("astFidelityPercent"),
                    "had_failures": tu.get("isFailure"),
                    "had_recoverable_errors": tu.get("hadRecoverableErrors"),
                    "has_asts": tu.get("hasASTs"),
                    "code_lines": None,
                })
    for c in captured:
        c["md5"] = hashes.get(c["path"])

    # A3 -- invocations: metrics and link units.
    rc3, so3, se3 = run([tool(bindir, "cov-manage-emit"), "--dir", idir,
                         "list-capture-invocations", "--no-process-details"])
    inv = first_json(so3) if rc3 == 0 else None
    out["sources"]["list-capture-invocations"] = {
        "rc": rc3, "ok": inv is not None, "stderr": se3.strip()[:2000]}
    if inv:
        out["metrics"] = inv.get("metrics", {})
        fid = {f.get("id"): norm(f.get("case-preserved") or
                                 f.get("case-normalized"))
               for f in inv.get("files", [])}
        lus = []
        for lu in inv.get("link-units", []):
            lus.append({
                "kind": lu.get("kind"),
                "primary": fid.get(lu.get("primary-file-id")),
                "emit_failed": lu.get("emit-failed"),
                "inputs": [
                    {"path": fid.get(i.get("file-id")), "kind": i.get("kind")}
                    for i in lu.get("input-files", [])
                ],
            })
        out["link_units"] = lus

    # A5 -- the CLI's own diagnostics, when capture went through `coverity`.
    # Authoritative for the build command, capture rate, and config hash.
    cd_path = os.path.join(idir, "output", "cli-diagnostics.json")
    if os.path.isfile(cd_path):
        try:
            cd = load_json(cd_path)
        except (OSError, ValueError) as e:
            out["sources"]["cli-diagnostics"] = {"ok": False, "error": str(e)}
        else:
            cap = cd.get("capture", {})
            eff = (cap.get("configuration", {})
                      .get("effective-configuration", {}))
            out["sources"]["cli-diagnostics"] = {"ok": True,
                                                 "version": cd.get("version")}
            out["cli_diagnostics"] = {
                "primary_capture_mode": cap.get("primary-capture-mode"),
                "capture_rate": cap.get("capture-rate"),
                "capture_summary": cap.get("capture-summary"),
                "build_command": (eff.get("capture", {})
                                     .get("build", {})
                                     .get("build-command")),
                "project_directory": cap.get("project-directory"),
                "configuration_hash": (cap.get("configuration", {})
                                          .get("configuration-hash")),
                "analysis_ran": "analysis" in cd,
            }

    # A1 -- coverity list, for the project-directory denominator.
    if args.project_dir:
        cmd = [tool(bindir, "coverity"), "list",
               "--project-dir", os.path.abspath(args.project_dir),
               "--dir", idir]
        if not args.no_all:
            cmd.append("--all")
        rc4, so4, se4 = run(cmd)
        summary, sections, rows = parse_coverity_list(so4 + "\n" + se4)
        out["sources"]["coverity-list"] = {
            "rc": rc4, "ok": bool(summary), "command": cmd,
            "used_all_flag": not args.no_all,
        }
        out["coverity_list_summary"] = summary
        out["coverity_list_sections"] = sections
        out["coverity_list_rows"] = rows
        # `Incomplete` + Notes "Recoverable Errors" is the documented
        # function-level signal, and the one to prefer when it disagrees with
        # the per-TU percentage.
        out["coverity_list_incomplete"] = [
            r for r in rows if r["status"] == "Incomplete"]
        out["coverity_list_failed"] = [
            r for r in rows if r["status"] == "Failed"]
        if args.keep_raw:
            out["coverity_list_raw"] = so4

    # Function-level capture loss: named functions from the capture logs, and
    # cov-analyze's function count if analysis has run.
    out["capture_log"] = scan_capture_logs(idir)
    asum = parse_analysis_summary(idir)
    if asum:
        out["analysis_summary"] = asum

    out["captured"] = sorted(captured, key=lambda d: d["path"] or "")
    out["captured_count"] = len(captured)

    # Three states, not two.  A TU with recoverable errors IS analyzed -- it
    # is simply missing functions -- so it must not be counted as unusable,
    # and must not be counted as clean either.
    unusable, partial = [], []
    for c in captured:
        if c.get("has_asts") is False or c.get("had_failures"):
            unusable.append(c["path"])
        elif (c.get("had_recoverable_errors")
              or (c.get("capture_percentage") is not None
                  and c["capture_percentage"] < 100)):
            partial.append(c["path"])
    # A file can be flagged Incomplete by `coverity list` -- the documented
    # signal -- so honour it even if the per-TU fields look clean.
    by_tail = {}
    for c in captured:
        by_tail.setdefault((c["path"] or "").split("/")[-1], []).append(c["path"])
    for r in out.get("coverity_list_incomplete", []):
        cands = by_tail.get(r["path"].split("/")[-1], [])
        for p in cands:
            if p not in partial and p not in unusable:
                partial.append(p)

    out["unusable"] = sorted(unusable)
    out["partial"] = sorted(partial)
    out["complete_count"] = len(captured) - len(unusable) - len(partial)
    out["analyzable_count"] = len(captured) - len(unusable)
    # Kept for compatibility: everything that is not fully clean.
    out["degraded"] = sorted(set(unusable) | set(partial))

    write_json(args.out, out)
    nfn = len(out["capture_log"]["functions_not_emitted"])
    print("captured %d TU records: %d complete, %d partial, %d unusable; "
          "%d function(s) named as not emitted"
          % (len(captured), out["complete_count"], len(partial),
             len(unusable), nfn), file=sys.stderr)
    return 0


# --------------------------------------------------------------------------
# Method B: scan transparency


def cmd_method_b(args):
    idir = os.path.abspath(args.dir)
    st = os.path.join(idir, "scan-transparency")
    out = {"method": "B", "idir": norm(idir),
           "scan_transparency_dir": norm(st),
           "directory_present": os.path.isdir(st),
           "files": {}, "unconfigured_compilers": [],
           "cli_ignored_files": [], "capture_path": None}

    if not out["directory_present"]:
        # Absence is not a pass.  Say so loudly and refuse to imply otherwise.
        out["verdict"] = "NOT_RUN"
        out["note"] = ("No scan-transparency directory. Method B did not run "
                       "-- this is NOT a clean result. Capture may have used "
                       "--disable-scan-transparency-data, or the Coverity "
                       "version predates it.")
        write_json(args.out, out)
        print("scan-transparency ABSENT -- method B unavailable",
              file=sys.stderr)
        return 0

    for fn in sorted(os.listdir(st)):
        p = os.path.join(st, fn)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                body = f.read()
        except OSError as e:
            out["files"][fn] = {"error": str(e)}
            continue
        lines = [l.strip() for l in body.splitlines() if l.strip()]
        out["files"][fn] = {"size": os.path.getsize(p), "lines": len(lines)}
        if fn == "unconfigured-compilers":
            out["unconfigured_compilers"] = lines
        elif fn == "cli-ignored-files":
            out["cli_ignored_files"] = lines

    # A non-existent path in unconfigured-compilers is an artifact, not a
    # finding: measured on 2026.6.0, a fully successful `coverity capture`
    # listed "<project-dir>\gcc", a path that never existed, apparently from
    # resolving the bare command name against the project directory.
    real, phantom = [], []
    for entry in out["unconfigured_compilers"]:
        (real if os.path.exists(entry) else phantom).append(entry)
    out["unconfigured_compilers_existing"] = real
    out["unconfigured_compilers_phantom"] = phantom

    # The CLI capture path writes cli-ignored-files; cov-build does not.  The
    # absence of that file is structural, not a clean bill of health.
    out["capture_path"] = ("coverity-cli" if "cli-ignored-files" in out["files"]
                           else "cov-build-or-unknown")

    n, nreal, nphantom = (len(out["unconfigured_compilers"]),
                          len(real), len(phantom))
    if n == 0:
        out["verdict"] = "CLEAN"
    elif nreal == 0:
        out["verdict"] = "UNCONFIGURED_COMPILERS_PHANTOM_ONLY"
    else:
        out["verdict"] = "UNCONFIGURED_COMPILERS"

    notes = []
    if n == 0:
        notes.append("No compiler-shaped binary escaped configuration. This "
                     "does NOT establish that anything was captured.")
    else:
        if nreal:
            notes.append(
                "%d existing binary/binaries ran as compilers without "
                "configuration; each is a candidate capture hole. See "
                "coverity-compiler-configuration." % nreal)
        if nphantom:
            notes.append(
                "%d listed path(s) do not exist on disk and are probably "
                "artifacts of resolving a bare command name against the "
                "project directory, not real holes. Confirm against Method A "
                "before reporting: a fully successful capture has been "
                "observed listing a phantom entry." % nphantom)
    if out["capture_path"] == "coverity-cli":
        notes.append(
            "CLI capture path: cli-ignored-files lists %d project file(s) the "
            "CLI knew about and did not capture. It mixes genuine misses with "
            "expected ones (.o, .exe) -- partition before reporting."
            % len(out["cli_ignored_files"]))
    else:
        notes.append(
            "No cli-ignored-files: this looks like a cov-build capture, which "
            "does not write one. Its absence is structural, not evidence that "
            "nothing was skipped -- that evidence must come from Method A.")
    notes.append(
        "scan-transparency is written at CAPTURE time; analysis does not add "
        "to it, and nothing needs committing to Connect.")
    out["note"] = " ".join(notes)
    write_json(args.out, out)
    print("scan-transparency: %s (%d unconfigured)" % (out["verdict"], n),
          file=sys.stderr)
    return 0


# --------------------------------------------------------------------------
# Adjudication


def cmd_adjudicate(args):
    c = load_json(args.expected)
    a = load_json(args.inventory)
    b = load_json(args.transparency)

    if not c.get("reviewed"):
        print("WARNING: method-c file is still an unreviewed scaffold; the "
              "expectation has not been formed by judgment.", file=sys.stderr)

    expect, exclude = {}, {}
    for f in c.get("files", []):
        d = (f.get("decision") or "").upper()
        key = norm(f.get("abs") or f.get("path"))
        if d == "EXPECT":
            expect[key] = f
        elif d == "EXCLUDE":
            exclude[key] = f

    cap = {x["path"]: x for x in a.get("captured", []) if x.get("path")}

    # Compare on basename when the expectation is relative to a project dir
    # and the capture records absolute paths under a different root.
    def tail(p, n=3):
        return "/".join(p.split("/")[-n:])

    cap_tails = {}
    for p in cap:
        cap_tails.setdefault(tail(p), []).append(p)

    matched, missing = {}, []
    for k, f in expect.items():
        if k in cap:
            matched[k] = cap[k]
            continue
        cands = cap_tails.get(tail(k)) or cap_tails.get(tail(k, 2)) or []
        if len(cands) == 1:
            matched[k] = cap[cands[0]]
        else:
            missing.append(f.get("path") or k)

    matched_caps = {v["path"] for v in matched.values()}
    surplus = [p for p in cap if p not in matched_caps]

    n_exp, n_cap = len(expect), len(cap)
    n_missing, n_surplus = len(missing), len(surplus)
    degraded = a.get("degraded", [])
    unusable = a.get("unusable", degraded)
    partial = a.get("partial", [])
    # Partial TUs are analyzed, with functions missing.  Only unusable ones
    # drop out of the analysis entirely.
    analyzable = a.get("analyzable_count", n_cap - len(unusable))
    complete = a.get("complete_count", analyzable - len(partial))
    lost_functions = (a.get("capture_log", {}) or {}).get(
        "functions_not_emitted", [])
    asum = a.get("analysis_summary") or {}
    unconf = b.get("unconfigured_compilers", [])
    sections = a.get("coverity_list_sections", {})
    notfound = sections.get("Captured files not found on disk", [])
    outside = sections.get("Captured files outside of the project directory", [])

    # Grade.  Order matters: the worst true statement wins.
    if n_cap == 0 or (n_exp and n_cap < max(1, n_exp * 0.1)):
        grade, why = "VACUOUS", (
            "Essentially nothing was captured. A no-op incremental build, a "
            "build delegating to a persistent daemon or compile server, or "
            "--record-only without --replay. Never report this as a pass.")
    elif notfound:
        grade, why = "INDETERMINATE", (
            "The emit database references %d source file(s) not present on "
            "disk: stale intermediate directory, cleaned generated code, or "
            "path drift. Distrust the idir until this is explained."
            % len(notfound))
    elif n_missing and b.get("unconfigured_compilers_existing", unconf):
        n_real = len(b.get("unconfigured_compilers_existing", unconf))
        n_ghost = len(b.get("unconfigured_compilers_phantom", []))
        grade, why = "SHORTFALL", (
            "%d expected source(s) not captured, and %d unconfigured "
            "compiler(s) that exist on disk. Route to "
            "coverity-compiler-configuration.%s"
            % (n_missing, n_real,
               " (%d further entr%s named a path that does not exist and "
               "%s disregarded.)" % (n_ghost, "y" if n_ghost == 1 else "ies",
                                     "was" if n_ghost == 1 else "were")
               if n_ghost else ""))
    elif n_missing:
        grade, why = "SHORTFALL", (
            "%d expected source(s) not captured with no unconfigured "
            "compiler to explain it. The build most likely never compiled "
            "them: incremental build, compiler-cache hits, wrong target, or "
            "an early failure the build continued past. Clean and "
            "re-capture." % n_missing)
    elif unusable or partial:
        grade = "DEGRADED"
        bits = []
        if unusable:
            bits.append("%d translation unit(s) captured but NOT analyzable "
                        "at all (no AST, or the emit failed)." % len(unusable))
        if partial:
            bits.append(
                "%d translation unit(s) parsed only partially: they ARE "
                "analyzed, but individual functions that failed to parse were "
                "never emitted, so no defect in them can be reported. Capture "
                "is not all-or-nothing, and the per-TU percentage does not say "
                "so -- a file can read capture-percentage 100 and still be "
                "missing a function." % len(partial))
        if lost_functions:
            bits.append("%d function(s) are named in the capture log as not "
                        "emitted." % len(lost_functions))
        why = " ".join(bits)
    elif n_surplus:
        grade, why = "SURPLUS", (
            "%d captured file(s) beyond the expectation -- normally build "
            "probes, tests, generated or third-party sources. Benign, but "
            "name them." % n_surplus)
    elif exclude:
        grade, why = "CONSISTENT_WITH_EXCLUSIONS", (
            "Capture matches the expectation once %d named exclusion(s) are "
            "applied." % len(exclude))
    else:
        grade, why = "CONSISTENT", (
            "All three methods agree; capture covers the expected set.")

    # A SHORTFALL that also has partial parses must say so: fixing the missing
    # files would otherwise look like the whole job.
    if grade == "SHORTFALL" and (partial or lost_functions):
        why += (" Additionally, %d captured TU(s) parsed only partially%s -- "
                "file-level completeness would not have been the whole story."
                % (len(partial),
                   " and %d function(s) are named as not emitted"
                   % len(lost_functions) if lost_functions else ""))

    result = {
        "grade": grade,
        "rationale": why,
        "counts": {"expected": n_exp, "captured": n_cap,
                   "analyzable": analyzable, "complete": complete,
                   "partial": len(partial), "unusable": len(unusable)},
        "functions_not_emitted": lost_functions,
        "analysis_summary": asum,
        "method_c_reviewed": bool(c.get("reviewed")),
        "missing": sorted(missing),
        "surplus": sorted(surplus),
        "degraded": sorted(degraded),
        "unconfigured_compilers": unconf,
        "captured_files_not_found_on_disk": notfound,
        "captured_files_outside_project_dir": outside,
        "exclusions": [{"path": f.get("path"), "reason": f.get("reason")}
                       for f in exclude.values()],
        "coverity_list_summary": a.get("coverity_list_summary", {}),
        "emit_metrics": a.get("metrics", {}),
        "method_b_verdict": b.get("verdict"),
    }

    if args.json_out:
        write_json(args.json_out, result)

    L = []
    L.append("# Capture fidelity: %s" % grade)
    L.append("")
    L.append("expected %d product sources / captured %d / analyzable %d / "
             "fully parsed %d" % (n_exp, n_cap, analyzable, complete))
    if asum.get("functions_analyzed") is not None:
        L.append("")
        L.append("cov-analyze reports **%d functions analyzed**%s. A function "
                 "count is a denominator too -- compare it against what the "
                 "sources define."
                 % (asum["functions_analyzed"],
                    " across %d files" % asum["files_analyzed"]
                    if asum.get("files_analyzed") is not None else ""))
    L.append("")
    L.append(why)
    L.append("")
    L.append("## Method agreement")
    L.append("")
    L.append("| Method | Result |")
    L.append("|---|---|")
    L.append("| C -- expectation | %d expected, %d excluded%s |"
             % (n_exp, len(exclude),
                "" if c.get("reviewed") else " (**UNREVIEWED SCAFFOLD**)"))
    L.append("| A -- capture inventory | %d captured: %d complete, %d partial, "
             "%d unusable |" % (n_cap, complete, len(partial), len(unusable)))
    L.append("| B -- scan transparency | %s (%s) |"
             % (b.get("verdict") or "?", b.get("capture_path") or "?"))
    L.append("")
    if b.get("verdict") == "NOT_RUN":
        L.append("> Method B did not run. A missing scan-transparency "
                 "directory is not a clean result.")
        L.append("")
    if outside:
        L.append("> %d captured file(s) lie outside the project directory, so "
                 "the project-directory denominator did not cover the whole "
                 "captured set: the SUCCEEDED/IGNORED counts below are not "
                 "directly comparable to the tree. Check --project-dir, an "
                 "out-of-tree build, or an idir captured under another root."
                 % len(outside))
        L.append("")
    for title, rows in (("Expected but not captured", sorted(missing)),
                        ("Captured but not expected", sorted(surplus)),
                        ("Captured but NOT analyzable at all", sorted(unusable)),
                        ("Captured but only partially parsed — analyzed with "
                         "functions missing", sorted(partial)),
                        ("Unconfigured compilers (exist on disk)",
                         b.get("unconfigured_compilers_existing", unconf)),
                        ("Unconfigured-compiler entries that do NOT exist "
                         "(probable artifacts, not holes)",
                         b.get("unconfigured_compilers_phantom", [])),
                        ("CLI-ignored project files (partition before "
                         "reporting)", b.get("cli_ignored_files", [])),
                        ("Captured files not found on disk", notfound),
                        ("Captured files outside the project directory",
                         outside)):
        if rows:
            L.append("## %s (%d)" % (title, len(rows)))
            L.append("")
            for r in rows[:args.max_rows]:
                L.append("- `%s`" % r)
            if len(rows) > args.max_rows:
                L.append("- ... and %d more" % (len(rows) - args.max_rows))
            L.append("")
    if lost_functions:
        L.append("## Functions not emitted (%d)" % len(lost_functions))
        L.append("")
        L.append("Named by the capture log — the only source that says *which* "
                 "function was lost. Each was skipped by the front end after a "
                 "parse error, is absent from the analysis, and takes its "
                 "interprocedural contribution to its callers with it.")
        L.append("")
        for fn in lost_functions[:args.max_rows]:
            L.append("- `%s` at `%s:%d`"
                     % (fn.get("function"), fn.get("file"), fn.get("line", 0)))
        if len(lost_functions) > args.max_rows:
            L.append("- ... and %d more"
                     % (len(lost_functions) - args.max_rows))
        L.append("")
        L.append("Fix the parse error — usually a missing include, define, or "
                 "compiler-compat detail — or model the function deliberately.")
        L.append("")
    elif partial:
        L.append("## Functions not emitted")
        L.append("")
        L.append("**Not determined.** Translation units are flagged as "
                 "partially parsed, but no `#1563` warning was found in the "
                 "capture logs%s. The dropped functions are named only there, "
                 "so keep capture logs; without them the loss is known to "
                 "exist but not localized."
                 % ("" if (a.get("capture_log", {}) or {}).get("logs_read")
                    else " (no capture log was present in the idir)"))
        L.append("")

    if exclude:
        L.append("## Exclusions applied (%d)" % len(exclude))
        L.append("")
        L.append("Echoed in full on every run; exclusions are never silent.")
        L.append("")
        for f in exclude.values():
            L.append("- `%s` -- %s" % (f.get("path"),
                                       f.get("reason") or "NO REASON GIVEN"))
        L.append("")
    L.append("## Scope")
    L.append("")
    L.append("This measures capture only: files on disk -> compiled -> "
             "emitted -> analyzable. It does not establish that the analysis "
             "was complete, that the right checkers ran, or that the build "
             "produced correct binaries.")
    L.append("")
    L.append("Counts are per file. A file counted as captured may still be "
             "missing individual functions; the *fully parsed* figure and the "
             "functions-not-emitted list above are what speak to that.")
    L.append("")

    text = "\n".join(L)
    if args.out and args.out != "-":
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote %s" % args.out, file=sys.stderr)
    else:
        print(text)
    print("GRADE: %s" % grade, file=sys.stderr)
    return 0


# --------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("expect", help="Method C scaffold from the source tree")
    p.add_argument("--project-dir", required=True)
    p.add_argument("-o", "--out", default="method-c-expected.json")
    p.set_defaults(func=cmd_expect)

    p = sub.add_parser("method-a", help="capture inventory from the idir")
    p.add_argument("--bin", required=True, help="<coverity-install>/bin")
    p.add_argument("--dir", required=True, help="intermediate directory")
    p.add_argument("--project-dir", help="enables the coverity list arm")
    p.add_argument("--no-all", action="store_true",
                   help="omit --all from coverity list (not recommended)")
    p.add_argument("--keep-raw", action="store_true")
    p.add_argument("-o", "--out", default="method-a-inventory.json")
    p.set_defaults(func=cmd_method_a)

    p = sub.add_parser("method-b", help="scan-transparency readout")
    p.add_argument("--dir", required=True)
    p.add_argument("-o", "--out", default="method-b-transparency.json")
    p.set_defaults(func=cmd_method_b)

    p = sub.add_parser("adjudicate", help="compare the three frozen results")
    p.add_argument("-c", "--expected", default="method-c-expected.json")
    p.add_argument("-a", "--inventory", default="method-a-inventory.json")
    p.add_argument("-b", "--transparency", default="method-b-transparency.json")
    p.add_argument("-o", "--out", default="adjudication.md")
    p.add_argument("--json-out")
    p.add_argument("--max-rows", type=int, default=50)
    p.set_defaults(func=cmd_adjudicate)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
