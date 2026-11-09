"""scripts/steps/paseo-bootstrap.py: Bootstrap steps 1, 2 and 4 of commands/paseo-daemon.md.

The script is run for real, as a subprocess, with the ledger CLI and the timers CLI behind it.
Every path is a pytest tmp_path: the ledger root, the timer registry (--registry-dir) and HOME,
so the real registry under the home directory is never reached and no daemon is touched.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "steps" / "paseo-bootstrap.py"
FOUR_KEYS = ("tick", "reinject", "watchdog", "sweep")
CONTROLLER_AGENT_ID = "agent-controller-test"
RESET_A = "2026-11-12T07:00:00Z"
RESET_B = "2026-11-13T19:30:00Z"


def run(tmp_path, *args, env_extra=None, drop_accounts_env=True):
    env = {k: v for k, v in os.environ.items() if k != "PASEO_DAEMON_ACCOUNTS"} if drop_accounts_env else dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    env.update(env_extra or {})
    proc = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                          cwd=REPO, env=env)
    facts = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.partition("=")
        assert sep, f"not a key=value line: {line!r}"
        facts[key] = value
    return proc, facts


def make_prompts(tmp_path):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    for key in FOUR_KEYS:
        (prompts / f"{key}.prompt.txt").write_text(f"synthetic prompt for {key}\n")
    return prompts


def start_args(tmp_path, holder="ctrl-1", **extra):
    prompts = tmp_path / "prompts"
    if not prompts.exists():
        make_prompts(tmp_path)
    args = ["start", "--holder", holder, "--root", tmp_path / "ledger", "--accounts", "acct-a,acct-b",
            "--registry-dir", tmp_path / "registry", "--controller-agent-id", CONTROLLER_AGENT_ID,
            "--prompts-dir", prompts]
    for flag, value in extra.items():
        args += [f"--{flag.replace('_', '-')}", value]
    return args


def registry_files(tmp_path):
    registry = tmp_path / "registry"
    return sorted(registry.glob("*.json")) if registry.exists() else []


def test_start_initializes_the_ledger_creates_the_timers_and_takes_the_lease(tmp_path):
    proc, facts = run(tmp_path, *start_args(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert facts["status"] == "ok" and facts["failed_at"] == "none"
    assert (facts["init"], facts["timers"], facts["lease"]) == ("ok", "ok", "acquired")
    assert facts["init_exit"] == facts["timers_exit"] == facts["lease_exit"] == "0"
    assert sorted(facts["timers_created"].split(",")) == sorted(FOUR_KEYS)
    assert facts["timers_deviations"] == "none"
    assert json.loads(facts["timers_json"])["ok"] is True
    assert (facts["lease_holder"], facts["lease_incarnation"]) == ("ctrl-1", "1")

    ledger = tmp_path / "ledger"
    accounts = json.loads((ledger / "accounts.json").read_text())["accounts"]
    assert sorted(accounts) == ["acct-a", "acct-b"]
    assert all(account["state"] == "unknown" for account in accounts.values())
    assert (ledger / "config.json").is_file() and (ledger / "inbox" / "watermark.json").is_file()
    assert json.loads((ledger / "lease.json").read_text())["holder"] == "ctrl-1"
    assert len(registry_files(tmp_path)) == 4


def test_start_twice_creates_nothing_again_and_bumps_the_incarnation(tmp_path):
    run(tmp_path, *start_args(tmp_path))
    before = {p.name: p.read_text() for p in registry_files(tmp_path)}
    proc, facts = run(tmp_path, *start_args(tmp_path))
    assert proc.returncode == 0 and facts["status"] == "ok"
    assert facts["timers_created"] == "none"
    assert facts["lease_incarnation"] == "2"
    assert {p.name: p.read_text() for p in registry_files(tmp_path)} == before


def test_start_takes_the_account_names_from_the_environment_when_no_flag_is_given(tmp_path):
    args = [a for a in start_args(tmp_path)]
    index = args.index("--accounts")
    del args[index:index + 2]
    proc, facts = run(tmp_path, *args, env_extra={"PASEO_DAEMON_ACCOUNTS": "env-a,env-b,env-c"})
    assert facts["status"] == "ok", proc.stdout
    accounts = json.loads((tmp_path / "ledger" / "accounts.json").read_text())["accounts"]
    assert sorted(accounts) == ["env-a", "env-b", "env-c"]


def test_start_without_any_account_stops_at_init_and_touches_nothing_else(tmp_path):
    args = start_args(tmp_path)
    index = args.index("--accounts")
    del args[index:index + 2]
    proc, facts = run(tmp_path, *args)
    assert proc.returncode == 0
    assert (facts["status"], facts["failed_at"]) == ("failed", "init")
    assert (facts["init"], facts["timers"], facts["lease"]) == ("failed", "skipped", "skipped")
    assert facts["init_exit"] != "0" and "no account given" in facts["init_message"]
    assert registry_files(tmp_path) == []
    assert not (tmp_path / "ledger" / "lease.json").exists()


def test_start_fails_closed_at_timers_when_a_timer_cannot_be_created(tmp_path):
    args = start_args(tmp_path)
    index = args.index("--prompts-dir")
    del args[index:index + 2]
    proc, facts = run(tmp_path, *args)
    assert (facts["status"], facts["failed_at"]) == ("failed", "timers")
    assert (facts["init"], facts["timers"], facts["lease"]) == ("ok", "failed", "skipped")
    assert "cannot create missing timer(s), zero files written" in facts["timers_message"]
    assert registry_files(tmp_path) == []
    assert not (tmp_path / "ledger" / "lease.json").exists()


def test_start_reports_a_lease_another_holder_has_not_released(tmp_path):
    run(tmp_path, *start_args(tmp_path, holder="ctrl-1"))
    proc, facts = run(tmp_path, *start_args(tmp_path, holder="ctrl-2"))
    assert proc.returncode == 0
    assert (facts["status"], facts["failed_at"], facts["lease"]) == ("failed", "lease", "refused")
    assert "takeover only after expiry" in facts["lease_message"]
    assert (facts["init"], facts["timers"]) == ("ok", "ok")
    assert json.loads((tmp_path / "ledger" / "lease.json").read_text())["holder"] == "ctrl-1"


def test_a_warning_before_the_refusal_does_not_hide_the_refusal(tmp_path):
    run(tmp_path, *start_args(tmp_path, holder="ctrl-1"))
    proc, facts = run(tmp_path, *start_args(tmp_path, holder="ctrl-2", ttl_seconds="10"))
    assert facts["lease"] == "refused"
    assert "takeover only after expiry" in facts["lease_message"]


def test_start_takes_over_an_expired_lease(tmp_path):
    run(tmp_path, *start_args(tmp_path, holder="ctrl-1", ttl_seconds="1"))
    lease_path = tmp_path / "ledger" / "lease.json"
    lease = json.loads(lease_path.read_text())
    lease["expires_at"] = "2020-01-01T00:00:00Z"
    lease_path.write_text(json.dumps(lease))
    proc, facts = run(tmp_path, *start_args(tmp_path, holder="ctrl-2"))
    assert facts["status"] == "ok" and facts["lease_holder"] == "ctrl-2"
    assert facts["lease_incarnation"] == "2"


def test_start_names_a_paused_timer_as_a_deviation(tmp_path):
    run(tmp_path, *start_args(tmp_path))
    paused = [p for p in registry_files(tmp_path) if json.loads(p.read_text())["name"] == "ctrl-core-reinject"]
    assert len(paused) == 1
    document = json.loads(paused[0].read_text())
    document["status"] = "paused"
    paused[0].write_text(json.dumps(document))
    proc, facts = run(tmp_path, *start_args(tmp_path))
    assert facts["status"] == "ok" and facts["timers_created"] == "none"
    assert facts["timers_deviations"] == "reinject"
    assert json.loads(paused[0].read_text())["status"] == "paused"


def test_start_without_registry_dir_uses_the_registry_under_home(tmp_path):
    args = start_args(tmp_path)
    index = args.index("--registry-dir")
    del args[index:index + 2]
    proc, facts = run(tmp_path, *args)
    assert facts["status"] == "ok", proc.stdout
    assert len(list((tmp_path / "home" / ".paseo" / "schedules").glob("*.json"))) == 4
    assert registry_files(tmp_path) == []


def test_accounts_seeds_each_reset_instant_after_the_lease_is_taken(tmp_path):
    run(tmp_path, *start_args(tmp_path))
    proc, facts = run(tmp_path, "accounts", "--root", tmp_path / "ledger", "--caller-id", "ctrl-1",
                      "--reset", f"acct-a={RESET_A}", "--reset", f"acct-b={RESET_B}")
    assert proc.returncode == 0, proc.stderr
    assert facts["status"] == "ok"
    assert (facts["account_acct-a"], facts["account_acct-b"]) == ("ok", "ok")
    accounts = json.loads((tmp_path / "ledger" / "accounts.json").read_text())["accounts"]
    assert accounts["acct-a"]["weekly_reset_at"] == RESET_A
    assert accounts["acct-b"]["weekly_reset_at"] == RESET_B
    assert accounts["acct-a"]["state"] == accounts["acct-b"]["state"] == "eligible"


def test_accounts_reports_each_failure_and_goes_on_with_the_rest(tmp_path):
    run(tmp_path, *start_args(tmp_path))
    proc, facts = run(tmp_path, "accounts", "--root", tmp_path / "ledger", "--caller-id", "ctrl-1",
                      "--reset", f"unknown-acct={RESET_A}", "--reset", f"acct-b={RESET_B}")
    assert proc.returncode == 0
    assert facts["status"] == "failed"
    assert facts["account_unknown-acct"] == "failed" and facts["account_unknown-acct_message"]
    assert facts["account_acct-b"] == "ok"
    accounts = json.loads((tmp_path / "ledger" / "accounts.json").read_text())["accounts"]
    assert accounts["acct-b"]["weekly_reset_at"] == RESET_B


def test_accounts_refuses_a_caller_that_does_not_hold_the_lease(tmp_path):
    run(tmp_path, *start_args(tmp_path))
    proc, facts = run(tmp_path, "accounts", "--root", tmp_path / "ledger", "--caller-id", "someone-else",
                      "--reset", f"acct-a={RESET_A}")
    assert facts["status"] == "failed" and facts["account_acct-a"] == "failed"
    assert "lease held by ctrl-1" in facts["account_acct-a_message"]
    accounts = json.loads((tmp_path / "ledger" / "accounts.json").read_text())["accounts"]
    assert accounts["acct-a"]["weekly_reset_at"] is None


def test_wrong_arguments_exit_2_and_print_no_facts(tmp_path):
    for argv in (["start"], ["accounts", "--caller-id", "x"], ["accounts", "--caller-id", "x", "--reset", "no-equals"],
                 ["bogus"], []):
        proc, facts = run(tmp_path, *argv)
        assert proc.returncode == 2, argv
        assert facts == {}, argv


def test_the_command_bootstrap_section_calls_both_subcommands_and_the_flags_exist():
    text = (REPO / "commands" / "paseo-daemon.md").read_text(encoding="utf-8")
    start = text.index("\n## Bootstrap\n")
    section = text[start:text.index("\n## ", start + 1)]
    assert 'python3 "<HARNESS_ROOT>/scripts/steps/paseo-bootstrap.py" start --holder ' in section
    assert 'python3 "<HARNESS_ROOT>/scripts/steps/paseo-bootstrap.py" accounts --caller-id ' in section
    for call in ("start", "accounts"):
        help_text = subprocess.run([sys.executable, str(SCRIPT), call, "--help"], capture_output=True,
                                   text=True, cwd=REPO).stdout
        for flag in {"start": ("--holder", "--ttl-seconds", "--controller-agent-id", "--prompts-dir"),
                     "accounts": ("--caller-id", "--reset")}[call]:
            assert flag in section and flag in help_text, (call, flag)
