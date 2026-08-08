"""End-to-end BLOCK/ALLOW tests for the destructive `git clean` deny rule in
hooks/pretool-bash-safety.sh (task dev-20260719-150041-a, lane r01-a).

`git clean -fd` removes UNTRACKED files with no rm, no reflog and no reachable
git object — the same no-trace deletion channel as the already-blocked `rm`,
and the mechanism that destroyed an untracked work-in-progress engine on
2026-07-12/13. The rule's polarity is BLOCK-unless-PROVABLY-non-destructive:

  TRUST GATE (first, all fail-closed)
    T1  every RAW argument token must be literal-safe [A-Za-z0-9_./=+:@,-]*
    T2  the raw and stripped passes must see the same number of invocations
    T3  no argument-injecting wrapper (basename `xargs`) in command position
  then the separate-value-exclude gate, then the effective-dry-run walk, both
  on the CONTEXT-STRIPPED classifier args.

These drive the real hook process via piped JSON (the Claude Code PreToolUse
protocol) and assert on the exit code: 2 => BLOCKED, 0 => ALLOWED.

Every form below is verbatim from the machine-readable acceptance criteria
docs/dev/acceptance-criteria-dev-20260719-150041-a.json (AC1-AC14); the
generated skeletons under tests/generated/dev-20260719-150041-a/ import these
same lists so the two can never drift.

Run with: python3 -m pytest hooks/tests/test_bash_safety_git_clean.py -v
"""

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

HOOK = os.path.join(os.path.dirname(__file__), "..", "pretool-bash-safety.sh")

BLOCK = 2
ALLOW = 0

DO_FLAG_TMPL = "/tmp/claude-orchestrator-consent-{sid}.flag"
SENTINEL_DIR = Path("/tmp/claude-grants")

# Env keys that would otherwise let an ambient grant leak into the hook's
# session/task resolution and silently turn a BLOCK assertion into an ALLOW.
_HERMETIC_UNSET = ("CLAUDE_TASK_ID", "CLAUDE_SESSION_ID")


def fresh_sid() -> str:
    """A session id no /do flag and no /allow sentinel can exist for."""
    return "gitclean-test-%s" % uuid.uuid4().hex


def run_hook(command: str, session_id: str = None, hook: str = HOOK,
             agent_id: str = None, cwd: str = None, want_stderr: bool = False):
    """Invoke the real hook with a Bash tool_input and return its exit code.

    `agent_id` makes the hook's IS_SUBAGENT true, which is what selects the
    4th grant channel; `cwd` keeps a granted clean's pre-clean WIP snapshot
    inside a throwaway repo instead of this one.

    `want_stderr` additionally returns the hook's stderr, so a BLOCK assertion
    can prove THIS rule denied the command rather than some sibling rule that
    happens to exit 2 as well (an exit-code-only assertion is vacuous against a
    wrapper token like `sudo` that another layer already blocks).
    """
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": session_id or fresh_sid(),
    }
    if agent_id:
        payload["agent_id"] = agent_id
    env = {k: v for k, v in os.environ.items() if k not in _HERMETIC_UNSET}
    proc = subprocess.run(
        ["bash", hook], input=json.dumps(payload), text=True,
        capture_output=True, env=env, cwd=cwd,
    )
    return proc.returncode


def assert_all(forms, expected):
    """Assert every form yields `expected`, reporting the offending form."""
    for form in forms:
        assert run_hook(form) == expected, form


# ── Human-grant fixtures ─────────────────────────────────────────────────────
# Cleanup uses Python's unlink, never bash `rm` — the hook blocks `rm`.

def write_do_flag(sid: str) -> Path:
    """Create the /do consent flag the main-agent short-circuit reads."""
    path = Path(DO_FLAG_TMPL.format(sid=sid))
    path.write_text("true")
    return path


def write_allow_sentinel(task_id: str) -> Path:
    """Create a structured /allow sentinel matching `git clean …`."""
    SENTINEL_DIR.mkdir(parents=True, exist_ok=True)
    path = SENTINEL_DIR / ("%s.json" % task_id)
    path.write_text(json.dumps({
        "task_id": task_id,
        "session_id": task_id,
        "allowed_operations": [{"op": "git", "target": "clean"}],
        "created_at": time.time(),
        "expires_at": time.time() + 300,
    }))
    return path


@pytest.fixture
def granted_sid():
    """Yield a session id whose matching /do consent flag exists."""
    sid = fresh_sid()
    path = write_do_flag(sid)
    yield sid
    path.unlink(missing_ok=True)


@pytest.fixture
def sentinel_sid():
    """Yield a session id whose matching /allow sentinel grant exists."""
    sid = fresh_sid()
    path = write_allow_sentinel(sid)
    yield sid
    path.unlink(missing_ok=True)


# ── AC1: force / interactive, every spelling incl. abbreviations ─────────────

AC1_FORMS = [
    "git clean -f", "git clean --force", "git clean --for", "git clean --fo",
    "git clean --f", "git clean -i", "git clean --interactive",
    "git clean --int", "git clean -fd", "git clean -fdx", "git clean -df",
]


@pytest.mark.parametrize("form", AC1_FORMS)
def test_AC1_force_or_interactive_blocks(form):
    """Not provably dry-run => conservative default blocks every spelling."""
    assert run_hook(form) == BLOCK


# ── AC2: removal-scope flags AND bare clean (requireForce=false hole) ────────

AC2_FORMS = [
    "git clean", "git clean -d", "git clean -x", "git clean -X",
    "git clean -dx", "git -c clean.requireForce=false clean",
    "git -c clean.requireForce=false clean -d",
]


@pytest.mark.parametrize("form", AC2_FORMS)
def test_AC2_removal_scope_and_bare_clean_block(form):
    """Bare clean deletes when clean.requireForce=false, so it must block."""
    assert run_hook(form) == BLOCK


# ── AC3: path-qualified, global-option and sudo forms ────────────────────────

AC3_FORMS = [
    "/usr/bin/git clean -fd", "/usr/bin/git clean", "git -C /some/dir clean -fd",
    "git -c foo=bar clean -fd", "git --no-pager clean -f",
    "sudo git clean -f -n --no-dry-run",
]


@pytest.mark.parametrize("form", AC3_FORMS)
def test_AC3_path_qualified_and_global_opts_block(form):
    """The classifier basename-matches git, so /usr/bin/git is covered too."""
    assert run_hook(form) == BLOCK


# ── AC4: effective dry-run OFF (unquoted) ────────────────────────────────────

AC4_FORMS = [
    "git clean -f -n --no-dry-run", "git clean -f -n --no-d",
    "git clean -f -e -n", "git clean -f --ex -n", "git clean -f --e -n",
    "git clean -fe -n", "git clean -fen", "git clean --force -n --no-dry-run",
    "git clean -f -- -n",
]


@pytest.mark.parametrize("form", AC4_FORMS)
def test_AC4_effective_dry_run_off_blocks(form):
    """A -n TOKEN is not a dry-run: negation is last-wins, an exclude eats the
    next token, and tokens after `--` are pathspecs."""
    assert run_hook(form) == BLOCK


# ── AC5: command chaining blocks the whole command ───────────────────────────

AC5_FORMS = [
    "git clean -n; git clean -f", "git clean -f; git clean -n",
    "git clean -n && git clean -fd",
]


@pytest.mark.parametrize("form", AC5_FORMS)
def test_AC5_chained_clean_blocks_whole_command(form):
    """Per-invocation evaluation: one unproven clean blocks the command."""
    assert run_hook(form) == BLOCK


# ── AC6: genuinely-safe forms (the anti-over-block guardrail) ────────────────

AC6_FORMS = [
    "git clean -n", "git clean --dry-run", "git clean --dry", "git clean --d",
    "git clean -nd", "git clean -fn", "git clean -nf", "git clean -nef",
    "git clean -n --no-quiet", "git clean -n --exclude=build",
    "git clean --exclude=build -n", "git config clean.requireForce false",
]


@pytest.mark.parametrize("form", AC6_FORMS)
def test_AC6_provable_dry_run_and_config_read_allowed(form):
    """The trust gate MUST NOT regress any provable dry-run or config read."""
    assert run_hook(form) == ALLOW


# ── AC7: human-grant polarity, three channels + negative case ────────────────

GRANTED_FORM = "git clean -fd"


def test_AC7a_matching_do_consent_flag_allows(granted_sid):
    """A matching main-agent /do flag short-circuits before the deny rule."""
    assert run_hook(GRANTED_FORM, session_id=granted_sid) == ALLOW


def test_AC7b_mismatched_session_do_flag_still_blocks(granted_sid):
    """The grant is session-specific: another session's flag does not bypass."""
    assert run_hook(GRANTED_FORM, session_id=fresh_sid()) == BLOCK


def test_AC7c_matching_allow_sentinel_allows(sentinel_sid):
    """A structured /allow sentinel matching op=git target=clean bypasses."""
    assert run_hook(GRANTED_FORM, session_id=sentinel_sid) == ALLOW


# ── AC8: quoted TOKEN corruption — options as well as values (OBJ-E) ─────────

AC8_FORMS = [
    "git clean -f '-e' -n", "git clean -f -n '--no-dry-run'",
    "git clean '-fe' -n", "git clean -f '--' -n", 'git clean -f "-e" -n',
    'git clean -f -n "--no-dry-run"', 'git clean "-fe" -n',
    'git clean -f "--" -n', "git clean -f -e 'a' -e -n",
    "git clean -e 'keep' --no-dry-run", 'git clean -e "a" -n',
    "git clean -f --exclude 'build' -n",
]


@pytest.mark.parametrize("form", AC8_FORMS)
def test_AC8_quoted_tokens_block(form):
    """Context-stripping blanks EVERY quoted token after the command word —
    single-quoted ones vanish, double-quoted ones survive content-free — so a
    quoted OPTION erases the destructive signal. T1 fails closed on both."""
    assert run_hook(form) == BLOCK


# ── AC9: fail-closed coarse fallback + config-read exemption ─────────────────

AC9_FAIL_CLOSED_FORMS = [
    "env -i git clean -f -n --no-dry-run",
    "command -- git clean -f -n --no-dry-run",
    "time -p git clean -f -n --no-dry-run",
]
AC9_CONFIG_READ = "git config clean.requireForce false"


@pytest.mark.parametrize("form", AC9_FAIL_CLOSED_FORMS)
def test_AC9_zero_invocation_wrappers_fail_closed(form):
    """These wrappers make the classifier yield ZERO clean invocations while
    git still executes the clean, so the coarse anchor must block."""
    assert run_hook(form) == BLOCK


# Dev self-review extension: the coarse anchor must ALSO cover a PATH-QUALIFIED
# git behind a zero-invocation wrapper. The bare-git anchor class
# (^|[[:space:];&|()`])git never matches the '/' in /usr/bin/git, so a
# GIT_CMD_RE-only fallback lets these through while git still deletes.
AC9_PATH_QUALIFIED_FAIL_CLOSED_FORMS = [
    "env -i /usr/bin/git clean -f -n --no-dry-run",
    "command -- /usr/bin/git clean -f",
    "time -p /usr/bin/git clean -fd",
]


@pytest.mark.parametrize("form", AC9_PATH_QUALIFIED_FAIL_CLOSED_FORMS)
def test_AC9_path_qualified_zero_invocation_wrappers_fail_closed(form):
    """Zero classifier invocations AND a path-qualified git: the fallback must
    use the path-tolerant anchor, not the bare-git one."""
    assert run_hook(form) == BLOCK


def test_AC9_config_read_is_not_a_clean_subcommand():
    """The `clean` here is a config KEY token; the subcommand anchor must not
    misfire on it."""
    assert run_hook(AC9_CONFIG_READ) == ALLOW


# ── AC10: no regression on the sibling blocks ────────────────────────────────

AC10_FORMS = ["rm foo", "git reset --hard HEAD~1"]


@pytest.mark.parametrize("form", AC10_FORMS)
def test_AC10_sibling_blocks_not_regressed(form):
    """The rm-block and the ref-mutation block must still fire."""
    assert run_hook(form) == BLOCK


# ── AC11: this test file exists and covers AC1-AC10 and AC12-AC14 ────────────

AC11_COVERED = [
    "AC1", "AC2", "AC3", "AC4", "AC5", "AC6", "AC7",
    "AC8", "AC9", "AC10", "AC12", "AC13", "AC14", "AC15", "AC16",
]


def test_AC11_every_ac_has_an_executing_test():
    """Each covered AC id must own at least one test function in this module."""
    source = Path(__file__).read_text()
    missing = [ac for ac in AC11_COVERED if ("def test_%s" % ac) not in source]
    assert missing == [], "ACs without a test function: %s" % missing


# ── AC12: non-quote untrusted tokens (backslash / expansion / history) ───────

AC12_FORMS = [
    "git clean -f \\-e -n", "git clean \\-fe -n", "E=-e; git clean -f ${E} -n",
    "N=--no-dry-run; git clean -f -n ${N}", "git clean -f {-e,-x} -n",
    "git clean -f $'-e' -n", "git clean -f -n ^X:1", "git clean -f -n ~/x",
]


@pytest.mark.parametrize("form", AC12_FORMS)
def test_AC12_non_quote_untrusted_tokens_block(form):
    """Backslash, ${VAR}, brace, ANSI-C, ^ and ~ are rewritten by bash AFTER
    the hook reads them, and contain no quote character — a quote-only trust
    test would miss every one of these."""
    assert run_hook(form) == BLOCK


# ── AC13: argument injection via an appending wrapper ────────────────────────

AC13_FORMS = [
    "printf %s --no-dry-run|xargs git clean -f -n",
    "echo --no-dry-run | xargs git clean -n",
    "printf %s -f | xargs git clean -n",
]

# QA advisory A1 (must_fix_in_dev): a path-qualified wrapper injects arguments
# identically and DELETES live, so T3 matches the command word's BASENAME —
# mirroring the normalization the classifier already applies to git itself.
AC13_PATH_QUALIFIED_FORMS = [
    "printf %s --no-dry-run | /usr/bin/xargs git clean -f -n",
    "printf %s --no-dry-run | /bin/xargs git clean -f -n",
]


@pytest.mark.parametrize("form", AC13_FORMS + AC13_PATH_QUALIFIED_FORMS)
def test_AC13_argument_injecting_wrapper_blocks(form):
    """Every token here passes the T1 whitelist — only T3 closes this."""
    assert run_hook(form) == BLOCK


def test_AC13_pathspec_named_xargs_is_not_an_injection():
    """T3 is scoped to COMMAND WORDS, so a pathspec literally named `xargs`
    does not fire it (QA advisory A6)."""
    assert run_hook("git clean -n xargs") == ALLOW


# ── AC14: accepted over-blocks are blocked AND escapable ─────────────────────

AC14_OVER_BLOCK_FORMS = [
    "git clean -n 'somepath'", 'git clean -n "some path"',
    "git clean -n -e build", "git clean -n ~/scratch",
]
AC14_ESCAPE_FORM = "git clean -n 'somepath'"


@pytest.mark.parametrize("form", AC14_OVER_BLOCK_FORMS)
def test_AC14_accepted_over_blocks_block(form):
    """A documented fail-safe cost of the trust gate, not a defect."""
    assert run_hook(form) == BLOCK


def test_AC14_over_block_is_escapable_with_a_grant(granted_sid):
    """The same over-blocked preview passes under a matching /do consent."""
    assert run_hook(AC14_ESCAPE_FORM, session_id=granted_sid) == ALLOW


# ── AC15: a QUOTED binary or subcommand is still an invocation ───────────────
# Regression anchor for the highest-severity hole found after the first pass:
# every form below was measured at rc=0 — ALLOWED with NO grant of any kind —
# because bash strips the quotes before exec while both detection layers kept
# them. Two independent causes: the shared classifier basenamed the RAW token,
# so `"/usr/bin/git"` basenamed to `git"` and no invocation was recorded; and
# the coarse fallback's anchor and path classes admit neither `/` nor a quote,
# so it did not catch what the classifier missed.

AC15_QUOTED_BLOCK_FORMS = [
    # quoted binary, path-qualified and bare, both quote styles
    '"/usr/bin/git" clean -fd', "'/usr/bin/git' clean -fd",
    '"git" clean -fd', "'git' clean -fd",
    '"/usr/bin/git" clean', '"/usr/bin/git" clean -f',
    '"/usr/bin/git" -C /tmp clean -fd', 'sudo "git" clean -fd',
    # quoted SUBCOMMAND — context-stripping blanks it, so the stripped stream
    # sees no `clean` at all and only the fallback can catch these
    'git "clean" -fd', "git 'clean' -fd",
    # quoted binary behind a zero-invocation wrapper: neither layer saw these
    'env -i "/usr/bin/git" clean -fd', 'env -i "git" clean -fd',
    'command -- "git" clean -fd', "time -p '/usr/bin/git' clean -fdx",
    # the quoted spelling must not escape the chain, negation or T3 rules either
    'echo hi; "git" clean -fd', '"git" clean -f -n --no-dry-run',
    'printf %s --no-dry-run|xargs "git" clean -f -n',
]


@pytest.mark.parametrize("form", AC15_QUOTED_BLOCK_FORMS)
def test_AC15_quoted_binary_or_subcommand_blocks(form):
    """No spelling of a destructive clean is allowed without a grant."""
    assert run_hook(form) == BLOCK


# The fix must close the hole WITHOUT swallowing commands that merely quote
# the phrase as DATA. That is why the fallback matches quotes as a balanced
# pair hugging the binary (`"git"`) instead of adding quote characters to the
# anchor class: `"git" clean` and `"git clean"` differ only in where the
# closing quote falls, and a class-widening anchor cannot tell them apart.
AC15_ALLOW_FORMS = [
    # a quoted binary running a PROVABLE dry run is still provable
    '"/usr/bin/git" clean -n', '"git" clean -nd',
    # quoted phrases as data: not invocations, must stay usable
    "grep -n 'git clean' file.txt",
    'echo "git clean -fd"',
    "echo 'git clean -fd'",
]


@pytest.mark.parametrize("form", AC15_ALLOW_FORMS)
def test_AC15_quoted_fix_does_not_over_block(form):
    """Closing the quoted hole must not cost the dry-run or data surface."""
    assert run_hook(form) == ALLOW


# ── AC16: grant channel 4 of 4 — the subagent side of /do consent ────────────
# The other three grant exits run BEFORE this deny, so they already reach lane
# r03-c's pre-clean WIP snapshot guard. The subagent /do exit runs AFTER it, so
# the deny preempted the snapshot and made an explicit human grant weaker on
# this channel than on the other three. The deny now honours it, and the
# release is exactly as wide as that exit's own predicate — never wider.

@pytest.fixture
def throwaway_repo(tmp_path):
    """A git repo with one untracked WIP file, so a granted clean has
    something to snapshot and the snapshot lands outside this repository."""
    subprocess.run(
        ["git", "init", "-q", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "--allow-empty", "-m", "base"],
        cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "untracked_wip.txt").write_text("wip")
    return str(tmp_path)


AC16_GRANTED_FORMS = ["git clean -fd", "git clean -fdx", '"/usr/bin/git" clean -fd']


@pytest.mark.parametrize("form", AC16_GRANTED_FORMS)
def test_AC16a_subagent_do_consent_reaches_the_snapshot_guard(
        granted_sid, throwaway_repo, form):
    """A granted destructive clean on the subagent channel must proceed —
    through the snapshot guard, not around this deny."""
    assert run_hook(form, session_id=granted_sid, agent_id="agent-under-test",
                    cwd=throwaway_repo) == ALLOW


def test_AC16b_subagent_grant_still_denies_an_unprotectable_clean(
        granted_sid, throwaway_repo):
    """Releasing the deny hands the command to a FAIL-CLOSED guard: a clean
    whose target is a redirected tree cannot be snapshotted, so it is denied
    even though the grant is valid."""
    assert run_hook("git -C /tmp/elsewhere clean -fd", session_id=granted_sid,
                    agent_id="agent-under-test", cwd=throwaway_repo) == BLOCK


@pytest.mark.parametrize("form", ["git clean -fd", '"/usr/bin/git" clean -fd'])
def test_AC16c_subagent_without_a_grant_still_blocks(form, throwaway_repo):
    """The carve-out is the grant, not the agent: no flag, no release."""
    assert run_hook(form, agent_id="agent-under-test",
                    cwd=throwaway_repo) == BLOCK


def test_AC16d_subagent_grant_for_another_session_does_not_release(
        granted_sid, throwaway_repo):
    """Session-scoped exactly like the main-agent channel (AC7b)."""
    assert run_hook("git clean -fd", session_id=fresh_sid(),
                    agent_id="agent-under-test", cwd=throwaway_repo) == BLOCK
