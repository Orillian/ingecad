# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A new Drawing Window Color reaches the drawings kept in other tabs (#81).

"Upon reopening a file, previous changing the Drawing Window Color only
takes effect after menu View Regenerate." Each tab keeps the scene it
built, valid while the drawing does not change; it was resolved against
the old canvas (ACI 7 white over dark), and coming back to the tab -- or
opening the same file again, which brings its tab to the front -- showed
it as it was. A kept scene now also has to match the colours.
"""
from __future__ import annotations

import time

import numpy as np
import pytest


def _wait_regen(qapp, win, timeout_s=20.0):
    t0 = time.monotonic()
    while win._regen_worker is not None and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()


def _line_rgb(scene):
    rgba = scene.lines.data["rgba"]
    assert len(rgba)
    return tuple(int(v) for v in np.unique(rgba[:, :3], axis=0)[0])


def test_coming_back_to_a_tab_shows_the_new_canvas_colour(qapp):
    from core import actions, window_colors
    from views.main_window import MainWindow

    win = MainWindow()
    win.resize(900, 600)
    win.show()
    try:
        win.new_document()
        win.tools._execute(actions.add_line((0, 0), (100, 50)))  # colour 7
        win.regen_in_memory()
        _wait_regen(qapp, win)
        first = win._session
        assert _line_rgb(win.viewport._scene) == (255, 255, 255)

        win.new_document()                       # another drawing in front
        _wait_regen(qapp, win)
        # Options > Display > Colors: a white model canvas, then the regen
        # the dialog asks for (OptionsDialog._open_window_colors)
        window_colors.set_background("model", "#FFFFFF")
        win.regen_in_memory()
        _wait_regen(qapp, win)

        win.switch_document(first)
        _wait_regen(qapp, win)
        scene = win.viewport._scene
        assert scene.background == pytest.approx((1.0, 1.0, 1.0, 1.0))
        assert _line_rgb(scene) == (0, 0, 0)     # ACI 7 over white is black
    finally:
        window_colors.restore_all()
        for session in list(win._sessions):
            session.document.dirty = False
        win.close()
