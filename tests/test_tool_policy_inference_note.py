"""Regression tests for lane e (task 20260921-134709): the self-explaining
inference note appended by hooks/pretool-tool-policy.py to a Bash write-target
refusal of the known inference false-positive class.

Self-contained: no import from another test module, no deletion calls. Reads
the hook under test / baseline copy from the environment so the same file
proves the candidate first (P1/P2) and later regresses the live hook (AC1-AC7).

Env:
  TOOL_POLICY_HOOK_UNDER_TEST  -- default hooks/pretool-tool-policy.py
  TOOL_POLICY_BASELINE_HOOK    -- default .claude/dev-registry/dev-20260921-134709/lane-e-baseline/hooks/pretool-tool-policy.py

A missing baseline copy is a hard FAIL (not a skip): every test needs it.
"""

from __future__ import annotations

import ast
import concurrent.futures
import itertools
import json
import os
import re
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HOOK_UNDER_TEST = os.environ.get(
    "TOOL_POLICY_HOOK_UNDER_TEST", "hooks/pretool-tool-policy.py"
)
BASELINE_HOOK = os.environ.get(
    "TOOL_POLICY_BASELINE_HOOK",
    ".claude/dev-registry/dev-20260921-134709/lane-e-baseline/hooks/pretool-tool-policy.py",
)

if not os.path.isfile(os.path.join(REPO_ROOT, BASELINE_HOOK)):
    pytest.fail("baseline hook copy is absent: " + BASELINE_HOOK, pytrace=False)

NOTE_PREFIX = "tool-policy.v1 note: "


# --------------------------------------------------------------------------
# Hook process runner
# --------------------------------------------------------------------------


def run_hook(hook_path, payload):
    """Run one hook as a real subprocess; return (rc, stdout, stderr)."""
    p = subprocess.run(
        [sys.executable, hook_path],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=90,
    )
    return p.returncode, p.stdout, p.stderr


def bash_payload(command, role="ba", agent_id=None, session_id="tp-note-sess"):
    d = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "subagent_type": role,
        "agent_id": agent_id or ("a" + role + "probe"),
        "session_id": session_id,
    }
    return d


def tool_payload(tool_name, path_key, path_value, role="ba", agent_id=None,
                  session_id="tp-note-sess"):
    d = {
        "tool_name": tool_name,
        "tool_input": {path_key: path_value},
        "subagent_type": role,
        "agent_id": agent_id or ("a" + role + "probe"),
        "session_id": session_id,
    }
    return d


def run_pair(command, role="ba", **kw):
    """Run the same Bash payload against baseline and hook-under-test."""
    payload = bash_payload(command, role=role, **kw)
    base = run_hook(BASELINE_HOOK, payload)
    cand = run_hook(HOOK_UNDER_TEST, payload)
    return base, cand


def note_line(stderr):
    """The single note line of a refusal's stderr, or None."""
    lines = stderr.split("\n")
    for line in lines[1:]:
        if line.startswith(NOTE_PREFIX):
            return line
    return None


# --------------------------------------------------------------------------
# Marking-shape grid (>= 30 variants; used by e1 and e7)
# --------------------------------------------------------------------------

_HOME_STYLES = ("$CLAUDE_HOME", "$HOME/.claude", "`echo /root/.claude`", "/root/.claude")
_SUFFIXES = ("", " 2>&1", " 2>&1 | tail -3", " | tail -3", " 2>/dev/null", " >/dev/null 2>&1", " && echo done")


def marking_grid():
    """>= 30 marking-shape command templates (unformatted, no {role})."""
    variants = []
    for home in _HOME_STYLES:
        for quote_id in (False, True):
            for suf in _SUFFIXES:
                cp_id = '"cp-01"' if quote_id else "cp-01"
                variants.append(
                    'python3 ' + home + '/scripts/spec-check.py mark --spec-id S '
                    '--agent {role} --agent-id "$CLAUDE_AGENT_ID" --cp-id ' + cp_id + suf
                )
    return variants


assert len(marking_grid()) >= 30


_REFUSED_CACHE = {}


def discover_refused_marking_shapes():
    """Shapes of the marking grid that BASELINE refuses, per role ba/qa.

    Fails loudly (not vacuously) if a role has fewer than 3 refused shapes --
    per the ticket's edge-case note, if the F3 class is cured by a sibling
    lane's follow-up landing this must be re-measured, not silently ignored.
    """
    if _REFUSED_CACHE:
        return _REFUSED_CACHE
    grid = marking_grid()
    for role in ("ba", "qa"):
        refused = []
        for tmpl in grid:
            cmd = tmpl.format(role=role)
            rc, out, err = run_hook(BASELINE_HOOK, bash_payload(cmd, role=role))
            if rc == 2:
                refused.append((cmd, rc, out, err))
        assert len(refused) >= 3, (
            "role %s: expected >= 3 refused marking shapes on the baseline copy, "
            "found %d -- re-measure (the F3 inference class may have been cured "
            "by a sibling lane's follow-up landing)" % (role, len(refused))
        )
        _REFUSED_CACHE[role] = refused
    return _REFUSED_CACHE


# ==========================================================================
# AC1 -- refused marking shapes carry the note
# ==========================================================================


def test_e1_refused_shapes_rc_and_stdout__pin():
    refused = discover_refused_marking_shapes()
    for role, shapes in refused.items():
        for cmd, base_rc, base_out, base_err in shapes:
            rc, out, err = run_hook(HOOK_UNDER_TEST, bash_payload(cmd, role=role))
            assert rc == 2, (role, cmd, rc)
            assert out == "", (role, cmd, out)


def test_e1_refused_shapes_line1_unchanged__pin():
    refused = discover_refused_marking_shapes()
    for role, shapes in refused.items():
        for cmd, base_rc, base_out, base_err in shapes:
            rc, out, err = run_hook(HOOK_UNDER_TEST, bash_payload(cmd, role=role))
            base_line1 = base_err.split("\n")[0]
            cand_line1 = err.split("\n")[0]
            assert cand_line1 == base_line1, (role, cmd, base_line1, cand_line1)
            assert cand_line1.startswith("BLOCKED by tool-policy.v1: ")


def test_e1_note_present_with_inference_language__change():
    """The note must state INFERRED-ness and must never contain 'BLOCKED by'."""
    refused = discover_refused_marking_shapes()
    seen_any = False
    for role, shapes in refused.items():
        for cmd, base_rc, base_out, base_err in shapes:
            rc, out, err = run_hook(HOOK_UNDER_TEST, bash_payload(cmd, role=role))
            lines = err.split("\n")
            assert len(lines) == 3 and lines[2] == "", (role, cmd, lines)
            nl = lines[1]
            assert nl.startswith(NOTE_PREFIX), (role, cmd, nl)
            assert "INFERRED" in nl
            assert "not an observed file write" in nl
            assert "BLOCKED by" not in nl
            seen_any = True
    assert seen_any


def test_e1_note_target_and_segment_json__change():
    refused = discover_refused_marking_shapes()
    for role, shapes in refused.items():
        for cmd, base_rc, base_out, base_err in shapes:
            rc, out, err = run_hook(HOOK_UNDER_TEST, bash_payload(cmd, role=role))
            nl = note_line(err)
            assert nl is not None, (role, cmd)
            # Recover the two json.dumps'd strings the note embeds.
            m = re.search(
                r"Inferred target: (.*); read from the command segment: (.*)\. If the command",
                nl,
            )
            assert m is not None, nl
            target_json, segment_json = m.group(1), m.group(2)
            target_val = json.loads(target_json)
            segment_val = json.loads(segment_json)
            assert isinstance(target_val, str) and target_val
            assert isinstance(segment_val, str) and segment_val
            # The segment is a (possibly truncated) fragment of the original
            # command -- it must not be an unrelated string.
            stripped_segment = segment_val[:-3] if segment_val.endswith("...") else segment_val
            assert stripped_segment.strip() in cmd or cmd.strip().startswith(stripped_segment.strip())


def test_e1_note_gives_rewording__change():
    """The advice: keep the id LAST, quote it, or drop the trailing redirect
    and pipe; for a real write, use an absolute allowed scratch path."""
    refused = discover_refused_marking_shapes()
    for role, shapes in refused.items():
        for cmd, base_rc, base_out, base_err in shapes:
            rc, out, err = run_hook(HOOK_UNDER_TEST, bash_payload(cmd, role=role))
            nl = note_line(err)
            assert nl is not None
            assert "LAST argument" in nl
            assert "quote" in nl
            assert "trailing redirect" in nl
            assert "absolute allowed scratch path" in nl


# ==========================================================================
# AC2 -- real refusals keep target/deny_reason, add the note
# ==========================================================================

_E2_CASES = [
    ("ba", "echo x > docs/reference/zz-not-allowed.md",
     "docs/reference/zz-not-allowed.md",
     "write target docs/reference/zz-not-allowed.md not in allowed_write_path_prefixes"),
    ("qa", "echo x > /tmp/zz-real-write.txt",
     "/tmp/zz-real-write.txt",
     "write target /tmp/zz-real-write.txt not in allowed_write_path_prefixes"),
    ("dev", "echo x > /tmp/zz-real-write.txt",
     "/tmp/zz-real-write.txt",
     "arbitrary /tmp and /var/tmp are denied for every role; use the managed "
     "scratch namespace .claude/scratch/<session>/<role>/<dispatch>/"),
]

_E2_LONG_CMD = 'echo "' + ("x" * 220) + '" > docs/reference/zz-not-allowed.md'


def test_e2_real_refusals_preserve_fields__pin():
    """line 1 (role/tool/target/deny_reason JSON) is byte-identical to the
    baseline's; the structured deny_reason field is never touched -- the
    prefix-layer deny_reason ("write target <T> not in allowed_write_path_prefixes")
    and the scratch-gate deny_reason ("arbitrary /tmp and /var/tmp are denied
    for every role; ...") both keep flowing to line 1 unchanged."""
    for role, cmd, target, deny_reason in _E2_CASES:
        assert ("not in allowed_write_path_prefixes" in deny_reason
                or "arbitrary /tmp and /var/tmp are denied" in deny_reason)
        base_rc, base_out, base_err = run_hook(BASELINE_HOOK, bash_payload(cmd, role=role))
        rc, out, err = run_hook(HOOK_UNDER_TEST, bash_payload(cmd, role=role))
        assert rc == 2 == base_rc
        assert err.split("\n")[0] == base_err.split("\n")[0]
        assert json.dumps(deny_reason) in err.split("\n")[0]


def test_e2_real_refusals_get_note_with_correct_deny_reason__change():
    """Each site's own deny_reason keeps flowing to line 1 unchanged while an
    additional note line, absent on the baseline, is appended."""
    for role, cmd, target, deny_reason in _E2_CASES:
        base_rc, base_out, base_err = run_hook(BASELINE_HOOK, bash_payload(cmd, role=role))
        rc, out, err = run_hook(HOOK_UNDER_TEST, bash_payload(cmd, role=role))
        assert note_line(base_err) is None
        nl = note_line(err)
        assert nl is not None, (role, cmd)
        assert "INFERRED" in nl


def test_e2_note_carries_correct_target_json__change():
    for role, cmd, target, deny_reason in _E2_CASES:
        rc, out, err = run_hook(HOOK_UNDER_TEST, bash_payload(cmd, role=role))
        nl = note_line(err)
        assert nl is not None
        assert ("Inferred target: " + json.dumps(target)) in nl


def test_e2_long_segment_capped_at_200__change():
    rc, out, err = run_hook(HOOK_UNDER_TEST, bash_payload(_E2_LONG_CMD, role="ba"))
    assert rc == 2
    nl = note_line(err)
    assert nl is not None
    m = re.search(r"read from the command segment: (\".*?\")\. If the command", nl)
    assert m is not None
    segment_val = json.loads(m.group(1))
    assert len(segment_val) <= 203
    assert segment_val.endswith("...")


# ==========================================================================
# AC3 -- allowed / non-Bash / unknown-role / main-agent payloads: unaffected
# ==========================================================================


def test_e3_allowed_bash_no_output__pin():
    """Allowed Bash commands: rc 0, no output at all (unaffected)."""
    docmark = (
        'python3 "${CLAUDE_HOME:-$HOME/.claude}/scripts/spec-check.py" mark '
        '--spec-id S --agent ba --agent-id "$CLAUDE_AGENT_ID" --cp-id cp-01'
    )
    for role in ("ba", "qa", "dev"):
        for cmd in ("echo hi", "ls docs/dev", docmark):
            rc, out, err = run_hook(HOOK_UNDER_TEST, bash_payload(cmd, role=role))
            assert (rc, out, err) == (0, "", ""), (role, cmd, rc, out, err)


def test_e3_non_bash_refusal_unchanged_no_note__pin():
    """A non-Bash (Write tool) refusal never gets a note (D2)."""
    base = run_hook(BASELINE_HOOK, tool_payload("Write", "file_path", "docs/reference/zz-nope.md", role="ba"))
    cand = run_hook(HOOK_UNDER_TEST, tool_payload("Write", "file_path", "docs/reference/zz-nope.md", role="ba"))
    assert cand[0] == 2 == base[0]
    assert cand == base, "no output at all beyond the baseline's single line"


def test_e3_unknown_role_bash_no_note__pin():
    """The Bash tool-list decision for an unknown role (target null) is
    unaffected -- 'unknown role' is refused, but idx == 0 so no note fires."""
    payload = bash_payload("echo hi", role="zzz-unknown-role")
    base = run_hook(BASELINE_HOOK, payload)
    cand = run_hook(HOOK_UNDER_TEST, payload)
    assert base[0] == 2 and cand[0] == 2
    assert "unknown role zzz-unknown-role" in base[2]
    assert cand == base


def test_e3_main_agent_and_unresolved_role_no_output__pin():
    """The main agent and a genuinely unresolved role: rc 0, no output."""
    main_agent_payload = {"tool_name": "Bash", "tool_input": {"command": "echo hi"}}
    unresolved_payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "echo hi"},
        "agent_id": "a-bogus-unregistered-zzz",
        "session_id": "tp-note-sess",
    }
    for payload in (main_agent_payload, unresolved_payload):
        rc, out, err = run_hook(HOOK_UNDER_TEST, payload)
        assert (rc, out, err) == (0, "", ""), "no output expected: %r" % (payload,)


# ==========================================================================
# AC4 -- differential over a >= 600 payload corpus
# ==========================================================================

_ALLOWED_DESTS = ("docs/dev/zz-scratch-note.md", "/dev/null")
_DENIED_DESTS = (
    "docs/reference/zz-not-allowed.md",
    "/tmp/zz-real-write.txt",
    "/var/tmp/zz-real-write.txt",
    "/etc/zz-not-allowed.conf",
)
_ROLES_4 = ("ba", "qa", "dev", "zzz-unknown-role")


def build_corpus():
    """>= 600 distinct payloads: Bash (marking/redirect/cp-mv/no-write/
    multi-segment) and non-Bash tools, across roles, an unknown role, an
    unresolved role and the main agent."""
    bash_cmds = []
    for tmpl in marking_grid():
        bash_cmds.append(tmpl)
    for home in ("$CLAUDE_HOME", "/root/.claude", "`echo /root/.claude`"):
        for quote_id in (False, True):
            for quote_agent in (False, True):
                cid = '"cp-01"' if quote_id else "cp-01"
                aid = '"aprobeqa1"' if quote_agent else "aprobeqa1"
                bash_cmds.append(
                    "python3 " + home + "/scripts/spec-check.py mark --spec-id S "
                    "--agent {role} --cp-id " + cid + " --agent-id " + aid
                )
    for dest in _ALLOWED_DESTS + _DENIED_DESTS:
        for op in (">", ">>", "2>", "&>", ">|"):
            bash_cmds.append("echo x " + op + " " + dest)
        bash_cmds.append("echo x | tee " + dest)
        bash_cmds.append("cat <<EOF > " + dest + "\nhello\nEOF")
    for dest in _ALLOWED_DESTS + _DENIED_DESTS:
        bash_cmds.append("cp src.txt " + dest)
        bash_cmds.append("mv src.txt " + dest)
    for c in ("echo hi", "ls docs/dev", "pwd", "cat docs/dev/README.md",
              "grep -n foo docs/dev/README.md", "whoami", "date", "true",
              "false", ""):
        bash_cmds.append(c)
    joins = [
        "echo hi",
        "echo x > docs/reference/zz-not-allowed.md",
        'python3 $CLAUDE_HOME/scripts/spec-check.py mark --spec-id S --agent {role} '
        '--agent-id "$CLAUDE_AGENT_ID" --cp-id cp-01',
    ]
    for a, b, joiner in itertools.product(joins, joins, (";", "&&", "|")):
        bash_cmds.append(a + " " + joiner + " " + b)

    payloads = []
    seen = set()
    for tmpl in bash_cmds:
        for role in _ROLES_4:
            cmd = tmpl.format(role=role) if "{role}" in tmpl else tmpl
            p = bash_payload(cmd, role=role)
            key = json.dumps(p, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            payloads.append(p)

    non_bash_tools = [
        ("Write", "file_path"), ("Edit", "file_path"), ("MultiEdit", "file_path"),
        ("NotebookEdit", "notebook_path"), ("Read", "file_path"), ("FooTool", "file_path"),
    ]
    non_bash_paths = _ALLOWED_DESTS + _DENIED_DESTS + ("docs/dev/README.md",)
    for (tool, key), path, role in itertools.product(non_bash_tools, non_bash_paths, _ROLES_4):
        p = tool_payload(tool, key, path, role=role)
        k = json.dumps(p, sort_keys=True)
        if k in seen:
            continue
        seen.add(k)
        payloads.append(p)

    # main agent + unresolved role, a handful of each
    for cmd in ("echo hi", "echo x > docs/reference/zz-not-allowed.md"):
        p = {"tool_name": "Bash", "tool_input": {"command": cmd}}
        k = json.dumps(p, sort_keys=True)
        if k not in seen:
            seen.add(k)
            payloads.append(p)
        p2 = {"tool_name": "Bash", "tool_input": {"command": cmd},
              "agent_id": "a-bogus-unregistered-zzz", "session_id": "s"}
        k2 = json.dumps(p2, sort_keys=True)
        if k2 not in seen:
            seen.add(k2)
            payloads.append(p2)

    return payloads


_CORPUS_CACHE = {}


def _run_corpus_pair(payload):
    return payload, run_hook(BASELINE_HOOK, payload), run_hook(HOOK_UNDER_TEST, payload)


def get_corpus_diff_results():
    if _CORPUS_CACHE:
        return _CORPUS_CACHE["corpus"], _CORPUS_CACHE["results"]
    corpus = build_corpus()
    assert len(corpus) >= 600, "corpus too small: %d" % len(corpus)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        for payload, base, cand in pool.map(_run_corpus_pair, corpus):
            results.append((payload, base, cand))
    n_refused = sum(1 for _, base, _ in results if base[0] == 2)
    n_allowed = sum(1 for _, base, _ in results if base[0] == 0)
    assert n_refused >= 100, "need >= 100 refused on baseline, got %d" % n_refused
    assert n_allowed >= 100, "need >= 100 allowed on baseline, got %d" % n_allowed
    _CORPUS_CACHE["corpus"] = corpus
    _CORPUS_CACHE["results"] = results
    return corpus, results


def test_e4_decisions_and_exit_status_identical__pin():
    """Decisions, exit status, line 1 and allowed-silence are identical to
    the baseline over the whole corpus (>= 600 payloads)."""
    corpus, results = get_corpus_diff_results()
    mismatches = []
    for payload, base, cand in results:
        base_rc, base_out, base_err = base
        rc, out, err = cand
        if rc != base_rc or out != base_out:
            mismatches.append((payload, base, cand))
            continue
        if base_rc == 0:
            if err != base_err:
                mismatches.append((payload, base, cand))
        else:
            if err.split("\n")[0] != base_err.split("\n")[0]:
                mismatches.append((payload, base, cand))
    assert not mismatches, "corpus mismatches (showing up to 3): %r" % (mismatches[:3],)


def test_e4_note_only_on_bash_targets__change():
    """The extra note line appears if and only if the tool is Bash and the
    baseline's denied target is not null -- absent on the baseline itself."""
    corpus, results = get_corpus_diff_results()
    checked = 0
    for payload, base, cand in results:
        base_rc, base_out, base_err = base
        rc, out, err = cand
        if base_rc != 2:
            continue
        base_target_is_null = '"target":null' in base_err
        should_have_note = payload.get("tool_name") == "Bash" and not base_target_is_null
        has_note = note_line(err) is not None
        assert note_line(base_err) is None
        assert has_note == should_have_note, (payload, base_err, err)
        checked += 1
    assert checked >= 100


# ==========================================================================
# AC5 -- fault injection end to end (never 0, line 1 already written)
# ==========================================================================

_FAULT_DRIVER = r'''
import sys, json, importlib.util

hook_path = sys.argv[1]
fault = sys.argv[2]

spec = importlib.util.spec_from_file_location("victim_hook_under_fault", hook_path)
victim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(victim)

state = {"guard_active": False}

if fault == "a":
    def _fake_extract(tool_name, tool_input):
        return [None, "docs/reference/zz-not-allowed.md"]
    victim._extract_targets = _fake_extract
elif fault == "b":
    orig_write = sys.stderr.write
    def _flaky_write(s):
        if state["guard_active"]:
            raise RuntimeError("injected stderr.write failure")
        return orig_write(s)
    sys.stderr.write = _flaky_write
    orig_emit = victim._emit_block
    def _wrapped_emit(*a, **kw):
        state["guard_active"] = False
        try:
            return orig_emit(*a, **kw)
        finally:
            state["guard_active"] = True
    victim._emit_block = _wrapped_emit
elif fault == "c":
    orig_dumps = json.dumps
    def _flaky_dumps(*a, **kw):
        if state["guard_active"]:
            raise RuntimeError("injected json.dumps failure")
        return orig_dumps(*a, **kw)
    json.dumps = _flaky_dumps
    victim.json.dumps = _flaky_dumps
    orig_emit = victim._emit_block
    def _wrapped_emit(*a, **kw):
        state["guard_active"] = False
        try:
            return orig_emit(*a, **kw)
        finally:
            state["guard_active"] = True
    victim._emit_block = _wrapped_emit
else:
    raise SystemExit("unknown fault " + repr(fault))

try:
    victim.main()
except SystemExit:
    raise
except Exception as e:
    sys.stderr.write("pretool-tool-policy: unexpected (%s)\n" % (e,))
    sys.exit(0)
'''


def run_fault(hook_path, fault, payload):
    p = subprocess.run(
        [sys.executable, "-c", _FAULT_DRIVER, hook_path, fault],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=90,
    )
    return p.returncode, p.stdout, p.stderr


_FAULT_A_PAYLOAD = {
    "tool_name": "Bash", "tool_input": "not-a-dict",
    "subagent_type": "ba", "agent_id": "aprobe", "session_id": "fault-a",
}
_FAULT_BC_PAYLOAD = bash_payload("echo x > docs/reference/zz-not-allowed.md", role="qa",
                                  session_id="fault-bc")
_EXPECTED_LINE1 = (
    'BLOCKED by tool-policy.v1: '
    + json.dumps(
        {"role": "qa", "tool": "Write", "target": "docs/reference/zz-not-allowed.md",
         "deny_reason": "write target docs/reference/zz-not-allowed.md not in allowed_write_path_prefixes"},
        separators=(",", ":"),
    )
)


def test_e5_fault_a_nondict_tool_input_never_crashes__pin():
    """Fault (a): _extract_targets is forced to hand _check_targets targets
    [None, <denied path>] while data['tool_input'] is a non-dict string --
    the note helper's data.get('tool_input').get('command') would raise
    AttributeError on a str; that must be swallowed, never surface as an
    uncaught SystemExit-bypassing traceback, and the decision stays DENY."""
    for hook in (BASELINE_HOOK, HOOK_UNDER_TEST):
        rc, out, err = run_fault(hook, "a", _FAULT_A_PAYLOAD)
        assert rc == 2, (hook, rc, out, err)
        assert out == ""
        assert "Traceback" not in err
        assert err.split("\n")[0].startswith("BLOCKED by tool-policy.v1: ")


def test_e5_fault_b_stderr_write_failure_after_line1__pin():
    """Fault (b): sys.stderr.write raises for every call once _emit_block's
    own (successful) write has completed -- json.dumps for line 1 must have
    already run and the SystemExit(2) fail-closed decision must not flip to
    a fail open exit 0, even though the note write attempt now raises."""
    for hook in (BASELINE_HOOK, HOOK_UNDER_TEST):
        rc, out, err = run_fault(hook, "b", _FAULT_BC_PAYLOAD)
        assert rc == 2, (hook, rc, out, err)
        assert out == ""
        assert err.split("\n")[0] == _EXPECTED_LINE1


def test_e5_fault_c_json_dumps_failure_after_line1__pin():
    """Fault (c): json.dumps raises for every call after _emit_block's own
    (successful) json.dumps(payload) -- the note's two json.dumps(...) calls
    would raise; that must be swallowed (never an uncaught traceback), and
    the fail-closed sys.exit(2) decision is unaffected (never fail open)."""
    for hook in (BASELINE_HOOK, HOOK_UNDER_TEST):
        rc, out, err = run_fault(hook, "c", _FAULT_BC_PAYLOAD)
        assert rc == 2, (hook, rc, out, err)
        assert out == ""
        assert "Traceback" not in err
        assert err.split("\n")[0] == _EXPECTED_LINE1


# ==========================================================================
# AC6 -- additive-only diff, imports/functions unchanged, call sites wired
# ==========================================================================


def _read(path):
    with open(os.path.join(REPO_ROOT, path), encoding="utf-8") as f:
        return f.read()


def _module_level_imports(src):
    tree = ast.parse(src)
    out = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            out.add(("import", tuple((a.name, a.asname) for a in node.names)))
        elif isinstance(node, ast.ImportFrom):
            out.add(("from", node.module, node.level,
                      tuple((a.name, a.asname) for a in node.names)))
    return out


def _function_source(src, name):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node)
    return None


def _main_guard_source(src):
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.If):
            test = node.test
            if (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
                    and test.left.id == "__name__"):
                return ast.get_source_segment(src, node)
    return None


def test_e6_compiles__pin():
    src = _read(HOOK_UNDER_TEST)
    compile(src, HOOK_UNDER_TEST, "exec")  # must not raise


def test_e6_additive_diff_bounds__pin():
    """additive: no baseline line removed or changed, at most 50 lines added."""
    import difflib

    base_lines = _read(BASELINE_HOOK).splitlines()
    cand_lines = _read(HOOK_UNDER_TEST).splitlines()
    sm = difflib.SequenceMatcher(None, base_lines, cand_lines, autojunk=False)
    added = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        assert tag == "insert", "non-additive diff opcode %r (not additive-only)" % (tag,)
        added += j2 - j1
    assert added <= 50, "added %d lines, budget is 50" % added


def test_e6_module_imports_identical__pin():
    base_imports = _module_level_imports(_read(BASELINE_HOOK))
    cand_imports = _module_level_imports(_read(HOOK_UNDER_TEST))
    assert cand_imports == base_imports, "module-level import set changed"


def test_e6_untouched_functions_byte_identical__pin():
    base_src = _read(BASELINE_HOOK)
    cand_src = _read(HOOK_UNDER_TEST)
    for name in ("_emit_block", "_extract_targets", "main"):
        b = _function_source(base_src, name)
        c = _function_source(cand_src, name)
        assert b is not None and c is not None, name
        assert b == c, "function %s changed" % name
    bg = _main_guard_source(base_src)
    cg = _main_guard_source(cand_src)
    assert bg is not None and cg is not None
    assert bg == cg, "the __main__ guard changed"


def test_e6_check_targets_call_site_follows_emit_block__change():
    """Inside _check_targets, each _emit_block call site is directly
    followed by a call to the new helper, before sys.exit(2)."""
    cand_func = _function_source(_read(HOOK_UNDER_TEST), "_check_targets")
    base_func = _function_source(_read(BASELINE_HOOK), "_check_targets")
    assert cand_func is not None and base_func is not None

    def followups(func_src):
        lines = func_src.splitlines()
        out = []
        for i, line in enumerate(lines):
            if "_emit_block(" in line:
                between = []
                j = i + 1
                while j < len(lines) and "sys.exit(2)" not in lines[j]:
                    s = lines[j].strip()
                    if s:
                        between.append(s)
                    j += 1
                out.append(between)
        return out

    base_followups = followups(base_func)
    cand_followups = followups(cand_func)
    assert len(base_followups) == 2, base_followups
    assert len(cand_followups) == 2, cand_followups
    # baseline: nothing but sys.exit(2) follows each _emit_block call site
    assert all(f == [] for f in base_followups)
    # candidate: an added statement (a call to the new helper) is present
    # at each call site, before sys.exit(2) -- this is the additive wiring.
    for f in cand_followups:
        assert f, "expected an inserted call between _emit_block and sys.exit(2)"
        assert any(re.search(r"\w+\(", line) for line in f), f


# ==========================================================================
# AC7 -- the advice is true (quoting / dropping the redirect actually cure it)
# ==========================================================================


def test_e7_quoting_the_id_cures_every_refused_shape__change():
    refused = discover_refused_marking_shapes()
    for role, shapes in refused.items():
        for cmd, base_rc, base_out, base_err in shapes:
            quoted_cmd = cmd.replace("--cp-id cp-01", '--cp-id "cp-01"')
            assert quoted_cmd != cmd, cmd
            rc, out, err = run_hook(HOOK_UNDER_TEST, bash_payload(quoted_cmd, role=role))
            assert rc == 0 and out == "" and err == "", (role, quoted_cmd, rc, err)
            nl = note_line(run_hook(HOOK_UNDER_TEST, bash_payload(cmd, role=role))[2])
            assert nl is not None and "quote" in nl


def test_e7_dropping_trailing_redirect_cures_every_refused_shape__change():
    refused = discover_refused_marking_shapes()
    for role, shapes in refused.items():
        for cmd, base_rc, base_out, base_err in shapes:
            m = re.search(r"\s*(2>&1|2>/dev/null|>/dev/null 2>&1)(\s*\|[^&]*)?\s*$", cmd)
            if not m:
                continue
            dropped_cmd = cmd[: m.start()]
            rc, out, err = run_hook(HOOK_UNDER_TEST, bash_payload(dropped_cmd, role=role))
            assert rc == 0 and out == "" and err == "", (role, dropped_cmd, rc, err)
            nl = note_line(run_hook(HOOK_UNDER_TEST, bash_payload(cmd, role=role))[2])
            assert nl is not None
            assert "trailing redirect" in nl
            assert "pipe" in nl


def test_e7_no_pipe_only_promise__change():
    """Dropping ONLY the pipe (keeping 2>&1) does NOT cure the refusal; the
    note must not claim that dropping the pipe alone is sufficient."""
    for role in ("ba", "qa"):
        cmd = (
            'python3 $CLAUDE_HOME/scripts/spec-check.py mark --spec-id S '
            '--agent ' + role + ' --agent-id "$CLAUDE_AGENT_ID" --cp-id cp-01 2>&1'
        )
        rc, out, err = run_hook(HOOK_UNDER_TEST, bash_payload(cmd, role=role))
        assert rc == 2, (role, cmd, rc, err)
        assert '"target":"2"' in err.split("\n")[0]
        nl = note_line(err)
        assert nl is not None
        assert "pipe" in nl
        assert "trailing redirect" in nl
        # the note conditions the pipe remedy on ALSO dropping the redirect:
        # it must not read as "drop the pipe" without qualification.
        assert "drop the pipe" not in nl
        assert "and any pipe after it" in nl
