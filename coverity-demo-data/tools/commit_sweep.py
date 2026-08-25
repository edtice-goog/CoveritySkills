#!/usr/bin/env python3
"""Phase 3: commit a version corpus to Coverity Connect, oldest first.

This is the one-shot phase. `merged_defect.date_originated` is global per merge
key and set the first time a key is committed, so a mistake here is not
correctable in place -- only by restoring the database and starting over. The
driver is therefore built to fail loudly and immediately rather than to finish.

After every commit it verifies an invariant that catches the failure modes that
would otherwise be discovered on stage:

  the first-detected counts for all EARLIER dates must be unchanged

If committing version N alters how many CIDs are dated to version N-3, defects
are not merging the way Phase 2 predicted -- typically a build-path or analyzer
mismatch -- and every subsequent commit compounds it. The sweep stops there.

Usage:
  commit_sweep.py --idirs-root idirs --tags tag-dates.txt \
      --url http://host:8080 --auth-key-file key.json --stream NAME \
      --strip-path /home/me/demo/proj --platform-bin <Connect>/bin

  --dry-run prints the plan (order, dates, idirs) and commits nothing.
"""
import argparse
import pathlib
import re
import subprocess
import sys


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def read_tags(path, default_stream):
    """'<tag> <YYYY-MM-DD> [stream]' per line -> [(tag, date, stream)].

    Sorted globally by date, ACROSS streams. First detected is global per merge
    key, not per stream, so committing one stream to completion before starting
    the next would date every shared defect to whichever stream went first --
    and no later backdate can move it. Interleave by date; assign by branch.
    (Rule 29.)
    """
    out = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        tag, date = parts[0], parts[1] if len(parts) > 1 else ""
        stream = parts[2] if len(parts) > 2 else default_stream
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            sys.exit(f"[FATAL] bad date for {tag!r}: {date!r} (want YYYY-MM-DD)")
        if not stream:
            sys.exit(f"[FATAL] no stream for {tag!r}: give a third column "
                     f"or pass --stream")
        out.append((tag, date, stream))
    out.sort(key=lambda t: t[1])
    return out


def first_detected_counts(platform_bin):
    """{date: count} from merged_defect -- the invariant we protect."""
    sql = ("SELECT date_originated::date, count(*) FROM merged_defect "
           "GROUP BY 1 ORDER BY 1;")
    r = run([str(pathlib.Path(platform_bin) / "cov-admin-db"), "psql"], input=sql)
    counts = {}
    for line in r.stdout.splitlines():
        m = re.match(r"\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(\d+)\s*$", line)
        if m:
            counts[m.group(1)] = int(m.group(2))
    return counts


def snapshot_dates(platform_bin):
    """[(id, date, description)] for every committed snapshot."""
    sql = "SELECT id, date_created::date, description FROM snapshot ORDER BY id;"
    r = run([str(pathlib.Path(platform_bin) / "cov-admin-db"), "psql"], input=sql)
    rows = []
    for line in r.stdout.splitlines():
        m = re.match(r"\s*(\d+)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|(.*)$", line)
        if m:
            rows.append((int(m.group(1)), m.group(2), m.group(3).strip()))
    return rows


def unstripped_paths(platform_bin, strip):
    """True if Connect still holds paths under the prefix we meant to strip."""
    sql = ("SELECT count(*) FROM file_path WHERE pathname LIKE '"
           + strip.replace("'", "''") + "%';")
    r = run([str(pathlib.Path(platform_bin) / "cov-admin-db"), "psql"], input=sql)
    for line in r.stdout.splitlines():
        t = line.strip()
        if t.isdigit():
            return int(t) > 0
    return False


def check_invariant(before, after, expect_date, tag):
    """Earlier dates must be untouched; growth only at the current date."""
    problems = []
    for date, n in before.items():
        if date == expect_date:
            continue
        if after.get(date) != n:
            problems.append(
                f"  first-detected count for {date} changed "
                f"{n} -> {after.get(date)}")
    for date, n in after.items():
        if date not in before and date != expect_date:
            problems.append(
                f"  {n} defect(s) appeared at unexpected date {date}")
    if problems:
        sys.stderr.write(
            f"\n[FATAL] committing {tag} disturbed earlier first-detected "
            f"dates:\n" + "\n".join(problems) + "\n\n"
            "Defects are not merging as Phase 2 predicted -- usually a build\n"
            "path that varied between versions, or a mixed analyzer version.\n"
            "Every further commit compounds this. Stop, restore the database\n"
            "from the Step 0 backup, fix Phase 1, and start the sweep over.\n")
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--idirs-root", required=True)
    ap.add_argument("--tags", required=True,
                    help="file of '<tag> <YYYY-MM-DD>' lines; sorted here")
    ap.add_argument("--url", required=True)
    ap.add_argument("--auth-key-file", required=True,
                    help="rule 28: the target comes from --url, never from "
                         "the host recorded inside this key")
    ap.add_argument("--stream", default="",
                    help="destination stream; overridden per-tag by an "
                         "optional third column in --tags")
    ap.add_argument("--strip-path", default="")
    ap.add_argument("--cov-bin", required=True,
                    help="Coverity Analysis bin dir (cov-commit-defects)")
    ap.add_argument("--platform-bin",
                    help="Connect bin dir; enables post-commit verification")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tags = read_tags(args.tags, args.stream)
    root = pathlib.Path(args.idirs_root)

    # --strip-path only matches with the trailing separator. Given
    # "/home/me/demo/proj" it strips NOTHING, silently -- no error, no warning,
    # just every path in Connect prefixed with a build directory nobody wants
    # to see in a demo. Normalise rather than trust the caller.
    strip = args.strip_path
    if strip and not strip.endswith("/"):
        strip += "/"
        print(f"[note] --strip-path normalised to {strip!r} "
              f"(it is a silent no-op without the trailing separator)")

    # Fail before touching Connect if any idir is missing or unanalyzed.
    missing = [t for t, _, _ in tags if not (root / t).is_dir()]
    if missing:
        sys.exit("[FATAL] no idir for: " + ", ".join(missing))

    streams = sorted({st for _, _, st in tags})
    print(f"Commit plan ({len(tags)} versions, {len(streams)} stream(s), "
          f"globally oldest first):")
    for tag, date, st in tags:
        print(f"  {date}  {tag:<10} -> {st}")
    if args.dry_run:
        print("\n--dry-run: nothing committed.")
        return 0

    if not args.platform_bin:
        print("\n[WARN] --platform-bin not given: committing WITHOUT the "
              "post-commit invariant check. On a one-shot phase this is a "
              "poor trade.", file=sys.stderr)

    stripped_ok = False

    print("\nThis phase is NOT reversible. Ensure the Step 0 backup exists.\n")
    for tag, date, stream in tags:
        before = first_detected_counts(args.platform_bin) if args.platform_bin else {}
        cmd = [str(pathlib.Path(args.cov_bin) / "cov-commit-defects"),
               "--dir", str(root / tag), "--url", args.url,
               "--auth-key-file", args.auth_key_file, "--stream", stream,
               "--backdate", date.replace("-", ""),
               "--description", tag, "--version", tag]
        if strip:
            cmd += ["--strip-path", strip]

        print(f"[{date}] committing {tag} -> {stream} ...", flush=True)
        r = run(cmd)
        if r.returncode != 0:
            sys.stderr.write(r.stdout[-2000:] + r.stderr[-2000:])
            sys.exit(f"\n[FATAL] commit failed for {tag}. Nothing after this "
                     f"point has been committed; the database is still usable "
                     f"as-is or restorable from the Step 0 backup.")

        if args.platform_bin:
            after = first_detected_counts(args.platform_bin)
            if not check_invariant(before, after, date, tag):
                return 2
            snaps = snapshot_dates(args.platform_bin)
            got = snaps[-1][1] if snaps else None
            if got != date:
                sys.exit(f"[FATAL] {tag}: snapshot landed on {got}, "
                         f"expected {date}")
            new = after.get(date, 0) - before.get(date, 0)
            print(f"           ok: snapshot dated {date}, "
                  f"{new} newly-originated CID(s)")
            if strip and not stripped_ok:
                stripped_ok = True
                if unstripped_paths(args.platform_bin, strip):
                    sys.exit(
                        f"[FATAL] --strip-path {strip!r} stripped nothing -- "
                        f"Connect is storing full build paths. Fix the prefix "
                        f"and re-run from the Step 0 backup before committing "
                        f"the rest.")

    if args.platform_bin:
        print("\nFinal first-detected distribution:")
        for date, n in sorted(first_detected_counts(args.platform_bin).items()):
            print(f"  {date}  {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
