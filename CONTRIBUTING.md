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

## Before pushing

- Grep the diff for any identifier you remember from the run, including the
  mangled forms (`_Z...`).
- Prefer the fixture names in every example.
- Measurements stay; names and literals go.

## What happened once

A pull request that fixed real C++ gaps in `slice_function.py` quoted the
symbols it had been debugged on in its code comments and description. The
history was rewritten and the description edited. The fixes were good; the
examples were not. `coverity-pathout/evals/fixtures/nested_members.cpp` is
the fixture that should have carried them.
