# Anatomy of the capture-invocation record

What `cov-manage-emit --dir <idir> list-capture-invocations` returns, and what
each part is evidence of.

Must be run under an install whose emit format matches the idir. Output is
JSON on stdout and it is not small -- roughly 3 MB for a 90-TU C project,
because the include closure of every translation unit is enumerated.

`--no-process-details` suppresses the process details. The default *includes*
them, which is what makes this skill possible.

## Top-level shape

```
type                          "Coverity Capture Invocations"
version                       the tool version that produced this dump
files[]                       interned path table
environment-variables[]       interned name/value pairs
environment-variable-blocks[] named sets of those pairs
cov-build-invocations[]       the outer cov-build process
cov-translate-invocations[]   one per TU -- the ORIGINAL compiler argv
cov-emit-invocations[]        one per TU -- the RESOLVED cov-emit argv
translation-units[]           the join table
link-units[]                  empty for a compile-only capture
metrics                       tu-count, tu-failures, lu-count, lu-failures
```

## `files[]` -- the path table

```json
{ "id": 4, "case-normalized": "\\home\\etice\\proftpd",
           "case-preserved":  "\\home\\etice\\proftpd" }
```

Everything else refers to paths by `id`. Resolve through this table.

**Separator caution.** The separators are rendered by the *reading* tool, not
the writing one. A win64 `cov-manage-emit` reading a Linux-emitted idir prints
`\home\etice\proftpd`. Cosmetic, but it breaks naive path matching and it makes
"is this a Windows or Linux capture?" unanswerable from this field alone. Use
`process-invocation.platform` for that.

## `process-invocation` -- common to all three invocation kinds

```json
{
  "hostname": "BD-46312",
  "pid": 19660,
  "start-time": "2025-05-19T20:08:12Z",
  "end-time":   "2025-05-19T20:08:21Z",
  "exit-code": 0,
  "platform": "Linux x86_64",
  "username": "etice",
  "command-line": [ ... ],
  "working-directory-id": 5,
  "environment-variable-block-id": 2
}
```

`command-line` is a real argv array, not a reconstructed string -- no quoting
ambiguity. `working-directory-id` matters: relative `-I` flags are passed
through verbatim, so the cwd is part of the input to the transformation.

## The three invocation kinds

**`cov-build-invocations`** -- normally one: the outer wrapper, with the build
command as its tail. Its `exit-code` is the build's, and a zero here says
nothing about capture completeness (rule 9).

**`cov-translate-invocations`** -- one per TU. This is **the original compiler
command line as the build issued it**, prefixed by the `cov-translate` path:

```
cov-translate gcc -DHAVE_CONFIG_H -DLINUX -I.. -I../include -g2 -O2 -Wall
              -fno-omit-frame-pointer -fno-strict-aliasing -c pr_fnmatch.c -o pr_fnmatch.o
```

This is the *input* to the transformation probe, and it is also the honest
answer to "what did this build actually compile, and how?".

**`cov-emit-invocations`** -- one per TU, the *output*: a fully-resolved front
end invocation carrying the distilled compiler model.

```
cov-emit --dir=<idir>
         --ignore_path=<per-session temp>
         --pre_preinclude <idir>/emit/<host>/config/<hash>/gcc-config-0/coverity-macro-compat.h
         --pre_preinclude <idir>/emit/<host>/config/<hash>/gcc-config-0/coverity-compiler-compat.h
         --c --coverity_config_md5=<hex>
         --comp_ver 13.3.0  --gnu_version 130300  --gcc  --c11
         --type_sizes=e16Pdlx8fi4s2  --type_alignments=e16Pdlx8fi4s2
         --size_t_type=m --wchar_t_type=i --ptrdiff_t_type=l
         --sys_include=/usr/lib/gcc/x86_64-linux-gnu/13/include
         --sys_include=/usr/local/include
         --sys_include=/usr/include/x86_64-linux-gnu
         --sys_include=/usr/include
         -I.. -I../include  -DHAVE_CONFIG_H -DLINUX -D__OPTIMIZE__
         [--preinclude <config>/../user_nodefs.h]
         pr_fnmatch.c
```

This is the single most useful artifact in the idir for this skill. **The
compiler's probed behaviour is already here** -- version, type model,
alignment, system header search path, predefined macros. That is why the
original compiler need not exist for a replay: rule 1's build-time probe left
its result on disk.

Two of these flags point *inside the old idir*
(`coverity-macro-compat.h`, `coverity-compiler-compat.h`), so they travel with
it. Preserve the old idir; do not extract only the JSON.

## `translation-units[]` -- the join table

```json
{
  "id": 1,
  "cov-build-invocation-id": 1,
  "cov-translate-invocation-id": 1,
  "cov-emit-invocation-id": 1,
  "emit-failed": false,
  "kind": "C",
  "primary-file-id": 35,
  "input-files": [ { "file-id": 6, "kind": "source file", "implicit": false }, ... ]
}
```

This is what makes the probe possible: the (input, output) pair for each TU is
recorded **explicitly linked**, so you are not inferring which emit line came
from which compiler invocation.

`input-files` is the **complete include closure** -- 222 entries for one C file
in the measured project, all of `kind: "source file"`. Uses:

- determine exactly which headers a replay needs, before discovering it the
  hard way
- distinguish "the source is missing" from "a header is missing" when a replay
  falls short
- as a change signal between two idirs that is grounded in real inputs, unlike
  `primaryFileHash` (see `CALIBRATION.md`)

`emit-failed` is per-TU truth about whether the front end succeeded.

## `environment-variables` / `environment-variable-blocks`

Variables are interned as `{id, name, value}`; a block is
`{id, environment-variable-ids: [...]}`. Invocations reference a block.
Measured: 68 distinct variables across 5 blocks (sizes 29, 61, 59, 59, 59) for
a single-project build.

**This is the whole build environment, `PATH` included, and anything else the
build had in scope -- which may include secrets.** `coverity`'s
`references/idir-anatomy.md` flags the same exposure for `build-log.txt` and
`cli-diagnostics.json`. Anything this skill extracts inherits it. Check before
forwarding a `pairs.json`, a replay script, or the idir itself.

## `metrics`

```json
{ "tu-count": 90, "tu-failures": 0, "lu-count": 0, "lu-failures": 0 }
```

`lu-count: 0` on a compile-only capture is structural, not a fault. Cross-check
`tu-count` against `cov-manage-emit list` and the build log's *Emitted N* line;
these are different counts printed in different places and are routinely quoted
as one another.
