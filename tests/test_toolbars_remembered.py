# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A toolbar the user hides stays hidden at the next start (#107).

"I can't permanently disable toolbars. They always return when I restart
the program. I don't use them, I always use the command line." The user
turns a bar off from the right-click list over any bar, as in AutoCAD;
that choice is remembered. Clean Screen (Ctrl+0) is not a choice to keep.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolBar


def _window():
    from views.main_window import MainWindow

    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    return win


def _bar(win, name) -> QToolBar:
    return win.findChild(QToolBar, name)


def _toggle_from_right_click(qapp, win, bar) -> None:
    """Pick the bar in the list a right click over the bars shows."""
    menu = win.createPopupMenu()
    actions = menu.actions()
    (action,) = [a for a in actions if a.text() == bar.windowTitle()]
    action.trigger()
    menu.deleteLater()
    qapp.processEvents()


def test_a_hidden_toolbar_stays_hidden_after_a_restart(qapp):
    win = _window()
    try:
        _toggle_from_right_click(qapp, win, _bar(win, "dimension_toolbar"))
        assert _bar(win, "dimension_toolbar").isHidden()
    finally:
        win.close()

    win = _window()
    try:
        assert _bar(win, "dimension_toolbar").isHidden()
        assert not _bar(win, "draw_toolbar").isHidden()      # only that one
        assert not _bar(win, "modify_toolbar").isHidden()
        # and back on, which is remembered too
        _toggle_from_right_click(qapp, win, _bar(win, "dimension_toolbar"))
        assert not _bar(win, "dimension_toolbar").isHidden()
    finally:
        win.close()

    win = _window()
    try:
        assert not _bar(win, "dimension_toolbar").isHidden()
    finally:
        win.close()


def test_clean_screen_is_not_remembered(qapp):
    win = _window()
    try:
        win.toggle_clean_screen()
        assert _bar(win, "draw_toolbar").isHidden()
    finally:
        win.close()
    win = _window()
    try:
        assert not _bar(win, "draw_toolbar").isHidden()
    finally:
        win.close()


def test_a_plugin_toolbar_hidden_there_is_turned_off_in_its_setting(qapp):
    win = _window()
    pid = "topografia"
    try:
        if not win.plugins.is_active(pid):
            win.plugins.activate(pid)
        win.plugins.set_toolbar_enabled(pid, True)
        qapp.processEvents()                 # on screen, as the user sees it
        bar = win._plugin_toolbars[pid]
        assert bar.toggleViewAction().isChecked()
        _toggle_from_right_click(qapp, win, bar)
        QTest.qWait(20)                      # the deferred turn-off
        assert not win.plugins.toolbar_enabled(pid)          # one place
        assert pid not in win._plugin_toolbars
    finally:
        win.plugins.set_toolbar_enabled(pid, False)
        QSettings().remove(win.plugins.TOOLBAR_SETTING.format(id=pid))
        win.close()
