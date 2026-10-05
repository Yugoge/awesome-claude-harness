"""LANE-POL least-privilege role-policy regression matrix."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
import policy_registry  # noqa: E402


def _use_current_policy(monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(ROOT))
    policy_registry._reset_cache_for_tests()
    assert policy_registry.load_policy() is not None


def test_ba_exact_observations_ledger_only(monkeypatch):
    _use_current_policy(monkeypatch)
    ledger = ROOT / "docs/dev/observations-ledger.md"
    assert policy_registry.is_allowed("ba", "Write", str(ledger)) == (True, "ok")
    allowed, reason = policy_registry.is_allowed("ba", "Edit", str(ledger) + ".bak")
    assert not allowed and reason.endswith("not in allowed_write_path_prefixes")
    allowed, reason = policy_registry.is_allowed(
        "ba", "Write", str(ROOT / ".claude/policies/escape.json")
    )
    assert not allowed and reason.endswith("matches denied_write_path_prefixes")


def test_ba_search_without_fetch(monkeypatch):
    _use_current_policy(monkeypatch)
    assert policy_registry.is_allowed("ba", "WebSearch", None) == (True, "ok")
    allowed, reason = policy_registry.is_allowed("ba", "WebFetch", None)
    assert not allowed and reason == "tool WebFetch not in allowed_tools"
    assert policy_registry.is_allowed("general-purpose", "WebSearch", None) == (True, "ok")
    assert policy_registry.is_allowed("general-purpose", "WebFetch", None) == (True, "ok")


def test_browser_provider_aliases_are_role_equivalent(monkeypatch):
    _use_current_policy(monkeypatch)
    roles = ("user", "ui-specialist", "qa", "pm")
    for role in roles:
        for provider in ("playwright", "paseo"):
            for operation in ("browser_navigate", "browser_run_code"):
                tool = f"mcp__{provider}__{operation}"
                assert policy_registry.is_allowed(role, tool, None) == (True, "ok")
        allowed, reason = policy_registry.is_allowed(
            role, "mcp__unrelated__browser_run_code", None
        )
        assert not allowed and reason.endswith("not in allowed_tools")
