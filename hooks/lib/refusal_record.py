#!/usr/bin/env python3
"""The refusal record: one line for every tool call, stop or prompt a registered hook refuses.

The gates' advisory logs had no reader and were deleted (P1b); since then nothing could say what
the harness refused. This file is the record's one writer and the one definition of where
it lives; scripts/refusals reads it (totals, counts, loops, the reconcile with the transcripts).

Who reports. The process that sees a hook refuse, naming the refusing hook file and the text it gave
the agent: a launcher (lib/hook_launch.py) its rules, a gate (hooks/pretool-write-gate.py,
lib/gate_runner.py) the rules of its table, lib/bash_safety_rules.py itself, hooks/stop-launch.py
the Stop coordinator's block or its own, a shell hook its exit 2 (lib/refusal_record.sh). Each
reports through this file's command line (``report``): the writer runs as a process of its own, so
one program writes the record and nothing it does reaches the hook that reported. The reports of
one call merge into one line (``same``, ``merge``): a hook that reported its own rules replaces what
its parent said of it. A payload that names no refusing event (a canary's probe, a unit test's
input) is no call of the CLI: nothing is started and nothing recorded.

Where. ``directory()``: <user's home>/.local/state/claude-harness/<harness home's name>-<crc32 of
its real path>/refusals/refusals-<UTC day>.jsonl. The harness home is the one lib/harness_switch.py
derives from this file's location, so every session running this home's hooks (through ~/.claude, an
account's linked hooks/, a daemon) and the reader resolve one place: on disk where the home is on
tmpfs, private to the user (directory 0700, files 0600). A day's file stops growing at MAX_DAY_BYTES,
and the days older than KEEP_DAYS go when a new day's file starts.

Recording never decides: ``write`` returns False where it cannot write (no space, no permission, the
day file's lock not free within LOCK_WAIT seconds) and never raises; ``report`` waits at most
REPORT_WAIT seconds for the writer and reads nothing back from it.

Kinds. REFUSAL; UNPROVEN, a command the removal policy could not prove safe and let through: the
same fields, counted apart by the reader and left out of its reconcile.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import time
import zlib

try:  # as lib.refusal_record; else with hooks/lib on the path (lib/bash_safety_rules.py), or run as a script
    from . import harness_switch
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import harness_switch
    finally:
        sys.path.pop(0)

REFUSAL, UNPROVEN = "refusal", "unproven"
# The events at which a hook's exit 2 refuses something: a call before or after it ran, a prompt, a stop.
EVENTS = ("PreToolUse", "PostToolUse", "PostToolUseFailure", "UserPromptSubmit", "Stop", "SubagentStop")
KEEP_DAYS, MAX_DAY_BYTES = 90, 16 << 20
LOCK_WAIT, SAME_CALL, REPORT_WAIT = 2.0, 30, 10   # seconds
TEXT_MAX = 4000                         # characters of a rule's text handed to the writer
TAIL = 1 << 18                          # bytes of the day file searched for an earlier report of the call
REFUSED_MAX, MESSAGE_MAX, RULES_MAX, WORDS = 400, 800, 12, 8
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_.'+-]*$")
_EDGE, _QUOTE = "[](){}.,;:!?\u2014\u2013", ("'", '"', "`")


def directory() -> str:
    """The record's directory: the one definition, for this writer and for scripts/refusals."""
    home = harness_switch.harness_home()
    key = "-".join((home.rsplit(os.sep, 1)[-1].lstrip("."), f"{zlib.crc32(os.fsencode(home)):08x}"))
    return os.path.join(os.path.expanduser("~"), ".local", "state", "claude-harness", key, "refusals")


def day_file(now: float) -> str:
    """The name of the file holding the records of `now`'s UTC day."""
    return "refusals-" + time.strftime("%Y-%m-%d", time.gmtime(now)) + ".jsonl"


def _stamp(now: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now % 1 * 1000):03d}Z"


def _name(hook: str) -> str:
    """A hook file as its path below the harness home (hooks/x.py); another name as it is."""
    home = harness_switch.harness_home()
    real = os.path.realpath(hook) if os.path.isabs(hook) else hook
    return os.path.relpath(real, home) if real.startswith(home + os.sep) else hook


def _version() -> str:
    """The harness's VERSION and, where its home is a git checkout, the first 12 hex of its HEAD."""
    home, out = harness_switch.harness_home(), []
    try:
        with open(os.path.join(home, "VERSION")) as fh:
            out.append(fh.read().strip())
        with open(os.path.join(home, ".git", "HEAD")) as fh:
            head = fh.read().strip()
        if head.startswith("ref: "):
            try:
                with open(os.path.join(home, ".git", head[5:])) as fh:
                    head = fh.read().strip()
            except OSError:
                with open(os.path.join(home, ".git", "packed-refs")) as fh:
                    head = next((ln.split()[0] for ln in fh if ln.rstrip().endswith(" " + head[5:])), "")
        out.append(head[:12])
    except OSError:
        pass
    return "+".join(x for x in out if x)


def _words(line: str, skip, limit: int) -> list[str]:
    """The constant words of one line of a refusal text, `limit` at most: a token is variable text, and
    left out, unless it is a plain word (letters first; at most two digits; no path, quote, option,
    assignment or other sign in it), not in `skip`, and outside a quoted span; `code:detail` gives
    the code and ends the line."""
    def plain(word: str) -> bool:
        return bool(_WORD.match(word)) and sum(c.isdigit() for c in word) <= 2 and word not in skip

    out, quoted = [], False
    for token in line.split():
        code, _, detail = token.partition(":")
        coded = bool(detail) and not quoted and plain(code.strip(_EDGE))
        opens, closes = token[0] in _QUOTE, token.rstrip(_EDGE)[-1:] in _QUOTE
        if not coded and (quoted or opens or closes):
            quoted = (quoted or opens) and not closes
            continue
        word = (code if coded else token).strip(_EDGE)
        if not plain(word):
            continue
        out.append(word.lower())
        if coded or len(out) >= limit:
            break
    return out


def rule_id(text, skip=()) -> str:
    """The identifier of the rule that gave `text`: the constant words of its first line (``_words``),
    WORDS at most, and of the line after it where the first ends in a colon and that one is its detail
    (indented, or a list item); the same for every call the rule refuses. A JSON object in the line
    stands for its sentence, the string value with the most words, and its other string values are
    variable text, as the words of `skip` are (the call's tool, role and ids)."""
    lines = [ln for ln in str(text).splitlines() if ln.strip()]
    head, skip = (lines[0].strip() if lines else ""), set(skip)
    a, b = head.find("{"), head.rfind("}")
    if 0 <= a < b:
        try:
            values = [v for v in json.loads(head[a:b + 1]).values() if isinstance(v, str)]
        except (ValueError, AttributeError):
            values = []
        if values:
            sentence = max(values, key=lambda v: len(v.split()))
            head, skip = head[:a] + sentence + head[b + 1:], skip | (set(values) - {sentence})
    words = _words(head, skip, WORDS)
    if head.endswith(":") and len(lines) > 1 and lines[1][0] in " \t-*":
        words += _words(lines[1], skip, WORDS // 2)
    return "-".join(words)


def same(old: dict, new: dict) -> bool:
    """Whether two reports are of one call: the kind, session, event and tool-call id are the same;
    where the payload has no id, the agent, tool and refused text are too, the earlier report is at most
    SAME_CALL seconds old and comes from other hooks (a hook reports a call once: its next is a retry)."""
    if any(old.get(k) != new.get(k) for k in ("kind", "session", "event", "tool_use_id")):
        return False
    if new.get("tool_use_id"):
        return True
    return (new.get("event") in EVENTS[:3] and all(old.get(k) == new.get(k) for k in ("agent_id", "tool", "refused"))
            and not {r.get("by") for r in old.get("rules", [])} & {r.get("by") for r in new.get("rules", [])}
            and str(old.get("ts")) >= _stamp(time.time() - SAME_CALL))


def merge(old: dict, new: dict) -> dict:
    """Two reports of one call as one record: the first report's fields, every rule once in a fixed
    order, a hook's own report in place of what its parent said of that hook, the longer text (both
    where neither holds the other), and each tool name a hook was handed the call under (the CLI hands
    a Monitor's command to the Bash-matched hooks as a Bash call)."""
    rules = old.get("rules", []) + [r for r in new.get("rules", []) if r not in old.get("rules", [])]
    said = {r.get("by") for r in rules}
    rules = sorted((r for r in rules if r.get("hook") == r.get("by") or r.get("hook") not in said),
                   key=lambda r: (str(r.get("hook")), str(r.get("id")), str(r.get("by"))))
    texts = sorted({old.get("message") or "", new.get("message") or ""} - {""})
    message = next((t for t in texts if all(x in t for x in texts)), "\n".join(texts))
    tools = sorted({t for x in (old, new) for t in str(x.get("tool") or "").split("|") if t})
    return dict(old, rules=rules[:RULES_MAX], message=message[:MESSAGE_MAX], tool="|".join(tools) or None)


def report(payload, rules, by, kind=REFUSAL) -> None:
    """A hook's report of one call it refused (or, kind=UNPROVEN, let through unproven): ``write``, run as a
    process of its own through this file's command line. A payload that names no refusing event starts
    nothing. Never raises; whatever the writer does, the hook goes on."""
    try:
        p, rules = _payload(payload), [(str(h), str(t)[:TEXT_MAX].replace("\0", " ")) for h, t in rules]
        if p.get("hook_event_name") in EVENTS and rules:
            raw = payload if isinstance(payload, bytes) else json.dumps(p).encode("utf-8", "replace")
            subprocess.run([sys.executable, os.path.abspath(__file__), kind, str(by), *(x for rule in rules for x in rule)],
                           input=raw, capture_output=True, timeout=REPORT_WAIT)
    except Exception:  # noqa: BLE001 - a report that cannot be made changes nothing
        pass


def write(payload, rules, by, kind=REFUSAL) -> bool:
    """Record one call that hooks refused (or, kind=UNPROVEN, let through unproven).

    payload: the hook's stdin (bytes, text or the parsed object); rules: (hook file, the text it gave)
    pairs, one per refusing rule; by: the hook file that reports them. True when the record holds the
    report (a new line, or merged into the call's line). Never raises."""
    try:
        return _write(_payload(payload), list(rules), by, kind)
    except Exception:  # noqa: BLE001 - a record that cannot be written changes nothing
        return False


def _payload(payload) -> dict:
    if isinstance(payload, (bytes, str)):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = None
    return payload if isinstance(payload, dict) else {}


def _write(p: dict, rules, by, kind) -> bool:
    event = p.get("hook_event_name")
    if event not in EVENTS or not rules or kind not in (REFUSAL, UNPROVEN):
        return False
    tool_input = p.get("tool_input") if isinstance(p.get("tool_input"), dict) else {}
    refused = next((tool_input[k] for k in ("command", "file_path", "notebook_path")
                    if isinstance(tool_input.get(k), str)), None)
    if refused is None:
        refused = json.dumps(tool_input, ensure_ascii=False, sort_keys=True) if tool_input else str(p.get("prompt") or "")
    skip = {str(p[k]) for k in ("tool_name", "agent_type", "agent_id", "session_id") if p.get(k)}
    env, now = os.environ, time.time()
    record = {
        "v": 1, "kind": kind, "ts": _stamp(now), "event": event, "session": p.get("session_id"),
        "actor": "subagent" if p.get("agent_id") else "main", "agent_id": p.get("agent_id") or None,
        "role": p.get("agent_type") or None, "tool": p.get("tool_name"), "tool_use_id": p.get("tool_use_id"),
        "refused": refused[:REFUSED_MAX],
        "rules": [{"hook": _name(str(h)), "id": rule_id(t, skip), "by": _name(str(by))} for h, t in rules][:RULES_MAX],
        "message": "\n".join(str(t).strip("\n") for _, t in rules if t)[:MESSAGE_MAX],
        "project": env.get("CLAUDE_PROJECT_DIR") or p.get("cwd"),
        "provider": "codex" if env.get("CLAUDE_COMPAT_RUNTIME") == "codex" else
                    "claude" if env.get("CLAUDECODE") or env.get("CLAUDE_PROJECT_DIR") else None,
        "version": _version(),
    }
    return _append(record, now)


def _append(record: dict, now: float) -> bool:
    folder = directory()
    if not os.path.isabs(folder):  # no home to expand "~" to
        return False
    path = os.path.join(folder, day_file(now))
    try:
        fd = os.open(path, os.O_RDWR)
    except FileNotFoundError:  # the day's first record: the folder if need be, and the days past KEEP_DAYS go
        os.makedirs(folder, mode=0o700, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        oldest = day_file(now - KEEP_DAYS * 86400)
        try:
            for name in os.listdir(folder):
                if name.startswith("refusals-") and name.endswith(".jsonl") and name < oldest:
                    os.unlink(os.path.join(folder, name))
        except OSError:
            pass
    try:
        deadline = time.monotonic() + LOCK_WAIT
        while True:  # every writer holds the lock: a merge rewrites the file's end
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    return False
                time.sleep(0.002)
        size = os.fstat(fd).st_size
        if size >= MAX_DAY_BYTES:
            return False
        start = max(0, size - TAIL)
        tail = os.pread(fd, size - start, start)
        at, rest, end = len(tail), b"", len(tail)
        mark = json.dumps(record["session"]).encode() if record.get("session") else None
        while mark and end > 0:  # the lines from the last back, each tail[begin:end] with its newline
            begin = tail.rfind(b"\n", 0, end - 1) + 1
            if begin == 0 and start:
                break  # cut by the window
            if mark in tail[begin:end]:
                try:
                    old = json.loads(tail[begin:end])
                except ValueError:
                    old = None
                if isinstance(old, dict) and same(old, record):
                    record, at, rest = merge(old, record), begin, tail[end:]
                    break
            end = begin
        data = json.dumps(record, ensure_ascii=False).encode("utf-8", "backslashreplace") + b"\n" + rest
        if at == len(tail) and tail and not tail.endswith(b"\n"):
            data = b"\n" + data  # a crash left a fragment: it stays a line of its own
        os.pwrite(fd, data, start + at)
        os.ftruncate(fd, start + at + len(data))
        return True
    finally:
        os.close(fd)


if __name__ == "__main__" and len(sys.argv) > 3:
    # a report: <kind> <reporting hook>, then <refusing hook> <its text> for each rule; the payload on stdin
    write(sys.stdin.buffer.read(), list(zip(sys.argv[3::2], sys.argv[4::2])), sys.argv[2], sys.argv[1])
