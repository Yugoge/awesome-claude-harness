"""Regression replays (D25 (4)): each defect a review found, replayed on the tree under test.

R-V1 (reviews V1-1 and NV-1 of P7b's PR) is a script-level replay. A
landed harness home is a clone of a local bare origin built from the tree under test's tracked
files and made landed by init (scripts/bootstrap); the CLI's writes are plain file writes; /pull is
hooks/pull.sh and fswatch's periodic pull is git-fswatch.sh's safe_pull, each in the session's
environment (the rendered settings' env); a Stop is the registered Stop hook
(hooks/stop-workflow-coordinator.py), whose auto_commit phase runs the landing
(scripts/install/land) and relays its notice. HOME, CLAUDE_CONFIG_DIR, CLAUDE_STATE_DIR and
TMPDIR lie in the test's temporary directory (tests/test_landing.py's env); no network.
"""
import json
import os
import shutil
from pathlib import Path

import pytest

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
