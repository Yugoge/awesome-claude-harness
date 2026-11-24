"""The programs that write a file are one reading: hooks/lib/shell_parse.py's write targets (VERBS).

Before, a write through sort -o, touch, uniq IN OUT, sponge, gsed -i, perl -pi or gawk -i inplace
passed the guards that read the shared parser (tool policy, bash-views guard) while the same write
through a redirect was refused; the config guard read touch, perl -i and sort -o with private code
and missed the rest; the bash-views guard read touch with a private option table. The parser now
reads each of them, and every guard decides alike on the audit's writes.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS / "lib"))
import shell_parse  # noqa: E402
sys.path.pop(0)

WRITES = ["printf x | sponge {T}", "gsed -i s/a/b/ {T}", "perl -pi -e s/a/b/ {T}", "touch {T}",
          "sort -o {T} /etc/hostname", "sort --output={T} /etc/hostname", "uniq /etc/hostname {T}",
          "gawk -i inplace '{print}' {T}",
          "printf x > {T}"]  # the redirect they now agree with
READS = ["sort {T}", "uniq -c {T}", "perl -ne print {T}", "gawk '{print}' {T}"]
# hook -> (its protected target, the subagent role it runs for)
HOOK_TARGETS = {
    "pretool-claude-config-guard.py": (".claude/hooks/x.py", None),
    "pretool-harness-switch-guard.py": (".claude/settings.json", None),
    "pretool-tool-policy.py": ("src/x.py", ("a1", "qa")),
    "pretool-bash-views-guard.py": (".claude/specs/s1/cp-state-dev.json", None),
}


def _hook(name: str, command: str, agent, project: Path, home: Path) -> int:
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command},
               "cwd": str(project), "session_id": "writers", "transcript_path": str(project / "t.jsonl"),
               "permission_mode": "default", "tool_use_id": "toolu_writers"}
    if agent:
        payload.update(agent_id=agent[0], agent_type=agent[1], subagent_type=agent[1])
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "CODEX"))}
    env.update(HOME=str(home), CLAUDE_PROJECT_DIR=str(project), CLAUDE_CONFIG_DIR=str(home / ".claude"),
               CLAUDE_STATE_DIR=str(home / "state"))
    return subprocess.run([sys.executable, str(HOOKS / name)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(project), env=env, timeout=60).returncode


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("writers")
    p = root / "proj"
    for d in ("src", ".claude/hooks", ".claude/specs/s1"):
        (p / d).mkdir(parents=True)
    (p / ".claude" / "settings.json").write_text("{}\n")
    (root / "home" / ".claude").mkdir(parents=True)
    (root / "home" / "state").mkdir()
    return p


def _codes(project, template):
    return {name: _hook(name, template.replace("{T}", t), agent, project, project.parent / "home")
            for name, (t, agent) in HOOK_TARGETS.items()}


@pytest.mark.parametrize("template", WRITES)
def test_every_guard_refuses_the_write(project, template):
    assert _codes(project, template) == dict.fromkeys(HOOK_TARGETS, 2)


@pytest.mark.parametrize("command,targets", [
    ("sort -o T f", ["T"]), ("sort -uo T f", ["T"]), ("sort --outp=T f", ["T"]), ("sort -t o f", []),
    ("touch -r ref T", ["T"]), ("touch -d now T", ["T"]), ("uniq a T", ["T"]), ("uniq -f 1 a", []),
    ("sponge -a T", ["T"]), ("gsed -i s/a/b/ T", ["T"]), ("perl -i.bak -pe 1 T U", ["T", "U"]),
    ("perl -e 1 T", []), ("gawk -i inplace -v x=1 '{print}' T x=2", ["T"]), ("gawk '{print}' T", []),
])
def test_the_parser_reads_each_writer(command, targets):
    assert [t.path for t in shell_parse.write_targets(command)] == targets


@pytest.mark.parametrize("template", READS)
def test_the_reading_form_stays_free_where_it_was(project, template):
    codes = _codes(project, template)
    assert codes["pretool-tool-policy.py"] == 0 and codes["pretool-bash-views-guard.py"] == 0
