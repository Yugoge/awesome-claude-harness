#!/usr/bin/env python3
"""Load a standalone sibling script as a module by path, and hash bytes.

``scripts/close-route-select.py``, ``scripts/late-repair-controller.py`` and
``scripts/check-late-repair-provenance.py`` are standalone CLI scripts, not an
importable package, so each one loads other sibling scripts by exec'ing the
sibling's source into a fresh module object rather than a package import.
Before this module existed, that loader (and the small ``sha256_bytes``
wrapper two of the three also needed) was copy-pasted byte-for-byte into all
three files. This module is the single canonical implementation; callers
import it instead of keeping their own copy.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import ModuleType


def load_sibling_module(name: str, caller_file: str) -> ModuleType:
    """Load ``name`` (a sibling script filename) as a fresh module.

    ``caller_file`` is the loading script's own ``__file__``; the sibling is
    resolved relative to that file's directory, not this shared module's.
    """
    path = Path(caller_file).with_name(name)
    module = ModuleType(name.replace("-", "_").replace(".py", ""))
    module.__file__ = str(path)
    source = path.read_bytes()
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
