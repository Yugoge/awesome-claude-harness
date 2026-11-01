"""scripts/apply-permissions.sh, the harness's one writer of a project's .claude/settings.json.

/dev and /dev-command apply the permissions QA validated with the line their permission step
shows, as /dev-overnight applies its aggregated list: the cases run that line, taken from the
command text, in a toy project that has no .claude/settings.json. A missing file is an empty
object to the merge, so the file is created when the merge adds an entry; a merge that adds
nothing writes nothing; an existing file keeps what it holds and gains only the missing entries;
a file the settings load finds unusable fails the merge and stays unchanged.

HOME is a temporary directory whose .claude is this checkout, so the line's ~/.claude/scripts/
paths run the scripts under test; no CLAUDE_* variable is inherited.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
APPLY = REPO / "scripts" / "apply-permissions.sh"
TASK = "20260101-120000"
VALIDATED = [
    {"pattern": "Bash(scripts/new-script.sh:*)", "section": "allow", "status": "approved"},
    {"pattern": "Bash(scripts/purge-cache.sh:*)", "section": "ask", "status": "approved"},
]


def step_line(command):
    """The line of the command's permission step that calls apply-permissions.sh."""
    text = (REPO / "commands" / command).read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if "apply-permissions.sh" in ln
             and not ln.lstrip().startswith(("#", "-", "*", ">"))]
    assert len(lines) == 1, lines
    return lines[0].replace("<timestamp>", TASK)


@pytest.fixture
def project(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").symlink_to(REPO)
    proj = tmp_path / "toyproj"
    (proj / "docs" / "dev").mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(home), CLAUDE_PROJECT_DIR=str(proj), PYTHONDONTWRITEBYTECODE="1")
    return proj, env


def qa_report(proj, validated):
    report = {"qa": {"status": "pass", "permissions_verification": {
        "status": "pass", "permissions_count": len(validated), "issues": [],
        "validated_permissions": validated}}}
    path = proj / "docs" / "dev" / ("qa-report-%s.json" % TASK)
    path.write_text(json.dumps(report), encoding="utf-8")


def run_step(command, proj, env):
    return subprocess.run(["bash", "-c", step_line(command)], cwd=str(proj), env=env,
                          capture_output=True, text=True, timeout=60)


def apply(perms, settings, env, tmp_path):
    src = tmp_path / "perms.json"
    src.write_text(json.dumps(perms), encoding="utf-8")
    return subprocess.run(["bash", str(APPLY), str(src), str(settings)], env=env,
                          capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("command", ["dev.md", "dev-command.md"])
def test_the_permission_step_creates_a_missing_project_settings_file(project, command):
    proj, env = project
    qa_report(proj, VALIDATED)
    settings = proj / ".claude" / "settings.json"
    assert not settings.parent.exists()
    first = run_step(command, proj, env)
    assert first.returncode == 0, first.stderr
    assert json.loads(settings.read_text(encoding="utf-8")) == {"permissions": {
        "allow": ["Bash(scripts/new-script.sh:*)"], "ask": ["Bash(scripts/purge-cache.sh:*)"],
        "deny": []}}
    before = (settings.read_bytes(), settings.stat().st_mtime_ns)
    again = run_step(command, proj, env)  # every entry present: nothing to add, nothing written
    assert again.returncode == 0, again.stderr
    assert (settings.read_bytes(), settings.stat().st_mtime_ns) == before


@pytest.mark.parametrize("command", ["dev.md", "dev-command.md"])
def test_nothing_validated_leaves_the_file_absent(project, command):
    proj, env = project
    qa_report(proj, [])
    result = run_step(command, proj, env)
    assert result.returncode == 0, result.stderr
    assert not (proj / ".claude").exists()


def test_an_existing_file_gains_only_the_missing_entries(project, tmp_path):
    proj, env = project
    settings = proj / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"model": "demo", "permissions": {
        "allow": ["Read(docs/**)", "Bash(scripts/new-script.sh:*)"]}}), encoding="utf-8")
    result = apply(VALIDATED, settings, env, tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(settings.read_text(encoding="utf-8")) == {"model": "demo", "permissions": {
        "allow": ["Read(docs/**)", "Bash(scripts/new-script.sh:*)"],
        "ask": ["Bash(scripts/purge-cache.sh:*)"]}}


@pytest.mark.parametrize("data, reason", [
    (b'{"permissions": {"allow": [}\n', "not valid JSON ("),
    (b'{"permissions": {"allow": "Read"}}\n', "permissions.allow is not a list of strings"),
])
def test_an_unusable_file_fails_the_merge_and_stays_unchanged(project, tmp_path, data, reason):
    """The file is read through the one load of a settings file (hooks/lib/claude_home.py
    load_settings): its verdict refuses the merge, with its reason."""
    proj, env = project
    settings = proj / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_bytes(data)
    result = apply(VALIDATED, settings, env, tmp_path)
    assert result.returncode != 0
    assert "%s: %s" % (settings, reason) in result.stderr
    assert settings.read_bytes() == data
