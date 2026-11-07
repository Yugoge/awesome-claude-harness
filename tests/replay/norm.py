"""Normalisation shared by block records and trace relations.

A replay's own values (session ids, agent ids, tool-use ids, task ids, lanes,
the project slug) are replaced by value, and its timestamps by value too: a timestamp-shaped
substring is replaced only when it falls inside the run's own time window, so a
date that is part of the tree's content is kept. In a minted id that holds a
timestamp only the timestamp is replaced (dev-<ts>, not <task>). Sandbox roots
become stable tokens, so the same replay compares byte for byte across runs,
across isolation modes and across kits.
"""
from __future__ import annotations

import datetime as _dt
import re

_UTC = _dt.timezone.utc
_SLACK_S = 300

# Timestamp-shaped candidates, longest forms first; digit boundaries on both sides.
_TS_RE = re.compile(
    r"(?<![0-9])(?:"
    r"(?P<iso>\d{4}-\d{2}-\d{2}[T _]\d{2}[:\-]?\d{2}(?:[:\-]?\d{2}(?:[.,]\d{1,9})?)?(?:Z|[+-]\d{2}:?\d{2})?)"
    r"|(?P<compact>\d{8}[T_-]?\d{6}(?:[.,_-]\d{1,9})?Z?)"
    r"|(?P<epoch>\d{10}(?:\d{3}|\d{6}|\d{9})?(?:\.\d{1,9})?)"
    r"|(?P<date>\d{4}-\d{2}-\d{2}|\d{8})"
    r")(?![0-9])")
_UUID_RE = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9A-Za-z])", re.I)
_HEX_RE = re.compile(r"(?<![0-9A-Za-z])(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{12,}(?![0-9A-Za-z])")
_GIT_OBJ_RE = re.compile(r"(/objects/)(?:[0-9a-f]{2}/[0-9a-f]{38}|pack/pack-[0-9a-f]{40}(?=\.))")
_TMPNAME_RE = re.compile(r"(?<=/)(?:tmp[a-z0-9_]{8}|tmp\.[A-Za-z0-9]{10}|\.?tmp_obj_[A-Za-z0-9]{6})(?=$|[./])")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


class Window:
    """The run's wall-clock window; a timestamp is the replay's own when inside it."""

    def __init__(self, start: float, end: float | None = None):
        self.start, self.end = start, end

    def _bounds(self):
        end = self.end if self.end is not None else self.start + 86400
        return self.start - _SLACK_S, end + _SLACK_S

    def contains_epoch(self, secs: float) -> bool:
        lo, hi = self._bounds()
        return lo <= secs <= hi

    def contains_date(self, d: _dt.date) -> bool:
        lo, hi = self._bounds()
        days = {_dt.datetime.fromtimestamp(t, tz).date() for t in (lo, hi) for tz in (_UTC, None)}
        return min(days) <= d <= max(days)

    def is_own(self, m: re.Match) -> bool:
        kind = m.lastgroup
        s = m.group(kind)
        try:
            if kind == "epoch":
                whole = s.split(".")[0]
                secs = int(whole) / {10: 1, 13: 1e3, 16: 1e6, 19: 1e9}[len(whole)]
                return self.contains_epoch(secs)
            d = _digits(s)
            if kind == "date":
                return self.contains_date(_dt.date(int(d[:4]), int(d[4:6]), int(d[6:8])))
            parts = [int(d[:4]), int(d[4:6]), int(d[6:8]), int(d[8:10]), int(d[10:12])]
            sec = int(d[12:14]) if len(d) >= 14 else 0
            naive = _dt.datetime(*parts, sec)
            # The replay's own clock may have written UTC or local time.
            return any(self.contains_epoch(naive.replace(tzinfo=tz).timestamp()) for tz in (_UTC, None))
        except (ValueError, KeyError, OverflowError):
            return False

    def sub(self, text: str, token: str = "<ts>") -> str:
        return _TS_RE.sub(lambda m: token if self.is_own(m) else m.group(0), text)

    def holds_ts(self, text: str) -> bool:
        return any(self.is_own(m) for m in _TS_RE.finditer(text))


class Ids:
    """Values the replay minted or learned, replaced by value with their token."""

    TOKENS = {"sid": "<sid>", "agent": "<agent>", "tool": "<tool>", "task": "<task>",
              "lane": "<lane>", "slug": "<slug>", "rand": "<rand>"}

    def __init__(self):
        self.values: dict[str, str] = {}

    def add(self, kind: str, value) -> None:
        value = str(value or "")
        if value and value not in self.values:
            self.values[value] = kind

    def to_json(self) -> dict:
        return dict(self.values)

    @classmethod
    def from_json(cls, data: dict) -> "Ids":
        ids = cls()
        ids.values.update(data)
        return ids

    def sub(self, text: str, window: Window | None = None, kinds=None) -> str:
        for value in sorted(self.values, key=len, reverse=True):
            kind = self.values[value]
            if kinds and kind not in kinds:
                continue
            # A minted id that holds a timestamp keeps its other parts: the ts rule handles it.
            if kind == "task" and window is not None and window.holds_ts(value):
                continue
            if value not in text:
                continue
            text = re.sub(r"(?<![0-9A-Za-z])%s(?![0-9A-Za-z])" % re.escape(value), self.TOKENS[kind], text)
        return text


class Roots:
    """Sandbox path prefixes and the token each becomes (longest prefix wins)."""

    def __init__(self, pairs):
        self.pairs = sorted(((p.rstrip("/") or "/", t) for p, t in pairs if p), key=lambda pt: -len(pt[0]))

    def token_path(self, path: str) -> str | None:
        """`<token>/rest` for a path under one of the roots, else None."""
        for prefix, token in self.pairs:
            if path == prefix or path.startswith(prefix + "/"):
                return token + path[len(prefix):]
        return None

    def sub_text(self, text: str) -> str:
        for prefix, token in self.pairs:
            if len(prefix) > 1:
                text = text.replace(prefix, token)
        return text


def id_spans(text: str) -> list[tuple[int, int]]:
    """Where generic() sees an id no driver registered as a whole token (a uuid, a long hex id)."""
    return [m.span() for rx in (_UUID_RE, _HEX_RE) for m in rx.finditer(text)]


def generic(text: str) -> str:
    """Ids no driver registered: uuids, long hex ids, git object names, temp-file names."""
    text = _GIT_OBJ_RE.sub(r"\1<obj>", text)
    text = _TMPNAME_RE.sub("<tmp>", text)
    text = _UUID_RE.sub("<uuid>", text)
    return _HEX_RE.sub("<hex>", text)


def refusal_text(text: str, roots: Roots, ids: Ids, window: Window) -> str:
    """A hook's refusal text with run ids, session ids, hex ids, timestamps and sandbox paths removed."""
    text = roots.sub_text(text)
    text = ids.sub(text, window)
    text = window.sub(text)
    text = generic(text)
    return re.sub(r"[ \t]+", " ", text).strip()
