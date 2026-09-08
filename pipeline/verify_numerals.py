#!/usr/bin/env python3
"""Check every ayah identity against the number actually drawn inside its medallion.

The identities in a converted edition are transferred from an edition of the same riwaya --
which ayah ends where, page by page -- and the geometry is then measured from the new
artwork.  The transfer is safe only if the two editions really do end the same ayah on the
same page, and counting medallions cannot prove that: two editions with the same number of
medallions on a page could still disagree about which ayah each one closes.

The medallions say so themselves.  Each one has the ayah number drawn inside it, and this
reads that number back -- not by recognising digits, but by requiring the drawing to be
consistent with the assignment.  Every numeral is rasterised into a small normalised bitmap;
the bitmaps are averaged per assigned number to give one template each; and every numeral is
then required to be closer to its own number's template than to any other.  A page whose
identities had slipped by one would put a "51" against the template for 52 and be caught.

It is a consistency test, not an OCR, and that is the right shape for the question: a
systematic misassignment cannot survive it, because the glyph and the label would disagree
everywhere it happened.

    python3 pipeline/verify_numerals.py --edition hafs/kfqc-1422
    python3 pipeline/verify_numerals.py --edition hafs/kfqc-1441   # the same check on 1441
"""

import argparse
import collections
import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import editions                                                  # noqa: E402
import pathdata                                                  # noqa: E402
from polygon_lib import _glyph_bbox                              # noqa: E402

CELL = 24                 # the normalised bitmap is CELL x CELL
PAD = 0.06                # bbox padding, as a fraction, so strokes are not clipped
_GROUP = re.compile(r'<g transform="translate\(([-\d.]+) ([-\d.]+)\)( scale\([^)]*\))?"'
                    r'(?: ayah:x="([-\d.]+)" ayah:y="([-\d.]+)")?>(.*?)</g>', re.S)
_D = re.compile(r'<path d="([^"]*)"')


def _merge(parts):
    """One ``d`` for a numeral drawn as several paths, each with its own placement.

    Three pages set a two-digit number as two paths.  Joining the strings would be wrong --
    the second starts with a relative moveto, which would chain onto the end of the first --
    so each is parsed, shifted into the first one's frame, and the lot re-emitted together.
    """
    (ax, ay, first), rest = parts[0], parts[1:]
    subs = pathdata.parse(first)
    for bx, by, d in rest:
        for sub in pathdata.parse(d):
            subs.append([seg if seg[0] == "Z" else
                         (seg[0],) + tuple(v + (bx - ax if i % 2 == 0 else by - ay)
                                           for i, v in enumerate(seg[1:]))
                         for seg in sub])
    return pathdata.emit(subs, nd=3)


def numerals(edition, page):
    """[(surah, ayah, d)] — each ayah's numeral glyph, paired by the medallion's own centre."""
    with open(editions.page_path(edition, page), encoding="utf-8") as fh:
        text = fh.read()
    start = text.find('<g id="ayah_markers"')
    end = text.find('<g id="content"')
    if start < 0 or end < 0:
        return []
    # Walk the groups in order: a medallion carries a scale, the numeral that follows it
    # carries the ayah:x/ayah:y, and any further group before the next medallion is the rest
    # of that same numeral.
    stated, current = [], None
    for m in _GROUP.finditer(text[start:end]):
        x, y, scale, ax, ay = (float(m.group(1)), float(m.group(2)), m.group(3),
                               m.group(4), m.group(5))
        ds = _D.findall(m.group(6))
        if scale or not ds:
            current = None
            continue
        if ax is not None:
            current = [float(ax), float(ay), [(x, y, ds[0])]]
            stated.append(current)
        elif current is not None:
            current[2].append((x, y, ds[0]))
    stated = [(cx, cy, _merge(parts)) for cx, cy, parts in stated]
    with open(editions.page_path(edition, page, "json", "json"), encoding="utf-8") as fh:
        entries = [e for e in json.load(fh) if not e.get("continuation")]
    out = []
    for e in entries:
        near = [s for s in stated
                if abs(s[0] - e["x"]) < 0.5 and abs(s[1] - e["y"]) < 0.5]
        if len(near) != 1:
            raise ValueError("p%d %d:%d has %d numerals at its medallion"
                             % (page, e["surahNumber"], e["ayahNumber"], len(near)))
        out.append((e["surahNumber"], e["ayahNumber"], near[0][2]))
    return out


def bitmaps(glyphs):
    """One normalised CELL x CELL bitmap per glyph, rendered in a single pass."""
    if not glyphs:
        return np.zeros((0, CELL, CELL))
    cells = []
    for i, d in enumerate(glyphs):
        x0, y0, x1, y1 = _glyph_bbox(d)
        w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
        px, py = w * PAD, h * PAD
        cells.append('<svg x="%d" y="0" width="%d" height="%d" viewBox="%f %f %f %f" '
                     'preserveAspectRatio="xMidYMid meet"><path d="%s" fill="#000"/></svg>'
                     % (i * CELL, CELL, CELL, x0 - px, y0 - py, w + 2 * px, h + 2 * py, d))
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d">%s</svg>'
           % (CELL * len(glyphs), CELL, "".join(cells)))
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as fh:
        fh.write(svg)
        src = fh.name
    png = src + ".png"
    try:
        subprocess.run(["rsvg-convert", src, "-o", png], check=True, capture_output=True)
        # the glyphs are drawn on transparent ground, so the coverage is the alpha channel;
        # flattening to L would read every empty pixel as solid black
        a = np.array(Image.open(png).convert("RGBA"))[..., 3].astype(np.float32) / 255.0
    finally:
        for f in (src, png):
            if os.path.exists(f):
                os.unlink(f)
    return np.stack([a[:, i * CELL:(i + 1) * CELL] for i in range(len(glyphs))])


def _job(args):
    edition, page = args
    try:
        rows = numerals(edition, page)
        return page, rows, bitmaps([d for _, _, d in rows]), None
    except Exception as exc:                                     # noqa: BLE001
        return page, [], None, repr(exc)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--edition", default="hafs/kfqc-1422")
    ap.add_argument("--pages", default="1-604")
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4))
    ap.add_argument("--report", help="write every mismatch here as JSON")
    args = ap.parse_args(argv)

    pages = []
    for part in args.pages.split(","):
        if "-" in part.strip("-"):
            a, b = part.split("-")
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))

    from multiprocessing import Pool
    labels, images, where, errors = [], [], [], []
    with Pool(args.workers) as pool:
        for page, rows, bits, why in pool.imap_unordered(
                _job, [(args.edition, p) for p in pages], chunksize=4):
            if why:
                errors.append((page, why))
                continue
            for (surah, ayah, _), bmp in zip(rows, bits):
                labels.append(ayah)
                images.append(bmp)
                where.append((page, surah, ayah))
    if not images:
        print("nothing to check")
        return 1
    X = np.stack(images).reshape(len(images), -1)
    y = np.array(labels)

    order = sorted(set(labels))
    templates = np.stack([X[y == n].mean(0) for n in order])
    templates /= np.linalg.norm(templates, axis=1, keepdims=True) + 1e-9
    Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)

    best = np.zeros(len(X), dtype=int)
    margin = np.zeros(len(X))
    for i in range(0, len(X), 2000):
        sim = Xn[i:i + 2000] @ templates.T
        part = np.argsort(-sim, axis=1)
        best[i:i + 2000] = part[:, 0]
        margin[i:i + 2000] = np.take_along_axis(sim, part[:, :1], 1)[:, 0] - \
            np.take_along_axis(sim, part[:, 1:2], 1)[:, 0]
    index = {n: i for i, n in enumerate(order)}
    wrong = [(where[i], order[best[i]]) for i in range(len(X)) if best[i] != index[y[i]]]

    print("%s: %d medallions on %d pages, %d distinct ayah numbers"
          % (args.edition, len(X), len(pages) - len(errors), len(order)))
    print("  numerals whose drawing matches the ayah they are assigned: %d of %d (%.3f%%)"
          % (len(X) - len(wrong), len(X), 100.0 * (len(X) - len(wrong)) / len(X)))
    if wrong:
        print("  mismatches:")
        for (page, surah, ayah), got in wrong[:40]:
            print("    p%-3d assigned %d:%-3d but the numeral reads closest to %d"
                  % (page, surah, ayah, got))
        if len(wrong) > 40:
            print("    ... and %d more" % (len(wrong) - 40))
    for page, why in sorted(errors)[:10]:
        print("   ERROR p%-3d %s" % (page, why))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump([{"page": p, "surah": s, "ayah": a, "reads": int(g)}
                       for (p, s, a), g in wrong], fh, indent=1)
        print("\nreport written to %s" % args.report)
    return 1 if wrong or errors else 0


if __name__ == "__main__":
    sys.exit(main())
