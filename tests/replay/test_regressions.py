"""Regression replays (D25 (4)): each defect a review found, replayed on the tree under test.

R-N1 (review N1 of P7b's PR, X9) and R-V1 (reviews V1-1 and NV-1) are script-level replays. A
landed harness home is a clone of a local bare origin built from the tree under test's tracked
files and made landed by init (scripts/bootstrap); the CLI's writes are plain file writes; /pull is
hooks/pull.sh and fswatch's periodic pull is git-fswatch.sh's safe_pull, each in the session's
environment (the rendered settings' env); a Stop is the registered Stop hook
(hooks/stop-workflow-coordinator.py), whose auto_commit phase runs the landing
(scripts/install/land) and relays its notice. HOME, CLAUDE_CONFIG_DIR, CLAUDE_STATE_DIR and
TMPDIR lie in the test's temporary directory (tests/test_landing.py's env); no network.

R-P1, P1's fan-out wedge: one lane of a 2-lane /dev fan-out was dispatched from an earlier template
(its obligation unparseable, F7's shape, or no obligation block at all, F7b's) and left a report
dev-report.v2 refuses (dev.status needs_review); the compliant sibling lane stops in the same round,
while that report is on disk (tests/replay/faults.py `defer`: the faulted lane's stop comes after the
sibling's). The wedge was the sibling's stop blocked by the other lane's report in every round. Now:
the sibling's stop passes; the faulted lane's own stop is returned to it naming its own report, it
repairs at its next round, and the cycle reaches its terminal. Armed, G1 refuses the earlier
template at dispatch, so the lane never starts from it: the orchestrator's next round is the
declaring dispatch from the tree's template, and the sibling still stops with no block.
"""
import json
import os
import shutil
from pathlib import Path

import pytest

from tests.replay import suite
from tests.replay import test_faults as tf
from tests.test_landing import append_allow, cli_write, env, git, landing_log, run  # noqa: F401

TREE_UNDER_TEST = Path(__file__).resolve().parents[2]  # the tree under test
FSWATCH_UNDER_TEST = "hooks/git-fswatch-under-test.sh"  # git-fswatch.sh without its `main "$@"`


def _landed_harness_home(tmp_path, env):
    """A harness home cloned from a bare origin holding the tree under test, landed by init
    (bootstrap steps 2 to 5), with origin one commit ahead. Returns (home, upstream work tree,
    session) where session holds the env the CLI gives its hooks and tools and the registered
    Stop command."""
    work, origin = tmp_path / "upstream", tmp_path / "origin.git"
    git(env, tmp_path, "init", "-q", "-b", "master", str(work))
    for rel in run(["git", "-C", str(TREE_UNDER_TEST), "ls-files", "-z"], env).stdout.split("\0"):
        src = TREE_UNDER_TEST / rel
        if not rel or not os.path.lexists(src):
            continue
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            os.symlink(os.readlink(src), work / rel)
        else:
            shutil.copy2(src, work / rel)
    git(env, work, "add", "-A")
    git(env, work, "commit", "-q", "-m", "the tree under test")
    git(env, tmp_path, "clone", "-q", "--bare", str(work), str(origin))
    git(env, work, "remote", "add", "origin", str(origin))
    git(env, tmp_path, "clone", "-q", str(origin), str(tmp_path / "harness"))
    home = Path(os.path.realpath(tmp_path / "harness"))
    scratch = tmp_path / "session-tmp"
    scratch.mkdir()
    env = dict(env, TMPDIR=str(scratch))
    run(["bash", "scripts/bootstrap", "--steps", "2"], env, cwd=str(home))
    overlay = json.loads((home / "settings.machine.json").read_text(encoding="utf-8"))
    overlay["env"].update(TMPDIR=str(scratch), CLAUDE_CODE_TMPDIR=str(scratch))
    (home / "settings.machine.json").write_text(json.dumps(overlay, indent=2) + "\n")
    run(["bash", "scripts/bootstrap", "--steps", "3,4,5"], env, cwd=str(home))
    assert run(["bash", "scripts/install/land", "--state"], env, cwd=str(home)).stdout == "landed\n"
    assert git(env, home, "status", "--porcelain").stdout == ""
    settings = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    stop = [h["command"] for group in settings["hooks"]["Stop"] for h in group["hooks"]
            if "stop-workflow-coordinator.py" in h.get("command", "")]
    assert len(stop) == 1, stop
    session = dict(env, **{k: v for k, v in settings["env"].items() if isinstance(v, str)})
    session.update(CLAUDE_PROJECT_DIR=str(home))
    lib = (home / "hooks/git-fswatch.sh").read_text(encoding="utf-8").rstrip("\n")
    assert lib.endswith('\nmain "$@"')
    (home / FSWATCH_UNDER_TEST).write_text(lib.rsplit("\n", 1)[0] + "\n", encoding="utf-8")
    with open(home / ".git/info/exclude", "a", encoding="utf-8") as fh:
        fh.write("/%s\n" % FSWATCH_UNDER_TEST)
    (Path(env["CLAUDE_CONFIG_DIR"]) / "logs").mkdir(exist_ok=True)  # a live home has it
    (tmp_path / "transcript.jsonl").write_text("")
    _home_upstream_commit(env, work)
    return home, work, {"env": session, "stop": stop[0],
                        "transcript": tmp_path / "transcript.jsonl"}


def _home_upstream_commit(env, work, rel="upstream-note.md", text="an upstream change\n",
                          edit=None):
    if edit:
        edit(work)
    else:
        (work / rel).write_text(text, encoding="utf-8")
    git(env, work, "add", "-A")
    git(env, work, "commit", "-q", "-m", "upstream: " + rel)
    git(env, work, "push", "-q", "origin", "master")


def _harness_stop(session, home):
    """One Stop event through the registered hook, as the CLI sends it: exit 0 with each phase
    allowed (no gate block, no hook error). Returns the relayed notice (systemMessage)."""
    payload = {"session_id": "replay-regressions", "transcript_path": str(session["transcript"]),
               "cwd": str(home), "hook_event_name": "Stop", "stop_hook_active": False}
    proc = run(["bash", "-c", session["stop"]], session["env"], cwd=str(home),
               input=json.dumps(payload), check=False)
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-800:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert [p["status"] for p in out["phases"]] == ["allow"] * 4, out["phases"]
    return out.get("systemMessage", "")


def _home_pull(session, home, path):
    """/pull (hooks/pull.sh) or fswatch's periodic pull (safe_pull): (exit status, output)."""
    if path == "pull.sh":
        proc = run(["bash", str(home / "hooks/pull.sh")], session["env"], cwd=str(home),
                   check=False)
        return proc.returncode, proc.stdout + proc.stderr
    script = 'source "$1" "$2"; trap - SIGINT SIGTERM EXIT; safe_pull'
    proc = run(["bash", "-c", script, "fswatch", str(home / FSWATCH_UNDER_TEST), str(home)],
               session["env"], cwd=str(home), check=False)
    return proc.returncode, proc.stdout + proc.stderr


def _home_unmerged(env, home):
    """The unmerged paths (the index alone: `git diff` would run the clean filter on a file
    with conflict markers, which refuses it)."""
    return sorted({line.split("\t", 1)[1] for line in
                   git(env, home, "ls-files", "-u").stdout.splitlines()})


def _landing_result(home):
    """The result of the landing's last logged run (logs/landing.log), or "" when none ran."""
    results = [w for w in landing_log(home).split() if w.startswith("result=")]
    return results[-1] if results else ""


def _home_head(env, home):
    head = git(env, home, "rev-parse", "HEAD").stdout.strip()
    upstream = git(env, home, "rev-parse", "origin/master").stdout.strip()
    ls = git(env, home, "ls-remote", "origin", "refs/heads/master").stdout.split()[0]
    return "HEAD %s origin/master %s upstream %s" % (head[:12], upstream[:12], ls[:12]), \
        head == ls


# ----------------------------------------------------------------------- R-N1 (review N1, X9)

def _assert_pulled_and_kept(env, home, rc, out, path):
    state, at_upstream = _home_head(env, home)
    assert rc == 0, "%s rc=%d; %s\n%s" % (path, rc, state, out[-1500:])
    assert at_upstream, "%s rc=%d but %s\n%s" % (path, rc, state, out[-1500:])
    assert (home / "upstream-note.md").exists()
    doc = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    assert doc.get("model") == "demo-live-model", "the CLI's model was not kept"
    assert git(env, home, "stash", "list").stdout == "", "something was stashed"
    assert git(env, home, "status", "--porcelain").stdout == ""


@pytest.mark.parametrize("path", ["pull.sh", "safe_pull"])
def test_r_n1_a_cli_write_then_a_stop_then_the_pull_reaches_upstream(tmp_path, env, path):
    """X9 (i): on a landed home the CLI writes `model`, a key the clean form leaves out, into
    settings.json (stat-dirty, unchanged through the filter); one Stop; then /pull and fswatch's
    pull each reach upstream, `model` is kept and nothing is stashed. Before (1d10ae0): pull.sh
    exited 1 (`cannot pull with rebase: You have unstaged changes`), safe_pull returned 0, HEAD
    behind."""
    home, _work, session = _landed_harness_home(tmp_path, env)
    cli_write(home / "settings.json", "model", "demo-live-model")
    assert git(env, home, "diff-files", "--name-only").stdout == "settings.json\n"
    _harness_stop(session, home)
    rc, out = _home_pull(session, home, path)
    _assert_pulled_and_kept(env, home, rc, out, path)


@pytest.mark.parametrize("path", ["pull.sh", "safe_pull"])
def test_r_n1_a_cli_write_then_the_pull_before_any_stop_reaches_upstream(tmp_path, env, path):
    """X9 (ii): the same CLI write, then the pull before any Stop (`/model` starts no turn). The
    landing's re-record of settings.json's stat runs before the pull's stash decision (R20), so
    the pull goes through as after a Stop. Before (b97f947, review N1's remaining window): pull.sh
    exited 1, safe_pull returned 0 without pulling."""
    home, _work, session = _landed_harness_home(tmp_path, env)
    cli_write(home / "settings.json", "model", "demo-live-model")
    assert git(env, home, "diff-files", "--name-only").stdout == "settings.json\n"
    rc, out = _home_pull(session, home, path)
    _assert_pulled_and_kept(env, home, rc, out, path)
    _harness_stop(session, home)
    assert git(env, home, "status", "--porcelain").stdout == ""


def _gone_origin(env, home, tmp_path):
    git(env, home, "remote", "set-url", "origin", str(tmp_path / "gone.git"))


def _index_lock(env, home, tmp_path):
    (home / ".git/index.lock").write_text("")


def _lock_and_an_owner_edit(env, home, tmp_path):
    (home / "README.md").write_text("an owner's edit\n", encoding="utf-8")
    (home / ".git/index.lock").write_text("")


@pytest.mark.parametrize("step,fault,said", [
    ("fetch", _gone_origin, "Failed to fetch from remote"),
    ("stash push", _lock_and_an_owner_edit, "Failed to stash changes"),
    ("pull", _index_lock, "Pull failed"),
], ids=["fetch", "stash-push", "pull"])
def test_r_n1_safe_pull_returns_non_zero_when_a_step_fails(tmp_path, env, step, fault, said):
    """safe_pull judges each step by its git command's own exit status, not tee's: a failed fetch
    (origin gone), stash push (index.lock held, an owner's edit to stash) or pull (index.lock held)
    is logged as failed and safe_pull returns non-zero; HEAD stays. Before (b97f947): tee's status
    chose, so each was logged as success and safe_pull returned 0 behind upstream."""
    home, _work, session = _landed_harness_home(tmp_path, env)
    fault(env, home, tmp_path)
    head = git(env, home, "rev-parse", "HEAD").stdout
    rc, out = _home_pull(session, home, "safe_pull")
    assert rc != 0, "safe_pull rc=0 after a failed %s\n%s" % (step, out[-1500:])
    assert said in out and "Pull successful" not in out, out[-1500:]
    assert git(env, home, "rev-parse", "HEAD").stdout == head


# ------------------------------------------------------------- R-V1 (reviews V1-1 and NV-1)

def _doc_sync_index(work_or_home, line, value):
    """INDEX.md with one line replaced: line 0 is doc-sync's date line, 1 the one after it."""
    path = work_or_home / "INDEX.md"
    lines = path.read_text(encoding="utf-8").split("\n")
    at = next(i for i, text in enumerate(lines) if text.startswith("*Last updated: "))
    lines[at + line] = value
    path.write_text("\n".join(lines), encoding="utf-8")


@pytest.mark.parametrize("paths", [["settings.json"], ["INDEX.md"], ["INDEX.md", "settings.json"]],
                         ids=["V1-1-settings", "NV-1-doc-sync", "NV-1-doc-sync-and-settings"])
def test_r_v1_a_repair_git_refused_is_named_and_runs_again(tmp_path, env, paths):
    """A landed home's /pull left settings.json (upstream and the CLI each appended an allow
    entry) and/or doc-sync's INDEX.md (re-dated here, the line after the date edited upstream)
    unmerged. While index.lock is held, the Stop's relayed notice names each path the repair git
    refused and logs/landing.log says result=repair-refused; once it is released, the next Stop
    repairs every such path (result=repaired, nothing unmerged). Before: V1-1 (26a7ea7) and NV-1
    (96bcb8f) gave no notice and logged result=repaired; with both paths, 96bcb8f counted INDEX.md
    among the other conflicted paths left as they are."""
    home, work, session = _landed_harness_home(tmp_path, env)

    def upstream(tree):
        if "settings.json" in paths:
            append_allow(tree / "settings.json", "Bash(demo-upstream-tool:*)")
        if "INDEX.md" in paths:
            _doc_sync_index(tree, 1, "**Total entries**: 1 (an upstream edit)")
    _home_upstream_commit(env, work, "settings.json and INDEX.md", edit=upstream)
    if "settings.json" in paths:
        append_allow(home / "settings.json", "Bash(/opt/demo/bin/live-tool2:*)")
    if "INDEX.md" in paths:
        _doc_sync_index(home, 0, "*Last updated: 2099-01-01T00:00:00Z*")  # doc-sync re-dates it
    rc, out = _home_pull(session, home, "pull.sh")
    assert rc == 1 and "Stash conflicts detected" in out, out[-1500:]
    assert _home_unmerged(env, home) == paths
    (home / ".git/index.lock").write_text("")
    notice, result = _harness_stop(session, home), _landing_result(home)
    print("index.lock held: %s | relayed: %s" % (result, notice))
    named = "Harness landing: %s still conflicted: git refused its repair, tried again at the " \
        "next turn end" % ", ".join(paths)
    assert named in notice and "other conflicted path" not in notice \
        and result == "result=repair-refused", "relayed: %r; landing.log: %s" % (notice, result)
    assert _home_unmerged(env, home) == paths
    (home / ".git/index.lock").unlink()
    notice, result = _harness_stop(session, home), _landing_result(home)
    print("index.lock released: %s | relayed: %s" % (result, notice))
    taken = "Harness landing: %d file(s) a pull left conflicted taken from upstream (%d " \
        "doc-sync)" % (len(paths), "INDEX.md" in paths)
    assert taken in notice and result == "result=repaired", \
        "relayed: %r; landing.log: %s" % (notice, result)
    assert _home_unmerged(env, home) == []
    json.loads((home / "settings.json").read_text(encoding="utf-8"))  # no conflict markers


# ---------------------------------------------------------------- R-P1, P1's fan-out wedge
SHAPES = {
    "F7": f"pretemplate@{tf.L1_DEV_DISPATCH}=defer;invalid@{tf.L1_DEV}=dev.status:needs_review",
    "F7b": f"noblock@{tf.L1_DEV_DISPATCH}=defer;invalid@{tf.L1_DEV}=dev.status:needs_review",
}


def key(shape: str, settings: str) -> str:
    return suite.replay_key(tf.FANOUT, settings, (("fault", SHAPES[shape]),), tag="~R-P1")


CASES = [pytest.param(shape, s, id=f"R-P1-{shape}-{s}", marks=pytest.mark.replay(key(shape, s), tf.FANOUT.cost))
         for shape in SHAPES for s in suite.SETTINGS]


def _dispatched(r, label: str) -> str:
    """The agent id the Agent call labelled `label` started (its PostToolUse result)."""
    for ev in tf.invocations(r):
        p = ev["payload"]
        if ev["event"] == "PostToolUse" and p.get("tool_name") == "Agent" and ev["label"] == label:
            return (p.get("tool_response") or {}).get("agentId")
    return ""


@pytest.mark.parametrize("shape,settings", CASES)
def test_fanout_wedge(replays, shape, settings):
    r = replays.get(key(shape, settings))
    assert not r.error and not r.summary.get("driver_error"), r.explain()
    assert not r.hook_errors, "a hook error:\n" + r.explain()
    sibling = _dispatched(r, "Step 10 [l2] Agent(dev)")
    assert sibling, "the sibling lane's dev never ran:\n" + r.explain()
    sib_stops = tf.stops(r, sibling)
    assert sib_stops and not any(s["blocked"] for s in sib_stops), \
        f"the compliant sibling's stop was blocked (the wedge): {sib_stops}\n" + r.explain()
    dispatch = next(f for f in tf.fault_records(r) if f.get("kind") in ("pretemplate", "noblock"))
    if dispatch.get("refused_at_dispatch"):
        tf._refused_at_dispatch(shape, r, dispatch)
    else:
        report = next(f for f in tf.fault_records(r) if f.get("path"))
        own = tf.stops(r, report["agent"])
        written = [i for i, a in tf.writers(r, report["path"]) if a == report["agent"]]
        # the shape happened: the sibling stopped after the faulted report was written, before its
        # writer's own first stop
        assert written and own and written[0] < sib_stops[0]["i"] < own[0]["i"], \
            f"the sibling did not stop while the faulted report was on disk: {written} {sib_stops} {own}"
        tf._returned_and_repaired(shape, r)
    assert r.reached(), "the pipeline did not reach its terminal:\n" + r.explain()
