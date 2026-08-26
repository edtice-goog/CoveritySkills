# Target state: bringing an idir current without knowing where it came from

The main procedure is **provenance-based**. It asks "what commit was this idir
built from?", diffs that against the working tree, and re-emits the difference.
Gate 2 exists to enforce it: no known commit, no skill.

That is fast and simple when the idir comes from CI with a tag attached. It has
two weaknesses:

- **It fails closed on unknown provenance.** An idir from a colleague, a
  scratch build, or a job whose tag was lost is unusable, even though the
  content is perfectly good.
- **It trusts a claim about the past.** If anything touched the tree outside
  git -- a partial build, a generated file, a hand edit, a breakdown in process
  discipline -- the git diff does not know, and the idir silently disagrees
  with the tree.

There is a second approach that has neither weakness: **ignore where the idir
came from and compare its contents directly against the target.**

## The emit stores the source, and will give it back

`cov-manage-emit extract-files` writes out the files the emit actually holds --
**including headers**, not just primary source files:

```bash
cov-manage-emit --dir <idir> extract-files \
    --output-dir <tmp> --regex '.*\.(c|h|cc|cpp|hpp)$'
```

It also writes `emit-file-map.json`, mapping each recorded emit path to its
extracted location. That handles the path-remapping problem for free: you do
not have to infer a capture root, because the map states it.

Measured 2026-08-25 on an FFmpeg idir (2,060 TUs, `cov-analysis-linux64-2025.9.0`):

| | |
|---|---|
| extraction rate | **115 files/s** (230 files in 2 s, 2.5 MB) |
| extracted vs working tree | **230 / 230 byte-identical** |
| implied cost, whole FFmpeg emit | ~35 s |

So an exact, provenance-free answer costs seconds to a couple of minutes, and
is I/O-bound rather than CPU-bound -- it can run while the developer does
something else.

## Why not just use the recorded hash

Because it is not a content hash. `cov-manage-emit list-json` reports
`primaryFileHash`, a 32-hex value that looks like an MD5 and is not one.
Measured against 200 files present on disk:

| candidate | matches |
|---|---|
| `md5(raw bytes)` | **0 / 200** |
| `md5(CRLF -> LF)` | 0 / 200 |
| `md5(trailing whitespace stripped)` | 0 / 200 |
| `sha1[:32]` | 0 / 200 |
| `md5(path)` | 0 / 200 |
| `primaryFileSizeInBytes` | **200 / 200 exact** |

Do not use `primaryFileHash` as a source-identity gate; its construction is
undetermined. `primaryFileSizeInBytes` is exact and free, which makes it a
sound **cheap pre-filter** -- a size mismatch is a definite change -- but size
equality is not content equality, so it cannot stand alone.

**Recommended layering**, cheapest first:

1. `primaryFileSizeInBytes` vs the file on disk. Mismatch -> changed, no
   further work needed to know it.
2. `extract-files` + byte compare for everything that survives step 1. Exact.
3. Re-emit what differs.

## What this buys, and what it does not

Buys:

- **No Gate 2.** Provenance is irrelevant; an idir of unknown origin is usable.
- **Detects drift from any cause**, not just committed changes -- which is
  precisely the failure mode that process discipline is supposed to prevent
  and sometimes does not.
- **Sees headers directly.** The provenance route diffs git and then leans on
  the build system to work out the header cascade. This route knows which
  headers differ, as a fact rather than an inference.

Does not buy:

- **The TU set to re-emit.** Knowing which *files* differ is not the same as
  knowing which *translation units* must be re-emitted, because a changed
  header affects every TU that includes it. The emit holds that relation, but
  no queried subcommand for "which TUs include this header" has been found
  here. Until one is, the build system still answers that question -- so
  **Gate 1 still applies** even though Gate 2 does not.
- **Speed on a huge emit.** Cost scales with the number of files. Measure
  before assuming; 115 files/s was one box, one idir, I/O bound.

## The process-discipline alternative, and why it is not a substitute

The whole problem disappears if the idir is updated every time anything is
compiled. With `--record-only` the overhead is small -- measured on a Linux
kernel CI dashboard:

| | wall | vs plain build |
|---|---|---|
| plain build | 4 m 34 s | 1.0x |
| `cov-build` **record-only** | 6 m 41 s | **1.5x** |
| `cov-build` record-with-source | 8 m 15 s | 1.8x |
| `cov-build` normal | 17 m 34 s | 3.8x |

1.5x is cheap enough to leave on permanently, and a team that does so never
needs any of this.

The catch is that it is a **process** guarantee, not a technical one. Any
breakdown -- one build run outside the wrapper, one developer who skips it, one
script that bypasses it -- produces an idir that is silently wrong rather than
obviously stale. Target-state comparison is the check that survives that,
because it verifies content instead of trusting that a procedure was followed.

Prefer discipline for cost. Keep target-state comparison for trust.
