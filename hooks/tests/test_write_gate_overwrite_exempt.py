"""OB-L46: a Write may replace scratch, temp and untracked output; tracked, config, state, gate-read stay refused.

Each case runs the rule (lib/write_gate/overwrite.py) as a process on an architect subagent's Write
payload, under a throwaway HOME and state dir, so a refusal is the overwrite guard's own (tool-policy
denies every role a write under /tmp, where pytest's tmp_path lives). Each allowed case also runs
through the registered gate (hooks/pretool-write-gate.py) on the main agent's payload, which no
role policy narrows. CRITIQUE A5: the architect has Write but no Edit, so a refused second Write
onto its own untracked output was a dead end; that case is pinned here.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "hooks" / "pretool-write-gate.py"
RULE = ROOT / "hooks" / "lib" / "write_gate" / "overwrite.py"
SID = "sess-ob-l46"


@pytest.fixture
def lab(tmp_path):
    home, state, proj = tmp_path / "home", tmp_path / "state", tmp_path / "proj"
    for d in (home, state, tmp_path / "scratch-root", proj / "src", proj / ".claude", proj / "docs" / "dev" / "specs"):
        d.mkdir(parents=True, exist_ok=True)
    git = ["git", "-C", str(proj), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    (proj / "src" / "app.py").write_text("print('app')\n")
    (proj / "config.toml").write_text("a = 1\n")
    (proj / ".claude" / "settings.json").write_text("{}\n")
    subprocess.run(git + ["add", "src/app.py", "config.toml", ".claude/settings.json"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "base"], check=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "GIT_"))}
    env.update(HOME=str(home), CLAUDE_STATE_DIR=str(state), CLAUDE_HOME=str(ROOT),
               CLAUDE_PROJECT_DIR=str(proj), PYTHONDONTWRITEBYTECODE="1",
               TMPDIR=str(tmp_path / "scratch-root"))  # the session scratch root, as in use
    return {"tmp": tmp_path, "home": home, "state": state, "proj": proj, "env": env}


def _write(lab, path: Path, agent: str | None = "architect", script: Path = RULE):
    d = {"tool_name": "Write", "session_id": SID, "hook_event_name": "PreToolUse",
         "tool_input": {"file_path": str(path), "content": "second draft\n"}}
    if agent:
        d.update(agent_id="a-" + agent, agent_type=agent)
    p = subprocess.run([sys.executable, str(script)], input=json.dumps(d), capture_output=True,
                       text=True, env=lab["env"], cwd=lab["proj"], timeout=60)
    return p.returncode, p.stdout + p.stderr


def _refused(result) -> bool:
    """The overwrite guard's own refusal."""
    rc, out = result
    return rc == 2 and "[Write Guard] BLOCKED: File already exists" in out


def _passes(lab, path: Path) -> bool:
    """Allowed by the rule for the architect, and by the whole gate for the main agent."""
    rc, out = _write(lab, path)
    grc, gout = _write(lab, path, agent=None, script=GATE)
    return rc == 0 and grc == 0 and '"deny"' not in gout


def _existing(path: Path, text: str = "first draft\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _session_scratch(lab) -> Path:
    """$TMPDIR/<sid>/ with the .owner hooks/session-scratch-init.sh writes."""
    d = lab["tmp"] / "scratch-root" / SID
    _existing(d / ".owner", json.dumps({"sid": SID}))
    return d


# --- must pass ---------------------------------------------------------------------------------

def test_overwrite_of_session_scratch_report_passes(lab):
    assert _passes(lab, _existing(_session_scratch(lab) / "report.md"))


def test_overwrite_of_a_temp_file_that_is_not_harness_state_passes(lab):
    assert _passes(lab, _existing(lab["tmp"] / "work" / "notes.txt"))


def test_architect_rewrites_its_own_untracked_output(lab):
    """CRITIQUE A5: the architect (Write, no Edit) Writes docs/dev/arch-probe.md, then Writes it
    again: the second Write must pass, or the role has no way to revise its own draft."""
    probe = lab["proj"] / "docs" / "dev" / "arch-probe.md"
    assert _write(lab, probe)[0] == 0  # the first Write creates it
    _existing(probe)
    assert _passes(lab, probe)  # the second Write replaces it


@pytest.mark.parametrize("where", ["docs/codex/arch-probe.md", ".claude/scratch/arch-probe.md"])
def test_architect_rewrites_output_at_its_own_prefixes(lab, where):
    assert _passes(lab, _existing(lab["proj"] / where))


def test_role_scratch_under_claude_scratch_passes(lab):
    assert _passes(lab, _existing(lab["state"] / "claude-scratch" / "architect" / "probe.md"))


def test_untracked_rule_alone(lab, monkeypatch):
    """The untracked rule is not the temp rule in disguise: with the temp rule switched off, an
    untracked output in a work tree is still exempt, and a dot-named file or a file outside any
    work tree is not."""
    sys.path.insert(0, str(ROOT / "hooks" / "lib" / "write_gate"))
    sys.path.insert(0, str(ROOT / "hooks" / "lib"))
    import importlib
    import harness_temp_state
    overwrite = importlib.import_module("overwrite")
    monkeypatch.setattr(harness_temp_state, "is_in_temp_root", lambda *a, **k: False)
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(lab["state"]))
    proj = lab["proj"]
    assert overwrite.overwrite_exempt(str(_existing(proj / "docs" / "dev" / "arch-probe.md")), SID)
    assert overwrite.overwrite_exempt(str(_existing(proj / "build" / "out.txt")), SID)
    assert overwrite.overwrite_exempt(str(_existing(proj / ".claude" / "scratch" / "n.md")), SID)
    assert not overwrite.overwrite_exempt(str(_existing(proj / ".claude" / "notes.md")), SID)
    assert not overwrite.overwrite_exempt(str(_existing(proj / "docs" / "dev" / "qa-report-1.json")), SID)
    assert not overwrite.overwrite_exempt(str(proj / "src" / "app.py"), SID)
    assert not overwrite.overwrite_exempt(str(_existing(proj / ".env")), SID)
    assert not overwrite.overwrite_exempt(str(_existing(proj / ".vscode" / "x.json")), SID)
    outside = _existing(lab["tmp"] / "no-repo" / "f.txt")
    assert not overwrite.overwrite_exempt(str(outside), SID)


# --- must still refuse -------------------------------------------------------------------------

def test_tracked_source_still_refused(lab):
    assert _refused(_write(lab, lab["proj"] / "src" / "app.py"))


def test_claude_settings_still_refused_tracked_or_not(lab):
    settings = lab["proj"] / ".claude" / "settings.json"
    assert _refused(_write(lab, settings))
    subprocess.run(["git", "-C", str(lab["proj"]), "rm", "-q", "--cached", ".claude/settings.json"],
                   check=True)
    assert _refused(_write(lab, settings))


def test_tracked_config_still_refused_even_same_length(lab):
    cfg = lab["proj"] / "config.toml"
    cfg.write_text("a = 2\n")  # same length, modified in the work tree: still tracked
    assert _refused(_write(lab, cfg))


def test_staged_new_file_counts_as_tracked(lab):
    f = _existing(lab["proj"] / "src" / "new_mod.py")
    subprocess.run(["git", "-C", str(lab["proj"]), "add", "src/new_mod.py"], check=True)
    assert _refused(_write(lab, f))


@pytest.mark.parametrize("name", [
    "claude-grants/sess-ob-l46.json",
    "claude-orchestrator-consent-sess-ob-l46.flag",
    "claude-tool-streak-sess-ob-l46.json",
])
def test_harness_state_under_temp_still_refused(lab, name):
    assert _refused(_write(lab, _existing(lab["state"] / name, "{}\n")))


def test_session_scratch_owner_record_still_refused(lab):
    assert _refused(_write(lab, _session_scratch(lab) / ".owner"))


@pytest.mark.parametrize("name", ["dev-output-1.json", "checkpoint-result.1.2", "runtime-guard-ab"])
def test_harness_process_scratch_still_refused(lab, name):
    """Scratch a harness process writes and reads back is not an agent's scratch."""
    assert _refused(_write(lab, _existing(lab["state"] / name)))


@pytest.mark.parametrize("rel", [
    "docs/dev/dev-report-20261117-000000.json",
    "docs/dev/qa-report-x.json",
    "docs/dev/producer-question-t-architect.json",
    "docs/dev/ticket-20261117-000000.md",
    "docs/dev/user-requirement-sess.md",
    "docs/dev/close-report-t.md",
    "docs/dev/completion-t.md",
    "docs/dev/specs/spec-20261117-000000.md",
    "docs/dev/overnight/s/spec-pipeline-1.md",
])
def test_gate_read_artifact_still_refused(lab, rel):
    """Untracked (docs/dev is ignored or never committed) yet another gate reads it as evidence."""
    assert _refused(_write(lab, _existing(lab["proj"] / rel)))


def test_symlink_in_temp_onto_a_tracked_file_still_refused(lab):
    link = lab["tmp"] / "work" / "alias.py"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(lab["proj"] / "src" / "app.py")
    assert _refused(_write(lab, link))


def test_the_refusal_message_is_unchanged(lab):
    rc, err = _write(lab, lab["proj"] / "src" / "app.py")
    assert rc == 2 and err.startswith("[Write Guard] BLOCKED: File already exists: ")
    assert "Reserve Write for files that genuinely do not exist yet." in err
