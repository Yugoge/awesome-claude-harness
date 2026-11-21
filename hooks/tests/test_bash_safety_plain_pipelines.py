"""The service, process, disk and workflow rules read a command pipeline by pipeline (lib/bash_safety_rules.py).

Until 2026-11-20 one pipeline that was not a plain shape (any `if` or `for`, a variable argument, a pipe into sort,
a `cd`, a `date`) put the whole command under the older raw-text readings, so a word that was only data was read as
an action: a search for a word piped into sort, a listing next to a status command, a liveness probe of the shell
itself. Now those readings run over what is not a plain pipeline: a plain pipeline that writes no file other than
the null device is read at command position alone, inside compound bodies too; sort, uniq and cut are later filter
stages; a reader that can run nothing takes expanding arguments; the probe takes `$$` and `$!`; the workflow
rule's `rm`/`mv` is a word of its own.

The first list is the seven commands refused live that day (paths made neutral). The refusals the rules exist for
stay: at command position, behind a launcher the parser does not know, in a shell payload, and for text a command
writes to a file and runs. Every case goes through the real hook entry; no command is ever executed.

The removal rule's owner test also takes the session's scratch directory, for every caller of the session (the
last section).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
sys.path.insert(0, str(HOOKS))
from lib.runtime_guard.config import REQUIRED_KEYS  # noqa: E402

SID = "7a6b5c4d-3e2f-4a1b-8c9d-0e1f2a3b4c5d"
OTHER_SID = "0f0e0d0c-0b0a-4908-8706-050403020100"
AGENT = "a1b2c3d4e5f60718"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("bash-safety-plain-pipelines")
    home, state, repo, tmp = base / "home", base / "state", base / "repo", base / "tmp"
    for d in (home / ".claude", state, repo / "src", tmp / "not-a-session"):
        d.mkdir(parents=True)
    for sid in (SID, OTHER_SID):  # each session's scratch directory, with the record session-scratch-init.sh writes
        (tmp / sid / "sub").mkdir(parents=True)
        (tmp / sid / ".owner").write_text(json.dumps({"sid": sid}))
    (base / "gitconfig").write_text("")
    runtime = base / "protected-runtime.json"
    runtime.write_text(json.dumps({"schema_version": 1, **{k: [] for k in REQUIRED_KEYS}}))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
           "CLAUDE_STATE_DIR": str(state), "GIT_CONFIG_GLOBAL": str(base / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
           "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8", "CLAUDE_PROJECT_DIR": str(repo),
           "CLAUDE_PYTHON_BIN": sys.executable, "CLAUDE_HOOK_BOUNDARY_TIMEOUT": "120s",
           "CLAUDE_PROTECTED_RUNTIME_FILE": str(runtime)}
    return {"env": env, "repo": str(repo), "session": str(tmp / SID), "other": str(tmp / OTHER_SID),
            "tmp": str(tmp), "own": str(repo / ".claude" / "scratch" / SID / "dev" / AGENT)}


def run(sandbox, command, caller=None, session_id="bash-safety-plain-pipelines"):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": session_id,
               "cwd": sandbox["repo"], "hook_event_name": "PreToolUse"}
    if caller:
        payload.update(agent_id=caller[0], agent_type=caller[1], subagent_type=caller[1])
    return subprocess.run(["bash", str(HOOKS / "pretool-bash-safety.sh")], input=json.dumps(payload),
                          capture_output=True, text=True, env=sandbox["env"], cwd=sandbox["repo"], timeout=180)


# The seven harmless commands refused on 2026-11-20 (the project's path replaced by /srv/work/dot-claude: the family
# word of the process-family rule stays in the path, as it did live).
ROOT = "/srv/work/dot-claude"
REFUSED_LIVE = [
    'if kill -0 $$ 2>/dev/null; then echo "shell alive"; fi',
    f"grep -rln pkill {ROOT}/hooks/lib | sort | head -5",
    f"grep -rn kill --include='*.py' {ROOT}/hooks/lib | sort | head -3",
    f"cd {ROOT}/hooks && grep -rn kill --include='*.py' lib | wc -l",
    f'grep -rn "docker compose down" {ROOT}/docs | sort | head -3',
    f"ls {ROOT}/.claude/todos/ 2>&1 | head -3; uname -srm && date -u +%H:%MZ",
    f"git -C {ROOT} status --short | grep -v '^??' | head -3; git -C {ROOT} log --oneline -2; "
    f"git -C {ROOT} diff --text --stat HEAD~1 | tail -1; ls {ROOT}/docs | head -3; date -u +%H:%M:%SZ; "
    'echo "TMPDIR=$TMPDIR"; echo "the words rm -rf /x, kill -9 1 and git push --force are only text here"; '
    f'grep -c "rm -rf" {ROOT}/hooks/lib/bash_safety_rules.py; if kill -0 $$ 2>/dev/null; then echo "shell alive"; fi; '
    "ls /nonexistent-dir 2>/dev/null; echo done > /dev/null",
]


@pytest.mark.parametrize("command", REFUSED_LIVE)
def test_a_harmless_command_refused_live_passes(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


# The same cause in other spellings: a word that is only data beside, or inside, a pipeline that is not plain.
MUST_PASS = [
    # the liveness probe of the shell itself and of the last background job
    "kill -0 $$",
    'kill -0 "$$"',
    "kill -0 $$ && echo alive",
    'kill -0 "$!" 2>/dev/null && echo running',
    "sleep 1 & while kill -0 $! 2>/dev/null; do echo waiting; done",
    # a plain pipeline beside one that is not: only the latter keeps the older reading
    "date; kill -l",
    "cd hooks && git log --grep kill -5",
    'date -u; echo "docker system prune -a is the operator\'s call"',
    "fdisk -l; lsblk",
    "for d in a b; do grep -rn kill -i src; done",
    "while read f; do grep -c pkill docs/claude.md; done < list.txt",
    # sort, uniq and cut as later stages
    "grep -rn kill -i src | cut -d: -f1 | sort | uniq -c | sort -rn | head",
    # a reader that runs nothing: an expanding argument is data
    'grep -rn kill -i "$DIR" | head -3',
    'echo "TMPDIR=$TMPDIR"; date',
    'cat "${F:-notes.md}" | wc -l; date',
    # rm and mv as the end of another word
    "terraform plan; ls .claude/todos/",
    "uname -srm; cat .claude/workflow-abc.json",
]


@pytest.mark.parametrize("command", MUST_PASS)
def test_a_word_that_is_only_data_passes(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


KILL_SIG = "kill with signals is refused"
KILL_PID = "kill with PIDs is refused"
KILLALL = "Killing processes by name or pattern"
COMPOSE = "docker-compose down/stop/restart"
WORKFLOW = "workflow state files"
MUST_REFUSE = [
    # a signal at command position, inside a compound and inside a pipeline with a program that is no reader
    ("if kill -9 4242; then echo done; fi", KILL_SIG),
    ("for p in 1 2; do kill -TERM $p; done", KILL_SIG),
    ("date | kill -9 4242", KILL_SIG),
    ("ps aux | awk '{print $2}' | xargs kill -9", KILLALL),
    ("grep -rn x src | sort; if true; then kill -KILL 4242; fi", KILL_SIG),
    # behind a launcher the parser does not know, beside plain pipelines
    ("uv run kill -9 4242", KILL_SIG),
    ("grep -rn x src | sort | head; uv run kill -9 4242", KILL_SIG),
    ("for d in a b; do ls $d | sort; uv run kill -9 4242; done", KILL_SIG),
    # in a shell payload
    ('bash -c "kill -9 4242"', KILL_SIG),
    ("ls | sort; bash -c 'kill -9 4242'", KILL_SIG),
    # text written unquoted to a file and run in the same command, by each way its output reaches the file or a shell
    ("echo kill -9 1234 > k.sh; bash k.sh", KILL_SIG),
    ("echo kill -9 1234 > k.sh && bash k.sh", KILL_SIG),
    ("{ echo kill -9 1234; } > k.sh; bash k.sh", KILL_SIG),
    ("exec > k.sh; echo kill -9 1234; bash k.sh", KILL_SIG),
    ("if true; then echo kill -9 1234; fi | bash", KILL_SIG),
    ("for i in 1; do echo kill -9 1234; done | cat > k.sh; bash k.sh", KILL_SIG),
    ("f() { echo kill -9 1234; }; f > k.sh; bash k.sh", KILL_SIG),
    # sort or uniq writing a file or running a program is no filter
    ("grep -rn kill --include='*.py' lib | sort -o out.txt", KILL_SIG),
    ("grep -rn kill --include='*.py' lib | sort --output=out.txt", KILL_SIG),
    ("grep -rn kill --include='*.py' lib | sort --compress-program=./x", KILL_SIG),
    ("grep -rn kill --include='*.py' lib | uniq - out.txt", KILL_SIG),
    # the probe with any other word, and any other option with the shell's pid
    ("kill -0 $PID", KILL_SIG),
    ("kill -0 $$ $X", KILL_SIG),
    ("kill -9 $$", KILL_SIG),
    ("kill -s KILL $!", KILL_SIG),
    # a reader's argument that holds a substitution
    ("grep -rn kill -i $(cat list.txt) | head -3", KILL_SIG),
    # a numbered process
    ("if true; then kill 4242; fi", KILL_PID),
    ("ls | sort; kill 4242", KILL_PID),
    # the protected process family
    ("pkill -f claude", KILLALL),
    ("if true; then pkill -f claude; fi", KILLALL),
    ("ls | sort; pkill -f claude", KILLALL),
    ("ls | sort; uv run pkill -f claude", KILLALL),
    # a compose stack
    ("docker compose down", COMPOSE),
    ("if true; then docker compose down; fi", COMPOSE),
    ("ls | sort && docker compose down", COMPOSE),
    ("grep -c x f | sort; uv run docker compose down", COMPOSE),
    # workflow state files
    ("mv .claude/workflow-abc.json /tmp/", WORKFLOW),
    ("rm -rf .claude/todos/", WORKFLOW),
    ("if true; then rm .claude/workflow-abc.json; fi", WORKFLOW),
    ("ls | sort; mv .claude/workflow-abc.json /tmp/", WORKFLOW),
    ("uv run rm .claude/workflow-a.json", WORKFLOW),
    ("ls | sort; uv run /bin/rm .claude/workflow-a.json", WORKFLOW),
    ("ls | sort; uv run \\rm .claude/workflow-a.json", WORKFLOW),
]


@pytest.mark.parametrize("command,label", MUST_REFUSE)
def test_a_command_the_rule_protects_against_is_still_refused(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


# ── The session's scratch directory, for every caller of the session ─────────

REMOVAL = "BLOCKED: removal-policy"
CALLERS = [None, (AGENT, "dev"), (AGENT, "qa"), ("a9999999999999999", "dev")]


@pytest.mark.parametrize("caller", CALLERS, ids=lambda c: "main" if c is None else c[1] + "-" + c[0][:5])
def test_every_caller_of_a_session_removes_a_named_file_in_its_session_scratch(sandbox, caller):
    """$TMPDIR is the session's scratch directory, so the programs a subagent runs (pytest, mktemp) leave their
    files there: a file named there may be removed by any actor of that session."""
    for command in ("rm -f {s}/a.txt", "rm -rf {s}/sub", "rm -rf {s}/pytest-of-root/pytest-0",
                    "S={s}; rm -f $S/a.txt $S/sub/b"):
        r = run(sandbox, command.format(s=sandbox["session"]), caller, SID)
        assert r.returncode == 0 and "removal-policy" not in r.stderr, (caller, command, r.stderr)


@pytest.mark.parametrize("caller", CALLERS, ids=lambda c: "main" if c is None else c[1] + "-" + c[0][:5])
def test_the_directory_itself_a_pattern_and_another_sessions_stay_refused(sandbox, caller):
    for command in ("rm -rf {s}", "rm -rf {s}/", "rm -rf {s}/*", "rm -rf $TMPDIR/x", "rm -f {o}/a.txt",
                    "rm -rf {t}/not-a-session/x", "rm -f {s}/a.txt {o}/a.txt", "rm -f {s}/../{osid}/a.txt",
                    "rm {r}/src/main.py"):
        r = run(sandbox, command.format(s=sandbox["session"], o=sandbox["other"], t=sandbox["tmp"],
                                        osid=OTHER_SID, r=sandbox["repo"]), caller, SID)
        assert r.returncode == 2 and REMOVAL in r.stderr, (caller, command, r.stderr)


def test_a_session_whose_scratch_has_no_owner_record_owns_none(sandbox):
    """The directory counts only once its owner record names the session (lib/scratch_owner)."""
    for caller in CALLERS:
        r = run(sandbox, "rm -f " + sandbox["tmp"] + "/not-a-session/a.txt", caller, "not-a-session")
        assert r.returncode == 2 and REMOVAL in r.stderr, (caller, r.stderr)
        assert "session's scratch directory" not in r.stderr, r.stderr


def test_the_refusal_names_every_directory_a_removal_runs_in(sandbox):
    """A subagent's refusal names its own directory and the session's; the main agent's own directory is the
    session's, named once."""
    r = run(sandbox, "rm /tmp/x.py", (AGENT, "dev"), SID)
    assert r.returncode == 2 and REMOVAL in r.stderr, r.stderr
    assert f"your own scratch directory is {sandbox['own']}/ " in r.stderr, r.stderr
    assert f"this session's scratch directory is {sandbox['session']}/ " in r.stderr, r.stderr
    assert "and lies inside one of those directories." in r.stderr, r.stderr
    r = run(sandbox, "rm /tmp/x.py", None, SID)
    assert r.returncode == 2 and REMOVAL in r.stderr, r.stderr
    assert f"your own scratch directory is {sandbox['session']}/ " in r.stderr, r.stderr
    assert "this session's scratch directory" not in r.stderr and "lies inside that directory." in r.stderr, r.stderr
