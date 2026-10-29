# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Every dimension says its text, as the classic CAD does.

Recorded in the side-by-side session (group F): DIMRADIUS, DIMDIAMETER and
DIMANGULAR end with "Dimension text = 30" / "60" / "37", and DIMCONTINUE
says only its text. IngeCAD said nothing after a radius, a diameter or an
angle, and repeated "Non-associative dimension created." at each
continued dimension.
"""
from __future__ import annotations

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


def _pick(win, x, y):
    win.tools.on_hover(x, y, threshold_world=0.5)
    win.tools.on_click(x, y)


def _history(win):
    return win.command_line.history.toPlainText().splitlines()


def _texts(win):
    return [line for line in _history(win)
            if line.startswith("Dimension text = ")]


@pytest.mark.parametrize("command, number", [("DIMRADIUS", "30"),
                                             ("DIMDIAMETER", "60")])
def test_a_radius_or_diameter_says_its_text(win, command, number):
    _type(win, "CIRCLE", "0,0", "30")
    _type(win, command)
    _pick(win, 30, 0)
    _pick(win, 60, 40)
    (text,) = _texts(win)
    assert number in text
    assert "Non-associative dimension created." not in _history(win)


def test_an_angle_says_its_text(win):
    _type(win, "LINE", "0,0", "100,0", "", "LINE", "0,0", "80,60", "")
    _type(win, "DIMANGULAR")
    _pick(win, 50, 0)
    _pick(win, 40, 30)
    _pick(win, 70, 20)
    (text,) = _texts(win)
    assert "36" in text                  # 36.87 deg, at the style's DIMADEC


def test_a_continued_dimension_only_says_its_text(win):
    _type(win, "DIMLINEAR", "0,0", "100,0", "50,-20")
    _type(win, "DIMCONTINUE", "200,0", "", "")
    history = _history(win)
    assert len(_texts(win)) == 2
    assert history.count("Non-associative dimension created.") == 1
