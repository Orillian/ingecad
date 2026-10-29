# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A different arrowhead at each end, per dimension, from Properties.

Rafael's eighth review (min 28-29 and 44): the norm draws a dot at one
end and an arrow at the other; AutoCAD's Properties has Arrow 1 and
Arrow 2 for one dimension. The choice is a dimension override (ACAD
DSTYLE XDATA, DIMSAH with DIMBLK1/DIMBLK2), which AutoCAD reads as its own.
"""
from __future__ import annotations

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


def _row_combo(panel, label):
    from core.i18n import tr

    tree = panel.tree
    for i in range(tree.topLevelItemCount()):
        section = tree.topLevelItem(i)
        for j in range(section.childCount()):
            item = section.child(j)
            if item.text(0) == tr(label):
                return tree.itemWidget(item, 1)
    raise AssertionError(f"no {label} row")


def _arrows(win, dim) -> dict:
    """{arrow block name: x of its insert} of the dimension's block."""
    return {e.dxf.name.upper(): round(e.dxf.insert.x, 6)
            for e in win.document.doc.blocks.get(dim.dxf.geometry)
            if e.dxftype() == "INSERT"}


def test_arrow_1_changes_only_its_own_end(win):
    for text in ("DIMLINEAR", "0,0", "20,0", "10,5",
                 "DIMLINEAR", "0,20", "20,20", "10,25"):
        win._on_command_submitted(text)
    dim, other = win.document.modelspace().query("DIMENSION")
    before = _arrows(win, other)
    win.tools.selection = {dim.dxf.handle}
    panel = win._properties_panel
    panel.refresh()
    first = _row_combo(panel, "Arrow 1")
    assert first.currentData() == ""                       # Closed filled
    first.activated.emit(first.findData("DOT"))
    arrows = _arrows(win, dim)
    assert arrows.get("_DOT") == pytest.approx(0.0)          # at the 1st end
    assert any(x == pytest.approx(20.0) for name, x in arrows.items()
               if name != "_DOT")                           # the 2nd keeps its
    assert dim.override().get("dimsah") == 1
    assert dim.get_xdata_list("ACAD", "DSTYLE")
    assert _arrows(win, other) == before
    panel.refresh()
    second = _row_combo(panel, "Arrow 2")
    second.activated.emit(second.findData("OBLIQUE"))
    assert set(_arrows(win, dim)) >= {"_DOT", "_OBLIQUE"}
    win._cmd_undo()
    win._cmd_undo()
    assert "_DOT" not in _arrows(win, dim)
