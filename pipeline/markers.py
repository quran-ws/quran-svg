#!/usr/bin/env python3
"""The ۝ medallions of a raw 1422 page, in the page's own point space.

``Aya_Number`` holds two paths per ayah end -- the medallion, which carries a stroke, and
the numeral inside it, which does not.  Each numeral is attached to the medallion it sits
in, so the pair can be written out together the way the shipped pages do it.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

import rawsvg                                                    # noqa: E402
from polygon_lib import _glyph_bbox                              # noqa: E402


def _centre(path, sheet):
    bb = _glyph_bbox(path["d"])
    dx, dy = rawsvg.place(path, sheet)
    return (dx + (bb[0] + bb[2]) / 2, dy + (bb[1] + bb[3]) / 2,
            (bb[2] - bb[0]) / 2, (bb[3] - bb[1]) / 2)


def read(raw_text):
    """``[{rosette, numeral, x, y, r}]`` in reading order: top line first, right to left.

    ``x``/``y`` are the medallion centre in point space with y up, ``r`` its half width.
    A numeral drawn as more than one path -- three pages do that -- is kept as a list, so
    nothing is silently dropped.
    """
    sheet = rawsvg.viewbox(raw_text)[3]
    paths = rawsvg.paths(rawsvg.layers(raw_text)[rawsvg.NUMBERS])
    if any(p["tx"] is None for p in paths):
        raise ValueError("a marker path is not placed by the expected flipped scale")
    rosettes, numerals = [], []
    for p in paths:
        (rosettes if rawsvg.is_rosette(p) else numerals).append((p, _centre(p, sheet)))
    out = []
    for p, (x, y, rx, ry) in rosettes:
        out.append(dict(rosette=p, numeral=[], x=x, y=y, r=rx))
    for p, (x, y, _, _) in numerals:                  # each numeral joins its own medallion
        near = min(out, key=lambda m: (m["x"] - x) ** 2 + (m["y"] - y) ** 2)
        near["numeral"].append((p, x, y))
    return order(out)


def order(marks, gap=None):
    """Reading order: rows top to bottom, right to left inside a row."""
    if not marks:
        return marks
    gap = gap or 2.5 * max(m["r"] for m in marks)
    rows, row = [], []
    for m in sorted(marks, key=lambda m: -m["y"]):
        if row and row[-1]["y"] - m["y"] > gap:
            rows.append(row)
            row = []
        row.append(m)
    rows.append(row)
    return [m for r in rows for m in sorted(r, key=lambda m: -m["x"])]
