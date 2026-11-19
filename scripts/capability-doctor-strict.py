#!/usr/bin/env python3
"""`doctor --strict` implementation: fresh handshake + short compatibility report.

Two properties this file exists to guarantee:

  1. EVERY invocation starts a FRESH live-host handshake with a new nonce. A
     preseeded or cached PASS is never accepted as proof — it is overwritten by
     the PENDING that opens the fresh run, which is asserted, not assumed.
  2. It is an INDEPENDENT enforcement point. It reads and validates the state
     file in-process and never depends on hook dispatch, so it still refuses on a
     host that silently no-ops PreToolUse (and therefore no-ops the gate hook).

Brevity bound: the DEFAULT report is capped at 20 lines — one line per lifecycle
event (7), one aggregate verdict line, and actionable reasons only for FAILING
components. Full per-check detail moves behind --verbose; the information is
relocated, never lost.

`--route <route>` is the third mode and the PREFLIGHT callsite: it evaluates one
route through the independent consumer and returns its decision, without running
a handshake. This is the supported way for a protected-workflow entrypoint to
reach `evaluate_activation()` without hook dispatch, and is the value of the
manifest's `independent_enforcement_callsite` field.

Three results, never more. PASS certifies only what this run MEASURED:

  PASS               every check was measured here and passed. On this tree that is
                     not reachable yet: blocking capability and the four deep checks
                     have no probe, so they are always "not provable here".
  FAIL               a check was measured here and failed: a lifecycle event with no
                     receipt whose canary no settings layer this run reads registers
                     (named), a canary that fired on another host event
                     (misregistered), a receipt that failed an identity or session
                     cross-check, or an unusable binding.
  NOT_PROVABLE_HERE  nothing failed, but at least one check could not be measured
                     from where doctor runs. Each such check is named, with the one
                     action that would prove it. Never reported as PASS or FAIL.

A live receipt that passes every cross-check AND whose host event name matches its
label is taken as proof the event is wired, wherever the registration lives (a
layer this run does not read: managed settings, a plugin). Doctor cannot tell host
dispatch from a hand-run canary; the handshake names that residual too. A receipt
whose host event name differs from its label is a misregistration (FAIL); one with
no host event name still needs a registration in a layer this run reads. A receipt that arrived but is not tied to
this window (the run's nonce is not in that session's transcript, or the
transcript did not change in the window) proves nothing either way, so it is
NOT_PROVABLE_HERE, not FAIL. The state file the run
writes, and therefore every --route decision, is exactly what the handshake
produces; the three-way result is a reading of it, not a new input to it.

Usage: capability-doctor-strict.py [--home <dir>] [--session-id <id>] [--timeout <s>] [--verbose]
       capability-doctor-strict.py --route <route> [--home <dir>] [--session-id <id>]
Session id: --session-id, else CLAUDE_CODE_SESSION_ID, else CLAUDE_SESSION_ID, else
            a synthetic noninteractive-<pid>.
Exit codes: 0 = PASS (under --route: PERMIT);
            1 = FAIL (under --route: REFUSE);
            3 = --route only: NOT_PROTECTED, i.e. the route is outside the
                protected surface. Distinct from 0 so a mistyped route cannot be
                misread as approval;
            4 = NOT_PROVABLE_HERE (never under --route; an empty --route is a
                route like any other, outside the protected surface, so exit 3).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_HOME = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HOME / "hooks" / "lib"))
sys.path.insert(0, str(_HOME / "scripts"))

import capability_state as cs  # noqa: E402

MAX_DEFAULT_LINES = 20

PASS, FAIL, NOT_PROVABLE = "PASS", "FAIL", "NOT_PROVABLE_HERE"
EXIT_CODES = {PASS: 0, FAIL: 1, NOT_PROVABLE: 4}
CANARY = "capability-canary.py"
# Cross-check failures that say only that the receipt is not bound to THIS window,
# not that the host misidentified the event or the session. Not a measurement.
WINDOW_REASONS = ("transcript_missing_run_nonce", "transcript_mtime_stale")
NO_SESSION = "<a running session's id>"
# The in-session proof of the session's own PreToolUse/PostToolUse. The harness's
# hooks/pretool-block-background-tasks.py refuses the main agent a background Bash
# unless /do consent holds this turn, and a background task a subagent starts dies
# with that subagent before the nonce reaches the main transcript, so /do is the
# one route that works. hooks/tests pins this exact call against that hook.
IN_SESSION_COMMAND = "scripts/doctor --strict --timeout 60"
IN_SESSION_ACTION = (f"type /do in this session, then have it run `{IN_SESSION_COMMAND}` as a "
                     "background task and read its output once while it waits (without /do "
                     "the harness refuses a background task)")
DEEP_ACTIONS = {
    "identity_propagation": "a probe following a real subagent's host-issued identity across live callbacks",
    "permission_deny": "a probe with an actually-denied operation and an allowed control, both live",
    "hook_ordering": "a probe of the five ordering properties under live dispatch",
    "model_invocation_restriction": "a probe of model-originated Skill and SlashCommand calls "
                                    "against a human-only command",
}


def canary_registrations(home, project: Path | None = None) -> dict[str, list[str]]:
    """{event: [settings layer, ...]} for every layer that registers the canary
    under that event key with that event as its label argument.

    Read in-process from the settings files; no hook is dispatched. A registration
    under the wrong key, or with the wrong label, would deliver a receipt the
    handshake rejects, so it does not count as wired.
    """
    out: dict[str, list[str]] = {}
    for layer in settings_layers_read(home, project):
        settings, _err = cs.load_settings(layer)
        hooks = (settings or {}).get("hooks") or {}
        for event in cs.RELIED_UPON_EVENTS:
            for group in hooks.get(event) or []:
                for h in (group.get("hooks") if isinstance(group, dict) else None) or []:
                    cmd = str((h or {}).get("command") or "") if isinstance(h, dict) else ""
                    tokens = [t for t in re.split(r"[\s'\"]+", cmd) if t]
                    idx = next((i for i, t in enumerate(tokens) if t.endswith(CANARY)), None)
                    if idx is not None and event in tokens[idx + 1:]:
                        out.setdefault(event, []).append(str(layer))
    return out


def _transcript_cwd(sid: str | None) -> Path | None:
    """The working directory a session's own transcript records, or None."""
    if not sid:
        return None
    from subagent_restart import config_projects  # every configuration directory named, not only the caller's
    try:
        for tp in (t for root in config_projects() for t in root.glob(f"*/{sid}.jsonl")):
            with open(tp, encoding="utf-8", errors="replace") as fh:
                for _ in range(200):
                    line = fh.readline()
                    if not line:
                        break
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict) and isinstance(rec.get("cwd"), str):
                        return Path(rec["cwd"])
    except OSError:
        return None
    return None


def _project_root(start: Path, exclude: tuple = ()) -> Path | None:
    """Nearest ancestor of `start` (itself included) holding .claude/settings*.json,
    else the git toplevel above it, else None. A directory in `exclude` (the user's
    HOME, the harness home) is never taken as the project, and the walk does not
    pass a git toplevel."""
    skip = {os.path.realpath(x) for x in exclude}
    for d in (start, *start.parents):
        is_git = (d / ".git").exists()
        if os.path.realpath(d) in skip:
            if is_git:
                return None
            continue
        if (d / ".claude" / "settings.json").is_file() or \
                (d / ".claude" / "settings.local.json").is_file():
            return d
        if is_git:
            return d
    return None


def resolve_project(real_sid: str | None, probing_other: bool, home: Path) -> Path | None:
    """The session's project directory, or None when it cannot be known.

    Order: the cwd the probed session's own transcript records (a recorded cwd that
    no longer exists leaves the project unknown); then, only when doctor does not
    probe another session, CLAUDE_PROJECT_DIR and the nearest project root above
    doctor's own working directory, never the user's HOME or the harness home, so
    a run's verdict does not depend on where it runs. A deleted working directory
    is skipped, never a crash."""
    tcwd = _transcript_cwd(real_sid)
    if tcwd is not None:
        if not tcwd.is_dir():
            return None
        return _project_root(tcwd) or tcwd
    if probing_other:
        return None
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    try:
        cwd = Path(os.getcwd())
    except OSError:
        return None
    return _project_root(cwd, exclude=(Path.home(), home))


def settings_layers_read(home, project: Path | None) -> list:
    """The settings files the registration read covers: the harness home's layers
    (cs.SETTINGS_LAYERS), the home's .claude/settings.json, and, when the session's
    project is known, its two .claude layers. Managed settings and plugins are not
    read; a receipt whose host event name matches proves those."""
    layers = [home / layer for layer in cs.SETTINGS_LAYERS]
    layers.append(home / ".claude" / "settings.json")
    if project is not None:
        layers += [project / ".claude" / "settings.json",
                   project / ".claude" / "settings.local.json"]
    seen, out = set(), []
    for layer in layers:
        key = os.path.realpath(layer)
        if key not in seen:
            seen.add(key)
            out.append(layer)
    return out


def _event_actions(in_session: bool, sid: str | None) -> dict[str, str]:
    """The one proving action per event. `sid` is None when no real session id is
    known (a terminal run without --session-id); no synthetic id is ever printed."""
    if sid is None:
        rerun = (f"rerun doctor --strict inside a session ({IN_SESSION_ACTION}), or with "
                 f"--session-id {NO_SESSION} --timeout 120")
        return {label: rerun for label in cs.RELIED_UPON_EVENTS}
    nonce = "; the probe-open line must reach that session's transcript inside the window"
    tool = (IN_SESSION_ACTION if in_session
            else "have that session run one tool call that prints the probe-open line")
    return {
        "SessionStart": f"resume that session (claude --resume {sid}) while the probe is open{nonce}",
        "UserPromptSubmit": "send that session the probe-open line as one prompt while the "
                            "probe is open",
        "PreToolUse": tool,
        "PostToolUse": tool,
        "Notification": "let that session raise one notification (a permission prompt) "
                        f"while the probe is open{nonce}",
        "Stop": f"let one turn of that session end while the probe is open{nonce}",
        "SubagentStop": "have that session run one subagent to completion while the probe "
                        f"is open{nonce}",
    }


def classify(state: dict, registrations: dict[str, list[str]], in_session: bool,
             sid: str | None, project_known: bool = True, project_desc: str = "") -> list[dict]:
    """One record per check: {check, result, detail}. `detail` is the failure
    reason for FAIL and the proving action for NOT_PROVABLE_HERE."""
    checks: list[dict] = []
    binding = state.get("binding") or {}
    breason = cs.binding_failure(binding)
    if breason:
        checks.append({"check": "binding", "result": FAIL, "detail": breason})

    actions = _event_actions(in_session, sid)
    by_label = {e.get("event_label"): e for e in state.get("events") or []}
    for label in cs.RELIED_UPON_EVENTS:
        ev = by_label.get(label) or {}
        reason = ev.get("failure_reason")
        hen = (ev.get("host_receipt") or {}).get("hook_event_name")
        host_named = bool(hen) and hen != cs.ABSENT
        unknown = (f"the session's project is not known here (layers read: {project_desc})"
                   if not project_known else "")
        arrived = bool(ev.get("host_receipt")) and reason != "missing_event_record"
        if arrived and host_named and hen != label:
            # The canary for `label` ran on another host event: a registration under
            # the wrong key, whatever its nonce says.
            res, detail = FAIL, f"misregistered: {label} canary fired on {hen}"
        elif ev.get("outcome") == "PASS":
            if host_named or label in registrations:
                # Host event name matches (checked above), or a read layer registers it.
                res, detail = PASS, ""
            else:
                res, detail = NOT_PROVABLE, ("receipt names no host event and no read layer "
                                             f"registers it; proves it: {actions[label]}")
        elif not arrived:
            if label in registrations:
                res, detail = NOT_PROVABLE, f"no receipt in this window; proves it: {actions[label]}"
            elif not project_known and not registrations:
                # Nothing read wires the canary at all: the wiring may live in the
                # unknown project's layers, so absence here proves nothing.
                res, detail = NOT_PROVABLE, (f"no receipt, and {unknown}; proves it: "
                                             f"{actions[label]}")
            elif not project_known:
                # The layers read wire the canary for other events but not this one:
                # a partial wiring, measured where doctor reads, whatever the cwd.
                res, detail = FAIL, (f"not_wired: no receipt, and the layers read ({project_desc}) "
                                     f"register the {CANARY} for other events but not {label}")
            else:
                res, detail = FAIL, (f"not_wired: no receipt, and no {CANARY} {label} "
                                     f"registration in the settings layers read ({project_desc})")
        elif reason in WINDOW_REASONS:
            res, detail = NOT_PROVABLE, (f"receipt not tied to this window ({reason}); "
                                         f"proves it: {actions[label]}")
        else:
            res, detail = FAIL, str(reason)
        checks.append({"check": label, "result": res, "detail": detail})

    events = list(by_label.values())
    if (events and all(e.get("blocking_action") in cs.BLOCKING_OUTCOMES_OK for e in events)
            and any(e.get("blocking_action") == "blocked_confirmed" for e in events)):
        checks.append({"check": "blocking", "result": PASS, "detail": ""})
    else:
        checks.append({"check": "blocking", "result": NOT_PROVABLE,
                       "detail": "not measured by any run yet; proves it: a denied/allow-control "
                                 "sentinel pair probe, which this handshake does not run"})

    deep = state.get("deep_checks") or {}
    for name in cs.DEEP_CHECKS:
        rec = deep.get(name) or {}
        statuses = [rec.get("status")]
        if name == "hook_ordering":
            props = rec.get("properties") or {}
            statuses += [(props.get(p) or {}).get("status") for p in cs.ORDERING_PROPERTIES]
        if all(st == "pass" for st in statuses):
            checks.append({"check": name, "result": PASS, "detail": ""})
        elif any(st not in ("pass", "unsupported_self_check", None) for st in statuses):
            checks.append({"check": name, "result": FAIL, "detail": "deep_check_failed"})
        else:
            checks.append({"check": name, "result": NOT_PROVABLE,
                           "detail": f"proves it: {DEEP_ACTIONS[name]}, which this handshake "
                                     "does not run yet"})

    surface = state.get("status_surface") or {}
    if surface.get("status") == "observed":
        checks.append({"check": "status-surface", "result": PASS, "detail": ""})
    else:
        checks.append({"check": "status-surface", "result": NOT_PROVABLE,
                       "detail": "proves it: run doctor --strict inside tmux with the harness "
                                 "status line on screen"})
    return checks


def overall_result(checks: list[dict], state: dict) -> tuple[str, str | None]:
    """FAIL beats NOT_PROVABLE_HERE beats PASS. PASS additionally requires the
    handshake's own aggregate PASS, so a check this reading does not know about
    can never be waved through."""
    if any(c["result"] == FAIL for c in checks):
        return FAIL, next(c["check"] for c in checks if c["result"] == FAIL)
    if any(c["result"] == NOT_PROVABLE for c in checks):
        return NOT_PROVABLE, None
    if state.get("overall") != "PASS":
        return FAIL, state.get("failure_reason") or "aggregate_not_pass"
    return PASS, None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--home", default=None)
    ap.add_argument("--session-id", default=None)
    ap.add_argument("--verbose", action="store_true",
                    default=os.environ.get("STRICT_VERBOSE") == "1")
    ap.add_argument("--timeout", type=int, default=5)
    ap.add_argument("--route", default=None,
                    help="preflight one route through the independent consumer and exit; "
                         "runs no handshake and writes no state")
    args = ap.parse_args(argv)

    home = cs.harness_home(args.home)
    real_sid = args.session_id or cs.ambient_session_id() or None
    session_id = real_sid or f"noninteractive-{os.getpid()}"
    # Where doctor runs decides only the WORDING of a proving action, never a result.
    in_session = bool(cs.ambient_session_id()) and session_id == cs.ambient_session_id()
    state_file = cs.state_path(session_id)

    # PREFLIGHT MODE — the entrypoint-side, non-hook-dispatched callsite. It reads
    # state rather than producing it, so a protected workflow can consult the
    # handshake without the 25s cost of a fresh run and without overwriting a PASS
    # that another consumer is relying on.
    if args.route is not None:
        rec = cs.evaluate_activation(args.route, home=home, session_id=session_id,
                                     state_file=state_file, component="preflight_consumer")
        print(json.dumps(rec, indent=1, sort_keys=True))
        # NOT_PROTECTED gets its own exit code rather than sharing 0 with PERMIT.
        # An entrypoint asserting "I am /dev" that fat-fingers its route string
        # would otherwise read a silent 0 as approval, when what actually happened
        # is that the gate never recognised the route at all.
        if rec["decision"] == "PERMIT":
            return 0
        return 3 if rec["decision"] == "NOT_PROTECTED" else 1

    # Assert-not-assume: record whether a preseeded PASS existed, then run fresh
    # anyway. The fresh run's PENDING write is what actually invalidates it.
    preseeded, _ = cs.load_state(state_file)
    preseeded_status = (preseeded or {}).get("status")

    # The orchestrator's filename is hyphenated, so load it by path rather than
    # by import name.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "capability_handshake", home / "scripts" / "capability-handshake.py")
    hs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hs)

    def _announce(st: dict) -> None:
        # stderr, so the short stdout report keeps its bound. This line is how a
        # session proves its own PreToolUse/PostToolUse: reading it from a
        # background run is a tool call inside the window, and its result puts
        # the nonce in the transcript (cross-check 4).
        sys.stderr.write(f"probe open: session={real_sid or 'none'} run={st['run_id']} "
                         f"nonce={st['nonce']} window={args.timeout}s\n")
        sys.stderr.flush()

    state = hs.run_handshake(session_id, home, state_file, args.timeout, on_open=_announce)

    # INDEPENDENT consumer pass over every manifested route (no hook dispatch).
    manifest, merr = cs.load_manifest(home)
    consumer_records: list[dict] = []
    if not merr:
        for entry in manifest.get("routes", []):
            consumer_records.append(
                cs.evaluate_activation(entry.get("route", ""), home=home,
                                       session_id=session_id, state_file=state_file)
            )

    probing_other = bool(args.session_id) and args.session_id != cs.ambient_session_id()
    project = resolve_project(real_sid, probing_other, home)
    project_desc = (f"harness home and project {project}" if project is not None
                    else "harness home only")
    checks = classify(state, canary_registrations(home, project), in_session, real_sid,
                      project_known=project is not None, project_desc=project_desc)
    result, _first = overall_result(checks, state)
    code = EXIT_CODES[result]

    overall = state.get("overall")
    if args.verbose:
        print(json.dumps({
            "result": result,
            "exit_code": code,
            "checks": checks,
            "overall": overall,
            "failure_reason": state.get("failure_reason"),
            "fresh_run": {"run_id": state.get("run_id"), "nonce_prefix": str(state.get("nonce"))[:8],
                          "preseeded_status_ignored": preseeded_status},
            "binding": state.get("binding"),
            "events": state.get("events"),
            "deep_checks": state.get("deep_checks"),
            "status_surface": state.get("status_surface"),
            "independent_consumer": consumer_records,
        }, indent=1, sort_keys=True))
        return code

    lines: list[str] = []
    for c in checks:
        lines.append(f"{c['check']:<29}{c['result']:<18}{c['detail']}".rstrip())
    if any(c["result"] == NOT_PROVABLE and c["check"] in cs.RELIED_UPON_EVENTS for c in checks):
        lines.append(f"probe window: scripts/doctor --strict --session-id {real_sid or NO_SESSION} "
                     "--timeout 120 (its stderr 'probe open' line must reach that session's transcript)")
    b = state.get("binding") or {}
    lines.append(f"VERDICT {overall}  host={b.get('host_build')} harness={b.get('harness_version')}"
                 f"  reason={state.get('failure_reason') or 'none'}")
    named = [c["check"] for c in checks if c["result"] == result] if result != PASS else []
    lines.append(f"RESULT {result} (exit {code})" + (f": {', '.join(named)}" if named else ""))
    refused = [r for r in consumer_records if r.get("decision") == "REFUSE"]
    if refused:
        lines.append(f"independent-consumer: {len(refused)} manifested route(s) refused "
                     f"({refused[0].get('failure_reason')})")
    for line in lines[:MAX_DEFAULT_LINES]:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
