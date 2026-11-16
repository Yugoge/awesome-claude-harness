"""Execution-semantic write-target resolution at the exact sink use site."""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
import bash_write_targets as targets  # noqa: E402
import policy_registry  # noqa: E402

SAFE = "docs/dev/context-x.json"


@pytest.fixture(autouse=True)
def _bounded_environment(monkeypatch):
    monkeypatch.setenv("HOME", "/srv/harness")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(ROOT))


@pytest.mark.parametrize(
    "command,expected",
    [
        (f'OUT={SAFE}; printf x | tee "$OUT"', [SAFE]),
        (f'printf x | tee "$OUT"; OUT={SAFE}', ["$OUT"]),
        (f'OUT={SAFE}; tee "$OUT"; OUT=.claude/hooks/x', [SAFE]),
        (f'OUT={SAFE}; OUT=.claude/hooks/x; tee "$OUT"', [".claude/hooks/x"]),
        (f'OUT=.claude/hooks/x; OUT={SAFE}; tee "$OUT"', [SAFE]),
        (f'OUT={SAFE} tee "$OUT"', ["$OUT"]),
        (f'OUT={SAFE}; (tee "$OUT")', [SAFE]),
        (f"T={SAFE}; bash -c 'tee $T'", ["$T"]),
        ('OUT=$(producer); tee "$OUT"', ["$OUT"]),
        (f'REF=OUT; OUT={SAFE}; tee "${{!REF}}"', ["${!REF}"]),
        ('tee "$OUT"', ["$OUT"]),
        (f'tee {SAFE}', [SAFE]),
    ],
)
def test_assignment_target_matrix(command, expected):
    # The last assignment before the use wins, a subshell inherits it, and a `-c` shell sees
    # only exported variables.
    assert targets.extract_bash_write_paths(command) == expected


@pytest.mark.parametrize(
    "command,expected",
    [
        (f'OUT={SAFE}; [ -f x ] && OUT=.claude/hooks/y; tee "$OUT"', ["$OUT"]),
        (f'[ -f x ] && OUT={SAFE}; tee "$OUT"', ["$OUT"]),
        (f'OUT={SAFE}; for f in a; do OUT=.claude/hooks/y; done; tee "$OUT"', ["$OUT"]),
        (f'OUT={SAFE}; while x; do OUT=.claude/hooks/y; done; tee "$OUT"', ["$OUT"]),
        (f'OUT={SAFE}; if x; then OUT=.claude/hooks/y; fi; tee "$OUT"', ["$OUT"]),
        (f'OUT={SAFE}; case a in a) OUT=.claude/hooks/y;; esac; tee "$OUT"', ["$OUT"]),
        (f'OUT={SAFE}; f() {{ OUT=.claude/hooks/y; }}; f; tee "$OUT"', ["$OUT"]),
        (f'f() {{ OUT=.claude/hooks/y; }}; OUT={SAFE}; f; tee "$OUT"', ["$OUT"]),
        (f'OUT={SAFE}; read OUT; tee "$OUT"', ["$OUT"]),
        (f'OUT={SAFE}; declare OUT=.claude/hooks/y; tee "$OUT"', ["$OUT"]),
        (f'OUT={SAFE}; printf -v OUT %s .claude/hooks/y; tee "$OUT"', ["$OUT"]),
        (f'OUT={SAFE}; OUT=$(cmd); tee "$OUT"', ["$OUT"]),
        (f'OUT={SAFE} | tee "$OUT"', ["$OUT"]),
        (f'OUT={SAFE} & tee "$OUT"', ["$OUT"]),
        # eval runs in this shell: its assignment is the value tee writes
        (f'OUT={SAFE}; eval OUT=.claude/hooks/y; tee "$OUT"', [".claude/hooks/y"]),
    ],
)
def test_an_assignment_that_may_not_hold_projects_nothing(command, expected):
    # Under a condition, a loop, a case arm, a called function, a pipeline or the background, or
    # through a builtin that sets a variable, the value is not known: the target stays `$OUT`,
    # which a role's write check refuses.
    assert targets.extract_bash_write_paths(command) == expected


@pytest.mark.parametrize(
    "command,expected",
    [
        (f"export T={SAFE}; bash -c 'tee $T'", [SAFE]),
        (f"T={SAFE}; export T; bash -c 'tee $T'", [SAFE]),
        (f"T={SAFE} bash -c 'tee $T'", [SAFE]),
        (f"T={SAFE} bash -c 'tee $T'; bash -c 'tee $T'", [SAFE, "$T"]),
        (f"T={SAFE}; [ x ] && export T=.claude/hooks/y; bash -c 'tee $T'", ["$T"]),
    ],
)
def test_a_c_shell_sees_exported_and_prefix_assignments(command, expected):
    assert targets.extract_bash_write_paths(command) == expected


def test_approved_home_and_project_expansions_are_projected():
    command = 'OUT="$CLAUDE_PROJECT_DIR/docs/dev/context-x.json"; tee "$OUT"'
    assert targets.extract_bash_write_paths(command) == [str(ROOT / SAFE)]


def test_projection_failure_fails_closed(monkeypatch):
    # The projection is pure text (no process); a value it cannot project,
    # here an approved expansion whose variable is unset, keeps the literal.
    monkeypatch.delenv("CLAUDE_PROJECT_DIR")
    command = 'OUT="$CLAUDE_PROJECT_DIR/docs/dev/context-x.json"; tee "$OUT"'
    assert targets.extract_bash_write_paths(command) == ["$OUT"]


def test_projected_result_still_traverses_deny_before_allow(monkeypatch):
    # The allowed side is a directory BA's own rows keep: no row names an
    # artifact's file (a declared artifact's writer is derived from its
    # dispatch record by pretool-tool-policy.py, not from these rows).
    policy_registry._reset_cache_for_tests()
    safe = targets.extract_bash_write_paths('OUT=docs/research/x.md; tee "$OUT"')[0]
    protected = targets.extract_bash_write_paths(
        'OUT=.claude/hooks/escape.py; tee "$OUT"'
    )[0]
    assert policy_registry.is_allowed("ba", "Write", safe) == (True, "ok")
    allowed, reason = policy_registry.is_allowed("ba", "Write", protected)
    assert not allowed and reason.endswith("matches denied_write_path_prefixes")
