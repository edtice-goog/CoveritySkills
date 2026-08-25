# coverity-compiler-configuration

Part of [CoveritySkills](../README.md).

Gets `cov-configure` right. The rule is short — **always use `--template`** —
and the reason is not obvious, which is why it is so often done wrong.

A template configuration maps a compiler *executable name* to a compiler
*type*, and nothing more. The actual probe is deferred to build time and
repeated for each distinct set of arguments the build uses. Without
`--template`, `cov-configure` probes once at configure time with whatever
arguments and environment happen to exist at that moment — and compiler
behaviour changes with the arguments passed. Data captured under such a
configuration is tainted, and the fix is a fresh config and a fresh
intermediate directory, not an edit.

## What the skill knows that saves time

- The language shortcuts (`--gcc`, `--msvc`, ...) **already produce template
  configurations** and are safe as-is. The danger zone is the explicit
  `--compiler X --comptype Y` form — precisely what you reach for with
  cross-compilers, embedded toolchains, and wrapper scripts
- How to tell a tainted config at a glance: probed configs create
  `gcc-config-0` while template configs create `template-gcc-config-0`, and a
  probed config pins concrete versioned names (`gcc-13`,
  `x86_64-linux-gnu-gcc-13`) where a template config records globs (`gcc`,
  `gcc-*`, `*-gcc`)
- Under `--template` the compiler **need not exist** when you configure, so
  configuration never has to wait on a toolchain the build itself downloads
- `--template` takes a bare executable name, never a path, and never `--version`
- Configure every compiler-shaped executable the build invokes — C++ driver,
  archiver, linker — and the *prefixed* cross names, not the host ones
- Why `template-<name>-config-N` directories multiplying during a build is the
  mechanism working, not a fault

Every claim above was verified against a real Coverity installation.
