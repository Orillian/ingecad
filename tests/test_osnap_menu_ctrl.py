# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Shift or Ctrl + right-click during a command opens the object snap menu.

Recorded on AutoCAD 2026 (group F): Ctrl + right-click opens it too, and
IngeCAD answered it with Enter (the plain right click), ending the line.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt


@pytest.mark.parametrize("modifier", [Qt.ShiftModifier, Qt.ControlModifier])
def test_modified_right_click_opens_the_snap_menu(qapp, modifier):
    from PySide6.QtTest import QTest

    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    opened = []
    win.show_osnap_menu = lambda pos: opened.append(pos)
    win._on_command_submitted("LINE")
    win._on_command_submitted("0,0")
    vp = win.viewport
    QTest.mouseClick(vp, Qt.RightButton, modifier, QPoint(200, 200))
    qapp.processEvents()
    assert opened, "no object snap menu"
    assert win.tools.active(), "the right click ended LINE"
    win.tools.cancel()
    win.document.dirty = False
    win.close()
