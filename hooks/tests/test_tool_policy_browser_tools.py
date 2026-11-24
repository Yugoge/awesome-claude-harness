"""A role whose agent text has it render or drive a running app may use the browser tools its session has.

Recorded: a qa subagent's mcp__paseo__browser_new_tab, refused with "not in allowed_tools", so the live
rendering its agent text and lesson 12 demand had no permitted means; its row named one provider's
tools (mcp__playwright__*) and the session's browser came from another. The role table now names
"<browser tools>" (policy_registry.BROWSER_TOOLS), one definition of a browser tool across providers.
A role without that duty is still refused, and the refusal names the roles that may. A file a browser
tool writes (a screenshot's filename) is judged as a Write of the role, a file it uploads as a Read.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from test_tool_policy_own_scratch import ROOT, SID, run, session_root

sys.path.insert(0, str(Path(ROOT) / "hooks" / "lib"))
import policy_registry  # noqa: E402

PROJECT = "/nonexistent-browser-tools/proj"
RECORDED = ("mcp__paseo__browser_new_tab", {"url": "http://127.0.0.1:8080/login"})
OTHER_PROVIDERS = [("mcp__playwright__browser_navigate", {"url": "http://localhost:3000/"}),
                   ("mcp__claude-in-chrome__navigate", {"url": "http://localhost:3000/"}),
                   ("mcp__Claude_Browser__navigate", {"url": "http://localhost:3000/"})]
# An agent text that names a browser operation for its own steps (`browser_snapshot`, `mcp__playwright__browser_*`).
DUTY = re.compile(r"`(?:mcp__[A-Za-z_-]+__)?browser_[a-z_*]+")


def caller(role):
    return ("a" + role.replace("-", "").ljust(15, "0")[:15], role)


@pytest.mark.parametrize("tool,tool_input", [RECORDED] + OTHER_PROVIDERS)
def test_a_qa_uses_the_browser_its_session_has(tmp_path, tool, tool_input):
    proc = run(tmp_path, PROJECT, tool, tool_input, caller("qa"))
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("role", ["dev", "ba", "changelog-analyst"])
def test_a_role_without_the_duty_is_refused_and_told_who_may(tmp_path, role):
    proc = run(tmp_path, PROJECT, *RECORDED, caller(role))
    assert proc.returncode == 2 and f"tool {RECORDED[0]} not in allowed_tools" in proc.stderr, proc.stderr
    note = re.search(r"browser tools are open to the roles (\S+) only", proc.stderr)
    assert note and "qa" in note.group(1).split(","), proc.stderr


def test_a_session_tool_of_the_same_provider_is_no_browser_tool(tmp_path):
    proc = run(tmp_path, PROJECT, "mcp__paseo__create_agent", {"title": "x"}, caller("qa"))
    assert proc.returncode == 2 and "not in allowed_tools" in proc.stderr, proc.stderr


def test_a_screenshot_file_is_judged_as_a_write_of_the_role(tmp_path):
    shot = "mcp__playwright__browser_take_screenshot"
    refused = run(tmp_path, PROJECT, shot, {"filename": "/srv/shot.png"}, caller("qa"))
    assert refused.returncode == 2 and "/srv/shot.png not in allowed_write_path_prefixes" in refused.stderr, \
        refused.stderr
    own = session_root(tmp_path) / SID / "qa" / caller("qa")[0] / "shot.png"
    assert run(tmp_path, PROJECT, shot, {"filename": str(own)}, caller("qa")).returncode == 0


def test_an_uploaded_file_is_judged_as_a_read_of_the_role(tmp_path):
    # The user row denies reads of the app's source; a page upload of it is that read.
    upload = ("mcp__paseo__browser_upload", {"browserId": "x", "ref": "@e1", "filePaths": [f"{PROJECT}/src/a.js"]})
    proc = run(tmp_path, PROJECT, *upload, caller("user"))
    assert proc.returncode == 2 and "matches denied_path_prefixes" in proc.stderr, proc.stderr
    upload[1]["filePaths"] = [f"{PROJECT}/fixtures/a.png"]
    assert run(tmp_path, PROJECT, *upload, caller("user")).returncode == 0


def _agent_roles():
    for path in sorted((Path(ROOT) / "agents").glob("*.md")):
        text = path.read_text()
        name = re.search(r"^name:\s*(\S+)", text, re.M)
        if text.startswith("---") and name:
            yield name.group(1), bool(DUTY.search(text))


def test_every_role_whose_text_demands_the_browser_is_admitted_and_no_other(monkeypatch):
    # The requirement (the agent text names browser operations for its own steps) and the
    # permission (the row admits policy_registry.BROWSER_TOOLS) agree, both ways.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(ROOT))
    policy_registry._reset_cache_for_tests()
    roles = policy_registry.load_policy()["roles"]
    seen = dict(_agent_roles())
    assert {"qa", "ui-specialist", "user", "pm", "product-owner", "architect"} <= {r for r, d in seen.items() if d}
    for role, duty in seen.items():
        if role not in roles:
            continue
        for tool, _ in [RECORDED] + OTHER_PROVIDERS:
            assert policy_registry.is_allowed(role, tool, None)[0] is duty, (role, tool)


def test_no_row_names_one_providers_browser_tools():
    roles = json.loads((Path(ROOT) / "policies" / "tool-policy.v1.json").read_text())["roles"]
    for role, spec in roles.items():
        for entry in spec.get("allowed_tools", []):
            assert not policy_registry.is_browser_tool(entry.rstrip("*")), (role, entry)
