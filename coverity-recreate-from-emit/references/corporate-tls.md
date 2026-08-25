# TLS interception: four trust stores, and the one that fails silently

Applies whenever this skill talks to Coverity Connect -- fetching a reference
idir, running the cost estimator, running `cov-commit-defects
--preview-report-v3` -- from a machine behind a TLS-inspecting proxy (Zscaler,
Netskope, Blue Coat, corporate MITM of any brand). It is not specific to idir
reuse, but it blocks the skill before step 1 and diagnoses badly, so it is
documented here.

## The shape of the problem

A TLS-inspecting proxy re-signs traffic with a corporate root CA. The corporate
root is installed in the **operating system** trust store by IT. Every runtime
that does **not** read the OS store then fails -- and they fail differently.

On a single machine there are commonly **four independent trust stores**:

| runtime | reads | override |
|---|---|---|
| curl | its own CA bundle | `CURL_CA_BUNDLE` |
| git | its own CA bundle | `GIT_SSL_CAINFO` (or `http.sslcainfo`) |
| **Go** binaries | the **system** store | **`SSL_CERT_FILE`** |
| **Java** (JVM) | the JVM's own **`cacerts`** | `-Djavax.net.ssl.trustStore` |
| python-requests | certifi | `REQUESTS_CA_BUNDLE` |

Two of these bite hard:

- **Go ignores `CURL_CA_BUNDLE`.** Setting the curl and git variables makes
  `curl` and `git` work, which is exactly the evidence that convinces you the
  network is fine. Any Go tool then fails anyway.
- **The JVM carries its own `cacerts` and ignores all of the above.** Coverity
  ships **its own JDKs** -- measured on `cov-analysis-linux64-2025.12.2`, there
  are three (`jre/`, `jdk21/`, `jdk25/`), each with a separate
  `lib/security/cacerts` holding 109 trusted certs and **zero** corporate
  entries. Updating the OS store does not touch them.

## Why it diagnoses badly

Interception is usually **selective**. Measured on the subject network: a
handshake to `github.com` returned **200**, while `chromium.googlesource.com`
failed -- same machine, same instant, same trust store. So "the network works"
and "TLS works" both appear true while one specific host is broken.

The Go failure mode is worse than an error. A `depot_tools` fetch hung on
`anon_pipe_read` with an **empty output directory and nothing on stderr** for
thirteen minutes: the parent was waiting on a cipd child that could not
complete a handshake. There was no error to search for.

The Java failure at least names itself:

```
SSLHandshakeException: (certificate_unknown) PKIX path building failed:
sun.security.provider.certpath.SunCertPathBuilderException
```

Read `PKIX path building failed` as **"this JVM has never heard of your
corporate CA"**, not as a server problem.

## Procedure

**1. Confirm interception and capture the root.** Compare the issuer the server
presents against what you expect:

```bash
echo | openssl s_client -connect <host>:443 -servername <host> 2>/dev/null \
  | grep -E "^(subject|issuer)"
```

An `issuer` naming your security vendor confirms it. Export the corporate root
from the OS store that already trusts it (Windows shown; on Linux it is usually
already under `/usr/local/share/ca-certificates/`):

```powershell
$c = Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Subject -match '<vendor>' } | Select-Object -First 1
$b = [Convert]::ToBase64String($c.RawData, 'InsertLineBreaks')
[IO.File]::WriteAllText('corp-root.pem', "-----BEGIN CERTIFICATE-----`n$b`n-----END CERTIFICATE-----`n")
```

**2. Build one bundle and export it under every name.** Prefer this to editing
system trust stores: it is scoped, reversible, and leaves the machine's
security posture alone.

```bash
cat /etc/ssl/certs/ca-certificates.crt corp-root.pem > "$CA"
export SSL_CERT_FILE=$CA CURL_CA_BUNDLE=$CA GIT_SSL_CAINFO=$CA
export REQUESTS_CA_BUNDLE=$CA NODE_EXTRA_CA_CERTS=$CA
```

`SSL_CERT_FILE` is the one that fixes Go. Do not omit it because curl already
works.

**3. Give the JVM its own store.** A PEM bundle will not do; the JVM needs a
keystore. Copy Coverity's and add the root -- copy, do not edit in place, so
the install stays pristine and survives upgrade:

```bash
COV=/path/to/cov-analysis-<platform>-<version>
cp "$COV/jdk21/lib/security/cacerts" ./cov-cacerts-corp.jks && chmod u+w ./cov-cacerts-corp.jks
"$COV/jdk21/bin/keytool" -importcert -noprompt -trustcacerts \
  -alias corp-root -file corp-root.pem \
  -keystore ./cov-cacerts-corp.jks -storepass changeit
```

Then point every Coverity JVM at it **without changing any command line**:

```bash
export JAVA_TOOL_OPTIONS="-Djavax.net.ssl.trustStore=$PWD/cov-cacerts-corp.jks -Djavax.net.ssl.trustStorePassword=changeit"
```

`JAVA_TOOL_OPTIONS` is honored by every JVM at startup, so it reaches Coverity's
bundled JDKs through wrapper scripts you do not control. It prints one
`Picked up JAVA_TOOL_OPTIONS:` line to stderr -- harmless, but if a script
parses Coverity stderr strictly, use `-Djavax.net.ssl.trustStore` on the
specific command instead.

**Verify before proceeding**, against the host that failed, not a host you
already know works:

```bash
"$COV/jdk21/bin/java" -Djavax.net.ssl.trustStore=./cov-cacerts-corp.jks \
  -Djavax.net.ssl.trustStorePassword=changeit TlsTest.java https://<connect-host>/
```

## Note on scope

`changeit` is the JDK's documented default `cacerts` password and is not a
secret. This procedure adds a CA your organization already requires you to
trust; it does not weaken verification and it is **not** the same as disabling
it. Never resolve this with `GIT_SSL_NO_VERIFY`, `-k`, or
`-Dcom.sun.net.ssl.checkRevocation=false` -- those turn off the check that the
proxy exists to perform, and on a Connect connection they expose an auth key.

Related: rule 28 -- the host you connect to comes from the **user**, never from
the auth key file.
