# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Dragging the text of a dimension that came in the file leaves one.

Rafael's eighth review (min 15:57, "me duplica la cota"): the text grip of
a saved linear dimension moved it -- and its old picture stayed on screen
beside the new one until a full regen, a dozen seconds on his part. A
dimension drawn in the session did not, as it lives in the overlay; one
read from the file is baked in the base scene, and the command that moves
the text with its line did not hide that copy.
"""
from __future__ import annotations

import math
import time

import ezdxf


def _wait(qapp, win, seconds=60):
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        qapp.processEvents()
        if (win._open_thread is None
                and getattr(win, "_regen_worker", None) is None):
            break
    for _ in range(10):
        qapp.processEvents()


def test_the_old_picture_of_a_saved_dimension_goes(qapp, tmp_path):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from views.main_window import MainWindow

    doc = ezdxf.new(setup=True)
    msp = doc.modelspace()
    msp.add_line((0, 0), (0, 20))
    # DIMTMOVE 0, AutoCAD's default and the tester's: the text carries
    # its line, the move that left the old picture behind
    dim = msp.add_linear_dim(base=(-5, 10), p1=(0, 0), p2=(0, 20), angle=90,
                             override={"dimtmove": 0})
    dim.render()
    path = tmp_path / "saved_dim.dxf"
    doc.saveas(path)

    win = MainWindow()
    win.maybe_save_changes = lambda *a, **k: True
    win.resize(1200, 800)
    win.show()
    win.open_path(path)
    _wait(qapp, win)
    win._on_command_submitted("ZOOM")
    win._on_command_submitted("E")
    _wait(qapp, win)
    vp, t = win.viewport, win.tools
    t.osnap_on = False                # the drop would take the line's MID
    entity = next(e for e in win.document.modelspace()
                  if e.dxftype() == "DIMENSION")
    handle = entity.dxf.handle
    assert vp._scene.handle_ranges.get(handle), "baked in the base scene"

    def at(x, y):
        sx, sy = vp.view.world_to_screen(x, y)
        return QPoint(int(round(sx)), int(round(sy)))

    def click(x, y):
        QTest.mouseMove(vp, at(x, y))
        qapp.processEvents()
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, at(x, y))
        qapp.processEvents()

    mid = entity.dxf.text_midpoint
    t.selection = {handle}
    t.changed.emit()
    qapp.processEvents()
    click(mid.x, mid.y)                       # the text grip
    assert t._grip_drag is not None
    step = 3.0
    dx, dy = math.cos(math.radians(90)) * step, math.sin(math.radians(90)) * step
    for k in range(1, 6):
        QTest.mouseMove(vp, at(mid.x + dx * k / 5, mid.y + dy * k / 5))
        qapp.processEvents()
    click(mid.x + dx, mid.y + dy)
    qapp.processEvents()

    moved = win.document.doc.entitydb.get(handle).dxf.text_midpoint.y
    assert abs(moved - (mid.y + dy)) < 0.1, "the text did not move"
    batches = vp._scene
    alpha = [getattr(batches, name).data["rgba"][first:first + count, 3]
             for name, first, count in batches.handle_ranges[handle]]
    assert all((a == 0).all() for a in alpha), \
        "the old picture of the dimension is still on screen"
    win._on_command_submitted("U")
    qapp.processEvents()
    back = win.document.doc.entitydb.get(handle).dxf.text_midpoint.y
    assert abs(back - mid.y) < 1e-9, "U did not bring the text back"
    win.document.dirty = False
    win.close()
