"""P10-13: P9's parts of P10's rows R9, R14 and R17, each checked against the tree.

- R9 (the harness home's .gitignore): the old score store's lines stay under D28. Nothing writes
  agent-scores.json any more (score-update.sh writes logs/lifecycle.jsonl), and live homes still hold
  it, so `/agent-scores.json`, its lock and `logs/*` keep both out of `git status` and the checkpoint
  snapshots (P9 A12 (c)).
- R14 (/clean's outputs): P9's prose (commands/clean.md, the inspector and cleaner agents) sends each
  /clean producer's output to the path its dispatch declares, and says tool-policy refuses an
  undeclared docs/clean/ or docs/dev/<role>- path. P9 A18's replay: each producer dispatched with the
  obligation block clean.md gives it writes its declared path; the same role's undeclared
  docs/dev/<role>- report is refused. The blocks are read from commands/clean.md at run time.
- R17 (settings.json): no permission entry names a file that is gone, so none names a file P9
  deleted (hooks/doc_sync/claude.py; scripts/iterate-failed-pipelines.py came back as train 2's
  compatibility script); each Skill deny names a command, a skill or the documented built-in
  code-review (P9 A13).
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "pretool-tool-policy.py"
PROJECT = Path("/nonexistent-p10-13-clean") / "proj"
REQUEST = "clean-20261109-101010"
BUILT_IN_SKILLS = {"code-review"}


def _git(env, cwd, *args, stdin=None):
    return subprocess.run(["git", *args], cwd=cwd, env=env, input=stdin, capture_output=True, text=True)


# --- R9 -------------------------------------------------------------------------------------------

SCORE_STORE = ["agent-scores.json", "agent-scores.json.lock", "logs/lifecycle.jsonl", "logs/lifecycle.jsonl.lock"]


def test_the_old_score_store_stays_ignored_in_the_harness_home(tmp_path):
    home = tmp_path / "harness"
    home.mkdir()
    (home / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path),
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    assert _git(env, home, "init", "-q").returncode == 0
    for rel in SCORE_STORE:
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text("{}\n")
    status = _git(env, home, "status", "--porcelain", "--ignored", "--untracked-files=all", "--",
                  *SCORE_STORE).stdout.splitlines()
    assert sorted(status) == sorted(f"!! {rel}" for rel in SCORE_STORE)
    # Anchored at the home's root: a source file of the same name elsewhere stays visible.
    assert _git(env, home, "check-ignore", "-q", "--no-index", "schemas/agent-scores.json").returncode == 1


# --- R14 ------------------------------------------------------------------------------------------

def _clean_obligations() -> dict:
    """Each /clean producer's obligation, as commands/clean.md gives it, bound to REQUEST."""
    text = (ROOT / "commands" / "clean.md").read_text(encoding="utf-8")
    found = {}
    for raw in re.findall(r'<obligation v="1">\s*(\{.*?\})\s*</obligation>', text, re.S):
        doc = json.loads(raw.replace("{REQUEST_ID}", REQUEST).replace("{GROUP_ID}", "1"))
        doc["dispatched_at"] = "2026-11-09T10:10:10Z"
        found[doc["role"]] = doc
    return found


def _block(doc: dict) -> str:
    return f'<obligation v="1">\n{json.dumps(doc)}\n</obligation>'


class Session:
    """A /clean session's transcript store as the CLI keeps it: the human's command record, each
    Agent call, the child's first record (its prompt) and the meta naming its call."""

    def __init__(self, root: Path):
        self.sid = "sess-" + uuid.uuid4().hex[:8]
        self.transcript = root / f"{self.sid}.jsonl"
        self.subagents = root / self.sid / "subagents"
        self.subagents.mkdir(parents=True)
        self._append({"type": "user", "message": {"role": "user", "content":
                      "<command-message>clean is running…</command-message>\n"
                      "<command-name>/clean</command-name>\n<command-args></command-args>"}})

    def _append(self, record: dict) -> None:
        with self.transcript.open("a") as fh:
            fh.write(json.dumps(record) + "\n")

    def dispatch(self, prompt: str, subagent_type: str) -> str:
        call_id = "toolu_" + uuid.uuid4().hex[:20]
        self._append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": call_id, "name": "Agent",
             "input": {"description": "d", "prompt": prompt, "subagent_type": subagent_type,
                       "run_in_background": False}}]}})
        agent_id = "a" + uuid.uuid4().hex[:16]
        (self.subagents / f"agent-{agent_id}.jsonl").write_text(
            json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
        (self.subagents / f"agent-{agent_id}.meta.json").write_text(
            json.dumps({"agentType": subagent_type, "toolUseId": call_id}))
        return agent_id

    def write(self, tmp_path: Path, rel: str, agent: tuple):
        payload = {"session_id": self.sid, "transcript_path": str(self.transcript), "cwd": str(PROJECT),
                   "hook_event_name": "PreToolUse", "permission_mode": "default", "tool_name": "Write",
                   "tool_input": {"file_path": str(PROJECT / rel), "content": "{}"},
                   "tool_use_id": "toolu_" + uuid.uuid4().hex[:24],
                   "agent_id": agent[0], "agent_type": agent[1], "subagent_type": agent[1]}
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        env.update({"HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                    "CLAUDE_STATE_DIR": str(tmp_path / "state"), "CLAUDE_PROJECT_DIR": str(PROJECT),
                    "PYTHONDONTWRITEBYTECODE": "1"})
        proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                              text=True, cwd=str(tmp_path), env=env, timeout=60)
        assert not PROJECT.parent.exists(), "the policy check must not create the project"
        return proc


CLEAN_PRODUCERS = ["cleanliness-inspector", "style-inspector", "prompt-inspector", "cleaner"]


def test_clean_md_declares_each_producers_output():
    assert sorted(_clean_obligations()) == sorted(CLEAN_PRODUCERS)


@pytest.mark.parametrize("role", CLEAN_PRODUCERS)
def test_each_clean_producer_writes_its_declared_output_and_no_undeclared_role_path(tmp_path, role):
    doc = _clean_obligations()[role]
    s = Session(tmp_path / "projects")
    agent = (s.dispatch(f"Context file: docs/clean/context-{REQUEST}.json\n" + _block(doc), role), role)
    for artifact in doc["artifacts"]:
        proc = s.write(tmp_path, artifact["path"], agent)
        assert proc.returncode == 0, (artifact["path"], proc.stderr)
        # The declaration allows it, not a policy row: with no dispatch record the same write is refused.
        bare = Session(tmp_path / "bare").write(tmp_path, artifact["path"], ("a" + "0" * 16, role))
        assert bare.returncode == 2 and "not in allowed_write_path_prefixes" in bare.stderr, bare.stderr
    for undeclared in (f"docs/dev/{role}-report-{REQUEST}.json", f"docs/clean/{role}-extra-{REQUEST}.json"):
        proc = s.write(tmp_path, undeclared, agent)
        assert proc.returncode == 2, (undeclared, proc.stderr)
        assert "not in allowed_write_path_prefixes" in proc.stderr, proc.stderr


# --- R17 ------------------------------------------------------------------------------------------

_FILE_TOKEN = re.compile(r"[A-Za-z0-9_./*{}:$-]+\.(?:sh|py|json|md)\b")
_HOME_PREFIX = re.compile(r"^.*?(?:\$\{CLAUDE_HOME:-\$HOME/\.claude\}|\$HOME/\.claude|~/\.claude)/")


def _permissions() -> dict:
    return json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))["permissions"]


def _named_files(entry: str) -> list:
    """The harness-relative files a permission entry names (a token ending in a file suffix whose
    path is the harness home's, or a bare scripts/, hooks/ or tests/ path)."""
    named = []
    for token in _FILE_TOKEN.findall(entry):
        rel = _HOME_PREFIX.sub("", token)
        if rel != token or re.match(r"(?:scripts|hooks|tests)/", rel):
            named.append(rel)
    return named


def test_no_permission_entry_names_a_missing_harness_file():
    perms = _permissions()
    missing = []
    for key in ("allow", "deny", "ask"):
        for entry in perms.get(key, []):
            for rel in _named_files(entry):
                if not (glob.glob(str(ROOT / rel)) if "*" in rel else (ROOT / rel).exists()):
                    missing.append((key, entry, rel))
    assert missing == []


def test_the_entry_reader_sees_the_files_p9_deleted():
    """The reader above would catch an entry naming either file P9 deleted."""
    for rel in ("hooks/doc_sync/claude.py", "scripts/iterate-failed-pipelines.py"):
        entry = f'Bash(python3 "${{CLAUDE_HOME:-$HOME/.claude}}/{rel}":*)'
        assert _named_files(entry) == [rel]
    assert not (ROOT / "hooks" / "doc_sync" / "claude.py").exists()


def test_each_skill_deny_names_a_command_a_skill_or_a_built_in():
    commands = {p.stem for p in (ROOT / "commands").glob("*.md")} - {"INDEX", "README"}
    skills = {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()} if (ROOT / "skills").is_dir() else set()
    stems = [re.match(r"Skill\(([^:)]+)", e).group(1) for e in _permissions()["deny"] if e.startswith("Skill(")]
    assert [s for s in stems if s not in commands | skills | BUILT_IN_SKILLS] == []
