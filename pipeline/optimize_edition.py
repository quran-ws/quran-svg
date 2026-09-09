#!/usr/bin/env python3
"""Publish a re-fitted copy of an edition alongside the exact one.

The 1422 artwork is a trace, and it is described far more finely than it is drawn: about
117,000 segments a page, half of them shorter than a fifth of a raster pixel.  This writes a
second edition in which every contour has been re-fitted -- fewer nodes, smoother curves,
same letterforms -- and leaves the original untouched.

What changes and what does not:

* the ``d`` of each contour in ``<g id="content">``            re-fitted
* the ayah polygons, the medallions, the line grouping,
  ``json/``, ``lines/``, ``surah.json``, ``markers.json``      copied verbatim

The ayah layer is copied rather than re-derived on purpose.  Its geometry comes from the
page's ink, the ink moves by less than a fifth of a raster pixel, and re-deriving it would
introduce differences between the two editions that mean nothing.  Whether that was fair is
then checked, not assumed: ``tools/audit_ayah_polygons.py`` re-derives every polygon from the
new edition's own ink and compares, so if the re-fit had moved anything enough to matter, it
would say so.

    python3 pipeline/optimize_edition.py --from hafs/kfqc-1422 --to hafs/kfqc-1422-optimized
    python3 pipeline/optimize_edition.py --pages 3,550 --dry-run
"""

import argparse
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import brotli                                                    # noqa: E402
import curvefit                                                  # noqa: E402
import editions                                                  # noqa: E402
import pathdata                                                  # noqa: E402

BROTLI_QUALITY = 11
_D = re.compile(r'<path d="([^"]*)"')
_VIEWBOX = re.compile(r'viewBox="[^"]*"')

# The settings this edition is built with.  Tolerance is in typographic points; a raster pixel
# at the resolution every audit here measures with is 0.30 pt.
SETTINGS = dict(
    tol=0.15,             # no fitted curve is further than this from the outline it replaces
    angle=70,             # a turn sharper than this is a corner and is kept
    window=0.25,          # arc length the turn is measured over
    detect_smooth=0.20,   # corners are looked for on a copy smoothed this much
    smooth=0.15,          # smoothing between corners, tapering to nothing at each end
    min_diagonal=6.0,     # contours smaller than this across are not fitted at all
    small_thin=0.02,      # ... only thinned this far, which cannot round a corner
    clearance_share=0.4,  # never move more than this share of the room to the nearest contour
    size_share=0.008,     # ... nor more than this share of the contour's own extent
)


def optimise(text):
    """The page with every content contour re-fitted; everything else byte for byte."""
    cut = text.find('<g id="content"')
    if cut < 0:
        return text, 0, 0
    head, body = text[:cut], text[cut:]
    before = after = 0

    def one(m):
        nonlocal before, after
        subs = pathdata.parse(m.group(1))
        fitted = curvefit.refit(subs, **SETTINGS)
        before += sum(len(s) for s in subs)
        after += sum(len(s) for s in fitted)
        return '<path d="%s"' % re.sub(r"[ ,](-)", r"\1", pathdata.emit(fitted, nd=3))
    return head + _D.sub(one, body), before, after


def variants_of(edition, page):
    svg_dir = os.path.join(editions.base(edition), "svg")
    return sorted(f[:-4] for f in os.listdir(svg_dir)
                  if re.fullmatch(r"%03d-surah\d+\.svg" % page, f))


def _job(args):
    src, dst, page, dry = args
    try:
        with open(editions.page_path(src, page), encoding="utf-8") as fh:
            text = fh.read()
        new, before, after = optimise(text)
        written = [("svg", "%03d" % page, new)]
        # A surah crop is the same page under a shorter viewBox, so it inherits the work
        for stem in variants_of(src, page):
            with open(editions.page_path(src, page, "svg", "svg", stem), encoding="utf-8") as fh:
                vb = _VIEWBOX.search(fh.read(600)).group(0)
            written.append(("svg", stem, _VIEWBOX.sub(vb, new, count=1)))
        if not dry:
            for kind, stem, body in written:
                with open(editions.page_path(dst, page, kind, "svg", stem), "w",
                          encoding="utf-8") as fh:
                    fh.write(body)
                with open(editions.page_path(dst, page, "svg-br", "svg.br", stem), "wb") as fh:
                    fh.write(brotli.compress(body.encode("utf-8"), quality=BROTLI_QUALITY))
            for stem in ["%03d" % page] + variants_of(src, page):
                for kind, ext in (("json", "json"), ("lines", "json")):
                    a = editions.page_path(src, page, kind, ext, stem)
                    if os.path.exists(a):
                        shutil.copyfile(a, editions.page_path(dst, page, kind, ext, stem))
        return page, before, after, len(new), None
    except Exception as exc:                                     # noqa: BLE001
        return page, 0, 0, 0, repr(exc)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="src", default="hafs/kfqc-1422")
    ap.add_argument("--to", dest="dst", default="hafs/kfqc-1422-optimized")
    ap.add_argument("--pages", default="1-604")
    ap.add_argument("--workers", type=int, default=min(7, os.cpu_count() or 4))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    pages = []
    for part in args.pages.split(","):
        if "-" in part.strip("-"):
            a, b = part.split("-")
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))

    for kind in ("svg", "svg-br", "json", "lines"):
        os.makedirs(os.path.join(editions.base(args.dst), kind), exist_ok=True)
    if not args.dry_run:
        for name in ("surah.json", "markers.json"):
            a = editions.index_path(args.src, name)
            if os.path.exists(a):
                shutil.copyfile(a, editions.index_path(args.dst, name))

    from multiprocessing import Pool
    before = after = total = 0
    failed = []
    with Pool(args.workers) as pool:
        for page, b, a, size, why in pool.imap_unordered(
                _job, [(args.src, args.dst, p, args.dry_run) for p in pages], chunksize=1):
            if why:
                failed.append((page, why))
                continue
            before += b
            after += a
            total += size
    done = len(pages) - len(failed)
    print("%s -> %s" % (args.src, args.dst))
    print("  %d pages, %.2f GB, nodes %d -> %d (%.1f%%)"
          % (done, total / 1e9, before, after, 100.0 * after / max(1, before)))
    for page, why in sorted(failed)[:20]:
        print("   FAILED p%-3d %s" % (page, why))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
