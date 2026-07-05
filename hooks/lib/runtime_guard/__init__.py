"""runtime_guard package — thin re-export shim over _core."""
import importlib as _il
import os as _os
import sys as _sys

_HERE = _os.path.dirname(__file__)
_spec = _il.util.spec_from_file_location("_core", _os.path.join(_HERE, "_core.py"))
_core = _il.util.module_from_spec(_spec)
_spec.loader.exec_module(_core)

# Re-export all public names into this package namespace.
for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)


def __getattr__(name):
    try:
        return getattr(_core, name)
    except AttributeError:
        raise AttributeError(
            f"module 'hooks.lib.runtime_guard' has no attribute {name!r}"
        )
