"""hooks/subagentstop-codex-enforce.py: who must have called codex (P1b row 18).

The codex ledger's one deciding read blocks a stopping subagent whose session
armed the codex flag and whose ledger entry is absent. Which subagents are
bound is no role list: it is the stopping agent's own dispatch prompt, which
carries the line `codex_required: true` exactly where the command text asks
the agent to consult codex (every BA / QA / dev dispatch under --codex, and
any other dispatch whose template adds it, such as /dev-overnight's PM). That
is the agents' own contract (agents/*.md "Codex:": without that line skip
codex), so a dispatch without the line is not bound, even when the template it
was made from shows the line (live 2026-11-21: 15 stops of 10 agents held so).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "subagentstop-codex-enforce.py"
sys.path.insert(0, str(REPO / "hooks" / "lib"))
import dispatch_template  # noqa: E402

SESSION = "dev-20261028-120000"
HARNESS_SESSION = "harness-codex"


def _setup(tmp_path: Path, agent_type: str, prompt: str, *, flag=True, ledger=False):
    project = tmp_path / "project"
    registry = project / ".claude" / "dev-registry"
    (registry / SESSION).mkdir(parents=True)
    agent_id = f"agent-{agent_type}-codex"
    (registry / "agent-index.json").write_text(json.dumps(
        {agent_id: {"agent_type": agent_type, "dev_session_id": SESSION}}), encoding="utf-8")
    if flag is not None:
        (registry / SESSION / "codex-enforce.json").write_text(json.dumps({"enabled": flag}), encoding="utf-8")
    if ledger:
        (registry / SESSION / "codex-ledger").mkdir()
        (registry / SESSION / "codex-ledger" / f"{agent_id}.json").write_text("{}", encoding="utf-8")
    transcript = tmp_path / "store" / HARNESS_SESSION / "subagents" / f"agent-{agent_id}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(json.dumps({"type": "user", "message": {"content": prompt}}) + "\n",
                          encoding="utf-8")
    return project, agent_id, transcript


def _stop(tmp_path: Path, project: Path, agent_id: str, transcript: Path | None):
    payload = {"agent_id": agent_id, "session_id": HARNESS_SESSION}
    if transcript is not None:
        payload["agent_transcript_path"] = str(transcript)
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), "HOME": str(tmp_path / "home"),
           "CLAUDE_CONFIG_DIR": str(tmp_path / "home" / ".claude"), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=60)


ASKED = "FIRST ACTION: Read the sentinel.\nRequirement: build it\ncodex_required: true\nGo."
NOT_ASKED = "FIRST ACTION: Read the sentinel.\nRequirement: build it\nGo."


@pytest.mark.parametrize("agent_type", ["ba", "dev", "qa", "pm", "architect"])
def test_a_dispatch_asked_to_consult_codex_blocks_without_its_ledger_entry(tmp_path, agent_type):
    project, agent_id, transcript = _setup(tmp_path, agent_type, ASKED)
    proc = _stop(tmp_path, project, agent_id, transcript)
    assert proc.returncode == 2, proc.stderr
    assert f"CODEX_ENFORCE_BLOCKED: agent {agent_id} (type={agent_type})" in proc.stderr
    assert f"codex-ledger/{agent_id}.json (failing check: absent" in proc.stderr


@pytest.mark.parametrize("agent_type", ["ba", "dev", "qa", "pm"])
def test_its_ledger_entry_lets_it_stop(tmp_path, agent_type):
    project, agent_id, transcript = _setup(tmp_path, agent_type, ASKED, ledger=True)
    assert _stop(tmp_path, project, agent_id, transcript).returncode == 0


@pytest.mark.parametrize("agent_type", ["graphify", "test-writer", "architect", "ba"])
def test_a_dispatch_not_asked_is_not_bound(tmp_path, agent_type):
    """A dispatch whose prompt omits the line and was made from no command
    template (none of these prompts is) was not asked."""
    project, agent_id, transcript = _setup(tmp_path, agent_type, NOT_ASKED)
    proc = _stop(tmp_path, project, agent_id, transcript)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""


@pytest.mark.parametrize("flag", [None, False])
def test_without_the_sessions_codex_flag_nothing_is_bound(tmp_path, flag):
    project, agent_id, transcript = _setup(tmp_path, "dev", ASKED, flag=flag)
    assert _stop(tmp_path, project, agent_id, transcript).returncode == 0


def test_an_unreadable_dispatch_prompt_fails_open(tmp_path):
    project, agent_id, transcript = _setup(tmp_path, "dev", ASKED)
    transcript.unlink()
    assert _stop(tmp_path, project, agent_id, transcript).returncode == 0
    assert _stop(tmp_path, project, agent_id, None).returncode == 0


TASK = "20261028-120000"
CONDITIONAL = re.compile(r"^\s*<If codex_required [^>]*>\s*$")


def _template_prompt(command: str, role: str, profile: str, *, line: bool, block: bool = True,
                     kind: str | None = None) -> str:
    """A prompt made from the current commands/<command>.md template that
    declares role and profile (or, given `kind`, is of that subagent_type):
    its lines with the orchestrator's conditional codex pair resolved (`line`
    keeps the codex line), and, with `block`, the obligation it declares for
    role instantiated."""
    text = (REPO / "commands" / f"{command}.md").read_text(encoding="utf-8")
    body = next(b for b, t, roles, profiles, _e in dispatch_template._fences(text)
                if (t == kind if kind else role in roles) and profile in profiles)
    # The orchestrator puts its own block where the template shows one.
    lines, out = re.sub(r'<obligation v="1">.*?</obligation>', "", body, flags=re.S).splitlines(), []
    for i, raw in enumerate(lines):
        if CONDITIONAL.match(raw) or (i and CONDITIONAL.match(lines[i - 1]) and not line):
            continue
        out.append(raw.replace("<timestamp>", TASK))
    if block:
        doc = {"task_id": TASK, "lane": None, "lane_set": None, "role": role, "pipeline": command,
               "profile": profile, "dispatched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "artifacts": [{"kind": "json", "path": f"docs/dev/{role}-out-{TASK}.json",
                              "schema": "qa-report.v2", "identity": {"task_id": TASK}}]}
        out.append(f'<obligation v="1">\n{json.dumps(doc)}\n</obligation>')
    return "\n".join(out)


def _with_parent(transcript: Path, prompt: str, subagent_type: str, typed: str) -> None:
    """The CLI's agent meta and the parent session transcript: the typed
    command opening the span and the Agent call that started the agent."""
    call = "toolu_codex_dispatch_1"
    transcript.with_name(transcript.stem + ".meta.json").write_text(json.dumps({"toolUseId": call}),
                                                                    encoding="utf-8")
    parent = transcript.parent.parent.parent / f"{HARNESS_SESSION}.jsonl"
    records = [{"type": "user", "message": {"role": "user", "content": typed}},
               {"type": "assistant", "message": {"role": "assistant", "content": [
                   {"type": "tool_use", "id": call, "name": "Agent",
                    "input": {"description": "d", "prompt": prompt, "subagent_type": subagent_type}}]}}]
    parent.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


TEMPLATES_WITH_THE_LINE = [
    ("dev", "ba", "singular"), ("dev", "qa", "ba_validation"), ("dev", "dev", "fanout-lane"),
    ("dev", "qa", "final_verification"), ("dev-command", "ba", "singular"),
    ("dev-command", "dev", "singular"), ("dev-command", "qa", "final_verification"),
    ("dev-overnight", "ba", "overnight"), ("dev-overnight", "dev", "overnight"),
    ("dev-overnight", "qa", "final_verification"), ("dev-overnight", "pm", "overnight"),
]


@pytest.mark.parametrize("command,role,profile", TEMPLATES_WITH_THE_LINE)
def test_a_dispatch_omitting_the_line_its_template_carries_is_not_bound(tmp_path, command, role, profile):
    """The agent was told to skip codex, so its stop is not held (before: exit 2, CODEX_ENFORCE_BLOCKED)."""
    project, agent_id, transcript = _setup(tmp_path, role, _template_prompt(command, role, profile, line=False))
    proc = _stop(tmp_path, project, agent_id, transcript)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""


@pytest.mark.parametrize("command,role,profile", TEMPLATES_WITH_THE_LINE)
def test_a_template_dispatch_carrying_the_line_is_held(tmp_path, command, role, profile):
    project, agent_id, transcript = _setup(tmp_path, role, _template_prompt(command, role, profile, line=True))
    proc = _stop(tmp_path, project, agent_id, transcript)
    assert proc.returncode == 2, proc.stderr
    assert f"CODEX_ENFORCE_BLOCKED: agent {agent_id} (type={role})" in proc.stderr


@pytest.mark.parametrize("command,role,profile", TEMPLATES_WITH_THE_LINE[:3])
def test_a_compliant_template_dispatch_stops(tmp_path, command, role, profile):
    project, agent_id, transcript = _setup(tmp_path, role, _template_prompt(command, role, profile, line=True),
                                           ledger=True)
    assert _stop(tmp_path, project, agent_id, transcript).returncode == 0
    project, agent_id, transcript = _setup(tmp_path / "noflag", role,
                                           _template_prompt(command, role, profile, line=False), flag=None)
    assert _stop(tmp_path / "noflag", project, agent_id, transcript).returncode == 0


@pytest.mark.parametrize("command,role,profile", [("dev", "test-writer", "singular"),
                                                  ("dev-overnight", "architect", "overnight")])
def test_a_template_without_the_line_binds_nothing(tmp_path, command, role, profile):
    """test-writer is never told to consult codex, nor are /dev-overnight's
    exploration specialists (their template names the role by placeholder)."""
    kind = "specialist" if role == "architect" else None
    prompt = _template_prompt(command, role, profile, line=False, kind=kind).replace("<specialist.type>", role)
    project, agent_id, transcript = _setup(tmp_path, role, prompt)
    proc = _stop(tmp_path, project, agent_id, transcript)
    assert proc.returncode == 0, proc.stderr


def test_a_dispatch_carrying_no_block_is_judged_by_its_own_line_in_any_command_span(tmp_path):
    """No obligation names the command and the typed command is /dev --codex:
    the dispatch's own line still decides (before: the span's template bound it)."""
    prompt = _template_prompt("dev", "qa", "final_verification", line=False, block=False)
    project, agent_id, transcript = _setup(tmp_path, "qa", prompt)
    _with_parent(transcript, prompt, "qa", "/dev --codex harden add")
    proc = _stop(tmp_path, project, agent_id, transcript)
    assert proc.returncode == 0, proc.stderr
    asked = _template_prompt("dev", "qa", "final_verification", line=True, block=False)
    project, agent_id, transcript = _setup(tmp_path / "asked", "qa", asked)
    _with_parent(transcript, asked, "qa", "/dev --codex harden add")
    assert _stop(tmp_path / "asked", project, agent_id, transcript).returncode == 2
    graphify = "Use Agent tool with:\n- subagent_type: \"graphify\"\nGraphify enrichment: extract focused subgraph"
    project, agent_id, transcript = _setup(tmp_path / "graphify", "graphify", graphify)
    _with_parent(transcript, graphify, "graphify", "/dev --codex harden add")
    assert _stop(tmp_path / "graphify", project, agent_id, transcript).returncode == 0


def _asked_by(command: str, profile: str, role: str = "qa") -> str:
    """A dispatch made from commands/<command>.md's QA template with its own
    `codex_required: true` line, as /close --codex and /commit --codex pass it."""
    return _template_prompt(command, "qa", profile, line=True).replace('"role": "qa"', f'"role": "{role}"') \
        + "\ncodex_required: true"


@pytest.mark.parametrize("command,profile", [("close", "final_verification"), ("commit", "commit-qa")])
def test_close_and_commit_dispatches_are_not_bound_by_the_dev_codex_flag(tmp_path, command, profile):
    """R11: the /dev --codex flag in the task's registry binds the /dev cycle's
    own dispatches; a close-QA or commit-QA stop whose own obligation names its
    pipeline is let through (before: exit 2, CODEX_ENFORCE_BLOCKED)."""
    project, agent_id, transcript = _setup(tmp_path, "qa", _asked_by(command, profile))
    proc = _stop(tmp_path, project, agent_id, transcript)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""


def test_a_dev_pipeline_qa_is_still_bound(tmp_path):
    project, agent_id, transcript = _setup(tmp_path, "qa", _asked_by("dev", "final_verification"))
    proc = _stop(tmp_path, project, agent_id, transcript)
    assert proc.returncode == 2, proc.stderr
    assert f"CODEX_ENFORCE_BLOCKED: agent {agent_id} (type=qa)" in proc.stderr


@pytest.mark.parametrize("unresolved", ["invalid_obligation", "role_mismatch"])
def test_an_unresolved_close_obligation_is_judged_as_before(tmp_path, unresolved):
    """An obligation G2 would not resolve as this agent's own (a block failing
    the grammar, or one naming another role than the agent registered as)
    exempts nothing: its `codex_required: true` line binds it as before R11."""
    prompt = _asked_by("close", "final_verification", role="dev" if unresolved == "role_mismatch" else "qa")
    if unresolved == "invalid_obligation":
        prompt = re.sub(r'"profile": "[^"]*", ', "", prompt)  # a required field (dispatched_at is not)
    project, agent_id, transcript = _setup(tmp_path, "qa", prompt)
    proc = _stop(tmp_path, project, agent_id, transcript)
    assert proc.returncode == 2, proc.stderr
    assert f"CODEX_ENFORCE_BLOCKED: agent {agent_id} (type=qa)" in proc.stderr


# --- codex out of quota (live 2026-11-20: 25 bound stops blocked while every codex call failed on the limit) ---
RUN = REPO / "scripts" / "steps" / "codex-run.py"
# codex-run.py's real output of such a call (neutral workdir, session id and prompt); RESET is the stated time
LIMIT_OUTPUT = """Reading additional input from stdin...
OpenAI Codex v0.167.0
--------
workdir: /work/project
model: gpt-5.6-sol
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
reasoning effort: xhigh
reasoning summaries: none
session id: 00000000-0000-4000-8000-000000000000
--------
user
Read-only review, do not modify any files. Answer accept or reject with reasons.
deprecated: `[features].codex_hooks` is deprecated. Use `[features].hooks` instead.
Enable it with `--enable hooks` or `[features].hooks` in config.toml. See https://developers.openai.com/codex/config-basic#feature-flags for details.
ERROR: You’ve hit your usage limit. Visit https://chatgpt.com/settings/usage to purchase more credits or try again at RESET.
ERROR: You’ve hit your usage limit. Visit https://chatgpt.com/settings/usage to purchase more credits or try again at RESET.
"""
# the older CLI wrapped the line once
WRAPPED = ("ERROR: You've hit your usage limit. Visit https://chatgpt.com/codex/settings/usage\n"
           "to purchase more credits or try again at RESET.\n")
# a real network failure, a crash of the call and the limit text only quoted in the prompt
NETWORK = LIMIT_OUTPUT.split("ERROR:")[0] + (
    "ERROR: Reconnecting... 2/2 (stream disconnected before completion: websocket closed by server before "
    "response.completed)\n")
QUOTED = LIMIT_OUTPUT.replace("Answer accept", LIMIT_OUTPUT.splitlines()[-1] + "\nAnswer accept").rsplit(
    "ERROR:", 2)[0] + "ERROR: stream disconnected before completion\n"


@pytest.fixture(autouse=True)
def _state_dir(tmp_path, monkeypatch):
    """Every stop here reads a throwaway state directory, never the machine's."""
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    return tmp_path / "state"


def _reset(at: float) -> str:  # the CLI's own wording of a reset time, e.g. "Nov 23rd, 2026 11:32 AM"
    t = datetime.fromtimestamp(at)
    suffix = "th" if 10 < t.day % 100 < 14 else {1: "st", 2: "nd", 3: "rd"}.get(t.day % 10, "th")
    return f"{t:%b} {t.day}{suffix}, {t.year} {t.hour % 12 or 12}:{t:%M %p}"


def _codex_call(tmp_path: Path, output: str, code: int, *, executable=True):
    """One foreground codex-run.py exec against a wrapper that prints `output` and exits `code`."""
    wrapper = tmp_path / f"wrapper-{len(list(tmp_path.glob('wrapper-*')))}"
    (tmp_path / "out.txt").write_text(output, encoding="utf-8")
    wrapper.write_text(f"#!/bin/sh\ncat '{tmp_path / 'out.txt'}'\nexit {code}\n", encoding="utf-8")
    wrapper.chmod(0o755 if executable else 0o644)
    env = {**os.environ, "CODEX_ISO_BIN": str(wrapper), "CLAUDE_PROJECT_DIR": str(tmp_path),
           "CODEX_OUT_TASK_ID": "T", "CODEX_OUT_ROLE": "dev", "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(RUN), "exec", "p"], capture_output=True, text=True, env=env,
                          cwd=tmp_path, timeout=60)


def _bound_stops(tmp_path: Path, *roles: str):
    """Each role's bound stop in its own cycle; (returncode, ledger entry or None) per stop."""
    out = []
    for role in roles:
        root = tmp_path / f"cycle-{role}"
        root.mkdir()
        project, agent_id, transcript = _setup(root, role, ASKED)
        proc = _stop(root, project, agent_id, transcript)
        entry = project / ".claude" / "dev-registry" / SESSION / "codex-ledger" / f"{agent_id}.json"
        out.append((proc.returncode, json.loads(entry.read_text()) if entry.exists() else None))
    return out


@pytest.mark.parametrize("text", [LIMIT_OUTPUT, WRAPPED], ids=["current-cli", "wrapped-line"])
def test_after_an_observed_usage_limit_failure_the_next_stops_pass(tmp_path, text):
    reset = time.time() + 3 * 86400
    assert _codex_call(tmp_path, text.replace("RESET", _reset(reset)), 1).returncode == 1
    assert _bound_stops(tmp_path, "dev", "qa", "ba") == [(0, None)] * 3
    assert abs(datetime.fromisoformat(_until(tmp_path)).timestamp() - reset) < 60


def _until(tmp_path: Path) -> str:  # the reset time the observed failure stored in the throwaway state directory
    return json.loads((tmp_path / "state" / "codex-unavailable.json").read_text(encoding="utf-8"))["until"]


def test_a_stop_let_through_while_codex_is_unavailable_writes_no_ledger_file(tmp_path):
    """The ledger has one writer, posttool-codex-skill-ledger.py; a repeated stop passes on the same knowledge."""
    assert _codex_call(tmp_path, LIMIT_OUTPUT.replace("RESET", _reset(time.time() + 86400)), 1).returncode == 1
    (tmp_path / "cycle").mkdir()
    project, agent_id, transcript = _setup(tmp_path / "cycle", "dev", ASKED)
    assert [_stop(tmp_path / "cycle", project, agent_id, transcript).returncode for _ in range(2)] == [0, 0]
    assert not (project / ".claude" / "dev-registry" / SESSION / "codex-ledger").exists()


def test_after_the_stated_reset_time_the_stop_is_blocked_again(tmp_path):
    sys.path.insert(0, str(REPO / "hooks"))
    from lib import codex_transcript  # noqa: PLC0415
    past = time.time() - 3600
    (tmp_path / "seen.txt").write_text(LIMIT_OUTPUT.replace("RESET", _reset(past + 120)), encoding="utf-8")
    codex_transcript.observe(1, tmp_path / "seen.txt", now=past)  # observed an hour ago, reset 58 minutes ago
    assert json.loads(Path(codex_transcript.unavailable_path()).read_text())["until"]
    assert _bound_stops(tmp_path, "dev") == [(2, None)]


def test_a_failure_without_a_readable_time_holds_for_the_default_span_only(tmp_path):
    assert _codex_call(tmp_path, "ERROR: You've hit your usage limit.\n", 1).returncode == 1
    assert _bound_stops(tmp_path, "dev") == [(0, None)]
    assert abs(datetime.fromisoformat(_until(tmp_path)).timestamp() - time.time() - 5 * 3600) < 60


@pytest.mark.parametrize("output,code,executable", [
    (NETWORK, 1, True), (QUOTED, 1, True), (LIMIT_OUTPUT, 1, False),  # network; quoted only; no usable wrapper
    ("error: unexpected argument '--bogus' found\n", 2, True),  # bad arguments
    ("thread 'main' panicked at src/main.rs:1:1\n", 101, True)],  # a crash
    ids=["network", "quoted-in-prompt", "no-wrapper", "bad-arguments", "crash"])
def test_any_other_failure_changes_nothing(tmp_path, output, code, executable):
    proc = _codex_call(tmp_path, output.replace("RESET", _reset(time.time() + 86400)), code, executable=executable)
    assert proc.returncode != 0
    assert not (tmp_path / "state" / "codex-unavailable.json").exists()
    assert _bound_stops(tmp_path, "dev") == [(2, None)]


def test_a_successful_consultation_restores_the_demand(tmp_path):
    _codex_call(tmp_path, LIMIT_OUTPUT.replace("RESET", _reset(time.time() + 86400)), 1)
    assert _bound_stops(tmp_path, "dev")[0][0] == 0
    assert _codex_call(tmp_path, "codex\nACCEPT\n", 0).returncode == 0
    assert _bound_stops(tmp_path, "qa") == [(2, None)]


def test_a_usage_limit_text_a_successful_call_prints_arms_nothing(tmp_path):
    _codex_call(tmp_path, LIMIT_OUTPUT.replace("RESET", _reset(time.time() + 86400)), 0)
    assert _bound_stops(tmp_path, "dev") == [(2, None)]
