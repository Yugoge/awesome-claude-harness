"""hooks/subagentstop-codex-enforce.py: who must have called codex (P1b row 18).

The codex ledger's one deciding read blocks a stopping subagent whose session
armed the codex flag and whose ledger entry is absent. Which subagents are
bound is no role list: it is the stopping agent's own dispatch prompt, which
carries the line `codex_required: true` exactly where the command text asks
the agent to consult codex (every BA / QA / dev dispatch under --codex, and
any other dispatch whose template adds it, such as /dev-overnight's PM), or
the dispatch template it was made from (hooks/lib/dispatch_template.py), which
carries that line: in a --codex session a dispatch of that template without
the line is the orchestrator's omission (P1b acceptance 5).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
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
def test_a_dispatch_omitting_the_line_its_template_carries_is_bound(tmp_path, command, role, profile):
    project, agent_id, transcript = _setup(tmp_path, role, _template_prompt(command, role, profile, line=False))
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


def test_a_dispatch_carrying_no_block_is_read_in_its_command_span(tmp_path):
    """No obligation names the command: the typed command whose span holds the
    Agent call does (the agent meta names the call)."""
    prompt = _template_prompt("dev", "qa", "final_verification", line=False, block=False)
    project, agent_id, transcript = _setup(tmp_path, "qa", prompt)
    _with_parent(transcript, prompt, "qa", "/dev --codex harden add")
    proc = _stop(tmp_path, project, agent_id, transcript)
    assert proc.returncode == 2, proc.stderr
    _with_parent(transcript, prompt, "qa", "/do harden add")
    assert _stop(tmp_path, project, agent_id, transcript).returncode == 0
    graphify = "Use Agent tool with:\n- subagent_type: \"graphify\"\nGraphify enrichment: extract focused subgraph"
    project, agent_id, transcript = _setup(tmp_path / "graphify", "graphify", graphify)
    _with_parent(transcript, graphify, "graphify", "/dev --codex harden add")
    assert _stop(tmp_path / "graphify", project, agent_id, transcript).returncode == 0
