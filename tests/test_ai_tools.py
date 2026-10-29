# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The AI's one catalogue of tools (core.ai.tools), on a real window.

What an AI turn changes goes through the same Commands as the keyboard
and comes back with ONE U; a change planned on an older revision is
refused; erasing many objects or writing over a file waits for the
user's yes; a locked layer stays locked.
"""
from __future__ import annotations

import pytest

from core.ai import tools as ai


@pytest.fixture
def win(qapp):
    from views.main_window import MainWindow

    window = MainWindow()
    window.resize(900, 600)
    window.show()
    window.new_document()
    echoed = []
    original = window.command_line.echo

    def echo(text):
        echoed.append(text)
        original(text)
    window.command_line.echo = echo
    window.echoed = echoed
    yield window
    window.document.dirty = False
    window.close()


def _msp(win):
    return list(win.document.current_space())


def test_the_catalogue_is_well_formed():
    listed = ai.tool_list()
    names = [t["name"] for t in listed]
    assert len(names) == len(set(names))
    for tool in listed:
        schema = tool["parameters"]
        assert schema["type"] == "object" and tool["description"]
        assert set(schema["required"]) <= set(schema["properties"])
    for name in ("draw_line", "query_entities", "erase_entities", "undo",
                 "capture_view", "save_drawing"):
        assert name in names
    # every change can be pinned to the revision it was planned on
    for tool in ai.TOOLS.values():
        assert ("expected_revision" in tool.parameters["properties"]) \
            == tool.mutates


def test_a_turn_is_one_undo_step(win):
    depth = len(win.history._undo)
    with ai.Turn(win):
        r = ai.call(win, "draw_line", {"points": [[0, 0], [10, 0], [10, 5]]})
        assert len(r["created"]) == 2
        ai.call(win, "draw_circle", {"center": [5, 5], "radius": 2})
        ai.call(win, "create_layer", {"name": "EJES", "color": 1})
        r = ai.call(win, "set_entity_properties",
                    {"handles": r["created"], "layer": "EJES"})
        assert "error" not in r
    assert len(win.history._undo) == depth + 1
    assert len(_msp(win)) == 3
    assert {e.dxf.layer for e in _msp(win) if e.dxftype() == "LINE"} == {"EJES"}
    assert "AI: draw_line" in win.echoed           # seen in the history
    win._on_command_submitted("U")
    assert _msp(win) == []
    assert "EJES" not in win.document.doc.layers
    win._on_command_submitted("REDO")
    assert len(_msp(win)) == 3


def test_a_change_planned_on_an_old_revision_is_refused(win):
    first = ai.call(win, "get_drawing_info")
    ai.call(win, "draw_circle", {"center": [0, 0], "radius": 1})
    r = ai.call(win, "draw_circle", {"center": [9, 9], "radius": 1,
                                     "expected_revision": first["revision"]})
    assert "changed since revision" in r["error"]
    assert len(_msp(win)) == 1
    r = ai.call(win, "draw_circle", {"center": [9, 9], "radius": 1,
                                     "expected_revision": r["revision"]})
    assert "error" not in r and len(_msp(win)) == 2


def test_query_finds_by_type_layer_and_window_and_describes(win):
    ai.call(win, "draw_line", {"points": [[0, 0], [3, 4]]})
    ai.call(win, "draw_circle", {"center": [100, 100], "radius": 5})
    ai.call(win, "draw_polyline", {"points": [[0, 0], [1, 0], [1, 1]],
                                   "closed": True})
    r = ai.call(win, "query_entities", {"types": ["LINE"]})
    (line,) = r["entities"]
    assert line["start"] == [0, 0] and line["end"] == [3, 4]
    assert line["length"] == 5
    r = ai.call(win, "query_entities", {"window": [[90, 90], [110, 110]]})
    assert [e["type"] for e in r["entities"]] == ["CIRCLE"]
    assert r["entities"][0]["radius"] == 5
    r = ai.call(win, "query_entities", {"limit": 2})
    assert len(r["entities"]) == 2 and r["truncated"]
    r = ai.call(win, "query_entities", {"types": ["LWPOLYLINE"]})
    assert r["entities"][0]["closed"] and r["entities"][0]["vertex_count"] == 3


def test_erasing_many_waits_for_the_users_yes(win):
    handles = []
    for i in range(ai.ERASE_CONFIRM_ABOVE + 1):
        handles += ai.call(win, "draw_circle",
                           {"center": [i * 3, 0], "radius": 1})["created"]
    asked = []
    r = ai.call(win, "erase_entities", {"handles": handles})
    assert "declined" in r["error"]                    # nobody to ask: no
    r = ai.call(win, "erase_entities", {"handles": handles},
                confirm=lambda q: asked.append(q) or False)
    assert "declined" in r["error"] and asked
    assert len(_msp(win)) == len(handles)
    r = ai.call(win, "erase_entities", {"handles": handles},
                confirm=lambda q: True)
    assert "error" not in r and _msp(win) == []
    # a few go without asking
    few = ai.call(win, "draw_circle", {"center": [0, 0], "radius": 1})["created"]
    assert "error" not in ai.call(win, "erase_entities", {"handles": few})


def test_unknown_handles_and_locked_layers_are_refused(win):
    created = ai.call(win, "draw_circle",
                      {"center": [0, 0], "radius": 1})["created"]
    r = ai.call(win, "move_entities", {"handles": ["FFFFFF"], "dx": 1, "dy": 0})
    assert "no such entity" in r["error"]
    win.document.doc.layers.get("0").lock()
    r = ai.call(win, "move_entities", {"handles": created, "dx": 1, "dy": 0})
    assert "locked" in r["error"]
    (circle,) = _msp(win)
    assert circle.dxf.center.x == 0


def test_modify_tools_go_through_commands(win):
    (h,) = ai.call(win, "draw_line", {"points": [[0, 0], [10, 0]]})["created"]
    ai.call(win, "move_entities", {"handles": [h], "dx": 5, "dy": 5})
    ai.call(win, "rotate_entities", {"handles": [h], "base": [5, 5],
                                     "angle": 90})
    ai.call(win, "scale_entities", {"handles": [h], "base": [5, 5],
                                    "factor": 2})
    line = win.document.doc.entitydb[h]
    assert (line.dxf.start.x, line.dxf.start.y) == pytest.approx((5, 5))
    assert (line.dxf.end.x, line.dxf.end.y) == pytest.approx((5, 25))
    copies = ai.call(win, "copy_entities", {"handles": [h], "dx": 1,
                                            "dy": 0})["created"]
    assert len(copies) == 1 and copies[0] != h
    for _ in range(4):
        ai.call(win, "undo")
    assert (line.dxf.start.x, line.dxf.end.x) == pytest.approx((0, 10))


def test_bad_calls_come_back_as_errors(win):
    assert "unknown tool" in ai.call(win, "format_disk")["error"]
    assert "bad arguments" in ai.call(win, "draw_circle", {"centre": [0, 0]})["error"]
    assert "positive" in ai.call(win, "draw_circle",
                                 {"center": [0, 0], "radius": -1})["error"]
    assert "not a point" in ai.call(win, "draw_line",
                                    {"points": [[0, 0], "x"]})["error"]


def test_files_absolute_paths_and_overwrite_needs_a_yes(win, tmp_path):
    ai.call(win, "draw_circle", {"center": [0, 0], "radius": 10})
    assert "absolute" in ai.call(win, "save_drawing",
                                 {"path": "plano.dxf"})["error"]
    target = tmp_path / "plano.dxf"
    r = ai.call(win, "save_drawing", {"path": str(target)})
    assert r["saved"] == str(target) and target.stat().st_size > 0
    other = tmp_path / "otro.dxf"
    other.write_text("not mine")
    r = ai.call(win, "save_drawing", {"path": str(other)})
    assert "declined" in r["error"] and other.read_text() == "not mine"
    # its own file again: no question
    assert "error" not in ai.call(win, "save_drawing")
    pdf = tmp_path / "plano.pdf"
    r = ai.call(win, "export_pdf", {"path": str(pdf)})
    assert r["exported"] == str(pdf) and pdf.read_bytes()[:4] == b"%PDF"


def test_capture_is_a_png(win, qapp):
    ai.call(win, "draw_circle", {"center": [0, 0], "radius": 10})
    ai.call(win, "zoom")
    qapp.processEvents()
    image = ai.call(win, "capture_view")
    assert isinstance(image, ai.Image)
    assert image.png[:8] == b"\x89PNG\r\n\x1a\n" and "view from" in image.note
