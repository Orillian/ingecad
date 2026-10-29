# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Right click > Symbol in a text field, AutoCAD's MTEXT Symbol menu.

Rafael's eighth review (min 24-27): a dimension's text needs the drafting
symbols (diameter, degree, plus/minus, square, almost equal, not equal,
less/greater than or equal). The menu is in the in-place text editor and
in Properties' text fields, a dimension's Text override among them.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt


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


def _pick(widget, label: str) -> None:
    """Right click on ``widget`` and choose Symbol > ``label``."""
    from core.i18n import tr
    from views import symbol_menu

    assert widget.contextMenuPolicy() == Qt.CustomContextMenu
    menu = symbol_menu.context_menu(widget)
    actions = menu.actions()            # held while the menu is in use
    sub = None
    for a in actions:
        if a.text() == tr("Symbol"):
            sub = a.menu()              # once per action (PySide)
    assert sub is not None, "no Symbol submenu"
    items = sub.actions()
    action = [a for a in items if a.text().split("\t")[0] == tr(label)][0]
    action.trigger()
    menu.deleteLater()


def _row_edit(panel, label):
    from core.i18n import tr

    tree = panel.tree
    for i in range(tree.topLevelItemCount()):
        section = tree.topLevelItem(i)
        for j in range(section.childCount()):
            item = section.child(j)
            if item.text(0) == tr(label):
                return tree.itemWidget(item, 1)
    raise AssertionError(f"no {label} row")


def test_dimension_text_override_takes_a_diameter(win):
    for text in ("DIMLINEAR", "0,0", "20,0", "10,5"):
        win._on_command_submitted(text)
    dim = win.document.modelspace().query("DIMENSION")[0]
    win.tools.selection = {dim.dxf.handle}
    panel = win._properties_panel
    panel.refresh()
    edit = _row_edit(panel, "Text override")
    edit.clear()
    _pick(edit, "Diameter")
    edit.insert("<>")
    edit.editingFinished.emit()
    assert dim.dxf.text == "%%c<>"
    texts = [e.plain_text() for e in win.document.doc.blocks.get(
        dim.dxf.geometry) if e.dxftype() == "MTEXT"]
    assert texts and texts[0].startswith("Ø")


def test_in_place_editor_takes_symbols(win, qapp):
    win.dispatcher.submit("MTEXT")
    win.tools.tool.on_point((10.0, 40.0))
    win.tools.tool.on_point((90.0, 10.0))
    qapp.processEvents()
    editor = win.tools._mtext_editor
    try:
        _pick(editor.edit, "Square")
        _pick(editor.edit, "Plus/Minus")
        assert editor.edit.toPlainText() == "□%%p"
    finally:
        editor.cancel(ask=False)
