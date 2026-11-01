"""G2's spec-view check (P1b row 8): a /spec split is checked at the spec
subagent's stop by `spec-verify.py --strict` on the views its dispatch declares
(`spec_views`), the rule moved out of stop-spec-coverage-enforce.py. A spec
subagent dispatched from the base's /spec template carries no obligation; G2
takes the rule the current commands/spec.md template declares for its
subagent_type (hooks/lib/dispatch_template.py).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "subagentstop-artifact-contract-enforce.py"
sys.path.insert(0, str(REPO / "hooks" / "lib"))
import dispatch_template  # noqa: E402

SPEC_ID = "20261028-101010"
MONOLITH = f"docs/dev/specs/spec-{SPEC_ID}.md"
VIEWS = f"docs/dev/specs/{SPEC_ID}/views"
SESSION = "11111111-2222-3333-4444-555555555555"
AGENT = "a0123456789abcdef"
TOOL_USE = "toolu_spec_dispatch_1"

MONO_TEXT = """# Spec: toy

## Section 5: User's Acceptance Criterion

Make add return the sum of two numbers.
Keep sub unchanged for callers.
The toy tests must pass.
Report the pytest result line.
"""
HEADER = "<!-- AUTO-GENERATED VIEW for {a} | source: m | extracted: now -->\n\n# {a} view of x\n\n**Monolith**: m\n\n---\n\n"
VIEW_TEXT = {
    "ba.md": HEADER.format(a="ba") + "## Role Mandate\n\n> Make add return the sum of two numbers.\n\n"
             "Make add return the sum of two numbers.\nKeep sub unchanged for callers.\n",
    "qa.md": HEADER.format(a="qa") + "## Role Mandate\n\n> The toy tests must pass.\n\n"
             "The toy tests must pass.\nReport the pytest result line.\n",
    "orchestrator.md": HEADER.format(a="orchestrator") + "## Role Mandate (from spec)\n\n"
                       "> Make add return the sum of two numbers.\n\n## Pipeline Workflow\n\n# Spec: toy\n"
                       "## Section 5: User's Acceptance Criterion\n",
}


def _split(project: Path, complete: bool, mono: str = MONO_TEXT, view_text: dict = VIEW_TEXT) -> None:
    (project / MONOLITH).parent.mkdir(parents=True, exist_ok=True)
    (project / MONOLITH).write_text(mono, encoding="utf-8")
    views = project / VIEWS
    views.mkdir(parents=True, exist_ok=True)
    for name, text in view_text.items():
        if not complete and name == "qa.md":
            text = text.replace("Report the pytest result line.\n", "")
        (views / name).write_text(text, encoding="utf-8")


def _base_prompt(project: Path) -> str:
    # The base's /spec Step 6 template, instantiated: no obligation block.
    return (
        "You are the spec subagent. Read and follow the instructions in ~/.claude/agents/spec.md EXACTLY.\n"
        f"Spec id: {SPEC_ID}\nMonolith: {project / MONOLITH}\nMonolith lines: 8\n"
        f"Output folder: docs/dev/specs/{SPEC_ID}/\nProject dir: {project}\n"
        "Execute Phase 0 (read spec, decide relevant agents).\n"
    )


def _obligation_prompt(project: Path) -> str:
    doc = {"task_id": SPEC_ID, "lane": None, "lane_set": None, "role": "spec", "pipeline": "spec",
           "profile": "singular", "dispatched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "artifacts": [{"kind": "spec_views", "path": VIEWS, "monolith": MONOLITH}]}
    return _base_prompt(project) + f'<obligation v="1">\n{json.dumps(doc)}\n</obligation>\n'


def _store(home: Path, project: Path, prompt: str, subagent_type: str | None) -> None:
    slug = str(project.resolve()).replace("/", "-")
    session_dir = home / ".claude" / "projects" / slug / SESSION
    (session_dir / "subagents").mkdir(parents=True, exist_ok=True)
    agent = session_dir / "subagents" / f"agent-{AGENT}.jsonl"
    agent.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n",
                     encoding="utf-8")
    agent.with_name(agent.stem + ".meta.json").write_text(json.dumps({"toolUseId": TOOL_USE}), encoding="utf-8")
    tool_input = {"description": "Spec agent", "prompt": prompt}
    if subagent_type:
        tool_input["subagent_type"] = subagent_type
    parent = [
        {"type": "user", "message": {"role": "user", "content": "/spec make add work"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": TOOL_USE, "name": "Agent", "input": tool_input}]}},
    ]
    (session_dir.parent / f"{SESSION}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in parent),
                                                        encoding="utf-8")


def _stop(tmp_path: Path, prompt_of, subagent_type="spec", complete=True, mode="block", **split):
    project, home = tmp_path / "project", tmp_path / "home"
    project.mkdir(parents=True, exist_ok=True)
    _split(project, complete, **split)
    _store(home, project, prompt_of(project), subagent_type)
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude"), "CLAUDE_OBLIGATION_STOPGATE": mode}
    payload = {"agent_id": AGENT, "session_id": SESSION, "agent_type": subagent_type or "general-purpose"}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, env=env, timeout=60)


def test_declared_split_that_passes_spec_verify_strict_stops(tmp_path):
    run = _stop(tmp_path, _obligation_prompt)
    assert run.returncode == 0, run.stderr


def test_declared_split_that_fails_spec_verify_strict_goes_back_to_the_spec_subagent(tmp_path):
    run = _stop(tmp_path, _obligation_prompt, complete=False)
    assert run.returncode == 2, run.stderr
    assert "OBLIGATION_STOPGATE_BLOCKED" in run.stderr
    assert f"{VIEWS}: spec_verify_strict_failed" in run.stderr
    assert re.search(r"coverage:\s+FAIL \(\d+\.\d% < 100\.0%\)", run.stderr)  # the failing row, not a tail


def test_a_view_lacking_a_role_mandate_the_monolith_annotates_is_named_with_the_section(tmp_path):
    qa = HEADER.format(a="qa") + "### Role: qa\n\nThe toy tests must pass.\nReport the pytest result line.\n"
    run = _stop(tmp_path, _obligation_prompt, mono=MONO_TEXT + "\n### Role: qa\n",
                view_text=dict(VIEW_TEXT, **{"qa.md": qa}))
    assert run.returncode == 2, run.stderr
    assert re.search(r"structural:\s+FAIL \(qa\.md: ## Role Mandate missing\)", run.stderr), run.stderr
    # Without the annotation R3.4 lets the view omit the section: nothing blocks.
    assert _stop(tmp_path / "plain", _obligation_prompt, view_text=dict(VIEW_TEXT, **{"qa.md": qa})).returncode == 0


def test_advisory_mode_never_blocks(tmp_path):
    run = _stop(tmp_path, _obligation_prompt, complete=False, mode="advisory")
    assert run.returncode == 0, run.stderr


def test_a_base_template_dispatch_is_checked_by_the_current_template_rule(tmp_path):
    run = _stop(tmp_path, _base_prompt, complete=False)
    assert run.returncode == 2, run.stderr
    assert f"{VIEWS}: spec_verify_strict_failed" in run.stderr
    assert _stop(tmp_path / "ok", _base_prompt).returncode == 0


def test_a_dispatch_of_a_type_no_current_template_declares_is_not_checked(tmp_path):
    run = _stop(tmp_path, _base_prompt, subagent_type=None, complete=False)
    assert run.returncode == 0, run.stderr


def test_the_current_spec_template_declares_the_split_bound_to_the_dispatch(tmp_path):
    project = tmp_path / "project"
    declared = dispatch_template.template_obligation("spec", "spec", _base_prompt(project))
    assert declared["role"] == "spec" and declared["pipeline"] == "spec" and declared["task_id"] == SPEC_ID
    assert declared["artifacts"] == [{"kind": "spec_views", "path": VIEWS, "monolith": MONOLITH}]
    assert dispatch_template.template_obligation("spec", "general-purpose", _base_prompt(project)) is None
    assert dispatch_template.template_obligation("spec", "spec", "no matching lines") is None


def test_the_spec_views_grammar_in_the_library_and_the_schema():
    import jsonschema

    sys.path.insert(0, str(REPO / "hooks"))
    from lib import obligation

    doc = {"task_id": SPEC_ID, "lane": None, "lane_set": None, "role": "spec", "pipeline": "spec",
           "profile": "singular", "dispatched_at": "2026-10-28T10:10:10Z",
           "artifacts": [{"kind": "spec_views", "path": VIEWS, "monolith": MONOLITH}]}
    schema = json.loads((REPO / "schemas" / "obligation.v1.json").read_text(encoding="utf-8"))
    assert isinstance(obligation.validate_obligation(doc), obligation.Validated)
    jsonschema.Draft7Validator(schema).validate(doc)
    for bad in ({"kind": "spec_views", "path": VIEWS, "monolith": "/abs/spec.md"},
                {"kind": "spec_views", "path": VIEWS}):
        rejected = obligation.validate_obligation(dict(doc, artifacts=[bad]))
        assert isinstance(rejected, obligation.Rejection), bad
        assert not jsonschema.Draft7Validator(schema).is_valid(dict(doc, artifacts=[bad]))
