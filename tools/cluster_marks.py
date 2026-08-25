#!/usr/bin/env python3
"""Cluster every floating mark in an edition by outline shape, and name the clusters.

Shapes, not guesses: the art reuses the same outline for every fatha, every waqf sign,
every sajdah mark, so normalising each mark's outer contour and hashing it groups the
whole mushaf's marks into a few dozen shape classes. Each class then takes ONE label —
seeded automatically by majority vote from the prediction pipeline (assign_words labels
marks wherever the word's own diacritics match the drawn marks one-to-one), and
confirmed by a human on the generated sample sheet. Waqf marks, sajdah ۩, and anything
the per-word prediction can't see still cluster cleanly and get named on the sheet.

    tools/cluster_marks.py hafs/kfqc --pages 1-30
    tools/cluster_marks.py hafs/kfqc --pages all -o .cache/marks

Outputs <out>/clusters.json (signature -> label, members) and <out>/sheet.html
(one row per cluster: sample drawing, count, predicted-label votes) for review.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from page import Page
from svg_lines import apply as xform
from split_line_elements import contour_polylines
from markshape import (resample, signature, sig_key, normalize,
                       composite_signature, shape_dist)
from assign_words import (page_words, page_elements, classify, cluster_line,
                          segment_word, align_segs_atoms, label_marks)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def collect(edition, names):
    """Yield every logical mark (composites joined) with outline parts and label."""
    from assign_words import composite_marks
    for name in names:
        page_no = int(re.match(r"\d+", name).group(0))
        src = os.path.join(ROOT, "mushafs", edition, "svg", name)
        page = Page(src)
        if page.content is None:
            continue
        lines_path = os.path.join(ROOT, "mushafs", edition, "lines",
                                  name.replace(".svg", ".json"))
        lines_info = json.load(open(lines_path)) if os.path.exists(lines_path) else []
        try:
            words = page_words(page_no, os.path.join(ROOT, ".cache", "words"))
        except Exception:
            words = {}
        els = page_elements(page)
        from assign_words import part_key_for
        pk, known = part_key_for(page)
        from assign_words import mark_shape_table
        classify(els, lines_info, pk, mark_shape_table())
        composite_marks(els, pk, known)
        baselines = {li["lineNumber"]: li["baseline"] for li in lines_info}
        for ln in sorted({e["line"] for e in els if e["line"]}):
            l_els = [e for e in els if e["line"] == ln]
            ws = words.get(ln, [])
            clusters, _ = cluster_line(l_els, ws)
            for w, cl in zip(ws, clusters):
                segs = segment_word(w["uthmani"])
                groups, _ = align_segs_atoms(cl, segs)
                for g_atoms, g_segs in groups:
                    if g_atoms:
                        label_marks(g_atoms, [mk for s in g_segs for mk in s["marks"]],
                                    baselines.get(ln))
        polys = {}

        from markshape import element_points

        def outer(e):
            pi = e["path"]
            if pi not in polys:
                polys[pi] = contour_polylines(page.paths[pi]["d"])
            sp = e["contours"][0]["sp"]
            return [xform(page.paths[pi]["M"], x, y)
                    for x, y in polys[pi][sp["index"]]]

        def sigpts(e):
            pi = e["path"]
            if pi not in polys:
                polys[pi] = contour_polylines(page.paths[pi]["d"])
            return element_points([[xform(page.paths[pi]["M"], x, y)
                                    for x, y in polys[pi][c["sp"]["index"]]]
                                   for c in e["contours"]])

        # Surah-title and bismillah lines are known: they receive no words and
        # their ink is narrow. Their ornamental fragments are not Quranic marks.
        lw = {}
        for ln2 in {e["line"] for e in els if e["line"]}:
            bs = [e for e in els if e["line"] == ln2 and e["kind"] == "body"]
            lw[ln2] = (max(b["x2"] for b in bs) - min(b["x1"] for b in bs)) if bs else 0
        wmax = max(lw.values()) if lw else 1
        ornament = {ln2 for ln2 in lw
                    if lw[ln2] < 0.72 * wmax or not words.get(ln2)}

        for e in els:
            if e["kind"] != "mark" or e.get("mkpart") or e["line"] in ornament:
                continue
            members = [e] + e.get("mkmembers", [])
            parts = [outer(x) for x in members]
            sparts = [sigpts(x) for x in members]
            x1 = min(m["x1"] for m in members)
            x2 = max(m["x2"] for m in members)
            y1 = min(m["y1"] for m in members)
            y2 = max(m["y2"] for m in members)
            outer_c = e["contours"][0]["sp"]
            oa = max(1e-9, (outer_c["xmax"] - outer_c["xmin"])
                     * (outer_c["ymax"] - outer_c["ymin"]))
            ha = sum((c["sp"]["xmax"] - c["sp"]["xmin"])
                     * (c["sp"]["ymax"] - c["sp"]["ymin"]) for c in e["contours"][1:])
            yield {"page": name, "label": e.get("mark"), "parts": parts,
                   "sigparts": sparts, "holefrac": ha / oa,
                   "nparts": len(parts),
                   "nholes": len(e["contours"]) - 1,
                   "size": max(x2 - x1, y2 - y1),
                   "bbox": (x1, y1, x2, y2)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("edition")
    ap.add_argument("--pages", default="1-30")
    ap.add_argument("-o", "--out", default=os.path.join(ROOT, ".cache", "marks"))
    args = ap.parse_args(argv)

    svg_dir = os.path.join(ROOT, "mushafs", args.edition, "svg")
    if args.pages == "all":
        names = sorted(n for n in os.listdir(svg_dir)
                       if re.match(r"^\d+\.svg$", n))
    else:
        a, b = (args.pages.split("-") + [args.pages])[:2]
        names = ["%03d.svg" % p for p in range(int(a), int(b) + 1)]
        names = [n for n in names if os.path.exists(os.path.join(svg_dir, n))]
    # Pages 1–2 are set in ornate large type where small whole words fall under the
    # mark size envelope; they need their own pass and stay out of shape clustering.
    names = [n for n in names if n not in ("001.svg", "002.svg")]

    def rep_points(parts):
        if len(parts) == 1:
            return normalize(parts[0] if len(parts[0]) <= 60 else resample(parts[0], 32))
        def cen(p):
            return (sum(q[0] for q in p) / len(p), sum(q[1] for q in p) / len(p))
        ordered = sorted(parts, key=lambda p: (-round(cen(p)[0], 1), round(cen(p)[1], 1)))
        pts = []
        for p in ordered:
            pts += resample(p, 24)
        return normalize(pts)

    clusters = {}
    for mk in collect(args.edition, names):
        sig = (composite_signature(mk["sigparts"]) if mk["nparts"] > 1
               else signature(mk["sigparts"][0]))
        key = sig_key(sig)
        c = clusters.setdefault(key, {"count": 0, "votes": Counter(), "samples": [],
                                      "keys": [key], "nparts": mk["nparts"],
                                      "nholes": mk["nholes"], "sizes": [],
                                      "hf": mk["holefrac"],
                                      "rep": rep_points(mk["sigparts"])})
        c["count"] += 1
        c["sizes"].append(mk["size"])
        if mk["label"]:
            c["votes"][mk["label"]] += 1
        if len(c["samples"]) < 5:
            c["samples"].append(mk)

    # Agglomerative pass: a slightly stretched two-dots or sukun hashes to its own
    # tiny cluster; absorb it into the nearest big cluster of the same structure
    # (parts, holes, similar size, close outline) so singletons label themselves.
    order = sorted(clusters.values(), key=lambda c: -c["count"])
    merged = []
    for c in order:
        med = sorted(c["sizes"])[len(c["sizes"]) // 2]
        home = None
        for m in merged:
            if m["nparts"] != c["nparts"] or m["nholes"] != c["nholes"]:
                continue
            if abs(m["hf"] - c["hf"]) > 0.15:
                continue                  # counter size is identity: ring vs damma head
            mmed = sorted(m["sizes"])[len(m["sizes"]) // 2]
            if not (0.77 <= med / (mmed or 1) <= 1.3):
                continue
            if shape_dist(c["rep"], m["rep"]) < 0.05:
                home = m
                break
        if home:
            home["count"] += c["count"]
            home["votes"] += c["votes"]
            home["keys"] += c["keys"]
            home["sizes"] += c["sizes"]
            home["samples"] = (home["samples"] + c["samples"])[:5]
        else:
            merged.append(c)

    os.makedirs(args.out, exist_ok=True)
    total = sum(c["count"] for c in merged)

    labels_path = os.path.join(args.out, "labels.json")
    confirmed = json.load(open(labels_path)) if os.path.exists(labels_path) else {}

    # resolve labels: human > votes; then suggest for the rest by nearest labeled shape
    for c in merged:
        carried = {confirmed[k]["label"] for k in c["keys"]
                   if k in confirmed and not confirmed[k].get("auto")}
        human = carried.pop() if len(carried) == 1 else None
        # conflicting carried labels (a merge joined differently-labeled keys):
        # fall back to the prediction votes and let the sheet re-confirm
        votes = c["votes"].most_common(1)
        RARE = {"small-circle", "meem-iqlab", "small-ya", "small-waw", "pause",
                "sajdah", "hizb"}
        c["auto"] = (votes[0][0] if votes and (votes[0][1] >= 3 or
                     (votes[0][1] >= 2 and votes[0][0] in RARE)) else None)
        c["label"] = human or c["auto"]
        c["human"] = bool(human)
    labeled_set = [c for c in merged if c["label"]]
    for c in merged:
        c["sugg"], c["sugg_d"] = None, None
        if c["label"]:
            continue
        med = sorted(c["sizes"])[len(c["sizes"]) // 2]
        best, bd = None, 0.12
        for m in labeled_set:
            if m["nparts"] != c["nparts"] or m["nholes"] != c["nholes"]:
                continue
            if abs(m["hf"] - c["hf"]) > 0.2:
                continue
            mmed = sorted(m["sizes"])[len(m["sizes"]) // 2]
            if not (0.6 <= med / (mmed or 1) <= 1.6):
                continue
            d = shape_dist(c["rep"], m["rep"])
            if d < bd:
                best, bd = m, d
        if best:
            c["sugg"], c["sugg_d"] = best["label"], round(bd, 3)
        elif c["nparts"] >= 2 and sorted(c["sizes"])[len(c["sizes"]) // 2] > 11:
            # an overflowing last word drawn small above the line — not a mark
            c["sugg"], c["sugg_d"] = "word", None

    merged.sort(key=lambda c: -c["count"])
    out_json, sheet_data = [], []
    for i, c in enumerate(merged):
        svgs = []
        for smp in c["samples"]:
            x1, y1, x2, y2 = smp["bbox"]
            d = "".join("M" + " L".join("%.2f %.2f" % q for q in part) + "Z"
                        for part in smp["parts"])
            svgs.append('<svg viewBox="%.1f %.1f %.1f %.1f"><path d="%s"/></svg>'
                        % (x1 - .6, y1 - .6, (x2 - x1) + 1.2, (y2 - y1) + 1.2, d))
        ctx = [[smp["page"]] + [round(v, 1) for v in smp["bbox"]]
               for smp in c["samples"][:3]]
        row = {"keys": c["keys"], "key": c["keys"][0], "count": c["count"],
               "ctx": ctx,
               "auto": c["auto"], "label": c["label"], "human": c["human"],
               "sugg": c["sugg"], "sugg_d": c["sugg_d"],
               "votes": dict(c["votes"]), "svgs": "".join(svgs)}
        out_json.append({k: row[k] for k in
                         ("keys", "count", "label", "auto", "sugg", "votes")})
        sheet_data.append(row)

    json.dump(out_json, open(os.path.join(args.out, "clusters.json"), "w"),
              ensure_ascii=False, indent=1)

    KNOWN = ["fatha", "kasra", "damma", "fathatan", "kasratan", "dammatan", "shadda", "sukun", "maddah", "hamza", "wasla", "small-alef", "small-ya", "small-waw", "small-circle", "meem-iqlab", "dot", "two-dots", "three-dots", "pause", "sajdah", "hizb", "word", "letter-hamza", "letter-part", "ignore", "fatha+kasra", "fatha+damma", "fatha+hamza", "fatha+dot", "fatha+two-dots", "fatha+three-dots", "fatha+shadda", "fatha+sukun", "fatha+maddah", "fatha+pause", "fatha+small-alef", "kasra+fatha", "kasra+damma", "kasra+hamza", "kasra+dot", "kasra+two-dots", "kasra+three-dots", "kasra+shadda", "kasra+sukun", "kasra+maddah", "kasra+pause", "kasra+small-alef", "damma+fatha", "damma+kasra", "damma+hamza", "damma+dot", "damma+two-dots", "damma+three-dots", "damma+shadda", "damma+sukun", "damma+maddah", "damma+pause", "damma+small-alef", "hamza+fatha", "hamza+kasra", "hamza+damma", "hamza+dot", "hamza+two-dots", "hamza+three-dots", "hamza+shadda", "hamza+sukun", "hamza+maddah", "hamza+pause", "hamza+small-alef", "dot+fatha", "dot+kasra", "dot+damma", "dot+hamza", "dot+two-dots", "dot+three-dots", "dot+shadda", "dot+sukun", "dot+maddah", "dot+pause", "dot+small-alef", "two-dots+fatha", "two-dots+kasra", "two-dots+damma", "two-dots+hamza", "two-dots+dot", "two-dots+three-dots", "two-dots+shadda", "two-dots+sukun", "two-dots+maddah", "two-dots+pause", "two-dots+small-alef", "three-dots+fatha", "three-dots+kasra", "three-dots+damma", "three-dots+hamza", "three-dots+dot", "three-dots+two-dots", "three-dots+shadda", "three-dots+sukun", "three-dots+maddah", "three-dots+pause", "three-dots+small-alef", "shadda+fatha", "shadda+kasra", "shadda+damma", "shadda+hamza", "shadda+dot", "shadda+two-dots", "shadda+three-dots", "shadda+sukun", "shadda+maddah", "shadda+pause", "shadda+small-alef", "sukun+fatha", "sukun+kasra", "sukun+damma", "sukun+hamza", "sukun+dot", "sukun+two-dots", "sukun+three-dots", "sukun+shadda", "sukun+maddah", "sukun+pause", "sukun+small-alef", "maddah+fatha", "maddah+kasra", "maddah+damma", "maddah+hamza", "maddah+dot", "maddah+two-dots", "maddah+three-dots", "maddah+shadda", "maddah+sukun", "maddah+pause", "maddah+small-alef", "pause+fatha", "pause+kasra", "pause+damma", "pause+hamza", "pause+dot", "pause+two-dots", "pause+three-dots", "pause+shadda", "pause+sukun", "pause+maddah", "pause+small-alef", "small-alef+fatha", "small-alef+kasra", "small-alef+damma", "small-alef+hamza", "small-alef+dot", "small-alef+two-dots", "small-alef+three-dots", "small-alef+shadda", "small-alef+sukun", "small-alef+maddah", "small-alef+pause"]
    open(os.path.join(args.out, "label_marks.html"), "w", encoding="utf-8").write("""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Mark labeling</title><style>
body{font:14px system-ui;margin:1.5em;max-width:1100px}
h1{font-size:20px} .bar{position:sticky;top:0;background:#fff;padding:8px 0;border-bottom:1px solid #ddd}
table{border-collapse:collapse;width:100%%}
td,th{border-bottom:1px solid #e5e5e5;padding:6px 8px;text-align:left;vertical-align:middle}
svg{width:44px;height:44px;margin-right:4px;fill:#1a1a1a;background:#f7f5f0;border-radius:5px}
select{font-size:13px} .done td{background:#f2fbf5} .todo td{background:#fff7f2}
.sugg td{background:#fffbe8}
.n{color:#888;font-size:12px} button{padding:6px 14px;cursor:pointer}
.note{width:150px;font-size:11.5px;margin-top:3px;border:1px solid #ddd;border-radius:4px;padding:2px 5px}
</style></head><body>
<h1>Mark shape labeling — %s (pages %s)</h1>
<div class="bar"><b id="prog"></b>
<button id="export">Download labels.json</button>
<button id="export-mine">Download my edits only</button>
<span class="n">Green = labeled, yellow = auto-suggested (confirm or fix), red = needs you.
One choice labels every occurrence. Save the download as .cache/marks/labels.json.</span></div>
<table id="t"><tr><th>samples</th><th>count</th><th>evidence</th><th>label</th></tr></table>
<script>
const DATA = %s;
const KNOWN = %s;
const saved = JSON.parse(localStorage.getItem("marklabels") || "{}");
function current(c) {
  return saved[c.key]?.label ?? c.label ?? c.sugg ?? "";
}
function cls(c) {
  if (saved[c.key]?.label || c.label) return "done";
  return c.sugg ? "sugg" : "todo";
}
const t = document.getElementById("t");
for (const c of DATA) {
  const tr = document.createElement("tr");
  tr.className = cls(c);
  const votes = Object.entries(c.votes).sort((a,b)=>b[1]-a[1]).slice(0,3)
    .map(([k,v])=>k+"\u00d7"+v).join(", ");
  const ev = [votes, c.sugg ? `\u2248 ${c.sugg} (d=${c.sugg_d})` : ""]
    .filter(Boolean).join(" \u00b7 ") || "\u2014";
  const cur = current(c);
  const opts = ['<option value="">?</option>']
    .concat(KNOWN.map(k=>`<option ${k===cur?"selected":""}>${k}</option>`)).join("");
  const ctxlinks = (c.ctx || []).map((t, i) =>
    `<a href="context.html?page=${t[0]}&bbox=${t[1]},${t[2]},${t[3]},${t[4]}"
       target="_blank">p${parseInt(t[0])}</a>`).join(" ");
  const note = saved[c.key]?.note ?? "";
  tr.innerHTML = `<td>${c.svgs}<div class="n">#${c.key.slice(0,6)} ${ctxlinks}</div></td>
    <td>${c.count}</td><td class="n">${ev}</td>
    <td><select data-key="${c.key}">${opts}</select><br>
    <input class="note" data-key="${c.key}" placeholder="note…" value="${note.replace(/"/g,'&quot;')}"></td>`;
  tr._c = c;
  t.appendChild(tr);
}
function prog() {
  let done = 0, covered = 0, all = 0;
  for (const c of DATA) {
    all += c.count;
    if (current(c)) { done++; covered += c.count; }
  }
  document.getElementById("prog").textContent =
    `${done}/${DATA.length} shapes labeled \u2014 ${(100*covered/all).toFixed(1)}%% of ${all} marks covered  `;
}
t.addEventListener("change", e => {
  const key = e.target.dataset.key;
  if (!key) return;
  const cur = saved[key] || {};
  if (e.target.tagName === "SELECT") cur.label = e.target.value || null;
  if (e.target.classList.contains("note")) cur.note = e.target.value || undefined;
  saved[key] = cur;
  localStorage.setItem("marklabels", JSON.stringify(saved));
  if (e.target.classList.contains("note")) return;
  const tr = e.target.closest("tr");
  tr.className = e.target.value ? "done" : cls(tr._c);
  prog();
});
document.getElementById("export-mine").addEventListener("click", () => {
  const a = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(new Blob([JSON.stringify(saved, null, 1)],
                                       { type: "application/json" })),
    download: "my-mark-edits.json" });
  a.click();
});
document.getElementById("export").addEventListener("click", () => {
  const out = {};
  for (const c of DATA) {
    const l = current(c);
    if (l) for (const k of c.keys) {
      out[k] = { label: l };
      if (saved[c.key]?.note) out[k].note = saved[c.key].note;
    }
  }
  const a = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)],
                                       { type: "application/json" })),
    download: "labels.json" });
  a.click();
});
prog();
</script></body></html>""" % (args.edition, args.pages,
                              json.dumps(sheet_data, ensure_ascii=False),
                              json.dumps(KNOWN)))

    covered = sum(c["count"] for c in merged if c["label"] or c["sugg"])
    print("%d marks -> %d shape clusters after merge; labeled+suggested cover %.1f%%"
          % (total, len(merged), 100 * covered / max(1, total)))
    print("labeling tool:", os.path.join(args.out, "label_marks.html"))


if __name__ == "__main__":
    main()
