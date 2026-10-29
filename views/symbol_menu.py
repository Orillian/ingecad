# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Symbol menu of a text field: AutoCAD's MTEXT Symbol menu.

Rafael's eighth review (min 24-27): a dimension's text needs the drafting
symbols -- diameter, degree, plus/minus, square, almost equal, not equal,
less or greater than or equal. One list, one menu, used by the in-place
text editor and by the text fields of Properties.

The three AutoCAD control codes (%%c, %%d, %%p) are inserted as codes, as
AutoCAD's own menu does: every font draws them, SHX ones included. The
rest go in as the character itself -- IngeCAD keeps text as Unicode and
writes AutoCAD's ``\\U+`` escapes when it saves (core.encoding).
"""
from __future__ import annotations

from PySide6.QtWidgets import QMenu, QTextEdit

from core.i18n import tr

#: (label, what is inserted, how the menu shows it)
SYMBOLS: list[tuple[str, str, str]] = [
    ("Degree", "%%d", "%%d"),
    ("Plus/Minus", "%%p", "%%p"),
    ("Diameter", "%%c", "%%c"),
    ("Square", "□", "□"),
    ("Almost equal", "≈", "≈"),
    ("Not equal", "≠", "≠"),
    ("Less than or equal", "≤", "≤"),
    ("Greater than or equal", "≥", "≥"),
    ("Angle", "∠", "∠"),
    ("Delta", "Δ", "Δ"),
    ("Squared", "²", "²"),
    ("Cubed", "³", "³"),
]


def add_symbol_menu(menu: QMenu, insert) -> QMenu:
    """Append the Symbol submenu to ``menu``; ``insert(text)`` puts the
    chosen symbol at the caret."""
    sub = menu.addMenu(tr("Symbol"))
    for label, text, shown in SYMBOLS:
        action = sub.addAction(f"{tr(label)}\t{shown}")
        action.triggered.connect(lambda _=False, t=text: insert(t))
    return sub


def context_menu(widget) -> QMenu:
    """The widget's own context menu with the Symbol submenu at its end."""
    menu = widget.createStandardContextMenu()
    menu.addSeparator()
    if isinstance(widget, QTextEdit):
        add_symbol_menu(menu, widget.insertPlainText)
    else:
        add_symbol_menu(menu, widget.insert)
    return menu


def install(widget) -> None:
    """Give a QLineEdit or QTextEdit the Symbol submenu on right click."""
    from PySide6.QtCore import Qt

    target = widget
    widget.setContextMenuPolicy(Qt.CustomContextMenu)

    def show(pos) -> None:
        # a QTextEdit reports the click in its viewport's coordinates
        origin = target.viewport() if isinstance(target, QTextEdit) else target
        menu = context_menu(target)
        menu.exec(origin.mapToGlobal(pos))
        menu.deleteLater()

    widget.customContextMenuRequested.connect(show)
