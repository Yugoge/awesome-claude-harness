#!/usr/bin/env python3
"""Line-precise (hunk-filtered) staging primitive — fail-closed.

Stages ONLY this cycle's owned hunks within a single already-authorized file,
leaving any peer (unattributed) hunks unstaged in the working tree. Ownership is
derived from dev's own authored content (the owned-edits ledger), NOT from a
file-state snapshot — so it is immune to peer timing/interleaving. A pre-edit
snapshot is used ONLY for a fail-closed out-of-owned-region cross-check.

Usage:
  stage-owned-hunks.py --git-root <root> --file <repo-rel-path> \
      --ledger <ledger.json> --snapshot <snapshot-file>

  --ledger    JSON file: list of {"old": "...", "new": "..."} owned edits for THIS
              file, in the order dev applied them. Line numbers (if present) are
              ADVISORY only and ignored by ownership logic.
  --snapshot  Path to a file holding the EXACT pre-edit (pre-first-edit) bytes of
              the worktree file (the cross-check trust anchor).

Exit codes:
  0   owned hunks staged (or empty owned diff -> no-op, nothing to stage)
  10  EXCLUDED (fail-closed) — ambiguity, peer entanglement, or apply reject.
      Reason printed to stderr. Caller MUST warn-and-skip (NEVER whole-file stage).
  2   hard/usage error (also treated as EXCLUDE by the caller)

Design invariant (PROCEED iff): the file is staged ONLY when reconstructing the
worktree with every owned range reverted to its recorded `old_string` yields bytes
BYTE-IDENTICAL to the pre-edit snapshot. Any unattributed byte change must occupy
either owned bytes (caught by the byte-match check) or non-owned bytes (caught by
the cross-check) -> EXCLUDE. There is no fail-open path.
"""

import argparse
import json
import os
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


def _git(git_root, args, input_bytes=None):
    """Run a git command; return (returncode, stdout_bytes, stderr_text)."""
    proc = subprocess.run(
        ["git", "-C", git_root] + args,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.returncode, proc.stdout, proc.stderr.decode("utf-8", "replace")


def _is_binary(data):
    # A NUL byte is git's own heuristic for "binary".
    return b"\x00" in data


def _count_occurrences(haystack, needle):
    """Count non-overlapping occurrences of needle in haystack (bytes)."""
    if not needle:
        return -1  # empty needle is never uniquely locatable
    count = 0
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx == -1:
            break
        count += 1
        start = idx + len(needle)
    return count


def _locate_unique(haystack, needle):
    """Return the unique byte offset of needle in haystack, or None if absent
    or non-unique."""
    n = _count_occurrences(haystack, needle)
    if n != 1:
        return None
    return haystack.find(needle)


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--git-root", required=True)
    ap.add_argument("--file", required=True, help="repo-relative path")
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--snapshot", required=True)
    try:
        ns = ap.parse_args(argv)
    except SystemExit as exc:
        # --help / -h exits 0; a genuine usage error exits non-zero.
        return 0 if exc.code in (0, None) else HARD

    git_root = ns.git_root
    rel = ns.file

    # --- Load inputs -------------------------------------------------------
    if not os.path.isdir(git_root):
        return _excluded("git root not a directory: %s" % git_root)

    abspath = os.path.join(git_root, rel)
    if not os.path.isfile(abspath):
        return _excluded("worktree file missing: %s" % rel)

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
        _git(git_root, ["restore", "--staged", "--", rel])
        return _excluded(
            "target file already had staged content in the index; unstaged it and "
            "EXCLUDE (will not commit unattributed staged bytes): %s" % rel
        )

    # --- Forward sequential replay from the snapshot (authoritative) -------
    # Ownership is the AUTHORED TRANSFORMATION, not just endpoint content. We
    # replay the ledger forward from the pre-edit snapshot: for each edit, find a
    # UNIQUE occurrence of `old` in the current replay buffer (at that step) and
    # replace it with `new`. Then require the replayed result to byte-match the
    # worktree.
    #
    # Why forward-replay (not just an endpoint recon): a plain "revert owned ranges
    # to old_string and compare to snapshot" check is permutation-insensitive when
    # old_strings are duplicated (e.g. ledger slot->A, slot->B but the worktree is
    # the peer's swap B\nA\n reverts to slot\nslot\n == snapshot, fail-open). Binding
    # each edit to a unique pre-edit occurrence and requiring the replayed final
    # state == worktree makes the check order-sensitive and closes that hole.
    #
    # A non-unique `old` at any step, an `old` whose match cannot be found, or a
    # final replayed state that differs from the worktree (an unattributed peer edit
    # anywhere — overlapping, non-overlapping, inside-owned, or a swap) => EXCLUDE.
    replay = snapshot
    for i, edit in enumerate(edits):
        if not isinstance(edit, dict) or "old" not in edit or "new" not in edit:
            return _excluded("ledger entry %d malformed (need old+new) for %s" % (i, rel))
        new_b = edit["new"].encode("utf-8") if isinstance(edit["new"], str) else edit["new"]
        old_b = edit["old"].encode("utf-8") if isinstance(edit["old"], str) else edit["old"]

        off = _locate_unique(replay, old_b)
        if off is None:
            return _excluded(
                "owned old_string for edit %d not uniquely locatable during replay "
                "(absent or duplicated at this step) -> ambiguous: %s" % (i, rel)
            )
        replay = replay[:off] + new_b + replay[off + len(old_b):]

    if replay != worktree:
        return _excluded(
            "replayed owned edits do not reproduce the worktree (unattributed peer "
            "edit or ledger inconsistency detected) for %s" % rel
        )

    # --- Build owned-only patch -------------------------------------------
    # We stage exactly: snapshot (a == pre-edit) -> worktree (b). The forward
    # replay above PROVED that applying ONLY dev's authored edits to the snapshot
    # reproduces the worktree byte-for-byte; therefore snapshot..worktree contains
    # ONLY owned hunks (any peer change would have failed the replay). We let
    # `git diff --no-index -U0` compute the minimal zero-context hunks, then
    # `git apply --cached --recount --unidiff-zero`.
    #
    # Diffing snapshot->worktree (rather than the current index state) means a peer
    # hunk baked into the snapshot is on BOTH sides and never appears in the patch
    # (cannot be staged). Empty diff => nothing owned to stage => no-op (NOT a
    # whole-file fallback).
    with tempfile.TemporaryDirectory() as td:
        a_path = os.path.join(td, "a")
        b_path = os.path.join(td, "b")
        with open(a_path, "wb") as fh:
            fh.write(snapshot)
        with open(b_path, "wb") as fh:
            fh.write(worktree)

        # git diff --no-index returns exit 1 when files differ (expected), 0 when
        # identical, >1 on error.
        # NB: `git diff --no-index` accepts `-U0` (zero context) but NOT the
        # `git apply` spelling `--unidiff-zero`. Zero context isolates an owned
        # line even from an immediately-adjacent peer hunk.
        proc = subprocess.run(
            ["git", "diff", "--no-index", "-U0",
             "--src-prefix=a/", "--dst-prefix=b/", "--", a_path, b_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if proc.returncode not in (0, 1):
            return _excluded("git diff failed building owned patch: %s"
                             % proc.stderr.decode("utf-8", "replace"))
        patch = proc.stdout

    if not patch.strip():
        # Empty owned diff: nothing to stage. No-op, NOT a whole-file fallback.
        sys.stderr.write("NO-OP: empty owned diff for %s (nothing to stage)\n" % rel)
        return OK

    # Rewrite the temp-file paths in the patch headers to the real repo-relative
    # path so `git apply --cached` targets the tracked file.
    patch = _rewrite_patch_paths(patch, rel)

    # --- Stage via git apply --cached (never git add, never -A/.) ----------
    rc, out, err = _git(
        git_root,
        ["apply", "--cached", "--recount", "--unidiff-zero", "-"],
        input_bytes=patch,
    )
    if rc != 0:
        # Context drift / reject / overlapping with already-staged content.
        # Do NOT retry whole-file. Roll back any partial staging of this file.
        _git(git_root, ["restore", "--staged", "--", rel])
        return _excluded("git apply --cached rejected owned patch (context drift / "
                         "overlapping) for %s: %s" % (rel, err.strip()))

    return OK


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
