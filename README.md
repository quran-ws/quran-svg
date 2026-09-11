# Quran SVG

The printed Qur'ān, page by page, as vector artwork — with a transparent clickable layer that already knows where every verse sits.

| Package | Version | Muṣḥafs | Ayah polygons |
|---|---|---|---|
| not published yet — read the files from the repository | `v1.0.0` (2026-08-31) | 5, each 604 pages | 31,118 |

<div dir="rtl">

**صفحات المصحف الشريف بصيغة SVG مع إحداثيات الآيات** — مصحف المدينة كاملًا (٦٠٤ صفحات)
رسوميات متجهة، مع طبقة شفافة قابلة للنقر لكل آية، جاهزة لتطبيقات القرآن الكريم.

</div>

A **muṣḥaf** is one publisher's printed edition of the Qur'ān — its own typesetting, its own page
breaks ([glossary](https://quran.ws/docs/concepts/glossary/#mushaf)). Most Qur'ān page assets are
images with no geometry in them, so every project re-solves the same problem: *where on this page is
verse 2:255?* Here the answer ships inside the artwork.

This repository is the **archive**: every muṣḥaf that has been vectorised lives here, and it grows
when a new one is contributed. It is not a staging area for anything else.

## What it provides

- **604 pages of Muṣḥaf al-Madinah, vectorised, in five readings** — Ḥafṣ, Warsh, Qālūn, al-Dūrī and
  Shuʿbah. Vector, so sharp at any zoom and recolourable.
- **A real polygon for every verse**, carried in the page file itself as
  `<path class="ayahPolygon" surah="2" ayah="255" …>`. Derived from each page's own end-of-verse
  medallions and audited against the ink — not a bounding-box guess.
- **Per-page JSON** with the same geometry outside the artwork, plus a 114-surah index
  (`surah.json`) and every medallion centre in the muṣḥaf (`markers.json`).
- **A Brotli copy of every page** (`svg-br/`), for serving over the wire.

An ayah is the finest thing you can address here. There is no word layer and no letter layer in
these files.

## Use it when you need

- The simplest thing that works: drop a page in, tap a verse, no library and no build step.
- A muṣḥaf that has not been split into smaller shapes — most of them.
- Follow-along recitation, bookmarking, verse screenshots, ḥifẓ (memorisation) drills, or comparing
  the same reading across five printings.
- Static files you can bundle and run offline.

## Not for

| If you need | Use |
|---|---|
| A word or a mark as its own shape — these pages carry a verse layer only | [Quran SVG Elements](https://quran.ws/blocks/quran-svg-elements/), on the muṣḥafs that have been split |
| A whole muṣḥaf scrolling on a phone, where SVG of this size stops performing | [Quran Engine](https://quran.ws/blocks/quran-engine/) |
| Text you can search, select or copy — these pages are glyph outlines, not characters | [Quran Text](https://quran.ws/blocks/quran-text/) |
| Ornaments, surah headers and frames to typeset a page of your own | [Quran Assets](https://quran.ws/blocks/quran-assets/) |

Splitting a muṣḥaf into words and marks is hard work, and not every muṣḥaf here will ever be split.
For those, this repository is the whole answer, which is why it is the archive rather than a first
step towards something else.

## See it work

**<https://quran.ws/blocks/quran-svg/>** — three demos that fetch these files live from this
repository, over open CORS, with no proxy and no copy:

1. **Page viewer** — any page 1–604 in any of the five muṣḥafs; click a verse and read back its
   reference. Switch riwayah and the verse under your cursor changes, because the same page number
   is a different printed page in each.
2. **Find the page** — enter a reference, watch a binary search over the per-page JSON settle on the
   page in about six requests.
3. **Crop a verse** — take one polygon and cut that verse out of the printed page.

## Supported muṣḥafs

Verse totals are each muṣḥaf's own end-of-verse medallions, summed from its `surah.json`. They
differ between readings because the readings genuinely divide the text differently.

| Reading (riwayah) | Qirāʾah | Folder | Pages | Ayat |
|---|---|---|---:|---:|
| Ḥafṣ | ʿĀṣim | `mushafs/hafs/kfqc` | 604 | 6,236 |
| Warsh | Nāfiʿ | `mushafs/warsh/kfqc` | 604 | 6,214 |
| Qālūn | Nāfiʿ | `mushafs/qalon/kfqc` | 604 | 6,214 |
| al-Dūrī | Abū ʿAmr | `mushafs/douri/kfqc` | 604 | 6,218 |
| Shuʿbah | ʿĀṣim | `mushafs/shubah/kfqc` | 604 | 6,236 |

A *riwayah* is one transmitter's version of a reading of the Qur'ān
([glossary](https://quran.ws/docs/concepts/glossary/#riwayah)). **Never assume one muṣḥaf's page
number or verse count applies to another** — store the muṣḥaf key with every page number you save.
To map a reference between counting systems, use
[qiraat-ayah-map](https://github.com/quran-ws/qiraat-ayah-map).

## Provenance

| | |
|---|---|
| Source edition | King Fahd Glorious Qur'ān Printing Complex (KFGQPC), Muṣḥaf al-Madinah — the publisher's own vector edition, not a trace of a scan |
| Publisher folder | `kfqc` for all five muṣḥafs |
| Release | `v1.0.0`, 2026-08-31 — no release assets, so consumers pin a commit or the tag |
| Digest | none published per muṣḥaf; verify by pinning a ref |
| How the verse layer is made | Generated from each page's printed end-of-verse medallions and its line grid, then audited against the ink (`tools/`) |

Every polygon accounts for exactly one verse. Counted over all 604 Ḥafṣ page files:

```console
$ node -e 'let n=0,s=new Set();for(let i=1;i<=604;i++){const p=String(i).padStart(3,"0");
  for(const e of require(`./mushafs/hafs/kfqc/json/${p}.json`)){n++;s.add(e.surahNumber+":"+e.ayahNumber)}}
  console.log(n,"polygons,",s.size,"distinct ayat")'
6236 polygons, 6236 distinct ayat
```

## Quick start

There is no package to install. These are static files; take the pages you need.

```sh
# one page of Ḥafṣ, and its polygon metadata
curl -O https://raw.githubusercontent.com/quran-ws/quran-svg/main/mushafs/hafs/kfqc/svg/003.svg
curl -O https://raw.githubusercontent.com/quran-ws/quran-svg/main/mushafs/hafs/kfqc/json/003.json
```

```html
<style>
  #page path:not(.ayahPolygon) { pointer-events: none; }
  .ayahPolygon { fill: #15705D; fill-opacity: 0; cursor: pointer; }
  .ayahPolygon:hover { fill-opacity: .25; }
</style>
<div id="page"></div>

<script>
  fetch("003.svg").then(r => r.text()).then(svg => {
    page.innerHTML = svg;                        // inline, so CSS and events reach the paths
    page.querySelectorAll(".ayahPolygon").forEach(p =>
      p.onclick = () => console.log(p.getAttribute("surah") + ":" + p.getAttribute("ayah")));
  });
</script>
```

Clicking the third verse on that page logs `2:8`. That is the whole integration.

One whole muṣḥaf, without pulling the ~5 GB repository:

```sh
git clone --depth 1 --filter=blob:none --sparse https://github.com/quran-ws/quran-svg.git
cd quran-svg && git sparse-checkout set mushafs/hafs/kfqc
```

### Four things worth knowing before you build

1. **Set `pointer-events: none` on the glyph paths.** The polygon layer is drawn *after* the glyphs
   in Ḥafṣ, so it is already on top there, but *before* them in Warsh, Qālūn, al-Dūrī and Shuʿbah,
   where glyphs swallow some clicks. The one CSS rule above makes hit-testing behave the same in all
   five.
2. **Identify a verse from `surah` and `ayah`, never from the `id`.** `id="verse-N"` is a running
   index, and its origin is not the same in every muṣḥaf: page 1 of Ḥafṣ starts at `verse-1`, but
   page 1 of Warsh starts at `verse-18709` and page 1 of Shuʿbah at `verse-49797`. The `surah` and
   `ayah` attributes are correct everywhere.
3. **The JSON `polygon` field has two shapes.** Pages 1–2 hold a bare points list
   (`"181.08,18.31 57.54,18.31 …"`); pages 3–604 and the surah variants hold SVG path data
   (`"M 0.0 0.75 L 337.75 0.75 …"`). A parser written for one returns `NaN` on the other, silently.
   Pulling every number out and pairing them handles both, because every coordinate is x then y:

   ```js
   const n = (entry.polygon.match(/-?\d+(\.\d+)?/g) || []).map(Number);
   const xs = n.filter((_, i) => i % 2 === 0), ys = n.filter((_, i) => i % 2 === 1);
   const box = { x: Math.min(...xs), y: Math.min(...ys),
                 w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
   ```

   A polygon is usually several rectangles, because a verse runs over more than one printed line.
4. **Read the `viewBox`; do not assume it.** Pages 3–604 are `0 0 345 550`, except Warsh and Qālūn,
   which start at `x = −6`. Pages 1 and 2 are the two halves of an opening spread and keep the
   spread's own origin, which differs per muṣḥaf — the artwork fills about a third of the declared
   box, so fit it with `getBBox()` before first paint if you render those pages alone.

### `markers.json`, and what its `ayah` field is not

`markers.json` lists every end-of-verse medallion in a muṣḥaf as `{ page, ayah, x, y }`. **`ayah` is
the running index of the verse over the whole muṣḥaf, not the verse number within its surah**, and
there is no `surah` field. Reading it as a verse number returns a plausible, wrong page:

```console
$ node -e 'console.log(require("./markers.json").filter(e => e.page === 3).slice(0,1))'
[ { page: 3, ayah: 13, x: 265.17, y: 64.11 } ]     # this is 2:6, not 2:13
```

To answer "which page is 2:255 on", either convert the reference to a running index first using the
cumulative `ayahCount` in `surah.json`, or skip the 598 KB index and binary-search the per-page JSON
between the surah's first page and the next surah's — those files are 132 to 6,039 bytes, and any
reference in the muṣḥaf settles in about six requests. That is what the demo does.

### Layout

```
mushafs/<riwayah>/<publisher>/
├── svg/      001.svg …      604 pages + 118 surah-specific variants (106-surah4.svg)
├── svg-br/   001.svg.br …   the same, Brotli — serve with Content-Encoding: br
└── json/     001.json …     one entry per verse on the page: surahNumber, ayahNumber, x, y, polygon
           surah.json        all 114 surahs: starting page, juz, names, ayah count
           markers.json      every medallion in the muṣḥaf: { page, ayah, x, y }
```

Page 1 of Ḥafṣ is 196,304 bytes as SVG and 32,707 as `.svg.br`.

```nginx
location ~ \.svg\.br$ { add_header Content-Encoding br; default_type image/svg+xml; }
```

## Works with

| | |
|---|---|
| [Quran Engine](https://quran.ws/blocks/quran-engine/) | Renders these pages on phones, where SVG of this weight does not perform |
| [Quran Text](https://quran.ws/blocks/quran-text/) | The words of the verse you just tapped, as text |
| [Quran Assets](https://quran.ws/blocks/quran-assets/) | Headers, medallions and frames if you are building a page of your own |
| [qiraat-ayah-map](https://github.com/quran-ws/qiraat-ayah-map) | Moves a reference between the counting systems these five muṣḥafs use |
| [quran-tajweed](https://github.com/quran-ws/quran-tajweed) | Recitation-rule annotations to colour over the text |

## Documentation

- **Reference** — <https://quran.ws/docs/reference/quran-svg/>: the full field-by-field account,
  including the traps above with worked examples.
- **Ayah-counting systems** — <https://quran.ws/docs/concepts/ayah-counting/>: why the five muṣḥafs
  disagree about how many verses there are.
- **Glossary** — <https://quran.ws/docs/concepts/glossary/>: muṣḥaf, riwayah, qirāʾah, ayah marker.
- `tools/README.md` — how the verse layer is generated and audited, and what the audit does *not*
  prove.

Corrections are welcome. Polygons are derived rather than hand-placed, so a wrong one is a bug worth
an issue. New vectorised muṣḥafs belong here too.

## Licence

| What | Terms |
|---|---|
| `mushafs/` — the verse-polygon layer, the JSON and the page files as published here | **CC0 1.0** — public domain. No attribution required, though a link back helps people find corrections |
| `tools/` | CC0 1.0 |
| The page artwork, as the publisher's | KFGQPC terms: free worldwide for digital, web, software and media use. The one restriction is printing physical muṣḥafs for commercial sale |
| The Qur'ānic text itself | Not subject to copyright. It must never be altered, truncated or misrepresented |

Full terms and source attribution are in [`LICENSE`](LICENSE) and [`NOTICE.md`](NOTICE.md).
