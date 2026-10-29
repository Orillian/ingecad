# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""A layout's page-setup scale ("1 mm = 0.001 units": paper space drawn in
metres) sizes the sheet, its margins, the limits and the PLOT.

The sheet was always drawn in millimetres and plotted 1 mm = 1 unit: on such
a layout IngeCAD showed a 420 x 297 sheet with the title block and the
viewports tiny in its corner, and the PDF came out with the drawing as a dot.
AutoCAD draws the sheet at the plot scale (Page Setup > Plot scale,
"mm = units"; DXF groups 72, 142/143, 75 with flag 16 of group 70).
"""
from __future__ import annotations

import time
from pathlib import Path

import ezdxf
import pytest

from core import layouts as layout_ops
from formats import pdf_out

A3 = (420.0, 297.0)
MARGIN = 10.0


def _write_sheet(path: Path, k: float) -> Path:
    """An A3 layout with 10 mm margins at "1 mm = 1/k units", a title-block
    rectangle filling the printable area and one viewport, all drawn in
    paper-space units (k = 1 is the ordinary millimetre sheet)."""
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (50, 0), (50, 30), (0, 30)], close=True)
    psp = doc.layouts.get("Layout1")
    d = psp.dxf_layout.dxf
    d.paper_width, d.paper_height = A3
    d.left_margin = d.right_margin = MARGIN
    d.top_margin = d.bottom_margin = MARGIN
    d.plot_paper_units = 1
    d.plot_rotation = 0
    d.plot_origin_x_offset = d.plot_origin_y_offset = 0.0
    d.scale_numerator = 1.0
    d.scale_denominator = k
    d.standard_scale_type = 16
    d.plot_type = layout_ops.PLOT_TYPE_LAYOUT
    d.plot_layout_flags = int(d.get("plot_layout_flags", 0) or 0) \
        & ~layout_ops.FLAG_USE_STANDARD_SCALE
    # a stand-in for the paper's own viewport first (looking at empty
    # model space), then the floating one
    psp.add_viewport(center=(200 * k, 138.5 * k), size=(420 * k, 297 * k),
                     view_center_point=(-1e6, -1e6), view_height=297 * k)
    psp.add_lwpolyline([(0, 0), (400 * k, 0), (400 * k, 277 * k),
                        (0, 277 * k)], close=True)
    psp.add_viewport(center=(150 * k, 150 * k), size=(250 * k, 180 * k),
                     view_center_point=(25, 15), view_height=36)
    doc.saveas(path)
    return path


def _open_sheet(qapp, path):
    from views.main_window import MainWindow

    win = MainWindow()
    win.maybe_save_changes = lambda: True
    win.open_path(path)
    _settle(qapp, win)
    win.switch_layout("Layout1")
    _settle(qapp, win)
    return win


def _settle(qapp, win):
    t0 = time.monotonic()
    while (win._open_thread is not None or win._regen_worker is not None) \
            and time.monotonic() - t0 < 30:
        qapp.processEvents()
    qapp.processEvents()


def _close(win):
    win.document.dirty = False
    win.close()


def _plot_pdf(win, path):
    """PLOT, What to plot: Layout -- the dialog's own route to the PDF."""
    from views.print_dialog import PrintDialog

    dialog = PrintDialog(win)
    dialog.area.setCurrentIndex(dialog.area.findData("layout"))
    (width, height), _sheet = pdf_out.layout_sheet(win.document, "Layout1")
    dialog._plot_on(pdf_out.make_pdf_printer_mm(str(path), width, height))
    dialog.reject()


def _pdf_page_and_ink(path, px_per_mm=2):
    """(page size in mm, bbox of the dark pixels in mm from the top-left)."""
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument

    pdf = QPdfDocument()
    pdf.load(str(path))
    size = pdf.pagePointSize(0)
    w_mm, h_mm = size.width() / 72 * 25.4, size.height() / 72 * 25.4
    img = pdf.render(0, QSize(round(w_mm * px_per_mm), round(h_mm * px_per_mm)))
    xs, ys = [], []
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 0 and c.lightness() < 128:
                xs.append(x)
                ys.append(y)
    assert xs, "nothing plotted"
    ink = (min(xs) / px_per_mm, min(ys) / px_per_mm,
           (max(xs) + 1) / px_per_mm, (max(ys) + 1) / px_per_mm)
    return (w_mm, h_mm), ink


@pytest.mark.parametrize("k", [0.001, 1.0])
def test_the_sheet_is_drawn_at_the_page_setup_scale(qapp, tmp_path, k):
    # the frame the layout tab draws, as the regen hands it to the viewport
    win = _open_sheet(qapp, _write_sheet(tmp_path / "sheet.dxf", k))
    try:
        paper = win.viewport._scene.paper
        assert paper["sheet"] == pytest.approx(
            (-MARGIN * k, -MARGIN * k, (A3[0] - MARGIN) * k,
             (A3[1] - MARGIN) * k))
        assert paper["printable"] == pytest.approx(
            (0.0, 0.0, 400.0 * k, 277.0 * k), abs=1e-12)
        assert paper["mm_per_unit"] == pytest.approx(1.0 / k)
        # what is drawn on it (title block, viewport frames) is the size of
        # the sheet, not a dot in its corner
        x0, y0, x1, y1 = win.viewport._scene.extents
        assert 400.0 * k * 0.99 <= x1 - x0 <= 420.0 * k * 1.01
        assert 277.0 * k * 0.99 <= y1 - y0 <= 297.0 * k * 1.01
    finally:
        _close(win)


@pytest.mark.parametrize("k", [0.001, 1.0])
def test_plot_layout_comes_out_at_true_paper_size(qapp, tmp_path, k):
    win = _open_sheet(qapp, _write_sheet(tmp_path / "sheet.dxf", k))
    try:
        pdf = tmp_path / "sheet.pdf"
        _plot_pdf(win, pdf)
    finally:
        _close(win)
    (w_mm, h_mm), (ix0, iy0, ix1, iy1) = _pdf_page_and_ink(pdf)
    assert (w_mm, h_mm) == pytest.approx(A3, abs=0.5)
    # the title block, 400 x 277 mm, 10 mm in from every edge of the A3
    assert (ix0, iy0) == pytest.approx((MARGIN, MARGIN), abs=1.0)
    assert (ix1, iy1) == pytest.approx((410.0, 287.0), abs=1.0)


def test_the_page_setup_dialog_reads_the_scaled_sheet_in_mm(qapp, tmp_path):
    from views.page_setup_dialog import PageSetupDialog

    win = _open_sheet(qapp, _write_sheet(tmp_path / "sheet.dxf", 0.001))
    try:
        layout = win.document.doc.layouts.get("Layout1")
        page = layout_ops.effective_page(layout)
        assert (page["width"], page["height"]) == pytest.approx(A3)
        assert page["margins"] == pytest.approx((MARGIN,) * 4)
        dialog = PageSetupDialog(win, layout)
        assert dialog.paper.currentData()[0] == "ISO A3"
        assert dialog.margin_top.value() == pytest.approx(MARGIN)
        values = dialog.values()
        dialog.reject()
        assert values["scale"] == pytest.approx((1.0, 0.001))
        # OK with nothing changed keeps the sheet where it was
        win.history.execute(layout_ops.page_setup_command(layout, **values))
        assert layout_ops.paper_frame(layout)["sheet"] == pytest.approx(
            (-0.01, -0.01, 0.41, 0.287))
        assert tuple(layout.dxf.limmin)[:2] == pytest.approx((-0.01, -0.01))
        assert tuple(layout.dxf.limmax)[:2] == pytest.approx((0.41, 0.287))
    finally:
        _close(win)


def test_the_plot_dialog_reads_a_metre_sheet_as_metres(qapp, tmp_path):
    # Extents / Window on such a tab: one unit is a metre of paper
    from core.i18n import tr
    from views.print_dialog import PrintDialog

    win = _open_sheet(qapp, _write_sheet(tmp_path / "sheet.dxf", 0.001))
    try:
        dialog = PrintDialog(win)
        assert dialog.units.currentText() == tr("Meters")
        assert dialog.scale.currentText() == "1:1"
        assert dialog._mm_per_unit() == pytest.approx(1000.0)
        dialog.reject()
    finally:
        _close(win)


def test_paper_mm_per_unit_reads_every_way_a_scale_is_stored():
    doc = ezdxf.new("R2010")
    layout = doc.layouts.get("Layout1").dxf_layout
    dxf = layout.dxf
    dxf.plot_paper_units = 1
    dxf.plot_layout_flags = 0
    dxf.scale_numerator, dxf.scale_denominator = 1.0, 1.0
    assert layout_ops.paper_mm_per_unit(layout) == 1.0        # default 1:1
    dxf.scale_denominator = 0.001
    assert layout_ops.paper_mm_per_unit(layout) == pytest.approx(1000.0)
    # standard scale (flag 16): code 75 wins, 26 = 1:100
    dxf.plot_layout_flags = layout_ops.FLAG_USE_STANDARD_SCALE
    dxf.standard_scale_type = 26
    assert layout_ops.paper_mm_per_unit(layout) == pytest.approx(0.01)
    # scaled to fit: no sheet scale, as today
    dxf.standard_scale_type = 0
    assert layout_ops.paper_mm_per_unit(layout) == 1.0
    # inches: 1" = 1 unit is 25.4 mm per unit
    dxf.plot_layout_flags = 0
    dxf.plot_paper_units = 0
    dxf.scale_denominator = 1.0
    assert layout_ops.paper_mm_per_unit(layout) == pytest.approx(25.4)
    # garbage keeps 1:1 instead of a zero-size sheet
    dxf.plot_paper_units = 1
    dxf.scale_denominator = 0.0
    assert layout_ops.paper_mm_per_unit(layout) == 1.0
