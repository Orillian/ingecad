# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""How a surveyor and a road designer write angles, bearings and stations.

One place for the formats several bundled plugins print (Topography's
charts and profiles, Roads' axis and curve tables): a plugin never imports
another plugin, so what two of them must write the same way lives here.
Pure functions, no document, no Qt.

- azimuth: degrees from north, clockwise; CAD angle: degrees from east, CCW
- bearing: the quadrant form ``N 45°30'20" E``
- station (progresiva): ``0+020.00``, kilometres + metres
"""
from __future__ import annotations


def format_dms(degrees: float, seconds: bool = True) -> str:
    """``40°00'00"`` (or ``40°00'`` without seconds)."""
    total = round(degrees * 3600.0) if seconds else round(degrees * 60.0) * 60
    d, rest = divmod(int(total), 3600)
    m, s = divmod(rest, 60)
    return f"{d}°{m:02d}'{s:02d}\"" if seconds else f"{d}°{m:02d}'"


def format_bearing(azimuth: float, seconds: bool = True) -> str:
    """An azimuth as the quadrant bearing surveyors read: ``N 45°30'20" E``."""
    az = azimuth % 360.0
    if az <= 90.0:
        ns, ew, angle = "N", "E", az
    elif az <= 180.0:
        ns, ew, angle = "S", "E", 180.0 - az
    elif az < 270.0:
        ns, ew, angle = "S", "W", az - 180.0
    else:
        ns, ew, angle = "N", "W", 360.0 - az
    return f"{ns} {format_dms(angle, seconds)} {ew}"


def azimuth_to_cad(azimuth: float) -> float:
    """Azimuth (from north, clockwise) -> CAD angle (from east, CCW)."""
    return (90.0 - azimuth) % 360.0


def cad_to_azimuth(angle: float) -> float:
    """CAD angle (from east, CCW) -> azimuth (from north, clockwise)."""
    return (90.0 - angle) % 360.0


def format_station(s: float, decimals: int = 2) -> str:
    """A station the Peruvian way: ``0+020.00`` (``0+020`` with no decimals)."""
    km, m = divmod(round(s, decimals), 1000.0)
    width = 3 if decimals <= 0 else 4 + decimals
    return f"{int(km)}+{m:0{width}.{max(decimals, 0)}f}"


def readable_rotation(angle_deg: float) -> float:
    """The rotation a label along a line takes so it never reads upside
    down: AutoCAD's rule, (-90, 90]."""
    a = angle_deg % 360.0
    if 90.0 < a <= 270.0:
        a -= 180.0
    return ((a + 180.0) % 360.0) - 180.0
