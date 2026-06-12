"""Shared AC-runner for task 20260611-100500 generated tests.

run_ac("AC-N") invokes the behavioral harness (ac_harness.py AC-N), parses its
JSON output, and asserts every assertion declared for AC-N in
docs/dev/acceptance-criteria-20260611-100500.json. This keeps each generated
test body one line while the real behavioral evidence lives in ac_harness.py.

The assertions are read from the canonical acceptance-criteria JSON so the test
cannot drift from the AC contract (each `{property, match, value}` is enforced).
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]  # .../dot-claude
HARNESS = HERE / "ac_harness.py"
AC_JSON = REPO / "docs" / "dev" / "acceptance-criteria-20260611-100500.json"


def _load_assertions(ac_id: str) -> list[dict]:
    data = json.loads(AC_JSON.read_text())
    for ac in data.get("acceptance_criteria", []):
        if ac.get("id") == ac_id:
            return ac.get("check", {}).get("assertions", [])
    raise AssertionError(f"AC {ac_id} not found in {AC_JSON}")


def _run_harness(ac_id: str) -> dict:
    p = subprocess.run(
        [sys.executable, str(HARNESS), ac_id],
        capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        raise AssertionError(
            f"ac_harness.py {ac_id} exited {p.returncode}\n"
            f"STDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError as e:
        raise AssertionError(
            f"ac_harness.py {ac_id} did not emit JSON: {e}\nSTDOUT:\n{p.stdout}")


def run_ac(ac_id: str) -> None:
    assertions = _load_assertions(ac_id)
    result = _run_harness(ac_id)
    failures = []
    for a in assertions:
        prop = a["property"]
        match = a.get("match", "equals")
        expected = a.get("value")
        if prop not in result:
            failures.append(f"  MISSING property {prop!r} in harness output")
            continue
        actual = result[prop]
        if match == "equals":
            if actual != expected:
                failures.append(
                    f"  {prop}: expected {expected!r}, got {actual!r}")
        else:
            failures.append(f"  {prop}: unsupported match {match!r}")
    if failures:
        raise AssertionError(
            f"{ac_id} behavioral assertions FAILED:\n" + "\n".join(failures)
            + f"\nFull harness output:\n{json.dumps(result, indent=2)}")
