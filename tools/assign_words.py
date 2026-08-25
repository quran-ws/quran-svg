#!/usr/bin/env python3
"""Assign each ink element to its word, producing MushafDatabase-style word groups.

Pipeline stage 2, after split_line_elements.py. For every line the verified word list
(quran.com v4, KFGQPC layout) says how many words the line holds and what each one reads;
the elements on the line are clustered into exactly that many words by cutting at the
widest inter-element gaps. Because all KFGQPC prints share the same words per line across
qiraat, one Hafs layout drives every edition; the uthmani/imlaei strings attached are the
Hafs forms and per-riwayah spellings can be swapped in later without touching geometry.

Every line gets a confidence record: the margin between the cut gaps and the widest gap
kept inside a word, plus sanity flags (a word made only of floating marks, a count
mismatch, a line the source has no words for). Low-margin or flagged lines are the manual
review queue; the rest are safe automatic assignments.

    tools/assign_words.py hafs/kfqc 3                 # one page -> svg + report
    tools/assign_words.py hafs/kfqc 3 --words-cache DIR --out-dir DIR
"""

import argparse
import json
import math
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from page import Page
from svg_lines import transform_box
from split_line_elements import group_elements, PATH_RE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = ("https://api.quran.com/api/v4/verses/by_page/%d?words=true&mushaf=2"
       "&word_fields=line_number,text_uthmani,text_imlaei&per_page=50")


# ---------------------------------------------------------------------------
# Verified word list per line (never hand-typed; cached verbatim from the API)
# ---------------------------------------------------------------------------

def page_words(page_no, cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, "page-%03d.json" % page_no)
    if os.path.exists(cache):
        data = json.load(open(cache, encoding="utf-8"))
    else:
        req = urllib.request.Request(API % page_no,
                                     headers={"User-Agent": "quran-svg-tools/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        json.dump(data, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    # The art is the KFGQPC madani print, which the QCF v2 page fonts replicate
    # line-for-line; quran.com's own line numbers drift from it on some pages
    # (p4: end-of-line word wrapped). Prefer the QCF layout when we have it.
    qcf_lines = _qcf_lines().get(str(page_no), {})

    # The QCF layout is normally the better of the two, but on a few pages it
    # is self-contradictory: p599 puts 100:6 on line 1 while surah 100 does not
    # begin until line 14, so a word sits above its own surah's opening. Text
    # runs one way down a page, and a layout that runs backwards cannot be
    # right. Where it does, fall back to the line numbers that came with the
    # words. 22 pages are affected, 12 of them in juz 30, where the short
    # surahs put a page break in the middle of almost every one.
    def _monotonic(pick):
        first = {}
        for verse in data["verses"]:
            s0, a0 = (int(x) for x in verse["verse_key"].split(":"))
            for w in verse["words"]:
                if w["char_type_name"] != "word":
                    continue
                ln = pick(verse["verse_key"], w)
                if ln is None:
                    continue
                key = (s0, a0, w["position"])
                if ln not in first or key < first[ln]:
                    first[ln] = key
        seq = [first[ln] for ln in sorted(first)]
        return all(seq[i] <= seq[i + 1] for i in range(len(seq) - 1))

    use_qcf = bool(qcf_lines) and _monotonic(
        lambda vk, w: qcf_lines.get("%s:%s" % (vk, w["position"])))
    if qcf_lines and not use_qcf and _QCF_WARN is not None:
        _QCF_WARN.add(page_no)

    lines = {}
    for verse in data["verses"]:
        surah, ayah = verse["verse_key"].split(":")
        for w in verse["words"]:
            if w["char_type_name"] != "word":     # 'end' = medallion, kept out of #content
                continue
            ln = (qcf_lines.get("%s:%s" % (verse["verse_key"], w["position"]),
                                w["line_number"]) if use_qcf
                  else w["line_number"])
            lines.setdefault(ln, []).append({
                "surah": int(surah), "ayah": int(ayah), "pos": w["position"],
                "uthmani": w["text_uthmani"], "imlaei": w["text_imlaei"],
            })
    return lines


_QCF_LINES = None


_QCF_WARN = set()


def _qcf_lines():
    global _QCF_LINES
    if _QCF_LINES is None:
        p = os.path.join(ROOT, ".cache", "qcf_lines.json")
        _QCF_LINES = json.load(open(p)) if os.path.exists(p) else {}
    return _QCF_LINES


# ---------------------------------------------------------------------------
# Elements with page-space geometry, grouped by line
# ---------------------------------------------------------------------------

def line_of(chain):
    for tag in chain:
        m = re.search(r'data-line="(\d+)"', tag)
        if m:
            return int(m.group(1))
    return None


def page_elements(page):
    """[(line, path_index, element contours, page-space bbox)] for all glyph paths.

    Ink wholly outside the viewBox is invisible (the renderer clips to it); the
    ornate opening spreads carry off-canvas leftovers that must never join words.
    """
    vb = re.search(r'viewBox="([\d.eE+-]+)[,\s]+([\d.eE+-]+)[ ,\s]+([\d.eE+-]+)'
                   r'[ ,\s]+([\d.eE+-]+)"', page.svg)
    if vb:
        vx, vy, vw, vh = (float(g) for g in vb.groups())
        vlim = (vx, vy, vx + vw, vy + vh)
    else:
        vlim = None
    out = []
    for pi, p in enumerate(page.paths):
        if "ayahPolygon" in p["text"]:
            continue
        ln = line_of(p["chain"])
        for el in group_elements(p["d"]):
            xs, ys = [], []
            for c in el:
                sp = c["sp"]
                x1, y1, x2, y2 = transform_box(p["M"], sp["xmin"], sp["ymin"],
                                               sp["xmax"], sp["ymax"])
                xs += [x1, x2]
                ys += [y1, y2]
            bx1, bx2, by1, by2 = min(xs), max(xs), min(ys), max(ys)
            off = bool(vlim and (bx2 < vlim[0] or by2 < vlim[1]
                                 or bx1 > vlim[2] or by1 > vlim[3]))
            out.append({"line": ln, "path": pi, "contours": el, "offcanvas": off,
                        "x1": bx1, "x2": bx2, "y1": by1, "y2": by2})
    return out


# Shapes whose normalised outline has a letter twin (a dagger-alef looks like a full
# alef once scale is removed) may only force-mark when the drawn size fits the mark.
# Marks this art never draws below their letter (fatha/kasra and the dot family
# are two-sided and stay unrestricted).
_ABOVE_ONLY = {"damma", "dammatan", "pause", "sukun", "shadda", "small-circle",
               "meem-iqlab", "small-waw", "small-alef", "maddah", "wasla"}

_DUAL_SIZE_CAP = {"small-alef": 12.0, "small-waw": 8.0, "small-ya": 9.5,
                  "pause": 9.5, "sukun": 4.8, "wasla": 6.5, "shadda": 8.5,
                  "small-circle": 4.8, "dot": 4.0, "meem-iqlab": 6.0, "letter-part": 11.5,
                  "fatha": 12.0, "kasra": 12.0, "fathatan": 12.0, "kasratan": 12.0}


def classify(elements, lines_info, part_key=None, mark_shapes=None):
    """Tag each element body/mark: known mark shapes first, then baseline geometry.

    Shape identity outranks position — a damma hovering low over a flat letter dips
    into the baseline zone, and a dagger-alef is taller than the height ceiling, but
    both ARE marks and their outlines are in the confirmed shape table. Geometry
    decides only what the table does not know: letter bodies stand on the baseline
    (a standalone ء included — this art draws it baseline-height, so it is a body),
    and a letter raised in a stacked composition is tall where no unknown mark is.
    """
    info = {li["lineNumber"]: li for li in lines_info}
    hs = sorted((li.get("height") or (li["bottom"] - li["top"]))
                for li in lines_info) if lines_info else []
    med_h = hs[len(hs) // 2] if hs else None
    for e in elements:
        li = info.get(e["line"])
        if li is None:
            e["kind"] = "body"
            continue
        if mark_shapes and part_key:
            lab = mark_shapes.get(part_key(e))
            if lab:
                e["lab"] = lab            # remembered for position/attachment rules
            if lab in ("letter-hamza", "letter", "letter-part"):
                # letter ink — whole letters (ر د و ا…) and detached pieces (the
                # ك armature) both cluster into words as bodies; as marks they
                # could re-line onto a neighbouring line's word.
                e["kind"] = "body"
                continue
            if lab:
                cap = _DUAL_SIZE_CAP.get(lab)
                size = max(e["x2"] - e["x1"], e["y2"] - e["y1"])
                # the sukun of this script is an OPEN curve: a ringed twin is a
                # letter ه/ة, never a sukun
                # the sukun of this script is an OPEN curve: a ringed twin is a
                # letter ه/ة, never a sukun; likewise the dot family is solid —
                # a contour nested inside another is a ring (a ة head), not dots
                ok = not (lab == "sukun" and len(e["contours"]) > 1)
                if ok and lab in ("dot", "two-dots", "three-dots") \
                        and len(e["contours"]) > 1:
                    bbs = [c["sp"] for c in e["contours"]]
                    for i2, a2 in enumerate(bbs):
                        for b2 in bbs[i2 + 1:]:
                            if (a2["xmin"] <= b2["xmin"] and a2["xmax"] >= b2["xmax"]
                                    and a2["ymin"] <= b2["ymin"]
                                    and a2["ymax"] >= b2["ymax"]) or \
                               (b2["xmin"] <= a2["xmin"] and b2["xmax"] >= a2["xmax"]
                                    and b2["ymin"] <= a2["ymin"]
                                    and b2["ymax"] >= a2["ymax"]):
                                ok = False
                if ok and (cap is None or size <= cap):
                    e["kind"] = "mark"
                    continue
        size = max(e["x2"] - e["x1"], e["y2"] - e["y1"])
        _bh = e["y2"] - e["y1"]
        _bw = e["x2"] - e["x1"]
        # the sajdah overline is a hairline: its length varies with the words
        # it spans, its height barely at all — so recognise it by that ratio
        # rather than by an absolute length, and a short one still qualifies
        if _bh < 2.5 and _bw > 9.0 and _bw > 8.0 * max(_bh, 0.35):
            e["kind"] = "mark"
            e["lab"] = "sajdah"
            continue
        if size < 4.6:
            e["kind"] = "mark"            # no letter is this small; petals/dots are
            continue
        if size > 12.5:
            e["kind"] = "body"            # larger than every mark in this art
            continue
        # the line's "height" field is a padded art box; the band between top
        # and bottom is the geometric truth, and the smaller of the two keeps
        # a short baseline-hugging letter (a final meem) from being read as a
        # mark on pages whose padding runs wide
        h = min(li.get("height") or 1e9, li["bottom"] - li["top"])
        if med_h and h > 1.6 * med_h:
            h = med_h                     # merged/outlier band breaks the ratios
        base = li["baseline"]
        on_baseline = e["y2"] >= base - 0.18 * h and e["y1"] <= base - 0.20 * h
        tall = (e["y2"] - e["y1"]) > 0.22 * h
        e["kind"] = "body" if on_baseline or tall else "mark"


def composite_marks(elements, part_key=None, known=None):
    """Group mark elements drawn as one logical sign — the waqf ج is a ح curl plus a
    dot, small قلے/صلے are several strokes, a damma head and its tail. Members stack:
    x-ranges overlap and they touch or nearly touch. Two parts that EACH match an
    already-labeled single shape never merge — a fatha dipping onto a hamza is two
    marks, and the shape table knows both; a glyph's own fragments match nothing on
    their own and are free to rejoin. The largest member becomes the primary; the
    others point back to it and never count or label on their own.
    """
    known = known or {}
    DOTFAM = {"dot", "two-dots", "three-dots"}

    def label_of(e):
        return known.get(part_key(e)) if part_key is not None else None

    for ln in {e["line"] for e in elements}:
        marks = [e for e in elements
                 if e["line"] == ln and e["kind"] == "mark"]
        marks.sort(key=lambda e: e["x1"])
        parent = list(range(len(marks)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        # Radial ornaments first: the hizb rosette ۞ is many tiny petals packed
        # into one small box; x-overlap chaining misses the radial arrangement, and
        # larger petal pairs can pass the baseline test — recruit any small piece.
        def tiny(x):
            return max(x["x2"] - x["x1"], x["y2"] - x["y1"]) < 3.2

        for e in elements:
            if e["line"] != ln or e["kind"] != "body" or not tiny(e):
                continue
            near = [x for x in elements if x["line"] == ln and x is not e
                    and tiny(x)
                    and abs((x["x1"] + x["x2"]) / 2 - (e["x1"] + e["x2"]) / 2) < 6
                    and abs((x["y1"] + x["y2"]) / 2 - (e["y1"] + e["y2"]) / 2) < 6]
            if len(near) >= 4:
                e["kind"] = "mark"
        marks = [x for x in elements if x["line"] == ln and x["kind"] == "mark"]
        marks.sort(key=lambda x: x["x1"])
        parent = list(range(len(marks)))
        used = set()
        pp = list(range(len(marks)))

        def pfind(i):
            while pp[i] != i:
                pp[i] = pp[pp[i]]
                i = pp[i]
            return i

        for i in range(len(marks)):
            for j in range(i + 1, len(marks)):
                a, b = marks[i], marks[j]
                if b["x1"] > a["x2"] + 1.4:
                    break
                if not (tiny(a) and tiny(b)):
                    continue              # only rosette-sized petals join radially
                gx = max(a["x1"], b["x1"]) - min(a["x2"], b["x2"])
                gy = max(a["y1"], b["y1"]) - min(a["y2"], b["y2"])
                if gx <= 1.3 and gy <= 1.3:
                    pp[pfind(j)] = pfind(i)
        rad = {}
        for i in range(len(marks)):
            rad.setdefault(pfind(i), []).append(i)
        for idxs in rad.values():
            if len(idxs) < 4:
                continue
            xs1 = min(marks[i]["x1"] for i in idxs)
            xs2 = max(marks[i]["x2"] for i in idxs)
            ys1 = min(marks[i]["y1"] for i in idxs)
            ys2 = max(marks[i]["y2"] for i in idxs)
            w0, h0 = xs2 - xs1, ys2 - ys1
            if w0 > 10 or h0 > 10 or len(idxs) < 5 \
                    or not 0.7 <= (w0 / max(h0, 1e-9)) <= 1.4:
                continue                  # rosettes are compact and square-ish
            mem = sorted((marks[i] for i in idxs),
                         key=lambda e: -(e["x2"] - e["x1"]) * (e["y2"] - e["y1"]))
            mem[0]["mkmembers"] = mem[1:]
            for e in mem[1:]:
                e["mkpart"] = True
            used.update(idxs)

        for i in range(len(marks)):
            if i in used:
                continue
            for j in range(i + 1, len(marks)):
                if j in used:
                    continue
                a, b = marks[i], marks[j]
                if b["x1"] > a["x2"] + 0.3:
                    break
                ov = min(a["x2"], b["x2"]) - max(a["x1"], b["x1"])
                if ov < 0.4 * min(a["x2"] - a["x1"], b["x2"] - b["x1"]):
                    continue
                vgap = max(a["y1"], b["y1"]) - min(a["y2"], b["y2"])
                # a waqf letter's dot can hang below its curl (ج): a tiny piece
                # centred within a larger unlabeled piece joins across a bigger gap
                small, big = (a, b) if (a["x2"] - a["x1"]) < (b["x2"] - b["x1"]) else (b, a)
                nested_dot = (max(small["x2"] - small["x1"],
                                  small["y2"] - small["y1"]) < 3.2
                              and big["x1"] - 0.3 <= (small["x1"] + small["x2"]) / 2
                              <= big["x2"] + 0.3)
                if vgap > (2.2 if nested_dot else 0.8):
                    continue
                la, lb = label_of(a), label_of(b)
                # a slash is a complete mark on its own: it never welds into a
                # larger unknown piece (the ء of إ under a kasra) — only true
                # fragments (a damma's tail, a waqf curl) rejoin the unknown
                SLASH = ("fatha", "kasra", "fathatan", "kasratan")
                if ((la in SLASH and not lb and not nested_dot)
                        or (lb in SLASH and not la and not nested_dot)):
                    continue
                if la and lb:
                    dx = abs((a["x1"] + a["x2"]) / 2 - (b["x1"] + b["x2"]) / 2)
                    tight = dx < 2.5 and vgap <= 0.6
                    dots_pair = la in DOTFAM and lb in DOTFAM and tight
                    # a waqf letter owns its dot: ج = pause curl + nested dot
                    waqf_dot = (nested_dot and "pause" in (la, lb)
                                and (la in DOTFAM or lb in DOTFAM))
                    pause_pair = la == lb == "pause" and vgap <= 2.2
                    if not (dots_pair or waqf_dot or pause_pair):
                        continue         # two complete marks stacked, not one glyph
                parent[find(j)] = find(i)

        groups = {}
        for i, e in enumerate(marks):
            if i in used:
                continue                  # radial composites keep their grouping
            groups.setdefault(find(i), []).append(e)
        for members in groups.values():
            members.sort(key=lambda e: -(e["x2"] - e["x1"]) * (e["y2"] - e["y1"]))
            primary = members[0]
            primary["mkmembers"] = members[1:]
            for e in members[1:]:
                e["mkpart"] = True


# ---------------------------------------------------------------------------
# Clustering: exactly N words per line, cut at the N-1 widest gaps
# ---------------------------------------------------------------------------

_LETTER = re.compile(r"[ء-غف-يٱ-ۓ]")

# Relative drawn widths (em-ish) of skeleton letters in this script; 1.0 = a tooth.
WIDTH = {"ا": 0.4, "أ": 0.4, "إ": 0.4, "آ": 0.5, "ٱ": 0.4, "ء": 0.5,
         "ر": 0.8, "ز": 0.8, "د": 0.8, "ذ": 0.8, "و": 0.8, "ؤ": 0.8,
         "ب": 1.4, "ت": 1.4, "ث": 1.4, "ن": 1.1, "ي": 1.2, "ئ": 1.0, "ى": 1.2,
         "س": 1.7, "ش": 1.7, "ص": 1.8, "ض": 1.8, "ك": 1.4, "ل": 0.9,
         "م": 1.0, "ه": 1.0, "ة": 1.0, "ف": 1.3, "ق": 1.3}


_CAL = None


def _calibrated():
    """Per-(letter, position) widths learned from the mushaf by calibrate_widths.py."""
    global _CAL
    if _CAL is None:
        p = os.path.join(ROOT, ".cache", "letter-widths.json")
        _CAL = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    return _CAL


def letter_widths_list(text):
    """Expected drawn width of each letter of one connected piece, right to left."""
    cal = _calibrated()
    n = len(text)
    out = []
    for i, ch in enumerate(text):
        pos = ("isolated" if n == 1 else "initial" if i == 0 else
               "final" if i == n - 1 else "medial")
        e = cal.get(ch, {})
        got = e.get(pos) or e.get("medial") or e.get("initial") or e.get("final") \
            or e.get("isolated")
        if got and got["samples"] >= 3:
            out.append(got["width"])
        else:
            out.append(WIDTH.get(ch, 1.0) * 8.0)   # hand table, scaled to page units
    return out


def letter_width(text):
    return sum(letter_widths_list(text)) or 3.0


_QCF = None


def qcf_widths():
    """Per-word advance widths from the QCF v2 page fonts — the print's own metrics."""
    global _QCF
    if _QCF is None:
        p = os.path.join(ROOT, ".cache", "qcf_widths.json")
        _QCF = json.load(open(p)) if os.path.exists(p) else {}
    return _QCF


_QCF_SUSPECT = [False]


def letters(word):
    """Expected drawn width of a word: the QCF font's own advance when known
    (scaled to roughly page units), else the calibrated letter sum."""
    q = qcf_widths().get("%d:%d:%d" % (word["surah"], word["ayah"], word["pos"]))
    # a hizb-quarter word's QCF advance includes the ۞ ornament glyph, which this
    # art draws separately — the inflated width would make the word steal atoms
    ls = sum(letter_width(s["text"]) for s in segment_word(word["uthmani"])) or 3.0
    if q and not any(m in word["uthmani"] for m in "۞۩") \
            and os.environ.get("QSVG_QCF", "1") == "1":
        est = q * 19.5                    # em -> page units (alpha absorbs residual)
        # a handful of cached advances are corrupt (page-boundary drift pages
        # pair glyphs with the wrong words: لا wider than يموت). A real QCF
        # advance tracks the letter-sum estimate; an implausible ratio means
        # the advance belongs to some other word — use the calibrated sum.
        if not _QCF_SUSPECT[0] or 0.5 * ls <= est <= 1.45 * ls:
            return est
    return ls


_RECT = re.compile(r"M ([\d.]+) ([\d.]+) L ([\d.]+) [\d.]+ L [\d.]+ ([\d.]+)")


def ayah_ranges_per_line(polys_json, lines_info):
    """{line: {(surah, ayah): (x1, x2)}} from the per-page ayah polygons.

    Each polygon is a stack of per-line rectangles, so the x-extent of an ayah on a
    given line is a hard boundary no word of that ayah may cross.
    """
    out = {}
    for p in polys_json:
        key = (p["surahNumber"], p["ayahNumber"])
        for m in _RECT.finditer(p.get("polygon", "")):
            x1, y1, x2, y2 = (float(m.group(1)), float(m.group(2)),
                              float(m.group(3)), float(m.group(4)))
            if abs(y2 - y1) < 8:
                continue                      # separator/boundary strip, not a band
            # A rect may cover ONE line (per-line rows) or SEVERAL at once
            # (a generator that merges consecutive full-width lines into a
            # single rectangle). Both describe the same region, so credit every
            # band the rect substantially covers — matching on the rect's own
            # height alone silently drops the merged form.
            for li in lines_info:
                band = max(1e-6, li["bottom"] - li["top"])
                ov = min(y2, li["bottom"]) - max(y1, li["top"])
                if ov > 0.5 * min(band, y2 - y1):
                    r = out.setdefault(li["lineNumber"], {}).get(key)
                    lo, hi = min(x1, x2), max(x1, x2)
                    out[li["lineNumber"]][key] = ((min(r[0], lo), max(r[1], hi))
                                                  if r else (lo, hi))
    # A stale rect doubles an ayah onto the NEXT line with the SAME x-span it
    # had above (p592 line 8 "held" 88:1-2 over 88:3-6; p585 line 4 held
    # 80:1-3). A genuine continuation has a different span there — keep those,
    # drop only the identical copies.
    lns = sorted(out)
    for i in range(1, len(lns)):
        d, prev = out[lns[i]], out[lns[i - 1]]
        dups = [k for k in d if k in prev
                and abs(d[k][0] - prev[k][0]) < 2.0
                and abs(d[k][1] - prev[k][1]) < 2.0]
        for k in dups:
            # an ayah filling consecutive FULL lines repeats its span
            # legitimately; a stale copy betrays itself by colliding with
            # the line's own (non-duplicated) ayahs
            lo, hi = d[k]
            clash = any(min(hi, d[k2][1]) - max(lo, d[k2][0])
                        > 0.3 * min(hi - lo, d[k2][1] - d[k2][0])
                        for k2 in d if k2 not in dups and k2 != k)
            if clash:
                del d[k]
    return out


_W_WIDTH = float(__import__("os").environ.get("QSVG_WW", "0.3"))
_W_DOTS = float(__import__("os").environ.get("QSVG_WD", "2.40"))
_SEG_GAP = float(__import__("os").environ.get("QSVG_SEGGAP", "6.0"))
_DOT_REACH = float(__import__("os").environ.get("QSVG_DOTREACH", "3.0"))
_DOT_SCORE = float(__import__("os").environ.get("QSVG_DOTSCORE", "0.25"))
_W_SURPLUS = float(__import__("os").environ.get("QSVG_WSURP", "0.6"))


def cluster_line(els, words, ayah_ranges=None, alpha_scale=1.0,
                 use_dots=True):
    """Split a line's elements into one cluster per word, right to left.

    Elements are first merged into atoms wherever their x-intervals overlap — a mark
    above its letters can never be cut away from them. Atoms are then partitioned into
    consecutive runs by dynamic programming: each word's span should be about its letter
    count times the line's per-letter width. Gap size alone fails on justified lines —
    a kashida-stretched word holds gaps wider than the space before a short word like
    أم — but stretched words are exactly the ones the width prior expects to be wide.

    Returns (clusters, deviation): deviation is the worst |span − expected| relative to
    the line's mean word width; small = trustworthy, large = manual-review queue.
    """
    bodies = [e for e in els if e["kind"] == "body"]
    marks = [e for e in els if e["kind"] != "body"]
    if not bodies:
        bodies, marks = els, []
    # a letter fragment (the ك armature stroke) is drawn stacked over its base
    # letter: it joins that letter's atom instead of standing alone, where the
    # boundary search could hand it to the neighbouring word
    def armature(b):
        # the ك upper stroke: small, wider than tall-thin, drawn OVER its base —
        # a detached alef or a big letter chunk must keep its own atom
        w = b["x2"] - b["x1"]; h = b["y2"] - b["y1"]
        return max(w, h) <= 9.0 and h < 3.0 * w
    frags = [b for b in bodies if b.get("lab") == "letter-part" and armature(b)]
    bases = [b for b in bodies if b not in frags] or bodies
    atoms = [{"x1": b["x1"], "x2": b["x2"], "els": [b]} for b in bases]
    for f in frags:
        if f in bases:
            continue
        def ov(a):
            return min(a["x2"], f["x2"]) - max(a["x1"], f["x1"])
        fc = (f["x1"] + f["x2"]) / 2
        cands = [a for a in atoms
                 if ov(a) >= 0.5 * (f["x2"] - f["x1"])
                 and f["y2"] <= max(e["y2"] for e in a["els"]) + 1.0]
        if cands:
            # the ك stroke floats INSIDE its bowl: the atom whose span contains
            # the fragment's centre wins over a mere edge overlap
            best = max(cands, key=lambda a: (a["x1"] <= fc <= a["x2"], ov(a)))
            best["els"].append(f)
            best["x1"] = min(best["x1"], f["x1"])
            best["x2"] = max(best["x2"], f["x2"])
        else:
            atoms.append({"x1": f["x1"], "x2": f["x2"], "els": [f]})
    for mk in marks:
        if mk.get("mkpart"):
            continue                     # follows its composite's primary below
        cx = (mk["x1"] + mk["x2"]) / 2

        def fit(a):
            # overlap with the body's span first, then sheer distance
            ov = min(a["x2"], mk["x2"]) - max(a["x1"], mk["x1"])
            return (-ov, abs((a["x1"] + a["x2"]) / 2 - cx))

        best = min(atoms, key=fit)
        best["els"].append(mk)
        best["els"].extend(mk.get("mkmembers", []))
    # a SMALL body atom sitting mostly inside a wider atom's span is a stacked
    # stroke of the same ligature (the second stroke of a lam-alef, a broken
    # letter piece) — the boundary search must not be able to separate them
    atoms.sort(key=lambda a: a["x2"] - a["x1"])
    merged_away = set()
    for i, sm in enumerate(atoms):
        wsm = sm["x2"] - sm["x1"]
        if wsm > 13.0 or id(sm) in merged_away:
            continue
        for big in atoms[i + 1:]:
            if id(big) in merged_away:
                continue
            wb = big["x2"] - big["x1"]
            if wb < 1.3 * wsm:
                continue
            ov = min(sm["x2"], big["x2"]) - max(sm["x1"], big["x1"])
            # stacked strokes sit ABOVE the base (lam-alef's second stroke, the
            # ك armature); a neighbour's final letter merely OVERLAPS sideways
            sm_cy = sum((e["y1"] + e["y2"]) / 2 for e in sm["els"]) / len(sm["els"])
            big_cy = sum((e["y1"] + e["y2"]) / 2 for e in big["els"]) / len(big["els"])
            # ... and INTERIOR to its span: a neighbour's standalone alef over
            # this word's sweeping tail rides the extreme edge, while a piece
            # of the letter itself (the silent alef of ـوا۟ over its waw) sits
            # well inside it. Measure that clearance RELATIVE to the letter's
            # own width — an absolute one cannot separate a 1.5u overhang on a
            # 15u sweep from a 2.45u inset on a 10u waw.
            sm_cx = (sm["x1"] + sm["x2"]) / 2
            edge = min(abs(sm_cx - big["x1"]), abs(sm_cx - big["x2"]))
            if ov >= 0.6 * wsm and sm_cy < big_cy - 1.5 \
                    and edge > max(1.2, 0.18 * wb):
                big["els"].extend(sm["els"])
                big["x1"] = min(big["x1"], sm["x1"])
                big["x2"] = max(big["x2"], sm["x2"])
                merged_away.add(id(sm))
                break
    atoms = [a for a in atoms if id(a) not in merged_away]

    n = len(words)
    if n <= 0 or not atoms:
        return [[a] for a in atoms], 0.0
    if len(atoms) < n:
        return [[a] for a in atoms], float("inf")

    atoms.sort(key=lambda a: -(a["x1"] + a["x2"]))   # rightmost first = reading order
    m = len(atoms)
    lens = [letters(w) for w in words]
    span_total = atoms[0]["x2"] - atoms[-1]["x1"]
    alpha = span_total / sum(lens) * alpha_scale

    def width(i, j):                      # atoms i..j inclusive, RTL order
        return atoms[i]["x2"] - atoms[j]["x1"]

    # Gap before atom j in reading order — the space between it and its right neighbour.
    gap = [0.0] + [max(0.0, atoms[i - 1]["x1"] - atoms[i]["x2"]) for i in range(1, m)]

    # The cost of giving a word an atom run is how badly those atoms align to the
    # word's own expected letter structure (align_segs_atoms) — so the boundary search
    # knows that ءأنذرتهم expects a tiny floating ء at its right edge and عليهم expects
    # none. A real inter-word space still earns a reward, so a true boundary can pay
    # for a slightly worse width fit without splitting kashida-stretched words.
    GAP_REWARD = 1.0
    all_segs = [segment_word(w["uthmani"]) for w in words]
    # two width systems: word-level lens may be QCF-font based, but the letter
    # alignment works in calibrated letter units — give it its own absolute alpha
    cal_total = sum(letter_width(sg["text"]) for segs in all_segs for sg in segs)
    alpha_cal = span_total / max(1e-9, cal_total)
    n_letters = sum(len("".join(_LETTER.findall(w["uthmani"]))) for w in words) or 1
    mean_letter = span_total / n_letters       # scale-free gap normalisation

    # The skeleton fixes how many DOT units a word owns — a signal the split
    # search had been ignoring, though it is often the only thing that says
    # where one word ends: ٱلْمُحْصَنَـٰتِ (3) absorbing ثُمَّ (3) reads as 6.
    _DOTU_C = {"dot": 1, "two-dots": 2, "three-dots": 3}

    def _dots_of_word(w6):
        raw = _LETTER.findall(w6["uthmani"])
        sk = [(HAMZA_MAP[c][0] if c in HAMZA_MAP else c, c in HAMZA_MAP)
              for c in raw]
        t = 0
        for i6, (ch, seat) in enumerate(sk):
            if seat or ch not in DOTS:
                continue
            if ch == "\u064a" and i6 == len(sk) - 1:
                continue
            t += _DOTU_C.get(DOTS[ch][0], 0)
        return t

    _wdots = [_dots_of_word(w6) for w6 in words]

    def _dots_in(j6, i6):
        t = 0
        for a6 in atoms[j6:i6]:
            for e6 in a6["els"]:
                if e6.get("mkpart"):
                    continue
                t += _DOTU_C.get(e6.get("mark") or e6.get("lab"), 0)
        return t

    def group_cost(j, i, k):              # atoms j..i-1 as word k, in letter units
        if ayah_ranges:
            r = ayah_ranges.get((words[k - 1]["surah"], words[k - 1]["ayah"]))
            if r:
                # a word may not leave its ayah's polygon on this line
                overflow = (max(0.0, atoms[j]["x2"] - r[1] - 1.2)
                            + max(0.0, r[0] - atoms[i - 1]["x1"] - 1.2))
                if overflow > 0:
                    return 4.0 + overflow / alpha
        _, c = align_segs_atoms(atoms[j:i], all_segs[k - 1], alpha_cal)
        if c == float("inf"):
            c = abs(width(j, i - 1) - alpha * lens[k - 1]) / alpha + 2.0
        else:
            c *= len(all_segs[k - 1]) or 1
        # The art joins letters but never invents pieces: more atoms than expected
        # segments means the word is absorbing a neighbour's fragment — unless it
        # carries a hamza or tanween, whose tiny floats legitimately add atoms.
        surplus = max(0, (i - j) - len(all_segs[k - 1]))
        if surplus:
            floaty = any(ch in "ءأإؤئآ" for ch in words[k - 1]["uthmani"]) or \
                any(ch in "ًࣰٌࣱٍࣲ" for ch in words[k - 1]["uthmani"])
            c += surplus * (0.15 if floaty else _W_SURPLUS)
        # Direct word-width prior: the page font's own advance for this word is
        # ground truth (justification cancels through alpha). Letter alignment
        # alone lets a boundary drift a whole piece; this term pays for it.
        c += _W_WIDTH * abs(width(j, i - 1) - alpha * lens[k - 1]) / alpha
        # ... and the dot budget, which pins a boundary the widths cannot: a
        # surplus is charged harder than a deficit, since dots drawn over a
        # neighbour's letters are common but invented dots are not.
        dd = _dots_in(j, i) - _wdots[k - 1]
        if dd and not use_dots:
            dd = dd * _DOT_SCORE      # weaker voice when only SCORING a line
        if dd:
            c += (_W_DOTS * dd) if dd > 0 else (0.4 * _W_DOTS * -dd)
        return c

    INF = float("inf")
    dp = [[INF] * (n + 1) for _ in range(m + 1)]
    back = [[0] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = 0.0
    for k in range(1, n + 1):
        for i in range(k, m - (n - k) + 1):
            for j in range(k - 1, i):     # word k takes atoms j..i-1
                if dp[j][k - 1] == INF:
                    continue
                c = (dp[j][k - 1] + group_cost(j, i, k)
                     - (GAP_REWARD * gap[j] / mean_letter if j else 0.0))
                if c < dp[i][k]:
                    dp[i][k] = c
                    back[i][k] = j
    if dp[m][n] == INF:
        return [[a] for a in atoms], float("inf")

    bounds, i = [], m
    for k in range(n, 0, -1):
        j = back[i][k]
        bounds.append((j, i - 1))
        i = j
    bounds.reverse()

    clusters = [atoms[j:i + 1] for j, i in bounds]

    # Boundary repair: the DP is contiguous in reading order; keep it that way
    # and only SHIFT each word boundary by up to three atoms, scored by the QCF
    # width prior plus what the text says about edge atoms (a word ending in
    # \u0627/\u0629 owns the tall stroke / ring at its left edge; a word not starting
    # with an alef cannot open with a lone tall stroke). Order-preserving shifts
    # cannot interleave clusters, unlike free atom moves.
    def spanw(cl):
        return (max(a["x2"] for a in cl) - min(a["x1"] for a in cl)) if cl else 0.0

    def skel(w):
        return "".join(_LETTER.findall(w["uthmani"]))

    def alef_atom(a):
        b = max((e for e in a["els"] if e["kind"] == "body"), default=None,
                key=lambda e: (e["x2"] - e["x1"]) * (e["y2"] - e["y1"]))
        if b is None:
            return False
        w = b["x2"] - b["x1"]; h = b["y2"] - b["y1"]
        return h >= 8.5 and w <= 5.0 and h >= 2.6 * w   # a raa tail is squatter

    def ring_atom(a):
        b = max((e for e in a["els"] if e["kind"] == "body"), default=None,
                key=lambda e: (e["x2"] - e["x1"]) * (e["y2"] - e["y1"]))
        if b is None:
            return False
        w = b["x2"] - b["x1"]; h = b["y2"] - b["y1"]
        # nested contour is the signal: a ة drawn ring+tail as one path runs
        # to ~11 units, still unmistakably a ring letter
        return 3.0 <= max(w, h) <= 7.5 and 0.6 <= w / max(h, 1e-6) <= 1.7 \
            and len(b["contours"]) > 1

    ALEFS = "\u0627\u0623\u0625\u0622\u0671"
    sks = [skel(w) for w in words]

    def poly_pen(cl, k):
        # the ayah polygons are the art's own truth: an atom whose centre sits
        # outside its word's ayah extent on this line is on the wrong side
        if not ayah_ranges or not cl:
            return 0.0
        r = ayah_ranges.get((words[k]["surah"], words[k]["ayah"]))
        if not r:
            return 0.0
        lo, hi = r
        n_out = sum(1 for a in cl
                    if not (lo - 1.5 <= (a["x1"] + a["x2"]) / 2 <= hi + 1.5))
        return 4.0 * alpha * n_out

    def _nseg_band(w):
        segs = segment_word(w["uthmani"])
        hi = max(1, len(segs))
        soft = sum(1 for sg in segs if sg["text"] == "\u0621")
        # a lam-alef ligature may be drawn as TWO strokes (one extra piece)
        sk = "".join(_LETTER.findall(w["uthmani"]))
        laa = sum(sk.count("\u0644" + a) for a in "\u0627\u0623\u0625\u0622")
        return (max(1, hi - soft), hi + laa)

    nseg_band = [_nseg_band(w) for w in words]
    nsegs = [b[1] for b in nseg_band]

    def bscore(k, cl_r, cl_l):
        sk_r, sk_l = sks[k], sks[k + 1]
        c = (abs(spanw(cl_r) - alpha * lens[k])
             + abs(spanw(cl_l) - alpha * lens[k + 1])
             + poly_pen(cl_r, k) + poly_pen(cl_l, k + 1))
        # the text fixes how many detached pieces each word has: a stolen ذ or
        # ن leaves one word a segment short and its neighbour one over. The
        # first unit of mismatch matters most; chronic welds (fewer drawn
        # pieces than text segments, e.g. القرءان) add a flat offset that
        # cannot flip a boundary decision.
        def _segpen(cnt, band):
            lo, hi = band
            if lo <= cnt <= hi:
                return 0.0
            if cnt > hi:
                return 2.5 * (cnt - hi)   # surplus is always suspicious
            d = lo - cnt
            return d if d <= 1 else 1.0 + 0.25 * (d - 1)   # welds under-count
        c += 2.0 * alpha * (_segpen(len(cl_r), nseg_band[k])
                            + _segpen(len(cl_l), nseg_band[k + 1]))
        # provable theft of a short non-joining letter (dhal dal raa zay waw):
        # one side opens/ends with one per its text but is a piece short,
        # while the other holds a squat letter-sized piece at the boundary
        def _squat(a):
            b = max((e for e in a["els"] if e["kind"] == "body"), default=None,
                    key=lambda e: (e["x2"] - e["x1"]) * (e["y2"] - e["y1"]))
            if b is None:
                return False
            w2 = b["x2"] - b["x1"]; h2 = b["y2"] - b["y1"]
            if len(b["contours"]) > 1:
                return False
            return 4.0 <= max(w2, h2) <= 13.0 and h2 < 1.8 * w2 + 4.0
        if cl_r and cl_l and sk_l and sk_l[0] in "\u0630\u062f\u0631\u0632\u0648" \
                and len(cl_l) < nsegs[k + 1] and _squat(cl_r[-1]):
            c += 14.0 * alpha
        if cl_r and cl_l and sk_r and sk_r[-1] in "\u0630\u062f\u0631\u0632\u0648" \
                and len(cl_r) < nsegs[k] and _squat(cl_l[0]):
            c += 14.0 * alpha
        # a word expects a STANDALONE trailing alef only when its previous
        # letter is non-joining; after a joining letter the alef is fused into
        # a ligature and a lone alef at the boundary belongs to the neighbour
        r_ends_alef = (len(sk_r) >= 2 and sk_r[-1] in "\u0627\u0622"
                       and sk_r[-2] in "\u0648\u0630\u0631\u0632\u062f\u0621"
                                       "\u0627\u0623\u0625\u0622\u0671")
        l_starts_alef = bool(sk_l) and sk_l[0] in ALEFS
        if not cl_r or not cl_l:
            return c
        # penalise only PROVABLE thefts: the right word misses its trailing
        # stroke while the left word opens with one it has no textual right to
        # (a word starting with a tall lam must never be disturbed)
        if r_ends_alef and not l_starts_alef \
                and not alef_atom(cl_r[-1]) and alef_atom(cl_l[0]):
            c += 14.0 * alpha
        if os.environ.get("QSVG_DEBUG_BSC") and "\u063a\u062a" in sk_r:
            print("BSC r=%s l=%s r_ends=%s l_starts=%s aA(cl_r[-1])=%s aA(cl_l[0])=%s"
                  % (sk_r, sk_l, r_ends_alef, l_starts_alef,
                     alef_atom(cl_r[-1]), alef_atom(cl_l[0])), file=sys.stderr)
        if l_starts_alef and not r_ends_alef \
                and not alef_atom(cl_l[0]) and alef_atom(cl_r[-1]):
            c += 14.0 * alpha
        if r_ends_alef and l_starts_alef:
            if len(cl_r) >= 2 and alef_atom(cl_r[-1]) and alef_atom(cl_r[-2]) \
                    and not alef_atom(cl_l[0]):
                c += 14.0 * alpha
            if len(cl_l) >= 2 and alef_atom(cl_l[0]) and alef_atom(cl_l[1]) \
                    and not alef_atom(cl_r[-1]):
                c += 14.0 * alpha
        if sk_r.endswith("\u0629") and not ring_atom(cl_r[-1]) \
                and ring_atom(cl_l[0]) and not (sk_l and sk_l[0] in "\u0647\u0629"):
            c += 14.0 * alpha
        return c
    _dbg_pair = os.environ.get("QSVG_DEBUG_PAIR")
    if _dbg_pair:
        _orig_bscore = bscore
        def bscore(k, cl_r, cl_l):
            c = _orig_bscore(k, cl_r, cl_l)
            if _dbg_pair in sks[k]:
                w_r = abs(spanw(cl_r) - alpha * lens[k])
                w_l = abs(spanw(cl_l) - alpha * lens[k + 1])
                print("PAIR %s|%s nr=%d nl=%d tot=%.2f wr=%.2f wl=%.2f band_r=%s band_l=%s"
                      % (sks[k], sks[k + 1], len(cl_r), len(cl_l), c, w_r, w_l,
                         nseg_band[k], nseg_band[k + 1]), file=sys.stderr)
            return c

    for _ in range(2):
        changed = False
        for k in range(n - 1):
            cl_r, cl_l = clusters[k], clusters[k + 1]
            base = bscore(k, cl_r, cl_l)
            best = (base, 0)
            for j in (1, 2, 3):                        # take j atoms from the left word
                if len(cl_l) > j:
                    d = bscore(k, cl_r + cl_l[:j], cl_l[j:])
                    if d < best[0]:
                        best = (d, j)
            for j in (1, 2, 3):                        # give j atoms to the left word
                if len(cl_r) > j:
                    d = bscore(k, cl_r[:-j], cl_r[-j:] + cl_l)
                    if d < best[0]:
                        best = (d, -j)
            if os.environ.get("QSVG_DEBUG_BND"):
                print("BND %-10s|%-10s base %.2f best %.2f shift %d" % (
                    words[k]["uthmani"][:10], words[k + 1]["uthmani"][:10],
                    base, best[0], best[1]), file=sys.stderr)
            if best[1] and best[0] < base - 0.3 * alpha:
                j = best[1]
                if j > 0:
                    clusters[k] = cl_r + cl_l[:j]
                    clusters[k + 1] = cl_l[j:]
                else:
                    clusters[k] = cl_r[:j]
                    clusters[k + 1] = cl_r[j:] + cl_l
                changed = True
        if not changed:
            break

    mean_w = span_total / n
    worst = 0.0
    for k, cl in enumerate(clusters):
        if cl:
            span_k = spanw(cl)
            worst = max(worst, abs(span_k - alpha * lens[k]) / mean_w)
    return clusters, worst


# ---------------------------------------------------------------------------
# Letter level: ligature segmentation and mark prediction from the word's text
# ---------------------------------------------------------------------------
# A connected letter-body IS a ligature: Arabic non-joining letters break the
# connected groups, so the expected ligature split is computable from the text
# alone (ٱلَّذِينَ → ٱ / لذ / ين). Marks (harakat, hamza, i'jam dots) are separate
# small elements; each one's label is predicted from the Unicode marks plus the
# dot pattern of the skeleton letters, then matched to the atom's observed mark
# elements above/below the body in right-to-left order. Any count mismatch is
# flagged, never guessed.

HARAKA = {
    "ً": ("fathatan", "a"), "ٌ": ("dammatan", "a"),
    "ٍ": ("kasratan", "b"), "َ": ("fatha", "a"),
    "ُ": ("damma", "a"), "ِ": ("kasra", "b"),
    "ّ": ("shadda", "a"), "ْ": ("sukun", "a"),
    "ٓ": ("maddah", "a"), "ٔ": ("hamza", "a"), "ٕ": ("hamza", "b"),
    "ٰ": ("small-alef", "a"), "۟": ("small-circle", "a"),
    "۠": ("small-circle", "a"), "ۡ": ("sukun", "a"),
    "ۢ": ("meem-iqlab", "a"), "ۭ": ("meem-iqlab", "b"),
    "ۤ": ("maddah", "a"), "ۥ": ("small-waw", "a"),
    "ۦ": ("small-ya", "a"), "ۧ": ("small-ya", "a"),
    "ۖ": ("pause", "a"), "ۗ": ("pause", "a"), "ۘ": ("pause", "a"),
    "ۙ": ("pause", "a"), "ۚ": ("pause", "a"), "ۛ": ("pause", "a"),
    "ۜ": ("pause", "a"), "ࣰ": ("fathatan", "a"),
    "ࣱ": ("dammatan", "a"), "ࣲ": ("kasratan", "b"),
}
# skeleton letter -> (dots label, above/below); final ya is dotless in this script
DOTS = {
    "ب": ("dot", "b"), "ت": ("two-dots", "a"), "ث": ("three-dots", "a"),
    "ج": ("dot", "b"), "خ": ("dot", "a"), "ذ": ("dot", "a"), "ز": ("dot", "a"),
    "ش": ("three-dots", "a"), "ض": ("dot", "a"), "ظ": ("dot", "a"),
    "غ": ("dot", "a"), "ف": ("dot", "a"), "ق": ("two-dots", "a"),
    "ن": ("dot", "a"), "ي": ("two-dots", "b"), "ة": ("two-dots", "a"),
}
HAMZA_MAP = {
    "أ": ("ا", ("hamza", "a")), "إ": ("ا", ("hamza", "b")),
    "آ": ("ا", ("maddah", "a")), "ٱ": ("ا", ("wasla", "a")),
    "ؤ": ("و", ("hamza", "a")), "ئ": ("ي", ("hamza", "a")),
}
NONJOIN = set("اأإآٱدذرزوؤةى")


def segment_word(uthmani):
    """Expected ligatures of a word: [{'text', 'marks': [(label, pos)…], 'bad'}].

    `text` is the skeleton (rasm) the body path draws. A standalone ء is drawn as a
    floating mark in this art, so it joins the neighbouring segment's marks instead of
    counting as a body of its own.
    """
    segs, cur, pend, bad = [], None, [], False
    for ch in uthmani:
        if ch in " ـ":
            continue
        if ch == "ء":                       # drawn at baseline: its own tiny body
            cur = {"text": "ء", "marks": pend, "closed": True}
            segs.append(cur)
            pend = []
            continue
        if ch in HARAKA:
            if cur:
                cur["marks"].append(HARAKA[ch])
            else:
                pend.append(HARAKA[ch])
            continue
        if ch in HAMZA_MAP:
            base, extra = HAMZA_MAP[ch]
        elif "ء" <= ch <= "ي" or ch == "ى":
            base, extra = ch, None
        else:
            bad = True          # a char these tables don't know — review, not guess
            continue
        if cur is None or cur["closed"]:
            cur = {"text": "", "marks": pend, "closed": False}
            segs.append(cur)
            pend = []
        cur["text"] += base
        if extra:
            cur["marks"].append(extra)      # hamza carriers are drawn dotless
        elif base in DOTS:
            cur["marks"].append(DOTS[base])
        if ch in NONJOIN:
            cur["closed"] = True
    if pend and segs:
        segs[0]["marks"] = pend + segs[0]["marks"]
    # final ya and alef maqsura are drawn dotless in the Madinah script
    if segs and segs[-1]["text"].endswith("ي"):
        m = segs[-1]["marks"]
        if ("two-dots", "b") in m:
            m.remove(("two-dots", "b"))
    for s in segs:
        s["bad"] = bad
    return segs


def align_segs_atoms(atoms, segs, alpha=None):
    """Monotone alignment of drawn bodies to expected ligatures, both right-to-left.

    The nominal split rule and the art disagree in places — كفروا can be inked as one
    connected piece (one atom, three segments), a hamza or a stray piece can add an
    atom. Each aligned group is one atom run ↔ one segment run, where at least one side
    is a single item; groups are scored by the same width prior as word clustering.
    Returns (groups, cost): groups = [(atom_list, seg_list)…], cost normalised to the
    word's per-letter width (high = review).
    """
    n, m = len(atoms), len(segs)
    if not n or not m:
        return [(atoms, segs)] if atoms or segs else [], float("inf")
    lens = [letter_width(s["text"]) for s in segs]
    if alpha is None:                     # scale from the word itself; a caller that
        span_total = atoms[0]["x2"] - atoms[-1]["x1"]  # compares words must pass the
        alpha = span_total / sum(lens)                 # line's absolute per-letter width

    def span(pi, i):                                    # atoms pi..i-1, with gaps
        return atoms[pi]["x2"] - atoms[i - 1]["x1"]

    mean_seg = alpha * (sum(lens) / len(lens))
    INF = float("inf")
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            for pi in range(0, i):
                for pj in range(0, j):
                    if (i - pi > 1) and (j - pj > 1):
                        continue                    # one side must be a single item
                    if dp[pi][pj] == INF:
                        continue
                    c = dp[pi][pj] + abs(span(pi, i) - alpha * sum(lens[pj:j]))
                    if j - pj > 1:
                        # Merging expected segments means the art joined across a
                        # non-joining boundary — possible (a وا swash) but rare, and
                        # never possible for a standalone ء, which touches nothing.
                        if any(s["text"] == "ء" for s in segs[pj:j]):
                            continue
                        c += 0.12 * mean_seg * (j - pj - 1)
                    if c < dp[i][j]:
                        dp[i][j] = c
                        back[i][j] = (pi, pj)
    if dp[n][m] == INF:      # e.g. a lone atom asked to hold text ending in ء
        return [(atoms, segs)], float("inf")
    groups, i, j = [], n, m
    while i or j:
        pi, pj = back[i][j]
        groups.append((atoms[pi:i], segs[pj:j]))
        i, j = pi, pj
    groups.reverse()
    # Cost in fractions of a mean expected segment, so it is scale-free whether the
    # letter widths are relative table values or calibrated absolute units.
    mean_seg = alpha * (sum(lens) / len(lens))
    return groups, dp[n][m] / max(mean_seg, 1e-9) / max(1, len(groups))


def mark_pos(e, baseline, body):
    """'a' above the line's writing level, 'b' below — fatha vs kasra territory."""
    cy = (e["y1"] + e["y2"]) / 2
    if baseline is not None:
        return "a" if cy < baseline else "b"
    return "a" if cy < (body["y1"] + body["y2"]) / 2 else "b"


def label_marks(group_atoms, marks, baseline=None):
    """Attach predicted labels to a ligature group's observed marks; True if matched."""
    body = group_atoms[0]["els"][0]
    obs = {"a": [], "b": []}
    for a in group_atoms:
        for e in a["els"][1:]:
            if e.get("mkpart"):
                continue                 # a composite counts once, via its primary
            if e["kind"] != "mark":
                continue                 # a welded letter sliver is not a mark
            obs[mark_pos(e, baseline, body)].append(e)
    ok = True
    for pos in ("a", "b"):
        pred = [lab for lab, p in marks if p == pos]
        got = sorted(obs[pos], key=lambda e: -(e["x1"] + e["x2"]))
        if len(pred) == len(got):
            for lab, e in zip(pred, got):
                e["mark"] = lab
                for part in e.get("mkmembers", []):
                    part["mark"] = lab
        else:
            ok = False
    return ok


# ---------------------------------------------------------------------------
# Rewrite: word groups inside each line group
# ---------------------------------------------------------------------------

def esc(s):
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def rewrite(page, assignment):
    """Wrap elements in <g class="word"> / <g class="ligature"> with full metadata.

    Regrouping reorders elements within one original path; ink pieces never overlap
    (proved page-wide by the split verifier), so evenodd parity cannot change. A word
    or ligature whose elements span several source <path> wrappers is emitted once per
    wrapper with the same metadata.
    """
    from add_line_structure import build_d

    # A word is one thing on the page, but its ink can straddle the boundary
    # between two line paths — a descender dips below it, a mark rides above —
    # and emitting the word once per wrapper leaves half of it inside a line it
    # does not belong to, where that line's ayah polygon cannot reach it. Send
    # every element of a word to the wrapper holding most of that word's ink,
    # so the word is emitted exactly once, in the line it is written on.
    # Nothing about the picture changes: each element is written as its own
    # <path> either way, and every path in this art is the same colour, so
    # coverage composites to the same result whatever order it arrives in.
    home = {}
    for word, atoms in assignment:
        if not word:
            continue
        weight = {}
        for atom in atoms:
            for e in atom["els"]:
                area = max(e["x2"] - e["x1"], 0.01) * max(e["y2"] - e["y1"], 0.01)
                weight[e["path"]] = weight.get(e["path"], 0.0) + area
        if weight:
            home[id(word)] = max(weight, key=weight.get)

    per_path = {}
    for word, atoms in assignment:
        tgt = home.get(id(word)) if word else None
        for ai, atom in enumerate(atoms):
            lig = (id(word), atom.get("lig", ai))
            for e in atom["els"]:
                per_path.setdefault(e["path"] if tgt is None else tgt,
                                    []).append((word, lig, atom, e))

    svg = page.svg
    eid = [0]
    out, pos = [], 0
    for pi, p in enumerate(page.paths):
        s, t = p["span"]
        out.append(svg[pos:s])
        pos = t
        if pi not in per_path:
            out.append(p["text"])
            continue
        a, b = p["d_span"][0] - s, p["d_span"][1] - s
        head, tail = p["text"][:a], p["text"][b:]

        def emit(e):
            eid[0] += 1
            extra = '<path data-eid="e%d" data-kind="%s" ' % (eid[0], e["kind"])
            if e.get("mark"):
                extra += ('data-mark-part="%s" ' if e.get("mkpart")
                          else 'data-mark="%s" ') % e["mark"]
            if e.get("sig"):
                extra += 'data-sig="%s" ' % e["sig"]
            if e.get("fused"):
                extra += 'data-fused="1" '
            if e.get("standalone"):
                extra += ('data-standalone="1" data-surah="%d" data-ayah="%d" '
                          % e["standalone"])
            out.append(head.replace("<path ", extra, 1) + build_d(e["contours"]) + tail)

        open_word = open_lig = None
        open_ayah = None
        open_sa = None
        for word, lig_key, atom, e in per_path[pi]:
            sa = atom.get("sa") if not word else None
            if id(atom) != open_sa and open_sa is not None:
                out.append("</g>")
                open_sa = None
            wkey = id(word) if word else None
            if sa and open_sa is None:
                if open_lig is not None:
                    out.append("</g>")
                    open_lig = None
                if open_word is not None:
                    out.append("</g>")
                    open_word = None
                if open_ayah is not None:
                    out.append("</g>")
                    open_ayah = None
                out.append('<g class="%s-mark" data-mark="%s"%s>'
                           % (sa[0], sa[0],
                              (' data-surah="%d" data-ayah="%d"'
                               % (sa[1], sa[2])) if sa[1] else ""))
                open_sa = id(atom)
                emit(e)
                continue
            if wkey != open_word:
                if open_lig is not None:
                    out.append("</g>")
                    open_lig = None
                if open_word is not None:
                    out.append("</g>")
                open_word = None
                akey = (word["surah"], word["ayah"]) if word else None
                if akey != open_ayah:
                    if open_ayah is not None:
                        out.append("</g>")
                    open_ayah = None
                    if akey:
                        out.append('<g class="ayah" data-surah="%d" data-ayah="%d">'
                                   % akey)
                        open_ayah = akey
                if word:
                    out.append('<g class="word" data-surah="%d" data-ayah="%d" '
                               'data-word="%d" data-uthmani="%s" data-imlaei="%s">'
                               % (word["surah"], word["ayah"], word["pos"],
                                  esc(word["uthmani"]), esc(word["imlaei"])))
                    open_word = wkey
            if word and lig_key != open_lig:
                if open_lig is not None:
                    out.append("</g>")
                seg = atom.get("seg")
                out.append('<g class="ligature"%s>'
                           % (' data-text="%s"' % esc(seg["text"]) if seg else ""))
                open_lig = lig_key
            emit(e)
        if open_lig is not None:
            out.append("</g>")
        if open_word is not None:
            out.append("</g>")
        if open_ayah is not None:
            out.append("</g>")
        if open_sa is not None:
            out.append("</g>")
    out.append(svg[pos:])
    return "".join(out)


# ---------------------------------------------------------------------------

def part_key_for(page):
    """(part_key, known) for composite vetoes: shape id of one element's outer contour."""
    table = shape_labels()
    if not table:
        return None, {}
    from split_line_elements import contour_polylines
    from svg_lines import apply as xform
    from markshape import resample, signature, sig_key
    polys, memo = {}, {}

    from markshape import element_points

    def part_key(e):
        k = id(e)
        if k not in memo:
            pi = e["path"]
            if pi not in polys:
                polys[pi] = contour_polylines(page.paths[pi]["d"])
            cps = [[xform(page.paths[pi]["M"], x, y)
                    for x, y in polys[pi][c["sp"]["index"]]] for c in e["contours"]]
            memo[k] = sig_key(signature(element_points(cps)))
        return memo[k]

    return part_key, {k: v["label"] for k, v in table.items()}


# Auto (vote-derived) labels may force-mark only unambiguous families; anything a
# letter can imitate (pause vs ر, damma vs ء curl, hamza) needs a HUMAN-confirmed
# label before it may override geometry.
_SAFE_AUTO = {"fatha", "kasra", "fathatan", "kasratan", "dot", "two-dots",
              "three-dots", "shadda", "small-circle", "meem-iqlab", "maddah",
              "small-alef", "wasla"}


def _raw_label(sig):
    v = shape_labels().get(sig)
    return v["label"] if isinstance(v, dict) else v


def mark_shape_table():
    out = {}
    for k, v in shape_labels().items():
        lab = v["label"]
        if lab in ("word", "ignore", "hamza", "meem-iqlab"):
            # ء twins stay letters at classify time; apply still labels. The
            # iqlab meem shares its outline with a final letter م, and only
            # the word's text can tell them apart — so it stays letter ink
            # here and is promoted to a mark later, where the text is known.
            continue
        if v.get("auto") and lab not in _SAFE_AUTO:
            continue
        out[k] = lab
    return out


_SHAPE_LABELS = None


def shape_labels():
    """Human-confirmed shape->label table from cluster_marks.py, if present."""
    global _SHAPE_LABELS
    if _SHAPE_LABELS is None:
        p = os.path.join(ROOT, ".cache", "marks", "labels.json")
        _SHAPE_LABELS = (json.load(open(p, encoding="utf-8"))
                         if os.path.exists(p) else {})
    return _SHAPE_LABELS


# The same stroke is a fatha above the letter and a kasra below it; the shape table
# stores one name, the drawn position picks the final label.
_POS_SWAP = {("fatha", "b"): "kasra", ("kasra", "a"): "fatha",
             ("fathatan", "b"): "kasratan", ("kasratan", "a"): "fathatan"}


def apply_shape_labels(page, assignment, baselines):
    """Label every mark element by its outline shape; returns (labeled, total)."""
    table = {k: v["label"] for k, v in shape_labels().items()}
    if not table:
        return 0, 0
    from split_line_elements import contour_polylines
    from svg_lines import apply as xform
    from markshape import resample, signature, sig_key

    polys = {}
    body_pts = {}

    def poly_pts(el, outer_only=False):
        pi = el["path"]
        if pi not in polys:
            polys[pi] = contour_polylines(page.paths[pi]["d"])
        out = []
        for c in (el["contours"][:1] if outer_only else el["contours"]):
            out += [xform(page.paths[pi]["M"], x, y)
                    for x, y in polys[pi][c["sp"]["index"]]]
        return out

    def local_pos(e, atom):
        """Above or below the letter's own ink at the mark's x — not the line.

        A kasra under a letter stacked high in the composition sits above the
        baseline, and a fatha over low teeth like س sits below the line's middle;
        only the ink directly at the mark's x-window resolves both.
        """
        if id(atom) not in body_pts:
            body_pts[id(atom)] = poly_pts(atom["els"][0])
        cy = (e["y1"] + e["y2"]) / 2
        sel = [y for x, y in body_pts[id(atom)]
               if e["x1"] - 0.5 <= x <= e["x2"] + 0.5]
        if not sel:
            sel = [y for _, y in body_pts[id(atom)]]
        return "a" if cy < (min(sel) + max(sel)) / 2 else "b"

    from markshape import composite_signature, element_points

    def el_points(el):
        pi = el["path"]
        if pi not in polys:
            polys[pi] = contour_polylines(page.paths[pi]["d"])
        return element_points([[xform(page.paths[pi]["M"], x, y)
                                for x, y in polys[pi][c["sp"]["index"]]]
                               for c in el["contours"]])

    _MARKY = {"fatha", "kasra", "damma", "fathatan", "kasratan", "dammatan",
              "sukun", "shadda", "hamza", "maddah", "small-alef", "wasla",
              "dot", "two-dots", "three-dots", "pause", "small-circle",
              "small-ya", "small-waw", "small-meem", "small-noon"}
    labeled = total = 0
    for word, atoms in assignment:
        for atom in atoms:
            for e in atom["els"]:
                if e["kind"] != "mark":
                    # a mark-sized blob the baseline test kept as a body: if
                    # its outline is a known mark shape, that wins
                    if (e["kind"] == "body"
                            and max(e["x2"] - e["x1"], e["y2"] - e["y1"]) <= 8.5
                            and not e.get("mark")):
                        try:
                            sg = sig_key(signature(el_points(e)))
                        except Exception:
                            continue
                        lb = table.get(sg)
                        if lb and all(p in _MARKY for p in lb.split("+")):
                            e["kind"] = "mark"
                            e["sig"] = sg
                            e["mark"] = lb
                            labeled += 1
                            total += 1
                    continue             # merged atoms carry several bodies
                if e.get("mkpart"):
                    continue             # labeled through its composite's primary
                total += 1
                members = e.get("mkmembers", [])
                if members:
                    sig = composite_signature([el_points(x) for x in [e] + members])
                else:
                    sig = signature(el_points(e))
                e["sig"] = sig_key(sig)   # exported as data-sig: one decision
                                          # on this shape applies mushaf-wide
                lab = table.get(e["sig"])
                # the dot family is SOLID ink: a nested contour is a ring — a
                # ه/ة head — mislabeled by the auto pass; it is letter ink
                if lab in ("dot", "two-dots", "three-dots") \
                        and len(e.get("contours", [])) > 1:
                    bbs = [c["sp"] for c in e["contours"]]
                    for _i, _a in enumerate(bbs):
                        for _b in bbs[_i + 1:]:
                            if (_a["xmin"] <= _b["xmin"] and _a["xmax"] >= _b["xmax"]
                                    and _a["ymin"] <= _b["ymin"]
                                    and _a["ymax"] >= _b["ymax"]) or \
                               (_b["xmin"] <= _a["xmin"] and _b["xmax"] >= _a["xmax"]
                                    and _b["ymin"] <= _a["ymin"]
                                    and _b["ymax"] >= _a["ymax"]):
                                lab = "letter-part"
                if lab in ("ignore", "word", "letter-part", "letter-hamza", "letter"):
                    if lab in ("letter", "letter-part", "letter-hamza"):
                        e["kind"] = "body"   # letter ink misfiled as a mark
                    labeled += 1          # identified as non-mark ink: accounted for
                    continue
                if not lab and members:
                    # a composite of dot glyphs is the letter's full dot group:
                    # ث draws three-dots as a two-dot path plus a one-dot path
                    DOTN = {"dot": 1, "two-dots": 2, "three-dots": 3}
                    pl = [table.get(sig_key(signature(el_points(x))))
                          for x in [e] + members]
                    if "ignore" in pl:
                        # invisible sliver welded to a real mark: judge the rest
                        core = [l for l in pl if l != "ignore"]
                        if len(core) == 1 and core[0]:
                            lab = core[0]
                        pl = core
                    if pl and all(l in DOTN for l in pl):
                        lab = {1: "dot", 2: "two-dots", 3: "three-dots"}.get(
                            sum(DOTN[l] for l in pl))
                    elif pl and all(l == "pause" or l in DOTN for l in pl) \
                            and "pause" in pl:
                        lab = "pause"     # waqf letter + its dot(s)
                    elif pl and all(pl) and not any(
                            l in ("word", "ignore", "letter", "letter-hamza",
                                  "letter-part") for l in pl):
                        # every part is individually known: a stacked group whose
                        # welded outline was never seen — name it top-to-bottom and
                        # let the compound splitter cut it back into single marks
                        order = sorted(zip([e] + members, pl),
                                       key=lambda t: t[0]["y1"])
                        lab = "+".join(l for _, l in order)
                if not lab and (e["y2"] - e["y1"]) < 2.5 \
                        and (e["x2"] - e["x1"]) > 15.0:
                    lab = "sajdah"        # overline bars have per-length outlines
                if not lab or lab in ("ignore", "word", "letter-part", "letter-hamza", "letter"):
                    if not lab and os.environ.get("QSVG_DEBUG_UNACC"):
                        print("UNACC sig", e["sig"], "x%.1f..%.1f y%.1f..%.1f members %d"
                              % (e["x1"], e["x2"], e["y1"], e["y2"], len(members)),
                          file=sys.stderr)
                    continue
                if "+" in lab:
                    # compound label for a stacked group drawn touching: names are
                    # top-to-bottom; parts split into name-groups at the largest
                    # vertical gaps (a pause sign's own dot stays with its curl)
                    names = [x.strip() for x in lab.split("+")]
                    parts = sorted([e] + members,
                                   key=lambda x: (x["y1"] + x["y2"]) / 2)
                    if len(parts) >= len(names):
                        gaps = sorted(range(1, len(parts)),
                                      key=lambda i: (parts[i]["y1"] + parts[i]["y2"])
                                      - (parts[i-1]["y1"] + parts[i-1]["y2"]),
                                      reverse=True)[:len(names) - 1]
                        cuts = sorted(gaps)
                        gi = 0
                        for i, pt in enumerate(parts):
                            if gi < len(cuts) and i >= cuts[gi]:
                                gi += 1
                            pt["mark"] = names[min(gi, len(names) - 1)]
                        labeled += 1
                    else:
                        # the art drew the stack as one connected contour: the
                        # ink cannot be cut without redrawing it, so the single
                        # path keeps the compound name, flagged as fused
                        e["mark"] = lab
                        e["fused"] = True
                        labeled += 1
                    continue
                pos = local_pos(e, atom)
                final = _POS_SWAP.get((lab, pos), lab)
                e["mark"] = final
                for part in members:
                    part["mark"] = final
                labeled += 1
            compose_tanween(atom)
    return labeled, total


def compose_tanween(atom):
    """Two stacked identical strokes are one tanween: fatha+fatha -> fathatan.

    The dammatan glyph is drawn as one outline and labels directly; the stroke
    tanweens are drawn as two separate strokes, so without this pass the taxonomy
    would be inconsistent across the three.
    """
    # KFQC tucks a shadda's kasra UNDER the shadda but ABOVE the letter, where the
    # letter-relative rule would read it as fatha. When a stroke shares x-range
    # with a shadda, the shadda is the reference: below it = kasra, above = fatha.
    shaddas = [e for e in atom["els"][1:] if e.get("mark") == "shadda"]
    if shaddas:
        for e in atom["els"][1:]:
            if e.get("mark") not in ("fatha", "kasra"):
                continue
            for sh in shaddas:
                ov = min(e["x2"], sh["x2"]) - max(e["x1"], sh["x1"])
                if ov < 0.5 * min(e["x2"] - e["x1"], sh["x2"] - sh["x1"]):
                    continue
                below = (e["y1"] + e["y2"]) / 2 > (sh["y1"] + sh["y2"]) / 2
                e["mark"] = "kasra" if below else "fatha"
                break

    # A dammatan drawn as two curls: one piece often matches the damma shape and
    # the other a dedicated fragment labeled dammatan; touching pieces weld.
    pool = [e for e in atom["els"][1:] if e.get("mark") in ("damma", "dammatan")]
    for i, a in enumerate(pool):
        for b in pool[i + 1:]:
            if "dammatan" not in (a.get("mark"), b.get("mark")):
                continue
            dx = abs((a["x1"] + a["x2"]) / 2 - (b["x1"] + b["x2"]) / 2)
            dy = abs((a["y1"] + a["y2"]) / 2 - (b["y1"] + b["y2"]) / 2)
            if dx < 7.0 and dy < 6.0:
                a["mark"] = b["mark"] = "dammatan"

    def _weld_pairs():
        # a tanween's two strokes (or two damma curls) present as ONE mark: the
        # top piece is the master, the other becomes its part
        for lab in ("fathatan", "kasratan", "dammatan"):
            grp = [e for e in atom["els"][1:] if e.get("mark") == lab
                   and not e.get("mkpart")]
            grp.sort(key=lambda e: (e["y1"] + e["y2"]))
            while len(grp) >= 2:
                master, part = grp[0], grp[1]
                dx = abs((master["x1"] + master["x2"]) / 2
                         - (part["x1"] + part["x2"]) / 2)
                dy = abs((master["y1"] + master["y2"]) / 2
                         - (part["y1"] + part["y2"]) / 2)
                if dx < 8.0 and dy < 7.0:
                    part["mkpart"] = True
                    master.setdefault("mkmembers", []).append(part)
                    grp = [master] + grp[2:]
                    grp = grp[1:]        # master consumed one part; next pair
                else:
                    grp = grp[1:]

    for base, tan in (("fatha", "fathatan"), ("kasra", "kasratan")):
        strokes = [e for e in atom["els"][1:] if e.get("mark") == base]
        for i, a in enumerate(strokes):
            for b in strokes[i + 1:]:
                dx = abs((a["x1"] + a["x2"]) / 2 - (b["x1"] + b["x2"]) / 2)
                dy = abs((a["y1"] + a["y2"]) / 2 - (b["y1"] + b["y2"]) / 2)
                # measured on real tanween: parallel strokes nearly level,
                # side-stepped ~3.4 units; neighbouring letters' fathas differ
                # by dy >= 4 or dx >= 5
                lim = 4.2 if base == "fatha" else 5.5
                if dx < lim and dy < 2.2:
                    a["mark"] = b["mark"] = tan


def map_lines(art_widths, api_lines):
    """Order-preserving map from API word-lines to art lines, skipping ornament lines.

    A surah-header page dedicates one or two drawn lines to the header frame and the
    bismillah; the layout data numbers only word-bearing lines, so numbers drift by
    the count of ornament lines above. Match each API line (expected width from its
    words' letters) to an art line (measured ink width) in order, allowing art lines
    to be skipped at a cost — on ordinary pages the identity mapping wins untouched.
    """
    arts = sorted(art_widths)
    apis = sorted(api_lines)
    if not arts or not apis:
        return {}
    exp = {j: sum(letters(w) for w in api_lines[j]) for j in apis}
    total_ink = sum(art_widths[i] for i in arts)
    alpha = total_ink / max(1e-9, sum(exp.values()))

    INF = float("inf")
    n, m = len(arts), len(apis)
    if m > n:
        return {j: j for j in apis}          # malformed; keep identity
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    SKIP = 1.0
    for i in range(1, n + 1):
        for j in range(0, m + 1):
            # skip art line i (ornament)
            if dp[i - 1][j] + SKIP < dp[i][j]:
                dp[i][j] = dp[i - 1][j] + SKIP
                back[i][j] = "skip"
            if j:
                c = abs(art_widths[arts[i - 1]] - alpha * exp[apis[j - 1]]) \
                    / max(1e-9, alpha * exp[apis[j - 1]])
                if dp[i - 1][j - 1] + c < dp[i][j]:
                    dp[i][j] = dp[i - 1][j - 1] + c
                    back[i][j] = "match"
    mapping, i, j = {}, n, m
    while i and back[i][j]:
        if back[i][j] == "match":
            mapping[arts[i - 1]] = apis[j - 1]
            j -= 1
        i -= 1
    return mapping


def reflow_words(words_by_line, art_widths, prev_tail=None, next_head=None,
                 page_ayahs=None):
    """Redistribute the page's word sequence over the art's text lines by width.

    Surah-opening pages in this print pack the text into fewer, wider lines than any
    public layout records (page 77: 13 art lines vs 14 layout lines), so the layout's
    per-line lists cannot be trusted there. The word ORDER is identical, so partition
    the flow into consecutive per-line groups whose expected widths fit the measured
    line widths. Ornament lines (surah title, bismillah) are the narrow ones and get
    no words.
    """
    api_ids = sorted(words_by_line)
    if not api_ids or not art_widths:
        return words_by_line, {}
    wmax = max(art_widths.values())
    text_lines = [ln for ln in sorted(art_widths) if art_widths[ln] >= 0.72 * wmax]
    if len(api_ids) == len(text_lines):
        return words_by_line, {}          # counts agree; trust the layout's lists
    # The page boundary itself can differ between prints (art page 590 starts at
    # 84:25 while the layout's does at 85:1), so the candidate stream includes the
    # neighbouring pages' edge words, and the fit chooses the window: any prefix
    # may stay unused (previous page's ink) and any suffix likewise.
    core = [w for j in api_ids for w in words_by_line[j]]
    pre = len(prev_tail or [])
    flow = (prev_tail or []) + core + (next_head or [])
    core_end = pre + len(core)
    widths = [art_widths[ln] for ln in text_lines]
    lens = [letters(w) for w in flow]
    # letters() is in calibrated absolute units; the residual scale is spacing/
    # justification overhead (measured median 1.088). Solve once with that seed,
    # then re-estimate from the solution's own window and solve again — an edge
    # page's totals cannot bias the seed the way whole-page ratios did.
    alpha = 1.088
    n, m = len(flow), len(text_lines)
    MAXW = 22                             # words per line never exceed this
    SKIP_W = 0.8                          # dropping a current-page word costs its width
    INF = float("inf")

    # The page's own ayah polygons say exactly which ayahs have ink here: the
    # window must contain every word of the interior ayahs and may only trim
    # within the first and last (page-straddling) ayahs.
    if page_ayahs:
        keys = [(w["surah"], w["ayah"]) for w in flow]
        first, last = page_ayahs[0], page_ayahs[-1]
        idx_first = [i for i, k in enumerate(keys) if k == first]
        idx_last = [i for i, k in enumerate(keys) if k == last]
        start_lo = idx_first[0] if idx_first else 0
        start_hi = (idx_first[-1] + 1) if idx_first else n
        end_lo = idx_last[0] + 1 if idx_last else 0
        end_hi = (idx_last[-1] + 1) if idx_last else n
    else:
        start_lo, start_hi, end_lo, end_hi = 0, n, 0, n

    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(start_lo, start_hi + 1):
        dp[i][0] = 0.0
    for k in range(1, m + 1):
        for i in range(k, n + 1):
            for j in range(max(k - 1, i - MAXW), i):
                if dp[j][k - 1] == INF:
                    continue
                c = dp[j][k - 1] + abs(alpha * sum(lens[j:i]) - widths[k - 1])
                if c < dp[i][k]:
                    dp[i][k] = c
                    back[i][k] = j
    cand = [i for i in range(max(m, end_lo), min(n, end_hi) + 1)
            if dp[i][m] < INF]
    if not cand:
        return words_by_line, {}
    end = min(cand, key=lambda i: dp[i][m])
    bounds, i = [], end
    for k in range(m, 0, -1):
        j = back[i][k]
        bounds.append((j, i))
        i = j
    bounds.reverse()
    return ({ln: flow[j:i] for ln, (j, i) in zip(text_lines, bounds)},
            {"reflowed": True})


def poly_ayahs(edition, page_no):
    """The set of (surah, ayah) a page's polygons draw; empty if unknown."""
    pth = os.path.join(ROOT, "mushafs", edition, "json", "%03d.json" % page_no)
    if not os.path.exists(pth):
        return set()
    try:
        return {(p["surahNumber"], p["ayahNumber"])
                for p in json.load(open(pth))}
    except Exception:
        return set()


def ayah_stream(page_no, cache_dir, page_ayahs):
    """Every word of every ayah the page's polygons draw, in text order.

    The QCF layout's page boundaries can differ from this print by whole
    ayahs, so a fixed-size window of the neighbouring pages' words can miss
    the ones the art actually draws. The polygons name the ayahs; collect
    their words from the pages around this one and let the reflow DP (which
    trims the first and last ayah freely) decide where they sit.
    """
    want = set(page_ayahs or ())
    if not want:
        return []
    out = {}
    for pn in range(max(1, page_no - 2), min(604, page_no + 2) + 1):
        try:
            wl = page_words(pn, cache_dir)
        except Exception:
            continue
        for j in wl:
            for w in wl[j]:
                if (w["surah"], w["ayah"]) in want:
                    out[(w["surah"], w["ayah"], w["pos"])] = w
    return [out[k] for k in sorted(out)]


def polygon_reflow(page_ayahs, ay_ranges, stream, use_qcf=False,
                   free_head=True, free_tail=True):
    """Per-line word lists derived from the ayah polygons themselves.

    Each ayah's polygon says exactly which lines it inks and how wide each portion
    is, so its words partition across those lines by width — no page-level window
    guessing. A page-straddling first (last) ayah keeps a suffix (prefix) of its
    words, sized by its measured ink here.
    """
    per_line = {}
    # per-word QCF advance widths partition far better than letter counts;
    # calibrate their scale against the total drawn width of this page's ayahs
    _q = qcf_widths()

    def _qw(w):
        return _q.get("%d:%d:%d" % (w["surah"], w["ayah"], w["pos"]),
                      2.5 * max(1, letters(w)))
    _tw = _tq = 0.0
    for key in page_ayahs:
        for ln, r in ay_ranges.items():
            if key in r:
                _tw += r[key][1] - r[key][0]
        for w in stream:
            if (w["surah"], w["ayah"]) == key:
                _tq += _qw(w)
    _s = (_tw / _tq) if (_tq and use_qcf) else 1.088
    for idx, key in enumerate(page_ayahs):
        segs = sorted(((ln, r[key]) for ln, r in ay_ranges.items() if key in r),
                      key=lambda t: t[0])
        words_k = [w for w in stream if (w["surah"], w["ayah"]) == key]
        if not segs or not words_k:
            continue
        widths = [x2 - x1 for _, (x1, x2) in segs]
        lens = ([_qw(w) for w in words_k] if use_qcf
                else [letters(w) for w in words_k])
        n, m = len(words_k), len(segs)
        # the first ayah keeps a free prefix only when the PREVIOUS page's
        # polygons also draw it; otherwise every one of its words is here
        free_prefix = idx == 0 and free_head
        free_suffix = idx == len(page_ayahs) - 1 and free_tail
        INF = float("inf")
        dp = [[INF] * (m + 1) for _ in range(n + 1)]
        back = [[0] * (m + 1) for _ in range(n + 1)]
        for i in range(n + 1):
            if i == 0 or free_prefix:
                dp[i][0] = 0.0
        for k in range(1, m + 1):
            for i in range(k, n + 1):
                for j in range(k - 1, i):
                    if dp[j][k - 1] == INF:
                        continue
                    c = dp[j][k - 1] + abs(_s * sum(lens[j:i]) - widths[k - 1])
                    if c < dp[i][k]:
                        dp[i][k] = c
                        back[i][k] = j
        ends = range(m, n + 1) if free_suffix else [n]
        cand = [i for i in ends if dp[i][m] < INF]
        if not cand:
            continue
        end = min(cand, key=lambda i: dp[i][m])
        bounds, i = [], end
        for k in range(m, 0, -1):
            j = back[i][k]
            bounds.append((j, i))
            i = j
        bounds.reverse()
        for (ln, (x1, x2)), (j, i) in zip(segs, bounds):
            per_line.setdefault(ln, []).append((x2, words_k[j:i]))
    return {ln: [w for _, ws in sorted(items, key=lambda t: -t[0]) for w in ws]
            for ln, items in per_line.items()}


def anchored_reflow(words_by_line, art_widths):
    """Re-fit the layout's per-line lists to the drawn line widths, gently.

    The art's line breaks occasionally drift a word or two from the public layout
    mid-page (page 3 lines 8-10). Partition the page's word sequence into the drawn
    lines minimizing width misfit plus a per-word anchor penalty for leaving its
    layout line — an exact page stays exactly as listed, drift moves only where the
    ink demands it.
    """
    api_ids = sorted(words_by_line)
    wmax = max(art_widths.values()) if art_widths else 0
    text_lines = [ln for ln in sorted(art_widths) if art_widths[ln] >= 0.72 * wmax]
    if len(api_ids) != len(text_lines):
        return words_by_line
    flow, api_ord = [], []
    for oi, j in enumerate(api_ids):
        for w in words_by_line[j]:
            flow.append(w)
            api_ord.append(oi)
    widths = [art_widths[ln] for ln in text_lines]
    lens = [letters(w) for w in flow]
    alpha = sum(widths) / max(1e-9, sum(lens))
    ANCHOR = 3.0
    n, m = len(flow), len(text_lines)
    MAXW = 22
    INF = float("inf")
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    pre_pen = [[0.0] * (m + 1)]
    for i in range(1, n + 1):
        pre_pen.append([pre_pen[-1][k] + abs(api_ord[i - 1] - k) * ANCHOR
                        for k in range(m + 1)])
    for k in range(1, m + 1):
        for i in range(k, n - (m - k) + 1):
            for j in range(max(k - 1, i - MAXW), i):
                if dp[j][k - 1] == INF:
                    continue
                c = (dp[j][k - 1] + abs(alpha * sum(lens[j:i]) - widths[k - 1])
                     + (pre_pen[i][k - 1] - pre_pen[j][k - 1]))
                if c < dp[i][k]:
                    dp[i][k] = c
                    back[i][k] = j
    if dp[n][m] == INF:
        return words_by_line
    bounds, i = [], n
    for k in range(m, 0, -1):
        j = back[i][k]
        bounds.append((j, i))
        i = j
    bounds.reverse()
    return {ln: flow[j:i] for ln, (j, i) in zip(text_lines, bounds)}


def tag_ayah_markers(svg, polys_json):
    """Give every ayah medallion its own identified group.

    The art draws each marker as two sibling groups inside #ayah_markers — the
    ornament ring (a scaled glyph) followed by the numeral ink. Markers appear
    in ayah order, so pairing them with the page's sorted ayah list names them.
    The pair is wrapped in <g class="ayah-marker" data-surah data-ayah>, with
    data-kind on the ornament and the numeral separately.
    """
    i = svg.find('<g id="ayah_markers"')
    if i < 0 or not polys_json:
        return svg
    depth = 0
    j = i
    for m in re.finditer(r"<g\b|</g>", svg[i:]):
        depth += 1 if m.group(0) == "<g" else -1
        if depth == 0:
            j = i + m.end()
            break
    block = svg[i:j]

    seen = []
    for pl in polys_json:
        key = (pl["surahNumber"], pl["ayahNumber"])
        if key not in seen:
            seen.append(key)
    seen.sort()

    kids = list(re.finditer(r"<g\b[^>]*>(?:(?!</?g\b).)*</g>", block, re.S))
    pairs = []
    k = 0
    while k < len(kids):
        if "scale(" in kids[k].group(0) and k + 1 < len(kids) \
                and "ayah:x" in kids[k + 1].group(0):
            pairs.append((kids[k], kids[k + 1]))
            k += 2
        else:
            pairs.append((kids[k], None))
            k += 1

    out = []
    pos = 0
    for idx, (orn, dig) in enumerate(pairs):
        su, ay = seen[idx] if idx < len(seen) else (None, None)
        ident = (' data-surah="%d" data-ayah="%d"' % (su, ay)) if su else ""
        out.append(block[pos:orn.start()])
        piece = orn.group(0).replace(
            "<path ", '<path data-kind="ayah-marker-ornament" ', 1)
        if dig is not None:
            piece += block[orn.end():dig.start()]
            piece += dig.group(0).replace(
                "<path ", '<path data-kind="ayah-number" ', 1)
            pos = dig.end()
        else:
            pos = orn.end()
        out.append('<g class="ayah-marker"%s>%s</g>' % (ident, piece))
    out.append(block[pos:])
    return svg[:i] + "".join(out) + svg[j:]


def assign_page(edition, page_no, cache_dir):
    src = os.path.join(ROOT, "mushafs", edition, "svg", "%03d.svg" % page_no)
    page = Page(src)
    words_by_line = page_words(page_no, cache_dir)
    elements = page_elements(page)
    # Ink clipped away by the viewBox is invisible: keep it out of classification
    # and word clustering, but re-emit it unassigned so no ink is ever dropped.
    offcanvas = [e for e in elements if e.get("offcanvas")]
    elements = [e for e in elements if not e.get("offcanvas")]
    for e in offcanvas:
        e["kind"] = "body"
    lines_path = os.path.join(ROOT, "mushafs", edition, "lines", "%03d.json" % page_no)
    lines_info = json.load(open(lines_path)) if os.path.exists(lines_path) else []
    pk, known = part_key_for(page)
    mark_shapes = mark_shape_table()
    classify(elements, lines_info, pk, mark_shapes)
    composite_marks(elements, pk, known)
    baselines = {li["lineNumber"]: li["baseline"] for li in lines_info}

    # A letter BODY belongs to the band its center falls in — the ornate pages'
    # art groups occasionally tag ink with the neighbouring line, which lets a
    # word swallow pieces from the line above or below. Geometry is the truth
    # for bodies (marks are handled by their own re-liner below).
    if lines_info:
        bands = sorted(((li["lineNumber"],
                         li.get("top", li["baseline"] - 12),
                         li.get("bottom", li["baseline"] + 3))
                        for li in lines_info), key=lambda t: t[1])
        for e in elements:
            if not e["line"]:
                continue
            cy = (e["y1"] + e["y2"]) / 2
            best = None
            for ln2, top, bot in bands:
                if top <= cy <= bot:
                    best = ln2
                    break
                d = min(abs(cy - top), abs(cy - bot))
                if best is None or isinstance(best, tuple) and d < best[1]:
                    best = (ln2, d)
            if isinstance(best, tuple):
                # marks float in the inter-band gap by design: snap to nearest
                # band always; a body far from every band keeps its art tag
                best = best[0] if (e["kind"] == "mark" or best[1] < 6.0) else None
            if best and best != e["line"]:
                e["line"] = best

    # A mark belongs to its LETTER, not to whatever line band its ink fell into:
    # a deep kasra under line N sits in line N+1's band and would attach to the
    # word below. Re-line each mark to the nearest overlapping body in ln-1..ln+1.
    bodies_by_line = {}
    for e in elements:
        if e["kind"] == "body" and e["line"]:
            bodies_by_line.setdefault(e["line"], []).append(e)
    for e in elements:
        if e["kind"] != "mark" or e.get("mkpart") or not e["line"]:
            continue
        cx = (e["x1"] + e["x2"]) / 2
        cy = (e["y1"] + e["y2"]) / 2
        # These marks are only ever drawn ABOVE their letter in this art: a damma,
        # waqf sign or iqlab-meem hanging in the gap between two lines belongs to
        # the line BELOW it, never to the word whose ink ends above it.
        lab_pos = e.get("lab") or _raw_label(pk(e)) if pk else e.get("lab")
        above_only = lab_pos in _ABOVE_ONLY
        best = None
        for ln2 in (e["line"] - 1, e["line"], e["line"] + 1):
            for b in bodies_by_line.get(ln2, []):
                if above_only and cy > b["y2"]:
                    continue              # mark below this word: impossible owner
                ov = min(e["x2"], b["x2"]) - max(e["x1"], b["x1"])
                # a mark over a THIN letter (an alef) hangs to its left in this
                # art — plain x-overlap misses the pairing entirely
                thin_near = (b["x2"] - b["x1"]) <= 4.5 and \
                    abs((b["x1"] + b["x2"]) / 2 - cx) <= 3.5
                if ov < 0.3 * (e["x2"] - e["x1"]) and not thin_near:
                    continue
                # distance to the body's natural mark zones (just above its top
                # or just below its bottom) — sitting BESIDE a deep descender is
                # not ownership, so being inside the body's y-band earns no bonus
                vd = (abs(cy - b["y1"]) if above_only
                      else min(abs(cy - b["y1"]), abs(cy - b["y2"])))
                if ln2 != e["line"]:
                    vd += 2.5             # stay on your own line unless clearly closer
                score = (vd, -ov, abs((b["x1"] + b["x2"]) / 2 - cx))
                if best is None or score < best[0]:
                    best = (score, ln2)
        if best is None:
            # no x-overlapping body anywhere: a dot leaning off its letter's
            # edge — take the nearest body sideways
            for ln2 in (e["line"] - 1, e["line"], e["line"] + 1):
                for b in bodies_by_line.get(ln2, []):
                    gap = max(b["x1"] - e["x2"], e["x1"] - b["x2"], 0.0)
                    if gap > 6.0:
                        continue
                    vd = min(abs(cy - b["y1"]), abs(cy - b["y2"]))
                    if ln2 != e["line"]:
                        vd += 2.5
                    score = (vd + gap, 0, 0)
                    if best is None or score < best[0]:
                        best = (score, ln2)
        if best and best[1] != e["line"]:
            e["line"] = best[1]
            for part in e.get("mkmembers", []):
                part["line"] = best[1]
    # Line-break refinement by ink amount: the art sometimes breaks a line a
    # word earlier or later than every public layout. Ink amount per line is
    # immune to justification: move boundary words while both lines' ink-vs-
    # expected errors clearly improve.
    _ink = {}
    for e in elements:
        if e["kind"] == "body" and e.get("line"):
            _ink[e["line"]] = _ink.get(e["line"], 0.0) + (e["x2"] - e["x1"])

    def _ink_refine(wbl):
        lns = sorted(ln for ln in wbl if wbl[ln] and ln in _ink)
        if len(lns) < 2:
            return
        exp = {ln: sum(letters(w) for w in wbl[ln]) for ln in lns}
        k = sum(_ink[ln] for ln in lns) / (sum(exp[ln] for ln in lns) or 1.0)
        for _ in range(4):
            best = None
            for i in range(len(lns) - 1):
                L, L2 = lns[i], lns[i + 1]
                for dirn in (0, 1):
                    src = L if dirn == 0 else L2
                    if len(wbl[src]) < 2:
                        continue
                    wm = wbl[L][-1] if dirn == 0 else wbl[L2][0]
                    dl = -letters(wm) if dirn == 0 else letters(wm)
                    b1 = abs(_ink[L] - k * exp[L])
                    b2 = abs(_ink[L2] - k * exp[L2])
                    a1 = abs(_ink[L] - k * (exp[L] + dl))
                    a2 = abs(_ink[L2] - k * (exp[L2] - dl))
                    gain = (b1 + b2) - (a1 + a2)
                    # both lines must individually get closer to their ink
                    if a1 < b1 and a2 < b2 \
                            and gain > 0.75 * k * letters(wm) \
                            and (best is None or gain > best[0]):
                        best = (gain, L, L2, dirn, wm)
            if best is None:
                break
            _, L, L2, dirn, wm = best
            if dirn == 0:
                wbl[L].pop()
                wbl[L2].insert(0, wm)
                exp[L] -= letters(wm)
                exp[L2] += letters(wm)
            else:
                wbl[L2].pop(0)
                wbl[L].append(wm)
                exp[L2] -= letters(wm)
                exp[L] += letters(wm)

    polys_path = os.path.join(ROOT, "mushafs", edition, "json", "%03d.json" % page_no)
    ay_ranges = (ayah_ranges_per_line(json.load(open(polys_path)), lines_info)
                 if os.path.exists(polys_path) else {})
    # A page's polygons can omit a whole text line (p599 draws 98:6's first
    # ten words on line 1, but its first polygon row starts in line 2's band).
    # The reflow then has nothing to hang that ink on and the words are drawn
    # by no page at all. Ink is the truth: give an unclaimed full-width line
    # to the page's first (above every claimed line) or last (below) ayah, so
    # the partition DP can spread that ayah's words across both lines.
    if ay_ranges and os.path.exists(polys_path):
        _seen0 = []
        for _p0 in json.load(open(polys_path)):
            _k0 = (_p0["surahNumber"], _p0["ayahNumber"])
            if _k0 not in _seen0:
                _seen0.append(_k0)
        _seen0 = sorted(_seen0)
        _ink0 = {}
        for _e0 in elements:
            if _e0["kind"] == "body" and _e0.get("line"):
                _x1, _x2 = _ink0.get(_e0["line"], (_e0["x1"], _e0["x2"]))
                _ink0[_e0["line"]] = (min(_x1, _e0["x1"]), max(_x2, _e0["x2"]))
        if _ink0 and _seen0:
            _wmax0 = max(b - a for a, b in _ink0.values())
            _claimed = set(ay_ranges)
            _lo_c, _hi_c = min(_claimed), max(_claimed)
            for _ln0, (_x1, _x2) in sorted(_ink0.items()):
                if _ln0 in _claimed or _x2 - _x1 < 0.72 * _wmax0:
                    continue
                if _ln0 < _lo_c:
                    _key0 = _seen0[0]
                elif _ln0 > _hi_c:
                    _key0 = _seen0[-1]
                else:
                    continue
                ay_ranges.setdefault(_ln0, {})[_key0] = (_x1, _x2)
    _ay_lines = {}
    for _ln2, _rngs in ay_ranges.items():
        for _key in _rngs:
            _ay_lines.setdefault(_key, set()).add(_ln2)

    # Clustering the same line with the same word list is pure: the boundary
    # hill-climb re-scores whole pages to move ONE word, so without a memo a
    # 15-line page is clustered thousands of times (p350: 8,416 calls, 507s).
    # The key carries a fingerprint of the line's ink so a reclaim pass that
    # turns marks into bodies is never served a stale split.
    _cl_memo = {}

    def _cl(els4, words4, ayr4, alpha4=1.0, use_dots=True):
        key = (id(ayr4), round(alpha4, 4), use_dots, len(els4),
               sum(1 for e in els4 if e["kind"] == "body"),
               tuple((w["surah"], w["ayah"], w["pos"]) for w in words4))
        hit = _cl_memo.get(key)
        if hit is None:
            hit = cluster_line(els4, words4, ayr4, alpha4, use_dots=use_dots)
            _cl_memo[key] = hit
        cls4, dev4 = hit
        # hand out fresh containers: consumers mutate atom["els"] downstream
        return [[{"x1": a4["x1"], "x2": a4["x2"], "els": list(a4["els"])}
                 for a4 in cl4] for cl4 in cls4], dev4

    def _ayah_allowed(w5, ln5):
        # the polygons are the art's own statement of which ayahs occupy which
        # line: a word may never be moved onto a line its ayah does not touch
        rows5 = ay_ranges.get(ln5)
        if not ay_ranges or not rows5:
            return True
        return (w5["surah"], w5["ayah"]) in rows5

    def _count_conflicts(wbl):
        # forward: a wide polygon row whose ayah has no words on the line;
        # reverse: words on a line their ayah's polygon never touches. A lone
        # reverse hit is usually a filtered-out thin polygon row, so it only
        # counts once the disagreement is dense.
        nf = nr = 0
        for _ln, _ws in wbl.items():
            have = {(w["surah"], w["ayah"]) for w in _ws}
            for _key, (_lo, _hi) in ay_ranges.get(_ln, {}).items():
                if _hi - _lo >= 18 and _key not in have:
                    nf += 1
            for _key in have:
                if _key in _ay_lines and _ln not in _ay_lines[_key]:
                    nr += 1
        return nf + (nr if nr >= 3 else 0)

    # only pages where the polygons disagree with the layout get the ink-based
    # boundary moves; everywhere else the layout is already the art's truth
    if ay_ranges and _count_conflicts(words_by_line) >= 3:
        _ink_refine(words_by_line)

    def run_pass(words_by_line, grounded=False):
        assignment, report = [], []
        art_widths = {}
        for ln in {e["line"] for e in elements if e["line"]}:
            bs = [e for e in elements if e["line"] == ln and e["kind"] == "body"]
            art_widths[ln] = (max(b["x2"] for b in bs) - min(b["x1"] for b in bs)) if bs else 0.0
        prev_tail = next_head = None
        try:
            if page_no > 1:
                pw = page_words(page_no - 1, cache_dir)
                # TEXT order, not line order: QCF wraps overflow words onto
                # "lines 1-2" of the same page, which sort first by line and
                # would fall out of a line-ordered tail
                prev_tail = sorted((w for j in pw for w in pw[j]),
                                   key=lambda w: (w["surah"], w["ayah"],
                                                  w["pos"]))[-25:]
            if page_no < 604:
                nw = page_words(page_no + 1, cache_dir)
                next_head = sorted((w for j in nw for w in nw[j]),
                                   key=lambda w: (w["surah"], w["ayah"],
                                                  w["pos"]))[:25]
        except Exception:
            pass
        page_ayahs = None
        if os.path.exists(polys_path):
            seen = []
            for p in json.load(open(polys_path)):
                k = (p["surahNumber"], p["ayahNumber"])
                if k not in seen:
                    seen.append(k)
            page_ayahs = sorted(seen)
        # The layout's own line numbers usually match the art directly — the
        # 15-line KFGQPC grid counts header and bismillah lines too. Trust the
        # identity mapping whenever every layout line has ink and the per-line
        # ink-per-QCF-width densities are mutually consistent; the width-rank
        # heuristics below misfire on multi-surah pages whose short centered
        # lines drop below any "text line" width threshold.
        _qb0 = qcf_widths()
        ident = bool(words_by_line) and \
            all(art_widths.get(_ln, 0) > 0 for _ln in words_by_line)
        # a layout line whose ayahs this page's art doesn't draw (QCF page
        # boundaries can drift a few words against this print) breaks identity
        _drift = False
        _QCF_SUSPECT[0] = False
        if page_ayahs:
            _pa = set(page_ayahs)
            _drift = any((w["surah"], w["ayah"]) not in _pa
                         for _wl in words_by_line.values() for w in _wl)
            # ...and the converse: ink drawn here for an ayah whose words the
            # layout list doesn't carry (they wrapped onto a neighbouring QCF
            # page) — those words must come in through the reflow stream
            _la = {(w["surah"], w["ayah"])
                   for _wl in words_by_line.values() for w in _wl}
            if any(k not in _la for k in _pa):
                _drift = True
            if _drift:
                ident = False
                # the cached QCF advances were paired word-by-word per QCF
                # page; on drift pages that pairing is scrambled — distrust
                # implausible advances here (and only here)
                _QCF_SUSPECT[0] = True
        if ident:
            _rr = []
            for _ln, _wl in words_by_line.items():
                _qs = sum(_qb0.get("%d:%d:%d" % (w["surah"], w["ayah"],
                                                 w["pos"]),
                          2.5 * max(1, letters(w))) for w in _wl)
                _rr.append(art_widths[_ln] / max(1e-9, _qs))
            _md = sorted(_rr)[len(_rr) // 2]
            # every line within a band of the median: a single outlier line
            # (a bismillah paired with real words on a shifted page) breaks
            # identity even when the overall spread looks tame
            ident = all(0.62 * _md <= _v <= 1.6 * _md for _v in _rr)
            # every substantial text line in the ART must be claimed by the
            # layout — an unclaimed full line means the print used one more
            # line than the QCF layout and identity cannot hold (p76)
            if ident:
                _wm = max(art_widths.values())
                ident = all(_ln in words_by_line for _ln, _v in
                            art_widths.items() if _v >= 0.72 * _wm)
        # trigger reflow only when the layout's line count disagrees with the art
        wmax = max(art_widths.values()) if art_widths else 0
        n_text = sum(1 for v in art_widths.values() if v >= 0.72 * wmax)
        reflow_info = {}
        if not ident and page_ayahs \
                and (_drift or len(words_by_line) != n_text):
            stream = ayah_stream(page_no, cache_dir, page_ayahs) or \
                ((prev_tail or [])
                 + [w for j in sorted(words_by_line) for w in words_by_line[j]]
                 + (next_head or []))
            _fh = bool(page_ayahs) and \
                page_ayahs[0] in poly_ayahs(edition, page_no - 1)
            _ft = bool(page_ayahs) and \
                page_ayahs[-1] in poly_ayahs(edition, page_no + 1)

            def _order_repaired(rng):
                # Reading order is strict: once an ayah has ended on a line,
                # it cannot reappear lower down. Where the polygons say ayah A
                # both ends on line N (B starts beside it) AND continues on
                # line N+1 with the very same x-range, one of the two rows is
                # a generator artifact — the alternative is that A owns line N
                # whole. Build that alternative; the ink decides below.
                lns = sorted(rng)
                out = {ln: dict(r) for ln, r in rng.items()}
                changed = False
                for i, ln in enumerate(lns[:-1]):
                    nxt = lns[i + 1]
                    for a in sorted(out.get(ln, {})):
                        if a not in rng.get(nxt, {}):
                            continue
                        if rng[ln][a] != rng[nxt][a]:
                            continue
                        later = [b for b in out[ln] if b > a]
                        if not later:
                            continue
                        lo = min(out[ln][b][0] for b in later)
                        hi = max(out[ln][b][1] for b in later)
                        for b in later:
                            del out[ln][b]
                        out[ln][a] = (min(out[ln][a][0], lo),
                                      max(out[ln][a][1], hi))
                        changed = True
                return out if changed else None

            _alt = _order_repaired(ay_ranges)
            _fl = polygon_reflow(page_ayahs, ay_ranges, stream,
                                 free_head=_fh, free_tail=_ft)
            _fq = polygon_reflow(page_ayahs, ay_ranges, stream, use_qcf=True,
                                 free_head=_fh, free_tail=_ft)
            _fa = _fb = None
            if _alt:
                _ak = sorted({k for r in _alt.values() for k in r})
                _fa = polygon_reflow(_ak, _alt, stream,
                                     free_head=_fh, free_tail=_ft)
                _fb = polygon_reflow(_ak, _alt, stream, use_qcf=True,
                                     free_head=_fh, free_tail=_ft)

            def _flow_dev(fl):
                if not fl:
                    return float("inf")
                t = 0.0
                for _ln, _wl in fl.items():
                    ea = [e for e in elements if e["line"] == _ln]
                    if not ea or not _wl:
                        continue
                    cls, _ = _cl(ea, _wl, ay_ranges.get(_ln), use_dots=False)
                    spans = [(max(a["x2"] for a in cl) - min(a["x1"] for a in cl))
                             if cl else 0.0 for cl in cls]
                    tot = sum(spans)
                    tl = sum(letters(w) for w in _wl) or 1
                    alpha = tot / tl if tot else 1.0
                    t += sum(abs(sp - alpha * letters(w)) / max(alpha, 1e-6)
                             for sp, w in zip(spans, _wl))
                return t
            flowed = None
            _cands = [c for c in (_fl, _fq, _fa, _fb) if c]
            if _cands:
                flowed = min(_cands, key=_flow_dev)
                if _alt and flowed in (_fa, _fb):
                    # the repaired rows won on the ink: adopt them in place so
                    # every later stage sees the same geometry
                    ay_ranges.clear()
                    ay_ranges.update(_alt)
            if flowed:
                words_by_line = flowed
                reflow_info = {"reflowed": True}
        line_map = ({} if (ident or reflow_info)
                    else map_lines(art_widths, words_by_line))
        if os.environ.get("QSVG_DEBUG_MAP"):
            print("MAP ident=%s reflow=%s drift=%s n_text=%d layout=%d map=%s"
                  % (ident, bool(reflow_info), _drift, n_text,
                     len(words_by_line), line_map), file=sys.stderr)


        # The layout's line numbers come from the QCF mushaf, whose breaks
        # can differ from this print by one word (p27: QCF ends line 14 with
        # فإنمآ; KFGQPC starts it on line 15). The ink is the truth: when the
        # per-line ink-per-QCF-width densities of two adjacent lines disagree,
        # trial-cluster both lines with the boundary word moved and keep the
        # move if the actual clustering deviation improves.
        _qb = qcf_widths()
        _rows = []
        for _ln in sorted({e["line"] for e in elements if e["line"]}):
            _wl = words_by_line.get(line_map.get(_ln), []) if line_map else \
                words_by_line.get(_ln, [])
            if _wl and art_widths.get(_ln):
                _rows.append((_ln, _wl))

        def _qsum(_wl):
            if _drift or grounded or reflow_info:
                # drift pages: the raw advance table is scrambled — letters()
                # already distrusts it there
                return sum(letters(_w) for _w in _wl)
            t = 0.0
            for _w in _wl:
                _k = "%d:%d:%d" % (_w["surah"], _w["ayah"], _w["pos"])
                t += _qb.get(_k, 2.5 * max(1, letters(_w)))
            return t

        _thr = 0.08

        def _polyfit(_w, _dst, _dwl):
            # the ayah polygons cap how much of an ayah each line holds: a
            # move is legal only if the destination segment can absorb the
            # word alongside the ayah's words already there
            seg = ay_ranges.get(_dst, {}).get((_w["surah"], _w["ayah"]))
            if not ay_ranges:
                return True
            if seg is None:
                return False
            tot = letters(_w) + sum(letters(x) for x in _dwl
                                    if (x["surah"], x["ayah"])
                                    == (_w["surah"], _w["ayah"]))
            return tot <= 1.45 * (seg[1] - seg[0]) + 6.0

        _dev_cache = {}

        def _piece_pen(_ln, _wl, cls):
            # how badly the split had to violate the words' own ligature counts
            pen = 0.0
            for _w8, cl8 in zip(_wl, cls):
                bods8 = [e for a8 in cl8 for e in a8["els"]
                         if e["kind"] == "body"]
                eff8 = []
                for b8 in bods8:
                    wb8 = b8["x2"] - b8["x1"]
                    hb8 = b8["y2"] - b8["y1"]
                    if not any(o8 is not b8
                               and min(o8["x2"], b8["x2"]) - max(o8["x1"], b8["x1"])
                               >= 0.6 * wb8
                               and (o8["x2"] - o8["x1"]) > wb8
                               and hb8 <= (o8["y2"] - o8["y1"]) + 1.0
                               for o8 in bods8):
                        eff8.append(b8)
                ns8 = max(1, len(segment_word(_w8["uthmani"])))
                if len(eff8) > ns8:        # holding ink its text cannot own
                    pen += 0.5 * (len(eff8) - ns8)
            return pen

        def _dev1(_ln, _wl):
            key = (_ln, tuple(id(w) for w in _wl))
            if key not in _dev_cache:
                ea = [e for e in elements if e["line"] == _ln]
                if _wl and ea:
                    cls8, dev8 = _cl(ea, list(_wl), ay_ranges.get(_ln),
                                     use_dots=False)
                    _dev_cache[key] = dev8 + _piece_pen(_ln, list(_wl), cls8)
                else:
                    _dev_cache[key] = 0.0
            return _dev_cache[key]

        def _devpair(_lna, _wla, _lnb, _wlb):
            return _dev1(_lna, _wla) + _dev1(_lnb, _wlb)

        for _pass in range(3):
            _shifted = False
            for _i in range(len(_rows) - 1):
                _lnr, _wr = _rows[_i]
                _lnl, _wll = _rows[_i + 1]
                if not _wr or not _wll:
                    continue
                sr = art_widths[_lnr] / max(1e-9, _qsum(_wr))
                sl = art_widths[_lnl] / max(1e-9, _qsum(_wll))
                if abs(math.log(max(sr, 1e-6) / max(sl, 1e-6))) < 0.06:
                    continue
                d0 = _devpair(_lnr, _wr, _lnl, _wll)
                if sr < sl and len(_wr) > 1 \
                        and _polyfit(_wr[-1], _lnl, _wll):  # upper crowded
                    d1 = _devpair(_lnr, _wr[:-1], _lnl, [_wr[-1]] + _wll)
                    if d1 < d0 - _thr:
                        _wll.insert(0, _wr.pop())
                        _shifted = True
                elif sr > sl and len(_wll) > 1 \
                        and _polyfit(_wll[0], _lnr, _wr):   # lower crowded
                    d1 = _devpair(_lnr, _wr + [_wll[0]], _lnl, _wll[1:])
                    if d1 < d0 - _thr:
                        _wr.append(_wll.pop(0))
                        _shifted = True
            if not _shifted:
                break

        for ln in sorted({e["line"] for e in elements if e["line"]}):
            els = [e for e in elements if e["line"] == ln]
            words = words_by_line.get(line_map.get(ln), []) if line_map else \
                words_by_line.get(ln, [])
            clusters, deviation = _cl(els, words, ay_ranges.get(ln))

            # Repair pass: an overflowing last word is drawn small and raised, so its ink
            # was classified as marks and its cluster came out far too narrow. Reclaim
            # word-sized mark elements from the starved word's expected region as bodies
            # and recluster the line once.
            if words and clusters:
                span_line = (max(a["x2"] for cl in clusters for a in cl if cl)
                             - min(a["x1"] for cl in clusters for a in cl if cl))
                alpha_l = span_line / sum(letters(w) for w in words)
                reclaimed = False
                for k, (w, cl) in enumerate(zip(words, clusters)):
                    if not cl:
                        continue
                    ratio = (cl[0]["x2"] - cl[-1]["x1"]) / max(1e-9, alpha_l * letters(w))
                    if ratio >= 0.4:
                        continue
                    lo = (clusters[k + 1][0]["x2"] - 2 if k + 1 < len(clusters)
                          and clusters[k + 1] else -1e9)
                    hi = (clusters[k - 1][-1]["x1"] + 2 if k > 0
                          and clusters[k - 1] else 1e9)
                    for e in els:
                        if (e["kind"] == "mark" and not e.get("mkpart")
                                and (e["x2"] - e["x1"]) >= 3.5
                                and e.get("lab") not in
                                ("fatha", "kasra", "fathatan", "kasratan",
                                 "damma", "dammatan")
                                and lo <= (e["x1"] + e["x2"]) / 2 <= hi):
                            for x in [e] + e.get("mkmembers", []):
                                x["kind"] = "body"
                                x.pop("mkpart", None)
                            e.pop("mkmembers", None)
                            reclaimed = True
                if reclaimed:
                    clusters, deviation = _cl(els, words, ay_ranges.get(ln))

            # Layout-vs-geometry mismatch retry: when a word's span is far off what its
            # letters predict, the line's width calibration is suspect — re-solve under
            # alternative calibrations and keep the solution with the fewest violations.
            def violations(cls):
                if not words or not cls:
                    return 99, 0.0
                span_l = (max(a["x2"] for cl in cls for a in cl if cl)
                          - min(a["x1"] for cl in cls for a in cl if cl))
                al = span_l / sum(letters(w) for w in words)
                v = 0
                worst = 0.0
                for w, cl in zip(words, cls):
                    if not cl:
                        v += 2
                        continue
                    r = (cl[0]["x2"] - cl[-1]["x1"]) / max(1e-9, al * letters(w))
                    if r < 0.4 or (r > 2.4 and len(cl) > len(segment_word(w["uthmani"]))):
                        v += 1
                    worst = max(worst, abs(r - 1))
                return v, worst

            if words:
                v0, w0 = violations(clusters)
                if v0:
                    best = (v0, w0, clusters, deviation)
                    for sc in (0.9, 1.1, 0.8, 1.2):
                        cl2, dev2 = _cl(els, words, ay_ranges.get(ln), sc)
                        v2, w2 = violations(cl2)
                        if (v2, w2) < (best[0], best[1]):
                            best = (v2, w2, cl2, dev2)
                    clusters, deviation = best[2], best[3]
            flags = []
            if not words:
                flags.append("no-words-for-line")       # surah header / bismillah art
            if len(clusters) != len(words) and words:
                flags.append("count-mismatch:%d-clusters" % len(clusters))
            # completeness: every word must own a sensible share of the line's ink
            if words and clusters:
                span_line = (max(a["x2"] for cl in clusters for a in cl)
                             - min(a["x1"] for cl in clusters for a in cl))
                alpha_l = span_line / sum(letters(w) for w in words)
            for w, cl in zip(words, clusters):
                if not cl:
                    flags.append("word-missing:%d:%d:%d" % (w["surah"], w["ayah"], w["pos"]))
                    continue
                if not any(e["kind"] == "body" for a in cl for e in a["els"]):
                    flags.append("marks-only-word:%d" % w["pos"])
                ratio = (cl[0]["x2"] - cl[-1]["x1"]) / max(1e-9, alpha_l * letters(w))
                # Oversize alone is legal — a line-end word can carry a huge kashida —
                # unless the word also holds more pieces than its letters justify.
                over = ratio > 2.4 and len(cl) > len(segment_word(w["uthmani"]))
                if ratio < 0.4 or over:
                    flags.append("word-size:%d:%d:%d(x%.1f)"
                                 % (w["surah"], w["ayah"], w["pos"], ratio))
                pr = (ay_ranges.get(ln) or {}).get((w["surah"], w["ayah"])) \
                    if ay_ranges else None
                if pr:
                    n_out = sum(1 for a in cl if not (
                        pr[0] - 1.5 <= (a["x1"] + a["x2"]) / 2 <= pr[1] + 1.5))
                    if n_out:
                        flags.append("polygon:%d:%d:%d(%d out)"
                                     % (w["surah"], w["ayah"], w["pos"], n_out))
                # A word taller than ~1.5 line bands holds ink from another
                # line: always a defect, never calligraphy.
                els_cl = [e for a in cl for e in a["els"]]
                hh = (max(e["y2"] for e in els_cl) - min(e["y1"] for e in els_cl))
                band = None
                for _li in lines_info:
                    if _li["lineNumber"] == ln:
                        band = (_li.get("height")
                                or (_li["bottom"] - _li["top"]))
                if band and hh > 1.55 * band:
                    flags.append("word-height:%d:%d:%d(x%.1f)"
                                 % (w["surah"], w["ayah"], w["pos"], hh / band))
                segs = segment_word(w["uthmani"])
                groups, cost = align_segs_atoms(cl, segs)
                if cost > 0.6:
                    flags.append("ligatures:%d(cost=%.1f)" % (w["pos"], cost))
                for gi, (g_atoms, g_segs) in enumerate(groups):
                    if not g_atoms:
                        continue
                    merged = {"text": "".join(s["text"] for s in g_segs),
                              "marks": [mk for s in g_segs for mk in s["marks"]],
                              "bad": any(s["bad"] for s in g_segs)}
                    for atom in g_atoms:
                        atom["seg"] = merged
                        atom["lig"] = gi
                    if not label_marks(g_atoms, merged["marks"],
                                       baselines.get(ln)) or merged["bad"]:
                        flags.append("marks:%d" % w["pos"])
                assignment.append((w, cl))
            for cl in clusters[len(words):]:
                assignment.append((None, cl))
            if not words:
                for cl in clusters:
                    assignment.append((None, cl))
            hard = [f for f in flags if not f.startswith("marks:")]
            if reflow_info:
                hard = hard + ["page-reflowed"] if ln == min(
                    {e["line"] for e in elements if e["line"]}) else hard
            report.append({"line": ln, "words": len(words), "clusters": len(clusters),
                           "deviation": None if deviation == float("inf")
                           else round(deviation, 2),
                           "flags": hard,
                           "marks_unmatched": len(flags) - len(hard),
                           "review": bool(hard) or deviation == float("inf")
                           or deviation > 0.55})
        nviol = sum(1 for r in report for f in r.get("flags", [])
                    if f.startswith(("word-size", "word-missing")))
        return assignment, report, nviol

    def _anom_count(a):
        # number of words failing width or budget checks — the audit's view
        n = 0
        rows = {}
        for w2, at2 in a:
            if not w2:
                continue
            els2 = [e for a3 in at2 for e in a3["els"]]
            if els2:
                rows.setdefault(els2[0].get("line"), []).append((w2, els2))
        for ln2, sub in rows.items():
            tq = sum(letters(w2) for w2, _ in sub) or 1.0
            ta = sum(max(e["x2"] for e in els2) - min(e["x1"] for e in els2)
                     for _, els2 in sub)
            for w2, els2 in sub:
                sp = max(e["x2"] for e in els2) - min(e["x1"] for e in els2)
                rr = sp / (letters(w2) / tq * ta) if ta else 1.0
                bad = rr < 0.6 or rr > 1.6
                c3 = w2["uthmani"].count
                hv = sum(1 for e in els2 if e.get("mark") in
                         ("fatha", "kasra", "fathatan", "kasratan")
                         and not e.get("mkpart"))
                wv = (c3("\u064e") + c3("\u0650") + c3("\u064b")
                      + c3("\u064d") + c3("\u08f0") + c3("\u08f2"))
                hd = sum(1 for e in els2 if e.get("mark") in
                         ("damma", "dammatan") and not e.get("mkpart"))
                wd = c3("\u064f") + c3("\u064c") + c3("\u08f1")
                if bad or hv != wv or hd != wd:
                    n += 1
        return n

    def _anom_lines(a, width_only=False):
        # lines holding a word whose assigned span disagrees badly
        # with its QCF share — the tell of a one-word break miss
        rows = {}
        for w2, at2 in a:
            if not w2:
                continue
            els2 = [e for a3 in at2 for e in a3["els"]]
            if els2:
                rows.setdefault(els2[0].get("line"), []).append(
                    (w2, els2))
        bad = set()
        for ln2, sub in rows.items():
            tq = sum(letters(w2) for w2, _ in sub) or 1.0
            ta = sum(max(e["x2"] for e in els2)
                     - min(e["x1"] for e in els2)
                     for _, els2 in sub)
            for w2, els2 in sub:
                sp = (max(e["x2"] for e in els2)
                      - min(e["x1"] for e in els2))
                rr = sp / (letters(w2) / tq * ta) if ta else 1.0
                if rr < 0.6 or rr > 1.6:
                    bad.add(ln2)
                if width_only:
                    continue
                c3 = w2["uthmani"].count
                hv = sum(1 for e in els2 if e.get("mark") in
                         ("fatha", "kasra", "fathatan", "kasratan")
                         and not e.get("mkpart"))
                wv = (c3("\u064e") + c3("\u0650") + c3("\u064b")
                      + c3("\u064d") + c3("\u08f0") + c3("\u08f2"))
                hd = sum(1 for e in els2 if e.get("mark") in
                         ("damma", "dammatan") and not e.get("mkpart"))
                wd = c3("\u064f") + c3("\u064c") + c3("\u08f1")
                if hv != wv or hd != wd:
                    bad.add(ln2)
        return bad

    def _overcap_end(a, ln):
        # slash marks beyond the text budget on a line's LAST word: the tell
        # that the next line's first word was really drawn at this line's end
        rows = {}
        for w2, at2 in a:
            if not w2:
                continue
            els2 = [e for a3 in at2 for e in a3["els"]]
            if els2:
                rows.setdefault(els2[0].get("line"), []).append((w2, els2))
        sub = rows.get(ln)
        if not sub:
            return 0
        w2, els2 = min(sub, key=lambda t: min(e["x1"] for e in t[1]))
        c3 = w2["uthmani"].count
        hv = sum(1 for e in els2 if e.get("mark") in
                 ("fatha", "kasra", "fathatan", "kasratan")
                 and not e.get("mkpart"))
        wv = (c3("\u064e") + c3("\u0650") + c3("\u064b")
              + c3("\u064d") + c3("\u08f0") + c3("\u08f2"))
        return max(0, hv - wv)

    def _hillclimb(wbl, a2, r2, v2, d2, mode="conflict"):
        # single-word boundary hill-climb, truth-scored by run_pass: any
        # per-line word list can miss a break by one word; try shifting one
        # word across each anomalous boundary and keep real improvements
        n2 = _anom_count(a2)
        for _ in range(8):
            anoms = _anom_lines(a2, width_only=(mode == "width"))
            if not anoms:
                break
            lns3 = sorted(ln3 for ln3 in wbl if wbl[ln3])
            bestmv = None
            for i3 in range(len(lns3) - 1):
                La, Lb = lns3[i3], lns3[i3 + 1]
                if La not in anoms and Lb not in anoms:
                    continue
                for dirn3 in (0, 1):
                    src = La if dirn3 == 0 else Lb
                    if len(wbl[src]) < 2:
                        continue
                    if dirn3 == 0:
                        if not _ayah_allowed(wbl[La][-1], Lb):
                            continue
                    elif not _ayah_allowed(wbl[Lb][0], La):
                        continue
                    trial = {ln3: list(ws3)
                             for ln3, ws3 in wbl.items()}
                    if dirn3 == 0:
                        trial[Lb].insert(0, trial[La].pop())
                    else:
                        trial[La].append(trial[Lb].pop(0))
                    a4, r4, v4 = run_pass(trial)
                    d4 = sum((r.get("deviation") or 3.0)
                             for r in r4)
                    n4 = _anom_count(a4)
                    if dirn3 == 1 and _overcap_end(a2, La) >= 2:
                        n4 -= 3     # strong boundary-orphan signal
                    if mode == "width":
                        ok4 = v4 <= v2 and (n4 < n2 or
                                            (n4 == n2 and d4 < d2 - 0.05))
                    else:
                        ok4 = (v4 < v2 or (v4 == v2 and d4 < d2 - 0.05)
                               or (v4 == v2 and n4 <= n2 - 2
                                   and d4 < d2 + 0.5))
                    if ok4 and (bestmv is None
                                or (v4, n4, d4) < bestmv[0]):
                        bestmv = ((v4, n4, d4), trial, a4, r4)
            if bestmv is None:
                break
            (v2, n2, d2), wbl, a2, r2 = bestmv
        return wbl, a2, r2, v2, d2

    assignment, report, nviol = run_pass(words_by_line)
    # The art's line breaks can drift from the public layout even mid-page; the
    # ayah polygons are the art's own truth. Dense violations => re-derive the
    # per-line word lists from the polygons and keep the better assignment.
    layout_conflicts = _count_conflicts(words_by_line) if ay_ranges else 0
    if (nviol >= 3 or layout_conflicts) and os.path.exists(polys_path):
        seen = []
        for p in json.load(open(polys_path)):
            k = (p["surahNumber"], p["ayahNumber"])
            if k not in seen:
                seen.append(k)
        try:
            pw = page_words(page_no - 1, cache_dir) if page_no > 1 else {}
            prev_tail = sorted((w for j in pw for w in pw[j]),
                               key=lambda w: (w["surah"], w["ayah"],
                                              w["pos"]))[-25:]
            nw = page_words(page_no + 1, cache_dir) if page_no < 604 else {}
            next_head = sorted((w for j in nw for w in nw[j]),
                               key=lambda w: (w["surah"], w["ayah"],
                                              w["pos"]))[:25]
        except Exception:
            prev_tail, next_head = [], []
        stream = ayah_stream(page_no, cache_dir, sorted(seen)) or \
            (prev_tail + [w for j in sorted(words_by_line)
                          for w in words_by_line[j]] + next_head)
        _sk = sorted(seen)
        flowed = polygon_reflow(
            _sk, ay_ranges, stream,
            free_head=bool(_sk) and _sk[0] in poly_ayahs(edition, page_no - 1),
            free_tail=bool(_sk) and _sk[-1] in poly_ayahs(edition, page_no + 1))
        if flowed:
            if layout_conflicts >= 3:
                _ink_refine(flowed)
            a2, r2, v2 = run_pass(flowed, grounded=True)
            d1 = sum((r.get("deviation") or 3.0) for r in report)
            d2 = sum((r.get("deviation") or 3.0) for r in r2)

            if layout_conflicts >= 3 and v2 <= nviol:
                flowed, a2, r2, v2, d2 = _hillclimb(flowed, a2, r2, v2, d2)


            c2 = _count_conflicts(flowed)
            if v2 < nviol or (layout_conflicts and v2 <= nviol
                              and (d2 < d1 or c2 < layout_conflicts)):
                for r in r2:
                    r.setdefault("flags", []).append("line-reflowed") if r is r2[0] else None
                assignment, report, nviol = a2, r2, v2

    if _anom_lines(assignment, width_only=True):
        # a crushed or bloated word without polygon disagreement still marks a
        # missed break (a crowded line): hill-climb the current lists
        cur_wbl = {}
        for w4, at4 in assignment:
            if not w4:
                continue
            els4 = [e for a4 in at4 for e in a4["els"]]
            if els4:
                cur_wbl.setdefault(els4[0].get("line"), []).append(w4)
        d0 = sum((r.get("deviation") or 3.0) for r in report)
        _, a5, r5, v5, d5 = _hillclimb(cur_wbl, assignment, report, nviol, d0,
                                       mode="width")
        assignment, report, nviol = a5, r5, v5

    assignment = assignment + [(None, [{"els": [e]}]) for e in offcanvas]
    labeled, total_marks = apply_shape_labels(page, assignment, baselines)

    # ------------------------------------------------------------------
    # Global mark reconciliation. The text of each word fixes exactly how
    # many marks of each family it carries; geometry alone keeps mis-homing
    # marks that hang in the gap between lines or over a neighbour's edge.
    # Assign every identity-strong mark to the best word that still has
    # capacity for it, considering words on the mark's own line and the two
    # neighbouring lines within an x-window. One mechanism instead of a
    # rule per failure mode.
    # ------------------------------------------------------------------
    _FAM = {"fatha": "slash", "kasra": "slash", "damma": "damma",
            "fathatan": "slash", "kasratan": "slash", "dammatan": "damma",
            "sukun": "sukun", "hamza": "hamza", "wasla": "wasla",
            "small-alef": "small-alef", "maddah": "maddah",
            "shadda": "shadda", "small-circle": "small-circle",
            "meem-iqlab": "meem-iqlab", "pause": "pause",
            "small-waw": "small-waw", "small-ya": "small-ya"}
    # small-waw/small-ya are SUBSCRIPT letters (ride at or below baseline)
    _ABOVE_FAM = {"damma", "sukun", "wasla", "small-alef", "maddah", "shadda",
                  "small-circle", "meem-iqlab", "pause"}

    def _cap(txt, fam):
        c = txt.count
        if fam == "slash":
            # tanween fathatan/kasratan are drawn as stroke PAIRS in this art
            return (c("\u064e") + c("\u0650")
                    + c("\u064b") + c("\u064d")
                    + c("\u08f0") + c("\u08f2"))
        if fam == "damma":
            return c("\u064f") + c("\u064c") + c("\u08f1")
        if fam == "sukun":
            return c("\u0652") + c("\u06e1")
        if fam == "hamza":
            # bare \u0621 is a LETTER body in this art, not a mark
            return (sum(c(x) for x in "\u0623\u0625\u0624\u0626")
                    + c("\u0654") + c("\u0655"))
        if fam == "wasla":
            return c("\u0671")
        if fam == "small-alef":
            return c("\u0670")
        if fam == "maddah":
            return c("\u0653") + c("\u06e4")
        if fam == "shadda":
            return c("\u0651")
        if fam == "small-circle":
            return c("\u06df") + c("\u06e0")
        if fam == "meem-iqlab":
            return c("\u06e2") + c("\u06ed")
        if fam == "pause":
            return sum(c(x) for x in "\u06d6\u06d7\u06d8\u06d9\u06da\u06db\u06dc")
        if fam == "small-waw":
            return c("\u06e5")
        if fam == "small-ya":
            return c("\u06e6") + c("\u06e7")
        return 0

    wrec = []
    for w, at in assignment:
        if not w:
            continue
        els = [e for a in at for e in a["els"]]
        bods = [e for e in els if e["kind"] == "body"]
        if not bods:
            continue
        wrec.append({
            "w": w, "at": at, "els": els,
            "line": bods[0].get("line"),
            "x1": min(e["x1"] for e in bods), "x2": max(e["x2"] for e in bods),
            "top": min(e["y1"] for e in bods), "bot": max(e["y2"] for e in bods),
        })

    fams = {}
    for r in wrec:
        for e in r["els"]:
            fam = _FAM.get(e.get("mark"))
            if not fam or e.get("mkpart") or e.get("mkmembers"):
                continue
            fams.setdefault(fam, []).append((e, r))

    for fam, marks in fams.items():
        caps = {id(r): _cap(r["w"]["uthmani"], fam) for r in wrec}
        pairs = []
        for e, home in marks:
            cx = (e["x1"] + e["x2"]) / 2
            cy = (e["y1"] + e["y2"]) / 2
            for r in wrec:
                if r["line"] is None or home["line"] is None:
                    continue
                if abs(r["line"] - home["line"]) > 1:
                    continue
                rare = fam in ("pause", "small-ya", "small-waw",
                               "meem-iqlab", "wasla", "maddah")
                win = 6.0 if rare else 3.0
                if not (r["x1"] - win < cx < r["x2"] + win):
                    continue
                if fam == "slash" and r is not home \
                        and r["line"] != home["line"]:
                    continue    # slashes cross lines only via strict
                                # surplus->deficit capacity repair
                if fam in _ABOVE_FAM and cy > r["bot"]:
                    continue                        # above-marks never sit below
                vz = (abs(cy - r["top"]) if fam in _ABOVE_FAM
                      else min(abs(cy - r["top"]), abs(cy - r["bot"])))
                if r is home:
                    pen = 0.0
                elif r["line"] == home["line"]:
                    pen = 1.5             # neighbour word, same line: cheap
                else:
                    # rare identity-certain families follow the text anywhere
                    pen = 2.0 if rare else 6.0
                cost = vz + pen
                pairs.append((cost, id(e), e, home, r))
        pairs.sort(key=lambda t: t[0])
        placed = set()
        # two rounds: honour capacities first; a mark nobody had room for then
        # goes to its cheapest candidate that STILL has capacity (its home word
        # is over budget by construction, so staying put is the worst choice)
        for _round in (0, 1):
            for cost, eid_, e, home, r in pairs:
                if eid_ in placed or caps.get(id(r), 0) <= 0:
                    continue
                placed.add(eid_)
                caps[id(r)] -= 1
                if r is home:
                    continue
                for a in home["at"]:                # move the element across
                    if e in a["els"]:
                        a["els"].remove(e)
                        break
                home["els"].remove(e)
                tgt = min(r["at"], key=lambda a2: min(abs((x["x1"] + x["x2"]) / 2
                          - (e["x1"] + e["x2"]) / 2) for x in a2["els"])
                          if a2["els"] else 1e9)
                tgt["els"].append(e)
                r["els"].append(e)

    # Capacity repair: greedy order can keep a neighbour's stray and bump the
    # word's own mark instead (equal counts, wrong members). While a word holds
    # more of a family than its text allows and a candidate within reach has
    # room, hand over the member whose relocation costs least.
    _labs_by_fam = {}
    for _lab, _f in _FAM.items():
        _labs_by_fam.setdefault(_f, []).append(_lab)
    for fam in fams:
        labs = tuple(_labs_by_fam.get(fam, ()))
        for _ in range(3):
            moved = False
            for r in wrec:
                capr = _cap(r["w"]["uthmani"], fam)
                mine = [e for e in r["els"] if e.get("mark") in labs
                        and not e.get("mkpart") and not e.get("mkmembers")]
                if len(mine) <= capr:
                    continue
                best = None
                for e in mine:
                    cx = (e["x1"] + e["x2"]) / 2
                    cy = (e["y1"] + e["y2"]) / 2
                    for r2 in wrec:
                        if r2 is r or r2["line"] is None or r["line"] is None:
                            continue
                        if abs(r2["line"] - r["line"]) > 1:
                            continue
                        if not (r2["x1"] - 12.0 < cx < r2["x2"] + 12.0):
                            continue
                        if fam in _ABOVE_FAM and cy > r2["bot"]:
                            continue
                        n2 = sum(1 for x in r2["els"] if x.get("mark") in labs
                                 and not x.get("mkpart"))
                        if n2 >= _cap(r2["w"]["uthmani"], fam):
                            continue
                        vz = (abs(cy - r2["top"]) if fam in _ABOVE_FAM
                              else min(abs(cy - r2["top"]), abs(cy - r2["bot"])))
                        vz += 0.0 if r2["line"] == r["line"] else 3.0
                        if best is None or vz < best[0]:
                            best = (vz, e, r2)
                if best and best[0] < 12.0:
                    _, e, r2 = best
                    for a in r["at"]:
                        if e in a["els"]:
                            a["els"].remove(e)
                            break
                    r["els"].remove(e)
                    tgt = min(r2["at"], key=lambda a2: min(abs((x["x1"] + x["x2"]) / 2
                              - (e["x1"] + e["x2"]) / 2) for x in a2["els"])
                              if a2["els"] else 1e9)
                    tgt["els"].append(e)
                    r2["els"].append(e)
                    moved = True
            if not moved:
                break

    # a tanween's two strokes (and a dammatan's two curls) present as ONE
    # mark: the top piece is the master, its twin becomes a part. The text
    # says how many tanweens the word carries — pairs of plain damma/fatha/
    # kasra beyond the word's singles budget ARE its tanweens.
    for r in wrec:
        txt = r["w"]["uthmani"]
        for single, tan, chars_s, chars_t in (
                ("damma", "dammatan", "\u064f", "\u064c\u08f1"),):
            want_t = sum(txt.count(ch) for ch in chars_t)
            if not want_t:
                continue
            singles = [e for e in r["els"] if e.get("mark") == single
                       and not e.get("mkpart")]
            want_s = sum(txt.count(ch) for ch in chars_s)
            spare = len(singles) - want_s
            while spare >= 2 and want_t > 0:
                best = None
                for i, a in enumerate(singles):
                    for b in singles[i + 1:]:
                        dx = abs((a["x1"] + a["x2"]) / 2 - (b["x1"] + b["x2"]) / 2)
                        dy = abs((a["y1"] + a["y2"]) / 2 - (b["y1"] + b["y2"]) / 2)
                        if dx < 8.0 and dy < 7.0 and (best is None
                                                      or dx + dy < best[0]):
                            best = (dx + dy, a, b)
                if not best:
                    break
                _, a, b = best
                a["mark"] = b["mark"] = tan
                singles.remove(a)
                singles.remove(b)
                spare -= 2
                want_t -= 1
        # fathatan/kasratan: the table labels every slash "fatha" or "kasra"
        # regardless of position, so pool BOTH kinds; the pair's position
        # against the body midline says which tanween it is
        want_ft = txt.count("\u064b") + txt.count("\u08f0")
        want_kt = txt.count("\u064d") + txt.count("\u08f2")
        if want_ft or want_kt:
            pool = [e for e in r["els"] if e.get("mark") in ("fatha", "kasra")
                    and not e.get("mkpart") and not e.get("mkmembers")]
            spare = (len(pool) - txt.count("\u064e") - txt.count("\u0650"))
            mid = (r["top"] + r["bot"]) / 2
            while (spare >= 2 or want_ft or want_kt) and (want_ft or want_kt):
                best = None
                for i, a in enumerate(pool):
                    for b in pool[i + 1:]:
                        dx = abs((a["x1"] + a["x2"]) / 2
                                 - (b["x1"] + b["x2"]) / 2)
                        dy = abs((a["y1"] + a["y2"]) / 2
                                 - (b["y1"] + b["y2"]) / 2)
                        if dx < 8.0 and dy < 7.0 and (best is None
                                                      or dx + dy < best[0]):
                            best = (dx + dy, a, b)
                if not best:
                    break
                _, a, b = best
                if spare < 2:
                    # the plain budget is short (a vowel of this word is still
                    # missing), so only unmistakable stacking proves a tanween
                    dxb = abs((a["x1"] + a["x2"]) / 2 - (b["x1"] + b["x2"]) / 2)
                    dyb = abs((a["y1"] + a["y2"]) / 2 - (b["y1"] + b["y2"]) / 2)
                    if not (dxb < 4.5 and dyb < 5.0):
                        break
                pcy = (a["y1"] + a["y2"] + b["y1"] + b["y2"]) / 4
                if want_kt and (not want_ft or pcy > mid):
                    tan = "kasratan"
                    want_kt -= 1
                else:
                    tan = "fathatan"
                    want_ft -= 1
                a["mark"] = b["mark"] = tan
                pool.remove(a)
                pool.remove(b)
                spare -= 2
        for lab in ("fathatan", "kasratan", "dammatan"):
            grp = [e for e in r["els"] if e.get("mark") == lab
                   and not e.get("mkpart")]
            grp.sort(key=lambda e: (e["y1"] + e["y2"]))
            i = 0
            while i + 1 < len(grp):
                master, part = grp[i], grp[i + 1]
                dx = abs((master["x1"] + master["x2"]) / 2
                         - (part["x1"] + part["x2"]) / 2)
                dy = abs((master["y1"] + master["y2"]) / 2
                         - (part["y1"] + part["y2"]) / 2)
                if dx < 8.0 and dy < 7.0:
                    part["mkpart"] = True
                    master.setdefault("mkmembers", []).append(part)
                    i += 2
                else:
                    i += 1

    # muanaqah (\u06db): drawn as a floating dot-trio well above the word; its
    # ink matches letter-dot shapes, so only the text can name it
    for r in wrec:
        n_mu = r["w"]["uthmani"].count("\u06db")
        if not n_mu:
            continue
        cands = [e for e in r["els"]
                 if e.get("mark") in ("dot", "two-dots", "three-dots")
                 and not e.get("mkpart")
                 and (e["y1"] + e["y2"]) / 2 < r["top"] - 2.0]
        # The sign is ONE stop drawn as a tight triangle of dots, and a word
        # can have a real letter dot floating up there too — the fa of فِيهِ.
        # Renaming every candidate turns one sign into three stops and eats
        # the letter's dot as well, so group the ink first and spend exactly
        # the number of signs the text asks for, highest cluster first.
        cands.sort(key=lambda e: (e["y1"] + e["y2"]) / 2)
        groups = []
        for e in cands:
            cx = (e["x1"] + e["x2"]) / 2
            cy = (e["y1"] + e["y2"]) / 2
            for g in groups:
                if any(abs(cx - (o["x1"] + o["x2"]) / 2) <= 6.0
                       and abs(cy - (o["y1"] + o["y2"]) / 2) <= 6.0
                       for o in g):
                    g.append(e)
                    break
            else:
                groups.append([e])
        for g in groups[:n_mu]:
            g.sort(key=lambda e: -e["x1"])
            g[0]["mark"] = "pause"
            for x in g[1:]:
                x["mkpart"] = True    # welded twins count through their master

    # Every waqf sign floats above the line, clear of the letters. Most of
    # them are ligatures of real letters — قلى, صلى, the lone م — so the
    # classifier reads their ink as a letter and the word ends up one piece
    # heavy and one pause short, with the qaf's two dots counted as letter
    # dots on top of that. Nothing in the ink says "this is a stop"; only the
    # text does. So take the COUNT from the text and the POSITION from the
    # ink: pieces standing clear above the word's own letters.
    # The stop signs only. U+06DD ends an ayah and U+06DE (۞) marks a rub
    # el hizb: both are ornaments, not stops, and turning them into pause
    # marks invents a stop the text never asked for.
    _WAQF = "\u06d6\u06d7\u06d8\u06d9\u06da\u06dc"
    for r in wrec:
        want = sum(r["w"]["uthmani"].count(c) for c in _WAQF)
        if not want:
            continue
        have = sum(1 for e in r["els"]
                   if e.get("mark") == "pause" and not e.get("mkpart"))
        if have >= want:
            continue
        bods = [e for e in r["els"] if e["kind"] == "body"]
        if len(bods) < 2:
            continue
        # the letters' own band, taken from the median letter so one floating
        # piece cannot drag the reference up to meet itself
        mids = sorted((e["y1"] + e["y2"]) / 2 for e in bods)
        band = mids[len(mids) // 2]
        float_up = [e for e in bods if e["y2"] < band - 2.0]
        float_up.sort(key=lambda e: e["y2"])
        for e in float_up[:want - have]:
            e["kind"] = "mark"
            e["mark"] = "pause"
            e["lab"] = "pause"
            # the dots of the ligature ride with it and are not letter dots
            for d in r["els"]:
                if d is e or d.get("mkpart") or d["kind"] != "mark":
                    continue
                if d.get("mark") not in ("dot", "two-dots", "three-dots"):
                    continue
                if (d["x1"] >= e["x1"] - 1.5 and d["x2"] <= e["x2"] + 1.5
                        and (d["y1"] + d["y2"]) / 2 < band - 2.0):
                    d["mkpart"] = True

    # A superscript letter — the iqlab meem ۢ, the small waw ۥ and small ya ۦ
    # of the pronoun suffixes — is a real letter shape drawn small and clear
    # of the line. Its ink looks exactly like a letter to the classifier, so
    # the word ends up one piece heavy and one mark short, and the surplus
    # reads as stolen ink from a neighbour. Nothing in the ink says
    # "superscript"; the spelling does. So take the COUNT from the text and
    # the POSITION from the ink: a piece whose foot stands well above the
    # word's own baseline is not standing on the line, and no letter does that.
    _SUP = ({} if os.environ.get("QSVG_SUP") == "0" else
            {"\u06e2": "meem-iqlab", "\u06e5": "small-waw",
             "\u06e6": "small-ya"})
    for r in wrec:
        for ch, name in _SUP.items():
            want = r["w"]["uthmani"].count(ch)
            if not want:
                continue
            have = sum(1 for e in r["els"]
                       if e.get("mark") == name and not e.get("mkpart"))
            if have >= want:
                continue
            bods = [e for e in r["els"] if e["kind"] == "body"]
            if len(bods) < 2:
                continue
            base = max(e["y2"] for e in bods)
            hgt = max(base - min(e["y1"] for e in bods), 1e-6)
            big = max(bods, key=lambda e: ((e["x2"] - e["x1"])
                                           * (e["y2"] - e["y1"])))
            big_a = max((big["x2"] - big["x1"]) * (big["y2"] - big["y1"]), 1e-6)
            # A letter belonging to the NEXT word can be small and lifted
            # too, and calling it a mark is worse than leaving it: the word
            # stops counting as a piece heavy, so the surplus that would have
            # exposed the theft disappears and the audit falls silent. A
            # stolen letter gives itself away by the company it keeps — the
            # dot and the vowel of the word it really belongs to stand on it.
            # Taken from the assignment, not from wrec: a word that has been
            # stripped of every letter never enters wrec, and that is exactly
            # the word whose letter has gone missing — the one whose marks are
            # the evidence.
            _foreign = [e2 for w2, at2 in assignment if w2 is not r["w"]
                        for a2 in at2 for e2 in a2["els"]
                        if e2["kind"] == "mark" and not e2.get("mkpart")
                        and e2.get("line") == r["line"]]

            def _owned_by_other(e0):
                for o in _foreign:
                    if min(o["x2"], e0["x2"]) - max(o["x1"], e0["x1"]) <= 0.5:
                        continue
                    if 0.0 <= e0["y1"] - o["y2"] <= 6.0:
                        return True       # its vowel or dot rides above it
                    if 0.0 <= o["y1"] - e0["y2"] <= 6.0:
                        return True       # or hangs below it
                return False

            cands = []
            for e in bods:
                if e is big or _owned_by_other(e):
                    continue
                # These pieces ARE letter fragments — the classifier is not
                # wrong about that — so "letter-part" cannot rule them out.
                # What separates a superscript from a tall letter standing on
                # a deep descender's line is that it is short as well as
                # lifted: the alef of أَلِيمٌۢ clears the baseline too, but it
                # is half the word tall, where the meem is a third.
                area = (e["x2"] - e["x1"]) * (e["y2"] - e["y1"])
                lift = base - e["y2"]
                if (lift >= 0.25 * hgt and area <= 0.40 * big_a
                        and (e["y2"] - e["y1"]) <= 0.45 * hgt):
                    cands.append((lift, e))
            cands.sort(key=lambda t: -t[0])
            for _, e in cands[:want - have]:
                e["kind"] = "mark"
                e["mark"] = name
                e["lab"] = name

    # A hamza is two different things wearing one outline, which is why a
    # shape table can never settle it. Riding on a carrier — أ إ ؤ ئ — it is a
    # MARK and the spelling counts it. Standing on its own, ء is a LETTER and
    # the spelling wants no mark at all. Only the position separates them: the
    # mark sits clear above or below its carrier, while the letter stands on
    # the line, in sequence with the rest of the word.
    _CARRIER = "\u0623\u0625\u0624\u0626\u0654\u0655"

    # The other direction. أَ is drawn as a stack: the hamza sits on the alef
    # and the fatha sits on the hamza. Both are the same small stroke to the
    # position labeller, so it names them both fatha and the word comes out a
    # hamza short and a fatha long — two budgets pointing at one fix. The
    # lower of the pair is the one touching the carrier, and that is the hamza.
    for r in wrec:
        txt = r["w"]["uthmani"]
        want_h = sum(txt.count(c) for c in _CARRIER)
        if not want_h:
            continue
        have_h = sum(1 for e in r["els"] if e.get("mark") == "hamza"
                     and not e.get("mkpart"))
        if have_h >= want_h:
            continue
        if os.environ.get("QSVG_HZB") == "0":
            continue
        _TAN = {"fatha": "\u064b\u08f0", "kasra": "\u064d\u08f2",
                "damma": "\u064c\u08f1"}
        _PLAIN = {"fatha": "\u064e", "kasra": "\u0650", "damma": "\u064f"}
        for fam in ("fatha", "kasra", "damma"):
            if have_h >= want_h:
                break
            pool = [e for e in r["els"] if e.get("mark") == fam]
            free = len([e for e in pool if not e.get("mkpart")])
            spare = free - sum(txt.count(c) for c in _PLAIN[fam])
            has_tan = any(c in txt for c in _TAN[fam])
            for e in sorted(pool, key=lambda q: -(q["y1"] + q["y2"])):
                if have_h >= want_h:
                    break
                # A welded twin is spare capacity too. Two of the same stroke
                # are welded as a tanween, but this word's spelling has none —
                # so the pair is not a doubled vowel at all. It is the hamza
                # with its vowel stacked on top, which is how أَ is drawn.
                twin = bool(e.get("mkpart"))
                if twin:
                    if has_tan:
                        continue
                elif spare <= 0:
                    continue
                cx = (e["x1"] + e["x2"]) / 2
                on_carrier = any(
                    b["kind"] == "body" and (b["x2"] - b["x1"]) <= 7.0
                    and (b["y2"] - b["y1"]) >= 6.0
                    and b["x1"] - 1.5 <= cx <= b["x2"] + 1.5
                    and -1.0 <= b["y1"] - e["y2"] <= 5.0
                    for b in r["els"])
                above = any(o is not e and o["kind"] == "mark"
                            and min(o["x2"], e["x2"]) - max(o["x1"], e["x1"]) > 0.5
                            and -1.0 <= e["y1"] - o["y2"] <= 5.0
                            for o in r["els"])
                if not (on_carrier and above):
                    continue
                if twin:
                    e["mkpart"] = False
                    for o in r["els"]:
                        if e in (o.get("mkmembers") or []):
                            o["mkmembers"] = [m for m in o["mkmembers"]
                                              if m is not e]
                else:
                    spare -= 1
                e["mark"] = "hamza"
                e["lab"] = "hamza"
                have_h += 1

    # rename slashes inside each word by its own fatha/kasra budget: the ones
    # below the body midline are the kasras, capacity permitting
    for r in wrec:
        sl = [e for e in r["els"] if e["kind"] == "mark"
              and e.get("mark") in ("fatha", "kasra")
              and not e.get("mkpart") and not e.get("mkmembers")]
        if not sl:
            continue
        want_k = r["w"]["uthmani"].count("\u0650")
        # A kasra already carried by a welded mark — the hamza-with-kasra
        # under the alef of إِيَّاكَ — is not in this list and must still be
        # paid for out of the budget. Left uncounted, the loop below finds no
        # slash below the midline to spend the budget on and forces one ABOVE
        # into a kasra, which no kasra can be.
        want_k -= sum(1 for e in r["els"]
                      if e["kind"] == "mark" and e not in sl
                      and not e.get("mkpart")
                      and "kasra" in (e.get("mark") or "").split("+"))
        want_k = max(0, want_k)
        mid = (r["top"] + r["bot"]) / 2
        sl.sort(key=lambda e: -(e["y1"] + e["y2"]))     # lowest first
        for i, e in enumerate(sl):
            below = (e["y1"] + e["y2"]) / 2 > mid
            e["mark"] = "kasra" if (i < want_k and below) or                 (below and i < want_k + 1 and want_k) else                 ("kasra" if i < want_k and not any(
                    (x["y1"] + x["y2"]) / 2 > mid for x in sl) else "fatha")
        # simple pass: lowest want_k slashes that sit below mid become kasra
        for e in sl:
            e["mark"] = "fatha"
        k = 0
        for e in sl:
            if k < want_k and (e["y1"] + e["y2"]) / 2 > mid:
                e["mark"] = "kasra"
                k += 1
        if k < want_k:
            for e in sl:
                if k >= want_k:
                    break
                if e["mark"] == "fatha":
                    e["mark"] = "kasra"
                    k += 1
                    break

    # A ring is never dots. Letter dots are SOLID ink; a glyph whose outline
    # nests one contour inside another is a ring — the head of a ة or ه — and
    # several such shapes are auto-labelled "two-dots" in the table. Whatever
    # path named them, they are letter ink: strip the mark globally so the dot
    # budgets below count only real dots.
    for _w3, _at3 in assignment:
        for _a3 in _at3:
            for _e3 in _a3["els"]:
                if _e3.get("mark") not in ("dot", "two-dots", "three-dots"):
                    continue
                _cs = _e3.get("contours") or []
                if len(_cs) < 2:
                    continue
                _bbs = [c["sp"] for c in _cs]
                _ring = False
                for _i3, _a4 in enumerate(_bbs):
                    for _b4 in _bbs[_i3 + 1:]:
                        if (_a4["xmin"] <= _b4["xmin"] and _a4["xmax"] >= _b4["xmax"]
                                and _a4["ymin"] <= _b4["ymin"]
                                and _a4["ymax"] >= _b4["ymax"]) or \
                           (_b4["xmin"] <= _a4["xmin"] and _b4["xmax"] >= _a4["xmax"]
                                and _b4["ymin"] <= _a4["ymin"]
                                and _b4["ymax"] >= _a4["ymax"]):
                            _ring = True
                if _ring:
                    _e3.pop("mark", None)
                    _e3.pop("mkpart", None)
                    _e3["kind"] = "body"
                    _e3["lab"] = "letter-part"

    coverage = (labeled, total_marks)

    # Letter ink never carries a diacritic identity: positional labelers can
    # hand a mark name to a letter-part (the ك dagger reads as a slash, a tall
    # stem as a damma). The shape table is the authority — strip those labels.
    for _, atoms in assignment:
        for a in atoms:
            for e in a["els"]:
                if e.get("lab") in ("letter", "letter-part", "letter-hamza") \
                        and e.get("mark"):
                    del e["mark"]
                    e.pop("mkpart", None)

    # In-word tanween weld by TEXT: a kasratan drawn tucked against the
    # letter (the عٍ of ضريع/جوع) arrives as two plain slashes that the
    # positional namer calls fathas. When the text wants a tanween the word
    # does not yet have, its two stacked surplus slashes ARE that tanween.
    _TXTW = {"fathatan": ("\u064b", "\u08f0", ("fatha", "kasra")),
             "kasratan": ("\u064d", "\u08f2", ("fatha", "kasra")),
             "dammatan": ("\u064c", "\u08f1", ("damma",))}
    for _w, _atoms in assignment:
        if not _w:
            continue
        txt = _w["uthmani"]
        _els = [e for a in _atoms for e in a["els"]]
        for tan, (c1, c2, plains) in _TXTW.items():
            want_t = txt.count(c1) + txt.count(c2)
            if not want_t:
                continue
            have_t = sum(1 for e in _els if e.get("mark") == tan
                         and not e.get("mkpart"))
            if have_t >= want_t:
                continue
            plain_want = (txt.count("\u064e") + txt.count("\u0650")
                          if "fatha" in plains else txt.count("\u064f"))
            cand = [e for e in _els if e.get("mark") in plains + (tan,)
                    and not e.get("mkpart") and not e.get("mkmembers")]
            if len(cand) - plain_want < 2:
                continue                  # no surplus pair to claim
            best = None
            for i in range(len(cand)):
                for j in range(i + 1, len(cand)):
                    a2, b2 = cand[i], cand[j]
                    dx = abs((a2["x1"] + a2["x2"]) / 2
                             - (b2["x1"] + b2["x2"]) / 2)
                    dy = abs((a2["y1"] + a2["y2"]) / 2
                             - (b2["y1"] + b2["y2"]) / 2)
                    if dx < 4.5 and 0.8 < dy < 7.0:
                        d = dx + dy
                        if best is None or d < best[0]:
                            best = (d, a2, b2)
            if best:
                _, a2, b2 = best
                top, bot = (a2, b2) if a2["y1"] <= b2["y1"] else (b2, a2)
                top["mark"] = bot["mark"] = tan
                bot["mkpart"] = True
                top["mkmembers"] = top.get("mkmembers", []) + [bot]

    # Two dammatan-labeled pieces side by side in one word are ONE dammatan
    # drawn as a damma pair: weld early so later passes move them as a unit.
    for _w, _atoms in assignment:
        if not _w:
            continue
        dt = [e for a in _atoms for e in a["els"]
              if e.get("mark") == "dammatan" and not e.get("mkpart")
              and not e.get("mkmembers")]
        for i in range(len(dt)):
            for j in range(i + 1, len(dt)):
                a2, b2 = dt[i], dt[j]
                if a2.get("mkpart") or b2.get("mkpart"):
                    continue
                dx = abs((a2["x1"] + a2["x2"]) / 2 - (b2["x1"] + b2["x2"]) / 2)
                dy = abs((a2["y1"] + a2["y2"]) / 2 - (b2["y1"] + b2["y2"]) / 2)
                if dx < 5.0 and dy < 5.0:
                    b2["mkpart"] = True
                    a2.setdefault("mkmembers", []).append(b2)

    # Tanween pair reunification: a tanween's two strokes can land in
    # neighbouring words (even across a line break at the column edge), each
    # hiding inside a "balanced" plain-slash count. The text names the owner:
    # the word that wants the tanween claims the nearest matching stroke pair,
    # welds it, and oracle repair below settles the displaced plain budgets.
    _TXTT = {"fathatan": ("\u064b", "\u08f0"), "kasratan": ("\u064d", "\u08f2"),
             "dammatan": ("\u064c", "\u08f1")}
    _TPLAIN = {"fathatan": ("fatha",), "kasratan": ("kasra",),
               "dammatan": ("damma",)}
    _recs = []
    for _w, _atoms in assignment:
        if not _w:
            continue
        _els = [e for a in _atoms for e in a["els"]]
        _recs.append((_w, _atoms, _els))
    def _plain_ct(els):
        return sum(1 for e in els if e.get("mark") in ("fatha", "kasra")
                   and not e.get("mkpart") and not e.get("mkmembers"))
    for _w, _atoms, _els in _recs:
        txt = _w["uthmani"]
        pw_own = txt.count("\u064e") + txt.count("\u0650")
        for tan, chars in _TXTT.items():
            want_t = sum(txt.count(c) for c in chars)
            if not want_t:
                continue
            welded = sum(1 for e in _els if e.get("mark") == tan
                         and e.get("mkmembers"))
            if welded >= want_t:
                continue
            bods = [e for e in _els if e["kind"] == "body"]
            if not bods:
                continue
            mid = (min(e["y1"] for e in bods) + max(e["y2"] for e in bods)) / 2
            seeds = [e for e in _els if e.get("mark") == tan
                     and not e.get("mkpart") and not e.get("mkmembers")
                     and mid - 25.0 < (e["y1"] + e["y2"]) / 2 < mid + 20.0]
            if not seeds and tan == "dammatan":
                # a dammatan drawn as TWO damma curls inside the word: weld the
                # closest surplus pair into one unit
                dms = [e for e in _els if e.get("mark") == "damma"
                       and not e.get("mkpart") and not e.get("mkmembers")
                       and mid - 25.0 < (e["y1"] + e["y2"]) / 2 < mid + 20.0]
                # a TIGHT side-by-side pair is the ٌ curls even when the م's
                # own damma strayed to a neighbour — welding exposes the
                # deficit and the strict pass then fetches the stray
                tight = False
                for i1 in range(len(dms)):
                    for i2 in range(i1 + 1, len(dms)):
                        if abs(dms[i1]["x1"] - dms[i2]["x1"]) < 6.0 \
                                and abs(dms[i1]["y1"] - dms[i2]["y1"]) < 5.0:
                            tight = True
                if len(dms) >= (2 if tight else 2 + txt.count("\u064f")):
                    best_p = None
                    for i1 in range(len(dms)):
                        for i2 in range(i1 + 1, len(dms)):
                            a1, b1 = dms[i1], dms[i2]
                            d = (abs((a1["x1"] + a1["x2"]) / 2
                                     - (b1["x1"] + b1["x2"]) / 2)
                                 + abs((a1["y1"] + a1["y2"]) / 2
                                       - (b1["y1"] + b1["y2"]) / 2))
                            if d < 9.0 and (best_p is None or d < best_p[0]):
                                best_p = (d, a1, b1)
                    if best_p:
                        _, a1, b1 = best_p
                        top, bot = (a1, b1) if a1["x1"] >= b1["x1"] else (b1, a1)
                        top["mark"] = bot["mark"] = tan
                        bot["mkpart"] = True
                        top["mkmembers"] = top.get("mkmembers", []) + [bot]
                        continue
                # a lone curl seeds the cross-word search: its twin strayed
                # into a neighbouring word (even a line below)
                if not seeds:
                    seeds = dms
            if not seeds and tan != "dammatan" and _plain_ct(_els) > pw_own:
                seeds = [e for e in _els
                         if e.get("mark") in ("fatha", "kasra")
                         and not e.get("mkpart") and not e.get("mkmembers")
                         and (((e["y1"] + e["y2"]) / 2 > mid)
                              == (tan == "kasratan"))]
            # both strokes may already sit in the word as unwelded plain
            # slashes (a kasratan pair under مؤمنٰتٍ): weld in place first.
            # the ع descender can push the word's midline BELOW the upper
            # stroke, so pair from all spare slashes, not just the seeds
            pool = [e for e in _els
                    if e.get("mark") in ("fatha", "kasra", tan)
                    and not e.get("mkpart") and not e.get("mkmembers")]
            if len(pool) >= 2 and _plain_ct(_els) >= pw_own + 2:
                seeds = pool
            if len(seeds) >= 2 and _plain_ct(_els) >= pw_own + 2:
                bp = None
                for i1 in range(len(seeds)):
                    for i2 in range(i1 + 1, len(seeds)):
                        a1, b1 = seeds[i1], seeds[i2]
                        dx = abs((a1["x1"] + a1["x2"]) / 2
                                 - (b1["x1"] + b1["x2"]) / 2)
                        dy = abs((a1["y1"] + a1["y2"]) / 2
                                 - (b1["y1"] + b1["y2"]) / 2)
                        if dx < 4.5 and dy < 7.0 and (bp is None
                                                      or dx + dy < bp[0]):
                            bp = (dx + dy, a1, b1)
                if bp:
                    _, a1, b1 = bp
                    top, bot = (a1, b1) if a1["y1"] <= b1["y1"] else (b1, a1)
                    top["mark"] = bot["mark"] = tan
                    bot["mkpart"] = True
                    top["mkmembers"] = top.get("mkmembers", []) + [bot]
                    continue
            best = None
            for s1 in seeds:
                c1 = ((s1["x1"] + s1["x2"]) / 2, (s1["y1"] + s1["y2"]) / 2)
                for _w2, _at2, _els2 in _recs:
                    if _w2 is _w:
                        continue
                    t2 = _w2["uthmani"]
                    for s2 in _els2:
                        if s2.get("mkpart") or s2.get("mkmembers") \
                                or s2.get("standalone"):
                            continue
                        mk2 = s2.get("mark")
                        if mk2 == tan:
                            if sum(t2.count(c) for c in chars):
                                continue        # donor entitled to it
                        elif tan == "dammatan" and mk2 == "damma":
                            c2d = t2.count("\u064f")
                            h2d = sum(1 for x in _els2
                                      if x.get("mark") == "damma"
                                      and not x.get("mkpart"))
                            if h2d <= c2d:
                                continue        # donor not surplus
                        elif mk2 in ("fatha", "kasra"):
                            if tan == "dammatan":
                                continue
                            if _plain_ct(_els2) <= t2.count("\u064e") \
                                    + t2.count("\u0650"):
                                continue        # donor not surplus
                        else:
                            continue
                        c2 = ((s2["x1"] + s2["x2"]) / 2,
                              (s2["y1"] + s2["y2"]) / 2)
                        if not (mid - 25.0 < c2[1] < mid + 20.0):
                            continue      # from another line's band
                        dx = abs(c1[0] - c2[0]); dy = abs(c1[1] - c2[1])
                        if dx < 12.0 and dy < 6.0:
                            d = dx + dy
                            if best is None or d < best[0]:
                                best = (d, s1, s2, _at2, _els2)
            if best:
                _, s1, s2, _at2, _els2 = best
                _els2.remove(s2)
                for a in _at2:
                    if s2 in a["els"]:
                        a["els"].remove(s2)
                        break
                _atoms[0]["els"].append(s2)
                _els.append(s2)
                top, bot = (s1, s2) if s1["y1"] <= s2["y1"] else (s2, s1)
                top["mark"] = bot["mark"] = tan
                bot["mkpart"] = True
                top["mkmembers"] = top.get("mkmembers", []) + [bot]


    # ------------------------------------------------------------------
    # Oracle repair: the final authority. Whatever upstream stage erred, a
    # word that fails its oracles — piece count vs its own letter segments,
    # mark-family budgets from its text, line-band consistency, ayah-polygon
    # containment — trades elements with its geometric neighbours until the
    # joint score stops improving. Encodes verify-and-keep-fixing in code.
    # ------------------------------------------------------------------
    def _o_fams(txt):
        return {f: _cap(txt, f) for f in
                ("slash", "damma", "sukun", "hamza", "wasla", "small-alef",
                 "maddah", "shadda", "small-circle", "pause",
                 "small-waw", "small-ya")}

    _OFAM = {"fatha": "slash", "kasra": "slash", "fathatan": "slash",
             "kasratan": "slash", "damma": "damma", "dammatan": "damma",
             "sukun": "sukun", "hamza": "hamza", "wasla": "wasla",
             "small-alef": "small-alef", "maddah": "maddah", "shadda": "shadda",
             "small-circle": "small-circle", "pause": "pause",
             "meem-iqlab": "meem-iqlab",
             "small-waw": "small-waw", "small-ya": "small-ya"}

    owords = []
    for w, at in assignment:
        if not w:
            continue
        els = [e for a in at for e in a["els"]]
        if not els:
            continue
        bods = [e for e in els if e["kind"] == "body"]
        lns = [e.get("line") for e in (bods or els) if e.get("line")]
        ln0 = max(set(lns), key=lns.count) if lns else None
        owords.append({"w": w, "at": at, "ln": ln0,
                       "nseg": max(1, len(segment_word(w["uthmani"]))),
                       "top": min(e["y1"] for e in (bods or els)),
                       "bot": max(e["y2"] for e in (bods or els)),
                       "caps": _o_fams(w["uthmani"])})

    _ordix = {id(_r0): _i0 for _i0, _r0 in enumerate(owords)}

    def _ospan(r):
        els = [e for a in r["at"] for e in a["els"]]
        bods = [e for e in els if e["kind"] == "body"] or els
        if not bods:
            return r.get("span0", (0.0, 0.0))
        sp = (min(e["x1"] for e in bods), max(e["x2"] for e in bods))
        r.setdefault("span0", sp)
        return sp

    def _oscore(r):
        els = [e for a in r["at"] for e in a["els"]]
        bods = [e for e in els if e["kind"] == "body"]
        eff = []
        for b in bods:                     # a stroke nested inside a sibling is
            wb = b["x2"] - b["x1"]         # part of the same letter, not a piece
            hb = b["y2"] - b["y1"]
            # a stroke DRAWN OVER a letter (the kaf armature, a lam-alef's
            # second stroke) sits within its host's height; a piece that rises
            # ABOVE its host is a letter of its own — the silent alef standing
            # on the waw of ـوا۟ — and must keep counting as a piece.
            inside = any(o is not b
                         and min(o["x2"], b["x2"]) - max(o["x1"], b["x1"])
                         >= 0.6 * wb
                         and (o["x2"] - o["x1"]) > wb
                         and hb <= (o["y2"] - o["y1"]) + 1.0
                         for o in bods)
            if not inside:
                eff.append(b)
        sc = 3.0 * abs(len(eff) - r["nseg"])
        have = {}
        for e in els:
            f = _OFAM.get(e.get("mark"))
            if f and not e.get("mkpart"):
                have[f] = have.get(f, 0) + 1
        for f, want in r["caps"].items():
            sc += 2.0 * abs(have.get(f, 0) - want)
        if r["ln"]:
            sc += 2.0 * sum(1 for e in els
                            if e.get("line") and abs(e["line"] - r["ln"]) >= 1)
        return sc

    def _rtl_ok(a, b):
        """True when a and b still read in the right order on their line.

        Arabic runs right to left, so the word that comes first must keep the
        higher x. Words legitimately overlap — a sweeping tail runs under its
        neighbour — so this checks the two spans do not CROSS, not that they
        stay apart.
        """
        if a["ln"] is None or a["ln"] != b["ln"]:
            return True

        def _bspan(r):
            bs = [e for at in r["at"] for e in at["els"]
                  if e["kind"] == "body"]
            if not bs:
                return None
            return min(e["x1"] for e in bs), max(e["x2"] for e in bs)

        # Letter ink alone fixes a word's place on the line. Marks reach well
        # past it -- the hamza of أَوْ stands almost as far left as the whole
        # of مشركة -- so measuring with them makes a crossing look legal.
        fa, fb = _bspan(a), _bspan(b)
        if fa is None or fb is None:
            return False          # a word stripped of every letter is not a fix
        first, second = (a, b) if _ordix[id(a)] < _ordix[id(b)] else (b, a)
        f1, f2 = _bspan(first)
        s1, s2 = _bspan(second)
        return f1 >= s1 - 1.0 and f2 >= s2 - 1.0

    _TRACE = os.environ.get("QSVG_TRACE")
    # Letting the width prior carry a body move the oracle cannot judge is OFF.
    # Measured over all 604 pages it changes the number of wrong-sized words by
    # five — noise — while doing real damage in particular places: it fixed أَوْ
    # on p350 by taking sixteen units from وٱلزانية, and fixed إلى on p574 by
    # robbing أرسلنا. A rule that buys nothing and breaks words visibly is not
    # worth keeping. QSVG_WDECIDE=<gain> re-enables it for experiments.
    _WDECIDE = float(os.environ.get("QSVG_WDECIDE", "0"))

    def _omove(e, src, dst):
        # QSVG_TRACE=<x1> prints every hand-off of one piece of ink, which is
        # how a word that ends up with the wrong letter gets traced back to
        # the pass that took it.
        if _TRACE and any(abs(e["x1"] - float(_t)) < 0.5
                          for _t in _TRACE.split(",")):
            import traceback as _tb
            _fr = _tb.extract_stack()[-2]
            sys.stderr.write("MOVE line%-5d %-6s x %.1f-%.1f  %s -> %s\n"
                             % (_fr.lineno, e["kind"], e["x1"], e["x2"],
                                src["w"]["uthmani"], dst["w"]["uthmani"]))
        for a in src["at"]:
            if e in a["els"]:
                a["els"].remove(e)
                for m in e.get("mkmembers", []):
                    if m in a["els"]:
                        a["els"].remove(m)
                break
        tgt = min(dst["at"], key=lambda a2: min(abs((x["x1"] + x["x2"]) / 2
                  - (e["x1"] + e["x2"]) / 2) for x in a2["els"])
                  if a2["els"] else 1e9)
        tgt["els"].append(e)
        tgt["els"].extend(e.get("mkmembers", []))

    for _round in range(3):
        improved = False
        for r in owords:
            base_r = _oscore(r)
            if base_r <= 0:
                continue
            rx1, rx2 = _ospan(r)
            for v in owords:
                if v is r or v["ln"] is None or r["ln"] is None:
                    continue
                if abs(v["ln"] - r["ln"]) > 1:
                    continue
                vx1, vx2 = _ospan(v)
                if vx2 < rx1 - 20 or vx1 > rx2 + 20:
                    continue
                base = base_r + _oscore(v)
                def _wdev(x):
                    # width deviation vs the word's QCF share of its line
                    ln0 = x["ln"]
                    rs0 = [y for y in owords if y["ln"] == ln0]
                    ta = tq = 0.0
                    for y in rs0:
                        y1, y2 = _ospan(y)
                        ta += y2 - y1
                        tq += letters(y["w"])
                    if not tq or not ta:
                        return 0.0
                    x1, x2 = _ospan(x)
                    exp = letters(x["w"]) / tq * ta
                    import math as _m
                    return abs(_m.log(max((x2 - x1) / max(exp, 1e-6), 1e-3)))

                best = None
                for e in [x for a in v["at"] for x in a["els"]]:
                    if e.get("mkpart") or e.get("standalone"):
                        continue
                    if e["kind"] == "body" and v["ln"] != r["ln"]:
                        continue          # letter ink never crosses lines
                    if e["kind"] == "body" and e.get("lab") in \
                            ("letter-part", "letter", "letter-hamza"):
                        continue          # fragments stay with their base
                    cx = (e["x1"] + e["x2"]) / 2
                    win = 18.0 if e["kind"] == "body" else 4.0
                    if not (rx1 - win < cx < rx2 + win):
                        continue
                    far = e["kind"] == "body" and not (rx1 - 2 < cx < rx2 + 2)
                    if e["kind"] == "body":
                        wj0 = _wdev(r) + _wdev(v)
                        wj0_worst = max(_wdev(r), _wdev(v))
                    _omove(e, v, r)
                    d = _oscore(r) + _oscore(v)
                    ok_w = True
                    if e["kind"] == "body":
                        gain = wj0 - (_wdev(r) + _wdev(v))
                        # a far body must EARN its move with a real width gain;
                        # nearby pieces only need to not hurt
                        ok_w = gain >= (0.08 if far else -0.02)
                        # Width measures a span, not which piece fills it, so
                        # it is equally happy when two words trade the wrong
                        # letters. Reading order is what pins the piece down:
                        # on the line, an earlier word's ink stays right of a
                        # later one's. Letting أَوْ hand its alef away and take
                        # مشركة's waw satisfies both widths and puts the words
                        # in the wrong order on the page.
                        if ok_w and not _rtl_ok(r, v):
                            ok_w = False
                        # The gain is a SUM, so a word left far too short can
                        # hide behind a neighbour that lands perfectly. On
                        # p350 مشركة finished at 33.2 against 33.4 wanted by
                        # taking 16u from وٱلزانية, which ended at 25 against
                        # 41 — a good score for the pair, a broken word on the
                        # page. Neither side may be left badly out of size.
                        if ok_w:
                            worst_now = max(_wdev(r), _wdev(v))
                            if worst_now > 0.35 and worst_now > wj0_worst:
                                ok_w = False
                    _omove(e, r, v)
                    # The oracle counts marks, so it is flat on a body move
                    # that leaves both words' mark budgets intact — a letter
                    # piece sitting in the wrong word scores exactly like one
                    # sitting in the right word. Demanding it improve throws
                    # away moves the ink itself settles: on p350 the waw of
                    # أَوْ scored d == base while the width prior gained 0.60,
                    # leaving the word one piece where أ and و must give two.
                    # When the oracle is indifferent, let the widths decide,
                    # but only on a decisive gain.
                    take = ok_w and d < base - 0.5
                    if (_WDECIDE and not take and ok_w and e["kind"] == "body"
                            and d <= base + 1e-9 and gain >= _WDECIDE):
                        take = True
                    if take and (best is None or d < best[0]):
                        best = (d, e)
                if best:
                    _omove(best[1], v, r)
                    improved = True
                    base_r = _oscore(r)
        if not improved:
            break

    # Welded tanween masters are identity-strong: only a word whose text
    # carries that tanween may own the pair. Strict surplus->deficit transfer.
    for lab, chars in (("fathatan", "\u064b\u08f0"),
                       ("kasratan", "\u064d\u08f2"),
                       ("dammatan", "\u064c\u08f1")):
        for r in owords:
            want_r = sum(r["w"]["uthmani"].count(ch) for ch in chars)
            mine = [e for a in r["at"] for e in a["els"]
                    if e.get("mark") == lab and not e.get("mkpart")]
            if len(mine) <= want_r:
                continue
            for v in owords:
                if v is r or v["ln"] is None or r["ln"] is None \
                        or abs(v["ln"] - r["ln"]) > 1:
                    continue
                want_v = sum(v["w"]["uthmani"].count(ch) for ch in chars)
                have_v = sum(1 for a in v["at"] for e in a["els"]
                             if e.get("mark") == lab and not e.get("mkpart"))
                if have_v >= want_v:
                    continue
                vx1, vx2 = _ospan(v)
                cands = [e for e in mine
                         if vx1 - 12.0 < (e["x1"] + e["x2"]) / 2 < vx2 + 12.0]
                if not cands:
                    continue
                mv = min(cands, key=lambda e: abs((vx1 + vx2) / 2
                                                  - (e["x1"] + e["x2"]) / 2))
                _omove(mv, r, v)
                mine.remove(mv)
                if len(mine) <= want_r:
                    break

    # Line-balanced family refill: when a line's total of a family equals the
    # line's total budget but members are shuffled through a chain of words,
    # re-deal the marks in reading order against each word's quota (a mark may
    # only land in a word whose span, widened, actually reaches it).
    _lines_of = {}
    for r in owords:
        if r["ln"]:
            _lines_of.setdefault(r["ln"], []).append(r)
    for ln2, rs in _lines_of.items():
        rs.sort(key=lambda r: -sum(_ospan(r)) / 2)
        for fam in ("slash", "damma"):
            labs = tuple(l for l, f in _OFAM.items() if f == fam)
            want = {id(r): _cap(r["w"]["uthmani"], fam) for r in rs}
            pool = []
            for r in rs:
                for e in [x for a in r["at"] for x in a["els"]]:
                    if e.get("mark") in labs and not e.get("mkpart"):
                        pool.append((e, r))
            if sum(want.values()) != len(pool) or not pool:
                continue
            if all(sum(1 for e, r0 in pool if r0 is r) == want[id(r)]
                   for r in rs):
                continue
            pool.sort(key=lambda t: -(t[0]["x1"] + t[0]["x2"]) / 2)
            quota = dict(want)
            plan = []
            wi = 0
            ok = True
            for e, r0 in pool:
                while wi < len(rs) and quota[id(rs[wi])] <= 0:
                    wi += 1
                if wi >= len(rs):
                    ok = False
                    break
                tgt = rs[wi]
                x1, x2 = _ospan(tgt)
                cx = (e["x1"] + e["x2"]) / 2
                if not (x1 - 12.0 < cx < x2 + 12.0):
                    ok = False
                    break
                quota[id(tgt)] -= 1
                plan.append((e, r0, tgt))
            if ok:
                for e, r0, tgt in plan:
                    if r0 is not tgt:
                        _omove(e, r0, tgt)


    # Final strict pass: after every layer, any family surplus standing next
    # to a deficit (same or adjacent line, within reach) is resolved. Runs to
    # fixpoint; strictly budget-guarded, so it can only reduce mismatches.
    for _rounds in range(3):
        moved_any = False
        for fam in set(_OFAM.values()):
            labs = tuple(l for l, f in _OFAM.items() if f == fam)
            for r in owords:
                cap_r = _cap(r["w"]["uthmani"], fam)
                mine = [e for a in r["at"] for e in a["els"]
                        if e.get("mark") in labs and not e.get("mkpart")]
                if len(mine) <= cap_r:
                    continue
                for v in owords:
                    if v is r or v["ln"] is None or r["ln"] is None \
                            or abs(v["ln"] - r["ln"]) > 1:
                        continue
                    cap_v = _cap(v["w"]["uthmani"], fam)
                    have_v = sum(1 for a in v["at"] for e in a["els"]
                                 if e.get("mark") in labs
                                 and not e.get("mkpart"))
                    if have_v >= cap_v:
                        continue
                    vx1, vx2 = _ospan(v)
                    _reach = 14.0 if v["ln"] == r["ln"] else 20.0
                    cands = [e for e in mine
                             if vx1 - _reach < (e["x1"] + e["x2"]) / 2
                             < vx2 + _reach
                             and not (fam in _ABOVE_FAM
                                      and (e["y1"] + e["y2"]) / 2 > v["bot"])]
                    if not cands:
                        continue
                    mv = min(cands, key=lambda e: abs((vx1 + vx2) / 2
                             - (e["x1"] + e["x2"]) / 2))
                    _omove(mv, r, v)
                    mine.remove(mv)
                    moved_any = True
                    if len(mine) <= cap_r:
                        break
        if not moved_any:
            break

    # Text-gated trust for auto damma shapes: the shape table's UNCONFIRMED
    # damma/dammatan entries are ignored at classify time (a stem can match
    # them), so on some pages the real damma lands as a small "body". When a
    # word's text still WANTS a damma-family mark and it holds a small body
    # whose outline the table calls damma/dammatan, the text confirms the
    # shape — reclassify it as that mark.
    _full_tab = shape_labels()
    for r in owords:
        want_d = _cap(r["w"]["uthmani"], "damma")
        if not want_d:
            continue
        def _dunits(_r=r):
            return sum(1 for a in _r["at"] for x in a["els"]
                       if x.get("mark") in ("damma", "dammatan")
                       and not x.get("mkpart"))
        if _dunits() >= want_d:
            continue
        for a in r["at"]:
            for e in a["els"]:
                if e["kind"] != "body" or e.get("mark"):
                    continue
                w2 = e["x2"] - e["x1"]; h2 = e["y2"] - e["y1"]
                if not (3.0 <= max(w2, h2) <= 9.0):
                    continue
                v = _full_tab.get(pk(e))
                lab = (v.get("label") if isinstance(v, dict) else v) if v else None
                if lab in ("damma", "dammatan"):
                    e["kind"] = "mark"
                    e["mark"] = lab
                    if _dunits() >= want_d:
                        break

    # A slash-family "mark" whose ink sits INSIDE a letter's own box is the
    # letter's armature (the ك dagger) mislabeled by a shape collision — a
    # real fatha rides above the ink, a kasra below. Only a word whose slash
    # count exceeds its text budget may reclassify, most-interior first.
    for r in owords:
        want_s = _cap(r["w"]["uthmani"], "slash")
        def _shave(_r=r):
            return sum(1 for a in _r["at"] for x in a["els"]
                       if _OFAM.get(x.get("mark")) == "slash"
                       and not x.get("mkpart"))
        if _shave() <= want_s:
            continue
        bods = [x for a in r["at"] for x in a["els"] if x["kind"] == "body"
                and (x["y2"] - x["y1"]) >= 8.0]
        cands = []
        for e in [x for a in r["at"] for x in a["els"]
                  if x.get("mark") in ("fatha", "kasra")
                  and not x.get("mkpart") and not x.get("mkmembers")]:
            cx = (e["x1"] + e["x2"]) / 2
            cy = (e["y1"] + e["y2"]) / 2
            for b in bods:
                if b["x1"] <= cx <= b["x2"] \
                        and b["y1"] + 1.5 <= cy <= b["y2"] - 1.5:
                    depth = min(cy - b["y1"], b["y2"] - cy)
                    cands.append((depth, e))
                    break
        for _, e in sorted(cands, key=lambda t: -t[0]):
            if _shave() <= want_s:
                break
            e["kind"] = "body"
            del e["mark"]

    # Absorb stranded damma-family surplus: a word that wants NONE of the
    # family but holds a piece, with every neighbour numerically satisfied,
    # is carrying half of a neighbour's two-piece damma/dammatan — weld the
    # piece into the closest adjacent same-family unit instead.
    for r in owords:
        for e in [x for a in r["at"] for x in a["els"]
                  if x.get("mark") in ("damma", "dammatan")
                  and not x.get("mkpart") and not x.get("mkmembers")]:
            if _cap(r["w"]["uthmani"], "damma") >= sum(
                    1 for a in r["at"] for x in a["els"]
                    if x.get("mark") in ("damma", "dammatan")
                    and not x.get("mkpart")):
                break
            cx = (e["x1"] + e["x2"]) / 2
            cy = (e["y1"] + e["y2"]) / 2
            best = None
            for v in owords:
                if v is r or v["ln"] is None or r["ln"] is None \
                        or abs(v["ln"] - r["ln"]) > 1:
                    continue
                for u in [x for a in v["at"] for x in a["els"]
                          if x.get("mark") in ("damma", "dammatan")
                          and not x.get("mkpart")]:
                    dx = abs((u["x1"] + u["x2"]) / 2 - cx)
                    dy = abs((u["y1"] + u["y2"]) / 2 - cy)
                    if dx < 7.0 and dy < 7.0 and (best is None
                                                  or dx + dy < best[0]):
                        best = (dx + dy, u, v)
            if best:
                _, u, v = best
                _omove(e, r, v)
                e["mkpart"] = True
                u.setdefault("mkmembers", []).append(e)

    # A meem-iqlab that no text demands is the LETTER meem: give it back to
    # the ink. (Left as a mark it may re-line onto a neighbouring line — the
    # م of يَوْمَ landing on ٱبْنُ below it, and the hole it leaves pulling a
    # piece off each following word.)
    for r in owords:
        if "\u06e2" in r["w"]["uthmani"] or "\u06ed" in r["w"]["uthmani"]:
            continue
        for a in r["at"]:
            for e in a["els"]:
                if e.get("mark") == "meem-iqlab" and not e.get("mkpart"):
                    e.pop("mark", None)
                    e["kind"] = "body"
                    e["lab"] = "letter-part"

    # Every mark has a natural owner: the word whose letters it is drawn
    # against, on the correct side — fatha, damma, sukun, shadda, madda,
    # small-alef and wasla ride above; kasra and kasratan hang below. Budgets
    # cannot recover this, because three words can hold one another's marks in
    # a cycle with every count still balancing. So compute each mark's natural
    # owner from the ink alone and apply the moves together, which unwinds a
    # cycle in one pass.
    _SIDE_ABOVE = {"fatha", "damma", "sukun", "shadda", "maddah",
                   "small-alef", "wasla", "fathatan", "dammatan",
                   "small-circle", "meem-iqlab"}
    _SIDE_BELOW = {"kasra", "kasratan"}
    for _round in range(3):
        _ink = {}
        for r in owords:
            bs = [e for a in r["at"] for e in a["els"] if e["kind"] == "body"]
            if bs:
                _ink[id(r)] = (min(e["x1"] for e in bs), max(e["x2"] for e in bs),
                               min(e["y1"] for e in bs), max(e["y2"] for e in bs))

        def _fit(v, mk, cx, cy):
            sp = _ink.get(id(v))
            if not sp or not (sp[0] - 1.0 <= cx <= sp[1] + 1.0):
                return None
            gap = (sp[2] - cy) if mk in _SIDE_ABOVE else (cy - sp[3])
            if gap < -2.0 or gap > 16.0:
                return None               # not drawn against this word's ink
            return (gap, abs(cx - (sp[0] + sp[1]) / 2))

        moves = []
        for r in owords:
            if id(r) not in _ink:
                continue
            for a in r["at"]:
                for e in a["els"]:
                    if e["kind"] != "mark" or e.get("mkpart") \
                            or e.get("standalone"):
                        continue
                    mk = e.get("mark")
                    if mk not in _SIDE_ABOVE and mk not in _SIDE_BELOW:
                        continue
                    cx = (e["x1"] + e["x2"]) / 2
                    cy = (e["y1"] + e["y2"]) / 2
                    here = _fit(r, mk, cx, cy)
                    best = None
                    for v in owords:
                        if v["ln"] is None or r["ln"] is None \
                                or abs(v["ln"] - r["ln"]) > 1:
                            continue
                        f = _fit(v, mk, cx, cy)
                        if f is None:
                            continue
                        if best is None or f < best[0]:
                            best = (f, v)
                    if best is None or best[1] is r:
                        continue
                    # only when the other word is a clearly better fit
                    if here is not None and here[0] <= best[0][0] + 2.0:
                        continue
                    moves.append((e, r, best[1]))
        if not moves:
            break
        # Keep only moves that CLOSE: every word involved must give away as
        # many marks of a family as it receives. That is exactly the cycle
        # case, where each word ends with its own ink and no budget changes —
        # a lone move is a guess about ink nobody else claims, so it is
        # dropped and left for the audit to surface.
        fam_of = lambda e: _OFAM.get(e.get("mark")) or e.get("mark")
        out_c, in_c = {}, {}
        for e, src, dst in moves:
            f = fam_of(e)
            out_c[(id(src), f)] = out_c.get((id(src), f), 0) + 1
            in_c[(id(dst), f)] = in_c.get((id(dst), f), 0) + 1
        keep = [(e, src, dst) for e, src, dst in moves
                if out_c.get((id(src), fam_of(e)), 0)
                == in_c.get((id(src), fam_of(e)), 0)
                and out_c.get((id(dst), fam_of(e)), 0)
                == in_c.get((id(dst), fam_of(e)), 0)]
        if not keep:
            break
        for e, src, dst in keep:
            e["line"] = dst["ln"]
            _omove(e, src, dst)

    # A mark belongs to the line it is DRAWN in. Marks ride above and below
    # their letters, so some overshoot is normal, but ink sitting squarely in
    # a neighbouring band was drawn for a word there. The budgets cannot see
    # this — the holder's counts can balance perfectly — only the geometry can.
    _bands = {li0["lineNumber"]: (li0["top"], li0["bottom"])
              for li0 in lines_info}
    if _bands:
        _byline = {}
        for r in owords:
            if r["ln"] is not None:
                _byline.setdefault(r["ln"], []).append(r)
        for r in owords:
            if r["ln"] not in _bands:
                continue
            top0, bot0 = _bands[r["ln"]]
            h0 = max(1e-6, bot0 - top0)
            for a in list(r["at"]):
                for e in list(a["els"]):
                    if e["kind"] != "mark" or e.get("mkpart") \
                            or e.get("standalone"):
                        continue
                    cy = (e["y1"] + e["y2"]) / 2
                    tgt_ln, depth = None, 0.0
                    for ln0, (t0, b0) in _bands.items():
                        if t0 <= cy <= b0 and abs(ln0 - r["ln"]) <= 2:
                            tgt_ln = ln0
                            # how far inside that band it sits, as a share
                            depth = min(cy - t0, b0 - cy) / max(1e-6, b0 - t0)
                            break
                    if tgt_ln is None or tgt_ln == r["ln"]:
                        continue
                    fam0 = _OFAM.get(e.get("mark"))
                    cx = (e["x1"] + e["x2"]) / 2
                    best = None
                    for v in _byline.get(tgt_ln, []):
                        sp = _ospan(v)
                        # the mark must stand over this word's OWN ink: on the
                        # target line, containment is the evidence, not nearness
                        if not (sp[0] - 0.5 <= cx <= sp[1] + 0.5):
                            continue
                        short = 0
                        if fam0:
                            capv = _cap(v["w"]["uthmani"], fam0)
                            havev = sum(1 for a2 in v["at"] for x2 in a2["els"]
                                        if _OFAM.get(x2.get("mark")) == fam0
                                        and not x2.get("mkpart"))
                            short = 1 if havev < capv else 0
                        # a short word's claim is decisive; otherwise the
                        # mark must sit deep inside the other band, not merely
                        # dip into it the way a low kasra does
                        if not short and depth < 0.25:
                            continue
                        d = abs(cx - (sp[0] + sp[1]) / 2)
                        key = (-short, d)
                        if best is None or key < best[0]:
                            best = (key, v)
                    if best is None:
                        continue
                    e["line"] = tgt_ln
                    _omove(e, r, best[1])

    # Two words can hold each other's marks: the counts then balance in both,
    # so no budget check can see it — but the geometry is unambiguous. A mark
    # sitting outside its own word's ink and over a neighbour's, matched by one
    # going the other way, is a swap. Exchanging them keeps every budget intact
    # and can only move ink closer to the letters it was drawn on.
    def _mspan(rec):
        bs = [e for a in rec["at"] for e in a["els"] if e["kind"] == "body"]
        if not bs:
            return None
        return (min(e["x1"] for e in bs), max(e["x2"] for e in bs))

    _SWAP_FAM = {"fatha": "slash", "kasra": "slash", "damma": "damma",
                 "sukun": "sukun", "shadda": "shadda", "maddah": "maddah",
                 "small-alef": "small-alef", "hamza": "hamza",
                 "dot": "dots", "two-dots": "dots", "three-dots": "dots"}
    for r in owords:
        sp_r = _mspan(r)
        if sp_r is None:
            continue
        for v in owords:
            if v is r or v["ln"] is None or r["ln"] is None \
                    or abs(v["ln"] - r["ln"]) > 1:
                continue
            sp_v = _mspan(v)
            if sp_v is None:
                continue
            def _stray(src, own, other):
                out = []
                for a in src["at"]:
                    for e in a["els"]:
                        if e["kind"] != "mark" or e.get("mkpart"):
                            continue
                        fam = _SWAP_FAM.get(e.get("mark"))
                        if not fam:
                            continue
                        cx = (e["x1"] + e["x2"]) / 2

                        def _d(sp):
                            return 0.0 if sp[0] <= cx <= sp[1] else \
                                min(abs(cx - sp[0]), abs(cx - sp[1]))
                        # judge by which ink it is nearer to, not by a hard
                        # boundary: a mark can overhang its letter slightly
                        if _d(own) <= _d(other) + 1.0:
                            continue
                        out.append((fam, e))
                return out
            mine = _stray(r, sp_r, sp_v)
            theirs = _stray(v, sp_v, sp_r)
            if not mine or not theirs:
                continue
            for fam1, e1 in list(mine):
                match = next(((f2, e2) for f2, e2 in theirs if f2 == fam1), None)
                if match is None:
                    continue
                theirs.remove(match)
                _omove(e1, r, v)
                _omove(match[1], v, r)

    # A dammatan drawn as ONE glyph, and the small waw: both share the damma's
    # outline, so the table names all three "damma". The text separates them —
    # the tanween rides above the word's last letter, the small waw sits down
    # at writing level after it.
    for r in owords:
        txt = r["w"]["uthmani"]
        els9 = [e for a in r["at"] for e in a["els"]]
        # a welded pair counts through its master, and that master is exactly
        # what needs the tanween's name
        dms = [e for e in els9 if e.get("mark") == "damma"
               and not e.get("mkpart")]
        if not dms:
            continue
        plain = txt.count("\u064f")
        want_dt = txt.count("\u064c") + txt.count("\u08f1")
        want_sw = txt.count("\u06e5")
        have_dt = sum(1 for e in els9 if e.get("mark") == "dammatan"
                      and not e.get("mkpart"))
        have_sw = sum(1 for e in els9 if e.get("mark") == "small-waw"
                      and not e.get("mkpart"))
        bods9 = [e for e in els9 if e["kind"] == "body"]
        if not bods9:
            continue
        top9 = min(e["y1"] for e in bods9)
        bot9 = max(e["y2"] for e in bods9)
        lx9 = min(e["x1"] for e in bods9)
        # the small waw first: it is the one sitting AT writing level
        for _ in range(max(0, want_sw - have_sw)):
            cands = [e for e in dms
                     if (e["y1"] + e["y2"]) / 2 > top9 + 0.45 * (bot9 - top9)]
            if len(dms) <= plain or not cands:
                break
            mv = min(cands, key=lambda e: abs((e["x1"] + e["x2"]) / 2 - lx9))
            mv["mark"] = "small-waw"
            dms.remove(mv)
        # then the tanween: the surplus curl nearest the end of the word
        for _ in range(max(0, want_dt - have_dt)):
            if len(dms) <= plain:
                break
            mv = min(dms, key=lambda e: abs((e["x1"] + e["x2"]) / 2 - lx9))
            mv["mark"] = "dammatan"
            for _m in mv.get("mkmembers", []):
                _m["mark"] = "dammatan"
            dms.remove(mv)

    # The hamza of a seated alef: أ ؤ ئ carry it ABOVE, إ carries it BELOW.
    # Its outline is not always in the shape table, and where it sits under an
    # alef the position labeller can even read it as a wasla — which is
    # impossible, since a wasla only ever sits above. The text says the word
    # carries a hamza; the geometry says which mark it is.
    for r in owords:
        txt = r["w"]["uthmani"]
        want_h = (sum(txt.count(c) for c in "\u0623\u0625\u0624\u0626")
                  + txt.count("\u0654") + txt.count("\u0655"))
        if not want_h:
            continue
        els9 = [e for a in r["at"] for e in a["els"]]
        have_h = sum(1 for e in els9 if e.get("mark") == "hamza"
                     and not e.get("mkpart"))
        if have_h >= want_h:
            continue
        below = ("\u0625" in txt or "\u0655" in txt)
        has_wasla_text = "\u0671" in txt
        alefs = [e for e in els9 if e["kind"] == "body"
                 and (e["x2"] - e["x1"]) <= 7.0
                 and (e["y2"] - e["y1"]) >= 8.0]
        if not alefs:
            continue
        for _ in range(want_h - have_h):
            best = None
            for e in els9:
                if e["kind"] != "mark" or e.get("mkpart"):
                    continue
                mk = e.get("mark")
                if mk == "hamza":
                    continue
                if mk is None:
                    pass                  # unnamed ink: the likeliest hamza
                elif mk == "wasla" and not has_wasla_text and below:
                    pass                  # a wasla cannot sit below an alef
                else:
                    continue
                cx = (e["x1"] + e["x2"]) / 2
                for al in alefs:
                    if not (al["x1"] - 2.5 <= cx <= al["x2"] + 2.5):
                        continue
                    d = (e["y1"] - al["y2"]) if below else (al["y1"] - e["y2"])
                    if not (-2.0 <= d <= 5.0):
                        continue
                    if best is None or d < best[0]:
                        best = (d, e)
            if best is None:
                break
            best[1]["mark"] = "hamza"

    # Put every wasla over the alef it is drawn on, BEFORE the pass below
    # pulls alefs toward the words holding them. A wasla rides at the far left
    # of the word before it, standing over the NEXT word's opening alef, and
    # the split search — which sees overlap, not spelling — hands it to the
    # word it overlaps. Left uncorrected first, the pass below reads the stray
    # mark as proof and drags a second word's alef across to join it.
    def _alef6(e):
        return (e["kind"] == "body" and not e.get("mark")
                and (e["x2"] - e["x1"]) <= 6.0
                and (e["y2"] - e["y1"]) >= 6.0)

    def _stands_on(wa, e):
        ovx = min(e["x2"], wa["x2"]) - max(e["x1"], wa["x1"])
        d = e["y1"] - wa["y2"]
        return (ovx, d) if ovx > 0.5 and -1.5 <= d <= 5.0 else None

    for r in owords:
        # Only a word whose spelling has no ٱ at all is certainly not the
        # owner. Words that do have one keep their mark: neighbouring words
        # overlap — ٱلرَّحْمَـٰنِ and ٱلرَّحِيمِ share 18u on page 1 — so one
        # word's alef routinely lies under the other's wasla, and geometry
        # alone would hand the mark to the wrong one.
        if "\u0671" in r["w"]["uthmani"]:
            continue
        stray6 = [e for a in r["at"] for e in a["els"]
                  if e.get("mark") == "wasla" and not e.get("mkpart")]
        for wa in stray6:
            wcx = (wa["x1"] + wa["x2"]) / 2
            best = None
            for v in owords:
                if v is r or v["ln"] != r["ln"]:
                    continue
                txt6 = v["w"]["uthmani"]
                if "\u0671" not in txt6:
                    continue
                # No budget test here on purpose. These misplacements come in
                # chains — هُوَ holds ٱلسَّمِيعُ's wasla while ٱلسَّمِيعُ holds
                # ٱلْعَلِيمُ's — so every word in the middle already counts
                # right and a budget guard refuses the one move that would
                # start unwinding it. The alef underneath is proof enough.
                for a7 in v["at"]:
                    for e7 in a7["els"]:
                        if not _alef6(e7):
                            continue      # an alef is narrow and tall
                        hit = _stands_on(wa, e7)
                        if hit is None:
                            continue
                        ovx, d7 = hit
                        if best is None or (d7, -ovx) < (best[0], -best[1]):
                            best = (d7, ovx, v)
            if best:
                _omove(wa, r, best[2])

    # A wasla sits on an ALEF, always. So when a word whose text opens with ٱ
    # owns the wasla mark, the alef directly beneath it is that word's — even
    # where the previous word's tail sweeps underneath and the split search,
    # which can only cut consecutive runs, had to hand it over.
    for r in owords:
        if "\u0671" not in r["w"]["uthmani"]:
            continue
        wl6 = [e for a in r["at"] for e in a["els"]
               if e.get("mark") == "wasla" and not e.get("mkpart")]
        if not wl6:
            continue
        # holding more waslas than the spelling allows means one of them is a
        # neighbour's; pulling an alef under it would steal a letter too
        if len(wl6) > r["w"]["uthmani"].count("\u0671"):
            continue
        own = [e for a in r["at"] for e in a["els"] if e["kind"] == "body"]
        for wa in wl6:
            wcx = (wa["x1"] + wa["x2"]) / 2
            if any(b["x1"] - 1.0 <= wcx <= b["x2"] + 1.0
                   and (b["x2"] - b["x1"]) <= 6.0
                   and (b["y2"] - b["y1"]) >= 6.0
                   and -1.5 <= b["y1"] - wa["y2"] <= 4.0 for b in own):
                continue                  # its own alef is already here
            best = None
            for v in owords:
                if v is r or v["ln"] != r["ln"]:
                    continue
                for a7 in v["at"]:
                    for e7 in a7["els"]:
                        if e7["kind"] != "body" or e7.get("mark"):
                            continue
                        w7 = e7["x2"] - e7["x1"]
                        if w7 > 6.0 or (e7["y2"] - e7["y1"]) < 6.0:
                            continue      # an alef is narrow and tall
                        if not (e7["x1"] - 1.0 <= wcx <= e7["x2"] + 1.0):
                            continue      # must stand under the wasla
                        d7 = e7["y1"] - wa["y2"]
                        if not (-1.5 <= d7 <= 4.0):
                            continue
                        if best is None or d7 < best[0]:
                            best = (d7, e7, v)
            if best:
                _, e7, v = best
                _omove(e7, v, r)

    # Budget and ink corroborating one another. Where a word holds a surplus
    # of one family and the word beside it is short of exactly that family,
    # the counts say a transfer is owed; the ink then says WHICH mark and
    # confirms the direction. Neither signal is trusted alone here — counts
    # cannot see a swap that balances on both sides, and geometry alone moves
    # marks that were never misplaced — so the move is made only where the two
    # agree, and the mark must sit nearer the word that is short of it.
    _WANTC = {
        "fatha": "\u064e", "kasra": "\u0650", "damma": "\u064f",
        "fathatan": "\u064b\u08f0", "kasratan": "\u064d\u08f2",
        "dammatan": "\u064c\u08f1", "sukun": "\u0652\u06e1",
        "shadda": "\u0651", "maddah": "\u0653\u06e4",
        "small-alef": "\u0670", "wasla": "\u0671",
        "small-waw": "\u06e5", "small-ya": "\u06e6\u06e7",
        "small-circle": "\u06df\u06e0",
        "hamza": "\u0623\u0625\u0624\u0626\u0654\u0655",
    }
    _ABOVE8 = {"fatha", "damma", "sukun", "shadda", "maddah", "small-alef",
               "wasla", "fathatan", "dammatan", "small-circle", "hamza"}

    def _txt8(r, fam):
        t = r["w"]["uthmani"]
        return sum(t.count(c) for c in _WANTC[fam])

    def _held8(r, fam):
        return [e for a in r["at"] for e in a["els"]
                if e.get("mark") == fam and not e.get("mkpart")
                and not e.get("standalone")]

    def _bbox8(r):
        bs = [e for a in r["at"] for e in a["els"] if e["kind"] == "body"]
        if not bs:
            return None
        return (min(e["x1"] for e in bs), max(e["x2"] for e in bs),
                min(e["y1"] for e in bs), max(e["y2"] for e in bs))

    _byln8 = {}
    for _r8 in owords:
        if _r8["ln"] is not None:
            _byln8.setdefault(_r8["ln"], []).append(_r8)

    # Decide every transfer against ONE frozen reading of the page, then apply
    # them together. Deciding and moving in the same sweep lets a corrected
    # pair feed the next comparison: on p508 a fatha returned to ءَاسِنٍۢ was
    # immediately handed on again, leaving that word with none and its
    # neighbour with two. A move is also capped at the smaller of the two
    # imbalances, so a pair can never overshoot into the opposite error.
    _plan8 = []
    _spent8 = {}
    for _ln8, _grp8 in ({} if os.environ.get("QSVG_NB") == "0"
                        else _byln8).items():
        for a8 in _grp8:
            for b8 in _grp8:
                if a8 is b8:
                    continue
                wa, wb = a8["w"], b8["w"]
                if wa["surah"] != wb["surah"] or wa["ayah"] != wb["ayah"]:
                    continue
                if abs(wa["pos"] - wb["pos"]) != 1:
                    continue          # only the word right beside it
                bb = _bbox8(b8)
                ba = _bbox8(a8)
                if bb is None or ba is None:
                    continue
                for fam in _WANTC:
                    # The slash families are not settled here. A fatha and a
                    # kasra are the same stroke, named later from where it sits
                    # and what the word's budget allows, so handing one across
                    # a word boundary re-opens that decision for BOTH words and
                    # the renaming can come back differently — on p508 a kasra
                    # that landed correctly under غَيْرِ left both words with
                    # the wrong fatha count. Families whose name is fixed by
                    # shape alone have no such second act.
                    if fam in ("fatha", "kasra", "fathatan", "kasratan"):
                        continue
                    held = _held8(a8, fam)
                    if len(held) - _txt8(a8, fam) <= 0:
                        continue      # no surplus to give
                    if _txt8(b8, fam) - len(_held8(b8, fam)) <= 0:
                        continue      # the neighbour is not short of it
                    best = None
                    for e in held:
                        cx = (e["x1"] + e["x2"]) / 2
                        cy = (e["y1"] + e["y2"]) / 2
                        da = max(ba[0] - cx, cx - ba[1], 0.0)
                        db = max(bb[0] - cx, cx - bb[1], 0.0)
                        if db >= da:
                            continue  # not nearer the word that wants it
                        gap = (bb[2] - cy) if fam in _ABOVE8 else (cy - bb[3])
                        if gap < -3.0 or gap > 16.0:
                            continue  # not drawn against that word's letters
                        if best is None or (db, gap) < best[0]:
                            best = ((db, gap), e)
                    if best:
                        # Cap by WORD, not by pair: a word short of one fatha
                        # has two neighbours, and letting each hand one over
                        # leaves it holding two. Give only what the source can
                        # spare and take only what the destination lacks.
                        give = _spent8.get(("give", id(a8), fam), 0)
                        take = _spent8.get(("take", id(b8), fam), 0)
                        if (give < len(held) - _txt8(a8, fam)
                                and take < _txt8(b8, fam) - len(_held8(b8, fam))):
                            _spent8[("give", id(a8), fam)] = give + 1
                            _spent8[("take", id(b8), fam)] = take + 1
                            _plan8.append((best[1], a8, b8))

    _moved8 = set()
    for e8, src8, dst8 in _plan8:
        if id(e8) in _moved8:
            continue                  # one piece of ink moves once
        _moved8.add(id(e8))
        _omove(e8, src8, dst8)

    # A hamza standing on its own — ء — is a LETTER, and the spelling wants
    # no mark for it. Riding on a carrier it is a mark. The outline is the
    # same, so only the position tells them apart: the mark sits clear above
    # or below its carrier, while the letter stands on the line in sequence.
    # This runs late on purpose. Demote it any earlier and the passes that
    # name hamzas simply put the mark back, and the word ends up holding one
    # more than its spelling allows.
    _CARRIER9 = "\u0623\u0625\u0624\u0626\u0654\u0655"
    for r in owords:
        txt = r["w"]["uthmani"]
        if "\u0621" not in txt or os.environ.get("QSVG_HZA") == "0":
            continue
        want = sum(txt.count(c) for c in _CARRIER9)
        els = [e for a in r["at"] for e in a["els"]]
        hz = [e for e in els if e.get("mark") == "hamza"
              and not e.get("mkpart")]
        if len(hz) <= want:
            continue
        bods = [e for e in els if e["kind"] == "body"]
        if not bods:
            continue
        top = min(e["y1"] for e in bods)
        bot = max(e["y2"] for e in bods)
        inline = [e for e in hz
                  if e["y1"] >= top - 1.5 and e["y2"] <= bot + 1.5]
        inline.sort(key=lambda e: -((e["x2"] - e["x1"]) * (e["y2"] - e["y1"])))
        for e in inline[:len(hz) - want]:
            # Anything welded to it was counting through it. Turning the
            # master into letter ink would take its twins out of the count
            # with it, so free them first — a kasratan welded to the ء still
            # belongs to the word.
            for m in (e.get("mkmembers") or []):
                m["mkpart"] = False
            e["mkmembers"] = []
            e["kind"] = "body"
            e["mark"] = None
            e["lab"] = "letter-hamza"

    def _eff_pieces(bods):
        # a stroke drawn over/inside a wider sibling (the kaf armature, the
        # second stroke of a lam-alef) is part of that letter, not a piece
        out = []
        for b in bods:
            wb = b["x2"] - b["x1"]
            hb = b["y2"] - b["y1"]
            # a stroke DRAWN OVER a letter (the kaf armature, a lam-alef's
            # second stroke) sits within its host's height; a piece that rises
            # ABOVE its host is a letter of its own — the silent alef standing
            # on the waw of ـوا۟ — and must keep counting as a piece.
            inside = any(o is not b
                         and min(o["x2"], b["x2"]) - max(o["x1"], b["x1"])
                         >= 0.6 * wb
                         and (o["x2"] - o["x1"]) > wb
                         and hb <= (o["y2"] - o["y1"]) + 1.0
                         for o in bods)
            if not inside:
                out.append(b)
        return out

    # ... and that alef marks where the word STARTS. A piece reaching well to
    # the right of it is the PREVIOUS word's tail, swept underneath and handed
    # over by the consecutive-run split — but only give it back when that word
    # is provably short of pieces, so ordinary overlap is left alone.
    for r in owords:
        if "\u0671" not in r["w"]["uthmani"]:
            continue
        own = [e for a in r["at"] for e in a["els"] if e["kind"] == "body"]
        wl8 = [e for a in r["at"] for e in a["els"]
               if e.get("mark") == "wasla" and not e.get("mkpart")]
        alef = None
        for wa in wl8:
            wcx = (wa["x1"] + wa["x2"]) / 2
            for b in own:
                if (b["x1"] - 1.0 <= wcx <= b["x2"] + 1.0
                        and (b["x2"] - b["x1"]) <= 6.0
                        and -1.5 <= b["y1"] - wa["y2"] <= 4.0):
                    if alef is None or b["x2"] > alef["x2"]:
                        alef = b
        if alef is None:
            continue
        stray = [b for b in own if b is not alef and b["x2"] > alef["x2"] + 6.0]
        if not stray:
            continue
        prev = None
        for v in owords:
            if v is r or v["ln"] != r["ln"]:
                continue
            pb = [e for a in v["at"] for e in a["els"] if e["kind"] == "body"]
            if not pb or min(e["x1"] for e in pb) < alef["x2"] - 1.0:
                continue
            if len(_eff_pieces(pb)) >= v["nseg"]:
                continue                  # not short: leave its ink alone
            if prev is None or min(e["x1"] for e in pb) < prev[0]:
                prev = (min(e["x1"] for e in pb), v)
        if prev:
            pb2 = [e for a in prev[1]["at"] for e in a["els"]
                   if e["kind"] == "body"]
            px1 = min(e["x1"] for e in pb2)
            px2 = max(e["x2"] for e in pb2)
            for b in stray:
                # the tail must actually touch the word it is given back to
                if max(px1 - b["x2"], b["x1"] - px2, 0.0) > 4.0:
                    continue
                _omove(b, r, prev[1])

    # Iqlab tanween (ً ٌ ٍ followed by ۢ or ۭ): the nunation becomes a MEEM, so
    # this script does not double the stroke — it draws ONE vowel stroke plus a
    # small meem. Reading it as a plain vowel leaves the word a tanween short
    # and the meem filed as letter ink. The text names both.
    _IQTAN = {"\u064b": ("fathatan", "fatha", "\u064e"),
              "\u064c": ("dammatan", "damma", "\u064f"),
              "\u0650" if False else "\u064d": ("kasratan", "kasra", "\u0650")}
    for r in owords:
        txt = r["w"]["uthmani"]
        want = [_IQTAN[txt[i]] for i in range(len(txt) - 1)
                if txt[i] in _IQTAN and txt[i + 1] in ("\u06e2", "\u06ed")]
        if not want:
            continue
        els = [e for a in r["at"] for e in a["els"]]
        rx1 = min((e["x1"] for e in els if e["kind"] == "body"), default=None)
        if rx1 is None:
            continue
        for tan, base, plain_ch in want:
            if any(e.get("mark") == tan and not e.get("mkpart") for e in els):
                continue                  # already named
            if base == "damma":
                pool = [e for e in els if e.get("mark") == "damma"
                        and not e.get("mkpart") and not e.get("mkmembers")]
                spare = len(pool) - txt.count(plain_ch)
            else:
                # the table names every slash by position alone, so a lone
                # kasratan stroke can arrive called "fatha": pool both.
                pool = [e for e in els if e.get("mark") in ("fatha", "kasra")
                        and not e.get("mkpart") and not e.get("mkmembers")]
                spare = len(pool) - txt.count("\u064e") - txt.count("\u0650")
            if spare <= 0 or not pool:
                continue                  # no stroke to spare: nothing to name
            bods = [e for e in els if e["kind"] == "body"]
            mid = ((min(e["y1"] for e in bods) + max(e["y2"] for e in bods)) / 2
                   if bods else 0.0)
            below = tan == "kasratan"
            zone = [e for e in pool
                    if ((e["y1"] + e["y2"]) / 2 > mid) == below] or pool
            # the tanween sits at the END of the word — nearest its left edge
            mv = min(zone, key=lambda e: abs((e["x1"] + e["x2"]) / 2 - rx1))
            mv["mark"] = tan
            # ... and its meem rides just beside it, usually filed as letter ink
            if any(e.get("mark") == "meem-iqlab" and not e.get("mkpart")
                   for e in els):
                continue
            cx = (mv["x1"] + mv["x2"]) / 2
            cy = (mv["y1"] + mv["y2"]) / 2
            best = None
            for e in els:
                if e.get("mark") or e is mv:
                    continue
                w2 = e["x2"] - e["x1"]; h2 = e["y2"] - e["y1"]
                if not (1.5 <= w2 <= 12.0 and 3.0 <= h2 <= 12.0):
                    continue
                d = abs((e["x1"] + e["x2"]) / 2 - cx) \
                    + abs((e["y1"] + e["y2"]) / 2 - cy)
                if d < 14.0 and (best is None or d < best[0]):
                    best = (d, e)
            if best:
                e2 = best[1]
                e2["kind"] = "mark"
                e2["mark"] = "meem-iqlab"
                e2.pop("lab", None)

    # Fathatan and kasratan are the SAME pair of strokes — only their position
    # tells them apart, and the table names them by shape alone. The text is
    # authoritative: rename by what the word actually carries, lowest strokes
    # first, then weld any pair still standing as two units into one mark.
    for r in owords:
        txt = r["w"]["uthmani"]
        want_ft = txt.count("\u064b") + txt.count("\u08f0")
        want_kt = txt.count("\u064d") + txt.count("\u08f2")
        if not (want_ft or want_kt):
            continue
        els = [e for a in r["at"] for e in a["els"]]
        have = [e for e in els if e.get("mark") in ("fathatan", "kasratan")
                and not e.get("mkpart")]
        if not have:
            continue
        if len(have) == want_ft + want_kt:
            have.sort(key=lambda e: -(e["y1"] + e["y2"]))    # lowest first
            for i, e in enumerate(have):
                nm = "kasratan" if i < want_kt else "fathatan"
                e["mark"] = nm
                for m in e.get("mkmembers", []):
                    m["mark"] = nm
            continue
        # more units than the text allows: the strokes of one tanween are
        # still standing apart — weld the closest same-named pair
        for nm, wn in (("fathatan", want_ft), ("kasratan", want_kt)):
            grp = [e for e in els if e.get("mark") == nm and not e.get("mkpart")]
            while len(grp) > wn and wn >= 0:
                best = None
                for i, a1 in enumerate(grp):
                    for b1 in grp[i + 1:]:
                        dx = abs((a1["x1"] + a1["x2"]) / 2
                                 - (b1["x1"] + b1["x2"]) / 2)
                        dy = abs((a1["y1"] + a1["y2"]) / 2
                                 - (b1["y1"] + b1["y2"]) / 2)
                        if dx < 8.0 and dy < 7.0 and (best is None
                                                      or dx + dy < best[0]):
                            best = (dx + dy, a1, b1)
                if not best:
                    break
                _, a1, b1 = best
                top, bot = (a1, b1) if a1["y1"] <= b1["y1"] else (b1, a1)
                bot["mkpart"] = True
                top["mkmembers"] = top.get("mkmembers", []) + [bot]
                grp.remove(bot)

    _DOTUNIT = {"dot": 1, "two-dots": 2, "three-dots": 3}

    # A letter's dot GROUP can be drawn as several pieces (the three dots of
    # sheen as a two-dot path plus a one-dot path). When a word holds more dot
    # pieces than its skeleton has dotted letters, but the right number of dot
    # UNITS, the touching pieces are one group: weld them into a single mark.
    def _dot_groups(txt):
        raw = _LETTER.findall(txt)
        sk = [(HAMZA_MAP[ch][0] if ch in HAMZA_MAP else ch, ch in HAMZA_MAP)
              for ch in raw]
        out = []
        for i, (ch, seat) in enumerate(sk):
            if seat or ch not in DOTS:
                continue
            if ch == "\u064a" and i == len(sk) - 1:
                continue
            out.append(_DOTUNIT.get(DOTS[ch][0], 0))
        return out

    for r in owords:
        groups = _dot_groups(r["w"]["uthmani"])
        pieces = [e for a in r["at"] for e in a["els"]
                  if e.get("mark") in _DOTUNIT and not e.get("mkpart")]
        if len(pieces) <= len(groups):
            continue
        units = sum(_DOTUNIT[e["mark"]] for e in pieces)
        if units != sum(groups) or 3 not in groups:
            continue                  # only a 3-dot group splits in this art
        best = None
        for i, a1 in enumerate(pieces):
            for b1 in pieces[i + 1:]:
                if _DOTUNIT[a1["mark"]] + _DOTUNIT[b1["mark"]] != 3:
                    continue
                dx = abs((a1["x1"] + a1["x2"]) / 2 - (b1["x1"] + b1["x2"]) / 2)
                dy = abs((a1["y1"] + a1["y2"]) / 2 - (b1["y1"] + b1["y2"]) / 2)
                if dx < 6.0 and dy < 6.0 and (best is None or dx + dy < best[0]):
                    best = (dx + dy, a1, b1)
        if best:
            _, a1, b1 = best
            top, bot = (a1, b1) if a1["y1"] <= b1["y1"] else (b1, a1)
            top["mark"] = "three-dots"
            bot["mark"] = "three-dots"
            bot["mkpart"] = True
            top["mkmembers"] = top.get("mkmembers", []) + [bot]

    # Containment repair: a letter piece drawn INSIDE another word's ink
    # belongs to that word. The tanween alef of a word like شَرًّۭا is drawn
    # tucked under its own body, so a neighbour whose cluster reached across
    # can hold it while the owner is left a segment short.
    def _bodies(r):
        return [e for a in r["at"] for e in a["els"] if e["kind"] == "body"]

    for v in owords:
        vb = _bodies(v)
        if len(vb) < 2:
            continue
        for e in list(vb):
            if e.get("lab") in ("letter", "letter-part", "letter-hamza"):
                pass                    # letter ink is exactly what may move
            for r in owords:
                if r is v or r["ln"] is None or v["ln"] is None \
                        or r["ln"] != v["ln"]:
                    continue
                rb = _bodies(r)
                if not rb or len(rb) >= r["nseg"]:
                    continue            # only a word short of pieces claims
                rx1 = min(x["x1"] for x in rb)
                rx2 = max(x["x2"] for x in rb)
                if not (rx1 - 0.5 <= e["x1"] and e["x2"] <= rx2 + 0.5):
                    continue            # must be strictly inside its ink
                others = [x for x in vb if x is not e]
                if not others:
                    continue
                ox1 = min(x["x1"] for x in others)
                ox2 = max(x["x2"] for x in others)
                if ox1 - 0.5 <= e["x1"] and e["x2"] <= ox2 + 0.5:
                    continue            # also inside its holder: ambiguous
                _omove(e, v, r)
                vb.remove(e)
                break

    # Segment budgets: Arabic joining rules fix how many disconnected letter
    # groups a word is drawn with. A word holding MORE pieces than its text
    # allows, next to one holding fewer, has taken its neighbour's ligature —
    # hand back the piece that touches the short word's ink.
    for _round in range(3):
        moved_any = False
        for v in owords:
            vb0 = [e for a in v["at"] for e in a["els"] if e["kind"] == "body"]
            vb = _eff_pieces(vb0)
            if len(vb) <= v["nseg"]:
                continue
            for r in owords:
                if r is v or r["ln"] is None or v["ln"] is None \
                        or abs(r["ln"] - v["ln"]) > 1:
                    continue
                rb0 = [e for a in r["at"] for e in a["els"]
                       if e["kind"] == "body"]
                rb = _eff_pieces(rb0)
                if not rb or len(rb) >= r["nseg"]:
                    continue
                rx1 = min(e["x1"] for e in rb0)
                rx2 = max(e["x2"] for e in rb0)
                # only the piece at the very edge facing the short word can
                # be its ligature — an interior piece is the donor's own
                # which side the short word lies on — by centre, since two
                # words' ink commonly overlaps where a tail sweeps across
                left = ((rx1 + rx2) / 2
                        < (min(e["x1"] for e in vb)
                           + max(e["x2"] for e in vb)) / 2)
                edge = (min(vb, key=lambda e: e["x1"]) if left
                        else max(vb, key=lambda e: e["x2"]))
                best = None
                for e in vb:
                    if left and e["x1"] > edge["x1"] + 1.0:
                        continue
                    if not left and e["x2"] < edge["x2"] - 1.0:
                        continue
                    gap = max(rx1 - e["x2"], e["x1"] - rx2, 0.0)
                    if gap > _SEG_GAP:
                        continue          # must be near the short word's ink
                    if r["ln"] != v["ln"]:
                        # across a line break the ink must sit clearly in the
                        # receiver's band, not merely near its column
                        cy = (e["y1"] + e["y2"]) / 2
                        if not (r["top"] - 2.0 <= cy <= r["bot"] + 2.0):
                            continue
                        if v["top"] - 2.0 <= cy <= v["bot"] + 2.0:
                            continue      # equally at home in its holder
                    rest = [x for x in vb if x is not e]
                    if len(rest) < v["nseg"]:
                        continue          # never fall below the donor's own
                    if best is None or gap < best[0]:
                        best = (gap, e)
                if best is None:
                    continue
                _omove(best[1], v, r)
                vb.remove(best[1])
                moved_any = True
                if len(vb) <= v["nseg"]:
                    break
        if not moved_any:
            break

    # Dot budgets: a word's skeleton says exactly how many letter dots it
    # carries, and dots are drawn wherever the calligraphy has room — the two
    # dots of an initial ya can sit over the PREVIOUS word's raa. A word that
    # holds more dot units than its letters can own gives the surplus to a
    # neighbour that is short, when the ink is within reach of that neighbour.
    # Ink drawn in another line's territory. A word can steal from the line
    # above or below it, not just from its neighbour along the line, and
    # nothing here could see that: once a word absorbs a stolen letter, the
    # letter joins its outline and the word looks close to ink it should never
    # have held. Measuring the ink against the word's OTHER letters exposes it.
    # The victim is not required to stand over the ink either — robbed of a
    # letter, its span stops short of the very thing it is missing.
    _CROSS_X = 8.0          # about one letter's reach beside the victim's ink
    _byln5 = {}
    for _r5 in owords:
        if _r5["ln"] is not None:
            _byln5.setdefault(_r5["ln"], []).append(_r5)

    def _span5(bods):
        return (min(b["x1"] for b in bods), max(b["x2"] for b in bods),
                min(b["y1"] for b in bods), max(b["y2"] for b in bods))

    _plan5 = []
    for r in owords:
        if r["ln"] is None:
            continue
        els = [e for a in r["at"] for e in a["els"]]
        bods = [e for e in els if e["kind"] == "body"]
        if len(bods) < 2:
            continue
        for e in els:
            if e.get("mkpart") or e.get("standalone"):
                continue
            rest = [b for b in bods if b is not e]
            if not rest:
                continue
            _, _, ry1, ry2 = _span5(rest)
            cx = (e["x1"] + e["x2"]) / 2
            cy = (e["y1"] + e["y2"]) / 2
            own = max(ry1 - cy, cy - ry2, 0.0)
            if own <= 8.0:
                continue          # sitting with its own word, as ink should
            best = None
            for dl in (-1, 1):
                for v in _byln5.get(r["ln"] + dl, ()):
                    vb = [b for a in v["at"] for b in a["els"]
                          if b["kind"] == "body"]
                    if not vb:
                        continue
                    vx1, vx2, vy1, vy2 = _span5(vb)
                    xd = max(vx1 - e["x2"], e["x1"] - vx2, 0.0)
                    if xd > _CROSS_X:
                        continue
                    d = max(vy1 - cy, cy - vy2, 0.0)
                    if best is None or (d + xd) < (best[0] + best[1]):
                        best = (d, xd, v)
            if best is None:
                continue
            d, xd, v = best
            if d + 5.0 >= own:
                continue          # not decisively the other line's
            if e["kind"] == "body":
                # the victim must actually be short of a letter piece
                vb = [b for a in v["at"] for b in a["els"]
                      if b["kind"] == "body"]
                if len(_eff_pieces(vb)) >= v["nseg"]:
                    continue
            else:
                fam = e.get("mark")
                if fam not in _WANTC:
                    continue
                # Not the slash families. A fatha and a kasra are one stroke
                # named later from where it sits and what the word's budget
                # allows, so carrying one to another line re-opens that
                # decision for both words and the renaming can come back
                # differently — p446 and p576 each lost two words that way.
                if fam in ("fatha", "kasra", "fathatan", "kasratan"):
                    continue
                txt_r = r["w"]["uthmani"]
                have_r = sum(1 for q in els if q.get("mark") == fam
                             and not q.get("mkpart"))
                if have_r <= sum(txt_r.count(c) for c in _WANTC[fam]):
                    continue      # the holder is not carrying a surplus
            _plan5.append((e, r, v))

    _done5 = set()
    for e5, src5, dst5 in _plan5:
        if id(e5) in _done5:
            continue
        _done5.add(id(e5))
        e5["line"] = dst5["ln"]
        _omove(e5, src5, dst5)

    def _dots_want(txt):
        raw = _LETTER.findall(txt)
        # a hamza-carrying seat (ئ ؤ أ إ) is drawn WITHOUT its letter's dots
        sk = [(HAMZA_MAP[ch][0] if ch in HAMZA_MAP else ch, ch in HAMZA_MAP)
              for ch in raw]
        n = 0
        for i, (ch, seat) in enumerate(sk):
            if seat or ch not in DOTS:
                continue
            if ch == "\u064a" and i == len(sk) - 1:
                continue              # a final ya is drawn undotted here
            n += _DOTUNIT.get(DOTS[ch][0], 0)
        return n

    def _dots_have(r):
        return sum(_DOTUNIT[e["mark"]] for a in r["at"] for e in a["els"]
                   if e.get("mark") in _DOTUNIT and not e.get("mkpart"))

    for _round in range(2):
        moved_any = False
        for r in owords:
            want_r = _dots_want(r["w"]["uthmani"])
            have_r = _dots_have(r)
            if have_r <= want_r:
                continue
            mine = [e for a in r["at"] for e in a["els"]
                    if e.get("mark") in _DOTUNIT and not e.get("mkpart")]
            for v in owords:
                if v is r or v["ln"] is None or r["ln"] is None \
                        or abs(v["ln"] - r["ln"]) > 1:
                    continue
                want_v = _dots_want(v["w"]["uthmani"])
                have_v = _dots_have(v)
                if have_v >= want_v:
                    continue
                vx1, vx2 = _ospan(v)
                rx1, rx2 = _ospan(r)
                cands = []
                for e in mine:
                    u = _DOTUNIT[e["mark"]]
                    if have_r - u < want_r or have_v + u > want_v:
                        continue          # the move must fix, not overshoot
                    cx = (e["x1"] + e["x2"]) / 2
                    if not (vx1 - _DOT_REACH < cx < vx2 + _DOT_REACH):
                        continue          # must sit over the receiver's ink
                    cy = (e["y1"] + e["y2"]) / 2
                    if not (v["top"] - 9.0 < cy < v["bot"] + 9.0):
                        continue          # ... and at its writing level
                    # prefer ink the donor cannot plausibly own: nearer the
                    # receiver's centre than the donor's
                    dv = abs(cx - (vx1 + vx2) / 2)
                    dr = abs(cx - (rx1 + rx2) / 2)
                    cands.append((dv - dr, dv, e))
                if not cands:
                    continue
                cands.sort(key=lambda t: (t[0], t[1]))
                _, _, mv = cands[0]
                _omove(mv, r, v)
                mine.remove(mv)
                mv["line"] = v["ln"]
                have_r -= _DOTUNIT[mv["mark"]]
                moved_any = True
                if have_r <= want_r:
                    break
        if not moved_any:
            break

    # Letter-ink rescue: an UNLABELED mark of letter size is stranded letter
    # ink — a ن bowl classified as a mark and re-lined onto a neighbouring
    # line's word. Hand it, as a body, to the word (same or adjacent line,
    # x-overlapping) whose QCF width ratio improves most; its dot rides along.
    _qall = qcf_widths()

    def _wlog(r, extra=None, drop=()):
        els = [e for a in r["at"] for e in a["els"] if e not in drop]
        if extra is not None:
            els = els + [extra]
        bods = [e for e in els if e["kind"] == "body"
                or e.get("mark") in ("small-ya", "small-waw")
                or e is extra]          # a rescued piece counts as letter ink
        if not bods:
            return None
        span = max(e["x2"] for e in bods) - min(e["x1"] for e in bods)
        qw = _qall.get("%d:%d:%d" % (r["w"]["surah"], r["w"]["ayah"],
                                     r["w"]["pos"]))
        if not qw or any(m in r["w"]["uthmani"] for m in "\u06de\u06e9"):
            return None
        rs = [y for y in owords if y["ln"] == r["ln"]]
        ta = tq = 0.0
        for y in rs:
            sp = _ospan(y)
            ta += sp[1] - sp[0]
            tq += _qall.get("%d:%d:%d" % (y["w"]["surah"], y["w"]["ayah"],
                                          y["w"]["pos"]), 0)
        if not tq or not ta:
            return None
        return abs(math.log(max(span / (qw / tq * ta), 1e-3)))

    for r in owords:
        strays = [e for a in r["at"] for e in a["els"]
                  if e["kind"] == "mark" and not e.get("mark")
                  and not e.get("mkpart")
                  and max(e["x2"] - e["x1"], e["y2"] - e["y1"]) >= 7.5]
        if strays and os.environ.get("QSVG_DBG_RESC"):
            print("RESC strays in %s: %s" % (r["w"]["uthmani"],
                  ["x%.0f..%.0f y%.0f..%.0f" % (e["x1"], e["x2"], e["y1"], e["y2"])
                   for e in strays]), file=sys.stderr)
        for e in strays:
            riders = [x for a in r["at"] for x in a["els"]
                      if x is not e and x["kind"] == "mark"
                      and not x.get("mkpart")
                      and (not x.get("mark") or x.get("mark") in
                           ("dot", "two-dots", "three-dots"))
                      and x["x1"] > e["x1"] - 2.5 and x["x2"] < e["x2"] + 2.5
                      and x["y1"] > e["y1"] - 6.0 and x["y2"] < e["y2"] + 6.0]
            cur = _wlog(r, drop=[e] + riders)
            cur0 = _wlog(r)
            best = None
            for v in owords:
                if v is r or v["ln"] is None or r["ln"] is None \
                        or abs(v["ln"] - r["ln"]) > 1:
                    continue
                vx1, vx2 = _ospan(v)
                cx = (e["x1"] + e["x2"]) / 2
                # a word missing its FINAL letter has a span that stops short
                # on the left — reach further in the reading direction
                if not (vx1 - 12.0 < cx < vx2 + 4.0):
                    continue
                w_now = _wlog(v)
                w_with = _wlog(v, extra=e)
                if w_now is None or w_with is None:
                    continue
                gain = w_now - w_with
                if os.environ.get("QSVG_DBG_RESC"):
                    print("RESC cand v=%s gain=%.2f now=%.2f with=%.2f"
                          % (v["w"]["uthmani"], gain, w_now, w_with),
                          file=sys.stderr)
                if gain > 0.2 and (best is None or gain > best[0]):
                    best = (gain, v)
            if best is None:
                continue
            hold_gain = 0.0 if cur is None or cur0 is None else cur0 - cur
            if best[0] + hold_gain <= 0.25:
                continue
            v = best[1]
            e["kind"] = "body"
            e["line"] = v["ln"]
            _omove(e, r, v)
            for x in riders:
                x["line"] = v["ln"]
                _omove(x, r, v)

    # Iqlab meem recovery: the small م of نۢ shares its outline with letter
    # fragments, so the table can force it into the NEXT word as body ink.
    # The text names its owner: a word with a ۢ budget and no meem-iqlab
    # claims a small م-sized body piece standing at its left edge.
    for r in owords:
        # only ۢ (U+06E2) is drawn as a separate small م in this art; the
        # low ۭ of iqlab tanween leaves no standalone glyph to claim
        want_m = r["w"]["uthmani"].count("\u06e2")
        if not want_m:
            continue
        have_m = sum(1 for a in r["at"] for e in a["els"]
                     if e.get("mark") == "meem-iqlab" and not e.get("mkpart"))
        if have_m >= want_m:
            continue
        rx1, rx2 = _ospan(r)
        best = None
        for v in owords:
            if v is r or v["ln"] is None or r["ln"] is None \
                    or abs(v["ln"] - r["ln"]) > 1:
                continue
            for a in v["at"]:
                for e in a["els"]:
                    if e["kind"] != "body" or e.get("mark"):
                        continue
                    w2 = e["x2"] - e["x1"]; h2 = e["y2"] - e["y1"]
                    if os.environ.get("QSVG_DBG_MEEM") and abs(e["x1"] - 291) < 3 \
                            and r["w"]["uthmani"].startswith("\u0645"):
                        print("MEEM-CAND x%.0f..%.0f y%.0f..%.0f w%.1f h%.1f donor=%s"
                              % (e["x1"], e["x2"], e["y1"], e["y2"], w2, h2,
                                 v["w"]["uthmani"]), file=sys.stderr)
                    if not (2.0 <= w2 <= 6.0 and 5.0 <= h2 <= 12.0):
                        continue
                    cx = (e["x1"] + e["x2"]) / 2
                    d = abs(cx - rx1)          # iqlab م trails at the LEFT edge
                    if d > 8.0:
                        continue
                    # ... at its word's writing level or riding just above it
                    # (ۢ is a superscript م), never a stroke from another line
                    # (the ك armature of the line above sits far higher)
                    rb = [x for a2 in r["at"] for x in a2["els"]
                          if x["kind"] == "body"]
                    if rb:
                        ry1 = min(x["y1"] for x in rb)
                        ry2 = max(x["y2"] for x in rb)
                        cy = (e["y1"] + e["y2"]) / 2
                        if not (ry1 - 12.0 <= cy <= ry2 + 2.0):
                            if os.environ.get("QSVG_DBG_MEEM"):
                                print("MEEM-YREJ cy=%.0f ry=%.0f..%.0f w=%s"
                                      % (cy, ry1, ry2, r["w"]["uthmani"]),
                                      file=sys.stderr)
                            continue
                    # the donor must not need the piece as a letter segment
                    vb = [x for a2 in v["at"] for x in a2["els"]
                          if x["kind"] == "body" and x is not e]
                    if len(vb) < max(1, v["nseg"]):
                        if os.environ.get("QSVG_DBG_MEEM"):
                            print("MEEM-REJ nseg donor=%s piece x%.0f nseg=%d nb=%d"
                                  % (v["w"]["uthmani"], e["x1"], v["nseg"],
                                     len(vb)), file=sys.stderr)
                        continue
                    if best is None or d < best[0]:
                        best = (d, e, v)
        if os.environ.get("QSVG_DBG_MEEM"):
            print("MEEM want=%d have=%d word=%s rx1=%.0f best=%s"
                  % (want_m, have_m, r["w"]["uthmani"], rx1,
                     "None" if best is None else "d=%.1f x%.0f..%.0f y%.0f..%.0f"
                     % (best[0], best[1]["x1"], best[1]["x2"],
                        best[1]["y1"], best[1]["y2"])), file=sys.stderr)
        if best:
            _, e, v = best
            e["kind"] = "mark"
            e["mark"] = "meem-iqlab"
            e.pop("lab", None)
            e["line"] = r["ln"]
            _omove(e, v, r)

    # Unassigned strays: a mark sitting in no word joins an adjacent word that
    # still has budget for its family — including the letter-dot budget derived
    # from the word's own skeleton.
    _DOTU = {"dot": 1, "two-dots": 2, "three-dots": 3}

    def _dot_want(txt):
        raw = _LETTER.findall(txt)
        sk = [(HAMZA_MAP[ch][0] if ch in HAMZA_MAP else ch, ch in HAMZA_MAP)
              for ch in raw]
        n = 0
        for i, (ch, seat) in enumerate(sk):
            if seat or ch not in DOTS:
                continue
            if ch == "\u064a" and i == len(sk) - 1:
                continue
            n += _DOTU.get(DOTS[ch][0], 0)
        return n

    free = []
    for w0, at0 in assignment:
        if w0:
            continue
        for a0 in at0:
            for e in a0["els"]:
                if e["kind"] == "mark" and not e.get("mkpart") \
                        and not e.get("offcanvas") and not e.get("standalone"):
                    free.append((e, a0))
    for e, a0 in free:
        cx = (e["x1"] + e["x2"]) / 2
        fam = _OFAM.get(e.get("mark"))
        dotu = _DOTU.get(e.get("mark"), 0)
        best = None
        for r in owords:
            if r["ln"] is None or e.get("line") is None \
                    or abs(r["ln"] - e["line"]) > 1:
                continue
            rx1, rx2 = _ospan(r)
            if not (rx1 - 2.0 < cx < rx2 + 2.0):
                continue
            els_r = [x for a in r["at"] for x in a["els"]]
            need = False
            if fam:
                have = sum(1 for x in els_r
                           if _OFAM.get(x.get("mark")) == fam
                           and not x.get("mkpart"))
                need = have < r["caps"].get(fam, 0)
            elif dotu:
                have = sum(_DOTU.get(x.get("mark"), 0) for x in els_r
                           if not x.get("mkpart"))
                need = have + dotu <= _dot_want(r["w"]["uthmani"])
            if not need:
                continue
            d = abs((rx1 + rx2) / 2 - cx)
            if best is None or d < best[0]:
                best = (d, r)
        if best is None:
            continue
        r = best[1]
        if e in a0["els"]:
            a0["els"].remove(e)
            for m in e.get("mkmembers", []):
                if m in a0["els"]:
                    a0["els"].remove(m)
            tgt = min(r["at"], key=lambda a2: min(abs((x["x1"] + x["x2"]) / 2
                      - (e["x1"] + e["x2"]) / 2) for x in a2["els"])
                      if a2["els"] else 1e9)
            tgt["els"].append(e)
            tgt["els"].extend(e.get("mkmembers", []))

    # Re-run tanween pairing/welding: the repair layers may have reunited a
    # pair that was split at first-weld time.
    for r in owords:
        txt = r["w"]["uthmani"]
        els_r = [e for a in r["at"] for e in a["els"]]
        for single, tan, chars_s, chars_t in (
                ("damma", "dammatan", "\u064f", "\u064c\u08f1"),
                ("fatha", "fathatan", "\u064e", "\u064b\u08f0"),
                ("kasra", "kasratan", "\u0650", "\u064d\u08f2")):
            want_t = sum(txt.count(ch) for ch in chars_t)
            if not want_t:
                continue
            have_t = sum(1 for e in els_r if e.get("mark") == tan
                         and not e.get("mkpart"))
            singles = [e for e in els_r if e.get("mark") == single
                       and not e.get("mkpart")]
            want_s = sum(txt.count(ch) for ch in chars_s)
            # a pair drawn with mixed labels: lone tan-master absorbs the
            # nearest spare single as its part
            tans = [e for e in els_r if e.get("mark") == tan
                    and not e.get("mkpart") and not e.get("mkmembers")]
            for tm in tans:
                if len(singles) - want_s < 1:
                    break
                near = [e for e in singles
                        if abs((e["x1"] + e["x2"]) / 2
                               - (tm["x1"] + tm["x2"]) / 2) < 8.0
                        and abs((e["y1"] + e["y2"]) / 2
                                - (tm["y1"] + tm["y2"]) / 2) < 7.0]
                if not near:
                    continue
                pt = min(near, key=lambda e: abs((e["x1"] + e["x2"]) / 2
                                                 - (tm["x1"] + tm["x2"]) / 2))
                pt["mark"] = tan
                pt["mkpart"] = True
                tm.setdefault("mkmembers", []).append(pt)
                singles.remove(pt)
            while len(singles) - want_s >= 2 and have_t < want_t:
                best = None
                for i2, a2 in enumerate(singles):
                    for b2 in singles[i2 + 1:]:
                        dx = abs((a2["x1"] + a2["x2"]) / 2
                                 - (b2["x1"] + b2["x2"]) / 2)
                        dy = abs((a2["y1"] + a2["y2"]) / 2
                                 - (b2["y1"] + b2["y2"]) / 2)
                        if dx < 8.0 and dy < 7.0 and (best is None
                                                      or dx + dy < best[0]):
                            best = (dx + dy, a2, b2)
                if not best:
                    break
                _, a2, b2 = best
                top, bot2 = (a2, b2) if (a2["y1"] + a2["y2"]) \
                    <= (b2["y1"] + b2["y2"]) else (b2, a2)
                top["mark"] = tan
                bot2["mark"] = tan
                bot2["mkpart"] = True
                top.setdefault("mkmembers", []).append(bot2)
                singles.remove(a2)
                singles.remove(b2)
                have_t += 1
            # the art's tanween halves are not always labeled alike: a spare
            # single (or a duplicate tan half) hugging a tan master is that
            # master's second curl
            masters = [e for e in els_r if e.get("mark") == tan
                       and not e.get("mkpart")]
            def _near(a3, b3):
                return (abs((a3["x1"] + a3["x2"]) / 2
                            - (b3["x1"] + b3["x2"]) / 2) < 8.0
                        and abs((a3["y1"] + a3["y2"]) / 2
                                - (b3["y1"] + b3["y2"]) / 2) < 7.0)
            while len(masters) > want_t:
                pair = next(((m1, m2) for i3, m1 in enumerate(masters)
                             for m2 in masters[i3 + 1:] if _near(m1, m2)), None)
                if not pair:
                    break
                m1, m2 = pair
                m2["mark"] = tan
                m2["mkpart"] = True
                m1.setdefault("mkmembers", []).append(m2)
                masters.remove(m2)
            while len(singles) > want_s and masters:
                pair = next(((sgl, m1) for sgl in singles for m1 in masters
                             if not m1.get("mkmembers") and _near(sgl, m1)),
                            None)
                if not pair:
                    break
                sgl, m1 = pair
                sgl["mark"] = tan
                sgl["mkpart"] = True
                m1.setdefault("mkmembers", []).append(sgl)
                singles.remove(sgl)
            # kasratan/fathatan strokes carry whatever slash name the position
            # pass guessed: weld two spare slash strokes of any name
            if tan in ("fathatan", "kasratan") and have_t < want_t:
                other = "kasra" if single == "fatha" else "fatha"
                spare2 = [e for e in els_r
                          if e.get("mark") in (single, other)
                          and not e.get("mkpart")]
                nsl = (txt.count("َ") + txt.count("ِ"))
                while len(spare2) - nsl >= 2 and have_t < want_t:
                    pair = next(((s1, s2) for i3, s1 in enumerate(spare2)
                                 for s2 in spare2[i3 + 1:] if _near(s1, s2)),
                                None)
                    if not pair:
                        break
                    s1, s2 = pair
                    top2 = s1 if (s1["y1"] + s1["y2"]) <= (s2["y1"] + s2["y2"]) \
                        else s2
                    bot3 = s2 if top2 is s1 else s1
                    top2["mark"] = tan
                    bot3["mark"] = tan
                    bot3["mkpart"] = True
                    top2.setdefault("mkmembers", []).append(bot3)
                    spare2.remove(s1)
                    spare2.remove(s2)
                    have_t += 1

    # a stray tanween half that drifted onto the previous word snaps back to
    # the master it hugs on the neighbouring word
    for ri, r in enumerate(owords):
        txt = r["w"]["uthmani"]
        for singles_n, tans_n, chars_s, chars_t in (
                (("damma",), ("dammatan",), "ُ", "ٌࣱ"),
                (("fatha", "kasra"), ("fathatan", "kasratan"),
                 "َِ", "ًࣰٍࣲ")):
            fam = singles_n + tans_n
            els_r = [e for a in r["at"] for e in a["els"]]
            have = sum(1 for e in els_r
                       if e.get("mark") in fam
                       and not e.get("mkpart"))
            want = (sum(txt.count(ch) for ch in chars_s)
                    + sum(txt.count(ch) for ch in chars_t))
            if have <= want:
                continue
            spare3 = [e for e in els_r if e.get("mark") in fam
                      and not e.get("mkpart")]
            for nb in owords:
                if nb is r or have <= want:
                    continue
                nb_els = [e for a in nb["at"] for e in a["els"]]
                nb_txt = nb["w"]["uthmani"]
                nb_want_t = sum(nb_txt.count(ch) for ch in chars_t)
                nb_have_t = sum(1 for e in nb_els if e.get("mark") in tans_n
                                and not e.get("mkpart"))
                for m1 in nb_els:
                    if m1.get("mkpart") or m1.get("mkmembers"):
                        continue
                    if m1.get("mark") in tans_n:
                        tan = m1["mark"]
                    elif m1.get("mark") in singles_n \
                            and nb_want_t > nb_have_t:
                        # the tanween the neighbour's text actually wants
                        tan = next((t for t, ch2 in zip(
                            tans_n, ("ًࣰ", "ٍࣲ") if len(tans_n) == 2
                            else ("ٌࣱ",))
                            if any(c in nb_txt for c in ch2)), None)
                        if tan is None:
                            continue
                    else:
                        continue
                    hit = next((e for e in spare3
                                if abs((e["x1"] + e["x2"]) / 2
                                       - (m1["x1"] + m1["x2"]) / 2) < 8.0
                                and abs((e["y1"] + e["y2"]) / 2
                                        - (m1["y1"] + m1["y2"]) / 2) < 7.0),
                               None)
                    if hit is None:
                        continue
                    for a0 in r["at"]:
                        if hit in a0["els"]:
                            a0["els"].remove(hit)
                    m1["mark"] = tan
                    hit["mark"] = tan
                    hit["mkpart"] = True
                    m1.setdefault("mkmembers", []).append(hit)
                    nb["at"][0]["els"].append(hit)
                    spare3.remove(hit)
                    have -= 1

    # Standalone signs (hizb / rub markers, division stars) belong to no word:
    # eject them and stamp the ayah whose polygon holds them
    _rects_sa = []
    if os.path.exists(polys_path):
        for _pl in json.load(open(polys_path)):
            for _m in _RECT.finditer(_pl.get("polygon", "")):
                _x1, _y1, _x2, _y2 = (float(_m.group(1)), float(_m.group(2)),
                                      float(_m.group(3)), float(_m.group(4)))
                _rects_sa.append((min(_x1, _x2), min(_y1, _y2), max(_x1, _x2),
                                  max(_y1, _y2), _pl["surahNumber"],
                                  _pl["ayahNumber"]))

    def _ayah_at(x, y):
        best = None
        for (rx1, ry1, rx2, ry2, su, ay) in _rects_sa:
            if rx1 <= x <= rx2 and ry1 <= y <= ry2:
                return su, ay
            d = max(rx1 - x, x - rx2, 0) + max(ry1 - y, y - ry2, 0)
            if best is None or d < best[0]:
                best = (d, su, ay)
        return (best[1], best[2]) if best else (None, None)

    ejected = {}
    bars = []
    for w, at in assignment:
        if not w:
            continue
        for a in at:
            for e in list(a["els"]):
                # the sajdah overline is a hairline bar: variable length, all
                # but fixed height. It belongs to the sajdah sign, never to a
                # word — collect it even though it carries no mark name.
                is_bar = (e.get("lab") == "sajdah" and not e.get("mark")
                          and not e.get("mkpart"))
                if is_bar:
                    a["els"].remove(e)
                    bars.append(e)
                    continue
                if e.get("mark") in ("hizb", "sajdah") and not e.get("mkpart"):
                    grp = [e] + [m for m in e.get("mkmembers", []) if m in a["els"]]
                    for x in grp:
                        a["els"].remove(x)
                    su, ay = _ayah_at((e["x1"] + e["x2"]) / 2,
                                      (e["y1"] + e["y2"]) / 2)
                    key = (e["mark"], su, ay)
                    for x in grp:
                        x["standalone"] = (su, ay)
                    ejected.setdefault(key, []).extend(grp)
    # each bar joins the nearest sajdah sign on the page; with none to join it
    # still stands on its own rather than inside a word
    for e in bars:
        cx = (e["x1"] + e["x2"]) / 2
        cy = (e["y1"] + e["y2"]) / 2
        best = None
        for key, grp in ejected.items():
            if key[0] != "sajdah":
                continue
            gx = sum((x["x1"] + x["x2"]) / 2 for x in grp) / len(grp)
            gy = sum((x["y1"] + x["y2"]) / 2 for x in grp) / len(grp)
            d = abs(cx - gx) + abs(cy - gy)
            if best is None or d < best[0]:
                best = (d, key)
        if best is not None:
            key = best[1]
            e["standalone"] = (key[1], key[2])
            ejected[key].append(e)
        else:
            su, ay = _ayah_at(cx, cy)
            e["standalone"] = (su, ay)
            ejected.setdefault(("sajdah", su, ay), []).append(e)
    for (lab, su, ay), grp in ejected.items():
        assignment = assignment + [(None, [{"els": grp,
                                            "sa": (lab, su, ay)}])]



    # A mark that changed hands keeps the name its old word gave it, which its
    # new word may not want at all — a tanween landing on a word whose text has
    # none, or a plain vowel landing where a tanween belongs. The text decides
    # again, by position.
    for _w7, _at7 in assignment:
        if _w7 is None:
            continue
        txt7 = _w7["uthmani"]
        els7 = [e for a in _at7 for e in a["els"]]
        bods7 = [e for e in els7 if e["kind"] == "body"]
        if not bods7:
            continue
        mid7 = (min(e["y1"] for e in bods7) + max(e["y2"] for e in bods7)) / 2
        for tan7, plain7, chars7 in (
                ("fathatan", "fatha", "\u064b\u08f0"),
                ("kasratan", "kasra", "\u064d\u08f2"),
                ("dammatan", "damma", "\u064c\u08f1")):
            want7 = sum(txt7.count(c) for c in chars7)
            got7 = [e for e in els7 if e.get("mark") == tan7
                    and not e.get("mkpart")]
            for e in got7[want7:]:        # a tanween this word never carries
                if tan7 == "dammatan":
                    e["mark"] = "damma"
                else:
                    cy7 = (e["y1"] + e["y2"]) / 2
                    e["mark"] = "kasra" if cy7 > mid7 else "fatha"
                for m7 in e.get("mkmembers", []):
                    m7["mark"] = e["mark"]
            if want7 > len(got7):
                # ... and the tanween it does carry, arriving as a plain vowel
                pool7 = [e for e in els7 if e.get("mark") == plain7
                         and not e.get("mkpart")]
                spare7 = len(pool7) - txt7.count(
                    {"fatha": "\u064e", "kasra": "\u0650",
                     "damma": "\u064f"}[plain7])
                lx7 = min(e["x1"] for e in bods7)
                for e in sorted(pool7,
                                key=lambda x: abs((x["x1"] + x["x2"]) / 2 - lx7)):
                    if spare7 <= 0 or want7 <= len(got7):
                        break
                    e["mark"] = tan7
                    for m7 in e.get("mkmembers", []):
                        m7["mark"] = tan7
                    got7.append(e)
                    spare7 -= 1

    # Re-run the slash renamer: oracle repair moves slashes between words after
    # the first naming pass, so a mark can keep the identity its OLD word gave
    # it (a fatha arriving above a new word still called kasra). Position and
    # the new word's own kasra budget decide again.
    for _w, atoms in assignment:
        if _w is None:
            continue
        els = [e for a in atoms for e in a["els"]]
        sl = [e for e in els if e["kind"] == "mark"
              and e.get("mark") in ("fatha", "kasra")
              and not e.get("mkpart") and not e.get("mkmembers")]
        if not sl:
            continue
        bods = [e for e in els if e["kind"] == "body"] or els
        mid = (min(e["y1"] for e in bods) + max(e["y2"] for e in bods)) / 2
        want_k = _w["uthmani"].count("\u0650")
        # a kasra welded into another mark still spends the word's budget
        want_k -= sum(1 for e in els
                      if e["kind"] == "mark" and e not in sl
                      and not e.get("mkpart")
                      and "kasra" in (e.get("mark") or "").split("+"))
        want_k = max(0, want_k)
        sl.sort(key=lambda e: -(e["y1"] + e["y2"]))     # lowest first
        for e in sl:
            e["mark"] = "fatha"
        k = 0
        for e in sl:
            if k < want_k and (e["y1"] + e["y2"]) / 2 > mid:
                e["mark"] = "kasra"
                k += 1
        if k < want_k:
            for e in sl:
                if k >= want_k:
                    break
                if e["mark"] == "fatha":
                    e["mark"] = "kasra"
                    k += 1
                    break

    # Late two-stroke damma weld: oracle repair can reunite an ornate damma's
    # curl and tail after the early weld ran — join touching stacked pieces.
    for _w, atoms in assignment:
        if _w is None:
            continue
        dm = [e for a in atoms for e in a["els"]
              if e.get("mark") == "damma" and not e.get("mkpart")]
        dm.sort(key=lambda e: e["y1"])
        for i in range(len(dm)):
            for j in range(i + 1, len(dm)):
                top, bot = dm[i], dm[j]
                if top.get("mkpart") or bot.get("mkpart"):
                    continue
                xov = min(top["x2"], bot["x2"]) - max(top["x1"], bot["x1"])
                gap = bot["y1"] - top["y2"]
                if xov > 2.0 and -1.5 < gap < 1.0 \
                        and bot["y2"] - top["y1"] < 9.5:
                    bot["mkpart"] = True
                    top.setdefault("mkmembers", []).append(bot)
        # a dammatan drawn as two side-by-side dammas: weld the two pieces
        dt = [e for a in atoms for e in a["els"]
              if e.get("mark") == "dammatan" and not e.get("mkpart")
              and not e.get("mkmembers")]
        for i in range(len(dt)):
            for j in range(i + 1, len(dt)):
                a2, b2 = dt[i], dt[j]
                if a2.get("mkpart") or b2.get("mkpart"):
                    continue
                dx = abs((a2["x1"] + a2["x2"]) / 2 - (b2["x1"] + b2["x2"]) / 2)
                dy = abs((a2["y1"] + a2["y2"]) / 2 - (b2["y1"] + b2["y2"]) / 2)
                if dx < 5.0 and dy < 5.0:
                    b2["mkpart"] = True
                    a2.setdefault("mkmembers", []).append(b2)

    # The shape table is the strongest identity: repairs and welds sometimes
    # rename a stroke across structural families (a slash pressed into service
    # as a dot or a tanween half). Where the single-shape table disagrees
    # across families, it wins; fatha/kasra stay position-resolved.
    _tbl_fix = {k: (v["label"] if isinstance(v, dict) else v)
                for k, v in shape_labels().items()}
    from markshape import signature as _sg2, sig_key as _sk2, \
        element_points as _ep2
    from split_line_elements import contour_polylines as _cp2
    from svg_lines import apply as _xf2

    _cp_cache = {}

    def _late_sig(e):
        if e.get("sig"):
            return e["sig"]
        try:
            pi = e["path"]
            if pi not in _cp_cache:
                _cp_cache[pi] = _cp2(page.paths[pi]["d"])
            polys2 = _cp_cache[pi]
            pts = _ep2([[_xf2(page.paths[pi]["M"], x, y)
                         for x, y in polys2[c["sp"]["index"]]]
                        for c in e["contours"]])
            e["sig"] = _sk2(_sg2(pts))
        except Exception:
            return None
        return e["sig"]

    for _w2, _at2 in assignment:
        for _a2 in _at2:
            bods2 = [e for e in _a2["els"] if e["kind"] == "body"]
            for _e2 in _a2["els"]:
                if _e2.get("mkpart") or _e2.get("fused") or _e2.get("mkmembers"):
                    continue
                t = _tbl_fix.get(_late_sig(_e2))
                cur = _e2.get("mark")
                if not t or not cur or t == cur:
                    continue
                fix = None
                if cur == "dot" and t in ("fatha", "kasra")                         and (_e2["x2"] - _e2["x1"]) >= 4.5:
                    fix = "slash"
                elif cur in ("damma", "dammatan") and t in ("fatha", "kasra"):
                    fix = "slash"
                elif cur in ("fatha", "kasra", "damma", "dammatan")                         and t == "shadda":
                    fix = "shadda"
                elif cur == "small-waw" and t == "damma":
                    _e2["mark"] = "damma"
                if fix == "slash":
                    ref = bods2[0] if bods2 else None
                    below = ref is not None and                         (_e2["y1"] + _e2["y2"]) / 2 > (ref["y1"] + ref["y2"]) / 2
                    _e2["mark"] = "kasra" if below else "fatha"
                elif fix == "shadda":
                    _e2["mark"] = "shadda"

    # kind follows the final identity: a piece that ended up carrying a mark
    # name is a mark whatever the size heuristic first said, and vice versa
    _MARKFAM = {"fatha", "kasra", "damma", "fathatan", "kasratan", "dammatan",
                "sukun", "shadda", "hamza", "maddah", "small-alef", "wasla",
                "dot", "two-dots", "three-dots", "pause", "small-circle",
                "small-ya", "small-waw", "small-meem", "small-noon"}
    for _w2, _at2 in assignment:
        for _a2 in _at2:
            for _e2 in _a2["els"]:
                mk = _e2.get("mark")
                if mk and _e2["kind"] == "body" \
                        and all(p in _MARKFAM for p in mk.split("+")):
                    _e2["kind"] = "mark"

    # Reviewer overrides have the last word. A human looked at this page and
    # said which word owns this piece of ink; no inference outranks that. They
    # are keyed by geometry, not by element id, so they survive pipeline
    # changes — and each one is also a standing regression test.
    _ovr_path = os.path.join(ROOT, ".cache", "review", "overrides.json")
    if os.path.exists(_ovr_path):
        try:
            _ovr = json.load(open(_ovr_path)).get(str(page_no), {})
        except Exception:
            _ovr = {}
        if _ovr:
            _by_word = {}
            for _w9, _at9 in assignment:
                if _w9:
                    _by_word["%d:%d:%d" % (_w9["surah"], _w9["ayah"],
                                           _w9["pos"])] = (_w9, _at9)
            for _w9, _at9 in assignment:
                for _a9 in list(_at9):
                    for _e9 in list(_a9["els"]):
                        _k9 = "%.1f,%.1f,%.1f,%.1f" % (_e9["x1"], _e9["y1"],
                                                       _e9["x2"], _e9["y2"])
                        _tgt = _ovr.get(_k9)
                        if not _tgt or _tgt not in _by_word:
                            continue
                        _dw, _dat = _by_word[_tgt]
                        if _dw is _w9:
                            continue          # already where it belongs
                        _a9["els"].remove(_e9)
                        for _m9 in _e9.get("mkmembers", []):
                            if _m9 in _a9["els"]:
                                _a9["els"].remove(_m9)
                        _dat[0]["els"].append(_e9)
                        _dat[0]["els"].extend(_e9.get("mkmembers", []))

    out_svg = rewrite(page, assignment)
    polys_all = json.load(open(polys_path)) if os.path.exists(polys_path) else []
    out_svg = tag_ayah_markers(out_svg, polys_all)
    return page, out_svg, report, coverage


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("edition")
    ap.add_argument("page", type=int)
    ap.add_argument("--words-cache", default=os.path.join(ROOT, ".cache", "words"))
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args(argv)

    page, out_svg, report, (labeled, total_marks) = assign_page(
        args.edition, args.page, args.words_cache)

    out_dir = args.out_dir or os.path.join(ROOT, ".cache", "words-svg",
                                           args.edition.replace("/", "-"))
    os.makedirs(out_dir, exist_ok=True)
    svg_path = os.path.join(out_dir, "%03d.svg" % args.page)
    with open(svg_path, "w", encoding="utf-8") as fh:
        fh.write(out_svg)
    rep_path = os.path.join(out_dir, "%03d.report.json" % args.page)
    json.dump(report, open(rep_path, "w"), indent=1)

    need = [r for r in report if r["review"]]
    print("wrote %s — %d lines, %d flagged for review; marks shape-labeled %d/%d"
          % (svg_path, len(report), len(need), labeled, total_marks))
    for r in need:
        print("  line %2d: words=%d clusters=%d deviation=%s flags=%s"
              % (r["line"], r["words"], r["clusters"], r["deviation"], r["flags"]))


if __name__ == "__main__":
    main()
