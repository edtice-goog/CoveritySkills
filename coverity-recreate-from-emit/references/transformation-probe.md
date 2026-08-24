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

Each entry here was observed to vary between two runs of the *same* version,
which is what qualifies it for masking. Do not extend this set to make a delta
disappear -- if something new varies, find out why first.

| Token | Why it varies |
|---|---|
| `--dir=<path>` | the target idir, chosen per run |
| `--ignore_path=<path>` | per-session temp directory, new every invocation. The count can differ too -- a build-time capture had two, a standalone probe had one |
| `<idir>/emit/<host>/config/<32-hex>/...` | config instance hash; the `--pre_preinclude` compat headers live under it |
| `--coverity_config_md5=<hex>` | identity of the configuration in use |
| `--preinclude <...>/user_nodefs.h` | present iff the config directory contains one -- see below |
| the source filename | substituted by the probe itself |

Everything else is signal. In particular these are **not** maskable, and a
difference in any of them is a real finding: `--comp_ver`, `--gnu_version`,
`--type_sizes`, `--type_alignments`, `--size_t_type`, `--wchar_t_type`,
`--ptrdiff_t_type`, every `--sys_include`, every `-D`, every `-I`, the language
level (`--c11` / `--c17` / `--c++NN`), and the builtin/emulation flag block.

### user_nodefs.h deserves its own note

An installation ships a `user_nodefs.h` inside its own `config/` directory. A
config directory you create yourself with `cov-configure --config <newdir>`
does **not** get one. When it is present, the emit line gains:

```
--preinclude <config>/template-gcc-config-0/../user_nodefs.h
```

Two consequences:

- If the original build used the install's own config directory (check
  `BUILD.metrics.xml`, `<metric><name>config</name>`) and your probe uses a
  fresh one, the control will show this pair as a spurious difference. That is
  your setup, not the version.
- `user_nodefs.h` is where user-defined nodefs and models go. If the original
  team customized it, it is a **semantic input to the analysis** and must be
  carried into any replay. Diff it, do not assume it is stock.

## Reading the result

**`IDENTITY`** -- the two versions generate the same emit line for this input.
Replay via `cov-translate` is sound for this argument set.

**A residual** -- classify each differing token as environment, cosmetic, or
semantic (see SKILL.md Step 6). Semantic differences require an explicit
accept-or-pin decision, recorded in the report.

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
