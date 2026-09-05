#!/usr/bin/env python3
"""Commit-event journal — a hook-written witness correlating a session to a resulting commit sha.

WHY THIS EXISTS
---------------
The push-gate token authorizes `/push`. It is normally written by the changelog-analyst
AGENT just after the agent's own commit, so its credibility is TEMPORAL: it witnesses an
event the writer had itself just performed. Not atomically with it, though — Phase 10
step 6 writes the token AFTER the fd-9 commit flock is released, which is exactly why
changelog-analyst carries a `push_gate_race` failure code for HEAD moving in that gap.

Push-gate reconciliation (agents/changelog-analyst.md) needs to write a missing token for
a commit that ALREADY sits at HEAD. At that later moment the event is over, and the only
surviving artifact is the commit object — which is written by the very actor whose
identity is in question. Attribution inferred from the commit message body or its file
set therefore reads actor-chosen content and is worthless: both are free variables for
whoever made the commit, and, worse, two fan-out lanes of one task routinely produce
prefix-related task ids and overlapping file sets, so the inference misfires by ACCIDENT
and not only under attack.

This journal is the missing record: it is written by the PostToolUse hook layer, and it is
keyed on fields that live OUTSIDE the commit object — HEAD as observed by the hook after
the commit, and session ids drawn from the hook payload, the hook's environment, and the
commit grant.

WHEN IT IS WRITTEN, stated exactly, because two claims here used to overstate it. The entry
is NOT written at the moment `git commit` returns: PostToolUse fires once the committing
shell call has EXITED, which is also when the Phase 3 commit lock is released, and the hook
then reads LIVE HEAD. A peer commit landing in that window is recorded as this session's
`resulting_head` while `parent_head` still holds this session's own grant's pre-commit head
— one entry naming two DIFFERENT commits. So the observed HEAD is beyond the committing
actor's authorship only in the narrow sense that the actor does not write it into the commit
object; it is NOT guaranteed to be that actor's own commit. Nothing here can tell the
difference, so the gap is closed at MATCH time instead: `_parent_linkage_verified` refuses
any entry whose recorded parent is not the actual first parent of its recorded sha. The
session ids are likewise not all beyond the actor — the append_commit_event docstring states
exactly which candidates the actor can influence, and when.

An entry is appended only when the commit was authorized by a single-use commit grant (see
`scripts/write-commit-grant.py`), so it witnesses grant-authorized `/commit` commits only.
Bulk/auto-bulk commits carry a multi-use sentinel instead: `_evaluate_commit`
(hooks/pretool-git-privilege-guard.py) accepts them and RETURNS before
`_lock_grant_for_posttool`, so no grant and no pointer of their own is ever minted; and the
finalizer resolves the pointer for THIS TOOL EVENT only. They are therefore never journaled,
and consequently never reconcilable.

RULE: the pointer binding is PER-EVENT, not per-session. The finalizer — registered under
BOTH PostToolUse and PostToolUseFailure, whose payloads for one tool call carry the same
`tool_use_id` — derives one pointer name from that id and re-checks the RAW id recorded
INSIDE the pointer, raw-for-raw, because the derived filename is lossy; there is no session
lookup and no untargeted scan left to fall back to. An event
that minted no pointer therefore reaches no other event's. Do not re-key this on a session
id: the bulk conclusion above rests on the per-event binding and NOT on the superseded
by-name/wildcard split, which did not in fact deliver it — under session keying a bulk commit
sharing a session with a live ordinary grant resolved that grant BY NAME, so it was
journalable under another task's id, and spendable as a token whenever the two commits
happened to share a parent. Pinned by `no_pointer_event_writes_no_journal_entry` and
`no_pointer_event_yields_no_spendable_attribution` in
hooks/tests/test_posttool_commit_grant_finalize.py.

WHAT THIS IS NOT
----------------
This is NOT an authorization boundary, and it must never be described as one. No hook
guards `/tmp/agentic-commit/**`, and `hooks/push.sh` authorizes purely on
`token.commit_sha == HEAD`. An adversary who can emit arbitrary Bash (THREAT-MODEL §1.2)
can therefore write the push-gate token directly and open the gate, which is strictly
cheaper than forging a journal entry. The journal accordingly grants an attacker NO new
capability; what it does is remove every dependence on content the committing actor
chooses IN THE COMMIT ITSELF — message body and file set — which eliminates the
coincidental mis-attribution that the message/file-set heuristics allowed. It does not
remove every actor-influenced input: some recorded session ids remain settable through
the environment or the grant (see append_commit_event's docstring), which is why this is
a non-regression argument and not a soundness claim.
Read `docs/THREAT-MODEL.md` before strengthening any claim in this docstring.

FAIL-OPEN ON WRITE, FAIL-CLOSED ON MATCH
----------------------------------------
`append_commit_event` must NEVER raise and must NEVER block a commit: it is called from a
PostToolUse hook that runs after the commit has already landed. On the WRITE path every
failure mode (unreadable grant, git timeout, unwritable /tmp) degrades to "no entry
written", which fail-CLOSES reconciliation (no entry => no attribution => no token) without
affecting the commit itself.

A written entry is NOT therefore an attribution: reconciliation also fails closed at MATCH
time, and not only through a missing entry. `find_attributable_event` returns None on any
error, and `_parent_linkage_verified` refuses every entry whose linkage it cannot READ —
unreadable repository, a commit the repository does not contain, git timeout, a missing or
non-sha `parent_head`, a root commit. An entry that cannot be checked attributes nothing.
"""

import hashlib
import json
import os
import select
import subprocess
import sys
import time
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


# Byte bound on the raw-object header read below. Only the header can name a parent, and
# a REAL commit header is small: tree + parents + author + committer is a few hundred
# bytes, and the largest legitimate extra headers (a gpgsig, or a mergetag embedding a tag
# object) are a few KiB. 64 KiB is orders of magnitude above both, so no legitimate commit
# is refused by the cap — while the MESSAGE, whose size the committing actor chooses
# freely, is never buffered at all. A header that does not terminate within the cap is
# not something git wrote; it is treated as unverifiable, fail-closed.
_HEADER_CAP = 65536

# Wall-clock bound on that same read, the 5 seconds every other git call in this module
# already uses. Named rather than inlined because the two refusals it feeds — the expired
# deadline and the select() timeout — are MUTUALLY REDUNDANT: delete either alone and the
# other still answers "unverifiable", so the pair is only observable to a test that can
# shorten it. Nothing in the hook path sets it.
_HEADER_DEADLINE = 5


def _read_commit_header(repo_root, object_sha):
    """Raw header bytes of the commit object `object_sha`, or None when unreadable.

    Streams `git --no-replace-objects cat-file commit <sha>` and stops reading at the
    first blank line (the header terminator) or at ~_HEADER_CAP bytes, whichever comes
    first, then closes the pipe and reaps git. This is the R2-8 bound: the previous
    whole-object `subprocess.run` read buffered the entire commit INCLUDING its message
    just to inspect the header, so an actor-sized message could exhaust memory or burn
    the timeout and deny legitimate reconciliation. Memory here is bounded by the cap
    plus one read chunk, and time by `_HEADER_DEADLINE`, enforced with select() so a
    stalled pipe can never block past it.

    The command form is unchanged from the unbounded read — raw object, replacement
    suppressed — so the substitution immunity argued in `_first_parent` is untouched.
    Exit codes are deliberately not consulted: git is killed once the header is in hand,
    so there is no meaningful code to read, and a missing or non-commit object yields no
    terminated header and therefore None through the same path as every other failure.

    Returns None for: no such object, no blank line within the cap, timeout, unreadable
    repository, and every other error. Never raises.
    """
    proc = None
    try:
        proc = subprocess.Popen(
            ["git", "-C", repo_root, "--no-replace-objects", "cat-file", "commit",
             object_sha],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, bufsize=0,
        )
        deadline = time.monotonic() + _HEADER_DEADLINE
        buffer = b""
        while b"\n\n" not in buffer and len(buffer) < _HEADER_CAP:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            if not select.select([proc.stdout], [], [], remaining)[0]:
                return None
            chunk = os.read(proc.stdout.fileno(), 8192)
            if not chunk:
                break  # EOF: object fully delivered (or git failed) without more bytes
            buffer += chunk
        if b"\n\n" not in buffer:
            return None  # header never terminated: absent object or not a header at all
        return buffer.split(b"\n\n", 1)[0]
    except Exception:
        return None
    finally:
        if proc is not None:
            for cleanup in (proc.stdout.close, proc.kill,
                            lambda: proc.wait(timeout=5)):
                try:
                    cleanup()
                except Exception:
                    pass


def _first_parent(repo_root, commit_sha):
    """First parent RECORDED IN THE COMMIT OBJECT of `commit_sha`, or '' when unreadable.

    Read as `git --no-replace-objects cat-file commit <sha>` (bounded to the header —
    `_read_commit_header`). That exact form is required because git has TWO independent
    substitution mechanisms that can make a commit report a parent it does not record, and
    each read defeats only one of them (measured on git 2.54):

      - `rev-parse <sha>^1`, which this used to do, parses the commit and so honours BOTH
        refs/replace/* and the .git/info/grafts file. Either can hand back a parent the
        object never named.
      - `--no-replace-objects rev-parse <sha>^1` suppresses refs/replace/* but STILL
        applies grafts: grafts are imposed while parsing the commit, not while looking the
        object up, so the replace switch does not reach them.
      - `cat-file commit <sha>` prints the raw object and so is immune to grafts, but the
        object it is handed is itself substituted by refs/replace/*.

    Only suppressing replacement AND reading the raw object escapes both. This matters
    because the substitution is attacker-reachable from inside the repository and moves
    the answer BOTH ways: it can make a raced entry's recorded parent appear correct, and
    it can make a legitimate entry's correct parent appear wrong.

    STRUCTURAL VALIDITY IS REQUIRED (R2-7). `cat-file commit` only checks the TYPE the
    object was stored under; it validates nothing about the bytes, and
    `hash-object -t commit --literally` will store arbitrary garbage under that type. A
    naive scan for the first `parent`-prefixed line would grant such an object a VERIFIED
    linkage that the old parsing read (`rev-parse ^1`) refused outright. So a parent is
    extracted only from a header with the canonical commit shape:

      - line 0 is `tree ` + a full lowercase hex object name (40 or 64 chars)
      - zero or more `parent ` + full lowercase hex names, contiguous, directly after tree
      - the next line starts with `author `, and the one after it with `committer `
      - no `parent`-prefixed line appears anywhere later: git's parser would not treat a
        stray one as a parent, but a naive scan would, so its presence marks the object
        as something git never wrote

    Presence and position are what is validated, not the ident contents: linkage needs
    the object to BE a commit, and refusing on an oddly-formed author name would refuse
    real historical commits git itself still parses. The validation reads the raw bytes
    directly rather than asking git — running `rev-parse` as a validity oracle would
    reopen the substitution vector this read exists to close, because the oracle's
    VERDICT is itself graft-sensitive: a graft that strips a commit's parents makes
    `<sha>^1` fail for a structurally perfect commit, so even a yes/no consult lets an
    in-repo write flip a true linkage to unverifiable.

    '' is returned for a root commit (no first parent), a commit the repository does not
    contain, a non-commit or structurally invalid object, an unreadable repository, a
    timeout, a malformed parent line, and every other error path — the caller treats all
    of them identically as "linkage unverifiable". Never raises.
    """
    text = (commit_sha or "").strip()
    # Only a literal object name is accepted. A recorded head is a sha or it is not
    # verifiable at all, and refusing everything else keeps a recorded value from reaching
    # git as a revision expression or, with a leading '-', as an option.
    if len(text) < 40 or any(char not in "0123456789abcdefABCDEF" for char in text):
        return ""
    try:
        header = _read_commit_header(repo_root, text)
        if header is None:
            return ""
        # errors='replace' cannot raise, and replacement characters can only land inside
        # ident payloads, which are not inspected; every prefix and sha checked below is
        # pure ASCII, which UTF-8 decodes byte-for-byte.
        lines = header.decode("utf-8", "replace").split("\n")

        def is_object_name(value):
            return len(value) in (40, 64) and all(
                char in "0123456789abcdef" for char in value)

        if not lines[0].startswith("tree ") or not is_object_name(lines[0][5:]):
            return ""
        index = 1
        parents = []
        while index < len(lines) and lines[index].startswith("parent "):
            candidate = lines[index][7:]
            if not is_object_name(candidate):
                return ""  # malformed header: unverifiable, not "no parent"
            parents.append(candidate)
            index += 1
        if index >= len(lines) or not lines[index].startswith("author "):
            return ""
        if index + 1 >= len(lines) or not lines[index + 1].startswith("committer "):
            return ""
        if any(line.startswith("parent ") for line in lines[index:]):
            return ""  # a parent line outside the canonical block: not git's work
        return parents[0] if parents else ""
    except Exception:
        return ""


def _parent_linkage_verified(entry):
    """True only when the entry's recorded parent IS the actual first parent of its sha.

    WHY THIS IS NEEDED. `append_commit_event` runs in a PostToolUse hook, which fires
    AFTER the commit lock was released with the committing shell call. It reads live HEAD
    in that window, so a peer session's commit landing inside it is journaled as THIS
    session's `resulting_head` while `parent_head` still holds this session's OWN grant's
    pre-commit head. The two fields then describe different commits, and reconciliation
    would mint this session's token for the PEER's commit. Requiring recorded parent ==
    actual first parent of the recorded sha, compared exactly and resolved in the
    repository the entry is bound to, refuses exactly those entries.

    FAILS CLOSED on anything it cannot check: a missing or non-sha `parent_head`, an
    unreadable repository, a commit the repository does not contain, and a root commit,
    which has no first parent. An entry whose linkage cannot be verified attributes
    nothing.

    RULE — the comparison is only as good as the READ, so the parent comes from the RAW
    commit object with replacement objects suppressed, and only when those bytes are
    structurally a commit (`_first_parent`). That makes this check immune to BOTH
    refs/replace/* and .git/info/grafts, which are attacker-reachable
    from inside the repository and move the answer in EITHER direction — forging a raced
    entry's linkage, or breaking a legitimate one. Do not "simplify" the read back to a
    revision-graph form such as `rev-parse <sha>^1`; see `_first_parent` for why each half
    of that command is load-bearing.

    ACCEPTED RESIDUAL, stated narrowly so it is not mistaken for a soundness claim: this
    compares shas, so it cannot separate two commits that genuinely share a first parent.
    A peer that hard-resets to this session's grant head and re-commits inside the same
    window produces a sha whose actual first parent IS the recorded `parent_head`, so that
    entry still validates and remains attributable. That residual requires the peer to
    destroy history at exactly the raced instant AND to land on the same parent. The
    ordinary linear race — the peer commits on top of what is already there, which is what
    concurrent sessions on one branch actually do — is closed.

    The surviving residual is not only a matcher caveat: it is enumerated as a
    reconciliation ROUTE (agents/changelog-analyst.md, "Which cases actually survive") —
    the raced entry names the PEER's commit under this session's task and ids, the
    original cycle's pre-write HEAD-stability check returns `push_gate_race` and writes no
    token, and a later empty-candidate /commit reconciles the peer's commit under this
    session's attribution.
    """
    if not isinstance(entry, dict):
        return False
    recorded_parent = (entry.get("parent_head") or "").strip()
    if not recorded_parent:
        return False
    actual_parent = _first_parent(
        entry.get("repo_root") or "", entry.get("resulting_head")
    )
    return bool(actual_parent) and actual_parent == recorded_parent


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
        `session_id` when the payload carries a non-empty one — harness-supplied in that
        case only — and when the payload's value is absent, null, or empty it falls back
        to `CLAUDE_SESSION_ID` from its own environment (the placeholder `default` when
        that is unset too). So this member is beyond the committing agent's authorship
        exactly when the payload actually carried it; on the fallback path it is as
        environment-derived as the next two.
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
            # Recorded for audit only: find_attributable_event deliberately does NOT
            # match on it (see its docstring). Token paths are branch-keyed, which is
            # what makes this visible as the namespace-drift reconciliation route.
            "branch": (grant.get("branch") or "").strip(),
            # expected_head is the grant's pre-commit HEAD binding, enforced by the
            # privilege guard before the commit ran. It is the true parent ONLY when
            # nothing else landed in between, which this function cannot assume: it runs
            # in PostToolUse, AFTER the commit lock was released with the committing shell
            # call, and `resulting_head` above is live HEAD read inside that window. A peer
            # commit landing there makes these two fields describe DIFFERENT commits. The
            # mismatch is not repairable here — the hook has no way to tell — so it is left
            # recorded and `_parent_linkage_verified` detects and refuses it at match time.
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
      - its resulting_head equals `head_sha` EXACTLY. This is the freshness bind, and it is
        POINT-IN-TIME, not permanent: `head_sha` is whatever the caller passes — live HEAD as
        read at query time — and nothing here ever marks an entry superseded. A commit that
        has been built upon stops matching WHILE something else sits at HEAD; if HEAD is
        later restored to it, the SAME entry matches again. Do not describe a HEAD move as
        permanently defeating reconciliation; it defeats it only for as long as it lasts
        (agents/changelog-analyst.md, "Which cases actually survive", HEAD-round-trip route).
      - its task_id equals `task_id`
      - `session_id` is a member of its recorded, identifying session_ids
      - its recorded parent_head IS the actual first parent of its resulting_head, read
        from the repository the entry is bound to (`_parent_linkage_verified`). This is
        the HEAD-race bind: the appending hook reads live HEAD after the commit lock is
        already released, so a peer commit landing in that window is journaled under this
        session's task and ids with a parent_head that belongs to a different commit. An
        entry whose linkage cannot be verified attributes nothing.

    Deliberately absent: any cross-session tier. Only a session named in an entry's
    identifying `session_ids[]` can match here. State it that way and not as "a session that
    did not create the commit cannot attribute it": the two are NOT equivalent, and the
    stronger form contradicts the residual `_parent_linkage_verified` records — a peer commit
    landing in the append window on the SAME first parent this session's grant recorded stays
    attributable to THIS session, which did not create it. See agents/changelog-analyst.md
    for that residual and for why a task-id-only tier was rejected as forgeable.

    Also deliberately absent: a branch comparison. The entry RECORDS the grant's `branch`,
    and no check here reads it. A branch name is a mutable post-commit namespace label, not
    a component of the work's identity (the sha is): `git branch -m` is not a guarded
    operation, so REFUSING on a recorded-vs-live branch mismatch would let an in-repo
    rename flip a true attribution to unmatchable — the same in-repo-sensitivity class the
    raw-object parent read exists to avoid — while ACCEPTING on a match adds no forgery
    resistance, because the recorded value originates from the grant and a matching live
    branch is manufacturable by the same rename. Consequence, stated as a route and not
    hidden: push-gate token paths ARE branch-keyed, so the same commit at the same HEAD
    under a renamed or switched branch presents an EMPTY token slot that reconciliation can
    fill — a second token for the SAME attributed commit object, in the new branch's slot
    (agents/changelog-analyst.md, "Which cases actually survive").

    The SESSION segment of that same path drifts the same way, for a different reason, and
    it is a route too. This function accepts MEMBERSHIP in `session_ids[]` — up to four ids,
    see `append_commit_event` — while the token path is keyed on ONE alias, resolved by a
    chain preferring `CLAUDE_CODE_SESSION_ID`; the grant's own `sid` is resolved by the
    OPPOSITE precedence (scripts/write-commit-grant.py), so the two routinely disagree. A
    later run resolving a DIFFERENT member of that set finds an empty slot and reconciles
    into it while the first run's token still sits under the first alias. Neither side is
    safe to narrow: the width here is exactly what lets an orchestrator and its subagent
    count as one logical session, and no single-alias path derivation can cover a set that
    is deliberately wider than one. Note this is NARROWER than the branch case, not wider —
    session is checked here, branch is not. Same consequence: a second token for the same
    attributed commit, in a sibling alias's slot.
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
                # Last, so git runs only for an entry that already matches on every cheap
                # field, and only ever against the repo_root just confirmed to be ours.
                if not _parent_linkage_verified(entry):
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

    This route decides nothing itself: attribution is delegated entirely to
    `find_attributable_event`, so every check that function applies — including the
    parent-linkage bind — binds this route identically. Together the two are the whole set
    of routes by which a journal entry can reach a token write.
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
