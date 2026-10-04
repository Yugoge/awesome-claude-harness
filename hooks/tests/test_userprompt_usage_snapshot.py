#!/usr/bin/env python3
"""Tests for hooks/userprompt-usage-snapshot.py.

Covers the three cache states the hook must handle (cache hit, cache expired
+ successful re-read, read failure/timeout with degrade-to-last-success), the
as_of assertion in every emitted state, and the never-blocks-on-timeout bound.

Isolation: every test runs with CLAUDE_STATE_DIR pointed at a tmp_path (so the
cache file never touches the real /tmp global cache) and
CLAUDE_USAGE_ADAPTER_CMD pointed at a tiny stub script (so no real node
process, websocket, daemon, or ledger is ever touched). A "poison" adapter
command is used in the cache-hit test specifically to PROVE no new read
process is spawned on a cache hit: if the hook spawned it, the test would see
its sentinel file appear.
"""

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "hooks" / "userprompt-usage-snapshot.py"

FIXTURE_PROVIDERS = [
    {
        "providerId": "claude",
        "displayName": "Claude · orchestrade",
        "status": "available",
        "windows": [
            {"id": "five_hour", "label": "Session", "usedPct": 8, "remainingPct": 92,
             "resetsAt": "2026-08-29T00:00:00Z"},
            {"id": "weekly", "label": "Weekly", "usedPct": 14, "remainingPct": 86,
             "resetsAt": "2026-09-03T18:00:00Z"},
        ],
    },
    {
        "providerId": "claude-yugetang",
        "displayName": "Claude · yugetang",
        "status": "unavailable",
        "windows": [],
    },
]


def load_hook_module():
    spec = importlib.util.spec_from_file_location("userprompt_usage_snapshot_under_test", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_stub_adapter(path: Path, *, stdout_json=None, exit_code=0, sleep_seconds=0):
    """A tiny python stub standing in for scripts/paseo-usage-read.mjs."""
    payload = json.dumps(stdout_json if stdout_json is not None else [])
    path.write_text(
        "import sys, time, json\n"
        f"time.sleep({sleep_seconds})\n"
        f"sys.stdout.write({payload!r})\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )


def run_hook(env):
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input="{}",
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def base_env(tmp_path, monkeypatch_env):
    env = dict(monkeypatch_env)
    env["CLAUDE_STATE_DIR"] = str(tmp_path)
    return env


# ---------------- unit-level: normalization and formatting ----------------

def test_normalize_providers_extracts_session_and_weekly_windows():
    mod = load_hook_module()
    rows = mod._normalize_providers(FIXTURE_PROVIDERS)
    assert len(rows) == 2
    orch = rows[0]
    assert orch["provider_id"] == "claude"
    assert orch["session"]["remaining_pct"] == 92
    assert orch["session"]["resets_at"] == "2026-08-29T00:00:00Z"
    assert orch["weekly"]["remaining_pct"] == 86
    yugetang = rows[1]
    assert yugetang["status"] == "unavailable"
    assert yugetang["session"] is None and yugetang["weekly"] is None


def test_normalize_providers_accepts_dict_wrapped_providers_key():
    mod = load_hook_module()
    rows = mod._normalize_providers({"providers": FIXTURE_PROVIDERS})
    assert len(rows) == 2


def test_normalize_providers_rejects_non_list_non_dict():
    mod = load_hook_module()
    assert mod._normalize_providers("garbage") == []
    assert mod._normalize_providers(None) == []


def test_format_context_ok_state_includes_as_of_and_fresh_label():
    mod = load_hook_module()
    now = 1_000_000.0
    cache = {
        "last_attempt_status": "ok",
        "last_success": {
            "as_of_epoch": now - 5,
            "as_of_iso": "2026-10-04T08:30:00Z",
            "providers": mod._normalize_providers(FIXTURE_PROVIDERS),
        },
    }
    text = mod._format_context(now, cache)
    assert "as_of=2026-10-04T08:30:00Z" in text
    assert "fresh" in text and "STALE" not in text
    assert "orchestrade" in text or "claude" in text
    assert "92% remaining" in text


def test_format_context_failure_with_prior_success_is_stale_and_names_the_failure():
    mod = load_hook_module()
    now = 1_000_000.0
    cache = {
        "last_attempt_status": "failed_timeout",
        "last_attempt_note": "adapter timed out after 5s",
        "last_success": {
            "as_of_epoch": now - 9000,
            "as_of_iso": "2026-10-04T06:00:00Z",
            "providers": mod._normalize_providers(FIXTURE_PROVIDERS),
        },
    }
    text = mod._format_context(now, cache)
    assert "as_of=2026-10-04T06:00:00Z" in text
    assert "STALE" in text
    assert "failed_timeout" in text
    assert "adapter timed out after 5s" in text


def test_format_context_never_succeeded_says_so_plainly():
    mod = load_hook_module()
    cache = {"last_attempt_status": "failed_error", "last_attempt_note": "boom"}
    text = mod._format_context(1_000_000.0, cache)
    assert "no successful reading yet" in text
    assert "failed_error" in text and "boom" in text


# ---------------- end-to-end: the three cache states, sandboxed ----------------

def test_cache_miss_successful_read_populates_cache_and_emits_as_of(tmp_path, monkeypatch):
    stub = tmp_path / "stub_ok.py"
    write_stub_adapter(stub, stdout_json=FIXTURE_PROVIDERS, exit_code=0)
    env = base_env(tmp_path, dict(**{"PATH": __import__("os").environ.get("PATH", "")}))
    env["CLAUDE_USAGE_ADAPTER_CMD"] = f"{sys.executable} {stub}"

    r = run_hook(env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "as_of=" in text
    assert "fresh" in text
    assert "92% remaining" in text

    cache_file = tmp_path / "claude-usage-snapshot-cache.json"
    cache = json.loads(cache_file.read_text())
    assert cache["last_attempt_status"] == "ok"
    assert cache["last_success"]["providers"][0]["session"]["remaining_pct"] == 92


def test_cache_hit_never_spawns_a_new_read_process(tmp_path, monkeypatch):
    cache_file = tmp_path / "claude-usage-snapshot-cache.json"
    sentinel = tmp_path / "poison-ran.flag"
    now = time.time()
    cache_file.write_text(json.dumps({
        "last_attempt_epoch": now - 10,  # well within the 300s TTL
        "last_attempt_iso": "irrelevant",
        "last_attempt_status": "ok",
        "last_attempt_note": None,
        "last_success": {
            "as_of_epoch": now - 10,
            "as_of_iso": "2026-10-04T08:29:50Z",
            "providers": [],
        },
    }))

    poison = tmp_path / "poison.py"
    poison.write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('ran')\n"
        "import sys; sys.stdout.write('[]'); sys.exit(0)\n",
        encoding="utf-8",
    )
    env = {"PATH": __import__("os").environ.get("PATH", "")}
    env["CLAUDE_STATE_DIR"] = str(tmp_path)
    env["CLAUDE_USAGE_ADAPTER_CMD"] = f"{sys.executable} {poison}"

    r = run_hook(env)
    assert r.returncode == 0, r.stderr
    assert not sentinel.exists(), "cache hit must not spawn a new read process"
    out = json.loads(r.stdout)
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "as_of=2026-10-04T08:29:50Z" in text
    assert "fresh" in text


def test_cache_expired_triggers_fresh_read(tmp_path, monkeypatch):
    cache_file = tmp_path / "claude-usage-snapshot-cache.json"
    now = time.time()
    cache_file.write_text(json.dumps({
        "last_attempt_epoch": now - 3600,  # older than the 300s TTL
        "last_attempt_iso": "2026-10-04T07:00:00Z",
        "last_attempt_status": "ok",
        "last_attempt_note": None,
        "last_success": {
            "as_of_epoch": now - 3600,
            "as_of_iso": "2026-10-04T07:00:00Z",
            "providers": [],
        },
    }))

    stub = tmp_path / "stub_fresh.py"
    write_stub_adapter(stub, stdout_json=FIXTURE_PROVIDERS, exit_code=0)
    env = {"PATH": __import__("os").environ.get("PATH", "")}
    env["CLAUDE_STATE_DIR"] = str(tmp_path)
    env["CLAUDE_USAGE_ADAPTER_CMD"] = f"{sys.executable} {stub}"

    r = run_hook(env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "2026-10-04T07:00:00Z" not in text  # the stale as_of must be replaced
    assert "fresh" in text

    cache = json.loads(cache_file.read_text())
    assert cache["last_attempt_epoch"] > now - 60  # refreshed just now


def test_read_failure_degrades_to_last_success_with_stale_label(tmp_path, monkeypatch):
    cache_file = tmp_path / "claude-usage-snapshot-cache.json"
    now = time.time()
    cache_file.write_text(json.dumps({
        "last_attempt_epoch": now - 3600,
        "last_attempt_iso": "2026-10-04T07:00:00Z",
        "last_attempt_status": "ok",
        "last_attempt_note": None,
        "last_success": {
            "as_of_epoch": now - 3600,
            "as_of_iso": "2026-10-04T07:00:00Z",
            "providers": [],
        },
    }))

    stub = tmp_path / "stub_fail.py"
    write_stub_adapter(stub, stdout_json=None, exit_code=2)
    env = {"PATH": __import__("os").environ.get("PATH", "")}
    env["CLAUDE_STATE_DIR"] = str(tmp_path)
    env["CLAUDE_USAGE_ADAPTER_CMD"] = f"{sys.executable} {stub}"

    r = run_hook(env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "as_of=2026-10-04T07:00:00Z" in text
    assert "STALE" in text
    assert "failed_error" in text

    cache = json.loads(cache_file.read_text())
    assert cache["last_attempt_status"] == "failed_error"
    assert cache["last_success"]["as_of_iso"] == "2026-10-04T07:00:00Z"  # unchanged


def test_timeout_does_not_block_and_degrades_with_note(tmp_path, monkeypatch):
    cache_file = tmp_path / "claude-usage-snapshot-cache.json"
    now = time.time()
    cache_file.write_text(json.dumps({
        "last_attempt_epoch": now - 3600,
        "last_attempt_iso": "2026-10-04T07:00:00Z",
        "last_attempt_status": "ok",
        "last_attempt_note": None,
        "last_success": {
            "as_of_epoch": now - 3600,
            "as_of_iso": "2026-10-04T07:00:00Z",
            "providers": [],
        },
    }))

    stub = tmp_path / "stub_hang.py"
    write_stub_adapter(stub, stdout_json=[], exit_code=0, sleep_seconds=30)
    env = {"PATH": __import__("os").environ.get("PATH", "")}
    env["CLAUDE_STATE_DIR"] = str(tmp_path)
    env["CLAUDE_USAGE_ADAPTER_CMD"] = f"{sys.executable} {stub}"

    started = time.monotonic()
    r = run_hook(env)
    elapsed = time.monotonic() - started

    assert r.returncode == 0, r.stderr
    # The hook's own READ_TIMEOUT_SECONDS (5s) bounds the wait; generous slack
    # for process-spawn overhead, still far under the stub's 30s sleep.
    assert elapsed < 15, f"hook took {elapsed}s -- must never block on a hung adapter"
    out = json.loads(r.stdout)
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "as_of=2026-10-04T07:00:00Z" in text
    assert "STALE" in text
    assert "failed_timeout" in text


def test_never_fetched_before_and_adapter_fails_says_unavailable_plainly(tmp_path, monkeypatch):
    stub = tmp_path / "stub_fail_first.py"
    write_stub_adapter(stub, stdout_json=None, exit_code=1)
    env = {"PATH": __import__("os").environ.get("PATH", "")}
    env["CLAUDE_STATE_DIR"] = str(tmp_path)
    env["CLAUDE_USAGE_ADAPTER_CMD"] = f"{sys.executable} {stub}"

    r = run_hook(env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "no successful reading yet" in text
    assert "failed_error" in text
