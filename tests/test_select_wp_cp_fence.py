# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""WPolygon, CPolygon and Fence at "Select objects:" (SELECT, Command
Reference): "ERASE, WP, Enter" said "*Invalid selection*" -- the three
polygon methods an AutoCAD hand reaches for on a dense plan were refused.

Every test runs the real path: the command typed on the command line, the
vertices clicked through the tool controller, Enter to close, Enter to end.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from core import actions

# An L-shaped (concave) polygon: its bounding window would also take what
# sits in the notch, the polygon must not.
L_SHAPE = [(0, 0), (12, 0), (12, 4), (4, 4), (4, 12), (0, 12)]


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    window.new_document()
    t = window.tools
    t._execute(actions.add_line((2, 2), (8, 2)))            # inside the foot
    t._execute(actions.add_line((7, 7), (9, 9)))            # in the notch
    t._execute(actions.add_line((8, 1), (20, 1)))           # crosses an edge
    t._execute(actions.add_circle((2, 8), 1.0))             # inside the leg
    t._execute(actions.add_circle((4, 9), 1.0))             # on the leg's edge
    t._execute(actions.add_line((30, 0), (40, 0)))          # far away
    window.viewport.view.zoom_extents(-5, -5, 45, 15)
    qapp.processEvents()
    yield window
    window.document.dirty = False
    window.close()


def _type(win, text):
    edit = win.command_line.input
    edit.setFocus()
    if text:
        QTest.keyClicks(edit, text)
    QTest.keyClick(edit, Qt.Key_Return)


def _left(win):
    """What survived, as 'L x0,y0' / 'C x,y' labels."""
    out = []
    for e in win.document.modelspace():
        if e.dxftype() == "LINE":
            out.append(f"L {e.dxf.start.x:g},{e.dxf.start.y:g}")
        else:
            out.append(f"C {e.dxf.center.x:g},{e.dxf.center.y:g}")
    return sorted(out)


def _erase_with(win, option, points):
    _type(win, "ERASE")
    _type(win, option)
    for x, y in points:
        win.tools.on_click(x, y)
    _type(win, "")          # closes the polygon / ends the fence
    _type(win, "")          # ends "Select objects:"


def test_wpolygon_takes_only_what_is_fully_inside(win):
    _erase_with(win, "WP", L_SHAPE)
    # the foot's line and the leg's circle go; the notch line (inside the
    # bounding window, outside the polygon) and the circle on the edge stay
    assert _left(win) == ["C 4,9", "L 30,0", "L 7,7", "L 8,1"]


def test_cpolygon_also_takes_what_crosses(win):
    _erase_with(win, "CP", L_SHAPE)
    assert _left(win) == ["L 30,0", "L 7,7"]


def test_a_curve_partly_inside_cpolygon_yes_wpolygon_no(win):
    # a triangle over the right half of the circle at (4, 9) only
    tri = [(4, 7), (7, 9), (4, 11)]
    _erase_with(win, "WP", tri)
    assert "C 4,9" in _left(win)
    _erase_with(win, "CP", tri)
    assert "C 4,9" not in _left(win)


def test_fence_takes_what_it_crosses_and_not_what_its_legs_surround(win):
    # one leg through the leg circle and the foot line; the notch line and
    # the circle on the edge are nowhere near it
    _erase_with(win, "F", [(1, 12), (3, -1)])
    left = _left(win)
    assert "C 2,8" not in left and "L 2,2" not in left
    assert "L 7,7" in left and "C 4,9" in left


def test_a_fence_may_cross_itself(win):
    # a bow tie around the far line: allowed for a fence, unlike WP/CP
    _erase_with(win, "F", [(30, 1), (40, -1), (40, 1), (30, -1)])
    assert "L 30,0" not in _left(win)
    assert len(_left(win)) == 5


def test_fence_crossing_a_circle_but_not_one_it_lies_inside(win):
    win.tools._execute(actions.add_circle((20, 8), 5.0))
    # a short fence entirely inside the big circle touches no curve
    _erase_with(win, "F", [(19, 8), (21, 8)])
    assert "C 20,8" in _left(win)
    # a chord across it does
    _erase_with(win, "F", [(14, 6), (26, 6)])
    assert "C 20,8" not in _left(win)


def test_undo_takes_the_last_vertex_back(win):
    _type(win, "ERASE")
    _type(win, "WP")
    for x, y in L_SHAPE[:3]:
        win.tools.on_click(x, y)
    win.tools.on_click(30, 30)                    # a stray vertex
    _type(win, "U")
    for x, y in L_SHAPE[3:]:
        win.tools.on_click(x, y)
    _type(win, "")
    _type(win, "")
    assert _left(win) == ["C 4,9", "L 30,0", "L 7,7", "L 8,1"]


def test_typed_vertices_and_prompts(win):
    _type(win, "ERASE")
    _type(win, "CP")
    history = win.command_line.history.toPlainText
    assert ("First polygon point" in history()
            or "Primer punto del polígono" in history())
    for x, y in L_SHAPE:
        _type(win, f"{x},{y}")
    assert ("Specify endpoint of line or [Undo]" in history()
            or "Precise punto final de línea" in history())
    _type(win, "")
    _type(win, "")
    assert _left(win) == ["L 30,0", "L 7,7"]


def test_a_polygon_may_not_cross_itself(win):
    _type(win, "ERASE")
    _type(win, "WP")
    for x, y in ((0, 0), (12, 12), (12, 0)):
        win.tools.on_click(x, y)
    win.tools.on_click(0, 12)        # bow tie: refused, the polygon stays
    text = win.command_line.history.toPlainText()
    assert ("polygon segments cannot intersect" in text
            or "no pueden cortarse" in text)
    assert win.tools._sel_poly[1] == [(0, 0), (12, 12), (12, 0)]
    win.tools.cancel()


def test_a_locked_layer_and_remove_mode_as_with_a_window(win):
    doc = win.document.doc
    doc.layers.add("CANDADO").lock()
    foot = [e for e in doc.modelspace().query("LINE")
            if e.dxf.start.y == 2][0]
    foot.dxf.layer = "CANDADO"
    _erase_with(win, "CP", L_SHAPE)
    assert _left(win) == ["L 2,2", "L 30,0", "L 7,7"]
    win._cmd_undo()
    foot.dxf.layer = "0"
    # ALL, then Remove with a fence over the far line
    _type(win, "ERASE")
    _type(win, "ALL")
    _type(win, "R")
    _type(win, "F")
    win.tools.on_click(35, -1)
    win.tools.on_click(35, 1)
    _type(win, "")
    _type(win, "")
    assert _left(win) == ["L 30,0"]


def test_the_rubber_band_follows_the_cursor_and_closes(win):
    _type(win, "ERASE")
    _type(win, "WP")
    t = win.tools
    assert t.selection_polygon() is None          # nothing clicked yet
    t.on_click(0, 0)
    t.on_click(12, 0)
    t.on_hover(6, 8)
    mode, points = t.selection_polygon()
    assert mode == "WP" and points == [(0, 0), (12, 0), (6, 8)]
    t.cancel()
    assert t.selection_polygon() is None


def test_a_circle_crossing_the_notch_is_not_inside_the_wpolygon(win):
    # its box sits within the polygon's box and its 0-degree point lies in
    # the foot, but it pokes up across the foot's top edge
    win.tools._execute(actions.add_circle((4.5, 3.5), 0.8))
    _erase_with(win, "WP", L_SHAPE)
    assert "C 4.5,3.5" in _left(win)
    _erase_with(win, "CP", L_SHAPE)
    assert "C 4.5,3.5" not in _left(win)


def test_a_drag_while_drawing_a_polygon_is_a_vertex_not_a_window(win):
    _type(win, "ERASE")
    _type(win, "WP")
    t = win.tools
    t.on_click(0, 0)
    t.start_window(12, 0)        # what the viewport does on a drag
    t.on_click(12, 4)
    t.on_hover(6, 6)
    assert t.selection_rect() is None
    assert t._sel_poly[1] == [(0, 0), (12, 4)]
    t.cancel()


def test_stretch_by_crossing_polygon_moves_only_the_caught_end(win):
    # STRETCH asks for "crossing-window or crossing-polygon": a CPolygon
    # around the far line's right end stretches it, the left end holds
    _type(win, "STRETCH")
    _type(win, "CP")
    for x, y in ((38, -1), (42, -1), (42, 1), (38, 1)):
        win.tools.on_click(x, y)
    for text in ("", "", "0,0", "5,0"):
        _type(win, text)
    far = [e for e in win.document.modelspace().query("LINE")
           if e.dxf.start.x == 30][0]
    assert (far.dxf.start.x, far.dxf.end.x) == (30, 45)


def test_a_forced_crossing_previews_as_a_crossing_either_way(win):
    _type(win, "ERASE")
    _type(win, "C")
    t = win.tools
    t.on_click(0, 0)
    t.on_hover(10, 10)             # left to right, yet Crossing was typed
    assert t.selection_rect()[1] is True
    t.cancel()
