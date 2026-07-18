r"""DRIFT GUARD — the shell fail-CLOSED fallback vs the engine's front-end tokens.

WHY THIS FILE EXISTS
────────────────────
`pretool-bash-safety.sh::_runtime_guard_fail_closed` is a regex approximation of the
verb families the ENGINE recognizes. It is the last link in the fail-CLOSED chain:
when the decision engine returns any non-ALLOW verdict (INDETERMINATE sentinel, a
crash, a missing deployment), the shell helper is the ONLY thing standing between a
protected command and a silent ALLOW.

That helper is maintained BY HAND while the engine's token sets evolve in Python.
Twice now the engine grew front-ends the shell never learned about, and each time the
fail-CLOSED guarantee silently became false while every existing test stayed green:

  * `_core.HTTP_CLIENT_HEADS` gained `http` / `https` / `httpie` — the shell knew only
    nc/ncat/netcat/socat/telnet/curl/wget.
  * `_core._is_kill_executor` gained the `fuser` file-user front-end — the shell knew
    only `constants.KILL_VERBS`.

Both were invisible because nothing MECHANICALLY tied the two sides together. These
tests are that tie. They import the engine's OWN definitions and assert the shell
helper denies a representative command for every token in them, so adding a token to
the engine WITHOUT widening the shell fallback fails here — loudly — instead of
silently re-opening the hole.

WHAT THIS FILE DOES **NOT** CLAIM
─────────────────────────────────
It asserts TOKEN-SET COVERAGE across FOUR INVOCATION FORMS ONLY (bare / quoted-whole /
path-qualified / path-qualified+quoted), for the P5 endpoint-client and P6 process-
termination families — the only two families this test mechanically checks (they are
NOT the only families the fallback covers at all). It does NOT assert
semantic equivalence with the engine's lexer, and passing it does NOT mean any family
is fail-CLOSED family-wide. The single authoritative account of the fallback's coverage
and its limits (which lexical forms the regex fallback does not match, and why only full
semantic equivalence with the engine's lexer is impossible) lives at
`hooks/pretool-bash-safety.sh::_runtime_guard_fail_closed`;
the residual gaps (STEP0/P3/P4/P7 fail-OPEN on a crash) live in
`docs/reference/core-context-refactor-plan.md`. Do not restate them here.

SAFETY: every command below is a STRING fed to the helper. Nothing is executed, and no
real service, endpoint, or process is ever contacted. Vocabulary is assembled from
fragments so this file's own source never types a full termination-pipeline phrase —
same convention as test_runtime_guard.py.
"""
import ast
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
HOOK = os.path.join(HOOKS_DIR, "pretool-bash-safety.sh")
CORE_PY = os.path.join(HOOKS_DIR, "lib", "runtime_guard", "_core.py")

sys.path.insert(0, os.path.join(HOOKS_DIR, "lib"))

from runtime_guard._core import (  # noqa: E402
    HTTP_CLIENT_HEADS,
    NET_HEADS,
    RAW_SOCKET_HEADS,
    _is_kill_executor,
)
from runtime_guard.constants import KILL_VERBS  # noqa: E402

# ── vocabulary fragments (never a whole phrase in this file's source) ────────
_EP = "/st" + "op"                       # a protected control-endpoint path
_URL = "http://127.0.0.1:8080" + _EP
_FUSER = "fu" + "ser"                    # file-user termination front-end
_KFLAG = "-k"                            # its kill-flag
_IDENT = "happy-" + "daemon"             # a protected process identifier

# The engine's P6 front-ends that are NOT in KILL_VERBS. `fuser` is recognized by
# `_is_kill_executor` via a literal head comparison rather than a named set, so it is
# listed here explicitly AND its engine-side recognition is asserted independently by
# test_engine_still_recognizes_fuser_frontend (so this list cannot quietly go stale).
_EXTRA_KILL_FRONTENDS = frozenset({_FUSER})

# Head literals `_is_kill_executor` compares against that are NOT themselves
# termination front-ends. `xargs` is an argument-wrapper: the engine unwraps it and
# re-tests the WRAPPED verb, and the shell fallback catches those forms via the
# wrapped token (`xargs kill` matches on `kill`). Anything appearing in that function
# outside this set and KILL_VERBS is a NEW front-end that must be mirrored in the
# shell helper — see test_no_unmirrored_kill_frontend_literals.
_KILL_WRAPPER_HEADS = frozenset({"xargs"})


# ── shell-helper harness ────────────────────────────────────────────────────
def _extract_helper():
    """Lift `_runtime_guard_fail_closed` out of the hook so it can be called alone.

    Sourcing the whole hook would run its top-level logic; the helper is a pure
    text-predicate, so we extract just its definition. If the function is renamed or
    restructured the extraction yields nothing and every test here fails loudly —
    which is the correct outcome for a drift guard.
    """
    with open(HOOK, encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r"^_runtime_guard_fail_closed\(\)\s*\{.*?^\}", src, re.S | re.M)
    assert m, (
        "could not extract _runtime_guard_fail_closed from the hook — it was renamed "
        "or restructured. The fail-CLOSED drift guard cannot verify coverage; fix the "
        "extraction (or the helper) rather than deleting this test."
    )
    return m.group(0)


@pytest.fixture(scope="module")
def helper_path(tmp_path_factory):
    p = tmp_path_factory.mktemp("failclosed") / "helper.sh"
    p.write_text(_extract_helper(), encoding="utf-8")
    # the extracted fragment must itself be valid bash
    r = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, f"extracted helper is not valid bash: {r.stderr}"
    return str(p)


def _denies(helper_path, cmd):
    """True iff the shell fallback conservatively DENIES this raw command text."""
    script = (
        f"source {helper_path}\n"
        '_runtime_guard_fail_closed "$1" && echo DENY || echo ALLOW\n'
    )
    r = subprocess.run(["bash", "-c", script, "_", cmd], capture_output=True, text=True)
    assert r.returncode == 0, f"helper harness failed: {r.stderr}"
    return r.stdout.strip() == "DENY"


def _invocation_forms(tok, args):
    """The invocation forms the ENGINE normalizes and still recognizes.

    The engine strips a leading path and surrounding quotes before matching a head, so
    the shell fallback must tolerate the same forms or they slip through it.
    """
    return [
        ("bare", f"{tok} {args}"),
        ("path-qualified", f"/usr/bin/{tok} {args}"),
        ("quoted", f'"{tok}" {args}'),
        ("path-qualified+quoted", f"'/usr/bin/{tok}' {args}"),
    ]


# ── P5: endpoint clients ────────────────────────────────────────────────────
@pytest.mark.parametrize("tok", sorted(NET_HEADS))
def test_shell_fallback_covers_every_engine_endpoint_client(helper_path, tok):
    """Every token in the engine's NET_HEADS must be denied by the shell fallback.

    Derived from `_core.NET_HEADS` itself: adding a client to the engine without
    widening `_runtime_guard_fail_closed` fails HERE.
    """
    for form, cmd in _invocation_forms(tok, _URL):
        assert _denies(helper_path, cmd), (
            f"FAIL-CLOSED DRIFT: the engine recognizes {tok!r} as a P5 endpoint client "
            f"(_core.NET_HEADS), but the shell fallback ALLOWs the {form} form:\n"
            f"    {cmd}\n"
            f"With a non-ALLOW engine verdict this command falls through to ALLOW — the "
            f"exact fail-open the fallback exists to close. Widen the endpoint-client "
            f"line in hooks/pretool-bash-safety.sh::_runtime_guard_fail_closed."
        )


def test_net_heads_is_the_union_of_both_client_kinds():
    """Guard the derivation itself: NET_HEADS must stay the union the tests iterate.

    If a THIRD client kind is introduced and NET_HEADS stops being this union, the
    parametrization above would silently stop covering it.
    """
    assert NET_HEADS == RAW_SOCKET_HEADS | HTTP_CLIENT_HEADS, (
        "NET_HEADS is no longer RAW_SOCKET_HEADS | HTTP_CLIENT_HEADS — the drift guard "
        "iterates NET_HEADS and may no longer cover every endpoint client kind."
    )


# ── P6: process-termination front-ends ──────────────────────────────────────
@pytest.mark.parametrize("tok", sorted(KILL_VERBS | _EXTRA_KILL_FRONTENDS))
def test_shell_fallback_covers_every_engine_kill_frontend(helper_path, tok):
    """Every P6 termination front-end the engine recognizes must be denied."""
    args = f"{_KFLAG} {_IDENT}" if tok == _FUSER else _IDENT
    for form, cmd in _invocation_forms(tok, args):
        assert _denies(helper_path, cmd), (
            f"FAIL-CLOSED DRIFT: the engine recognizes {tok!r} as a P6 process-"
            f"termination front-end, but the shell fallback ALLOWs the {form} form:\n"
            f"    {cmd}\n"
            f"With a non-ALLOW engine verdict this command falls through to ALLOW. "
            f"Widen the process-termination line in "
            f"hooks/pretool-bash-safety.sh::_runtime_guard_fail_closed."
        )


def test_engine_still_recognizes_fuser_frontend():
    """`fuser` is listed in _EXTRA_KILL_FRONTENDS by hand — prove it is really one.

    Keeps the hand-maintained list honest in the REMOVAL direction: if the engine drops
    the fuser front-end, this fails and the list gets pruned rather than testing a
    front-end that no longer exists.
    """
    assert _is_kill_executor(_FUSER, [_KFLAG, _IDENT]) is True, (
        f"the engine no longer treats {_FUSER!r} + {_KFLAG!r} as a kill executor — "
        f"prune it from _EXTRA_KILL_FRONTENDS."
    )


def _head_literals(fn):
    """String literals compared against the `head` parameter inside `fn`.

    Recognizes the two shapes that can introduce a front-end via an inline literal:
      * `head == "fuser"`        -> ast.Compare(left=Name('head'), comparators=[Constant])
      * `head in {"fuser", ...}` -> ast.Compare(left=Name('head'), comparators=[Set|List|Tuple])
    A comparison against a NAMED set (`head in KILL_VERBS`) yields no literals here by
    design — it is diffed set-wise by the parametrized tests instead.
    """
    lits = set()

    def _collect(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lits.add(node.value)
        elif isinstance(node, (ast.Set, ast.List, ast.Tuple)):
            for elt in node.elts:
                _collect(elt)

    for node in ast.walk(fn):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) \
                and node.left.id == "head":
            for comp in node.comparators:
                _collect(comp)
    return lits


def test_no_unmirrored_kill_frontend_literals():
    """Catch a NEW head literal added to `_is_kill_executor` (the fuser-class drift).

    `fuser` was missed because it is a bare literal inside the function, not a member of
    a named set the shell side could be diffed against. This parses that function and
    fails on any head literal that is neither a known wrapper nor an acknowledged
    front-end — forcing whoever adds one to also widen the shell fallback and extend
    _EXTRA_KILL_FRONTENDS.

    SCOPE — two literal-bearing comparison shapes against `head` are recognized:
      * direct equality  — `head == "fuser"`
      * membership test  — `head in {"fuser", ...}` / `[...]` / `(...)` over INLINE
        string literals
    Both are covered because recognizing only the first would let the second form
    introduce a front-end this guard never sees (falsified below in
    test_membership_form_drift_is_caught). NOT recognized, by design: a comparison
    against a NAMED set (`head in KILL_VERBS`) — that is not a literal and is already
    diffed set-wise by the parametrized tests above; and any head reached through
    indirection (a variable, a call, an attribute) rather than an inline literal. A
    front-end introduced that way is NOT caught here — state that limit rather than
    implying total coverage.
    """
    with open(CORE_PY, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "_is_kill_executor"),
        None,
    )
    assert fn is not None, (
        "_is_kill_executor no longer exists in _core.py — the P6 front-end drift guard "
        "cannot introspect it; re-point this test rather than deleting it."
    )

    # every string literal compared against the `head` parameter, in BOTH the direct
    # equality form (`head == "x"`) and the membership form (`head in {"x", "y"}`).
    heads = _head_literals(fn)

    known = set(KILL_VERBS) | set(_EXTRA_KILL_FRONTENDS) | set(_KILL_WRAPPER_HEADS)
    unknown = heads - known
    assert not unknown, (
        f"FAIL-CLOSED DRIFT: _is_kill_executor recognizes new head(s) {sorted(unknown)} "
        f"that the shell fallback was never taught about. Either add each to the "
        f"process-termination line in _runtime_guard_fail_closed and to "
        f"_EXTRA_KILL_FRONTENDS, or — if it is an argument-wrapper whose WRAPPED verb "
        f"is what gets denied — add it to _KILL_WRAPPER_HEADS with a note."
    )


def test_membership_form_drift_is_caught():
    """FALSIFIES the widening: the membership form must not be able to hide a head.

    Before the widening, `_head_literals` only understood `head == "x"`, so a front-end
    introduced as `head in {"x"}` was invisible and the drift guard passed while the
    shell fallback knew nothing about it. This drives the analysis over BOTH shapes and
    asserts each surfaces the literal — so deleting the Set/List/Tuple branch fails here
    rather than silently re-opening the hole.
    """
    equality = ast.parse('def f(head, rest):\n    return head == "dr' 'ift_eq"\n').body[0]
    assert _head_literals(equality) == {"dr" "ift_eq"}

    for src in (
        'def f(head, rest):\n    return head in {"dr" "ift_set", "other"}\n',
        'def f(head, rest):\n    return head in ["dr" "ift_set", "other"]\n',
        'def f(head, rest):\n    return head in ("dr" "ift_set", "other")\n',
    ):
        found = _head_literals(ast.parse(src).body[0])
        assert "dr" "ift_set" in found, (
            f"the membership-test form evaded _head_literals for source:\n{src}\n"
            "A new termination front-end could be added as `head in {...}` without the "
            "shell fallback ever learning it. Restore the Set/List/Tuple branch."
        )

    # a NAMED set must stay out — it is diffed set-wise elsewhere, not by literal
    named = ast.parse("def f(head, rest):\n    return head in KILL_VERBS\n").body[0]
    assert _head_literals(named) == set()


# ── the fallback must stay substring-safe (no over-broad denial) ────────────
@pytest.mark.parametrize("cmd", [
    "httpx-cli --version",                          # contains 'http'
    "nctool --help",                                # contains 'nc'
    "curler --version",                             # contains 'curl'
    "socatx --version",                             # contains 'socat'
    "telnetd-wrapper --version",                    # contains 'telnet'
    "cat node_modules/https-proxy-agent/README.md",  # contains 'https' mid-path
    "my-" + _FUSER + "-report --list",              # contains the fuser front-end
    "k" + "ills --help",                            # contains the bare kill verb
    "echo hello world",
    "git status",
    "ls -la packages",
])
def test_fallback_does_not_match_longer_unrelated_tokens(helper_path, cmd):
    """A family name inside a longer token IN THE SAME PATH COMPONENT must not be denied.

    Widening the fallback means a broken engine denies MORE; that pressure must not be
    paid for with false denials on unrelated commands.

    SCOPE — the cases below are all same-component (`httpx-cli`, `nctool`, `curler`).
    This does NOT assert the broader "a longer token containing a family name never
    matches": that is FALSE and verified false. The helper is neither quote-aware nor
    command-position-aware, so a family name standing as a WHOLE token is denied
    wherever it sits — `ls /opt/curl` (final component of an argument path),
    `echo curl` (bare argument), `git commit -m "fix curl retry"` (inside a quoted
    string) are all DENIED. Those over-denials are accepted: this path runs only on an
    already-broken engine. Do not add such a case here expecting it to pass.
    """
    assert not _denies(helper_path, cmd), (
        f"OVER-BLOCK: the fallback denies {cmd!r}, which merely contains a family name "
        f"as a substring of a longer, unrelated token. The token anchoring in "
        f"_runtime_guard_fail_closed regressed."
    )


# ── the widened denial must remain reachable ONLY from the non-ALLOW branch ──
def test_widened_denial_is_gated_behind_a_non_allow_verdict():
    """The fallback must be called ONLY on the non-ALLOW path, never on a healthy ALLOW.

    Coverage was widened, so a mis-wiring that let the helper run on the ALLOW path
    would now deny a large set of benign commands. This asserts the call site stays
    inside the `!= "ALLOW"` branch, structurally.
    """
    with open(HOOK, encoding="utf-8") as fh:
        src = fh.read()
    calls = [m.start() for m in re.finditer(r"^\s*if _runtime_guard_fail_closed",
                                            src, re.M)]
    assert len(calls) == 1, (
        f"expected exactly one _runtime_guard_fail_closed call site, found {len(calls)}."
        " A second call site could invoke the widened denial outside the non-ALLOW "
        "branch."
    )
    branch = src.index('elif [ "$_RUNTIME_GUARD_VERDICT" != "ALLOW" ]')
    closing = src.index("\nelse\n", branch)
    assert branch < calls[0] < closing, (
        "the _runtime_guard_fail_closed call escaped the non-ALLOW branch — the widened "
        "denial could now fire on a healthy ALLOW verdict."
    )
