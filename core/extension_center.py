# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeCAD contributors.
"""The extension center: the catalog, and installing what it lists.

Ported from IngeTrazo's extension manager (same author, same rules). The
catalog is a ``catalog.json`` (format 1) beside a ``reviewed.toml`` in the
``ingelibre/ingecad-extensions`` repository; an entry names a ``download``
(an HTTPS ``.zip``) and its ``sha256``, and nothing is installed whose bytes
do not hash to it. ``reviewed.toml`` maps an id to the ``sha256`` someone
read: an extension is *Reviewed* only while the catalog's digest is that
one -- a new version is *Community* again until it is read.

An IngeCAD extension is a plugin (docs/plugins.md): a folder holding an
``__init__.py`` with a ``PLUGIN`` spec. It is installed into
:func:`core.plugins.user_plugins_dir` under its catalog id, with an
``extension.json`` beside the code that marks the folder as the center's
own: only such a folder is ever updated or deleted here. A folder the user
copied by hand is listed, never touched.

Every install is staged in a dot-folder inside the plugins folder (the
loader skips dot names) and moved into place in one rename, so a failure
at any point leaves the previous state exactly as it was.

This module is headless and blocking: the GUI calls it from a worker
thread (views/extensions_panel.py).
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import shutil
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Optional

from core import plugins
from core.i18n import tr
from core.version import __version__

#: Where the catalog lives. ``INGECAD_EXTENSIONS_BASE`` points the center at
#: another copy of the repository (a fork, or a local checkout as
#: ``file:///path``) -- for whoever maintains the catalog, not for users.
DEFAULT_BASE = ("https://raw.githubusercontent.com/ingelibre/"
                "ingecad-extensions/main")
CATALOG_FILE = "catalog.json"
REVIEWED_FILE = "reviewed.toml"
TIMEOUT = 20
MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_FILES = 2000
MAX_EXTRACTED_BYTES = 128 * 1024 * 1024
METADATA = "extension.json"
USER_AGENT = f"IngeCAD/{__version__}"

#: The categories a catalog entry may carry, in the order the filter lists
#: them. English labels, translated where they are shown.
TAGS = {
    "topography": "Topography",
    "civil": "Civil",
    "architecture": "Architecture",
    "structures": "Structures",
    "gis": "GIS",
    "import-export": "Import / export",
    "drawing": "Drawing",
    "annotation": "Annotation",
    "productivity": "Productivity",
    "education": "Education",
    "other": "Other",
}

# An id is a folder name and a module suffix (``ingecad_plugin_<id>``).
_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")

log = logging.getLogger("ingecad.extensions")


class ExtensionError(Exception):
    """A catalog or installation step could not be completed safely."""


@dataclass(frozen=True)
class Extension:
    id: str
    version: str
    author: str
    license: str
    repository: str
    download: str
    sha256: str
    minimum_version: str
    name: dict
    summary: dict
    tags: tuple = ()
    author_url: str = ""
    screenshot: Optional[str] = None


@dataclass(frozen=True)
class CatalogSnapshot:
    extensions: list
    reviewed: dict
    fetched_at: str
    from_cache: bool


# -- where --------------------------------------------------------------------

def catalog_base() -> str:
    return (os.environ.get("INGECAD_EXTENSIONS_BASE") or DEFAULT_BASE).rstrip("/")


def _root(root: Optional[Path]) -> Path:
    return Path(root) if root is not None else plugins.user_plugins_dir()


def catalog_cache_path(root: Optional[Path] = None) -> Path:
    """The last catalog that validated, for the next time there is no
    network. Beside the plugins folder, in the user's config."""
    return _root(root).parent / "extension-catalog.json"


# -- fetching -----------------------------------------------------------------

def _get(url: str, limit: int) -> bytes:
    """The bytes at ``url``, at most ``limit``. HTTPS only -- except the
    ``file://`` catalog a maintainer points ``INGECAD_EXTENSIONS_BASE`` at."""
    local = url.startswith("file://") and catalog_base().startswith("file://")
    if not (url.startswith("https://") or local):
        raise ExtensionError(tr("Refusing a non-HTTPS address: {url}", url=url))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    kwargs = {}
    if not local:
        from core.tls import https_context

        kwargs["context"] = https_context()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, **kwargs) as response:
            if not local and not response.geturl().startswith("https://"):
                raise ExtensionError(
                    tr("The download redirected to a non-HTTPS address."))
            data = response.read(limit + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ExtensionError(tr("Could not download {url}: {error}", url=url, error=exc)) from exc
    if len(data) > limit:
        raise ExtensionError(tr("The downloaded file is too large."))
    return data


# -- the catalog ----------------------------------------------------------------

def _text_map(value, field: str, ident: str) -> dict:
    if not isinstance(value, dict) or not value or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ExtensionError(f"Extension {ident!r} has an invalid {field}.")
    return dict(value)


def _parse_extension(raw) -> Extension:
    if not isinstance(raw, dict):
        raise ExtensionError("Invalid extension entry in the catalog.")
    ident = raw.get("id")
    if not isinstance(ident, str) or not _ID_RE.fullmatch(ident):
        raise ExtensionError("Invalid extension id in the catalog.")
    required = ("version", "author", "license", "repository", "download",
                "sha256", "ingecad")
    if any(not isinstance(raw.get(key), str) or not raw[key] for key in required):
        raise ExtensionError(f"Extension {ident!r} has incomplete catalog metadata.")
    if not _SHA_RE.fullmatch(raw["sha256"]):
        raise ExtensionError(f"Extension {ident!r} has an invalid SHA-256 digest.")
    download = raw["download"]
    if not (download.startswith("https://")
            or (download.startswith("file://")
                and catalog_base().startswith("file://"))):
        raise ExtensionError(f"Extension {ident!r} does not download over HTTPS.")
    tags = raw.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ExtensionError(f"Extension {ident!r} has invalid tags.")
    screenshot = raw.get("screenshot")
    if screenshot is not None and not isinstance(screenshot, str):
        raise ExtensionError(f"Extension {ident!r} has an invalid screenshot.")
    author_url = raw.get("author_url") or ""
    if not isinstance(author_url, str):
        raise ExtensionError(f"Extension {ident!r} has an invalid author_url.")
    return Extension(
        id=ident, version=raw["version"], author=raw["author"],
        license=raw["license"], repository=raw["repository"],
        download=download, sha256=raw["sha256"].lower(),
        minimum_version=raw["ingecad"],
        name=_text_map(raw.get("name"), "name", ident),
        summary=_text_map(raw.get("summary"), "summary", ident),
        tags=tuple(t for t in tags if t in TAGS) or ("other",),
        author_url=author_url, screenshot=screenshot)


def parse_catalog(catalog_data: bytes, reviewed_data: bytes,
                  fetched_at: str = "", from_cache: bool = False) -> CatalogSnapshot:
    import tomllib

    try:
        catalog = json.loads(catalog_data)
        reviewed = tomllib.loads(reviewed_data.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:      # JSON and TOML errors alike
        raise ExtensionError(tr("The extension catalog is invalid: {error}", error=exc)) from exc
    if not isinstance(catalog, dict) or catalog.get("format") != 1:
        raise ExtensionError(tr("Unsupported extension catalog format."))
    raw = catalog.get("extensions")
    if not isinstance(raw, list):
        raise ExtensionError(tr("The extension catalog has no entries."))
    extensions = []
    for entry in raw:
        try:
            extensions.append(_parse_extension(entry))
        except ExtensionError as exc:      # one bad entry hides itself only
            log.warning("skipping a catalog entry: %s", exc)
    ids = [e.id for e in extensions]
    if len(ids) != len(set(ids)):
        raise ExtensionError(tr("The catalog lists the same id twice."))
    if not isinstance(reviewed, dict):
        raise ExtensionError(tr("The reviewed-extension list is invalid."))
    return CatalogSnapshot(extensions, reviewed, fetched_at, from_cache)


def load_cached_catalog(root: Optional[Path] = None) -> Optional[CatalogSnapshot]:
    path = catalog_cache_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return parse_catalog(json.dumps(data["catalog"]).encode("utf-8"),
                             data["reviewed"].encode("utf-8"),
                             str(data["fetched_at"]), True)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError, AttributeError,
            ExtensionError) as exc:
        log.warning("unusable extension catalog cache %s: %s", path, exc)
        return None


def refresh_catalog(root: Optional[Path] = None) -> CatalogSnapshot:
    """Fetch and validate the catalog, and keep a copy for offline use.

    Without network the cached copy is returned (``from_cache``); with no
    cache either, the network error is raised.
    """
    base = catalog_base()
    try:
        catalog_data = _get(f"{base}/{CATALOG_FILE}", MAX_CATALOG_BYTES)
        reviewed_data = _get(f"{base}/{REVIEWED_FILE}", MAX_CATALOG_BYTES)
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        snapshot = parse_catalog(catalog_data, reviewed_data, fetched_at, False)
    except (ExtensionError, OSError) as exc:
        cached = load_cached_catalog(root)
        if cached is not None:
            log.info("using the cached extension catalog: %s", exc)
            return cached
        raise
    path = catalog_cache_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(path.suffix + ".part")
        part.write_text(json.dumps({
            "catalog": json.loads(catalog_data),
            "reviewed": reviewed_data.decode("utf-8"),
            "fetched_at": fetched_at,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        part.replace(path)
    except OSError:
        log.warning("could not cache the extension catalog at %s", path,
                    exc_info=True)
    return snapshot


# -- reading an entry ---------------------------------------------------------------

def _lang(language: str) -> str:
    return language.lower().replace("_", "-").split("-", 1)[0]


def display_name(extension: Extension, language: str) -> str:
    return (extension.name.get(_lang(language)) or extension.name.get("en")
            or next(iter(extension.name.values()), extension.id))


def display_summary(extension: Extension, language: str) -> str:
    return (extension.summary.get(_lang(language)) or extension.summary.get("en")
            or next(iter(extension.summary.values()), ""))


def is_reviewed(extension: Extension, reviewed: dict) -> bool:
    entry = reviewed.get(extension.id)
    return (isinstance(entry, dict)
            and str(entry.get("sha256", "")).lower() == extension.sha256)


def _version_parts(value: str):
    match = re.match(r"^\s*(\d+(?:\.\d+)*)", value or "")
    return tuple(map(int, match.group(1).split("."))) if match else None


def compatible(extension: Extension, current: str = __version__) -> bool:
    """Does this IngeCAD meet the entry's minimum version?"""
    required, have = _version_parts(extension.minimum_version), _version_parts(current)
    if required is None or have is None:
        return False
    width = max(len(required), len(have))
    return (required + (0,) * (width - len(required))
            <= have + (0,) * (width - len(have)))


# -- what is installed --------------------------------------------------------------

def installed_info(ident: str, root: Optional[Path] = None) -> Optional[dict]:
    """The ``extension.json`` of a folder the center installed, else None
    (not installed, or installed by hand)."""
    if not _ID_RE.fullmatch(ident):
        return None
    folder = _root(root) / ident
    if folder.is_symlink() or not folder.is_dir():
        return None
    try:
        data = json.loads((folder / METADATA).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("id") == ident else None


def is_managed(ident: str, root: Optional[Path] = None) -> bool:
    return installed_info(ident, root) is not None


def update_available(extension: Extension, root: Optional[Path] = None) -> bool:
    info = installed_info(extension.id, root)
    return info is not None and info.get("sha256") != extension.sha256


def installation_conflict(ident: str, root: Optional[Path] = None) -> bool:
    """A plugin of that name is there and the center did not put it there."""
    target = _root(root) / ident
    return (target.exists() or target.is_symlink()) and not is_managed(ident, root)


# -- install / uninstall ----------------------------------------------------------------

def install_extension(extension: Extension, root: Optional[Path] = None) -> Path:
    """Download, verify and install (or update) ``extension``; returns its
    folder. Raises :class:`ExtensionError` -- with nothing changed on disk
    -- when anything is wrong: the digest, the archive, the name."""
    if not compatible(extension):
        raise ExtensionError(tr("{id} requires IngeCAD {version} or later.",
                                id=extension.id,
                                version=extension.minimum_version))
    if extension.id in _bundled_ids():
        raise ExtensionError(tr("{id} is the name of a plugin included "
                                "with IngeCAD.", id=extension.id))
    if installation_conflict(extension.id, root):
        raise ExtensionError(tr("A plugin named {id} already exists and was "
                                "not installed by the extension center.",
                                id=extension.id))
    data = _get(extension.download, MAX_DOWNLOAD_BYTES)
    if hashlib.sha256(data).hexdigest() != extension.sha256:
        raise ExtensionError(tr("Checksum mismatch for {id}; nothing was "
                                "installed.", id=extension.id))
    return install_bytes(extension, data, root)


def install_bytes(extension: Extension, data: bytes,
                  root: Optional[Path] = None) -> Path:
    """Unpack verified ``data`` as ``extension`` (the second half of
    :func:`install_extension`)."""
    base = _root(root)
    base.mkdir(parents=True, exist_ok=True)
    target = base / extension.id
    stage = Path(tempfile.mkdtemp(prefix=f".{extension.id}-", dir=base))
    backup = base / f".{extension.id}-backup-{uuid.uuid4().hex}"
    try:
        if zipfile.is_zipfile(io.BytesIO(data)):
            _extract_plugin_zip(data, stage, extension.id)
        elif (urllib.parse.urlsplit(extension.download).path.lower().endswith(".py")
              and data and b"\x00" not in data):
            (stage / "__init__.py").write_bytes(data)   # a one-file plugin
        else:
            raise ExtensionError(tr(
                "{id} did not download a valid ZIP package.", id=extension.id))
        if not (stage / "__init__.py").is_file():
            raise ExtensionError(tr("{id} holds no plugin package.",
                                    id=extension.id))
        (stage / METADATA).write_text(json.dumps({
            "id": extension.id,
            "version": extension.version,
            "sha256": extension.sha256,
            "download": extension.download,
        }, indent=2) + "\n", encoding="utf-8")
        if target.exists():
            target.replace(backup)
        try:
            stage.replace(target)
        except OSError:
            if backup.exists() and not target.exists():
                backup.replace(target)
            raise
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return target


def uninstall_extension(ident: str, root: Optional[Path] = None) -> None:
    """Delete an extension the center installed -- and nothing else."""
    if not is_managed(ident, root):
        raise ExtensionError(tr(
            "{id} is not an extension installed by the extension center.",
            id=ident))
    shutil.rmtree(_root(root) / ident)


def _bundled_ids() -> set:
    folder = plugins.bundled_plugins_dir()
    if not folder.is_dir():
        return set()
    return {p.name for p in folder.iterdir()
            if p.is_dir() and (p / "__init__.py").is_file()}


def _extract_plugin_zip(data: bytes, stage: Path, ident: str) -> None:
    """Unpack the one plugin package of the archive into ``stage``.

    Accepted: one folder with ``__init__.py`` (at any depth -- a GitHub
    archive wraps it in ``<repo>-main/``), the package's files at the top,
    or a single ``<id>.py``. Any absolute path, ``..``, drive letter or
    symlink refuses the whole archive before a byte is written.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (OSError, zipfile.BadZipFile) as exc:
        raise ExtensionError(tr("The extension ZIP file is invalid.")) from exc
    with archive:
        members = [info for info in archive.infolist()
                   if not info.is_dir() and not info.filename.startswith("__MACOSX/")]
        if len(members) > MAX_ARCHIVE_FILES:
            raise ExtensionError(tr("The extension archive has too many files."))
        total = 0
        normalized = []
        for info in members:
            name = info.filename
            path = PurePosixPath(name)
            mode = info.external_attr >> 16
            if ("\\" in name or ":" in name or path.is_absolute()
                    or any(part in ("", ".", "..") for part in path.parts)
                    or stat.S_ISLNK(mode)):
                raise ExtensionError(tr("The extension archive contains an unsafe path."))
            total += info.file_size
            if total > MAX_EXTRACTED_BYTES:
                raise ExtensionError(tr("The unpacked extension is too large."))
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            normalized.append((info, path))

        inits = [path for _info, path in normalized if path.name == "__init__.py"]
        if inits:
            depth = min(len(p.parent.parts) for p in inits)
            roots = {p.parent for p in inits if len(p.parent.parts) == depth}
            if len(roots) > 1:
                named = [r for r in roots if r.name == ident]
                if len(named) != 1:
                    raise ExtensionError(tr(
                        "The ZIP holds more than one top-level plugin package."))
                roots = set(named)
            source = next(iter(roots))
            for info, path in normalized:
                if source.parts and not path.is_relative_to(source):
                    continue
                relative = path.relative_to(source)
                destination = stage.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(info))
            return

        single = [(info, path) for info, path in normalized
                  if path.name == f"{ident}.py"]
        if len(single) != 1:
            raise ExtensionError(tr("The ZIP must hold one plugin package or a "
                                    "Python file named {id}.py.", id=ident))
        (stage / "__init__.py").write_bytes(archive.read(single[0][0]))
