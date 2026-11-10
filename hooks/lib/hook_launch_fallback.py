"""The dispatchers' fallback: each hook as its own process, as the CLI ran them.

A dispatcher (hooks/<event>-launch.py) uses this when its own code cannot run:
lib/hook_launch.py does not import, or its runner fails. The standard library
only, so a fault in the dispatcher's other modules never skips a hook. The hooks'
answers combine through lib/hook_launch.combine when that module loads; else a
refusal from any hook is still a refusal (exit 2, every refusal's reason), and
otherwise the first answer a hook printed is passed on.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL_EVENTS = ("PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest")


class Rule:
    """A dispatcher's table row when lib/hook_launch.py cannot load (the same fields)."""

    def __init__(self, name, path, tools=None, timeout=60.0, matcher_spelling=None):
        self.name, self.path, self.tools, self.timeout = name, path, tools, timeout
        self.matcher_spelling = matcher_spelling

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
        p = subprocess.run([sys.executable, os.path.join(HOOKS, rule.path)], input=raw, capture_output=True,
                           timeout=rule.timeout)
        return _Result(rule, p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"),
                       time.monotonic() - t0)
    except subprocess.TimeoutExpired:
        return _Result(rule, "timeout", "", "", time.monotonic() - t0)
    except Exception as exc:
        return _Result(rule, 1, "", f"{rule.path}: could not start: {exc}\n", time.monotonic() - t0)


def minimal(results):
    """Exit status, stdout and stderr of `results` without lib/hook_launch.combine: a refusal from any
    hook refuses; else the first answer printed is passed on."""
    refusals = []
    for r in results:
        if r.code == 2:
            refusals.append(r.stderr)
            continue
        try:
            out = json.loads(r.stdout) if r.code == 0 and r.stdout.strip().startswith("{") else None
        except ValueError:
            out = None
        if isinstance(out, dict):
            hso = out.get("hookSpecificOutput") if isinstance(out.get("hookSpecificOutput"), dict) else {}
            if hso.get("permissionDecision") == "deny":
                refusals.append(str(hso.get("permissionDecisionReason") or ""))
            elif out.get("decision") == "block":
                refusals.append(str(out.get("reason") or ""))
    if refusals:
        return 2, "", "".join(t if t.endswith("\n") else t + "\n" for t in refusals if t)
    printed = [r.stdout for r in results if r.code == 0 and r.stdout.strip()]
    errors = "".join(r.stderr for r in results if r.code not in (0, 2))
    if printed:
        return 0, printed[0], errors
    return (1 if errors else 0), "", errors


def run(event, rules, raw, record_fd=None) -> int:
    tool = _tool(event, raw)
    results = [_run(r, raw) for r in rules if tool is None or r.applies(tool)]
    try:
        sys.path.insert(0, HOOKS)
        from lib.hook_launch import combine
        code, out, err = combine(event, results)
    except Exception:
        code, out, err = minimal(results)
    if record_fd is not None:
        lines = "".join(json.dumps({"hook": "hooks/" + r.rule.path, "matcher": r.rule.matcher,
                                    "timeout": r.rule.timeout, "rc": r.code, "stdout": r.stdout,
                                    "stderr": r.stderr if r.code != "timeout" else "timeout",
                                    "ms": round(r.seconds * 1000), "how": r.how}) + "\n" for r in results)
        _write(record_fd, lines)
    _write(1, out)
    _write(2, err)
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
    fd = os.environ.pop("CLAUDE_HOOK_LAUNCH_RECORD_FD", "")
    try:
        fd = int(fd) if fd else None
    except ValueError:
        fd = None
    return run(event, rules, raw, fd)
