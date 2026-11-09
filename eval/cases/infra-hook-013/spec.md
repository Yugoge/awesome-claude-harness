# Infra-Hook Eval Case infra-hook-013: stop-post-compaction.py

## Trigger
Stop hook (no matcher). Hook fires after Claude Code emits the
compaction signal in the JSONL transcript.

## Behavior Required
- Reads Stop hook input JSON on stdin and detects the
  `compaction_occurred: true` flag if present.
- Walks the session JSONL transcript to identify entries marked as
  compacted summaries.
- Computes a delta of which TodoWrite items remained unaddressed
  before compaction and writes a recovery hint to
  `~/.claude/sessions/<session>/post-compaction-recovery.md`.
- Updates the session memory file to flag that compaction occurred so
  the next prompt can warn the orchestrator.
- Skips entirely (no-op exit 0) if no compaction signal is present.

## Exit Code Contract
- exit 0: compaction was processed OR no compaction signal observed.
- exit 2: transcript file missing OR parse failure on JSONL.

## Acceptance
- AC-1: synthetic transcript with `compaction_occurred: true` produces
  the recovery markdown file with at least one TodoWrite delta entry.
- AC-2: transcript without compaction signal yields exit 0 and creates
  no recovery file.
- AC-3: corrupt JSONL (truncated mid-line) yields exit 2 with stderr
  naming the transcript path.
