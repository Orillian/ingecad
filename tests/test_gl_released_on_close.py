# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Closing a window releases its GL objects while the context is alive.

The CI died with SIGSEGV in QOpenGLContext::shareGroup, from the GC
deleting a raster image's QOpenGLTexture long after its window closed.
The context's aboutToBeDestroyed came when the Viewport was already
deleted, so its slot released nothing and the texture outlived the
context it asked about. The window now releases on close.
"""
from __future__ import annotations

from tests.test_image_surgical import _wait_regen, _win_with_image


def test_closing_the_window_destroys_the_image_textures(qapp, tmp_path):
    win = _win_with_image(qapp, tmp_path)
    _wait_regen(qapp, win)
    win.viewport.grabFramebuffer()
    textures = [entry[0] for entry in win.viewport._image_bufs]
    assert textures and all(t.isCreated() for t in textures)
    win.document.dirty = False
    win.close()
    assert not any(t.isCreated() for t in textures), \
        "a texture left for the GC asks a dead context on delete"
