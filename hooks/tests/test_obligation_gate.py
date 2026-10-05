#!/usr/bin/env python3
"""Regression coverage for hooks/pretool-obligation-gate.py (G1 dispatch gate).

G1 is the first of five enforcement doors (spec-20260930-092323) that move
artifact-completeness detection from /close and /commit time -- where the
producing agent's context is already gone -- to the dispatch moment. It runs
on every Agent dispatch whose tool_input.subagent_type is a producer role
(ba, dev, qa, test-writer, changelog-analyst) and evaluates whether the
dispatch prompt carries a valid <obligation v="1"> block
(hooks/lib/obligation.py's parse_obligation(), never re-implemented here),
logging (advisory mode) or rejecting (block mode) when it does not.

Every assertion anchors on the subprocess exit code and/or stable tokens in
stderr/the advisory JSONL log -- never solely on a full free-text sentence
(backlog #118's control-flow-not-wording rule), mirroring
hooks/tests/test_do_block_subagents.py's style.

Fixture hygiene: every test uses a per-test unique session id (uuid4 hex) so
dev-registry directory fixtures and advisory-log assertions can never
collide with a real session; every fixture this file creates (temp
dev-registry dirs, advisory-log lines) is removed in a finally block.
"""

import json
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO_ROOT, "hooks", "pretool-obligation-gate.py")
ADVISORY_LOG = Path(os.path.expanduser("~/.claude/logs/obligation-gate-advisory.jsonl"))

# Mirrors lib.subagent.SUBAGENT_ENV_KEYS: scrub these from the subprocess env
# so a test run that itself happens inside a subagent context cannot leak
# unrelated agent identity into the hook under test.
SUBAGENT_ENV_KEYS = (
    "CLAUDE_AGENT_ID",
    "CODEX_AGENT_ID",
    "CODEX_AGENT_PATH",
    "OPENAI_AGENT_ID",
    "CLAUDE_COMPAT_RUNTIME",
)

BLOCK_BANNER = "OBLIGATION GATE BLOCK"


def _clean_env(switch=None):
    env = dict(os.environ)
    for key in SUBAGENT_ENV_KEYS:
        env.pop(key, None)
    if switch is None:
        env.pop("CLAUDE_OBLIGATION_GATE", None)
    else:
        env["CLAUDE_OBLIGATION_GATE"] = switch
    return env


def _run_hook(payload=None, raw_stdin=None, switch=None):
    data = raw_stdin if raw_stdin is not None else json.dumps(payload)
    return subprocess.run(
        [sys.executable, HOOK],
        input=data,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=_clean_env(switch),
    )


def _unique_sid(label="gate"):
    return f"test-obligation-{label}-{uuid.uuid4().hex}"


def _payload(sid, subagent_type="dev", prompt="do work"):
    return {
        "tool_name": "Agent",
        "session_id": sid,
        "tool_input": {"subagent_type": subagent_type, "prompt": prompt},
    }


def _valid_block(task_id="20260930-000000"):
    doc = {
        "task_id": task_id,
        "role": "dev",
        "pipeline": "dev",
        "profile": "singular",
        "dispatched_at": "2026-09-30T13:30:00Z",
        "artifacts": [{"kind": "response_line", "terminal_line_regex": "^DONE$"}],
    }
    return '<obligation v="1">' + json.dumps(doc) + "</obligation>"


def _malformed_block():
    """Missing the required 'profile' field -> Rejection(reason='missing_field')."""
    doc = {
        "task_id": "20260930-000000",
        "role": "dev",
        "pipeline": "dev",
        "dispatched_at": "2026-09-30T13:30:00Z",
        "artifacts": [{"kind": "response_line", "terminal_line_regex": "^DONE$"}],
    }
    return '<obligation v="1">' + json.dumps(doc) + "</obligation>"


@contextmanager
def _dev_registry_dir(sid):
    path = Path(REPO_ROOT) / ".claude" / "dev-registry" / sid
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        try:
            path.rmdir()
        except OSError:
            pass


def _advisory_records_for(sid):
    if not ADVISORY_LOG.is_file():
        return []
    records = []
    for line in ADVISORY_LOG.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("session_id") == sid:
            records.append(record)
    return records


def _purge_advisory_records_for(sid):
    """Remove every advisory line this test wrote, keeping unrelated lines."""
    if not ADVISORY_LOG.is_file():
        return
    kept = [
        line
        for line in ADVISORY_LOG.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("session_id") != sid
    ]
    ADVISORY_LOG.write_text(
        ("\n".join(kept) + "\n") if kept else "", encoding="utf-8"
    )


@contextmanager
def _advisory_cleanup(sid):
    try:
        yield
    finally:
        _purge_advisory_records_for(sid)


def test_AC_L1_01_valid_block_always_passes():
    """AC-L1-01: well-formed block, any switch mode -> exit 0, no advisory."""
    for switch in (None, "advisory", "block", "garbage-value"):
        sid = _unique_sid("ac01")
        with _advisory_cleanup(sid):
            result = _run_hook(
                _payload(sid, prompt="do work\n" + _valid_block()), switch=switch
            )
            assert result.returncode == 0, f"switch={switch!r}: {result.stderr}"
            assert _advisory_records_for(sid) == []


def test_AC_L1_02_missing_block_active_session_advisory_logs_and_passes():
    """AC-L1-02: no block, advisory, active dev-family session -> exit 0 +
    one advisory line with ts/session_id/subagent_type/reason=missing_block."""
    sid = _unique_sid("ac02")
    try:
        with _dev_registry_dir(sid):
            result = _run_hook(_payload(sid, prompt="do work, no block"))
        assert result.returncode == 0
        records = _advisory_records_for(sid)
        assert len(records) == 1, records
        record = records[0]
        for field in ("ts", "session_id", "subagent_type", "reason"):
            assert field in record, f"missing field {field!r} in {record}"
        assert record["reason"] == "missing_block"
    finally:
        _purge_advisory_records_for(sid)


def test_AC_L1_03_missing_block_no_active_session_silent_pass():
    """AC-L1-03: no block, no dev-registry dir -> exit 0, nothing logged."""
    sid = _unique_sid("ac03")
    with _advisory_cleanup(sid):
        result = _run_hook(_payload(sid, prompt="do work, no block"))
    assert result.returncode == 0
    assert _advisory_records_for(sid) == []


def test_AC_L1_04_missing_block_active_session_block_mode_rejects():
    """AC-L1-04: no block, block mode, active session -> exit 2, stderr names
    what's missing, whose responsibility it is, and the fix."""
    sid = _unique_sid("ac04")
    try:
        with _dev_registry_dir(sid):
            result = _run_hook(_payload(sid, prompt="do work, no block"), switch="block")
        assert result.returncode == 2
        assert BLOCK_BANNER in result.stderr
        for token in ("obligation", "orchestrator", "<obligation"):
            assert token in result.stderr, f"missing token {token!r} in {result.stderr}"
        # Block mode still logs (log-then-decide ordering, turn-1 microstep 4a).
        assert len(_advisory_records_for(sid)) == 1
    finally:
        _purge_advisory_records_for(sid)


def test_AC_L1_05_malformed_block_advisory_logs_validator_reason():
    """AC-L1-05: malformed block, advisory, active session -> exit 0 +
    advisory reason carries the validator's specific rejection reason."""
    sid = _unique_sid("ac05")
    try:
        with _dev_registry_dir(sid):
            result = _run_hook(_payload(sid, prompt="do work\n" + _malformed_block()))
        assert result.returncode == 0
        records = _advisory_records_for(sid)
        assert len(records) == 1, records
        assert records[0]["reason"] == "missing_field"
    finally:
        _purge_advisory_records_for(sid)


def test_AC_L1_06_malformed_block_block_mode_rejects_with_reason():
    """AC-L1-06: same malformed block, block mode -> exit 2, stderr includes
    the specific validator reason (not a generic message)."""
    sid = _unique_sid("ac06")
    with _advisory_cleanup(sid), _dev_registry_dir(sid):
        result = _run_hook(
            _payload(sid, prompt="do work\n" + _malformed_block()), switch="block"
        )
    assert result.returncode == 2
    assert "missing_field" in result.stderr


def test_AC_L1_07_non_producer_role_always_passes_untouched():
    """AC-L1-07: subagent_type outside the producer set -> exit 0
    unconditionally, no advisory, regardless of block/switch state."""
    for subagent_type in ("architect", "ui-specialist", None):
        sid = _unique_sid("ac07")
        with _advisory_cleanup(sid):
            result = _run_hook(
                _payload(sid, subagent_type=subagent_type, prompt="do work, no block"),
                switch="block",
            )
            assert result.returncode == 0, subagent_type
            assert _advisory_records_for(sid) == []


def test_AC_L1_08_switch_off_is_unconditional():
    """AC-L1-08: CLAUDE_OBLIGATION_GATE=off -> exit 0 before any other check,
    no advisory, even for a missing-block producer dispatch in block mode."""
    sid = _unique_sid("ac08")
    with _advisory_cleanup(sid), _dev_registry_dir(sid):
        result = _run_hook(_payload(sid, prompt="do work, no block"), switch="off")
    assert result.returncode == 0
    assert _advisory_records_for(sid) == []


def test_AC_L1_09_internal_crash_still_exits_0():
    """AC-L1-09: malformed/empty stdin raises inside the fail-open wrapper ->
    caught, advisory reason=gate_error written best-effort, exit 0."""
    for raw_stdin in ("this is not json {", ""):
        result = _run_hook(raw_stdin=raw_stdin)
        assert result.returncode == 0
    # The malformed-json run above has no session_id to scope cleanup by, so
    # purge any gate_error record with a null session_id this test produced.
    if ADVISORY_LOG.is_file():
        lines = ADVISORY_LOG.read_text(encoding="utf-8").splitlines()
        kept, found = [], False
        for line in lines:
            record = json.loads(line)
            if record.get("reason") == "gate_error" and record.get("session_id") is None:
                found = True
                continue
            kept.append(line)
        ADVISORY_LOG.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
        assert found, "expected a gate_error advisory record from malformed stdin"


def test_AC_L1_10_settings_json_registration_additive_only():
    """AC-L1-10: the matcher="Agent" PreToolUse group has exactly one new
    entry invoking pretool-obligation-gate.py; no other group is touched."""
    settings_path = Path(REPO_ROOT) / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    agent_groups = [g for g in data["hooks"]["PreToolUse"] if g.get("matcher") == "Agent"]
    assert len(agent_groups) == 1
    commands = [h["command"] for h in agent_groups[0]["hooks"]]
    matches = [c for c in commands if "pretool-obligation-gate.py" in c]
    assert len(matches) == 1, commands
    # The 6 pre-existing sibling hooks must still all be present.
    for sibling in (
        "pretool-layer-escalation-check.sh",
        "pretool-bisect-gate.sh",
        "pretool-spec-block-foreground-agent.py",
        "pretool-orchestrator-prompt-purity.py",
        "pretool-aggregate-check.py",
        "pretool-gitignore-preflight.py",
    ):
        assert any(sibling in c for c in commands), f"missing sibling hook {sibling}"


def test_AC_L1_11_advisory_mode_zero_behavioral_change():
    """AC-L1-11: on the pre-rollout shape (no obligation block anywhere, no
    active dev-registry dir for this session), advisory mode is silent --
    exit 0, empty stdout/stderr, identical to the hook not existing."""
    sid = _unique_sid("ac11")
    with _advisory_cleanup(sid):
        result = _run_hook(_payload(sid, prompt="an ordinary pre-rollout dispatch"))
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert _advisory_records_for(sid) == []


def test_AC_L1_12_block_then_fixed_dispatch_passes():
    """AC-L1-12 (injected-error suite item 6): block mode rejects a stripped
    dispatch, then the same prompt with a valid block appended passes."""
    sid = _unique_sid("ac12")
    base_prompt = "producer dispatch body"
    with _advisory_cleanup(sid), _dev_registry_dir(sid):
        first = _run_hook(_payload(sid, prompt=base_prompt), switch="block")
        assert first.returncode == 2
        assert BLOCK_BANNER in first.stderr
        second = _run_hook(
            _payload(sid, prompt=base_prompt + "\n" + _valid_block()), switch="block"
        )
        assert second.returncode == 0


def test_AC_L1_13_malformed_block_unconditional_no_active_session():
    """AC-L1-13: malformed block, advisory, NO dev-registry dir -> still
    exits 0 and logs the validator's reason (Rejection is unconditional,
    unlike NoBlock's AC-L1-03 gating)."""
    sid = _unique_sid("ac13")
    try:
        result = _run_hook(_payload(sid, prompt="do work\n" + _malformed_block()))
        assert result.returncode == 0
        records = _advisory_records_for(sid)
        assert len(records) == 1, records
        assert records[0]["reason"] == "missing_field"
    finally:
        _purge_advisory_records_for(sid)


def test_AC_L1_14_absent_prompt_routes_to_bad_prompt_rejection():
    """AC-L1-14: tool_input.prompt absent/non-string -> extract_obligation_block
    returns Rejection(reason='bad_prompt') -- routed through Rejection, not
    NoBlock -- advisory logs reason=bad_prompt, exit 0."""
    sid = _unique_sid("ac14")
    payload = {
        "tool_name": "Agent",
        "session_id": sid,
        "tool_input": {"subagent_type": "dev"},  # no "prompt" key at all
    }
    try:
        with _dev_registry_dir(sid):
            result = _run_hook(payload)
        assert result.returncode == 0
        records = _advisory_records_for(sid)
        assert len(records) == 1, records
        assert records[0]["reason"] == "bad_prompt"
    finally:
        _purge_advisory_records_for(sid)
