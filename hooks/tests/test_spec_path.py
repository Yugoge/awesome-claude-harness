"""hooks/lib/spec_path.py: the spec a session last wrote (P1b E14, PLAN-v2 P9 row 1),
and prompt-workflow.py's one decision of a run's spec built on it."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS / "lib"))
import spec_path  # noqa: E402

PROJECT = "/work/proj"
SPEC = f"{PROJECT}/docs/dev/specs/spec-20261028-101010.md"
OTHER = f"{PROJECT}/docs/dev/specs/spec-20261028-202020.md"


def _transcript(tmp_path, calls):
    """calls: (name, input, result_text or None for no result, is_error)."""
    path = tmp_path / "t.jsonl"
    lines = [{"type": "user", "message": {"role": "user", "content": "/spec"}}]
    for n, (name, tool_input, result, is_error) in enumerate(calls):
        tid = f"t{n}"
        lines.append({"type": "assistant", "cwd": PROJECT, "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": name, "input": tool_input}]}})
        if result is not None:
            block = {"type": "tool_result", "tool_use_id": tid, "content": result}
            if is_error:
                block["is_error"] = True
            lines.append({"type": "user", "message": {"role": "user", "content": [block]}})
    path.write_text("".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")
    return str(path)


def _bash_writer(path, op="append"):
    return ("Bash", {"command": f'python3 ~/.claude/scripts/spec-write.py {op} --spec "$spec_path" --section 5'},
            f"spec-write: {op} {path}\n", False)


def test_the_last_ok_write_wins(tmp_path):
    t = _transcript(tmp_path, [("Write", {"file_path": OTHER, "content": "x"}, "ok", False),
                               ("Edit", {"file_path": SPEC}, "ok", False)])
    assert spec_path.last_spec_write(t) == SPEC


def test_a_call_of_the_one_writer_counts_as_a_write(tmp_path):
    t = _transcript(tmp_path, [("Write", {"file_path": OTHER, "content": "x"}, "ok", False), _bash_writer(SPEC)])
    assert spec_path.last_spec_write(t) == SPEC


def test_relative_paths_resolve_against_the_record_cwd(tmp_path):
    t = _transcript(tmp_path, [("MultiEdit", {"file_path": "docs/dev/specs/spec-20261028-101010.md"}, "ok", False)])
    assert spec_path.last_spec_write(t) == SPEC


def test_what_is_not_a_spec_write(tmp_path):
    t = _transcript(tmp_path, [
        ("Write", {"file_path": SPEC, "content": "x"}, "ok", False),
        ("Write", {"file_path": OTHER, "content": "x"}, "denied", True),        # an error result
        ("Edit", {"file_path": OTHER}, None, False),                            # no result
        ("Read", {"file_path": OTHER}, "text", False),                          # a read
        ("Write", {"file_path": f"{PROJECT}/docs/dev/specs/INDEX.md"}, "ok", False),
        ("Write", {"file_path": f"{PROJECT}/docs/dev/specs/README.md"}, "ok", False),
        ("Write", {"file_path": f"{PROJECT}/docs/dev/specs/20261028-202020/views/ba.md"}, "ok", False),
        ("Bash", {"command": f"echo spec-write: append {OTHER}"}, f"spec-write: append {OTHER}\n", False),
        ("Bash", {"command": "python3 spec-write.py append --spec x --section 5"}, "refused", True),
    ])
    assert spec_path.last_spec_write(t) == SPEC


def test_no_write_or_no_transcript_is_none(tmp_path):
    assert spec_path.last_spec_write(_transcript(tmp_path, [])) is None
    assert spec_path.last_spec_write(str(tmp_path / "absent.jsonl")) is None


def _prompt_workflow(project_dir):
    spec = importlib.util.spec_from_file_location("prompt_workflow_under_test", HOOKS / "prompt-workflow.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PROJECT_DIR = Path(project_dir)
    return module


def test_decide_spec_path_explicit_first_then_the_session(tmp_path):
    pw = _prompt_workflow(PROJECT)
    pw.CURRENT_TRANSCRIPT_PATH = _transcript(tmp_path, [_bash_writer(SPEC, "create")])
    assert pw.decide_spec_path("docs/dev/specs/spec-20261028-202020.md", "sid") == OTHER
    assert pw.decide_spec_path("", "sid") == SPEC
    pw.CURRENT_TRANSCRIPT_PATH = _transcript(tmp_path, [])
    assert pw.decide_spec_path("", "sid") == ""
