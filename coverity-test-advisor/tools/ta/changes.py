"""Changed functions (S0): git diff hunks mapped onto the functions that contain them.

Function extents come from the idir's `output/FUNCTION.metrics.xml.gz`: `ml` is the first line and `lc` the line
count, so a function spans ml to ml + lc - 1 (checked against gcov's start_line and end_line).
"""
import collections
import gzip
import re
import subprocess

FN_RE = re.compile(r"<fnmetric>\s*<file>(.*?)</file>\s*<names><!\[CDATA\[(.*?)\]\]></names>\s*"
                   r"<metrics>(.*?)</metrics>", re.S)
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class Fn:
    def __init__(self, file, name, start, end):
        self.file, self.name, self.start, self.end = file, name, start, end

    @property
    def fid(self):
        return f"{self.file}:{self.name}"

    def __repr__(self):
        return f"{self.fid}@{self.start}-{self.end}"


def rel(path, roots):
    for r in roots:
        r = r.rstrip("/") + "/"
        if path.startswith(r):
            return path[len(r):]
    return path


def functions(idir, roots):
    """Every function the analysis measured, with repo-relative files."""
    text = gzip.open(f"{idir}/output/FUNCTION.metrics.xml.gz", "rt").read()
    out = []
    for file, names, metrics in FN_RE.findall(text):
        name = re.search(r"fn:([^;]+);", names)
        m = dict(kv.split(":", 1) for kv in metrics.split(";") if ":" in kv)
        if name and "ml" in m and "lc" in m:
            start = int(m["ml"])
            out.append(Fn(rel(file, roots), name[1], start, start + int(m["lc"]) - 1))
    return out


def hunks(clone, base_sha, head_sha, paths=("src",)):
    """{file: [hunk]}, each hunk with its head lines added or changed, the head line after which lines were
    deleted (for a pure deletion), and its text."""
    out = subprocess.run(["git", "-C", clone, "diff", "-U0", "--no-color", base_sha, head_sha, "--", *paths],
                         check=True, capture_output=True, text=True).stdout
    files, cur, hunk = collections.defaultdict(list), None, None
    for line in out.splitlines():
        if line.startswith("+++ "):
            cur = None if line == "+++ /dev/null" else line[6:]
            continue
        m = HUNK_RE.match(line)
        if m and cur:
            c, d = int(m[3]), int(m[4]) if m[4] is not None else 1
            hunk = {"head_lines": list(range(c, c + d)), "deleted_after": c if d == 0 else None,
                    "base_start": int(m[1]), "text": [line]}
            files[cur].append(hunk)
            continue
        if hunk is not None and line[:1] in "+- ":
            hunk["text"].append(line)
    return dict(files)


def changed_functions(head_fns, base_fns, file_hunks):
    """S0 as {fid: {"fn", "kind", "lines", "hunks"}}; `lines` are the function's head lines the diff added or
    changed, or the line next to a pure deletion."""
    base_ids = {f.fid for f in base_fns}
    s0 = {}
    for f in head_fns:
        mine, lines = [], set()
        for h in file_hunks.get(f.file, []):
            touched = [n for n in h["head_lines"] if f.start <= n <= f.end]
            near = h["deleted_after"]
            if touched or (near is not None and f.start <= near <= f.end):
                mine.append(h)
                lines.update(touched or [near])
        if mine:
            s0[f.fid] = {"fn": f, "kind": "body" if f.fid in base_ids else "new", "lines": sorted(lines),
                         "hunks": mine}
    removed = sorted(f.fid for f in base_fns if f.fid not in {g.fid for g in head_fns})
    return s0, removed


def _code(text):
    t = text.strip()
    return bool(t) and not t.startswith(("//", "/*", "*", "*/"))  # a changed #define is a change; keep it


def unmapped(head_fns, file_hunks, source=None):
    """Changed lines that no analysed function contains, so no model, call graph or verdict covers them:
    [{"file", "lines", "kind"}], kind "no analysed function in this file" (not compiled, not source, or no function
    bodies, such as a header of declarations) or "outside any function" (declarations, fields, macros, initializers).
    With `source(file) -> lines`, blank and comment lines are left out (a changed #define stays). The report lists
    the rest instead of dropping them: this is where a capture that missed a changed file shows."""
    by_file = {}
    for f in head_fns:
        by_file.setdefault(f.file, []).append((f.start, f.end))
    out = []
    for file, hs in sorted(file_hunks.items()):
        spans = by_file.get(file, [])
        lines = set()
        for h in hs:
            for n in h["head_lines"] or [h["deleted_after"]]:
                if n is not None and not any(a <= n <= b for a, b in spans):
                    lines.add(n)
        if source and lines:
            text = source(file)
            lines = {n for n in lines if text is None or (0 < n <= len(text) and _code(text[n - 1]))}
        if lines:
            out.append({"file": file, "lines": sorted(lines),
                        "kind": "outside any function" if spans else "no analysed function in this file"})
    return out
