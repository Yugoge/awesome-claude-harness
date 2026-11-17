"""The git-privilege guard refuses a fetch or pull that writes refs/checkpoints/.

The auto-commit mechanism snapshots work to `refs/checkpoints/<branch>` (see
docs/reference/checkpoint-mechanism.md). `git fetch origin
refs/checkpoints/master:refs/checkpoints/master` overwrites that local snapshot
ref, and the guard did not read where a fetch writes (audit GIT-M3). A refspec
whose destination is under refs/checkpoints/ is now refused wherever the
command carries it: an operand, `--refmap`, a `-c`/`--config-env`/GIT_CONFIG_*
`remote.<name>.fetch` value, or `--stdin` text from a pipe, here-doc or
here-string. A fetch that only reads a checkpoint ref (no destination, or a
destination elsewhere) still passes.

The guard runs as a subprocess with a scratch HOME, state dir and repository,
once as the main agent and once as a subagent.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
GUARD = HOOKS / "pretool-git-privilege-guard.py"
SID = "checkpoint-fetch-0001"
CKPT_DENY = "BLOCKED: agent git checkpoint ref write"

AGENTS = {"main": {}, "subagent": {"agent_id": "agent-1", "agent_type": "general-purpose"}}

REFUSED = [
    # the audit's case and its plain variants
    "git fetch origin refs/checkpoints/master:refs/checkpoints/master",
    "git fetch origin +refs/checkpoints/*:refs/checkpoints/*",
    "git fetch origin '+refs/checkpoints/*:refs/checkpoints/*'",
    "git fetch origin master:refs/checkpoints/master",
    "git fetch . HEAD:refs/checkpoints/x",
    "git fetch origin master refs/heads/a:refs/checkpoints/a",
    # quoted or escaped spellings of the refspec and of `fetch`
    "git fetch origin 'refs/checkpoints/master:refs/checkpoints/master'",
    'git fetch origin "master:refs/checkpoints/master"',
    'git fetch origin master:"refs/"checkpoints/master',
    "git fetch origin master:refs/check\\points/master",
    "git fetch origin $'master:refs/\\x63heckpoints/master'",
    "git 'fetch' origin master:refs/checkpoints/master",
    'git "fe"tch origin master:refs/checkpoints/master',
    "git f\\etch origin master:refs/checkpoints/master",
    # spellings of the namespace: what git writes there, and what it rejects
    "git fetch . HEAD:refs//checkpoints/x",
    "git fetch . HEAD:refs/checkpoints/",
    "git fetch . HEAD:refs/checkpoints",              # a ref that blocks every snapshot
    "git fetch . HEAD:refs/Checkpoints/x",            # one directory on a case-blind disk
    "git fetch . HEAD:REFS/CHECKPOINTS/x",
    "git fetch . HEAD:refs/checkpoints/../checkpoints/x",
    "git fetch . HEAD:refs/./checkpoints/x",
    "git fetch . HEAD:refs/heads/../checkpoints/x",
    # glob destinations that reach the namespace
    "git fetch origin +refs/*:refs/*",
    "git fetch origin refs/heads/*:refs/check*",
    "git fetch origin 'refs/heads/*:refs/c*'",
    # --refmap, with and without command-line refspecs
    "git fetch origin --refmap=+refs/heads/*:refs/checkpoints/*",
    "git fetch origin master --refmap=+refs/heads/*:refs/checkpoints/*",
    "git fetch origin master --refmap '+refs/heads/*:refs/checkpoints/*'",
    # configuration that adds a fetch refspec
    "git -c remote.origin.fetch=+refs/checkpoints/*:refs/checkpoints/* fetch origin",
    "git -c 'remote.origin.fetch=+refs/checkpoints/*:refs/checkpoints/*' fetch origin",
    "git -c Remote.Origin.Fetch=+refs/heads/*:refs/checkpoints/* fetch origin master",
    "git --config-env=remote.origin.fetch=SPEC fetch origin",   # value unseen
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=remote.origin.fetch "
    "GIT_CONFIG_VALUE_0=+refs/checkpoints/*:refs/checkpoints/* git fetch origin",
    "export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=remote.origin.fetch "
    "GIT_CONFIG_VALUE_0=+refs/checkpoints/*:refs/checkpoints/*; git fetch origin",
    "GIT_CONFIG_PARAMETERS=\"'remote.origin.fetch'='+refs/checkpoints/*:refs/checkpoints/*'\" "
    "git fetch origin",
    # refspecs read from stdin
    "echo refs/checkpoints/master:refs/checkpoints/master | git fetch --stdin origin",
    "echo '+refs/checkpoints/master:refs/checkpoints/master' | git fetch --stdin origin",
    "printf 'main:x\\nmaster:refs/checkpoints/master\\n' | git fetch --stdin origin",
    "git fetch --stdin origin <<'EOF'\n+refs/checkpoints/*:refs/checkpoints/*\nEOF",
    "git fetch --stdin origin <<< 'master:refs/checkpoints/master'",
    # pull, prune, nested and aliased forms
    "git pull origin x:refs/checkpoints/x",
    "git fetch --prune origin +refs/checkpoints/*:refs/checkpoints/*",
    "git fetch --prune-tags --prune origin +refs/heads/*:refs/checkpoints/*",
    "bash -c 'git fetch origin master:refs/checkpoints/master'",
    "git -C . fetch origin master:refs/checkpoints/master",
    "git -c alias.f=fetch f origin master:refs/checkpoints/master",
    'git fetch origin "master:refs/checkpoints/$B"',   # a computed tail
    "git fetch origin master:refs/checkpoints/master || true",
    # brace alternatives and parameter defaults the shell expands (verifier round 1)
    "git fetch origin master:refs/checkpoint{s,}/master",
    "git fetch origin master:refs/{checkpoints,x}/master",
    "git fetch origin --refmap=+refs/heads/*:refs/{checkpoints,x}/*",
    "git -c remote.origin.fetch=+refs/heads/*:refs/{checkpoints,x}/* fetch origin",
    "git fetch origin master:${D:-refs/checkpoints/x}",
    "git fetch origin master:${D-refs/checkpoints/x}",
    "git fetch origin master:${D:=refs/checkpoints/x}",
    "git fetch origin master:${D=refs/checkpoints/x}",
    "git fetch origin master:refs/{x,{y,checkpoints}}/master",
    # sequence braces, a brace cap, nested defaults and a destination that
    # stays unresolved (verifier round 2): refused, not guessed
    "git fetch origin master:refs/checkpoint{s..s}/m",
    "git fetch origin master:refs/checkpoint{r..t}/m",
    "git fetch origin master:refs/checkpoint{s,}{,}{,}{,}{,}{,}{,}{,}{,}/m",
    "git fetch origin master:${D:-${E:-refs/checkpoints/x}}",
    'git fetch origin "master:$DST"',
    "git fetch origin master:refs/$NS/x",
    "git fetch origin master:refs/$(echo checkpoints)/x",
    "git fetch origin --refmap \"+refs/heads/*:$MAP\" master",
    "git -c \"remote.origin.fetch=+refs/heads/*:$MAP\" fetch origin",
    # an abbreviation git takes for --refmap (verifier round 3)
    'git fetch --refm="refs/heads/*:$D/*" origin master',
    "git fetch --refm 'refs/heads/*:$D/*' origin master",
    "git fetch --refma=+refs/heads/*:refs/checkpoints/* origin master",
    "git fetch origin master --refm +refs/heads/*:refs/checkpoints/*",
]

PASSES = [
    "git fetch origin",
    "git fetch origin master",
    "git fetch origin master:refs/remotes/origin/master",
    "git fetch origin refs/checkpoints/master",        # writes FETCH_HEAD only
    "git fetch origin refs/checkpoints/master:refs/remotes/origin/checkpoints/master",
    "git fetch origin '+refs/checkpoints/*:refs/remotes/origin/checkpoints/*'",
    "git fetch --all",
    "git fetch --prune origin",
    "git fetch origin +refs/heads/*:refs/remotes/origin/*",
    "git fetch . HEAD:checkpoints/x",                  # git writes refs/heads/checkpoints/x
    "git log refs/checkpoints/master",
    "git show refs/checkpoints/master:README.md",
    # the audit's GIT-7 inputs: they write no checkpoint ref
    "echo main:newbranch | git fetch --stdin origin",
    "git -c remote.origin.fetch=+refs/heads/*:refs/heads/* fetch origin",
    "git fetch origin master:refs/remotes/{origin,up}/master",
    "git fetch origin master:${D:-refs/remotes/origin/master}",
    "git fetch origin master:refs/remotes/origin/b{1..3}",
    'git fetch "$REMOTE" master',                      # a computed repository
    'git fetch "https://$HOST/repo.git" master:refs/remotes/h/master',
    'git fetch origin "$BRANCH"',                      # no destination written
    "git fetch --multiple origin upstream",
]


class Box:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.state = tmp_path / "state"
        self.repo = tmp_path / "toyproj"
        home = tmp_path / "home"
        for d in (self.state, self.repo, home):
            d.mkdir()
        (home / "gitconfig").write_text("")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
        self.env.update(HOME=str(home), CLAUDE_STATE_DIR=str(self.state),
                        CLAUDE_PROJECT_DIR=str(self.repo), PYTHONDONTWRITEBYTECODE="1",
                        GIT_CONFIG_GLOBAL=str(home / "gitconfig"), GIT_CONFIG_NOSYSTEM="1",
                        GIT_CEILING_DIRECTORIES=str(tmp_path))
        subprocess.run(["git", "init", "-q", "-b", "master", str(self.repo)], check=True,
                       capture_output=True, env=self.env)

    def grant(self, target: str) -> Path:
        code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                "from lib.allowlist import write_sentinel_grant; "
                "print(write_sentinel_grant(sys.argv[2], sys.argv[2], "
                "[{'op': 'git', 'target': sys.argv[3]}]))")
        out = subprocess.run([sys.executable, "-B", "-c", code, str(HOOKS), SID, target],
                             check=True, capture_output=True, text=True, env=self.env,
                             cwd=str(self.tmp))
        return Path(out.stdout.strip())

    def run(self, command: str, **payload):
        data = {"session_id": SID, "tool_name": "Bash", "tool_input": {"command": command},
                "cwd": str(self.repo), "hook_event_name": "PreToolUse", **payload}
        return subprocess.run([sys.executable, "-B", str(GUARD)], input=json.dumps(data),
                              text=True, capture_output=True, cwd=str(self.repo), env=self.env,
                              timeout=120)


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


@pytest.mark.parametrize("who", sorted(AGENTS))
@pytest.mark.parametrize("command", REFUSED)
def test_a_fetch_that_writes_a_checkpoint_ref_is_refused(box, command, who):
    proc = box.run(command, **AGENTS[who])
    assert proc.returncode == 2, (command, who, proc.stderr)
    assert "BLOCKED" in proc.stderr, (command, who, proc.stderr)
    if not command.startswith("git pull"):   # pull meets the plumbing rule first
        assert CKPT_DENY in proc.stderr, (command, who, proc.stderr)


@pytest.mark.parametrize("who", sorted(AGENTS))
@pytest.mark.parametrize("command", PASSES)
def test_a_fetch_that_writes_no_checkpoint_ref_passes(box, command, who):
    proc = box.run(command, **AGENTS[who])
    assert proc.returncode == 0, (command, who, proc.stderr)


def test_the_refusal_names_a_destination_that_passes(box):
    proc = box.run("git fetch origin refs/checkpoints/master:refs/checkpoints/master")
    assert "refs/remotes/" in proc.stderr, proc.stderr


@pytest.mark.parametrize("who", sorted(AGENTS))
def test_an_allow_grant_lifts_the_refusal_once(box, who):
    box.grant("fetch")
    command = "git fetch origin master:refs/checkpoints/master"
    proc = box.run(command, **AGENTS[who])
    assert proc.returncode == 0, proc.stderr
