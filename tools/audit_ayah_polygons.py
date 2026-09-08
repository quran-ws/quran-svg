#!/usr/bin/env python3
"""Audit the ayah polygons of every mushaf against the page's own markers, ink and qiraa.

Ground truth is the ۝ end-of-ayah markers drawn in each page SVG, the page's rendered ink,
and — for the ayah identities — the counting madhhab the mushaf's qiraa follows, taken from
the vendored `qiraat-ayah-map` dataset.  Nothing here trusts the polygons it is checking.

Violations are reported in four tiers:

  IDENTITY   the ayat a mushaf claims, against its own counting system
  MARKER     every polygon must end at its own ayah's marker
  GEOMETRY   reading order, no overlaps, no unowned ink on a text line
  FILES      json/, svg-br/ and the surah variants must agree with the page SVG

Usage:
    python3 tools/audit_ayah_polygons.py                        # every mushaf, pages 3-604
    python3 tools/audit_ayah_polygons.py --mushaf hafs --pages 294,545
    python3 tools/audit_ayah_polygons.py --tier identity --quiet
    python3 tools/audit_ayah_polygons.py --json report.json
"""

import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import editions
import qiraat_map
from polygon_lib import (EPS, INKCOL, Z, band_spans, build_polygons, ink_mask,
                         line_grid, markers, read_page, recover_markers, score, text_margins,
                         translation_fit)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRST_PAGE, LAST_PAGE = 3, 604          # 1-2 are the ornate opening spread, hand-made

IDENTITY_SIGS = ("COUNT", "GAP", "DUP", "SURAHJSON", "IDSEQ")
MARKER_SIGS = ("MARKERCOUNT", "MARKER", "STRAY", "NOROSETTE", "MARKERMETA")
GEOMETRY_SIGS = ("ORDER", "BREAK", "OVERLAP", "UNCOVERED", "BADID", "NONRECT",
                 "DEGENERATE", "LINES")
FILE_SIGS = ("JSONDIFF", "BRDIFF", "VARIANT")
TIERS = {"identity": IDENTITY_SIGS, "marker": MARKER_SIGS,
         "geometry": GEOMETRY_SIGS, "files": FILE_SIGS}


LINES_PER_PAGE = 15      # every full-size KFQC page is a fifteen-line grid
META_TOL = 8.0           # ayah:x/ayah:y drift: worst measured 7.35; a line band is ~36

_AYAH_ATTRS = re.compile(r'ayah:x="([-\d.]+)" ayah:y="([-\d.]+)"')

_MARKERS_JSON = {}


def markers_json(mushaf):
    """markers.json grouped by page, loaded once."""
    if mushaf not in _MARKERS_JSON:
        path = editions.index_path(mushaf, "markers.json")
        by_page = collections.defaultdict(list)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for entry in json.load(fh):
                    by_page[entry["page"]].append(entry)
        _MARKERS_JSON[mushaf] = by_page
    return _MARKERS_JSON[mushaf]


def marker_metadata(text):
    """The ``ayah:x``/``ayah:y`` the SVG states for each marker, in the mushaf's own frame.

    This is the one piece of evidence the generator never touches, so comparing it against
    the marker centres derived from the transforms checks that layer without routing through
    any shared code.
    """
    k = text.find('<g id="ayah_markers"')
    if k < 0:
        return []
    depth, end = 0, len(text)
    for m in re.finditer(r"<g\b|</g>", text[k:]):
        if m.group(0) == "</g>":
            depth -= 1
            if depth == 0:
                end = k + m.end()
                break
        else:
            depth += 1
    return [(float(x), float(y)) for x, y in _AYAH_ATTRS.findall(text[k:end])]


def page_path(mushaf, page, kind="svg", ext="svg"):
    return editions.page_path(mushaf, page, kind, ext)


# --------------------------------------------------------------------------- per page

def audit_page(args):
    """[(signature, message)] for one page, plus the ayat whose marker is on it."""
    mushaf, page, want_files = args
    svg = page_path(mushaf, page)
    found = []
    text, box, polys = read_page(svg)
    keys = [(p["surah"], p["ayah"]) for p in polys]

    for p in polys:
        if not (p["id"] and re.fullmatch(r"verse-\d+", p["id"])):
            found.append(("BADID", "%s: id is %r, not verse-N" % (p["key"], p["id"])))
        if p["subpaths"] != len(p["rects"]):
            found.append(("NONRECT", "%s: %d subpaths parsed as %d rectangles"
                          % (p["key"], p["subpaths"], len(p["rects"]))))
        for r in p["rects"]:
            if r[2] - r[0] < 0.05 or r[3] - r[1] < 0.05:
                found.append(("DEGENERATE", "%s: rectangle %s has no area" % (p["key"], r)))

    # an ayah that starts on this page and ends on the next carries a continuation polygon
    # here: one extra polygon, last in the file, repeating the next page's first ayah
    continuation = None
    nxt = page_path(mushaf, page + 1)
    next_first = None
    if os.path.exists(nxt):
        _, _, next_polys = read_page(nxt)
        if next_polys:
            next_first = next_polys[0]["key"]
    mk = markers(text)
    if len(mk) < len(polys):
        mk, rescued = recover_markers(mk, markers_json(mushaf).get(page, []))
        for x, y, _ in rescued:
            found.append(("NOROSETTE", "an ayah ends at (%.2f, %.2f) with a bare numeral and no "
                          "۝ rosette in the svg; markers.json supplied the position" % (x, y)))
    if polys and len(polys) == len(mk) + 1 and polys[-1]["key"] == next_first:
        continuation = polys.pop()
        keys = keys[:-1]
    if len(mk) != len(polys):
        found.append(("MARKERCOUNT", "%d polygons but %d marker rosettes drawn"
                      % (len(polys) + (1 if continuation else 0), len(mk))))

    # the marker layer, checked against the SVG's own metadata rather than against itself
    meta = marker_metadata(text)
    if meta and mk:
        if len(meta) != len(mk):
            found.append(("MARKERMETA", "%d markers derived from the transforms but %d "
                          "ayah:x/ayah:y attributes" % (len(mk), len(meta))))
        else:
            # The attributes are anchored on the numeral, not on the medallion, so they
            # drift on wider numbers.  Measured with this same metric over all 31,061
            # markers: median 0.13, p99 2.27, worst 7.35 (shubah p313).  The tolerance
            # therefore has 0.65 units of headroom, not much -- but a marker attributed to
            # the wrong line is ~36 units out, which is what this check exists to catch.
            entries = [{"x": x, "y": y} for x, y in meta]
            n, dx, dy = translation_fit(mk, entries, tol=META_TOL)
            if n < len(mk):
                worst = max(min(max(abs(e["x"] - dx - x), abs(e["y"] - dy - y))
                                for e in entries) for x, y, _ in mk)
                found.append(("MARKERMETA", "%d of %d markers agree with the page's own "
                              "ayah:x/ayah:y (worst miss %.2f units)" % (n, len(mk), worst)))

    mask = ink_mask(svg)
    pitch, bands = line_grid(mask, [m[1] for m in mk], box)
    if not bands:
        found.append(("LINES", "no inked line bands found on the page"))
        return page, found, keys
    if box[3] > 400 and len(bands) != LINES_PER_PAGE:
        found.append(("LINES", "%d line bands found, expected %d"
                      % (len(bands), LINES_PER_PAGE)))
    old = {p["key"]: [list(r) for r in p["rects"]] for p in polys}
    if continuation:
        old[continuation["key"]] = [list(r) for r in continuation["rects"]]

    # what the page *should* look like, built from the markers alone
    reference = None
    if len(mk) == len(polys) and bands:
        try:
            reference, margins, decor, notes, _ = build_polygons(bands, mk, keys, box, next_first)
        except ValueError as exc:
            found.append(("BREAK", "cannot model this page: %s" % exc))
        else:
            for note in notes:
                found.append(("ORDER", note))
    if reference is None:
        decor = set()
        margins = text_margins(bands, box) if bands else (box[0], box[0] + box[2])

    sc = score(old, bands, decor, mask, mk, box, ["%d:%d" % k for k in keys])
    if sc["overlap_pairs"]:
        flat = [(k, r) for k, rs in old.items() for r in rs]
        shown = 0
        for i in range(len(flat)):
            ka, ra = flat[i]
            for j in range(i + 1, len(flat)):
                kb, rb = flat[j]
                if ka == kb:
                    continue
                ox = min(ra[2], rb[2]) - max(ra[0], rb[0])
                oy = min(ra[3], rb[3]) - max(ra[1], rb[1])
                if ox > 0.05 and oy > 0.05 and shown < 6:
                    shown += 1
                    found.append(("OVERLAP", "%s and %s both claim %.1f x %.2f at x%.1f y%.1f"
                                  % (ka, kb, ox, oy, max(ra[0], rb[0]), max(ra[1], rb[1]))))
    if sc["stray_markers"]:
        found.append(("STRAY", "%d ayah(s) whose polygon does not contain their own marker"
                      % sc["stray_markers"]))
    if sc["uncovered_ink"] > 200:
        found.append(("UNCOVERED", "%d ink pixels on text lines belong to no ayah"
                      % sc["uncovered_ink"]))

    # every polygon must end at its own marker: the boundary has to fall in the whitespace
    # beside the medallion, not inside the medallion and not over the next ayah's first glyph
    if reference is not None and bands:
        for key, marker in zip(("%d:%d" % k for k in keys),
                               sorted(mk, key=lambda t: (_band_of(bands, t[1]), -t[0]))):
            rects = old.get(key)
            if not rects:
                continue
            last = sorted(rects, key=lambda r: (r[1], -r[2]))[-1]
            band = _band_of(bands, marker[1])
            if not last[1] - 1.0 <= marker[1] <= last[3] + 1.0:
                found.append(("MARKER", "%s ends on the line at y%.1f-%.1f but its marker is at "
                              "y%.2f" % (key, last[1], last[3], marker[1])))
                continue
            lo, hi = _boundary_window(bands[band], marker, box[0], margins[0])
            if not lo - 0.6 <= last[0] <= hi + 0.6:
                found.append(("MARKER", "%s ends at x=%.2f; the whitespace beside its marker "
                              "runs x%.2f..%.2f" % (key, last[0], lo, hi)))

    # what the marker geometry says the page should look like, line by line
    if reference is not None:
        for key in ("%d:%d" % k for k in keys):
            want, got = reference.get(key, []), old.get(key, [])
            if not want or not got:
                continue
            want_bands = [i for i, b in enumerate(bands) if band_spans(want, b["top"], b["bot"])]
            got_bands = [i for i, b in enumerate(bands) if band_spans(got, b["top"], b["bot"])]
            if want_bands != got_bands:
                found.append(("BREAK", "%s covers lines %s but its marker puts it on %s"
                              % (key, got_bands, want_bands)))

    if want_files:
        found += audit_files(mushaf, page, text,
                             polys + ([continuation] if continuation else []))
    return page, found, keys


def _band_of(bands, y):
    for i, b in enumerate(bands):
        if b["top"] <= y < b["bot"]:
            return i
    return min(range(len(bands)), key=lambda i: abs((bands[i]["top"] + bands[i]["bot"]) / 2 - y))


def _boundary_window(band, marker, x0, left_margin, z=Z):
    """(lo, hi) — where an ayah ending at this marker may put its left edge: anywhere in the
    whitespace between the medallion and the next glyph.  When the medallion touches that
    glyph the window collapses onto the medallion's own edge; when nothing follows on the
    line the ayah runs out to the margin."""
    centre, half = marker[0], marker[2]
    col = band["col"]
    edge = centre - half
    i = min(int((edge - x0 - 0.5) * z), len(col) - 1)
    if i < 0:
        return edge, edge
    if col[i] > INKCOL:
        return edge - 1.0, edge + 1.0
    first_empty = i
    while i >= 0 and col[i] <= INKCOL:
        i -= 1
    if i < 0:
        return left_margin, edge          # the line ends here
    return (i + 0.5) / z + x0, (first_empty + 0.5) / z + x0


def audit_files(mushaf, page, text, polys):
    """json/, svg-br/ and the surah-variant files must agree with the page SVG."""
    import brotli
    found = []
    jpath = page_path(mushaf, page, "json", "json")
    if os.path.exists(jpath):
        with open(jpath, encoding="utf-8") as fh:
            entries = json.load(fh)
        if len(entries) != len(polys):
            found.append(("JSONDIFF", "json has %d entries, the svg has %d polygons"
                          % (len(entries), len(polys))))
        else:
            for e, p in zip(entries, polys):
                if (e["surahNumber"], e["ayahNumber"]) != (p["surah"], p["ayah"]):
                    found.append(("JSONDIFF", "json lists %d:%d where the svg has %s"
                                  % (e["surahNumber"], e["ayahNumber"], p["key"])))
                    break
                if e["polygon"].strip() != p["d"].strip():
                    found.append(("JSONDIFF", "%s: polygon differs between json and svg" % p["key"]))
                    break
    else:
        found.append(("JSONDIFF", "no json/%03d.json" % page))

    br = editions.page_path(mushaf, page, "svg-br", "svg.br")
    if not os.path.exists(br):
        found.append(("BRDIFF", "no svg-br/%03d.svg.br" % page))
    else:
        with open(br, "rb") as fh:
            blob = fh.read()
        try:
            if brotli.decompress(blob) != text.encode("utf-8"):
                found.append(("BRDIFF", "svg-br/%03d.svg.br does not decompress to the svg" % page))
        except Exception as exc:                                  # noqa: BLE001
            found.append(("BRDIFF", "svg-br/%03d.svg.br is unreadable: %s" % (page, exc)))

    page_d = [p["d"].strip() for p in polys]
    base = editions.base(mushaf)
    for variant in sorted(os.listdir(os.path.join(base, "svg"))):
        if not re.fullmatch(r"%03d-surah\d+\.svg" % page, variant):
            continue
        stem = variant[:-4]
        with open(os.path.join(base, "svg", variant), encoding="utf-8") as fh:
            vtext = fh.read()
        _, _, vpolys = read_page(os.path.join(base, "svg", variant))
        if [p["d"].strip() for p in vpolys] != page_d:
            found.append(("VARIANT", "%s carries different polygon geometry from the page"
                          % variant))
        vjson = os.path.join(base, "json", stem + ".json")
        if not os.path.exists(vjson):
            found.append(("VARIANT", "no json/%s.json" % stem))
        else:
            with open(vjson, encoding="utf-8") as fh:
                ventries = json.load(fh)
            if [e["polygon"].strip() for e in ventries] != [p["d"].strip() for p in vpolys]:
                found.append(("VARIANT", "json/%s.json does not match its svg" % stem))
        vbr = os.path.join(base, "svg-br", stem + ".svg.br")
        if not os.path.exists(vbr):
            found.append(("VARIANT", "no svg-br/%s.svg.br" % stem))
        else:
            with open(vbr, "rb") as fh:
                blob = fh.read()
            try:
                if brotli.decompress(blob) != vtext.encode("utf-8"):
                    found.append(("VARIANT", "svg-br/%s.svg.br does not decompress to its svg"
                                  % stem))
            except Exception as exc:                              # noqa: BLE001
                found.append(("VARIANT", "svg-br/%s.svg.br is unreadable: %s" % (stem, exc)))
    return found


# --------------------------------------------------------------------------- per mushaf

def audit_identity(mushaf, per_page, kufi):
    """The ayat a mushaf claims, against the counting system its qiraa follows."""
    system = qiraat_map.counting_system(editions.riwaya(mushaf))
    expected = qiraat_map.ayah_counts(system, kufi)
    seen = collections.defaultdict(list)
    for page, keys in per_page.items():
        for surah, ayah in keys:
            seen[surah].append((ayah, page))
    found = []
    for surah in sorted(set(expected) | set(seen)):
        want = expected.get(surah, 0)
        got = sorted(a for a, _ in seen.get(surah, []))
        dup = sorted({a for a in got if got.count(a) > 1})
        uniq = sorted(set(got))
        if dup:
            found.append(("DUP", "surah %d: ayah(s) %s appear more than once"
                          % (surah, ", ".join(map(str, dup)))))
        if not uniq:
            continue
        missing = [a for a in range(1, want + 1) if a not in set(uniq)]
        extra = [a for a in uniq if a > want]
        # a surah that starts on page 1 or 2 is only partly in scope
        partial = min(p for a, p in seen[surah]) <= FIRST_PAGE and 1 in missing
        if missing and not partial:
            found.append(("GAP", "surah %d is missing ayah(s) %s"
                          % (surah, ", ".join(map(str, missing[:12])))))
        if extra:
            found.append(("COUNT", "surah %d has ayah numbers up to %d, but the %s system "
                          "counts %d" % (surah, max(uniq), system, want)))
    return system, expected, found


def audit_surah_json(mushaf, system, expected):
    path = editions.index_path(mushaf, "surah.json")
    if not os.path.exists(path):
        return [("SURAHJSON", "no surah.json")]
    with open(path, encoding="utf-8") as fh:
        surahs = json.load(fh)
    found = []
    total = sum(int(s["ayahCount"]) for s in surahs)
    want_total = qiraat_map.expected_total(system)
    if total != want_total:
        found.append(("SURAHJSON", "surah.json totals %d ayat; the %s system counts %d"
                      % (total, system, want_total)))
    wrong = [(int(s["number"]), int(s["ayahCount"]), expected[int(s["number"])])
             for s in surahs if int(s["ayahCount"]) != expected[int(s["number"])]]
    for number, got, want in wrong[:20]:
        found.append(("SURAHJSON", "surah %d: surah.json says %d ayat, the %s system counts %d"
                      % (number, got, system, want)))
    if len(wrong) > 20:
        found.append(("SURAHJSON", "... and %d more surahs disagree" % (len(wrong) - 20)))
    return found


def audit_id_sequence(mushaf, pages):
    """verse-N ids must run 1..total once, in reading order, across the whole mushaf."""
    found, previous, last_page = [], None, None
    for page in pages:
        text, _, polys = read_page(page_path(mushaf, page))
        for p in polys:
            if not (p["id"] and re.fullmatch(r"verse-\d+", p["id"])):
                continue
            n = int(p["id"].split("-")[1])
            if previous is not None and n not in (previous, previous + 1):
                found.append(("IDSEQ", "page %d: %s follows verse-%d on page %s"
                              % (page, p["id"], previous, last_page)))
            previous, last_page = max(previous or 0, n), page
    return found


# --------------------------------------------------------------------------- driver

def parse_pages(spec):
    if not spec:
        return list(range(FIRST_PAGE, LAST_PAGE + 1))
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return [p for p in out if FIRST_PAGE <= p <= LAST_PAGE]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mushaf", help="comma-separated editions, e.g. hafs/kfqc-1422 "
                    "(default: every edition)")
    ap.add_argument("--pages", help="comma-separated pages or A-B ranges")
    ap.add_argument("--tier", choices=("all",) + tuple(TIERS), default="all")
    ap.add_argument("--workers", type=int, default=min(12, (os.cpu_count() or 4)))
    ap.add_argument("--max-detail", type=int, default=4, help="messages per page per signature")
    ap.add_argument("--quiet", action="store_true", help="summary only")
    ap.add_argument("--json", help="write the full report here")
    args = ap.parse_args(argv)

    mushafs = editions.resolve(args.mushaf)
    pages = parse_pages(args.pages)
    keep = set(sum((list(TIERS[t]) for t in TIERS), [])) if args.tier == "all" else set(TIERS[args.tier])
    want_files = args.tier in ("all", "files")

    kufi = qiraat_map.kufi_counts_from_surah_json(
        editions.index_path(editions.DEFAULT, "surah.json"))

    from multiprocessing import Pool
    report, totals = {}, collections.Counter()
    for mushaf in mushafs:
        per_page, findings = {}, []
        with Pool(args.workers) as pool:
            jobs = [(mushaf, p, want_files) for p in pages]
            for page, found, keys in pool.imap_unordered(audit_page, jobs, chunksize=4):
                per_page[page] = keys
                findings += [(page, sig, msg) for sig, msg in found]
        system = qiraat_map.counting_system(editions.riwaya(mushaf))
        whole_mushaf = pages == list(range(FIRST_PAGE, LAST_PAGE + 1))
        if whole_mushaf:
            system, expected, ident = audit_identity(mushaf, per_page, kufi)
            findings += [(None, sig, msg) for sig, msg in ident]
            findings += [(None, sig, msg) for sig, msg in audit_surah_json(mushaf, system, expected)]
            findings += [(None, sig, msg) for sig, msg in audit_id_sequence(mushaf, pages)]
        elif args.tier in ("all", "identity"):
            print("    (identity checks need the whole mushaf; skipped for a page subset)")
        findings = [f for f in findings if f[1] in keep]
        report[mushaf] = dict(counting_system=system,
                              findings=[dict(page=p, signature=s, message=m) for p, s, m in findings])
        counts = collections.Counter(s for _, s, _ in findings)
        totals.update(counts)

        print("%s — %s" % (mushaf, qiraat_map.describe(system)))
        if not findings:
            print("    clean: %d pages, %d ayat\n"
                  % (len(pages), sum(len(v) for v in per_page.values())))
            continue
        for tier, sigs in TIERS.items():
            live = [(p, s, m) for p, s, m in findings if s in sigs]
            if not live:
                continue
            print("  %s: %d" % (tier.upper(), len(live)))
            shown = collections.Counter()
            for p, s, m in live:
                shown[s] += 1
                if shown[s] <= args.max_detail:
                    print("    %-12s %s%s" % (s, ("p%d " % p) if p else "", m))
            for s, n in shown.items():
                if n > args.max_detail:
                    print("    %-12s ... %d more" % (s, n - args.max_detail))
        print()

    print("total findings: %d" % sum(totals.values()))
    for sig, n in totals.most_common():
        print("  %-12s %5d" % (sig, n))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
        print("\nreport written to %s" % args.json)
    return 1 if totals else 0


if __name__ == "__main__":
    sys.exit(main())
