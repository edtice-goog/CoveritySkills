# Ephemeral fields by format

Fields that differ between two runs of an identical build *by construction*.
These form the fast path: `pe.py` resolves them from parsed structure, so the
model is never asked to adjudicate a timestamp. Everything the fast path does
not resolve is, by definition, the signal.

Every entry below was observed in real runs, not taken from documentation.
Where a field exists in the format but did not vary in the observed builds,
that is noted -- it still needs handling, because it *will* vary elsewhere.

## Windows -- PE image (.exe, .dll)

| Field | Offset source | Notes |
|---|---|---|
| `coff.TimeDateStamp` | COFF header +4 | Unix seconds. Always varies unless `/Brepro`. |
| `optional.CheckSum` | optional header +64 | Was **0** in CMake Release zlib -- linker did not compute it. Varies on signed and driver binaries. |
| `debug[*].TimeDateStamp` | each debug directory entry +4 | One per entry. MSVC Release emitted a `POGO` entry. |
| `debug.CODEVIEW.RSDS.Guid` | RSDS record +4, 16 bytes | New GUID every link. Absent when no PDB is emitted. |
| `debug.CODEVIEW.RSDS.Age` | RSDS record +20, 4 bytes | |
| `debug.CODEVIEW.RSDS.PdbPath` | RSDS record +24, NUL-terminated | **Not ephemeral in the same sense** -- it is path-dependent, and its *length* affects alignment. Treat as environment, not noise. |
| `certificate_table` | data directory 4 | Authenticode. Excise, do not diff. |

`/Brepro` replaces the COFF timestamp with a content hash and adds an
`IMAGE_DEBUG_TYPE_REPRO` (16) debug entry. **Detect it on the reference
artifact**: if present, `E` collapses toward empty and every remaining
difference is meaningful. Do not add `/Brepro` to your local builds if the
reference did not use it -- that changes the artifact.

**CMake `Release` emits no PDB and therefore no CODEVIEW/RSDS record at all.**
Confirmed on zlib: `pdb_path` is `None`, and the only debug entry is `POGO`.
`RelWithDebInfo` does emit one. This matters for path recovery, which loses its
best evidence source.

## Windows -- bare COFF object (.obj)

No `MZ`/`PE` wrapper; the COFF header sits at file offset 0.

| Field | Offset | Notes |
|---|---|---|
| `coff.obj.TimeDateStamp` | +4 | The only ephemeral field observed. 34 of 34 objects differed here and nowhere else. |

Two header variants:

- **Classic COFF** -- `machine` (uint16) at offset 0, `TimeDateStamp` at +4.
- **bigobj** (`/bigobj`) -- signature `00 00 FF FF`, then version, machine at
  +6, `TimeDateStamp` at +8.

Objects also carry **`.debug$S`**, MSVC's CodeView symbol section, which holds
the object's own full output path. That makes objects strongly path-sensitive
even in Release builds -- see `build-path-recovery.md`.

**`.chks64`** holds per-section checksums. It is a *derived* region: it changes
because other content changed. Classify as derived only when you can name the
region it depends on.

## Windows -- ar archive (.lib)

MSVC import and static libraries are `ar` archives (`!<arch>\n`), 60-byte
member headers: name(16) date(12) uid(6) gid(6) mode(8) size(10) `` `\n ``(2).
Members are 2-byte aligned.

| Field | Offset | Notes |
|---|---|---|
| `ar.member[NAME].Date` | member header +16, 12 bytes | ASCII decimal seconds, one per member. zlibstatic.lib had 17. |
| inner `coff.obj.TimeDateStamp` | per COFF member | Recurse into members; offsets shift by the member body offset. |

Members named `/`, `//`, `/N` are linker symbol tables and long-name tables,
not objects.

An **import library** may be fully deterministic -- `zlib.lib` was
byte-identical across all runs while `zlibstatic.lib` was not.

## Measured baseline -- zlib, MSVC 2022 (14.44), Ninja, Release

Three native builds, same directory. 39 artifacts, **zero unresolved regions**:

| Format | Files | Signature |
|---|---|---|
| PE image | 3 | `coff.TimeDateStamp`, `debug[POGO].TimeDateStamp` |
| COFF object | 34 | `coff.obj.TimeDateStamp` |
| ar archive | 1 | 17x `ar.member[*].Date` + inner `coff.obj.TimeDateStamp` |
| identical | 1 | `zlib.lib` |

A fourth build under `cov-build` produced **the same signature and no
additional regions** -- `K` empty.

The zero-unresolved property is what makes model adjudication cheap. If a
toolchain's baseline leaves regions unresolved, extend the fast-path tables
here before running production comparisons; otherwise every run hands the model
noise and the signal is buried.

## Not yet characterized

Windows/MSVC, Windows/llvm-mingw (via curl-for-win) and Linux/gcc have been
measured. Before running this skill on any other toolchain, run the
two-native calibration first and confirm the baseline is either empty or
fully resolved.

- **MinGW/gcc on Windows** -- PE container with DWARF. `.comment`,
  `DW_AT_producer`, and `-grecord-gcc-switches` are expected to record the
  compiler command line, which is where `cov-build`'s interposition could
  legitimately land in the artifact. That would be `coverity-benign`, not a
  failure -- but it must be classified, not assumed. `busybox-w32` and
  `mbedtls` are the intended fixtures.
- **Mach-O** -- `LC_UUID`, code signature blob.

## Linux -- ELF / gcc (measured)

**The noise floor is empty.** Two native builds of zlib 1.3.1 with gcc 13.3.0,
CMake + Ninja, Release, same directory: all 21 artifacts byte-identical --
shared library, static archive, both executables, every `.o`. A third build
under `cov-build` was also byte-identical.

This is qualitatively unlike PE. There is no mandatory timestamp field in ELF,
and `.note.gnu.build-id` is a **content hash**, not a clock reading, so it is
stable whenever the content is. `ar` archives built by GNU `ar` in
deterministic mode (`D`, the default on modern binutils) zero the member
timestamps, uid, gid, and mode.

**So on gcc/ELF, use `cmp` first and skip the shape algebra.** With an empty
`D(N,N')` any difference is immediately meaningful, and region diffing buys
nothing. Reach for it only when a plain compare disagrees.

Fields to look at *if* a compare does disagree, in rough order of likelihood:

| Field | Where | Notes |
|---|---|---|
| `.note.gnu.build-id` | `readelf -n` | Content hash -- differs only if content differs. A build-id change is a *symptom*, not noise. |
| `DW_AT_comp_dir` | `readelf --debug-dump=info` | Absolute build directory. Path-sensitive, same length rule as PE. |
| `DW_AT_producer` | same | Records the compiler command line. **The expected place for a legitimate `coverity-benign` classification** if `cov-build` alters the observed command line -- still unobserved. |
| `.comment` | `readelf -p .comment` | Compiler identification string. |
| `ar` member headers | `ar tv` | Zeroed under deterministic mode; non-zero means `U`/non-deterministic archiving. |

`-frecord-gcc-switches` and `-grecord-gcc-switches` embed the command line
explicitly; if the build uses either, treat command-line differences as
expected and classify rather than fail.
