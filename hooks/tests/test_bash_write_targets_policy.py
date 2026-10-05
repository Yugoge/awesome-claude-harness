"""Execution-semantic write-target resolution at the exact sink use site."""

from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
import bash_write_targets as targets  # noqa: E402
import policy_registry  # noqa: E402

SAFE = "docs/dev/context-x.json"


@pytest.fixture(autouse=True)
def _bounded_environment(monkeypatch):
    monkeypatch.setenv("HOME", "/home/tester")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(ROOT))


@pytest.mark.parametrize(
    "command,expected",
    [
        (f'OUT={SAFE}; printf x | tee "$OUT"', [SAFE]),
        (f'printf x | tee "$OUT"; OUT={SAFE}', ["$OUT"]),
        (f'OUT={SAFE}; tee "$OUT"; OUT=.claude/hooks/x', [SAFE]),
        (f'OUT={SAFE}; OUT=.claude/hooks/x; tee "$OUT"', ["$OUT"]),
        (f'OUT=.claude/hooks/x; OUT={SAFE}; tee "$OUT"', ["$OUT"]),
        (f'OUT={SAFE} tee "$OUT"', ["$OUT"]),
        (f'OUT={SAFE}; (tee "$OUT")', ["$OUT"]),
        ('OUT=$(producer); tee "$OUT"', ["$OUT"]),
        (f'REF=OUT; OUT={SAFE}; tee "${{!REF}}"', ["${!REF}"]),
        ('tee "$OUT"', ["$OUT"]),
        (f'tee {SAFE}', [SAFE]),
    ],
)
def test_assignment_target_matrix(command, expected):
    assert targets.extract_bash_write_paths(command) == expected


def test_approved_home_and_project_expansions_are_projected():
    command = 'OUT="$CLAUDE_PROJECT_DIR/docs/dev/context-x.json"; tee "$OUT"'
    assert targets.extract_bash_write_paths(command) == [str(ROOT / SAFE)]


def test_projection_timeout_fails_closed(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout", 0.5))

    monkeypatch.setattr(targets.subprocess, "run", timeout)
    assert targets.extract_bash_write_paths(f'OUT={SAFE}; tee "$OUT"') == ["$OUT"]


def test_projected_result_still_traverses_deny_before_allow(monkeypatch):
    policy_registry._reset_cache_for_tests()
    safe = targets.extract_bash_write_paths(f'OUT={SAFE}; tee "$OUT"')[0]
    protected = targets.extract_bash_write_paths(
        'OUT=.claude/hooks/escape.py; tee "$OUT"'
    )[0]
    assert policy_registry.is_allowed("ba", "Write", safe) == (True, "ok")
    allowed, reason = policy_registry.is_allowed("ba", "Write", protected)
    assert not allowed and reason.endswith("matches denied_write_path_prefixes")
