# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A vertical or rotated dimension keeps its rotation through Save as DWG.

Rafael's eighth review: after making the dimension style annotative, every
vertical dimension of his part read "0" (7:33), and dragging the text of
a vertical "1,94" turned it into a horizontal "2,44" (15:57). Both were the
re-render of dimensions that had lost their rotation when the drawing was
saved as DWG: LibreDWG's DXF importer read group 50 -- the rotation, which
precedes the AcDbRotatedDimension marker -- as an aligned dimension's
oblique angle, and left the rotation 0. ODA read those DWGs the same way
(measurement 0, oblique 90), so AutoCAD users saw it too. Fixed in the
vendored LibreDWG (tools/libredwg-patches, in_dxf.c).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from formats.dwg_bridge import find_dxf2dwg


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


def _texts(dim) -> list[str]:
    return [e.plain_text() for e in dim.get_geometry_block()
            if e.dxftype() == "MTEXT"]


@pytest.mark.skipif(find_dxf2dwg() is None, reason="LibreDWG not available")
def test_rotations_survive_save_as_dwg_and_a_redraw(win, tmp_path: Path):
    from core.actions import rerender_dimension
    from formats.dwg_bridge import load_dwg

    _type(win, "DIMLINEAR", "0,0", "40,0", "20,-8")              # horizontal
    _type(win, "DIMLINEAR", "0,0", "2.44,1.94", "-3,1")          # vertical
    _type(win, "DIMLINEAR", "50,0", "50,12.4", "45,6")           # vertical
    _type(win, "DIMLINEAR", "0,30", "20,40", "R", "30", "10,45")  # rotated 30
    _type(win, "DIMALIGNED", "0,60", "30,70", "10,75")           # aligned
    drawn = [(round(d.dxf.get("angle", 0.0), 6), round(d.get_measurement(), 6))
             for d in win.document.modelspace().query("DIMENSION")]
    assert [m for _a, m in drawn][:3] == [40.0, 1.94, 12.4]
    path = tmp_path / "dims.dwg"
    win.document.save_as(path)

    back = load_dwg(path)
    dims = back.doc.modelspace().query("DIMENSION")
    assert [(round(d.dxf.get("angle", 0.0), 6), round(d.get_measurement(), 6))
            for d in dims] == drawn
    for dim in dims:
        assert dim.dxf.get("oblique_angle", 0.0) == pytest.approx(0.0)
    rerender_dimension(back, dims[1])
    rerender_dimension(back, dims[2])
    assert _texts(dims[1]) == ["1,94"]
    assert _texts(dims[2]) == ["12,4"]
