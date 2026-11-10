"""P4-3: /close's rating step is "Step 4" (P4 R4, R7, R11, A3), not the "Step 3b" 376a9ae gave it.

376a9ae relabelled it so that no command's dispatch template would sit under a heading of the same
label; the rule that keeps BA's template off /close's own step is obligation._canonical_step's (a
label binds a template only inside its own command's file), and it holds at either label. The label
is one fact read in three places that must agree: close.md's heading (lane L2's file), close.py's
canonical list (check-todo-md-sync compares the two) and the Stop gate's todo half, which finds each
step's section by the heading line its label names (_step_heading, the in-flight rule of d4565ff9).
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
CLOSE_MD = REPO / "commands" / "close.md"
CLOSE_PY = REPO / "scripts" / "todo" / "close.py"
GATE = REPO / "hooks" / "stop-command-gate.py"
RATING = "Ask the user to rate each landed cycle"
TASK = "20261028-120000"
BA_PATHS = (f"docs/dev/ticket-{TASK}.md", f"docs/dev/context-{TASK}.json",
            f"docs/dev/acceptance-criteria-{TASK}.json")

sys.path.insert(0, str(REPO))
from hooks.lib import obligation  # noqa: E402
from hooks.lib import todo_canonical  # noqa: E402


def _close_steps(prompt: str = "") -> list[dict]:
    out = subprocess.run([sys.executable, str(CLOSE_PY)], capture_output=True, text=True, check=True,
                         env=dict(os.environ, CLAUDE_TODO_PROMPT=prompt))
    return json.loads(out.stdout)


def _gate():
    spec = importlib.util.spec_from_file_location("stop_command_gate_p4_3", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_rating_step_is_step_4_in_close_md_close_py_and_the_gate():
    text = CLOSE_MD.read_text(encoding="utf-8")
    heading = f"### Step 4: {RATING}"
    assert heading in text.splitlines()
    assert "Step 3b" not in text
    gate = _gate()
    for prompt in ("", "--auto", "--force", f"/close --late-repair {TASK}"):
        steps = _close_steps(prompt)
        assert [s["content"].split(":")[0] for s in steps] == [f"Step {n}" for n in range(5)], prompt
        assert steps[-1]["content"] == f"Step 4: {RATING}", prompt
        # The gate's todo half finds the rating step's section by the heading line its label names.
        found = re.search(gate._step_heading(steps[-1]), text, re.M)
        assert found is not None and found.group(0) == heading, prompt
    assert "3b" not in CLOSE_PY.read_text(encoding="utf-8")
    assert "Step 3b" not in GATE.read_text(encoding="utf-8")
    assert "Step 3b" not in (REPO / "hooks" / "lib" / "close_rating.py").read_text(encoding="utf-8")


def test_at_step_4_no_other_command_s_template_binds_to_the_rating_step(monkeypatch):
    """The item's question, asked at the label it restores: BA's template sits under /dev's own
    "Step 4", and with /close's rating step labelled "Step 4" too, _canonical_step(<task>, path,
    [("close", "")], ["dev"]) still names no owner for BA's ticket, context and acceptance criteria
    (a label binds only inside the template's own command), while the qa-report still binds to the
    /close step whose dispatch names qa."""
    assert any(t["role"] == "ba" and t["step"] == "4" and any(
        "ticket-" in str((a or {}).get("path")) for a in t["artifacts"] if isinstance(a, dict))
        for t in obligation.command_templates("dev"))
    real = todo_canonical.run_todo_script

    def at_step_4(command, prompt=""):
        steps = real(command, prompt)
        if command == "close" and steps:
            steps = steps[:-1] + [dict(steps[-1], content=f"Step 4: {RATING}")]
        return steps

    monkeypatch.setattr(todo_canonical, "run_todo_script", at_step_4)
    assert todo_canonical.run_todo_script("close")[-1]["content"] == f"Step 4: {RATING}"
    for path in BA_PATHS:
        assert obligation._canonical_step(TASK, path, [("close", "")], ["dev"]) is None, path
    answer = obligation._canonical_step(TASK, f"docs/dev/qa-report-{TASK}.json", [("close", "")], ["dev"])
    assert (answer["command"], answer["subagent_call"]["subagent_type"]) == ("close", "qa")
