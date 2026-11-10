"""`gh pr checkout` and its detach option, as pretool-block-branch-pr-worktree.py reads it.

`gh pr checkout` creates a local branch for the pull request unless it is told to
detach (`--detach`) or gh stops before it runs. The option table comes from
`gh pr checkout --help` (gh 2.89) and gh's flag parser, spf13/pflag, measured on
that gh with no credentials (a parsed command reaches the login message, a
rejected one prints the parse error and does nothing):

  * `--detach` is a long-only boolean; it has no short form, so `-d` is an
    unknown shorthand and gh exits without checking anything out;
  * pflag accepts no abbreviation of a long option (`--det`, `--bran`);
  * a boolean takes a value only as `--detach=<bool>` (strconv.ParseBool), and
    the last one given wins; `-b`/`--branch` and `-R`/`--repo` take a value, the
    next word whatever it looks like.

Run with: python3 -m pytest hooks/tests/test_block_branch_pr_worktree_gh_checkout.py
"""

import json
import os
import subprocess
import sys

import pytest

HOOK = os.path.join(
    os.path.dirname(__file__), '..', 'pretool-block-branch-pr-worktree.py')


def _rc(cmd, tmp_path, **extra):
    env = dict(os.environ)
    env.pop('CLAUDE_TASK_ID', None)
    env.pop('CLAUDE_SESSION_ID', None)
    env['CLAUDE_PROJECT_DIR'] = str(tmp_path)
    env['CLAUDE_STATE_DIR'] = str(tmp_path / 'state')
    payload = {'tool_name': 'Bash', 'tool_input': {'command': cmd}}
    payload.update(extra)
    proc = subprocess.run(
        [sys.executable, HOOK], input=json.dumps(payload),
        capture_output=True, text=True, cwd=str(tmp_path), env=env)
    return proc.returncode


# gh detaches, or stops before it checks anything out: no branch is created.
NOTHING_CREATED = [
    'gh pr checkout 19 --detach',
    'gh pr checkout --detach 19',
    'gh pr checkout 19 --detach=true',       # attached value of the boolean
    'gh pr checkout 19 --detach=T',
    'gh pr checkout 19 --detach=1',
    'gh pr checkout 19 --detach=false --detach',    # the last one wins
    'gh pr checkout 19 -f --detach',
    'gh pr checkout 19 -b topic --detach',
    'gh pr checkout 19 -R o/r --detach',
    'gh -R o/r pr checkout 19 --detach',
    'gh pr -R o/r checkout 19 --detach',
    # No short form: gh prints "unknown shorthand flag: 'd'" and stops.
    'gh pr checkout 19 -d',
    'gh pr checkout -d 19',
    'gh pr checkout 19 -df',                 # clustered
    'gh pr checkout 19 -fd',
    'gh pr checkout 19 -d=true',             # attached
    'gh pr checkout 19 -dtrue',
    # No abbreviation of a long option: gh prints "unknown flag" and stops.
    'gh pr checkout 19 --det',
    'gh pr checkout 19 --d',
    'gh pr checkout 19 --bran x',
    'gh pr checkout 19 --no-detach',
    # Other parse failures and help.
    'gh pr checkout 19 --detach=maybe',
    'gh pr checkout 19 -f=zz',
    'gh pr checkout 19 --bogus',
    'gh pr checkout 19 20',                  # at most one argument
    'gh pr checkout 19 -b',                  # -b needs its value
    'gh pr checkout -h',
    'gh pr checkout --help',
]

# gh parses the command and checks the pull request out on a new local branch.
STILL_CREATES = [
    'gh pr checkout 19',
    'gh pr checkout',
    'gh pr checkout 19 --detach=false',
    'gh pr checkout 19 --detach=F',
    'gh pr checkout 19 --detach --detach=false',    # the last one wins
    'gh pr checkout 19 --detach=true --detach=0',
    'gh pr checkout 19 -f',
    'gh pr checkout 19 --force',
    'gh pr checkout 19 --recurse-submodules',
    'gh pr checkout 19 -b topic',
    'gh pr checkout 19 -btopic',
    'gh pr checkout 19 -fbtopic',            # clustered, attached value
    'gh pr checkout 19 -fb topic',
    'gh pr checkout 19 --branch topic',
    'gh pr checkout 19 --branch=topic',
    'gh pr checkout 19 -R o/r',
    'gh pr checkout 19 -Ro/r',
    'gh pr checkout 19 --repo o/r',
    'gh pr checkout 19 --repo=o/r',
    'gh pr checkout -- --detach',            # after `--` it is the argument
    'gh pr checkout -b --detach 19',         # the value of -b
    'gh pr checkout --branch --detach 19',
    'gh pr checkout 19 -f=true',
    'gh pr checkout 19 --help=false',
    'gh pr checkout 19 --help --help=false',    # the last one wins
    'gh -R o/r pr checkout 19',
    'gh pr -R o/r checkout 19',
    '/usr/bin/gh pr checkout 19',
    'true && gh pr checkout 19',
    'sudo gh pr checkout 19',
]


@pytest.mark.parametrize('cmd', NOTHING_CREATED)
def test_a_checkout_that_creates_no_branch_passes(cmd, tmp_path):
    assert _rc(cmd, tmp_path) == 0, cmd


@pytest.mark.parametrize('cmd', STILL_CREATES)
def test_a_checkout_that_creates_a_branch_is_refused(cmd, tmp_path):
    assert _rc(cmd, tmp_path) == 2, cmd


@pytest.mark.parametrize('cmd', ['gh pr checkout 19', 'gh pr checkout 19 --detach=false'])
def test_a_subagent_is_refused_the_same_way(cmd, tmp_path):
    assert _rc(cmd, tmp_path, agent_id='sub-1', session_id='s') == 2


@pytest.mark.parametrize('cmd', ['gh pr checkout 19 -d', 'gh pr checkout 19 --detach=true'])
def test_a_subagent_passes_a_checkout_that_creates_nothing(cmd, tmp_path):
    assert _rc(cmd, tmp_path, agent_id='sub-1', session_id='s') == 0
