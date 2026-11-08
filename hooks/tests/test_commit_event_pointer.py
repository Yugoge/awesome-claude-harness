"""The commit grant's single use, the per-event pointer and the commit-event journal.

The privilege guard spends a grant by deleting it and, in the same step, writes one
pointer named for the commit's own tool event that carries the grant's journal fields;
the PostToolUse finalizer appends the journal entry from that pointer and removes it.
Nothing writes a `.lck`, a `.use` record or an attestation claim. The caller's identity
is the digest of the prompt that dispatched it, read from its own transcript, so one
dispatch commits every repository of its plan and no other subagent commits at all.
The Stop cleanup takes the finalizer's stale reading and the guard's sentinel test.
"""

import glob
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

import lib.commit_journal as CJ  # noqa: E402
import lib.commit_pipeline as CP  # noqa: E402


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARD = _load(HOOKS / "pretool-git-privilege-guard.py", "guard_commit_event_pointer")
FINALIZER = _load(HOOKS / "posttool-allowlist-consume.py", "finalizer_commit_event_pointer")
REVOKER = _load(ROOT / "scripts" / "write-commit-grant.py", "revoker_commit_event_pointer")

SID = "sid-orchestrator"


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def make_repo(path):
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "master")
    git(path, "config", "user.email", "t@example.invalid")
    git(path, "config", "user.name", "test")
    git(path, "config", "commit.gpgsign", "false")
    (path / "f.txt").write_text("base\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "base")
    return str(path)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A state dir, a journal root and a pointer namespace of the test's own."""
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(state))
    monkeypatch.setattr(CJ, "JOURNAL_ROOT", str(tmp_path / "commit-events"))
    monkeypatch.setattr(CJ, "POINTER_TEMPLATE", str(state / (CJ.POINTER_PREFIX + "{key}.json")))
    monkeypatch.setattr(CJ, "POINTER_GLOB", str(state / (CJ.POINTER_PREFIX + "*.json")))
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "CLAUDE_SESSION_ID",
                 "CLAUDE_CODE_SESSION_ID", "CLAUDE_TASK_ID"):
        monkeypatch.delenv(name, raising=False)
    # The session's project directory: its transcripts live under its slug, whatever
    # repository a subagent commits in.
    (tmp_path / "project").mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "project"))
    return tmp_path


def session_dir():
    slug = str(Path(os.environ["CLAUDE_PROJECT_DIR"]).resolve()).replace("/", "-")
    return Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / slug


def mint(state, repo, task_id="20261028-100000", sid=SID):
    """A grant exactly as scripts/write-commit-grant.py shapes it."""
    now = datetime.now(timezone.utc)
    nonce = os.urandom(8).hex()
    grant = {"task_id": task_id, "sid": sid, "nonce": nonce, "repo_root": git(repo, "rev-parse", "--show-toplevel"),
             "branch": git(repo, "branch", "--show-current"), "expected_head": git(repo, "rev-parse", "HEAD"),
             "created_at": (now - timedelta(seconds=2)).isoformat(),
             "expires_at": (now + timedelta(minutes=30)).isoformat(),
             "minted_by": {"origin": CP.PIPELINE_ORIGIN}}
    path = Path(state) / f"claude-commit-grant-{sid}-{nonce}.json"
    path.write_text(json.dumps(grant))
    return str(path), grant


def dispatch(prompt, sid=SID, subagent_type="changelog-analyst"):
    """The records a real dispatch leaves: the parent's Agent call and the subagent
    transcript, plus, for a changelog-analyst, the attestation the PreToolUse:Agent hook
    writes (hooks/pretool-commit-dispatch-attest.py writes none for any other type)."""
    if subagent_type == "changelog-analyst":
        digest = hashlib.sha256(prompt.encode()).hexdigest()
        CP.write_attestation(sid, task_id="20261028-100000", dryrun=False, prompt_sha256=digest)
    root = session_dir()
    agent_id = "a" + os.urandom(8).hex()
    tool_use_id = "toolu_" + os.urandom(8).hex()
    (root / sid / "subagents").mkdir(parents=True, exist_ok=True)
    with open(root / f"{sid}.jsonl", "a") as handle:
        handle.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tool_use_id, "name": "Agent",
             "input": {"subagent_type": subagent_type, "prompt": prompt}}]}}) + "\n")
    transcript = root / sid / "subagents" / f"agent-{agent_id}.jsonl"
    transcript.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
    (root / sid / "subagents" / f"agent-{agent_id}.meta.json").write_text(json.dumps({"toolUseId": tool_use_id}))
    return agent_id


def commit_payload(repo, agent_id, tool_use_id):
    msg = Path(repo).parent / "msg.txt"
    msg.write_text("feat: change\n")
    return {"tool_name": "Bash", "session_id": SID, "agent_id": agent_id, "cwd": repo,
            "tool_use_id": tool_use_id, "transcript_path": str(session_dir() / f"{SID}.jsonl"),
            "tool_input": {"command": f'git -C {repo} commit -F "{msg}"'}}


def evaluate(payload):
    try:
        GUARD._evaluate_commit(payload["tool_input"]["command"], payload)
    except SystemExit as exc:
        return exc.code
    return 0


def land(repo, text):
    (Path(repo) / "f.txt").write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", text)
    return git(repo, "rev-parse", "HEAD")


def finalize(payload, response=True):
    full = dict(payload, hook_event_name="PostToolUse" if response else "PostToolUseFailure")
    if response:
        full["tool_response"] = {"stdout": "", "stderr": "", "interrupted": False}
    else:
        full["error"] = "exit 1"
    saved = sys.stdin
    sys.stdin = io.StringIO(json.dumps(full))
    try:
        FINALIZER.main()
    except SystemExit as exc:
        return exc.code
    finally:
        sys.stdin = saved
    return None


def no_lock_or_use_files(state):
    return not glob.glob(os.path.join(state, "*.lck")) and not glob.glob(os.path.join(state, "*.use"))


def test_one_dispatch_commits_every_planned_repository_and_no_other_subagent_does(world):
    state = os.environ["CLAUDE_STATE_DIR"]
    first = make_repo(world / "toy")
    second = make_repo(world / "home")
    g1, _ = mint(state, first)
    g2, _ = mint(state, second)
    analyst = dispatch("TASK_ID=20261028-100000\nDRYRUN=false\n<obligation v=\"1\">{}</obligation>")
    attestation = glob.glob(CP.attestation_glob(SID))[0]
    attestation_bytes = Path(attestation).read_bytes()

    p1 = commit_payload(first, analyst, "toolu_first")
    assert evaluate(p1) == 0
    assert not os.path.exists(g1)
    pointer = json.loads(Path(CJ.pointer_path(CJ.event_key(p1))).read_text())
    assert pointer["repo_root"] == git(first, "rev-parse", "--show-toplevel")
    assert pointer["tool_use_id"] == "toolu_first" and pointer["sid"] == SID
    land(first, "one")
    assert finalize(p1) == 0
    assert not os.path.exists(CJ.pointer_path(CJ.event_key(p1)))

    other = dispatch("a dev dispatch prompt", subagent_type="dev")
    intruder = commit_payload(second, other, "toolu_intruder")
    assert evaluate(intruder) == 2
    assert os.path.exists(g2), "a refused caller must not spend the grant"

    p2 = commit_payload(second, analyst, "toolu_second")
    assert evaluate(p2) == 0
    assert not os.path.exists(g2)
    assert Path(attestation).read_bytes() == attestation_bytes, "the attestation is never rewritten"
    assert no_lock_or_use_files(state)


def test_main_agent_and_a_spent_grant_are_refused(world):
    state = os.environ["CLAUDE_STATE_DIR"]
    repo = make_repo(world / "toy")
    grant, _ = mint(state, repo)
    analyst = dispatch("TASK_ID=20261028-100000")
    main_agent = commit_payload(repo, analyst, "toolu_main")
    main_agent.pop("agent_id")
    assert evaluate(main_agent) == 2
    assert os.path.exists(grant)
    assert evaluate(commit_payload(repo, analyst, "toolu_a")) == 0
    # The commit failed: the grant does not come back, so the same commit again is refused.
    assert evaluate(commit_payload(repo, analyst, "toolu_b")) == 2


def test_spending_is_an_unlink_only_one_event_wins(world):
    state = os.environ["CLAUDE_STATE_DIR"]
    repo = make_repo(world / "toy")
    grant, _ = mint(state, repo)
    assert GUARD._spend_grant(grant) is True
    assert GUARD._spend_grant(grant) is False


def test_success_journals_from_the_pointer_and_reconciliation_attributes_the_commit(world):
    state = os.environ["CLAUDE_STATE_DIR"]
    repo = make_repo(world / "toy")
    _, grant = mint(state, repo)
    analyst = dispatch("TASK_ID=20261028-100000")
    payload = commit_payload(repo, analyst, "toolu_ok")
    payload["session_id"] = "sid-subagent-view"
    assert evaluate(payload) == 0
    head = land(repo, "landed")
    assert finalize(payload) == 0
    entries = [json.loads(line) for line in open(CJ.journal_path(repo))]
    assert len(entries) == 1
    assert entries[0]["parent_head"] == grant["expected_head"] and entries[0]["resulting_head"] == head
    # The session the grant was minted under and the subagent's own payload session both match.
    for sid in (SID, "sid-subagent-view"):
        assert CJ.find_attributable_event(repo, head, grant["task_id"], sid) is not None
    assert CJ._main(["commit_journal.py", "query", "--repo-root", repo, "--head", head,
                     "--task-id", grant["task_id"], "--session-id", SID]) == 0


def test_failure_and_background_receipt_journal_nothing(world):
    state = os.environ["CLAUDE_STATE_DIR"]
    repo = make_repo(world / "toy")
    mint(state, repo)
    analyst = dispatch("TASK_ID=20261028-100000")
    failed = commit_payload(repo, analyst, "toolu_fail")
    assert evaluate(failed) == 0
    assert finalize(failed, response=False) == 0
    assert not os.path.exists(CJ.journal_path(repo))
    assert not os.path.exists(CJ.pointer_path(CJ.event_key(failed)))

    mint(state, repo)
    receipt = commit_payload(repo, analyst, "toolu_bg")
    assert evaluate(receipt) == 0
    full = dict(receipt, hook_event_name="PostToolUse",
                tool_response={"stdout": "", "stderr": "", "interrupted": False, "backgroundTaskId": "b1"})
    saved = sys.stdin
    sys.stdin = io.StringIO(json.dumps(full))
    try:
        FINALIZER.main()
    except SystemExit:
        pass
    finally:
        sys.stdin = saved
    assert os.path.exists(CJ.pointer_path(CJ.event_key(receipt))), "a nonterminal receipt finalizes nothing"


def test_an_event_with_no_pointer_of_its_own_acts_on_nothing(world):
    state = os.environ["CLAUDE_STATE_DIR"]
    repo = make_repo(world / "toy")
    mint(state, repo)
    analyst = dispatch("TASK_ID=20261028-100000")
    owner = commit_payload(repo, analyst, "toolu_owner")
    assert evaluate(owner) == 0
    land(repo, "landed")
    stranger = dict(owner, tool_use_id="toolu_stranger")
    assert finalize(stranger) == 0
    assert os.path.exists(CJ.pointer_path(CJ.event_key(owner)))
    assert not os.path.exists(CJ.journal_path(repo))


def test_a_derived_name_collision_is_not_finalized_by_the_other_raw_id(world):
    state = os.environ["CLAUDE_STATE_DIR"]
    repo = make_repo(world / "toy")
    mint(state, repo)
    analyst = dispatch("TASK_ID=20261028-100000")
    owner = commit_payload(repo, analyst, "toolu_a.b")
    assert evaluate(owner) == 0
    twin = dict(owner, tool_use_id="toolu_a/b")
    assert CJ.event_key(twin) == CJ.event_key(owner)
    land(repo, "landed")
    assert finalize(twin) == 0
    assert os.path.exists(CJ.pointer_path(CJ.event_key(owner)))
    assert not os.path.exists(CJ.journal_path(repo))


def test_the_pointer_is_never_taken_for_a_grant(world):
    state = os.environ["CLAUDE_STATE_DIR"]
    repo = make_repo(world / "toy")
    _, grant = mint(state, repo)
    os.unlink(glob.glob(os.path.join(state, "claude-commit-grant-*.json"))[0])
    assert CJ.write_event_pointer("tu-x", "x", grant)
    assert GUARD._collect_commit_grant_candidates() == []
    assert not GUARD._has_active_commit_grant("")
    REVOKER._revoke_grants_for_task(state, grant["task_id"], SID)
    assert os.path.exists(CJ.pointer_path("tu-x"))


def test_stale_reading_reaps_old_pointers_and_spares_fresh_and_live_ones(world, monkeypatch):
    state = os.environ["CLAUDE_STATE_DIR"]
    repo = make_repo(world / "toy")
    fields = {"task_id": "t", "repo_root": repo, "branch": "master", "expected_head": "x", "sid": SID}
    for key in ("tu-old", "tu-fresh", "tu-junk"):
        assert CJ.write_event_pointer(key, key, fields)
    Path(CJ.pointer_path("tu-junk")).write_text("{not json")
    for key in ("tu-old", "tu-junk"):
        stamp = time.time() - CJ.POINTER_STALE_SECONDS - 5
        os.utime(CJ.pointer_path(key), (stamp, stamp))
    monkeypatch.setattr(CJ, "live_commit_repos", lambda: {os.path.realpath(repo)})
    assert CJ.reap_stale_pointers() == 1  # only the junk one: the repo has a live commit
    monkeypatch.setattr(CJ, "live_commit_repos", lambda: set())
    assert CJ.reap_stale_pointers() == 1
    assert sorted(os.path.basename(p) for p in glob.glob(CJ.POINTER_GLOB)) == [CJ.POINTER_PREFIX + "tu-fresh.json"]


def test_a_fifo_at_a_pointer_name_does_not_stall_the_reader(world):
    state = os.environ["CLAUDE_STATE_DIR"]
    fifo = CJ.pointer_path("tu-fifo")
    os.mkfifo(fifo)
    started = time.monotonic()
    parsed, ident = CJ.read_untrusted_json_ident(fifo)
    assert parsed is None and ident is not None and time.monotonic() - started < 2
    assert CJ.unlink_verified(fifo, ident)
    assert os.listdir(state) == []


def test_stop_cleanup_takes_the_deciders_readings(world):
    state = Path(os.environ["CLAUDE_STATE_DIR"])
    now = datetime.now(timezone.utc)
    sentinels = {
        "live": {"kind": "bulk-commit", "origin": "userpromptsubmit-hook",
                 "expires_at": (now + timedelta(minutes=5)).isoformat()},
        "expired": {"kind": "bulk-commit", "origin": "userpromptsubmit-hook",
                    "expires_at": (now - timedelta(minutes=5)).isoformat()},
        "cli": {"kind": "bulk-commit", "origin": "cli",
                "expires_at": (now + timedelta(minutes=5)).isoformat()},
    }
    for name, body in sentinels.items():
        (state / f"claude-bulk-commit-sentinel-{name}-n.json").write_text(json.dumps(body))
    (state / "claude-bulk-commit-sentinel-junk-n.json").write_text("{")
    fields = {"task_id": "t", "repo_root": str(world / "gone"), "branch": "b", "expected_head": "x", "sid": SID}
    old = state / (CJ.POINTER_PREFIX + "tu-old.json")
    fresh = state / (CJ.POINTER_PREFIX + "tu-fresh.json")
    for path in (old, fresh):
        path.write_text(json.dumps(fields))
    stamp = time.time() - CJ.POINTER_STALE_SECONDS - 5
    os.utime(old, (stamp, stamp))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(["bash", str(HOOKS / "stop-cleanup-allowlist.sh")], input=json.dumps({"session_id": SID}),
                          text=True, capture_output=True, env=env)
    assert proc.returncode == 0
    assert sorted(p.name for p in state.glob("claude-bulk-commit-sentinel-*")) == [
        "claude-bulk-commit-sentinel-live-n.json"]
    assert not old.exists() and fresh.exists()
    assert "reaped 3 bulk-commit sentinels, 1 commit-event pointers" in proc.stdout
    for name, body in sentinels.items():
        assert CP.bulk_commit_sentinel_live(body) == (name == "live")


def test_an_event_with_no_key_is_authorized_and_left_unjournaled(world):
    state = os.environ["CLAUDE_STATE_DIR"]
    repo = make_repo(world / "toy")
    grant, _ = mint(state, repo)
    analyst = dispatch("TASK_ID=20261028-100000")
    payload = commit_payload(repo, analyst, "")
    payload.pop("tool_use_id")
    assert evaluate(payload) == 0
    assert not os.path.exists(grant)
    assert glob.glob(CJ.POINTER_GLOB) == []


def test_a_taken_pointer_name_is_never_overwritten(world):
    fields = {"task_id": "t", "repo_root": "/r", "branch": "b", "expected_head": "h", "sid": SID}
    assert CJ.write_event_pointer("tu-same", "first", fields)
    assert not CJ.write_event_pointer("tu-same", "second", fields)
    assert json.loads(Path(CJ.pointer_path("tu-same")).read_text())["tool_use_id"] == "first"
    assert [p for p in os.listdir(os.environ["CLAUDE_STATE_DIR"]) if ".wip." in p] == []


def test_an_unlink_acts_only_on_the_instance_that_was_read(world):
    fields = {"task_id": "t", "repo_root": "/r", "branch": "b", "expected_head": "h", "sid": SID}
    assert CJ.write_event_pointer("tu-aba", "old", fields)
    _, ident = CJ.read_untrusted_json_ident(CJ.pointer_path("tu-aba"))
    # Keep the read inode alive elsewhere, so the replacement cannot reuse its number.
    os.link(CJ.pointer_path("tu-aba"), str(world / "held"))
    os.unlink(CJ.pointer_path("tu-aba"))
    assert CJ.write_event_pointer("tu-aba", "replacement", fields)
    assert not CJ.unlink_verified(CJ.pointer_path("tu-aba"), ident)
    assert json.loads(Path(CJ.pointer_path("tu-aba")).read_text())["tool_use_id"] == "replacement"
