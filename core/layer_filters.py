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
property filters; AutoCAD writes both and the modern one is the one read
here. Nothing is written: the records travel through the round-trip as
they came (the DWG path needed a LibreDWG fix for the group's 330s).
Measured on a drawing made in AutoCAD 2018 for the purpose.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.commands import CompositeCommand
from core.i18n import tr
from core.layers import (LayerInfo, LayerPropertyCommand, current_layer_name,
                         layer_list, name_matches)

GROUP = "group"
PROPERTY = "property"


@dataclass
class LayerFilter:
    name: str
    kind: str                         # GROUP or PROPERTY
    handles: tuple[str, ...] = ()     # a group's layers
    expression: str = ""              # a property filter's rule
    children: list["LayerFilter"] = field(default_factory=list)


def _records(dictionary):
    for _key, record in dictionary.items():
        if record.dxftype() == "XRECORD":
            yield record


def _parse(record) -> LayerFilter | None:
    values = [(tag.code, tag.value) for tag in record.tags]
    marker = next((v for c, v in values if c == 1), "")
    name = next((v for c, v in values if c == 300), "")
    if marker == "AcLyLayerGroup":
        found = LayerFilter(name, GROUP, tuple(
            str(v).upper() for c, v in values if c == 330))
    elif marker == "AcLyLayerFilter":
        found = LayerFilter(name, PROPERTY, expression=next(
            (v for c, v in values if c == 301), ""))
    else:
        return None
    if record.has_extension_dict:
        nested = record.get_extension_dict().get("ACLYDICTIONARY")
        if nested is not None:
            found.children = _read(nested)
    return found


def _read(dictionary) -> list[LayerFilter]:
    return [f for f in (_parse(r) for r in _records(dictionary)) if f]


def layer_filters(document) -> list[LayerFilter]:
    """The drawing's layer filters, nested as AutoCAD shows them."""
    head = document.doc.layers.head
    if not head.has_extension_dict:
        return []
    dictionary = head.get_extension_dict().get("ACLYDICTIONARY")
    if dictionary is None or dictionary.dxftype() != "DICTIONARY":
        return []
    return _read(dictionary)


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
