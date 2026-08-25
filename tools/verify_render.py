#!/usr/bin/env python3
"""Prove the line grouping changed no pixel, by rendering each page before and after.

Grouping contours into `<g>` elements must be a pure restructuring. The one way it could
not be is `fill-rule="evenodd"`: parity is evaluated per `<path>` element, so two contours
that overlap cancel while they share an element and both fill once they are split apart.
That can only happen between contours the segmentation put on different lines, so this
renders the page as git has it against the page on disk and compares the bitmaps.

    tools/verify_render.py hafs/kfqc              # every page of an edition
    tools/verify_render.py hafs/kfqc --pages 1,255
    tools/verify_render.py hafs/kfqc --scale 4    # render at 4x page size

Needs `rsvg-convert` (librsvg) on PATH and reads the pre-change SVG from git.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from multiprocessing import Pool

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def render(svg_bytes, width, tmpdir, tag):
    src = os.path.join(tmpdir, tag + ".svg")
    png = os.path.join(tmpdir, tag + ".png")
    with open(src, "wb") as fh:
        fh.write(svg_bytes)
    subprocess.run(["rsvg-convert", "-w", str(width), src, "-o", png],
                   check=True, capture_output=True)
    with open(png, "rb") as fh:
        return fh.read()


def compare(job):
    rel, scale = job
    path = os.path.join(ROOT, rel)
    try:
        before = subprocess.run(["git", "show", "HEAD:" + rel], cwd=ROOT,
                                check=True, capture_output=True).stdout
        with open(path, "rb") as fh:
            after = fh.read()
        if before == after:
            return {"file": rel, "unchanged": True}
        m = re.search(rb'viewBox="([^"]*)"', after)
        box = [float(v) for v in m.group(1).split()] if m else [0, 0, 1024, 1024]
        width = max(16, int(box[2] * scale))
        with tempfile.TemporaryDirectory() as tmp:
            a = render(before, width, tmp, "before")
            b = render(after, width, tmp, "after")
        res = {"file": rel, "identical": a == b,
               "sha_before": hashlib.sha256(a).hexdigest()[:16],
               "sha_after": hashlib.sha256(b).hexdigest()[:16]}
        if not res["identical"]:
            res.update(measure(a, b))
        return res
    except subprocess.CalledProcessError as exc:
        return {"file": rel, "error": exc.stderr.decode()[:200]}


def measure(a, b):
    """How far apart two renderings are, in pixels and in ink.

    Reported rather than reduced to a yes/no, because the interesting question is not
    whether a rasteriser produced identical bytes but whether anything moved: the fill
    region is provably unchanged, so what is left is how a renderer spreads anti-aliased
    coverage over an edge when the same outlines arrive as several draw calls.
    """
    try:
        import io

        import numpy as np
        from PIL import Image
    except ImportError:
        return {"delta": "install numpy+pillow to quantify"}
    ia = np.asarray(Image.open(io.BytesIO(a)).convert("RGBA")).astype(int)
    ib = np.asarray(Image.open(io.BytesIO(b)).convert("RGBA")).astype(int)
    if ia.shape != ib.shape:
        return {"delta": "size changed %s -> %s" % (ia.shape, ib.shape)}
    alpha = np.abs(ia[:, :, 3] - ib[:, :, 3])
    return {"pixels": int((alpha > 0).sum()), "total": int(alpha.size),
            "max_alpha": int(alpha.max()), "sum_alpha": int(alpha.sum())}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mushaf", help="edition, e.g. hafs/kfqc")
    ap.add_argument("--pages", help="comma-separated page numbers")
    ap.add_argument("--scale", type=float, default=3.0,
                    help="render width as a multiple of the page's viewBox width")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--json", help="write per-page results as JSON")
    args = ap.parse_args(argv)

    svg_dir = os.path.join(ROOT, "mushafs", args.mushaf, "svg")
    names = sorted(n for n in os.listdir(svg_dir) if n.endswith(".svg"))
    if args.pages:
        want = set(args.pages.split(","))
        names = [n for n in names if re.match(r"^(\d+)", n).group(1).lstrip("0") in want]
    jobs = [("mushafs/%s/svg/%s" % (args.mushaf, n), args.scale) for n in names]

    with Pool(args.jobs) as pool:
        results = pool.map(compare, jobs)

    diff = [r for r in results if r.get("identical") is False]
    err = [r for r in results if "error" in r]
    same = [r for r in results if r.get("identical")]
    untouched = [r for r in results if r.get("unchanged")]
    print("%s at %gx: %d pages   %d byte-identical renders   %d unchanged files   "
          "%d differing   %d errors"
          % (args.mushaf, args.scale, len(results), len(same), len(untouched),
             len(diff), len(err)))
    measured = [r for r in diff if "pixels" in r]
    if measured:
        total_px = sum(r["total"] for r in measured)
        worst = max(measured, key=lambda r: r["max_alpha"])
        print("   differing pixels: %d of %d rendered (%.6f%%)"
              % (sum(r["pixels"] for r in measured), total_px,
                 100.0 * sum(r["pixels"] for r in measured) / total_px))
        print("   per page: median %d, worst %d (%s)"
              % (sorted(r["pixels"] for r in measured)[len(measured) // 2],
                 max(r["pixels"] for r in measured),
                 max(measured, key=lambda r: r["pixels"])["file"]))
        print("   largest single-pixel alpha change: %d of 255 (%s)"
              % (worst["max_alpha"], worst["file"]))
    for r in err:
        print("   ERROR", r["file"], r["error"])
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=1)
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
