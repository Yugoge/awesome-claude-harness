"""The owner's ruling of 2026-11-20: no day window refuses or silently leaves something out; it warns.

One test group per window: /restart's cross-account sweep (subagent_restart.sibling_transcripts and
prepare_state), the restart grant's lifetime bounds (mint_grant), a cp-state slot's age
(agent_resolver, subagentstop-cp-enforce.py) and the refusal record's day files (command_span). Each
group also pins a refusal whose reason is not age and stays.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hooks"))

from lib import agent_resolver, command_span  # noqa: E402
from lib import subagent_restart as restart  # noqa: E402
from tests.test_restart_command import (  # noqa: E402
    AUTHORIZER, HELPER, _record, _run_hook, _tool_use, _write_jsonl, _write_meta,
)

DAY = 86400


def _aged(path: Path, seconds: float) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then))


@pytest.fixture()
def accounts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """An operator session in account b; another session of the project in account a, last written 3 days
    ago; a copy of the operator's own session in account a, also 3 days old."""
    monkeypatch.setenv("CLAUDE_RESTART_GRANT_DIR", str(tmp_path / "grants"))
    monkeypatch.setenv("CLAUDE_RESTART_STATE_DIR", str(tmp_path / "states"))
    monkeypatch.delenv("CLAUDE_RESTART_SIBLING_WINDOW_SECONDS", raising=False)
    monkeypatch.delenv("CLAUDE_RESTART_SIBLING_MAX_BYTES", raising=False)
    root = tmp_path / "accounts"
    monkeypatch.setattr(restart, "ACCOUNTS_ROOT", root)
    project = tmp_path / "project"
    project.mkdir()
    slug = restart.project_slug(project)
    sid, other = str(uuid.uuid4()), str(uuid.uuid4())
    paths = {
        "own": root / "acct-b" / "claude" / "projects" / slug / f"{sid}.jsonl",
        "copy": root / "acct-a" / "claude" / "projects" / slug / f"{sid}.jsonl",
        "older": root / "acct-a" / "claude" / "projects" / slug / f"{other}.jsonl",
    }
    for name, path in paths.items():
        tool = f"toolu_{name}"
        _write_jsonl(path, [_record("assistant", [_tool_use(tool, f"{name} interrupted")])])
        _write_meta(path, f"agent-{name}", tool, f"{name} interrupted")
    _aged(paths["copy"], 3 * DAY)
    _aged(paths["older"], 3 * DAY)
    restart.mint_grant(sid, str(paths["own"]), ttl_seconds=600)
    return {"sid": sid, "other": other, "project": project, **paths}


def _send(sid: str, item: dict) -> dict:
    return {"tool_name": "SendMessage", "session_id": sid,
            "tool_input": {"to": item["agent_id"], "message": item["resume_message"]}}


# 1. /restart --cross-account

def test_a_copy_of_this_session_is_read_whatever_its_age(accounts):
    view = restart.prepare_state(accounts["sid"], project_dir=accounts["project"], cross_account=True)
    assert {c["agent_id"] for c in view["candidates"]} == {"agent-own", "agent-copy"}
    assert "agent-copy" not in [c["agent_id"] for c in view.get("older_candidates", [])]


def test_an_older_session_is_listed_apart_with_its_age_and_a_warning(accounts):
    view = restart.prepare_state(accounts["sid"], project_dir=accounts["project"], cross_account=True)
    assert view["candidate_count"] == 2 and "agent-older" not in [c["agent_id"] for c in view["candidates"]]
    assert view["older_candidate_count"] == 1
    older = view["older_candidates"][0]
    assert older["agent_id"] == "agent-older" and older["parent_session_id"] == accounts["other"]
    assert older["session_last_written"].startswith("3 d ") and older["session_last_written"].endswith(" ago")
    assert 3 * DAY - 60 <= older["session_last_written_seconds_ago"] <= 3 * DAY + 60
    assert view["warnings"] == [restart.OLDER_WARNING.format(count=1, window="1 d 0 h")]
    assert "resume them only when the operator's guidance asks for them" in view["warnings"][0]
    # The window still separates the lists and stays configurable.
    os.environ["CLAUDE_RESTART_SIBLING_WINDOW_SECONDS"] = str(4 * DAY)
    try:
        wide = restart.prepare_state(accounts["sid"], project_dir=accounts["project"], cross_account=True)
    finally:
        del os.environ["CLAUDE_RESTART_SIBLING_WINDOW_SECONDS"]
    assert "agent-older" in [c["agent_id"] for c in wide["candidates"]] and "warnings" not in wide


def test_an_older_candidate_nobody_resumed_holds_back_no_finalize_and_one_resumed_does(accounts):
    sid = accounts["sid"]
    view = restart.prepare_state(sid, project_dir=accounts["project"], cross_account=True)
    for item in view["candidates"]:
        restart.mark_dispatched(sid, item["agent_id"])
        restart.observe_subagent_stop({"session_id": sid, "agent_id": item["agent_id"],
                                       "last_assistant_message": "done\nRECOVERY_STATUS: completed"})
    done = restart.get_status(sid)
    assert done["complete"] is True and done["incomplete_agent_ids"] == []
    assert set(restart.completed_resumes(sid)) == {"agent-own", "agent-copy"}
    older = done["older_candidates"][0]
    assert restart.authorize_send_message(_send(sid, older)) == (True, "validated /restart recovery")
    restart.mark_dispatched(sid, "agent-older")
    assert restart.get_status(sid)["incomplete_agent_ids"] == ["agent-older"]
    with pytest.raises(restart.RestartError):
        restart.finalize(sid)


def test_the_byte_bound_names_what_it_did_not_read(accounts, monkeypatch):
    monkeypatch.setenv("CLAUDE_RESTART_SIBLING_MAX_BYTES", "1")
    view = restart.prepare_state(accounts["sid"], project_dir=accounts["project"], cross_account=True)
    assert view["siblings_not_read"]["count"] == 1  # the older session; the copy of this one is read anyway
    assert view["siblings_not_read"]["newest"].startswith("3 d ")
    assert restart.NOT_READ_WARNING.format(count=1, limit=1) in view["warnings"]
    state = json.loads(Path(view["state_path"]).read_text(encoding="utf-8"))
    assert [e["transcript"] for e in state["siblings_not_read"]] == [str(accounts["older"].resolve())]
    assert [c["agent_id"] for c in view["candidates"]] == ["agent-own", "agent-copy"]
    assert view["older_candidate_count"] == 0


def test_without_the_opt_in_no_other_session_is_read_and_a_foreign_send_stays_refused(accounts):
    sid = accounts["sid"]
    cross = restart.prepare_state(sid, project_dir=accounts["project"], cross_account=True)
    older = cross["older_candidates"][0]
    plain = restart.prepare_state(sid, project_dir=accounts["project"])
    assert [c["agent_id"] for c in plain["candidates"]] == ["agent-own"] and "older_candidates" not in plain
    state_file = Path(cross["state_path"])
    state = json.loads(state_file.read_text(encoding="utf-8"))
    state["candidates"].append({**older, "older": True, "status": "pending"})
    state_file.write_text(json.dumps(state), encoding="utf-8")
    ok, reason = restart.authorize_send_message(_send(sid, older))
    assert ok is False and "another parent session" in reason


def test_the_cli_prints_the_warning_and_the_command_text_says_what_to_do(accounts):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_RESTART_SIBLING") and k != "CLAUDE_PROJECT_DIR"}
    env["CLAUDE_RESTART_ACCOUNTS_ROOT"] = str(restart.ACCOUNTS_ROOT)
    env["CLAUDE_CONFIG_DIR"] = str(accounts["project"] / "no-config")
    done = subprocess.run([sys.executable, str(HELPER), "prepare", "--session-id", accounts["sid"], "--cross-account"],
                          capture_output=True, text=True, env=env, cwd=str(accounts["project"]), check=False)
    assert done.returncode == 0, done.stderr
    assert restart.OLDER_WARNING.format(count=1, window="1 d 0 h") in done.stderr
    assert json.loads(done.stdout)["older_candidates"][0]["agent_id"] == "agent-older"
    text = (ROOT / "commands" / "restart.md").read_text(encoding="utf-8")
    for words in ("`older_candidates`", "only when the operator's guidance asks for", "report them in one line",
                  "`siblings_not_read`", "holds back no", "`older_candidates` follow step 2's rule"):
        assert words in " ".join(text.split()), words


# 2. The restart grant's lifetime bounds

@pytest.mark.parametrize(("asked", "used"), [(10, 60), (10 ** 6, 86400)])
def test_a_grant_lifetime_out_of_bounds_takes_the_nearest_bound_with_a_warning(tmp_path, monkeypatch, asked, used):
    monkeypatch.setenv("CLAUDE_RESTART_GRANT_DIR", str(tmp_path / "grants"))
    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    _write_jsonl(transcript, [])
    grant = restart.mint_grant(sid, str(transcript), ttl_seconds=asked)
    life = (datetime.fromisoformat(grant["expires_at"]) - datetime.fromisoformat(grant["issued_at"])).total_seconds()
    assert life == used
    assert grant["ttl_warning"] == f"warning: restart grant TTL {asked} s is outside 60-86400 s; {used} s is used"
    assert restart.load_valid_grant(sid)["expires_at"] == grant["expires_at"]
    assert "ttl_warning" not in restart.mint_grant(sid, str(transcript), ttl_seconds=600)


def test_the_issuer_prints_the_lifetime_warning_and_a_malformed_lifetime_is_still_refused(tmp_path):
    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    _write_jsonl(transcript, [])
    env = {**os.environ, "CLAUDE_RESTART_GRANT_DIR": str(tmp_path / "grants"),
           "CLAUDE_RESTART_STATE_DIR": str(tmp_path / "states"), "CLAUDE_RESTART_GRANT_TTL_SECONDS": "5"}
    payload = {"session_id": sid, "transcript_path": str(transcript), "cwd": str(tmp_path), "prompt": "/restart"}
    issued = _run_hook(AUTHORIZER, payload, env)
    assert issued.returncode == 0, issued.stderr
    assert "[/restart] warning: restart grant TTL 5 s is outside 60-86400 s; 60 s is used" in issued.stdout
    refused = _run_hook(AUTHORIZER, payload, {**env, "CLAUDE_RESTART_GRANT_TTL_SECONDS": "soon"})
    assert refused.returncode == 2 and "TTL is not an integer" in refused.stderr


# 3. A cp-state slot's age

def _iso_ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds").replace("+00:00", "Z")


def _slot(project: Path, spec: str, role: str, agent_id: str, hours: float | None, pending: bool = False) -> Path:
    path = project / ".claude" / "specs" / spec / f"cp-state-{role}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "spec_id": spec, "agent_type": role, "agent_id": agent_id, "is_running": True,
        "checked_in_at": None if hours is None else _iso_ago(hours), "checked_out_at": None,
        "checkpoints": [{"id": "cp-01", "state": "pending"}] if pending else [],
    }), encoding="utf-8")
    return path


def _role(project: Path, agent_id: str, monkeypatch) -> str | None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    return agent_resolver.resolve_agent_type({"tool_name": "Write", "agent_id": agent_id})


def test_a_day_old_slot_is_honoured_with_a_warning_naming_it_and_its_age(tmp_path, monkeypatch, capsys):
    path = _slot(tmp_path, "s1", "qa", "a1111111111111111", 50)
    assert _role(tmp_path, "a1111111111111111", monkeypatch) == "qa"
    err = capsys.readouterr().err
    assert f"cp-state slot {path} (agent_id a1111111111111111, role qa) was checked in 50.0 h ago" in err


def test_a_fresher_record_still_wins_and_stale_slots_of_two_roles_give_no_role(tmp_path, monkeypatch, capsys):
    _slot(tmp_path, "s1", "architect", "a2222222222222222", 60)
    _slot(tmp_path, "s2", "qa", "a2222222222222222", 1)
    assert _role(tmp_path, "a2222222222222222", monkeypatch) == "qa"
    idx = tmp_path / ".claude" / "dev-registry" / "agent-index.json"
    idx.parent.mkdir(parents=True)
    idx.write_text(json.dumps({"a3333333333333333": "ba"}), encoding="utf-8")
    _slot(tmp_path, "s3", "architect", "a3333333333333333", 60)
    assert _role(tmp_path, "a3333333333333333", monkeypatch) == "ba"
    _slot(tmp_path, "s4", "architect", "a4444444444444444", 60)
    _slot(tmp_path, "s5", "dev", "a4444444444444444", 70)
    assert _role(tmp_path, "a4444444444444444", monkeypatch) is None
    capsys.readouterr()


def test_a_slot_with_no_readable_check_in_time_is_still_not_trusted(tmp_path, monkeypatch):
    _slot(tmp_path, "s1", "dev", "a5555555555555555", None)
    _slot(tmp_path, "s2", "qa", "a6666666666666666", -24)
    assert _role(tmp_path, "a5555555555555555", monkeypatch) is None
    assert _role(tmp_path, "a6666666666666666", monkeypatch) is None


def test_a_stopping_agent_s_day_old_slot_with_pending_checkpoints_is_judged_with_the_warning(tmp_path):
    _slot(tmp_path, "s1", "dev", "a7777777777777777", 50, pending=True)
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path), "CP_ENFORCE_MODE": "block"}
    enforce = ROOT / "hooks" / "subagentstop-cp-enforce.py"
    stop = subprocess.run([sys.executable, str(enforce)], input=json.dumps({"agent_id": "a7777777777777777"}),
                          text=True, capture_output=True, env=env, timeout=15)
    assert stop.returncode == 2 and "was checked in 50.0 h ago" in stop.stderr
    other = subprocess.run([sys.executable, str(enforce)], input=json.dumps({"agent_id": "a8888888888888888"}),
                           text=True, capture_output=True, env=env, timeout=15)
    assert other.returncode == 0, other.stderr  # another agent's slot is not this agent's to mark


# 4. The refusal record's day files

def test_a_refusal_recorded_days_ago_is_found_and_only_this_session_s(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    sid = "99999999-2222-3333-4444-555555555555"
    folder = Path(command_span._refusal_record_files(time.time())[-1]).parent
    folder.mkdir(parents=True)
    old = folder / time.strftime("refusals-%Y-%m-%d.jsonl", time.gmtime(time.time() - 5 * DAY))
    lines = [{"kind": "refusal", "event": "PreToolUse", "session": sid, "tool_use_id": "toolu_old"},
             {"kind": "unproven", "event": "PreToolUse", "session": sid, "tool_use_id": "toolu_unproven"},
             {"kind": "refusal", "event": "PreToolUse", "session": "another", "tool_use_id": "toolu_theirs"}]
    old.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    assert command_span.refused_calls(str(tmp_path / f"{sid}.jsonl")) == {"toolu_old"}
    assert [Path(p).name for p in command_span._refusal_record_files(time.time())][0] == old.name
