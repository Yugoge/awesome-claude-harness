"""Shared loader for the Task-A (R1 reverse-blast-radius) unit tests.

scripts/graphify-enrich.py is hyphenated and not importable by name, so load it
via importlib. Cached so repeated calls return the same module object.
"""

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_CACHED = None


def load_enrich():
    """Import and return scripts/graphify-enrich.py as a module (cached)."""
    global _CACHED
    if _CACHED is None:
        spec = importlib.util.spec_from_file_location(
            "graphify_enrich_under_test", _SCRIPTS / "graphify-enrich.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _CACHED = mod
    return _CACHED


def repo_root() -> Path:
    return _REPO_ROOT
