"""OB-L11: bash-safety's service, process, disk, docker and workflow rules read the command word and that simple
command's own arguments (lib/shell_parse.py), not raw-text co-occurrence.

A search for the words, a read of the file and the exact harmless kill and dd forms pass; the commands the rules
protect against are refused at command position behind wrappers (sudo, xargs, timeout, path forms), inside eval
and shell payloads, and inside interpreter code. Every case goes through the real hook entry with a scratch HOME,
state dir and git config. No command is ever executed.
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


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("bash-safety-command-position")
    home, state, repo, tmp = base / "home", base / "state", base / "repo", base / "tmp"
    for d in (home / ".claude", state, repo, tmp):
        d.mkdir(parents=True)
    (base / "gitconfig").write_text("")
    runtime = base / "protected-runtime.json"
    runtime.write_text(json.dumps({"schema_version": 1, **{k: [] for k in REQUIRED_KEYS}}))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
           "CLAUDE_STATE_DIR": str(state), "GIT_CONFIG_GLOBAL": str(base / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
           "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
           "CLAUDE_PROTECTED_RUNTIME_FILE": str(runtime)}
    return {"env": env, "repo": str(repo)}


def run(sandbox, command):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "bash-safety-command-position",
               "cwd": sandbox["repo"], "hook_event_name": "PreToolUse"}
    return subprocess.run(["bash", str(HOOKS / "pretool-bash-safety.sh")], input=json.dumps(payload),
                          capture_output=True, text=True, env=sandbox["env"], cwd=sandbox["repo"], timeout=120)


# The over-blocks fixed: each was refused by raw-text co-occurrence (or by an inexact kill/dd reading).
MUST_PASS = [
    "kill -0 12345 && echo alive",
    "kill -l",
    "grep -rn kill -i src/",
    "fdisk -l",
    "dd if=/dev/zero of=/tmp/blob.bin bs=1k count=4",
    'grep -rn "docker compose down" docs/',
    "sed -n 1,20p /etc/docker/daemon.json",
    "grep tcp /etc/docker/daemon.json",
    'rg -n "systemctl restart nginx" docs',
    "jq .platform .claude/workflow-abc.json",
    "grep -rn killall ~/.claude/hooks/",
    # the exact harmless forms the lane names
    "kill -L",
    'kill -0 "$SERVER_PID" 2>/dev/null && echo running',
    "dd if=/dev/zero of=/dev/null bs=1k count=1",
    "dd if=in.bin of=/dev/stdout",
    "dd if=in.bin of=/dev/fd/3",
    # prose about the commands, in a heredoc written to a file
    "cat <<'EOF' > notes.md\nrun docker compose down, then systemctl restart nginx\nEOF",
]


@pytest.mark.parametrize("command", MUST_PASS)
def test_a_command_that_only_names_the_words_passes(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


# The commands the rules exist for, with the refusal each must give.
KILL_SIG = "kill with signals is refused"
MUST_REFUSE = [
    ("pgrep -f vite | xargs kill -9", KILL_SIG),
    ("sudo kill -9 4242", KILL_SIG),
    ("timeout 5 kill -TERM 4242", KILL_SIG),
    ("kill -09 4242", KILL_SIG),
    ('eval "systemctl restart docker"', "refused for production services"),
    ('eval "docker compose down"', "docker-compose down/stop/restart"),
    ("""python3 -c 'import os; os.system("docker system prune -a -f")'""", "docker system prune -a"),
    ("dd if=/dev/zero of=/dev/sda", "Destructive disk operation"),
    ("dd if=/dev/zero of=$TARGET bs=1M count=1", "Destructive disk operation"),
    ("cp a /etc/docker/daemon.json", "Modifying Docker daemon config"),
    ("sed -i s/a/b/ /etc/docker/daemon.json", "Modifying Docker daemon config"),
    ('T=~/.claude/todos/; rm -rf "$T"', "workflow state files"),
    ("pkill -f claude", "Killing claude/docker processes"),
    # wrappers, path forms and payloads
    ("/bin/kill -9 4242", KILL_SIG),
    ("env X=1 nohup kill -KILL 4242", KILL_SIG),
    ('bash -c "kill -9 4242"', KILL_SIG),
    ("find /proc -maxdepth 1 -name 4242 -exec kill -9 {} \\;", KILL_SIG),
    ("kill -s KILL 4242", KILL_SIG),
    ("sudo kill 4242", "kill with PIDs is refused"),
    ("sudo killall -9 docker", "Killing claude/docker processes"),
    ("docker compose -f compose.yml down", "docker-compose down/stop/restart"),
    ("sudo docker-compose stop", "docker-compose down/stop/restart"),
    ("docker system prune --all", "docker system prune -a"),
    ("""node -e 'require("child_process").execSync("docker compose down")'""", "docker-compose down/stop/restart"),
    ("""python3 -c 'import os; os.system("systemctl restart nginx")'""", "refused for production services"),
    ("python3 - <<'EOF'\nimport os\nos.system(\"docker compose down\")\nEOF", "docker-compose down/stop/restart"),
    ('CMD="docker compose down"; eval "$CMD"', "docker-compose down/stop/restart"),
    ('watch "docker compose down"', "docker-compose down/stop/restart"),
    ("sudo systemctl restart nginx", "refused for production services"),
    ("systemctl restart $UNIT", "refused for production services"),
    ("sudo dd if=disk.iso of=/dev/sdb", "Destructive disk operation"),
    ("dd if=/dev/zero bs=1 count=1 > /dev/sda", "Destructive disk operation"),
    ("cd /dev && dd if=/dev/zero of=sda", "Destructive disk operation"),
    ("dd if=/dev/zero of=/dev/tty", "Destructive disk operation"),
    ("mkfs.ext4 /dev/sdb1", "Destructive disk operation"),
    ("sudo fdisk /dev/sda", "Destructive disk operation"),
    ("shred -u secret.bin", "Destructive disk operation"),
    ("echo '{}' > /etc/docker/daemon.json", "Modifying Docker daemon config"),
    ("cat cfg.json | sudo tee /etc/docker/daemon.json", "Modifying Docker daemon config"),
    ("mv .claude/workflow-abc.json /tmp/", "workflow state files"),
    ("git rm .claude/workflow-abc.json", "workflow state files"),
    ("ls .claude/todos/ | xargs rm", "workflow state files"),
]


@pytest.mark.parametrize("command,label", MUST_REFUSE)
def test_a_command_the_rule_protects_against_is_refused(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


# Verifier round 2. git reads its subcommand past global options and their values; dd writes every descriptor its
# command opens for writing (of=/dev/fd/N and friends name those); dd's of= writes daemon.json.
WORKFLOW = "workflow state files"
DISK = "Destructive disk operation"
MUST_REFUSE_ROUND2 = [
    ("git -C . rm .claude/workflow-abc.json", WORKFLOW),
    ("git -C . rm -r .claude/todos/", WORKFLOW),
    ("git -C . mv .claude/workflow-abc.json /tmp/x", WORKFLOW),
    ("git --work-tree . mv .claude/workflow-abc.json x", WORKFLOW),
    ("git -c core.x=y --git-dir=.git rm .claude/workflow-abc.json", WORKFLOW),
    ("dd if=/dev/zero of=/dev/fd/3 3>/dev/sda", DISK),
    ("dd if=/dev/zero of=/dev/fd/3 3<>/dev/sda", DISK),
    ("dd if=/dev/zero of=/proc/self/fd/3 3>/dev/sda", DISK),
    ("dd if=/dev/zero of=/dev/stderr 2>/dev/sda", DISK),
    ("dd if=/dev/zero >&3 3>/dev/sda", DISK),
    ("dd if=x of=/etc/docker/daemon.json", "Modifying Docker daemon config"),
    ("dd if=x of=/etc/docker/daemon.json conv=notrunc", "Modifying Docker daemon config"),
    ("dd if=/dev/zero of=/etc/docker/daemon.json count=0", "Modifying Docker daemon config"),
    ("cat x | sudo dd of=/etc/docker/daemon.json", "Modifying Docker daemon config"),
    ("docker compose --profile x down", "docker-compose down/stop/restart"),
    ("docker compose -p proj down -v", "docker-compose down/stop/restart"),
    ("docker compose --file=x.yml stop web", "docker-compose down/stop/restart"),
    ("docker --log-level info system prune -a", "docker system prune -a"),
    ("docker system prune -fa", "docker system prune -a"),
]


@pytest.mark.parametrize("command,label", MUST_REFUSE_ROUND2)
def test_round2_a_command_the_rule_protects_against_is_refused(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


# A down/restart/stop word that is not the compose verb (a command `exec` or `run` runs, a service name) and a
# prune flag outside `system prune` are data.
MUST_PASS_ROUND2 = [
    "docker compose exec db pg_ctl stop",
    "docker compose exec app supervisorctl restart worker",
    "docker compose run --rm app ./manage.py down",
    "docker compose logs -f stop",
    "docker system --help prune -a",
    "dd if=in.bin of=/dev/stdout 2>/dev/null",
    "dd if=in.bin of=out.img 2>dd.log",
    "git -C . mv notes.md docs/notes.md",
]


@pytest.mark.parametrize("command", MUST_PASS_ROUND2)
def test_round2_a_word_outside_the_verb_position_passes(sandbox, command):
    r = run(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


# Verifier round 3. D1: Linux reopens the file behind an of= descriptor for writing, so a file opened on it for
# reading is a target, and another process's descriptor cannot be read. D2: a command that is not a plain shape
# (readers, kill -0/-l/-L, an fdisk listing, plain dd, git reads) also keeps the whole-command readings the rules had
# before command position, so a launcher or git/pager form the parser does not classify loses no refusal.
COMPOSE = "docker-compose down/stop/restart"
UNIT = "refused for production services"
KILLALL = "Killing claude/docker processes"
PRUNE = "docker system prune -a"
MUST_REFUSE_ROUND3 = [
    ("dd if=/dev/zero of=/dev/fd/3 3</dev/sda", DISK),
    ("dd if=/dev/zero of=/proc/self/fd/3 3</dev/sda", DISK),
    ("dd if=/dev/zero of=/proc/thread-self/fd/3 3</dev/sda", DISK),
    ("dd if=/dev/zero of=/dev/stdin </dev/sda", DISK),
    ("dd if=/dev/zero of=/dev/fd/0 0</dev/sda", DISK),
    ("dd if=/dev/zero of=/dev/fd/3 3<&4 4</dev/sda", DISK),
    ("dd if=/dev/zero of=/proc/1/fd/3", DISK),
    ("dd if=/dev/zero of=/proc/4242/fd/1", DISK),
    ("exec 3>/dev/sda; dd if=/dev/zero of=/dev/fd/3", DISK),
    ("dd if=/dev/zero of=~/../../../../../../dev/sda", DISK),
    ("uv run docker compose down", COMPOSE),
    ("uv run kill -9 4242", KILL_SIG),
    ("poetry run kill -9 4242", KILL_SIG),
    ("pipenv run systemctl restart nginx", UNIT),
    ("pdm run pkill -f claude", KILLALL),
    ("hatch run docker system prune -a", PRUNE),
    ("conda run -n x docker compose down", COMPOSE),
    ("npm exec -- pkill -f claude", KILLALL),
    ("pnpm exec docker compose down", COMPOSE),
    ("pnpm dlx kill -9 4242", KILL_SIG),
    ("yarn exec systemctl restart nginx", UNIT),
    ("bunx docker compose down", COMPOSE),
    ("npx kill -9 4242", KILL_SIG),
    ("bundle exec docker system prune -a", PRUNE),
    ("direnv exec . docker compose down", COMPOSE),
    ("nix develop -c docker compose down", COMPOSE),
    ("nix-shell --run 'docker compose down'", COMPOSE),
    ("mise exec -- kill -9 4242", KILL_SIG),
    ("op run -- systemctl restart nginx", UNIT),
    ("doppler run -- docker compose down", COMPOSE),
    ("aws-vault exec p -- kill -9 4242", KILL_SIG),
    ("dotenv -- pkill -f claude", KILLALL),
    ("caffeinate docker compose down", COMPOSE),
    ("cgexec -g cpu:x kill -9 4242", KILL_SIG),
    ("proxychains docker compose down", COMPOSE),
    ("torsocks systemctl restart nginx", UNIT),
    ("tsp docker compose down", COMPOSE),
    ("faketime '2020-01-01' kill -9 4242", KILL_SIG),
    ("lldb -- kill -9 4242", KILL_SIG),
    ("nsenter -t 1 -m systemctl restart nginx", UNIT),
    ("uv run rm .claude/workflow-a.json", WORKFLOW),
    ("git -c alias.x='!systemctl restart nginx' x", UNIT),
    ("git rebase --exec 'docker compose down' HEAD~1", COMPOSE),
    ("git bisect run docker compose down", COMPOSE),
    ("git submodule foreach 'docker compose down'", COMPOSE),
    ("git -c core.sshCommand='docker compose down' fetch", COMPOSE),
    ("GIT_PAGER='docker compose down' git log", COMPOSE),
    ("PAGER='docker compose down' man ls", COMPOSE),
    ("bash -c 'uv run docker compose down'", COMPOSE),
    ("rg --pre ./x 'docker compose down'", COMPOSE),
    ("git grep -O'docker compose down' x", COMPOSE),
    ("sed -n 'w /etc/docker/daemon.json' x", "Modifying Docker daemon config"),
]


@pytest.mark.parametrize("command,label", MUST_REFUSE_ROUND3)
def test_round3_a_launcher_or_descriptor_form_is_refused(sandbox, command, label):
    r = run(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)
