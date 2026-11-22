"""hooks/lib/refusal_record.py: a call two hooks refused keeps the text of each in its one line.

- Two live cases: a Bash call that both the removal policy (lib/bash_safety_rules.py, the text the CLI
  showed) and the tool policy (a /tmp write, through pretool-write-gate.py, a text of more than
  MESSAGE_MAX characters) refused. The line named both rules, but the message was cut after the two
  texts were joined, so the removal policy's text was gone and the line read as a tool-policy denial
  filed under the removal rule's name. Each rule's text is now cut on its own, and every rule the
  line names has its text in the message, whatever order the reports arrive in.
- The reader counts the call once, under each of the two rules once.

Run with: python3 -m pytest hooks/tests/test_refusal_record_every_rule_text.py -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "hooks"))

from lib import refusal_record as R  # noqa: E402

SID = "5d0c2f6e-8a41-4b7c-9e15-2f3a6b7c8d90"
SCRATCH = "/work/app/.claude/scratch/" + SID + "/dev/a1b2c3d4e5f60718"
NOTE = ('tool-policy.v1 note: the target above is INFERRED from the Bash command text by a static scan (Bash write '
        'targets are checked as Write requests, hence "tool":"Write"); it is not an observed file write. Inferred '
        'target: "{t}"; read from the command segment: "{seg}". If the command does not really write that path, '
        'reword it: keep the checkpoint id as the LAST argument of the marking command, quote it (--cp-id "cp-01"), '
        'or drop the trailing redirect (such as 2>&1) and any pipe after it. To really write a file, use an absolute '
        'allowed scratch path.\ntool-policy.v1 scratch: your own scratch directory is ' + SCRATCH + '/ (mkdir -p '
        + SCRATCH + ' first; a program that writes under $TMPDIR: TMPDIR=' + SCRATCH + ' <command>)\n')
REMOVAL = ("BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm\nCommand: {cmd}\nREASON: every "
           "execution boundary must be provably inert or a provably non-filesystem removal (e.g. git rm --cached, docker "
           "container rm) or a recoverable git rm (no -f, outside the harness home, no submodule); this command has a "
           "boundary that is none of these.\nRelease: the user can authorize this command with /do or a matching /allow "
           "grant.\ntool-policy.v1 scratch: your own scratch directory is " + SCRATCH + "/\n")
CASES = {  # role, the command, the /tmp target, the segment it was read from, the tool policy's deny reason
    "dev heredoc to /tmp": ("dev", "cd /work/app; cat > /tmp/dbg_test.py <<'EOF'\nimport sys\nEOF\ncp /tmp/dbg_test.py "
                            "tests/test_dbg_tmp.py; python3 -m pytest tests/test_dbg_tmp.py -q; rm tests/test_dbg_tmp.py",
                            "/tmp/dbg_test.py", "cat > /tmp/dbg_test.py <<'EOF'",
                            "arbitrary /tmp and /var/tmp are denied for every role",
                            "blocked-by-tool-policy.v1-arbitrary-and-are-denied-for"),
    "qa tee to /tmp": ("qa", "cd /work/app; git diff-tree -r --name-status HEAD | tee /tmp/qa-c3.txt; "
                       "for f in $(awk '{print $2}' /tmp/qa-c3.txt); do ls -la \"$f\"; done; rm -f /tmp/qa-c3.txt",
                       "/tmp/qa-c3.txt", "tee /tmp/qa-c3.txt", "write target /tmp/qa-c3.txt not in allowed_write_path_prefixes",
                       "blocked-by-tool-policy.v1-write-target-not-in-allowed_write_path_prefixes"),
}
RULES = "hooks/lib/bash_safety_rules.py"
REMOVAL_ID = "blocked-removal-policy-forbidden_removal-filesystem_removal"


def reports(case):
    role, cmd, target, seg, reason, _ = CASES[case]
    head = "BLOCKED by tool-policy.v1: " + json.dumps({"role": role, "tool": "Write", "target": target,
                                                         "deny_reason": reason}, separators=(",", ":"))
    policy = head + "\n" + NOTE.format(t=target, seg=seg)
    p = {"hook_event_name": "PreToolUse", "session_id": SID, "cwd": "/work/app", "tool_name": "Bash",
         "tool_use_id": "toolu_01", "tool_input": {"command": cmd}, "agent_id": "a1b2c3d4e5f60718", "agent_type": role}
    return p, (RULES, REMOVAL.format(cmd=cmd)), ("hooks/pretool-tool-policy.py", policy)


def lines() -> list[dict]:
    folder = Path(R.directory())
    return [json.loads(x) for f in sorted(folder.glob("refusals-*.jsonl")) for x in f.read_text().splitlines()]


def ids_in(message: str, p: dict) -> set:
    skip = {str(p[k]) for k in ("tool_name", "agent_type", "agent_id", "session_id")}
    rows = message.splitlines()
    return {R.rule_id("\n".join(rows[i:]), skip) for i in range(len(rows))}


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.mark.parametrize("case", sorted(CASES))
@pytest.mark.parametrize("removal_first", [True, False])
def test_a_call_two_hooks_refused_holds_each_rules_text(case, removal_first):
    p, removal, policy = reports(case)
    assert len(policy[1]) > R.MESSAGE_MAX  # the live text: longer than one rule's share on its own
    first, second = ((removal, RULES), (policy, "hooks/pretool-write-gate.py"))[::1 if removal_first else -1]
    assert R.write(p, [first[0]], first[1]) and R.write(p, [second[0]], second[1])
    (line,) = lines()
    named = {r["id"] for r in line["rules"]}
    assert named == {REMOVAL_ID, CASES[case][5]}
    assert named <= ids_in(line["message"], p), "a rule the line names has no text in its message"


@pytest.mark.parametrize("case", sorted(CASES))
def test_one_report_of_two_rules_holds_each_rules_text(case):
    p, removal, policy = reports(case)
    assert R.write(p, [policy, removal], "hooks/pretool-write-gate.py")
    (line,) = lines()
    assert {r["id"] for r in line["rules"]} <= ids_in(line["message"], p)


def test_the_reader_counts_the_call_once_under_each_rule(home):
    p, removal, policy = reports("qa tee to /tmp")
    R.write(p, [removal], RULES)
    R.write(p, [policy], "hooks/pretool-write-gate.py")
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
    out = subprocess.run([sys.executable, str(REPO / "scripts" / "refusals"), "--json", "--since", "2000-01-01"],
                         capture_output=True, text=True, env=env, timeout=120)
    s = json.loads(out.stdout)
    assert s["refusals"] == 1
    assert sorted(s["by_rule"]) == sorted([[f"{RULES} {REMOVAL_ID}", 1],
                                           [f"hooks/pretool-tool-policy.py {CASES['qa tee to /tmp'][5]}", 1]])
