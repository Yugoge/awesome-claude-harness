#!/usr/bin/env python3
"""Thin shim — delegates to hooks/lib/runtime_guard/_core.py.

This file exists for backwards-compatibility with callers that invoke
runtime_guard.py directly as a subprocess (e.g. pretool-bash-safety.sh).
Python import machinery prefers the runtime_guard/ package over this module,
so `import lib.runtime_guard` always loads the package's __init__.py.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_core_path = os.path.join(_HERE, "runtime_guard", "_core.py")

if __name__ == "__main__":
    # Replace this process with _core.py, passing all args and environment through.
    os.execv(sys.executable, [sys.executable, _core_path] + sys.argv[1:])
