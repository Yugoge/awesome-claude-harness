"""What /clean's owner approves is written by its producer, and by no other caller (P9-4).

hooks/pretool-tool-policy.py derives it while a human-typed /clean's span is the active one: the
cleaner (its own dispatch a cleaner dispatch of that span, made after an answered AskUserQuestion)
writes each approved move's or rename's destination and each approved fix_style file of the request's
docs/clean/user-approvals-<id>.json; the rule-inspector (its own dispatch a rule-inspector dispatch of
that span) writes the project's root README.md and ARCHITECTURE.md. Every other caller's write of such a
path, the main agent's included, exits 2 (D8). hooks/pretool-claude-config-guard.py lets that cleaner's
approved moves and edits under commands/ through, in a harness-home /clean, and nothing else.

Each case runs the real hooks as subprocesses on a transcript store shaped as the CLI keeps it. The
project lies under pytest's temp directory, where the scratch rule refuses every role's write (raw /tmp
is denied for every role; hooks/tests/test_tool_policy_* cover that rule): the tool-policy runs set its
temp roots to a path nothing lies under, and change nothing else.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "hooks" / "pretool-tool-policy.py"
GUARD = ROOT / "hooks" / "pretool-claude-config-guard.py"
RID = "clean-20261109-101010"
BLOCK = "BLOCKED by tool-policy.v1: "
# The hook, run as its own __main__ does, with the scratch rule's temp roots moved off pytest's tmp_path.
RUN_POLICY = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('tool_policy_clean_case', sys.argv[1])\n"
    "m = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(m)\n"
    "m._SYSTEM_TEMP_ROOTS = ('/nonexistent-p9-4-raw-temp',)\n"
    "m.main()\n"
)


def _obligation(role: str, artifacts: list) -> str:
    doc = {"task_id": None, "lane": None, "lane_set": None, "role": role, "pipeline": "clean",
           "profile": "ad_hoc", "dispatched_at": "2026-11-09T10:10:10Z", "artifacts": artifacts}
    return f'<obligation v="1">\n{json.dumps(doc)}\n</obligation>'


CLEANER = ("You are the cleaner subagent.\n\n"
           f"The merged context with approvals is at: docs/clean/context-with-approvals-{RID}.json\n"
           + _obligation("cleaner", [{"kind": "markdown", "path": f"docs/clean/cleanup-execution-{RID}.json",
                                      "identity_anchor": RID, "terminal_line_regex": "^}$"}])
           + f"\n\nExecute ALL approved_actions. Write results to docs/clean/cleanup-execution-{RID}.json.")
INSPECTORS = {
    "cleanliness-inspector": (f"docs/clean/cleanliness-report-{RID}.json", "cleanliness-inspector-report.v1"),
    "style-inspector": (f"docs/clean/style-partial-{RID}-group-g1.json", "style-inspector-report.v1"),
    "prompt-inspector": (f"docs/clean/prompt-report-{RID}.json", "prompt-inspector-report.v1"),
}


def _approved(action_id: str, action: str, **fields) -> dict:
    return dict({"action_id": action_id, "source_report": "cleanliness", "source_finding_index": 0,
                 "action": action, "description": "d", "approved": True}, **fields)


PRODUCT_APPROVALS = [
    _approved("finding_1", "move", location="usage-guide.md", file="usage-guide.md",
              destination="docs/guides/usage-guide.md"),
    _approved("finding_2", "rename", location="old_name.md", file="old_name.md", destination="docs/old-name.md"),
    _approved("finding_3", "fix_style", location="scripts/run-tests.sh:1", old_line="a", new_line="b"),
    _approved("finding_4", "fix_style", location="src/app.py:3", old_line="a", new_line="b"),
    _approved("finding_5", "move", location="notes.md", file="notes.md", destination=".claude/hooks/notes.md"),
    _approved("finding_6", "move", location="spare.md", file="spare.md", destination="docs/spare.md",
              approved=False),
    _approved("finding_7", "fix_style", location=f"docs/clean/user-approvals-{RID}.json", old_line="a",
              new_line="b"),
    _approved("finding_8", "move", location="x.md", file="x.md", destination="../outside/x.md"),
]


class Session:
    """A /clean session of ``project``: Step 4's rule-inspector, the inspectors, Step 13's question and
    Step 16's cleaner (running), each a started subagent; the approvals Step 13 writes."""

    def __init__(self, root: Path, project: Path, approvals: list, asked: bool = True, after: str = ""):
        self.project = project
        self.sid = "sess-" + uuid.uuid4().hex[:8]
        self.transcript = root / f"{self.sid}.jsonl"
        self.subagents = root / self.sid / "subagents"
        self.subagents.mkdir(parents=True)
        self.agents = {}
        self.records = [{"type": "user", "message": {"role": "user", "content":
                         "<command-message>clean is running…</command-message>\n<command-name>/clean</command-name>\n"
                         "<command-args></command-args>"}}]
        self.dispatch("rule-inspector", f"Context file: docs/clean/rule-context-{RID}.json", done=True)
        for role, (path, schema) in INSPECTORS.items():
            self.dispatch(role, f"Context file: docs/clean/context-{RID}.json\n" + _obligation(
                role, [{"kind": "json", "path": path, "schema": schema, "identity": {"request_id": RID}}]), done=True)
        if asked:
            self.tool("AskUserQuestion", {"questions": [{"question": "Which cleanup?", "header": "Cleanup",
                                                         "multiSelect": False, "options": [
                                                             {"label": "Execute all", "description": "a"},
                                                             {"label": "Report only", "description": "r"}]}]},
                      "User answered: Execute all")
        self.dispatch("cleaner", CLEANER, done=False)
        if after:  # the owner typed another command: /clean's span is over
            self.records.append({"type": "user", "message": {"role": "user", "content":
                                 f"<command-message>{after} is running…</command-message>\n"
                                 f"<command-name>/{after}</command-name>\n<command-args>x</command-args>"}})
        self.transcript.write_text("".join(json.dumps(r) + "\n" for r in self.records))
        clean = project / "docs" / "clean"
        clean.mkdir(parents=True, exist_ok=True)
        (clean / f"user-approvals-{RID}.json").write_text(json.dumps(
            {"request_id": RID, "mode": "execute_all", "user_approvals": {
                "total_issues_in_report": len(approvals), "total_approved_actions": len(approvals),
                "approved_actions": approvals, "rejected_actions": []}}))

    def tool(self, name: str, tool_input: dict, result: str | None) -> str:
        call = "toolu_" + uuid.uuid4().hex[:20]
        self.records.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": call, "name": name, "input": tool_input}]}})
        if result is not None:
            self.records.append({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call, "content": result}]}})
        return call

    def dispatch(self, role: str, prompt: str, done: bool) -> None:
        call = self.tool("Agent", {"description": role, "prompt": prompt, "subagent_type": role},
                         "done" if done else None)
        agent_id = "a" + uuid.uuid4().hex[:16]
        (self.subagents / f"agent-{agent_id}.jsonl").write_text(
            json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
        (self.subagents / f"agent-{agent_id}.meta.json").write_text(json.dumps({"agentType": role, "toolUseId": call}))
        self.agents[role] = agent_id

    def payload(self, role: str, tool: str, tool_input: dict) -> dict:
        data = {"session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(self.project),
                "hook_event_name": "PreToolUse", "permission_mode": "default", "tool_name": tool,
                "tool_input": tool_input, "tool_use_id": "toolu_" + uuid.uuid4().hex[:24]}
        if role != "main":
            data.update(agent_id=self.agents.get(role) or "a" + uuid.uuid4().hex[:16], agent_type=role)
        return data

    def env(self, tmp_path: Path) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        env.update({"HOME": str(tmp_path / "home"), "CLAUDE_CONFIG_DIR": str(tmp_path / "home" / ".claude"),
                    "CLAUDE_STATE_DIR": str(tmp_path / "state"), "CLAUDE_PROJECT_DIR": str(self.project),
                    "PYTHONDONTWRITEBYTECODE": "1"})
        return env

    def policy(self, tmp_path: Path, role: str, tool: str, tool_input: dict):
        return subprocess.run([sys.executable, "-c", RUN_POLICY, str(POLICY)], capture_output=True, text=True,
                              input=json.dumps(self.payload(role, tool, tool_input)), env=self.env(tmp_path),
                              cwd=str(self.project), timeout=60)

    def guard(self, tmp_path: Path, role: str, tool: str, tool_input: dict):
        return subprocess.run([sys.executable, str(GUARD)], capture_output=True, text=True,
                              input=json.dumps(self.payload(role, tool, tool_input)), env=self.env(tmp_path),
                              cwd=str(self.project), timeout=60)


def _edit(path: Path) -> dict:
    return {"file_path": str(path), "old_string": "a", "new_string": "b"}


def _write(path: Path) -> dict:
    return {"file_path": str(path), "content": "x\n"}


MOVE = {"command": "mkdir -p docs/guides && mv usage-guide.md docs/guides/usage-guide.md"}
RENAME = {"command": "mkdir -p docs && mv old_name.md docs/old-name.md"}


@pytest.fixture()
def product(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    return Session(tmp_path / "projects", project, PRODUCT_APPROVALS)


def _refused(proc, reason: str = "") -> dict:
    assert proc.returncode == 2, (proc.returncode, proc.stderr)
    first = proc.stderr.splitlines()[0]
    assert first.startswith(BLOCK), proc.stderr
    denial = json.loads(first[len(BLOCK):])
    assert reason in denial["deny_reason"], denial
    return denial


# -- the producer's approved write passes -------------------------------------------------------

@pytest.mark.parametrize("tool, tool_input", [
    ("Bash", MOVE), ("Bash", RENAME),
    ("Edit", "scripts/run-tests.sh"),  # fix_style, its location's line taken off
    ("Edit", "src/app.py"),  # the owner approved it: the source denial does not refuse it
], ids=["move", "rename", "fix_style", "fix_style-in-src"])
def test_the_cleaner_writes_what_the_owner_approved(tmp_path, product, tool, tool_input):
    if isinstance(tool_input, str):
        tool_input = _edit(product.project / tool_input)
    proc = product.policy(tmp_path, "cleaner", tool, tool_input)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("name", ["README.md", "ARCHITECTURE.md"])
@pytest.mark.parametrize("tool", ["Edit", "Write"])
def test_the_rule_inspector_writes_the_root_readme_and_architecture(tmp_path, product, name, tool):
    tool_input = (_edit if tool == "Edit" else _write)(product.project / name)
    proc = product.policy(tmp_path, "rule-inspector", tool, tool_input)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("role", ["cleanliness-inspector", "style-inspector", "prompt-inspector", "cleaner"])
def test_each_clean_producer_writes_its_own_report(tmp_path, product, role):
    """P9 A18's tool-policy replay: each /clean producer writing the report its dispatch declares."""
    path = INSPECTORS[role][0] if role in INSPECTORS else f"docs/clean/cleanup-execution-{RID}.json"
    proc = product.policy(tmp_path, role, "Write", _write(product.project / path))
    assert proc.returncode == 0, proc.stderr


# -- the same write by any other caller stays refused -------------------------------------------

@pytest.mark.parametrize("role", ["main", "dev", "cleanliness-inspector", "rule-inspector", "general-purpose"])
@pytest.mark.parametrize("tool, tool_input", [("Bash", MOVE), ("Edit", "scripts/run-tests.sh")],
                         ids=["move", "fix_style"])
def test_another_caller_does_not_write_the_cleaners_approved_paths(tmp_path, product, role, tool, tool_input):
    if isinstance(tool_input, str):
        tool_input = _edit(product.project / tool_input)
    _refused(product.policy(tmp_path, role, tool, tool_input))


@pytest.mark.parametrize("role", ["main", "dev", "cleaner", "style-inspector"])
def test_another_caller_does_not_write_the_root_readme_in_the_clean_span(tmp_path, product, role):
    _refused(product.policy(tmp_path, role, "Edit", _edit(product.project / "README.md")))


def test_the_main_agents_refusal_names_the_producer(tmp_path, product):
    denial = _refused(product.policy(tmp_path, "main", "Bash", MOVE), "only that cleaner writes it (D8)")
    assert denial["role"] == "main"


# -- outside the approved paths, the role rows decide as before ---------------------------------

@pytest.mark.parametrize("tool, tool_input, reason", [
    ("Bash", {"command": "mkdir -p docs/other && mv usage-guide.md docs/other/usage-guide.md"},
     "not in allowed_write_path_prefixes"),
    ("Write", "docs/guides/other.md", "not in allowed_write_path_prefixes"),
    ("Edit", "src/other.py", "matches denied_write_path_prefixes"),
    ("Bash", {"command": "mkdir -p docs && mv spare.md docs/spare.md"}, "not in allowed_write_path_prefixes"),
    ("Bash", {"command": "mkdir -p .claude/hooks && mv notes.md .claude/hooks/notes.md"},
     "matches _shared_protected_path_prefixes"),
    ("Edit", f"docs/clean/user-approvals-{RID}.json", "not in allowed_write_path_prefixes"),
    ("Edit", "README.md", "only that rule-inspector writes it (D8)"),
], ids=["unapproved-destination", "unapproved-file", "unapproved-source-file", "rejected-action",
        "protected-destination", "the-approvals-file", "the-rule-inspectors-readme"])
def test_the_cleaner_writes_nothing_else(tmp_path, product, tool, tool_input, reason):
    if isinstance(tool_input, str):
        tool_input = (_edit if tool == "Edit" else _write)(product.project / tool_input)
    _refused(product.policy(tmp_path, "cleaner", tool, tool_input), reason)


def test_an_approval_outside_the_project_grants_nothing(tmp_path, product):
    proc = product.policy(tmp_path, "cleaner", "Bash", {"command": "mv x.md ../outside/x.md"})
    _refused(proc, "not in allowed_write_path_prefixes")


@pytest.mark.parametrize("name", ["NOTES.md", "docs/README.md", "src/app.py"])
def test_the_rule_inspector_writes_no_other_file(tmp_path, product, name):
    _refused(product.policy(tmp_path, "rule-inspector", "Edit", _edit(product.project / name)))


def test_without_the_owners_answer_the_cleaner_holds_nothing(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    s = Session(tmp_path / "projects", project, PRODUCT_APPROVALS, asked=False)
    _refused(s.policy(tmp_path, "cleaner", "Bash", MOVE), "not in allowed_write_path_prefixes")
    assert s.policy(tmp_path, "main", "Bash", MOVE).returncode == 0


def test_after_the_clean_span_nothing_is_held(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    s = Session(tmp_path / "projects", project, PRODUCT_APPROVALS, after="dev")
    _refused(s.policy(tmp_path, "cleaner", "Bash", MOVE), "not in allowed_write_path_prefixes")
    _refused(s.policy(tmp_path, "rule-inspector", "Edit", _edit(project / "README.md")))
    assert s.policy(tmp_path, "main", "Bash", MOVE).returncode == 0
    assert s.policy(tmp_path, "main", "Edit", _edit(project / "README.md")).returncode == 0


def test_a_cleaner_started_from_another_prompt_holds_nothing(tmp_path, product):
    """The caller's own dispatch: its meta names the span's cleaner call, but its first record is
    another prompt."""
    agent = product.agents["cleaner"]
    (product.subagents / f"agent-{agent}.jsonl").write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "something else"}}) + "\n")
    _refused(product.policy(tmp_path, "cleaner", "Bash", MOVE), "only that cleaner writes it (D8)")


def test_the_harness_homes_config_surface_is_never_approved(tmp_path):
    """In a harness-home /clean, an approval of hooks/, policies/, schemas/, scripts/ or
    settings.json grants nothing; commands/ and agents/ are approved as asked."""
    spec = importlib.util.spec_from_file_location("tool_policy_clean_unit", POLICY)
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    home = tmp_path / "home" / ".claude"
    (home / "docs" / "clean").mkdir(parents=True)
    approvals = [_approved(f"f{i}", "rename", location=f"{d}/a", destination=f"{d}/b")
                 for i, d in enumerate(("hooks", "policies", "schemas", "scripts", "commands", "agents"))]
    approvals += [_approved("f9", "fix_style", location="settings.json:2"),
                  _approved("f10", "fix_style", location=".git/config:1")]
    (home / "docs" / "clean" / f"user-approvals-{RID}.json").write_text(
        json.dumps({"user_approvals": {"approved_actions": approvals}}))
    written, removed = policy._clean_approved(str(home), RID, str(home))
    assert {os.path.relpath(p, home) for p in written} == {"commands/b", "agents/b"}
    assert {os.path.relpath(p, home) for p in removed} == {"commands/a", "agents/a"}


# -- the config guard: a harness-home /clean's cleaner, and no other writer --------------------

@pytest.fixture()
def home_clean(tmp_path):
    """A /clean run inside a harness home (its path holds `.claude/commands/`)."""
    project = tmp_path / "h" / ".claude"
    (project / "commands").mkdir(parents=True)
    (project / "hooks").mkdir()
    approvals = [
        _approved("finding_1", "rename", location="commands/old_cmd.md", file="commands/old_cmd.md",
                  destination="commands/old-cmd.md"),
        _approved("finding_2", "fix_style", location="commands/clean.md", old_line="a", new_line="b",
                  source_report="prompt"),
        _approved("finding_3", "fix_style", location="hooks/x.py:1", old_line="a", new_line="b"),
    ]
    return Session(tmp_path / "projects", project, approvals)


def test_the_guard_lets_the_cleaner_edit_an_approved_command_file(tmp_path, home_clean):
    proc = home_clean.guard(tmp_path, "cleaner", "Edit", _edit(home_clean.project / "commands" / "clean.md"))
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("form", ["absolute", "real-home-variable"])
def test_the_guard_lets_the_cleaner_move_an_approved_command_file(tmp_path, home_clean, form):
    p = home_clean.project / "commands"
    command = f"mv {p}/old_cmd.md {p}/old-cmd.md"
    proc = home_clean.guard(tmp_path, "cleaner", "Bash", {"command": command})
    assert proc.returncode == 0, proc.stderr
    if form == "real-home-variable":  # the guard reads a home variable as the home: no approved path there
        proc = home_clean.guard(tmp_path, "cleaner", "Bash", {
            "command": 'mv "$CLAUDE_HOME/commands/old_cmd.md" "$CLAUDE_HOME/commands/old-cmd.md"'})
        assert proc.returncode == 2, proc.stderr


@pytest.mark.parametrize("role", ["main", "dev", "qa", "rule-inspector", "prompt-inspector"])
def test_the_guard_still_refuses_every_other_writer(tmp_path, home_clean, role):
    p = home_clean.project / "commands"
    for tool, tool_input in (("Edit", _edit(p / "clean.md")), ("Bash", {"command": f"mv {p}/old_cmd.md {p}/old-cmd.md"}),
                             ("Bash", {"command": f"echo x > {p}/new.md"})):
        proc = home_clean.guard(tmp_path, role, tool, tool_input)
        assert proc.returncode == 2 and "BLOCKED: claude config guard" in proc.stderr, (role, tool, proc.stderr)


@pytest.mark.parametrize("tool, tool_input", [
    ("Edit", "commands/push.md"),
    ("Bash", "mv {p}/old_cmd.md {p}/evil.md"),
    ("Bash", "mv {p}/old_cmd.md {p}/old-cmd.md && echo x > {p}/evil.md"),
    ("Bash", "mv {p}/old_cmd.md {p}/old-cmd.md && cp x {h}/hooks/x.py"),
    ("Edit", "hooks/x.py"),
], ids=["unapproved-edit", "unapproved-destination", "approved-and-another-write", "approved-and-a-hook",
        "approved-hook-file"])
def test_the_guard_refuses_the_cleaner_anything_else(tmp_path, home_clean, tool, tool_input):
    h, p = home_clean.project, home_clean.project / "commands"
    if tool == "Edit":
        tool_input = _edit(h / tool_input)
    else:
        tool_input = {"command": tool_input.format(p=p, h=h)}
    proc = home_clean.guard(tmp_path, "cleaner", tool, tool_input)
    assert proc.returncode == 2 and "BLOCKED: claude config guard" in proc.stderr, proc.stderr


def test_the_guard_refuses_the_cleaner_without_the_owners_answer(tmp_path):
    project = tmp_path / "h" / ".claude"
    (project / "commands").mkdir(parents=True)
    s = Session(tmp_path / "projects", project, [
        _approved("finding_2", "fix_style", location="commands/clean.md", old_line="a", new_line="b")], asked=False)
    proc = s.guard(tmp_path, "cleaner", "Edit", _edit(project / "commands" / "clean.md"))
    assert proc.returncode == 2, proc.stderr
