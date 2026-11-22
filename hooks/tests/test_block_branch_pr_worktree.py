"""Unit tests for hooks/pretool-block-branch-pr-worktree.py.

The hook refuses worktree CREATION on the Bash surface, with three bypasses (in
order): a live /dev-overnight session, /do consent (main agent), and a /allow
grant. Branch and PR creation are allowed. The EnterWorktree tool is governed by a separate hook
(pretool-block-enterworktree.sh) and is intentionally ignored here.

Tests invoke the hook as a subprocess (the way the harness does) and assert the
exit code: 0 = allow, 2 = block.

Run with: python3 -m pytest hooks/tests/test_block_branch_pr_worktree.py -v
"""

import json
import os
import subprocess
import sys

import pytest

HOOK = os.path.join(
    os.path.dirname(__file__), '..', 'pretool-block-branch-pr-worktree.py')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.harness_state_dir import harness_state_dir  # noqa: E402


def _run(payload, project_dir, env_extra=None):
    """Run the hook with payload on stdin.

    project_dir is pinned as both cwd and CLAUDE_PROJECT_DIR (a non-git tmp dir)
    so overnight detection is deterministic. CLAUDE_TASK_ID / CLAUDE_SESSION_ID
    are stripped so an inherited sentinel/consent from the live session can never
    leak a bypass into the block-path tests; env_extra is applied last.
    """
    env = dict(os.environ)
    env.pop('CLAUDE_TASK_ID', None)
    env.pop('CLAUDE_SESSION_ID', None)
    env['CLAUDE_PROJECT_DIR'] = str(project_dir)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps(payload),
        capture_output=True, text=True, cwd=str(project_dir), env=env,
    )
    return proc.returncode, proc.stderr


def _bash(cmd, **extra):
    p = {'tool_name': 'Bash', 'tool_input': {'command': cmd}}
    p.update(extra)
    return p


# ── Allowed: branch creation (incl. attached / path-qualified / clustered) ───

@pytest.mark.parametrize('cmd', [
    'git checkout -b feature/x',
    'git checkout -B feature/x',
    'git checkout --orphan gh-pages',
    'git checkout --orphan=gh-pages',
    'git checkout -bfeature',            # attached short-opt value
    'git switch -c feature/x',
    'git switch -C feature/x',
    'git switch --create feature/x',
    'git switch --create=feature',       # attached long-opt value
    'git switch --force-create feature/x',
    'git switch --orphan=feat',
    'git switch -cfeature',              # attached short-opt value
    'git branch new-feature',
    'git branch new-feature origin/master',
    'git branch -c old new',             # copy creates a branch
    'git branch -f forced start',        # force create/reset
    'git -C /some/repo branch newbr',    # git global-option prefix
    '/usr/bin/git checkout -b bypass',   # path-qualified git
    'true && git checkout -b chained',
    'sudo git checkout -b withsudo',
    'git branch -v newbranch HEAD',      # -v is display, not a veto
    'git branch -vv newbranch',          # -vv display cluster
    'git branch --verbose newbranch',
    'git branch --no-color nb HEAD',
    'git branch --sort=refname nb HEAD',
    'git branch --format=%(refname) nb',
    'git branch --abbrev=7 nb',
    'git branch --format %(refname) nb',  # space value THEN positional name
    'git branch --color always',
    'git branch --column always',
    'git branch --abbrev 7',
    'git branch --color always extra',    # two positionals after boolean flag
    'git checkout -t origin/foo',
    'git checkout --track origin/foo',
    'git switch -t origin/foo',
    'git switch --track origin/foo',
    'git switch --guess remotebranch',
    'git switch --cr foo',               # --cr -> --create
    'git checkout --or foo',             # --or -> --orphan
    'git checkout --tr origin/x',        # --tr -> --track
    'git switch --g foo',                # --g  -> --guess
    'git switch --force-c foo',          # --force-c -> --force-create
    'git stash branch foo',
    'git fetch . HEAD:refs/heads/foo',
    'git pull origin x:refs/heads/foo',
    'git fetch origin main:newbranch',
    'git fetch . HEAD:newbranch',
    'git fetch origin main:heads/nb',
    'git fetch origin main:foo/bar',
    'git pull origin main:topic',
    'git pull . HEAD:newbranch',
    'git fetch origin +main:newbranch',  # leading '+' force marker stripped
    'git update-ref refs/heads/foo HEAD',
    'echo $(git checkout -b foo)',
    'x=$(git switch -c foo)',
    'git checkout --guess ro_branch',
    'git checkout --g ro_branch',        # --g -> --guess (unique prefix)
    'sudo git checkout -b x',
    'FOO=bar git checkout -b x',
    '/usr/bin/git checkout -b x',
    'git -C /repo branch new',           # git global option, git is command tok
])
def test_branch_creation_allowed(cmd, tmp_path):
    rc, _ = _run(_bash(cmd), tmp_path)
    assert rc == 0, f'expected allow for: {cmd}'


def test_backtick_substitution_inner_creation_allowed(tmp_path):
    cmd = 'result=`git checkout -b foo`'
    rc, _ = _run(_bash(cmd), tmp_path)
    assert rc == 0, f'expected allow for: {cmd}'


# ── Blocked: worktree creation ───────────────────────────────────────────────

@pytest.mark.parametrize('cmd', [
    'git worktree add ../wt feature',
    '/usr/bin/git worktree add ../wt HEAD',
    'git worktree add -b br ../wt HEAD',
])
def test_worktree_creation_blocked(cmd, tmp_path):
    rc, _ = _run(_bash(cmd), tmp_path)
    assert rc == 2, f'expected block for: {cmd}'


# ── Allowed: PR creation (incl. interspersed gh flags) ───────────────────────

@pytest.mark.parametrize('cmd', [
    'gh pr create --fill',
    'gh pr create --title x --body y',
    'gh -R cli/cli pr create --fill',    # global flag before pr
    'gh pr -R cli/cli create --fill',    # global flag between pr and create
    '/usr/bin/gh pr create --fill',      # path-qualified gh
    'gh pr new --fill',
    'gh -R o/r pr new',                  # global flag before pr, `new` alias
    'gh pr checkout 12',
    'gh -R cli/cli pr checkout 12',
    'gh api repos/o/r/pulls -f title=x -f head=f -f base=main',
    'gh api -X POST repos/o/r/pulls -f title=x',
    'gh api --method POST repos/o/r/pulls',
])
def test_pr_creation_allowed(cmd, tmp_path):
    rc, _ = _run(_bash(cmd), tmp_path)
    assert rc == 0, f'expected allow for: {cmd}'


# ── Allowed: non-creation git/gh forms ───────────────────────────────────────

@pytest.mark.parametrize('cmd', [
    'git branch',                      # list
    'git branch -a',
    'git branch -r',
    'git branch -v',
    'git branch -rl "*"',              # clustered short flags (list remotes)
    'git branch -avv',                 # clustered short flags
    'git branch --list "feat/*"',
    'git branch --show-current',
    'git branch --contains HEAD',      # value-flag, not creation
    'git branch -d old-feature',       # delete
    'git branch -D old-feature',
    'git branch -m old new',           # rename
    'git branch -u origin/x',          # set upstream (-u veto, value not a name)
    'git branch --merged',
    'git branch -vv',                  # verbose list, no positional
    'git branch --sort=refname',       # no positional
    "git branch --format='%(refname)'",  # attached value, no positional
    'git branch --format %(refname)',  # space value, no positional
    'git branch --points-at HEAD',     # query, value not a positional
    'git branch --merged main',        # query, value not a positional
    'git branch --color',              # bare boolean flag, no positional
    'git branch --color=always',       # attached value, single token
    'git branch --column=always',      # attached value, single token
    'git branch --abbrev=7',           # attached value, single token
    'git branch --sort refname',       # required-value flag swallows the value
    'git branch --sort=refname',       # attached value, no positional
    'git worktree list',
    'git worktree remove ../wt',
    'git worktree prune',
    'git status',
    'git switch master',               # switch to existing, no -c
    'git checkout master',             # checkout existing, no -b
    'git checkout -- -b',              # pathspec literally named -b
    'gh pr list',
    'gh pr view 12',
    'gh pr view 3',
    'gh pr status',
    'gh pr diff 7',
    'gh pr checkout --detach 12',       # detached HEAD: no branch ref → allow
    'git switch --detach',
    'git switch --force',
    'git switch --no-track',
    'git checkout --force',
    'git checkout --ours x',
    'git checkout --theirs x',
    'git stash',
    'git stash list',
    'git stash pop',
    'git fetch',
    'git fetch origin',
    'git fetch --all',
    'git pull origin main',
    'git fetch origin main',             # space-separated src, no refspec colon
    'git fetch origin main:refs/remotes/foo',  # remote-tracking, not local
    'git fetch origin main:refs/tags/v1',      # tag, not a local branch
    'git fetch origin main:',                  # empty dst → FETCH_HEAD only
    'git fetch https://host/repo.git',         # URL, not a refspec
    'git fetch ssh://host/repo',               # URL, not a refspec
    'git fetch git@github.com:o/r.git',        # scp-like remote, not a refspec
    'git clone git@github.com:o/r.git',        # clone is not fetch/pull anyway
    'git fetch --dry-run origin main:newbranch',  # dry-run writes nothing
    'git update-ref -d refs/heads/foo',
    'echo $(git status)',
    'git log --format %(refname)',
    'git branch --format %(refname)',
    'echo gh pr new',
    'echo git checkout -b x',
    'git stash -- branch',
    'git fetch --dry-run . HEAD:refs/heads/d',
    'git pull --dry-run origin x:refs/heads/d',
    'git update-ref -m refs/heads/msg refs/tags/v1 HEAD',
    'git checkout somebranch',
    'git switch somebranch',
    'gh api repos/o/r/pulls',
    'gh api -X GET repos/o/r/pulls',
    'gh api --method GET repos/o/r/pulls -f x=y',  # explicit GET overrides field
])
def test_non_creation_forms_allowed(cmd, tmp_path):
    rc, _ = _run(_bash(cmd), tmp_path)
    assert rc == 0, f'expected allow for: {cmd}'


def test_quoted_branch_text_not_matched(tmp_path):
    # `git checkout -b foo` inside a quoted echo arg is non-executable -> allowed.
    rc, _ = _run(_bash('echo "to create run: git checkout -b foo"'), tmp_path)
    assert rc == 0


# ── Scope: this hook is Bash-only ────────────────────────────────────────────

def test_enterworktree_tool_ignored_by_this_hook(tmp_path):
    # EnterWorktree is governed by pretool-block-enterworktree.sh, not this hook.
    rc, _ = _run({'tool_name': 'EnterWorktree', 'tool_input': {'name': 'wt'}},
                 tmp_path)
    assert rc == 0


def test_non_bash_tool_ignored(tmp_path):
    rc, _ = _run({'tool_name': 'Read', 'tool_input': {'file_path': '/x'}},
                 tmp_path)
    assert rc == 0


def test_empty_command_allowed(tmp_path):
    rc, _ = _run(_bash(''), tmp_path)
    assert rc == 0


def test_malformed_stdin_fails_open(tmp_path):
    env = dict(os.environ)
    env['CLAUDE_PROJECT_DIR'] = str(tmp_path)
    proc = subprocess.run(
        [sys.executable, HOOK], input='not json',
        capture_output=True, text=True, cwd=str(tmp_path), env=env)
    assert proc.returncode == 0


# ── Bypass 1: live /dev-overnight session (any session) ──────────────────────

def _write_overnight_state(project_dir, live=True):
    claude = project_dir / '.claude'
    claude.mkdir(parents=True, exist_ok=True)
    end = '2099-01-01T00:00:00Z' if live else '2000-01-01T00:00:00Z'
    state = {
        'current_phase': 'exploring' if live else 'complete',
        'end_time': end,
        'session_id': 'overnight-sess',
    }
    (claude / 'overnight-state-overnight-sess.json').write_text(json.dumps(state))


@pytest.mark.parametrize('cmd', [
    'git checkout -b feature/x',
    'git worktree add ../wt feature',
    'gh pr create --fill',
    'git branch new-feature',
])
def test_creation_allowed_during_live_overnight(cmd, tmp_path):
    _write_overnight_state(tmp_path, live=True)
    rc, _ = _run(_bash(cmd), tmp_path)
    assert rc == 0, f'expected allow during live overnight for: {cmd}'


@pytest.mark.parametrize('cmd, rc_expected', [
    ('git checkout -b feature/x', 0),
    ('git worktree add ../wt feature', 2),
])
def test_creation_when_overnight_completed(cmd, rc_expected, tmp_path):
    # A completed/expired overnight state is NOT a live session.
    _write_overnight_state(tmp_path, live=False)
    rc, _ = _run(_bash(cmd), tmp_path)
    assert rc == rc_expected


# ── Bypass 2: /do consent (main agent only) ──────────────────────────────────

@pytest.mark.parametrize('cmd', ['git checkout -b feature/x', 'git worktree add ../wt'])
def test_do_consent_allows_main_agent(cmd, tmp_path):
    sid = f'test-do-{os.getpid()}'
    flag = os.path.join(harness_state_dir(), f'claude-orchestrator-consent-{sid}.flag')
    with open(flag, 'w') as fh:
        fh.write('true')
    try:
        rc, _ = _run(_bash(cmd, session_id=sid), tmp_path)
        assert rc == 0
    finally:
        os.unlink(flag)


@pytest.mark.parametrize('cmd, rc_expected', [
    ('git checkout -b feature/x', 0),
    ('git worktree add ../wt', 2),
])
def test_do_consent_does_not_help_subagent(cmd, rc_expected, tmp_path):
    sid = f'test-do-sub-{os.getpid()}'
    flag = os.path.join(harness_state_dir(), f'claude-orchestrator-consent-{sid}.flag')
    with open(flag, 'w') as fh:
        fh.write('true')
    try:
        payload = _bash(cmd, session_id=sid, agent_id='sub-1')
        rc, _ = _run(payload, tmp_path)
        assert rc == rc_expected  # subagents never qualify for /do
    finally:
        os.unlink(flag)


def test_subagent_blocked_without_bypass(tmp_path):
    payload = _bash('git worktree add ../wt', session_id='whatever', agent_id='sub-9')
    rc, _ = _run(payload, tmp_path)
    assert rc == 2


# ── Bypass 3: /allow sentinel grant (reaches subagents) ──────────────────────

# Retired: test_allow_sentinel_grant_allows. The hook reads no /allow grant; the owner's /allow
# releases its refusal in the launcher (test_allow_releases_anything.py).


# ── Bash is the oracle: obfuscated words that are not git ───────────────────

NOT_GIT = [
    "gi'a b't worktree add ../w",        # one word: `gia bt`
    "g\\ \nit worktree add x",           # words `g ` then `it`
    "g\\#x\nit worktree add x",          # words `g#x` then `it`
]
IS_GIT = "gi\\\nt worktree add x"        # a line continuation joins `git`


def _bash_runs_git(cmd, tmp_path):
    """True when bash, given cmd, runs the stub `git` placed first on PATH."""
    stub = tmp_path / 'bin'
    stub.mkdir(exist_ok=True)
    marker = tmp_path / 'git-ran'
    (stub / 'git').write_text(f'#!/bin/sh\ntouch {marker}\n')
    (stub / 'git').chmod(0o755)
    env = dict(os.environ, PATH=f'{stub}:{os.environ.get("PATH", "")}')
    subprocess.run(['bash', '-c', cmd], cwd=str(tmp_path), env=env,
                   capture_output=True, timeout=30)
    return marker.exists()


@pytest.mark.parametrize('cmd', NOT_GIT)
def test_a_word_bash_does_not_read_as_git_is_not_git(cmd, tmp_path):
    from lib.shell_parse import git_invocations
    assert git_invocations(cmd) == [], cmd
    assert not _bash_runs_git(cmd, tmp_path), cmd
    rc, _ = _run(_bash(cmd), tmp_path)
    assert rc == 0, cmd


def test_the_oracle_sees_git_where_bash_runs_it(tmp_path):
    from lib.shell_parse import git_invocations
    assert [i.subcommand for i in git_invocations(IS_GIT)] == ['worktree']
    assert _bash_runs_git(IS_GIT, tmp_path)
    rc, _ = _run(_bash(IS_GIT), tmp_path)
    assert rc == 2


@pytest.mark.parametrize('cmd', [
    'env git worktree add ../w',
    'bash -c "git worktree add ../w"',
    'eval "git worktree add ../w"',
    'command git worktree add ../w',
    'echo $(git worktree add ../w)',
    'git -C x worktree add ../w',
])
def test_worktree_creation_through_a_wrapper_is_refused(cmd, tmp_path):
    for extra in ({}, {'agent_id': 'sub-1', 'session_id': 's'}):
        rc, _ = _run(_bash(cmd, **extra), tmp_path)
        assert rc == 2, (cmd, extra)
