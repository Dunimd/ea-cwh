#!/usr/bin/env python3

# Copyright © 2025-2026 Wenze Wei. All Rights Reserved.
#
# This file is part of Encre.
# The Encre project belongs to the Dunimd Team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# DISCLAIMER: Users must comply with applicable AI regulations.
# Non-compliance may result in service termination or legal liability.

"""ea-cwh — the Encre Agent plugin market central index.

This package carries exactly one piece of data: ``catalog.json``, the
authoritative list of every plugin published to the central repository.
It is regenerated and re-published by the registry repository's CI on
each merge; nobody hand-edits the shipped file.

The market backend never talks to the network to render the store: it
upgrades this package on a schedule (``pip install -U ea-cwh``) and then
reads the bundled catalog locally through the small stdlib-only API
below.  A failed upgrade simply leaves the last known-good index in
place.

Entry contract (see :func:`validate_catalog`):

* ``name`` is the plugin's manifest name (its registry identity).
* ``display_name`` is a short human-friendly name shown to users — the
  agent and the installer keep identifying the plugin by ``name`` alone.
* ``pypi_package`` is the PyPI distribution to install and MUST carry the
  reserved namespace prefixes (``ea-plugin-``/``ea-tool-``/``ea-skill-``).
* ``version`` is pinned — installs always resolve to exactly this version.
* ``artifacts`` maps distribution file names to their ``sha256`` digest so
  the installer can verify what PyPI handed back before any code runs.
* ``tier`` is ``user`` (community) or ``system-default`` (the vendor
  pipeline) — it decides the activation gate after install.
* ``min_encre_version`` is the oldest Encre Agent release the plugin
  supports (what the manifest called ``min_ea_version``/``engines.encre``).
* ``icon`` is a short render token — a lucide icon name, a single emoji,
  or a file name inside the plugin wheel's ``ui/`` assets — never binary
  data; bitmaps always travel in the plugin wheel, not in this index.
* ``published_at`` is the ISO-8601 UTC stamp of the PyPI upload.
* ``yanked`` is a boolean; yanked entries never surface as updates.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

__version__ = "0.1.0"

#: Bumped only on breaking changes to the entry schema below.
SCHEMA_VERSION = 1

#: Reserved PyPI namespaces for central-repository plugin distributions:
#: ea-plugin- is the community prefix; ea-tool-/ea-skill- are the vendor
#: namespaces the Encre build pipeline publishes official packages under.
RESERVED_PREFIXES = ("ea-plugin-", "ea-tool-", "ea-skill-")

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^\d+[!+.a-zA-Z0-9]*$")  # PEP 440-ish sanity check

_CATALOG_FILE = Path(__file__).resolve().parent / "catalog.json"


def catalog_path() -> Path:
    """Absolute path of the bundled ``catalog.json``."""
    return _CATALOG_FILE


def load_raw() -> dict[str, Any]:
    """Parse and return the whole catalog document.

    Returns:
        The raw document: ``{"schema_version", "generated_at", "registry",
        "plugins": [...]}``.

    Raises:
        FileNotFoundError: the data file is missing from the wheel.
        json.JSONDecodeError: the shipped catalog is corrupt.
    """
    with _CATALOG_FILE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def catalog() -> dict[str, Any]:
    """Return the validated catalog document.

    Raises:
        ValueError: the document violates the entry schema (message lists
            every violation found).
    """
    doc = load_raw()
    problems = validate_catalog(doc)
    if problems:
        raise ValueError("invalid market catalog: " + "; ".join(problems))
    return doc


def plugins(*, include_yanked: bool = False) -> list[dict[str, Any]]:
    """Return catalog entries, yanked ones dropped unless requested."""
    entries = load_raw().get("plugins") or []
    if include_yanked:
        return list(entries)
    return [e for e in entries if not e.get("yanked")]


def get(name: str) -> dict[str, Any] | None:
    """Look one entry up by plugin manifest name (None when absent)."""
    for entry in load_raw().get("plugins") or []:
        if entry.get("name") == name:
            return entry
    return None


def by_pypi_package(pypi_package: str) -> dict[str, Any] | None:
    """Look one entry up by its PyPI distribution name."""
    for entry in load_raw().get("plugins") or []:
        if entry.get("pypi_package") == pypi_package:
            return entry
    return None


def index_version() -> str:
    """Version of this ea-cwh distribution (the index build stamp).

    Reads installed metadata first so a stale import path cannot masquerade
    as the live index; falls back to ``__version__`` in editable checkouts.
    """
    try:
        from importlib.metadata import version

        return version("ea-cwh")
    except Exception:
        return __version__


def validate_catalog(doc: Any) -> list[str]:
    """Check a catalog document against the entry schema.

    Args:
        doc: The parsed document to check.

    Returns:
        A list of human-readable violations; empty means the document is
        safe to serve to the market.
    """
    problems: list[str] = []
    if not isinstance(doc, dict):
        return ["catalog document must be a JSON object"]

    if doc.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"unsupported schema_version {doc.get('schema_version')!r}")

    entries = doc.get("plugins")
    if not isinstance(entries, list):
        problems.append("'plugins' must be a list")
        return problems

    seen_names: set[str] = set()
    seen_pkgs: set[str] = set()
    for i, entry in enumerate(entries):
        where = f"plugins[{i}]"
        if not isinstance(entry, dict):
            problems.append(f"{where} must be an object")
            continue
        name = entry.get("name")
        pkg = entry.get("pypi_package")
        version = entry.get("version")
        if not isinstance(name, str) or not name.strip():
            problems.append(f"{where}.name is required")
            continue
        where = f"plugins[{i}] ({name})"
        if name in seen_names:
            problems.append(f"{where}: duplicate plugin name")
        seen_names.add(name)
        if not isinstance(pkg, str) or not pkg.startswith(RESERVED_PREFIXES):
            problems.append(f"{where}.pypi_package must start with one of {RESERVED_PREFIXES}")
        else:
            if pkg in seen_pkgs:
                problems.append(f"{where}: duplicate pypi_package {pkg}")
            seen_pkgs.add(pkg)
        if not isinstance(version, str) or not _VERSION_RE.match(version):
            problems.append(f"{where}.version must be a pinned PEP 440 string")
        for key in ("description", "author", "license", "homepage", "repository", "docs", "email", "icon"):
            value = entry.get(key, "")
            if not isinstance(value, str):
                problems.append(f"{where}.{key} must be a string")
        # ``icon`` is a render token (lucide name / single emoji / ui/ asset
        # file name), not a bitmap — the wheel carries the binary.  A longer
        # value can only be someone stuffing data into the index.
        icon = entry.get("icon", "")
        if isinstance(icon, str) and len(icon) > 128:
            problems.append(
                f"{where}.icon must be a short render token (<=128 chars); "
                "binary icons belong in the plugin wheel's ui/ assets")
        # ``display_name`` is the user-facing label; "short and easy to
        # read" is part of the contract, so the index caps its length.
        display_name = entry.get("display_name", "")
        if not isinstance(display_name, str):
            problems.append(f"{where}.display_name must be a string")
        elif len(display_name) > 64:
            problems.append(f"{where}.display_name must stay short (<=64 chars)")
        tier = entry.get("tier", "user")
        if tier not in ("user", "system-default"):
            problems.append(f"{where}.tier must be 'user' or 'system-default'")
        min_ver = entry.get("min_encre_version", "")
        if not isinstance(min_ver, str) or (min_ver and not _VERSION_RE.match(min_ver)):
            problems.append(f"{where}.min_encre_version must be a PEP 440 version string")
        if not isinstance(entry.get("published_at", ""), str):
            problems.append(f"{where}.published_at must be a string")
        # A truthy non-bool (e.g. the string "false") would silently flip a
        # live entry into the yanked bucket, so the type is enforced hard.
        if not isinstance(entry.get("yanked", False), bool):
            problems.append(f"{where}.yanked must be a boolean")
        for key in ("tags", "permissions"):
            value = entry.get(key, [])
            if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                problems.append(f"{where}.{key} must be a list of strings")
        provides = entry.get("provides", {})
        if not isinstance(provides, dict) or any(
            not isinstance(items, list) or any(not isinstance(i, str) for i in items)
            for items in provides.values()
        ):
            problems.append(f"{where}.provides must map surface names to lists of strings")
        artifacts = entry.get("artifacts")
        if not isinstance(artifacts, dict) or not artifacts:
            problems.append(f"{where}.artifacts must be a non-empty object")
        else:
            for fname, meta in artifacts.items():
                if not isinstance(meta, dict) or not _SHA256_RE.match(str(meta.get("sha256", ""))):
                    problems.append(f"{where}.artifacts[{fname}].sha256 must be 64 hex chars")
    return problems
