"""hooks/lib/dispatch_template.py: the one template a dispatch was made from.

A dispatch's template is the fence of its command's file that names its
subagent_type (or, naming none, declares it as the one role its obligation
names: G1 refuses a dispatch whose role is not its subagent_type), declares
the role and profile the dispatch's own block names, and whose lines the
prompt carries most. Its obligation is bound to the prompt's values; an entry
whose only unbound placeholder is in its identity is kept without that value.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "hooks" / "lib"))
import dispatch_template  # noqa: E402

FENCE = "```"


def _example(role: str, profile: str, path: str, identity: dict | None = None) -> str:
    doc = {"task_id": "<timestamp>", "lane": None, "lane_set": None, "role": role, "pipeline": "toy",
           "profile": profile, "dispatched_at": "<ISO-8601 UTC ending in Z>",
           "artifacts": [{"kind": "json", "path": path, "schema": "qa-report.v2",
                          "identity": identity or {"task_id": "<timestamp>"}}]}
    return f'  <obligation v="1">\n  {json.dumps(doc)}\n  </obligation>'


def _command(tmp_path: Path, text: str) -> Path:
    (tmp_path / "toy.md").write_text(text, encoding="utf-8")
    return tmp_path


def _block(role: str, profile: str) -> str:
    doc = {"task_id": "20261029-101010", "role": role, "pipeline": "toy", "profile": profile}
    return f'<obligation v="1">\n{json.dumps(doc)}\n</obligation>'


QA_TWICE = f"""### Step 7

{FENCE}
Use Agent tool with:
- subagent_type: "qa"
- prompt: "
  Validate BA analysis for <timestamp>.
{_example("qa", "ba_validation", "docs/dev/ba-qa-report-<timestamp>.json")}
  You are in BA-VALIDATION MODE.
  "
{FENCE}

### Step 13

{FENCE}
Use Agent tool with:
- subagent_type: "qa"
- prompt: "
  Verify implementation for <timestamp>.
{_example("qa", "final_verification", "docs/dev/qa-report-<timestamp>.json")}
  You are the QA subagent.
  "
{FENCE}
"""


def test_the_template_of_the_dispatchs_own_role_and_profile_not_a_union(tmp_path):
    commands = _command(tmp_path, QA_TWICE)
    final = "Verify implementation for 20261029-101010.\n" + _block("qa", "final_verification")
    declared = dispatch_template.template_obligation("toy", "qa", final, commands)
    assert [a["path"] for a in declared["artifacts"]] == ["docs/dev/qa-report-20261029-101010.json"]
    # The block alone names the template, whatever lines the prompt shares with another one.
    mixed = "Validate BA analysis for 20261029-101010.\n" + _block("qa", "final_verification")
    assert "You are the QA subagent." in dispatch_template.template_of("toy", "qa", mixed, commands)
    # With no block of its own, the template whose lines the prompt carries.
    bare = "Validate BA analysis for 20261029-101010.\nYou are in BA-VALIDATION MODE."
    declared = dispatch_template.template_obligation("toy", "qa", bare, commands)
    assert [a["path"] for a in declared["artifacts"]] == ["docs/dev/ba-qa-report-20261029-101010.json"]
    assert dispatch_template.template_of("toy", "qa", "nothing of either", commands) is None
    assert dispatch_template.template_of("toy", "qa", "x\n" + _block("qa", "singular"), commands) is None


def test_a_fence_naming_no_type_dispatches_the_role_it_declares(tmp_path):
    commands = _command(tmp_path, f"""### Step 4

**Use Task tool to invoke BA subagent**:

{FENCE}
Use Task tool with:
- prompt: "
  Analyze <timestamp>.
{_example("ba", "singular", "docs/dev/context-<timestamp>.json")}
  "
{FENCE}

### Step 2

Use the Agent tool with `subagent_type: qa` once per round:

{FENCE}
Judge close of <timestamp>.
{_example("qa", "final_verification", "docs/dev/close-report-<timestamp>.json")}
{FENCE}
""")
    prompt = "Analyze 20261029-101010."
    assert dispatch_template.template_obligation("toy", "ba", prompt, commands)["artifacts"][0]["path"] == \
        "docs/dev/context-20261029-101010.json"
    assert dispatch_template.template_obligation("toy", "general-purpose", prompt, commands) is None
    assert dispatch_template.template_obligation("toy", "qa", "Judge close of 20261029-101010.", commands)[
        "artifacts"][0]["path"] == "docs/dev/close-report-20261029-101010.json"


def test_an_identity_left_unbound_keeps_the_entry_without_that_value(tmp_path):
    example = _example("pm", "overnight", "docs/dev/overnight/<session_id>/test-plan.json", {"task_id": "<TS>"})
    commands = _command(tmp_path, f"""{FENCE}
Use Agent tool with:
- subagent_type: "pm"
- prompt: "
{example.replace('"<timestamp>"', '"<TS>"')}
  Session ID: <session_id>
  Output test plan to: docs/dev/overnight/<session_id>/<plan_name>
  "
{FENCE}
""")
    declared = dispatch_template.template_obligation("toy", "pm", "Session ID: s1\nOutput test plan to: x", commands)
    assert declared["artifacts"] == [{"kind": "json", "path": "docs/dev/overnight/s1/test-plan.json",
                                      "schema": "qa-report.v2", "identity": {}}]
    # A placeholder outside the identity still drops the entry.
    assert dispatch_template.template_obligation("toy", "pm", "Output test plan to: x", commands) is None


def test_the_current_dev_qa_templates_carry_the_codex_line_and_request_id():
    text = (REPO / "commands" / "dev.md").read_text(encoding="utf-8")
    final = next(b for b, t, roles, profiles, _e in dispatch_template._fences(text)
                 if t == "qa" and "final_verification" in profiles)
    assert "\n  codex_required: true\n" in final
    assert '"identity":{"task_id":"<timestamp>","request_id":"<timestamp>"}' in final
    prompt = "Use Task tool with:\n- description: \"Verify implementation quality against standards\"\n" \
             + _block("qa", "final_verification")
    assert dispatch_template.template_of("dev", "qa", prompt) == final
