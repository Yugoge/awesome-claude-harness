#!/usr/bin/env python3
"""Notices for skipped regeneration: text, per-audience dedupe state, hook JSON output.

A skipped README, INDEX or CLAUDE.md section is a deliberate outcome (regeneration is opt-in
through the AUTO markers, and a file the classifier refuses is never guessed at), but a
silent skip looks exactly like a hook that did nothing, so every skip is reported to the
caller once per audience and artifact state.
"""

import hashlib
import json
import os
import re
import sys
import tempfile

from .regions import (
    INDEX_MARKER_ID, README_MARKER_ID, ArtifactKind, RegenRecord, RegenStatus, RegionShape,
    marker_close, marker_open,
)

HOOK_EVENT_NAME = 'PostToolUse'
NOTIFY_STATUSES = (
    RegenStatus.SKIPPED_NO_OPENING_MARKER,
    RegenStatus.SKIPPED_NO_CLOSING_MARKER,
    RegenStatus.SKIPPED_MALFORMED_MARKERS,
)
# The documented cap for hook output strings is 10,000 characters; a notice is a pointer,
# not a report, so it stays far below it.
MAX_NOTICE_CHARS = 2000
TRUNCATION_SUFFIX = '...'
# The relay hook (userprompt-doc-sync-check.py) keeps its own copy of this prefix because it
# must not import doc_sync; a test pins the two together.
INDEX_NOTICE_PREFIX = 'doc-sync: INDEX not regenerated'
# Opens every hook_ledger failure line, so an operator can find them by one string.
LEDGER_FAILURE_PREFIX = 'doc-sync ledger: side-effect record not written '
# session_id becomes a path component of the state directory, so it gets the same
# charset guard as hooks/session-scratch-init.sh (no separators, no traversal).
SESSION_ID_PATTERN = re.compile(r'[A-Za-z0-9_.-]{1,128}')
# Written by hooks/session-scratch-init.sh; only a directory that carries it is a
# registered session directory that hooks/sessionend-scratch-sweep.sh removes at SessionEnd.
OWNER_FILE = '.owner'
STATE_FILE_TEMPLATE = 'doc-sync-notices-{audience}.json'
AGENT_AUDIENCE_HASH_CHARS = 16
# Test seam, never set in production: tempfile.gettempdir() raises under RLIMIT_FSIZE=0
# (it probes each candidate by writing), which would make the state-write failure path
# unreachable from a test because directory resolution fails first.
STATE_ROOT_ENV = 'CLAUDE_DOC_SYNC_STATE_ROOT'

# Word for the artifact inside a sentence, and the label that opens the notice line.
_ARTIFACT_WORD = {
    ArtifactKind.README: 'README',
    ArtifactKind.INDEX: 'INDEX',
    ArtifactKind.CLAUDE_MD_SECTION: 'section',
}
_ARTIFACT_LABEL = {
    ArtifactKind.README: 'README',
    ArtifactKind.INDEX: 'INDEX',
    ArtifactKind.CLAUDE_MD_SECTION: 'CLAUDE.md section',
}
# Reason and action per malformed shape; {o}, {c} are the marker lines, {line} the fence line.
_MALFORMED_PARTS = {
    RegionShape.DUPLICATE_OPENING: (
        'the opening marker {o} appears more than once',
        'keep exactly one {o} and one {c} pair and remove the extra opening marker'),
    RegionShape.DUPLICATE_CLOSING: (
        'the closing marker {c} appears more than once',
        'keep exactly one {o} and one {c} pair and remove the extra closing marker'),
    RegionShape.MULTIPLE_REGIONS: (
        'the marked region appears more than once',
        'keep exactly one {o} and one {c} pair'),
    RegionShape.NESTED_REGIONS: (
        'marked regions are nested inside each other',
        'remove the inner opening marker {o}'),
    RegionShape.FOREIGN_MARKER_INSIDE: (
        'a marker of another section lies between {o} and {c}',
        'move the other section\'s marker out of the region'),
    RegionShape.NEAR_MISS_MARKER: (
        'a line looks like a marker but is not spelled exactly',
        'write the marker exactly as {o} (closing {c}) on a line of its own'),
    RegionShape.UNCLOSED_FENCE: (
        'a code fence that is never closed hides a marker line',
        'close the code fence that starts at line {line}'),
    RegionShape.BODY_CONTAINS_MARKER: (
        'nothing was written because the generated content would contain marker text',
        'remove the marker-like line from the description of a listed file'),
    RegionShape.BODY_BREAKS_REGION: (
        'nothing was written because the generated content would break the region',
        'remove marker-like lines or unbalanced code fences from the descriptions of listed files'),
}


def _marker_id_of(record):
    if record.kind is ArtifactKind.README:
        return README_MARKER_ID
    if record.kind is ArtifactKind.INDEX:
        return INDEX_MARKER_ID
    return record.marker_id


def _reason_and_action(record):
    """(reason, action) sentences for one skip; raises on a record it cannot describe."""
    word = _ARTIFACT_WORD[record.kind]
    open_marker = marker_open(_marker_id_of(record))
    close_marker = marker_close(_marker_id_of(record))
    section = 'section' if record.kind is ArtifactKind.CLAUDE_MD_SECTION else 'stats section'
    if record.status is RegenStatus.SKIPPED_NO_OPENING_MARKER:
        if record.kind is ArtifactKind.CLAUDE_MD_SECTION:
            return (f'closing marker {close_marker} found without its opening marker {open_marker}, '
                    'so the section was left untouched',
                    f'add {open_marker} before {close_marker}, or remove {close_marker}')
        return (f'opening marker {open_marker} not found, so the {word} is treated as '
                'hand-written and left untouched',
                f'add {open_marker} and {close_marker} to let doc-sync manage its '
                f'stats section, or ignore this notice if the {word} is meant to stay hand-written')
    if record.status is RegenStatus.SKIPPED_NO_CLOSING_MARKER:
        return (f'closing marker missing or placed before the opening marker, so the {word} was '
                'left untouched',
                f'place {close_marker} after {open_marker} so the {section} can be regenerated')
    reason, action = _MALFORMED_PARTS[record.shape]
    fields = {'o': open_marker, 'c': close_marker, 'line': record.detail}
    if record.shape is RegionShape.UNCLOSED_FENCE and not record.detail:
        action = 'close the code fence that hides the marker'
    return (f'shape {record.shape.value}: {reason.format(**fields)}',
            f'{action.format(**fields)}; the {word} was left untouched')


def _entry_text(record):
    reason, action = _reason_and_action(record)
    label = _ARTIFACT_LABEL[record.kind]
    if record.kind is ArtifactKind.CLAUDE_MD_SECTION:
        where = f'CLAUDE.md: {record.path} section: {record.marker_id}'
    else:
        where = f'{label}: {record.path}'
    return f'doc-sync: {label} not regenerated ({record.status.value}). Reason: {reason}. Action: {action}. {where}'


def _normalize(item):
    """A record for the notifiable skips, else None. Legacy (path, status) pairs are READMEs."""
    if isinstance(item, RegenRecord):
        record = item
    elif isinstance(item, tuple) and len(item) == 2:
        record = RegenRecord(ArtifactKind.README, item[0], item[1])
    else:
        return None
    status = RegenStatus(record.status)
    if status not in NOTIFY_STATUSES:
        return None
    kind = ArtifactKind(record.kind)
    marker_id = record.marker_id
    if kind is ArtifactKind.CLAUDE_MD_SECTION and not (isinstance(marker_id, str) and marker_id):
        return None
    shape = RegionShape(record.shape) if record.shape is not None else None
    if status is RegenStatus.SKIPPED_MALFORMED_MARKERS and shape not in _MALFORMED_PARTS:
        return None
    return RegenRecord(kind, os.path.realpath(record.path), status, marker_id, shape, record.detail)


def notifiable(results):
    """Records that deserve a notice: one per README, INDEX, or CLAUDE.md section, resolved path.

    A record that cannot be understood is dropped on its own; it never hides the others.
    """
    try:
        items = list(results)
    except Exception:
        return []
    unique = {}
    for item in items:
        try:
            record = _normalize(item)
        except Exception:
            continue
        if record is not None:
            unique.setdefault((record.kind, record.path, record.marker_id), record)
    return list(unique.values())


def _overflow_tail(count):
    return f'doc-sync: {count} more notice(s) not shown here; they are reported again after the next edit'


def render_notices(entries, limit=None):
    """(entries printed, notice text): whole entries in order, at most `limit` chars.

    `limit` defaults to MAX_NOTICE_CHARS. It is a parameter only so the caller can
    render skip notices into whatever budget the recorder-failure lines left, keeping
    the combined body inside the ONE capped output object.

    The first entry is always printed (cut with the suffix only if it alone exceeds the cap).
    Entries that do not fit are counted in a tail line that itself sits inside the cap, and
    are NOT part of the returned printed list, so the caller records only what was shown.
    """
    cap = MAX_NOTICE_CHARS if limit is None else limit
    texts = []
    describable = []
    for record in entries:
        try:
            texts.append(_entry_text(record))
            describable.append(record)
        except Exception:
            continue
    if not texts:
        return [], ''
    total = len(texts)
    for shown in range(total, 0, -1):
        text = '\n'.join(texts[:shown])
        if shown < total:
            text += '\n' + _overflow_tail(total - shown)
        if len(text) <= cap:
            return describable[:shown], text
    first = texts[0]
    if len(first) > cap:
        first = first[:max(cap - len(TRUNCATION_SUFFIX), 0)] + TRUNCATION_SUFFIX
    return describable[:1], first


def build_notice_text(entries):
    return render_notices(entries)[1]


def _ledger_failure_text(descriptor):
    """One operator-findable line for one hook_ledger failure descriptor."""
    where = descriptor.get('path')
    tail = f' Path: {where}' if where else ''
    return (f"{LEDGER_FAILURE_PREFIX}({descriptor.get('class')}). "
            f"Reason: {descriptor.get('reason')}.{tail}")


def _ledger_state_key(descriptor):
    """`ledger|<class>|<path>` -- the dedupe identity of one recorder failure."""
    return f"ledger|{descriptor.get('class')}|{descriptor.get('path') or '-'}"


def _ledger_digest(descriptor):
    """Digest of the failure's own content, so a MATERIALLY different failure re-notifies.

    A recorder failure has no artifact file to hash, so it stands in for itself: the
    same class, path and reason is the same failure and is reported once per audience,
    exactly like a skip notice. A hook that fires on every edit in the harness must not
    repeat one line forever -- that is the unbounded-log shape this channel must not grow.
    """
    material = f"{descriptor.get('class')}|{descriptor.get('path')}|{descriptor.get('reason')}"
    return hashlib.sha256(material.encode('utf-8', 'replace')).hexdigest()


def render_ledger_failures(descriptors):
    """The usable subset of hook_ledger.record_landed_files()'s failure descriptors.

    These are the six FAILURE no-op classes only. The four legitimate no-ops never
    produce a descriptor, so nothing here can report an ordinary non-dev edit --
    which is the majority case, and reporting it would bury the real failures.

    A descriptor that cannot be understood is dropped on its own; it never hides the
    others, mirroring notifiable()'s own per-item tolerance.
    """
    try:
        items = list(descriptors or [])
    except Exception:
        return []
    usable = []
    for descriptor in items:
        try:
            if isinstance(descriptor, dict) and descriptor.get('class'):
                usable.append(descriptor)
        except Exception:
            continue
    return usable


def _ledger_overflow_tail(count):
    return (f'doc-sync ledger: {count} more recorder failure(s) not shown here; '
            'they are reported again after the next edit')


def render_ledger_body(failures, limit=None):
    """(failures rendered IN FULL, body text): whole lines in order, at most `limit` chars.

    The failure half's counterpart to render_notices, and it returns what it actually
    showed for the same reason: the caller records ONLY the returned failures as seen,
    so one withheld by the cap is reported again after the next edit instead of being
    marked delivered and suppressed forever. Because the shown ones ARE marked, the
    next edit suppresses them and the withheld ones move to the front, so a body over
    the cap drains across successive edits rather than starving its own tail.

    A withheld failure is COUNTED in a tail line rather than cut mid-sentence: this
    channel must never report that something was dropped without reporting how much,
    which is the rule hook_ledger's own descriptor cap already follows. A single line
    longer than the whole cap is the one case that must still be cut, and it is then
    reported as shown to nobody, so it too returns on the next edit.
    """
    cap = MAX_NOTICE_CHARS if limit is None else limit
    texts = []
    describable = []
    for failure in failures:
        try:
            texts.append(_ledger_failure_text(failure))
            describable.append(failure)
        except Exception:
            continue
    if not texts:
        return [], ''
    total = len(texts)
    for shown in range(total, 0, -1):
        text = '\n'.join(texts[:shown])
        if shown < total:
            text += '\n' + _ledger_overflow_tail(total - shown)
        if len(text) <= cap:
            return describable[:shown], text
    tail = _ledger_overflow_tail(total)
    room = cap - len(tail) - 1
    if room > len(TRUNCATION_SUFFIX):
        return [], texts[0][:room - len(TRUNCATION_SUFFIX)] + TRUNCATION_SUFFIX + '\n' + tail
    return [], tail[:cap]


def build_hook_output(text):
    """The one JSON object the harness reads from a PostToolUse hook's stdout.

    additionalContext reaches the agent, systemMessage the user; both carry the same text.
    """
    return {
        'systemMessage': text,
        'hookSpecificOutput': {'hookEventName': HOOK_EVENT_NAME, 'additionalContext': text},
    }


def audience_of(payload):
    """'main' for the top-level session, a stable per-subagent token otherwise.

    A subagent never saw the notice its parent received, so the two must not share state.
    """
    agent_id = payload.get('agent_id')
    if not agent_id:
        return 'main'
    digest = hashlib.sha256(str(agent_id).encode('utf-8', 'replace')).hexdigest()
    return 'agent-' + digest[:AGENT_AUDIENCE_HASH_CHARS]


def _state_root():
    override = os.environ.get(STATE_ROOT_ENV, '')
    if override and os.path.isabs(override):
        return override
    return tempfile.gettempdir()


def state_path_for(payload):
    """State file of this audience, or None when dedupe must stay off (notify every time).

    Dedupe needs a session directory that already exists and is registered by
    session-scratch-init.sh. The hook never creates it: a directory without an .owner
    record cannot be classified by the SessionEnd sweep and would linger for days.
    """
    try:
        session_id = payload.get('session_id')
        if not isinstance(session_id, str) or session_id in ('.', '..'):
            return None
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            return None
        session_dir = os.path.join(_state_root(), session_id)
        if os.path.islink(session_dir) or not os.path.isdir(session_dir):
            return None
        if not os.path.isfile(os.path.join(session_dir, OWNER_FILE)):
            return None
        return os.path.join(session_dir, STATE_FILE_TEMPLATE.format(audience=audience_of(payload)))
    except Exception:
        # Includes a state root that cannot be resolved: no session directory, notify.
        return None


def read_state(path):
    """{state key: artifact digest}; anything unreadable or malformed counts as empty.

    Catches Exception, not only OSError and ValueError: a deeply nested file raises
    RecursionError, and any failure to read the state must mean "notify", never silence.
    """
    try:
        with open(path, encoding='utf-8') as handle:
            state = json.load(handle)
    except Exception:
        return {}
    return state if isinstance(state, dict) else {}


def write_state(path, state):
    """Atomically replace the state file; raises OSError when the write fails."""
    descriptor, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(path), prefix='.doc-sync-notices-', suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(state, handle)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _state_key(path, status, marker_id=None):
    """`<realpath>|<STATUS>`; a CLAUDE.md section appends `|<marker id>` (one file, many sections)."""
    key = f'{path}|{status.value}'
    return key if marker_id is None else f'{key}|{marker_id}'


def _record_key(record):
    marker_id = record.marker_id if record.kind is ArtifactKind.CLAUDE_MD_SECTION else None
    return _state_key(record.path, record.status, marker_id)


def _readme_digest(readme_path):
    """SHA-256 of the artifact file, or None when it cannot be hashed (which always notifies)."""
    try:
        with open(readme_path, 'rb') as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except Exception:
        return None


def _detach_stdout():
    """Point fd 1 at devnull after a failed write.

    The text that could not be written stays in the stdout buffer and is flushed again at
    interpreter exit; on a broken pipe that second flush turns the exit code into 120.
    """
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull, sys.stdout.fileno())
        finally:
            os.close(devnull)
    except Exception:
        pass


def emit_post_tool_notice(results, payload, ledger_failures=None):
    """Print ONE PostToolUse JSON object covering skipped artifacts and recorder failures.

    Never raises and never changes the exit code of the edit that triggered the hook.
    Every state problem (missing, corrupt, unreadable, unwritable) resolves to "notify":
    a lost notice is worse than a repeated one. Only entries that were printed are recorded
    as seen, and only after the print succeeded, so a failed print (or an entry cut by the
    length cap) is retried on the next edit.

    `ledger_failures` are hook_ledger.record_landed_files()'s structured descriptors. They
    share this ONE object rather than printing a second one: the PostToolUse protocol reads
    a single JSON object from stdout, so a second print would corrupt the first.

    Recorder failures LEAD the body, because a failure is the half that says something
    went wrong; a skip notice describes a deliberate, stable outcome that will be
    reported again after the next edit, so it is the safer half to drop when the cap
    binds. Both halves share the SAME per-audience dedupe state, keyed for a failure on
    its class, path and reason: this hook fires on every Write/Edit/NotebookEdit in the
    harness, so a failure that repeated its line on every edit would itself become the
    unbounded log this channel must never grow. A materially different failure has a
    different digest and notifies again.
    """
    printed = []
    printed_failures = []
    shown_failures = []
    digests = {}
    state_path = None
    try:
        failures = render_ledger_failures(ledger_failures)
        entries = notifiable(results)
        if not entries and not failures:
            return
        state_path = state_path_for(payload)
        state = read_state(state_path) if state_path else {}
        digests = {_record_key(record): _readme_digest(record.path) for record in entries}
        digests.update({_ledger_state_key(f): _ledger_digest(f) for f in failures})
        unseen = [
            record for record in entries
            if digests[_record_key(record)] is None
            or state.get(_record_key(record)) != digests[_record_key(record)]
        ]
        printed_failures = [
            failure for failure in failures
            if state.get(_ledger_state_key(failure)) != digests[_ledger_state_key(failure)]
        ]
        if not unseen and not printed_failures:
            return
        shown_failures, failure_body = render_ledger_body(printed_failures)
        remaining = MAX_NOTICE_CHARS - len(failure_body) - (1 if failure_body else 0)
        notice_text = ''
        if unseen and remaining > len(TRUNCATION_SUFFIX):
            printed, notice_text = render_notices(unseen, remaining)
        text = '\n'.join(part for part in (failure_body, notice_text) if part)
        if not text:
            return
        print(json.dumps(build_hook_output(text), ensure_ascii=True))
        sys.stdout.flush()
    except Exception:
        _detach_stdout()
        return
    if not state_path:
        return
    try:
        for record in printed:
            key = _record_key(record)
            if digests[key] is not None:
                state[key] = digests[key]
        # Only failures that were actually PRINTED are recorded as seen, on the
        # same terms as a skip notice: one cut by the length cap must be retried
        # on the next edit rather than marked delivered.
        if failure_body:
            for failure in shown_failures:
                key = _ledger_state_key(failure)
                state[key] = digests[key]
        write_state(state_path, state)
    except Exception:
        pass
