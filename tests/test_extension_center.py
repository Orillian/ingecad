# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The extension center: the catalog, install, update, uninstall.

No network: the catalog and the downloads are served from memory by a
stand-in for ``core.extension_center._get``, and the user's plugins folder
is a temporary one. Through the window wherever there is a window to go
through: PLUGINS opens the Extensions tab, the buttons are clicked.
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from core import extension_center as center
from core import plugins

FIXTURE = Path(__file__).resolve().parent / "plugins_fixture"
ID = "demo_ext"
BASE = center.DEFAULT_BASE


def _source(version: str, command: str = "DEMOEXT", helper: bool = False) -> str:
    # with ``helper`` the echoed text comes from a submodule, so an update
    # that kept the old submodule loaded would say the old version
    text = "TEXT" if helper else repr(f"demo {version}")
    return (
        "from core.plugins import MenuItem, PluginSpec\n"
        + ("from .helpers import TEXT\n" if helper else "") + "\n"
        "def run(ctx, *args):\n"
        f"    ctx.echo({text})\n\n"
        f"PLUGIN = PluginSpec(id={ID!r}, name='Demo', version={version!r},\n"
        f"    commands={{{command!r}: run}}, aliases={{'DQX': {command!r}}},\n"
        f"    menu=(MenuItem('Run demo', {command!r}),))\n")


def _zip(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def _package(version: str = "1.0", command: str = "DEMOEXT") -> bytes:
    # what a GitHub release of a plugin looks like: the folder, inside
    return _zip({f"{ID}-{version}/{ID}/__init__.py": _source(version, command, True),
                 f"{ID}-{version}/{ID}/helpers.py": f"TEXT = 'demo {version}'\n",
                 f"{ID}-{version}/README.md": "demo\n"})


def _entry(data: bytes, version: str = "1.0", **overrides) -> dict:
    entry = {
        "id": ID, "version": version, "author": "Ana Example",
        "author_url": "https://example.org", "license": "GPL-3.0-or-later",
        "repository": "https://example.org/demo",
        "download": f"https://example.org/{ID}-{version}.zip",
        "sha256": hashlib.sha256(data).hexdigest(), "ingecad": "0.6",
        "tags": ["drawing", "productivity"], "screenshot": None,
        "name": {"en": "Demo extension", "es": "Extensión de prueba"},
        "summary": {"en": "Adds one command.", "es": "Agrega un comando."},
    }
    entry.update(overrides)
    return entry


class _Server:
    """``_get`` from memory: url -> bytes; anything else is offline."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.online = True
        self.asked: list[str] = []

    def publish(self, entries: list, reviewed: dict | None = None,
                downloads: dict | None = None) -> None:
        self.files[f"{BASE}/catalog.json"] = json.dumps(
            {"format": 1, "extensions": entries}).encode()
        toml = "".join(f'[{k}]\nsha256 = "{v}"\n' for k, v in (reviewed or {}).items())
        self.files[f"{BASE}/reviewed.toml"] = toml.encode()
        self.files.update(downloads or {})

    def __call__(self, url: str, limit: int) -> bytes:
        self.asked.append(url)
        if not self.online or url not in self.files:
            raise center.ExtensionError(f"Could not download {url}: offline")
        return self.files[url]


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    folder = tmp_path / "config" / "plugins"
    monkeypatch.setattr(plugins, "user_plugins_dir", lambda: folder)
    monkeypatch.delenv("INGECAD_EXTENSIONS_BASE", raising=False)
    return folder


@pytest.fixture
def server(monkeypatch):
    serve = _Server()
    monkeypatch.setattr(center, "_get", serve)
    return serve


@pytest.fixture
def settings_clean():
    from PySide6.QtCore import QSettings

    yield
    settings = QSettings()
    for key in (f"plugins/{ID}/enabled", f"plugins/{ID}/toolbar",
                "plugins/ejemplo/enabled"):
        settings.remove(key)


def _window(qapp):
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    return win


def _open_tab(win):
    """PLUGINS, as typed: the sidebar shows the Extensions tab and the
    catalog is asked for; wait for the answer."""
    win.dispatcher.submit("PLUGINS")
    panel = win._extensions_panel
    assert win._sidebar_tabs.currentWidget() is panel
    panel.wait()
    return panel


def _card(panel, ident):
    from PySide6.QtWidgets import QFrame

    return panel.findChild(QFrame, f"ext_card_{ident}")


def _button(panel, name, ident):
    from PySide6.QtWidgets import QPushButton

    return panel.findChild(QPushButton, f"ext_{name}_{ident}")


def _section_of(panel, ident) -> str:
    """The section heading the card sits under."""
    from PySide6.QtWidgets import QLabel

    heading = ""
    for i in range(panel._cards.count()):
        widget = panel._cards.itemAt(i).widget()
        if isinstance(widget, QLabel) and widget.text().startswith("<b>"):
            heading = widget.text()[3:-4]
        elif widget is not None and widget.objectName() == f"ext_card_{ident}":
            return heading
    return ""


def _click(panel, name, ident):
    button = _button(panel, name, ident)
    assert button is not None, f"no {name} button for {ident}"
    assert button.isEnabled()
    button.click()
    panel.wait()


def _leftovers(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


# -- the catalog ------------------------------------------------------------------

def test_the_tab_lists_the_catalog_and_what_is_included(qapp, user_dir, server):
    data = _package()
    server.publish([_entry(data)])
    win = _window(qapp)
    try:
        assert server.asked == [], "the catalog is fetched at start-up"
        panel = _open_tab(win)
        assert f"{BASE}/catalog.json" in server.asked
        assert _section_of(panel, ID) == "Available"
        assert _button(panel, "install", ID) is not None
        assert _card(panel, ID).findChild(
            type(panel.status), f"ext_badge_{ID}").property("badge") == "community"
        for bundled in ("topografia", "terreno"):
            assert _section_of(panel, bundled) == "Included"
        assert "1 extension(s)" in panel.status.text()
        assert "same access as IngeCAD" in panel.findChild(
            type(panel.status), "ext_warning").text()
        # Tools > Plugins... is the same door
        win._sidebar_tabs.setCurrentIndex(0)
        assert "Plugins..." in [a.text() for a in _tools_menu(win)]
    finally:
        win.close()


def _tools_menu(win):
    actions = win._menu_bar.actions()
    menu = next(a.menu() for a in actions if a.text() == "Tools")
    return menu.actions()


def test_a_tag_filters_the_available_list(qapp, user_dir, server):
    data = _package()
    server.publish([_entry(data)])
    win = _window(qapp)
    try:
        panel = _open_tab(win)
        combo = panel.tag_filter
        combo.setCurrentIndex(combo.findData("gis"))
        assert _card(panel, ID) is None
        combo.setCurrentIndex(combo.findData("drawing"))
        assert _card(panel, ID) is not None
    finally:
        win.close()


# -- install ------------------------------------------------------------------------

def test_install_verifies_and_the_plugin_runs_at_once(qapp, user_dir, server,
                                                      settings_clean):
    data = _package()
    entry = _entry(data)
    server.publish([entry], reviewed={ID: entry["sha256"]},
                   downloads={entry["download"]: data})
    win = _window(qapp)
    echoed = []
    win.command_line.echo = echoed.append
    try:
        panel = _open_tab(win)
        panel.confirm = lambda *a: pytest.fail("a reviewed one needs no question")
        _click(panel, "install", ID)
        assert "DEMOEXT" in win.dispatcher._commands
        win.dispatcher.submit("DEMOEXT")
        assert echoed[-1] == "demo 1.0"
        assert win.dispatcher.resolve_name("DQX") == "DEMOEXT"
        folder = user_dir / ID
        assert (folder / "__init__.py").is_file() and (folder / "helpers.py").is_file()
        assert not (folder / "README.md").exists()       # outside the package
        info = json.loads((folder / "extension.json").read_text())
        assert info["version"] == "1.0" and info["sha256"] == entry["sha256"]
        assert _section_of(panel, ID) == "Installed"
        assert _card(panel, ID).findChild(
            type(panel.status), f"ext_badge_{ID}").property("badge") == "reviewed"
        assert _leftovers(user_dir) == [ID], "the stage was left behind"
    finally:
        win.plugins.forget(ID)
        win.close()


def test_a_bad_checksum_installs_nothing(qapp, user_dir, server, settings_clean):
    data = _package()
    entry = _entry(data, sha256="0" * 64)
    server.publish([entry], downloads={entry["download"]: data})
    win = _window(qapp)
    try:
        panel = _open_tab(win)
        panel.confirm = lambda *a: True
        _click(panel, "install", ID)
        assert "Checksum mismatch" in panel.message
        assert "DEMOEXT" not in win.dispatcher._commands
        assert ID not in win.plugins.loaded
        assert _leftovers(user_dir) == []
        assert _section_of(panel, ID) == "Available"
    finally:
        win.close()


def test_an_unreviewed_extension_asks_first(qapp, user_dir, server, settings_clean):
    data = _package()
    entry = _entry(data)
    server.publish([entry], downloads={entry["download"]: data})
    win = _window(qapp)
    try:
        panel = _open_tab(win)
        asked = []
        panel.confirm = lambda title, text: asked.append(text) or False
        _button(panel, "install", ID).click()
        panel.wait()
        assert asked and "has not been reviewed" in asked[0]
        assert entry["download"] not in server.asked
        assert _leftovers(user_dir) == []
    finally:
        win.close()


# -- disable, uninstall: no trace -------------------------------------------------------

def test_disable_and_uninstall_leave_no_trace(qapp, user_dir, server, settings_clean):
    from PySide6.QtCore import QSettings

    from tests.test_plugins import _snapshot

    data = _package()
    entry = _entry(data)
    server.publish([entry], reviewed={ID: entry["sha256"]},
                   downloads={entry["download"]: data})
    win = _window(qapp)
    try:
        panel = _open_tab(win)
        before = _snapshot(win)
        _click(panel, "install", ID)
        during = _snapshot(win)
        assert during != before and "Demo" in during["menus"]
        _click(panel, "toggle", ID)                       # Disable
        assert _snapshot(win) == before
        assert str(QSettings().value(f"plugins/{ID}/enabled")) == "false"
        assert _button(panel, "toggle", ID).text() == "Enable"
        _click(panel, "toggle", ID)                       # Enable again
        assert _snapshot(win) == during
        panel.confirm = lambda *a: True
        _click(panel, "uninstall", ID)
        assert _snapshot(win) == before
        assert not (user_dir / ID).exists() and _leftovers(user_dir) == []
        assert not any(m.startswith(f"ingecad_plugin_{ID}") for m in sys.modules)
        assert QSettings().value(f"plugins/{ID}/enabled") is None
        assert ID not in win.plugins.loaded
        assert _section_of(panel, ID) == "Available"     # back on offer
    finally:
        win.plugins.forget(ID)
        win.close()


def test_a_plugin_copied_by_hand_is_never_deleted(qapp, user_dir, server,
                                                  settings_clean):
    server.online = False
    user_dir.mkdir(parents=True)
    shutil.copytree(FIXTURE / "ejemplo", user_dir / "ejemplo")
    win = _window(qapp)
    try:
        panel = _open_tab(win)
        assert _section_of(panel, "ejemplo") == "Installed"
        assert _button(panel, "uninstall", "ejemplo") is None
        assert _button(panel, "toggle", "ejemplo").text() == "Enable"
        _click(panel, "toggle", "ejemplo")
        assert "HELLO" in win.dispatcher._commands
        with pytest.raises(center.ExtensionError):
            center.uninstall_extension("ejemplo", user_dir)
        assert (user_dir / "ejemplo" / "__init__.py").is_file()
    finally:
        win.plugins.forget("ejemplo")
        win.close()


# -- update -------------------------------------------------------------------------------

def test_update_replaces_the_version_in_place(qapp, user_dir, server, settings_clean):
    old, new = _package("1.0"), _package("2.0")
    first, second = _entry(old, "1.0"), _entry(new, "2.0")
    server.publish([first], reviewed={ID: first["sha256"]},
                   downloads={first["download"]: old})
    win = _window(qapp)
    echoed = []
    win.command_line.echo = echoed.append
    try:
        panel = _open_tab(win)
        _click(panel, "install", ID)
        assert _button(panel, "update", ID) is None
        server.publish([second], reviewed={ID: first["sha256"]},
                       downloads={second["download"]: new})
        panel.refresh_btn.click()
        panel.wait()
        update = _button(panel, "update", ID)
        assert update is not None and "2.0" in update.text()
        # the new version is not the one reviewed: Community, and it asks
        assert _card(panel, ID).findChild(
            type(panel.status), f"ext_badge_{ID}").property("badge") == "community"
        panel.confirm = lambda *a: True
        _click(panel, "update", ID)
        assert win.plugins.loaded[ID].spec.version == "2.0"
        assert win.plugins.is_active(ID)
        win.dispatcher.submit("DEMOEXT")
        assert echoed[-1] == "demo 2.0"
        info = center.installed_info(ID, user_dir)
        assert info["version"] == "2.0" and info["sha256"] == second["sha256"]
        assert _button(panel, "update", ID) is None
        assert _leftovers(user_dir) == [ID], "the backup was left behind"
    finally:
        win.plugins.forget(ID)
        win.close()


def test_an_update_that_renames_its_command_drops_the_old_one(qapp, user_dir,
                                                              settings_clean):
    """Updating unloads the old modules: what v1 registered is gone."""
    from views.main_window import MainWindow

    v1, v2 = _package("1.0", "DEMOEXT"), _package("2.0", "DEMONEW")
    center.install_bytes(center._parse_extension(_entry(v1)), v1, user_dir)
    win = MainWindow()
    try:
        win.plugins.set_enabled(ID, True)
        assert "DEMOEXT" in win.dispatcher._commands
        center.install_bytes(center._parse_extension(_entry(v2, "2.0")), v2, user_dir)
        win.plugins.reload(ID)
        assert "DEMONEW" in win.dispatcher._commands
        assert "DEMOEXT" not in win.dispatcher._commands
        echoed = []
        win.command_line.echo = echoed.append
        win.dispatcher.submit("DEMONEW")
        assert echoed[-1] == "demo 2.0", "the old submodule stayed loaded"
    finally:
        win.plugins.forget(ID)
        win.close()


# -- offline ------------------------------------------------------------------------------

def test_offline_still_lists_and_manages_what_is_installed(qapp, user_dir, server,
                                                           settings_clean):
    data = _package()
    center.install_bytes(center._parse_extension(_entry(data)), data, user_dir)
    server.online = False
    win = _window(qapp)
    try:
        panel = _open_tab(win)
        assert "Catalog unavailable" in panel.status.text()
        assert _section_of(panel, ID) == "Installed"
        for bundled in ("topografia", "terreno"):
            assert _section_of(panel, bundled) == "Included"
            assert _button(panel, "toggle", bundled) is not None
        _click(panel, "toggle", ID)
        assert "DEMOEXT" in win.dispatcher._commands
        panel.confirm = lambda *a: True
        _click(panel, "uninstall", ID)
        assert "DEMOEXT" not in win.dispatcher._commands
        assert not (user_dir / ID).exists()
    finally:
        win.plugins.forget(ID)
        win.close()


def test_offline_falls_back_to_the_last_catalog(qapp, user_dir, server):
    data = _package()
    server.publish([_entry(data)])
    snapshot = center.refresh_catalog(user_dir)
    assert not snapshot.from_cache
    server.online = False
    cached = center.refresh_catalog(user_dir)
    assert cached.from_cache and [e.id for e in cached.extensions] == [ID]
    win = _window(qapp)
    try:
        panel = _open_tab(win)
        assert "Offline" in panel.status.text()
        assert _section_of(panel, ID) == "Available"
    finally:
        win.close()


# -- unsafe archives, headless ----------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "../escaped.py", f"{ID}/../../escaped.py", "/tmp/escaped.py",
    "C:/escaped.py", f"{ID}\\..\\escaped.py",
])
def test_an_archive_with_an_unsafe_path_is_refused_whole(user_dir, server, name):
    data = _zip({f"{ID}/__init__.py": _source("1.0"), name: "print('owned')\n"})
    entry = _entry(data)
    server.publish([entry], downloads={entry["download"]: data})
    with pytest.raises(center.ExtensionError, match="unsafe path"):
        center.install_extension(center._parse_extension(entry), user_dir)
    assert _leftovers(user_dir) == []
    assert not (user_dir.parent / "escaped.py").exists()


def test_a_symlink_in_the_archive_is_refused(user_dir, server):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{ID}/__init__.py", _source("1.0"))
        link = zipfile.ZipInfo(f"{ID}/link")
        link.external_attr = (0o120777 << 16)
        archive.writestr(link, "/etc/passwd")
    data = buffer.getvalue()
    entry = _entry(data)
    server.publish([entry], downloads={entry["download"]: data})
    with pytest.raises(center.ExtensionError, match="unsafe path"):
        center.install_extension(center._parse_extension(entry), user_dir)
    assert _leftovers(user_dir) == []


def test_a_single_file_plugin_is_wrapped_into_a_folder(user_dir, server):
    data = _zip({f"{ID}.py": _source("1.0")})
    entry = _entry(data)
    server.publish([entry], downloads={entry["download"]: data})
    folder = center.install_extension(center._parse_extension(entry), user_dir)
    assert folder == user_dir / ID and (folder / "__init__.py").is_file()
    loaded = plugins.load_plugin(folder, bundled=False)
    assert loaded.available and "DEMOEXT" in loaded.spec.commands
    sys.modules.pop(f"ingecad_plugin_{ID}", None)


def test_two_packages_in_one_archive_are_refused(user_dir):
    data = _zip({"one/__init__.py": "", "two/__init__.py": ""})
    with pytest.raises(center.ExtensionError, match="more than one"):
        center.install_bytes(center._parse_extension(_entry(data)), data, user_dir)
    assert _leftovers(user_dir) == []


def test_the_name_of_an_included_plugin_cannot_be_taken(user_dir, server):
    data = _package()
    entry = _entry(data, id="topografia")
    server.publish([entry], downloads={entry["download"]: data})
    with pytest.raises(center.ExtensionError, match="included with IngeCAD"):
        center.install_extension(center._parse_extension(entry), user_dir)
    assert entry["download"] not in server.asked


def test_the_catalog_refuses_plain_http_and_old_ingecad(user_dir):
    data = _package()
    good = _entry(data)
    snapshot = center.parse_catalog(json.dumps({"format": 1, "extensions": [
        _entry(data, id="plain", download="http://example.org/x.zip"),
        good]}).encode(), b"")
    assert [e.id for e in snapshot.extensions] == [ID]   # the bad entry only
    future = center._parse_extension(_entry(data, ingecad="99.0"))
    assert not center.compatible(future)
    with pytest.raises(center.ExtensionError, match="requires IngeCAD"):
        center.install_extension(future, user_dir)
    assert center.compatible(center._parse_extension(_entry(data, ingecad="0.6.9")))
    assert not center.compatible(center._parse_extension(_entry(data, ingecad="0.7")))
