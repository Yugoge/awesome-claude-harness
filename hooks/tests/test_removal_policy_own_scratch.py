"""A removal inside the caller's own scratch directory runs (lib/bash_safety_rules.py::removal_policy).

The owner, 2026-11-19: one's own temp folder may be deleted. Until then every removal the analyzer found was
refused, wherever its files lay. Now a removal runs when two things hold:

* the analyzer knows every file the command removes: each removal is `rm` or `unlink` run as a command's own head,
  every operand written out (no variable, substitution, pattern or `~`), and nothing else in the command is unproven
  (lib/bash_execution_boundary.py reports the files as `removal_targets`; its verdict stays FORBIDDEN_REMOVAL);
* each of those files lies inside the calling actor's own scratch directory, by the one definition the write policy
  uses for where that actor may write scratch files (hooks/pretool-tool-policy.py: `_scratch_status` == "owner").

Every other removal is refused as before, and the refusal now names the caller's own scratch directory, in the write
policy's own words. An actor the write policy gives no scratch directory (the main agent) owns none.

Projects are throwaway directories; no command is ever executed.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
HOOK = os.path.join(HOOKS_DIR, "pretool-bash-safety.sh")
WRITE_POLICY = os.path.join(HOOKS_DIR, "pretool-tool-policy.py")
sys.path.insert(0, os.path.join(HOOKS_DIR, "lib"))

import bash_execution_boundary as eb  # noqa: E402

SID = "5e6f7a8b-1c2d-4e3f-9a0b-1c2d3e4f5a6b"
AGENT, OTHER_AGENT = "a1b2c3d4e5f60718", "a9999999999999999"
NAMED = re.compile(r"your own scratch directory is (/\S+?)/ ")
REFUSED = "removal-policy — FORBIDDEN_REMOVAL filesystem_removal"


# ── What the analyzer knows ──────────────────────────────────────────────────

KNOWN = [
    ("rm -rf /s/own/x", ["/s/own/x"], []),
    ("rm -f a b 'c d'", ["a", "b", "c d"], []),
    ("rm -rf -- -x y", ["-x", "y"], []),
    ("rm - x", ["-", "x"], []),
    ("unlink /s/own/f", ["/s/own/f"], []),
    ("rm /s/own/x; unlink /s/own/y", ["/s/own/x", "/s/own/y"], []),
    ("cd /p; rm -f rel/x", ["rel/x"], ["/p"]),
    ("(cd /q && rm y)", ["y"], ["/q"]),
    ("pushd /q; rm z; popd", ["z"], ["/q"]),
    ("if [ -f /s/own/x ]; then rm /s/own/x; fi", ["/s/own/x"], []),
    ("ls /s/own; rm -f /s/own/x && echo done > /s/own/log", ["/s/own/x"], []),
    ("cd sub && rm x", ["x"], None),      # a `cd` whose directory is not written out as an absolute path
    ("cd; rm x", ["x"], None),
]
UNKNOWN = [
    "rm /s/own/x; rm $D", "rm -rf \"$D\"", "rm *.tmp", "rm /s/own/*", "rm /s/own/{a,b}", "rm ~/x", "rm -rf",
    "rm /s/own/x.$$", "rm \"$(pwd)/x\"", "D=$(mktemp -d); rm -rf $D", "for f in a b; do rm \"$f\"; done",
    "sudo rm /s/own/x", "command rm /s/own/x", "env rm /s/own/x", "bash -c 'rm /s/own/x'", "eval 'rm /s/own/x'",
    "echo x | xargs rm /s/own/x", "x=$(rm /s/own/x)", "find /s/own -name '*.tmp' -delete",
    "find /s/own -exec rm {} +", "shred -u /s/own/x", "srm /s/own/x", "rm /s/own/x; git rm y",
    "rm /s/own/x; git rm -f y", "rm /s/own/x; $TOOL y", "rm /s/own/x; python3 -c 'import os; os.unlink(\"y\")'",
]


@pytest.mark.parametrize("command,targets,cwds", KNOWN, ids=[c for c, _t, _d in KNOWN])
def test_the_analyzer_reports_the_files_a_removal_names(command, targets, cwds):
    result = eb.analyze(command)
    assert result["verdict"] == eb.FORBIDDEN_REMOVAL and result["allowed"] is False, result
    assert result.get("removal_targets") == {"targets": targets, "cwds": cwds}, result.get("removal_targets")


@pytest.mark.parametrize("command", UNKNOWN)
def test_the_analyzer_reports_no_files_when_it_does_not_know_them_all(command):
    result = eb.analyze(command)
    assert result["allowed"] is False, result
    assert "removal_targets" not in result, (command, result.get("removal_targets"))


def test_a_command_that_removes_nothing_reports_no_files():
    for command in ("ls -la", "man rm", "git rm --cached x", "echo rm /s/own/x"):
        assert "removal_targets" not in eb.analyze(command), command


# ── Through the hook ─────────────────────────────────────────────────────────

class Project:
    """A throwaway project with the caller's own scratch directory, another actor's, a source file and two links."""

    def __init__(self, base):
        self.base = base
        self.root = str(base / "proj")
        self.scratch = os.path.join(self.root, ".claude", "scratch")
        self.own = os.path.join(self.scratch, SID, "dev", AGENT)
        self.other = os.path.join(self.scratch, SID, "dev", OTHER_AGENT)
        for d in (self.own + "/sub", self.other, self.root + "/src"):
            os.makedirs(d)
        os.symlink(self.own + "/sub", self.root + "/src/link_in")   # outside, pointing into the own directory
        os.symlink(self.root + "/src", self.own + "/link_out")      # inside, pointing out of it
        self.home = str(base / "home")

    def env(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        env.update(HOME=self.home, CLAUDE_CONFIG_DIR=os.path.join(self.home, ".claude"), CLAUDE_PROJECT_DIR=self.root,
                   CLAUDE_STATE_DIR=str(self.base / "state"), CLAUDE_PYTHON_BIN=sys.executable,
                   CLAUDE_PROTECTED_RUNTIME_FILE=os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"],
                   CLAUDE_HOOK_BOUNDARY_TIMEOUT="120s", PYTHONDONTWRITEBYTECODE="1")
        return env

    def payload(self, tool, tool_input, caller, cwd=None):
        payload = {"session_id": SID, "cwd": cwd or self.root, "hook_event_name": "PreToolUse", "tool_name": tool,
                   "tool_input": tool_input}
        if caller:
            payload.update(agent_id=caller[0], agent_type=caller[1], subagent_type=caller[1])
        return payload

    def bash(self, command, caller=(AGENT, "dev"), cwd=None, **env_extra):
        proc = subprocess.run(["bash", HOOK], input=json.dumps(self.payload("Bash", {"command": command}, caller, cwd)),
                              capture_output=True, text=True, cwd=cwd or self.root, env={**self.env(), **env_extra},
                              timeout=180)
        return proc.returncode, proc.stderr

    def write(self, path, caller=(AGENT, "dev")):
        """The write policy's verdict on a Write of ``path`` by the same caller."""
        proc = subprocess.run([sys.executable, WRITE_POLICY], capture_output=True, text=True, cwd=self.root,
                              input=json.dumps(self.payload("Write", {"file_path": path, "content": "x"}, caller)),
                              env=self.env(), timeout=120)
        return proc.returncode, proc.stderr


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    return Project(tmp_path_factory.mktemp("own-scratch"))


OWN = [
    "rm -f {own}/a.txt",
    "rm -rf {own}/sub",
    "rm {own}/a {own}/sub/b",
    "rm -f .claude/scratch/{sid}/dev/{agent}/a.txt",              # relative, from the project the call runs in
    "cd {root}; rm -f .claude/scratch/{sid}/dev/{agent}/a.txt",   # after a `cd` written out
    "rm {own}/a; unlink {own}/b",
    "ls {own}; rm -f {own}/a.txt && echo done",
    "if [ -f {own}/a.txt ]; then rm {own}/a.txt; fi",
]
NOT_OWN = [
    "rm {root}/src/main.py",                                      # a project file
    "rm -f {own}/a.txt {root}/src/main.py",                       # one own, one not
    "rm -f {other}/a.txt",                                        # another actor's scratch directory
    "rm -f {scratch}/_probe.py",                                  # the scratch root, nobody's own
    "rm /tmp/x.py",                                               # a bare file in the system temp directory
    "rm -rf {own}/sub/../../../../../src",                        # leaves the directory through `..`
    "rm {root}/src/link_in",                                      # a link outside that points in
    "rm {own}/link_out",                                          # a link inside that points out
    "rm -rf {own}",                                               # the directory itself is not inside it
    "cd src && rm -f ../.claude/scratch/{sid}/dev/{agent}/a.txt",  # relative after a `cd` that is not written out
    "rm -rf {own}/*",                                             # a pattern: the files are not written out
    "D={own}/sub; rm -rf $D",                                     # a variable
    "D=$(mktemp -d); touch $D/x; rm -rf $D",                      # a directory the command makes: not known here
    "sudo rm -f {own}/a.txt",                                     # not the command's own head
    "find {own} -name '*.tmp' -delete",
    "rm -f {own}/a.txt; git rm -f README.md",
]


def _fill(template, project):
    return template.format(own=project.own, other=project.other, root=project.root, scratch=project.scratch, sid=SID,
                           agent=AGENT)


@pytest.mark.parametrize("template", OWN)
def test_a_removal_inside_the_callers_own_scratch_directory_runs(project, template):
    code, err = project.bash(_fill(template, project))
    assert code == 0 and "removal-policy" not in err, (template, err)


@pytest.mark.parametrize("template", NOT_OWN)
def test_any_other_removal_is_refused_and_names_the_own_directory(project, template):
    code, err = project.bash(_fill(template, project))
    assert code == 2 and "BLOCKED: removal-policy" in err, (template, err)
    found = NAMED.search(err)
    assert found and found.group(1) == project.own, (template, err)
    assert "A removal runs when every file it names is written out" in err, err


def test_the_named_directory_is_one_the_same_actor_may_write_and_delete_in(project):
    """The refusal's directory is the write policy's: a Write there by the same actor is allowed, and so is the
    removal of what it wrote; another actor gets neither."""
    code, err = project.bash("rm /tmp/x.py")
    assert code == 2, err
    own = NAMED.search(err).group(1)
    assert project.write(own + "/next.txt")[0] == 0
    assert project.bash("rm " + own + "/next.txt")[0] == 0
    for other in ((OTHER_AGENT, "dev"), (AGENT, "qa")):
        assert project.write(own + "/next.txt", caller=other)[0] == 2, other
        code, err = project.bash("rm " + own + "/next.txt", caller=other)
        assert code == 2 and REFUSED in err, (other, err)
        assert NAMED.search(err).group(1) != own, (other, err)


def test_the_main_agent_has_no_scratch_directory_of_its_own(project):
    """The write policy defines an own scratch directory for a subagent with a role; for the main agent it defines
    none, so the main agent's removals stay refused and no directory can be named."""
    for command in ("rm -f " + project.own + "/a.txt", "rm /tmp/x.py",
                    "rm -f /var/tmp/claude-scratch/" + SID + "/notes.md"):
        code, err = project.bash(command, caller=None)
        assert code == 2 and REFUSED in err, (command, err)
        assert "own scratch directory" not in err, err


def test_without_a_verdict_a_removal_is_refused_wherever_its_files_lie(project):
    """The degraded path knows no file: the text holds a removal word, so it refuses, naming the directory."""
    code, err = project.bash("rm -f " + project.own + "/a.txt", CLAUDE_HOOK_BOUNDARY_TIMEOUT="0.001s")
    assert code == 2 and "removal-policy FAIL-CLOSED" in err, err
    assert NAMED.search(err).group(1) == project.own


def test_an_unproven_command_naming_a_removal_is_refused_and_names_the_directory(project):
    code, err = project.bash("python3 -c 'import os; os.unlink(\"" + project.own + "/a.txt\")'")
    assert code == 2 and "removal-policy — UNRESOLVED" in err, err
    assert NAMED.search(err).group(1) == project.own


# ── One definition ───────────────────────────────────────────────────────────

def _write_policy():
    spec = importlib.util.spec_from_file_location("_tool_policy_under_test", WRITE_POLICY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._bootstrap_security()
    return module


def test_the_owner_test_is_the_write_policys_own(project, monkeypatch):
    """lib/bash_safety_rules.py asks hooks/pretool-tool-policy.py; it holds no reading of its own to drift."""
    argv, sys.argv = sys.argv, [sys.argv[0], HOOKS_DIR]
    try:
        import bash_safety_rules as R
    finally:
        sys.argv = argv
    monkeypatch.setattr(R, "HOOKS", HOOKS_DIR)
    for name, value in project.env().items():
        monkeypatch.setenv(name, value)
    policy = _write_policy()
    paths = [project.own + "/a.txt", project.own, project.other + "/a.txt", project.scratch + "/x", project.root + "/src/a",
             "/tmp/x.py", project.own + "/link_out", project.root + "/src/link_in"]
    for caller in ((AGENT, "dev"), (AGENT, "qa"), (OTHER_AGENT, "dev"), None):
        payload = project.payload("Bash", {"command": "true"}, caller)
        owns, note = R._scratch_owner(payload)
        role = policy.resolve_agent_type(payload)
        for path in paths:
            assert owns(path) == bool(role and policy._scratch_status(role, path, payload) == "owner"), (caller, path)
        assert bool(note) == bool(caller), (caller, note)
    source = open(os.path.join(HOOKS_DIR, "lib", "bash_safety_rules.py"), encoding="utf-8").read()
    body = source[source.index("def _scratch_owner(payload):"):source.index("def removal_policy(payload_text, command):")]
    assert "_scratch_status(" in body and "_note_own_scratch(" in body
    assert '"scratch"' not in body and "'scratch'" not in body and "session_resources" not in body, \
        "the removal policy composes no scratch path of its own"


def test_a_write_policy_that_cannot_be_asked_owns_nothing(tmp_path, project):
    """No answer is no ownership: with the write policy's file gone, the removal is refused as it always was."""
    import shutil
    stage = tmp_path / "hooks"
    shutil.copytree(HOOKS_DIR, stage, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    os.remove(stage / "pretool-tool-policy.py")
    proc = subprocess.run(["bash", str(stage / "pretool-bash-safety.sh")], capture_output=True, text=True,
                          input=json.dumps(project.payload("Bash", {"command": "rm -f " + project.own + "/a.txt"},
                                                           (AGENT, "dev"))), cwd=project.root, env=project.env(),
                          timeout=180)
    assert proc.returncode == 2 and REFUSED in proc.stderr, proc.stderr
