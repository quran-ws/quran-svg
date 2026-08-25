#!/usr/bin/env python3
"""Fold reviewer shape decisions into the global label table.

A decision names an outline, not an occurrence, so it applies everywhere that
outline is drawn. Confirmed entries are written with auto=false, which marks
them as human and protects them from being re-derived by the automatic seeding
in cluster_marks.py.

    python3 tools/apply_labels.py decisions.json [--dry-run]

The previous table is copied beside itself before anything is written, so a
decision that turns out wrong can be taken back.
"""
import argparse, json, os, shutil, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLE = os.path.join(ROOT, ".cache", "marks", "labels.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("decisions")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="allow a composite label to be replaced by a single name")
    a = ap.parse_args()

    raw = json.load(open(a.decisions, encoding="utf-8"))
    if not isinstance(raw, dict) or not raw:
        sys.exit("decisions.json must be a non-empty {signature: ...} object")
    # Two shapes of entry, because a reviewer may have something to say about a
    # shape without being able to name it: a bare label, or an object carrying
    # a label, a note, or both. A note with no label is kept, not discarded.
    dec, notes = {}, {}
    for sg, v in raw.items():
        if isinstance(v, dict):
            if v.get("label"):
                dec[sg] = v["label"]
            if v.get("note"):
                notes[sg] = v["note"]
        elif v:
            dec[sg] = v
    table = json.load(open(TABLE, encoding="utf-8"))

    new = changed = same = refused = 0
    for sg, lab in dec.items():
        cur = table.get(sg)
        was = (cur or {}).get("label") or ""
        # A composite label says ONE outline carries TWO marks, and the audit
        # splits it on "+" to count both. Replacing it with a single name
        # deletes the other mark everywhere that outline is drawn — 763 hamza
        # flags appeared the first time this went through unchecked.
        if "+" in was and "+" not in lab and not a.force:
            print("  REFUSED %s  %s -> %s  (composite; pass --force to override)"
                  % (sg[:10], was, lab))
            refused += 1
            continue
        if cur is None:
            new += 1
        elif cur.get("label") != lab:
            changed += 1
            print("  %s  %s -> %s%s" % (sg[:10], cur.get("label"), lab,
                                        "  (was human)" if not cur.get("auto", False) else ""))
        else:
            same += 1
        if not a.dry_run:
            table[sg] = {"label": lab, "auto": False}

    print("%d decisions: %d new, %d changed, %d already agreed, %d refused"
          % (len(dec), new, changed, same, refused))
    if notes:
        npath = os.path.join(ROOT, "docs", "defects", "shape_notes.json")
        keep = json.load(open(npath, encoding="utf-8")) if os.path.exists(npath) else {}
        keep.update(notes)
        if not a.dry_run:
            os.makedirs(os.path.dirname(npath), exist_ok=True)
            json.dump(keep, open(npath, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        print("%d note(s) kept in docs/defects/shape_notes.json" % len(notes))
    if a.dry_run:
        print("dry run - nothing written")
        return
    bak = TABLE + "." + time.strftime("%Y%m%d-%H%M%S") + ".bak"
    shutil.copy2(TABLE, bak)
    json.dump(table, open(TABLE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=0)
    print("written %s   (previous table kept at %s)" % (TABLE, os.path.basename(bak)))
    print("next: clear .cache/words-svg/hafs-kfqc, then re-run bench and the sweep")


if __name__ == "__main__":
    main()
