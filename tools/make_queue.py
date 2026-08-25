#!/usr/bin/env python3
"""Build the defect queue every lane works from.

One row per open defect, routed to the lane whose evidence can actually settle
it, and ranked by how many defects one decision would close. Reads the latest
full sweep (audit_marks + audit_intervals per page) and writes
docs/defects/queue.json plus a short summary.

    python3 tools/make_queue.py <sweep-dir> [-o docs/defects/queue.json]

Lanes
  auto    a mechanical invariant decides it: side rules, text budgets, the
          joining-rule piece count, reading order, band membership.
  label   a shape is named wrong. One human decision per SHAPE fixes every
          occurrence mushaf-wide, through .cache/marks/labels.json.
  place   this ink, on this page, belongs to that word. Nothing general to
          learn; one human decision per occurrence, via overrides.json.
  judge   the audit and the artwork disagree and neither is obviously right.
"""
import argparse, json, os, sys
from collections import Counter, defaultdict

# Which family, in which direction, is settled by which kind of evidence.
# A count that is SHORT of the text usually means ink we failed to name; a
# count that is OVER it usually means ink we named twice or stole.
LANE = {
    "pause": "label",        # waqf glyphs are ligatures of real letters
    "damma": "label",        # the ornate damma and a dot pair look alike
    "dots": "label",
    "small-circle": "label",
    "small-noon": "label",
    "ligatures": "auto",     # surplus pieces = ink stolen from a neighbour
    "fatha": "auto",         # side rule + budget
    "kasra": "auto",
    "fathatan": "auto",
    "kasratan": "auto",
    "sukun": "auto",
    "shadda": "auto",
    "maddah": "auto",
    "wasla": "auto",         # a wasla only ever sits on an alef
    "small-alef": "auto",
    "small-waw": "auto",     # the pronoun suffix trails its own word
    "small-ya": "auto",
    "hamza": "auto",
    "dammatan": "auto",
    "rtl-order": "auto",
}
IV_LANE = {"BODY-STEAL": "auto", "BODY-GRAB": "auto",
           "NEIGHBOUR-BAD": "auto", "MARK-STEAL": "auto"}


def contested_words(sig_flags, labels):
    """Words whose ink actually contains a shape nobody has settled.

    Routing by family alone sent every pause and dot flag to the reviewer, but
    a family is not evidence: what makes a defect answerable by naming a SHAPE
    is that one of the word's own outlines is unnamed or disputed. Measured
    against the real data, that is a few dozen words, not a few hundred.
    """
    if not sig_flags or not os.path.exists(sig_flags):
        return None
    derived = ({"fatha", "kasra", "fathatan", "kasratan"}, {"damma", "dammatan"})
    out = set()
    for r in json.load(open(sig_flags)):
        if r.get("kind") != "mark":
            continue
        known = (labels.get(r["sig"]) or {}).get("label")
        mark = r.get("mark")
        if known is not None:
            if not mark or mark == known:
                continue
            if any(known in f and mark in f for f in derived):
                continue
            if "+" in known and mark in known.split("+"):
                continue
        out.add((r["page"], r["key"]))
    return out


def build(sweep, contested=None):
    rows = []
    for f in sorted(os.listdir(sweep)):
        if not f.endswith(".json"):
            continue
        r = json.load(open(os.path.join(sweep, f)))
        pg = r["page"]
        for x in r.get("marks", []):
            fams = sorted({b[0] for b in x["bad"]})
            lanes = {LANE.get(fm, "judge") for fm in fams}
            lane = "label" if lanes == {"label"} else (
                "auto" if lanes <= {"auto"} else "judge")
            # a shape question only when one of THIS word's outlines is open
            if lane == "label" and contested is not None \
                    and (pg, x["key"]) not in contested:
                lane = "auto"
            rows.append({"page": pg, "key": x["key"], "word": x["word"],
                         "source": "marks", "families": fams,
                         "detail": x["bad"], "lane": lane, "status": "open"})
        for y in r.get("intervals", []):
            rows.append({"page": pg, "key": y.get("key"), "word": y.get("holder"),
                         "source": "interval", "families": [y.get("kind")],
                         "detail": y, "lane": IV_LANE.get(y.get("kind"), "judge"),
                         "status": "open"})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sweep")
    ap.add_argument("-o", default="docs/defects/queue.json")
    ap.add_argument("--sig-flags", help="scan output, to route the label lane "
                                        "by actual open shapes")
    a = ap.parse_args()
    labels_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), ".cache", "marks", "labels.json")
    labels = json.load(open(labels_path)) if os.path.exists(labels_path) else {}
    rows = build(a.sweep, contested_words(a.sig_flags, labels))
    os.makedirs(os.path.dirname(a.o), exist_ok=True)
    json.dump(rows, open(a.o, "w"), ensure_ascii=False, indent=1)
    lane = Counter(r["lane"] for r in rows)
    fam = Counter(f for r in rows for f in r["families"])
    pages = defaultdict(set)
    for r in rows:
        pages[r["lane"]].add(r["page"])
    print("queue: %d open defects -> %s" % (len(rows), a.o))
    print("\n%-8s %-8s %-8s %s" % ("lane", "defects", "pages", "who"))
    who = {"auto": "AI, no input needed", "label": "you: one call per SHAPE",
           "place": "you: one call per occurrence", "judge": "you: adjudicate"}
    for ln in ("auto", "label", "judge", "place"):
        if lane[ln]:
            print("%-8s %-8d %-8d %s" % (ln, lane[ln], len(pages[ln]), who[ln]))
    print("\ntop families:", dict(fam.most_common(10)))


if __name__ == "__main__":
    main()
