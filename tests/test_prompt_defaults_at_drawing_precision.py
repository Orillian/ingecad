# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A prompt's default is written at the drawing's precision.

The classic CAD shows CIRCLE's last radius as ``<25.0000>`` and TEXT's
rotation as ``<0>`` from LUPREC/AUPREC; IngeCAD printed Python's ``<25>``
in some sixty prompts, while FILLET and ROTATE already used the drawing.
"""
from __future__ import annotations

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


def _type(win, *answers):
    for answer in answers:
        win._on_command_submitted(answer)


def test_circles_last_radius_and_texts_rotation_follow_the_drawing(win):
    units = win.tools.units()
    _type(win, "CIRCLE", "0,0", "25")
    _type(win, "CIRCLE", "100,0")
    assert win.tools.current_prompt.endswith(f"<{units.length(25)}>:")
    assert units.length(25) != "25"        # the template's LUPREC is not 0
    _type(win, "")                         # Enter: the default radius
    _type(win, "TEXT", "0,50", "5")
    assert win.tools.current_prompt.endswith(f"<{units.angle(0)}>:")
