"""commands/commit.md Steps 2 and 7 say what the code does (follow-ups: P5-4's text half, #27 item 2).

Step 2: a typed task-id is authoritative only when it names a task, the rule the /commit Stop applies
(hooks/stop-command-gate.py `_targets` / `_resolves`); one that names none is asked about, as close.md asks.
Step 7: the "never retried without the owner's grant" hook rule excludes exactly the grant codes the
Retryable rule retries, and agents/changelog-analyst.md's failure_code table keeps those codes apart from
`hook_blocked`.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMMIT = (REPO / "commands" / "commit.md").read_text(encoding="utf-8")
ANALYST = (REPO / "agents" / "changelog-analyst.md").read_text(encoding="utf-8")
GUARD = (REPO / "hooks" / "pretool-git-privilege-guard.py").read_text(encoding="utf-8")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    ends = [e for e in (text.find("\n## ", start + 1), text.find("\n### ", start + 1)) if e > 0]
    return text[start:min(ends)] if ends else text[start:]


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _codes(text: str) -> list[str]:
    return re.findall(r"`([a-z_]+)`", text)


# ------------------------------------------------------------------ Step 2
# The bullet's wording is read by no code; the rule it states is the Stop gate's, run below.
def test_step2_rule_is_the_gates_resolve_rule(tmp_path: Path) -> None:
    """The gate's `_resolves` checks what the bullet says: a docs/dev file carrying the id (its own or a
    lane's of that parent), or a typed path that exists; a mistyped id resolves to nothing."""
    gate = _load(REPO / "hooks" / "stop-command-gate.py", "stop_command_gate_commit_text")
    source = Path(gate.__file__).read_text(encoding="utf-8")
    assert "_resolves(root, arg, task)" in source
    # "with none dispatched the Stop holds, naming the typed id"
    assert '"{action}: {arg} names no task or chain file, and no dispatch of this /{action} names a task"' in source
    dev = tmp_path / "docs" / "dev"
    dev.mkdir(parents=True)
    own, laned, typo = "20260424-103044", "20260424-110000", "20260424-103045"
    (dev / f"dev-report-{own}.json").write_text("{}")
    (dev / f"dev-report-{laned}-l1.json").write_text("{}")
    assert gate._resolves(tmp_path, own, own)
    assert gate._resolves(tmp_path, laned, laned)
    assert not gate._resolves(tmp_path, typo, typo)
    rel = f"docs/dev/dev-report-{own}.json"
    assert gate._resolves(tmp_path, rel, gate._task_of(rel))
    assert not gate._resolves(tmp_path, "docs/dev/dev-report-x.json", "x")


# ------------------------------------------------------------------ Step 7
def _step7() -> str:
    return _flat(_section(COMMIT, "### Step 7:"))


def test_step7_never_retried_rule_excludes_exactly_the_retryable_grant_codes() -> None:
    step7 = _step7()
    retryable = _codes(re.search(r"\*\*Retryable\*\* \(([^)]*)\)", step7).group(1))
    hook = re.search(r"\*\*A hook rejection\*\*.*?(?=Ask one AskUserQuestion)", step7).group(0)
    assert "never retried without the owner's grant" in hook
    excluded = _codes(re.search(r"This rule does not cover (.*?), though", hook).group(1))
    assert retryable == excluded == ["grant_missing", "grant_expired", "grant_consumed"]
    assert "not a hook refusing an operation" in hook and "asks nothing" in hook
    nonretryable = _codes(re.search(r"\*\*Non-retryable\*\* \(([^)]*)\)", step7).group(1))
    assert "hook_blocked" in nonretryable and not set(nonretryable) & set(retryable)


def test_grant_codes_match_the_analysts_table_and_the_guard() -> None:
    table = dict(re.findall(r"^\| `([a-z_]+)` \| (.*) \|$", ANALYST, re.M))
    for code in _codes(re.search(r"This rule does not cover (.*?), though", _step7()).group(1)):
        meaning, retry = table[code].rsplit(" | ", 1)
        assert retry == "Yes", code
    assert table["hook_blocked"].startswith("A non-grant PreToolUse hook")
    assert table["hook_blocked"].endswith("| No")
    # The lifecycle the three codes name is the guard's: an expired grant is not live, an admitted one is spent.
    assert "if not _end_time_passed(grant.get('expires_at', ''))" in GUARD
    assert "if not _spend_grant(grant_path):" in GUARD
