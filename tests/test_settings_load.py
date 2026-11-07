"""The one load of a settings file (hooks/lib/claude_home.py load_settings) and the deciders that
take its verdict which no other test runs: the claude_home probes, installer.py's plan, and the two
reference checks /clean runs (scripts/check-file-references.sh, scripts/detect-orphan-scripts.sh).

A settings.json or settings.local.json is its JSON object with the shapes the deciders rely on,
absent, or unusable with a reason; "unparseable" below is the file's own bytes replaced by as many
"{" (E1's mutation, at the same size).
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LIB = REPO / "hooks" / "lib"
sys.path.insert(0, str(LIB))
from claude_home import load_settings  # noqa: E402


def env_without_homes(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
    env.update(HOME=str(tmp_path / "nohome"), PYTHONDONTWRITEBYTECODE="1",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return env


def unparseable(path):
    path.write_bytes(b"{" * path.stat().st_size)


@pytest.mark.parametrize("data, reason", [
    (b"{", "not valid JSON ("),
    (b"\xff{}", "not valid JSON ("),
    (b"[]", "not a JSON object"),
    (b'{"permissions": []}', "permissions is not an object"),
    (b'{"permissions": {"deny": "Bash(rm:*)"}}', "permissions.deny is not a list of strings"),
    (b'{"permissions": {"allow": [1]}}', "permissions.allow is not a list of strings"),
    (b'{"env": []}', "env is not an object"),
    (b'{"hooks": []}', "hooks is not an object"),
    (b'{"hooks": {"Stop": {}}}', "hooks.Stop is not a list"),
])
def test_an_unusable_file_is_named_with_its_reason(tmp_path, data, reason):
    path = tmp_path / "settings.json"
    path.write_bytes(data)
    settings, problem = load_settings(path)
    assert settings is None and problem.startswith(f"{path}: {reason}")
    proc = subprocess.run([sys.executable, str(LIB / "claude_home.py"), "settings", str(path)],
                          capture_output=True, text=True, env=env_without_homes(tmp_path))
    assert (proc.returncode, proc.stdout) == (1, "")
    assert proc.stderr.startswith(f"{path}: {reason}")


def test_a_usable_file_is_its_object_and_a_missing_one_is_absent(tmp_path):
    path = tmp_path / "settings.json"
    doc = {"permissions": {"allow": ["Read"], "defaultMode": "plan"}, "env": {"A": "1"},
           "hooks": {"Stop": [{"hooks": []}]}, "model": "demo"}
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert load_settings(path) == (doc, None)
    assert load_settings(tmp_path / "missing.json") == (None, None)
    cli = [sys.executable, str(LIB / "claude_home.py"), "settings"]
    env = env_without_homes(tmp_path)
    proc = subprocess.run(cli + [str(path)], capture_output=True, text=True, env=env)
    assert proc.returncode == 0 and json.loads(proc.stdout) == doc
    proc = subprocess.run(cli + [str(tmp_path / "missing.json")], capture_output=True, text=True,
                          env=env)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


@pytest.fixture
def home(tmp_path):
    """A harness home: the sentinel set plus a copy of both resolvers."""
    h = tmp_path / "home"
    for sub in ("hooks/lib", "policies", "scripts"):
        (h / sub).mkdir(parents=True)
    for name in ("claude_home.sh", "claude_home.py"):
        shutil.copy2(LIB / name, h / "hooks" / "lib" / name)
    (h / "settings.json").write_text('{\n  "env": {}\n}\n', encoding="utf-8")
    return Path(os.path.realpath(h))


def resolved(home, tmp_path):
    env = env_without_homes(tmp_path)
    sh = subprocess.run(["bash", str(home / "hooks/lib/claude_home.sh"), "resolve"],
                        capture_output=True, text=True, env=env)
    py = subprocess.run([sys.executable, str(home / "hooks/lib/claude_home.py"), "resolve"],
                        capture_output=True, text=True, env=env)
    return sh.stdout.strip() or None, py.stdout.strip() or None


def test_the_probes_take_the_loads_verdict_on_a_missing_file(home, tmp_path):
    assert resolved(home, tmp_path) == (str(home), str(home))
    unparseable(home / "settings.json")  # unusable still marks the home, as on the base
    assert resolved(home, tmp_path) == (str(home), str(home))
    (home / "settings.json").unlink()
    assert resolved(home, tmp_path) == (None, None)


def plan(tmp_path, config):
    proc = subprocess.run([sys.executable, str(REPO / "scripts/install/installer.py"), "plan",
                           "--json", "--config-dir", str(config), "--prefix",
                           str(tmp_path / "prefix")],
                          capture_output=True, text=True, env=env_without_homes(tmp_path))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_installer_plan_takes_the_loads_verdict(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    target = config / "settings.json"
    target.write_text('{\n  "permissions": {"allow": []}\n}\n', encoding="utf-8")
    assert plan(tmp_path, config)["settings_plan"]["change_kind"] == "modify"
    unparseable(target)
    out = plan(tmp_path, config)
    assert out["settings_plan"] is None
    details = [c["detail"] for c in out["conflicts"] if c["path"] == "settings.json"]
    assert len(details) == 1 and details[0].startswith(f"{target}: not valid JSON (")
    assert details[0].endswith("; left untouched")
    target.unlink()
    assert plan(tmp_path, config)["settings_plan"]["change_kind"] == "create"


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / "scripts").mkdir()
    (proj / "scripts" / "zz-demo-fix.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    env = env_without_homes(tmp_path)
    subprocess.run(["git", "init", "-q", str(proj)], check=True, env=env)
    subprocess.run(["git", "-C", str(proj), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True, env=env)
    return proj


def test_reference_checks_take_the_loads_verdict(project, tmp_path):
    settings = project / ".claude" / "settings.json"
    settings.write_text('{\n  "env": {"DEMO": "scripts/zz-demo-fix.sh"}\n}\n', encoding="utf-8")
    env = env_without_homes(tmp_path)

    def check_refs():
        return subprocess.run(["bash", str(REPO / "scripts/check-file-references.sh"),
                               "scripts/zz-demo-fix.sh", str(project)], capture_output=True,
                              text=True, env=env, cwd=str(project))

    def orphans():
        proc = subprocess.run(["bash", str(REPO / "scripts/detect-orphan-scripts.sh"),
                               str(project)], capture_output=True, text=True, env=env,
                              cwd=str(project))
        assert proc.returncode == 0, proc.stderr
        return proc

    named = check_refs()
    assert named.returncode == 1 and "Found reference in .claude/settings.json" in named.stdout
    assert "zz-demo-fix.sh" not in orphans().stdout

    unparseable(settings)  # cannot show the name is unreferenced: counted as a reference
    proc = check_refs()
    assert proc.returncode == 1 and "is unusable (see above): counted as a reference" in proc.stdout
    assert ".claude/settings.json: not valid JSON (" in proc.stderr
    proc = orphans()
    assert "zz-demo-fix.sh" not in proc.stdout and "not valid JSON (" in proc.stderr

    settings.unlink()  # absent: no reference
    assert "No config file references" in check_refs().stdout
    assert "zz-demo-fix.sh" in orphans().stdout
