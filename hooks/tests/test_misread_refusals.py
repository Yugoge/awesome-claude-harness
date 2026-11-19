"""Misread refusals: a rule judges what the command does at the place where a program runs.

Each group holds the shapes of refusals recorded in three days of sessions (paths, names and PIDs made
generic), which must pass, and beside them what the rule exists to stop, in the same command positions, which
must still be refused. Every case goes through the real hook entry with a scratch HOME, state directory, temp
directory and git config. No command is ever executed and no signal is sent: the hooks read text.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
RUNTIME = {"schema_version": 1, "protected_cmds": ["svc", "svc-dev"], "protected_launch_paths": ["/usr/bin/svc"],
           "protected_services": ["svc-daemon"], "protected_hotfiles": [], "protected_statefiles": [],
           "protected_endpoint_paths": ["/stop"], "protected_proc_idents": ["svc-daemon"],
           "protected_global_bins": ["/usr/bin/svc*"], "protected_build_workspaces": ["svc"],
           "protected_build_paths": ["**/packages/svc-cli"]}


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("misread-refusals")
    home, state, repo, tmp = base / "home", base / "state", base / "repo", base / "tmp"
    for d in (home / ".claude", state, repo, tmp):
        d.mkdir(parents=True)
    (base / "gitconfig").write_text("")
    mono = base / "mono"
    (mono / "packages" / "svc-cli").mkdir(parents=True)
    (mono / "package.json").write_text('{"name": "mono", "scripts": {"build": "x"}}')
    (mono / "packages" / "svc-cli" / "package.json").write_text('{"name": "svc", "scripts": {"build": "x"}}')
    (base / "protected-runtime.json").write_text(json.dumps(dict(
        RUNTIME, script_run_policy="default_deny", protected_script_workspaces=["svc"],
        protected_script_paths=["**/packages/svc-cli"], protected_root_manifest_paths=[str(mono)])))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
           "CLAUDE_STATE_DIR": str(state), "GIT_CONFIG_GLOBAL": str(base / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
           "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
           "CLAUDE_PROTECTED_RUNTIME_FILE": str(base / "protected-runtime.json"),
           "CLAUDE_PROTECTED_PROCESS_FAMILY": "svc", "CLAUDE_HARD_BANNED_SCRIPTS": "svc-session-recovery|svc-restart"}
    return {"env": env, "repo": str(repo), "state": str(state), "mono": str(mono)}


def bash_safety(sandbox, command, description=None):
    """hooks/pretool-bash-safety.sh on a Bash call. A Monitor's command reaches this hook as the same call
    ({command, description}): the CLI hands it to the registrations that match Bash."""
    tool_input = {"command": command} if description is None else {"command": command, "description": description}
    payload = {"tool_name": "Bash", "tool_input": tool_input, "session_id": "misread-refusals",
               "cwd": sandbox["repo"], "hook_event_name": "PreToolUse"}
    return subprocess.run(["bash", str(HOOKS / "pretool-bash-safety.sh")], input=json.dumps(payload),
                          capture_output=True, text=True, env=sandbox["env"], cwd=sandbox["repo"], timeout=120)


# ── The liveness probe: `kill -0 PID` sends no signal ────────────────────────
# 66 recorded refusals: the probe as the condition of if, while and until, inside a for loop, behind `!`, in an
# && / || list, after a heredoc fed to an interpreter, and with the PID in a variable the command sets itself.
OUT = "/srv/work/docs/codex/run-01/out.txt"
PROBES = [
    f'f={OUT}; if kill -0 4242 2>/dev/null; then echo "STATUS=running"; else echo "STATUS=exited"; fi; wc -lc "$f"',
    f"for i in $(seq 1 55); do if ! kill -0 4242 2>/dev/null; then echo exited; break; fi; sleep 10; done; wc -c {OUT}",
    f'until ! kill -0 4242 2>/dev/null; do sleep 10; done; echo "process exited"; tail -c 400 {OUT}',
    f"until ! kill -0 4242; do sleep 5; done; tail -c 300 {OUT}",
    f'until ! kill -0 4242 2>/dev/null || grep -q "FEEDBACK" {OUT} 2>/dev/null; do sleep 5; done; '
    f'if kill -0 4242 2>/dev/null; then echo "still alive"; else echo "exited"; fi; wc -c {OUT}',
    f'until grep -q "FEEDBACK" {OUT} || ! kill -0 4242 2>/dev/null; do sleep 5; done; tail -c 300 {OUT} | head -5',
    f"while kill -0 4242 2>/dev/null; do sleep 20; done; echo finished; tail -c 300 {OUT}",
    f"for i in $(seq 1 55); do kill -0 4242 2>/dev/null || break; sleep 10; done; "
    f"kill -0 4242 2>/dev/null && echo running || echo done; wc -c {OUT}",
    f'timeout 570 tail --pid=4242 -f /dev/null; echo "wait_exit=$?"; if kill -0 4242 2>/dev/null; then echo running; '
    f"else echo exited; fi; ls -la {OUT}",
    f'f={OUT}; for i in $(seq 1 19); do if grep -q "FEEDBACK" <(tail -n +60 $f | grep -v "^Reply with") && '
    f"! kill -0 4242 2>/dev/null; then break; fi; if ! kill -0 4242 2>/dev/null; then break; fi; sleep 28; done; "
    f"kill -0 4242 2>/dev/null && echo running || echo done; wc -c $f; tail -c 600 $f",
    "cd /srv/work && python3 - <<'E'\nimport json\njson.dump({'summary': 'the watcher must not kill -9 the worker'},"
    " open('ctx.json', 'w'))\nprint('ok')\nE\nsleep 120; tail -c 600 " + OUT + "; kill -0 4242 && echo alive",
    # the PID in a variable the command sets once, to digits
    f"pid=4242; while kill -0 $pid 2>/dev/null; do sleep 20; done; echo done; tail -c 600 {OUT}",
    f'pid=4242; out={OUT}; until ! kill -0 $pid 2>/dev/null; do sleep 15; done; echo "exited"; tail -c 300 $out',
    'pid=4242; for i in $(seq 1 55); do if ! kill -0 $pid 2>/dev/null; then echo "finished"; exit 0; fi; sleep 10; '
    'done; echo "still running"',
]


@pytest.mark.parametrize("command", PROBES)
def test_a_liveness_probe_passes_in_every_position_it_was_written_in(sandbox, command):
    r = bash_safety(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


def test_a_monitors_probe_loop_passes(sandbox):
    """24 of the refusals were a Monitor (the watcher tool) whose command is the until loop."""
    r = bash_safety(sandbox, f"until ! kill -0 4242 2>/dev/null; do sleep 5; done; echo exited; wc -c {OUT}",
                    description="wait for the review to exit")
    assert r.returncode == 0, r.stderr


# What the rules exist to stop: a signal sent to a process, by number or by pattern, in each of those positions.
KILL_SIG = "kill with signals is refused"
KILL_PID = "kill with PIDs is refused"
KILL_FAMILY = "claude/docker processes is refused"
RUNTIME_GUARD = "[protected-runtime-guard] BLOCK"
SIGNALS = [
    ("if kill -9 4242 2>/dev/null; then echo killed; fi", KILL_SIG),
    ("for i in $(seq 1 5); do if ! kill -TERM 4242 2>/dev/null; then break; fi; sleep 1; done", KILL_SIG),
    ("until ! kill -9 4242 2>/dev/null; do sleep 1; done; echo gone", KILL_SIG),
    ("while kill -s KILL 4242 2>/dev/null; do sleep 1; done", KILL_SIG),
    ("for i in 1 2 3; do kill -15 4242 2>/dev/null || break; sleep 1; done", KILL_SIG),
    ("pid=4242; while kill -9 $pid 2>/dev/null; do sleep 1; done", KILL_SIG),
    ("sleep 5; tail -c 300 out.txt; kill -HUP 4242 && echo sent", KILL_SIG),
    # a real kill beside a probe: the probe hides nothing
    ("until ! kill -0 4242 2>/dev/null; do sleep 5; done; kill -9 4242", KILL_SIG),
    ("if kill -0 4242 2>/dev/null; then kill -KILL 4242; fi", KILL_SIG),
    ("while kill -0 4242; do kill -TERM 4242; sleep 1; done", KILL_SIG),
    ("kill -0 4242 && kill 4242", KILL_PID),
    ("until ! kill -0 4242; do sleep 1; done; kill 4242", KILL_PID),
    # by pattern
    ("if kill -0 4242; then pkill -f claude; fi", KILL_FAMILY),
    ("until ! kill -0 4242; do sleep 1; done; killall docker", KILL_FAMILY),
    ("for i in 1 2; do pkill -f svc-daemon; done", RUNTIME_GUARD),
    ("while kill -0 4242; do sleep 1; done; pgrep -f svc-daemon | xargs kill", RUNTIME_GUARD),
    # the probe's own words: -0 is no probe once another word can name a signal (bash reads -s SIG and -n NUM,
    # attached too, after -0), a PID bash computes, or a variable something else can have set
    ("until ! kill -0 -s KILL 4242; do sleep 1; done", KILL_SIG),
    ('if kill -0 "-sKILL" 4242; then echo x; fi', KILL_SIG),
    ("while kill -0 ${X:--s} KILL 4242; do sleep 1; done", KILL_SIG),
    ("if kill -0 $(cat run.pid); then echo alive; fi", KILL_SIG),
    ("until ! kill -0 `cat run.pid`; do sleep 1; done", KILL_SIG),
    ('pid=4242; pid="-s KILL 1"; while kill -0 $pid; do sleep 1; done', KILL_SIG),
    ("pid=4242; read pid; while kill -0 $pid; do sleep 1; done", KILL_SIG),
    ('pid=4242; for pid in "-s KILL 1"; do kill -0 $pid; done', KILL_SIG),
    ("while kill -0 $pid; do sleep 1; done; pid=4242", KILL_SIG),
    ("false && pid=4242; if kill -0 $pid; then echo alive; fi", KILL_SIG),
    ("pid=4242; if kill -0 $pid 4343; then echo alive; fi", KILL_SIG),
    ("pid=-9; if kill -0 $pid 4242; then echo alive; fi", KILL_SIG),
    ("x=$(kill -0 4242 && kill -9 4242)", KILL_SIG),
    ("uv run kill -0 4242; npx kill -9 4242", KILL_SIG),
]


@pytest.mark.parametrize("command,label", SIGNALS)
def test_a_signal_sent_to_a_process_is_still_refused_in_each_position(sandbox, command, label):
    r = bash_safety(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


def test_a_monitors_real_kill_is_still_refused(sandbox):
    r = bash_safety(sandbox, "until ! kill -9 4242 2>/dev/null; do sleep 5; done; echo gone", description="stop it")
    assert r.returncode == 2 and KILL_SIG in r.stderr, r.stderr


# ── A read of a settings file is no change to it ─────────────────────────────
# 3 recorded refusals: `command grep` and `git check-ignore` naming a Claude Code settings file. The rule judges a
# command at its command word as hooks/lib/shell_parse.py resolves it, and a git command by
# hooks/lib/bash_read_only.py's proof that it only reads.
@pytest.fixture()
def project(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "settings.json").write_text('{"env": {"A": "1"}, "permissions": {"deny": ["Bash(rm:*)"]}}')
    (proj / ".claude.json").write_text('{"env": {"A": "1"}}')
    return proj


def switch_guard(sandbox, project, command):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "misread-refusals",
               "cwd": str(project), "hook_event_name": "PreToolUse"}
    env = dict(sandbox["env"], CLAUDE_PROJECT_DIR=str(project))
    return subprocess.run(["python3", str(HOOKS / "pretool-harness-switch-guard.py")], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, cwd=str(project), timeout=120)


SETTINGS_READS = [
    "echo '--- mentions'; command grep -c 'model-x' /srv/other/.claude.json {P}/.claude.json",
    "P='qa-scratch|baseline'; command grep -oE '\"/[^\"]*('\"$P\"')[^\"]*\"' {P}/.claude.json "
    "/srv/accounts/*/.claude.json 2>/dev/null | sort -u | head",
    'cd {P}; grep -n "research" .claude/settings.json | cut -c1-200 | head -40; '
    "git check-ignore -v .claude/settings.json; git ls-files .claude/settings.json .claude/settings.local.json",
    "timeout 20 cat .claude/settings.json",
    "git -C {P} diff -- .claude/settings.json",
]


@pytest.mark.parametrize("command", SETTINGS_READS)
def test_a_search_or_print_of_a_settings_file_passes(sandbox, project, command):
    r = switch_guard(sandbox, project, command.replace("{P}", str(project)))
    assert r.returncode == 0, (command, r.stderr)


SETTINGS_WRITES = [
    "command tee .claude/settings.json < /dev/null",
    "command cp /srv/other/settings.json .claude/settings.json",
    "command sed -i 's/on/off/' .claude/settings.json",
    "timeout 20 rm .claude/settings.json",
    "command grep -c x notes.md > .claude/settings.json",
    "time -o .claude/settings.json cat notes.md",            # the wrapper's own operand is the file written
    "git check-ignore -v notes.md > .claude/settings.json",
    "git checkout -- .claude/settings.json",
    "git -C {P} checkout HEAD -- .claude/settings.json",
    "git config --file .claude/settings.json core.x y",
    "command grep -c x notes.md > {P}/.claude.json",
]


@pytest.mark.parametrize("command", SETTINGS_WRITES)
def test_a_write_of_a_settings_file_is_still_refused_behind_the_same_words(sandbox, project, command):
    r = switch_guard(sandbox, project, command.replace("{P}", str(project)))
    assert r.returncode == 2 and "harness-switch:" in r.stderr and "Claude Code settings file" in r.stderr, \
        (command, r.stderr)


@pytest.mark.parametrize("command", ["command touch {H}/.harness-switch/off", "echo x > {H}/.harness-switch/off",
                                     "timeout 5 rm -rf {H}/.harness-switch"])
def test_a_write_of_the_switch_state_is_still_refused(sandbox, project, command):
    r = switch_guard(sandbox, project, command.replace("{H}", str(REPO)))
    assert r.returncode == 2 and "harness-switch:" in r.stderr and "switch's state" in r.stderr, (command, r.stderr)


# ── dd reading a file to standard output writes no disk ──────────────────────
# 1 recorded refusal: twelve `dd if=$F bs=1M skip=N count=1 status=none | sed -n 2p | cut ...` lines sampling a log.
DISK = "Destructive disk operation"
DD_READS = [
    "F=/var/log/app.log\n" + "\n".join(
        f"dd if=$F bs=1M skip={n} count=1 status=none | sed -n '2p' | cut -c1-110" for n in (500, 1000, 2000)),
    "for n in 1 2; do\ndd if=/var/log/app.log bs=1M skip=$n count=1 status=none | wc -c\ndone",
]


@pytest.mark.parametrize("command", DD_READS)
def test_dd_reading_a_file_to_standard_output_passes(sandbox, command):
    r = bash_safety(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


DD_WRITES = [
    "F=/dev/sda\ndd if=/dev/zero of=$F bs=1M count=1 status=none | sed -n '2p'",
    "F=/var/log/app.log\ndd if=$F bs=1M count=1 status=none > /dev/sda",
    "F=/var/log/app.log\ndd if=$F bs=1M count=1 status=none | sed -n '2p'\ndd if=/dev/zero of=/dev/sdb bs=1M",
    "for n in 1 2; do dd if=/dev/zero of=/dev/sd$n bs=1M count=1; done",
    "F=/var/log/app.log\ndd if=$F $EXTRA | head -c 100",           # a computed word may be of=
    'F=/var/log/app.log\ndd if=$F "of=$X" | head -c 100',
    "F=/var/log/app.log\ndd if=$F status=none | sudo dd of=/dev/sda",
    "dd if=/var/log/app.log status=none | head -c 10; mkfs.ext4 /dev/sdb1",
    "exec 3>/dev/sda; dd if=/dev/zero of=/dev/fd/3 status=none | cat",
]


@pytest.mark.parametrize("command", DD_WRITES)
def test_a_destructive_dd_is_still_refused_in_the_same_shape(sandbox, command):
    r = bash_safety(sandbox, command)
    assert r.returncode == 2 and DISK in r.stderr, (command, r.stderr)


# ── A sensitive name whose reader writes no file ─────────────────────────────
# 1 of 2 recorded refusals: `ls <dir>/.env >/dev/null 2>&1 && echo exists`. Standard output thrown into /dev/null,
# with no other file opened, puts what the command reads in no file.
SENSITIVE_READ = "Attempting to redirect from/to sensitive file via Bash"
SENSITIVE_WRITE = "Attempting to write to sensitive file via Bash"


@pytest.mark.parametrize("command", [
    "hostname -I 2>&1 | head -2; ls /srv/app/.env >/dev/null 2>&1 && echo env-exists",
    "test -f .env > /dev/null && echo yes",
])
def test_a_command_whose_output_is_thrown_away_names_a_secret_file_freely(sandbox, command):
    r = bash_safety(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


@pytest.mark.parametrize("command,label", [
    ("cat /srv/app/.env > /srv/work/copy.txt 2>&1 && echo copied", SENSITIVE_READ),
    ("cat /srv/app/.env > /dev/null 2> /srv/work/err.txt", SENSITIVE_READ),
    ("cat /srv/app/.env > /dev/null 3> /srv/work/copy.txt", SENSITIVE_READ),
    ("cp /srv/app/.env /srv/work/copy.txt >/dev/null 2>&1 && echo copied", SENSITIVE_READ),
    ("wget -q https://x/.env > /dev/null", SENSITIVE_READ),     # wget names its own output file .env
    ("ls /srv/app >/dev/null 2>&1 && echo KEY=1 > /srv/app/.env", SENSITIVE_WRITE),
    ("echo KEY=1 > /srv/app/.env 2>/dev/null", SENSITIVE_WRITE),
    ("tee /srv/app/.env < x.txt > /dev/null", SENSITIVE_WRITE),
])
def test_a_write_or_a_kept_read_of_a_secret_file_is_still_refused(sandbox, command, label):
    r = bash_safety(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)


# ── A package-manager command where no manifest can reach a protected workspace ──
# 3 recorded refusals: `npm view <pkg> version` and `npm init -y` in a directory with no package.json from it up
# to /, read as a script-run whose manifest could not be resolved.
NO_MANIFEST = [
    "timeout 25 npm view @scope/tool version 2>&1 | tail -2",
    "echo '--- npm latest'; timeout 25 npm view @scope/tool version 2>&1 | tail -1; echo '--- install dir'; ls /usr/lib",
    "ls {R}/node_modules | wc -l; mkdir -p {R}/pwlibs && cd {R}/pwlibs && npm init -y >/dev/null 2>&1; "
    "npm install @playwright/test 2>&1 | tail -2; ls node_modules/@playwright",
]


@pytest.mark.parametrize("command", NO_MANIFEST)
def test_a_package_manager_command_with_no_manifest_above_it_passes(sandbox, command):
    r = bash_safety(sandbox, command.replace("{R}", sandbox["repo"]))
    assert r.returncode == 0, (command, r.stderr)


PROTECTED_RUNS = [
    "cd {M} && npm view @scope/tool version",                 # under the protected root: still a script-run there
    "cd {M} && yarn build",
    "cd {M}/packages/svc-cli && npm run build",
    "mkdir -p {M}/fresh && cd {M}/fresh && npm init -y",      # no manifest of its own, the protected root above it
    "yarn --cwd packages/svc-cli dev",                        # a protected script path with no manifest yet
    'cd "$DIR" && npm run build',                             # a cwd the text does not give
    "yarn svc daemon start",                                  # the protected command, by name
    "timeout 25 npm exec svc -- daemon start",
    "npm install -g svc-coder",                               # a real global install
    "timeout 25 npm view @scope/tool version; npm i -g svc-coder",
]


@pytest.mark.parametrize("command", PROTECTED_RUNS)
def test_a_run_that_reaches_a_protected_workspace_is_still_refused(sandbox, command):
    r = bash_safety(sandbox, command.replace("{M}", sandbox["mono"]))
    assert r.returncode == 2 and RUNTIME_GUARD in r.stderr, (command, r.stderr)
