#!/usr/bin/env python3
"""Add per-line structure to the mushaf page SVGs, and write `lines/NNN.json` beside them.

A page's whole body is one `<path>` — `hafs/255`'s `d` is 456,221 characters — with no
markup to say where one line ends and the next begins. This groups that path's glyph
contours into `<g class="line" data-line="N">`, N counting from 1 at the top of the
rendered page, and writes the same geometry out as JSON for consumers that would rather
not parse SVG.

The restructuring is a pure regrouping. Every contour is copied out of the source
byte-for-byte; the only numbers this program writes into an SVG are the absolute `moveto`
that has to replace a relative one when a contour is lifted out of its original chain, and
those round-trip through float64 exactly. The filled region is therefore identical, which
`check` proves per page and `verify_render.py` confirms by rendering.

Usage:

    tools/add_line_structure.py                       # every mushaf
    tools/add_line_structure.py --mushaf hafs/kfqc    # one edition
    tools/add_line_structure.py --check               # validate only, write nothing
    tools/add_line_structure.py --no-brotli           # skip regenerating svg-br/
    tools/verify_render.py hafs/kfqc                  # render every page before and after

Re-running is safe: a page that already carries line groups is restored to its original
shape first, so the tool is idempotent and can be re-run whenever the pages are
regenerated upstream.
"""

import argparse
import json
import os
import re
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from page import Page                                                     # noqa: E402
from svg_lines import (band_index, clusters, fmt, segment,
                       segment_valleys)                                   # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mushafs")

# A standard muṣḥaf body page has fifteen lines. This is the correctness gate: a body page
# that does not segment to fifteen is reported, never emitted.
BODY_LINES = 15

# The two opening pages are set on their own spacing rather than the body grid, and hold
# seven lines each rather than fifteen: Al-Fatiha over seven, and the basmala plus the
# first six lines of Al-Baqarah. Counted off rendered images of pages 1 and 2 of all five
# editions — and cross-checked by the segmentation itself, which refused to cut shubah/002
# into eight when eight was first assumed.
OPENING_LINES = {1: 7, 2: 7}

# Every cut must fall in clear space: ink within ±0.5 units of a cut, as a fraction of one
# line's ink. Measured over all 3,010 body pages the worst is under 2%.
MAX_CUT_INK = 0.05
# The emptiest band must still hold a real line's worth of ink against the typical band.
MIN_BAND_FILL = 0.10

# Contours within this distance of each other are assigned to a line as one unit, so that
# splitting the page can neither break an `evenodd` cancellation nor re-composite an
# anti-aliased edge. 0.5 page units is about one device pixel on a page rendered at twice
# its nominal width, and about a fifth of the narrowest inter-line gap on these pages.
CLUSTER_EPS = 0.5

# Ink this tall is a letter, not a diacritic. Letters are what must not be
# filed under a line they are not drawn in; marks stand in the gap between
# lines by design and are better left with the letters they cluster with.
LETTER_H = 6.0

LINE_GROUP_RE = re.compile(r'<g class="line" data-line="\d+">')


# ---------------------------------------------------------------------------
# Segmenting one page
# ---------------------------------------------------------------------------

def page_number(name):
    m = re.match(r"^(\d+)", name)
    return int(m.group(1)) if m else None


def is_variant(name):
    """`255-surah14.svg` — the same page cropped to one of the surahs on it."""
    return bool(re.match(r"^\d+-surah\d+\.svg$", name))


def ink_boxes(page, contours):
    """Contour boxes that fall inside the viewport, which is what the reader sees.

    A few pages carry ink outside their own viewBox — `hafs/001` has 32 contours sitting
    above the top edge. It is clipped away by the viewport, so it must not be allowed to
    invent a line; it is still assigned to its nearest line when the page is rewritten.
    """
    vb = page.viewbox
    out = []
    for c in contours:
        if vb and (c["y2"] < vb[1] - 1 or c["y1"] > vb[1] + vb[3] + 1):
            continue
        out.append((c["y1"], c["y2"], c["x2"] - c["x1"]))
    return out


def segment_page(page, contours, expected, method):
    boxes = ink_boxes(page, contours)
    if not boxes:
        return None, None, "no visible ink"
    fn = segment_valleys if method == "valleys" else segment
    bands, info = fn(boxes, expected)
    if not bands or "cut_ink" not in info:
        return None, None, info.get("reason", "no fit")
    return bands, info, None


def assign(contours, bands, eps=CLUSTER_EPS):
    """Give every contour a line, keeping contours that can interact on the same one.

    Sets `line` on each contour and returns how many were pulled onto a line other than
    the one their own centre falls in — the cost of keeping renderable units intact.
    """
    moved = 0
    by_path = {}
    for c in contours:
        by_path.setdefault(c["path"], []).append(c)
    def vote(members, source):
        weights = [0.0] * len(bands)
        for i in members:
            c = source[i]
            weights[band_index(bands, (c["y1"] + c["y2"]) / 2)] += max(c["x2"] - c["x1"], 0.01)
        return weights.index(max(weights))

    for group in by_path.values():
        for members in clusters(group, eps):
            line = vote(members, group)
            spans = {band_index(bands, (group[i]["y1"] + group[i]["y2"]) / 2)
                     for i in members}
            if len(spans) > 1:
                # Proximity chains: a descender that dips toward the line below
                # comes within eps of it, that ink comes within eps of more, and
                # the cluster grows until a whole word on THIS line is outvoted
                # by ink on the next one and dragged there with it. Only
                # contours that actually OVERLAP can mis-render when separated —
                # that is what `evenodd` cancels — so where a cluster spans
                # bands, re-form it from overlap alone and let each piece take
                # the line holding most of its own ink. Contours that merely
                # come near each other part company at the cost of an
                # anti-aliased edge, which verify_render measures.
                # Release only whole LETTERS, and only when the letter sits
                # entirely inside one band. A diacritic is small and routinely
                # stands in the gap between lines, so where it lands says very
                # little and cutting it loose from the letters it was clustered
                # with only scatters one word over two line groups. A letter
                # that lies wholly inside another band is not ambiguous at all.
                sub = [group[i] for i in members]
                for part in clusters(sub, 0.0):
                    if not any(sub[k]["y2"] - sub[k]["y1"] >= LETTER_H
                               for k in part):
                        continue
                    lo = min(sub[k]["y1"] for k in part)
                    hi = max(sub[k]["y2"] for k in part)
                    home = band_index(bands, (lo + hi) / 2)
                    t, b = bands[home]
                    if not (lo >= t - 0.01 and hi <= b + 0.01) or home == line:
                        continue
                    for k in part:
                        sub[k]["_free"] = home
                for i in members:
                    c = group[i]
                    own = band_index(bands, (c["y1"] + c["y2"]) / 2)
                    ln = c.pop("_free", line)
                    if own != ln:
                        moved += 1
                    c["line"] = ln
                continue
            for i in members:
                c = group[i]
                own = band_index(bands, (c["y1"] + c["y2"]) / 2)
                if own != line:
                    moved += 1
                c["line"] = line
    return moved


def check(bands, info, contours, expected):
    """Everything that has to hold before a page may be emitted."""
    problems = []
    if len(bands) != expected:
        problems.append("segmented to %d lines, expected %d" % (len(bands), expected))
    worst = max(info["cut_ink"]) if info["cut_ink"] else 0.0
    if worst > MAX_CUT_INK:
        problems.append("a cut runs through ink (%.3f of a line)" % worst)
    if info["band_fill"] < MIN_BAND_FILL:
        problems.append("emptiest line holds %.0f%% of a typical line" % (info["band_fill"] * 100))
    counts = [0] * len(bands)
    for c in contours:
        counts[c["line"]] += 1
    if 0 in counts:
        problems.append("line %d is empty" % (counts.index(0) + 1))

    # The one way a regrouping could change what is drawn: `fill-rule="evenodd"` is
    # evaluated per element, so two contours that overlapped inside one `<path>` cancelled
    # there and would both fill once split apart. This proves that cannot have happened —
    # no two contours that started in the same element and ended on different lines even
    # have touching bounding boxes, which is a strictly weaker condition than overlapping
    # ink. The filled region is therefore identical, not merely similar.
    overlaps = 0
    by_path = {}
    for c in contours:
        by_path.setdefault(c["path"], []).append(c)
    for group in by_path.values():
        order = sorted(group, key=lambda c: c["y1"])
        active = []
        for c in order:
            active = [o for o in active if o["y2"] >= c["y1"]]
            for o in active:
                if o["line"] != c["line"] and o["x1"] <= c["x2"] and c["x1"] <= o["x2"]:
                    overlaps += 1
            active.append(c)
    if overlaps:
        problems.append("%d contour pairs split across lines still overlap" % overlaps)
    return problems, counts


# ---------------------------------------------------------------------------
# Rewriting the SVG
# ---------------------------------------------------------------------------

def build_d(contours):
    """Path data for one line, from contours of one original path, in document order.

    A contour that still follows its original predecessor keeps its source text exactly —
    including its relative `moveto`, whose meaning is unchanged because the current point
    before it is unchanged. A contour that has been separated from its predecessor gets an
    absolute `moveto` instead, since there is no longer a previous point to be relative to.
    """
    parts = []
    prev = None
    for c in contours:
        sp = c["sp"]
        if (prev is None and sp["index"] == 0) or (prev is not None and sp["index"] == prev + 1):
            parts.append(sp["text"])
        else:
            x, y = sp["abs_start"]
            tail = sp["tail"]
            # `m dx dy dx2 dy2` is a moveto followed by an implicit *relative* lineto.
            # Once the moveto is absolute the implicit lineto would turn absolute too, so
            # the elided command letter has to be written back out.
            stripped = tail.lstrip(" ,\t\r\n")
            if stripped and (stripped[0].isdigit() or stripped[0] in "+-."):
                tail = ("l" if sp["text"][0] == "m" else "L") + stripped
            parts.append("M%s %s%s" % (fmt(x), fmt(y), tail))
        prev = sp["index"]
    return "".join(parts)


def rewrite(page, contours, bands):
    """Return the page SVG with `#content` regrouped into one `<g>` per line.

    Line groups sit directly under `#content`, so a page has exactly as many of them as it
    has lines however many paths it was drawn with, and each keeps the `<g transform>`
    wrappers its paths were under. `hafs/017` is drawn with 162 paths and `qalon/440` with
    886; splitting inside each of those would have scattered a single line across hundreds
    of elements.
    """
    per_line = [{} for _ in bands]
    for c in contours:
        per_line[c["line"]].setdefault(c["path"], []).append(c)

    out = []
    for i, group in enumerate(per_line):
        out.append('<g class="line" data-line="%d">' % (i + 1))
        open_chain = ()
        for pi in sorted(group):
            p = page.paths[pi]
            if p["chain"] != open_chain:
                out.append("</g>" * len(open_chain))
                out.append("".join(p["chain"]))
                open_chain = p["chain"]
            a, b = p["d_span"][0] - p["span"][0], p["d_span"][1] - p["span"][0]
            out.append(p["text"][:a] + build_d(group[pi]) + p["text"][b:])
        out.append("</g>" * len(open_chain))
        out.append("</g>")

    start, end = page.content
    return page.svg[:start] + "".join(out) + page.svg[end:]


def unwrap(svg):
    """Strip line groups, returning a page to the shape the upstream generator emits.

    Each `<g class="line">` is removed together with the `</g>` that closes it, leaving
    the contours inside exactly as they are. That is enough for the tool to re-segment and
    re-emit a page it wrote before, which is what makes re-running it idempotent.
    """
    out = []
    i = 0
    drop = []                              # depths at which a line group was opened
    depth = 0
    while True:
        c = svg.find("<", i)
        if c < 0:
            out.append(svg[i:])
            break
        out.append(svg[i:c])
        m = LINE_GROUP_RE.match(svg, c)
        if m:
            drop.append(depth)
            depth += 1
            i = m.end()
            continue
        if svg.startswith("<g", c) and svg[c + 2] in " >\t\r\n":
            depth += 1
        elif svg.startswith("</g>", c):
            depth -= 1
            if drop and drop[-1] == depth:
                drop.pop()
                i = c + 4
                continue
        end = svg.find(">", c)
        if end < 0:
            out.append(svg[c:])
            break
        out.append(svg[c:end + 1])
        i = end + 1
    return "".join(out)


# ---------------------------------------------------------------------------
# lines.json
# ---------------------------------------------------------------------------

def baseline_of(contours):
    """Where the line sits: the y most of its contours rest on.

    Arabic letters sit on a common baseline with a handful of descenders below it, so the
    heaviest cluster of contour bottoms is the baseline. Weighted by contour width, so a
    wide letter counts for more than a dot.
    """
    if not contours:
        return None
    bins = {}
    for c in contours:
        w = max(c["x2"] - c["x1"], 0.01)
        bins[round(c["y2"] * 4)] = bins.get(round(c["y2"] * 4), 0.0) + w
    peak = max(bins, key=bins.get)
    near = [c for c in contours if abs(c["y2"] - peak / 4) <= 0.5]
    total = sum(max(c["x2"] - c["x1"], 0.01) for c in near)
    return sum(c["y2"] * max(c["x2"] - c["x1"], 0.01) for c in near) / total


def lines_json(page, bands, contours):
    vb = page.viewbox or [0, 0, 0, 0]
    per_line = [[] for _ in bands]
    for c in contours:
        per_line[c["line"]].append(c)
    out = []
    for i, (band, group) in enumerate(zip(bands, per_line)):
        vis = [c for c in group if not (c["y2"] < vb[1] - 1 or c["y1"] > vb[1] + vb[3] + 1)]
        box = vis or group
        x1 = min(c["x1"] for c in box)
        x2 = max(c["x2"] for c in box)
        y1 = min(c["y1"] for c in box)
        y2 = max(c["y2"] for c in box)
        entry = {
            "lineNumber": i + 1,
            "x": round(x1, 2),
            "y": round(y1, 2),
            "width": round(x2 - x1, 2),
            "height": round(y2 - y1, 2),
            "top": round(band[0], 2),
            "bottom": round(band[1], 2),
        }
        base = baseline_of(box)
        if base is not None:
            entry["baseline"] = round(base, 2)
        if not vis:
            entry["visible"] = False
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Driving one page
# ---------------------------------------------------------------------------

def plan_for(name, viewbox, body_viewbox):
    """(expected line count, segmentation method, note) for a page."""
    n = page_number(name)
    if viewbox is not None and body_viewbox is not None and viewbox == body_viewbox:
        return BODY_LINES, "grid", None
    if n in OPENING_LINES:
        return OPENING_LINES[n], "valleys", "opening page"
    return None, None, "non-standard viewBox"


def fingerprint(contours):
    """A page's contour geometry, independent of how it is grouped into elements.

    Lets a surah variant be matched against its parent page whether or not the parent has
    already been rewritten, since the rewrite preserves geometry exactly.
    """
    return sorted((round(c["x1"], 6), round(c["y1"], 6), round(c["x2"], 6), round(c["y2"], 6))
                  for c in contours)


def process(job):
    path, body_viewbox, opts, parent_bands = job
    name = os.path.basename(path)
    res = {"file": name}
    try:
        page = Page(path)
        original = unwrap(page.svg)
        if original != page.svg:                 # re-run over already-annotated data
            page = Page(path, svg=original)
            res["rebuilt"] = True
        if page.content is None:
            res["error"] = "no #content group"
            return res
        contours = page.contours()
        res["contours"] = len(contours)
        res["viewBox"] = page.viewbox

        if is_variant(name):
            # A surah variant is the same page under a cropping viewBox — verified
            # byte-identical apart from that attribute — so it inherits the parent's lines
            # and, with them, the parent's line numbering. Segmenting the crop on its own
            # would restart the numbering at 1 partway down the page.
            res["variant_of"] = "%03d.svg" % page_number(name)
            if parent_bands is None:
                res["error"] = "parent page has no accepted segmentation"
                return res
            bands, info, ref = parent_bands
            if fingerprint(contours) != ref:
                res["error"] = "variant content differs from its parent page"
                return res
            expected, method, err = len(bands), "parent", None
        else:
            expected, method, note = plan_for(name, page.viewbox, body_viewbox)
            if expected is None:
                res["skipped"] = note
                return res
            if note:
                res["note"] = note
            bands, info, err = segment_page(page, contours, expected, method)

        if err:
            res["error"] = err
            return res
        res["lines"] = len(bands)
        res["method"] = method
        res["pitch"] = round(info.get("pitch", 0), 3)
        res["max_cut_ink"] = round(max(info["cut_ink"]), 5)
        res["band_fill"] = round(info["band_fill"], 3)

        res["moved_to_neighbour"] = assign(contours, bands)
        problems, counts = check(bands, info, contours, expected)
        if problems:
            res["error"] = "; ".join(problems)
            return res
        res["per_line"] = counts

        if not opts["check"]:
            new_svg = rewrite(page, contours, bands)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new_svg)
            res["bytes_added"] = len(new_svg) - len(original)
            jdir = os.path.join(os.path.dirname(os.path.dirname(path)), "lines")
            os.makedirs(jdir, exist_ok=True)
            jpath = os.path.join(jdir, os.path.splitext(name)[0] + ".json")
            with open(jpath, "w", encoding="utf-8") as fh:
                json.dump(lines_json(page, bands, contours), fh, ensure_ascii=False)
        if not is_variant(name):
            res["bands"] = (bands, info, fingerprint(contours))
        return res
    except Exception as exc:                                     # noqa: BLE001
        import traceback
        res["error"] = "%s: %s" % (type(exc).__name__, exc)
        res["traceback"] = traceback.format_exc()[-800:]
        return res


def body_viewbox_of(svg_dir):
    """The viewBox shared by the edition's body pages, read rather than assumed.

    Warsh and Qalun start at x = -6 and every mushaf has its own page height, so nothing
    about the page box can be hard-coded.
    """
    seen = {}
    for name in sorted(os.listdir(svg_dir)):
        if not re.match(r"^\d+\.svg$", name):
            continue
        with open(os.path.join(svg_dir, name), encoding="utf-8") as fh:
            head = fh.read(600)
        m = re.search(r'viewBox="([^"]*)"', head)
        if m:
            vb = tuple(float(x) for x in m.group(1).split())
            seen[vb] = seen.get(vb, 0) + 1
    if not seen:
        return None
    return list(max(seen, key=seen.get))


def editions(selector=None):
    for qiraa in sorted(os.listdir(ROOT)):
        qdir = os.path.join(ROOT, qiraa)
        if not os.path.isdir(qdir):
            continue
        for pub in sorted(os.listdir(qdir)):
            svg_dir = os.path.join(qdir, pub, "svg")
            if not os.path.isdir(svg_dir):
                continue
            if selector and selector not in ("%s/%s" % (qiraa, pub)):
                continue
            yield "%s/%s" % (qiraa, pub), svg_dir


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mushaf", help="restrict to one edition, e.g. hafs/kfqc")
    ap.add_argument("--pages", help="comma-separated page numbers")
    ap.add_argument("--check", action="store_true", help="validate only, write nothing")
    ap.add_argument("--no-brotli", action="store_true", help="do not refresh svg-br/")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--report", help="write the full per-page report as JSON")
    args = ap.parse_args(argv)

    wanted = set(args.pages.split(",")) if args.pages else None
    opts = {"check": args.check}
    failed = 0
    report = {}

    for edition, svg_dir in editions(args.mushaf):
        body_vb = body_viewbox_of(svg_dir)
        names = sorted(n for n in os.listdir(svg_dir) if n.endswith(".svg"))
        if wanted:
            names = [n for n in names if str(page_number(n)) in wanted]
        # Whole pages first, then the surah variants — a variant inherits its parent's
        # lines, so the parent has to have passed before the variant is looked at, and it
        # must not be read off disk while another worker is rewriting it.
        whole = [n for n in names if not is_variant(n)]
        variants = [n for n in names if is_variant(n)]
        with Pool(args.jobs) as pool:
            results = pool.map(process, [(os.path.join(svg_dir, n), body_vb, opts, None)
                                         for n in whole])
        bands_by_page = {page_number(r["file"]): r.pop("bands")
                         for r in results if "bands" in r}
        if variants:
            with Pool(args.jobs) as pool:
                results += pool.map(process, [
                    (os.path.join(svg_dir, n), body_vb, opts,
                     bands_by_page.get(page_number(n))) for n in variants])
        results.sort(key=lambda r: r["file"])
        report[edition] = results

        ok = [r for r in results if "error" not in r and "skipped" not in r]
        bad = [r for r in results if "error" in r]
        skipped = [r for r in results if "skipped" in r]
        body = [r for r in ok if r.get("lines") == BODY_LINES and "note" not in r]
        print("%-14s body viewBox %s" % (edition, body_vb))
        print("   %d pages: %d segmented (%d at %d lines), %d exceptions, %d failed"
              % (len(results), len(ok), len(body), BODY_LINES,
                 len(ok) - len(body), len(bad)))
        if ok:
            print("   worst cut through ink: %.4f of a line   emptiest line: %.2f"
                  % (max(r["max_cut_ink"] for r in ok), min(r["band_fill"] for r in ok)))
        for r in [x for x in ok if "note" in x]:
            print("   exception  %-18s %d lines (%s)" % (r["file"], r["lines"], r["note"]))
        for r in skipped:
            print("   skipped    %-18s %s" % (r["file"], r["skipped"]))
        for r in bad:
            print("   FAILED     %-18s %s" % (r["file"], r["error"]))
        failed += len(bad)

        if not args.check and not args.no_brotli:
            refresh_brotli(os.path.dirname(svg_dir), [r["file"] for r in ok], args.jobs)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)
    return 1 if failed else 0


def _compress(job):
    src, dst = job
    import brotli
    with open(src, "rb") as fh:
        raw = fh.read()
    # quality 11 with the default window, which is what the existing .br files were
    # written with — recompressing an untouched page reproduces it byte for byte.
    data = brotli.compress(raw, quality=11)
    # Written to a temporary neighbour and renamed, never in place. Quality 11 over three
    # thousand pages takes long enough that a run *will* be interrupted eventually, and
    # writing in place turns that into a truncated `.br` that fails to decompress at all —
    # a reader gets a decoder error rather than a page. Measured after one interrupted run:
    # 38 of 604 hafs files were unreadable. `os.replace` is atomic on the same filesystem,
    # so an interrupted run now leaves the previous file intact.
    tmp = dst + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, dst)


def refresh_brotli(edition_dir, names, jobs):
    br_dir = os.path.join(edition_dir, "svg-br")
    if not os.path.isdir(br_dir):
        return
    work = [(os.path.join(edition_dir, "svg", n), os.path.join(br_dir, n + ".br"))
            for n in names]
    with Pool(jobs) as pool:
        pool.map(_compress, work)
    print("   refreshed %d Brotli copies" % len(work))


if __name__ == "__main__":
    sys.exit(main())
