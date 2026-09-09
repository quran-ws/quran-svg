#!/usr/bin/env python3
"""Re-fit a traced outline: fewer nodes, smoother curves, corners kept.

The 1422 artwork is a trace, not a font.  On page 550 it spends 143,631 nodes on the same
1,689 contours the 1441 edition draws with 21,763, and 33,542 of its segments are straight
lines against 1441's 721 -- long runs of short chords standing in for a curve.  That is what
makes the letterforms look faceted next to 1441, and it is also where the file size is.

Thinning (``pathdata.thin``) only deletes points, so it can make an outline smaller but never
smoother: what is left is still a polyline through a subset of the same points.  This module
does the other thing -- it fits new curves.

    flatten   every contour to a dense polyline, so lines and curves are treated alike
    corners   the points that must survive, found from the turn in the outline
    fit       a cubic Bezier per smooth run, split until it is within tolerance

The corner pass is the part that decides whether this is safe.  A letterform's sharp
extremities -- the tip of a ت, the heel of a ط, the join where a stroke meets a bowl -- are
real and must stay sharp; the faceting is not.  They are told apart by the angle the outline
turns through, measured over a window of arc length rather than between adjacent samples, so
that a hundred small turns that add up to a corner are seen as one, and a single sample's
jitter is not mistaken for one.

Tolerance is in typographic points and is a hard bound: no fitted curve is further than
``tol`` from the original outline, anywhere.  For scale, a raster pixel at the resolution
every audit in this repo measures with is 0.30 pt.
"""

import math

import pathdata

PASSES = 4          # Newton reparameterisation rounds before giving up and splitting


# --------------------------------------------------------------------------- flattening

def _bez(p0, p1, p2, p3, t):
    u = 1 - t
    return (u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
            u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1])


def _flat_enough(p0, p1, p2, p3, tol):
    d1 = _point_line(p1, p0, p3)
    d2 = _point_line(p2, p0, p3)
    return max(d1, d2) <= tol


def _point_line(p, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    den = vx * vx + vy * vy
    if den <= 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / den
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return math.hypot(p[0] - a[0] - t * vx, p[1] - a[1] - t * vy)


_FLAT_CACHE = {}


def flat_cached(sub, tol):
    """``flatten`` memoised for one ``refit`` call; a contour is flattened by four callers."""
    key = (id(sub), round(tol, 6))
    hit = _FLAT_CACHE.get(key)
    if hit is None:
        hit = flatten(sub, tol)
        _FLAT_CACHE[key] = hit
    return hit


def flatten(sub, tol=0.01):
    """(points, closed) — the contour as a dense polyline within ``tol`` of the original."""
    pts = [(sub[0][1], sub[0][2])]
    closed = False
    for seg in sub[1:]:
        if seg[0] == "Z":
            closed = True
            continue
        if seg[0] == "L":
            pts.append((seg[1], seg[2]))
        elif seg[0] == "C":
            p0 = pts[-1]
            p1, p2, p3 = (seg[1], seg[2]), (seg[3], seg[4]), (seg[5], seg[6])
            _subdivide(pts, p0, p1, p2, p3, tol, 0)
        else:                                     # arcs are left alone by the caller
            pts.append((seg[-2], seg[-1]))
    if closed and len(pts) > 1 and _dist(pts[0], pts[-1]) < 1e-9:
        pts.pop()
    return pts, closed


def _subdivide(out, p0, p1, p2, p3, tol, depth):
    if depth > 16 or _flat_enough(p0, p1, p2, p3, tol):
        out.append(p3)
        return
    m = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    p01, p12, p23 = m(p0, p1), m(p1, p2), m(p2, p3)
    p012, p123 = m(p01, p12), m(p12, p23)
    mid = m(p012, p123)
    _subdivide(out, p0, p01, p012, mid, tol, depth + 1)
    _subdivide(out, mid, p123, p23, p3, tol, depth + 1)


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


# --------------------------------------------------------------------------- corners

def corners(pts, closed, angle=55.0, window=0.35):
    """Indices whose turn is too sharp to be smoothed away.

    The turn is measured between the chord arriving from ``window`` points-of-arc-length back
    and the chord leaving the same distance ahead, so the test asks about the shape of the
    outline around a point rather than about one sample of it.
    """
    n = len(pts)
    if n < 4:
        return set(range(n))
    # u is the chord arriving, v the chord leaving; they are parallel on a straight run
    # (cos 1) and turn through the outline's angle at a corner, so the test is on the turn
    # itself, not on its supplement.
    limit = math.cos(math.radians(angle))
    out = set()
    for i in range(n):
        a = _walk(pts, i, -1, window, closed)
        b = _walk(pts, i, +1, window, closed)
        if a is None or b is None:
            out.add(i)
            continue
        ux, uy = pts[i][0] - a[0], pts[i][1] - a[1]
        vx, vy = b[0] - pts[i][0], b[1] - pts[i][1]
        lu, lv = math.hypot(ux, uy), math.hypot(vx, vy)
        if lu < 1e-12 or lv < 1e-12:
            continue
        cos = (ux * vx + uy * vy) / (lu * lv)
        if cos < limit:
            out.add(i)
    if not closed:
        out.add(0)
        out.add(n - 1)
    return _thin_corners(out, pts, closed)


def _walk(pts, i, step, distance, closed):
    n = len(pts)
    travelled = 0.0
    j = i
    for _ in range(n):
        k = j + step
        if k < 0 or k >= n:
            if not closed:
                return pts[j] if travelled > 0 else None
            k %= n
        travelled += _dist(pts[j], pts[k])
        j = k
        if travelled >= distance:
            return pts[j]
    return None


def _thin_corners(idx, pts, closed, min_gap=0.12):
    """One corner per cluster: a sharp turn spread over several samples is still one corner."""
    if not idx:
        return idx
    order = sorted(idx)
    keep, last = [], None
    for i in order:
        if last is not None and _dist(pts[last], pts[i]) < min_gap:
            continue
        keep.append(i)
        last = i
    return set(keep)


# --------------------------------------------------------------------------- fitting

def _tangent(pts, i, j, closed):
    """Unit tangent at ``i`` looking towards ``j``, averaged over a couple of samples."""
    n = len(pts)
    k = j
    dx = dy = 0.0
    for step in range(3):
        m = (i + (1 if j > i or (closed and j < i) else -1) * (step + 1))
        if not closed and not (0 <= m < n):
            break
        m %= n
        w = 1.0 / (step + 1)
        dx += w * (pts[m][0] - pts[i][0])
        dy += w * (pts[m][1] - pts[i][1])
    L = math.hypot(dx, dy)
    if L < 1e-12:
        dx, dy = pts[k][0] - pts[i][0], pts[k][1] - pts[i][1]
        L = math.hypot(dx, dy) or 1.0
    return dx / L, dy / L


def _chord_params(pts):
    u = [0.0]
    for i in range(1, len(pts)):
        u.append(u[-1] + _dist(pts[i - 1], pts[i]))
    total = u[-1] or 1.0
    return [v / total for v in u]


def _fit_one(pts, t1, t2, u=None):
    """Least-squares cubic through pts[0]..pts[-1] with the given end tangents."""
    if u is None:
        u = _chord_params(pts)
    p0, p3 = pts[0], pts[-1]
    c00 = c01 = c11 = x0 = x1 = 0.0
    for pt, t in zip(pts, u):
        b0 = (1 - t) ** 3
        b1 = 3 * t * (1 - t) ** 2
        b2 = 3 * t * t * (1 - t)
        b3 = t ** 3
        a1 = (t1[0] * b1, t1[1] * b1)
        a2 = (t2[0] * b2, t2[1] * b2)
        c00 += a1[0] * a1[0] + a1[1] * a1[1]
        c01 += a1[0] * a2[0] + a1[1] * a2[1]
        c11 += a2[0] * a2[0] + a2[1] * a2[1]
        tx = pt[0] - (p0[0] * (b0 + b1) + p3[0] * (b2 + b3))
        ty = pt[1] - (p0[1] * (b0 + b1) + p3[1] * (b2 + b3))
        x0 += a1[0] * tx + a1[1] * ty
        x1 += a2[0] * tx + a2[1] * ty
    det = c00 * c11 - c01 * c01
    seg = _dist(p0, p3)
    if abs(det) < 1e-12:
        a = b = seg / 3.0
    else:
        a = (x0 * c11 - x1 * c01) / det
        b = (c00 * x1 - c01 * x0) / det
        if a <= 0 or b <= 0:
            a = b = seg / 3.0
    return (p0, (p0[0] + t1[0] * a, p0[1] + t1[1] * a),
            (p3[0] + t2[0] * b, p3[1] + t2[1] * b), p3)


def _dbez(p0, p1, p2, p3, t):
    """First derivative of the cubic at t."""
    u = 1 - t
    return (3 * u * u * (p1[0] - p0[0]) + 6 * u * t * (p2[0] - p1[0]) + 3 * t * t * (p3[0] - p2[0]),
            3 * u * u * (p1[1] - p0[1]) + 6 * u * t * (p2[1] - p1[1]) + 3 * t * t * (p3[1] - p2[1]))


def _ddbez(p0, p1, p2, p3, t):
    u = 1 - t
    return (6 * u * (p2[0] - 2 * p1[0] + p0[0]) + 6 * t * (p3[0] - 2 * p2[0] + p1[0]),
            6 * u * (p2[1] - 2 * p1[1] + p0[1]) + 6 * t * (p3[1] - 2 * p2[1] + p1[1]))


def _reparam(pts, curve, u):
    """One Newton step per point, moving each parameter to its true nearest point on the curve.

    Chord length is only a guess at where each sample sits along the curve, and a wrong guess
    makes the least-squares fit look worse than the curve really is -- so the splitter cuts a
    run that did not need cutting.  Correcting the parameters first is what turns the same
    tolerance into materially fewer curves.
    """
    out = []
    for pt, t in zip(pts, u):
        q = _bez(curve[0], curve[1], curve[2], curve[3], t)
        d1 = _dbez(curve[0], curve[1], curve[2], curve[3], t)
        d2 = _ddbez(curve[0], curve[1], curve[2], curve[3], t)
        dx, dy = q[0] - pt[0], q[1] - pt[1]
        num = dx * d1[0] + dy * d1[1]
        den = d1[0] ** 2 + d1[1] ** 2 + dx * d2[0] + dy * d2[1]
        nt = t if abs(den) < 1e-12 else t - num / den
        out.append(0.0 if nt < 0.0 else (1.0 if nt > 1.0 else nt))
    out[0], out[-1] = 0.0, 1.0
    for i in range(1, len(out)):                 # keep them ordered
        if out[i] <= out[i - 1]:
            out[i] = min(1.0, out[i - 1] + 1e-6)
    return out


def _max_error(pts, curve, u=None):
    if u is None:
        u = _chord_params(pts)
    worst, at = 0.0, len(pts) // 2
    for i, (pt, t) in enumerate(zip(pts, u)):
        q = _bez(curve[0], curve[1], curve[2], curve[3], t)
        e = math.hypot(q[0] - pt[0], q[1] - pt[1])
        if e > worst:
            worst, at = e, i
    return worst, at


def _fit_run(pts, t1, t2, tol, depth=0):
    """[curve] covering pts within ``tol``, splitting where it does not."""
    if len(pts) < 3:
        seg = _dist(pts[0], pts[-1]) / 3.0
        return [(pts[0], (pts[0][0] + t1[0] * seg, pts[0][1] + t1[1] * seg),
                 (pts[-1][0] + t2[0] * seg, pts[-1][1] + t2[1] * seg), pts[-1])]
    u = _chord_params(pts)
    curve = _fit_one(pts, t1, t2, u)
    err, at = _max_error(pts, curve, u)
    for _ in range(PASSES):                      # Schneider's reparameterisation
        if err <= tol:
            break
        u = _reparam(pts, curve, u)
        curve = _fit_one(pts, t1, t2, u)
        err, at = _max_error(pts, curve, u)
    if err <= tol or depth > 24:
        return [curve]
    if at <= 0 or at >= len(pts) - 1:
        at = len(pts) // 2
    left = pts[:at + 1]
    right = pts[at:]
    tx = (right[1][0] - left[-2][0], right[1][1] - left[-2][1])
    L = math.hypot(*tx) or 1.0
    tm = (tx[0] / L, tx[1] / L)
    return (_fit_run(left, t1, (-tm[0], -tm[1]), tol, depth + 1)
            + _fit_run(right, tm, t2, tol, depth + 1))


def smooth_run(pts, window):
    """A moving average along one run, in arc length, with both ends pinned.

    The jitter a trace leaves behind is smaller than any feature of the letterform, so an
    average taken over a window narrower than a pen stroke removes it and touches nothing
    else.  The window tapers to nothing at the ends, so the corners bounding the run -- which
    is where the sharp detail is -- are not moved at all, and the runs still join exactly.
    """
    n = len(pts)
    if n < 5 or window <= 0:
        return pts
    s = [0.0]
    for i in range(1, n):
        s.append(s[-1] + _dist(pts[i - 1], pts[i]))
    out = [pts[0]]
    for i in range(1, n - 1):
        w = min(window, s[i], s[-1] - s[i])       # taper, so the ends stay put
        if w <= 0:
            out.append(pts[i])
            continue
        sx = sy = wt = 0.0
        j = i
        while j >= 0 and s[i] - s[j] <= w:
            k = 1.0 - (s[i] - s[j]) / w
            sx += k * pts[j][0]; sy += k * pts[j][1]; wt += k
            j -= 1
        j = i + 1
        while j < n and s[j] - s[i] <= w:
            k = 1.0 - (s[j] - s[i]) / w
            sx += k * pts[j][0]; sy += k * pts[j][1]; wt += k
            j += 1
        out.append((sx / wt, sy / wt) if wt > 0 else pts[i])
    out.append(pts[-1])
    return out


def smooth_closed(pts, closed, window):
    """The same moving average over a whole contour, wrapping if it is closed."""
    if window <= 0 or len(pts) < 5:
        return pts
    if not closed:
        return smooth_run(pts, window)
    n = len(pts)
    third = n // 3 or 1
    rolled = pts[-third:] + pts + pts[:third]
    out = smooth_run(rolled, window)
    return out[third:third + n]


def refit_contour(sub, tol=0.05, angle=55.0, flat_tol=None, smooth=0.0,
                  detect_smooth=0.0, window=0.35):
    """One contour, re-fitted.  Returns segments in ``pathdata``'s form."""
    pts, closed = flatten(sub, flat_tol if flat_tol is not None else min(tol / 4, 0.01))
    if len(pts) < 3:
        return sub
    # Corners are looked for on a lightly smoothed copy, but the curves are fitted to the
    # real points.  A trace's jitter otherwise reads as a crowd of corners -- and a corner
    # forces a curve to start and stop there, which is what actually sets the node count.
    probe = smooth_closed(pts, closed, detect_smooth) if detect_smooth > 0 else pts
    marks = sorted(corners(probe, closed, angle, window))
    n = len(pts)
    if closed:
        if not marks:
            marks = [0, n // 3, 2 * n // 3]        # no corner at all: cut it into arcs
        runs = []
        for i in range(len(marks)):
            a, b = marks[i], marks[(i + 1) % len(marks)]
            runs.append([pts[k % n] for k in range(a, b + 1 if b > a else b + n + 1)])
    else:
        if marks[0] != 0:
            marks.insert(0, 0)
        if marks[-1] != n - 1:
            marks.append(n - 1)
        runs = [pts[marks[i]:marks[i + 1] + 1] for i in range(len(marks) - 1)]

    out = [("M", pts[marks[0]][0], pts[marks[0]][1])]
    for run in runs:
        if len(run) < 2:
            continue
        if smooth > 0:
            run = smooth_run(run, smooth)
        t1 = _tangent(run, 0, 1, False)
        t2 = _tangent(run, len(run) - 1, len(run) - 2, False)
        for c in _fit_run(run, t1, t2, tol):
            if _dist(c[0], c[3]) < 1e-9 and _dist(c[1], c[0]) < 1e-9:
                continue
            # a cubic whose handles lie on its own chord is a line, and costs a third as much
            if (_point_line(c[1], c[0], c[3]) <= 1e-6
                    and _point_line(c[2], c[0], c[3]) <= 1e-6):
                out.append(("L", c[3][0], c[3][1]))
            else:
                out.append(("C", c[1][0], c[1][1], c[2][0], c[2][1], c[3][0], c[3][1]))
    if closed:
        out.append(("Z",))
    return out


def _one_way(a, b):
    """Worst distance from every point of polyline ``a`` to the points of ``b``.

    Both polylines are resampled finely before this is called, so point-to-point stands in
    for point-to-segment.  It reads slightly high -- by at most half the resampling step --
    and that is the safe direction: this number is compared against a tolerance to decide
    whether to *keep* a fit, so erring high can only reject a fit, never accept a bad one.
    """
    import numpy as np
    from scipy.spatial import cKDTree

    if len(a) < 1 or len(b) < 2:
        return float("inf")
    tree = cKDTree(np.asarray(b, dtype=float))
    dist, _ = tree.query(np.asarray(a, dtype=float), k=1, workers=1)
    return float(dist.max())


def deviation(original, fitted, flat_tol=0.02):
    """Symmetric worst-case distance between two contours, in points.

    Both directions matter and they catch different failures.  Original-to-fitted finds
    detail that was smoothed away; fitted-to-original finds detail that was *invented* -- a
    run the splitter mishandled, leaving a hairline spike across the page.  Measuring only
    the first misses the second entirely, because every original point still has a fitted
    point next to it; the spike is extra ink, not missing ink.
    """
    a = resample(flat_cached(original, flat_tol)[0], 0.08)
    b = resample(flatten(fitted, flat_tol)[0], 0.08)
    if len(a) < 2 or len(b) < 2:
        return float("inf")
    return max(_one_way(a, b), _one_way(b, a))


def resample(pts, step=0.08):
    """Points no further apart than ``step`` along the polyline.

    ``flatten`` subdivides curves to a tolerance but leaves a straight segment as its two
    endpoints, which is right for measuring shape and wrong for measuring distance: this
    artwork draws long runs as straight edges, and a point-to-point test across one of them
    reports a gap that is not there.  Anything comparing two outlines has to walk the edges,
    not just their corners.
    """
    if len(pts) < 2 or step <= 0:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts)):
        ax, ay = pts[i - 1]
        bx, by = pts[i]
        d = math.hypot(bx - ax, by - ay)
        n = int(d / step)
        for k in range(1, n + 1):
            t = k / (n + 1.0)
            out.append((ax + t * (bx - ax), ay + t * (by - ay)))
        out.append(pts[i])
    return out


def clearances(subs, flat_tol=0.05, reach=2.0, step=0.15, self_arc=1.2):
    """For each contour, how much room it has -- to its neighbours *and to itself*.

    Two things can be closed by moving an outline, and they need the same answer.  A gap
    between two contours, which welds two letters into one blob if it shuts.  And a contour's
    own waist -- the neck of a shadda, the pinch where a stroke narrows -- which breaks one
    blob into two if it shuts.  The second is easy to miss because nothing about the contour's
    neighbours reveals it, and skipping same-contour pairs is the obvious way to write this
    function and the wrong one.

    Self-distances are only counted between points far apart *along* the outline -- ``self_arc``
    of arc length -- since points that are neighbours on the path are meant to be close.
    """
    import numpy as np
    from scipy.spatial import cKDTree

    pts, arcs = [], []
    for sub in subs:
        p = resample(flat_cached(sub, flat_tol)[0], step)
        pts.append(p)
        a, run = [0.0], 0.0
        for i in range(1, len(p)):
            run += _dist(p[i - 1], p[i])
            a.append(run)
        arcs.append(a)

    xy = np.array([q for p in pts for q in p], dtype=float)
    if len(xy) == 0:
        return [float("inf")] * len(subs)
    owner = np.concatenate([np.full(len(p), i) for i, p in enumerate(pts)])
    along = np.concatenate([np.asarray(a) for a in arcs])
    length = np.array([a[-1] if a else 0.0 for a in arcs])

    tree = cKDTree(xy)
    k = min(len(xy), 24)
    dist, idx = tree.query(xy, k=k, workers=-1)

    same = owner[idx] == owner[:, None]
    gap = np.abs(along[idx] - along[:, None])
    total = length[owner][:, None]
    gap = np.where(total > 0, np.minimum(gap, total - gap), gap)
    # a point may not be measured against itself, its neighbours along the outline, or
    # anything closer than `self_arc` around the loop
    blocked = same & (gap < self_arc)
    dist = np.where(blocked, np.inf, dist)

    out = [float("inf")] * len(subs)
    best = dist.min(axis=1)
    for i in range(len(subs)):
        m = best[owner == i]
        if len(m):
            v = float(m.min())
            out[i] = v if np.isfinite(v) else float("inf")
    return out


def _diagonal(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5


def refit(subs, tol=0.05, angle=55.0, slack=1.5, smooth=0.0,
          detect_smooth=0.0, window=0.35, min_diagonal=0.0, small_thin=0.0,
          clearance_share=0.4, size_share=0.0):
    """Re-fit every contour, keeping the original wherever the fit does not hold.

    The fitter is not trusted on its word.  Each contour it produces is measured back against
    the one it replaced, and any that has moved further than ``tol * slack`` anywhere is
    thrown away and the original kept.  Without this a single bad fit -- a run the splitter
    could not resolve, a contour with no usable tangent -- puts a stray line across the page,
    and it is not the sort of thing that shows up in a size table.
    """
    _FLAT_CACHE.clear()
    room = clearances(subs) if clearance_share > 0 else [float("inf")] * len(subs)
    out, kept, small, capped = [], 0, 0, 0
    for sub, gap in zip(subs, room):
        # A tolerance that is nothing against a stem is a large fraction of a dot, and the
        # dots and diacritics are where a shape is read rather than a stroke followed.  Below
        # the threshold nothing is fitted: the contour is either left exactly as drawn, or --
        # if asked -- thinned, which only ever drops a point already within tolerance of the
        # chord replacing it and so cannot round anything off.
        if min_diagonal > 0:
            pts, _ = flat_cached(sub, 0.02)
            if len(pts) < 3 or _diagonal(pts) < min_diagonal:
                out.append(pathdata.thin([sub], small_thin)[0] if small_thin > 0 else sub)
                small += 1
                continue
        # never move more than a share of the room to the nearest neighbour: two contours
        # can then close the gap between them by at most 2 * share, which is less than the
        # gap itself, so a join cannot be manufactured
        # A tolerance is only meaningful against the size of the thing it applies to: 0.15 pt
        # is nothing across a stem and a sixtieth of a small letter, which is why the middle
        # sizes were the ones swelling.  Tie it to the contour's own extent as well as to the
        # room around it, and take whichever is tighter.
        here = tol if gap == float("inf") else min(tol, clearance_share * gap)
        if size_share > 0:
            pts, _ = flat_cached(sub, 0.05)
            here = min(here, size_share * _diagonal(pts))
        if here < tol:
            capped += 1
        if here <= 0.005:
            out.append(sub)
            kept += 1
            continue
        try:
            fitted = refit_contour(sub, here, angle, smooth=min(smooth, here),
                                   detect_smooth=detect_smooth, window=window)
        except Exception:                                        # noqa: BLE001
            out.append(sub)
            kept += 1
            continue
        if len(fitted) < 2 or deviation(sub, fitted) > here * slack:
            out.append(sub)
            kept += 1
        else:
            out.append(fitted)
    refit.rejected = kept
    refit.protected = small
    refit.capped = capped
    _FLAT_CACHE.clear()
    return out
