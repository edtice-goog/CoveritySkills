# Contributing

This is a public repository. Skills here are developed against real
projects, including customer code that must not appear in it.

## Nothing from a customer run enters the repo

A commit, a comment in code, a calibration note, a fixture, or a pull
request description may not carry anything that came out of a customer's
idir: function, type, field, enumerator or file names, string literals,
paths, or sizes precise enough to identify the project.

Say what was learned in terms of the fixtures in `*/evals/fixtures/`, or in
neutral words ("a large real-world C++ TU", "a static member of a class with
a nested enum"). If a construct has no fixture yet, add one; that is what
the fixtures are for.

This applies to a model working in a zero-retention environment as much as
to a person: the environment protects the idir, not the pull request it
writes.

## Nothing from the machine it was developed on, either

The same goes for the environment a skill was built and measured in:
usernames, home directories, host names, install paths hard-coded into
scripts, scratch and workspace directories, the network a run sat behind,
and the names of other sessions or projects. They creep in through benchmark
scripts, quoted logs, JSON samples and worked examples. Scripts take such
paths as parameters or environment variables; prose uses neutral
placeholders (`/home/build/proj`, `capture-host`, `<install-root>`). Where a
measurement depends on a value's shape, such as a path's length in a
hexdump, keep the shape and change the value. And a skill is used by its
readers, not by the projects that tested it: nothing in it should need those
projects explained.

The Coverity version a measurement ran on is provenance, not environment:
keep it (`cov-analysis-win64-2026.6.0`, "2025.9.0 linux64"), as the
measured-versus-reasoned rule requires.

## Someone else's finding: credit it, then have them check it

When you carry another contributor's finding into shared text, such as a rule,
a skill or a calibration note, ask them to check your wording before it lands.
Only they know which part they measured and which part they reasoned. A
plausible mechanism written down beside a measurement borrows its confidence,
and nothing in the text shows the difference. Crediting the source keeps the
provenance; their check keeps the claim accurate. A finding can be credited
correctly and still be stated wrongly.

## Before pushing

- Grep the diff for any identifier you remember from the run, including the
  mangled forms (`_Z...`), and for your username, host name and home
  directory.
- Prefer the fixture names in every example.
- Measurements stay; names and literals go.

## What happened once

A pull request that fixed real C++ gaps in `slice_function.py` quoted the
symbols it had been debugged on in its code comments and description. The
history was rewritten and the description edited. The fixes were good; the
examples were not. `coverity-function-slice/evals/fixtures/nested_members.cpp` is
the fixture that should have carried them.
