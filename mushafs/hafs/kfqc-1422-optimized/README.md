# hafs/kfqc-1422-optimized — under testing

> **This edition is under testing. It is not the reference.**
> `../kfqc-1422` is the exact one — every path in it is the publisher's artwork, verified
> unchanged. This folder is that same edition with the outlines re-fitted to make the files
> a fifth of the size. Use it if you need the size; check it against `../kfqc-1422` before
> you rely on it.

## What this is

The King Fahd Complex's 1422 Ḥafṣ edition was not set from a font. Its letterforms are
outlines — traced, then converted to curves — and they are described far more finely than
they are drawn: about **117,000 segments a page**, against roughly 21,000 in the 1441
edition, with half of them shorter than a fifth of a raster pixel. That is where the size
goes, and it is also why the strokes look faceted next to 1441 at high magnification.

This edition re-fits those outlines. Cubic curves are fitted to the shape the trace
describes, corners are kept as corners, and the letterforms are the 1422 edition's own.
Nothing is redrawn from any other edition, and no geometry is borrowed from `kfqc-1441`.

| | `../kfqc-1422` | this folder |
|---|--:|--:|
| page 550 | 3,932 kB · 143,730 nodes | 808 kB · ~22,000 nodes |
| whole edition | 2.7 GB · 72,691,094 nodes | **666 MB · 16,297,182 nodes** (24.7% / 22.4%) |
| ink | the publisher's, exactly | re-fitted, within 0.15 pt |

## What changed, and what did not

Only the `d` of each contour inside `<g id="content">` is re-fitted. Everything else is
copied byte for byte: the ayah polygons, the ۝ medallions and their `ayah:x`/`ayah:y`, the
per-line grouping, `json/`, `lines/`, `surah.json` and `markers.json`. Page numbers, ayah
identities, coordinates and the `viewBox` are identical to `../kfqc-1422`, so anything built
against one works against the other.

The ayah layer is copied rather than re-derived deliberately — its geometry comes from the
page's ink, the ink moves by less than a fifth of a raster pixel, and re-deriving it would
introduce differences that mean nothing. That this was fair is checked rather than assumed:
`tools/audit_ayah_polygons.py` re-derives every polygon from *this* edition's own ink and
compares it with what is shipped here.

## The settings, and why each one exists

Tolerance is in typographic points. For scale, a raster pixel at the resolution every audit
in this repository measures with is **0.30 pt**, and a pen stroke is 2–3 pt.

| | | |
|---|--:|---|
| `tol` | 0.15 | no fitted curve is further than this from the outline it replaces |
| `angle` | 70° | a turn sharper than this is a corner, and is kept sharp |
| `window` | 0.25 | the arc length the turn is measured over |
| `detect_smooth` | 0.20 | corners are looked for on a lightly smoothed copy, so the trace's own jitter is not mistaken for a crowd of corners |
| `smooth` | 0.15 | smoothing between corners, tapering to nothing at each end so the corners never move |
| `min_diagonal` | 6.0 | contours smaller than this across — the dots, the iʿjām, the diacritics — are **not fitted at all** |
| `small_thin` | 0.02 | they are only thinned this far, which drops a point already within 0.02 pt of the chord replacing it and so cannot round anything off |
| `clearance_share` | 0.4 | no contour moves more than this share of the room it has — to its nearest neighbour, *and to itself* across a narrow waist — so neither two contours nor the two sides of one neck can be pushed together |
| `size_share` | 0.008 | nor more than this share of its own extent, because 0.15 pt is nothing across a stem and a large fraction of a small letter |

The last three exist because of specific failures found while measuring, not as a matter of
taste. Without `min_diagonal` the dots move by up to 0.21 pt and visibly change shape.
Without `clearance_share` the foot of an alif on page 550 is welded to the hamza beneath it,
across a hairline gap the artwork leaves open. Without `size_share` contours of 8–12 pt
swell systematically by 3.7%.

## What was measured

**Ayah polygons.** `tools/audit_ayah_polygons.py` re-derives every polygon from *this*
edition's own ink and compares it with what is shipped here. Over all 602 body pages and
6,224 ayat: **clean, zero findings**. Separately, the marker layer, the ayah polygons, the
`viewBox` and the root matrix are **byte-identical to `../kfqc-1422` on all 604 pages**, so
the ayah identities cannot have drifted.

**Contours.** Across all 604 pages the contour count is unchanged, and no contour was opened,
re-wound or lost.

**Corners, small elements, area** (page 550, representative):

* of the 4,690 genuine sharp corners (a turn over 100°), the average moves **0.006 pt** and
  the worst **0.144 pt** — under half a raster pixel;
* the 577 contours under 6 pt across move by at most **0.029 pt**;
* the page-wide area bias is **+0.26%**, worst band +0.54%.

**Ink connectivity, and the floor under it.** `pipeline/audit_refit.py` rasterises both
editions and matches ink components by overlap, so a stroke that pinches in two is seen as a
split and two letters growing together as a merge. Over all 604 pages at scale 10 it reports
81 pages whose blob count moves by one and 90 split/merge events.

Those are the measurement's noise floor rather than defects, and the control that shows it is
this: **the exact edition's own blob count changes with rendering scale.**

```
page 178   exact 1050 / 1050 / 1051 / 1053   optimized 1051 / 1051 / 1052 / 1054
page 219   exact 1099 / 1101 / 1105 / 1106   optimized 1099 / 1102 / 1106 / 1106
page 375   exact 1068 / 1070 / 1073 / 1074   optimized 1068 / 1071 / 1073 / 1073
                             (scales 8 / 10 / 14 / 20)
```

The artwork contains gaps narrower than a pixel, and whether the rasteriser bridges one
depends on the resolution. The difference between the two editions at any fixed scale is
smaller than the difference the exact edition shows against itself across scales, and page
219 reads as a *merge* at scale 14 and a *split* at scale 10 — the same site, opposite
directions. A raster test cannot settle features below its own pixel; the vector-level checks
above can, and they are clean.

## Why it is still under testing

The settings were tuned on page 550, and the guards were each added after a real defect was
found rather than designed in from the start — which is reason to expect there are failure
modes nobody has thought to look for. Two were caught only after a first build had already
been made and audited:

* the clearance test measured distance point-to-point on a polyline that subdivides curves
  but not straight segments, and this artwork draws long runs as straight edges — so gaps
  were overstated by up to 0.24 pt, and on page 219 two pieces of 82 and 23 page units² were
  welded into one;
* the first topology audit matched components by centre of mass, which cannot see a split at
  all, because both halves sit where the whole one was.

Both are fixed and the edition was rebuilt. But the pattern — that each defect was invisible
to the checks in place until a better check was written — is the reason for the warning at
the top. No one who reads Arabic has yet looked at these pages. Until that happens,
`../kfqc-1422` is the one to trust.

## Reproducing and checking it

```sh
python3 pipeline/optimize_edition.py --from hafs/kfqc-1422 --to hafs/kfqc-1422-optimized
python3 pipeline/audit_refit.py --pages 3,106,255,550,604
python3 tools/audit_ayah_polygons.py --mushaf hafs/kfqc-1422-optimized
```

`demo/trace.html` shows any page line by line, in both editions and the other settings that
were compared, either stacked or as an ink difference. Build its samples with
`python3 pipeline/make_trace_samples.py --pages …`.
