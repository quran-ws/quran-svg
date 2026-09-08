#!/usr/bin/env python3
"""Regenerate the ayah polygons of a mushaf from its own markers and ink.

For every page this rewrites, in place:

  ``svg/NNN.svg``        the ``d`` of each ``path.ayahPolygon`` (and a malformed ``id``)
  ``json/NNN.json``      the per-page polygon list
  ``svg-br/NNN.svg.br``  the Brotli copy of the rewritten svg

Nothing else in the SVG is touched — the glyphs, the marker group and every other attribute
are left byte for byte as they were.  An ayah that continues onto the next page also gets a
polygon on the page it starts on; those json entries carry ``"continuation": true`` and the
coordinates of the marker that ends the ayah, which is drawn on the following page.

Usage:
    python3 tools/build_ayah_polygons.py --dry-run              # report, write nothing
    python3 tools/build_ayah_polygons.py                        # every mushaf, pages 3-604
    python3 tools/build_ayah_polygons.py --mushaf warsh --pages 50,415
"""

import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import brotli

from editions import EDITIONS, base as edition_base, index_path, page_path, resolve
from polygon_lib import (build_polygons, ink_mask, line_grid, markers, merge_rects,
                         path_d, read_page, recover_markers)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRST_PAGE, LAST_PAGE = 3, 604
BROTLI_QUALITY = 11        # what the shipped .svg.br files were produced with

_ELEMENT = re.compile(r'<path class="ayahPolygon"[^>]*?/>')


def paths(mushaf, page, stem=None):
    return (page_path(mushaf, page, "svg", "svg", stem),
            page_path(mushaf, page, "json", "json", stem),
            page_path(mushaf, page, "svg-br", "svg.br", stem))


def variants(mushaf, page):
    """The surah-specific crops of a page: same coordinate space, narrower viewBox."""
    svg_dir = os.path.join(edition_base(mushaf), "svg")
    return sorted(f[:-4] for f in os.listdir(svg_dir)
                  if re.fullmatch(r"%03d-surah\d+\.svg" % page, f))


_MARKERS_JSON = {}


def markers_json(mushaf):
    """markers.json grouped by page, loaded once."""
    if mushaf not in _MARKERS_JSON:
        path = index_path(mushaf, "markers.json")
        by_page = collections.defaultdict(list)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for entry in json.load(fh):
                    by_page[entry["page"]].append(entry)
        _MARKERS_JSON[mushaf] = by_page
    return _MARKERS_JSON[mushaf]


def regenerate(mushaf, page):
    """(svg_text, json_entries, stats) for one page, or (None, None, reason)."""
    svg_path, _, _ = paths(mushaf, page)
    text, box, polys = read_page(svg_path)
    if not polys:
        return None, None, "no ayah polygons on the page"
    tail_key, tail_attrs = None, None
    nxt = paths(mushaf, page + 1)[0]
    if os.path.exists(nxt):
        _, _, next_polys = read_page(nxt)
        if next_polys:
            tail_key, tail_attrs = next_polys[0]["key"], next_polys[0]["attrs"]

    # A continuation polygon written by an earlier run belongs to the next page's first ayah,
    # not to this page's own list.  Setting it aside is what makes the generator idempotent:
    # leave it in and the page has one more polygon than it has markers, and gets skipped.
    existing_tail = None
    if (len(polys) > 1 and tail_key and polys[-1]["key"] == tail_key
            and tail_key not in {p["key"] for p in polys[:-1]}):
        existing_tail = polys.pop()

    keys = [(p["surah"], p["ayah"]) for p in polys]
    mk = markers(text)
    recovered = []
    if len(mk) < len(polys):
        mk, recovered = recover_markers(mk, markers_json(mushaf).get(page, []))
    if len(mk) != len(polys):
        return None, None, ("%d polygons but %d marker rosettes, and markers.json does not "
                            "resolve the rest" % (len(polys), len(mk) - len(recovered)))
    mask = ink_mask(svg_path)
    _, bands = line_grid(mask, [m[1] for m in mk], box)
    if not bands:
        return None, None, "no inked lines found on the page"

    built, _, _, notes, has_tail = build_polygons(bands, mk, keys, box, tail_key)

    # marker coordinates, paired with the ayat in reading order
    def band_of(y):
        for i, b in enumerate(bands):
            if b["top"] <= y < b["bot"]:
                return i
        return min(range(len(bands)), key=lambda i: abs((bands[i]["top"] + bands[i]["bot"]) / 2 - y))
    ordered = sorted(mk, key=lambda m: (band_of(m[1]), -m[0]))
    marker_of = {"%d:%d" % k: m for k, m in zip(keys, ordered)}

    geometry = {k: path_d(merge_rects(v)) for k, v in built.items()}
    new_text = rewrite_polygons(text, polys, geometry, tail_key if has_tail else None,
                                tail_attrs, existing_tail)

    entries = []
    for p in polys:
        m = marker_of["%d:%d" % (p["surah"], p["ayah"])]
        entries.append(collections.OrderedDict(
            surahNumber=p["surah"], ayahNumber=p["ayah"],
            x=round(m[0], 2), y=round(m[1], 2),
            polygon=path_d(merge_rects(built[p["key"]]))))
    if has_tail and tail_attrs:
        entries.append(collections.OrderedDict(
            surahNumber=int(tail_attrs["surah"]), ayahNumber=int(tail_attrs["ayah"]),
            x=None, y=None, continuation=True,
            polygon=path_d(merge_rects(built[tail_key]))))
    if recovered:
        notes = list(notes) + ["%d ayah end(s) had no ۝ rosette in the svg; position taken "
                               "from markers.json: %s" % (len(recovered),
                               ", ".join("(%.2f, %.2f)" % (x, y) for x, y, _ in recovered))]
    return new_text, entries, dict(geometry=geometry, tail=has_tail, tail_key=tail_key,
                                   tail_attrs=tail_attrs, notes=notes)


def rewrite_polygons(text, polys, geometry, tail_key=None, tail_attrs=None, existing_tail=None):
    """The same svg with every ayahPolygon's ``d`` replaced, a malformed ``id`` repaired, and
    the continuation polygon written, rewritten or dropped.  Everything else is left byte for
    byte."""
    out, cursor = [], 0
    for i, p in enumerate(polys):
        start, end = p["span"]
        element = text[start:end]
        element = element.replace('d="%s"' % p["d"], 'd="%s"' % geometry[p["key"]])
        if not (p["id"] and re.fullmatch(r"verse-\d+", p["id"])):
            fixed = _repair_id(polys, i)
            if fixed:
                element = re.sub(r'id="[^"]*"', 'id="%s"' % fixed, element, count=1)
        out.append(text[cursor:start])
        out.append(element)
        cursor = end
    if existing_tail is not None:
        start, end = existing_tail["span"]
        out.append(text[cursor:start])
        if tail_key:                      # rewrite the one already there
            out.append(text[start:end].replace('d="%s"' % existing_tail["d"],
                                               'd="%s"' % geometry[tail_key]))
        cursor = end                      # otherwise drop it: the page no longer needs one
    elif tail_key and tail_attrs:
        attrs = " ".join('%s="%s"' % (k, tail_attrs[k])
                         for k in ("fill-opacity", "id", "number", "ayah", "surah")
                         if k in tail_attrs)
        out.append('<path class="ayahPolygon" %s d="%s"/>' % (attrs, geometry[tail_key]))
    out.append(text[cursor:])
    return "".join(out)


def _repair_id(polys, index):
    """A malformed verse id, recovered from its neighbours' running numbers."""
    for step in (1, -1):
        j = index + step
        while 0 <= j < len(polys):
            other = polys[j]["id"]
            if other and re.fullmatch(r"verse-\d+", other):
                return "verse-%d" % (int(other.split("-")[1]) - step * abs(j - index))
            j += step
    return None


def write_json(path, entries):
    """Keep each file's own layout: the page files are one compact line, the surah crops are
    indented.  Reformatting either would bury the real change in whitespace."""
    indent, newline = None, ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            existing = fh.read()
        if "\n" in existing.strip():
            indent = len(existing.split("\n")[1]) - len(existing.split("\n")[1].lstrip())
            newline = "\n" if existing.endswith("\n") else ""
    with open(path, "w", encoding="utf-8") as fh:
        if indent:
            json.dump(entries, fh, ensure_ascii=False, indent=indent)
        else:
            json.dump(entries, fh, ensure_ascii=False, separators=(", ", ": "))
        fh.write(newline)


def process(args):
    mushaf, page, dry = args
    svg_path, json_path, br_path = paths(mushaf, page)
    try:
        text, entries, stats = regenerate(mushaf, page)
    except Exception as exc:                                       # noqa: BLE001
        return page, "error", repr(exc)
    if text is None:
        return page, "skipped", stats
    if not dry:
        with open(svg_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        write_json(json_path, entries)
        with open(br_path, "wb") as fh:
            fh.write(brotli.compress(text.encode("utf-8"), quality=BROTLI_QUALITY))
    written = 0
    for stem in variants(mushaf, page):
        written += write_variant(mushaf, page, stem, entries, stats, dry)
    stats["variants"] = written
    return page, "ok", stats


def write_variant(mushaf, page, stem, entries, stats, dry):
    """A surah crop shares its page's coordinate space, so it takes the same geometry."""
    svg_path, json_path, br_path = paths(mushaf, page, stem)
    text, _, polys = read_page(svg_path)
    geometry = stats["geometry"]
    tail_key = stats["tail_key"] if stats["tail"] else None

    # Same as regenerate(): a continuation polygon left by an earlier run is not one of the
    # page's own.  Without this the crop would keep the old one *and* gain a fresh copy on
    # every run.
    existing_tail = None
    if (len(polys) > 1 and stats["tail_key"] and polys[-1]["key"] == stats["tail_key"]
            and stats["tail_key"] not in {q["key"] for q in polys[:-1]}):
        existing_tail = polys.pop()

    if any(q["key"] not in geometry for q in polys):
        return 0
    new_text = rewrite_polygons(text, polys, geometry, tail_key,
                                stats["tail_attrs"], existing_tail)
    if not dry:
        with open(svg_path, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        write_json(json_path, entries)
        with open(br_path, "wb") as fh:
            fh.write(brotli.compress(new_text.encode("utf-8"), quality=BROTLI_QUALITY))
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mushaf", help="comma-separated editions, e.g. hafs/kfqc-1422 "
                    "(default: every edition)")
    ap.add_argument("--pages", help="comma-separated pages or A-B ranges")
    ap.add_argument("--workers", type=int, default=min(12, (os.cpu_count() or 4)))
    ap.add_argument("--dry-run", action="store_true", help="report what would change")
    args = ap.parse_args(argv)

    mushafs = resolve(args.mushaf)
    if args.pages:
        pages = []
        for part in args.pages.split(","):
            if "-" in part:
                a, b = part.split("-")
                pages.extend(range(int(a), int(b) + 1))
            else:
                pages.append(int(part))
        pages = [p for p in pages if FIRST_PAGE <= p <= LAST_PAGE]
    else:
        pages = list(range(FIRST_PAGE, LAST_PAGE + 1))

    from multiprocessing import Pool
    failed = 0
    for mushaf in mushafs:
        counts = collections.Counter()
        skipped, errors, tails, notes, variant_files = [], [], 0, [], 0
        with Pool(args.workers) as pool:
            for page, status, stats in pool.imap_unordered(
                    process, [(mushaf, p, args.dry_run) for p in pages], chunksize=4):
                counts[status] += 1
                if status == "ok":
                    tails += bool(stats["tail"])
                    variant_files += stats.get("variants", 0)
                    notes += ["p%d %s" % (page, n) for n in stats["notes"]]
                elif status == "skipped":
                    skipped.append((page, stats))
                else:
                    errors.append((page, stats))
        print("%-7s %d pages written, %d surah crops, %d skipped, %d errors, "
              "%d continuation polygons"
              % (mushaf, counts["ok"], variant_files, counts["skipped"], counts["error"], tails))
        for page, why in sorted(skipped):
            print("    skipped p%-3d %s" % (page, why))
        for page, why in sorted(errors):
            print("    ERROR   p%-3d %s" % (page, why))
        for note in notes:
            print("    note    %s" % note)
        failed += counts["error"]
    if args.dry_run:
        print("\ndry run — nothing was written")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
