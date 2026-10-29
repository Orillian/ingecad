# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Layer filters: AutoCAD's layer groups and property filters, as the
drawing already carries them.

AutoCAD keeps them in the layer table's extension dictionary, under
``ACLYDICTIONARY``: one XRECORD per top-level filter (``*A1``, ``*A2``...).

* a group filter, the layers the user dragged into it::

      1 AcLyLayerGroup / 90 1 / 300 <name> / 330 <layer handle> ...

* a property filter, a rule over the layers' properties::

      290 1 / 1 AcLyLayerFilter / 90 1 / 300 <name> / 301 NAME=="MUR*" AND COLOR=="1"

A nested filter lives in its parent's own extension dictionary, again under
``ACLYDICTIONARY``. ``ACAD_LAYERFILTERS`` is the pre-2005 copy of the
property filters, keyed by name; AutoCAD writes both, the modern one is
the one read here, and a rename or delete keeps the old copy in step.
Measured on a drawing made in AutoCAD 2018 for the purpose (the DWG path
needed a LibreDWG fix for the group's 330s).

Every edit is a Command addressed by the filter's *path* -- its keys from
the top dictionary down -- and by layer *names*, resolved to handles when
it runs: an undone and redone layer, or filter, may come back as another
object, and the path and the name are what stay the same.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.commands import Command, CompositeCommand
from core.i18n import tr
from core.layers import (LayerInfo, LayerPropertyCommand, current_layer_name,
                         layer_list, name_matches)

GROUP = "group"
PROPERTY = "property"

_GROUP_MARKER = "AcLyLayerGroup"
_FILTER_MARKER = "AcLyLayerFilter"
_DICTIONARY = "ACLYDICTIONARY"
_LEGACY = "ACAD_LAYERFILTERS"


@dataclass
class LayerFilter:
    name: str
    kind: str                         # GROUP or PROPERTY
    handles: tuple[str, ...] = ()     # a group's layers
    expression: str = ""              # a property filter's rule
    children: list["LayerFilter"] = field(default_factory=list)
    path: tuple[str, ...] = ()        # its keys, from the top dictionary


def _records(dictionary):
    for key, record in dictionary.items():
        if record.dxftype() == "XRECORD":
            yield key, record


def _nested(record, create: bool = False):
    """A filter's own ACLYDICTIONARY, where its nested filters live."""
    if not record.has_extension_dict:
        if not create:
            return None
        record.new_extension_dict()
    xdict = record.get_extension_dict()
    found = xdict.get(_DICTIONARY)
    if found is None and create:
        found = xdict.add_dictionary(_DICTIONARY, hard_owned=True)
    return found


def _parse(record, path) -> LayerFilter | None:
    values = [(tag.code, tag.value) for tag in record.tags]
    marker = next((v for c, v in values if c == 1), "")
    name = next((v for c, v in values if c == 300), "")
    if marker == _GROUP_MARKER:
        found = LayerFilter(name, GROUP, tuple(
            str(v).upper() for c, v in values if c == 330), path=path)
    elif marker == _FILTER_MARKER:
        found = LayerFilter(name, PROPERTY, expression=next(
            (v for c, v in values if c == 301), ""), path=path)
    else:
        return None
    nested = _nested(record)
    if nested is not None:
        found.children = _read(nested, path)
    return found


def _read(dictionary, path=()) -> list[LayerFilter]:
    return [f for f in (_parse(r, path + (k,)) for k, r in _records(dictionary))
            if f]


def _top(document, create: bool = False):
    head = document.doc.layers.head
    if not head.has_extension_dict:
        if not create:
            return None
        head.new_extension_dict()
    xdict = head.get_extension_dict()
    found = xdict.get(_DICTIONARY)
    if found is None and create:
        found = xdict.add_dictionary(_DICTIONARY, hard_owned=True)
    if found is None or found.dxftype() != "DICTIONARY":
        return None
    return found


def layer_filters(document) -> list[LayerFilter]:
    """The drawing's layer filters, nested as AutoCAD shows them."""
    dictionary = _top(document)
    return [] if dictionary is None else _read(dictionary)


# -- property filter rules -----------------------------------------------------

class UnsupportedRule(ValueError):
    """A rule names a property IngeCAD does not evaluate yet."""


_TOKEN = re.compile(r'\s*(\(|\)|==|!=|"[^"]*"|[A-Za-z_]+)')


def _tokens(text: str) -> list[str]:
    tokens, pos = [], 0
    text = text.rstrip()
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if match is None:
            raise UnsupportedRule(text)
        tokens.append(match.group(1))
        pos = match.end()
    return tokens


def _value_matches(prop: str, pattern: str, info: LayerInfo) -> bool:
    if prop == "NAME":
        return name_matches(info.name, pattern)
    if prop == "LINETYPE":
        return name_matches(info.linetype, pattern)
    if prop == "COLOR":
        return name_matches(str(info.color), pattern)
    raise UnsupportedRule(prop)


def rule_matches(rule: str, info: LayerInfo) -> bool:
    """Evaluate a property filter's rule (``NAME=="MUR*" AND COLOR=="1"``):
    AND, OR, NOT and parentheses over ``==``/``!=`` comparisons."""
    tokens = _tokens(rule)
    pos = 0

    def peek() -> str:
        return tokens[pos].upper() if pos < len(tokens) else ""

    def take() -> str:
        nonlocal pos
        if pos >= len(tokens):
            raise UnsupportedRule(rule)
        pos += 1
        return tokens[pos - 1]

    def either() -> bool:
        result = both()
        while peek() == "OR":
            take()
            result = both() or result
        return result

    def both() -> bool:
        result = single()
        while peek() == "AND":
            take()
            result = single() and result
        return result

    def single() -> bool:
        if peek() == "NOT":
            take()
            return not single()
        if peek() == "(":
            take()
            result = either()
            if take() != ")":
                raise UnsupportedRule(rule)
            return result
        prop, op, value = take().upper(), take(), take()
        if op not in ("==", "!=") or not value.startswith('"'):
            raise UnsupportedRule(rule)
        hit = _value_matches(prop, value.strip('"'), info)
        return hit if op == "==" else not hit

    result = either()
    if pos != len(tokens):
        raise UnsupportedRule(rule)
    return result


def filter_layer_names(document, layer_filter: LayerFilter,
                       within: list[str] | None = None,
                       infos: list[LayerInfo] | None = None) -> list[str]:
    """The layers a filter shows, in the Layers tab's order.

    A group shows the layers put in it. A property filter shows the layers
    its rule matches -- restricted to its parent's, when it is nested
    (``within``). A rule that names a property not evaluated yet raises
    UnsupportedRule. ``infos`` saves re-reading the layers (``layer_list``
    walks the whole drawing to know which are in use).
    """
    if infos is None:
        infos = layer_list(document)
    if layer_filter.kind == GROUP:
        mine = {layer.dxf.name for layer in document.doc.layers
                if layer.dxf.handle.upper() in layer_filter.handles}
        names = [i.name for i in infos if i.name in mine]
    else:
        names = [i.name for i in infos
                 if rule_matches(layer_filter.expression, i)]
    if within is not None:
        allowed = set(within)
        names = [n for n in names if n in allowed]
    return names


@dataclass
class FilterRow:
    depth: int
    layer_filter: LayerFilter
    names: list[str] | None           # None: a rule not evaluated yet


def filter_rows(document,
                infos: list[LayerInfo] | None = None) -> list[FilterRow]:
    """The filter tree, flattened in display order, each with its layers.

    A nested property filter looks only at its parent's layers; a nested
    group keeps the layers put in it."""
    rows: list[FilterRow] = []
    filters = layer_filters(document)
    if filters and infos is None:
        infos = layer_list(document)

    def walk(filters, depth, parent_names):
        for layer_filter in filters:
            within = parent_names if layer_filter.kind == PROPERTY else None
            try:
                names = filter_layer_names(document, layer_filter, within,
                                           infos)
            except UnsupportedRule:
                names = None
            rows.append(FilterRow(depth, layer_filter, names))
            walk(layer_filter.children, depth + 1, names or [])

    walk(filters, 0, None)
    return rows


def set_filter_state(document, names: list[str], prop: str,
                     value: bool) -> CompositeCommand | None:
    """One undo step that puts every layer of a filter in one state (On,
    Freeze, Lock, like the manager's right-click on a filter). Layers
    already there are left out; the current layer is never frozen, as
    AutoCAD refuses to. None when nothing would change."""
    current = current_layer_name(document)
    commands = []
    for name in names:
        layer = document.doc.layers.get(name)
        if layer is None:
            continue
        if prop == "frozen" and value and name == current:
            continue
        state = {"on": layer.is_on, "frozen": layer.is_frozen,
                 "locked": layer.is_locked}[prop]()
        if state != value:
            commands.append(LayerPropertyCommand(name, prop, value))
    if not commands:
        return None
    label = {
        ("on", True): tr("turn the filter's layers on"),
        ("on", False): tr("turn the filter's layers off"),
        ("frozen", True): tr("freeze the filter's layers"),
        ("frozen", False): tr("thaw the filter's layers"),
        ("locked", True): tr("lock the filter's layers"),
        ("locked", False): tr("unlock the filter's layers"),
    }[(prop, value)]
    return CompositeCommand(label, commands)


# -- editing -------------------------------------------------------------------

def _record(document, path):
    """The XRECORD of the filter at ``path``, or None."""
    dictionary, record = _top(document), None
    for depth, key in enumerate(path):
        if dictionary is None:
            return None
        record = dictionary.get(key)
        if record is None or record.dxftype() != "XRECORD":
            return None
        if depth < len(path) - 1:
            dictionary = _nested(record)
    return record


def _home(document, parent_path, create: bool = False):
    """The dictionary a filter under ``parent_path`` lives in."""
    if not parent_path:
        return _top(document, create)
    parent = _record(document, parent_path)
    return None if parent is None else _nested(parent, create)


def _walk(dictionary, path=()):
    for key, record in _records(dictionary):
        yield path + (key,), record
        nested = _nested(record)
        if nested is not None:
            yield from _walk(nested, path + (key,))


def _tags(record) -> list[tuple[int, object]]:
    return [(tag.code, tag.value) for tag in record.tags]


def _snapshot(record):
    nested = _nested(record)
    children = [] if nested is None else [
        (key, _snapshot(child)) for key, child in _records(nested)]
    return _tags(record), children


def _rebuild(dictionary, key, snapshot) -> None:
    tags, children = snapshot
    record = dictionary.add_xrecord(key)
    record.reset(tags)
    for child_key, child in children:
        _rebuild(_nested(record, create=True), child_key, child)


def _destroy(document, dictionary, key) -> None:
    record = dictionary.get(key)
    if record is None:
        return
    nested = _nested(record)
    if nested is not None:
        for child_key in list(nested.keys()):
            _destroy(document, nested, child_key)
    if record.has_extension_dict:
        record.discard_extension_dict()
    dictionary.discard(key)
    document.doc.objects.delete_entity(record)


def _legacy(document):
    head = document.doc.layers.head
    if not head.has_extension_dict:
        return None
    return head.get_extension_dict().get(_LEGACY)


def filters_key(document) -> tuple:
    """The filters as a value, cheap to compare: what the Layers tab shows
    of them changed when this did (an undo, a script)."""
    dictionary = _top(document)
    if dictionary is None:
        return ()
    return tuple((path, tuple(_tags(record)))
                 for path, record in _walk(dictionary))


def filter_names(document) -> set[str]:
    """Every filter's name, folded: AutoCAD keeps them unique."""
    dictionary = _top(document)
    if dictionary is None:
        return set()
    return {str(next((v for c, v in _tags(record) if c == 300), "")).lower()
            for _path, record in _walk(dictionary)}


def unique_filter_name(document) -> str:
    taken = filter_names(document)
    n = 1
    while tr("Group Filter{n}", n=n).lower() in taken:
        n += 1
    return tr("Group Filter{n}", n=n)


class NewGroupFilterCommand(Command):
    """A new layer group, at the top or inside another group, empty or
    with the layers it is made from."""

    name = "new layer group"

    def __init__(self, parent_path: tuple[str, ...], filter_name: str,
                 layer_names=()) -> None:
        self.parent_path = tuple(parent_path)
        self.filter_name = filter_name
        self.layer_names = list(layer_names)
        self.path: tuple[str, ...] | None = None

    def do(self, document) -> None:
        dictionary = _home(document, self.parent_path, create=True)
        key = self.path[-1] if self.path else None
        if key is None or key in dictionary:
            n = 1
            while f"*A{n}" in dictionary:
                n += 1
            key = f"*A{n}"
        layers = document.doc.layers
        dictionary.add_xrecord(key).reset(
            [(1, _GROUP_MARKER), (90, 1), (300, self.filter_name)]
            + [(330, layers.get(n).dxf.handle.upper())
               for n in self.layer_names if layers.has_entry(n)])
        self.path = self.parent_path + (key,)
        document.dirty = True

    def undo(self, document) -> None:
        _destroy(document, _home(document, self.parent_path), self.path[-1])
        document.dirty = True


class DeleteLayerFilterCommand(Command):
    """A filter and the filters nested in it; undo puts them all back."""

    name = "delete layer filter"

    def __init__(self, path: tuple[str, ...]) -> None:
        self.path = tuple(path)
        self._snapshot = None
        self._legacy = None

    def do(self, document) -> None:
        record = _record(document, self.path)
        self._snapshot = _snapshot(record)
        found = _parse(record, self.path)
        legacy = _legacy(document)
        self._legacy = None
        if found is not None and found.kind == PROPERTY and legacy is not None:
            old = legacy.get(found.name)
            if old is not None and old.dxftype() == "XRECORD":
                self._legacy = (found.name, _snapshot(old))
                _destroy(document, legacy, found.name)
        _destroy(document, _home(document, self.path[:-1]), self.path[-1])
        document.dirty = True

    def undo(self, document) -> None:
        _rebuild(_home(document, self.path[:-1], create=True), self.path[-1],
                 self._snapshot)
        if self._legacy is not None:
            key, snapshot = self._legacy
            _rebuild(_legacy(document), key, snapshot)
        document.dirty = True


class _RetagCommand(Command):
    """Rewrite one filter's tags; undo puts the old ones back."""

    def __init__(self, path: tuple[str, ...]) -> None:
        self.path = tuple(path)
        self._old: list = []

    def _retag(self, document, tags: list) -> list:
        raise NotImplementedError

    def do(self, document) -> None:
        record = _record(document, self.path)
        self._old = _tags(record)
        record.reset(self._retag(document, self._old))
        document.dirty = True

    def undo(self, document) -> None:
        _record(document, self.path).reset(self._old)
        document.dirty = True


def _rename_legacy(document, old: str, new: str) -> None:
    legacy = _legacy(document)
    record = None if legacy is None else legacy.get(old)
    if record is None or record.dxftype() != "XRECORD" or new in legacy:
        return
    tags, children = _snapshot(record)
    if tags and tags[0][0] == 1:
        tags = [(1, new)] + tags[1:]
    _destroy(document, legacy, old)
    _rebuild(legacy, new, (tags, children))


class RenameLayerFilterCommand(_RetagCommand):
    name = "rename layer filter"

    def __init__(self, path: tuple[str, ...], new_name: str) -> None:
        super().__init__(path)
        self.new_name = new_name

    def _retag(self, document, tags):
        return [(c, self.new_name if c == 300 else v) for c, v in tags]

    def _old_name(self) -> str:
        return next((v for c, v in self._old if c == 300), "")

    def _is_property(self) -> bool:
        return any(c == 1 and v == _FILTER_MARKER for c, v in self._old)

    def do(self, document) -> None:
        super().do(document)
        if self._is_property():
            _rename_legacy(document, self._old_name(), self.new_name)

    def undo(self, document) -> None:
        super().undo(document)
        if self._is_property():
            _rename_legacy(document, self.new_name, self._old_name())


class GroupLayersCommand(_RetagCommand):
    """Put layers in a group, or take them out (AutoCAD drags them in)."""

    def __init__(self, path: tuple[str, ...], layer_names, add: bool) -> None:
        super().__init__(path)
        self.layer_names = list(layer_names)
        self.add = add
        self.name = "add layers to group" if add else "remove layers from group"

    def _retag(self, document, tags):
        layers = document.doc.layers
        known = {layer.dxf.handle.upper() for layer in layers}
        wanted = [layers.get(n).dxf.handle.upper() for n in self.layer_names
                  if layers.has_entry(n)]
        kept = [str(v).upper() for c, v in tags
                if c == 330 and str(v).upper() in known]
        if self.add:
            kept += [h for h in wanted if h not in kept]
        else:
            kept = [h for h in kept if h not in wanted]
        return [(c, v) for c, v in tags if c != 330] + [(330, h) for h in kept]


def unlist_layers(document, handles) -> list:
    """Take deleted layers out of every group; the answer undoes it
    (``relist_layers``)."""
    dictionary = _top(document)
    if dictionary is None:
        return []
    gone = {str(h).upper() for h in handles}
    saved = []
    for path, record in _walk(dictionary):
        tags = _tags(record)
        kept = [(c, v) for c, v in tags
                if not (c == 330 and str(v).upper() in gone)]
        if len(kept) != len(tags):
            saved.append((path, tags))
            record.reset(kept)
    return saved


def relist_layers(document, saved) -> None:
    for path, tags in reversed(saved):
        record = _record(document, path)
        if record is not None:
            record.reset(tags)
