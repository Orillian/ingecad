# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Zoomed in on a selected ellipse, its highlight lies on the curve.

The author's recording (2026-10-29): selecting an ellipse and zooming in
showed two lines, the smooth curve and a polygon beside it -- the blue
highlight drew the selection index's chords, 1/500 of the ellipse's size
apart, whatever the zoom.
"""
from __future__ import annotations

import math

import numpy as np


def test_the_highlight_of_an_ellipse_follows_the_zoom(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    qapp.processEvents()
    win.new_document()
    try:
        for text in ("ELLIPSE", "-100,0", "100,0", "50"):
            win._on_command_submitted(text)
        (e,) = win.document.modelspace().query("ELLIPSE")
        t, vp = win.tools, win.viewport
        t.selection = {e.dxf.handle}
        t.changed.emit()
        qapp.processEvents()

        def worst_gap_px(scale):
            vp.view.scale = scale              # pixels per drawing unit
            segs, _circles, _boxes = t.highlight_geometry()
            mx = (segs[:, 0] + segs[:, 2]) / 2.0
            my = (segs[:, 1] + segs[:, 3]) / 2.0
            # a chord's midpoint lies inside the curve by its sagitta; on
            # this ellipse (b = 50) the gap is at most (1 - f) * 100
            f = np.sqrt((mx / 100.0) ** 2 + (my / 50.0) ** 2)
            return float(np.max((1.0 - f) * 100.0)) * scale

        assert worst_gap_px(1.0) < 1.0
        assert worst_gap_px(1000.0) < 1.0, "zoomed in, the highlight is a polygon"
    finally:
        win.document.dirty = False
        win.close()
