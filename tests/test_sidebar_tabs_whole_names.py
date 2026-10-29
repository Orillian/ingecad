# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The sidebar's tabs keep their whole names and scroll when they do not fit.

With the Extensions tab there are five, and at the sidebar's usual width
they no longer fit: they keep their names and the bar shows scroll
arrows, as IngeTrazo's trays do, instead of cutting every name short.
"""
from __future__ import annotations


def test_the_tabs_scroll_with_whole_names(qapp):
    from PySide6.QtCore import Qt

    from views.main_window import MainWindow

    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    qapp.processEvents()
    tabs = win._sidebar_tabs
    assert tabs.count() >= 5
    assert tabs.elideMode() == Qt.ElideNone
    assert tabs.usesScrollButtons()
    bar = tabs.tabBar()
    for i in range(bar.count()):
        need = bar.fontMetrics().horizontalAdvance(bar.tabText(i))
        assert bar.tabRect(i).width() >= need, bar.tabText(i)
    win.close()
