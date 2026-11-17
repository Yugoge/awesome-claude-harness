"""OB-L08: project writes are allowed by `Edit(./**)`; the config, hook and secret surfaces stay stopped.

Root cause: permissions.allow's Edit entries covered only manifests, .claude/agents|commands, .review,
docs, scripts and tests/generated, so every other write inside the project (Write `src/newmodule.py`,
`echo hi > notes.md`, a heredoc written to a file at the project root) asked in default mode, and was
refused outright headless or overnight. The owner chose `Edit(./**)` (not defaultMode acceptEdits).

The CLI's decision is modelled here from its documentation, not measured (no offline run of the CLI's
own permission check is available in this tree's tooling):

* code.claude.com/docs/en/permissions.md, "Manage permissions": "Rules are evaluated in order: deny,
  then ask, then allow. The first match in that order determines the outcome" and "An allow rule can't
  carve an exception out of a deny rule."
* same page, "How path patterns match": `path` or `./path` is "Path relative to current directory";
  gitignore syntax; "Bare filenames follow gitignore semantics and match at any depth"; "`Edit` rules
  apply to all built-in tools that edit files"; "A `Read` deny rule also blocks the Edit and Write tools
  on the same path".
* same page, "Redirections": "for `> file`, `>> file`, or `2> file`, the check covers your `Edit`
  allow and deny rules, protected paths, and the working directories"; "here-docs and here-strings"
  are no target.
* code.claude.com/docs/en/permission-modes.md, "Protected paths": in `default` and `acceptEdits`
  protected-path writes are "Prompted"; "`permissions.allow` rules in settings files do not
  pre-approve protected-path writes. The safety check runs before Claude Code evaluates allow rules
  from settings"; `.claude` (with exceptions such as `.claude/worktrees/`) and `.git` are protected
  directories.

Case sensitivity of path rules is undocumented; every path here is lower case, so the model's
case-sensitive match decides the same either way. The settings file is the harness home's
settings.json, i.e. user settings, where `./**` anchors at the session's current directory, the
project root in every case below.

The hook layer is not modelled: hooks/pretool-claude-config-guard.py and
hooks/pretool-harness-switch-guard.py are run on the calls they stop.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"

# permission-modes.md "Protected paths" (directories; `.claude/worktrees/` is a listed exception).
PROTECTED_DIRS = (".git", ".config/git", ".vscode", ".idea", ".husky", ".cargo", ".devcontainer", ".yarn",
                  ".mvn", ".claude")
PROTECTED_EXCEPTIONS = (".claude/worktrees/",)


def _permissions() -> dict:
    with open(ROOT / "settings.json", encoding="utf-8") as fh:
        return json.load(fh)["permissions"]


def _glob_regex(pattern: str) -> str:
    """A gitignore glob as a regex over a `/`-separated path: `**/` any directories (none too), `/**`
    everything below, `*` and `?` within one name."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("/**", i) and i + 3 == len(pattern):
            out.append("/.*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "".join(out)


def path_rule_matches(rule: str, tool: str, rel: str) -> bool:
    """Whether a `Read(...)`/`Edit(...)` rule written in user settings matches `rel`, a path relative to
    the current directory (the project root). Only the cwd-relative forms are modelled; `//`, `~/` and
    `/` anchored rules never name a project-relative path here, so they match nothing."""
    m = re.fullmatch(r"(\w+)\((.*)\)", rule)
    if not m or m.group(1) != tool:
        return False
    pat = m.group(2)
    if pat.startswith(("//", "~/", "/")):
        return False
    if rel.startswith("../") or rel.startswith("/"):
        return False  # "A rule only matches files under its anchor."
    if pat.startswith("./"):
        pat = pat[2:]
    if "/" not in pat.rstrip("/"):
        pat = "**/" + pat  # a bare name matches at any depth (gitignore)
    return re.fullmatch(_glob_regex(pat), rel) is not None


def protected(rel: str) -> bool:
    if any(rel.startswith(e) for e in PROTECTED_EXCEPTIONS):
        return False
    return any(rel == d or rel.startswith(d + "/") for d in PROTECTED_DIRS)


def write_decision(perms: dict, rel: str) -> str:
    """The CLI's decision on a write of `rel` (Write/Edit tool, or a Bash output redirect target) in
    default mode: deny (Edit deny, or Read deny, which also blocks Edit/Write), then ask, then the
    protected-path check that runs before allow rules, then allow; no match asks."""
    if any(path_rule_matches(r, "Edit", rel) or path_rule_matches(r, "Read", rel) for r in perms["deny"]):
        return "deny"
    if any(path_rule_matches(r, "Edit", rel) for r in perms.get("ask", [])):
        return "ask"
    if protected(rel):
        return "ask"
    if any(path_rule_matches(r, "Edit", rel) for r in perms["allow"]):
        return "allow"
    return "ask"


_REDIRECT = re.compile(r"(?<![<>&0-9])>{1,2}\s*([^\s<>|;&]+)")


def redirect_targets(command: str) -> list[str]:
    """The output-redirect targets of the simple commands used below (heredoc bodies are no target)."""
    first = command.split("\n", 1)[0]
    return [t.strip("'\"") for t in _REDIRECT.findall(first)]


# ---- the matcher model itself ---------------------------------------------------------------------

def test_the_path_rule_model():
    assert path_rule_matches("Edit(./**)", "Edit", "src/newmodule.py")
    assert path_rule_matches("Edit(./**)", "Edit", "notes.md")
    assert not path_rule_matches("Edit(./**)", "Edit", "../outside.txt")
    assert path_rule_matches("Edit(.env)", "Edit", "sub/.env")  # bare name: any depth
    assert path_rule_matches("Edit(**/.env.*)", "Edit", ".env.local")
    assert not path_rule_matches("Edit(**/.env.*)", "Edit", ".envrc")
    assert path_rule_matches("Edit(.claude/hooks/**)", "Edit", ".claude/hooks/x.sh")
    assert not path_rule_matches("Edit(.claude/settings.json)", "Edit", ".claude/settings.local.json")
    assert not path_rule_matches("Edit(//etc/passwd)", "Edit", "etc/passwd")
    assert protected(".claude/settings.local.json") and protected(".git/hooks/pre-commit")
    assert not protected(".claude/worktrees/a/src/x.py") and not protected("src/.claude.txt")
    assert redirect_targets("echo hi > notes.md") == ["notes.md"]
    assert redirect_targets("cat > notes.md <<'EOF'\nhi > not-a-target\nEOF") == ["notes.md"]
    assert redirect_targets("ls 2>&1") == []


# ---- the entries ----------------------------------------------------------------------------------

def test_project_writes_entry_is_allowed():
    assert "Edit(./**)" in _permissions()["allow"]


def test_project_local_settings_entry_is_denied():
    """Nothing else stops a Write of `.claude/settings.local.json` whose keys the harness-switch guard
    leaves alone (model, theme, ...): no deny entry covered it, and the protected-path prompt is the
    CLI's alone (routed to the classifier in auto mode). The narrowest deny that keeps it stopped once
    project writes are allowed sits beside `Edit(.claude/settings.json)`."""
    deny = _permissions()["deny"]
    assert "Edit(.claude/settings.local.json)" in deny
    assert "Edit(.claude/settings.json)" in deny


# ---- must pass ------------------------------------------------------------------------------------

@pytest.mark.parametrize("rel", ["src/newmodule.py", "notes.md", "README.md", "src/pkg/sub/mod.py"])
def test_project_write_is_allowed(rel):
    assert write_decision(_permissions(), rel) == "allow"


@pytest.mark.parametrize("command", [
    "echo hi > notes.md",
    "cat > notes.md <<'EOF'\nhi\nEOF",
    "cat <<'EOF' > release-notes.txt\nline\nEOF",
])
def test_project_redirect_is_allowed(command):
    """echo and cat are in the CLI's built-in read-only set; the redirect target is checked as a write."""
    targets = redirect_targets(command)
    assert targets
    assert all(write_decision(_permissions(), t) == "allow" for t in targets)


def _hook(name: str, tool: str, tool_input: dict, project: Path, home: Path) -> subprocess.CompletedProcess:
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
               "cwd": str(project), "session_id": "ob-l08", "transcript_path": str(project / "t.jsonl")}
    env = dict(os.environ, HOME=str(home), CLAUDE_PROJECT_DIR=str(project))
    return subprocess.run([sys.executable, str(HOOKS / name)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(project), env=env, timeout=60)


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    (p / ".claude").mkdir(parents=True)
    (tmp_path / "home").mkdir()
    return p


@pytest.mark.parametrize("tool,tool_input", [
    ("Write", {"file_path": "src/newmodule.py", "content": "x = 1\n"}),
    ("Bash", {"command": "echo hi > notes.md"}),
    ("Bash", {"command": "cat > notes.md <<'EOF'\nhi\nEOF"}),
])
def test_hooks_pass_project_writes(project, tool, tool_input):
    if tool == "Write":
        tool_input = dict(tool_input, file_path=str(project / tool_input["file_path"]))
    for name in ("pretool-claude-config-guard.py", "pretool-harness-switch-guard.py"):
        proc = _hook(name, tool, tool_input, project, project.parent / "home")
        assert proc.returncode == 0, (name, proc.stderr)


# ---- must still be stopped: the permission layer --------------------------------------------------

# (path, decision, the layer that decides) -- protected-path asks are the CLI's own check
STOPPED = [
    (".claude/settings.json", "deny", "Edit(.claude/settings.json)"),
    (".claude/settings.local.json", "deny", "Edit(.claude/settings.local.json)"),
    (".claude/hooks/x.sh", "deny", "Edit(.claude/hooks/**)"),
    (".claude/scripts/x.sh", "deny", "Edit(.claude/scripts/**)"),
    (".claude/CLAUDE.md", "deny", "Edit(.claude/CLAUDE.md)"),
    (".claude/commands/x.md", "ask", "protected path .claude (allow Edit(.claude/commands/**) does not pre-approve)"),
    (".claude/agents/x.md", "ask", "protected path .claude"),
    (".git/hooks/pre-commit", "ask", "protected path .git"),
    (".env", "deny", "Edit(**/.env) / Edit(.env)"),
    (".env.local", "deny", "Edit(**/.env.*)"),
    ("config/.env.production", "deny", "Edit(**/.env.*)"),
    ("../outside.txt", "ask", "outside the anchor of Edit(./**)"),
]


@pytest.mark.parametrize("rel,decision,layer", STOPPED, ids=[s[0] for s in STOPPED])
def test_write_is_still_stopped(rel, decision, layer):
    assert write_decision(_permissions(), rel) == decision, layer


@pytest.mark.parametrize("command,decision", [
    ("echo '{}' > .claude/settings.json", "deny"),
    ("echo '{}' > .claude/settings.local.json", "deny"),
    ("echo x > .claude/hooks/x.sh", "deny"),
    ("echo x > .claude/commands/x.md", "ask"),
    ("echo SECRET=1 > .env", "deny"),
    ("echo SECRET=1 >> .env.local", "deny"),
])
def test_redirect_is_still_stopped(command, decision):
    assert [write_decision(_permissions(), t) for t in redirect_targets(command)] == [decision]


def test_project_writes_entry_widens_no_stopped_path():
    """`Edit(./**)` changes no decision of a stopped path: with it taken out the decisions are the same."""
    perms = _permissions()
    without = dict(perms, allow=[e for e in perms["allow"] if e != "Edit(./**)"])
    for rel, decision, _layer in STOPPED:
        assert write_decision(without, rel) == decision == write_decision(perms, rel), rel


# ---- must still be stopped: the hook layer --------------------------------------------------------

def test_config_guard_stops_a_hooks_redirect(project):
    proc = _hook("pretool-claude-config-guard.py", "Bash", {"command": "echo x > .claude/hooks/x.sh"},
                 project, project.parent / "home")
    assert proc.returncode == 2 and "BLOCKED: claude config guard" in proc.stderr


def test_config_guard_stops_a_commands_write(project):
    proc = _hook("pretool-claude-config-guard.py", "Write",
                 {"file_path": str(project / ".claude/commands/x.md"), "content": "x"},
                 project, project.parent / "home")
    assert proc.returncode == 2 and "BLOCKED: claude config guard" in proc.stderr


def test_switch_guard_stops_a_local_settings_permissions_write(project):
    proc = _hook("pretool-harness-switch-guard.py", "Write",
                 {"file_path": str(project / ".claude/settings.local.json"),
                  "content": '{"permissions": {"allow": ["Bash"]}}'},
                 project, project.parent / "home")
    assert proc.returncode == 2 and "BLOCKED: harness-switch" in proc.stderr


def test_switch_guard_leaves_a_benign_local_settings_write_to_the_deny(project):
    """Why the deny entry is needed: the guard passes a settings.local.json write of keys it does not own."""
    proc = _hook("pretool-harness-switch-guard.py", "Write",
                 {"file_path": str(project / ".claude/settings.local.json"), "content": '{"model": "x"}'},
                 project, project.parent / "home")
    assert proc.returncode == 0, proc.stderr
    assert write_decision(_permissions(), ".claude/settings.local.json") == "deny"
