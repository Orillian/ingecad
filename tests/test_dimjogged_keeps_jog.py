# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A jogged radius keeps its jog when it is redrawn or its text moves.

Rafael's eighth review (min 36-43): dragging the text of a jogged radius
"pierde el recodo, pierde prácticamente todo" -- the redraw came back as a
plain radius to the centre override.
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
    yield window
    window.document.dirty = False
    window.close()


def _lines(win, dim):
    return [e for e in win.document.doc.blocks.get(dim.dxf.geometry)
            if e.dxftype() == "LINE" and e.dxf.layer.lower() != "defpoints"]


def _jogged(win, dim) -> bool:
    """Three segments: override -> parallel -> transverse -> arrow's,
    the last one on the radial line through the true centre (0, 0)."""
    lines = _lines(win, dim)
    if len(lines) != 3:
        return False
    first, last = lines[0], lines[-1]
    a, p = last.dxf.start, last.dxf.end
    on_radial = abs(a.x * p.y - a.y * p.x) <= 1e-6 * math.hypot(p.x, p.y)
    return (first.dxf.start.x, first.dxf.start.y) == pytest.approx(
        (300.0, 100.0)) and on_radial


def test_redraw_and_text_grip_keep_the_jog(win):
    from core import actions

    for text in ("CIRCLE", "0,0", "500", "DIMJOGGED", "500,0", "300,100",
                 "330,330", "300,300"):
        win._on_command_submitted(text)
    dim = win.document.modelspace().query("DIMENSION")[0]
    assert _jogged(win, dim)
    actions.rerender_dimension(win.document, dim)          # a style change
    assert _jogged(win, dim)
    win.history.execute(actions.DimTextEditCommand(          # the text grip
        dim, location=(250.0, 380.0), turn=True))
    assert _jogged(win, dim)
    p = dim.dxf.defpoint4
    assert math.atan2(p.y, p.x) == pytest.approx(math.atan2(380.0, 250.0))
    win.history.undo()
    assert _jogged(win, dim)
