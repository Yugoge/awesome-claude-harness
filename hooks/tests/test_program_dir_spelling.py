"""A program's directory is read from what it is, not from how it is spelled (location rule: a plain program directory).

The session-dirs rule and the bulk-commit-sentinel rule read a command word in a plain program directory
(lib/locations.BIN_DIRS) as the bare program. `/usr//bin/grep` and `/usr/bin/../bin/grep` name the same file as
`/usr/bin/grep`, so each pair gets one verdict from the real hook entry, pretool-bash-safety.sh. A command that runs
or writes the protected name stays refused in every spelling.
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

SD = "session_" + "dirs.txt"  # spelled in two parts so this file's own text does not carry the protected name
BULK = "write-bulk-commit-" + "sentinel.py"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("program-dir-spelling")
    home, state, repo, tmp = base / "home", base / "state", base / "repo", base / "tmp"
    for d in (home / ".claude", state, repo, tmp):
        d.mkdir(parents=True)
    (base / "gitconfig").write_text("[user]\n\tname = sandbox\n\temail = sandbox@example.invalid\n")
    runtime = base / "protected-runtime.json"
    runtime.write_text(json.dumps({"schema_version": 1, **{k: [] for k in REQUIRED_KEYS}}))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
           "CLAUDE_STATE_DIR": str(state), "GIT_CONFIG_GLOBAL": str(base / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
           "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
           "CLAUDE_PROTECTED_RUNTIME_FILE": str(runtime)}
    (repo / "README.md").write_text("toy\n")
    for step in (["init", "-q", "-b", "master"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *step], cwd=repo, env=env, check=True, capture_output=True)
    return {"env": env, "repo": str(repo)}


def rc(sandbox, command):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "program-dir-spelling",
               "cwd": sandbox["repo"], "hook_event_name": "PreToolUse"}
    return subprocess.run(["bash", str(HOOKS / "pretool-bash-safety.sh")], input=json.dumps(payload),
                          capture_output=True, text=True, env=sandbox["env"], cwd=sandbox["repo"], timeout=120).returncode


SPELLINGS = ("/usr/bin/{p}", "/usr//bin/{p}", "/usr/bin/../bin/{p}", "//usr/bin/{p}")
TEMPLATES = [
    "{grep} -rn SD docs/",
    "{grep} -rn SD docs/ | {head} -5",
    "{grep} -rn SD docs/ && {echo} done",
    "{git} commit -m 'docs: explain SD'",
]


def spelled(template, form):
    text = template.replace("SD", SD).replace("BULK", BULK)
    return text.format(**{p: form.format(p=p) for p in ("grep", "head", "echo", "git")})


@pytest.mark.parametrize("template", TEMPLATES)
def test_the_same_program_in_its_directory_gets_one_verdict_however_the_directory_is_spelled(sandbox, template):
    plain = rc(sandbox, spelled(template, SPELLINGS[0]))
    assert plain == 0, "the plain spelling is the ordinary case and passes"
    for form in SPELLINGS[1:]:
        assert rc(sandbox, spelled(template, form)) == plain, form


@pytest.mark.parametrize("form", SPELLINGS)
def test_running_the_protected_name_stays_refused_in_every_spelling(sandbox, form):
    assert rc(sandbox, "%s %s" % (form.format(p="cat"), SD)) != 0
    assert rc(sandbox, "%s %s" % (form.format(p="python3"), BULK)) != 0
