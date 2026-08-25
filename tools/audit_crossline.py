#!/usr/bin/env python3
"""Ink held by a word on one line but drawn in another line's territory.

The interval audit compares words along a line and the mark audit compares
counts against the text; neither can see a word holding ink that belongs to
the line above or below it. A reviewer can — "this ه is stolen from the word
below", "it has a ه at the top stolen from the word above but it is not
flagged" — so this looks for exactly that.

A mark legitimately rides above its own letters and may cross a band edge, so
the test is not "which band is it in". It is: does this ink sit closer to a
word on the OTHER line than to the word holding it, and does that other word's
own ink stand directly over or under it?

    python3 tools/audit_crossline.py [first] [last]
"""
import importlib.util, io, contextlib, json, os, sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
PIPE = os.environ.get("QSVG_PIPE", os.path.join(ROOT, "tools", "assign_words.py"))
spec = importlib.util.spec_from_file_location("assign_words", PIPE)
aw = importlib.util.module_from_spec(spec)
sys.modules["assign_words"] = aw
spec.loader.exec_module(aw)
_cap = {}
_orig = aw.rewrite


def _spy(page, a):
    _cap["a"] = a
    return _orig(page, a)


aw.rewrite = _spy


def scan(pg):
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            aw.assign_page("hafs/kfqc", pg, os.path.join(ROOT, ".cache", "words"))
    except Exception as e:
        return pg, []
    words = []
    for w, at in _cap["a"]:
        if not w:
            continue
        els = [e for a in at for e in a["els"]]
        bods = [e for e in els if e["kind"] == "body"]
        if not bods:
            continue
        lns = [e.get("line") for e in bods if e.get("line")]
        if not lns:
            continue
        words.append({
            "w": w, "els": els, "bods": bods,
            "ln": max(set(lns), key=lns.count),
            "x1": min(e["x1"] for e in bods), "x2": max(e["x2"] for e in bods),
            "y1": min(e["y1"] for e in bods), "y2": max(e["y2"] for e in bods),
        })
    byline = defaultdict(list)
    for r in words:
        byline[r["ln"]].append(r)

    # What the holder's spelling actually asks for. A waqf sign is drawn high
    # above its own word by design, so it lands nearer the line above and
    # looks stolen when it is not; the same goes for any mark the word really
    # owns. Only ink the holder has no room for is evidence of theft.
    TXT = {"pause": "\u06d6\u06d7\u06d8\u06d9\u06da\u06db\u06dc",
           "fatha": "\u064e", "kasra": "\u0650", "damma": "\u064f",
           "sukun": "\u0652\u06e1", "shadda": "\u0651",
           "maddah": "\u0653\u06e4", "small-alef": "\u0670",
           "wasla": "\u0671", "fathatan": "\u064b\u08f0",
           "kasratan": "\u064d\u08f2", "dammatan": "\u064c\u08f1"}

    def surplus(r, fam):
        if fam not in TXT:
            return True             # dots and letter ink: no character to count
        txt = r["w"]["uthmani"]
        have = sum(1 for e in r["els"] if e.get("mark") == fam
                   and not e.get("mkpart"))
        return have > sum(txt.count(c) for c in TXT[fam])

    out = []
    for r in words:
        for e in r["els"]:
            if e.get("mkpart") or e.get("standalone"):
                continue
            if e["kind"] == "mark" and not surplus(r, e.get("mark")):
                continue
            cx = (e["x1"] + e["x2"]) / 2
            cy = (e["y1"] + e["y2"]) / 2
            # Measured against the word's OTHER letters, never against itself.
            # A stolen letter joins the word's outline the moment it is taken,
            # so a word always looks close to ink it should never have held.
            rest = [b for b in r["bods"] if b is not e]
            if not rest:
                continue
            ry1 = min(b["y1"] for b in rest)
            ry2 = max(b["y2"] for b in rest)
            own = max(ry1 - cy, cy - ry2, 0.0)
            best = None
            for dl in (-1, 1):
                for v in byline.get(r["ln"] + dl, ()):
                    if v is r:
                        continue
                    # Not "must stand over it": the word robbed of a letter has
                    # a span that stops short of the very ink it is missing, so
                    # demanding containment can never find the victim. Allow
                    # the reach of about one letter beside its remaining ink.
                    xd = max(v["x1"] - e["x2"], e["x1"] - v["x2"], 0.0)
                    if xd > 8.0:
                        continue
                    d = max(v["y1"] - cy, cy - v["y2"], 0.0)
                    if best is None or (d + xd) < (best[0] + best[2]):
                        best = (d, v, xd)
            if best is None:
                continue
            d, v, xd = best
            # clearly nearer the other line's word, and far from its own
            if d + 3.0 < own and own > 6.0:
                out.append({"page": pg, "line": r["ln"],
                            "holder": r["w"]["uthmani"],
                            "key": "%d:%d:%d" % (r["w"]["surah"], r["w"]["ayah"],
                                                 r["w"]["pos"]),
                            "kind": e["kind"], "mark": e.get("mark"),
                            "other_line": v["ln"], "other": v["w"]["uthmani"],
                            "gap_own": round(own, 1), "gap_other": round(d, 1),
                            "x_gap": round(xd, 1)})
    return pg, out


if __name__ == "__main__":
    a = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    b = int(sys.argv[2]) if len(sys.argv) > 2 else 604
    from multiprocessing import Pool
    allr = []
    with Pool(2, maxtasksperchild=6) as pool:
        for pg, rows in pool.imap_unordered(scan, range(a, b + 1)):
            allr += rows
    S = os.path.dirname(os.path.abspath(__file__))
    json.dump(allr, open(os.path.join(ROOT, "docs", "defects",
                                      "crossline.json"), "w"),
              ensure_ascii=False, indent=1)
    print("ink drawn in another line's territory: %d over %d pages"
          % (len(allr), len({r["page"] for r in allr})))
    print("by kind:", dict(Counter(r["kind"] for r in allr)))
    print("by mark:", dict(Counter(r["mark"] or "-" for r in allr).most_common(8)))
    print("\n%-6s %-16s %-11s %s" % ("page", "holder", "ink", "really belongs with"))
    for r in allr[:14]:
        print("p%-5d %-16s %-11s %s (line %d, %.1f vs %.1f away)"
              % (r["page"], r["holder"], r["mark"] or r["kind"], r["other"],
                 r["other_line"], r["gap_other"], r["gap_own"]))
