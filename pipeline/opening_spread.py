#!/usr/bin/env python3
"""Finish pages 1 and 2, which the polygon generator does not handle.

Everywhere else in this repo the opening spread is a special case: it is not a fifteen-line
grid, and its ayah polygons are staircases cut around the ornamental frame rather than a
stack of full-width bands, so ``build_ayah_polygons.py`` starts at page 3 and the 1441
spread's polygons were finished by hand.

They do not have to be done by hand twice.  The two editions set these two pages the same
way -- once both are mapped into the 235x235 window their twelve ayah medallions agree to
within 2.5 units -- so the hand-cut geometry carries over, and the check that it did is the
one that matters: every medallion has to land inside its own polygon, with room to spare.

    python3 pipeline/opening_spread.py --edition hafs/kfqc-1422 --from hafs/kfqc-1441
    python3 pipeline/opening_spread.py --dry-run
"""

import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import brotli                                                    # noqa: E402

import pathdata                                                  # noqa: E402
import editions                                                  # noqa: E402
from polygon_lib import markers, read_page                       # noqa: E402

PAGES = (1, 2)
MAX_PAIRING_GAP = 6.0     # page units; the two editions agree to within 2.5
BROTLI_QUALITY = 11
_EXISTING = "ayahPolygon"


def _rings(d):
    """The polygon's closed rings as point lists.  These are staircases, so all straight."""
    rings = []
    for sub in pathdata.parse(d):
        pts = [(seg[-2], seg[-1]) for seg in sub if seg[0] in ("M", "L", "C")]
        if len(pts) >= 3:
            rings.append(pts)
    return rings


def _inside(d, x, y):
    """How far inside its polygon a point sits, in page units; negative when outside.

    The opening spread's polygons are staircases cut around the frame, not the stacks of
    rectangles the generator writes, so this is a general even-odd test with the distance
    measured to the nearest edge rather than to a bounding box."""
    rings = _rings(d)
    if not rings:
        return float("-inf")
    inside = False
    near = float("inf")
    for pts in rings:
        for i in range(len(pts)):
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % len(pts)]
            if (ay > y) != (by > y) and x < ax + (y - ay) / (by - ay) * (bx - ax):
                inside = not inside
            near = min(near, _seg_distance(x, y, ax, ay, bx, by))
    return near if inside else -near


def _seg_distance(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    den = vx * vx + vy * vy
    if den <= 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / den))
    return ((px - ax - t * vx) ** 2 + (py - ay - t * vy) ** 2) ** 0.5


def transfer(target, source, page):
    """(svg, json entries, worst margin) for one page of the spread."""
    stext, _, spolys = read_page(editions.page_path(source, page))
    if not spolys:
        raise ValueError("%s p%d has no polygons to copy" % (source, page))
    tpath = editions.page_path(target, page)
    with open(tpath, encoding="utf-8") as fh:
        text = fh.read()
    if _EXISTING in text:
        raise ValueError("p%d already carries polygons; re-convert the page first" % page)

    mk = markers(text)
    if len(mk) != len(spolys):
        raise ValueError("p%d has %d medallions against %d polygons in %s"
                         % (page, len(mk), len(spolys), source))

    # Pair on position, not on order: two ayat can end on one line a couple of units apart
    # in y, which is enough to sort them the wrong way round.  The reference edition states
    # where each of its own medallions is, and ours are within a few units of those, so the
    # nearest one is the right one -- and the pairing then owes nothing to the polygons it
    # is about to be checked against.
    with open(editions.page_path(source, page, "json", "json"), encoding="utf-8") as fh:
        ref = [e for e in json.load(fh) if not e.get("continuation")]
    if len(ref) != len(spolys):
        raise ValueError("p%d: %d json entries against %d polygons" % (page, len(ref), len(spolys)))
    free = list(mk)
    by_key = {}
    for p, e in zip(spolys, ref):
        best = min(free, key=lambda m: (m[0] - e["x"]) ** 2 + (m[1] - e["y"]) ** 2)
        free.remove(best)
        gap = ((best[0] - e["x"]) ** 2 + (best[1] - e["y"]) ** 2) ** 0.5
        if gap > MAX_PAIRING_GAP:
            raise ValueError("p%d %s: nearest medallion is %.1f units from the reference's"
                             % (page, p["key"], gap))
        by_key[p["key"]] = (best[0], best[1])

    added, entries, worst = [], [], float("inf")
    for p in spolys:
        element = stext[p["span"][0]:p["span"][1]]
        added.append(element)
        x, y = by_key[p["key"]]
        room = _inside(p["d"], x, y)
        worst = min(worst, room)
        entries.append(collections.OrderedDict(
            surahNumber=p["surah"], ayahNumber=p["ayah"],
            x=round(x, 2), y=round(y, 2), polygon=p["d"]))
    return text.replace("</svg>", "".join(added) + "</svg>"), entries, worst


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--edition", default="hafs/kfqc-1422")
    ap.add_argument("--from", dest="source", default="hafs/kfqc-1441")
    ap.add_argument("--min-margin", type=float, default=2.0,
                    help="how far inside its polygon a medallion must sit, in page units")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    results, bad = [], []
    for page in PAGES:
        svg, entries, worst = transfer(args.edition, args.source, page)
        results.append((page, svg, entries, worst))
        if worst < args.min_margin:
            bad.append((page, worst))
        print("p%d: %d polygons copied, worst medallion margin %.2f units" %
              (page, len(entries), worst))
    if bad:
        print("\nrefusing to write: a medallion sits too close to its polygon's edge")
        return 1
    if args.dry_run:
        print("\ndry run — nothing written")
        return 0
    for page, svg, entries, _ in results:
        with open(editions.page_path(args.edition, page), "w", encoding="utf-8") as fh:
            fh.write(svg)
        with open(editions.page_path(args.edition, page, "json", "json"), "w",
                  encoding="utf-8") as fh:
            json.dump(entries, fh, ensure_ascii=False, separators=(", ", ": "))
        with open(editions.page_path(args.edition, page, "svg-br", "svg.br"), "wb") as fh:
            fh.write(brotli.compress(svg.encode("utf-8"), quality=BROTLI_QUALITY))
    print("\nwritten")
    return 0


if __name__ == "__main__":
    sys.exit(main())
