# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Layer filters: the groups and property filters AutoCAD saves with a
drawing show in the Layers tab, and survive Save as DWG.

A reviewer asked for AutoCAD's layer groups (eighth review, 33:55). The
format is not documented; it was read from a drawing made in AutoCAD 2018
for the purpose (a group with two layers and a nested group, a property
filter ``NAME=="MUR*" AND COLOR=="1"``), and the drawing here is built to
the same tags. Saving it as DWG used to empty the groups: LibreDWG's DXF
importer dropped an XRECORD's 330s (tools/libredwg-patches, in_dxf.c).
"""
from __future__ import annotations

import time
from pathlib import Path

import ezdxf
import pytest

from core.layer_filters import (GROUP, PROPERTY, UnsupportedRule,
                                filter_rows, layer_filters, rule_matches)
from core.layers import LayerInfo
from formats.dwg_bridge import find_dxf2dwg


def _drawing(path: Path) -> Path:
    """The AutoCAD sample's layers and filters, tag for tag."""
    doc = ezdxf.new("R2018")
    handles = {}
    for name, color in (("MUROS", 1), ("MUROS-EXT", 1), ("PUERTAS", 2),
                        ("COTAS", 3), ("TEXTO", 7)):
        handles[name] = doc.layers.add(name, color=color).dxf.handle
        doc.modelspace().add_line((0, 0), (10, 0), dxfattribs={"layer": name})
    filters = doc.layers.head.new_extension_dict().add_dictionary(
        "ACLYDICTIONARY", hard_owned=True)
    group = filters.add_xrecord("*A1")
    group.reset([(1, "AcLyLayerGroup"), (90, 1), (300, "Arquitectura"),
                 (330, handles["TEXTO"]), (330, handles["PUERTAS"])])
    nested = group.new_extension_dict().add_dictionary(
        "ACLYDICTIONARY", hard_owned=True).add_xrecord("*A1")
    nested.reset([(1, "AcLyLayerGroup"), (90, 1), (300, "Carpinteria"),
                  (330, handles["PUERTAS"])])
    rule = filters.add_xrecord("*A2")
    rule.reset([(290, 1), (1, "AcLyLayerFilter"), (90, 1),
                (300, "Rojas-MUR"), (301, 'NAME=="MUR*" AND COLOR=="1"')])
    # the pre-2005 copy AutoCAD writes next to it, keyed by name
    legacy = doc.layers.head.get_extension_dict().add_dictionary(
        "ACAD_LAYERFILTERS").add_xrecord("Rojas-MUR")
    legacy.reset([(1, "Rojas-MUR"), (1, "MUR*"), (1, "1"), (1, "*"), (70, 0),
                  (1, "*"), (1, "*")])
    doc.saveas(path)
    return path


def _tree(document) -> list[tuple[int, str, str, list | None]]:
    return [(r.depth, r.layer_filter.kind, r.layer_filter.name, r.names)
            for r in filter_rows(document)]


EXPECTED = [
    (0, GROUP, "Arquitectura", ["PUERTAS", "TEXTO"]),
    (1, GROUP, "Carpinteria", ["PUERTAS"]),
    (0, PROPERTY, "Rojas-MUR", ["MUROS", "MUROS-EXT"]),
]


def test_the_filters_read_as_autocad_shows_them(tmp_path):
    from core.document import Document

    document = Document.load(_drawing(tmp_path / "groups.dxf"))
    assert _tree(document) == EXPECTED


def test_a_drawing_without_filters_has_none():
    from core.document import Document

    assert layer_filters(Document.new()) == []


def _info(name, color=7, linetype="Continuous") -> LayerInfo:
    return LayerInfo(name, color, linetype, -3, True, False, False, False)


@pytest.mark.parametrize("rule, name, color, expected", [
    ('NAME=="MUR*" AND COLOR=="1"', "MUROS", 1, True),
    ('NAME=="MUR*" AND COLOR=="1"', "MUROS", 2, False),
    ('NAME=="mur*" AND COLOR=="1"', "Muros", 1, True),       # any case
    ('( NAME== "MUR*" ) and ( COLOR== "1" )', "MUROS", 1, True),  # old form
    ('NAME=="A*" OR NAME=="B*"', "B-1", 7, True),
    ('NOT NAME=="A*"', "A-1", 7, False),
    ('NAME!="A*"', "B-1", 7, True),
    ('(NAME=="A*" OR NAME=="B*") AND COLOR=="3"', "A-1", 7, False),
])
def test_property_filter_rules(rule, name, color, expected):
    assert rule_matches(rule, _info(name, color)) is expected


def test_a_rule_on_a_property_not_read_yet_says_so():
    with pytest.raises(UnsupportedRule):
        rule_matches('TRANSPARENCY=="50"', _info("A"))


def _wait_regen(qapp, win, timeout_s=30.0):
    t0 = time.monotonic()
    while (win._open_thread is not None or win._regen_worker is not None) \
            and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()


@pytest.fixture
def panel(qapp, tmp_path):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.open_path(_drawing(tmp_path / "groups.dxf"))
    _wait_regen(qapp, win)
    if win._layers_panel is None:
        win.toggle_layers_panel()
    panel = win._layers_panel
    panel.refresh()
    yield panel
    win.document.dirty = False
    win.close()


def _item(panel, name):
    from PySide6.QtWidgets import QTreeWidgetItemIterator

    found = QTreeWidgetItemIterator(panel.filters)
    while found.value():
        if found.value().text(0) == name:
            return found.value()
        found += 1
    raise AssertionError(f"no filter {name!r} in the tree")


def test_choosing_a_filter_shows_its_layers(panel):
    assert not panel.filters.isHidden()
    assert "COTAS" in panel._rows                     # All, to start with
    panel.filters.setCurrentItem(_item(panel, "Carpinteria"))
    assert panel._rows == ["PUERTAS"]
    panel.filters.setCurrentItem(_item(panel, "Rojas-MUR"))
    assert panel._rows == ["MUROS", "MUROS-EXT"]
    panel.filters.setCurrentItem(_item(panel, "All Used Layers"))
    assert "COTAS" in panel._rows and "Defpoints" not in panel._rows


def test_a_filter_turns_its_layers_off_in_one_undo_step(panel, qapp):
    win = panel.window
    layers = win.document.doc.layers
    panel.filters.setCurrentItem(_item(panel, "Arquitectura"))
    panel.set_filter_state("on", False)
    _wait_regen(qapp, win)
    assert not layers.get("PUERTAS").is_on() and not layers.get("TEXTO").is_on()
    assert layers.get("MUROS").is_on()
    win._on_command_submitted("U")
    _wait_regen(qapp, win)
    assert layers.get("PUERTAS").is_on() and layers.get("TEXTO").is_on()


def test_the_filter_tree_stays_hidden_without_filters(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    _wait_regen(qapp, win)
    try:
        if win._layers_panel is None:
            win.toggle_layers_panel()
        win._layers_panel.refresh()
        assert win._layers_panel.filters.isHidden()
    finally:
        win.close()


@pytest.mark.skipif(find_dxf2dwg() is None, reason="LibreDWG not available")
def test_groups_keep_their_layers_through_save_as_dwg(tmp_path):
    from core.document import Document
    from formats.dwg_bridge import load_dwg

    document = Document.load(_drawing(tmp_path / "groups.dxf"))
    document.save_as(tmp_path / "groups.dwg")
    assert _tree(load_dwg(tmp_path / "groups.dwg")) == EXPECTED


# -- editing -------------------------------------------------------------------

def _document(tmp_path):
    from core.document import Document

    return Document.load(_drawing(tmp_path / "groups.dxf"))


def _undo_redo(document, command):
    """Do, undo, redo: the tree after each."""
    before = _tree(document)
    command.do(document)
    after = _tree(document)
    command.undo(document)
    assert _tree(document) == before
    command.do(document)
    assert _tree(document) == after
    return after


def test_a_new_group_at_the_top_and_inside_another(tmp_path):
    from core.layer_filters import NewGroupFilterCommand

    document = _document(tmp_path)
    after = _undo_redo(document, NewGroupFilterCommand((), "Estructura",
                                                       ["COTAS"]))
    assert (0, GROUP, "Estructura", ["COTAS"]) in after
    inside = NewGroupFilterCommand(("*A1",), "Ventanas")
    after = _undo_redo(document, inside)
    assert after[:3] == [(0, GROUP, "Arquitectura", ["PUERTAS", "TEXTO"]),
                         (1, GROUP, "Carpinteria", ["PUERTAS"]),
                         (1, GROUP, "Ventanas", [])]


def test_a_new_group_in_a_drawing_without_filters(tmp_path):
    from core.document import Document
    from core.layer_filters import NewGroupFilterCommand

    document = Document.new()
    _undo_redo(document, NewGroupFilterCommand((), "Uno", ["0"]))
    assert _tree(document) == [(0, GROUP, "Uno", ["0"])]


def test_layers_go_into_a_group_and_out_of_it(tmp_path):
    from core.layer_filters import GroupLayersCommand

    document = _document(tmp_path)
    after = _undo_redo(document, GroupLayersCommand(("*A1",), ["COTAS",
                                                              "TEXTO"], True))
    assert after[0] == (0, GROUP, "Arquitectura", ["COTAS", "PUERTAS", "TEXTO"])
    after = _undo_redo(document, GroupLayersCommand(("*A1",), ["PUERTAS"],
                                                    False))
    assert after[0] == (0, GROUP, "Arquitectura", ["COTAS", "TEXTO"])
    assert after[1] == (1, GROUP, "Carpinteria", ["PUERTAS"])     # its own


def test_rename_and_delete_keep_the_old_copy_in_step(tmp_path):
    from core.layer_filters import (DeleteLayerFilterCommand,
                                    RenameLayerFilterCommand)

    document = _document(tmp_path)
    legacy = document.doc.layers.head.get_extension_dict()["ACAD_LAYERFILTERS"]
    after = _undo_redo(document, RenameLayerFilterCommand(("*A2",), "Muros"))
    assert after[2] == (0, PROPERTY, "Muros", ["MUROS", "MUROS-EXT"])
    assert list(legacy.keys()) == ["Muros"]
    assert legacy["Muros"].tags[0].value == "Muros"
    after = _undo_redo(document, DeleteLayerFilterCommand(("*A2",)))
    assert [name for _d, _k, name, _n in after] == ["Arquitectura", "Carpinteria"]
    assert list(legacy.keys()) == []
    command = DeleteLayerFilterCommand(("*A1",))      # with its nested group
    after = _undo_redo(document, command)
    assert after == []
    command.undo(document)
    assert [name for _d, _k, name, _n in _tree(document)] == [
        "Arquitectura", "Carpinteria"]


@pytest.mark.parametrize("how", ["delete", "purge"])
def test_a_deleted_layer_leaves_its_groups_and_comes_back_to_them(tmp_path, how):
    """Deleting a layer took it out of nothing, and undo made a NEW layer
    (another handle; lineweight, plot and description lost): its groups
    no longer knew it."""
    from core.cleanup import PurgeCommand
    from core.layers import DeleteLayerCommand

    document = _document(tmp_path)
    layer = document.doc.layers.get("PUERTAS")
    layer.dxf.lineweight = 50
    layer.description = "doors"
    handle = layer.dxf.handle
    command = (DeleteLayerCommand("PUERTAS") if how == "delete"
               else PurgeCommand({"layers": ["PUERTAS"]}))
    command.do(document)
    assert _tree(document)[:2] == [(0, GROUP, "Arquitectura", ["TEXTO"]),
                                   (1, GROUP, "Carpinteria", [])]
    record = document.doc.layers.head.get_extension_dict()["ACLYDICTIONARY"]["*A1"]
    assert handle not in [str(t.value) for t in record.tags if t.code == 330]
    command.undo(document)
    assert _tree(document) == EXPECTED
    back = document.doc.layers.get("PUERTAS")
    assert (back.dxf.handle, back.dxf.lineweight, back.description) == (
        handle, 50, "doors")


def test_a_deleted_layer_leaves_no_orphan_in_the_file(tmp_path):
    """A layer's extension dictionary stayed in OBJECTS when the layer was
    unhooked, and was saved with an owner that no longer existed."""
    from core.document import Document
    from core.layers import DeleteLayerCommand

    doc = ezdxf.new("R2018")
    doc.layers.add("X").new_extension_dict().add_xrecord(
        "ADSK_XREC_LAYER_RECONCILED").reset([(290, 1)])
    doc.saveas(tmp_path / "x.dxf")
    document = Document.load(tmp_path / "x.dxf")
    command = DeleteLayerCommand("X")
    command.do(document)
    document.doc.saveas(tmp_path / "gone.dxf")
    assert ezdxf.readfile(tmp_path / "gone.dxf").audit().fixes == []
    command.undo(document)
    document.doc.saveas(tmp_path / "back.dxf")
    back = ezdxf.readfile(tmp_path / "back.dxf")
    assert back.audit().fixes == []
    assert back.layers.get("X").get_extension_dict().get(
        "ADSK_XREC_LAYER_RECONCILED") is not None


@pytest.mark.skipif(find_dxf2dwg() is None, reason="LibreDWG not available")
def test_groups_made_here_survive_save_as_dwg(tmp_path):
    from core.document import Document
    from core.layer_filters import NewGroupFilterCommand
    from formats.dwg_bridge import load_dwg

    document = Document.new()
    for name in ("A", "B"):
        document.doc.layers.add(name)
    outer = NewGroupFilterCommand((), "Afuera", ["A", "B"])
    outer.do(document)
    NewGroupFilterCommand(outer.path, "Adentro", ["B"]).do(document)
    document.save_as(tmp_path / "made.dwg")
    assert _tree(load_dwg(tmp_path / "made.dwg")) == [
        (0, GROUP, "Afuera", ["A", "B"]), (1, GROUP, "Adentro", ["B"])]


def test_the_panel_makes_renames_fills_and_deletes_a_group(panel, qapp):
    win = panel.window
    panel.filters.setCurrentItem(_item(panel, "Arquitectura"))
    panel.new_group_filter()                         # inside the chosen group
    item = panel.filters.currentItem()
    assert item.text(0) == "Group Filter1"
    assert item.parent().text(0) == "Arquitectura"
    item.setText(0, "Ventanas")                      # what typing the name does
    assert _item(panel, "Ventanas") is panel.filters.currentItem()
    path = panel._chosen_row().layer_filter.path
    panel.group_layers(path, ["COTAS"], True)
    assert panel._rows == ["COTAS"]
    _item(panel, "Carpinteria").setText(0, "Ventanas")   # a duplicate name
    assert _item(panel, "Carpinteria") is not None
    panel.filters.setCurrentItem(_item(panel, "Ventanas"))
    panel.delete_filter()
    assert [r.layer_filter.name for r in panel._filter_rows] == [
        "Arquitectura", "Carpinteria", "Rojas-MUR"]
    names = lambda: [(r.layer_filter.name, r.names) for r in panel._filter_rows]  # noqa: E731
    for expected in (("Ventanas", ["COTAS"]), ("Ventanas", []),
                     ("Group Filter1", [])):
        win._on_command_submitted("U")
        _wait_regen(qapp, win)
        assert expected in names()
    win._on_command_submitted("U")
    _wait_regen(qapp, win)
    assert [n for n, _l in names()] == ["Arquitectura", "Carpinteria", "Rojas-MUR"]


def test_the_first_group_of_a_drawing_shows_the_tree(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    win.new_document()
    _wait_regen(qapp, win)
    try:
        if win._layers_panel is None:
            win.toggle_layers_panel()
        panel = win._layers_panel
        panel.refresh()
        assert panel.filters.isHidden()
        panel.table.selectRow(panel._rows.index("0"))
        panel._new_group_with(panel.selected_layers())
        assert not panel.filters.isHidden()
        assert panel._rows == ["0"]
    finally:
        win.document.dirty = False
        win.close()
