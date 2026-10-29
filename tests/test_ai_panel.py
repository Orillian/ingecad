# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The Assistant tab: off by default, one undo per answer, Stop, closing.

The provider is the fake server of test_ai_providers, reached through the
"Server URL" the user can type; the key lives in a throwaway file store.
The turn runs on the real worker thread and its tools on the real window.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from test_ai_providers import FakeServer, _anthropic_text, _anthropic_tool_use

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def assistant(qapp, clean_settings, tmp_path, monkeypatch):
    """Turn the assistant on against a fake server; yields make(replies)."""
    from core.ai import secrets
    from views import ai_panel

    store = secrets._FileStore(tmp_path / "ai-keys.json")
    monkeypatch.setattr(secrets, "_override", (None, store))
    store.store("anthropic", "sk-test")
    servers = []

    def make(replies, privacy_ok=True):
        server = FakeServer(replies)
        servers.append(server)
        settings = QSettings()
        settings.setValue(ai_panel.SETTING_ON, True)
        settings.setValue(ai_panel.SETTING_PROVIDER, "anthropic")
        settings.setValue(ai_panel.SETTING_BASE_URL, server.url)
        if privacy_ok:
            settings.setValue(ai_panel.SETTING_PRIVACY_OK.format(id="anthropic"),
                              True)
        return server
    yield make
    for server in servers:
        server.close()


def _window():
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    return win


def _type(win, text):
    edit = win.command_line.input
    edit.setFocus()
    if text:
        QTest.keyClicks(edit, text)
    QTest.keyClick(edit, Qt.Key_Return)


def _wait(condition, seconds=20.0):
    end = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < end, "timed out"
        QApplication.processEvents()
        time.sleep(0.01)


def test_off_by_default_imports_nothing_of_the_assistant(tmp_path):
    script = (
        "import sys\n"
        "from PySide6.QtWidgets import QApplication\n"
        "app = QApplication([])\n"
        "from views.main_window import MainWindow\n"
        "win = MainWindow()\n"
        "win.new_document()\n"
        "win.dispatcher.submit('AI')\n"
        "tabs = win._sidebar_tabs\n"
        "print('TABS', [tabs.tabText(i) for i in range(tabs.count())])\n"
        "print('LOADED', sorted(m for m in sys.modules if m.startswith('core.ai')))\n"
        "win.document.dirty = False\n"
        "win.close()\n")
    env = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path),
               QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(REPO))
    out = subprocess.run([sys.executable, "-c", script], cwd=REPO, env=env,
                         capture_output=True, text=True, timeout=120)
    lines = dict(ln.split(" ", 1) for ln in out.stdout.splitlines()
                 if ln.startswith(("TABS", "LOADED")))
    assert lines.get("LOADED") == "[]", out.stderr[-2000:]
    assert "Assistant" not in lines["TABS"]


def test_one_answer_is_one_undo_and_the_tab_follows_options(assistant):
    from views.options_dialog import OptionsDialog

    server = assistant([
        _anthropic_tool_use("draw_circle", {"center": [1, 1], "radius": 3}),
        _anthropic_tool_use("draw_line", {"points": [[0, 0], [5, 5]]},
                            "toolu_2"),
        _anthropic_text("Done.")])
    win = _window()
    try:
        panel = win._assistant_panel
        assert panel is not None
        assert win._sidebar_tabs.indexOf(panel) >= 0
        # a line drawn by hand first: the answer must not swallow it
        for typed in ("LINE", "0,10", "10,10", ""):
            _type(win, typed)
        depth = len(win.history._undo)
        assert depth >= 1
        _type(win, "AI")
        assert win._sidebar_tabs.currentWidget() is panel
        assert panel.send("draw a circle and a line")
        _wait(lambda: not panel.busy())
        assert sorted(e.dxftype() for e in win.document.modelspace()) \
            == ["CIRCLE", "LINE", "LINE"]
        assert len(win.history._undo) == depth + 1
        assert "Done." in panel.log.toPlainText()
        assert server.requests[0]["headers"]["x-api-key"] == "sk-test"
        _type(win, "U")          # one U takes the whole answer
        assert [e.dxftype() for e in win.document.modelspace()] == ["LINE"]
        # turned off in Options: the tab goes away
        dialog = OptionsDialog(win)
        dialog._ai_page.assistant_on.setChecked(False)
        dialog.apply()
        assert win._assistant_panel is None
        assert all(win._sidebar_tabs.tabText(i) != "Assistant"
                   for i in range(win._sidebar_tabs.count()))
    finally:
        win.document.dirty = False
        win.close()


def test_nothing_is_sent_until_the_privacy_notice_is_accepted(assistant):
    from views import ai_panel

    server = assistant([_anthropic_text("hi")], privacy_ok=False)
    win = _window()
    try:
        panel = win._assistant_panel
        panel.ask_privacy = lambda provider: False
        assert not panel.send("hello")
        assert server.requests == []
        panel.ask_privacy = lambda provider: True
        assert panel.send("hello")
        _wait(lambda: not panel.busy())
        assert len(server.requests) == 1
        assert ai_panel._flag(ai_panel.SETTING_PRIVACY_OK.format(id="anthropic"))
    finally:
        win.document.dirty = False
        win.close()


def test_closing_mid_answer_stops_the_turn_and_joins_the_thread(assistant,
                                                                 monkeypatch):
    from views import ai_panel

    server = assistant([_anthropic_tool_use("draw_circle",
                                            {"center": [0, 0], "radius": 1}),
                        _anthropic_text("never asked for")])
    asked = []
    # the window never gets round to answering the tool: the worker waits
    monkeypatch.setattr(ai_panel.AssistantPanel, "_on_tool_request",
                        lambda self, name, args: asked.append(name))
    win = _window()
    panel = win._assistant_panel
    assert panel.send("draw")
    _wait(lambda: asked)
    worker = panel._worker
    assert worker.isRunning()
    win.document.dirty = False
    win.close()                       # must not hang
    assert worker.isFinished()
    assert len(server.requests) == 1   # stopped before the next step
    assert len(win.document.modelspace()) == 0


def test_a_missing_key_is_said_not_sent(assistant):
    from core.ai import secrets

    server = assistant([_anthropic_text("hi")])
    secrets.forget("anthropic")
    win = _window()
    try:
        panel = win._assistant_panel
        assert not panel.send("hello")
        assert "no API key" in panel.log.toPlainText()
        assert server.requests == []
    finally:
        win.document.dirty = False
        win.close()
