# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Headless side of DIMJOGGED, DIMBREAK, DIMSPACE and QDIM (issue #39).

The interactive tools live in :mod:`tools.dim_commands`; everything here is
a Command over the document or a pure computation, so a script can call it
and a test can check it without a window.

*Jogged* radius dimensions are stored as a radius DIMENSION of the true
centre and radius, the centre override and the jog as XDATA; every render
draws the jog into the dimension's own *D block. Any CAD reads it as a
radius dimension (AutoCAD's AcDbRadialDimensionLarge has no renderer in
ezdxf, and no place in the r2000 DWG IngeCAD saves).

*Breaks* are cut into the *D block's lines and remembered as XDATA under
the INGECAD appid, so Remove knows what to undo; a later re-render of the
dimension (a style change, DIMTEDIT) draws it whole again -- AutoCAD's own
rule for manual breaks, and the limit of the automatic ones here.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

from core import xdata
from core.actions import AddDimensionCommand, rerender_dimension
from core.commands import Command, CompositeCommand

Point = tuple[float, float]

#: AutoCAD's default Break size (Symbols and Arrows tab): 0.125" = 3.75 mm.
DEFAULT_BREAK_SIZE = 3.75
XDATA_BREAK_TAG = "DIMBREAK"


# -- style lookups -------------------------------------------------------------

def _style(document, dim):
    name = None
    if dim is not None:
        name = dim.dxf.get("dimstyle", None)
    name = name or document.doc.header.get("$DIMSTYLE", "Standard")
    if name in document.doc.dimstyles:
        return document.doc.dimstyles.get(name)
    return None


def dim_scale(document, dim) -> float:
    style = _style(document, dim)
    scale = style.dxf.get("dimscale", 1.0) if style is not None else 1.0
    return float(scale) or 1.0


def text_height(document, dim) -> float:
    """The height ``dim``'s text is drawn at, DIMSCALE applied."""
    from core.styles import dim_text_height

    if dim is not None:
        try:
            get = dim.override().get
        except Exception:                      # noqa: BLE001 - the style's
            get = None
    else:
        get = None
    if get is None:
        style = _style(document, dim)
        if style is None:
            return 2.5 * dim_scale(document, dim)
        get = style.dxf.get
    return dim_text_height(document.doc, get) * dim_scale(document, dim)


def measurement_text(dim, value: float) -> str:
    """``value`` written the way ``dim`` writes its measurement: its
    DIMLFAC, DIMRND, DIMDEC, DIMZIN and decimal separator, each from the
    dimension's overrides first and then its style -- what a grip-drag
    preview must show so the number does not jump when the drag lands
    ("48.23" in the preview, "48" on the drawing, in Rafael's seventh
    review). DIMRND 0 is AutoCAD's "no rounding", not ezdxf's "drop the
    decimals"."""
    from ezdxf.render.dim_base import format_text

    try:
        override = dim.override()
        get = override.get
        # the renderer's own answer, so the preview and the drawing agree
        separator = override.get_decimal_separator()
    except Exception:                        # noqa: BLE001 - plain defaults
        def get(_key, default=None):
            return default
        separator = "."
    factor = float(get("dimlfac", 1.0) or 1.0)
    if factor < 0.0:            # paper space only; previews are of the model
        factor = 1.0
    rounding = get("dimrnd", None)
    rounding = float(rounding) if rounding else None
    decimals = get("dimdec", 2)
    return format_text(value * factor, dimrnd=rounding,
                       dimdec=int(decimals) if decimals is not None else 2,
                       dimzin=int(get("dimzin", 8) or 0),
                       dimdsep=separator or ".")


def break_size(document, dim) -> float:
    return DEFAULT_BREAK_SIZE * dim_scale(document, dim)


def dimdli(document, dim) -> float:
    style = _style(document, dim)
    value = style.dxf.get("dimdli", 3.75) if style is not None else 3.75
    return float(value or 3.75) * dim_scale(document, dim)


# -- the *D block's lines --------------------------------------------------------

def _block_lines(document, dim) -> list:
    """The LINE entities of a dimension's block that are not Defpoints."""
    name = dim.dxf.get("geometry", None)
    if not name or name not in document.doc.blocks:
        return []
    return [e for e in document.doc.blocks.get(name)
            if e.dxftype() == "LINE" and e.dxf.layer.lower() != "defpoints"]


def _seg(e) -> tuple[Point, Point]:
    s, w = e.dxf.start, e.dxf.end
    return (s.x, s.y), (w.x, w.y)


def _param(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy or 1.0
    return ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2


def _seg_distance(p: Point, a: Point, b: Point) -> float:
    u = max(0.0, min(1.0, _param(p, a, b)))
    return math.dist(p, (a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1])))


def _crossing(a: Point, b: Point, c: Point, d: Point) -> Optional[float]:
    """Parameter along a->b where it crosses segment c->d, or None."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    denom = r[0] * s[1] - r[1] * s[0]
    if abs(denom) < 1e-12:
        return None
    qp = (c[0] - a[0], c[1] - a[1])
    t = (qp[0] * s[1] - qp[1] * s[0]) / denom
    u = (qp[0] * r[1] - qp[1] * r[0]) / denom
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return min(1.0, max(0.0, t))
    return None


def obstacle_segments(entity, distance: float = 0.05) -> list[tuple[Point, Point]]:
    """A crossing object's outline as segments (curves flattened)."""
    from ezdxf import path as ezpath

    try:
        p = ezpath.make_path(entity)
        pts = [(v.x, v.y) for v in p.flattening(distance)]
    except Exception:            # noqa: BLE001 - not a shape we can cross
        return []
    return list(zip(pts, pts[1:]))


def auto_gaps(document, dim, obstacles: Iterable, size: Optional[float] = None
              ) -> list[tuple[str, float, float]]:
    """(line handle, t0, t1) gaps where the dimension's lines cross the
    obstacles, each ``size`` long (the style's Break size by default)."""
    size = break_size(document, dim) if size is None else size
    segments = []
    for obstacle in obstacles:
        segments.extend(obstacle_segments(obstacle))
    gaps = []
    for line in _block_lines(document, dim):
        a, b = _seg(line)
        length = math.dist(a, b) or 1.0
        half = (size / 2.0) / length
        for c, d in segments:
            t = _crossing(a, b, c, d)
            if t is None:
                continue
            gaps.append((line.dxf.handle, max(0.0, t - half), min(1.0, t + half)))
    return gaps


def manual_gap(document, dim, p1: Point, p2: Point) -> list[tuple[str, float, float]]:
    """One gap between two points, on the dimension line nearest to them."""
    lines = _block_lines(document, dim)
    if not lines:
        return []
    line = min(lines, key=lambda e: _seg_distance(p1, *_seg(e))
               + _seg_distance(p2, *_seg(e)))
    a, b = _seg(line)
    t0, t1 = sorted((_param(p1, a, b), _param(p2, a, b)))
    t0, t1 = max(0.0, t0), min(1.0, t1)
    if t1 - t0 <= 1e-9:
        return []
    return [(line.dxf.handle, t0, t1)]


def _cut(document, dim, gaps) -> None:
    by_handle: dict[str, list[tuple[float, float]]] = {}
    for handle, t0, t1 in gaps:
        by_handle.setdefault(handle, []).append((t0, t1))
    block = document.doc.blocks.get(dim.dxf.geometry)
    db = document.doc.entitydb
    for handle, intervals in by_handle.items():
        line = db.get(handle)
        if line is None or not line.is_alive:
            continue
        a, b = _seg(line)
        intervals.sort()
        pieces, cursor = [], 0.0
        for t0, t1 in intervals:
            if t0 > cursor:
                pieces.append((cursor, t0))
            cursor = max(cursor, t1)
        if cursor < 1.0:
            pieces.append((cursor, 1.0))
        attribs = line.dxfattribs()
        for key in ("handle", "owner", "start", "end"):
            attribs.pop(key, None)
        for t0, t1 in pieces:
            block.add_line((a[0] + t0 * (b[0] - a[0]), a[1] + t0 * (b[1] - a[1])),
                           (a[0] + t1 * (b[0] - a[0]), a[1] + t1 * (b[1] - a[1])),
                           dxfattribs=attribs)
        block.delete_entity(line)


def has_breaks(dim) -> bool:
    if not dim.has_xdata(xdata.APPID):
        return False
    return any(code == 1000 and value == XDATA_BREAK_TAG
               for code, value in dim.get_xdata(xdata.APPID))


def _strip_break_tags(tags):
    return [t for t in tags if not (t[0] == 1000 and t[1] == XDATA_BREAK_TAG)
            and t[0] != 1070]


class DimBreakCommand(Command):
    """DIMBREAK Auto/Manual: cut the given gaps into the dimension's block
    and remember them; undo re-renders the block and restores the XDATA."""

    name = "DIMBREAK"
    needs_regen = False

    @property
    def entities(self) -> list:
        return [self.dim]

    def __init__(self, dim, gaps) -> None:
        self.dim = dim
        self.gaps = list(gaps)
        self._old_xdata = None

    def do(self, document) -> None:
        d = self.dim
        self._old_xdata = (list(d.get_xdata(xdata.APPID))
                           if d.has_xdata(xdata.APPID) else None)
        _cut(document, d, self.gaps)
        xdata.ensure_appid(document.doc)
        tags = _strip_break_tags(self._old_xdata or [])
        tags.append((1000, XDATA_BREAK_TAG))
        tags.append((1070, len(self.gaps)))
        d.discard_xdata(xdata.APPID)
        d.set_xdata(xdata.APPID, tags)
        document.dirty = True

    def undo(self, document) -> None:
        d = self.dim
        d.discard_xdata(xdata.APPID)
        if self._old_xdata is not None:
            d.set_xdata(xdata.APPID, self._old_xdata)
        rerender_dimension(document, d)
        document.dirty = True


class DimBreakRemoveCommand(Command):
    """DIMBREAK Remove: the dimension drawn whole again."""

    name = "DIMBREAK"
    needs_regen = False

    @property
    def entities(self) -> list:
        return [self.dim]

    def __init__(self, dim) -> None:
        self.dim = dim
        self._old_xdata = None
        self._old_name = None

    def do(self, document) -> None:
        d = self.dim
        self._old_xdata = (list(d.get_xdata(xdata.APPID))
                           if d.has_xdata(xdata.APPID) else None)
        d.discard_xdata(xdata.APPID)
        kept = _strip_break_tags(self._old_xdata or [])
        if kept:
            d.set_xdata(xdata.APPID, kept)
        # the broken block survives under its name for undo; the dimension
        # gets a fresh one
        self._old_name = d.dxf.get("geometry", None)
        d.dxf.discard("geometry")
        d.render()
        document.dirty = True

    def undo(self, document) -> None:
        d = self.dim
        d.discard_xdata(xdata.APPID)
        if self._old_xdata is not None:
            d.set_xdata(xdata.APPID, self._old_xdata)
        fresh = d.dxf.get("geometry", None)
        if self._old_name and self._old_name in document.doc.blocks:
            d.dxf.geometry = self._old_name
            if fresh and fresh in document.doc.blocks and fresh != self._old_name:
                document.doc.blocks.delete_block(fresh, safe=False)
        else:
            rerender_dimension(document, d)
        document.dirty = True


# -- DIMJOGGED -------------------------------------------------------------------

#: AutoCAD's DIMJOGANG initial value (p. 2241); valid range 5 to 90.
DEFAULT_JOG_ANGLE = 45.0
XDATA_JOG_TAG = "DIMJOGGED"


def jog_points(center: Point, p: Point, override: Point, jog: Point,
               angle: float = DEFAULT_JOG_ANGLE,
               limit: Optional[float] = None) -> list[Point]:
    """The polyline O -> B -> A -> P of a jogged radius, AutoCAD's shape
    (Rafael's eighth review, the norm's): A -> P lies on the TRUE radial
    line, pointing at the centre wherever it is; O -> B runs parallel to it
    from the centre override; B -> A is the transverse segment, at
    ``angle`` degrees to the dimension line, centred where ``jog``
    projects. ``limit`` is the farthest A may sit from the true centre
    (the text sits on the arrow's segment)."""
    cx, cy = center
    r = math.hypot(p[0] - cx, p[1] - cy) or 1.0
    ux, uy = (p[0] - cx) / r, (p[1] - cy) / r
    nx, ny = -uy, ux
    ox, oy = override[0] - cx, override[1] - cy
    h = ox * nx + oy * ny
    if abs(h) <= 1e-9 * max(1.0, r):
        return [override, p]
    s_o = ox * ux + oy * uy
    angle = max(5.0, min(90.0, angle))
    d = 0.0 if angle >= 90.0 else abs(h) / math.tan(math.radians(angle))
    s_j = (jog[0] - cx) * ux + (jog[1] - cy) * uy
    hi = r if limit is None else min(r, limit)
    s_a = min(s_j + d / 2.0, hi)
    s_b = s_a - d
    if s_b < s_o:
        # the jog would start behind the override: it starts there, and
        # when even then it overshoots the arc (or the text) it steepens
        # over half the room -- an override far to the side, a centre far
        # off the sheet -- and the arrow keeps its stretch of true radius
        s_b, s_a = s_o, s_o + d
        if s_a > hi:
            s_a = s_o + max(hi - s_o, 0.0) / 2.0
    b = (cx + ux * s_b + nx * h, cy + uy * s_b + ny * h)
    a = (cx + ux * s_a, cy + uy * s_a)
    if math.hypot(b[0] - override[0], b[1] - override[1]) <= 1e-9 * r:
        return [override, a, p]
    return [override, b, a, p]


def jog_data(dim) -> Optional[tuple[Point, Point]]:
    """(centre override, jog location) of a jogged radius, or None. Kept
    as XDATA world points (1011), which follow the dimension when it is
    moved, rotated or scaled."""
    if not dim.has_xdata(xdata.APPID):
        return None
    tags = list(dim.get_xdata(xdata.APPID))
    for i, (code, value) in enumerate(tags):
        if code == 1000 and value == XDATA_JOG_TAG:
            points = [v for c, v in tags[i + 1:i + 3] if c == 1011]
            if len(points) == 2:
                return ((points[0][0], points[0][1]),
                        (points[1][0], points[1][1]))
    return None


def _jog_angle(get) -> float:
    """DIMJOGANG in degrees: DXF stores it in radians, a value above the
    90-degree mark in radians can only be degrees."""
    value = get("dimjogang", None)
    if value is None:
        return DEFAULT_JOG_ANGLE
    value = float(value)
    return math.degrees(value) if value <= math.pi / 2 + 1e-9 else value


def _center_mark_lines(renderer, c, r) -> list:
    """The segments ezdxf's ``add_center_mark`` draws at ``c``: a cross
    of DIMCEN, and centre lines out past the arc when DIMCEN is negative."""
    dimcen = float(renderer.dim_style.get("dimcen", 0) or 0)
    size = abs(dimcen)
    if size == 0:
        return []
    out = [((c.x - size, c.y), (c.x + size, c.y)),
           ((c.x, c.y - size), (c.x, c.y + size))]
    if dimcen < 0 and size + r >= 2 * size:
        far = size + r
        for sx, sy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            out.append(((c.x + sx * 2 * size, c.y + sy * 2 * size),
                        (c.x + sx * far, c.y + sy * far)))
    return out


def _same_segment(a, b, seg, eps) -> bool:
    (x0, y0), (x1, y1) = seg
    def at(q, x, y):
        return abs(q.x - x) <= eps and abs(q.y - y) <= eps
    return ((at(a, x0, y0) and at(b, x1, y1))
            or (at(a, x1, y1) and at(b, x0, y0)))


def draw_jog(renderer, block) -> None:
    """Redraw a jogged radius's dimension line into its freshly rendered
    block: ezdxf drew a plain radius to the true centre (a centre mark
    there, the line through it); the jogged one runs from the override
    instead. Called on every render, so a style change or a moved text
    keeps the jog."""
    data = jog_data(renderer.dimension)
    if data is None:
        return
    override, jog = data
    c, p = renderer.center, renderer.point_on_circle
    r = (p - c).magnitude or 1.0
    ux, uy = (p.x - c.x) / r, (p.y - c.y) / r
    eps = 1e-6 * max(1.0, r)
    far = r
    limit = None
    m = renderer.measurement
    if m.text and m.text_location is not None:
        t = m.text_location
        s_text = (t.x - c.x) * ux + (t.y - c.y) * uy
        if s_text < r:              # the text sits on the arrow's segment
            limit = s_text - renderer.total_text_width() / 2.0
    attribs = None
    marks = _center_mark_lines(renderer, c, r)
    for line in list(block):
        if line.dxftype() != "LINE" or line.dxf.layer.lower() == "defpoints":
            continue
        a, b = line.dxf.start, line.dxf.end
        if any(_same_segment(a, b, m, eps) for m in marks):
            # the centre a jogged radius stands in for is off the sheet:
            # no mark there (it stretched ZOOM Extents to it)
            block.delete_entity(line)
            continue
        perp = [abs((q.x - c.x) * -uy + (q.y - c.y) * ux) for q in (a, b)]
        inside = all(math.hypot(q.x - c.x, q.y - c.y) <= r + eps for q in (a, b))
        if not (inside or max(perp) <= eps):
            continue                 # a horizontal landing outside: kept
        if max(perp) <= eps:
            far = max(far, *((q.x - c.x) * ux + (q.y - c.y) * uy for q in (a, b)))
        if attribs is None:
            attribs = line.dxfattribs()
            for key in ("handle", "owner", "start", "end"):
                attribs.pop(key, None)
        block.delete_entity(line)
    pts = jog_points((c.x, c.y), (p.x, p.y), override, jog,
                     _jog_angle(renderer.dim_style.get), limit)
    if far > r + eps:
        pts[-1] = (c.x + ux * far, c.y + uy * far)
    for s, e in zip(pts, pts[1:]):
        block.add_line(s, e, dxfattribs=attribs or {})


def dim_jogged(center: Point, radius: float, override: Point, location: Point,
               jog: Point, *, text: str = "<>",
               text_rotation: Optional[float] = None) -> AddDimensionCommand:
    """DIMJOGGED: a radius dimension of the TRUE centre and radius -- it
    measures, and re-measures, like any other -- whose text sits at
    ``location``; the centre override and the jog live in its XDATA and
    every render draws the jogged line (:func:`draw_jog`)."""
    from core.actions import _current_dimstyle, _text_rotation_attribs

    dx, dy = location[0] - center[0], location[1] - center[1]
    if math.hypot(dx, dy) < 1e-9:
        location = (center[0] + radius, center[1])

    def factory(msp, document):
        override_ = msp.add_radius_dim(
            center=(center[0], center[1]), radius=radius,
            location=location, text=text, dimstyle=_current_dimstyle(document),
            dxfattribs=_text_rotation_attribs(text_rotation))
        xdata.ensure_appid(document.doc)
        override_.dimension.set_xdata(xdata.APPID, [
            (1000, XDATA_JOG_TAG),
            (1011, (override[0], override[1], 0.0)),
            (1011, (jog[0], jog[1], 0.0))])
        return override_

    cmd = AddDimensionCommand(factory)
    cmd.name = "DIMJOGGED"
    return cmd


# -- DIMSPACE --------------------------------------------------------------------

def is_linear(dim) -> bool:
    return dim.dxftype() == "DIMENSION" and (dim.dxf.dimtype & 15) in (0, 1)


def _axis(dim) -> tuple[Point, Point]:
    """(unit normal to the dimension line, the first extension origin)."""
    p1 = dim.dxf.defpoint2
    p2 = dim.dxf.defpoint3
    if (dim.dxf.dimtype & 15) == 1:
        dx, dy = p2.x - p1.x, p2.y - p1.y
    else:
        a = math.radians(dim.dxf.get("angle", 0.0))
        dx, dy = math.cos(a), math.sin(a)
    length = math.hypot(dx, dy) or 1.0
    return (-dy / length, dx / length), (p1.x, p1.y)


def _offset(dim, normal: Point, origin: Point) -> float:
    d = dim.dxf.defpoint
    return (d.x - origin[0]) * normal[0] + (d.y - origin[1]) * normal[1]


def space_plan(document, base, dims, spacing: Optional[float]
               ) -> list[tuple[object, Point]]:
    """(dimension, new defpoint) for every dimension to move: equal
    ``spacing`` from the base outwards, in their present order. None
    spacing = Auto, twice the base style's text height; 0 lines them up."""
    if not is_linear(base):
        return []
    if spacing is None:
        spacing = 2.0 * text_height(document, base)
    normal, origin = _axis(base)
    base_offset = _offset(base, normal, origin)
    others = [d for d in dims if is_linear(d) and d is not base]
    others.sort(key=lambda d: abs(_offset(d, normal, origin) - base_offset))
    plan = []
    for k, d in enumerate(others, start=1):
        current = _offset(d, normal, origin)
        side = 1.0 if current >= base_offset else -1.0
        target = base_offset + side * k * spacing
        shift = target - current
        p = d.dxf.defpoint
        plan.append((d, (p.x + normal[0] * shift, p.y + normal[1] * shift)))
    return plan


class DimSpaceCommand(Command):
    name = "DIMSPACE"
    needs_regen = False

    def __init__(self, plan) -> None:
        self.plan = list(plan)
        self._old = None

    @property
    def entities(self) -> list:
        return [d for d, _ in self.plan]

    def do(self, document) -> None:
        if self._old is None:
            self._old = [(d, (d.dxf.defpoint.x, d.dxf.defpoint.y))
                         for d, _ in self.plan]
        for d, (x, y) in self.plan:
            d.dxf.defpoint = (x, y, 0.0)
            rerender_dimension(document, d)
        document.dirty = True

    def undo(self, document) -> None:
        for d, (x, y) in self._old or []:
            d.dxf.defpoint = (x, y, 0.0)
            rerender_dimension(document, d)
        document.dirty = True


# -- QDIM --------------------------------------------------------------------------

def feature_points(entities) -> list[Point]:
    """The extension-line origins QDIM takes from the selected geometry."""
    from core import ocs

    pts: list[Point] = []
    for e in entities:
        t = e.dxftype()
        if t == "LINE":
            pts += [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
        elif t == "LWPOLYLINE":
            pts += [(p[0], p[1]) for p in ocs.points_wcs(
                e, [(p[0], p[1]) for p in e.get_points("xy")])]
        elif t == "ARC":
            c, r = ocs.center_wcs(e), e.dxf.radius
            for a in ocs.angles_wcs(e):
                pts.append((c.x + r * math.cos(math.radians(a)),
                            c.y + r * math.sin(math.radians(a))))
        elif t == "CIRCLE":
            c = ocs.center_wcs(e)
            pts.append((c.x, c.y))
    return pts


def _dedupe(values: list[float], tol: float = 1e-6) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or abs(v - out[-1]) > tol:
            out.append(v)
    return out


def qdim_axis(points: list[Point], position: Point) -> float:
    """0 (horizontal dimensions) when the position sits above or below the
    geometry, 90 when beside it; the farther side wins in between."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    dy = max(y0 - position[1], position[1] - y1, 0.0)
    dx = max(x0 - position[0], position[0] - x1, 0.0)
    if dy == 0.0 and dx == 0.0:
        return 0.0 if (x1 - x0) >= (y1 - y0) else 90.0
    return 0.0 if dy >= dx else 90.0


def qdim_commands(document, entities, position: Point, mode: str,
                  datum: Optional[Point] = None) -> list:
    """The AddDimensionCommands of one QDIM placement, in order."""
    from core import actions

    mode = mode.upper()
    if mode in ("RADIUS", "DIAMETER"):
        from core import ocs

        out = []
        for e in entities:
            if e.dxftype() not in ("CIRCLE", "ARC"):
                continue
            c = ocs.center_wcs(e)
            make = actions.dim_radius if mode == "RADIUS" else actions.dim_diameter
            out.append(make((c.x, c.y), float(e.dxf.radius), position))
        return out
    points = feature_points(entities)
    if not points or (len(points) < 2 and mode != "ORDINATE"):
        return []
    angle = qdim_axis(points, position)
    horizontal = angle == 0.0
    along = 0 if horizontal else 1
    across = 1 - along
    coords = _dedupe([p[along] for p in points])
    origin_of: dict[float, Point] = {}
    for p in points:
        for c in coords:
            if abs(p[along] - c) <= 1e-6:
                origin_of.setdefault(c, p)
    ys = [p[across] for p in points]
    outward = 1.0 if position[across] >= (min(ys) + max(ys)) / 2.0 else -1.0
    step = dimdli(document, None)

    def location(c_mid: float, level: int) -> Point:
        off = position[across] + outward * step * level
        return (c_mid, off) if horizontal else (off, c_mid)

    def linear(c1: float, c2: float, level: int):
        p1, p2 = origin_of[c1], origin_of[c2]
        return actions.dim_linear(p1, p2, location((c1 + c2) / 2.0, level),
                                  angle=angle)

    out = []
    if mode == "CONTINUOUS":
        for c1, c2 in zip(coords, coords[1:]):
            out.append(linear(c1, c2, 0))
    elif mode == "BASELINE":
        start = coords[0]
        if datum is not None:
            start = min(coords, key=lambda c: abs(c - datum[along]))
        others = [c for c in coords if c != start]
        others.sort(key=lambda c: abs(c - start))
        for level, c in enumerate(others):
            out.append(linear(start, c, level))
    elif mode == "STAGGERED":
        lo, hi, level = 0, len(coords) - 1, 0
        while lo < hi:
            out.append(linear(coords[lo], coords[hi], level))
            lo, hi, level = lo + 1, hi - 1, level + 1
    elif mode == "ORDINATE":
        for c in coords:
            feature = origin_of[c]
            leader_end = ((c, position[across]) if horizontal
                          else (position[across], c))
            out.append(actions.dim_ordinate(feature, leader_end,
                                            dtype="X" if horizontal else "Y"))
    return out


def qdim(document, entities, position: Point, mode: str,
         datum: Optional[Point] = None) -> Optional[CompositeCommand]:
    commands = qdim_commands(document, entities, position, mode, datum)
    if not commands:
        return None
    return CompositeCommand("QDIM", commands)
