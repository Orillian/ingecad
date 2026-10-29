# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The MCP bridge: ``main.py --mcp`` as a client starts it, talking to a
real window through the socket, and the token that keeps others out.

The socket and the token file live in a fresh folder of /tmp (a Unix
socket path has to be short), never in the user's runtime folder.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.ai import mcp_server

REPO = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform == "win32",
                                reason="the tests speak to a Unix socket")


@pytest.fixture
def bridge_env(monkeypatch, clean_settings):
    folder = Path(tempfile.mkdtemp(prefix="icmcp", dir="/tmp"))
    sock, token = folder / "s", folder / "t"
    monkeypatch.setenv("INGECAD_MCP_SOCKET", str(sock))
    monkeypatch.setenv("INGECAD_MCP_TOKEN", str(token))
    yield sock, token
    shutil.rmtree(folder, ignore_errors=True)


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


def _pump_until(condition, seconds=30.0):
    end = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < end, "timed out"
        QApplication.processEvents()
        time.sleep(0.005)


def test_off_by_default_and_the_two_commands(qapp, bridge_env):
    sock, token = bridge_env
    win = _window()
    try:
        assert win._mcp_bridge is None and not sock.exists()
        _type(win, "MCPSTART")
        assert win._mcp_bridge is not None and sock.exists()
        assert oct(token.stat().st_mode & 0o777) == "0o600"
        assert len(token.read_text()) == 64
        _type(win, "MCPSTOP")
        assert win._mcp_bridge is None and not token.exists()
        assert str(QSettings().value("ai/mcp")).lower() == "false"
    finally:
        win.document.dirty = False
        win.close()


def test_a_client_drives_the_window_through_main_mcp(qapp, bridge_env):
    QSettings().setValue("ai/mcp", True)
    win = _window()
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "main.py"), "--mcp"], cwd=REPO,
        env=dict(os.environ), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True)
    answers: dict = {}

    def reader():
        for line in proc.stdout:
            message = json.loads(line)          # stdout is nothing but JSON
            answers[message.get("id")] = message
    threading.Thread(target=reader, daemon=True).start()

    def ask(mid, method, params=None):
        message = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            message["params"] = params
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
        _pump_until(lambda: mid in answers)
        return answers[mid]

    try:
        assert win._mcp_bridge is not None
        init = ask(1, "initialize", {"protocolVersion": "2025-06-18",
                                     "capabilities": {},
                                     "clientInfo": {"name": "t", "version": "0"}})
        assert init["result"]["protocolVersion"] == "2025-06-18"
        assert init["result"]["serverInfo"]["name"] == "ingecad"
        proc.stdin.write(json.dumps({"jsonrpc": "2.0",
                                     "method": "notifications/initialized"})
                         + "\n")
        tools = ask(2, "tools/list")["result"]["tools"]
        circle = next(t for t in tools if t["name"] == "draw_circle")
        assert circle["inputSchema"]["type"] == "object"
        depth = len(win.history._undo)
        # two segments, two Commands -- and still one undo step per call
        done = ask(3, "tools/call", {"name": "draw_line", "arguments": {
            "points": [[0, 0], [10, 0], [10, 20]]}})["result"]
        assert done["isError"] is False
        created = json.loads(done["content"][0]["text"])["created"]
        lines = list(win.document.modelspace())
        assert [e.dxftype() for e in lines] == ["LINE", "LINE"]
        assert sorted(e.dxf.handle for e in lines) == sorted(created)
        assert len(win.history._undo) == depth + 1
        bad = ask(4, "tools/call", {"name": "draw_circle", "arguments": {
            "center": [0, 0], "radius": -1}})["result"]
        assert bad["isError"] is True
        assert ask(5, "nope")["error"]["code"] == -32601
        assert ask(6, "ping")["result"] == {}
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
        win.document.dirty = False
        win.close()
    assert proc.returncode == 0, proc.stderr.read()[-2000:]


def test_a_wrong_token_gets_nothing(qapp, bridge_env):
    sock, _token = bridge_env
    QSettings().setValue("ai/mcp", True)
    win = _window()
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(sock))
        client.setblocking(False)
        client.sendall(b'{"token": "guess"}\n'
                       b'{"id": 1, "call": "erase_entities", "arguments": {}}\n')
        got = b""

        def closed():
            nonlocal got
            try:
                chunk = client.recv(4096)
            except BlockingIOError:
                return False
            got += chunk
            return chunk == b""
        _pump_until(closed)
        assert json.loads(got.splitlines()[0]) == {"error": "bad token"}
        assert len(got.splitlines()) == 1          # the call never ran
        client.close()
    finally:
        win.document.dirty = False
        win.close()


def test_without_a_window_the_call_says_how_to_start_the_bridge(tmp_path):
    server = mcp_server.Server(mcp_server.BridgeClient(
        str(tmp_path / "nobody"), str(tmp_path / "no-token")))
    answer = server.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                            "params": {"name": "draw_line", "arguments": {}}})
    assert answer["result"]["isError"] is True
    assert "MCPSTART" in answer["result"]["content"][0]["text"]
    # the list is there all the same, and an unknown protocol gets the newest
    listed = server.handle({"jsonrpc": "2.0", "id": 8, "method": "tools/list"})
    assert any(t["name"] == "draw_line" for t in listed["result"]["tools"])
    init = server.handle({"jsonrpc": "2.0", "id": 9, "method": "initialize",
                          "params": {"protocolVersion": "1999-01-01"}})
    assert init["result"]["protocolVersion"] == mcp_server.PROTOCOL_VERSIONS[0]
    assert server.handle({"jsonrpc": "2.0", "method": "x"}) is None


def test_pictures_travel_as_image_content():
    out = mcp_server.call_result({"image": "aGk=", "note": "view"})
    assert out["content"][0] == {"type": "image", "data": "aGk=",
                                 "mimeType": "image/png"}
    assert out["content"][1]["text"] == "view"
