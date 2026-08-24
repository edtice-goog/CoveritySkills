# The transformation probe

How to measure the way a given Coverity version turns a compiler command line
into a `cov-emit` command line, instead of assuming it is unchanged.

## What is being measured

Capture is two stages:

```
compiler argv  --[cov-translate]-->  cov-emit argv  --[cov-emit]-->  emitted TU
```

`cov-translate` is where the compiler model gets applied: it takes the
build's own command line, consults the compiler configuration (which, under a
template config, was probed at build time for this exact argument set), and
produces a fully-resolved `cov-emit` invocation.

That second argv is the thing that determines what the front end actually
parses. If it differs between two Coverity versions for the same input, then
"same code, newer analyzer" is not quite true -- the code was *read*
differently, before any checker ran.

The probe measures that function, for the argument sets your build actually
used.

## Why the control is not optional

The probe compares a recorded output against a freshly generated one. Between
those two runs, several things differ that have nothing to do with the Coverity
version: the target idir, the temp directory, the config instance, the machine,
possibly the compiler's own point release.

Run the probe under the **version that wrote the idir** and you get a direct
measurement of that environmental noise floor. If it comes back `IDENTITY`, the
normalization is sufficient and any residual in the cross-version run is
attributable to the version. If it does not, you are looking at your own
environment and cannot say what the version contributed.

This is the same move as `coverity-build-fidelity`'s native control pair, and
the same move as producing Method C before opening the idir: **a delta without
a control is an argument from plausibility, not evidence.**

## Procedure

### 1. Get a recorded pair

From the old idir, under an install whose emit format matches:

```bash
cov-manage-emit --dir <idir> list-capture-invocations > inv.json
```

`translation-units[i]` links the two sides by id:

```
cov-translate-invocation-id  ->  cov-translate-invocations[]  (the input)
cov-emit-invocation-id       ->  cov-emit-invocations[]       (the output)
```

Keep the recorded working directory too (`working-directory-id`, resolved
through the `files` table). Relative `-I` flags are passed through verbatim, so
the cwd is part of the input.

### 2. Make an empty source file

```bash
: > empty.c
```

The probe does not need the real source. `cov-translate` computes the emit
argv from the *command line and configuration*, not from the file's contents.
An empty file makes the probe fast, side-effect-free, and runnable even when
the original sources are gone.

Recreate enough of the directory structure that relative include paths resolve
(`-I..`, `-I../include`). They are not dereferenced during the probe, but
keeping the shape makes the comparison honest and avoids incidental warnings.

### 3. Re-run the recorded input under the version under test

Substitute the source filename, keep everything else:

```bash
cd <recorded-cwd-equivalent>
<install>/bin/cov-translate --dir <scratch-idir> --config <cfg>/coverity_config.xml \
    --dryrun  gcc <recorded flags> -c empty.c -o empty.o
```

`--dryrun` "prints out the Coverity compiler command line it would normally run
without actually running it". Verified: `--dryrun` and a real run produce the
same `cov-emit` line, differing only in the per-session `--ignore_path` temp
directory. So the probe can measure the transformation without emitting
anything.

Use a real run instead when you want the generated line to be recorded in an
idir you can re-read later; the answer is the same.

### 4. Normalize, then diff

Compare the generated `cov-emit` argv against the recorded one, token by token,
after masking the elements that vary for non-version reasons.

## The normalization set

Two different operations, and conflating them loses real signal:

**MASK** -- environment noise. Dropped, or replaced by a placeholder. Each
entry was observed to vary between two runs of the *same* version, which is
what qualifies it.

**TRANSFORM** -- version-owned artifacts. These legitimately live under
whichever install or idir is running, so the token is **kept** and only its
path root is rewritten. That way a difference in install root is absorbed,
while a genuine *presence* asymmetry still surfaces as a diff.

Do not extend either set to make a delta disappear -- if something new varies,
find out why first.

| Token | Op | Why |
|---|---|---|
| `--dir=<path>` | mask | the target idir, chosen per run |
| `--ignore_path=<path>` | mask | per-session temp directory, new every invocation. The *count* can differ too -- a build-time capture had two, a standalone probe had one |
| `--coverity_config_md5=<hex>` | mask | identity of the configuration in use |
| the source filename | mask | substituted by the probe itself |
| `<idir>/emit/<host>/config/<32-hex>/...` | transform | config instance hash. The `--pre_preinclude` compat headers live under it and belong to the running version |
| `--preinclude <...>/user_nodefs.h` | transform | version-owned; see below |

Everything else is signal. In particular these are **not** maskable, and a
difference in any of them is a real finding: `--comp_ver`, `--gnu_version`,
`--type_sizes`, `--type_alignments`, `--size_t_type`, `--wchar_t_type`,
`--ptrdiff_t_type`, every `--sys_include`, every `-D`, every `-I`, the language
level (`--c11` / `--c17` / `--c++NN`), and the builtin/emulation flag block.

### user_nodefs.h deserves its own note

The pre-includes and nodefs are **always pulled from the same product version
as `cov-emit`**. They are not something the old build hands forward; each run
supplies its own from the install it is using. That is why they are
transformed rather than masked, and why you must never copy the *old*
version's copy into a *new* version's replay.

An installation ships a `user_nodefs.h` inside its own `config/` directory. A
config directory you create yourself with `cov-configure --config <newdir>`
does **not** get one, so a probe using a fresh config silently loses the flag.
`emit_probe.py probe` seeds it from the install being probed and prints that it
did. When present, the emit line gains:

```
--preinclude <config>/template-gcc-config-0/../user_nodefs.h
```

Two consequences:

- If the original build used the install's own config directory (check
  `BUILD.metrics.xml`, `<metric><name>config</name>`) and your probe uses a
  fresh one, the control will show this as a spurious *presence* difference.
  That is your setup, not the version -- seed the file and re-run.
- `user_nodefs.h` is where user-defined nodefs and models go, so a customized
  one is a **semantic input to the analysis**. Carry the *customization*
  forward, not the file: diff the old install's copy against a stock copy of
  the same version, and if it differs, apply that difference to the new
  install's own copy. Replacing the new version's file wholesale with the old
  version's is the one thing not to do -- these travel with the product
  version, and a stale one can disagree with the front end that reads it.
  (Measured on this project: the 2024.12.1, 2025.9.0 and 2025.12.2 copies were
  byte-identical stock, so it made no difference here. Do not assume that.)

## Reading the result

**`IDENTITY`** -- the two versions generate the same emit line for this input.
Replay via `cov-translate` is sound for this argument set.

**A residual** -- classify each differing token as environment, cosmetic, or
semantic (see SKILL.md Step 6). For a semantic one, do not stop at "the
versions differ": ask the **compiler** which version is right. Coverity models
each compiler's flag handling by hand, so a delta is frequently a *correction*
rather than a change, and a correction must be accepted rather than pinned --
pinning it reproduces a known-wrong parse and calls it a control.

**Control failure** -- stop; fix the environment before interpreting anything.

## Coverage: probe more than one argument set

A template configuration is probed **per distinct argument set**, which is why
`template-<name>-config-N` directories multiply during a build (rule 7). It
follows that the transformation can differ per argument set. One probe of one C
file does not characterize a build that also compiles C++, or that uses
`-m32` on part of the tree, or that mixes `-std` levels.

Sample deliberately:

- one per language (`gcc` and `g++` arms are different configs)
- one per distinct `-std` / architecture flag group
- and say in the report which sets you probed and which you did not

## Worked result

Measured 2026-08-24 against a real archived idir. Full session in
`worked-example-proftpd.md`. Reported here as an illustration of the output
shape -- **not** as a compatibility table to look up. Formats and defaults move
nearly every release; re-run the probe for the pair you actually have.

Control, old version against its own recorded line: `IDENTITY` (after the
`user_nodefs.h` setup difference was found and explained).

Cross-version, one release family apart, 60 tokens each:

```
--- recorded
+++ generated
   --builtin_emulation
   --gcc
 - --c11
 + --c17
   --gnu_version
   130300
```

One token. Semantic. Everything else identical, including the full type-model
block and every system include path.

The lesson is not "expect `--c11 -> --c17`". It is that the transformation is
*almost* identity, which is exactly the condition under which people stop
checking -- and the first pair ever tested under this procedure was not
identity.

The second lesson came from interpreting that delta. gcc 13.3.0 given the same
flags reports `__STDC_VERSION__ 201710L`, so C17 is the compiler's real
default and the older `--c11` was a **mistake in Coverity's model of gcc**, not
a behavioural choice. Such a mistake stays hidden while builds pass `-std=`
explicitly -- as most do -- and surfaces only on the ones that rely on the
default. When choosing argument sets to probe, favour the ones carrying the
fewest explicit flags: that is where model errors live.
