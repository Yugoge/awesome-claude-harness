#!/usr/bin/env python3
"""Tests for the write-time attribution journal (Phase 0): capture, chain fold,
break detection, verify script verdicts, torn-tail handling, seal.

Run: python3 -m pytest hooks/tests/test_attribution_journal.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "hooks"))
from lib import attribution_journal as aj  # noqa: E402
sys.path.insert(0, str(ROOT))  # for hooks.doc_sync.* (namespace package import)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


verify = _load("verify_attr", "scripts/verify-attribution-chain.py")
seal = _load("seal_attr", "scripts/seal-attribution-journal.py")


def _env(tmp, monkeypatch):
    gd = tmp / "odb.git"
    subprocess.run(["git", "init", "--bare", "-q", str(gd)], check=True)
    monkeypatch.setenv("ATTRIBUTION_STATE_DIR", str(tmp / "state"))
    monkeypatch.setenv("ATTRIBUTION_GIT_DIR", str(gd))
    monkeypatch.delenv("CLAUDE_TASK_ID", raising=False)
    # Autoseal is wired into record_post's hook entrypoint (not record_post
    # itself -- see test_hook_entry_points_via_stdin), but that hook entrypoint
    # IS exercised below via real subprocess calls. Default it OFF here so
    # every pre-existing test stays hermetic (no real seal, no write outside
    # tmp); autoseal-specific tests re-enable it explicitly and point
    # ATTRIBUTION_SEAL_DEST into tmp.
    monkeypatch.setenv("ATTRIBUTION_AUTOSEAL_DISABLE", "1")
    monkeypatch.delenv("ATTRIBUTION_SEAL_DEST", raising=False)
    repo = tmp / "repo"                      # hermetic harness worktree for shell measurement
    if not repo.exists():
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-q", "--allow-empty", "-m", "i"], check=True)
    monkeypatch.setenv("ATTRIBUTION_HARNESS_ROOT", str(repo))
    return gd


def _run(tool, tool_input, sid, inv, mutate, cwd):
    pl = {"tool_name": tool, "tool_input": tool_input, "session_id": sid,
          "tool_use_id": inv, "cwd": str(cwd)}
    aj.record_pre(pl)
    mutate()
    return aj.record_post(pl)


def _ev(sid, seq, pre, post, ts, path="/x"):
    return {"seq": seq, "session_id": sid, "path": path, "pre_sha": pre, "post_sha": post,
            "ts": ts, "tool": "Edit", "invocation_id": f"{sid}-{seq}"}


def test_capture_file_edit(tmp_path, monkeypatch):
    gd = _env(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDE_TASK_ID", "T1")
    f = tmp_path / "a.txt"
    f.write_text("one")
    n = _run("Edit", {"file_path": str(f)}, "s1", "tu1", lambda: f.write_text("two"), tmp_path)
    assert n == 1
    evs, bad = aj.read_all_journals()
    assert not bad and len(evs) == 1
    e = evs[0]
    assert e["path"] == str(f) and e["tool"] == "Edit" and e["invocation_id"] == "tu1"
    assert e["task_id"] == "T1" and e["seq"] == 1 and e["session_id"] == "s1"
    assert e["pre_sha"] != e["post_sha"]
    # blobs recoverable from the object database
    for sha, want in ((e["pre_sha"], b"one"), (e["post_sha"], b"two")):
        out = subprocess.run(["git", "--git-dir", str(gd), "cat-file", "blob", sha],
                             capture_output=True, check=True).stdout
        assert out == want
    # pending sidecar consumed
    assert not any(aj.pending_dir().rglob("*.json"))


def test_capture_creation_has_absent_pre(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    f = tmp_path / "new.txt"
    _run("Write", {"file_path": str(f)}, "s1", "tu1", lambda: f.write_text("x"), tmp_path)
    e = aj.read_all_journals()[0][0]
    assert e["pre_sha"] == aj.ABSENT and e["post_sha"] != aj.ABSENT


def test_capture_shell_write_targets_relative_to_cwd(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    out = tmp_path / "out.txt"
    cmd = "echo hi > out.txt && echo ignored > /dev/null"
    n = _run("Bash", {"command": cmd}, "s1", "tu1", lambda: out.write_text("hi\n"), tmp_path)
    assert n == 1
    e = aj.read_all_journals()[0][0]
    assert e["path"] == str(out) and e["tool"] == "Bash" and e["pre_sha"] == aj.ABSENT


def test_hook_entry_points_via_stdin(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    f = tmp_path / "e.txt"
    f.write_text("1")
    pl = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(f)},
                     "session_id": "sx", "tool_use_id": "tuX", "cwd": str(tmp_path)})
    for hook in ("pretool-attribution-pre.py", "posttool-attribution-post.py"):
        if hook.startswith("posttool"):
            f.write_text("2")
        r = subprocess.run([sys.executable, str(ROOT / "hooks" / hook)], input=pl, text=True,
                           capture_output=True, env=dict(os.environ))
        assert r.returncode == 0 and r.stdout == ""
    evs = aj.read_all_journals()[0]
    assert len(evs) == 1 and evs[0]["session_id"] == "sx"


def test_non_mutating_tool_is_ignored(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    assert _run("Bash", {"command": "ls -la"}, "s1", "tu1", lambda: None, tmp_path) == 0
    assert aj.read_all_journals()[0] == []


def test_two_sessions_interleaving_one_file_chain_continuous(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    f = tmp_path / "shared.txt"
    f.write_text("v0")
    for sid, inv, val in (("sA", "1", "v1"), ("sB", "1", "v2"), ("sA", "2", "v3"), ("sB", "2", "v4")):
        _run("Edit", {"file_path": str(f)}, sid, inv, lambda v=val: f.write_text(v), tmp_path)
    evs, _ = aj.read_all_journals()
    assert {e["session_id"] for e in evs} == {"sA", "sB"}
    assert len(list(aj.journal_dir().glob("*.jsonl"))) == 2   # one journal per session
    r = verify.verify_path(str(f), [e for e in evs if e["path"] == str(f)])
    assert r["verdict"] == "CONTINUOUS_TAIL_MATCH"


def test_unjournaled_write_detected_as_break_via_real_capture(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    f = tmp_path / "f.txt"
    f.write_text("v0")
    _run("Edit", {"file_path": str(f)}, "sA", "1", lambda: f.write_text("v1"), tmp_path)
    f.write_text("sneaky")                      # bypasses hooks
    _run("Edit", {"file_path": str(f)}, "sB", "1", lambda: f.write_text("v2"), tmp_path)
    r = verify.verify_path(str(f), [e for e in aj.read_all_journals()[0] if e["path"] == str(f)])
    assert r["verdict"] == "BREAK"
    b = r["segments"][0]
    assert b["before"]["session_id"] == "sA" and b["after"]["session_id"] == "sB"
    assert b["hash_before"] != b["hash_after"]


def test_fold_fixture_continuous_with_revisited_state():
    # A->B->A->C : revisits state A; order must not depend on timestamps
    evs = [_ev("s1", 1, "A", "B", 9), _ev("s2", 1, "B", "A", 1), _ev("s1", 2, "A", "C", 5)]
    r = verify.verify_path("/x", evs, disk_hash="C")
    assert r["verdict"] == "CONTINUOUS_TAIL_MATCH"


def test_fold_fixture_tail_mismatch():
    r = verify.verify_path("/x", [_ev("s1", 1, "A", "B", 1), _ev("s1", 2, "B", "C", 2)], disk_hash="Z")
    assert r["verdict"] == "CONTINUOUS_TAIL_MISMATCH"
    assert r["last_event"]["post_sha"] == "C" and r["disk_sha"] == "Z"


def test_fold_fixture_break_precise_bracketing():
    evs = [_ev("s1", 1, "A", "B", 1), _ev("s2", 1, "B", "C", 2),
           _ev("s1", 2, "X", "Y", 3), _ev("s2", 2, "Y", "Z", 4)]   # C != X : break
    r = verify.verify_path("/x", evs, disk_hash="Z")
    assert r["verdict"] == "BREAK" and len(r["segments"]) == 1
    b = r["segments"][0]
    assert (b["before"]["session_id"], b["before"]["seq"], b["hash_before"]) == ("s2", 1, "C")
    assert (b["after"]["session_id"], b["after"]["seq"], b["hash_after"]) == ("s1", 2, "X")


def test_fold_fixture_two_breaks():
    evs = [_ev("s", 1, "A", "B", 1), _ev("s", 2, "C", "D", 2), _ev("s", 3, "E", "F", 3)]
    r = verify.verify_path("/x", evs, disk_hash="F")
    assert r["verdict"] == "BREAK" and len(r["segments"]) == 2


def test_verify_script_cli_verdicts(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    f = tmp_path / "c.txt"
    f.write_text("0")
    _run("Edit", {"file_path": str(f)}, "s1", "1", lambda: f.write_text("1"), tmp_path)
    cmd = [sys.executable, str(ROOT / "scripts" / "verify-attribution-chain.py"), "--file", str(f)]
    r = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ))
    assert r.returncode == 0 and "CONTINUOUS_TAIL_MATCH" in r.stdout
    f.write_text("tampered")
    r = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ))
    assert r.returncode == 1 and "CONTINUOUS_TAIL_MISMATCH" in r.stdout
    # fixture journal with a real break
    jd = tmp_path / "fx"
    jd.mkdir()
    lines = [_ev("s1", 1, "A", "B", 1, "/fx"), _ev("s1", 2, "X", "Y", 2, "/fx")]
    (jd / "s1.jsonl").write_text("\n".join(json.dumps(e) for e in lines) + "\n")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify-attribution-chain.py"),
                        "--journal-dir", str(jd)], capture_output=True, text=True)
    assert r.returncode == 1 and "BREAK" in r.stdout and "post_sha=B" in r.stdout and "pre_sha=X" in r.stdout


def test_torn_tail_detected_discarded_remainder_intact(tmp_path):
    good = [_ev("s1", 1, "A", "B", 1), _ev("s1", 2, "B", "C", 2)]
    jp = tmp_path / "s1.jsonl"
    jp.write_text("\n".join(json.dumps(e) for e in good) + "\n" + '{"seq": 3, "session_id": "s1", "pa')
    evs, bad = aj.read_journal(jp)
    assert [e["seq"] for e in evs] == [1, 2]
    assert len(bad) == 1 and bad[0]["torn_tail"] is True


def test_malformed_mid_line_discarded(tmp_path):
    jp = tmp_path / "s1.jsonl"
    jp.write_text(json.dumps(_ev("s1", 1, "A", "B", 1)) + "\nnot json\n" + json.dumps({"seq": 2}) + "\n"
                  + json.dumps(_ev("s1", 3, "B", "C", 3)) + "\n")
    evs, bad = aj.read_journal(jp)
    assert [e["seq"] for e in evs] == [1, 3] and len(bad) == 2


def test_writer_fences_off_torn_tail(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    jp = aj.journal_dir() / "s1.jsonl"
    jp.parent.mkdir(parents=True)
    jp.write_text(json.dumps(_ev("s1", 1, "A", "B", 1)) + "\n" + '{"seq": 2, "sess')
    aj.append_events("s1", [{"session_id": "s1", "path": "/x", "pre_sha": "B", "post_sha": "C",
                             "ts": 3, "tool": "Edit", "invocation_id": "n"}])
    evs, bad = aj.read_journal(jp)
    assert len(evs) == 2 and len(bad) == 1 and evs[1]["post_sha"] == "C"


def test_seal_copies_journals_and_blobs_to_dest(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    f = tmp_path / "s.txt"
    f.write_text("p")
    _run("Edit", {"file_path": str(f)}, "s1", "1", lambda: f.write_text("q"), tmp_path)
    e = aj.read_all_journals()[0][0]
    dest = tmp_path / "seal"
    res = seal.seal(dest, allow_volatile=True)
    assert res["journals_copied"] == 1 and res["blobs_added"] == 2 and not res["blobs_missing_in_source"]
    assert (dest / "journals" / "s1.jsonl").read_bytes() == (aj.journal_dir() / "s1.jsonl").read_bytes()
    out = subprocess.run(["git", "--git-dir", str(dest / "objects.git"), "cat-file", "blob", e["post_sha"]],
                         capture_output=True, check=True).stdout
    assert out == b"q"
    assert seal.seal(dest, allow_volatile=True)["blobs_added"] == 0   # idempotent


def test_seal_refuses_ram_backed_dest(tmp_path, monkeypatch):
    import pytest
    _env(tmp_path, monkeypatch)
    ram = Path("/dev/shm/attr-seal-refuse-test")
    if seal.mount_class(Path("/dev/shm"))["persistent"]:
        pytest.skip("/dev/shm not RAM-backed here")
    with pytest.raises(SystemExit):
        seal.seal(ram)
    assert not ram.exists() or not any(ram.iterdir())


def test_dev_shm_paths_are_captured_but_device_sinks_are_not():
    tgt = aj.extract_targets("Edit", {"file_path": "/dev/shm/x/y.py"}, "/")
    assert tgt == ["/dev/shm/x/y.py"]
    assert aj.extract_targets("Bash", {"command": "echo a > /dev/null 2>/dev/stderr"}, "/") == []
    assert aj.extract_targets("Bash", {"command": "echo a > /dev/shm/q.txt"}, "/") == ["/dev/shm/q.txt"]


# ---------------------------------------------------- measured shell capture

def _repo(tmp_path):
    return tmp_path / "repo"


def _events_for(path):
    return [e for e in aj.read_all_journals()[0] if e["path"] == str(path)]


def test_interpreter_heredoc_write_is_measured(tmp_path, monkeypatch):
    # the diagnosed pattern: a heredoc feeds a python program that opens files for writing;
    # the command line names no target, so the parser sees nothing -- measurement must.
    _env(tmp_path, monkeypatch)
    f = _repo(tmp_path) / "ticket.md"
    f.write_text("old\n")
    cmd = "python3 - <<'PY'\nopen('ticket.md','w').write('new\\n')\nPY"
    assert aj.extract_targets("Bash", {"command": cmd}, str(_repo(tmp_path))) == []
    n = _run("Bash", {"command": cmd}, "s1", "tu1", lambda: f.write_text("new\n"), _repo(tmp_path))
    assert n == 1
    e = _events_for(f)[0]
    assert e["measured"] is True and e["tool"] == "Bash"
    assert e["pre_sha"] != e["post_sha"] and e["pre_sha"] != aj.ABSENT
    r = verify.verify_path(str(f), _events_for(f), disk_hash=aj.hash_file(str(f)))
    assert r["verdict"] == "CONTINUOUS_TAIL_MATCH"


def test_new_file_via_script_is_measured_with_absent_pre(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    f = _repo(tmp_path) / "sub" / "made.txt"
    def mutate():
        f.parent.mkdir()
        f.write_text("created by script")
    _run("Bash", {"command": "python3 gen.py"}, "s1", "tu1", mutate, _repo(tmp_path))
    e = _events_for(f)[0]
    assert e["pre_sha"] == aj.ABSENT and e["post_sha"] != aj.ABSENT and e["measured"] is True


def test_truncation_and_deletion_are_measured(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    repo = _repo(tmp_path)
    a, b = repo / "a.txt", repo / "b.txt"
    a.write_text("keep me")
    b.write_text("delete me")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "-m", "files"], check=True)

    def mutate():
        a.write_text("")
        b.unlink()
    n = _run("Bash", {"command": "python3 wipe.py"}, "s1", "tu1", mutate, repo)
    assert n == 2
    ea, eb = _events_for(a)[0], _events_for(b)[0]
    assert ea["post_sha"] == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391" and ea["pre_sha"] != ea["post_sha"]
    assert eb["post_sha"] == aj.ABSENT and eb["pre_sha"] != aj.ABSENT


def test_unchanged_dirty_file_emits_no_event_and_changed_dirty_one_does(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    repo = _repo(tmp_path)
    quiet, busy = repo / "quiet.txt", repo / "busy.txt"
    quiet.write_text("q")
    busy.write_text("1")
    n = _run("Bash", {"command": "python3 x.py"}, "s1", "tu1", lambda: busy.write_text("2"), repo)
    assert n == 1 and _events_for(quiet) == [] and len(_events_for(busy)) == 1


def test_out_of_repo_named_path_uses_parser_hint(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    out = tmp_path / "elsewhere.txt"
    cmd = f"echo hi > {out}"
    n = _run("Bash", {"command": cmd}, "s1", "tu1", lambda: out.write_text("hi\n"), _repo(tmp_path))
    assert n == 1
    e = _events_for(out)[0]
    assert "measured" not in e and e["pre_sha"] == aj.ABSENT


def test_gitignored_in_repo_file_named_by_command_is_still_captured(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("ign.txt\n")
    f = repo / "ign.txt"
    n = _run("Bash", {"command": "echo z > ign.txt"}, "s1", "tu1", lambda: f.write_text("z\n"), repo)
    assert len(_events_for(f)) == 1 and n >= 1


def test_measured_overhead_reported(tmp_path, monkeypatch, capsys):
    import time
    _env(tmp_path, monkeypatch)
    repo = _repo(tmp_path)
    for i in range(50):
        (repo / f"f{i}.txt").write_text(str(i))
    pl = {"tool_name": "Bash", "tool_input": {"command": "true"}, "session_id": "s", "tool_use_id": "t", "cwd": str(repo)}
    t0 = time.perf_counter()
    aj.record_pre(pl)
    t1 = time.perf_counter()
    aj.record_post(pl)
    t2 = time.perf_counter()
    print(f"overhead pre={1000*(t1-t0):.0f}ms post={1000*(t2-t1):.0f}ms (50 dirty files)")
    assert (t2 - t0) < 5


def _dup(sid, seq, pre, post, ts, agent=None):
    e = _ev(sid, seq, pre, post, ts)
    if agent:
        e["agent_id"] = agent
    return e


def test_duplicate_identical_transition_collapses_continuous():
    evs = [_ev("s1", 1, "A", "B", 1), _dup("s2", 1, "A", "B", 1.1, "ag2"), _ev("s1", 2, "B", "C", 2)]
    r = verify.verify_path("/x", evs, disk_hash="C")
    assert r["verdict"] == "CONTINUOUS_TAIL_MATCH"
    assert r["events"] == 3


def test_duplicate_witnesses_and_ambiguous_writer_flag():
    evs = [_dup("s1", 1, "A", "B", 1, "ag1"), _dup("s2", 1, "A", "B", 1.1, "ag2")]
    r = verify.verify_path("/x", evs, disk_hash="B")
    assert r["ambiguous_writer"] is True
    (c,) = r["collapsed_edges"]
    assert c["ambiguous_writer"] is True and len(c["witnesses"]) == 2
    assert {w["session_id"] for w in c["writers"]} == {"s1", "s2"}
    assert {w["agent_id"] for w in c["witnesses"]} == {"ag1", "ag2"}


def test_duplicate_same_writer_not_ambiguous():
    evs = [_dup("s1", 1, "A", "B", 1, "ag1"), _dup("s1", 2, "A", "B", 1.1, "ag1")]
    r = verify.verify_path("/x", evs, disk_hash="B")
    assert r["verdict"] == "CONTINUOUS_TAIL_MATCH"
    assert r["ambiguous_writer"] is False and len(r["collapsed_edges"][0]["witnesses"]) == 2


def test_divergent_duplicate_remains_break():
    evs = [_ev("s1", 1, "A", "B", 1), _ev("s2", 1, "A", "D", 1.1)]
    r = verify.verify_path("/x", evs, disk_hash="B")
    assert r["verdict"] == "BREAK"


def test_spanning_window_edge_absorbed_and_flagged():
    evs = [_ev("s1", 1, "absent", "B", 1), _ev("s1", 2, "B", "C", 2), _dup("s2", 1, "absent", "C", 2.1, "ag2")]
    r = verify.verify_path("/x", evs, disk_hash="C")
    assert r["verdict"] == "CONTINUOUS_TAIL_MATCH"
    assert r["ambiguous_writer"] is True and len(r["spanning_edges"]) == 1


def test_fork_to_unreachable_state_still_breaks_with_spanning_rule():
    evs = [_ev("s1", 1, "A", "B", 1), _ev("s1", 2, "B", "C", 2), _ev("s2", 1, "A", "D", 2.1)]
    assert verify.verify_path("/x", evs, disk_hash="C")["verdict"] == "BREAK"


# ------------------------------------------------- automatic periodic sealing

def _autoseal_env(tmp, monkeypatch):
    """Re-enable autoseal (off by default via _env) scoped entirely to tmp."""
    dest = tmp / "seal-dest"
    monkeypatch.setenv("ATTRIBUTION_AUTOSEAL_DISABLE", "0")
    monkeypatch.setenv("ATTRIBUTION_SEAL_DEST", str(dest))
    return dest


def test_autoseal_skips_when_not_due_then_seals_when_due(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    dest = _autoseal_env(tmp_path, monkeypatch)
    f = tmp_path / "a.txt"
    f.write_text("1")
    _run("Edit", {"file_path": str(f)}, "s1", "1", lambda: f.write_text("2"), tmp_path)
    first = seal.autoseal_if_due(dest, interval=3600, allow_volatile=True)
    assert first is not None and first["status"] == "ok" and first["trigger"] == "auto"
    assert first["result"]["journals_copied"] == 1
    second = seal.autoseal_if_due(dest, interval=3600, allow_volatile=True)
    assert second is None                                   # not due yet
    assert seal.read_last_evidence(dest) == first            # log unchanged


def test_autoseal_forced_repeat_is_idempotent_and_logs_both_attempts(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    dest = _autoseal_env(tmp_path, monkeypatch)
    f = tmp_path / "a.txt"
    f.write_text("1")
    _run("Edit", {"file_path": str(f)}, "s1", "1", lambda: f.write_text("2"), tmp_path)
    first = seal.autoseal_if_due(dest, interval=0, allow_volatile=True)
    second = seal.autoseal_if_due(dest, interval=0, allow_volatile=True)   # interval=0 -> always due
    assert first["result"]["blobs_added"] == 2 and first["result"]["journals_copied"] == 1
    assert second["result"]["blobs_added"] == 0 and second["result"]["journals_copied"] == 0
    lines = seal.evidence_log_path(dest).read_text().strip().splitlines()
    assert len(lines) == 2 and all(json.loads(l)["status"] == "ok" for l in lines)


def test_autoseal_refuses_volatile_dest_records_error_evidence(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    ram = Path("/dev/shm/attr-autoseal-refuse-test")
    if seal.mount_class(Path("/dev/shm"))["persistent"]:
        import pytest
        pytest.skip("/dev/shm not RAM-backed here")
    entry = seal.autoseal_if_due(ram, interval=0, allow_volatile=False)
    assert entry["status"] == "error" and "refusing" in entry["error"]
    assert seal.read_last_evidence(ram) == entry
    if ram.exists():
        import shutil as _sh
        _sh.rmtree(ram, ignore_errors=True)


def test_autoseal_disabled_by_default_is_a_true_noop(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)          # leaves ATTRIBUTION_AUTOSEAL_DISABLE=1
    monkeypatch.setenv("ATTRIBUTION_SEAL_DEST", str(tmp_path / "would-be-dest"))
    f = tmp_path / "a.txt"
    f.write_text("1")
    _run("Edit", {"file_path": str(f)}, "s1", "1", lambda: f.write_text("2"), tmp_path)
    aj.autoseal_hook_trigger()
    assert not (tmp_path / "would-be-dest").exists()


def test_posttool_hook_autoseals_end_to_end_via_real_subprocess(tmp_path, monkeypatch):
    """The production wiring: posttool-attribution-post.py -> record_post ->
    autoseal_hook_trigger -> seal-attribution-journal.py, as one subprocess
    call, exactly as settings.json invokes it. Must stay silent on stdout
    (the hook's stdout contract) while still producing a durable, checkable
    seal-log.jsonl entry."""
    _env(tmp_path, monkeypatch)
    dest = _autoseal_env(tmp_path, monkeypatch)
    monkeypatch.setenv("ATTRIBUTION_SEAL_INTERVAL_SECONDS", "0")   # always due
    f = tmp_path / "e.txt"
    f.write_text("1")
    pl = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(f)},
                     "session_id": "sx", "tool_use_id": "tuX", "cwd": str(tmp_path)})
    f.write_text("2")
    r = subprocess.run([sys.executable, str(ROOT / "hooks" / "posttool-attribution-post.py")],
                       input=pl, text=True, capture_output=True, env=dict(os.environ))
    assert r.returncode == 0 and r.stdout == ""
    last = seal.read_last_evidence(dest)
    assert last is not None and last["status"] == "ok" and last["trigger"] == "auto"


# ----------------------------------- known boundary: hook-written side effects

def test_doc_sync_regen_outside_capture_window_surfaces_as_break(tmp_path, monkeypatch):
    """Known, ruled boundary (docs/reference/attribution-journal-phase0-facility.md
    #3): a file written by a DIFFERENT PostToolUse hook as a side effect of
    editing a sibling file (doc-sync regenerating INDEX.md) is captured by
    NEITHER this call's single-target measurement NOR a Bash dirty-worktree
    scan -- it is simply never the declared target. This uses the REAL
    hooks.doc_sync.regen_index producer (not a synthetic stand-in) to pin the
    ruled detection signature: an otherwise-ordinary chain BREAK on the
    hook-managed path, with no distinguishing flag of its own."""
    _env(tmp_path, monkeypatch)
    repo = _repo(tmp_path)
    from hooks.doc_sync.regen_index import regen_index
    from hooks.doc_sync.regions import RegenStatus
    watched_dir = repo / "hooks"
    watched_dir.mkdir()
    sibling = watched_dir / "sibling.py"
    sibling.write_text("# v1\n")
    index_path = watched_dir / "INDEX.md"
    assert regen_index(watched_dir, repo) is RegenStatus.WRITTEN   # pre-history: uncaptured, by design
    # session s1 directly (and correctly) captures a hand-note edit to INDEX.md
    _run("Edit", {"file_path": str(index_path)}, "s1", "1",
         lambda: index_path.write_text(index_path.read_text() + "\nHand note.\n"), watched_dir)
    # doc-sync regenerates INDEX.md as an UNCAPTURED side effect of a sibling edit
    sibling.write_text("# v2\n")
    assert regen_index(watched_dir, repo) is RegenStatus.WRITTEN
    # session s2 later edits INDEX.md directly; capture resumes from whatever is on disk NOW
    _run("Edit", {"file_path": str(index_path)}, "s2", "1",
         lambda: index_path.write_text(index_path.read_text() + "\nAnother note.\n"), watched_dir)
    events = [e for e in aj.read_all_journals()[0] if e["path"] == str(index_path)]
    assert len(events) == 2
    r = verify.verify_path(str(index_path), events)
    assert r["verdict"] == "BREAK"
    (b,) = r["segments"]
    assert b["before"]["session_id"] == "s1" and b["after"]["session_id"] == "s2"
