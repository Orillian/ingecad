# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""TRIM's "every object is an edge" means every object on screen.

Redrawing a tester's part: the construction lines lived on a layer then
frozen, and TRIM with Enter cut the outline against them -- arcs split
at the hidden lines, a base line cut short -- though no pick or window
would take them.
"""
from __future__ import annotations

import pytest


@pytest.mark.parametrize("hide", ["freeze", "off"])
def test_trim_all_leaves_out_a_hidden_layer(qapp, hide):
    from core import actions
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    t = win.tools
    t.osnap_on = False
    for text in ("-LAYER", "M", "Aux", ""):
        win._on_command_submitted(text)
    t._execute(actions.add_line((0, 0), (10, 0)))          # on Aux, then hidden
    win._on_command_submitted("CLAYER")
    win._on_command_submitted("0")
    t._execute(actions.add_line((2, -3), (2, 6)))
    for text in ("-LAYER", "F" if hide == "freeze" else "OFF", "Aux", ""):
        win._on_command_submitted(text)
    assert win.document.doc.layers.get("Aux").is_frozen() == (hide == "freeze")

    win._on_command_submitted("TRIM")
    win._on_command_submitted("")              # every object is an edge
    t.on_hover(2, -2, threshold_world=0.3)
    t.on_click(2, -2)
    t.cancel()
    line = next(e for e in win.document.modelspace()
                if e.dxftype() == "LINE" and e.dxf.layer == "0")
    assert (line.dxf.start.y, line.dxf.end.y) == (-3, 6), \
        "the hidden line on Aux cut the visible one"
    win.document.dirty = False
    win.close()
