# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A right click with a command typed runs that command (#110).

With Right-click = Enter in Options, a user typed the alias DS and right
clicked: IngeCAD repeated the last command (PURGE) instead of running
DIST. Enter itself ran DS -- the right click sent an empty Enter and threw
the typed text away.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest


def test_a_right_click_runs_the_typed_alias(qapp, clean_settings):
    from PySide6.QtCore import QSettings

    from views.main_window import MainWindow
    from views.options_dialog import RIGHT_CLICK_ENTER, SETTING_RIGHT_CLICK

    QSettings().setValue(SETTING_RIGHT_CLICK, RIGHT_CLICK_ENTER)
    win = MainWindow()
    win.show()
    qapp.processEvents()
    win.new_document()
    try:
        win._on_command_submitted("ZOOM")
        win._on_command_submitted("E")           # the last command: ZOOM
        edit = win.command_line.input
        edit.setFocus()
        QTest.keyClicks(edit, "DI")              # DIST's alias
        win.on_canvas_right_click(win.viewport.mapToGlobal(QPoint(200, 200)))
        qapp.processEvents()
        assert win.tools.active(), "the right click did not run DI"
        assert type(win.tools.tool).__name__.lower().startswith("dist")
        assert edit.text() == ""
        win.tools.cancel()
    finally:
        win.document.dirty = False
        win.close()
