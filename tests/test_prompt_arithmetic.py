# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Arithmetic in any number or coordinate typed at a prompt.

Rafael's eighth review (second e-mail): "43.3/3", "123+45,40/2". BricsCAD
reads them directly (AutoCAD asks for 'CAL); options, plain numbers,
negative coordinates and literal text keep their meaning.
"""
from __future__ import annotations

import math

import pytest

from core.calc import expand_input


@pytest.mark.parametrize("typed, read", [
    ("43.3/3", "14.4333333333333"),
    ("123+45,40/2", "168,20"),
    ("@20*2<45", "@40<45"),
    ("#5*2,3", "#10,3"),
    ("2^3", "8"),
    ("10,20,30/3", "10,20,10"),
    # what already means something stays as it is
    ("C", "C"), ("U", "U"), ("Undo", "Undo"), ("-5", "-5"),
    ("-5,-3", "-5,-3"), ("1e-3", "1e-3"), ("@10,5", "@10,5"),
    ("10<45", "10<45"), ("pi", "pi"), ("A-1", "A-1"), ("3*", "3*"),
    ("1/0", "1/0"), ("(1+2", "(1+2"),
])
def test_expand_input(typed, read):
    assert expand_input(typed) == read


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.new_document()
    qapp.processEvents()
    yield window
    window.document.dirty = False
    window.close()


def _type(win, *texts):
    for text in texts:
        win._on_command_submitted(text)


def test_points_and_values_take_arithmetic(win):
    _type(win, "LINE", "0,0", "123+45,40/2", "@20*2<45", "")
    a, b = win.document.modelspace().query("LINE")
    assert (b.dxf.start.x, b.dxf.start.y) == pytest.approx((168.0, 20.0))
    assert (b.dxf.end.x - 168.0, b.dxf.end.y - 20.0) == pytest.approx(
        (40 * math.cos(math.radians(45)), 40 * math.sin(math.radians(45))))
    _type(win, "CIRCLE", "0,0", "43.3/3")
    circle = win.document.modelspace().query("CIRCLE")[0]
    assert circle.dxf.radius == pytest.approx(43.3 / 3)


def test_an_option_stays_an_option(win):
    _type(win, "LINE", "0,0", "10,0", "20,0", "U", "")
    lines = win.document.modelspace().query("LINE")
    assert len(lines) == 1


def test_literal_text_is_not_worked_out(win):
    _type(win, "DIMLINEAR", "0,0", "10,0", "T", "1+1", "5,5")
    dim = win.document.modelspace().query("DIMENSION")[0]
    assert dim.dxf.text == "1+1"
