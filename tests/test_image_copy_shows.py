# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A copied raster image shows at once, not after a REGEN.

Found reading a plugin that patched it: COPY of an attached image left the
destination empty (only its grips showed) until REGEN. The copy went to
the vector overlay, which never draws rasters on purpose (rendering an
IMAGE decodes its file), and below the merge threshold nothing rebuilt
the scene. A new image has no quad to move: only a regen puts it there.
"""
from __future__ import annotations

from core import actions
from tests.test_image_surgical import _wait_regen, _win_with_image


def test_a_copied_image_gets_its_own_quad(qapp, tmp_path):
    win = _win_with_image(qapp, tmp_path)
    try:
        img = next(e for e in win.document.modelspace()
                   if e.dxftype() == "IMAGE")
        win.tools._execute(actions.copy_entities([img], 20.0, 0.0))
        _wait_regen(qapp, win)
        for _ in range(5):
            qapp.processEvents()
        copy = next(e for e in win.document.modelspace()
                    if e.dxftype() == "IMAGE" and e is not img)
        handles = {i.handle for i in win.viewport._scene.images}
        assert copy.dxf.handle in handles, "the copy has no pixels on screen"
        assert copy not in win.tools._pending_render, \
            "an IMAGE in the vector overlay decodes its file on every refresh"
    finally:
        win.document.dirty = False
        win.close()
