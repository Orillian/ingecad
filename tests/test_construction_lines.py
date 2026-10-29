# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Construction lines (XLINE, RAY) snap and offset, as in AutoCAD.

Rafael's eighth review: drafters lay XLINEs on Defpoints as a grid of
guides and draw on their crossings. "No funcionan las referencias con este
tipo de línea" (3:52) -- no object snap reached them; and OFFSET answered
"XLINE no se puede desfasar" (5:20), so the grid could not be stepped out.
"""
from __future__ import annotations

import pytest

from core import actions


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


def _type(win, *texts):
    for text in texts:
        win._on_command_submitted(text)


def _hover(win, x, y, modes):
    t = win.tools
    t.osnap_on = True
    t.osnap_modes = set(modes)
    t.on_hover(x, y, threshold_world=0.5)
    return t.snap_hit


def test_a_circle_lands_on_the_crossing_of_two_xlines(win):
    t = win.tools
    t._execute(actions.add_xline((0, 0), 0.0))
    t._execute(actions.add_xline((29.5, 0), 90.0))
    win.dispatcher.submit("CIRCLE")
    hit = _hover(win, 29.7, 0.2, {"INT"})
    assert hit is not None and hit.kind == "INT"
    assert (hit.x, hit.y) == pytest.approx((29.5, 0.0))
    t.on_click(29.7, 0.2)
    _type(win, "2.5")
    circle = win.document.modelspace().query("CIRCLE")[0]
    assert (circle.dxf.center.x, circle.dxf.center.y) == pytest.approx((29.5, 0))


def test_an_xline_crosses_a_circle_far_from_its_base(win):
    t = win.tools
    t._execute(actions.add_xline((0, 0), 0.0))
    t._execute(actions.add_circle((1000, 0), 3.0))
    win.dispatcher.submit("LINE")
    hit = _hover(win, 997.2, 0.2, {"INT"})
    assert hit is not None and (hit.x, hit.y) == pytest.approx((997.0, 0.0))


def test_nearest_and_perpendicular_reach_an_xline(win):
    t = win.tools
    t._execute(actions.add_xline((0, 0), 45.0))
    win.dispatcher.submit("LINE")
    hit = _hover(win, 500.3, 500.0, {"NEA"})
    assert hit is not None and hit.kind == "NEA"
    assert hit.x == pytest.approx(hit.y)
    assert _hover(win, 10.0, 0.0, {"PER"}) is None
    t.on_click(10.0, 0.0)                     # a first point off the line
    hit = _hover(win, 300.2, 300.0, {"PER"})
    assert hit is not None and hit.kind == "PER"
    assert (hit.x, hit.y) == pytest.approx((5.0, 5.0))   # the foot, far away


def test_a_ray_snaps_at_its_base_and_not_behind_it(win):
    t = win.tools
    t._execute(actions.add_ray((10, 10), 0.0))
    win.dispatcher.submit("CIRCLE")
    hit = _hover(win, 10.2, 10.2, {"END"})
    assert hit is not None and hit.kind == "END"
    assert (hit.x, hit.y) == pytest.approx((10.0, 10.0))
    assert _hover(win, 5.0, 10.1, {"NEA"}) is None       # behind the base
    hit = _hover(win, 50.0, 10.1, {"NEA"})
    assert hit is not None and (hit.x, hit.y) == pytest.approx((50.0, 10.0))


def test_an_xline_has_no_endpoint_and_no_midpoint(win):
    t = win.tools
    t._execute(actions.add_xline((0, 0), 0.0))
    win.dispatcher.submit("LINE")
    assert _hover(win, 0.1, 0.1, {"END", "MID"}) is None


def test_offset_steps_an_xline_out_to_a_parallel_xline(win):
    from tools.edit import OffsetTool

    OffsetTool.erase_source = False
    OffsetTool.layer_mode = "source"
    win.tools._execute(actions.add_xline((0, 0), 90.0))
    _type(win, "OFFSET", "29.5", "0,40", "10,0", "")
    xlines = win.document.modelspace().query("XLINE")
    assert len(xlines) == 2, win.command_line.history.toPlainText()[-300:]
    new = xlines[-1]
    assert new.dxf.start.x == pytest.approx(29.5)
    assert (new.dxf.unit_vector.x, new.dxf.unit_vector.y) == pytest.approx((0, 1))
    win.history.undo()
    assert len(win.document.modelspace().query("XLINE")) == 1


def test_offset_through_a_point_keeps_a_ray_a_ray(win):
    from tools.edit import OffsetTool

    OffsetTool.erase_source = False
    OffsetTool.layer_mode = "source"
    win.tools._execute(actions.add_ray((0, 0), 0.0))
    _type(win, "OFFSET", "T", "20,0", "7,-12", "")
    rays = win.document.modelspace().query("RAY")
    assert len(rays) == 2, win.command_line.history.toPlainText()[-300:]
    assert (rays[-1].dxf.start.x, rays[-1].dxf.start.y) == pytest.approx((0, -12))


def test_parallel_takes_an_xline_direction(win):
    from core.snap import SnapEngine

    win.tools._execute(actions.add_xline((0, 0), 30.0))
    engine = SnapEngine(win.document)
    direction = engine.line_direction((866.0, 500.2), 0.5)
    assert direction == pytest.approx((0.8660254, 0.5))
