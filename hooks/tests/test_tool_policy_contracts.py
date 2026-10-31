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


def test_ba_cannot_write_the_retired_observations_ledger(monkeypatch):
    # BA no longer keeps docs/dev/observations-ledger.md (nothing read it), so no prefix admits it.
    _use_current_policy(monkeypatch)
    ledger = ROOT / "docs/dev/observations-ledger.md"
    allowed, reason = policy_registry.is_allowed("ba", "Write", str(ledger))
    assert not allowed and reason.endswith("not in allowed_write_path_prefixes")
    allowed, reason = policy_registry.is_allowed(
        "ba", "Write", str(ROOT / ".claude/policies/escape.json")
    )
    assert not allowed and reason.endswith("matches denied_write_path_prefixes")


def test_no_row_names_the_file_of_an_artifact(monkeypatch):
    # The BA-validation verdict has one producer, the QA dispatch whose obligation
    # declares it; pretool-tool-policy.py derives that from the dispatch record
    # (hooks/tests/test_tool_policy_derived_permission.py). The rows admit
    # neither role: no allow prefix ends in anything but '/' or '*', bar the
    # three devices a redirect names.
    _use_current_policy(monkeypatch)
    report = ROOT / "docs/dev/ba-qa-report-20261028-000000.json"
    for role in ("ba", "qa"):
        allowed, reason = policy_registry.is_allowed(role, "Write", str(report))
        assert not allowed and reason.endswith("not in allowed_write_path_prefixes")
    devices = {"*/dev/null", "*/dev/stderr", "*/dev/stdout"}
    for role, spec in policy_registry.load_policy()["roles"].items():
        assert "allowed_path_prefixes" not in spec, role
        for prefix in spec.get("allowed_write_path_prefixes", []):
            assert prefix.endswith(("/", "*")) or prefix in devices, (role, prefix)


def test_ba_search_without_fetch(monkeypatch):
    _use_current_policy(monkeypatch)
    assert policy_registry.is_allowed("ba", "WebSearch", None) == (True, "ok")
    assert policy_registry.is_allowed("ba", "WebFetch", None) == (True, "ok")
    assert policy_registry.is_allowed("general-purpose", "WebSearch", None) == (True, "ok")
    assert policy_registry.is_allowed("general-purpose", "WebFetch", None) == (True, "ok")


def test_browser_provider_aliases_are_role_equivalent(monkeypatch):
    _use_current_policy(monkeypatch)
    roles = ("user", "ui-specialist", "qa", "pm")
    for role in roles:
        for operation in ("browser_navigate", "browser_run_code"):
            tool = f"mcp__playwright__{operation}"
            assert policy_registry.is_allowed(role, tool, None) == (True, "ok")
        allowed, reason = policy_registry.is_allowed(
            role, "mcp__unrelated__browser_run_code", None
        )
        assert not allowed and reason.endswith("not in allowed_tools")
