#!/usr/bin/env python3
"""Draw the ۝ rosette on ayah ends that print only the bare numeral.

A few Qālūn pages give an ayah end its number but no medallion around it, so the marker is
missing from ``<g id="ayah_markers">`` and every ayah on the page after it is left without a
reliable end.  This adds the ornament, using the same path, the same scale and the same
group shape as every other marker on that page, positioned so the medallion is concentric
with the numeral already printed there.

Where the centre comes from:

1. ``markers.json`` states every ayah end, in a frame offset from page space by a
   translation that varies page to page.  The offset is fitted by consensus and only
   accepted when it explains *every* rosette the page does draw.
2. That gives a position to within a unit or two, which is then refined onto the ink: the
   numeral is the run of ink around it bounded by whitespace on both sides, and the
   medallion is centred on that run.
3. The vertical placement copies what the page's other markers do relative to their line.

This changes page artwork, not just hit-regions, so it is a separate script from
``build_ayah_polygons.py`` and never runs as part of it.

Usage:
    python3 tools/draw_missing_rosettes.py --dry-run
    python3 tools/draw_missing_rosettes.py --mushaf qalon
"""

import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import brotli
import numpy as np

import editions
from polygon_lib import (INKCOL, Z, _D, _glyph_bbox, ink_mask, line_grid, markers,
                         read_page, recover_markers, translation_fit, viewbox)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRST_PAGE, LAST_PAGE = 3, 604
BROTLI_QUALITY = 11

_MATRIX = re.compile(r'<g transform="matrix\(([-\d.eE ]+)\)"')
_ROSETTE = re.compile(r'(<g transform="translate\(([-\d.eE]+) ([-\d.eE]+)\) '
                      r'scale\(([-\d.eE]+) ([-\d.eE]+)\)">\s*<path d="[^"]*"[^>]*/>\s*</g>)', re.S)


def page_matrix(text):
    return [float(v) for v in _MATRIX.search(text).group(1).split()]


def rosette_template(text):
    """(element, translate, scale, glyph_centre) of the first marker rosette on the page."""
    m = _ROSETTE.search(text, text.find('<g id="ayah_markers"'))
    if not m:
        return None
    element = m.group(1)
    tx, ty, sx, sy = (float(m.group(2)), float(m.group(3)), float(m.group(4)), float(m.group(5)))
    return element, (tx, ty), (sx, sy)


def glyph_centre(element):
    """The medallion path's own bbox centre, in glyph units."""
    d = _D.findall(element)[0]
    bb = _glyph_bbox(d)
    return (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2


def numeral_box(mask, bands, band, approx_x, box, reach=11.0, gap=1.6, z=Z):
    """The numeral's ink box: the cluster around ``approx_x``, allowing the small gaps
    between Arabic-Indic digits but stopping at the wider whitespace either side."""
    x0, y0 = box[0], box[1]
    b = bands[band]
    sl = mask[max(0, int((b["top"] - y0) * z)):int((b["bot"] - y0) * z)]
    col = sl.sum(0)
    lo_i = max(0, int((approx_x - reach - x0) * z))
    hi_i = min(len(col), int((approx_x + reach - x0) * z))
    inked = [i for i in range(lo_i, hi_i) if col[i] > INKCOL]
    if not inked:
        return None
    runs = []
    for i in inked:
        if runs and i - runs[-1][1] <= gap * z:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    target = (approx_x - x0) * z
    a, c = min(runs, key=lambda r: 0 if r[0] <= target <= r[1]
               else min(abs(r[0] - target), abs(r[1] - target)))
    rows = np.where(sl[:, a:c + 1].any(1))[0]
    return (a / z + x0, rows.min() / z + b["top"], c / z + x0, rows.max() / z + b["top"])


def missing_rosettes(mushaf, page, entries):
    """[(centre_x, centre_y)] for the ayah ends this page draws without a medallion."""
    svg = editions.page_path(mushaf, page, "svg", "svg")
    text, box, polys = read_page(svg)
    mk = markers(text)
    if len(mk) >= len(polys):
        return text, box, [], []
    filled, recovered = recover_markers(mk, entries)
    if not recovered:
        return text, box, [], []
    _, fit_dx, fit_dy = translation_fit(mk, entries)
    mask = ink_mask(svg)
    _, bands = line_grid(mask, [m[1] for m in filled], box)
    if not bands:
        return text, box, [], []

    def band_of(y):
        for i, b in enumerate(bands):
            if b["top"] <= y < b["bot"]:
                return i
        return min(range(len(bands)), key=lambda i: abs((bands[i]["top"] + bands[i]["bot"]) / 2 - y))

    out, meta = [], []
    for cx, cy, _ in recovered:
        band = band_of(cy)
        bb = numeral_box(mask, bands, band, cx, box)
        if bb is None:
            continue
        out.append((round((bb[0] + bb[2]) / 2, 3), round((bb[1] + bb[3]) / 2, 3),
                    round(bb[2] - bb[0], 2), round(bb[3] - bb[1], 2)))
        # the markers.json entry this recovered marker came from, in the mushaf's own frame
        near = min(entries, key=lambda e: abs(e["x"] - fit_dx - cx) + abs(e["y"] - fit_dy - cy))
        meta.append((near["x"], near["y"]))
    return text, box, out, meta


def marker_children(text):
    """(start, end) of each top-level child of the marker group, in document order."""
    k = text.find('<g id="ayah_markers"')
    if k < 0:
        return []
    k = text.find(">", k) + 1
    out, depth, start = [], 0, None
    for m in re.finditer(r"<g\b|</g>", text[k:]):
        if m.group(0) == "</g>":
            depth -= 1
            if depth == 0:
                out.append((k + start, k + m.end()))
            elif depth < 0:
                break
        else:
            if depth == 0:
                start = m.start()
            depth += 1
    return out


def draw(text, centres, meta_xy=None):
    """The svg with a rosette added at each centre, copied from the page's own marker.

    Each marker in the group is a pair: the rosette glyph, then a sibling carrying the
    numeral and the ``ayah:x``/``ayah:y`` attributes.  The pair is inserted in reading order
    so document order still matches the page, and the sibling is attribute-only — these four
    ayah ends already have their numeral drawn in the content layer, and a second copy would
    print the number twice.
    """
    template = rosette_template(text)
    if template is None:
        return text, []
    element, _, (sx, sy) = template
    gx, gy = glyph_centre(element)
    a, b, c, d, e, f = page_matrix(text)

    children = marker_children(text)
    rosettes = []                       # (index, centre_x, centre_y) of each existing rosette
    offsets = []                        # numeral translate minus rosette translate
    for i, (start, end) in enumerate(children):
        m = re.match(r'<g transform="translate\(([-\d.eE]+) ([-\d.eE]+)\) scale', text[start:end])
        if m:
            tx, ty = float(m.group(1)), float(m.group(2))
            rosettes.append((i, a * (tx + sx * gx) + e, d * (ty + sy * gy) + f, tx, ty))
        elif rosettes:
            n = re.match(r'<g transform="translate\(([-\d.eE]+) ([-\d.eE]+)\)"', text[start:end])
            if n:
                offsets.append((float(n.group(1)) - rosettes[-1][3],
                                float(n.group(2)) - rosettes[-1][4]))
    ox = float(np.median([o[0] for o in offsets])) if offsets else 0.0
    oy = float(np.median([o[1] for o in offsets])) if offsets else 0.0

    def reading_key(cx, cy):
        return (round(cy / 8.0), -cx)   # line first, then right to left

    inserts, added = [], []
    for n, (cx, cy, _, _) in enumerate(centres):
        tx = (cx - e) / a - sx * gx
        ty = (cy - f) / d - sy * gy
        rosette = re.sub(r'translate\([-\d.eE]+ [-\d.eE]+\)',
                         "translate(%.3f %.3f)" % (tx, ty), element, count=1)
        meta = ""
        if meta_xy and n < len(meta_xy) and meta_xy[n]:
            meta = ('<g transform="translate(%.3f %.3f)" ayah:x="%.2f" ayah:y="%.2f"></g>'
                    % (tx + ox, ty + oy, meta_xy[n][0], meta_xy[n][1]))
        after = [r for r in rosettes if reading_key(r[1], r[2]) < reading_key(cx, cy)]
        at = children[after[-1][0]][1] if after else children[0][0]
        # a rosette is followed by its sibling; step past it too
        idx = (after[-1][0] + 1) if after else -1
        if 0 <= idx < len(children) and not re.match(
                r'<g transform="translate\([-\d.eE]+ [-\d.eE]+\) scale', text[children[idx][0]:children[idx][1]]):
            at = children[idx][1]
        inserts.append((at, rosette + meta))
        added.append((cx, cy))

    for at, blob in sorted(inserts, reverse=True):
        text = text[:at] + blob + text[at:]
    return text, added


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mushaf", help="comma-separated subset (default: all five)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    total = 0
    for mushaf in (args.mushaf.split(",") if args.mushaf else list(MUSHAFS)):
        path = editions.index_path(mushaf, "markers.json")
        by_page = collections.defaultdict(list)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for entry in json.load(fh):
                    by_page[entry["page"]].append(entry)
        for page in range(FIRST_PAGE, LAST_PAGE + 1):
            svg = editions.page_path(mushaf, page, "svg", "svg")
            if not os.path.exists(svg):
                continue
            text, box, centres, meta = missing_rosettes(mushaf, page, by_page.get(page, []))
            if not centres:
                continue
            new_text, added = draw(text, centres, meta)
            for (cx, cy, w, h) in centres:
                print("%s p%-3d rosette at (%.2f, %.2f), around a numeral %.1f x %.1f"
                      % (mushaf, page, cx, cy, w, h))
            total += len(added)
            if args.dry_run or not added:
                continue
            with open(svg, "w", encoding="utf-8") as fh:
                fh.write(new_text)
            br = editions.page_path(mushaf, page, "svg-br", "svg.br")
            with open(br, "wb") as fh:
                fh.write(brotli.compress(new_text.encode("utf-8"), quality=BROTLI_QUALITY))
            for variant in sorted(os.listdir(os.path.dirname(svg))):
                if not re.fullmatch(r"%03d-surah\d+\.svg" % page, variant):
                    continue
                vpath = os.path.join(os.path.dirname(svg), variant)
                with open(vpath, encoding="utf-8") as fh:
                    vtext = fh.read()
                vnew, _ = draw(vtext, centres, meta)
                with open(vpath, "w", encoding="utf-8") as fh:
                    fh.write(vnew)
                vbr = editions.page_path(mushaf, page, "svg-br", "svg.br",
                                         stem=variant[:-4])
                with open(vbr, "wb") as fh:
                    fh.write(brotli.compress(vnew.encode("utf-8"), quality=BROTLI_QUALITY))
    print("\n%d rosette(s)%s" % (total, " would be drawn" if args.dry_run else " drawn"))
    print("re-run tools/build_ayah_polygons.py for those pages so the polygons pick them up")
    return 0


if __name__ == "__main__":
    sys.exit(main())
