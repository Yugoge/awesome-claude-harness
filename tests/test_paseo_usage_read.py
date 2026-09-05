"""BUILD-AC08 facade — usage-read path real and consumed end-to-end.

MANDATORY pytest facade for lane 20260828-112025-b: collects EVERY test
binding a BUILD-AC08 assertion (docs/dev/acceptance-criteria-20260828-112025-b.json):
live read-only adapter run against the paseo daemon, captured-envelope fixture
end-to-end chain (adapter stdout JSON -> ledger usage-ingest -> persisted
per-account state -> scheduling decision), blind-window -> unknown mapping
(amended RUNTIME-AC07), settings parse assertions, and the adapter source
audit (no mutation RPC).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ADAPTER = REPO / "scripts" / "paseo-usage-read.mjs"
LEDGER = REPO / "scripts" / "paseo-daemon-ledger.py"
FIXTURE = REPO / "tests" / "fixtures" / "paseo-usage-envelope-20260828.json"
COMMAND = REPO / "commands" / "paseo-daemon.md"
ALLOW_MATCHER = "Bash(node scripts/paseo-usage-read.mjs:*)"
ACCOUNTS = ["orchestrade", "yugetang", "yugoge"]
T0 = "2026-08-28T19:07:02Z"


def run_adapter(*args):
    return subprocess.run(["node", str(ADAPTER), *args],
                          capture_output=True, text=True, cwd=REPO, timeout=30)


def run_ledger(root, *args, stdin=None, now=T0):
    return subprocess.run(
        [sys.executable, str(LEDGER), "--root", str(root), "--now", now, *args],
        capture_output=True, text=True, input=stdin, cwd=REPO)


def init_root(tmp_path):
    root = tmp_path / "ledger"
    r = run_ledger(root, "init", "--accounts", ",".join(ACCOUNTS))
    assert r.returncode == 0, r.stderr
    return root


def claude_account_of(row):
    """Account identity: providerId PRIMARY (claude / claude-<account>)."""
    pid = row.get("providerId", "")
    if pid.startswith("claude-"):
        return pid[len("claude-"):]
    if pid == "claude":
        label = row.get("displayName", "")
        for name in ACCOUNTS:
            if name in label:
                return name
    return None


# ---------------- (1) live adapter run ----------------

def test_live_adapter_read_only_run_exits_zero_with_per_account_rows():
    r = run_adapter()
    assert r.returncode == 0, f"live adapter run failed: {r.stderr}"
    rows = json.loads(r.stdout)
    claude_rows = {}
    for row in rows:
        account = claude_account_of(row)
        if account is not None:
            assert account not in claude_rows, f"duplicate row for {account}"
            claude_rows[account] = row
    assert set(claude_rows) == set(ACCOUNTS), "one row per claude account required"
    for account, row in claude_rows.items():
        # display label CONTAINS the account name (punctuation non-normative)
        assert account in (row.get("displayName") or ""), (account, row.get("displayName"))
        # an all-unavailable live result is a valid blind-window outcome for
        # the LIVE half only — status just has to be a known enum value
        assert row.get("status") in ("available", "unavailable")


# ---------------- (2) captured-envelope fixture: end-to-end chain ----------------

def test_captured_fixture_round_trips_adapter_ingest_state_decision(tmp_path):
    # hop 1: adapter parses the captured envelope (offline, deterministic)
    r = run_adapter("--from-envelope", str(FIXTURE))
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    available = [row for row in rows if claude_account_of(row)
                 and row.get("status") == "available"]
    assert len(available) >= 1  # >= 1 available account row with a weekly window
    # hop 2: adapter stdout JSON -> ledger usage-ingest
    root = init_root(tmp_path)
    ri = run_ledger(root, "usage-ingest", stdin=r.stdout)
    assert ri.returncode == 0, ri.stderr
    assert sorted(json.loads(ri.stdout)["ingested"]) == ["orchestrade", "yugoge"]
    # hop 3: persisted per-account state preserves identity + reading fields
    accounts = json.loads((root / "accounts.json").read_text())["accounts"]
    orch = accounts["orchestrade"]
    assert orch["usage"]["providerId"] == "claude"
    assert orch["usage"]["status"] == "available"
    weekly = next(w for w in orch["usage"]["windows"] if w["id"] == "weekly")
    assert (weekly["usedPct"], weekly["remainingPct"]) == (14, 86)
    assert weekly["resetsAt"] == "2026-09-03T18:00:00Z"
    assert orch["weekly_reset_at"] == "2026-09-03T18:00:00Z"
    assert orch["tier"] == "plentiful"
    yugoge = accounts["yugoge"]
    assert yugoge["usage"]["providerId"] == "claude-yugoge"
    assert yugoge["weekly_reset_at"] == "2026-09-02T14:00:00Z"
    assert accounts["yugetang"]["tier"] == "unknown"  # live blind-window specimen
    # hop 4: the scheduling decision CONSUMES the persisted state
    rd = run_ledger(root, "scheduling-decision", "--account", "orchestrade",
                    "--task-class", "quality")
    assert rd.returncode == 0, rd.stderr
    decision = json.loads(rd.stdout)
    assert decision["tier"] == "plentiful" and decision["model"] == "fable 5"
    assert decision["action"] == "dispatch"


# ---------------- (3) blind windows map to unknown, no switch ----------------

def test_unavailable_row_and_missing_row_map_to_unknown_no_switch(tmp_path):
    root = init_root(tmp_path)
    providers = [
        # status=unavailable row
        {"providerId": "claude-yugetang", "displayName": "Claude · yugetang",
         "status": "unavailable", "windows": []},
        # orchestrade + yugoge rows entirely MISSING from the reading
    ]
    ri = run_ledger(root, "usage-ingest", stdin=json.dumps(providers))
    assert ri.returncode == 0, ri.stderr
    out = json.loads(ri.stdout)
    # unavailable row (yugetang) AND missing rows (orchestrade, yugoge) are
    # ALL the fetcher blind window
    assert sorted(out["blind_window"]) == ACCOUNTS and out["ingested"] == []
    accounts = json.loads((root / "accounts.json").read_text())["accounts"]
    for name in ACCOUNTS:
        assert accounts[name]["tier"] == "unknown", name
    for name in ACCOUNTS:
        rd = run_ledger(root, "scheduling-decision", "--account", name,
                        "--task-class", "general")
        decision = json.loads(rd.stdout)
        # conservative scheduling; NO account switch on the blind-window artifact
        assert decision["action"] == "hold_conservative", name
        assert decision["switch_account"] is False, name


# ---------------- (4) settings parse assertions ----------------

def test_allow_matcher_exactly_once_in_settings_json():
    settings = json.loads((REPO / "settings.json").read_text())
    allow = settings["permissions"]["allow"]
    assert allow.count(ALLOW_MATCHER) == 1
    deny = settings["permissions"]["deny"]
    assert ALLOW_MATCHER not in deny


def test_allow_matcher_nowhere_in_settings_template():
    raw = (REPO / "settings.template.json").read_text()
    assert ALLOW_MATCHER not in raw  # zero machine-specific paseo Bash entries


# ---------------- (5) command tick names the adapter as the usage-read step ----------------

def test_command_tick_section_names_adapter_invocation():
    text = COMMAND.read_text()
    sections = re.split(r"^## ", text, flags=re.M)
    tick = [s for s in sections if s.lower().startswith("tick loop")]
    assert len(tick) == 1, "exactly one tick-loop section expected"
    assert "paseo-usage-read.mjs" in tick[0], "tick must name the adapter invocation"


# ---------------- (6) source audit: no mutation RPC ----------------

def test_adapter_source_sends_only_usage_list_request():
    src = ADAPTER.read_text()
    request_types = set(re.findall(r'"([a-z][a-z0-9]*(?:\.[a-z0-9]+)*\.request)"', src))
    assert request_types == {"provider.usage.list.request"}, request_types
    # the only ws.send payload types are the hello handshake and the wrapped
    # usage request — no mutation RPC of any kind
    sent_types = set(re.findall(r'type:\s*"([^"]+)"', src))
    assert sent_types <= {"hello", "session", "provider.usage.list.request",
                          "provider.usage.list.response"}, sent_types
