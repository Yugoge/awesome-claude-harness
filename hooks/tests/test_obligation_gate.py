#!/usr/bin/env python3
"""Regression coverage for hooks/pretool-obligation-gate.py (G1 dispatch gate).

G1 is the first of five enforcement doors (spec-20260930-092323) that move
artifact-completeness detection from /close and /commit time -- where the
producing agent's context is already gone -- to the dispatch moment. It runs
on every Agent dispatch whose prompt contains "<obligation" (any
subagent_type) or whose tool_input.subagent_type is a role the active
command's dispatch templates declare an obligation for (read from the
command's text the CLI recorded when it was typed, else from
commands/<command>.md, P1b row 18), and evaluates the
dispatch prompt's <obligation v="1"> block with hooks/lib/obligation.py's
parse_obligation() (never re-implemented here) against the harness's own
schemas/registry.json, allowing (advisory mode) or rejecting (block mode,
CLAUDE_OBLIGATION_GATE=block) when it is not valid.

P1 behaviour pinned here:
  - a valid block carries a current dispatched_at (within 300 s of now) and
    a role equal to the dispatch's subagent_type; otherwise role_mismatch,
    dispatch_clock_out_of_bound or dispatch_clock_unverifiable;
  - a dispatch without a block is a violation (missing_block) only inside
    the active human-typed span (hooks/lib/command_span.active_span on the
    payload's transcript_path) of a command whose templates declare an
    obligation for its subagent_type (/redev's are /dev's) -- never keyed by
    .claude/dev-registry/<session_id>/ and never by a list of commands;
  - a malformed block, an unregistered schema id or a bad prompt is rejected
    whatever the span.

Every assertion anchors on the subprocess exit code and/or stable tokens in
stderr -- never solely on a full free-text sentence
(backlog #118's control-flow-not-wording rule), mirroring
hooks/tests/test_do_block_subagents.py's style.

Fixture hygiene: every hook subprocess runs with HOME and CLAUDE_CONFIG_DIR
pinned to a per-test tmp dir (never the real one), CLAUDE_PROJECT_DIR and
cwd pinned to a per-test tmp project dir, and
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
# P4 R9: the advisory switch's one stderr line, the would-block reason.
ADVISORY_BANNER = "OBLIGATION GATE ADVISORY"
TASK_ID = "20261019-103000"
DISPATCH_ID = "toolu_g1_dispatch"
# (command, a role its dispatch templates declare an obligation for) (TC-41, D7).
DECLARING_SPANS = (
    ("dev", "ba"), ("redev", "ba"), ("dev-command", "ba"), ("dev-overnight", "pm"),
    ("close", "qa"), ("close", "dev"), ("commit", "changelog-analyst"), ("commit", "dev"), ("spec", "spec"),
    ("merge", "merge-analyst"), ("push", "push-analyst"),
)


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


def _written_logs(home):
    """Files under the scratch home's logs/ directory: the gate writes none."""
    logs = Path(home) / ".claude" / "logs"
    return sorted(p.name for p in logs.rglob("*")) if logs.is_dir() else []


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
    subagent_type) inside a /dev span, any switch mode -> exit 0, nothing
    written."""
    home, project = _dirs(tmp_path)
    for switch in (None, "advisory", "block", "garbage-value"):
        sid = _unique_sid("ac01")
        payload = _dispatch_payload(project, sid, _span_records("dev"),
                                    prompt="do work\n" + _valid_block("dev"))
        result = _run_hook(home, project, payload, switch=switch)
        assert result.returncode == 0, f"switch={switch!r}: {result.stderr}"
        assert _written_logs(home) == []


def test_AC_L1_02_missing_block_active_session_advisory_passes(tmp_path):
    """AC-L1-02: no block, advisory, active /dev span (no dev-registry dir
    anywhere) -> exit 0, no block message, the would-block reason on one
    stderr line, nothing written."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("ac02")
    payload = _dispatch_payload(project, sid, _span_records("dev"), prompt="do work, no block")
    assert not (project / ".claude" / "dev-registry").exists()
    result = _run_hook(home, project, payload)
    assert result.returncode == 0
    assert BLOCK_BANNER not in result.stderr
    assert result.stderr.startswith(ADVISORY_BANNER) and result.stderr.count("\n") == 1, result.stderr
    assert "reason=missing_block" in result.stderr
    assert _written_logs(home) == []


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
        assert _written_logs(home) == []


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
    assert _written_logs(home) == []


def test_AC_L1_05_malformed_block_advisory_passes(tmp_path):
    """AC-L1-05: malformed block, advisory, active /dev span -> exit 0, no
    block message, the validator's reason on the advisory stderr line,
    nothing written (AC-L1-06 pins the reason in block mode)."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("ac05")
    payload = _dispatch_payload(project, sid, _span_records("dev"),
                                prompt="do work\n" + _malformed_block())
    result = _run_hook(home, project, payload)
    assert result.returncode == 0
    assert BLOCK_BANNER not in result.stderr
    assert ADVISORY_BANNER in result.stderr and "reason=missing_field" in result.stderr, result.stderr
    assert _written_logs(home) == []


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
    in the prompt -> exit 0 unconditionally, nothing written, even in block
    mode inside a gated /dev span."""
    home, project = _dirs(tmp_path)
    for subagent_type in ("architect", "ui-specialist", "general-purpose", None):
        sid = _unique_sid("ac07")
        payload = _dispatch_payload(project, sid, _span_records("dev"),
                                    subagent_type=subagent_type, prompt="do work, no block")
        result = _run_hook(home, project, payload, switch="block")
        assert result.returncode == 0, subagent_type
        assert _written_logs(home) == []


def test_AC_L1_08_switch_off_is_unconditional(tmp_path):
    """AC-L1-08: CLAUDE_OBLIGATION_GATE=off -> exit 0 before any other check,
    nothing written, even for a missing-block producer dispatch in a /dev span
    and for a malformed block."""
    home, project = _dirs(tmp_path)
    for prompt in ("do work, no block", "do work\n" + _malformed_block()):
        sid = _unique_sid("ac08")
        payload = _dispatch_payload(project, sid, _span_records("dev"), prompt=prompt)
        result = _run_hook(home, project, payload, switch="off")
        assert result.returncode == 0
        assert _written_logs(home) == []


def test_AC_L1_09_internal_crash_still_exits_0(tmp_path):
    """AC-L1-09: malformed/empty stdin raises inside the fail-open wrapper ->
    caught, nothing written, exit 0."""
    home, project = _dirs(tmp_path)
    for raw_stdin in ("this is not json {", ""):
        result = _run_hook(home, project, raw_stdin=raw_stdin, switch="block")
        assert result.returncode == 0
        assert _written_logs(home) == []


def test_AC_L1_10_settings_json_registration_additive_only():
    """AC-L1-10: the matcher="Agent" PreToolUse group runs pretool-obligation-gate.py exactly once;
    since P12 the group is the dispatch gate (hooks/pretool-dispatch-gate.py), which runs it as one
    refuse rule, beside the hooks that shared the group with it."""
    settings_path = Path(REPO_ROOT) / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    agent_groups = [g for g in data["hooks"]["PreToolUse"] if g.get("matcher") == "Agent"]
    assert len(agent_groups) == 1
    commands = [h["command"] for h in agent_groups[0]["hooks"]]
    assert len(commands) == 1 and commands[0].rstrip('"').endswith("/hooks/pretool-dispatch-gate.py"), commands
    gate = Path(REPO_ROOT) / "hooks" / "pretool-dispatch-gate.py"
    ns = {"__name__": "gate", "__file__": str(gate)}
    exec(compile(gate.read_text(encoding="utf-8"), str(gate), "exec"), ns)
    rules = {Path(r.path).name if r.path else r.call: r.kind for r in ns["RULES"]}
    assert rules.get("pretool-obligation-gate.py") == "refuse", rules
    assert [r.path for r in ns["RULES"]].count(str(gate.parent / "pretool-obligation-gate.py")) == 1
    # The pre-existing siblings still run on the dispatch: four as the gate's rules, and the two
    # anti-loop hooks' checks (layer escalation, bisect) as lib/dev_loop_checks.py's advice.
    for sibling in (
        "pretool-spec-block-foreground-agent.py",
        "pretool-orchestrator-prompt-purity.py",
        "pretool-aggregate-check.py",
        "pretool-gitignore-preflight.py",
        "lib.dev_loop_checks:advice",
    ):
        assert sibling in rules, f"missing sibling hook {sibling}"


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
    assert _written_logs(home) == []


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
    """AC-L1-13: malformed block, NO gated span -> block mode still rejects it
    with the validator's reason (Rejection is unconditional, unlike NoBlock's
    AC-L1-03 gating)."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("ac13")
    payload = _dispatch_payload(project, sid, _no_span_records(),
                                prompt="do work\n" + _malformed_block())
    result = _run_hook(home, project, payload, switch="block")
    assert result.returncode == 2
    assert "reason=missing_field at profile)" in result.stderr, result.stderr


def test_G1_names_the_field_a_pre_p1_template_fails(tmp_path):
    """P1c F7: a dispatch from the pre-P1 template (its json artifact still
    carries required_values) is refused naming the check and the field it
    fails, so the orchestrator's next round knows which template to send."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("f7")
    doc = _obligation_doc(role="dev")
    doc["artifacts"][0]["required_values"] = {"dev.status": ["completed"]}
    prompt = "do work\n" + _block(doc)
    result = _run_hook(home, project, _dispatch_payload(project, sid, _span_records("dev"), prompt=prompt),
                       switch="block")
    assert result.returncode == 2
    assert "reason=unknown_field at artifacts[0].required_values)" in result.stderr, result.stderr


def test_AC_L1_14_absent_prompt_routes_to_bad_prompt_rejection(tmp_path):
    """AC-L1-14: tool_input.prompt absent/non-string -> extract_obligation_block
    returns Rejection(reason='bad_prompt') -- routed through Rejection, not
    NoBlock -- block mode rejects it with reason=bad_prompt."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("ac14")
    payload = _dispatch_payload(project, sid, _span_records("dev"),
                                tool_input={"subagent_type": "dev"})  # no "prompt" key at all
    result = _run_hook(home, project, payload, switch="block")
    assert result.returncode == 2
    assert "reason=bad_prompt" in result.stderr, result.stderr


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
    stderr banner names the specific reason, and nothing is written."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("g1blk")
    payload, subagent_type, reason = _violation_payload(project, sid, case_id)
    result = _run_hook(home, project, payload, switch="block")
    assert result.returncode == 2, f"{case_id}: rc={result.returncode} stderr={result.stderr}"
    assert BLOCK_BANNER in result.stderr
    assert f"reason={reason}" in result.stderr, result.stderr
    assert f"subagent_type={subagent_type}" in result.stderr, result.stderr
    assert _written_logs(home) == []


@pytest.mark.parametrize("case_id", sorted(VIOLATION_CASES))
def test_G1_switch_unset_advisory_passes_violation(tmp_path, case_id):
    """Acceptance 3 (k): the same cases with CLAUDE_OBLIGATION_GATE unset or
    advisory -> exit 0, no block message, the reason the block would name on
    one stderr line (P4 R9), nothing written."""
    home, project = _dirs(tmp_path)
    for switch in (None, "advisory"):
        sid = _unique_sid("g1adv")
        payload, subagent_type, reason = _violation_payload(project, sid, case_id)
        result = _run_hook(home, project, payload, switch=switch)
        assert result.returncode == 0, f"{case_id}: {result.stderr}"
        assert BLOCK_BANNER not in result.stderr
        assert result.stderr.startswith(ADVISORY_BANNER), result.stderr
        assert f"reason={reason}" in result.stderr and f"subagent_type={subagent_type}" in result.stderr
        assert _written_logs(home) == []


@pytest.mark.parametrize("command,role", DECLARING_SPANS)
def test_G1_gated_span_producer_without_block_rejects(tmp_path, command, role):
    """TC-41/D7: inside a command's span, a dispatch of a role that command's
    templates declare an obligation for (/redev's are /dev's) without a block
    is missing_block (exit 2 in block mode)."""
    home, project = _dirs(tmp_path)
    sid = _unique_sid("g1span")
    payload = _dispatch_payload(project, sid, _span_records(command),
                                subagent_type=role, prompt="do work, no block")
    result = _run_hook(home, project, payload, switch="block")
    assert result.returncode == 2, f"/{command}: {result.stderr}"
    assert "reason=missing_block" in result.stderr


@pytest.mark.parametrize("command,subagent_type", [
    ("do", "dev"), ("close", "ba"), ("commit", "ba"), ("merge", "dev"), ("push", "qa"),
])
def test_G1_role_the_active_command_declares_no_template_for_passes(tmp_path, command, subagent_type):
    """No list of commands requires a block: /do's text declares no template,
    /close's and /commit's none for ba (another command's template for that
    role does not count; their own dev template, the dev that completes a /do
    task's work, does), /merge's and /push's none but their analyst's.
    Each such dispatch without a block passes in block mode."""
    home, project = _dirs(tmp_path)
    payload = _dispatch_payload(project, _unique_sid("g1nodecl"), _span_records(command),
                                subagent_type=subagent_type, prompt="do work, no block")
    result = _run_hook(home, project, payload, switch="block")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


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
    assert _written_logs(home) == []


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
    assert _written_logs(home) == []


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
    assert _written_logs(home) == []

    control_sid = _unique_sid("g1jctl")
    control = _dispatch_payload(
        project, control_sid,
        _no_span_records() + opener("dev", "build it", typed=True) + [_assistant_text()],
        subagent_type="ba", prompt="Requirement: build it")
    controlled = _run_hook(home, project, control, switch="block")
    assert controlled.returncode == 2, controlled.stderr
    assert "reason=missing_block" in controlled.stderr


# --------------------------------------------------------------------------
# P1b row 18: which dispatches must carry a block is read from the command
# templates' obligation declarations -- no role list, and not the roster
# --------------------------------------------------------------------------

@pytest.mark.parametrize("command,subagent_type", [
    ("dev", "graphify"), ("redev", "graphify"), ("dev-overnight", "graphify"),
    ("dev", "architect"), ("dev", "ui-specialist"), ("dev", "product-owner"), ("dev", "user"),
])
def test_G1_dispatch_no_template_declares_a_block_for_passes(tmp_path, command, subagent_type):
    """/dev dispatches graphify (Step 9) and its specialists (Step 3) without
    a block: inside a gated span, in block mode, each passes untouched."""
    home, project = _dirs(tmp_path)
    payload = _dispatch_payload(project, _unique_sid("g1decl"), _span_records(command),
                                subagent_type=subagent_type, prompt="do work, no block")
    result = _run_hook(home, project, payload, switch="block")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def _gate_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("pretool_obligation_gate_under_test", HOOK)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return gate


def test_G1_declared_roles_come_from_the_active_command_templates():
    """Each command's set is derived from its own commands/<command>.md at run
    time: every role is an agent of the roster, each producer whose template
    declares a block is in its command's set, graphify, which no template
    gives a block, is in none, /redev has /dev's (its canonical todo is
    /dev's) and a command without templates has none."""
    sys.path.insert(0, os.path.join(REPO_ROOT, "hooks"))
    from lib import roster

    gate = _gate_module()
    declared = {command: gate._declared_roles(command)
                for command in ("dev", "redev", "dev-command", "dev-overnight", "close", "commit",
                                "spec", "do", "merge", "push")}
    assert all(roles <= roster.roles() for roles in declared.values())
    assert {"ba", "dev", "qa", "test-writer"} <= declared["dev"]
    assert declared["redev"] == declared["dev"]
    assert {"ba", "dev", "qa"} <= declared["dev-command"]
    assert {"pm", "ba", "dev", "qa"} <= declared["dev-overnight"]
    assert {"qa", "style-inspector", "cleanliness-inspector", "prompt-inspector"} <= declared["close"]
    assert {"qa", "changelog-analyst"} <= declared["commit"]
    assert declared["spec"] == {"spec"}
    assert declared["do"] == frozenset()
    # P1b E3's fallback: the analysts' templates declare their own obligation.
    assert declared["merge"] == {"merge-analyst"} and declared["push"] == {"push-analyst"}
    assert not any("graphify" in roles for roles in declared.values())


def test_G1_declared_roles_follow_the_command_files(tmp_path, monkeypatch):
    """No role or command is listed in the gate: a command file it is pointed
    at declares what it declares, and a missing command or todo file
    declares nothing (no error)."""
    gate = _gate_module()
    commands = tmp_path / "commands"
    todo = tmp_path / "scripts" / "todo"
    commands.mkdir()
    todo.mkdir(parents=True)
    (commands / "ship.md").write_text('---\n---\nembed it with role="qa", pipeline="ship"\n')
    (commands / "reship.md").write_text("---\n---\nRun the /ship workflow.\n")
    (todo / "reship.py").write_text("from ship import get_todos\n")
    monkeypatch.setattr(gate.stop_contract, "COMMANDS_DIR", commands)
    monkeypatch.setattr(sys.modules[gate.stop_contract.harness_commands.__module__], "COMMANDS_DIR", commands)
    monkeypatch.setattr(gate, "TODO_DIR", todo)
    assert gate._declared_roles("ship") == {"qa"}
    assert gate._declared_roles("reship") == {"qa"}
    assert gate._declared_roles("absent") == frozenset()
    # The text the session loaded, when given, is read in place of the file;
    # a command whose todo is another's still has that one's file.
    assert gate._declared_roles("ship", 'embed it with role="ba"') == {"ba"}
    assert gate._declared_roles("absent", 'embed it with role="ba"') == {"ba"}
    assert gate._declared_roles("reship", 'embed it with role="ba"') == {"qa"}


# --------------------------------------------------------------------------
# P2 acceptance 15 (live landing): a session follows the prose it loaded. The
# CLI records a typed command's text once, in the isMeta record whose
# parentUuid is the command record's uuid (measured on CLI 2.1.319: the file
# minus its frontmatter, $ARGUMENTS filled); a later edit of the file leaves
# that record as it was. G1 reads the declared roles from it.
# --------------------------------------------------------------------------

# A /dev-overnight text from before the update: its BA template declares an
# obligation, its PM templates none (origin/master's commands/dev-overnight.md).
LOADED_BEFORE_UPDATE = (
    "# /dev-overnight\n\n### Step 2: PM PLAN\n\nAgent(subagent_type: pm, prompt: \"PM_MODE: PLAN ...\")\n\n"
    "### Step 8: BA\n\nAgent(subagent_type: ba, prompt: \"... "
    '<obligation v="1">{"role":"ba","pipeline":"dev-overnight"}</obligation>")\n'
)


def _recorded_command(name, text, args="8h harden the toy package"):
    """A typed /<name> as the CLI records it: the command record, then the
    isMeta record of the text it loaded, linked by uuid and parentUuid."""
    typed = {"type": "user", "isSidechain": False, "origin": {"kind": "human"},
             "uuid": f"uuid-{name}-typed", "parentUuid": None,
             "message": {"role": "user", "content": _command_tag_text(name, args)}}
    loaded = {"type": "user", "isSidechain": False, "isMeta": True, "turnCompanion": True,
              "uuid": f"uuid-{name}-text", "parentUuid": typed["uuid"],
              "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
    return [typed, loaded]


def _shipped_text(name):
    """commands/<name>.md as the CLI records it when typed: frontmatter dropped."""
    text = Path(REPO_ROOT, "commands", f"{name}.md").read_text(encoding="utf-8")
    return text.split("\n---\n", 1)[1] if text.startswith("---\n") else text


@pytest.mark.parametrize("role,expected", [("pm", 0), ("ba", 2)])
def test_G1_session_started_before_an_update_is_held_to_the_prose_it_loaded(tmp_path, role, expected):
    """An overnight session typed before the update loaded a text whose PM
    templates declare no obligation, while commands/dev-overnight.md on disk
    now declares one for pm: its PM dispatch without a block passes in block
    mode, and its BA dispatch without one, which its own text declares, is
    still missing_block."""
    assert "pm" in _gate_module()._declared_roles("dev-overnight")  # the file on disk declares pm
    home, project = _dirs(tmp_path)
    records = _queue_operations() + _recorded_command("dev-overnight", LOADED_BEFORE_UPDATE) + [_assistant_text()]
    payload = _dispatch_payload(project, _unique_sid("g1loaded"), records,
                                subagent_type=role, prompt="PM_MODE: PLAN, no block")
    result = _run_hook(home, project, payload, switch="block")
    assert result.returncode == expected, result.stderr
    assert ("reason=missing_block" in result.stderr) == (expected == 2), result.stderr


def test_G1_session_on_the_new_prose_still_needs_its_pm_block(tmp_path):
    """A session typed after the update loaded the shipped text: its PM
    dispatch without a block is missing_block in block mode."""
    home, project = _dirs(tmp_path)
    records = (_queue_operations() + _recorded_command("dev-overnight", _shipped_text("dev-overnight"))
               + [_assistant_text()])
    payload = _dispatch_payload(project, _unique_sid("g1newprose"), records,
                                subagent_type="pm", prompt="PM_MODE: PLAN, no block")
    result = _run_hook(home, project, payload, switch="block")
    assert result.returncode == 2, result.stderr
    assert "reason=missing_block" in result.stderr


def test_G1_reads_the_file_when_no_record_holds_the_loaded_text(tmp_path):
    """No isMeta record links to the command record: the roles come from
    commands/dev-overnight.md, so a PM dispatch without a block is
    missing_block in block mode."""
    home, project = _dirs(tmp_path)
    typed, loaded = _recorded_command("dev-overnight", LOADED_BEFORE_UPDATE)
    loaded["parentUuid"] = "uuid-of-another-record"
    payload = _dispatch_payload(project, _unique_sid("g1unlinked"),
                                _queue_operations() + [typed, loaded, _assistant_text()],
                                subagent_type="pm", prompt="PM_MODE: PLAN, no block")
    result = _run_hook(home, project, payload, switch="block")
    assert result.returncode == 2, result.stderr
    assert "reason=missing_block" in result.stderr


# --------------------------------------------------------------------------
# R17: dispatch order, read from the active span's record of each dispatch
# and its returned result. A finding exits ORDER_EXIT (2 since the promotion
# commit; 0 in the warning commit before it).
# --------------------------------------------------------------------------

ORDER_BANNER = "OBLIGATION GATE ORDER"
ORDER_EXIT = 2
LANES = ["l1", "l2"]


def _returned(tool_use_id, refused=False):
    """The record of a dispatch's returned result (refused: a hook's is_error refusal)."""
    result = {"type": "tool_result", "tool_use_id": tool_use_id, "content": "returned"}
    if refused:
        result.update(content="PreToolUse hook refused the dispatch", is_error=True)
    return {"type": "user", "isSidechain": False, "message": {"role": "user", "content": [result]}}


def _stage(kind, task=TASK_ID, lane=None, extra=(), dispatched_at=None):
    """(subagent_type, prompt) of a /dev stage dispatch as commands/dev.md's
    templates write it: the input paths it names, its report path, its block."""
    context, ticket = f"docs/dev/context-{task}.json", f"docs/dev/ticket-{task}.md"
    dev_report = f"docs/dev/dev-report-{task}.json"

    def report(path, schema):
        return {"kind": "json", "path": path, "schema": schema, "identity": {"task_id": task}}

    role, profile, artifacts, inputs = {
        "ba": ("ba", "singular", [report(context, "context.v1"),
                                  {"kind": "markdown", "path": ticket, "identity_anchor": task}], []),
        "ba_qa": ("qa", "ba_validation", [report(f"docs/dev/ba-qa-report-{task}.json", "ba-qa-report.v1")],
                  [ticket, context]),
        "dev": ("dev", "singular", [report(dev_report, "dev-report.v2")], [context, ticket]),
        "qa": ("qa", "final_verification", [report(f"docs/dev/qa-report-{task}.json", "qa-report.v2")],
               [context, dev_report, ticket]),
    }[kind]
    doc = _obligation_doc(role=role, profile=profile, artifacts=artifacts, task_id=task,
                          dispatched_at=dispatched_at)
    if lane:
        doc.update(lane=lane, lane_set=LANES, profile="fanout-lane" if role != "qa" else profile)
    lines = [f"Input file: {path}" for path in list(inputs) + list(extra)]
    return role, "\n".join(lines + [f"Write your report to: {artifacts[0]['path']}", _block(doc)])


def _history(steps):
    """Records of earlier dispatches: (id, stage, returned) each, in order;
    returned is True, False (still running) or "refused"."""
    records = []
    for tool_use_id, (subagent_type, prompt), returned in steps:
        records.append(_tool_use(tool_use_id, "Agent", {"subagent_type": subagent_type, "prompt": prompt}))
        if returned:
            records.append(_returned(tool_use_id, refused=returned == "refused"))
    return records


def _order_run(home, project, steps, stage, opener="dev", switch="block", tail=()):
    subagent_type, prompt = stage
    payload = _dispatch_payload(project, _unique_sid("r17"),
                                _span_records(opener) + _history(steps) + list(tail),
                                subagent_type=subagent_type, prompt=prompt)
    return _run_hook(home, project, payload, switch=switch)


QA_FIX = (f"docs/dev/qa-report-{TASK_ID}.json",)
# A3/A12 (G1): the QA fail loops back to dev; the BA-QA fail loops back to BA.
DEV_LOOP = [("toolu_ba", _stage("ba"), True), ("toolu_baqa", _stage("ba_qa"), True),
            ("toolu_dev", _stage("dev"), True), ("toolu_qa", _stage("qa"), True)]
BA_LOOP = [("toolu_ba", _stage("ba"), True), ("toolu_baqa", _stage("ba_qa"), True)]


def test_R17_qa_before_redispatched_dev_returned_warns(tmp_path):
    """A QA dispatch issued while the re-dispatched dev has not returned:
    the warning names the dev-report and the dispatch declaring it."""
    home, project = _dirs(tmp_path)
    steps = DEV_LOOP + [("toolu_dev2", _stage("dev", extra=QA_FIX), False)]
    result = _order_run(home, project, steps, _stage("qa"))
    assert result.returncode == ORDER_EXIT, result.stderr
    assert ORDER_BANNER in result.stderr and BLOCK_BANNER not in result.stderr
    assert (f"reason=producer_not_stopped artifact=docs/dev/dev-report-{TASK_ID}.json: "
            "declared by dispatch toolu_dev2 (dev), which has not returned") in result.stderr


def test_R17_qa_after_redispatched_dev_returned_passes(tmp_path):
    home, project = _dirs(tmp_path)
    steps = DEV_LOOP + [("toolu_dev2", _stage("dev", extra=QA_FIX), True)]
    result = _order_run(home, project, steps, _stage("qa"))
    assert result.returncode == 0 and result.stderr == "", result.stderr


@pytest.mark.parametrize("ba2_returned", [True, False], ids=["ba_returned", "ba_running"])
def test_R17_dev_while_verdict_predates_redispatched_ba_stop_warns(tmp_path, ba2_returned):
    """A dev dispatch while the latest BA-QA verdict was issued before the
    re-dispatched BA returned (or while that BA still runs) warns."""
    home, project = _dirs(tmp_path)
    steps = BA_LOOP + [("toolu_ba2", _stage("ba"), ba2_returned)]
    result = _order_run(home, project, steps, _stage("dev"))
    assert result.returncode == ORDER_EXIT, result.stderr
    assert ORDER_BANNER in result.stderr
    if ba2_returned:
        assert (f"reason=verdict_not_after_producer_stop artifact=docs/dev/ba-qa-report-{TASK_ID}.json: "
                "the latest verdict on") in result.stderr
        assert "dispatch toolu_baqa (line" in result.stderr and "dispatch toolu_ba2 (ba)" in result.stderr
    else:
        assert "reason=producer_not_stopped artifact=docs/dev/context-" in result.stderr


@pytest.mark.parametrize("baqa2_returned", [True, False], ids=["verdict_returned", "verdict_running"])
def test_R17_dev_after_newer_verdict(tmp_path, baqa2_returned):
    """After a newer BA-QA dispatch issued once the re-dispatched BA
    returned: silent when it has returned, a finding while it runs."""
    home, project = _dirs(tmp_path)
    steps = BA_LOOP + [("toolu_ba2", _stage("ba"), True), ("toolu_baqa2", _stage("ba_qa"), baqa2_returned)]
    result = _order_run(home, project, steps, _stage("dev"))
    assert result.returncode == (0 if baqa2_returned else ORDER_EXIT)
    if baqa2_returned:
        assert result.stderr == "", result.stderr
    else:
        assert "dispatch toolu_baqa2 (line" in result.stderr and "not returned" in result.stderr


def test_R17_compliant_sequence_never_warns(tmp_path):
    """BA, BA-QA pass, dev, QA, then the QA-fail loop (dev, QA) and a
    BA-QA re-validation of a re-dispatched BA: no dispatch warns."""
    home, project = _dirs(tmp_path)
    sequence = [("toolu_ba", _stage("ba")), ("toolu_baqa", _stage("ba_qa")),
                ("toolu_dev", _stage("dev")), ("toolu_qa", _stage("qa")),
                ("toolu_dev2", _stage("dev", extra=QA_FIX)), ("toolu_qa2", _stage("qa"))]
    for index, (_id, stage) in enumerate(sequence):
        history = [(tool_use_id, earlier, True) for tool_use_id, earlier in sequence[:index]]
        result = _order_run(home, project, history, stage)
        assert result.returncode == 0 and result.stderr == "", f"dispatch {index}: {result.stderr}"
    result = _order_run(home, project, BA_LOOP + [("toolu_ba2", _stage("ba"), True)], _stage("ba_qa"))
    assert result.returncode == 0 and result.stderr == "", result.stderr


def test_R17_fanout_lanes_dispatched_together_never_warn(tmp_path):
    """Each lane's stage is dispatched while its sibling lane's runs: a lane
    names only its own task id's artifacts, so no lane waits for another."""
    home, project = _dirs(tmp_path)
    one, two = (f"{TASK_ID}-{lane}" for lane in LANES)
    done = []
    for kind in ("ba", "ba_qa", "dev", "qa"):
        sibling = (f"toolu_{kind}_l1", _stage(kind, one, "l1"), False)
        result = _order_run(home, project, done + [sibling], _stage(kind, two, "l2"))
        assert result.returncode == 0 and result.stderr == "", f"{kind}: {result.stderr}"
        done += [(f"toolu_{kind}_l1", _stage(kind, one, "l1"), True),
                 (f"toolu_{kind}_l2", _stage(kind, two, "l2"), True)]


@pytest.mark.parametrize("command,kind", [("do", "dev"), ("close", "dev"), ("commit", "qa")])
def test_R17_later_command_span_passes(tmp_path, command, kind):
    """A /do, /close or /commit dispatch is compared with its own span's
    dispatches only: the /dev span's re-dispatched BA without a newer
    verdict (control: the same dispatch inside that /dev span warns)."""
    home, project = _dirs(tmp_path)
    steps = BA_LOOP + [("toolu_ba2", _stage("ba"), True)]
    later = _typed_command(command) + [_assistant_text()]
    result = _order_run(home, project, steps, _stage(kind), tail=later)
    assert result.returncode == 0 and result.stderr == "", result.stderr
    control = _order_run(home, project, steps, _stage(kind))
    assert ORDER_BANNER in control.stderr


@pytest.mark.parametrize("switch", [None, "advisory", "off"])
def test_R17_unarmed_gate_stays_silent(tmp_path, switch):
    """The arming switch: R17 speaks only when G1 is armed (block); advisory
    and off pass the violating QA dispatch silently, as every G1 finding."""
    home, project = _dirs(tmp_path)
    steps = DEV_LOOP + [("toolu_dev2", _stage("dev", extra=QA_FIX), False)]
    result = _order_run(home, project, steps, _stage("qa"), switch=switch)
    assert result.returncode == 0 and result.stderr == "", result.stderr


def test_R17_order_is_record_order_not_dispatched_at(tmp_path):
    """No clock allowance: the dispatches' dispatched_at never decide. An
    in-flight dev stamped two hours before the QA still warns; a returned
    dev stamped after the QA's dispatched_at passes."""
    home, project = _dirs(tmp_path)
    later = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(timespec="seconds")
    old = _stage("dev", extra=QA_FIX, dispatched_at=_two_hours_ago())
    late = _stage("dev", extra=QA_FIX, dispatched_at=later.replace("+00:00", "Z"))
    warned = _order_run(home, project, DEV_LOOP + [("toolu_dev2", old, False)], _stage("qa"))
    assert "reason=producer_not_stopped" in warned.stderr and warned.returncode == ORDER_EXIT
    passed = _order_run(home, project, DEV_LOOP + [("toolu_dev2", late, True)], _stage("qa"))
    assert passed.returncode == 0 and passed.stderr == "", passed.stderr


def test_R17_a_refused_redispatch_has_not_returned(tmp_path):
    """A dev re-dispatch a hook refused (is_error result) ran nothing: a QA
    after it would re-judge the previous round's report, so it is a finding;
    so is a dev after a refused BA-QA re-dispatch."""
    home, project = _dirs(tmp_path)
    steps = DEV_LOOP + [("toolu_dev2", _stage("dev", extra=QA_FIX), "refused")]
    result = _order_run(home, project, steps, _stage("qa"))
    assert result.returncode == ORDER_EXIT
    assert ("reason=producer_not_stopped artifact=docs/dev/dev-report-" in result.stderr
            and "toolu_dev2 (dev), which has not returned a result" in result.stderr), result.stderr
    steps = BA_LOOP + [("toolu_ba2", _stage("ba"), True), ("toolu_baqa2", _stage("ba_qa"), "refused")]
    result = _order_run(home, project, steps, _stage("dev"))
    assert result.returncode == ORDER_EXIT
    assert "dispatch toolu_baqa2 (line" in result.stderr and "not returned" in result.stderr, result.stderr
