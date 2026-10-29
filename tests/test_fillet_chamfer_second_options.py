# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""FILLET and CHAMFER offer their settings at the second object too, as
the classic CAD does (group D): "Select second object or shift-select to
apply corner or [Radius]:" and "Select second line ... or
[Distance/Angle/Method]:", back to that same prompt after the value. The
polyline prompt offers them as well. IngeCAD offered nothing there."""
from __future__ import annotations

import math

import pytest


@pytest.fixture
def win(qapp):
    from tools.edit import FilletTool
    from tools.modify import ChamferTool
    from views.main_window import MainWindow

    saved = (FilletTool.radius, ChamferTool.dist1, ChamferTool.dist2,
             ChamferTool.method)
    FilletTool.radius = 0.0
    ChamferTool.dist1 = ChamferTool.dist2 = 0.0
    ChamferTool.method = "D"
    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    window.new_document()
    window.tools.osnap_on = False
    for answer in ("LINE", "0,0", "100,0", "", "LINE", "0,0", "0,100", ""):
        window._on_command_submitted(answer)
    yield window
    (FilletTool.radius, ChamferTool.dist1, ChamferTool.dist2,
     ChamferTool.method) = saved
    window.document.dirty = False
    window.close()


def _pick(win, x, y):
    win.tools.on_hover(x, y, threshold_world=0.5)
    win.tools.on_click(x, y)


def _last(win):
    return win.command_line.history.toPlainText().splitlines()[-1]


def test_fillet_radius_at_the_second_object(win):
    win._on_command_submitted("FILLET")
    _pick(win, 60, 0)
    assert _last(win).endswith("shift-select to apply corner or [Radius]:")
    win._on_command_submitted("R")
    win._on_command_submitted("15")
    assert _last(win).endswith("shift-select to apply corner or [Radius]:")
    _pick(win, 0, 60)
    (arc,) = win.document.modelspace().query("ARC")
    assert arc.dxf.radius == pytest.approx(15)
    assert (arc.dxf.center.x, arc.dxf.center.y) == pytest.approx((15, 15))


def test_chamfer_distances_at_the_second_line(win):
    win._on_command_submitted("CHAMFER")
    _pick(win, 60, 0)
    assert _last(win).endswith("or [Distance/Angle/Method]:")
    for answer in ("D", "10", "20"):
        win._on_command_submitted(answer)
    assert _last(win).endswith("or [Distance/Angle/Method]:")
    _pick(win, 0, 60)
    lines = list(win.document.modelspace().query("LINE"))
    bevel = [l for l in lines if l.dxf.start.x * l.dxf.end.x == 0
             and l.dxf.start.y * l.dxf.end.y == 0
             and math.dist(l.dxf.start, l.dxf.end) > 1
             and min(l.dxf.start.x, l.dxf.end.x) == 0
             and max(l.dxf.start.x, l.dxf.end.x) == pytest.approx(10)]
    assert len(bevel) == 1
    ends = sorted([(round(bevel[0].dxf.start.x, 6), round(bevel[0].dxf.start.y, 6)),
                   (round(bevel[0].dxf.end.x, 6), round(bevel[0].dxf.end.y, 6))])
    assert ends == [(0, 20), (10, 0)]


def test_the_polyline_prompts_offer_the_settings(win):
    win._on_command_submitted("FILLET")
    win._on_command_submitted("P")
    assert _last(win).endswith("Select 2D polyline or [Radius]:")
    win._on_command_submitted("R")
    win._on_command_submitted("5")
    assert _last(win).endswith("Select 2D polyline or [Radius]:")
    win.tools.cancel()
    win._on_command_submitted("CHAMFER")
    win._on_command_submitted("P")
    assert _last(win).endswith("Select 2D polyline or [Distance/Angle/Method]:")


def test_fillet_starts_with_the_drawings_radius_and_keeps_a_new_one(win):
    """FILLET said "Radius = 0.000" in a drawing whose $FILLETRAD is 10;
    the classic CAD starts from the drawing's radius and saves a new one
    into it."""
    win.document.doc.header["$FILLETRAD"] = 10.0
    win._on_command_submitted("FILLET")
    history = win.command_line.history.toPlainText()
    assert "Radius = 10.000" in history
    for answer in ("R", "7"):
        win._on_command_submitted(answer)
    assert win.document.doc.header["$FILLETRAD"] == 7.0
