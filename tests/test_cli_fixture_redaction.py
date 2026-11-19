"""No recorded CLI fixture keeps the account's usage or a model id (scripts/cli-fixture-record.sh).

The recorder's account rule writes 0 for a token, request or cost count and for a clock time kept as
a number; 0, false or "<redacted>" for every value of a rate-limit reading (stream-json's
rate_limit_event) and every utilization or overage value; and a stand-in for a model id.
`cli-fixture-record.sh --redact` runs that rule alone on a recording made by hand. Every file under
tests/fixtures that the CLI wrote, the recorder's tests/fixtures/cli/<version> files and the
hand-recorded tests/fixtures/cli-todowrite-oldtodos stream and cli-request-copies excerpt alike, is a
fixed point of it.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "cli-fixture-record.sh"
FIXTURES = REPO / "tests" / "fixtures"
# shapes.json is derived from the recordings (types only); CURRENT and README.md are not JSON.
RECORDINGS = sorted(p for d in ("cli", "cli-todowrite-oldtodos", "cli-request-copies") for p in (FIXTURES / d).rglob("*")
                    if p.suffix in (".json", ".jsonl") and p.name != "shapes.json")


def _redact(tmp_path, *files):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": str(tmp_path)}
    return subprocess.run(["bash", str(SCRIPT), "--redact", *map(str, files)], env=env,
                          capture_output=True, text=True, timeout=60)


def test_every_cli_recording_is_already_under_the_account_rule(tmp_path):
    assert FIXTURES / "cli-todowrite-oldtodos" / "stream-2.1.326.jsonl" in RECORDINGS
    assert FIXTURES / "cli-request-copies" / "transcript-2.1.322.jsonl" in RECORDINGS
    copies = []
    for i, path in enumerate(RECORDINGS):
        copy = tmp_path / f"{i}{path.suffix}"
        shutil.copyfile(path, copy)
        copies.append((path, copy))
    result = _redact(tmp_path, *(copy for _, copy in copies))
    assert result.returncode == 0, result.stderr
    for path, copy in copies:
        assert copy.read_bytes() == path.read_bytes(), (
            f"{path.relative_to(REPO)} keeps a value the account rule removes: "
            f"run bash scripts/cli-fixture-record.sh --redact on it")


def test_the_rule_removes_usage_rate_limits_and_model_values_and_nothing_else(tmp_path):
    record = {"type": "result", "model": "an-alias", "requestedModel": "<synthetic>", "result": "DONE",
              "usage": {"input_tokens": 7, "server_tool_use": {"web_search_requests": 1}},
              "total_cost_usd": 0.5, "duration_ms": 12, "nextFireAt": 1795168800,
              "modelUsage": {"<MODEL>": {"costUSD": 0.5, "webSearchRequests": 2, "contextWindow": 9}},
              "rate_limit_info": {"status": "allowed_warning", "utilization": 0.84, "resetsAt": 1795168800,
                                  "isUsingOverage": True, "overageStatus": "rejected",
                                  "unifiedWindows": {"seven_day": {"surpassedThreshold": 0.75}}}}
    path = tmp_path / "stream.jsonl"
    path.write_text(json.dumps(record, separators=(",", ":")) + "\n")

    result = _redact(tmp_path, path)

    assert result.returncode == 0, result.stderr
    expected = {"type": "result", "model": "<MODEL>", "requestedModel": "<synthetic>", "result": "DONE",
                "usage": {"input_tokens": 0, "server_tool_use": {"web_search_requests": 0}},
                "total_cost_usd": 0, "duration_ms": 12, "nextFireAt": 0,
                "modelUsage": {"<MODEL>": {"costUSD": 0, "webSearchRequests": 0, "contextWindow": 9}},
                "rate_limit_info": {"status": "<redacted>", "utilization": 0, "resetsAt": 0,
                                    "isUsingOverage": False, "overageStatus": "<redacted>",
                                    "unifiedWindows": {"seven_day": {"surpassedThreshold": 0}}}}
    # The CLI's own layout (compact, its key order) is kept.
    assert path.read_text() == json.dumps(expected, separators=(",", ":")) + "\n"


def test_a_layout_the_rule_cannot_write_back_is_left_as_it_was(tmp_path):
    path = tmp_path / "odd.jsonl"
    text = '{"input_tokens":  7}\n'
    path.write_text(text)

    result = _redact(tmp_path, path)

    assert result.returncode == 1
    assert "a JSON layout this script does not write" in result.stderr
    assert path.read_text() == text
