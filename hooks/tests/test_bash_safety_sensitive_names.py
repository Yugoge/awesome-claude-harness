"""OB-L14: bash-safety's sensitive-file rule (BS-10, BS-11) matches an exact list of secret file names
(hooks/lib/sensitive_names.py) against the parsed write targets and command words, not a substring of the text.

Every hook call runs pretool-bash-safety.sh with a scratch HOME, state dir and git config, an empty
protected-runtime file, and a throwaway repository as its working directory. No command is ever executed.
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

WRITE = "Attempting to write to sensitive file via Bash"
READ = "Attempting to redirect from/to sensitive file via Bash"


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("bash-safety-sensitive")
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


def run(sandbox, command):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "bash-safety-sensitive",
               "cwd": sandbox["repo"], "hook_event_name": "PreToolUse"}
    return subprocess.run(["bash", str(HOOKS / "pretool-bash-safety.sh")], input=json.dumps(payload),
                          capture_output=True, text=True, env=sandbox["env"], cwd=sandbox["repo"], timeout=120)


# The lane's must-pass commands: a name that merely contains a secret word is no secret file.
MUST_PASS = [
    "cat > tests/test_password_reset.py <<'EOF'\ndef test_reset():\n    assert reset_password('x')\nEOF",
    "ls -la src/ > /tmp/secret-scan-report.txt",
    "python3 -m pytest tests/test_auth_password.py > /tmp/pytest.log 2>&1",
    "curl -s https://example.com/docs/password-policy > /tmp/policy.html",
    "cat > src/config.ts <<'EOF'\nexport const port = () => process.env.PORT;\nEOF",
]


@pytest.mark.parametrize("command", MUST_PASS)
def test_a_name_that_only_contains_a_secret_word_passes(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


# The lane's must-still-refuse commands, each with the refusal it gets.
MUST_REFUSE = [
    ("cat > .env <<'EOF'\nA=1\nEOF", WRITE),
    ("echo x > .env.local", WRITE),
    ("cat .env > x", READ),
    ("cat ~/.aws/credentials > x", READ),
    ("> .git-credentials", WRITE),
    ("> secrets.yaml", WRITE),
    ("> id_rsa", WRITE),
    ("> db_password", WRITE),
    ("> passwords.csv", WRITE),
]


@pytest.mark.parametrize("command,label", MUST_REFUSE)
def test_a_listed_secret_file_is_still_refused(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


@pytest.mark.parametrize("command", [
    "cat > .env <<'EOF'\nA=1",                       # unterminated: the parser cannot read it
    "cat > id_rsa <<'EOF'\n-----BEGIN KEY-----",
    "cat > tests/test_password_reset.py <<'EOF'\nx",  # unreadable, so judged by substring: refused more, never less
])
def test_a_heredoc_the_parser_cannot_read_falls_back_to_refusal(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 2 and WRITE in r.stderr, (command, r.stderr)


# P14-5 (search-09) already reads quoted data and heredoc bodies as data; pinned here.
@pytest.mark.parametrize("command", [
    'echo "see secret > file"',
    "echo 'cat .env > x'",
    "cat > notes.md <<'EOF'\nnever run: echo KEY=1 > .env\nEOF",
    "cat > docs/auth.md <<'EOF'\nlogin form -> password check > db_password\nEOF",
])
def test_a_secret_name_inside_quoted_data_or_a_heredoc_body_passes(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


# The write targets come from the parser, payloads and wrappers included.
@pytest.mark.parametrize("command,label", [
    ("bash -c 'echo x > .env'", WRITE),
    ('eval "echo x > ~/.ssh/id_ed25519"', WRITE),
    ("echo k | tee .env", WRITE),
    ("echo k | sudo tee -a .env.production", WRITE),
    ("cp .env.example .env", WRITE),
    ("echo x > ~/.claude/.credentials.json", WRITE),
    ('echo x > "$HOME/.env"', WRITE),
    ("echo x > .ENV", WRITE),
    ("sudo cat .env > out.txt", READ),
    ("cp .env /tmp/leak.txt", READ),
    ("sort < secrets.yaml > /tmp/sorted.txt", READ),
])
def test_a_parsed_write_or_read_of_a_secret_file_is_refused(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


def test_the_list_is_one_reusable_definition():
    from lib.sensitive_names import is_sensitive_name
    listed = [".env", ".env.local", ".env.example", "config/prod.env", ".envrc", "credentials", "/home/u/.aws/credentials",
              ".git-credentials", ".credentials.json", "client_secret.json", "secrets.yaml", "secret.txt",
              "secrets.enc.yaml", "id_rsa", "id_ed25519", "~/.ssh/id_ecdsa", "db_password", "passwords.csv",
              "PASSWORD.TXT", '"$HOME/.env"']
    unlisted = ["test_password_reset.py", "test_auth_password.py", "secret-scan-report.txt", "password-policy",
                "config.ts", "pytest.log", "policy.html", "id_rsa.pub", "secrets.py", "environment.ts", "venv",
                "password_reset.md", ""]
    assert [n for n in listed if not is_sensitive_name(n)] == []
    assert [n for n in unlisted if is_sensitive_name(n)] == []
