# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""DIM, QDIM, DIMBREAK, DIMJOGGED and DIMSPACE (issue #39)."""
from __future__ import annotations

import math

import pytest

from core import dim_commands, xdata
from core.commands import History
from core.document import Document
from tools.base import ToolContext
from tools.dim_commands import (DimBreakTool, DimJoggedTool, DimSpaceTool,
                                DimTool, QDimTool)


class Services:
    def __init__(self, document):
        self.document = document
        self.picks = {}

    def pick_entity(self, point):
        for key, entity in self.picks.items():
            if math.dist(key, point) < 1e-6:
                return entity
        return None


class Harness:
    def __init__(self):
        self.document = Document.new()
        self.history = History(self.document)
        self.finished = False
        self.prompts: list[str] = []
        self.echoes: list[str] = []
        self.services = Services(self.document)
        self.ctx = ToolContext(
            execute=self.history.execute,
            prompt=self.prompts.append,
            echo=self.echoes.append,
            finish=lambda: setattr(self, "finished", True),
            undo_last=self.history.undo,
            services=self.services,
        )

    @property
    def msp(self):
        return self.document.modelspace()

    def dims(self):
        return list(self.msp.query("DIMENSION"))


def _block_lines(h, dim):
    return [e for e in h.document.doc.blocks.get(dim.dxf.geometry)
            if e.dxftype() == "LINE" and e.dxf.layer.lower() != "defpoints"]


# -- DIM -----------------------------------------------------------------------

def test_dim_routes_by_what_is_picked_and_keeps_running():
    h = Harness()
    line = h.msp.add_line((0, 0), (100, 0))
    circle = h.msp.add_circle((300, 0), 20)
    arc = h.msp.add_arc((500, 0), 30, 0, 90)
    h.services.picks = {(50, 0): line, (320, 0): circle, (530, 0): arc}
    tool = DimTool(h.ctx)
    tool.start()
    assert "aliGn/Distribute/Layer/Undo" in h.prompts[-1]

    tool.on_point((50, 0))             # a line -> linear
    tool.on_point((50, 20))
    tool.on_point((320, 0))            # a circle -> diameter
    tool.on_point((340, 10))
    tool.on_point((530, 0))            # an arc -> radius
    tool.on_point((540, 30))
    tool.on_point((0, 50))             # two bare points -> linear
    tool.on_point((0, 150))
    tool.on_point((-20, 100))
    assert not h.finished, "DIM ended after one dimension"
    kinds = [d.dxf.dimtype & 15 for d in h.dims()]
    assert kinds == [0, 3, 4, 0]
    assert h.dims()[0].get_measurement() == pytest.approx(100.0)
    assert h.dims()[3].get_measurement() == pytest.approx(100.0)
    tool.on_enter()
    assert h.finished


def test_dim_layer_option_and_undo():
    h = Harness()
    h.document.doc.layers.add("COTAS")
    tool = DimTool(h.ctx)
    tool.start()
    assert tool.on_option("L")
    assert "Use current/eXit" in h.prompts[-1]
    assert tool.on_option("COTAS")
    tool.on_point((0, 0))
    tool.on_point((10, 0))
    tool.on_point((5, 5))
    assert h.dims()[0].dxf.layer == "COTAS"
    tool.on_point((0, 20))
    tool.on_point((10, 20))
    tool.on_point((5, 25))
    assert len(h.dims()) == 2
    assert tool.on_option("U")          # Undo takes the last one back
    assert len(h.dims()) == 1


# -- QDIM ----------------------------------------------------------------------

def _stairs(h):
    return [h.msp.add_line((0, 0), (10, 0)), h.msp.add_line((10, 0), (30, 0)),
            h.msp.add_line((30, 0), (60, 0))]


@pytest.mark.parametrize("mode,measures", [
    ("C", [10, 20, 30]),
    ("B", [10, 30, 60]),
    ("S", [60, 20]),
])
def test_qdim_series_is_one_undo_step(mode, measures):
    h = Harness()
    lines = _stairs(h)
    tool = QDimTool(h.ctx)
    tool.start()
    tool.on_selection(lines)
    assert "datumPoint/Edit/seTtings" in h.prompts[-1]
    assert tool.on_option(mode)
    tool.on_point((30, 15))
    got = sorted(round(d.get_measurement(), 6) for d in h.dims())
    assert got == sorted(measures)
    assert all(abs(d.dxf.get("angle", 0.0)) < 1e-9 for d in h.dims())
    h.history.undo()
    assert h.dims() == []
    QDimTool.mode = "Continuous"


def test_qdim_radius_on_circles():
    h = Harness()
    circles = [h.msp.add_circle((0, 0), 5), h.msp.add_circle((50, 0), 8)]
    tool = QDimTool(h.ctx)
    tool.start()
    tool.on_selection(circles)
    tool.on_option("R")
    tool.on_point((20, 20))
    assert sorted(round(d.get_measurement(), 6) for d in h.dims()) == [5, 8]
    QDimTool.mode = "Continuous"


# -- DIMBREAK ------------------------------------------------------------------

def _crossed(h):
    from core import actions

    h.history.execute(actions.dim_linear((0, 0), (100, 0), (50, 20), angle=0.0))
    dim = h.dims()[0]
    crossing = h.msp.add_line((30, -10), (30, 40))
    return dim, crossing


def test_dimbreak_auto_cuts_and_undo_restores():
    h = Harness()
    dim, crossing = _crossed(h)
    before = len(_block_lines(h, dim))
    h.services.picks = {(50, 20): dim, (30, 30): crossing}
    tool = DimBreakTool(h.ctx)
    tool.start()
    tool.on_point((50, 20))
    assert "[Auto/Manual/Remove] <Auto>" in h.prompts[-1]
    tool.on_enter()                           # <Auto>
    assert h.finished
    after = _block_lines(h, dim)
    assert len(after) == before + 1, "the dimension line was not cut"
    gap_ok = all(not (min(e.dxf.start.x, e.dxf.end.x) < 30 < max(e.dxf.start.x, e.dxf.end.x)
                      and abs(e.dxf.start.y - 20) < 1e-6)
                 for e in after)
    assert gap_ok, "a line still crosses x=30"
    assert dim_commands.has_breaks(dim)
    h.history.undo()
    assert len(_block_lines(h, dim)) == before
    assert not dim_commands.has_breaks(dim)


def test_dimbreak_manual_and_remove():
    h = Harness()
    dim, _crossing = _crossed(h)
    before = len(_block_lines(h, dim))
    h.services.picks = {(50, 20): dim}
    tool = DimBreakTool(h.ctx)
    tool.start()
    tool.on_point((50, 20))
    assert tool.on_option("M")
    tool.on_point((60, 20))
    tool.on_point((70, 20))
    assert len(_block_lines(h, dim)) == before + 1
    tool = DimBreakTool(h.ctx)
    tool.start()
    tool.on_point((50, 20))
    assert tool.on_option("R")
    assert len(_block_lines(h, dim)) == before
    assert not dim_commands.has_breaks(dim)
    h.history.undo()                          # the break comes back
    assert len(_block_lines(h, dim)) == before + 1


# -- DIMJOGGED -----------------------------------------------------------------

def _jog_shape(h, dim):
    """The jogged line's vertices O, B, A, P, chained from the override."""
    lines = _block_lines(h, dim)
    return [(round(e.dxf.start.x, 6), round(e.dxf.start.y, 6))
            for e in lines] + [(round(lines[-1].dxf.end.x, 6),
                                round(lines[-1].dxf.end.y, 6))]


def test_dimjogged_points_at_the_true_centre_with_a_wide_jog():
    """Rafael's eighth review (min 36-43): the arrow's segment points at
    the true centre, the segment from the override runs parallel to it,
    the jog between them is a wide transverse at DIMJOGANG (45), and the
    text sits on the arrow's segment, not at the tip."""
    h = Harness()
    arc = h.msp.add_arc((0, 0), 500, 0, 90)
    h.services.picks = {(500, 0): arc}
    tool = DimJoggedTool(h.ctx)
    tool.start()
    tool.on_point((500, 0))
    assert h.prompts[-1] == "Specify center location override:"
    tool.on_point((300, 100))
    assert "[Mtext/Text/Angle]" in h.prompts[-1]
    tool.on_point((330, 330))
    assert h.prompts[-1] == "Specify jog location:"
    tool.on_point((300, 300))
    dim = h.dims()[0]
    assert dim.get_measurement() == pytest.approx(500.0)
    block = h.document.doc.blocks.get(dim.dxf.geometry)
    assert [e.plain_text() for e in block if e.dxftype() == "MTEXT"] == ["R500"]
    o, b, a, p = _jog_shape(h, dim)
    assert o == (300.0, 100.0)
    assert p == pytest.approx((500 / math.sqrt(2), 500 / math.sqrt(2)))
    # A on the radial line, O -> B parallel to it, B -> A at 45 degrees
    assert a[0] == pytest.approx(a[1])
    assert b[0] - o[0] == pytest.approx(b[1] - o[1])
    seg = math.degrees(math.atan2(a[1] - b[1], a[0] - b[0]))
    assert abs(seg - 45.0) == pytest.approx(45.0)
    assert math.dist(a, b) == pytest.approx(200.0)     # |h| / sin 45
    text = [e for e in block if e.dxftype() == "MTEXT"][0].dxf.insert
    s_text = (text.x + text.y) / math.sqrt(2)
    assert math.hypot(*a) < s_text < 500.0, "the text is not on the arrow's segment"
    h.history.undo()
    assert h.dims() == []


# -- DIMSPACE ------------------------------------------------------------------

def test_dimspace_equal_spacing_auto_and_value():
    from core import actions

    h = Harness()
    for y in (10, 13, 40):
        h.history.execute(actions.dim_linear((0, 0), (100, 0), (50, y), angle=0.0))
    base, a, b = h.dims()
    h.services.picks = {(1, 1): base, (2, 2): a, (3, 3): b}
    tool = DimSpaceTool(h.ctx)
    tool.start()
    tool.on_point((1, 1))
    tool.on_point((2, 2))
    tool.on_point((3, 3))
    tool.on_enter()
    assert "[Auto] <Auto>" in h.prompts[-1]
    assert tool.on_option("7")
    assert a.dxf.defpoint.y == pytest.approx(17.0)
    assert b.dxf.defpoint.y == pytest.approx(24.0)
    h.history.undo()
    assert a.dxf.defpoint.y == pytest.approx(13.0)
    assert b.dxf.defpoint.y == pytest.approx(40.0)
    auto = dim_commands.space_plan(h.document, base, [a, b], None)
    step = 2 * dim_commands.text_height(h.document, base)
    assert auto[0][1][1] == pytest.approx(10 + step)


# -- through the window --------------------------------------------------------

def test_the_commands_and_aliases_reach_the_tools(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    try:
        for typed, name in (("DIM", "DIM"), ("QDIM", "QDIM"),
                            ("DIMBREAK", "DIMBREAK"), ("JOG", "DIMJOGGED"),
                            ("DJO", "DIMJOGGED"), ("DIMSPACE", "DIMSPACE")):
            win._on_command_submitted(typed)
            assert win.tools.tool is not None and win.tools.tool.name == name, typed
            win.tools.cancel()
    finally:
        win.document.dirty = False
        win.close()
