#!/usr/bin/env python3
"""Where a 1422 page sits inside the 345x550 window every KFQC page in this repo uses.

The two Hafs editions are the same muṣḥaf -- 604 pages, fifteen lines, identical page and
line breaks -- but they were drawn on different sheets.  1441 was set on a 382.677 x 547.086
pt page; 1422 was set on A4.  Neither number reaches the shipped file: a page is cropped to
a 345 x 550 window around its text, so the two editions can be made to share one coordinate
space and a reader that swaps editions sees the text stay put.

The map is a uniform scale and a translation, and it is fitted, not assumed:

    page_x =  A * u_x + E(parity)
    page_y = -A * u_y + F

with ``u`` the page's own point space, y up from the foot of the sheet.  ``A`` comes from the
justified line width, which is a design constant and the one measurement neither edition's
glyphs can perturb; ``E`` and ``F` centre 1422's ink on 1441's, per page parity, because the
inner and outer margins differ between recto and verso.

Re-derive with:

    python3 pipeline/layout.py --fit          # body pages
    python3 pipeline/layout.py --fit --spread # the opening spread

which prints the constants below together with the residuals behind them.
"""

import argparse
import os
import re
import statistics
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import rawsvg                                                    # noqa: E402

# ---------------------------------------------------------------------------
# fitted constants
# ---------------------------------------------------------------------------
# Body pages, from 86 pages sampled every seventh page over 3-604.  The 1422 justified
# measure is 520.5 px odd / 520.0 px even against 326.25 / 326.50 in 1441, so a single
# scale serves both parities to within 0.03 page units across a full line.
BODY_VIEWBOX = (0.0, 0.0, 345.0, 550.0)
BODY_A = 0.8366
BODY_E = {1: -54.34, 0: -103.76}      # keyed by page parity, as 1441's -55 / -115 are
BODY_F = 622.81

# The opening spread keeps 1441's square window.  Both editions drop the surah title from
# these two pages and crop to the text, and the fit is against that same body -- from the
# twelve ayah medallions of the two pages, which land within 2.5 units of 1441's.  There are
# only two such pages and they are set differently from each other, so each has its own map.
SPREAD_VIEWBOX = (0.0, 0.0, 235.0, 235.0)
SPREAD = {1: (0.8280, -126.78, 422.43),
          2: (0.8231, -125.49, 420.73)}
TITLE_MAX_WIDTH = 150.0     # points; the surah title is far narrower than the text block

PARITY = lambda page: page % 2


def matrix(page):
    """The root ``matrix(...)`` a page is wrapped in."""
    if page in SPREAD:
        return SPREAD[page]
    return BODY_A, BODY_E[PARITY(page)], BODY_F


def viewbox(page):
    return SPREAD_VIEWBOX if page in SPREAD else BODY_VIEWBOX


# ---------------------------------------------------------------------------
# fitting
# ---------------------------------------------------------------------------

def _render_bbox(svg_text, z):
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as fh:
        fh.write(svg_text)
        src = fh.name
    png = src + ".png"
    try:
        subprocess.run(["rsvg-convert", "-z", str(z), src, "-o", png], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        a = np.array(Image.open(png).convert("RGBA"))[..., 3] > 40
    finally:
        for f in (src, png):
            if os.path.exists(f):
                os.unlink(f)
    rows, cols = np.where(a.any(1))[0], np.where(a.any(0))[0]
    if not len(rows):
        return None
    return (cols.min() / z, rows.min() / z, (cols.max() + 1) / z, (rows.max() + 1) / z)


def raw_bbox(raw_path, layers=(rawsvg.NUMBERS, rawsvg.TEXT), z=2.0):
    text = open(raw_path, encoding="utf-8").read()
    box = rawsvg.viewbox(text)
    L = rawsvg.layers(text)
    body = "".join(L[k] for k in layers if k in L)
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%s">%s</svg>'
           % (" ".join(str(v) for v in box), body))
    return _render_bbox(svg, z)


def shipped_bbox(svg_path, z=4.0):
    return _render_bbox(open(svg_path, encoding="utf-8").read(), z)


def fit(raw_dir, ref_dir, pages, workers=8):
    """(A, E per parity, F, residuals) mapping the raw px space onto the reference pages."""
    from multiprocessing import Pool
    with Pool(workers) as pool:
        got = pool.map(_measure, [(raw_dir, ref_dir, p) for p in pages])
    got = [g for g in got if g and g[1] and g[2]]
    scale = statistics.median([(b[2] - b[0]) / (a[2] - a[0]) for _, a, b in got])
    A = round(scale * rawsvg.K, 4)
    px = A / rawsvg.K                       # page units per raw px, after rounding A
    E, res = {}, []
    for parity in (1, 0):
        R = [(a, b) for p, a, b in got if p % 2 == parity]
        if not R:
            continue
        E[parity] = round(statistics.median([(b[0] + b[2]) / 2 - px * (a[0] + a[2]) / 2
                                             for a, b in R]), 2)
        res += [abs(px * (a[0] + a[2]) / 2 + E[parity] - (b[0] + b[2]) / 2) for a, b in R]
    with open(os.path.join(raw_dir, "%03d.svg" % pages[0]), encoding="utf-8") as fh:
        sheet = rawsvg.viewbox(fh.read(4000))[3]
    F = round(statistics.median([(b[1] + b[3]) / 2 - px * ((a[1] + a[3]) / 2 - sheet)
                                 for _, a, b in got]), 2)
    vres = [abs(px * ((a[1] + a[3]) / 2 - sheet) + F - (b[1] + b[3]) / 2) for _, a, b in got]
    return A, E, F, dict(pages=len(got), x_residual=max(res), y_residual=max(vres),
                         width_ratio_spread=(
                             min((b[2] - b[0]) / (a[2] - a[0]) for _, a, b in got),
                             max((b[2] - b[0]) / (a[2] - a[0]) for _, a, b in got)))


def _measure(job):
    raw_dir, ref_dir, page = job
    try:
        return page, raw_bbox(os.path.join(raw_dir, "%03d.svg" % page)), \
            shipped_bbox(os.path.join(ref_dir, "%03d.svg" % page))
    except Exception:                                            # noqa: BLE001
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=os.path.join(ROOT, ".work", "hafs1422", "raw"))
    ap.add_argument("--reference", default=os.path.join(ROOT, "mushafs", "hafs", "kfqc-1441", "svg"))
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--spread", action="store_true", help="fit pages 1-2 instead of the body")
    ap.add_argument("--step", type=int, default=7)
    args = ap.parse_args(argv)
    if not args.fit:
        ap.error("nothing to do; pass --fit")
    pages = [1, 2] if args.spread else list(range(3, 605, args.step))
    A, E, F, stats = fit(args.raw, args.reference, pages)
    print("A = %.4f" % A)
    print("E = %s" % {k: v for k, v in sorted(E.items(), reverse=True)})
    print("F = %.2f" % F)
    print("pages %(pages)d  worst x residual %(x_residual).2f  worst y residual "
          "%(y_residual).2f  width ratio %(width_ratio_spread)s" % stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
