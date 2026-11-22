"""A cycle that declares no file: /commit lands the tree's changes no open cycle claims (scripts/steps/commit-plan.py
`unclaimed`, commands/commit.md Steps 5-7), leaves the ones an open cycle claims, and a cycle with files is unchanged.
Throwaway repositories and a throwaway bare remote only; the commit and the push are made by this test's own code, as
changelog-analyst (Phases 5-8) and /push would make them from the plan."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("COMMIT_PLAN_SCRIPT") or REPO_ROOT / "scripts" / "steps" / "commit-plan.py")
TASK, OTHER, LANDED = "20260101-000100", "20260101-000200", "20260101-000300"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    for name in ("seed.txt", "claimed.txt", "old.txt"):
        (path / name).write_text("seed\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "seed")
    return path.resolve()


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _do_report(control: Path, task: str, modified: list[str]) -> None:
    _write(control / "docs" / "dev" / f"do-report-{task}.json", {
        "report_version": 1, "task_id": task, "request_id": task, "request": "r", "source": "do",
        "do": {"status": "completed", "summary": "s", "files_modified": modified, "files_created": []}})


def _dev_report(control: Path, task: str, modified: list[str]) -> None:
    _write(control / "docs" / "dev" / f"dev-report-{task}.json", {
        "task_id": task, "request_id": task, "dev": {"files_modified": modified, "files_created": []},
        "owned_edits": {p: [{"old": "x", "new": "y"}] for p in modified}})


@pytest.fixture()
def world(tmp_path: Path):
    control, home = _repo(tmp_path / "control"), _repo(tmp_path / "harness-home")
    (control / "docs" / "dev").mkdir(parents=True)
    (control / "docs" / "dev" / f"close-report-{TASK}.md").write_text("# Close\n\nCLOSE: YES\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "CLAUDE_CODE_SESSION_ID",
                                                            "CLAUDE_CONFIG_DIRS", "CLAUDE_RESTART_ACCOUNTS_ROOT")}
    env.update(CLAUDE_HOME=str(home), CLAUDE_STATE_DIR=str(tmp_path / "state"), HOME=str(tmp_path / "home"),
               ATTRIBUTION_STATE_DIR=str(tmp_path / "attr"), CLAUDE_SESSION_ID="s1", PYTHONDONTWRITEBYTECODE="1",
               CLAUDE_CONFIG_DIR=str(tmp_path / "config"))
    return tmp_path, control, env


def _plan(control: Path, env: dict, *extra: str) -> dict:
    proc = subprocess.run([sys.executable, str(SCRIPT), "--task-id", TASK, *extra], cwd=control, env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout)


def test_a_cycle_with_no_files_lands_the_unclaimed_changes_and_they_push(world) -> None:
    tmp, control, env = world
    _do_report(control, TASK, [])
    (control / "seed.txt").write_text("changed\n", encoding="utf-8")
    (control / "new.txt").write_text("new\n", encoding="utf-8")

    out = _plan(control, env)

    assert out["plan_error"] is None and out["repository_plan"]["repositories"][0]["owned_paths"] == []
    assert out["unclaimed"]["paths"] == ["new.txt", "seed.txt"]  # docs/dev is never swept
    assert {Path(p).name for p in out["attribution_log"]["no_events"]} == {"new.txt", "seed.txt"}
    # what changelog-analyst does with the plan (Phases 5-8), then a push to a throwaway remote
    remote = tmp / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _git(control, "remote", "add", "origin", str(remote))
    _git(control, "add", "--", *out["unclaimed"]["paths"])
    message = tmp / "msg.txt"
    message.write_text(f"chore(repo): land unclaimed changes\n\nTask-id: {TASK}\n"
                       f"Unclaimed: {len(out['unclaimed']['paths'])} file(s) no open cycle claims, landed by /commit\n",
                       encoding="utf-8")
    _git(control, "commit", "-q", "-F", str(message))
    _git(control, "push", "-q", "origin", "main")
    assert set(_git(remote, "show", "--name-only", "--format=", "main").split()) == {"new.txt", "seed.txt"}
    assert "Unclaimed: 2 file(s)" in _git(remote, "log", "-1", "--format=%B", "main")
    assert _plan(control, env)["unclaimed"]["paths"] == []  # nothing left to land


def test_changes_an_open_cycle_claims_stay_and_a_landed_cycles_claim_lapses(world) -> None:
    _tmp, control, env = world
    _do_report(control, TASK, [])
    _dev_report(control, OTHER, ["claimed.txt"])          # open: no Task-id line of its own in HEAD
    _dev_report(control, LANDED, ["old.txt"])
    _git(control, "commit", "-q", "--allow-empty", "-m", f"landed\n\nTask-id: {LANDED}")
    for name in ("claimed.txt", "old.txt", "seed.txt"):
        (control / name).write_text("changed\n", encoding="utf-8")

    sweep = _plan(control, env)["unclaimed"]

    assert sweep["paths"] == ["old.txt", "seed.txt"]
    assert sweep["claimed_by_open_cycles"] == {"claimed.txt": [OTHER]}
    left = _plan(control, env, "--leave-unclaimed", "old.txt")["unclaimed"]  # a path commit QA rejected
    assert left["paths"] == ["seed.txt"] and left["left"] == ["old.txt"]


def _session(env: dict, session: str, *prompts: str) -> None:
    """A session's transcript as the CLI keeps it: one human-typed prompt record per prompt."""
    path = Path(env["CLAUDE_CONFIG_DIR"]) / "projects" / "-a-project" / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps({"type": "user", "timestamp": "2026-01-01T00:00:00Z",
                                        "message": {"role": "user", "content": text}}) + "\n" for text in prompts),
                    encoding="utf-8")


def _edit(env: dict, session: str, path: Path) -> None:
    """One edit as the attribution hooks journal it (hooks/lib/attribution_journal.py), in the session's journal."""
    journal = Path(env["ATTRIBUTION_STATE_DIR"]) / "journals" / f"{session}.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"seq": 1, "session_id": session, "path": str(path), "pre_sha": "absent",
                                 "post_sha": "0" * 40, "ts": 1893456000.0, "tool": "Write",
                                 "invocation_id": f"call-{path.name}"}) + "\n")


def test_two_working_sessions_an_open_command_without_a_report_keeps_its_edits(world) -> None:
    _tmp, control, env = world
    _do_report(control, TASK, [])
    _session(env, "s1", "/do a task", "/close", "/commit")   # this /commit's own session
    _session(env, "s2", "/dev more work")                    # still working: no report yet
    _session(env, "s3", "a plain question")                  # no command open
    for name in ("claimed.txt", "old.txt", "seed.txt"):
        (control / name).write_text("changed\n", encoding="utf-8")
    (control / "new.txt").write_text("nobody's\n", encoding="utf-8")
    (control / "far.txt").write_text("far\n", encoding="utf-8")
    _edit(env, "s1", control / "seed.txt")
    _edit(env, "s2", control / "claimed.txt")
    _edit(env, "s3", control / "old.txt")
    _edit(env, "s4", control / "far.txt")                    # a session no configuration directory holds

    sweep = _plan(control, env)["unclaimed"]

    assert sweep["paths"] == ["new.txt", "old.txt", "seed.txt"]
    assert sweep["claimed_by_open_commands"] == {"claimed.txt": ["s2"], "far.txt": ["s4"]}
    assert sweep["unresolved_sessions"] == ["s4"]
    assert sweep["claimed_by_open_cycles"] == {}


def test_a_cycle_with_files_is_unchanged(world) -> None:
    _tmp, control, env = world
    _dev_report(control, TASK, ["seed.txt"])
    (control / "seed.txt").write_text("changed\n", encoding="utf-8")
    (control / "stray.txt").write_text("stray\n", encoding="utf-8")

    out = _plan(control, env)

    assert "unclaimed" not in out
    assert out["repository_plan"]["repositories"][0]["owned_paths"] == ["seed.txt"]
    assert [Path(p).name for p in out["attribution_log"]["no_events"]] == ["seed.txt"]
