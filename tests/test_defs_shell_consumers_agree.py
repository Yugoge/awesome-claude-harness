"""Hooks that read one definition of a shell fact decide alike on the inputs where their copies differed.

Each hook below refuses its own base command. A wrapper, runner, payload option or shell
definition around that command is a fact about the shell, and the hooks read it from one
definition (shell_parse); so every hook that refuses the bare command refuses it behind
the shape too. The shapes are the ones the 2026-11 duplicate-definition audit found the
hooks disagreeing on (each family's name is the test id).

Every hook runs as a subprocess with a scratch HOME, state directory, TMPDIR and project.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"

# key: (hook file, the hook's refused base command, agent (id, type) or None)
BASE = {
    "ui": ("pretool-wrapper-userintent.py", "python3 scripts/break-overnight-lock.py", None),
    "gp": ("pretool-git-privilege-guard.py", "git commit -m x", None),
    "bs": ("pretool-bash-safety.sh", "rm -rf build", None),
    "cg": ("pretool-claude-config-guard.py", "cp /etc/hostname .claude/hooks/x.py", None),
    "hs": ("pretool-harness-switch-guard.py", "cp /etc/hostname .claude/settings.json", None),
    "tp": ("pretool-tool-policy.py", "cp /etc/hostname src/x.py", ("a1", "qa")),
}


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("defs-shell")
    proj, home = tmp / "proj", tmp / "home"
    for d in ("src", ".claude/hooks", "scripts", "build"):
        (proj / d).mkdir(parents=True)
    (proj / ".claude/settings.json").write_text("{}\n")
    for d in (home / ".claude", tmp / "state", tmp / "tmp"):
        d.mkdir(parents=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude"), "CLAUDE_STATE_DIR": str(tmp / "state"),
           "TMPDIR": str(tmp / "tmp"), "CLAUDE_PROJECT_DIR": str(proj),
           "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}

    seen = {}

    def run(key: str, template: str) -> int:
        if (key, template) in seen:
            return seen[key, template]
        hook, base, agent = BASE[key]
        payload = {"session_id": "sess-" + uuid.uuid4().hex[:8], "transcript_path": str(tmp / "none.jsonl"),
                   "cwd": str(proj), "hook_event_name": "PreToolUse", "permission_mode": "default",
                   "tool_name": "Bash", "tool_input": {"command": template.replace("{}", base)},
                   "tool_use_id": "toolu_" + uuid.uuid4().hex[:24]}
        if agent:
            payload.update(agent_id=agent[0], agent_type=agent[1], subagent_type=agent[1])
        interp = [sys.executable] if hook.endswith(".py") else ["bash"]
        proc = subprocess.run(interp + [str(HOOKS / hook)], input=json.dumps(payload), text=True,
                              capture_output=True, cwd=str(proj), env=env, timeout=120)
        seen[key, template] = proc.returncode
        return proc.returncode

    return run


# (family, template, the hooks that must refuse it as they refuse the bare command)
CASES = [
    # the git classifier reads the shared parser's split (shell_parse.git_invocations)
    ("shell-splitting", "find . -maxdepth 0 -exec {} ';'", ("gp", "tp")),
    ("shell-splitting", "env -S '{}'", ("gp", "tp")),
    ("env-split-string-option", "env --split-string='{}'", ("gp", "bs", "tp")),
    ("su-command-option", "su -c '{}'", ("gp", "bs", "tp")),
    ("su-command-option", "runuser -c '{}'", ("gp", "bs", "tp")),
    # the removal analyzer reads the attached spelling from the same COMMAND_OPTS
    ("su-command-option", "su --command='{}'", ("gp", "bs", "tp")),
    ("su-command-option", "runuser --command='{}'", ("bs",)),
    ("xargs-value-options", "xargs -i {} < /dev/null", ("gp", "tp")),
    ("xargs-value-options", "xargs -e {} < /dev/null", ("gp", "tp")),
    ("xargs-value-options", "xargs -l {} < /dev/null", ("gp", "tp")),
    ("xargs-value-options", "xargs --process-slot-var V {} < /dev/null", ("gp", "tp")),
    # one XARGS_SPEC: --replace and --max-lines take a value only when attached
    ("xargs-value-options", "xargs --replace {} < /dev/null", ("gp", "bs", "tp")),
    ("xargs-value-options", "xargs --max-lines {} < /dev/null", ("gp", "bs", "tp")),
    # shell_parse.PEEL names the programs that only run the command after their options
    ("exec-wrappers", "watch {}", ("gp", "bs", "tp")),
    ("exec-wrappers", "faketime now {}", ("gp", "bs", "tp")),
    ("exec-wrappers", "pkexec {}", ("gp", "bs", "tp")),
    ("exec-wrappers", "proxychains {}", ("gp", "bs", "tp")),
    ("exec-wrappers", "torsocks {}", ("gp", "bs", "tp")),
    ("exec-wrappers", "trickle {}", ("gp", "bs", "tp")),
    ("exec-wrappers", "cpulimit -l 5 {}", ("gp", "bs", "tp")),
    ("exec-wrappers", "tsp {}", ("gp", "bs", "tp")),
    ("exec-wrappers", "ssh-agent {}", ("gp", "bs", "tp")),
    # one option spec per wrapper (shell_parse), read by the runtime guard too
    ("wrapper-option-specs", "systemd-run --on-startup V {}", ("gp", "bs", "tp")),
    ("wrapper-option-specs", "systemd-run -H V {}", ("gp", "bs", "tp")),
    ("wrapper-option-specs", "sudo -U V {}", ("gp", "bs", "tp")),
    ("privilege-wrappers", "runuser -u root -- {}", ("gp", "bs", "tp")),
    # the git classifier's hidden-code reading knows the interpreters its _INTERPRETERS knows
    ("interpreters", "php -r 'system(\"{}\");'", ("gp", "bs")),
    ("interpreters", "lua -e 'os.execute(\"{}\")'", ("gp", "bs")),
    ("interpreters", "Rscript -e 'system(\"{}\")'", ("gp", "bs")),
    ("exec-env-variables", "GIT_PAGER='{}' git -p log", ("gp", "bs", "ui")),
    ("exec-env-variables", "PAGER='{}' man ls", ("gp", "bs", "ui")),
    ("shell-state-builtins", "trap '{}' EXIT", ("gp", "bs", "tp")),
    ("shell-state-builtins", "function f { {}; }; f", ("gp", "bs", "tp")),
    # write_targets walks into an alias's body as walk does
    ("shell-state-builtins", "alias g='{}'; g", ("gp", "bs", "tp")),
]


@pytest.mark.parametrize("family,template,hooks", CASES, ids=[f"{c[0]}:{c[1]}" for c in CASES])
def test_consumers_refuse_behind_the_shape(box, family, template, hooks):
    bare = {k: box(k, "{}") for k in hooks}
    assert bare == {k: 2 for k in hooks}, f"a hook does not refuse its bare command: {bare}"
    got = {k: box(k, template) for k in hooks}
    assert got == {k: 2 for k in hooks}, f"{family}: {template!r}: {got}"
