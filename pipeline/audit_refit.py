#!/usr/bin/env python3
"""Check that a re-fit changed how an outline is described, not what it is.

Size and pixel counts cannot see the failures that matter here.  A contour can vanish, a
stroke can pinch shut at a narrow neck and split in two, two neighbouring letters can grow
together, a counter -- the hole in a ه or a و -- can fill in, and a page will still look
about right and still be smaller.  Those are topology changes, and they need counting, not
measuring.

Two independent passes, because they fail differently:

**Per contour, from the geometry.**  Every contour is matched to the one it replaced, and
compared on the things a fit must preserve: that it is still closed, still wound the same
way, still has area, and still encloses about as much as it did.  A contour that shrinks or
swells materially is reported whatever its size, and small ones -- the dots and the
diacritics, which have the least room to lose -- are reported at a tighter threshold, since
0.15 pt off a dot is a far bigger fraction than 0.15 pt off a stem.

**Per page, from the ink.**  Both versions are rasterised and their connected components
counted, ink and background alike.  This is what actually answers "did anything become
disconnected": a pinched stroke shows up as one component becoming two, a lost contour as one
disappearing, letters growing together as two becoming one, and a filled counter as a
background component disappearing.  It needs no correspondence between the two files and no
assumption about how either was drawn.

    python3 pipeline/audit_refit.py --pages 3,106,255,550,604
    python3 pipeline/audit_refit.py --pages 550 --scale 12 --verbose
"""

import argparse
import collections
import os
import re
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import curvefit                                                  # noqa: E402
import editions                                                  # noqa: E402
import pathdata                                                  # noqa: E402

EDITION = "hafs/kfqc-1422"
_D = re.compile(r'<path d="([^"]*)"')

# A contour this small is a dot or a fragment of a diacritic, in square points.
SMALL = 4.0
AREA_TOL = 0.06          # a contour may change area by this fraction
SMALL_AREA_TOL = 0.12    # small ones get more room, being mostly outline
MIN_BLOB = 4             # raster components below this many pixels are antialiasing crumbs


def contour_stats(sub):
    """(closed, signed area, perimeter) of one contour, from a dense flattening."""
    pts, closed = curvefit.flatten(sub, 0.01)
    if len(pts) < 3:
        return closed, 0.0, 0.0
    a = 0.0
    per = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        a += x0 * y1 - x1 * y0
        per += ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    return closed, a / 2.0, per


def geometry_report(subs, fitted):
    """Everything the per-contour comparison found."""
    out = dict(count_before=len(subs), count_after=len(fitted),
               opened=[], sign_flipped=[], vanished=[], area=[], worst=0.0)
    for i, (a, b) in enumerate(zip(subs, fitted)):
        ca, aa, _ = contour_stats(a)
        cb, ab, _ = contour_stats(b)
        if ca and not cb:
            out["opened"].append(i)
        if aa != 0 and ab != 0 and (aa > 0) != (ab > 0):
            out["sign_flipped"].append(i)
        if abs(aa) > 0.05 and abs(ab) < 0.01 * abs(aa):
            out["vanished"].append((i, abs(aa)))
            continue
        if abs(aa) < 1e-9:
            continue
        ratio = abs(ab) / abs(aa)
        limit = SMALL_AREA_TOL if abs(aa) < SMALL else AREA_TOL
        out["worst"] = max(out["worst"], abs(ratio - 1))
        if abs(ratio - 1) > limit:
            out["area"].append((i, abs(aa), ratio))
    return out


def _mask(svg_text, scale):
    box = [float(v) for v in re.search(r'viewBox="([^"]*)"', svg_text).group(1).split()]
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as fh:
        fh.write(svg_text)
        p = fh.name
    png = p + ".png"
    try:
        subprocess.run(["rsvg-convert", "-w", str(int(box[2] * scale)),
                        "-h", str(int(box[3] * scale)), p, "-o", png],
                       check=True, capture_output=True)
        return np.array(Image.open(png).convert("RGBA"))[..., 3] > 128
    finally:
        for f in (p, png):
            if os.path.exists(f):
                os.unlink(f)


def blobs(mask):
    """(count, sizes, centroids) of the components above the crumb threshold."""
    lab, n = ndimage.label(mask)
    if n == 0:
        return 0, np.array([]), np.zeros((0, 2))
    sizes = np.bincount(lab.ravel())[1:]
    keep = np.where(sizes >= MIN_BLOB)[0] + 1
    cents = np.array(ndimage.center_of_mass(mask, lab, keep)) if len(keep) else np.zeros((0, 2))
    return len(keep), sizes[keep - 1], cents


def _overlaps(a, b, min_px):
    """Splits and merges between two ink masks, found by label overlap rather than by
    centroid distance.

    Distance between centres cannot see a split: a stroke that pinches in two leaves both
    halves sitting where the whole one was.  Overlap can -- a component of one mask is
    matched to every component of the other that shares a pixel with it, so one-to-two is a
    split, two-to-one a merge, and one-to-none a disappearance."""
    la, na = ndimage.label(a)
    lb, nb = ndimage.label(b)
    sa = np.bincount(la.ravel())
    sb = np.bincount(lb.ravel())
    pairs = collections.defaultdict(set)
    rev = collections.defaultdict(set)
    both = (la > 0) & (lb > 0)
    for i, j in set(zip(la[both].tolist(), lb[both].tolist())):
        if sa[i] >= min_px and sb[j] >= min_px:
            pairs[i].add(j)
            rev[j].add(i)
    splits = [(int(sa[i]), sorted(int(sb[j]) for j in js))
              for i, js in pairs.items() if len(js) > 1]
    merges = [(int(sb[j]), sorted(int(sa[i]) for i in ins))
              for j, ins in rev.items() if len(ins) > 1]
    return splits, merges


def topology_report(before, after, scale):
    a_ink, a_sizes, a_cent = blobs(before)
    b_ink, b_sizes, b_cent = blobs(after)
    # a hole is a background component that does not touch the border
    def holes(mask):
        lab, n = ndimage.label(~mask)
        if n == 0:
            return 0
        edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])))
        sizes = np.bincount(lab.ravel())
        return sum(1 for i in range(1, n + 1) if i not in edge and sizes[i] >= MIN_BLOB)
    lost, gained = [], []
    if len(a_cent) and len(b_cent):
        for i, c in enumerate(a_cent):
            d = np.hypot(b_cent[:, 0] - c[0], b_cent[:, 1] - c[1]).min()
            if d > 3 * scale:
                lost.append((c / scale, a_sizes[i]))
        for i, c in enumerate(b_cent):
            d = np.hypot(a_cent[:, 0] - c[0], a_cent[:, 1] - c[1]).min()
            if d > 3 * scale:
                gained.append((c / scale, b_sizes[i]))
    splits, merges = _overlaps(before, after, MIN_BLOB)
    return dict(splits=splits, merges=merges,
                ink_before=a_ink, ink_after=b_ink,
                holes_before=holes(before), holes_after=holes(after),
                smallest_before=int(a_sizes.min()) if len(a_sizes) else 0,
                smallest_after=int(b_sizes.min()) if len(b_sizes) else 0,
                lost=lost, gained=gained)


CFG = dict(tol=0.15, angle=70, window=0.25, detect_smooth=0.20, smooth=0.15,
           min_diagonal=6.0, small_thin=0.02, clearance_share=0.4, size_share=0.008)


def compare_editions(page, scale, src, dst):
    """The same checks, but between two editions on disk rather than against a recomputation.

    This is what audits the thing that shipped.  ``check()`` re-runs the fit and inspects the
    result, which answers "would this be safe"; this one opens both published files and asks
    "is it".
    """
    with open(editions.page_path(src, page), encoding="utf-8") as fh:
        a_text = fh.read()
    with open(editions.page_path(dst, page), encoding="utf-8") as fh:
        b_text = fh.read()
    a_subs, b_subs = [], []
    for d in _D.findall(a_text[a_text.find('<g id="content"'):]):
        a_subs += pathdata.parse(d)
    for d in _D.findall(b_text[b_text.find('<g id="content"'):]):
        b_subs += pathdata.parse(d)
    geo = geometry_report(a_subs, b_subs)
    top = topology_report(_mask(a_text, scale), _mask(b_text, scale), scale)
    return page, geo, top


def check(page, scale, cfg):
    src = editions.page_path(EDITION, page)
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    cut = text.find('<g id="content"')
    head, body = text[:cut], text[cut:]
    subs = []
    for d in _D.findall(body):
        subs += pathdata.parse(d)
    fitted = curvefit.refit(subs, **cfg)
    geo = geometry_report(subs, fitted)
    it = iter(fitted)

    def one(m):
        n = len(pathdata.parse(m.group(1)))
        return '<path d="%s"' % re.sub(r"[ ,](-)", r"\1",
                                       pathdata.emit([next(it) for _ in range(n)], nd=3))
    new = head + _D.sub(one, body)
    top = topology_report(_mask(text, scale), _mask(new, scale), scale)
    return page, geo, top


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", default="3,106,255,550,604")
    ap.add_argument("--scale", type=float, default=8.0)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--compare", nargs=2, metavar=("SRC", "DST"),
                    help="audit two published editions against each other instead of "
                         "re-running the fit, e.g. --compare hafs/kfqc-1422 "
                         "hafs/kfqc-1422-optimized")
    ap.add_argument("--workers", type=int, default=min(6, os.cpu_count() or 4))
    args = ap.parse_args(argv)

    pages = []
    for part in args.pages.split(","):
        if "-" in part.strip("-"):
            lo, hi = part.split("-")
            pages.extend(range(int(lo), int(hi) + 1))
        else:
            pages.append(int(part))

    bad = 0
    if args.compare:
        from multiprocessing import Pool
        with Pool(args.workers) as pool:
            results = pool.starmap(compare_editions,
                                   [(p, args.scale, args.compare[0], args.compare[1])
                                    for p in pages])
    else:
        results = [check(p, args.scale, CFG) for p in pages]
    for page, geo, top in results:
        problems = (geo["count_before"] != geo["count_after"]
                    or geo["opened"] or geo["sign_flipped"] or geo["vanished"]
                    or top["ink_before"] != top["ink_after"]
                    or top["holes_before"] != top["holes_after"]
                    or top["lost"] or top["gained"]
                    or top["splits"] or top["merges"])
        bad += bool(problems)
        print("page %-4d  contours %d -> %d   ink blobs %d -> %d   counters %d -> %d"
              % (page, geo["count_before"], geo["count_after"],
                 top["ink_before"], top["ink_after"],
                 top["holes_before"], top["holes_after"]))
        print("           smallest ink blob %d -> %d px;  worst area change %.1f%%;  "
              "%d contours past the area limit"
              % (top["smallest_before"], top["smallest_after"],
                 100 * geo["worst"], len(geo["area"])))
        for tag in ("opened", "sign_flipped"):
            if geo[tag]:
                print("           %s: contours %s" % (tag, geo[tag][:10]))
        for i, a in geo["vanished"][:10]:
            print("           VANISHED contour %d (was %.3f sq pt)" % (i, a))
        for whole, parts in sorted(top["splits"], key=lambda t: -t[0])[:6]:
            print("           SPLIT  %d px became %s" % (whole, parts))
        for whole, parts in sorted(top["merges"], key=lambda t: -t[0])[:6]:
            print("           MERGE  %s became %d px" % (parts, whole))
        for c, s in top["lost"][:10]:
            print("           ink LOST near page (%.1f, %.1f), %d px" % (c[1], c[0], s))
        for c, s in top["gained"][:10]:
            print("           ink GAINED near page (%.1f, %.1f), %d px" % (c[1], c[0], s))
        if args.verbose:
            for i, a, r in sorted(geo["area"], key=lambda t: -abs(t[2] - 1))[:15]:
                print("           contour %-5d area %8.3f sq pt -> x%.3f" % (i, a, r))
    print("\n%s" % ("all pages clean" if not bad else "%d page(s) with findings" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
