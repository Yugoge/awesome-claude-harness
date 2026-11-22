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
           "CLAUDE_HARD_BANNED_SCRIPTS": "svc-session-recovery|svc-restart"}
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
KILL_FAMILY = "Killing processes by name or pattern"
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
    ("pid=4242; source ./env.sh; while kill -0 $pid; do sleep 1; done", KILL_SIG),   # a sourced file may set it
    ("x=$(kill -0 4242 && kill -9 4242)", KILL_SIG),
    ("if kill -0 4242 > /etc/hosts; then echo alive; fi", KILL_SIG),   # no plain redirection: read as before
    ("uv run kill -0 4242; npx kill -9 4242", KILL_SIG),
    # the remaining positions the probe passes in: an || list in a loop's condition, an && list in an if's, a list
    # after a heredoc fed to an interpreter
    ('until grep -q "FEEDBACK" out.txt || ! kill -9 4242 2>/dev/null; do sleep 5; done', KILL_SIG),
    ('until ! kill -9 4242 2>/dev/null || grep -q "FEEDBACK" out.txt 2>/dev/null; do sleep 5; done', KILL_SIG),
    ("if grep -q x <(tail -n +60 out.txt) && ! kill -TERM 4242 2>/dev/null; then echo y; fi", KILL_SIG),
    ("python3 - <<'E'\nprint('ok')\nE\nsleep 1; kill -9 4242 && echo sent", KILL_SIG),
    # the three real kills recorded beside the probes
    ('kill 4242; sleep 1; ps aux | grep "[r]un_reconcile.py" | wc -l; tail -c 300 /srv/work/live_run.out', KILL_PID),
    ("kill 4242; sleep 2; cd /srv/work/frontend; tail -3 /srv/work/next-start.log", KILL_PID),
    ('pkill -f "next dev -p 3000" ; sleep 1; tail -5 /srv/work/next-build.log | cut -c1-200', RUNTIME_GUARD),
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
    'F=/var/log/app.log\ndd if="$F" bs=1M skip=8 count=1 status=none | wc -c',
    "echo sample\ndd if=/var/log/app.log bs=1M skip=8 count=1 status=none | cut -c1-110",
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
    # an operand the command does not set once to a plain path may split into an of=: read as before
    "read F\ndd if=$F bs=1M count=1 status=none | wc -c",
    'F="/var/log/app.log of=/dev/sda"\ndd if=$F bs=1M count=1 status=none | wc -c',
    "F=/var/log/app.log; F=$(cat name.txt)\ndd if=$F bs=1M count=1 status=none | wc -c",
    "F=/var/log/app.log\nsource ./env.sh\ndd if=$F bs=1M count=1 status=none | wc -c",
    "for n in 1 2; do\ndd if=/var/log/app.log bs=1M skip=$n count=1 status=none | wc -c\ndone",
    # a dd that writes a file is not the reading dd: the whole-command reading refuses it as before
    "F=/var/log/app.log\ndd if=$F of=/etc/hosts bs=1M count=1",
    "F=/var/log/app.log\ndd if=$F bs=1M count=1 status=none > /etc/hosts",
    "F=/var/log/app.log\ndd if=$F of=/srv/work/copy.bin bs=1M count=1",
]


@pytest.mark.parametrize("command", DD_WRITES)
def test_a_destructive_dd_is_still_refused_in_the_same_shape(sandbox, command):
    r = bash_safety(sandbox, command)
    assert r.returncode == 2 and DISK in r.stderr, (command, r.stderr)


# ── A sensitive name whose reader writes no file ─────────────────────────────
# 1 of 2 recorded refusals: `ls <dir>/.env >/dev/null 2>&1 && echo exists`. A command hooks/lib/bash_read_only.py
# proves a reader, its standard output thrown into /dev/null, puts what it reads in no file.
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
    # a program that can write a file of its own is no proven reader, whatever its standard output does
    ("tee /srv/work/copy.txt < /srv/app/.env > /dev/null", SENSITIVE_READ),
    ("sed -n 'w /srv/work/copy.txt' /srv/app/.env > /dev/null", SENSITIVE_READ),
    ("python3 keep.py /srv/app/.env > /dev/null", SENSITIVE_READ),
    ("sort < /srv/app/secrets.yaml > /dev/null", SENSITIVE_READ),
    ('bash -c "cat /srv/app/.env > /dev/null"', SENSITIVE_READ),      # not at the top level: read as before
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


# ── A fresh temp directory is not the state directory ────────────────────────
# 1 recorded refusal: `X=$(mktemp -d <state dir>/name.XXXXXX)` and then `tar -x -C "$X"`. mktemp makes a new name
# below the template's directory, so the archive lands in a child of the state directory, never beside the flag.
CONSENT = "do-consent-flag-write"


def test_an_archive_extracted_into_a_fresh_temp_directory_passes(sandbox):
    command = ('X=$(mktemp -d {S}/probe-tracked.XXXXXX); C=$(mktemp -d {S}/probe-cache.XXXXXX)\n'
               'git -C /srv/work archive HEAD | tar -x -C "$X"\n'
               'echo "tracked-only copy: $(find "$X" -type f | wc -l) files"\n'
               'ls -la "$C"/*/ 2>&1 | head -12').replace("{S}", sandbox["state"])
    r = bash_safety(sandbox, command)
    assert r.returncode == 0, r.stderr


CONSENT_WRITES = [
    "git -C /srv/work archive HEAD | tar -x -C {S}",
    'X=$(mktemp -d {S}/probe.XXXXXX); git -C /srv/work archive HEAD | tar -x -C "$X/.."',
    'X=$(mktemp -d {S}/probe.XXXXXX; echo {S}); tar -x -C "$X" < a.tar',
    'X=$(mktemp -d {S}/probe.XXXXXX | xargs dirname); tar -x -C "$X" < a.tar',
    'X=$(mktemp -d {S}/probe.XXXXXX); X={S}; tar -x -C "$X" < a.tar',
    'X=$(mktemp -d -p {S}); tar -x -C "$X" < a.tar',           # a form whose path is not the template's: as before
    'X=$(Y=1); tar -x -C "$X" < a.tar; tar -x -C {S} < b.tar',  # a substitution with no command word reads on
    'X=$(mktemp -d {S}/probe.XXXXXX); touch "$X/../claude-orchestrator-consent-abc.flag"',
    'X=$(mktemp -d {S}/probe.XXXXXX); cp -r src/. "$X/.."',
    "touch {S}/claude-orchestrator-consent-abc.flag",
    "echo 1 > {S}/claude-orchestrator-consent-abc.flag",
]


@pytest.mark.parametrize("command", CONSENT_WRITES)
def test_a_write_into_the_state_directory_or_of_the_flag_is_still_refused(sandbox, command):
    r = bash_safety(sandbox, command.replace("{S}", sandbox["state"]))
    assert r.returncode == 2 and CONSENT in r.stderr, (command, r.stderr)


# ── A command with no git commit bypasses no commit hook ─────────────────────
# 1 recorded refusal: a double-quoted `python3 -c "..."` inside a double-quoted $(...), with `git status` and a
# path holding `config` after it. The guard's own splitter cannot follow that quoting; hooks/lib/shell_parse.py
# can, and reads no commit and no config in it.
BYPASS = "commit-hook-bypass"
NO_COMMIT = ('cd /srv/work; echo "files: $(python3 -c "\nimport json\nprint(len(json.load(open(\'.claude/files.json\'))))")"; '
             "git status --porcelain src/alpha.py; ls src/_resolver.py config/rules.json")
NO_COMMIT_LOOP = ('cd /srv/work; for f in alpha beta; do echo "$f: $(python3 -c "\nimport json;d=json.load(open(\'.claude/files.json\'))\n'
                  'print([k for k,(m,c) in d.items() if any(x.endswith(\'/$f.py\') for x in m+c)])")"; done; '
                  "git status --porcelain src/alpha.py; ls src/_resolver.py config/rules.json")


def test_a_command_with_no_commit_is_no_commit_hook_bypass(sandbox):
    r = bash_safety(sandbox, NO_COMMIT)
    assert r.returncode == 0, r.stderr
    # the recorded command itself: no longer this rule's refusal (the removal policy still reads its inline Python)
    assert BYPASS not in bash_safety(sandbox, NO_COMMIT_LOOP).stderr


COMMIT_BYPASSES = [
    'echo "$(bash -c "git commit --no-verify -m x")"',
    'echo "$(eval "git commit -n -m x")"',
    'echo "$(sh -c "git config --global core.hooksPath /x")"',
    'echo "files: $(python3 -c "print(1)")"; git commit --no-verify -m x',
    'echo "files: $(python3 -c "print(1)")"; git -c core.hooksPath=/dev/null commit -m x',
    'echo "files: $(python3 -c "print(1)")"; G=git; $G commit --no-verify -m x; ls config',
    'echo "files: $(python3 -c "import os; os.system(\'git commit --no-verify -m $f\')")"',
    "git commit --no-verify -m x",
]


@pytest.mark.parametrize("command", COMMIT_BYPASSES)
def test_a_commit_that_skips_the_hooks_is_still_refused(sandbox, command):
    r = bash_safety(sandbox, command)
    assert r.returncode == 2 and BYPASS in r.stderr, (command, r.stderr)


# ── A search of the banned script's file is no run of it ─────────────────────
# 1 recorded refusal, with a configured ban list (CLAUDE_HARD_BANNED_SCRIPTS, each entry matched anywhere): two
# `/usr/bin/grep -rI...` searches naming the script's file. A command hooks/lib/bash_read_only.py proves read-only
# as a whole runs nothing, so the name in it is searched, listed or printed.
BANNED = "hard-banned script"
BAN_READS = [
    '/usr/bin/grep -rIn -e "svc-dev/logs" -e "SVC_HOME_DIR" /srv/bin/svc-session-recovery.sh /etc/systemd/system/'
    'svc-watcher.service 2>/dev/null | cut -c1-220 | head -30; echo "--- any script mentioning .svc-dev:"; '
    '/usr/bin/grep -rIl "\\.svc-dev" /srv/bin /usr/local/bin 2>/dev/null | head -20',
    "cat /srv/bin/svc-session-recovery.sh",
    "ls -l /srv/bin/svc-restart.sh",
]


@pytest.mark.parametrize("command", BAN_READS)
def test_a_search_or_print_of_the_banned_scripts_file_passes(sandbox, command):
    r = bash_safety(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


BAN_RUNS = [
    "bash /srv/bin/svc-session-recovery.sh",
    "/srv/bin/svc-session-recovery.sh --all",
    "sudo /srv/bin/svc-restart.sh",
    "source /srv/bin/svc-session-recovery.sh",
    "nohup svc-session-recovery &",
    "cat /srv/bin/svc-session-recovery.sh | sh",                      # the print feeds a shell
    "/usr/bin/grep -l x /srv/bin/svc-restart.sh | xargs sh",
    "echo svc-restart | bash",
    'echo "$(svc-restart)"',
    "if /usr/bin/grep -q x /srv/bin/svc-restart.sh; then svc-restart; fi",
    "find /srv/bin -name 'svc-restart*' -exec sh {} \\;",
    "awk 'BEGIN { system(\"svc-restart\") }'",
    "/srv/evil/grep x /srv/bin/svc-restart.sh",                       # a grep that is not the system's
    "/usr/bin/grep -rn x /srv/bin/svc-restart.sh > /srv/work/out.txt",  # not read-only as a whole: as before
]


@pytest.mark.parametrize("command", BAN_RUNS)
def test_a_run_of_the_banned_script_is_still_refused(sandbox, command):
    r = bash_safety(sandbox, command)
    assert r.returncode == 2 and BANNED in r.stderr, (command, r.stderr)


# ── Three recorded refusals f199dfb1e no longer made: pinned so they stay gone ─
# Text written into a file is no command: the word kill in a heredoc `cat` writes to a page, and the phrase
# `npm install -g` in a heredoc that writes a Python file (both were the protected-runtime guard's refusals); and a
# search of a file another dispatch declared writes nothing (the tool policy's D8 refusal came from a write target
# read out of a grep pattern holding `\|` and the word install). These pass before this repair too.
TEXT_IN_A_FILE = [
    'cd "/srv/work/frontend/src/app/(product)/admin" && mkdir -p health && cat > health/loading.tsx <<\'E\'\n'
    "// route loading state: quiet shimmer rows.\n// Server component; reduced-motion animation kill ships from the kit CSS.\n"
    "export default function Loading() {\n  return null;\n}\nE\nls health",
    "cat > /srv/work/report.py <<'E'\nimport json\nnotes = [\"run npm install -g svc-coder by hand\", \"then restart\"]\n"
    "print(json.dumps(notes))\nE\necho ready",
]


@pytest.mark.parametrize("command", TEXT_IN_A_FILE)
def test_text_written_into_a_file_is_no_kill_and_no_global_install(sandbox, command):
    r = bash_safety(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


def test_a_search_of_another_dispatchs_file_names_no_write_target():
    import sys
    sys.path.insert(0, str(HOOKS))
    try:
        from lib import bash_write_targets
    finally:
        sys.path.pop(0)
    command = ('cd /srv/work; grep -n "registry" docs/dev/ticket-a.md docs/dev/ticket-b.md | cut -c1-400 | head -12; '
               'grep -n "alpha-W\\|beta-blocks\\|gamma.*shard\\|install.*registry" docs/dev/ticket-c.md | cut -c1-500 | head')
    assert bash_write_targets.extract_bash_write_targets_with_modes(command) == []
    written = bash_write_targets.extract_bash_write_targets_with_modes("install -m 644 notes.md docs/dev/ticket-c.md")
    assert written and "docs/dev/ticket-c.md" in {bash_write_targets._render(t, "") for t in written}


# ── A relative write target is judged where the command is at that point ─────
# 26 of 166 recorded write-location refusals had a relative target after a `cd`: tool-policy joined it to the project
# root. The shared parser now gives each write target the directories its command may run in
# (hooks/lib/shell_parse.CdScopes), and hooks/lib/bash_write_targets.py renders the path there.
def _write_paths(command):
    import sys
    sys.path.insert(0, str(HOOKS))
    try:
        from lib import bash_write_targets
    finally:
        sys.path.pop(0)
    return bash_write_targets.extract_bash_write_paths(command)


def test_a_relative_target_is_rendered_at_the_directory_in_effect(tmp_path, monkeypatch):
    (tmp_path / "there").mkdir()
    monkeypatch.chdir(tmp_path)
    assert _write_paths("echo x > plain.txt") == ["plain.txt"]
    assert _write_paths("cd /srv/scratch/ba/r00 && jq . a.json > t.json && cat t.json > a.json") == [
        "/srv/scratch/ba/r00/t.json", "/srv/scratch/ba/r00/a.json"]
    assert _write_paths("cd /srv/elsewhere && echo x > docs/codex/a.txt") == ["/srv/elsewhere/docs/codex/a.txt"]
    assert _write_paths("cd there; sed -i 1d ticket.md") == ["there/ticket.md"]        # the directory is there
    assert _write_paths("cd there && grep -c x t.md | head; sed -i s/a/b/ t.md") == ["there/t.md"]
    assert _write_paths("(cd there && echo x > in.txt); echo y > after.txt") == ["there/in.txt", "after.txt"]
    assert _write_paths("cd there && cp a.md ../reg/b.md") == ["there/../reg/b.md"]
    # a cd that may have failed leaves both directories; one that cannot be read leaves the target unresolved
    assert _write_paths("cd missing; sed -i 1d ticket.md") == ["ticket.md", "missing/ticket.md"]
    assert _write_paths("rm -rf there; cd there; echo x > f") == ["f", "there/f"]
    assert _write_paths('cd "$SOMEWHERE" && echo x > out.txt') == ["$(pwd)/out.txt"]
    assert _write_paths("for d in a b; do cd $d; echo x > h; done") == ["h", "$(pwd)/h"]
    assert _write_paths('cd "$SOMEWHERE" && echo x > /srv/abs/out.txt') == ["/srv/abs/out.txt"]


SESSION = "5e6f7a8b-1c2d-4e3f-9a0b-1c2d3e4f5a6b"


def tool_policy(tmp_path, project, command, caller=("a1b2c3d4e5f60718", "ba")):
    payload = {"session_id": SESSION, "cwd": str(project), "hook_event_name": "PreToolUse",
               "tool_name": "Bash", "tool_input": {"command": command}}
    if caller:
        payload.update(agent_id=caller[0], agent_type=caller[1], subagent_type=caller[1])
    home = tmp_path / "home"
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=str(project),
               CLAUDE_STATE_DIR=str(tmp_path / "state"), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(["python3", str(HOOKS / "pretool-tool-policy.py")], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(project), env=env, timeout=120)


@pytest.fixture()
def repo_project(tmp_path):
    project = tmp_path / "proj"
    for d in ("docs/codex", "src"):
        (project / d).mkdir(parents=True)
    return project


@pytest.mark.parametrize("command", [
    "cd {D}/ba && jq '.forms' forms.json > t_forms.json && cat t_forms.json > forms.json",  # its drafts directory
    "cd {P}/docs/codex; sed -i '2,4d' note-r05.md && sed -n '1,3p' note-r05.md | cut -c1-80",
    "cd {P}/docs/codex && grep -n x note-r04.md | cut -c1-80; sed -i 's/17/18/' note-r04.md; grep -c 18 note-r04.md",
])
def test_a_write_after_cd_into_the_roles_own_directory_passes(tmp_path, repo_project, command):
    session = os.path.join(os.path.realpath(os.environ.get("TMPDIR") or "/var/tmp/claude-scratch"), SESSION)
    r = tool_policy(tmp_path, repo_project, command.replace("{P}", str(repo_project)).replace("{D}", session))
    assert r.returncode == 0, (command, r.stderr)


@pytest.mark.parametrize("command,caller,reason", [
    # judged at the project root these read as the role's own docs/codex, or as no protected file at all
    ("cd {P}/src && echo x > docs/codex/a.py", ("a1b2c3d4e5f60718", "ba"), "denied_write_path_prefixes"),
    ("cd {P}/src; mkdir -p docs/codex; echo x > docs/codex/a.py", ("a1b2c3d4e5f60718", "ba"), "denied_write_path_prefixes"),
    ("cd {H} && echo '{}' > settings.machine.json", None, "no agent writes, deletes or renames it"),
    ("cd {H} && echo '{}' > settings.machine.json", ("a1b2c3d4e5f60718", "ba"), "no agent writes, deletes or renames it"),
])
def test_a_write_after_cd_out_of_the_roles_directories_is_refused(tmp_path, repo_project, command, caller, reason):
    r = tool_policy(tmp_path, repo_project, command.replace("{P}", str(repo_project)).replace("{H}", str(REPO)), caller)
    assert r.returncode == 2 and reason in r.stderr, (command, r.stderr)


@pytest.mark.parametrize("command", [
    "cd {P}/docs/codex-typo; echo x > note.md",          # the cd may fail: the write may land in the project root
    'cd "$SOMEWHERE" && echo x > note.md',               # an unknown directory: an unresolved target, as `> $D/note.md` is
    "cd /tmp/probe-r13 && printf '%s\\n' x > t.md",       # system temp that is not the role's own
])
def test_a_write_whose_directory_is_not_the_roles_stays_refused(tmp_path, repo_project, command):
    r = tool_policy(tmp_path, repo_project, command.replace("{P}", str(repo_project)))
    assert r.returncode == 2 and "BLOCKED by tool-policy.v1" in r.stderr, (command, r.stderr)


# ── Only a word that can be the source of the redirect is judged ─────────────
# 1 recorded refusal: `docker exec <c> sh -c '<greps>' > file`, where token, password and cookie stand only in a
# quoted grep pattern. The command line a shell or a runner is handed is read as the commands it holds; a search
# pattern and echo's text are no files.
RUNNER_GREP = ("cd /srv/work/reports && docker exec app-api sh -c 'cd /app && grep -rn --include=*.py -i -E "
               '"stale|expire|max_age|closed_at" app pipeline/worker.py | grep -v -i -E '
               '"jwt|token|cookie|session|oauth|redis|password|verify|reset|lock|ttl"\' > container__grep_staleness.txt; '
               "wc -l container__grep_staleness.txt; cut -c1-230 container__grep_staleness.txt")


@pytest.mark.parametrize("command", [
    RUNNER_GREP,
    "ssh build-host 'grep -v -i password /var/log/app.log | tail -5' > /srv/work/app-tail.txt",
    "sh -c 'grep -c token src/auth.py' > /srv/work/count.txt",
])
def test_a_pattern_inside_a_command_line_handed_to_a_runner_passes(sandbox, command):
    r = bash_safety(sandbox, command)
    assert r.returncode == 0, (command, r.stderr)


@pytest.mark.parametrize("command,label", [
    ("docker exec app-api sh -c 'cat /app/.env' > /srv/work/out.txt", SENSITIVE_READ),          # the file it reads
    ("docker exec app-api cat /app/.env > /srv/work/out.txt", SENSITIVE_READ),
    ("docker exec app-api sh -c 'grep -rn KEY /app/.env | grep -v -E \"jwt|token\"' > /srv/work/out.txt", SENSITIVE_READ),
    ("docker exec app-api sh -c 'echo KEY=1 > /app/.env' > /srv/work/out.txt", SENSITIVE_WRITE),
    ("ssh build-host 'cat ~/.aws/credentials' > /srv/work/out.txt", SENSITIVE_READ),
    ("sh -c 'cat .env' > /srv/work/out.txt", SENSITIVE_READ),
    ("grep -n token /srv/app/.env > /srv/work/hits.txt", SENSITIVE_READ),
    ('echo "$(cat /srv/app/.env)" > /srv/work/out.txt', SENSITIVE_READ),                        # computed text
    ("python3 -c 'print(open(\".env\").read())' > /srv/work/out.txt", SENSITIVE_READ),           # code, not a shell line
    ("sometool password > /srv/work/out.txt", SENSITIVE_READ),    # a program with no table: any word may be a file it reads
])
def test_a_secret_file_read_into_a_kept_output_is_still_refused(sandbox, command, label):
    r = bash_safety(sandbox, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)
