"""/merge: a merge-analyst verdict that forbids the merge must be enforced by a gate, not by
commands/merge.md Step 3's prose alone.

Today hooks/merge.sh reads no grant, no PreToolUse hook reads the grant at the Bash call of
merge.sh, and the Stop gate's p_merge (hooks/stop-command-gate.py) passes on any landed merge of
the source before it looks at the verdict. These tests fail on that tree and pass once:
  (a) a PreToolUse gate refuses the Bash call that runs <HARNESS_ROOT>/hooks/merge.sh <ref> (the
      shape stop-command-gate.py's Step-5 matcher already recognises) unless this session's newest
      merge-analyst grant for the repository, written since the /merge opener, has verdict
      `approved`, names <ref> as `branch`, is unexpired, and its source_tip/default_tip equal the
      live tips; and
  (b) p_merge counts a merge of the source landed after the opener as complete only when that
      same newest grant is `approved` for the source tip that was merged.
The approved control must keep passing.

Place in hooks/tests/ of a harness tree; it reuses test_stop_command_gate.py's fixtures.
Run: python3 -m pytest hooks/tests/test_merge_verdict_enforced.py -q
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_stop_command_gate as t  # noqa: E402
from test_stop_command_gate import env, repo  # noqa: E402,F401  (fixtures)

TREE = t.REPO
REGISTERED_BASH = [  # settings.json: the PreToolUse entries that fire on a Bash call
    ["python3", str(TREE / "hooks" / "pretool-launch.py")],
    ["bash", str(TREE / "hooks" / "pretool-bash-safety.sh")],
    ["bash", str(TREE / "hooks" / "pretool-worktree-guard.sh")],
]


def _hook_env(env):
    home = env.tmp / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    return {**os.environ, "CLAUDE_HOME": str(TREE), "HOME": str(home), "CLAUDE_STATE_DIR": str(env.state),
            "CLAUDE_PROJECT_DIR": str(env.project), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
            "CLAUDE_CODE_SESSION_ID": t.SID}


def _pretool_refusals(env, command, cwd):
    """The registered PreToolUse hooks that refuse the main agent's Bash ``command``."""
    payload = {"session_id": t.SID, "transcript_path": str(env.tx.path), "cwd": str(cwd),
               "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "toolu_merge0001",
               "tool_input": {"command": command, "description": "merge"}, "permission_mode": "default"}
    refused = []
    for argv in REGISTERED_BASH:
        done = subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True,
                              env=_hook_env(env), cwd=str(cwd), timeout=120)
        if done.returncode == 2 or '"permissionDecision": "deny"' in done.stdout:
            refused.append((Path(argv[-1]).name, done.stderr.strip()[:400]))
    return refused


def _grant_path(repo):
    folder = Path(importlib.import_module("lib.merge_grant").grant_root(),
                  hashlib.sha256(os.path.realpath(repo).encode()).hexdigest()[:16], t.SID)
    return sorted(folder.glob("*.json"))[-1]


def _after_analysis(env, repo, grant):
    """/merge feature typed, Step 1 run, the merge-analyst dispatched and (unless ``grant`` is
    'none') its grant written as agents/merge-analyst.md Phase 8 writes it."""
    t.branches(repo, "feature")
    t.opener_now(env, "merge", "feature")
    env.tx.tool("Bash", {"command": f"python3 {TREE}/scripts/steps/merge-snapshot.py snapshot feature"})
    if grant != "none":
        t.write_grant(env, repo, "feature", "approved" if grant in ("approved", "expired", "moved") else "blocked")
    env.tx.tool("Agent", {"subagent_type": "merge-analyst", "description": "merge-analyst",
                          "prompt": "RESOLVED_REF=feature\n"}, result="merge-analyst grant written: g.json")
    if grant == "expired":  # past the 60 s the analyst gives it; the file keeps its Write time
        path = _grant_path(repo)
        body, stamp = json.loads(path.read_text()), path.stat().st_mtime
        body["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        path.write_text(json.dumps(body))
        os.utime(path, (stamp, stamp))
    if grant == "moved":  # the source moved after the analysis: Step 4's "Tips changed"
        t.git(repo, "checkout", "-q", "feature")
        t.commit(repo, "late.txt")
        t.git(repo, "checkout", "-q", "master")


MERGE_SH = "bash {tree}/hooks/merge.sh {flags}feature"


@pytest.mark.parametrize("flags", ["", "--no-commit "])
@pytest.mark.parametrize("grant", ["blocked", "none", "expired", "moved"])
def test_merge_sh_is_refused_without_a_live_approved_grant(env, repo, grant, flags):
    _after_analysis(env, repo, grant)
    refused = _pretool_refusals(env, MERGE_SH.format(tree=TREE, flags=flags), repo)
    assert refused, f"no PreToolUse hook refused merge.sh after a {grant!r} merge-analyst grant"


@pytest.mark.parametrize("flags", ["", "--no-commit "])
def test_control_merge_sh_passes_after_a_live_approved_grant(env, repo, flags):
    _after_analysis(env, repo, "approved")
    assert _pretool_refusals(env, MERGE_SH.format(tree=TREE, flags=flags), repo) == []


def _land_with_merge_sh(env, repo):
    """merge.sh run from the test process (as no hook sees it), recorded as the agent's Bash call."""
    t.GIT_CLOCK[0] += 1
    when = f"@{int(t.GIT_CLOCK[0])} +0000"
    done = subprocess.run(["bash", str(TREE / "hooks" / "merge.sh"), "feature"], cwd=str(repo), capture_output=True,
                          text=True, timeout=120, env={**os.environ, "CLAUDE_HOME": str(TREE),
                                                        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                                                        "GIT_COMMITTER_NAME": "t",
                                                        "GIT_COMMITTER_EMAIL": "t@example.invalid",
                                                        "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when})
    assert done.returncode == 0, done.stderr
    env.tx.tool("Bash", {"command": MERGE_SH.format(tree=TREE, flags="")}, result=done.stdout)
    env.tx.say("Merged feature into master.")


# Expiry is judged at the merge.sh call (above); at Stop the 60 s grant is normally past already,
# and the reflog times here run on the fixture's git clock, so no "expired" case is asked of Stop.
@pytest.mark.parametrize("grant", ["blocked", "none"])
def test_stop_holds_a_merge_landed_without_a_live_approved_grant(env, repo, grant):
    _after_analysis(env, repo, grant)
    _land_with_merge_sh(env, repo)
    code, text = t.run(env)
    assert code == 2, f"the Stop gate passed a merge landed after a {grant!r} merge-analyst grant: {text!r}"


def test_control_stop_passes_a_merge_landed_after_an_approved_grant(env, repo):
    _after_analysis(env, repo, "approved")
    _land_with_merge_sh(env, repo)
    assert t.run(env) == (0, "")
