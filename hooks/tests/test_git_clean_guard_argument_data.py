"""OB-L30 / BS-29: under /do, the pre-clean guard (hooks/lib/git_clean_guard.py)
read grep / rg / echo pattern text and heredoc text as a `git clean`.

The guard runs at the /do grant exit of hooks/pretool-bash-safety.sh. Before
this lane every argument word was scanned as possibly-executed text, so
`grep -rn "git clean -fd" docs/` was refused (rc 11, exit 2) exactly like a
real clean whose snapshot could not be taken. The fix tells argument DATA from
executed command words in the parser: a command proven to execute nothing
(echo, grep, rg, cat, ...), whose output reaches nothing that executes, no
longer contributes its arguments or heredoc content to the scan. It is not a
classifier pre-filter: the detector still runs on every granted command.

Two layers:
  - detector verdicts (fast, exhaustive over the carriers);
  - the real hook under /do in a directory that is NOT a git repository, so any
    SNAPSHOT verdict meets a failing snapshot and must be refused, and a NONE
    verdict must reach the /do exit.
"""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS / "lib"))
sys.path.insert(0, str(HOOKS))

from git_clean_guard import decide  # noqa: E402
from lib.harness_state_dir import harness_state_dir  # noqa: E402

HOOK = HOOKS / "pretool-bash-safety.sh"

# ---------------------------------------------------------------------------
# Must PASS under /do (verdict NONE). Each failed on the base revision.
# ---------------------------------------------------------------------------
MUST_PASS = [
    'grep -rn "git clean -fd" docs/',
    'echo "git clean -fd"',
    "rg -n 'git clean' docs/",
    "cat > docs/ci.md <<'EOF'\nCI runs git clean -fdX\nEOF",
    "cat <<'EOF'\nCI runs git clean -fdX\nEOF",
    "cat <<EOF > notes.md\n# Notes\nCI runs git clean -fdX\nEOF",
    "cat <<-EOF\n\tCI runs git clean -fdX\n\tEOF",
    "tee docs/ci.md <<'EOF'\nCI runs git clean -fdX\nEOF",
    'grep -rn "git clean -fd" docs/ | head -5',
    'echo "git clean -fd" 2>&1 | head',
    'echo "git clean -fd" > /dev/null',
    "egrep -n 'git clean -f' docs/*.md | wc -l",
    'command echo "git clean -fd"',
    'grep -rn "git clean -fd" .',
    "grep -rn 'eval' hooks/ | grep -c 'git clean'",
    # A heredoc with no terminator: bash reads its body to the end of the text
    # ("here-document delimited by end-of-file") and feeds it to the command,
    # so the body is data and no line of it is a command.
    "cat <<EOF\ngit clean -fdx",
    "cat > notes.md <<'EOF'\nrun git clean -fd later",
]

# ---------------------------------------------------------------------------
# Must still REFUSE under /do when the snapshot fails. The spliced forms are
# real hook-cwd cleans (SNAPSHOT, refused when the snapshot fails); the rest
# execute the clean somewhere unprovable (DENY). Verdicts pinned exactly so a
# SNAPSHOT that silently became NONE, or a DENY that became SNAPSHOT, is caught.
# ---------------------------------------------------------------------------
MUST_REFUSE = [
    ("g''it clean -fd", "SNAPSHOT"),
    ("git cl\\ean -fd", "SNAPSHOT"),
    ('eval "git clean -fdx"', "DENY"),
    ("git -C /x clean -fd", "DENY"),
    ('bash -c "git clean -fd"', "DENY"),
    ("sh -c 'git clean -fd'", "DENY"),
    ("$(git clean -fd)", "DENY"),
    ("`git clean -fd`", "DENY"),
    ("xargs git clean -fd", "SNAPSHOT"),
    ("bash <<EOF\ngit clean -fd\nEOF", "SNAPSHOT"),
    ("bash <<'EOF'\ngit clean -fd\nEOF", "SNAPSHOT"),
    ("sh <<EOF\ngit clean -fd\nEOF", "SNAPSHOT"),
    ("bash <<< 'git clean -fd'", "DENY"),
]

# ---------------------------------------------------------------------------
# Data-command spellings whose text DOES reach an executor. Every one must keep
# the scan; NONE here would be a granted clean run with no snapshot.
# ---------------------------------------------------------------------------
DATA_THAT_EXECUTES = [
    'echo "git clean -fd" | bash',
    "echo 'git clean -fd' | bash -s",
    'echo "git clean -fd" |& bash',
    '{ echo "git clean -fd"; } | bash',
    'for f in a; do echo "git clean -fd"; done | sh',
    'echo "git clean -fd" | grep git | sh',
    "grep -e 'git clean -fd' -r . | xargs sh",
    "$(echo git clean -fd)",
    "`echo git clean -fd`",
    'source <(echo "git clean -fd")',
    'bash <(echo "git clean -fd")',
    'echo "git clean -fd" > x.sh && bash x.sh',
    'echo "git clean -fd" | tee x.sh; sh x.sh',
    "echo 'git clean -fd' | head -1 > x.sh; . x.sh",
    'exec 3>x.sh; echo "git clean -fd" >&3; bash x.sh',
    "cat > x.sh <<'EOF'\ngit clean -fd\nEOF\nbash x.sh",
    "cat <<'EOF' | bash\ngit clean -fd\nEOF",
    "cat <<'EOF' | sh -s\ngit clean -fd\nEOF",
    # With no terminator the body still reaches the shell it feeds.
    "bash <<EOF\ngit clean -fd",
    "cat <<'EOF' | bash\ngit clean -fd",
    "$(cat <<'EOF'\ngit clean -fd\nEOF\n)",
    "cat <<EOF\n$(git clean -fd)\nEOF",
    "cat <<EOF\n`git clean -fd`\nEOF",
    # The name itself rebound in the same text.
    'grep() { eval "$@"; }; grep "git clean -fd"',
    "function grep { eval \"$@\"; }; grep 'git clean -fd'",
    "alias grep=bash; grep 'git clean -fd'",
    'PATH=/tmp/x:$PATH grep "git clean -fd"',
    'export PATH=/tmp/x; echo "git clean -fd"',
    ". ./functions.sh; grep 'git clean -fd'",
    # A program-running option, or one an expansion could supply.
    "rg --pre sh 'git clean -fd' docs/",
    "rg --pre=sh 'git clean -fd' docs/",
    "rg $OPTS 'git clean -fd' docs/",
    # A wrapper option or assignment in front ends the proof.
    "sudo -u root echo git clean -fd",
    "FOO=1 echo git clean -fd && FOO=1 bash -c 'git clean -fd'",
    # Embedded payloads are never exempt: the outer program executes them.
    "bash -c 'echo \"git clean -fd\" | sh'",
    "git rebase -x 'echo x; git clean -fd' HEAD~1",
    # A heredoc whose delimiter carries an expansion is not captured; the line
    # after the literal terminator is a real command.
    "cat <<$X\nfoo\n$X\ngit clean -fd",
    # With no terminator its lines are still scanned, as on OB-L30's head.
    "cat <<$X\ngit clean -fd",
    # A real clean next to data still snapshots.
    "echo hi && git clean -fd",
    "cat <<'EOF'\nnotes\nEOF\ngit clean -fd",
    "if grep -q 'git clean' f; then git clean -fd; fi",
    "cat <<A; bash <<B\nx\nA\ngit clean -fd\nB",
    "git clean -fd <<< '-n'",
]


@pytest.mark.parametrize("command", MUST_PASS)
def test_argument_and_heredoc_data_is_not_a_clean(command):
    verdict, reason = decide(command)
    assert verdict == "NONE", (command, verdict, reason)


@pytest.mark.parametrize("command,expected", MUST_REFUSE)
def test_executed_clean_keeps_its_verdict(command, expected):
    assert decide(command)[0] == expected, command


@pytest.mark.parametrize("command", DATA_THAT_EXECUTES)
def test_data_text_that_reaches_an_executor_is_still_scanned(command):
    verdict, _reason = decide(command)
    assert verdict in ("SNAPSHOT", "DENY"), (command, verdict)


# ---------------------------------------------------------------------------
# Hook level: the real pretool-bash-safety.sh under /do consent.
# ---------------------------------------------------------------------------

def _run_under_do(command: str, cwd: Path):
    sid = "ob-l30-%s" % uuid.uuid4().hex
    flag = Path(harness_state_dir()) / ("claude-orchestrator-consent-%s.flag" % sid)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("true")
    try:
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_TASK_ID", "CLAUDE_SESSION_ID")}
        proc = subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps({"tool_name": "Bash",
                              "tool_input": {"command": command},
                              "session_id": sid}),
            text=True, capture_output=True, env=env, cwd=str(cwd), timeout=60,
        )
    finally:
        flag.unlink()
    return proc.returncode, proc.stderr


@pytest.fixture
def not_a_repo(tmp_path):
    """A working directory where write_checkpoint cannot snapshot (rc 2)."""
    work = tmp_path / "work"
    work.mkdir()
    return work


@pytest.mark.parametrize("command", MUST_PASS[:4])
def test_hook_under_do_allows_argument_and_heredoc_data(command, not_a_repo):
    rc, err = _run_under_do(command, not_a_repo)
    assert rc == 0, (command, err)
    assert "pre-clean" not in err, (command, err)


@pytest.mark.parametrize("command", [c for c, _v in MUST_REFUSE[:4]])
def test_hook_under_do_still_refuses_when_the_snapshot_fails(command, not_a_repo):
    rc, err = _run_under_do(command, not_a_repo)
    assert rc == 2, (command, err)
    assert "granted 'git clean' denied" in err, (command, err)
