#!/usr/bin/env python3
"""commit_pipeline.py -- the /commit pipeline-evidence contract.

ONE home for the two questions the commit-authorization chain could not
previously answer, shared by all three participants so writer and readers
agree by construction rather than by coincidence (the failure mode that the
2026-10-03 `harness_state_dir` unification had to clean up afterwards):

  MINT side  -- `verify_pipeline_dispatch()`, called by
                `scripts/write-commit-grant.py`: is a real /commit pipeline
                run actually standing behind this mint request?
  CONSUME side -- `select_dispatch_attestation()` / `claim_attestation()`,
                called by `hooks/pretool-git-privilege-guard.py`: is the
                caller presenting this grant the subagent the pipeline
                dispatched, or merely a bearer holding the ticket?

WHAT THIS CLOSES (disclosure items 1 and 2 of commit 1fdbd3767, both landed
labelled `Not fully closed` / `Not a full closure`). Before this module the
chain was: a `/commit`-prefixed prompt lights
`claude-commit-userintent-<sid>.flag`; the sentinel alone authorizes
`write-commit-grant.py` to mint; the minted grant alone authorizes a bare
`git commit`. Nothing anywhere required the commit to be a pipeline PRODUCT.
Measured consequence: a seat sent a bare `/commit` first line lit the
sentinel, self-minted, and committed 14 times with changelog-analyst never
dispatched and the Phase 2/3/4/5/10 gates -- including the fd-9 lock and the
MANDATORY pre-stage validation, both of which fail SILENTLY -- never run.

The grant was a BEARER ticket. These two sides make it a NAMED one.

Evidence asymmetry, stated plainly because it bounds what this module
proves. The two sides do not have equal strength, and the mint side is the
weaker one BY CONSTRUCTION, not by oversight:

  * The dispatch-snapshot manifest (`claude-commit-manifest-<sid>.json`) is
    authored by the /commit orchestrator itself via Bash, because /commit
    Step 5 mints BEFORE it dispatches anything (`commands/commit.md` Step 5
    -> Step 7) -- so at mint time no dispatch has happened yet and no
    hook-written witness of one can exist. The manifest is therefore
    orchestrator-forgeable in principle. What `verify_pipeline_dispatch()`
    buys is that forging it is no longer cheap: the manifest must be
    mutually consistent with FOUR artifacts the bypass path does not have
    (a repository plan admitting this exact repo at its live branch/HEAD, a
    cycle report whose sha256 matches the plan's own `report_sha256`, and a
    close-report for the task). A seat that just lights the sentinel and
    runs the minter has none of them.
  * The dispatch attestation (`claude-commit-dispatch-<sid>-<nonce>.json`)
    does not depend on an orchestrator's good faith the way the manifest
    does: its only INTENDED writer is
    `hooks/pretool-commit-dispatch-attest.py`, a PreToolUse:Agent hook that
    fires on the real `Agent` tool call, so an attestation that hook wrote
    exists only because a dispatch happened. Bash forgery of the file is
    intercepted at the Bash layer (`hooks/pretool-bash-safety.sh` Layer
    1.E3) -- one artifact over from Layer 1.E2's protection of the
    user-intent sentinel, but NOT a mirror of it. "Mirrors Layer 1.E2" is
    retracted in the hook itself as inaccurate in both directions, and the
    three differences hold in the current bytes: 1.E2 anchors its path
    regex on a filename-suffix pattern (an alphanumeric-and-dash run plus a
    `.flag` extension) where 1.E3 matches the bare namespace prefix with no
    filename anchor; 1.E2 pairs that with a short UNANCHORED eight-token
    alternation (the two redirection operators plus `tee`, `cp`, `mv`,
    `ln`, `touch`, `cat`) where 1.E3 uses the sixteen-token shared
    `ARTIFACT_WRITE_VERB_RE`, every token of which is word-boundary
    anchored and carries an explicit right bound; and 1.E3's
    redirection test is the NARROWER of the two, requiring the namespace to
    be the redirection TARGET, where 1.E2's bare redirection operator
    matches anywhere in the command. That layer is also a verb BLACKLIST,
    so it raises the cost of forging one rather than making it impossible,
    and an unenumerated write verb would still get through. What the
    consume side actually requires is identity,
    below: the artifact must be claimed by a dispatched subagent's own
    `agent_id`, which no Bash-authored file supplies.

So: mint side raises the cost, consume side is the structural barrier. Both
are required; neither is sufficient. Do not describe the mint side as
unforgeable.

Consumer identity: `agent_id` in the PreToolUse payload. MEASURED, not
assumed -- `hooks/pretool-cp-checkin.py` is itself a PreToolUse hook and
writes `json.load(sys.stdin)["agent_id"]` straight into
`.claude/dev-registry/agent-index.json`, where the recorded `a`-prefixed ids
map to real agent types (ba/qa/pm/architect/...), so the asymmetry is
re-derivable from that index rather than taken on faith from this comment. A
dispatched subagent's PreToolUse payload carries a non-empty `agent_id`; the
main agent's does not. That asymmetry is what refuses the
orchestrator-as-bearer.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_state_dir import harness_state_dir  # noqa: E402

# ---------------------------------------------------------------------------
# Contract constants. Shared by minter, attesting hook and privilege guard --
# never re-spelled at a call site.
# ---------------------------------------------------------------------------

ATTEST_SCHEMA = "commit-dispatch-attestation/1"
ATTEST_PREFIX = "claude-commit-dispatch-"
ATTEST_ORIGIN = "pretool-agent-hook"

MANIFEST_PREFIX = "claude-commit-manifest-"

# Stamped into every pipeline-minted grant's `minted_by.origin`. The guard
# refuses any grant that does not carry it, which is what retires the
# unsigned bearer ticket: a grant written by an older copy of the minter (no
# `minted_by` at all) is not honored.
PIPELINE_ORIGIN = "commit-pipeline"

# The ONLY agent type whose dispatch attests the commit pipeline.
CHANGELOG_ANALYST = "changelog-analyst"

# Attestation validity window. Deliberately the same 30 minutes as
# GRANT_TTL_MINUTES in scripts/write-commit-grant.py: a cycle that outruns
# the window its own grant would expire in is retried by re-invoking
# /commit, which re-mints AND re-dispatches, so a shorter attestation life
# would only add a second, differently-timed way to fail the same cycle.
ATTEST_TTL_MINUTES = 30

# Freshness bound on the dispatch-snapshot manifest, same window and same
# reasoning.
MANIFEST_WINDOW_MINUTES = 30

# Upper bound for any read out of the world-writable state root. Real
# manifests run a few KiB (plan + per-repo porcelain status); attestations a
# few hundred bytes. 1 MiB is far above both and far below a memory risk.
_READ_LIMIT = 1024 * 1024


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def state_dir() -> str:
    """The hook runtime-state root, via the one shared resolver.

    Same `harness_state_dir()` the user-intent sentinel writer
    (`prompt-workflow.py::_write_userintent_sentinel`) and reader
    (`scripts/write-commit-grant.py::_sentinel_dir`) use. No second env var
    is layered on top here -- that is precisely how the sentinel's writer and
    reader once came to agree only when CLAUDE_STATE_DIR happened to be
    unset.
    """
    return harness_state_dir()


def manifest_path(sid: str) -> str:
    """Dispatch-snapshot manifest path for `sid` (/commit Step 5)."""
    return str(Path(state_dir()) / f"{MANIFEST_PREFIX}{sid}.json")


def attestation_path(sid: str, nonce: str) -> str:
    return str(Path(state_dir()) / f"{ATTEST_PREFIX}{sid}-{nonce}.json")


def attestation_glob(sid: str = "*") -> str:
    return str(Path(state_dir()) / f"{ATTEST_PREFIX}{sid}-*.json")


# ---------------------------------------------------------------------------
# Safe reads
# ---------------------------------------------------------------------------

def safe_read_json(path: str, limit: int = _READ_LIMIT):
    """Parsed JSON for an untrusted path under the state root, or None.

    The state root is world-writable, so a plain `open()` would follow a
    planted symlink or block forever on a planted FIFO. O_NOFOLLOW +
    O_NONBLOCK + a regular-file fstat + a size cap remove all three.

    NOT the same function as `write-commit-grant.py::_read_identified`, and
    deliberately not refactored into it: that one returns the (st_dev,
    st_ino) of the inode it read because its caller UNLINKS by name
    afterwards and must prove it is deleting what it inspected (audit F8).
    Nothing here deletes anything, so there is no identity contract to keep
    and no reason to borrow one.

    Never raises. None means "could not be read as JSON", with no
    distinction drawn between absent, malformed, oversized and hostile --
    every one of them fails closed at every call site.
    """
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
        return None
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0))
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        raw = b""
        while len(raw) <= limit:
            chunk = os.read(fd, limit + 1 - len(raw))
            if not chunk:
                break
            raw += chunk
        if len(raw) > limit:
            return None
    except OSError:
        return None
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def _parse_iso(value) -> datetime | None:
    """Parse an ISO-8601 timestamp to an aware UTC datetime, else None.

    Accepts the trailing-Z form (the dispatch manifest writes
    `2026-10-05T01:48:01Z`) exactly as the privilege guard's
    `_end_time_passed` does, and treats a naive timestamp as UTC rather than
    guessing a local zone.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _within(ts: datetime | None, now: datetime, minutes: int) -> bool:
    """True iff `ts` is in [now - minutes, now + 1 min].

    The forward minute absorbs ordinary clock jitter between a writer and a
    reader on the same host. A timestamp further in the future than that is
    refused rather than trusted: an attacker-chosen `expires_at` decades out
    is exactly how a short-lived credential becomes a permanent one.
    """
    if ts is None:
        return False
    if ts > now + timedelta(minutes=1):
        return False
    return ts >= now - timedelta(minutes=minutes)


def _mtime_utc(path: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(os.stat(path).st_mtime, timezone.utc)
    except OSError:
        return None


def _canon(path_text) -> str:
    if not isinstance(path_text, str) or not path_text.strip():
        return ""
    try:
        return str(Path(path_text).resolve())
    except (OSError, RuntimeError):
        return os.path.normpath(path_text)


def file_sha256(path: str) -> str:
    """sha256 of a file's bytes, or '' when unreadable."""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# MINT side
# ---------------------------------------------------------------------------

def _close_report_exists(task_id: str, repo_root: str, control_root: str) -> bool:
    """True iff a close-report file exists for `task_id`.

    Resolution is DELEGATED to `scripts/resolve-close-report.sh` -- the same
    script /commit Step 3 check 1 uses -- instead of being reimplemented
    here. A second implementation of a candidate-probe order is exactly the
    mirrored-pair shape that turns one invariant into two that can disagree:
    the script probes CLAUDE_PROJECT_DIR, then the cwd's git toplevel, then
    CONTROL_ROOT, and the report is `.md`, not `.json`.

    EXISTENCE ONLY, never content. /commit Step 3 relaxes check 2 (the
    `CLOSE: YES` content test) under `--dry-run` while never relaxing check
    1, so requiring the verdict here would refuse a legitimate
    `/commit --dry-run` -- tightening one gate by breaking another.
    """
    script = Path(__file__).resolve().parent.parent.parent / "scripts" / "resolve-close-report.sh"
    if not script.is_file():
        return False
    env = dict(os.environ)
    env["CONTROL_ROOT"] = control_root or repo_root
    try:
        done = subprocess.run(
            ["bash", str(script), task_id],
            cwd=repo_root if os.path.isdir(repo_root) else None,
            capture_output=True, text=True, timeout=10, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def verify_pipeline_dispatch(sid: str, task_id: str, repo_root: str,
                             branch: str, expected_head: str, now=None):
    """Is a real /commit pipeline run standing behind this mint request?

    Returns `(ok, reason, evidence)`. `reason` is operator-facing and names
    the ONE missing piece; `evidence` is folded into the grant's `minted_by`
    so the consume side and any later audit can see what was checked.

    Every check binds the manifest to an artifact the measured bypass path
    does not possess. Read them as one conjunction:

      1-3. a live, well-formed manifest for THIS session and THIS task
           (bounded by both `dispatched_at` and the file's own mtime, so
           back-dating one field is not enough)
      4-5. a repository plan for the same task that ADMITS this exact repo
      6.   whose plan entry agrees with the repo's live branch and HEAD --
           the same triple the grant itself records and the guard re-checks
      7.   whose `report_sha256` matches the actual bytes of the cycle
           report it names, so the plan cannot cite a report that does not
           exist or has since changed
      8.   and a close-report for the task (existence only -- see
           `_close_report_exists`)

    Fails closed on every unreadable, malformed or mismatched input.
    """
    now = now or datetime.now(timezone.utc)
    evidence: dict = {}

    path = manifest_path(sid)
    manifest = safe_read_json(path)
    if not isinstance(manifest, dict):
        return False, (
            f"no readable /commit dispatch-snapshot manifest at {path} -- a grant may "
            "only be minted from inside a real /commit pipeline run, which writes this "
            "manifest (commands/commit.md Step 5) BEFORE it mints"
        ), evidence
    evidence["manifest_path"] = path
    evidence["manifest_sha256"] = file_sha256(path)

    if str(manifest.get("session_id") or "") != sid:
        return False, (
            f"manifest {path} belongs to session {manifest.get('session_id')!r}, not "
            f"{sid!r} -- a manifest from another session does not authorize minting here"
        ), evidence

    if str(manifest.get("task_id") or "") != task_id:
        return False, (
            f"manifest {path} is for task {manifest.get('task_id')!r}, but the mint "
            f"request is for {task_id!r}"
        ), evidence

    dispatched_at = _parse_iso(manifest.get("dispatched_at"))
    if not _within(dispatched_at, now, MANIFEST_WINDOW_MINUTES):
        return False, (
            f"manifest {path} has dispatched_at={manifest.get('dispatched_at')!r}, which is "
            f"not inside the {MANIFEST_WINDOW_MINUTES}-minute window ending now -- re-run "
            "/commit rather than reusing a stale pipeline manifest"
        ), evidence
    if not _within(_mtime_utc(path), now, MANIFEST_WINDOW_MINUTES):
        return False, (
            f"manifest {path} has an mtime outside the {MANIFEST_WINDOW_MINUTES}-minute "
            "window (its dispatched_at field alone is not proof of freshness)"
        ), evidence
    evidence["manifest_dispatched_at"] = manifest.get("dispatched_at")

    # Accept BOTH spellings of this one key. `commands/commit.md` names the
    # manifest's own fields in lowercase (`session_id`, `task_id`,
    # `dispatched_at`, `files_at_dispatch`) but refers to the plan and the
    # artifact chain by their SHELL VARIABLE names, `REPOSITORY_PLAN` and
    # `ARTIFACT_CHAIN` -- so an orchestrator serializing "the complete
    # REPOSITORY_PLAN" into the manifest can reasonably use either case, and
    # measurably does. Pinning only the lowercase form here would refuse to
    # mint for a genuine /commit run that happened to pick the other spelling
    # -- breaking the normal path, which is worse than not having hardened it
    # at all.
    #
    # RE-DERIVE THAT, do not trust a count frozen into this comment. A
    # host-specific ratio stood here and was load-bearing for this acceptance
    # decision while naming no directory, no predicate and no command -- so it
    # was unverifiable on any other host and silently stale the moment the
    # manifest population turned over. The decision needs exactly ONE fact:
    # does any GENUINE manifest carry the uppercase spelling?
    #
    # METHOD. Manifests live in `state_dir()`, named `MANIFEST_PREFIX` + the
    # session id + `.json`. Count a file as GENUINE when it parses as a JSON
    # object whose `session_id` is non-empty and equals the session-id segment
    # of its own filename, AND it carries a plan OBJECT under either spelling
    # -- a list-shaped `repository_plan` is a fixture written by
    # tests/test_commit_multi_repo_plan.py, not a pipeline product, and the
    # self-consistency test is what drops hand-made and truncated leftovers.
    # Tally the two spellings across that set. Accepting both is justified for
    # as long as the uppercase tally is non-zero; if it ever reaches zero,
    # report that rather than quietly narrowing the check here.
    #
    # Corroboration available in the same pass: the uppercase manifests also
    # uppercase `ARTIFACT_CHAIN` while leaving `session_id`, `task_id` and
    # `dispatched_at` lowercase -- exactly the mixed shape the shell-variable
    # explanation above predicts, which is why they are orchestrator output
    # and not corruption. Last re-derived 2026-10-08 (41 lowercase, 5
    # uppercase, so justified); re-run the method rather than citing that.
    #
    # This is exactly the writer/reader-agreement failure this module's own
    # docstring cites as its cautionary precedent (the sentinel directory whose
    # writer and reader agreed only by coincidence), reproduced here one key
    # over. Found by the close gate, not by this module's author.
    #
    # It widens nothing that matters: the key's NAME was never the security
    # property. Every check below -- session, task, freshness, the admitted
    # repo at its live branch/HEAD, the report digest, the close-report -- runs
    # identically whichever spelling carried the plan here.
    plan = manifest.get("repository_plan")
    if not isinstance(plan, dict):
        plan = manifest.get("REPOSITORY_PLAN")
    if not isinstance(plan, dict):
        return False, (
            f"manifest {path} carries no repository_plan object -- the plan is what admits "
            "a repository for commit; a manifest without one authorizes nothing"
        ), evidence
    if str(plan.get("task_id") or "") != task_id:
        return False, (
            f"repository_plan in {path} is for task {plan.get('task_id')!r}, not {task_id!r}"
        ), evidence

    repositories = plan.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        return False, (
            f"repository_plan in {path} admits no repositories"
        ), evidence

    want = _canon(repo_root)
    entry = None
    for candidate in repositories:
        if isinstance(candidate, dict) and _canon(candidate.get("repo_root")) == want:
            entry = candidate
            break
    if entry is None:
        admitted = [str(c.get("repo_root")) for c in repositories if isinstance(c, dict)]
        return False, (
            f"repository_plan in {path} does not admit repo_root {want!r} "
            f"(admitted: {admitted}) -- a grant cannot be minted for a repository the "
            "pipeline never planned"
        ), evidence
    evidence["plan_repo_root"] = str(entry.get("repo_root"))

    if branch and str(entry.get("branch") or "") != branch:
        return False, (
            f"repository_plan entry for {want!r} records branch "
            f"{entry.get('branch')!r} but the repo is live on {branch!r} -- the plan is "
            "stale; rebuild it and re-mint"
        ), evidence
    if expected_head and str(entry.get("expected_head") or "") != expected_head:
        return False, (
            f"repository_plan entry for {want!r} records expected_head "
            f"{entry.get('expected_head')!r} but live HEAD is {expected_head!r} -- the plan "
            "is stale; rebuild it and re-mint"
        ), evidence

    report_path = str(plan.get("report_path") or "")
    report_sha = str(plan.get("report_sha256") or "")
    if not report_path or not report_sha:
        return False, (
            f"repository_plan in {path} is missing report_path/report_sha256 -- without them "
            "the plan cannot be tied to the cycle report it claims to derive from"
        ), evidence
    actual_sha = file_sha256(report_path)
    if not actual_sha:
        return False, (
            f"repository_plan cites report {report_path!r}, which cannot be read -- the plan "
            "must derive from a cycle report that actually exists"
        ), evidence
    if actual_sha != report_sha:
        return False, (
            f"report {report_path!r} has sha256 {actual_sha} but the plan recorded "
            f"{report_sha} -- plan and report disagree; rebuild the plan and re-mint"
        ), evidence
    evidence["plan_report_path"] = report_path
    evidence["plan_report_sha256"] = report_sha

    control_root = str(plan.get("control_root") or "")
    if not _close_report_exists(task_id, repo_root, control_root):
        return False, (
            f"no close-report exists for task {task_id!r} -- /commit Step 3 check 1 requires "
            "one and never relaxes it, so a mint request for a task that was never closed is "
            "not a pipeline product"
        ), evidence
    evidence["close_report_present"] = True

    return True, "", evidence


# ---------------------------------------------------------------------------
# CONSUME side
# ---------------------------------------------------------------------------

def write_attestation(sid: str, *, task_id: str = "", dryrun=None,
                      dispatcher_agent_id: str = "",
                      prompt_sha256: str = "") -> str:
    """Record that changelog-analyst was really dispatched. Returns the path.

    Called ONLY from `hooks/pretool-commit-dispatch-attest.py`, on the real
    PreToolUse:Agent event. That is the whole value of the artifact: the
    orchestrator cannot produce one by NARRATING a dispatch, because
    narration writes nothing -- this hook is the artifact's only INTENDED
    writer, and it fires on the real `Agent` tool call or not at all.

    Bash is a weaker story and the sentence above must not be read as
    covering it. `pretool-bash-safety.sh` Layer 1.E3 intercepts the
    ordinary Bash write shapes aimed at this namespace, but it is a verb
    BLACKLIST: it raises the COST of forging the artifact rather than
    making it impossible, and an unenumerated write verb would still get
    through (see the evidence-asymmetry note in this module's own
    docstring, and the RESIDUAL list in the hook's Layer 1.E3 comment).
    The STRUCTURAL barrier sits on the consume side, in
    `hooks/pretool-git-privilege-guard.py`: a grant must carry a pipeline
    `minted_by.origin`, the calling payload must supply a non-empty
    `agent_id`, and that caller must be the dispatched subagent holding the
    matching dispatch attestation. Both sides are required and neither is
    sufficient alone -- do not describe either as unforgeable.

    `task_id` and `dryrun` are parsed from the dispatch prompt and are
    FORENSIC ONLY -- nothing gates on them. A prompt-shape parser that
    gated the commit path would hand the happy path a new way to fail
    silently the first time /commit reworded its prompt.
    """
    now = datetime.now(timezone.utc)
    nonce = secrets.token_hex(8)
    record = {
        "schema": ATTEST_SCHEMA,
        "origin": ATTEST_ORIGIN,
        "sid": sid,
        "subagent_type": CHANGELOG_ANALYST,
        "task_id": task_id,
        "dryrun": dryrun,
        "dispatcher_agent_id": dispatcher_agent_id,
        "prompt_sha256": prompt_sha256,
        "nonce": nonce,
        "dispatched_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=ATTEST_TTL_MINUTES)).isoformat(),
        "claimed_by_agent_id": None,
        "claimed_at": None,
    }
    path = attestation_path(sid, nonce)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, json.dumps(record, sort_keys=True).encode("utf-8"))
    finally:
        os.close(fd)
    return path


def _attestation_is_live(record, path: str, now: datetime) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("schema") != ATTEST_SCHEMA:
        return False
    if record.get("origin") != ATTEST_ORIGIN:
        return False
    if record.get("subagent_type") != CHANGELOG_ANALYST:
        return False
    expires_at = _parse_iso(record.get("expires_at"))
    if expires_at is None or expires_at <= now:
        return False
    # Both the self-declared dispatch time and the file's own mtime must sit
    # in the window: one field alone is a claim, the pair is a claim plus a
    # filesystem fact.
    if not _within(_parse_iso(record.get("dispatched_at")), now, ATTEST_TTL_MINUTES):
        return False
    return _within(_mtime_utc(path), now, ATTEST_TTL_MINUTES)


def select_dispatch_attestation(sids, grant_created_at: str, agent_id: str,
                                now=None):
    """Pick the attestation that lets `agent_id` consume a grant.

    Returns `(path, reason)`: a path on success, `(None, reason)` otherwise.

    `sids` is the candidate session list -- in practice the grant's own `sid`
    plus the consuming payload's `session_id`. Both are accepted because a
    subagent's payload session id and the dispatching session's id
    legitimately differ in this harness (the privilege guard's own
    `_find_grant_any` exists for that same reason), and an attestation under
    either id is still the product of a real changelog-analyst dispatch in
    that session -- the property being proved.

    Requires `dispatched_at >= grant.created_at`: the dispatch must come
    AFTER the mint. That ordering is what makes the attestation evidence
    about THIS pipeline run rather than about any recent one, and the happy
    path satisfies it by construction (Step 5 mints, Step 6/7 dispatch).

    Prefers an attestation already claimed by this same `agent_id`, so the
    second repository of a multi-repo plan reuses the claim its first commit
    established instead of consuming a second attestation.
    """
    now = now or datetime.now(timezone.utc)
    minted = _parse_iso(grant_created_at)
    candidates: list[tuple[datetime, str, dict]] = []
    seen: set[str] = set()
    # Why live attestations were passed over, so a refusal can say which of
    # three very different situations it is instead of reporting all of them
    # as "none found" -- the shape of diagnostic that sends a reader looking
    # for a missing file that is in fact present.
    rejected_older = 0
    rejected_claimed = 0
    for sid in [s for s in (sids or []) if s]:
        import glob as _glob
        for path in _glob.glob(attestation_glob(sid)):
            if path in seen:
                continue
            seen.add(path)
            record = safe_read_json(path)
            if not _attestation_is_live(record, path, now):
                continue
            dispatched_at = _parse_iso(record.get("dispatched_at"))
            if minted is not None and dispatched_at is not None and dispatched_at < minted:
                rejected_older += 1
                continue
            claimed = record.get("claimed_by_agent_id")
            if claimed and str(claimed) != agent_id:
                rejected_claimed += 1
                continue
            candidates.append((dispatched_at or now, path, record))
    if not candidates:
        if rejected_older:
            return None, (
                f"{rejected_older} live changelog-analyst dispatch attestation(s) exist for "
                f"session(s) {[s for s in (sids or []) if s]!r}, but all of them predate this "
                f"grant's created_at ({grant_created_at!r}). The pipeline mints and THEN "
                "dispatches, so a grant newer than every dispatch means the grant was "
                "re-minted without re-dispatching changelog-analyst -- re-dispatch it "
                "(commands/commit.md Step 8 re-mints and re-dispatches together)"
            )
        if rejected_claimed:
            return None, (
                f"{rejected_claimed} live changelog-analyst dispatch attestation(s) exist but "
                f"are claimed by a different agent than {agent_id!r} -- one dispatch "
                "authorizes one consumer"
            )
        return None, (
            "no live changelog-analyst dispatch attestation for "
            f"session(s) {[s for s in (sids or []) if s]!r} minted-at-or-after "
            f"{grant_created_at!r}"
        )
    # Already-mine first, then newest: a claim this agent already holds is
    # the strongest match available.
    candidates.sort(
        key=lambda item: (
            str(item[2].get("claimed_by_agent_id") or "") == agent_id,
            item[0],
        ),
        reverse=True,
    )
    return candidates[0][1], ""


def claim_attestation(path: str, agent_id: str):
    """Bind this attestation to `agent_id`. Returns `(ok, reason)`.

    First consumer wins and is recorded; every later consumption under the
    same attestation must present the same `agent_id`. That is what turns
    "some dispatched subagent" into "the one subagent this dispatch
    produced" -- without it, one real dispatch would license commits by any
    number of unrelated subagents.

    Serialized with `flock` and re-read inside the lock, so two concurrent
    commits cannot both observe the claim as free.
    """
    import fcntl
    if not agent_id:
        return False, "no agent_id to claim with"
    try:
        fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        return False, f"attestation {path} could not be opened to claim: {exc}"
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            raw = b""
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                raw += chunk
                if len(raw) > _READ_LIMIT:
                    return False, f"attestation {path} is oversized"
            record = json.loads(raw.decode("utf-8"))
            if not isinstance(record, dict):
                return False, f"attestation {path} is not a JSON object"
            held = record.get("claimed_by_agent_id")
            if held and str(held) != agent_id:
                return False, (
                    f"attestation {path} is already claimed by agent {held!r}; "
                    f"agent {agent_id!r} is a different consumer"
                )
            if not held:
                record["claimed_by_agent_id"] = agent_id
                record["claimed_at"] = datetime.now(timezone.utc).isoformat()
                payload = json.dumps(record, sort_keys=True).encode("utf-8")
                os.lseek(fd, 0, os.SEEK_SET)
                os.write(fd, payload)
                os.ftruncate(fd, len(payload))
            return True, ""
        except (UnicodeDecodeError, ValueError) as exc:
            return False, f"attestation {path} is unparseable: {exc}"
        except OSError as exc:
            return False, f"attestation {path} could not be claimed: {exc}"
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
