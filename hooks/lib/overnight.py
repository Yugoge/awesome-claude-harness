#!/usr/bin/env python3
"""The /dev-overnight session state: its one reading, its one write, its cycle index.

The state record `<project>/.claude/overnight-state-<sid>.json` has one producer,
the launcher's write path `write_state`: scripts/create-overnight-state.sh
publishes the record through it at launch, and scripts/break-overnight-lock.py
writes the owner's /stop through it. Every reader that decides on the record
calls `state_verdicts` and acts on what it returns, so each verdict has one rule:

  window_live     the session's window is open (current_phase is not
                  complete/completed and end_time has not passed; a missing or
                  malformed end_time counts as passed, so a half-written record
                  is never a live session);
  isolation_held  the isolation guarantee still binds (isolation_released_at is
                  unset and isolation_active_until, else end_time, has not
                  passed; a missing or malformed window keeps it held, so the
                  guard fails toward enforcing);
  released        isolation_released_at is set to a non-null value, which only
                  the owner's /stop does.

The git keystone and the overnight policy shim run this module as a script
(`protected-branches`) instead of parsing the record in shell, and the
/dev-overnight orchestrator reads the cycle number through `cycle-index`.

`is_overnight_active` is deliberately session-agnostic: ANY live record under a
candidate project dir counts. The "except dev-overnight" policy exempts the whole
overnight CONTEXT, the orchestrator AND the subagents it dispatches, and those
subagents carry DIFFERENT session_ids than the orchestrator that wrote the state
file (see hooks/lib/allowlist.py). Forgery of the state file is out of scope for
this guardrail: writes to .claude/overnight-state-*.json are blocked by
pretool-overnight-hook-guard.py, and the /do and /allow escape hatches exist for
everything else.

Stdlib-only, so the shell callers can run it with `python3 -I`; readers never
raise (every probe fails closed).
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional


class Verdicts(NamedTuple):
    """What a record says, decided once. `record` holds the fields callers act on."""

    window_live: bool
    isolation_held: bool
    released: bool
    end_time: Optional[datetime]
    record: dict


def _parse_end_time(value):
    """The window's end_time as a datetime (naive stays naive-as-local), else None."""
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError):
        return None


def _passed(end):
    if end.tzinfo is None:
        return datetime.now() > end
    return datetime.now(timezone.utc) > end


def _end_time_passed(end_str):
    """True iff end_str (ISO-8601) is in the past, or is missing/unparseable."""
    end = _parse_end_time(end_str)
    return True if end is None else _passed(end)


def _isolation_window_passed(value):
    """True iff the isolation window has passed; missing or malformed keeps it open."""
    if not isinstance(value, str) or not value:
        return False
    try:
        end = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return False
    return _passed(end)


def read_state(sf):
    """The record in state file `sf`, or None when it is empty or not a JSON object."""
    try:
        path = Path(sf)
        if path.stat().st_size == 0:
            return None
        record = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return None
    return record if isinstance(record, dict) else None


def state_verdicts(record):
    """The one decision on an overnight-state record (see the module docstring)."""
    if not isinstance(record, dict):
        return Verdicts(False, False, False, None, {})
    window_live = (record.get('current_phase', '') not in ('complete', 'completed')
                   and not _end_time_passed(record.get('end_time', '')))
    window = record.get('isolation_active_until') or record.get('end_time', '')
    isolation_held = (not record.get('isolation_released_at')
                      and not _isolation_window_passed(window))
    released = record.get('isolation_released_at') is not None
    return Verdicts(window_live, isolation_held, released,
                    _parse_end_time(record.get('end_time', '')), record)


def write_state(path, record):
    """The record's one write: the whole record, published by rename.

    The temporary name cannot match `overnight-state-*.json`, so no reader ever
    sees a partial record.
    """
    path = Path(path)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def state_path(session_id, project_dir=None):
    """Where the launcher writes one session's record."""
    root = Path(project_dir or os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd())
    return root / '.claude' / f'overnight-state-{session_id}.json'


def session_state(session_id, project_dir=None):
    """One session's record: its state file whose own session_id is
    `session_id` (no scan of other sessions' files), else None."""
    if not isinstance(session_id, str) or not session_id:
        return None
    record = read_state(state_path(session_id, project_dir))
    if record is None or record.get('session_id') != session_id:
        return None
    return record


def working_root(state):
    """Where the session's producers write: the record's worktree_path."""
    wt = state.get('worktree_path') if isinstance(state, dict) else None
    if isinstance(wt, str) and wt:
        return Path(wt)
    return Path(os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd())


def session_dir(state):
    """`<working root>/docs/dev/overnight/<sid>`, the session's cycle directories."""
    sid = state.get('session_id') if isinstance(state, dict) else None
    sid = sid if isinstance(sid, str) and sid else 'unknown'
    return working_root(state) / 'docs' / 'dev' / 'overnight' / sid


def cycle_index(state):
    """The number of the cycle in progress, read from the session's directory.

    A cycle ends with its PM retrospective (Step 20 writes
    retro-report-cycle<N>.json there), so the cycle in progress is the first
    one whose retrospective is not on disk. No state field counts cycles.
    """
    try:
        base = session_dir(state)
        n = 1
        while (base / f'retro-report-cycle{n}.json').is_file():
            n += 1
        return n
    except (OSError, ValueError, TypeError):
        return 1


def candidate_project_dirs(project_dir=None):
    """Ordered, de-duplicated dirs whose .claude/ may hold the state file.

    Precedence: explicit project_dir arg → $CLAUDE_PROJECT_DIR → cwd →
    git-toplevel. The state file lives in the MAIN repo's .claude/, so a subagent
    running inside a worktree still resolves it via $CLAUDE_PROJECT_DIR (set by
    the harness to the main repo).
    """
    dirs = []
    for d in (project_dir, os.environ.get('CLAUDE_PROJECT_DIR')):
        if d and d not in dirs:
            dirs.append(d)
    try:
        cwd = os.getcwd()
        if cwd and cwd not in dirs:
            dirs.append(cwd)
    except Exception:
        pass
    try:
        top = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, timeout=3,
        )
        if top.returncode == 0:
            t = (top.stdout or '').strip()
            if t and t not in dirs:
                dirs.append(t)
    except Exception:
        pass
    return dirs


def is_overnight_active(project_dir=None):
    """True iff a record whose window is live exists under any candidate project
    dir's .claude/. Fails closed (returns False) on any error."""
    try:
        for d in candidate_project_dirs(project_dir):
            try:
                state_files = Path(d).glob('.claude/overnight-state-*.json')
            except Exception:
                continue
            for sf in state_files:
                record = read_state(sf)
                if record is not None and state_verdicts(record).window_live:
                    return True
        return False
    except Exception:
        return False


def _main(argv):
    """Script entry for callers that cannot import this module.

      protected-branches FILE...   the protected_branch of every given record
                                   that is not released, one per line
      cycle-index FILE             the cycle in progress for the record in FILE
      write-state FILE SOURCE      publish the record in SOURCE as FILE
    """
    if len(argv) >= 2 and argv[0] == 'protected-branches':
        for sf in argv[1:]:
            record = read_state(sf)
            if record is None or state_verdicts(record).released:
                continue
            name = record.get('protected_branch')
            if isinstance(name, str) and name:
                print(name)
        return 0
    if len(argv) == 2 and argv[0] == 'cycle-index':
        print(cycle_index(read_state(argv[1]) or {}))
        return 0
    if len(argv) == 3 and argv[0] == 'write-state':
        record = read_state(argv[2])
        if record is None:
            print(f'write-state: {argv[2]} holds no JSON object', file=sys.stderr)
            return 1
        try:
            write_state(argv[1], record)
        except OSError as exc:
            print(f'write-state: {exc}', file=sys.stderr)
            return 1
        return 0
    print(_main.__doc__, file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(_main(sys.argv[1:]))
