"""Non-executing replay harness for the pinned POL 436-case matrix.

ZERO-EXECUTION CONTRACT (LANE-POL AC-R02-06). Every ``command`` string in the
fixture is DATA. It is delivered to the hook as JSON on stdin — the same shape
Claude Code's PreToolUse protocol uses — and is never executed, expanded,
eval'd, or passed to a shell. The only process this module ever spawns is the
hook itself (``bash hooks/pretool-bash-safety.sh``) and, in the pytest
delegates, ``python3 -m pytest``.

The replay is memoized so that the four ACs derived from it (zero mismatch,
non-empty denial reasons, zero-execution scan, latency budget) cost one pass
rather than four.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import statistics
import subprocess
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HOOK = os.path.join(REPO_ROOT, "hooks", "pretool-bash-safety.sh")
FIXTURE = os.path.join(REPO_ROOT, "hooks", "tests", "fixtures",
                       "pol_iteration5_qa_matrix.v1.json")
FIXTURE_SHA256 = "142c584a99a370d3093811aa412b4161c2c066616ad8911221f57874cd9492d6"

# Baseline measured against the pre-change hook on this host (BA, 2026-08-19).
BASELINE_MEDIAN_ROW_SECONDS = 0.62
LATENCY_BUDGET_SECONDS = 1.24

# Rows the fixture pins at exit 2 that the owner's rule of 2026-11-19 lets run: the analyzer cannot prove them
# (UNRESOLVED) and the text that can become the command they leave unresolved (the analyzer's unresolved_scopes)
# holds no removal word by lib/pol_degraded_removal_reference.ere, so the removal policy hands them to the record
# instead of refusing them. The fixture's bytes stay as pinned (FIXTURE_SHA256); the expectation changes here, row by
# row. hooks/tests/test_removal_policy_unproven_rule.py checks that this is exactly the set the rule names: 8
# spellings of a removal program that name it nowhere (`${R}${M}`, `/bin/r?`), 5 malformed or dynamic commands
# (`bash -c`, `env -S`, `echo >`, `$UNKNOWN x`, `command $UNKNOWN x`), an unclosed here-document, a git call with a
# dynamic subcommand, and `source /tmp/rm` / `. /tmp/rm` (a file path, which is no command). The ANSI-C spellings
# (`$'\x72m'`) and the names joined across an empty variable (`r${EMPTY}m`) are refused again: their words read rm.
OWNER_RULE_LET_THROUGH = frozenset((
    "POL-I5-QA-0084-914770c8959f", "POL-I5-QA-0085-a0c10bf1a26d",
    "POL-I5-QA-0098-93d772555372", "POL-I5-QA-0099-81a09f252f22",
    "POL-I5-QA-0100-a12dd130c0ba", "POL-I5-QA-0101-a670c8644aea", "POL-I5-QA-0105-86303ae06b6f",
    "POL-I5-QA-0108-a8492862a7e5", "POL-I5-QA-0230-bbc5e6185472", "POL-I5-QA-0231-4d6b7b3bcc1a",
    "POL-I5-QA-0276-86818c50ffad",
    "POL-I5-QA-0324-28ac7559ff6a", "POL-I5-QA-0431-ee907a2944eb", "POL-I5-QA-0432-e640ec8c4c88",
    "POL-I5-QA-0433-328ae02d0ce8", "POL-I5-QA-0435-0bf3eb9e0d1c", "POL-I5-QA-0436-97b1f355417c",
))


def expected_exit(row) -> int:
    """The exit code a fixture row is held to: its pinned one, or 0 where the owner's rule lets the row run."""
    return 0 if row["id"] in OWNER_RULE_LET_THROUGH else row["expected_hook_exit_code"]


def fixture_digest() -> str:
    h = hashlib.sha256()
    with open(FIXTURE, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_fixture() -> dict:
    with open(FIXTURE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def run_hook_payload(payload: str, hook: str = HOOK, env=None):
    """Feed one raw JSON payload to the hook. Returns (returncode, out, err)."""
    proc = subprocess.run(
        ["bash", hook],
        input=payload,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_hook_command(command: str, hook: str = HOOK, env=None):
    """Wrap ``command`` as tool_input data. The command is NEVER executed."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return run_hook_payload(payload, hook=hook, env=env)


@functools.lru_cache(maxsize=1)
def replay_all():
    """Replay all 436 fixture rows through the hook. Returns a tuple of dicts."""
    rows = load_fixture()["rows"]
    results = []
    for row in rows:
        started = time.monotonic()
        code, _out, err = run_hook_payload(row["stdin_envelope"])
        results.append({
            "id": row["id"],
            "category": row["category"],
            "expected_class": row["expected_class"],
            "expected": expected_exit(row),
            "actual": code,
            "stderr": err,
            "seconds": time.monotonic() - started,
        })
    return tuple(results)


def mismatches():
    return [r for r in replay_all() if r["actual"] != r["expected"]]


def dangerous_rows():
    return [r for r in replay_all() if r["expected"] == 2]


def safe_rows():
    return [r for r in replay_all() if r["expected"] == 0]


def median_row_seconds():
    return statistics.median([r["seconds"] for r in replay_all()])


def run_pytest(paths):
    """Run pytest over ``paths`` in a child process; return (returncode, output)."""
    proc = subprocess.run(
        ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider"] + list(paths),
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )
    return proc.returncode, proc.stdout + proc.stderr


# Target basenames the fixture's commands would create IF any of them were
# executed. Derived FROM the fixture rather than hand-listed, so the scan stays
# exact (no unrelated "qa-*" file can masquerade as execution evidence) and
# cannot drift from the fixture. `tracked.txt` / `other.txt` come from the
# ported historical control sets.
_TARGET_TOKEN_RE = __import__("re").compile(r"\bqa-[A-Za-z0-9][A-Za-z0-9._-]*")
FIXTURE_TARGET_EXTRA = ("tracked.txt", "other.txt")
SCAN_ROOTS = (REPO_ROOT, "/dev/shm/claude-scratch")
SCAN_SKIP_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv",
                  "worktrees", "fixtures"}


@functools.lru_cache(maxsize=1)
def fixture_target_names():
    names = set(FIXTURE_TARGET_EXTRA)
    for row in load_fixture()["rows"]:
        names.update(_TARGET_TOKEN_RE.findall(row["command"]))
    return frozenset(names)


def scan_for_executed_targets():
    """Return paths that would only exist if a fixture command had executed."""
    targets = fixture_target_names()
    found = []
    seen_roots = set()
    for root in SCAN_ROOTS:
        root = os.path.abspath(root)
        if root in seen_roots or not os.path.isdir(root):
            continue
        seen_roots.add(root)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SCAN_SKIP_DIRS]
            for name in filenames:
                if name in targets:
                    found.append(os.path.join(dirpath, name))
            if len(found) > 50:
                return found
    return found
