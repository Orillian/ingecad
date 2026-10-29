# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Roads, headless: every operation is an undoable Command over the ezdxf
document, and everything it draws is a plain DXF entity.

An axis (eje) is an open LWPOLYLINE of tangents and arcs on ``CAR-EJE``
whose XDATA, under the plugin's own APPID ``INGECAD_CARRETERAS``, holds its
start station, its direction and the stationing it was last drawn with.
What the plugin draws for an axis -- station ticks and their labels -- carries the axis handle in the same APPID, so drawing
the stationing again replaces the old one in one undo step. The tables are
plain lines and text (``core.tables``), a snapshot like Topography's chart.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from core import tables
from core.actions import AddEntityCommand, EraseCommand
from core.commands import Command, CompositeCommand
from core.i18n import tr
from core.layers import NewLayerCommand
from core.surveying import (cad_to_azimuth, format_bearing, format_dms,
                            format_station, readable_rotation)
from core.xdata import ensure_appid

from . import geometry

#: The plugin's own APPID: never ``INGECAD`` (core/xdata.py says why).
APPID = "INGECAD_CARRETERAS"
AXIS_TAG = "CAR-AXIS"
ANNOT_TAG = "CAR-ANNOT"

#: (layer, ACI colour) per kind of object.
LAYERS = {
    "axis": ("CAR-EJE", 1),
    "ticks": ("CAR-ESTACAS", 7),
    "stations": ("CAR-PROGRESIVAS", 3),
    "tables": ("CAR-CUADROS", 7),
}

#: annotation kinds, each regenerated with the axis
STATIONS = "stations"


@dataclass(frozen=True)
class AxisParams:
    """What the axis remembers: where its stationing starts and runs, and
    how it was last drawn."""

    start: float = 0.0               # start station, metres
    reverse: bool = False            # stationed from the polyline's last vertex
    interval: float = 20.0
    tick: float = 4.0                # tick length, across the axis
    height: float = 2.0              # text height

    def xdata(self) -> list:
        return [(1000, AXIS_TAG), (1040, self.start), (1070, 1 if self.reverse else 0),
                (1040, self.interval), (1040, self.tick), (1040, self.height)]

    @classmethod
    def from_xdata(cls, tags) -> "AxisParams | None":
        values = [v for _code, v in tags]
        if len(values) < 6 or values[0] != AXIS_TAG:
            return None
        return cls(float(values[1]), bool(int(values[2])), float(values[3]),
                   float(values[4]), float(values[5]))


# -- reading the drawing -------------------------------------------------------------

def _tags(entity):
    try:
        return list(entity.get_xdata(APPID))
    except Exception:
        return None


def axis_params(entity) -> AxisParams | None:
    """The axis data of ``entity``, or None if it is not an axis."""
    if entity.dxftype() != "LWPOLYLINE":
        return None
    tags = _tags(entity)
    return AxisParams.from_xdata(tags) if tags else None


def is_axis(entity) -> bool:
    return axis_params(entity) is not None


def polyline_vertices(entity) -> list:
    """(x, y, bulge) of an LWPOLYLINE in world coordinates; an arc drawn
    with its extrusion pointing down turns the other way seen from above."""
    if entity.dxftype() != "LWPOLYLINE":
        raise ValueError("the axis must be a polyline")
    if entity.closed:
        raise ValueError("the axis must be an open polyline")
    ocs = entity.ocs()
    flip = ocs.uz.z < 0
    out = []
    for x, y, b in entity.get_points("xyb"):
        w = ocs.to_wcs((x, y, 0.0))
        out.append((w.x, w.y, -b if flip else b))
    return out


def alignment_of(entity, params: AxisParams | None = None) -> geometry.Alignment:
    """The axis as stationed geometry, walked the way its stationing runs."""
    params = params or axis_params(entity) or AxisParams()
    verts = polyline_vertices(entity)
    if params.reverse:
        verts = geometry.reverse_vertices(verts)
    return geometry.Alignment(verts, params.start)


def annotation_kind(entity) -> tuple[str, str] | None:
    """(kind, axis handle) of something drawn for an axis."""
    tags = _tags(entity)
    if not tags or len(tags) < 3 or tags[0][1] != ANNOT_TAG:
        return None
    return str(tags[1][1]), str(tags[2][1])


def annotations_of(document, axis, kinds=None) -> list:
    handle = axis.dxf.handle
    out = []
    for entity in document.current_space():
        found = annotation_kind(entity)
        if found and found[1] == handle and (kinds is None or found[0] in kinds):
            out.append(entity)
    return out


def axes_in(entities) -> list:
    return [e for e in entities if is_axis(e)]


# -- commands --------------------------------------------------------------------------

def layer_commands(document, kinds) -> list[Command]:
    out = []
    for kind in kinds:
        name, color = LAYERS[kind]
        if name not in document.doc.layers:
            out.append(NewLayerCommand(name, color=color))
    return out


class SetAxisCommand(Command):
    """Make a polyline an axis (or change what its axis remembers): its
    XDATA under the plugin's APPID, and the axis layer. Undo puts both back."""

    name = "road axis"

    def __init__(self, entity, params: AxisParams, layer: str | None = LAYERS["axis"][0]) -> None:
        self.entity = entity
        self.params = params
        self.layer = layer
        self._old_layer = None
        self._old_xdata = None

    def do(self, document) -> None:
        ensure_appid(document.doc, APPID)
        self._old_layer = self.entity.dxf.layer
        self._old_xdata = _tags(self.entity)
        if self.layer and self.layer in document.doc.layers:
            self.entity.dxf.layer = self.layer
        self.entity.set_xdata(APPID, self.params.xdata())
        document.dirty = True

    def undo(self, document) -> None:
        self.entity.dxf.layer = self._old_layer
        if self._old_xdata:
            self.entity.set_xdata(APPID, self._old_xdata)
        else:
            self.entity.discard_xdata(APPID)
        document.dirty = True


def _link(axis):
    """The axis handle, read when the entity is made: the axis may be made
    by an earlier step of the same command (HCURVES)."""
    if isinstance(axis, AddEntityCommand):
        return lambda: axis.entity.dxf.handle
    return lambda: axis.dxf.handle


def _tagged(make, kind: str, link):
    def factory(msp):
        ensure_appid(msp.doc, APPID)
        entity = make(msp)
        entity.set_xdata(APPID, [(1000, ANNOT_TAG), (1000, kind), (1005, link())])
        return entity
    return factory


def _line(a, b, layer: str, kind: str, link) -> Command:
    return AddEntityCommand("CAR-LINE", _tagged(
        lambda msp: msp.add_line((a[0], a[1]), (b[0], b[1])), kind, link), layer=layer)


def _text_entity(msp, text, pos, height, rotation, align):
    from ezdxf.enums import TextEntityAlignment

    entity = msp.add_text(text, height=height, dxfattribs={"rotation": rotation})
    entity.set_placement((pos[0], pos[1]), align=getattr(TextEntityAlignment, align))
    return entity


def _text(text, pos, height, layer, kind, link, rotation=0.0, align="MIDDLE_CENTER") -> Command:
    return AddEntityCommand("CAR-TEXT", _tagged(
        lambda msp: _text_entity(msp, text, pos, height, rotation, align), kind, link),
        layer=layer)


def _along(angle_deg: float):
    """(rotation, alignment) for a label written along a direction away
    from its base point, kept readable: flipped, it ends there instead."""
    rotation = readable_rotation(angle_deg)
    flipped = abs(((angle_deg - rotation) % 360.0) - 180.0) < 1e-6
    return rotation, ("MIDDLE_RIGHT" if flipped else "MIDDLE_LEFT")


def station_label(station: float, regular: bool) -> str:
    """``0+020`` at a regular tick, ``0+013.57`` at the start or the end."""
    return format_station(station, 0 if regular else 2)


def stationing_commands(alignment: geometry.Alignment, params: AxisParams, link) -> list[Command]:
    """Ticks across the axis every ``interval`` metres and their labels,
    on the left of the direction of travel; full kilometres longer and
    larger."""
    out: list[Command] = []
    tick_layer, text_layer = LAYERS["ticks"][0], LAYERS["stations"][0]
    for tick in geometry.station_ticks(alignment, params.interval):
        rad = math.radians(tick.angle)
        nx, ny = -math.sin(rad), math.cos(rad)               # left of travel
        half = params.tick / 2.0 * (1.5 if tick.km else 1.0)
        x, y = tick.point
        a, b = (x - nx * half, y - ny * half), (x + nx * half, y + ny * half)
        out.append(_line(a, b, tick_layer, STATIONS, link))
        height = params.height * (1.5 if tick.km else 1.0)
        gap = 0.5 * params.height
        rotation, align = _along(tick.angle + 90.0)
        out.append(_text(station_label(tick.station, tick.regular),
                         (b[0] + nx * gap, b[1] + ny * gap), height, text_layer,
                         STATIONS, link, rotation, align))
    return out


def _drawing_commands(alignment, params, link, kinds) -> list[Command]:
    out: list[Command] = []
    if STATIONS in kinds:
        out.extend(stationing_commands(alignment, params, link))
    return out


def define_axis(document, entity, params: AxisParams) -> CompositeCommand:
    """ROADAXIS: the polyline becomes an axis with ``params``; whatever was
    already drawn for it is redrawn to match."""
    alignment = alignment_of(entity, params)             # refuses a bad polyline now
    existing = annotations_of(document, entity)
    kinds = {annotation_kind(e)[0] for e in existing}
    commands = layer_commands(document, ("axis", "ticks", "stations"))
    commands.append(SetAxisCommand(entity, params))
    if existing:
        commands.append(EraseCommand(existing))
        commands.extend(_drawing_commands(alignment, params, _link(entity), kinds))
    return CompositeCommand("road axis", commands)


def draw_stationing(document, entity, params: AxisParams | None = None) -> CompositeCommand:
    """STATIONING: the stationing of the axis with ``params`` (or the ones
    it remembers), replacing the one drawn before -- one undo step. A plain
    polyline becomes an axis on the way."""
    params = params or axis_params(entity) or AxisParams()
    alignment = alignment_of(entity, params)
    existing = annotations_of(document, entity)
    kinds = {annotation_kind(e)[0] for e in existing} | {STATIONS}
    commands = layer_commands(document, ("axis", "ticks", "stations"))
    commands.append(SetAxisCommand(entity, params))
    if existing:
        commands.append(EraseCommand(existing))
    commands.extend(_drawing_commands(alignment, params, _link(entity), kinds))
    return CompositeCommand("stationing", commands)


def regenerate(document, axes) -> CompositeCommand:
    """RESTATION: redraw what each axis has drawn (its stationing)
    from the axis as it is now -- after a grip edit, say."""
    commands: list[Command] = layer_commands(document, ("ticks", "stations"))
    for entity in axes:
        params = axis_params(entity)
        if params is None:
            continue
        existing = annotations_of(document, entity)
        kinds = {annotation_kind(e)[0] for e in existing} or {STATIONS}
        alignment = alignment_of(entity, params)
        if existing:
            commands.append(EraseCommand(existing))
        commands.extend(_drawing_commands(alignment, params, _link(entity), kinds))
    return CompositeCommand("restation", commands)


def reverse_axis(document, entity) -> CompositeCommand:
    """AXISREVERSE: the stationing runs the other way, from the same start
    station; what was drawn for the axis is redrawn."""
    params = axis_params(entity) or AxisParams()
    return define_axis(document, entity, replace(params, reverse=not params.reverse))


# -- the tables -------------------------------------------------------------------------

def _f(value: float, decimals: int = 3) -> str:
    return f"{value:.{decimals}f}"


def axis_table_rows(alignment: geometry.Alignment) -> list[list[str]]:
    """Start, every PI, end: station, east, north, and the tangent leaving
    it -- bearing, azimuth and distance to the next one."""
    pis = geometry.points_of_intersection(alignment)
    (x0, y0), _ = alignment.at(0.0)
    (x1, y1), _ = alignment.at(alignment.length)
    stops = [(tr("START"), (x0, y0), alignment.start_station)]
    stops += [(f"PI-{p.number}", p.point, p.station) for p in pis]
    stops.append((tr("END"), (x1, y1), alignment.end_station))
    rows = []
    for i, (name, (x, y), station) in enumerate(stops):
        row = [name, format_station(station), _f(x), _f(y), "", "", ""]
        if i + 1 < len(stops):
            nx, ny = stops[i + 1][1]
            az = cad_to_azimuth(math.degrees(math.atan2(ny - y, nx - x)))
            row[4] = format_bearing(az)
            row[5] = format_dms(az)
            row[6] = _f(math.hypot(nx - x, ny - y))
        rows.append(row)
    return rows


def axis_table(document, entity, insert, text_height: float = 2.0) -> CompositeCommand:
    """AXISTABLE: the cuadro del eje at ``insert`` (top-left)."""
    alignment = alignment_of(entity)
    rows = axis_table_rows(alignment)
    h = text_height
    headers = ["PI", tr("STATION"), tr("EAST"), tr("NORTH"), tr("BEARING"),
               tr("AZIMUTH"), tr("DISTANCE")]
    widths = [w * h for w in (7.0, 8.0, 10.0, 11.0, 12.0, 10.0, 8.0)]
    table = tables.insert_table(insert, cols=7, col_width=10.0 * h, data_rows=len(rows),
                                row_height=2.0 * h, text_height=h, title=tr("AXIS TABLE"),
                                headers=headers, data=rows, col_widths=widths)
    return _on_table_layer(document, table, "axis table")


def _on_table_layer(document, table: CompositeCommand, name: str) -> CompositeCommand:
    commands = layer_commands(document, ("tables",))
    for command in table.commands:
        command.layer = LAYERS["tables"][0]
    commands.extend(table.commands)
    return CompositeCommand(name, commands)
