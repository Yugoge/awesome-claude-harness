#!/usr/bin/env bash
# STUB: the QA-fail loop re-dispatches dev with the QA report path; no context is merged any more.
# refine-context.sh <orig-ctx> <qa-report> <iteration> [out] stays at its path for a
# /dev-overnight session still running the earlier Step 17 text, which redirects this
# script's output into the next iteration's context file: it passes BA's context through
# unchanged, so that dispatch still reads the context BA wrote, and always exits 0.
[ -r "${1:-}" ] && cat -- "$1" > "${4:-/dev/stdout}"
exit 0
