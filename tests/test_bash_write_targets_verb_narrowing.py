"""Regression net for the cp/mv verb readings of hooks/lib/bash_write_targets.py, per consumer.

The library used to read a word that merely begins `cp-`/`mv-` (a checkpoint id such as `cp-01`, a
tool name such as `mv-tool`) and the variable name of a `for`/`select` loop spelled cp or mv as the
copy/move verb, so marking commands such as `spec-check.py mark ... --cp-id cp-01 2>&1` produced a
phantom write target (`2`, `ID`, `cp-09`) that the guards then refused. The reading is narrowed
only where the command segment holds no word that may be the verb; every real copy or move stays
reported, including one whose verb is a quoted expansion (`"$CP"`) inside a `case` arm.

Every test goes through the ENTRY POINT of one consumer, never through the library alone:
  * tool_policy - hooks/pretool-tool-policy.py, run as the real hook process
  * overnight   - hooks/pretool-overnight-hook-guard.py, the six decision functions that consume it
  * overwrite   - hooks/pretool-overwrite-guard.py, `offending_targets` and `--explain`
  * noncaller   - hooks/pretool-cp-state-write-guard.py and hooks/pretool-wrapper-userintent.py, which
                  import the library but never call the extractor and must stay unaffected
Kinds: `no_phantom` (a command that writes nothing yields no target: red on the unmodified library),
`still_detected` (a real copy or move is still refused, destination named: green on the unmodified
library and red on a library that drops detection) and `unchanged`.

The harness under test is read from HARNESS_ROOT_UNDER_TEST (default: the tree this file is in). It
needs `hooks/`, `policies/`, `scripts/` and `settings.json` together. Standard library and pytest
only; nothing is written outside pytest temporary directories.
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("HARNESS_ROOT_UNDER_TEST") or PROJECT).resolve()
HOOKS = ROOT / "hooks"

TOOL_POLICY_HOOK = "pretool-tool-policy.py"
OVERNIGHT_HOOK = "pretool-overnight-hook-guard.py"
OVERWRITE_HOOK = "pretool-overwrite-guard.py"
CP_STATE_GUARD_HOOK = "pretool-cp-state-write-guard.py"
USERINTENT_HOOK = "pretool-wrapper-userintent.py"

DEST = "/srv/data/out"  # outside every ba/qa write prefix and not exempt in the overnight guard
M = "spec-check.py mark --spec-id S --agent ba --agent-id ID"
ROLES = ["ba", "qa"]

# ---- commands that write nothing: no phantom target may come out of them ------------------------
REDIRECT_MARKING = [
    M + " --cp-id cp-01 2>&1 | tail -5",
    M + " --cp-id cp-01 2>&1",
    "spec-check.py mark --spec-id S --agent qa --cp-id cp-01 --agent-id ID 2>&1 | tail -5",
    M + " --cp-id cp-01 --note 'cp done' 2>&1",
    "spec-check.py mark --spec-id S --agent ba --cp-id cp-01 --agent-id ID",
]
DOCUMENTED_MARKING = (
    'source "${CLAUDE_HOME:-$HOME/.claude}/venv/bin/activate" && python3 "${CLAUDE_HOME:-$HOME/.claude}'
    '/scripts/spec-check.py" mark --spec-id S --agent ba --agent-id "$CLAUDE_AGENT_ID" --cp-id cp-01 2>&1 | tail -3'
)
LOOP_MARKING = [
    "for %s in cp-01 cp-02 cp-09; do %s --cp-id $%s; done" % (v, M, v) for v in ("cp", "mv", "id", "c")
] + [
    "for cp in a b c; do echo $cp; done",
    "for mv in a b c; do echo $mv; done",
    "for cp in cp-01 cp-02 cp-09; do %s --cp-id $cp 2>&1 | tail -1; done" % M,
]
TOOL_NAME_WORDS = ["mv-tool src " + DEST, "cp-tool a " + DEST]

# ---- real copies and moves: still reported, destination named -------------------------------------
REAL_PLAIN = [
    "cp src " + DEST, "mv src " + DEST, "/bin/cp src " + DEST,
    "for f in a b; do cp $f " + DEST + "; done",
    "sudo -u for cp a " + DEST, "xargs -I for cp a " + DEST,
]
# a real copy in the same command as a cp-named loop: on the unmodified library the loop's phantom
# word is refused instead of (or before) the destination
BESIDE_REAL = [
    "for cp in a b; do cp x " + DEST + "; done",
    "for cp in cp-01 cp-02; do " + M + " --cp-id $cp; done; mv src " + DEST,
]
REAL_CHECKPOINT_SOURCE = [
    "cp cp-01 " + DEST, "sudo cp cp-01 " + DEST, "cp -r cp-01 " + DEST, "cp -a mv-tool " + DEST,
    "\\cp -R cp-01 " + DEST, M + " --cp-id cp-01 && cp src " + DEST,
]
REAL_ABSOLUTE_QUOTED = [
    "sudo /bin/cp cp-01 " + DEST, "time /bin/cp cp-01 " + DEST, "{ /bin/cp cp-01 " + DEST + "; }",
    "env A=1 /bin/mv mv-tool " + DEST, "sudo -u X /bin/mv mv-tool " + DEST,
    'sudo "cp" cp-01 ' + DEST, "sudo c\\p cp-01 " + DEST,
]
REAL_EXPANSION_SPELLED = [
    "$CP cp-01 " + DEST, "sudo $CP cp-01 " + DEST, "${CP} -r cp-01 " + DEST,
    '"$CP" cp-01 ' + DEST, 'sudo "$CP" cp-01 ' + DEST, 'sudo -u X "$CP" cp-01 ' + DEST,
    'time -p "$CP" cp-01 ' + DEST, 'nice -n 5 "$CP" -r mv-tool ' + DEST, 'env A=1 "$MV" mv-tool ' + DEST,
    "c$X -a cp-01 " + DEST, "sudo /usr/bin/$CMD -a cp-01 " + DEST, 'c"$X" cp-01 ' + DEST,
]
# a real copy or move inside a `case` arm, verb spelled with a quoted expansion (`"$CP"`, `c"$X"`), an
# unquoted expansion or plainly; `@@` is the destination and the second field the overwrite-guard mechanism
CASE_ARM_ROWS = [
    ('case x in x) "${CP}" -r mv-tool @@ ;; esac', "mv-dest"), ('case x in x) "$C$P" -- cp-01 @@ ;; esac', "cp-dest"),
    ('case x in x) c"$X" -- mv-tool @@ ;; esac', "mv-dest"), ('case x in x) "$CP" -r cp-01 @@ ;; esac', "cp-dest"),
    ('case "$V" in x) "$CP" cp-01 @@ ;; esac', "cp-dest"), ('case x in (x) "$CP" cp-01 @@ ;; esac', "cp-dest"),
    ('case x in y) true ;; x) "$MV" mv-tool @@ ;; esac', "mv-dest"),
    ('case x in y) true ;; (x) "$CP" cp-01 @@ ;; esac', "cp-dest"), ('case x in a|b) "$CP" cp-01 @@ ;; esac', "cp-dest"),
    ('if true; then case x in x) "$CP" cp-01 @@ ;; esac; fi', "cp-dest"),
    ("case x in x) $CP -r mv-tool @@ ;; esac", "mv-dest"), ("case x in x) $C$P -- cp-01 @@ ;; esac", "cp-dest"),
    ("case x in x) c$X -- mv-tool @@ ;; esac", "mv-dest"), ("case x in x) cp -r mv-tool @@ ;; esac", "mv-dest"),
    ("case x in x) mv -- cp-01 @@ ;; esac", "mv-dest"), ("case x in x) /bin/cp cp-01 @@ ;; esac", "cp-dest"),
    # `;;`, `;&`, `in` and `case` that do not belong to an arm must not hide a real quoted-expansion verb
    ('# note;;\n"$CP" cp-01 @@', "cp-dest"), ('echo a\\;; "$CP" cp-01 @@', "cp-dest"),
    ('find . -exec ls {} \\;; "$CP" cp-01 @@', "cp-dest"), ('echo in\n"$CP" cp-01 @@', "cp-dest"),
]
REAL_CASE_ARM = [row.replace("@@", DEST) for row, _ in CASE_ARM_ROWS]
# a marking command or a copy-less word inside a case arm writes nothing
CASE_MARKING = [
    "case x in x) " + M + " --cp-id cp-01 2>&1 ;; esac",
    'case "$1" in start) python3 "$SC" mark --spec-id S --agent ba --agent-id "$ID" --cp-id cp-01 2>&1 | tail -3 ;; esac',
    "case x in x) for id in cp-01 cp-09; do echo $id; done ;; esac",
    "case x in y) true ;; (x) " + M + " --cp-id cp-01 2>&1 ;; esac",
    'case "$CP" in x) echo cp-01 ' + DEST + " ;; esac",
]


# ---- consumer 1: the real tool-policy hook process ----------------------------------------------
def _run_policy(role: str, command: str):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "subagent_type": role,
               "agent_id": "a" + role + "verbnarrow", "session_id": "verbnarrow-sess"}
    proc = subprocess.run([sys.executable, str(HOOKS / TOOL_POLICY_HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(PROJECT), timeout=90)
    return proc.returncode, proc.stderr


def _policy_target(stderr: str):
    m = re.search(r"BLOCKED by tool-policy\.v1: (\{.*\})", stderr)
    if not m:
        return None
    try:
        return json.loads(m.group(1)).get("target")
    except ValueError:
        return None


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", REDIRECT_MARKING)
def test_tool_policy_no_phantom_redirect_marking(role, command):
    rc, err = _run_policy(role, command)
    assert rc == 0, "marking command refused for %s with target %r: %r" % (role, _policy_target(err), command)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", LOOP_MARKING)
def test_tool_policy_no_phantom_loop_marking(role, command):
    rc, err = _run_policy(role, command)
    assert rc == 0, "loop refused for %s with target %r: %r" % (role, _policy_target(err), command)


@pytest.mark.parametrize("role", ROLES)
def test_tool_policy_no_phantom_documented_marking_form(role):
    rc, err = _run_policy(role, DOCUMENTED_MARKING)
    assert rc == 0, "documented marking command refused for %s, target %r" % (role, _policy_target(err))


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", TOOL_NAME_WORDS)
def test_tool_policy_no_phantom_tool_name_word(role, command):
    rc, err = _run_policy(role, command)
    assert rc == 0, "a tool name that starts with cp-/mv- was read as the verb: target %r" % _policy_target(err)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", BESIDE_REAL)
def test_tool_policy_no_phantom_beside_real_copy(role, command):
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), "the refused target must be the real destination: %r" % command


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", REAL_PLAIN)
def test_tool_policy_still_detected_real_copy_and_move(role, command):
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), "real copy not refused for %s: %r" % (role, command)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", REAL_CHECKPOINT_SOURCE)
def test_tool_policy_still_detected_checkpoint_source(role, command):
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), "real copy with a cp-/mv- source not refused: %r" % command


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", REAL_ABSOLUTE_QUOTED)
def test_tool_policy_still_detected_absolute_and_quoted_verb(role, command):
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), "absolute or quoted verb not refused: %r" % command


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", REAL_EXPANSION_SPELLED)
def test_tool_policy_still_detected_expansion_spelled_verb(role, command):
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), "expansion-spelled verb not refused: %r" % command


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", CASE_MARKING)
def test_tool_policy_no_phantom_case_arm_marking(role, command):
    rc, err = _run_policy(role, command)
    assert rc == 0, "a case arm that writes nothing was refused for %s, target %r: %r" % (role, _policy_target(err), command)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("command", REAL_CASE_ARM)
def test_tool_policy_still_detected_case_arm_verb(role, command):
    rc, err = _run_policy(role, command)
    assert (rc, _policy_target(err)) == (2, DEST), "real copy in a case arm not refused for %s: %r" % (role, command)


# ---- consumer 2: the overnight guard, six decision functions ------------------------------------
@pytest.fixture(scope="module")
def overnight():
    sys.path.insert(0, str(HOOKS))
    spec = importlib.util.spec_from_file_location("overnight_guard_under_test", HOOKS / OVERNIGHT_HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    granted = "/granted-verbnarrow/x"
    module._grant_skips_block = lambda target: target == granted
    module.GRANTED_FOR_TEST = granted
    return module


WORKTREE = "/nonexistent-worktree-verbnarrow"
MAIN = str(PROJECT)
GIT = os.path.join(MAIN, ".git")


def _call(fn, *args):
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            return "returned", fn(*args), ""
    except SystemExit as exc:
        return "exit", exc.code, " ".join(err.getvalue().split())


def _assert_hook(module, hook_name):
    """The module under test is the intended consumer hook of the harness root under test."""
    assert Path(module.__file__).name == hook_name and Path(module.__file__).parent == HOOKS


def _bash_sites(module):
    return [
        (module._enforce_bash_all_sessions, lambda c: ("Bash", {"command": c}, [WORKTREE])),
        (module._enforce_bash_worktree, lambda c: (c, WORKTREE)),
        (module._check_bash_string, lambda c: ({"command": c}, WORKTREE)),
    ]


@pytest.mark.parametrize("command", REDIRECT_MARKING + [DOCUMENTED_MARKING] + LOOP_MARKING + CASE_MARKING)
def test_overnight_no_phantom_marking_not_blocked(overnight, command):
    _assert_hook(overnight, OVERNIGHT_HOOK)
    for fn, make in _bash_sites(overnight):
        kind, value, text = _call(fn, *make(command))
        assert kind == "returned", "%s blocked a command that writes nothing: %s" % (fn.__name__, text[-120:])


@pytest.mark.parametrize("command", BESIDE_REAL)
def test_overnight_no_phantom_beside_real_copy(overnight, command):
    _assert_hook(overnight, OVERNIGHT_HOOK)
    for fn, make in _bash_sites(overnight):
        kind, value, text = _call(fn, *make(command))
        assert (kind, value) == ("exit", 2) and DEST in text, "%s must name %s for %r: %s" % (fn.__name__, DEST, command, text[-120:])


@pytest.mark.parametrize("command", [M + " --cp-id cp-01 2>&1 | tail -5", "for cp in a b c; do echo $cp; done"])
def test_overnight_no_phantom_grant_and_worktree_local(overnight, command):
    _assert_hook(overnight, OVERNIGHT_HOOK)
    granted = overnight.GRANTED_FOR_TEST
    assert _call(overnight._all_bash_targets_granted, command + " > " + granted)[1] is True
    assert _call(overnight._command_is_worktree_local, command + " > " + granted, MAIN, WORKTREE, GIT)[1] is True
    assert _call(overnight._raw_git_metadata_write_into_main, command, MAIN, WORKTREE, GIT)[1] is False


@pytest.mark.parametrize(
    "command", REAL_PLAIN + REAL_CHECKPOINT_SOURCE + REAL_ABSOLUTE_QUOTED + REAL_EXPANSION_SPELLED + REAL_CASE_ARM)
def test_overnight_still_detected_real_copy_refused(overnight, command):
    _assert_hook(overnight, OVERNIGHT_HOOK)
    for fn, make in _bash_sites(overnight):
        kind, value, text = _call(fn, *make(command))
        assert (kind, value) == ("exit", 2) and DEST in text, "%s did not refuse %r" % (fn.__name__, command)


@pytest.mark.parametrize("command", ["cp src", "cp cp-01", "sudo /bin/cp cp-01", '"$CP" cp-01', "c$X -a cp-01", "mv src"])
def test_overnight_still_detected_main_checkout_and_git_metadata(overnight, command):
    _assert_hook(overnight, OVERNIGHT_HOOK)
    assert _call(overnight._command_is_worktree_local, command + " " + MAIN + "/x", MAIN, WORKTREE, GIT)[1] is False
    assert _call(overnight._raw_git_metadata_write_into_main, command + " " + GIT + "/HEAD", MAIN, WORKTREE, GIT)[1] is True


# ---- consumer 3: the overwrite guard ---------------------------------------------------------------
@pytest.fixture(scope="module")
def overwrite():
    sys.path.insert(0, str(HOOKS))
    spec = importlib.util.spec_from_file_location("overwrite_guard_under_test", HOOKS / OVERWRITE_HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert not module._BOOTSTRAP_ERROR, module._BOOTSTRAP_ERROR
    return module


@pytest.fixture()
def populated(tmp_path):
    for name in ("2", "b", "c", "cp-09", "ID", "dest", "real_dst", "src", "cp-01"):
        (tmp_path / name).write_text("existing")
    return str(tmp_path)


def _explain(command: str, cwd: str) -> str:
    proc = subprocess.run([sys.executable, str(HOOKS / OVERWRITE_HOOK), "--explain", command, cwd],
                          capture_output=True, text=True, timeout=60, cwd=str(PROJECT))
    return proc.stdout


OVERWRITE_NOWRITE = REDIRECT_MARKING[:2] + [
    DOCUMENTED_MARKING, LOOP_MARKING[0], LOOP_MARKING[4], "mv-tool a b", CASE_MARKING[0], CASE_MARKING[2],
    'case "$CP" in x) echo cp-01 real_dst ;; esac',
]
OVERWRITE_BESIDE_REAL = [
    ("for cp in a b c; do cp src real_dst; done", "cp-dest"),
    (M + " --cp-id cp-01 2>&1 | tail -5 && mv src real_dst", "mv-dest"),
]
OVERWRITE_REAL = [
    ("cp src real_dst", "cp-dest"), ("mv src real_dst", "mv-dest"), ("sudo -u for cp src real_dst", "cp-dest"),
    ("cp cp-01 real_dst", "cp-dest"), ("cp -r cp-01 real_dst", "cp-dest"), ("cp -a mv-tool real_dst", "mv-dest"),
    ("sudo /bin/cp cp-01 real_dst", "cp-dest"), ("time /bin/cp cp-01 real_dst", "cp-dest"),
    ("env A=1 /bin/cp cp-01 real_dst", "cp-dest"), ('sudo "cp" cp-01 real_dst', "cp-dest"),
    ("$CP cp-01 real_dst", "cp-dest"), ("sudo $CP cp-01 real_dst", "cp-dest"), ('"$CP" cp-01 real_dst', "cp-dest"),
    ('sudo "$MV" mv-tool real_dst', "mv-dest"), ("c$X -a cp-01 real_dst", "cp-dest"),
    ("sudo /usr/bin/$CMD -a cp-01 real_dst", "cp-dest"), ('time -p "$CP" cp-01 real_dst', "cp-dest"),
] + [(row.replace("@@", "real_dst"), mechanism) for row, mechanism in CASE_ARM_ROWS]


@pytest.mark.parametrize("command", OVERWRITE_NOWRITE)
def test_overwrite_no_phantom_marking_offends_nothing(overwrite, populated, command):
    _assert_hook(overwrite, OVERWRITE_HOOK)
    names = sorted(o["as_written"] for o in overwrite.offending_targets(command, populated))
    assert names == [], "the overwrite guard would refuse a command that writes nothing: %r -> %r" % (command, names)


@pytest.mark.parametrize("command", [REDIRECT_MARKING[0], LOOP_MARKING[0], "for cp in a b c; do echo $cp; done"])
def test_overwrite_no_phantom_explain_shows_no_deny(populated, command):
    out = _explain(command, populated)
    assert "DENY" not in out, "--explain shows a DENY for a command that writes nothing: %r" % out[-160:]


@pytest.mark.parametrize("command,mechanism", OVERWRITE_BESIDE_REAL)
def test_overwrite_no_phantom_beside_real_replacement(overwrite, populated, command, mechanism):
    _assert_hook(overwrite, OVERWRITE_HOOK)
    offenders = overwrite.offending_targets(command, populated)
    assert [(o["as_written"], o["mechanism"]) for o in offenders] == [("real_dst", mechanism)], command


@pytest.mark.parametrize("command", ["for cp in a b; do cp x real_dst; done"])
def test_overwrite_no_phantom_explain_names_only_the_destination(populated, command):
    deny = [line for line in _explain(command, populated).splitlines() if "DENY" in line]
    assert len(deny) == 1 and "real_dst" in deny[0], "--explain should name real_dst once for %r: %r" % (command, deny)


@pytest.mark.parametrize("command,mechanism", OVERWRITE_REAL)
def test_overwrite_still_detected_real_replacement(overwrite, populated, command, mechanism):
    _assert_hook(overwrite, OVERWRITE_HOOK)
    offenders = overwrite.offending_targets(command, populated)
    assert [(o["as_written"], o["mechanism"]) for o in offenders] == [("real_dst", mechanism)], command


@pytest.mark.parametrize("command", ["cp src real_dst", "sudo -u for cp src real_dst", '"$CP" cp-01 real_dst'])
def test_overwrite_still_detected_explain_deny_line(populated, command):
    deny = [line for line in _explain(command, populated).splitlines() if "DENY" in line]
    assert len(deny) == 1 and "real_dst" in deny[0], "--explain should name real_dst once for %r: %r" % (command, deny)


# ---- the two importers that never call the extractor: unaffected by any state of the library ------
def _extractor_calls(tree):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and (
        (isinstance(n.func, ast.Name) and n.func.id == "extract_bash_write_paths")
        or (isinstance(n.func, ast.Attribute) and n.func.attr == "extract_bash_write_paths"))]


def test_noncaller_unchanged_cp_state_write_guard_imports_but_never_calls():
    source = (HOOKS / CP_STATE_GUARD_HOOK).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "lib.bash_write_targets"
               and any(a.name == "extract_bash_write_paths" for a in n.names)]
    assert len(imports) == 1 and _extractor_calls(tree) == [], "the guard must stay import-only"
    for command in REDIRECT_MARKING + [DOCUMENTED_MARKING, "cp src dest", "mv src " + DEST]:
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "subagent_type": "ba",
                   "agent_id": "abaverbnarrow", "session_id": "verbnarrow-sess"}
        proc = subprocess.run([sys.executable, str(HOOKS / CP_STATE_GUARD_HOOK)], input=json.dumps(payload),
                              capture_output=True, text=True, cwd=str(PROJECT), timeout=90)
        assert proc.returncode == 0, "the cp-state guard changed its Bash behaviour for %r" % command
    write = {"tool_name": "Write", "tool_input": {"file_path": str(PROJECT / ".claude" / "specs" / "S-vn" / "cp-state-ba.json"),
                                                    "content": "{}"}, "subagent_type": "ba", "agent_id": "abaverbnarrow",
             "session_id": "verbnarrow-sess"}
    proc = subprocess.run([sys.executable, str(HOOKS / CP_STATE_GUARD_HOOK)], input=json.dumps(write),
                          capture_output=True, text=True, cwd=str(PROJECT), timeout=90)
    assert proc.returncode == 2, "a direct subagent write to a cp-state file must stay denied"


def test_noncaller_unchanged_wrapper_userintent_imports_only_the_heredoc_stripper():
    text = (HOOKS / USERINTENT_HOOK).read_text(encoding="utf-8")
    assert "extract_bash_write" not in text
    assert "from lib.bash_write_targets import command_without_heredoc_bodies" in text
    spec = importlib.util.spec_from_file_location("bwt_for_noncaller", HOOKS / "lib" / "bash_write_targets.py")
    lib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lib)
    assert lib.command_without_heredoc_bodies("cat > /x <<EOF\nbody > /y\nEOF") == "cat > /x <<EOF"
    assert lib.command_without_heredoc_bodies("echo hi") == "echo hi"
