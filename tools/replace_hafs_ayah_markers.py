#!/usr/bin/env python3
"""Replace Hafs page medallions while preserving each existing number group."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from xml.etree import ElementTree as ET

from fontTools.svgLib.path import parse_path
from fontTools.pens.boundsPen import BoundsPen


SVG_NS = "http://www.w3.org/2000/svg"
AYAH_NS = "https://quranpedia.net"
OLD_MARKER_PREFIX = "m1248,4"

# Bounds of the Douri U+06DD glyph used in the extracted SVG.
DOURI_BOUNDS = (37.0, -419.0, 1514.0, 1406.0)
# The largest enclosed interior of the Douri glyph is below its full-glyph
# center by about 31.2 font units in font coordinates.
INNER_SPACE_Y = 462.3


def local_transform_number_center(number: ET.Element) -> tuple[float, float]:
    match = re.search(r"translate\(([-.0-9]+)[,\s]+([-.0-9]+)\)", number.attrib["transform"])
    if not match:
        raise ValueError("Number group has no translate transform")
    tx, ty = map(float, match.groups())
    path = next((node for node in number.iter() if node.tag.endswith("path")), None)
    if path is None:
        # Some Qaloun pages intentionally keep an empty number group; its
        # translation is the marker center and the group must remain intact.
        return tx, ty
    pen = BoundsPen(None)
    parse_path(path.attrib["d"], pen)
    x0, y0, x1, y1 = pen.bounds
    return tx + (x0 + x1) / 2, ty + (y0 + y1) / 2


def marker_element(
    number: ET.Element,
    marker_path: str,
    marker_scale: float,
    marker_inner_transform: str | None = None,
) -> ET.Element:
    center_x, center_y = local_transform_number_center(number)
    if marker_inner_transform is not None:
        wrapper = ET.Element(f"{{{SVG_NS}}}g", {"class": "ayah_marker"})
        mark = ET.SubElement(
            wrapper,
            f"{{{SVG_NS}}}g",
            {
                "class": "ayah_marker_mark",
                "transform": f"translate({center_x:.6f} {center_y:.6f}) scale({marker_scale:g} {-marker_scale:g})",
            },
        )
        ET.SubElement(
            mark,
            f"{{{SVG_NS}}}path",
            {"d": marker_path, "transform": marker_inner_transform, "fill": "#231f20", "fill-rule": "evenodd"},
        )
        wrapper.append(number)
        return wrapper
    x0, y0, x1, y1 = DOURI_BOUNDS
    douri_cx = (x0 + x1) / 2
    douri_cy = (y0 + y1) / 2
    sx = 0.65 * 2164.0 / (x1 - x0)
    sy = 0.65 * 2834.0 / (y1 - y0)

    # Outer marker transform follows the page's existing Y inversion. The
    # positive local shift places the Douri inner space on the number center.
    inner_shift = marker_scale * sy * (INNER_SPACE_Y - douri_cy)
    marker_center_y = center_y - inner_shift
    inner = (
        f"matrix({sx:.8f} 0 0 {-sy:.8f} "
        f"{-sx * douri_cx:.8f} {sy * douri_cy:.8f})"
    )
    wrapper = ET.Element(f"{{{SVG_NS}}}g", {"class": "ayah_marker"})
    mark = ET.SubElement(
        wrapper,
        f"{{{SVG_NS}}}g",
        {
            "class": "ayah_marker_mark",
            "transform": (
                f"translate({center_x:.6f} {marker_center_y:.6f}) "
                f"scale({marker_scale:g} {-marker_scale:g})"
            ),
        },
    )
    ET.SubElement(
        mark,
        f"{{{SVG_NS}}}path",
        {"d": marker_path, "transform": inner, "fill": "#231f20", "fill-rule": "evenodd"},
    )
    # Keep the supplied number group as-is and put it after the mark.
    wrapper.append(number)
    return wrapper


def replace_page(
    path: Path,
    marker_path: str,
    page1_scale: float,
    page2_scale: float,
    rest_scale: float,
    marker_inner_transform: str | None = None,
) -> int:
    tree = ET.parse(path)
    root = tree.getroot()
    layer = next((node for node in root.iter() if node.attrib.get("id") == "ayah_markers"), None)
    if layer is None:
        raise ValueError(f"Missing ayah_markers layer: {path}")

    scale = page1_scale if path.stem == "001" else page2_scale if path.stem == "002" else rest_scale
    children = list(layer)
    # Make the sweep resumable after an interrupted run. Rebuild existing
    # wrappers with the final scale while keeping their number child intact.
    if children and all(child.attrib.get("class") == "ayah_marker" and len(child) == 2 for child in children):
        rebuilt = []
        for wrapper in children:
            number = wrapper[-1]
            rebuilt.append(marker_element(number, marker_path, scale, marker_inner_transform))
        layer[:] = rebuilt
        tree.write(path, encoding="unicode", xml_declaration=True)
        return len(rebuilt)
    new_children: list[ET.Element] = []
    pending_old = 0
    replaced = 0
    for child in children:
        path_node = next((node for node in child.iter() if node.tag.endswith("path")), None)
        path_data = path_node.attrib.get("d", "") if path_node is not None else ""
        is_old_marker = "scale(" in child.attrib.get("transform", "") and path_data.startswith(OLD_MARKER_PREFIX)
        is_number = any(key.endswith("}x") for key in child.attrib)
        if is_old_marker:
            pending_old += 1
            if scale is None:
                match = re.search(r"scale\(([-.0-9]+)", child.attrib["transform"])
                if not match:
                    raise ValueError(f"Marker scale missing: {path}")
                scale = float(match.group(1))
            continue
        if is_number:
            if pending_old == 0:
                raise ValueError(f"Number without marker group: {path}")
            new_children.append(marker_element(child, marker_path, scale, marker_inner_transform))
            pending_old = 0
            replaced += 1
            continue
        if pending_old:
            raise ValueError(f"Marker groups not immediately followed by number: {path}")
        new_children.append(child)
    if pending_old:
        raise ValueError(f"Unpaired marker groups: {path}")
    layer[:] = new_children
    tree.write(path, encoding="unicode", xml_declaration=True)
    return replaced


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mushaf-root", type=Path, default=Path("mushafs"))
    parser.add_argument("--mushafs", nargs="+", default=["hafs", "douri", "qalon", "shubah"])
    parser.add_argument("--douri-svg", type=Path, default=Path("tools/ayah-marker-u06dd.svg"))
    parser.add_argument("--marker-svg", type=Path)
    parser.add_argument("--marker-inner-transform")
    parser.add_argument("--page1-scale", type=float, default=0.007)
    parser.add_argument("--page2-scale", type=float, default=0.007)
    parser.add_argument("--rest-scale", type=float, default=0.009)
    args = parser.parse_args()

    marker_svg = args.marker_svg or args.douri_svg
    marker_root = ET.parse(marker_svg).getroot()
    marker_node = next(node for node in marker_root.iter() if node.tag.endswith("path"))
    marker_path = marker_node.attrib["d"]
    marker_inner_transform = args.marker_inner_transform
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("ayah", AYAH_NS)

    import brotli
    total_pages = total_markers = compressed = 0
    for mushaf in args.mushafs:
        svg_dir = args.mushaf_root / mushaf / "kfqc" / "svg"
        br_dir = args.mushaf_root / mushaf / "kfqc" / "svg-br"
        pages = sorted(svg_dir.glob("*.svg"))
        for page in pages:
            total_markers += replace_page(page, marker_path, args.page1_scale, args.page2_scale, args.rest_scale, marker_inner_transform)
        for page in pages:
            target = br_dir / f"{page.name}.br"
            if target.exists():
                target.write_bytes(brotli.compress(page.read_bytes(), quality=11))
                compressed += 1
        total_pages += len(pages)
        print(f"{mushaf}: {len(pages)} pages updated")
    print(f"Updated {total_pages} SVG pages, {total_markers} ayah markers, and {compressed} Brotli files")


if __name__ == "__main__":
    main()
