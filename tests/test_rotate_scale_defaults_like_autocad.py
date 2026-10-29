# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""ROTATE and SCALE answer as AutoCAD 2026 did (group E of the session).

ROTATE offers the last angle as its default (``<30>``) and Enter takes
it; Reference asks "the reference angle <0>" and "the new angle or
[Points] <0>" and leaves new - reference as the next default. SCALE
Reference asks "reference length <1.0000>" and "new length or [Points]
<1.0000>". IngeCAD had no defaults, Enter ended ROTATE without turning,
and there was no Points.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def win(qapp):
    from tools.edit import RotateTool
    from views.main_window import MainWindow

    RotateTool.angle = 0.0                    # a fresh session
    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    window.new_document()
    window.tools.osnap_on = False
    yield window
    RotateTool.angle = 0.0
    window.document.dirty = False
    window.close()


def _type(win, *answers):
    for answer in answers:
        win._on_command_submitted(answer)


def _end(win):
    (line,) = win.document.modelspace().query("LINE")
    return (line.dxf.end.x, line.dxf.end.y)


def _a(win, value):
    """A default as the drawing writes it (AUPREC: the template's 2)."""
    return win.tools.units().angle(value)


def _l(win, value):
    return win.tools.units().length(value)


def _last_prompt(win):
    return win.command_line.history.toPlainText().splitlines()[-1]


def test_rotate_remembers_its_angle_and_enter_takes_it(win):
    _type(win, "LINE", "0,0", "100,0", "")
    _type(win, "ROTATE", "ALL", "", "0,0")
    assert _last_prompt(win).endswith(f"[Copy/Reference] <{_a(win, 0)}>:")
    _type(win, "30")
    assert _end(win) == pytest.approx((86.6025404, 50))
    _type(win, "ROTATE", "ALL", "", "0,0")
    assert _last_prompt(win).endswith(f"[Copy/Reference] <{_a(win, 30)}>:")
    _type(win, "")                            # Enter: the 30 offered
    assert _end(win) == pytest.approx((50, 86.6025404))


def test_rotate_reference_with_defaults_and_points(win):
    _type(win, "LINE", "0,0", "100,0", "")
    _type(win, "ROTATE", "ALL", "", "0,0", "R")
    assert _last_prompt(win).endswith(f"Specify the reference angle <{_a(win, 0)}>:")
    _type(win, "30")
    assert _last_prompt(win).endswith(f"Specify the new angle or [Points] <{_a(win, 0)}>:")
    _type(win, "90")                          # turns by 60, as AutoCAD
    assert _end(win) == pytest.approx((50, 86.6025404))
    _type(win, "ROTATE", "ALL", "", "0,0")
    assert _last_prompt(win).endswith(f"<{_a(win, 60)}>:")
    _type(win, "R", "", "P", "0,0", "0,10")   # reference 0, new by two points
    assert _end(win) == pytest.approx((-86.6025404, 50))


def test_scale_reference_with_defaults_and_points(win):
    _type(win, "LINE", "0,0", "100,0", "")
    _type(win, "SCALE", "ALL", "", "0,0", "R")
    assert _last_prompt(win).endswith(f"Specify reference length <{_l(win, 1)}>:")
    _type(win, "100")
    assert _last_prompt(win).endswith(f"Specify new length or [Points] <{_l(win, 1)}>:")
    _type(win, "50")
    assert _end(win) == pytest.approx((50, 0))
    _type(win, "SCALE", "ALL", "", "0,0", "R", "", "P", "0,0", "3,4")
    assert _end(win) == pytest.approx((250, 0))   # new 5 / reference 1
