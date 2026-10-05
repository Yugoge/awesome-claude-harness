"""Shared filename-classification for dev-report shard discovery.

Single source for the per-worker / canonical dev-report filename regexes and
the NON_WORKER_LABELS / NON_WORKER_LABEL_RE iteration-suffix filter.
hooks/pretool-aggregate-check.py, scripts/aggregate-dev-report.py, and
hooks/posttool-lane-completeness-watch.py all import from here instead of
hand-mirroring copies (ticket 20261001-161041-r05 M2; prior drift already
required a one-off sync, commit 3c0101ce, backlog #102).

classify_filename() reproduces the exact classification precedence
previously hand-copied as
hooks/pretool-aggregate-check.py::_classify_filename: prefixed-canonical,
prefixed-worker, bare-canonical, role-first-worker, task-first-worker --
filtering NON_WORKER_LABELS / NON_WORKER_LABEL_RE iteration-suffix tokens
("iter2", "retry", "draft", ...) out of worker classification. Callers that
need the regex objects directly (e.g. cross-module pattern-equality checks)
can import them too.
"""

import re

# Active /dev adapter naming: dev-report-dev-<task-id>-<worker>.json.
PREFIXED_WORKER_RE = re.compile(
    r"^dev-report-(?P<task_id>dev-\d{8}-\d{6})-(?P<worker>[A-Za-z0-9][A-Za-z0-9.\-]*)\.json$"
)

# Active /dev canonical: dev-report-dev-<task-id>.json.
PREFIXED_CANONICAL_RE = re.compile(
    r"^dev-report-(?P<task_id>dev-\d{8}-\d{6})\.json$"
)

# Per-worker filename -- role-first naming: dev-report-<role>-<task-id>.json
PER_WORKER_ROLE_FIRST_RE = re.compile(
    r"^dev-report-(?P<role>[A-Za-z0-9]+)-(?P<task_id>\d{8}-\d{6})\.json$"
)

# Per-worker filename -- task-first naming: dev-report-<task-id>-<worker>.json
PER_WORKER_TASK_FIRST_RE = re.compile(
    r"^dev-report-(?P<task_id>\d{8}-\d{6})-(?P<worker>[A-Za-z0-9][A-Za-z0-9.\-]*)\.json$"
)

# Canonical singular: dev-report-<task-id>.json
CANONICAL_RE = re.compile(r"^dev-report-(?P<task_id>\d{8}-\d{6})\.json$")

# Bare iteration / draft / retry suffixes real cycles emit as within-shard
# markers (NOT separate workers).
NON_WORKER_LABELS = frozenset({
    "draft", "final", "fix", "continuation", "wip",
})

# Numeric-suffixed variants of the same iteration markers (iter2, retry1, ...).
NON_WORKER_LABEL_RE = re.compile(
    r"^(?:iter|retry|attempt)\d*$",
    re.IGNORECASE,
)


def is_non_worker_label(label):
    """True iff `label` is a within-shard iteration/draft marker, not a
    real worker/lane label."""
    label_lc = label.lower()
    return label_lc in NON_WORKER_LABELS or bool(NON_WORKER_LABEL_RE.match(label_lc))


def classify_filename(name):
    """Return ('canonical', task_id) | ('worker', task_id, label) | None.

    Order: prefixed-canonical, prefixed-worker, bare-canonical, role-first,
    task-first. Each branch returns once; None if no match. MUST stay
    byte-identical to the pre-refactor hooks/pretool-aggregate-check.py
    ::_classify_filename this was extracted from (ticket 20261001-161041-r05
    AC5).
    """
    m_prefixed_canonical = PREFIXED_CANONICAL_RE.match(name)
    if m_prefixed_canonical is not None:
        return ("canonical", m_prefixed_canonical.group("task_id"))
    m_prefixed_worker = PREFIXED_WORKER_RE.match(name)
    if m_prefixed_worker is not None:
        worker = m_prefixed_worker.group("worker")
        if is_non_worker_label(worker):
            return None
        return ("worker", m_prefixed_worker.group("task_id"), worker)
    m_can = CANONICAL_RE.match(name)
    if m_can is not None:
        return ("canonical", m_can.group("task_id"))
    m_role = PER_WORKER_ROLE_FIRST_RE.match(name)
    if m_role is not None:
        role = m_role.group("role")
        if is_non_worker_label(role):
            return None
        return ("worker", m_role.group("task_id"), role)
    m_task = PER_WORKER_TASK_FIRST_RE.match(name)
    if m_task is None:
        return None
    worker = m_task.group("worker")
    if is_non_worker_label(worker):
        return None
    return ("worker", m_task.group("task_id"), worker)
