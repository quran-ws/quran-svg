#!/usr/bin/env python3
"""Reading the raw Inkscape conversion of a KFGQPC Illustrator page.

``convert_ai.py`` turns each ``NNN.ai`` into a plain SVG whose top-level groups are the
Illustrator layers, named by Inkscape after the PDF's optional-content groups:

    layer-MC0  Header & Page No.     the surah name and folio number
    layer-MC1  Marks                 the juz / hizb ornaments printed in the outer margin
    layer-MC2  Border                the printed frame
    layer-MC3  Aya_Number            one ۝ rosette plus one numeral per ayah end
    layer-MC4  Quran_TEXT            the body

Only ``Aya_Number`` and ``Quran_TEXT`` survive into a page of this repo, which is what the
1441 edition ships too: its frame, folio and margin ornaments fall outside the 345x550
window every page is cropped to.

Every path Inkscape writes carries its own ``matrix(k,0,0,-k,tx,ty)``, so the ``d`` itself
is in typographic points with y running up -- the same space the shipped pages use inside
their root matrix.  ``place()`` is the whole of the conversion: the matrix becomes a
translation, and the ``d`` is untouched.
"""

import re

K = 4.0 / 3.0                     # Illustrator points to the px user unit Inkscape emits

HEADER, MARKS, BORDER, NUMBERS, TEXT = 0, 1, 2, 3, 4

_LAYER = re.compile(r'<g\s+id="layer-MC(\d+)"[^>]*?/?>')
_PATH = re.compile(r"<path\b(.*?)/>", re.S)
_ATTR = re.compile(r'([\w:-]+)="([^"]*)"', re.S)
_MATRIX = re.compile(r"matrix\(\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*,"
                     r"\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*,\s*([-\d.eE]+)\s*\)")


def viewbox(text):
    return [float(v) for v in re.search(r'viewBox="([^"]*)"', text).group(1).split()]


def layers(text):
    """``{layer index: inner xml}`` for the top-level layers, empty ones included."""
    out = {}
    marks = [(m.start(), m.end(), int(m.group(1)), m.group(0).endswith("/>"))
             for m in _LAYER.finditer(text)]
    end = text.rindex("</svg>")
    for i, (start, after, idx, empty) in enumerate(marks):
        if empty:
            out[idx] = ""
            continue
        stop = marks[i + 1][0] if i + 1 < len(marks) else end
        body = text[after:stop]
        out[idx] = body[:body.rindex("</g>")]
    return out


def style_of(attrs):
    return dict(kv.split(":", 1) for kv in attrs.get("style", "").split(";") if ":" in kv)


def paths(layer_xml):
    """``[{d, attrs, style, tx, ty}]`` for one layer, in document order.

    ``tx``/``ty`` are the path's placement in points with y up from the foot of the sheet,
    which is what ``place()`` needs; a path whose transform is not the usual flipped scale
    is returned with ``tx = ty = None`` so the caller can refuse the page rather than
    silently misplace it.
    """
    out = []
    for m in _PATH.finditer(layer_xml):
        attrs = dict(_ATTR.findall(m.group(1)))
        if "d" not in attrs:
            continue
        mm = _MATRIX.search(attrs.get("transform", ""))
        tx = ty = None
        if mm:
            a, b, c, d, e, f = (float(v) for v in mm.groups())
            if abs(a - K) < 1e-6 and abs(d + K) < 1e-6 and b == 0 and c == 0:
                tx, ty = e, f
        out.append(dict(d=attrs["d"], attrs=attrs, style=style_of(attrs), tx=tx, ty=ty))
    return out


def place(path, sheet_height):
    """The path's translation in the page's own y-up point space."""
    return path["tx"] / K, (sheet_height - path["ty"]) / K


def is_rosette(path):
    """The ۝ medallion, told from the numeral inside it by its outline stroke."""
    return path["style"].get("stroke", "none") != "none"
