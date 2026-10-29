# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Where a linear dimension's text sits: Outside, and slid past the lines.

Rafael's eighth review (min 14:40-16:20): the text has to stay off the
part's lines. Taking the dimension to the other side of the part should
put its text below the line, "como si hiciese una simetría", in the same
reading orientation -- AutoCAD's Vertical position "Outside" (DIMTAD 2),
which ezdxf drew as "Above". Sliding the text along the line past an
extension line, the dimension line has to grow under it.
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


def _style(win, **values):
    doc = win.document.doc
    style = doc.dimstyles.get(doc.header.get("$DIMSTYLE"))
    for key, value in dict(dimasz=1.0, dimtxt=1.0, dimscale=1.0, dimgap=0.3,
                           dimtmove=0, **values).items():
        style.dxf.set(key, value)


def _dim(win, *points):
    win._on_command_submitted("DIMLINEAR")
    for p in points:
        win._on_command_submitted(p)
    return win.document.modelspace().query("DIMENSION")[-1]


def _block(win, dim):
    return win.document.doc.blocks.get(dim.dxf.geometry)


def _text_y(win, dim) -> float:
    return [e for e in _block(win, dim) if e.dxftype() == "MTEXT"][0].dxf.insert.y


@pytest.mark.parametrize("line_y, side", [(5.0, +1), (-5.0, -1)])
def test_outside_puts_the_text_away_from_the_part(win, line_y, side):
    _style(win, dimtad=2)
    dim = _dim(win, "0,0", "10,0", f"5,{line_y}")
    assert (_text_y(win, dim) - line_y) * side > 0.5


def test_the_line_taken_across_the_part_takes_the_text_across(win):
    from core import actions

    _style(win, dimtad=2)
    dim = _dim(win, "0,0", "10,0", "5,5")
    assert _text_y(win, dim) > 5.5
    win.history.execute(actions.DimGripCommand(dim, "defpoint", (5.0, -5.0)))
    assert _text_y(win, dim) < -5.5
    win.history.undo()
    assert _text_y(win, dim) > 5.5


def test_above_keeps_the_text_above(win):
    _style(win, dimtad=1)
    dim = _dim(win, "0,0", "10,0", "5,-5")
    assert _text_y(win, dim) > -4.5


def test_text_slid_past_an_extension_line_gets_its_line(win):
    from ezdxf import bbox

    from core import actions

    _style(win, dimtad=1)
    dim = _dim(win, "0,0", "10,0", "5,5")
    mid = dim.dxf.text_midpoint              # slide along the line only
    win.history.execute(actions.DimTextWithLineCommand(dim, (16.0, mid.y)))
    block = _block(win, dim)
    text = bbox.extents([e for e in block if e.dxftype() == "MTEXT"])
    assert text.extmin.x > 10.0, "the text did not leave the extension lines"
    reach = max(max(e.dxf.start.x, e.dxf.end.x) for e in block
                if e.dxftype() == "LINE" and abs(e.dxf.start.y - 5.0) < 1e-9
                and abs(e.dxf.end.y - 5.0) < 1e-9)
    assert reach == pytest.approx(text.extmax.x)


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


def test_properties_sets_one_dimensions_vertical_position(win):
    _style(win, dimtad=1)
    dim = _dim(win, "0,0", "10,0", "5,-5")
    other = _dim(win, "0,20", "10,20", "5,15")
    win.tools.selection = {dim.dxf.handle}
    panel = win._properties_panel
    panel.refresh()
    combo = _row_combo(panel, "Text pos vert")
    assert combo.currentData() == 1
    combo.activated.emit(combo.findData(2))
    assert dim.override().get("dimtad") == 2
    assert dim.get_xdata_list("ACAD", "DSTYLE")             # AutoCAD reads it
    assert _text_y(win, dim) < -5.5                       # away from the part
    assert _text_y(win, other) > 15.5                      # untouched
    win._cmd_undo()
    assert _text_y(win, dim) > -4.5
