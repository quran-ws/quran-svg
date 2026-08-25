"""Geometry helpers for recovering per-line structure from a mushaf page SVG.

A page's whole body is a single `<path>` whose `d` runs to hundreds of thousands of
characters: `hafs/255` is 456,221. There is no markup to group it by line, so lines have
to be recovered from geometry — the vertical position of each glyph contour.

Nothing here rounds, re-fits or rewrites geometry. Every coordinate that ends up back in
an SVG is either copied verbatim from the source or is an absolute `moveto` computed from
the source at full float64 precision, so the restructuring is pixel-for-pixel a no-op.
"""

import math
import re

# ---------------------------------------------------------------------------
# Path data
# ---------------------------------------------------------------------------

_NUM = re.compile(r"[-+]?(?:\d*\.\d+(?:[eE][-+]?\d+)?|\d+\.?(?:[eE][-+]?\d+)?)")
_CMD = "MmLlHhVvCcSsQqTtAaZz"
_ARGC = {"m": 2, "l": 2, "h": 1, "v": 1, "c": 6, "s": 4, "q": 4, "t": 2, "a": 7, "z": 0}


def tokenize(d):
    """Split path data into (command, args, start, end) tuples.

    `start`/`end` index back into `d`, which is what lets a subpath be moved to another
    element by copying its source text rather than re-serialising its numbers.
    """
    out = []
    i, n = 0, len(d)
    while i < n:
        ch = d[i]
        if ch in " ,\t\r\n":
            i += 1
            continue
        if ch not in _CMD:
            raise ValueError("unexpected %r at %d: %r" % (ch, i, d[max(0, i - 20):i + 20]))
        nargs = _ARGC[ch.lower()]
        i += 1
        if nargs == 0:
            out.append((ch, [], i - 1, i))
            continue
        # A command may be followed by several argument groups; the 2nd onward repeat the
        # command implicitly, except that m/M repeat as l/L (SVG 1.1 §8.3.2).
        repeat = {"m": "l", "M": "L"}.get(ch, ch)
        first = True
        while True:
            j = i
            while j < n and d[j] in " ,\t\r\n":
                j += 1
            if not _NUM.match(d, j):
                break
            args, k = [], j
            for _ in range(nargs):
                while k < n and d[k] in " ,\t\r\n":
                    k += 1
                m = _NUM.match(d, k)
                if m is None:
                    raise ValueError("truncated args at %d" % k)
                args.append(float(m.group(0)))
                k = m.end()
            out.append((ch if first else repeat, args, i - 1 if first else j, k))
            i, first = k, False
    return out


def _cubic_extrema(p0, p1, p2, p3):
    """Exact 1-D extrema of a cubic Bezier, endpoints included."""
    lo, hi = min(p0, p3), max(p0, p3)
    a = -p0 + 3 * p1 - 3 * p2 + p3
    b = 2 * (p0 - 2 * p1 + p2)
    c = p1 - p0
    ts = []
    if abs(a) < 1e-12:
        if abs(b) > 1e-12:
            ts.append(-c / b)
    else:
        disc = b * b - 4 * a * c
        if disc >= 0:
            r = math.sqrt(disc)
            ts += [(-b + r) / (2 * a), (-b - r) / (2 * a)]
    for t in ts:
        if 0 < t < 1:
            u = 1 - t
            v = (u * u * u * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t * t * t * p3)
            lo, hi = min(lo, v), max(hi, v)
    return lo, hi


def _quad_extrema(p0, p1, p2):
    lo, hi = min(p0, p2), max(p0, p2)
    den = p0 - 2 * p1 + p2
    if abs(den) > 1e-12:
        t = (p0 - p1) / den
        if 0 < t < 1:
            u = 1 - t
            v = u * u * p0 + 2 * u * t * p1 + t * t * p2
            lo, hi = min(lo, v), max(hi, v)
    return lo, hi


class Subpath(dict):
    """One glyph contour: its source text, its start point, and its exact bounding box."""


def subpaths(d):
    """Split `d` into contours, each with an exact bounding box in the path's own space.

    Bounding boxes solve the Bezier derivative rather than hulling the control points.
    Control-point hulls inflate a contour far past its ink at these coordinate scales and
    bridge the gaps between lines, which is precisely what line recovery depends on.
    """
    res = []
    cx = cy = sx = sy = 0.0
    cur = None
    prev_ctrl = None          # reflected control point for S/T
    prev_kind = None

    def start(nx, ny, tok_start, tok_end):
        return Subpath(text_start=tok_start, head_end=tok_end, abs_start=(nx, ny),
                       xmin=nx, xmax=nx, ymin=ny, ymax=ny)

    def grow(x0, x1, y0, y1):
        if x0 < cur["xmin"]:
            cur["xmin"] = x0
        if x1 > cur["xmax"]:
            cur["xmax"] = x1
        if y0 < cur["ymin"]:
            cur["ymin"] = y0
        if y1 > cur["ymax"]:
            cur["ymax"] = y1

    for cmd, a, s, e in tokenize(d):
        rel = cmd.islower()
        c = cmd.lower()
        if c == "m":
            if cur is not None:
                cur["text_end"] = s
                res.append(cur)
            nx = cx + a[0] if rel else a[0]
            ny = cy + a[1] if rel else a[1]
            cur = start(nx, ny, s, e)
            cx, cy = sx, sy = nx, ny
            prev_ctrl, prev_kind = None, "m"
            continue
        if cur is None:                      # data before any moveto — malformed, ignore
            continue
        if c == "l":
            nx = cx + a[0] if rel else a[0]
            ny = cy + a[1] if rel else a[1]
            grow(min(cx, nx), max(cx, nx), min(cy, ny), max(cy, ny))
            cx, cy = nx, ny
            prev_ctrl, prev_kind = None, "l"
        elif c == "h":
            nx = cx + a[0] if rel else a[0]
            grow(min(cx, nx), max(cx, nx), cy, cy)
            cx = nx
            prev_ctrl, prev_kind = None, "l"
        elif c == "v":
            ny = cy + a[0] if rel else a[0]
            grow(cx, cx, min(cy, ny), max(cy, ny))
            cy = ny
            prev_ctrl, prev_kind = None, "l"
        elif c in ("c", "s"):
            if c == "c":
                pts = [(a[0], a[1]), (a[2], a[3]), (a[4], a[5])]
            else:
                r = prev_ctrl if prev_kind in ("c", "s") and prev_ctrl else (cx, cy)
                refl = (2 * cx - r[0], 2 * cy - r[1])
                pts = [(a[0], a[1]), (a[2], a[3])]
                pts = [(refl[0] - cx, refl[1] - cy) if rel else refl] + pts
            if rel:
                pts = [(cx + px, cy + py) for px, py in pts]
            x0, x1 = _cubic_extrema(cx, pts[0][0], pts[1][0], pts[2][0])
            y0, y1 = _cubic_extrema(cy, pts[0][1], pts[1][1], pts[2][1])
            grow(x0, x1, y0, y1)
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
            x0, x1 = _quad_extrema(cx, ctrl[0], end[0])
            y0, y1 = _quad_extrema(cy, ctrl[1], end[1])
            grow(x0, x1, y0, y1)
            prev_ctrl = ctrl
            cx, cy = end
            prev_kind = c
        elif c == "a":
            nx = cx + a[5] if rel else a[5]
            ny = cy + a[6] if rel else a[6]
            # Conservative: the arc stays inside the box grown by its radii.
            rx, ry = abs(a[0]), abs(a[1])
            grow(min(cx, nx) - rx, max(cx, nx) + rx, min(cy, ny) - ry, max(cy, ny) + ry)
            cx, cy = nx, ny
            prev_ctrl, prev_kind = None, "a"
        elif c == "z":
            cx, cy = sx, sy
            prev_ctrl, prev_kind = None, "z"
    if cur is not None:
        cur["text_end"] = len(d)
        res.append(cur)
    for i, sp in enumerate(res):
        sp["index"] = i
        sp["text"] = d[sp["text_start"]:sp["text_end"]]
        sp["tail"] = d[sp["head_end"]:sp["text_end"]]
    return res


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------

def parse_transform(text):
    """Compose an SVG transform list into (a, b, c, d, e, f)."""
    M = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, args in re.findall(r"(matrix|translate|scale|rotate)\s*\(([^)]*)\)", text or ""):
        v = [float(x) for x in _NUM.findall(args)]
        if name == "matrix":
            N = tuple(v[:6])
        elif name == "translate":
            N = (1.0, 0.0, 0.0, 1.0, v[0], v[1] if len(v) > 1 else 0.0)
        elif name == "scale":
            N = (v[0], 0.0, 0.0, v[1] if len(v) > 1 else v[0], 0.0, 0.0)
        else:
            r = math.radians(v[0])
            N = (math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 0.0, 0.0)
        M = mul(M, N)
    return M


def mul(M, N):
    return (M[0] * N[0] + M[2] * N[1], M[1] * N[0] + M[3] * N[1],
            M[0] * N[2] + M[2] * N[3], M[1] * N[2] + M[3] * N[3],
            M[0] * N[4] + M[2] * N[5] + M[4], M[1] * N[4] + M[3] * N[5] + M[5])


def apply(M, x, y):
    return (M[0] * x + M[2] * y + M[4], M[1] * x + M[3] * y + M[5])


def transform_box(M, xmin, ymin, xmax, ymax):
    """Bounding box of a transformed box. Handles the negative y-scale these pages use."""
    xs, ys = [], []
    for px, py in ((xmin, ymin), (xmax, ymin), (xmin, ymax), (xmax, ymax)):
        rx, ry = apply(M, px, py)
        xs.append(rx)
        ys.append(ry)
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------
# Line segmentation
# ---------------------------------------------------------------------------

ROW = 0.05          # page units per profile row
HALF_WINDOW = 0.5   # a boundary is scored on the ink within ±this


class Profile:
    """Ink density down the page: for each row, the total width of contours crossing it.

    Width rather than a plain count, because the thing that separates two lines is the
    absence of *body* text, and a line of body text is wide while the descender or the
    stray diacritic that reaches across a gap is narrow. A boolean coverage profile
    cannot tell those apart, and on these pages it doesn't: measured over hafs, contours
    bridge the inter-line gap on 590 of 604 pages, so coverage alone reports 11 or 12
    lines where there are 15.
    """

    def __init__(self, boxes):
        self.ylo = min(b[0] for b in boxes)
        self.yhi = max(b[1] for b in boxes)
        self.n = max(1, int((self.yhi - self.ylo) / ROW) + 2)
        diff = [0.0] * (self.n + 2)
        for y1, y2, w in boxes:
            lo = max(0, int((y1 - self.ylo) / ROW))
            hi = min(self.n - 1, int((y2 - self.ylo) / ROW))
            if hi < lo:
                continue
            diff[lo] += w
            diff[hi + 1] -= w
        # Prefix sums of the row profile, so the ink in any interval is one subtraction.
        cum = [0.0] * (self.n + 2)
        run = 0.0
        for i in range(self.n + 1):
            run += diff[i]
            cum[i + 1] = cum[i] + run * ROW
        self.cum = cum
        self.total = cum[self.n + 1]

    def ink(self, y0, y1):
        """Ink between two page coordinates."""
        def at(y):
            i = (y - self.ylo) / ROW
            if i <= 0:
                return 0.0
            if i >= self.n:
                return self.cum[self.n]
            k = int(i)
            t = i - k
            return self.cum[k] + (self.cum[k + 1] - self.cum[k]) * t
        return at(y1) - at(y0)

    def at(self, y):
        return self.ink(y - HALF_WINDOW, y + HALF_WINDOW)


def segment(boxes, expected):
    """Recover `expected` line bands from contour boxes.

    `boxes` are (top, bottom, width) in rendered page coordinates. Returns
    (bands, info) where bands is a list of (top, bottom).

    A muṣḥaf page is typeset on a fixed grid — the King Fahd Complex sets fifteen lines at
    a constant pitch — so the search is for one pitch and one offset, not fifteen
    independent cuts. That constraint is what makes the result trustworthy on the pages
    where a descender or a low diacritic reaches across into the next line: the grid is
    fitted where the page has least ink overall, and only then is each cut nudged, by at
    most a quarter of a line, onto the local minimum beside it.
    """
    if not boxes:
        return [], {"reason": "no ink"}
    prof = Profile(boxes)
    span = prof.yhi - prof.ylo
    if expected < 2 or span <= 0:
        return [(prof.ylo, prof.yhi)], {"pitch": span, "cuts": []}

    def cost(o, p):
        return sum(prof.at(o + k * p) for k in range(1, expected))

    def search(plo, phi, steps, around=None):
        """Best (offset, pitch) over a rectangle of the search space, at bounded cost."""
        best = None
        pstep = max(0.005, (phi - plo) / steps)
        p = plo
        while p <= phi + 1e-9:
            omin = prof.yhi - expected * p
            omax = prof.ylo
            if around is not None:
                omin, omax = max(omin, around - 1.5), min(omax, around + 1.5)
            ostep = max(0.01, (omax - omin) / steps)
            o = omin
            while o <= omax + 1e-9:
                c = cost(o, p)
                if best is None or c < best[0]:
                    best = (c, o, p)
                o += ostep
            p += pstep
        return best

    # The grid must cover the ink (p >= span/n) and no band may fall entirely outside it
    # (p <= span/(n-1)). Coarse pass over that rectangle, then a fine pass around the
    # winner — bounded work per page whatever the line count.
    lo, hi = span / expected, span / (expected - 1)
    coarse = search(lo, hi, 60)
    if coarse is None:
        return [], {"reason": "no fit"}
    _, o0, p0 = coarse
    width = (hi - lo) / 60
    best = search(max(lo, p0 - width), min(hi, p0 + width), 40, around=o0)
    _, o, p = best

    cuts = [o + k * p for k in range(1, expected)]
    grid_cuts = list(cuts)
    slack = p * 0.25
    for k, b in enumerate(cuts):
        lo_k, hi_k = b - slack, b + slack
        y, cands = lo_k, []
        while y <= hi_k:
            cands.append((round(prof.at(y), 9), abs(y - b), y))
            y += ROW
        cands.sort()
        cuts[k] = cands[0][2]
    for k in range(1, len(cuts)):
        cuts[k] = max(cuts[k], cuts[k - 1] + ROW)

    edges = [prof.ylo] + cuts + [prof.yhi]
    bands = [(edges[i], edges[i + 1]) for i in range(expected)]
    line_ink = prof.total / expected
    band_ink = [prof.ink(a, b) for a, b in bands]
    median_ink = sorted(band_ink)[len(band_ink) // 2]
    return bands, {
        "pitch": p,
        "offset": o,
        "cuts": cuts,
        "drift": max(abs(a - b) for a, b in zip(cuts, grid_cuts)),
        # How clean each cut is: ink in its ±0.5 window as a fraction of one line's ink.
        # On a correct segmentation this is a fraction of a percent.
        "cut_ink": [prof.at(c) / line_ink if line_ink else 0.0 for c in cuts],
        # How full the emptiest band is against the typical one. A page cut into more
        # lines than it has leaves a band with next to nothing in it.
        "band_fill": min(band_ink) / median_ink if median_ink else 0.0,
    }



def segment_valleys(boxes, expected):
    """Cut a page into `expected` lines without assuming a constant pitch.

    The body pages are set on a fixed grid and are fitted as one; the opening two pages
    are not — Al-Fatiha and the opening of Al-Baqarah are set with their own spacing, and
    forcing a uniform grid onto them leaves a band empty. Here the cuts are the deepest
    troughs in the ink profile, kept a minimum distance apart so that two of them cannot
    both land in the same gap.

    That minimum starts at half a line and is raised until every band holds ink. It has
    to be: the gap under the basmala on page 2 is wide enough to swallow two cuts at half
    a line's separation, which is exactly how `shubah/002` first came out with one band
    holding two lines and another holding none.
    """
    if not boxes:
        return [], {"reason": "no ink"}
    prof = Profile(boxes)
    span = prof.yhi - prof.ylo
    if expected < 2:
        return [(prof.ylo, prof.yhi)], {"pitch": span, "cuts": [], "cut_ink": [0.0],
                                        "drift": 0.0, "band_fill": 1.0}

    best = None
    for factor in (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9):
        min_sep = span / expected * factor
        cands = []
        y = prof.ylo + min_sep
        while y <= prof.yhi - min_sep:
            cands.append((prof.at(y), y))
            y += ROW
        cands.sort()
        cuts = []
        for _, y in cands:
            if all(abs(y - c) >= min_sep for c in cuts):
                cuts.append(y)
                if len(cuts) == expected - 1:
                    break
        if len(cuts) < expected - 1:
            continue
        cuts.sort()
        edges = [prof.ylo] + cuts + [prof.yhi]
        bands = [(edges[i], edges[i + 1]) for i in range(expected)]
        line_ink = prof.total / expected
        band_ink = [prof.ink(a, b) for a, b in bands]
        median_ink = sorted(band_ink)[len(band_ink) // 2]
        info = {
            "pitch": span / expected,
            "cuts": cuts,
            "drift": 0.0,
            "min_sep": round(min_sep, 2),
            "cut_ink": [prof.at(c) / line_ink if line_ink else 0.0 for c in cuts],
            "band_fill": min(band_ink) / median_ink if median_ink else 0.0,
        }
        if best is None or info["band_fill"] > best[1]["band_fill"]:
            best = (bands, info)
        if info["band_fill"] >= 0.15:
            return bands, info
    if best is None:
        return [], {"reason": "could not place %d cuts" % (expected - 1)}
    return best


def band_index(bands, y):
    """Band containing `y`, else the nearest one."""
    best, bestd = 0, None
    for i, (top, bottom) in enumerate(bands):
        if top <= y <= bottom:
            return i
        d = top - y if y < top else y - bottom
        if bestd is None or d < bestd:
            best, bestd = i, d
    return best



def clusters(contours, eps):
    """Group contours that are close enough to interact when rendered.

    Two contours in one `<path>` with `fill-rule="evenodd"` cancel where they overlap;
    move them into separate elements and the overlap fills instead. Contours that merely
    come within a pixel of each other don't cancel, but they do get composited separately
    once split, which changes the anti-aliased edge between them.

    Neither can happen to contours that stay together, so anything within `eps` is kept
    together and assigned to a line as a unit. On these pages that binds a word's letters
    to each other, which costs nothing — they are on the same line regardless — and binds
    the rare descender that reaches into the line below to whichever line owns most of it.

    Returns a list of member-index lists, over the given contour list.
    """
    order = sorted(range(len(contours)), key=lambda i: contours[i]["y1"])
    parent = list(range(len(contours)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        a, b = find(i), find(j)
        if a != b:
            parent[a] = b

    active = []
    for i in order:
        c = contours[i]
        active = [j for j in active if contours[j]["y2"] >= c["y1"] - eps]
        for j in active:
            o = contours[j]
            if (c["x1"] - eps <= o["x2"] and o["x1"] - eps <= c["x2"]
                    and c["y1"] - eps <= o["y2"] and o["y1"] - eps <= c["y2"]):
                union(i, j)
        active.append(i)

    groups = {}
    for i in range(len(contours)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


# ---------------------------------------------------------------------------
# Number formatting
# ---------------------------------------------------------------------------

def fmt(v):
    """Decimal that parses back to exactly the same double.

    Used only for the absolute `moveto` that replaces a relative one when a contour is
    lifted out of its original chain; everything else is copied byte-for-byte. It has to
    round-trip exactly, not merely closely: a renderer walking the original relative chain
    accumulates the same float64 sum this does, so writing that sum back out losslessly is
    what makes the split invisible. Rounding to nine decimals instead was measured to
    shift a handful of pixels per page by up to 23/1020 of full ink.
    """
    s = repr(float(v))
    if s.endswith(".0"):
        s = s[:-2]
    return "0" if s in ("-0", "") else s
