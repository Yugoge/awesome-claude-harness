"""Re-export of hooks/lib/score_log.py (the same file name, so it is loaded by path) for score-update.sh and score-inject.sh."""
import importlib.util
import pathlib
_spec = importlib.util.spec_from_file_location("hooks_lib_score_log", pathlib.Path(__file__).resolve().parents[2] / "hooks/lib/score_log.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
globals().update({name: value for name, value in vars(_module).items() if not name.startswith("_")})
