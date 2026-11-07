#!/usr/bin/env python3
# STUB: the push-gate token is written by scripts/write-push-gate-token.py, which checks before
# the write that its commit is a commit object and live HEAD at its repository root (the rule
# this hook applied after a Write of the token); no Write of the token is left to match.
"""PostToolUse (matcher Write): exit-0 stub kept at its registered path (D15).

The push gate stays, with its reconciliation path (owner's decision, 2026-09-05).
/commit writes the token after a real commit (scripts/write-push-gate-token.py);
hooks/push.sh passes only while a token names an ancestor of HEAD. It evidences that
HEAD came through the sanctioned commit path, against loss and mistake, not an
adversary. Reconciliation (agents/changelog-analyst.md) writes a missing token for a
commit already at HEAD, attributed by hooks/lib/commit_journal.py; without it a commit
that lost its token stays unpushable. Removing it would have cut 1 of the 15 round-4
audit findings; hardening was declined, as each added check brings its own audit
surface. Accepted residual: on a same-parent race the reconciled commit can be a
peer's. Out of scope, not foreclosed: the journal hook writing the token itself.
"""
import sys

sys.exit(0)
