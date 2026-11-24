"""A hook that cannot write the control state it needs says so; it never passes silently.

Behaviours pinned (each hook runs as a subprocess with its own HOME, project and state dir):
1. hooks/pretool-orchestrator-gate.py: a counted call whose count cannot be recorded, or that finds a
   record it cannot read (an empty one, as a failed write leaves it), is refused with the file, the error,
   the volume and the words "cannot be enforced". An absent record is a fresh count.
2. hooks/prompt-workflow.py on /do: consent that cannot be recorded blocks the prompt (exit 2, the text on
   stderr, which the CLI shows the owner) and nothing is granted.
3. The same hook on /commit and /stop: an intent mark that cannot be written blocks the prompt the same
   way; no empty mark is left.
4. lib/allowlist.py's writers (write_state_entry, write_tool_streak, record_tool_ran,
   write_sentinel_grant) raise and leave no partial or empty entry; hooks/posttool-orchestrator-ran.py
   says that the record failed (exit 1, its stderr reaches the user).
5. A writable state dir: every decision, output and entry as before (test_writable_state_is_unchanged).

Two ways to make the writes fail: a state dir the test user may not write (mode 0o500; meaningful for
an unprivileged user only, as CI runs the tests), and a full volume: a 64 KiB tmpfs mounted in a private
mount namespace only the test's own process tree sees, filled to 0 bytes free (made as root, else in a user
namespace, else through passwordless sudo, as on CI: hooks/tests/_private_ns.py).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _private_ns  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
GATE = HOOKS / "pretool-orchestrator-gate.py"
PROMPT = HOOKS / "prompt-workflow.py"
RAN = HOOKS / "posttool-orchestrator-ran.py"
COUNTED_BASH = {"command": "python3 x.py", "description": "probe"}
UNENFORCED = "cannot be enforced"

unprivileged = pytest.mark.skipif(os.geteuid() == 0, reason="a mode-0o500 directory does not stop root")


class Session:
    def __init__(self, tmp: Path, state: Path | None = None):
        self.tmp = tmp
        self.state = state or tmp / "state"
        self.home, self.project = tmp / "home", tmp / "project"
        for d in (self.home / ".claude", self.project, tmp / "tmp"):
            d.mkdir(parents=True, exist_ok=True)
        self.state.mkdir(parents=True, exist_ok=True)
        self.sid = str(uuid.uuid4())
        self.transcript = tmp / "t.jsonl"
        self.transcript.write_text("")

    def env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        env.update({"HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
                    "CLAUDE_STATE_DIR": str(self.state), "TMPDIR": str(self.tmp / "tmp"),
                    "CLAUDE_PROJECT_DIR": str(self.project), "GIT_CEILING_DIRECTORIES": str(self.tmp),
                    "PYTHONDONTWRITEBYTECODE": "1"})
        return env

    def payload(self, event: str, **extra) -> dict:
        return {"session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(self.project),
                "hook_event_name": event, "permission_mode": "default", **extra}

    def run(self, hook: Path, body: dict) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(hook)], input=json.dumps(body), capture_output=True,
                              text=True, env=self.env(), cwd=self.project, timeout=60)

    def gate(self, tool: str = "Bash", tool_input: dict | None = None) -> subprocess.CompletedProcess:
        return self.run(GATE, self.payload("PreToolUse", tool_name=tool, tool_input=tool_input or COUNTED_BASH,
                                           tool_use_id=f"toolu_{uuid.uuid4().hex[:20]}"))

    def prompt(self, text: str) -> subprocess.CompletedProcess:
        return self.run(PROMPT, self.payload("UserPromptSubmit", prompt=text))

    def streak(self) -> Path:
        return self.state / f"claude-tool-streak-{self.sid}.json"

    def entries(self) -> list:
        return sorted(p.name for p in self.state.iterdir())


@pytest.fixture
def readonly(tmp_path):
    s = Session(tmp_path)
    s.state.chmod(0o500)
    yield s
    s.state.chmod(0o700)


def _names_cause(text: str, path: Path, error: str) -> None:
    assert str(path) in text, text
    assert error in text, text
    assert re.search(r"on the volume mounted at /\S*", text), text


# 1. the call-limit gate ------------------------------------------------------------------------------

@unprivileged
def test_gate_refuses_a_count_it_cannot_record(readonly):
    p = readonly.gate()
    assert p.returncode == 2, p
    _names_cause(p.stderr, readonly.streak(), "Permission denied")
    assert UNENFORCED in p.stderr


def test_gate_refuses_an_empty_record(tmp_path):
    s = Session(tmp_path)
    s.streak().write_text("")  # what a failed write_text left behind
    p = s.gate()
    assert p.returncode == 2, p
    _names_cause(p.stderr, s.streak(), "empty")
    assert UNENFORCED in p.stderr


def test_gate_refuses_a_record_that_is_not_json(tmp_path):
    s = Session(tmp_path)
    s.streak().write_text('{"schema_version": 2, "per_tool')  # a write cut short
    p = s.gate()
    assert p.returncode == 2 and UNENFORCED in p.stderr, p


def test_an_absent_record_is_a_fresh_count(tmp_path):
    s = Session(tmp_path)
    assert [s.gate().returncode for _ in range(6)] == [0, 0, 0, 0, 0, 2]


@pytest.mark.parametrize("where", ["default root", "CLAUDE_STATE_DIR"])
def test_a_fresh_home_counts_from_its_first_call(tmp_path, where):
    """A first session on a fresh machine: no state dir yet, at the default root of a new HOME or at a
    CLAUDE_STATE_DIR not made yet. It is made (0700) and the count runs as in a made one: never a refusal."""
    sys.path.insert(0, str(HOOKS / "lib"))
    from harness_state_dir import state_root
    s = Session(tmp_path)
    s.state.rmdir()
    env = s.env()
    if where == "default root":
        del env["CLAUDE_STATE_DIR"]
        s.state = Path(state_root(home=str(s.home)), "state")
    assert not s.state.exists() and not (s.home / ".local").exists()
    runs = [subprocess.run([sys.executable, str(GATE)], text=True, capture_output=True, env=env, cwd=s.project,
                           input=json.dumps(s.payload("PreToolUse", tool_name="Bash", tool_input=COUNTED_BASH,
                                                      tool_use_id=f"toolu_{n:04d}")), timeout=60) for n in range(6)]
    assert [p.returncode for p in runs] == [0] * 5 + [2], [p.stderr for p in runs]
    assert UNENFORCED not in runs[5].stderr and "beyond limit (6/5)" in runs[5].stderr, runs[5].stderr
    assert json.loads(s.streak().read_text())["bash_consecutive"] == {"last_tool": "Bash", "count": 6}
    assert s.state.stat().st_mode & 0o777 == 0o700


def test_uncounted_tools_pass_whatever_the_record(tmp_path):
    s = Session(tmp_path)
    s.streak().write_text("")
    assert s.gate("Read", {"file_path": "/etc/hostname"}).returncode == 0
    assert s.gate("Agent", {"subagent_type": "x", "prompt": "x", "run_in_background": False}).returncode == 0
    assert s.streak().read_text() == "", "an unreadable record is never replaced by a fresh one"


# 2./3. the owner's prompts ---------------------------------------------------------------------------

@unprivileged
def test_do_consent_that_cannot_be_recorded_blocks_the_prompt(readonly):
    p = readonly.prompt("/do run the probe")
    assert p.returncode == 2, p
    _names_cause(p.stderr, readonly.state / f"claude-orchestrator-consent-{readonly.sid}.flag", "Permission denied")
    assert "not granted" in p.stderr


@unprivileged
@pytest.mark.parametrize("command", ["commit", "stop"])
def test_intent_mark_that_cannot_be_written_blocks_the_prompt(readonly, command):
    p = readonly.prompt(f"/{command}")
    assert p.returncode == 2, p
    _names_cause(p.stderr, readonly.state / f"claude-{command}-userintent-{readonly.sid}.flag", "Permission denied")


# 4. the writers --------------------------------------------------------------------------------------

def _allowlist(state: Path):
    os.environ["CLAUDE_STATE_DIR"] = str(state)
    sys.path.insert(0, str(HOOKS))
    try:
        import importlib
        import lib.allowlist as allowlist
        return importlib.reload(allowlist)
    finally:
        sys.path.pop(0)


@unprivileged
def test_writers_raise_on_an_unwritable_dir(readonly, monkeypatch):
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(readonly.state))
    allowlist = _allowlist(readonly.state)
    for write in (lambda: allowlist.write_tool_streak(readonly.sid, {"schema_version": 2}),
                  lambda: allowlist.record_tool_ran(readonly.sid, "toolu_1")):
        with pytest.raises(OSError):
            write()
    assert readonly.entries() == []
    p = readonly.run(RAN, readonly.payload("PostToolUse", tool_name="Bash", tool_use_id="toolu_1"))
    assert p.returncode == 1, p
    _names_cause(p.stderr, readonly.state / f"claude-tool-ran-{readonly.sid}.log", "Permission denied")


# The full-volume cases run in one process inside the namespace: a 64 KiB tmpfs over the test's own
# directory, filled, then the hooks and writers against it; the results come back as JSON.
FULL = textwrap.dedent(r"""
    import json, os, subprocess, sys
    full, hooks, sid, transcript, project = sys.argv[1:6]
    subprocess.run(["mount", "-t", "tmpfs", "-o", "size=64k", "none", full], check=True)
    # A log that already holds a call, of a second session: the prompts' reset of this session's turn
    # state would free its page.
    log = os.path.join(full, f"claude-tool-ran-{sid}x.log")
    with open(log, "w") as f:
        f.write("toolu_0\n")
    with open(os.path.join(full, "fill"), "wb", buffering=0) as f:
        try:
            while True:
                f.write(b"\0" * 4096)
        except OSError:
            pass
    env = dict(os.environ, CLAUDE_STATE_DIR=full)
    def run(hook, body, session=sid):
        body.update(session_id=session, transcript_path=transcript, cwd=project, permission_mode="default")
        p = subprocess.run([sys.executable, os.path.join(hooks, hook)], input=json.dumps(body),
                           capture_output=True, text=True, env=env, cwd=project, timeout=60)
        return [p.returncode, p.stdout, p.stderr]
    out = {"gate": [run("pretool-orchestrator-gate.py", {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                    "tool_input": {"command": "python3 x.py"}, "tool_use_id": f"toolu_{i}"}) for i in range(8)]}
    out["do"] = run("prompt-workflow.py", {"hook_event_name": "UserPromptSubmit", "prompt": "/do run the probe"})
    out["commit"] = run("prompt-workflow.py", {"hook_event_name": "UserPromptSubmit", "prompt": "/commit"})
    out["ran"] = run("posttool-orchestrator-ran.py", {"hook_event_name": "PostToolUse", "tool_name": "Bash",
                     "tool_use_id": "toolu_" + "9" * 5000}, sid + "x")
    sys.path.insert(0, hooks)
    from lib import allowlist
    try:
        allowlist.write_sentinel_grant("t1", sid, [{"op": "git"}])
        out["grant"] = "written"
    except OSError as e:
        out["grant"] = str(e)
    os.unlink(os.path.join(full, "fill"))
    out["entries"] = {n: os.path.getsize(os.path.join(full, n)) for n in os.listdir(full)}
    for d, _, files in os.walk(full):
        for n in files:
            out["entries"].setdefault(os.path.relpath(os.path.join(d, n), full), os.path.getsize(os.path.join(d, n)))
    with open(log) as f:
        out["ran_log"] = f.read()
    print(json.dumps(out))
""")


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("full")
    s = Session(tmp, state=tmp / "state")
    way = _private_ns.require("the full-volume cases")
    p = subprocess.run(_private_ns.unshare_argv(way, s.env(), [sys.executable, "-c", FULL, str(s.state), str(HOOKS),
                                                               s.sid, str(s.transcript), str(s.project)]),
                       capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p
    return s, json.loads(p.stdout.splitlines()[-1])


def test_full_volume_gate_refuses_every_counted_call(full):
    s, out = full
    assert [rc for rc, _, _ in out["gate"]] == [2] * 8
    for _, _, err in out["gate"]:
        _names_cause(err, s.streak(), "No space left on device")
        assert UNENFORCED in err


def test_full_volume_do_and_commit_block_the_prompt(full):
    s, out = full
    for key, name in (("do", f"claude-orchestrator-consent-{s.sid}.flag"),
                      ("commit", f"claude-commit-userintent-{s.sid}.flag")):
        rc, _, err = out[key]
        assert rc == 2, out[key]
        _names_cause(err, s.state / name, "No space left on device")
        assert name not in out["entries"], f"{name} left behind"


def test_full_volume_writers_leave_nothing_half_written(full):
    s, out = full
    rc, _, err = out["ran"]
    assert rc == 1 and "No space left on device" in err, out["ran"]
    assert out["ran_log"] == "toolu_0\n", "a failed append is cut back to what the log held"
    assert "No space left on device" in out["grant"]
    stray = {n: size for n, size in out["entries"].items() if n != f"claude-tool-ran-{s.sid}x.log"}
    assert all(not n.endswith(".flag") and ".tmp." not in n and not n.endswith(".json") for n in stray), stray


# 5. a writable state dir: as before --------------------------------------------------------------------

def test_writable_state_is_unchanged(tmp_path):
    """The cases the existing tests pin, with the exact texts and entries the hooks gave before."""
    s = Session(tmp_path)
    runs = [s.gate() for _ in range(6)]
    assert [(p.returncode, p.stdout) for p in runs] == [(0, "")] * 5 + [(2, "")]
    assert [p.stderr for p in runs[:5]] == [""] * 5
    assert runs[5].stderr == (
        "[Orchestrator Gate] BLOCKED: Bash used consecutively beyond limit (6/5): Bash counts its calls since "
        "the last Agent dispatch or prompt, any other non-whitelisted tool its calls this turn, whatever ran "
        "between them.\nDelegate to a subagent (Agent tool) or ask the user to run /do to unlock.\n")
    record = json.loads(s.streak().read_text())
    assert record["bash_consecutive"] == {"last_tool": "Bash", "count": 6}
    assert s.streak().read_text() == json.dumps(record)
    # A foreground dispatch resets the count; a background launch resets nothing (the owner's decision of 2026-11-21).
    agent = s.gate("Agent", {"subagent_type": "x", "prompt": "x", "run_in_background": False})
    assert (agent.returncode, agent.stdout, agent.stderr) == (0, "", "")
    assert json.loads(s.streak().read_text())["bash_consecutive"] == {"last_tool": "Agent", "count": 0}
    edit = [s.gate("Edit", {"file_path": str(s.project / "a"), "old_string": "a", "new_string": "b"})
            for _ in range(2)]
    assert [p.returncode for p in edit] == [0, 2]
    ran = s.run(RAN, s.payload("PostToolUse", tool_name="Bash", tool_use_id="toolu_r"))
    assert (ran.returncode, ran.stdout, ran.stderr) == (0, "", "")
    assert (s.state / f"claude-tool-ran-{s.sid}.log").read_text() == "toolu_r\n"
    do = s.prompt("/do run the probe")
    assert do.returncode == 0 and do.stderr == "", do
    assert "[/do] Consent granted. Main agent may now perform direct operations this turn.\n" in do.stdout
    assert re.search(r"\[/do\] task-id minted: \d{8}-\d{6} — resolve via", do.stdout)
    assert (s.state / f"claude-orchestrator-consent-{s.sid}.flag").read_text() == "true"
    sidecar = json.loads((s.state / f"claude-do-task-{s.sid}.json").read_text())
    assert set(sidecar) == {"task_id", "session_id", "created_at"} and sidecar["session_id"] == s.sid
    commit = s.prompt("/commit")
    assert commit.returncode == 0 and commit.stderr == "", commit
    assert (s.state / f"claude-commit-userintent-{s.sid}.flag").read_text() == "true"
    assert not s.streak().exists(), "the prompt reset removes the record"
    assert not [n for n in s.entries() if ".tmp." in n]
