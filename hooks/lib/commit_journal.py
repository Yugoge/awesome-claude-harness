#!/usr/bin/env python3
"""Commit-event journal — a hook-written witness correlating a session to a resulting commit sha.

WHY THIS EXISTS
---------------
The push-gate token authorizes `/push`. It is normally written by the changelog-analyst
AGENT immediately after the agent's own commit, so its credibility is TEMPORAL: it
witnesses an event the writer had just performed, inside the same critical section.

Push-gate reconciliation (agents/changelog-analyst.md) needs to write a missing token for
a commit that ALREADY sits at HEAD. At that later moment the event is over, and the only
surviving artifact is the commit object — which is written by the very actor whose
identity is in question. Attribution inferred from the commit message body or its file
set therefore reads actor-chosen content and is worthless: both are free variables for
whoever made the commit, and, worse, two fan-out lanes of one task routinely produce
prefix-related task ids and overlapping file sets, so the inference misfires by ACCIDENT
and not only under attack.

This journal is the missing record: it is written by the PostToolUse hook layer at the
moment `git commit` returns, and it is keyed on fields that live OUTSIDE the commit
object — HEAD as observed by the hook after the commit, and session ids drawn from the
hook payload, the hook's environment, and the commit grant. HEAD-as-observed is beyond
the committing actor's authorship; the session ids are not all — the append_commit_event
docstring states exactly which candidates the actor can influence, and when. It is
appended only when the commit was authorized by a single-use commit grant (see
`scripts/write-commit-grant.py`), so it witnesses grant-authorized `/commit` commits only;
bulk/auto-bulk commits carry a multi-use sentinel instead of a grant, produce no grant
pointer, and are therefore never journaled — and consequently never reconcilable.

WHAT THIS IS NOT
----------------
This is NOT an authorization boundary, and it must never be described as one. No hook
guards `/tmp/agentic-commit/**`, and `hooks/push.sh` authorizes purely on
`token.commit_sha == HEAD`. An adversary who can emit arbitrary Bash (THREAT-MODEL §1.2)
can therefore write the push-gate token directly and open the gate, which is strictly
cheaper than forging a journal entry. The journal accordingly grants an attacker NO new
capability; what it does is remove every dependence on actor-chosen content, which
eliminates the coincidental mis-attribution that the message/file-set heuristics allowed.
Read `docs/THREAT-MODEL.md` before strengthening any claim in this docstring.

FAIL-OPEN CONTRACT
------------------
`append_commit_event` must NEVER raise and must NEVER block a commit: it is called from a
PostToolUse hook that runs after the commit has already landed. Every failure mode
(unreadable grant, git timeout, unwritable /tmp) degrades to "no entry written", which
fail-CLOSES reconciliation (no entry => no attribution => no token) without affecting the
commit itself.
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

SCHEMA = "commit-event/1"

# Journal root. Shares the /tmp/agentic-commit/ family with the push-gate token and the
# Phase 3 commit locks, so a single tmp sweep clears the whole coordination surface.
JOURNAL_ROOT = "/tmp/agentic-commit/commit-events"

# Bound the file so a long-lived machine cannot grow it without limit. The journal is a
# lookup-by-HEAD structure, not an audit log of record — only the newest entries can ever
# match a live HEAD, so truncating the oldest is lossless in practice.
MAX_ENTRIES = 500

# Session-id placeholders that identify NOTHING. Both producers have their own fallback
# for "no session id in the environment" (`unknown` in changelog-analyst, `default` in the
# posttool hook), and an empty string is always possible. These must never participate in
# the membership test: if they did, two unrelated sessions that both lack the env vars
# would mutually attribute each other's commits — recreating by accident exactly the
# coincidental mis-attribution this journal exists to remove.
NON_IDENTIFYING = frozenset({"", "unknown", "default", "any", "none", "null"})


def repo_hash(repo_root):
    """sha256(realpath(repo_root))[:16] — the canonical repo-hash algorithm.

    Identical to the derivation `/commit` and `/push` already share for the push-gate
    token path (agents/changelog-analyst.md "Algorithm is canonical"), so a journal file
    and a token directory for the same repository agree on their key.
    """
    return hashlib.sha256(
        os.path.realpath(repo_root).encode("utf-8", "surrogateescape")
    ).hexdigest()[:16]


def journal_path(repo_root):
    """Absolute path of the journal file for one repository."""
    return os.path.join(JOURNAL_ROOT, repo_hash(repo_root) + ".jsonl")


def _identifying(values):
    """Deduplicated, order-preserving list of session ids that actually identify someone."""
    out = []
    for value in values:
        text = (value or "").strip()
        if text and text.lower() not in NON_IDENTIFYING and text not in out:
            out.append(text)
    return out


def _git_head(repo_root):
    """`git -C repo_root rev-parse HEAD`, or '' on any error. Never raises."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return ""
        return (result.stdout or "").strip()
    except Exception:
        return ""


def _prune(path):
    """Truncate the journal to the newest MAX_ENTRIES lines. Best-effort, never raises."""
    try:
        with open(path, "r") as handle:
            lines = handle.readlines()
        if len(lines) <= MAX_ENTRIES:
            return
        with open(path, "w") as handle:
            handle.writelines(lines[-MAX_ENTRIES:])
    except Exception:
        pass


def append_commit_event(grant, payload_session_id):
    """Record one grant-authorized commit. Returns the entry dict, or None if not recorded.

    `grant` is the parsed single-use commit grant that the privilege guard validated for
    this `git commit` (it supplies task_id, repo_root, branch and the pre-commit
    expected_head). `payload_session_id` is the session id the calling hook resolved for
    this PostToolUse event — see below for exactly what that resolution is.

    PRECISION ON WHAT IS AUTHORED, because `session_ids[]` — not `payload_session_id` alone
    — is what the matcher below searches, and the candidates do not have the same
    properties:

      - `payload_session_id` is whatever the caller passes. The one live caller
        (hooks/posttool-allowlist-consume.py) passes the PostToolUse payload's
        `session_id` when the payload carries one — harness-supplied in that case only —
        and otherwise falls back to `CLAUDE_SESSION_ID` from its own environment (the
        placeholder `default` when that is unset too). So this member is beyond the
        committing agent's authorship exactly when the payload actually carried it; on the
        fallback path it is as environment-derived as the next two.
      - `CLAUDE_CODE_SESSION_ID` / `CLAUDE_SESSION_ID` are read from the agent's own
        environment.
      - `grant["sid"]` originates from the grant, whose `--sid` is CLI-supplied at mint time.

    All four are CANDIDATES, considered because an orchestrator and its subagent
    legitimately carry different ids for one logical session, and keying on a single one
    would refuse legitimate matches (see the divergence check in the test module). What is
    RECORDED is the subset `_identifying` leaves standing: placeholder values
    (NON_IDENTIFYING) are dropped and duplicates collapse to their first occurrence, so
    `session_ids[]` holds anywhere from zero to four entries whose membership depends on
    the inputs — and the zero case aborts the write below rather than record an
    unmatchable entry. The consequence must be stated rather than glossed: membership in
    `session_ids[]` is NOT unforgeable against an actor that can influence every candidate
    the harness did not pin. That is the same NON-REGRESSION position taken for the
    journal as a whole — forging this is strictly more expensive than writing the
    push-gate token directly, so it confers no new capability — and it is likewise NOT a
    soundness claim. Do not restate this array as proof of identity.

    NEVER raises: every failure path returns None, leaving reconciliation with no
    attribution rather than leaving the commit in any way affected.
    """
    try:
        if not isinstance(grant, dict):
            return None
        repo_root = (grant.get("repo_root") or "").strip()
        task_id = (grant.get("task_id") or "").strip()
        if not repo_root or not task_id or not os.path.isdir(repo_root):
            return None

        resulting_head = _git_head(repo_root)
        if not resulting_head:
            return None

        entry = {
            "schema": SCHEMA,
            "event": "commit",
            "task_id": task_id,
            "repo_root": os.path.realpath(repo_root),
            "branch": (grant.get("branch") or "").strip(),
            # expected_head is the grant's pre-commit HEAD binding, already enforced by the
            # privilege guard before the commit ran, so it is the true parent here.
            "parent_head": (grant.get("expected_head") or "").strip(),
            "resulting_head": resulting_head,
            "session_ids": _identifying(
                [
                    payload_session_id,
                    os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
                    os.environ.get("CLAUDE_SESSION_ID", ""),
                    grant.get("sid", ""),
                ]
            ),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if not entry["session_ids"]:
            # Nothing identifying to key on — an entry written now could only ever be
            # matched by an equally anonymous reader. Fail closed instead.
            return None

        path = journal_path(repo_root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Single O_APPEND write of one line: concurrent writers interleave whole lines
        # rather than corrupting each other.
        with open(path, "a") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        _prune(path)
        return entry
    except Exception:
        return None


def find_attributable_event(repo_root, head_sha, task_id, session_id):
    """Return the newest journal entry attributing `head_sha` to this task+session, else None.

    ALL of the following must hold; there is no partial credit and no fallback tier:
      - the entry carries the current SCHEMA and is a commit event
      - its repo_root resolves to the same directory as `repo_root`
      - its resulting_head equals `head_sha` EXACTLY (this is the freshness bind: a commit
        that has since been built upon no longer sits at HEAD and stops matching)
      - its task_id equals `task_id`
      - `session_id` is a member of its recorded, identifying session_ids

    Deliberately absent: any cross-session tier. A session that did not create the commit
    cannot attribute it here — see agents/changelog-analyst.md for the named residual that
    this refusal accepts, and why a task-id-only tier was rejected as forgeable.
    """
    try:
        wanted = (session_id or "").strip()
        if not wanted or wanted.lower() in NON_IDENTIFYING:
            return None
        path = journal_path(repo_root)
        if not os.path.isfile(path):
            return None
        target_root = os.path.realpath(repo_root)
        match = None
        with open(path, "r") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if not isinstance(entry, dict):
                    continue
                if entry.get("schema") != SCHEMA or entry.get("event") != "commit":
                    continue
                if entry.get("resulting_head") != head_sha:
                    continue
                if entry.get("task_id") != task_id:
                    continue
                if os.path.realpath(entry.get("repo_root") or "/nonexistent") != target_root:
                    continue
                if wanted not in _identifying(entry.get("session_ids") or []):
                    continue
                match = entry  # last match wins: newest entry for this HEAD
        return match
    except Exception:
        return None


def _main(argv):
    """CLI used by changelog-analyst to test attribution before reconciling.

    Usage:
      commit_journal.py query --repo-root R --head SHA --task-id T --session-id S

    Exit 0 and print the matching entry as JSON when the commit at `--head` is
    attributable; exit 1 and print nothing when it is not. Any other exit code means the
    query itself failed and MUST be treated as "not attributable".
    """
    if len(argv) < 2 or argv[1] != "query":
        print("usage: commit_journal.py query --repo-root R --head SHA "
              "--task-id T --session-id S", file=sys.stderr)
        return 2
    args = {}
    rest = argv[2:]
    for index in range(0, len(rest) - 1, 2):
        args[rest[index].lstrip("-").replace("-", "_")] = rest[index + 1]
    for required in ("repo_root", "head", "task_id", "session_id"):
        if not args.get(required):
            print("missing --" + required.replace("_", "-"), file=sys.stderr)
            return 2
    entry = find_attributable_event(
        args["repo_root"], args["head"], args["task_id"], args["session_id"]
    )
    if entry is None:
        return 1
    print(json.dumps(entry, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
