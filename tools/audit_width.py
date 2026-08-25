#!/usr/bin/env python3
"""Words whose ink is the wrong SIZE for the word.

The mark audits count diacritics and the interval audit compares neighbours;
none of them notices a word that has quietly lost a letter, because losing one
changes no count. On p350 وٱلزانية fell from 44u to 25u against 41u expected —
a visibly broken word, with the flag total unchanged.

Each line's ink is shared out among its words by the reference metrics, so a
word's expected width is its share of what is actually drawn on that line. A
word far from its share is holding too little ink or too much.

    python3 tools/audit_width.py [first] [last]

Reported as a ratio: 0.6 means the word has 60% of the ink it should.
"""
import importlib.util, io, contextlib, json, math, os, sys
from collections import Counter

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
LOW, HIGH = 0.70, 1.45      # outside this, the word is the wrong size
# ... but a ratio alone is unfair to short words. The same six units of error
# reads as 1.60 on a ten-unit word and 1.13 on a forty-five-unit one, so a
# ratio threshold flags short words far more readily and makes any page of
# short words look broken. Ask for a real absolute error as well.
MIN_OFF = 4.0


def scan(pg):
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            aw.assign_page("hafs/kfqc", pg, os.path.join(ROOT, ".cache", "words"))
    except Exception:
        return pg, []
    q = aw.qcf_widths()
    lines = {}
    for w, at in _cap["a"]:
        if not w:
            continue
        b = [e for a in at for e in a["els"] if e["kind"] == "body"]
        if not b:
            continue
        ln = b[0].get("line")
        lines.setdefault(ln, []).append(
            (w, min(e["x1"] for e in b), max(e["x2"] for e in b), len(b)))
    out = []
    for ln, sub in lines.items():
        ta = sum(x2 - x1 for _, x1, x2, _ in sub)
        tq = sum(q.get("%d:%d:%d" % (w["surah"], w["ayah"], w["pos"]), 0)
                 for w, _, _, _ in sub)
        if not tq or not ta:
            continue
        for w, x1, x2, nb in sub:
            qw = q.get("%d:%d:%d" % (w["surah"], w["ayah"], w["pos"]), 0)
            if not qw:
                continue
            exp = qw / tq * ta
            if exp <= 0:
                continue
            r = (x2 - x1) / exp
            if (r < LOW or r > HIGH) and abs((x2 - x1) - exp) >= MIN_OFF:
                out.append({"page": pg, "line": ln,
                            "key": "%d:%d:%d" % (w["surah"], w["ayah"], w["pos"]),
                            "word": w["uthmani"], "ratio": round(r, 2),
                            "width": round(x2 - x1, 1), "want": round(exp, 1),
                            "bodies": nb})
    return pg, out


if __name__ == "__main__":
    a = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    b = int(sys.argv[2]) if len(sys.argv) > 2 else 604
    from multiprocessing import Pool
    allr = []
    with Pool(2, maxtasksperchild=6) as pool:
        for pg, rows in pool.imap_unordered(scan, range(a, b + 1)):
            allr += rows
    out = os.path.join(ROOT, "docs", "defects", "width.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(allr, open(out, "w"), ensure_ascii=False, indent=1)
    short = [r for r in allr if r["ratio"] < LOW]
    wide = [r for r in allr if r["ratio"] > HIGH]
    print("words the wrong size: %d over %d pages  (too small %d, too big %d)"
          % (len(allr), len({r["page"] for r in allr}), len(short), len(wide)))
    worst = sorted(allr, key=lambda r: abs(math.log(max(r["ratio"], 1e-3))),
                   reverse=True)[:12]
    print("\n%-6s %-16s %6s %8s %8s %s" % ("page", "word", "ratio", "width",
                                           "wanted", "bodies"))
    for r in worst:
        print("p%-5d %-16s %6.2f %8.1f %8.1f %d"
              % (r["page"], r["word"], r["ratio"], r["width"], r["want"],
                 r["bodies"]))
