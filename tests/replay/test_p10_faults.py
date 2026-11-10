"""P10 A25 (D25): the fault replays for the process classes P10 changes, and the product repository
the compliant pipelines leave.

Stub registrations (P10 R1-R3). A harness home landed by init (tests/replay/test_regressions.py's
`_landed_harness_home`: a clone of a bare origin holding the tree under test, the CLI's writes plain
file writes, a Stop the registered Stop hook, whose auto_commit phase runs the landing) is upgraded
the way P10 reached it: a revision that still tracks a harness hook P10 deleted
(hooks/pretool-overwrite-guard.py, R4, its content from this checkout's history), whose overlay the
owner had register that hook and a stub HEAD tracks (hooks/stop-completion-gate.py, `# STUB:`),
beside a registration of his own; then /pull (hooks/pull.sh) brings the deletion.
  * The landing is the overlay's producer: `render-settings check` fails on both (the stub named, the
    deleted file, which HEAD does not track, counted under its event: R1 echoes no possibly personal
    path); the next Stop repairs the overlay (both dropped, the rest of it byte for byte as it was, mode 0600), the
    working settings.json loses the same commands, check passes, logs/landing.log gets counts only,
    the home's `git status --porcelain` stays empty, and a second Stop does nothing. No human action.
  * The migration is the producer of a new overlay: init's `--migrate-from` over the same previous
    settings does not carry the two commands (named by event and count, never by text) and carries
    the owner's own.
  * A session whose loaded hook list names the stubs passes: /dev singular with the tree's
    settings.json plus, for each `# STUB:` harness hook (read from the tree) it does not register,
    the registration the newest settings.json in this checkout's history gave it (BUILT_SETTINGS
    "stubs-shipped", "stubs-armed"): 0 blocks, 0 hook errors, the terminal reached, every stub whose
    event fired run with exit 0.

`git rm` (P10 R13, R14; tests/replay/removal.py), each in /dev singular's dev subagent before it
writes its report, shipped and armed:
  * recoverable: the dev's `git rm -- toy/util.py` (a file as HEAD has it) runs, its DISCARDED line's
    own recover command (`git checkout <sha> -- toy/util.py`) puts back the file and its index entry;
    `git rm -- toy/__init__.py` after the dev's edit is let through by the hooks and refused by git, the
    file staying with the dev's change. No block, no hook error, the dev's stop passes, the terminal
    is reached.
  * refused, forced: the dev's `git rm -f -- README.md` is refused at PreToolUse by the removal policy,
    changing nothing; the refusal names a recoverable `git rm` without -f, the dev's next call is that
    one and it runs, its DISCARDED line's recover command puts the file back. The one block of the
    run is that call's; the dev's own stop passes and no human event follows.

A product repository left clean after the pipelines (P10's goal and R8, A11's checks; read from
endstate.json, which every untraced replay writes: tests/replay/endstate.py), over each compliant
scenario of suite.COMPLIANT in both settings (the replays test_pipelines.py reads): the tracked
.gitignore is HEAD's at the start, byte for byte; every harness runtime path under .claude/ is
ignored through `.git/info/exclude`, which holds one line per harness-owned .claude/ directory and
ignores no docs/ path; in `git status --porcelain`, the only file under .claude/ no actor Wrote is the
bookmark of a session the replay left open (`.claude/workflow-<session>.json`, which that session's
SessionEnd sweep removes), a session the replay ended left none, and every entry elsewhere is a cycle
artifact the pipeline's own tool calls name (input or result: a deliverable /commit can stage), never
a file only a process behind them left; after /commit and /push nothing of the cycle is left.

REPLAY_WORK keeps the replays; each test prints its row of the A25 fault table.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys

import pytest

from tests.replay import endstate, sandbox, suite
from tests.replay import test_faults as tf
from tests.replay.test_regressions import (TREE_UNDER_TEST, _harness_stop, _home_pull, _home_upstream_commit,
                                           _landed_harness_home, _landing_result)
from tests.test_landing import env, git, landing_log, run  # noqa: F401  (env: the scratch-HOME fixture)

DELETED = "hooks/pretool-overwrite-guard.py"  # a harness hook P10 R4 deleted (whole, with its tests)
STUB = "hooks/stop-completion-gate.py"  # a `# STUB:` file HEAD tracks, which the clean form does not register
OWN = "hooks/session-info.sh"  # a live harness hook, registered by the owner at an event nothing runs it at
OVERLAY = "settings.machine.json"


def _row(**cells) -> None:
    print("A25 | " + " | ".join(f"{k}: {v}" for k, v in cells.items()), flush=True)


# ---------------------------------------------------------------- stub registrations: the landing

def _deleted_hook_text() -> str:
    """DELETED as this checkout's history last tracked it."""
    rev = subprocess.run(["git", "-C", str(TREE_UNDER_TEST), "rev-list", "-n1", "--full-history", "--no-merges",
                          "HEAD", "--", DELETED], capture_output=True, text=True).stdout.strip()
    assert rev, f"this checkout's history does not hold {DELETED} (CI fetches it whole)"
    for spec in (f"{rev}:{DELETED}", f"{rev}^:{DELETED}"):
        p = subprocess.run(["git", "-C", str(TREE_UNDER_TEST), "show", spec], capture_output=True, text=True)
        if p.returncode == 0:
            return p.stdout
    raise AssertionError(f"no blob of {DELETED} at {rev} or its parent")


def _command(kind: str, home, rel: str) -> dict:
    return {"type": "command", "command": f'{kind} "{home}/{rel}"'}


def _registrations(home) -> dict:
    """The owner's overlay hooks: the deleted hook and the stub, and one registration of his own."""
    return {"PreToolUse": [{"matcher": "Write|Edit|MultiEdit", "hooks": [_command("python3", home, DELETED)]}],
            "Stop": [{"hooks": [_command("python3", home, STUB)]}],
            "Notification": [{"matcher": "idle_prompt", "hooks": [_command("bash", home, OWN)]}]}


def _check(env, home) -> tuple:
    """(exit status, the hook paths line and the lines under it) of `render-settings check`."""
    p = run([sys.executable, str(home / "scripts/install/render-settings"), "check"], env, cwd=str(home),
            check=False)
    lines = p.stdout.splitlines()
    at = next((i for i, ln in enumerate(lines) if " hook paths: " in ln), None)
    assert at is not None, p.stdout + p.stderr
    under = []
    for ln in lines[at + 1:]:
        if not ln.startswith("       "):
            break
        under.append(ln.strip())
    return p.returncode, lines[at], under


def _commands(path) -> list:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [h.get("command", "") for gs in (doc.get("hooks") or {}).values() for g in gs for h in g.get("hooks", [])]


def _upgraded_home(tmp_path, env):
    """The landed home at a revision tracking DELETED, its overlay registering DELETED and STUB beside
    the owner's own hook (rendered), then /pull of the revision that deletes DELETED. Returns (home,
    work, session, the overlay before, the restoring revision)."""
    home, work, session = _landed_harness_home(tmp_path, env)
    text = _deleted_hook_text()

    def restore(tree):
        (tree / DELETED).write_text(text, encoding="utf-8")
    _home_upstream_commit(env, work, DELETED, edit=restore)
    rev = git(env, work, "rev-parse", "HEAD").stdout.strip()
    rc, out = _home_pull(session, home, "pull.sh")
    assert rc == 0 and (home / DELETED).is_file(), out[-1500:]
    _harness_stop(session, home)
    ov = json.loads((home / OVERLAY).read_text(encoding="utf-8"))
    ov["hooks"] = _registrations(home)
    (home / OVERLAY).write_text(json.dumps(ov, indent=2) + "\n", encoding="utf-8")
    os.chmod(home / OVERLAY, 0o600)
    run([sys.executable, str(home / "scripts/install/render-settings"), "render"], env, cwd=str(home))
    assert git(env, home, "status", "--porcelain").stdout == ""
    _home_upstream_commit(env, work, DELETED, edit=lambda tree: (tree / DELETED).unlink())
    rc, out = _home_pull(session, home, "pull.sh")
    assert rc == 0 and not (home / DELETED).exists(), out[-1500:]
    return home, work, session, (home / OVERLAY).read_bytes(), rev


def test_stub_registrations_in_an_overlay_are_repaired_by_the_next_stops_landing(tmp_path, env):
    home, _work, session, before, _rev = _upgraded_home(tmp_path, env)
    rc, line, under = _check(env, home)
    print("before the Stop: rc %d | %s | %s" % (rc, line, under))
    assert rc != 0 and "[FAIL] hook paths:" in line, (line, under)
    # R1: the stub HEAD tracks is named; the deleted file, which HEAD does not track, may be personal, so
    # check counts it as missing under its event and does not echo it.
    assert "missing=1, stubs=1" in line, line
    assert sorted(under) == ["PreToolUse: a hook outside the clean form (see settings.machine.json)",
                             f"Stop: {STUB} is a stub the clean form does not register"], under
    log = landing_log(home)
    notice = _harness_stop(session, home)  # the overlay's producer, at the next Stop: no human action
    assert "Harness landing: 2 hook command(s) of settings.machine.json that HEAD retired or already runs " \
        "dropped" in notice, notice
    after = json.loads((home / OVERLAY).read_text(encoding="utf-8"))
    want = json.loads(before.decode("utf-8"))
    want["hooks"] = {k: v for k, v in _registrations(home).items() if k == "Notification"}
    assert after == want, "the overlay kept a dropped command or lost something else"
    assert stat.S_IMODE((home / OVERLAY).stat().st_mode) == 0o600
    cmds = _commands(home / "settings.json")
    assert not [c for c in cmds if DELETED in c or STUB in c], cmds
    assert any(OWN in c for c in cmds), "the owner's own registration was dropped"
    rc, line, under = _check(env, home)
    print("after the Stop: rc %d | %s | %s" % (rc, line, under))
    assert "[ ok ] hook paths:" in line and under == [], (line, under)
    added = landing_log(home)[len(log):]
    assert "overlay repaired: hooks.PreToolUse=1 hooks.Stop=1" in added, added
    for word in ("overwrite-guard", "completion-gate", "session-info", str(home)):
        assert word not in added and word not in notice, word
    assert git(env, home, "status", "--porcelain").stdout == ""
    mtime = (home / OVERLAY).stat().st_mtime_ns
    assert _harness_stop(session, home) == "" and (home / OVERLAY).stat().st_mtime_ns == mtime
    _row(fault="overlay registers a stub and a deleted harness hook", producer="the landing (overlay repair)",
         **{"blocked at": "render-settings check [FAIL]: the stub named, the deleted hook counted",
            "cleared by": "the next Stop's landing", "result": _landing_result(home)})


def test_stub_registrations_are_not_carried_by_the_migration(tmp_path, env):
    _home, work, _session, _before, rev = _upgraded_home(tmp_path, env)
    fresh = tmp_path / "fresh"
    git(env, tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(fresh))
    fresh = fresh.resolve()
    prev = json.loads(git(env, fresh, "show", f"{rev}:settings.json").stdout)
    for event, groups in _registrations(fresh).items():
        prev.setdefault("hooks", {}).setdefault(event, []).extend(groups)
    (tmp_path / "previous-settings.json").write_text(json.dumps(prev, indent=2) + "\n", encoding="utf-8")
    p = run(["bash", "scripts/bootstrap", "--steps", "2", "--migrate-from", rev, "--settings-file",
             str(tmp_path / "previous-settings.json")], dict(env, TMPDIR=str(tmp_path)), cwd=str(fresh))
    print(p.stdout[-1500:])
    for event in ("PreToolUse", "Stop"):
        assert f"not migrated: hooks.{event}: 1 hook command HEAD retired or already runs" in p.stdout \
            or f"not migrated: hooks.{event}: 1 hook commands HEAD retired or already runs" in p.stdout, p.stdout
    for word in ("overwrite-guard", "completion-gate"):
        assert word not in p.stdout + p.stderr, word
    cmds = _commands(fresh / OVERLAY)
    assert not [c for c in cmds if DELETED in c or STUB in c], cmds
    assert [c for c in cmds if OWN in c], "the owner's own registration was not migrated"
    _row(fault="previous settings register a stub and a deleted harness hook", producer="the migration (init)",
         **{"blocked at": "not carried (named by event and count)", "cleared by": "nothing to clear",
            "result": "overlay without them"})


# ---------------------------------------------------------------- stub registrations: a loaded session

def _stubs(tree: str) -> list:
    """The harness hooks of the tree marked `# STUB:` (the hooks/ directory, read now)."""
    out = []
    for name in sorted(os.listdir(os.path.join(tree, "hooks"))):
        path = os.path.join(tree, "hooks", name)
        if os.path.isfile(path) and name.endswith((".py", ".sh")):
            with open(path, "rb") as fh:
                if any(ln.startswith(b"# STUB:") for ln in fh):
                    out.append("hooks/" + name)
    return out


def _history_registration(tree: str, rel: str):
    """(event, group) of the newest settings.json in the history that registers `rel`, or None."""
    revs = subprocess.run(["git", "-C", tree, "log", "--format=%H", "-S", os.path.basename(rel), "--",
                           "settings.json"], capture_output=True, text=True).stdout.split()
    for rev in revs:
        for spec in (f"{rev}:settings.json", f"{rev}^:settings.json"):
            p = subprocess.run(["git", "-C", tree, "show", spec], capture_output=True, text=True)
            try:
                doc = json.loads(p.stdout) if p.returncode == 0 else {}
            except ValueError:
                continue
            for event, groups in (doc.get("hooks") or {}).items():
                for g in groups:
                    if any(f"/{rel}" in h.get("command", "") for h in g.get("hooks", [])):
                        # spelled as the tree's own commands are, whatever home path history used
                        kind = "python3" if rel.endswith(".py") else "bash"
                        hook = {"type": "command", "command": f'{kind} "${{CLAUDE_HOME:-$HOME/.claude}}/{rel}"'}
                        return event, dict({k: v for k, v in g.items() if k == "matcher"}, hooks=[hook])
    return None


def stub_settings(runner, armed: bool) -> str:
    """The tree's settings.json plus every stub's registration from history it lacks (see the docstring)."""
    with open(os.path.join(runner.tree, "settings.json")) as fh:
        doc = json.load(fh)
    commands = [h.get("command", "") for gs in doc["hooks"].values() for g in gs for h in g["hooks"]]
    added = {}
    for rel in _stubs(runner.tree):
        reg = None if any(f"/{rel}" in c for c in commands) else _history_registration(runner.tree, rel)
        if reg:
            doc["hooks"].setdefault(reg[0], []).append(reg[1])
            added[rel] = reg[0]
    doc = sandbox.armed(doc) if armed else doc
    doc["_a25_added_stubs"] = added  # read back by the test; the replay ignores unknown keys
    path = os.path.join(runner.work, "settings", f"stubs-{'armed' if armed else 'shipped'}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=2)
    return path


suite.BUILT_SETTINGS["stubs-shipped"] = lambda runner: stub_settings(runner, False)
suite.BUILT_SETTINGS["stubs-armed"] = lambda runner: stub_settings(runner, True)
SINGULAR = next(s for s in suite.COMPLIANT if s.name == "/dev singular")
STUB_CASES = [pytest.param(suite.replay_key(SINGULAR, s, tag="~A25-stubs"), id=s,
                           marks=pytest.mark.replay(suite.replay_key(SINGULAR, s, tag="~A25-stubs"), SINGULAR.cost))
              for s in ("stubs-shipped", "stubs-armed")]


@pytest.mark.parametrize("key", STUB_CASES)
def test_a_session_whose_hook_list_names_the_stubs_passes(replays, key):
    r = replays.get(key)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    with open(os.path.join(replays.work, "settings", r.settings + ".json")) as fh:
        added = json.load(fh)["_a25_added_stubs"]
    assert added, "no stub registration was added from history (CI fetches it whole)"
    assert not r.blocks and not r.hook_errors, r.explain()
    assert r.reached(), r.explain()
    stubs = set(_stubs(replays.tree))
    ran = {}
    for ev in r.hook_events():
        for h in ev.get("hooks", []):
            rel = next((s for s in stubs if h.get("hook", "").endswith(s)), None)
            if rel:
                ran.setdefault(rel, set()).add(h.get("rc"))
    fired = {e for e in r.summary.get("events", [])}
    for rel, event in added.items():
        if event in fired:
            assert ran.get(rel) == {0}, f"{rel} ({event}) did not run with exit 0: {ran.get(rel)}"
    assert all(rcs == {0} for rcs in ran.values()), ran
    _row(fault="loaded hook list names the stubs", producer="-", **{
        "blocked at": "nothing (0 blocks, 0 hook errors)", "cleared by": "-",
        "result": f"terminal reached; stubs run with exit 0: {', '.join(sorted(ran))}"})


# ---------------------------------------------------------------- git rm

DEV_REPORT = "agent:dev Write docs/dev/dev-report-*"
REMOVALS = {
    "recoverable": f"recover@{DEV_REPORT}=toy/util.py;modified@{DEV_REPORT}=toy/__init__.py",
    "forced": f"forced@{DEV_REPORT}=README.md",
}


def removal_key(case: str, settings: str) -> str:
    return suite.replay_key(SINGULAR, settings, (("removal", REMOVALS[case]),))


RM_CASES = {case: [pytest.param(removal_key(case, s), id=s, marks=pytest.mark.replay(removal_key(case, s),
                                                                                       SINGULAR.cost))
                   for s in suite.SETTINGS] for case in REMOVALS}


def _removals(r) -> dict:
    return {f["kind"]: f for f in tf.fault_records(r) if str(f.get("kind", "")).startswith("removal-")}


def _assert_put_back(rec: dict) -> None:
    assert rec.get("removed", {}).get("exists") is False and rec["removed"]["status"].startswith("D "), rec
    assert rec["after"] == rec["before"], f"the recover command did not put back {rec['removal_path']}: {rec}"
    recover = rec["calls"][-1]
    assert recover["ran"] and not recover["refused"] and recover["command"] == rec["discarded"].split(
        " - recover: ", 1)[1], recover


def _dev_stops_pass(r, agent: str) -> None:
    mine = tf.stops(r, agent)
    assert mine and not any(s["blocked"] for s in mine), f"the dev's stop was blocked: {mine}\n" + r.explain()


@pytest.mark.parametrize("key", RM_CASES["recoverable"])
def test_a_recoverable_git_rm(replays, key):
    r = replays.get(key)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    recs = _removals(r)
    rec, mod = recs.get("removal-recover"), recs.get("removal-modified")
    assert rec and mod, f"the removals were never made: {tf.fault_records(r)}"
    rm = rec["calls"][1]
    assert rm["command"] == "git rm -- toy/util.py" and rm["ran"] and not rm["refused"], rm
    assert re.fullmatch(r"DISCARDED toy/util\.py - recover: git checkout [0-9a-f]{40} -- toy/util\.py",
                        rec["discarded"]), rec["discarded"]
    _assert_put_back(rec)
    call = mod["calls"][0]
    assert not call["refused"], f"a hook refused git rm of a modified file: {call}"
    assert not call["ran"] and "local modifications" in call["error"], f"git did not refuse it: {call}"
    assert mod["before"]["status"].startswith(" M") and mod["after"] == mod["before"], mod
    assert not r.blocks and not r.hook_errors, r.explain()
    _dev_stops_pass(r, rec["agent"])
    assert not tf.human_events(r, tf.first_index(r, rec["calls"][0]["label"])), "a human event after the removal"
    assert r.reached(), r.explain()
    _row(fault="git rm of a clean tracked file; git rm of a modified one", producer=rec["role"], **{
        "blocked at": "nothing (the hooks allow both; git refuses the modified one, file kept)",
        "cleared by": "the DISCARDED line's recover command, same agent", "result": "file and index back; terminal"})


@pytest.mark.parametrize("key", RM_CASES["forced"])
def test_a_forced_git_rm_is_refused_naming_the_action_that_clears_it(replays, key):
    r = replays.get(key)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    rec = _removals(r).get("removal-forced")
    assert rec, f"the removal was never tried: {tf.fault_records(r)}"
    forced = rec["calls"][0]
    assert forced["command"] == "git rm -f -- README.md" and forced["refused"], forced
    assert any(h.endswith("pretool-bash-safety.sh") for h in forced["hooks"]), forced
    assert "FORBIDDEN_REMOVAL git_rm_worktree" in forced["text"], forced["text"]
    assert rec["refused_state"] == rec["before"], "the refused call changed the file or the index"
    assert rec["named"], f"the refusal names no action that clears it: {forced['text']}"
    plain = rec["calls"][2]
    assert plain["command"] == "git rm -- README.md" and plain["ran"] and not plain["refused"], plain
    _assert_put_back(rec)
    bl = tf.blocks(r)
    assert bl and all(b["step"] == forced["label"] and b["agent"] == rec["agent"] for b in bl), \
        "a block other than the forced removal's:\n" + r.explain()
    assert not r.hook_errors, r.explain()
    _dev_stops_pass(r, rec["agent"])
    assert not tf.human_events(r, tf.first_index(r, forced["label"])), "a human event after the refusal"
    assert r.reached(), r.explain()
    _row(fault="git rm -f of a tracked file", producer=rec["role"], **{
        "blocked at": "PreToolUse " + ", ".join(os.path.basename(h) for h in forced["hooks"]),
        "cleared by": "the refusal's named action (git rm without -f), same agent, then its recover command",
        "result": "file and index back; terminal"})


# ---------------------------------------------------------------- the product repository after the pipelines

CLEAN_CASES = [pytest.param(scn, s, id=f"{scn.name}-{s}",
                            marks=pytest.mark.replay(suite.replay_key(scn, s), scn.cost))
               for scn in suite.COMPLIANT for s in suite.SETTINGS]
BOOKMARK = re.compile(r"\.claude/workflow-([0-9a-f-]+)\.json")
COMMITTING = ("commit", "push")  # the scenario's own command ends with the cycle committed


def _sessions(r) -> tuple:
    """(sessions the replay started, sessions it ended) by session id."""
    started, ended = set(), set()
    for ev in tf.invocations(r):
        sid = ev["payload"].get("session_id")
        if ev["event"] == "SessionStart":
            started.add(sid)
        elif ev["event"] == "SessionEnd":
            ended.add(sid)
    return started, ended


def _calls(r) -> tuple:
    """(absolute paths a Write or Edit wrote, as the actor gave them, the text of every tool call's input
    and result) of every actor."""
    paths, text = set(), []
    given = {}
    for ev in tf.invocations(r):
        p = ev["payload"]
        if ev["event"] == "PreToolUse":
            given[p.get("tool_use_id")] = p.get("tool_input") or {}
        if ev["event"] != "PostToolUse":
            continue
        ti = given.get(p.get("tool_use_id")) or p.get("tool_input") or {}
        text.append(json.dumps(p.get("tool_input") or {}) + json.dumps(p.get("tool_response") or {}))
        if p.get("tool_name") in ("Write", "Edit", "MultiEdit"):
            paths.add(ti.get("file_path", ""))
    return paths, "\n".join(text)


@pytest.mark.parametrize("scn,settings", CLEAN_CASES)
def test_the_product_repository_is_left_clean(replays, scn, settings):
    r = replays.get(suite.replay_key(scn, settings))
    assert not r.error and not r.summary.get("driver_error"), r.explain()
    es = endstate.load(r.run_dir)
    assert es and not es.get("error"), f"no end state recorded: {es}"
    gi = es["gitignore"]
    assert gi["worktree"] == gi["start"] == gi["head"] and gi["start"], f"the tracked .gitignore changed: {gi}"
    exclude = es["exclude"]
    assert len(exclude) == len(set(exclude)), f"an exclude line twice: {exclude}"
    assert all(re.fullmatch(r"\.claude/[^/]+/", ln) for ln in exclude), f"an exclude line that is no harness-owned " \
        f".claude/ directory: {exclude}"
    for ig in es["ignored"]:
        if ig["path"].startswith(".claude/"):
            assert ig.get("source", "").endswith("info/exclude") and ig.get("pattern") in exclude, \
                f"{ig['path']} is not ignored through .git/info/exclude: {ig}"
        assert not ig["path"].startswith("docs/"), f"a docs artifact is ignored: {ig}"
    started, ended = _sessions(r)
    paths, named = _calls(r)
    left = []
    for e in es["status"]:
        path = e["path"]
        m = BOOKMARK.fullmatch(path)
        if m:
            assert m.group(1) in started - ended, f"{path}: the bookmark of a session that ended was left"
            continue
        if path.startswith(".claude/"):  # the project's own files there an actor Writes; the rest is runtime
            assert any(p.endswith("/" + path) for p in paths), \
                f"a harness runtime file in git status, not under an excluded directory: {e}"
        else:  # a cycle artifact is one the pipeline's own calls name; a file none names is a leftover
            assert path in named or os.path.basename(path) in named, \
                f"{e}: in git status and named by no tool call of the pipeline (a leftover runtime file)"
        left.append(e)
    if scn.pipeline in COMMITTING:
        assert es["head_moved"] and not left, f"after /{scn.pipeline} the cycle left {left}"
    _row(fault="-", producer=f"{scn.name} ({settings})", **{
        "blocked at": "-", "cleared by": "-",
        "result": f".gitignore unchanged; {len(exclude)} exclude lines; {len(es['ignored'])} ignored; "
                  f"{len(left)} deliverables, {len(es['status']) - len(left)} open-session bookmark(s) in status"})
