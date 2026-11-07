"""The /do report's one reading (P1b E8).

`docs/dev/do-report-<task_id>.json` has one producer, the /do main agent. Every
reader of it takes `load`'s verdict on whether there is a record (the /do Stop
gate, which then decides the record's own contract; the e2e gate's
expected-absent exemption; the /commit repository plan) instead of an existence
or parse test of its own, and acts on the fields it uses.

Stdlib-only; never raises.
"""

from __future__ import annotations

import json
from pathlib import Path


def load(path) -> tuple[dict | None, str | None]:
    """(record, None) for a report holding a JSON object; (None, reason) when it is
    absent, unreadable or not an object."""
    p = Path(path)
    try:
        record = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"do-report absent: {p}"
    except (OSError, ValueError) as e:
        return None, f"do-report unreadable/unparseable: {e}"
    if not isinstance(record, dict):
        return None, "do-report is not a JSON object"
    return record, None


def expected_absent(path) -> list:
    """The artifact kinds the report declares this task leaves absent (its
    `expected_absent`), or [] when it declares none or there is no record."""
    record, _problem = load(path)
    absent = record.get("expected_absent") if record is not None else None
    return [a for a in absent if isinstance(a, str)] if isinstance(absent, list) else []
