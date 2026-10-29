# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""BATTMAN's Remove reaches the blocks already inserted.

Rafael's eighth review (min 32:40): "defines, defines, defines y ... uno
que no te vale ... no logré borrarlos". AutoCAD's BATTMAN applies its
changes to existing references by default; ours removed the definition
and left the attribute on every placed block until Sync. And it was only
under Modify > Object > Attribute: it is now beside Define Attributes.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from core import attributes as att


@pytest.fixture
def win(qapp, monkeypatch):
    from views.main_window import MainWindow

    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    window = MainWindow()
    window.show()
    window.new_document()
    doc = window.document.doc
    block = doc.blocks.new("CAJETIN")
    block.add_line((0, 0), (40, 0))
    block.add_attdef("NOMBRE", (0, 5), dxfattribs={"height": 2.5})
    block.add_attdef("MALO", (0, 10), dxfattribs={"height": 2.5})
    for x in (0, 100):
        window.tools._execute(att.insert_block_with_attribs(
            "CAJETIN", (x, 0), values={"NOMBRE": "Rafa", "MALO": "x"}))
    qapp.processEvents()
    yield window
    window.document.dirty = False
    window.close()


def _tags(win):
    return [sorted(a.dxf.tag for a in i.attribs)
            for i in win.document.modelspace().query("INSERT")]


def _remove_malo(win, apply: bool):
    from views.battman_dialog import BattmanDialog

    dialog = BattmanDialog(win)
    try:
        dialog.apply_to_references.setChecked(apply)
        row = [a.dxf.tag for a in dialog.attdefs()].index("MALO")
        dialog.table.setCurrentCell(row, 0)
        dialog.remove()
        return [a.dxf.tag for a in dialog.attdefs()]
    finally:
        dialog.deleteLater()


def test_remove_reaches_the_inserted_blocks(win):
    assert _remove_malo(win, True) == ["NOMBRE"]
    assert _tags(win) == [["NOMBRE"], ["NOMBRE"]]
    assert [i.get_attrib_text("NOMBRE") for i in
            win.document.modelspace().query("INSERT")] == ["Rafa", "Rafa"]
    win._cmd_undo()                                   # one step
    assert _tags(win) == [["MALO", "NOMBRE"], ["MALO", "NOMBRE"]]
    assert [a.dxf.tag for a in att.attdefs_of(win.document.doc,
                                              "CAJETIN")] == ["NOMBRE", "MALO"]


def test_unchecked_leaves_the_references(win):
    assert _remove_malo(win, False) == ["NOMBRE"]
    assert _tags(win) == [["MALO", "NOMBRE"], ["MALO", "NOMBRE"]]


def test_battman_is_beside_define_attributes(win):
    from core.i18n import tr

    bar = win._menu_bar
    menus = bar.actions()
    insert = [a for a in menus if a.text().replace("&", "") == tr("Insert")][0]
    items = insert.menu().actions()
    texts = [a.text() for a in items]
    at = texts.index(tr("Define Attributes..."))
    assert texts[at + 1] == tr("Block Attribute Manager...")
