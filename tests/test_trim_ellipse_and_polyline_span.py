# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""TRIM on a circle, a rectangle and an ellipse that overlap, as AutoCAD.

The author's side-by-side recording (2026-10-29): the same three shapes
trimmed to their outline in AutoCAD; in IngeCAD the ellipse could not be
trimmed ("TRIM supports LINE, PLINE, CIRCLE and ARC"), and the side of the
rectangle inside the circle was cut only to its corner -- the polyline's
own vertex counted as a cut, where AutoCAD removes the whole run between
the two crossings.
"""
from __future__ import annotations

import math

import pytest


@pytest.fixture
def win(qapp):
    from core import actions
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    qapp.processEvents()
    window.new_document()
    t = window.tools
    t.osnap_on = False
    t._execute(actions.add_circle((0, 0), 10))
    for text in ("RECTANG", "5,-5", "20,5", "ELLIPSE", "16,-2", "34,-2", "2.5"):
        window._on_command_submitted(text)
    yield window
    window.document.dirty = False
    window.close()


def _trim_at(win, x, y):
    t = win.tools
    win._on_command_submitted("TRIM")
    win._on_command_submitted("")              # every object is an edge
    t.on_hover(x, y, threshold_world=0.3)
    t.on_click(x, y)
    t.cancel()


def _rect(win):
    (pl,) = win.document.modelspace().query("LWPOLYLINE")
    return [(round(x, 2), round(y, 2)) for x, y in pl.get_points("xy")]


def test_the_rectangle_loses_the_whole_run_inside_the_circle(win):
    _trim_at(win, 6, 5)                       # its top side, inside the circle
    assert _rect(win) == [(8.66, -5), (20, -5), (20, 5), (8.66, 5)]


def test_the_ellipse_trims_inside_the_rectangle(win):
    _trim_at(win, 16, -2)
    (e,) = win.document.modelspace().query("ELLIPSE")
    # what is left is the part outside: from one crossing of x = 20 round
    # the far end to the other, through the parameter 0 at (34, -2)
    cross = math.acos(-5 / 9)
    assert (e.dxf.start_param, e.dxf.end_param) == pytest.approx(
        (math.tau - cross, cross), abs=1e-6)
    win._on_command_submitted("U")
    (e,) = win.document.modelspace().query("ELLIPSE")
    assert e.dxf.end_param - e.dxf.start_param == pytest.approx(math.tau)
