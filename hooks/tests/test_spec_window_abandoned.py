"""The /spec window ends when its span is abandoned (CRITIQUE A3).

pretool-spec-block-foreground-agent.py refuses a foreground dispatch while a
/spec interview runs, and pretool-block-background-tasks.py lets only a
background Explore agent through in that window. Both read the window from
lib.todo_canonical.live_spec_checklist: the active span is /spec, its
checklist has an open step, and the span was not abandoned. It is abandoned
when a human-typed prompt followed the opener while the checklist, as the last
ok TodoWrite before that prompt left it, still had an open step among Steps
1-3a, the steps /spec runs inside the turn that opened it (its questions are
AskUserQuestion results, not prompts). The Step 4 loop that later prompts
continue stays live.

Each case runs the hooks alone and through the registered launcher
(pretool-launch.py, which runs the background rule and the dispatch gate).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
REPO = HOOKS.parent
sys.path.insert(0, str(REPO))
from hooks.lib import todo_canonical  # noqa: E402

SESSION_ID = "5be0a6f1-7c42-4d1e-9a3b-0c2d8e4f6a17"
SPEC_FG = HOOKS / "pretool-spec-block-foreground-agent.py"
BACKGROUND = HOOKS / "pretool-block-background-tasks.py"
LAUNCH = HOOKS / "pretool-launch.py"


class _Transcript:
    """A main-session transcript in the CLI's record shapes."""

    def __init__(self):
        self.records = []
        self._ids = 0

    def _envelope(self, kind, **fields):
        index = len(self.records) + 1
        record = {"parentUuid": None, "isSidechain": False, "type": kind, "uuid": f"uuid-{index:04d}",
                  "timestamp": f"2026-11-17T10:{index // 60 % 60:02d}:{index % 60:02d}.000Z",
                  "userType": "external", "entrypoint": "cli", "cwd": "/opt/demo/toyproj",
                  "sessionId": SESSION_ID, "version": "2.1.303"}
        record.update(fields)
        self.records.append(record)
        return len(self.records)

    def typed(self, content):
        return self._envelope("user", message={"role": "user", "content": content},
                              origin={"kind": "human"}, promptSource="sdk", turnOrigin="human")

    def command(self, name, args=""):
        line = self.typed(f"<command-message>{name}</command-message>\n<command-name>/{name}</command-name>\n"
                          f"<command-args>{args}</command-args>")
        self._envelope("user", isMeta=True, message={"role": "user", "content": [{"type": "text", "text": f"# /{name}"}]})
        return line

    def scheduled(self, content):
        return self._envelope("user", isMeta=True, message={"role": "user", "content": content},
                              promptSource="system", turnOrigin="scheduled")

    def notification(self, content):
        return self._envelope("user", message={"role": "user", "content": content},
                              origin={"kind": "task-notification"})

    def tool(self, name, tool_input, ok=True):
        self._ids += 1
        ident = f"toolu_{self._ids:04d}"
        self._envelope("assistant", message={"role": "assistant", "type": "message", "content": [
            {"type": "tool_use", "id": ident, "name": name, "input": tool_input}]})
        block = {"type": "tool_result", "tool_use_id": ident, "content": "ok"}
        if not ok:
            block["is_error"] = True
        self._envelope("user", message={"role": "user", "content": [block]}, toolUseResult={"stdout": "ok"})
        return ident

    def todos(self, done, active=True):
        """An ok TodoWrite of /spec's canonical list with ``done`` steps completed
        and the next in_progress (pending when ``active`` is False)."""
        steps = todo_canonical.run_todo_script("spec")
        for index, step in enumerate(steps):
            step["status"] = ("completed" if index < done
                              else "in_progress" if index == done and active else "pending")
        return self.tool("TodoWrite", {"todos": steps})

    def write(self, path):
        path.write_text("".join(json.dumps(r) + "\n" for r in self.records), encoding="utf-8")
        return str(path)


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    environ = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    environ.update(HOME=str(home), CLAUDE_PROJECT_DIR=str(project), CLAUDE_HOME=str(REPO),
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return environ


def _payload(transcript, tool_input):
    return {"session_id": SESSION_ID, "transcript_path": transcript, "cwd": "/opt/demo/toyproj",
            "hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": tool_input}


def _run(hook, payload, env):
    result = subprocess.run([sys.executable, str(hook)], input=json.dumps(payload), capture_output=True,
                            text=True, env=env, cwd=env["CLAUDE_PROJECT_DIR"], timeout=120)
    return result.returncode, result.stderr


FOREGROUND = {"subagent_type": "general-purpose", "run_in_background": False, "prompt": "summarize README.md",
              "description": "Summarize the readme"}
BACKGROUND_EXPLORE = {"subagent_type": "Explore", "run_in_background": True, "prompt": "list files under docs/",
                      "description": "List docs"}
BACKGROUND_GENERAL = dict(FOREGROUND, run_in_background=True)


def _abandoned(tmp_path):
    """CRITIQUE A3's repro: /spec, Step 1 left in_progress, then a plain prompt."""
    tx = _Transcript()
    tx.command("spec")
    tx.todos(0)
    tx.typed("never mind, something else")
    return tx.write(tmp_path / "abandoned.jsonl")


def _opening_turn(tmp_path):
    """/spec's opening turn, still running: Step 1 in_progress, no later prompt."""
    tx = _Transcript()
    tx.command("spec", "add a retry cap")
    tx.todos(0)
    return tx.write(tmp_path / "opening.jsonl")


def _loop(tmp_path, done=4):
    """/spec past Steps 1-3a in its opening turn, then a follow-up requirement (Step 4's loop)."""
    tx = _Transcript()
    tx.command("spec", "add a retry cap")
    tx.todos(0)
    for step in range(1, done + 1):
        tx.todos(step)
    tx.typed("also cap the backoff at 30s")
    return tx.write(tmp_path / "loop.jsonl")


# ---------------------------------------------------------------- new allows (CRITIQUE A3)

def test_abandoned_spec_lets_a_foreground_dispatch_through(tmp_path, env):
    payload = _payload(_abandoned(tmp_path), FOREGROUND)
    assert _run(SPEC_FG, payload, env) == (0, "")
    assert _run(BACKGROUND, payload, env)[0] == 0


def test_abandoned_spec_foreground_dispatch_passes_the_registered_launcher(tmp_path, env):
    code, err = _run(LAUNCH, _payload(_abandoned(tmp_path), FOREGROUND), env)
    assert code == 0, err
    assert "SPEC INTERVIEW IN PROGRESS" not in err


def test_abandoned_spec_background_form_is_judged_as_outside_spec(tmp_path, env):
    """The background form: no /spec hold is left. A background general-purpose agent is refused by the
    ordinary background rule exactly as with no /spec span at all (never by the /spec window), and the
    Explore-only exception, which belongs to a live interview, no longer applies."""
    abandoned = _abandoned(tmp_path)
    plain = _Transcript()
    plain.typed("hello")
    outside = plain.write(tmp_path / "outside.jsonl")
    for tool_input in (BACKGROUND_GENERAL, BACKGROUND_EXPLORE):
        assert _run(SPEC_FG, _payload(abandoned, tool_input), env) == (0, "")
        assert _run(BACKGROUND, _payload(abandoned, tool_input), env) == _run(BACKGROUND, _payload(outside, tool_input), env)
        code, err = _run(LAUNCH, _payload(abandoned, tool_input), env)
        assert code == 2 and "SPEC INTERVIEW IN PROGRESS" not in err and "runs in the background by default" in err


def test_abandoned_spec_without_any_todowrite(tmp_path, env):
    """The opening turn ended before the first TodoWrite: the canonical list (all pending) is the state."""
    tx = _Transcript()
    tx.command("spec")
    tx.typed("summarize README.md instead")
    payload = _payload(tx.write(tmp_path / "t.jsonl"), FOREGROUND)
    assert _run(SPEC_FG, payload, env) == (0, "")


def test_abandoned_spec_mid_requirement_round(tmp_path, env):
    """Steps 1-3 done, Step 3a still open when the human typed the next prompt."""
    payload = _payload(_loop(tmp_path, done=3), FOREGROUND)
    assert _run(SPEC_FG, payload, env) == (0, "")


# ---------------------------------------------------------------- must still refuse

def test_opening_turn_still_refuses_a_foreground_dispatch(tmp_path, env):
    payload = _payload(_opening_turn(tmp_path), FOREGROUND)
    code, err = _run(SPEC_FG, payload, env)
    assert code == 2 and "SPEC INTERVIEW IN PROGRESS" in err and "(0/8 steps complete)" in err
    code, err = _run(LAUNCH, payload, env)
    assert code == 2 and "SPEC INTERVIEW IN PROGRESS" in err


def test_opening_turn_keeps_the_explore_only_background_exception(tmp_path, env):
    transcript = _opening_turn(tmp_path)
    assert _run(BACKGROUND, _payload(transcript, BACKGROUND_EXPLORE), env)[0] == 0
    assert _run(SPEC_FG, _payload(transcript, BACKGROUND_EXPLORE), env)[0] == 0
    assert _run(BACKGROUND, _payload(transcript, BACKGROUND_GENERAL), env)[0] == 2


def test_step4_loop_after_a_follow_up_prompt_stays_live(tmp_path, env):
    """A later prompt continues the interview once its opening turn reached Step 4."""
    transcript = _loop(tmp_path)
    code, err = _run(SPEC_FG, _payload(transcript, FOREGROUND), env)
    assert code == 2 and "(4/8 steps complete)" in err
    assert _run(LAUNCH, _payload(transcript, FOREGROUND), env)[0] == 2
    assert _run(BACKGROUND, _payload(transcript, BACKGROUND_EXPLORE), env)[0] == 0
    assert _run(BACKGROUND, _payload(transcript, BACKGROUND_GENERAL), env)[0] == 2


def test_spec_qa_ba_stay_exempt_in_a_live_interview(tmp_path, env):
    transcript = _opening_turn(tmp_path)
    for role in ("spec", "qa", "ba"):
        assert _run(SPEC_FG, _payload(transcript, dict(FOREGROUND, subagent_type=role)), env)[0] == 0


def test_a_step_set_back_after_the_prompt_does_not_make_a_live_loop_stale(tmp_path, env):
    """Staleness is read as of the first later prompt, so a TodoWrite after it cannot forge it."""
    tx = _Transcript()
    tx.command("spec", "add a retry cap")
    for step in range(0, 5):
        tx.todos(step)
    tx.typed("also cap the backoff at 30s")
    tx.todos(1)  # Steps 2.. set back to pending (if the validator ever let it through)
    payload = _payload(tx.write(tmp_path / "t.jsonl"), FOREGROUND)
    assert _run(SPEC_FG, payload, env)[0] == 2


@pytest.mark.parametrize("later", ["scheduled", "notification", "notification-plain", "tool-result"])
def test_only_a_human_prompt_ends_the_opening_turn(tmp_path, env, later):
    """A scheduled prompt (the agent's own CronCreate or wakeup), a task-notification (its own background
    agent finishing) or a tool result is not the human's prompt: the opening turn is still live."""
    tx = _Transcript()
    tx.command("spec")
    tx.todos(0)
    if later == "scheduled":
        tx.scheduled("check on the spec")
    elif later == "notification":
        tx.notification("<task-notification><status>completed</status></task-notification>")
    elif later == "notification-plain":
        tx.typed("<task-notification>\n<status>completed</status>\n</task-notification>")
    else:
        tx.tool("AskUserQuestion", {"questions": []})
    payload = _payload(tx.write(tmp_path / "t.jsonl"), FOREGROUND)
    assert _run(SPEC_FG, payload, env)[0] == 2
    assert _run(BACKGROUND, _payload(payload["transcript_path"], BACKGROUND_EXPLORE), env)[0] == 0


def test_a_new_spec_after_an_abandoned_one_is_live_again(tmp_path, env):
    tx = _Transcript()
    tx.command("spec")
    tx.todos(0)
    tx.typed("never mind")
    tx.command("spec", "add a retry cap")
    tx.todos(0)
    payload = _payload(tx.write(tmp_path / "t.jsonl"), FOREGROUND)
    assert _run(SPEC_FG, payload, env)[0] == 2


def test_live_spec_checklist_reading(tmp_path):
    assert todo_canonical.live_spec_checklist(_abandoned(tmp_path)) is None
    assert todo_canonical.live_spec_checklist(_opening_turn(tmp_path)).command == "spec"
    assert todo_canonical.live_spec_checklist(_loop(tmp_path)).command == "spec"
