#!/usr/bin/env python3
"""Write-gate rule: Write never replaces an existing file; nothing writes the bulk-commit sentinel.

The Python form of hooks/pretool-write-guard.sh, decision for decision and message for
message (hooks/tests/test_write_gate_overwrite_parity.py runs both over one corpus).
It is a rule of hooks/pretool-write-gate.py, which runs it as ``__main__``; it can also
run alone. Exit 0 allows, exit 2 refuses with the reason on stderr.

1. Bulk-commit sentinel (every actor, the main agent included; no /do or /allow
   exemption): a Write or NotebookEdit whose target's name is
   ``claude-bulk-commit-sentinel-*.json`` is refused. Only the orchestrator's /commit
   --bulk route mints it. (The shell hook was registered on Write alone, so its
   NotebookEdit branch never ran; the gate gives this rule the same tool set.)
2. Every other check is for Write only.
3. /do consent (lib.allowlist.has_do_consent: the main agent, the flag holding true)
   allows the Write.
4. The main agent's /allow grant for Write: a grant that names this target allows it;
   a valid same-session grant that names another target refuses an overwrite of an
   existing file (CF-1) and leaves a new file's creation to step 6.
5. No target: allow (a parse problem never blocks).
6. The target is an existing file: refused, Edit it in place instead, unless
   overwrite_exempt() says the file is a scratch, temp or untracked generated output
   (OB-L46, owner decision). The exemption also answers step 4's CF-1 refusal, so a
   grant for another path never makes the rule stricter than no grant at all.

The OB-L46 exemption (overwrite_exempt) is judged on the file the Write lands on
(its realpath), in this order:

  a. Protected, whatever else holds:
     * harness state (lib/harness_temp_state.classify): every control location, and
       every scratch location but the agent scratch ones (claude-scratch, codex-outputs,
       the graphify cache); the rest (orchestrator outputs, runtime-guard stderr,
       checkpoint results, ...) are written and read back by harness processes;
     * a gate-read artifact: a file under a ``docs/dev/`` directory that is JSON/JSONL,
       lies in its ``specs/`` or ``overnight/`` subtree, or carries the name of a
       markdown family a gate or command parses (ticket-, user-requirement-,
       close-report-, completion-, ba-spec-, ba-panel-, overnight-summary-,
       overnight-log-, spec-);
     * outside a ``.claude/scratch/`` directory: any path with a ``.claude`` or ``.git``
       component (settings, hooks, commands, repository internals) and anything in the
       harness home (lib/claude_home.py);
     * a file git tracks (in the index) in the work tree that holds it, or one git cannot
       answer for.
  b. Exempt: scratch: an agent scratch location (a), this session's own scratch dir
     (<root>/<session_id>/ whose .owner names it, lib/scratch_owner.py), or a
     ``.claude/scratch/`` directory.
  c. Exempt: temp: a file whose realpath lies below a temp root (/tmp, /var/tmp,
     $TMPDIR, ...) and is not protected by (a).
  d. Exempt: an untracked generated output: a file inside a git work tree that git does
     not track (ignored or not: the harness ignores docs/*/), with no dot-named component
     below the work tree's top (so .env, .vscode/... stay protected).
  e. Anything else (outside a work tree, or git cannot answer): refused, as before.

The line between (d) and a gate-read artifact is the reader, not the writer: a role's
own draft (docs/dev/arch-probe.md, docs/codex/notes.md, build/out.txt) is read by no
gate, so replacing it wholesale damages nothing but the draft; a report, context, ticket
or spec under docs/dev/ is what a later gate trusts, so it keeps the Edit-only rule even
when untracked.

Why this split: the guard protects what a wholesale rewrite can silently damage for
someone else: tracked sources, configuration, and evidence another gate reads. A role's
own untracked output is its working draft; several roles (architect, product-owner,
changelog-analyst, push-analyst, merge-analyst, graphify, user) have Write but no Edit,
so for them a refused second Write was a dead end, not a nudge toward Edit.
"""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys

_HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _err(*lines: str) -> None:
    sys.stderr.write("".join(f"{line}\n" for line in lines))


def _shell_str(value) -> str:
    """What the shell hook's ``print(value)`` put into its variable (None prints "None")."""
    return "" if value == "" else str(value)


def _bulk_target(data: dict) -> str:
    try:
        ti = data.get("tool_input", {})
        return _shell_str(ti.get("file_path") or ti.get("notebook_path") or "")
    except Exception:
        return ""


def _field(data: dict, key: str) -> str:
    try:
        if key == "file_path":
            return _shell_str(data.get("tool_input", {}).get("file_path", ""))
        return _shell_str(data.get(key, ""))
    except Exception:
        return ""


def _consent(data) -> bool:
    try:
        sys.path.insert(0, os.path.join(_HOOKS_DIR, "lib"))
        from allowlist import has_do_consent
        return bool(has_do_consent(data))
    except BaseException:
        return False


def _sentinel(session_id: str, data_task_id: str, env_task_id: str, target: str) -> str:
    """'match', 'valid_no_match' or 'none' (and 'none' when the lookup fails)."""
    try:
        sys.path.insert(0, _HOOKS_DIR)
        from lib.allowlist import match_sentinel_grant_for_write, load_sentinel_grant_for_task
        writer_key = env_task_id if env_task_id else session_id
        seen, candidates = set(), []
        for k in (writer_key, data_task_id, session_id):
            if k and k not in seen:
                seen.add(k)
                candidates.append(k)
        any_valid = False
        for key in candidates:
            g = load_sentinel_grant_for_task(key)
            if g is None or g.get("session_id") != session_id:
                continue
            any_valid = True
            if match_sentinel_grant_for_write(key, session_id, target) is not None:
                return "match"
        return "valid_no_match" if any_valid else "none"
    except BaseException:
        return "none"


# OB-L46: which existing files a Write may replace (see the module docstring, a-e).
_GATE_READ_SUBTREES = ("specs", "overnight")
_GATE_READ_MD_PREFIXES = ("ticket-", "user-requirement-", "close-report-", "completion-",
                          "ba-spec-", "ba-panel-", "overnight-summary-", "overnight-log-",
                          "spec-")
_PROTECTED_COMPONENTS = (".claude", ".git")
# harness_temp_state scratch locations agents write their own output into. Its other
# scratch kinds (orchestrator outputs, runtime-guard stderr, checkpoint results, ...) are
# written by a harness process and read back by one, so they stay protected.
_AGENT_SCRATCH = ("claude-scratch", "codex-outputs", "graphify-cache")


def _temp_state():
    sys.path.insert(0, os.path.join(_HOOKS_DIR, "lib"))
    import harness_temp_state
    return harness_temp_state


def _is_gate_read_artifact(real: str) -> bool:
    parts = real.split(os.sep)
    for i in range(len(parts) - 2):
        if parts[i] == "docs" and parts[i + 1] == "dev":
            rel = parts[i + 2:]
            name = rel[-1]
            if name.endswith((".json", ".jsonl")):
                return True
            if len(rel) > 1 and rel[0] in _GATE_READ_SUBTREES:
                return True
            if name.startswith(_GATE_READ_MD_PREFIXES):
                return True
    return False


def _own_scratch(real: str, session_id: str) -> bool:
    if not session_id:
        return False
    try:
        sys.path.insert(0, os.path.join(_HOOKS_DIR, "lib"))
        from scratch_owner import owns_scratch_dir
    except BaseException:
        return False
    d = os.path.dirname(real)
    while d and d != os.sep:
        if os.path.basename(d) == session_id and owns_scratch_dir(d, session_id):
            return True
        d = os.path.dirname(d)
    return False


def _in_harness_home(real: str) -> bool:
    """True when `real` lies in the harness home (lib/claude_home.resolve), or the home
    cannot be resolved (then nothing is exempt by location there; refuse)."""
    try:
        sys.path.insert(0, os.path.join(_HOOKS_DIR, "lib"))
        from claude_home import resolve
        home = resolve()
    except BaseException:
        return True
    if home is None:
        return False
    root = os.path.realpath(str(home))
    return root != os.sep and (real == root or real.startswith(root + os.sep))


_NO_REPO = "no-repo"


# Two git calls at most, each well inside the rule's 5 s budget (lib/write_gate/__init__.py):
# an overrun of this fail-open rule would let the Write through, a git timeout here refuses.
_GIT_TIMEOUT = 2.0


def _git(cwd: str, *args: str):
    """(returncode, stdout, stderr), or (None, "", "") when git cannot run or times out."""
    try:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        p = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True,
                           timeout=_GIT_TIMEOUT, env=env)
        return p.returncode, p.stdout, p.stderr
    except BaseException:
        return None, "", ""


def _work_tree(real: str):
    """(top, tracked) for the git work tree holding `real`: (_NO_REPO, False) outside any
    work tree, (None, None) when git cannot answer (the caller then refuses)."""
    d = os.path.dirname(real)
    rc, out, err = _git(d, "rev-parse", "--is-inside-work-tree", "--show-toplevel")
    if rc is not None and rc != 0 and "not a git repository" in err:
        return _NO_REPO, False
    lines = out.splitlines()
    if rc != 0 or len(lines) < 2 or lines[0].strip() != "true":
        return None, None
    top = os.path.realpath(lines[1].strip())
    rc, out, _ = _git(d, "ls-files", "-z", "--", os.path.basename(real))
    if rc != 0:
        return None, None
    return top, bool(out.strip("\0"))


def _in_project_scratch(real: str) -> bool:
    """True below a ``.claude/scratch/`` directory (the roles' shared scratch prefix)."""
    parts = real.split(os.sep)
    return any(parts[i] == ".claude" and parts[i + 1] == "scratch"
               for i in range(len(parts) - 2))


def overwrite_exempt(file_path: str, session_id: str) -> bool:
    """True when the existing file `file_path` is a scratch, temp or untracked generated
    output a Write may replace (OB-L46). Any doubt answers False (the guard refuses)."""
    try:
        real = os.path.realpath(file_path)
        if not os.path.isfile(real):
            return False
        hts = _temp_state()
        loc = hts.classify(file_path)
        own = _own_scratch(real, session_id)
        if loc is not None and (loc.kind == hts.CONTROL
                                or (loc.name not in _AGENT_SCRATCH and not own)):
            return False
        if _is_gate_read_artifact(real):
            return False
        project_scratch = _in_project_scratch(real)
        if not project_scratch and (any(c in _PROTECTED_COMPONENTS for c in real.split(os.sep))
                                    or _in_harness_home(real)):
            return False
        top, tracked = _work_tree(real)
        if tracked is not False:
            return False
        if own or loc is not None or project_scratch:
            return True
        if hts.is_in_temp_root(real):
            return True
        if top == _NO_REPO:
            return False
        rel = os.path.relpath(real, top).split(os.sep)
        return rel[0] != os.pardir and not any(c.startswith(".") for c in rel)
    except BaseException:
        return False


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
        tool = _shell_str(data.get("tool_name", ""))
    except Exception:
        return 0

    if tool in ("Write", "NotebookEdit"):
        target = _bulk_target(data)
        if fnmatch.fnmatchcase(target, "*/claude-bulk-commit-sentinel-*.json"):
            _err(f"BLOCKED: bulk-commit-sentinel-write — writing to claude-bulk-commit-sentinel-*.json via {tool} is FORBIDDEN",
                 f"Target: {target}",
                 "REASON: per task 20260524-205206 M4.3, only the orchestrator via /commit --bulk may",
                 "        create the bulk-commit sentinel. ALL model tool calls are denied",
                 "        regardless of agent_id (main agent and subagent equally blocked).")
            return 2

    if tool != "Write":
        return 0

    file_path = _field(data, "file_path")
    task_id = _field(data, "task_id")
    env_task_id = os.environ.get("CLAUDE_TASK_ID", "")

    if _consent(data):
        return 0
    if not data.get("agent_id"):
        sid = _shell_str(data.get("session_id", "") or os.environ.get("CLAUDE_SESSION_ID", "default")) or "default"
        result = _sentinel(sid, task_id, env_task_id, file_path)
        if result == "match":
            return 0
        if (result == "valid_no_match" and os.path.isfile(file_path)
                and not overwrite_exempt(file_path, sid)):
            _err("[Write Guard] BLOCKED: sentinel grant does not cover this target.",
                 f"Target: {file_path}",
                 "A valid sentinel grant exists for this task, but it does NOT name this file,",
                 "so it confers no permission to overwrite it. The grant is scoped on purpose:",
                 "an approval for one path is not an approval for every path.",
                 "Two ways forward:",
                 "  1. Re-issue the grant naming this exact path, if overwriting it is genuinely intended.",
                 "  2. Modify the existing file in place (Edit) instead of replacing it wholesale.")
            return 2

    if not file_path:
        return 0
    session_id = _shell_str(data.get("session_id", "") or os.environ.get("CLAUDE_SESSION_ID", ""))
    if os.path.isfile(file_path) and not overwrite_exempt(file_path, session_id):
        _err(f"[Write Guard] BLOCKED: File already exists: {file_path}",
             "Write would replace this file wholesale, so every byte of the new content has to be",
             "reproduced from memory. Any field you forgot to carry over, or mis-remembered, would be",
             "silently lost — there is no diff to reveal what went missing.",
             "Modify the existing file IN PLACE instead (Edit), changing only the fields that need to",
             "change. Reserve Write for files that genuinely do not exist yet.")
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
