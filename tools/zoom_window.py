# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""ZOOM Window as AutoCAD asks for it (ZOOM, p. 2140): "Specify first
corner:", then "Specify opposite corner:" with a rectangle following the
cursor -- two clicks or two typed points, with object snaps like any
other point prompt (#80: the drag on the canvas had none).

In the Model tab and on a sheet; inside an active viewport ZOOM W stays
a drag, since a viewport has no model snaps on purpose (it is for
navigating, and building them cost 2 s on entry).
"""
from __future__ import annotations

import re
from typing import Optional

from tools.base import Point, Tool

#: ``2X``: a factor of the current view, as AutoCAD's ZOOM reads it.
_TIMES = re.compile(r"^\s*([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*[xX]\s*$")


def parse_times(text: str) -> Optional[float]:
    """``2X`` -> 2.0; anything else (``2``, ``2XP``) -> None."""
    match = _TIMES.match(text)
    if match is None:
        return None
    value = float(match.group(1))
    return value if value > 0 else None


class ZoomWindowTool(Tool):
    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.name = "ZOOMWINDOW"
        self._first: Optional[Point] = None

    def start(self) -> None:
        self.prompt("Specify first corner:")

    def on_point(self, point: Point) -> None:
        if self._first is None:
            self._first = point
            self.last_point = point
            self.prompt("Specify opposite corner:")
            return
        (x0, y0), (x1, y1) = self._first, point
        if abs(x1 - x0) < 1e-12 or abs(y1 - y0) < 1e-12:
            self.prompt("Specify opposite corner:")   # a line is not a window
            return
        services = self.ctx.services
        self.ctx.finish()
        if services is not None:
            services.zoom_to_window((min(x0, x1), min(y0, y1),
                                     max(x0, x1), max(y0, y1)))

    def preview_segments(self, cursor: Point) -> list[tuple[Point, Point]]:
        if self._first is None:
            return []
        (x0, y0), (x1, y1) = self._first, cursor
        a, b, c, d = (x0, y0), (x1, y0), (x1, y1), (x0, y1)
        return [(a, b), (b, c), (c, d), (d, a)]

    def on_enter(self) -> None:
        self.ctx.finish()


class ZoomCenterTool(Tool):
    """ZOOM Center as AutoCAD 2026 asks for it (group H): "Specify center
    point:", then "Enter magnification or height <current>:" -- a height
    in drawing units, or ``nX`` of the current view; Enter keeps it."""

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.name = "ZOOMCENTER"
        self._center: Optional[Point] = None

    def _view(self):
        services = self.ctx.services
        return services.window.viewport.view if services is not None else None

    def _height(self) -> float:
        view = self._view()
        return view.height / view.scale if view is not None and view.scale else 0.0

    def start(self) -> None:
        self.prompt("Specify center point:")

    def on_point(self, point: Point) -> None:
        if self._center is None:
            self._center = point
            self.last_point = point
            self._ask_height()

    def _ask_height(self) -> None:
        self.prompt("Enter magnification or height <{height}>:",
                    height=f"{self._height():.4f}")

    def on_option(self, text: str) -> bool:
        if self._center is None:
            return False
        times = parse_times(text)
        try:
            height = self._height() / times if times else float(text)
        except ValueError:
            return False
        if height <= 0:
            self._ask_height()
            return True
        self._zoom(height)
        return True

    def on_enter(self) -> None:
        if self._center is None:
            self.ctx.finish()
        else:
            self._zoom(self._height())

    def _zoom(self, height: float) -> None:
        view = self._view()
        services = self.ctx.services
        self.ctx.finish()
        if view is None or services is None or height <= 0:
            return
        half_h = height / 2.0
        half_w = half_h * view.width / max(view.height, 1)
        cx, cy = self._center
        services.zoom_to_window((cx - half_w, cy - half_h, cx + half_w, cy + half_h))


ZOOM_TOOL_CLASSES = {"ZOOMWINDOW": ZoomWindowTool, "ZOOMCENTER": ZoomCenterTool}
