"""scripts/steps/commit-plan.py: /commit Step 5's plan call, run for real against temporary git
repositories and temporary report files (no network, nothing read from the owner's home)."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _late_repair_fixtures as fx  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "steps" / "commit-plan.py"
CONTROLLER = REPO_ROOT / "scripts" / "late-repair-controller.py"
TASK = "20260101-000100"
EMPTY_ATTRIBUTION = {"results": [], "no_events": [], "discarded_lines": []}


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return done.stdout


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(path, "add", "seed.txt")
    _git(path, "commit", "-q", "-m", "seed")
    return path.resolve()


def _env(tmp: Path, home: Path, **extra: str) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_PROJECT_DIR", "CLAUDE_STATE_DIR", "CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID",
                        "CONTROL_ROOT")}
    env.update(CLAUDE_HOME=str(home), CLAUDE_STATE_DIR=str(tmp / "state"), ATTRIBUTION_STATE_DIR=str(tmp / "attr"),
               CLAUDE_CODE_SESSION_ID="session-under-test", HOME=str(tmp / "owner-home"),
               PYTHONDONTWRITEBYTECODE="1")
    env.update(extra)
    return env


def _plan(control: Path, env: dict, task: str = TASK, check: bool = True) -> dict:
    proc = subprocess.run([sys.executable, str(SCRIPT), "--task-id", task], cwd=control, env=env,
                          capture_output=True, text=True)
    if check:
        assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout)


def _write(path: Path, doc: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _dev_report(control: Path, task: str, modified: list[str]) -> Path:
    return _write(control / "docs" / "dev" / f"dev-report-{task}.json", {
        "task_id": task, "request_id": task, "dev": {"files_modified": modified, "files_created": []},
        "owned_edits": {p: [{"old": "x", "new": "y"}] for p in modified}})


def _do_report(control: Path, task: str, modified: list[str], status: str = "completed",
               source: str | None = "do") -> Path:
    doc = {"report_version": 1, "task_id": task, "request_id": task, "request": "r",
           "do": {"status": status, "summary": "s", "files_modified": modified, "files_created": []}}
    if source:
        doc["source"] = source
    return _write(control / "docs" / "dev" / f"do-report-{task}.json", doc)


def _close_report(control: Path, task: str = TASK) -> Path:
    path = control / "docs" / "dev" / f"close-report-{task}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Close\n\nCLOSE: YES\n", encoding="utf-8")
    return path


@pytest.fixture()
def world(tmp_path: Path):
    control = _repo(tmp_path / "control")
    home = _repo(tmp_path / "harness-home")
    (control / "owned.txt").write_text("owned change\n", encoding="utf-8")
    return tmp_path, control, home


def test_one_call_prints_the_plan_and_every_fact_the_next_steps_read(world) -> None:
    tmp, control, home = world
    report = _dev_report(control, TASK, ["owned.txt"])
    close = _close_report(control)

    out = _plan(control, _env(tmp, home))

    assert out["task_id"] == TASK
    assert Path(out["control_root"]) == control and Path(out["nested_repo"]) == home
    assert Path(out["close_report"]) == close
    assert out["late_repair"] == {"state": "none", "path": None}
    assert Path(out["task_report"]) == report
    assert out["plan_error"] is None
    plan = out["repository_plan"]
    assert plan["task_id"] == TASK and Path(plan["report_path"]) == report
    [entry] = plan["repositories"]
    assert Path(entry["repo_root"]) == control and entry["owned_paths"] == ["owned.txt"]
    assert entry["branch"] == _git(control, "branch", "--show-current").strip()
    assert entry["expected_head"] == _git(control, "rev-parse", "HEAD").strip()
    # the attribution slice covers exactly the plan's owned paths; no journal event is no failure
    assert out["attribution_log"]["results"] == []
    assert [Path(p) for p in out["attribution_log"]["no_events"]] == [control / "owned.txt"]
    # the manifest's inputs: session id, its path under the state dir, each plan entry's porcelain status
    assert out["session_id"] == "session-under-test"
    assert out["manifest_path"] == str(tmp / "state" / "claude-commit-manifest-session-under-test.json")
    assert out["files_at_dispatch"] == {str(control): _git(control, "status", "--porcelain=v1").splitlines()}
    assert any("owned.txt" in line for line in out["files_at_dispatch"][str(control)])


def test_a_second_supported_repository_is_planned_and_its_status_read(world) -> None:
    tmp, control, home = world
    (home / "nested.txt").write_text("nested change\n", encoding="utf-8")
    _dev_report(control, TASK, ["owned.txt", str(home / "nested.txt")])
    _close_report(control)

    out = _plan(control, _env(tmp, home))

    assert [Path(e["repo_root"]) for e in out["repository_plan"]["repositories"]] == [control, home]
    assert set(out["files_at_dispatch"]) == {str(control), str(home)}
    assert any("nested.txt" in line for line in out["files_at_dispatch"][str(home)])
    assert {Path(p).name for p in out["attribution_log"]["no_events"]} == {"owned.txt", "nested.txt"}


def test_a_plan_that_owns_no_path_asks_the_verifier_nothing(world) -> None:
    tmp, control, home = world
    _dev_report(control, TASK, [])
    _close_report(control)

    out = _plan(control, _env(tmp, home))

    assert out["plan_error"] is None
    assert out["repository_plan"]["repositories"][0]["owned_paths"] == []
    assert out["attribution_log"] == EMPTY_ATTRIBUTION  # not the whole journal


@pytest.mark.parametrize("reports,expected", [
    (("dev",), "dev"),
    (("do",), "do"),
    (("dev", "do-completed"), "do"),   # P4-22: the disposition plans from a completed do-report
    (("dev", "do-blocked"), "dev"),    # dev's report concludes a /do task whose do-report is not completed
    (("dev", "do-no-source"), "dev"),  # a do-report that is no /do task's is no plan source
], ids=["dev-only", "do-only", "both-do-completed", "both-do-blocked", "both-do-without-source"])
def test_the_report_is_the_one_the_disposition_plans_from(world, reports, expected) -> None:
    tmp, control, home = world
    _close_report(control)
    paths = {}
    if "dev" in reports:
        paths["dev"] = _dev_report(control, TASK, ["owned.txt"])
    for name in reports:
        if name.startswith("do"):
            status = "blocked" if name == "do-blocked" else "completed"
            paths["do"] = _do_report(control, TASK, ["owned.txt"], status,
                                     source=None if name == "do-no-source" else "do")

    out = _plan(control, _env(tmp, home))

    assert Path(out["task_report"]) == paths[expected]
    assert out["plan_error"] is None
    assert Path(out["repository_plan"]["report_path"]) == paths[expected]


def test_the_do_report_is_the_planned_report_even_when_a_dev_report_also_exists(world) -> None:
    """The disposition (resolve-dev-artifact-chain.py) and Step 5 agree for a /do task that has both."""
    tmp, control, home = world
    _close_report(control)
    _dev_report(control, TASK, ["owned.txt"])
    do = _do_report(control, TASK, ["owned.txt"])
    spec = importlib.util.spec_from_file_location("_chain_under_test", REPO_ROOT / "scripts" / "resolve-dev-artifact-chain.py")
    chain = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(chain)
    problems = [g for g in chain.disposition(control, TASK, "dev")["gaps"]
                if g["artifact"].endswith(f"do-report-{TASK}.json")]
    assert problems == []  # the disposition takes the completed do-report as the task's report

    out = _plan(control, _env(tmp, home))

    assert Path(out["task_report"]) == do
    assert Path(out["repository_plan"]["report_path"]) == do


def test_a_plan_that_cannot_be_built_is_a_fact_not_a_failure(world) -> None:
    tmp, control, home = world
    _close_report(control)
    (control / "docs" / "dev" / f"dev-report-{TASK}.json").write_text("{not json", encoding="utf-8")

    out = _plan(control, _env(tmp, home))

    assert out["repository_plan"] is None
    assert "resolve-commit-repos: BLOCKED" in out["plan_error"]
    assert out["attribution_log"] == EMPTY_ATTRIBUTION and out["files_at_dispatch"] == {}
    assert Path(out["task_report"]) == control / "docs" / "dev" / f"dev-report-{TASK}.json"


def test_no_report_at_all_names_the_dev_report_as_the_finding_path(world) -> None:
    tmp, control, home = world
    _close_report(control)

    out = _plan(control, _env(tmp, home))

    assert out["repository_plan"] is None and out["plan_error"]
    assert Path(out["task_report"]) == control / "docs" / "dev" / f"dev-report-{TASK}.json"


def test_without_a_close_report_the_docs_root_is_the_resolvers_fallback(world) -> None:
    tmp, control, home = world
    fallback = tmp / "fallback"
    (fallback / "docs" / "dev").mkdir(parents=True)

    out = _plan(control, _env(tmp, home, CONTROL_ROOT=str(fallback)))

    assert Path(out["close_report"]) == fallback / "docs" / "dev" / f"close-report-{TASK}.md"
    assert Path(out["task_report"]) == fallback / "docs" / "dev" / f"dev-report-{TASK}.json"
    assert out["repository_plan"] is None


def test_the_reports_are_the_ones_beside_the_close_report_of_another_project(world) -> None:
    tmp, control, home = world
    other = tmp / "other-project"
    report = _dev_report(other, TASK, ["owned.txt"])
    close = _close_report(other)
    _dev_report(control, TASK, ["seed.txt"])    # the control checkout's own report must not be the one read

    out = _plan(control, _env(tmp, home, CLAUDE_PROJECT_DIR=str(other)))

    assert Path(out["close_report"]) == close
    assert Path(out["task_report"]) == report


def test_the_session_id_comes_from_either_variable_and_the_manifest_path_follows_it(world) -> None:
    tmp, control, home = world
    _dev_report(control, TASK, ["owned.txt"])
    _close_report(control)
    env = _env(tmp, home)
    del env["CLAUDE_CODE_SESSION_ID"]

    none = _plan(control, env)
    assert none["session_id"] == "" and none["manifest_path"] is None

    fallback = _plan(control, {**env, "CLAUDE_SESSION_ID": "fallback-id"})
    assert fallback["session_id"] == "fallback-id"
    assert fallback["manifest_path"] == str(tmp / "state" / "claude-commit-manifest-fallback-id.json")

    primary = _plan(control, {**env, "CLAUDE_SESSION_ID": "fallback-id", "CLAUDE_CODE_SESSION_ID": "primary-id"})
    assert primary["session_id"] == "primary-id"


def test_a_late_repair_run_without_an_outcome_is_state_invalid_and_names_finalizes_artifact(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    home = _repo(tmp_path / "harness-home")
    fx.build_beyond_qa_clean(control, TASK)
    _close_report(control)
    init = subprocess.run([sys.executable, str(CONTROLLER), "init", "--task-id", TASK, "--project-dir", str(control)],
                          capture_output=True, text=True)
    assert init.returncode == 0, init.stdout + init.stderr

    out = _plan(control, _env(tmp_path, home))

    assert out["late_repair"]["state"] == "invalid"
    assert Path(out["late_repair"]["path"]) == control / "docs" / "dev" / f"dev-report-{TASK}.effective.json"
    assert Path(out["task_report"]) == control / "docs" / "dev" / f"dev-report-{TASK}.json"  # not the effective one


def test_the_task_id_is_required(world) -> None:
    tmp, control, home = world
    proc = subprocess.run([sys.executable, str(SCRIPT)], cwd=control, env=_env(tmp, home), capture_output=True,
                          text=True)
    assert proc.returncode == 2 and "--task-id" in proc.stderr


def test_the_call_commit_md_spells_runs_this_script(world) -> None:
    """The prompt's one Bash call for Step 5 is a call of this script, as the text writes it."""
    tmp, control, home = world
    _dev_report(control, TASK, ["owned.txt"])
    _close_report(control)
    text = (REPO_ROOT / "commands" / "commit.md").read_text(encoding="utf-8")
    step5 = text[text.index("### Step 5:"):text.index("### Step 6:")]
    [call] = [b for b in re.findall(r"```bash\n(.*?)```", step5, re.S) if "commit-plan.py" in b]

    env = _env(tmp, home, CLAUDE_HOME=str(REPO_ROOT), TASK_ID=TASK)
    env["CLAUDE_HOME"] = str(REPO_ROOT)
    proc = subprocess.run(["bash", "-c", call], cwd=control, env=env, capture_output=True, text=True)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["task_id"] == TASK and out["repository_plan"]["repositories"][0]["owned_paths"] == ["owned.txt"]
