"""The close-pending listing reads the transcript store once, not once per task and gap.

/close and /commit find their candidate tasks with `list-actionable`. For each task waiting to be
closed, the close listing asks who owes each gap of its chain (resolve-dev-artifact-chain.py
unowed_gap -> obligation.declaring_dispatch), and each answer read every session transcript of the
project anew: a project with a long history and a few unfinished tasks took more than twenty
minutes, with no output. A scan now reads each transcript once for every task and gap
(obligation.transcript_scan), the commit listing (which never uses those answers) reads none, and
a scan that runs long says so on stderr. Its answers are the ones each call gives alone.

Every transcript record here is a recorded CLI record (tests/fixtures/cli), values filled in.
"""

from __future__ import annotations

import io
import json
import os
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _dev_lifecycle_fixtures import (  # noqa: E402
    REPO_ROOT,
    ba_qa_report,
    completion_md,
    dev_dir,
    dev_report,
    dlc,
    make_project,
    qa_report,
    write_json,
    write_text,
    write_ticket_fixture,
)

sys.path.insert(0, str(REPO_ROOT))
from hooks.lib import obligation  # noqa: E402
from hooks.lib.subagent_restart import project_slug  # noqa: E402
from tests.cli_shapes import check_record, synthesize  # noqa: E402

ABANDONED = [f"2026010{d}-0{d}0000" for d in range(1, 6)]  # a dev-report and nothing else: no owner
FANOUT = "20260110-100000"  # a fan-out whose lane l2 QA never ran, its /dev session in the store
PASSING = "20260111-110000"
FILLERS = 12


# --------------------------------------------------------------------------- the store
_OPENED: list[str] | None = None


def _audit(event, args):  # every open of a file (builtins.open, io.open, os.open, Path.read_bytes)
    if _OPENED is not None and event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        _OPENED.append(os.fsdecode(args[0]))


sys.addaudithook(_audit)


def _store(project: Path) -> Path:
    store = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / project_slug(project)
    store.mkdir(parents=True, exist_ok=True)
    return store


def _session(project: Path, name: str, records: list[dict]) -> Path:
    path = _store(project) / f"{name}.jsonl"
    for record in records:
        record["sessionId"] = name
        if "cwd" in record:
            record["cwd"] = str(project)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _typed(command: str, args: str) -> dict:
    return synthesize("user", "command", turnOrigin="human", message__content=(
        f"<command-message>{command} is running…</command-message>\n"
        f"<command-name>/{command}</command-name>\n<command-args>{args}</command-args>"))


def _talk(text: str) -> list[dict]:
    return [synthesize("user", "prompt", message__content=text),
            synthesize("assistant", "text", message__content=[{"type": "text", "text": text}])]


def _lane_dispatch(task: str, lane: str) -> dict:
    lane_id = f"{task}-{lane}"
    doc = {"task_id": lane_id, "lane": lane, "lane_set": ["l1", "l2"], "role": "dev", "pipeline": "dev",
           "profile": "fanout-lane", "dispatched_at": "2026-01-10T10:05:00Z",
           "artifacts": [{"kind": "json", "path": f"docs/dev/dev-report-{lane_id}.json",
                          "schema": "dev-report.v2", "identity": {"task_id": lane_id}}]}
    return synthesize("assistant", "tool_use", message__content=[
        {"type": "tool_use", "id": f"toolu_dev_{lane}", "name": "Agent",
         "input": {"subagent_type": "dev", "prompt": "Do the work.\n" + obligation.serialize_obligation(doc)}}])


def _history(tmp_path) -> Path:
    """Five abandoned tasks, a fan-out with a gap its /dev session owes, a passing task; a store of
    ordinary sessions (two of them name an abandoned task) and the fan-out's /dev session."""
    project = make_project(tmp_path)
    dd = dev_dir(project)
    for task in ABANDONED:
        write_json(dd / f"dev-report-{task}.json", dev_report(task))
    write_text(dd / f"ticket-{FANOUT}.md", f"Task-id: {FANOUT}\n")
    write_json(dd / f"dev-report-{FANOUT}.json", dev_report(FANOUT, parallel_workers=["l1", "l2"]))
    for lane in ("l1", "l2"):
        write_text(dd / f"ticket-{FANOUT}-{lane}.md", f"Task-id: {FANOUT}-{lane}\n")
        write_json(dd / f"dev-report-{FANOUT}-{lane}.json", dev_report(f"{FANOUT}-{lane}"))
    write_json(dd / f"qa-report-{FANOUT}-l1.json", qa_report(f"{FANOUT}-l1"))
    write_ticket_fixture(project, PASSING)
    write_json(dd / f"ba-qa-report-{PASSING}.json", ba_qa_report(PASSING, top_verdict="pass"))
    write_json(dd / f"dev-report-{PASSING}.json", dev_report(PASSING))
    write_json(dd / f"qa-report-{PASSING}.json", qa_report(PASSING))
    write_text(dd / f"completion-{PASSING}.md", completion_md(PASSING))
    for n in range(FILLERS):
        mention = f"what happened to {ABANDONED[0]}?" if n in (3, 7) else "carry on with the refactor"
        _session(project, f"filler-{n:02d}", [_typed("dev", "tidy up"), *_talk(mention), *_talk("done " * 200)])
    _session(project, "dev-fanout", [_typed("dev", "build the feature"),
                                     _lane_dispatch(FANOUT, "l1"), _lane_dispatch(FANOUT, "l2")])
    return project


def _list(project: Path, action: str, capsys) -> tuple[list[str], list[str], dict[str, int]]:
    """list-actionable's stdout and stderr lines, and how often each store file was opened."""
    global _OPENED
    store = str(_store(project))
    capsys.readouterr()
    _OPENED = []
    try:
        assert dlc.main(["list-actionable", "--next-action", action, "--project-dir", str(project)]) == 0
    finally:
        opened, _OPENED = _OPENED, None
    out = capsys.readouterr()
    counts: dict[str, int] = {}
    for path in opened:
        if path.startswith(store + os.sep):
            counts[Path(path).name] = counts.get(Path(path).name, 0) + 1
    return out.out.splitlines(), out.err.splitlines(), counts


# --------------------------------------------------------------------------- bounded reads
def test_the_store_holds_the_records_the_cli_records(tmp_path):
    project = _history(tmp_path)
    records = [json.loads(line) for path in sorted(_store(project).glob("*.jsonl"))
               for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == FILLERS * 5 + 3
    assert [problem for record in records for problem in check_record(record)] == []


def test_the_close_listing_reads_each_transcript_once_for_every_task_and_gap(tmp_path, capsys):
    project = _history(tmp_path)
    out, err, opened = _list(project, "close", capsys)
    # the listing itself: the fan-out (its gap has an owner) and the passing task; each abandoned
    # task passed over with its reason
    assert [line.split(" ", 1)[0] for line in out] == [FANOUT, PASSING]
    assert err == [f"{task}: skipped: no dispatch record or todo step owes docs/dev/ticket-{task}.md"
                   for task in ABANDONED]
    # the reads: a transcript naming none of the tasks is read once, whatever the number of tasks
    # and gaps (before: once per gap of every task newer than it); one naming a task is read once
    # more to take its dispatch records and command spans
    named = {"filler-03.jsonl", "filler-07.jsonl", "dev-fanout.jsonl"}
    sessions = {p.name for p in _store(project).glob("*.jsonl")}
    assert set(opened) == sessions
    assert {name: n for name, n in opened.items() if name not in named} == {name: 1 for name in sessions - named}
    assert all(opened[name] <= 3 for name in named), opened


def test_the_commit_listing_reads_no_transcript(tmp_path, capsys):
    # who owes a gap (auto_skip) is the close listing's question only
    project = _history(tmp_path)
    out, err, opened = _list(project, "commit", capsys)
    assert (out, err, opened) == ([], [], {})


def test_one_scan_answers_as_each_call_alone(tmp_path):
    # every owner question of every task, asked inside one scan and each on its own
    project = _history(tmp_path)
    resolver = dlc._load_resolver_module()
    questions = [(task, gap["artifact"]) for task in [*ABANDONED, FANOUT, PASSING]
                 for gap in resolver.disposition(project, task, "dev")["gaps"]]
    assert len(questions) > len(ABANDONED)
    alone = [obligation.declaring_dispatch(task, path, project) for task, path in questions]
    with obligation.transcript_scan() as scan:
        together = [obligation.declaring_dispatch(task, path, project) for task, path in questions]
        again = [obligation.declaring_dispatch(task, path, project) for task, path in questions]
        records = [obligation._task_records(task, project, None) for task in [*ABANDONED, FANOUT]]
    assert scan.transcripts == FILLERS + 1
    assert together == alone == again and any(alone) and None in alone
    assert records == [obligation._task_records(task, project, None) for task in [*ABANDONED, FANOUT]]
    # an answer a caller changes is its own copy
    task, path = questions[-1]
    with obligation.transcript_scan():
        first = obligation.declaring_dispatch(task, path, project)
        next(value for value in first.values() if isinstance(value, dict)).clear()
        assert obligation.declaring_dispatch(task, path, project) == alone[-1] != first


def test_the_rows_and_listings_are_the_ones_each_derivation_gives_alone(tmp_path, capsys):
    project = _history(tmp_path)
    alone = {task: dlc.derive_state(project, task) for task in [*ABANDONED, FANOUT, PASSING]}
    rows = {row["task_id"]: row for row in dlc.scan(project)}
    assert {task: rows[task] for task in alone} == alone
    assert dlc.auto_targets(project, "close") == [FANOUT, PASSING]
    assert dlc.auto_targets(project, "commit") == []


# --------------------------------------------------------------------------- the one-read test of a family
_ID_CHARS = "0123456789-._lxdevcommand"


@pytest.mark.parametrize("seed", range(6))
def test_a_family_is_named_by_a_transcript_exactly_when_its_bytes_hold_it(tmp_path, seed):
    # the scan decides from one read which families a transcript names; each answer is the
    # transcript's bytes', on text dense with ids, stamps glued to other id characters,
    # overlapping stamps, and multibyte text around them
    rng = random.Random(seed)
    stamps = ["20260101-000001", "20260101-000002", "20260101-12345678-123456"]

    def noise() -> str:
        parts = []
        for _ in range(rng.randint(20, 60)):
            pick = rng.random()
            if pick < 0.4:
                stamp = rng.choice(stamps)
                parts.append("".join(rng.choice(_ID_CHARS) for _ in range(rng.randint(0, 3))) + stamp
                             + "".join(rng.choice(_ID_CHARS) for _ in range(rng.randint(0, 4))))
            elif pick < 0.7:
                parts.append("".join(rng.choice(_ID_CHARS) for _ in range(rng.randint(1, 12))))
            else:
                parts.append(rng.choice([" ", "/", "\"", "é", "—", "\\", "\n", "}"]))
        return "".join(parts)

    project = make_project(tmp_path)
    transcripts = [_session(project, f"s{k}", _talk(noise()) + _talk(noise())) for k in range(8)]
    families = {"20260101-000001", "20260101-000002", "20260101-000001-l1", "20260101-000002-0",
                "20260101-000001.x", "120260101-000001", "12345678-123456", "20260101-12345678",
                "x20260101-000002", "20260101-000001-ldev", "20260101-000003"}
    for transcript in transcripts:
        text = transcript.read_bytes()
        families |= {text[m.start() - 10:m.end() + 3].decode("ascii", "ignore").strip("\\/\" ")
                     for m in obligation._STAMP_DASH_RE.finditer(text) if m.start() >= 10}
    families = {f for f in families if obligation._INDEXABLE_FAMILY_RE.fullmatch(f)}
    with obligation.transcript_scan() as scan:
        decided = {(t.name, f): obligation._mentions(t, f) for t in transcripts for f in sorted(families)}
    assert scan.transcripts == len(transcripts)
    assert decided == {(t.name, f): f.encode() in t.read_bytes() for t in transcripts for f in sorted(families)}
    assert any(decided.values()) and not all(decided.values())


# --------------------------------------------------------------------------- progress
def test_a_long_scan_reports_its_progress_on_stderr_and_names_no_task_first(tmp_path):
    project = _history(tmp_path)
    stream = io.StringIO()
    rows = dlc.scan(project, progress=dlc.Progress(after=0, stream=stream))
    lines = stream.getvalue().splitlines()
    assert {row["task_id"] for row in rows} >= {*ABANDONED, FANOUT, PASSING}
    assert lines and all(line.startswith("dev-lifecycle.py: still scanning after ") for line in lines)
    assert any(f"task 1 of " in line for line in lines)
    assert any(f"; {FILLERS + 1} session transcripts read (" in line for line in lines)
    assert not any(": skipped: " in line for line in lines)  # /close reads only "<task-id>: skipped:" lines


def test_progress_is_silent_at_first_then_at_most_one_line_per_interval():
    now = [100.0]
    stream = io.StringIO()
    progress = dlc.Progress(after=10, stream=stream, clock=lambda: now[0])

    class Scan:
        transcripts, bytes = 3, 5_000_000

    for step in range(30):  # one event a second for 30 seconds
        now[0] = 100.0 + step
        progress.task(step + 1, 30, f"20260101-0000{step:02d}")
        progress.read(Scan)
    assert stream.getvalue().splitlines() == [
        "dev-lifecycle.py: still scanning after 10s: task 11 of 30 (20260101-000010); "
        "3 session transcripts read (5 MB)",
        "dev-lifecycle.py: still scanning after 20s: task 21 of 30 (20260101-000020); "
        "3 session transcripts read (5 MB)",
    ]
