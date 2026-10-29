# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""LENGTHEN: change the length of objects and the included angle of arcs.

AutoCAD's prompts (LENGTHEN, p. 1034): ``Select an object or
[DElta/Percent/Total/DYnamic]:`` -- picking an object only *reports* its
length; an option then asks for its value and enters a "Select an object
to change or [Undo]:" loop that ends with Enter. The end that moves is the
one nearest the pick.
"""
from __future__ import annotations

from core import modify
from core.i18n import tr
from tools.base import Point, Tool

_LOOP = "Select an object to change or [Undo]:"


class LengthenTool(Tool):
    entity_picker = True

    #: Last values, sticky for the session as AutoCAD's defaults are.
    _delta = 0.0
    _delta_angle = 0.0
    _percent = 100.0
    _total = 1.0
    _total_angle = 57.0

    def start(self) -> None:
        self.name = "LENGTHEN"
        self._mode: str | None = None          # DE, DEA, P, T, TA, DY
        self._value = 0.0
        self._await: str | None = None         # which number the prompt wants
        self._dynamic_entity = None
        self._dynamic_pick: Point | None = None
        self._done: list = []                  # commands of this run, for Undo
        self.prompt("Select an object or [DElta/Percent/Total/DYnamic]:")

    # -- options -----------------------------------------------------------------
    def on_option(self, text: str) -> bool:
        token = self.option(text) or text.strip().upper()
        if self._await is not None:
            return self._take_number(text, token)
        if self._mode is None:
            if token in ("DE", "DELTA"):
                self._await = "DE"
                self.prompt("Enter delta length or [Angle] <{v}>:", v=self.length_text(self._delta))
                return True
            if token in ("P", "PERCENT"):
                self._await = "P"
                self.prompt("Enter percentage length <{v:g}>:", v=self._percent)
                return True
            if token in ("T", "TOTAL"):
                self._await = "T"
                self.prompt("Specify total length or [Angle] <{v}>:", v=self.length_text(self._total))
                return True
            if token in ("DY", "DYNAMIC"):
                self._mode = "DY"
                self.prompt(_LOOP)
                return True
            return False
        if token in ("U", "UNDO") and self._dynamic_entity is None:
            if self._done:
                self._done.pop()
                self.ctx.undo_last()
            self.prompt(_LOOP)
            return True
        return False

    def _take_number(self, text: str, token: str) -> bool:
        cls = type(self)
        if self._await in ("DE", "T") and token in ("A", "ANGLE"):
            self._await = "DEA" if self._await == "DE" else "TA"
            if self._await == "DEA":
                self.prompt("Enter delta angle <{v}>:", v=self.angle_text(self._delta_angle))
            else:
                self.prompt("Specify total angle <{v}>:", v=self.angle_text(self._total_angle))
            return True
        stripped = text.strip()
        defaults = {"DE": cls._delta, "DEA": cls._delta_angle, "P": cls._percent,
                    "T": cls._total, "TA": cls._total_angle}
        if stripped == "":
            value = defaults[self._await]
        else:
            try:
                value = float(stripped)
            except ValueError:
                self.ctx.echo(tr("Requires numeric value."))
                return True
        if self._await in ("P", "T", "TA") and value <= 0:
            self.ctx.echo(tr("Value must be positive."))
            return True
        setattr(cls, {"DE": "_delta", "DEA": "_delta_angle", "P": "_percent",
                      "T": "_total", "TA": "_total_angle"}[self._await], value)
        self._mode, self._value, self._await = self._await, value, None
        self.prompt(_LOOP)
        return True

    def on_enter(self) -> None:
        if self._await is not None:
            self._take_number("", "")
            return
        self.ctx.finish()

    # -- points ------------------------------------------------------------------
    def on_point(self, point: Point) -> None:
        if self._await is not None:
            return                             # a number is wanted, not a pick
        if self._dynamic_entity is not None:
            command = modify.lengthen(self._dynamic_entity, self._dynamic_pick,
                                      "DY", new_end=point)
            self._dynamic_entity = None
            self.entity_picker = True
            self._run(command)
            self.prompt(_LOOP)
            return
        services = self.ctx.services
        entity = services.pick_entity(point) if services else None
        if entity is None:
            self.prompt(_LOOP if self._mode else
                        "Select an object or [DElta/Percent/Total/DYnamic]:")
            return
        if self._mode is None:
            self._report(entity)
            self.prompt("Select an object or [DElta/Percent/Total/DYnamic]:")
            return
        if self._mode == "DY":
            if modify.object_length(entity) is None:
                self.ctx.echo(tr("This object has no length to change."))
                self.prompt(_LOOP)
                return
            self._dynamic_entity, self._dynamic_pick = entity, point
            self.entity_picker = False         # a real point now: snap it
            self.prompt("Specify new end point:")
            return
        self._run(modify.lengthen(entity, point, self._mode, self._value))
        self.prompt(_LOOP)

    def _run(self, command) -> None:
        if command is None:
            self.ctx.echo(tr("This object has no length to change."))
            return
        self.ctx.execute(command)
        self._done.append(command)

    def _report(self, entity) -> None:
        length = modify.object_length(entity)
        if length is None:
            self.ctx.echo(tr("This object has no length to change."))
        elif entity.dxftype() == "ARC":
            self.ctx.echo(tr("Current length: {length:.4f}, included angle: {angle:.0f}",
                             length=length, angle=modify.arc_included_angle(entity)))
        else:
            self.ctx.echo(tr("Current length: {length:.4f}", length=length))


LENGTHEN_TOOL_CLASSES = {"LENGTHEN": LengthenTool}
