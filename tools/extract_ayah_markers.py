#!/usr/bin/env python3
"""Extract the numbered ayah-marker glyphs from a QCF4 TrueType font."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont


MARKER_BOUNDS = (339, -915, 2503, 1919)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("font", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    font = TTFont(args.font)
    glyphs = font["glyf"]
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap()
    units_per_em = font["head"].unitsPerEm
    args.output.mkdir(parents=True, exist_ok=True)

    markers = []
    marker_paths = {}
    for glyph_name in font.getGlyphOrder():
        glyph = glyphs[glyph_name]
        if not hasattr(glyph, "xMin"):
            continue
        if (glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax) != MARKER_BOUNDS:
            continue

        pen = SVGPathPen(glyph_set)
        glyph_set[glyph_name].draw(pen)
        path = pen.getCommands()
        marker_paths[glyph_name] = path
        x_min, y_min, x_max, y_max = MARKER_BOUNDS
        width = x_max - x_min
        height = y_max - y_min
        # Translate the font-space bounds to the SVG viewport and flip Y.
        path = f"M 0 0 {path}" if not path else path
        transform = f"translate({-x_min} {y_max}) scale(1 -1)"
        svg = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {width} {height}" width="{width}" height="{height}">\n'
            f'  <path d="{path}" transform="{transform}"/>\n'
            '</svg>\n'
        )
        filename = f"{glyph_name}.svg"
        (args.output / filename).write_text(svg, encoding="utf-8")

        codepoints = [f"U+{codepoint:04X}" for codepoint, name in cmap.items() if name == glyph_name]
        markers.append(
            {
                "glyph": glyph_name,
                "file": filename,
                "codepoints": codepoints,
                "private_use_codepoint": codepoints[0] if codepoints else None,
                "font_units": {"x": x_min, "y": y_min, "width": width, "height": height},
                "advance_width": font["hmtx"][glyph_name][0],
                "units_per_em": units_per_em,
            }
        )

    if not markers:
        raise RuntimeError("No ayah-marker glyphs found")

    # The first contour in the first marker is its numeral.  The remaining
    # nine contours are the identical decorative medallion shared by every
    # numbered marker in this font.
    border_path = "".join(re.split(r"(?=M)", marker_paths[markers[0]["glyph"]])[2:])
    x_min, y_min, x_max, y_max = MARKER_BOUNDS
    border_svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {x_max - x_min} {y_max - y_min}" '
        f'width="{x_max - x_min}" height="{y_max - y_min}">\n'
        f'  <path d="{border_path}" transform="translate({-x_min} {y_max}) scale(1 -1)"/>\n'
        '</svg>\n'
    )
    (args.output / "ayah-marker-no-number.svg").write_text(border_svg, encoding="utf-8")

    index = {
        "font": str(args.font),
        "marker_count": len(markers),
        "no_number_file": "ayah-marker-no-number.svg",
        "markers": markers,
    }
    (args.output / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(f"Extracted {len(markers)} ayah-marker glyphs to {args.output}")


if __name__ == "__main__":
    main()
