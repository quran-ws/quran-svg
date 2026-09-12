<div align="center">

<img src=".github/banner.svg" alt="Quran SVG — Pages & Assets, Stable" width="820">

**Vector Mushaf pages in SVG, with the position of every ayah mapped on the page.**

<a href="https://quran.ws/blocks/quran-svg"><img alt="See it work" src="https://img.shields.io/badge/See_it_work-15705D?style=for-the-badge&labelColor=102F29"></a>
<a href="https://quran.ws/docs/reference/quran-svg"><img alt="Documentation" src="https://img.shields.io/badge/Documentation-102F29?style=for-the-badge&labelColor=102F29"></a>

</div>

Use it when you want to display printed Mushaf pages in a website or application and make individual ayahs selectable or connect them to recitation, Tafsir, and other features.

> صفحات مصاحف جاهزة بصيغة SVG، مع إحداثيات كل آية داخل الصفحة.
>
> استخدمه عندما تريد عرض صفحة المصحف كما هي في موقع أو تطبيق، مع إمكانية تحديد الآيات وربطها بالتلاوة أو التفسير أو غيرها من وظائف التطبيق.

| | |
|---|---|
| **Riwayat** | 5 |
| **Ayah polygons** | 31,118 |
| **Licence** | CC BY 4.0 for the metadata and polygon layer, MIT for `tools/`; attribution waived for use inside a product |

```sh
# one page
curl -O https://raw.githubusercontent.com/quran-ws/quran-svg/main/mushafs/hafs/kfqc/svg/001.svg

# one whole mushaf, without the 5.29 GiB a plain `git clone` fetches
git clone --depth 1 --filter=blob:none --sparse https://github.com/quran-ws/quran-svg.git
cd quran-svg && git sparse-checkout set mushafs/hafs/kfqc
```

## Where the documentation is

Everything about using it lives on the site. This repository is the source.

| | |
|---|---|
| **Overview and demo** | [quran.ws/blocks/quran-svg](https://quran.ws/blocks/quran-svg) |
| **Reference** | [quran.ws/docs/reference/quran-svg](https://quran.ws/docs/reference/quran-svg) |
| **Display a complete Muṣḥaf page** | [quran.ws/docs/build/display-page](https://quran.ws/docs/build/display-page) |
| **Highlight an ayah** | [quran.ws/docs/build/highlight-ayah](https://quran.ws/docs/build/highlight-ayah) |
| **Work offline** | [quran.ws/docs/build/offline](https://quran.ws/docs/build/offline) |
| **Licensing in full** | [quran.ws/docs/reference/licensing](https://quran.ws/docs/reference/licensing) |

## What is in here

| | |
|---|---|
| `mushafs/` | the artwork and the ayah polygon layer, one directory per muṣḥaf |
| `tools/` | how the polygon layer is built and audited |
| `docs/` | [how the polygon layer ships](docs/FORMAT.md) — stacking order, the two `polygon` shapes, the opening spread · [getting the files](docs/GETTING-THE-FILES.md) — what to fetch, and what not to clone |

Issues and pull requests are welcome here. Everything that is not about *changing* this repository is on the site.
