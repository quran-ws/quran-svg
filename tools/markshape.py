#!/usr/bin/env python3
"""Shared shape signature for mark outlines: normalise, resample, hash.

The art reuses one outline per mark glyph, so a translation/scale-normalised,
arc-length-resampled contour quantised to a coarse grid is a stable identity: every
fatha in the mushaf hashes to the same key. Used by cluster_marks.py to group marks
and by assign_words.py to label marks from a confirmed shape->label table.
"""

import hashlib
import math


def resample(poly, k=32):
    """K points along the polyline at uniform arc length."""
    if len(poly) < 2:
        return [poly[0]] * k if poly else []
    lens = [0.0]
    for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
        lens.append(lens[-1] + math.hypot(x2 - x1, y2 - y1))
    total = lens[-1] or 1.0
    out, j = [], 0
    for i in range(k):
        t = total * i / k
        while j < len(lens) - 2 and lens[j + 1] < t:
            j += 1
        seg = lens[j + 1] - lens[j] or 1.0
        f = (t - lens[j]) / seg
        out.append((poly[j][0] + f * (poly[j + 1][0] - poly[j][0]),
                    poly[j][1] + f * (poly[j + 1][1] - poly[j][1])))
    return out


def normalize(points):
    """Translate to centroid, scale to unit box — full precision."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    scale = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    return [((x - cx) / scale, (y - cy) / scale) for x, y in points]


def signature(points):
    """Scale/translation-normalised outline, quantised for exact-match grouping."""
    return tuple((round(x, 1), round(y, 1)) for x, y in normalize(points))


def shape_dist(a, b):
    """Mean point distance between two normalised outlines of equal length."""
    if len(a) != len(b):
        return float("inf")
    return sum(math.hypot(p[0] - q[0], p[1] - q[1]) for p, q in zip(a, b)) / len(a)


def sig_key(sig):
    """Stable string id for a signature (safe across runs and machines)."""
    return hashlib.md5(repr(sig).encode()).hexdigest()[:16]


def element_points(polys):
    """Canonical point set for one element: outer contour plus its counters.

    Holes are part of a shape's identity — the sukun ring and the damma head have
    near-identical outer ovals and are told apart only by their counters.
    """
    def span(p):
        xs = [q[0] for q in p]
        ys = [q[1] for q in p]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))

    ordered = [polys[0]] + sorted(polys[1:], key=span, reverse=True)
    pts = resample(ordered[0], 32)
    for hole in ordered[1:3]:
        pts += resample(hole, 12)
    return pts


def composite_signature(parts):
    """Signature of a multi-part mark (واقف ج = curl + dot) as one shape.

    Each part's outline is resampled, parts are concatenated in a canonical order
    (right-to-left, then top-to-bottom), and the whole point set is normalised
    together — so the same sign always hashes the same, and ج ≠ bare ح ≠ خ.
    """
    def centroid(poly):
        return (sum(p[0] for p in poly) / len(poly),
                sum(p[1] for p in poly) / len(poly))

    ordered = sorted(parts, key=lambda poly: (-round(centroid(poly)[0], 1),
                                              round(centroid(poly)[1], 1)))
    pts = []
    for poly in ordered:
        pts += resample(poly, 24) if len(poly) > 60 else list(poly)
    return signature(pts)
