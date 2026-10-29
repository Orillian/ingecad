# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The extension center: the extension manager window's contents.

Ported from IngeTrazo's extension manager (same author): tiles in a grid,
as many columns as the window's width holds, each with a screenshot of the
plugin at work. Three sections: *Included* (the ones that ship with
IngeCAD), *Installed* (the user's own, from the catalog or copied by hand)
and *Available* (what the catalog offers and is not here yet). A card says
who made it, which version, what it does and whether someone reviewed that
exact version, and carries the buttons that apply: Install, Update,
Enable/Disable, Uninstall. Turning one on or off takes effect at once
(core/plugins.py); installing one turns it on.

The pictures: a plugin's own ``screenshot.jpg`` beside its ``__init__.py``
(core.plugins.SCREENSHOT_FILES; the included ones ship theirs), else the
catalog entry's ``screenshot``, downloaded beside the catalog the first
time its card is on screen and kept for the next time there is no network.
No picture -- or one that does not decode -- leaves the placeholder.

The network: the catalog and a download run on one worker thread at a
time (core.gc_guard); a screenshot is a QNetworkAccessManager reply, on
the GUI thread. Without network the installed and included plugins are
still listed and managed.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from PySide6.QtCore import (QCoreApplication, QEvent, QPoint, QSettings, Qt,
                            QThread, QTimer, QUrl, Signal)
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtNetwork import (QNetworkAccessManager, QNetworkReply,
                               QNetworkRequest)
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)

from core import extension_center as center
from core import i18n
from core.i18n import tr

log = logging.getLogger("ingecad.extensions")

#: The chip on each card. "badge|...": one plugin is "Incluida" where the
#: section of them is "Incluidas" (tr_context).
_BADGES = {
    "included": ("badge|Included", "#5b7a99"),
    "reviewed": ("badge|Reviewed", "#479B1B"),
    "community": ("badge|Community", "#b86e00"),
    "hand": ("badge|Installed by you", "#6c6c6c"),
}

_IMAGE_SIZE = (240, 150)            # 16:10, as the catalog screenshots
#: The width one column of cards asks for: one column in a narrow window,
#: two at the usual size, three on a maximised Full HD one.
_COLUMN_WIDTH = 540
_CARD_MIN_WIDTH = 440
_CARD_MAX_WIDTH = 680
_SEARCH_DELAY_MS = 180
#: A screenshot that failed is asked for again on its own, a little later
#: each time, while the tries last.
_SCREENSHOT_RETRIES = 3
_SCREENSHOT_RETRY_MS = 2000
#: Once the visible cards have their pictures, the rest already on disk
#: are scaled a few at a time, so scrolling finds them ready.
_PREFETCH_DELAY_MS = 150
_PREFETCH_BATCH = 4
_THUMBS_DIR = "thumbs"

#: The scaled card pictures while IngeCAD runs, by source file, its mtime
#: and size, and the size in device pixels: the window rebuilds its cards
#: on every change and must not decode a screenshot again each time.
#: Images, not pixmaps: they outlive the window.
_SCALED: dict[tuple, QImage] = {}

#: Everything a card wears, set once on the card area (not one style sheet
#: per widget: that is what made IngeTrazo's manager slow on Windows).
_CARD = 'QFrame[extCard="true"]'
_CARD_RULES = {
    "": "background: palette(base); border: 1px solid palette(midlight); "
        "border-radius: 4px;",
    " QLabel": "background: transparent; border: none; color: palette(text);",
    " QLabel#ext_image": "background: palette(alternate-base); "
                         "color: palette(text); border: none;",
    " QLabel#ext_title": "font-weight: bold; font-size: 15px;",
    " QLabel#ext_byline": "color: palette(text);",
    " QLabel#ext_license": "font-weight: bold;",
    " QLabel#ext_versions": "font-size: 10px; font-weight: bold;",
    " QLabel#ext_tags": "color: palette(link); font-size: 11px;",
    " QLabel#ext_note": "color: palette(mid);",
    ' QLabel[badge="included"]': f"background: {_BADGES['included'][1]};",
    ' QLabel[badge="reviewed"]': f"background: {_BADGES['reviewed'][1]};",
    ' QLabel[badge="community"]': f"background: {_BADGES['community'][1]};",
    ' QLabel[badge="hand"]': f"background: {_BADGES['hand'][1]};",
    " QLabel[badge]": "color: white; border-radius: 3px; padding: 1px 5px; "
                      "font-size: 10px; font-weight: bold;",
}
_CARD_STYLE = "".join(f"{_CARD}{selector} {{ {rule} }}"
                      for selector, rule in _CARD_RULES.items())
_SECTION_STYLE = "QLabel#ext_section { font-weight: bold; font-size: 16px; }"


class _Worker(QThread):
    """One catalog fetch or one install, off the GUI thread."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, name: str, job, *args) -> None:
        super().__init__()
        self.setObjectName(f"extensions-{name}")
        self._job = job
        self._args = args

    def run(self) -> None:
        from core import gc_guard

        with gc_guard.paused():
            try:
                result = self._job(*self._args)
            except center.ExtensionError as exc:
                self.failed.emit(str(exc))
            except Exception as exc:          # noqa: BLE001 -- shown, never fatal
                self.failed.emit(f"{type(exc).__name__}: {exc}")
            else:
                self.done.emit(result)


def _source_key(source: Path, size: tuple) -> tuple | None:
    try:
        stat = source.stat()
    except OSError:
        return None
    return (str(source), stat.st_mtime_ns, stat.st_size, *size)


def _fit(image: QImage, width: int, height: int) -> QImage:
    """``image`` filling ``width`` x ``height``, the overflow cut evenly."""
    scaled = image.scaled(width, height, Qt.KeepAspectRatioByExpanding,
                          Qt.SmoothTransformation)
    return scaled.copy((scaled.width() - width) // 2,
                       (scaled.height() - height) // 2, width, height)


class ExtensionsPanel(QWidget):
    def __init__(self, window, parent=None) -> None:
        super().__init__(parent if parent is not None else window)
        self.window = window
        self.manager = window.plugins
        self.snapshot: center.CatalogSnapshot | None = None
        self.catalog_error = ""
        self.message = ""
        self._worker: _Worker | None = None
        self._job = None
        self._asked = False
        self._closing = False
        self._tag = ""
        self._columns_now = 0
        # the cards of each section, in order (re-flowed on resize)
        self._sections: list[tuple[QGridLayout, list[QFrame]]] = []
        # plugin id -> (picture label, local file or catalog entry)
        self._image_labels: dict[str, tuple[QLabel, object]] = {}
        self._unreadable: set[str] = set()
        self._requested: set[str] = set()
        self._failures: dict[str, int] = {}
        self._pending: dict[QNetworkReply, tuple[str, Path]] = {}
        self._network = QNetworkAccessManager(self)
        self._network.finished.connect(self._screenshot_finished)
        self._images_timer = QTimer(self)
        self._images_timer.setSingleShot(True)
        self._images_timer.setInterval(0)
        self._images_timer.timeout.connect(self._load_visible_images)
        self._prefetch_timer = QTimer(self)
        self._prefetch_timer.setSingleShot(True)
        self._prefetch_timer.setInterval(_PREFETCH_DELAY_MS)
        self._prefetch_timer.timeout.connect(self._prefetch_images)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self.refresh)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        header = QHBoxLayout()
        heading = QLabel(tr("Extensions"), self)
        heading.setStyleSheet("QLabel { font-size: 22px; font-weight: bold; }")
        header.addWidget(heading)
        header.addStretch(1)
        self.status = QLabel(self)
        self.status.setObjectName("ext_status")
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        header.addWidget(self.status, 1)
        self.refresh_btn = QPushButton(tr("Refresh"), self)
        self.refresh_btn.setObjectName("ext_refresh")
        self.refresh_btn.setToolTip(tr("Download the catalog again"))
        self.refresh_btn.clicked.connect(self.fetch_catalog)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        filters = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setObjectName("ext_search")
        self.search.setPlaceholderText(tr("Search extensions..."))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._search_changed)
        filters.addWidget(self.search, 1)
        self.count = QLabel(self)
        self.count.setObjectName("ext_count")
        filters.addWidget(self.count)
        layout.addLayout(filters)

        tags_scroll = QScrollArea(self)
        tags_scroll.setFrameShape(QFrame.NoFrame)
        tags_scroll.setWidgetResizable(True)
        tags_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tags_scroll.setFixedHeight(36)
        tags_content = QWidget(tags_scroll)
        self._tags_layout = QHBoxLayout(tags_content)
        self._tags_layout.setContentsMargins(1, 2, 1, 2)
        self._tags_layout.setSpacing(6)
        self._tags_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._tags_group = QButtonGroup(self)
        self._tags_group.setExclusive(True)
        tags_scroll.setWidget(tags_content)
        layout.addWidget(tags_scroll)

        self._scroll = scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.verticalScrollBar().valueChanged.connect(self._images_timer.start)
        scroll.viewport().installEventFilter(self)     # columns follow width
        self._body = QWidget(scroll)
        self._body.setStyleSheet(_CARD_STYLE + _SECTION_STYLE)
        self._cards = QVBoxLayout(self._body)
        self._cards.setContentsMargins(2, 2, 2, 12)
        self._cards.setSpacing(8)
        scroll.setWidget(self._body)
        layout.addWidget(scroll, 1)

        footer = QHBoxLayout()
        warning = QLabel(tr(
            "Extensions are Python code: they run with the same access as "
            "IngeCAD to your files and your network. Install only what you "
            "trust. Reviewed means someone read that exact version."), self)
        warning.setObjectName("ext_warning")
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "QLabel { background: rgba(184, 110, 0, 40); border: 1px solid "
            "#b86e00; border-radius: 4px; padding: 4px; }")
        footer.addWidget(warning, 1)
        close = QPushButton(tr("Close"), self)
        close.setObjectName("ext_close")
        close.clicked.connect(self._close_window)
        footer.addWidget(close, 0, Qt.AlignBottom)
        layout.addLayout(footer)
        self.refresh()

    # -- what there is --------------------------------------------------------------
    def _catalog(self) -> dict:
        if self.snapshot is None:
            return {}
        return {e.id: e for e in self.snapshot.extensions}

    def _reviewed(self, extension) -> bool:
        return (self.snapshot is not None
                and center.is_reviewed(extension, self.snapshot.reviewed))

    def ensure_catalog(self) -> None:
        """The first time the window is opened, ask for the catalog."""
        if not self._asked:
            self.fetch_catalog()

    def busy(self) -> bool:
        return self._worker is not None

    def _close_window(self, *_args) -> None:
        QWidget.window(self).close()

    # -- the worker ----------------------------------------------------------------
    def _start(self, name: str, job, *args, what=None) -> bool:
        if self._worker is not None:
            return False
        from core import gc_guard

        worker = _Worker(name, job, *args)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        self._worker, self._job = worker, what or (name,)
        self.refresh()
        gc_guard.start(worker)
        return True

    def _finish(self):
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.wait()
        job, self._job = self._job, None
        return job

    def fetch_catalog(self) -> None:
        self._asked = True
        self.catalog_error = ""
        self._start("catalog", center.refresh_catalog, self.manager.user_dir)

    def _on_done(self, result) -> None:
        job = self._finish()
        if job is None:
            return
        if job[0] == "catalog":
            self.snapshot = result
        elif job[0] == "install":
            self._installed(job[1], job[2])
        self.refresh()

    def _on_failed(self, message: str) -> None:
        job = self._finish()
        if job is None:
            return
        if job[0] == "catalog":
            self.catalog_error = message
        else:
            self._say(tr("Could not install {name}: {reason}",
                         name=job[1].id, reason=message))
        self.refresh()

    def wait(self) -> None:
        """Let the running job end and its answer arrive (tests, scripts)."""
        worker = self._worker
        if worker is not None:
            worker.wait()
            QCoreApplication.sendPostedEvents(self)

    def shutdown(self) -> None:
        """The window is closing: join the worker, drop its answer, and
        abandon the screenshots still on their way."""
        self._closing = True
        for timer in (self._images_timer, self._prefetch_timer,
                      self._search_timer):
            timer.stop()
        for reply in list(self._pending):
            reply.abort()
        self._pending.clear()
        worker, self._worker = self._worker, None
        if worker is not None:
            for signal, slot in ((worker.done, self._on_done),
                                 (worker.failed, self._on_failed)):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            worker.wait()
        self._job = None

    # -- actions -------------------------------------------------------------------
    def confirm(self, title: str, text: str) -> bool:
        """A yes/no question (a seam the tests replace)."""
        answer = QMessageBox.question(self, title, text,
                                      QMessageBox.Yes | QMessageBox.No,
                                      QMessageBox.No)
        return answer == QMessageBox.Yes

    def _say(self, text: str) -> None:
        self.message = text
        echo = getattr(self.window, "command_line", None)
        if echo is not None:
            echo.echo(text)

    def install(self, extension) -> bool:
        """Install or update ``extension`` from the catalog (in the worker)."""
        name = center.display_name(extension, i18n.current_language())
        if not self._reviewed(extension) and not self.confirm(
                tr("Install extension"),
                tr("{name} has not been reviewed. It is Python code that "
                   "runs with the same access as IngeCAD. Install it "
                   "anyway?", name=name)):
            return False
        update = center.is_managed(extension.id, self.manager.user_dir)
        return self._start("install", center.install_extension, extension,
                           self.manager.user_dir,
                           what=("install", extension, update))

    def _installed(self, extension, update: bool) -> None:
        """On the GUI thread, after the files are in place: load it, and
        switch a new one on (it was installed to be used)."""
        loaded = self.manager.reload(extension.id)
        name = center.display_name(extension, i18n.current_language())
        if loaded is None or not loaded.available:
            reason = loaded.reason if loaded is not None else ""
            self._say(tr("{name} was installed but cannot run: {reason}",
                         name=name, reason=reason))
            return
        if not update:
            self.manager.set_enabled(extension.id, True)
        self._say(tr("{name} {version} updated.", name=name,
                     version=extension.version) if update else
                  tr("{name} {version} installed.", name=name,
                     version=extension.version))

    def uninstall(self, plugin_id: str) -> bool:
        name = self._name(plugin_id)
        if not self.confirm(tr("Uninstall extension"),
                            tr("Uninstall {name}? Its files are deleted.",
                               name=name)):
            return False
        self.manager.forget(plugin_id)
        try:
            center.uninstall_extension(plugin_id, self.manager.user_dir)
        except (center.ExtensionError, OSError) as exc:
            self._say(tr("Could not uninstall {name}: {reason}",
                         name=name, reason=str(exc)))
            self.manager.reload(plugin_id)
            self.refresh()
            return False
        settings = QSettings()
        for key in (self.manager.SETTING, self.manager.TOOLBAR_SETTING):
            settings.remove(key.format(id=plugin_id))
        self._say(tr("{name} uninstalled.", name=name))
        self.refresh()
        return True

    def set_enabled(self, plugin_id: str, flag: bool) -> None:
        self.manager.set_enabled(plugin_id, flag)
        self.refresh()

    def _toolbar_toggled(self, plugin_id: str, flag: bool) -> None:
        self.manager.set_toolbar_enabled(plugin_id, flag)

    # -- filters -------------------------------------------------------------------
    def _search_changed(self, _text: str) -> None:
        self._search_timer.start()

    def select_tag(self, tag: str) -> None:
        """Show only the catalog's extensions with ``tag`` ("" = all)."""
        self._tag = tag
        self.refresh()

    def _populate_tags(self, catalog: dict) -> None:
        layout = self._tags_layout
        while layout.count():
            widget = layout.takeAt(0).widget()
            if widget is not None:
                self._tags_group.removeButton(widget)
                widget.hide()
                widget.deleteLater()
        used = {t for e in catalog.values() for t in e.tags}
        tags = [t for t in center.TAGS if t in used]
        if self._tag and self._tag not in tags:
            self._tag = ""
        for tag in [""] + tags:
            button = QToolButton(layout.parentWidget())
            button.setObjectName(f"ext_tag_{tag or 'all'}")
            button.setText(tr(center.TAGS[tag]) if tag else tr("All"))
            button.setCheckable(True)
            button.setChecked(tag == self._tag)
            button.setFocusPolicy(Qt.NoFocus)
            button.setStyleSheet(
                "QToolButton { background: palette(base); color: palette(text);"
                " border: 1px solid palette(midlight); border-radius: 11px;"
                " padding: 3px 10px; }"
                "QToolButton:checked { background: palette(highlight); "
                "color: palette(highlighted-text); "
                "border-color: palette(highlight); }")
            button.clicked.connect(
                lambda _checked=False, t=tag: self.select_tag(t))
            self._tags_group.addButton(button)
            layout.addWidget(button)

    def _matches(self, *texts) -> bool:
        query = self.search.text().strip().casefold()
        return not query or query in " ".join(t for t in texts if t).casefold()

    # -- the cards -----------------------------------------------------------------
    def _name(self, plugin_id: str) -> str:
        loaded = self.manager.loaded.get(plugin_id)
        if loaded is not None and loaded.spec is not None:
            return tr(loaded.spec.name)
        entry = self._catalog().get(plugin_id)
        if entry is not None:
            return center.display_name(entry, i18n.current_language())
        return plugin_id

    def _plugin_texts(self, plugin_id: str, entry) -> tuple:
        loaded = self.manager.loaded[plugin_id]
        spec = loaded.spec
        texts = [plugin_id, self._name(plugin_id)]
        if spec is not None:
            texts += [spec.name, tr(spec.description) if spec.description else ""]
        if entry is not None:
            texts += [entry.author, *entry.name.values(), *entry.summary.values(),
                      *(tr(center.TAGS[t]) for t in entry.tags if t in center.TAGS)]
        return tuple(texts)

    @staticmethod
    def _entry_texts(entry) -> tuple:
        return (entry.id, entry.author, *entry.name.values(),
                *entry.summary.values(),
                *(tr(center.TAGS[t]) for t in entry.tags if t in center.TAGS))

    def columns(self) -> int:
        """How many columns of cards the window's width holds now."""
        return max(1, self._scroll.viewport().width() // _COLUMN_WIDTH)

    def refresh(self, *_args) -> None:
        """Rebuild the cards from what is on disk and in the catalog."""
        if self._closing:
            return
        self._body.setUpdatesEnabled(False)
        try:
            self._rebuild()
        finally:
            self._body.setUpdatesEnabled(True)
        self._images_timer.start()

    def _rebuild(self) -> None:
        while self._cards.count():
            item = self._cards.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # out of the layout is not off the screen: hide it at once
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._sections = []
        self._image_labels = {}
        self._status_text()
        self.refresh_btn.setEnabled(not self.busy())
        catalog = self._catalog()
        self._populate_tags(catalog)
        loaded = self.manager.loaded
        included = sorted(pid for pid, p in loaded.items() if p.bundled)
        installed = sorted(pid for pid, p in loaded.items() if not p.bundled)
        tag = self._tag
        offered = [e for e in sorted(catalog.values(), key=lambda e: e.id)
                   if e.id not in loaded]
        available = [e for e in offered
                     if (not tag or tag in e.tags) and self._matches(*self._entry_texts(e))]
        shown_included = [p for p in included
                          if self._matches(*self._plugin_texts(p, catalog.get(p)))]
        shown_installed = [p for p in installed
                           if self._matches(*self._plugin_texts(p, catalog.get(p)))]
        columns = self._columns_now = self.columns()

        self._section(tr("Included"), "included",
                      [self._plugin_card(pid, catalog.get(pid)) for pid in shown_included],
                      columns)
        if not shown_included:
            self._note(tr("No extension matches the search."))
        self._section(tr("Installed"), "installed",
                      [self._plugin_card(pid, catalog.get(pid)) for pid in shown_installed],
                      columns)
        if not installed:
            self._note(tr("No extensions installed yet."))
        elif not shown_installed:
            self._note(tr("No extension matches the search."))
        self._section(tr("Available"), "available",
                      [self._catalog_card(entry) for entry in available], columns)
        if not available:
            self._note(tr("The catalog is not loaded.") if self.snapshot is None
                       else tr("Nothing more to install.") if not offered
                       else tr("No extension matches the search."))
        self._cards.addStretch(1)
        total = len(included) + len(installed) + len(offered)
        shown = len(shown_included) + len(shown_installed) + len(available)
        self.count.setText(tr("{shown} of {total} extensions",
                              shown=shown, total=total))

    def _status_text(self) -> None:
        if self.busy() and self._job and self._job[0] == "install":
            text = tr("Installing {name}...", name=self._job[1].id)
        elif self.busy():
            text = tr("Loading the catalog...")
        elif self.catalog_error:
            text = tr("Catalog unavailable: {reason}", reason=self.catalog_error)
        elif self.snapshot is None:
            text = ""
        elif self.snapshot.from_cache:
            text = tr("Offline: catalog saved on {date}.",
                      date=self.snapshot.fetched_at[:10])
        else:
            text = tr("{n} extension(s) in the catalog.",
                      n=len(self.snapshot.extensions))
        self.status.setText(text)

    def _section(self, title: str, key: str, cards: list, columns: int) -> None:
        label = QLabel(title, self._body)
        label.setObjectName("ext_section")
        label.setProperty("section", key)
        label.setContentsMargins(0, 8, 0, 0)
        self._cards.addWidget(label)
        if not cards:
            return
        holder = QWidget(self._body)
        holder.setObjectName(f"ext_grid_{key}")
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(14)
        grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._sections.append((grid, cards))
        self._place(grid, cards, columns)
        self._cards.addWidget(holder)

    @staticmethod
    def _place(grid: QGridLayout, cards: list, columns: int) -> None:
        """The cards in as many columns as fit, in order."""
        for card in cards:
            grid.removeWidget(card)
        for column in range(max(columns, grid.columnCount())):
            grid.setColumnStretch(column, 1 if column < columns else 0)
        for index, card in enumerate(cards):
            grid.addWidget(card, index // columns, index % columns)

    def eventFilter(self, obj, event) -> bool:
        # A wider or narrower window: the same cards, in the columns that
        # fit now -- moved, not rebuilt (their pictures stay).
        scroll = getattr(self, "_scroll", None)
        if (event.type() == QEvent.Resize and scroll is not None
                and obj is scroll.viewport()):
            columns = self.columns()
            if columns != self._columns_now:
                self._columns_now = columns
                for grid, cards in self._sections:
                    self._place(grid, cards, columns)
            self._images_timer.start()
        return super().eventFilter(obj, event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._images_timer.start()

    def _note(self, text: str) -> None:
        label = QLabel(text, self._body)
        label.setWordWrap(True)
        label.setEnabled(False)
        self._cards.addWidget(label)

    def _frame(self, plugin_id: str, title: str, version: str, author: str,
               summary: str, badge: str, tags=(), licence: str = "",
               picture=None) -> tuple[QFrame, QVBoxLayout]:
        """A tile: the picture, who and the licence on the left; version,
        badge, name and what it does on the right, the buttons below
        (added by the caller to the returned column)."""
        frame = QFrame(self._body)
        frame.setObjectName(f"ext_card_{plugin_id}")
        frame.setProperty("extCard", True)
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        frame.setMinimumWidth(_CARD_MIN_WIDTH)
        frame.setMaximumWidth(_CARD_MAX_WIDTH)
        content = QHBoxLayout(frame)
        content.setContentsMargins(10, 10, 10, 8)
        content.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(5)
        image = QLabel(tr("Preview unavailable"), frame)
        image.setObjectName("ext_image")
        image.setProperty("plugin", plugin_id)
        image.setAlignment(Qt.AlignCenter)
        image.setWordWrap(True)
        image.setFixedSize(*_IMAGE_SIZE)
        left.addWidget(image, 0, Qt.AlignTop)
        if picture is not None:
            self._image_labels[plugin_id] = (image, picture)
            pixmap = self._remembered(picture)
            if pixmap is not None:
                image.setPixmap(pixmap)
        if author:
            by = QLabel(tr("by {author}", author=author), frame)
            by.setObjectName("ext_byline")
            by.setWordWrap(True)
            by.setMaximumWidth(_IMAGE_SIZE[0])
            left.addWidget(by)
        if tags:
            cats = QLabel(" · ".join(tr(center.TAGS[t]) for t in tags
                                     if t in center.TAGS), frame)
            cats.setObjectName("ext_tags")
            cats.setWordWrap(True)
            cats.setMaximumWidth(_IMAGE_SIZE[0])
            left.addWidget(cats)
        if licence:
            lic = QLabel(licence, frame)
            lic.setObjectName("ext_license")
            lic.setWordWrap(True)
            lic.setMaximumWidth(_IMAGE_SIZE[0])
            left.addWidget(lic)
        left.addStretch(1)
        content.addLayout(left)

        box = QVBoxLayout()
        box.setSpacing(4)
        top = QHBoxLayout()
        top.addStretch(1)
        if version:
            versions = QLabel(f"v{version}", frame)
            versions.setObjectName("ext_versions")
            top.addWidget(versions, 0, Qt.AlignVCenter)
        text, _colour = _BADGES[badge]
        chip = QLabel(i18n.tr_context(text), frame)
        chip.setObjectName(f"ext_badge_{plugin_id}")
        chip.setProperty("badge", badge)
        top.addWidget(chip, 0, Qt.AlignVCenter)
        box.addLayout(top)
        name = QLabel(title, frame)
        name.setObjectName("ext_title")
        name.setWordWrap(True)
        box.addWidget(name)
        if summary:
            about = QLabel(summary, frame)
            about.setObjectName("ext_summary")
            about.setWordWrap(True)
            about.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            box.addWidget(about)
        content.addLayout(box, 1)
        return frame, box

    @staticmethod
    def _plain(frame: QFrame) -> QFrame:
        # Names, summaries and authors come from the catalog: as rich text,
        # "<b>Reviewed</b>" in a summary would pass for the real badge.
        for label in frame.findChildren(QLabel):
            label.setTextFormat(Qt.PlainText)
        return frame

    def _button(self, frame: QFrame, row: QHBoxLayout, name: str, label: str,
                plugin_id: str, slot, enabled: bool = True) -> QPushButton:
        button = QPushButton(label, frame)
        button.setObjectName(f"ext_{name}_{plugin_id}")
        button.setFocusPolicy(Qt.NoFocus)
        button.setEnabled(enabled and not self.busy())
        button.clicked.connect(slot)
        row.addWidget(button)
        return button

    def _picture(self, plugin_id: str, entry):
        """What the card shows: the plugin's own file, else the catalog's."""
        loaded = self.manager.loaded.get(plugin_id)
        local = loaded.screenshot if loaded is not None else None
        if local is not None:
            return local
        if entry is not None and center.screenshot_cache(
                entry, self.manager.user_dir) is not None:
            return entry
        return None

    def _plugin_card(self, plugin_id: str, entry) -> QFrame:
        loaded = self.manager.loaded[plugin_id]
        spec = loaded.spec
        language = i18n.current_language()
        managed = (not loaded.bundled
                   and center.is_managed(plugin_id, self.manager.user_dir))
        info = center.installed_info(plugin_id, self.manager.user_dir) if managed else None
        if loaded.bundled:
            badge, author, licence = "included", "IngeCAD", tr("Included with IngeCAD")
        elif not managed:
            badge, author, licence = "hand", "", ""
        else:
            badge = "reviewed" if entry is not None and self._reviewed(entry) else "community"
            author = entry.author if entry is not None else ""
            licence = (tr("License: {license}", license=entry.license)
                       if entry is not None else "")
        version = (spec.version if spec is not None
                   else (info or {}).get("version", ""))
        summary = (center.display_summary(entry, language) if entry is not None
                   else (tr(spec.description) if spec is not None and spec.description
                         else ""))
        frame, box = self._frame(plugin_id, self._name(plugin_id), version,
                                 author, summary, badge,
                                 entry.tags if entry is not None else (),
                                 licence, self._picture(plugin_id, entry))
        if not loaded.available:
            self._note_in(frame, box, tr("unavailable: {reason}", reason=loaded.reason))
        if not managed and not loaded.bundled:
            self._note_in(frame, box, tr("Location: {path}", path=str(loaded.location)))
        active = self.manager.is_active(plugin_id)
        if active and self.manager.has_toolbar(plugin_id):
            check = QCheckBox(tr("Show this plugin's toolbar"), frame)
            check.setObjectName(f"ext_toolbar_{plugin_id}")
            check.setToolTip(check.text())
            check.setChecked(self.manager.toolbar_enabled(plugin_id))
            check.toggled.connect(
                lambda on, p=plugin_id: self._toolbar_toggled(p, on))
            box.addWidget(check)
        box.addStretch(1)
        if managed and entry is not None and center.update_available(
                entry, self.manager.user_dir):
            update = QHBoxLayout()
            self._button(frame, update, "update",
                         tr("Update to {version}", version=entry.version),
                         plugin_id, lambda _=False, e=entry: self.install(e),
                         enabled=center.compatible(entry))
            update.addStretch(1)
            box.addLayout(update)
        row = QHBoxLayout()
        self._button(frame, row, "toggle", tr("Disable") if active else tr("Enable"),
                     plugin_id,
                     lambda _=False, p=plugin_id, on=not active: self.set_enabled(p, on),
                     enabled=loaded.available or active)
        if managed:
            self._button(frame, row, "uninstall", tr("Uninstall"), plugin_id,
                         lambda _=False, p=plugin_id: self.uninstall(p))
        row.addStretch(1)
        box.addLayout(row)
        return self._plain(frame)

    def _catalog_card(self, entry) -> QFrame:
        language = i18n.current_language()
        frame, box = self._frame(
            entry.id, center.display_name(entry, language), entry.version,
            entry.author, center.display_summary(entry, language),
            "reviewed" if self._reviewed(entry) else "community", entry.tags,
            tr("License: {license}", license=entry.license),
            self._picture(entry.id, entry))
        ok = center.compatible(entry)
        if not ok:
            self._note_in(frame, box, tr("Requires IngeCAD {version} or later.",
                                         version=entry.minimum_version))
        box.addStretch(1)
        row = QHBoxLayout()
        self._button(frame, row, "install", tr("Install"), entry.id,
                     lambda _=False, e=entry: self.install(e), enabled=ok)
        row.addStretch(1)
        box.addLayout(row)
        return self._plain(frame)

    def _note_in(self, frame: QFrame, box: QVBoxLayout, text: str) -> None:
        label = QLabel(text, frame)
        label.setObjectName("ext_note")
        label.setWordWrap(True)
        box.addWidget(label)

    # -- the pictures --------------------------------------------------------------
    def _source(self, picture) -> Path | None:
        """The file on disk ``picture`` reads from (it may not exist yet)."""
        if isinstance(picture, Path):
            return picture
        return center.screenshot_cache(picture, self.manager.user_dir)

    def _device_size(self) -> tuple[int, int, float]:
        ratio = max(1.0, self.devicePixelRatioF())
        return (round(_IMAGE_SIZE[0] * ratio), round(_IMAGE_SIZE[1] * ratio), ratio)

    def _remembered(self, picture) -> QPixmap | None:
        """The card picture scaled earlier in this run, if its file has not
        changed since: a rebuilt card is born with it."""
        source = self._source(picture)
        width, height, ratio = self._device_size()
        key = _source_key(source, (width, height)) if source is not None else None
        image = _SCALED.get(key) if key is not None else None
        if image is None:
            return None
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(ratio)
        return pixmap

    def _thumb_path(self, source: Path, width: int, height: int) -> Path:
        name = hashlib.sha1(f"{source}|{width}x{height}".encode()).hexdigest()[:16]
        return center.screenshots_dir(self.manager.user_dir) / _THUMBS_DIR / f"{name}.png"

    def _scaled(self, source: Path, data: bytes | None = None) -> QImage | None:
        """``source`` at card size: from memory, from its thumbnail on disk
        (downloaded screenshots only), or decoded and scaled now."""
        width, height, _ratio = self._device_size()
        key = _source_key(source, (width, height))
        if key is None:
            return None
        image = _SCALED.get(key)
        if image is not None:
            return image
        downloaded = source.parent == center.screenshots_dir(self.manager.user_dir)
        thumb = self._thumb_path(source, width, height) if downloaded else None
        image = QImage()
        try:
            fresh = thumb is not None and thumb.stat().st_mtime_ns >= key[1]
        except OSError:
            fresh = False
        if not (fresh and image.load(str(thumb)) and not image.isNull()):
            full = QImage()
            try:
                if data is None:
                    if source.stat().st_size > center.MAX_SCREENSHOT_BYTES:
                        return None
                    data = source.read_bytes()
            except OSError:
                return None
            if not full.loadFromData(data) or full.isNull():
                return None
            image = _fit(full, width, height)
            if thumb is not None:
                try:
                    thumb.parent.mkdir(parents=True, exist_ok=True)
                    temporary = thumb.with_suffix(".part")
                    if image.save(str(temporary), "PNG"):
                        temporary.replace(thumb)
                except OSError:
                    log.warning("could not cache the thumbnail %s", thumb,
                                exc_info=True)
        _SCALED[key] = image
        return image

    def _set_picture(self, plugin_id: str, source: Path,
                     data: bytes | None = None) -> bool:
        image = self._scaled(source, data)
        if image is None:
            self._unreadable.add(str(source))
            return False
        entry = self._image_labels.get(plugin_id)
        if entry is not None:
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(self._device_size()[2])
            entry[0].setPixmap(pixmap)
        return True

    def _load_visible_images(self, *_args) -> None:
        """Pictures for the cards on screen: from disk when they are there,
        else asked for (a catalog screenshot not downloaded yet)."""
        if self._closing or not self._scroll.isVisible():
            return     # showEvent asks again once there is a screen to fill
        self._body.layout().activate()
        viewport = self._scroll.viewport()
        visible = viewport.rect()
        for plugin_id, (label, picture) in list(self._image_labels.items()):
            if label.pixmap() is not None and not label.pixmap().isNull():
                continue
            rect = label.geometry()
            rect.moveTopLeft(label.mapTo(viewport, QPoint(0, 0)))
            if not visible.intersects(rect):
                continue
            source = self._source(picture)
            if source is None or str(source) in self._unreadable:
                continue
            if source.is_file():
                self._set_picture(plugin_id, source)
            elif not isinstance(picture, Path):
                self._request(plugin_id, picture, source)
        self._prefetch_timer.start()

    def _request(self, plugin_id: str, entry, cache: Path) -> None:
        if plugin_id in self._requested:
            return
        if self._failures.get(plugin_id, 0) > _SCREENSHOT_RETRIES:
            return
        url = center.screenshot_url(entry)
        local = url is not None and url.startswith("file://") and \
            center.catalog_base().startswith("file://")
        if url is None or not (url.startswith("https://") or local):
            return
        self._requested.add(plugin_id)
        request = QNetworkRequest(QUrl(url))
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute,
                             QNetworkRequest.NoLessSafeRedirectPolicy)
        request.setRawHeader(b"User-Agent", center.USER_AGENT.encode())
        reply = self._network.get(request)
        self._pending[reply] = (plugin_id, cache)

    def _screenshot_finished(self, reply: QNetworkReply) -> None:
        """A screenshot arrived (QNetworkAccessManager.finished, GUI thread)."""
        target = self._pending.pop(reply, None)
        reply.deleteLater()
        if target is None or self._closing:
            return
        plugin_id, cache = target
        self._requested.discard(plugin_id)
        data = bytes(reply.readAll())
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        https = reply.url().scheme() == "https"
        if (reply.error() != QNetworkReply.NetworkError.NoError
                or (https and (status is None or not 200 <= int(status) < 300))
                or not data or len(data) > center.MAX_SCREENSHOT_BYTES
                or QImage.fromData(data).isNull()):
            log.info("could not fetch the screenshot of %s: %s", plugin_id,
                     reply.errorString())
            self._retry(plugin_id)
            return
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache.with_suffix(cache.suffix + ".part")
            temporary.write_bytes(data)
            temporary.replace(cache)
        except OSError:
            log.warning("could not keep the screenshot %s", cache, exc_info=True)
            return
        self._set_picture(plugin_id, cache, data)

    def _retry(self, plugin_id: str) -> None:
        """Ask again a little later while the tries last; the cards on
        screen are looked at again then."""
        failures = self._failures.get(plugin_id, 0) + 1
        self._failures[plugin_id] = failures
        if failures <= _SCREENSHOT_RETRIES:
            QTimer.singleShot(_SCREENSHOT_RETRY_MS * failures, self,
                              self._images_timer.start)

    def _prefetch_images(self) -> None:
        """Scale a few more of the pictures already on disk, off screen;
        again a moment later while any is left."""
        if self._closing or not self.isVisible():
            return
        done = 0
        for plugin_id, (label, picture) in list(self._image_labels.items()):
            if label.pixmap() is not None and not label.pixmap().isNull():
                continue
            source = self._source(picture)
            if (source is None or str(source) in self._unreadable
                    or not source.is_file()):
                continue
            if done == _PREFETCH_BATCH:
                self._prefetch_timer.start()
                return
            self._set_picture(plugin_id, source)
            done += 1
