"""Shared git-fixture helpers for the stage-owned-hunks.py AC suite.

All fixtures are synchronous git operations in throwaway temp repos — no
background daemons, so the R10 verification-harness cleanup contract is not
triggered. pytest's tmp_path handles teardown.
"""

import json
import os
import subprocess
import sys

import pytest

HELPER = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "stage-owned-hunks.py")
)

# Exit codes from the helper
OK = 0
EXCLUDE = 10


class Repo:
    """A throwaway git repo with helpers to drive stage-owned-hunks.py."""

    def __init__(self, root):
        self.root = str(root)

    def git(self, *args, input_bytes=None):
        return subprocess.run(
            ["git", "-C", self.root, *args],
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def git_text(self, *args):
        p = self.git(*args)
        return p.stdout.decode("utf-8", "replace")

    def init(self):
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "Test")
        # Defensive: ensure a deterministic line-ending policy in the fixture.
        self.git("config", "core.autocrlf", "false")

    def path(self, rel):
        return os.path.join(self.root, rel)

    def write(self, rel, data):
        full = self.path(rel)
        os.makedirs(os.path.dirname(full), exist_ok=True) if os.path.dirname(rel) else None
        mode = "wb" if isinstance(data, (bytes, bytearray)) else "w"
        with open(full, mode) as fh:
            fh.write(data)

    def read_bytes(self, rel):
        with open(self.path(rel), "rb") as fh:
            return fh.read()

    def commit(self, msg):
        # Runs inside pytest's own subprocess tree — the privilege guard only
        # intercepts the agent's direct Bash tool calls, never a grandchild.
        self.git("add", "-A")
        p = self.git("commit", "-qm", msg)
        assert p.returncode == 0, p.stderr.decode()

    def write_ledger(self, edits, name="ledger.json"):
        p = os.path.join(self.root, name)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(edits, fh)
        return p

    def write_snapshot(self, data, name="snapshot.bin"):
        p = os.path.join(self.root, name)
        mode = "wb" if isinstance(data, (bytes, bytearray)) else "w"
        with open(p, mode) as fh:
            fh.write(data)
        return p

    def run_helper(self, rel, ledger_path, snapshot_path):
        """Invoke the helper; return (exit_code, stderr_text)."""
        p = subprocess.run(
            [sys.executable, HELPER,
             "--git-root", self.root,
             "--file", rel,
             "--ledger", ledger_path,
             "--snapshot", snapshot_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        return p.returncode, p.stderr.decode("utf-8", "replace")

    def cached_diff(self, rel):
        return self.git_text("diff", "--cached", "--", rel)

    def unstaged_diff(self, rel):
        return self.git_text("diff", "--", rel)

    def cached_names(self):
        out = self.git_text("diff", "--cached", "--name-only").strip()
        return set(out.split("\n")) if out else set()

    def porcelain(self):
        return self.git_text("status", "--porcelain")


@pytest.fixture
def repo(tmp_path):
    r = Repo(tmp_path / "wt")
    os.makedirs(r.root, exist_ok=True)
    r.init()
    return r
