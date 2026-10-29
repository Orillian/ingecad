# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A road axis as exact geometry: straight tangents and circular arcs,
stationed by their true length. Pure: no document, no Qt.

The axis is an open polyline of ``(x, y, bulge)`` vertices, the way an
LWPOLYLINE stores it. Topography's alignment flattens arcs to a centimetre,
which is enough for a profile; a road's PC and PT stations are read off the
plan to the millimetre, so here an arc's length is ``R·θ`` exactly.

Curve elements (MTC, *Manual de Carreteras: Diseño Geométrico DG-2018*,
simple circular curve)::

    T  = R·tan(Δ/2)            tangent, PI to PC and PI to PT
    Lc = π·R·Δ/180             length of the curve
    E  = R·(1/cos(Δ/2) − 1)    external, PI to the middle of the curve
    M  = R·(1 − cos(Δ/2))      middle ordinate (flecha)
    C  = 2·R·sin(Δ/2)          long chord, PC to PT
"""
from __future__ import annotations

import math
from dataclasses import dataclass

Point = tuple[float, float]
Vertex = tuple[float, float, float]          # x, y, bulge to the next vertex

EPS = 1e-9


# -- segments --------------------------------------------------------------------

@dataclass(frozen=True)
class Segment:
    """One piece of the axis: a straight line (bulge 0) or a circular arc."""

    start: Point
    end: Point
    bulge: float = 0.0

    @property
    def is_arc(self) -> bool:
        return abs(self.bulge) > 1e-12

    @property
    def chord(self) -> float:
        return math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])

    @property
    def theta(self) -> float:
        """Signed central angle in radians (positive = counterclockwise)."""
        return 4.0 * math.atan(self.bulge)

    @property
    def radius(self) -> float:
        b = abs(self.bulge)
        return self.chord * (1.0 + b * b) / (4.0 * b) if self.is_arc else math.inf

    @property
    def center(self) -> Point:
        c = self.chord
        ux, uy = (self.end[0] - self.start[0]) / c, (self.end[1] - self.start[1]) / c
        mx, my = (self.start[0] + self.end[0]) / 2.0, (self.start[1] + self.end[1]) / 2.0
        sagitta = abs(self.bulge) * c / 2.0
        d = math.copysign(self.radius - sagitta, self.bulge)
        return (mx - uy * d, my + ux * d)

    @property
    def length(self) -> float:
        return abs(self.theta) * self.radius if self.is_arc else self.chord

    @property
    def start_angle(self) -> float:
        """Direction of travel at the start, degrees CCW from east."""
        chord_angle = math.degrees(math.atan2(self.end[1] - self.start[1],
                                              self.end[0] - self.start[0]))
        return chord_angle - math.degrees(self.theta) / 2.0

    @property
    def end_angle(self) -> float:
        return self.start_angle + math.degrees(self.theta)

    def at(self, t: float) -> tuple[Point, float]:
        """(point, direction in degrees) ``t`` metres from the start."""
        t = max(0.0, min(self.length, t))
        if not self.is_arc:
            c = self.chord
            if c <= 0:
                return self.start, 0.0
            f = t / c
            return ((self.start[0] + f * (self.end[0] - self.start[0]),
                     self.start[1] + f * (self.end[1] - self.start[1])), self.start_angle)
        cx, cy = self.center
        phi = math.copysign(t / self.radius, self.bulge)
        dx, dy = self.start[0] - cx, self.start[1] - cy
        cos_p, sin_p = math.cos(phi), math.sin(phi)
        return ((cx + dx * cos_p - dy * sin_p, cy + dx * sin_p + dy * cos_p),
                self.start_angle + math.degrees(phi))


# -- the axis -------------------------------------------------------------------------

class Alignment:
    """An open chain of segments, stationed from ``start_station``."""

    def __init__(self, vertices, start_station: float = 0.0) -> None:
        verts = [(float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0)
                 for v in vertices]
        if len(verts) < 2:
            raise ValueError("an axis needs at least two vertices")
        self.vertices: list[Vertex] = verts
        self.start_station = float(start_station)
        self.segments = [Segment((a[0], a[1]), (b[0], b[1]), a[2])
                         for a, b in zip(verts, verts[1:])
                         if math.hypot(b[0] - a[0], b[1] - a[1]) > EPS]
        if not self.segments:
            raise ValueError("the axis has no length")
        self._runs = []
        run = 0.0
        for seg in self.segments:
            self._runs.append(run)
            run += seg.length
        self.length = run

    @property
    def end_station(self) -> float:
        return self.start_station + self.length

    def reversed(self, start_station: float | None = None) -> "Alignment":
        return Alignment(reverse_vertices(self.vertices),
                         self.start_station if start_station is None else start_station)

    def at(self, s: float) -> tuple[Point, float]:
        """(point, direction) at distance ``s`` from the start of the axis."""
        s = max(0.0, min(self.length, s))
        for seg, run in zip(reversed(self.segments), reversed(self._runs)):
            if s >= run - EPS:
                return seg.at(s - run)
        return self.segments[0].at(0.0)

    def at_station(self, station: float) -> tuple[Point, float]:
        return self.at(station - self.start_station)

    def segment_runs(self):
        """(segment, distance from the start to its first point)."""
        return list(zip(self.segments, self._runs))


def reverse_vertices(vertices) -> list[Vertex]:
    """The same polyline walked the other way: the order flips and every
    arc turns the other way round (its bulge changes sign)."""
    verts = list(vertices)
    out = []
    for i in range(len(verts) - 1, -1, -1):
        bulge = -verts[i - 1][2] if i > 0 else 0.0
        out.append((verts[i][0], verts[i][1], bulge))
    return out


# -- stations ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Tick:
    station: float
    point: Point
    angle: float               # direction of travel, degrees
    regular: bool              # a multiple of the interval (else start / end)
    km: bool = False           # a full kilometre


def station_ticks(alignment: Alignment, interval: float) -> list[Tick]:
    """Every multiple of ``interval`` along the axis, plus its start and its
    end when they fall between them; a multiple of 1000 m is a km tick."""
    if interval <= 0:
        raise ValueError("the station interval must be positive")
    s0, s1 = alignment.start_station, alignment.end_station
    ticks = []
    k = math.ceil((s0 - 1e-6) / interval)
    if abs(k * interval - s0) > 1e-6:
        point, angle = alignment.at(0.0)
        ticks.append(Tick(s0, point, angle, False))
    while k * interval <= s1 + 1e-6:
        station = k * interval
        point, angle = alignment.at_station(station)
        km = abs(station / 1000.0 - round(station / 1000.0)) < 1e-9
        ticks.append(Tick(station, point, angle, True, km))
        k += 1
    if abs(ticks[-1].station - s1) > 1e-6:
        point, angle = alignment.at(alignment.length)
        ticks.append(Tick(s1, point, angle, False))
    return ticks


# -- curve elements ------------------------------------------------------------------------

@dataclass(frozen=True)
class CurveElements:
    delta: float               # deflection, degrees
    radius: float

    @property
    def half(self) -> float:
        return math.radians(self.delta) / 2.0

    @property
    def tangent(self) -> float:
        return self.radius * math.tan(self.half)

    @property
    def length(self) -> float:
        return math.pi * self.radius * self.delta / 180.0

    @property
    def external(self) -> float:
        return self.radius * (1.0 / math.cos(self.half) - 1.0)

    @property
    def middle_ordinate(self) -> float:
        return self.radius * (1.0 - math.cos(self.half))

    @property
    def chord(self) -> float:
        return 2.0 * self.radius * math.sin(self.half)


@dataclass(frozen=True)
class PI:
    """A point of intersection of two tangents, with its curve if any."""

    number: int
    point: Point
    station: float
    curve: CurveElements | None = None
    left: bool = False                    # the axis turns left (Izq.)
    pc: Point | None = None
    pt: Point | None = None
    pc_station: float | None = None
    pt_station: float | None = None


def _deflection(a_in: float, a_out: float) -> float:
    """Signed turn from one direction to the next, degrees, in (-180, 180]."""
    d = (a_out - a_in) % 360.0
    return d - 360.0 if d > 180.0 else d


def points_of_intersection(alignment: Alignment) -> list[PI]:
    """The PIs of the axis in stationing order: one per arc (where its two
    tangents meet) and one per corner between straight pieces."""
    out: list[PI] = []
    runs = alignment.segment_runs()
    for i, (seg, run) in enumerate(runs):
        if seg.is_arc:
            delta = abs(math.degrees(seg.theta))
            elements = CurveElements(delta, seg.radius)
            rad = math.radians(seg.start_angle)
            t = elements.tangent
            pi = (seg.start[0] + t * math.cos(rad), seg.start[1] + t * math.sin(rad))
            pc_station = alignment.start_station + run
            out.append(PI(len(out) + 1, pi, pc_station + t, elements, seg.bulge > 0,
                          seg.start, seg.end, pc_station, pc_station + seg.length))
        if i + 1 < len(runs):
            nxt = runs[i + 1][0]
            if not seg.is_arc and not nxt.is_arc:
                turn = _deflection(seg.end_angle, nxt.start_angle)
                if abs(turn) > 1e-7:
                    out.append(PI(len(out) + 1, seg.end,
                                  alignment.start_station + run + seg.length,
                                  None, turn > 0))
    return out


class TangentOverlap(ValueError):
    """Two curves need more tangent than the straight between their PIs."""

    def __init__(self, first: int, second: int, needed: float, available: float) -> None:
        where = f"PI-{first}" if first == second else f"PI-{first} and PI-{second}"
        super().__init__(f"{where}: T = {needed:.3f} m > {available:.3f} m")
        self.first, self.second = first, second
        self.needed, self.available = needed, available


def deflections(points) -> list[float]:
    """Signed deflection at each interior vertex of a chain of tangents."""
    out = []
    for a, b, c in zip(points, points[1:], points[2:]):
        a_in = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        a_out = math.degrees(math.atan2(c[1] - b[1], c[0] - b[0]))
        out.append(_deflection(a_in, a_out))
    return out


def fit_curves(points, radii) -> list[Vertex]:
    """The axis through a chain of tangents with a simple circular curve of
    radius ``radii[i]`` at each interior vertex (PI), as (x, y, bulge)
    vertices. A PI where the tangents are aligned, or whose radius is 0,
    keeps its corner. Raises :class:`TangentOverlap` when two curves would
    need more than the tangent between them, and ValueError on a PI that
    turns back on itself."""
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) < 3:
        raise ValueError("a chain of tangents needs at least three vertices")
    turns = deflections(pts)
    if len(radii) != len(turns):
        raise ValueError(f"{len(radii)} radii for {len(turns)} PIs")
    tangents = []
    for i, (turn, r) in enumerate(zip(turns, radii)):
        if abs(abs(turn) - 180.0) < 1e-7:
            raise ValueError(f"PI-{i + 1} turns back on itself")
        if r < 0:
            raise ValueError(f"PI-{i + 1}: the radius must be positive")
        tangents.append(0.0 if abs(turn) < 1e-7 or r == 0
                        else CurveElements(abs(turn), r).tangent)
    for j in range(len(pts) - 1):
        length = math.hypot(pts[j + 1][0] - pts[j][0], pts[j + 1][1] - pts[j][1])
        before = tangents[j - 1] if j >= 1 else 0.0          # at vertex j
        after = tangents[j] if j < len(tangents) else 0.0     # at vertex j+1
        if before + after > length + 1e-9:
            if j == 0 or j == len(pts) - 2:
                # a curve longer than the first or last tangent: the axis
                # would start or end inside the curve
                which = j + 1 if j == 0 else j
                raise TangentOverlap(which, which, before + after, length)
            raise TangentOverlap(j, j + 1, before + after, length)
    out: list[Vertex] = []

    def push(x: float, y: float, bulge: float) -> None:
        if out and math.hypot(out[-1][0] - x, out[-1][1] - y) < 1e-9:
            out[-1] = (out[-1][0], out[-1][1], bulge)      # PT meets the next PC
        else:
            out.append((x, y, bulge))

    push(pts[0][0], pts[0][1], 0.0)
    for i, (turn, t) in enumerate(zip(turns, tangents)):
        a, b, c = pts[i], pts[i + 1], pts[i + 2]
        if t <= 0.0:
            push(b[0], b[1], 0.0)
            continue
        lin = math.hypot(b[0] - a[0], b[1] - a[1])
        lout = math.hypot(c[0] - b[0], c[1] - b[1])
        pc = (b[0] - (b[0] - a[0]) / lin * t, b[1] - (b[1] - a[1]) / lin * t)
        pt = (b[0] + (c[0] - b[0]) / lout * t, b[1] + (c[1] - b[1]) / lout * t)
        push(pc[0], pc[1], math.copysign(math.tan(math.radians(abs(turn)) / 4.0), turn))
        push(pt[0], pt[1], 0.0)
    push(pts[-1][0], pts[-1][1], 0.0)
    return out


def parse_station(text: str) -> float:
    """``1+250.50``, ``1+250,5`` or plain metres ``1250.5``."""
    raw = text.strip().replace(",", ".")
    if "+" in raw:
        km, _, m = raw.partition("+")
        km_v = float(km) if km.strip() else 0.0
        m_v = float(m)
        if m_v < 0 or km_v < 0:
            raise ValueError(text)
        return km_v * 1000.0 + m_v
    return float(raw)
