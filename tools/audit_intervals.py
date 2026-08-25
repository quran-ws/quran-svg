#!/usr/bin/env python3
"""RTL interval audit.

Scan each line right-to-left. Each word's BODY ink gives an interval; the part
of it no other word touches is that word's *exclusive core*. A mark sitting in
another word's exclusive core is misplaced ink -- and unlike a mark count, this
stays true when two words swap marks, so it sees chain shifts and cycles.

A flag has two possible causes, and they need opposite fixes:
  BODY-STEAL  the holder lost a letter piece, so its interval is too short and
              its own marks fall inside the thief. Re-partition; do NOT move
              the mark -- that would strip the word of a vowel it really owns.
  MARK-STEAL  both words have healthy ink and the mark alone is in the wrong
              word. Safe to move.
Separating them needs the width prior and the joining-rule piece count.
"""
import importlib.util, json, os, sys
from collections import Counter

ROOT = "/Users/abdullah/Documents/Github/quran-svg"
sys.path.insert(0, ROOT + "/tools")
spec = importlib.util.spec_from_file_location("assign_words", ROOT + "/tools/assign_words.py")
aw = importlib.util.module_from_spec(spec); sys.modules["assign_words"] = aw
spec.loader.exec_module(aw)
cap = {}; _orig = aw.rewrite
def _spy(page, a): cap["a"] = a; return _orig(page, a)
aw.rewrite = _spy
QW = json.load(open(ROOT + "/.cache/qcf_widths.json"))


def eff_bodies(els):
    bods = [e for e in els if e["kind"] == "body"]
    out = []
    for b in bods:
        wb = b["x2"] - b["x1"]
        if not any(o is not b
                   and min(o["x2"], b["x2"]) - max(o["x1"], b["x1"]) >= 0.6 * wb
                   and (o["x2"] - o["x1"]) > wb for o in bods):
            out.append(b)
    return out


def scan(pg):
    aw.assign_page("hafs/kfqc", pg, ROOT + "/.cache/words")
    lines = {}
    for w, at in cap["a"]:
        if not w:
            continue
        els = [e for a in at for e in a["els"]]
        if els:
            lines.setdefault(els[0].get("line"), []).append((w, els))

    flags = []
    for ln, sub in lines.items():
        iv, meta = {}, {}
        for w, els in sub:
            b = [e for e in els if e["kind"] == "body"]
            if not b:
                continue
            iv[id(w)] = (min(e["x1"] for e in b), max(e["x2"] for e in b), w)
            meta[id(w)] = (els, eff_bodies(els))
        # width prior: share out the line's actual ink by the reference metrics
        tot_a = sum(t[1] - t[0] for t in iv.values())
        tot_q = sum(QW.get("%d:%d:%d" % (t[2]["surah"], t[2]["ayah"], t[2]["pos"]), 0)
                    for t in iv.values())
        def ratio(w):
            t = iv[id(w)]
            qw = QW.get("%d:%d:%d" % (w["surah"], w["ayah"], w["pos"]), 0)
            if not qw or not tot_q:
                return None
            exp = qw / tot_q * tot_a
            return (t[1] - t[0]) / exp if exp else None

        for w, els in sub:
            if id(w) not in iv:
                continue
            for e in els:
                if e["kind"] != "mark" or e.get("mkpart") or e.get("standalone"):
                    continue
                # A mark is wide enough that its centre can tip past its own
                # word's edge while the mark still stands squarely on that
                # word's last letter -- the kasra under a word-initial lam
                # does exactly this. Overlap, not the centre, is the test:
                # ink that touches its holder at all is not foreign to it.
                cx = (e["x1"] + e["x2"]) / 2
                def ov(t):
                    return min(e["x2"], t[1]) - max(e["x1"], t[0])
                mine = iv[id(w)]
                if ov(mine) > 0.5:
                    continue                  # still touching its own word
                # The small waw of the pronoun suffix -hu and the small ya of
                # -hi are written clear of the word's own ink, past its left
                # edge, so they sit over whatever follows. When the text says
                # the word has one, its position is the script's doing and not
                # a defect -- and moving it would strip the suffix.
                if e.get("mark") == "small-waw" and "\u06e5" in w["uthmani"]:
                    continue
                if e.get("mark") == "small-ya" and "\u06e6" in w["uthmani"]:
                    continue
                owners = [t for t in iv.values() if ov(t) > 0.5]
                if len(owners) != 1 or owners[0][2] is w:
                    continue
                other = owners[0][2]
                rA, rB = ratio(w), ratio(other)
                nsegA = max(1, len(aw.segment_word(w["uthmani"])))
                defA = nsegA - len(meta[id(w)][1])
                # Ink can bleed across a word boundary without a whole piece
                # changing hands, so the width prior -- not the piece count --
                # is what says the body partition is wrong. A piece deficit
                # only sharpens it.
                if rA is not None and rA < 0.75:
                    kind = "BODY-STEAL"          # holder starved: it lost ink
                elif rA is not None and rA > 1.35:
                    kind = "BODY-GRAB"           # holder swollen: it took ink
                elif rB is not None and not (0.7 <= rB <= 1.35):
                    kind = "NEIGHBOUR-BAD"       # the other word's ink is off
                else:
                    kind = "MARK-STEAL"          # both sound: the mark alone moved
                flags.append({"page": pg, "line": ln, "kind": kind,
                              "holder": w["uthmani"], "inside": other["uthmani"],
                              "key": "%d:%d:%d" % (w["surah"], w["ayah"], w["pos"]),
                              "mark": e.get("mark"), "x": round(cx, 1),
                              "rA": None if rA is None else round(rA, 2),
                              "rB": None if rB is None else round(rB, 2),
                              "pieces": "%d/%d" % (len(meta[id(w)][1]), nsegA),
                              "deficit": defA})
    return flags


if __name__ == "__main__":
    pages = [int(x) for x in sys.argv[1:]] or [1, 3, 20, 341, 350, 355, 366, 418]
    allf, per = [], Counter()
    for pg in pages:
        f = scan(pg)
        allf += f
        per[pg] = len(f)
    kinds = Counter(x["kind"] for x in allf)
    print("flags %d over %d pages   %s" % (len(allf), len(pages), dict(kinds)))
    print("per page:", {p: n for p, n in per.items() if n})
    for k in ("BODY-STEAL", "BODY-GRAB", "NEIGHBOUR-BAD", "MARK-STEAL"):
        rows = [x for x in allf if x["kind"] == k]
        if not rows:
            continue
        print("\n== %s (%d)" % (k, len(rows)))
        for x in rows[:14]:
            print("  p%-4d L%-3s %-14s holds %-11s inside %-14s  w %s/%s  pieces %s"
                  % (x["page"], x["line"], x["holder"], x["mark"], x["inside"],
                     x["rA"], x["rB"], x["pieces"]))
    json.dump(allf, open(os.path.dirname(os.path.abspath(__file__)) + "/interval_flags.json", "w"),
              ensure_ascii=False, indent=1)
