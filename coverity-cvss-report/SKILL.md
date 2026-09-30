---
name: coverity-cvss-report
description: >
  Run the Coverity CVSS report the way the documentation says, then audit
  what it produced -- because on a real project a large fraction of the
  rows carry a CVSS vector nobody chose. Use this skill for "generate a
  CVSS report", "score our Coverity findings", "why does this CWE have no
  CVSS score", "why is this issue scored 0", "why is the CVSS column
  empty", "set up cov-generate-cvss-report", "create the CVSS triage
  attributes", "our DISA-STIG report shows CVSS_Severity None", "should we
  write a CVSS profile", and for the question underneath all of them:
  whether a Coverity weakness deserves the vulnerability score somebody is
  about to put in front of an auditor. Coverity finds weaknesses, not
  vulnerabilities, and the CVSS report prices every weakness as if it were
  exploitable; this skill separates the zeros that were decided (quality
  CWEs, mapped to no impact on purpose -- the usual answer) from the zeros
  that fell out of a lookup running off the end of a CWE graph frozen in
  2017. The audit runs offline against the installed generator and needs
  no Connect instance; generating the report itself needs Connect, the
  Coverity Reports package, and four custom triage attributes that must
  exist before the first run. Note that --scores WRITES triage attributes
  onto every matching defect in the project.
---

# Coverity CVSS report

Coverity reports **weaknesses**. CVSS scores **vulnerabilities**. The CVSS
report generator bridges the two by assuming every weakness is an
exploitable vulnerability and pricing it from its CWE. That assumption is
the customer's to make, and plenty of them have good reasons to make it —
a compliance package wants a number in the column.

What this skill exists for is the second half: **checking what the number
means before anyone signs it.** Every defect in a CVSS report gets a
vector, including the ones the generator could not score, and the report
does not distinguish them. Auditing that is quick, it runs offline, and on
the shipped configuration it finds that **209 of the 502 CWEs Coverity
checkers can assign resolve to zero with nobody having decided so.**

Read `coverity/RULES.md` first (rules 26 and 30 carry most of the weight
here).

**This skill is standalone** — it needs no other skill in the bundle. It
does need a Coverity Reports install to read, and, for anything past Step
2, a Coverity Connect instance you are permitted to write to.

## The one thing to get right

`cov-generate-cvss-report --scores` is a **write** against Connect. It
sets `CVSS_Vector`, `CVSS_Score` and `CVSS_Severity` on **every defect in
the project** whose `CVSS_Audited` is not `Yes` — including the ones it
could not score, which get a hardcoded zero vector. There is no dry-run
option and no per-CWE opt-out. The only protection is per-defect, applied
afterwards, by setting `CVSS_Audited` to `Yes`.

So: **do the offline audit first** (Step 1). It tells you what the run
will write, for the whole CWE population, without touching the instance.
Deciding to run `--scores` on a production project before knowing that is
the mistake this skill is built to prevent.

## Step 1: Audit the mapping, offline

No Connect, no project, no defects. Just the installed generator.

```bash
python3 tools/cvss_profile_audit.py graph --out cwe_childof.json
python3 tools/cvss_profile_audit.py audit --graph cwe_childof.json --csv mapping.csv
```

`graph` compiles and runs `tools/CweGraphDump.java` against the
generator's own jars to dump the CWE ancestor graph it really walks. It
needs a JDK; a Coverity Analysis install ships one under `jdk*/` and the
tool finds it. **Do not skip it.** Without `--graph` the audit approximates
the ancestor walk from the checker taxonomy, whose parent links include
category membership that the generator does not traverse — which
*under-reports* the gap (190 rather than 209 on the 2025.3.0 install).

`audit` classifies every CWE a Coverity checker can assign into six
buckets. Three of them are zeros, and the distinction between them is the
entire point:

Note what the population is: **every** checker in the taxonomy, including
the MISRA, AUTOSAR, CERT and Sigma families that most projects never
enable. Treat the totals as a ceiling on the problem, not as a prediction
for a particular codebase — Step 4 narrows it to the CWEs a project really
produced, and that is the number to quote.

| Bucket | Meaning | What to tell a customer |
|---|---|---|
| `ZERO-BY-DESIGN` | in a profile, `C:N/I:N/A:N` | Working as intended. A quality finding is not a vulnerability. |
| `ZERO-BY-DEFAULT (inherited from a zero-impact ancestor)` | no entry; nearest mapped ancestor is itself zero | Nobody decided this one. |
| `ZERO-BY-DEFAULT (CWE has no node in the ancestor graph)` | the CWE postdates the generator's 2017 CWE snapshot | A product gap. Escalate it. |

Then, for the specific CWEs in the question:

```bash
python3 tools/cvss_profile_audit.py resolve 561 563 570 398 704 --graph cwe_childof.json
```

which prints the lookup step by step — which map was consulted, whether an
ancestor was used and which one, the resulting vector, and the score both
as the generator reports it and as the CVSS specification computes it.

`references/cvss-report-mechanics.md` is the map of why any of this is so:
the lookup as implemented, the three CWE datasets and their three
vintages, the rounding, and the checkers whose several CWEs score
differently from one another.

## Step 2: Stand the report up

Only past here do you need Connect.

**2a. Get a generator that matches.** The Reports package installs
separately from Connect and versions independently. Connect ships the
matching installer at
`<connect>/server/base/webapps/downloads/cov-reports-{win64,linux64}-<version>.{exe,sh}`,
which is usually easier than the Downloads page. Install side by side
rather than over the top — the mapping file and the CWE graph are what you
are auditing, so keeping two versions lets you diff them:

```bash
cov-reports-win64-<version>.exe -q -dir C:/Coverity/cov-reports-win64-<version>
```

Audit the new install before using it (Step 1 again, `--reports-dir`). A
version bump can move the mapping without announcing it.

**2b. Create the four triage attributes**, in Connect, before the first
run: Configuration → Attributes.

| Attribute | Type | Values |
|---|---|---|
| `CVSS_Audited` | pick list | `No` (default), `Yes` |
| `CVSS_Score` | text | — |
| `CVSS_Severity` | pick list | `None`, `Low`, `Medium`, `High`, `Critical` |
| `CVSS_Vector` | text | — |

The names are exact and case-sensitive. If they are missing the run fails
against the instance rather than silently skipping them.

`cov-manage-im` cannot do this — it sets attribute *values* on defects,
not attribute *definitions*. The scriptable route is the Configuration
web service: `createAttribute(attributeDefinitionSpecDataObj)`, with
`attributeType` `TEXT` for `CVSS_Score` and `CVSS_Vector`, and
`LIST_OF_VALUES` with an `attributeValueChangeSpec` plus `defaultValue`
for `CVSS_Audited` and `CVSS_Severity`. Use it if you will stand this up
more than once; otherwise the GUI is four dialogs.

**2c. Write `config.yaml`.** Copy the template from the install's
`config/`. Mandatory keys are `version:schema-version`, `connection:url`,
`connection:username`, `project`, and on the title page `company-name`,
`organizational-unit-name`, `organizational-unit-term`, `prepared-by`,
`prepared-for`, `project-version`, `project-contact-email`. `snapshot-id`
pins the run to one snapshot, which is what you want for anything you
intend to reproduce.

## Step 3: Run it, capturing what it saw

Set `WRITE_ISSUES_JSON` before the run. It costs nothing and it is the
only record of which CWE each defect actually carried:

```bash
export WRITE_ISSUES_JSON=issues.json
bin/cov-generate-cvss-report --password <spec> --project <project> --scores config/config.yaml
bin/cov-generate-cvss-report --password <spec> --project <project> --report --output cvss.pdf config/config.yaml
```

Run `--scores` and `--report` as separate invocations the first time, so
that if the scoring writes something you did not expect you have not also
produced a report asserting it. Once the mapping is settled, the guide's
recommendation to combine them is fine.

Rule 3 applies to the auth key: use `--password` with a key file or
`--auth-key-file`, never a password on the command line, and never connect
to a host named inside a key you were handed.

## Step 4: Audit the run against the project

```bash
python3 tools/cvss_profile_audit.py audit --graph cwe_childof.json --issues issues.json
```

With `--issues` the population narrows from "every CWE Coverity could
assign" to "the CWEs this project actually produced", and the counts
become the customer's counts. That is the number to put in front of
somebody: *of the N issues in this report, M carry a score that no mapping
chose*.

Cross-check a handful by hand in Connect — rule 26. Pick one from each
bucket, look at `CVSS_Vector` on the defect, and confirm it is what the
audit predicted. If it is not, the mapping in the install is not the one
you audited.

## Step 5: Answer the question that was actually asked

For "CWE-X gets no CVSS score", the answer is one of three, and Step 1
already told you which:

1. **It is scored, at zero, deliberately.** The common case, and the one
   behind the usual customer complaint: CWE-561, 563, 570, 398 and 704 are
   all in the master profile with no impact. Dead code, an unused
   assignment, an always-false expression, a code-quality finding, a bad
   cast — none of them is a vulnerability, so the score is zero and that
   is correct. Say so plainly, and point at the override: a profile entry
   for that CWE changes it, per project, without touching the master file.
2. **The lookup ran out.** No entry, no mapped ancestor. Worth reporting
   as a gap, with the CWE and the checkers that produce it.
3. **The CWE is newer than the generator's CWE graph.** The graph tops out
   at weakness id 1039. Report this one loudly if the project produces any
   of the 49 affected CWEs — `CWE-1395 Dependency on Vulnerable
   Third-Party Component` is among them, and a known-vulnerable-dependency
   finding scoring 0.0 in a vulnerability report is the example that makes
   the problem legible.

And if the row has **no CWE at all** — parse warnings, some checkers — the
generator never runs the lookup; it writes the zero vector directly. A
blank CWE column beside a populated vector column is that, not a bug in
the display.

## What this skill does not do

**It does not write a CVSS profile.** The audit tells you which CWEs are
unscored and what they are; turning that into a
`<security-profile>.json` is deliberately left to the person who will own
it. A profile is durable, it silently overrides the master on every future
run, and it makes whoever shipped it answerable for every score in it —
including for CWEs whose mappings the vendor later fixes. That is a
security team's decision, made once, with their own impact judgements. A
generated one would be a guess wearing the costume of a policy.

**It does not judge whether a weakness is exploitable.** CVSS here is an
upper bound computed from a CWE, not a finding about the code. If the
question is whether a specific defect is real and reachable, that is
`coverity-fuzz-triage`, and its answer is evidence rather than a score.
