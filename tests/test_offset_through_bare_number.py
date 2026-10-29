# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""OFFSET Through refuses a bare number, as AutoCAD 2026 did (group D):
"Specify through point ... : 50" answers "Point or option keyword
required." and asks again. IngeCAD took 50 as a distance from LASTPOINT
and put the copy somewhere else."""
from __future__ import annotations

import pytest


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    window.new_document()
    window.tools.osnap_on = False
    yield window
    window.document.dirty = False
    window.close()


def _lines(win):
    return list(win.document.modelspace().query("LINE"))


def test_a_bare_number_at_the_through_point_is_refused(win):
    from core.i18n import tr

    for answer in ("LINE", "300,0", "300,100", ""):
        win._on_command_submitted(answer)
    win._on_command_submitted("OFFSET")
    win._on_command_submitted("T")
    win.tools.on_hover(300, 50, threshold_world=0.5)
    win.tools.on_click(300, 50)                # the line to offset
    win._on_command_submitted("50")
    history = win.command_line.history.toPlainText().splitlines()
    assert history[-2:] == [tr("Point or option keyword required."),
                            tr("Specify through point or [Exit/Multiple/Undo] <Exit>:")]
    assert len(_lines(win)) == 1
    win._on_command_submitted("330,50")        # a point still works
    xs = sorted(round(line.dxf.start.x, 6) for line in _lines(win))
    assert xs == [300, 330]
