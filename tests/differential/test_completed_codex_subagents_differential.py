"""Differential test: ``completed_codex_subagents`` before and after its refactor.

The frozen copy in completed_codex_subagents_legacy.py is the function as it was at
commit cc22f78. Both versions run on the same generated transcripts and step windows
(a fixed seed, so every run sees the same cases) and must give identical results: the
same records in the same order with the same keys in the same order, or the same
exception. The cases are built from the event shapes tests/test_codex_workflow_gate.py
uses (spawn_agent, sub_agent_activity started, the child's FINAL_ANSWER message,
list_agents and its output), as coherent scenarios with one or two mutations each, and
as random event soups from small pools so that identities collide and every early
return is reached.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import random
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SESSION = "session-diff"
BASE_MS = 1784559600000  # 2026-07-20T15:00:00Z
SEED = 20261110
SCENARIOS = 2500
SOUPS = 2500


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LIVE = _load("pretool_workflow_gate_differential", ROOT / "hooks" / "pretool-workflow-gate.py")
LEGACY = _load("completed_codex_subagents_legacy", Path(__file__).with_name("completed_codex_subagents_legacy.py"))

CALL_IDS = ["call-a", "call-b", "call-c"]
LIST_IDS = ["list-1", "list-2"]
TASKS = ["qa_lane", "dev_lane", "baqa_x"]
PREFIXES = ["/root/", "/root/sub/", "/other/"]
THREADS = ["thread-1", "thread-2", "thread-3"]
FINAL = "Message Type: FINAL_ANSWER\nPayload:\n"
BODIES = [
    "ok", "QA verdict: FAIL, two criteria unmet", "paused", "blocked: waiting", '{"status": "failed"}',
    '{"outcome": "Usage Limit"}', '{"status": 3}', '{"result": "ok"}', "usage limit reached", "no work",
    "No-work today", "timed out after 10m", "error - boom", "cancelled", "quota", "",
]


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _timestamp(rng: random.Random, ms: int, noisy: bool):
    roll = rng.random()
    if not noisy or roll < 0.9:
        return _iso(ms)
    return rng.choice([None, 17, "", "not a time", _iso(ms).replace("Z", ""), "2026-13-40T00:00:00Z"])


def _event(rng: random.Random, ms: int, type_: str, payload, noisy: bool = True) -> dict:
    event = {"type": type_, "payload": payload}
    stamp = _timestamp(rng, ms, noisy)
    if stamp is not None or rng.random() < 0.5:
        event["timestamp"] = stamp
    return event


def _spawn(rng, ms, call_id, task, noisy=True):
    arguments = rng.choice([
        json.dumps({"task_name": task, "message": "opaque"}), {"task_name": task}, "{not json",
        json.dumps({"task_name": "Bad-Name"}), json.dumps(["task_name"]), json.dumps({"message": "x"}),
    ]) if noisy and rng.random() < 0.25 else json.dumps({"task_name": task, "message": "opaque"})
    payload = {"type": "function_call", "name": "spawn_agent", "namespace": "collaboration",
               "call_id": call_id, "arguments": arguments}
    return _event(rng, ms, "response_item", payload, noisy)


def _start(rng, ms, call_id, path, thread, occurred, noisy=True):
    payload = {"type": "sub_agent_activity", "event_id": call_id, "kind": "started",
               "agent_path": path, "agent_thread_id": thread, "occurred_at_ms": occurred}
    return _event(rng, ms, "event_msg", payload, noisy)


def _final(rng, ms, author, body, noisy=True):
    content = [{"type": "input_text", "text": FINAL + body}]
    if noisy and rng.random() < 0.1:
        content = rng.choice([
            [{"type": "input_text", "text": "Message Type: PROGRESS\n" + body}],
            [{"type": "output_text", "text": FINAL + body}], "not a list", [7, {"type": "input_text", "text": 3}],
        ])
    return _event(rng, ms, "response_item", {"type": "agent_message", "author": author, "content": content}, noisy)


def _list_call(rng, ms, call_id, noisy=True):
    payload = {"type": "function_call", "namespace": "collaboration", "name": "list_agents",
               "call_id": call_id, "arguments": "{}"}
    return _event(rng, ms, "response_item", payload, noisy)


def _list_output(rng, ms, call_id, paths, status="completed", noisy=True):
    agents = [{"agent_name": p, "agent_status": {status: "runtime"}} for p in paths]
    output = {"agents": agents}
    roll = rng.random()
    if not noisy or roll < 0.75:
        output = json.dumps(output)
    elif roll < 0.85:
        output = rng.choice(["{not json", json.dumps([1]), json.dumps({"agents": "x"}), 5,
                             json.dumps({"agents": [3, {"agent_name": 4, "agent_status": {}},
                                                    {"agent_name": "/root/qa_lane", "agent_status": "completed"}]})])
    return _event(rng, ms, "response_item", {"type": "function_call_output", "call_id": call_id, "output": output},
                  noisy)


def _noise(rng, ms):
    return rng.choice([
        {"type": "response_item"},
        {"type": "response_item", "payload": "text", "timestamp": _iso(ms)},
        _event(rng, ms, "event_msg", {"type": "token_count"}),
        _event(rng, ms, "response_item", {"type": "function_call", "namespace": "other", "name": "spawn_agent",
                                          "call_id": "call-a", "arguments": json.dumps({"task_name": "qa_lane"})}),
        _event(rng, ms, "response_item", {"type": "function_call", "namespace": "collaboration", "name": "send_input",
                                          "call_id": "call-z"}),
        _event(rng, ms, "event_msg", {"type": "sub_agent_activity", "event_id": "call-a", "kind": "completed",
                                      "agent_path": "/root/qa_lane", "agent_thread_id": "thread-1",
                                      "occurred_at_ms": ms}),
        _event(rng, ms, "session_event", {"type": "agent_message", "author": "/root/qa_lane"}),
        [1, 2, 3],
        "a JSON string line",
    ])


def _scenario(rng: random.Random) -> list:
    """Coherent children (spawn, start, final, status), then up to two mutations."""
    events, ms = [], BASE_MS + rng.choice([0, 500, 1000])
    children = rng.choice([1, 1, 2, 3])  # distinct identities, unless a collision is drawn
    calls, tasks, threads = rng.sample(CALL_IDS, children), rng.sample(TASKS, children), rng.sample(THREADS, children)
    prefixes = [rng.choice(PREFIXES[:2]) for _ in range(children)]
    if children > 1 and rng.random() < 0.2:  # two children share a thread, or a task and its path
        if rng.random() < 0.5:
            threads[1] = threads[0]
        else:
            tasks[1], prefixes[1] = tasks[0], prefixes[0]
    for call_id, task, thread, prefix in zip(calls, tasks, threads, prefixes):
        path = prefix + task
        list_id = rng.choice(LIST_IDS)
        ms += rng.choice([100, 500, 1000])
        events.append(_spawn(rng, ms, call_id, task, noisy=False))
        ms += rng.choice([0, 100, 1000])
        events.append(_start(rng, ms, call_id, path, thread, ms + rng.choice([0, 0, 0, -200, 50]), noisy=False))
        for _ in range(rng.choice([1, 1, 2])):
            ms += rng.choice([0, 500, 1000])
            events.append(_final(rng, ms, path, rng.choice(BODIES[:2] * 6 + BODIES), noisy=False))
        ms += rng.choice([0, 1000, 2000])
        events.append(_list_call(rng, ms, list_id, noisy=False))
        events.append(_list_output(rng, ms + rng.choice([0, 0, 100, -3000]), list_id,
                                   [path] if rng.random() < 0.85 else [path, "/root/other"],
                                   status="completed" if rng.random() < 0.95 else "running", noisy=False))
    if rng.random() < 0.1:  # the first child starts again under another thread or path
        start = copy.deepcopy(next(e for e in events if e["payload"]["type"] == "sub_agent_activity"))
        if rng.random() < 0.5:
            start["payload"]["agent_thread_id"] = "thread-restarted"
        else:
            start["payload"]["agent_path"] = "/elsewhere/" + start["payload"]["agent_path"].rsplit("/", 1)[-1]
        events.insert(rng.randrange(len(events) + 1), start)
    for _ in range(rng.choice([0, 1, 1, 2])):
        _mutate(rng, events)
    return events


def _mutate(rng: random.Random, events: list) -> None:
    if not events:
        return
    at = rng.randrange(len(events))
    kind = rng.randrange(9)
    if kind == 0:
        del events[at]
    elif kind == 1:
        events.insert(at, copy.deepcopy(events[rng.randrange(len(events))]))
    elif kind == 2:
        rng.shuffle(events)
    elif kind == 3:
        events.insert(at, _noise(rng, BASE_MS + rng.randrange(0, 9000)))
    elif isinstance(events[at], dict) and isinstance(events[at].get("payload"), dict):
        payload = events[at]["payload"]
        key = rng.choice(sorted(payload))
        if kind == 4:
            del payload[key]
        elif kind == 5:
            payload[key] = rng.choice([None, 0, True, "", " ", [], {}, "call-b", "thread-2", "/root/dev_lane",
                                       BASE_MS + 9000, BASE_MS - 9000, 1.5])
        elif kind == 6:
            events[at]["timestamp"] = rng.choice([_iso(BASE_MS - 5000), _iso(BASE_MS + 20000), None, "bad"])
        elif kind == 7:
            events.append(copy.deepcopy(events[at]))
        else:
            events[at]["payload"] = rng.choice(["flat", None, [payload]])


def _soup(rng: random.Random) -> list:
    """Random events from small pools: identities collide, windows cut through them."""
    events = []
    for _ in range(rng.randrange(0, 16)):
        ms = BASE_MS + rng.randrange(-2000, 12000, 250)
        call_id, task = rng.choice(CALL_IDS), rng.choice(TASKS)
        path = rng.choice(PREFIXES) + rng.choice([task, task, "qa_lane"])
        roll = rng.randrange(7)
        if roll == 0:
            cid = call_id if rng.random() < 0.9 else rng.choice(["", None, 5])
            events.append(_spawn(rng, ms, cid, task))
        elif roll == 1:
            thread = rng.choice(THREADS + ["", "  ", None, 4])
            occurred = rng.choice([ms, ms, ms - 1000, ms + 1000, True, str(ms), None, float(ms)])
            cid = call_id if rng.random() < 0.95 else rng.choice([None, 7, "call-x"])
            events.append(_start(rng, ms, cid, path, thread, occurred))
        elif roll == 2:
            events.append(_final(rng, ms, path if rng.random() < 0.9 else rng.choice([None, 3, "/nobody"]),
                                 rng.choice(BODIES)))
        elif roll == 3:
            events.append(_list_call(rng, ms, rng.choice(LIST_IDS + ["", None, 9])))
        elif roll == 4:
            cid = rng.choice(LIST_IDS + [call_id])
            events.append(_list_output(rng, ms, cid, rng.sample(sorted({path, "/root/qa_lane", "/root/sub/dev_lane"}),
                                                                rng.randrange(0, 3))))
        else:
            events.append(_noise(rng, ms))
    return events


def _window(rng: random.Random, n_lines: int, scenario: bool) -> dict:
    offsets = [-1000, 0, 0, 0, 0, 500, 2500] if scenario else [-1000, 0, 0, 500, 1000, 2500, 6000]
    window = {"started_after_ms": BASE_MS + rng.choice(offsets)}
    if rng.random() < 0.3:
        window["completed_before_ms"] = BASE_MS + rng.randrange(0, 14000, 500)
    if rng.random() < 0.3:
        window["completed_before_line"] = rng.randrange(1, n_lines + 3)
    if rng.random() < 0.3:
        window["binding"] = rng.choice([{"step": 3, "lane": "a"}, {"call_id": "rebound"}, {}])
    return window


def _lines(rng: random.Random, events: list) -> list[str]:
    meta = {"timestamp": _iso(BASE_MS), "type": "session_meta", "payload": {"id": SESSION, "session_id": SESSION}}
    lines = [json.dumps(e) for e in events]
    lines.insert(rng.randrange(len(lines) + 1) if rng.random() < 0.2 else 0, json.dumps(meta))
    if rng.random() < 0.02:
        lines.insert(rng.randrange(len(lines) + 1), "")  # a blank line: the transcript does not parse
    return lines


def _outcome(fn, data, session_id, window):
    try:
        result = fn(data, session_id, **copy.deepcopy(window))
    except Exception as exc:  # the comparison includes the exception a malformed input raises
        return ("raise", type(exc).__name__, str(exc))
    return ("ok", [list(record.items()) for record in result])


def _run(data, session_id, window):
    started = window.pop("started_after_ms")
    call = lambda fn: _outcome(lambda d, s, **w: fn(d, s, started, **w), data, session_id, window)  # noqa: E731
    return call(LEGACY.completed_codex_subagents), call(LIVE.completed_codex_subagents)


def test_generated_transcripts_give_identical_results(tmp_path: Path) -> None:
    rng = random.Random(SEED)
    kinds = {"records": 0, "empty": 0, "raise": 0}
    mismatches = []
    for i in range(SCENARIOS + SOUPS):
        events = _scenario(rng) if i < SCENARIOS else _soup(rng)
        lines = _lines(rng, events)
        path = tmp_path / f"rollout-{i}-{SESSION}.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        window = _window(rng, len(lines), i < SCENARIOS)
        old, new = _run({"transcript_path": str(path)}, SESSION, dict(window))
        if old != new:
            mismatches.append((i, window, old, new))
        kinds["raise" if old[0] == "raise" else "records" if old[1] else "empty"] += 1
    assert not mismatches, mismatches[:3]
    # The generator must exercise each outcome, or agreement would prove little.
    assert kinds["records"] > 300 and kinds["empty"] > 300 and kinds["raise"] > 0, kinds


def test_unresolvable_or_unreadable_transcripts_give_identical_results(tmp_path: Path, monkeypatch) -> None:
    good = tmp_path / f"rollout-good-{SESSION}.jsonl"
    meta = {"timestamp": _iso(BASE_MS), "type": "session_meta", "payload": {"id": SESSION, "session_id": SESSION}}
    good.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    foreign = tmp_path / f"rollout-foreign-{SESSION}.jsonl"
    foreign.write_text(json.dumps({**meta, "payload": {"id": "other", "session_id": "other"}}) + "\n")
    undecodable = tmp_path / f"rollout-bytes-{SESSION}.jsonl"
    undecodable.write_bytes(b"\xff\xfe not utf-8\n")
    cases = [
        ({"transcript_path": str(good)}, ""),
        ({"transcript_path": str(tmp_path / "missing.jsonl")}, SESSION),
        ({"transcript_path": str(foreign)}, SESSION),
        ({"transcript_path": str(undecodable)}, SESSION),
        ({"transcript_path": str(good), "transcript": str(foreign)}, SESSION),
    ]
    for data, session_id in cases:
        old, new = _run(data, session_id, {"started_after_ms": BASE_MS})
        assert old == new, (data, old, new)

    def unreadable(self, *args, **kwargs):
        raise OSError("unreadable")

    monkeypatch.setattr(Path, "read_text", unreadable)
    old, new = _run({"transcript_path": str(good)}, SESSION, {"started_after_ms": BASE_MS})
    assert old == new == ("ok", [])
