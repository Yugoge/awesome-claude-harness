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
import re
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


# --- verifier bypasses (each refused) ----------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "docs/dev/commit-qa-report-T1.md",
    "docs/dev/commit-qa-report-bulk.md",
    "docs/clean/cleanliness-report-R1.json",
    "docs/clean/style-partial-R1-group-G1.json",
    "docs/clean/prompt-report-R1.json",
    "docs/clean/cleanup-execution-R1.json",
    "docs/clean/context-R1.json",
    "tests/generated/T1/manifest.json",
    "tests/generated/T1/test_AC1.py",
    "docs/test/edge-case-analysis.json",
    "docs/dev/overnight-summary-2026-11-17.md",
    "docs/dev/ba-spec-T1.md",
])
def test_more_gate_read_families_still_refused(lab, rel):
    assert _refused(_write(lab, _existing(lab["proj"] / rel)))


def _agent_scratch_link(lab, name: str, target: Path) -> Path:
    link = lab["state"] / "claude-scratch" / "architect" / name
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    return link


def test_agent_scratch_symlink_to_a_file_outside_repo_and_temp_refused(lab, monkeypatch):
    """P1: the scratch exemption is decided on the realpath, not the link's own entry."""
    outside = Path("/dev/shm")
    if not (outside.is_dir() and os.access(outside, os.W_OK)):
        pytest.skip("no writable directory outside every temp root")
    d = Path(os.path.realpath(outside)) / f"ob-l46-{os.getpid()}-{lab['tmp'].name}"
    d.mkdir()
    try:
        target = _existing(d / "notes.txt")
        assert _refused(_write(lab, _agent_scratch_link(lab, "link-out", target)))
    finally:
        for p in sorted(d.rglob("*"), reverse=True):
            p.unlink()
        d.rmdir()


def test_agent_scratch_symlink_to_repo_dotenv_refused(lab):
    """P2."""
    env = _existing(lab["proj"] / ".env")
    assert _refused(_write(lab, _agent_scratch_link(lab, "link-env", env)))


def test_agent_scratch_symlink_to_control_state_refused(lab):
    state = _existing(lab["state"] / f"claude-tool-streak-{SID}.json", "{}\n")
    assert _refused(_write(lab, _agent_scratch_link(lab, "link-state", state)))


def test_another_sessions_scratch_refused(lab):
    """P5: one session never overwrites another session's scratch."""
    other = lab["state"] / "claude-scratch" / "other-sess"
    _existing(other / ".owner", json.dumps({"sid": "other-sess"}))
    assert _refused(_write(lab, _existing(other / "report.md")))
    other_tmp = lab["tmp"] / "scratch-root" / "other-sess"
    _existing(other_tmp / ".owner", json.dumps({"sid": "other-sess"}))
    assert _refused(_write(lab, _existing(other_tmp / "report.md")))


def test_forged_own_scratch_outside_the_scratch_roots_is_not_own(lab, monkeypatch):
    """P11/P11b: a <sid>/.owner forged anywhere is not this session's scratch."""
    sys.path.insert(0, str(ROOT / "hooks" / "lib" / "write_gate"))
    sys.path.insert(0, str(ROOT / "hooks" / "lib"))
    import harness_temp_state
    import overwrite_scope
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(lab["state"]))
    monkeypatch.setenv("TMPDIR", str(lab["tmp"] / "scratch-root"))
    forged = lab["proj"] / SID
    _existing(forged / ".owner", json.dumps({"sid": SID}))
    f = _existing(forged / "f.txt")
    assert not overwrite_scope._own_scratch(os.path.realpath(f), SID, harness_temp_state)
    real = _existing(lab["tmp"] / "scratch-root" / SID / "r.md")
    _existing(real.parent / ".owner", json.dumps({"sid": SID}))
    assert overwrite_scope._own_scratch(os.path.realpath(real), SID, harness_temp_state)
    assert _refused(_write(lab, _existing(forged / ".env")))


def test_docs_dev_symlinked_into_temp_still_refused(lab):
    """P12: the gate-read rule is checked on the path as written too."""
    devdir = lab["tmp"] / "work" / "devdir"
    devdir.mkdir(parents=True)
    proj2 = lab["tmp"] / "proj2"
    (proj2 / "docs").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(proj2)], check=True)
    (proj2 / "docs" / "dev").symlink_to(devdir)
    _existing(devdir / "qa-report-T9.json", "{}\n")
    assert _refused(_write(lab, proj2 / "docs" / "dev" / "qa-report-T9.json"))


@pytest.mark.parametrize("name", [":x", "a*b", ":(glob)*"])
def test_tracked_file_with_pathspec_magic_in_its_name_refused(lab, name):
    """P9: the tracked check matches the name literally."""
    f = _existing(lab["proj"] / "src" / name)
    subprocess.run(["git", "-C", str(lab["proj"]), "add", "--", f"src/{name}"], check=True,
                   env={**os.environ, "GIT_LITERAL_PATHSPECS": "1"})
    assert _refused(_write(lab, f))


def test_hardlink_in_temp_to_a_tracked_file_refused(lab):
    """P10: a file with more than one hard link is never exempt."""
    link = lab["tmp"] / "work" / "hardlink-app.py"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(lab["proj"] / "src" / "app.py", link)
    except OSError:
        pytest.skip("hard links unsupported here")
    assert _refused(_write(lab, link))


# --- the gate-read set is pinned against what the harness declares and reads ------------------

_DECL = re.compile(r'"kind"\s*:\s*"[a-z_-]+"\s*,\s*"path"\s*:\s*"([^"\\]+)')
_TEMPLATED = re.compile(r"(?:docs|tests)/[a-z_-]+/[A-Za-z0-9_.{}<>$*/-]*[<{$*][A-Za-z0-9_.{}<>$*/-]*")
# docs/ and tests/ directories whose templated files no gate, command or step script reads as
# evidence: codex output kept for the human (commands/codex.md) and /clean's archive.
_NOT_ARTIFACT_DIRS = ("docs/codex/", "docs/archive/")
_PLACEHOLDER = re.compile(r"<[^<>]*>|\{[^{}]*\}|\$\{[^{}]*\}|\$[A-Za-z_]+|\*")


def _harness_sources():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "commands", "templates", "agents",
                          "skills", "hooks", "scripts"], capture_output=True, text=True, check=True)
    for rel in out.stdout.splitlines():
        if re.search(r"(^|/)tests?/", rel) or rel.endswith(("INDEX.md", "README.md")):
            continue
        p = ROOT / rel
        if p.suffix in (".md", ".py", ".sh", ".json") and p.is_file():
            yield rel, p.read_text(errors="replace")


def _concrete(path: str) -> str:
    path = _PLACEHOLDER.sub("T1", path).rstrip("/.")
    return path if "." in path.rsplit("/", 1)[-1] else path + "/x.json"


def _gate_read(rel_path: str) -> bool:
    sys.path.insert(0, str(ROOT / "hooks" / "lib" / "write_gate"))
    import overwrite_scope
    return overwrite_scope.is_gate_read_artifact("/proj/" + rel_path)


def test_every_declared_obligation_artifact_is_gate_read():
    """Each artifact path a command, agent or hook declares in an obligation lies under an
    artifact root and is gate-read, so a new declared artifact cannot fall outside the set."""
    declared = {(rel, m.group(1)) for rel, text in _harness_sources() for m in _DECL.finditer(text)}
    assert len(declared) >= 30, "the scan found too few obligation declarations"
    missed = [(rel, path) for rel, path in declared if not _gate_read(_concrete(path))]
    assert not missed, missed


def test_every_templated_artifact_name_is_gate_read():
    """Each templated file name under docs/<dir>/ or tests/<dir>/ that a command, agent, hook or
    step script refers to is gate-read, but for the _NOT_ARTIFACT_DIRS."""
    refs = {(rel, m.group(0)) for rel, text in _harness_sources() for m in _TEMPLATED.finditer(text)
            if not m.group(0).startswith(_NOT_ARTIFACT_DIRS)}
    # A name that is nothing but a placeholder (docs/dev/<x>.md in a docstring) names no family.
    refs = {(rel, path) for rel, path in refs
            if not re.fullmatch(r"(<[^<>]*>|\{[^{}]*\})(\.[a-z]+)?", path.rsplit("/", 1)[-1])}
    assert len(refs) >= 100, "the scan found too few templated artifact names"
    missed = sorted({path for rel, path in refs if not _gate_read(_concrete(path))})
    assert not missed, missed


def test_a_draft_outside_every_family_is_not_gate_read():
    assert not _gate_read("docs/dev/arch-probe.md")
    assert not _gate_read("docs/clean/notes.md")
    assert _gate_read("docs/dev/commit-qa-report-T1.md")
    assert _gate_read("docs/test/edge-case-analysis.json")


# --- round 2: nested work trees, case, /test's reports, the harness home's scratch -------------

def _tracked_core(lab) -> Path:
    core = _existing(lab["proj"] / "src" / "core2.py", "core\n")
    subprocess.run(["git", "-C", str(lab["proj"]), "add", "src/core2.py"], check=True)
    return core


def test_nested_git_file_does_not_hide_the_projects_index(lab):
    """Route A: a new src/.git file pointing at another repository makes src/ a work tree of
    its own; a file the project tracks there stays refused."""
    core = _tracked_core(lab)
    other = lab["tmp"] / "other"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    (lab["proj"] / "src" / ".git").write_text(f"gitdir: {other / '.git'}\n")
    assert _refused(_write(lab, core))
    assert _refused(_write(lab, core, agent="dev"))


def test_git_init_in_a_subdirectory_does_not_hide_the_projects_index(lab):
    """Route B: `git init src` then a Write onto the tracked src/core2.py."""
    core = _tracked_core(lab)
    subprocess.run(["git", "init", "-q", str(lab["proj"] / "src")], check=True)
    assert _refused(_write(lab, core))
    assert _refused(_write(lab, core, agent="dev"))


@pytest.mark.parametrize("rel", [
    "docs/dev/Commit-QA-Report-T1.md",
    "Docs/Dev/qa-report-T1.json",
    "docs/clean/CLEANUP-EXECUTION-R1.json",
])
def test_gate_read_families_fold_case(lab, rel):
    assert _refused(_write(lab, _existing(lab["proj"] / rel)))


def test_dot_claude_folds_case(lab):
    assert _refused(_write(lab, _existing(lab["proj"] / ".Claude" / "settings.json", "{}\n")))


@pytest.mark.parametrize("rel", [
    "tests/reports/validator-registry-R1.json",
    "tests/reports/execution-context-R1.json",
    "tests/reports/completion-R1.md",
    "tests/scripts/validate-login.py",
    "tests/instructions/login.md",
])
def test_test_command_reports_and_validators_refused(lab, rel):
    assert _refused(_write(lab, _existing(lab["proj"] / rel)))


def test_harness_home_scratch_is_not_project_scratch(lab, monkeypatch, tmp_path):
    """The harness home's own .claude/scratch/ is not exempt; a project's is."""
    sys.path.insert(0, str(ROOT / "hooks" / "lib" / "write_gate"))
    sys.path.insert(0, str(ROOT / "hooks" / "lib"))
    import claude_home
    import overwrite_scope
    home = tmp_path / "hh" / ".claude"
    monkeypatch.setattr(claude_home, "resolve", lambda: home)
    f = _existing(home / "scratch" / "n.md")
    assert not overwrite_scope._in_project_scratch(os.path.realpath(f))
    assert not overwrite_scope.overwrite_exempt(str(f), SID)
    g = _existing(lab["proj"] / ".claude" / "scratch" / "n.md")
    assert overwrite_scope._in_project_scratch(os.path.realpath(g))
