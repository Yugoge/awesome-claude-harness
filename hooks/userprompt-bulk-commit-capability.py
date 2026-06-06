#!/usr/bin/env python3
"""UserPromptSubmit hook: mint the /commit --bulk capability from the trusted
human prompt, NOT from an LLM-emitted Bash command.

Why this exists (design "1B" — capability minted by trusted code, not by an
LLM fragile exact-string):
  The bulk-commit privilege guard (pretool-git-privilege-guard.py) authorizes
  `auto-bulk:` commits only when a bulk-commit sentinel exists. Historically
  that sentinel was written by the /commit --bulk Step 5 *LLM Bash command*
  (`source venv/bin/activate && python3 .../write-bulk-commit-sentinel.py`),
  which the bash-safety Layer 1.F gate accepts ONLY as one exact start-to-end
  string. An LLM orchestrator routinely adds benign noise (cd, echo, 2>&1,
  ; echo EXIT), breaking that exact-match gate and silently failing the bulk
  commit. The contract "LLM emits one perfect shell string" is not a reliable
  availability/security boundary.

  Trust root: an LLM cannot self-invoke a `disable-model-invocation: true`
  slash command. Therefore a `/commit ... --bulk` appearing in the
  UserPromptSubmit payload is proof the *human* authorized a bulk commit. This
  hook runs in-process as trusted code (it never goes through the Bash tool /
  bash-safety) and mints the sentinel directly the moment the human submits
  `/commit --bulk` — removing the LLM-in-the-middle fragility entirely.

Behavior:
  - Non-blocking: ALWAYS exits 0 (a UserPromptSubmit hook must never block the
    user's prompt).
  - Mints ONLY when the prompt is a /commit invocation carrying a --bulk
    word-boundary flag. Plain `/commit <task-id>` (non-bulk) is a no-op — that
    path uses the separate single-use commit grant, unchanged.
  - Reuses scripts/write-bulk-commit-sentinel.py as the single source of truth
    for the sentinel shape, stamping origin="userpromptsubmit-hook" so a future
    guard-side provenance check (staged lockdown) can require it.
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
_WRITER_PATH = _SCRIPTS_DIR / "write-bulk-commit-sentinel.py"

# Leading-/commit detector and a --bulk word-boundary flag detector. Mirrors the
# /commit Step 1 parse: first token is the command, --bulk appears as its own token.
_COMMIT_RE = re.compile(r"^\s*/commit(?:\s|$)")
_BULK_FLAG_RE = re.compile(r"(?:^|\s)--bulk(?:\s|$)")


def _is_bulk_commit(prompt: str) -> bool:
    if not prompt or not _COMMIT_RE.match(prompt):
        return False
    args = re.sub(r"^\s*/commit", "", prompt, count=1)
    return bool(_BULK_FLAG_RE.search(args))


def _mint(sid: str) -> None:
    """Mint the bulk-commit sentinel via the canonical writer module (loaded by
    path because the filename contains hyphens, which import_module rejects)."""
    spec = importlib.util.spec_from_file_location("_wbcs_writer", _WRITER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load writer at {_WRITER_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # write-bulk-commit-sentinel.py main() honors --sid and (new) --origin.
    mod.main(["--sid", sid, "--origin", "userpromptsubmit-hook"])


def main() -> int:
    try:
        try:
            data = json.load(sys.stdin)
        except Exception:
            return 0  # never block prompt submission
        if not isinstance(data, dict):
            return 0
        prompt = data.get("prompt", "")
        if not isinstance(prompt, str):
            return 0
        sid_raw = data.get("session_id", "")
        sid = str(sid_raw) if sid_raw is not None else ""
        if not _is_bulk_commit(prompt):
            return 0  # not a bulk commit -> no-op
        if not sid:
            # No session id to scope the sentinel; commit.md Step 5 fallback handles it.
            print(
                "[bulk-commit-capability] /commit --bulk seen but no session_id; "
                "deferring to /commit Step 5 fallback",
                file=sys.stderr,
            )
            return 0
        try:
            _mint(sid)
        except SystemExit:
            pass
        except Exception as exc:  # noqa: BLE001 - hook must never block
            print(f"[bulk-commit-capability] mint skipped: {exc}", file=sys.stderr)
            return 0
        print(
            f"[bulk-commit-capability] bulk-commit capability minted for session {sid}",
            file=sys.stderr,
        )
        return 0
    except Exception:
        # Absolute backstop: a UserPromptSubmit hook must never block the prompt.
        return 0


if __name__ == "__main__":
    sys.exit(main())
