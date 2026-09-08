#!/usr/bin/env python3
"""Parse, thin and re-emit an SVG ``d``.

The 1422 artwork is not a font: Illustrator converted the text to outlines, and the result
is sampled far more finely than it needs to be.  A page carries about 117,000 segments
against roughly 35,000 for the font-based 1441 edition, and half of them are shorter than
0.2 typographic points -- a fifth of a raster pixel at the resolution every audit in this
repo measures with.

So the thinning here is not a redesign of the curve.  It drops a point only when leaving it
out moves the outline by less than ``tol`` points, which is checked against the chord it
would sit on, never accumulated blindly along a run.  Nothing is refitted and no curve is
replaced by a different curve: a cubic becomes a line only when its own control points
already lie on its chord.
"""

import re

_TOK = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])|(-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")
_NARG = dict(M=2, L=2, H=1, V=1, C=6, S=4, Q=4, T=2, A=7, Z=0)


def parse(d):
    """``d`` as a list of subpaths, each a list of absolute segments.

    A segment is ``("M", x, y)``, ``("L", x, y)``, ``("C", x1, y1, x2, y2, x, y)`` or
    ``("Z",)``.  Quadratics are raised to cubics exactly; arcs are kept verbatim as
    ``("A", ...)`` and never touched by the thinning.
    """
    toks = [(m.group(1), m.group(2)) for m in _TOK.finditer(d)]
    subs, cur = [], None
    x = y = sx = sy = 0.0
    px = py = None          # previous control point, for S and T
    cmd = None
    i = 0
    while i < len(toks):
        if toks[i][0]:
            cmd = toks[i][0]
            i += 1
            if cmd in "Zz":
                if cur:
                    cur.append(("Z",))
                    x, y = sx, sy
                px = py = None
                continue
        if cmd is None:
            break
        n = _NARG[cmd.upper()]
        a = []
        while len(a) < n and i < len(toks) and toks[i][1] is not None:
            a.append(float(toks[i][1]))
            i += 1
        if len(a) < n:
            break
        rel, c = cmd.islower(), cmd.upper()
        if c == "M":
            x, y = (x + a[0], y + a[1]) if rel else (a[0], a[1])
            sx, sy = x, y
            cur = [("M", x, y)]
            subs.append(cur)
            cmd = "l" if rel else "L"        # further pairs after an M are implicit L
            px = py = None
            continue
        if cur is None:                       # a stray segment before any M
            cur = [("M", x, y)]
            subs.append(cur)
        if c == "L":
            x, y = (x + a[0], y + a[1]) if rel else (a[0], a[1])
            cur.append(("L", x, y))
            px = py = None
        elif c == "H":
            x = x + a[0] if rel else a[0]
            cur.append(("L", x, y))
            px = py = None
        elif c == "V":
            y = y + a[0] if rel else a[0]
            cur.append(("L", x, y))
            px = py = None
        elif c == "C":
            p = [(x + a[k] if rel else a[k], y + a[k + 1] if rel else a[k + 1])
                 for k in (0, 2, 4)]
            cur.append(("C", p[0][0], p[0][1], p[1][0], p[1][1], p[2][0], p[2][1]))
            px, py = p[1]
            x, y = p[2]
        elif c == "S":
            c1 = (2 * x - px, 2 * y - py) if px is not None else (x, y)
            p = [(x + a[k] if rel else a[k], y + a[k + 1] if rel else a[k + 1])
                 for k in (0, 2)]
            cur.append(("C", c1[0], c1[1], p[0][0], p[0][1], p[1][0], p[1][1]))
            px, py = p[0]
            x, y = p[1]
        elif c in "QT":
            if c == "Q":
                q = (x + a[0] if rel else a[0], y + a[1] if rel else a[1])
                e = (x + a[2] if rel else a[2], y + a[3] if rel else a[3])
            else:
                q = (2 * x - px, 2 * y - py) if px is not None else (x, y)
                e = (x + a[0] if rel else a[0], y + a[1] if rel else a[1])
            cur.append(("C", x + 2.0 / 3 * (q[0] - x), y + 2.0 / 3 * (q[1] - y),
                        e[0] + 2.0 / 3 * (q[0] - e[0]), e[1] + 2.0 / 3 * (q[1] - e[1]),
                        e[0], e[1]))
            px, py = q
            x, y = e
        elif c == "A":
            e = (x + a[5] if rel else a[5], y + a[6] if rel else a[6])
            cur.append(("A", a[0], a[1], a[2], a[3], a[4], e[0], e[1]))
            px = py = None
            x, y = e
    return subs


def _dist(px, py, ax, ay, bx, by):
    """Distance from P to the segment AB."""
    vx, vy = bx - ax, by - ay
    den = vx * vx + vy * vy
    if den <= 0.0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = ((px - ax) * vx + (py - ay) * vy) / den
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return ((px - ax - t * vx) ** 2 + (py - ay - t * vy) ** 2) ** 0.5


def _flat_cubic(seg, x0, y0, tol):
    """True when a cubic's own control points sit on its chord within ``tol``."""
    _, x1, y1, x2, y2, x3, y3 = seg
    return (_dist(x1, y1, x0, y0, x3, y3) <= tol
            and _dist(x2, y2, x0, y0, x3, y3) <= tol)


def thin(subs, tol=0.05):
    """Drop points whose removal moves the outline by less than ``tol``.

    Two passes, both local and both bounded by ``tol`` against the chord that would replace
    the dropped point -- a straight cubic becomes a line, and a run of near-collinear lines
    becomes one line only while every point it swallows stays within the tolerance of the
    single chord that replaces them.
    """
    out = []
    for sub in subs:
        segs = [sub[0]]
        x0, y0 = sub[0][1], sub[0][2]
        for seg in sub[1:]:
            if seg[0] == "C" and _flat_cubic(seg, x0, y0, tol):
                seg = ("L", seg[5], seg[6])
            segs.append(seg)
            if seg[0] in ("L", "C"):
                x0, y0 = seg[-2], seg[-1]
            elif seg[0] == "A":
                x0, y0 = seg[-2], seg[-1]
        # collapse runs of lines
        merged = [segs[0]]
        ax, ay = segs[0][1], segs[0][2]
        run = []                                   # points swallowed by the pending chord
        for seg in segs[1:]:
            if seg[0] == "L":
                bx, by = seg[1], seg[2]
                if run and all(_dist(px, py, ax, ay, bx, by) <= tol for px, py in run):
                    run.append((bx, by))
                    merged[-1] = ("L", bx, by)
                    continue
                if merged[-1][0] == "L" and not run:
                    run = [(merged[-1][1], merged[-1][2])]
                    if _dist(run[0][0], run[0][1], ax, ay, bx, by) <= tol:
                        run.append((bx, by))
                        merged[-1] = ("L", bx, by)
                        continue
                    run = []
                ax, ay = merged[-1][-2], merged[-1][-1]
                run = []
                merged.append(seg)
                continue
            run = []
            merged.append(seg)
            if seg[0] in ("C", "A"):
                ax, ay = seg[-2], seg[-1]
        out.append(merged)
    return out


def _fmt(v, nd):
    s = "%.*f" % (nd, v)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    if s.startswith("0.") and len(s) > 2:
        s = s[1:]
    elif s.startswith("-0.") and len(s) > 3:
        s = "-" + s[2:]
    return s


def emit(subs, dx=0.0, dy=0.0, nd=2):
    """The path back as relative commands, translated by (dx, dy) and rounded to ``nd``.

    Every coordinate is written relative to the *rounded* pen position, so the rounding
    error of one point is never carried into the next.
    """
    out = []
    cx = cy = 0.0
    grid = 10.0 ** nd
    snap = lambda v: round(v * grid) / grid
    for sub in subs:
        last = None
        start = None
        for seg in sub:
            k = seg[0]
            if k == "Z":
                out.append("z")
                last = "z"
                if start is not None:        # `z` returns the pen to the subpath's start
                    cx, cy = start
                continue
            if k == "A":
                x, y = snap(seg[6] + dx), snap(seg[7] + dy)
                out.append("a" + " ".join(_fmt(v, nd) for v in seg[1:6])
                           + " " + _fmt(x - cx, nd) + "," + _fmt(y - cy, nd))
                cx, cy = x, y
                last = "a"
                continue
            pts = [(snap(seg[i] + dx), snap(seg[i + 1] + dy))
                   for i in range(1, len(seg), 2)]
            code = {"M": "m", "L": "l", "C": "c"}[k]
            body = " ".join("%s,%s" % (_fmt(px - cx, nd), _fmt(py - cy, nd))
                            for px, py in pts)
            out.append((" " if code == last and code != "m" else code) + body)
            cx, cy = pts[-1]
            if k == "M":
                start = (cx, cy)
            last = code
    return "".join(out)


def optimise(d, tol=0.0, nd=3, dx=0.0, dy=0.0):
    """Re-encode ``d``; with ``tol`` 0 (the default) the geometry is carried across exactly."""
    return emit(thin(parse(d), tol) if tol else parse(d), dx, dy, nd)
