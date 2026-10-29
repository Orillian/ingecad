# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""An angle's text reads from the bottom or the right and sits ABOVE its
arc as it is read -- ISO 129-1, figure 63: outside the arc in the upper
half, towards the centre in the lower half.

Rafael's eighth review (min 50): the 81,76 of his part read below its
line; ezdxf set every angular text outside the arc.
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
    doc = window.document.doc
    style = doc.dimstyles.get(doc.header.get("$DIMSTYLE"))
    for key, value in dict(dimasz=0.5, dimtxt=0.5, dimscale=1.0, dimgap=0.2,
                           dimtad=1).items():
        style.dxf.set(key, value)
    yield window
    window.document.dirty = False
    window.close()


def _at(deg: float, r: float = 10.0):
    return (r * math.cos(math.radians(deg)), r * math.sin(math.radians(deg)))


# the figure's sectors (degrees, counter-clockwise), one at a time
@pytest.mark.parametrize("a, b", [(90, 135), (135, 195), (195, 240),
                                  (240, 300), (300, 360), (0, 30)])
def test_text_reads_upright_above_its_arc(win, a, b):
    p1, p2 = _at(a), _at(b)
    mid = (a + b) / 2.0
    for text in ("DIMANGULAR", "", "0,0", f"{p1[0]},{p1[1]}",
                 f"{p2[0]},{p2[1]}"):
        win._on_command_submitted(text)
    loc = _at(mid, 12.0)
    win._on_command_submitted(f"{loc[0]},{loc[1]}")
    dim = win.document.modelspace().query("DIMENSION")[-1]
    mtext = [e for e in win.document.doc.blocks.get(dim.dxf.geometry)
             if e.dxftype() == "MTEXT"][0]
    rotation = mtext.get_rotation()
    reads = math.cos(math.radians(rotation)) > 1e-9 or \
        math.isclose(rotation % 360.0, 90.0, abs_tol=1e-6)
    assert reads, f"upside-down text at {rotation}"
    up = (-math.sin(math.radians(rotation)), math.cos(math.radians(rotation)))
    p = mtext.dxf.insert
    arc = _at(math.degrees(math.atan2(p.y, p.x)), 12.0)
    assert (p.x - arc[0]) * up[0] + (p.y - arc[1]) * up[1] > 0.0, \
        "the text reads below its arc"
