# Shared driver for the AC-WS2-* fresh-clone bootstrap smoke (WI-WS2).
#
# The smoke script (tests/fresh-clone-bootstrap-smoke.sh) builds an isolated
# NON-ROOT clone with the author home ABSENT, exercises each security guard with
# the three-assertion-per-guard contract (negative block / positive own-helper
# canary / clean-exit), proves optional-capability graceful degradation, and runs
# the post-Wave-1 zero-literal integration gate. It emits a machine-readable JSON
# result document. This helper runs the smoke ONCE per pytest process (cached) so
# the six AC-WS2-* tests each assert their own slice without re-running it 6x.
#
# Exit-code contract of the smoke (see its header):
#   0 = every assertion passed; 3 = one or more failed (JSON lists which);
#   2 = setup precondition unmet (e.g. running as root with no way to drop to a
#       non-root user) -> the tests SKIP rather than silently pass.
import json
import os
import subprocess
import tempfile
from pathlib import Path

# tests/generated/dev-20260616-204226/_ws2_smoke.py -> repo root is parents[3].
_REPO = Path(__file__).resolve().parents[3]
_SMOKE = _REPO / "tests" / "fresh-clone-bootstrap-smoke.sh"

_CACHE = {}  # keyed by smoke-script mtime so an edit re-runs it


def run_smoke():
    """Run the smoke once (cached); return (rc, result_dict). rc==2 => SKIP."""
    key = _SMOKE.stat().st_mtime if _SMOKE.exists() else 0
    if key in _CACHE:
        return _CACHE[key]
    if not _SMOKE.exists():
        raise AssertionError(f"smoke script missing: {_SMOKE}")
    out = tempfile.NamedTemporaryFile(
        prefix="ws2-smoke-", suffix=".json", delete=False)
    out.close()
    proc = subprocess.run(
        ["bash", str(_SMOKE), "--json", out.name],
        capture_output=True, text=True,
    )
    try:
        result = json.loads(Path(out.name).read_text())
    except (json.JSONDecodeError, OSError):
        result = {"all_pass": False, "assertions": [],
                  "_raw_stdout": proc.stdout, "_raw_stderr": proc.stderr,
                  "_returncode": proc.returncode}
    finally:
        try:
            os.unlink(out.name)
        except OSError:
            pass
    val = (proc.returncode, result)
    _CACHE[key] = val
    return val


def assertions_for(guard):
    """Return the list of assertion records for a given guard name."""
    rc, result = run_smoke()
    return rc, result, [a for a in result.get("assertions", [])
                        if a.get("guard") == guard]


def require_not_setup_error(rc, result):
    """Skip the test (not fail) when the smoke could not satisfy its non-root
    precondition. Anything else proceeds to real assertions.

    Two precondition-unmet signals:
      * rc==2  — the smoke's own setup guard (setpriv/nobody absent, mktemp
        failure, etc.) reported it cannot build the non-root clone.
      * a runtime privilege-drop failure — `setpriv` is PRESENT (so detect_drop
        passed) but `setresuid()` is denied by a nested sandbox/seccomp, so every
        probe fails with rc=127 and the smoke exits 3 with that signature in the
        assertion details / raw stderr. That is the SAME 'cannot run a non-root
        probe' precondition, not a genuine guard regression, so it must SKIP — a
        real guard failure on a privilege-capable machine still FAILS.
    """
    import pytest
    if rc == 2:
        pytest.skip(
            "WS2 smoke precondition unmet (cannot run a non-root probe with the "
            f"author home absent on this machine): {result.get('_raw_stderr','')[:200]}")
    # Runtime privilege-drop failure (e.g. nested sandbox): look for the setpriv/
    # setresuid signature in any assertion detail or the captured raw stderr.
    blob = result.get("_raw_stderr", "") + " ".join(
        a.get("detail", "") for a in result.get("assertions", []))
    if "setresuid failed" in blob or "setpriv:" in blob:
        pytest.skip(
            "WS2 smoke precondition unmet (this environment cannot drop "
            "privileges — setpriv/setresuid is denied, so the non-root probe "
            f"cannot run): {blob[:200]}")
