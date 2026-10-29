# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The snap point under the cursor wins, and CEN takes the curve.

Redrawing a tester's part in a new drawing:
- with END and INT on, an END 10 px away beat the INT under the cursor,
  and a 1 mm slot came out of zero-length lines;
- CEN only took the centre with the cursor near the centre itself --
  passing over the arc, as one does in AutoCAD, snapped nothing, and two
  continued dimensions measured from the raw cursor.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.new_document()
    yield window
    window.document.dirty = False
    window.close()


def _hover(win, kinds, x, y, reach):
    t = win.tools
    t.osnap_on = True
    t.osnap_modes = set(kinds)
    win._on_command_submitted("LINE")
    t.on_hover(x, y, threshold_world=reach)
    hit = t.snap_hit
    t.cancel()
    return hit


def test_an_intersection_under_the_cursor_beats_a_farther_endpoint(win):
    from core import actions

    t = win.tools
    t._execute(actions.add_line((0, 5), (20, 5)))
    t._execute(actions.add_line((14.7, -10), (14.7, 20)))
    t._execute(actions.add_line((-10, 3), (14.7, 6)))         # ends 1 above
    hit = _hover(win, {"END", "INT"}, 14.65, 5.02, reach=1.0)
    assert hit is not None and hit.kind == "INT"
    assert (hit.x, hit.y) == pytest.approx((14.7, 5))


def test_an_endpoint_under_the_cursor_still_wins(win):
    from core import actions

    t = win.tools
    t._execute(actions.add_line((0, 5), (20, 5)))
    t._execute(actions.add_line((14.7, -10), (14.7, 20)))
    t._execute(actions.add_line((-10, 3), (14.7, 6)))
    hit = _hover(win, {"END", "INT"}, -9.9, 3.1, reach=1.0)   # a free end
    assert hit is not None and hit.kind == "END"
    assert (hit.x, hit.y) == pytest.approx((-10, 3))


def test_cen_snaps_from_the_arc_itself(win):
    from core import actions

    t = win.tools
    t._execute(actions.add_circle((0, 0), 2.5))
    t._execute(actions.add_arc_3p((23, 0), (20, 3), (17, 0)))
    hit = _hover(win, {"CEN"}, 1.25, 2.17, reach=0.3)       # on the circle
    assert hit is not None and hit.kind == "CEN"
    assert (hit.x, hit.y) == pytest.approx((0, 0))
    hit = _hover(win, {"CEN"}, 20, 3.05, reach=0.3)          # on the arc
    assert hit is not None and (hit.x, hit.y) == pytest.approx((20, 0))
    assert _hover(win, {"CEN"}, 20, -3.05, reach=0.3) is None  # not its sweep


def test_an_endpoint_of_the_arc_beats_its_centre(win):
    from core import actions

    t = win.tools
    t._execute(actions.add_arc_3p((23, 0), (20, 3), (17, 0)))
    hit = _hover(win, {"END", "CEN"}, 23.05, 0.05, reach=0.3)
    assert hit is not None and hit.kind == "END"
