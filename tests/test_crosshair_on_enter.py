# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The crosshair shows as soon as the pointer is over the canvas.

The canvas hides the system arrow and paints its own crosshair, which
waited for the first mouse MOVE. A pointer already over the drawing when
the window -- or the start-up dialog over it -- went away had no cursor
at all until it moved (Marco: "cuando abres IngeCAD por primera vez el
cursor se pierde o hay un lag").
"""
from __future__ import annotations


def test_entering_without_moving_shows_the_crosshair(qapp):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent

    from views.main_window import MainWindow

    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    win.new_document()
    qapp.processEvents()
    viewport = win.viewport
    viewport._cursor = None                      # nothing has moved yet
    local = QPointF(200, 150)
    event = QEnterEvent(local, viewport.mapToGlobal(local),
                        viewport.mapToGlobal(local))
    qapp.sendEvent(viewport, event)
    assert viewport._cursor is not None
    assert (viewport._cursor.x(), viewport._cursor.y()) == (200, 150)
    win.document.dirty = False
    win.close()
