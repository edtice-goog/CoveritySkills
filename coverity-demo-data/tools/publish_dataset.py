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

# Manifest contract version. Bump it whenever a consumer reading an older
# manifest would be wrong, so the mistake is detectable rather than a
# silently missing key.
#   2: audit.present (a directory existed) replaced by audit.triaged
#      (coverity-triage records exist). The old field read as "checked"
#      for datasets that had not been.
#   3: per-release findings/<tag>.json and capture/<tag>.json retained,
#      and listed under capture.findings and capture.inventory. A
#      column needs both to be comparable to another column, and
#      neither can be regenerated once the matching install is gone.
#   4: the audit block is gone. This skill builds datasets and does not
#      triage, so a dataset carries no verdicts to describe. Triage is
#      invoked separately against a published dataset and its output
#      stays with whoever ran it.
#   5: streams[] carries "version" beside "tag". The tag is the unique
#      label (idir name, file key); the version is the snapshot version
#      and the git ref. They differ when one release is built twice --
#      e.g. for two targets in parallel streams -- and a consumer that
#      read the tag as the version would commit "<target>-v1.0" where
#      "v1.0" was meant. Absent in older manifests: version == tag.
SCHEMA = 5


def fail(msg):
    print("[FATAL] " + msg, file=sys.stderr)
    sys.exit(2)


def read_tags(path, default_stream="default"):
    """'<label> <YYYY-MM-DD> [stream [version]]' per line, sorted globally by date.

    The label is the unique key: the idir's directory name and the name of
    every per-version file. The version is what the snapshot is committed as
    and what git resolves; it defaults to the label. They differ when one
    release is built more than once -- two targets in two parallel streams
    carry the same version under two labels, so a view pinned to that
    version shows both builds side by side.

    Date only, and stable: versions that share a date keep the file's order.
    --backdate is day-granular, so a parent and child committed the same day
    share a date, and only the file knows which came first. A tiebreak on the
    tag would order them by label -- child-first for short SHAs, and wrong for
    describe names once a count crosses a digit ("-10-" < "-9-").
    """
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
                     "stream": parts[2] if len(parts) > 2 else default_stream,
                     "version": parts[3] if len(parts) > 3 else tag})
    if not rows:
        fail(f"no versions in {path}")
    labels = collections.Counter(r["tag"] for r in rows)
    dup = sorted(t for t, n in labels.items() if n > 1)
    if dup:
        fail(f"label used more than once in {path}: {', '.join(dup)} -- a label "
             f"names one idir; to put one release in two streams, give each "
             f"its own label and the shared version as the fourth column")
    per_stream = collections.Counter((r["stream"], r["version"]) for r in rows)
    dup = sorted(f"{v} in {s}" for (s, v), n in per_stream.items() if n > 1)
    if dup:
        fail(f"version committed twice to one stream in {path}: {', '.join(dup)}")
    rows.sort(key=lambda r: r["date"])
    return rows


def idir_facts(idir, cov_bin):
    """Everything the idir says about itself."""
    f = {}
    bc = idir / "build-cwd.txt"
    if not bc.is_file():
        fail(f"{idir}: no build-cwd.txt -- not a capture directory")
    f["build_cwd"] = bc.read_text(encoding="utf-8", errors="replace").strip()
    sr = idir / "scm-root.txt"
    f["scm_root"] = (sr.read_text(encoding="utf-8", errors="replace").strip() or None
                     if sr.is_file() else None)
    f["build_root"] = f["build_cwd"]   # settled by settle_root() in validate()

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

    # list-json rather than list: one call serves both the path validation
    # below and the capture inventory the dataset retains. It carries
    # primaryFileHash as well as the size, which is what lets a later column
    # prove it analyzed the same code rather than merely a same-sized file.
    r = subprocess.run([str(pathlib.Path(cov_bin) / "cov-manage-emit"),
                        "--dir", str(idir), "list-json"],
                       capture_output=True, text=True)
    try:
        records = json.loads(r.stdout)
    except json.JSONDecodeError:
        records = []
    if not records:
        fail(f"{idir}: cov-manage-emit list-json returned no translation units "
             f"(exit {r.returncode}): {r.stderr.strip()[:200]}")
    f["tu_records"] = records
    f["tus"] = [t["primaryFilename"] for t in records if t.get("primaryFilename")]
    if not f["tus"]:
        fail(f"{idir}: list-json records carry no primaryFilename")
    return f


def strip_root(path, root):
    """path relative to root, or None if root is not a whole-component prefix.

    "/b/proj" must not claim "/b/project2/x.c": that would strip to "ect2/x.c"
    here and leave the path unstripped in Connect.
    """
    p = path.replace("\\", "/")
    r = root.replace("\\", "/").rstrip("/")
    if not r or not (p == r or p.startswith(r + "/")):
        return None
    return p[len(r):].lstrip("/")


def settle_root(f, given):
    """(strip root, where it came from, problem or None) for one idir.

    The strip root is the SCM checkout the build ran in -- never a folder
    inferred from the captured paths. Inference is wrong exactly when the
    build reads files from outside the checkout: "the nearest folder holding
    every captured file" then climbs above the checkout to take them in.
    Files outside the checkout keep their own paths, as system headers do.

    In order: the idir's scm-root.txt (capture.sh writes it), then
    --scm-root for idirs captured without one. A build directory that holds
    every captured path is accepted as the checkout for older in-tree
    captures; an out-of-tree capture with no recorded checkout is refused.
    """
    norm = lambda p: p.replace("\\", "/").rstrip("/")
    rec, cwd = f["scm_root"], f["build_cwd"]
    if rec and given and norm(rec) != norm(given):
        return rec, "scm-root.txt", (f"scm-root.txt says {rec!r} but --scm-root "
                                     f"says {given!r}")
    if rec or given:
        return norm(rec or given), ("scm-root.txt" if rec else "--scm-root"), None
    if all(strip_root(p, cwd) is not None for p in f["tus"]):
        return norm(cwd), "build-cwd.txt", None
    bad = [p for p in f["tus"] if strip_root(p, cwd) is None]
    return norm(cwd), "build-cwd.txt", (
        f"build directory {cwd!r} does not prefix {len(bad)} of {len(f['tus'])} "
        f"captured paths (e.g. {bad[0]}) and no checkout is recorded -- an "
        f"out-of-tree build; pass --scm-root with the checkout's top level "
        f"(git rev-parse --show-toplevel), or recapture with capture.sh")


def findings_export(idir, cov_bin, scratch):
    """Path to this idir's JSON v10 finding export, generating it if absent.

    The export IS the column's finding set, and regenerating it later needs an
    analyzer install whose version matches the idir -- installs get removed, so
    a column that loses its export cannot be reproduced. It is therefore
    retained in the dataset rather than treated as a scratch intermediate.
    """
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
    return src


def merge_keys(idir, cov_bin, scratch):
    """mergeKey set for one idir."""
    src = findings_export(idir, cov_bin, scratch)
    data = json.loads(src.read_text(encoding="utf-8"))
    return {i["mergeKey"] for i in data.get("issues", []) if i.get("mergeKey")}


def git_cmd(repo):
    """safe.directory is overridden for these invocations only -- a repo
    reached over a UNC path or a WSL share is "dubious ownership" to git, and
    the global config is not ours to edit for the sake of a read."""
    return ["git", "-c", "safe.directory=" + str(repo), "-C", str(repo)]


def same_date_problems(stream, chain, source_repo):
    """Equal dates in one stream are legal only as a strict ancestor chain.

    A stream is one branch moving forward (rule 29), and two versions on one
    date usually mean two lines. But --backdate is day-granular, so a parent
    and child committed the same day collide too. Git can tell them apart: in
    file order, each same-date version must be a proper ancestor of the next.
    """
    groups = collections.defaultdict(list)
    for r in chain:
        groups[r["date"]].append(r["version"])
    groups = {d: ts for d, ts in groups.items() if len(ts) > 1}
    if not groups:
        return []
    if not source_repo:
        return [f"{stream}: more than one version on the same date "
                f"{sorted(groups)} -- concurrent lines need separate streams; "
                f"same-day commits on one line are allowed only with "
                f"--source-repo, which proves the ancestry"]
    git, out = git_cmd(source_repo), []
    for date, tags in sorted(groups.items()):
        for a, b in zip(tags, tags[1:]):
            sa = subprocess.run(git + ["rev-parse", "--verify", "-q", a + "^{commit}"],
                                capture_output=True, text=True).stdout.strip()
            sb = subprocess.run(git + ["rev-parse", "--verify", "-q", b + "^{commit}"],
                                capture_output=True, text=True).stdout.strip()
            if not sa or not sb:
                out.append(f"{stream}: {date}: cannot resolve "
                           f"{a if not sa else b} in {source_repo}")
                continue
            anc = subprocess.run(git + ["merge-base", "--is-ancestor", sa, sb],
                                 capture_output=True).returncode == 0
            if sa == sb or not anc:
                out.append(
                    f"{stream}: {a} and {b} share the date {date} but {a} is "
                    f"not a proper ancestor of {b} -- concurrent lines need "
                    f"separate streams; if they are one line, list them "
                    f"parent first in the tags file")
    return out


def validate(rows, idirs_root, cov_bin, scratch, source_repo=None, scm_root=None):
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
    # The strip root is the SCM checkout (settle_root), which for an
    # out-of-tree build is not where the build ran.
    for tag, f in facts.items():
        root, src, problem = settle_root(f, scm_root)
        if problem:
            problems.append(f"{tag}: {problem}")
        f["build_root"], f["root_source"] = root, src
        inside = [s for s in (strip_root(p, root) for p in f["tus"]) if s is not None]
        f["stripped"] = set(inside)
        # Only meaningful against a settled root; a refused one would count noise.
        f["outside_checkout"] = 0 if problem or not inside else len(f["tus"]) - len(inside)
        if not inside and not problem:
            problems.append(f"{tag}: checkout {root!r} prefixes none of the "
                            f"{len(f['tus'])} captured paths -- wrong checkout?")
    moved = sorted(t for t, f in facts.items()
                   if f["build_root"] != f["build_cwd"].replace("\\", "/").rstrip("/"))
    if moved:
        f0 = facts[moved[0]]
        print(f"out-of-tree builds: {len(moved)} version(s) strip at the checkout, "
              f"not the build directory, e.g. {moved[0]}: "
              f"{f0['build_cwd']} -> {f0['build_root']} ({f0['root_source']})")
    outside = {t: f["outside_checkout"] for t, f in facts.items() if f["outside_checkout"]}
    if outside:
        t0 = max(outside, key=outside.get)
        print(f"files outside the checkout keep their full paths: {len(outside)} "
              f"version(s), at most {outside[t0]} files ({t0}). Normal for "
              f"headers or sources the build pulls from elsewhere; review if "
              f"the count is large.")

    # --- stripped paths line up across versions within a stream ----------
    # This is what --strip-path actually buys: when stripped paths disagree,
    # Connect declines to line files up across versions and the UI loses
    # forward/backward file history. Defect identity is unaffected.
    by_stream = collections.defaultdict(list)
    for r in rows:
        by_stream[r["stream"]].append(r)
    #
    # A low overlap is a strip mistake -- unless upstream moved the files. The
    # two are told apart by the root: with ONE strip root on both sides, the
    # stripping is identical, so a disagreement can only come from the tree
    # itself. Then the basenames still match (src/x/A.java ->
    # src/main/java/x/A.java), and the break is real history to report, not a
    # dataset to refuse. With different roots, a basename match proves nothing:
    # per-version checkout directories under a too-short root look the same.
    history_breaks = []
    for stream, chain in sorted(by_stream.items()):
        for a, b in zip(chain, chain[1:]):
            fa, fb = facts[a["tag"]]["stripped"], facts[b["tag"]]["stripped"]
            shared = len(fa & fb)
            if shared >= 0.5 * max(len(fa), 1):
                continue
            base = lambda s: {p.rsplit("/", 1)[-1] for p in s}
            tail = lambda s: {p.split("/", 1)[1] for p in s if "/" in p}
            ba = base(fa)
            same_root = facts[a["tag"]]["build_root"] == facts[b["tag"]]["build_root"]
            shared_base = len(ba & base(fb))
            # Paths that agree once the top directory is dropped, built in
            # different directories, are not a move: that is one strip root laid
            # over per-version checkouts. (Built in the same directory, a
            # top-level rename such as source/ -> src/ is a real move.)
            top_only = len(tail(fa) & tail(fb)) >= 0.5 * max(len(fa), 1)
            moved_cwd = facts[a["tag"]]["build_cwd"] != facts[b["tag"]]["build_cwd"]
            if top_only and moved_cwd:
                problems.append(
                    f"{stream}: {a['tag']} -> {b['tag']} differ only in their top "
                    f"directory -- one strip root over per-version checkouts? "
                    f"Strip each version at its own checkout")
                continue
            if same_root and shared_base >= 0.5 * max(len(ba), 1):
                history_breaks.append({
                    "stream": stream, "from": a["tag"], "to": b["tag"],
                    "shared_paths": shared, "shared_basenames": shared_base,
                    "basenames": len(ba)})
                continue
            if shared == 0:
                problems.append(
                    f"{stream}: {a['tag']} and {b['tag']} share no stripped "
                    f"file paths -- the UI will not line files up across them")
            else:
                problems.append(
                    f"{stream}: {a['tag']} -> {b['tag']} share only {shared} "
                    f"stripped paths of {len(fa)} -- check the build roots")
    for h in history_breaks:
        facts[h["to"]]["history_break"] = h
        print(f"[warn] {h['stream']}: file history does not line up across "
              f"{h['from']} -> {h['to']}: upstream moved files ({h['shared_paths']} "
              f"paths shared, {h['shared_basenames']} of {h['basenames']} "
              f"basenames). Say so in the dataset description.")

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
        problems.extend(same_date_problems(stream, chain, source_repo))

    if problems:
        print("[FATAL] dataset is not publishable:", file=sys.stderr)
        for p in problems:
            print("  - " + p, file=sys.stderr)
        print("\nNothing was written. Fix these and re-run; publishing a "
              "broken dataset costs every later consumer.", file=sys.stderr)
        sys.exit(2)
    return facts


def source_shas(repo, rows):
    """Resolve the commit behind each version, keyed by label."""
    git = git_cmd(repo)
    out = {}
    for r in rows:
        p = subprocess.run(git + ["rev-parse", r["version"] + "^{commit}"],
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
    ap.add_argument("--scm-root",
                    help="top level of the SCM checkout the build ran in, as "
                         "the build saw it, for idirs captured without "
                         "scm-root.txt. The strip root; see settle_root()")
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
    facts = validate(rows, idirs_root, args.cov_bin, scratch, args.source_repo,
                     args.scm_root)
    print("validation passed")
    if args.validate_only:
        return 0

    version = next(iter({f["analysis_version"] for f in facts.values()}))
    dataset = pathlib.Path(args.archive_root) / args.project / f"{args.date}-{args.slug}"
    if dataset.exists():
        fail(f"{dataset} already exists. Datasets are immutable; use a new slug.")
    dataset.mkdir(parents=True)
    try:
        assemble(dataset, rows, facts, args, ws, idirs_root, version, scratch)
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


def assemble(dataset, rows, facts, args, ws, idirs_root, version, scratch):
    for sub in ("idirs", "tools", "provenance", "findings", "capture"):
        (dataset / sub).mkdir()
    for r in rows:
        print(f"  copying {r['tag']} ...", flush=True)
        copy_tree(idirs_root / r["tag"], dataset / "idirs" / r["tag"], args.link)
    for sub in ("logs",):
        if (ws / sub).is_dir():
            copy_tree(ws / sub, dataset / sub, args.link)
    here = pathlib.Path(__file__).parent
    shutil.copy2(here / "commit_sweep.py", dataset / "tools" / "commit_sweep.py")
    shutil.copy2(here / "commit_template.sh", dataset / "commit.sh")
    os.chmod(dataset / "commit.sh", 0o755)
    for r in rows:
        st = facts[r["tag"]]["analysis_settings"]
        if st:
            shutil.copy2(st, dataset / "provenance" / f"{r['tag']}-analysis-settings.json")

    # The two artifacts a later column needs in order to be comparable to this
    # one, and that cannot be regenerated once the matching analyzer install is
    # gone. Both are small; both are derived from the idir rather than part of
    # it, so they sit beside the manifest where publish can verify them.
    emitted = {}
    for r in rows:
        tag = r["tag"]
        shutil.copy2(findings_export(idirs_root / tag, args.cov_bin, scratch),
                     dataset / "findings" / f"{tag}.json")
        log = ws / "logs" / f"{tag}.build.log"
        n = None
        if log.is_file():
            # One summary line per language ("C/C++", "Java", "C#", ...); a
            # mixed build prints several. Last count per language, summed.
            hits = re.findall(r"^Emitted (\d+) (.+?) compilation units",
                              log.read_text(encoding="utf-8", errors="replace"),
                              re.M)
            if hits:
                n = sum(dict((lang, int(c)) for c, lang in hits).values())
        emitted[tag] = n
        (dataset / "capture" / f"{tag}.json").write_text(json.dumps({
            "tag": tag,
            "tu_count": len(facts[tag]["tu_records"]),
            "emitted_from_build_log": n,
            "build_root": facts[tag]["build_root"],
            "build_cwd": facts[tag]["build_cwd"],
            "build_root_from": facts[tag]["root_source"],
            "outside_checkout": facts[tag]["outside_checkout"],
            "translation_units": facts[tag]["tu_records"],
        }, indent=2) + chr(10), encoding="utf-8")

    url, shas = (None, {})
    if args.source_repo:
        url, shas = source_shas(args.source_repo, rows)

    roots = sorted({facts[r["tag"]]["build_root"] for r in rows})

    # Capture scope, reported rather than judged. What a build compiles is in
    # scope by the SSDLC's own logic, so test code in the capture is a decision
    # made at build-configure time -- not something to filter out afterwards,
    # and not something a filename pattern can settle (alsa-utils ships
    # speaker-test/speaker-test.c as an installed program). Record the shape so
    # the builder sees it before publishing and a consumer sees it in the
    # manifest without re-deriving it.
    tip = rows[-1]["tag"]
    tip_dirs = collections.Counter(s.split("/")[0]
                                  for s in facts[tip]["stripped"] if "/" in s)
    all_dirs = sorted({s.split("/")[0]
                       for r in rows for s in facts[r["tag"]]["stripped"] if "/" in s})
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
        "streams": [{"tag": r["tag"], "version": r["version"], "date": r["date"],
                     "stream": r["stream"], "cids": facts[r["tag"]]["cids"]}
                    for r in rows],
        "source": {"url": url, "shas": shas},
        "counts": {
            "versions": len(rows),
            "streams": sorted({r["stream"] for r in rows}),
            "cids_at_tip": facts[rows[-1]["tag"]]["cids"],
        },
        "capture": {
            "tu_by_top_dir_at_tip": dict(sorted(tip_dirs.items(),
                                                key=lambda kv: -kv[1])),
            "top_dirs_any_version": all_dirs,
            # Per release: the finding set this column reported, and the
            # inventory proving what it analyzed. Both retained because
            # regenerating either needs an analyzer install matching the idir.
            "findings": {r["tag"]: f"findings/{r['tag']}.json" for r in rows},
            "inventory": {r["tag"]: f"capture/{r['tag']}.json" for r in rows},
            "emitted_from_build_log": emitted,
            # Adjacent versions whose files upstream moved: Connect will not
            # line file history up across these, by the tree's own doing.
            "file_history_breaks": [facts[r["tag"]]["history_break"] for r in rows
                                    if "history_break" in facts[r["tag"]]],
        },
    }
    (dataset / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    readme = [
        f"# {args.project} demo dataset -- {args.date}-{args.slug}", "",
        args.description or "(no description given)", "",
        f"- {len(rows)} versions, {', '.join(manifest['counts']['streams'])}",
        f"- {manifest['counts']['cids_at_tip']} CIDs at the newest version",
        f"- analyzed with Coverity {version}",
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
    print()
    print("capture scope at " + tip + " (translation units by top directory):")
    for d, c in sorted(tip_dirs.items(), key=lambda kv: -kv[1]):
        print("  " + d.ljust(20) + " " + str(c))
    print("Review this. Whatever the build compiled is in the dataset, and a")
    print("demo dataset should normally cover only what ships: test and fuzz")
    print("harnesses pulled in by a stock build are a scope decision to make")
    print("at configure time, not a filter to apply afterwards.")
    print()
    print(f"published {dataset}")
    print(f"  {len(rows)} versions, {n} files checksummed")


if __name__ == "__main__":
    sys.exit(main())
