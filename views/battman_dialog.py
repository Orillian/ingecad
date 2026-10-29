# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Block Attribute Manager (BATTMAN, p. 203).

Attributes of the chosen block definition in a list (Tag / Prompt / Default /
Mode), Move Up / Move Down (the prompt order is the block order), Edit (the
Attribute Definition dialog on that definition), Remove and Sync (ATTSYNC on
every reference). Every change is a Command through the window's history.

"Apply changes to existing references" (AutoCAD's BATTMAN setting, on by
default) carries each change to the blocks already inserted, in the same
undo step: Rafael's eighth review (min 32:40) removed an attribute he no
longer wanted and it stayed on every block he had placed.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core import attributes as att
from core.commands import CompositeCommand
from core.i18n import tr


def open_battman(window) -> bool:
    """BATTMAN from the command line / menu. False when the drawing has no
    block with attributes (AutoCAD then shows a message, so do we)."""
    document = window.document
    if document is None:
        return False
    if not att.blocks_with_attributes(document.doc):
        window.command_line.echo(
            tr("This drawing contains no attributed blocks."))
        return False
    BattmanDialog(window).exec()
    return True


class BattmanDialog(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.document = window.document
        self.setWindowTitle(tr("Block Attribute Manager"))
        self.resize(620, 360)
        root = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Block:"), self))
        self.block = QComboBox(self)
        for name in att.blocks_with_attributes(self.document.doc):
            self.block.addItem(name)
        self.block.currentTextChanged.connect(lambda *_: self.refresh())
        row.addWidget(self.block, 1)
        self.sync_button = QPushButton(tr("Sync"), self)
        self.sync_button.clicked.connect(self.sync)
        row.addWidget(self.sync_button)
        root.addLayout(row)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(
            [tr("Tag"), tr("Prompt"), tr("Default"), tr("Mode")])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        root.addWidget(self.table, 1)

        row = QHBoxLayout()
        for label, slot in ((tr("Move Up"), self.move_up),
                            (tr("Move Down"), self.move_down),
                            (tr("Edit..."), self.edit),
                            (tr("Remove"), self.remove)):
            button = QPushButton(label, self)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        root.addLayout(row)

        self.found = QLabel("", self)
        root.addWidget(self.found)
        self.apply_to_references = QCheckBox(
            tr("Apply changes to existing references"), self)
        self.apply_to_references.setChecked(True)
        root.addWidget(self.apply_to_references)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)
        self.refresh()

    # -- state ----------------------------------------------------------------
    def block_name(self) -> str:
        return self.block.currentText()

    def attdefs(self) -> list:
        return att.attdefs_of(self.document.doc, self.block_name())

    def current(self):
        row = self.table.currentRow()
        defs = self.attdefs()
        return defs[row] if 0 <= row < len(defs) else None

    def refresh(self, select_row: int = -1) -> None:
        defs = self.attdefs()
        self.table.setRowCount(len(defs))
        for row, a in enumerate(defs):
            cells = (str(a.dxf.tag), str(a.dxf.get("prompt", "") or ""),
                     att.default_of(a), att.AttMode.of(a).label())
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                self.table.setItem(row, col, item)
        from core.blockedit import references_of

        count = len(references_of(self.document, self.block_name()))
        self.found.setText(tr("Found in drawing: {n}", n=count))
        if defs:
            row = select_row if 0 <= select_row < len(defs) else \
                max(0, min(self.table.currentRow(), len(defs) - 1))
            self.table.setCurrentCell(row, 0)

    def _after(self, command, select_row: int = -1,
               carry: bool = False) -> None:
        if carry and self.apply_to_references.isChecked():
            command = CompositeCommand(command.name, [
                command, att.SyncAttribsCommand(self.document,
                                                self.block_name())])
        self.window.history.execute(command)
        self.window.tools.after_history_change(command)
        self.window.tools.changed.emit()
        self.refresh(select_row)

    # -- actions --------------------------------------------------------------
    def _move(self, delta: int) -> None:
        defs = self.attdefs()
        row = self.table.currentRow()
        target = row + delta
        if not (0 <= row < len(defs)) or not (0 <= target < len(defs)):
            return
        order = list(defs)
        order[row], order[target] = order[target], order[row]
        block = self.document.doc.blocks.get(self.block_name())
        self._after(att.ReorderAttdefsCommand(block, order), target,
                    carry=True)

    def move_up(self) -> None:
        self._move(-1)

    def move_down(self) -> None:
        self._move(1)

    def edit(self) -> None:
        attdef = self.current()
        if attdef is None:
            return
        from views import attdef_dialog

        dialog = attdef_dialog.AttDefDialog(self, self.document, attdef=attdef)
        if not dialog.exec():
            return
        v = dialog.values()
        changes = []
        if v["tag"] != str(attdef.dxf.tag):
            changes.append((attdef, "tag", v["tag"]))
        if v["prompt"] != str(attdef.dxf.get("prompt", "") or ""):
            changes.append((attdef, "prompt", v["prompt"]))
        if v["default"] != att.default_of(attdef):
            changes.append((attdef, "text", v["default"]))
        mode = v["mode"]
        if mode.flags() != int(attdef.dxf.get("flags", 0)):
            changes.append((attdef, "flags", mode.flags()))
        if (1 if mode.lock_position else 0) != int(
                attdef.dxf.get("lock_position", 0)):
            changes.append((attdef, "lock_position",
                            1 if mode.lock_position else 0))
        if abs(v["height"] - float(attdef.dxf.height or 0.0)) > 1e-9:
            changes.append((attdef, "height", v["height"]))
        if abs(v["rotation"] - float(attdef.dxf.get("rotation", 0.0))) > 1e-9:
            changes.append((attdef, "rotation", v["rotation"]))
        if v["style"] and v["style"] != str(attdef.dxf.get("style", "Standard")):
            changes.append((attdef, "style", v["style"]))
        if changes:
            self._after(att.EditAttribsCommand(changes, name="BATTMAN"),
                        self.table.currentRow(), carry=True)

    def remove(self) -> None:
        attdef = self.current()
        if attdef is None:
            return
        if QMessageBox.question(
                self, tr("Block Attribute Manager"),
                tr("Remove attribute \"{tag}\" from block \"{name}\"?",
                   tag=attdef.dxf.tag, name=self.block_name())) \
                != QMessageBox.Yes:
            return
        block = self.document.doc.blocks.get(self.block_name())
        self._after(att.UnlinkEntitiesCommand(block, [attdef]), carry=True)

    def sync(self) -> None:
        command = att.SyncAttribsCommand(self.document, self.block_name())
        self._after(command, self.table.currentRow())
        self.window.command_line.echo(
            tr("ATTSYNC complete: {n} reference(s) of \"{name}\" updated.",
               n=len(command.inserts), name=self.block_name()))
