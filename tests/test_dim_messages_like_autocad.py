# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""What the command line says around a linear dimension, as AutoCAD 2026
said it side by side (group G): typed points give "Non-associative
dimension created." and "Dimension text = 100"; DIMCONTINUE asks
"Specify second extension line origin or [Select/Undo] <Select>:"."""
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


def _lines(win):
    return win.command_line.history.toPlainText().splitlines()


def test_dimlinear_reports_its_text(win):
    for answer in ("DIMLINEAR", "0,0", "100,0", "50,-20"):
        win._on_command_submitted(answer)
    lines = _lines(win)
    assert lines[-2:] == ["Non-associative dimension created.",
                          "Dimension text = 100"]


def test_dimcontinue_prompt(win):
    for answer in ("DIMLINEAR", "0,0", "100,0", "50,-20", "DIMCONTINUE"):
        win._on_command_submitted(answer)
    assert win.tools.current_prompt == (
        "Specify second extension line origin or [Select/Undo] <Select>:")
    win.tools.cancel()
