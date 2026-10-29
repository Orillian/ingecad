# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""BLOCK onto a name the drawing has asks "Redefine it?", and the new
reference lands on the current layer.

Found reading a plugin that had to patch it: a square made a block "A"
after a circle had been made block "A" disappeared and came back as a
reference to the CIRCLE, without a word; and every reference BLOCK left
was on layer 0 whatever the current layer was.
"""
from __future__ import annotations

import pytest

from tests.test_blocks import Harness
from tools.blocks import BlockTool


def _circle_block(h):
    tool = BlockTool(h.ctx)
    tool.start()
    tool.on_selection([h.msp.add_circle((0, 0), 1)])
    tool.on_point((0, 0))
    return tool


def _square(h):
    pts = [(10, 10), (12, 10), (12, 12), (10, 12)]
    return [h.msp.add_line(pts[i], pts[(i + 1) % 4]) for i in range(4)]


def test_yes_redefines_and_every_reference_shows_the_new_content():
    h = Harness(text_answer="A")
    _circle_block(h)
    first = h.msp.query("INSERT")[0]
    tool = BlockTool(h.ctx)
    tool.start()
    tool.on_selection(_square(h))
    assert tool._await == "redefine"
    assert tool.on_option("Y")
    tool.on_point((10, 10))
    block = h.document.doc.blocks.get("A")
    assert sorted(e.dxftype() for e in block) == ["LINE"] * 4
    assert tuple(block.block.dxf.base_point)[:2] == pytest.approx((10, 10))
    assert len(h.msp.query("INSERT")) == 2
    assert first.dxf.name == "A"          # the old reference shows it too
    assert len(h.msp.query("LINE")) == 0
    h.history.undo()                      # the circle definition comes back
    block = h.document.doc.blocks.get("A")
    assert [e.dxftype() for e in block] == ["CIRCLE"]
    assert tuple(block.block.dxf.base_point)[:2] == pytest.approx((0, 0))
    assert len(h.msp.query("LINE")) == 4


def test_no_keeps_the_old_block_and_asks_for_a_name_again():
    h = Harness(text_answer="A")
    _circle_block(h)
    tool = BlockTool(h.ctx)
    tool.start()
    square = _square(h)
    tool.on_selection(square)
    tool.on_enter()                       # <No>
    assert tool._await == "redefine"      # same name typed again: asked again
    assert [e.dxftype() for e in h.document.doc.blocks.get("A")] == ["CIRCLE"]
    assert len(h.msp.query("LINE")) == 4  # the square is untouched


def test_the_reference_lands_on_the_current_layer():
    h = Harness(text_answer="B")
    h.document.doc.layers.add("MUROS")
    h.document.doc.header["$CLAYER"] = "MUROS"
    tool = BlockTool(h.ctx)
    tool.start()
    tool.on_selection(_square(h))
    tool.on_point((0, 0))
    assert h.msp.query("INSERT")[0].dxf.layer == "MUROS"
