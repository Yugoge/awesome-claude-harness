#!/usr/bin/env python3
"""Line-precise (hunk-filtered) staging primitive — fail-closed.

Stages ONLY this cycle's owned hunks within a single already-authorized file,
leaving any peer (unattributed) hunks unstaged in the working tree. Ownership is
derived from dev's own authored content (the owned-edits ledger), NOT from a
file-state snapshot — so it is immune to peer timing/interleaving. A pre-edit
snapshot is used ONLY for a fail-closed out-of-owned-region cross-check.

Usage:
  stage-owned-hunks.py --git-root <root> --file <repo-rel-path> \
      --ledger <ledger.json> --snapshot <snapshot-file> [--dry-run]
  stage-owned-hunks.py --git-root <root> --file <repo-rel-path> \
      --checkpoint-provenance <entry.json> --task-id <task-id> [--plan-only]
  stage-owned-hunks.py --git-root <root> --file <repo-rel-path> \
      --provenance-plan <aggregate-or-path-plan.json> --task-id <task-id> \
      [--plan-only] [--approved-sha256 <digest>]
  stage-owned-hunks.py --git-root <root> --file <repo-rel-path> \
      --untracked-modified-report <canonical-dev-report.json> \
      --report-sha256 <digest> --task-id <task-id> \
      [--plan-only] [--approved-sha256 <digest>]

  --ledger    JSON file: list of {"old": "...", "new": "..."} owned edits for THIS
              file, in the order dev applied them. Line numbers (if present) are
              ADVISORY only and ignored by ownership logic.
  --snapshot  Path to a file holding the EXACT pre-edit (pre-first-edit) bytes of
              the worktree file (the cross-check trust anchor).
  --checkpoint-provenance  Immutable task-bound base/end checkpoint record.
  --provenance-plan  Ordered checkpoint + live-ledger provenance segments. The
              input may be one path plan or a canonical report containing a
              provenance_segments map.
  --untracked-modified-report  Canonical report containing an exact, report-
              digest-bound pre-edit/final hash and ``??`` status attestation for
              a pre-existing untracked path in dev.files_modified (never
              dev.files_created). This deliberately records adoption of an
              authenticated pre-existing file; it does not relabel it as newly
              created by the cycle.
  --report-sha256  SHA-256 of the canonical report already bound into the
              repository plan. Required with --untracked-modified-report.
  --plan-only  Compute exact selected patch/digest against a temporary index.
  --dry-run    Ledger path only: emit INCLUDE/EXCLUDE diagnostic without modifying
               the git index or working tree.
  --approved-sha256  Fail closed unless recomputed selected bytes have this digest.

Exit codes:
  0   owned hunks staged (or empty owned diff -> no-op, nothing to stage)
  10  EXCLUDED (fail-closed) — ambiguity, peer entanglement, or apply reject.
      Reason printed to stderr. Caller MUST warn-and-skip (NEVER whole-file stage).
  2   hard/usage error (also treated as EXCLUDE by the caller)

Design invariant (PROCEED iff): the file is staged ONLY when reconstructing the
worktree with every owned range reverted to its recorded `old_string` yields bytes
BYTE-IDENTICAL to the pre-edit snapshot. Any unattributed byte change must occupy
either owned bytes (caught by the byte-match check) or non-owned bytes (caught by
the cross-check) -> EXCLUDE. There is no fail-open path: for the --ledger/--snapshot
path, this is enforced not only by the pre-apply forward-replay check but also by an
explicit post-apply INDEX read-back (I13-post-apply-mismatch) -- `git apply
--cached`'s exit code alone is never trusted as proof of correct placement.

Session-private index (scripts/lib/session_index.py / scripts/session-index.py):
this script never names or imports either -- it needs no code of its own to honor
one. Every git invocation here goes through `_git()`, which passes its `env`
argument straight to `subprocess.run` and defaults to `None`, which means "inherit
this process's environment" (Python subprocess semantics), and git's own
`--git-path index` resolution (used internally, e.g. by `_temporary_index()`)
already honors `$GIT_INDEX_FILE` (verified directly: `GIT_INDEX_FILE=/tmp/x git
rev-parse --git-path index` prints `/tmp/x`, not `.git/index`). So a caller that
exports `GIT_INDEX_FILE` before invoking this script as a subprocess -- exactly
what `agents/changelog-analyst.md`'s Phase 3 does via
`eval "$(session-index.py init ...)"` before it ever calls this script -- gets
every `add`/`rm`/`show :path`/`diff --cached` call in this file transparently
redirected to that private index, with zero special-casing here. Adding an
explicit session-index.py call inside this script would be redundant with (and
could conflict with) the caller's own `init`/`export`/`sync-shared` lifecycle, and
would break callers (tests, `--dry-run` probes) that legitimately invoke this
script against the ordinary shared index with no private index ever seeded. If a
future caller needs this script to use the shared index deliberately even when
`GIT_INDEX_FILE` happens to be set in its environment, unset it before invoking --
this script has no flag for that override and should not grow one that duplicates
what the environment already expresses.
"""

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# Exit codes
OK = 0
EXCLUDE = 10
HARD = 2


def _excluded(reason):
    sys.stderr.write("EXCLUDE (fail-closed): %s\n" % reason)
    return EXCLUDE


def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def _git(git_root, args, input_bytes=None, env=None):
    """Run a git command; return (returncode, stdout_bytes, stderr_text)."""
    proc = subprocess.run(
        ["git", "-C", git_root] + args,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr.decode("utf-8", "replace")


def _tree_entry(git_root, commit, rel):
    rc, out, _ = _git(git_root, ["ls-tree", commit, "--", rel])
    if rc or not out:
        return None
    try:
        meta, path = out.rstrip(b"\n").split(b"\t", 1)
        mode, kind, blob = meta.decode().split()
    except ValueError:
        return None
    return (mode, kind, blob, path.decode())


def _checkpoint_patch(git_root, base, end, rel, context=0):
    entry = _tree_entry(git_root, base, rel)
    file_mode = 0o755 if entry and entry[0] == "100755" else 0o644
    with tempfile.TemporaryDirectory() as td:
        paths = []
        for name, rev in (("a", base), ("b", end)):
            rc, data, err = _git(git_root, ["show", "%s:%s" % (rev, rel)])
            if rc:
                return None, err
            path = os.path.join(td, name)
            with open(path, "wb") as fh:
                fh.write(data)
            os.chmod(path, file_mode)
            paths.append(path)
        proc = subprocess.run(
            ["git", "diff", "--no-index", "-U%d" % context, "--src-prefix=a/",
             "--dst-prefix=b/", "--", *paths],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if proc.returncode not in (0, 1):
            return None, proc.stderr.decode("utf-8", "replace")
        return _rewrite_patch_paths(proc.stdout, rel), ""


def _validate_checkpoint_record(git_root, rel, item, expected_task_id):
    """Validate immutable checkpoint evidence and return its patches/mode."""
    if not isinstance(item, dict) or item.get("task_id") != expected_task_id:
        return _excluded("checkpoint provenance task binding missing or mismatched")
    rationale = item.get("scope_rationale")
    if item.get("path") != rel or not isinstance(rationale, str) or len(rationale) < 20:
        return _excluded("checkpoint provenance path/rationale missing or mismatched")

    bound = False
    root = os.path.realpath(git_root)
    for artifact in item.get("binding_artifacts", []):
        if (not isinstance(artifact, dict)
                or not isinstance(artifact.get("path"), str)):
            continue
        candidate = os.path.realpath(os.path.join(root, artifact["path"]))
        if os.path.commonpath((root, candidate)) != root:
            continue
        try:
            raw = _read_bytes(candidate)
            report = json.loads(raw)
        except (OSError, ValueError):
            continue
        claimed = report.get("do", {})
        modified = claimed.get("files_modified", [])
        created = claimed.get("files_created", [])
        paths = modified + created if isinstance(modified, list) and isinstance(created, list) else []
        if (report.get("source") == "do" and rel in paths
                and hashlib.sha256(raw).hexdigest() == artifact.get("sha256")):
            bound = True
            break
    if not bound:
        return _excluded("no digest-bound prior task artifact claims this path")

    base = item.get("base_commit", "")
    end = item.get("owned_end_commit", "")
    if any(not isinstance(v, str) or len(v) != 40
           or any(c not in "0123456789abcdef" for c in v)
           for v in (base, end)):
        return _excluded("checkpoint IDs must be full lowercase object IDs")
    for rev in (base, end):
        rc, kind, _ = _git(git_root, ["cat-file", "-t", rev])
        if rc or kind.strip() != b"commit":
            return _excluded("checkpoint commit object missing: %s" % rev)
    rc, _, _ = _git(git_root, ["merge-base", "--is-ancestor", base, end])
    if rc:
        return _excluded("checkpoint interval is not ancestor ordered")

    before = _tree_entry(git_root, base, rel)
    after = _tree_entry(git_root, end, rel)
    if not before or not after or before[1] != "blob" or after[1] != "blob":
        return _excluded("path/blob absent from checkpoint tree")
    if before[0] != after[0] or before[0] not in ("100644", "100755"):
        return _excluded("mode-changing checkpoint interval is not hunk-splittable")
    if before[2] != item.get("base_blob") or after[2] != item.get("owned_end_blob"):
        return _excluded("declared path blob does not match checkpoint tree")
    rc, base_bytes, _ = _git(git_root, ["show", "%s:%s" % (base, rel)])
    rc2, end_bytes, _ = _git(git_root, ["show", "%s:%s" % (end, rel)])
    # Not the screening stage's concern: these are COMMIT-TREE blobs the stage
    # never sees, and the question is whether they are hunk-splittable at all,
    # not whether check-in conversion would alter a candidate image.
    if rc or rc2 or any(_is_binary(data) for data in (base_bytes, end_bytes)):
        return _excluded("binary or unreadable checkpoint path")

    patch, error = _checkpoint_patch(git_root, base, end, rel)
    if patch is None or not patch.strip():
        return _excluded("checkpoint patch missing or empty: %s" % error)
    validation_patch, error = _checkpoint_patch(git_root, base, end, rel, context=3)
    if validation_patch is None:
        return _excluded("checkpoint validation patch unavailable: %s" % error)
    return {
        "patch": patch,
        "validation_patch": validation_patch,
        "mode": before[0],
    }


def _apply_worktree_patch(data, patch, rel, mode, reverse=False):
    """Apply a patch to in-memory bytes via an isolated temporary repository."""
    with tempfile.TemporaryDirectory() as td:
        candidate = os.path.join(td, rel)
        os.makedirs(os.path.dirname(candidate), exist_ok=True)
        with open(candidate, "wb") as fh:
            fh.write(data)
        os.chmod(candidate, 0o755 if mode == "100755" else 0o644)
        subprocess.run(["git", "-C", td, "init", "-q"], check=True)
        args = ["git", "-C", td, "apply", "--recount", "--unidiff-zero"]
        if reverse:
            args.append("--reverse")
        args.append("-")
        proc = subprocess.run(
            args, input=patch,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if proc.returncode:
            return None
        return _read_bytes(candidate)


def _encode_edit_value(value):
    return value.encode("utf-8") if isinstance(value, str) else value


def _replay_live(snapshot, edits, rel):
    """Validate and replay one live ledger against its own trust anchor."""
    if not isinstance(edits, list) or not edits:
        return None, "live owned-edits ledger empty/invalid for %s" % rel
    replay = snapshot
    for i, edit in enumerate(edits):
        if not isinstance(edit, dict) or "old" not in edit or "new" not in edit:
            return None, "ledger entry %d malformed (need old+new) for %s" % (i, rel)
        old_b = _encode_edit_value(edit["old"])
        new_b = _encode_edit_value(edit["new"])
        if not isinstance(old_b, bytes) or not isinstance(new_b, bytes):
            return None, "ledger entry %d values must be strings/bytes for %s" % (i, rel)
        try:
            off = _locate_unique(replay, old_b)
        except EmptyOwnedOldStringError as exc:
            return None, "ledger entry %d has an empty old_string for %s: %s" % (i, rel, exc)
        if off is None:
            return None, (
                "owned old_string for edit %d not uniquely locatable during replay "
                "(absent or duplicated at this step) -> ambiguous: %s" % (i, rel)
            )
        replay = replay[:off] + new_b + replay[off + len(old_b):]
    return replay, ""


def _live_patch(snapshot, replay, rel, context=0):
    with tempfile.TemporaryDirectory() as td:
        a_path = os.path.join(td, "a")
        b_path = os.path.join(td, "b")
        with open(a_path, "wb") as fh:
            fh.write(snapshot)
        with open(b_path, "wb") as fh:
            fh.write(replay)
        proc = subprocess.run(
            ["git", "diff", "--no-index", "-U%d" % context, "--src-prefix=a/",
             "--dst-prefix=b/", "--", a_path, b_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    if proc.returncode not in (0, 1):
        return None, proc.stderr.decode("utf-8", "replace")
    return _rewrite_patch_paths(proc.stdout, rel), ""


def _tracked_mode(git_root, rel, env=None):
    # `env` is passed through ONLY when supplied, so the two-positional call
    # shape every existing caller (and every existing `_git` stub) relies on is
    # unchanged.
    args = ["ls-files", "-s", "--", rel]
    rc, out, _ = _git(git_root, args, env=env) if env else _git(git_root, args)
    if rc or not out:
        return None
    try:
        return out.split(None, 1)[0].decode("ascii")
    except (IndexError, UnicodeDecodeError):
        return None


def _worktree_mode(path):
    return "100755" if os.stat(path).st_mode & 0o111 else "100644"


def _patch_headers_and_hunks(patch):
    lines = patch.splitlines(keepends=True)
    header = []
    hunks = []
    current = None
    for line in lines:
        if line.startswith(b"@@ "):
            if current is not None:
                hunks.append(b"".join(current))
            current = [line]
        elif current is None:
            # Object IDs describe the full checkpoint endpoints, not a selected
            # subset. Omitting this line lets each owned hunk be tested against
            # the evolving temporary index independently.
            if not line.startswith(b"index "):
                header.append(line)
        else:
            current.append(line)
    if current is not None:
        hunks.append(b"".join(current))
    return b"".join(header), hunks


def _index_forward_anchor_resolve(current_bytes, segment, hunk):
    """Verify and re-resolve a live segment's pure-insertion hunk's TRUE
    insertion point in `current_bytes` (the scratch index buffer under
    test) -- the forward-direction counterpart of `_content_anchor_retry`'s
    reverse-direction resolution, reusing the same fail-closed primitives
    (`_resolve_pure_insertion_anchor`, `_locate_unique`, `_regenerate_hunk`)
    rather than reimplementing uniqueness logic.

    A zero-context pure-insertion hunk carries no old/context text, so
    `git apply` cannot fail to match it regardless of where it lands; its
    declared offset is meaningful only in the coordinate space of the
    segment's own `pre_edit_snapshot`, which the tracked index/HEAD this
    function verifies against is allowed to diverge from by design (see
    module docstring). Returns (corrected_hunk, anchor, inserted_text)
    positioned in `current_bytes`'s own coordinate space on a unique,
    verified anchor match; None otherwise (non-insertion hunk, or 0/2+
    anchor matches in the ledger or in `current_bytes`) -- fail-closed
    EXCLUDE, per the "no fail-open path" invariant.
    """
    parsed = _parse_hunk_header(hunk)
    if parsed is None or parsed[1] != 0:
        return None
    inserted_text = _hunk_inserted_text(hunk)
    if not inserted_text:
        return None
    anchor = _resolve_pure_insertion_anchor(segment, inserted_text)
    if not anchor:
        return None
    off = _locate_unique(current_bytes, anchor)
    if off is None:
        return None
    point = off + len(anchor)
    target = current_bytes[:point] + inserted_text + current_bytes[point:]
    corrected_hunk = _regenerate_hunk(current_bytes, target)
    if corrected_hunk is None:
        return None
    return corrected_hunk, anchor, inserted_text


def _filter_segments_against_index(git_root, rel, segments):
    """Return segment copies containing only hunks composable in one index.

    A `kind == "live"` segment's zero-context PURE-INSERTION hunk (old_count
    == 0) carries no old/context text, so the naive `git apply` below cannot
    fail to match it regardless of where it lands against this scratch
    index (a copy of the real tracked HEAD, which the hunk's own
    `pre_edit_snapshot`-relative offset is allowed to diverge from by
    design -- see module docstring). Such a hunk's true position is
    verified and re-resolved by content anchor via
    `_index_forward_anchor_resolve` BEFORE it is tested here: the CORRECTED
    hunk (not the raw, unverifiable one) is what is actually applied to
    this scratch index, so later hunks in this same pass are tested
    against an accurately-reconstructed buffer. The RAW hunk is still what
    is recorded in `patch_hunks`/`patch` -- `_filter_segments_against_worktree`
    needs that unchanged coordinate space for its own worktree-reversal
    round trip -- and the (anchor, inserted_text) pair is carried forward
    on `pending_insertions` so `_composed_main`'s existing staging-time
    re-resolution (added by 8bcb4532) positions it correctly against the
    REAL buffer it is finally staged into, exactly like an insertion
    corrected by the worktree-reversal leg. A hunk whose anchor cannot be
    uniquely resolved (0 or 2+ matches, in the ledger or in this buffer) is
    fail-closed EXCLUDEd here rather than accepted on an unverifiable
    offset. Every other hunk (non-insertion, or not `kind == "live"`) keeps
    the prior, unchanged behavior.
    """
    td = tempfile.mkdtemp()
    try:
        rc, index_path, err = _git(git_root, ["rev-parse", "--git-path", "index"])
        if rc:
            return None, "cannot resolve index: %s" % err
        source_index = index_path.decode().strip()
        if not os.path.isabs(source_index):
            source_index = os.path.join(git_root, source_index)
        plan_index = os.path.join(td, "index")
        shutil.copyfile(source_index, plan_index)
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = plan_index
        result = []
        for segment in segments:
            header, hunks = _patch_headers_and_hunks(segment["patch"])
            accepted = []
            pending = dict(segment.get("pending_insertions") or {})
            for hunk in hunks:
                to_apply, resolved = hunk, None
                if segment.get("kind") == "live":
                    rc_show, current_bytes, _ = _git(
                        git_root, ["show", ":%s" % rel], env=env
                    )
                    if not rc_show:
                        resolved = _index_forward_anchor_resolve(
                            current_bytes, segment, hunk
                        )
                    is_pure_insertion = (
                        _hunk_inserted_text(hunk) is not None
                        and _parse_hunk_header(hunk) is not None
                        and _parse_hunk_header(hunk)[1] == 0
                    )
                    if resolved is None and is_pure_insertion:
                        # A live pure-insertion hunk whose true anchor could
                        # not be uniquely re-resolved against this buffer --
                        # fail-closed EXCLUDE rather than trust its
                        # unverifiable snapshot-relative offset.
                        continue
                    if resolved is not None:
                        to_apply = resolved[0]
                candidate = header + to_apply
                rc, _, _ = _git(
                    git_root,
                    ["apply", "--cached", "--recount", "--unidiff-zero", "-"],
                    input_bytes=candidate, env=env,
                )
                if not rc:
                    accepted.append(hunk)
                    if resolved is not None:
                        pending[hunk] = (resolved[1], resolved[2])
            item = dict(segment)
            item["patch_header"] = header
            item["patch_hunks"] = accepted
            item["patch"] = header + b"".join(accepted) if accepted else b""
            item["original_hunk_count"] = segment.get("original_hunk_count", len(hunks))
            item["pending_insertions"] = pending
            result.append(item)
        return result, ""
    finally:
        shutil.rmtree(td)


_HUNK_HEADER_RE = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _parse_hunk_header(hunk):
    """Parse a -U0 hunk's leading `@@ -a[,b] +c[,d] @@` line.

    Returns (old_start, old_count, new_start, new_count) -- an omitted count
    defaults to 1 per unified-diff convention -- or None if malformed.
    """
    match = _HUNK_HEADER_RE.match(hunk.split(b"\n", 1)[0])
    if not match:
        return None
    old_count = int(match.group(2)) if match.group(2) is not None else 1
    new_count = int(match.group(4)) if match.group(4) is not None else 1
    return int(match.group(1)), old_count, int(match.group(3)), new_count


def _hunk_inserted_text(hunk):
    """Return the exact added bytes of a pure-insertion (-U0, old_count == 0)
    hunk body, or None if the body is not purely additions."""
    out = []
    for line in hunk.splitlines(keepends=True)[1:]:
        if line.startswith(b"+"):
            out.append(line[1:])
        elif line.rstrip(b"\r\n") == b"\\ No newline at end of file":
            continue
        else:
            return None
    return b"".join(out) if out else None


def _live_pure_insertion_anchor(edits, inserted_text):
    """Identify the unique ledger anchor for a pure-insertion hunk's added
    bytes: a ledger entry whose non-empty `old` is a prefix of `new` and whose
    suffix (the inserted content) matches `inserted_text` exactly. Returns the
    anchor bytes, or None when no such entry is unique (caller keeps today's
    line-offset-only behavior unchanged)."""
    if not isinstance(edits, list):
        return None
    matches = []
    for edit in edits:
        if not isinstance(edit, dict):
            continue
        old_b = _encode_edit_value(edit.get("old"))
        new_b = _encode_edit_value(edit.get("new"))
        if not isinstance(old_b, bytes) or not isinstance(new_b, bytes) or not old_b:
            continue
        if new_b.startswith(old_b) and new_b[len(old_b):] == inserted_text:
            matches.append(old_b)
    return matches[0] if len(matches) == 1 else None


def _checkpoint_pure_insertion_anchor(validation_patch, inserted_text):
    """Derive an anchor from the checkpoint's own context=3 validation patch
    (scripts/stage-owned-hunks.py's _checkpoint_patch): the context lines
    immediately preceding a pure-addition run matching `inserted_text`.
    Returns anchor bytes, or None (caller falls back unchanged)."""
    if not validation_patch:
        return None
    _, hunks = _patch_headers_and_hunks(validation_patch)
    matches = []
    for hunk in hunks:
        lines = hunk.splitlines(keepends=True)[1:]
        if any(line.startswith(b"-") for line in lines):
            continue  # not a pure addition; this fix targets pure insertions only
        added = b"".join(line[1:] for line in lines if line.startswith(b"+"))
        if added != inserted_text:
            continue
        context_before = []
        for line in lines:
            if line.startswith(b"+"):
                break
            if line.startswith(b" "):
                context_before.append(line[1:])
        anchor = b"".join(context_before)
        if anchor:
            matches.append(anchor)
    return matches[0] if len(matches) == 1 else None


def _resolve_pure_insertion_anchor(segment, inserted_text):
    """Return the non-empty anchor bytes for a pure-insertion hunk within
    `segment`, or None if no unique anchor can be derived for its kind."""
    if segment.get("kind") == "live":
        anchor = _live_pure_insertion_anchor(segment.get("edits"), inserted_text)
        if anchor:
            return anchor
        # Fallback: a ledger entry that replaces a whole surrounding block
        # (e.g. a rewritten method whose new body happens to add these exact
        # lines somewhere in its middle) is not a plain `new == old +
        # inserted_text` append, so the prefix/suffix check above cannot
        # match it even though the snapshot->replay BYTE diff still renders
        # it as a pure-insertion hunk. Re-derive the anchor the same way
        # _checkpoint_pure_insertion_anchor already does for the checkpoint
        # kind: from the stable, UNCHANGED context lines a context=3 diff of
        # this same snapshot->replay transformation places immediately
        # before the identical inserted_text -- content that does not
        # depend on how the ledger entry's own old/new strings were shaped.
        snapshot = segment.get("pre_edit_snapshot")
        replay = segment.get("replay")
        if isinstance(snapshot, (bytes, bytearray)) and isinstance(replay, (bytes, bytearray)):
            validation_patch, verr = _live_patch(snapshot, replay, "live", context=3)
            if not verr and validation_patch:
                return _checkpoint_pure_insertion_anchor(validation_patch, inserted_text)
        return None
    if segment.get("kind") == "checkpoint":
        return _checkpoint_pure_insertion_anchor(
            segment.get("validation_patch"), inserted_text
        )
    return None


def _regenerate_hunk(old_bytes, new_bytes):
    """Produce a fresh -U0 hunk (header discarded) for old_bytes -> new_bytes.

    Correct by construction from the real content offsets, per the ticket's
    recommended technique, instead of hand-rewriting a stale line-number
    header -- this is what makes the corrected position, not the original
    hunk's header, what downstream re-apply and staging actually use.
    """
    with tempfile.TemporaryDirectory() as td:
        a_path = os.path.join(td, "a")
        b_path = os.path.join(td, "b")
        with open(a_path, "wb") as fh:
            fh.write(old_bytes)
        with open(b_path, "wb") as fh:
            fh.write(new_bytes)
        proc = subprocess.run(
            ["git", "diff", "--no-index", "-U0", "--src-prefix=a/",
             "--dst-prefix=b/", "--", a_path, b_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    if proc.returncode not in (0, 1):
        return None
    _, hunks = _patch_headers_and_hunks(proc.stdout)
    return hunks[0] if len(hunks) == 1 else None


def _content_anchor_retry(before, rel, mode, segment, hunk):
    """Retry a pure-insertion hunk that failed the line-offset round trip by
    CONTENT: if the segment's own anchor context is uniquely locatable in
    `before` (the real worktree state at this point in the reversal loop) and
    the recorded inserted text is exactly where the anchor says it should be,
    accept it there and regenerate a hunk positioned in `before`'s own
    coordinate space -- unchanged from the prior fix (5ab61c99); this part
    (anchor location, insertion-presence verification, and the worktree-
    relative `corrected_hunk` used to prove reversibility against the real
    worktree) is confirmed correct in isolation and is not reopened here.

    `corrected_hunk`'s POSITION is only valid in the worktree-reversal-walk's
    own coordinate space, though -- NOT in the isolated per-segment index
    reconstruction _composed_main actually stages against, which may lack
    sibling-hunk or foreign content `before` includes (M1's own bug). Rather
    than trying to pick ONE position that would satisfy both buffers (they
    can genuinely differ), this function also returns the raw ingredients
    (`anchor`, `inserted_text`) a caller can use to re-resolve a FRESH,
    correctly-positioned hunk immediately before the real staging apply --
    see _composed_main's per-segment "pending_insertions" resolution.

    Returns (reversed_value, corrected_hunk, anchor, inserted_text) on a
    verified match; None leaves the existing fail-closed exclusion for this
    hunk unchanged (0 or 2+ anchor matches, a non-insertion hunk, or any
    inconsistency in reconstruction).
    """
    parsed = _parse_hunk_header(hunk)
    if parsed is None or parsed[1] != 0:
        return None
    inserted_text = _hunk_inserted_text(hunk)
    if not inserted_text:
        return None
    anchor = _resolve_pure_insertion_anchor(segment, inserted_text)
    if not anchor:
        return None
    off = _locate_unique(before, anchor)
    if off is None:
        return None  # absent or ambiguous in the real worktree -> unchanged EXCLUDE
    insertion_point = off + len(anchor)
    if before[insertion_point:insertion_point + len(inserted_text)] != inserted_text:
        return None  # anchor located, but the insertion isn't where it claims
    reversed_value = before[:insertion_point] + before[insertion_point + len(inserted_text):]
    corrected_hunk = _regenerate_hunk(reversed_value, before)
    if corrected_hunk is None:
        return None
    roundtrip = _apply_worktree_patch(
        reversed_value, segment["patch_header"] + corrected_hunk, rel, mode
    )
    if roundtrip != before:
        return None
    return reversed_value, corrected_hunk, anchor, inserted_text


def _filter_segments_against_worktree(worktree, rel, mode, segments):
    """Reverse composable hunks newest-first, omitting real current overlap.

    A pure-insertion hunk (old_count == 0) that fails the line-offset round
    trip is retried by content anchor (_content_anchor_retry) before being
    excluded -- see that helper for the acceptance/rejection contract. A
    retried hunk's (anchor, inserted_text) is carried forward on the returned
    segment as `pending_insertions` (keyed by the accepted hunk's own bytes)
    so _composed_main can re-resolve its position against the buffer it is
    actually staged against, immediately before that staging happens (M1) --
    `corrected_hunk` itself remains valid ONLY in this function's own
    worktree-reversal coordinate space (used above to prove reversibility).

    _composed_main's convergence loop calls this function repeatedly, and a
    hunk that was corrected on an earlier iteration is (by construction) now
    self-consistent with a PLAIN reversal against this same worktree -- so a
    later iteration accepts it via the "continue" path below without ever
    calling _content_anchor_retry again. That must not silently drop its
    `pending_insertions` entry (plain-reversal success here says nothing
    about validity in the DIFFERENT staging-time buffer): a hunk already
    flagged pending on the segment handed in stays pending.
    """
    candidate = worktree
    accepted_by_segment = [[] for _ in segments]
    pending_by_segment = [{} for _ in segments]
    for segment_index in range(len(segments) - 1, -1, -1):
        segment = segments[segment_index]
        header = segment["patch_header"]
        carried_pending = segment.get("pending_insertions") or {}
        for hunk in reversed(segment["patch_hunks"]):
            before = candidate
            reversed_value = _apply_worktree_patch(
                candidate, header + hunk, rel, mode, reverse=True
            )
            roundtrip = (
                _apply_worktree_patch(reversed_value, header + hunk, rel, mode)
                if reversed_value is not None else None
            )
            if reversed_value is not None and roundtrip == before:
                candidate = reversed_value
                accepted_by_segment[segment_index].append(hunk)
                if hunk in carried_pending:
                    pending_by_segment[segment_index][hunk] = carried_pending[hunk]
                continue
            retried = _content_anchor_retry(before, rel, mode, segment, hunk)
            if retried is not None:
                candidate, corrected_hunk, anchor, inserted_text = retried
                accepted_by_segment[segment_index].append(corrected_hunk)
                pending_by_segment[segment_index][corrected_hunk] = (anchor, inserted_text)
        accepted_by_segment[segment_index].reverse()
    result = []
    for segment, hunks, pending in zip(segments, accepted_by_segment, pending_by_segment):
        item = dict(segment)
        item["patch_hunks"] = hunks
        item["patch"] = item["patch_header"] + b"".join(hunks) if hunks else b""
        item["pending_insertions"] = pending
        result.append(item)
    return result, candidate


def _segment_signature(segments):
    return tuple(
        hashlib.sha256(segment.get("patch", b"")).hexdigest()
        for segment in segments
    )


def _load_provenance_plan(ns):
    try:
        with open(ns.provenance_plan, "r", encoding="utf-8") as fh:
            document = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, "provenance plan unreadable: %s" % exc
    if not isinstance(document, dict):
        return None, "provenance plan must be an object"
    if "provenance_segments" in document:
        mapping = document.get("provenance_segments")
        if not isinstance(mapping, dict) or ns.file not in mapping:
            return None, "canonical provenance has no segments for %s" % ns.file
        plan = {
            "task_id": document.get("task_id") or document.get("request_id"),
            "path": ns.file,
            "segments": mapping[ns.file],
        }
    else:
        plan = document
    if plan.get("task_id") != ns.task_id or plan.get("path") != ns.file:
        return None, "provenance plan task/path binding missing or mismatched"
    if not isinstance(plan.get("segments"), list) or not plan["segments"]:
        return None, "provenance plan segments missing or empty"
    return plan, ""


def _composed_main(ns, plan):
    """Validate ordered provenance and stage one final owned-only patch."""
    rel = ns.file
    worktree_path = os.path.join(ns.git_root, rel)
    worktree = _read_bytes(worktree_path)
    # Not the screening stage's concern: hunk-splittability, not conversion.
    if _is_binary(worktree):
        return _excluded("binary current worktree path: %s" % rel)
    index_mode = _tracked_mode(ns.git_root, rel)
    if index_mode not in ("100644", "100755"):
        return _excluded("target file is not a regular tracked index path: %s" % rel)
    current_mode = _worktree_mode(worktree_path)
    if current_mode != index_mode:
        return _excluded(
            "current worktree mode %s differs from attested index mode %s: %s"
            % (current_mode, index_mode, rel)
        )
    rc, _, _ = _git(ns.git_root, ["diff", "--cached", "--quiet", "--", rel])
    if rc:
        return _excluded("target file already has staged content")

    prepared = []
    saw_live = False
    for number, segment in enumerate(plan["segments"]):
        if not isinstance(segment, dict) or not isinstance(segment.get("source_worker"), str):
            return _excluded("provenance segment %d lacks source_worker" % number)
        kind = segment.get("kind")
        if kind == "checkpoint":
            if saw_live:
                return _excluded("checkpoint segment appears after live provenance")
            record = segment.get("checkpoint_provenance")
            expected = segment.get("source_task_id")
            validated = _validate_checkpoint_record(ns.git_root, rel, record, expected)
            if isinstance(validated, int):
                return validated
            if validated["mode"] != index_mode:
                return _excluded("checkpoint mode does not match current tracked mode")
            _, checkpoint_hunks = _patch_headers_and_hunks(validated["patch"])
            validated["original_hunk_count"] = len(checkpoint_hunks)
            prepared.append({"kind": kind, **validated})
        elif kind == "live":
            saw_live = True
            snapshot_value = segment.get("pre_edit_snapshot")
            if not isinstance(snapshot_value, str):
                return _excluded("live segment %d snapshot must be a string" % number)
            snapshot = snapshot_value.encode("utf-8")
            edits = segment.get("owned_edits")
            # Not the screening stage's concern: a per-segment HISTORICAL
            # snapshot, never the image this route intends the index to hold.
            if _is_binary(snapshot):
                return _excluded("binary live snapshot for %s" % rel)
            replay, error = _replay_live(snapshot, edits, rel)
            if replay is None:
                return _excluded(error)
            patch, error = _live_patch(snapshot, replay, rel)
            if patch is None or not patch.strip():
                return _excluded("live segment patch missing or empty: %s" % error)
            _, live_hunks = _patch_headers_and_hunks(patch)
            prepared.append({
                "kind": kind, "edits": edits, "patch": patch,
                "original_hunk_count": len(live_hunks),
                # Carried only so _resolve_pure_insertion_anchor's live-kind
                # fallback can re-derive a context=3 validation patch on
                # demand (mirrors the checkpoint kind's own validation_patch)
                # -- not otherwise read by the index/worktree filters.
                "pre_edit_snapshot": snapshot, "replay": replay,
            })
        else:
            return _excluded("unknown provenance segment kind at position %d" % number)

    # Intersect two independent facts hunk-by-hunk: application to the clean
    # index (foreign pre-base bytes excluded) and reversible presence in the real
    # current worktree (foreign post-end overlap excluded). Iterate because
    # dropping an earlier dependency can make a later hunk cease to compose.
    candidates = prepared
    total_hunks = sum(item["original_hunk_count"] for item in prepared)
    for _ in range(total_hunks + 1):
        indexed, error = _filter_segments_against_index(ns.git_root, rel, candidates)
        if indexed is None:
            return _excluded(error)
        current_filtered, reversed_bytes = _filter_segments_against_worktree(
            worktree, rel, index_mode, indexed
        )
        if _segment_signature(current_filtered) == _segment_signature(candidates):
            prepared = current_filtered
            break
        candidates = current_filtered
    else:
        return _excluded("provenance hunk composition did not converge")
    if not any(item["patch"].strip() for item in prepared):
        return _excluded("no provenance hunk is both index-composable and current-reversible")

    candidate = reversed_bytes
    for segment in prepared:
        for hunk in segment["patch_hunks"]:
            candidate = _apply_worktree_patch(
                candidate, segment["patch_header"] + hunk, rel, index_mode
            )
            if candidate is None:
                return _excluded("selected provenance hunk cannot replay in sequence")
    if candidate != worktree:
        return _excluded("ordered provenance is not a reversible current-worktree transform")

    env = None
    temporary_index = None
    if ns.plan_only:
        td = tempfile.mkdtemp()
        temporary_index = td
        rc, index_path, err = _git(ns.git_root, ["rev-parse", "--git-path", "index"])
        if rc:
            shutil.rmtree(td)
            return _excluded("cannot resolve index: %s" % err)
        source_index = index_path.decode().strip()
        if not os.path.isabs(source_index):
            source_index = os.path.join(ns.git_root, source_index)
        plan_index = os.path.join(td, "index")
        shutil.copyfile(source_index, plan_index)
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = plan_index
    try:
        for number, segment in enumerate(prepared):
            if not segment["patch"].strip():
                continue
            patch = segment["patch"]
            pending = segment.get("pending_insertions") or {}
            if pending:
                # M1: re-resolve each content-anchor-retried insertion's
                # position against the SAME buffer it is about to be staged
                # into (the running index, reflecting every earlier segment
                # already applied above) -- never the worktree-reversal
                # buffer `corrected_hunk` was positioned against, which may
                # contain sibling-hunk or foreign content this buffer lacks.
                rc, current_bytes, err = _git(ns.git_root, ["show", ":%s" % rel], env=env)
                if rc:
                    if not ns.plan_only:
                        _git(ns.git_root, ["restore", "--staged", "--", rel])
                    return _excluded(
                        "cannot read staging target for content-anchored "
                        "insertion in %s: %s" % (rel, err.strip())
                    )
                rebuilt_hunks = []
                for hunk in segment["patch_hunks"]:
                    record = pending.get(hunk)
                    if record is None:
                        # Not a retried insertion -- its declared position is
                        # already correct relative to this segment's own base
                        # (unchanged since generation). Actually apply it (in
                        # memory) so `current_bytes` keeps tracking the exact
                        # buffer a LATER pending insertion in this same
                        # segment will truly land in once every hunk before
                        # it has applied -- a fresh hunk's position must be
                        # cumulative-consistent with its neighbors, not just
                        # correct against the segment's raw, pre-hunk base.
                        advanced = _apply_worktree_patch(
                            current_bytes, segment["patch_header"] + hunk, rel, index_mode
                        )
                        if advanced is None:
                            if not ns.plan_only:
                                _git(ns.git_root, ["restore", "--staged", "--", rel])
                            return _excluded(
                                "cannot advance staging target past a prior "
                                "hunk while resolving a content-anchored "
                                "insertion for %s" % rel
                            )
                        rebuilt_hunks.append(hunk)
                        current_bytes = advanced
                        continue
                    anchor, inserted_text = record
                    off = _locate_unique(current_bytes, anchor)
                    if off is None:
                        if not ns.plan_only:
                            _git(ns.git_root, ["restore", "--staged", "--", rel])
                        return _excluded(
                            "content-anchored insertion anchor not uniquely "
                            "resolvable against the staging target for %s" % rel
                        )
                    point = off + len(anchor)
                    target = current_bytes[:point] + inserted_text + current_bytes[point:]
                    fresh_hunk = _regenerate_hunk(current_bytes, target)
                    if fresh_hunk is None:
                        if not ns.plan_only:
                            _git(ns.git_root, ["restore", "--staged", "--", rel])
                        return _excluded(
                            "cannot regenerate content-anchored insertion "
                            "against the staging target for %s" % rel
                        )
                    rebuilt_hunks.append(fresh_hunk)
                    current_bytes = target  # keep cumulative for >1 pending insertion in one segment
                patch = segment["patch_header"] + b"".join(rebuilt_hunks)
            rc, _, err = _git(
                ns.git_root,
                ["apply", "--cached", "--recount", "--unidiff-zero", "-"],
                input_bytes=patch, env=env,
            )
            if rc:
                if not ns.plan_only:
                    _git(ns.git_root, ["restore", "--staged", "--", rel])
                return _excluded(
                    "provenance segment %d does not apply to the composed index: %s"
                    % (number, err.strip())
                )
        # MODE readback, performed UNCONDITIONALLY -- not only when an approved
        # digest was supplied. Mode is read from the INDEX ENTRY the route just
        # wrote, never from the working tree, and compared against the index
        # mode this route already attested above. A git blob object id does not
        # encode file mode, so no content comparison can stand in for this.
        staged_mode = _tracked_mode(ns.git_root, rel, env=env)
        if staged_mode != index_mode:
            if not ns.plan_only:
                _git(ns.git_root, ["restore", "--staged", "--", rel])
            return _excluded(
                "file mode divergence for %s: the index entry records %s after "
                "staging but this route attested %s; nothing is left staged "
                "-> EXCLUDE" % (rel, staged_mode, index_mode))
        # The composed image exists only once the segments have been applied,
        # so it is read back from the index that holds it. Under --plan-only
        # that index is the temporary one and the real index is still
        # untouched; otherwise this is the post-apply re-probe and a refusal
        # unstages what was written.
        rc_show, composed, err_show = _git(ns.git_root, ["show", ":%s" % rel], env=env)
        if rc_show:
            if not ns.plan_only:
                _git(ns.git_root, ["restore", "--staged", "--", rel])
            return _excluded(
                "%s for %s: the composed index image is unreadable: %s "
                "-> EXCLUDE" % (SCREEN_INDETERMINATE_PREFIX, rel, err_show.strip()))
        reason = _screen_checkin_transform(
            ns.git_root, rel, composed, "composed index image")
        if reason is not None:
            if not ns.plan_only:
                _git(ns.git_root, ["restore", "--staged", "--", rel])
            return _excluded(reason)
        rc, selected, err = _git(
            ns.git_root,
            ["diff", "--cached", "--binary", "--full-index", "--", rel],
            env=env,
        )
        if rc or not selected:
            if not ns.plan_only:
                _git(ns.git_root, ["restore", "--staged", "--", rel])
            return _excluded("selected staged patch unavailable: %s" % err.strip())
        digest = hashlib.sha256(selected).hexdigest()
        if ns.approved_sha256 and digest != ns.approved_sha256:
            if not ns.plan_only:
                _git(ns.git_root, ["restore", "--staged", "--", rel])
            return _excluded(
                "approved patch digest mismatch for %s (expected %s, recomputed %s)"
                % (rel, ns.approved_sha256, digest)
            )
        payload = {
            "path": rel,
            "patch": selected.decode("utf-8"),
            "patch_sha256": digest,
            "segment_count": len(prepared),
            "checkpoint_hunks_excluded": sum(
                item.get("original_hunk_count", 0) - len(item.get("patch_hunks", []))
                for item in prepared if item["kind"] == "checkpoint"
            ),
            "live_hunks_excluded": sum(
                item.get("original_hunk_count", 0) - len(item.get("patch_hunks", []))
                for item in prepared if item["kind"] == "live"
            ),
            "reversed_worktree_sha256": hashlib.sha256(reversed_bytes).hexdigest(),
        }
        sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
        return OK
    finally:
        if temporary_index:
            shutil.rmtree(temporary_index)


def _checkpoint_main(ns):
    try:
        with open(ns.checkpoint_provenance, "r", encoding="utf-8") as fh:
            item = json.load(fh)
    except (OSError, ValueError) as exc:
        return _excluded("checkpoint provenance unreadable: %s" % exc)
    plan = {
        "task_id": ns.task_id,
        "path": ns.file,
        "segments": [{
            "kind": "checkpoint",
            "source_worker": "checkpoint",
            "source_task_id": ns.task_id,
            "checkpoint_provenance": item,
        }],
    }
    return _composed_main(ns, plan)


def _valid_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _claim_resolves_to(git_root, claim, target):
    if not isinstance(claim, str) or not claim or "\x00" in claim:
        return False
    expanded = os.path.expanduser(claim)
    candidate = expanded if os.path.isabs(expanded) else os.path.join(git_root, expanded)
    return os.path.realpath(candidate) == target


def _exact_untracked_status(git_root, rel):
    rc, output, _ = _git(
        git_root,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--", rel],
    )
    if rc:
        return False
    return output == b"?? " + os.fsencode(rel) + b"\0"


def _temporary_index(git_root):
    rc, index_path, error = _git(git_root, ["rev-parse", "--git-path", "index"])
    if rc:
        return None, None, error
    source = os.fsdecode(index_path).strip()
    if not os.path.isabs(source):
        source = os.path.join(git_root, source)
    # Keep the alternate index on the repository's own filesystem. Normal
    # commit admission must not become unavailable merely because the global
    # scratch partition is full, and same-filesystem placement also avoids a
    # cross-device copy. The directory is removed in every caller outcome.
    directory = tempfile.mkdtemp(
        prefix="claude-stage-plan-", dir=os.path.dirname(source)
    )
    target = os.path.join(directory, "index")
    if os.path.isfile(source):
        shutil.copyfile(source, target)
    else:
        # The normal /commit path requires an attached HEAD, but keeping the
        # primitive deterministic for an unborn repository costs little.
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = target
        rc, _, error = _git(git_root, ["read-tree", "--empty"], env=env)
        if rc:
            shutil.rmtree(directory)
            return None, None, error
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = target
    return directory, env, ""


def _load_untracked_modified_contract(ns, report_bytes):
    try:
        document = json.loads(report_bytes)
    except ValueError as exc:
        return None, "canonical dev report is invalid JSON: %s" % exc
    if not isinstance(document, dict):
        return None, "canonical dev report must be an object"
    identities = [
        document.get(field) for field in ("task_id", "request_id")
        if document.get(field) is not None
    ]
    if not identities or any(identity != ns.task_id for identity in identities):
        return None, "canonical dev report task binding missing or mismatched"
    expected_name = "dev-report-%s.json" % ns.task_id
    effective_name = "dev-report-%s.effective.json" % ns.task_id
    actual_name = os.path.basename(ns.untracked_modified_report)
    # Narrowly-scoped R4 exception (codex round-2 finding #11): the
    # .effective.json basename is accepted ONLY when the caller explicitly
    # passes --effective-report-verified, which only
    # late-repair-controller.py finalize sets, and only after its own
    # independent corroboration has already succeeded. The plain canonical
    # name stays the default/only accepted name otherwise -- this does not
    # loosen the check for any ordinary (non-late-repair) invocation.
    if actual_name == effective_name and getattr(ns, "effective_report_verified", False):
        pass
    elif actual_name != expected_name:
        return None, "canonical dev report filename does not match task"

    dev = document.get("dev")
    if not isinstance(dev, dict):
        return None, "canonical dev report lacks dev object"
    modified = dev.get("files_modified")
    created = dev.get("files_created")
    if (not isinstance(modified, list) or not isinstance(created, list)
            or any(not isinstance(item, str) for item in modified + created)):
        return None, "canonical dev ownership arrays must contain only strings"

    root = os.path.realpath(ns.git_root)
    target = os.path.realpath(os.path.join(root, ns.file))
    modified_claims = [
        claim for claim in modified if _claim_resolves_to(root, claim, target)
    ]
    created_claims = [
        claim for claim in created if _claim_resolves_to(root, claim, target)
    ]
    if len(modified_claims) != 1 or created_claims:
        return None, (
            "path must have exactly one files_modified claim and no files_created claim"
        )
    claim = modified_claims[0]

    contracts = document.get("untracked_modified_provenance")
    if not isinstance(contracts, dict) or set(contracts).intersection(modified_claims) != {claim}:
        return None, "exact untracked-modified path contract missing"
    contract = contracts.get(claim)
    if not isinstance(contract, dict) or contract.get("path") != claim:
        return None, "untracked-modified contract path binding missing or mismatched"
    if contract.get("admission") != "authenticated_preexisting_untracked_whole_file":
        return None, "untracked-modified admission mode missing or mismatched"

    before = contract.get("pre_edit")
    final = contract.get("final")
    if not isinstance(before, dict) or not isinstance(final, dict):
        return None, "untracked-modified pre_edit/final states must be objects"
    if before.get("git_status") != "??" or final.get("git_status") != "??":
        return None, "untracked-modified status binding must be exactly ?? before and after"
    before_sha = before.get("sha256")
    final_sha = final.get("sha256")
    if not _valid_sha256(before_sha) or not _valid_sha256(final_sha):
        return None, "untracked-modified hashes must be lowercase SHA-256"
    if before_sha == final_sha:
        return None, "pre-existing untracked path has no authenticated cycle modification"

    pre_edit = document.get("pre_edit_provenance")
    pre_files = pre_edit.get("files") if isinstance(pre_edit, dict) else None
    pre_statuses = pre_edit.get("statuses") if isinstance(pre_edit, dict) else None
    if (not isinstance(pre_edit, dict)
            or pre_edit.get("verified_before_edit") is not True
            or not isinstance(pre_edit.get("source"), str)
            or not pre_edit["source"].strip()
            or not isinstance(pre_files, dict)
            or pre_files.get(claim) != before_sha
            or not isinstance(pre_statuses, dict)
            or pre_statuses.get(claim) != "??"):
        return None, "pre-edit hash/status contract lacks verified canonical provenance"
    final_hashes = document.get("final_source_hashes")
    if not isinstance(final_hashes, dict) or final_hashes.get(claim) != final_sha:
        return None, "final hash contract disagrees with canonical final_source_hashes"
    if not isinstance(contract.get("evidence_source"), str) or not contract["evidence_source"].strip():
        return None, "untracked-modified evidence_source is required"
    return {
        "claim": claim,
        "pre_edit_sha256": before_sha,
        "final_sha256": final_sha,
    }, ""


def _untracked_modified_main(ns):
    if not ns.task_id:
        return _excluded("--task-id is required with untracked modified provenance")
    if not _valid_sha256(ns.report_sha256):
        return _excluded("--report-sha256 is required and must be lowercase SHA-256")
    try:
        report_bytes = _read_bytes(ns.untracked_modified_report)
    except OSError as exc:
        return _excluded("canonical dev report unreadable: %s" % exc)
    actual_report_sha = hashlib.sha256(report_bytes).hexdigest()
    if actual_report_sha != ns.report_sha256:
        return _excluded(
            "canonical dev report digest mismatch (expected %s, found %s)"
            % (ns.report_sha256, actual_report_sha)
        )
    contract, error = _load_untracked_modified_contract(ns, report_bytes)
    if contract is None:
        return _excluded(error)

    rel = ns.file
    path = os.path.join(ns.git_root, rel)
    if os.path.islink(path) or not os.path.isfile(path):
        return _excluded("untracked-modified target must be a regular non-symlink file")
    if not _exact_untracked_status(ns.git_root, rel):
        return _excluded("current path status is not exactly untracked (??): %s" % rel)
    rc, _, _ = _git(ns.git_root, ["ls-files", "--error-unmatch", "--", rel])
    if rc == 0:
        return _excluded("untracked-modified target unexpectedly exists in the index")
    # This route's candidate image IS the whole current file, which the
    # screening stage in main() has already probed before dispatching here.
    # Re-probing it would duplicate the predicate for no new information.
    current = _read_bytes(path)
    if _is_binary(current):
        # Not the screening stage's concern: a NUL byte makes the file
        # unreviewable as a text patch regardless of any conversion, and this
        # route admits a whole file rather than hunks.
        return _excluded("binary untracked-modified file is not reviewable as a text patch")
    if hashlib.sha256(current).hexdigest() != contract["final_sha256"]:
        return _excluded("current untracked-modified bytes differ from attested final hash")

    directory, env, error = _temporary_index(ns.git_root)
    if directory is None:
        return _excluded("cannot create alternate index: %s" % error)
    try:
        rc, _, error = _git(ns.git_root, ["add", "--", rel], env=env)
        if rc:
            return _excluded("cannot plan exact untracked-modified addition: %s" % error)
        rc, selected, error = _git(
            ns.git_root,
            ["diff", "--cached", "--binary", "--full-index", "--", rel],
            env=env,
        )
        if rc or not selected:
            return _excluded("planned untracked-modified patch unavailable: %s" % error)
        try:
            patch_text = selected.decode("utf-8")
        except UnicodeDecodeError:
            return _excluded("untracked-modified selected patch is not UTF-8 reviewable")
        digest = hashlib.sha256(selected).hexdigest()
        if ns.approved_sha256 and digest != ns.approved_sha256:
            return _excluded(
                "approved patch digest mismatch for %s (expected %s, recomputed %s)"
                % (rel, ns.approved_sha256, digest)
            )
        payload = {
            "path": rel,
            "patch": patch_text,
            "patch_sha256": digest,
            "admission": "authenticated_preexisting_untracked_whole_file",
            "pre_edit_sha256": contract["pre_edit_sha256"],
            "final_sha256": contract["final_sha256"],
            "report_sha256": actual_report_sha,
        }
        if ns.plan_only:
            sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
            return OK

        # SEAM 2 -- the same two mandatory checks on this route's candidate
        # image, which IS the whole current file, strictly before the first
        # real-index write. The planning index above is a private copy in a
        # temporary directory, so nothing in the repository has been mutated
        # at this point.
        refusal = _soundness_gate().screen_landing(
            rel, current, _worktree_mode(path), git_root=ns.git_root,
            claimant_id=ns.task_id)
        if refusal is not None:
            return _excluded(refusal)

        rc, _, error = _git(ns.git_root, ["add", "--", rel])
        if rc:
            return _excluded("cannot stage authenticated untracked-modified file: %s" % error)
        rc, staged, error = _git(
            ns.git_root, ["diff", "--cached", "--binary", "--full-index", "--", rel]
        )
        if rc or staged != selected:
            _git(ns.git_root, ["rm", "--cached", "--force", "--quiet", "--", rel])
            return _excluded("staged untracked-modified patch changed after validation: %s" % error)
        # Stage 3 -- re-probe the blob now in the index, detecting a
        # configuration that changed after the pre-staging probe.
        #
        # MODE IS DELIBERATELY NOT COMPARED HERE, and this is a recorded
        # decision rather than an omission. This route's contract attests only
        # an admission enum, a pre_edit and a final SHA-256, and the '??'
        # status; there is NO attested mode to compare against. A mode does
        # appear in the artefact this route compares, but both sides of that
        # comparison derive from the same worktree file, so it is
        # self-referentially derived and cannot diverge from intent. Inventing
        # an expected mode here would assert an authority no producer granted.
        # Lifting this needs an attested `mode` added alongside pre_edit and
        # final in the contract, which is a producer change this route may not
        # make on its own.
        rc_staged, staged_bytes, err_staged = _git(ns.git_root, ["show", ":%s" % rel])
        if rc_staged:
            _git(ns.git_root, ["rm", "--cached", "--force", "--quiet", "--", rel])
            return _excluded(
                "%s for %s: the staged index blob is unreadable: %s -> EXCLUDE"
                % (SCREEN_INDETERMINATE_PREFIX, rel, err_staged.strip()))
        reason = _screen_checkin_transform(
            ns.git_root, rel, staged_bytes, "index blob after staging")
        if reason is not None:
            _git(ns.git_root, ["rm", "--cached", "--force", "--quiet", "--", rel])
            return _excluded(reason)
        sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
        return OK
    finally:
        shutil.rmtree(directory)


def _is_binary(data):
    # A NUL byte is git's own heuristic for "binary".
    return b"\x00" in data


class EmptyOwnedOldStringError(ValueError):
    """A ledger entry's `old` is empty: unlocatable in principle, not merely absent."""


def _count_occurrences(haystack, needle):
    """Count CANDIDATE START OFFSETS at which needle occurs in haystack (bytes).

    Occurrences are counted INCLUSIVE OF OVERLAPS: the scan advances by one
    position, not by len(needle), so every offset i with
    haystack[i:i+len(needle)] == needle is counted. b"aaa"/b"aa" counts 2,
    b"ababab"/b"abab" counts 2, b"aaaa"/b"aa" counts 3. A needle that cannot
    self-overlap is unaffected (b"aXbXc"/b"X" still counts 2).

    This is what the schema rule REPLAY-UNIQUE means by "occurs EXACTLY ONCE":
    advancing by len(needle) skips an overlapping candidate start, so
    _locate_unique could return a byte offset for an anchor that in fact
    matches at more than one position, and a splice could then be attributed
    to the wrong region.

    Raises EmptyOwnedOldStringError for an empty needle so callers can tell a
    malformed ledger entry apart from real content drift.
    """
    if not needle:
        raise EmptyOwnedOldStringError(
            "empty old_string is structurally unlocatable (a pure insertion has no "
            "anchor); malformed ledger entry, not content drift"
        )
    count = 0
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx == -1:
            break
        count += 1
        start = idx + 1
    return count


def _locate_unique(haystack, needle):
    """Return the unique byte offset of needle in haystack, or None if absent
    or non-unique.

    Propagates EmptyOwnedOldStringError for an empty needle: that is a malformed
    ledger entry, not an absent-or-ambiguous match.
    """
    n = _count_occurrences(haystack, needle)
    if n != 1:
        return None
    return haystack.find(needle)


# ===========================================================================
# Owned-only image construction (docs/dev/specs/spec-20260914-052140.md §5.3)
# ===========================================================================
#
# The judging rule is "do the regions I MYSELF own still contain what I
# recorded", NOT "is the whole file byte-identical to my pre-edit snapshot".
# What is landed is an owned-only IMAGE -- content AND file mode -- assembled
# ONCE on the clean stage-0 index blob (the commit baseline `I`), never on the
# shared working tree and never on the pre-edit snapshot `S`, because `S` may
# already carry another claimant's uncommitted bytes.
#
# Notation used throughout this section:
#   S = the claimant's pre-edit snapshot     R = the forward-replay result
#   I = the clean stage-0 index blob         W = the shared working tree
#
# Two refusal reason codes are emitted by this route, and they stay
# distinguishable (§5.3 (c)):
#   OWNED_FINAL_MISMATCH    -- my recorded region is not where I recorded it
#   BOUNDARY_INDETERMINATE  -- a claimant component has no determinate
#                              correspondence; names SIDE, COMPONENT and CAUSE
# Neither message may use the words "peer" or "conflict": §5.3 (c) forbids a
# boundary-indeterminacy refusal being reported as somebody else's clash.

REASON_OWNED_FINAL_MISMATCH = "OWNED_FINAL_MISMATCH"
REASON_BOUNDARY_INDETERMINATE = "BOUNDARY_INDETERMINATE"

# Side enumeration is THREE-valued. An intra-entry indeterminacy arises from
# the entry's own old->new pair BEFORE either mapping is attempted, so forcing
# it into a mapping side would misreport where it arose.
SIDE_ENTRY = "ENTRY"          # intra-entry: old -> new
SIDE_BASELINE = "BASELINE"    # S -> I, the commit baseline
SIDE_WORKTREE = "WORKTREE"    # R -> W, the shared working tree
REFUSAL_SIDES = (SIDE_ENTRY, SIDE_BASELINE, SIDE_WORKTREE)

REFUSAL_CAUSES = (
    "crossing",
    "absent",
    "envelope-overlap",
    "multiple",
    "image-indeterminate",
    "ambiguous-attribution",
)

# ---------------------------------------------------------------------------
# REFUSAL PRECEDENCE -- a contract decision taken under the exhausted-iteration
# rule (BA/QA analysis reached its 3-of-3 iteration limit with this unstated;
# see docs/dev/context-dev-20260927-135305-r01.json ba_qa_unresolved_objections).
#
# More than one refusal clause can fire on a single input, and §5.3 (c)
# requires a refusal to give "the specific reason why the boundary could not be
# determined" -- so exactly one cause must be determined, and it must be the
# most specific one, not whichever clause happens to be evaluated first.
#
# SIDE precedence: ENTRY > BASELINE > WORKTREE.
#   The intra-entry decomposition is fixed before either side is mapped, and
#   the baseline mapping is a precondition of the worktree comparison. A cause
#   raised at an earlier stage is the origin; a cause raised later is its
#   consequence.
#
# CAUSE precedence within a side, most specific first:
#   crossing > absent > envelope-overlap > multiple > image-indeterminate
#            > ambiguous-attribution
#   A cause that localises the indeterminacy to a NAMED claimant component or
#   boundary outranks one that can only report that the whole assembled image
#   diverged. `image-indeterminate` is therefore ranked below `multiple`:
#   whenever a component's own mapped interval is not unique, the image
#   divergence is a downstream symptom of that, and naming the symptom would
#   violate §5.3 (c)'s "specific reason" requirement. `image-indeterminate`
#   remains reachable and load-bearing on its own -- it is the ONLY cause that
#   can fire when every component projection IS determinate, which is exactly
#   the fixed-alignment, ambiguous-decomposition case (S=b"aa", I=b"aba",
#   entry b"aa"->b"a" yields image b"ba" or b"ab").
#   `ambiguous-attribution` ranks last because it is the only cause about a
#   FOREIGN byte rather than the claimant's own structure, and it is reachable
#   only once that structure is determinate.
# ---------------------------------------------------------------------------
SIDE_PRECEDENCE = {side: n for n, side in enumerate(REFUSAL_SIDES)}
CAUSE_PRECEDENCE = {cause: n for n, cause in enumerate(REFUSAL_CAUSES)}

# Exact byte-level alignment is quadratic. Above this many DP cells the input
# is first anchored on identical LINES and the byte-exact alignment is computed
# only inside the differing blocks. Stated as a method limit, not hidden.
_ALIGN_DP_CELLS = 4000000


class AlignmentBudgetExceeded(Exception):
    """A differing block is too large to align byte-exactly within budget."""


class OwnedLandingRefusal(Exception):
    """A refusal this route itself produces, carrying its own specific reason."""

    def __init__(self, reason, detail, side=None, cause=None, component=None):
        self.reason = reason
        self.detail = detail
        self.side = side
        self.cause = cause
        self.component = component
        Exception.__init__(self, self.message())

    def rank(self):
        return (SIDE_PRECEDENCE.get(self.side, len(REFUSAL_SIDES)),
                CAUSE_PRECEDENCE.get(self.cause, len(REFUSAL_CAUSES)))

    def message(self):
        if self.reason == REASON_BOUNDARY_INDETERMINATE:
            return ("%s: side=%s component=%s cause=%s -- %s"
                    % (self.reason, self.side, self.component, self.cause,
                       self.detail))
        return "%s: %s" % (self.reason, self.detail)


def _boundary_indeterminate(side, cause, component, detail):
    return OwnedLandingRefusal(REASON_BOUNDARY_INDETERMINATE, detail,
                               side=side, cause=cause, component=component)


def _owned_final_mismatch(detail):
    return OwnedLandingRefusal(REASON_OWNED_FINAL_MISMATCH, detail)


# --- Alignment ------------------------------------------------------------
#
# An ALIGNMENT between byte strings P and Q is a set of matched byte pairs
# (i, j) with P[i] == Q[j], strictly increasing in both coordinates (monotone,
# non-crossing). Its COST is len(P) + len(Q) - 2 * |matched|.
#
# The ADMISSIBLE universe is exactly the MINIMUM-COST alignments (equivalently
# maximum total matched bytes). Two rejected universes and why:
#   * all monotone matchings -- one can always match less, so every pair would
#     be "ambiguous" and the rule would refuse everything;
#   * whatever a diff library returns -- that is ONE alignment, signalling no
#     ambiguity, which makes the verdict a function of the library rather than
#     of what the claimant authored. That is the defect class this route
#     exists to eliminate.


def _dp_match_pairs(p, q):
    """Exact maximum-matching alignment of two byte strings, as (i, j) pairs."""
    n, m = len(p), len(q)
    if n == 0 or m == 0:
        return []
    rows = [[0] * (m + 1)]
    prev = rows[0]
    for i in range(n):
        pi = p[i]
        cur = [0] * (m + 1)
        for j in range(m):
            if pi == q[j]:
                cur[j + 1] = prev[j] + 1
            else:
                left = cur[j]
                up = prev[j + 1]
                cur[j + 1] = left if left >= up else up
        rows.append(cur)
        prev = cur
    pairs = []
    i, j = n, m
    while i > 0 and j > 0:
        if p[i - 1] == q[j - 1] and rows[i][j] == rows[i - 1][j - 1] + 1:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif rows[i - 1][j] >= rows[i][j - 1]:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def _line_offsets(data):
    lines = data.splitlines(keepends=True)
    offsets = []
    acc = 0
    for line in lines:
        offsets.append(acc)
        acc += len(line)
    offsets.append(len(data))
    return lines, offsets


def _line_anchored_match_pairs(p, q):
    """Byte-exact alignment inside line-anchored differing blocks.

    Used only above _ALIGN_DP_CELLS. Identical lines are matched as anchors and
    each differing block between anchors is aligned byte-exactly. Stated limit:
    the result is minimum-cost WITHIN each block and anchored on identical
    lines, which is the minimum-cost alignment whenever no cheaper alignment
    crosses a whole identical line -- the ordinary case for source files.
    """
    plines, poff = _line_offsets(p)
    qlines, qoff = _line_offsets(q)
    matcher = difflib.SequenceMatcher(None, plines, qlines, autojunk=False)
    pairs = []
    pi = qi = 0
    for a, b, size in matcher.get_matching_blocks():
        pa, qb = poff[a], qoff[b]
        if pa > pi or qb > qi:
            sub_p, sub_q = p[pi:pa], q[qi:qb]
            if len(sub_p) * len(sub_q) > _ALIGN_DP_CELLS:
                raise AlignmentBudgetExceeded(
                    "differing block of %d x %d bytes exceeds the alignment budget"
                    % (len(sub_p), len(sub_q))
                )
            pairs.extend((i + pi, j + qi)
                         for i, j in _dp_match_pairs(sub_p, sub_q))
        blen = poff[a + size] - pa
        for k in range(blen):
            pairs.append((pa + k, qb + k))
        pi = pa + blen
        qi = qb + (qoff[b + size] - qb)
    return pairs


def _align_pairs(p, q):
    """A minimum-cost monotone non-crossing alignment of p and q."""
    n, m = len(p), len(q)
    lo = 0
    while lo < n and lo < m and p[lo] == q[lo]:
        lo += 1
    hi = 0
    while hi < (n - lo) and hi < (m - lo) and p[n - 1 - hi] == q[m - 1 - hi]:
        hi += 1
    pairs = [(i, i) for i in range(lo)]
    pm, qm = p[lo:n - hi], q[lo:m - hi]
    if pm and qm:
        if len(pm) * len(qm) <= _ALIGN_DP_CELLS:
            mid = _dp_match_pairs(pm, qm)
        else:
            mid = _line_anchored_match_pairs(pm, qm)
        pairs.extend((i + lo, j + lo) for i, j in mid)
    pairs.extend((n - hi + k, m - hi + k) for k in range(hi))
    return pairs


def _change_regions(p, q, pairs):
    """Maximal unmatched runs of an alignment, as (a, b, c, d) with P[a:b)
    unmatched against Q[c:d)."""
    regions = []
    pi = pj = 0
    for i, j in pairs:
        if i > pi or j > pj:
            regions.append((pi, i, pj, j))
        pi, pj = i + 1, j + 1
    if len(p) > pi or len(q) > pj:
        regions.append((pi, len(p), pj, len(q)))
    return regions


def _slide_variants(p, q, region):
    """Every minimum-cost position of one change region, by boundary sliding.

    Shifting a region right by one trades the matched pair on its right for the
    pair (P[a], Q[c]) on its left, so the cost is unchanged; the mirror holds
    for a left shift. This is what makes an inserted line slide over an equal
    flanking newline, and it is why ambiguity is the NORM at byte granularity
    rather than an exotic case: b"ab"->b"aab" and the ordinary one-line
    insertion b"x\\ny\\n"->b"x\\nz\\ny\\n" each admit two positions.

    Stated limit of the enumeration: it yields the slide-variants of one
    minimum-cost alignment. Structurally distinct minimum-cost alignments that
    are not slide-variants of each other are not enumerated; interaction
    between regions is bounded instead where it can actually change the bytes
    to land -- the ENTRY-side image-determinacy check and the disjointness of
    the mapped baseline slices in _assemble_image, both stated over the bound
    image rather than over the envelopes.
    """
    variants = [region]
    x = region
    while True:
        a, b, c, d = x
        if a > 0 and c > 0 and p[b - 1] == q[d - 1]:
            x = (a - 1, b - 1, c - 1, d - 1)
            variants.append(x)
        else:
            break
    x = region
    while True:
        a, b, c, d = x
        if b < len(p) and d < len(q) and p[a] == q[c]:
            x = (a + 1, b + 1, c + 1, d + 1)
            variants.append(x)
        else:
            break
    variants.sort()
    return variants


def _optimal_structure(p, q):
    """The EXACT structure of every minimum-cost alignment of p and q.

    Returns (p_changed, q_changed, images):
      p_changed  p indices unmatched in SOME minimum-cost alignment
      q_changed  q indices unmatched in SOME minimum-cost alignment
      images     p index -> frozenset of q indices it may be matched to

    Enumerating the alignments themselves is exponential; these three
    quantities are not. Two LCS tables -- prefix and suffix -- decide, for
    every state, whether an optimal path passes through it:
      p[i] may be unmatched  iff  pre[i][j] + suf[i+1][j]   == L for some j
      q[j] may be unmatched  iff  pre[i][j] + suf[i][j+1]   == L for some i
      (i,j) may be matched   iff  pre[i][j] + 1 + suf[i+1][j+1] == L

    Why this replaces boundary sliding: sliding enumerates only the variants
    reachable by moving ONE change region's boundaries, and measurement over
    every (p,q) pair on a two-symbol alphabet up to length 4 showed it misses
    admissible alignments in 562 of 870 cases -- including splitting one
    region around an equal matched byte, and structurally distinct alignments
    such as b"ab" -> b"ba". Under-estimating the admissible set is the
    FAIL-OPEN direction: it would let a claimant stage bytes whose ownership
    is in fact undecidable.

    The common prefix and suffix are stripped first and the exact tables are
    built on the reduced window only. Positions outside it are matched
    identically; a change region can still SLIDE into them through equal
    bytes, so the window is widened over the adjacent equal-byte runs before
    the tables are built, which keeps that case inside the exact analysis.
    """
    n, m = len(p), len(q)
    if p == q:
        # Identical strings: every position is matched to itself in the one
        # minimum-cost alignment. Short-circuited so an unchanged multi-kilobyte
        # file never builds a table.
        return frozenset(), frozenset(), {i: frozenset((i,)) for i in range(n)}, True

    exact = True
    if n * m <= _ALIGN_DP_CELLS:
        lo = hi = 0                      # the FULL window: no reduction at all
    else:
        # Too large for an exact table. Reduce to the differing window, then
        # widen: by an upper bound on the alignment cost (a matched pair (i,j)
        # of a minimum-cost alignment satisfies |i-j| <= D), and across the
        # adjacent equal-byte runs (a change can slide through them freely).
        # STATED LIMIT: this reduction is exact for every case measured except
        # a PERIODIC neighbourhood of period > 1 -- b"abab" -> b"ababab" is the
        # smallest -- where it can still under-claim. It is used only on the
        # baseline and working-tree sides, never on the intra-entry side that
        # decides image determinacy, and it is reported as inexact.
        lo = 0
        while lo < n and lo < m and p[lo] == q[lo]:
            lo += 1
        hi = 0
        while hi < (n - lo) and hi < (m - lo) and p[n - 1 - hi] == q[m - 1 - hi]:
            hi += 1
        pad = 2 * ((n - lo - hi) + (m - lo - hi)) + 2
        lo = max(0, lo - pad)
        hi = max(0, hi - pad)
        lo = min(_run_start(p, min(lo, n)), _run_start(q, min(lo, m)))
        p_end = _run_end(p, max(n - hi, lo))
        q_end = _run_end(q, max(m - hi, lo))
        hi = max(0, min(n - p_end, m - q_end))
        exact = False
    pm, qm = p[lo:n - hi], q[lo:m - hi]
    if not pm and not qm:
        return (frozenset(), frozenset(),
                {i: frozenset((i,)) for i in range(n)}, exact)
    if len(pm) * len(qm) > _ALIGN_DP_CELLS:
        # Still too large: anchor on identical LINES and build the exact
        # tables inside each differing block only. The positions bordering a
        # differing block are marked changed, so the approximation over-claims
        # rather than under-claims -- a wider envelope refuses more, which is
        # the safe direction; a narrower one would stage unattributed bytes.
        return _blockwise_structure(p, q, lo, hi)

    local_p, local_q, local_images = _exact_masks(pm, qm)
    # Positions outside the window are provably matched to themselves (prefix)
    # or at the constant end-shift (suffix); recording them here spares every
    # caller a special case.
    images = {i: frozenset((i,)) for i in range(lo)}
    for i in range(n - hi, n):
        images[i] = frozenset((i + (m - n),))
    for i, targets in local_images.items():
        images[i + lo] = frozenset(j + lo for j in targets)
    return (frozenset(i + lo for i in local_p),
            frozenset(j + lo for j in local_q), images, exact)


def _exact_masks(pm, qm):
    """The all-minimum-cost masks for two byte strings, with local indices.

    A state (i, j) lies on an optimal path iff pre[i][j] + suf[i][j] is the
    LCS length, so:
      pm[i] may be unmatched  iff  pre[i][j] + suf[i+1][j]       == L for some j
      qm[j] may be unmatched  iff  pre[i][j] + suf[i][j+1]       == L for some i
      (i, j) may be matched   iff  pre[i][j] + 1 + suf[i+1][j+1] == L
    """
    a, b = len(pm), len(qm)
    if a == 0 or b == 0:
        return (frozenset(range(a)), frozenset(range(b)), {})
    pre = [[0] * (b + 1) for _ in range(a + 1)]
    for i in range(a):
        row, prev = pre[i + 1], pre[i]
        pi = pm[i]
        for j in range(b):
            if pi == qm[j]:
                row[j + 1] = prev[j] + 1
            else:
                left, up = row[j], prev[j + 1]
                row[j + 1] = left if left >= up else up
    suf = [[0] * (b + 1) for _ in range(a + 1)]
    for i in range(a - 1, -1, -1):
        row, nxt = suf[i], suf[i + 1]
        pi = pm[i]
        for j in range(b - 1, -1, -1):
            if pi == qm[j]:
                row[j] = nxt[j + 1] + 1
            else:
                down, right = nxt[j], row[j + 1]
                row[j] = down if down >= right else right
    total = pre[a][b]
    p_changed = set()
    q_changed = set()
    images = {}
    for i in range(a):
        if any(pre[i][j] + suf[i + 1][j] == total for j in range(b + 1)):
            p_changed.add(i)
        targets = frozenset(
            j for j in range(b)
            if pm[i] == qm[j] and pre[i][j] + 1 + suf[i + 1][j + 1] == total)
        if targets:
            images[i] = targets
    for j in range(b):
        if any(pre[i][j] + suf[i][j + 1] == total for i in range(a + 1)):
            q_changed.add(j)
    return frozenset(p_changed), frozenset(q_changed), images


def _blockwise_structure(p, q, lo, hi):
    """Exact masks inside each line-anchored differing block; fail-closed at the
    block borders. Used only when an exact whole-window table is unaffordable."""
    n, m = len(p), len(q)
    pm, qm = p[lo:n - hi], q[lo:m - hi]
    p_lines, p_offsets = _line_offsets(pm)
    q_lines, q_offsets = _line_offsets(qm)
    matcher = difflib.SequenceMatcher(None, p_lines, q_lines, autojunk=False)
    p_changed = set()
    q_changed = set()
    images = {i: frozenset((i,)) for i in range(lo)}
    for i in range(n - hi, n):
        images[i] = frozenset((i + (m - n),))
    p_cursor = q_cursor = 0
    for a_line, b_line, size in matcher.get_matching_blocks():
        p_at, q_at = p_offsets[a_line], q_offsets[b_line]
        if p_at > p_cursor or q_at > q_cursor:
            sub_p, sub_q = pm[p_cursor:p_at], qm[q_cursor:q_at]
            if len(sub_p) * len(sub_q) > _ALIGN_DP_CELLS:
                raise AlignmentBudgetExceeded(
                    "a differing block of %d x %d bytes exceeds the budget"
                    % (len(sub_p), len(sub_q)))
            local_p, local_q, local_images = _exact_masks(sub_p, sub_q)
            p_changed.update(i + p_cursor + lo for i in local_p)
            q_changed.update(j + q_cursor + lo for j in local_q)
            for i, targets in local_images.items():
                images[i + p_cursor + lo] = frozenset(
                    j + q_cursor + lo for j in targets)
            # Fail-closed borders: the matched bytes immediately flanking a
            # differing block may themselves move in another optimal alignment.
            for border in (p_cursor + lo - 1, p_at + lo):
                if lo <= border < n - hi:
                    p_changed.add(border)
                    images.pop(border, None)
            for border in (q_cursor + lo - 1, q_at + lo):
                if lo <= border < m - hi:
                    q_changed.add(border)
        block_bytes = p_offsets[a_line + size] - p_at
        for k in range(block_bytes):
            images.setdefault(p_at + k + lo, frozenset((q_at + k + lo,)))
        p_cursor = p_at + block_bytes
        q_cursor = q_at + (q_offsets[b_line + size] - q_at)
    return frozenset(p_changed), frozenset(q_changed), images, False


def _run_start(buf, index):
    """Walk back over the equal-byte run the window's left edge sits in."""
    if not buf:
        return 0
    reference = buf[index] if index < len(buf) else buf[index - 1]
    while index > 0 and buf[index - 1] == reference:
        index -= 1
    return index


def _run_end(buf, index):
    """Walk forward over the equal-byte run the window's right edge sits in."""
    if not buf:
        return 0
    reference = buf[index - 1] if index > 0 else buf[index]
    while index < len(buf) and buf[index] == reference:
        index += 1
    return index


def _maybe_changed_span(changed, start, end, length):
    """The maximal maybe-changed run enclosing [start, end) -- the component's
    AMBIGUITY ENVELOPE. A singleton envelope means the boundary is determinate."""
    lower, upper = start, end
    while lower > 0 and (lower - 1) in changed:
        lower -= 1
    while upper < length and upper in changed:
        upper += 1
    return lower, upper


def _canonical_regions(p, q, regions):
    """Canonicalise every region to its left-most admissible position and
    return [(canonical, [admissible variants])]. Sliding is bounded by the
    neighbouring regions so canonical slices stay ordered and disjoint."""
    total = len(regions)
    result = []
    lo_p = lo_q = 0
    for k, region in enumerate(regions):
        hi_p = regions[k + 1][0] if k + 1 < total else len(p)
        hi_q = regions[k + 1][2] if k + 1 < total else len(q)
        variants = [v for v in _slide_variants(p, q, region)
                    if v[0] >= lo_p and v[2] >= lo_q
                    and v[1] <= hi_p and v[3] <= hi_q]
        if not variants:
            variants = [region]
        canonical = variants[0]
        result.append((canonical, variants))
        lo_p, lo_q = canonical[1], canonical[3]
    return result


def _decompose_entry(old_b, new_b):
    """The determinately CHANGED sub-components of one ledger entry.

    NOT the entry's whole target range -- unchanged matched context inside an
    entry is anchor context, not ownership, and claiming it refuses a
    legitimate interleave. NOT the net endpoint delta either -- that accepts a
    ledger whose recorded final content exists in no working tree.
    """
    pairs = _align_pairs(old_b, new_b)
    regions = _change_regions(old_b, new_b, pairs)
    return _canonical_regions(old_b, new_b, regions)


# --- Forward replay with a per-byte provenance carry ----------------------

_FROM_SNAPSHOT = "S"
_AUTHORED = "A"

_MAX_VARIANT_IMAGES = 128


def _as_bytes(value):
    return value.encode("utf-8") if isinstance(value, str) else value


def _carving_reach(prov, off, old_b, variants):
    """The snapshot offsets every admissible carving of one component can rest
    on, recorded while the pre-entry provenance is still readable.

    A carving placed at old[a:b) displaces the baseline images of a..b-1 and
    rests on the images of its flanks a-1 and b, so over every admissible
    placement the positions involved are exactly old[min(a)-1 .. max(b)]. That
    closure is derived from the admissible set itself, NOT sized by a constant:
    a pure deletion has a zero-width produced span and therefore zero slide,
    yet its carvings still range over the whole equal-byte run it deletes from.

    `None` marks a position this record cannot resolve to a snapshot byte (a
    byte an earlier entry authored, or one outside this entry's window). It is
    reported rather than dropped so the neutrality test can refuse to prune,
    which costs an enumeration and never a missed refusal.
    """
    if len(variants) < 2:
        return ()          # no choice to make: nothing can depend on it
    lo = min(v[0] for v in variants) - 1
    hi = max(v[1] for v in variants) + 1
    return tuple(
        prov[off + t][1]
        if 0 <= t < len(old_b) and prov[off + t][0] == _FROM_SNAPSHOT else None
        for t in range(lo, hi))


def _carving_is_baseline_neutral(reach, s_changed, i_changed, sigma):
    """True when the commit baseline carries no difference anywhere this
    component's carvings can reach, so every one of them displaces the SAME
    baseline bytes and no choice among them can change the image.

    Sliding a carving within a run of equal bytes is harmless only while the
    baseline reproduces that run; this decides exactly that, over the reach
    above, and every unresolved position answers False.
    """
    if any(p is None or p in s_changed for p in reach):
        return False
    targets = [sigma.get(p) for p in reach]
    if any(t is None for t in targets):
        return False
    if any(reach[k] != reach[0] + k or targets[k] != targets[0] + k
           for k in range(len(reach))):
        return False
    return not any(p in i_changed for p in range(targets[0], targets[-1] + 1))


def _carving_assignments(unresolved):
    """Every admissible carving assignment over the components whose choice the
    baseline does not render neutral, as `overrides` maps. Canonical-first; the
    all-canonical assignment is the one already built and is not re-emitted."""
    keys = [meta["key"] for meta in unresolved]
    pools = [meta["variants"] for meta in unresolved]
    chosen = [0] * len(pools)
    while True:
        position = len(pools) - 1
        while position >= 0:
            chosen[position] += 1
            if chosen[position] < len(pools[position]):
                break
            chosen[position] = 0
            position -= 1
        if position < 0:
            return
        yield {key: pools[k][chosen[k]] for k, key in enumerate(keys)}


def _replay_with_provenance(snapshot, edits, rel, overrides=None):
    """Replay the ledger forward from `S`, carrying byte provenance.

    The replay is the ownership WITNESS -- it establishes what this claimant
    authored. It is NOT the artifact to land: `S` may already hold another
    claimant's uncommitted bytes, so landing the replay buffer would stage them
    and a readback against it would certify that rather than catch it.

    Marks are carried THROUGH a later entry's matched components, not replaced
    wholesale over the overlapped region -- replacing under-claims (measured:
    footprint [0,1) instead of [0,2) on a chained partially-cancelling ledger).
    """
    buf = bytearray(snapshot)
    prov = [(_FROM_SNAPSHOT, i) for i in range(len(snapshot))]
    components = {}
    for idx, edit in enumerate(edits):
        if not isinstance(edit, dict) or "old" not in edit or "new" not in edit:
            raise _owned_final_mismatch(
                "ledger entry %d malformed (need old+new) for %s" % (idx, rel))
        old_b = _as_bytes(edit["old"])
        new_b = _as_bytes(edit["new"])
        try:
            off = _locate_unique(bytes(buf), old_b)
        except EmptyOwnedOldStringError as exc:
            raise EmptyOwnedOldStringError("entry %d: %s" % (idx, exc))
        if off is None:
            raise _boundary_indeterminate(
                SIDE_ENTRY, "absent", "entry %d anchor" % idx,
                "owned old_string for edit %d not uniquely locatable during "
                "replay (absent or duplicated at this step -- occurrences are "
                "counted as candidate start offsets, inclusive of overlaps) -> "
                "ambiguous: %s" % (idx, rel))
        # The EXACT set of positions this entry may have changed, over every
        # minimum-cost decomposition of its own old -> new pair. This is what
        # the ambiguity envelope is built from; a budget failure here is
        # treated as ambiguous, never as unambiguous.
        try:
            (entry_source_changed, entry_target_changed,
             _entry_images, entry_exact) = _optimal_structure(old_b, new_b)
        except AlignmentBudgetExceeded:
            entry_source_changed = entry_target_changed = None
            entry_exact = False
        segment = bytearray()
        segment_prov = []
        cursor_p = cursor_q = 0
        for rindex, (canonical, variants) in enumerate(_decompose_entry(old_b, new_b)):
            key = (idx, rindex)
            a, b, c, d = overrides[key] if (overrides and key in overrides) else canonical
            if (a - cursor_p) != (c - cursor_q):
                raise _boundary_indeterminate(
                    SIDE_ENTRY, "crossing", "entry %d component %d" % (idx, rindex),
                    "the unchanged context around a recorded component does not "
                    "correspond one-to-one between the recorded old and new "
                    "text: %s" % rel)
            for k in range(a - cursor_p):
                at = off + cursor_p + k
                segment += buf[at:at + 1]
                segment_prov.append(prov[at])
            segment += new_b[c:d]
            segment_prov.extend([(_AUTHORED, key)] * (d - c))
            if entry_target_changed is None:
                env_c, env_d, ambiguous = c, d, True
            else:
                env_c, env_d = _maybe_changed_span(
                    entry_target_changed, c, d, len(new_b))
                src_lo, src_hi = _maybe_changed_span(
                    entry_source_changed, a, b, len(old_b))
                ambiguous = (not entry_exact
                             or (env_c, env_d) != (c, d)
                             or (src_lo, src_hi) != (a, b))
            components[key] = {
                "key": key,
                "entry": idx,
                "region": rindex,
                "consumed": old_b[a:b],
                "produced": new_b[c:d],
                "left_slide": c - env_c,
                "right_slide": env_d - d,
                "ambiguous": ambiguous,
                "variants": variants,
                "canonical": canonical,
                "reach": _carving_reach(prov, off, old_b, variants),
            }
            cursor_p, cursor_q = b, d
        for k in range(len(old_b) - cursor_p):
            at = off + cursor_p + k
            segment += buf[at:at + 1]
            segment_prov.append(prov[at])
        buf[off:off + len(old_b)] = segment
        prov[off:off + len(old_b)] = segment_prov
    return bytes(buf), prov, components


def _authored_runs(prov):
    """Maximal contiguous runs of one component's authored bytes, in R."""
    runs = []
    start = None
    key = None
    for i, mark in enumerate(prov):
        if mark[0] == _AUTHORED:
            if key != mark[1]:
                if start is not None:
                    runs.append((start, i, key))
                start, key = i, mark[1]
        elif start is not None:
            runs.append((start, i, key))
            start, key = None, None
    if start is not None:
        runs.append((start, len(prov), key))
    return runs


def _net_edits_in_snapshot_coords(replay, prov, snapshot_len, rel):
    """The claimant's net authored edits as ordered, pairwise-disjoint
    (s_start, s_end, produced_bytes, component_keys) tuples in `S` coordinates."""
    out = []
    expected = 0
    pending = bytearray()
    pending_keys = []
    last_s = -1
    for i, mark in enumerate(prov):
        if mark[0] == _FROM_SNAPSHOT:
            s = mark[1]
            if s <= last_s:
                raise _boundary_indeterminate(
                    SIDE_BASELINE, "crossing", "snapshot offset %d" % s,
                    "the surviving snapshot bytes are no longer in ascending "
                    "order after replay, so no monotone correspondence exists "
                    "for %s" % rel)
            if s != expected or pending:
                out.append((expected, s, bytes(pending), tuple(pending_keys)))
            pending = bytearray()
            pending_keys = []
            last_s = s
            expected = s + 1
        else:
            pending += replay[i:i + 1]
            if not pending_keys or pending_keys[-1] != mark[1]:
                pending_keys.append(mark[1])
    if pending or expected < snapshot_len:
        out.append((expected, snapshot_len, bytes(pending), tuple(pending_keys)))
    return out


def _map_edit_onto_baseline(sigma, edit, snapshot_len, index_len, rel,
                            consulted=None):
    """Map one net edit from `S` coordinates onto `I`. Returns (u, v).

    Every alignment position read to place the edit is appended to `consulted`,
    so the uniqueness guard can demand determinacy of EXACTLY the positions the
    placement rested on instead of re-deriving them from its own copy of the
    case analysis -- which is how boundary insertions escaped it entirely.
    """
    s0, s1, _produced, _keys = edit

    def image(position):
        if consulted is not None:
            consulted.append(position)
        return sigma.get(position)

    if s0 != s1:
        base = image(s0)
        if base is None:
            raise _boundary_indeterminate(
                SIDE_BASELINE, "crossing", "snapshot range [%d,%d)" % (s0, s1),
                "a difference between the recorded snapshot and the commit "
                "baseline falls inside this recorded component, so its bytes "
                "have no order-preserving image on the baseline: %s" % rel)
        for k in range(1, s1 - s0):
            if image(s0 + k) != base + k:
                raise _boundary_indeterminate(
                    SIDE_BASELINE, "crossing",
                    "snapshot range [%d,%d)" % (s0, s1),
                    "this recorded component's bytes do not map to a contiguous "
                    "run of the commit baseline: %s" % rel)
        return base, base + (s1 - s0)
    # Pure insertion: the boundary is derived from its aligned flanks.
    if s0 == 0:
        if snapshot_len == 0:
            # An empty snapshot offers no byte to anchor on, so the placement
            # rests on no alignment position and none is recorded.
            return 0, 0
        first = image(0)
        if first is None:
            raise _boundary_indeterminate(
                SIDE_BASELINE, "absent", "snapshot boundary 0",
                "the flank anchoring this recorded insertion has no image on "
                "the commit baseline: %s" % rel)
        if first != 0:
            raise _boundary_indeterminate(
                SIDE_BASELINE, "multiple", "snapshot boundary 0",
                "the commit baseline carries unattributed leading bytes, so "
                "this recorded insertion admits more than one start-of-file "
                "boundary: %s" % rel)
        return 0, 0
    if s0 == snapshot_len:
        last = image(snapshot_len - 1)
        if last is None:
            raise _boundary_indeterminate(
                SIDE_BASELINE, "absent", "snapshot boundary %d" % s0,
                "the flank anchoring this recorded insertion has no image on "
                "the commit baseline: %s" % rel)
        if last != index_len - 1:
            raise _boundary_indeterminate(
                SIDE_BASELINE, "multiple", "snapshot boundary %d" % s0,
                "the commit baseline carries unattributed trailing bytes, so "
                "this recorded insertion admits more than one end-of-file "
                "boundary: %s" % rel)
        return index_len, index_len
    left = image(s0 - 1)
    right = image(s0)
    if left is None or right is None:
        raise _boundary_indeterminate(
            SIDE_BASELINE, "absent", "snapshot boundary %d" % s0,
            "a flank anchoring this recorded insertion has no image on the "
            "commit baseline: %s" % rel)
    if right != left + 1:
        raise _boundary_indeterminate(
            SIDE_BASELINE, "multiple", "snapshot boundary %d" % s0,
            "the commit baseline carries unattributed bytes between the flanks "
            "anchoring this recorded insertion, so its boundary admits more "
            "than one position: %s" % rel)
    return right, right


def _assemble_image(index_blob, mapped, rel):
    """Assemble the owned-only image ONCE, from the immutable baseline.

    Applying a baseline coordinate to an already-mutated buffer is forbidden:
    it silently corrupts the image while every individual span stays
    well-formed, and the post-landing readback then certifies the corruption
    because it compares against that same image.
    """
    pieces = []
    cursor = 0
    for u, v, produced in mapped:
        if u < cursor:
            raise _boundary_indeterminate(
                SIDE_BASELINE, "envelope-overlap", "baseline range [%d,%d)" % (u, v),
                "two recorded components map to overlapping baseline slices, so "
                "their order on the baseline is not determined: %s" % rel)
        pieces.append(index_blob[cursor:u])
        pieces.append(produced)
        cursor = v
    pieces.append(index_blob[cursor:])
    return b"".join(pieces)


def _image_for_overrides(snapshot, index_blob, edits, rel, sigma, overrides):
    replay, prov, _components = _replay_with_provenance(
        snapshot, edits, rel, overrides=overrides)
    net = _net_edits_in_snapshot_coords(replay, prov, len(snapshot), rel)
    mapped = []
    for entry in net:
        u, v = _map_edit_onto_baseline(
            sigma, entry, len(snapshot), len(index_blob), rel)
        mapped.append((u, v, entry[2]))
    return _assemble_image(index_blob, mapped, rel)


def _verify_against_worktree(replay, worktree, runs, deletions, components, rel):
    """Owned-region-local verdict over the AUTHORED transformation.

    Differences wholly outside the claimant's footprint are IGNORED -- that is
    the entire point: a foreign byte anywhere in the file, including a
    machine-written timestamp, must not withhold the claimant's contribution.

    Obligations are PAIRED. A produced-target check alone is not enough:
    measured, S=b"aXb" with entry b"X"->b"Y" against W=b"aXYb" satisfies
    produced-target although the source was never consumed.
    """
    r_changed, _w_changed, r_images, _exact = _optimal_structure(replay, worktree)

    def image_of(index):
        targets = r_images.get(index)
        return targets if targets else None

    # Every boundary of the replayed content at which the working tree carries
    # bytes this claimant's record does not account for.
    foreign_boundaries = set()
    for boundary in range(len(replay) + 1):
        left = image_of(boundary - 1) if boundary > 0 else frozenset((-1,))
        right = (image_of(boundary) if boundary < len(replay)
                 else frozenset((len(worktree),)))
        if not left or not right:
            continue
        if max(right) - min(left) > 1:
            foreign_boundaries.add(boundary)

    def foreign_bytes_at(boundary):
        left = image_of(boundary - 1) if boundary > 0 else frozenset((-1,))
        right = (image_of(boundary) if boundary < len(replay)
                 else frozenset((len(worktree),)))
        if not left or not right:
            return b""
        return worktree[min(left) + 1:max(right)]

    def _mapped_span(r0, r1, label):
        previous = None
        for i in range(r0, r1):
            targets = image_of(i)
            if i in r_changed or targets is None or len(targets) != 1:
                raise _owned_final_mismatch(
                    "the recorded region %s of %s no longer holds what was "
                    "recorded: its replayed bytes have no single, matched "
                    "counterpart in the working tree" % (label, rel))
            j = next(iter(targets))
            if previous is not None and j != previous + 1:
                raise _owned_final_mismatch(
                    "the recorded region %s of %s no longer holds what was "
                    "recorded: its replayed bytes have no contiguous "
                    "counterpart in the working tree" % (label, rel))
            previous = j
        if r1 > r0:
            return next(iter(image_of(r0))), previous + 1
        if r0 in foreign_boundaries:
            raise _owned_final_mismatch(
                "the recorded deletion %s of %s cannot be witnessed: the "
                "working tree carries unaccounted bytes at its mapped "
                "boundary" % (label, rel))
        left = image_of(r0 - 1) if r0 > 0 else None
        right = image_of(r0) if r0 < len(replay) else None
        if r0 == 0:
            base = 0 if not right else min(right)
        elif r0 == len(replay):
            base = len(worktree) if not left else max(left) + 1
        else:
            if not left or not right:
                raise _owned_final_mismatch(
                    "the recorded deletion %s of %s cannot be witnessed: its "
                    "mapped boundary in the working tree is interrupted"
                    % (label, rel))
            base = min(right)
        return base, base

    checks = []
    for r0, r1, key in runs:
        meta = components[key]
        checks.append((r0, r1, meta, "entry %d component %d"
                       % (meta["entry"], meta["region"])))
    for r0, consumed, label in deletions:
        checks.append((r0, r0, {"consumed": consumed, "produced": b"",
                                "left_slide": 0, "right_slide": 0}, label))

    for r0, r1, meta, label in checks:
        _start, _end = _mapped_span(r0, r1, label)
        # Paired obligation, consumed-source half. A produced-target check
        # alone accepts a working tree that carries the recorded source
        # ALONGSIDE the recorded replacement, where the recorded
        # transformation demonstrably never happened (measured: S=b"aXb",
        # entry b"X"->b"Y", W=b"aXYb"). The signature is unaccounted bytes
        # ABUTTING the component that re-materialise the consumed source;
        # keying on the abutting difference rather than on raw byte adjacency
        # is what keeps this from firing on an ordinary short component whose
        # neighbour happens to repeat one of its bytes.
        consumed = meta["consumed"]
        if consumed:
            for boundary in (r0, r1):
                if boundary in foreign_boundaries \
                        and consumed in foreign_bytes_at(boundary):
                    raise _owned_final_mismatch(
                        "the recorded source text of %s in %s was never "
                        "consumed -- it is still present beside the recorded "
                        "replacement, so the recorded transformation did not "
                        "happen here" % (label, rel))
        # Attribution: only the AMBIGUITY MARGIN can make an unaccounted
        # difference unattributable. A margin exists only where the component
        # itself could have been decomposed differently; where it could not,
        # the difference is outside this claimant's footprint and is IGNORED,
        # which is the entire point of the route.
        margins = []
        if meta["left_slide"]:
            margins.append((r0 - meta["left_slide"], r0))
        if meta["right_slide"]:
            margins.append((r1, r1 + meta["right_slide"]))
        for lower, upper in margins:
            if any(lower <= boundary <= upper for boundary in foreign_boundaries) \
                    or any(position in r_changed
                           for position in range(max(lower, 0), upper)):
                raise _boundary_indeterminate(
                    SIDE_ENTRY, "ambiguous-attribution", label,
                    "a difference in the working tree falls inside this "
                    "component's ambiguity envelope but outside the component "
                    "itself, so it cannot be determined whether those bytes "
                    "are the ones recorded here: %s" % rel)


def _owned_only_image(snapshot, index_blob, worktree, edits, rel,
                      replayed=None, mapped_out=None):
    """Build and validate the owned-only image. Raises OwnedLandingRefusal.

    `replayed` lets the caller reuse a replay it already performed -- ledger
    validity is a property of the ledger alone, so the caller diagnoses a
    malformed or unlocatable entry before it reads anything from the index.
    """
    if replayed is None:
        replayed = _replay_with_provenance(snapshot, edits, rel)
    replay, prov, components = replayed
    runs = _authored_runs(prov)
    net = _net_edits_in_snapshot_coords(replay, prov, len(snapshot), rel)

    # There is deliberately NO order test over component ambiguity envelopes.
    # One ledger is ONE claimant and the forward replay already fixes the order
    # of every component in it -- across entries exactly as within one entry --
    # so an envelope overlap says only that this claimant's own authored bytes
    # could have been carved up differently; every byte involved is still this
    # claimant's. The test that stood here read "a different ledger entry" as
    # "a different party" and so refused ordinary authoring: insert a block,
    # then revise a line inside the block you just inserted. Whether an
    # admissible re-carving changes the bytes to LAND is the only question that
    # matters, and it is answered on the bound image below -- by the ENTRY-side
    # image-determinacy check, and by the disjointness of the mapped baseline
    # slices that _assemble_image enforces. A genuine two-party double claim is
    # stated over two TASKS and is decided by the classification route; a
    # refusal here could never have protected that, because it instead withheld
    # a nested ledger from reaching it at all (an unresolved boundary is
    # excluded from pairing).

    # --- Baseline (S -> I) --------------------------------------------------
    baseline_pairs = _align_pairs(snapshot, index_blob)
    sigma = dict(baseline_pairs)
    s_changed, i_changed, s_images, _baseline_exact = _optimal_structure(
        snapshot, index_blob)
    # Placement reads the SAME object whose determinacy the gate below
    # certifies. `_align_pairs` yields ONE witness alignment, and above the DP
    # budget it and `_optimal_structure` line-anchor over DIFFERENT windows, so
    # the witness drifts from the structure inside text byte-identical in both
    # buffers: measured on this file's own ledger over its recorded snapshot,
    # 47 positions the structure determines uniquely are unpaired by the
    # witness and 26 more are paired three bytes off -- and that refused a
    # determinate ledger as "crossing" at snapshot [72969,72997). The 26 are
    # the worse half: had the contiguity run not tripped, the owned slice would
    # have landed three bytes from where the gate then certified it, and the
    # post-apply read-back compares against that same mis-assembled image. So
    # a position the structure calls UNCHANGED with exactly ONE admissible
    # image takes that image. This admits nothing the gate rejects -- those are
    # exactly the two conditions it demands, so a reconciled position passes it
    # by construction -- while a position left changed or multiply-imaged keeps
    # the witness's answer and so keeps refusing.
    for position, targets in s_images.items():
        if len(targets) == 1 and position not in s_changed:
            sigma[position] = next(iter(targets))

    mapped = []
    anchors = []
    for entry in net:
        consulted = []
        u, v = _map_edit_onto_baseline(
            sigma, entry, len(snapshot), len(index_blob), rel, consulted)
        mapped.append((u, v, entry[2]))
        anchors.append(consulted)
    image = _assemble_image(index_blob, mapped, rel)

    # --- ENTRY side: does this ledger determine the image UNIQUELY? Sliding a
    # component inside a run of equal bytes is harmless only while it stays in
    # the buffer it was computed against; transplanted onto a DIFFERENT
    # baseline, where unattributed bytes intervene, sliding changes which
    # baseline bytes are displaced. Minimal counterexample: S=b"aa", I=b"aba",
    # entry b"aa"->b"a" has a UNIQUE S->I alignment and yields b"ba" or b"ab".
    # Every instance needs S != I, which is exactly the divergent-baseline case
    # this route exists to serve -- so it is skipped only when S == I, where it
    # holds by construction rather than by assumption.
    #
    # The question is ASKED, not approximated: the admissible images are
    # assembled and compared. What stood here instead measured how far the
    # baseline had diverged within a window sized from the component's SLIDE,
    # and a window is the wrong object -- a pure deletion produces nothing, so
    # both slides are zero and the window collapsed to one byte while its
    # carvings still ranged over the whole equal-byte run it deletes from.
    # Measured on the pre-change build: S=b"aabbb", I=b"aabbab", entry
    # b"abbb"->b"abb" admits carvings (1,2,1,1), (2,3,2,2) and (3,4,3,3),
    # assembling b"aabab" or b"aabba", and it landed b"aabab" silently.
    # The enumeration is confined to the components whose carving the baseline
    # does not render neutral, which is what keeps it affordable: measured over
    # the 1094 recorded ledgers under docs/dev/, the unconfined product exceeds
    # _MAX_VARIANT_IMAGES on 341 of them and reaches 3.9e11, so enumerating it
    # whole would refuse determinate inputs -- the §5.3 fail-closed behaviour
    # this route exists to remove.
    if s_changed or i_changed:
        unresolved = [meta for meta in components.values()
                      if meta["ambiguous"] and len(meta["variants"]) > 1
                      and not _carving_is_baseline_neutral(
                          meta["reach"], s_changed, i_changed, sigma)]
        if unresolved:
            label = "entry %d component %d" % (unresolved[0]["entry"],
                                               unresolved[0]["region"])
            breadth = 1
            for meta in unresolved:
                breadth *= len(meta["variants"])
                if breadth > _MAX_VARIANT_IMAGES:
                    raise _boundary_indeterminate(
                        SIDE_ENTRY, "image-indeterminate", label,
                        "the recorded text admits more than %d admissible "
                        "images over a diverged commit baseline, too many to "
                        "establish that the ledger determines a single one, so "
                        "the image to land is not determined: %s"
                        % (_MAX_VARIANT_IMAGES, rel))
            for overrides in _carving_assignments(unresolved):
                try:
                    alternative = _image_for_overrides(
                        snapshot, index_blob, edits, rel, sigma, overrides)
                except (OwnedLandingRefusal, AlignmentBudgetExceeded):
                    # A carving the ledger cannot be replayed or mapped under
                    # is not an admissible READING of it, so it contributes no
                    # image. Skipped rather than raised: raising here would
                    # report a carving nobody claimed as this claimant's cause.
                    continue
                if alternative != image:
                    raise _boundary_indeterminate(
                        SIDE_ENTRY, "image-indeterminate", label,
                        "the recorded old and new text admit more than one "
                        "minimum-cost decomposition, and over this commit "
                        "baseline they assemble more than one owned-only "
                        "image, so the image to land is not determined by "
                        "this ledger: %s" % rel)

    # --- BASELINE side: is each component's mapped interval the same under
    # EVERY admissible S -> I alignment? Uniqueness is required of the
    # CLAIMANT'S PROJECTION only, never of the whole-file alignment: demanding
    # the latter would refuse whenever repeated unowned context admits several
    # equivalent alignments, re-creating the fail-closed behaviour this route
    # exists to remove.
    # The positions demanded here are the ones the mapping above RECORDED
    # consulting, never a second case analysis of the same placement: the two
    # drifted once already, exempting boundary insertions from this check.
    for (s0, s1, _produced, _keys), required in zip(net, anchors):
        for position in required:
            label = "snapshot range [%d,%d)" % (s0, s1)
            if position in s_changed:
                raise _boundary_indeterminate(
                    SIDE_BASELINE, "crossing", label,
                    "a difference between the recorded snapshot and the "
                    "commit baseline falls inside this component, so its "
                    "bytes have no order-preserving image there: %s" % rel)
            targets = s_images.get(position)
            if not targets:
                raise _boundary_indeterminate(
                    SIDE_BASELINE, "absent", label,
                    "a position anchoring this component has no image on the "
                    "commit baseline: %s" % rel)
            if len(targets) != 1:
                raise _boundary_indeterminate(
                    SIDE_BASELINE, "multiple", label,
                    "more than one minimum-cost correspondence between the "
                    "recorded snapshot and the commit baseline maps this "
                    "component to a different baseline interval: %s" % rel)

    # --- WORKTREE side ------------------------------------------------------
    deletions = []
    s_to_r = {}
    for i, mark in enumerate(prov):
        if mark[0] == _FROM_SNAPSHOT:
            s_to_r[mark[1]] = i
    for s0, s1, produced, _keys in net:
        if produced or s0 == s1:
            continue
        boundary = s_to_r.get(s1, len(replay))
        deletions.append((boundary, snapshot[s0:s1],
                          "recorded deletion at snapshot [%d,%d)" % (s0, s1)))
    _verify_against_worktree(replay, worktree, runs, deletions, components, rel)
    # The baseline-coordinate slices are handed back through an OPTIONAL sink
    # rather than a fourth return value: the arity is part of this helper's
    # published surface and other callers unpack exactly three. A caller that
    # wants to re-compose a SUBSET of the owned slices passes a sink.
    if mapped_out is not None:
        mapped_out.extend(mapped)
    return image, replay, net


def _index_stage0_oid(git_root, rel):
    """The object id of the path's STAGE-0 INDEX entry (never a commit's tree)."""
    rc, out, _ = _git(git_root, ["ls-files", "-s", "--", rel])
    if rc or not out:
        return None
    try:
        fields = out.split(b"\t", 1)[0].split()
        if fields[2] != b"0":
            return None
        return fields[1].decode("ascii")
    except (IndexError, UnicodeDecodeError):
        return None


def _restore_index_entry(git_root, rel, mode, oid):
    # --add is required: a fault may have removed the entry outright, and
    # without it `update-index --cacheinfo` refuses to re-create one.
    _git(git_root, ["update-index", "--add", "--cacheinfo",
                    "%s,%s,%s" % (mode, oid, rel)])


def _refusal_text(git_root, rel, snapshot, refusal):
    """A refusal message, plus the I12 stale-capture signature when present.

    Reached ONLY on the refusal path. The accepted landing path must issue no
    commit-scoped read of the path at all, which is what makes the mode's
    stage-0 provenance observable rather than merely asserted -- so this
    HEAD lookup must never migrate onto the accepting side.
    """
    text = refusal.message()
    head_entry = _tree_entry(git_root, "HEAD", rel)
    if head_entry is not None:
        rc_head, head_blob, _ = _git(git_root, ["cat-file", "blob", head_entry[2]])
        if rc_head == 0 and head_blob == snapshot:
            text += (
                " | I12-snapshot-mismatch: the pre_edit_snapshot for %s is "
                "byte-identical to the current HEAD blob rather than the "
                "file's true dispatch-time working-tree bytes. If the file "
                "was already dirty when this cycle's capture ran, the "
                "recorded snapshot never reflected the pre-existing "
                "uncommitted content. Re-capture pre_edit_snapshots from "
                "actual dispatch-time working-tree bytes (e.g. `git "
                "hash-object <path>` against the live file at cycle start), "
                "not HEAD:%s." % (rel, rel))
    return text


def _land_owned_image(git_root, rel, image, mode, prior_oid):
    """FREEZE, then land: write the image as an immutable object and only then
    point the index entry at it. A check-then-land against a mutable path is a
    time-of-check/time-of-use gap that no lock around repository operations
    closes, so the reviewed content is frozen first and that object is landed.

    The working tree is never written, so another claimant's pending bytes
    survive untouched.
    """
    rc_write, out_write, err_write = _git(
        git_root, ["hash-object", "-t", "blob", "-w", "--stdin"], input_bytes=image)
    if rc_write != 0:
        # No index mutation has been attempted at this point.
        return _excluded(
            "could not freeze the owned-only image as a git object for %s "
            "(index untouched): %s" % (rel, err_write.strip()))
    oid = out_write.strip().decode("ascii", "replace")
    rc_read, frozen, err_read = _git(git_root, ["cat-file", "blob", oid])
    if rc_read != 0 or frozen != image:
        return _excluded(
            "the frozen owned-only image for %s does not read back as written; "
            "no index mutation attempted: %s"
            % (rel, err_read.strip() if rc_read != 0 else "byte mismatch"))
    rc_update, _, err_update = _git(
        git_root, ["update-index", "--cacheinfo", "%s,%s,%s" % (mode, oid, rel)])
    if rc_update != 0:
        _restore_index_entry(git_root, rel, mode, prior_oid)
        return _excluded(
            "could not set the index entry for %s to the frozen owned-only "
            "image; restored the prior index entry: %s" % (rel, err_update.strip()))
    # Readback: the STAGED entry against the FROZEN IMAGE -- never against any
    # whole-working-tree buffer. Mode is asserted separately from content,
    # because a git blob object id does not encode file mode.
    staged_mode = _tracked_mode(git_root, rel)
    staged_oid = _index_stage0_oid(git_root, rel)
    rc_show, staged, err_show = _git(git_root, ["show", ":%s" % rel])
    if (staged_oid is None or staged_mode is None or rc_show != 0
            or staged != image or staged_mode != mode or staged_oid != oid):
        _restore_index_entry(git_root, rel, mode, prior_oid)
        if staged_oid is None or staged_mode is None:
            detail = "index entry absent or unreadable after the update"
        elif rc_show != 0:
            detail = err_show.strip() or "staged blob unreadable"
        elif staged_mode != mode:
            detail = ("staged mode %s != image mode %s" % (staged_mode, mode))
        else:
            detail = "staged bytes differ from the frozen image"
        return _excluded(
            "I13-post-apply-mismatch: the staged INDEX entry for %s does not "
            "match the frozen owned-only image; restored the prior index entry "
            "-> EXCLUDE: %s" % (rel, detail))
    # Stage 3 -- re-probe the blob ACTUALLY PRESENT in the index now. The
    # pre-apply probe answered for the configuration as it stood then; between
    # that instant and this one another claimant may have changed it, or landed
    # a combination that was never itself probed. This DETECTS that window; it
    # does not close it. Closing it needs the reviewed content pinned against
    # concurrent change, which is not this stage's to do.
    reason = _screen_checkin_transform(
        git_root, rel, staged, "index blob after staging")
    if reason is not None:
        _restore_index_entry(git_root, rel, mode, prior_oid)
        return _excluded(reason)
    return OK


# ---------------------------------------------------------------------------
# Check-in conversion screen.
#
# THE LAYER THIS DECIDES AT IS THE WHOLE POINT. Two earlier attempts decided
# from what the CONFIGURATION SAYS -- an attribute name, or the token an
# attribute query answers with. Both are wrong in both directions, and the
# measurement is not subtle: three different attribute names answer the
# identical leading-dash token and split two-proceed against one-refuse: two
# of the three leave the bytes untouched, while the third alters them as soon
# as repository-level conversion is switched on, and the split follows the
# NAME rather than the token. A token rule would therefore need per-name
# semantics, i.e. the enumeration this screen exists to abolish -- and the
# names themselves are exactly what must not appear. So NO attribute name,
# no configuration token and no answer token appears
# anywhere below in an expression that determines the verdict.
#
# This screen decides from what the conversion DOES to the actual candidate
# bytes: hash the buffer twice, once with the path declared (so check-in
# conversion applies) and once raw. Unequal digests mean conversion would
# alter these exact bytes. That is the entire verdict.
#
# TWO OUTCOMES THAT MUST NOT BE CONFLATED, and are textually distinct so a
# reader learns the distinction here without executing anything:
#   * TRANSFORM OBSERVED  -- the two digests differ. A transform provably
#     exists for this buffer.
#   * COULD NOT BE COMPLETED -- the probe did not return a usable answer
#     (non-zero exit, death by signal, unparsable output, or exceeding the
#     bounded timeout below). UNPROVEN IS NOT ABSENT; it is also not proof
#     that a transform exists. Both refuse, but only the first asserts a
#     transform.
#
# The probe deliberately does NOT route through `_git`. A test that stubs
# `_git` wholesale is itself the "could not be completed" shape, and routing
# through it would turn a blanket stub into a refusal on EVERY path. Going
# direct to the process keeps an unrelated stub from steering this verdict.
# ---------------------------------------------------------------------------
_PROBE_TIMEOUT_SECONDS = 30

# Distinct leading phrases. AC7: each names a transform/encoding cause
# specifically and neither carries peer-conflict or ownership-ambiguity
# phrasing -- a conversion refusal is never routed to human adjudication.
SCREEN_TRANSFORM_PREFIX = "content-transform"
SCREEN_INDETERMINATE_PREFIX = "check-in conversion screening could not be completed"


class _ScreenIndeterminate(Exception):
    """The probe returned no usable answer. Not a transform; not an absence."""


def _hash_object_digest(git_root, data, rel=None):
    """One bounded `git hash-object --stdin` run. With `rel`, the path is
    declared so check-in conversion applies; without it, the bytes are hashed
    raw. Nothing is written to the object database."""
    args = ["git", "-C", git_root, "hash-object", "--stdin"]
    args.append("--path=" + rel if rel is not None else "--no-filters")
    try:
        proc = subprocess.run(args, input=data, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,
                              timeout=_PROBE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise _ScreenIndeterminate(
            "the probe exceeded its %d-second bound" % _PROBE_TIMEOUT_SECONDS)
    except OSError as exc:
        raise _ScreenIndeterminate("the probe could not be started: %s" % exc)
    if proc.returncode < 0:
        raise _ScreenIndeterminate(
            "the probe died on signal %d" % -proc.returncode)
    if proc.returncode != 0:
        raise _ScreenIndeterminate(
            "the probe exited %d: %s" % (
                proc.returncode,
                proc.stderr.decode("utf-8", "replace").strip() or "no detail"))
    digest = proc.stdout.strip().decode("ascii", "replace")
    if len(digest) != 40 or any(c not in "0123456789abcdef" for c in digest):
        raise _ScreenIndeterminate("the probe emitted unparsable output")
    return digest


def _checkin_transform_families(git_root, rel):
    """MESSAGE TEXT ONLY -- never branched on, never part of the verdict.

    `git check-attr --all` is attribute-AGNOSTIC: it is not given any attribute
    name and simply reports whichever attributes the path declares. It is
    reached only once a refusal has ALREADY been decided by the digest pair, so
    its failure can never change an outcome.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", git_root, "check-attr", "--all", "--", rel],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=_PROBE_TIMEOUT_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if proc.returncode != 0:
        return ""
    names = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        # "<path>: <attribute>: <answer>" -- take the attribute field as a
        # LABEL. Nothing is compared against it.
        parts = line.split(": ")
        if len(parts) >= 3 and parts[-2] not in names:
            names.append(parts[-2])
    return ",".join(names)


def _screen_checkin_transform(git_root, rel, data, what):
    """THE screening predicate. One implementation, shared by every stage.

    Returns None to proceed, or a refusal reason. A conversion-DISABLING
    configuration necessarily probes EQUAL and therefore PROCEEDS: refusing it
    would make landing harder with no safety gained, which is the opposite of
    this primitive's purpose.
    """
    try:
        declared = _hash_object_digest(git_root, data, rel=rel)
        raw = _hash_object_digest(git_root, data)
    except _ScreenIndeterminate as exc:
        return ("%s for %s: %s. Unproven is not absent -- this refuses without "
                "asserting that a transform exists -> EXCLUDE"
                % (SCREEN_INDETERMINATE_PREFIX, rel, exc))
    if declared == raw:
        return None
    label = _checkin_transform_families(git_root, rel) or "repository"
    return ("%s (%s=) attribute configured for %s -- check-in conversion would "
            "alter the %s bytes, so what lands would not be what was reviewed "
            "(probe digests differ: %s path-declared vs %s raw) -> EXCLUDE"
            % (SCREEN_TRANSFORM_PREFIX, label, rel, what, declared, raw))


def _screen_entry_stage(git_root, rel, abspath):
    """THE screening stage. Exactly ONE call site, in main(), ahead of EVERY
    route dispatch -- which is the only reason the three non-ledger routes are
    screened at all: each of them returns directly out of main().

    Returns None to proceed, or EXCLUDE."""
    try:
        data = _read_bytes(abspath)
    except OSError as exc:
        return _excluded("%s for %s: the candidate bytes are unreadable: %s "
                         "-> EXCLUDE" % (SCREEN_INDETERMINATE_PREFIX, rel, exc))
    reason = _screen_checkin_transform(git_root, rel, data, "worktree")
    if reason is not None:
        return _excluded(reason)
    return None


# ===========================================================================
# Ownership CLASSIFICATION and CONFLICT ESCALATION
# (docs/dev/specs/spec-20260914-052140.md §5.3 boundaries (a) and (c))
# ===========================================================================
#
# Three fundamentally different situations used to share one message and one
# status. They are now three named verdicts, and the evidence outcome rides
# BESIDE the classification instead of replacing it:
#
#   bytes no claimant accounts for          -> unaccounted_bytes
#   accounted for but not separable         -> accounted_not_separable
#   a genuine same-region double claim      -> ownership_conflict
#   (beside) own boundaries undeterminable  -> boundaries_undeterminable
#   (beside) claimant census incomplete     -> classification_undeterminable
#
# A true ownership conflict is NEVER resolved, merged, or decided here. The
# standing user ruling (§5.3 boundary (a)) forbids picking a side AND forbids
# silently discarding a claimant -- including discard by OMISSION, which is
# what INV-12 and INV-13 exist to make a validation failure rather than a
# smaller record.
#
# This route composes with, and does not contradict, the owned-only landing
# route above: it never dereferences the whole working tree, and its refusal
# vocabulary is disjoint from that route's SIDE/CAUSE precedence ladder, which
# continues to govern OWNED_FINAL_MISMATCH / BOUNDARY_INDETERMINATE refusals
# raised while assembling an owned-only image.

CLASSIFY_SCHEMA_ID = "owned-edits-classification.v1"

EVIDENCE_STATUS_ENUM = ("admissible", "boundaries_undeterminable",
                        "census_incomplete")

OVERLAP_CLASSIFICATION_ENUM = ("disjoint", "conflict", "not_applicable",
                               "not_computed")

V_ELIGIBLE = "eligible_for_staging"
V_NOTHING_OWNED = "nothing_owned"
V_UNACCOUNTED = "unaccounted_bytes"
V_NOT_SEPARABLE = "accounted_not_separable"
V_CONFLICT = "ownership_conflict"
V_BOUNDARIES = "boundaries_undeterminable"
V_CENSUS = "classification_undeterminable"

CLASSIFICATION_VERDICT_ENUM = (
    V_ELIGIBLE, V_NOTHING_OWNED, V_UNACCOUNTED, V_NOT_SEPARABLE,
    V_CONFLICT, V_BOUNDARIES, V_CENSUS,
)

# Enumeration (A) -- owned by classification_verdict == boundaries_undeterminable.
BOUNDARY_UNDETERMINABLE_REASON_ENUM = (
    "anchor_absent_in_own_baseline",
    "anchor_not_unique_in_own_baseline",
    "baseline_missing_or_unreadable",
    "baseline_is_committed_blob_not_dispatch_time_bytes",
    "bound_image_unavailable",
    "bound_images_incomparable",
)

# Enumeration (B) -- owned by classification_verdict == classification_undeterminable.
# INV-10: (A) and (B) share no string, which is what makes AC4 and AC9
# simultaneously satisfiable.
CENSUS_UNDETERMINABLE_REASON_ENUM = (
    "claimant_identity_unresolvable",
    "claim_enumeration_incomplete",
)

OBSTACLE_ENUM = (
    "binary",
    "mode_change",
    "line_ending_divergence",
    "content_transform_attribute",
    "not_tracked_in_index",
    "pre_staged_content_present",
    "apply_rejected",
    "readback_mismatch",
)

REASON_CLASS_ENUM = ("ownership", "evidence", "invalid_input",
                     "operational_error")

LOCATOR_KIND_ENUM = ("argument", "path", "claim_index", "anchor", "region")

# Governs the SUMMARY LABEL only. No region result is ever dropped, so this is
# reporting order, not selection.
SUMMARY_PRECEDENCE = (V_CONFLICT, V_CENSUS, V_BOUNDARIES, V_UNACCOUNTED,
                      V_NOT_SEPARABLE)

# "冲突" is the Chinese translation of "conflict". The strings checked against
# this tuple in _assert_message_vocabulary() below are English literals today,
# but several of their interpolated fields (boundary_undeterminable_reason,
# census_undeterminable_reason, obstacle) are read from upstream verdict
# records this module does not itself produce, so a translated leak is not
# excluded by construction. (task-id 20261005-033820)
BANNED_TOKENS_IN_NON_CONFLICT_MESSAGES = (
    "conflict", "entanglement", "entangled", "collision", "冲突",
)

NO_SELECTION_AND_NO_DISCARD = (
    "No side was chosen and no claimant was discarded. Both recorded versions "
    "are preserved verbatim; this decision is deferred to a human and may be "
    "deferred indefinitely."
)

# The named withheld-all status. Fixed BY NAME here so an arbitrary unequal
# label cannot pass, and deliberately distinct from nothing_to_commit.
STATUS_ALL_CANDIDATES_WITHHELD = "all_candidates_withheld"
STATUS_NOTHING_TO_COMMIT = "nothing_to_commit"

# A namespaced ref is not a branch, a PR or a worktree; it costs one ref plus
# objects that already exist (cf. the refs/checkpoints/* precedent).
PENDING_CONFLICT_REF_NAMESPACE = "refs/pending-conflicts"

# ---------------------------------------------------------------------------
# Invariants. IDENTICAL id strings are used here, in the schema and in the
# tests. Each is tested ACCORDING TO ITS OWN LOGICAL FORM: a one-way
# implication is NOT tested as a biconditional.
# ---------------------------------------------------------------------------
CLASSIFICATION_INVARIANTS = (
    {"id": "INV-01", "logical_form": "one-way implication",
     "invariant": "overlap_classification never takes the value "
                  "boundaries_undeterminable or classification_undeterminable."},
    {"id": "INV-02", "logical_form": "one-way implication",
     "invariant": "classification_verdict == ownership_conflict => "
                  "overlap_classification == conflict AND an escalation record "
                  "is present AND proven_overlap_pairs[] is non-empty AND every "
                  "member of every recorded pair is resolved against the SAME "
                  "bound_image_id AND claimants[] and versions[] cover the "
                  "COMPLETE participating_claims[] union."},
    {"id": "INV-03", "logical_form": "one-way implication",
     "invariant": "overlap_classification == conflict => "
                  "classification_verdict == ownership_conflict."},
    {"id": "INV-04", "logical_form": "one-way implication",
     "invariant": "classification_verdict == ownership_conflict => the "
                  "participating claims resolve to at least two DISTINCT "
                  "task_id values, none of them absent or empty. The TASK is "
                  "the party (§5.3 boundary (a)); claimant_id is a handle and "
                  "is NOT an identity condition, because one agent legitimately "
                  "spans two tasks and any number of handles may name one task. "
                  "Cardinality of claims alone is insufficient."},
    {"id": "INV-05", "logical_form": "one-way implication",
     "invariant": "overlap_classification == conflict => every participating "
                  "claim is resolved against the SAME bound_image_id."},
    {"id": "INV-06", "logical_form": "one-way implication",
     "invariant": "(evidence_status != admissible AND proven_overlap_pairs[] is "
                  "EMPTY) => overlap_classification == not_computed AND "
                  "classification_verdict in {boundaries_undeterminable, "
                  "classification_undeterminable}."},
    {"id": "INV-07", "logical_form": "one-way implication",
     "invariant": "(evidence_status == admissible AND fewer than two claims are "
                  "eligible for comparison) => overlap_classification == "
                  "not_applicable AND classification_verdict != ownership_conflict."},
    {"id": "INV-08", "logical_form": "one-way implication",
     "invariant": "classification_verdict == unaccounted_bytes => "
                  "claimant_census.complete == true."},
    {"id": "INV-09", "logical_form": "one-way implication",
     "invariant": "every refusal has reason_class set, a non-null reason_code, "
                  "and exactly one populated locator; region content is required "
                  "only when reason_class == ownership."},
    {"id": "INV-10", "logical_form": "iff - test BOTH logical directions "
                                     "(field-presence clauses)",
     "invariant": "boundary_undeterminable_reason and "
                  "census_undeterminable_reason are DISJOINT value sets, and "
                  "each is populated IFF its own verdict is emitted."},
    {"id": "INV-11", "logical_form": "one-way implication - do NOT enforce the "
                                     "converse",
     "invariant": "(classification_verdict == ownership_conflict AND "
                  "evidence_status != admissible) => evidence_caveats[] is "
                  "NON-EMPTY and names the specific typed sub_reason and, for "
                  "boundary caveats, the affected non-participating claims."},
    {"id": "INV-12",
     "logical_form": "set equality - test BOTH failure directions "
                     "(omission and invention)",
     "invariant": "proven_overlap_pairs[], read as a SET of unordered pairs, "
                  "EQUALS the complete set of QUALIFYING pairs computed over "
                  "candidate_claims[]. Omission and invention both fail."},
    {"id": "INV-13",
     "logical_form": "set equality - test BOTH failure directions "
                     "(omission and invention)",
     "invariant": "candidate_claims[], read as a SET, EQUALS the "
                  "REGION-RESTRICTED PROJECTION OF THE CLASSIFIER'S CLAIM INPUT "
                  "for that region -- not a subset of it, and NEVER re-derived "
                  "from the record under test. INV-12 quantifies over "
                  "candidate_claims[]; without INV-13 an emitter that "
                  "under-populates candidate_claims[] shrinks the qualifying "
                  "domain so that INV-02's complete-union clause, INV-04, "
                  "INV-05 and INV-12 itself all still pass while a claimant "
                  "vanishes. That is discard by omission, which §5.3 boundary "
                  "(a) forbids in the user's own words."},
)

CLASSIFICATION_INVARIANT_IDS = tuple(
    inv["id"] for inv in CLASSIFICATION_INVARIANTS)


class ClaimInputError(ValueError):
    """The claim input itself is malformed -- an invalid_input refusal."""


# --- Interval algebra (R-INTERVAL-ALGEBRA) ---------------------------------
#
# Every resolved region is a HALF-OPEN byte interval [start, end) in the bound
# image's coordinate space. A pure insertion at coordinate k is the degenerate
# interval [k, k). This algebra decides ONLY pair qualification: it authorizes
# no landing and selects no side.

def _interval_intersects(a, b):
    a0, a1 = a
    b0, b1 = b
    a_zero = a0 == a1
    b_zero = b0 == b1
    if a_zero and b_zero:
        # Rule 4: two insertions at the SAME coordinate share no byte but write
        # at one insertion point; their combined result is order-dependent and
        # not separable, so they ARE a genuine same-coordinate double claim.
        return a0 == b0
    if a_zero:
        # Rule 5: strictly interior intersects; boundary-coincident is adjacency.
        return b0 < a0 < b1
    if b_zero:
        return a0 < b0 < a1
    # Rules 2 and 3: share at least one byte; b == c is adjacency, not
    # intersection. This direction is what keeps interleaving from failing
    # closed, which §5.3 forbids.
    return max(a0, b0) < min(a1, b1)


def _interval_intersection(a, b):
    if not _interval_intersects(a, b):
        return None
    if a[0] == a[1]:
        return [a[0], a[1]]
    if b[0] == b[1]:
        return [b[0], b[1]]
    return [max(a[0], b[0]), min(a[1], b[1])]


# --- Claim accessors -------------------------------------------------------

def _claim_ref(claim, index):
    ref = claim.get("claim_ref")
    if ref:
        return str(ref)
    cid = claim.get("claimant_id")
    return str(cid) if cid else "claim[%d]" % index


def _claim_region_id(claim, claim_input):
    return claim.get("region_id") or claim_input.get("default_region_id") or "R1"


def _claim_boundary(claim):
    br = claim.get("boundary_resolution")
    return br if isinstance(br, dict) else {}


def _claim_resolved(claim):
    return _claim_boundary(claim).get("resolved") is True


def _claim_image(claim):
    return _claim_boundary(claim).get("bound_image_id")


def _claim_interval(claim):
    iv = _claim_boundary(claim).get("interval")
    if (isinstance(iv, (list, tuple)) and len(iv) == 2
            and all(isinstance(v, int) for v in iv) and iv[0] <= iv[1]):
        return [iv[0], iv[1]]
    return None


def region_restricted_claim_projection(claim_input, region_id):
    """INV-13's RIGHT-HAND SIDE: the region-restricted projection of the
    classifier's own CLAIM INPUT.

    This is the single definitional source of candidate_claims[]. It is
    computed from the INPUT and never from a record, so binding a record's
    candidate_claims[] to it is non-circular: a record that omits an input
    claimant cannot satisfy the equality by also shrinking the domain.
    """
    refs = []
    for index, claim in enumerate(claim_input.get("claims") or []):
        if not isinstance(claim, dict):
            raise ClaimInputError("claims[%d] is not an object" % index)
        if _claim_region_id(claim, claim_input) == region_id:
            refs.append(_claim_ref(claim, index))
    return refs


def _pair_qualifies(claim_a, claim_b):
    """The three qualifying conditions, in order, with the first failure named.

    PARTY IDENTITY IS THE TASK, NEVER THE HANDLE. claimant_id is a handle, and
    one agent legitimately spans two tasks, so a shared handle is not evidence
    of one party -- it is not consulted here at all. A handle comparison used
    to sit ahead of the task comparison and decided party identity before the
    task was ever read, which silently withheld a genuine two-task double claim
    from escalation. The ordering hazard is removed by there being exactly ONE
    identity condition to apply, not by sequencing two correctly: there is no
    comparison order left to maintain by hand.

    Every remaining condition is conjunctive, so the qualification verdict is
    independent of the order they are applied in; only the reported reason
    label depends on it.
    """
    task_a = claim_a.get("task_id")
    task_b = claim_b.get("task_id")
    if not task_a or not task_b:
        # A claim whose task cannot be resolved is not a second party.
        return False, "claimant_identity_unresolvable"
    if task_a == task_b:
        # §5.3 boundary (a) is stated over two TASKS; any number of handles
        # naming one task are ONE party, not two.
        return False, "same_task_id"
    if not (_claim_resolved(claim_a) and _claim_resolved(claim_b)):
        return False, "boundary_not_resolved"
    if _claim_image(claim_a) != _claim_image(claim_b) or _claim_image(claim_a) is None:
        return False, "bound_images_incomparable"
    iv_a = _claim_interval(claim_a)
    iv_b = _claim_interval(claim_b)
    if iv_a is None or iv_b is None:
        return False, "boundary_not_resolved"
    if not _interval_intersects(iv_a, iv_b):
        return False, "intervals_disjoint"
    return True, None


def compute_qualifying_pairs(claims_by_ref, candidate_refs):
    """The complete set of qualifying pairs over candidate_claims[].

    Returned as a list of records; INV-12 compares it AS A SET, so ordering is
    reporting order only.
    """
    pairs = []
    refs = list(candidate_refs)
    for i in range(len(refs)):
        for j in range(i + 1, len(refs)):
            claim_a = claims_by_ref[refs[i]]
            claim_b = claims_by_ref[refs[j]]
            ok, _why = _pair_qualifies(claim_a, claim_b)
            if not ok:
                continue
            pairs.append({
                "claimant_a": refs[i],
                "claimant_b": refs[j],
                "interval": _interval_intersection(_claim_interval(claim_a),
                                                   _claim_interval(claim_b)),
                "bound_image_id": _claim_image(claim_a),
            })
    return pairs


def _pair_key(pair):
    return tuple(sorted((pair["claimant_a"], pair["claimant_b"])))


def _eligible_for_comparison(claims_by_ref, candidate_refs):
    """Claims resolved against a bound image AND having at least one other
    candidate resolvable to a DIFFERENT task. Fewer than two of these means
    there is nothing to compare (INV-07's not_applicable), which is a different
    fact from an evidence failure (not_computed)."""
    eligible = []
    for ref in candidate_refs:
        claim = claims_by_ref[ref]
        if not _claim_resolved(claim) or not claim.get("task_id"):
            continue
        for other_ref in candidate_refs:
            if other_ref == ref:
                continue
            other = claims_by_ref[other_ref]
            if (_claim_resolved(other) and other.get("task_id")
                    and other.get("task_id") != claim.get("task_id")
                    and _claim_image(other) == _claim_image(claim)):
                eligible.append(ref)
                break
    return eligible


# --- Escalation record (E1..E6) -------------------------------------------

def _canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _derive_conflict_record_id(path, bound_image_id, contested_region,
                               participating_ids, version_ids):
    """E5(iii): DERIVED from a canonical representation binding path, bound
    image, contested region, participating claimant ids and version ids. A
    reused constant is a validation failure."""
    canon = _canonical_json({
        "path": path,
        "bound_image_id": bound_image_id,
        "contested_region": {
            "anchor": (contested_region or {}).get("anchor"),
            "interval": (contested_region or {}).get("interval"),
        },
        "participating_claimant_ids": sorted(participating_ids),
        "version_ids": sorted(version_ids),
    })
    return "conflict-sha256:" + hashlib.sha256(
        canon.encode("utf-8")).hexdigest()


def _derive_preview_digest(conflict_record_id, claim_ref, outcome_text):
    """E5(i): authenticates the preview and MUST NOT identify a complete
    candidate post-image. The domain separator and the non-git prefix mean no
    staging or apply interface will accept this string as an object id.

    Keyed on claim_ref -- the identity key every set-valued invariant and every
    other field of this record is already stated over -- and NEVER on
    claimant_id. A handle is only a handle: one agent legitimately spans two
    tasks, so two claims may share one. Keying here on the handle made the two
    previews collide OUTRIGHT whenever the proposed bytes also matched, and one
    digest then authenticated two different parties' previews. claim_ref is
    refused at the input boundary when it repeats, so its distinctness is by
    construction and no list or ordering is maintained by hand.
    """
    canon = "preview\x00%s\x00%s\x00%s" % (
        conflict_record_id, claim_ref, outcome_text)
    return "preview-sha256:" + hashlib.sha256(
        canon.encode("utf-8")).hexdigest()


def _common_affixes(texts):
    """The identical leading and trailing context shared by every candidate
    outcome. Everything strictly between them DIFFERS somewhere, so keeping it
    all inline satisfies E5(ii)'s complete-union rule while truncation removes
    ONLY identical context."""
    if not texts:
        return 0, 0
    shortest = min(len(t) for t in texts)
    prefix = 0
    while prefix < shortest and len({t[prefix] for t in texts}) == 1:
        prefix += 1
    suffix = 0
    while (suffix < shortest - prefix
           and len({t[len(t) - 1 - suffix] for t in texts}) == 1):
        suffix += 1
    return prefix, suffix


def _build_escalation_record(path, region, pairs, participating_refs,
                             claims_by_ref):
    """E1-E6. Produces evidence a human can act on WITHOUT opening the
    repository, and selects nothing."""
    bound_image_id = pairs[0]["bound_image_id"] if pairs else None
    contested_interval = None
    for pair in pairs:
        iv = pair.get("interval")
        if iv is None:
            continue
        if contested_interval is None:
            contested_interval = list(iv)
        else:
            contested_interval = [min(contested_interval[0], iv[0]),
                                  max(contested_interval[1], iv[1])]

    anchor = (region.get("anchor") or {})
    contested_region = {
        # R-CONTENT-ANCHOR: the region is identified BY ITS CONTENT. Line
        # numbers move under concurrent editing and are advisory only.
        "anchor": anchor.get("content"),
        "anchor_kind": "content",
        "interval": contested_interval,
        "bound_image_id": bound_image_id,
        "advisory_line_number": anchor.get("advisory_line_number"),
        "advisory_line_number_is_advisory": True,
    }
    anchor_uniqueness = {
        "count": anchor.get("occurrence_count"),
        # Overlap-inclusive counting: advancing by the needle length misses
        # overlapping matches, so a self-overlapping anchor could otherwise be
        # certified as uniquely located.
        "counting": "overlap_inclusive",
    }

    claimants = []
    versions = []
    for ref in participating_refs:
        claim = claims_by_ref[ref]
        version = claim.get("version") or {}
        claimants.append({
            "claim_ref": ref,
            "claimant_id": claim.get("claimant_id"),
            "session_id": claim.get("session_id"),
            "task_id": claim.get("task_id"),
            "boundary_resolution": _claim_boundary(claim),
        })
        versions.append({
            "claim_ref": ref,
            "claimant_id": claim.get("claimant_id"),
            "version_id": version.get("version_id") or version.get("content_oid"),
            "content_oid": version.get("content_oid"),
            # E3: an object id ALONE would require opening the repository and
            # fails the readable-without-the-repository test.
            "excerpt": version.get("excerpt", version.get("bytes", "")),
            "bytes": version.get("bytes", ""),
            "preserved": True,
        })

    record_id = _derive_conflict_record_id(
        path, bound_image_id, contested_region,
        [c["claimant_id"] for c in claimants],
        [v["version_id"] for v in versions])

    context_before = region.get("context_before", "")
    context_after = region.get("context_after", "")
    candidate_texts = [v["bytes"] for v in versions]
    pre_len, suf_len = _common_affixes(candidate_texts)

    if_chosen = []
    for version in versions:
        text = version["bytes"]
        differing = text[pre_len:len(text) - suf_len] if suf_len else text[pre_len:]
        identical_prefix = text[:pre_len]
        identical_suffix = text[len(text) - suf_len:] if suf_len else ""
        outcome_text = context_before + text + context_after
        if_chosen.append({
            "claimant_id": version["claimant_id"],
            "claim_ref": version["claim_ref"],
            "bound_image_id": bound_image_id,
            "contested_interval": contested_interval,
            # E5(i): NOT an apply-ready object id. Keyed on claim_ref, not on
            # the handle, so two claims sharing a handle keep two digests even
            # when they propose identical bytes.
            "preview_digest": _derive_preview_digest(
                record_id, version["claim_ref"], outcome_text),
            # E5(ii): the COMPLETE union of differing ranges, inline.
            "decision_relevant_ranges": (
                [[pre_len, len(text) - suf_len]] if differing else []),
            "inline_outcome": {
                "identical_prefix": identical_prefix,
                "differing_bytes": differing,
                "identical_suffix": identical_suffix,
                "omitted_context_bytes": 0,
                "context_before": context_before,
                "context_after": context_after,
            },
            # Addressed by claim_ref for the same reason as the digest: under a
            # shared handle two summaries keyed on the handle read WORD FOR
            # WORD identically in the ordinary differing-bytes case, and a
            # record whose two options read the same does not let a human
            # decide. The handle stays available in claimant_id beside it.
            "summary": ("deciding for claim %s (handle %s, task %s) would "
                        "place that claim's recorded bytes in the contested "
                        "region and leave every byte outside it unchanged"
                        % (version["claim_ref"], version["claimant_id"],
                           claims_by_ref[version["claim_ref"]].get("task_id"))),
            "authority": "preview_only",
        })

    return {
        "conflict_record_id": record_id,
        "escalation_record_id": record_id,
        "path": path,
        "claimants": claimants,
        "versions": versions,
        "contested_region": contested_region,
        "anchor_uniqueness": anchor_uniqueness,
        "if_chosen": if_chosen,
        "no_selection_and_no_discard": NO_SELECTION_AND_NO_DISCARD,
        "requires_human_adjudication": True,
        "deferrable_indefinitely": True,
        "region_scoped": True,
        # The FULL digest, never a truncated prefix: a prefix collision between
        # two different pending records would make one overwrite the other.
        "pending_conflict_ref": "%s/%s" % (
            PENDING_CONFLICT_REF_NAMESPACE, record_id.split(":", 1)[1]),
        "side_effects": {"index": False, "worktree": False,
                         "chosen_side_ref": False, "commit": False},
    }


# --- Per-region classification --------------------------------------------

def _first_unresolved(claims_by_ref, candidate_refs, participating_refs):
    """Predicate 2's antecedent: a claim REQUIRED TO DECIDE THIS REGION and NOT
    a member of a proven overlapping pair whose boundaries are unresolved."""
    for index, ref in enumerate(candidate_refs):
        if ref in participating_refs:
            continue
        claim = claims_by_ref[ref]
        if not _claim_resolved(claim) or _claim_interval(claim) is None:
            reason = (_claim_boundary(claim).get("unresolved_reason")
                      or "bound_image_unavailable")
            if reason not in BOUNDARY_UNDETERMINABLE_REASON_ENUM:
                reason = "bound_image_unavailable"
            return ref, index, reason
    return None, None, None


def classify_region(claim_input, region, claims_by_ref):
    """The ordered predicates, applied per region, first match wins.

    The order is SEMANTIC and is independent of any control-flow order
    elsewhere in this file.
    """
    region_id = region.get("region_id") or "R1"
    path = claim_input.get("path") or ""

    # INV-13: the candidate set is the region-restricted projection of the
    # CLAIM INPUT, taken BEFORE any pair is computed and never derived from a
    # recorded array.
    candidate_refs = region_restricted_claim_projection(claim_input, region_id)

    census = claim_input.get("claimant_census") or {}
    census_complete = census.get("complete") is True
    census_reason = census.get("reason")
    identity_unresolvable = any(
        not claims_by_ref[ref].get("task_id") for ref in candidate_refs)
    if identity_unresolvable:
        census_complete = False
        census_reason = "claimant_identity_unresolvable"
    elif not census_complete and census_reason not in CENSUS_UNDETERMINABLE_REASON_ENUM:
        census_reason = "claim_enumeration_incomplete"

    pairs = compute_qualifying_pairs(claims_by_ref, candidate_refs)
    participating_refs = []
    for ref in candidate_refs:
        if any(ref in (p["claimant_a"], p["claimant_b"]) for p in pairs):
            participating_refs.append(ref)

    unresolved_ref, unresolved_index, unresolved_reason = _first_unresolved(
        claims_by_ref, candidate_refs, set(participating_refs))

    # Incomparable bound images are an EVIDENCE failure, never "nothing to
    # compare": two claims WERE each resolved, but against different images, so
    # their coordinates do not live in one space.
    resolved_images = {_claim_image(claims_by_ref[r])
                       for r in candidate_refs
                       if _claim_resolved(claims_by_ref[r])
                       and r not in participating_refs}
    resolved_images.discard(None)
    incomparable = (unresolved_ref is None and len(resolved_images) > 1)

    boundary_gap = unresolved_ref is not None or incomparable
    if boundary_gap:
        evidence_status = "boundaries_undeterminable"
    elif not census_complete:
        evidence_status = "census_incomplete"
    else:
        evidence_status = "admissible"

    result = {
        "region_id": region_id,
        "candidate_claims": candidate_refs,
        "proven_overlap_pairs": pairs,
        "participating_claims": participating_refs,
        "claimant_census": {"complete": census_complete,
                            "reason": census_reason if not census_complete else None},
        "evidence_status": evidence_status,
        "evidence_caveats": [],
        "index_effect": {"mutated": False, "unstaged_paths": [],
                         "detail": "classification is read-only; the index and "
                                   "the working tree are not touched"},
        "route_decision": {
            "new_file_whole_file_add": False,
            "detail": ("the classification-bypassing whole-file route is not "
                       "taken: %d claims are retained for this region "
                       "(R-NEW-PATH-GATE)" % len(candidate_refs)),
        },
    }

    def _caveats():
        caveats = []
        if boundary_gap:
            affected = ([unresolved_ref] if unresolved_ref
                        else [r for r in candidate_refs
                              if r not in participating_refs
                              and _claim_resolved(claims_by_ref[r])])
            caveats.append({
                "kind": "boundary",
                "sub_reason": ("bound_images_incomparable" if incomparable
                               else unresolved_reason),
                # A boundary caveat MUST name its known affected claims.
                "affected_claim_refs": affected,
                "evidence_locator": {"kind": "region", "value": region_id},
            })
        if not census_complete:
            caveats.append({
                "kind": "census",
                "sub_reason": census_reason,
                # A census caveat with claim_enumeration_incomplete MAY carry an
                # empty affected_claim_refs[]: "enumeration incomplete" means
                # precisely that some claims cannot be named.
                "affected_claim_refs": (
                    [r for r in candidate_refs
                     if not claims_by_ref[r].get("task_id")]
                    if census_reason == "claimant_identity_unresolvable" else []),
                "unresolved_scope": {"region_id": region_id, "path": path},
                "evidence_locator": {"kind": "region", "value": region_id},
            })
        return caveats

    # PREDICATE 1 -- a proven overlapping pair exists. Fires REGARDLESS of the
    # resolution status of any non-participating claim and REGARDLESS of
    # whether the wider census is complete: any such incompleteness is recorded
    # BESIDE the verdict and never replaces it (R-PROVEN-OVERLAP-WINS).
    if pairs:
        escalation = _build_escalation_record(
            path, region, pairs, participating_refs, claims_by_ref)
        result.update({
            "classification_verdict": V_CONFLICT,
            "overlap_classification": "conflict",
            "refusal": True,
            "reason_class": "ownership",
            "reason_code": "OWNERSHIP_CONFLICT_SAME_REGION",
            "locator": {"kind": "region", "value": region_id},
            "escalation_record": escalation,
            "escalation_record_id": escalation["escalation_record_id"],
            "claimants": escalation["claimants"],
            "versions": escalation["versions"],
            "contested_region": escalation["contested_region"],
            "anchor_uniqueness": escalation["anchor_uniqueness"],
            "if_chosen": escalation["if_chosen"],
            "no_selection_and_no_discard": NO_SELECTION_AND_NO_DISCARD,
            "evidence_caveats": _caveats(),
        })
        return result

    # PREDICATE 2 -- own boundaries not determinable. §5.3 (c): state
    # specifically WHY, and never report it as somebody else's clash.
    if boundary_gap:
        reason = "bound_images_incomparable" if incomparable else unresolved_reason
        result.update({
            "classification_verdict": V_BOUNDARIES,
            "overlap_classification": "not_computed",
            "refusal": True,
            "reason_class": "evidence",
            "reason_code": "BOUNDARY_UNDETERMINABLE:%s" % reason,
            "boundary_undeterminable_reason": reason,
            "locator": ({"kind": "claim_index", "value": unresolved_index}
                        if unresolved_ref is not None
                        else {"kind": "region", "value": region_id}),
            "evidence": {
                "claim_index": unresolved_index,
                "claim_ref": unresolved_ref,
                "occurrence_count": (
                    _claim_boundary(claims_by_ref[unresolved_ref]).get(
                        "occurrence_count", 0)
                    if unresolved_ref is not None else None),
                "bound_image_ids": sorted(resolved_images) if incomparable else None,
            },
            "evidence_caveats": _caveats(),
        })
        return result

    # PREDICATE 3 -- claimant census incomplete. Reached ONLY when predicate 2
    # did not fire; neither a conflict nor an orphan is asserted, and every
    # observed claim and version is preserved.
    if not census_complete:
        result.update({
            "classification_verdict": V_CENSUS,
            "overlap_classification": "not_computed",
            "refusal": True,
            "reason_class": "evidence",
            "reason_code": "CENSUS_UNDETERMINABLE:%s" % census_reason,
            "census_undeterminable_reason": census_reason,
            "locator": {"kind": "region", "value": region_id},
            "claims": [claims_by_ref[r] for r in candidate_refs],
            "versions": [dict(claims_by_ref[r].get("version") or {},
                              claim_ref=r,
                              claimant_id=claims_by_ref[r].get("claimant_id"),
                              preserved=True)
                         for r in candidate_refs],
            "evidence_caveats": _caveats(),
        })
        return result

    # PREDICATE 4 -- changed bytes covered by NO claim, census COMPLETE.
    uncovered = _uncovered_ranges(region, claims_by_ref, candidate_refs)
    if uncovered:
        result.update({
            "classification_verdict": V_UNACCOUNTED,
            "overlap_classification": _overlap_when_no_pair(
                claims_by_ref, candidate_refs, evidence_status),
            "refusal": True,
            "reason_class": "ownership",
            "reason_code": "UNACCOUNTED_BYTES",
            "locator": {"kind": "region", "value": region_id},
            "unaccounted_ranges": uncovered,
        })
        return result

    # PREDICATE 5 -- accounted for, but a structural obstacle prevents
    # separating this claimant's bytes.
    obstacle = region.get("obstacle")
    if obstacle:
        if obstacle not in OBSTACLE_ENUM:
            raise ClaimInputError("unknown obstacle %r" % (obstacle,))
        result.update({
            "classification_verdict": V_NOT_SEPARABLE,
            "overlap_classification": _overlap_when_no_pair(
                claims_by_ref, candidate_refs, evidence_status),
            "refusal": True,
            "reason_class": "ownership",
            "reason_code": "ACCOUNTED_NOT_SEPARABLE:%s" % obstacle,
            "obstacle": obstacle,
            "locator": {"kind": "region", "value": region_id},
        })
        return result

    # PREDICATE 6 -- a POSITIVE outcome with a named verdict, not a residual.
    # The name is deliberately NON-EFFECTFUL: the index side effect belongs to
    # the landing route, not here.
    result.update({
        "classification_verdict": V_ELIGIBLE,
        "overlap_classification": _overlap_when_no_pair(
            claims_by_ref, candidate_refs, evidence_status),
        "refusal": False,
        "reason_class": None,
        "reason_code": None,
        "locator": None,
    })
    return result


def _overlap_when_no_pair(claims_by_ref, candidate_refs, evidence_status):
    if evidence_status != "admissible":
        return "not_computed"
    if len(_eligible_for_comparison(claims_by_ref, candidate_refs)) < 2:
        # "fewer than two claims eligible for comparison -- nothing to compare".
        return "not_applicable"
    return "disjoint"


def _uncovered_ranges(region, claims_by_ref, candidate_refs):
    changed = region.get("changed_byte_ranges") or []
    covered = []
    for ref in candidate_refs:
        iv = _claim_interval(claims_by_ref[ref])
        if iv is not None:
            covered.append(iv)
    uncovered = []
    for rng in changed:
        start, end = rng[0], rng[1]
        cursor = start
        for cov in sorted(covered):
            if cov[1] <= cursor or cov[0] >= end:
                continue
            if cov[0] > cursor:
                uncovered.append([cursor, min(cov[0], end)])
            cursor = max(cursor, cov[1])
            if cursor >= end:
                break
        if cursor < end:
            uncovered.append([cursor, end])
    return uncovered


# --- Rendered message ------------------------------------------------------

def render_classification_message(result, path):
    verdict = result.get("classification_verdict")
    if verdict == V_CONFLICT:
        names = ", ".join(str(c.get("claimant_id")) for c in result["claimants"])
        return ("OWNERSHIP CONFLICT on %s region %s: %s assert the same region. "
                "%s Adjudicate with the escalation record %s."
                % (path, result["region_id"], names,
                   NO_SELECTION_AND_NO_DISCARD,
                   result["escalation_record_id"]))
    # Every message below is checked against
    # BANNED_TOKENS_IN_NON_CONFLICT_MESSAGES before it is emitted: §5.3 (c)
    # forbids a boundary-indeterminacy or census refusal being reported as
    # somebody else's clash.
    if verdict == V_BOUNDARIES:
        return ("The owned-region boundaries for %s region %s could not be "
                "determined: %s. Evidence: claim index %s, occurrence count %s. "
                "No counterparty is asserted."
                % (path, result["region_id"],
                   result.get("boundary_undeterminable_reason"),
                   result.get("evidence", {}).get("claim_index"),
                   result.get("evidence", {}).get("occurrence_count")))
    if verdict == V_CENSUS:
        return ("The claimant census for %s region %s is incomplete: %s. Every "
                "observed claim and version is preserved; neither an orphan nor "
                "a second party is asserted."
                % (path, result["region_id"],
                   result.get("census_undeterminable_reason")))
    if verdict == V_UNACCOUNTED:
        return ("%d changed byte range(s) in %s region %s are covered by no "
                "retained claim under a complete claimant census."
                % (len(result.get("unaccounted_ranges") or []), path,
                   result["region_id"]))
    if verdict == V_NOT_SEPARABLE:
        return ("Every changed byte in %s region %s is accounted for, but the "
                "structural obstacle %r prevents separating this claimant's "
                "bytes." % (path, result["region_id"], result.get("obstacle")))
    return ("Owned regions for %s region %s are separable and no refusal "
            "applies." % (path, result["region_id"]))


def _assert_message_vocabulary(message, verdict):
    """A non-conflict refusal may not borrow the vocabulary of a double claim."""
    if verdict == V_CONFLICT:
        return
    lowered = message.lower()
    for token in BANNED_TOKENS_IN_NON_CONFLICT_MESSAGES:
        if token in lowered:
            raise AssertionError(
                "banned token %r leaked into a %s message" % (token, verdict))


# --- Record assembly -------------------------------------------------------

def _refusal_envelope(reason_class, reason_code, locator_kind, locator_value,
                      message, path=None):
    """Every refusal carries a locatable reason -- INCLUDING invalid-input and
    operational failures, where no content region exists. Forcing those into an
    ownership verdict would itself be a false classification."""
    return {
        "schema": CLASSIFY_SCHEMA_ID,
        "refusal": True,
        "path": path,
        "reason_class": reason_class,
        "reason_code": reason_code,
        "locator": {"kind": locator_kind, "value": locator_value},
        "message": message,
        "classification_verdict": None,
        "overlap_classification": None,
        "invariant_ids": list(CLASSIFICATION_INVARIANT_IDS),
    }


def classify_claim_input(claim_input):
    """Classify every region of one path. region_results[] is AUTHORITATIVE and
    is never erased; the top-level summary is DERIVED from it by precedence,
    which governs the LABEL only and drops no region."""
    if not isinstance(claim_input, dict):
        raise ClaimInputError("claim input must be an object")
    path = claim_input.get("path")
    if not path:
        raise ClaimInputError("claim input has no path")

    # claim_ref IS the identity key every set-valued invariant is stated over,
    # so a DUPLICATE ref is not a cosmetic problem: the second claim would
    # overwrite the first in this dict and two genuinely distinct claimants
    # would collapse into one. INV-13's set equality cannot see that -- the
    # projection carries the duplicate too, and {dup} == {dup} holds -- so the
    # collision has to be refused HERE, at the input boundary, or a real
    # same-region double claim is reported as eligible_for_staging with every
    # invariant green. That is the silent discard §5.3 boundary (a) forbids.
    claims_by_ref = {}
    for index, claim in enumerate(claim_input.get("claims") or []):
        if not isinstance(claim, dict):
            raise ClaimInputError("claims[%d] is not an object" % index)
        ref = _claim_ref(claim, index)
        if ref in claims_by_ref:
            raise ClaimInputError(
                "duplicate claim_ref %r at claims[%d]: claim_ref is the "
                "identity key every set-valued invariant is stated over, so a "
                "collision would silently collapse two claimants into one"
                % (ref, index))
        claims_by_ref[ref] = claim

    regions = claim_input.get("regions")
    if not regions:
        regions = [{"region_id": claim_input.get("default_region_id") or "R1"}]

    # A claim whose region_id names no DECLARED region would be projected into
    # no region at all and would therefore vanish from every candidate set
    # without tripping a single invariant -- a whole claimant discarded in
    # silence. Refuse instead.
    declared = {region.get("region_id") or "R1" for region in regions}
    for index, claim in enumerate(claim_input.get("claims") or []):
        region_id = _claim_region_id(claim, claim_input)
        if region_id not in declared:
            raise ClaimInputError(
                "claims[%d] (%r) names region %r, which is not among the "
                "declared regions %s: a claim projected into no region would "
                "be dropped from every candidate set without violating any "
                "invariant" % (index, _claim_ref(claim, index), region_id,
                               sorted(declared)))

    region_results = []
    for region in regions:
        result = classify_region(claim_input, region, claims_by_ref)
        result["message"] = render_classification_message(result, path)
        _assert_message_vocabulary(result["message"],
                                   result["classification_verdict"])
        region_results.append(result)

    summary = None
    for verdict in SUMMARY_PRECEDENCE:
        if any(r["classification_verdict"] == verdict for r in region_results):
            summary = verdict
            break
    if summary is None:
        summary = V_ELIGIBLE
    summary_region = next(r for r in region_results
                          if r["classification_verdict"] == summary)

    refusal = any(r.get("refusal") for r in region_results)
    withheld = [{"path": path,
                 "region": r["region_id"],
                 "classification_verdict": r["classification_verdict"],
                 "reason_code": r["reason_code"]}
                for r in region_results if r.get("refusal")]

    if withheld and len(withheld) == len(region_results):
        status = STATUS_ALL_CANDIDATES_WITHHELD
    elif not region_results or (not withheld and not claims_by_ref
                                and not any(r.get("changed_byte_ranges")
                                            for r in regions)):
        status = STATUS_NOTHING_TO_COMMIT
    else:
        status = "partially_withheld" if withheld else "eligible"

    record = {
        "schema": CLASSIFY_SCHEMA_ID,
        "path": path,
        "refusal": refusal,
        # region_results[] is authoritative and never erased.
        "region_results": region_results,
        "summary_is_derived": True,
        "summary_precedence": list(SUMMARY_PRECEDENCE),
        "invariant_ids": list(CLASSIFICATION_INVARIANT_IDS),
        "staging_outcome": {"status": status, "withheld": withheld},
        "status": status,
    }
    # The summary region's fields are HOISTED for readability. They are a
    # derived view of region_results[]; nothing is dropped by hoisting.
    for key, value in summary_region.items():
        if key == "region_id":
            record["summary_region_id"] = value
        else:
            record.setdefault(key, value)
    record["classification_verdict"] = summary
    return record


# --- Validation: the invariants, enforced rather than described ------------

def validate_classification_record(record, claim_input):
    """Return a list of {invariant, detail} violations.

    `claim_input` is REQUIRED and is the binding that makes INV-13 non-circular:
    candidate_claims[] is checked against the region-restricted projection of
    THE INPUT, never against anything re-derived from `record`.
    """
    violations = []

    def fail(inv_id, detail):
        violations.append({"invariant": inv_id, "detail": detail})

    if not isinstance(record, dict):
        return [{"invariant": "INV-09", "detail": "record is not an object"}]

    for result in record.get("region_results") or []:
        region_id = result.get("region_id")
        verdict = result.get("classification_verdict")
        overlap = result.get("overlap_classification")
        pairs = result.get("proven_overlap_pairs") or []
        candidates = list(result.get("candidate_claims") or [])
        participating = list(result.get("participating_claims") or [])
        evidence_status = result.get("evidence_status")

        # INV-13 -- candidate_claims[] EQUALS the region-restricted projection
        # of the CLAIM INPUT. Checked FIRST because every other set-valued
        # invariant quantifies over this domain: without it they are all
        # satisfiable on a shrunken domain while a claimant vanishes.
        try:
            projection = region_restricted_claim_projection(claim_input, region_id)
        except ClaimInputError as exc:
            fail("INV-13", "claim input unusable for region %s: %s"
                 % (region_id, exc))
            projection = None
        if projection is not None and sorted(candidates) != sorted(projection):
            # Compared as a MULTISET, not a set. Set equality cannot see a
            # duplicate collapsing two claimants into one ({dup} == {dup}),
            # which is the fail-open directly below this invariant.
            missing = sorted(set(projection) - set(candidates))
            invented = sorted(set(candidates) - set(projection))
            fail("INV-13",
                 "region %s: candidate_claims[] must EQUAL the region-restricted "
                 "projection of the claim input as a MULTISET; omitted=%s "
                 "invented=%s recorded=%s projection=%s"
                 % (region_id, missing, invented, sorted(candidates),
                    sorted(projection)))

        # INV-12 -- proven_overlap_pairs[] EQUALS the qualifying set computed
        # over candidate_claims[]. Recomputed from the CLAIM INPUT's claims so
        # that a record cannot satisfy it by also editing its own claim data.
        claims_by_ref = {}
        for index, claim in enumerate(claim_input.get("claims") or []):
            if isinstance(claim, dict):
                claims_by_ref[_claim_ref(claim, index)] = claim
        known = [ref for ref in candidates if ref in claims_by_ref]
        expected_pairs = {_pair_key(p)
                          for p in compute_qualifying_pairs(claims_by_ref, known)}
        recorded_pairs = set()
        for pair in pairs:
            if not isinstance(pair, dict) or "claimant_a" not in pair:
                fail("INV-12", "region %s: malformed pair %r" % (region_id, pair))
                continue
            recorded_pairs.add(_pair_key(pair))
        if recorded_pairs != expected_pairs:
            fail("INV-12",
                 "region %s: proven_overlap_pairs[] must EQUAL the qualifying "
                 "set over candidate_claims[]; omitted=%s invented=%s"
                 % (region_id, sorted(expected_pairs - recorded_pairs),
                    sorted(recorded_pairs - expected_pairs)))

        # participating_claims[] is computed from candidate_claims[] and the
        # qualifying conditions, NOT from the recorded array.
        expected_participating = {ref for pair in expected_pairs for ref in pair}
        if set(participating) != expected_participating:
            fail("INV-12",
                 "region %s: participating_claims[] must be computed from "
                 "candidate_claims[]; expected=%s recorded=%s"
                 % (region_id, sorted(expected_participating),
                    sorted(participating)))

        # INV-01
        if overlap in ("boundaries_undeterminable", "classification_undeterminable"):
            fail("INV-01", "region %s: overlap_classification == %r"
                 % (region_id, overlap))
        if overlap is not None and overlap not in OVERLAP_CLASSIFICATION_ENUM:
            fail("INV-01", "region %s: overlap_classification %r outside the "
                           "declared enumeration" % (region_id, overlap))

        # INV-03
        if overlap == "conflict" and verdict != V_CONFLICT:
            fail("INV-03", "region %s: overlap conflict with verdict %r"
                 % (region_id, verdict))

        if verdict == V_CONFLICT:
            # INV-02
            if overlap != "conflict":
                fail("INV-02", "region %s: conflict verdict with overlap %r"
                     % (region_id, overlap))
            if not pairs:
                fail("INV-02", "region %s: conflict with empty "
                               "proven_overlap_pairs[]" % region_id)
            if not result.get("escalation_record"):
                fail("INV-02", "region %s: conflict with no escalation record"
                     % region_id)
            images = set()
            for pair in pairs:
                for ref in (pair.get("claimant_a"), pair.get("claimant_b")):
                    claim = claims_by_ref.get(ref)
                    if claim is None or not _claim_resolved(claim):
                        fail("INV-02", "region %s: pair member %r is not "
                                       "resolved" % (region_id, ref))
                    else:
                        images.add(_claim_image(claim))
            if len(images) > 1:
                fail("INV-02", "region %s: recorded pairs span bound images %s"
                     % (region_id, sorted(images)))
            covered = {c.get("claim_ref") for c in (result.get("claimants") or [])}
            version_covered = {v.get("claim_ref")
                               for v in (result.get("versions") or [])}
            if not expected_participating <= covered:
                fail("INV-02", "region %s: claimants[] misses %s"
                     % (region_id, sorted(expected_participating - covered)))
            if not expected_participating <= version_covered:
                fail("INV-02", "region %s: versions[] misses %s"
                     % (region_id, sorted(expected_participating - version_covered)))

            # INV-04 -- decided on the TASK, which is the party. There is
            # deliberately no claimant_id cardinality check: requiring two
            # distinct handles would reject a genuine two-task conflict raised
            # by one agent, which is the fail-open this invariant exists to
            # prevent rather than to cause.
            task_ids = {claims_by_ref[r].get("task_id")
                        for r in expected_participating if r in claims_by_ref}
            if len(task_ids) < 2 or None in task_ids or "" in task_ids:
                fail("INV-04", "region %s: participating ids do not resolve to "
                               "two distinct tasks: %s" % (region_id, sorted(
                                   str(t) for t in task_ids)))

            # INV-05
            for ref in expected_participating:
                claim = claims_by_ref.get(ref)
                if claim is not None and _claim_image(claim) not in images:
                    fail("INV-05", "region %s: participating claim %r resolved "
                                   "against a different bound image"
                         % (region_id, ref))

            # INV-11 -- a conflict may outrank an evidence gap but may never
            # ERASE it. Do NOT enforce the converse.
            if evidence_status != "admissible":
                caveats = result.get("evidence_caveats") or []
                if not caveats:
                    fail("INV-11", "region %s: conflict with evidence_status %r "
                                   "and no caveat" % (region_id, evidence_status))
                for caveat in caveats:
                    if not caveat.get("sub_reason"):
                        fail("INV-11", "region %s: caveat without sub_reason"
                             % region_id)
                    if (caveat.get("kind") == "boundary"
                            and not caveat.get("affected_claim_refs")):
                        fail("INV-11", "region %s: boundary caveat names no "
                                       "affected claims" % region_id)
                    if (caveat.get("kind") == "census"
                            and not caveat.get("affected_claim_refs")
                            and not (caveat.get("unresolved_scope")
                                     and caveat.get("evidence_locator"))):
                        fail("INV-11", "region %s: census caveat with neither "
                                       "affected claims nor a located scope"
                             % region_id)

            _validate_escalation_record(result, claims_by_ref, fail)

        # INV-06
        if evidence_status != "admissible" and not pairs:
            if overlap != "not_computed":
                fail("INV-06", "region %s: evidence_status %r with overlap %r"
                     % (region_id, evidence_status, overlap))
            if verdict not in (V_BOUNDARIES, V_CENSUS):
                fail("INV-06", "region %s: evidence_status %r with verdict %r"
                     % (region_id, evidence_status, verdict))

        # INV-07
        if evidence_status == "admissible":
            eligible = _eligible_for_comparison(claims_by_ref, known)
            if len(eligible) < 2:
                if overlap != "not_applicable":
                    fail("INV-07", "region %s: fewer than two eligible claims "
                                   "but overlap %r" % (region_id, overlap))
                if verdict == V_CONFLICT:
                    fail("INV-07", "region %s: fewer than two eligible claims "
                                   "but a conflict verdict" % region_id)

        # INV-08
        if verdict == V_UNACCOUNTED:
            if (result.get("claimant_census") or {}).get("complete") is not True:
                fail("INV-08", "region %s: unaccounted_bytes without a complete "
                               "census" % region_id)

        # INV-09
        if result.get("refusal"):
            if result.get("reason_class") not in REASON_CLASS_ENUM:
                fail("INV-09", "region %s: reason_class %r"
                     % (region_id, result.get("reason_class")))
            if not result.get("reason_code"):
                fail("INV-09", "region %s: no reason_code" % region_id)
            locator = result.get("locator")
            if (not isinstance(locator, dict)
                    or locator.get("kind") not in LOCATOR_KIND_ENUM
                    or locator.get("value") is None):
                fail("INV-09", "region %s: locator %r is not exactly one "
                               "populated locator" % (region_id, locator))
            if result.get("reason_class") == "ownership" and not candidates \
                    and verdict != V_UNACCOUNTED:
                fail("INV-09", "region %s: ownership refusal with no region "
                               "content" % region_id)

        # INV-10 -- iff, BOTH directions, on the two TOP-LEVEL reason fields.
        has_boundary_reason = "boundary_undeterminable_reason" in result and \
            result.get("boundary_undeterminable_reason") is not None
        has_census_reason = "census_undeterminable_reason" in result and \
            result.get("census_undeterminable_reason") is not None
        if (verdict == V_BOUNDARIES) != has_boundary_reason:
            fail("INV-10", "region %s: boundary_undeterminable_reason present=%s "
                           "but verdict=%r" % (region_id, has_boundary_reason,
                                               verdict))
        if (verdict == V_CENSUS) != has_census_reason:
            fail("INV-10", "region %s: census_undeterminable_reason present=%s "
                           "but verdict=%r" % (region_id, has_census_reason,
                                               verdict))
        if has_boundary_reason and has_census_reason:
            fail("INV-10", "region %s: both top-level reason fields populated"
                 % region_id)
        if has_boundary_reason and result["boundary_undeterminable_reason"] \
                not in BOUNDARY_UNDETERMINABLE_REASON_ENUM:
            fail("INV-10", "region %s: boundary reason %r outside enumeration (A)"
                 % (region_id, result["boundary_undeterminable_reason"]))
        if has_census_reason and result["census_undeterminable_reason"] \
                not in CENSUS_UNDETERMINABLE_REASON_ENUM:
            fail("INV-10", "region %s: census reason %r outside enumeration (B)"
                 % (region_id, result["census_undeterminable_reason"]))

    return violations


def _validate_escalation_record(result, claims_by_ref, fail):
    """E5's three constraints, enforced from the record's OWN bytes so that a
    swapped, duplicated, truncated, apply-ready or constant-id preview fails."""
    escalation = result.get("escalation_record") or {}
    previews = escalation.get("if_chosen") or result.get("if_chosen") or []
    versions = {v.get("claim_ref"): v
                for v in (escalation.get("versions")
                          or result.get("versions") or [])}
    participating = set(result.get("participating_claims") or [])

    # E5: EXACTLY ONE preview per participating claimant.
    seen = [p.get("claim_ref") for p in previews]
    if sorted(x for x in seen if x is not None) != sorted(participating):
        fail("INV-02", "if_chosen[] must carry exactly one preview per "
                       "participating claimant: got %s expected %s"
             % (sorted(str(s) for s in seen), sorted(participating)))

    contested = escalation.get("contested_region") or {}
    if not contested.get("anchor") or contested.get("anchor_kind") != "content":
        fail("INV-02", "contested_region must be identified BY CONTENT")

    derived_id = _derive_conflict_record_id(
        escalation.get("path"),
        contested.get("bound_image_id"),
        contested,
        [c.get("claimant_id") for c in (escalation.get("claimants") or [])],
        [v.get("version_id") for v in (escalation.get("versions") or [])])
    if escalation.get("conflict_record_id") != derived_id:
        fail("INV-02", "conflict_record_id is not DERIVED from path + bound "
                       "image + contested region + participating claimant ids "
                       "+ version ids (a reused constant is a failure)")

    for preview in previews:
        ref = preview.get("claim_ref")
        version = versions.get(ref)
        inline = preview.get("inline_outcome") or {}
        if version is None:
            fail("INV-02", "preview for %r has no matching version" % (ref,))
            continue
        # E5(ii): the reconstruction proves the COMPLETE differing union is
        # inline. A truncated differing range, a duplicated preview, or a
        # preview swapped between claimant ids all fail here.
        reconstructed = ("%s%s%s" % (inline.get("identical_prefix", ""),
                                     inline.get("differing_bytes", ""),
                                     inline.get("identical_suffix", "")))
        if reconstructed != version.get("bytes", ""):
            fail("INV-02", "preview for %r does not reconstruct that "
                           "claimant's preserved version: decision-relevant "
                           "content is missing, duplicated or swapped" % (ref,))
        # E5(i): the digest must not be something a staging or apply interface
        # would accept as a complete post-image.
        digest = preview.get("preview_digest") or ""
        if not digest.startswith("preview-sha256:"):
            fail("INV-02", "preview_digest %r is not domain-separated; it could "
                           "be read as an apply-ready object id" % (digest,))
        else:
            outcome_text = ("%s%s%s" % (inline.get("context_before", ""),
                                        version.get("bytes", ""),
                                        inline.get("context_after", "")))
            expected = _derive_preview_digest(
                escalation.get("conflict_record_id"), ref, outcome_text)
            if digest != expected:
                fail("INV-02", "preview_digest for %r does not authenticate "
                               "that claimant's own preview" % (ref,))
        if preview.get("authority") != "preview_only":
            fail("INV-02", "preview for %r is not marked non-authoritative"
                 % (ref,))

    for flag, value in (escalation.get("side_effects") or {}).items():
        if value:
            fail("INV-02", "escalation record reports a %s side effect" % flag)


def persist_escalation_record(git_root, record):
    """E6: keep every referenced object REACHABLE through a neutral namespaced
    pending-conflict ref so the decision survives indefinitely.

    NEVER called implicitly. The caller must pass --escalation-store naming the
    repository, because writing objects or refs into a shared, concurrently
    edited worktree is not this route's to do.
    """
    stored = []
    for result in record.get("region_results") or []:
        escalation = result.get("escalation_record")
        if not escalation:
            continue
        entries = []
        for version in escalation.get("versions") or []:
            payload = (version.get("bytes") or "").encode("utf-8")
            rc, out, err = _git(git_root,
                                ["hash-object", "-t", "blob", "-w", "--stdin"],
                                input_bytes=payload)
            if rc != 0:
                return None, "could not store version blob: %s" % err.strip()
            entries.append(("100644", out.strip().decode("ascii"),
                            "version-%s.txt" % version.get("claim_ref")))
        body = json.dumps(escalation, sort_keys=True,
                          ensure_ascii=False).encode("utf-8")
        rc, out, err = _git(git_root,
                            ["hash-object", "-t", "blob", "-w", "--stdin"],
                            input_bytes=body)
        if rc != 0:
            return None, "could not store the record blob: %s" % err.strip()
        entries.append(("100644", out.strip().decode("ascii"), "record.json"))
        tree_input = b"".join(
            ("%s blob %s\t%s\n" % entry).encode("utf-8") for entry in entries)
        rc, out, err = _git(git_root, ["mktree"], input_bytes=tree_input)
        if rc != 0:
            return None, "could not build the pending tree: %s" % err.strip()
        tree_oid = out.strip().decode("ascii")
        ref = escalation["pending_conflict_ref"]
        # CREATE-ONLY. An unconditional ref write would silently destroy an
        # EARLIER pending record that no human had adjudicated yet -- a silent
        # discard of a claimant's escalation, which is precisely what §5.3
        # boundary (a) forbids, reached from the durability side instead of
        # the classification side. The empty old-value argument makes git
        # refuse when the ref already exists.
        rc_existing, existing, _ = _git(git_root, ["rev-parse", "--verify",
                                                   "--quiet", ref])
        if rc_existing == 0:
            existing_oid = existing.strip().decode("ascii", "replace")
            if existing_oid == tree_oid:
                # Byte-identical re-persist of the same record: idempotent.
                stored.append({"ref": ref, "tree": tree_oid,
                               "objects": [e[1] for e in entries],
                               "already_present": True})
                continue
            return None, (
                "%s already names a DIFFERENT pending record (%s); refusing to "
                "overwrite an un-adjudicated escalation" % (ref, existing_oid))
        rc, _out, err = _git(git_root, ["update-ref", ref, tree_oid, ""])
        if rc != 0:
            return None, "could not write %s: %s" % (ref, err.strip())
        stored.append({"ref": ref, "tree": tree_oid,
                       "objects": [e[1] for e in entries],
                       "already_present": False})
    return stored, None


def _classify_main(ns):
    """The classification route. READ-ONLY with respect to the index and the
    working tree: it consumes the supplied claim input and never reads, patches,
    stages or lands any byte of the target file, which is why it needs no
    check-in conversion screening -- there are no candidate bytes to screen.
    """
    path_arg = ns.classify
    if os.path.isabs(ns.file) or ".." in ns.file.split(os.sep):
        record = _refusal_envelope(
            "invalid_input", "INVALID_PATH_ARGUMENT", "argument", "--file",
            "file must be a repo-relative path inside the git root: %r" % ns.file)
        sys.stdout.write(json.dumps(record, sort_keys=True) + "\n")
        return EXCLUDE
    if not os.path.isfile(path_arg):
        record = _refusal_envelope(
            "invalid_input", "CLAIM_INPUT_MISSING", "path", path_arg,
            "the claim input file does not exist: %s" % path_arg, path=ns.file)
        sys.stdout.write(json.dumps(record, sort_keys=True) + "\n")
        return EXCLUDE
    try:
        with open(path_arg, "r", encoding="utf-8") as handle:
            claim_input = json.load(handle)
    except (ValueError, OSError) as exc:
        record = _refusal_envelope(
            "operational_error", "CLAIM_INPUT_UNREADABLE", "path", path_arg,
            "the claim input could not be read: %s" % exc, path=ns.file)
        sys.stdout.write(json.dumps(record, sort_keys=True) + "\n")
        return EXCLUDE

    for option, code in (("ledger", "LEDGER_MISSING"),
                         ("snapshot", "SNAPSHOT_MISSING"),
                         ("provenance_plan", "PLAN_UNREADABLE")):
        value = getattr(ns, option, None)
        if value and not os.path.isfile(value):
            record = _refusal_envelope(
                "invalid_input" if code != "PLAN_UNREADABLE"
                else "operational_error",
                code, "path", value,
                "%s is missing or unreadable: %s" % (option, value),
                path=ns.file)
            sys.stdout.write(json.dumps(record, sort_keys=True) + "\n")
            return EXCLUDE

    claim_input.setdefault("path", ns.file)
    try:
        record = classify_claim_input(claim_input)
    except ClaimInputError as exc:
        record = _refusal_envelope(
            "invalid_input", "CLAIM_INPUT_MALFORMED", "argument", "--classify",
            "the claim input is malformed: %s" % exc, path=ns.file)
        sys.stdout.write(json.dumps(record, sort_keys=True) + "\n")
        return EXCLUDE

    violations = validate_classification_record(record, claim_input)
    record["invariant_violations"] = violations
    if violations:
        record["refusal"] = True
        record["reason_class"] = "operational_error"
        record["reason_code"] = "INVARIANT_VIOLATION"
        record["locator"] = {"kind": "path", "value": ns.file}
        record["message"] = ("the emitted classification record violates %s"
                             % ", ".join(sorted({v["invariant"]
                                                 for v in violations})))

    if ns.escalation_store and not violations:
        stored, error = persist_escalation_record(ns.escalation_store, record)
        record["escalation_persistence"] = (
            {"stored": stored} if error is None else {"error": error})

    sys.stdout.write(json.dumps(record, sort_keys=True) + "\n")
    return EXCLUDE if record.get("refusal") else OK


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--git-root", required=True)
    ap.add_argument("--file", required=True, help="repo-relative path")
    ap.add_argument("--ledger")
    ap.add_argument("--snapshot")
    ap.add_argument("--checkpoint-provenance")
    ap.add_argument("--provenance-plan")
    ap.add_argument("--untracked-modified-report")
    ap.add_argument("--report-sha256")
    ap.add_argument("--task-id")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument(
        "--classify",
        help=(
            "Ownership CLASSIFICATION route (spec-20260914-052140 §5.3 (a)/(c)). "
            "Takes a claim-input JSON file and emits one structured "
            "classification record on stdout. Read-only: it never reads, "
            "patches, stages or lands any byte of the target file, and it never "
            "resolves, merges or selects a side of a true ownership conflict."
        ),
    )
    ap.add_argument(
        "--escalation-store",
        help=(
            "Repository in which to persist a pending-conflict escalation record "
            "under refs/pending-conflicts/. OPT-IN and never implicit: writing "
            "objects or refs into a shared, concurrently edited worktree is not "
            "this route's to do."
        ),
    )
    ap.add_argument("--dry-run", action="store_true", help="Ledger path only: emit INCLUDE/EXCLUDE diagnostic without modifying the git index or working tree.")
    ap.add_argument("--approved-sha256")
    ap.add_argument(
        "--effective-report-verified",
        action="store_true",
        help=(
            "R4 late-repair only: authorizes --untracked-modified-report to accept "
            "the dev-report-<task-id>.effective.json basename. Only "
            "late-repair-controller.py finalize sets this, and only after its own "
            "independent corroboration has already succeeded."
        ),
    )
    try:
        ns = ap.parse_args(argv)
    except SystemExit as exc:
        # --help / -h exits 0; a genuine usage error exits non-zero.
        return 0 if exc.code in (0, None) else HARD

    git_root = ns.git_root
    rel = ns.file

    # The classification route is dispatched FIRST and deliberately ahead of
    # the worktree-existence checks: an invalid path argument, a missing
    # ledger, a missing snapshot and an unreadable plan must each surface as a
    # STRUCTURED refusal envelope with its own reason_class and locator, not as
    # a bare stderr line. It is not a bypass of the check-in conversion screen:
    # the route reads no candidate bytes from the working tree and mutates
    # neither the index nor the tree, so there is nothing for that screen to
    # decide about.
    if ns.classify:
        return _classify_main(ns)

    root = os.path.realpath(git_root)
    abspath = os.path.realpath(os.path.join(root, rel))
    if os.path.isabs(rel) or os.path.commonpath((root, abspath)) != root:
        return _excluded("file must be a repo-relative path inside git root")

    # --- Load inputs -------------------------------------------------------
    if not os.path.isdir(git_root):
        return _excluded("git root not a directory: %s" % git_root)

    if not os.path.isfile(abspath):
        return _excluded("worktree file missing: %s" % rel)

    provenance_inputs = sum(bool(value) for value in (
        ns.checkpoint_provenance,
        ns.provenance_plan,
        ns.untracked_modified_report,
    ))
    if provenance_inputs > 1:
        return _excluded(
            "choose checkpoint, composed, or untracked-modified provenance; not multiple"
        )
    # Argument misuse is diagnosed BEFORE any content is screened: a malformed
    # invocation has no candidate bytes worth probing. The predicate carries
    # `and not ns.untracked_modified_report` because it used to sit AFTER that
    # route's dispatch and was bare only for that reason -- the untracked route
    # REQUIRES --report-sha256, so a bare relocation would refuse every
    # legitimate invocation of it. The message is byte-identical to the
    # pre-relocation one: this introduces no new refusal, and its cause is an
    # illegal argument combination rather than a transform, encoding or mode
    # divergence.
    if ns.report_sha256 and not ns.untracked_modified_report:
        return _excluded("--report-sha256 is only valid with --untracked-modified-report")

    # --- THE screening stage: one helper, ONE call site, ahead of every route
    # dispatch below. Moving any dispatch above this line is the bypass the
    # structural check in tests/test_stage_owned_hunks_boundary.py detects.
    screened = _screen_entry_stage(git_root, rel, abspath)
    if screened is not None:
        return screened

    if ns.untracked_modified_report:
        return _untracked_modified_main(ns)
    if ns.checkpoint_provenance:
        if not ns.task_id:
            return _excluded("--task-id is required with checkpoint provenance")
        return _checkpoint_main(ns)
    if ns.provenance_plan:
        if not ns.task_id:
            return _excluded("--task-id is required with a provenance plan")
        plan, error = _load_provenance_plan(ns)
        if plan is None:
            return _excluded(error)
        return _composed_main(ns, plan)
    if not ns.ledger or not ns.snapshot:
        return _excluded("ledger and snapshot are required for live provenance")

    # Missing-signal: ledger absent or unreadable -> EXCLUDE
    if not os.path.isfile(ns.ledger):
        return _excluded("owned-edits ledger missing for %s" % rel)
    try:
        with open(ns.ledger, "r", encoding="utf-8") as fh:
            edits = json.load(fh)
    except (ValueError, OSError) as exc:
        return _excluded("owned-edits ledger unreadable: %s" % exc)

    if not isinstance(edits, list) or not edits:
        return _excluded("owned-edits ledger empty/invalid for %s" % rel)

    if not os.path.isfile(ns.snapshot):
        return _excluded("pre-edit snapshot missing for %s" % rel)
    snapshot = _read_bytes(ns.snapshot)

    worktree = _read_bytes(abspath)

    # --- Reject non-hunk-splittable files ----------------------------------
    # Not the screening stage's concern: this asks whether these two buffers
    # can be reconstructed byte-for-byte, not whether conversion alters one
    # image. The pre-edit snapshot is not a candidate the stage ever probes.
    if _is_binary(worktree) or _is_binary(snapshot):
        return _excluded("binary file (not safely hunk-splittable): %s" % rel)

    # CRLF / encoding mismatch: if line-ending style differs between snapshot and
    # worktree, byte-level reconstruction is unsafe -> EXCLUDE.
    if (b"\r\n" in snapshot) != (b"\r\n" in worktree):
        return _excluded("CRLF/encoding mismatch between snapshot and worktree: %s" % rel)

    # Mode change: a staged-vs-worktree mode delta is not hunk-splittable.
    rc_mode, mode_out, _ = _git(git_root, ["diff", "--summary", "--", rel])
    if rc_mode == 0 and b"mode change" in mode_out:
        return _excluded("mode change present (not hunk-splittable): %s" % rel)

    # The content-transform precondition that used to sit here decided from a
    # POSITIVELY parsed attribute VALUE. Evaluated verbatim it refused on a set
    # answer, on an UNSET answer and on an explicit value, proceeding only on
    # "unspecified" -- so it false-REFUSED the conversion-DISABLING answer while
    # false-PROCEEDING whenever the query itself failed. It is gone. The
    # screening stage in main() now covers every route, decides from what
    # conversion does to the bytes rather than from what the configuration says,
    # and carries no attribute name in its verdict.

    # New (untracked) file: `git apply --cached` cannot patch a path absent from
    # the index. A brand-new file is whole-file owned by definition, but staging it
    # here as a hunk patch is malformed (git rejects "does not exist in index").
    # Fail-closed EXCLUDE so the caller's whole-file path (for genuinely owned new
    # files) handles it — the helper never emits a malformed new-file patch.
    rc_tracked, _, _ = _git(git_root, ["ls-files", "--error-unmatch", "--", rel])
    if rc_tracked != 0:
        return _excluded(
            "target file is not tracked in the index (new file — not hunk-stageable "
            "via git apply --cached) -> EXCLUDE: %s" % rel
        )

    # Clean-index gate: if the target already has STAGED content in the index,
    # applying the owned-only patch on top would leave that pre-staged (possibly
    # peer) content in the index alongside the owned hunk -> fail-open. Require the
    # file to be unstaged; otherwise EXCLUDE. (Phase 4 pre-staged-verify normally
    # clears this, but we do not trust the caller's index state.)
    rc_idx, _, _ = _git(git_root, ["diff", "--cached", "--quiet", "--", rel])
    # `--quiet` exits 1 when there ARE staged changes, 0 when clean.
    if rc_idx == 1:
        # Fail-closed MUST leave the file contributing NOTHING to the commit: the
        # pre-staged (possibly peer) bytes are unstaged here, so `git diff --cached
        # -- <rel>` is empty after EXCLUDE (AC3/AC7). Worktree content is untouched.
        if not ns.dry_run:
            _git(git_root, ["restore", "--staged", "--", rel])
        return _excluded(
            "target file already had staged content in the index; unstaged it and "
            "EXCLUDE (will not commit unattributed staged bytes): %s" % rel
        )

    # --- Owned-only image on the commit baseline (§5.3) --------------------
    # Ownership is the AUTHORED TRANSFORMATION, not endpoint content. The
    # ledger is replayed forward from the pre-edit snapshot, binding each edit
    # to a UNIQUE occurrence of its `old` in the buffer as it has evolved. That
    # replay is the ownership WITNESS; it is not the artifact to land.
    #
    # Why forward replay and not an endpoint reconstruction: a plain "revert
    # owned ranges to old_string and compare to the snapshot" check is
    # permutation-insensitive when old_strings are duplicated (ledger slot->A,
    # slot->B against a swapped B\nA\n reverts to slot\nslot\n == snapshot,
    # fail-open). Unique binding closes that, and the overlap-inclusive
    # counting above means a self-overlapping anchor can no longer be certified
    # as uniquely located.
    #
    # What gets landed is an owned-only IMAGE assembled once on the clean
    # stage-0 index blob. Every byte the claimant did not author comes from
    # that baseline, so another claimant's uncommitted bytes -- which the
    # pre-edit snapshot may itself already carry -- can never ride along.
    # Differences wholly outside the claimant's own footprint are ignored.
    # Ledger validity first: a malformed entry, an empty old_string, or an
    # anchor that is absent or matches at more than one candidate start offset
    # is a property of the ledger alone, diagnosed before anything is read from
    # the index.
    try:
        replayed = _replay_with_provenance(snapshot, edits, rel)
    except EmptyOwnedOldStringError as exc:
        return _excluded(
            "a ledger entry has an empty old_string for %s: %s" % (rel, exc))
    except AlignmentBudgetExceeded as exc:
        return _excluded(
            "the owned-region correspondence for %s exceeds this route's "
            "computation budget: %s" % (rel, exc))
    except OwnedLandingRefusal as exc:
        return _excluded(_refusal_text(git_root, rel, snapshot, exc))

    index_mode = _tracked_mode(git_root, rel)      # REQUIRED source: the path's
    index_oid = _index_stage0_oid(git_root, rel)   # STAGE-0 INDEX entry
    if index_mode is None or index_oid is None:
        return _excluded("no readable stage-0 index entry for %s" % rel)
    rc_base, index_blob, err_base = _git(git_root, ["cat-file", "blob", index_oid])
    if rc_base != 0:
        return _excluded("commit baseline blob unreadable for %s: %s"
                         % (rel, err_base.strip()))

    try:
        mapped_slices = []
        image, _replay, owned_slices = _owned_only_image(
            snapshot, index_blob, worktree, edits, rel, replayed=replayed,
            mapped_out=mapped_slices)
    except AlignmentBudgetExceeded as exc:
        return _excluded(
            "the owned-region correspondence for %s exceeds this route's "
            "computation budget: %s" % (rel, exc))
    except OwnedLandingRefusal as exc:
        return _excluded(_refusal_text(git_root, rel, snapshot, exc))

    # Stage 2 -- the ASSEMBLED CANDIDATE IMAGE, probed before any index or
    # object-database mutation. Probing the snapshot or the baseline blob is
    # not a substitute and is never a second verdict source: two buffers can
    # each be individually invariant under check-in conversion while their
    # concatenation is not (measured: a base side ending in a bare CR followed
    # by a side beginning with LF). Only the assembly the index is meant to
    # hold answers the question. The in-memory buffer is never a file, which is
    # why the probe declares the path on stdin rather than reading from disk.
    reason = _screen_checkin_transform(
        git_root, rel, image, "assembled owned-only image")
    if reason is not None:
        return _excluded(reason)

    if ns.dry_run:
        # Non-mutating diagnostic. The image identity is emitted so callers have
        # an oracle that does not require mutating the repository; the object id
        # is COMPUTED without writing, so it stays absent from the object
        # database. Nothing below this branch runs.
        rc_oid, oid_out, err_oid = _git(
            git_root, ["hash-object", "-t", "blob", "--stdin"], input_bytes=image)
        if rc_oid != 0:
            return _excluded("could not compute the owned-only image object id "
                             "for %s: %s" % (rel, err_oid.strip()))
        diag = {"decision": "INCLUDE", "dry_run": True,
                "hunk_count": len(owned_slices),
                "image_blob_oid": oid_out.strip().decode("ascii", "replace"),
                "image_file_mode": index_mode,
                "image_sha256": hashlib.sha256(image).hexdigest(),
                "image_size": len(image),
                "mode": "ledger+snapshot", "path": rel}
        sys.stdout.write(json.dumps(diag, sort_keys=True) + "\n")
        return OK

    if image == index_blob:
        # Empty owned delta, reached only AFTER the footprint check above: no
        # object write and no index write. NOT a whole-file fallback.
        sys.stderr.write("NO-OP: empty owned delta for %s (nothing to stage)\n" % rel)
        return OK

    # SEAM 1 -- the two mandatory soundness checks, run on the ASSEMBLED
    # candidate image and strictly before the first object or index write.
    # A demonstrated failure refuses with the hunk combination that caused
    # it; a non-assertion is reported and left to the landing owner.
    refusal = _soundness_gate().screen_landing(
        rel, image, index_mode, slices=_owned_gate_slices(
            owned_slices, mapped_slices, ns.task_id),
        baseline=index_blob, git_root=git_root, claimant_id=ns.task_id)
    if refusal is not None:
        return _excluded(refusal)

    return _land_owned_image(git_root, rel, image, index_mode, index_oid)


def _soundness_gate():
    """Load the soundness gate, which lives in its own module.

    This file's bytes are digest-pinned by a live consumer assertion, so the
    gate is NOT inlined here: the call-site delta is the minimum that can
    invoke it.
    """
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib",
                        "soundness_gate.py")
    try:
        spec = importlib.util.spec_from_file_location("soundness_gate", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as exc:
        # A gate that cannot be loaded must not take a landing down with it:
        # it asserts nothing, says so, and authorizes nothing either.
        sys.stderr.write("soundness-gate: not asserted -- the gate module "
                         "could not be loaded (%s)\n" % type(exc).__name__)
        return _UnloadableGate()


class _UnloadableGate(object):
    @staticmethod
    def screen_landing(*_args, **_kwargs):
        return None


def _owned_gate_slices(net, mapped, claimant_id):
    """One gate hunk per recorded owned edit, in baseline order.

    `net[i]` and `mapped[i]` describe the same recorded edit -- the first in
    snapshot coordinates, the second on the commit baseline -- so the pair
    yields a selectable atomic hunk. Attribution stays at HUNK granularity
    rather than collapsing to the file.
    """
    slices = []
    for number, (entry, span) in enumerate(zip(net, mapped)):
        slices.append(("h%03d" % number, claimant_id, span[0], span[1],
                       entry[2]))
    return slices


def _rewrite_patch_paths(patch, rel):
    """Rewrite the a/<tmp> and b/<tmp> path tokens in a unified diff to a/<rel>
    and b/<rel> so the patch targets the real tracked file."""
    lines = patch.split(b"\n")
    out = []
    rel_b = rel.encode("utf-8")
    for line in lines:
        if line.startswith(b"diff --git "):
            out.append(b"diff --git a/" + rel_b + b" b/" + rel_b)
        elif line.startswith(b"--- "):
            out.append(b"--- a/" + rel_b)
        elif line.startswith(b"+++ "):
            out.append(b"+++ b/" + rel_b)
        else:
            out.append(line)
    return b"\n".join(out)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
