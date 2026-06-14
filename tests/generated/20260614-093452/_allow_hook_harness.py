# Shared harness for the 16 generated ACs of task 20260614-093452.
#
# Drives the REAL hook hooks/userprompt-consent-allowlist.sh with a crafted
# UserPromptSubmit-style stdin JSON and reports the observable result: whether
# the legacy flag file and the structured sentinel file were written, the
# stderr text, and the exit code. Grant files live at fixed /tmp paths keyed by
# session_id (legacy) and CLAUDE_TASK_ID (sentinel); each invocation uses a
# fresh random id pair so concurrent/repeated runs never collide.
#
# This harness is test-support only (NOT itself a test); pytest collects no
# test_* functions from it.

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
HOOK = str(_REPO_ROOT / "hooks" / "userprompt-consent-allowlist.sh")
HOOKS_DIR = str(_REPO_ROOT / "hooks")

# Make the consumer matchers importable for the channel-scope ACs (AC7/AC9/AC15).
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)


def fresh_ids():
    """Return a unique (session_id, task_id) pair for an isolated invocation."""
    nonce = uuid.uuid4().hex[:12]
    return f"gen20260614-{nonce}", f"gen20260614-{nonce}"


def legacy_path(sid):
    return f"/tmp/claude-bash-allowlist-{sid}.json"


def sentinel_path(task_id):
    return f"/tmp/claude-grants/{task_id}.json"


def suffixed_sentinel_path(task_id, suffix):
    return f"/tmp/claude-grants/{task_id}-{suffix}.json"


def run_hook(prompt, sid, task_id=None, agent_id=None):
    """Invoke the hook for `prompt` and return an observation dict.

    Returns: {exit, stdout, stderr, legacy_written, sentinel_written,
              legacy, sentinel, sid, task_id}
    legacy/sentinel are the parsed JSON contents (or None when absent).
    """
    if task_id is None:
        task_id = sid
    payload = {"prompt": prompt, "session_id": sid}
    if agent_id is not None:
        payload["agent_id"] = agent_id
    env = dict(os.environ)
    env["CLAUDE_TASK_ID"] = task_id
    env["CLAUDE_SESSION_ID"] = sid
    proc = subprocess.run(
        ["bash", HOOK],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    lpath, spath = legacy_path(sid), sentinel_path(task_id)
    legacy = _read_json(lpath)
    sentinel = _read_json(spath)
    return {
        "exit": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "legacy_written": os.path.exists(lpath),
        "sentinel_written": os.path.exists(spath),
        "legacy": legacy,
        "sentinel": sentinel,
        "sid": sid,
        "task_id": task_id,
    }


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def cleanup(sid, task_id=None):
    """Remove any grant files this invocation may have created (no bash rm)."""
    if task_id is None:
        task_id = sid
    targets = [legacy_path(sid)]
    d = Path("/tmp/claude-grants")
    if d.is_dir():
        for p in d.glob("*.json"):
            if p.name == f"{task_id}.json" or p.name.startswith(f"{task_id}-"):
                targets.append(str(p))
    for t in targets:
        try:
            os.unlink(t)
        except FileNotFoundError:
            pass
        except Exception:
            pass


def seed_sentinel(path, task_id, session_id, ops, ttl=300):
    """Write a live sentinel grant file at an explicit path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    now = time.time()
    grant = {
        "task_id": task_id,
        "session_id": session_id,
        "allowed_operations": ops,
        "created_at": now,
        "expires_at": now + ttl,
    }
    with open(path, "w") as f:
        json.dump(grant, f)


def seed_legacy(path, pattern, is_regex):
    with open(path, "w") as f:
        json.dump({"pattern": pattern, "is_regex": is_regex}, f)


# Usage-error fingerprint emitted by the refuse gate (distinct from the
# nested-quantifier rejection message — see AC11).
USAGE_ERROR_MARKERS = ("name an explicit command", "no wildcard default")


def stderr_has_usage_error(stderr):
    return any(m in stderr for m in USAGE_ERROR_MARKERS)
