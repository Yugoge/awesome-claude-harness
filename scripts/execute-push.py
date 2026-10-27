#!/usr/bin/env python3
"""Atomic push script: validate grant, consume it, write Chain-B sentinel, exec push.sh.

Eliminates the timing window that exists when validate + push are && -chained.
All 13 steps run in one Python process; os.execv replaces the process image so
the Chain-B sentinel write and push.sh sentinel-read occur within the same PID
lifetime — the 60s mtime gate in push.sh cannot expire between them.

Usage:
    python3 ~/.claude/scripts/execute-push.py \\
        --repo-hash <REPO_HASH> \\
        --branch <BRANCH> \\
        --remote <RESOLVED_REMOTE> \\
        --request-id <REQUEST_ID> \\
        [--repo-root <REPO_ROOT>] \\
        [--auto]

Exit codes:
    0   Never returned — successful path calls os.execv (process replaced by push.sh)
    1   Grant validation failed, HEAD drift, blocked verdict, or grant-consume failure
    2   Infrastructure failure: CLAUDE_SESSION_ID unset, push.sh missing/not executable,
        os.execv raised OSError after sentinel write, or invalid --repo-root path (OSError on chdir)
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks" / "lib"))
from harness_state_dir import harness_state_dir  # noqa: E402

# Sentinel/grant base directory under the hook state directory, where push.sh reads it
_SENTINEL_BASE = os.path.join(harness_state_dir(), "agentic-commit", "push-analyst")

# Push.sh location — resolved from this script's install location (<harness home>/hooks)
_PUSH_SH_TILDE = str(Path(__file__).resolve().parent.parent / "hooks" / "push.sh")


def _parse_args(argv: list) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="execute-push.py",
        description=(
            "Atomic push: validate Chain-B grant, consume it, write sentinel, "
            "exec push.sh — all in one process. Eliminates the && timing window."
        ),
    )
    parser.add_argument(
        "--repo-hash",
        required=True,
        help="16-char hex sha256(realpath(git_root))[:16] from orchestrator Step 2.",
    )
    parser.add_argument(
        "--branch",
        required=True,
        help="Branch name snapshot from Step 2 (used for grant field validation and sentinel).",
    )
    parser.add_argument(
        "--remote",
        required=True,
        help="Resolved push remote name (e.g. 'origin' or 'fork').",
    )
    parser.add_argument(
        "--request-id",
        required=True,
        help="REQUEST_ID from orchestrator Step 2 snapshot (matches grant.nonce field).",
    )
    parser.add_argument(
        "--repo-root",
        required=False,
        default=None,
        help="Repo root to chdir into before any git operations. Eliminates CWD dependency.",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        default=False,
        help="Forward --auto flag to push.sh for non-interactive lock handling.",
    )
    return parser.parse_args(argv)


def main(argv: list = None) -> int:
    # Step 1: Parse CLI arguments
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    # Step 1b: chdir to --repo-root before any git operations (and before os.execv
    # which inherits CWD into push.sh). Must fire before session_id check and grant access.
    if args.repo_root is not None:
        try:
            os.chdir(args.repo_root)
        except OSError as e:
            print(
                f"execute-push: cannot chdir to --repo-root {args.repo_root!r}: {e}",
                file=sys.stderr,
            )
            return 2

    repo_hash = args.repo_hash
    branch = args.branch
    remote = args.remote
    request_id = args.request_id
    auto = args.auto

    # Step 2: Read SESSION_ID from environment (NOT a CLI arg)
    session_id = os.environ.get("CLAUDE_SESSION_ID", "") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not session_id:
        print(
            "execute-push: CLAUDE_SESSION_ID and CLAUDE_CODE_SESSION_ID are not set or empty. "
            "Invoke /push from within a Claude Code session.",
            file=sys.stderr,
        )
        return 2

    # Step 3: Compute grant path
    grant_path = Path(_SENTINEL_BASE) / repo_hash / session_id / f"{request_id}.json"

    # Step 4: Check push.sh exists and is executable — infrastructure check before
    # any grant file is touched. Abort exit 2 on failure (not a validation failure).
    push_sh_path = str(Path(_PUSH_SH_TILDE).expanduser())
    if not os.path.isfile(push_sh_path) or not os.access(push_sh_path, os.X_OK):
        print(
            f"execute-push: push.sh not found or not executable at {push_sh_path}. "
            "Infrastructure failure — cannot exec push.sh.",
            file=sys.stderr,
        )
        return 2

    # Step 5: Read grant file
    if not grant_path.exists():
        print(
            f"execute-push: grant file not found at {grant_path}. "
            "Ensure push-analyst subagent completed successfully.",
            file=sys.stderr,
        )
        return 1

    # Step 6: Parse grant JSON
    try:
        grant_text = grant_path.read_text()
        grant = json.loads(grant_text)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"execute-push: grant file is malformed JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(grant, dict):
        print("execute-push: grant file is not a JSON object.", file=sys.stderr)
        return 1

    # Step 7: Validate grant fields (grant NOT consumed on any failure here)
    # expires_at — Z-suffix compatible with Python 3.8-3.10
    expires_at_raw = grant.get("expires_at", "")
    try:
        expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
        # Require timezone-aware datetime; tz-naive grants cannot be safely compared.
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError("expires_at is timezone-naive; UTC offset required")
        expires_at = expires_at.astimezone(timezone.utc)
    except (ValueError, AttributeError, TypeError):
        print(
            f"execute-push: grant field 'expires_at' is not a valid timezone-aware ISO-8601 datetime: "
            f"{expires_at_raw!r}",
            file=sys.stderr,
        )
        return 1
    if expires_at <= datetime.now(timezone.utc):
        print(
            f"execute-push: grant field 'expires_at' is in the past ({expires_at_raw}). "
            "Grant expired — run /push again.",
            file=sys.stderr,
        )
        return 1

    # Validate non-head_sha binding fields
    field_checks = [
        ("nonce", request_id, "--request-id"),
        ("branch", branch, "--branch"),
        ("remote_name", remote, "--remote"),
        ("session_id", session_id, "CLAUDE_SESSION_ID"),
    ]
    for field, expected, source in field_checks:
        actual = grant.get(field)
        if not isinstance(actual, str) or not actual:
            print(
                f"execute-push: grant field '{field}' is missing or empty.",
                file=sys.stderr,
            )
            return 1
        if actual != expected:
            print(
                f"execute-push: grant field '{field}' mismatch — "
                f"grant has {actual!r}, {source} is {expected!r}.",
                file=sys.stderr,
            )
            return 1

    # Validate verdict and risks before acting
    verdict = grant.get("verdict")
    if verdict not in ("approved", "warn", "blocked"):
        print(
            f"execute-push: grant field 'verdict' is invalid: {verdict!r}. "
            "Expected one of: approved, warn, blocked.",
            file=sys.stderr,
        )
        return 1
    risks = grant.get("risks")
    if not isinstance(risks, list):
        print(
            f"execute-push: grant field 'risks' must be a JSON array, got: {risks!r}.",
            file=sys.stderr,
        )
        return 1

    # Step 8: Act on verdict
    if verdict == "blocked":
        # Grant intentionally NOT consumed — blocked grant cannot authorize a push;
        # it will always re-block if replayed. A new /push generates a fresh grant.
        print("execute-push: push BLOCKED by push-analyst. Risks:", file=sys.stderr)
        for risk in risks:
            print(f"  - {risk}", file=sys.stderr)
        return 1
    if verdict == "warn":
        print("execute-push: WARNING — push-analyst flagged risks:", file=sys.stderr)
        for risk in risks:
            print(f"  - {risk}", file=sys.stderr)
        sys.stderr.flush()
        # Proceed to step 9 (do not abort)

    # Step 9: Check HEAD drift — single check at this step only; grant NOT consumed
    # on mismatch. The sentinel head field uses grant.head_sha (proved equal to
    # current HEAD here; avoids a second subprocess call later).
    head_sha_from_grant = grant.get("head_sha", "")
    if not isinstance(head_sha_from_grant, str) or not head_sha_from_grant:
        print(
            "execute-push: grant field 'head_sha' is missing or empty.",
            file=sys.stderr,
        )
        return 1
    try:
        current_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except subprocess.CalledProcessError:
        print("execute-push: failed to run 'git rev-parse HEAD'.", file=sys.stderr)
        return 1
    if current_head != head_sha_from_grant:
        print(
            f"execute-push: HEAD drift detected — grant.head_sha is {head_sha_from_grant!r} "
            f"but current HEAD is {current_head!r}. Aborting push; grant preserved.",
            file=sys.stderr,
        )
        return 1

    # Step 10: Consume (unlink) grant file — only after steps 5-9 all pass
    try:
        os.unlink(grant_path)
    except OSError as exc:
        print(
            f"execute-push: failed to consume (unlink) grant at {grant_path}: {exc}",
            file=sys.stderr,
        )
        return 1

    # Step 11: Write Chain-B sentinel atomically (mkstemp + os.replace)
    # branch_encoded is used for the sentinel FILE PATH only; the sentinel JSON
    # 'branch' field carries the RAW branch name (push.sh:94 reads raw branch).
    branch_encoded = branch.replace("/", "__")
    sentinel_dir = Path(_SENTINEL_BASE) / repo_hash
    sentinel_path = sentinel_dir / f"{branch_encoded}-chainB.validated.sentinel.json"
    sentinel_data = {
        "result": "PASS",
        "request_id": request_id,
        "head": head_sha_from_grant,   # proved equal to current HEAD at step 9
        "branch": branch,              # raw branch name — NOT the encoded form
        "remote": remote,
    }
    sentinel_bytes = json.dumps(sentinel_data).encode()
    sentinel_dir.mkdir(parents=True, exist_ok=True)
    tmp_sentinel = None
    try:
        fd, tmp_sentinel = tempfile.mkstemp(
            dir=str(sentinel_dir), prefix=".sentinel-", suffix=".tmp"
        )
        os.write(fd, sentinel_bytes)
        os.close(fd)
        os.replace(tmp_sentinel, str(sentinel_path))
        tmp_sentinel = None  # os.replace succeeded; no temp to clean up
    except OSError as exc:
        if tmp_sentinel is not None:
            try:
                os.unlink(tmp_sentinel)
            except OSError:
                pass
        print(f"execute-push: failed to write Chain-B sentinel: {exc}", file=sys.stderr)
        return 1

    # Step 12: Set CLAUDE_PUSH_REQUEST_ID in environment and flush stderr so
    # warn-path risk messages are not lost when the process image is replaced.
    os.environ["CLAUDE_PUSH_REQUEST_ID"] = request_id
    sys.stderr.flush()

    # Step 13: exec push.sh — replaces this process image (NOT subprocess).
    # argv[0] must be the program path; remote is argv[1]; --auto optional argv[2].
    push_argv = [push_sh_path, remote] + (["--auto"] if auto else [])
    try:
        print(f"execute-push: sentinel written, exec push.sh pid={os.getpid()}", flush=True)
    except BrokenPipeError:
        pass
    try:
        os.execv(push_sh_path, push_argv)
    except OSError as exc:
        # M11: sentinel cleanup on execv failure — prevent orphaned sentinel.
        # Grant was already consumed at step 10 before sentinel write.
        try:
            os.unlink(str(sentinel_path))
        except OSError:
            pass
        print(
            f"execute-push: os.execv raised OSError: {exc}. Sentinel cleaned up.",
            file=sys.stderr,
        )
        return 2

    # os.execv never returns on success; this line is unreachable.
    return 0  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
