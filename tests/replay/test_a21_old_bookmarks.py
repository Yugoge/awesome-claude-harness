"""A21's seeding case (P5-29): the workflow bookmarks a harness from before P5 left on disk.

A21 (prompts/short/P5.md): a session that loaded origin/master's hook list meets this tree's files,
with origin/master's state and transcripts; "pretool-tool-policy, pretool-todo-validate accept old
transcripts and bookmarks". tests/replay/test_live_arming.py builds A21's five sessions (an in-flight
/dev cycle, an in-flight /do with its sidecar, a /merge span with a blocked analysis, an open
/dev-overnight window, an ungated session) with no bookmark at all. Here each session also holds
the bookmark `<project>/.claude/workflow-<sid>.json` (and the checklist copy
`<config>/todos/<sid>-agent-<sid>.json`) in the shapes the writers before P5 left them:

- "pre-P5": the bookmark a7d3a9f's hooks/prompt-workflow.py writes at a command's start
  (command, workflow_instance_id, workflow_generation, workflow_started_at_ms, task_id,
  preservation_policy, start_envelope_sha256, arguments); no todo copies (P1b E7).
- "pre-P1b, in step": 78194a8's: the start's keys with todo_acknowledged, the list
  posttool-todo-sequence.py's save_state kept as last_todos (the transcript's own last list),
  posttool-subagent-track.py's subagent_calls, no lock.
- "pre-P1b, sequence lock": posttool-todo-sequence.py's _lock_bookmark after a refused list
  (todo_acknowledged false, lock_reason sequence_violation) over a last_todos that disagrees with
  the transcript: it holds the list two steps further on, the one a 2-step skip writes.
- "pre-P1b, count lock": posttool-todo-count.py's _emit_count_mismatch (lock_reason count_mismatch)
  over a 2-item last_todos.
- "torn": the first half of the in-step bookmark, as 78194a8's non-atomic write_text
  (prompt-workflow.py _write_bookmark, posttool-todo-sequence.py save_state) can leave it.

The ungated session's bookmark is a stale /dev one (an earlier command of that session); the
others name their own command. P5 (R18, R20) took every Claude-path reader off the bookmark: the
previous list is the transcript's (command_span.last_todos), the lock is the transcript's
(todo_canonical.checklist). So A21's outcome must not move with the bookmark: for each shape, every
event of A21's pipeline (each Stop under the pre-update hook list and under this tree's; a
PreToolUse TodoWrite, compliant and a 2-step skip, in the /dev cycle; a PreToolUse Read in each
session) gives every hook the verdict, exit code and output it gives with no bookmark; no hook
errs or prints a traceback; pretool-tool-policy.py and pretool-todo-validate.py accept the
compliant TodoWrite and the skip stays refused by pretool-todo-validate.py (a stale last_todos
neither blocks the compliant list nor admits the skip); A21's Stop outcomes hold as stated.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.replay import hookrun
from tests.replay.test_live_arming import (DO_ID, SID, SPANS, World, _blocked, _healthy, current_settings,
                                           pre_update_settings)

SHAPES = ("none", "pre-P5", "pre-P1b, in step", "pre-P1b, sequence lock", "pre-P1b, count lock", "torn")
COMMAND = {"dev": "dev", "do": "do", "merge": "merge", "window": "dev-overnight", "ungated": "dev"}
ARGS = {"dev": "fix the flaky test", "do": "rename the heading", "merge": "feature-x",
        "window": "1h harden the toy package", "ungated": "an earlier request"}
TASK = {"dev": "20261101-090000", "do": DO_ID}
NAMED = ("hooks/pretool-tool-policy.py", "hooks/pretool-todo-validate.py")


def _list(steps, done):
    return [{"content": s["content"], "activeForm": s.get("activeForm", s["content"]),
             "status": "completed" if k < done else ("in_progress" if k == done else "pending")}
            for k, s in enumerate(steps)]


def _steps(world: World, command: str) -> list:
    """The command's canonical checklist; a command with none (/merge) kept the list its session wrote."""
    if (world.home / ".claude" / "scripts" / "todo" / f"{command}.py").exists():
        return world.canonical(command)
    return [{"content": "Analyse the branch"}, {"content": "Merge the branch"}]


def _bookmark(world: World, name: str, shape: str):
    """(bookmark text, checklist copy or None) of ``shape`` for session ``name``."""
    started = {"command": COMMAND[name], "workflow_instance_id": "ab" * 32, "workflow_generation": 1,
               "workflow_started_at_ms": 1793523600000, "arguments": ARGS[name]}
    if shape == "pre-P5":
        if name in TASK:
            started.update(task_id=TASK[name], start_envelope_sha256="cd" * 32,
                           preservation_policy="immutable_prior_family_atomic_current_pointer/v1")
        return json.dumps(started, sort_keys=True), None
    steps = _steps(world, COMMAND[name])
    if shape in ("pre-P1b, in step", "torn"):
        last, extra = _list(steps, 3), {"todo_acknowledged": True, "subagent_calls": {"3": True}}
    elif shape == "pre-P1b, sequence lock":
        last = _list(steps, 6)
        extra = {"todo_acknowledged": False, "lock_reason": "sequence_violation",
                 "subagent_calls": {str(k): True for k in range(7)}}
    else:  # "pre-P1b, count lock"
        last, extra = _list(steps, 0)[:2], {"todo_acknowledged": False, "lock_reason": "count_mismatch"}
    text = json.dumps(dict(started, last_todos=last, **extra))
    return (text[:len(text) // 2] if shape == "torn" else text), json.dumps(last)


class SeededWorld(World):
    def __init__(self, tmp, shape):
        super().__init__(tmp)
        self.shape = shape
        self.seed()

    def paths(self, name):
        return (self.project / ".claude" / f"workflow-{SID[name]}.json",
                self.home / ".claude" / "todos" / f"{SID[name]}-agent-{SID[name]}.json")

    def seed(self):
        """Put each session's old bookmark (and checklist copy) back as the old harness left it."""
        if self.shape == "none":
            return
        for name in SID:
            bookmark, todos = self.paths(name)
            text, copy = _bookmark(self, name, self.shape)
            bookmark.parent.mkdir(parents=True, exist_ok=True)
            bookmark.write_text(text, encoding="utf-8")
            if copy is not None:
                todos.parent.mkdir(parents=True, exist_ok=True)
                todos.write_text(copy, encoding="utf-8")


def _events(world: SeededWorld) -> dict:
    """A21's pipeline on ``world``, each event run with the old files freshly seeded: label -> event."""
    out = {}
    old, new = pre_update_settings(), current_settings()
    steps = world.canonical("dev")
    for which, settings in (("pre-update", old), ("this tree", new)):
        for name in SID:
            world.seed()
            out[f"Stop {name} ({which})"] = world.run_stop(name, settings)
        for label, done in (("compliant", 4), ("2-step skip", 6)):
            world.seed()
            payload = dict(world.payload("dev"), tool_name="TodoWrite", tool_input={"todos": _list(steps, done)},
                           tool_use_id=f"toolu_a21_bm_{done}")
            out[f"TodoWrite dev {label} ({which})"] = hookrun.run_event(
                settings, "PreToolUse", payload, world.env(settings), str(world.project))
        for name in SID:
            world.seed()
            payload = dict(world.payload(name), tool_name="Read",
                           tool_input={"file_path": str(world.project / "README.md")}, tool_use_id="toolu_a21_bm_r")
            out[f"Read {name} ({which})"] = hookrun.run_event(
                settings, "PreToolUse", payload, world.env(settings), str(world.project))
    return out


WINDOW_LEFT = re.compile(r"open until \S+, \d+h \d+m left")


def _neutral_stdout(text: str) -> str:
    """The Stop coordinator's phase record with two digests set aside: the auto_commit phase's
    stdout (auto-commit.sh prints the snapshot's time and tip, "Checkpoint saved at" and "Tip:",
    which differ in every run) and the completion phase's stderr (it is the coordinator's relay, its
    own stderr, compared in full with the world's paths made neutral)."""
    try:
        record = json.loads(text)
    except ValueError:
        return text
    if not isinstance(record, dict) or not isinstance(record.get("phases"), list):
        return text
    for phase in record["phases"]:
        if isinstance(phase, dict) and phase.get("phase") == "auto_commit":
            phase["stdout_sha256"] = "<checkpoint time and tip>"
        if isinstance(phase, dict) and phase.get("phase") == "completion":
            phase["stderr_sha256"] = "<the relay, compared as stderr>"
    return json.dumps(record, sort_keys=True)


def _outcome(world: SeededWorld, event: dict) -> list:
    """Each hook's (name, verdict, rc, stdout, stderr), made neutral where a world differs from any
    other world whatever its bookmark: its paths, the checkpoint, and the window's end (World sets it
    an hour after its own construction)."""
    def neutral(text):
        return WINDOW_LEFT.sub("open until <end>", text.replace(str(world.tmp), "<world>"))
    return [(h["hook"], h["verdict"], h["rc"], _neutral_stdout(neutral(h["stdout"])), neutral(h["stderr"]))
            for h in event["hooks"]]


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """Each shape in a world of its own (the same events in the same order, so whatever state a hook
    leaves is alike in all of them), two worlds at a time."""
    dirs = {shape: tmp_path_factory.mktemp(f"a21bm{k}") for k, shape in enumerate(SHAPES)}

    def run(shape):
        world = SeededWorld(dirs[shape], shape)
        return world, _events(world)
    with ThreadPoolExecutor(max_workers=2) as pool:
        return dict(zip(SHAPES, pool.map(run, SHAPES)))


def _table(runs) -> str:
    rows = [f"{'shape':<24} {'events':>6} {'differ':>6} {'blocked':>7} {'errors':>6}"]
    for shape, (world, events) in runs.items():
        base_world, base = runs["none"]
        differ = sum(_outcome(world, e) != _outcome(base_world, base[label]) for label, e in events.items())
        rows.append(f"{shape:<24} {len(events):>6} {differ:>6} {sum(map(_blocked, events.values())):>7} "
                    f"{sum(bool(_healthy(e)) for e in events.values()):>6}")
    return "\n  ".join(rows)


def test_a21_seeded_shapes_are_the_old_writers(runs):
    """The seeded files are on disk where the old harness wrote them, in each shape."""
    for shape, (world, _events_) in runs.items():
        for name in SID:
            bookmark, todos = world.paths(name)
            assert bookmark.exists() == (shape != "none"), (shape, name)
            assert todos.exists() == (shape not in ("none", "pre-P5")), (shape, name)
            if shape.startswith("pre-P1b"):
                assert "last_todos" in json.loads(bookmark.read_text(encoding="utf-8")), (shape, name)


@pytest.mark.parametrize("shape", SHAPES[1:])
def test_a21_old_bookmarks_change_no_hook_outcome(runs, shape):
    """Every hook of every A21 event gives, with the old bookmark seeded, the verdict, exit code and
    output it gives with no bookmark."""
    print("\nA21 seeding (old bookmark shapes; each row against `none`):\n  " + _table(runs))
    base_world, base = runs["none"]
    world, events = runs[shape]
    assert events.keys() == base.keys()
    differ = {label: (_outcome(base_world, base[label]), _outcome(world, e))
              for label, e in events.items() if _outcome(world, e) != _outcome(base_world, base[label])}
    assert not differ, json.dumps(differ, indent=1)[:6000]


@pytest.mark.parametrize("shape", SHAPES)
def test_a21_with_old_bookmarks_the_outcome_is_a21s(runs, shape):
    """A21's outcome with the shape seeded: no hook errs or prints a traceback; the pre-update list
    holds no span (`would block` on the coordinator's stderr), this tree's list enforces each gated
    span, the open window blocks under both, the ungated session stops; pretool-tool-policy.py and
    pretool-todo-validate.py accept the compliant TodoWrite, the 2-step skip stays refused by
    pretool-todo-validate.py; a Read is held only by an unwritten checklist, never by an old lock."""
    _world, events = runs[shape]
    sick = {label: _healthy(e) for label, e in events.items() if _healthy(e)}
    assert not sick, sick
    for which in ("pre-update", "this tree"):
        for name in SID:
            event = events[f"Stop {name} ({which})"]
            if name == "window":
                assert _blocked(event) and "overnight window open until" in event["hooks"][0]["stderr"], event
            elif which == "pre-update":
                assert not _blocked(event), (name, event["hooks"])
                assert ("would block" in event["hooks"][0]["stderr"]) == (name in SPANS), event["hooks"][0]
            elif name in SPANS:
                launcher = event["hooks"][0]
                assert launcher["rc"] == 2 and launcher["stderr"].startswith(f"COMMAND_GATE /{name}: not complete"), \
                    launcher
            else:
                assert not _blocked(event), event["hooks"]
            # A Read is held only where the span's checklist has no ok TodoWrite yet (/do, the window):
            # never by an old lock, in the /dev cycle (its list written) or the ungated session.
            read = events[f"Read {name} ({which})"]
            held = [h["hook"] for h in read["hooks"] if h["verdict"] == "block"]
            assert held == (["hooks/pretool-workflow-gate.py"] if name in ("do", "window") else []), \
                (name, which, held, [h["stderr"][-300:] for h in read["hooks"] if h["verdict"] == "block"])
        ok = {h["hook"]: h for h in events[f"TodoWrite dev compliant ({which})"]["hooks"] if h["hook"] in NAMED}
        assert sorted(ok) == sorted(NAMED) and all(h["verdict"] == "ok" for h in ok.values()), ok
        skip = {h["hook"]: h for h in events[f"TodoWrite dev 2-step skip ({which})"]["hooks"]}
        assert skip["hooks/pretool-todo-validate.py"]["verdict"] == "block", skip["hooks/pretool-todo-validate.py"]
