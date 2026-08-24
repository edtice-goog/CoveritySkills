#!/usr/bin/env python3
"""Read a Coverity install's checker-enablement table and diff two installs.

Rule 4: enablement defaults are read from the installation, never remembered.
A finding that appears only under the newer analyzer because its checker moved
from default-off to default-on is a CONFIGURATION change, not a capability
improvement, and the two need different labels because they need different
decisions.
"""
import sys, json, html
from html.parser import HTMLParser

DOC = "doc/en/checker-enablement-and-option-defaults.html"


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell, self.in_cell, self.in_head = [], [], [], False, False

    def handle_starttag(self, tag, attrs):
        if tag == "thead":
            self.in_head = True
        elif tag in ("td", "th"):
            self.in_cell, self.cell = True, []
        elif tag == "tr":
            self.row = []

    def handle_endtag(self, tag):
        if tag == "thead":
            self.in_head = False
        elif tag in ("td", "th"):
            if self.in_cell:
                self.row.append(" ".join("".join(self.cell).split()))
            self.in_cell = False
        elif tag == "tr" and self.row and not self.in_head:
            self.rows.append(self.row)
            self.row = []

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)


def load(install):
    p = TableParser()
    with open(f"{install}/{DOC}", encoding="utf-8", errors="replace") as f:
        p.feed(f.read())
    out = {}
    for r in p.rows:
        if len(r) < 4:
            continue
        name, lang, _opts, enablement = r[0], r[1], r[2], r[3]
        if not name:
            continue
        out[(name, lang)] = enablement
    return out


def main():
    a, b = sys.argv[1], sys.argv[2]
    A, B = load(a), load(b)
    ka, kb = set(A), set(B)
    def on(e):  # what counts as reported at plain `cov-analyze` defaults
        return "default" in e.lower() and "not" not in e.lower()
    rep = {
        "old_install": a, "new_install": b,
        "old_rows": len(A), "new_rows": len(B),
        "added_checkers": sorted(f"{n} [{l}] -> {B[(n,l)]}" for n, l in kb - ka),
        "removed_checkers": sorted(f"{n} [{l}] ({A[(n,l)]})" for n, l in ka - kb),
        "enablement_changed": sorted(
            f"{n} [{l}]: {A[(n,l)]} -> {B[(n,l)]}" for n, l in ka & kb if A[(n, l)] != B[(n, l)]),
    }
    rep["newly_default_on"] = sorted(
        f"{n} [{l}]: {A[(n,l)]} -> {B[(n,l)]}" for n, l in ka & kb
        if not on(A[(n, l)]) and on(B[(n, l)]))
    rep["added_default_on"] = sorted(
        f"{n} [{l}]" for n, l in kb - ka if on(B[(n, l)]))
    print(json.dumps(rep, indent=2))


main()
