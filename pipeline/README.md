# pipeline — turning a publisher's Illustrator files into an edition

This is how `mushafs/hafs/kfqc-1422` was made, and the route any future edition takes. It is
a chain of small steps, each of which can be re-run on its own and each of which reports what
it did rather than only that it finished.

```
hafs_1422.zip                       604 Illustrator files from the King Fahd Complex
   │  convert_ai.py                 Inkscape, one SVG per page, layers preserved
   ▼
.work/hafs1422/raw/NNN.svg          the artwork, untouched, on its A4 sheet
   │  normalize.py                  select the layers, map the sheet into the page window
   ▼
mushafs/<edition>/svg/NNN.svg       a page in this repo's format — but with no ayah layer
   │  verify_ink.py                 prove the artwork survived the trip
   │  seed_polygons.py              give every ayah end its identity, from a reference edition
   │  tools/build_ayah_polygons.py  give every identity its geometry, from this edition's ink
   │  opening_spread.py             pages 1 and 2, which that generator does not do
   │  tools/add_line_structure.py   group each page's contours into its fifteen lines
   │  make_variants.py              cut the surah-specific views
   │  build_indexes.py              markers.json and surah.json
   ▼
mushafs/<edition>/                  svg/ svg-br/ json/ lines/
   │  tools/audit_ayah_polygons.py  and the rest of tools/
```

## What the steps are for

| | |
|---|---|
| `convert_ai.py` | drives Inkscape over the `.ai` files. They are PDFs; the Illustrator layers survive as `layer-MC0…MC4` because the PDF names them as optional-content groups. |
| `rawsvg.py` | reads that output: which layer is which, and where each path sits. |
| `pathdata.py` | parses, optionally thins, and re-encodes a `d`. |
| `layout.py` | the fitted map from a publisher's sheet into the 345×550 page window, and the code that re-derives it. |
| `markers.py` | the ۝ medallions of a raw page, each paired with its numeral. |
| `normalize.py` | the conversion itself. |
| `verify_ink.py` | the proof that it changed nothing. |
| `seed_polygons.py` | ayah identities, transferred from an edition of the same riwaya. |
| `opening_spread.py` | pages 1 and 2. |
| `make_variants.py` | the `NNN-surahS` crops. |
| `build_indexes.py` | `markers.json`, `surah.json`. |

## The two things worth knowing before you use it

**The artwork is not touched.** `normalize.py` re-encodes each `d` at the source's own three
decimals and moves nothing: over a page's 584,654 coordinates the round trip shifts none of
them by more than 3e-12 points, and `verify_ink.py` renders every page twice — once as
written, once with the source's own path strings dropped back in — and requires the two
bitmaps to be equal. All 604 pages pass. The whole conversion lives in the root matrix and a
per-path translate, and `verify_ink.py` also compares those two transform chains as matrices,
which agree to 2.3e-13 page units.

`pathdata.py` can also *thin* an outline, and this artwork has room for it — the 1422 pages
were set as outlines rather than as a font and carry about 117,000 segments a page against
35,000 for 1441, half of them shorter than a fifth of a raster pixel. Thinning at 0.05 pt
makes a page eight times smaller and moves 0.1% of the edge pixels by at most a fifth of a
grey level. It is off by default and `--tolerance` turns it on; nothing in the shipped
edition used it.

**Identities are transferred, geometry is not.** The two Hafs editions are the same muṣḥaf,
and that is checked rather than assumed: over pages 3–604 they carry the same 6,224 medallions
with no page differing by even one. So which ayah ends where transfers from 1441, and every
polygon's shape is then measured from the 1422 artwork's own ink. `seed_polygons.py` refuses a
page whose medallion count disagrees instead of guessing.

## Running it

```sh
python3 pipeline/convert_ai.py --zip ~/Downloads/hafs_1422.zip --out .work/hafs1422
python3 pipeline/normalize.py       --out mushafs/hafs/kfqc-1422 --pages 1-604
python3 pipeline/verify_ink.py      --pages 3-604
python3 pipeline/seed_polygons.py   --edition hafs/kfqc-1422 --from hafs/kfqc-1441
python3 tools/build_ayah_polygons.py --mushaf hafs/kfqc-1422
python3 pipeline/opening_spread.py  --edition hafs/kfqc-1422 --from hafs/kfqc-1441
python3 tools/add_line_structure.py  --mushaf hafs/kfqc-1422
python3 pipeline/make_variants.py   --edition hafs/kfqc-1422
python3 pipeline/build_indexes.py   --edition hafs/kfqc-1422 --from hafs/kfqc-1441
python3 tools/audit_ayah_polygons.py --mushaf hafs/kfqc-1422
```

`layout.py --fit` re-derives the page map, and `make_variants.py --check` and
`build_indexes.py --check` report without writing. Every step needs `rsvg-convert`, `numpy`,
`Pillow` and `brotli`; the first also needs `inkscape`.
