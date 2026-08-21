# C# capture and analysis

Capture differs from C/C++; the analysis workflow (SKILL.md Steps 3-5) is the
same. The facts below were verified against Coverity 2026.6.0 with the .NET 9
SDK on Windows.

## Capture: prefer the real build, and configure C# first

1. **Confirm the code compiles.** Build it the way it's meant to be built —
   for a modern project, `dotnet build <proj>.csproj -c Debug`. Fix compile
   errors with the usual stubbing discipline (don't touch the defect; note
   every change as a caveat). Note that the legacy Framework `csc.exe` at
   `Microsoft.NET\Framework64\v4.0.30319` predates interpolated strings and
   many modern features — use the SDK (`dotnet`) toolchain, or the Roslyn
   `csc`, not that one.

2. **Configure the C# compiler once, or capture emits nothing.**
   ```
   cov-configure --cs
   ```
   Without this, `cov-build` runs your build, reports **"No files were
   emitted"**, and `cov-analyze` then finds nothing — a pure capture failure
   that looks exactly like a clean result. `cov-configure --cs` registers
   `csc`, `dotnet`, `msbuild`, and the Razor compilers.

3. **Capture with `cov-build` around a full rebuild, shared compilation off.**
   ```
   cov-build --dir idir dotnet build <proj>.csproj -c Debug \
       --no-incremental -p:UseSharedCompilation=false
   ```
   Two non-obvious requirements, both about making the compiler a visible
   child process of `cov-build`:
   - **`-p:UseSharedCompilation=false`** — Roslyn's default build server
     (VBCSCompiler) compiles inside a persistent process that `cov-build`'s
     wrapper never sees. Leave it on and you get "No files were emitted".
   - **Force a real compile** — `dotnet build` is incremental; if the
     assembly is up to date it skips compilation and nothing is captured.
     Delete `bin/` and `obj/` (or use `--no-incremental`) so csc actually
     runs. A successful capture prints `Emitted N C# compilation units`.

   Buildless capture (`cov-emit-cs` against loose files) exists and is faster,
   but for C# it sharply widens the capture-vs-miss ambiguity — reserve it for
   cases where you've already proven the build captures cleanly and just want
   speed on a variant. When a verdict is on the line, use the real build.

4. **When "0 defects" might be a capture artifact, prove capture first** —
   the canary probe from capture.md works in C# too: drop an unmissable bug
   (`string s = null; s.ToString();`) into the method, rebuild, re-analyze,
   and confirm it's reported before trusting any silence. `cov-manage-emit
   --dir idir list` and `cov-find-function` confirm what was captured, but
   the canary is faster on a small file.

## Analysis note: C# defaults are not C/C++ defaults

Unlike C/C++, a default `cov-analyze` on C# **does** report a useful set of
security findings, because the SIGMA checkers are on by default (hardcoded
secrets, weak hashes, insecure randomness, uncontrolled search path, ...).
The dataflow injection checkers (SQLI, OS_CMD_INJECTION, LOG_INJECTION) and
some others still need `--webapp-security` and a distrusted source, exactly as
in C/C++. So the two-baseline rung-1 rule still applies, and for C# the
`--webapp-security` / `--recommended-security-checkers` run is especially
worth doing early — it's targeted at exactly the managed-language classes.

## Worked ground truth: hud-rfi `InsecureService.cs`

A single `Main` seeded with a spread of issues. Verified detections:

| Line | Author's intent | Coverity checker | Config |
|------|-----------------|------------------|--------|
| 11 | hardcoded connection string | SIGMA.hardcoded_secret | **default** |
| 20 | (same, as credentials) | HARDCODED_CREDENTIALS | `--webapp-security` |
| 17 | weak RNG for a token | SIGMA.insecure_random | **default** |
| 23 | SQL injection | SQLI | `--webapp-security` + distrusted source |
| 26 | leaked reader/handle | RESOURCE_LEAK | **default** |
| 28 | (see below — MD5) | SIGMA.weak_hash | **default** |
| 28 | (same) | RISKY_CRYPTO | `--webapp-security` |
| 32 | cert-validation bypass | BAD_CERT_VERIFICATION | `--webapp-security` |
| 34 | command injection | OS_CMD_INJECTION | `--webapp-security` + distrusted source |
| 34 | (same call) | SIGMA.uncontrolled_search_path | **default** |

Minimal combined command that reports the injection classes too:
`cov-analyze --dir idir --webapp-security --distrust-all` (10 findings).

### Two botched plants — the reason this file is a stress test

The file contains two seeded "defects" where the author's intent and the code
diverge. Handle both with the three-part answer from SKILL.md Step 1.

- **Line 28-29, MD5 of a string literal.** `md5.ComputeHash(...GetBytes(
  "password"))` hashes the constant `"password"` and prints it — there is no
  sensitive-data flow, so the intended "sensitive data leak" isn't present.
  But Coverity still flags the line, as **SIGMA.weak_hash** (default) and
  **RISKY_CRYPTO** (security) — because MD5 *is* a weak algorithm regardless
  of its input. The test "passes," but for a reason the author didn't design.
  Say so: the finding is real (weak crypto), the intended vulnerability is
  not.

- **Line 25, `Console.WriteLine(reader["Username"])`.** The author appears to
  have intended a sensitive-data leak by logging query results. Enumerating
  usernames to the console is not inherently a sensitive-data exposure, and
  **no info-exposure checker fires on it.** What *does* fire — only under
  `--enable-audit-checkers` — is **LOG_INJECTION**: untrusted DB data flowing
  into a console/log sink. That is a genuine finding, but of a *different
  class* than intended, and only at audit sensitivity (higher false-positive
  cost). The honest answer separates three things: the intended defect
  (sensitive-data leak) is not present; the default run reports nothing here;
  an audit-mode run reports LOG_INJECTION, which is a real but distinct issue.

The lesson these encode: "does a checker fire on this line?" and "is the
author's intended defect real and detected?" are different questions.
Answering only the first — the trap a naive found/not-found verdict falls
into — would call both of these "detected" and mislead the reader.
