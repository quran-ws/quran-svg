#!/usr/bin/env python3
"""The editions this repository ships, and where their files live.

An *edition* is ``<riwaya>/<publisher>`` -- the folder pair under ``mushafs/``.  The
publisher segment carries the printing year where a publisher has given us more than one:
the King Fahd Complex's Hafs muṣḥaf is here twice, as ``kfqc-1441`` and ``kfqc-1422``, and
they are different artwork for the same 604 pages, not different data about one artwork.

Everything that used to hard-code ``"kfqc"`` goes through here, so adding an edition is a
line in ``EDITIONS`` and nothing else.
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSHAFS = os.path.join(ROOT, "mushafs")

EDITIONS = (
    "douri/kfqc",
    "hafs/kfqc-1422",
    "hafs/kfqc-1441",
    "qalon/kfqc",
    "shubah/kfqc",
    "warsh/kfqc",
)

DEFAULT = "hafs/kfqc-1441"          # the edition the word-level tools work on


def riwaya(edition):
    """``'hafs/kfqc-1441'`` -> ``'hafs'``: which reading the edition transmits."""
    return edition.split("/")[0]


def base(edition):
    return os.path.join(MUSHAFS, edition)


def page_path(edition, page, kind="svg", ext="svg", stem=None):
    """A page file, or a surah crop of one when ``stem`` is given."""
    stem = stem or "%03d" % page
    return os.path.join(MUSHAFS, edition, kind, "%s.%s" % (stem, ext))


def index_path(edition, name):
    """``surah.json`` or ``markers.json``."""
    return os.path.join(MUSHAFS, edition, "json", name)


def resolve(selector):
    """Editions named by a comma-separated selector.

    A selector may be a full edition (``hafs/kfqc-1441``), a riwaya (``hafs``, which is both
    Hafs editions), or a prefix of one.  An unknown name is an error rather than an empty
    run, which is how a typo used to become a silent no-op.
    """
    if not selector:
        return list(EDITIONS)
    out = []
    for part in selector.split(","):
        part = part.strip().strip("/")
        hit = [e for e in EDITIONS if e == part or e.startswith(part + "/")
               or e.split("/")[1].startswith(part) and e.split("/")[0] == part.split("/")[0]]
        if not hit:
            hit = [e for e in EDITIONS if e.startswith(part)]
        if not hit:
            raise KeyError("unknown edition %r; known: %s" % (part, ", ".join(EDITIONS)))
        out.extend(e for e in hit if e not in out)
    return out


def existing(selector=None):
    """Only the editions that actually have a ``svg/`` folder on disk."""
    return [e for e in resolve(selector) if os.path.isdir(os.path.join(MUSHAFS, e, "svg"))]
