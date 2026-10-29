# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""Where the assistant's API keys are kept: never in QSettings, never in
a drawing.

* Linux: the desktop's keyring (GNOME Keyring, KWallet...) through the
  Secret Service, by libsecret. PySide6's QtDBus cannot marshal the
  structures that protocol takes, so libsecret is called with ctypes --
  it is on every desktop and in the Flatpak runtime, and nothing new is
  installed.
* Windows: the Credential Manager, through ctypes.
* Anywhere else, or when the keyring cannot be reached: a file only the
  user can read (0600), and :func:`store` says so, for the dialog to warn.

Keys are looked up by provider id ("openai", "anthropic"...).
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path
from typing import Optional

#: What the keyring calls IngeCAD's secrets.
SCHEMA_NAME = b"org.ingecad.IngeCAD.ApiKey"

KEYRING, WINDOWS, FILE = "keyring", "windows", "file"


class SecretsError(Exception):
    pass


# -- Linux: libsecret -----------------------------------------------------------

class _Attr(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p), ("type", ctypes.c_int)]


class _Schema(ctypes.Structure):
    _fields_ = ([("name", ctypes.c_char_p), ("flags", ctypes.c_int),
                 ("attributes", _Attr * 32), ("reserved", ctypes.c_int)]
                + [(f"reserved{i}", ctypes.c_void_p) for i in range(1, 8)])


class _GError(ctypes.Structure):
    _fields_ = [("domain", ctypes.c_uint32), ("code", ctypes.c_int),
                ("message", ctypes.c_char_p)]


class _LibSecret:
    """secret_password_{store,lookup,clear}v_sync, one attribute: the
    provider. ``collection`` None is the user's default keyring; tests use
    "session", which lives in memory and never asks to be unlocked."""

    def __init__(self, collection: Optional[str] = None) -> None:
        self.glib = ctypes.CDLL("libglib-2.0.so.0")
        self.lib = ctypes.CDLL("libsecret-1.so.0")
        self.collection = collection.encode() if collection else None
        self.schema = _Schema()
        self.schema.name = SCHEMA_NAME
        self.schema.attributes[0] = _Attr(b"provider", 0)   # a string
        g, s = self.glib, self.lib
        g.g_hash_table_new.restype = ctypes.c_void_p
        g.g_hash_table_new.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        g.g_hash_table_insert.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                          ctypes.c_char_p]
        g.g_hash_table_unref.argtypes = [ctypes.c_void_p]
        g.g_error_free.argtypes = [ctypes.c_void_p]
        perr = ctypes.POINTER(ctypes.POINTER(_GError))
        schema = ctypes.POINTER(_Schema)
        s.secret_password_storev_sync.argtypes = [
            schema, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
            ctypes.c_char_p, ctypes.c_void_p, perr]
        s.secret_password_storev_sync.restype = ctypes.c_int
        s.secret_password_lookupv_sync.argtypes = [
            schema, ctypes.c_void_p, ctypes.c_void_p, perr]
        s.secret_password_lookupv_sync.restype = ctypes.c_void_p
        s.secret_password_clearv_sync.argtypes = [
            schema, ctypes.c_void_p, ctypes.c_void_p, perr]
        s.secret_password_clearv_sync.restype = ctypes.c_int
        s.secret_password_free.argtypes = [ctypes.c_void_p]

    def _call(self, provider: str, fn, *args):
        g = self.glib
        table = g.g_hash_table_new(ctypes.cast(g.g_str_hash, ctypes.c_void_p),
                                   ctypes.cast(g.g_str_equal, ctypes.c_void_p))
        key, value = b"provider", provider.encode()   # alive for the call
        g.g_hash_table_insert(table, key, value)
        error = ctypes.POINTER(_GError)()
        try:
            result = fn(ctypes.byref(self.schema), table, *args,
                        ctypes.byref(error))
        finally:
            g.g_hash_table_unref(table)
        if error:
            message = (error.contents.message or b"").decode("utf-8", "replace")
            g.g_error_free(error)
            raise SecretsError(message)
        return result

    def store(self, provider: str, secret: str) -> None:
        ok = self._call(provider, self.lib.secret_password_storev_sync,
                        self.collection,
                        f"IngeCAD: {provider} API key".encode(),
                        secret.encode(), None)
        if not ok:
            raise SecretsError("the keyring did not store the key")

    def load(self, provider: str) -> Optional[str]:
        pointer = self._call(provider, self.lib.secret_password_lookupv_sync,
                             None)
        if not pointer:
            return None
        try:
            return ctypes.string_at(pointer).decode("utf-8")
        finally:
            self.lib.secret_password_free(pointer)

    def forget(self, provider: str) -> None:
        self._call(provider, self.lib.secret_password_clearv_sync, None)


# -- Windows: the Credential Manager -------------------------------------------

class _WinCred:
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    def __init__(self) -> None:
        from ctypes import wintypes

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                        ("TargetName", wintypes.LPWSTR),
                        ("Comment", wintypes.LPWSTR),
                        ("LastWritten", wintypes.FILETIME),
                        ("CredentialBlobSize", wintypes.DWORD),
                        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                        ("Persist", wintypes.DWORD),
                        ("AttributeCount", wintypes.DWORD),
                        ("Attributes", ctypes.c_void_p),
                        ("TargetAlias", wintypes.LPWSTR),
                        ("UserName", wintypes.LPWSTR)]

        self.CREDENTIAL = CREDENTIAL
        self.api = ctypes.WinDLL("advapi32", use_last_error=True)
        pcred = ctypes.POINTER(CREDENTIAL)
        self.api.CredWriteW.argtypes = [pcred, wintypes.DWORD]
        self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                       wintypes.DWORD, ctypes.POINTER(pcred)]
        self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                         wintypes.DWORD]
        self.api.CredFree.argtypes = [ctypes.c_void_p]

    @staticmethod
    def _target(provider: str) -> str:
        return f"IngeCAD/{provider}"

    def store(self, provider: str, secret: str) -> None:
        blob = secret.encode("utf-8")
        cred = self.CREDENTIAL()
        cred.Type = self.CRED_TYPE_GENERIC
        cred.TargetName = self._target(provider)
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(ctypes.create_string_buffer(blob),
                                          ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = "IngeCAD"
        if not self.api.CredWriteW(ctypes.byref(cred), 0):
            raise SecretsError(f"CredWrite failed ({ctypes.get_last_error()})")

    def load(self, provider: str) -> Optional[str]:
        pcred = ctypes.POINTER(self.CREDENTIAL)()
        if not self.api.CredReadW(self._target(provider),
                                  self.CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
            if ctypes.get_last_error() == self.ERROR_NOT_FOUND:
                return None
            raise SecretsError(f"CredRead failed ({ctypes.get_last_error()})")
        try:
            c = pcred.contents
            return ctypes.string_at(c.CredentialBlob,
                                    c.CredentialBlobSize).decode("utf-8")
        finally:
            self.api.CredFree(pcred)

    def forget(self, provider: str) -> None:
        if not self.api.CredDeleteW(self._target(provider),
                                    self.CRED_TYPE_GENERIC, 0):
            if ctypes.get_last_error() != self.ERROR_NOT_FOUND:
                raise SecretsError(f"CredDelete failed ({ctypes.get_last_error()})")


# -- the last resort: a file only the user can read ----------------------------

class _FileStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        if path is None:
            from core.paths import user_config_dir

            path = user_config_dir() / "ai-keys.json"
        self.path = Path(path)

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, keys: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # created 0600 from the start: never a moment readable by others
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(keys, handle)
        if os.name == "posix":
            os.chmod(self.path, 0o600)

    def store(self, provider: str, secret: str) -> None:
        keys = self._read()
        keys[provider] = secret
        self._write(keys)

    def load(self, provider: str) -> Optional[str]:
        return self._read().get(provider)

    def forget(self, provider: str) -> None:
        keys = self._read()
        if keys.pop(provider, None) is not None:
            self._write(keys)


# -- the API ---------------------------------------------------------------------

_override = None    # tests: (keyring backend or None, file store)


def _backends():
    """(name, backend) in the order they are tried."""
    if _override is not None:
        keyring, store = _override
        return ([(KEYRING, keyring)] if keyring is not None else []) \
            + [(FILE, store)]
    out = []
    try:
        if sys.platform.startswith("win"):
            out.append((WINDOWS, _WinCred()))
        elif sys.platform.startswith("linux"):
            out.append((KEYRING, _LibSecret()))
    except OSError:                       # the library is not there
        pass
    out.append((FILE, _FileStore()))
    return out


def store(provider: str, secret: str) -> str:
    """Keep ``secret`` for ``provider``; returns where it went (KEYRING,
    WINDOWS or FILE -- FILE means the keyring failed: warn the user)."""
    last = None
    for name, backend in _backends():
        try:
            backend.store(provider, secret)
        except SecretsError as exc:
            last = exc
            continue
        # the key lives in one place only: an older copy elsewhere goes
        for other_name, other in _backends():
            if other_name != name:
                try:
                    other.forget(provider)
                except SecretsError:
                    pass
        return name
    raise SecretsError(str(last) if last else "nowhere to keep the key")


def load(provider: str) -> Optional[str]:
    for _name, backend in _backends():
        try:
            secret = backend.load(provider)
        except SecretsError:
            continue
        if secret:
            return secret
    return None


def forget(provider: str) -> None:
    for _name, backend in _backends():
        try:
            backend.forget(provider)
        except SecretsError:
            pass
