# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Extensions tab of the right sidebar: the extension center.

Three sections, one card per plugin: *Included* (the ones that ship with
IngeCAD: Topography, Terrain), *Installed* (the user's own, from the
catalog or copied by hand) and *Available* (what the catalog offers and is
not here yet). A card says who made it, which version, what it does and
whether someone reviewed that exact version, and carries the buttons that
apply: Install, Update, Enable/Disable, Uninstall. Turning one on or off
takes effect at once (core/plugins.py); installing one turns it on.

Managers live in the sidebar, not in modal dialogs (Tools > Plugins... and
PLUGINS open this tab). The network -- the catalog, a download -- runs on
one worker thread at a time; without network the installed and included
plugins are still listed and managed.
"""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QSettings, Qt, QThread, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from core import extension_center as center
from core import i18n
from core.i18n import tr

#: The chip on each card. "badge|...": one plugin is "Incluida" where the
#: section of them is "Incluidas" (tr_context).
_BADGES = {
    "included": ("badge|Included", "#5b7a99"),
    "reviewed": ("badge|Reviewed", "#479B1B"),
    "community": ("badge|Community", "#b86e00"),
    "hand": ("badge|Installed by you", "#6c6c6c"),
}


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


class ExtensionsPanel(QWidget):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.manager = window.plugins
        self.snapshot: center.CatalogSnapshot | None = None
        self.catalog_error = ""
        self.message = ""
        self._worker: _Worker | None = None
        self._job = None
        self._asked = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        warning = QLabel(tr(
            "Extensions are Python code: they run with the same access as "
            "IngeCAD to your files and your network. Install only what you "
            "trust. Reviewed means someone read that exact version."), self)
        warning.setObjectName("ext_warning")
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "QLabel { background: rgba(184, 110, 0, 40); border: 1px solid "
            "#b86e00; border-radius: 4px; padding: 4px; }")
        layout.addWidget(warning)

        top = QHBoxLayout()
        self.status = QLabel(self)
        self.status.setObjectName("ext_status")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(self.status, 1)
        self.refresh_btn = QPushButton(tr("Refresh"), self)
        self.refresh_btn.setObjectName("ext_refresh")
        self.refresh_btn.setToolTip(tr("Download the catalog again"))
        self.refresh_btn.clicked.connect(self.fetch_catalog)
        top.addWidget(self.refresh_btn)
        layout.addLayout(top)

        self.tag_filter = QComboBox(self)
        self.tag_filter.setObjectName("ext_tags")
        self.tag_filter.addItem(tr("All categories"), "")
        for tag, label in center.TAGS.items():
            self.tag_filter.addItem(tr(label), tag)
        self.tag_filter.currentIndexChanged.connect(self.refresh)
        layout.addWidget(self.tag_filter)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._body = QWidget(scroll)
        self._cards = QVBoxLayout(self._body)
        self._cards.setContentsMargins(0, 0, 0, 0)
        self._cards.setSpacing(6)
        scroll.setWidget(self._body)
        layout.addWidget(scroll, 1)
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
        """The first time the tab is looked at, ask for the catalog."""
        if not self._asked:
            self.fetch_catalog()

    def busy(self) -> bool:
        return self._worker is not None

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
        """The window is closing: join the worker, drop its answer."""
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

    # -- the cards -----------------------------------------------------------------
    def _name(self, plugin_id: str) -> str:
        loaded = self.manager.loaded.get(plugin_id)
        if loaded is not None and loaded.spec is not None:
            return tr(loaded.spec.name)
        entry = self._catalog().get(plugin_id)
        if entry is not None:
            return center.display_name(entry, i18n.current_language())
        return plugin_id

    def refresh(self, *_args) -> None:
        """Rebuild the cards from what is on disk and in the catalog."""
        while self._cards.count():
            item = self._cards.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._status_text()
        self.refresh_btn.setEnabled(not self.busy())
        catalog = self._catalog()
        loaded = self.manager.loaded
        included = sorted(pid for pid, p in loaded.items() if p.bundled)
        installed = sorted(pid for pid, p in loaded.items() if not p.bundled)
        tag = self.tag_filter.currentData() or ""
        available = [e for e in sorted(catalog.values(), key=lambda e: e.id)
                     if e.id not in loaded and (not tag or tag in e.tags)]

        self._section(tr("Included"))
        for pid in included:
            self._cards.addWidget(self._plugin_card(pid, catalog.get(pid)))
        self._section(tr("Installed"))
        for pid in installed:
            self._cards.addWidget(self._plugin_card(pid, catalog.get(pid)))
        if not installed:
            self._note(tr("No extensions installed yet."))
        self._section(tr("Available"))
        for entry in available:
            self._cards.addWidget(self._catalog_card(entry))
        if not available:
            self._note(tr("Nothing more to install.") if self.snapshot is not None
                       else tr("The catalog is not loaded."))
        self._cards.addStretch(1)

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

    def _section(self, title: str) -> None:
        label = QLabel(f"<b>{title}</b>", self._body)
        label.setContentsMargins(0, 6, 0, 0)
        self._cards.addWidget(label)

    def _note(self, text: str) -> None:
        label = QLabel(text, self._body)
        label.setWordWrap(True)
        label.setEnabled(False)
        self._cards.addWidget(label)

    def _frame(self, plugin_id: str, title: str, version: str, author: str,
               summary: str, badge: str, tags=()) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame(self._body)
        frame.setObjectName(f"ext_card_{plugin_id}")
        frame.setFrameShape(QFrame.StyledPanel)
        box = QVBoxLayout(frame)
        box.setContentsMargins(6, 4, 6, 4)
        box.setSpacing(2)
        head = QHBoxLayout()
        name = QLabel(f"<b>{title}</b>" + (f"  {version}" if version else ""), frame)
        name.setWordWrap(True)
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        head.addWidget(name, 1)
        text, colour = _BADGES[badge]
        chip = QLabel(i18n.tr_context(text), frame)
        chip.setObjectName(f"ext_badge_{plugin_id}")
        chip.setProperty("badge", badge)
        chip.setStyleSheet(f"QLabel {{ background: {colour}; color: white; "
                           "border-radius: 3px; padding: 0 4px; }")
        head.addWidget(chip, 0, Qt.AlignTop)
        box.addLayout(head)
        if author:
            by = QLabel(tr("by {author}", author=author), frame)
            by.setEnabled(False)
            box.addWidget(by)
        if summary:
            about = QLabel(summary, frame)
            about.setWordWrap(True)
            box.addWidget(about)
        if tags:
            cats = QLabel(" · ".join(tr(center.TAGS[t]) for t in tags
                                     if t in center.TAGS), frame)
            cats.setEnabled(False)
            box.addWidget(cats)
        return frame, box

    def _button(self, frame: QFrame, row: QHBoxLayout, name: str, label: str,
                plugin_id: str, slot, enabled: bool = True) -> QPushButton:
        button = QPushButton(label, frame)
        button.setObjectName(f"ext_{name}_{plugin_id}")
        button.setFocusPolicy(Qt.NoFocus)
        button.setEnabled(enabled and not self.busy())
        button.clicked.connect(slot)
        row.addWidget(button)
        return button

    def _plugin_card(self, plugin_id: str, entry) -> QFrame:
        loaded = self.manager.loaded[plugin_id]
        spec = loaded.spec
        language = i18n.current_language()
        managed = (not loaded.bundled
                   and center.is_managed(plugin_id, self.manager.user_dir))
        info = center.installed_info(plugin_id, self.manager.user_dir) if managed else None
        if loaded.bundled:
            badge, author = "included", "IngeCAD"
        elif not managed:
            badge, author = "hand", ""
        else:
            badge = "reviewed" if entry is not None and self._reviewed(entry) else "community"
            author = entry.author if entry is not None else ""
        version = (spec.version if spec is not None
                   else (info or {}).get("version", ""))
        summary = (center.display_summary(entry, language) if entry is not None
                   else (tr(spec.description) if spec is not None and spec.description
                         else ""))
        frame, box = self._frame(plugin_id, self._name(plugin_id), version,
                                 author, summary, badge,
                                 entry.tags if entry is not None else ())
        if not loaded.available:
            self._note_in(frame, box, tr("unavailable: {reason}", reason=loaded.reason))
        row = QHBoxLayout()
        active = self.manager.is_active(plugin_id)
        self._button(frame, row, "toggle", tr("Disable") if active else tr("Enable"),
                     plugin_id,
                     lambda _=False, p=plugin_id, on=not active: self.set_enabled(p, on),
                     enabled=loaded.available or active)
        if managed:
            self._button(frame, row, "uninstall", tr("Uninstall"), plugin_id,
                         lambda _=False, p=plugin_id: self.uninstall(p))
        row.addStretch(1)
        box.addLayout(row)
        if managed and entry is not None and center.update_available(
                entry, self.manager.user_dir):
            # a row of its own: three buttons do not fit a narrow sidebar
            update = QHBoxLayout()
            self._button(frame, update, "update",
                         tr("Update to {version}", version=entry.version),
                         plugin_id, lambda _=False, e=entry: self.install(e),
                         enabled=center.compatible(entry))
            update.addStretch(1)
            box.addLayout(update)
        if active and self.manager.has_toolbar(plugin_id):
            check = QCheckBox(tr("Show this plugin's toolbar"), frame)
            check.setObjectName(f"ext_toolbar_{plugin_id}")
            # its text may be cut, never the sidebar widened by it
            check.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            check.setToolTip(check.text())
            check.setChecked(self.manager.toolbar_enabled(plugin_id))
            check.toggled.connect(
                lambda on, p=plugin_id: self._toolbar_toggled(p, on))
            box.addWidget(check)
        if not managed and not loaded.bundled:
            self._note_in(frame, box, tr("Location: {path}", path=str(loaded.location)))
        return frame

    def _catalog_card(self, entry) -> QFrame:
        language = i18n.current_language()
        frame, box = self._frame(
            entry.id, center.display_name(entry, language), entry.version,
            entry.author, center.display_summary(entry, language),
            "reviewed" if self._reviewed(entry) else "community", entry.tags)
        ok = center.compatible(entry)
        if not ok:
            self._note_in(frame, box, tr("Requires IngeCAD {version} or later.",
                                         version=entry.minimum_version))
        row = QHBoxLayout()
        self._button(frame, row, "install", tr("Install"), entry.id,
                     lambda _=False, e=entry: self.install(e), enabled=ok)
        row.addStretch(1)
        box.addLayout(row)
        return frame

    def _note_in(self, frame: QFrame, box: QVBoxLayout, text: str) -> None:
        label = QLabel(text, frame)
        label.setWordWrap(True)
        label.setEnabled(False)
        box.addWidget(label)
