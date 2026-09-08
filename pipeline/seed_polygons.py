#!/usr/bin/env python3
"""Give a new edition its ayah identities, so the generator can give them geometry.

``tools/build_ayah_polygons.py`` rebuilds the ``d`` of every ``path.ayahPolygon`` from the
page's own markers and ink, but it never invents one: the identities -- which ayah, which
running verse number -- have to be on the page already.  A freshly converted edition has
none.

Where they come from here is the point of the whole exercise.  The two Hafs editions are the
same muṣḥaf: the 1422 pages carry 6,224 ۝ rosettes over pages 3-604 and so do the 1441
pages, page for page, with no exceptions -- so ayah *n* of a page is the same ayah in both,
and the identities transfer.  That is checked before anything is written, per page, and a
page whose rosette count disagrees is refused rather than guessed at.

Only the attributes cross over.  Every ``d`` written here is a placeholder; the geometry is
the new edition's own, measured from its own ink by the generator in the next step.

    python3 pipeline/seed_polygons.py --edition hafs/kfqc-1422 --from hafs/kfqc-1441
    python3 pipeline/seed_polygons.py --dry-run
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import editions                                                  # noqa: E402
import markers as markerlib                                      # noqa: E402
from polygon_lib import markers as svg_markers, read_page        # noqa: E402

PLACEHOLDER = "M 0.0 0.0 L 0.0 0.0 L 0.0 0.0 L 0.0 0.0 Z"
ORDER = ("fill-opacity", "id", "number", "ayah", "surah")
_EXISTING = re.compile(r'<path class="ayahPolygon"[^>]*?/>')


def element(attrs):
    body = " ".join('%s="%s"' % (k, attrs[k]) for k in ORDER if k in attrs)
    return '<path class="ayahPolygon" %s d="%s"/>' % (body, PLACEHOLDER)


def seed_page(target, source, page):
    """(text, count) — the target page with one placeholder polygon per source polygon."""
    src = editions.page_path(source, page)
    dst = editions.page_path(target, page)
    _, _, polys = read_page(src)
    if not polys:
        raise ValueError("%s has no ayah polygons to copy" % os.path.basename(src))
    with open(dst, encoding="utf-8") as fh:
        text = fh.read()

    theirs = len(svg_markers(open(src, encoding="utf-8").read()))
    ours = len(svg_markers(text))
    if ours != theirs:
        raise ValueError("%d rosettes here against %d in %s — identities would be a guess"
                         % (ours, theirs, source))

    text = _EXISTING.sub("", text)                    # re-seeding replaces, never appends
    added = "".join(element(p["attrs"]) for p in polys)
    return text.replace("</svg>", added + "</svg>"), len(polys)


def _job(args):
    target, source, page, dry = args
    try:
        text, n = seed_page(target, source, page)
    except Exception as exc:                                     # noqa: BLE001
        return page, -1, repr(exc)
    if not dry:
        with open(editions.page_path(target, page), "w", encoding="utf-8") as fh:
            fh.write(text)
    return page, n, None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--edition", default="hafs/kfqc-1422")
    ap.add_argument("--from", dest="source", default="hafs/kfqc-1441")
    ap.add_argument("--pages", default="3-604")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4))
    args = ap.parse_args(argv)

    pages = []
    for part in args.pages.split(","):
        if "-" in part.strip("-"):
            a, b = part.split("-")
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))

    from multiprocessing import Pool
    total, failed = 0, []
    with Pool(args.workers) as pool:
        for page, n, why in pool.imap_unordered(
                _job, [(args.edition, args.source, p, args.dry_run) for p in pages],
                chunksize=4):
            if n < 0:
                failed.append((page, why))
            else:
                total += n
    print("%s: %d polygons seeded on %d pages from %s%s"
          % (args.edition, total, len(pages) - len(failed), args.source,
             " (dry run)" if args.dry_run else ""))
    for page, why in sorted(failed):
        print("   FAILED p%-3d %s" % (page, why))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
