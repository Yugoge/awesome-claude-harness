"""Frozen reference for the differential test of ``completed_codex_subagents``.

NOT PRODUCTION CODE. This is a verbatim copy of ``completed_codex_subagents`` from
hooks/pretool-workflow-gate.py as it was at commit cc22f78, before that function was
split into the ``_CodexStepWindow`` helpers. tests/differential/
test_completed_codex_subagents_differential.py runs this copy and the live function on
the same generated inputs and requires identical results, so the refactor is shown to
change no behaviour. Do not edit the function below; it is the old behaviour by
definition. The helpers it calls were not changed by the refactor and are taken from
the live hook, loaded by path as the hook's own tests load it.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_HOOK_PATH = Path(__file__).resolve().parents[2] / "hooks" / "pretool-workflow-gate.py"
_SPEC = importlib.util.spec_from_file_location("pretool_workflow_gate_legacy_helpers", _HOOK_PATH)
assert _SPEC and _SPEC.loader
_LIVE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_LIVE)

_transcript_path = _LIVE._transcript_path
_event_epoch_ms = _LIVE._event_epoch_ms
_spawn_task_name = _LIVE._spawn_task_name
_structured_completed_paths = _LIVE._structured_completed_paths
_final_agent_text = _LIVE._final_agent_text
_terminal_operational_outcome = _LIVE._terminal_operational_outcome


# --- verbatim from hooks/pretool-workflow-gate.py at cc22f78 (lines 630-806) ---
def completed_codex_subagents(
    data: dict,
    session_id: str,
    started_after_ms: int,
    *,
    completed_before_ms: int | None = None,
    completed_before_line: int | None = None,
    binding: dict | None = None,
) -> list[dict]:
    """Return closed spawn/start/terminal/status records for one step window."""
    path = _transcript_path(data, session_id)
    if path is None:
        return []
    events = []
    try:
        for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            event = json.loads(line)
            if isinstance(event, dict):
                events.append((line_no, event))
    except (OSError, json.JSONDecodeError):
        return []

    spawns: dict[str, dict] = {}
    started_by_path: dict[str, dict] = {}
    identity_by_call: dict[str, tuple] = {}
    identity_by_thread: dict[str, tuple] = {}
    completed_by_identity: dict[tuple, dict] = {}
    list_agent_calls: set[str] = set()
    structured_success_by_path: dict[str, tuple[int, int]] = {}
    for line_no, event in events:
        if completed_before_line is not None and line_no >= completed_before_line:
            break
        payload = event.get('payload')
        if not isinstance(payload, dict):
            continue
        event_ms = _event_epoch_ms(event)
        if event.get('type') == 'response_item' and payload.get('type') == 'function_call':
            if payload.get('namespace') == 'collaboration' and payload.get('name') == 'list_agents':
                call_id = payload.get('call_id')
                if isinstance(call_id, str) and call_id:
                    list_agent_calls.add(call_id)
                continue
            if payload.get('namespace') == 'collaboration' and payload.get('name') == 'spawn_agent':
                call_id = payload.get('call_id')
                task_name = _spawn_task_name(payload)
                if (
                    isinstance(call_id, str)
                    and call_id
                    and task_name is not None
                    and event_ms is not None
                    and event_ms >= started_after_ms
                ):
                    spawn = {
                        'spawned_at_ms': event_ms,
                        'task_name': task_name,
                        'spawn_line': line_no,
                    }
                    existing = spawns.get(call_id)
                    if existing is not None and existing['task_name'] != task_name:
                        return []
                    if existing is None:
                        spawns[call_id] = spawn
            continue
        if event.get('type') == 'response_item' and payload.get('type') == 'function_call_output':
            call_id = payload.get('call_id')
            if call_id not in list_agent_calls or event_ms is None:
                continue
            if completed_before_ms is not None and event_ms >= completed_before_ms:
                continue
            for agent_path in _structured_completed_paths(payload.get('output')):
                prior = structured_success_by_path.get(agent_path)
                if prior is None or (event_ms, line_no) >= prior:
                    structured_success_by_path[agent_path] = (event_ms, line_no)
            continue
        if event.get('type') == 'event_msg' and payload.get('type') == 'sub_agent_activity':
            call_id = payload.get('event_id')
            agent_path = payload.get('agent_path')
            agent_thread_id = payload.get('agent_thread_id')
            occurred_ms = payload.get('occurred_at_ms')
            spawn = spawns.get(call_id)
            if (
                payload.get('kind') == 'started'
                and isinstance(call_id, str)
                and isinstance(spawn, dict)
                and isinstance(agent_path, str)
                and agent_path.rsplit('/', 1)[-1] == spawn['task_name']
                and isinstance(agent_thread_id, str)
                and bool(agent_thread_id.strip())
                and type(occurred_ms) is int
                and occurred_ms >= started_after_ms
                and occurred_ms >= spawn['spawned_at_ms']
            ):
                identity = (
                    call_id,
                    agent_thread_id,
                    agent_path,
                    spawn['task_name'],
                )
                if (
                    call_id in identity_by_call
                    and identity_by_call[call_id] != identity
                ):
                    return []
                if (
                    agent_thread_id in identity_by_thread
                    and identity_by_thread[agent_thread_id] != identity
                ):
                    return []
                if (
                    agent_path in started_by_path
                    and (
                        started_by_path[agent_path]['call_id'],
                        started_by_path[agent_path]['agent_thread_id'],
                        started_by_path[agent_path]['agent_path'],
                        started_by_path[agent_path]['task_name'],
                    ) != identity
                ):
                    return []
                record = {
                    'call_id': call_id,
                    'agent_path': agent_path,
                    'agent_thread_id': agent_thread_id,
                    'task_name': spawn['task_name'],
                    'spawned_at_ms': spawn['spawned_at_ms'],
                    'started_at_ms': occurred_ms,
                    'spawn_line': spawn['spawn_line'],
                    'started_line': line_no,
                }
                identity_by_call[call_id] = identity
                identity_by_thread[agent_thread_id] = identity
                started_by_path.setdefault(agent_path, record)
            continue
        if event.get('type') != 'response_item' or payload.get('type') != 'agent_message':
            continue
        author = payload.get('author')
        final_text = _final_agent_text(payload)
        if (
            not isinstance(author, str)
            or author not in started_by_path
            or final_text is None
        ):
            continue
        started = started_by_path[author]
        if event_ms is None or event_ms < started['started_at_ms']:
            continue
        identity = (
            started['call_id'],
            started['agent_thread_id'],
            started['agent_path'],
            started['task_name'],
        )
        terminal = {
            **started,
            'terminal_at_ms': event_ms,
            'terminal_line': line_no,
            '_operational_outcome': _terminal_operational_outcome(final_text),
        }
        existing = completed_by_identity.get(identity)
        if existing is None or event_ms >= existing['terminal_at_ms']:
            completed_by_identity[identity] = terminal
    completed = []
    for record in completed_by_identity.values():
        if record.pop('_operational_outcome', None) is not None:
            continue
        success = structured_success_by_path.get(record['agent_path'])
        if success is None:
            continue
        completion_ms, completion_line = success
        if completion_ms < record['terminal_at_ms'] or completion_line < record['terminal_line']:
            continue
        record['completion_observed_at_ms'] = completion_ms
        record['completion_observed_line'] = completion_line
        record['completion_status'] = 'completed'
        if binding is not None:
            record.update(binding)
        completed.append(record)
    return completed
