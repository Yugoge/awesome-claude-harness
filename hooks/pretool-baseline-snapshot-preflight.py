#!/usr/bin/env python3
# pretool-baseline-snapshot-preflight.py — PreToolUse hook (matcher: Agent)
#
# Purpose: Block a dev-role Agent dispatch whose rendered prompt omits the
# baseline_dirty_snapshot: field. This hook is designed to turn the
# documentation-only contract at agents/dev.md:535 (the orchestrator
# captures this snapshot before dev dispatch) into a runtime checkpoint
# mechanism -- one that will enforce that contract once registered (it is
# not yet registered; see Activation note below). Without this check,
# "forgetting to capture at dispatch time" passes silently and the
# downstream ownership gate (scripts/resolve-commit-repos.py) can later
# reject a fully compliant dev-report as if it carried unaccounted edits
# (backlog #119, real incident task 20260923-083731).
#
# Positive identification of a dev-role dispatch (BOTH required, per the
# fixed commands/dev.md Step 10 template markers at :825 and :835):
#   - the literal string "You are the dev subagent." appears in the prompt
#   - the label "baseline_head_sha:" appears in the prompt
# Any dispatch not matching BOTH markers is not treated as dev-role and
# exits 0 unconditionally (fail-open on ambiguity -- a BA/QA/specialist
# dispatch must never be false-blocked by this hook).
#
# No-op conditions (exits 0):
#   1. stdin is not valid JSON.
#   2. tool_input (or toolInput) is absent, or its "prompt" value is absent
#      or not a string.
#   3. The prompt is not positively identified as a dev-role dispatch (see
#      above).
#   4. The prompt IS a dev-role dispatch and the label
#      "baseline_dirty_snapshot:" appears anywhere in it (any value,
#      including an empty string, is a documented-legitimate value per
#      agents/dev.md:533).
#
# Blocking condition (exits 2):
#   The prompt is positively identified as a dev-role dispatch AND the
#   label "baseline_dirty_snapshot:" does not appear anywhere in it.
#
# Field-existence is the ONLY thing this hook checks. It does NOT validate
# the porcelain shape/content of baseline_dirty_snapshot's value -- that is
# a separate, consumer-side concern (scripts/resolve-commit-repos.py).
#
# Input JSON shape (stdin), matching the existing hooks/pretool-gitignore-
# preflight.py pattern:
#   {"tool_name": "Agent", "tool_input": {"prompt": "... baseline_head_sha: "
#    "<...> baseline_dirty_snapshot: <...> ..."}}
#   Prompt is extracted via data.get("tool_input") or data.get("toolInput")
#   then .get("prompt", "").
#
# Activation note: as of this writing this hook is NOT registered in
# settings.json's "Agent" matcher hooks array (settings.json:553-581), so it
# provides zero runtime interception until that registration lands in a
# future change. See docs/reference/harness-issues-backlog.md #119.

import json
import sys

DEV_ROLE_MARKER = "You are the dev subagent."
BASELINE_HEAD_SHA_LABEL = "baseline_head_sha:"
BASELINE_DIRTY_SNAPSHOT_LABEL = "baseline_dirty_snapshot:"


def is_dev_role_dispatch(prompt):
    """True only if BOTH fixed Step 10 template markers are present."""
    return DEV_ROLE_MARKER in prompt and BASELINE_HEAD_SHA_LABEL in prompt


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = data.get("toolInput")
    if not isinstance(tool_input, dict):
        tool_input = {}

    prompt = tool_input.get("prompt", "")
    if not isinstance(prompt, str):
        sys.exit(0)

    if not is_dev_role_dispatch(prompt):
        sys.exit(0)

    if BASELINE_DIRTY_SNAPSHOT_LABEL in prompt:
        sys.exit(0)

    print(
        "BLOCKED: dev-role Agent dispatch prompt is missing the required "
        "'baseline_dirty_snapshot:' field (agents/dev.md:535 assigns the "
        "orchestrator responsibility to capture and include this snapshot "
        "before dev dispatch). This is an upstream dispatch defect -- "
        "capture 'git status --porcelain' and add the "
        "'baseline_dirty_snapshot:' line to the prompt before retrying.",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
