# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Angular extension lines reach the vertex when the arc is beyond it.

Rafael's eighth review (min 21, the 45 of his Detalle A): dimensioning
two lines with the arc on the far side of their vertex, the extension
line "tiene que venir justo hasta el punto de origen del ángulo"; IngeCAD
drew none at all. A line that starts past the arc gets its extension back
to the arc; a line the arc crosses gets none (it used to get a
zero-length one).
"""
from __future__ import annotations

import math

import pytest


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.new_document()
    qapp.processEvents()
    doc = window.document.doc
    style = doc.dimstyles.get(doc.header.get("$DIMSTYLE"))
    for key, value in dict(dimasz=0.5, dimtxt=0.5, dimscale=1.0, dimgap=0.2,
                           dimexo=0.3, dimexe=0.3).items():
        style.dxf.set(key, value)
    yield window
    window.document.dirty = False
    window.close()


def _type(win, *texts):
    for text in texts:
        win._on_command_submitted(text)


def _lines(win):
    dim = win.document.modelspace().query("DIMENSION")[-1]
    return [((e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y))
            for e in win.document.doc.blocks.get(dim.dxf.geometry)
            if e.dxftype() == "LINE" and e.dxf.layer.lower() != "defpoints"]


def test_arc_beyond_the_vertex_extends_from_the_vertex(win):
    _type(win, "LINE", "2,0", "10,0", "", "LINE", "-2,-2", "-7,-7", "")
    _type(win, "DIMANGULAR", "6,0", "-5,-5", "-1,3")
    lines = _lines(win)
    assert len(lines) == 2
    for start, end in lines:
        assert start == pytest.approx((0.0, 0.0), abs=1e-9)
        assert math.hypot(*end) == pytest.approx(math.hypot(1, 3) + 0.3)


def test_line_starting_past_the_arc_extends_back_to_it(win):
    _type(win, "LINE", "5,0", "10,0", "", "LINE", "0,0", "0,10", "")
    _type(win, "DIMANGULAR", "7,0", "0,5", "2,2")
    radius = math.hypot(2, 2)
    reach = [ln for ln in _lines(win) if abs(ln[0][1]) < 1e-9
             and abs(ln[1][1]) < 1e-9]
    assert len(reach) == 1
    xs = sorted(x for (x, _y) in reach[0])
    assert xs[0] == pytest.approx(radius - 0.3)     # DIMEXE past the arc
    assert xs[1] == pytest.approx(5.0 - 0.3)        # DIMEXO short of the line


def test_arc_crossing_both_lines_draws_no_extension(win):
    _type(win, "LINE", "0,0", "10,0", "", "LINE", "0,0", "0,10", "")
    _type(win, "DIMANGULAR", "7,0", "0,5", "2,2")
    assert _lines(win) == []
