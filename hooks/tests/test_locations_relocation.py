"""The nine location findings of the hardcode audit (2026-11-19), relocated.

hooks/lib/locations.py is the one place that answers where things are. Each decision that
used to test a literal is taken here with the project under /dev/shm, /root, /home/<user>,
/var/tmp, /run/user/<uid> and at a path with a space, and, where a harness home is named,
with the home addressed by its real path, as ~/.claude and through an account's symlinked
directory: the answer is the same in every cell.

No directory is made at a project location. The hooks judge paths, and the roots are
injected the way a session gives them (CLAUDE_PROJECT_DIR, the payload's cwd, HOME,
CLAUDE_HOME, CLAUDE_CONFIG_DIR, CLAUDE_STATE_DIR, TMPDIR); the home's links are made
under pytest's own tmp_path. On f199dfb1e the /dev/shm, /var/tmp, real-path and
account-link cells fail.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shlex
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS))
NEVER = "harness-audit-throwaway-never-made"  # no test creates a directory of this name
PROJECTS = {
    "dev-shm": f"/dev/shm/{NEVER}/proj",
    "root": f"/root/{NEVER}/proj",
    "home-user": "/home/harness-audit-throwaway-user/proj",
    "var-tmp": f"/var/tmp/{NEVER}/proj",
    "run-user": f"/run/user/{os.getuid()}/{NEVER}/proj",
    "space": f"/srv/{NEVER} with space/my proj",
}
TASK = "20261119-101010"
POLICY_BLOCK = "BLOCKED by tool-policy.v1: "


@pytest.fixture(params=list(PROJECTS))
def project(request) -> str:
    path = PROJECTS[request.param]
    assert not os.path.exists(path)
    return path


def _load(name: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, HOOKS / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _env(tmp_path: Path, project: str, **extra) -> dict:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    for name in ("state", "tmp"):
        (tmp_path / name).mkdir(exist_ok=True)
    env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8",
           "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
           "CLAUDE_STATE_DIR": str(tmp_path / "state"), "TMPDIR": str(tmp_path / "tmp"),
           "CLAUDE_PROJECT_DIR": project, "PYTHONDONTWRITEBYTECODE": "1"}
    env.update(extra)
    return env


def _hook(name: str, payload: dict, env: dict, cwd: Path):
    return subprocess.run([sys.executable, str(HOOKS / name)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(cwd), env=env, timeout=120)


def _payload(project: str, tool: str, tool_input: dict, **extra) -> dict:
    return {"session_id": "s-relocation", "cwd": project, "hook_event_name": "PreToolUse",
            "permission_mode": "default", "tool_name": tool, "tool_input": tool_input, **extra}


# --- finding 1: a write target under /dev/ was dropped before three tool-policy stages -------------

class Session:
    """A transcript store shaped as the CLI keeps it (after test_tool_policy_derived_permission.py)."""

    def __init__(self, root: Path):
        self.sid = "sess-" + uuid.uuid4().hex[:8]
        self.transcript = root / f"{self.sid}.jsonl"
        self.subagents = root / self.sid / "subagents"
        self.subagents.mkdir(parents=True)
        self.transcript.write_text("")

    def _append(self, record: dict) -> None:
        with self.transcript.open("a") as fh:
            fh.write(json.dumps(record) + "\n")

    def command(self, name: str) -> None:
        self._append({"type": "user", "message": {"role": "user", "content":
                      f"<command-message>{name} is running…</command-message>\n"
                      f"<command-name>/{name}</command-name>\n<command-args>x</command-args>"}})

    def dispatch(self, role: str, *paths: str) -> tuple:
        doc = {"task_id": TASK, "role": role, "pipeline": "dev", "profile": "singular",
               "dispatched_at": "2026-11-19T10:10:10Z",
               "artifacts": [{"kind": "markdown", "path": p, "identity_anchor": TASK} for p in paths]}
        prompt = f'You are the {role} subagent.\n<obligation v="1">\n{json.dumps(doc)}\n</obligation>'
        call_id = "toolu_" + uuid.uuid4().hex[:20]
        self._append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": call_id, "name": "Agent", "input": {"description": "d", "prompt": prompt}}]}})
        agent_id = "a" + uuid.uuid4().hex[:16]
        (self.subagents / f"agent-{agent_id}.jsonl").write_text(
            json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
        (self.subagents / f"agent-{agent_id}.meta.json").write_text(
            json.dumps({"agentType": "general-purpose", "toolUseId": call_id}))
        return agent_id, role

    def payload(self, project: str, tool: str, tool_input: dict, agent: tuple | None = None) -> dict:
        extra = {"session_id": self.sid, "transcript_path": str(self.transcript),
                 "tool_use_id": "toolu_" + uuid.uuid4().hex[:24]}
        if agent:
            extra.update(agent_id=agent[0], agent_type=agent[1], subagent_type=agent[1])
        return _payload(project, tool, tool_input, **extra)


def _denial(proc) -> dict:
    assert proc.returncode == 2, proc.stderr
    first = proc.stderr.splitlines()[0]
    assert first.startswith(POLICY_BLOCK), proc.stderr
    return json.loads(first[len(POLICY_BLOCK):])


def test_f1_declared_report_is_its_declarers_alone_wherever_the_project_is(tmp_path, project):
    """The declaring dispatch writes its report; every other caller is refused, by a Write and by
    a Bash redirect, absolute or relative. Under /dev/shm this was the reverse."""
    context, report = f"docs/dev/context-{TASK}.json", f"docs/dev/dev-report-{TASK}.json"
    session = Session(tmp_path / "store")
    session.command("dev")
    ba, dev = session.dispatch("ba", context), session.dispatch("dev", report)
    env, target = _env(tmp_path, project), os.path.join(project, context)

    def run(tool, tool_input, agent=None):
        return _hook("pretool-tool-policy.py", session.payload(project, tool, tool_input, agent), env, tmp_path)

    own = run("Write", {"file_path": target, "content": "x"}, ba)
    assert own.returncode == 0, own.stderr
    for agent in (dev, None):
        denial = _denial(run("Write", {"file_path": target, "content": "x"}, agent))
        assert "only ba writes this artifact (D8)" in denial["deny_reason"], denial
    for command in (f"printf x > {shlex.quote(target)}", f"printf x > {context}"):
        denial = _denial(run("Bash", {"command": command}))
        assert "only ba writes this artifact (D8)" in denial["deny_reason"], denial
    assert not os.path.exists(project)


# The six files of finding 1 that passed the whole write gate by their real path under /dev/shm.
PROTECTED = ("private-literals.txt", "scripts/check-public-core.sh", "scripts/install/render-settings",
             "hooks/git-hooks/pre-commit", ".gitattributes", ".git/config")


@pytest.mark.parametrize("rel", PROTECTED)
@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_f1_protected_file_is_refused_by_its_real_path_wherever_the_home_is(monkeypatch, capsys, project, rel, tool):
    """The harness home at each location (injected: the protected stage asks lib/claude_home for it):
    a Write or Edit of a protected file by its absolute path is refused."""
    policy = _load("pretool-tool-policy.py", "tool_policy_relocation")
    policy._bootstrap_security()
    home = os.path.join(os.path.dirname(project), "dot-claude")
    from lib import claude_home
    monkeypatch.setattr(claude_home, "resolve", lambda: Path(home))
    target = os.path.join(home, rel)
    tool_input = {"file_path": target, "content": "x"}
    data = _payload(project, tool, tool_input)
    with pytest.raises(SystemExit) as stop:
        policy._check_protected(None, tool, tool_input, policy._extract_targets(tool, tool_input), data)
    assert stop.value.code == 2
    assert "no agent writes, deletes or renames it (D11/D12)" in capsys.readouterr().err


def test_f1_a_device_write_stays_harmless(tmp_path, project):
    """/dev/null and the standard streams hold no artifact (the three stages skip them); a file of a
    project on the /dev/shm tmpfs is no device."""
    policy = _load("pretool-tool-policy.py", "tool_policy_relocation_devices")
    policy._bootstrap_security()
    inside = os.path.join(project, "docs", "x.json")
    assert policy._write_targets("Bash", ["/dev/null", "/dev/stderr", "/dev/stdout", "/dev/fd/2", inside]) == [inside]
    proc = _hook("pretool-tool-policy.py", _payload(project, "Bash", {"command": "ls src > /dev/null 2> /dev/stderr"},
                                                    agent_id="a1", agent_type="qa", subagent_type="qa"),
                 _env(tmp_path, project), tmp_path)
    assert proc.returncode == 0, proc.stderr


# --- finding 13: "system temp" was the literals /tmp and /var/tmp, the project included ------------

def test_f13_a_project_is_not_arbitrary_temp_wherever_it_is_checked_out(tmp_path, project):
    env = _env(tmp_path, project)
    dev = {"agent_id": "a1", "agent_type": "dev", "subagent_type": "dev"}

    def run(tool, tool_input):
        return _hook("pretool-tool-policy.py", _payload(project, tool, tool_input, **dev), env, tmp_path)

    for tool, tool_input in (("Write", {"file_path": os.path.join(project, "src", "app.py"), "content": "x"}),
                             ("Bash", {"command": "printf x > src/app.py"})):
        proc = run(tool, tool_input)
        assert proc.returncode == 0, proc.stderr
    # the ban on system temp writes keeps its meaning: a path there outside the project is refused
    for stray in (f"/tmp/{NEVER}-stray/x.txt", f"/var/tmp/{NEVER}-stray/x.txt"):
        denial = _denial(run("Write", {"file_path": stray, "content": "x"}))
        assert "arbitrary /tmp and /var/tmp are denied for every role" in denial["deny_reason"], denial


def test_f13_a_symlinked_temp_directory_answers_alike(tmp_path, monkeypatch):
    from lib import locations
    real, link = tmp_path / "private-tmp", tmp_path / "tmp-link"
    real.mkdir()
    link.symlink_to(real)
    monkeypatch.setattr(locations, "SYSTEM_TEMP_DIRS", (str(link),))
    assert locations.system_temp_roots() == (str(real),)
    for spelling in (real, link):
        assert locations.in_system_temp(str(spelling / "scratch" / "x.txt"))
        assert locations.in_arbitrary_temp(str(spelling / "x.txt"), "/work/proj")
        assert not locations.in_arbitrary_temp(str(spelling / "proj" / "x.txt"), str(link / "proj"))
    assert not locations.in_system_temp(str(tmp_path / "elsewhere" / "x.txt"))
    assert not locations.in_system_temp(str(link))  # the root itself is not below it
    # judged where the write lands: a link kept in temp that leads out of it, and one leading into it
    (real / "out").symlink_to(tmp_path / "elsewhere")
    (tmp_path / "in").symlink_to(real / "scratch")
    assert not locations.in_system_temp(str(link / "out" / "x.txt"))
    assert locations.in_system_temp(str(tmp_path / "in" / "x.txt"))


# --- finding 2: the hooks and commands folders were the text `.claude/hooks/` ----------------------

@pytest.fixture
def home_layout(tmp_path):
    """This machine in miniature: the home's real directory has no `.claude` in its name,
    ~/.claude links to it, and an account's configuration directory links its hooks and commands."""
    real = tmp_path / "dot-claude-real"
    for sub in ("hooks", "commands"):
        (real / sub).mkdir(parents=True)
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / ".claude").symlink_to(real)
    (tmp_path / "acct" / "claude").mkdir(parents=True)
    for sub in ("hooks", "commands"):
        (tmp_path / "acct" / "claude" / sub).symlink_to(tmp_path / "home" / ".claude" / sub)
    return {"real path": real, "~/.claude": tmp_path / "home" / ".claude", "account link": tmp_path / "acct" / "claude"}


SPELLINGS = ("real path", "~/.claude", "account link")


def _home_env(tmp_path: Path, project: str, layout: dict) -> dict:
    return _env(tmp_path, project, CLAUDE_HOME=str(layout["real path"]),
                CLAUDE_CONFIG_DIR=str(layout["account link"]))


@pytest.mark.parametrize("spelling", SPELLINGS)
def test_f2_config_guard_judges_the_folder_by_where_it_is(tmp_path, project, home_layout, spelling):
    env, base = _home_env(tmp_path, project, home_layout), home_layout[spelling]
    for folder, name in (("hooks", "pretool-x.py"), ("commands", "x.md")):
        target = str(base / folder / name)
        proc = _hook("pretool-claude-config-guard.py",
                     _payload(project, "Write", {"file_path": target, "content": "x"}), env, tmp_path)
        assert proc.returncode == 2 and f"agent Write to .claude/{folder}/" in proc.stderr, (target, proc.stderr)
        proc = _hook("pretool-claude-config-guard.py",
                     _payload(project, "Bash", {"command": f"cp /etc/hostname {shlex.quote(target)}"}), env, tmp_path)
        assert proc.returncode == 2 and f"agent Bash write to .claude/{folder}/" in proc.stderr, (target, proc.stderr)


def test_f2_a_folder_that_only_ends_in_the_text_is_not_protected(tmp_path, project, home_layout):
    env = _home_env(tmp_path, project, home_layout)
    for target in (os.path.join(project, "docs", "notes.claude", "hooks", "readme.md"),
                   os.path.join(project, "hooks", "local.py"), os.path.join(project, "commands", "local.md")):
        proc = _hook("pretool-claude-config-guard.py",
                     _payload(project, "Write", {"file_path": target, "content": "x"}), env, tmp_path)
        assert proc.returncode == 0, (target, proc.stderr)
    # a project's own configuration directory is one, wherever the project is
    target = os.path.join(project, ".claude", "hooks", "x.py")
    proc = _hook("pretool-claude-config-guard.py",
                 _payload(project, "Write", {"file_path": target, "content": "x"}), env, tmp_path)
    assert proc.returncode == 2, (target, proc.stderr)


def test_f2_a_relative_path_in_the_harness_home_is_judged_from_the_call_directory(tmp_path, home_layout):
    real = home_layout["real path"]
    env = _home_env(tmp_path, str(real), home_layout)
    proc = _hook("pretool-claude-config-guard.py",
                 _payload(str(real), "Write", {"file_path": "hooks/pretool-x.py", "content": "x"}), env, real)
    assert proc.returncode == 2, proc.stderr
    proc = _hook("pretool-claude-config-guard.py",
                 _payload(str(real), "Bash", {"command": "cp /etc/hostname hooks/pretool-x.py"}), env, real)
    assert proc.returncode == 2, proc.stderr


@pytest.mark.parametrize("spelling", SPELLINGS)
def test_f2_overnight_guard_twin_judges_the_folder_by_where_it_is(tmp_path, monkeypatch, project, home_layout, spelling):
    for key, value in _home_env(tmp_path, project, home_layout).items():
        monkeypatch.setenv(key, value)
    overnight = _load("pretool-overnight-hook-guard.py", "overnight_guard_relocation_f2")
    base = home_layout[spelling]
    assert overnight.is_hooks_path(str(base / "hooks" / "pretool-x.py"))
    assert overnight.is_commands_path(str(base / "commands" / "dev.md"))
    assert not overnight.is_commands_path(str(base / "hooks" / "pretool-x.py"))
    stray = os.path.join(project, "docs", "notes.claude", "hooks", "readme.md")
    assert not overnight.is_hooks_path(stray) and not overnight.is_commands_path(stray)
    assert overnight.is_hooks_path(os.path.join(project, ".claude", "hooks", "x.py"))


# --- finding 8: the overnight exemption was the literal /tmp/, the state root unresolved -----------

def test_f8_overnight_exemption_follows_the_session_temp_and_state_roots(tmp_path, monkeypatch, project):
    # the session temp root lies outside the default one, as the shipped settings put it (never made here)
    session_tmp, state_real, state_link = Path(f"/var/tmp/{NEVER}/session tmp"), tmp_path / "state-real", tmp_path / "state-link"
    state_real.mkdir()
    state_link.symlink_to(state_real)  # as /tmp is a link on macOS
    for key, value in _env(tmp_path, project, TMPDIR=str(session_tmp), CLAUDE_STATE_DIR=str(state_link)).items():
        monkeypatch.setenv(key, value)
    overnight = _load("pretool-overnight-hook-guard.py", "overnight_guard_relocation_f8")
    worktree = project + "-wt"

    def allowed(path) -> bool:
        return overnight._is_path_allowed_during_overnight(str(path), [worktree])

    sid = "0b0f6d0e-1111-4222-8333-444455556666"
    assert allowed(os.path.join(worktree, "src", "x.py"))
    assert allowed(session_tmp / sid / "notes.md")                           # the session's scratch directory
    assert allowed(session_tmp / "claude-0" / "-p" / sid / "scratchpad" / "n.md")  # the CLI's scratchpad
    assert allowed(state_link / "claude-grants" / "x.json")                  # the state root as the variable spells it
    assert allowed(state_real / "claude-grants" / "x.json")                  # and by its real path
    assert allowed(f"/tmp/{NEVER}/notes.md")                                 # the system default temp directory
    assert allowed("/dev/null")
    assert not allowed(os.path.join(project, "src", "x.py"))                 # main, outside the worktree
    assert not allowed(f"/etc/{NEVER}/x")
    (state_real / "escape").symlink_to(f"/etc/{NEVER}")                      # a link kept in the state root
    assert not allowed(state_link / "escape" / "x.py")                       # is judged where the write lands


# --- finding 9: a here-document was data only below the literals /tmp/ and /var/tmp/ ---------------

NOTE = "Steps for the owner after review:\ngit push --force origin main\n"


def _heredoc_runs_git(classifier, dest: str) -> bool:
    invocations, _residual = classifier.classify_git_command(f"cat > {shlex.quote(dest)} <<'EOF'\n{NOTE}EOF")
    return bool(invocations)


def test_f9_a_note_written_into_the_project_is_data_wherever_the_project_is(tmp_path, monkeypatch, project):
    for key, value in _env(tmp_path, project).items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(tmp_path)
    from lib import git_command_classifier as classifier
    classifier._shell_layers.cache_clear()
    # data: the project by a relative or an absolute spelling, its managed scratch, the session temp root
    for dest in ("docs/notes.md", os.path.join(project, "docs", "notes.md"),
                 ".claude/scratch/sess/qa/a1/notes.md", os.path.join(project, ".claude", "scratch", "s", "qa", "a1", "notes.md"),
                 str(tmp_path / "tmp" / "sess" / "notes.md"), f"/tmp/{NEVER}/notes.md"):
        assert not _heredoc_runs_git(classifier, dest), dest
    # code, as before: a hidden or hooks component, and an absolute path outside the project and temp
    for dest in (os.path.join(project, ".git", "hooks", "pre-push"), os.path.join(project, "hooks", "x.sh"),
                 ".claude/notes.md", os.path.join(project, ".claude", "settings.json"),
                 f"/etc/{NEVER}/notes.md", "~/.bashrc"):
        assert _heredoc_runs_git(classifier, dest), dest


@pytest.mark.parametrize("spelling", SPELLINGS)
def test_f9_the_harness_home_as_project_answers_alike_by_each_spelling(tmp_path, monkeypatch, home_layout, spelling):
    real = home_layout["real path"]
    for key, value in _home_env(tmp_path, str(real), home_layout).items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(tmp_path)
    from lib import git_command_classifier as classifier
    classifier._shell_layers.cache_clear()
    base = home_layout[spelling]
    # commands/ is in the home by all three spellings (the account directory links it)
    assert not _heredoc_runs_git(classifier, str(base / "commands" / "notes.md"))
    assert _heredoc_runs_git(classifier, str(base / "hooks" / "x.sh"))


# --- finding 11: the overnight git-config check skipped a Bash target under /dev/ ------------------

def test_f11_overnight_bash_write_onto_git_config_is_refused_wherever_main_is(tmp_path, monkeypatch, capsys, project):
    for key, value in _env(tmp_path, project).items():
        monkeypatch.setenv(key, value)
    overnight = _load("pretool-overnight-hook-guard.py", "overnight_guard_relocation_f11")
    main, worktree = project, project + "-wt"
    git_dir = os.path.join(main, ".git")
    # the one git query of the rule, answered for the injected checkout (no repository is made there)
    monkeypatch.setattr(overnight, "_checkout_git_dirs", lambda path: [git_dir, git_dir])
    overnight._set_request_ctx({}, {"cwd": worktree})
    for target in (os.path.join(git_dir, "config"), os.path.join(git_dir, "keystone-hooks", "reference-transaction")):
        assert overnight._targets_git_config(target), target  # the Write tool's predicate
        with pytest.raises(SystemExit) as stop:
            overnight._enforce_overnight_git_command(f"printf x >> {shlex.quote(target)}", main, worktree, git_dir)
        assert stop.value.code == 2
        assert "OVERNIGHT GIT CONFIG PROTECTION" in capsys.readouterr().err
    overnight._enforce_overnight_git_command("printf x > /dev/null", main, worktree, git_dir)  # a device: no refusal


# --- finding 14: the spec roots named one machine's directory, dot-claude --------------------------

@pytest.mark.parametrize("name", ["dot-claude", "claude-harness"])
def test_f14_the_harness_homes_specs_are_a_spec_root_whatever_the_home_is_named(tmp_path, project, name):
    real = tmp_path / name
    (real / "specs" / "s1").mkdir(parents=True)
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / ".claude").symlink_to(real)
    env = _env(tmp_path, project, CLAUDE_CONFIG_DIR=str(tmp_path / "home" / ".claude"))
    for base in (tmp_path / "home" / ".claude", real):
        target = str(base / "specs" / "s1" / "cp-state-dev.json")
        proc = _hook("pretool-cp-state-write-guard.py",
                     _payload(project, "Write", {"file_path": target, "content": "{}"}, agent_id="a1", agent_type="dev"),
                     env, tmp_path)
        assert proc.returncode == 2 and "cp-state write-guard" in proc.stderr, (target, proc.stderr)
        proc = _hook("pretool-bash-views-guard.py",
                     _payload(project, "Bash", {"command": f"printf '{{}}' > {shlex.quote(target)}"}, agent_id="a1"),
                     env, tmp_path)
        assert proc.returncode == 2 and "views/cp-state" in proc.stderr, (target, proc.stderr)


def test_f14_a_projects_spec_roots_are_the_same_wherever_the_project_is(tmp_path, project):
    env = _env(tmp_path, project)

    def write(rel):
        return _hook("pretool-cp-state-write-guard.py", _payload(
            project, "Write", {"file_path": os.path.join(project, rel), "content": "{}"}, agent_id="a1", agent_type="dev"),
            env, tmp_path).returncode

    def redirect(rel):
        return _hook("pretool-bash-views-guard.py", _payload(
            project, "Bash", {"command": f"printf '{{}}' > {shlex.quote(os.path.join(project, rel))}"}, agent_id="a1"),
            env, tmp_path).returncode

    for rel in ("docs/dev/specs/s1/cp-state-dev.json", ".claude/specs/s1/cp-state-dev.json"):
        assert (write(rel), redirect(rel)) == (2, 2), rel
    # no spec root: another specs/ directory, and a directory that only has the old literal's name
    for rel in ("tests/fixtures/specs/s1/cp-state-dev.json", "dot-claude/specs/s1/cp-state-dev.json"):
        assert (write(rel), redirect(rel)) == (0, 0), rel


# --- finding 16: with a relative PATH entry, a path under /dev/ could plant no program -------------

def test_f16_a_relative_path_entry_makes_every_file_a_planted_program_wherever_it_is(tmp_path, monkeypatch, project):
    for key, value in _env(tmp_path, project).items():
        monkeypatch.setenv(key, value)
    guard = _load("pretool-claude-config-guard.py", "config_guard_relocation_f16")
    planted = os.path.join(project, "ls")
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin:/bin")
    assert not guard._on_search_path(planted)
    for path_value in (".:/usr/local/bin:/usr/bin:/bin", "/usr/bin::/bin"):
        monkeypatch.setenv("PATH", path_value)
        assert guard._on_search_path(planted), path_value
        assert not guard._on_search_path("/dev/null")  # a device holds no program
    monkeypatch.setenv("PATH", ".:/usr/local/bin:/usr/bin:/bin")
    command = f"cp /srv/payload {shlex.quote(planted)} && ls .claude/hooks/x.py"
    assert not guard._proven_harmless(command, project)
    assert guard._classify_bash_target(command, project) == "hooks"


# --- finding 17: the runtime guard's stop roots held /root and /home, never the user's home --------

GUARD_PROBE = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
from runtime_guard import _core, config
cfg = {"schema_version": 1, **{k: [] for k in config.REQUIRED_KEYS}}
for command in sys.argv[2:]:
    print(_core.evaluate(command, os.environ["HOME"], cfg)[0])
"""
HOMES = ["/root", "/home/alice", "/Users/alice", f"/var/tmp/{NEVER}/home", f"/dev/shm/{NEVER}/home",
         f"/run/user/1000/{NEVER}/home", f"/srv/{NEVER} with space/home"]


@pytest.mark.parametrize("home", HOMES)
def test_f17_the_users_home_is_a_broad_root_whoever_the_user_is(tmp_path, home):
    quoted = shlex.quote(home)
    allowed = [f"chmod 700 {quoted}", "chmod go-w ~", f"chown alice:alice {quoted}",
               f"chmod 755 {shlex.quote(os.path.dirname(home))}"]
    # the data file's own directories stay protected
    blocked = [f"chmod 700 {shlex.quote(home + '/.config')}", f"rm -rf {shlex.quote(home + '/.config/claude')}",
               f"mv {shlex.quote(home + '/.config/claude/protected-runtime.json')} /srv/x"]
    proc = subprocess.run([sys.executable, "-c", GUARD_PROBE, str(HOOKS / "lib"), *allowed, *blocked],
                          capture_output=True, text=True, cwd=str(tmp_path), timeout=120,
                          env={"PATH": "/usr/bin:/bin", "HOME": home, "PYTHONDONTWRITEBYTECODE": "1"})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == ["ALLOW"] * len(allowed) + ["BLOCK"] * len(blocked), proc.stdout


# --- the one place itself -------------------------------------------------------------------------

def test_a_file_on_the_shared_memory_tmpfs_is_no_device(tmp_path):
    from lib import locations
    for device in ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/fd/2", "/dev", "/dev/tcp/host/80",
                   "/dev/sda1", "/dev/mapper/not-made-yet", "/dev/shm/../sda"):
        assert locations.is_device(device), device
    for ordinary in ("/dev/shm", f"/dev/shm/{NEVER}/proj/docs/x.json", "/dev/../etc/hostname", "/dev/shmem/x/../../shm/x",
                     str(tmp_path / "x"), "docs/x.json", "", "/devices/x"):
        assert not locations.is_device(ordinary), ordinary
    assert locations.is_device("x", cwd="/dev") and not locations.is_device("x", cwd="/dev/shm")
    assert locations.is_system_path("/dev/sda1") and locations.is_system_path("/etc/hostname")
    assert not locations.is_system_path("/dev/shm/proj/x") and not locations.is_system_path("/root/proj/x")


def test_is_inside_resolves_both_sides(tmp_path):
    from lib import locations
    real, link = tmp_path / "real", tmp_path / "link"
    (real / "sub").mkdir(parents=True)
    link.symlink_to(real)
    for directory in (real, link):
        for path in (real / "sub" / "f", link / "sub" / "f", real / "sub" / ".." / "sub" / "f", real):
            assert locations.is_inside(str(path), str(directory)), (path, directory)
        assert locations.inside(str(link / "sub" / "f"), str(directory)) == ("sub", "f")
        assert not locations.is_inside(str(tmp_path / "realistic" / "f"), str(directory))
        assert not locations.is_inside(str(real / ".." / "other"), str(directory))
    assert locations.is_inside("link/sub/f", "real", cwd=str(tmp_path))
    # a write through a link is judged where it lands, not where the link lies
    (real / "sub" / "out").symlink_to(tmp_path / "elsewhere")
    assert not locations.is_inside(str(real / "sub" / "out"), str(real))
    assert not locations.is_inside(str(real / "sub" / "out" / "f"), str(link))


def test_the_roots_have_one_resolution_each(tmp_path, monkeypatch):
    """A writer and a reader that ask the one place get the answer of the resolvers every hook
    already shares (lib/claude_home, lib/harness_state_dir), also through a symlinked spelling."""
    from lib import claude_home, harness_state_dir, locations
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(state) + "//")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/proj")
    monkeypatch.setenv("TMPDIR", str(tmp_path / "t"))
    assert locations.state_root() == harness_state_dir.harness_state_dir() == str(state)
    assert locations.project_root() == claude_home.project_dir() == Path("/work/proj")
    assert locations.harness_home() == claude_home.resolve()
    assert os.path.realpath(str(locations.harness_home())) == str(ROOT)
    assert locations.temp_root() == str(tmp_path / "t")
    monkeypatch.setenv("TMPDIR", "relative/tmp")
    assert locations.temp_root() == locations.DEFAULT_TEMP_DIR
    monkeypatch.setenv("TMPDIR", "/")
    assert os.sep not in locations.session_temp_roots() and os.sep not in locations.temp_roots()
