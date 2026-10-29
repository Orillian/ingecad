# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""ZOOM takes what the classic CAD takes in the side-by-side session (group H).

``ZOOM C 150,30 250`` answered "Unknown ZOOM option", and the centre and
height then ran as commands ("Unknown command "150,50""). The classic CAD also
takes ``2X``, a bare scale, All, Scale and a typed first window corner.
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
    for answer in ("LINE", "0,0", "200,100", ""):
        window._on_command_submitted(answer)
    yield window
    window.document.dirty = False
    window.close()


def _type(win, *answers):
    for answer in answers:
        win._on_command_submitted(answer)


def _history(win):
    return win.command_line.history.toPlainText()


def _view(win):
    v = win.viewport.view
    return v.cx, v.cy, v.height / v.scale


def test_zoom_center_with_a_height(win):
    _type(win, "ZOOM", "C", "150,30", "250")
    cx, cy, height = _view(win)
    assert (cx, cy) == pytest.approx((150, 30))
    assert height == pytest.approx(250)
    assert "Unknown" not in _history(win)


def test_zoom_center_with_a_magnification(win):
    _type(win, "ZOOM", "E")
    before = _view(win)[2]
    _type(win, "ZOOM", "_C", "150,60", "2X")
    assert _view(win)[:2] == pytest.approx((150, 60))
    assert _view(win)[2] == pytest.approx(before / 2)


def test_zoom_by_a_factor_of_the_view_and_of_the_drawing(win):
    _type(win, "ZOOM", "E")
    whole = _view(win)[2]
    _type(win, "ZOOM", "2X")
    assert _view(win)[2] == pytest.approx(whole / 2)
    _type(win, "ZOOM", "0.5")                 # of the whole drawing
    assert _view(win)[2] == pytest.approx(whole * 2)
    _type(win, "ZOOM", "S", "2X")
    assert _view(win)[2] == pytest.approx(whole)


def test_a_typed_first_corner_is_a_window(win):
    _type(win, "ZOOM", "-20,-20", "130,80")
    cx, cy, height = _view(win)
    assert (cx, cy) == pytest.approx((55, 30))
    assert height >= 100 - 1e-6
    assert "Unknown" not in _history(win)


def test_all_fits_the_drawing_as_extents(win):
    _type(win, "ZOOM", "E")
    extents = _view(win)
    _type(win, "ZOOM", "W", "10,10", "20,20")
    assert _view(win) != pytest.approx(extents)
    _type(win, "ZOOM", "A")
    assert _view(win) == pytest.approx(extents)


def test_the_spanish_prompt_offers_the_options(win):
    from core import i18n

    source = ("Specify corner of window, enter a scale factor (nX or nXP), or "
              "[All/Center/Extents/Previous/Scale/Window] <Extents>:")
    assert i18n.keywords.collisions(source, i18n.tr(source)) == []
    win._on_command_submitted("ZOOM")
    assert "[All/Center/Extents/Previous/Scale/Window]" in _history(win)
