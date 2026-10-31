"""write-qa-mode.sh is an exit-0 stub (P1b E7, acceptance 17).

Each QA dispatch's obligation now declares the report it owes, so no qa_mode
switch is written. A session that took up the earlier command text still runs
every call that text made, by path (the overnight calls execute the script
directly); each must exit 0 and create or change nothing, with or without
CLAUDE_PROJECT_DIR and whether or not the session's qa.json exists.
"""

import os
from pathlib import Path
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
STUB = ROOT / "scripts/write-qa-mode.sh"

# The calls of the earlier text: commands/dev.md Steps 7 and 13,
# commands/dev-command.md Steps 7 and 12, commands/dev-overnight.md Steps 10,
# 15, 17 and 20, commands/close.md's QA arming.
CALLS = [
    ["--session-id", "dev-20260101-000000", "--mode", "ba_validation"],
    ["--session-id", "dev-20260101-000000", "--mode", "final_verification", "--task-id", "20260101-000000"],
    ["--session-id", "dev-20260101-000000", "--mode", "final_verification"],
    ["--session-id", "dev-20260101-000000", "--mode", "final_verification", "--task-id", "20260101-000000",
     "--init-if-missing"],
]


def _tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def test_stub_answers_every_earlier_call_with_exit_0_and_writes_nothing(tmp_path):
    assert STUB.stat().st_mode & stat.S_IXUSR, "the overnight text executes it by path"
    assert any(line.startswith("# STUB:") for line in STUB.read_text().splitlines())
    project = tmp_path / "proj"
    sentinel = project / ".claude/dev-registry/dev-20260101-000000/qa.json"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text('{"agent_type": "qa", "session_id": "dev-20260101-000000"}\n')
    bare = tmp_path / "bare"  # an in-flight close: no registry, no qa.json
    bare.mkdir()
    for root in (project, bare):
        before, before_bytes = _tree(root), sentinel.read_bytes()
        for args in CALLS:
            for env_root in (root, None):
                env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
                env["HOME"] = str(tmp_path / "home")
                if env_root is not None:
                    env["CLAUDE_PROJECT_DIR"] = str(env_root)
                for argv in (["bash", str(STUB), *args], [str(STUB), *args]):
                    proc = subprocess.run(argv, text=True, capture_output=True, env=env, cwd=root)
                    assert proc.returncode == 0, (argv, proc.stderr)
        assert _tree(root) == before
        assert sentinel.read_bytes() == before_bytes
    assert not (tmp_path / "home").exists()
