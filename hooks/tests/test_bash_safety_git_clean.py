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
    return (proc.returncode, proc.stderr) if want_stderr else proc.returncode


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
    "AC8", "AC9", "AC10", "AC12", "AC13", "AC14", "AC15", "AC16", "AC17",
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


# ── AC17: a destructive clean carried as a NESTED SHELL PAYLOAD ──────────────
# QA final verification measured seven spellings executing UNGRANTED at exit 0
# while the rm-block this rule was asked to mirror denies the equivalent
# `sh -c 'rm foo'`. The gap was one of INPUT, not of capability: the fail-closed
# fallback scanned only raw $COMMAND, whereas bash_context_strip already unwraps
# a shell interpreter's -c payload, which is why the rm-block's grep of
# COMMAND_CONTEXT_STRIPPED inherits the coverage for free.
#
# Pinned as a CLASS, not as one example string — every interpreter in
# bash_context_strip._SHELL_INTERPS, both quote styles, the -c/-lc/-ic flag
# spellings, wrapper prefixes and two nesting depths — because this lane's
# recurring failure mode has been criteria passing while real evasions survive.
# Assertions check the hook's OWN stderr token, so a form that some sibling rule
# also happens to deny cannot score a vacuous pass here.

CLEAN_DENY_TOKEN = "destructive 'git clean'"

# The seven spellings QA measured at exit 0, verbatim from the QA report.
AC17_QA_MEASURED = [
    "sh -c 'git clean -fd'",
    "/bin/sh -c 'git clean -fd'",
    'bash -c "git clean -fd"',
    "bash -lc 'git clean -fd'",
    "dash -c 'git clean -fd'",
    "env bash -c 'git clean -fd'",
    'sh -c \'sh -c "git clean -fd"\'',
]

# Class sweep. The interpreters are the ones bash_context_strip treats as shells;
# none of them needs to be installed, because the guard is a text predicate.
_AC17_SHELLS = ["sh", "/bin/sh", "bash", "/bin/bash", "dash", "zsh"]
_AC17_CFLAGS = ["-c", "-lc", "-ic"]
_AC17_PAYLOADS = [
    "git clean -fd",                 # canonical destructive
    "git clean -fdx",                # + ignored files
    "git clean --force",             # long option
    "git clean",                     # bare (requireForce=false hole)
    "git clean -f -n --no-dry-run",  # dry-run token present, effective state OFF
    "/usr/bin/git clean -fd",        # path-qualified inside the payload
    "git -C /tmp clean -fd",         # git GLOBAL OPTION between binary and sub
    "git -c core.x=1 clean -fdx",    # -c key=value form
    "git --no-pager clean -fd",      # long boolean global option
]

# Every shape of git GLOBAL OPTION that GIT_GLOBAL_OPT_RE admits between the
# binary and the subcommand. This is the axis the previous round shipped blind:
# the shell-side scan's regex interpolated the global-option segment and the
# Python count comparison's copy did not, so a payload spelt with ANY of these
# was seen by one layer and missed by the other.
# Option NAME and the value it takes, kept apart from the SPELLING so the value
# can be generated in every joining style. Writing the option and its value as
# one frozen string is what made this axis blind for three consecutive rounds:
# every long option was written with `=`, so a grammar that could not span
# `--namespace ns` or `-c "k=v"` passed the suite while 89 destructive spellings
# executed ungranted. The axis must vary the JOIN, not just the name.
_AC17_GOPT_SPECS = [
    ("--namespace", "ns"), ("--git-dir", "/tmp/r/.git"), ("--work-tree", "/tmp"),
    ("--exec-path", "/x"), ("--super-prefix", "p/"), ("--config-env", "k=E"),
    # Accepted by REAL git 2.54.0 (verified by execution) but absent from the
    # shared GIT_GLOBAL_OPT_RE enumeration, and PROVEN to delete an untracked
    # file and a nested untracked directory in its separate-value spelling.
    ("--attr-source", "HEAD"),
    ("-c", "core.x=1"), ("-C", "/tmp"),
]
# Options that take NO value, so they have exactly one spelling.
_AC17_GOPT_NOVAL = [
    "--no-pager", "--bare", "--literal-pathspecs", "--glob-pathspecs",
    "--icase-pathspecs", "--no-optional-locks", "-p", "-P",
    "--no-lazy-fetch", "--no-advice",
]


def _ac17_value_joinings(name, value):
    """EVERY way one global option's value can be JOINED to it.

    THE axis every prior corpus omitted. `--namespace=ns` and `--namespace ns`
    are the same option to git and different strings to a regex, and a fix
    validated only against the first cannot be shown to cover the second.
    """
    if name.startswith("--"):
        return ["%s=%s" % (name, value),          # inline
                "%s %s" % (name, value),          # separate token
                '%s="%s"' % (name, value),        # quoted inline, double
                "%s='%s'" % (name, value),        # quoted inline, single
                '%s "%s"' % (name, value)]        # quoted separate
    return ["%s %s" % (name, value),              # separate token
            "%s%s" % (name, value),               # attached
            '%s "%s"' % (name, value),            # quoted separate, double
            "%s '%s'" % (name, value)]            # quoted separate, single


def _ac17_global_opts():
    forms = []
    for name, value in _AC17_GOPT_SPECS:
        forms.extend(_ac17_value_joinings(name, value))
    return forms + _AC17_GOPT_NOVAL


_AC17_GLOBAL_OPTS = _ac17_global_opts()

# Wrapper prefixes that make the shared classifier resolve ZERO git invocations,
# so the coarse occurrence scan is the ONLY remaining guard. AC9 asserts a
# UNIVERSAL over this class but listed three literal strings; the three passed
# while the universal was false, which is how a green suite certified a
# regression. Generated as a cross product with the joining axis instead.
_AC17_WRAPPERS = [
    "env -u FOO", "time -p", "nice -n 5", "stdbuf -o0", "ionice -c 3",
    "setsid -w", "nohup", "command --", "env -i",
]


def _ac17_shell_matrix():
    """Every shell x -c spelling x quote style carrying a destructive clean."""
    forms = []
    for shell in _AC17_SHELLS:
        for flag in _AC17_CFLAGS:
            forms.append("%s %s 'git clean -fd'" % (shell, flag))
            forms.append('%s %s "git clean -fd"' % (shell, flag))
    return forms


def _ac17_payload_matrix():
    """Each destructive payload spelling, carried by a nested shell."""
    return ["sh -c '%s'" % payload for payload in _AC17_PAYLOADS]


def _ac17_nesting_matrix():
    """Depth 1, 2 and 3, in both quote orders."""
    return [
        "sh -c 'git clean -fd'",
        'sh -c "git clean -fd"',
        'sh -c \'sh -c "git clean -fd"\'',
        'bash -c \'bash -c "git clean -fd"\'',
        'sh -c \'bash -c "git clean -fd"\'',
        'sh -c "sh -c \'sh -c \\"git clean -fd\\"\'"',
    ]


# Interpreter NAMES beyond the four bash_context_strip calls shells. For these
# the stripper does NOT unwrap the -c payload — it blanks it as an ordinary
# quoted argument — so the stripped view holds no evidence and only the raw
# stream still carries it. Every one of these was measured escaping at exit 0
# before the probe was extended to the raw stream.
_AC17_SHELL_NAMES = [
    "sh", "/bin/sh", "bash", "/bin/bash", "dash", "zsh", "ksh", "mksh",
    "pdksh", "ash", "yash", "csh", "tcsh", "fish", "busybox sh",
    "/usr/bin/env sh",
]


def _ac17_shell_name_matrix():
    """One canonical destructive form per interpreter name."""
    return ["%s -c 'git clean -fd'" % name for name in _AC17_SHELL_NAMES]


def _ac17_indirect_matrix():
    """Routes to a nested shell that are not a bare interpreter in command
    position: an exec/eval prefix, a wrapper that swallows the command word,
    an argument-injecting wrapper, and a payload piped INTO a shell."""
    return [
        "exec sh -c 'git clean -fd'",
        "eval sh -c 'git clean -fd'",
        "timeout 5 sh -c 'git clean -fd'",
        "nohup sh -c 'git clean -fd'",
        "sudo sh -c 'git clean -fd'",
        "echo x | xargs -I{} sh -c 'git clean -fd'",
        "printf %s 'git clean -fd' | sh",
        "printf %s 'git clean -fd' | bash",
        "printf %s 'git clean -fd' | /bin/sh",
        "sh -c 'cd /tmp && git clean -fd'",
        "$(sh -c 'git clean -fd')",
        "sh -c 'true\ngit clean -fd'",
    ]


def _ac17_chained_matrix():
    """A PROVABLE dry-run chained with a nested destructive payload.

    This is the sub-class that made the first attempt at AC17 insufficient. The
    shell-side fail-closed fallback only runs when the classifier resolved NO
    clean invocation, so prefixing the payload with `git clean -n;` suppressed
    it and the destructive half ran ungranted — every form here was measured at
    exit 0. Closed by comparing the coarse `git … clean` occurrence count with
    the number the parser could resolve.
    """
    return [
        "git clean -n; sh -c 'git clean -fd'",
        "git clean -n && sh -c 'git clean -fd'",
        "sh -c 'git clean -fd'; git clean -n",
        "git clean -n | sh -c 'git clean -fd'",
        "git clean -n; ksh -c 'git clean -fd'",
        "git clean -n; exec sh -c 'git clean -fd'",
        "git clean -n; printf %s 'git clean -fd' | sh",
        "git config clean.requireForce false; sh -c 'git clean -fd'",
    ]


def _ac17_globalopt_chained_matrix():
    """THE class the previous round shipped reachable: a resolvable clean
    chained with a nested payload whose git invocation carries a GLOBAL OPTION.

    Generated as a CROSS PRODUCT over the class axes — every global-option
    spelling x chain separator x interpreter x nesting depth — rather than as
    the handful of example strings QA happened to measure. A fix that closes
    only the measured examples fails here; only agreement between the two
    occurrence grammars passes. Every form was measured at exit 0, ungranted,
    against the pre-fix hook.
    """
    forms = []
    for i, gopt in enumerate(_AC17_GLOBAL_OPTS):
        payload = "git %s clean -fd" % gopt
        sep = ["&&", ";", "|"][i % 3]
        shell = ["sh", "bash", "/bin/sh"][i % 3]
        forms.append("git clean -n %s %s -c '%s'" % (sep, shell, payload))
        forms.append('git clean -nd %s %s -c "%s"' % (sep, shell, payload))
        forms.append("git clean -n --exclude=b %s sh -c 'sh -c \"%s\"'"
                     % (sep, payload))
    return forms


def _ac17_globalopt_wrapper_matrix():
    """A DESTRUCTIVE clean behind a wrapper prefix, in every value-joining
    spelling. This is the direction the previous round could not see: its
    differential ran over ORDINARY commands, which by construction can only
    reveal over-blocks, never a new ALLOW. Every form here was measured at
    exit 0 ungranted against the round-3 hook and PROVEN to delete an untracked
    file and a nested untracked directory at real git 2.54.0.
    """
    forms = []
    for i, (name, value) in enumerate(_AC17_GOPT_SPECS):
        for j, gopt in enumerate(_ac17_value_joinings(name, value)):
            wrapper = _AC17_WRAPPERS[(i + j) % len(_AC17_WRAPPERS)]
            forms.append("%s git %s clean -fd" % (wrapper, gopt))
    for i, gopt in enumerate(_AC17_GOPT_NOVAL):
        forms.append("%s git %s clean -fdx"
                     % (_AC17_WRAPPERS[i % len(_AC17_WRAPPERS)], gopt))
    return forms


# git subcommands that run an ARBITRARY STRING as a command. A destructive clean
# sitting in those quotes is execution, not data, and `git rebase -x '<clean>'`
# was proven to delete while exiting 0 ungranted on BOTH the pre-lane hook and
# the round-3 hook — an ordinary developer command, in no exclusion list.
_AC17_EXEC_CTX = [
    "git rebase -x '%s' HEAD~2",
    'git rebase --exec "%s" -i HEAD~3',
    "git rebase --exec='%s' HEAD~2",
    "git submodule foreach '%s'",
    "git submodule foreach --recursive '%s'",
    "git filter-branch --tree-filter '%s' HEAD",
    "git filter-branch --index-filter '%s' HEAD",
    "git bisect run sh -c '%s'",
    "git clean -n && git rebase -x '%s' HEAD~2",
]
_AC17_EXEC_CFG = ["sequence.editor", "core.pager", "diff.external", "core.editor"]


def _ac17_execctx_matrix():
    """Each exec-taking subcommand carrying each destructive payload spelling,
    plus the `-c <key>='<command>'` route that reaches the same place."""
    forms = []
    payloads = ["git clean -fd", "git -c a=b clean -fdx",
                'git -C "." clean -fd', "git --namespace ns clean -fd",
                "git --attr-source HEAD clean -fd"]
    for i, tmpl in enumerate(_AC17_EXEC_CTX):
        for payload in payloads:
            forms.append(tmpl % payload)
    for key in _AC17_EXEC_CFG:
        forms.append("git -c %s='git clean -fdx' rebase -i HEAD~2" % key)
        forms.append('git -c %s="git clean -fdx" log' % key)
    return forms


# Interpreter names NOBODY enumerated: every one of these escaped the previous
# round's 16-name allowlist at exit 0, and `rbash` is installed on this host and
# IS bash. Listed here as evidence for the class, not as the definition of it —
# the rule under test recognises a command-position word ending in `sh` rather
# than any name, so it must hold for names not written down anywhere.
_AC17_UNLISTED_SHELLS = [
    "ksh93", "rbash", "/usr/bin/rbash", "posh", "oksh", "loksh", "dtksh",
    "elvish", "xonsh", "nsh", "bsh", "sh5", "rzsh", "sash", "wish",
]


def _ac17_unlisted_shell_matrix():
    """Each unlisted interpreter carrying a destructive payload, bare and
    chained behind a provable dry-run, with and without a global option."""
    forms = []
    for i, name in enumerate(_AC17_UNLISTED_SHELLS):
        forms.append("%s -c 'git clean -fd'" % name)
        forms.append("%s -c 'git -c a=b clean -fdx'" % name)
        if i % 2 == 0:
            forms.append("git clean -n && %s -c 'git clean -fd'" % name)
    # QUOTED interpreter binary. The word class that makes the rule structural
    # necessarily excludes the quote characters, so without a balanced-quote
    # alternation `"/bin/sh" -c '<destructive>'` was recognised by nobody and ran
    # ungranted — the same shape the occurrence grammar already handles for the
    # git binary itself (`"git" clean -fd`). Both quote styles, listed and
    # unlisted names, bare and chained.
    for name in ("/bin/sh", "bash", "/usr/bin/rbash", "ksh93"):
        forms.append('"%s" -c \'git clean -fd\'' % name)
        forms.append("'%s' -c 'git clean -fd'" % name)
        forms.append('git clean -n && "%s" -c \'git -C /tmp clean -fd\'' % name)
    return forms


def assert_clean_rule_denies(form):
    """Exit 2 AND the clean rule's own stderr token — never a vacuous pass."""
    rc, err = run_hook(form, want_stderr=True)
    assert rc == BLOCK, "ungranted destructive clean ALLOWED: %r" % form
    assert CLEAN_DENY_TOKEN in err, (
        "denied by some OTHER rule, not the clean rule: %r -> %r" % (form, err))


@pytest.mark.parametrize("form", AC17_QA_MEASURED)
def test_AC17a_qa_measured_nested_payloads_block(form):
    """The exact seven spellings QA measured running ungranted."""
    assert_clean_rule_denies(form)


@pytest.mark.parametrize("form", _ac17_shell_matrix())
def test_AC17b_every_shell_and_c_flag_spelling_blocks(form):
    """sh / /bin/sh / bash / /bin/bash / dash / zsh x -c / -lc / -ic x '' and ""."""
    assert_clean_rule_denies(form)


@pytest.mark.parametrize("form", _ac17_payload_matrix())
def test_AC17c_every_destructive_payload_spelling_blocks(form):
    """The nesting must not become a way to respell the payload either."""
    assert_clean_rule_denies(form)


@pytest.mark.parametrize("form", _ac17_nesting_matrix())
def test_AC17d_nesting_depth_one_two_and_three_block(form):
    """A payload nested two deep keeps its inner quotes in the stripped view;
    quote-neutralisation before the grep is what closes that depth."""
    assert_clean_rule_denies(form)


@pytest.mark.parametrize("form", _ac17_shell_name_matrix())
def test_AC17i_every_interpreter_name_blocks(form):
    """Coverage must not stop at the four names bash_context_strip unwraps:
    ksh, mksh, pdksh, ash, yash, csh, tcsh, fish and `busybox sh` reach the
    same deletion and were all measured escaping at exit 0."""
    assert_clean_rule_denies(form)


@pytest.mark.parametrize("form", _ac17_indirect_matrix())
def test_AC17j_indirect_routes_to_a_nested_shell_block(form):
    """exec / eval / timeout / nohup / sudo prefixes, an xargs-injected shell,
    a payload piped INTO a shell, a cd-prefixed payload, a command
    substitution and a newline-separated payload."""
    assert_clean_rule_denies(form)


def test_AC17e_a_human_grant_still_releases_this_deny(granted_sid):
    """The deny stays in the bypassable region: under a matching /do grant the
    clean rule no longer denies any of these forms.

    What the command meets NEXT is lane r03-c's pre-clean WIP snapshot guard,
    which fails CLOSED on an embedded shell payload because it cannot prove the
    clean targets this working directory. That is the same hand-off AC16b
    already pins for `git -C /tmp/elsewhere clean -fd`, and it is deliberately
    not relaxed here — releasing this deny must not weaken a downstream guard.
    """
    for form in AC17_QA_MEASURED:
        rc, err = run_hook(form, session_id=granted_sid, want_stderr=True)
        assert CLEAN_DENY_TOKEN not in err, (
            "the grant did not release the clean deny: %r -> %r" % (form, err))
        assert rc == ALLOW or "pre-clean WIP snapshot" in err, (
            "released, but stopped by something other than the snapshot "
            "guard: %r -> %r" % (form, err))


def test_AC17f_nested_payload_without_a_grant_is_not_released():
    """Polarity control for AC17e — a non-granting session still denies."""
    for form in AC17_QA_MEASURED:
        assert run_hook(form, session_id=fresh_sid()) == BLOCK, form


# Non-regression: the fix reads the STRIPPED stream, where a non-shell command's
# quoted argument has already been blanked. Data that merely NAMES the
# subcommand must therefore still pass, and so must every AC6 dry-run form
# (those are covered by test_AC6 above and are unaffected because this arm only
# runs when the classifier resolved NO clean invocation at all).
AC17_ALLOW_CONTROLS = [
    # phrase as data, no shell in command position -> probe never neutralises
    'echo "git clean -fd"',
    "grep -rn 'git clean' docs/",
    'python3 -c \'print("git clean -fd")\'',
    'CMD_INPUT="sh -c \'git clean -fd\'" python3 x.py',
    'echo "git clean -fd" > notes.txt',
    # non-git 'clean', and the config/help reads
    "git config clean.requireForce false",
    "git help clean",
    "make clean",
    "./gradlew clean",
    # NOT a valid control here: `npm run clean` exits 2 via the
    # protected-runtime-guard's P9 script-run branch, and does so identically at
    # the pre-lane baseline commit. It is denied by an unrelated, unbypassable
    # guard, so asserting ALLOW on it would be asserting that guard away.
    # a shell IS present but there is no clean at all -> must stay untouched
    "bash -c 'make test'",
    "sh -c 'ls -la'",
    "printf %s hello | sh",
    "timeout 5 sh -c 'sleep 1'",
    "ls *.sh",
    "which bash",
]


@pytest.mark.parametrize("form", AC17_ALLOW_CONTROLS)
def test_AC17g_quoted_data_and_non_git_clean_still_allowed(form):
    """The added scan streams must not widen the mention-level over-block
    beyond the measured, documented set below."""
    assert run_hook(form) == ALLOW, form


# The MEASURED cost of the nested-payload coverage. EIGHT forms, in TWO distinct
# shapes with two distinct mechanisms — the earlier disclosure named only the
# first shape and attributed the whole cost to it, which understated the real
# breadth by half:
#
#   Shape A (the raw-stream scan, gated on a shell in command position) — the
#   phrase appears as DATA in a command that ALSO invokes a shell. Once an
#   unparsed shell payload is present the hook cannot separate an inert mention
#   from an executable one.
#
#   Shape B (the occurrence-count comparison) — an inert prose, grep or
#   commit-message mention chained with a REAL dry-run preview. There is no
#   shell in command position at all here, so shape B is not a leak of the
#   command-position gate; the coarse counter simply cannot tell a mention from
#   an unresolved invocation, and a legitimate preview-plus-documentation
#   command is the everyday casualty.
#
# Accepted, not a defect: both shapes are in the fail-safe direction and both
# are escapable by a human grant. Pinned so any future widening of either
# surface shows up as a test change rather than silently.
AC17_ACCEPTED_OVER_BLOCKS = [
    # shape A — phrase as data alongside a shell invocation
    'bash -c \'echo "git clean -fd"\'',
    "sh -c 'grep -rn \"git clean\" docs/'",
    'bash -lc "make test" && grep -rn \'git clean\' docs/',
    'sh scripts/build.sh && echo "git clean -fd"',
    # shape B — inert mention chained with a real dry-run preview, no shell
    "git clean -n && echo run git clean later",
    "git clean -n; echo see git clean docs",
    "git clean -n && grep -rn git clean docs/",
    'git clean -n && git commit -m "docs: git clean"',
    # shape C — the one form this round newly over-blocks: a repository whose
    # DIRECTORY is literally named `clean`, reached via -C. The cost of the
    # occurrence grammar tolerating global options real git accepts but no
    # enumeration lists. `git -C ./clean status` is the unaffected spelling.
    "git -C clean status",
]


@pytest.mark.parametrize("form", AC17_ACCEPTED_OVER_BLOCKS)
def test_AC17k_accepted_over_blocks_are_blocked_and_escapable(form, granted_sid):
    """Blocked with no grant; released from THIS deny by a matching grant."""
    assert run_hook(form) == BLOCK, form
    _, err = run_hook(form, session_id=granted_sid, want_stderr=True)
    assert CLEAN_DENY_TOKEN not in err, form


@pytest.mark.parametrize("form", _ac17_chained_matrix())
def test_AC17m_dry_run_chained_with_a_nested_payload_blocks(form):
    """A provable dry-run must not launder a nested destructive payload."""
    assert_clean_rule_denies(form)


def test_AC17n_chaining_guard_does_not_over_block_a_lone_dry_run():
    """Polarity control for AC17m: the count comparison must fire only on an
    UNRESOLVED clean. A dry-run beside a shell that carries no clean, and a
    dry-run beside a pure data mention, must both still be allowed."""
    assert run_hook("bash -c 'make test' && git clean -n") == ALLOW
    assert run_hook('git clean -n && echo "git clean -fd"') == ALLOW
    assert run_hook("git clean -n") == ALLOW


def test_AC17l_script_interpreter_payloads_are_a_symmetric_residual():
    """DOCUMENTED RESIDUAL, deliberately not closed by this lane: a payload
    carried by a LANGUAGE interpreter rather than a shell. Measured symmetric
    with the rm-block — both allow — so it is a pre-existing cross-cutting gap
    of the same shape as eval/alias/variable-command-word, not a miss of the
    nested-SHELL class. Closing it would mean treating every interpreter's
    string argument as executable, which is a different capability."""
    for clean_form, rm_form in [
        ("python3 -c 'import os; os.system(\"git clean -fd\")'",
         "python3 -c 'import os; os.system(\"rm foo\")'"),
        ("perl -e 'system(\"git clean -fd\")'", "perl -e 'system(\"rm foo\")'"),
    ]:
        assert run_hook(clean_form) == run_hook(rm_form), clean_form


@pytest.mark.parametrize("form", _ac17_globalopt_chained_matrix())
def test_AC17o_global_option_inside_a_nested_payload_blocks(form):
    """A git GLOBAL OPTION inside the nested payload must not make the payload
    invisible to the layer that guards the chained case.

    Root cause this pins: the shell-side fail-closed scan runs ONLY when the
    classifier resolved zero cleans, so when a resolvable dry-run is present the
    count comparison is the only guard — and its occurrence regex carried no
    global-option segment while the shell-side one did. Both grammars now come
    from a single definition, so this class cannot be reopened by re-spelling
    the option; it can only be reopened by re-introducing a second copy.
    """
    assert_clean_rule_denies(form)


@pytest.mark.parametrize("form", _ac17_globalopt_wrapper_matrix())
def test_AC17q_wrapper_prefixed_global_option_spellings_block(form):
    """AC9's UNIVERSAL, generated instead of exemplified.

    Behind any wrapper prefix the classifier resolves no invocation, so the
    coarse occurrence grammar is the only guard left. Round 3 narrowed that
    grammar and 89 of these flipped from denied to allowed while AC9's three
    literal examples kept passing.
    """
    assert_clean_rule_denies(form)


@pytest.mark.parametrize("form", _ac17_execctx_matrix())
def test_AC17r_exec_taking_git_subcommands_block(form):
    """A clean carried as the command-string ARGUMENT of a git subcommand that
    executes it. Proven destructive at real git; open on every prior hook."""
    assert_clean_rule_denies(form)


def _mutant_hook(tmp_path, *replacements):
    """A copy of the live hook with one property surgically removed, so a
    criterion can be shown to DISCRIMINATE rather than merely to pass."""
    src = Path(HOOK).resolve().read_text(encoding="utf-8")
    for old, new in replacements:
        assert old in src, "mutation target vanished: %r" % old
        src = src.replace(old, new)
    d = tmp_path / "mutant"
    d.mkdir()
    (d / "lib").symlink_to(Path(HOOK).resolve().parent / "lib")
    p = d / "pretool-bash-safety.sh"
    p.write_text(src, encoding="utf-8")
    return str(p)


# One representative per sub-mechanism, each PROVEN destructive at real git.
_AC17_MUTANT_PROBES = [
    "env -u FOO git --namespace ns clean -fd",       # separate-value long opt
    'command -- git -c "core.x=1" clean -fd',        # quoted option value
    "git clean -n && sh -c 'git --git-dir /tmp/r/.git clean -fdx'",
    "git clean -n && sh -c 'git --namespace=\"ns\" clean -fd'",
    "nohup git --attr-source HEAD clean -fd",        # unenumerated separate val
]


def test_AC18z_corpus_discriminates_against_a_grammar_relapse(tmp_path):
    """Proving a criterion against the PRE-EDIT hook alone is what let round 3
    certify a regression as a closure: the pre-edit hook failed the axis for a
    DIFFERENT reason, so the axis looked sharp while being blind to the new
    grammar. The axis must also fail against a mutant of TODAY's hook that
    reintroduces the defect — here, dropping the shared enumeration branch from
    the union and leaving only the hand-shaped syntax branch.
    """
    mut = _mutant_hook(tmp_path, ("${GIT_GLOBAL_OPT_ALT}|", ""))
    escaped = [f for f in _AC17_MUTANT_PROBES if run_hook(f, hook=mut) != BLOCK]
    assert escaped, (
        "the corpus cannot detect a relapse of the round-3 grammar, so passing "
        "it proves nothing about the class it names")
    for form in _AC17_MUTANT_PROBES:
        assert_clean_rule_denies(form)


def test_AC17s_corpus_discriminates_against_exec_context_removal(tmp_path):
    """Same discrimination requirement for the exec-taking-subcommand gate."""
    mut = _mutant_hook(
        tmp_path,
        ('"$_GC_SHELL_RE|$_GC_EXECCTX_RE"', '"$_GC_SHELL_RE"'),
        (" or EXEC_CTX.search(text)", ""))
    probes = ["git rebase -x 'git clean -fd' HEAD~2",
              "git submodule foreach 'git clean -fd'",
              "git filter-branch --tree-filter 'git clean -fd' HEAD"]
    assert [f for f in probes if run_hook(f, hook=mut) != BLOCK], (
        "the exec-context axis does not discriminate")
    for form in probes:
        assert_clean_rule_denies(form)


@pytest.mark.parametrize("key", ["CLEAN_OCCURRENCE_RE", "CLEAN_SHELL_RE",
                                 "CLEAN_EXECCTX_RE"])
def test_AC18y_single_sourced_grammar_fails_closed(tmp_path, key):
    """Every string shared from the shell into the Python verdict must fail
    CLOSED if the sharing breaks. Round 4 split the shared env assignment across
    two lines, which silently defeats a delete-the-line mutation — so the
    mutation renames the exported binding instead, leaving the lookup intact."""
    mut = _mutant_hook(tmp_path, (key + '="$', key + '_BROKEN="$'))
    assert run_hook("git clean -n", hook=mut) == BLOCK, (
        "breaking %s fails OPEN: a benign dry-run was allowed by a hook whose "
        "shared grammar is missing" % key)


@pytest.mark.parametrize("form", _ac17_unlisted_shell_matrix())
def test_AC17p_interpreters_outside_any_name_list_block(form):
    """Recognition must not depend on having enumerated the interpreter.

    A fixed name allowlist was the repeated root cause in this task; every name
    here escaped the previous one. The predicate is now structural — a
    command-position word ending in `sh`, optional version suffix — so passing
    this requires the structural rule, not a longer list. None of these need to
    be installed: the guard is a text predicate.
    """
    assert_clean_rule_denies(form)


def test_AC17h_rm_block_nested_parity_not_regressed():
    """The rule was asked to MIRROR the rm-block; closing this class must not
    have touched it. Depth 1 is denied by both rules; depth 2 is a documented
    residual of the rm-block that this lane did not widen."""
    assert run_hook("sh -c 'rm foo'") == BLOCK
    assert run_hook('bash -c "rm foo"') == BLOCK
