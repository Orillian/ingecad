# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Draw > Arc lists the eleven ways, and each one asks for what it says.

AutoCAD's menu and the ribbon's Arc drop-down run ARC with the options
already answered (``^C^C_arc \\_e \\_r``): pick Start, End, Radius and the
user only gives the two points and the radius. IngeCAD had one Arc item, so
every other way meant knowing to type C, E, A... at the right prompt.
"""
from __future__ import annotations

import math

import pytest


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.new_document()
    window.tools.osnap_on = False
    yield window
    window.document.dirty = False
    window.close()


def _submenu(actions, names):
    # PySide: keep the action list alive while its menus are used, and ask
    # each action for .menu() once
    for a in actions:
        if a.text().replace("&", "") in names:
            menu = a.menu()
            if menu is not None:
                return menu
    raise LookupError(names)


_KEEP = []


def _arc_menu(win):
    bar = win._menu_bar.actions()
    draw = _submenu(bar, ("Draw", "Dibujo"))
    inner = draw.actions()
    _KEEP[:] = [bar, inner]
    return _submenu(inner, ("Arc", "Arco"))


def _pick(win, label):
    menu = _arc_menu(win)
    items = [a for a in menu.actions() if not a.isSeparator()]
    act = next(a for a in items if a.text() == label)
    act.trigger()
    return items


def _arcs(win):
    return [e for e in win.document.modelspace() if e.dxftype() == "ARC"]


def test_the_menu_lists_the_eleven_ways(win):
    labels = [a.text() for a in _arc_menu(win).actions() if not a.isSeparator()]
    assert labels == ["3 Points",
                      "Start, Center, End", "Start, Center, Angle",
                      "Start, Center, Length",
                      "Start, End, Angle", "Start, End, Direction",
                      "Start, End, Radius",
                      "Center, Start, End", "Center, Start, Angle",
                      "Center, Start, Length", "Continue"]


def test_start_end_radius_asks_only_for_points_and_radius(win):
    t = win.tools
    _pick(win, "Start, End, Radius")
    t.on_click(10, 0)
    t.on_click(0, 10)
    win._on_command_submitted("10")
    arcs = _arcs(win)
    assert len(arcs) == 1
    a = arcs[0]
    assert a.dxf.radius == pytest.approx(10)
    assert (a.dxf.center.x, a.dxf.center.y) == pytest.approx((0, 0), abs=1e-9)
    history = win.command_line.history.toPlainText()
    assert "_E" in history and "_R" in history


def test_center_start_angle(win):
    t = win.tools
    _pick(win, "Center, Start, Angle")
    t.on_click(0, 0)                 # centre
    t.on_click(5, 0)                 # start
    win._on_command_submitted("90")
    arcs = _arcs(win)
    assert len(arcs) == 1
    a = arcs[0]
    assert a.dxf.radius == pytest.approx(5)
    assert a.dxf.start_angle % 360 == pytest.approx(0, abs=1e-9)
    assert a.dxf.end_angle % 360 == pytest.approx(90)


def test_the_toolbar_button_draws_the_last_way_picked(win):
    from PySide6.QtWidgets import QToolButton

    button = win._draw_toolbar.widgetForAction(win._arc_action)
    assert isinstance(button, QToolButton) and button.menu() is not None
    t = win.tools
    _pick(win, "Center, Start, End")
    t.on_click(0, 0)
    t.on_click(3, 0)
    t.on_click(0, 3)
    assert len(_arcs(win)) == 1
    win._arc_action.trigger()        # the button again: centre first
    t.on_click(20, 0)
    t.on_click(24, 0)
    t.on_click(20, 4)
    arcs = _arcs(win)
    assert len(arcs) == 2
    assert arcs[1].dxf.radius == pytest.approx(4)
    assert math.isclose(arcs[1].dxf.center.x, 20)
