"""Default hard bans (BS-19, CLAUDE_HARD_BANNED_SCRIPTS unset): a shell that only reads the script (noexec:
`bash -n`, `sh -n`, `bash -o noexec`, `-n` inside a short-option cluster) and a unary file test (`test`, `[`,
`[[ ... ]]`) do not run the script, so they pass; every form that runs it is still refused.

The relaxation is a strict allow-list of whole-command shapes: the entire command must parse cleanly into a list
joined by `&&`, `||` or `;` (no pipe) of simple commands, each a noexec non-verbose bash/sh/dash written bare or as
a system bin path, one unary file test, or echo/printf/true/false/`:` with plain literal words; no substitution,
expansion, assignment, function, alias, here-doc or wrapper anywhere and no redirection but a dup or /dev/null.
Any other command falls back to the base reading of the raw text, so a later command that reads the shell's own
text back (`/proc/$$/cmdline`), a quote-split `eval` or `alias`, or a shell word that is not a system shell
(`./bash`, `/tmp/p/bash`) is refused as before. The shell options of a shell that runs are read as bash/dash read
them (the last of `-n` / `+n` / `-o noexec` / `+o noexec` wins, an interactive shell ignores noexec), so
`bash -n +n x.sh` names a run.

Every case goes through the real hook entry, hooks/pretool-bash-safety.sh, with a scratch HOME, config dir,
state dir and protected-runtime data file; the quote-split eval/alias forms are also checked against
hard_ban_rule itself.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "pretool-bash-safety.sh"
HANG_GUARD = 900  # seconds: a bound only a hung child reaches; a slow machine must never read as a failure
sys.path.insert(0, str(REPO / "hooks"))
from lib.runtime_guard.config import REQUIRED_KEYS  # noqa: E402

KNOBS = (
    "CLAUDE_DEV_CONTAINERS", "CLAUDE_DEV_SYSTEMD", "CLAUDE_DAEMON_RESTART_GRANT_HELPER",
    "CLAUDE_PROTECTED_DAEMON_PREFIX", "CLAUDE_PROTECTED_DAEMON_TARGETS",
    "CLAUDE_HARD_BANNED_SCRIPTS", "CLAUDE_HOME",
    "CLAUDE_TASK_ID", "CLAUDE_COMMAND_GATE",
)


@pytest.fixture
def env(tmp_path):
    for name in ("home", "config", "grants", "state"):
        (tmp_path / name).mkdir()
    runtime = tmp_path / "protected-runtime.json"
    runtime.write_text(json.dumps({"schema_version": 1, **{k: [] for k in REQUIRED_KEYS}}))
    (tmp_path / "gitconfig").write_text("")
    e = {k: v for k, v in os.environ.items() if k not in KNOBS}
    e.update({
        "HOME": str(tmp_path / "home"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "config"),
        "CLAUDE_STATE_DIR": str(tmp_path / "state"),
        "CLAUDE_DAEMON_RESTART_SENTINEL_DIR": str(tmp_path / "grants"),
        "CLAUDE_PROTECTED_RUNTIME_FILE": str(runtime),
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
    })
    return e


def hook(env, command, **extra):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command},
                          "session_id": "hard-ban-noexec-test"})
    return subprocess.run(["bash", str(HOOK)], input=payload, text=True, capture_output=True,
                          env={**env, **extra}, timeout=HANG_GUARD)


@pytest.mark.parametrize("command", (
    # the lane's must-pass examples
    "bash -n scripts/session-recovery.sh",
    "[[ ! -f scripts/restart-all-sessions.sh ]] && echo missing",
    # noexec spellings bash and dash both honour
    "sh -n scripts/session-recovery.sh",
    "dash -n scripts/restart-all-sessions.sh",
    "bash -nx scripts/session-recovery.sh",
    "bash -xn scripts/session-recovery.sh",
    "bash -o noexec scripts/session-recovery.sh",
    "bash -on noexec scripts/session-recovery.sh",
    "bash +n -n scripts/session-recovery.sh",
    "bash -n -- scripts/session-recovery.sh",
    "bash -n -O extglob scripts/session-recovery.sh",
    "bash --norc -n scripts/session-recovery.sh",
    "/bin/bash -n scripts/session-recovery.sh",
    # -c with noexec: neither the string nor the $0 operand runs
    "bash -n -c x scripts/session-recovery.sh",
    "bash -n -c 'session-recovery --all'",
    # in a list
    "bash -n scripts/session-recovery.sh && echo syntax-ok",
    "bash -n scripts/session-recovery.sh 2>&1",
    "bash -n scripts/session-recovery.sh >/dev/null 2>&1",
    # test operands
    "[[ -f scripts/session-recovery.sh ]] && echo present",
    "[ ! -f scripts/session-recovery.sh ] || echo present",
    "test -x scripts/restart-all-sessions.sh",
    "if [[ -x ./scripts/session-recovery.sh ]]; then echo ok; fi",
    "[[ scripts/session-recovery.sh == *.sh ]]",
    "[ -n scripts/session-recovery.sh ]",
))
def test_noexec_shell_and_test_operand_pass(env, command):
    r = hook(env, command)
    assert r.returncode == 0, r.stderr
    assert "hard-banned script" not in r.stderr


# eval, alias and a function name split by quotes or an escape, which a raw keyword scan does not see
QUOTE_SPLIT = (
    "bash -n scripts/session-recovery.sh; eva\"\"l '\"$''_\"'",
    "bash -n scripts/session-recovery.sh; ev\\al '\"$''_\"'",
    "shopt -s expand_aliases\nali\"\"as bash='sh -c '\\''\"$2\"'\\'' sh'\nbash -n scripts/session-recovery.sh",
    "shopt -s expand_aliases; ali\"\"as bash='bash +n'; bash -n scripts/session-recovery.sh",
    "bas\"\"h() { \"$2\"; }; bash -n scripts/session-recovery.sh",
    "bash -n scripts/session-recovery.sh; e\\val \"$_\"",
)


@pytest.mark.parametrize("command,name", (
    # the lane's must-still-refuse examples
    ("bash scripts/session-recovery.sh", "session-recovery"),
    ("! ./scripts/session-recovery.sh", "session-recovery"),
    ("bash --norc scripts/session-recovery.sh", "session-recovery"),  # --norc is not noexec
    ("bash -n scripts/session-recovery.sh; bash scripts/session-recovery.sh", "session-recovery"),
    ("bash -n scripts/session-recovery.sh && scripts/session-recovery.sh", "session-recovery"),
    # noexec turned off again: the last option wins
    ("bash -n +n scripts/session-recovery.sh", "session-recovery"),
    ("bash -n +nx scripts/session-recovery.sh", "session-recovery"),
    ("bash -n +o noexec scripts/session-recovery.sh", "session-recovery"),
    ("bash -o noexec +o noexec scripts/session-recovery.sh", "session-recovery"),
    ("bash -n -o noexec +n scripts/restart-all-sessions.sh", "restart-all-sessions"),
    # options the command-word pattern does not read still name a run
    ("bash +x scripts/session-recovery.sh", "session-recovery"),
    ("bash -o errexit scripts/restart-all-sessions.sh", "restart-all-sessions"),
    ("bash -o pipefail -c 'session-recovery --all'", "session-recovery"),
    # an interactive shell ignores noexec
    ("bash -n -i scripts/session-recovery.sh", "session-recovery"),
    ("bash -ni scripts/session-recovery.sh", "session-recovery"),
    # output piped on (`-v` echoes the script) is not inert
    ("bash -nv scripts/session-recovery.sh 2>&1 | bash", "session-recovery"),
    # noexec read only for bash/sh/dash; an unknown long option is not read as noexec
    ("zsh -n scripts/session-recovery.sh", "session-recovery"),
    ("bash --frobnicate -n scripts/session-recovery.sh", "session-recovery"),
    # a test whose operand runs a substitution, and a test followed by a run
    ("[[ -f $(session-recovery) ]]", "session-recovery"),
    ("[[ -f scripts/session-recovery.sh ]] && ./scripts/session-recovery.sh", "session-recovery"),
    ("test -f x && restart-all-sessions", "restart-all-sessions"),
    # a noexec shell nested in a payload is still read as before (fail closed)
    ("bash -c 'bash -n scripts/session-recovery.sh; session-recovery'", "session-recovery"),
    # the -v echo of the script carried on by a group, subshell, substitution or redirection runs it;
    # a noexec shell is read as inert only as a top-level simple command, not verbose, output not redirected
    ("{ bash -nv scripts/session-recovery.sh; } 2>&1 | bash", "session-recovery"),
    ("( bash -nv scripts/session-recovery.sh ) 2>&1 | bash", "session-recovery"),
    ('eval "$(bash -nv scripts/session-recovery.sh 2>&1)"', "session-recovery"),
    ("bash -nv scripts/session-recovery.sh 2> >(bash)", "session-recovery"),
    ("bash <(bash -nv scripts/session-recovery.sh 2>&1)", "session-recovery"),
    ("bash -nv scripts/session-recovery.sh 2>/tmp/x.sh; bash /tmp/x.sh", "session-recovery"),
    ("x=$(bash -n scripts/restart-all-sessions.sh) && echo ok", "restart-all-sessions"),
    ("{ bash -n -o verbose scripts/session-recovery.sh; } 2>&1 | bash", "session-recovery"),
    ("bash -n --verbose scripts/session-recovery.sh 2>&1 | bash", "session-recovery"),
    ("exec 2>/tmp/x.sh; bash -nv scripts/session-recovery.sh; bash /tmp/x.sh", "session-recovery"),
    # a function or alias named like the shell or a test builtin replaces it
    ('bash() { shift; command bash "$@"; }; bash -n scripts/session-recovery.sh', "session-recovery"),
    ('function sh { shift; command bash "$@"; }; sh -n scripts/session-recovery.sh', "session-recovery"),
    ('[() { bash "$3"; }; [ ! -f scripts/session-recovery.sh ]', "session-recovery"),
    ('test () { bash "$3"; }; test ! -f scripts/session-recovery.sh', "session-recovery"),
    ("eval 'bash() { shift; command bash \"$@\"; }'; bash -n scripts/session-recovery.sh", "session-recovery"),
    ("alias bash='bash -c \"$2\"'; bash -n scripts/session-recovery.sh", "session-recovery"),
    # a later word that re-runs an earlier operand ($_, a DEBUG trap reading BASH_COMMAND)
    ('bash -n scripts/session-recovery.sh; "$_"', "session-recovery"),
    ('[[ ! -f scripts/session-recovery.sh ]] && "$_"', "session-recovery"),
    ("trap 'c=${BASH_COMMAND#* -n }; $c' DEBUG; bash -n scripts/session-recovery.sh", "session-recovery"),
    # operands bash evaluates as a subscript or as arithmetic run their substitutions
    ("[[ 'a[$(scripts/session-recovery.sh)]' -eq 0 ]]", "session-recovery"),
    ("[[ -v 'a[$(scripts/session-recovery.sh)]' ]]", "session-recovery"),
    ("[[ 0 -lt 'a[$(scripts/session-recovery.sh)]' ]]", "session-recovery"),
    ("[[ -f x && 'a[$(scripts/session-recovery.sh)]' -ge 1 ]]", "session-recovery"),
    # the shell's own text read back by a later command and run
    ("bash -n scripts/session-recovery.sh; tr '\\0' ' ' < /proc/$$/cmdline | grep -o 'scripts/[a-z-]*\\.sh' "
     "| head -1 | sh", "session-recovery"),
    ("bash -n scripts/session-recovery.sh; cat /proc/$$/cmdline | sh", "session-recovery"),
    # a shell word that is not a system shell may be any program
    ("/tmp/p/bash -n scripts/session-recovery.sh", "session-recovery"),
    ("./bash -n scripts/session-recovery.sh", "session-recovery"),
    ("sudo bash -n scripts/session-recovery.sh", "session-recovery"),
    ("x=$(bash -n scripts/session-recovery.sh) && echo ok", "session-recovery"),
) + tuple((c, "session-recovery") for c in QUOTE_SPLIT))
def test_running_the_script_is_still_refused(env, command, name):
    r = hook(env, command)
    assert r.returncode == 2, r.stderr
    assert f"hard-banned script '{name}' is refused" in r.stderr


@pytest.mark.parametrize("command", QUOTE_SPLIT)
def test_hard_ban_rule_itself_refuses_quote_split_forms(command, monkeypatch, capsys):
    """The hard-ban rule on its own refuses these, not only some other rule of the pipeline."""
    from lib import bash_safety_rules
    monkeypatch.delenv("CLAUDE_HARD_BANNED_SCRIPTS", raising=False)
    with pytest.raises(SystemExit) as exc:
        bash_safety_rules.hard_ban_rule(command)
    assert exc.value.code == 2
    assert "hard-banned script 'session-recovery' is refused" in capsys.readouterr().err


def test_explicit_value_keeps_match_anywhere(env):
    """A set CLAUDE_HARD_BANNED_SCRIPTS keeps its match-anywhere meaning: the noexec reading is the default's."""
    r = hook(env, "bash -n scripts/demo-recovery.sh", CLAUDE_HARD_BANNED_SCRIPTS="demo-recovery")
    assert r.returncode == 2 and "hard-banned script 'demo-recovery'" in r.stderr


@pytest.mark.parametrize("program", ["/usr/bin/cat", "/usr//bin/cat", "/usr/bin/../bin/cat", "cat"])
def test_a_read_is_a_read_however_the_program_directory_is_spelled(env, program):
    """g-loctriage U39: the same program, named through another spelling of its directory, gets the same verdict;
    running the script stays refused in every spelling."""
    r = hook(env, f"{program} demo-recovery.sh", CLAUDE_HARD_BANNED_SCRIPTS="demo-recovery")
    assert r.returncode == 0 and "hard-banned script" not in r.stderr, r.stderr
    shell = program.replace("cat", "bash")
    r = hook(env, f"{shell} demo-recovery.sh", CLAUDE_HARD_BANNED_SCRIPTS="demo-recovery")
    assert r.returncode == 2 and "hard-banned script 'demo-recovery'" in r.stderr
