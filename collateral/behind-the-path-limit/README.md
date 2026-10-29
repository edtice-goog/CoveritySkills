# Behind the Path Limit

A standalone deck, in the visual style of the public *SSDLC in the Mythos
Era* series (https://github.com/edtice-goog/ssdlc-mythos) but not part of
it: a worked example of an earlier-stage tool (Coverity) enriching its
output with the functions on which it applied its path bound, and a
later-stage tool (a fuzzer built on the analyzer's own intermediate
directory and derived models) targeting exactly those. It is an
implementation of the findings-out, enrichments-in architecture the series
describes, not a new step in the lifecycle.

| file | |
|---|---|
| `behind-the-path-limit.md` | the companion document; the slides are the sections that carry a `<!-- slide: -->` directive |
| `behind-the-path-limit.pptx` | the deck, ten slides, as built from the markdown at the commit that last changed it |
| `build.py` | rebuilds the deck with the series builder (`build-decks.py`, its template and its icons, from a checkout of the series repository beside this one or at `$SSDLC_MYTHOS`), then relabels the footer so the file does not claim membership of the series |

The skills the deck describes are in this repository: `coverity-pathout`,
`coverity-function-slice`, `coverity-verify`; the shape catalogue is
`coverity-pathout/shapes/`. Every number on the slides is from those
skills' calibration records.

The deck shows verification by extraction: the slice set, with callees
outside it stubbed from their derived models. `coverity-verify` now has a
second route, harness-verification, which compiles the whole translation
unit as the build did and is its default; extraction remains the route for
code the harness route cannot take.
