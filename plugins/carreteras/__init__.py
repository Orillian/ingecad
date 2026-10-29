# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Roads -- the road designer's plugin (docs/plan-complementos.md §6), after
the Peruvian norm, MTC *Manual de Carreteras: Diseño Geométrico DG-2018*.

C1, the axis and its stationing: a polyline of tangents and arcs becomes an
axis with its start station and direction; ticks and station labels every
N metres (``0+020``), reversed or redrawn on demand; the axis table.
C2, simple horizontal curves: a chain of tangents with a radius per PI
becomes the axis with its arcs, the PI, PC and PT marked, and the table of
curve elements (Δ, R, T, Lc, E, M, C, PC, PT, direction).
Everything it draws is plain DXF (LWPOLYLINE, LINE, TEXT, layers); what the
axis remembers rides in XDATA under the plugin's own APPID.
"""
from __future__ import annotations

from pathlib import Path

from core.plugins import SEPARATOR, MenuItem, PluginSpec, Submenu, ToolbarItem

from .tools import TOOL_CLASSES

PLUGIN = PluginSpec(
    id="carreteras",
    name="Roads",
    version="0.1.0",
    description="Road axis, stationing and horizontal curves after the Peruvian DG-2018.",
    tools=dict(TOOL_CLASSES),
    menu=(
        Submenu("Axis", (
            MenuItem("Define axis...", "ROADAXIS"),
            MenuItem("Stationing...", "STATIONING"),
            MenuItem("Redraw stationing", "RESTATION"),
            MenuItem("Reverse stationing", "AXISREVERSE"),
        )),
        Submenu("Horizontal curves", (
            MenuItem("Fit curves at the PIs...", "HCURVES"),
            MenuItem("Curve table...", "CURVETABLE"),
        )),
        SEPARATOR,
        MenuItem("Axis table...", "AXISTABLE"),
    ),
    toolbar=(
        ToolbarItem("Define axis...", "ROADAXIS"),
        ToolbarItem("Stationing...", "STATIONING"),
        ToolbarItem("Fit curves at the PIs...", "HCURVES"),
        ToolbarItem("Axis table...", "AXISTABLE"),
        ToolbarItem("Curve table...", "CURVETABLE"),
    ),
    i18n_dir=Path(__file__).parent / "i18n",
)
