# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Picking an arrowhead in the dimension style editor changes the arrows.

Rafael's eighth review (28:50): "lo del punto, lo del oblicuo... los puse y
no funcionan". DIMBLK1/DIMBLK2 are read only with DIMSAH on; the editor
always reports DIMSAH 1 and writes only what changed, so on a style with
DIMSAH 0 -- his, and ISO-25's -- DIMSAH was never written and the arrows
stayed closed filled whatever was picked.
"""
from __future__ import annotations


def _arrows(dim) -> list[str]:
    return [e.dxf.name for e in dim.get_geometry_block()
            if e.dxftype() == "INSERT"]


def test_a_dot_picked_in_the_editor_draws_dots(qapp):
    from core import actions
    from core import styles as style_ops
    from core.templates import new_document
    from views.dimstyle_dialog import DimStyleEditorDialog

    document = new_document("mm")
    name = document.doc.header.get("$DIMSTYLE")
    style = document.doc.dimstyles.get(name)
    style.dxf.discard("dimsah")                         # DIMSAH 0
    actions.dim_linear((0, 0), (40, 0), (20, -8)).do(document)
    dim = document.doc.modelspace().query("DIMENSION")[-1]
    assert _arrows(dim) == ["_CLOSEDFILLED", "_CLOSEDFILLED"]

    dlg = DimStyleEditorDialog(
        None, "t", style_ops.dim_style_attribs(document, name),
        style_ops.text_style_names(document))
    dlg.dimblk1.setCurrentIndex(dlg.dimblk1.findData("DOT"))   # Second follows
    dlg.dimblk2.setCurrentIndex(dlg.dimblk2.findData("OBLIQUE"))
    changed = dlg.changed_props()
    dlg.reject()
    style_ops.SetDimStylePropsCommand(name, changed).do(document)
    assert _arrows(dim) == ["_DOT", "_OBLIQUE"]


def test_with_dimsah_off_the_editor_shows_the_arrow_drawn(qapp):
    from views.dimstyle_dialog import DimStyleEditorDialog

    attribs = {"dimsah": 0, "dimblk": "_ARCHTICK", "dimblk1": "", "dimblk2": ""}
    dlg = DimStyleEditorDialog(None, "t", attribs, ["Standard"])
    assert dlg.dimblk1.currentData() == dlg.dimblk2.currentData() == "ARCHTICK"
    assert dlg.changed_props() == {}
    dlg.reject()


def test_an_arrowhead_stored_with_its_underscore_is_shown(qapp):
    """How a DWG brings them back: ``_DOT`` showed as Closed filled."""
    from views.dimstyle_dialog import DimStyleEditorDialog

    attribs = {"dimsah": 1, "dimblk1": "_DOT", "dimblk2": "_OBLIQUE",
               "dimldrblk": "_DOT"}
    dlg = DimStyleEditorDialog(None, "t", attribs, ["Standard"])
    assert (dlg.dimblk1.currentData(), dlg.dimblk2.currentData(),
            dlg.dimldrblk.currentData()) == ("DOT", "OBLIQUE", "DOT")
    dlg.reject()
