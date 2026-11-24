"""The session's owner record (<root>/<sid>/.owner, hooks/session-scratch-init.sh) has one reader and its
directory one root rule (hooks/lib/scratch_owner.py, hooks/lib/locations.py).

- Every module that decides on the record takes it from scratch_owner.owner_record: what the record says is
  read in one place (the overwrite rule's own/foreign scratch, the dispatch temp cleanup's owner state, the
  in-flight rule's "session begun before"). Each reader's answers on real records stay what they were.
- The session-start and session-end scripts take the root from locations.session_scratch_root (through
  scratch_owner.py --root), the definition every Python reader uses: a $TMPDIR that is one session's
  directory, spelled with a trailing slash or through a link, still names the same root.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent
LIB = HOOKS / "lib"
for p in (str(HOOKS), str(LIB), str(LIB / "write_gate")):
    if p not in sys.path:
        sys.path.insert(0, p)

SID = "own-sid"


def _owner(d: Path, record) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / ".owner").write_text(record if isinstance(record, str) else json.dumps(record), encoding="utf-8")
    return d


RECORDS = {
    "own": {"sid": SID, "pid": "1", "created_at": "2000-01-01T00:00:00Z"},
    "other": {"sid": "other-sid", "pid": "1"},
    "no-sid": {"pid": "1"},
    "list": [SID],
    "not-json": "{",
    "not-utf8": b"\xff\xfe".decode("latin-1"),
}


@pytest.mark.parametrize("kind", [*RECORDS, "missing"])
def test_the_one_reader_answers_as_each_reader_did(tmp_path, kind):
    import scratch_owner
    import overwrite_scope
    from lib import dispatch_temp
    d = tmp_path / "d"
    if kind == "missing":
        d.mkdir()
    elif kind == "not-utf8":
        d.mkdir()
        (d / ".owner").write_bytes(b"\xff\xfe{")
    else:
        _owner(d, RECORDS[kind])
    rec = scratch_owner.owner_record(str(d))
    assert rec == (RECORDS[kind] if kind in ("own", "other", "no-sid") else None)
    assert scratch_owner.owns_scratch_dir(str(d), SID) is (kind == "own")
    assert overwrite_scope._owner_sid(str(d)) == {"own": SID, "other": "other-sid"}.get(kind)
    assert dispatch_temp._owner_record(str(d / ".owner")) == rec


def test_every_reader_takes_the_record_from_scratch_owner(tmp_path, monkeypatch):
    """A record only scratch_owner.owner_record gives (no file holds it) reaches every deciding reader."""
    import scratch_owner
    import overwrite_scope
    import policy_registry
    from lib import dispatch_temp
    until = 2_000_000_000.0
    given = {"sid": SID, "created_at": "2033-05-16T03:33:18Z"}  # a day before until - 24 h
    assert policy_registry.IN_FLIGHT_HOURS == 24

    def fake(_session_dir):
        return dict(given)

    real = scratch_owner.owner_record

    class _Owner:
        is_safe_session_dir_name = staticmethod(scratch_owner.is_safe_session_dir_name)
        owner_record = staticmethod(fake)
    monkeypatch.setattr(scratch_owner, "owner_record", fake)
    monkeypatch.setattr(dispatch_temp.scratch_owner, "owner_record", fake)
    monkeypatch.setattr(overwrite_scope, "_scratch_owner", lambda: _Owner)
    monkeypatch.setattr(policy_registry, "_in_flight_until", lambda: until)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    (tmp_path / SID).mkdir()
    assert overwrite_scope._owner_sid(str(tmp_path / "nowhere")) == SID
    assert dispatch_temp._owner_record(str(tmp_path / "nowhere" / ".owner")) == given
    assert policy_registry._began_before(SID) is True
    assert real(str(tmp_path / "nowhere")) is None


def _root_of(env) -> str:
    probe = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                            "import locations; print(locations.session_scratch_root())", str(LIB)],
                           capture_output=True, text=True, env=env, timeout=30)
    assert probe.returncode == 0, probe.stderr
    return probe.stdout.strip()


@pytest.mark.parametrize("spelling", ["trailing-slash", "link"])
def test_the_session_scripts_take_the_root_of_the_one_definition(tmp_path, spelling):
    """TMPDIR is one session's directory, spelled as a shell's ${ROOT%/*} gets wrong: the new session registers
    where every Python reader (locations.session_scratch_root) looks, and its end sweeps that same place."""
    root = tmp_path / "root"
    _owner(root / "outer-sid", {"sid": "outer-sid"})
    if spelling == "link":
        (tmp_path / "links").mkdir()
        (tmp_path / "links" / "outer").symlink_to(root / "outer-sid")
        tmpdir = str(tmp_path / "links" / "outer")
    else:
        tmpdir = str(root / "outer-sid") + "/"
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_ENV_FILE",)}
    env.update(TMPDIR=tmpdir, CLAUDE_CODE_SESSION_ID="inner-sid", CLAUDE_PID=str(os.getpid()))
    assert _root_of(env) == os.path.realpath(root)
    r = subprocess.run(["bash", str(HOOKS / "session-scratch-init.sh")], input="{}", capture_output=True,
                       text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    assert (root / "inner-sid" / ".owner").is_file(), sorted(str(p) for p in tmp_path.rglob(".owner"))
    assert not (root / "outer-sid" / "inner-sid").exists() and not (tmp_path / "links" / "inner-sid").exists()
    r = subprocess.run(["bash", str(HOOKS / "sessionend-scratch-sweep.sh")], input='{"session_id": "inner-sid"}',
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    assert not (root / "inner-sid").exists()
    assert (root / "outer-sid" / ".owner").is_file()
