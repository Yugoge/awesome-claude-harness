"""/rating: scripts/rating-view.py prints the score log's per-agent view of the working directory's project as plain
text, and commands/rating.md only runs that script.

Every run uses a temporary config directory (CLAUDE_CONFIG_DIR) and a temporary home, so the real home is never
read or written. The renderer itself is tested in tests/test_score_log.py; here the script is run as a process."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "rating-view.py"
COMMAND = REPO / "commands" / "rating.md"
sys.path.insert(0, str(REPO / "hooks" / "lib"))
import score_log  # noqa: E402

NO_RECORDS = "Scores (this project): no records yet."
LATER = "2999-01-01T00:00:00Z"


@pytest.fixture()
def world(tmp_path: Path) -> SimpleNamespace:
    """A git working copy with a sub-directory, an empty config directory and a home of its own."""
    project, config, home = tmp_path / "project", tmp_path / "config", tmp_path / "home"
    (project / "src").mkdir(parents=True)
    config.mkdir()
    home.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True, capture_output=True, env={**os.environ, "HOME": str(home)})
    return SimpleNamespace(project=project, config=config, home=home, log=config / "logs" / "lifecycle.jsonl",
                           key=score_log.project_key(project))


def _rows(key: str) -> list[dict]:
    """Event and rating rows of the project, rows of another project, and rows without kind (score-update.sh's)."""
    def event(n, role, points, why, name="qa_fail", project=key, day="2026-05-0"):
        return {"kind": "event", "ts": f"{day}{n}T10:00:00Z", "project": project, "task_id": f"2026050{n}-100000", "role": role,
                "event": name, "points": points, "key": f"{role}{n}{project}", "why": why, "ref": "ref"}

    rows = [event(n, "dev", -6 if n % 2 else 2, f"reason {n}", "qa_fail" if n % 2 else "qa_first_pass") for n in range(1, 7)]
    rows += [event(n, "qa", 1, f"caught {n}", "qa_catch") for n in (2, 4)]
    rows += [{"kind": "rating", "ts": f"2026-05-0{n}T11:00:00Z", "project": key, "task_id": f"2026050{n}-100000", "rating": 4,
              "roles": ["dev", "qa"], "tool_use_id": f"toolu_{n}"} for n in (3, 6)]
    rows += [event(1, "stranger", -50, "another project", project="c" * 12),
             {"ts": "2026-05-01T00:00:00Z", "agent": "ghost", "event": "old", "delta": -50, "new_score": 0}]
    return rows


def _write(world: SimpleNamespace, rows: list[dict], tail: str = "") -> None:
    world.log.parent.mkdir(parents=True, exist_ok=True)
    world.log.write_text("".join(json.dumps(row) + "\n" for row in rows) + tail, encoding="utf-8")


def _run(world: SimpleNamespace, cwd: Path | None = None, **env: str | None) -> subprocess.CompletedProcess:
    environ = {"PATH": os.environ["PATH"], "HOME": str(world.home), "CLAUDE_CONFIG_DIR": str(world.config),
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", **env}
    environ = {name: value for name, value in environ.items() if value is not None}
    return subprocess.run([sys.executable, "-B", str(SCRIPT)], cwd=cwd or world.project, env=environ, capture_output=True,
                          text=True, encoding="utf-8", timeout=60)


def _tree(path: Path) -> list:
    return sorted((str(p.relative_to(path)), p.stat().st_mtime_ns, p.stat().st_size if p.is_file() else -1) for p in path.rglob("*"))


def test_the_script_prints_the_renderers_text_for_the_working_directorys_project(world: SimpleNamespace) -> None:
    rows = _rows(world.key)
    _write(world, rows)
    expected = score_log.render_rating_view(rows, world.key, LATER) + "\n"
    for cwd in (world.project, world.project / "src"):  # a sub-directory belongs to the same project
        done = _run(world, cwd)
        assert (done.returncode, done.stdout, done.stderr) == (0, expected, "")
    lines = expected.splitlines()
    assert lines[0] == "Scores (this project), lowest first"
    assert [line.split(":")[0] for line in lines if re.fullmatch(r"\S+: -?\d+ \[Rank: .+\]", line)] == ["dev", "main", "qa"]
    assert "stranger" not in expected and "ghost" not in expected


def test_the_default_log_is_under_the_homes_dot_claude_when_no_config_directory_is_set(world: SimpleNamespace) -> None:
    rows = _rows(world.key)
    world.log = world.home / ".claude" / "logs" / "lifecycle.jsonl"
    _write(world, rows)
    done = _run(world, CLAUDE_CONFIG_DIR=None)
    assert done.stdout == score_log.render_rating_view(rows, world.key, LATER) + "\n" and done.returncode == 0


def test_the_output_is_plain_text(world: SimpleNamespace) -> None:
    _write(world, _rows(world.key))
    out = _run(world).stdout
    assert out and not re.search(r"</?[A-Za-z!][^>]*>", out) and "\x1b" not in out
    assert not re.search(r"[\x00-\x09\x0b-\x1f\x7f]", out) and {c for c in out if ord(c) > 127} <= set("▁▂▃▅▇")


@pytest.mark.parametrize("log", ["missing", "empty", "blank lines", "another project only", "no kind only"])
def test_a_log_with_no_record_for_the_project_means_no_records_yet(world: SimpleNamespace, log: str) -> None:
    if log == "empty":
        _write(world, [])
    elif log == "blank lines":
        _write(world, [], "\n\n")
    elif log == "another project only":
        _write(world, _rows("d" * 12))
    elif log == "no kind only":
        _write(world, [{"ts": "2026-05-01T00:00:00Z", "agent": "dev", "event": "old", "delta": 2, "new_score": 52}])
    done = _run(world)
    assert (done.returncode, done.stdout, done.stderr) == (0, NO_RECORDS + "\n", "")
    if log == "missing":
        assert list(world.config.iterdir()) == []  # the view creates nothing, not even the logs directory


@pytest.mark.parametrize("damage", ["malformed middle line", "directory", "undecodable"])
def test_a_log_that_cannot_be_read_gives_one_clear_line_and_exit_0(world: SimpleNamespace, damage: str) -> None:
    if damage == "malformed middle line":
        rows = _rows(world.key)
        _write(world, rows[:2], "{not json,,\n" + "".join(json.dumps(row) + "\n" for row in rows[2:4]))
    elif damage == "directory":
        world.log.mkdir(parents=True)
    else:
        world.log.parent.mkdir(parents=True)
        world.log.write_bytes(b"\xff\xfe\x00 not utf-8\n")
    done = _run(world)
    assert done.returncode == 0 and done.stderr == ""
    assert len(done.stdout.splitlines()) == 1 and done.stdout.startswith("The score log cannot be read: ")
    assert "Traceback" not in done.stdout and (damage != "malformed middle line" or "line 3" in done.stdout)


def test_a_partial_last_line_is_skipped_and_the_rest_is_shown(world: SimpleNamespace) -> None:
    rows = _rows(world.key)
    _write(world, rows, '{"kind": "event", "ts": "2026-05-0')
    assert _run(world).stdout == score_log.render_rating_view(rows, world.key, LATER) + "\n"


def test_the_script_only_reads(world: SimpleNamespace) -> None:
    _write(world, _rows(world.key))
    before = (_tree(world.config), _tree(world.project / ".git"), _tree(world.home))
    assert _run(world).returncode == 0
    assert (_tree(world.config), _tree(world.project / ".git"), _tree(world.home)) == before
    assert sorted(p.name for p in world.log.parent.iterdir()) == ["lifecycle.jsonl"]  # no lock file, no temporary file


def test_a_terminal_that_cannot_show_the_glyphs_gets_replacements_not_a_traceback(world: SimpleNamespace) -> None:
    _write(world, _rows(world.key))
    done = _run(world, PYTHONIOENCODING="ascii")
    assert done.returncode == 0 and done.stderr == "" and "?" in done.stdout and "Traceback" not in done.stdout


# --------------------------------------------------------------------------
# commands/rating.md
# --------------------------------------------------------------------------

def _command() -> tuple[dict, str]:
    head, body = COMMAND.read_text(encoding="utf-8").split("---\n", 2)[1:]
    return dict(line.split(": ", 1) for line in head.strip().splitlines()), body


def test_the_command_is_human_only_and_denied_to_the_skill_tool() -> None:
    front, _ = _command()
    assert front["disable-model-invocation"] == "true" and front["description"].strip()
    settings = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))
    assert "Skill(rating:*)" in settings["permissions"]["deny"]
    assert not [rule for rule in settings["permissions"]["allow"] if "rating" in rule]


def test_the_command_runs_the_script_and_shows_its_output_unchanged() -> None:
    _, body = _command()
    fences = re.findall(r"```(\w*)\n(.*?)```", body, re.S)
    assert fences == [("bash", 'python3 "<HARNESS_ROOT>/scripts/rating-view.py"\n')] and SCRIPT.is_file()
    assert "exactly as printed" in body and "Add nothing" in body
    assert len(body.strip().splitlines()) <= 10


def test_the_command_text_follows_the_prompt_rules() -> None:
    text = COMMAND.read_text(encoding="utf-8")
    assert len(re.findall(r"\b[A-Z]{3,}\b", text.replace("<HARNESS_ROOT>", ""))) <= 3  # emphasis words
    assert not re.search(r"block", text, re.I) and not re.search(r"\b(?:previously|formerly|used to|no longer|legacy)\b", text, re.I)
    for path in re.findall(r"\b(?:scripts|hooks|commands|agents|tests|docs)/[\w./-]+", text):
        assert (REPO / path).exists(), path  # a reference to a file that does not exist
