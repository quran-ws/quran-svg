# Getting the files without cloning 5 GB

The artwork is the bulk of this repository, and most consumers want one muṣḥaf,
or one page. Three ways, cheapest first. Only the third needs `git` at all.

## One page

```sh
curl -O https://raw.githubusercontent.com/quran-ws/quran-svg/main/mushafs/hafs/kfqc/svg/001.svg
```

The path is `mushafs/<riwayah>/<edition>/svg/<page>.svg`, zero-padded to three
digits. `svg-br/` beside it holds the same pages Brotli-compressed — 72 MB
against 414 MB for Ḥafṣ — and `json/` holds the ayah polygon layer, which is
what [`FORMAT.md`](FORMAT.md) describes.

Pin a commit rather than `main` if you need the bytes to stay put. Releases
also carry per-muṣḥaf archives — `<riwayah>-kfqc-svg.zip` and
`<riwayah>-kfqc-svg-br.zip` — so a release tag is a pin too, and the cheapest
way to take one muṣḥaf whole without `git`.

## One muṣḥaf

**Do not plain-`git clone` for this.** The pack is 5.29 GiB, and nearly all of it
is artwork for muṣḥafs you did not ask for:

```sh
$ git count-objects -vH
size-pack: 5.29 GiB
```

Ask for one directory instead:

```sh
git clone --depth 1 --filter=blob:none --sparse https://github.com/quran-ws/quran-svg.git
cd quran-svg && git sparse-checkout set mushafs/hafs/kfqc
```

Measured on a home connection, 2026-09-12: **7 seconds**, 684 MB on disk — 194 MB
of `.git` and 490 MB of files, of which `svg/` is 414 MB, `svg-br/` 72 MB and
`json/` 3.7 MB. `--filter=blob:none` is what does the work: file contents are
fetched only for the paths you check out, so the muṣḥafs you did not name never
arrive.

Narrow it further if you only want the compressed pages and the polygons:

```sh
git sparse-checkout set mushafs/hafs/kfqc/svg-br mushafs/hafs/kfqc/json
```

Add another muṣḥaf later with `git sparse-checkout add mushafs/warsh/kfqc` — it
fetches only the new directory.

## All of it

```sh
git clone https://github.com/quran-ws/quran-svg.git
```

5.29 GiB, plus the working tree on top. Worth it to work *on* this repository,
not to read from it.

## What is where

Every riwayah has the same three directories under `mushafs/<riwayah>/kfqc/`:

| | |
|---|---|
| `svg/` | one SVG per page |
| `svg-br/` | the same pages, Brotli-compressed |
| `json/` | the ayah polygon layer — [`FORMAT.md`](FORMAT.md) |

Five riwāyāt ship: `douri`, `hafs`, `qalon`, `shubah`, `warsh`. Their page
numbering is **not** interchangeable, and neither are their ayah numbers — an
ayah's page in one is not its page in another. See
[quran.ws/docs/concepts/ayah-counting](https://quran.ws/docs/concepts/ayah-counting).
