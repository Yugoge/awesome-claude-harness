"""The inventory's hooks_only control state (lib/harness_temp_state LOCATIONS) is refused to every agent.

hooks/pretool-tool-policy.py `_protected` reads the inventory: an entry marked hooks_only, and a directory
holding one, is not written, edited, moved or removed by any agent through a file tool or a shell command
the policy reads. Its hooks write it without a tool call, so their writes pass. The owner's /allow releases
such a refusal like any other (lib/hook_launch.release_refused). Throwaway state, scratch and home only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
POLICY = HOOKS / "pretool-tool-policy.py"
SID = "sess-0001"
PRODUCT = "/nonexistent-hooks-only-state/product"
sys.path.insert(0, str(HOOKS))

from lib import harness_temp_state  # noqa: E402

# Each hooks_only entry: the path below the throwaway roots ("state" or "scratch", the session scratch root).
ENTRIES = {
    "lane-ledger": ("state", "lane-ledger/s-1/lane-1.json"),
    "returns-hold": ("state", f"returns-hold/{SID}.json"),
    "tool-ran": ("state", f"claude-tool-ran-{SID}.log"),
    "checkpoint-overtime": ("state", ".checkpoint-overtime-0123abcd"),
    "codex-unavailable": ("state", "codex-unavailable.json"),
    "report-provenance": ("state", "report-provenance/k.json"),
    "dispatch-temp-state": ("scratch", f"{SID}/.dispatch-tmp"),
    "scratch-owner": ("scratch", f"{SID}/.owner"),  # policy_registry._began_before reads it: no agent backdates it
}
CALLERS = {"main": None, "dev": ("a0dev", "dev")}


def environ(tmp_path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "CODEX_"))}
    home = tmp_path / "home"
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=PRODUCT,
               CLAUDE_STATE_DIR=str(tmp_path / "state"), TMPDIR=str(tmp_path / "scratch"),
               PYTHONDONTWRITEBYTECODE="1", CLAUDE_SESSION_ID=SID)
    return env


def entry(tmp_path, name: str, create: bool = False) -> str:
    root, rel = ENTRIES[name]
    path = tmp_path / root / rel
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n")
    return str(path)


def run(tmp_path, tool: str, tool_input: dict, caller=None, hook=POLICY, n=1):
    payload = {"session_id": SID, "transcript_path": str(tmp_path / "none.jsonl"), "cwd": PRODUCT,
               "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
               "tool_use_id": f"toolu_{tool}_{n}"}
    if caller:
        payload.update(agent_id=caller[0], agent_type=caller[1], subagent_type=caller[1])
    return subprocess.run([sys.executable, str(hook)], input=json.dumps(payload), capture_output=True, text=True,
                          cwd=str(tmp_path), env=environ(tmp_path), timeout=120)


def forms(path: str) -> dict:
    return {"Write": ("Write", {"file_path": path, "content": "x"}),
            "Edit": ("Edit", {"file_path": path, "old_string": "{", "new_string": "["}),
            "echo": ("Bash", {"command": f"echo x > {path}"}),
            "sed": ("Bash", {"command": f"sed -i 's/a/b/' {path}"}),
            "rm": ("Bash", {"command": f"rm -f {path}"}),
            "mv": ("Bash", {"command": f"mv {path} {path}.bak"})}


def assert_refused(proc) -> str:
    assert proc.returncode == 2, proc.stderr
    assert proc.stderr.startswith("BLOCKED by tool-policy.v1: "), proc.stderr
    reason = json.loads(proc.stderr.splitlines()[0].split(": ", 1)[1])["deny_reason"]
    assert reason.endswith("no agent writes, deletes or renames it (D11/D12)"), reason
    return reason


def test_the_inventory_marks_each_entry_hooks_only(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "scratch"))
    for name in ENTRIES:
        loc = harness_temp_state.classify(entry(tmp_path, name))
        assert loc is not None and loc.name == name and loc.hooks_only, name


@pytest.mark.parametrize("caller", sorted(CALLERS))
@pytest.mark.parametrize("form", sorted(forms("x")))
@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_every_write_form_of_a_hooks_only_entry_is_refused(tmp_path, name, form, caller):
    tool, tool_input = forms(entry(tmp_path, name, create=True))[form]
    assert_refused(run(tmp_path, tool, tool_input, CALLERS[caller]))


@pytest.mark.parametrize("verb", ["rm -rf {d}", "mv {d} {d}.old"])
@pytest.mark.parametrize("name", sorted(ENTRIES))
def test_a_directory_holding_a_hooks_only_entry_is_not_removed_or_moved(tmp_path, name, verb):
    """Refused as the entry it holds. An entry directly in the state root is put in the scratch root, also a root of
    the inventory's names: removing the state root is refused as the report-provenance ledger's holder whatever it holds."""
    root, rel = ENTRIES[name]
    path = tmp_path / ("scratch" if root == "state" and "/" not in rel else root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n")
    reason = assert_refused(run(tmp_path, "Bash", {"command": verb.format(d=path.parent)}, CALLERS["dev"]))
    if name not in ("report-provenance", "dispatch-temp-state"):  # those two have their own, older labels
        assert f"is harness control state ({name})" in reason, reason


def test_reading_it_and_writing_beside_it_pass(tmp_path):
    path = entry(tmp_path, "lane-ledger", create=True)
    assert run(tmp_path, "Bash", {"command": f"cat {path}"}).returncode == 0
    other = tmp_path / "state" / "unrelated-notes.txt"
    assert run(tmp_path, "Bash", {"command": f"echo x > {other}"}).returncode == 0
    empty = tmp_path / "state" / "empty-dir"
    empty.mkdir(parents=True)
    assert run(tmp_path, "Bash", {"command": f"rm -rf {empty}"}).returncode == 0


def test_the_hooks_own_writes_pass(tmp_path, monkeypatch):
    """The lane record's and the hold's writers write without a tool call: the policy never stands between."""
    from lib import lane_ledger, returns_hold

    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path / "state"))
    repo = tmp_path / "project"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / "a.py").write_text("v1\n")
    lane_ledger.record({"session_id": "s-1", "agent_id": "lane-1", "agent_type": "dev", "tool_name": "Edit",
                        "tool_use_id": "tu-1", "cwd": str(repo), "tool_input": {"file_path": str(repo / "a.py")}})
    record = lane_ledger._path("s-1", "lane-1")
    assert str(repo / "a.py") in json.loads(Path(record).read_text())["files"]
    assert str(record) == entry(tmp_path, "lane-ledger")
    hold = returns_hold._path(SID)
    returns_hold._save(hold, {"held": []})
    assert json.loads(Path(hold).read_text()) == {"held": []} and hold == entry(tmp_path, "returns-hold")
    assert_refused(run(tmp_path, "Edit", {"file_path": str(record), "old_string": "{", "new_string": "["},
                       CALLERS["dev"]))


@pytest.mark.parametrize("caller", sorted(CALLERS))
@pytest.mark.parametrize("form", sorted(forms("x")))
def test_another_sessions_owner_record_is_refused_too(tmp_path, form, caller):
    other = tmp_path / "scratch" / "sess-0002" / ".owner"
    other.parent.mkdir(parents=True)
    other.write_text(json.dumps({"sid": "sess-0002", "created_at": "2000-01-01T00:00:00Z"}))
    assert_refused(run(tmp_path, *forms(str(other))[form], CALLERS[caller]))


def test_the_session_start_hook_writes_the_owner_record(tmp_path):
    """hooks/session-scratch-init.sh writes .owner without a tool call; an agent's Write of the same file is refused."""
    env = dict(environ(tmp_path), CLAUDE_CODE_SESSION_ID=SID)
    p = subprocess.run(["bash", str(HOOKS / "session-scratch-init.sh")], input=json.dumps({"session_id": SID}),
                       capture_output=True, text=True, env=env, timeout=60)
    owner = Path(entry(tmp_path, "scratch-owner"))
    assert p.returncode == 0 and json.loads(owner.read_text())["sid"] == SID, p.stdout + p.stderr
    assert_refused(run(tmp_path, *forms(str(owner))["Write"]))


def _prompt(tmp_path, text: str) -> None:
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": SID, "prompt": text, "cwd": PRODUCT}
    p = subprocess.run(["bash", str(HOOKS / "userprompt-consent-allowlist.sh")], input=json.dumps(payload),
                       capture_output=True, text=True, env=environ(tmp_path), timeout=60)
    assert p.returncode == 0, p.stderr


def test_the_owners_allow_releases_the_refusal(tmp_path):
    (tmp_path / "home").mkdir()
    edit = {"file_path": entry(tmp_path, "lane-ledger", create=True), "old_string": "{", "new_string": "["}
    launcher = HOOKS / "pretool-launch.py"
    assert run(tmp_path, "Edit", edit, hook=launcher).returncode == 2
    _prompt(tmp_path, "/allow")
    released = run(tmp_path, "Edit", edit, hook=launcher, n=2)
    assert released.returncode == 0, released.stderr
    assert "RELEASED" in json.loads(released.stdout)["systemMessage"]
