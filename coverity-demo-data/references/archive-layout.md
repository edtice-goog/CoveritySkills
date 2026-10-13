# Archiving a dataset: standard layout

A demo dataset is expensive to build and cheap to reuse, so it belongs in a
shared library rather than on the machine that happened to build it. This is
the layout for that library. Its purpose is narrow and worth stating: **the
next person to want this data should not have to interrogate the directory to
find out how to use it.**

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
      audit/                        false-positive verdicts
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
