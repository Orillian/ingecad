# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The interactive side of Roads: thin shells over ``actions``, prompting
the way AutoCAD prompts (English keys, translated through the pack)."""
from __future__ import annotations

from dataclasses import replace

from core.i18n import tr
from core.surveying import format_dms, format_station
from tools.base import Tool

from . import actions, geometry


def _document(ctx):
    document = getattr(ctx.services, "document", None)
    if document is None:
        document = getattr(getattr(ctx.services, "window", None), "document", None)
    return document


def _number(text: str) -> float:
    return float(text.strip().replace(",", "."))


def _polyline_in(entities, axis_first: bool = True):
    """The axis among ``entities`` (or, failing one, the first open
    LWPOLYLINE)."""
    polylines = [e for e in entities if e.dxftype() == "LWPOLYLINE" and not e.closed]
    if axis_first:
        for entity in polylines:
            if actions.is_axis(entity):
                return entity
    return polylines[0] if polylines else None


class _AxisTool(Tool):
    """Select one polyline, then ask; subclasses say what to ask."""

    wants_selection = True

    def start(self) -> None:
        self._entity = None

    def selection_prompt(self) -> str:
        return tr("Select the axis polyline:")

    def on_selection(self, entities: list) -> None:
        self._entity = _polyline_in(entities)
        if self._entity is None:
            self.ctx.echo(tr("The selection has no open polyline."))
            self.ctx.finish()
            return
        self.picked()

    def picked(self) -> None: ...

    def run(self, command) -> None:
        """Execute, or say why not, and finish the command either way."""
        try:
            built = command()
        except ValueError as exc:
            self.ctx.echo(tr("Cannot do it: {error}", error=exc))
            self.ctx.finish()
            return
        self.ctx.execute(built)
        self.ctx.finish()


class RoadAxisTool(_AxisTool):
    """ROADAXIS: a polyline of tangents and arcs becomes a road axis with
    its start station and direction."""

    def start(self) -> None:
        super().start()
        self.name = "ROADAXIS"

    def picked(self) -> None:
        self._params = actions.axis_params(self._entity) or actions.AxisParams()
        self._ask()

    def _ask(self) -> None:
        self.prompt("Start station <{s}> or [Reverse]:", s=format_station(self._params.start))

    def wants_raw_text(self) -> bool:
        # "1+250.50" is a station, not arithmetic: the command line would
        # otherwise hand over 251.5
        return self._entity is not None

    def on_option(self, text: str) -> bool:
        if self._entity is None:
            return False
        if self.option(text) == "R":
            self._params = replace(self._params, reverse=not self._params.reverse)
            self.ctx.echo(tr("Stationing runs from the last vertex.") if self._params.reverse
                          else tr("Stationing runs from the first vertex."))
            self._ask()
            return True
        try:
            start = geometry.parse_station(text)
        except ValueError:
            self.ctx.echo(tr("Invalid station: {text}", text=text))
            return True
        self._params = replace(self._params, start=start)
        self._finish()
        return True

    def on_enter(self) -> None:
        if self._entity is None:
            self.ctx.finish()
            return
        self._finish()

    def _finish(self) -> None:
        def build():
            command = actions.define_axis(_document(self.ctx), self._entity, self._params)
            length = actions.alignment_of(self._entity, self._params).length
            self.ctx.echo(tr("Axis from {a} to {b} ({n:.3f} m).",
                             a=format_station(self._params.start),
                             b=format_station(self._params.start + length), n=length))
            return command
        self.run(build)


class StationingTool(_AxisTool):
    """STATIONING: ticks and station labels along the axis every N metres,
    replacing the ones drawn before."""

    def start(self) -> None:
        super().start()
        self.name = "STATIONING"
        self._stage = ""

    def picked(self) -> None:
        self._params = actions.axis_params(self._entity) or actions.AxisParams()
        self._stage = "interval"
        self.prompt("Station interval <{v:g}>:", v=self._params.interval)

    def on_option(self, text: str) -> bool:
        if not self._stage:
            return False
        try:
            value = _number(text)
            if value <= 0:
                raise ValueError(text)
        except ValueError:
            self.ctx.echo(tr("Invalid number: {text}", text=text))
            return True
        self._take(value)
        return True

    def on_enter(self) -> None:
        if not self._stage:
            self.ctx.finish()
            return
        self._take(None)

    def _take(self, value) -> None:
        if self._stage == "interval":
            if value is not None:
                self._params = replace(self._params, interval=value)
            self._stage = "tick"
            self.prompt("Tick length <{v:g}>:", v=self._params.tick)
        elif self._stage == "tick":
            if value is not None:
                self._params = replace(self._params, tick=value)
            self._stage = "height"
            self.prompt("Text height <{v:g}>:", v=self._params.height)
        elif self._stage == "height":
            if value is not None:
                self._params = replace(self._params, height=value)
            self._stage = ""
            self.run(lambda: actions.draw_stationing(_document(self.ctx), self._entity,
                                                     self._params))


class RestationTool(Tool):
    """RESTATION: redraw the stationing of the selected axes from their
    current shape and the settings each one remembers."""

    wants_selection = True

    def start(self) -> None:
        self.name = "RESTATION"

    def selection_prompt(self) -> str:
        return tr("Select the axes to restation:")

    def on_selection(self, entities: list) -> None:
        axes = actions.axes_in(entities)
        if not axes:
            self.ctx.echo(tr("The selection has no road axis."))
            self.ctx.finish()
            return
        try:
            command = actions.regenerate(_document(self.ctx), axes)
        except ValueError as exc:
            self.ctx.echo(tr("Cannot do it: {error}", error=exc))
            self.ctx.finish()
            return
        self.ctx.execute(command)
        self.ctx.echo(tr("{n} axes restationed.", n=len(axes)))
        self.ctx.finish()


class AxisReverseTool(_AxisTool):
    """AXISREVERSE: the stationing of the axis runs the other way."""

    def start(self) -> None:
        super().start()
        self.name = "AXISREVERSE"

    def picked(self) -> None:
        self.run(lambda: actions.reverse_axis(_document(self.ctx), self._entity))


class _TableTool(_AxisTool):
    """Select the axis, click the top-left corner of the table."""

    def start(self) -> None:
        super().start()
        self._height = 2.0
        self._await_height = False

    def picked(self) -> None:
        params = actions.axis_params(self._entity)
        if params is not None:
            self._height = params.height
        self._ask()

    def _ask(self) -> None:
        self._await_height = False
        self.prompt("Specify insertion point (top-left) or [Height]:")

    def on_option(self, text: str) -> bool:
        if self._entity is None:
            return False
        if self._await_height:
            try:
                self._height = _number(text)
                if self._height <= 0:
                    raise ValueError(text)
            except ValueError:
                self.ctx.echo(tr("Invalid number: {text}", text=text))
                return True
            self._ask()
            return True
        if self.option(text) == "H":
            self._await_height = True
            self.prompt("Text height <{v:g}>:", v=self._height)
            return True
        return False

    def on_enter(self) -> None:
        if self._await_height:
            self._ask()
            return
        self.ctx.finish()

    def on_point(self, point) -> None:
        if self._entity is None or self._await_height:
            return
        self.run(lambda: self.table(_document(self.ctx), point))

    def table(self, document, point): ...


class AxisTableTool(_TableTool):
    """AXISTABLE: the cuadro del eje -- PIs, stations, coordinates, bearings
    and distances."""

    def start(self) -> None:
        super().start()
        self.name = "AXISTABLE"

    def table(self, document, point):
        return actions.axis_table(document, self._entity, point, self._height)


class CurveTableTool(_TableTool):
    """CURVETABLE: the cuadro de elementos de curva, one row per curve."""

    def start(self) -> None:
        super().start()
        self.name = "CURVETABLE"

    def table(self, document, point):
        return actions.curve_table(document, self._entity, point, self._height)


class HorizontalCurvesTool(_AxisTool):
    """HCURVES: a chain of tangents (its vertices are the PIs) becomes an
    axis with a simple circular curve at every PI: one radius for all, or
    one typed per PI."""

    #: the last radius typed, offered again as the default
    last_radius = 100.0

    def start(self) -> None:
        super().start()
        self.name = "HCURVES"
        self._points = None
        self._turns = []
        self._radii = []
        self._each = False

    def selection_prompt(self) -> str:
        return tr("Select the polyline of tangents:")

    def picked(self) -> None:
        try:
            self._points = actions.tangent_points(self._entity)
        except ValueError as exc:
            self.ctx.echo(tr("Cannot do it: {error}", error=exc))
            self.ctx.finish()
            return
        self._turns = geometry.deflections(self._points)
        self.ctx.echo(tr("{n} PIs.", n=len(self._turns)))
        self._ask_all()

    def _ask_all(self) -> None:
        self._each = False
        self.prompt("Radius for every PI <{r:g}> or [Each]:", r=HorizontalCurvesTool.last_radius)

    def _next_pi(self) -> None:
        """Ask the radius of the next PI that turns; build after the last."""
        while len(self._radii) < len(self._turns) and abs(self._turns[len(self._radii)]) < 1e-7:
            self._radii.append(0.0)                 # aligned tangents: no curve
        if len(self._radii) == len(self._turns):
            self._build()
            return
        i = len(self._radii)
        self.prompt("Radius at PI-{n} (deflection {d}) <{r:g}>:", n=i + 1,
                    d=format_dms(abs(self._turns[i])), r=HorizontalCurvesTool.last_radius)

    def on_option(self, text: str) -> bool:
        if self._points is None:
            return False
        if not self._each and self.option(text) == "E":
            self._each = True
            self._radii = []
            self._next_pi()
            return True
        try:
            radius = _number(text)
            if radius <= 0:
                raise ValueError(text)
        except ValueError:
            self.ctx.echo(tr("Invalid radius: {text}", text=text))
            return True
        HorizontalCurvesTool.last_radius = radius
        self._take(radius)
        return True

    def on_enter(self) -> None:
        if self._points is None:
            self.ctx.finish()
            return
        self._take(HorizontalCurvesTool.last_radius)

    def _take(self, radius: float) -> None:
        if self._each:
            self._radii.append(radius)
            self._next_pi()
        else:
            self._radii = [radius] * len(self._turns)
            self._build()

    def _build(self) -> None:
        try:
            command = actions.fit_axis(_document(self.ctx), self._entity, self._radii)
        except geometry.TangentOverlap as exc:
            where = (f"PI-{exc.first}" if exc.first == exc.second
                     else f"PI-{exc.first} / PI-{exc.second}")
            self.ctx.echo(tr("Cannot fit the curves: the tangents overlap at {where} "
                             "(T1 + T2 = {need:.3f} m > {have:.3f} m). Use smaller radii.",
                             where=where, need=exc.needed, have=exc.available))
            self.ctx.finish()
            return
        except ValueError as exc:
            self.ctx.echo(tr("Cannot do it: {error}", error=exc))
            self.ctx.finish()
            return
        self.ctx.execute(command)
        alignment = actions.alignment_of(command.axis_command.entity)
        n = sum(1 for pi in geometry.points_of_intersection(alignment) if pi.curve)
        self.ctx.echo(tr("{n} curves fitted; axis from {a} to {b}.", n=n,
                         a=format_station(alignment.start_station),
                         b=format_station(alignment.end_station)))
        self.ctx.finish()


TOOL_CLASSES = {
    "ROADAXIS": RoadAxisTool,
    "STATIONING": StationingTool,
    "RESTATION": RestationTool,
    "AXISREVERSE": AxisReverseTool,
    "AXISTABLE": AxisTableTool,
    "HCURVES": HorizontalCurvesTool,
    "CURVETABLE": CurveTableTool,
}
