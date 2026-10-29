# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Text that does not fit takes the arrowheads outside with it.

Rafael's eighth review (min 17:15): with his part's style (arrowheads and
text 1 unit, DIMATFIT 3) a 2.56 dimension -- room for two arrowheads, not
for "2,56" -- kept its arrows inside and set its text beside, while the
narrower ones turned them out. The norm puts both outside.
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


def _arrows_outside(block, x0: float, x1: float) -> bool:
    """Each arrowhead's body lies beyond its own extension line."""
    out = []
    for e in block:
        if e.dxftype() != "INSERT":
            continue
        body = -math.cos(math.radians(e.dxf.rotation))   # the tail's side
        near_first = abs(e.dxf.insert.x - x0) < abs(e.dxf.insert.x - x1)
        out.append(body < 0 if near_first else body > 0)
    return len(out) == 2 and all(out)


@pytest.mark.parametrize("width, text_out", [(2.56, True), (5.0, False)])
def test_text_outside_takes_the_arrows_out(win, width, text_out):
    doc = win.document
    style = doc.doc.dimstyles.get(doc.doc.header.get("$DIMSTYLE"))
    for key, value in (("dimasz", 1.0), ("dimtxt", 1.0), ("dimscale", 1.0),
                       ("dimatfit", 3), ("dimtmove", 0), ("dimgap", 0.3),
                       ("dimtad", 1)):
        style.dxf.set(key, value)
    for text in ("DIMLINEAR", "0,0", f"{width},0", f"{width / 2},-3"):
        win._on_command_submitted(text)
    dim = doc.modelspace().query("DIMENSION")[0]
    block = doc.doc.blocks.get(dim.dxf.geometry)
    mtext = [e for e in block if e.dxftype() == "MTEXT"][0]
    assert (mtext.dxf.insert.x > width) is text_out
    assert _arrows_outside(block, 0.0, width) is text_out
