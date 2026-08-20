#!/usr/bin/env python3
"""Adversarial tests for hooks/lib/commit_journal.py — the push-gate reconciliation
attribution basis.

These exercise the two failure modes that sank the previous attribution design
(`Task-id:` trailer matching and file-set intersection), both of which read content the
committing actor chose:

  - a CONCURRENT PEER's commit must never be attributable to this session (test_peer_*)
  - a FAN-OUT LANE whose task id is a prefix-extension of its parent's must never be
    attributable to the parent (test_prefix_*) — the exact relationship this repository's
    dev-registry creates by construction

Plus the fail-open contract: no input may make the journal raise, because it is written
from a PostToolUse hook that runs after the commit has already landed.

Run: python3 hooks/tests/test_commit_journal.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOKS_DIR = Path(__file__).parent.parent
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import lib.commit_journal as CJ  # noqa: E402

CHECKS = []
FAILURES = []


def check(name, condition):
    # CHECKS is appended to by every executed check, so the summary line below counts
    # what actually ran. Do NOT reintroduce a hardcoded total: a literal cannot notice
    # a check being deleted or short-circuited, and the exit status is computed from
    # FAILURES independently, so a stale total would misreport coverage silently.
    CHECKS.append(name)
    print(("PASS  " if condition else "FAIL  ") + name)
    if not condition:
        FAILURES.append(name)


def make_repo(parent, name):
    root = os.path.join(parent, name)
    os.makedirs(root)
    for args in (["init", "-q"], ["config", "user.email", "t@example.invalid"],
                 ["config", "user.name", "test"]):
        subprocess.run(["git", "-C", root] + args, check=True, capture_output=True)
    return root


def make_commit(root, message):
    with open(os.path.join(root, "f.txt"), "a") as handle:
        handle.write(message + "\n")
    subprocess.run(["git", "-C", root, "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", root, "commit", "-q", "-m", message],
                   check=True, capture_output=True)
    return subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def grant(task_id, repo_root, sid="grant-sid", parent="p"):
    return {"task_id": task_id, "sid": sid, "repo_root": repo_root,
            "branch": "master", "expected_head": parent}


def _run(tmp):
    CJ.JOURNAL_ROOT = os.path.join(tmp, "commit-events")
    repo_a = make_repo(tmp, "repoA")
    repo_b = make_repo(tmp, "repoB")

    # Baseline — a grant-authorized commit is journaled and attributable by either the
    # payload session id or the grant's own sid (orchestrator/subagent divergence).
    sha1 = make_commit(repo_a, "feat: real work")
    entry = CJ.append_commit_event(grant("T-A", repo_a, sid="sid-orch"), "sid-subagent")
    check("entry written with the observed resulting head",
          entry is not None and entry["resulting_head"] == sha1)
    check("attributable by payload session id",
          CJ.find_attributable_event(repo_a, sha1, "T-A", "sid-subagent") is not None)
    check("attributable by grant sid (orchestrator/subagent divergence)",
          CJ.find_attributable_event(repo_a, sha1, "T-A", "sid-orch") is not None)

    # THREAT — a concurrent peer session's commit.
    sha2 = make_commit(repo_a, "feat: peer work")
    CJ.append_commit_event(grant("T-B", repo_a, sid="peer-sid", parent=sha1), "peer-sid")
    check("test_peer_commit_not_attributable_to_my_session",
          CJ.find_attributable_event(repo_a, sha2, "T-B", "sid-subagent") is None)
    check("test_peer_commit_not_attributable_under_my_task_id",
          CJ.find_attributable_event(repo_a, sha2, "T-A", "sid-subagent") is None)

    # THREAT — prefix-related fan-out lane ids.
    sha3 = make_commit(repo_a, "feat: lane one")
    CJ.append_commit_event(grant("T-A-lane1", repo_a, sid="sid-subagent", parent=sha2),
                           "sid-subagent")
    check("test_prefix_lane_id_does_not_match_parent_task_id",
          CJ.find_attributable_event(repo_a, sha3, "T-A", "sid-subagent") is None)
    check("test_prefix_lane_id_matches_itself_exactly",
          CJ.find_attributable_event(repo_a, sha3, "T-A-lane1", "sid-subagent") is not None)

    # Freshness bind — resulting_head is compared to live HEAD, so a superseded commit
    # stops matching once anything is built on top of it.
    check("superseded commit no longer matches the new HEAD",
          CJ.find_attributable_event(repo_a, sha3, "T-A", "sid-subagent") is None)

    # Repository binding.
    sha_b = make_commit(repo_b, "feat: other repo")
    CJ.append_commit_event(grant("T-A", repo_b, sid="sid-subagent"), "sid-subagent")
    check("entry for another repository is not visible from this one",
          CJ.find_attributable_event(repo_a, sha_b, "T-A", "sid-subagent") is None)

    # Degenerate session ids identify nobody and must never attribute.
    sha4 = make_commit(repo_a, "feat: anonymous")
    saved = {k: os.environ.pop(k, None)
             for k in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID")}
    anonymous = CJ.append_commit_event(grant("T-C", repo_a, sid=""), "default")
    for key, value in saved.items():
        if value is not None:
            os.environ[key] = value
    check("test_anonymous_commit_writes_no_entry", anonymous is None)
    check("placeholder session 'default' attributes nothing",
          CJ.find_attributable_event(repo_a, sha4, "T-C", "default") is None)
    check("placeholder session 'unknown' attributes nothing",
          CJ.find_attributable_event(repo_a, sha4, "T-C", "unknown") is None)

    # Fail-open contract.
    try:
        results = [CJ.append_commit_event(None, "s"),
                   CJ.append_commit_event({}, "s"),
                   CJ.append_commit_event({"task_id": "t", "repo_root": "/nope"}, "s")]
        check("malformed grants return None without raising",
              all(r is None for r in results))
    except Exception:
        check("malformed grants return None without raising", False)
    try:
        CJ.find_attributable_event("/nonexistent", "abc", "t", "s")
        check("query against a missing journal does not raise", True)
    except Exception:
        check("query against a missing journal does not raise", False)

    with open(CJ.journal_path(repo_a), "a") as handle:
        handle.write("{ not json\n")
    check("corrupt journal line is skipped, valid entries still found",
          CJ.find_attributable_event(repo_a, sha1, "T-A", "sid-subagent") is not None)

    # Growth bound. MAX_ENTRIES is restored in a finally block, exactly as main() does
    # for JOURNAL_ROOT: CJ is shared interpreter state, and an inline restore on the
    # normal path only would leak the test value into every later test item or repeated
    # invocation if anything between the override and the restore raises.
    original_max = CJ.MAX_ENTRIES
    CJ.MAX_ENTRIES = 5
    try:
        for _ in range(20):
            CJ.append_commit_event(grant("bulk", repo_a, sid="sid-subagent"),
                                   "sid-subagent")
        line_count = sum(1 for _ in open(CJ.journal_path(repo_a)))
        check("journal is pruned to MAX_ENTRIES", line_count <= 5)
    finally:
        CJ.MAX_ENTRIES = original_max

    # CLI contract consumed by changelog-analyst: exit 0 + JSON on match, exit 1 on miss.
    sha5 = make_commit(repo_a, "feat: cli")
    CJ.append_commit_event(grant("cli-task", repo_a, sid="cli-sid"), "cli-sid")
    bootstrap = (
        "import sys; sys.path.insert(0, %r); import lib.commit_journal as C; "
        "C.JOURNAL_ROOT = %r; sys.exit(C._main(sys.argv))"
        % (str(HOOKS_DIR), CJ.JOURNAL_ROOT)
    )
    base = [sys.executable, "-c", bootstrap, "query", "--repo-root", repo_a,
            "--head", sha5, "--task-id", "cli-task", "--session-id"]
    hit = subprocess.run(base + ["cli-sid"], capture_output=True, text=True)
    check("CLI exits 0 and prints the entry on a match",
          hit.returncode == 0 and json.loads(hit.stdout)["task_id"] == "cli-task")
    miss = subprocess.run(base + ["other-sid"], capture_output=True, text=True)
    check("CLI exits 1 and prints nothing on a miss",
          miss.returncode == 1 and miss.stdout.strip() == "")

    print("\n%d/%d passed" % (len(CHECKS) - len(FAILURES), len(CHECKS)))
    return 1 if FAILURES else 0


def main():
    # TemporaryDirectory, not mkdtemp: this builds two git repositories per run, and the
    # bare mkdtemp form leaked both on every invocation. Module state is saved and
    # restored so the pytest entry point below can run in a shared interpreter.
    del CHECKS[:]
    del FAILURES[:]
    saved_root = CJ.JOURNAL_ROOT
    try:
        with tempfile.TemporaryDirectory(prefix="commit-journal-test-") as tmp:
            return _run(tmp)
    finally:
        CJ.JOURNAL_ROOT = saved_root


def test_commit_journal_adversarial():
    """Collected by the hooks/tests pytest run.

    Without this the module is importable but contributes no test items, so the
    adversarial checks would not execute as part of the suite at all.
    """
    assert main() == 0, "failed checks: %s" % (FAILURES,)


if __name__ == "__main__":
    sys.exit(main())
