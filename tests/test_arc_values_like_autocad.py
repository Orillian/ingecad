# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""ARC answers impossible values and negative chords as AutoCAD 2026 did.

Recorded on AutoCAD 2026 (group A of the side-by-side session): a radius
under half the chord answers ``*Invalid*`` and ends the command; a negative
chord draws the major arc. IngeCAD drew the major arc but stored its end
angle past 360 (466 deg), which no AutoCAD file carries.
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
    window.tools.osnap_on = False
    yield window
    window.document.dirty = False
    window.close()


def _type(win, *answers):
    for answer in answers:
        win._on_command_submitted(answer)


def _arcs(win):
    return [e for e in win.document.modelspace() if e.dxftype() == "ARC"]


def test_a_negative_chord_stores_angles_inside_a_turn(win):
    _type(win, "ARC", "600,100", "_C", "650,100", "_L", "-60")
    (arc,) = _arcs(win)
    assert 0 <= arc.dxf.start_angle < 360 and 0 <= arc.dxf.end_angle < 360
    assert arc.dxf.start_angle == pytest.approx(180)
    # the major arc: 360 - 73.74 deg of sweep, counterclockwise
    assert arc.dxf.end_angle == pytest.approx(106.26, abs=0.01)


def test_a_radius_under_half_the_chord_is_invalid(win):
    _type(win, "ARC", "400,450", "_E", "500,450", "_R", "10")
    assert _arcs(win) == []
    history = win.command_line.history.toPlainText().splitlines()
    assert history[-1] == "*Invalid*"
    assert not win.tools.active()


# A value prompt answered with a click (group A-extra, AutoCAD 2026 with
# the mouse): what the value is, and the point it is measured from.

def _click(win, x, y):
    win.tools.on_click(x, y)


def test_a_clicked_included_angle_is_the_direction_from_the_center(win):
    _type(win, "ARC", "200,0", "_C", "250,0", "_A")
    seg = win.tools.tool.preview_segments((250, 80))[0]
    assert seg == ((250, 0), (250, 80))       # elastic line from the centre
    _click(win, 250, 80)
    (arc,) = _arcs(win)
    assert (arc.dxf.start_angle, arc.dxf.end_angle) == pytest.approx((180, 270))


def test_a_clicked_chord_is_the_distance_from_the_start(win):
    _type(win, "ARC", "200,0", "_C", "250,0", "_L")
    _click(win, 250, 80)                      # 94.3398 from the start
    (arc,) = _arcs(win)
    assert arc.dxf.start_angle == pytest.approx(180)
    # 2 asin(94.3398 / 100) = 141.26 deg; AutoCAD's LIST rounded it to 321
    assert arc.dxf.end_angle == pytest.approx(321.26, abs=0.01)


def test_a_clicked_radius_is_the_distance_from_the_end(win):
    _type(win, "ARC", "200,0", "_E", "300,0", "_R")
    _click(win, 250, 80)                      # 94.3398 from the end
    (arc,) = _arcs(win)
    assert arc.dxf.radius == pytest.approx(94.3398, abs=1e-4)
    assert (arc.dxf.center.x, arc.dxf.center.y) == pytest.approx((250, 80))


def test_a_clicked_angle_after_the_end_is_measured_from_the_start(win):
    _type(win, "ARC", "200,0", "_E", "300,0", "_A")
    _click(win, 260, 96)                      # direction 58 deg from the start
    (arc,) = _arcs(win)
    half = math.atan2(96, 60) / 2
    assert arc.dxf.radius == pytest.approx(50 / math.sin(half), abs=1e-6)
    assert arc.dxf.radius == pytest.approx(103.142, abs=1e-3)   # AutoCAD's LIST


def test_the_three_point_preview_is_the_arc_not_the_circle(win):
    """ARC 3P showed the whole circle through the three points while the
    end was sought (Marco: "me sale todo el tiempo un círculo"); the classic CAD
    shows the arc that will be drawn, and so does IngeCAD now."""
    _type(win, "ARC", "0,0", "50,50")
    cursor = (100, 0)
    segments = win.tools.tool.preview_segments(cursor)
    points = [p for seg in segments for p in seg]
    # every point of the preview is on the upper half -- the arc from
    # (0,0) through (50,50) to (100,0); the circle's lower half is not
    assert min(y for _x, y in points) > -1e-6
    assert max(y for _x, y in points) == pytest.approx(50, abs=0.5)
    _click(win, *cursor)
    (arc,) = _arcs(win)
    assert (arc.dxf.start_angle % 360, arc.dxf.end_angle % 360) == \
        pytest.approx((0, 180))
