# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The two provider adapters and the tool loop, against a fake server.

A local http.server answers as Anthropic's Messages API or as an
OpenAI-compatible chat endpoint would, from a script, and keeps every
request it got -- so the tests read what IngeCAD really sent: headers,
tool definitions, tool results, pictures. No network, no key.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from core.ai import providers as P
from core.ai.tools import Image


class FakeServer:
    def __init__(self, replies):
        self.replies = list(replies)     # (status, body) per request
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("content-length", 0))
                outer.requests.append({
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": json.loads(self.rfile.read(length))})
                status, body = outer.replies.pop(0)
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    made = []

    def make(replies):
        s = FakeServer(replies)
        made.append(s)
        return s
    yield make
    for s in made:
        s.close()


ANTHROPIC = P.PROVIDERS["anthropic"]
OPENAI = P.PROVIDERS["openai"]
TOOLS = [{"name": "draw_circle", "description": "A circle.",
          "parameters": {"type": "object", "properties": {}}},
         {"name": "capture_view", "description": "A picture.",
          "parameters": {"type": "object", "properties": {}}}]


def _anthropic_tool_use(name, args, uid="toolu_1"):
    return 200, {"content": [{"type": "thinking", "thinking": "",
                              "signature": "sig"},
                             {"type": "text", "text": "Drawing it."},
                             {"type": "tool_use", "id": uid, "name": name,
                              "input": args}],
                 "stop_reason": "tool_use"}


def _anthropic_text(text):
    return 200, {"content": [{"type": "text", "text": text}],
                 "stop_reason": "end_turn"}


def test_anthropic_round_trip(server):
    s = server([_anthropic_tool_use("draw_circle", {"center": [0, 0],
                                                     "radius": 5}),
                _anthropic_text("Done.")])
    calls, said, history = [], [], []

    def execute(name, args):
        calls.append((name, args))
        return {"created": ["2A"], "revision": 3}

    end = P.run_turn(ANTHROPIC, "claude-opus-5-5", "sk-ant-x", history,
                     "draw a circle", execute, tools=TOOLS, base_url=s.url,
                     on_text=said.append)
    assert end == "end"
    assert calls == [("draw_circle", {"center": [0, 0], "radius": 5})]
    assert said == ["Drawing it.", "Done."]
    first, second = s.requests
    assert first["path"] == "/v1/messages"
    assert first["headers"]["x-api-key"] == "sk-ant-x"
    assert first["headers"]["anthropic-version"] == P.ANTHROPIC_VERSION
    assert "fallbacks" not in first["body"]            # not Anthropic's own host
    assert first["body"]["tools"][0]["input_schema"] == TOOLS[0]["parameters"]
    assert first["body"]["model"] == "claude-opus-5-5"
    messages = second["body"]["messages"]
    # the assistant turn goes back exactly as it came, thinking block and all
    assert messages[1]["content"][0] == {"type": "thinking", "thinking": "",
                                         "signature": "sig"}
    (result,) = messages[2]["content"]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_1"
    assert json.loads(result["content"]) == {"created": ["2A"], "revision": 3}


def test_anthropic_errors_and_pictures(server):
    s = server([_anthropic_tool_use("capture_view", {}),
                _anthropic_tool_use("draw_circle", {}, uid="toolu_2"),
                _anthropic_text("ok")])
    picture = Image(b"\x89PNG fake", "view from (0, 0) to (10, 10)")
    results = iter([picture, {"error": "the radius must be positive"}])
    P.run_turn(ANTHROPIC, "m", "k", [], "look", lambda n, a: next(results),
               tools=TOOLS, base_url=s.url)
    image_result = s.requests[1]["body"]["messages"][-1]["content"][0]
    kinds = [c["type"] for c in image_result["content"]]
    assert kinds == ["image", "text"]
    assert image_result["content"][0]["source"]["media_type"] == "image/png"
    error_result = s.requests[2]["body"]["messages"][-1]["content"][0]
    assert error_result["is_error"] is True


def test_anthropic_own_host_asks_for_fallbacks(monkeypatch):
    sent = {}

    def post(url, headers, body):
        sent.update(url=url, headers=headers, body=body)
        return {"content": [], "stop_reason": "end_turn"}
    P.anthropic_complete(ANTHROPIC, "claude-opus-5-5", "k", "sys", [], [],
                         post=post)
    assert sent["url"] == "https://api.anthropic.com/v1/messages"
    assert sent["body"]["fallbacks"] == "default"
    assert sent["headers"]["anthropic-beta"] == "server-side-fallback-2026-07-01"


def _openai_tool_call(name, arguments, cid="call_1"):
    return 200, {"choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None, "tool_calls": [
            {"id": cid, "type": "function",
             "function": {"name": name, "arguments": arguments}}]}}]}


def _openai_text(text):
    return 200, {"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": text}}]}


def test_openai_round_trip_with_a_picture(server):
    s = server([_openai_tool_call("capture_view", "{}"),
                _openai_tool_call("draw_circle", '{"radius": 2}', "call_2"),
                _openai_text("Listo.")])
    seen = []

    def execute(name, args):
        seen.append((name, args))
        return Image(b"png", "view") if name == "capture_view" else {"ok": 1}

    end = P.run_turn(OPENAI, "gpt-x", "sk-o", [], "hola", execute,
                     tools=TOOLS, base_url=s.url)
    assert end == "end" and seen[1] == ("draw_circle", {"radius": 2})
    first = s.requests[0]
    assert first["path"] == "/chat/completions"
    assert first["headers"]["authorization"] == "Bearer sk-o"
    assert first["body"]["messages"][0]["role"] == "system"
    assert first["body"]["tools"][0]["function"]["name"] == "draw_circle"
    messages = s.requests[1]["body"]["messages"]
    tool_msg = next(m for m in messages if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call_1"
    picture = messages[-1]
    assert picture["role"] == "user"
    assert picture["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,")


def test_a_local_model_without_eyes_gets_no_picture_and_no_key(server):
    s = server([_openai_tool_call("capture_view", "{}"), _openai_text("ok")])
    P.run_turn(P.PROVIDERS["ollama"], "llama3.1", "", [], "look",
               lambda n, a: Image(b"png", "view"), tools=TOOLS, base_url=s.url)
    assert "authorization" not in s.requests[0]["headers"]
    messages = s.requests[1]["body"]["messages"]
    assert not any(isinstance(m["content"], list) for m in messages)
    assert "cannot receive pictures" in messages[-1]["content"]


def test_arguments_that_are_not_json_go_back_as_an_error(server):
    s = server([_openai_tool_call("draw_circle", "{radius: 2"),
                _openai_text("sorry")])
    ran = []
    P.run_turn(OPENAI, "m", "k", [], "x", lambda n, a: ran.append(n),
               tools=TOOLS, base_url=s.url)
    assert ran == []
    tool_msg = next(m for m in s.requests[1]["body"]["messages"]
                    if m["role"] == "tool")
    assert "not valid JSON" in tool_msg["content"]


def test_provider_errors_say_what_the_provider_said(server):
    s = server([(401, {"type": "error", "error": {
        "type": "authentication_error", "message": "invalid x-api-key"}})])
    with pytest.raises(P.ProviderError) as info:
        P.run_turn(ANTHROPIC, "m", "bad", [], "x", lambda n, a: {},
                   tools=TOOLS, base_url=s.url)
    assert info.value.status == 401 and "invalid x-api-key" in str(info.value)
    with pytest.raises(P.ProviderError) as info:
        P.run_turn(OPENAI, "m", "k", [], "x", lambda n, a: {}, tools=TOOLS,
                   base_url="http://127.0.0.1:9")            # nobody there
    assert info.value.status == 0 and "cannot reach" in str(info.value)


def test_stop_and_the_step_limit(server):
    s = server([_openai_tool_call("draw_circle", "{}")] * 3)
    flag = {"stop": False}

    def execute(name, args):
        flag["stop"] = True                 # the user pressed Stop meanwhile
        return {}
    assert P.run_turn(OPENAI, "m", "k", [], "x", execute, tools=TOOLS,
                      base_url=s.url, stopped=lambda: flag["stop"]) == "stopped"
    assert len(s.requests) == 1
    s = server([_openai_tool_call("draw_circle", "{}")] * 3)
    assert P.run_turn(OPENAI, "m", "k", [], "x", lambda n, a: {}, tools=TOOLS,
                      base_url=s.url, max_steps=3) == "steps"


def test_a_turn_through_the_real_tools_is_one_undo(server, qapp):
    from core.ai import tools as ai
    from views.main_window import MainWindow

    win = MainWindow()
    win.new_document()
    try:
        s = server([_anthropic_tool_use("draw_circle",
                                        {"center": [1, 1], "radius": 3}),
                    _anthropic_tool_use("draw_line",
                                        {"points": [[0, 0], [5, 5]]}, "toolu_2"),
                    _anthropic_text("Done.")])
        depth = len(win.history._undo)
        with ai.Turn(win):
            P.run_turn(ANTHROPIC, "m", "k", [], "draw",
                       lambda n, a: ai.call(win, n, a), base_url=s.url)
        assert len(win.history._undo) == depth + 1
        assert sorted(e.dxftype() for e in win.document.modelspace()) \
            == ["CIRCLE", "LINE"]
        # the real catalogue went to the model
        names = [t["name"] for t in s.requests[0]["body"]["tools"]]
        assert "draw_circle" in names and "erase_entities" in names
    finally:
        win.document.dirty = False
        win.close()
