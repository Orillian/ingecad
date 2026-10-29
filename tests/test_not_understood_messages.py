# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Typed text a prompt cannot use is answered as the classic CAD does.

Recorded in the side-by-side session (groups B, D and F): LINE ``FOO``
answers "Point or option keyword required."; a word at TRIM's object
prompt answers "*Invalid selection*" and lists what it expects; a word at
DIMRADIUS's "Select arc or circle:" expects a single object. IngeCAD
answered "Invalid input." to all three.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.new_document()
    yield window
    window.document.dirty = False
    window.close()


def _type(win, *answers):
    for answer in answers:
        win._on_command_submitted(answer)


def _history(win):
    return win.command_line.history.toPlainText().splitlines()


def test_a_word_at_a_point_prompt_asks_for_a_point_or_keyword(win):
    _type(win, "LINE", "FOO")
    assert _history(win)[-1] == "Point or option keyword required."
    assert win.tools.active()


def test_a_word_at_trims_object_prompt_is_an_invalid_selection(win):
    _type(win, "LINE", "0,0", "100,0", "")
    _type(win, "TRIM")
    if win.tools._selecting_for is not None:      # cutting edges first
        _type(win, "")
    _type(win, "FOO")
    history = _history(win)
    assert "*Invalid selection*" in history
    expects = [line for line in history if line.startswith("Expects a point or")]
    assert expects and "Fence/Crossing/mOde/Undo" in expects[-1]


def test_a_word_at_dimradius_expects_a_single_object(win):
    _type(win, "CIRCLE", "0,0", "50")
    _type(win, "DIMRADIUS", "FOO")
    history = _history(win)
    assert history[-2:] == ["*Invalid selection*", "Expects a single object."]
