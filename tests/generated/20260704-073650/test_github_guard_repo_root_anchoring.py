# Regression tests for config.is_github_reserved_subtree repo-root anchoring
# (task 20260704-073650). Exercises the RUNTIME behaviour of the guard, unlike
# the source-grep closure test in tests/generated/20260702-171509/. Covers the
# two edge cases the /commit pre-commit QA gate + codex surfaced:
#   (1) bare relative '.' / 'workflows' must be judged against the repo root,
#       never the process CWD (the false-NEGATIVE codex reproduced);
#   (2) a repo living under an unrelated ancestor dir literally named '.github'
#       must NOT flag its normal folders (the false-POSITIVE a bare abspath fix
#       would have reintroduced).

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hooks.doc_sync.config import is_github_reserved_subtree  # noqa: E402


def test_absolute_within_repo_github_is_reserved():
    root = _REPO_ROOT
    assert is_github_reserved_subtree(root / ".github", root) is True
    assert is_github_reserved_subtree(root / ".github" / "workflows", root) is True


def test_absolute_non_github_is_not_reserved():
    root = _REPO_ROOT
    assert is_github_reserved_subtree(root / "scripts", root) is False
    assert is_github_reserved_subtree(root, root) is False  # repo root itself


def test_relative_github_anchored_to_repo_root():
    root = _REPO_ROOT
    assert is_github_reserved_subtree(".github", root) is True
    assert is_github_reserved_subtree(".github/workflows", root) is True
    assert is_github_reserved_subtree("scripts", root) is False


def test_dotdot_collapses_relative_to_root():
    root = _REPO_ROOT
    assert is_github_reserved_subtree(".github/workflows/..", root) is True      # -> .github
    assert is_github_reserved_subtree(".github/workflows/../..", root) is False  # -> repo root


def test_bare_dot_is_repo_root_not_github():
    # '.' means the repo root, which is not .github — must be False regardless.
    assert is_github_reserved_subtree(".", _REPO_ROOT) is False


def test_bare_relative_ignores_cwd_inside_github(tmp_path, monkeypatch):
    # The false-NEGATIVE: even with the process CWD physically inside .github, a
    # repo-root-anchored answer must not silently inherit that .github.
    root = tmp_path / "repo"
    (root / ".github" / "workflows").mkdir(parents=True)
    monkeypatch.chdir(root / ".github" / "workflows")
    # The repo's real .github/workflows (absolute) is reserved.
    assert is_github_reserved_subtree(root / ".github" / "workflows", root) is True
    # A bare '.' anchored to the repo root is the repo root -> NOT reserved.
    assert is_github_reserved_subtree(".", root) is False


def test_ancestor_named_github_does_not_false_positive(tmp_path):
    # The false-POSITIVE the old normpath deliberately avoided (and a naive
    # abspath fix would reintroduce): a repo that itself lives beneath an
    # unrelated ancestor named '.github'. Only the repo's OWN .github may match.
    root = tmp_path / ".github" / "myrepo"
    (root / "scripts").mkdir(parents=True)
    (root / ".github").mkdir()
    assert is_github_reserved_subtree(root / "scripts", root) is False  # ancestor .github ignored
    assert is_github_reserved_subtree("scripts", root) is False
    assert is_github_reserved_subtree(root / ".github", root) is True   # repo's own .github
    assert is_github_reserved_subtree(".github", root) is True


def test_path_outside_repo_is_not_reserved(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "other" / ".github"
    outside.mkdir(parents=True)
    # An absolute .github OUTSIDE the repo root is not THIS repo's .github.
    assert is_github_reserved_subtree(outside, root) is False


def test_nested_non_root_github_is_not_reserved(tmp_path):
    # Only the repo's ROOT-level .github is GitHub-reserved. A nested .github
    # deeper in the tree (e.g. src/.github) is a normal folder and must NOT be
    # suppressed (codex do-audit finding 1: anchored check must be parts[0], not
    # "any component").
    root = tmp_path / "repo"
    (root / "src" / ".github" / "workflows").mkdir(parents=True)
    assert is_github_reserved_subtree(root / "src" / ".github", root) is False
    assert is_github_reserved_subtree(root / "src" / ".github" / "workflows", root) is False
    assert is_github_reserved_subtree("src/.github/workflows", root) is False
    # The repo's own ROOT-level .github is still reserved.
    (root / ".github").mkdir()
    assert is_github_reserved_subtree(root / ".github", root) is True
    assert is_github_reserved_subtree(".github", root) is True


def test_no_project_dir_lexical_fallback_preserves_dotdot_contract():
    # Backward-compat: without a repo anchor the judgment is lexical on the path
    # as written (collapses '..'), preserving the prior single-arg behaviour.
    assert is_github_reserved_subtree(".github/workflows/..") is True       # -> .github
    assert is_github_reserved_subtree(".github/workflows/../..") is False   # -> .
    assert is_github_reserved_subtree("scripts") is False
    assert is_github_reserved_subtree(Path(".github")) is True
