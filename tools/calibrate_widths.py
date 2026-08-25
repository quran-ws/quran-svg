#!/usr/bin/env python3
"""Learn each letter's drawn width from the mushaf itself, using the expected text.

Every single-piece ligature we have aligned carries its letter string and a measured
span; span ≈ Σ width(letter, position) is one linear equation. Thousands of ligatures
over-determine a few hundred (letter × initial/medial/final/isolated) unknowns, so
least squares recovers the script's true metrics — replacing the hand-made WIDTH table
with values measured from the calligraphy. The solution feeds word clustering, ligature
alignment, and the letter-boundary priors.

    tools/calibrate_widths.py hafs/kfqc --pages 1-40
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from page import Page
from assign_words import (page_words, page_elements, classify, cluster_line,
                          segment_word, align_segs_atoms)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def positions(text):
    """(char, position) per letter: isolated / initial / medial / final in the piece."""
    n = len(text)
    out = []
    for i, ch in enumerate(text):
        pos = ("isolated" if n == 1 else
               "initial" if i == 0 else
               "final" if i == n - 1 else "medial")
        out.append((ch, pos))
    return out


def samples(edition, names):
    for name in names:
        page_no = int(re.match(r"\d+", name).group(0))
        page = Page(os.path.join(ROOT, "mushafs", edition, "svg", name))
        if page.content is None:
            continue
        lp = os.path.join(ROOT, "mushafs", edition, "lines",
                          name.replace(".svg", ".json"))
        lines_info = json.load(open(lp)) if os.path.exists(lp) else []
        try:
            words = page_words(page_no, os.path.join(ROOT, ".cache", "words"))
        except Exception:
            continue
        els = page_elements(page)
        classify(els, lines_info)
        for ln in sorted({e["line"] for e in els if e["line"]}):
            ws = words.get(ln, [])
            l_els = [e for e in els if e["line"] == ln]
            clusters, _ = cluster_line(l_els, ws)
            for w, cl in zip(ws, clusters):
                segs = segment_word(w["uthmani"])
                groups, cost = align_segs_atoms(cl, segs)
                if cost == float("inf") or cost > 0.5:
                    continue                    # calibrate only on confident alignments
                for g_atoms, g_segs in groups:
                    if len(g_atoms) != 1 or len(g_segs) != 1:
                        continue                # one drawn piece <-> one expected segment
                    text = g_segs[0]["text"]
                    if not text:
                        continue
                    a = g_atoms[0]
                    yield text, a["x2"] - a["x1"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("edition")
    ap.add_argument("--pages", default="1-40")
    ap.add_argument("-o", "--out", default=os.path.join(ROOT, ".cache",
                                                        "letter-widths.json"))
    args = ap.parse_args(argv)

    a, b = (args.pages.split("-") + [args.pages])[:2]
    names = ["%03d.svg" % p for p in range(int(a), int(b) + 1)]
    svg_dir = os.path.join(ROOT, "mushafs", args.edition, "svg")
    names = [n for n in names if os.path.exists(os.path.join(svg_dir, n))]

    import numpy as np
    rows, spans = [], []
    keys, index = [], {}
    for text, span in samples(args.edition, names):
        eq = defaultdict(int)
        for key in positions(text):
            if key not in index:
                index[key] = len(keys)
                keys.append(key)
            eq[index[key]] += 1
        rows.append(eq)
        spans.append(span)

    A = np.zeros((len(rows), len(keys)))
    for r, eq in enumerate(rows):
        for c, k in eq.items():
            A[r, c] = k
    y = np.array(spans)
    # ridge for rarely-seen forms
    lam = 0.5
    AtA = A.T @ A + lam * np.eye(len(keys))
    w = np.linalg.solve(AtA, A.T @ y)
    pred = A @ w
    resid = np.abs(pred - y)
    counts = A.sum(axis=0)

    out = {}
    for (ch, pos), wi, c in zip(keys, w, counts):
        out.setdefault(ch, {})[pos] = {"width": round(float(wi), 2),
                                       "samples": int(c)}
    json.dump(out, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print("%d ligature samples, %d (letter,position) unknowns" % (len(rows), len(keys)))
    print("median |residual| = %.2f units, 90th pct = %.2f, mean span = %.1f"
          % (float(np.median(resid)), float(np.percentile(resid, 90)),
             float(np.mean(y))))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
