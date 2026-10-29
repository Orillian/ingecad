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


def _vertices(win, dim):
    return [(q.x, q.y) for e in _lines(win, dim) for q in (e.dxf.start, e.dxf.end)]


def test_an_override_far_to_the_side_steepens_the_jog(win):
    """The audit of the same review: with the override well to the side
    the jog started with a zero-length line and ran past the arc, the
    arrow's segment coming back inwards."""
    for text in ("CIRCLE", "0,0", "100", "DIMJOGGED", "100,0", "60,-60",
                 "120,0", "80,-30"):
        win._on_command_submitted(text)
    dim = win.document.modelspace().query("DIMENSION")[0]
    lines = _lines(win, dim)
    assert all(math.dist((e.dxf.start.x, e.dxf.start.y),
                         (e.dxf.end.x, e.dxf.end.y)) > 1e-6 for e in lines)
    # every vertex but the text's end is inside the arc, the last segment
    # out on the true radial line (y = 0) towards the text
    off = [v for v in _vertices(win, dim) if math.hypot(*v) > 100 + 1e-6]
    assert all(abs(y) < 1e-6 for _, y in off), off
    a = lines[-1].dxf.start
    assert abs(a.y) < 1e-6 and a.x < 100 - 1e-6


def test_no_centre_mark_at_the_true_centre(win):
    """A jogged radius stands in for a centre off the sheet: the text put
    inside drew ezdxf's centre mark there anyway."""
    from core.actions import _current_dimstyle

    doc = win.document.doc
    doc.dimstyles.get(_current_dimstyle(win.document)).dxf.dimcen = -2.5
    for text in ("CIRCLE", "0,0", "100", "DIMJOGGED", "100,0", "60,-60",
                 "50,0", "70,-30"):
        win._on_command_submitted(text)
    dim = win.document.modelspace().query("DIMENSION")[0]
    near = [v for v in _vertices(win, dim) if math.hypot(*v) < 10]
    assert near == [], near
