"""A role's drafts live in <session root>/<role>/, the commit lock under the state root, none in /tmp.

policies/tool-policy.v1.json (policy_version 10) gives each of the 21 roles that keep drafts the allow prefix
`<session root>/<role>/`: the session's scratch directory (the settings' TMPDIR, then the session id) and the
role's name, resolved per write (hooks/lib/policy_registry.py placed). The changelog-analyst's fd-9 lock is
`<state dir>/agentic-commit/locks/*`, the state root the one resolver names. Before, every such row held
`*/tmp/claude-scratch/<role>/`, a glob that matched any directory tree ending in tmp/claude-scratch/<role>/
(the system temp directory's, /var/tmp's own claude-scratch/<role>/, one in a project or a home), and the lock
was `/tmp/agentic-commit/locks/*`. A dispatch begun before still rewrites a file it left at its old place, and
the changelog-analyst still takes its old lock there (policy_registry.in_flight); nothing new is made there.

Each case runs the real hook as a subprocess, the project outside every temp root and never created. The
in-flight and full-volume cases run it in a private mount namespace whose /tmp is a small tmpfs of the test's
own (unshare -rm); they are skipped where no such namespace can be made.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-tool-policy.py"
PROJECT = "/nonexistent-role-drafts/proj"
SID, OTHER_SID = "0d1e2f3a-0000-4000-8000-000000000001", "0d1e2f3a-0000-4000-8000-000000000002"
OUTSIDE_STATE = "/nonexistent-role-drafts/state"  # a state root on disk, outside every temp root
ROLES = ("architect", "ba", "changelog-analyst", "cleaner", "cleanliness-inspector", "git-edge-case-analyst",
         "graphify", "merge-analyst", "pm", "product-owner", "prompt-inspector", "push-analyst", "qa",
         "rule-inspector", "spec", "style-inspector", "test-executor", "test-validator", "test-writer",
         "ui-specialist", "user")
POLICY = json.loads((ROOT / "policies" / "tool-policy.v1.json").read_text(encoding="utf-8"))
AGENT = (ROOT / "agents" / "changelog-analyst.md").read_text(encoding="utf-8")
# The previous version's Phase 3 lock block, as a flow begun then still runs it.
OLD_LOCK = ('mkdir -p /tmp/agentic-commit/locks\n'
            'REPO_HASH="$(printf \'%s\' "$(git -C "/srv/repo" rev-parse --show-toplevel)" | sha256sum | cut -c1-16)"\n'
            'exec 9>"/tmp/agentic-commit/locks/${REPO_HASH}.lock"\nflock -w 30 -x 9 || exit 1\n')
# The private /tmp of the namespace cases: what a flow begun before left there, then (FULL=1) no space left.
PREPARE = r'''
mount -t tmpfs -o size=256k,mode=1777 none /tmp || exit 97
if [ "$LINKED" = 1 ]; then mkdir -p /tmp/real/agentic-commit && ln -s /tmp/real/agentic-commit /tmp/agentic-commit; fi
mkdir -p /tmp/claude-scratch/changelog-analyst /tmp/claude-scratch/qa/proj/src /tmp/agentic-commit/locks /tmp/elsewhere/sub
printf old > /tmp/claude-scratch/changelog-analyst/commit-msg-old.txt
printf old > /tmp/claude-scratch/qa/notes.md
printf old > /tmp/claude-scratch/qa/a.md && ln /tmp/claude-scratch/qa/a.md /tmp/claude-scratch/qa/linked.md
printf old > /tmp/claude-scratch/qa/proj/src/x.py && printf old > /tmp/elsewhere/sub/f.md
ln -s /tmp/elsewhere /tmp/claude-scratch/qa/mid && ln -s /tmp/elsewhere /tmp/claude-scratch/ba
if [ "$FULL" = 1 ]; then cat /dev/zero > /tmp/.full 2>/dev/null; [ "$(df --output=avail /tmp | tail -1)" -eq 0 ] || exit 98; fi
exec "$@"
'''
# The hook, run with policy_registry.IN_FLIGHT_HOURS set (argv: hook, hours).
WITH_HOURS = ("import runpy, sys; sys.path.insert(0, sys.argv[1].rsplit('/', 1)[0]); from lib import policy_registry; "
              "policy_registry.IN_FLIGHT_HOURS = float(sys.argv[2]); sys.argv = sys.argv[1:2]; "
              "runpy.run_path(sys.argv[0], run_name='__main__')")
OPEN = 1e6  # hours: the window still open, whenever the tree's policy file was last written


@pytest.fixture()
def place(tmp_path):
    """The session root's parent (the hook's TMPDIR) and a HOME, both the test's own."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return {"tmpdir": os.path.realpath(scratch), "home": tmp_path / "home"}


def _env(place, state=OUTSIDE_STATE) -> dict:
    (place["home"] / ".claude").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(place["home"]), CLAUDE_CONFIG_DIR=str(place["home"] / ".claude"), CLAUDE_PROJECT_DIR=PROJECT,
               PYTHONDONTWRITEBYTECODE="1", TMPDIR=place["tmpdir"], CLAUDE_STATE_DIR=state)
    return env


def run(place, role, tool, tool_input, state=OUTSIDE_STATE, ns=None, hours=None, project=PROJECT):
    """The hook's exit code and first stderr line for one call of a subagent of ``role``; ``ns`` "free", "full"
    or "linked" (/tmp/agentic-commit a link) runs it in the private namespace (PREPARE); ``hours`` sets how long
    after the policy's arrival a flow begun before finishes (policy_registry.IN_FLIGHT_HOURS) in the hook's run."""
    payload = {"session_id": SID, "cwd": project, "hook_event_name": "PreToolUse", "tool_name": tool,
               "tool_input": tool_input, "agent_id": "a" + uuid.uuid4().hex[:16], "agent_type": role}
    argv, env = [sys.executable, str(HOOK)], _env(place, state)
    env["CLAUDE_PROJECT_DIR"] = project
    if hours is not None:
        argv = [sys.executable, "-c", WITH_HOURS, str(HOOK), str(hours)]
    if ns:
        argv = ["unshare", "-rm", "--propagation", "private", "sh", "-c", PREPARE, "sh"] + argv
        env["FULL"], env["LINKED"] = ("1" if ns == "full" else "0"), ("1" if ns == "linked" else "0")
    proc = subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=60)
    if ns and proc.returncode in (97, 98):
        pytest.skip(f"no private /tmp could be made here (rc {proc.returncode}): {proc.stderr[:200]}")
    assert not Path(PROJECT).parent.exists(), "the policy check must not create the project"
    return proc.returncode, (proc.stderr.splitlines() or [""])[0]


def _ns_available() -> bool:
    try:
        return subprocess.run(["unshare", "-rm", "true"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


needs_ns = pytest.mark.skipif(not _ns_available(), reason="no private mount namespace (unshare -rm) here")


def write(path):
    return "Write", {"file_path": path, "content": "draft"}


def drafts(place, role, sid=SID) -> str:
    return os.path.join(place["tmpdir"], sid, role)


# ---------------------------------------------------------------- the policy rows and the agent text
def test_each_role_root_is_its_directory_under_the_session_root():
    rows = POLICY["roles"]
    held = sorted(r for r, row in rows.items() if f"<session root>/{r}/" in row.get("allowed_write_path_prefixes", []))
    assert held == sorted(ROLES)
    for role, row in rows.items():
        for prefix in row.get("allowed_write_path_prefixes", []):
            assert "claude-scratch" not in prefix and "tmp/agentic-commit/locks" not in prefix, (role, prefix)
            assert not prefix.startswith("<session root>") or prefix == f"<session root>/{role}/", (role, prefix)
    assert "<state dir>/agentic-commit/locks/*" in rows["changelog-analyst"]["allowed_write_path_prefixes"]


def test_the_agent_and_command_texts_name_no_draft_or_lock_place_in_tmp():
    texts = [*(ROOT / "agents").glob("*.md"), *(ROOT / "commands").glob("*.md")]
    hits = [f"{p.name}:{n}" for p in texts for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if re.search(r"(?<!/var)/tmp/(claude-scratch|agentic-commit/locks)", line)]
    assert hits == [], hits


def test_the_commit_flow_text_takes_both_places_from_their_resolvers(place, tmp_path):
    """Rule CP-5's block, run as written, prints the session root and the state root; the analyst's message file in
    the first and the Phase 3 lock in the second are places the hook lets it write."""
    block = re.search(r"\*\*Rule CP-5[^\n]*\n\n```bash\n(.*?)```", AGENT, re.S).group(1)
    state = str(tmp_path / "state")
    env = _env(place, state)
    env.update(CLAUDE_CODE_TMPDIR=place["tmpdir"], CLAUDE_CODE_SESSION_ID=SID, CLAUDE_HOME=str(ROOT))
    proc = subprocess.run(["bash", "-c", block], capture_output=True, text=True, env=env, timeout=30)
    assert proc.returncode == 0, proc.stderr
    session_root, state_dir = proc.stdout.splitlines()
    assert (session_root, state_dir) == (os.path.join(place["tmpdir"], SID), state)
    msg = os.path.join(session_root, "changelog-analyst", "commit-msg-t1-r0002x.txt")
    assert run(place, "changelog-analyst", *write(msg), state=state) == (0, "")
    lock = re.search(r"### Phase 3: Serialization.*?```bash\n(.*?)```", AGENT, re.S).group(1)
    lock = "GIT_ROOT=/srv/repo\n" + lock.replace("<STATE_DIR>", state_dir)
    assert run(place, "changelog-analyst", "Bash", {"command": lock}, state=state) == (0, "")


# ---------------------------------------------------------------- the hook's decisions
@pytest.mark.parametrize("role", ROLES)
def test_each_role_writes_a_draft_in_its_own_directory(place, role):
    assert run(place, role, *write(os.path.join(drafts(place, role), "draft.md"))) == (0, "")


@pytest.mark.parametrize("path", [
    "/tmp/claude-scratch/ba/new-{u}.md",                         # the old role root: nothing new there
    "/var/tmp/claude-scratch/ba/new-{u}.md",                     # /var/tmp's own claude-scratch/<role>/
    "{T}/" + SID + "/tmp/claude-scratch/ba/new-{u}.md",          # a tree ending in tmp/claude-scratch/<role>/
    "/srv/u/tmp/claude-scratch/ba/new-{u}.md",                   # one under a user's home
    PROJECT + "/x/tmp/claude-scratch/ba/new-{u}.md",
    "{T}/" + OTHER_SID + "/ba/new-{u}.md",                       # another session's ba directory
    "{T}/" + SID + "/qa/new-{u}.md",                             # another role's directory
    "{T}/" + SID + "/new-{u}.md",                                # the session root itself
    "{T}/ba/new-{u}.md",                                         # a role name at the temp root
])
def test_a_role_writes_no_draft_outside_its_own_directory(place, path):
    target = path.replace("{T}", place["tmpdir"]).replace("{u}", uuid.uuid4().hex[:8])
    code, err = run(place, "ba", *write(target))
    assert code == 2 and "BLOCKED by tool-policy.v1" in err, (target, err)


@pytest.mark.parametrize("state", [OUTSIDE_STATE, "below-tmp"])
def test_the_commit_message_and_lock_are_at_their_new_places(place, tmp_path, state):
    state = str(tmp_path / "state") if state == "below-tmp" else state
    msg = os.path.join(drafts(place, "changelog-analyst"), "commit-msg-t1-r0001x.txt")
    assert run(place, "changelog-analyst", *write(msg), state=state) == (0, "")
    lock = re.search(r"### Phase 3: Serialization.*?```bash\n(.*?)```", AGENT, re.S).group(1)
    lock = "GIT_ROOT=/srv/repo\n" + lock.replace("<STATE_DIR>", state)
    assert run(place, "changelog-analyst", "Bash", {"command": lock}, state=state) == (0, "")
    # another role takes no lock there, and the analyst none at the old place it never used
    assert run(place, "qa", "Bash", {"command": lock}, state=state)[0] == 2
    assert run(place, "changelog-analyst", *write(f"/tmp/claude-scratch/changelog-analyst/new-{SID}.txt"))[0] == 2


# ---------------------------------------------------------------- a flow in flight, /tmp free or full
@needs_ns
@pytest.mark.parametrize("ns", ["free", "full"])
def test_a_flow_begun_before_finishes_at_its_old_places(place, ns):
    ca = "changelog-analyst"
    assert run(place, ca, *write("/tmp/claude-scratch/changelog-analyst/commit-msg-old.txt"), ns=ns, hours=OPEN) == (0, "")
    assert run(place, ca, "Bash", {"command": OLD_LOCK}, ns=ns, hours=OPEN) == (0, "")
    assert run(place, "qa", *write("/tmp/claude-scratch/qa/notes.md"), ns=ns, hours=OPEN) == (0, "")
    # nothing new at the old places, no file with a second link, no other role's, no other role's lock
    for role, path in ((ca, "/tmp/claude-scratch/changelog-analyst/commit-msg-new.txt"),
                       ("qa", "/tmp/claude-scratch/qa/linked.md"), ("ba", "/tmp/claude-scratch/qa/notes.md")):
        assert run(place, role, *write(path), ns=ns, hours=OPEN)[0] == 2, (role, path)
    assert run(place, "qa", "Bash", {"command": OLD_LOCK}, ns=ns, hours=OPEN)[0] == 2


@needs_ns
def test_the_deny_prefixes_hold_at_the_old_place(place):
    old_project = "/tmp/claude-scratch/qa/proj"  # a project under the old place: qa's /src/ denial holds there
    code, err = run(place, "qa", *write(old_project + "/src/x.py"), ns="free", hours=OPEN, project=old_project)
    assert code == 2 and "denied_write_path_prefixes" in err, err


@needs_ns
@pytest.mark.parametrize("role, tool_input, ns", [
    ("qa", write("/tmp/claude-scratch/qa/mid/sub/f.md"), "free"),       # a link in a middle component
    ("ba", write("/tmp/claude-scratch/ba/sub/f.md"), "free"),           # the role's old directory a link
    ("changelog-analyst", ("Bash", {"command": OLD_LOCK}), "linked"),   # a link above the lock directory
])
def test_a_link_in_any_component_closes_the_old_place(place, role, tool_input, ns):
    assert run(place, role, *tool_input, ns=ns, hours=OPEN)[0] == 2


@needs_ns
@pytest.mark.parametrize("tool_input, new", [
    (write("/tmp/claude-scratch/changelog-analyst/commit-msg-old.txt"), "{drafts}/"),
    (("Bash", {"command": OLD_LOCK}), OUTSIDE_STATE + "/agentic-commit/locks/"),
])
def test_after_the_window_the_refusal_names_the_new_place(place, tool_input, new):
    code, err = run(place, "changelog-analyst", *tool_input, ns="free", hours=0)
    assert code == 2 and "write to " + new.replace("{drafts}", drafts(place, "changelog-analyst")) in err, err


def test_the_window_runs_from_the_policy_files_arrival(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "hooks" / "lib"))
    import policy_registry
    policy = tmp_path / "tool-policy.v1.json"
    policy.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(policy_registry.claude_home, "resolve_optional", lambda rel: policy)
    now = time.time()
    for age_h, open_ in ((policy_registry.IN_FLIGHT_HOURS - 1, True), (policy_registry.IN_FLIGHT_HOURS + 1, False)):
        os.utime(policy, (now - age_h * 3600, now - age_h * 3600))
        assert (now < policy_registry._in_flight_until()) is open_, age_h
    monkeypatch.setattr(policy_registry.claude_home, "resolve_optional", lambda rel: None)
    assert policy_registry._in_flight_until() == 0.0  # no policy read: the window is closed


@needs_ns
@pytest.mark.parametrize("role", ["changelog-analyst", "qa"])
def test_the_new_places_decide_alike_with_tmp_full(place, role):
    path = os.path.join(drafts(place, role), "draft.md")
    assert run(place, role, *write(path), ns="full") == run(place, role, *write(path), ns="free") == (0, "")
