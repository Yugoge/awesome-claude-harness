#!/usr/bin/env python3
"""Behavioural tests for hooks/pretool-overwrite-guard.py.

Every assertion drives the REAL guard as a subprocess over a synthetic
PreToolUse envelope. Nothing here asserts against a mock of the thing under
test, and nothing asserts a measurement read from a path this run did not just
write — the workspace is under concurrent mutation, so a remembered value is
not evidence.

Two disciplines are load-bearing:

  * `coverage` in the corpus is DEMONSTRATED, never declared. Covered rows are
    executed against the guard on an existing regular file (expect refusal) and
    on a path that does not exist (expect allow, then the command really runs).
    Uncovered rows are executed for real and MUST still replace the content; a
    route that turns out to be blocked fails here and forces the corpus to be
    corrected. Typing the word "covered" into the fixture proves nothing.

  * FAILURE INJECTION IS GUARD-LOCAL. The bootstrap-failure test injects an
    ImportError into the guard's OWN process via sitecustomize. It never edits,
    deletes or shadows hooks/lib/bash_write_targets.py — three hooks import that
    module and pretool-tool-policy.py fails CLOSED on ImportError, so corrupting
    it would deny every Bash call in the session rather than exercise this guard.
"""
from __future__ import annotations

import ast
import doctest
import inspect
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import textwrap
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
GUARD = REPO / "hooks" / "pretool-overwrite-guard.py"
CORPUS_PATH = REPO / "hooks" / "tests" / "fixtures" / "overwrite_corpus.json"
DOCS = REPO / "docs" / "reference" / "overwrite-prohibition.md"
LEXER = REPO / "hooks" / "lib" / "bash_write_targets.py"

sys.path.insert(0, str(REPO / "hooks"))
from lib import bash_write_targets as bwt  # noqa: E402
from lib.allowlist import (  # noqa: E402
    SENTINEL_GRANT_DIR,
    consume_sentinel_grant_on_terminal_result,
    match_sentinel_grant_for_bash_command,
    match_sentinel_grant_for_write,
)

CORPUS = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
ROUTES = CORPUS["routes"]
COVERED = [r for r in ROUTES if r["coverage"] == "covered"]
UNCOVERED = [r for r in ROUTES if r["coverage"] == "uncovered"]

#: Covered rows the verb harness can drive: one command, one target, one
#: verdict. A row marked `demonstration: bespoke` is covered by a property the
#: harness cannot express as a single command (the grant lifecycle), and brings
#: its own named test instead.
COVERED_VERB_ROUTES = [r for r in COVERED if r.get("demonstration") != "bespoke"]

NEW = "NEWCONTENT"
EDIT_SURFACE = ("Edit", "MultiEdit", "NotebookEdit", "Write")


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

def original_bytes() -> str:
    """Fresh known bytes for this run; never a remembered constant."""
    return f"ORIGINAL-{uuid.uuid4().hex}"


def rp(path) -> str:
    """The identity the guard decides on: the realpath of the target."""
    return os.path.realpath(str(path))


def run_guard(command, cwd, *, guard=GUARD, session_id="sid-test", task_id=None,
              env=None, run_from=None):
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": session_id,
        "cwd": str(cwd),
    }
    if task_id:
        payload["task_id"] = task_id
    child_env = dict(os.environ)
    child_env.pop("CLAUDE_TASK_ID", None)
    child_env.pop("CLAUDE_HOME", None)
    if env:
        child_env.update(env)
    return subprocess.run(
        [sys.executable, str(guard)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=60,
        cwd=str(run_from) if run_from else str(REPO),
        env=child_env,
    )


def run_guard_tool(tool_name, tool_input, cwd):
    """Drive the guard with a NON-Bash tool envelope."""
    payload = {"tool_name": tool_name, "tool_input": tool_input,
               "session_id": "sid-test", "cwd": str(cwd)}
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=60, cwd=str(REPO))


def sh(command, cwd):
    return subprocess.run(command, shell=True, executable="/bin/bash", cwd=str(cwd),
                          capture_output=True, text=True, timeout=60)


def fill(template, mapping):
    out = template
    for key, value in mapping.items():
        out = out.replace(key, value)
    return out


@pytest.fixture(scope="module")
def http_url():
    """Loopback HTTP source so curl -o / wget -O are exercised for real."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = NEW.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/payload"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def sandbox_home(root: Path) -> Path:
    """A self-contained harness home holding a COPY of the guard and lib/.

    The structural sentinel set (settings.json + hooks/ + policies/ + scripts/)
    makes the shared resolver land here, so the audit sink is isolated from the
    real one and can be manipulated without touching the repository.
    """
    home = root / "sandbox-home"
    (home / "hooks" / "lib").mkdir(parents=True)
    (home / "policies").mkdir()
    (home / "scripts").mkdir()
    (home / "settings.json").write_text("{}", encoding="utf-8")
    shutil.copy2(GUARD, home / "hooks" / GUARD.name)
    for module in (REPO / "hooks" / "lib").glob("*.py"):
        shutil.copy2(module, home / "hooks" / "lib" / module.name)
    return home


def audit_rows(home: Path):
    sink = home / "logs" / "overwrite-guard.jsonl"
    if not sink.is_file():
        return []
    return [json.loads(line) for line in sink.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_grant(task_id, session_id, operations) -> Path:
    Path(SENTINEL_GRANT_DIR).mkdir(parents=True, exist_ok=True)
    path = Path(SENTINEL_GRANT_DIR) / f"{task_id}.json"
    path.write_text(json.dumps({
        "task_id": task_id,
        "session_id": session_id,
        "allowed_operations": operations,
        "created_at": time.time(),
        "expires_at": time.time() + 300,
    }), encoding="utf-8")
    return path


def drop_grants(task_id):
    for path in Path(SENTINEL_GRANT_DIR).glob(f"{task_id}*.json"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# AC-01 — every covered route refused on an existing regular file, allowed on new
# ---------------------------------------------------------------------------

def test_ac01_mandated_verbs_all_have_a_covered_row():
    """The covered floor cannot be narrowed by quietly dropping a verb."""
    assert {r["mechanism"] for r in COVERED_VERB_ROUTES} == {
        "redirect-truncate", "redirect-clobber", "tee-truncate", "truncate-cmd",
        "dd-of", "cp-dest", "install-dest", "mv-dest", "curl-output",
        "wget-output", "unlink-cmd",
    }


@pytest.mark.parametrize("row", COVERED_VERB_ROUTES,
                         ids=[r["route_id"] for r in COVERED_VERB_ROUTES])
def test_ac01_covered_route_denied_on_existing_and_allowed_on_new(row, tmp_path, http_url):
    work = tmp_path / row["route_id"]
    work.mkdir(parents=True)
    target = work / (row.get("victim_name") or "victim.txt")
    original = original_bytes()
    target.write_text(original, encoding="utf-8")
    source = work / "source.txt"
    source.write_text(NEW, encoding="utf-8")

    base = {"{SRC}": str(source), "{DIR}": str(work), "{URL}": http_url}
    deny_cmd = fill(row["command_template"], {**base, "{TARGET}": str(target)})

    result = run_guard(deny_cmd, cwd=work)
    assert result.returncode == row["expect_on_existing"], (
        f"{row['route_id']}: expected refusal, got {result.returncode}\n{result.stderr}")
    assert target.read_text(encoding="utf-8") == original, "denied route must not have run"
    assert rp(target) in result.stderr

    # Same verb, a path that does not exist: creation is never denied.
    created = work / "created.txt"
    source.write_text(NEW, encoding="utf-8")  # mv consumed it on some routes
    allow_cmd = fill(row["command_template"], {**base, "{TARGET}": str(created)})
    allowed = run_guard(allow_cmd, cwd=work)
    assert allowed.returncode == row["expect_on_new"], (
        f"{row['route_id']}: creation must be allowed\n{allowed.stderr}")

    executed = sh(allow_cmd, cwd=work)
    if row["creates_on_new"]:
        assert executed.returncode == 0, executed.stderr
        assert created.is_file()
    else:
        assert not created.exists()


# ---------------------------------------------------------------------------
# AC-02 — ordinary incremental work is completely ungated
# ---------------------------------------------------------------------------

def test_ac02_incremental_shell_work_is_ungated(tmp_path):
    work = tmp_path / "incremental"
    work.mkdir()
    target = work / "victim.txt"
    original = original_bytes()
    target.write_text(original, encoding="utf-8")
    source = work / "source.txt"
    source.write_text(NEW, encoding="utf-8")
    fresh = work / "renamed.txt"

    token = f"SUBSTITUTED-{uuid.uuid4().hex}"
    operations = [
        f"echo {NEW} >> {target}",
        f"echo {NEW} | tee -a {target}",
        f"sed -i s/{original}/{token}/ {target}",
        f"mv {source} {fresh}",
    ]
    for command in operations:
        result = run_guard(command, cwd=work)
        assert result.returncode == 0, f"{command!r} must be ungated\n{result.stderr}"

    assert sh(operations[0], cwd=work).returncode == 0
    assert target.read_text(encoding="utf-8").startswith(original)
    assert sh(operations[1], cwd=work).returncode == 0
    assert target.read_text(encoding="utf-8").startswith(original)
    assert sh(operations[2], cwd=work).returncode == 0
    assert token in target.read_text(encoding="utf-8")
    assert sh(operations[3], cwd=work).returncode == 0
    assert fresh.is_file()


@pytest.mark.parametrize("tool", EDIT_SURFACE)
def test_ac02_edit_tool_surface_is_never_intercepted(tool, tmp_path):
    """The guard's matcher is Bash. Every edit-tool envelope passes untouched."""
    target = tmp_path / "victim.txt"
    target.write_text(original_bytes(), encoding="utf-8")
    result = run_guard_tool(tool, {"file_path": str(target), "content": NEW}, tmp_path)
    assert result.returncode == 0
    assert result.stdout == "" and result.stderr == ""


def test_ac02_guard_compares_tool_name_against_bash_only():
    """Source-level: no edit-tool name is ever a decision input."""
    tree = ast.parse(GUARD.read_text(encoding="utf-8"))
    tool_name_compares = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        rendered = ast.unparse(node)
        for banned in ("Edit", "MultiEdit", "NotebookEdit"):
            assert f"'{banned}'" not in rendered, f"guard branches on {banned}: {rendered}"
        if "tool_name" in rendered:
            tool_name_compares.append(rendered)
    assert tool_name_compares, "guard must gate on tool_name"
    for rendered in tool_name_compares:
        assert "'Bash'" in rendered, rendered
    # 'Write' may appear only as the sentinel-grant OP name, never as a tool gate.
    for rendered in tool_name_compares:
        assert "'Write'" not in rendered, rendered


def test_ac02_documented_registration_declares_bash_only():
    text = DOCS.read_text(encoding="utf-8")
    assert '"matcher": "Bash"' in text
    assert "settings.template.json" in text
    for banned in ('"matcher": "Edit"', '"matcher": "Write"', '"matcher": "MultiEdit"'):
        assert banned not in text


# ---------------------------------------------------------------------------
# AC-03 — non-regular targets allowed BY FILE TYPE, not by a path allowlist
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "echo hello > /dev/null",
    "ls /nonexistent 2>&1",
    "echo hello > /dev/stderr",
    "echo hello > /dev/fd/1",
])
def test_ac03_device_targets_are_allowed(command, tmp_path):
    result = run_guard(command, cwd=tmp_path)
    assert result.returncode == 0, f"{command!r} must not be gated\n{result.stderr}"


def test_ac03_decision_is_anchored_on_file_type_not_path_strings(tmp_path):
    """A FIFO is allowed and a regular file is refused at sibling paths.

    Neither path string can appear in the guard, so only the stat() type test
    can be producing the difference.
    """
    fifo = tmp_path / "as-a-fifo"
    regular = tmp_path / "as-a-regular-file"
    os.mkfifo(fifo)
    regular.write_text(original_bytes(), encoding="utf-8")
    assert stat.S_ISFIFO(os.stat(fifo).st_mode)

    assert run_guard(f"echo hi > {fifo}", cwd=tmp_path).returncode == 0
    assert run_guard(f"echo hi > {regular}", cwd=tmp_path).returncode == 2

    # A character device the guard has never heard of behaves like /dev/null,
    # so the allow decision cannot be coming from a list of blessed names.
    source = GUARD.read_text(encoding="utf-8")
    assert "/dev/zero" not in source and "/dev/urandom" not in source
    assert fifo.name not in source and regular.name not in source
    assert run_guard("echo hi > /dev/zero", cwd=tmp_path).returncode == 0
    assert run_guard("echo hi > /dev/urandom", cwd=tmp_path).returncode == 0


# ---------------------------------------------------------------------------
# AC-04 — move-into-a-directory allowed; only the resolved collision refused
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template", [
    "mv {SRC} {DIR}/",
    "cp {SRC} {DIR}/",
    "install -m 644 {SRC} {DIR}/",
])
def test_ac04_move_into_directory(template, tmp_path):
    work = tmp_path / "movein"
    work.mkdir()
    destination = work / "archive"
    destination.mkdir()
    source = work / "report.txt"
    source.write_text(NEW, encoding="utf-8")

    command = fill(template, {"{SRC}": str(source), "{DIR}": str(destination)})
    assert run_guard(command, cwd=work).returncode == 0, "move-into is ordinary work"
    assert sh(command, cwd=work).returncode == 0
    assert (destination / "report.txt").is_file()

    # Now the resolved landing path exists as a regular file: that path is refused.
    original = original_bytes()
    (destination / "report.txt").write_text(original, encoding="utf-8")
    source.write_text(NEW, encoding="utf-8")
    result = run_guard(command, cwd=work)
    assert result.returncode == 2
    assert rp(destination / "report.txt") in result.stderr
    assert (destination / "report.txt").read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# AC-05 — identity resolved once; creation is never denied
# ---------------------------------------------------------------------------

def test_ac05_symlink_and_relative_and_variable_identity(tmp_path):
    work = tmp_path / "identity"
    work.mkdir()
    real = work / "real.txt"
    original = original_bytes()
    real.write_text(original, encoding="utf-8")

    live_link = work / "live.lnk"
    live_link.symlink_to(real)
    dead_link = work / "dead.lnk"
    dead_link.symlink_to(work / "absent.txt")

    # Symlink to an existing regular file: refused on the RESOLVED identity.
    result = run_guard(f"echo {NEW} > {live_link}", cwd=work)
    assert result.returncode == 2
    assert rp(real) in result.stderr, "verdict must name the resolved identity"
    assert real.read_text(encoding="utf-8") == original

    # Dangling symlink: nothing exists, so this is creation.
    assert run_guard(f"echo {NEW} > {dead_link}", cwd=work).returncode == 0

    # Relative literal resolved against payload['cwd'] — proven by running the
    # guard process from a DIFFERENT directory than the payload cwd.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert run_guard(f"echo {NEW} > real.txt", cwd=work, run_from=elsewhere).returncode == 2
    assert run_guard(f"echo {NEW} > brand-new.txt", cwd=work, run_from=elsewhere).returncode == 0

    # Variable indirection is ALLOWED and declared uncovered.
    assert run_guard(f"T={real}; echo {NEW} > $T", cwd=work).returncode == 0
    assert any(r["route_id"] == "variable-indirection" and r["coverage"] == "uncovered"
               for r in ROUTES)


# ---------------------------------------------------------------------------
# AC-06 — a grant authorizes exactly one replacement of exactly one named file
# ---------------------------------------------------------------------------

def test_ac06_grant_is_single_use_and_target_bound(tmp_path):
    work = tmp_path / "grant"
    work.mkdir()
    target = work / "victim.txt"
    original = original_bytes()
    target.write_text(original, encoding="utf-8")
    other = work / "other.txt"
    other.write_text(original_bytes(), encoding="utf-8")

    task_id = f"ovwtest-{uuid.uuid4().hex}"
    session_id = f"sid-{uuid.uuid4().hex}"
    command = f"echo {NEW} > {target}"
    try:
        grant_file = write_grant(task_id, session_id,
                                 [{"op": "Write", "target": str(target)}])
        first = run_guard(command, cwd=work, session_id=session_id, task_id=task_id)
        assert first.returncode == 0, first.stderr
        assert "permitted_by_grant" in first.stderr

        # A grant naming this file does not authorize a different file.
        denied_other = run_guard(f"echo {NEW} > {other}", cwd=work,
                                 session_id=session_id, task_id=task_id)
        assert denied_other.returncode == 2

        # SINGLE USE, ASSERTED THROUGH THE GUARD ITSELF — never by calling the
        # consumption helper by hand. Driving the helper is what concealed the
        # defect: the helper always worked, and the registered PostToolUse
        # consumer never reached it for a Write-op grant, so a green suite sat
        # on top of a grant that authorized replacements without limit.
        assert not grant_file.exists(), (
            "authorizing must SPEND the grant; if this file survives, the escape "
            "hatch is a mode and not a one-shot")
        assert not list(Path(SENTINEL_GRANT_DIR).glob(f"{task_id}*.json"))
        assert "grant CONSUMED" in first.stderr

        second = run_guard(command, cwd=work, session_id=session_id, task_id=task_id)
        assert second.returncode == 2, "a consumed grant must not authorize a second replacement"
        third = run_guard(command, cwd=work, session_id=session_id, task_id=task_id)
        assert third.returncode == 2
        assert target.read_text(encoding="utf-8") == original, "no attempt ever ran"
    finally:
        drop_grants(task_id)


def test_ac06_single_use_holds_under_concurrency(tmp_path):
    """Two guards, one grant, no terminal result between them: ONE permit.

    The corpus previously declared this an uncovered route on the reasoning
    that consumption was POST-tool. Consumption is now the unlink performed by
    the guard that authorizes, and unlink is atomic, so the file itself is the
    mutual exclusion: whichever process gets it wins and the loser is refused.
    Both interleavings satisfy the same assertion, so this is not a flaky race
    probe — if the two calls are serialized the second simply finds no grant.
    """
    work = tmp_path / "concurrent"
    work.mkdir()
    target = work / "victim.txt"
    original = original_bytes()
    target.write_text(original, encoding="utf-8")
    task_id = f"ovwtest-{uuid.uuid4().hex}"
    session_id = f"sid-{uuid.uuid4().hex}"
    command = f"echo {NEW} > {target}"
    try:
        for _ in range(4):
            write_grant(task_id, session_id, [{"op": "Write", "target": str(target)}])
            with ThreadPoolExecutor(max_workers=2) as pool:
                codes = [f.result().returncode for f in [
                    pool.submit(run_guard, command, work, session_id=session_id, task_id=task_id)
                    for _ in range(2)]]
            assert codes.count(0) == 1, f"exactly one permit expected, got {codes}"
            assert codes.count(2) == 1, f"exactly one refusal expected, got {codes}"
            assert not list(Path(SENTINEL_GRANT_DIR).glob(f"{task_id}*.json"))
            assert target.read_text(encoding="utf-8") == original
    finally:
        drop_grants(task_id)


def test_ac06_grant_is_spent_only_by_the_call_it_authorizes(tmp_path):
    """Single-use must not become collateral damage to ordinary work.

    The guard reaches consumption only after it has established a replacing
    verb, an existing regular target, AND a grant naming that exact file. An
    ungated call, an append, a creation, or a refused attempt on a different
    file must all leave the grant untouched — otherwise the narrowing is
    reintroduced from the other side, with the human's grant silently eaten by
    an unrelated command.
    """
    work = tmp_path / "no-collateral"
    work.mkdir()
    target = work / "victim.txt"
    original = original_bytes()
    target.write_text(original, encoding="utf-8")
    other = work / "other.txt"
    other.write_text(original_bytes(), encoding="utf-8")
    task_id = f"ovwtest-{uuid.uuid4().hex}"
    session_id = f"sid-{uuid.uuid4().hex}"
    try:
        grant_file = write_grant(task_id, session_id,
                                 [{"op": "Write", "target": str(target)}])
        untouched = [
            "ls -la /tmp",                       # no write target at all
            f"echo {NEW} >> {target}",           # append to the granted file
            f"sed -i s/a/b/ {target}",           # in-place edit of it
            f"echo {NEW} > {work / 'fresh.txt'}",  # creation
            f"echo {NEW} > {other}",             # refused: a DIFFERENT file
        ]
        for command in untouched:
            run_guard(command, cwd=work, session_id=session_id, task_id=task_id)
            assert grant_file.exists(), f"{command!r} must not spend the grant"

        spent = run_guard(f"echo {NEW} > {target}", cwd=work,
                          session_id=session_id, task_id=task_id)
        assert spent.returncode == 0
        assert not grant_file.exists()
    finally:
        drop_grants(task_id)


@pytest.mark.parametrize("operations, label", [
    ([{"op": "Write"}], "bare wildcard"),
    ([{"op": "Write", "target": "victim.txt"}], "relative target"),
    ([{"op": "Write", "target": ""}], "empty target"),
    ([{"op": "Write", "args_contain": ["victim.txt"]}], "no target key"),
])
def test_ac06_non_authorizing_grant_shapes(operations, label, tmp_path):
    work = tmp_path / f"grant-{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True)
    target = work / "victim.txt"
    original = original_bytes()
    target.write_text(original, encoding="utf-8")
    task_id = f"ovwtest-{uuid.uuid4().hex}"
    session_id = f"sid-{uuid.uuid4().hex}"
    try:
        write_grant(task_id, session_id, operations)
        result = run_guard(f"echo {NEW} > {target}", cwd=work,
                           session_id=session_id, task_id=task_id)
        assert result.returncode == 2, f"{label} must not authorize shell replacement"
        assert target.read_text(encoding="utf-8") == original
    finally:
        drop_grants(task_id)


def test_ac06_write_tool_wildcard_behaviour_is_unchanged():
    """The bare wildcard stays live for the Write TOOL; we narrowed at the guard."""
    task_id = f"ovwtest-{uuid.uuid4().hex}"
    session_id = f"sid-{uuid.uuid4().hex}"
    try:
        write_grant(task_id, session_id, [{"op": "Write"}])
        matched = match_sentinel_grant_for_write(task_id, session_id, "/any/path/at/all")
        assert matched == {"op": "Write"}, "allowlist.py must be untouched"
    finally:
        drop_grants(task_id)


def test_ac06_guard_creates_no_new_issuance_channel():
    """The guard reads grants; it can never write one, and adds no op name."""
    source = GUARD.read_text(encoding="utf-8")
    assert "SENTINEL_GRANT_DIR" not in source
    assert "claude-grants" not in source
    assert "overwrite\"" not in source.lower().replace("overwrite-guard", "")
    tree = ast.parse(source)
    op_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value in ("overwrite", "Overwrite", "OVERWRITE")
    }
    assert not op_literals, "no new sentinel op name may be introduced"


# ---------------------------------------------------------------------------
# AC-07 — every refusal and every granted replacement is attributable
# ---------------------------------------------------------------------------

REQUIRED_AUDIT_FIELDS = ("resolved_target", "mechanism", "decision", "grant_identity",
                         "session_id", "task_id", "timestamp")


def test_ac07_both_verdicts_are_recorded_and_audit_failure_denies(tmp_path):
    home = sandbox_home(tmp_path)
    guard = home / "hooks" / GUARD.name
    work = tmp_path / "audited"
    work.mkdir()
    target = work / "victim.txt"
    original = original_bytes()
    target.write_text(original, encoding="utf-8")
    command = f"echo {NEW} > {target}"
    task_id = f"ovwtest-{uuid.uuid4().hex}"
    session_id = f"sid-{uuid.uuid4().hex}"

    try:
        # (a) refusal
        refused = run_guard(command, cwd=work, guard=guard,
                            session_id=session_id, task_id=task_id)
        assert refused.returncode == 2
        rows = audit_rows(home)
        assert len(rows) == 1
        row = rows[0]
        for field in REQUIRED_AUDIT_FIELDS:
            assert field in row, f"audit row missing {field}"
        assert row["decision"] == "refused"
        assert rp(target) in row["resolved_target"]
        assert "redirect-truncate" in row["mechanism"]
        assert row["session_id"] == session_id and row["task_id"] == task_id

        # (b) grant-permitted replacement
        write_grant(task_id, session_id, [{"op": "Write", "target": str(target)}])
        permitted = run_guard(command, cwd=work, guard=guard,
                              session_id=session_id, task_id=task_id)
        assert permitted.returncode == 0, permitted.stderr
        rows = audit_rows(home)
        assert len(rows) == 2
        assert rows[1]["decision"] == "permitted_by_grant"
        assert rows[1]["grant_identity"][0]["grant_target"] == str(target)

        # durability: the guard fsyncs, so the row survives without our help
        assert "os.fsync" in GUARD.read_text(encoding="utf-8")

        # (c) the sink cannot be written: BOTH paths deny
        shutil.rmtree(home / "logs")
        (home / "logs").write_text("not a directory", encoding="utf-8")

        wedged_grant = run_guard(command, cwd=work, guard=guard,
                                 session_id=session_id, task_id=task_id)
        assert wedged_grant.returncode == 2, "a granted replacement that cannot be recorded is denied"
        assert "cannot be attributed" in wedged_grant.stderr

        drop_grants(task_id)
        wedged_refusal = run_guard(command, cwd=work, guard=guard,
                                   session_id=session_id, task_id=task_id)
        assert wedged_refusal.returncode == 2
        assert "cannot be attributed" in wedged_refusal.stderr
        assert target.read_text(encoding="utf-8") == original
    finally:
        drop_grants(task_id)


# ---------------------------------------------------------------------------
# AC-08 — guard-local bootstrap failure fails OPEN without sealing repair
# ---------------------------------------------------------------------------

def _import_blocker(tmp_path: Path) -> Path:
    shim = tmp_path / "import-blocker"
    shim.mkdir()
    (shim / "sitecustomize.py").write_text(textwrap.dedent("""
        import sys

        class _GuardLocalBlocker:
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "lib.bash_write_targets":
                    raise ImportError("injected guard-local bootstrap failure")
                return None

        sys.meta_path.insert(0, _GuardLocalBlocker())
    """), encoding="utf-8")
    return shim


def test_ac08_bootstrap_failure_fails_open_loudly(tmp_path):
    home = sandbox_home(tmp_path)
    guard = home / "hooks" / GUARD.name
    work = tmp_path / "failopen"
    work.mkdir()
    target = work / "victim.txt"
    original = original_bytes()
    target.write_text(original, encoding="utf-8")
    env = {"PYTHONPATH": str(_import_blocker(tmp_path))}

    # The shared lexer is untouched by this injection.
    assert LEXER.is_file() and "extract_bash_write_paths" in LEXER.read_text(encoding="utf-8")

    replacing = run_guard(f"echo {NEW} > {target}", cwd=work, guard=guard, env=env)
    assert replacing.returncode == 0, "bootstrap failure must FAIL OPEN"
    assert "hooks/pretool-overwrite-guard.py" in replacing.stderr
    assert "FAILING OPEN" in replacing.stderr

    repair = run_guard("ls /nonexistent 2>&1", cwd=work, guard=guard, env=env)
    assert repair.returncode == 0, "the repair path must not be sealed"

    rows = audit_rows(home)
    assert rows and all(r["decision"] == "bootstrap_failed_fail_open" for r in rows)
    assert rows[0]["guard"] == "hooks/pretool-overwrite-guard.py"


# ---------------------------------------------------------------------------
# AC-09 — the uncovered set is declared AND demonstrated
# ---------------------------------------------------------------------------

def test_ac09_required_uncovered_classes_are_all_present():
    """AC-09's mandated disclosure floor, minus one class that was CLOSED.

    `concurrent-grant-reuse` was on this list because the criterion was written
    while consumption was believed to be POST-tool. It was not consumed at all
    (see test_ac06_grant_is_single_use_and_target_bound), and closing that made
    the concurrent case fall out with it, because the unlink IS the mutual
    exclusion. A class that no longer describes a real gap cannot stay on a
    disclosure list: the list's whole value is that every entry is DEMONSTRATED,
    and this one now fails its own demonstration. Recorded as a measured
    correction to AC-09, not dropped silently — the closure is asserted by
    test_ac06_single_use_holds_under_concurrency and the corpus row carries
    `reclassified_from: uncovered` with its reasoning.
    """
    required = {
        "displace-then-create", "interpreter-script", "interpreter-stdin",
        "wrapper-script", "compiled-binary", "variable-indirection",
        "check-use-race", "semantic-lexer-corruption",
    }
    assert required <= {r["route_class"] for r in UNCOVERED}
    closed = [r for r in ROUTES if r["route_class"] == "concurrent-grant-reuse"]
    assert len(closed) == 1 and closed[0]["coverage"] == "covered", (
        "the reclassified route must still be in the corpus, as covered")
    assert closed[0].get("reclassified_from") == "uncovered"
    assert closed[0].get("reclassification_reason") and closed[0].get("residual")


def test_ac09_documentation_lists_the_same_uncovered_route_ids():
    text = DOCS.read_text(encoding="utf-8")
    headings = [line for line in text.splitlines()
                if line.startswith("## ") and line.rstrip().endswith("Uncovered Routes")]
    assert len(headings) == 1, f"expected exactly one Uncovered Routes section, got {headings}"
    section = text.split(headings[0], 1)[1]
    for row in UNCOVERED:
        assert f"`{row['route_id']}`" in section, f"{row['route_id']} missing from documentation"


GENERIC_UNCOVERED = [r for r in UNCOVERED if r.get("demonstration", "").startswith("generic")]


@pytest.mark.parametrize("row", GENERIC_UNCOVERED, ids=[r["route_id"] for r in GENERIC_UNCOVERED])
def test_ac09_uncovered_route_still_replaces_content(row, tmp_path):
    work = tmp_path / row["route_id"]
    work.mkdir(parents=True)
    victim_name = row.get("victim_name") or row.get("target_basename") or "victim.txt"
    target = work / victim_name
    original = original_bytes()
    target.write_text(original, encoding="utf-8")
    source = work / "source.txt"
    source.write_text(NEW, encoding="utf-8")

    mapping = {
        "{TARGET}": str(target),
        "{SRC}": str(source),
        "{DIR}": str(work),
        "{SCRIPT}": str(work / "writer.script"),
        "{SRCDIR}": str(work / "srctree"),
        "{ARCHIVE}": str(work / "bundle.tar"),
        "{GZSRC}": str(work / "payload"),
    }
    for setup in row.get("setup_templates", []):
        prepared = sh(fill(setup, mapping), cwd=work)
        assert prepared.returncode == 0, prepared.stderr

    commands = row.get("command_sequence") or [row["command_template"]]
    for template in commands:
        command = fill(template, mapping)
        verdict = run_guard(command, cwd=work)
        assert verdict.returncode == 0, (
            f"{row['route_id']} is recorded UNCOVERED but the guard blocked it — "
            f"correct the corpus\n{verdict.stderr}")
        executed = sh(command, cwd=work)
        assert executed.returncode == 0, executed.stderr

    assert target.read_text(encoding="utf-8", errors="replace") != original, (
        f"{row['route_id']} did not actually replace the content — it is not a real gap")


def test_ac09_compiled_binary_route(tmp_path):
    work = tmp_path / "compiled-binary"
    work.mkdir()
    target = work / "victim.txt"
    original = original_bytes()
    target.write_text(original, encoding="utf-8")
    binary = work / "replacer"

    source = work / "replacer.c"
    source.write_text(
        '#include <stdio.h>\n'
        'int main(int argc, char **argv) {\n'
        '  FILE *f = fopen(argv[1], "w");\n'
        '  if (!f) return 1;\n'
        '  fputs("NEWCONTENT", f);\n'
        '  fclose(f);\n'
        '  return 0;\n'
        '}\n', encoding="utf-8")
    built = sh(f"cc -O0 -o {binary} {source}", cwd=work)
    if built.returncode != 0:  # no compiler: a coreutils binary is still compiled code
        shutil.copy2("/usr/bin/truncate", binary)
        command = f"{binary} -s 0 {target}"
    else:
        command = f"{binary} {target}"

    assert os.stat(binary).st_mode & stat.S_IXUSR
    verdict = run_guard(command, cwd=work)
    assert verdict.returncode == 0, "a compiled binary's target is not in the command text"
    assert sh(command, cwd=work).returncode == 0
    assert target.read_text(encoding="utf-8") != original


def test_ac09_check_use_race(tmp_path):
    work = tmp_path / "check-use-race"
    work.mkdir()
    target = work / "victim.txt"
    command = f"echo {NEW} > {target}"

    # The guard judges BEFORE execution, when nothing exists: creation, allowed.
    assert run_guard(command, cwd=work).returncode == 0

    # Another actor creates the file in the window between check and use.
    original = original_bytes()
    target.write_text(original, encoding="utf-8")

    assert sh(command, cwd=work).returncode == 0
    assert target.read_text(encoding="utf-8") != original


def test_ac09_the_registered_posttool_consumer_still_cannot_see_a_write_grant(tmp_path):
    """Why single-use had to move INTO the guard, asserted rather than asserted-about.

    The registered consumer gates its unlink on
    match_sentinel_grant_for_bash_command, which reads the shell command's
    FIRST WORD as the op name. The only grant shape this guard accepts is
    {"op":"Write","target":...}, which no shell command can spell — so that
    matcher returns None for every replacement command, and the unlink never
    fired. This test pins the reason: if the matcher ever does match a Write
    grant against a bash command, the guard's own consumption would become a
    double-consume and this assertion says so out loud.
    """
    work = tmp_path / "posttool-blind"
    work.mkdir()
    target = work / "victim.txt"
    target.write_text(original_bytes(), encoding="utf-8")
    task_id = f"ovwtest-{uuid.uuid4().hex}"
    session_id = f"sid-{uuid.uuid4().hex}"
    try:
        write_grant(task_id, session_id, [{"op": "Write", "target": str(target)}])
        for command in (f"echo {NEW} > {target}", f"cp src {target}", f"tee {target}"):
            assert match_sentinel_grant_for_bash_command(task_id, command) is None, (
                "the PostToolUse gate now matches a Write grant — the guard's own "
                "consumption must be reviewed for double-consume")
        # And the helper it would have called is, and always was, fine.
        assert consume_sentinel_grant_on_terminal_result(task_id, "success") is True
    finally:
        drop_grants(task_id)


def test_ac09_grant_self_minting(tmp_path):
    """CORRECTION: the spec claimed an agent cannot mint its own grant. It can.

    The sentinel grant is an ordinary JSON file. Creating it is creation of a
    path that does not exist, which this guard never denies — by binding
    requirement. So the escape hatch is forgeable from the very surface it
    guards. Demonstrated here rather than claimed closed.
    """
    work = tmp_path / "grant-self-minting"
    work.mkdir()
    target = work / "victim.txt"
    original = original_bytes()
    target.write_text(original, encoding="utf-8")
    task_id = f"ovwtest-{uuid.uuid4().hex}"
    session_id = f"sid-{uuid.uuid4().hex}"
    command = f"echo {NEW} > {target}"
    grant_path = Path(SENTINEL_GRANT_DIR) / f"{task_id}.json"
    try:
        assert run_guard(command, cwd=work, session_id=session_id,
                         task_id=task_id).returncode == 2

        forged = json.dumps({
            "task_id": task_id, "session_id": session_id,
            "allowed_operations": [{"op": "Write", "target": str(target)}],
            "created_at": 0, "expires_at": 9999999999,
        })
        Path(SENTINEL_GRANT_DIR).mkdir(parents=True, exist_ok=True)
        mint_command = f"echo '{forged}' > {grant_path}"
        assert run_guard(mint_command, cwd=work, session_id=session_id,
                         task_id=task_id).returncode == 0, "minting is creation, never denied"
        assert sh(mint_command, cwd=work).returncode == 0
        assert grant_path.is_file()

        assert run_guard(command, cwd=work, session_id=session_id,
                         task_id=task_id).returncode == 0, "the forged grant authorizes"
        assert sh(command, cwd=work).returncode == 0
        assert target.read_text(encoding="utf-8") != original
    finally:
        drop_grants(task_id)


def test_ac09_semantic_lexer_corruption(tmp_path):
    """A lexer that IMPORTS cleanly but returns nothing degrades the guard silently.

    Injected into the guard's own process only. The real shared module keeps
    working — proven by re-reading it here after the run.
    """
    work = tmp_path / "semantic-lexer-corruption"
    work.mkdir()
    target = work / "victim.txt"
    original = original_bytes()
    target.write_text(original, encoding="utf-8")

    shim = tmp_path / "semantic-shim"
    shim.mkdir()
    (shim / "sitecustomize.py").write_text(textwrap.dedent("""
        import sys, types
        fake = types.ModuleType("lib.bash_write_targets")
        fake.REPLACING_MODES = frozenset({"truncating", "rename_into_place", "destroying"})
        fake.extract_bash_write_targets_with_modes = lambda command: []
        sys.modules["lib.bash_write_targets"] = fake
    """), encoding="utf-8")

    command = f"echo {NEW} > {target}"
    degraded = run_guard(command, cwd=work, env={"PYTHONPATH": str(shim)})
    assert degraded.returncode == 0, "the guard silently allows — this is the open switch"
    assert "FAILING OPEN" not in degraded.stderr, "and it is SILENT: no warning is emitted"
    assert sh(command, cwd=work).returncode == 0
    assert target.read_text(encoding="utf-8") != original

    # The real module is untouched: the same call still names the target.
    assert [t.path for t in bwt.extract_bash_write_targets_with_modes(command)] == [str(target)]
    assert run_guard(command, cwd=work).returncode == 2


# ---------------------------------------------------------------------------
# Iteration 1 — the two syntaxes that hid a command word from every verb
#
# Both are DERIVED from the covered set rather than listed, so a verb added
# later cannot quietly acquire the gap: the derivation reads each covered row's
# own template, and the exemption set is asserted rather than assumed.
# ---------------------------------------------------------------------------

def _verb_of(row) -> str | None:
    """The command WORD a covered row invokes, or None for a redirect operator."""
    candidate = row["mechanism"].split("-")[0]
    return None if candidate == "redirect" else candidate


#: Rows written in PLAIN form. The `hidden-command-word` rows ARE the escaped
#: and grouped forms, so applying the transformation to them again would
#: produce `\\cp`, which is not a command at all.
PLAIN_COVERED = [r for r in COVERED_VERB_ROUTES if r["route_class"] != "hidden-command-word"]
VERB_ROWS = [r for r in PLAIN_COVERED if _verb_of(r)]
OPERATOR_ROWS = [r for r in PLAIN_COVERED if not _verb_of(r)]


def test_f1_only_the_redirect_operators_are_exempt_from_the_word_syntaxes():
    """Pins WHICH rows the two derived tests below are allowed to skip.

    A backslash escapes a command WORD, so `>` and `>|` have nothing to escape.
    Every other covered row names a word and must survive both syntaxes. Two
    ways of quietly shrinking this coverage are closed: renaming a mechanism so
    its verb stops being derivable (the regex assertion below), and moving a
    verb's only plain row into the exempt `hidden-command-word` class (the
    mechanism-set assertion, which requires every mandated mechanism to still
    have a plain row to derive from).
    """
    assert {r["mechanism"] for r in OPERATOR_ROWS} == {"redirect-truncate", "redirect-clobber"}
    assert {r["mechanism"] for r in PLAIN_COVERED} == \
        {r["mechanism"] for r in COVERED_VERB_ROUTES}, (
            "a mandated mechanism lost its plain-form row and is no longer derived against")
    for row in VERB_ROWS:
        verb = _verb_of(row)
        assert re.search(rf"(?:^|[\s;|&]){re.escape(verb)}\b", row["command_template"]), (
            f"{row['route_id']}: mechanism {row['mechanism']} names verb {verb!r}, "
            f"which does not appear as a word in {row['command_template']!r}")


@pytest.mark.parametrize("row", VERB_ROWS, ids=[r["route_id"] for r in VERB_ROWS])
def test_f1_backslash_prefix_defeats_no_covered_verb(row, tmp_path, http_url):
    r"""`\cp` is the routine alias-bypass idiom, and it defeated 9 of 11 verbs.

    The verb regexes required a `[\s;|&]` boundary before the command word and
    a backslash is not in that class, so one byte turned every one of these
    into an unnamed target — while the path stayed fully visible in the command
    text. That is the guard failing on its own stated model, not an opacity
    class, and it was declared nowhere.
    """
    verb = _verb_of(row)
    work = tmp_path / f"backslash-{row['route_id']}"
    work.mkdir(parents=True)
    target = work / (row.get("victim_name") or "victim.txt")
    original = original_bytes()
    target.write_text(original, encoding="utf-8")
    source = work / "source.txt"
    source.write_text(NEW, encoding="utf-8")

    escaped = row["command_template"].replace(verb, "\\" + verb, 1)
    assert "\\" + verb in escaped
    command = fill(escaped, {"{SRC}": str(source), "{DIR}": str(work),
                             "{URL}": http_url, "{TARGET}": str(target)})
    result = run_guard(command, cwd=work)
    assert result.returncode == 2, (
        f"\\{verb} must be refused exactly as {verb} is\n{result.stderr}")
    assert rp(target) in result.stderr
    assert target.read_text(encoding="utf-8") == original

    # And creation through the same syntax is still never denied.
    created = work / "created.txt"
    allow = fill(escaped, {"{SRC}": str(source), "{DIR}": str(work),
                           "{URL}": http_url, "{TARGET}": str(created)})
    assert run_guard(allow, cwd=work).returncode == 0


@pytest.mark.parametrize("row", COVERED_VERB_ROUTES,
                         ids=[r["route_id"] for r in COVERED_VERB_ROUTES])
def test_f2_subshell_grouping_defeats_no_covered_route(row, tmp_path, http_url):
    """A grouping paren was worse than a miss: it produced an affirmative ALLOW.

    `)` was absorbed into the path token, so the guard resolved a path that
    does not exist, judged the call CREATION, and permitted a real replacement.
    `(cd dir && cmd > file)` is a very common agent idiom.
    """
    work = tmp_path / f"subshell-{row['route_id']}"
    work.mkdir(parents=True)
    target = work / (row.get("victim_name") or "victim.txt")
    original = original_bytes()
    target.write_text(original, encoding="utf-8")
    source = work / "source.txt"
    source.write_text(NEW, encoding="utf-8")

    inner = fill(row["command_template"], {"{SRC}": str(source), "{DIR}": str(work),
                                           "{URL}": http_url, "{TARGET}": str(target)})
    for command in (f"({inner})", f"(cd {work} && {inner})"):
        result = run_guard(command, cwd=work)
        assert result.returncode == 2, (
            f"{command!r} must be refused exactly as the bare form is\n{result.stderr}")
        assert rp(target) in result.stderr
        assert target.read_text(encoding="utf-8") == original


def test_f2_token_termination_does_not_over_reach(tmp_path):
    """The fix must not start naming things that are not targets.

    Making `)` terminate a token could regress three shapes, so each is pinned:
    a quoted filename that really contains parentheses (still judged), process
    substitution (still never a named target), and a read-only command whose
    redirect merely goes to a device inside a subshell (still ungated).
    """
    work = tmp_path / "no-over-reach"
    work.mkdir()
    parens = work / "report (1).txt"
    original = original_bytes()
    parens.write_text(original, encoding="utf-8")

    denied = run_guard(f'echo {NEW} > "{parens}"', cwd=work)
    assert denied.returncode == 2, "a quoted path containing ')' must still be judged"
    assert parens.read_text(encoding="utf-8") == original

    for allowed in (
        f"echo {NEW} > >(cat)",                                    # process substitution
        f"diff <(sort {parens}) <(sort {parens}) > {work}/d.txt",  # both, plus creation
        "(ls /nonexistent 2>/dev/null || true) | head",            # QA's own live probe
        f"(cd {work} && cat 'report (1).txt' | wc -l)",            # read-only in a group
    ):
        assert run_guard(allowed, cwd=work).returncode == 0, f"{allowed!r} must be ungated"

    # Creation inside a group is still creation.
    assert run_guard(f"(cd {work} && echo {NEW} > brand-new.txt)", cwd=work).returncode == 0


@pytest.mark.parametrize("template, mech", [
    ("curl -sS -o{TARGET} {URL}", "curl-output"),
    ("curl -sSo{TARGET} {URL}", "curl-output"),
    ("wget -q -O{TARGET} {URL}", "wget-output"),
    ("wget -qO{TARGET} {URL}", "wget-output"),
])
def test_f1_attached_output_flag_is_read(template, mech, tmp_path, http_url):
    """getopt accepts -o/path exactly as -o /path; only the spaced form was read."""
    work = tmp_path / f"attached-{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True)
    target = work / "victim.txt"
    original = original_bytes()
    target.write_text(original, encoding="utf-8")

    command = fill(template, {"{TARGET}": str(target), "{URL}": http_url})
    result = run_guard(command, cwd=work)
    assert result.returncode == 2, f"{command!r} must be refused\n{result.stderr}"
    assert mech in result.stderr
    assert target.read_text(encoding="utf-8") == original

    created = work / "created.txt"
    allow = fill(template, {"{TARGET}": str(created), "{URL}": http_url})
    assert run_guard(allow, cwd=work).returncode == 0
    assert sh(allow, cwd=work).returncode == 0
    assert created.read_text(encoding="utf-8") == NEW


def test_f1_f2_do_not_gate_ordinary_developer_work(tmp_path):
    """The binding narrowing, re-asserted against BOTH new syntaxes.

    A guard that fires on routine work gets switched off, and then nothing is
    protected. Neither token normalization may reach an edit tool, an append,
    an in-place edit, or a creation — in plain, grouped or escaped form.
    """
    work = tmp_path / "ordinary"
    work.mkdir()
    target = work / "victim.txt"
    original = original_bytes()
    target.write_text(original, encoding="utf-8")
    source = work / "source.txt"
    source.write_text(NEW, encoding="utf-8")

    ungated = [
        f"echo {NEW} >> {target}",
        f"(cd {work} && echo {NEW} >> {target})",
        f"echo {NEW} | \\tee -a {target}",
        f"(sed -i s/{original}/REPLACED/ {target})",
        f"\\cp {source} {work}/fresh-copy.txt",
        f"(cp {source} {work}/fresh-copy-2.txt)",
        f"\\mv {source} {work}/renamed.txt",
        "ls -la | wc -l",
        f"grep -c . {target}",
        f"(cd {work} && git status --porcelain 2>/dev/null | head)",
    ]
    for command in ungated:
        result = run_guard(command, cwd=work)
        assert result.returncode == 0, f"{command!r} must be ungated\n{result.stderr}"

    for command in ungated[:7]:
        assert sh(command, cwd=work).returncode == 0, f"{command!r} must also RUN"


# ---------------------------------------------------------------------------
# AC-10 — the shared lexer stays backward compatible for all THREE consumers
# ---------------------------------------------------------------------------

CONSUMERS = (
    "hooks/pretool-tool-policy.py",
    "hooks/pretool-overnight-hook-guard.py",
    "hooks/pretool-cp-state-write-guard.py",
)


def test_ac10_doctests_pass():
    failures, _ = doctest.testmod(bwt, verbose=False)
    assert failures == 0


def test_ac10_frozen_extractor_signature_and_return_shape():
    signature = inspect.signature(bwt.extract_bash_write_paths)
    assert list(signature.parameters) == ["command"]
    assert signature.return_annotation in ("List[str]", list)
    result = bwt.extract_bash_write_paths("cat > /tmp/a.txt << EOF\nhello\nEOF")
    assert isinstance(result, list) and all(isinstance(x, str) for x in result)


@pytest.mark.parametrize("command, expected", [
    ("cat > /tmp/a.txt << EOF\nhello\nEOF", ["/tmp/a.txt"]),
    ("tee -a /tmp/x.txt", ["/tmp/x.txt"]),
    ("cp src dest", ["dest"]),
    ("mv src dest", ["dest"]),
    ("sed -i s/a/b/ /tmp/file", ["/tmp/file"]),
    ("install -m 755 src /usr/local/bin/x", ["/usr/local/bin/x"]),
    ("echo hello >> /var/log/app.log", ["/var/log/app.log"]),
    ("echo 'need >=10/3 items'", []),
    ("echo 'foo > bar'", []),
    ("echo X", []),
    # Iteration 1 pinned the shapes the OTHER consumers depend on, because the
    # token-termination fix lives in the shared reader rather than in this
    # guard's own extractor: the same absorbed ')' fails OPEN here and fails
    # CLOSED in pretool-tool-policy.py, which refused a read-only
    # '(… 2>/dev/null) | head' by inventing a write target named '/dev/null)'.
    ("ls /nope 2>&1", []),
    ("cmd --reason 'scope reduction' > /tmp/o", ["/tmp/o"]),
    ('cmd <<<"hello world" > /tmp/out', ["/tmp/out"]),
    ("cp x /tmp/my\\ file.txt", ["file.txt"]),  # pre-existing: this reader splits on space
    ("diff <(sort a) <(sort b) > /tmp/d", ["/tmp/d"]),
    ("echo x > >(cat)", []),
    ("f() { echo x > /tmp/a.txt; }", ["/tmp/a.txt"]),
    ("case $x in a) echo hi;; esac", []),
    ("git status --porcelain | head -20", []),
])
def test_ac10_frozen_extractor_behaviour_unchanged(command, expected):
    assert bwt.extract_bash_write_paths(command) == expected


@pytest.mark.parametrize("command, expected", [
    ("(cd /d && echo x > /tmp/a.txt)", ["/tmp/a.txt"]),
    ("(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | head", ["/dev/null"]),
    ("(cp s /tmp/a.txt)", ["/tmp/a.txt"]),
    ("(sed -i s/a/b/ /tmp/file)", ["/tmp/file"]),
    ("\\cp src /tmp/a.txt", ["/tmp/a.txt"]),
    ("echo x | \\tee /tmp/a.txt", ["/tmp/a.txt"]),
    ("(diff <(sort a) <(sort b) > /tmp/d)", ["/tmp/d"]),
])
def test_ac10_frozen_extractor_names_the_true_path_in_grouped_and_escaped_forms(command, expected):
    """The four consumers share this reader, so the correction reaches them all.

    Each of these previously returned either nothing (the write escaped the
    policy consumers entirely) or a path with a parenthesis glued to it (which
    resolves to nothing, and which tool-policy reported as a bogus deny target).
    Naming the true path is the same answer both consumers already give for the
    ungrouped form.
    """
    assert bwt.extract_bash_write_paths(command) == expected


def test_ac10_quoted_paths_are_untouched_by_the_token_terminator():
    """The quoted branch of the token reader is deliberately not changed."""
    assert bwt.extract_bash_write_paths('echo x > "/tmp/report (1).txt"') == \
        ["/tmp/report (1).txt"]
    assert [t.path for t in bwt.extract_bash_write_targets_with_modes(
        "echo x > '/tmp/a (copy).txt'")] == ["/tmp/a (copy).txt"]


@pytest.mark.parametrize("consumer", CONSUMERS)
def test_ac10_consumers_still_compile_and_import_the_frozen_symbol(consumer):
    path = REPO / consumer
    text = path.read_text(encoding="utf-8")
    assert "extract_bash_write_paths" in text
    assert "extract_bash_write_targets_with_modes" not in text, (
        "existing consumers must be unaffected by the additive extension")
    compiled = subprocess.run([sys.executable, "-m", "py_compile", str(path)],
                              capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr


def test_ac10_fourth_consumer_of_the_shared_module_is_pinned_too():
    """CORRECTION to the analysis: the module has FOUR consumers, not three.

    hooks/pretool-wrapper-userintent.py imports command_without_heredoc_bodies
    from the same module. The criterion enumerated only the three that import
    extract_bash_write_paths, so this consumer had no pin at all. It does now.
    """
    path = REPO / "hooks" / "pretool-wrapper-userintent.py"
    assert "from lib.bash_write_targets import command_without_heredoc_bodies" in \
        path.read_text(encoding="utf-8")
    compiled = subprocess.run([sys.executable, "-m", "py_compile", str(path)],
                              capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr
    signature = inspect.signature(bwt.command_without_heredoc_bodies)
    assert list(signature.parameters) == ["command"]
    assert bwt.command_without_heredoc_bodies("cat > /tmp/a << EOF\nhello\nEOF") == \
        "cat > /tmp/a << EOF"
    assert bwt.command_without_heredoc_bodies("echo plain") == "echo plain"
