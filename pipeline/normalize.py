#!/usr/bin/env python3
"""Turn a raw Inkscape conversion into a page in this repo's format.

What comes out is the shape every other tool here already reads:

    <svg viewBox="0 0 345 550"><g transform="matrix(A 0 0 -A E F)">
      <g id="ayah_markers" class="ayah_markers">
        <g transform="translate(x y) scale(1 1)"><path d="…" …/></g>   the ۝ medallion
        <g transform="translate(x y)" ayah:x="…" ayah:y="…"><path …/></g>   its numeral
        …
      </g>
      <g id="content"><g transform="translate(x y)"><path …/></g>…</g>
    </g></svg>

Two details are load-bearing rather than cosmetic.  ``polygon_lib.markers`` finds a medallion
by matching ``translate(...) scale(...)`` and takes the first path inside, so the medallion
must carry a scale and its numeral must not -- that is how the 1441 pages distinguish them
too, and it is why a page yields eleven markers from twenty-two groups.  And ``ayah:x`` /
``ayah:y`` are written in page space: the audit only requires them to agree with the derived
centres up to a constant offset, and zero is the clearest constant to pick.

No ink is redrawn.  Each ``d`` is re-encoded by ``pathdata`` at the source's own three
decimals, which is exact -- over a page's 584,654 coordinates the round trip moves none of
them by more than 3e-12 points -- and buys about 16% on the file for free.  ``pathdata`` can
also thin an outline, and this artwork has room for it, but that is off unless you ask:
``--tolerance`` is 0.  ``verify_ink.py`` proves the result renders pixel for pixel onto the
raw conversion.

Usage:
    python3 pipeline/normalize.py --raw .work/hafs1422/raw --out mushafs/hafs/kfqc-1422
    python3 pipeline/normalize.py --pages 3,4,5 --tolerance 0
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import layout                                                    # noqa: E402
import markers as markerlib                                      # noqa: E402
import pathdata                                                  # noqa: E402
import rawsvg                                                    # noqa: E402

HEAD = ("<?xml version='1.0' encoding='UTF-8'?>\n"
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:ayah="https://quranpedia.net" '
        'version="1.1" viewBox="%s" xml:space="preserve">')
INK = "#231f20"


def _n(v, nd=6):
    s = "%.*f" % (nd, v)
    return s.rstrip("0").rstrip(".") if "." in s else s


def _path_element(raw_path, d, force_fill=None):
    """A path in the shipped convention: geometry first, then paint."""
    style = raw_path["style"]
    bits = ['<path d="%s"' % d]
    bits.append(' fill="%s"' % (force_fill or style.get("fill", INK)))
    if style.get("fill-rule") == "evenodd":
        bits.append(' fill-rule="evenodd"')
    if style.get("stroke", "none") != "none":
        bits.append(' stroke="%s"' % style["stroke"])
        if "stroke-width" in style:
            bits.append(' stroke-width="%s"' % style["stroke-width"])
    return "".join(bits) + "/>"


def body_paths(raw_text, page):
    """The Quran_TEXT paths that belong on the page.

    On the opening spread that is everything but the surah title, which is drawn well clear
    of the text block and falls outside the square window these two pages are cropped to.
    The 1441 edition drops it here too; it is the one thing removed from the artwork, and
    only on pages 1 and 2.
    """
    paths = rawsvg.paths(rawsvg.layers(raw_text)[rawsvg.TEXT])
    if page not in layout.SPREAD:
        return paths
    wide = []
    for p in paths:
        bb = pathdata_bbox(p["d"])
        if bb and bb[2] - bb[0] >= layout.TITLE_MAX_WIDTH:
            wide.append(p)
    if len(wide) != 1:
        raise ValueError("expected one text block on p%d, found %d" % (page, len(wide)))
    return wide


def pathdata_bbox(d):
    from polygon_lib import _glyph_bbox
    return _glyph_bbox(d)


def page_svg(raw_text, page, tolerance=0.0, decimals=3, raw_d=False):
    """The finished page, and the marker centres in page space."""
    sheet = rawsvg.viewbox(raw_text)[3]
    A, E, F = layout.matrix(page)
    box = layout.viewbox(page)
    to_page = lambda x, y: (A * x + E, -A * y + F)

    def reencode(d, tol, nd):
        return d if raw_d else pathdata.optimise(d, tol=tol, nd=nd)

    marks = markerlib.read(raw_text)
    out = ['<g id="ayah_markers" class="ayah_markers">']
    centres = []
    for m in marks:
        dx, dy = rawsvg.place(m["rosette"], sheet)
        out.append('<g transform="translate(%s %s) scale(1 1)">%s</g>'
                   % (_n(dx), _n(dy),
                      _path_element(m["rosette"],
                                    reencode(m["rosette"]["d"], 0, max(decimals, 3)))))
        cx, cy = to_page(m["x"], m["y"])
        centres.append((round(cx, 2), round(cy, 2)))
        for i, (p, nx, ny) in enumerate(m["numeral"]):
            ndx, ndy = rawsvg.place(p, sheet)
            meta = ' ayah:x="%s" ayah:y="%s"' % (_n(cx, 2), _n(cy, 2)) if i == 0 else ""
            out.append('<g transform="translate(%s %s)"%s>%s</g>'
                       % (_n(ndx), _n(ndy), meta,
                          _path_element(p, reencode(p["d"], 0, max(decimals, 3)))))
    out.append("</g>")

    out.append('<g id="content">')
    for p in body_paths(raw_text, page):
        if p["tx"] is None:
            raise ValueError("a body path is not placed by the expected flipped scale")
        dx, dy = rawsvg.place(p, sheet)
        out.append('<g transform="translate(%s %s)">%s</g>'
                   % (_n(dx), _n(dy),
                      _path_element(p, reencode(p["d"], tolerance, decimals), force_fill=INK)))
    out.append("</g>")

    body = "".join(out)
    svg = (HEAD % " ".join(_n(v) for v in box)
           + '<g transform="matrix(%s 0 0 -%s %s %s)">' % (_n(A, 4), _n(A, 4), _n(E), _n(F))
           + body + "</g></svg>")
    return svg, centres


def convert(raw_dir, out_dir, page, tolerance=0.0, decimals=3):
    with open(os.path.join(raw_dir, "%03d.svg" % page), encoding="utf-8") as fh:
        raw = fh.read()
    svg, centres = page_svg(raw, page, tolerance, decimals)
    svg_dir = os.path.join(out_dir, "svg")
    os.makedirs(svg_dir, exist_ok=True)
    with open(os.path.join(svg_dir, "%03d.svg" % page), "w", encoding="utf-8") as fh:
        fh.write(svg)
    return page, len(svg), len(centres)


def _job(args):
    try:
        return convert(*args[:3], tolerance=args[3], decimals=args[4])
    except Exception as exc:                                     # noqa: BLE001
        return args[2], -1, repr(exc)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=os.path.join(ROOT, ".work", "hafs1422", "raw"))
    ap.add_argument("--out", default=os.path.join(ROOT, "mushafs", "hafs", "kfqc-1422"))
    ap.add_argument("--pages", help="comma-separated pages or A-B ranges (default 3-604)")
    ap.add_argument("--tolerance", type=float, default=0.0,
                    help="optional path thinning, in points; 0 (the default) keeps the "
                         "artwork exactly as drawn")
    ap.add_argument("--decimals", type=int, default=3,
                    help="coordinate precision; the source carries 3, so 3 is lossless")
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4))
    args = ap.parse_args(argv)

    pages = []
    for part in (args.pages or "3-604").split(","):
        if "-" in part.strip("-"):
            a, b = part.split("-")
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))

    from multiprocessing import Pool
    jobs = [(args.raw, args.out, p, args.tolerance, args.decimals) for p in pages]
    total, failed = 0, []
    with Pool(args.workers) as pool:
        for page, size, info in pool.imap_unordered(_job, jobs, chunksize=2):
            if size < 0:
                failed.append((page, info))
            else:
                total += size
    print("%d pages, %.1f MB, mean %.0f kB" % (len(pages) - len(failed), total / 1e6,
                                               total / max(1, len(pages) - len(failed)) / 1e3))
    for page, why in sorted(failed):
        print("  FAILED p%-3d %s" % (page, why))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
