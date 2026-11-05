"""Coverage from gcov's JSON (`gcov --json-format --conditions`, format_version 2).

Files are keyed by their path relative to the repo root: gcov's path joined to its working directory, with the
coverage root stripped. A source compiled into several objects (a header) is summed line by line.
"""
import collections
import glob
import gzip
import json
import os
import xml.etree.ElementTree as ET


class Cov:
    def __init__(self, counts=True):
        self.counts = counts  # False: "count" is 1 or 0 (ran or not), as JaCoCo gives it; gcov gives real counts
        self.lines = collections.defaultdict(dict)      # file -> line -> {"count", "branches", "conditions"}
        self.functions = collections.defaultdict(dict)  # file -> name -> {"start", "end", "count"}

    def has(self, file):
        return file in self.lines

    def count(self, file, line):
        rec = self.lines.get(file, {}).get(line)
        return None if rec is None else rec["count"]


def load(json_dir, coverage_root):
    cov = Cov()
    root = coverage_root.rstrip("/") + "/"
    paths = glob.glob(f"{json_dir}/**/*.gcov.json.gz", recursive=True) +         glob.glob(f"{json_dir}/**/*.gcov.json", recursive=True)
    for path in paths:
        d = json.load(gzip.open(path) if path.endswith(".gz") else open(path))
        cwd = d.get("current_working_directory", "")
        for f in d["files"]:
            full = os.path.normpath(os.path.join(cwd, f["file"]))
            if not full.startswith(root):
                continue
            file = full[len(root):]
            for fn in f.get("functions", []):
                prev = cov.functions[file].get(fn["name"])
                count = fn["execution_count"] + (prev["count"] if prev else 0)
                cov.functions[file][fn["name"]] = {"start": fn["start_line"], "end": fn["end_line"], "count": count}
            for ln in f["lines"]:
                n = ln["line_number"]
                rec = cov.lines[file].get(n)
                if rec is None:
                    cov.lines[file][n] = {"count": ln["count"], "branches": [b["count"] for b in ln["branches"]],
                                          "conditions": ln.get("conditions", [])}
                else:
                    rec["count"] += ln["count"]
                    rec["branches"] = [a + b["count"] for a, b in zip(rec["branches"], ln["branches"])]
    return cov


def load_per_test(per_test_dir, coverage_root):
    """{unit: Cov} for a per-test directory: one subdirectory per unit, each with its own json/."""
    out = {}
    for unit_json in sorted(glob.glob(f"{per_test_dir}/*/json")):
        out[os.path.basename(os.path.dirname(unit_json))] = load(unit_json, coverage_root)
    return out


JVM_PRIMITIVES = dict(B="byte", C="char", D="double", F="float", I="int", J="long", S="short", Z="boolean", V="void")


def jvm_type(desc, i):
    dims = 0
    while desc[i] == "[":
        dims, i = dims + 1, i + 1
    if desc[i] == "L":
        j = desc.index(";", i)
        return desc[i + 1:j].replace("/", ".") + "[]" * dims, j + 1
    return JVM_PRIMITIVES[desc[i]] + "[]" * dims, i + 1


def jvm_name(cls, name, desc):
    """Coverity's function name (no return type) for JaCoCo's class (a/b/C$D), method name and JVM descriptor:
    parseInt([CII)I of tools/jackson/core/io/NumberInput becomes tools.jackson.core.io.NumberInput.parseInt(char[], int, int)."""
    i, args = 1, []
    while desc[i] != ")":
        t, i = jvm_type(desc, i)
        args.append(t)
    return f"{cls.replace('/', '.')}.{name}({', '.join(args)})"


def load_jacoco(xml_path, source_root="src/main/java"):
    """Coverage from a JaCoCo XML report (`jacococli report --xml`). Same shape as `load`, without
    counts: a line's "count" is 1 if any of its instructions ran and 0 if none did; "branches" has one 1 per covered
    and one 0 per missed branch (JaCoCo reports the two totals, not which arc); no "conditions". A line JaCoCo does not
    list has no executable code. A method's "count" is 1 if it ran (its "start" is its first executable line; there is
    no end line). Files are <source_root>/<package path>/<source file>.
    """
    cov = Cov(counts=False)
    for pkg in ET.parse(xml_path).getroot().iter("package"):
        pdir = pkg.get("name")
        for cl in pkg.findall("class"):
            file = f"{source_root}/{pdir}/{cl.get('sourcefilename')}"
            for m in cl.findall("method"):
                ran = any(c.get("type") == "METHOD" and int(c.get("covered")) > 0 for c in m.findall("counter"))
                name = jvm_name(cl.get("name"), m.get("name"), m.get("desc"))
                prev = cov.functions[file].get(name)
                cov.functions[file][name] = {"start": int(m.get("line", 0)), "end": None,
                                             "count": int(ran) + (prev["count"] if prev else 0)}
        for sf in pkg.findall("sourcefile"):
            file = f"{source_root}/{pdir}/{sf.get('name')}"
            for ln in sf.findall("line"):
                cb, mb = int(ln.get("cb")), int(ln.get("mb"))
                cov.lines[file][int(ln.get("nr"))] = {"count": int(int(ln.get("ci")) > 0),
                                                      "branches": [1] * cb + [0] * mb, "conditions": []}
    return cov


def load_per_test_jacoco(per_test_dir, source_root="src/main/java"):
    """{unit: Cov} for a directory of per-test-class JaCoCo XML reports (<unit>.xml)."""
    return {os.path.basename(p)[:-4]: load_jacoco(p, source_root) for p in sorted(glob.glob(f"{per_test_dir}/*.xml"))}


def condition_text(c):
    """gcov's own wording for one line's condition record."""
    s = f"condition outcomes covered {c['covered']}/{c['count']}"
    missing = []
    for i in sorted(set(c["not_covered_true"]) | set(c["not_covered_false"])):
        which = [w for w, lst in (("true", c["not_covered_true"]), ("false", c["not_covered_false"])) if i in lst]
        missing.append(f"condition {i} not covered ({' '.join(which)})")
    return "; ".join([s] + missing)
