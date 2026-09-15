# NOTICE — Sources, Attribution & Usage Terms

This repository contains vector (SVG) renderings of Qur'an muṣḥaf pages together with a
transparent, clickable ayah‑polygon layer and per‑page JSON metadata. Please read the
following before using the material.

**In one line:** everything *we* made is CC BY 4.0, with attribution waived when you use
it inside a product; the muṣḥaf page artwork belongs to its publishers, whose terms are
permissive and set out below.

`LICENSE` holds the standard Quran.ws notice. It covers **our** contribution only — the
scope is spelled out in §3, and the publishers' terms for the artwork are in §2.

## 1. The Qur'anic text itself

The text of the Holy Qur'an (the ʿUthmānī rasm) is the revealed Word of Allah. It is **not
subject to copyright** and may be freely reproduced. However, it **must never be altered,
truncated, or misrepresented**, and it must be handled with the respect (ḥurmah) due to it
under Islamic rulings.

## 2. Source editions & their terms

The mushaf pages are derived from the following publishers' editions. All rights in the
original editions remain with their respective publishers.

### 2.1 King Fahd Glorious Qur'an Printing Complex (KFQC) — مجمع الملك فهد لطباعة المصحف الشريف
Covers: `hafs/kfqc`, `warsh/kfqc`, `qalon/kfqc`, `douri/kfqc`, `shubah/kfqc`.

The Complex publishes a **complete free digital copy** of Muṣḥaf al‑Madinah (as Adobe
Illustrator files, PDF, high‑quality images, and a TrueType font). Per the Complex's stated
usage rights:

> Based on the approval of His Excellency the Minister of Islamic Affairs, Daʿwah and
> Guidance, General Supervisor of the King Fahd Qur'an Printing Complex — the Complex is
> honored to present to the Muslim public a complete free digital copy of Muṣḥaf al‑Madinah.
> These formats **can be used for free** in all personal and individual businesses, in works
> of governmental departments & agencies, in the publications of both private and national
> institutions; it also allows **Qur'an printing\***, **digital publishing**, **media use**,
> and use in **websites, software, and other similar intermediates**.
>
> \* The printing of the Qur'an inside the Kingdom and importing it from abroad **for the
> purpose of commercial sale** is subject to Royal Decree No. 136/8 (1/2/1406 AH) and Royal
> Decree No. 9/B/46356 (28/9/1424 AH), which prohibit printing the Qur'an inside the Kingdom
> anywhere other than the King Fahd Glorious Qur'an Printing Complex, and prohibit importing
> it from abroad for the purpose of commercial sale.

The exact bundle behind each edition here — filename, size and SHA-256 — is recorded in
[`docs/PROVENANCE.md`](docs/PROVENANCE.md).

**In practice:** free for essentially every personal, commercial, governmental, digital,
media, web, and software use — worldwide. The **only** restriction is the physical
**print‑for‑commercial‑sale** trade of muṣḥafs, which is reserved to the Complex.
Source: <https://qurancomplex.gov.sa>.

### 2.2 Libyan Ministry of Endowments (Awqāf) — the Libyan Qālūn edition

Free for **non‑commercial** use only; commercial use requires prior approval from the
Libyan Ministry of Endowments (Awqāf). No such edition is published in this repository
today — the five editions above are all KFQC — but the term is recorded here so it travels
with the project if that artwork is ever added.

## 3. This repository's own contribution — CC BY 4.0, attribution waived in products

Everything **we** authored — the ayah‑polygon hit‑layer, the JSON metadata (per‑page
polygons, `surah.json`, `markers.json` — the per‑riwaya ayah counts, ayah↔page mapping, and
hit‑region coordinates), and the repository structure — is **CC BY 4.0**, and `tools/` is
**MIT** (see `LICENSE`). Reuse it freely, including commercially.

Attribution is **waived** when the material is used inside an application, website,
service, API, bot, tool, research work or product, free or commercial. It is asked for when
the data itself is republished as a resource in its own right, so that a path stays open
from every copy back to its corrections and later releases.

## 4. Disclaimer

The material is provided "as is", for the service of the Book of Allah. If you find any error
in a page or its metadata, please open an issue so it can be corrected promptly.
