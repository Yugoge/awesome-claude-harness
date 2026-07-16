#!/usr/bin/env python3
"""P0 anchor helper predicates for the guard.

The cleanly-extractable leaf subset of the HEAD-AGNOSTIC P0 anchor scan.
Depends on shell_lex (`_strip_quotes`) + constants (`RUNTIMES`,
`EXEC_RUNNER_TOKENS`, `SERVICE_VERBS`) + stdlib; references nothing from _core.
See docs/reference/monolith-split-plan.md for the decomposition rationale (incl.
why the irreducible P0 decision ENGINE `_p0_anchor` and every forward-referencing
anchor helper stay in _core) and the INV-3 dual-context import contract.

Scope: the exec-token scanner (`_anchor_exec_tokens`), the launch-position and
fused-option-value primitives (`_anchor_in_launch_position`,
`_fused_option_values`), the head-agnostic service-control hit-detector
(`_anchor_service_hits_protected`), and the non-protected-workspace-selector
exemption predicate (`_anchor_nonprotected_workspace_selector`), plus the generic
launch-subcommand / service-manager / recursive-workspace lookup tables they key
on.
ZERO project identifiers.
"""

from __future__ import annotations

import os
import re

# The anchor predicates key on the phase-1 quote stripper and the phase-2 runtime
# /runner/service-verb lookup tables. Dual-context import (INV-3) --
# see docs/reference/monolith-split-plan.md.
try:
    from .shell_lex import _strip_quotes
    from .constants import EXEC_RUNNER_TOKENS, RUNTIMES, SERVICE_VERBS
except ImportError:  # executed under the top-level-script shim (no package)
    from shell_lex import _strip_quotes  # type: ignore[no-redef]
    from constants import EXEC_RUNNER_TOKENS, RUNTIMES, SERVICE_VERBS  # type: ignore[no-redef]


# Launch subcommand grammar: a protected command/launch-path is a daemon LAUNCH
# when followed (immediately, after its own flags) by one of these subcommands.
# These are generic process-lifecycle verbs, NOT project names.
_LAUNCH_SUBCMDS = frozenset({
    "daemon", "start", "start-sync", "serve", "run", "up", "spawn", "launch",
})


def _anchor_exec_tokens(tokens: list) -> list:
    """Return the list of (index, token) bare EXECUTABLE-position candidate tokens
    for the anchor scan: tokens that are NOT options (no leading '-'), NOT a
    VAR=val env-prefix, and NOT inside a redirection. These are the words that a
    front-end / wrapper chain could exec() or pass to a build/launch. Quoted
    tokens are stripped. This is head-agnostic: it scans the WHOLE argv (the head
    itself is also a candidate, since a bare `<protected-cmd> <launch-subcmd>` has
    the protected command as its head).
    """
    out = []
    skip_next = False
    for i, raw in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue
        st = _strip_quotes(raw)
        if not st:
            continue
        # redirection operators (> >> < 2> &>) and their target are not exec words
        if st in (">", ">>", "<", "2>", "&>", "1>", "2>>", "|", "&", ";"):
            skip_next = st in (">", ">>", "<", "2>", "&>", "1>", "2>>")
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", st):
            # VAR=val env-prefix
            continue
        # keep the `--` end-of-options marker as a position anchor (the token
        # after it is in executable position), but skip all other options.
        if st == "--":
            out.append((i, st))
            continue
        if st.startswith("-"):
            continue
        out.append((i, st))
    return out


# Launch subcommands a protected command/path takes (`<cmd> daemon start`).
# Generic process-lifecycle verbs — NOT project names.
_ANCHOR_LAUNCH_FOLLOW = _LAUNCH_SUBCMDS


def _anchor_in_launch_position(exec_vals: list, pos: int) -> bool:
    """True if the exec token at `pos` is a LAUNCH (vs a data/argument). A
    protected command/path anchor is a launch when:
      • it is the FIRST exec token (`<protected> …`, possibly the head), OR
      • the preceding exec token is `--` (end-of-options before the real cmd), OR
      • the preceding exec token is a runtime/runner (`node <path>`), OR
      • it is FOLLOWED by a launch subcommand (`<protected> daemon start`).
    Otherwise the token is an argument to some other head (`cp <path> dst`,
    `pytest -k <name>`, `grep <name>`) and is NOT a launch.
    """
    if pos == 0:
        return True
    prev = exec_vals[pos - 1]
    if prev == "--":
        return True
    if os.path.basename(prev) in RUNTIMES or os.path.basename(prev) in EXEC_RUNNER_TOKENS:
        return True
    if pos + 1 < len(exec_vals) and exec_vals[pos + 1] in _ANCHOR_LAUNCH_FOLLOW:
        return True
    return False


def _fused_option_values(tokens: list) -> list:
    """Yield the RHS values of fused `--opt=value` / `-o=value` option tokens, so
    a wrapper option whose VALUE is a protected launch path / command is still
    seen (`<wrapper> --exec=<protected-path> …`). The whole `--opt` token is
    otherwise skipped by _anchor_exec_tokens (it starts with '-')."""
    out = []
    for raw in tokens:
        st = _strip_quotes(raw)
        if st.startswith("-") and "=" in st:
            val = st.split("=", 1)[1]
            if val:
                out.append(_strip_quotes(val))
    return out


# Service-manager program basenames the service-control anchor recognizes. These
# are generic init/service tools — NOT project names. Mirrors the head set P2
# keys on, so the anchor blocks the same family head-agnostically.
_SERVICE_MANAGER_PROGRAMS = frozenset({"systemctl", "service", "initctl"})


def _anchor_service_hits_protected(tokens: list, exec_toks: list,
                                   services: list) -> bool:
    """True if the simple command (head-agnostic) is a service-manager invocation
    that disrupts a PROTECTED unit: a service-manager program basename
    (systemctl/service/initctl) appears in EXECUTABLE position (head-agnostic, so
    it fires behind any wrapper front-end) AND a disruptive lifecycle verb
    (SERVICE_VERBS — start/stop/restart/try-restart/reload/reload-or-restart/kill/
    disable/mask/enable + the force/conditional variants force-reload/condrestart/
    try-reload-or-restart/reload-or-try-restart/condreload) AND a protected unit
    name appear in the service-manager's OWN argv (the tokens FROM that program
    onward) — NOT anywhere in the simple command. Matches the bare unit,
    `unit.service`, and the systemd template-instance form `unit@instance(.service)`
    — the SAME regex P2 uses on its own `rest`. The wrapper NAME is irrelevant
    (mirrors how W1/W2/W4 are head-agnostic). Scoping verb+unit to the manager's
    own argv (exactly like P2 scopes to `rest`) avoids over-blocking a protected
    name carried as an UNRELATED operand (`UNIT=<unit> systemctl restart other`,
    `systemd-run --unit <unit> systemctl restart other`) or `service` used as a
    non-manager noun after a different command (`docker compose restart <unit>
    service`)."""
    # locate the service-manager program in executable position (head-agnostic).
    svc_idx = next((i for i, st in exec_toks
                    if os.path.basename(_strip_quotes(st)) in _SERVICE_MANAGER_PROGRAMS),
                   None)
    if svc_idx is None:
        return False
    # the manager's OWN argv: the original tokens FROM the program token onward
    # (mirrors P2's `rest`, but reached behind any wrapper). The program token
    # itself is included; verb/unit are matched only within this window.
    own = tokens[svc_idx:]
    own_bases = [os.path.basename(_strip_quotes(t)) for t in own]
    if not any(v in own_bases for v in SERVICE_VERBS):
        return False
    joined = " " + " ".join(_strip_quotes(t) for t in own) + " "
    for s in services:
        rx = re.compile(r"(^|[\s=])" + re.escape(s) + r"(@[^\s.=/]*)?(\.service)?(\s|$|\.|=)")
        if rx.search(joined):
            return True
    return False


# Recursive / all-workspace flags that fan a build into EVERY workspace (incl.
# the protected one) — their presence VOIDS any non-protected-selector exemption.
_RECURSIVE_WS_FLAGS = frozenset({"-r", "--recursive"})


def _anchor_nonprotected_workspace_selector(tokens: list, cfg: dict) -> bool:
    """True if a workspace selector names a workspace in the KNOWN non-protected
    set and NONE names a protected one AND no recursive/glob/multi selector is
    present. Used by the build anchor to exempt an explicit non-protected
    workspace build from the cwd-based fallback. A RECURSIVE (`-r`/`--recursive`),
    GLOB (`--filter '*'` / `...`), or MULTI selector fans into EVERY workspace
    (incl. the protected one) and therefore does NOT exempt (codex finding 5).
    """
    non_prot = set(cfg.get("non_protected_workspaces", []))
    prot = set(cfg.get("protected_build_workspaces", []))
    if not non_prot:
        return False
    sel_keywords = ("workspace", "workspaces")
    sel_flags = ("-w", "--workspace", "--filter", "-F")
    found_nonprot = False
    sel_count = 0
    for i, raw in enumerate(tokens):
        st = _strip_quotes(raw)
        # a recursive/all-workspace flag voids the exemption (fans into protected)
        if st in _RECURSIVE_WS_FLAGS:
            return False
        sel = None
        sel_raw = None
        if st in sel_keywords and i + 1 < len(tokens):
            sel_raw = _strip_quotes(tokens[i + 1])
        elif st in sel_flags and i + 1 < len(tokens):
            sel_raw = _strip_quotes(tokens[i + 1])
        else:
            for f in sel_flags:
                if st.startswith(f + "="):
                    sel_raw = _strip_quotes(st.split("=", 1)[1])
                    break
        if sel_raw is None:
            continue
        sel_count += 1
        # a glob / wildcard selector fans broadly -> not a determinate single ws
        if any(ch in sel_raw for ch in ("*", "?", "{", "}", "...")):
            return False
        sel = os.path.basename(sel_raw.rstrip("/"))
        if sel in prot:
            return False  # an explicit protected selector → not exempt
        if sel in non_prot:
            found_nonprot = True
        elif sel:
            # an UNKNOWN selector (neither protected nor known-non-protected)
            # cannot be proven non-protected -> do not exempt (fail closed).
            return False
    # exactly one determinate non-protected selector -> exempt; multiple selectors
    # (potentially fanning into protected) -> do NOT exempt.
    return found_nonprot and sel_count == 1
