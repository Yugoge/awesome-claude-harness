"""The dispatchers' fallback: each hook as its own process, as the CLI ran them.

A dispatcher (hooks/<event>-launch.py) uses this when its own code cannot run:
lib/hook_launch.py does not import, or its runner fails. The standard library
only, so a fault in the dispatcher's other modules never skips a hook. The hooks'
answers combine through lib/hook_launch.combine when that module loads; else a
refusal from any hook is still a refusal (exit 2, every refusal's reason), a stop
a stop, and otherwise the first answer a hook printed is passed on; the other hooks'
contexts and messages go with each of these (``minimal``).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The hook events whose payload names a tool (the dispatchers select their rules by it); defined
# here, the standard-library-only module, and read by lib/hook_launch.py.
TOOL_EVENTS = ("PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest")


class Rule:
    """A dispatcher's table row when lib/hook_launch.py cannot load (the same fields)."""

    def __init__(self, name, path, tools=None, timeout=60.0, matcher_spelling=None, after=()):
        self.name, self.path, self.tools, self.timeout = name, path, tools, timeout
        self.matcher_spelling, self.after = matcher_spelling, after  # in order here: `after` always holds

    def applies(self, tool) -> bool:
        return self.tools is None or tool in self.tools

    @property
    def file(self) -> str:
        return os.path.join(HOOKS, self.path)

    @property
    def matcher(self) -> str:
        if self.matcher_spelling is not None:
            return self.matcher_spelling
        return "|".join(self.tools) if self.tools is not None else ""


class _Result:
    def __init__(self, rule, code, stdout, stderr, seconds):
        self.rule, self.code, self.stdout, self.stderr, self.seconds = rule, code, stdout, stderr, seconds
        self.how = "process"


def _tool(event, raw):
    if event not in TOOL_EVENTS:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data.get("tool_name") if isinstance(data, dict) else None


def _run(rule, raw):
    t0 = time.monotonic()
    try:
        p = subprocess.run(["bash" if rule.path.endswith(".sh") else sys.executable, os.path.join(HOOKS, rule.path)],
                           input=raw, capture_output=True,
                           timeout=rule.timeout)
        return _Result(rule, p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"),
                       time.monotonic() - t0)
    except subprocess.TimeoutExpired:
        return _Result(rule, "timeout", "", "", time.monotonic() - t0)
    except Exception as exc:
        return _Result(rule, 1, "", f"{rule.path}: could not start: {exc}\n", time.monotonic() - t0)


def _plain_context(event) -> bool:
    """Whether `event`'s plain stdout reaches the model (lib/hook_launch's set); yes when the event is not
    named or that module cannot load: a plain text is then delivered rather than dropped."""
    try:
        sys.path.insert(0, HOOKS)
        from lib.hook_launch import PLAIN_CONTEXT_EVENTS
    except Exception:
        return True
    return event is None or event in PLAIN_CONTEXT_EVENTS


def minimal(results, event=None):
    """Exit status, stdout and stderr of `results` without lib/hook_launch.combine: a refusal from any
    hook refuses; else a stop stops; else the first answer printed is passed on. The other hooks' texts
    for the model and the user (contexts, messages; plain stdout on the events whose plain stdout reaches
    the model, or on any when that cannot be told: `_plain_context`) go with it, each once, as combine
    delivers them: after the refusals on stderr, in the stop's systemMessage, else merged into one JSON."""
    refusals, stops, printed, ctxs, msgs, said = [], [], [], [], [], []
    for r in results:
        if r.code == 2:
            refusals.append(r.stderr)
            continue
        try:
            out = json.loads(r.stdout) if r.code == 0 and r.stdout.strip().startswith("{") else None
        except ValueError:
            out = None
        o = out if isinstance(out, dict) else {}
        hso = o.get("hookSpecificOutput") if isinstance(o.get("hookSpecificOutput"), dict) else {}
        if hso.get("permissionDecision") == "deny":
            refusals.append(str(hso.get("permissionDecisionReason") or ""))
        elif o.get("decision") == "block":
            refusals.append(str(o.get("reason") or ""))
        elif o.get("continue") is False:
            stops.append(o)
        elif r.code == 0 and r.stdout.strip():
            printed.append((r, o))
            plain = not isinstance(out, dict) and _plain_context(event)
            mine = event is None or hso.get("hookEventName") in (None, event)
            c = [r.stdout.strip()] if plain else [str(hso["additionalContext"])] if hso.get("additionalContext") \
                and mine else []
            m = [str(o["systemMessage"])] if o.get("systemMessage") else []
            ctxs, msgs, said = ctxs + c, msgs + m, said + c + m
    texts = [t for i, t in enumerate(said) if t not in said[:i]]
    if stops:
        stop = {**stops[0], "systemMessage": "\n".join([str(stops[0].get("systemMessage") or "")] * bool(
            stops[0].get("systemMessage")) + texts)} if texts else stops[0]
        return 0, json.dumps(stop) + "\n", ""
    if refusals:
        return 2, "", "".join(t if t.endswith("\n") else t + "\n" for t in refusals + texts if t)
    errors = "".join(r.stderr for r in results if r.code not in (0, 2))
    if len(printed) > 1:  # one JSON answer: the first one's fields, every hook's contexts and messages
        first = dict(printed[0][1])
        if ctxs:
            first["hookSpecificOutput"] = {**(first.get("hookSpecificOutput") or {}), "additionalContext": "\n".join(
                ctxs), "hookEventName": (first.get("hookSpecificOutput") or {}).get("hookEventName") or event}
        if msgs:
            first["systemMessage"] = "\n".join(msgs)
        return 0, json.dumps(first) + "\n", errors
    if printed:
        return 0, printed[0][0].stdout, errors
    return (1 if errors else 0), "", errors


def run(event, rules, raw, record_fd=None) -> int:
    tool = _tool(event, raw)
    results = [_run(r, raw) for r in rules if tool is None or r.applies(tool)]
    try:
        sys.path.insert(0, HOOKS)
        from lib.hook_launch import combine
        code, out, err = combine(event, results)
    except Exception:
        code, out, err = minimal(results, event)
    if record_fd is not None:
        lines = "".join(json.dumps({"hook": "hooks/" + r.rule.path, "matcher": r.rule.matcher,
                                    "timeout": r.rule.timeout, "rc": r.code, "stdout": r.stdout,
                                    "stderr": r.stderr if r.code != "timeout" else "timeout",
                                    "ms": round(r.seconds * 1000), "how": r.how}) + "\n" for r in results)
        _write(record_fd, lines)
    try:  # an /allow grant's release (lib/hook_launch.release_refused), when that module loads
        from lib.hook_launch import release_refused
        code, out, err = release_refused(event, results, raw, code, out, err)
    except Exception:
        pass
    _write(1, out)
    _write(2, err)
    if code == 2:  # a report to the refusal record (lib/refusal_record.py); it never changes the answer
        try:
            from lib import refusal_record
            refusal_record.report(raw, [(r.rule.file, minimal([r])[2]) for r in results if minimal([r])[0] == 2],
                                  os.path.join(HOOKS, os.path.basename(sys.argv[0])))
        except Exception:
            pass
    return code


def _write(fd, text):
    data = (text or "").encode("utf-8", "replace")
    while data:
        try:
            n = os.write(fd, data)
        except OSError:
            return
        data = data[n:]


def main(event, rules, raw=None) -> int:
    """The dispatcher's entry when lib/hook_launch.py cannot load."""
    if raw is None:
        raw = sys.stdin.buffer.read()
    os.environ.pop("CLAUDE_HOOK_LAUNCH_MARKS", None)  # its hooks run as processes: the trace names them
    fd = os.environ.pop("CLAUDE_HOOK_LAUNCH_RECORD_FD", "")
    try:
        fd = int(fd) if fd else None
    except ValueError:
        fd = None
    return run(event, rules, raw, fd)
