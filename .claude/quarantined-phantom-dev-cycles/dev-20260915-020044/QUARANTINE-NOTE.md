# Quarantine: phantom /dev cycle `dev-20260915-020044`

This directory holds 22 files relocated from a `/dev` invocation that was never
requested. At 2026-09-15 ~02:00Z a user message quoted (for reference, not
invocation) another workspace's title, whose literal text happened to be a
command line; the harness's command-detection mechanism could not distinguish
"quoting a command string" from "issuing a command" and fired a real `/dev`
run, minting task-id `dev-20260915-020044`. No development was requested and
none occurred. Full account, search method, and the true-positive/excluded
inventory: `docs/reference/quarantine-record-dev-20260915-020044.md` (outside
this directory), which cross-references the original incident record at
`docs/dev/specs/spec-20260914-052140.md`, Section 5.4's twin entry — the
"### 5.4 的孪生病症(反方向):散文中引用的命令文本被当真触发" subsection
(heading-anchored, not line-numbered — that spec file is under active,
ongoing edit by a different, concurrent session in this shared multi-session
worktree, so a line-number citation would silently drift out of true again
regardless of what number was written; verified current at correction-pass
time, 2026-09-15, matching the citation form already corrected in the
disclosure record outside this directory).

Every file below this directory is moved here verbatim (byte-identical, `mv`
only, never copied or deleted) under its full original repo-relative path, so
`<this-dir>/<original relative path>` always resolves to the original
location. See `original-path-manifest.json` in this directory for the exact
original-path -> quarantined-path mapping plus size/sha256 for every file, for
full retrievability.
