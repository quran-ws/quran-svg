#!/usr/bin/env python3
"""Build the refit variants of a few pages, cut into single lines, for side-by-side review.

Judging a re-fit from a whole page is hopeless -- the differences are a fraction of a stroke
width -- and judging it from one zoomed crop proves nothing about the rest of the page.  So
this writes every page as fifteen separate one-line SVGs per variant, each holding only that
line's contours and cropped to its band, which is small enough to view at real magnification
and complete enough to be worth trusting.

Output goes to ``.work/trace/`` (untracked) and is what ``demo/trace.html`` reads:

    .work/trace/index.json
    .work/trace/550/line07-E3.svg

Variants are the settings compared in the size investigation; ``shipped`` is the page exactly
as it is in ``mushafs/``.

    python3 pipeline/make_trace_samples.py --pages 3,106,255,550,604
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import curvefit                                                  # noqa: E402
import editions                                                  # noqa: E402
import pathdata                                                  # noqa: E402

OUT = os.path.join(ROOT, ".work", "trace")
EDITION = "hafs/kfqc-1422"

VARIANTS = {
    "shipped": None,
    "E1": dict(tol=0.10, angle=60, window=0.25, detect_smooth=0.20, smooth=0.10),
    "E3": dict(tol=0.15, angle=70, window=0.25, detect_smooth=0.20, smooth=0.15),
    "E4": dict(tol=0.20, angle=70, window=0.25, detect_smooth=0.20, smooth=0.20),
    # the same as E3, with the three guards: small elements left alone, no contour moved
    # into a neighbour, and the tolerance tied to each contour's own size
    "E3s": dict(tol=0.15, angle=70, window=0.25, detect_smooth=0.20, smooth=0.15,
                min_diagonal=6.0, small_thin=0.02, clearance_share=0.4, size_share=0.008),
}

_D = re.compile(r'<path d="([^"]*)"')
_LINE = re.compile(r'<g class="line" data-line="(\d+)">')


def pack(d):
    return re.sub(r"[ ,](-)", r"\1", d)


def refit_page(text, cfg):
    """The page with every contour re-fitted, or unchanged when ``cfg`` is None."""
    if cfg is None:
        return text
    cut = text.find('<g id="content"')
    head, body = text[:cut], text[cut:]

    def one(m):
        subs = pathdata.parse(m.group(1))
        return '<path d="%s"' % pack(pathdata.emit(curvefit.refit(subs, **cfg), nd=3))
    return head + _D.sub(one, body)


def line_groups(text):
    """{line number: the group's markup} — a balanced scan, since the groups nest."""
    out = {}
    for m in _LINE.finditer(text):
        depth, i = 1, m.end()
        while depth and i < len(text):
            nxt = text.find("<", i)
            if nxt < 0:
                break
            if text.startswith("</g>", nxt):
                depth -= 1
                i = nxt + 4
            elif text.startswith("<g", nxt) and text[nxt + 2] in " >\t\r\n":
                depth += 1
                i = nxt + 2
            else:
                i = nxt + 1
        out[int(m.group(1))] = text[m.start():i]
    return out


def wrapper(text):
    """(prefix, suffix) — everything around the content, so one line can stand alone."""
    root = re.search(r'(<svg[^>]*>)(<g transform="matrix\([^)]*\)">)', text)
    return root.group(1), root.group(2)


def write_page(page, pages_index):
    src = editions.page_path(EDITION, page)
    with open(src, encoding="utf-8") as fh:
        shipped = fh.read()
    with open(editions.page_path(EDITION, page, "lines", "json"), encoding="utf-8") as fh:
        bands = {b["lineNumber"]: b for b in json.load(fh)}
    svg_open, g_open = wrapper(shipped)
    box = [float(v) for v in re.search(r'viewBox="([^"]*)"', shipped).group(1).split()]

    folder = os.path.join(OUT, "%03d" % page)
    os.makedirs(folder, exist_ok=True)
    sizes = {}
    for name, cfg in VARIANTS.items():
        text = refit_page(shipped, cfg)
        sizes[name] = len(text)
        groups = line_groups(text)
        for n, markup in sorted(groups.items()):
            b = bands.get(n)
            if not b:
                continue
            vb = "%g %g %g %g" % (box[0], b["top"], box[2], b["bottom"] - b["top"])
            piece = (svg_open.replace(re.search(r'viewBox="[^"]*"', svg_open).group(0),
                                      'viewBox="%s"' % vb)
                     + g_open + markup + "</g></svg>")
            with open(os.path.join(folder, "line%02d-%s.svg" % (n, name)), "w",
                      encoding="utf-8") as fh:
                fh.write(piece)
    pages_index[str(page)] = dict(lines=sorted(bands), bytes=sizes,
                                  viewBox=box)
    print("p%-4d  " % page + "  ".join("%s %.0f kB" % (k, v / 1e3) for k, v in sizes.items()))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", default="3,106,255,550,604")
    ap.add_argument("--workers", type=int, default=min(5, os.cpu_count() or 4))
    args = ap.parse_args(argv)
    pages = [int(p) for p in args.pages.split(",")]
    os.makedirs(OUT, exist_ok=True)

    from multiprocessing import Manager, Pool
    with Manager() as mgr:
        index = mgr.dict()
        with Pool(args.workers) as pool:
            pool.starmap(write_page, [(p, index) for p in pages])
        data = dict(index)
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(dict(edition=EDITION, variants=list(VARIANTS),
                       pages={k: data[k] for k in sorted(data, key=int)}), fh, indent=1)
    print("\nwritten to %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
