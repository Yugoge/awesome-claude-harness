#!/usr/bin/env python3
"""Resolve a /spec monolith path to its split-artifact id + paths (the canonical
spec-id resolver shared by /spec finalize and every /dev* consumer).

Why this exists (one-time migration note — convention flip ~2026-05-14..05-21):
  /spec writes the monolith FLAT at docs/dev/specs/spec-<ts>.md (WITH a `spec-`
  prefix) but substitutes a DE-PREFIXED <spec-id>=<ts> for the split artifacts
  (docs/dev/specs/<ts>/views/, .claude/specs/<ts>/). Older specs were emitted
  PREFIXED on disk (docs/dev/specs/spec-<ts>/views/). Consumers used to derive the
  spec-id by taking the monolith basename minus .md (which KEEPS the prefix), so
  new de-prefixed specs silently fell back to monolith mode. A naive strip would
  REGRESS the old prefixed specs. This helper is a TOLERANT resolver: it computes
  candidate ids [de_prefixed, raw_stem] and classifies each candidate's on-disk
  artifacts into exactly three states, then decides loudly.

THREE-STATE decision table (per candidate):
  ABSENT            -> no artifact evidence (no views dir / manifest / split marker)
  PRESENT-AND-VALID -> manifest valid JSON, schema_version==1, monolith_path
                       realpath/samefile == THIS monolith (anchored to project),
                       split marker present + fresh, all referenced views present
  PRESENT-BUT-INVALID -> has artifact evidence but fails ANY validity predicate

Decision:
  every candidate ABSENT      -> views_available=false, legacy monolith mode, EXIT 0
  exactly one PRESENT-AND-VALID (others ABSENT) -> artifact_id=that, EXIT 0
  any PRESENT-BUT-INVALID      -> FAIL LOUD (EXIT non-zero) — never silent monolith
  two PRESENT-AND-VALID         -> FAIL LOUD (EXIT non-zero) — ambiguous

Orphan cp-state under .claude/specs/<c>/ is NOT artifact evidence and never drives
ABSENT/VALID classification (protects Part A: a prefixed orphan cp-state must not
block resolution to the de-prefixed valid artifacts).

Usage:
  resolve-spec-artifacts.py --spec-path <monolith.md> --project-dir <root>
Output: machine-readable JSON on stdout.
Exit codes: 0 = resolved (single-valid OR all-absent legacy monolith mode)
            3 = PRESENT-BUT-INVALID (loud-fail guard)
            4 = AMBIGUOUS (two valid manifests for one monolith)
            2 = usage / unreadable spec_path error
"""

import argparse
import hashlib
import json
import os
import sys

# Per-candidate states
ABSENT = "ABSENT"
PRESENT_AND_VALID = "PRESENT_AND_VALID"
PRESENT_BUT_INVALID = "PRESENT_BUT_INVALID"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INVALID = 3
EXIT_AMBIGUOUS = 4


def _err(msg):
    sys.stderr.write("resolve-spec-artifacts: " + msg + "\n")


def _real(path):
    """realpath that does not require the path to exist."""
    return os.path.realpath(path)


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _anchor(path, project_dir):
    """Anchor a possibly-relative path to project_dir, then realpath it."""
    if not os.path.isabs(path):
        path = os.path.join(project_dir, path)
    return _real(path)


def _view_entry_path(val, role):
    """Normalize a manifest.views[role] value into a relative path string.

    Tolerates the historical shapes (codex issue 2 — old schema_version==1
    manifests may store dicts rather than plain path strings):
      "views/architect.md"            -> as-is
      {"file"/"path": "views/x.md"}   -> the inner path
      {"line_count": N} (no path key) -> infer "views/<role>.md"
    Returns None if no usable path can be derived.
    """
    if isinstance(val, str):
        return val or None
    if isinstance(val, dict):
        for key in ("path", "file", "view", "rel"):
            v = val.get(key)
            if isinstance(v, str) and v:
                return v
        # metadata-only dict (e.g. {"line_count": N}) -> infer canonical location
        if role and isinstance(role, str):
            return "views/%s.md" % role
    return None


def classify(candidate, abs_spec, project_dir, project_real):
    """Classify one candidate id into (state, detail-dict)."""
    specs_root = os.path.join(project_dir, "docs", "dev", "specs")
    spec_dir = os.path.join(specs_root, candidate)
    views_dir = os.path.join(spec_dir, "views")
    manifest = os.path.join(views_dir, "manifest.json")
    split_marker = os.path.join(spec_dir, ".split-complete")
    cp_dir = os.path.join(project_dir, ".claude", "specs", candidate)

    detail = {
        "candidate": candidate,
        "views_dir": views_dir,
        "manifest_path": manifest,
        "split_marker": split_marker,
        "cp_dir": cp_dir,
        "reason": None,
    }

    # Evidence detection MUST use lexists/lstat (NOT exists) so a DANGLING SYMLINK
    # at any of these paths counts as evidence -> reaches PRESENT-BUT-INVALID
    # instead of falsely classifying ABSENT and silently degrading to monolith mode.
    has_evidence = (
        os.path.lexists(views_dir)
        or os.path.lexists(manifest)
        or os.path.lexists(split_marker)
    )
    if not has_evidence:
        detail["reason"] = "no artifact evidence (no views dir / manifest / split-complete)"
        return ABSENT, detail

    def invalid(reason):
        detail["reason"] = reason
        return PRESENT_BUT_INVALID, detail

    # manifest must be a regular file. os.path.isfile() returns False for a
    # broken symlink, a directory, or a wrong-type path, so it doubles as the
    # PRESENT-BUT-INVALID guard here (evidence present but not a usable manifest).
    if not os.path.isfile(manifest):
        return invalid("views/manifest.json missing or not a regular file (evidence present)")

    try:
        with open(manifest, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return invalid("views/manifest.json unreadable or malformed JSON: %s" % exc)

    if not isinstance(data, dict):
        return invalid("manifest is not a JSON object")

    if data.get("schema_version") != 1:
        return invalid("schema_version != 1 (got %r)" % data.get("schema_version"))

    mono = data.get("monolith_path")
    if not isinstance(mono, str) or not mono:
        return invalid("manifest.monolith_path missing or not a string")

    mono_abs = _anchor(mono, project_dir)
    # reject escapes outside project root
    if not (mono_abs == project_real or mono_abs.startswith(project_real + os.sep)):
        return invalid("manifest.monolith_path resolves outside project root: %s" % mono_abs)
    if not os.path.exists(mono_abs):
        return invalid("manifest.monolith_path points at a non-existent file: %s" % mono_abs)
    # samefile resolves symlinks + compares inodes (requires both exist — guaranteed above)
    try:
        same = os.path.samefile(mono_abs, abs_spec)
    except OSError as exc:
        return invalid("could not compare monolith_path to spec_path: %s" % exc)
    if not same:
        return invalid(
            "manifest.monolith_path resolves to a DIFFERENT monolith (%s) than this spec (%s)"
            % (mono_abs, abs_spec)
        )

    # split marker must exist as a regular file (broken symlink / dir / missing -> invalid)
    if not os.path.isfile(split_marker):
        return invalid(".split-complete missing or not a regular file while manifest present")

    # Staleness guard. The split is fresh iff the monolith content has not changed
    # since the split was written. We STRENGTHEN (never weaken) the pre-existing
    # mtime guard with a content-hash check:
    #   - If the manifest records the monolith hash (sha256 / monolith_sha256) and it
    #     MATCHES the current monolith content, the split is provably fresh — accept
    #     regardless of mtime. (mtime is bumped by no-op touches / git checkouts /
    #     auto-checkpoint snapshots, which produce false "stale" positives.)
    #   - If the recorded hash MISMATCHES, the monolith genuinely changed -> stale.
    #   - If NO hash is recorded, fall back to the original mtime guard unchanged.
    # Collect EVERY recorded monolith-hash field. Do NOT short-circuit on the first
    # present field (`sha256 or monolith_sha256`): that lets a matching sha256 MASK a
    # mismatching monolith_sha256, wrongly classifying a genuinely-stale split as
    # PRESENT-AND-VALID (F-QA-2). Every hash field that is present MUST equal the
    # current monolith content hash; any mismatch (or a malformed/non-64-hex present
    # hash) => stale, fail loud. The mtime fallback applies ONLY when NO hash field
    # is recorded at all.
    recorded_hashes = []  # list of (field_name, value) for present hash fields
    # Key PRESENCE (not non-null value) marks a field as "recorded": a manifest that
    # explicitly carries "sha256": null is asserting a hash it failed to compute — it
    # must NOT silently fall through to the mtime guard (that would re-open the
    # short-circuit hole). A present-but-null/malformed hash is caught by the 64-hex
    # validation below and classified stale.
    for field in ("sha256", "monolith_sha256"):
        if field in data:
            recorded_hashes.append((field, data[field]))
    if recorded_hashes:
        try:
            actual_hash = _sha256_file(abs_spec)
        except OSError as exc:
            return invalid("could not hash monolith for staleness check: %s" % exc)
        for field, val in recorded_hashes:
            if not (isinstance(val, str) and len(val) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in val)):
                return invalid("manifest.%s is present but not a 64-hex sha256 (got %r) — cannot validate freshness" % (field, val))
            if val.lower() != actual_hash.lower():
                return invalid("split is stale (monolith content changed since split: manifest %s != monolith hash)" % field)
        # ALL present hashes match -> fresh; skip the mtime check (mtime drift is a no-op artifact)
    else:
        try:
            if os.path.getmtime(abs_spec) > os.path.getmtime(split_marker):
                return invalid("split is stale (monolith newer than .split-complete)")
        except OSError as exc:
            return invalid("could not stat for staleness check: %s" % exc)

    # All referenced view files must exist as regular files UNDER this candidate's
    # views_dir. manifest view values use historical conventions:
    #   new schema:  "views/architect.md"                 (relative to spec dir)
    #   old schema:  "<candidate>/views/architect.md"     (relative to specs root)
    #   dict forms:  {"file"/"path": "views/architect.md"} OR a metadata-only dict
    #               (e.g. {"line_count": N}) where the path is inferred views/<role>.md
    # The resolved real path MUST stay inside views_dir (reject absolute paths,
    # ".." escapes, and any value that resolves outside the candidate's views dir) —
    # otherwise a manifest could point at an unrelated file and falsely validate
    # (codex issue 1).
    views = data.get("views")
    if not isinstance(views, dict) or not views:
        return invalid("manifest.views missing or empty")
    views_dir_real = _real(views_dir)
    for role, val in views.items():
        rel = _view_entry_path(val, role)   # normalize string/dict -> a path string
        if rel is None:
            return invalid("manifest.views[%r] has no usable view path (got %r)" % (role, val))
        # candidate resolutions, in precedence order:
        #   spec_dir/<rel>            (new: rel begins with "views/")
        #   specs_root/<rel>          (old: rel begins with "<candidate>/views/")
        resolved = None
        for base in (spec_dir, specs_root):
            cand = _real(os.path.join(base, rel))
            # must be a regular file AND inside this candidate's views_dir
            if (cand == views_dir_real or cand.startswith(views_dir_real + os.sep)) and os.path.isfile(cand):
                resolved = cand
                break
        if resolved is None:
            return invalid("referenced view file for role %r not found as a regular file under views/ (%s)" % (role, rel))

    detail["reason"] = "valid"
    return PRESENT_AND_VALID, detail


def resolve(spec_path, project_dir):
    project_dir = os.path.abspath(project_dir)
    project_real = _real(project_dir)

    # Anchor relative spec_path to project_dir but DO NOT realpath-resolve before
    # deriving the id: the candidate id must match the filename the caller invoked
    # (e.g. spec-<ts>.md), not a symlink target it may point at. Resolve symlinks
    # only for the samefile() monolith-identity comparison (abs_spec).
    lexical_spec = spec_path if os.path.isabs(spec_path) else os.path.join(project_dir, spec_path)
    abs_spec = _anchor(spec_path, project_dir)   # realpath, for samefile identity
    if not os.path.isfile(abs_spec):
        _err("spec_path is not a readable file: %s" % abs_spec)
        return EXIT_USAGE, {"error": "spec_path not a readable file", "spec_path": spec_path, "abs_spec": abs_spec}

    raw_id = os.path.splitext(os.path.basename(lexical_spec))[0]  # stem from CALLER path (pre-symlink-resolve)
    de_prefixed = raw_id[len("spec-"):] if raw_id.startswith("spec-") else raw_id  # strip EXACTLY ONE leading "spec-" from the stem
    # candidates: de_prefixed first, dedup preserving order
    candidates = []
    for c in (de_prefixed, raw_id):
        if c and c not in candidates:
            candidates.append(c)

    state_per_candidate = {}
    details = {}
    for c in candidates:
        st, detail = classify(c, abs_spec, project_dir, project_real)
        state_per_candidate[c] = st
        details[c] = detail

    valid_set = [c for c in candidates if state_per_candidate[c] == PRESENT_AND_VALID]
    invalid_set = [c for c in candidates if state_per_candidate[c] == PRESENT_BUT_INVALID]

    base_out = {
        "spec_path": spec_path,
        "abs_spec": abs_spec,
        "raw_id": raw_id,
        "candidates": candidates,
        "state_per_candidate": state_per_candidate,
    }

    if invalid_set:
        c = invalid_set[0]
        reason = details[c]["reason"]
        _err("PRESENT-BUT-INVALID candidate %r: %s" % (c, reason))
        base_out.update({"error": "present_but_invalid", "candidate": c, "failed_predicate": reason})
        return EXIT_INVALID, base_out

    if len(valid_set) == 2:
        _err("AMBIGUOUS: two valid manifests point at the same monolith: %s" % valid_set)
        base_out.update({"error": "ambiguous", "candidates_valid": valid_set})
        return EXIT_AMBIGUOUS, base_out

    if len(valid_set) == 1:
        c = valid_set[0]
        d = details[c]
        base_out.update({
            "canonical_id": c,
            "artifact_id": c,
            "manifest_path": _relpath(d["manifest_path"], project_dir),
            "split_marker": _relpath(d["split_marker"], project_dir),
            "views_dir": _relpath(d["views_dir"], project_dir),
            "cp_dir": _relpath(d["cp_dir"], project_dir),
            "views_available": True,
        })
        return EXIT_OK, base_out

    # all ABSENT -> legacy monolith mode
    base_out.update({
        "canonical_id": de_prefixed,
        "artifact_id": de_prefixed,
        "manifest_path": None,
        "split_marker": None,
        "views_dir": None,
        "cp_dir": _relpath(os.path.join(project_dir, ".claude", "specs", de_prefixed), project_dir),
        "views_available": False,
    })
    return EXIT_OK, base_out


def _relpath(abs_path, project_dir):
    """Return a project-root-relative path when inside the project, else absolute."""
    project_dir = os.path.abspath(project_dir)
    try:
        rel = os.path.relpath(abs_path, project_dir)
    except ValueError:
        return abs_path
    if rel.startswith(".." + os.sep) or rel == "..":
        return abs_path
    return rel


def main(argv=None):
    parser = argparse.ArgumentParser(description="Resolve a /spec monolith to its split-artifact id + paths.")
    parser.add_argument("--spec-path", required=True, help="Path to the monolith spec .md (e.g. docs/dev/specs/spec-<ts>.md)")
    parser.add_argument("--project-dir", default=os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd(),
                        help="Project root (default: $CLAUDE_PROJECT_DIR or cwd)")
    args = parser.parse_args(argv)

    code, out = resolve(args.spec_path, args.project_dir)
    sys.stdout.write(json.dumps(out, indent=2, sort_keys=True) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
