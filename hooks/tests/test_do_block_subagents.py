#!/usr/bin/env python3
"""Regression coverage for hooks/pretool-do-block-subagents.py.

During an active /do cycle the main agent could still dispatch dev-type
subagents; a dispatched dev subagent writes docs/dev/dev-report-<TASK_ID>.json
alongside the cycle's do-report-<TASK_ID>.json, /close and /commit route
purely on the canonical dev-report filename, and the cycle flips onto the
five-artifact /dev chain and fails MISSING_ARTIFACT x4 (backlog entry
"a stray dev-report coexisting with the do-report under one task-id
misroutes /close onto the wrong chain",
2026-09-03). The hook blocks Agent/Task dispatch from the MAIN agent exactly
while the session's /do consent flag is active, honors the /allow Agent
grant, and fails open on every other shape.

Every assertion anchors on the subprocess exit code and/or literal stable
tokens in stderr (the "DO-CYCLE BLOCK" banner, the "dev-report" /
"five-artifact" collision tokens) -- never solely on a full free-text
sentence (backlog #118's control-flow-not-wording rule).

Fixture hygiene: every test uses a per-test unique session id (uuid4 hex)
so the /tmp flag fixtures can never collide with a real session, and every
/tmp fixture the tests create is removed in a finally block.
"""

import json
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO_ROOT, "hooks", "pretool-do-block-subagents.py")

# Mirrors lib.subagent.SUBAGENT_ENV_KEYS: scrub these from the subprocess env
# so a test run that itself happens inside a subagent context cannot leak
# "caller is a subagent" into the hook under test.
SUBAGENT_ENV_KEYS = (
    "CLAUDE_AGENT_ID",
    "CODEX_AGENT_ID",
    "CODEX_AGENT_PATH",
    "OPENAI_AGENT_ID",
    "CLAUDE_COMPAT_RUNTIME",
)

# Stable stderr anchors (tokens, not sentences).
BLOCK_BANNER = "DO-CYCLE BLOCK"
COLLISION_TOKENS = ("dev-report", "do-report", "five-artifact", "MISSING_ARTIFACT")


def _clean_env():
    env = dict(os.environ)
    for key in SUBAGENT_ENV_KEYS:
        env.pop(key, None)
    return env


def _run_hook(payload=None, raw_stdin=None):
    """Pipe a synthetic PreToolUse payload (or raw bytes) into the hook."""
    data = raw_stdin if raw_stdin is not None else json.dumps(payload)
    return subprocess.run(
        [sys.executable, HOOK],
        input=data,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=_clean_env(),
    )


def _unique_sid():
    return f"test-do-block-{uuid.uuid4().hex}"


@contextmanager
def _consent_flag(sid, content="true"):
    """Create the /do consent flag the hook keys on; always clean up."""
    path = Path(f"/tmp/claude-orchestrator-consent-{sid}.flag")
    path.write_text(content)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


@contextmanager
def _allow_agent_grant(sid):
    """Create the /allow grant file read_grant('Agent', sid) matches on
    (exact_only literal pattern, same file pretool-subagent-enforce reads)."""
    path = Path(f"/tmp/claude-bash-allowlist-{sid}.json")
    path.write_text(json.dumps({"pattern": "Agent", "is_regex": False}))
    lock = Path(f"{path}.lock")
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def test_a_consent_main_agent_agent_call_blocked():
    """(a) consent flag "true" + main-agent Agent call -> exit 2, stderr
    carries the block banner and the dev-report/do-report collision rationale."""
    sid = _unique_sid()
    with _consent_flag(sid):
        result = _run_hook({"tool_name": "Agent", "session_id": sid,
                            "tool_input": {"prompt": "do work"}})
    assert result.returncode == 2
    assert BLOCK_BANNER in result.stderr
    for token in COLLISION_TOKENS:
        assert token in result.stderr, f"missing collision token {token!r}"


def test_b_consent_main_agent_task_call_blocked():
    """(b) consent flag "true" + Task tool -> blocked with exit 2."""
    sid = _unique_sid()
    with _consent_flag(sid):
        result = _run_hook({"tool_name": "Task", "session_id": sid,
                            "tool_input": {"prompt": "do work"}})
    assert result.returncode == 2
    assert BLOCK_BANNER in result.stderr


def test_c_consent_subagent_context_allowed():
    """(c) consent present + subagent context (truthy agent_id) -> exit 0."""
    sid = _unique_sid()
    with _consent_flag(sid):
        result = _run_hook({"tool_name": "Agent", "session_id": sid,
                            "agent_id": "a1b2c3-subagent",
                            "tool_input": {"prompt": "do work"}})
    assert result.returncode == 0
    assert BLOCK_BANNER not in result.stderr


def test_d_no_consent_flag_allowed():
    """(d) no consent flag at all -> exit 0 (nothing to enforce)."""
    sid = _unique_sid()
    result = _run_hook({"tool_name": "Agent", "session_id": sid,
                        "tool_input": {"prompt": "do work"}})
    assert result.returncode == 0
    assert BLOCK_BANNER not in result.stderr


def test_e_flag_content_not_true_allowed():
    """(e) flag exists but content is not the string "true" -> exit 0
    (same content check as _has_consent in pretool-subagent-enforce.py)."""
    sid = _unique_sid()
    with _consent_flag(sid, content="1"):
        result = _run_hook({"tool_name": "Agent", "session_id": sid,
                            "tool_input": {"prompt": "do work"}})
    assert result.returncode == 0
    assert BLOCK_BANNER not in result.stderr


def test_f_allow_agent_grant_overrides_block():
    """(f) /allow Agent grant present + consent present -> exit 0
    (human escape hatch, same read_grant('Agent', sid) lookup)."""
    sid = _unique_sid()
    with _consent_flag(sid), _allow_agent_grant(sid):
        result = _run_hook({"tool_name": "Agent", "session_id": sid,
                            "tool_input": {"prompt": "do work"}})
    assert result.returncode == 0
    assert BLOCK_BANNER not in result.stderr


def test_g_non_agent_task_tool_allowed():
    """(g) non-Agent/Task tool name -> exit 0 even with consent active."""
    sid = _unique_sid()
    with _consent_flag(sid):
        result = _run_hook({"tool_name": "Bash", "session_id": sid,
                            "tool_input": {"command": "true"}})
    assert result.returncode == 0
    assert BLOCK_BANNER not in result.stderr


def test_h_malformed_stdin_fails_open():
    """(h) malformed stdin -> exit 0 (fail open, never wedge)."""
    result = _run_hook(raw_stdin="this is not json {")
    assert result.returncode == 0
    assert BLOCK_BANNER not in result.stderr


def test_h2_empty_stdin_fails_open():
    """(h) empty stdin -> exit 0 (fail open)."""
    result = _run_hook(raw_stdin="")
    assert result.returncode == 0


def test_h3_non_object_json_stdin_fails_open():
    """(h) valid JSON that is not an object -> exit 0 (fail open)."""
    result = _run_hook(raw_stdin=json.dumps(["Agent", "Task"]))
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# ticket-20260930-132644-l8 Part C2: structural repair-profile exception.
# Both cases verbatim from turn-5 补漏1 (AC-L8-11 / AC-L8-12).
# ---------------------------------------------------------------------------

def _repair_obligation_prompt(profile: str = "repair") -> str:
    return (
        'dispatch a producer fix '
        f'<obligation v="1">{{"profile": "{profile}", "task_id": null}}</obligation> '
        'end of prompt'
    )


def test_i_repair_profile_dispatch_allowed_during_do():
    """(i) AC-L8-11: consent active + a syntactically valid obligation block
    with profile="repair" -> exit 0, verified structurally (extract_
    obligation_block + raw JSON parse), never via a substring search for
    the word "repair" in the prompt."""
    sid = _unique_sid()
    with _consent_flag(sid):
        result = _run_hook({
            "tool_name": "Agent", "session_id": sid,
            "tool_input": {"prompt": _repair_obligation_prompt()},
        })
    assert result.returncode == 0
    assert BLOCK_BANNER not in result.stderr


def test_j_non_repair_dispatch_still_blocked_during_do():
    """(j) AC-L8-12: consent active + (a) no obligation block at all, and
    (b) an obligation block with a DIFFERENT profile value -> both still
    exit 2 with the existing block message, unchanged."""
    sid = _unique_sid()
    with _consent_flag(sid):
        no_block = _run_hook({
            "tool_name": "Agent", "session_id": sid,
            "tool_input": {"prompt": "dispatch a dev subagent, no obligation block"},
        })
    assert no_block.returncode == 2
    assert BLOCK_BANNER in no_block.stderr

    sid2 = _unique_sid()
    with _consent_flag(sid2):
        other_profile = _run_hook({
            "tool_name": "Agent", "session_id": sid2,
            "tool_input": {"prompt": _repair_obligation_prompt(profile="fanout-lane")},
        })
    assert other_profile.returncode == 2
    assert BLOCK_BANNER in other_profile.stderr


def test_k_repair_substring_without_structural_block_still_blocked():
    """A prompt that merely MENTIONS the word "repair" in free text, with no
    syntactically valid obligation block at all, must NOT be treated as an
    allow signal -- the exception is structural, never text-sniffing."""
    sid = _unique_sid()
    with _consent_flag(sid):
        result = _run_hook({
            "tool_name": "Agent", "session_id": sid,
            "tool_input": {"prompt": "please repair this finding, profile: repair, no xml block here"},
        })
    assert result.returncode == 2
    assert BLOCK_BANNER in result.stderr


def test_l_malformed_obligation_body_fails_closed_still_blocked():
    """A syntactically-present obligation tag whose body is not valid JSON
    must fail closed (treated as "not repair"), never as an allow signal."""
    sid = _unique_sid()
    with _consent_flag(sid):
        result = _run_hook({
            "tool_name": "Agent", "session_id": sid,
            "tool_input": {"prompt": '<obligation v="1">{not valid json</obligation>'},
        })
    assert result.returncode == 2
    assert BLOCK_BANNER in result.stderr
