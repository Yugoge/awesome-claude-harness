"""Detectors for the residual-refusal RECOVERY ROUTE in pretool-git-privilege-guard.py.

Background
----------
`_evaluate_command` refuses on a non-empty `residuals` list: a segment whose
command token is git-shaped but statically unresolvable (`g\\it push`,
`$GIT push`, `$(which git) push`).  That refusal fires BEFORE the invocation
list and WITHOUT an allowlist bypass, and the `/do` consent that could override
it is main-agent-only.  A subagent that trips it correctly had NO route at all.

These detectors specify the route:

  D1   a human-authorized, digest-bound override clears the residual refusal
  D2   the refusal message NAMES the route (a route nobody can learn is no route)
  D3   honoring emits an audit record: who authorized, why, what was refused
  D4   the digest binding is exact - an override for a DIFFERENT command is inert
  D5   ORDERING REGRESSION: the residual check still precedes the allowlist
  D6   the override is NOT a general bypass - remaining checks still run
  D7   single-use: the override is consumed at validation time
  D8   expired overrides are inert
  D9   an override with no `reason` is inert (the "why" is structurally required)
  D10  an override without the human-origin marker is inert
  D11  the override is bound to the residual KINDS it was issued for
  D12  every residual refusal is journaled (so the human can see what to sign)
  D13  an override for a command the guard NEVER refused is inert
  D14  RESIDUAL REGRESSION: with no override present, every residual still blocks
  D15  hooks/lib/git_command_classifier.py compiles clean under
       SyntaxWarning-as-error (side item: docstring escape sequence)

D5 and D14 are REGRESSION detectors: green before the change, and they must stay
green after it.  Their load-bearingness is established by ablation, not by being
red first.  Every other detector is red against the pre-change guard.
"""

import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent
SCRATCH = os.environ.get("GITGUARD_TEST_SCRATCH", "/dev/shm/gitguard-route")


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    hooks_str = str(HOOKS_DIR)
    if hooks_str not in sys.path:
        sys.path.insert(0, hooks_str)
    spec.loader.exec_module(mod)
    return mod


# GITGUARD_UNDER_TEST lets the ablation harness point this suite at a MUTATED
# copy of the guard, to prove each mechanism is load-bearing. Unset in normal use.
_GUARD_PATH = Path(os.environ.get("GITGUARD_UNDER_TEST")
                   or (HOOKS_DIR / "pretool-git-privilege-guard.py"))
guard = _load_module(_GUARD_PATH, "pretool_git_privilege_guard_route")

# Four residual shapes, confirmed against hooks/lib/git_command_classifier.py.
# The `&` forms are the ones that matter for D5: `_bash_subcommands` (the grant
# matcher's splitter) does NOT split on `&`, while `_segments` (the residual
# detector's splitter) does - so a single grant-matchable "subcommand" can carry
# an unresolvable git segment.
CMD_DYNAMIC = "$GIT push --force origin master"
CMD_OBFUSCATED = "g\\it push --force origin master"
CMD_SUBSTITUTED = "git status &  $(which git) push --force"
CMD_LAUNDER = "git status & $GIT push --force origin master"
CMD_MIXED_PUSH = "git push --force origin master & $GIT status"


def _digest(command):
    return hashlib.sha256(command.encode("utf-8", "surrogateescape")).hexdigest()


def _data(command, agent_id="agent-sub-1", session_id="sid-route-test"):
    d = {
        "tool_name": "Bash",
        "session_id": session_id,
        "tool_input": {"command": command},
    }
    if agent_id:
        d["agent_id"] = agent_id
    return d


def _evaluate(command, agent_id="agent-sub-1", session_id="sid-route-test"):
    """Run _evaluate_command; return (blocked: bool, stderr: str)."""
    buf = io.StringIO()
    blocked = False
    try:
        with redirect_stderr(buf):
            guard._evaluate_command(command, _data(command, agent_id, session_id))
    except SystemExit as exc:
        blocked = exc.code == 2
    return blocked, buf.getvalue()


class _RouteCase(unittest.TestCase):
    """Base: isolate the override namespace into per-test scratch."""

    def setUp(self):
        os.makedirs(SCRATCH, exist_ok=True)
        self.ns = tempfile.mkdtemp(prefix="override-ns-", dir=SCRATCH)
        self._saved_dir = getattr(guard, "_RESIDUAL_OVERRIDE_DIR", None)
        guard._RESIDUAL_OVERRIDE_DIR = self.ns

    def tearDown(self):
        if self._saved_dir is not None:
            guard._RESIDUAL_OVERRIDE_DIR = self._saved_dir

    # -- helpers ---------------------------------------------------------
    def journal(self):
        p = Path(self.ns) / "refusals.jsonl"
        if not p.exists():
            return []
        return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]

    def audit(self):
        p = Path(self.ns) / "audit.jsonl"
        if not p.exists():
            return []
        return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]

    def write_override(self, command, kinds, *, reason="stuck subagent needs the "
                       "runtime-resolved git binary to finish AC-3",
                       authorized_by="human:yuge.tang@orchestrade.com",
                       origin="userpromptsubmit-hook", ttl_minutes=10,
                       digest=None, session_id="sid-route-test"):
        os.makedirs(self.ns, exist_ok=True)
        now = datetime.now(timezone.utc)
        rec = {
            "kind": "git-residual-override",
            "origin": origin,
            "authorized_by": authorized_by,
            "reason": reason,
            "session_id": session_id,
            "command_sha256": digest if digest is not None else _digest(command),
            "residual_kinds": kinds,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=ttl_minutes)).isoformat(),
        }
        path = Path(self.ns) / ("override-%s.json" % rec["command_sha256"][:16])
        path.write_text(json.dumps(rec))
        return path

    def prime_refusal(self, command):
        """Trip the guard once so the command is recorded as genuinely refused."""
        blocked, _ = _evaluate(command)
        self.assertTrue(blocked, "priming run should have been refused")


class D1_RouteExists(_RouteCase):
    def test_authorized_override_clears_residual_refusal(self):
        self.prime_refusal(CMD_DYNAMIC)
        self.write_override(CMD_DYNAMIC, ["dynamic_git_token"])
        blocked, err = _evaluate(CMD_DYNAMIC)
        self.assertFalse(
            blocked,
            "a human-authorized, digest-bound override must clear the residual "
            "refusal; stderr was:\n" + err)


class D2_RouteIsDiscoverable(_RouteCase):
    def test_refusal_message_names_the_route(self):
        blocked, err = _evaluate(CMD_DYNAMIC)
        self.assertTrue(blocked)
        self.assertIn("could not be statically classified", err)
        # The message must name the recovery route AND hand over the exact
        # digest, so the human does not have to re-derive it.
        self.assertIn(_digest(CMD_DYNAMIC), err,
                      "refusal must print the command digest to authorize")
        self.assertIn("write-git-residual-override.py", err,
                      "refusal must name the recovery route")
        self.assertIn("only the human", err.lower(),
                      "refusal must say the authorization is human-only")


class D3_HonorIsAudited(_RouteCase):
    def test_honor_records_who_why_and_what_was_refused(self):
        self.prime_refusal(CMD_DYNAMIC)
        self.write_override(CMD_DYNAMIC, ["dynamic_git_token"])
        blocked, err = _evaluate(CMD_DYNAMIC)
        self.assertFalse(blocked)
        # (a) non-suppressible: the audit goes to stderr, which lands in the
        #     transcript the agent cannot retroactively edit.
        self.assertIn("RESIDUAL-OVERRIDE HONORED", err)
        self.assertIn("human:yuge.tang@orchestrade.com", err)
        self.assertIn("AC-3", err, "the human's REASON must appear in the audit")
        self.assertIn("dynamic_git_token", err,
                      "the audit must say WHAT was being refused")
        # (b) durable: an append-only journal entry
        recs = self.audit()
        self.assertEqual(len(recs), 1, "exactly one audit record expected")
        rec = recs[0]
        self.assertEqual(rec["event"], "residual_override_honored")
        self.assertEqual(rec["authorized_by"], "human:yuge.tang@orchestrade.com")
        self.assertIn("AC-3", rec["reason"])
        self.assertEqual(rec["residual_kinds"], ["dynamic_git_token"])
        self.assertEqual(rec["command_sha256"], _digest(CMD_DYNAMIC))
        self.assertTrue(rec["residual_segments"],
                        "the refused segments must be recorded verbatim")


class D4_DigestBindingIsExact(_RouteCase):
    def test_override_for_a_different_command_is_inert(self):
        self.prime_refusal(CMD_DYNAMIC)
        # Authorized for a DIFFERENT command; digest will not match.
        self.write_override(CMD_DYNAMIC, ["dynamic_git_token"],
                            digest=_digest("$GIT status"))
        blocked, err = _evaluate(CMD_DYNAMIC)
        self.assertTrue(blocked, "digest mismatch must not clear the refusal")
        self.assertEqual(self.audit(), [],
                         "a rejected override must not produce an honor record")

    def test_one_appended_byte_breaks_the_binding(self):
        tampered = CMD_DYNAMIC + " ; echo pwned"
        self.prime_refusal(tampered)
        self.write_override(CMD_DYNAMIC, ["dynamic_git_token"])
        blocked, _ = _evaluate(tampered)
        self.assertTrue(blocked,
                        "the binding is to the FULL command text; appending a "
                        "segment must invalidate it")
        self.assertEqual(self.audit(), [])


class D5_OrderingRegression(_RouteCase):
    """The residual check must stay AHEAD of the allowlist.

    `_bash_subcommands` (grant matcher) splits on && || ; | but NOT on `&`;
    `_segments` (residual detector) does split on `&`.  So the single
    grant-matchable subcommand `git status & $GIT push --force origin master`
    has head token `git status` - which a structural sentinel grant matches -
    while carrying an unresolvable `$GIT push --force`.  If the allowlist ran
    first, authority earned for `git status` would be spent on a force-push
    through an unknown binary.
    """

    def test_grant_for_a_benign_head_cannot_launder_a_residual(self):
        def _always_allow(command, data):
            return True

        saved = guard._check_git_allowlist
        guard._check_git_allowlist = _always_allow
        try:
            blocked, err = _evaluate(CMD_LAUNDER)
        finally:
            guard._check_git_allowlist = saved
        self.assertTrue(
            blocked,
            "a matching allowlist grant must NOT clear a residual refusal")
        self.assertIn("could not be statically classified", err)


class D6_NotAGeneralBypass(_RouteCase):
    """Honoring the override clears ONLY the residual refusal.

    Evaluation continues, so everything the guard CAN judge is still judged.
    """

    def test_parseable_force_push_still_blocks_under_an_override(self):
        self.prime_refusal(CMD_MIXED_PUSH)
        self.write_override(CMD_MIXED_PUSH, ["dynamic_git_token"])
        blocked, err = _evaluate(CMD_MIXED_PUSH)
        self.assertTrue(blocked, "the parseable force-push must still block")
        self.assertNotIn(
            "BLOCKED: agent git command could not be statically classified", err,
            "the residual refusal should have been cleared...")
        self.assertIn("RESIDUAL-OVERRIDE HONORED", err,
                      "...and the honor should still have been audited")
        # It blocked for a DIFFERENT, parseable reason - proving the override is
        # not a general bypass.
        self.assertIn(
            "BLOCKED: agent git push", err,
            "expected the block to come from the push policy; got:\n" + err)


class D7_SingleUse(_RouteCase):
    def test_override_is_consumed_at_validation(self):
        self.prime_refusal(CMD_DYNAMIC)
        path = self.write_override(CMD_DYNAMIC, ["dynamic_git_token"])
        blocked, _ = _evaluate(CMD_DYNAMIC)
        self.assertFalse(blocked)
        self.assertFalse(path.exists(), "override must be unlinked on use")
        blocked2, _ = _evaluate(CMD_DYNAMIC)
        self.assertTrue(blocked2, "a second run must be refused again")


class D8_Expiry(_RouteCase):
    def test_expired_override_is_inert(self):
        self.prime_refusal(CMD_DYNAMIC)
        self.write_override(CMD_DYNAMIC, ["dynamic_git_token"], ttl_minutes=-5)
        blocked, _ = _evaluate(CMD_DYNAMIC)
        self.assertTrue(blocked)
        self.assertEqual(self.audit(), [])


class D9_ReasonIsMandatory(_RouteCase):
    def test_override_without_a_reason_is_inert(self):
        self.prime_refusal(CMD_DYNAMIC)
        self.write_override(CMD_DYNAMIC, ["dynamic_git_token"], reason="")
        blocked, _ = _evaluate(CMD_DYNAMIC)
        self.assertTrue(blocked, "an override with no WHY must not be honored")
        self.assertEqual(self.audit(), [])

    def test_override_without_an_authorizer_is_inert(self):
        self.prime_refusal(CMD_DYNAMIC)
        self.write_override(CMD_DYNAMIC, ["dynamic_git_token"], authorized_by="")
        blocked, _ = _evaluate(CMD_DYNAMIC)
        self.assertTrue(blocked, "an override with no WHO must not be honored")
        self.assertEqual(self.audit(), [])


class D10_OriginMarker(_RouteCase):
    def test_override_without_human_origin_marker_is_inert(self):
        self.prime_refusal(CMD_DYNAMIC)
        self.write_override(CMD_DYNAMIC, ["dynamic_git_token"],
                            origin="subagent-selfmint")
        blocked, _ = _evaluate(CMD_DYNAMIC)
        self.assertTrue(blocked)
        self.assertEqual(self.audit(), [])


class D11_KindBinding(_RouteCase):
    def test_override_is_bound_to_the_kinds_it_was_issued_for(self):
        self.prime_refusal(CMD_DYNAMIC)
        # Issued for an obfuscation refusal; spent on a dynamic-expansion one.
        self.write_override(CMD_DYNAMIC, ["obfuscated_git_token"])
        blocked, _ = _evaluate(CMD_DYNAMIC)
        self.assertTrue(blocked, "kind mismatch must not be honored")
        self.assertEqual(self.audit(), [])


class D12_RefusalIsJournaled(_RouteCase):
    def test_every_refusal_is_recorded(self):
        blocked, _ = _evaluate(CMD_OBFUSCATED)
        self.assertTrue(blocked)
        recs = self.journal()
        self.assertEqual(len(recs), 1)
        rec = recs[0]
        self.assertEqual(rec["event"], "residual_refusal")
        self.assertEqual(rec["command_sha256"], _digest(CMD_OBFUSCATED))
        self.assertEqual(rec["residual_kinds"], ["obfuscated_git_token"])
        self.assertEqual(rec["session_id"], "sid-route-test")
        self.assertEqual(rec["agent_id"], "agent-sub-1")
        self.assertTrue(rec["residual_segments"])


class D13_MustAnswerARealRefusal(_RouteCase):
    def test_preemptive_override_is_inert(self):
        # NO priming run: the guard never refused this command.
        self.write_override(CMD_DYNAMIC, ["dynamic_git_token"])
        blocked, err = _evaluate(CMD_DYNAMIC)
        # The evaluation itself journals the refusal, but the override must not
        # be honored on the very run that first records it.
        self.assertTrue(
            blocked,
            "an override may only ANSWER a refusal the guard already emitted; "
            "stderr:\n" + err)
        self.assertEqual(self.audit(), [])


class D14_ResidualRegression(_RouteCase):
    """With no override present, every residual shape still blocks."""

    def test_all_residual_shapes_still_refused(self):
        for cmd in (CMD_DYNAMIC, CMD_OBFUSCATED, CMD_SUBSTITUTED, CMD_LAUNDER,
                    CMD_MIXED_PUSH):
            with self.subTest(cmd=cmd):
                blocked, err = _evaluate(cmd)
                self.assertTrue(blocked, "must still block: %r" % cmd)

    def test_git_free_commands_stay_permissive(self):
        for cmd in ("echo hi", "grep git .", "cat git.md", "ls -la"):
            with self.subTest(cmd=cmd):
                blocked, _ = _evaluate(cmd)
                self.assertFalse(blocked, "must stay permissive: %r" % cmd)


class D15_ClassifierDocstringEscape(unittest.TestCase):
    def test_classifier_compiles_under_syntaxwarning_as_error(self):
        import py_compile
        import warnings
        src = HOOKS_DIR / "lib" / "git_command_classifier.py"
        out = Path(tempfile.mkdtemp(prefix="pyc-", dir=SCRATCH)) / "gcc.pyc"
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            py_compile.compile(str(src), cfile=str(out), doraise=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
