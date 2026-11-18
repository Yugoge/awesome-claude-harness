"""OB-L04: a main-agent write into the session's own scratch directory does not use the turn's one write.

hooks/pretool-orchestrator-gate.py allows the main agent one call per non-whitelisted tool name per
turn, so a turn that wrote docs/report.md could not then jot notes into its own scratch directory:
the second Write was refused. The owner decided that a Write, Edit, MultiEdit or NotebookEdit of a
file inside the session's scratch directory passes uncounted. The scratch directory is the harness's
<TMPDIR>/<sid> (hooks/session-scratch-init.sh, its .owner naming the session) or the CLI's
<CLAUDE_CODE_TMPDIR>/claude-<uid>/<project>/<sid>/scratchpad. The file is resolved through every
symlink; anything that is not plainly a file of that directory counts: a project file (a gate-read
artifact such as docs/dev/qa-report-*.json included, however it is reached), a `..` path, a hard
link, the harness's own files in the scratch directory, a harness state file, another session's
scratch, the TMPDIR root, or a scratch directory that holds or sits in a directory the harness reads.

Gate cases run the gate (and, for the registered pipeline, hooks/pretool-launch.py) as a subprocess
with the PreToolUse payload the CLI sends; HOME, state dir, project and TMPDIR live in tmp_path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "hooks" / "pretool-orchestrator-gate.py"
LAUNCH = ROOT / "hooks" / "pretool-launch.py"
REFUSED = "used consecutively beyond limit"


class Session:
    def __init__(self, tmp_path: Path, state: Path | None = None, project: Path | None = None):
        self.tmp, self.sid = tmp_path, str(uuid.uuid4())
        self.home = tmp_path / "home"
        self.project = project or tmp_path / "project"
        self.state = state or tmp_path / "state"
        self.tmpdir = tmp_path / "tmp"
        self.cli_tmp = tmp_path / "cli"
        for d in (self.project / ".claude", self.project / "src", self.project / "docs" / "dev", self.state,
                  self.tmpdir):
            d.mkdir(parents=True, exist_ok=True)
        (self.project / "src" / "a.py").write_text("x = 1\n")
        tdir = self.home / ".claude" / "projects" / "-project"
        tdir.mkdir(parents=True)
        self.transcript = tdir / f"{self.sid}.jsonl"
        self.transcript.write_text(json.dumps(
            {"type": "user", "message": {"role": "user", "content": "write the report"}}) + "\n")
        self.n = 0

    def harness_scratch(self, owner: str | None = None) -> Path:
        """<TMPDIR>/<sid>, as hooks/session-scratch-init.sh creates it."""
        d = self.tmpdir / self.sid
        d.mkdir(exist_ok=True)
        (d / ".owner").write_text(json.dumps({"sid": owner or self.sid, "pid": "1"}))
        return d

    def cli_scratch(self) -> Path:
        d = self.cli_tmp / f"claude-{os.getuid()}" / "-project" / self.sid / "scratchpad"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def run(self, tool: str, path, hook: Path = GATE, env_extra: dict | None = None, proc_cwd: Path | None = None,
            **payload) -> subprocess.CompletedProcess:
        self.n += 1
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
               "CLAUDE_HOME": str(ROOT), "CLAUDE_STATE_DIR": str(self.state), "TMPDIR": str(self.tmpdir),
               "CLAUDE_CODE_TMPDIR": str(self.cli_tmp), "CLAUDE_PROJECT_DIR": str(self.project),
               "GIT_CEILING_DIRECTORIES": str(self.tmp), "PYTHONDONTWRITEBYTECODE": "1", **(env_extra or {})}
        key = "notebook_path" if tool == "NotebookEdit" else "file_path"
        tool_input = {key: str(path)}
        if tool == "Write":
            tool_input["content"] = "notes\n"
        elif tool == "Edit":
            tool_input.update(old_string="x", new_string="y")
        elif tool == "MultiEdit":
            tool_input["edits"] = [{"old_string": "x", "new_string": "y"}]
        else:
            tool_input.update(new_source="y = 2", cell_id="c1")
        body = {"session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(self.project),
                "hook_event_name": "PreToolUse", "permission_mode": "default", "tool_name": tool,
                "tool_use_id": f"toolu_{self.n:04d}", "tool_input": tool_input, **payload}
        return subprocess.run([sys.executable, str(hook)], input=json.dumps(body), capture_output=True,
                              text=True, env=env, cwd=proc_cwd or self.project, timeout=120)

    def allowed(self, tool: str, path, **kw) -> bool:
        p = self.run(tool, path, **kw)
        assert p.returncode in (0, 2), (p.returncode, p.stdout, p.stderr)
        if p.returncode == 2:
            assert REFUSED in p.stderr, p.stderr
        return p.returncode == 0

    def spend(self, tool: str, **kw) -> None:
        """The turn's one call of tool, on a project file."""
        assert self.allowed(tool, "docs/report.md" if tool == "Write" else self.project / "src" / "a.py", **kw)


SCRATCH_KINDS = ["harness", "cli"]


def _scratch(s: Session, kind: str) -> Path:
    return s.harness_scratch() if kind == "harness" else s.cli_scratch()


@pytest.mark.parametrize("kind", SCRATCH_KINDS)
def test_report_then_scratch_notes_in_one_turn(tmp_path, kind):
    """AUDIT.md section 2 OB-L04 must-pass: Write docs/report.md, then Write <scratch>/notes.md."""
    s = Session(tmp_path)
    scratch = _scratch(s, kind)
    assert s.allowed("Write", "docs/report.md")
    assert s.allowed("Write", scratch / "notes.md")
    assert s.allowed("Write", scratch / "more.md"), "a second scratch write"
    assert s.allowed("Write", scratch / "sub" / "third.md"), "a third scratch write"
    (scratch / "notes.md").write_text("x\n")
    assert s.allowed("Edit", scratch / "notes.md")
    assert s.allowed("Edit", scratch / "notes.md")
    assert s.allowed("MultiEdit", scratch / "notes.md")
    assert s.allowed("NotebookEdit", scratch / "n.ipynb")
    assert not s.allowed("Write", "docs/other.md"), "the project write is still one per turn"


@pytest.mark.parametrize("kind", SCRATCH_KINDS)
@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_scratch_writes_neither_spend_nor_refill_the_project_write(tmp_path, kind, tool):
    s = Session(tmp_path)
    scratch = _scratch(s, kind)
    (scratch / "notes.md").write_text("x\n")
    for _ in range(3):
        assert s.allowed(tool, scratch / ("new.md" if tool == "Write" else "notes.md"))
    state_file = s.state / f"claude-tool-streak-{s.sid}.json"
    assert not state_file.exists(), "a scratch write writes no count"
    s.spend(tool)
    assert s.allowed(tool, scratch / ("new2.md" if tool == "Write" else "notes.md"))
    assert not s.allowed(tool, "docs/x.md" if tool == "Write" else s.project / "src" / "a.py")


@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit", "NotebookEdit"])
def test_second_project_source_write_still_refused(tmp_path, tool):
    s = Session(tmp_path)
    _scratch(s, "harness")
    assert s.allowed(tool, s.project / "src" / "b.py")
    assert not s.allowed(tool, s.project / "src" / "c.py")


def _bad_targets(s: Session):
    """(name, target path, env_extra) the gate must count, each after a spent Write/Edit."""
    h = s.harness_scratch()
    c = s.cli_scratch()
    dev = s.project / "docs" / "dev"
    (dev / "qa-report-1.json").write_text("{}")
    (h / "dev").symlink_to(dev)
    (c / "src").symlink_to(s.project / "src")
    (c / "qa.json").symlink_to(dev / "qa-report-1.json")
    os.link(s.project / "src" / "a.py", h / "hard.py")
    other = s.tmpdir / "other-session"
    other.mkdir()
    (other / ".owner").write_text(json.dumps({"sid": "other-session"}))
    (h / "doc-sync-notices-main.json").write_text("{}")
    (h / "state").mkdir()
    return [
        ("gate-read artifact", dev / "qa-report-2.json", None),
        ("existing gate-read artifact", dev / "qa-report-1.json", None),
        ("relative gate-read artifact", "docs/dev/qa-report-3.json", None),
        ("artifact via scratch dir symlink", h / "dev" / "qa-report-4.json", None),
        ("existing artifact via scratch dir symlink", h / "dev" / "qa-report-1.json", None),
        ("artifact via scratch file symlink", c / "qa.json", None),
        ("source via scratch dir symlink", c / "src" / "a.py", None),
        ("dot-dot out of scratch", f"{h}/../../project/docs/dev/qa-report-5.json", None),
        ("dot-dot inside scratch", f"{h}/sub/../notes.md", None),
        ("relative dot-dot", f"../{s.tmpdir.name}/{s.sid}/notes.md", None),
        ("hard link to source", h / "hard.py", None),
        ("scratch owner record", h / ".owner", None),
        ("doc-sync notice state", h / "doc-sync-notices-main.json", None),
        ("harness state file", s.state / f"claude-tool-streak-{s.sid}.json", None),
        ("harness state dir entry", s.state / "claude-grants" / "x.json", None),
        ("another session's scratch", other / "notes.md", None),
        ("TMPDIR root", s.tmpdir / "notes.md", None),
        ("CLI tree outside the scratchpad", c.parent / "notes.md", None),
        ("scratch dir itself", h, None),
        ("state dir inside scratch", h / "notes.md", {"CLAUDE_STATE_DIR": str(h / "state")}),
        ("project inside scratch", c / "notes.md", {"CLAUDE_PROJECT_DIR": str(c / "proj")}),
        ("grant dir is the scratch", h / "claude-allow-daemon-restart-x", {"CLAUDE_DAEMON_RESTART_GRANT_DIR": str(h)}),
    ]


@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_must_still_refuse(tmp_path, tool):
    names = [name for name, _, _ in _bad_targets(Session(tmp_path / "probe"))]
    for i, name in enumerate(names):
        s = Session(tmp_path / f"case{i}")
        target, env_extra = next((t, e) for n, t, e in _bad_targets(s) if n == name)
        s.spend(tool, env_extra=env_extra)
        if tool == "Write" and Path(s.project, target).is_file():
            continue  # a Write over an existing file is the base's write-guard skip, refused there; Edit covers it
        assert not s.allowed(tool, target, env_extra=env_extra), name


def test_scratch_dir_that_is_a_symlink_to_the_project_counts(tmp_path):
    s = Session(tmp_path)
    pad = s.cli_tmp / f"claude-{os.getuid()}" / "-project" / s.sid
    pad.mkdir(parents=True)
    (pad / "scratchpad").symlink_to(s.project / "docs" / "dev")
    s.spend("Write")
    assert not s.allowed("Write", pad / "scratchpad" / "qa-report-9.json")


@pytest.mark.parametrize("owner", [None, "someone-else"])
def test_harness_scratch_needs_this_sessions_owner_record(tmp_path, owner):
    s = Session(tmp_path)
    d = s.harness_scratch(owner or "x")
    if owner is None:
        (d / ".owner").unlink()
    s.spend("Write")
    assert not s.allowed("Write", d / "notes.md")


@pytest.mark.parametrize("payload", [{"session_id": ""}, {"session_id": ".."}, {"cwd": "relative"}, {"cwd": None}])
def test_unusable_payload_counts(tmp_path, payload):
    s = Session(tmp_path)
    scratch = s.harness_scratch()
    target = "notes.md" if "cwd" in payload else scratch / "notes.md"
    assert s.allowed("Write", s.project / "docs" / "r.md", **payload)
    assert not s.allowed("Write", target, **payload)


def test_relative_path_resolves_against_payload_cwd_not_the_hooks(tmp_path):
    s = Session(tmp_path)
    scratch = s.harness_scratch()
    s.spend("Write")
    assert not s.allowed("Write", "notes.md", proc_cwd=scratch)


def test_cwd_inside_scratch_counts(tmp_path):
    """The payload's cwd is where gates look for the project: a scratch directory holding it is no scratch."""
    s = Session(tmp_path)
    scratch = s.harness_scratch()
    assert s.allowed("Write", "notes.md", cwd=str(scratch))
    assert not s.allowed("Write", "notes2.md", cwd=str(scratch))


def test_registered_pipeline(tmp_path):
    """Through hooks/pretool-launch.py, the PreToolUse hook settings.json registers for every tool."""
    s = Session(tmp_path)
    scratch = s.cli_scratch()
    p = s.run("Write", "docs/report.md", hook=LAUNCH)
    assert REFUSED not in p.stderr + p.stdout, (p.stdout, p.stderr)
    for name in ("notes.md", "more.md"):
        p = s.run("Write", scratch / name, hook=LAUNCH)
        assert REFUSED not in p.stderr + p.stdout, (p.stdout, p.stderr)
    p = s.run("Write", "docs/dev/qa-report-1.json", hook=LAUNCH)
    assert REFUSED in p.stderr + p.stdout, (p.stdout, p.stderr)
