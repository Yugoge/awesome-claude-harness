"""
tests/test_graphify_workflow_contract.py — contract tests for graphify agent registration.

Verifies AC5's registration through the one agent roster (hooks/lib/roster.py:
the stems of the agents/*.md files with front matter, P1b row 18):
  1. hooks/pretool-cp-checkin.py registers a graphify sentinel read
  2. scripts/spec-check.py accepts graphify
  3. the UserPromptSubmit hook writes one registry sentinel per roster role
Neither 1 nor 2 keeps a role list of its own.

These registrations ensure the graphify.json sentinel file is created at
UserPromptSubmit time, enabling the graphify subagent's mandatory FIRST ACTION
Read to succeed (mirroring test-writer precedent).
"""

import ast
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent


def _load(name: str, relative_path: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, _REPO_ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCPAgentsRegistration:
    """A graphify sentinel read registers graphify (pretool-cp-checkin.py)."""

    def test_graphify_sentinel_read_registers(self):
        hook = _load("cp_checkin_under_test", "hooks/pretool-cp-checkin.py")
        payload = {"tool_name": "Read", "agent_id": "agent-graphify",
                   "tool_input": {"file_path": "/p/.claude/dev-registry/dev-20260601-000000/graphify.json"}}
        assert hook._extract_dev_sentinel(payload) == ("dev-20260601-000000", "graphify")
        cp_read = dict(payload, tool_input={"file_path": "/p/.claude/specs/s1/cp-state-graphify.json"})
        assert hook._extract_cp_state_target(cp_read) == ("s1", "graphify")


class TestAllowedAgentsRegistration:
    """spec-check.py accepts graphify."""

    def test_graphify_in_allowed_agents(self):
        spec_check = _load("spec_check_under_test", "scripts/spec-check.py")
        assert "graphify" in spec_check._allowed_agents()


class TestPromptWorkflowRegistration:
    """'graphify' is a role of the agent roster the registry is written from."""

    def test_graphify_in_roster(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "roster_under_test", _REPO_ROOT / "hooks" / "lib" / "roster.py")
        roster = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(roster)
        assert "graphify" in roster.roles(), (
            "agents/graphify.md must carry front matter: the UserPromptSubmit hook "
            "writes one registry sentinel per roster role, graphify.json among them"
        )


class TestSymmetricRegistration:
    """Both registration sites read the one roster (arch-2 symmetry by
    construction): every roster role registers at both, nothing else does."""

    def test_both_registration_sites_take_the_roster(self):
        roster = _load("roster_under_test", "hooks/lib/roster.py")
        hook = _load("cp_checkin_under_test", "hooks/pretool-cp-checkin.py")
        spec_check = _load("spec_check_under_test", "scripts/spec-check.py")
        roles = roster.roles()
        assert spec_check._allowed_agents() == sorted(roles)
        for name in sorted(roles) + ["wizard"]:
            payload = {"tool_name": "Read", "agent_id": "a",
                       "tool_input": {"file_path": f"/p/.claude/dev-registry/sid/{name}.json"}}
            assert (hook._extract_dev_sentinel(payload)[1] == name) is (name in roles), name
