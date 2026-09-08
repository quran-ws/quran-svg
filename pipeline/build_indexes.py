#!/usr/bin/env python3
"""Write an edition's two index files from the pages themselves.

``json/markers.json``  every ayah end in the muṣḥaf, in reading order, as
                       ``{page, ayah, x, y}`` where ``ayah`` is the running 1..N index the
                       page's ``verse-N`` ids and polygons use.
``json/surah.json``    the 114-surah index.  Everything in it except ``headerPosition`` is a
                       fact about the muṣḥaf rather than about the artwork -- ayah counts,
                       which page a surah opens on, its juz, its names -- and is copied from
                       a reference edition of the same riwaya, which is what makes the two
                       Hafs editions agree by construction instead of by luck.

``headerPosition`` is a fact about the artwork and is measured here: the centre of the ink in
the surah's header band, in page space.  Measuring the 1441 pages this way reproduces the
values that edition already ships to within 0.4 units, which is what says the definition is
the right one.

    python3 pipeline/build_indexes.py --edition hafs/kfqc-1422 --from hafs/kfqc-1441
    python3 pipeline/build_indexes.py --edition hafs/kfqc-1441 --check   # remeasure, write nothing
"""

import argparse
import collections
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import editions                                                  # noqa: E402
from polygon_lib import (Z, decoration, ink_mask, line_grid, markers, read_page,  # noqa: E402
                         viewbox)

FIRST_PAGE, LAST_PAGE = 1, 604
OPENING_SPREAD = (1, 2)   # surah 1 and 2 open here, with their headers removed


def page_entries(edition, page):
    """The page's own ayat, in reading order, from its built json."""
    path = editions.page_path(edition, page, "json", "json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return [e for e in json.load(fh) if not e.get("continuation")]


def markers_index(edition, pages):
    """[{page, ayah, x, y}] with ``ayah`` the running index, and the pages that were missing."""
    out, missing, running = [], [], 0
    for page in pages:
        entries = page_entries(edition, page)
        if entries is None:
            missing.append(page)
            continue
        for e in entries:
            running += 1
            out.append(collections.OrderedDict(page=page, ayah=running,
                                               x=e["x"], y=e["y"]))
    return out, missing


def header_positions(edition, pages):
    """{surah: y} — where each surah's header band sits, in page space."""
    found = {}
    for page in pages:
        if page in OPENING_SPREAD:
            continue          # the header ornament is not drawn on these pages
        svg = editions.page_path(edition, page)
        if not os.path.exists(svg):
            continue
        text, box, polys = read_page(svg)
        if not polys:
            continue
        keys = [(p["surah"], p["ayah"]) for p in polys]
        starts = [i for i, (s, a) in enumerate(keys)
                  if a == 1 and (i == 0 or keys[i - 1][0] != s)]
        if not starts:
            continue
        mk = markers(text)
        if len(mk) != len(polys):
            continue
        mask = ink_mask(svg)
        _, bands = line_grid(mask, [m[1] for m in mk], box)
        if not bands:
            continue
        marker_bands = [_band_of(bands, y) for _, y, _ in
                        sorted(mk, key=lambda m: (_band_of(bands, m[1]), -m[0]))]
        decor = sorted(decoration(bands, marker_bands, keys))
        for i in starts:
            # only the decoration between the previous ayah's line and this surah's first
            # one: three surahs can open on one page, and each has its own header
            floor = marker_bands[i - 1] if i else -1
            before = [j for j in decor if floor < j <= marker_bands[i]]
            if not before:
                continue
            band = bands[min(before)]                # the header, above its basmalah
            found[keys[i][0]] = round(_ink_centre(mask, band, box), 2)
    return found


def _band_of(bands, y):
    for i, b in enumerate(bands):
        if b["top"] <= y < b["bot"]:
            return i
    return min(range(len(bands)),
               key=lambda i: abs((bands[i]["top"] + bands[i]["bot"]) / 2 - y))


def _ink_centre(mask, band, box, z=Z):
    r0 = max(0, int((band["top"] - box[1]) * z))
    r1 = min(mask.shape[0], int((band["bot"] - box[1]) * z))
    rows = np.where(mask[r0:r1].sum(1) > 0)[0]
    if not len(rows):
        return (band["top"] + band["bot"]) / 2
    return band["top"] + (rows.min() + rows.max() + 1) / (2 * z)


def surah_index(edition, source, pages):
    """The reference edition's surah records, with this edition's own header positions."""
    with open(editions.index_path(source, "surah.json"), encoding="utf-8") as fh:
        surahs = json.load(fh)
    moved = header_positions(edition, pages)
    out, kept = [], []
    for s in surahs:
        s = dict(s)
        if s["number"] in moved:
            s["headerPosition"] = moved[s["number"]]
        else:
            kept.append(s["number"])
        out.append(collections.OrderedDict(sorted(s.items())))
    return out, kept


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--edition", default="hafs/kfqc-1422")
    ap.add_argument("--from", dest="source", default="hafs/kfqc-1441")
    ap.add_argument("--check", action="store_true", help="measure and report, write nothing")
    args = ap.parse_args(argv)

    pages = list(range(FIRST_PAGE, LAST_PAGE + 1))
    index, missing = markers_index(args.edition, pages)
    surahs, kept = surah_index(args.edition, args.source, pages)

    print("%s" % args.edition)
    print("  markers.json  %d ayah ends%s"
          % (len(index), "" if not missing
             else "  (MISSING pages %s)" % _runs(missing)))
    print("  surah.json    114 surahs, %d header positions measured, %d copied from %s"
          % (114 - len(kept), len(kept), args.source))
    if kept:
        print("                not measured: %s" % ", ".join(str(n) for n in kept[:20]))
    if args.check:
        print("\ncheck only — nothing written")
        return 0
    if missing:
        print("\nrefusing to write markers.json while pages are missing")
        return 1
    with open(editions.index_path(args.edition, "markers.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=4)
        fh.write("\n")
    with open(editions.index_path(args.edition, "surah.json"), "w", encoding="utf-8") as fh:
        json.dump(surahs, fh, ensure_ascii=False, indent=4, sort_keys=True)
        fh.write("\n")
    print("\nwritten")
    return 0


def _runs(pages):
    out, start, prev = [], None, None
    for p in sorted(pages) + [None]:
        if start is None:
            start = prev = p
            continue
        if p == prev + 1 if p else False:
            prev = p
            continue
        out.append(str(start) if start == prev else "%d-%d" % (start, prev))
        start = prev = p
    return ", ".join(out)


if __name__ == "__main__":
    sys.exit(main())
