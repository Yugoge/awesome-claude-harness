"""scripts/refusals: the refusal record's reader.

- For a period it gives the totals and the counts by event, rule, hook, role, project, day and
  provider, the loops (one actor, the identical refusal more than once), and counts a let-through
  (unproven) apart from the refusals; reports a writer could not merge count once. A let-through whose
  call another hook refused (same session, event and tool-call id) is counted apart again, not listed.
- reconcile pairs the record with the hook refusals of the session transcripts by tool-call id (a
  blocked stop by session, agent and time): no difference exits 0; a line taken out of the record,
  and a line no transcript holds, are each printed and exit 1. A refused prompt and a call rejected
  after it ran (no transcript line shows them), a Codex seat's record, a let-through and a denial
  by the CLI's own permission rules are counted, not compared.
- The transcript records are built from the recorded CLI fixture (tests/fixtures/cli), never by hand.
- It reads the directory the writer writes, with no argument naming it (the reader is the record's
  consumer: without it this file fails, and the record would be written and never read).

Run with: python3 -m pytest tests/test_refusals_reader.py -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
READER = REPO / "scripts" / "refusals"
sys.path.insert(0, str(REPO / "hooks"))

try:
    from lib import refusal_record as R  # noqa: E402
except ImportError:  # the writer is gone: each test below fails by name, instead of this file not loading
    R = None

SID = "7e1f0a2b-3c4d-4e5f-8a6b-7c8d9e0f1a2b"
POLICY = ("hooks/pretool-tool-policy.py", 'BLOCKED by tool-policy.v1: {"role":"ba","tool":"TodoWrite","target":null,'
          '"deny_reason":"tool TodoWrite not in allowed_tools"}')
REMOVAL = ("hooks/lib/bash_safety_rules.py", "BLOCKED: removal-policy — UNRESOLVED dynamic_command_head:x=$(date)")
STOPGATE = ("hooks/subagentstop-artifact-contract-enforce.py", "OBLIGATION_STOPGATE_BLOCKED: agent a1 (role=ba) declared:\n"
            "  - docs/dev/ba-panel-1.md: artifact_missing")
GATE = ("hooks/stop-workflow-coordinator.py", "COMMAND_GATE /dev: not complete\n- todo: not completed: Step 10")


def call(tool, tool_input, tool_id, event="PreToolUse", **more) -> dict:
    p = {"hook_event_name": event, "session_id": SID, "cwd": "/work/app", "tool_name": tool, "tool_input": tool_input,
         "tool_use_id": tool_id}
    p.update(more)
    return {k: v for k, v in p.items() if v is not None}


def reader(*args) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(READER), *args], capture_output=True, text=True, env=env, timeout=300)


def a_week(monkeypatch) -> None:
    """Refusals of two actors in two projects, a loop of three, a let-through, a Codex seat's refusal, a prompt."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/app")
    R.write(call("TodoWrite", {"todos": []}, "toolu_1", agent_id="a1", agent_type="ba"), [POLICY], "hooks/pretool-write-gate.py")
    for i in (2, 3, 4):       # the same actor, the identical command, refused again and again
        R.write(call("Bash", {"command": "x=$(date); echo $x"}, f"toolu_{i}", agent_id="a1", agent_type="ba"),
                [REMOVAL], REMOVAL[0])
    R.write(call(None, None, None, "SubagentStop", agent_id="a1", agent_type="ba"), [STOPGATE], "hooks/subagentstop-producer-gate.py")
    R.write(call("Bash", {"command": "y=$(date)"}, "toolu_5"), [REMOVAL], REMOVAL[0], R.UNPROVEN)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/other")
    R.write(call("Bash", {"command": "git push --force"}, "toolu_6"), [("hooks/pretool-git-privilege-guard.py", "BLOCKED: agent git push")],
            "hooks/pretool-launch.py")
    R.write(call(None, None, None, "UserPromptSubmit", prompt="/dev --spec nowhere"), [("hooks/prompt-workflow.py", "Spec: /nowhere/spec.md (unresolved)")],
            "hooks/userprompt-launch.py")
    monkeypatch.setenv("CLAUDE_COMPAT_RUNTIME", "codex")
    R.write(call("Bash", {"command": "kill -9 1"}, "toolu_7"), [("hooks/lib/bash_safety_rules.py", "BLOCKED: kill with signals is refused")],
            "hooks/lib/bash_safety_rules.py")
    monkeypatch.delenv("CLAUDE_COMPAT_RUNTIME")


def test_one_command_answers_what_was_refused(monkeypatch):
    a_week(monkeypatch)
    out = reader("--json")
    assert out.returncode == 0, out.stderr
    s = json.loads(out.stdout)
    assert s["record"] == R.directory() and s["unreadable_lines"] == 0
    assert (s["refusals"], s["unproven"]) == (8, 1)
    assert dict(map(tuple, s["by_event"])) == {"PreToolUse": 6, "SubagentStop": 1, "UserPromptSubmit": 1}
    removal = "hooks/lib/bash_safety_rules.py blocked-removal-policy-unresolved-dynamic_command_head"
    assert dict(map(tuple, s["by_rule"])) == {
        removal: 3, "hooks/pretool-tool-policy.py blocked-by-tool-policy.v1-tool-not-in-allowed_tools": 1,
        "hooks/subagentstop-artifact-contract-enforce.py obligation_stopgate_blocked-agent-declared-artifact_missing": 1,
        "hooks/pretool-git-privilege-guard.py blocked-agent-git-push": 1, "hooks/prompt-workflow.py spec-unresolved": 1,
        "hooks/lib/bash_safety_rules.py blocked-kill-with-signals-is-refused": 1}
    assert dict(map(tuple, s["by_hook"]))["hooks/lib/bash_safety_rules.py"] == 4
    assert dict(map(tuple, s["by_role"])) == {"ba": 5, "main": 3}
    assert dict(map(tuple, s["by_project"])) == {"/work/app": 5, "/work/other": 3}
    assert s["by_day"] == [[time.strftime("%Y-%m-%d", time.gmtime()), 8]] or len(s["by_day"]) == 2   # a run across midnight
    assert dict(map(tuple, s["by_provider"])) == {"claude": 7, "codex": 1}
    assert s["unproven_by_rule"] == [[removal, 1]]
    (loop,) = s["loops"]
    assert (loop["times"], loop["role"], loop["agent_id"], loop["tool"], loop["rules"]) == (3, "ba", "a1", "Bash", [removal])
    text = reader().stdout
    assert "refusals: 8    let through unproven (not refusals): 1" in text and "     3x  " in text


def test_a_let_through_is_listed_with_the_snapshot_taken_before_it_ran(monkeypatch):
    """The pre-command snapshot (hooks/lib/bash_safety_rules.py::let_through_unproven) is read back with its call."""
    text = ("removal-policy let through unproven: UNRESOLVED dynamic_command_head:$PY\n"
            "snapshot: refs/checkpoints/main 5aab; bring a file back: git -C /work/app restore --source=5aab -- <path>")
    R.write(call("Bash", {"command": "PY=x; $PY --version"}, "toolu_8"), [("hooks/lib/bash_safety_rules.py", text)],
            "hooks/lib/bash_safety_rules.py", R.UNPROVEN)
    R.write(call("Bash", {"command": "z=$(date)"}, "toolu_9"), [REMOVAL], REMOVAL[0], R.UNPROVEN)  # an older line
    s = json.loads(reader("--json").stdout)
    assert (s["refusals"], s["unproven"]) == (0, 2)
    assert [x["snapshot"] for x in s["unproven_calls"]] == [text.splitlines()[1], "snapshot: not recorded"]
    out = reader().stdout
    assert "let through unproven (not refusals): 2" in out and "      " + text.splitlines()[1] in out


UNPROVEN_TEXT = ("hooks/lib/bash_safety_rules.py", "removal-policy let through unproven: UNRESOLVED dynamic_command_head:$X\n"
                 "snapshot: refs/checkpoints/main 5aab; bring a file back: git -C /work/app restore --source=5aab -- <path>")
PRIVILEGE = ("hooks/pretool-git-privilege-guard.py", "BLOCKED: agent git push")
HEADING = "let through by the removal policy, refused by another hook"


def extracted_rows(tmp_path, *ids) -> str:
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    path = tmp_path / "refusals.jsonl"
    path.write_text("".join(json.dumps({"tool_use_id": i, "record_uuid": None, "ts": now, "session_id": SID, "agent_id": None,
                                        "hook_event": "PreToolUse:Bash"}) + "\n" for i in ids))
    return str(path)


def test_a_let_through_another_hook_refused_is_counted_apart_and_not_listed(monkeypatch, tmp_path):
    """Live wall 3, B: one call, a refusal by one hook and the removal policy's unproven line from its own process."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/app")
    R.write(call("Bash", {"command": "X=git; $X push"}, "toolu_p"), [PRIVILEGE], "hooks/pretool-launch.py")
    R.write(call("Bash", {"command": "X=git; $X push"}, "toolu_p"), [UNPROVEN_TEXT], UNPROVEN_TEXT[0], R.UNPROVEN)
    s = json.loads(reader("--json").stdout)
    assert (s["refusals"], s["unproven"], s["unproven_refused_elsewhere"]) == (1, 0, 1)
    assert s["unproven_calls"] == [] and s["unproven_by_rule"] == []
    text = reader().stdout
    assert f"let through unproven (not refusals): 0    {HEADING}: 1" in text and "each with its snapshot" not in text
    out = reader("reconcile", "--refusals", extracted_rows(tmp_path, "toolu_p"))
    assert out.returncode == 0 and "in the record: 1    differences: 0" in out.stdout, out.stdout + out.stderr
    assert "'unproven': 0, 'unproven, refused by another hook': 1}" in out.stdout


def test_a_lone_let_through_is_listed_as_let_through(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/app")
    R.write(call("Bash", {"command": "X=ls; $X ."}, "toolu_u"), [UNPROVEN_TEXT], UNPROVEN_TEXT[0], R.UNPROVEN)
    R.write(call("Bash", {"command": "git push"}, "toolu_r"), [PRIVILEGE], "hooks/pretool-launch.py")  # another call
    s = json.loads(reader("--json").stdout)
    assert (s["refusals"], s["unproven"], s["unproven_refused_elsewhere"]) == (1, 1, 0)
    assert [x["snapshot"] for x in s["unproven_calls"]] == [UNPROVEN_TEXT[1].splitlines()[1]]
    assert f"let through unproven (not refusals): 1    {HEADING}: 0" in reader().stdout
    out = reader("reconcile", "--refusals", extracted_rows(tmp_path, "toolu_r"))
    assert out.returncode == 0 and "'unproven': 1, 'unproven, refused by another hook': 0}" in out.stdout, out.stdout


def test_a_lone_refusal_has_no_let_through(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/app")
    R.write(call("Bash", {"command": "git push"}, "toolu_r"), [PRIVILEGE], "hooks/pretool-launch.py")
    s = json.loads(reader("--json").stdout)
    assert (s["refusals"], s["unproven"], s["unproven_refused_elsewhere"], s["unproven_calls"]) == (1, 0, 0, [])
    out = reader("reconcile", "--refusals", extracted_rows(tmp_path, "toolu_r"))
    assert out.returncode == 0 and "'unproven': 0, 'unproven, refused by another hook': 0}" in out.stdout, out.stdout


def test_the_period_bounds_what_is_counted_and_split_reports_count_once():
    folder = Path(R.directory())
    folder.mkdir(parents=True)
    row = {"v": 1, "kind": "refusal", "event": "PreToolUse", "session": SID, "tool": "Bash", "tool_use_id": "toolu_1",
           "refused": "c", "message": "m", "project": "/p", "rules": [{"hook": "hooks/a.py", "id": "a", "by": "hooks/gate.py"}]}
    other = dict(row, rules=[{"hook": "hooks/gate.py", "id": "a", "by": "hooks/launch.py"}, {"hook": "hooks/b.py", "id": "b", "by": "hooks/launch.py"}])
    (folder / "refusals-2026-11-16.jsonl").write_text(
        json.dumps(dict(row, ts="2026-11-16T08:00:00.000Z")) + "\n" + json.dumps(dict(other, ts="2026-11-16T08:00:00.100Z")) + "\n"
        + "half a li")
    (folder / "refusals-2026-11-18.jsonl").write_text(json.dumps(dict(row, ts="2026-11-18T23:59:59.000Z", tool_use_id="toolu_2")) + "\n")
    week = json.loads(reader("--json", "--since", "2026-11-12", "--until", "2026-11-19").stdout)
    assert (week["refusals"], week["unreadable_lines"]) == (2, 1)
    assert dict(map(tuple, week["by_rule"])) == {"hooks/a.py a": 2, "hooks/b.py b": 1}      # the gate's own report stands for it
    assert week["by_day"] == [["2026-11-16", 1], ["2026-11-18", 1]]
    assert json.loads(reader("--json", "--since", "2026-11-16T09:00", "--until", "2026-11-18").stdout)["refusals"] == 0
    assert reader("--since", "last week").returncode == 2


def transcripts(cli_record, root: Path, refused: dict, stops: list, denied: str) -> Path:
    """A session's transcript and one subagent's, built from the recorded CLI fixture: a refused call per
    (tool-call id, text) of `refused`, a blocked stop per (uuid, time, the agent's or the session's) of
    `stops`, and one call the CLI's own permission rules denied. A blocked stop reads "Stop hook feedback:"
    in either transcript: the CLI writes an agent's blocked stop into that agent's transcript under the same words."""
    results = [r for r in cli_record("user") if isinstance(r["message"]["content"], list)
               and r["message"]["content"][0].get("type") == "tool_result"]
    typed = next(r for r in cli_record("user") if isinstance(r["message"]["content"], str))
    main, sub, now = [], [], time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    for n, (tool_id, text) in enumerate([*refused.items(), (denied, "Permission to use Bash with command x has been denied.")]):
        record = json.loads(json.dumps(results[n % len(results)]))
        record.update(sessionId=SID, timestamp=now, uuid=f"00000000-0000-4000-8000-{n:012d}")
        record["message"]["content"][0].update(tool_use_id=tool_id, content=text, is_error=True)
        (sub if n % 2 else main).append(record)
    for uuid, stamp, of_agent in stops:
        record = dict(json.loads(json.dumps(typed)), sessionId=SID, timestamp=stamp, uuid=uuid, isMeta=True)
        hook = "subagentstop-producer-gate.py" if of_agent else "stop-launch.py"
        record["message"]["content"] = f"Stop hook feedback:\n[python3 \"x/hooks/{hook}\"]: " + (STOPGATE[1] if of_agent else GATE[1])
        (sub if of_agent else main).append(record)
    project = root / "projects" / "-work-app"
    (project / SID / "subagents").mkdir(parents=True)
    (project / f"{SID}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in main))
    (project / SID / "subagents" / "agent-a1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in sub))
    return root / "projects"


def test_reconcile_is_zero_and_every_removed_or_added_line_is_a_difference(monkeypatch, cli_record, tmp_path):
    a_week(monkeypatch)
    R.write(call("Agent", {"prompt": "p"}, "toolu_8", "PostToolUse"), [("hooks/posttool-overnight-file-check.py", "FILE CHECK BLOCK")],
            "hooks/posttool-dispatch-record.py")
    hook = 'PreToolUse:{} hook error: [python3 "/h/hooks/pretool-launch.py"]: {}'
    refused = {"toolu_1": hook.format("TodoWrite", POLICY[1]), "toolu_6": hook.format("Bash", "BLOCKED: agent git push"),
               **{f"toolu_{i}": hook.format("Bash", REMOVAL[1]) for i in (2, 3, 4)}}
    R.write(call(None, None, None, "Stop"), [GATE], "hooks/stop-launch.py")
    now = time.time()
    stops = [("5a5a5a5a-0000-4000-8000-000000000001", time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now + 2)), True),
             ("5a5a5a5a-0000-4000-8000-000000000002", time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now + 3)), False)]
    projects = transcripts(cli_record, tmp_path, refused, stops, "toolu_denied")
    # an account's copy of the same session counts once
    out = reader("reconcile", "--transcripts", str(projects), str(projects))
    assert out.returncode == 0, out.stdout + out.stderr
    assert "hook refusals in the transcripts: 7    in the record: 7    differences: 0" in out.stdout
    assert ("{'no transcript line': 2, 'codex': 1, 'unproven': 1, 'unproven, refused by another hook': 0}, "
            "CLI permission-rule denials 1") in out.stdout

    day = next(Path(R.directory()).glob("*.jsonl"))
    kept = day.read_text().splitlines()
    day.write_text("".join(x + "\n" for x in kept if '"toolu_3"' not in x and '"SubagentStop"' not in x))
    R.write(call("Bash", {"command": "rm x"}, "toolu_9"), [REMOVAL], REMOVAL[0])
    out = reader("reconcile", "--transcripts", str(projects))
    assert out.returncode == 1
    found = [x for x in out.stdout.splitlines() if x.startswith("DIFFERENCE")]
    assert len(found) == 3 and "differences: 3" in out.stdout
    assert any("in the transcripts, not in the record" in x and "id=toolu_3" in x for x in found)
    assert any("in the transcripts, not in the record" in x and "SubagentStop" in x and stops[0][0] in x for x in found)
    assert any("in the record, not in the transcripts" in x and "id=toolu_9" in x for x in found)


def test_reconcile_reads_extracted_rows_too(monkeypatch, tmp_path):
    a_week(monkeypatch)
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    rows = [{"tool_use_id": f"toolu_{i}", "record_uuid": None, "ts": now, "session_id": SID, "agent_id": "a1",
             "hook_event": "PreToolUse:Bash"} for i in (1, 2, 3, 4, 6)]
    rows += [{"tool_use_id": None, "record_uuid": "u-1", "ts": now, "session_id": SID, "agent_id": "a1", "hook_event": "SubagentStop"},
             {"tool_use_id": "toolu_denied", "record_uuid": None, "ts": now, "session_id": SID, "agent_id": None, "hook_event": None}]
    extracted = tmp_path / "refusals.jsonl"
    extracted.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = reader("reconcile", "--refusals", str(extracted))
    assert out.returncode == 0 and "differences: 0" in out.stdout and "denials 1" in out.stdout, out.stdout + out.stderr
    extracted.write_text("".join(json.dumps(r) + "\n" for r in rows[1:]))
    out = reader("reconcile", "--refusals", str(extracted))
    assert out.returncode == 1 and "in the record, not in the transcripts" in out.stdout and "id=toolu_1 " in out.stdout
