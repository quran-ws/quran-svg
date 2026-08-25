#!/usr/bin/env python3
"""Merge APPROVED reviewer label edits into the global shape table.

Label edits carry the mark's shape signature (data-sig), so one approved
decision applies across the whole mushaf: every page regenerated afterwards
picks the label up from .cache/marks/labels.json.

Usage: python3 tools/apply_review_edits.py [--dry-run]
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REVIEW = os.path.join(ROOT, ".cache", "review")
LABELS = os.path.join(ROOT, ".cache", "marks", "labels.json")


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
    decisions = {}
    for d in read_jsonl(os.path.join(REVIEW, "decisions.jsonl")):
        decisions[d.get("id")] = d
    labels = json.load(open(LABELS, encoding="utf-8")) if os.path.exists(LABELS) else {}
    applied = skipped = 0
    for e in read_jsonl(os.path.join(REVIEW, "edits.jsonl")):
        d = decisions.get(e["id"])
        if d is None or d.get("action") not in ("approve", "amend"):
            continue
        if e.get("kind") not in ("relabel-mark", "label-unlabeled"):
            continue
        payload = d.get("amended_payload") or e.get("payload") or {}
        sig, lab = payload.get("sig"), payload.get("to_label")
        if not sig or not lab:
            skipped += 1          # eid-only edit: page-local, applied elsewhere
            continue
        labels[sig] = {"label": lab,
                       "note": "reviewer %s, approved by %s"
                               % (e.get("editor"), d.get("reviewer"))}
        applied += 1
    print("approved label edits applied to shape table:", applied,
          "| without sig (page-local only):", skipped)
    if not dry:
        json.dump(labels, open(LABELS, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=0)
        print("wrote", LABELS)


if __name__ == "__main__":
    main()
