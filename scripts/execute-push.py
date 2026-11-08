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

In-flight compatibility (train 2, A17; D15, D18, D25), kept until no session
predates train 2's landing: 2acc29b's changelog-analyst text writes the
push-gate token with the Write tool, which hooks/pretool-tool-policy.py refuses
for every agent (P5 review H2, or its role row where the state dir is not
/tmp), so a /commit that session runs lands its commit with no token. Step 9b
below is the route that refusal names: once the push-analyst grant its own
dispatch binds has passed Steps 5-9, and while no token names an ancestor of
HEAD, the token's one writer (scripts/write-push-gate-token.py) writes the
token for HEAD when a session transcript records that refusal for HEAD
(_refused_inflight_token_write). No agent writes the token, and push.sh stays
its one decider.
"""

import argparse
import hashlib
import json
import os
import re
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

# The push-gate token's one writer, beside this script.
_TOKEN_WRITER = str(Path(__file__).resolve().parent / "write-push-gate-token.py")


# -- in-flight compatibility (train 2, A17): Step 9b ---------------------------
# COMPATIBILITY CODE (module docstring), kept only until no running session
# predates train 2's landing (D15); then Step 9b, these helpers and
# hooks/tests/test_inflight_push_route.py go, with the refusal note in
# hooks/pretool-tool-policy.py (_note_inflight_token_route).
# The record read is the CLI's own: a subagent transcript and its meta under
# <config dir>/projects, which no agent writes, deletes or renames (P5 R2).
# 2acc29b's Phase 10 writes the token at <dir>/agentic-commit/push/<repo hash>/
# <session digest>/<branch>.json, <dir> its literal /tmp.
_REFUSED_TOKEN_WRITE_RE = re.compile(r"/agentic-commit/push/([0-9a-f]{16})/[0-9a-f]{16}/([^/]+)\.json\Z")
_REFUSAL = "BLOCKED by tool-policy.v1"


def _git_ok(*args: str) -> bool:
    return subprocess.run(["git", *args], capture_output=True, timeout=20).returncode == 0


def _git_out(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=20)
    return r.stdout.strip() if r.returncode == 0 else ""


def _token_names_ancestor(repo_hash: str, branch: str, head: str) -> bool:
    """push.sh's READ side: a token of BRANCH at either depth under the repo
    hash names an ancestor of HEAD (or HEAD itself)."""
    base = Path(harness_state_dir()) / "agentic-commit" / "push" / repo_hash
    name = branch.replace("/", "__") + ".json"
    for path in [base / name, *base.glob(f"*/{name}")]:
        try:
            sha = json.loads(path.read_text()).get("commit_sha")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(sha, str) and sha and _git_ok("merge-base", "--is-ancestor", sha, head):
            return True
    return False


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def _in_commit_span(session: Path, call: str) -> bool:
    """Whether the dispatch record of tool call ``call`` in the session transcript
    lies in a /commit span: the latest human-typed harness command before it is
    /commit (lib/command_span's rule of a typed command)."""
    import command_span  # hooks/lib, stdlib only (P5 R10)

    needle = json.dumps(call).encode()
    try:
        with open(session, "rb") as fh:
            line = next((n for n, raw in enumerate(fh, 1) if needle in raw and b'"tool_use"' in raw), 0)
    except OSError:
        return False
    before = [cmd for n, cmd, _args in command_span.openers(session) if n < line]
    return bool(line) and bool(before) and before[-1] == "commit"


def _refused_inflight_token_write(repo_root: str, repo_hash: str, branch: str, head: str) -> str | None:
    """The subagent transcript recording an in-flight /commit's refused token
    Write for HEAD, else None: a changelog-analyst subagent (its meta), whose
    dispatch lies in a /commit span, Wrote a push-gate token path of this
    repository hash and branch whose content names HEAD, this repository and
    BRANCH, and the Write came back refused by the tool policy. Only transcripts
    written to since HEAD's commit are read, each only when its bytes name the
    repository's token directory."""
    projects = Path(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")) / "projects"
    try:
        committed = int(_git_out("log", "-1", "--format=%ct", head) or 0)
    except ValueError:
        return None
    needle = f"/agentic-commit/push/{repo_hash}/".encode()
    name = branch.replace("/", "__")
    for agent in projects.glob("*/*/subagents/agent-*.jsonl"):
        try:
            if agent.stat().st_mtime < committed - 1:
                continue
            data = agent.read_bytes()
            if needle not in data:
                continue
            meta = json.loads(agent.with_suffix(".meta.json").read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict) or meta.get("agentType") != "changelog-analyst":
            continue
        call, session = meta.get("toolUseId"), agent.parent.parent
        if not isinstance(call, str) or not call:
            continue
        writes, refused = {}, set()
        for raw in data.splitlines():
            if needle not in raw and b'"tool_result"' not in raw:
                continue
            try:
                content = (json.loads(raw).get("message") or {}).get("content")
            except (ValueError, AttributeError):
                continue
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") == "Write":
                    ti = block.get("input") if isinstance(block.get("input"), dict) else {}
                    m = _REFUSED_TOKEN_WRITE_RE.search(str(ti.get("file_path") or ""))
                    if m and m.group(1) == repo_hash and m.group(2) == name:
                        writes[block.get("id")] = ti.get("content")
                elif (block.get("type") == "tool_result" and block.get("is_error")
                      and _REFUSAL in _text_of(block.get("content"))):
                    refused.add(block.get("tool_use_id"))
        for use, content in writes.items():
            try:
                token = json.loads(content)
            except (TypeError, ValueError):
                continue
            if (use in refused and isinstance(token, dict) and token.get("commit_sha") == head
                    and token.get("branch") == branch
                    and os.path.realpath(str(token.get("repo_root") or "/nonexistent")) == os.path.realpath(repo_root)
                    and _in_commit_span(session.parent / (session.name + ".jsonl"), call)):
                return str(agent)
    return None


def _inflight_token(repo_hash: str, branch: str, head: str) -> None:
    """Step 9b: the token for HEAD by its one writer, on the record of an
    in-flight /commit's refused token Write (module docstring). Never fails
    the push: on any miss push.sh decides as before (its exit 3)."""
    try:
        root = _git_out("rev-parse", "--show-toplevel")
        if not root or hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:16] != repo_hash:
            return
        if _token_names_ancestor(repo_hash, branch, head):
            return
        record = _refused_inflight_token_write(root, repo_hash, branch, head)
        if record is None:
            return
        r = subprocess.run([sys.executable, _TOKEN_WRITER, "--repo-root", root, "--branch", branch,
                            "--commit", head], capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            print(f"execute-push: no push-gate token named HEAD {head}; an in-flight /commit's token Write "
                  f"was refused ({record}), so its one writer wrote it: {r.stdout.strip()}", flush=True)
        else:
            print(f"execute-push: the push-gate token for HEAD {head} was not written "
                  f"(write-push-gate-token.py exit {r.returncode}): {r.stderr.strip()}", file=sys.stderr)
    except Exception as exc:  # the push itself is push.sh's decision
        print(f"execute-push: in-flight token check skipped: {exc}", file=sys.stderr)


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

    # Step 9b: in-flight compatibility (module docstring): an in-flight /commit's
    # token, refused to its Write, by the token's one writer, before push.sh reads it.
    _inflight_token(repo_hash, branch, current_head)

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
