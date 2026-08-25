#!/usr/bin/env python3
"""Check that every contour is on the line its ink belongs to.

`verify_render.py` proves the regrouping changed no pixel, and it does that by rendering the
page **as it sits**. That is the right check for `evenodd` cancellation and the wrong one for
line *assignment*, because a contour placed in the wrong `<g>` renders identically until
something moves the lines. The error is invisible in the file and appears only downstream, in
a consumer that spreads lines to fill a screen, highlights line by line, or reflows the page.

This is the check for that. It needs no renderer and no reference image, because the property
is local: a contour whose own ink sits in band M has no business in line group N unless it is
genuinely touching something in group N.

## Why a contour ends up in the wrong group

`clusters()` unions contours whose **bounding boxes** overlap, which is the correct and
cheap test for whether splitting them apart could break an `evenodd` cancellation. It is not
a test of whether they touch. A bounding box is not ink, and Arabic script is full of long
tails that sweep down from one line and pass over the whitespace of the next: their box
encloses marks they never come near.

Bound to such a tail, a mark is outvoted by the tail's width and assigned to the tail's line.
The page still renders correctly — nothing has moved — so `verify_render.py` passes. Spread
the lines and the mark travels a full line away from the letter it belongs to. Measured
downstream in `quranpedia.ios`, which ported this same rule: rendering `hafs/300` with lines
spread turned `أَوْ` into `اوْ`, and `hafs/048` turned `أَن` into `ان`. Different words.

Whether this corpus contains such an assignment is exactly what this reports.

## What it measures

For every contour, the band its own ink centre falls in. Where that differs from the group it
was assigned to, the contour must be within `--eps` of some contour in its group **by true
distance between the outlines**, not between their boxes. Distances are computed on flattened
curves; boxes are used only to skip pairs that cannot possibly be close.

    tools/verify_line_assignment.py hafs/kfqc
    tools/verify_line_assignment.py hafs/kfqc --pages 300,48
    tools/verify_line_assignment.py                        # every edition

Exits non-zero if any contour is assigned to a line it neither belongs to nor touches.
"""

import argparse
import json
import math
import os
import re
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from page import Page                                                     # noqa: E402
from svg_lines import apply, tokenize                                     # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mushafs")

# How close two outlines must come to count as touching. The same 0.5 page units
# `add_line_structure.py` clusters with, so this asks whether the binding that rule performed
# was justified on the ink rather than on the boxes.
DEFAULT_EPS = 0.5

# Points sampled along each curve segment when flattening. Eight is far finer than the
# distances being tested — a glyph contour at these scales is a few units across — and the
# cost only lands on the handful of contours that need checking at all.
CURVE_SAMPLES = 8

LINE_ATTR_RE = re.compile(r'data-line="(\d+)"')


def flatten(d, matrix):
    """Every contour in `d` as a list of points in page coordinates.

    Curves are sampled rather than solved: this measures distance, not extent, so points on
    the curve are what is wanted. `subpaths` already solves the extrema for the boxes.
    """
    out = []
    cur = []
    cx = cy = sx = sy = 0.0

    def emit(x, y):
        cur.append(apply(matrix, x, y))

    def bezier(p0, p1, p2, p3):
        for i in range(1, CURVE_SAMPLES + 1):
            t = i / CURVE_SAMPLES
            u = 1 - t
            emit(u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                 u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1])

    for cmd, args, _, _ in tokenize(d):
        rel = cmd.islower()
        up = cmd.upper()
        if up == "M":
            if cur:
                out.append(cur)
            cur = []
            cx, cy = (cx + args[0], cy + args[1]) if rel else (args[0], args[1])
            sx, sy = cx, cy
            emit(cx, cy)
        elif up == "Z":
            if cur:
                out.append(cur)
            cur = []
            cx, cy = sx, sy
        elif up == "L":
            cx, cy = (cx + args[0], cy + args[1]) if rel else (args[0], args[1])
            emit(cx, cy)
        elif up == "H":
            cx = cx + args[0] if rel else args[0]
            emit(cx, cy)
        elif up == "V":
            cy = cy + args[0] if rel else args[0]
            emit(cx, cy)
        elif up == "C":
            p1 = (cx + args[0], cy + args[1]) if rel else (args[0], args[1])
            p2 = (cx + args[2], cy + args[3]) if rel else (args[2], args[3])
            p3 = (cx + args[4], cy + args[5]) if rel else (args[4], args[5])
            bezier((cx, cy), p1, p2, p3)
            cx, cy = p3
        elif up in ("S", "Q", "T", "A"):
            # Approximate by their endpoint. These do not appear in the glyph paths of this
            # corpus; if that ever changes the sampling above should be extended rather than
            # this silently under-measuring.
            cx, cy = (cx + args[-2], cy + args[-1]) if rel else (args[-2], args[-1])
            emit(cx, cy)
    if cur:
        out.append(cur)
    return [c for c in out if c]


def box(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def boxes_within(a, b, eps):
    return not (a[2] + eps < b[0] or b[2] + eps < a[0]
                or a[3] + eps < b[1] or b[3] + eps < a[1])


def outline_distance(a, b, eps):
    """Smallest distance between two outlines, given up early once inside `eps`."""
    best = math.inf
    for x0, y0 in a:
        for x1, y1 in b:
            d = math.hypot(x0 - x1, y0 - y1)
            if d < best:
                best = d
                if best <= eps:
                    return best
    return best


def band_of(bands, y):
    for i, b in enumerate(bands):
        if b["top"] - 1e-9 <= y <= b["bottom"] + 1e-9:
            return i + 1
    # Above the first line or below the last: attribute to the nearer, so a descender
    # hanging past the last baseline is not reported as homeless.
    return 1 if y < bands[0]["top"] else len(bands)


def check_page(args):
    svg_path, lines_path, eps = args
    name = os.path.basename(svg_path)
    if not os.path.exists(lines_path):
        return {"file": name, "skipped": True}
    bands = json.load(open(lines_path, encoding="utf-8"))
    if len(bands) < 2:
        return {"file": name, "skipped": True}

    # `Page` composes the transform stack — including the negative y-scale these pages carry
    # — and records the `<g>` chain each path sits under. Reusing it means this cannot
    # disagree with the generator about where a contour is; reimplementing the CTM here
    # produced coordinates off the page on the first attempt.
    page = Page(svg_path)
    if not page.paths:
        return {"file": name, "skipped": True}

    groups = {}
    for p in page.paths:
        line = None
        for tag in p["chain"]:
            m = LINE_ATTR_RE.search(tag)
            if m:
                line = int(m.group(1))
        if line is None:
            continue
        for pts in flatten(p["d"], p["M"]):
            groups.setdefault(line, []).append({"pts": pts, "box": box(pts)})

    if not groups:
        return {"file": name, "skipped": True}
    groups = sorted(groups.items())

    offenders = []
    for line, contours in groups:
        for c in contours:
            cy = (c["box"][1] + c["box"][3]) / 2
            own = band_of(bands, cy)
            if own == line:
                continue
            # Only contours lying *wholly* inside another band are reported. A contour that
            # straddles a boundary — a descender, a kashida reaching down — has a genuinely
            # ambiguous home and either answer is defensible; flagging those would drown the
            # ones that are unambiguous in noise.
            band = bands[own - 1]
            if not (c["box"][1] >= band["top"] - 1e-9 and c["box"][3] <= band["bottom"] + 1e-9):
                continue
            # Assigned away from its own band. Justified only by genuinely touching
            # something in the group it was put in.
            touching = False
            for other in contours:
                if other is c:
                    continue
                if not boxes_within(c["box"], other["box"], eps):
                    continue
                if outline_distance(c["pts"], other["pts"], eps) <= eps:
                    touching = True
                    break
            if not touching:
                offenders.append({
                    "line": line, "own": own,
                    "x": round(c["box"][0], 2), "y": round(cy, 2),
                    "w": round(c["box"][2] - c["box"][0], 2),
                })

    return {"file": name, "contours": sum(len(c) for _, c in groups),
            "offenders": offenders}


def editions(only):
    out = []
    for mushaf in sorted(os.listdir(ROOT)):
        mdir = os.path.join(ROOT, mushaf)
        if not os.path.isdir(mdir):
            continue
        for pub in sorted(os.listdir(mdir)):
            rel = "%s/%s" % (mushaf, pub)
            if only and rel != only:
                continue
            if os.path.isdir(os.path.join(mdir, pub, "svg")):
                out.append(rel)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mushaf", nargs="?", help="edition, e.g. hafs/kfqc; omit for all")
    ap.add_argument("--pages", help="comma-separated page numbers")
    ap.add_argument("--eps", type=float, default=DEFAULT_EPS)
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    args = ap.parse_args()

    wanted = None
    if args.pages:
        wanted = {int(p) for p in args.pages.split(",")}

    total_offenders = 0
    for rel in editions(args.mushaf):
        base = os.path.join(ROOT, rel)
        tasks = []
        for name in sorted(os.listdir(os.path.join(base, "svg"))):
            if not name.endswith(".svg") or re.search(r"\d+-surah", name):
                continue
            stem = os.path.splitext(name)[0]
            if wanted and int(re.match(r"\d+", stem).group(0)) not in wanted:
                continue
            tasks.append((os.path.join(base, "svg", name),
                          os.path.join(base, "lines", stem + ".json"),
                          args.eps))

        with Pool(args.jobs) as pool:
            results = pool.map(check_page, tasks)

        done = [r for r in results if "offenders" in r]
        bad = [r for r in done if r["offenders"]]
        n = sum(len(r["offenders"]) for r in done)
        total_offenders += n

        print("%-16s pages %3d   contours %7d   misassigned %d%s" % (
            rel, len(done), sum(r["contours"] for r in done), n,
            "   on %d page(s)" % len(bad) if bad else ""))
        for r in bad[:5]:
            for o in r["offenders"][:3]:
                print("     %s  contour at (%.1f, %.1f) w=%.1f is on line %d, its ink is on line %d"
                      % (r["file"], o["x"], o["y"], o["w"], o["line"], o["own"]))

    return 1 if total_offenders else 0


if __name__ == "__main__":
    sys.exit(main())
