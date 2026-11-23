"""No code path of the harness moves what an earlier version kept in its old default places; the carry-over is
one explicit step of the install tooling (scripts/install/carry_state.py), which only the configured harness
may run.

The incident behind it: the resolver's first default resolution moved every control entry out of /tmp into the
running checkout's own state root, guarded only by "HOME is the user's own". A copy of the tree run by a test
with the real home took 2,941 entries of the installed harness's state that way.

Safety of these tests: the old control-state directory is a directory of tmp_path, bind-mounted over /tmp inside
a private mount namespace this test starts (``unshare -m``), and HOME, TMPDIR and every state variable name
directories of tmp_path. A sitecustomize on PYTHONPATH makes the passwd home equal that throwaway HOME, so the
old guard ("HOME is the user's own") would have let a move run: the test is red against the old code. Without
a private namespace (made as root, else a user namespace, else passwordless sudo, as on CI:
hooks/tests/_private_ns.py) the hook case is skipped, and fails so on GitHub Actions; never run against the real /tmp.
"""
from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
LIB = HOOKS / "lib"
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(ROOT / "scripts" / "install"))
import harness_temp_state as hts  # noqa: E402
sys.path.insert(0, str(ROOT / "hooks" / "tests"))
import _private_ns  # noqa: E402

SID = "sid-no-move"
SENTINEL = ".sentinel-no-move"
SITE = '''import os, pwd
_get = pwd.getpwuid
def _own(uid, _get=_get):
    p = _get(uid)
    return pwd.struct_passwd((p.pw_name, p.pw_passwd, p.pw_uid, p.pw_gid, p.pw_gecos,
                              os.environ.get("HOME", p.pw_dir), p.pw_shell))
pwd.getpwuid = _own
'''


def inventoried_old_entries() -> dict:
    """One entry of every control kind the earlier version kept directly in /tmp."""
    out = {}
    for loc in hts.LOCATIONS:
        if loc.kind != hts.CONTROL or loc.name in hts.NOT_IN_STATE_DIR:
            continue
        for pat in loc.patterns:
            if len(pat) != 1:
                continue
            name = pat[0].replace("*", f"x-{SID}")
            out[f"{name}/e.json" if loc.tree else name] = f'{{"kind": "{loc.name}"}}'
    return out


FOREIGN = {"notes.txt": "mine", "claude-0/x/tasks/a.output": "out", "claude-scratch/qa/r.txt": "r"}
RECORDS = {"logs/lifecycle.jsonl": '{"row": 1}\n{"row": 2}\n', "restart-state/sends/s.json": "{}",
           f"restart-state/claude-restart-{SID}.json": '{"wave": 1}', "logs/landing.log": "other"}


def populate(old: Path, records: Path) -> None:
    for base, entries in ((old, {**inventoried_old_entries(), **FOREIGN, SENTINEL: ""}), (records, RECORDS)):
        for rel, text in entries.items():
            (base / rel).parent.mkdir(parents=True, exist_ok=True)
            (base / rel).write_text(text)
            os.utime(base / rel, (1_700_000_000, 1_700_000_000))
    (old / f"claude-tool-streak-linked-{SID}.json").symlink_to(old / "notes.txt")


def snapshot(base: Path) -> dict:
    out = {}
    for dirpath, dirnames, filenames in os.walk(base):
        for name in dirnames + filenames:
            path = Path(dirpath, name)
            rel = str(path.relative_to(base))
            st = path.lstat()
            if path.is_symlink():
                out[rel] = ("link", os.readlink(path))
            elif path.is_dir():
                out[rel] = ("dir", st.st_mode)
            else:
                out[rel] = ("file", st.st_mode, st.st_mtime, hashlib.sha256(path.read_bytes()).hexdigest())
    return out


def records_snapshot(records: Path) -> dict:
    """The earlier version's score log and restart state in its configuration directory (other files there,
    such as a cache a hook keeps in the configuration directory, are not old state)."""
    return {sub: snapshot(records / sub) for sub in ("logs", "restart-state")}


PROBE = r'''
import importlib, json, sys
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[1] + "/lib")
out = {}
for name in ("harness_state_dir", "harness_temp_state", "score_log", "subagent_restart", "refusal_record",
             "allowlist", "capability_state", "report_provenance", "commit_journal", "merge_grant"):
    try:
        mod = importlib.import_module(name)
        out[name] = "imported"
    except Exception as exc:  # a module that cannot import here is reported, not hidden
        out[name] = f"import failed: {type(exc).__name__}"
import harness_state_dir, score_log, subagent_restart
out["state"] = harness_state_dir.harness_state_dir()
out["log"] = str(score_log.log_path()); out["restart"] = str(subagent_restart.state_dir())
print(json.dumps(out))
'''

# Hook entry points registered in settings.json that read or write control state, each with one payload.
# Left out, by design: the Stop launcher (it runs the landing, which works on the harness home's own git
# repository and git-fswatch daemons), and the SessionStart/PostToolUse hooks that run git in the project.
ENTRY_POINTS = [
    ("pretool-launch.py", {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "true"}}),
    ("posttool-launch.py", {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "true"},
                            "tool_response": {"stdout": ""}}),
    ("posttool-failure-launch.py", {"hook_event_name": "PostToolUseFailure", "tool_name": "Bash",
                                    "tool_input": {"command": "true"}, "error": "x"}),
    ("userprompt-launch.py", {"hook_event_name": "UserPromptSubmit", "prompt": "hello"}),
    ("sessionstart-launch.py", {"hook_event_name": "SessionStart", "source": "startup"}),
    ("subagentstart-launch.py", {"hook_event_name": "SubagentStart", "agent_id": "a1", "agent_type": "qa"}),
    ("subagentstop-producer-gate.py", {"hook_event_name": "SubagentStop", "agent_id": "a1", "agent_type": "qa"}),
    ("permissionrequest-launch.py", {"hook_event_name": "PermissionRequest", "tool_name": "Bash",
                                     "tool_input": {"command": "true"}}),
    ("userprompt-consent-allowlist.sh", {"hook_event_name": "UserPromptSubmit", "prompt": "hello"}),
    ("userprompt-harness-switch.sh", {"hook_event_name": "UserPromptSubmit", "prompt": "hello"}),
    ("userprompt-tmpfs-pressure.sh", {"hook_event_name": "UserPromptSubmit", "prompt": "hello"}),
    ("session-scratch-init.sh", {"hook_event_name": "SessionStart", "source": "startup"}),
    ("session-tmpfs-banner.sh", {"hook_event_name": "SessionStart", "source": "startup"}),
    ("session-info.sh", {"hook_event_name": "SessionStart", "source": "startup"}),
]


@pytest.fixture
def sandbox(tmp_path):
    box = {k: tmp_path / k for k in ("home", "old", "tmpdir", "work", "site")}
    for d in box.values():
        d.mkdir()
    (box["site"] / "sitecustomize.py").write_text(SITE)
    box["records"] = box["home"] / ".claude"  # the earlier version's ~/.claude/logs and ~/.claude/restart-state
    populate(box["old"], box["records"])
    return box


def _env(box) -> dict:
    keep = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL") if k in os.environ}
    return {**keep, "HOME": str(box["home"]), "TMPDIR": str(box["tmpdir"]), "PYTHONPATH": str(box["site"]),
            "PYTHONDONTWRITEBYTECODE": "1", "CLAUDE_PROJECT_DIR": str(box["work"]),
            "CLAUDE_CODE_TMPDIR": str(box["tmpdir"]),
            "CLAUDE_PYTHON_BIN": sys.executable, "PYTHON_BIN": sys.executable}


def _alias_base() -> str:
    """A directory of the namespace to put the alias tmpfs over: one that hides nothing this run reads, so the
    checkout and the interpreter may lie under any of them (a runner may keep its checkout under /mnt)."""
    used = [os.path.realpath(p) for p in (HOOKS, sys.executable, sys.prefix, sys.base_prefix, os.__file__)]
    for cand in ("/mnt", "/media", "/srv", "/opt", pwd.getpwuid(os.getuid()).pw_dir):  # the last: computed
        if os.path.isdir(cand) and not any(u == cand or u.startswith(cand + "/") for u in used):
            return cand
    pytest.fail("no directory to put the alias over that hides nothing this run needs")


def test_no_import_and_no_hook_moves_anything_out_of_the_old_places(sandbox):
    box = sandbox
    old_before, rec_before = snapshot(box["old"]), records_snapshot(box["records"])
    assert len(inventoried_old_entries()) >= 25  # every kind is there, not a token few
    runs = ""
    for i, (hook, payload) in enumerate(ENTRY_POINTS):
        payload = {**payload, "session_id": SID, "cwd": str(box["work"]), "tool_use_id": f"toolu_{i}"}
        runner = sys.executable if hook.endswith(".py") else "bash"
        runs += (f"printf '%s' {shlex.quote(json.dumps(payload))} | timeout 60 {runner} \"{HOOKS / hook}\" "
                 f">/dev/null 2>&1; echo \"{hook}=$?\"\n")
    # The box (tmp_path) is reached at a fixed alias on a tmpfs of the namespace, bound from a descriptor opened
    # before any mount, so the stand-in over /tmp never hides it wherever pytest's temp lies (under /tmp on CI).
    real, mnt = os.path.realpath(box["home"].parent), _alias_base()
    alias = f"{mnt}/.no-move-box"
    script = (f'exec 3<"{real}"; mount -t tmpfs none {mnt} || exit 97\n'
              f'mkdir {alias} && mount -c --bind /proc/self/fd/3 {alias} || exit 97; exec 3<&-\n'
              f'mount --bind "{box["old"]}" /tmp || exit 97\n'
              f'[ -e /tmp/{SENTINEL} ] || exit 98\n'
              f'cd "{box["work"]}" || exit 99\n'
              f'"{sys.executable}" -c "$PROBE" "{HOOKS}"\n'
              f'bash -c \'. "{LIB / "harness_state_dir.sh"}"; harness_state_dir\'\n' + runs)
    way = _private_ns.require("the no-move case")  # never run against the real /tmp
    script = script.replace(str(box["home"].parent), real).replace(real + "/", alias + "/")
    env = {k: v.replace(str(box["home"].parent), real).replace(real + "/", alias + "/") for k, v in _env(box).items()}
    proc = subprocess.run(_private_ns.unshare_argv(way, {**env, "PROBE": PROBE}, ["bash", "-c", script]),
                          text=True, capture_output=True, timeout=1200)
    assert proc.returncode not in (97, 98, 99), proc.stdout + proc.stderr  # the stand-in really was /tmp
    assert proc.stdout.startswith("{"), proc.stdout + proc.stderr  # the probe printed its result first
    probe = json.loads(proc.stdout.splitlines()[0])
    assert probe["state"].startswith(env["HOME"]), probe  # the resolvers ran against the throwaway home
    assert snapshot(box["old"]) == old_before, proc.stdout
    assert records_snapshot(box["records"]) == rec_before, proc.stdout


# ------------------------------------------------------------------------------------- the explicit step
@pytest.fixture
def configured(sandbox, monkeypatch):
    """The user's configuration points to this tree (the harness running the step), with a throwaway home."""
    monkeypatch.setenv("HOME", str(sandbox["home"]))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(ROOT))
    for var in ("CLAUDE_STATE_DIR", "CLAUDE_RESTART_STATE_DIR"):
        monkeypatch.delenv(var, raising=False)
    import carry_state
    return sandbox, carry_state


def test_the_explicit_step_carries_every_kind_once_and_leaves_the_rest(configured):
    box, cs = configured
    import harness_state_dir as hsd
    import score_log
    import subagent_restart
    state, log, restart = Path(hsd.harness_state_dir()), score_log.log_path(), subagent_restart.state_dir()
    assert str(state).startswith(str(box["home"])) and str(log).startswith(str(box["home"]))
    newer = f"claude-tool-streak-x-{SID}.json"
    state.mkdir(parents=True, exist_ok=True)
    (state / newer).write_text("newer")  # written by the new version after the old one: it wins
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text('{"row": 2}\n{"row": 3}\n')  # rows the new version wrote; row 2 is in both

    out = cs.carry_over(old_state_root=str(box["old"]), old_records=str(box["records"]))
    entries = inventoried_old_entries()
    for rel, text in entries.items():
        if rel == newer:
            assert (state / rel).read_text() == "newer" and (box["old"] / rel).exists()
            continue
        assert (state / rel).read_text() == text and not (box["old"] / rel).exists(), rel
        assert (state / rel).stat().st_mtime == 1_700_000_000, rel  # stamps and TTLs read the time
    assert f"state/{newer}" in out["kept_newer"]
    for rel, text in FOREIGN.items():
        assert (box["old"] / rel).read_text() == text, rel
    assert (box["old"] / f"claude-tool-streak-linked-{SID}.json").is_symlink()
    assert (restart / "sends" / "s.json").exists() and (restart / f"claude-restart-{SID}.json").exists()
    assert log.read_text() == '{"row": 1}\n{"row": 2}\n{"row": 3}\n'
    assert not (box["records"] / "logs" / "lifecycle.jsonl").exists()
    assert (box["records"] / "logs" / "landing.log").read_text() == "other"  # not the harness's to carry

    after = (snapshot(box["old"]), snapshot(state), snapshot(restart), log.read_text())
    again = cs.carry_over(old_state_root=str(box["old"]), old_records=str(box["records"]))
    assert again["carried"] == [] and (snapshot(box["old"]), snapshot(state), snapshot(restart), log.read_text()) == after


def test_the_explicit_step_refuses_when_the_running_code_is_not_the_configured_harness(configured, monkeypatch):
    box, cs = configured
    elsewhere = box["home"] / "installed"
    elsewhere.mkdir()
    (elsewhere / "settings.json").write_text("{}")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(elsewhere))
    before = snapshot(box["old"]), snapshot(box["records"])
    with pytest.raises(cs.NotTheConfiguredHarness):
        cs.carry_over(old_state_root=str(box["old"]), old_records=str(box["records"]))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")  # ~/.claude of the throwaway home is not this tree either
    with pytest.raises(cs.NotTheConfiguredHarness):
        cs.carry_over(old_state_root=str(box["old"]), old_records=str(box["records"]))
    assert (snapshot(box["old"]), snapshot(box["records"])) == before
    assert not (box["home"] / ".local").exists()


CALL = re.compile(r"carry_over\(|import carry_state|from carry_state|python3?\S*\s+\S*carry_state\.py|move_old_state")


def test_nothing_calls_the_explicit_step():
    callers = []
    for path in list(ROOT.glob("hooks/**/*")) + list(ROOT.glob("scripts/**/*")) + list(ROOT.glob("commands/*")):
        if path.is_file() and path.suffix != ".pyc" and "/tests/" not in path.as_posix() and path.name != "carry_state.py":
            text = path.read_text(errors="ignore")
            if CALL.search(text):
                callers.append(str(path.relative_to(ROOT)))
    assert callers == []
