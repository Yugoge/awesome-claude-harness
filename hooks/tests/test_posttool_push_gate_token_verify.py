#!/usr/bin/env python3
"""Coverage for hooks/posttool-push-gate-token-verify.py (task 20261001-161041-r15).

THE GAP THIS HOOK CLOSES. agents/changelog-analyst.md Phase 10 writes the push-gate
token purely on the strength of three prose-instructed pre-write/post-write checks
the LLM agent itself must execute (:1221-1225, identically :555-569). Nothing
independently re-verifies that the agent actually ran them, or wrote correct
content. The only mechanized commit_sha comparison anywhere in hooks/*.py or
hooks/*.sh was hooks/push.sh:206-238's ancestor scan, run at /push time -- long
after the write. This hook mechanizes the same invariant Phase 10 already states in
prose (commit_sha must equal live HEAD at repo_root), immediately after the Write.

Run: pytest hooks/tests/test_posttool_push_gate_token_verify.py
"""

import json
import os
import shutil
import subprocess
import sys
import uuid

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO_ROOT, "hooks", "posttool-push-gate-token-verify.py")


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True,
                          text=True, check=True).stdout.strip()


def _make_repo(tmp_path, name="repo"):
    """A real throwaway repo with one commit -- its HEAD is the ground truth a
    correct token must match."""
    repo = os.path.join(str(tmp_path), name)
    os.makedirs(repo)
    for args in (["init", "-q"], ["config", "user.email", "t@example.invalid"],
                 ["config", "user.name", "test"]):
        _git(repo, *args)
    with open(os.path.join(repo, "f.txt"), "w") as handle:
        handle.write("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo, _git(repo, "rev-parse", "HEAD")


def _run_hook(token_path):
    """Drive the hook exactly as the harness does: a PostToolUse Write payload on
    stdin naming the just-written file."""
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": token_path}})
    return subprocess.run([sys.executable, HOOK], input=payload, capture_output=True,
                          text=True, cwd=REPO_ROOT)


def _write_token(path, **fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        json.dump(fields, handle)


@pytest.fixture
def token_base_dir():
    """A uniquely-named directory under the real /tmp/agentic-commit/push/ root --
    the hook's path regex is anchored to that literal prefix, so tests must write
    there, not to pytest's tmp_path. Cleaned up unconditionally afterward."""
    repo_hash = uuid.uuid4().hex[:16]
    base = os.path.join("/tmp/agentic-commit/push", repo_hash)
    yield base
    shutil.rmtree(base, ignore_errors=True)


# --- AC2: path matching (depth-1 legacy / depth-2 session-scoped / non-matching) --

def test_ac2_non_matching_path_is_noop(tmp_path):
    """A Write outside the push-gate token path shape is always a no-op, even when
    its content would otherwise be a glaring mismatch -- the hook must not open
    files it has no business validating."""
    path = str(tmp_path / "not-a-token.json")
    _write_token(path, commit_sha="deadbeef" * 5, repo_root=str(tmp_path))
    result = _run_hook(path)
    assert result.returncode == 0
    assert result.stderr == ""
    assert os.path.exists(path)


def test_ac2_depth1_legacy_layout_is_recognized_and_validated(tmp_path, token_base_dir):
    """Legacy depth-1 layout (<repo_hash>/<branch>.json, per hooks/push.sh:212-215)
    is in-scope: a mismatched commit_sha at this shape is still caught, proving the
    path was recognized rather than skipped."""
    repo, head = _make_repo(tmp_path)
    path = os.path.join(token_base_dir, "master.json")
    _write_token(path, commit_sha="f" * 40, repo_root=repo, branch="master",
                 session_id="s")
    result = _run_hook(path)
    assert result.returncode == 1
    assert not os.path.exists(path)
    assert os.path.exists(path + ".rejected")


def test_ac2_depth2_session_scoped_layout_is_recognized(tmp_path, token_base_dir):
    """Session-scoped depth-2 layout (<repo_hash>/<sid_digest>/<branch>.json) is the
    shape agents/changelog-analyst.md's current Phase 10 procedure writes."""
    repo, head = _make_repo(tmp_path)
    sid_digest = uuid.uuid4().hex[:16]
    path = os.path.join(token_base_dir, sid_digest, "master.json")
    _write_token(path, commit_sha=head, repo_root=repo, branch="master",
                 session_id="s")
    result = _run_hook(path)
    assert result.returncode == 0
    assert os.path.exists(path)


# --- AC3: mismatch is detected, quarantined, and reported immediately -------------

def test_ac3_wrong_commit_sha_is_quarantined_with_clear_stderr(tmp_path, token_base_dir):
    repo, head = _make_repo(tmp_path)
    wrong_sha = "0" * 40
    assert wrong_sha != head
    path = os.path.join(token_base_dir, "feature.json")
    _write_token(path, commit_sha=wrong_sha, repo_root=repo, branch="feature",
                 session_id="s")
    result = _run_hook(path)
    assert result.returncode == 1
    assert not os.path.exists(path)
    rejected = path + ".rejected"
    assert os.path.exists(rejected)
    assert json.load(open(rejected))["commit_sha"] == wrong_sha  # survives for forensics
    assert wrong_sha in result.stderr
    assert head in result.stderr


def test_ac3_nonexistent_commit_object_is_quarantined(tmp_path, token_base_dir):
    """A commit_sha that is well-formed but never existed in repo_root (fabricated,
    not merely stale) must also be caught, not just a plain inequality with HEAD."""
    repo, head = _make_repo(tmp_path)
    fabricated_sha = "1234567890abcdef1234567890abcdef12345678"
    path = os.path.join(token_base_dir, "feature.json")
    _write_token(path, commit_sha=fabricated_sha, repo_root=repo, branch="feature",
                 session_id="s")
    result = _run_hook(path)
    assert result.returncode == 1
    assert not os.path.exists(path)
    assert os.path.exists(path + ".rejected")
    assert "does not resolve to an existing commit object" in result.stderr


# --- AC4: a correct token passes silently, zero behavioral change -----------------

def test_ac4_matching_commit_sha_passes_silently_and_token_untouched(
        tmp_path, token_base_dir):
    repo, head = _make_repo(tmp_path)
    path = os.path.join(token_base_dir, "master.json")
    _write_token(path, commit_sha=head, repo_root=repo, branch="master",
                 session_id="s")
    before = open(path, "rb").read()
    result = _run_hook(path)
    assert result.returncode == 0
    assert result.stderr == ""
    assert os.path.exists(path)
    assert open(path, "rb").read() == before


# --- Fail-open edges: the hook must never crash on a shape it cannot validate -----

def test_malformed_token_json_fails_open(tmp_path, token_base_dir):
    path = os.path.join(token_base_dir, "master.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write("{not valid json")
    result = _run_hook(path)
    assert result.returncode == 0
    assert os.path.exists(path)


def test_token_missing_required_fields_fails_open(tmp_path, token_base_dir):
    path = os.path.join(token_base_dir, "master.json")
    _write_token(path, branch="master", session_id="s")  # no commit_sha/repo_root
    result = _run_hook(path)
    assert result.returncode == 0
    assert os.path.exists(path)


def test_unresolvable_repo_root_fails_open(tmp_path, token_base_dir):
    path = os.path.join(token_base_dir, "master.json")
    _write_token(path, commit_sha="f" * 40,
                 repo_root=str(tmp_path / "does-not-exist"), branch="master",
                 session_id="s")
    result = _run_hook(path)
    assert result.returncode == 0
    assert os.path.exists(path)
