# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""AREA by points asks as the classic CAD does (group H of the side-by-side session).

"Specify next point or [Arc/Length/Undo]:", with Total offered from the
third point on ("[Arc/Length/Undo/Total] <Total>:"); the rectangle 0,0
100,0 100,60 0,60 gives "Area = 6000.0000, Perimeter = 320.0000". IngeCAD
asked "Specify next point or press Enter for total:" with no options:
no arcs, no length, and a wrong point meant starting over.
"""
from __future__ import annotations

import math

import pytest


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    window.new_document()
    window.tools.osnap_on = False
    yield window
    window.document.dirty = False
    window.close()


def _type(win, *answers):
    for answer in answers:
        win._on_command_submitted(answer)


def _lines(win):
    return win.command_line.history.toPlainText().splitlines()


def _area_line(win):
    return next(line for line in reversed(_lines(win)) if line.startswith("Area ="))


def _u(win):
    return win.tools.units()


def test_the_prompts_and_the_rectangle(win):
    _type(win, "AREA", "0,0")
    assert _lines(win)[-1] == "Specify next point or [Arc/Length/Undo]:"
    _type(win, "100,0")
    assert _lines(win)[-1] == "Specify next point or [Arc/Length/Undo]:"
    _type(win, "100,60")
    assert _lines(win)[-1] == "Specify next point or [Arc/Length/Undo/Total] <Total>:"
    _type(win, "0,60", "")
    u = _u(win)
    assert _area_line(win) == (f"Area = {u.area(6000)}, "
                               f"Perimeter = {u.length(320)}")


def test_undo_drops_the_last_point(win):
    _type(win, "AREA", "0,0", "100,0", "500,500", "U", "100,60", "0,60", "T")
    u = _u(win)
    assert _area_line(win).startswith(f"Area = {u.area(6000)},")


def test_length_follows_the_last_segment(win):
    # up the side, then 60 more along it, to 0,160 -- not along +X, where a
    # bare number at a point prompt would go
    _type(win, "AREA", "0,0", "0,100", "L", "60")
    _type(win, "-60,160", "-60,0", "")
    u = _u(win)
    assert _area_line(win) == (f"Area = {u.area(160 * 60)}, "
                               f"Perimeter = {u.length(2 * 160 + 2 * 60)}")


def test_an_arc_segment_counts_exactly(win):
    # 0,0 -> 100,0 straight, then a tangent arc up to 100,100: it leaves
    # east and turns north -- a half circle of radius 50 bulging to +X,
    # then back along the top and down the side
    _type(win, "AREA", "0,0", "100,0", "A", "100,100", "L", "0,100", "")
    u = _u(win)
    area = 100 * 100 + math.pi * 50 ** 2 / 2
    perimeter = 100 + math.pi * 50 + 100 + 100
    assert _area_line(win) == (f"Area = {u.area(area)}, "
                               f"Perimeter = {u.length(perimeter)}")
