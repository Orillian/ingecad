# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The first annotation scale change of a new drawing reaches its objects.

Rafael's eighth review (9:14-11:52): annotative dimensions drawn in a new
drawing did not follow 1:1 -> 2:1 with ANNOAUTOSCALE on; after choosing
1:1 and toggling the button they did. The button was a red herring: a new
drawing has no CANNOSCALE stored, the scale being left was None, and
nothing was added -- until picking 1:1 stored it.
"""
from __future__ import annotations

import pytest

from core import annotative


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.show()
    window.new_document()
    qapp.processEvents()
    old = window.annoautoscale()
    yield window
    window._set_annoautoscale(old)
    window.document.dirty = False
    window.close()


def _dim(win):
    from core.styles import SetDimStylePropsCommand

    name = win.document.doc.header.get("$DIMSTYLE")
    win.history.execute(SetDimStylePropsCommand(name, {"annotative": True}))
    for text in ("DIMLINEAR", "0,0", "40,0", "20,-8"):
        win._on_command_submitted(text)
    return win.document.modelspace().query("DIMENSION")[-1]


def test_the_first_change_adds_the_new_scale_with_annoautoscale_on(win):
    win._set_annoautoscale(4)
    dim = _dim(win)
    doc = win.document.doc
    assert annotative.current_scale(doc) is None        # never set: 1:1
    assert win.set_annotation_scale("2:1")
    assert annotative.has_scale(dim, annotative.find_scale(doc, "2:1"))
    win.history.undo()
    assert not annotative.has_scale(dim, annotative.find_scale(doc, "2:1"))
    assert annotative.current_scale(doc) is None


def test_with_annoautoscale_off_the_objects_keep_their_scales(win):
    win._set_annoautoscale(-4)
    dim = _dim(win)
    doc = win.document.doc
    assert win.set_annotation_scale("2:1")
    assert not annotative.has_scale(dim, annotative.find_scale(doc, "2:1"))
