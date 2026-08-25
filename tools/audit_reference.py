#!/usr/bin/env python3
"""Check our decomposition against an independent one.

MushafDatabase publishes the same KFGQPC Madani pages decomposed to words and
ligatures, with each word carrying its surah, ayah, index in the ayah and line
number. That is an outside opinion on the two things our own audits are worst
at judging: which line a word is on, and where one word ends and the next
begins.

This compares the cheap, geometry-free part first — the line each word sits on
— because it needs no registration between two different coordinate systems.

    python3 tools/audit_reference.py <ref-dir> [first] [last]
"""
import importlib.util, io, contextlib, json, os, re, sys
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
WORD = re.compile(r'<g id="md-word-\d+"([^>]*)>')
ATTR = re.compile(r'data-([a-z-]+)="([^"]*)"')


_KEEP = set(range(0x0621, 0x064B)) | {0x0671, 0x0672, 0x0673, 0x0675,
                                        0x0640}


def skeleton(t):
    """Just the letters: the two sources spell the marks differently."""
    return "".join(c for c in (t or "") if ord(c) in _KEEP)


WAQF = "\u06d6\u06d7\u06d8\u06d9\u06da\u06db\u06dc\u06dd\u06de\u06e9"


def reference(path):
    """{(surah, ayah, our-position): (line, hafs text)} for one page.

    The reference counts words differently from the layout we follow: a
    conjunction waw is a word of its own (data-waw-alatf), and a stop sign is
    another. Both belong to a neighbouring word in our numbering, so they are
    folded back before the positions are compared — otherwise every index after
    the first waw is off by one and every word looks misplaced.
    """
    s = io.open(path, encoding="utf-8-sig").read()
    seq = {}
    for m in WORD.finditer(s):
        a = dict(ATTR.findall(m.group(1)))
        if a.get("type") != "text":
            continue
        try:
            sa = (int(a["surah"]), int(a["aya"]))
            idx = int(a["word-index-in-ayah"])
        except (KeyError, ValueError):
            continue
        seq.setdefault(sa, []).append(
            (idx, int(a.get("line-number", 0)), a.get("hafs", ""),
             a.get("waw-alatf") == "true"))
    out = {}
    for sa, items in seq.items():
        items.sort()
        merged = []
        pend = ""
        for _, ln, txt, waw in items:
            if waw:
                pend += txt              # joins the word that follows it
                continue
            if txt and all(c in WAQF or c.isspace() for c in txt):
                if merged:               # a stop belongs to the word before it
                    continue
            merged.append((ln, pend + txt))
            pend = ""
        if pend and merged:
            merged.append((merged[-1][0], pend))
        for i, (ln, txt) in enumerate(merged, 1):
            out[(sa[0], sa[1], i)] = (ln, txt)
    return out


def ours(pg):
    with contextlib.redirect_stdout(io.StringIO()):
        aw.assign_page("hafs/kfqc", pg, os.path.join(ROOT, ".cache", "words"))
    out = {}
    for w, at in _cap["a"]:
        if not w:
            continue
        b = [e for a in at for e in a["els"] if e["kind"] == "body"]
        if not b:
            continue
        lns = [e.get("line") for e in b if e.get("line")]
        if not lns:
            continue
        out[(w["surah"], w["ayah"], w["pos"])] = (
            max(set(lns), key=lns.count),
            min(e["x1"] for e in b), max(e["x2"] for e in b), w["uthmani"])
    return out


def scan(args):
    pg, refdir = args
    p = os.path.join(refdir, "%03d.svg" % pg)
    if not os.path.exists(p):
        return pg, None
    try:
        ref, mine = reference(p), ours(pg)
    except Exception as e:
        return pg, {"err": str(e)[:90]}
    both = set(ref) & set(mine)
    off = []
    mismatched = 0
    for k in sorted(both):
        # Same position is not the same word. The two sources still split some
        # ayahs differently, so an index can line up while the words do not,
        # and comparing those reports a line error that does not exist. The
        # letter skeleton settles it: same letters, same word.
        if skeleton(ref[k][1]) != skeleton(mine[k][3]):
            mismatched += 1
            continue
        rl = ref[k][0]
        ml = mine[k][0]
        if rl and ml and rl != ml:
            off.append({"page": pg, "key": "%d:%d:%d" % k, "word": ref[k][1],
                        "ref_line": rl, "our_line": ml})
    return pg, {"matched": len(both) - mismatched, "text_mismatch": mismatched,
                "only_ref": len(set(ref) - set(mine)),
                "only_ours": len(set(mine) - set(ref)), "line_off": off}


if __name__ == "__main__":
    refdir = sys.argv[1]
    a = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    b = int(sys.argv[3]) if len(sys.argv) > 3 else 604
    from multiprocessing import Pool
    tot = Counter()
    offs = []
    with Pool(2, maxtasksperchild=6) as pool:
        for pg, r in pool.imap_unordered(scan, [(p, refdir) for p in range(a, b + 1)]):
            if not r or "err" in r:
                tot["pages_failed"] += 1
                continue
            tot["pages"] += 1
            tot["matched"] += r["matched"]
            tot["text_mismatch"] += r["text_mismatch"]
            tot["only_ref"] += r["only_ref"]
            tot["only_ours"] += r["only_ours"]
            offs += r["line_off"]
    json.dump(offs, open(os.path.join(ROOT, "docs", "defects",
                                      "reference_lines.json"), "w"),
              ensure_ascii=False, indent=1)
    print("pages compared %d (failed %d)" % (tot["pages"], tot["pages_failed"]))
    print("words matched by identity AND text: %d" % tot["matched"])
    print("same index but different word (ayah split differently): %d"
          % tot["text_mismatch"])
    print("only in reference: %d   only ours: %d"
          % (tot["only_ref"], tot["only_ours"]))
    print("words on a DIFFERENT line than the reference: %d over %d pages"
          % (len(offs), len({o["page"] for o in offs})))
    for o in offs[:12]:
        print("   p%-4d %-11s %-16s reference line %2d, ours %2d"
              % (o["page"], o["key"], o["word"], o["ref_line"], o["our_line"]))
