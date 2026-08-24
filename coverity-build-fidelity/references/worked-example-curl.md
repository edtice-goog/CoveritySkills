# Worked example: curl against its official release binary

The production topology, run for real: an **official vendor release binary**
as reference `O`, plus a local native build `N` and a local Coverity build `C`.
Two builds, exactly as a real engagement would have.

Result: **`D(O,N)` empty and `K = D(O,C)` empty.** The rebuild is byte-identical
to the shipped artifact, and wrapping it in `cov-build` changed nothing.

## Reference

`curl-8.21.0_7-win64-mingw.zip` from `curl.se/windows`, SHA256 verified against
the publisher's `hashes.txt`.

## Pre-flight rejected the obvious comparison

The workspace already had a local MSVC build of curl 8.21.0. Comparing it to
the official binary would have produced numbers with no meaning:

| | Official | Local MSVC |
|---|---|---|
| Size | 3,846,248 | 6,026,240 |
| Linker version | 14.0 | 14.44 |
| Sections | `.text .rdata` **`.buildid`** `.data .pdata` **`.note .rodata .tls`** `.rsrc .reloc` | `.text .rdata .data .pdata .rsrc .reloc` |
| Debug entry | `EX_DLLCHARACTERISTICS` | `POGO` |
| Signed | yes (Authenticode) | no |

`.buildid`, `.note`, `.rodata`, `.tls` are llvm-mingw signatures with no MSVC
counterpart. **Step 1 pre-flight is what saves the two builds** that would
otherwise have been spent producing a meaningless `INCOMPARABLE`.

## Reproducing the vendor build exactly

The official Windows binaries are **not built on Windows**. The publishing job
(`win-llvm`, the one carrying `environment: production` and the signing
secrets) runs on `ubuntu-26.04` inside a digest-pinned Debian container,
cross-compiling with downloaded llvm-mingw. Everything had to match:

| | |
|---|---|
| Commit | `c791028a` -- "8.21.0_7 with libpsl 0.23.2 and certdata 2026-07-15" |
| Toolchain | llvm-mingw `20260616`, clang 22.1.8, SHA256-verified against the repo's pin |
| Container | `debian:testing-20260803-slim@sha256:90e4367c...` |
| Config | `CW_CONFIG=main-werror-win`, `CW_LLVM_MINGW_DL=1`, `CW_LLVM_MINGW_ONLY=1` |
| TLS backend | LibreSSL 4.3.2 (the default for this config; confirmed from the official binary's `--version`) |

Two checks that could each have invalidated the run:

- **`_REV` only feeds `_REVSUFFIX` in package filenames**, never compiled into
  the binary -- so the `_7` label does not affect content.
- The build is genuinely reproducible: **`_peclean.py` normalizes PE
  timestamps** deterministically against a reference mtime, which is why the
  official binary has a fixed timestamp and no `/Brepro`.

## Result

Both sides normalized identically: Authenticode signature excised
(`pestrip.py`, 3,688 bytes) and PE checksum zeroed. Both are forced -- we do
not have curl's signing key, and signing recomputes the checksum. Nothing else
was touched.

| Artifact | official vs native | official vs Coverity | native vs Coverity |
|---|---|---|---|
| `curl.exe` (3,842,560 B) | **identical** | **identical** | identical |
| `libcurl-x64.dll` | **identical** | **identical** | identical |

```
D(O,N) = empty        ->  K = D(O,C) \ empty = D(O,C) = empty
```

With `D(O,N)` empty there is **no noise floor to subtract**, so any difference
would have needed no interpretation at all. This is the strongest form the
methodology can take, and it is only available when the vendor ships
reproducible builds.

Before normalization the single difference was 3 bytes in
`optional.CheckSum` -- an artifact of stripping the reference's signature, not
a real difference. `bindiff.py` resolved it via the fast path with zero
unresolved regions.

## Capture arm

```
Emitted 1620 C/C++ compilation units (91%) successfully
failures 153   successes 1620   recoverable-errors 0
```

`scan-transparency/unconfigured-compilers` named only:

```
/root/cfw/libpsl/_a64-win-ucrt-bld/clang
/root/cfw/libpsl/_x64-win-ucrt-bld/clang
/usr/bin/apt-get
/usr/lib/apt/apt-extracttemplates
```

The apt entries are heuristic false positives. **745 unique product sources**
were emitted across all ten components:

| libressl | zlibng | ngtcp2 | brotli | nghttp3 | zstd | nghttp2 | curl | libssh2 | libpsl |
|---|---|---|---|---|---|---|---|---|---|
| 505 | 58 | 48 | 35 | 32 | 30 | 26 | 7 | 2 | 2 |

The build log contains **zero `[ERROR]` lines and zero `cov-emit` non-zero
returns**, so the 153 failures are not emit errors. They are compilations that
produced no translation unit -- overwhelmingly configure probes that fail *by
design* (`check_c_source_compiles` and friends; 600 unique probe files were
seen, 300 probe TUs emitted). A `< 100% -> fail` gate rejects this build for no
reason.

## Three traps this run exposed

**Unity builds destroy naive TU reconciliation.** curl-for-win sets
`CMAKE_UNITY_BUILD=ON` with `CMAKE_UNITY_BUILD_BATCH_SIZE=30`. curl's entire
tool and library appear as **7 unique product sources**, and libssh2 as 2.
Reconciling emitted TUs against source-file counts would report a catastrophic
capture gap where none exists. Check for unity builds before counting.

**Capturing inside a container keys the emit DB to the container hostname.**
Reading the intermediate directory from the host fails with:

```
No emit DB found for this host ("BD-46312") ... but one was found for host "8b1f70642fbf".
Please run cov-manage-emit --dir <intermediate-directory> reset-host-name
```

**Vendor build scripts are not built for slow or inspected networks.**
curl-for-win downloads with `--max-time 80` and no resume; the 82 MB toolchain
could not finish in 80s and every retry restarted from zero. And corporate TLS
inspection is *selective* -- Zscaler intercepted `ftp.openbsd.org` and
`pgpkeys.eu` while passing GitHub through untouched, which made the failure
look random rather than systematic. Neither risks integrity here: every
download is SHA256- and GPG-verified by the build itself.

## Open item

libpsl's build directory contains a local `clang` wrapper that went
unconfigured. libpsl emitted exactly its two real library sources (`psl.c`,
`lookup_string_in_fixed_set.c`), so the capture looks complete -- but that is
inference, not proof, and the wrapper is exactly the shape of thing that
silently swallows compilations. Worth settling before this example is cited as
a clean 100%.

## Reproducing

```bash
# in WSL/Linux with podman
git clone https://github.com/curl/curl-for-win.git && cd curl-for-win
git checkout c791028a
# pre-seed llvm-mingw (verify against LLVM_MINGW_LINUX_X86_64_HASH in _versions.sh)
export CW_CONFIG='main-werror-win' CW_LLVM_MINGW_DL=1 CW_LLVM_MINGW_ONLY=1
podman run --rm -v "$PWD:$PWD" -w "$PWD" <pinned-image> sh -c ./_ci-linux-debian.sh
```

Coverity arm: identical, wrapped in `cov-build --dir idir-cov --config <cfg>`,
where `<cfg>` was built with `--template` only (see
`coverity-compiler-configuration`).
