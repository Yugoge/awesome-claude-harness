"""runtime_guard package — thin re-export shim over _core."""
import importlib as _importlib
import sys as _sys

# Load _core as a proper submodule so module identity is correct:
# rg.evaluate.__module__ == "lib.runtime_guard._core" and
# `import lib.runtime_guard._core` and reload() both see the same object.
_core_name = f"{__name__}._core"
if _core_name in _sys.modules:
    _core = _importlib.reload(_sys.modules[_core_name])
else:
    _core = _importlib.import_module("._core", __name__)

# Re-export all public names into this package namespace.
for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)


def __getattr__(name):
    try:
        return getattr(_core, name)
    except AttributeError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        )
