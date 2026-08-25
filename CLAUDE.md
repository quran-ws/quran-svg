# Working on this repo

Semantic decomposition of the KFGQPC Madani mushaf: every page SVG broken into
ayah → word → ligature → element → labelled mark, pixel-identical to the
original artwork.

**Start here:** `docs/PROCESS.md` is the working loop. This file is the state
of play and the things that will waste your time if you do not know them.

---

## Where the work stands

Branch `feat/line-structure-on-main`, cut from `origin/main` (f8ea2002).
**Nothing has ever been committed to `main`.**

| | at session start | now |
|---|---|---|
| Flagged words (mark audit) | 991 | **667** |
| Interval-audit flags | 308 | 293 |
| Pages fully clean | 153 | **238** of 604 |
| Words emitted as two `<g class="word">` | 1158 | **0** |
| Letters filed under the wrong line | 161 | 49 |
| Bench | SCORE 77, no failures, pixelfail 0 | same |

Line placement agrees with an independent decomposition
(MushafDatabase) on **67,761 of 67,765** comparable words — 99.994%.

---

## Run these before believing anything

```bash
python3 scratchpad/bench.py                 # ~2 min. Any FAILURE or pixelfail > 0 blocks.
python3 scratchpad/cmp_pages.py 350 418     # the pages a change was aimed at
python3 scratchpad/full_sweep.py 1 604      # ~25 min, writes one JSON per page
python3 scratchpad/cmp_full.py <sweep-dir>  # against the pinned baseline
```

Accept only if the total falls, **no page worsens by more than +1**, pixelfail
is 0, and no bench case fails. The pinned "before" build is
`tools/_pipeline_baseline.py` — keep it, every comparison is against it.

After anything touching the artwork or the line cut, also run
`tools/audit_split.py` (must stay 0), `tools/audit_lines.py`, and
`tools/verify_render.py` (largest single-pixel alpha change must not grow).

---

## The audits, and what each one can and cannot see

| tool | sees | blind to |
|---|---|---|
| `scratchpad/audit_marks.py` | mark counts vs the text, dots, ligature surplus, reading order | anything that leaves counts balanced |
| `tools/audit_intervals.py` | a mark sitting in another word's exclusive territory | defects where the body partition is wrong |
| `tools/audit_width.py` | a word the wrong SIZE for its share of the line | a word that swaps one letter for another |
| `tools/audit_crossline.py` | ink held by a word but drawn in another line's territory | — |
| `tools/audit_reference.py` | disagreement with an outside decomposition | words the two sources split differently (~12%) |
| `tools/audit_split.py` | a word emitted as more than one group | — |
| `tools/audit_lines.py` | a contour tagged to a line it is not drawn in | — |

**The trap that cost the most:** for most of the session every gate counted
marks per word. A word can lose a letter, or shrink to 19% of its width, with
perfectly correct mark counts. `أَن` on p555 and `وَٱلزَّانِيَةُ` on p350 were
both visibly broken while the score was clean. `audit_width.py` exists because
of that and must be part of the gate.

---

## What worked

- **Text-driven recovery of glyphs the classifier reads as letters.** A waqf
  sign, an iqlab meem ۢ, the small waw ۥ and small ya ۦ are letter shapes drawn
  small and clear of the line. Nothing in the ink says "mark"; the spelling
  does. Take the COUNT from the text and the POSITION from the ink. Biggest
  single win of the session: pause 457 → 200, dots 255 → 148.
- **Two signals agreeing.** A transfer between neighbouring words is made only
  where the text budget says a transfer is owed AND the ink says which mark and
  confirms direction. Neither alone is safe.
- **Fixing the layer that is actually wrong.** Words landing in the wrong line
  looked like a line-cutting bug; the cut was fine and the emitter was wrong.
  Sending every element of a word to the wrapper holding most of its ink took
  split words from 1158 to 0 with pixelfail 0.
- **An outside opinion.** MushafDatabase found real defects nothing internal
  could see, and confirmed 99.994% agreement on line placement.

## What did not work — do not retry these

- **Driving repairs from the interval audit.** It finds defects counting cannot
  see, but using it to move marks moved the audit 36 → 40. It is a detector,
  not a corrector: the intervals come from the very partition being corrected.
- **Letting the width prior carry a body move.** Now OFF by default
  (`QSVG_WDECIDE=0`). Over 604 pages it changes wrong-sized words by five —
  noise — while fixing `أَوْ` on p350 by taking 16u from `وَٱلزَّانِيَةُ`, and
  fixing `إِلَىٰ` on p574 by robbing `أَرْسَلْنَآ`. Buys nothing, breaks words
  visibly.
- **Moving fatha/kasra between words.** They are one stroke named later from
  position and budget, so carrying one across a boundary re-opens that decision
  for both words. Both the neighbour transfer and the cross-line repair now
  skip the slash families. Ignoring this cost +2 on p508, p526, p446, p576.
- **Nearest-word for ink in a gap.** The small waw of ـهُۥ always sits nearer
  the NEXT word. Direction beats distance, or ~2000 suffixes lose their ۥ.

---

## Shape labels: three things that cannot be chosen from a drawing

`.cache/marks/labels.json` maps a shape signature to one label applied
mushaf-wide, so a wrong entry costs hundreds of flags at once.

1. **Composites** (`fatha+hamza`, `damma+shadda`). NOT mistakes — one outline
   carries two marks and the audit splits the label on `+`. Collapsing
   `fatha+hamza` to `hamza` deleted a fatha everywhere: 991 → 1601 flags,
   hamza +763. `apply_labels.py` now refuses without `--force`.
2. **Derived families.** fatha/kasra/fathatan/kasratan are ONE stroke; the name
   comes from position (`_POS_SWAP`) and proximity (two side by side = tanween).
   Same for damma/dammatan. Asking a reviewer to choose is a question with no
   answer — 161 of the first sheet's 187 words were this artefact.
3. **hamza vs letter-hamza.** Identical ink. `letter-hamza` is grouped with
   `letter`/`letter-part` everywhere and is never counted; `hamza` is a
   diacritic that is. One entry changed from `letter-hamza` to `hamza` cost
   ~+527 flags mushaf-wide.

**Always measure a label change.** `scratchpad/label_bisect.py` applies
confirmed labels one at a time against an 11-page sample and keeps only those
that do not make things worse — it found the one bad entry out of 18.

---

## Traps in `tools/assign_words.py`

- **The fatha/kasra slash-renaming pass exists TWICE**, hundreds of lines
  apart. Fixing one has no observable effect. Patch both.
- **`ROOT` comes from `__file__`.** A pipeline snapshot copied outside `tools/`
  silently resolves to the wrong data root and produces plausible-but-wrong
  output (p350 reported 1 flag instead of 18). Keep snapshots in `tools/`.
- **`QSVG_TRACE=<x1>[,<x1>…]`** prints every `_omove` hand-off of the ink
  starting at that x, with the calling line number. `_omove` is the single
  choke point for ~20 movers — this traces any wrongly-owned piece to the pass
  that took it.
- **Many passes move speculatively then undo.** `A -> B` immediately followed
  by `B -> A` is a trial, not a bug. Read the line numbers.
- **Body-less words never enter `wrec`** (`if not bods: continue`) — and that
  is exactly the word whose letter has gone missing. Build cross-word checks
  from `assignment`, not `wrec`.
- **Never name a script `bisect.py`** — it shadows the stdlib module `urllib`
  imports.

Env switches for A/B: `QSVG_WDECIDE` (width carries a body move, default off),
`QSVG_NB` (neighbour transfer), `QSVG_SUP` (superscript recovery),
`QSVG_HZA`/`QSVG_HZB` (hamza demote/promote), `QSVG_PIPE` (which build an audit
loads), `QSVG_OUT` (sweep output dir).

---

## `data-line` serves two layers — do not conflate them

- **The artwork** holds ONE compound `<path>` per line. Contours that overlap
  must stay in the same path or `evenodd` cancellation breaks.
  `add_line_structure.assign()` protects this.
- **The decomposed output** writes each element as its own `<path>`, and every
  path in the whole mushaf is `fill="#231f20"`. Same-colour coverage
  composites order-independently, so elements can be regrouped there with zero
  pixel change.

Fix word/line grouping in `rewrite()`, never in the artwork cut.

---

## Where to pick up

### 1. Juz 30 — cause identified, fix not written
Defect rate is **7.0 per page in juz 30 vs 2.6 elsewhere**. Measured across all
604 pages, the driver is **ayahs per page**, not word density:

```
correlation with defects/page:  ayahs +0.294 | words +0.013 | gap +0.224
   0-8 ayahs  221 pages  2.3 defects/page
  18-30 ayahs  68 pages  4.2
  30+   ayahs   8 pages  5.4
```

Juz 30 has 24.5 ayahs/page vs 9.8, and gaps 62% WIDER (6.71 vs 4.13) — it is
**looser, not tighter**, so the obvious "the text is more cramped" explanation
is wrong.

Two candidate explanations were tested and both are dead:

- **Ayah medallions.** A word beside a medallion (first or last in its ayah) is
  broken 2.4% of the time against 2.1% for a mid-ayah word — **1.1x**, no
  effect. `scratchpad/medallion.py`.
- **A biased metric.** `audit_width` flags on a ratio, and the same six units
  of error reads as 1.60 on a ten-unit word and 1.13 on a forty-five-unit one,
  so short words are flagged more readily and juz 30 has narrower words. Real
  bias — an absolute-error floor (`MIN_OFF`) is now applied — but immaterial:
  1658 flagged words became 1643 and juz 30 stayed at **2.7x** (6.8 vs 2.6).

So juz 30 is genuinely worse, it tracks ayahs per page rather than word
density, and **the mechanism is still unidentified**. Next thing to try: what
else scales with ayah count on a page? Surah headers and basmalas take whole
lines in juz 30, so the text lines per page and the band geometry differ —
compare band heights and the line-mapping stage's behaviour on those pages
against a normal page.

### 2. Four confirmed line errors
Reference and QCF layout both disagree with us; all four are words at a line
edge pulled to the neighbouring line, and the layout stage was given the
correct boundary in every case, so a later stage moves them.
`docs/defects/reference_confirmed.json` — p131 `رُسُلٌ`, p341 `لَهُۥ`,
p543 `بِمَا`, p599 `لَهَا`.

### 3. Open queue
`python3 tools/make_queue.py <sweep-dir> --sig-flags <sig_flags.json>` →
`docs/defects/queue.json`. Currently ~948 auto (mine), 9 label, 40 judge.
Largest families: pause 200, mark-steal 171, dots 148, fatha 134,
body-steal 85, ligatures 76.

### 4. Reviewer notes not yet acted on
`docs/defects/shape_notes.json` — 20 observations from Abdullah. Themes: ه/ة/و
stolen across lines, kasratan strokes not being paired (6 shapes), the sajdah
line needing to group with the word below, and signature `9514d0381190`
covering both 2 dots and 3 dots (an outline that does not discriminate).

### 5. Known open regressions
p368 `بِشَىْءٍۢ` (kasratan read as fatha) and p122 `مِّنْ` (ligature surplus).
Both +1 versus the session baseline; neither is explained.

---

## Reviewing with a human

- Review platform: `python3 tools/review_server.py` → `http://127.0.0.1:8777/?page=N&step=audit&user=NAME`.
  **Restart it and clear `.cache/words-svg/hafs-kfqc` after every pipeline
  change** — it imports the pipeline once at startup and will otherwise serve
  a stale build. This has caused false "you broke it" reports.
- Shape decisions: `tools/label_sheet.py` builds a sheet showing each shape in
  place, several times, with a note box; `tools/apply_labels.py` folds answers
  into the global table (backs up first, refuses composite collapse).
- A move edit is a fact about one place: `tools/build_overrides.py` writes
  geometry-keyed overrides that survive pipeline changes.

---

## Ground rules

- Never hand-type Quranic text. Word text comes only from the verified cached
  sources.
- Human input is captured as DATA — shapes to `labels.json`, places to
  `overrides.json` — never as a code edit.
- Every hard-won fix should become a bench case, or it comes back.
- Backups live outside the repo in `~/Documents/quran-svg-backups/`.
