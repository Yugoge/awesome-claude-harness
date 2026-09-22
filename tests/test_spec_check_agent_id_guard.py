"""Pins for blank agent ids and id-less mark/waive resolution in scripts/spec-check.py.

Lane b of task 20260921-134709. Self-contained and subprocess based: one scratch
project per case under tmp_path, CLAUDE_PROJECT_DIR always set explicitly and
CLAUDE_AGENT_ID always removed (subagent shells do not have it). Set
SPEC_CHECK_UNDER_TEST to run the whole file against another copy of the script
(default: scripts/spec-check.py of this repository).

Pinned behavior:
  * a blank agent id (empty, spaces, tab, equals form, non-breaking space) is refused by
    mark, waive, check-in (also with --bump-generation) and check-out with exit 2, empty
    stdout, a message naming cause and self-correction, and a byte-identical tree;
  * the unquoted shell shape fails at argument parsing (exit 2) and names the same cause;
  * an id-less mark/waive is refused (exit 1) when the role has several slot files or its
    only slot file is running for a recorded owner, and keeps the legacy primary-slot
    behavior otherwise; an explicit --instance-id stays allowed;
  * normal ids and spec-<id>-preregister-<role> placeholder ids behave as before.
"""

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SC = os.environ.get("SPEC_CHECK_UNDER_TEST") or str(REPO / "scripts" / "spec-check.py")
SPEC = "20990101-000000"
BLANK_SHAPES = {
    "empty": ["--agent-id", ""],
    "spaces": ["--agent-id", "   "],
    "tab": ["--agent-id", "\t"],
    "equals-form": ["--agent-id="],
    "non-breaking-space": ["--agent-id", "\u00a0"],
}
SUBCOMMANDS = ("mark", "waive", "check-in", "check-out")
CAUSE_TOKENS = ("unset", "claude_agent_id", "slot file", "nothing was written",
                "checked_in_at", "placeholder")
AMBIGUITY_TOKENS = ("--agent-id", "--instance-id", "slot file", "nothing was written",
                    "checked_in_at", "placeholder")
STATE_LETTER = {"p": "pending", "d": "done", "w": "waived-with-reason"}
CLOSED_AT = "2026-09-21T01:00:00Z"


def _env(proj):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(proj)
    env["SC_PATH"] = SC
    env["SC_PY"] = sys.executable
    env.pop("CLAUDE_AGENT_ID", None)
    return env


def run(proj, args):
    p = subprocess.run([sys.executable, SC] + list(args), capture_output=True, text=True,
                       env=_env(proj))
    return p.returncode, p.stdout, p.stderr


def run_shell(proj, command):
    p = subprocess.run(["bash", "-c", command], capture_output=True, text=True, env=_env(proj))
    return p.returncode, p.stdout, p.stderr


def tree(proj):
    """Paths (directories included) mapped to a sha256; catches .lock files and new slots."""
    out = {}
    for root, dirs, files in os.walk(str(proj)):
        for d in dirs:
            out[os.path.relpath(os.path.join(root, d), str(proj)) + "/"] = "dir"
        for f in files:
            fp = os.path.join(root, f)
            with open(fp, "rb") as fh:
                out[os.path.relpath(fp, str(proj))] = hashlib.sha256(fh.read()).hexdigest()
    return out


def mk(proj, role, slots, generation=1):
    """slots: {instance_id or None: (owner, running, checked_out_at, state letters)}."""
    d = Path(str(proj)) / ".claude" / "specs" / SPEC
    d.mkdir(parents=True, exist_ok=True)
    for iid, (owner, running, out_at, letters) in slots.items():
        suffix = "" if iid is None else "-" + str(iid)
        cps = [{"id": "cp-0" + str(i + 1), "action": "x", "state": STATE_LETTER[ch],
                "waived_reason": None, "updated_at": "t"} for i, ch in enumerate(letters)]
        payload = {"spec_id": SPEC, "agent_type": role, "instance_id": iid,
                   "generation": generation, "agent_id": owner, "is_running": running,
                   "checked_in_at": "2026-09-21T00:00:00Z", "checked_out_at": out_at,
                   "checkpoints": cps,
                   "terminal_artifact": {"path": None, "exists": False, "validated_at": None}}
        (d / ("cp-state-" + role + suffix + ".json")).write_text(json.dumps(payload, indent=2))


def slots_of(proj, role="ba"):
    """{file name: (owner, running, state letters)} for every slot file of the role."""
    d = Path(str(proj)) / ".claude" / "specs" / SPEC
    out = {}
    for f in sorted(d.iterdir()):
        if f.name.startswith("cp-state-" + role) and f.name.endswith(".json"):
            j = json.loads(f.read_text())
            out[f.name] = (j["agent_id"], j["is_running"],
                           "".join(c["state"][0] for c in j["checkpoints"]))
    return out


def _without_dir_lock(snapshot):
    """Drop the per-spec-directory `.claude/specs/<SPEC>/.cp-checkin.lock` entry
    from a tree() snapshot. Narrow, evidenced exclusion -- NOT a blanket
    weakening: every other path, including any per-slot cp-state-*.json.lock
    sidecar a write would leave behind, stays covered by the plain
    byte-identical tree() comparison.

    Verified this session (task 20260921-134709, lane b/c reconciliation):
    main() in scripts/spec-check.py takes _spec_dir_lock (an exclusive flock
    on this file) for every mutating subcommand whose spec directory already
    exists on disk, and does so BEFORE dispatching to the handler that runs
    the id-less-ambiguity check (mark/waive) or the ownership check
    (check-out) -- see _lock_plan()/main()'s `with _spec_dir_lock(...):
    return handler(args)`. _locked_file() opens the lock path with O_CREAT
    unconditionally, so the file is created the instant the critical section
    is entered, independent of whether the handler inside it then succeeds or
    refuses. Direct empirical check: a SUCCESSFUL mark and a SUCCESSFUL
    check-out, run against a scratch spec directory built the exact way this
    file's fixtures build one (cp-state JSON written straight to disk, no
    prior spec-check.py invocation), each create this same
    .cp-checkin.lock file too -- so its presence after a refused id-less
    mark/waive or a refused check-out is not conditioned on the refusal
    branch at all; it is the same directory lock ANY first touch of an
    existing spec directory creates. Per _locked_file's own docstring and the
    module docstring's "Concurrency and atomicity" section, nobody is
    responsible for ever removing it: it is "never unlinked or truncated,"
    shared with the read-trigger hook, and released only by closing the file
    descriptor (which drops the flock, including on process death) -- a
    permanent per-spec-directory artifact, not a leak.
    """
    return {k: v for k, v in snapshot.items() if not k.endswith("/.cp-checkin.lock")}


def placeholder(role="ba"):
    return "spec-" + SPEC + "-preregister-" + role


def three(proj, role="ba"):
    """Primary owned by the spec lead's placeholder id, slots 2 and 3 owned by real ids."""
    mk(proj, role, {None: (placeholder(role), True, None, "ppp"), 2: ("AID-2", True, None, "ppp"),
                    3: ("AID-3", True, None, "ppp")})


def single(proj, owner, running, out_at=None, role="ba", letters="ppp"):
    mk(proj, role, {None: (owner, running, out_at, letters)})


def _assert_blank_refusal(rc, out, err, sub):
    assert rc == 2, (rc, err)
    assert out.strip() == "", out
    low = err.lower()
    for tok in ("empty",) + CAUSE_TOKENS + (("slot owner",) if sub == "check-in" else ()):
        assert tok in low, "stderr lacks %r: %r" % (tok, err)


def _blank_call(sub, shape, extra=()):
    args = [sub, "--spec-id", SPEC, "--agent", "ba"] + list(BLANK_SHAPES[shape]) + list(extra)
    if sub in ("mark", "waive"):
        args += ["--cp-id", "cp-01"]
    return args


# ---- blank id: refused by every subcommand, tree byte-identical ------------------------

@pytest.mark.parametrize("shape", list(BLANK_SHAPES))
@pytest.mark.parametrize("sub", SUBCOMMANDS)
def test_blank_agent_id_is_refused_and_writes_nothing(tmp_path, sub, shape):
    three(tmp_path)
    before = tree(tmp_path)
    rc, out, err = run(tmp_path, _blank_call(sub, shape))
    _assert_blank_refusal(rc, out, err, sub)
    assert tree(tmp_path) == before


@pytest.mark.parametrize("shape", ["empty", "spaces", "tab", "equals-form"])
@pytest.mark.parametrize("sub", SUBCOMMANDS)
def test_blank_agent_id_on_empty_project_creates_nothing(tmp_path, sub, shape):
    rc, out, err = run(tmp_path, _blank_call(sub, shape))
    _assert_blank_refusal(rc, out, err, sub)
    assert tree(tmp_path) == {}


@pytest.mark.parametrize("sub", ("mark", "waive"))
def test_blank_agent_id_with_instance_id_is_still_refused(tmp_path, sub):
    three(tmp_path)
    before = tree(tmp_path)
    rc, out, err = run(tmp_path, _blank_call(sub, "empty", ["--instance-id", "2"]))
    _assert_blank_refusal(rc, out, err, sub)
    assert tree(tmp_path) == before


@pytest.mark.parametrize("shape", ["empty", "spaces", "tab", "equals-form"])
@pytest.mark.parametrize("fixture", ["running-owned", "closed"])
def test_blank_check_in_never_stamps_or_allocates(tmp_path, fixture, shape):
    if fixture == "running-owned":
        single(tmp_path, "OWNER-1", True)
    else:
        single(tmp_path, None, False, CLOSED_AT)
    before = tree(tmp_path)
    rc, out, err = run(tmp_path, _blank_call("check-in", shape))
    _assert_blank_refusal(rc, out, err, "check-in")
    assert tree(tmp_path) == before


@pytest.mark.parametrize("shape", ["empty", "spaces", "equals-form"])
def test_blank_check_in_with_bump_generation_moves_nothing(tmp_path, shape):
    mk(tmp_path, "ba", {None: ("OWNER-1", True, None, "dwp")}, generation=3)
    before_tree = tree(tmp_path)
    before_slot = slots_of(tmp_path)
    rc, out, err = run(tmp_path, _blank_call("check-in", shape, ["--bump-generation"]))
    _assert_blank_refusal(rc, out, err, "check-in")
    assert tree(tmp_path) == before_tree
    assert slots_of(tmp_path) == before_slot == {"cp-state-ba.json": ("OWNER-1", True, "dwp")}
    j = json.loads((Path(str(tmp_path)) / ".claude" / "specs" / SPEC / "cp-state-ba.json").read_text())
    assert j["generation"] == 3


# ---- real shell shapes the role documents prescribe --------------------------------------

def _shell(sub, role, tail, quoted):
    idv = '"$CLAUDE_AGENT_ID"' if quoted else "$CLAUDE_AGENT_ID"
    return " ".join(['"$SC_PY"', '"$SC_PATH"', sub, "--spec-id", SPEC, "--agent", role,
                     "--agent-id", idv] + tail)


@pytest.mark.parametrize("sub,role,tail", [
    ("mark", "ba", ["--cp-id", "cp-01"]),
    ("waive", "ba", ["--cp-id", "cp-02"]),
    ("mark", "qa", ["--cp-id", "cp-01"]),
    ("waive", "qa", ["--cp-id", "cp-02"]),
    ("waive", "dev", ["--cp-id", "cp-02"]),
    ("check-in", "ba", []),
    ("check-out", "ba", []),
])
def test_quoted_unset_variable_is_refused_in_every_role(tmp_path, sub, role, tail):
    three(tmp_path, role)
    before = tree(tmp_path)
    rc, out, err = run_shell(tmp_path, _shell(sub, role, tail, True))
    _assert_blank_refusal(rc, out, err, sub)
    assert tree(tmp_path) == before


@pytest.mark.parametrize("sub,tail", [
    ("mark", ["--cp-id", "cp-01"]),
    ("waive", ["--cp-id", "cp-01"]),
    ("check-in", []),
    ("check-out", []),
])
def test_unquoted_unset_variable_fails_parsing_and_names_the_cause(tmp_path, sub, tail):
    three(tmp_path)
    before = tree(tmp_path)
    rc, out, err = run_shell(tmp_path, _shell(sub, "ba", tail, False))
    assert rc == 2, (rc, err)
    assert out.strip() == ""
    low = err.lower()
    for tok in CAUSE_TOKENS:
        assert tok in low, "stderr lacks %r: %r" % (tok, err)
    assert tree(tmp_path) == before


def test_unquoted_unset_variable_as_last_token_names_the_cause(tmp_path):
    three(tmp_path)
    before = tree(tmp_path)
    cmd = " ".join(['"$SC_PY"', '"$SC_PATH"', "mark", "--spec-id", SPEC, "--agent", "ba",
                    "--cp-id", "cp-01", "--agent-id", "$CLAUDE_AGENT_ID"])
    rc, out, err = run_shell(tmp_path, cmd)
    assert rc == 2, (rc, err)
    assert all(tok in err.lower() for tok in CAUSE_TOKENS), err
    assert tree(tmp_path) == before


def test_other_usage_errors_keep_the_plain_argparse_text(tmp_path):
    three(tmp_path)
    rc, out, err = run(tmp_path, ["mark", "--spec-id", SPEC, "--agent", "ba"])
    assert rc == 2
    assert "--cp-id" in err
    assert "unset" not in err.lower()


# ---- id-less mark/waive: refused when the target slot is ambiguous ----------------------

def _f1b(p):
    mk(p, "ba", {None: (None, False, None, "ppp"), 2: ("AID-2", True, None, "ppp")})


def _f2b(p):
    mk(p, "ba", {2: ("AID-2", True, None, "ppp")})


def _la1(p):
    mk(p, "ba", {None: (None, False, None, "ppp"), 2: (None, False, None, "ppp")})


def _la2(p):
    mk(p, "ba", {None: (None, False, CLOSED_AT, "ppp"), 2: (None, False, CLOSED_AT, "ppp")})


def _la3(p):
    mk(p, "ba", {None: (None, True, None, "ppp"), 2: (None, True, None, "ppp")})


# F1, F1b: both limbs (several slot files AND a running owned slot);
# F2, F2b: limb b only (the only slot file is running for a recorded owner);
# La1..La3: limb a only (several slot files, none running for a recorded owner).
AMBIGUOUS_FIXTURES = {
    "F1": three,
    "F1b": _f1b,
    "F2": lambda p: single(p, "OWNER-1", True),
    "F2b": _f2b,
    "La1": _la1,
    "La2": _la2,
    "La3": _la3,
}


@pytest.mark.parametrize("sub", ("mark", "waive"))
@pytest.mark.parametrize("name", list(AMBIGUOUS_FIXTURES))
def test_id_less_call_is_refused_when_the_slot_is_ambiguous(tmp_path, name, sub):
    AMBIGUOUS_FIXTURES[name](tmp_path)
    before = tree(tmp_path)
    rc, out, err = run(tmp_path, [sub, "--spec-id", SPEC, "--agent", "ba", "--cp-id", "cp-01"])
    assert rc == 1, (rc, err)
    assert out.strip() == ""
    low = err.lower()
    for tok in AMBIGUITY_TOKENS:
        assert tok in low, "stderr lacks %r: %r" % (tok, err)
    # The refusal is reached only after main() has already entered the
    # directory-lock critical section (see _without_dir_lock's docstring for
    # the evidence); that lock's file is excluded here and nowhere else.
    assert _without_dir_lock(tree(tmp_path)) == _without_dir_lock(before)


def test_legacy_single_running_slot_without_owner_keeps_the_primary_path(tmp_path):
    single(tmp_path, None, True)
    rc1, _, _ = run(tmp_path, ["mark", "--spec-id", SPEC, "--agent", "ba", "--cp-id", "cp-01"])
    rc2, _, _ = run(tmp_path, ["waive", "--spec-id", SPEC, "--agent", "ba", "--cp-id", "cp-02"])
    assert (rc1, rc2) == (0, 0)
    assert slots_of(tmp_path)["cp-state-ba.json"][2] == "dwp"


def test_legacy_single_idle_never_checked_out_slot_keeps_the_primary_path(tmp_path):
    single(tmp_path, None, False)
    rc, _, _ = run(tmp_path, ["mark", "--spec-id", SPEC, "--agent", "ba", "--cp-id", "cp-01"])
    assert rc == 0
    assert slots_of(tmp_path)["cp-state-ba.json"][2] == "dpp"


def test_explicit_instance_id_without_an_id_stays_allowed(tmp_path):
    three(tmp_path)
    rc, _, _ = run(tmp_path, ["mark", "--spec-id", SPEC, "--agent", "ba", "--instance-id", "2",
                              "--cp-id", "cp-01"])
    assert rc == 0
    assert {k: v[2] for k, v in slots_of(tmp_path).items()} == {
        "cp-state-ba.json": "ppp", "cp-state-ba-2.json": "dpp", "cp-state-ba-3.json": "ppp"}


def test_check_out_without_an_id_keeps_its_own_refusal(tmp_path):
    single(tmp_path, "OWNER-1", True)
    before = tree(tmp_path)
    rc, out, err = run(tmp_path, ["check-out", "--spec-id", SPEC, "--agent", "ba"])
    assert rc == 1
    assert "requires --agent-id" in err
    # Same directory-lock critical section as the id-less mark/waive refusals
    # above (check-out's ownership check also runs inside it); see
    # _without_dir_lock's docstring for the empirical evidence.
    assert _without_dir_lock(tree(tmp_path)) == _without_dir_lock(before)


# ---- normal path and placeholder ids are unchanged ---------------------------------------

@pytest.mark.parametrize("agent_id,slot_file", [
    ("AID-2", "cp-state-ba-2.json"),
    ("AID-3", "cp-state-ba-3.json"),
    (placeholder("ba"), "cp-state-ba.json"),
])
def test_mark_by_owner_changes_only_the_owners_slot(tmp_path, agent_id, slot_file):
    three(tmp_path)
    rc, out, err = run(tmp_path, ["mark", "--spec-id", SPEC, "--agent", "ba", "--agent-id",
                                  agent_id, "--cp-id", "cp-01"])
    assert rc == 0, err
    assert "marked done" in out
    changed = {k for k, v in slots_of(tmp_path).items() if v[2] != "ppp"}
    assert changed == {slot_file}


@pytest.mark.parametrize("agent_id,slot_file", [
    ("AID-2", "cp-state-ba-2.json"),
    (placeholder("ba"), "cp-state-ba.json"),
])
def test_waive_by_owner_changes_only_the_owners_slot(tmp_path, agent_id, slot_file):
    three(tmp_path)
    rc, out, err = run(tmp_path, ["waive", "--spec-id", SPEC, "--agent", "ba", "--agent-id",
                                  agent_id, "--cp-id", "cp-02"])
    assert rc == 0, err
    assert "waived" in out
    states = {k: v[2] for k, v in slots_of(tmp_path).items()}
    assert states.pop(slot_file) == "pwp"
    assert set(states.values()) == {"ppp"}


@pytest.mark.parametrize("agent_id,slot_file", [
    ("AID-3", "cp-state-ba-3.json"),
    (placeholder("ba"), "cp-state-ba.json"),
])
def test_check_out_by_owner_clears_only_the_owners_slot(tmp_path, agent_id, slot_file):
    three(tmp_path)
    rc, out, err = run(tmp_path, ["check-out", "--spec-id", SPEC, "--agent", "ba", "--agent-id",
                                  agent_id])
    assert rc == 0, err
    for name, (owner, running, _letters) in slots_of(tmp_path).items():
        if name == slot_file:
            assert (owner, running) == (None, False)
        else:
            assert running is True and owner is not None


def test_check_in_with_a_placeholder_id_stays_legal(tmp_path):
    rc, out, err = run(tmp_path, ["check-in", "--spec-id", SPEC, "--agent", "ba", "--agent-id",
                                  placeholder("ba")])
    assert rc == 0, err
    assert slots_of(tmp_path)["cp-state-ba.json"][:2] == (placeholder("ba"), True)


def test_check_in_does_not_validate_the_shape_of_a_non_blank_id(tmp_path):
    rc, out, err = run(tmp_path, ["check-in", "--spec-id", SPEC, "--agent", "ba", "--agent-id",
                                  "Any odd id 7"])
    assert rc == 0, err
    assert slots_of(tmp_path)["cp-state-ba.json"][:2] == ("Any odd id 7", True)


@pytest.mark.parametrize("role", ("qa", "dev"))
def test_other_roles_keep_their_normal_path(tmp_path, role):
    three(tmp_path, role)
    rc, out, err = run(tmp_path, ["waive", "--spec-id", SPEC, "--agent", role, "--agent-id",
                                  "AID-3", "--cp-id", "cp-02"])
    assert rc == 0, err
    rc, out, err = run(tmp_path, ["mark", "--spec-id", SPEC, "--agent", role, "--agent-id",
                                  placeholder(role), "--cp-id", "cp-01"])
    assert rc == 0, err
    assert {k: v[2] for k, v in slots_of(tmp_path, role).items()} == {
        "cp-state-%s.json" % role: "dpp", "cp-state-%s-2.json" % role: "ppp",
        "cp-state-%s-3.json" % role: "pwp"}


def test_status_still_needs_no_agent_id(tmp_path):
    three(tmp_path)
    rc, out, err = run(tmp_path, ["status", "--spec-id", SPEC, "--agent", "ba"])
    assert rc == 0, err
    assert "[ba]" in out


# ---- script text ---------------------------------------------------------------------------

def test_script_compiles_and_docstring_pins_the_exit_codes():
    src = Path(SC).read_text(encoding="utf-8")
    compile(src, SC, "exec")
    assert "Exit codes: 0 ok, 1 refused, 2 usage" in (ast.get_docstring(ast.parse(src)) or "")
