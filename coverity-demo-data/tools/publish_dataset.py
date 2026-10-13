#!/usr/bin/env python3
"""Publish a finished demo dataset into the shared archive library.

See references/archive-layout.md for the layout and the MANIFEST contract.

The validation asymmetry this tool exists to enforce: **everything checkable is
checked here**, once, on the machine that built the data, where a failure costs
a re-run and nothing else. Once a dataset is in the library it is trusted, and
committing from the library does only cheap checks -- because the people doing
that want data in Connect quickly and are not the ones who could fix a
structural problem anyway. A broken dataset must never reach the library: every
later consumer pays for it and none of them can diagnose it.

Facts are DERIVED from the artifacts, never taken on trust, because an analyzed
idir is self-describing:

  build-cwd.txt                   the build root, hence this idir's strip path
  output/version                  the Coverity version that produced it
  output/ANALYSIS.metrics.xml     present iff the idir was analyzed
  output/analysis-settings.json   the exact analysis configuration
  cov-manage-emit ... list        every captured translation unit

Anything derived from the artifact cannot drift from it; anything a human types
can.
"""
import argparse
import collections
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import datetime

SCHEMA = 1


def fail(msg):
    print("[FATAL] " + msg, file=sys.stderr)
    sys.exit(2)


def read_tags(path, default_stream="default"):
    """'<tag> <YYYY-MM-DD> [stream]' per line, sorted globally by date."""
    rows = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            fail(f"malformed line in {path}: {line!r}")
        tag, date = parts[0], parts[1]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            fail(f"bad date for {tag!r}: {date!r} (want YYYY-MM-DD)")
        rows.append({"tag": tag, "date": date,
                     "stream": parts[2] if len(parts) > 2 else default_stream})
    if not rows:
        fail(f"no versions in {path}")
    rows.sort(key=lambda r: (r["date"], r["tag"]))
    return rows


def idir_facts(idir, cov_bin):
    """Everything the idir says about itself."""
    f = {}
    bc = idir / "build-cwd.txt"
    if not bc.is_file():
        fail(f"{idir}: no build-cwd.txt -- not a capture directory")
    f["build_root"] = bc.read_text(encoding="utf-8", errors="replace").strip()

    if not (idir / "output" / "ANALYSIS.metrics.xml").is_file():
        fail(f"{idir}: not analyzed (no output/ANALYSIS.metrics.xml). "
             f"Run cov-analyze before publishing.")

    ver = idir / "output" / "version"
    m = re.search(r"version ([0-9][0-9.]*)",
                  ver.read_text(encoding="utf-8", errors="replace")) if ver.is_file() else None
    if not m:
        fail(f"{idir}: cannot read the Coverity version from output/version")
    f["analysis_version"] = m.group(1)

    settings = idir / "output" / "analysis-settings.json"
    f["analysis_settings"] = settings if settings.is_file() else None

    r = subprocess.run([str(pathlib.Path(cov_bin) / "cov-manage-emit"),
                        "--dir", str(idir), "list"],
                       capture_output=True, text=True)
    tus = [m.group(1) for m in
           (re.match(r"\s*\d+ -> (.+)$", ln) for ln in r.stdout.splitlines()) if m]
    if not tus:
        fail(f"{idir}: cov-manage-emit listed no translation units "
             f"(exit {r.returncode}): {r.stderr.strip()[:200]}")
    f["tus"] = tus
    return f


def strip_root(path, root):
    p = path.replace("\\", "/")
    r = root.replace("\\", "/").rstrip("/")
    return p[len(r):].lstrip("/") if r and p.startswith(r) else None


def merge_keys(idir, cov_bin, scratch):
    """mergeKey set for one idir, exporting JSON if it is not already there."""
    cached = idir / "phase2-issues.json"
    src = cached
    if not cached.is_file():
        src = scratch / (idir.name + "-issues.json")
        if not src.is_file():
            r = subprocess.run([str(pathlib.Path(cov_bin) / "cov-format-errors"),
                                "--dir", str(idir), "--json-output-v10", str(src)],
                               capture_output=True, text=True)
            if not src.is_file():
                fail(f"{idir}: cov-format-errors failed (exit {r.returncode}). "
                     f"Note it needs a licence and checks AFTER printing a "
                     f"summary: {r.stderr.strip()[:200]}")
    data = json.loads(src.read_text(encoding="utf-8"))
    return {i["mergeKey"] for i in data.get("issues", []) if i.get("mergeKey")}


def validate(rows, idirs_root, cov_bin, scratch):
    """Every check that can be made locally. Returns derived facts."""
    facts, problems = {}, []

    # --- per-version: present, analyzed, self-describing -----------------
    for r in rows:
        idir = idirs_root / r["tag"]
        if not idir.is_dir():
            fail(f"no idir for {r['tag']} at {idir}")
        facts[r["tag"]] = idir_facts(idir, cov_bin)

    # --- one pinned analyzer across the corpus ---------------------------
    # This is the precondition for the merge-key arithmetic (rule 27): keys can
    # move between analyzer versions, and Connect's antecedent merge keys are
    # what reconcile them -- something a local comparison cannot see. Pin one
    # version and no key moves.
    versions = {t: f["analysis_version"] for t, f in facts.items()}
    if len(set(versions.values())) > 1:
        by_v = collections.defaultdict(list)
        for t, v in versions.items():
            by_v[v].append(t)
        problems.append("mixed analyzer versions across the corpus: " +
                        "; ".join(f"{v}: {', '.join(sorted(ts))}"
                                  for v, ts in sorted(by_v.items())))

    # --- strip paths: derived per idir, and genuinely a prefix ------------
    # Build paths need NOT match across versions -- merge keys are
    # path-independent, and --strip-path is per-commit. What must hold is that
    # each idir's recorded root really prefixes its own captured paths, or the
    # strip silently does nothing at commit time (rule 31).
    for tag, f in facts.items():
        bad = [p for p in f["tus"] if strip_root(p, f["build_root"]) is None]
        if bad:
            problems.append(
                f"{tag}: build root {f['build_root']!r} does not prefix "
                f"{len(bad)} of {len(f['tus'])} captured paths "
                f"(e.g. {bad[0]}) -- --strip-path would not clean them")
        f["stripped"] = {s for s in (strip_root(p, f["build_root"]) for p in f["tus"]) if s}

    # --- stripped paths line up across versions within a stream ----------
    # This is what --strip-path actually buys: when stripped paths disagree,
    # Connect declines to line files up across versions and the UI loses
    # forward/backward file history. Defect identity is unaffected.
    by_stream = collections.defaultdict(list)
    for r in rows:
        by_stream[r["stream"]].append(r)
    for stream, chain in sorted(by_stream.items()):
        for a, b in zip(chain, chain[1:]):
            fa, fb = facts[a["tag"]]["stripped"], facts[b["tag"]]["stripped"]
            shared = len(fa & fb)
            if shared == 0:
                problems.append(
                    f"{stream}: {a['tag']} and {b['tag']} share no stripped "
                    f"file paths -- the UI will not line files up across them")
            elif shared < 0.5 * max(len(fa), 1):
                problems.append(
                    f"{stream}: {a['tag']} -> {b['tag']} share only {shared} "
                    f"stripped paths of {len(fa)} -- check the build roots")

    # --- defect continuity within each stream ----------------------------
    for stream, chain in sorted(by_stream.items()):
        prev_tag = prev = None
        for r in chain:
            cur = merge_keys(idirs_root / r["tag"], cov_bin, scratch)
            facts[r["tag"]]["cids"] = len(cur)
            if prev is not None and not (prev & cur):
                problems.append(
                    f"{stream}: {prev_tag} and {r['tag']} share zero merge "
                    f"keys -- mixed analyzer versions, a mispaired corpus, or "
                    f"unrelated code")
            prev_tag, prev = r["tag"], cur

    # --- stream shape (rule 29) ------------------------------------------
    for stream, chain in sorted(by_stream.items()):
        dates = [r["date"] for r in chain]
        if dates != sorted(dates):
            problems.append(f"{stream}: dates are not monotonic: {dates}")
        dupes = [d for d, n in collections.Counter(dates).items() if n > 1]
        if dupes:
            problems.append(
                f"{stream}: two releases on the same date {dupes} -- a stream "
                f"is one branch moving forward; concurrent lines need separate "
                f"streams")

    if problems:
        print("[FATAL] dataset is not publishable:", file=sys.stderr)
        for p in problems:
            print("  - " + p, file=sys.stderr)
        print("\nNothing was written. Fix these and re-run; publishing a "
              "broken dataset costs every later consumer.", file=sys.stderr)
        sys.exit(2)
    return facts


def source_shas(repo, rows):
    """Resolve the commit behind each tag, for reproducibility.

    safe.directory is overridden for these invocations only -- a repo reached
    over a UNC path or a WSL share is "dubious ownership" to git, and the global
    config is not ours to edit for the sake of reading two dozen SHAs.
    """
    git = ["git", "-c", "safe.directory=" + str(repo), "-C", str(repo)]
    out = {}
    for r in rows:
        p = subprocess.run(git + ["rev-parse", r["tag"] + "^{commit}"],
                           capture_output=True, text=True)
        if p.returncode == 0:
            out[r["tag"]] = p.stdout.strip()
    url = subprocess.run(git + ["remote", "get-url", "origin"],
                         capture_output=True, text=True)
    if not out:
        print(f"[warn] no commit SHAs resolved from {repo} -- the dataset will "
              f"carry no source provenance", file=sys.stderr)
    return (url.stdout.strip() if url.returncode == 0 else None), out


def winlong(p):
    """Windows MAX_PATH escape.

    An idir nests deeply -- emit/<host>/config/<md5>/<compiler>-config-N/... --
    and the archive adds a project and dataset level on top. A long archive
    root therefore pushes ordinary files past 260 characters and the copy fails
    partway. The extended-length prefix lifts the limit.
    """
    s = os.path.abspath(str(p))
    # Built from chr(92) so no quoting layer can eat a backslash: the
    # prefix must be exactly two backslashes, "?", one backslash.
    prefix = chr(92) * 2 + "?" + chr(92)
    if os.name == "nt" and not s.startswith(prefix):
        s = prefix + s
    return s


def copy_tree(src, dst, link):
    fn = os.link if link else shutil.copy2
    shutil.copytree(winlong(src), winlong(dst), copy_function=fn,
                    dirs_exist_ok=True)


def write_sums(root):
    lines = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS":
            h = hashlib.sha256()
            with open(winlong(p), "rb") as fh:
                for blk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(blk)
            lines.append(f"{h.hexdigest()}  {p.relative_to(root).as_posix()}")
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--slug", required=True,
                    help="what distinguishes this dataset, e.g. releases24-defaults")
    ap.add_argument("--archive-root", default=os.environ.get("COVERITY_DEMO_ARCHIVE"),
                    help="staging archive root. Defaults to $COVERITY_DEMO_ARCHIVE "
                         "so every session publishes to the same place without "
                         "hardcoding a path; keep it SHORT (see archive-layout.md)")
    ap.add_argument("--tags", help="default <workspace>/tag-streams.txt")
    ap.add_argument("--cov-bin", required=True)
    ap.add_argument("--source-repo")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--description", default="")
    ap.add_argument("--link", action="store_true",
                    help="hardlink idirs instead of copying (same filesystem only)")
    ap.add_argument("--validate-only", action="store_true")
    args = ap.parse_args()
    if not args.archive_root:
        fail("no --archive-root and $COVERITY_DEMO_ARCHIVE is unset. Publish to "
             "the configured staging root so every dataset lands in one place.")

    ws = pathlib.Path(args.workspace)
    idirs_root = ws / "idirs"
    tags = pathlib.Path(args.tags) if args.tags else ws / "tag-streams.txt"
    if not tags.is_file():
        fail(f"no tag/date/stream file at {tags}")
    scratch = ws / ".publish-scratch"
    scratch.mkdir(exist_ok=True)

    rows = read_tags(tags)
    print(f"validating {len(rows)} versions ...")
    facts = validate(rows, idirs_root, args.cov_bin, scratch)
    print("validation passed")
    if args.validate_only:
        return 0

    version = next(iter({f["analysis_version"] for f in facts.values()}))
    dataset = pathlib.Path(args.archive_root) / args.project / f"{args.date}-{args.slug}"
    if dataset.exists():
        fail(f"{dataset} already exists. Datasets are immutable; use a new slug.")
    dataset.mkdir(parents=True)
    try:
        assemble(dataset, rows, facts, args, ws, idirs_root, version)
    except BaseException:
        shutil.rmtree(winlong(dataset), ignore_errors=True)
        parent = dataset.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
        print(f"[FATAL] assembly failed; removed the partial dataset at "
              f"{dataset}. The library holds complete datasets only.",
              file=sys.stderr)
        raise
    return 0


def assemble(dataset, rows, facts, args, ws, idirs_root, version):
    for sub in ("idirs", "tools", "provenance"):
        (dataset / sub).mkdir()
    for r in rows:
        print(f"  copying {r['tag']} ...", flush=True)
        copy_tree(idirs_root / r["tag"], dataset / "idirs" / r["tag"], args.link)
    for sub in ("audit", "logs"):
        if (ws / sub).is_dir():
            copy_tree(ws / sub, dataset / sub, args.link)
    for name in ("TRIAGE-REPORT.md",):
        if (ws / name).is_file():
            shutil.copy2(ws / name, dataset / name)

    here = pathlib.Path(__file__).parent
    shutil.copy2(here / "commit_sweep.py", dataset / "tools" / "commit_sweep.py")
    shutil.copy2(here / "commit_template.sh", dataset / "commit.sh")
    os.chmod(dataset / "commit.sh", 0o755)
    for r in rows:
        s = facts[r["tag"]]["analysis_settings"]
        if s:
            shutil.copy2(s, dataset / "provenance" / f"{r['tag']}-analysis-settings.json")

    url, shas = (None, {})
    if args.source_repo:
        url, shas = source_shas(args.source_repo, rows)

    roots = sorted({facts[r["tag"]]["build_root"] for r in rows})
    manifest = {
        "schema": SCHEMA,
        "project": args.project,
        "dataset": f"{args.date}-{args.slug}",
        "description": args.description,
        "built_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "analysis": {"version": version},
        "commit": {
            # One root for the whole corpus is the easy case: one --strip-path
            # cleans everything. Several roots are legal -- --strip-path is
            # per-commit -- so record them per version too.
            "strip_path": roots[0] if len(roots) == 1 else None,
            "strip_path_per_tag": {r["tag"]: facts[r["tag"]]["build_root"] for r in rows},
            "suggested_project": args.project,
        },
        "streams": [{"tag": r["tag"], "date": r["date"], "stream": r["stream"],
                     "cids": facts[r["tag"]]["cids"]} for r in rows],
        "source": {"url": url, "shas": shas},
        "counts": {
            "versions": len(rows),
            "streams": sorted({r["stream"] for r in rows}),
            "cids_at_tip": facts[rows[-1]["tag"]]["cids"],
        },
        "audit": {"present": (dataset / "audit").is_dir()},
    }
    (dataset / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    readme = [
        f"# {args.project} demo dataset -- {args.date}-{args.slug}", "",
        args.description or "(no description given)", "",
        f"- {len(rows)} versions, {', '.join(manifest['counts']['streams'])}",
        f"- {manifest['counts']['cids_at_tip']} CIDs at the newest version",
        f"- analyzed with Coverity {version}", "",
        "## Commit it", "",
        "Take a database backup of the target Connect first: the dates this",
        "writes are write-once per merge key and cannot be corrected in place.",
        "",
        "```",
        "./commit.sh --install <coverity-analysis-root> \\",
        "            --url http://<connect-host>:8080 \\",
        "            --auth-key-file <key.json> [--dry-run]",
        "```",
        "",
        "Run it here, or copy this directory to a host that can reach Connect",
        "and run it there -- it resolves everything relative to itself.", "",
        "`MANIFEST.json` is authoritative. This dataset was validated at",
        "publish time; commit does only quick checks.",
    ]
    (dataset / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")

    n = write_sums(dataset)
    print(f"published {dataset}")
    print(f"  {len(rows)} versions, {n} files checksummed")


if __name__ == "__main__":
    sys.exit(main())
