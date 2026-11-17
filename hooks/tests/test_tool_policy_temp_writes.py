"""A policy role writes the temp roots, never the harness state kept there (owner decision, 2026-11-17).

hooks/pretool-tool-policy.py (run by the write gate, hooks/pretool-write-gate.py) used to refuse every
role's write into /tmp and /var/tmp: dev by the raw-temp rule, every other role by its allow prefixes.
It refused `>`, `>>`, cp, tee, heredocs and the Write and Edit tools, while curl -o, touch, mkdir and
awk `print >` passed. Now a write target qualifies as a temp write, and is allowed for every policy
role whose tool lists and deny prefixes allow the tool, when (lib/harness_temp_state.py is the one
definition of temp roots and harness state):

- it is spelled as an absolute path with no variable, glob or command substitution;
- both of its resolved views (its realpath and its entry) lie strictly below a temp root
  (/tmp, /var/tmp, $TMPDIR, $CLAUDE_TMPDIR, $CLAUDE_CODE_TMPDIR);
- it is not harness control state (is_harness_state), nor another policy role's scratch directory
  /tmp/claude-scratch/<role>/;
- it is not inside the project, the harness home, the CLI config dir or $HOME, nor in a git work
  tree or a .git or .claude directory kept in a temp root;
- for Bash, no command of it runs under a wrapper (sudo, env, timeout, xargs, ...) or find -exec.

Any other target keeps the verdict it had: each case below is a decision the base pinned. Every case
runs the real hook file, and the pipeline cases every registered PreToolUse hook, with a throwaway
HOME, CLI config dir, state dir and git config; only symlinks under tmp_path are created.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-tool-policy.py"
SID = "7c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f"
PRODUCT = "/nonexistent-tmp-writes/product"  # a project outside every temp root, never created
TEMP = os.path.realpath(tempfile.gettempdir())
ROLES = ("dev", "qa", "ba")

# The write forms the write-target shim reports, each naming its target as T.
FORMS = {
    ">": ("Bash", lambda t: {"command": f"echo x > {t}"}),
    ">>": ("Bash", lambda t: {"command": f"echo x >> {t}"}),
    "cp": ("Bash", lambda t: {"command": f"cp notes.txt {t}"}),
    "tee": ("Bash", lambda t: {"command": f"echo x | tee {t}"}),
    "heredoc": ("Bash", lambda t: {"command": f"cat <<'EOF' > {t}\nx\nEOF"}),
    "Write": ("Write", lambda t: {"file_path": t, "content": "x"}),
    "Edit": ("Edit", lambda t: {"file_path": t, "old_string": "a", "new_string": "b"}),
}


def _env(tmp_path: Path, project: str, extra: dict | None = None) -> dict:
    home = tmp_path / "home"
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE") and k not in ("TMPDIR",)}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=project,
               CLAUDE_STATE_DIR=str(tmp_path / "state"), CLAUDE_HOME=str(ROOT), TMPDIR=TEMP,
               GIT_CONFIG_GLOBAL=str(tmp_path / "gitconfig"), GIT_CONFIG_NOSYSTEM="1",
               PYTHONDONTWRITEBYTECODE="1")
    env.update(extra or {})
    return env


def _payload(tool: str, tool_input: dict, role: str | None, project: str) -> str:
    home_projects = Path(os.sep, "nonexistent-tmp-writes", "home", ".claude", "projects", "-p")
    payload = {"session_id": SID, "transcript_path": str(home_projects / f"{SID}.jsonl"), "cwd": project,
               "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
    if role:
        payload.update(agent_id=f"a0{role}", agent_type=role, subagent_type=role)
    return json.dumps(payload)


def run(tmp_path: Path, tool: str, tool_input: dict, role: str | None, project: str = PRODUCT,
        extra: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HOOK)], input=_payload(tool, tool_input, role, project),
                          capture_output=True, text=True, cwd=str(tmp_path), env=_env(tmp_path, project, extra),
                          timeout=60)


def verdict(proc: subprocess.CompletedProcess) -> str:
    assert proc.returncode in (0, 2), proc.stderr
    if proc.returncode == 2:
        assert proc.stderr.startswith("BLOCKED by tool-policy.v1: "), proc.stderr
        return "refused"
    return "allowed"


# -- the allow ----------------------------------------------------------------------------------------------

def _temp_targets(tmp_path: Path) -> dict:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return {
        "/tmp": "/tmp/tmp-writes-lane/out.txt",
        "/var/tmp": "/var/tmp/tmp-writes-lane/out.txt",
        "pytest tmp": str(work / "out.txt"),
        "own role scratch": "/tmp/claude-scratch/{role}/out.txt",
        "session scratch": f"/var/tmp/claude-scratch/{SID}/out.txt",
        "codex outputs": "/var/tmp/codex-outputs/out.txt",
    }


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("form", list(FORMS))
def test_a_policy_role_writes_a_temp_root(tmp_path, role, form):
    tool, make = FORMS[form]
    decided = {name: verdict(run(tmp_path, tool, make(target.format(role=role)), role))
               for name, target in _temp_targets(tmp_path).items()}
    assert decided == {name: "allowed" for name in decided}, decided


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("form", list(FORMS))
def test_tmpdir_is_a_temp_root(tmp_path, role, form):
    """$TMPDIR outside /tmp and /var/tmp (never created) is a temp root as they are."""
    tool, make = FORMS[form]
    extra = {"TMPDIR": "/nonexistent-tmp-writes-tmpdir"}
    proc = run(tmp_path, tool, make("/nonexistent-tmp-writes-tmpdir/out.txt"), role, extra=extra)
    assert verdict(proc) == "allowed", proc.stderr


@pytest.mark.parametrize("role", ROLES)
def test_the_main_agent_and_a_layer_decide_as_before(tmp_path, role):
    target = "/tmp/tmp-writes-lane/out.txt"
    assert verdict(run(tmp_path, "Bash", {"command": f"echo x > {target}"}, None)) == "allowed"
    assert verdict(run(tmp_path, "Bash", {"command": f'bash -c "echo x > {target}"'}, role)) == "allowed"
    assert verdict(run(tmp_path, "Bash", {"command": f"cd /tmp && cp notes.txt {target}"}, role)) == "allowed"


def test_every_role_that_holds_the_write_tool_writes_a_temp_root_and_no_other_does(tmp_path):
    sys.path.insert(0, str(ROOT / "hooks"))
    roles = json.loads((ROOT / "policies" / "tool-policy.v1.json").read_text())["roles"]
    for role, row in roles.items():
        holds = "Write" in (row.get("allowed_tools") or [])
        for tool, tool_input in (("Write", {"file_path": "/tmp/tmp-writes-lane/out.txt", "content": "x"}),
                                 ("Bash", {"command": "echo x > /var/tmp/tmp-writes-lane/out.txt"})):
            got = verdict(run(tmp_path, tool, tool_input, role))
            assert got == ("allowed" if holds else "refused"), (role, tool)


# -- the neighbours keep the verdict they had -----------------------------------------------------------------
# A target the temp allow does not cover is decided as on the base: refused where it was refused (dev, qa and
# ba alike), and, for the dev role's '*' row, allowed where the base allowed it outside every temp root.

REFUSED = {"dev": "refused", "qa": "refused", "ba": "refused"}
DEV_ROW = {"dev": "allowed", "qa": "refused", "ba": "refused"}


def _state_targets(tmp_path: Path) -> dict:
    state = tmp_path / "state"
    return {
        "sentinel grant (state dir)": (str(state / "claude-grants" / f"{SID}.json"), REFUSED),
        "sentinel grant (/tmp)": ("/tmp/claude-grants/x.json", REFUSED),
        "sentinel grant, other case": ("/tmp/Claude-Grants/x.json", REFUSED),
        "/do consent flag": (f"/tmp/claude-orchestrator-consent-{SID}.flag", REFUSED),
        "userintent flag": (f"/tmp/claude-push-userintent-{SID}.flag", REFUSED),
        "commit grant": (f"/tmp/claude-commit-grant-{SID}-n1.json", REFUSED),
        "push grant": (f"/tmp/claude-push-grant-{SID}-n1.json", REFUSED),
        "bulk commit sentinel": (f"/tmp/claude-bulk-commit-sentinel-{SID}-n1.json", REFUSED),
        "agentic-commit": ("/tmp/agentic-commit/commit-events/x.json", REFUSED),
        "agentic-commit (state dir)": (str(state / "agentic-commit" / "locks" / "x.lock"), REFUSED),
        "capability state": ("/tmp/claude-capability-0/state.json", REFUSED),
        "git blessed grant": ("/tmp/claude-git-blessed/t.grant", REFUSED),
        "session scratch owner": (f"/var/tmp/claude-scratch/{SID}/.owner", REFUSED),
        "harness home hooks/": (str(ROOT / "hooks" / "tmp-writes-x.py"), REFUSED)
        if ROOT.as_posix().startswith(("/tmp/", "/var/tmp/")) else None,
        "harness home settings.json": (str(ROOT / "settings.json"), REFUSED)
        if ROOT.as_posix().startswith(("/tmp/", "/var/tmp/")) else None,
        "~/.claude": (str(tmp_path / "home" / ".claude" / "settings.json"), REFUSED),
        "$HOME": (str(tmp_path / "home" / "notes.txt"), REFUSED),
        "a temp root itself": ("/tmp", REFUSED),
        "a glob": ("/tmp/*.txt", REFUSED),
    }


def _other_scratch(role: str) -> str:
    return "/tmp/claude-scratch/{}/x.txt".format("ba" if role == "qa" else "qa")


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("form", list(FORMS))
def test_harness_state_and_trees_in_temp_stay_refused(tmp_path, role, form):
    tool, make = FORMS[form]
    cases = {k: v for k, v in _state_targets(tmp_path).items() if v is not None}
    cases["another role's scratch"] = (_other_scratch(role), REFUSED)
    decided = {name: verdict(run(tmp_path, tool, make(target), role)) for name, (target, _) in cases.items()}
    assert decided == {name: want[role] for name, (_, want) in cases.items()}, decided


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("form", ["cp", ">", "Write", "Edit"])
def test_a_project_and_a_work_tree_in_temp_stay_refused(tmp_path, role, form):
    tool, make = FORMS[form]
    project = tmp_path / "proj"
    clone = tmp_path / "clone"
    for repo in (project, clone):
        (repo / ".git" / "hooks").mkdir(parents=True)
    cases = [str(project / ".git" / "config"), str(project / ".git" / "hooks" / "pre-commit"),
             str(project / "src" / "app.py"), str(project / "notes.md"), str(clone / ".git" / "config"),
             str(clone / "src" / "app.py"), str(tmp_path / "loose" / ".git" / "config"),
             str(tmp_path / "loose" / ".claude" / "settings.json")]
    decided = [verdict(run(tmp_path, tool, make(t), role, project=str(project))) for t in cases]
    assert decided == ["refused"] * len(cases), list(zip(cases, decided))


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("form", ["cp", ">", "tee", "Write"])
def test_a_path_out_of_temp_keeps_its_verdict(tmp_path, role, form):
    tool, make = FORMS[form]
    work = tmp_path / "work"
    work.mkdir()
    (work / "out-link").symlink_to("/nonexistent-tmp-writes-out/x.txt")
    (work / "state-link").symlink_to(tmp_path / "state" / "claude-grants" / f"{SID}.json")
    (work / "dir-link").symlink_to("/nonexistent-tmp-writes-out")
    cases = {
        "`..` out of /tmp": ("/tmp/../nonexistent-tmp-writes-out/x.txt", DEV_ROW),
        "`..` out of tmp_path": (str(work) + "/" + "../" * 12 + "nonexistent-tmp-writes-out/x.txt", DEV_ROW),
        "a symlink out of temp": (str(work / "out-link"), DEV_ROW),
        "a symlinked directory out of temp": (str(work / "dir-link" / "x.txt"), DEV_ROW),
        "a symlink into harness state": (str(work / "state-link"), REFUSED),
        "`..` into harness state": (f"/tmp/tmp-writes-lane/../claude-grants/{SID}.json", REFUSED),
        "a relative path": ("out.txt", DEV_ROW),
    }
    decided = {name: verdict(run(tmp_path, tool, make(target), role)) for name, (target, _) in cases.items()}
    assert decided == {name: want[role] for name, (_, want) in cases.items()}, decided


# Unresolved words, `--` and wrappers: (command, verdict per role) as the base decided them.
SHELL_CASES = [
    ("echo x > $T/out.txt", DEV_ROW),
    ('echo x > "${T:-/tmp}/out.txt"', DEV_ROW),
    ("echo x > $(mktemp)", DEV_ROW),
    ("echo x > /tmp/*.txt", REFUSED),
    (f"cp -- notes.txt /tmp/claude-grants/{SID}.json", REFUSED),
    ("cp -- notes.txt /tmp/../nonexistent-tmp-writes-out/x.txt", DEV_ROW),
    (f"echo x | tee -a -- /tmp/claude-orchestrator-consent-{SID}.flag", REFUSED),
    ("sudo tee /tmp/tmp-writes-lane/out.txt", REFUSED),
    ("env tee /tmp/tmp-writes-lane/out.txt", REFUSED),
    ("env FOO=1 cp notes.txt /tmp/tmp-writes-lane/out.txt", REFUSED),
    ("timeout 5 cp notes.txt /tmp/tmp-writes-lane/out.txt", REFUSED),
    ("find . -name x -exec cp {} /tmp/tmp-writes-lane/out.txt \\;", REFUSED),
    ("xargs cp -t /tmp/tmp-writes-lane/", REFUSED),
    ('sudo bash -c "echo x > /tmp/tmp-writes-lane/out.txt"', REFUSED),
    ("echo x > /tmp/tmp-writes-lane/out.txt; sudo tee /tmp/tmp-writes-lane/b.txt", REFUSED),
]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command,want", SHELL_CASES, ids=[c for c, _ in SHELL_CASES])
def test_unresolved_words_dashes_and_wrappers_keep_their_verdict(tmp_path, role, command, want):
    assert verdict(run(tmp_path, "Bash", {"command": command}, role)) == want[role]


@pytest.mark.parametrize("role", ROLES)
def test_tmpdir_harness_state_and_tool_rows_keep_their_verdict(tmp_path, role):
    extra = {"TMPDIR": "/nonexistent-tmp-writes-tmpdir"}
    grant = "/nonexistent-tmp-writes-tmpdir/claude-grants/x.json"  # outside /tmp: dev's '*' row held it
    assert verdict(run(tmp_path, "Write", {"file_path": grant, "content": "x"}, role, extra=extra)) == DEV_ROW[role]
    # A role without the Write tool writes no temp file through Bash either: its tool lists still apply.
    proc = run(tmp_path, "Bash", {"command": "echo x > /tmp/tmp-writes-lane/out.txt"}, "pull-analyst")
    assert verdict(proc) == "refused" and "not in allowed_tools" in proc.stderr, proc.stderr


def test_a_harness_state_refusal_names_the_state(tmp_path):
    proc = run(tmp_path, "Bash", {"command": "echo x > /tmp/claude-grants/x.json"}, "dev")
    reason = json.loads(proc.stderr.splitlines()[0].split(": ", 1)[1])["deny_reason"]
    assert "harness state (sentinel-grants)" in reason, reason


# -- the registered PreToolUse pipeline ------------------------------------------------------------------------

def _registered(tool: str) -> list:
    sys.path.insert(0, str(ROOT / "hooks"))
    from lib import launch_settings

    settings = launch_settings.expand(json.loads((ROOT / "settings.json").read_text()), str(ROOT))
    out = []
    for group in settings["hooks"]["PreToolUse"]:
        matcher = group.get("matcher")
        if matcher in (None, "", "*") or tool in matcher.split("|"):
            out += [h["command"] for h in group["hooks"]]
    return out


def pipeline(tmp_path: Path, tool: str, tool_input: dict, role: str) -> str:
    """Every PreToolUse registration matching the tool, as the CLI runs them: one refusal refuses."""
    raw = _payload(tool, tool_input, role, PRODUCT)
    env = _env(tmp_path, PRODUCT)
    (tmp_path / "home" / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state").mkdir(exist_ok=True)
    refused = []
    for command in _registered(tool):
        proc = subprocess.run(["bash", "-c", command], input=raw, capture_output=True, text=True, env=env,
                              cwd=str(tmp_path), timeout=90)
        try:
            out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        except ValueError:
            out = {}
        decision = ((out.get("hookSpecificOutput") or {}).get("permissionDecision")
                    if isinstance(out, dict) else None)
        if proc.returncode == 2 or decision == "deny":
            refused.append((command, proc.stderr[:300], proc.stdout[:300]))
    return ("refused", refused) if refused else ("allowed", [])


PIPELINE_CASES = [
    ("Write", {"file_path": "/tmp/tmp-writes-lane/out.txt", "content": "x"}, "allowed"),
    ("Edit", {"file_path": "/tmp/tmp-writes-lane/out.txt", "old_string": "a", "new_string": "b"}, "allowed"),
    ("Bash", {"command": "echo x > /tmp/tmp-writes-lane/out.txt"}, "allowed"),
    ("Bash", {"command": "echo x >> /var/tmp/tmp-writes-lane/out.txt"}, "allowed"),
    ("Bash", {"command": "cp notes.txt /tmp/tmp-writes-lane/out.txt"}, "allowed"),
    ("Bash", {"command": "echo x | tee /tmp/tmp-writes-lane/out.txt"}, "allowed"),
    ("Bash", {"command": "cat <<'EOF' > /tmp/tmp-writes-lane/out.txt\nx\nEOF"}, "allowed"),
    ("Write", {"file_path": "/tmp/claude-grants/x.json", "content": "x"}, "refused"),
    ("Bash", {"command": f"echo x > /tmp/claude-orchestrator-consent-{SID}.flag"}, "refused"),
    ("Bash", {"command": f"cp notes.txt /tmp/claude-commit-grant-{SID}-n1.json"}, "refused"),
    ("Bash", {"command": "echo x | tee /tmp/agentic-commit/commit-events/x.json"}, "refused"),
    ("Bash", {"command": "sudo tee /tmp/tmp-writes-lane/out.txt"}, "refused"),
]


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("tool,tool_input,want", PIPELINE_CASES,
                         ids=[f"{t}:{json.dumps(i)[:60]}" for t, i, _ in PIPELINE_CASES])
def test_the_registered_pipeline_decides_as_the_rule(tmp_path, role, tool, tool_input, want):
    got, refusals = pipeline(tmp_path, tool, tool_input, role)
    assert got == want, refusals
