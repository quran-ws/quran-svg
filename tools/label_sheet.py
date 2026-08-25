#!/usr/bin/env python3
"""Build the review sheet for shapes the pipeline cannot name with confidence.

The art reuses one outline for every fatha, every waqf sign, every sajdah mark,
so a shape signature names ink for the WHOLE mushaf: one answer here fixes every
occurrence. This asks only about shapes that are genuinely contested, ordered by
how many flagged words each answer settles.

Each shape is shown several times, and shown IN PLACE — the mark picked out
against the rest of its word — because the same outline reads differently
depending on where it sits, and that is exactly the judgement being asked for.

    python3 tools/label_sheet.py scratchpad/sig_flags.json
    open docs/defects/label_sheet.html

Shapes whose element name differs from the table only by drawn POSITION are not
asked about: the same stroke is a fatha above the letter and a kasra below it,
and the pipeline is right to swap it.
"""
import argparse, html, json, os, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
# Families whose final name is DERIVED from one outline rather than chosen by
# shape, so a disagreement inside them is not a question for a reviewer:
#   position    - the same stroke is a fatha above the letter, a kasra below it
#   proximity   - two of that stroke side by side are a tanween
# Dots are NOT such a family: one blob, two and three are different outlines,
# so a signature called both is a real conflict and stays on the sheet.
DERIVED = ({"fatha", "kasra", "fathatan", "kasratan"},
           {"damma", "dammatan"})
ALL = ["fatha", "kasra", "damma", "fathatan", "kasratan", "dammatan",
       "sukun", "shadda", "maddah", "small-alef", "small-waw", "small-ya",
       "small-circle", "small-noon", "wasla", "hamza", "pause", "meem-iqlab",
       "dot", "two-dots", "three-dots", "letter-part", "word", "ignore"]
# offered as one-tap buttons beside whatever the shape is already called
COMMON = ["fatha", "kasra", "damma", "sukun", "shadda", "pause",
          "dot", "two-dots", "three-dots", "hamza", "maddah", "meem-iqlab"]


def contested(rows):
    out = defaultdict(lambda: {"words": set(), "known": None,
                               "drawn": set(), "occ": []})
    for r in rows:
        if r["kind"] != "mark":
            continue                      # a letter body needs no shape name
        known = r["known"]
        if known is not None:
            if not r["mark"] or r["mark"] == known:
                continue
            if any(known in f and r["mark"] in f for f in DERIVED):
                continue      # the pipeline derives this name; nothing to ask
            if "+" in known and r["mark"] in known.split("+"):
                continue      # a composite outline carries both marks, and
                              # the element is named for one of them: expected
        e = out[r["sig"]]
        e["words"].add((r["page"], r["key"]))
        e["known"] = known
        if r["mark"]:
            e["drawn"].add(r["mark"])
        e["occ"].append((r["page"], r["key"]))
    return out


def pick_pages(cand, per):
    """Fewest pages that still show every shape `per` times."""
    pool = defaultdict(set)
    for sg, e in cand.items():
        for pg, key in e["occ"][:14]:
            pool[pg].add(sg)
    got, chosen = defaultdict(int), []
    for pg, sigs in sorted(pool.items(), key=lambda t: -len(t[1])):
        useful = [s for s in sigs if got[s] < per]
        if not useful:
            continue
        chosen.append(pg)
        for s in useful:
            got[s] += 1
        if all(got[s] >= per for s in cand):
            break
    return chosen


def gather(cand, per):
    """One drawing per occurrence: the mark, against the rest of its word."""
    import importlib.util, io, contextlib
    spec = importlib.util.spec_from_file_location(
        "assign_words", os.path.join(ROOT, "tools", "assign_words.py"))
    aw = importlib.util.module_from_spec(spec)
    sys.modules["assign_words"] = aw
    spec.loader.exec_module(aw)
    from add_line_structure import build_d
    cap = {}
    orig = aw.rewrite

    def spy(page, a):
        cap["a"] = a
        cap["page"] = page
        return orig(page, a)
    aw.rewrite = spy

    want = defaultdict(set)
    for sg, e in cand.items():
        for pg, key in e["occ"][:14]:
            want[pg].add(sg)
    shots = defaultdict(list)
    pages = pick_pages(cand, per)
    # A contested shape often appears in only one or two FLAGGED words, but the
    # same outline is drawn all over the mushaf. Judging it from a single
    # example is exactly the way to name it wrongly, so sweep a spread of other
    # pages for more of the same signature until each shape has enough to
    # compare. Pages already chosen come first so nothing is read twice.
    spread = [p for p in range(6, 605, 13) if p not in pages]
    for pg in pages + spread:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                aw.assign_page("hafs/kfqc", pg,
                               os.path.join(ROOT, ".cache", "words"))
        except Exception:
            continue
        if all(len(shots[g]) >= per for g in cand):
            break
        for w, at in cap["a"]:
            if not w:
                continue
            els = [e for a in at for e in a["els"]]
            if not els:
                continue
            for e in els:
                sg = e.get("sig")
                if sg not in cand or len(shots[sg]) >= per:
                    continue
                if e["kind"] != "mark":
                    continue
                x1 = min(q["x1"] for q in els)
                x2 = max(q["x2"] for q in els)
                y1 = min(q["y1"] for q in els)
                y2 = max(q["y2"] for q in els)
                pad = 1.6
                # The mark gets its own box as well as the word's. Drawn only
                # inside the word's box a diacritic is a few pixels across —
                # far too small to name — so the shape is shown large on its
                # own, with the word beside it just to place it.
                mw = max(e["x2"] - e["x1"], 0.8)
                mh = max(e["y2"] - e["y1"], 0.8)
                mp = 0.28 * max(mw, mh)
                # Contour data is in the source file's own coordinates, but
                # the bounding boxes are in page space — these pages carry a
                # transform with a negative y-scale. Drawn straight into a
                # page-space viewBox the ink lands nowhere near it, which is
                # why nothing appeared. Each piece keeps the matrix of the
                # path it came from and is wrapped in it.
                def _g(q, cls):
                    M = cap["page"].paths[q["path"]]["M"]
                    return ('<g transform="matrix(%s)"><path class="%s" '
                            'fill-rule="evenodd" d="%s"/></g>'
                            % (" ".join("%.6f" % v for v in M), cls,
                               build_d(q["contours"])))
                shots[sg].append({
                    "ctx": "".join(_g(q, "ctx") for q in els if q is not e),
                    "hit": _g(e, "hit"),
                    "vb": "%.2f %.2f %.2f %.2f" % (x1 - pad, y1 - pad,
                                                   (x2 - x1) + 2 * pad,
                                                   (y2 - y1) + 2 * pad),
                    "mvb": "%.2f %.2f %.2f %.2f" % (e["x1"] - mp, e["y1"] - mp,
                                                    mw + 2 * mp, mh + 2 * mp),
                    "word": w["uthmani"], "page": pg,
                    "mark": e.get("mark") or "unnamed",
                })
    return shots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sig_flags")
    ap.add_argument("-o", default="docs/defects/label_sheet.html")
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--samples", type=int, default=4)
    a = ap.parse_args()

    rows = json.load(open(a.sig_flags))
    # Notes survive a rebuild: they are observations about a SHAPE, and the
    # shape outlives any one sheet.
    npath = os.path.join(ROOT, "docs", "defects", "shape_notes.json")
    seed = json.load(open(npath, encoding="utf-8")) if os.path.exists(npath) else {}
    cand = dict(sorted(contested(rows).items(),
                       key=lambda t: -len(t[1]["words"]))[:a.limit])
    shots = gather(cand, a.samples)

    cards = []
    for i, (sg, e) in enumerate(sorted(cand.items(),
                                       key=lambda t: -len(t[1]["words"])), 1):
        n = len(e["words"])
        drawn = sorted(e["drawn"])
        pics = "".join(
            '<figure>'
            '<svg class="big" viewBox="%s" role="img" aria-label="%s">%s</svg>'
            '<svg class="map" viewBox="%s" role="img" aria-label="in %s">%s%s</svg>'
            '<figcaption>p%s<span>%s</span></figcaption></figure>'
            % (s["mvb"], html.escape(s["mark"]), s["hit"],
               s["vb"], html.escape(s["word"]), s["ctx"], s["hit"],
               s["page"], html.escape(s["word"]))
            for s in shots.get(sg, []))
        if not pics:
            pics = '<p class="nopic">no drawing available</p>'
        quick = []
        for c in ([e["known"]] if e["known"] else []) + drawn + COMMON:
            if c and c in ALL and c not in quick:
                quick.append(c)
            if len(quick) == 8:
                break
        btns = "".join('<button type="button" data-v="%s">%s<kbd>%d</kbd></button>'
                       % (c, c, k) for k, c in enumerate(quick, 1))
        opts = "".join('<option value="%s">%s</option>' % (c, c)
                       for c in ALL if c not in quick)
        cards.append(
            '<article class="shape" data-sig="%s" id="s%d" tabindex="0">'
            '<div class="head"><span class="idx">%d</span>'
            '<span class="count"><b>%d</b> flagged word%s</span>'
            '<span class="meta">table <b>%s</b> &middot; pipeline <b>%s</b></span>'
            '<code>%s</code><span class="state" aria-live="polite"></span></div>'
            '<div class="shots">%s</div>'
            '<div class="pick"><div class="btns">%s</div>'
            '<select><option value="">more&hellip;</option>%s</select>'
            '<button type="button" class="leave" data-v="">leave<kbd>0</kbd></button>'
            '</div>'
            '<textarea class="note" rows="1" spellcheck="false" '
            'placeholder="note \u2014 anything a label cannot say, e.g. '
            '&quot;this is the \u062f of the next word&quot;">%s</textarea>'
            '</article>'
            % (sg, i, i, n, "" if n == 1 else "s",
               html.escape(e["known"] or "—"),
               html.escape(", ".join(drawn) or "—"),
               sg[:12], pics, btns, opts,
               html.escape(seed.get(sg, "") or seed.get(sg[:12], ""))))

    total = len(set().union(*[e["words"] for e in cand.values()])) if cand else 0
    doc = (TEMPLATE.replace("@@CARDS@@", "\n".join(cards))
                   .replace("@@SHAPES@@", str(len(cand)))
                   .replace("@@WORDS@@", str(total)))
    out = os.path.join(ROOT, a.o)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write(doc)
    print("%d shapes, %d drawings -> %d flagged words   %s"
          % (len(cand), sum(len(v) for v in shots.values()), total, a.o))


TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shape decisions</title>
<style>
:root{
  --ground:#f5f6f8;--surface:#fff;--surface-2:#eceef2;--line:#dcdfe6;
  --text:#231f20;--text-2:#5d6068;--text-3:#8b8e97;
  --accent:#1f4b99;--accent-soft:#e6ecf7;
  --ok:#2e6b4f;--ok-soft:#e2efe8;--ink:#231f20;--ghost:#c8ccd4;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#131417;--surface:#1b1d21;--surface-2:#23262b;--line:#2f333a;
  --text:#e8e9ec;--text-2:#a5a8b0;--text-3:#787c85;
  --accent:#7ba3e8;--accent-soft:#1c2740;--ok:#6dc19a;--ok-soft:#16281f;
  --ink:#e8e9ec;--ghost:#4a4f58;}}
:root[data-theme="dark"]{
  --ground:#131417;--surface:#1b1d21;--surface-2:#23262b;--line:#2f333a;
  --text:#e8e9ec;--text-2:#a5a8b0;--text-3:#787c85;
  --accent:#7ba3e8;--accent-soft:#1c2740;--ok:#6dc19a;--ok-soft:#16281f;
  --ink:#e8e9ec;--ghost:#4a4f58;}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--text);
  font:400 15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;padding-bottom:96px}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 0}
header{margin-bottom:24px}
h1{font-size:26px;margin:0 0 6px;letter-spacing:-.01em}
.sub{margin:0;color:var(--text-2);max-width:70ch}
.sub b{color:var(--text)}
kbd{font:500 10px/1 ui-monospace,Menlo,monospace;border:1px solid var(--line);
  border-bottom-width:2px;border-radius:3px;padding:2px 4px;margin-left:6px;
  color:var(--text-3);background:var(--surface)}
.shape{background:var(--surface);border:1px solid var(--line);border-radius:12px;
  padding:18px 20px;margin-bottom:14px;scroll-margin-top:16px}
.shape:focus{outline:2px solid var(--accent);outline-offset:2px}
.shape.done{border-color:var(--ok);background:var(--ok-soft)}
.shape.left{opacity:.5}
.head{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px}
.idx{font:500 12px/22px ui-monospace,monospace;min-width:22px;height:22px;
  text-align:center;border-radius:50%;background:var(--surface-2);color:var(--text-3)}
.count b{font-variant-numeric:tabular-nums}
.meta{color:var(--text-2);font-size:13.5px}
.meta b{color:var(--text);font-weight:600}
.head code{margin-left:auto;font:400 12px/1 ui-monospace,monospace;color:var(--text-3)}
.state{font-size:13px;font-weight:600;color:var(--ok)}
.shots{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}
figure{margin:0;background:var(--surface-2);border:1px solid var(--line);
  border-radius:8px;padding:9px;display:flex;flex-direction:column;gap:7px;
  align-items:stretch;min-width:170px;flex:1 1 170px;max-width:250px}
figure svg{width:100%;display:block}
figure svg.big{height:104px;background:var(--surface);border-radius:6px}
figure svg.map{height:30px;opacity:.95}
.ctx{fill:var(--ghost)}
.hit{fill:var(--accent)}
figcaption{font-size:11px;color:var(--text-3);text-align:center;line-height:1.3}
figcaption span{display:block;font-size:16px;color:var(--text);direction:rtl}
.nopic{color:var(--text-3);font-size:13px;margin:0}
.pick{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.btns{display:flex;gap:6px;flex-wrap:wrap}
.pick button{font:500 13px/1 inherit;padding:8px 11px;border-radius:7px;
  border:1px solid var(--line);background:var(--surface-2);color:var(--text);
  cursor:pointer;display:inline-flex;align-items:center}
.pick button:hover{border-color:var(--accent);color:var(--accent)}
.pick button.on{background:var(--accent);border-color:var(--accent);color:#fff}
.pick button.on kbd{color:#fff;border-color:rgba(255,255,255,.5)}
.pick button.leave{margin-left:auto;color:var(--text-3)}
textarea.note{width:100%;margin-top:10px;padding:9px 11px;border-radius:7px;
  border:1px dashed var(--line);background:transparent;color:var(--text);
  font:400 13.5px/1.5 inherit;resize:vertical;min-height:38px}
textarea.note:focus{border-style:solid;border-color:var(--accent);outline:none}
textarea.note.has{border-style:solid;border-color:var(--accent);
  background:var(--accent-soft)}
.pick select{font:400 13px/1 inherit;padding:8px 10px;border-radius:7px;
  border:1px solid var(--line);background:var(--surface-2);color:var(--text)}
.bar{position:fixed;left:0;right:0;bottom:0;background:var(--surface);
  border-top:1px solid var(--line);padding:12px 20px;display:flex;gap:16px;
  align-items:center;justify-content:center;flex-wrap:wrap;z-index:5}
.bar .prog{font-variant-numeric:tabular-nums;color:var(--text-2);font-size:14px}
.bar .prog b{color:var(--text);font-size:16px}
.bar button{font:500 14px/1 inherit;padding:10px 18px;border-radius:8px;
  border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer}
.bar button.ghost{background:transparent;color:var(--accent)}
#out{display:none;width:100%;max-width:1080px;margin:12px auto 0;height:160px;
  font:400 12px/1.5 ui-monospace,monospace;padding:12px;border-radius:8px;
  border:1px solid var(--line);background:var(--surface);color:var(--text)}
button:focus-visible,select:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style></head><body>
<div class="wrap">
<header>
  <h1>Shape decisions</h1>
  <p class="sub"><b>@@SHAPES@@</b> shapes the pipeline cannot name with confidence &mdash;
  together they account for <b>@@WORDS@@</b> flagged words. One answer fixes every
  occurrence of that shape in the mushaf, so the rows at the top are worth most.
  Each shape is shown in place, picked out in blue against the rest of its word.
  Keys: <kbd>1</kbd>&ndash;<kbd>8</kbd> choose, <kbd>0</kbd> leave,
  <kbd>J</kbd>/<kbd>K</kbd> move. Every shape also has a note box &mdash; use it
  for anything a label cannot say, such as <i>this is a letter of the next
  word</i>. A note reaches me even with no label chosen. Everything saves as you
  go.</p>
</header>
@@CARDS@@
<textarea id="out" spellcheck="false" aria-label="decisions JSON"></textarea>
</div>
<div class="bar">
  <span class="prog"><b id="ndone">0</b> of @@SHAPES@@ decided</span>
  <button onclick="dump()">Copy decisions</button>
  <button class="ghost" onclick="toggleOut()">Show JSON</button>
  <button class="ghost" onclick="reset()">Reset</button>
</div>
<script>
var KEY="mushaf-shape-decisions",NKEY="mushaf-shape-notes",saved={},notes={};
try{saved=JSON.parse(localStorage.getItem(KEY)||"{}")}catch(e){saved={}}
try{notes=JSON.parse(localStorage.getItem(NKEY)||"{}")}catch(e){notes={}}
var cards=[].slice.call(document.querySelectorAll(".shape")),cur=0;

function paint(card){
  var sig=card.dataset.sig,v=saved[sig];
  card.classList.toggle("done",v!==undefined&&v!=="");
  card.classList.toggle("left",v==="");
  card.querySelector(".state").textContent=
    v===undefined?"":(v===""?"left":"\\u2713 "+v);
  card.querySelectorAll(".btns button").forEach(function(b){
    b.classList.toggle("on",b.dataset.v===v);
  });
  var sel=card.querySelector("select");
  sel.value=(v&&![].slice.call(card.querySelectorAll(".btns button"))
    .some(function(b){return b.dataset.v===v}))?v:"";
  var ta=card.querySelector(".note");
  if(ta&&document.activeElement!==ta)ta.value=notes[sig]||"";
  if(ta)ta.classList.toggle("has",!!(notes[sig]||"").trim());
}
function set(card,v){
  var sig=card.dataset.sig;
  if(v===undefined){delete saved[sig]}else{saved[sig]=v}
  try{localStorage.setItem(KEY,JSON.stringify(saved))}catch(e){}
  paint(card);count();
}
function count(){
  var n=0,seen={};
  for(var k in saved){if(saved[k]){seen[k]=1}}
  for(var k in notes){if((notes[k]||"").trim()){seen[k]=1}}
  for(var k in seen)n++;
  document.getElementById("ndone").textContent=n;
}
cards.forEach(function(card,i){
  var pre=card.querySelector(".note");
  if(pre&&pre.value.trim()&&!(card.dataset.sig in notes))
    notes[card.dataset.sig]=pre.value;
  card.addEventListener("focus",function(){cur=i});
  card.querySelectorAll(".btns button").forEach(function(b){
    b.addEventListener("click",function(){
      set(card,saved[card.dataset.sig]===b.dataset.v?undefined:b.dataset.v);
    });
  });
  card.querySelector(".leave").addEventListener("click",function(){
    set(card,saved[card.dataset.sig]===""?undefined:"");
  });
  card.querySelector("select").addEventListener("change",function(){
    if(this.value)set(card,this.value);
  });
  var ta=card.querySelector(".note");
  ta.addEventListener("input",function(){
    var sig=card.dataset.sig,t=ta.value;
    if(t.trim()){notes[sig]=t}else{delete notes[sig]}
    try{localStorage.setItem(NKEY,JSON.stringify(notes))}catch(e){}
    ta.classList.toggle("has",!!t.trim());count();
  });
  paint(card);
});
count();
document.addEventListener("keydown",function(ev){
  if(/^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName))return;
  var card=cards[cur];if(!card)return;
  var k=ev.key.toLowerCase();
  if(k==="j"||ev.key==="ArrowDown"){cur=Math.min(cur+1,cards.length-1);cards[cur].focus();ev.preventDefault()}
  else if(k==="k"||ev.key==="ArrowUp"){cur=Math.max(cur-1,0);cards[cur].focus();ev.preventDefault()}
  else if(k==="0"){set(card,saved[card.dataset.sig]===""?undefined:"");ev.preventDefault()}
  else if(/^[1-8]$/.test(k)){
    var b=card.querySelectorAll(".btns button")[parseInt(k,10)-1];
    if(b){set(card,b.dataset.v);ev.preventDefault();
      if(cur<cards.length-1){cur++;cards[cur].focus()}}
  }
});
function decisions(){
  var o={},k;
  for(k in saved){if(saved[k])o[k]={label:saved[k]}}
  for(k in notes){
    var t=(notes[k]||"").trim();
    if(!t)continue;
    if(!o[k])o[k]={};       // a note on its own still reaches me
    o[k].note=t;
  }
  return o;
}
function dump(){
  var j=JSON.stringify(decisions(),null,1),t=document.getElementById("out");
  t.value=j;t.style.display="block";t.select();
  if(navigator.clipboard)navigator.clipboard.writeText(j);
  var n=Object.keys(decisions()).length;
  document.getElementById("ndone").textContent=n;
  alert(n+" decision"+(n==1?"":"s")+" copied. Save as decisions.json, then run:\\n\\npython3 tools/apply_labels.py decisions.json");
}
function toggleOut(){var t=document.getElementById("out");
  t.value=JSON.stringify(decisions(),null,1);
  t.style.display=t.style.display==="block"?"none":"block"}
function reset(){if(confirm("Clear all decisions and notes on this sheet?")){
  saved={};notes={};
  try{localStorage.removeItem(KEY);localStorage.removeItem(NKEY)}catch(e){}
  cards.forEach(paint);count()}}
if(cards.length)cards[0].focus();
</script></body></html>
"""

if __name__ == "__main__":
    main()
