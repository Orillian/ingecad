# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A radius with its text inside the circle starts at the centre.

Rafael's eighth review (min 18-20): "la línea de cota por norma tiene que
llegar siempre al punto central" -- ISO 129. ezdxf drew the line from the
text to the arc, like a leader. DIMTOFL off keeps that.
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


def _lines_from_centre(win, dimtofl: int) -> list:
    doc = win.document.doc
    style = doc.dimstyles.get(doc.header.get("$DIMSTYLE"))
    for key, value in dict(dimasz=1.0, dimtxt=1.0, dimscale=1.0, dimgap=0.3,
                           dimtad=1, dimtofl=dimtofl, dimcen=0).items():
        style.dxf.set(key, value)
    for text in ("CIRCLE", "0,0", "10", "DIMRADIUS", "10,0", "5,3"):
        win._on_command_submitted(text)
    dim = win.document.modelspace().query("DIMENSION")[0]
    p = dim.dxf.defpoint4
    radial = math.atan2(p.y, p.x)
    return [e for e in doc.blocks.get(dim.dxf.geometry)
            if e.dxftype() == "LINE" and math.hypot(e.dxf.start.x,
                                                    e.dxf.start.y) < 1e-9
            and math.atan2(e.dxf.end.y, e.dxf.end.x) == pytest.approx(radial)]


def test_iso_radius_inside_starts_at_the_centre(win):
    assert len(_lines_from_centre(win, 1)) == 1


def test_dimtofl_off_keeps_the_line_from_the_text(win):
    assert _lines_from_centre(win, 0) == []
