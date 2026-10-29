# Collateral

Material that explains the skills rather than runs them: decks, worked
examples, write-ups. Each item has its own directory with a README naming
its files and how they are built.

The same rules apply as to the skills (`CONTRIBUTING.md`): nothing from a
customer, nothing from the machine a piece was written on, numbers only from
the skills' own calibration records on fixtures and public code. Collateral
explains how to use the skills; it does not record what anyone has done with
them. A built
artefact (a `.pptx`) is committed beside its source so that a reader need not
rebuild it; the build script says where the builder comes from.

| item | what |
|---|---|
| [`behind-the-path-limit/`](behind-the-path-limit/) | a ten-slide worked example of `coverity-pathout`, `coverity-function-slice` and `coverity-verify` as one findings-out, enrichments-in chain: find the functions on which the analyzer applied its path bound, look behind it with shape checkers, slice, verify, and a verdict that carries its evidence |
