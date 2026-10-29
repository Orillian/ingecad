# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A construction line stays endless however far the view zooms out (#104).

#98 baked an XLINE ten drawing diagonals long; the user came back: "Al
principio sí la hace como infinita en la ventana pero si te alejas vuelve a
ser finita". The baked segment stays, and the viewport carries the line on
to the edge of the view every frame -- both ways for an XLINE, one way for
a RAY.
"""
from __future__ import annotations

import time

import pytest

from render.batches import ConstructionLine, construction_extensions

RECT = (-1000.0, -1000.0, 1000.0, 1000.0)


def _xline(ray=False, handle="A"):
    return ConstructionLine(handle, (-10.0, -10.0), (10.0, 10.0), ray,
                            (255, 0, 0, 255))


def test_an_xline_goes_on_to_the_rect_both_ways():
    pieces = construction_extensions([_xline()], RECT)
    ends = sorted((round(p[0]), round(p[1]), round(p[2]), round(p[3]))
                  for p in pieces)
    assert ends == [(-1000, -1000, -10, -10), (10, 10, 1000, 1000)]
    assert all(p[4] == (255, 0, 0, 255) for p in pieces)


def test_a_ray_goes_on_only_past_its_far_end():
    (piece,) = construction_extensions([_xline(ray=True)], RECT)
    assert piece[:4] == pytest.approx((10, 10, 1000, 1000))


def test_nothing_past_the_ends_inside_a_small_view_or_for_a_hidden_line():
    assert construction_extensions([_xline()], (-5, -5, 5, 5)) == []
    assert construction_extensions([_xline()], RECT, skip={"A"}) == []
    # a line that misses the view entirely
    assert construction_extensions(
        [ConstructionLine("B", (0, 2000), (1, 2000), False, (1, 1, 1, 255))],
        RECT) == []


def _wait_regen(qapp, win, timeout_s=20.0):
    t0 = time.monotonic()
    while win._regen_worker is not None and time.monotonic() - t0 < timeout_s:
        qapp.processEvents()


def _lit(img, x, y, radius=2) -> bool:
    """A drawn pixel near (x, y): brighter than the dark model canvas."""
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            px, py = int(x) + dx, int(y) + dy
            if 0 <= px < img.width() and 0 <= py < img.height():
                c = img.pixelColor(px, py)
                if c.red() > 150 and c.green() < 80 and c.blue() < 80:
                    return True
    return False


def _on_screen(view, base, direction, side, width, height):
    """Where the line from ``base`` along ``direction`` meets the screen's
    left (side=-1) or right (side=+1) margin, in pixels."""
    sx, sy = view.world_to_screen(*base)
    ex, ey = view.world_to_screen(base[0] + direction[0], base[1] + direction[1])
    dx, dy = ex - sx, ey - sy
    target = 6 if side < 0 else width - 7
    t = (target - sx) / dx
    return target, sy + dy * t


@pytest.mark.parametrize("regen", [False, True])
def test_zoomed_out_a_thousand_times_the_lines_still_reach_the_screen_edge(
        qapp, regen):
    from core import actions
    from views.main_window import MainWindow

    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    win.new_document()
    try:
        # red, to find the lines among the pixels
        win.document.doc.layers.get("0").color = 1
        t = win.tools
        t._execute(actions.add_line((0, 0), (100, 50)))
        win._on_command_submitted("XLINE")
        t.on_click(50, 25)
        t.on_click(60, 30)
        win._on_command_submitted("")
        win._on_command_submitted("RAY")
        t.on_click(50, 25)
        t.on_click(40, 30)                    # up and to the left
        win._on_command_submitted("")
        _wait_regen(qapp, win)
        if regen:                             # from the baked scene, too
            win.regen_in_memory()
            _wait_regen(qapp, win)
        win._on_command_submitted("ZOOM")
        win._on_command_submitted("E")
        view = win.viewport.view
        view.scale /= 1000.0
        win.viewport.update()
        qapp.processEvents()
        win.viewport.grabFramebuffer()
        img = win.viewport.grabFramebuffer()
        w, h = img.width(), img.height()
        assert (w, h) == (win.viewport.width(), win.viewport.height())

        xl = (1.0, 0.5)
        ray = (-1.0, 0.5)
        for side in (-1, 1):                  # the XLINE: both edges
            x, y = _on_screen(view, (50, 25), xl, side, w, h)
            assert 0 <= y < h
            assert _lit(img, x, y), f"XLINE missing at the {side} edge"
        x, y = _on_screen(view, (50, 25), ray, -1, w, h)
        assert _lit(img, x, y), "RAY missing at its far edge"
        # ...and a RAY does not go back past its start
        x, y = _on_screen(view, (50, 25), ray, 1, w, h)
        if 0 <= y < h:
            assert not _lit(img, x, y)
        # control: off the line, the canvas is empty
        x, y = _on_screen(view, (50, 25), xl, 1, w, h)
        assert not _lit(img, x, y - 40 if y > 60 else y + 40)
    finally:
        win.document.dirty = False
        win.close()
