"""Reading one mushaf page SVG: its viewBox, its content paths, and their contours."""

import os
import re

from svg_lines import mul, parse_transform, subpaths, transform_box

CONTENT_OPEN = '<g id="content">'
PATH_RE = re.compile(r"<path\b[^>]*?\bd=\"([^\"]*)\"[^>]*?/>", re.S)
MARKER_RE = re.compile(r'ayah:x="([-\d.]+)"\s+ayah:y="([-\d.]+)"')


def _matching_close(svg, start):
    """Index just past the `</g>` that closes the `<g>` opening at `start`."""
    depth, i = 0, start
    while i < len(svg):
        if svg.startswith("<g", i) and (i + 2 >= len(svg) or svg[i + 2] in " >\t\r\n"):
            depth += 1
            i += 2
        elif svg.startswith("</g>", i):
            depth -= 1
            i += 4
            if depth == 0:
                return i
        else:
            i += 1
    raise ValueError("unbalanced <g> from %d" % start)


class Page:
    """A page SVG, decomposed far enough to segment it and to rewrite it in place."""

    def __init__(self, path, svg=None):
        self.path = path
        self.name = os.path.basename(path)
        self.svg = svg if svg is not None else open(path, encoding="utf-8").read()
        vb = re.search(r'viewBox="([^"]*)"', self.svg)
        self.viewbox = [float(x) for x in vb.group(1).split()] if vb else None

        open_at = self.svg.find(CONTENT_OPEN)
        if open_at < 0:
            self.content = None
            self.paths = []
            return
        close_at = _matching_close(self.svg, open_at)
        inner_start = open_at + len(CONTENT_OPEN)
        inner_end = close_at - len("</g>")
        self.content = (inner_start, inner_end)

        # Every ancestor transform between <svg> and the path, composed in one forward
        # scan. Contour coordinates live in the path's own space, and the root matrix on
        # these pages carries a negative y-scale: a page segmented in raw path space comes
        # out upside down, so line 1 would be the bottom line.
        self.paths = []
        for span, ctm, chain in self._walk(inner_start, inner_end):
            m = PATH_RE.match(self.svg, span[0], span[1])
            self.paths.append({
                "span": span,
                "d_span": m.span(1),
                "d": m.group(1),
                "text": m.group(0),
                "M": ctm,
                # Open tags of the `<g>` elements wrapping this path inside #content, so
                # the path can be re-emitted under the same transforms it had before.
                "chain": chain,
            })

    def _walk(self, start, end):
        """Yield (path span, composed transform, wrapper chain) for `<path>` in [start, end).

        The transform stack is seeded from the ancestors of `start` — the root matrix and
        the `<g id="content">` wrapper — then maintained incrementally.
        """
        stack = [self._root_ctm(start)]
        chain = []
        i = start
        svg = self.svg
        while i < end:
            c = svg.find("<", i)
            if c < 0 or c >= end:
                return
            if svg.startswith("<g", c) and svg[c + 2] in " >\t\r\n":
                gt = svg.index(">", c)
                t = re.search(r'transform="([^"]*)"', svg[c:gt])
                stack.append(mul(stack[-1], parse_transform(t.group(1))) if t else stack[-1])
                chain.append(svg[c:gt + 1])
                i = gt + 1
            elif svg.startswith("</g>", c):
                if len(stack) > 1:
                    stack.pop()
                if chain:
                    chain.pop()
                i = c + 4
            elif svg.startswith("<path", c):
                gt = svg.index(">", c)
                yield (c, gt + 1), stack[-1], tuple(chain)
                i = gt + 1
            else:
                i = c + 1

    def _root_ctm(self, index):
        """Composed transform of the `<g>` elements still open at `index`."""
        M = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        stack, i = [], 0
        svg = self.svg
        while i < index:
            c = svg.find("<", i)
            if c < 0 or c >= index:
                break
            if svg.startswith("<g", c) and svg[c + 2] in " >\t\r\n":
                gt = svg.index(">", c)
                t = re.search(r'transform="([^"]*)"', svg[c:gt])
                stack.append(t.group(1) if t else "")
                i = gt + 1
            elif svg.startswith("</g>", c):
                if stack:
                    stack.pop()
                i = c + 4
            else:
                i = c + 1
        for t in stack:
            M = mul(M, parse_transform(t))
        return M

    def contours(self):
        """Every glyph contour on the page, with its box in rendered page coordinates."""
        out = []
        for pi, p in enumerate(self.paths):
            for sp in subpaths(p["d"]):
                x1, y1, x2, y2 = transform_box(p["M"], sp["xmin"], sp["ymin"],
                                               sp["xmax"], sp["ymax"])
                out.append({"path": pi, "sp": sp, "x1": x1, "y1": y1, "x2": x2, "y2": y2})
        return out

    def markers(self):
        """Ayah medallion centres the SVG already carries, in page coordinates."""
        return [(float(x), float(y)) for x, y in MARKER_RE.findall(self.svg)]

    def polygon_bands(self, json_dir):
        """Row edges implied by the per-page ayah polygons — independent of the glyphs."""
        import json
        f = os.path.join(json_dir, os.path.splitext(self.name)[0] + ".json")
        if not os.path.exists(f):
            return []
        ys = set()
        for entry in json.load(open(f, encoding="utf-8")):
            for m in re.finditer(r"[ML]\s+[-\d.]+\s+([-\d.]+)", entry.get("polygon", "")):
                ys.add(round(float(m.group(1)), 2))
        return sorted(ys)
