"""The analysis of one base/head pair: everything up to the judge.

Maps the git diff onto the head's functions, diffs both sides' derived models, walks the call graph from the changed
functions while models keep changing, joins the head's coverage, applies the fixed rules and writes an evidence
packet per affected function.
"""
import hashlib
import json
import os
import re
import subprocess

from . import callgraph, changes, models, triage, walk


def sh(*args, **kw):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kw).stdout


def packet_name(fid):
    """A file name for the function's packet: the fid, unless that holds characters Windows cannot keep (Java's
    <init>) or is long (Java parameter lists), then a cleaned, clipped form plus a short hash."""
    name = fid.replace("/", "_").replace(":", "__")
    unsafe = re.compile(r'[<>"|?*\\]')
    if len(name) > 140 or unsafe.search(name):
        name = unsafe.sub("_", name)[:110] + "-" + hashlib.md5(fid.encode()).hexdigest()[:8]
    return name


def source_lines(clone, sha, file, cache={}):
    if (clone, sha, file) not in cache:
        cache[(clone, sha, file)] = sh("git", "-C", clone, "show", f"{sha}:{file}").splitlines()
    return cache[(clone, sha, file)]


def analyze(ds, base, head, run):
    """Model diff, changed functions, call graph and walk, coverage join, fixed rules and evidence packets for one
    base/head pair, written to the folder `run`: analysis.json, judge.txt (the functions left for the judge) and
    packets/*.md. `ds` gives the repository, the Coverity bin folder, the diff paths and the coverage, and prepares
    each side (`ds.prepare(label)`: its idir, model dump, commit and build roots)."""
    os.makedirs(f"{run}/packets", exist_ok=True)
    b, h = ds.prepare(base), ds.prepare(head)
    roots = [h.capture_root]

    b_models, _ = models.load(b.dump, roots)
    h_models, disagree = models.load(h.dump, roots)
    deltas = models.diff(b_models, h_models)

    h_fns, b_fns = changes.functions(h.idir, roots), changes.functions(b.idir, [b.capture_root])
    by_fid = {f.fid: f for f in h_fns}
    file_hunks = changes.hunks(ds.clone, b.sha, h.sha, ds.diff_paths)
    s0, removed = changes.changed_functions(h_fns, b_fns, file_hunks)
    def head_source(file):
        try:
            return source_lines(ds.clone, h.sha, file)
        except Exception:
            return None
    unmapped = changes.unmapped(h_fns, file_hunks, head_source)
    graph = callgraph.load(h.idir, roots, h_fns)
    # A function whose model changed with none of its lines changed: the cause is outside it (a header macro, an
    # inline function, a type). It is affected, and so are its callers.
    seeds = sorted(f.fid for f in h_fns if f.fid not in s0 and deltas.get(f.name, {}).get("status") == "changed")
    affected = walk.walk(s0, graph, lambda fid: fid.split(":", 1)[1] in deltas, seeds=seeds)

    cov, per_test = ds.load_coverage(h)

    results, judge = {}, []
    for fid, info in sorted(affected.items(), key=lambda kv: (kv[1]["depth"], kv[0])):
        fn = by_fid[fid]
        targets = triage.target_lines(fid, info, s0, graph, cov, fn)
        src = source_lines(ds.clone, h.sha, fn.file)
        verdict, detail = triage.triage(fn, targets, cov, src)
        text = triage.packet(fid, fn, info, s0, deltas, graph, cov, per_test, targets, (verdict, detail),
                             src, ds.per_test_note, unmapped)
        name = packet_name(fid)
        open(f"{run}/packets/{name}.md", "w").write(text)
        if verdict == "JUDGE":
            judge.append(fid)
        results[fid] = {"file": fn.file, "name": fn.name, "start": fn.start, "end": fn.end,
                        "depth": info["depth"], "reasons": info["reasons"], "boundary": info["boundary"],
                        "truncated": info["truncated"], "address_taken": info["address_taken"],
                        "model_changed": fn.name in deltas, "targets": targets, "triage": verdict,
                        "detail": detail, "packet": f"packets/{name}.md",
                        "tests": triage.tests_reaching(fn, range(fn.start, fn.end + 1), per_test)}

    reached = {r["name"] for r in results.values()}
    analysis = {
        "dataset": ds.name,
        "base": {"tag": base, "sha": b.sha}, "head": {"tag": head, "sha": h.sha},
        "s0": sorted(s0), "removed": removed, "unmapped_changes": unmapped, "affected": results,
        "model_changes": {n: {"status": d["status"], "lines": models.describe(d)} for n, d in deltas.items()},
        "unexplained_model_changes": sorted(n for n in deltas if n not in reached),
        "model_disagreements": sorted(disagree),
        "graph": {"edges": sum(len(v) for v in graph.callers.values()),
                  "virtual_edges": len(graph.virtual),
                  "address_taken": {k: sorted(v) for k, v in graph.address_taken.items()}},
        "per_test_units": sorted(per_test),
    }
    json.dump(analysis, open(f"{run}/analysis.json", "w"), indent=1)
    open(f"{run}/judge.txt", "w").write("".join(f"{f}\t{results[f]['packet']}\n" for f in judge))
    counts = {}
    for r in results.values():
        counts[r["triage"]] = counts.get(r["triage"], 0) + 1
    print(f"S0 {len(s0)}, model changes {len(deltas)}, affected {len(results)}: {counts}")
    print(f"unexplained model changes: {analysis['unexplained_model_changes']}")
    print(f"run: {run}")
