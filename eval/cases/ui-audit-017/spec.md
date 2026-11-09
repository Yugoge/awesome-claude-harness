# UI-Audit Eval Case ui-audit-017: Utility multi-file upload tool

## App Description
Web-based bulk file uploader built on SvelteKit with a tus.io resumable-
upload backend. Primary user is a media specialist uploading hundreds of
files per session, often multiple gigabytes total. The app must surface
detailed per-file progress, retry failed uploads automatically, and remain
responsive while transferring.

## Routes to Audit
- /
- /upload
- /upload/queue
- /upload/active
- /upload/completed
- /upload/failed
- /history

## Audit Focus
Drag-and-drop drop-zone affordance and visible-state changes during
hover/drop, per-file progress bar contrast, retry button discoverability
on failed-upload rows, queue-management interactions (pause, resume,
cancel), and overall UI responsiveness while a hypothetical 200-file
queue is in flight.

## Acceptance
- 7 routes captured at both viewports (>= 14 shots).
- Drop-zone hover state is visually distinct (not color-only).
- Progress-bar APCA Lc >= 60 against the page background.
- Retry, pause, cancel actions reachable by keyboard from the queue table.
- Final verdict PASS or WARNING.
