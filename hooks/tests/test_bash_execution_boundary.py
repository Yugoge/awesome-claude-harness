"""Unit and end-to-end tests for the fail-closed execution-boundary analyzer.

These cover the properties the 436-case matrix cannot express on its own:

  * the verdict ALGEBRA (precedence, and which verdicts are terminal-safe)
  * the COMPLETENESS obligation — the census is an independent second opinion
    and an undischarged obligation denies
  * the twelve adversarial probes POL-RD-REP-01..12, each a representation the
    six rejected iterations got wrong
  * ANALYZER-FAILURE injections: absent, crashing, malformed-output, wrong
    schema, lying-shape and timing-out analyzers must never authorize a
    removal-suspect command

ZERO EXECUTION: every command string below is data handed to the hook as JSON
stdin. Nothing here runs a fixture or probe command.

Run with: python3 -m pytest hooks/tests/test_bash_execution_boundary.py -v
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "hooks", "lib"))

import bash_active_syntax_census as census_mod  # noqa: E402
import bash_execution_boundary as eb  # noqa: E402

from pol_replay_harness import (  # noqa: E402
    FIXTURE_SHA256, HOOK, fixture_digest, run_hook_command,
)

BLOCK = 2
ALLOW = 0


# ── The algebra itself ───────────────────────────────────────────────────────

class TestVerdictAlgebra:
    def test_precedence_order_is_forbidden_over_unresolved_over_safe(self):
        assert eb._RANK[eb.FORBIDDEN_REMOVAL] > eb._RANK[eb.UNRESOLVED]
        assert eb._RANK[eb.UNRESOLVED] > eb._RANK[eb.PROVEN_SAFE_REMOVAL]
        assert eb._RANK[eb.PROVEN_SAFE_REMOVAL] > eb._RANK[eb.PROVEN_INERT]

    def test_only_proven_verdicts_are_terminal_safe(self):
        assert set(eb._TERMINAL_SAFE) == {eb.PROVEN_INERT, eb.PROVEN_SAFE_REMOVAL}
        assert eb.UNRESOLVED not in eb._TERMINAL_SAFE
        assert eb.FORBIDDEN_REMOVAL not in eb._TERMINAL_SAFE

    def test_unresolved_never_maps_to_allowed(self):
        for command in ("$UNKNOWN qa-mal-12", "bash -c", "env -S", "echo >"):
            result = eb.analyze(command)
            assert result["verdict"] == eb.UNRESOLVED, command
            assert result["allowed"] is False, command

    def test_worst_boundary_decides_the_command(self):
        # A proven-safe removal next to a forbidden one must not be averaged out.
        result = eb.analyze("git rm --cached a.txt; rm b.txt")
        assert result["verdict"] == eb.FORBIDDEN_REMOVAL
        assert result["allowed"] is False

    def test_analyzer_exception_is_reported_as_denial_not_allow(self, monkeypatch):
        monkeypatch.setattr(eb.Analyzer, "analyze_code",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        proc = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "hooks", "lib",
                                          "bash_execution_boundary.py")],
            input="", text=True, capture_output=True,
            env={**os.environ, "CMD_INPUT": "rm x"},
        )
        payload = json.loads(proc.stdout)
        assert payload["allowed"] is False


# ── The completeness obligation ──────────────────────────────────────────────

class TestCompletenessObligation:
    def test_census_does_not_import_the_semantic_analyzer(self):
        source = open(os.path.join(REPO_ROOT, "hooks", "lib",
                                   "bash_active_syntax_census.py"),
                      encoding="utf-8").read()
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not any("bash_execution_boundary" in name for name in imported), (
            "the census must be an independent second opinion, never a summary "
            "of the analyzer's own conclusions (imports: %r)" % sorted(imported))

    def test_census_sees_active_substitutions(self):
        result = census_mod.census('echo "$(rm x)"')
        kinds = {ob["kind"] for ob in result["obligations"]}
        assert census_mod.KIND_SUBSTITUTION in kinds

    def test_census_treats_unbalanced_input_as_fatal(self):
        for command in ("$(rm x", "`rm x", "'rm x", '"rm x', "cat <<EOF\n$(rm x)"):
            assert census_mod.census(command)["fatal"], command

    def test_undischarged_obligation_denies(self, monkeypatch):
        # Simulate a semantic analyzer that silently skips a substitution: the
        # census still reports it, and the mismatch must deny.
        monkeypatch.setattr(eb.Analyzer, "note", lambda self, kind, off: None)
        result = eb.analyze('echo "$(date)"')
        assert result["allowed"] is False
        assert "census_obligation_undischarged" in result["reason"]

    def test_clean_command_discharges_every_obligation(self):
        result = eb.analyze('echo "$(date)" && ls -la')
        assert result["census"]["undischarged"] == []
        assert result["allowed"] is True


# ── The boundary budget must DENY on exhaustion ──────────────────────────────
#
# MAX_BOUNDARIES was a fail-OPEN cliff. ``Analyzer.add`` stops appending once
# the list is full, and finalization then tried to record the overflow marker
# through that very method — so the marker was dropped at exactly the moment it
# decided the outcome, and the ranking loop, seeing only the inert prefix,
# returned PROVEN_INERT. Measured through the hook on this host before the
# repair: 399 inert padding units followed by a filesystem removal exited 2
# (FORBIDDEN_REMOVAL); 400 identical units exited 0 (PROVEN_INERT, allowed);
# 800 likewise. The class was invisible to lane r02 — MAX_BOUNDARIES,
# boundary_limit and overflow appear ZERO times in its QA report — so the
# criteria grow here with it.

_OVERFLOW_REMOVAL = "rm qa-overflow-target.txt"


def _padded_removal(units, tail=_OVERFLOW_REMOVAL):
    """``units`` inert boundaries followed by a filesystem removal. DATA ONLY."""
    return " ; ".join(["echo ok"] * units + ([tail] if tail else []))


class TestBoundaryBudgetExhaustionDenies:
    """Pins the whole neighbourhood of the cap, so an off-by-one cannot re-open
    it, and pins the MECHANISM, so a repair that merely relocates the cliff or
    re-routes the marker to some other recorder does not pass."""

    def test_one_padding_unit_records_one_boundary(self):
        # Anchors the arithmetic every threshold below depends on. If a padding
        # unit ever stops costing exactly one boundary, these thresholds stop
        # straddling the cap and would silently test one side of it twice.
        assert len(eb.analyze("echo ok")["boundaries"]) == 1
        assert eb.analyze(_padded_removal(1))["verdict"] == eb.FORBIDDEN_REMOVAL

    @pytest.mark.parametrize("units", [
        1, 100,
        eb.MAX_BOUNDARIES - 2, eb.MAX_BOUNDARIES - 1,   # just under
        eb.MAX_BOUNDARIES,                              # exactly at
        eb.MAX_BOUNDARIES + 1, eb.MAX_BOUNDARIES * 2,   # well beyond
    ])
    def test_the_removal_denies_on_both_sides_of_the_cap(self, units):
        result = eb.analyze(_padded_removal(units))
        assert result["allowed"] is False, units
        assert result["verdict"] not in eb._TERMINAL_SAFE, units

    def test_just_under_the_cap_still_names_the_removal(self):
        result = eb.analyze(_padded_removal(eb.MAX_BOUNDARIES - 1))
        assert result["verdict"] == eb.FORBIDDEN_REMOVAL
        assert result["reason"].startswith("filesystem_removal")

    def test_at_the_cap_the_exhaustion_itself_denies(self):
        result = eb.analyze(_padded_removal(eb.MAX_BOUNDARIES))
        assert result["verdict"] == eb.UNRESOLVED
        assert result["reason"] == "boundary_limit_exceeded:%d" % eb.MAX_BOUNDARIES

    def test_exhaustion_denies_with_no_removal_present_at_all(self):
        # The unfinished analysis IS the finding. Gating it on removal evidence
        # would leave the same hole for every head the prefix never reached.
        result = eb.analyze(_padded_removal(eb.MAX_BOUNDARIES + 5, tail=None))
        assert result["allowed"] is False
        assert result["reason"].startswith("boundary_limit_exceeded")

    def test_a_full_recorder_refuses_to_record_but_add_terminal_does_not(self):
        # The defect in one assertion: at overflow, ``add`` is unavailable.
        az = eb.Analyzer("qa-overflow-probe")
        for _ in range(eb.MAX_BOUNDARIES):
            az.add(eb.PROVEN_INERT, "pad")
        assert az.overflow is False
        az.add(eb.PROVEN_INERT, "pad")
        assert az.overflow is True
        full = len(az.boundaries)
        az.add(eb.UNRESOLVED, "boundary_limit_exceeded", str(eb.MAX_BOUNDARIES))
        assert len(az.boundaries) == full, "the old path: the marker is dropped"
        az.add_terminal(eb.UNRESOLVED, "boundary_limit_exceeded",
                        str(eb.MAX_BOUNDARIES))
        assert len(az.boundaries) == full + 1, "the repair: the marker survives"

    def test_the_verdict_does_not_depend_on_the_marker_being_recorded(
            self, monkeypatch):
        """The invariant itself, as a test.

        Disable the terminal recorder entirely and exhaustion must STILL deny.
        A repair that only re-routed the overflow marker to a working recorder
        passes every threshold test above and fails this one — which is the
        difference between "the marker happens to be recorded today" and "the
        exhaustion path is decided by something that still functions at the
        bound".
        """
        monkeypatch.setattr(eb.Analyzer, "add_terminal",
                            lambda self, *a, **k: None)
        result = eb.analyze(_padded_removal(eb.MAX_BOUNDARIES))
        assert result["allowed"] is False
        assert result["verdict"] == eb.UNRESOLVED

    def test_raising_the_cap_would_not_have_been_the_repair(self, monkeypatch):
        """A higher cliff is the same defect further out.

        Whatever MAX_BOUNDARIES is set to, one unit past it must deny — so this
        stays true if a future cycle retunes the budget for throughput.

        The cap is SUBSTITUTED at runtime, because sizing only the padding to
        ``cap`` leaves the real cap in force: the short payloads then deny via
        ``filesystem_removal`` and satisfy ``allowed is False`` for a reason
        unrelated to the property, so only the shipped cap would ever reach the
        exhaustion path. Pinning the reason code is what makes each cap prove
        the MECHANISM rather than merely the outcome.
        """
        for cap in (12, 40, 137, eb.MAX_BOUNDARIES):   # last = shipped default
            monkeypatch.setattr(eb, "MAX_BOUNDARIES", cap)
            result = eb.analyze(_padded_removal(cap + 1))
            assert result["allowed"] is False, cap
            assert result["verdict"] == eb.UNRESOLVED, cap
            assert result["reason"] == "boundary_limit_exceeded:%d" % cap, cap

    def test_ordinary_work_is_nowhere_near_the_budget(self):
        # The counterweight: a stricter exhaustion path must not start denying
        # real commands. These are the longest shapes ordinary work produces.
        for command in ("git status && git diff --stat && npm run build",
                        "for f in a b c; do echo $f; done",
                        "cat a.txt | grep -n qa | sort -u | head -20",
                        " && ".join(["echo step%d" % i for i in range(40)])):
            assert len(eb.analyze(command)["boundaries"]) < eb.MAX_BOUNDARIES, \
                command


class TestBoundaryBudgetExhaustionDeniesThroughTheHook:
    """The same thresholds through the SHIPPED decision path.

    The class above runs the analyzer in-process; QA measured the fail-open
    through the hook's JSON-stdin protocol, and that is the path a real Bash
    call takes, so the regression is pinned there too (AC-R02-16 fidelity).
    """

    @pytest.mark.parametrize("units", [
        eb.MAX_BOUNDARIES - 1,      # just under — denied before AND after
        eb.MAX_BOUNDARIES,          # exactly at — the measured fail-open
        eb.MAX_BOUNDARIES + 1,      # one past
        eb.MAX_BOUNDARIES * 2,      # well beyond
    ])
    def test_the_hook_denies_at_and_beyond_the_cap(self, units):
        code, _out, err = run_hook_command(_padded_removal(units))
        assert code == BLOCK, units
        assert err.strip()

    def test_the_hook_denial_at_the_cap_names_the_exhaustion(self):
        code, _out, err = run_hook_command(_padded_removal(eb.MAX_BOUNDARIES))
        assert code == BLOCK
        assert "boundary_limit_exceeded" in err

    def test_the_hook_still_allows_a_long_but_bounded_inert_command(self):
        # Same counterweight at the hook level: length alone must not deny.
        code, _out, err = run_hook_command(
            " ; ".join(["echo ok"] * (eb.MAX_BOUNDARIES - 1)))
        assert code == ALLOW, err


# ── Absence from a table must fall to UNRESOLVED, never to allow ─────────────

class TestTablesOnlyEverProveSafety:
    def test_unknown_wrapper_option_with_removal_evidence_denies(self):
        result = eb.analyze("timeout --no-such-flag 5 /bin/rm x")
        assert result["allowed"] is False

    def test_unknown_git_subcommand_with_removal_evidence_denies(self):
        result = eb.analyze("git -c alias.q='!rm' q target")
        assert result["allowed"] is False

    def test_unmodelled_option_without_removal_evidence_stays_usable(self):
        # Fail-closed is scoped to the removal policy: an unmodelled option on a
        # command with nothing to remove is not this policy's business.
        result = eb.analyze("timeout --no-such-flag 5 ls")
        assert result["allowed"] is True


# ── The twelve adversarial probes (AC-R02-05) ────────────────────────────────
# Each entry is a representation family that some earlier iteration allowed.

PROBES = {
    "POL-RD-REP-01-coproc-body": "coproc QAJOB /bin/rm qa-probe-1",
    "POL-RD-REP-02-plus-O-arity": "bash +O extglob -c '/bin/rm qa-probe-2'",
    "POL-RD-REP-03-flock-c-payload": "flock -n 9 -c '/bin/rm qa-probe-3'",
    "POL-RD-REP-04-parallel-template": "parallel --rpl '{x} s/.//' /bin/rm ::: qa-probe-4",
    "POL-RD-REP-05-git-alias-dispatch": "git -c alias.qawipe='!command /bin/rm' qawipe qa-probe-5",
    "POL-RD-REP-06-container-payload": "docker exec qa-c sh -c '/bin/rm qa-probe-6'",
    "POL-RD-REP-07-generated-code": "python3 -c 'import os; os.system(\"/bin/rm qa-probe-7\")'",
    "POL-RD-REP-08-prompt-reexpansion": "X='$(/bin/rm qa-probe-8)'; echo \"${X@P}\"",
    "POL-RD-REP-09-xargs-abbreviation": "printf qa | xargs --max-p 1 /bin/rm",
    "POL-RD-REP-10-ssh-payload": "ssh qa-host sh -c '/bin/rm qa-probe-10'",
    "POL-RD-REP-11-at-stdin-payload": "at now <<< '/bin/rm qa-probe-11'",
    "POL-RD-REP-12-heredoc-line-joining": "cat <<EOF\n$\\\n(/bin/rm qa-probe-12)\nEOF",
}


class TestAdversarialProbes:
    @pytest.mark.parametrize("probe_id", sorted(PROBES))
    def test_probe_denies_end_to_end(self, probe_id):
        code, _out, err = run_hook_command(PROBES[probe_id])
        assert code == BLOCK, "%s was allowed: %r" % (probe_id, PROBES[probe_id])
        assert err.strip(), "%s denied with an empty reason" % probe_id

    def test_all_twelve_probe_families_are_present(self):
        assert len(PROBES) == 12


# ── Analyzer-failure injections (AC-R02-05, second half) ────────────────────

REMOVAL_SUSPECT = "/bin/rm tracked.txt"

BROKEN_ANALYZERS = {
    "absent": None,
    "crashing": "import sys\nsys.exit(3)\n",
    "raises": "raise RuntimeError('injected analyzer fault')\n",
    "malformed_output": "print('this is not json')\n",
    "wrong_schema": ("import json,sys\n"
                     "json.dump({'schema':'someone-elses.v1','allowed':True,"
                     "'verdict':'PROVEN_INERT'}, sys.stdout)\n"),
    "missing_schema_but_allowing": ("import json,sys\n"
                                    "json.dump({'allowed':True}, sys.stdout)\n"),
    "unknown_verdict_token": ("import json,sys\n"
                              "json.dump({'schema':'bash-execution-boundary.v1',"
                              "'allowed':True,'verdict':'TOTALLY_FINE'}, sys.stdout)\n"),
    "empty_output": "pass\n",
}


def _hook_with_analyzer(tmp_path, body):
    """Copy the hook tree and replace/remove the analyzer. Returns the hook path."""
    dst = tmp_path / "hooks"
    shutil.copytree(os.path.join(REPO_ROOT, "hooks"), str(dst),
                    ignore=shutil.ignore_patterns("tests", "__pycache__"))
    target = dst / "lib" / "bash_execution_boundary.py"
    if body is None:
        if target.exists():
            target.unlink()
    else:
        target.write_text(body, encoding="utf-8")
    return str(dst / "pretool-bash-safety.sh")


class TestAnalyzerFailureFailsClosed:
    @pytest.mark.parametrize("injection", sorted(BROKEN_ANALYZERS))
    def test_broken_analyzer_still_denies_removal_suspect_command(self, tmp_path,
                                                                 injection):
        hook = _hook_with_analyzer(tmp_path, BROKEN_ANALYZERS[injection])
        code, _out, err = run_hook_command(REMOVAL_SUSPECT, hook=hook)
        assert code == BLOCK, "injection %r authorized %r" % (injection, REMOVAL_SUSPECT)
        assert err.strip()

    def test_at_least_three_failure_modes_are_covered(self):
        assert len(BROKEN_ANALYZERS) >= 3

    def test_timing_out_analyzer_denies_removal_suspect_command(self, tmp_path):
        hook = _hook_with_analyzer(tmp_path, "import time\ntime.sleep(30)\n")
        env = dict(os.environ, CLAUDE_HOOK_BOUNDARY_TIMEOUT="1s")
        code, _out, err = run_hook_command(REMOVAL_SUSPECT, hook=hook, env=env)
        assert code == BLOCK
        assert err.strip()

    def test_broken_analyzer_fallback_is_broader_than_the_rule_it_replaced(self,
                                                                          tmp_path):
        # The superseded guard only matched `rm` in command position of the
        # context-stripped view. The degraded fallback must not be narrower.
        hook = _hook_with_analyzer(tmp_path, None)
        for command in ("/bin/rm tracked.txt", "sudo /bin/rm tracked.txt",
                        "echo hi && rm tracked.txt"):
            code, _out, _err = run_hook_command(command, hook=hook)
            assert code == BLOCK, command


# ── Iteration-2: absence must never authorize ────────────────────────────────
#
# QA rejected iteration 1 because the terminal leaf for a named program mapped
# TABLE-ABSENCE to PROVEN_INERT, which is terminal-safe — so absence still
# authorized. Every case below is one QA measured leaking. They are anchored on
# binaries that need no exotic install: `taskset` and `script` are already in
# the analyzer's covered set, and 0x1 / -qc are their canonical documented
# option forms.

# A covered wrapper reached through an argument shape its spec does not model.
COVERED_WRAPPER_LEAKS = [
    "taskset 0x1 rm qa-t1.txt",            # mask operand, not consumed by spec
    "taskset 0x1 /bin/rm qa-t2.txt",
    "taskset 0x1 'rm' qa-t3.txt",          # quoting is not a semantic barrier
    "script -qc 'rm qa-s1.txt' /dev/null",  # clustered short option carries -c
    "script -aqc 'shred qa-s2.txt' /dev/null",
    "script -qc 'unlink qa-s3.txt' /dev/null",
]

# The exec-wrapper family that never appears in any table. QA found 27 of 47
# real installed wrappers passed a literal removal through at exit 0.
UNMODELLED_WRAPPER_LEAKS = [
    "chrt -f 99 rm qa-w1.txt",
    "numactl --physcpubind=0 rm qa-w2.txt",
    "setpriv --reuid=0 rm qa-w3.txt",
    "choom -n 0 rm qa-w4.txt",
    "runcon -t x rm qa-w5.txt",
    "cgexec -g cpu:/ rm qa-w6.txt",
    "proxychains rm qa-w7.txt",
    "torsocks rm qa-w8.txt",
    "systemd-inhibit rm qa-w9.txt",
    "lxc-execute -n c -- rm qa-w10.txt",
    "capsh -- -c 'rm qa-w11.txt'",
    "some-wrapper-that-does-not-exist rm qa-w12.txt",
]

# Removal front ends the policy scope had never named.
NON_RM_REMOVAL_FRONT_ENDS = [
    "unlink qa-u1.txt", "shred -u qa-u2.txt", "srm qa-u3.txt",
    "/usr/bin/unlink qa-u4.txt", "find . -name '*.tmp' -delete",
]

# Interpreter payloads that remove through a library API and so carry no
# rm|unlink|shred|srm TOKEN for a token scan to find.
INTERPRETER_API_REMOVALS = [
    "python3 -c 'import shutil; shutil.rmtree(\"qa-p1\")'",
    "python3 -c 'import os; os.remove(\"qa-p2.txt\")'",
    "node -e 'require(\"fs\").unlinkSync(\"qa-p3.txt\")'",
    "node -e 'fs.rmSync(\"qa-p4\", {recursive: true})'",
    "ruby -e 'File.delete(\"qa-p5.txt\")'",
    "ruby -e 'FileUtils.rm_rf(\"qa-p6\")'",
]

ALL_ITERATION2_LEAKS = (COVERED_WRAPPER_LEAKS + UNMODELLED_WRAPPER_LEAKS
                        + NON_RM_REMOVAL_FRONT_ENDS + INTERPRETER_API_REMOVALS)

# The false-positive control. A stricter default is only correct if ordinary
# work keeps flowing; these must stay ALLOWED.
EVERYDAY_COMMANDS = [
    "ls -la", "git status", "cat README.md", "grep -rn TODO src/",
    "source venv/bin/activate && python script.py",
    "source venv/bin/activate && pytest -q hooks/tests",
    "npm run build", "docker ps -a", "echo hello",
    "git commit -m 'drop rm usage from the helper'",
    "man rm", "which rm", "type -a rm", "command -v rm", "hash rm",
    "grep -F '/bin/rm' README.md", "rg -n 'command /bin/rm' docs",
    "git rm --cached foo.txt", "docker rm my-container",
    "python3 -c 'print(\"/bin/rm is a path\")'",
    "awk 'BEGIN { print \"/bin/rm\" }'",
    "find . -name '*.py' -print", "sha256sum hooks/lib/bash_execution_boundary.py",
    "taskset -c 0 python3 train.py", "nice -n 10 make -j4",
    "chrt -f 99 python3 rt.py", "numactl --physcpubind=0 ./bench",
    "basename /bin/rm", "readlink -f /bin/rm", "stat /bin/rm", "ls -l /bin/rm",
]


class TestAbsenceNeverAuthorizes:
    @pytest.mark.parametrize("command", ALL_ITERATION2_LEAKS)
    def test_unproven_boundary_with_a_removal_reference_denies(self, command):
        result = eb.analyze(command)
        assert result["allowed"] is False, (
            "absence still authorized %r (verdict %s, reason %s)"
            % (command, result["verdict"], result["reason"]))
        assert result["verdict"] in (eb.UNRESOLVED, eb.FORBIDDEN_REMOVAL)

    @pytest.mark.parametrize("command", ALL_ITERATION2_LEAKS)
    def test_the_hook_denies_them_end_to_end(self, command):
        code, _out, err = run_hook_command(command)
        assert code == BLOCK, command
        assert err.strip()

    @pytest.mark.parametrize("command", EVERYDAY_COMMANDS)
    def test_ordinary_work_is_not_collateral_damage(self, command):
        result = eb.analyze(command)
        assert result["allowed"] is True, (
            "false positive on %r (verdict %s, reason %s)"
            % (command, result["verdict"], result["reason"]))

    def test_named_program_leaf_no_longer_defaults_to_terminal_safe(self):
        # The precise defect: a head absent from every table, carrying a
        # removal reference, used to resolve PROVEN_INERT "named_program".
        result = eb.analyze("some-unmodelled-wrapper rm qa-leaf.txt")
        assert result["verdict"] == eb.UNRESOLVED
        assert "unproven_boundary_with_removal_reference" in result["reason"]

    def test_removal_scope_is_shared_with_the_degraded_fallback(self):
        # One definition of "removal binary", so the primary path can never be
        # laxer than the fallback that covers for it.
        assert eb.REMOVAL_EXES == {"rm", "unlink", "shred", "srm"}
        assert set(census_mod.REMOVAL_BINARIES) == eb.REMOVAL_EXES

    def test_inertness_table_only_moves_boundaries_toward_safe(self):
        # Membership proves inertness; ABSENCE must not authorize. Removing a
        # consumer from the table may only make the analyzer stricter.
        assert "grep" in eb.INERT_ARGV_CONSUMERS
        for exe in eb.REMOVAL_EXES:
            assert exe not in eb.INERT_ARGV_CONSUMERS


class TestCensusIsARealBackstop:
    """Must-2: the census must raise obligations the analyzer has to answer."""

    @pytest.mark.parametrize("command", COVERED_WRAPPER_LEAKS
                             + UNMODELLED_WRAPPER_LEAKS)
    def test_every_leaking_form_now_raises_an_obligation(self, command):
        obligations = census_mod.census(command)["obligations"]
        kinds = [o["kind"] for o in obligations]
        assert census_mod.KIND_REMOVAL_REFERENCE in kinds, (
            "census raised no obligation for %r" % command)

    def test_obligations_are_raised_inside_quoted_payloads(self):
        obligations = census_mod.census(
            "script -qc 'rm qa-q.txt' /dev/null")["obligations"]
        offsets = [o["offset"] for o in obligations
                   if o["kind"] == census_mod.KIND_REMOVAL_REFERENCE]
        assert offsets, "quoted command payload raised nothing"

    def test_an_undischarged_obligation_denies_on_its_own(self):
        # Independence check: the backstop must deny even if the analyzer's own
        # leaf logic were to go back to calling this inert.
        command = "taskset 0x1 rm qa-backstop.txt"
        analyzer = eb.Analyzer(command)
        obligations = census_mod.census(command)["obligations"]
        undischarged = [o for o in obligations
                        if (o["kind"], o["offset"]) not in analyzer.discharged]
        assert any(o["kind"] == census_mod.KIND_REMOVAL_REFERENCE
                   for o in undischarged)

    def test_the_census_does_not_import_its_trigger_set_from_the_analyzer(self):
        source = open(os.path.join(REPO_ROOT, "hooks", "lib",
                                   "bash_active_syntax_census.py"),
                      encoding="utf-8").read()
        assert "import bash_execution_boundary" not in source

    @pytest.mark.parametrize("command", EVERYDAY_COMMANDS)
    def test_ordinary_commands_discharge_everything_they_raise(self, command):
        result = eb.analyze(command)
        assert result["census"]["undischarged"] == [], command


class TestInterpreterAndFindActions:
    @pytest.mark.parametrize("command", INTERPRETER_API_REMOVALS)
    def test_library_level_removal_is_not_proven_inert(self, command):
        assert eb.analyze(command)["allowed"] is False, command

    @pytest.mark.parametrize("command", [
        "python3 -c 'print(\"/bin/rm\")'",
        "perl -e 'print q{/bin/rm}'",
        "ruby -e 'puts %q{/bin/rm}'",
        "node -e 'console.log(\"/bin/rm\")'",
        "awk 'BEGIN { print \"/bin/rm\" }'",
    ])
    def test_a_removal_name_inside_an_output_sink_still_flows(self, command):
        assert eb.analyze(command)["allowed"] is True, command

    def test_find_delete_is_a_removal_even_without_a_child_process(self):
        result = eb.analyze("find /tmp -name '*.tmp' -delete")
        assert result["verdict"] == eb.FORBIDDEN_REMOVAL
        assert "find_delete_action" in result["reason"]


class TestNoFailurePathAllows:
    """AC-R02-05: every degraded mode must deny, not just the modelled ones."""

    # Obfuscated command heads carry NO literal removal token, so a fallback
    # that greps for rm|unlink|shred|srm is structurally blind to them. QA
    # measured 23 of 360 dangerous forms allowed under analyzer timeout and
    # under memory starvation for exactly this reason.
    TOKENLESS_DANGEROUS = [
        "R=r; M=m; ${R}${M} qa-d", "R=/bin/r; \"${R}m\" qa-e",
        "$'\\x72m' qa-k", "$'\\u0072\\u006d' qa-l",
        "r${EMPTY}m qa-p", "/bin/r[mp] qa-r", "/bin/r? qa-s",
        "/bin/{r,}m qa-u", "C=r; C+=m; \"$C\" qa-ab",
        "bash -c", "env -S", "echo >", "$UNKNOWN qa-mal-12",
    ]

    @pytest.mark.parametrize("command", TOKENLESS_DANGEROUS)
    @pytest.mark.parametrize("knob,value", [
        ("CLAUDE_HOOK_BOUNDARY_TIMEOUT", "0.001s"),
        ("CLAUDE_HOOK_BOUNDARY_MEM_KB", "4096"),
    ])
    def test_degraded_mode_denies_forms_carrying_no_removal_token(
            self, command, knob, value):
        env = dict(os.environ, **{knob: value})
        code, _out, err = run_hook_command(command, env=env)
        assert code == BLOCK, "%s=%s allowed %r" % (knob, value, command)
        assert err.strip()

    @pytest.mark.parametrize("broken", [
        {"CLAUDE_PYTHON_BIN": "/nonexistent/python",
         "CLAUDE_PYTHON_FALLBACK": "/nonexistent/python3"},
        {"CLAUDE_PYTHON_BIN": "/bin/false", "CLAUDE_PYTHON_FALLBACK": "/bin/false"},
        {"CLAUDE_PYTHON_BIN": "/bin/echo", "CLAUDE_PYTHON_FALLBACK": "/bin/echo"},
    ])
    def test_a_dead_interpreter_does_not_silently_allow_everything(self, broken):
        # With no usable interpreter the payload cannot be parsed at all, so
        # TOOL_NAME came back empty (or echoed garbage) and the non-Bash exit
        # read it as "not a Bash call" and allowed EVERY command in the file.
        env = dict(os.environ, **broken)
        code, _out, err = run_hook_command("rm qa-dead-interpreter.txt", env=env)
        assert code == BLOCK, broken
        assert err.strip()

    @pytest.mark.parametrize("tool_name", ["Read", "Edit", "Write",
                                           "NotebookEdit", "WebFetch"])
    def test_non_bash_tools_are_untouched_when_the_interpreter_is_healthy(
            self, tool_name):
        payload = json.dumps({"tool_name": tool_name,
                              "tool_input": {"file_path": "/tmp/qa.txt"}})
        from pol_replay_harness import run_hook_payload
        code, _out, err = run_hook_payload(payload)
        assert code == ALLOW
        assert err == ""


# ── Fixture immutability ─────────────────────────────────────────────────────

def test_fixture_bytes_are_unchanged():
    assert fixture_digest() == FIXTURE_SHA256


def test_hook_consults_the_analyzer():
    source = open(HOOK, encoding="utf-8").read()
    assert "bash_execution_boundary.py" in source
    assert "bash-execution-boundary.v1" in source
