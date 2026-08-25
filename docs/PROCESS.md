# Closing the remaining defects

A repeatable loop for the last ~1,000 open defects. Every defect is routed to
the lane whose evidence can actually settle it, and nothing is accepted without
a global before/after against a pinned baseline.

## Where it stands

| | |
|---|---|
| Flagged words | 762 of ~9,000 |
| Pages fully clean | 216 of 604 |
| Split word groups | 0 (was 1,158) |
| Letters filed under the wrong line | 49 on 33 pages (was 161 on 94) |
| Bench | SCORE 77, no failures, pixelfail 0 |

## The four lanes

Run `python3 tools/make_queue.py <sweep-dir>` to route every open defect into
`docs/defects/queue.json`.

| lane | open | pages | who | cost of one decision |
|---|---|---|---|---|
| **auto** | 638 | 271 | me | none — a rule decides it |
| **label** | 380 | 231 | you | one call per **shape**, applies mushaf-wide |
| **judge** | 48 | 29 | you | one call, becomes a test or an override |
| **place** | residue | — | you | one call per **occurrence** — last resort |

### Lane A — automatic

Defects with a mechanical invariant: side rules (kasra hangs below, fatha rides
above), text budgets, the joining-rule piece count, reading order, band
membership. I work these in leverage order, root-causing with `QSVG_TRACE`
rather than patching symptoms.

Open: ligature surplus (89), fatha (138), MARK-STEAL (172), BODY-STEAL (83),
hamza composites (62), wasla chains (35).

### Lane B — labelling  *(needs you)*

The art reuses one outline for every fatha, every waqf sign, every sajdah mark.
A shape signature therefore names ink for the whole mushaf, and one answer fixes
every occurrence.

**72 shapes are unlabelled or contested; they cause 196 flagged words. The top
10 answers settle 141 of them.**

```
python3 tools/label_sheet.py <sig_flags.json>     # builds the sheet
open docs/defects/label_sheet.html                # decide; Copy decisions
python3 tools/apply_labels.py decisions.json      # folds into labels.json
```

The sheet asks only about shapes that are genuinely contested. It does not ask
about position swaps — the same stroke is a fatha above a letter and a kasra
below it, and the pipeline is right to swap it. Tick *leave* on anything you are
unsure of; unanswered shapes simply stay in the queue.

### Lane C — per-place override  *(needs you)*

For residue no general rule should have to infer: *this ink, on this page,
belongs to that word.* Mark it on the review platform, then:

```
python3 tools/build_overrides.py        # -> .cache/review/overrides.json
```

Overrides are keyed by geometry, not element id, so they survive pipeline
changes. Use this lane only after A and B are exhausted — it buys one word.

### Lane D — adjudication  *(needs you)*

Where an audit and the artwork disagree and I cannot tell which is right. You
look and decide. If the answer generalises it becomes a bench case; if it is
local it becomes an override.

## Outside opinion

Two audits cannot see a word that is wholly wrong but internally consistent:
mark counts balance, and the interval test compares it only with its
neighbours. An independent decomposition can.

```
python3 tools/audit_reference.py "<MushafDatabase>/SVG V1.01"
```

MushafDatabase publishes the same KFGQPC pages with word identity and line
number per word. Fold their separate waw and stop-sign words back into ours,
and compare the letter skeleton rather than the index, or the result is noise.
Where it disagrees, check `.cache/qcf_lines.json` as a third source before
believing either side: of 15 real disagreements only 4 were ours.

## Word size

```
python3 tools/audit_width.py
```

A word that loses a letter changes no mark count, so nothing else notices. This
compares each word's ink against its share of the line and flags anything far
off — it is the only audit that saw `وَٱلزَّانِيَةُ` fall to 60% of its size.

## The verification spine

Every change, every lane, in order. This is not optional — three of my own
"fixes" this session were caught here, not by reasoning.

1. **`bench.py`** — named ink-level cases, SCORE, `pixelfail`. ~2 min. Any
   FAILURE or `pixelfail > 0` blocks outright.
2. **`cmp_pages.py <pages>`** — the pages the change was aimed at.
3. **`full_sweep.py` → `cmp_full.py`** — all 604 pages against the pinned
   baseline `tools/_pipeline_baseline.py`. ~25 min.
4. **Accept only if** total flags fall, no page worsens by more than +1,
   `pixelfail` is 0, and no bench case fails.
5. Accepted → re-pin the baseline. Rejected → restore from
   `~/Documents/quran-svg-backups/`.

After anything that touches the artwork or the line cut, also run
`audit_split.py` (must stay 0), `audit_lines.py`, and `verify_render.py` (the
max alpha change must not grow).

## Rules that cost something to learn

- **A detector is not a corrector.** The interval audit finds defects counting
  cannot see, but driving repairs from it moved the audit 36 → 40. Any
  automatic repair needs an independent guard — width prior, side rule,
  reading order.
- **Human input is captured as data, never as a code edit.** Shapes go to
  `labels.json`, places to `overrides.json`. A decision written into a branch
  is a decision lost.
- **Grep for a second copy before editing a pass.** The fatha/kasra renaming
  exists twice in `assign_words.py`; fixing one has no observable effect.
- **Fix the layer that is wrong.** Words in the wrong line looked like a
  line-cutting bug; the cut was fine and the emitter was wrong.
- **Every hard-won fix becomes a bench case**, or it will come back.

## Done, per class

A family is finished when its audit count is zero, or every remaining item has
been adjudicated and recorded with a reason — and a bench case exists that would
catch its return.
