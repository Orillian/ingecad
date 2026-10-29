# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""ARC answers impossible values and negative chords as AutoCAD 2026 did.

Recorded on AutoCAD 2026 (group A of the side-by-side session): a radius
under half the chord answers ``*Invalid*`` and ends the command; a negative
chord draws the major arc. IngeCAD drew the major arc but stored its end
angle past 360 (466 deg), which no AutoCAD file carries.
"""
from __future__ import annotations

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
