# Build-path recovery

In production the reference artifact was built by a CI system whose working
directory you do not control. Paths get embedded in binaries, and a path of a
*different length* shifts every byte after it -- which destroys the offset
alignment the region algebra depends on.

## The key result: length, not content

Measured on `deflate.c.obj`, zlib, MSVC Release. Local build path was 49
characters:

| Reference path | Length | Size | Regions | Differing bytes | Unresolved |
|---|---|---|---|---|---|
| `C:\a\1\s\zlib` | 15 | mismatch (-36) | 154 | **30,341** | 153 |
| `C:\a\1\padpad...pad\zlib` | 49 | equal | 3 | **51** | 2 |

Both are *wrong* paths. The equal-length one produces a legible diff anyway,
and what survives is exactly the path text plus a derived checksum:

```
0x00001558 +41  .debug$S   a: Data\repo-monitoring-workspace\stage3\src
                           b: a\1\padpadpadpadpadpadpadpadpadpadpadpadp
0x00006115 +8   .chks64    a: 77639e153e3dbea1   b: 3672ed8dcfa37192
```

**So: reproduce the exact path when you can. When you cannot, match its
length.** Alignment is what the algebra needs; content merely produces one
easily-classified region. A 34-character length error produced a 600x larger
diff than a 41-character *content* error.

## Probe before you pay

Not every artifact carries a path. Run `paths.py` on the reference first.

| Artifact | Path embedded? | Consequence |
|---|---|---|
| `zlib.dll` (CMake Release) | **no** | Path mimicry unnecessary. 34-char path difference produced 2 differing bytes -- both timestamps. |
| `deflate.c.obj` | yes, in `.debug$S` | Strongly path-sensitive. |

A shipped Release image may be entirely path-immune, in which case skip path
reconstruction for it. Objects are path-sensitive even in Release. **This
decision therefore follows from the comparison scope**: shipping-images-only
comparisons often need no path work at all.

## Evidence sources, best first

1. **PE debug directory CODEVIEW/RSDS `PdbPath`** -- the full PDB path,
   structured and unambiguous. Present whenever a PDB is emitted.
   **Absent in CMake `Release`**, which emits no PDB reference at all; use
   `RelWithDebInfo` builds or other artifacts when available.
2. **The shipped PDB itself**, if delivered alongside -- definitive.
3. **`.debug$S` in COFF objects** -- each object records its own full output
   path. Only useful if objects were delivered.
4. **`__FILE__` strings** from `assert`/`_wassert` in `.rdata`.
5. **Bulk string scan** for anything path-shaped, ASCII *and UTF-16LE*.
   Windows binaries are full of wide strings; a naive scan misses most.

Beware URL schemes: `http://host/` satisfies the drive-letter shape.
`paths.py` guards with `(?![\\/])` after the colon-separator, after
zlib.dll's embedded homepage URL was reported as a candidate build root.

## CI workspace signatures

A partial string plus a known convention is usually enough to reconstruct the
root:

| Pattern | System |
|---|---|
| `C:\a\1\s`, `D:\a\1\s` | Azure DevOps default agent workspace |
| `D:\a\<repo>\<repo>` | GitHub Actions (Windows runner) |
| `/__w/<repo>/<repo>` | GitHub Actions (container runner) |
| `C:\jenkins\workspace\<job>` | Jenkins |
| `C:\BuildAgent\work\<hash>` | TeamCity |
| `/builds/<group>/<project>` | GitLab CI |

Encoded in `paths.py:CI_SIGNATURES`.

## Verify the guess -- do not trust it

Asking the user is legitimate and fast, but users misremember. **The artifact
adjudicates.** After building locally at the candidate path, re-run `paths.py`
on your own output and confirm the recovered path strings match the
reference's. If they do not, the guess was wrong and the fidelity verdict must
not be issued as though it were right.

This closes the loop: the path guess is confirmed or refuted by evidence, not
by assertion.

## Degradation ladder

1. Exact path recovered and verified -> full byte-region basis.
2. Length matched, content wrong -> full basis; expect one path region per
   artifact plus derived checksums. Classify and move on.
3. Length unknown -> alignment lost on path-carrying artifacts. Drop to a
   coarser basis (Step 2 of SKILL.md) for those artifacts only; artifacts that
   do not carry paths are unaffected and keep their finer basis.
4. Nothing recoverable and everything path-carrying -> fall back to
   calibration topology and report the weaker claim honestly.
