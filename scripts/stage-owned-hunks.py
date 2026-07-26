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
the cross-check) -> EXCLUDE. There is no fail-open path.
"""

import argparse
import hashlib
import json
import os
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
        off = _locate_unique(replay, old_b)
        if off is None:
            return None, (
                "owned old_string for edit %d not uniquely locatable during replay "
                "(absent or duplicated at this step) -> ambiguous: %s" % (i, rel)
            )
        replay = replay[:off] + new_b + replay[off + len(old_b):]
    return replay, ""


def _live_patch(snapshot, replay, rel):
    with tempfile.TemporaryDirectory() as td:
        a_path = os.path.join(td, "a")
        b_path = os.path.join(td, "b")
        with open(a_path, "wb") as fh:
            fh.write(snapshot)
        with open(b_path, "wb") as fh:
            fh.write(replay)
        proc = subprocess.run(
            ["git", "diff", "--no-index", "-U0", "--src-prefix=a/",
             "--dst-prefix=b/", "--", a_path, b_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    if proc.returncode not in (0, 1):
        return None, proc.stderr.decode("utf-8", "replace")
    return _rewrite_patch_paths(proc.stdout, rel), ""


def _tracked_mode(git_root, rel):
    rc, out, _ = _git(git_root, ["ls-files", "-s", "--", rel])
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


def _filter_segments_against_index(git_root, segments):
    """Return segment copies containing only hunks composable in one index."""
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
            for hunk in hunks:
                candidate = header + hunk
                rc, _, _ = _git(
                    git_root,
                    ["apply", "--cached", "--recount", "--unidiff-zero", "-"],
                    input_bytes=candidate, env=env,
                )
                if not rc:
                    accepted.append(hunk)
            item = dict(segment)
            item["patch_header"] = header
            item["patch_hunks"] = accepted
            item["patch"] = header + b"".join(accepted) if accepted else b""
            item["original_hunk_count"] = segment.get("original_hunk_count", len(hunks))
            result.append(item)
        return result, ""
    finally:
        shutil.rmtree(td)


def _filter_segments_against_worktree(worktree, rel, mode, segments):
    """Reverse composable hunks newest-first, omitting real current overlap."""
    candidate = worktree
    accepted_by_segment = [[] for _ in segments]
    for segment_index in range(len(segments) - 1, -1, -1):
        segment = segments[segment_index]
        header = segment["patch_header"]
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
        accepted_by_segment[segment_index].reverse()
    result = []
    for segment, hunks in zip(segments, accepted_by_segment):
        item = dict(segment)
        item["patch_hunks"] = hunks
        item["patch"] = item["patch_header"] + b"".join(hunks) if hunks else b""
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
        indexed, error = _filter_segments_against_index(ns.git_root, candidates)
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
            rc, _, err = _git(
                ns.git_root,
                ["apply", "--cached", "--recount", "--unidiff-zero", "-"],
                input_bytes=segment["patch"], env=env,
            )
            if rc:
                if not ns.plan_only:
                    _git(ns.git_root, ["restore", "--staged", "--", rel])
                return _excluded(
                    "provenance segment %d does not apply to the composed index: %s"
                    % (number, err.strip())
                )
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
    if os.path.basename(ns.untracked_modified_report) != expected_name:
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
    current = _read_bytes(path)
    if _is_binary(current):
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

        rc, _, error = _git(ns.git_root, ["add", "--", rel])
        if rc:
            return _excluded("cannot stage authenticated untracked-modified file: %s" % error)
        rc, staged, error = _git(
            ns.git_root, ["diff", "--cached", "--binary", "--full-index", "--", rel]
        )
        if rc or staged != selected:
            _git(ns.git_root, ["rm", "--cached", "--force", "--quiet", "--", rel])
            return _excluded("staged untracked-modified patch changed after validation: %s" % error)
        sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
        return OK
    finally:
        shutil.rmtree(directory)


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
    ap.add_argument("--ledger")
    ap.add_argument("--snapshot")
    ap.add_argument("--checkpoint-provenance")
    ap.add_argument("--provenance-plan")
    ap.add_argument("--untracked-modified-report")
    ap.add_argument("--report-sha256")
    ap.add_argument("--task-id")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--approved-sha256")
    try:
        ns = ap.parse_args(argv)
    except SystemExit as exc:
        # --help / -h exits 0; a genuine usage error exits non-zero.
        return 0 if exc.code in (0, None) else HARD

    git_root = ns.git_root
    rel = ns.file

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
    if ns.untracked_modified_report:
        return _untracked_modified_main(ns)
    if ns.report_sha256:
        return _excluded("--report-sha256 is only valid with --untracked-modified-report")
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
