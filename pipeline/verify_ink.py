#!/usr/bin/env python3
"""Prove a converted page carries the artwork across unchanged.

Two things could go wrong in the conversion and each is checked on its own terms, because
they fail in different ways and only one of them can be settled by rasterising.

**Placement.**  Every path in the raw file is drawn under ``matrix(k,0,0,-k,tx,ty)``; in the
converted page it sits under ``translate(tx/k, (sheet-ty)/k)`` inside the page's root matrix.
Those two chains are compared as matrices, composed and differenced -- an algebraic check,
exact to the last bit, and immune to how a renderer happens to associate the products.

**The ``d`` itself.**  The page is rendered twice, once as written and once with every ``d``
replaced by the source's own string and nothing else touched.  Identical structure, identical
transforms, one variable: the re-encoding.  For a lossless run the two bitmaps are equal byte
for byte, and that is the sense in which the ink is unchanged.

Rasterising the raw file against the converted one instead would answer neither question
cleanly: the two express the same map as a different product of matrices, and librsvg rounds
the two products differently, which paints about 0.02% of the glyph edge pixels one grey
level apart no matter how exact the conversion is.

    python3 pipeline/verify_ink.py --pages 3-604
    python3 pipeline/verify_ink.py --pages 3 --scale 16
"""

import argparse
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import layout                                                    # noqa: E402
import normalize                                                 # noqa: E402
import rawsvg                                                    # noqa: E402

TOL = 1e-9


def _render(svg_text, width, height):
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as fh:
        fh.write(svg_text)
        src = fh.name
    png = src + ".png"
    try:
        subprocess.run(["rsvg-convert", "-w", str(width), "-h", str(height), src, "-o", png],
                       check=True, capture_output=True)
        return np.array(Image.open(png).convert("L")).astype(np.int16)
    finally:
        for f in (src, png):
            if os.path.exists(f):
                os.unlink(f)


def placement_error(raw_text, page):
    """The worst disagreement, in page units, between the two transform chains.

    A path's raw chain is ``matrix(k,0,0,-k,tx,ty)`` read in the sheet's px space; the
    converted chain is the page's root matrix over ``translate(dx,dy)``.  Both are reduced
    to the map they apply to the path's own ``d`` and compared coefficient by coefficient,
    scaled by the size of a page so a rotation-like term is not judged against a shift.
    """
    sheet = rawsvg.viewbox(raw_text)[3]
    A, E, F = layout.matrix(page)
    P = A / rawsvg.K                      # page units per px of the raw sheet
    L = rawsvg.layers(raw_text)
    worst = 0.0
    for key in (rawsvg.NUMBERS, rawsvg.TEXT):
        for p in rawsvg.paths(L.get(key, "")):
            if p["tx"] is None:
                raise ValueError("path is not placed by the expected flipped scale")
            # raw: px = (k*gx + tx, -k*gy + ty); page = (P*px_x + E, P*px_y + F - P*sheet)
            want = (P * rawsvg.K, -P * rawsvg.K,
                    P * p["tx"] + E, P * p["ty"] + F - P * sheet)
            # converted: g = translate(dx,dy) under matrix(A,0,0,-A,E,F)
            dx, dy = rawsvg.place(p, sheet)
            got = (A, -A, A * dx + E, -A * dy + F)
            worst = max(worst, max(abs(w - g) for w, g in zip(want, got)))
    return worst


def check(raw_dir, svg_dir, page, scale=4.0):
    with open(os.path.join(raw_dir, "%03d.svg" % page), encoding="utf-8") as fh:
        raw = fh.read()
    with open(os.path.join(svg_dir, "%03d.svg" % page), encoding="utf-8") as fh:
        made = fh.read()
    verbatim, _ = normalize.page_svg(raw, page, raw_d=True)
    box = layout.viewbox(page)
    w, h = int(box[2] * scale), int(box[3] * scale)
    diff = np.abs(_render(made, w, h) - _render(verbatim, w, h))
    return page, placement_error(raw, page), (int(diff.max()), int((diff > 0).sum()))


def _job(args):
    try:
        return check(*args)
    except Exception as exc:                                     # noqa: BLE001
        return args[2], float("inf"), repr(exc)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=os.path.join(ROOT, ".work", "hafs1422", "raw"))
    ap.add_argument("--svg", default=os.path.join(ROOT, "mushafs", "hafs", "kfqc-1422", "svg"))
    ap.add_argument("--pages", default="3-604")
    ap.add_argument("--scale", type=float, default=4.0)
    ap.add_argument("--max-delta", type=int, default=0,
                    help="worst single-pixel difference to accept. 0 for a fresh conversion; "
                         "add_line_structure.py later regroups the contours into lines and "
                         "librsvg antialiases a handful of the new joins differently, so use "
                         "about 32 once a page has been through it")
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4))
    args = ap.parse_args(argv)

    pages = []
    for part in args.pages.split(","):
        if "-" in part.strip("-"):
            a, b = part.split("-")
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))

    from multiprocessing import Pool
    worst, worst_px, clean, redrawn, errors = 0.0, 0, 0, [], []
    with Pool(args.workers) as pool:
        for page, err, delta in pool.imap_unordered(
                _job, [(args.raw, args.svg, p, args.scale) for p in pages], chunksize=2):
            if isinstance(delta, str):
                errors.append((page, delta))
                continue
            top, count = delta
            worst = max(worst, err)
            worst_px = max(worst_px, top)
            if top == 0:
                clean += 1
            if err > TOL:
                redrawn.append((page, "placement off by %.2e page units" % err))
            elif top > args.max_delta:
                redrawn.append((page, "%d pixels differ, worst by %d of 255" % (count, top)))
    print("%d pages checked at %g px per page unit" % (len(pages), args.scale))
    print("  placement: worst disagreement %.2e page units (tolerance %.0e)" % (worst, TOL))
    print("  ink:       %d of %d pages render identically to the source paths; "
          "worst single-pixel difference %d of 255"
          % (clean, len(pages) - len(errors), worst_px))
    for page, why in sorted(redrawn)[:40]:
        print("   p%-3d %s" % (page, why))
    for page, why in sorted(errors)[:20]:
        print("   ERROR p%-3d %s" % (page, why))
    return 1 if redrawn or errors else 0


if __name__ == "__main__":
    sys.exit(main())
