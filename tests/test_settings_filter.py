"""Tests for scripts/install/render-settings: the settings clean/smudge filter and its record of
applied layers, the machine-form renderer, the doctor and pre-commit checks, and the owner
migration (P7, R2 and R5).

Every git repository is created under the test's temporary directory, HOME and
CLAUDE_CONFIG_DIR point at temporary directories, and the filter is registered only in each test
repository's own local config (pointing at a copy of the script inside that repository, because
the script resolves its harness home from its own location). All values are synthetic stand-ins.
"""
import ast
import copy
import importlib.machinery
import importlib.util
import json
import os
import random
import shlex
import shutil
import stat
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "install" / "render-settings"
RUNTIME_GUARD = REPO / "hooks" / "lib" / "runtime_guard"
CHANNEL = "${CLAUDE_HOME:-$HOME/.claude}"
OLD_HOME = "/opt/demo/.claude"  # stand-in for the absolute harness home an old settings file used
RUNCODE = "mcp__playwright__browser_run_code"
PASEO_RUNCODE = "mcp__paseo__browser_run_code"
STRUCTURED = ("env", "permissions", "hooks")
CLI_OWNED = ("model", "alwaysThinkingEnabled", "effortLevel", "tui", "theme",
             "autoCompactEnabled", "modelSettings", "fastMode", "advisorModel")
HOOK_FILES = ("hooks/session-info.sh", "hooks/userprompt-demo.py", "hooks/pretool-bash-safety.sh",
              "hooks/pretool-runcode-watchdog.py", "hooks/posttool-runcode-watchdog.py",
              "hooks/stop-demo.py", "hooks/userprompt-usage-snapshot.py")


def canon(obj):
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def hook(kind, rel, prefix=None, quoted=True, **extra):
    path = "%s/%s" % (prefix or CHANNEL, rel)
    command = '%s "%s"' % (kind, path) if quoted else "%s %s" % (kind, path)
    return dict({"type": "command", "command": command}, **extra)


def clean_form():
    """A synthetic clean-form settings.json (channel-form hooks, no machine values)."""
    return {
        "cleanupPeriodDays": 30,
        "env": {"GIT_AUTO_PUSH": "0", "LANG": "C.UTF-8", "TMPDIR": "/var/tmp/claude-scratch"},
        "includeCoAuthoredBy": True,
        "permissions": {"allow": ["Bash(git status:*)", "Bash(~/.claude/scripts/demo-tool.sh:*)"],
                        "deny": ["Bash(rm -rf /:*)"], "ask": []},
        "deniedMcpServers": [],
        "hooks": {
            "SessionStart": [{"hooks": [hook("bash", "hooks/session-info.sh")]}],
            "UserPromptSubmit": [{"hooks": [hook("python3", "hooks/userprompt-demo.py")]}],
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [hook("bash", "hooks/pretool-bash-safety.sh")]},
                {"matcher": RUNCODE,
                 "hooks": [hook("python3", "hooks/pretool-runcode-watchdog.py")]},
            ],
            "PostToolUse": [
                {"matcher": RUNCODE,
                 "hooks": [hook("python3", "hooks/posttool-runcode-watchdog.py")]},
            ],
            "Stop": [{"hooks": [hook("python3", "hooks/stop-demo.py")]}],
        },
    }


def overlay_doc(home, token):
    """Overrides an existing env key, adds env keys, adds allow and deny entries, adds a CLI-owned
    key, enables the paseo module and carries meta keys."""
    return {
        "_comment": "synthetic overlay for tests",
        "modules": {"paseo": True},
        "env": {"TMPDIR": "/opt/demo/%s" % token, "CLAUDE_HOME": str(home), "DEMO_FLAG": "1"},
        "permissions": {"allow": ["Bash(/opt/demo/bin/helper:*)"], "deny": ["Bash(demo-danger:*)"]},
        "model": "demo-model-x",
    }


# ------------------------------------------------------------------------------------ fixtures

@pytest.fixture
def sb(tmp_path, monkeypatch):
    """Isolated environment: scratch HOME and CLAUDE_CONFIG_DIR, no inherited git or harness
    variables, an empty global git config and a protected-runtime path under tmp_path."""
    user_home = tmp_path / "userhome"
    config_dir = tmp_path / "config-dir"
    user_home.mkdir()
    config_dir.mkdir()
    drop = ("CLAUDE_HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_PROTECTED_RUNTIME_FILE")
    for key in list(os.environ):
        if key.startswith("GIT_") or key in drop:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    env = dict(os.environ)
    env.update({
        "HOME": str(user_home), "CLAUDE_CONFIG_DIR": str(config_dir),
        "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(user_home / ".gitconfig"),
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "CLAUDE_PROTECTED_RUNTIME_FILE": str(tmp_path / "protected-runtime.json"),
    })
    (user_home / ".gitconfig").write_text("")
    return types.SimpleNamespace(tmp=tmp_path, env=env,
                                 runtime_file=tmp_path / "protected-runtime.json")


def make_home(sb, name="H"):
    """A harness home with a copy of the script, the settings load (hooks/lib/claude_home.py),
    the runtime-guard config module and hook stubs."""
    home = sb.tmp / name
    (home / "scripts" / "install").mkdir(parents=True)
    target = home / "scripts" / "install" / "render-settings"
    shutil.copyfile(SCRIPT, target)
    target.chmod(0o755)
    guard = home / "hooks" / "lib" / "runtime_guard"
    guard.mkdir(parents=True)
    for module in ("config.py", "shell_lex.py", "pathmatch.py"):
        shutil.copyfile(RUNTIME_GUARD / module, guard / module)
    shutil.copyfile(REPO / "hooks" / "lib" / "claude_home.py", guard.parent / "claude_home.py")
    for rel in HOOK_FILES:
        (home / rel).write_text("# stub\n")
    return Path(os.path.realpath(home))


def run_tool(sb, home, *args, data=None):
    return subprocess.run([sys.executable, str(home / "scripts" / "install" / "render-settings"),
                           *args], cwd=str(home), env=sb.env, input=data, capture_output=True,
                          timeout=120)


def git(sb, home, *args, check=True):
    proc = subprocess.run(["git", "-C", str(home), *args], env=sb.env, capture_output=True,
                          timeout=120)
    if check:
        assert proc.returncode == 0, proc.stderr.decode()
    return proc


def register_filter(sb, home):
    tool = "%s scripts/install/render-settings" % shlex.quote(sys.executable)
    git(sb, home, "config", "filter.claude-settings.clean", tool + " clean")
    git(sb, home, "config", "filter.claude-settings.smudge", tool + " smudge")
    git(sb, home, "config", "filter.claude-settings.required", "true")


def init_repo(sb, home, settings_bytes, register=False):
    git(sb, home, "init", "-q")
    (home / ".gitignore").write_text("/settings.machine.json\n")
    (home / ".gitattributes").write_text("/settings.json filter=claude-settings\n")
    if register:
        register_filter(sb, home)
    (home / "settings.json").write_bytes(settings_bytes)
    git(sb, home, "add", "-A")
    git(sb, home, "commit", "-q", "-m", "init")


def write_overlay(home, obj):
    (home / "settings.machine.json").write_bytes(canon(obj))


def status(sb, home):
    return git(sb, home, "status", "--porcelain").stdout.decode()


def required_keys():
    tree = ast.parse((RUNTIME_GUARD / "config.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "REQUIRED_KEYS"
                                                for t in node.targets):
            return list(ast.literal_eval(node.value))
    raise AssertionError("REQUIRED_KEYS not found")


def load_tool(sb):
    """Import a copy of the script (outside the repository) for in-process property tests."""
    home = make_home(sb, "imported")
    path = str(home / "scripts" / "install" / "render-settings")
    sys.dont_write_bytecode = True
    loader = importlib.machinery.SourceFileLoader("render_settings_under_test", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


# ------------------------------------------------------------------------- clean and smudge

def test_round_trip_and_idempotence(sb):
    home = make_home(sb)
    base = canon(clean_form())
    init_repo(sb, home, base)
    write_overlay(home, overlay_doc(home, "demo-overlay-value-1"))

    smudge = run_tool(sb, home, "smudge", data=base)
    assert smudge.returncode == 0, smudge.stderr
    machine = smudge.stdout
    doc = json.loads(machine)
    want = clean_form()
    # env: the existing key is overridden in place, new keys are appended.
    assert list(doc["env"]) == list(want["env"]) + ["CLAUDE_HOME", "DEMO_FLAG"]
    assert doc["env"]["TMPDIR"] == "/opt/demo/demo-overlay-value-1"
    assert doc["env"]["CLAUDE_HOME"] == str(home)
    # permissions: module entries (modules first), then the overlay's.
    assert doc["permissions"]["allow"] == want["permissions"]["allow"] + [
        "mcp__paseo__*", "Bash(node scripts/paseo-usage-read.mjs:*)",
        "Bash(/opt/demo/bin/helper:*)"]
    assert doc["permissions"]["deny"] == want["permissions"]["deny"] + ["Bash(demo-danger:*)"]
    assert doc["permissions"]["ask"] == []
    # CLI-owned key from the overlay; meta keys never rendered.
    assert doc["model"] == "demo-model-x"
    assert "modules" not in doc and "_comment" not in doc
    # paseo module: matcher alternative merged into the existing group, group appended.
    assert doc["hooks"]["PreToolUse"][1]["matcher"] == RUNCODE + "|" + PASEO_RUNCODE
    assert doc["hooks"]["PostToolUse"][0]["matcher"] == RUNCODE + "|" + PASEO_RUNCODE
    assert len(doc["hooks"]["PreToolUse"]) == 2 and len(doc["hooks"]["PostToolUse"]) == 1
    assert doc["hooks"]["UserPromptSubmit"] == want["hooks"]["UserPromptSubmit"] + [
        {"hooks": [hook("python3", "hooks/userprompt-usage-snapshot.py", timeout=10)]}]

    def clean(data):
        proc = run_tool(sb, home, "clean", data=data)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout

    def smudge_(data):
        proc = run_tool(sb, home, "smudge", data=data)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout

    assert clean(machine) == base                      # clean(smudge(B)) == B
    assert smudge_(machine) == machine                 # smudge(smudge(B)) == smudge(B)
    assert clean(base) == base
    assert clean(clean(machine)) == clean(machine)
    # Non-canonical formatting is canonicalised.
    assert clean(json.dumps(clean_form(), indent=4).encode()) == base
    # A hand edit survives clean (it is a real change); overlay values and CLI keys do not.
    edited = json.loads(machine)
    edited["permissions"]["allow"].append("Bash(demo-user-tool:*)")
    edited["theme"] = "dark"
    once = clean(canon(edited))
    assert json.loads(once)["permissions"]["allow"] == want["permissions"]["allow"] + [
        "Bash(demo-user-tool:*)"]
    assert b"demo-overlay-value-1" not in once and b"theme" not in once
    assert b"demo-model-x" not in once and str(home).encode() not in once
    assert clean(once) == once


def test_clean_strips_cli_owned_keys_without_overlay(sb):
    home = make_home(sb)
    base = canon(clean_form())
    init_repo(sb, home, base)
    assert not (home / "settings.machine.json").exists()
    with_cli = clean_form()
    with_cli.update({"model": "demo-model", "alwaysThinkingEnabled": True, "effortLevel": "high",
                     "tui": "default", "theme": "dark", "autoCompactEnabled": False,
                     "modelSettings": {"demo": 1}, "fastMode": True, "advisorModel": "demo-adv"})
    proc = run_tool(sb, home, "clean", data=canon(with_cli))
    assert proc.returncode == 0 and proc.stdout == base
    proc = run_tool(sb, home, "smudge", data=base)
    assert proc.returncode == 0 and proc.stdout == base
    # Outside a git checkout the base is empty and the keys are removed as well.
    loose = make_home(sb, "loose")
    proc = run_tool(sb, loose, "clean", data=canon(with_cli))
    assert proc.returncode == 0 and proc.stdout == base



def test_check_staged_refuses_committed_machine_keys_without_overlay(sb):
    """The CI backstop: no overlay, base == HEAD, yet a committed CLI-owned key or the
    machine-only env.CLAUDE_HOME is still refused (they are never part of the clean form)."""
    for extra in ({"model": "demo-model"}, {"env": {"CLAUDE_HOME": "/opt/demo/claude-harness"}}):
        home = make_home(sb, "committed-%s" % next(iter(extra)))
        doc = clean_form()
        for key, value in extra.items():
            doc[key] = dict(doc.get(key, {}), **value) if isinstance(value, dict) else value
        init_repo(sb, home, canon(doc))
        proc = run_tool(sb, home, "check", "--staged")
        assert proc.returncode == 1, (extra, proc.stdout, proc.stderr)
    clean_home = make_home(sb, "committed-clean")
    init_repo(sb, clean_home, canon(clean_form()))
    assert run_tool(sb, clean_home, "check", "--staged").returncode == 0

@pytest.mark.parametrize("overlay_bytes, needle", [
    (b"{not json", "not a valid JSON object"),
    (b"[1, 2]\n", "not a valid JSON object"),
    (canon({"modules": {"demo-unknown-module": True}}), "unknown module"),
    (canon({"env": {"DEMO_KEY": 424242}}), "env.DEMO_KEY must be a string"),
    (canon({"modules": {"paseo": "yes"}}), "modules.paseo must be true or false"),
])
def test_invalid_overlay_fails_clean_and_smudge_passes_through(sb, overlay_bytes, needle):
    home = make_home(sb)
    base = canon(clean_form())
    init_repo(sb, home, base)
    (home / "settings.machine.json").write_bytes(overlay_bytes)
    machine = canon(dict(clean_form(), model="demo-model"))
    proc = run_tool(sb, home, "clean", data=machine)
    assert proc.returncode == 1
    assert proc.stdout == b""
    err = proc.stderr.decode()
    assert "settings.machine.json" in err and needle in err and "424242" not in err
    proc = run_tool(sb, home, "smudge", data=base)
    assert proc.returncode == 0 and proc.stdout == base
    assert "settings.machine.json" in proc.stderr.decode()


def test_invalid_input_clean_refuses_and_smudge_passes_through(sb):
    """clean is a required filter: input it cannot clean is refused (exit 1, no output), never
    passed through, because unchanged input may carry machine values. smudge stays fail safe."""
    home = make_home(sb)
    init_repo(sb, home, canon(clean_form()))
    write_overlay(home, overlay_doc(home, "demo-overlay-value-1"))
    machine = run_tool(sb, home, "smudge", data=canon(clean_form())).stdout
    assert b"demo-overlay-value-1" in machine
    cases = [(b"{broken", "is not a JSON object this filter can parse"),
             (b"[]\n", "is not a JSON object this filter can parse"),
             (canon({"env": ["not", "an", "object"]}), "unexpected structure at env"),
             (b"\xef\xbb\xbf" + machine, "starts with a UTF-8 byte order mark")]
    for data, needle in cases:
        proc = run_tool(sb, home, "clean", data=data)
        err = proc.stderr.decode()
        assert proc.returncode == 1 and proc.stdout == b"", (data[:12], err)
        assert "clean refused: settings.json" in err and needle in err, err
        assert "demo-overlay-value-1" not in err and "/opt/demo" not in err
        proc = run_tool(sb, home, "smudge", data=data)
        assert proc.returncode == 0 and proc.stdout == data, data[:12]
        assert "unchanged" in proc.stderr.decode()


def test_git_refuses_to_stage_a_bom_prefixed_machine_form(sb):
    """With the filter registered, a byte order mark in front of the machine form makes git add
    fail (the filter is required) instead of staging the overlay values; once it is removed, the
    clean form is staged again."""
    home = make_home(sb)
    base = canon(clean_form())
    init_repo(sb, home, base, register=True)
    write_overlay(home, overlay_doc(home, "demo-overlay-value-1"))
    assert run_tool(sb, home, "render").returncode == 0
    machine = (home / "settings.json").read_bytes()
    (home / "settings.json").write_bytes(b"\xef\xbb\xbf" + machine)
    proc = git(sb, home, "add", "settings.json", check=False)
    err = proc.stderr.decode()
    assert proc.returncode != 0 and "byte order mark" in err, err
    assert "demo-overlay-value-1" not in err and "demo-model-x" not in err
    assert git(sb, home, "cat-file", "blob", ":settings.json").stdout == base
    (home / "settings.json").write_bytes(machine)
    os.utime(home / "settings.json", (3, 3))
    git(sb, home, "add", "settings.json")
    assert git(sb, home, "cat-file", "blob", ":settings.json").stdout == base
    assert status(sb, home) == ""


# ------------------------------------------------------------------------ git integration

def test_git_filter_render_keeps_index_clean(sb):
    home = make_home(sb)
    base = canon(clean_form())
    init_repo(sb, home, base, register=True)
    write_overlay(home, overlay_doc(home, "demo-overlay-value-1"))

    proc = run_tool(sb, home, "render")
    assert proc.returncode == 0, proc.stderr
    assert "rendered" in proc.stdout.decode()
    working = (home / "settings.json").read_bytes()
    assert working != base and b"demo-overlay-value-1" in working
    assert status(sb, home) == ""
    assert git(sb, home, "diff", "--exit-code", check=False).returncode == 0
    assert git(sb, home, "cat-file", "blob", ":settings.json").stdout == base

    # Change an overlay value and re-render: still no diff, the index never sees the value.
    write_overlay(home, overlay_doc(home, "demo-overlay-value-2"))
    proc = run_tool(sb, home, "render")
    assert proc.returncode == 0, proc.stderr
    working = (home / "settings.json").read_bytes()
    assert b"demo-overlay-value-2" in working and b"demo-overlay-value-1" not in working
    assert status(sb, home) == ""
    assert git(sb, home, "diff", "--exit-code", check=False).returncode == 0
    os.utime(home / "settings.json", (1, 1))  # force git to re-read (and clean) the file
    git(sb, home, "add", "settings.json")
    staged = git(sb, home, "cat-file", "blob", ":settings.json").stdout
    assert staged == base
    for value in (b"demo-overlay-value", b"demo-model-x", b"/opt/demo", str(home).encode()):
        assert value not in staged
    assert run_tool(sb, home, "check", "--staged").returncode == 0

    # A second render is a no-op; a git checkout smudges to the same machine form.
    proc = run_tool(sb, home, "render")
    assert proc.returncode == 0 and "already up to date" in proc.stdout.decode()
    rendered = (home / "settings.json").read_bytes()
    (home / "settings.json").unlink()
    git(sb, home, "checkout", "--", "settings.json")
    assert (home / "settings.json").read_bytes() == rendered
    assert status(sb, home) == ""

    # Doctor: all checks pass once the protected-runtime file is complete.
    sb.runtime_file.write_text(json.dumps(dict({"schema_version": 1},
                                               **{k: [] for k in required_keys()})))
    proc = run_tool(sb, home, "check")
    out = proc.stdout.decode()
    assert proc.returncode == 0, out + proc.stderr.decode()
    assert "[ ok ] hook paths: 7 commands, missing=0" in out
    assert "[ ok ] settings filter: registered, required, exact round trip" in out
    assert "[ ok ] protected-runtime file: valid" in out

    # Fail closed: an invalid overlay makes git refuse to stage; checkout still yields a file.
    (home / "settings.machine.json").write_text("{broken")
    os.utime(home / "settings.json", (2, 2))
    assert git(sb, home, "add", "settings.json", check=False).returncode != 0
    (home / "settings.json").unlink()
    git(sb, home, "checkout", "--", "settings.json")
    assert (home / "settings.json").read_bytes() == base


def test_check_staged_refuses_machine_form_without_filter(sb):
    home = make_home(sb)
    base = canon(clean_form())
    init_repo(sb, home, base, register=True)
    write_overlay(home, overlay_doc(home, "demo-overlay-value-1"))
    assert run_tool(sb, home, "render").returncode == 0
    assert status(sb, home) == ""

    git(sb, home, "config", "--remove-section", "filter.claude-settings")
    git(sb, home, "rm", "-q", "--cached", "settings.json")
    git(sb, home, "add", "settings.json")
    assert b"demo-overlay-value-1" in git(sb, home, "cat-file", "blob", ":settings.json").stdout
    proc = run_tool(sb, home, "check", "--staged")
    assert proc.returncode == 1
    out = (proc.stdout + proc.stderr).decode()
    assert "staged in machine form" in out and "scripts/bootstrap" in out
    assert "demo-overlay-value-1" not in out and "demo-model-x" not in out
    proc = run_tool(sb, home, "check")
    assert proc.returncode == 1
    assert "filter.claude-settings.clean is not set" in proc.stdout.decode()

    # A canonical clean form passes; a non-canonical one is refused.
    (home / "settings.json").write_bytes(json.dumps(clean_form(), indent=4).encode())
    git(sb, home, "add", "settings.json")
    assert run_tool(sb, home, "check", "--staged").returncode == 1
    register_filter(sb, home)
    git(sb, home, "rm", "-q", "--cached", "--force", "settings.json")  # index only
    git(sb, home, "add", "settings.json")
    assert git(sb, home, "cat-file", "blob", ":settings.json").stdout == base
    assert run_tool(sb, home, "check", "--staged").returncode == 0


def test_render_refuses_extras_without_force(sb):
    home = make_home(sb)
    init_repo(sb, home, canon(clean_form()), register=True)
    write_overlay(home, overlay_doc(home, "demo-overlay-value-1"))
    assert run_tool(sb, home, "render").returncode == 0
    machine = (home / "settings.json").read_bytes()

    edited = json.loads(machine)
    edited["permissions"]["allow"].append("Bash(demo-extra-tool:*)")
    edited["env"]["DEMO_EXTRA_KEY"] = "demo-secret-value-9"
    edited["env"]["TMPDIR"] = "/opt/demo/stale-overlay-value"   # overlay-owned: not an extra
    edited["theme"] = "dark"                                     # CLI-owned: carried over
    (home / "settings.json").write_bytes(canon(edited))
    before = (home / "settings.json").read_bytes()
    proc = run_tool(sb, home, "render")
    assert proc.returncode == 1
    err = proc.stderr.decode()
    # Key paths and counts only: never the entry text or an env value.
    assert "extra in settings.json: permissions.allow: 1 entry" in err
    assert "extra in settings.json: env.DEMO_EXTRA_KEY" in err
    assert "move it into settings.machine.json to keep it" in err
    assert "TMPDIR" not in err and "theme" not in err and "demo-extra-tool" not in err
    assert "demo-secret-value-9" not in err and "stale-overlay-value" not in err
    assert (home / "settings.json").read_bytes() == before

    proc = run_tool(sb, home, "render", "--force")
    assert proc.returncode == 0, proc.stderr
    result = json.loads((home / "settings.json").read_bytes())
    assert result["theme"] == "dark"
    del result["theme"]
    assert canon(result) == machine
    assert status(sb, home) == ""


def test_check_reports_missing_hooks_and_protected_runtime(sb):
    home = make_home(sb)  # not a git checkout: render uses the working file as the clean form
    (home / "settings.json").write_bytes(canon(clean_form()))
    write_overlay(home, {"env": {"CLAUDE_HOME": str(home)}})
    assert run_tool(sb, home, "render").returncode == 0
    (home / "hooks" / "stop-demo.py").unlink()

    proc = run_tool(sb, home, "check")
    out = proc.stdout.decode()
    assert proc.returncode == 1
    assert "[FAIL] hook paths: 6 commands, missing=1" in out
    assert "hooks/stop-demo.py" in out
    assert "[ ok ] settings filter: not a git checkout: no settings filter to check" in out
    assert ("[FAIL] protected-runtime file: missing or incomplete at "
            "$CLAUDE_PROTECTED_RUNTIME_FILE") in out
    assert str(home) not in out and str(sb.runtime_file) not in out

    sb.runtime_file.write_text(json.dumps({"schema_version": 1, "protected_cmds": []}))
    proc = run_tool(sb, home, "check")
    assert proc.returncode == 1 and "[FAIL] protected-runtime file" in proc.stdout.decode()

    (home / "hooks" / "stop-demo.py").write_text("# stub\n")
    sb.runtime_file.write_text(json.dumps(dict({"schema_version": 1},
                                               **{k: [] for k in required_keys()})))
    proc = run_tool(sb, home, "check")
    out = proc.stdout.decode()
    assert proc.returncode == 0, out
    assert "[ ok ] hook paths: 6 commands, missing=0" in out
    assert "[ ok ] protected-runtime file: valid" in out

    # A hook path that resolves outside the harness home fails (here: CLAUDE_HOME elsewhere).
    write_overlay(home, {"env": {"CLAUDE_HOME": str(sb.tmp / "elsewhere")}})
    assert run_tool(sb, home, "render", "--force").returncode == 0
    proc = run_tool(sb, home, "check")
    out = proc.stdout.decode()
    assert proc.returncode == 1 and "missing=6" in out
    assert "outside the harness home: %s/hooks/stop-demo.py" % CHANNEL in out
    assert str(sb.tmp / "elsewhere") not in out


def test_render_and_check_take_the_settings_load_verdict(sb):
    """render and check read settings.json through the one load of a settings file
    (hooks/lib/claude_home.py load_settings): an unusable file is refused with the load's reason,
    named relative to the home; a missing one is reported missing."""
    home = make_home(sb)  # not a git checkout: render uses the working file as the clean form
    (home / "settings.json").write_bytes(canon(clean_form()))
    write_overlay(home, {"env": {"CLAUDE_HOME": str(home)}})
    assert run_tool(sb, home, "render").returncode == 0
    size = (home / "settings.json").stat().st_size
    for data, reason in ((b"{" * size, "settings.json: not valid JSON ("),
                         (canon({"permissions": {"allow": "Bash"}}),
                          "settings.json: permissions.allow is not a list of strings")):
        (home / "settings.json").write_bytes(data)
        proc = run_tool(sb, home, "render")
        assert proc.returncode == 1 and (home / "settings.json").read_bytes() == data
        assert "render refused: %s" % reason in proc.stderr.decode()
        proc = run_tool(sb, home, "check")
        out = proc.stdout.decode()
        assert proc.returncode == 1 and "[FAIL] hook paths: %s" % reason in out, out
        assert str(home) not in out
    (home / "settings.json").unlink()
    proc = run_tool(sb, home, "check")
    out = proc.stdout.decode()
    assert proc.returncode == 1, out
    assert "[FAIL] hook paths: settings.json is missing; run scripts/bootstrap" in out


# ------------------------------------------------- stale or missing overlay (review item 1, R2)

STAND_IN = "acct-test-123"  # every personal value below contains it
PERSONAL_ALLOW = "Bash(/home/%s/bin/sync.sh:*)" % STAND_IN
PERSONAL_HOOK = "hooks/personal-%s.sh" % STAND_IN  # an untracked, excluded stub
PUBLIC_DENY = "Bash(demo-public-deny:*)"


def personal_overlay(home):
    """An overlay with a stand-in personal allow entry, env value and hook group."""
    return {"modules": {"paseo": False},
            "env": {"CLAUDE_HOME": str(home), "DEMO_ACCOUNT": STAND_IN},
            "permissions": {"allow": [PERSONAL_ALLOW]},
            "hooks": {"Notification": [{"matcher": "idle_prompt",
                                        "hooks": [hook("bash", PERSONAL_HOOK)]}]}}


def rendered_home(sb, name="H"):
    """A checkout with the filter registered and the personal overlay rendered (init's state)."""
    home = make_home(sb, name)
    init_repo(sb, home, canon(clean_form()), register=True)
    (home / PERSONAL_HOOK).write_text("# stub\n")
    (home / ".git" / "info").mkdir(exist_ok=True)
    with open(home / ".git" / "info" / "exclude", "a") as fh:
        fh.write("/%s\n" % PERSONAL_HOOK)
    write_overlay(home, personal_overlay(home))
    proc = run_tool(sb, home, "render")
    assert proc.returncode == 0, proc.stderr
    assert STAND_IN.encode() in (home / "settings.json").read_bytes()
    assert status(sb, home) == ""
    return home


def assert_never_committed(sb, home):
    assert git(sb, home, "grep", "-q", STAND_IN, "HEAD", check=False).returncode == 1
    assert STAND_IN.encode() not in git(sb, home, "log", "-p", "--all").stdout


def stage_unfiltered(sb, home, entry):
    """Stage, bypassing the filter, the clean form plus one recorded allow entry: no CLI-owned
    key and no CLAUDE_HOME, so nothing structural gives the value away."""
    doc = clean_form()
    doc["permissions"]["allow"].append(entry)
    path = sb.tmp / "unfiltered.json"
    path.write_bytes(canon(doc))
    oid = git(sb, home, "hash-object", "-w", "--no-filters", str(path)).stdout.decode().strip()
    git(sb, home, "update-index", "--cacheinfo", "100644,%s,settings.json" % oid)


def assert_check_staged_refuses(sb, home, entry=PERSONAL_ALLOW):
    """The pre-commit hook's and CI's check refuses a stage that carries a recorded value."""
    stage_unfiltered(sb, home, entry)
    proc = run_tool(sb, home, "check", "--staged")
    assert proc.returncode == 1 and "staged in machine form" in proc.stderr.decode()
    assert STAND_IN not in (proc.stdout + proc.stderr).decode()
    git(sb, home, "reset", "-q", "--", "settings.json")


def test_entry_dropped_from_overlay_without_render_never_reaches_a_commit(sb):
    """1a: the stale working file still carries the values the overlay no longer lists; a plain
    commit of all changes (here together with a public edit) lands the edit and none of them."""
    home = rendered_home(sb)
    overlay = personal_overlay(home)
    overlay["permissions"]["allow"].remove(PERSONAL_ALLOW)
    del overlay["env"]["DEMO_ACCOUNT"], overlay["hooks"]
    write_overlay(home, overlay)
    os.utime(home / "settings.json", (3, 3))  # a CLI write re-stats the file
    assert status(sb, home) == ""
    assert git(sb, home, "diff").stdout == b""
    assert_check_staged_refuses(sb, home)

    doc = json.loads((home / "settings.json").read_bytes())
    assert PERSONAL_ALLOW in doc["permissions"]["allow"]  # still stale: no re-render
    doc["permissions"]["deny"].append(PUBLIC_DENY)
    (home / "settings.json").write_bytes(canon(doc))
    git(sb, home, "commit", "-q", "-am", "plain commit")
    want = clean_form()
    want["permissions"]["deny"].append(PUBLIC_DENY)
    assert git(sb, home, "cat-file", "blob", "HEAD:settings.json").stdout == canon(want)
    assert_never_committed(sb, home)
    assert run_tool(sb, home, "check", "--staged").returncode == 0


def test_deleted_overlay_never_leaks_into_a_commit(sb):
    """1b: the overlay is deleted without a re-render; the record still strips its values."""
    home = rendered_home(sb)
    (home / "settings.machine.json").unlink()
    os.utime(home / "settings.json", (3, 3))
    assert status(sb, home) == ""
    assert_check_staged_refuses(sb, home)
    (home / "hooks" / "stop-demo.py").write_text("# stub, edited\n")
    git(sb, home, "commit", "-q", "-am", "plain commit")
    assert git(sb, home, "cat-file", "blob", "HEAD:settings.json").stdout == canon(clean_form())
    assert_never_committed(sb, home)
    assert run_tool(sb, home, "check", "--staged").returncode == 0


def test_public_edit_lands_without_opt_in(sb):
    """1c: a hand-added deny entry lands in clean form with a plain commit; nothing to opt in."""
    home = rendered_home(sb)
    doc = json.loads((home / "settings.json").read_bytes())
    doc["permissions"]["deny"].append(PUBLIC_DENY)
    (home / "settings.json").write_bytes(canon(doc))
    assert status(sb, home) == " M settings.json\n"
    git(sb, home, "commit", "-q", "-am", "public edit")
    want = clean_form()
    want["permissions"]["deny"].append(PUBLIC_DENY)
    assert git(sb, home, "cat-file", "blob", "HEAD:settings.json").stdout == canon(want)
    assert_never_committed(sb, home)
    assert status(sb, home) == ""
    assert run_tool(sb, home, "check", "--staged").returncode == 0
    sb.runtime_file.write_text(json.dumps(dict({"schema_version": 1},
                                               **{k: [] for k in required_keys()})))
    proc = run_tool(sb, home, "check")
    assert proc.returncode == 0, proc.stdout.decode()


def test_smudge_records_what_it_applies(sb):
    """An overlay value that reached the working file through a checkout (smudge), not a render,
    is recorded too."""
    home = rendered_home(sb)
    extra = "Bash(/home/%s/bin/other.sh:*)" % STAND_IN
    overlay = personal_overlay(home)
    overlay["permissions"]["allow"].append(extra)
    write_overlay(home, overlay)
    (home / "settings.json").unlink()
    git(sb, home, "checkout", "--", "settings.json")
    assert extra.encode() in (home / "settings.json").read_bytes()
    write_overlay(home, {"env": {"CLAUDE_HOME": str(home)}})
    os.utime(home / "settings.json", (3, 3))
    assert status(sb, home) == ""
    assert_check_staged_refuses(sb, home, extra)


def test_record_is_private_and_fails_closed(sb):
    home = rendered_home(sb)
    record = home / ".git" / "claude-settings.applied"
    assert stat.S_IMODE(record.stat().st_mode) == 0o600
    assert STAND_IN.encode() in record.read_bytes()  # hence owner-only, inside the git directory
    assert b"claude-settings.applied" not in git(sb, home, "ls-files", "--others").stdout
    sb.runtime_file.write_text(json.dumps(dict({"schema_version": 1},
                                               **{k: [] for k in required_keys()})))

    # No record while an overlay exists: doctor fails until a render writes one.
    record.unlink()
    proc = run_tool(sb, home, "check")
    assert proc.returncode == 1 and "no record of what render applied" in proc.stdout.decode()
    assert run_tool(sb, home, "render").returncode == 0
    assert run_tool(sb, home, "check").returncode == 0

    # An unusable record: clean and check --staged fail closed, render needs --force to rewrite.
    record.write_text("{broken")
    machine = (home / "settings.json").read_bytes()
    proc = run_tool(sb, home, "clean", data=machine)
    assert proc.returncode == 1 and proc.stdout == b""
    err = proc.stderr.decode()
    assert "the record .git/claude-settings.applied is not valid" in err and str(home) not in err
    assert run_tool(sb, home, "check", "--staged").returncode == 1  # the index is clean
    proc = run_tool(sb, home, "render")
    assert proc.returncode == 1 and "render --force" in proc.stderr.decode()
    assert run_tool(sb, home, "render", "--force").returncode == 0
    assert json.loads(record.read_bytes())["layers"]
    assert status(sb, home) == ""
    assert run_tool(sb, home, "check", "--staged").returncode == 0

    # A render keeps the old record while the index still carries a recorded value (staged
    # without the filter), so check --staged goes on refusing it.
    stage_unfiltered(sb, home, PERSONAL_ALLOW)
    write_overlay(home, {"env": {"CLAUDE_HOME": str(home)}})
    assert run_tool(sb, home, "render").returncode == 0
    assert run_tool(sb, home, "check", "--staged").returncode == 1


# ------------------------------------------------------- personal files never reach a commit

PERSONAL_FILES = ("settings.machine.json", "private-literals.txt")
PRE_COMMIT = "hooks/git-hooks/pre-commit"
PRE_COMMIT_RUNS = ("hooks/pre-commit-check.sh", "scripts/check-public-core.sh")


def install_pre_commit(home):
    target = home / ".git" / "hooks" / "pre-commit"
    target.parent.mkdir(exist_ok=True)
    shutil.copyfile(home / PRE_COMMIT, target)
    target.chmod(0o755)
    return target


def hooked_home(sb):
    """rendered_home with the tracked pre-commit hook (and the scripts it runs) installed as init
    installs it, and an untracked private-literal list holding the stand-in literal."""
    home = rendered_home(sb)
    for rel in (PRE_COMMIT, *PRE_COMMIT_RUNS):
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, home / rel)
    git(sb, home, "add", PRE_COMMIT, *PRE_COMMIT_RUNS)
    git(sb, home, "commit", "-q", "-m", "the pre-commit hook and the scripts it runs")
    with open(home / ".git" / "info" / "exclude", "a") as fh:
        fh.write("/private-literals.txt\n")
    (home / "private-literals.txt").write_text("# stand-in list\n%s\n" % STAND_IN)
    install_pre_commit(home)
    assert status(sb, home) == ""
    return home


def assert_names_only(rel, proc, home):
    """A refusal names the path and how to untrack it, never the file's content."""
    out = (proc.stdout + proc.stderr).decode()
    assert proc.returncode != 0, out
    assert "%s is in the index" % rel in out and "git rm --cached -- %s" % rel in out, out
    assert STAND_IN not in out and str(home) not in out, out


@pytest.mark.parametrize("rel", PERSONAL_FILES)
def test_pre_commit_refuses_a_personal_file_in_the_index(sb, rel):
    """Whatever .gitignore says, the hook refuses a commit whose index holds the overlay or the
    private-literal list: newly force-added, tracked and unchanged, or tracked and modified. The
    commit that untracks it (git rm --cached) passes, and so do ordinary commits after it."""
    home = hooked_home(sb)
    path, edited = home / rel, home / "hooks" / "stop-demo.py"

    def refused():
        head = git(sb, home, "rev-parse", "HEAD").stdout
        proc = git(sb, home, "commit", "-q", "-m", "attempt", check=False)
        assert_names_only(rel, proc, home)
        assert "REFUSED by the settings check" in proc.stderr.decode()
        assert git(sb, home, "rev-parse", "HEAD").stdout == head

    git(sb, home, "add", "-f", "--", rel)
    refused()
    git(sb, home, "reset", "-q", "--", rel)

    # An earlier commit made where the hook was not installed (before init, or with a version
    # that did not check this) tracks the file.
    (home / ".git" / "hooks" / "pre-commit").unlink()
    git(sb, home, "add", "-f", "--", rel)
    git(sb, home, "commit", "-q", "-m", "earlier commit")
    install_pre_commit(home)
    assert git(sb, home, "cat-file", "-e", "HEAD:" + rel, check=False).returncode == 0

    edited.write_text("# stub, edited\n")  # tracked and unchanged: an unrelated change
    git(sb, home, "add", "--", "hooks/stop-demo.py")
    refused()
    with open(path, "ab") as fh:  # tracked and modified
        fh.write(b"\n" if rel == "settings.machine.json" else b"# another comment\n")
    git(sb, home, "add", "--", rel)
    refused()

    git(sb, home, "rm", "-q", "--cached", "--", rel)
    git(sb, home, "commit", "-q", "-m", "untrack " + rel)
    assert git(sb, home, "cat-file", "-e", "HEAD:" + rel, check=False).returncode != 0
    assert path.exists() and status(sb, home) == ""
    edited.write_text("# stub, edited again\n")
    git(sb, home, "commit", "-q", "-am", "ordinary commit")
    assert run_tool(sb, home, "check", "--staged").returncode == 0


def test_ci_check_on_a_fresh_checkout_refuses_a_tracked_personal_file(sb):
    """CI runs check --staged on a fresh checkout (no overlay, no filter, no hook): it passes on
    a tree that tracks neither personal file and fails, naming only the path, on one that tracks
    either; once a commit untracks it, a fresh checkout passes again."""
    origin = make_home(sb, "origin")
    init_repo(sb, origin, canon(clean_form()))

    def ci_check(name):
        checkout = sb.tmp / ("ci-" + name)
        git(sb, sb.tmp, "clone", "-q", str(origin), str(checkout))
        return run_tool(sb, checkout, "check", "--staged")

    assert ci_check("clean").returncode == 0
    contents = {"settings.machine.json": canon(personal_overlay(origin)),
                "private-literals.txt": ("# stand-in list\n%s\n" % STAND_IN).encode()}
    for rel, data in contents.items():
        (origin / rel).write_bytes(data)
        git(sb, origin, "add", "-f", "--", rel)
        git(sb, origin, "commit", "-q", "-m", "track " + rel)
        proc = ci_check("tracks-" + rel)
        assert_names_only(rel, proc, origin)  # the overlay holds the origin's path
        assert "staged in machine form" not in proc.stderr.decode()  # settings.json is clean
        git(sb, origin, "rm", "-q", "--cached", "--", rel)
        git(sb, origin, "commit", "-q", "-m", "untrack " + rel)
        assert ci_check("untracked-" + rel).returncode == 0
    for rel in contents:  # both at once: both named
        git(sb, origin, "add", "-f", "--", rel)
    git(sb, origin, "commit", "-q", "-m", "track both")
    proc = ci_check("tracks-both")
    for rel in contents:
        assert_names_only(rel, proc, origin)


def add_doctor(sb, home):
    """scripts/doctor, its resolver and a venv stub (outside the checkout) for a test home."""
    for rel in ("scripts/doctor", "hooks/lib/claude_home.sh", "hooks/lib/claude_home.py"):
        shutil.copyfile(REPO / rel, home / rel)
        (home / rel).chmod(0o755)
    (home / "policies").mkdir()
    venv = sb.tmp / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text('#!/bin/sh\nexec %s "$@"\n' % shlex.quote(sys.executable))
    (venv / "bin" / "python").chmod(0o755)
    sb.runtime_file.write_text(json.dumps(dict({"schema_version": 1},
                                               **{k: [] for k in required_keys()})))
    return lambda: subprocess.run(["bash", str(home / "scripts" / "doctor"), "--venv", str(venv)],
                                  cwd=str(sb.tmp), env=sb.env, capture_output=True, timeout=120)


def test_doctor_fails_on_entries_nothing_explains(sb):
    """Doctor fails (a required check) on working-file entries that neither the clean form, the
    enabled modules nor the overlay explain, naming key paths and counts, never values."""
    home = rendered_home(sb)
    doctor = add_doctor(sb, home)
    proc = doctor()
    out = (proc.stdout + proc.stderr).decode()
    assert proc.returncode == 0, out
    assert "[ ok ] settings.json entries: all explained by" in out

    # Stale: the personal values left the overlay, the working file was not re-rendered (and
    # the personal hook's script is gone: its path is not echoed either).
    write_overlay(home, {"env": {"CLAUDE_HOME": str(home)}})
    (home / PERSONAL_HOOK).unlink()
    proc = doctor()
    out = (proc.stdout + proc.stderr).decode()
    assert proc.returncode == 1, out
    assert "[FAIL] hook paths: 7 commands, missing=1" in out
    assert "Notification: a hook outside the clean form" in out
    assert "[FAIL] settings.json entries: some are outside the clean form" in out
    for line in ("env.DEMO_ACCOUNT", "permissions.allow: 1 entry", "hooks.Notification: 1 hook "
                 "command", "public edits meant for the tracked file: stage them (git add "
                 "settings.json)", "machine-specific: move them into settings.machine.json, then "
                 "run scripts/install/render-settings render", "already removed from "
                 "settings.machine.json: render drops them",
                 "render-settings check failed (see above) — fix what each [FAIL] line names, "
                 "then re-run scripts/doctor",
                 "required check(s) FAILED — fix each item above as its line says."):
        assert line in out, line
    for line in ("before the first run", "re-run scripts/bootstrap"):  # first-install advice
        assert line not in out, line
    assert STAND_IN not in out
    # render (no --force) drops what the record shows it applied; doctor passes again.
    proc = run_tool(sb, home, "render")
    assert proc.returncode == 0 and STAND_IN not in (proc.stdout + proc.stderr).decode()
    assert STAND_IN.encode() not in (home / "settings.json").read_bytes()
    assert doctor().returncode == 0

    # A hand edit nobody recorded: doctor and render name it by key path only; staging it as a
    # public edit explains it.
    doc = json.loads((home / "settings.json").read_bytes())
    doc["permissions"]["allow"].append("Bash(demo-local-tool:*)")
    (home / "settings.json").write_bytes(canon(doc))
    proc = doctor()
    out = (proc.stdout + proc.stderr).decode()
    assert proc.returncode == 1 and "permissions.allow: 1 entry" in out
    assert "demo-local-tool" not in out
    proc = run_tool(sb, home, "render")
    err = proc.stderr.decode()
    assert proc.returncode == 1 and "permissions.allow: 1 entry" in err
    assert "demo-local-tool" not in err
    git(sb, home, "add", "settings.json")
    assert doctor().returncode == 0

    # A machine-specific hand edit: moved into the overlay and rendered, it is explained and
    # active, and stays out of the index.
    entry = "Bash(/home/%s/bin/other-tool.sh:*)" % STAND_IN
    doc["permissions"]["allow"].append(entry)
    (home / "settings.json").write_bytes(canon(doc))
    proc = doctor()
    out = (proc.stdout + proc.stderr).decode()
    assert proc.returncode == 1 and "permissions.allow: 1 entry" in out, out
    assert STAND_IN not in out
    doc["permissions"]["allow"].remove(entry)
    (home / "settings.json").write_bytes(canon(doc))
    write_overlay(home, {"env": {"CLAUDE_HOME": str(home)}, "permissions": {"allow": [entry]}})
    proc = run_tool(sb, home, "render")
    assert proc.returncode == 0 and STAND_IN not in (proc.stdout + proc.stderr).decode()
    assert entry in json.loads((home / "settings.json").read_bytes())["permissions"]["allow"]
    proc = doctor()
    assert proc.returncode == 0 and STAND_IN not in (proc.stdout + proc.stderr).decode()
    assert STAND_IN.encode() not in git(sb, home, "show", ":settings.json").stdout


# ---------------------------------------------------------------------------------- migrate

SAFETY_OLD = r"""#!/usr/bin/env bash
# CLAUDE_DEV_CONTAINERS (documented default "comment-is-not-a-default")
DEV_CONTAINERS="${CLAUDE_DEV_CONTAINERS:-demo-web-dev}"
DAEMON_RESTART_GRANT_HELPER="${CLAUDE_DAEMON_RESTART_GRANT_HELPER:-/opt/demo/bin/allow-restart}"
PROTECTED_DAEMON_PREFIX="${CLAUDE_PROTECTED_DAEMON_PREFIX:-demo-daemon}"
PROTECTED_DAEMON_TARGETS="${CLAUDE_PROTECTED_DAEMON_TARGETS:-acct-a|acct-b}"
if echo "$COMMAND" | grep -qE 'session_dirs\.txt'; then
  echo "BLOCKED: session_dirs.txt is PERMANENTLY FORBIDDEN" >&2
  exit 2
fi
if echo "$COMMAND" | grep -qE 'demo-session-recovery'; then
  echo "BLOCKED: demo-session-recovery.sh is PERMANENTLY FORBIDDEN" >&2
  exit 2
fi
if echo "$COMMAND" | grep -qE 'demo-restart-all'; then
  echo "BLOCKED: demo-restart-all.sh is PERMANENTLY FORBIDDEN" >&2
  exit 2
fi
if echo "$COMMAND" | grep -qE 'unrelated-pattern'; then
  echo "BLOCKED: something else" >&2
fi
if echo "$COMMAND" | grep -qE 'docker\s+(stop|restart|rm|kill)\s+.*demo'; then
  exit 2
fi
"""
SAFETY_NEW = r"""#!/usr/bin/env bash
DEV_CONTAINERS="${CLAUDE_DEV_CONTAINERS:-}"
PROTECTED_DAEMON_PREFIX="${CLAUDE_PROTECTED_DAEMON_PREFIX:-}"
HARD_BANNED="${CLAUDE_HARD_BANNED_SCRIPTS:-session-recovery|restart-all-sessions}"
"""
CODE_OLD = {
    "hooks/pretool-bash-safety.sh": SAFETY_OLD,
    "hooks/lib/subagent_restart.py":
        'ACCOUNTS_ROOT = Path(os.environ.get("CLAUDE_RESTART_ACCOUNTS_ROOT", '
        '"/opt/demo/accounts"))\n',
    "scripts/prune-orphaned-workflow-bookmarks.sh":
        'ACCOUNTS_DIR="${WORKFLOW_PRUNE_ACCOUNTS_DIR:-/opt/demo/accounts}"\n'
        'PROJECT_DIRNAME="${WORKFLOW_PRUNE_PROJECT_DIRNAME:--opt-demo-dot-claude}"\n',
    "hooks/lib/checkpoint-core.sh":
        'msg="checkpoint\n\nCo-Authored-By: Claude <noreply@example.invalid>\n'
        'Co-Authored-By: Demo Bot <demo-bot@example.invalid>"\n',
    "scripts/paseo-daemon-ledger.py": 'DEFAULT_ACCOUNTS = ["acct-a", "acct-b"]\n',
    "scripts/paseo-daemon-timers.py": 'SPEC = {\n    "model": "demo-model@acct-a",\n}\n',
}
CODE_NEW = {
    "hooks/pretool-bash-safety.sh": SAFETY_NEW,
    "hooks/lib/subagent_restart.py":
        'ACCOUNTS_ROOT = os.environ.get("CLAUDE_RESTART_ACCOUNTS_ROOT") or None\n',
    "scripts/prune-orphaned-workflow-bookmarks.sh":
        'ACCOUNTS_DIR="${WORKFLOW_PRUNE_ACCOUNTS_DIR:-}"\n',
    "hooks/lib/checkpoint-core.sh":
        'msg="checkpoint\n\nCo-Authored-By: Claude <noreply@example.invalid>"\n',
    "scripts/paseo-daemon-ledger.py": 'DEFAULT_ACCOUNTS = []\n',
    "scripts/paseo-daemon-timers.py": 'SPEC = {"model": MODEL}\n',
}
DERIVED = {
    "CLAUDE_DEV_CONTAINERS": "demo-web-dev",
    "CLAUDE_DAEMON_RESTART_GRANT_HELPER": "/opt/demo/bin/allow-restart",
    "CLAUDE_PROTECTED_DAEMON_PREFIX": "demo-daemon",
    "CLAUDE_PROTECTED_DAEMON_TARGETS": "acct-a|acct-b",
    "CLAUDE_RESTART_ACCOUNTS_ROOT": "/opt/demo/accounts",
    "WORKFLOW_PRUNE_ACCOUNTS_DIR": "/opt/demo/accounts",
    "WORKFLOW_PRUNE_PROJECT_DIRNAME": "-opt-demo-dot-claude",
    "CLAUDE_HARD_BANNED_SCRIPTS": "demo-session-recovery|demo-restart-all",
    "CLAUDE_PROTECTED_PROCESS_FAMILY": "demo",
    "CLAUDE_CHECKPOINT_EXTRA_TRAILER": "Co-Authored-By: Demo Bot <demo-bot@example.invalid>",
    "PASEO_DAEMON_ACCOUNTS": "acct-a,acct-b",
    "PASEO_DAEMON_MODEL": "demo-model@acct-a",
}
NOTIFY_GROUP = {"matcher": "idle_prompt",
                "hooks": [{"type": "command", "command": "/opt/demo/bin/notify-demo"}]}


def previous_settings(paseo=True):
    """The owner's previous personal settings: absolute hook paths (one unquoted), CLI-owned
    keys, a personal env value, personal tool permissions, a personal hook and (optionally) the
    paseo module's entries inline."""
    old = lambda kind, rel, **kw: hook(kind, rel, prefix=OLD_HOME, **kw)  # noqa: E731
    runcode = RUNCODE + ("|" + PASEO_RUNCODE if paseo else "")
    allow = ["Bash(git status:*)", "Bash(%s/scripts/demo-tool.sh:*)" % OLD_HOME,
             "Bash(/opt/demo/bin/helper:*)"]
    if paseo:
        allow += ["mcp__paseo__*", "Bash(node scripts/paseo-usage-read.mjs:*)"]
    prompt = [{"hooks": [old("python3", "hooks/userprompt-demo.py")]}]
    if paseo:
        prompt.append({"hooks": [old("python3", "hooks/userprompt-usage-snapshot.py", timeout=10)]})
    return {
        "cleanupPeriodDays": 30,
        "env": {"GIT_AUTO_PUSH": "0", "LANG": "C.UTF-8", "TMPDIR": "/var/tmp/claude-scratch",
                "DEMO_BIN": "/opt/demo/bin/demo-tool"},
        "includeCoAuthoredBy": True,
        "permissions": {"allow": allow, "deny": ["Bash(rm -rf /:*)"], "ask": []},
        "model": "demo-model-x",
        "deniedMcpServers": [],
        "hooks": {
            "SessionStart": [{"hooks": [old("bash", "hooks/session-info.sh")]}],
            "UserPromptSubmit": prompt,
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [old("bash", "hooks/pretool-bash-safety.sh",
                                                  quoted=False)]},
                {"matcher": runcode,
                 "hooks": [old("python3", "hooks/pretool-runcode-watchdog.py")]},
            ],
            "PostToolUse": [
                {"matcher": runcode,
                 "hooks": [old("python3", "hooks/posttool-runcode-watchdog.py")]},
            ],
            "Stop": [{"hooks": [old("python3", "hooks/stop-demo.py")]}],
            "Notification": [NOTIFY_GROUP],
        },
        "theme": "dark",
        "effortLevel": "high",
    }


def migration_repo(sb, prev):
    """Commit 1 = the previous revision (personal settings, code defaults); commit 2 = the new
    tree (clean form, empty defaults). Returns (home, previous revision id)."""
    home = make_home(sb)
    git(sb, home, "init", "-q")
    (home / ".gitignore").write_text("/settings.machine.json\n")
    for rel, text in CODE_OLD.items():
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text(text)
    (home / "settings.json").write_bytes(canon(prev))
    git(sb, home, "add", "-A")
    git(sb, home, "commit", "-q", "-m", "previous")
    rev = git(sb, home, "rev-parse", "HEAD").stdout.decode().strip()
    for rel, text in CODE_NEW.items():
        (home / rel).write_text(text)
    (home / ".gitattributes").write_text("/settings.json filter=claude-settings\n")
    (home / "settings.json").write_bytes(canon(clean_form()))
    git(sb, home, "add", "-A")
    git(sb, home, "commit", "-q", "-m", "new tree")
    return home, rev


def norm_hooks(hooks):
    def norm(h):
        h = dict(h)
        command = h["command"].replace('"', "")
        h["command"] = command.replace(CHANNEL, "<H>").replace(OLD_HOME, "<H>")
        return h
    return {event: [dict(g, hooks=[norm(h) for h in g["hooks"]]) for g in groups]
            for event, groups in hooks.items()}


def test_migrate_builds_overlay_and_render_matches_previous(sb):
    prev = previous_settings()
    home, rev = migration_repo(sb, prev)

    proc = run_tool(sb, home, "migrate", "--from", rev)
    assert proc.returncode == 0, proc.stderr
    out = (proc.stdout + proc.stderr).decode()
    for value in list(DERIVED.values()) + ["/opt/demo", "demo-model-x", "dark", str(home)]:
        assert value not in out, value
    assert "paseo=on" in out and "CLAUDE_HOME" in out and "DEMO_BIN" in out
    assert "CLAUDE_PROTECTED_DAEMON_PREFIX" in out
    path = home / "settings.machine.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    overlay = json.loads(path.read_bytes())
    assert path.read_bytes() == canon(overlay)
    assert overlay["modules"] == {"paseo": True}
    assert overlay["env"] == dict({"DEMO_BIN": "/opt/demo/bin/demo-tool"}, **DERIVED,
                                  CLAUDE_HOME=str(home))
    assert overlay["permissions"] == {"allow": ["Bash(%s/scripts/demo-tool.sh:*)" % OLD_HOME,
                                                "Bash(/opt/demo/bin/helper:*)"]}
    assert overlay["hooks"] == {"Notification": [NOTIFY_GROUP]}
    assert {k: overlay[k] for k in ("model", "theme", "effortLevel")} == {
        "model": "demo-model-x", "theme": "dark", "effortLevel": "high"}
    assert set(overlay) == {"modules", "env", "permissions", "hooks", "model", "theme",
                            "effortLevel"}

    # Refuses when an overlay exists; the overlay is left byte-identical.
    before = path.read_bytes()
    proc = run_tool(sb, home, "migrate", "--from", rev)
    assert proc.returncode == 1 and "already exists" in proc.stderr.decode()
    assert path.read_bytes() == before

    # --settings-file and --base: the previous file need not be committed.
    path.unlink()
    from_file = dict(prev, autoCompactEnabled=False)
    prev_path = sb.tmp / "previous-settings.json"
    prev_path.write_bytes(canon(from_file))
    proc = run_tool(sb, home, "migrate", "--from", rev, "--settings-file", str(prev_path),
                    "--base", "HEAD")
    assert proc.returncode == 0, proc.stderr
    overlay2 = json.loads(path.read_bytes())
    assert overlay2 == dict(overlay, autoCompactEnabled=False)

    # Render: semantically the previous file, except the listed path-form differences.
    register_filter(sb, home)
    proc = run_tool(sb, home, "render")
    assert proc.returncode == 0, proc.stderr
    rendered = json.loads((home / "settings.json").read_bytes())
    assert status(sb, home) == ""
    assert {k: v for k, v in rendered.items() if k not in STRUCTURED} == \
        {k: v for k, v in from_file.items() if k not in STRUCTURED}
    assert {k: rendered["env"][k] for k in from_file["env"]} == from_file["env"]
    assert set(rendered["env"]) - set(from_file["env"]) == set(DERIVED) | {"CLAUDE_HOME"}
    perms, prev_perms = rendered["permissions"], from_file["permissions"]
    assert perms["deny"] == prev_perms["deny"] and perms["ask"] == prev_perms["ask"]
    assert set(prev_perms["allow"]) <= set(perms["allow"])
    path_form_differences = {"Bash(~/.claude/scripts/demo-tool.sh:*)"}
    assert set(perms["allow"]) - set(prev_perms["allow"]) == path_form_differences
    assert len(perms["allow"]) == len(set(perms["allow"]))
    # Hooks: identical per event once the harness-home path form is normalised (absolute and
    # unquoted in the previous file, the quoted ${CLAUDE_HOME:-...} channel form now).
    assert norm_hooks(rendered["hooks"]) == norm_hooks(from_file["hooks"])
    for groups in rendered["hooks"].values():
        for group in groups:
            for h in group["hooks"]:
                assert OLD_HOME not in h["command"]


def test_migrate_detects_module_off(sb):
    prev = previous_settings(paseo=False)
    home, rev = migration_repo(sb, prev)
    proc = run_tool(sb, home, "migrate", "--from", rev)
    assert proc.returncode == 0, proc.stderr
    assert "paseo=off" in proc.stdout.decode()
    overlay = json.loads((home / "settings.machine.json").read_bytes())
    assert overlay["modules"] == {"paseo": False}
    assert overlay["hooks"] == {"Notification": [NOTIFY_GROUP]}
    register_filter(sb, home)
    assert run_tool(sb, home, "render").returncode == 0
    rendered = json.loads((home / "settings.json").read_bytes())
    assert norm_hooks(rendered["hooks"]) == norm_hooks(prev["hooks"])
    assert "mcp__paseo__*" not in rendered["permissions"]["allow"]


def test_migrate_refuses_unknown_revision(sb):
    home, _rev = migration_repo(sb, previous_settings())
    for bad in ("no-such-revision", "--output=x"):
        proc = run_tool(sb, home, "migrate", "--from", bad)
        assert proc.returncode != 0
    assert not (home / "settings.machine.json").exists()


# --------------------------------------------------------------- randomised algebra (in-process)

def test_round_trip_properties_randomised(sb):
    tool = load_tool(sb)
    rng = random.Random(20261014)
    pool = [[{"type": "command", "command": "python3 demo-%d.py" % i}] for i in range(3)]
    for fragment_groups in tool.MODULES["paseo"]["hooks"].values():
        pool.extend(copy.deepcopy(g["hooks"]) for g in fragment_groups)
    matchers = [None, "", "*", "A", "B", "A|B", "C", "B|C", "A|C|D", RUNCODE, PASEO_RUNCODE]
    events = ["PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop"]
    entries = ["E%d" % i for i in range(6)] + ["mcp__paseo__*"]

    def group():
        g = {"hooks": copy.deepcopy(rng.choice(pool))}
        m = rng.choice(matchers)
        if m is not None:
            g["matcher"] = m
        return g

    def settings_doc(cli):
        doc = {"cleanupPeriodDays": rng.randrange(40)}
        if rng.random() < 0.85:
            doc["env"] = {"K%d" % i: "b%d" % rng.randrange(3)
                          for i in rng.sample(range(6), rng.randrange(4))}
        if rng.random() < 0.85:
            names = rng.sample(["allow", "deny", "ask"], rng.randrange(4))
            doc["permissions"] = {name: rng.sample(entries, rng.randrange(4)) for name in names}
        if rng.random() < 0.9:
            doc["hooks"] = {ev: [group() for _ in range(rng.randrange(4))]
                            for ev in rng.sample(events, rng.randrange(5))}
        if cli and rng.random() < 0.3:
            doc["model"] = "m0"
        return doc

    def overlay():
        doc = {"modules": {"paseo": rng.random() < 0.6}, "_doc": "meta"}
        doc["env"] = {"K%d" % i: "o%d" % rng.randrange(3)
                      for i in rng.sample(range(8), rng.randrange(4))}
        doc["permissions"] = {name: rng.sample(entries, rng.randrange(3))
                              for name in rng.sample(["allow", "deny"], rng.randrange(3))}
        doc["hooks"] = {ev: [group() for _ in range(rng.randrange(3))]
                        for ev in rng.sample(events, rng.randrange(3))}
        for key, value in (("cleanupPeriodDays", 7), ("model", "m1"), ("extraKey", [1, 2])):
            if rng.random() < 0.3:
                doc[key] = value
        return doc

    def mutate(doc):
        doc = copy.deepcopy(doc)
        for _ in range(rng.randrange(1, 4)):
            choice = rng.randrange(6)
            if choice == 0 and doc.get("env"):
                del doc["env"][rng.choice(list(doc["env"]))]
            elif choice == 1:
                doc.setdefault("env", {})["K%d" % rng.randrange(8)] = "x"
            elif choice == 2:
                allow = doc.setdefault("permissions", {}).setdefault("allow", [])
                allow.append(rng.choice(entries))
            elif choice == 3 and doc.get("hooks"):
                lst = doc["hooks"][rng.choice(list(doc["hooks"]))]
                if lst:
                    lst.append(copy.deepcopy(rng.choice(lst)))
                    target = rng.choice(lst)
                    target["matcher"] = rng.choice([m for m in matchers if m is not None])
            elif choice == 4:
                doc.setdefault("hooks", {}).setdefault(rng.choice(events), []).append(group())
            else:
                doc["theme"] = "t"
        return doc

    checked = 0
    for _ in range(400):
        base = json.loads(canon(settings_doc(cli=False)))
        over = overlay()
        tool._validate_layer(tool._layer_of(over), "overlay")
        layers = tool.layers_of(over)
        b_bytes = canon(base)
        machine, problem = tool.smudge_bytes(b_bytes, layers)
        assert problem is None
        assert tool.clean_bytes(machine, layers, base) == (b_bytes, None), (base, over)
        assert tool.smudge_bytes(machine, layers) == (machine, None), (base, over)
        assert tool.clean_bytes(b_bytes, layers, base) == (b_bytes, None)
        edited = canon(mutate(json.loads(machine)))
        once, problem = tool.clean_bytes(edited, layers, base)
        assert problem is None
        assert tool.clean_bytes(once, layers, base) == (once, None), (base, over, edited)
        twice, _ = tool.smudge_bytes(edited, layers)
        assert tool.smudge_bytes(twice, layers) == (twice, None)
        # A recorded earlier overlay: clean strips what it applied even when the current overlay
        # no longer lists it (stale working file) or is gone, and changes nothing else.
        old = tool.layers_of(overlay())
        stale, problem = tool.smudge_bytes(b_bytes, old)
        assert problem is None
        assert tool.clean_bytes(stale, layers + old, base) == (b_bytes, None), (base, over, old)
        assert tool.clean_bytes(stale, old, base) == (b_bytes, None), (base, old)
        assert tool.clean_bytes(machine, layers + old, base) == (b_bytes, None), (base, over, old)
        checked += 1
    assert checked == 400
