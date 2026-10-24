# Archiving a dataset: standard layout

A demo dataset is expensive to build and cheap to reuse, so it belongs in a
standard place with a predictable shape rather than wherever the build
happened to leave it. Its purpose is narrow and worth stating: **the next
person to want this data should not have to interrogate the directory to find
out how to use it** -- and a dataset built for one project should look exactly
like a dataset built for another.

**The archive is local, and nothing here touches the network.**
`publish_dataset.py` writes to a directory you name and does no more than that.
Replicating an archive onto a shared host, so a team can draw on a common
library, is a reasonable thing to want and is deliberately **out of scope**: a
skill that instructed an agent to copy data to a remote host would be
indistinguishable, from the outside, from a compromised one. If you want that,
build it yourself around this layout -- the layout is the portable part.

## The validation asymmetry

Checking happens **once, at publish time, on the machine that built the data**,
and it is exhaustive. By the time a dataset is in the library it is trusted.

Committing *from* the library does only cheap checks, because the people doing
it want data in a Connect instance quickly and are not the ones who can fix a
structural problem anyway.

| | publish (once, local) | commit (often, from the library) |
|---|---|---|
| cost of failure | re-run locally, nothing lost | someone is blocked |
| checks | everything that can be checked | structure, version, and the in-flight commit invariants |

Put differently: a broken dataset must never reach the library, because every
later consumer pays for it and none of them can diagnose it.

## Layout

```
<archive-root>/
  INDEX.md                          generated; one line per dataset
  <project>/                        nested by project
    <YYYY-MM-DD>-<slug>/            build date + what distinguishes it
      README.md                     what it is, what it shows, how to use it
      MANIFEST.json                 authoritative machine contract
      SHA256SUMS                    for periodic archive integrity audits
      commit.sh                     parameterized entry point
      tools/commit_sweep.py         bundled, so the dataset stands alone
      idirs/<tag>/                  analyzed intermediate directories
      audit/                        triage bundles and records (coverity-triage), if triage was chosen
      logs/                         configure, build and analyze logs; cu-counts
      provenance/                   analysis-settings.json, source SHAs, toolchain
```

Nest by project; several datasets per project is the normal case, since the
same corpus analyzed with a different checker set is a different dataset. The
dataset id is the build date plus a slug naming the distinguishing axis
(`2026-08-25-releases24-defaults`), so ids sort chronologically and cannot
collide.

**Store idirs uncompressed.** Compression and decompression time does not pay
for itself on a fast network, and it makes running directly from the archive
host worse. Budget roughly 29 MB per analyzed version -- about 700 MB for a
24-version corpus.

## MANIFEST.json

Authoritative, and the reason a consumer does not need to explore. It records
what cannot be guessed from the outside:

| field | why it has to be recorded |
|---|---|
| `commit.strip_path` | the original build root. Required at commit, unguessable from the archive |
| `analysis.version` | idirs are version-bound; committing with a mismatched install can fail |
| `streams[]` | `{tag, date, stream}` -- both the commit order and the branch mapping |
| `source` | repo URL and per-tag commit SHA, so the corpus is reproducible |
| `capture` | build host OS, compiler, cov-configure template; capture is toolchain-dependent |
| `counts`, `audit` | lets someone judge fit before committing anything anywhere |

**Single source of truth.** Do not write the stream map into a second file
beside the manifest. `commit.sh` derives whatever input format it needs at run
time. Two copies of a stream map is exactly the drift that silently flattens
branches (rule 29).

**Derive, do not ask.** An analyzed idir is self-describing, so publish reads
these from the artifacts instead of trusting a human:

- `build-cwd.txt` -- the build root, hence `strip_path`
- `output/version` -- the Coverity version that produced it
- `output/ANALYSIS.metrics.xml` -- present iff the idir was analyzed
- `output/analysis-settings.json` -- the exact analysis configuration

Anything derived from the artifact cannot drift from it. Anything a human types
can.

## What publishing expects of a workspace

This is the compliance checklist for a session that already built a dataset and
now wants it in the standard shape. Required:

```
<workspace>/
  idirs/<tag>/           one ANALYZED idir per version (cov-analyze has run)
  tag-streams.txt        "<tag> <YYYY-MM-DD> [stream]", one per line
```

The date is the release date to backdate to. The third field is the stream, and
it is how concurrent release lines stay apart (rule 29); omit it only for a
single-stream corpus. Pass `--tags` if the file lives elsewhere or is named
differently.

Carried through if present, ignored if not: `audit/`, `logs/`, and a top-level
triage report. `MANIFEST.json` lists every `coverity-triage` records file under
`audit/` (`audit.triage_records`); an empty list means the dataset is
untriaged.

Nothing else is asked for, because everything else is **derived** from the
idirs -- the strip path from `build-cwd.txt`, the analyzer version from
`output/version`, whether analysis ran from `output/ANALYSIS.metrics.xml`, the
captured file list from `cov-manage-emit`. You do not supply those and cannot
get them wrong.

Run with `--validate-only` first. It reports every problem it can find without
writing anything, which is the cheap way to discover that a corpus has mixed
analyzer versions or a stream carrying two releases on one date.

Choose `--slug` to name what distinguishes this dataset from another of the
same project -- the version span, the checker configuration, the analyzer
version -- because that is the question someone browsing the archive is asking.
`releases24-defaults` answers it; `final` does not.

## MANIFEST.json, concretely

Abridged from a real dataset. Tools read this; nothing else on disk duplicates
it.

```json
{
  "schema": 1,
  "project": "proftpd",
  "dataset": "2026-10-13-releases24-defaults",
  "description": "24 releases across five branch streams, 2015-2025 ...",
  "built_at": "2026-10-13T18:22:04-04:00",
  "analysis": { "version": "2025.9.0" },
  "commit": {
    "strip_path": "/home/etice/demo/proftpd",
    "strip_path_per_tag": { "v1.3.5a": "/home/etice/demo/proftpd" },
    "suggested_project": "proftpd"
  },
  "streams": [
    { "tag": "v1.3.5a", "date": "2015-05-27", "stream": "proftpd-1.3.5", "cids": 176 }
  ],
  "source": {
    "url": "https://github.com/proftpd/proftpd.git",
    "shas": { "v1.3.5a": "379bdb0d413f9489768c29c3a36e7bc854c85395" }
  },
  "counts": { "versions": 24, "streams": ["proftpd-1.3.5"], "cids_at_tip": 112 },
  "audit": { "present": true, "triage_records": ["audit/v1.3.9/triage.json"] }
}
```

`strip_path` is the single root when the whole corpus shares one, and `null`
otherwise; `strip_path_per_tag` always carries every version's own root. Build
roots need not match across versions -- merge keys are path-independent and
`--strip-path` is per-commit -- so a corpus assembled from differently-rooted
builds is legal. What must hold is that the *stripped* paths agree, which is
what publish checks.

## Two practical traps

**Keep the archive root short on Windows.** An idir nests deeply
(`emit/<host>/config/<md5>/<compiler>-config-N/...`), and the archive adds a
project and a dataset level above that. A long root pushes ordinary files past
`MAX_PATH` and a naive copy fails partway. `publish_dataset.py` uses the
extended-length prefix so it works regardless, but anything else touching the
tree -- Explorer, a zip tool, a hand-rolled copy -- may not.

**A failed publish must leave nothing.** Validation failing writes nothing by
construction, but assembly can fail too (a full disk, a path limit, an
interrupted copy). A half-copied dataset in the library is worse than no
dataset, because it looks usable. `publish_dataset.py` removes the partial
directory and says so.

## Datasets are immutable

Once published, a dataset is not edited. Re-publishing with a new slug costs
only disk, and `SHA256SUMS` is the seal: it exists for periodic archive
integrity audits, not for the commit path -- ordinary file copying already
detects corruption. If something needs changing, publish a new dataset and let
the old one age out.
