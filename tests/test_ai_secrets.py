# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The assistant's API keys live in the keyring, or in a 0600 file.

The keyring test runs libsecret for real, against a throwaway GNOME
Keyring on a private session bus (dbus-run-session): the user's own
keyring is never touched.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from core.ai import secrets

REPO = Path(__file__).resolve().parents[1]


class _DictKeyring:
    def __init__(self, fail=False):
        self.keys, self.fail = {}, fail

    def store(self, provider, secret):
        if self.fail:
            raise secrets.SecretsError("locked")
        self.keys[provider] = secret

    def load(self, provider):
        if self.fail:
            raise secrets.SecretsError("locked")
        return self.keys.get(provider)

    def forget(self, provider):
        self.keys.pop(provider, None)


@pytest.fixture
def stores(tmp_path, monkeypatch):
    def use(keyring):
        store = secrets._FileStore(tmp_path / "ai-keys.json")
        monkeypatch.setattr(secrets, "_override", (keyring, store))
        return store
    return use


def test_the_file_is_only_the_users(stores):
    store = stores(None)
    assert secrets.store("openai", "sk-1") == secrets.FILE
    assert secrets.load("openai") == "sk-1"
    if os.name == "posix":
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    secrets.forget("openai")
    assert secrets.load("openai") is None


def test_a_locked_keyring_falls_back_to_the_file_and_says_so(stores):
    stores(_DictKeyring(fail=True))
    assert secrets.store("anthropic", "sk-ant") == secrets.FILE
    assert secrets.load("anthropic") == "sk-ant"


def test_the_keyring_wins_and_the_key_lives_in_one_place(stores):
    keyring = _DictKeyring()
    store = stores(keyring)
    store.store("openai", "old-in-file")
    assert secrets.store("openai", "sk-new") == secrets.KEYRING
    assert keyring.keys == {"openai": "sk-new"}
    assert store.load("openai") is None            # the old copy is gone
    assert secrets.load("openai") == "sk-new"


_SCRIPT = """
from core.ai import secrets
k = secrets._LibSecret("session")
k.store("openai", "sk-test-\\u00f1")
print("LOADED", k.load("openai"))
k.forget("openai")
print("AFTER", k.load("openai"))
"""


@pytest.mark.skipif(not sys.platform.startswith("linux")
                    or not shutil.which("dbus-run-session")
                    or not shutil.which("gnome-keyring-daemon"),
                    reason="needs dbus-run-session and gnome-keyring")
def test_libsecret_against_a_private_keyring(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin",
           "XDG_DATA_HOME": str(home / "data"),
           "XDG_RUNTIME_DIR": str(runtime), "PYTHONPATH": str(REPO),
           "LANG": "C.UTF-8"}
    shell = ('echo -n "" | gnome-keyring-daemon --unlock --components=secrets '
             '>/dev/null 2>&1; sleep 0.5; "$PY" -c "$SCRIPT"')
    env.update(PY=sys.executable, SCRIPT=_SCRIPT)
    out = subprocess.run(["dbus-run-session", "--", "sh", "-c", shell],
                         env=env, cwd=REPO, capture_output=True, text=True,
                         timeout=60)
    lines = [ln for ln in out.stdout.splitlines()
             if ln.startswith(("LOADED", "AFTER"))]
    assert lines == ["LOADED sk-test-ñ", "AFTER None"], out.stderr[-2000:]
