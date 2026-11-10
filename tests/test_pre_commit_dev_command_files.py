"""The fail-closed pre-commit hook (hooks/git-hooks/pre-commit) lets a commit stage the
dev-family command files as the tree holds them.

Its former step 4 ran hooks/sentinel-lint.sh whenever commands/dev.md, dev-command.md or
dev-overnight.md was staged, and required each to hold the line
`REGISTRY_DIR="$CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID"`. Train 1's merge
(05170bf) dropped it from dev.md and dev-command.md and train 2's (d64fa96) respelled it in
dev-overnight.md, so from then on every commit staging one of them was refused wherever the
hook is installed. The line was the `$REGISTRY_DIR` the FIRST ACTION reads once named; no
FIRST ACTION line names it now, and where a cycle's registry is is code's: the one rule
(hooks/lib/obligation.py, registry_dir_for / registry_dir_named), which the registry's
producers call and tests/test_registry_dir_one_rule.py pins. The lint and its step are removed.

The scratch repository, its isolated environment and the installed hook are the fixtures of
tests/test_private_literal_rule.py.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.test_private_literal_rule import (  # noqa: F401  (pytest fixtures)
    REPO, _commit, _head, env, hooked, repo,
)

COMMAND_FILES = ("commands/dev.md", "commands/dev-command.md", "commands/dev-overnight.md")


def _stage_from_tree(root: Path, *rels: str) -> None:
    for rel in rels:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, root / rel)


def _assert_committed(root: Path, env: dict, *rels: str) -> None:
    before = _head(root, env)
    r = _commit(root, env, *rels)
    assert r.returncode == 0 and "REFUSED" not in r.stderr, r.stderr
    assert _head(root, env) != before


@pytest.mark.parametrize("rel", COMMAND_FILES)
def test_staging_a_dev_command_file_from_the_tree_is_not_refused(hooked, env, rel):
    _stage_from_tree(hooked, rel)
    _assert_committed(hooked, env, rel)


def test_staging_all_three_together_is_not_refused(hooked, env):
    _stage_from_tree(hooked, *COMMAND_FILES)
    _assert_committed(hooked, env, *COMMAND_FILES)


def test_a_command_file_without_any_registry_line_is_not_refused(hooked, env):
    """No prose line is a precondition of a commit: the registry path is code's (one rule)."""
    path = hooked / "commands/dev-overnight.md"
    _stage_from_tree(hooked, "commands/dev-overnight.md")
    text = path.read_text(encoding="utf8")
    path.write_text("".join(l for l in text.splitlines(True) if "REGISTRY_DIR=" not in l), encoding="utf8")
    _assert_committed(hooked, env, "commands/dev-overnight.md")
