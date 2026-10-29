# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A radius whose text the user placed keeps it there on a redraw.

Rafael's eighth review: every radius of his part had its text dragged out
along the radial line; re-drawing them (a style change, making the style
annotative) pulled each text back against its circle -- R5 at 11.8 units
from the centre landed at 5.3.
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


def _text_at(win, dim):
    from core.actions import _block_text_insert

    return _block_text_insert(win.document, dim.dxf.geometry)


def test_dragged_radius_text_survives_a_redraw(win):
    from core.actions import rerender_dimension

    for text in ("CIRCLE", "0,0", "5", "DIMRADIUS", "5,0", "12,0"):
        win._on_command_submitted(text)
    dim = win.document.modelspace().query("DIMENSION")[0]
    assert int(dim.dxf.dimtype) & 128
    before = _text_at(win, dim)
    assert math.hypot(*before) > 10.0
    rerender_dimension(win.document, dim)
    after = _text_at(win, dim)
    assert after == pytest.approx(before, abs=1e-9)
