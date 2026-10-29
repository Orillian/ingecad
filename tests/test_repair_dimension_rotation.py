# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""DWGs saved before the LibreDWG fix get their dimensions' rotation back.

Every vertical or rotated dimension IngeCAD saved as DWG lost its rotation
(see test_dwg_dimension_rotation). The drawings people already have still
draw right -- the *D block was written before -- until a dimension is
re-rendered: then a vertical "12,4" reads "0". Rafael's part had six. On
opening, the rotation is taken back from the block's dimension line.
"""
from __future__ import annotations

import pytest

from core import actions
from core.encoding import repair_dimension_rotation


def _texts(dim) -> list[str]:
    return [e.plain_text() for e in dim.get_geometry_block()
            if e.dxftype() == "MTEXT"]


def _damaged(document, *points):
    """Dimensions drawn with their rotation, then stripped of it as the
    DWG round trip did (the block stays as drawn)."""
    for p1, p2, where, angle in points:
        command = actions.dim_linear(p1, p2, where, angle=angle)
        command.do(document)
    dims = list(document.doc.modelspace().query("DIMENSION"))
    for dim in dims:
        dim.dxf.discard("angle")
    return dims


def test_vertical_and_rotated_dimensions_get_their_rotation_back():
    from core.templates import new_document

    document = new_document("mm")
    dims = _damaged(document,
                    ((0, 0), (2.44, 1.94), (-3, 1), 90.0),
                    ((500_000, 8_000_000), (500_000, 8_000_012.4),
                     (499_995, 8_000_006), 90.0),          # UTM
                    ((0, 30), (20, 40), (10, 45), 30.0),
                    ((0, 60), (40, 60), (20, 52), 0.0))
    assert repair_dimension_rotation(document.doc) == 3
    assert [round(d.dxf.get("angle", 0.0), 6) for d in dims] \
        == [90.0, 90.0, 30.0, 0.0]
    assert [round(d.get_measurement(), 6) for d in dims[:2]] == [1.94, 12.4]
    actions.rerender_dimension(document, dims[0])
    assert _texts(dims[0]) == ["1,94"] or _texts(dims[0]) == ["1.94"]


def test_an_aligned_or_sound_dimension_is_left_alone():
    from core.templates import new_document

    document = new_document("mm")
    actions.dim_linear((0, 0), (0, 10), (-5, 5), angle=90.0).do(document)
    actions.dim_aligned((0, 20), (30, 30), (10, 35)).do(document)
    assert repair_dimension_rotation(document.doc) == 0
