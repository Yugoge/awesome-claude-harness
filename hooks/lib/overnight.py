#!/usr/bin/env python3
"""The /dev-overnight session state: its one reading, its one write, its cycle index.

The state record `<main root>/.claude/overnight-state-<sid>.json` has one producer,
the launcher's write path `write_state`: scripts/create-overnight-state.sh
publishes the record through it at launch, and scripts/break-overnight-lock.py
records the owner's /stop through it. Every reader finds it by one locator
(`locate`, `session_state_file`) and decides on it through `state_verdicts`, so
each verdict has one rule; end_time and every other time is read by
`parse_end_time`, in UTC:

  before_end      end_time is ahead (a missing or malformed end_time counts as
                  passed); no other field counts. With no human-typed /stop
                  after the session's /dev-overnight, it is the time-lock's
                  window (`window_open`);
  window_live     before_end and current_phase is not complete/completed: the
                  session-agnostic exemption of `is_overnight_active`;
  isolation_held  the isolation guarantee still binds (isolation_released_at is
                  unset and isolation_active_until, else end_time, has not
                  passed; a missing or malformed window keeps it held, so the
                  guard fails toward enforcing);
  released        isolation_released_at is set to a non-null value, which only
                  the owner's /stop does.

The git keystone and the overnight policy shim run this module as a script
(`protected-branches`) instead of parsing the record in shell, and the
/dev-overnight orchestrator binds its state file and main root through
`session-root` and reads the cycle number through `cycle-index`.

`is_overnight_active` is deliberately session-agnostic: ANY live record under a
candidate project dir counts. The "except dev-overnight" policy exempts the whole
overnight CONTEXT, the orchestrator AND the subagents it dispatches. A subagent's
hook payload carries its parent's session_id and main transcript_path, plus its
own agent_id, so the session-keyed readers (`locate`, `window_open`) reach the
orchestrator's record from either; this check takes a project dir, not a
session id. Forgery of the state file is out of scope for
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
    before_end: bool = False


def parse_end_time(value):
    """The one end_time parser: an aware UTC datetime (`Z` and offsets honoured,
    a naive value read as UTC), else None for a missing or malformed value,
    which every caller treats as passed."""
    try:
        end = datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
        return end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def _isolation_window_passed(value):
    """True iff the isolation window has passed; missing or malformed keeps it open."""
    end = parse_end_time(value) if value else None
    return end is not None and datetime.now(timezone.utc) > end


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


def _ended_by_harness_off(record):
    """True when the harness switch was turned off (/harness off) after this run started: the
    owner's off ends the run as /stop would, so after /harness on its record holds nothing."""
    started = parse_end_time(record.get('start_time')) if record.get('start_time') else None
    if started is None:
        return False
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            import harness_switch
        finally:
            sys.path.pop(0)
        off = harness_switch.last_off_at()
    except Exception:
        return False
    return off is not None and off >= started


def state_verdicts(record):
    """The one decision on an overnight-state record (see the module docstring). A run that
    started before the owner's last /harness off is over: every verdict is False."""
    if not isinstance(record, dict) or _ended_by_harness_off(record):
        return Verdicts(False, False, False, None, record if isinstance(record, dict) else {})
    end = parse_end_time(record.get('end_time'))
    before_end = end is not None and datetime.now(timezone.utc) < end
    window_live = before_end and record.get('current_phase', '') not in ('complete', 'completed')
    window = record.get('isolation_active_until') or record.get('end_time', '')
    isolation_held = (not record.get('isolation_released_at')
                      and not _isolation_window_passed(window))
    released = record.get('isolation_released_at') is not None
    return Verdicts(window_live, isolation_held, released, end, record, before_end)


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


# The session's wake (commands/dev-overnight.md Step 0): the prompt of its one recurring CronCreate,
# from launch to the session's end, which resumes a usage-limit cut with no human (P1c X8, D20).
WAKE_PROMPT = ('[awesome-claude-harness/overnight-wake-v1] Scheduled wake of this /dev-overnight session: '
               "resume what a usage limit cut (commands/restart.md's recovery), then carry on with the "
               'checklist step in progress.')


def _command_span():
    try:  # lib.overnight (hooks) or hooks.lib.overnight (tests); a script run alone never asks
        from . import command_span
    except ImportError:
        import command_span
    return command_span


def is_wake(use):
    """``use`` (a command_span.Use) is an ok recurring CronCreate of the wake's prompt."""
    return (use.name == 'CronCreate' and use.ok and use.input.get('prompt') == WAKE_PROMPT
            and use.input.get('recurring', True) is not False)


def wake_fired(prompt, transcript_path):
    """``prompt`` is the wake's text and the transcript's active span (the one the prompt
    continues) is a /dev-overnight one: never after the owner's /stop opened its own."""
    if not isinstance(prompt, str) or prompt.strip() != WAKE_PROMPT or not transcript_path:
        return False
    span = _command_span().active_span(str(transcript_path))
    return span is not None and span.command == 'dev-overnight'


def open_wakes(transcript_path):
    """The job ids of the transcript's wake CronCreate calls (their recorded results') that no
    later CronDelete names, whatever span is active; read through command_span."""
    spans = _command_span()
    found = []
    for use in spans.transcript_span(transcript_path).uses('CronCreate', 'CronDelete'):
        if use.name == 'CronDelete':
            found = [job for job in found if job != use.input.get('id')]
        elif is_wake(use):
            job = spans.recorded_result(transcript_path, use).get('id')
            found += [job] if isinstance(job, str) and job else []
    return found


def _own_record(session_id, root):
    """The record in `root`'s state file of `session_id` whose own session_id is
    `session_id` (no scan of other sessions' files), else None."""
    if not isinstance(session_id, str) or not session_id:
        return None
    record = read_state(state_path(session_id, root))
    return record if record is not None and record.get('session_id') == session_id else None


def session_state(session_id, project_dir=None):
    """One session's record (`_own_record`), else None. With no project_dir the
    record is found by `locate`, which selects through `_own_record`, never this
    function: no call here cycles back, so the artifact check's static half
    follows a write through the located path to `write_state` in any order."""
    return locate(session_id)[1] if project_dir is None else _own_record(session_id, project_dir)


def _git(where, *args):
    """git's one-line answer in directory `where`, else None."""
    try:
        out = subprocess.run(['git', '-C', str(where), *args], capture_output=True, text=True, timeout=5)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return (out.stdout.strip() or None) if out.returncode == 0 else None


def _roots(start):
    """Where a session's record may sit, seen from `start`: the start itself,
    the main root of its repository (the parent of the git common dir, so a
    linked worktree reaches the main checkout) and, for a fresh clone checkout
    (its own .git, a local clone of the main repository, wherever
    OVERNIGHT_FRESH_CLONE_ROOT put it), the main root of its origin."""
    yield start
    common = _git(start, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    if common is None:
        return
    yield Path(common).parent
    origin = _git(start, 'config', '--get', 'remote.origin.url')
    if origin and os.path.isabs(origin):
        common = _git(origin, 'rev-parse', '--path-format=absolute', '--git-common-dir')
        if common is not None:
            yield Path(common).parent


def session_state_file(session_id, starts):
    """The one locator: the state file of `session_id` and its record at
    <main root>/.claude/, reached from each start in turn (`_roots`).
    Selection is the record's own (`_own_record`: the session-keyed file
    name, then its session_id field). (None, None) when no start reaches one."""
    for start in starts:
        try:
            d = Path(start).resolve(strict=True) if start else None
        except (OSError, RuntimeError):
            continue
        for root in _roots(d) if d else ():
            record = _own_record(session_id, root)
            if record is not None:
                return state_path(session_id, root).resolve(), record
    return None, None


def locate(session_id, payload=None):
    """(state file, record) of `session_id` from CLAUDE_PROJECT_DIR, then the
    hook payload's cwd (else the process cwd); (None, None) when none."""
    try:
        cwd = (payload.get('cwd') if isinstance(payload, dict) else None) or os.getcwd()
    except OSError:  # the process cwd was removed
        cwd = None
    return session_state_file(session_id, (os.environ.get('CLAUDE_PROJECT_DIR'), cwd))


def window_open(payload):
    """The time-lock's window for a hook payload: the payload's session owns a
    record whose end_time is ahead (`before_end`) and no human-typed /stop
    follows its /dev-overnight (command_span.timelock_released, the one
    transcript reader's rule, which stop_contract re-exports). No state field
    (status, terminal_status, current_phase) and no token decides it."""
    try:
        _sf, record = locate(payload.get('session_id'), payload)
        if record is None or not state_verdicts(record).before_end:
            return False
        return not _command_span().timelock_released(payload.get('transcript_path'))
    except Exception:
        return False


def closeout_gaps(state, working_root):
    """What the session's closeout lacks on disk, one fact per gap: a PM
    retrospective (retro-report-cycle*.json under
    <working root>/docs/dev/overnight/<sid>/) and Step 21's overnight summary
    (overnight-summary-*.md under <working root>/docs/dev/) written at or after
    start_time (any, when start_time is unreadable) and not empty: the summary
    is opened, so its read is the Stop's own. No tree or checkpoint term."""
    state = state if isinstance(state, dict) else {}
    docs = Path(working_root) / 'docs' / 'dev'
    retro = docs / 'overnight' / str(state.get('session_id') or 'unknown')
    start = parse_end_time(state.get('start_time'))
    since = start.timestamp() if start else float('-inf')

    def written(path):
        try:
            return path.stat().st_mtime >= since and bool(path.read_text(errors='replace').strip())
        except (OSError, ValueError):
            return False

    gaps = []
    if not any(retro.glob('retro-report-cycle*.json')):
        gaps.append(f'{retro}/retro-report-cycle*.json: no PM retrospective report')
    if not any(written(p) for p in docs.glob('overnight-summary-*.md')):
        gaps.append(f'{docs}/overnight-summary-*.md: no summary written since start_time '
                    f'{state.get("start_time")}')
    return gaps


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


def cycle_index(state, written=()):
    """The number of the cycle in progress, read from the session's directory.

    A cycle ends with its PM retrospective (Step 20 writes
    retro-report-cycle<N>.json there), so the cycle in progress is the first
    one whose retrospective is not on disk. No state field counts cycles.

    ``written``: the files a dispatch declares, read as not on disk yet, so the
    answer is the cycle that dispatch runs in, at its dispatch (G1) and its
    collection (G3): the PM retrospective's report, left by it or by an earlier
    attempt of it, does not move that dispatch into the next cycle.
    """
    try:
        base = session_dir(state)
        before = {os.path.realpath(str(p)) for p in written}
        n = 1
        while (base / f'retro-report-cycle{n}.json').is_file() and \
                os.path.realpath(str(base / f'retro-report-cycle{n}.json')) not in before:
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
      session-root SID START...    this session's state file and the main root its
                                   record names (a directory), one per line, found
                                   by the locator from each START in turn; exit 1
                                   with the reason when there is none
    """
    if len(argv) >= 2 and argv[0] == 'session-root':
        sf, record = session_state_file(argv[1], argv[2:])
        if sf is None:
            print(f'ERROR: no readable overnight-state file for session {argv[1]} found from '
                  + ' or '.join(a or '<unset>' for a in argv[2:]), file=sys.stderr)
            return 1
        root = record.get('main_root')
        if not isinstance(root, str) or not root or not Path(root).is_dir():
            print(f"ERROR: {sf} records no usable main_root: '{root or '<empty>'}'", file=sys.stderr)
            return 1
        print(sf)
        print(Path(root).resolve())
        return 0
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
