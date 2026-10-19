"""A refused checkpoint snapshot never blocks a Stop (PR 4 review R5).

Drives the registered Stop hook, hooks/stop-workflow-coordinator.py with its four default
phases, in a throwaway copy of the harness home (hooks/ plus the two engines the refusal
runs). When the private-literal rule, the settings check or, with the filter registered, the
settings clean filter (a settings.json it cannot clean: a byte order mark, not JSON, not an
object) refuses the snapshot, nothing is written, the hook exits 0 with and without
stop_hook_active and past the failure-alert threshold, the cleanup phase still runs, and
systemMessage carries one line naming the rule and logs/checkpoint.log, never the stand-in
value. An ordinary snapshot is still written, and a refusal-free snapshot failure (also a
broken filter install) still fails the auto_commit phase as before.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STANDIN = "acct-test-123"  # stand-in personal value / listed literal
SID = "sess-r5-test"
REF = "refs/checkpoints/main"
PHASES = ["timelock", "coverage", "auto_commit", "cleanup"]
LITERAL_RULE = "the private-literal rule"
SETTINGS_CHECK = "the settings check (render-settings check --staged)"
SETTINGS_FILTER = "the settings filter (render-settings clean)"


def _git(env: dict, repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], env=env, text=True, capture_output=True, check=check
    ).stdout.strip()


@pytest.fixture
def harness(tmp_path: Path) -> tuple[Path, dict]:
    home = tmp_path / "harness"
    shutil.copytree(
        ROOT / "hooks", home / "hooks", ignore=shutil.ignore_patterns("tests", "__pycache__")
    )
    for rel in ("scripts/check-public-core.sh", "scripts/install/render-settings"):
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, home / rel)
    (home / ".gitignore").write_text("/settings.machine.json\n/private-literals.txt\n")
    (home / ".gitattributes").write_text("/settings.json filter=claude-settings\n")
    settings = {"permissions": {"allow": ["Bash(git status:*)"]}}
    (home / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    (tmp_path / "gitconfig").write_text("")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "HOME": str(tmp_path / "user-home"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "config"),
        "CLAUDE_STATE_DIR": str(tmp_path / "state"),
        "TMPDIR": str(tmp_path / "tmp"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    for key in ("HOME", "CLAUDE_STATE_DIR", "TMPDIR"):
        Path(env[key]).mkdir(parents=True)
    (tmp_path / "config" / "logs").mkdir(parents=True)  # an installed home has its logs/
    subprocess.run(["git", "init", "-q", "-b", "main", str(home)], env=env, check=True)
    _git(env, home, "add", "-A")
    _git(env, home, "commit", "-q", "-m", "init")
    return home, env


def _stop(home: Path, env: dict, *, active: bool) -> dict:
    """One Stop event through the registered hook, as Claude Code sends it."""
    flag = Path(env["CLAUDE_STATE_DIR"]) / f"claude-orchestrator-consent-{SID}.flag"
    flag.write_text("granted\n")  # the cleanup phase removes it
    payload = {
        "session_id": SID,
        "transcript_path": str(home / "transcript.jsonl"),
        "cwd": str(home),
        "hook_event_name": "Stop",
        "stop_hook_active": active,
    }
    proc = subprocess.run(
        [sys.executable, str(home / "hooks" / "stop-workflow-coordinator.py")],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(home),
        env={**env, "CLAUDE_PROJECT_DIR": str(home)},
        timeout=300,
    )
    return {
        "rc": proc.returncode,
        "raw": proc.stdout + proc.stderr,
        "out": json.loads(proc.stdout),
        "cleanup_ran": not flag.exists(),
    }


def _log(env: dict) -> str:
    path = Path(env["CLAUDE_CONFIG_DIR"]) / "logs" / "checkpoint.log"
    return path.read_text() if path.is_file() else ""


def _machine_form(home: Path, env: dict) -> None:
    """settings.json as smudge renders it from an overlay holding the stand-in."""
    overlay = {"permissions": {"allow": [f"Bash(/home/{STANDIN}/bin/sync.sh:*)"]}}
    (home / "settings.machine.json").write_text(json.dumps(overlay, indent=2) + "\n")
    rendered = subprocess.run(
        [sys.executable, "scripts/install/render-settings", "smudge"],
        input=(home / "settings.json").read_bytes(),
        capture_output=True,
        cwd=str(home),
        env=env,
        check=True,
    ).stdout
    (home / "settings.json").write_bytes(rendered)
    assert STANDIN in (home / "settings.json").read_text()


def _register_filter(home: Path, env: dict) -> None:
    """The settings filter as init registers it in the harness home's local git config."""
    for key in ("clean", "smudge"):
        _git(env, home, "config", f"filter.claude-settings.{key}",
             f"python3 scripts/install/render-settings {key}")
    _git(env, home, "config", "filter.claude-settings.required", "true")


# A machine-form settings.json the clean filter cannot clean: it exits non-zero, so staging fails.
UNCLEANABLE = {
    "bom": lambda data: b"\xef\xbb\xbf" + data,
    "not-json": lambda data: data.rstrip()[:-1],  # the closing brace dropped
    "not-object": lambda data: b"[" + data + b"]",
}


@pytest.mark.parametrize(
    "case, rules",
    [
        ("literal", LITERAL_RULE),
        ("settings", SETTINGS_CHECK),
        ("both", f"{LITERAL_RULE} and {SETTINGS_CHECK}"),
    ],
)
def test_refused_snapshot_never_blocks_a_stop(harness, case: str, rules: str) -> None:
    home, env = harness
    if case in ("literal", "both"):
        (home / "private-literals.txt").write_text(f"# stand-in list\n{STANDIN}\n")
    if case == "literal":
        (home / "leak.txt").write_text(f"ticket for {STANDIN}, demo only\n")
    else:  # machine form staged without the filter registered
        _machine_form(home, env)
    commits_before = _git(env, home, "rev-list", "--all", "--count")

    # Past CHECKPOINT_FAIL_ALERT_THRESHOLD (3): a refusal never escalates.
    for active in (False, True, False, True):
        stop = _stop(home, env, active=active)
        out = stop["out"]
        assert stop["rc"] == 0, stop["raw"]
        assert out["status"] == "pass" and "failed_phase" not in out, out
        assert [p["phase"] for p in out["phases"]] == PHASES
        assert all(p["status"] == "allow" for p in out["phases"]), out
        assert stop["cleanup_ran"], "the cleanup phase did not run"
        notice = out["systemMessage"]
        assert notice == (
            f"Checkpoint snapshot refused by {rules}: nothing written, see logs/checkpoint.log"
        )
        assert "\n" not in notice and STANDIN not in stop["raw"]

    assert _git(env, home, "for-each-ref", "refs/checkpoints") == ""
    assert _git(env, home, "rev-list", "--all", "--count") == commits_before
    log = _log(env)
    assert log.count(f"snapshot refused by {rules}: nothing written") == 4
    assert STANDIN not in log
    count = Path(env["CLAUDE_CONFIG_DIR"]) / "logs" / ".checkpoint-fail-count"
    assert not count.exists() or count.read_text().strip() == "0"


def test_ordinary_snapshot_is_still_written_without_a_notice(harness) -> None:
    home, env = harness
    (home / "private-literals.txt").write_text(f"{STANDIN}\n")  # the rule runs and passes
    (home / "notes.txt").write_text("ordinary note\n")
    stop = _stop(home, env, active=False)
    assert stop["rc"] == 0 and stop["out"]["status"] == "pass", stop["raw"]
    assert "systemMessage" not in stop["out"] and stop["cleanup_ran"]
    tip = _git(env, home, "rev-parse", "-q", "--verify", REF)
    assert _git(env, home, "show", f"{tip}:notes.txt") == "ordinary note"


def test_refusal_free_snapshot_failure_is_recorded_and_allowed(harness) -> None:
    """P1 (TC-11): a failed checkpoint never blocks a Stop; the failure is in the
    coordinator's result JSON and the cleanup phase still runs."""
    home, env = harness
    (home / "notes.txt").write_text("ordinary note\n")
    log = Path(env["CLAUDE_CONFIG_DIR"]) / "logs" / "checkpoint.log"
    log.mkdir()  # every `2>>checkpoint.log` redirect fails: read-tree fails, rc 1
    stop = _stop(home, env, active=False)
    out = stop["out"]
    assert stop["rc"] == 0 and "failed_phase" not in out, stop["raw"]
    assert [p["phase"] for p in out["phases"]] == PHASES
    auto_commit = out["phases"][PHASES.index("auto_commit")]
    assert auto_commit["status"] == "fail" and auto_commit["returncode"] == 1
    assert stop["cleanup_ran"], "the cleanup phase did not run"
    assert "systemMessage" not in out
    assert _git(env, home, "for-each-ref", "refs/checkpoints") == ""


@pytest.mark.parametrize("case", sorted(UNCLEANABLE))
def test_settings_json_the_clean_filter_refuses_never_blocks_a_stop(harness, case: str) -> None:
    home, env = harness
    _register_filter(home, env)
    _machine_form(home, env)
    (home / "notes.txt").write_text("ordinary note\n")
    first = _stop(home, env, active=False)  # filter registered: the clean form is snapshotted
    assert first["rc"] == 0 and "systemMessage" not in first["out"], first["raw"]
    tip = _git(env, home, "rev-parse", "-q", "--verify", REF)
    assert STANDIN not in _git(env, home, "show", f"{tip}:settings.json")
    settings = home / "settings.json"
    settings.write_bytes(UNCLEANABLE[case](settings.read_bytes()))
    assert STANDIN in settings.read_text(encoding="utf-8", errors="replace")
    (home / "notes.txt").write_text("second note\n")
    commits_before = _git(env, home, "rev-list", "--all", "--count")

    for active in (False, True, False, True):  # past the failure-alert threshold
        stop = _stop(home, env, active=active)
        out = stop["out"]
        assert stop["rc"] == 0, stop["raw"]
        assert out["status"] == "pass" and "failed_phase" not in out, out
        assert [p["phase"] for p in out["phases"]] == PHASES
        assert all(p["status"] == "allow" for p in out["phases"]), out
        assert stop["cleanup_ran"], "the cleanup phase did not run"
        assert out["systemMessage"] == (
            f"Checkpoint snapshot refused by {SETTINGS_FILTER}: nothing written,"
            " see logs/checkpoint.log"
        )
        assert STANDIN not in stop["raw"]

    assert _git(env, home, "rev-parse", "-q", "--verify", REF) == tip
    assert _git(env, home, "rev-list", "--all", "--count") == commits_before
    log = _log(env)
    assert log.count(f"snapshot refused by {SETTINGS_FILTER}: nothing written") == 4
    assert "add -A failed" not in log and STANDIN not in log
    count = Path(env["CLAUDE_CONFIG_DIR"]) / "logs" / ".checkpoint-fail-count"
    assert not count.exists() or count.read_text().strip() == "0"


def test_broken_filter_install_fails_the_phase_but_not_the_stop(harness) -> None:
    """The clean filter registered but its engine missing is a broken install, not a refusal."""
    home, env = harness
    _register_filter(home, env)
    settings = home / "settings.json"
    settings.write_bytes(UNCLEANABLE["bom"](settings.read_bytes()))  # uncleanable as well
    (home / "scripts" / "install" / "render-settings").unlink()
    stop = _stop(home, env, active=False)
    out = stop["out"]
    assert stop["rc"] == 0 and "failed_phase" not in out, stop["raw"]  # P1: recorded, allowed
    auto_commit = out["phases"][PHASES.index("auto_commit")]
    assert auto_commit["status"] == "fail" and auto_commit["returncode"] == 1
    assert stop["cleanup_ran"] and "systemMessage" not in out
    assert "add -A failed" in _log(env) and "snapshot refused" not in _log(env)
    assert _git(env, home, "for-each-ref", "refs/checkpoints") == ""
