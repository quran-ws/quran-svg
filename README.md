# Quran SVG — muṣḥaf pages as SVG with per-ayah coordinates

[![License: CC0-1.0](https://img.shields.io/badge/metadata-CC0%201.0-brightgreen.svg)](LICENSE)
[![Pages](https://img.shields.io/badge/pages-3%2C020-blue.svg)](#available-mushafs)
[![Ayah polygons](https://img.shields.io/badge/ayah%20polygons-31%2C118-blue.svg)](#svg--polygon-structure)
[![Qiraat](https://img.shields.io/badge/qiraat-5%20riwayat-orange.svg)](#available-mushafs)

**Free Quran SVG pages for app developers** — the complete 604-page Muṣḥaf al-Madinah as
vector graphics, with a transparent **clickable ayah layer** so you can highlight, tap or
select any verse without doing your own OCR or coordinate work.

<div dir="rtl">

**صفحات المصحف الشريف بصيغة SVG مع إحداثيات الآيات** — مصحف المدينة كاملًا (٦٠٤ صفحات)
رسوميات متجهة، مع طبقة شفافة قابلة للنقر لكل آية، جاهزة لتطبيقات القرآن الكريم.
مجاني ومفتوح المصدر. انظر [نبذة بالعربية](#نبذة-بالعربية).

</div>

Each page is an SVG (plus a Brotli `.svg.br`) whose ayah hit-regions are
`<path class="ayahPolygon" surah=… ayah=… number=…>`. The `json/` folder holds
per-page polygon metadata plus two indexes: `surah.json` and `markers.json`.

## Why this repo

Most Quran page assets are raster images with no verse geometry, so every project
re-solves the same problem: *where on the page is ayah 2:255?* Here that answer ships with
the artwork.

- **Vector, not raster** — sharp at any zoom, dark-mode friendly, small over the wire.
- **Ayah hit-regions included** — a real polygon per verse, not a bounding box guess.
- **Five riwāyāt** — Ḥafṣ, Warsh, Qālūn, al-Dūrī and Shuʿbah, in one consistent layout.
- **Coordinates you can trust** — polygons are derived from each page's own ayah medallions
  and audited against the ink, not hand-placed.
- **CC0 metadata** — the polygon layer and JSON are public domain; build on them commercially
  with no attribution required.

## Use cases

Things people build with this:

- **Quran apps** for iOS, Android, Flutter, React Native or the web — tap an ayah to open
  tafsīr, translation, or audio.
- **Verse highlighting** — follow-along recitation, karaoke-style ayah highlighting, bookmarks.
- **Ayah screenshots and sharing** — crop an exact verse from the printed page.
- **Memorisation (ḥifẓ) tools** — hide, reveal or test a single ayah in place.
- **Research and annotation** — a stable coordinate space for tagging tajwīd, waqf, or
  morphology onto the printed page.
- **Comparing qirāʾāt** — the same page number across five riwāyāt.

## Quick start — download

The full repository is large (every page of five muṣḥafs). Take only what you need.

**One mushaf, latest revision only:**

```sh
git clone --depth 1 --filter=blob:none --sparse https://github.com/quranpedia/quran-svg.git
cd quran-svg
git sparse-checkout set mushafs/hafs/kfqc
```

**A handful of pages, no clone at all:**

```sh
# page 1 of Hafs, and its polygon metadata
curl -O https://raw.githubusercontent.com/quranpedia/quran-svg/main/mushafs/hafs/kfqc/svg/001.svg
curl -O https://raw.githubusercontent.com/quranpedia/quran-svg/main/mushafs/hafs/kfqc/json/001.json
```

**Drop a page straight into a web app:**

```html
<object data="001.svg" type="image/svg+xml" id="page"></object>
<script>
  document.getElementById('page').addEventListener('load', e => {
    e.target.getSVGDocument().querySelectorAll('.ayahPolygon').forEach(p =>
      p.addEventListener('click', () =>
        console.log('surah', p.getAttribute('surah'), 'ayah', p.getAttribute('ayah'))));
  });
</script>
```

## Layout

Folders are organised by **qiraa → publisher**:

```
mushafs/<qiraa>/<publisher>/
├── svg/      001.svg …          vector page text + ayah hit-layer
├── svg-br/   001.svg.br …       Brotli-compressed (serve with Content-Encoding: br)
└── json/     001.json …         per-page polygons
           surah.json            114-surah index (page, juz, names, ayah count)
           markers.json          ayah medallion centres [{page, ayah, x, y}]
```

Pages that contain more than one surah also have surah-specific variants, e.g.
`106-surah4.svg` / `106-surah5.svg`.

## Available mushafs

| Qiraa | Rawi | Publisher | Folder | Pages | Ayah count |
|-------|------|-----------|--------|------:|-----------:|
| ʿAsim | Hafs | King Fahd Complex — KFQC | `hafs/kfqc` | 604 | 6236 |
| Nafiʿ | Warsh | King Fahd Complex — KFQC | `warsh/kfqc` | 604 | 6214 |
| Nafiʿ | Qalun | King Fahd Complex — KFQC | `qalon/kfqc` | 604 | 6214 |
| Abu ʿAmr | Al-Douri | King Fahd Complex — KFQC | `douri/kfqc` | 604 | 6218 |
| ʿAsim | Shuʿbah | King Fahd Complex — KFQC | `shubah/kfqc` | 604 | 6236 |

Spelling varies across sources; these are the same editions you may see written as
Hafs/Ḥafṣ, Warsh/Warch, Qalun/Qaloon/Qālūn, Douri/Duri/al-Dūrī, Shubah/Shuʿbah/Shu'bah,
and qiraat/qira'at/qirāʾāt/recitations. The publisher is the King Fahd Glorious Qur'an
Printing Complex (KFGQPC), i.e. the Madinah Mushaf / Mushaf al-Madinah.

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

### The `polygon` field in `json/NNN.json`

In the SVG, an ayah's hit-region is always SVG path data in `d`. In the JSON it is not: the
`polygon` string ships in **two shapes**, and which one you get depends on the page.

```jsonc
// pages 3–604 — SVG path data, one subpath per line the ayah occupies
"polygon": "M 0.0 0.75 L 337.75 0.75 L 337.75 41.0 L 0.0 41.0 Z M 254.12 41.0 … Z"

// pages 1–2 — a bare `x,y x,y …` point list, no commands
"polygon": "181.08,18.31 57.54,18.31 57.54,48.94 181.08,48.94"
```

Pages 3–604 are generated by `tools/build_ayah_polygons.py`, which builds an ayah out of the
line bands it covers — so an ayah spanning three printed lines is three rectangular subpaths,
and a full-page ayah has as many subpaths as it has lines. The ornate opening spread, pages
1–2, is [out of scope for that generator](tools/README.md) and keeps a single hand-corrected
staircase per ayah, written as a point list.

A parser written against page 1 will produce `NaN` on page 3. Handle both:

```js
// json `polygon` → SVG path data, either shape
function polygonToPath(polygon) {
  if (polygon.trimStart().startsWith('M')) return polygon;   // already path data
  const n = polygon.match(/-?\d+(?:\.\d+)?/g).map(Number);   // "x,y x,y …"
  const pts = [];
  for (let i = 0; i < n.length; i += 2) pts.push(`${n[i]} ${n[i + 1]}`);
  return `M ${pts.join(' L ')} Z`;
}

// json `polygon` → bounding box, either shape
function polygonBBox(polygon) {
  const n = polygon.match(/-?\d+(?:\.\d+)?/g).map(Number);
  const xs = n.filter((_, i) => i % 2 === 0), ys = n.filter((_, i) => i % 2 === 1);
  return { x: Math.min(...xs), y: Math.min(...ys),
           w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
}
```

Pulling every number out and pairing it as `x,y` is safe for a **bounding box**, because the
commands carry no coordinates of their own. It is not safe for an outline: joining the pairs
across subpath boundaries welds separate lines into one ring. To draw the shape, keep the path
data as it is.

## Coordinates & counts

- Coordinates are each mushaf's **native page pixels** (polygons and glyphs share one
  space — no rescaling needed). Every page is 345 × 550 user units at one scale. Pages 3–604
  are `viewBox 0 0 345 550`, except in Qalun and Warsh, whose user space starts at x = −6:
  `viewBox -6 0 345 550`. The opening spread, pages 1–2, is the same 345 × 550 box but keeps
  its own origin — the two facing pages of a mushaf share one, and it differs per mushaf.
  Surah-specific variants keep their page's x-origin and width and crop the height, so read
  the `viewBox` rather than assuming it.
- The **declared box is not the ink**, and on pages 1–2 the gap is wide: page 1's ayah
  polygons span about 222 × 197 units inside its 345 × 550 box, under a quarter of its area,
  so a render that fills the `viewBox` is mostly whitespace. If you are cropping or fitting a
  page rather than laying out the full spread, measure it — the rendered `getBBox()`, or the
  union of the page's polygon bounding boxes — instead of trusting the `viewBox`.
- Ayah counts follow **each mushaf's own medallions** and differ between qiraat
  (and occasionally between editions). The mushaf is authoritative.

## Serving Brotli files

```nginx
location ~ \.svg\.br$  { add_header Content-Encoding br; default_type image/svg+xml; }
location ~ \.json\.br$ { add_header Content-Encoding br; default_type application/json; }
```

## FAQ

**How do I make an ayah clickable on a Quran page?**
Render the SVG inline (or in an `<object>`), give the glyph paths `pointer-events:none`, and
listen for clicks on `.ayahPolygon`. Each polygon carries `surah`, `ayah` and `number`.

**How do I get the coordinates or bounding box of a specific verse?**
Read `mushafs/<qiraa>/<publisher>/json/<page>.json`. Every entry has the ayah's `polygon`
and the centre of its ayah medallion. `surah.json` maps a surah to its starting page.

**Which page is a surah or ayah on?**
`surah.json` gives page, juz, names and ayah count for all 114 surahs. `markers.json` lists
every ayah medallion with its page and position.

**Can I use this commercially / in a paid app?**
Yes. Our polygon layer and JSON are CC0. The KFQC page artwork is free for digital, web,
software and media use worldwide; the only restriction is printing physical muṣḥafs for
commercial sale. See [NOTICE.md](NOTICE.md).

**Can I use it offline?**
Yes — it's static files. Ship the pages you need with your app.

**Why are ayah counts different between the mushafs?**
Because the qirāʾāt genuinely differ in verse division. The counts follow each mushaf's own
medallions rather than being forced to one system. See
[qiraat-ayah-map](https://github.com/quranpedia/qiraat-ayah-map) for mapping between them.

**Is the Quran text itself included as text?**
The pages are vector artwork of the printed muṣḥaf — glyph outlines, not selectable Unicode.
Use the polygons to link a region to a verse identifier, then pull text from a text dataset.

## نبذة بالعربية

<div dir="rtl">

هذا المستودع يوفّر **صفحات المصحف الشريف بصيغة SVG** (رسوميات متجهة) مع **طبقة إحداثيات
لكل آية**، ممّا يتيح للمطوّرين جعل كل آية قابلة للنقر أو التظليل داخل التطبيقات.

**ما الذي يحتويه المستودع؟**

- مصحف المدينة كاملًا — ٦٠٤ صفحات لكل رواية.
- خمس روايات: **حفص، وورش، وقالون، والدوري، وشعبة** عن القرّاء العشرة.
- مضلّع (polygon) لكل آية يحدّد موضعها على الصفحة بدقّة.
- ملفات JSON تتضمّن إحداثيات الآيات، وفهرس السور، ومواضع علامات الآيات.
- نسخ مضغوطة بصيغة Brotli لتسريع التحميل على الويب.

**لمن هذا المشروع؟** لمطوّري **تطبيقات القرآن الكريم** على الويب وأندرويد و iOS، ومشاريع
التحفيظ، وبرامج التلاوة والمتابعة الصوتية، والبحث العلمي في الرسم العثماني.

**الترخيص:** كل ما أنتجناه (طبقة الإحداثيات وملفات JSON) في **الملك العام CC0** — استخدمه
بحرّية تامّة تجاريًا ودون نسب. أمّا رسوم صفحات المصحف فهي من إصدارات مجمع الملك فهد لطباعة
المصحف الشريف، ويُسمح باستخدامها مجانًا في الأغراض الرقمية والبرمجية والإعلامية، والقيد
الوحيد هو طباعة المصاحف الورقية لغرض البيع التجاري. راجع [NOTICE.md](NOTICE.md).

**كلمات مفتاحية:** تحميل مصحف SVG، إحداثيات الآيات، مصحف المدينة، القرآن الكريم للمطورين،
تطبيقات القرآن، تظليل الآية، بيانات القرآن مفتوحة المصدر، رواية حفص عن عاصم، رواية ورش عن نافع.

</div>

## Related projects

- **[qiraat-ayah-map](https://github.com/quranpedia/qiraat-ayah-map)** — maps ayah numbers
  between the six canonical counting systems used by the ten qirāʾāt.
- **[tajweed-engine](https://github.com/quranpedia/tajweed-engine)** — rule-driven tajwīd
  engine over Uthmani text, with a scholar-authored rule corpus.
- **[qurantech-skill](https://github.com/quranpedia/qurantech-skill)** — agent skill for
  building Quran apps: muṣḥaf display, qirāʾāt, tajwīd, audio, search, ḥifẓ and adab rules
  for handling sacred text.

Contributions and corrections are welcome — please open an issue if you find a page or a
polygon that is wrong.

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
