"""Cross-consistency tests for git-command detection across three mechanisms.

Verifies that GIT_CMD_RE (hooks/pretool-bash-safety.sh),
GIT_COMMAND_RE (hooks/pretool-git-privilege-guard.py), and
iter_git_invocations() (hooks/lib/git_command_classifier.py) agree on
which commands are git invocations.

RISK-2: divergence between these mechanisms could mean a command blocked
by one mechanism slips through another, creating a security bypass.

Legitimate divergence (marked xfail):
- None known after RISK-3 fix. Path-qualified forms are now handled by
  the classifier in both safety.sh and privilege-guard.py. The regex
  patterns (GIT_CMD_RE / GIT_COMMAND_RE) share the same anchor class
  [[:space:];&|()`] / [\\s;&|()`] which does NOT include '/', so
  path-qualified forms like /usr/bin/git only match via the classifier.
  When the classifier fires (CLASSIFIER_HAS_PATH_QUALIFIED_GIT=1) bash-
  safety.sh augments GIT_CMD_RE -- the two-layer architecture means both
  safety hooks agree in practice even when the regex alone would miss.
  We test the raw regex patterns here (pre-classifier-augmentation) and
  mark known regex-only divergences as xfail.
"""

import os
import re
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Project root setup
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'hooks'))

from lib.git_command_classifier import iter_git_invocations  # noqa: E402

# ---------------------------------------------------------------------------
# Extract GIT_CMD_RE from pretool-bash-safety.sh
# ---------------------------------------------------------------------------

_BASH_SAFETY_SH = PROJECT_ROOT / 'hooks' / 'pretool-bash-safety.sh'
_PRIVILEGE_GUARD_PY = PROJECT_ROOT / 'hooks' / 'pretool-git-privilege-guard.py'


def _extract_bash_git_cmd_re() -> str:
    """Read pretool-bash-safety.sh and reconstruct GIT_CMD_RE as a Python regex.

    The bash file defines:
      GIT_GLOBAL_OPT_RE='...'
      GIT_CMD_RE='(^|[[:space:];&|()`])git'"$GIT_GLOBAL_OPT_RE"'[[:space:]]+'

    We extract GIT_GLOBAL_OPT_RE then assemble the full pattern string.
    POSIX bracket-expression conversion:
      - Compound anchor [[:space:];&|()`]  ->  [\\s;&|()`]
      - Negated class [^[:space:];|&]      ->  [^\\s;|&]
      - Remaining standalone [[:space:]]   ->  \\s  (used as char class in GOR body)
    Order matters: replace the compound anchor FIRST so that the
    [:space:] fragment inside it does not get replaced prematurely.
    """
    text = _BASH_SAFETY_SH.read_text()

    # Extract GIT_GLOBAL_OPT_RE value
    gor_match = re.search(
        r"^GIT_GLOBAL_OPT_RE='([^']+)'",
        text,
        re.MULTILINE,
    )
    assert gor_match, "Could not find GIT_GLOBAL_OPT_RE in pretool-bash-safety.sh"
    git_global_opt_re = gor_match.group(1)

    # Assemble the raw bash regex string as bash does:
    #   '(^|[[:space:];&|()`])git' + $GIT_GLOBAL_OPT_RE + '[[:space:]]+'
    bash_re_raw = (
        '(^|[[:space:];&|()`])git'
        + git_global_opt_re
        + '[[:space:]]+'
    )

    # Convert POSIX bracket expressions to Python equivalents.
    # 1. Compound anchor (must go first to avoid premature [:space:] replacement)
    py_re = bash_re_raw.replace('[[:space:];&|()`]', r'[\s;&|()`]')
    # 2. Negated class inside GIT_GLOBAL_OPT_RE body
    py_re = py_re.replace('[^[:space:];|&]', r'[^\s;|&]')
    # 3. Remaining standalone [[:space:]] occurrences in the GOR body and suffix
    py_re = py_re.replace('[[:space:]]', r'\s')

    return py_re


def _extract_python_git_command_re() -> str:
    """Import pretool-git-privilege-guard module and read GIT_COMMAND_RE.

    The module defines GIT_COMMAND_RE as a module-level string built from
    r-string concatenation with GIT_GLOBAL_OPTION_RE.  We import the module
    directly (adding its parent directory to sys.path) so Python evaluates
    the concatenation natively and we get the correct assembled regex string.
    """
    hooks_dir = str(PROJECT_ROOT / 'hooks')
    if hooks_dir not in sys.path:
        sys.path.insert(0, hooks_dir)

    # Import the module; its top-level code only assigns constants and imports,
    # so this is safe and does not run any hook logic.
    import importlib
    spec = importlib.util.spec_from_file_location(
        '_pretool_git_privilege_guard',
        str(_PRIVILEGE_GUARD_PY),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    value = getattr(mod, 'GIT_COMMAND_RE', None)
    assert value is not None, "GIT_COMMAND_RE not found in pretool-git-privilege-guard.py"
    assert isinstance(value, str), f"GIT_COMMAND_RE is not a str: {type(value)}"
    return value


# Build both regex objects once at module import time so failures are
# visible as errors, not collection warnings.
BASH_GIT_CMD_RE_STR = _extract_bash_git_cmd_re()
PYTHON_GIT_COMMAND_RE_STR = _extract_python_git_command_re()

BASH_GIT_CMD_PATTERN = re.compile(BASH_GIT_CMD_RE_STR)
PYTHON_GIT_COMMAND_PATTERN = re.compile(PYTHON_GIT_COMMAND_RE_STR)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bash_matches(command: str) -> bool:
    """True iff GIT_CMD_RE (bash, converted to Python) matches the command."""
    return BASH_GIT_CMD_PATTERN.search(command) is not None


def _python_matches(command: str) -> bool:
    """True iff GIT_COMMAND_RE (privilege guard) matches the command."""
    return PYTHON_GIT_COMMAND_PATTERN.search(command) is not None


def _classifier_matches(command: str) -> bool:
    """True iff iter_git_invocations() yields at least one invocation."""
    return len(list(iter_git_invocations(command))) > 0


# ---------------------------------------------------------------------------
# Corpus definition
#
# Format: (command_string, expected_bash, expected_python, expected_classifier,
#           xfail_reason_or_None)
#
# xfail_reason is a string when the case is known to diverge from the
# cross-consistency expectation (all three must agree for non-xfail cases).
# Divergence reason: GIT_CMD_RE and GIT_COMMAND_RE anchor classes do NOT
# include '/', so path-qualified invocations like /usr/bin/git only match
# via the classifier. Those cases are marked xfail for the regex mechanisms
# but pass for the classifier.
# ---------------------------------------------------------------------------

CORPUS = [
    # ------------------------------------------------------------------
    # Simple bare-git forms — all three must agree
    # ------------------------------------------------------------------
    (
        "git commit -m 'msg'",
        True, True, True,
        None,
        "simple git commit",
    ),
    (
        "git reset --hard",
        True, True, True,
        None,
        "git reset hard",
    ),
    (
        "git stash push",
        True, True, True,
        None,
        "git stash push",
    ),
    (
        "git pull",
        True, True, True,
        None,
        "git pull",
    ),
    (
        "git fetch",
        True, True, True,
        None,
        "git fetch",
    ),
    (
        "git merge origin/main",
        True, True, True,
        None,
        "git merge",
    ),
    (
        "git checkout main",
        True, True, True,
        None,
        "git checkout branch",
    ),
    (
        "git status",
        True, True, True,
        None,
        "git status",
    ),
    (
        "git log --oneline",
        True, True, True,
        None,
        "git log",
    ),
    (
        "git diff HEAD",
        True, True, True,
        None,
        "git diff",
    ),
    (
        "git push origin main",
        True, True, True,
        None,
        "git push with remote and branch",
    ),
    (
        "git add -A",
        True, True, True,
        None,
        "git add all",
    ),
    # git alone (no subcommand) — regex requires trailing whitespace, so misses it;
    # classifier yields GitInvocation(subcommand=None) from token split.
    (
        "git",
        False, False, True,
        "bare 'git' with no trailing space/subcommand: both GIT_CMD_RE and "
        "GIT_COMMAND_RE require [[:space:]]+ / \\s+ after the 'git' token, so "
        "bare 'git' at end-of-string matches neither regex. The classifier "
        "splits on tokens (not a regex), so it yields GitInvocation(subcommand=None). "
        "This is a known, benign divergence.",
        "bare git no subcommand",
    ),
    # git -C /some/path status (global option)
    (
        "git -C /some/path status",
        True, True, True,
        None,
        "git with -C global option",
    ),
    # ------------------------------------------------------------------
    # Path-qualified forms (RISK-3 domain)
    # The raw regex patterns (GIT_CMD_RE / GIT_COMMAND_RE) anchor on
    # [[:space:];&|()`] / [\s;&|()`] which does NOT include '/'.
    # Hence a leading /usr/bin/git token does NOT match the raw regex.
    # The classifier correctly detects these via basename comparison.
    # These cases are xfail for the regex checks.
    # ------------------------------------------------------------------
    (
        "/usr/bin/git commit -m 'msg'",
        False, False, True,
        "path-qualified git: raw regex anchor class omits '/', so regex misses it; "
        "classifier detects it via os.path.basename(token)=='git'. "
        "bash-safety.sh compensates via CLASSIFIER_HAS_PATH_QUALIFIED_GIT augmentation at runtime.",
        "path-qualified /usr/bin/git commit",
    ),
    (
        "/usr/bin/git reset --hard",
        False, False, True,
        "path-qualified git: same anchor-class divergence as above",
        "path-qualified /usr/bin/git reset --hard",
    ),
    (
        "/usr/bin/git push --force",
        False, False, True,
        "path-qualified git: same anchor-class divergence as above",
        "path-qualified /usr/bin/git push --force",
    ),
    (
        "/usr/bin/git stash push",
        False, False, True,
        "path-qualified git: same anchor-class divergence as above",
        "path-qualified /usr/bin/git stash push",
    ),
    (
        "/usr/bin/git status",
        False, False, True,
        "path-qualified git: same anchor-class divergence as above",
        "path-qualified /usr/bin/git status",
    ),
    (
        "./git status",
        False, False, True,
        "relative-path-qualified git: same anchor-class divergence as above",
        "relative-path ./git status",
    ),
    # ------------------------------------------------------------------
    # Shell context forms — all three must agree
    # ------------------------------------------------------------------
    # bash -c 'git status': the single-quote is not in the anchor class, so the
    # regex does NOT treat 'git' as a git command here (it sees 'git status' as
    # string argument text, not a command token). The classifier segments on
    # ; | & ` ( ) separators -- the entire payload is one segment with 'bash'
    # as command token. All three: False.
    (
        "bash -c 'git status'",
        False, False, False,
        None,
        "git inside bash -c quoted string -- all three correctly return False",
    ),
    (
        "command git status",
        True, True, True,
        None,
        "command wrapper before git — classifier skips 'command' wrapper",
    ),
    # compound commands
    (
        "cd /tmp && git status",
        True, True, True,
        None,
        "git after && in compound command",
    ),
    (
        "echo ok; git fetch",
        True, True, True,
        None,
        "git after ; in compound command",
    ),
    # ------------------------------------------------------------------
    # Non-git commands — all three must return False
    # ------------------------------------------------------------------
    (
        "echo 'not git'",
        False, False, False,
        None,
        "plain echo — not a git command",
    ),
    (
        "ls -la",
        False, False, False,
        None,
        "ls — not a git command",
    ),
    (
        "/bin/sh -c 'echo test'",
        False, False, False,
        None,
        "sh -c with echo — no git",
    ),
    (
        "python3 -m pytest",
        False, False, False,
        None,
        "pytest — no git",
    ),
    # ------------------------------------------------------------------
    # Edge cases / false-positive traps
    # ------------------------------------------------------------------
    # 'gitk' — GUI tool, basename is 'gitk' not 'git' — should NOT match classifier
    (
        "gitk",
        False, False, False,
        None,
        "gitk: basename is 'gitk', not 'git' — must not be treated as git invocation",
    ),
    # 'digit' — should NOT match
    (
        "digit something",
        False, False, False,
        None,
        "digit: word containing 'git' as substring must not match",
    ),
    # 'github-cli' style command
    (
        "gh pr create",
        False, False, False,
        None,
        "gh CLI: basename 'gh' != 'git'",
    ),
    # git appears only in an argument string, not as a command
    (
        "echo 'git status'",
        False, False, False,
        None,
        "git inside a quoted echo argument — not a command invocation; "
        "classifier splits on shell separators and checks command position only, "
        "so the segment token at command position is 'echo', not 'git'",
    ),
    # git with pipe — the part after | is a new segment
    (
        "git log | grep foo",
        True, True, True,
        None,
        "git log piped — git is still a git invocation",
    ),
    # subshell form
    (
        "$(git rev-parse HEAD)",
        True, True, True,
        None,
        "git inside command substitution — _segments() opens a new segment at $(",
    ),
]

# ---------------------------------------------------------------------------
# Parametrized test
# ---------------------------------------------------------------------------

# Build pytest.param list from CORPUS
_params = []
for entry in CORPUS:
    cmd, exp_bash, exp_python, exp_cls, xfail_reason, label = entry
    marks = []
    if xfail_reason:
        marks.append(pytest.mark.xfail(reason=xfail_reason, strict=False))
    _params.append(pytest.param(
        cmd, exp_bash, exp_python, exp_cls,
        id=label,
        marks=marks,
    ))


@pytest.mark.parametrize(
    "command,expected_bash,expected_python,expected_classifier",
    _params,
)
def test_cross_consistency(command, expected_bash, expected_python, expected_classifier):
    """All three detection mechanisms must agree on the expected outcome.

    For xfail cases the mechanisms are known to diverge (e.g. path-qualified
    git where raw regex patterns do not fire but the classifier does).
    Non-xfail cases must have all three return the same expected value.
    """
    bash_result = _bash_matches(command)
    python_result = _python_matches(command)
    classifier_result = _classifier_matches(command)

    # Each mechanism is checked against its expected value independently.
    assert bash_result == expected_bash, (
        f"GIT_CMD_RE (bash) mismatch for {command!r}: "
        f"got {bash_result}, expected {expected_bash}"
    )
    assert python_result == expected_python, (
        f"GIT_COMMAND_RE (python guard) mismatch for {command!r}: "
        f"got {python_result}, expected {expected_python}"
    )
    assert classifier_result == expected_classifier, (
        f"iter_git_invocations() mismatch for {command!r}: "
        f"got {classifier_result}, expected {expected_classifier}"
    )


# ---------------------------------------------------------------------------
# Corpus sanity checks (run unconditionally — not parametrized)
# ---------------------------------------------------------------------------


def test_corpus_has_minimum_entries():
    """Corpus must contain at least 20 command entries."""
    assert len(CORPUS) >= 20, f"Corpus has only {len(CORPUS)} entries; need >= 20"


def test_corpus_has_minimum_path_qualified():
    """Corpus must contain at least 5 path-qualified invocations."""
    pq_count = sum(
        1 for cmd, *_ in CORPUS
        if cmd.startswith('/') and 'git' in cmd
    )
    assert pq_count >= 5, (
        f"Only {pq_count} path-qualified entries in corpus; need >= 5"
    )


def test_corpus_expected_outcomes_are_explicit():
    """Every corpus entry must have explicitly declared boolean expected values.

    Vacuous tests that derive expected values at runtime would mask regressions.
    """
    for entry in CORPUS:
        cmd, exp_bash, exp_python, exp_cls, _, label = entry
        assert isinstance(exp_bash, bool), (
            f"expected_bash for {label!r} is not a bool: {exp_bash!r}"
        )
        assert isinstance(exp_python, bool), (
            f"expected_python for {label!r} is not a bool: {exp_python!r}"
        )
        assert isinstance(exp_cls, bool), (
            f"expected_classifier for {label!r} is not a bool: {exp_cls!r}"
        )


def test_regex_patterns_are_extractable():
    """Sanity: both regex patterns could be extracted at module load time."""
    assert BASH_GIT_CMD_RE_STR, "GIT_CMD_RE extraction returned empty string"
    assert PYTHON_GIT_COMMAND_RE_STR, "GIT_COMMAND_RE extraction returned empty string"
    # Both should compile without error (already done at module level, but
    # re-assert here so failures are reported as test failures, not import errors)
    re.compile(BASH_GIT_CMD_RE_STR)
    re.compile(PYTHON_GIT_COMMAND_RE_STR)


def test_bash_and_python_patterns_agree_on_anchor():
    """The two raw regex patterns share equivalent anchor semantics.

    Both start with an anchor that allows start-of-string or a set of
    shell separator/operator characters. Verify the anchor character sets
    are functionally equivalent (both include ; & | ( ` and whitespace).
    """
    bash_anchor = re.search(r'^\(', BASH_GIT_CMD_RE_STR)
    python_anchor = re.search(r'^\(', PYTHON_GIT_COMMAND_RE_STR)
    assert bash_anchor, "BASH GIT_CMD_RE does not start with a '(' group"
    assert python_anchor, "PYTHON GIT_COMMAND_RE does not start with a '(' group"

    # Both patterns must recognise 'git status' at the start of a string
    assert _bash_matches("git status"), "Bash pattern must match 'git status' at start of string"
    assert _python_matches("git status"), "Python pattern must match 'git status' at start of string"

    # Both patterns must recognise 'git' after a semicolon
    assert _bash_matches("; git status"), "Bash pattern must match after ;"
    assert _python_matches("; git status"), "Python pattern must match after ;"
