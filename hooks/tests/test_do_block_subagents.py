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
so the flag fixtures can never collide with a real session, and every
fixture the tests create is removed in a finally block. Fixtures go where the
hook reads them: the hook state dir (CLAUDE_STATE_DIR, default /tmp;
hooks/lib/harness_state_dir.py).
"""

import importlib.util
import json
import os
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO_ROOT, "hooks", "pretool-do-block-subagents.py")
# The hook's own state-dir resolver, loaded under a private name (no sys.path change).
_spec = importlib.util.spec_from_file_location(
    "_do_block_test_harness_state_dir",
    os.path.join(REPO_ROOT, "hooks", "lib", "harness_state_dir.py"))
_state_dir_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_state_dir_module)
harness_state_dir = _state_dir_module.harness_state_dir

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
    path = Path(harness_state_dir()) / f"claude-orchestrator-consent-{sid}.flag"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


@contextmanager
def _allow_agent_grant(sid):
    """Create the grant `/allow Agent` writes, the one /allow grant file that
    match_sentinel_grant_for_tool reads (as pretool-subagent-enforce does)."""
    path = Path(harness_state_dir()) / "claude-grants" / f"{sid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    path.write_text(json.dumps({
        "task_id": sid, "session_id": sid, "allowed_operations": [{"op": "Agent"}],
        "created_at": now, "expires_at": now + 300,
    }))
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


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
    (lib.allowlist.has_do_consent, the content check every consent reader takes)."""
    sid = _unique_sid()
    with _consent_flag(sid, content="1"):
        result = _run_hook({"tool_name": "Agent", "session_id": sid,
                            "tool_input": {"prompt": "do work"}})
    assert result.returncode == 0
    assert BLOCK_BANNER not in result.stderr


def test_f_allow_agent_grant_overrides_block():
    """(f) /allow Agent grant present + consent present -> exit 0
    (human escape hatch, same match_sentinel_grant_for_tool lookup)."""
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
# P1 (A1.e): the repair-profile exception is retired. No template emits
# profile "repair" and G1 rejects it, so during an active /do a repair-profile
# dispatch is blocked like any other main-agent dispatch.
# ---------------------------------------------------------------------------

def _repair_obligation_prompt(profile: str = "repair") -> str:
    return (
        'dispatch a producer fix '
        f'<obligation v="1">{{"profile": "{profile}", "task_id": null}}</obligation> '
        'end of prompt'
    )


def test_i_repair_profile_dispatch_blocked_during_do():
    """(i) consent active + an obligation block with profile="repair" -> exit 2
    with the block message (before P1: exit 0 through the retired bypass)."""
    sid = _unique_sid()
    with _consent_flag(sid):
        result = _run_hook({
            "tool_name": "Agent", "session_id": sid,
            "tool_input": {"prompt": _repair_obligation_prompt()},
        })
    assert result.returncode == 2
    assert BLOCK_BANNER in result.stderr


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


# ---------------------------------------------------------------------------
# CRITIQUE A4: a role that cannot write cannot leave the colliding dev-report,
# so during an active /do the main agent may dispatch it. "Cannot write" is
# structural (a built-in read-only type, or a tool-policy row with only read
# tools), never the prompt's wording; everything else stays blocked.
# ---------------------------------------------------------------------------

import pytest  # noqa: E402


def _dispatch(sid, tool_input, tool_name="Agent", env_extra=None, cwd=None):
    payload = {"tool_name": tool_name, "session_id": sid, "tool_input": tool_input}
    if cwd is not None:
        payload["cwd"] = cwd
    env = _clean_env()
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, HOOK], input=json.dumps(payload), capture_output=True,
        text=True, cwd=REPO_ROOT, env=env,
    )


@pytest.mark.parametrize("tool_name", ["Agent", "Task"])
@pytest.mark.parametrize("role", ["Explore", "Plan", "claude-code-guide"])
def test_m_read_only_builtin_allowed_during_do(role, tool_name, tmp_path):
    """The A4 repro: a read-only built-in dispatch during /do -> exit 0."""
    sid = _unique_sid()
    with _consent_flag(sid):
        result = _dispatch(sid, {"subagent_type": role, "run_in_background": False,
                                 "prompt": "list files under docs/"},
                           tool_name=tool_name, env_extra={"HOME": str(tmp_path)})
    assert result.returncode == 0, result.stderr
    assert BLOCK_BANNER not in result.stderr


@pytest.mark.parametrize("tool_input", [
    {"prompt": "research only, list files under docs/"},                # omitted -> general-purpose
    {"subagent_type": "general-purpose", "prompt": "research only"},
    {"subagent_type": "dev", "prompt": "research only"},
    {"subagent_type": "qa", "prompt": "research only"},
    {"subagent_type": "ba", "prompt": "research only"},
    {"subagent_type": "pull-analyst", "prompt": "read only"},           # Bash: can write
    {"subagent_type": "graphify", "prompt": "read only"},
    {"subagent_type": "no-such-role", "prompt": "read only"},           # unknown
    {"subagent_type": "", "prompt": "x"},
    {"subagent_type": None, "prompt": "x"},
    {"subagent_type": ["Explore"], "prompt": "x"},
    {"subagent_type": "explore", "prompt": "x"},                        # case variants
    {"subagent_type": "EXPLORE", "prompt": "x"},
    {"subagent_type": " Explore", "prompt": "x"},                       # whitespace variants
    {"subagent_type": "Explore ", "prompt": "x"},
    {"subagent_type": "Explore\n", "prompt": "x"},
    {"subagent_type": "plan", "prompt": "x"},
    {"subagent_type": "Claude-Code-Guide", "prompt": "x"},
    {"subagent_type": "plugin:Explore", "prompt": "x"},
    {"subagent_type": " dev ", "prompt": "x"},
    {"subagent_type": "Dev", "prompt": "x"},
])
def test_n_writing_or_unknown_role_still_blocked_during_do(tool_input, tmp_path):
    sid = _unique_sid()
    with _consent_flag(sid):
        result = _dispatch(sid, tool_input, env_extra={"HOME": str(tmp_path)})
    assert result.returncode == 2, (tool_input, result.stderr)
    assert BLOCK_BANNER in result.stderr


def test_o_project_definition_shadowing_builtin_stays_blocked(tmp_path):
    """A project agent definition named like a built-in may carry write tools:
    the built-in allow no longer applies to that name."""
    project = tmp_path / "proj"
    agents = project / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "my-explorer.md").write_text(
        "---\nname: Explore\ndescription: x\ntools: Read, Write, Bash\n---\nbody\n")
    sid = _unique_sid()
    with _consent_flag(sid):
        result = _dispatch(sid, {"subagent_type": "Explore", "prompt": "x"},
                           env_extra={"HOME": str(tmp_path)}, cwd=str(project))
    assert result.returncode == 2, result.stderr
    assert BLOCK_BANNER in result.stderr


def test_p_user_definition_shadowing_builtin_stays_blocked(tmp_path):
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "plan.md").write_text("---\nname: planner\ntools: Write\n---\n")
    sid = _unique_sid()
    with _consent_flag(sid):
        result = _dispatch(sid, {"subagent_type": "Plan", "prompt": "x"},
                           env_extra={"HOME": str(tmp_path)})
    assert result.returncode == 2, result.stderr


def test_q_policy_role_with_only_read_tools_allowed(monkeypatch, tmp_path):
    """A tool-policy role whose allowed_tools are all read tools passes; one
    with Bash, a write tool, a wildcard or no tools does not (the structural source)."""
    spec = importlib.util.spec_from_file_location("_do_block_hook_under_test", HOOK)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    from lib import claude_home  # the module the hook resolves the policy through
    policy = tmp_path / "tool-policy.v1.json"
    policy.write_text(json.dumps({"roles": {
        "reader": {"allowed_tools": ["Read", "Glob", "Grep", "WebFetch"]},
        "basher": {"allowed_tools": ["Read", "Bash"]},
        "writer": {"allowed_tools": ["Read", "Write"]},
        "mcp": {"allowed_tools": ["Read", "mcp__playwright__*"]},
        "empty": {"allowed_tools": []},
    }}))
    monkeypatch.setattr(claude_home, "resolve_optional", lambda rel: policy)
    assert hook._read_only_role({"tool_input": {"subagent_type": "reader"}}) is True
    for name in ("basher", "writer", "mcp", "empty", "missing", "Reader", " reader"):
        assert hook._read_only_role({"tool_input": {"subagent_type": name}}) is False, name
    monkeypatch.setattr(claude_home, "resolve_optional", lambda rel: None)
    assert hook._read_only_role({"tool_input": {"subagent_type": "reader"}}) is False


def test_r_every_shipped_policy_role_stays_blocked(tmp_path):
    """Every role the shipped policy lists holds Bash or a write tool today, so
    each stays blocked during /do."""
    roles = json.loads((Path(REPO_ROOT) / "policies" / "tool-policy.v1.json").read_text())["roles"]
    for role in roles:
        sid = _unique_sid()
        with _consent_flag(sid):
            result = _dispatch(sid, {"subagent_type": role, "prompt": "x"},
                               env_extra={"HOME": str(tmp_path)})
        assert result.returncode == 2, role


# Shadow definitions the runtime may load, in every spelling a YAML
# frontmatter allows, keep the built-in name blocked (verifier follow-up).
_SHADOW_TEXTS = {
    "inline-comment": "---\nname: Explore # shadow\ntools: Write\n---\n",
    "folded-scalar": "---\nname: >-\n  Explore\ntools: Write\n---\n",
    "literal-scalar": "---\nname: |-\n  Explore\n---\n",
    "double-quoted": '---\nname: "Explore"\n---\n',
    "single-quoted": "---\nname: 'Explore'\n---\n",
    "quoted-padded": '---\nname: " explore "\n---\n',
    "bom": "﻿---\nname: Explore\ntools: Write\n---\n",
    "unparsable": "---\nname: [unclosed\n---\n",
    "unterminated": "---\nname: someone\n",
}


@pytest.mark.parametrize("label", sorted(_SHADOW_TEXTS))
def test_s_shadow_definition_spellings_stay_blocked(label, tmp_path):
    project = tmp_path / "proj"
    agents = project / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "custom-role.md").write_text(_SHADOW_TEXTS[label], encoding="utf-8")
    sid = _unique_sid()
    with _consent_flag(sid):
        result = _dispatch(sid, {"subagent_type": "Explore", "prompt": "x"},
                           env_extra={"HOME": str(tmp_path / "home")}, cwd=str(project))
    assert result.returncode == 2, (label, result.stderr)
    assert BLOCK_BANNER in result.stderr


@pytest.mark.parametrize("via", ["cwd", "CLAUDE_PROJECT_DIR"])
def test_t_shadow_definition_in_a_parent_directory_stays_blocked(via, tmp_path):
    top = tmp_path / "top"
    agents = top / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "x.md").write_text("---\nname: Plan\ntools: Write\n---\n")
    nested = top / "a" / "b"
    nested.mkdir(parents=True)
    env_extra = {"HOME": str(tmp_path / "home")}
    cwd = None
    if via == "cwd":
        cwd = str(nested)
    else:
        env_extra["CLAUDE_PROJECT_DIR"] = str(nested)
    sid = _unique_sid()
    with _consent_flag(sid):
        result = _dispatch(sid, {"subagent_type": "Plan", "prompt": "x"},
                           env_extra=env_extra, cwd=cwd)
    assert result.returncode == 2, result.stderr


def test_u_shadow_definition_behind_a_symlinked_subdirectory_stays_blocked(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "x.md").write_text("---\nname: claude-code-guide\ntools: Write\n---\n")
    project = tmp_path / "proj"
    agents = project / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "linked").symlink_to(elsewhere, target_is_directory=True)
    sid = _unique_sid()
    with _consent_flag(sid):
        result = _dispatch(sid, {"subagent_type": "claude-code-guide", "prompt": "x"},
                           env_extra={"HOME": str(tmp_path / "home")}, cwd=str(project))
    assert result.returncode == 2, result.stderr


def test_v_unrelated_definitions_and_a_symlink_cycle_still_allow(tmp_path):
    """Valid definitions of other names, a file without frontmatter and a
    symlink loop do not block the built-in (and the walk terminates)."""
    project = tmp_path / "proj"
    agents = project / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "helper.md").write_text("---\nname: helper # Explore-like\ntools: Read\n---\n")
    (agents / "notes.md").write_text("plain notes, no frontmatter\n")
    (agents / "loop").symlink_to(agents, target_is_directory=True)
    sid = _unique_sid()
    with _consent_flag(sid):
        result = _dispatch(sid, {"subagent_type": "Explore", "prompt": "x"},
                           env_extra={"HOME": str(tmp_path / "home")}, cwd=str(project))
    assert result.returncode == 0, result.stderr
