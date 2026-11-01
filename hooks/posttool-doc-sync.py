#!/usr/bin/env python3
"""
PostToolUse Hook: keep the marked INDEX.md, README.md and CLAUDE.md sections in sync
when structural files change (it updates files that exist and creates none).

Delegates to doc_sync module. See doc_sync/ directory for implementation.
Hook type: PostToolUse (Write|Edit|NotebookEdit matcher)
Exit codes: 0 always (never blocks)
"""

from doc_sync.main import main

if __name__ == '__main__':
    main()
