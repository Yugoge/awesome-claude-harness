#!/usr/bin/env python3
"""Regression coverage for hooks/pretool-obligation-gate.py (G1 dispatch gate).

G1 is the first of five enforcement doors (spec-20260930-092323) that move
artifact-completeness detection from /close and /commit time -- where the
producing agent's context is already gone -- to the dispatch moment. It runs
on every Agent dispatch whose tool_input.subagent_type is a producer role
(ba, dev, qa, test-writer, changelog-analyst and the three /close inspectors)
or whose prompt contains "<obligation" (any subagent_type), and evaluates the
dispatch prompt's <obligation v="1"> block with hooks/lib/obligation.py's
parse_obligation() (never re-implemented here) against the harness's own
schemas/registry.json, logging (advisory mode) or rejecting (block mode,
CLAUDE_OBLIGATION_GATE=block) when it is not valid.

P1 behaviour pinned here:
  - a valid block carries a current dispatched_at (within 300 s of now) and
    a role equal to the dispatch's subagent_type; otherwise role_mismatch,
    dispatch_clock_out_of_bound or dispatch_clock_unverifiable;
  - a producer dispatch without a block is a violation (missing_block) only
    inside the active human-typed span (hooks/lib/command_span.active_span on
    the payload's transcript_path) of dev, redev, dev-command, dev-overnight,
    do, close or commit -- never keyed by .claude/dev-registry/<session_id>/;
  - a malformed block, an unregistered schema id or a bad prompt is rejected
    whatever the span.

Every assertion anchors on the subprocess exit code and/or stable tokens in
stderr/the advisory JSONL log -- never solely on a full free-text sentence
(backlog #118's control-flow-not-wording rule), mirroring
hooks/tests/test_do_block_subagents.py's style.

Fixture hygiene: every hook subprocess runs with HOME and CLAUDE_CONFIG_DIR
pinned to a per-test tmp dir (so the advisory log is
<tmp HOME>/.claude/logs/obligation-gate-advisory.jsonl, never the real one),
CLAUDE_PROJECT_DIR and cwd pinned to a per-test tmp project dir, and
PYTHONDONTWRITEBYTECODE=1 so no bytecode cache lands in the repository.
Transcripts follow the T1 order: the in-flight Agent tool_use is already the
transcript's last record when PreToolUse runs.
"""

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO_ROOT, "hooks", "pretool-obligation-gate.py")
ADVISORY_LOG_RELPATH = Path(".claude") / "logs" / "obligation-gate-advisory.jsonl"

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
TASK_ID = "20261019-103000"
DISPATCH_ID = "toolu_g1_dispatch"
# SPAN_COMMANDS_REQUIRING_BLOCK in hooks/pretool-obligation-gate.py (TC-41, D7).
GATED_SPAN_COMMANDS = ("dev", "redev", "dev-command", "dev-overnight", "do", "close", "commit")


# --------------------------------------------------------------------------
# Environment / subprocess
# --------------------------------------------------------------------------

def _dirs(tmp_path):
    """(home, project) under tmp_path; project has no .claude/ nor schemas/."""
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir(exist_ok=True)
    project.mkdir(exist_ok=True)
    return home, project


def _clean_env(home, project, switch=None):
    env = dict(os.environ)
    for key in SUBAGENT_ENV_KEYS:
        env.pop(key, None)
    env["HOME"] = str(home)
    # Transcripts live in the configuration directory; pin it to this HOME.
    env["CLAUDE_CONFIG_DIR"] = str(Path(home) / ".claude")
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if switch is None:
        env.pop("CLAUDE_OBLIGATION_GATE", None)
    else:
        env["CLAUDE_OBLIGATION_GATE"] = switch
    return env


def _run_hook(home, project, payload=None, raw_stdin=None, switch=None):
    data = raw_stdin if raw_stdin is not None else json.dumps(payload)
    return subprocess.run(
        [sys.executable, HOOK],
        input=data,
        capture_output=True,
        text=True,
        cwd=str(project),
        env=_clean_env(home, project, switch),
    )


def _unique_sid(label="gate"):
    return f"test-obligation-{label}-{uuid.uuid4().hex}"


def _advisory_log(home):
    return Path(home) / ADVISORY_LOG_RELPATH


def _advisory_records(home, sid=None):
    log = _advisory_log(home)
    if not log.is_file():
        return []
    records = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if sid is None or record.get("session_id") == sid:
            records.append(record)
    return records


# --------------------------------------------------------------------------
# Obligation blocks
# --------------------------------------------------------------------------

def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _block(doc):
    return '<obligation v="1">' + json.dumps(doc) + "</obligation>"


def _obligation_doc(role="dev", pipeline="dev", profile="singular", dispatched_at=None,
                    artifacts=None, task_id=TASK_ID):
    return {
        "task_id": task_id,
        "role": role,
        "pipeline": pipeline,
        "profile": profile,
        "dispatched_at": dispatched_at if dispatched_at is not None else _now_iso(),
        "artifacts": artifacts or [{"kind": "response_line", "terminal_line_regex": "^DONE$"}],
    }


def _valid_block(role="dev"):
    """A valid block for a dispatch whose subagent_type is ``role``: current
    dispatched_at, role equal to the subagent_type."""
    return _block(_obligation_doc(role=role))


def _malformed_block():
    """Missing the required 'profile' field -> Rejection(reason='missing_field')."""
    doc = _obligation_doc()
    del doc["profile"]
    return _block(doc)


def _ba_qa_report_block(schema="ba-qa-report.v1"):
    return _block(_obligation_doc(
        role="qa",
        profile="ba_validation",
        artifacts=[{
            "kind": "json",
            "path": f"docs/dev/ba-qa-report-{TASK_ID}.json",
            "schema": schema,
            "identity": {"task_id": TASK_ID},
        }],
    ))


# --------------------------------------------------------------------------
# Transcripts (T1 order; shapes from the P1 test brief)
# --------------------------------------------------------------------------

def _queue_operations():
    return [
        {"type": "queue-operation", "operation": "enqueue", "timestamp": _now_iso(),
         "content": "queued prompt"},
        {"type": "queue-operation", "operation": "dequeue", "timestamp": _now_iso()},
    ]


def _command_tag_text(name, args=""):
    return (
        f"<command-message>{name}</command-message>\n"
        f"<command-name>/{name}</command-name>\n"
        f"<command-args>{args}</command-args>"
    )


def _typed_command(name, args="implement the requirement", form="tag"):
    """A human-typed slash command followed by its isMeta command body."""
    if form == "tag":
        typed = {"type": "user", "isSidechain": False, "origin": {"kind": "human"},
                 "message": {"role": "user", "content": _command_tag_text(name, args)}}
    else:
        typed = {"type": "user", "isSidechain": False,
                 "message": {"role": "user", "content": f"/{name} {args}".rstrip()}}
    body = {"type": "user", "isSidechain": False, "isMeta": True,
            "message": {"role": "user",
                        "content": [{"type": "text", "text": f"Command body of {name}."}]}}
    return [typed, body]


def _plain_prompt(text="please help with this"):
    return {"type": "user", "isSidechain": False, "message": {"role": "user", "content": text}}


def _assistant_text(text="Working on it."):
    return {"type": "assistant", "isSidechain": False,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def _tool_use(tool_use_id, name, tool_input):
    return {"type": "assistant", "isSidechain": False,
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": tool_use_id, "name": name, "input": tool_input}]}}


def _skill_expansion(name, args, typed=False):
    """A Skill-tool expansion of /<name>: tool_use, tool_result, then the
    expansion record. ``typed=True`` strips the expansion's isMeta and
    sourceToolUseID markers (the control: then it reads as human-typed)."""
    use_id = f"toolu_skill_{name.replace('-', '_')}"
    expansion = {"type": "user", "isSidechain": False,
                 "message": {"role": "user",
                             "content": [{"type": "text", "text": _command_tag_text(name, args)}]}}
    if not typed:
        expansion["isMeta"] = True
        expansion["sourceToolUseID"] = use_id
    return [
        _tool_use(use_id, "Skill", {"skill": name, "args": args}),
        {"type": "user", "isSidechain": False, "toolUseResult": {"success": True},
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": use_id, "content": f"Launching skill: {name}"}]}},
        expansion,
    ]


def _command_in_tool_result(name, args, typed=False):
    """/<name> text that only appears inside a tool_result block (no other
    non-human marker on the record, so the block type alone must exclude it).
    ``typed=True`` puts the same text in a plain text block (the control)."""
    use_id = "toolu_bash_echo"
    text = _command_tag_text(name, args)
    block = ({"type": "text", "text": text} if typed
             else {"type": "tool_result", "tool_use_id": use_id, "content": text})
    result = {"type": "user", "isSidechain": False, "message": {"role": "user", "content": [block]}}
    return [_tool_use(use_id, "Bash", {"command": "cat notes.txt"}), result]


def _dispatch_payload(directory, sid, records, subagent_type="dev", prompt="do work",
                      tool_input=None):
    """Write ``records`` plus the in-flight Agent tool_use (T1) to a transcript
    and return the PreToolUse payload naming it."""
    if tool_input is None:
        tool_input = {"subagent_type": subagent_type, "prompt": prompt}
    transcript = Path(directory) / f"{sid}.jsonl"
    lines = list(records) + [_tool_use(DISPATCH_ID, "Agent", tool_input)]
    transcript.write_text("".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")
    return {
        "session_id": sid,
        "transcript_path": str(transcript),
        "cwd": str(directory),
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "tool_input": tool_input,
        "tool_use_id": DISPATCH_ID,
    }


def _span_records(command, form="tag"):
    """queue-operation pair, a typed /<command>, an assistant reply."""
    return _queue_operations() + _typed_command(command, form=form) + [_assistant_text()]


def _no_span_records():
    return _queue_operations() + [_plain_prompt(), _assistant_text()]


# --------------------------------------------------------------------------
# Existing acceptance cases (AC-L1-01..14), pinned to the P1 behaviour
# --------------------------------------------------------------------------

def test_AC_L1_01_valid_block_always_passes(tmp_path):
    """AC-L1-01: well-formed block (current dispatched_at, role ==
    subagent_type) inside a /dev span, any switch mode -> exit 0, no advisory."""
    home, project = _dirs(tmp_path)
    for switch in (None, "advisory", "block", "garbage-value"):
        sid = _unique_sid("ac01")
        payload = _dispatch_payload(project, sid, _span_records("dev"),
                                    prompt="do work\n" + _valid_block("dev"))
        result = _run_hook(home, project, payload, switch=switch)
        assert result.returncode == 0, f"switch={switch!r}: {result.stderr}"
        assert _advisory_records(home, sid) == []


def test_AC_L1_02_missing_block_active_session_advisory_logs_and_passes(tmp_path):
    """AC-L1-02: no block, advisory, active /dev span (no dev-registry dir
    anywhere) -> exit 0 + one advisory line with ts/session_id/subagent_type/
    reason=missing_block."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("ac02")
    payload = _dispatch_payload(project, sid, _span_records("dev"), prompt="do work, no block")
    assert not (project / ".claude" / "dev-registry").exists()
    result = _run_hook(home, project, payload)
    assert result.returncode == 0
    records = _advisory_records(home, sid)
    assert len(records) == 1, records
    record = records[0]
    for field in ("ts", "session_id", "subagent_type", "reason"):
        assert field in record, f"missing field {field!r} in {record}"
    assert record["reason"] == "missing_block"
    assert record["subagent_type"] == "dev"


def test_AC_L1_03_missing_block_no_active_session_silent_pass(tmp_path):
    """AC-L1-03: no block, no gated span -> exit 0, nothing logged, in advisory
    and block mode -- even though .claude/dev-registry/<session_id>/ exists in
    CLAUDE_PROJECT_DIR (the retired dev-registry trigger no longer counts)."""
    home, project = _dirs(tmp_path)
    for switch in (None, "block"):
        sid = _unique_sid("ac03")
        (project / ".claude" / "dev-registry" / sid).mkdir(parents=True)
        payload = _dispatch_payload(project, sid, _no_span_records(), prompt="do work, no block")
        result = _run_hook(home, project, payload, switch=switch)
        assert result.returncode == 0, f"switch={switch!r}: {result.stderr}"
        assert BLOCK_BANNER not in result.stderr
        assert _advisory_records(home, sid) == []


def test_AC_L1_04_missing_block_active_session_block_mode_rejects(tmp_path):
    """AC-L1-04: no block, block mode, active /dev span -> exit 2, stderr names
    what's missing, whose responsibility it is, and the fix."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("ac04")
    payload = _dispatch_payload(project, sid, _span_records("dev"), prompt="do work, no block")
    result = _run_hook(home, project, payload, switch="block")
    assert result.returncode == 2
    assert BLOCK_BANNER in result.stderr
    for token in ("obligation", "orchestrator", "<obligation", "reason=missing_block"):
        assert token in result.stderr, f"missing token {token!r} in {result.stderr}"
    # Block mode still logs (log-then-decide ordering, turn-1 microstep 4a).
    records = _advisory_records(home, sid)
    assert len(records) == 1, records
    assert records[0]["reason"] == "missing_block"


def test_AC_L1_05_malformed_block_advisory_logs_validator_reason(tmp_path):
    """AC-L1-05: malformed block, advisory, active /dev span -> exit 0 +
    advisory reason carries the validator's specific rejection reason."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("ac05")
    payload = _dispatch_payload(project, sid, _span_records("dev"),
                                prompt="do work\n" + _malformed_block())
    result = _run_hook(home, project, payload)
    assert result.returncode == 0
    records = _advisory_records(home, sid)
    assert len(records) == 1, records
    assert records[0]["reason"] == "missing_field"


def test_AC_L1_06_malformed_block_block_mode_rejects_with_reason(tmp_path):
    """AC-L1-06: same malformed block, block mode -> exit 2, stderr includes
    the specific validator reason (not a generic message)."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("ac06")
    payload = _dispatch_payload(project, sid, _span_records("dev"),
                                prompt="do work\n" + _malformed_block())
    result = _run_hook(home, project, payload, switch="block")
    assert result.returncode == 2
    assert "missing_field" in result.stderr


def test_AC_L1_07_non_producer_role_always_passes_untouched(tmp_path):
    """AC-L1-07: subagent_type outside the producer set and no "<obligation"
    in the prompt -> exit 0 unconditionally, no advisory, even in block mode
    inside a gated /dev span."""
    home, project = _dirs(tmp_path)
    for subagent_type in ("architect", "ui-specialist", "general-purpose", None):
        sid = _unique_sid("ac07")
        payload = _dispatch_payload(project, sid, _span_records("dev"),
                                    subagent_type=subagent_type, prompt="do work, no block")
        result = _run_hook(home, project, payload, switch="block")
        assert result.returncode == 0, subagent_type
        assert _advisory_records(home, sid) == []


def test_AC_L1_08_switch_off_is_unconditional(tmp_path):
    """AC-L1-08: CLAUDE_OBLIGATION_GATE=off -> exit 0 before any other check,
    no advisory, even for a missing-block producer dispatch in a /dev span and
    for a malformed block."""
    home, project = _dirs(tmp_path)
    for prompt in ("do work, no block", "do work\n" + _malformed_block()):
        sid = _unique_sid("ac08")
        payload = _dispatch_payload(project, sid, _span_records("dev"), prompt=prompt)
        result = _run_hook(home, project, payload, switch="off")
        assert result.returncode == 0
        assert _advisory_records(home, sid) == []


def test_AC_L1_09_internal_crash_still_exits_0(tmp_path):
    """AC-L1-09: malformed/empty stdin raises inside the fail-open wrapper ->
    caught, advisory reason=gate_error written best-effort, exit 0."""
    home, project = _dirs(tmp_path)
    for count, raw_stdin in enumerate(("this is not json {", ""), 1):
        result = _run_hook(home, project, raw_stdin=raw_stdin, switch="block")
        assert result.returncode == 0
        gate_errors = [
            r for r in _advisory_records(home)
            if r.get("reason") == "gate_error" and r.get("session_id") is None
        ]
        assert len(gate_errors) == count, gate_errors


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


def test_AC_L1_11_advisory_mode_zero_behavioral_change(tmp_path):
    """AC-L1-11: on the pre-rollout shape (no obligation block anywhere, no
    gated span: a payload without transcript_path, or a transcript of plain
    prompts), advisory mode is silent -- exit 0, empty stdout/stderr,
    identical to the hook not existing."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("ac11")
    with_transcript = _dispatch_payload(project, sid, _no_span_records(),
                                        prompt="an ordinary pre-rollout dispatch")
    without_transcript = dict(with_transcript)
    del without_transcript["transcript_path"]
    for payload in (without_transcript, with_transcript):
        result = _run_hook(home, project, payload)
        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""
    assert _advisory_records(home, sid) == []


def test_AC_L1_12_block_then_fixed_dispatch_passes(tmp_path):
    """AC-L1-12 (injected-error suite item 6): block mode rejects a stripped
    dispatch in a /dev span, then the same prompt with a valid block appended
    passes."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("ac12")
    base_prompt = "producer dispatch body"
    first = _run_hook(home, project, _dispatch_payload(
        project, sid, _span_records("dev"), prompt=base_prompt), switch="block")
    assert first.returncode == 2
    assert BLOCK_BANNER in first.stderr
    second = _run_hook(home, project, _dispatch_payload(
        project, sid, _span_records("dev"), prompt=base_prompt + "\n" + _valid_block("dev")),
        switch="block")
    assert second.returncode == 0, second.stderr


def test_AC_L1_13_malformed_block_unconditional_no_active_session(tmp_path):
    """AC-L1-13: malformed block, advisory, NO gated span -> still exits 0 and
    logs the validator's reason (Rejection is unconditional, unlike NoBlock's
    AC-L1-03 gating)."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("ac13")
    payload = _dispatch_payload(project, sid, _no_span_records(),
                                prompt="do work\n" + _malformed_block())
    result = _run_hook(home, project, payload)
    assert result.returncode == 0
    records = _advisory_records(home, sid)
    assert len(records) == 1, records
    assert records[0]["reason"] == "missing_field"


def test_AC_L1_14_absent_prompt_routes_to_bad_prompt_rejection(tmp_path):
    """AC-L1-14: tool_input.prompt absent/non-string -> extract_obligation_block
    returns Rejection(reason='bad_prompt') -- routed through Rejection, not
    NoBlock -- advisory logs reason=bad_prompt, exit 0."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("ac14")
    payload = _dispatch_payload(project, sid, _span_records("dev"),
                                tool_input={"subagent_type": "dev"})  # no "prompt" key at all
    result = _run_hook(home, project, payload)
    assert result.returncode == 0
    records = _advisory_records(home, sid)
    assert len(records) == 1, records
    assert records[0]["reason"] == "bad_prompt"


# --------------------------------------------------------------------------
# P1 acceptance test 3 (G1 with CLAUDE_OBLIGATION_GATE=block)
# --------------------------------------------------------------------------

def _two_hours_ago():
    stamp = datetime.now(timezone.utc) - timedelta(hours=2)
    return stamp.isoformat(timespec="seconds").replace("+00:00", "Z")


def _naive_now():
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _dev_report_without_identity():
    return [{"kind": "json", "path": f"docs/dev/dev-report-{TASK_ID}.json", "schema": "dev-report.v2"}]


# case id -> (records(), subagent_type, prompt(), expected reason). Builders run
# at test time so every "current" dispatched_at is current when the hook runs.
VIOLATION_CASES = {
    # a: a /dev span opened after the 2 leading queue-operation records.
    "a_dev_span_after_queue_ops_ba_missing_block": (
        lambda: _span_records("dev", form="tag"), "ba",
        lambda: "Requirement: build it", "missing_block"),
    "a_dev_span_slash_form_ba_missing_block": (
        lambda: _span_records("dev", form="slash"), "ba",
        lambda: "Requirement: build it", "missing_block"),
    # b: D7 -- a dev obligation inside a /close span is validated like /dev's.
    "b_close_span_dev_obligation_without_identity": (
        lambda: _span_records("close"), "dev",
        lambda: "fix the findings\n" + _block(_obligation_doc(
            role="dev", pipeline="close", artifacts=_dev_report_without_identity())),
        "missing_field"),
    # c: a schema id the harness registry does not hold.
    "c_unregistered_schema_ba_qa_report_v9": (
        lambda: _span_records("dev"), "qa",
        lambda: "validate the BA output\n" + _ba_qa_report_block("ba-qa-report.v9"),
        "unregistered_schema"),
    # d: dispatched_at outside the 300 s bound.
    "d_dispatched_at_two_hours_old": (
        lambda: _span_records("dev"), "dev",
        lambda: "do work\n" + _block(_obligation_doc(role="dev", dispatched_at=_two_hours_ago())),
        "dispatch_clock_out_of_bound"),
    # d': a naive timestamp is uncomparable with the aware clock -> fails closed.
    "d_dispatched_at_naive_unverifiable": (
        lambda: _span_records("dev"), "dev",
        lambda: "do work\n" + _block(_obligation_doc(role="dev", dispatched_at=_naive_now())),
        "dispatch_clock_unverifiable"),
    # e: obligation role differs from the dispatch's subagent_type.
    "e_role_graphify_subagent_dev": (
        lambda: _span_records("dev"), "dev",
        lambda: "do work\n" + _valid_block("graphify"), "role_mismatch"),
    # f: a non-producer dispatch carrying "<obligation" is validated too.
    "f_general_purpose_malformed_obligation": (
        _no_span_records, "general-purpose",
        lambda: 'research this\n<obligation v="1">{"task_id": </obligation>', "malformed_json"),
    # i: profile "repair" is outside the grammar and bypasses nothing.
    "i_repair_profile": (
        lambda: _span_records("dev"), "dev",
        lambda: "repair it\n" + _block(_obligation_doc(role="dev", profile="repair")),
        "unknown_enum_value"),
}


def _violation_payload(project, sid, case_id):
    records, subagent_type, prompt, reason = VIOLATION_CASES[case_id]
    payload = _dispatch_payload(project, sid, records(), subagent_type=subagent_type,
                                prompt=prompt())
    return payload, subagent_type, reason


@pytest.mark.parametrize("case_id", sorted(VIOLATION_CASES))
def test_G1_block_mode_rejects_violation(tmp_path, case_id):
    """Acceptance 3 (a-f, i) under CLAUDE_OBLIGATION_GATE=block: exit 2, the
    stderr banner names the specific reason, and the violation is logged."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("g1blk")
    payload, subagent_type, reason = _violation_payload(project, sid, case_id)
    result = _run_hook(home, project, payload, switch="block")
    assert result.returncode == 2, f"{case_id}: rc={result.returncode} stderr={result.stderr}"
    assert BLOCK_BANNER in result.stderr
    assert f"reason={reason}" in result.stderr, result.stderr
    records = _advisory_records(home, sid)
    assert [(r["reason"], r["subagent_type"]) for r in records] == [(reason, subagent_type)]


@pytest.mark.parametrize("case_id", sorted(VIOLATION_CASES))
def test_G1_switch_unset_advisory_records_violation(tmp_path, case_id):
    """Acceptance 3 (k): the same cases with CLAUDE_OBLIGATION_GATE unset ->
    exit 0, no block message, and one advisory record in
    <HOME>/.claude/logs/obligation-gate-advisory.jsonl carrying the reason."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("g1adv")
    payload, subagent_type, reason = _violation_payload(project, sid, case_id)
    result = _run_hook(home, project, payload)
    assert result.returncode == 0, f"{case_id}: {result.stderr}"
    assert BLOCK_BANNER not in result.stderr
    assert _advisory_log(home).is_file()
    records = _advisory_records(home, sid)
    assert len(records) == 1, records
    record = records[0]
    for field in ("ts", "session_id", "subagent_type", "reason"):
        assert field in record, f"missing field {field!r} in {record}"
    assert (record["reason"], record["subagent_type"]) == (reason, subagent_type)


@pytest.mark.parametrize("command", GATED_SPAN_COMMANDS)
def test_G1_gated_span_producer_without_block_rejects(tmp_path, command):
    """TC-41/D7: every span in SPAN_COMMANDS_REQUIRING_BLOCK turns a producer
    dispatch without a block into missing_block (exit 2 in block mode)."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("g1span")
    payload = _dispatch_payload(project, sid, _span_records(command),
                                subagent_type="dev", prompt="do work, no block")
    result = _run_hook(home, project, payload, switch="block")
    assert result.returncode == 2, f"/{command}: {result.stderr}"
    assert "reason=missing_block" in result.stderr


@pytest.mark.parametrize("records", [
    pytest.param(lambda: _span_records("spec"), id="spec_span"),
    pytest.param(lambda: _span_records("dev") + _typed_command("spec") + [_assistant_text()],
                 id="dev_then_spec_latest_span_wins"),
])
def test_G1_spec_span_qa_without_obligation_passes(tmp_path, records):
    """Acceptance 3 (g): a QA dispatch without an obligation inside a /spec
    span (the active span, even after an earlier /dev) -> exit 0 in block
    mode, nothing logged."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("g1spec")
    payload = _dispatch_payload(project, sid, records(), subagent_type="qa",
                                prompt="judge the spec, no block")
    result = _run_hook(home, project, payload, switch="block")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert _advisory_records(home, sid) == []


def test_G1_product_repo_without_schemas_loads_harness_registry(tmp_path):
    """Acceptance 3 (h): CLAUDE_PROJECT_DIR and cwd are a product repo with no
    schemas/ -> a valid ba-qa-report.v1 obligation passes in block mode (the
    schema ids come from the harness's own schemas/registry.json)."""
    home, project = _dirs(tmp_path)
    assert not (project / "schemas").exists()
    sid = _unique_sid("g1prod")
    payload = _dispatch_payload(project, sid, _span_records("dev-command"), subagent_type="qa",
                                prompt="validate the BA output\n" + _ba_qa_report_block())
    result = _run_hook(home, project, payload, switch="block")
    assert result.returncode == 0, result.stderr
    assert _advisory_records(home, sid) == []


@pytest.mark.parametrize("opener", [
    pytest.param(_skill_expansion, id="skill_expansion"),
    pytest.param(_command_in_tool_result, id="tool_result"),
])
def test_G1_non_typed_dev_opens_no_span(tmp_path, opener):
    """Acceptance 3 (j): /dev that only appears in a Skill-tool expansion
    record (isMeta, sourceToolUseID) or inside a tool_result opens no span, so
    a ba dispatch without an obligation exits 0 in block mode, nothing logged.
    Control: the same text as a human-typed record does open the /dev span."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("g1j")
    payload = _dispatch_payload(
        project, sid, _no_span_records() + opener("dev", "build it") + [_assistant_text()],
        subagent_type="ba", prompt="Requirement: build it")
    result = _run_hook(home, project, payload, switch="block")
    assert result.returncode == 0, result.stderr
    assert _advisory_records(home, sid) == []

    control_sid = _unique_sid("g1jctl")
    control = _dispatch_payload(
        project, control_sid,
        _no_span_records() + opener("dev", "build it", typed=True) + [_assistant_text()],
        subagent_type="ba", prompt="Requirement: build it")
    controlled = _run_hook(home, project, control, switch="block")
    assert controlled.returncode == 2, controlled.stderr
    assert "reason=missing_block" in controlled.stderr
