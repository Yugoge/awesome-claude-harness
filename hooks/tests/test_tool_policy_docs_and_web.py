"""Roles that write or judge code may read library docs and the web (OB-L23).

policies/tool-policy.v1.json is default-deny per role: lib/policy_registry._check_tool_lists refuses
a tool its role's allowed_tools does not name. No row named Context7, and only ba named WebFetch and
WebSearch, so a dev told to "fetch the Context7 docs of a library the user names" (CLAUDE.md, Working
Practice) exited 2 on `mcp__context7__resolve-library-id`, and qa and the specialists could not
check a library's documented behaviour either. The owner decided these roles may use them:

- dev, qa, ba;
- the specialists: architect, product-owner, ui-specialist and user, the four roles
  agents/shared/specialist-protocol.md and commands/dev.md Step 3 name.

The tools are Context7's read-only documentation tools (resolve-library-id, query-docs and its older
name get-library-docs), under the bare server prefix `mcp__context7__` and the plugin prefix
`mcp__plugin_context7_context7__`, named exactly (no wildcard, so a tool the server adds later stays
refused until a row names it), plus WebFetch and WebSearch. None writes a file, runs a command or
dispatches an agent.

What must stay refused: every GitHub MCP tool for every role (no row names `mcp__github__`, the
write tools below are the ones that matter), Edit for a role without it (graphify), and Context7 /
WebFetch / WebSearch for the roles outside the list (graphify, the commit-pipeline analysts, the
clean inspectors, the test roles, pm, spec).

The hook-level cases run the real hooks/pretool-tool-policy.py for a subagent of each role, with a
throwaway HOME.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
HOOK = os.path.join(ROOT, "hooks", "pretool-tool-policy.py")
sys.path.insert(0, os.path.join(ROOT, "hooks", "lib"))
import policy_registry  # noqa: E402

SID = "3b9e1f20-6c4d-4e8a-9f1b-2d3c4e5f6a7b"
# A product repository outside /tmp and /var/tmp, never created; only paths are judged.
PRODUCT = "/nonexistent-ob-l23/product"

GRANTED_ROLES = ("dev", "qa", "ba", "architect", "product-owner", "ui-specialist", "user")
CONTEXT7_TOOLS = (
    "mcp__context7__resolve-library-id",
    "mcp__context7__query-docs",
    "mcp__context7__get-library-docs",
    "mcp__plugin_context7_context7__resolve-library-id",
    "mcp__plugin_context7_context7__query-docs",
    "mcp__plugin_context7_context7__get-library-docs",
)
WEB_TOOLS = ("WebFetch", "WebSearch")
GITHUB_WRITE_TOOLS = (
    "mcp__github__create_pull_request", "mcp__github__push_files", "mcp__github__merge_pull_request",
    "mcp__github__create_or_update_file", "mcp__github__delete_file", "mcp__github__create_branch",
    "mcp__github__create_repository", "mcp__github__fork_repository", "mcp__github__update_pull_request",
    "mcp__github__update_pull_request_branch", "mcp__github__issue_write", "mcp__github__add_issue_comment",
    "mcp__github__pull_request_review_write", "mcp__github__enable_pr_auto_merge",
    "mcp__github__actions_run_trigger",
)


def run(tmp_path, role: str, tool: str, tool_input: dict):
    home = tmp_path / "home"
    payload = {"session_id": SID, "transcript_path": str(home / ".claude" / "projects" / "-p" / f"{SID}.jsonl"),
               "cwd": PRODUCT, "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
               "agent_id": f"a0{role}", "agent_type": role, "subagent_type": role}
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=PRODUCT,
               CLAUDE_STATE_DIR=str(tmp_path / "state"), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True,
                          cwd=str(tmp_path), env=env, timeout=60)


RESOLVE = {"libraryName": "react"}
QUERY = {"libraryId": "/facebook/react", "query": "useEffect cleanup"}
DOCS = {"context7CompatibleLibraryID": "/facebook/react", "topic": "hooks"}
FETCH = {"url": "https://react.dev/reference/react/useEffect", "prompt": "cleanup semantics"}
SEARCH = {"query": "react useEffect cleanup"}

MUST_PASS = [
    ("dev", "mcp__context7__resolve-library-id", RESOLVE),
    ("dev", "mcp__context7__query-docs", QUERY),
    ("dev", "mcp__context7__get-library-docs", DOCS),
    ("dev", "mcp__plugin_context7_context7__resolve-library-id", RESOLVE),
    ("ba", "mcp__context7__resolve-library-id", RESOLVE),
    ("ba", "mcp__context7__query-docs", QUERY),
    ("qa", "mcp__context7__resolve-library-id", RESOLVE),
    ("qa", "mcp__context7__get-library-docs", DOCS),
    ("architect", "mcp__context7__resolve-library-id", RESOLVE),
    ("architect", "mcp__context7__query-docs", QUERY),
    ("dev", "WebFetch", FETCH),
    ("dev", "WebSearch", SEARCH),
    ("qa", "WebFetch", FETCH),
    ("qa", "WebSearch", SEARCH),
    ("ba", "WebFetch", FETCH),
    ("ba", "WebSearch", SEARCH),
]

PR = {"owner": "o", "repo": "r", "title": "t", "head": "h", "base": "main"}
MUST_REFUSE = [
    ("dev", "mcp__github__create_pull_request", PR),
    ("dev", "mcp__github__push_files", {"owner": "o", "repo": "r", "branch": "b", "files": [], "message": "m"}),
    ("dev", "mcp__github__merge_pull_request", {"owner": "o", "repo": "r", "pullNumber": 1}),
    ("qa", "mcp__github__create_pull_request", PR),
    ("ba", "mcp__github__create_pull_request", PR),
    ("architect", "mcp__github__merge_pull_request", {"owner": "o", "repo": "r", "pullNumber": 1}),
    ("graphify", "Edit", {"file_path": f"{PRODUCT}/README.md", "old_string": "a", "new_string": "b"}),
    ("graphify", "mcp__context7__resolve-library-id", RESOLVE),
    ("graphify", "WebFetch", FETCH),
    ("changelog-analyst", "WebSearch", SEARCH),
]


@pytest.mark.parametrize("role,tool,tool_input", MUST_PASS, ids=[f"{r}-{t}" for r, t, _ in MUST_PASS])
def test_docs_and_web_tool_passes(tmp_path, role, tool, tool_input):
    result = run(tmp_path, role, tool, tool_input)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("role,tool,tool_input", MUST_REFUSE, ids=[f"{r}-{t}" for r, t, _ in MUST_REFUSE])
def test_refusal_stays(tmp_path, role, tool, tool_input):
    result = run(tmp_path, role, tool, tool_input)
    assert result.returncode == 2, result.stderr
    assert result.stderr.startswith("BLOCKED by tool-policy.v1: "), result.stderr


def _use_current_policy(monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", ROOT)
    policy_registry._reset_cache_for_tests()
    assert policy_registry.load_policy() is not None


def test_granted_roles_admit_every_docs_and_web_tool(monkeypatch):
    _use_current_policy(monkeypatch)
    for role in GRANTED_ROLES:
        for tool in CONTEXT7_TOOLS + WEB_TOOLS:
            assert policy_registry.is_allowed(role, tool, None) == (True, "ok"), (role, tool)


def test_other_roles_stay_without_docs_and_web_tools(monkeypatch):
    _use_current_policy(monkeypatch)
    roles = policy_registry.load_policy()["roles"]
    others = [r for r in roles if r not in GRANTED_ROLES]
    assert "graphify" in others and "changelog-analyst" in others
    for role in others:
        for tool in CONTEXT7_TOOLS + WEB_TOOLS:
            allowed, reason = policy_registry.is_allowed(role, tool, None)
            assert not allowed and reason.endswith("not in allowed_tools"), (role, tool)


def test_no_role_admits_a_github_tool_or_an_unnamed_context7_tool(monkeypatch):
    _use_current_policy(monkeypatch)
    for role in policy_registry.load_policy()["roles"]:
        for tool in GITHUB_WRITE_TOOLS + ("mcp__context7__some-future-tool",
                                          "mcp__context7_evil__resolve-library-id"):
            allowed, reason = policy_registry.is_allowed(role, tool, None)
            assert not allowed and reason.endswith("not in allowed_tools"), (role, tool)


def test_rows_name_context7_exactly(monkeypatch):
    # An exact name, never a prefix wildcard: a tool the server adds later is refused until a row names it.
    _use_current_policy(monkeypatch)
    for role, spec in policy_registry.load_policy()["roles"].items():
        for entry in spec.get("allowed_tools", []):
            assert not (entry.endswith("*") and "context7" in entry), (role, entry)
            assert not entry.startswith("mcp__github"), (role, entry)
