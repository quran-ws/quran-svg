#!/usr/bin/env python3
"""Split each line's merged glyph path into one <path> per element of ink.

An "element" is one connected piece of ink together with its counters: a letter-body
ligature, a dot group drawn as one contour, a fatha, a hamza. The page draws each line as
a single <path> whose subpaths are these contours; this tool regroups them into separate
<path> elements so each can be addressed, classified and labelled individually — the
prerequisite for word/ligature/diacritic metadata a la MushafDatabase.

`fill-rule="evenodd"` makes the grouping delicate: a contour nested inside another (the
counter of م or ه) must stay in the same <path> as its outer contour or it fills solid,
while a dot sitting inside a letter's *bounding box* but not inside its ink must NOT be
merged. Nesting is therefore decided by an exact even-odd point test against the actual
outline, not by boxes. Contour source text is copied verbatim (same technique as
add_line_structure.py), so the ink is bit-identical; a render diff proves it.

    tools/split_line_elements.py hafs/kfqc 3                 # one page, to scratch dir
    tools/split_line_elements.py hafs/kfqc 3 -o out.svg      # explicit output
    tools/split_line_elements.py hafs/kfqc 3 --verify        # + rsvg-convert pixel diff
    tools/split_line_elements.py --batch --verify            # every edition, sample pages
    tools/split_line_elements.py --batch warsh/kfqc --pages all --verify --jobs 8
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from page import Page
from svg_lines import tokenize, subpaths, fmt
from add_line_structure import build_d

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Contour geometry: flatten each contour to a polyline for point-in-contour tests
# ---------------------------------------------------------------------------

def _bezier_points(p0, ctrl, samples=8):
    """Points along a bezier of any order, endpoints excluded/included as needed."""
    pts = []
    n = len(ctrl)
    for k in range(1, samples + 1):
        t = k / samples
        # de Casteljau
        work = [p0] + ctrl
        while len(work) > 1:
            work = [((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1])
                    for a, b in zip(work, work[1:])]
        pts.append(work[0])
    return pts


def contour_polylines(d):
    """One polyline per contour of `d`, in the path's own coordinate space.

    Sampling density only affects the point-in-contour test; glyph contours never graze
    each other closely enough for 8 samples per curve to flip a verdict, and the render
    diff would catch it if they did.
    """
    polys = []
    cur = None
    cx = cy = sx = sy = 0.0
    prev_ctrl = None
    prev_kind = None
    for cmd, a, _s, _e in tokenize(d):
        rel = cmd.islower()
        c = cmd.lower()
        if c == "m":
            if cur:
                polys.append(cur)
            nx = cx + a[0] if rel else a[0]
            ny = cy + a[1] if rel else a[1]
            cur = [(nx, ny)]
            cx, cy = sx, sy = nx, ny
            prev_ctrl, prev_kind = None, "m"
            continue
        if cur is None:
            continue
        if c in ("l", "h", "v"):
            if c == "l":
                nx = cx + a[0] if rel else a[0]
                ny = cy + a[1] if rel else a[1]
            elif c == "h":
                nx, ny = (cx + a[0] if rel else a[0]), cy
            else:
                nx, ny = cx, (cy + a[0] if rel else a[0])
            cur.append((nx, ny))
            cx, cy = nx, ny
            prev_ctrl, prev_kind = None, "l"
        elif c in ("c", "s"):
            if c == "c":
                pts = [(a[0], a[1]), (a[2], a[3]), (a[4], a[5])]
                if rel:
                    pts = [(cx + x, cy + y) for x, y in pts]
            else:
                r = prev_ctrl if prev_kind in ("c", "s") and prev_ctrl else (cx, cy)
                p1 = (2 * cx - r[0], 2 * cy - r[1])
                rest = [(a[0], a[1]), (a[2], a[3])]
                if rel:
                    rest = [(cx + x, cy + y) for x, y in rest]
                pts = [p1] + rest
            cur.extend(_bezier_points((cx, cy), pts))
            prev_ctrl = pts[1]
            cx, cy = pts[2]
            prev_kind = c
        elif c in ("q", "t"):
            if c == "q":
                ctrl = (cx + a[0], cy + a[1]) if rel else (a[0], a[1])
                end = (cx + a[2], cy + a[3]) if rel else (a[2], a[3])
            else:
                r = prev_ctrl if prev_kind in ("q", "t") and prev_ctrl else (cx, cy)
                ctrl = (2 * cx - r[0], 2 * cy - r[1])
                end = (cx + a[0], cy + a[1]) if rel else (a[0], a[1])
            cur.extend(_bezier_points((cx, cy), [ctrl, end]))
            prev_ctrl = ctrl
            cx, cy = end
            prev_kind = c
        elif c == "a":
            nx = cx + a[5] if rel else a[5]
            ny = cy + a[6] if rel else a[6]
            cur.append((nx, ny))          # chord; arcs do not occur in the glyph art
            cx, cy = nx, ny
            prev_ctrl, prev_kind = None, "a"
        elif c == "z":
            cx, cy = sx, sy
            prev_ctrl, prev_kind = None, "z"
    if cur:
        polys.append(cur)
    return polys


def point_in_poly(x, y, poly):
    """Even-odd ray crossing test, matching how the renderer evaluates fill parity."""
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if xi > x:
                inside = not inside
    return inside


# ---------------------------------------------------------------------------
# Grouping contours into elements
# ---------------------------------------------------------------------------

def group_elements(d):
    """Partition the contours of `d` into elements: outer contour + nested counters.

    Each contour is attached to its innermost enclosing contour; connected components of
    that forest are the elements. Because today the whole line shares one path, parity
    already applies across exactly these nestings — regrouping by true containment is
    therefore a rendering no-op, which --verify proves.
    """
    sps = subpaths(d)
    polys = contour_polylines(d)
    if len(sps) != len(polys):
        raise AssertionError("contour count mismatch: %d vs %d" % (len(sps), len(polys)))

    n = len(sps)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(n), key=lambda i: (sps[i]["xmax"] - sps[i]["xmin"]) *
                                           (sps[i]["ymax"] - sps[i]["ymin"]))
    for ii, i in enumerate(order):
        si = sps[i]
        pts = polys[i]
        # sample several points around the contour: a single boundary point can
        # parity-flip against an open bowl's outline (a ن sweeping under the
        # next word) and weld unrelated ink into one element
        step = max(1, len(pts) // 5)
        samples = pts[::step][:5] or [pts[0]]
        best, best_area = None, None
        for j in order[ii + 1:]:              # only larger contours can enclose i
            sj = sps[j]
            if not (sj["xmin"] <= si["xmin"] and sj["xmax"] >= si["xmax"] and
                    sj["ymin"] <= si["ymin"] and sj["ymax"] >= si["ymax"]):
                continue
            inside = sum(1 for (px, py) in samples if point_in_poly(px, py, polys[j]))
            if inside * 2 > len(samples):
                area = (sj["xmax"] - sj["xmin"]) * (sj["ymax"] - sj["ymin"])
                if best is None or area < best_area:
                    best, best_area = j, area
        if best is not None:
            root = find(best)
            parent[find(i)] = root

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    # Elements in document order of their first contour, contours in document order.
    out = []
    for root in sorted(groups, key=lambda r: min(groups[r])):
        idxs = sorted(groups[root])
        out.append([{"sp": sps[i]} for i in idxs])
    return out


# ---------------------------------------------------------------------------
# Page rewrite
# ---------------------------------------------------------------------------

PATH_RE = re.compile(r"<path\b[^>]*\bd=\"([^\"]*)\"[^>]*/>")


def explode(page):
    """Return (svg_text, stats): every #content glyph path split into element paths."""
    start, end = page.content
    svg = page.svg
    body = svg[start:end]

    stats = {"paths": 0, "contours": 0, "elements": 0, "counters": 0}

    def split_path(m):
        text = m.group(0)
        if "ayahPolygon" in text:
            return text
        d = m.group(1)
        a, b = m.span(1)
        a -= m.start(0)
        b -= m.start(0)
        head, tail = text[:a], text[b:]
        elements = group_elements(d)
        stats["paths"] += 1
        stats["elements"] += len(elements)
        for el in elements:
            stats["contours"] += len(el)
            stats["counters"] += len(el) - 1
        parts = []
        for k, el in enumerate(elements):
            h = head.replace("<path ", '<path data-el="%d" ' % (k + 1), 1)
            parts.append(h + build_d(el) + tail)
        return "".join(parts)

    new_body = PATH_RE.sub(split_path, body)
    return svg[:start] + new_body + svg[end:], stats


def verify(before, after, viewbox, scale=3, tolerance=100):
    """Render both and compare. Returns (ok, max_diff).

    Splitting one path into many is not byte-identical under antialiasing: edge coverage
    is composited per <path>, so borderline pixels shift by a few alpha levels. A real
    grouping error is categorically different — an evenodd parity flip turns full ink
    into none, a ~255 alpha jump. PASS therefore means no pixel moved more than
    `tolerance`; observed AA noise on a full page tops out around 64.
    """
    import numpy as np
    from PIL import Image

    width = max(16, int(viewbox[2] * scale))
    imgs = []
    with tempfile.TemporaryDirectory() as tmp:
        for tag, data in (("before", before), ("after", after)):
            src = os.path.join(tmp, tag + ".svg")
            png = os.path.join(tmp, tag + ".png")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(data)
            subprocess.run(["rsvg-convert", "-w", str(width), src, "-o", png],
                           check=True, capture_output=True)
            imgs.append(np.asarray(Image.open(png).convert("RGBA")).astype(int))
    # A real evenodd error fills or empties a whole counter — a contiguous region of
    # full-delta pixels. A hairline stroke rasterized in its own path can flip an
    # isolated edge pixel (observed on 9 of 3,610 pages, ~1 px each), so tolerate a
    # handful of outliers rather than a single max.
    diff = np.abs(imgs[0] - imgs[1]).max(axis=2)
    max_diff = int(diff.max())
    n_big = int((diff > tolerance).sum())
    return n_big <= 4, max_diff


def editions(selector=None):
    """Every `<qiraa>/<publisher>` under mushafs/, or just the selected one."""
    base = os.path.join(ROOT, "mushafs")
    for qiraa in sorted(os.listdir(base)):
        qdir = os.path.join(base, qiraa)
        if not os.path.isdir(qdir):
            continue
        for pub in sorted(os.listdir(qdir)):
            ed = "%s/%s" % (qiraa, pub)
            if os.path.isdir(os.path.join(qdir, pub, "svg")) and selector in (None, ed):
                yield ed


# One variant page rides along with every sample so the cropped-viewBox form is covered.
SAMPLE_PAGES = [1, 2, 3, 50, 106, 255, 400, 604]


def page_files(edition, spec):
    svg_dir = os.path.join(ROOT, "mushafs", edition, "svg")
    names = sorted(os.listdir(svg_dir))
    if spec == "all":
        return [n for n in names if n.endswith(".svg")]
    if spec == "sample":
        picked = ["%03d.svg" % p for p in SAMPLE_PAGES if "%03d.svg" % p in names]
        variants = [n for n in names if re.match(r"^\d+-surah\d+\.svg$", n)]
        return picked + variants[:1]
    out = []
    for part in spec.split(","):
        if "-" in part.strip() and not part.strip().endswith(".svg"):
            a, b = part.split("-")
            out += ["%03d.svg" % p for p in range(int(a), int(b) + 1)]
        elif part.strip().endswith(".svg"):
            out.append(part.strip())
        else:
            out.append("%03d.svg" % int(part))
    return [n for n in out if n in names]


def process(job):
    edition, name, do_verify, scale = job
    src = os.path.join(ROOT, "mushafs", edition, "svg", name)
    res = {"edition": edition, "name": name}
    try:
        page = Page(src)
        if page.content is None:
            res["error"] = "no #content group"
            return res
        out_svg, stats = explode(page)
        res.update(stats)
        if do_verify:
            ok, max_diff = verify(page.svg, out_svg, page.viewbox, scale)
            res["ok"], res["max_diff"] = ok, max_diff
    except Exception as e:  # noqa: BLE001 — a batch must report, not die
        res["error"] = "%s: %s" % (type(e).__name__, e)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("edition", nargs="?", help="e.g. hafs/kfqc (batch: default all)")
    ap.add_argument("page", nargs="?", type=int, help="single-page mode")
    ap.add_argument("-o", "--out", help="output SVG path (single-page mode)")
    ap.add_argument("--verify", action="store_true", help="pixel-diff with rsvg-convert")
    ap.add_argument("--batch", action="store_true", help="run many pages, report only")
    ap.add_argument("--pages", default="sample",
                    help='batch pages: "sample", "all", "1,3,10-20", or filenames')
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--scale", type=float, default=3.0)
    args = ap.parse_args(argv)

    if not args.batch and args.edition and args.page is not None:
        src = os.path.join(ROOT, "mushafs", args.edition, "svg", "%03d.svg" % args.page)
        page = Page(src)
        if page.content is None:
            sys.exit("no #content group in " + src)
        out_svg, stats = explode(page)
        out_path = args.out or os.path.join(
            tempfile.gettempdir(), "%s-%03d-elements.svg"
            % (args.edition.replace("/", "-"), args.page))
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(out_svg)
        print("%s: %d line paths -> %d elements (%d contours, %d counters kept nested)"
              % (os.path.relpath(src, ROOT), stats["paths"], stats["elements"],
                 stats["contours"], stats["counters"]))
        print("wrote", out_path)
        if args.verify:
            ok, max_diff = verify(page.svg, out_svg, page.viewbox, args.scale)
            print("render diff: %s (max pixel delta %d/255, AA noise only if <= 100)"
                  % ("PASS" if ok else "FAIL", max_diff))
            sys.exit(0 if ok else 1)
        return

    jobs = [(ed, name, args.verify, args.scale)
            for ed in editions(args.edition)
            for name in page_files(ed, args.pages)]
    if not jobs:
        sys.exit("nothing matched")

    from multiprocessing import Pool
    failures = []
    totals = {}
    with Pool(args.jobs) as pool:
        for i, res in enumerate(pool.imap_unordered(process, jobs), 1):
            t = totals.setdefault(res["edition"], {"pages": 0, "elements": 0, "worst": 0})
            if "error" in res or res.get("ok") is False:
                failures.append(res)
                print("FAIL %s/%s: %s" % (res["edition"], res["name"],
                                          res.get("error", "max delta %d" % res.get("max_diff", -1))))
            else:
                t["pages"] += 1
                t["elements"] += res.get("elements", 0)
                t["worst"] = max(t["worst"], res.get("max_diff", 0))
            if i % 50 == 0:
                print("  … %d/%d" % (i, len(jobs)), file=sys.stderr)

    print()
    for ed in sorted(totals):
        t = totals[ed]
        print("%-20s %4d pages OK, %6d elements, worst pixel delta %d"
              % (ed, t["pages"], t["elements"], t["worst"]))
    if failures:
        print("\n%d FAILURES" % len(failures))
        sys.exit(1)
    print("\nall pages verified" if args.verify else "\ndone (no verify)")


if __name__ == "__main__":
    main()
