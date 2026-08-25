#!/usr/bin/env python3
"""Prerequisite gate for coverity-recreate-from-emit.

The skill requires a properly formed `coverity.yaml` in the project. Not just
present -- it must name the Coverity Connect stream, because the stream is
where the snapshot history lives, and that history is what decides whether any
of this skill is worth using.

The Coverity CLI's own schema makes `commit.connect.stream` and
`commit.connect.url` BOTH required, so "properly formed" is the product's
definition, not one invented here.

If the file is absent, unparseable, or missing either key: **abort**. Do not
fall back to asking the user, and do not proceed on a guess. A project without
this configuration is not one this skill can help.

Pure stdlib. PyYAML is used when importable; otherwise a deliberately narrow
extractor handles the ordinary nesting and REFUSES on anything it cannot read
with confidence -- a wrong stream name is worse than no answer.
"""
import argparse, json, os, re, sys

CANDIDATES = ("coverity.yaml", "coverity.yml", "coverity.json")


def find_config(root):
    for n in CANDIDATES:
        p = os.path.join(root, n)
        if os.path.isfile(p):
            return p
    return None


def parse_with_yaml(text):
    try:
        import yaml  # noqa
    except ImportError:
        return None
    try:
        return yaml.safe_load(text)
    except Exception:
        return "UNPARSEABLE"


def parse_narrow(text):
    """Read commit: -> connect: -> url/stream by indentation.

    Intentionally limited. Returns None when the shape is not the plain nesting
    this understands, so the caller aborts instead of guessing.
    """
    lines = [l.rstrip("\n") for l in text.splitlines()]
    def indent(l):
        return len(l) - len(l.lstrip(" "))
    out, i = {}, 0
    while i < len(lines):
        if re.match(r"^commit\s*:", lines[i]):
            ci = indent(lines[i]); i += 1
            while i < len(lines) and (not lines[i].strip() or indent(lines[i]) > ci):
                if re.match(r"^\s*connect\s*:", lines[i]):
                    ni = indent(lines[i]); i += 1
                    while i < len(lines) and (not lines[i].strip() or indent(lines[i]) > ni):
                        m = re.match(r'^\s*(url|stream|project|auth-key-file)\s*:\s*(.+?)\s*$', lines[i])
                        if m:
                            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
                        i += 1
                    continue
                i += 1
            continue
        i += 1
    return out or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--json-out")
    a = ap.parse_args()
    root = os.path.abspath(a.project_dir)

    cfg = find_config(root)
    if not cfg:
        print("ABORT: no Coverity configuration in %s" % root)
        print("       Looked for: %s" % ", ".join(CANDIDATES))
        print()
        print("This skill requires a project already set up for Coverity. Without")
        print("that file there is no stream, no snapshot history, and no way to")
        print("judge whether reusing an intermediate directory is worth it.")
        return 2

    text = open(cfg, encoding="utf-8", errors="replace").read()
    if cfg.endswith(".json"):
        try:
            doc = json.loads(text)
        except Exception as e:
            print("ABORT: %s is not valid JSON (%s)" % (cfg, e)); return 2
        conn = (doc.get("commit") or {}).get("connect") or {}
    else:
        doc = parse_with_yaml(text)
        if doc == "UNPARSEABLE":
            print("ABORT: %s is not valid YAML." % cfg); return 2
        if isinstance(doc, dict):
            conn = (doc.get("commit") or {}).get("connect") or {}
        else:
            conn = parse_narrow(text) or {}
            if not conn:
                print("ABORT: could not read commit.connect from %s" % cfg)
                print("       No YAML parser available and the file is not in the")
                print("       plain nesting the fallback reader understands.")
                print("       Refusing to guess -- a wrong stream name is worse than none.")
                return 2

    stream = (conn.get("stream") or "").strip()
    url = (conn.get("url") or "").strip()

    print("config : %s" % cfg)
    print("stream : %s" % (stream or "<missing>"))
    print("url    : %s" % (url or "<missing>"))

    missing = [k for k, v in (("stream", stream), ("url", url)) if not v]
    if missing:
        print()
        print("ABORT: %s does not name %s." % (cfg, " and ".join(missing)))
        print("       The Coverity CLI schema makes commit.connect.stream and")
        print("       commit.connect.url both required, so this file is not a")
        print("       properly formed Coverity configuration.")
        return 2

    # Where the developer's auth key lives. The CLI default is documented as
    # $HOME/.coverity/ak-<hostname>-<port>, so it usually need not be asked for.
    keyfile = conn.get("auth-key-file")
    if not keyfile:
        m = re.match(r"https?://([^:/]+)(?::(\d+))?", url)
        if m:
            keyfile = os.path.join(os.path.expanduser("~"), ".coverity",
                                   "ak-%s-%s" % (m.group(1), m.group(2) or "443"))
    print("authkey: %s%s" % (keyfile or "<unknown>",
                             "" if keyfile and os.path.isfile(keyfile) else "  (not on disk)"))

    print("\nPREREQUISITE MET. Next: read the stream's snapshot history to estimate")
    print("what a full run costs -- tools/estimate_from_connect.py.")
    print("Take the Connect host from this url, never from the auth key (rule 28).")

    if a.json_out:
        json.dump({"config": cfg, "stream": stream, "url": url,
                   "auth_key_file": keyfile},
                  open(a.json_out, "w", encoding="utf-8"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
