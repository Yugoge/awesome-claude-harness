"""Schema registry loader for the harness ``schemas/`` directory.

Reads schemas/registry.json once and lazily loads referenced schema files.
All file reads are UTF-8 via pathlib.Path. Cached in module-level dict.

WS1: the schemas dir is resolved via the shared claude_home resolver (falling
back to this file's own ../../schemas location) so a fresh non-root clone never
depends on the author literal /root/.claude.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_home  # noqa: E402  (shared WS1 harness-home resolver)


def _schemas_dir() -> Path:
    """Resolve the harness ``schemas/`` dir via claude_home, else this file's
    sibling ``../../schemas`` (hooks/lib/ -> harness home -> schemas/)."""
    home = claude_home.resolve()
    if home is not None:
        return home / 'schemas'
    return Path(__file__).resolve().parent.parent.parent / 'schemas'


SCHEMAS_DIR = _schemas_dir()
REGISTRY_PATH = SCHEMAS_DIR / 'registry.json'

_CACHE: dict[str, dict] = {}
_REGISTRY_LOADED = False


def _load_registry_index() -> dict[str, str]:
    """Read registry.json and return the {schema_name: filename} index.

    Returns an empty dict on any failure (missing file, bad JSON, missing
    'schemas' key). Callers must treat absence as a non-fatal contract
    short-circuit signal.
    """
    try:
        raw = REGISTRY_PATH.read_text(encoding='utf-8')
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}
    schemas = data.get('schemas')
    if not isinstance(schemas, dict):
        return {}
    return {k: v for k, v in schemas.items() if isinstance(v, str)}


def _load_all_schemas() -> None:
    """Populate the module cache with every registry-referenced schema.

    Idempotent — repeat calls after the first successful load are no-ops.
    A schema file that fails to parse is silently skipped; callers asking
    for that name via :func:`get_schema` will receive ``None``.
    """
    global _REGISTRY_LOADED
    if _REGISTRY_LOADED:
        return
    index = _load_registry_index()
    for name, filename in index.items():
        path = SCHEMAS_DIR / filename
        try:
            _CACHE[name] = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            # Leave the slot unpopulated; get_schema() returns None.
            continue
    _REGISTRY_LOADED = True


def load_registry() -> dict[str, dict]:
    """Public API: return {schema_name: schema_object} for all loaded schemas."""
    _load_all_schemas()
    return dict(_CACHE)


def get_schema(name: str) -> Optional[dict]:
    """Return the parsed schema for ``name`` or ``None`` if missing."""
    _load_all_schemas()
    return _CACHE.get(name)
