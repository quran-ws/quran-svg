# Quran SVG

High-quality Quran **SVG pages** with a transparent, clickable **ayah-polygon** layer,
across multiple qiraat and publishers.

Each page is an SVG (plus a Brotli `.svg.br`) whose ayah hit-regions are
`<path class="ayahPolygon" surah=… ayah=… number=…>`. The `json/` folder holds
per-page polygon metadata plus two indexes: `surah.json` and `markers.json`.

## Layout

Folders are organised by **qiraa → publisher**, where the publisher segment carries the
printing year when we hold more than one edition from the same publisher:

```
mushafs/<qiraa>/<publisher>/
├── svg/      001.svg …          vector page text + ayah hit-layer
├── svg-br/   001.svg.br …       Brotli-compressed (serve with Content-Encoding: br)
└── json/     001.json …         per-page polygons
           surah.json            114-surah index (page, juz, names, ayah count)
           markers.json          ayah medallion centres [{page, ayah, x, y}]
```

Some editions also carry `lines/NNN.json`, the fifteen line bands of each page.

Pages that contain more than one surah also have surah-specific variants, e.g.
`106-surah4.svg` / `106-surah5.svg`.

## Available mushafs

| Qiraa | Rawi | Publisher | Folder | Pages | Ayah count |
|-------|------|-----------|--------|------:|-----------:|
| ʿAsim | Hafs | KFQC, 1441 AH | `hafs/kfqc-1441` | 604 | 6236 |
| ʿAsim | Hafs | KFQC, 1422 AH | `hafs/kfqc-1422` | 604 | 6236 |
| ʿAsim | Hafs | KFQC, 1422 AH — re-fitted, *under testing* | `hafs/kfqc-1422-optimized` | 604 | 6236 |
| Nafiʿ | Warsh | King Fahd Complex — KFQC | `warsh/kfqc` | 604 | 6214 |
| Nafiʿ | Qalun | King Fahd Complex — KFQC | `qalon/kfqc` | 604 | 6214 |
| Abu ʿAmr | Al-Douri | King Fahd Complex — KFQC | `douri/kfqc` | 604 | 6205 |
| ʿAsim | Shuʿbah | King Fahd Complex — KFQC | `shubah/kfqc` | 604 | 6236 |

### The two Hafs editions

The King Fahd Complex has printed the Madani muṣḥaf more than once, and we carry two of its
Ḥafṣ editions. They are the same muṣḥaf — 604 pages, fifteen lines, the same page and line
breaks, the same 6,236 ayat, and the same ayah ending on the same page throughout — but they
are **different artwork**, and they differ in ways you can see:

* the ayah marker is the ۝ rosette in 1441 and a plain disc in 1422;
* where an ayah ends exactly at a line's end, 1422 often sets the medallion at the head of
  the next line, so about 5% of markers sit a line lower and to the right of 1441's;
* the letterforms are drawn differently, 1422's being the heavier.

Both are mapped into the same `345 × 550` page window, so a reader can swap editions and the
text stays where it was. `hafs/kfqc` was renamed to `hafs/kfqc-1441` when the second arrived.

### `hafs/kfqc-1422-optimized`

The 1422 edition was not set from a font: its letterforms are traced outlines, described far
more finely than they are drawn — about 117,000 segments a page against 21,000 in 1441 — so
its pages are roughly six times the size of the others and look faceted at high
magnification. `hafs/kfqc-1422-optimized` is that edition with the outlines re-fitted: cubic
curves fitted to the shape the trace describes, corners kept, dots and diacritics left alone,
and no contour allowed to move into a neighbour. It is about a fifth of the size.

**It is still under testing, and `hafs/kfqc-1422` remains the reference** — that one is the
publisher's artwork exactly, verified path for path. See
[`mushafs/hafs/kfqc-1422-optimized/README.md`](mushafs/hafs/kfqc-1422-optimized/README.md)
for the settings, what was measured, and what has not been checked yet.

## SVG & polygon structure

```xml
<path class="ayahPolygon" id="verse-12" number="002005" surah="2" ayah="5"
      d="M …" fill-opacity="0"/>
```

- `id` — `verse-N`, a global running ayah index over the whole mushaf.
- `number` — `SSSAAA` (surah×1000 + ayah, zero-padded).
- Polygons render first (transparent); page glyphs render on top. Suggested CSS:

```css
.ayahPolygon { fill-opacity: 0; cursor: pointer; }
.ayahPolygon:hover { fill: #f5e6a3; fill-opacity: .5; }
```

Give the glyph paths `pointer-events:none` so the lower polygons receive clicks.

## Coordinates & counts

- Every KFQC edition here shares one `345 × 550` page space, including both Hafs editions.
- Coordinates are each mushaf's **native page pixels** (polygons and glyphs share one
  space — no rescaling needed). Pages 3–604 are `viewBox 0 0 345 550`, except in Qalun and
  Warsh, whose user space starts at x = −6: `viewBox -6 0 345 550`. The opening spread,
  pages 1–2, is `235 235`. Surah-specific variants keep their page's x-origin and width and
  crop the height, so read the `viewBox` rather than assuming it.
- Ayah counts follow **each mushaf's own medallions** and differ between qiraat
  (and occasionally between editions). The mushaf is authoritative.

## Serving Brotli files

```nginx
location ~ \.svg\.br$  { add_header Content-Encoding br; default_type image/svg+xml; }
location ~ \.json\.br$ { add_header Content-Encoding br; default_type application/json; }
```

## License & usage

- **Our own contribution** — the ayah-polygon overlay, the JSON metadata (`mushafs/**/json/` —
  per-page polygons, `surah.json`, `markers.json`), and the repo structure/tooling — is
  **[CC0 1.0](LICENSE)** (public domain): reuse freely, including commercially, no attribution
  required. This is the clean base to build a shared Qur'anic-data standard on.
- **King Fahd Complex editions** (Ḥafṣ, Warsh, Qālūn, Al-Dūrī, Shuʿbah — the `*/kfqc` folders):
  the Complex grants **free use** of its digital Muṣḥaf al-Madinah for personal, business,
  governmental, institutional, printing, digital-publishing, media, website, and software use,
  **worldwide**. The **only** restriction is that **printing physical muṣḥafs for commercial
  sale** is reserved to the Complex (Saudi Royal Decrees). So: free for essentially any
  digital/app/web use — you just can't use it to print-and-sell physical muṣḥafs.
- **The Qur'anic text itself** is not subject to copyright and may be freely reproduced, but
  must never be altered and its sanctity must be preserved.

See **[NOTICE.md](NOTICE.md)** for full source attribution and the publishers' exact terms.
