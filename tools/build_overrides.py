#!/usr/bin/env python3
"""Turn reviewer 'move-element' edits into durable per-element overrides.

A label edit generalises by shape signature and belongs in the global table.
A MOVE is different: it says "on this page, this piece of ink belongs to that
word" — a fact about one place, which no general rule should have to infer.
This resolves each edit's element id to the element's geometry (stable, since
the source art never changes) and writes .cache/review/overrides.json, which
assign_page applies as the last word.

Usage: python3 tools/build_overrides.py [--dry-run]
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
REVIEW = os.path.join(ROOT, ".cache", "review")
OUT = os.path.join(REVIEW, "overrides.json")


def read_jsonl(path):
    out = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main():
    dry = "--dry-run" in sys.argv
    decisions = {d["id"]: d.get("state") or d.get("status")
                 for d in read_jsonl(os.path.join(REVIEW, "decisions.jsonl"))}
    moves = {}
    for e in read_jsonl(os.path.join(REVIEW, "edits.jsonl")):
        if e.get("kind") != "move-element":
            continue
        if decisions.get(e["id"]) == "rejected":
            continue
        moves.setdefault(e["page"], {})[e["payload"]["eid"]] = (
            e["payload"]["to"], e["payload"].get("box"))
    if not moves:
        print("no move-element edits found")
        return

    import assign_words as aw
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for page, per_eid in sorted(moves.items()):
        if all(rec[1] for rec in per_eid.values()):
            geom = {}
            page_out = out.setdefault(str(page), {})
            for e_id, (target, box) in per_eid.items():
                page_out[box] = target
                print("p%s %s -> %s  at %s" % (page, e_id, target, box))
            continue
        cap = {}
        orig = aw.rewrite
        def spy(pg, assignment, _c=cap):
            _c["a"] = assignment
            return orig(pg, assignment)
        aw.rewrite = spy
        try:
            aw.assign_page("hafs/kfqc", page, os.path.join(ROOT, ".cache", "words"))
        finally:
            aw.rewrite = orig
        # eids are handed out in emission order, word by word
        eid = 0
        geom = {}
        for w, atoms in cap.get("a", []):
            for a in atoms:
                for el in a["els"]:
                    eid += 1
                    geom["e%d" % eid] = el
        page_out = out.setdefault(str(page), {})
        for e_id, rec in per_eid.items():
            target, box = rec
            if box:
                key = box            # geometry recorded at edit time: trusted
            else:
                # an older edit carries only an element id, and ids shift with
                # every pipeline change — resolving one now can name the wrong
                # piece entirely, so it must be re-made in the platform.
                print("p%s %s -> %s: SKIPPED (no geometry; re-do this edit)"
                      % (page, e_id, target))
                continue
            page_out[key] = target
            print("p%s %s -> %s  at %s" % (page, e_id, target, key))
    if dry:
        print("(dry run, nothing written)")
        return
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
    print("wrote %s (%d pages)" % (OUT, len(out)))


if __name__ == "__main__":
    main()
