"""Contract tests for shared /dev artifact-chain consumers.

Each command that reads the artifact chain spells one resolver call and names the result fields it hands
on. Each test runs that call as the command spells it, from the harness home, against a fixture project,
and checks the resolver's own output carries every field the text names, so a call or field name that
drifts from the resolver fails here (P15 L7).
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
TASK = "20260101-000010"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dev_lifecycle_fixtures import (  # noqa: E402
    ba_qa_report, close_report_text, completion_md, dev_dir, dev_report, make_project, qa_report, write_json,
    write_text, write_ticket_fixture,
)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _squash(text: str) -> str:
    return " ".join(text.split())


def _resolver_fences(text: str) -> list[str]:
    return [body for body in re.findall(r"```bash\n(.*?)```", text, re.S) if "resolve-dev-artifact-chain.py" in body]


def _ticks(text: str) -> list[str]:
    return [name.rstrip("[]") for name in re.findall(r"`([^`\n]+)`", text)]


def _passing_singular(tmp_path: Path) -> Path:
    project = make_project(tmp_path)
    write_ticket_fixture(project, TASK)
    write_json(dev_dir(project) / f"ba-qa-report-{TASK}.json", ba_qa_report(TASK, top_verdict="pass"))
    write_json(dev_dir(project) / f"dev-report-{TASK}.json", dev_report(TASK))
    write_json(dev_dir(project) / f"qa-report-{TASK}.json", qa_report(TASK))
    write_text(dev_dir(project) / f"completion-{TASK}.md", completion_md(TASK))
    write_text(dev_dir(project) / f"close-report-{TASK}.md", close_report_text(TASK, "CLOSE: YES"))
    return project


def _run(script: str, project: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_HOME": str(ROOT), "TASK_ID": TASK, "CLAUDE_PROJECT_DIR": str(project)}
    return subprocess.run(["bash", "-c", script], cwd=project, env=env, capture_output=True, text=True, timeout=120)


def _dev(project: Path) -> tuple[str, dict, list[str]]:
    """commands/dev.md: the completion postcondition's call binds ARTIFACT_CHAIN to the resolver's JSON."""
    text = _read("commands/dev.md")
    section = text[text.index("**Codex-native artifact postcondition"):]
    [fence] = _resolver_fences(section[:section.index("\n## ")])
    done = _run(fence.replace("<TASK_ID>", TASK) + 'printf "%s" "$ARTIFACT_CHAIN"\n', project)
    assert done.returncode == 0, done.stderr
    fields = _ticks(re.search(r"same result object \(([^)]*)\)", section).group(1))
    return done.stdout, json.loads(done.stdout), fields


def _disposition(project: Path, command: str, stage: str, named_in: str) -> tuple[str, dict, list[str]]:
    """A /close or /commit disposition call: one resolver fence in the whole command, its CHAIN= line."""
    text = _read(command)
    [fence] = _resolver_fences(text)
    assert f"--disposition --stage {stage} " in fence, fence
    done = _run(fence.replace("<PROJECT_ROOT>", str(project)), project)
    assert done.returncode == 0, done.stderr
    assert f"DISPOSITION=chain_pass STAGE={stage} TASK={TASK}" in done.stdout.splitlines(), done.stdout
    [chain] = [line[len("CHAIN="):] for line in done.stdout.splitlines() if line.startswith("CHAIN=")]
    return done.stdout, json.loads(chain), _fields_named(text, named_in)


def _fields_named(text: str, where: str) -> list[str]:
    if where == "close Step 0":
        bullet = next(line for line in text[text.index("### Step 0:"):].splitlines() if line.startswith("- **Exit 0**"))
        return _ticks(bullet[bullet.index("its `"):bullet.index(" are the data")])
    return sorted(set(re.findall(r"ARTIFACT_CHAIN\.(\w+)", text)))


def _spec_update(project: Path) -> tuple[str, dict, list[str]]:
    """commands/spec-update.md: a /spec-update typed on its own runs the fixed entrypoint itself."""
    text = _read("commands/spec-update.md")
    section = text[text.index("## Continuation-spec mode"):text.index("## Temp-note mode")]
    [call] = [c for c in re.findall(r"`([^`\n]+)`", section) if c.startswith("python3") and "resolve-dev" in c]
    done = _run(call.replace("<HARNESS_ROOT>", str(ROOT)).replace("<id>", TASK).replace("<root>", str(project)),
                project)
    assert done.returncode == 0, done.stderr
    named = section[section.index("Read the existing paths named by"):section.index("plus\n`docs/dev/close-report")]
    return done.stdout, json.loads(done.stdout), _ticks(named)


READERS = {
    "dev": _dev,
    "close": lambda project: _disposition(project, "commands/close.md", "dev", "close Step 0"),
    "commit": lambda project: _disposition(project, "commands/commit.md", "close", "commit ARTIFACT_CHAIN"),
    "spec-update": _spec_update,
}


@pytest.mark.parametrize("command", sorted(READERS))
def test_the_chain_call_a_command_spells_runs_the_resolver_and_yields_the_fields_it_names(
        tmp_path: Path, command: str) -> None:
    out, chain, fields = READERS[command](_passing_singular(tmp_path))
    assert fields, out
    missing = [field for field in fields if field not in chain]
    assert missing == [], (missing, sorted(chain))
    assert chain["mode"] == "singular" and chain["lanes"] == [], chain
    assert f"docs/dev/dev-report-{TASK}.json" in chain["commit_whitelist_artifacts"]


def test_commit_completes_an_unclosed_task_from_one_disposition() -> None:
    """P4 R5: an incomplete disposition is completed (dev-stage gaps routed, the close
    stage as close.md Steps 1-2), nobody is asked, nothing re-validates."""
    command = _read("commands/commit.md")
    step3 = command[command.index("### Step 3:") : command.index("### Step 4:")]
    flat = _squash(step3)

    assert "route it (Routes)" in flat
    assert "run `commands/close.md` Steps 1-2 for this task id" in flat
    assert "OPERATION_STALLED: <the error>" in flat
    # D10 (--dry-run): the cycle completes first; no close-gate relaxation is left.
    assert "`--dry-run` completes the cycle here exactly as a real run does" in flat
    assert "DRYRUN" not in step3 and "check 2 relaxed" not in command
    # The disposition alone decides; no close-report age is read (2026-11-20).
    assert "close-report age" not in command and "stat -c %Y" not in step3
    assert "check 4" not in command.lower() and "FORCED" not in command
    for gone in ("AWAITING_INPUT", "awaiting-input", "R15", "arbitrat", "route_finding", "owing_dispatch",
                 "pass_with_exceptions", "artifact_role", "source_check"):
        assert gone not in command, gone
    # Nobody is asked (2026-11-19): each former wait ends in a statement, the line the Stop gate reads.
    assert __import__("re").findall(r"header `([^`]+)`", command) == [] and "AskUserQuestion" not in command
    assert "`NO_TARGET: " in command and "`REFUSED: <hook> refused <the operation> for task <TASK_ID>`" in command
    assert "/stop" not in command and "I will fix the harness" not in command
    related = command[command.index("## Related") :]
    assert "may run first; `/commit` completes an unclosed task itself" in related
