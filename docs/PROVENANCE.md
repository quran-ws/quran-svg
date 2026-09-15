# Where the artwork came from

Every muṣḥaf in `mushafs/` is traced from one Adobe Illustrator bundle published by
the King Fahd Glorious Qur'an Printing Complex under the name *المصحف الرقمي —
الملفات المصدرية* (Digital Mushaf master files). Each bundle holds exactly 604 `.ai`
files, one per page, and each is the ancestor of one directory here.

| edition here | source archive | size | SHA-256 |
|---|---|---|---|
| `mushafs/hafs/kfqc` | `1441-AI-hafs.zip` — 1441H, Ḥafṣ | 466,430,736 B (444.82 MB) | `280c5d71ca16aaeeb3a343be1b92c76fa6df71d0671e202c026fde12402d9eef` |
| `mushafs/warsh/kfqc` | `1442-ai-warsh.zip` — 1442H, Warsh | 417,437,136 B (398.10 MB) | `2a0c65131dac5a922502fb4740034fb4ffc57792a0b6e5c1cc34c5a3339dd5d7` |
| `mushafs/qalon/kfqc` | `1443-qalon.zip` — 1443H, Qālūn | 551,792,593 B (526.23 MB) | `08ebd0b0ecbc5822da1eaa13a77e93a920383ee652a3b72bec09ec59de35f2da` |
| `mushafs/shubah/kfqc` | `1443-shubah.zip` — 1443H, Shuʿbah | 543,538,523 B (518.36 MB) | `a788777b56a1784ab8aecd042fc0149e4e96a019450a24f586a4552d0d2dd426` |
| `mushafs/douri/kfqc` | `Douri-1443.zip` — 1443H, al-Dūrī | 482,791,633 B (460.43 MB) | `f43a49555fd8c63774725e670a16c002a6024e40ad5601c8adc72846ca581c85` |

The al-Dūrī bundle carries `Last-Modified: Tue, 08 Feb 2022 10:35:43 GMT` on the KFQC
server and its pages are named `Douri-1443/001___douri__DM.ai` … `604___douri__DM.ai`.

## How to get them

The original download host answers **from inside Saudi Arabia only**:

```
https://dm.qurancomplex.gov.sa/Download/Douri-1443.zip
```

From anywhere else that request hangs rather than failing, which reads like a dead
link and is not one. Four of the five bundles have since been removed from
`dm.qurancomplex.gov.sa` altogether. Use the mirror, which is the practical access
route and is byte-identical to the original — check it against the SHA-256 above:

```sh
curl -O https://cdn.quran.ws/KFGQPC/resources/dm/douri-1443/Douri-1443.zip
shasum -a 256 Douri-1443.zip
```

The mirror, its metadata and the digests for every KFQC resource live in
[quran-ws/kfgqpc-resources](https://github.com/quran-ws/kfgqpc-resources)
([browse](https://quran-ws.github.io/kfgqpc-resources/)). The al-Dūrī copy there was
recovered from the Wayback Machine after KFQC removed the file.

## What was checked

For al-Dūrī, pages 50 and 300 were extracted from `Douri-1443.zip`, rendered, and
compared against `mushafs/douri/kfqc/svg/050.svg` and `300.svg`: same text, same
words, same line breaks, same fifteen lines, same page numbering. The shipped SVG is
not a pixel copy of the `.ai` page — the decorative frame, the running header and the
printed page number are dropped, the page is re-cropped to the text block, and the
ayah markers are redrawn — but the type itself is the same artwork.

For the other four, only structure was checked: 604 `.ai` pages each, named for the
matching riwāyah. Nobody has run a geometry diff on them.

## What this file does not settle

`mushafs/douri/kfqc/json/markers.json` is a flat list of **6218** entries, while
`quran-text` measures the same riwāyah at **6217**. That disagreement is about the
ayah layer, not the artwork, and is open — see issue #21.
