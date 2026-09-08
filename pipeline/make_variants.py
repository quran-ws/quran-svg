#!/usr/bin/env python3
"""Cut the surah-specific views of the pages that carry more than one surah.

A variant is the page itself -- same glyphs, same polygons, same coordinate space -- shown
through a shorter ``viewBox``, so ``106-surah4.svg`` and ``106-surah5.svg`` are page 106 seen
twice.  Nothing is re-rendered and no geometry is recomputed; that is what lets
``build_ayah_polygons.py`` keep them in step with the page afterwards.

The cut goes in the white space above a surah's header band: the midpoint between the last
inked row of the surah above and the first inked row of the header.  The crops tile the page
exactly -- the first runs from the top of the page, the last to its foot, and each boundary
is one number used by both sides.  (The 1441 edition's own crops were cut a little
differently, each side measured on its own, so they overlap or leave a gap of up to three
units; that is left as it is rather than churned.)

    python3 pipeline/make_variants.py --edition hafs/kfqc-1422
    python3 pipeline/make_variants.py --edition hafs/kfqc-1441 --check   # compare, write nothing
"""

import argparse
import collections
import json
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import brotli                                                    # noqa: E402
import editions                                                  # noqa: E402
from polygon_lib import Z, decoration, ink_mask, line_grid, markers, read_page  # noqa: E402

BROTLI_QUALITY = 11
FIRST_PAGE, LAST_PAGE = 3, 604
_VIEWBOX = re.compile(r'viewBox="[^"]*"')


def _band_of(bands, y):
    for i, b in enumerate(bands):
        if b["top"] <= y < b["bot"]:
            return i
    return min(range(len(bands)),
               key=lambda i: abs((bands[i]["top"] + bands[i]["bot"]) / 2 - y))


def cuts(edition, page):
    """[(surah, y0, y1)] for a page that carries more than one surah, else []."""
    svg = editions.page_path(edition, page)
    text, box, polys = read_page(svg)
    # The last polygon may be a continuation: the next page's first ayah, given a region here
    # as well.  It is not one of this page's own ayah ends and has no medallion on this page.
    nxt = editions.page_path(edition, page + 1)
    if os.path.exists(nxt) and len(polys) > 1:
        first = read_page(nxt)[2]
        if first and polys[-1]["key"] == first[0]["key"] \
                and polys[-1]["key"] not in {q["key"] for q in polys[:-1]}:
            polys = polys[:-1]
    keys = [(p["surah"], p["ayah"]) for p in polys]
    surahs = list(dict.fromkeys(s for s, _ in keys))
    if len(surahs) < 2:
        return []
    mk = markers(text)
    if len(mk) != len(polys):
        raise ValueError("%d markers but %d polygons" % (len(mk), len(polys)))
    mask = ink_mask(svg)
    _, bands = line_grid(mask, [m[1] for m in mk], box)
    if not bands:
        raise ValueError("no line bands")
    ordered = sorted(mk, key=lambda m: (_band_of(bands, m[1]), -m[0]))
    marker_bands = [_band_of(bands, y) for _, y, _ in ordered]
    decor = sorted(decoration(bands, marker_bands, keys))

    rows = np.where(mask.sum(1) > 0)[0]
    edges = []
    for i, (surah, ayah) in enumerate(keys):
        if not (i and keys[i - 1][0] != surah):
            continue
        here = [j for j in decor if marker_bands[i - 1] < j <= marker_bands[i]]
        if not here:
            raise ValueError("surah %d opens on the page with no header band" % surah)
        band = bands[min(here)]
        edges.append((surah, _gap(mask, rows, band, box)))
    if len(edges) != len(surahs) - 1:
        raise ValueError("%d surah changes but %d cuts" % (len(surahs) - 1, len(edges)))

    tops = [box[1]] + [y for _, y in edges]
    bottoms = [y for _, y in edges] + [box[1] + box[3]]
    return [(s, round(t, 2), round(b, 2)) for s, t, b in zip(surahs, tops, bottoms)]


def _gap(mask, rows, band, box, z=Z):
    """The middle of the white space above a header band, in page units."""
    first = int((band["top"] - box[1]) * z)
    below = rows[rows >= first]
    above = rows[rows < first]
    if not len(below) or not len(above):
        return band["top"]
    return box[1] + (above.max() + below.min() + 1) / (2 * z)


def write(edition, page, plan, dry=False):
    svg = editions.page_path(edition, page)
    with open(svg, encoding="utf-8") as fh:
        text = fh.read()
    with open(editions.page_path(edition, page, "json", "json"), encoding="utf-8") as fh:
        entries = json.load(fh)
    written = []
    for surah, y0, y1 in plan:
        stem = "%03d-surah%d" % (page, surah)
        box = re.search(r'viewBox="([^"]*)"', text).group(1).split()
        crop = 'viewBox="%s %s %s %s"' % (box[0], _n(y0), box[2], _n(y1 - y0))
        vtext = _VIEWBOX.sub(crop, text, count=1)
        written.append(stem)
        if dry:
            continue
        with open(editions.page_path(edition, page, "svg", "svg", stem), "w",
                  encoding="utf-8") as fh:
            fh.write(vtext)
        with open(editions.page_path(edition, page, "json", "json", stem), "w",
                  encoding="utf-8") as fh:
            json.dump(entries, fh, ensure_ascii=False, indent=4)
        with open(editions.page_path(edition, page, "svg-br", "svg.br", stem), "wb") as fh:
            fh.write(brotli.compress(vtext.encode("utf-8"), quality=BROTLI_QUALITY))
    return written


def _n(v):
    s = "%.2f" % v
    return s.rstrip("0").rstrip(".") if "." in s else s


def _job(args):
    edition, page, dry = args
    try:
        plan = cuts(edition, page)
        return page, plan, write(edition, page, plan, dry) if plan else [], None
    except Exception as exc:                                     # noqa: BLE001
        return page, None, [], repr(exc)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--edition", default="hafs/kfqc-1422")
    ap.add_argument("--pages", default="3-604")
    ap.add_argument("--check", action="store_true",
                    help="report the crops, and how they compare with what is on disk")
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
    made, errors, plans = [], [], {}
    with Pool(args.workers) as pool:
        for page, plan, stems, why in pool.imap_unordered(
                _job, [(args.edition, p, args.check) for p in pages], chunksize=4):
            if why:
                errors.append((page, why))
                continue
            if plan:
                plans[page] = plan
                made += stems
    print("%s: %d pages carry more than one surah, %d crops%s"
          % (args.edition, len(plans), len(made), " (check only)" if args.check else ""))
    on_disk = {f[:-4] for f in os.listdir(os.path.join(editions.base(args.edition), "svg"))
               if re.fullmatch(r"\d+-surah\d+\.svg", f)}
    extra, absent = sorted(on_disk - set(made)), sorted(set(made) - on_disk)
    if extra:
        print("  on disk but not planned: %s" % ", ".join(extra[:20]))
    if absent and args.check:
        print("  planned but not on disk: %s" % ", ".join(absent[:20]))
    for page, why in sorted(errors):
        print("   ERROR p%-3d %s" % (page, why))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
