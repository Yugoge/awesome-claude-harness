"""settings.json's hook registrations with each launcher expanded into the hooks it runs.

A launcher (hooks/<event>-launch.py, lib/hook_launch.py) is one registration that runs an
event's Python hooks. A reader that asks "which hooks run on which event, with which matcher
and timeout" (a test, a count, an installer check) reads the registrations through
``expand``: each launcher's registration replaced, in place, by one registration per rule of
its table, shaped as that hook's own registration was (its matcher, its timeout when it is not
the CLI's default, ``python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/<file>"``). The table is read
statically, so any tree can be expanded without running its code.
"""
from __future__ import annotations

import ast
import copy
import os
import re

DEFAULT_TIMEOUT = 60
COMMAND = 'python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/%s"'
_HOOK = re.compile(r"""/(hooks/[^"'\s]+\.py)""")


def rules(root: str, hook: str):
    """[(file, tools, timeout)] of the launcher `hook` (hooks/x.py) under `root`; None when the file
    is no launcher (it does not import lib.hook_launch, or has no RULES table)."""
    try:
        with open(os.path.join(root, hook)) as fh:
            tree = ast.parse(fh.read())
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return None
    if not any(isinstance(n, ast.ImportFrom) and n.module == "lib.hook_launch" for n in ast.walk(tree)):
        return None
    for st in tree.body:
        if isinstance(st, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "RULES" for t in st.targets):
            out = []
            for call in st.value.elts:
                args = [ast.literal_eval(a) for a in call.args]
                kw = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
                tools = kw.get("tools", args[2] if len(args) > 2 else None)
                timeout = kw.get("timeout", args[3] if len(args) > 3 else DEFAULT_TIMEOUT)
                out.append((args[1], tuple(tools) if tools is not None else None, timeout))
            return out
    return None


def spellings(root: str, hook: str) -> dict:
    """{file: matcher} for the rules of launcher `hook` that keep their registration's spelling of
    "every tool" (``matcher_spelling``, e.g. "*"), which ``tools=None`` cannot carry."""
    try:
        with open(os.path.join(root, hook)) as fh:
            tree = ast.parse(fh.read())
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return {}
    out = {}
    for call in ast.walk(tree):
        if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "Rule" and len(call.args) > 1:
            for k in call.keywords:
                if k.arg == "matcher_spelling":
                    out[ast.literal_eval(call.args[1])] = ast.literal_eval(k.value)
    return out


def launcher_of(command: str, root: str):
    """The launcher file a registered command runs (hooks/x.py), or None."""
    found = _HOOK.findall(command or "")
    if found and rules(root, found[-1]) is not None:
        return found[-1]
    return None


def expand(settings: dict, root: str) -> dict:
    """A copy of `settings` whose launcher registrations are the hooks they run."""
    out = copy.deepcopy(settings)
    for event, groups in (out.get("hooks") or {}).items():
        new_groups = []
        for g in groups:
            kept = []
            for h in g.get("hooks", []):
                launcher = launcher_of(h.get("command", ""), root)
                if launcher is None:
                    kept.append(h)
                    continue
                if kept:
                    new_groups.append(dict(g, hooks=kept))
                    kept = []
                for path, tools, timeout in rules(root, launcher):
                    spelled = spellings(root, launcher).get(path)
                    hook = {"type": "command", "command": COMMAND % path}
                    if timeout != DEFAULT_TIMEOUT:
                        hook["timeout"] = timeout
                    group = {"hooks": [hook]}
                    if tools is not None:
                        group = {"matcher": "|".join(tools), "hooks": [hook]}
                    elif spelled:  # every tool, as its registration spelled it ("*")
                        group = {"matcher": spelled, "hooks": [hook]}
                    new_groups.append(group)
            if kept:
                new_groups.append(dict(g, hooks=kept))
        out["hooks"][event] = new_groups
    return out
