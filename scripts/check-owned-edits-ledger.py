#!/usr/bin/env python3
"""Validate a dev-report's owned-edits ledger against the consumer's real contract.

The owned-edits ledger (``owned_edits`` / ``pre_edit_snapshots`` /
``untracked_modified_provenance``) is what lets ``scripts/stage-owned-hunks.py``
stage a cycle's owned hunks. Until now that contract existed only as prose in
``agents/dev.md`` and ``agents/changelog-analyst.md``, was described by no schema,
and was validated nowhere at write time -- so a malformed ledger surfaced hours
later during replay, after the lane had ended and its context was gone.

This checker closes the write-time gap. It validates the structural contract with
``schemas/owned-edits-ledger.v1.json`` and then enforces the five requirements that
schema cannot express (see ``x-unexpressible-in-schema`` in that file).

CONTRACT SOURCE
  Derived from the consumer's CODE, not from agent prose:
    scripts/stage-owned-hunks.py  -- cited BY SYMBOL throughout (see CITATION
      POLICY below), and bound to a measured digest recorded in the schema's
      x-consumer block, which tests/test_owned_edits_ledger_contract.py asserts.
    plus the snapshot-materialization rule in agents/changelog-analyst.md, found by
      searching for the anchor "2. Snapshot materialization (REQUIRED" -- the only
      place the report-level pre_edit_snapshots map becomes the --snapshot file the
      consumer opens.
  Where prose and code disagree, the code governs. Pass --show-consumer to print
  the rule table with the source construct that imposes each rule.

CITATION POLICY (deliberate; do not "helpfully" re-add line numbers)
  Every citation into another file names a FUNCTION, CLASS, or a distinctive
  quoted fragment -- never a line number. Several sessions write this tree
  concurrently, so a pinned line number silently rots into pointing at unrelated
  code, while a symbol or a quoted anchor either still resolves or fails loudly
  when you search for it. Each RULES entry below is phrased so that
  `grep -n "<the quoted fragment>" <the named file>` is a runnable check.

CONSUMER COUPLING (why this file imports its own consumer)
  The empty-needle semantics were previously MIRRORED here as a hand-copied
  reimplementation, and that copy drifted: the consumer moved from a -1 sentinel
  to raising EmptyOwnedOldStringError, while this checker kept describing the
  sentinel for six documented sites. A copy of a contract is a second source of
  truth, so this file now IMPORTS the consumer's real primitives
  (_count_occurrences / _locate_unique / EmptyOwnedOldStringError) instead of
  restating them, and self-checks their behaviour at startup. Drift is now
  impossible by construction rather than merely discouraged.

Usage:
  check-owned-edits-ledger.py <dev-report.json> [<dev-report.json> ...]
      [--git-root <path>] [--no-discover] [--json] [--show-consumer]

  <dev-report.json>  Any report of the cycle. By default its sibling lane shards
                     and the canonical report are discovered from the task id and
                     validated too, because three of the rules are only decidable
                     across the whole lane set.
  --git-root      Repo root used to resolve 7-40 hex snapshot blob refs via
                  `git cat-file -e`. Without it, SNAPSHOT-BLOB-UNRESOLVED is
                  reported as a skipped check rather than silently passing.
  --no-discover   Validate only the paths given.
  --json          Emit the findings as JSON instead of text.
  --show-consumer Print the rule table (id, requirement, consumer source) and exit.

Exit codes:
  0  every checked report satisfies the contract
  1  at least one contract violation (details on stdout)
  2  usage error, unreadable/unparseable input, or ENVIRONMENT/INFRASTRUCTURE
     failure (git not executable, --git-root not a repository, jsonschema not
     importable, consumer module missing or drifted). Always accompanied by an
     "INFRASTRUCTURE FAILURE" or "INPUT ERROR" banner on stderr.

  Exit 1 means "the reports were read and judged, and a lane's ledger is wrong."
  It must NEVER be produced by a broken environment: the documented wire-in maps
  1 to "re-dispatch the lane the findings name", so a 1 with no findings would
  blame an innocent lane. Every exception is therefore caught and mapped to 2.

NOT WIRED INTO ANY BLOCKING PATH -- see "FUTURE WIRE-IN" at the bottom of this
docstring. Deliberately standalone: adding a gate now would interrupt an
in-flight commit cycle. Integration is a separate, later change.

FUTURE WIRE-IN (describing it is part of this deliverable; performing it is not)
  Where:  commands/commit.md, Step 7 -- the /commit dispatch that hands the
          dev-report to the changelog-analyst subagent, immediately BEFORE the
          agent begins Phase 5 hunk-filtered staging (agents/changelog-analyst.md,
          anchor "2. Snapshot materialization (REQUIRED"). That is the last
          moment the ledger can be rejected while the
          authoring lane's context may still be recoverable, and the first moment
          the whole lane set exists on disk.
  How:    run `scripts/check-owned-edits-ledger.py <canonical-dev-report> \
          --git-root "$GIT_ROOT"` and branch on the exit code.
  On failure (exit 1): do NOT stage, do NOT commit, and do NOT fall back to
          whole-file staging -- that is the fail-open this contract exists to
          prevent. Abort the commit and surface the findings verbatim, so the
          orchestrator can re-dispatch the named lane to re-emit its ledger. The
          finding already names the lane, the field, the shape found and the shape
          required, which is what a re-dispatch prompt needs.
  On exit 2: treat as infrastructure failure, abort the same way; never interpret
          an unreadable ledger as an empty one.
  Alternative/second site: a PreToolUse hook on the Write of
          docs/dev/dev-report-*.json would catch a malformed ledger at the instant
          the lane writes it (earliest possible feedback), but it can only enforce
          the per-lane rules -- UMP-LANE-ONLY and the cross-lane co-presence rules
          need the full lane set and so must stay at the /commit site.
"""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys

OK = 0
VIOLATION = 1
HARD = 2

SCHEMA_REL = os.path.join("schemas", "owned-edits-ledger.v1.json")
CONSUMER_REL = os.path.join("scripts", "stage-owned-hunks.py")


class InfrastructureError(Exception):
    """The environment could not answer the question -- NOT a contract violation.

    Raised for anything that makes the verdict unknowable rather than negative:
    git missing, --git-root not a repository, jsonschema absent, the consumer
    module gone or drifted. Always mapped to exit 2, never to exit 1.
    """


def _load_consumer(repo_root):
    """Import scripts/stage-owned-hunks.py and return its replay primitives.

    The module is hyphen-named, so it is loaded by file location rather than by
    `import`. It is import-safe: its module level is a docstring, three int
    constants and an `if __name__ == "__main__"` guard, so importing runs no
    argument parsing and touches no repository.

    Returns (module, count_occurrences, EmptyOwnedOldStringError).
    """
    consumer = os.path.join(repo_root, CONSUMER_REL)
    if not os.path.isfile(consumer):
        raise InfrastructureError(
            "consumer not found at %s; this checker validates that file's contract "
            "and cannot answer without it" % consumer
        )
    try:
        spec = importlib.util.spec_from_file_location("stage_owned_hunks", consumer)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # import-time failure is environmental, not a verdict
        raise InfrastructureError(
            "cannot import consumer %s: %s: %s"
            % (consumer, type(exc).__name__, exc)
        )

    missing = [name for name in
               ("_count_occurrences", "_locate_unique", "EmptyOwnedOldStringError")
               if not hasattr(module, name)]
    if missing:
        raise InfrastructureError(
            "consumer %s no longer exports %s -- it has been refactored underneath "
            "this checker. Re-derive the rule table against the new code before "
            "trusting any verdict." % (consumer, ", ".join(missing))
        )

    empty_error = module.EmptyOwnedOldStringError
    count = module._count_occurrences

    # ACTIVE BEHAVIOURAL BINDING. Asserting the symbols merely EXIST would not have
    # caught the drift this checker just suffered: the mirror kept returning -1 long
    # after the consumer began raising. So assert the SEMANTICS the rule table
    # states, at every startup, and fail loudly rather than emit a wrong verdict.
    try:
        count(b"abc", b"")
    except empty_error:
        pass
    except Exception as exc:
        raise InfrastructureError(
            "consumer's _count_occurrences raised %s for an empty needle, not "
            "EmptyOwnedOldStringError; the rule table's REPLAY-EMPTY-OLD wording is "
            "no longer true of the consumer" % type(exc).__name__
        )
    else:
        raise InfrastructureError(
            "consumer's _count_occurrences RETURNED for an empty needle instead of "
            "raising EmptyOwnedOldStringError; the empty-old contract has changed "
            "underneath this checker and REPLAY-EMPTY-OLD must be re-derived"
        )
    if count(b"aXbXc", b"X") != 2 or count(b"abc", b"zz") != 0:
        raise InfrastructureError(
            "consumer's _count_occurrences no longer counts non-overlapping "
            "occurrences as the REPLAY-UNIQUE rule assumes"
        )
    return module, count, empty_error

# Rule table: id -> (requirement, the construct that imposes it).
#
# Sources are cited BY SYMBOL or by a distinctive quoted fragment, never by line
# number -- see CITATION POLICY in the module docstring. Each is runnable:
#   grep -n "<the quoted fragment>" <the named file>
RULES = {
    "SCHEMA": (
        "Structural shape must satisfy schemas/owned-edits-ledger.v1.json",
        "scripts/stage-owned-hunks.py (whole contract)",
    ),
    "LEDGER-ABSENT": (
        "the document must actually carry a ledger: owned_edits WITH "
        "pre_edit_snapshots, or an untracked_modified_provenance contract, and "
        "none of them empty",
        "schemas/owned-edits-ledger.v1.json top-level anyOf; a report with no "
        "ledger has nothing for stage-owned-hunks.py to stage and must not be "
        "counted as conforming",
    ),
    "REPLAY-UNIQUE": (
        "each entry's 'old' must occur exactly once in the replay buffer as it has "
        "evolved through all prior entries",
        "scripts/stage-owned-hunks.py def _replay_live() and def main(), both "
        "reporting 'not uniquely locatable during replay'",
    ),
    "REPLAY-EMPTY-OLD": (
        "'old' must be non-empty; an empty needle is structurally unlocatable, so "
        "the consumer rejects it as a malformed ledger entry rather than counting it",
        "scripts/stage-owned-hunks.py class EmptyOwnedOldStringError, raised by "
        "def _count_occurrences(), propagated by def _locate_unique(), and caught "
        "at both replay sites as 'has an empty old_string'",
    ),
    "SNAPSHOT-DIGEST-NOT-CONTENT": (
        "pre_edit_snapshots value must be literal pre-edit content or a 7-40 hex "
        "blob ref; a sha256 digest is neither",
        "agents/changelog-analyst.md anchor '2. Snapshot materialization (REQUIRED'",
    ),
    "SNAPSHOT-BLOB-UNRESOLVED": (
        "a 7-40 hex snapshot value must resolve via `git cat-file -e`, else it is "
        "written out as literal text",
        "agents/changelog-analyst.md anchor '2. Snapshot materialization (REQUIRED'",
    ),
    "LEDGER-SNAPSHOT-ORPHAN": (
        "every owned_edits path needs a pre_edit_snapshots entry and vice versa",
        "agents/changelog-analyst.md anchor 'Fail-closed for ambiguous shared dirty "
        "files' (the warn-and-skip exclusion)",
    ),
    "UMP-LANE-ONLY": (
        "untracked_modified_provenance is read only from the canonical report named "
        "dev-report-<task_id>.json",
        "scripts/stage-owned-hunks.py def _load_untracked_modified_contract(), its "
        "`expected_name` check and its --report-sha256 digest gate",
    ),
    "UMP-HASH-IDENTICAL": (
        "pre_edit.sha256 must differ from final.sha256",
        "scripts/stage-owned-hunks.py def _load_untracked_modified_contract(), the "
        "pre_edit/final digest-difference check",
    ),
    "UMP-PATH-KEY-MISMATCH": (
        "the contract's inner 'path' must equal its map key",
        "scripts/stage-owned-hunks.py def _load_untracked_modified_contract(), the "
        "contract-path vs claim-key check",
    ),
    "UMP-NOT-CLAIMED": (
        "the key must be claimed exactly once in dev.files_modified",
        "scripts/stage-owned-hunks.py def _load_untracked_modified_contract(), the "
        "dev.files_modified claim scan",
    ),
    "UMP-IN-CREATED": (
        "the key must NOT appear in dev.files_created",
        "scripts/stage-owned-hunks.py def _load_untracked_modified_contract(), the "
        "dev.files_created exclusion",
    ),
    "UMP-PREEDIT-PROV-MISSING": (
        "a verified pre_edit_provenance sibling is required",
        "scripts/stage-owned-hunks.py def _load_untracked_modified_contract(), the "
        "pre_edit_provenance / verified_before_edit gate",
    ),
    "UMP-PREEDIT-PROV-MISMATCH": (
        "pre_edit_provenance.files[key] and .statuses[key] must equal the contract's "
        "pre_edit.sha256 and '??'",
        "scripts/stage-owned-hunks.py def _load_untracked_modified_contract(), the "
        "pre_edit_provenance files/statuses cross-check",
    ),
    "UMP-FINAL-HASH-MISMATCH": (
        "final_source_hashes[key] must equal the contract's final.sha256",
        "scripts/stage-owned-hunks.py def _load_untracked_modified_contract(), the "
        "final_source_hashes cross-check",
    ),
}

BLOB_REF = re.compile(r"^[0-9a-f]{7,40}$")


def _finding(rule_id, lane, path, field, found, required):
    requirement, source = RULES[rule_id]
    return {
        "rule": rule_id,
        "lane": lane,
        "file": path,
        "field": field,
        "found": found,
        "required": required,
        "requirement": requirement,
        "consumer_source": source,
    }


def _shape(value, limit=140):
    """Describe the shape actually found, concretely enough to act on."""
    if value is None:
        return "absent"
    if isinstance(value, dict):
        return "object with keys %s" % sorted(value.keys())
    if isinstance(value, list):
        return "array of %d" % len(value)
    if isinstance(value, str):
        shown = value if len(value) <= limit else value[:limit] + "..."
        return "string(len=%d) %r" % (len(value), shown)
    return "%s %r" % (type(value).__name__, value)


# --- rules JSON Schema cannot express ------------------------------------


def _run_git(args):
    """Run git, converting an unusable git into a loud InfrastructureError.

    subprocess.run raises FileNotFoundError when git is not on PATH. Left
    uncaught that escaped main() and terminated the interpreter with status 1 --
    byte-identical, to a caller reading only the exit code, to "a lane's ledger
    violates the contract". That is the precise defect class this checker exists
    to eliminate, so it is trapped here and mapped to exit 2 instead.
    """
    try:
        return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise InfrastructureError(
            "cannot execute git (%s: %s). The snapshot blob-ref checks require it; "
            "without git the contract question is UNANSWERED, not answered "
            "negatively." % (type(exc).__name__, exc)
        )


def _require_usable_git(git_root):
    """Fail loudly and early when --git-root cannot serve blob lookups.

    Checked up front so an unusable environment is reported before any report is
    read, rather than surfacing mid-scan as a partial result.
    """
    probe = _run_git(["git", "-C", git_root, "rev-parse", "--git-dir"])
    if probe.returncode != 0:
        raise InfrastructureError(
            "--git-root %r is not a git repository (git rev-parse --git-dir exited "
            "%d: %s). Blob-ref snapshots cannot be resolved, so SNAPSHOT-BLOB-"
            "UNRESOLVED findings would be environmental noise, not violations."
            % (git_root, probe.returncode,
               probe.stderr.decode("utf-8", "replace").strip())
        )


def _resolve_snapshot(value, git_root):
    """Return (content_bytes, mode, note) exactly as the materializer would.

    agents/changelog-analyst.md, anchor "2. Snapshot materialization (REQUIRED":
    a 7-40 lowercase-hex value that resolves as a git object is replaced by that
    blob's bytes; anything else is written out verbatim as literal content.
    """
    if BLOB_REF.match(value):
        if not git_root:
            return None, "blobref-unchecked", "no --git-root; cannot resolve"
        probe = _run_git(["git", "-C", git_root, "cat-file", "-e", value])
        if probe.returncode != 0:
            return None, "blobref-unresolved", "git cat-file -e failed"
        blob = _run_git(["git", "-C", git_root, "cat-file", "blob", value])
        return blob.stdout, "blob", ""
    return value.encode("utf-8"), "literal", ""


def _check_replay(doc, lane, path, git_root, findings, consumer):
    """REPLAY-UNIQUE / REPLAY-EMPTY-OLD / SNAPSHOT-BLOB-UNRESOLVED.

    `consumer` is the (count_occurrences, EmptyOwnedOldStringError) pair imported
    from scripts/stage-owned-hunks.py. The counting is the CONSUMER'S OWN, not a
    copy of it: see CONSUMER COUPLING in the module docstring.
    """
    count_occurrences, empty_old_error = consumer
    owned = doc.get("owned_edits")
    snaps = doc.get("pre_edit_snapshots")
    if not isinstance(owned, dict):
        return
    snaps = snaps if isinstance(snaps, dict) else {}

    for rel, edits in sorted(owned.items()):
        if not isinstance(edits, list):
            continue  # schema already reported it

        for i, edit in enumerate(edits):
            if isinstance(edit, dict) and edit.get("old") == "":
                findings.append(_finding(
                    "REPLAY-EMPTY-OLD", lane, path,
                    "owned_edits[%r][%d].old" % (rel, i),
                    "empty string (pure insertion; new=%s)" % _shape(edit.get("new"), 60),
                    "a non-empty 'old' anchoring the insertion to unique surrounding "
                    "text (an empty needle makes the consumer's _count_occurrences "
                    "raise EmptyOwnedOldStringError, which both replay sites catch "
                    "and report as 'has an empty old_string' -- a malformed ledger "
                    "entry, held distinct from content drift)",
                ))

        raw = snaps.get(rel)
        if not isinstance(raw, str):
            continue  # schema/orphan rules already reported it
        content, mode, note = _resolve_snapshot(raw, git_root)
        if mode == "blobref-unresolved":
            findings.append(_finding(
                "SNAPSHOT-BLOB-UNRESOLVED", lane, path,
                "pre_edit_snapshots[%r]" % rel,
                "%s -- %s" % (_shape(raw), note),
                "a hex value that resolves in this repo, else the literal pre-edit "
                "content bytes",
            ))
            continue
        if content is None:
            continue  # blobref-unchecked: reported as skipped, not as a pass

        replay = content
        for i, edit in enumerate(edits):
            if not (isinstance(edit, dict) and isinstance(edit.get("old"), str)
                    and isinstance(edit.get("new"), str)):
                break  # schema already reported it
            old_b = edit["old"].encode("utf-8")
            new_b = edit["new"].encode("utf-8")
            try:
                n = count_occurrences(replay, old_b)
            except empty_old_error:
                break  # REPLAY-EMPTY-OLD already reported this entry
            if n != 1:
                findings.append(_finding(
                    "REPLAY-UNIQUE", lane, path,
                    "owned_edits[%r][%d].old" % (rel, i),
                    "%d occurrences in the replay buffer at step %d "
                    "(snapshot resolved as %s, %d bytes); old=%s"
                    % (n, i, mode, len(content), _shape(edit["old"], 60)),
                    "exactly 1 occurrence; a 0 here usually means "
                    "pre_edit_snapshots[%r] holds a digest or a stale revision "
                    "rather than the pre-edit bytes" % rel,
                ))
                break
            off = replay.find(old_b)
            replay = replay[:off] + new_b + replay[off + len(old_b):]


def _check_copresence(doc, lane, path, findings):
    """LEDGER-SNAPSHOT-ORPHAN."""
    owned = doc.get("owned_edits")
    snaps = doc.get("pre_edit_snapshots")
    if not isinstance(owned, dict) and not isinstance(snaps, dict):
        return
    owned_keys = set(owned) if isinstance(owned, dict) else set()
    snap_keys = set(snaps) if isinstance(snaps, dict) else set()
    for rel in sorted(owned_keys - snap_keys):
        findings.append(_finding(
            "LEDGER-SNAPSHOT-ORPHAN", lane, path,
            "pre_edit_snapshots[%r]" % rel,
            "absent, though owned_edits[%r] has %d entries"
            % (rel, len(owned[rel]) if isinstance(owned.get(rel), list) else 0),
            "a pre_edit_snapshots entry for every owned_edits path (a dirty tracked "
            "file with no snapshot is warn-and-skipped and contributes nothing)",
        ))
    for rel in sorted(snap_keys - owned_keys):
        findings.append(_finding(
            "LEDGER-SNAPSHOT-ORPHAN", lane, path,
            "owned_edits[%r]" % rel,
            "absent, though pre_edit_snapshots[%r] is present" % rel,
            "an owned_edits entry for every snapshotted path",
        ))


def _check_untracked_modified(doc, lane, path, is_canonical, findings):
    """UMP-* cross-field bindings and the canonical-only rule."""
    contracts = doc.get("untracked_modified_provenance")
    if contracts is None:
        return
    if not isinstance(contracts, dict):
        return  # schema already reported it

    if not is_canonical:
        findings.append(_finding(
            "UMP-LANE-ONLY", lane, path,
            "untracked_modified_provenance",
            "present in lane shard %r (keys %s)" % (lane, sorted(contracts)),
            "presence in the canonical report dev-report-<task_id>.json, whose "
            "sha256 the repository plan binds; a lane-only contract is never read",
        ))

    dev = doc.get("dev") if isinstance(doc.get("dev"), dict) else {}
    modified = dev.get("files_modified") if isinstance(dev.get("files_modified"), list) else []
    created = dev.get("files_created") if isinstance(dev.get("files_created"), list) else []
    pre_prov = doc.get("pre_edit_provenance")
    final_hashes = doc.get("final_source_hashes")

    for key, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            continue  # schema already reported it
        field = "untracked_modified_provenance[%r]" % key

        if contract.get("path") != key:
            findings.append(_finding(
                "UMP-PATH-KEY-MISMATCH", lane, path, field + ".path",
                _shape(contract.get("path")),
                "exactly the map key %r" % key,
            ))

        pre = contract.get("pre_edit") if isinstance(contract.get("pre_edit"), dict) else {}
        fin = contract.get("final") if isinstance(contract.get("final"), dict) else {}
        pre_sha, fin_sha = pre.get("sha256"), fin.get("sha256")
        if pre_sha is not None and pre_sha == fin_sha:
            findings.append(_finding(
                "UMP-HASH-IDENTICAL", lane, path, field + ".final.sha256",
                "identical to pre_edit.sha256 (%s)" % pre_sha,
                "a different digest -- the difference IS the authenticated cycle "
                "modification",
            ))

        if modified.count(key) != 1:
            findings.append(_finding(
                "UMP-NOT-CLAIMED", lane, path, "dev.files_modified",
                "%d claims of %r (array of %d)" % (modified.count(key), key, len(modified)),
                "exactly one claim of the contract key in dev.files_modified",
            ))
        if key in created:
            findings.append(_finding(
                "UMP-IN-CREATED", lane, path, "dev.files_created",
                "contains %r" % key,
                "the key must appear only in dev.files_modified; recording an "
                "adopted pre-existing file as created is the relabelling the "
                "admission mode exists to prevent",
            ))

        if not isinstance(pre_prov, dict):
            findings.append(_finding(
                "UMP-PREEDIT-PROV-MISSING", lane, path, "pre_edit_provenance",
                _shape(pre_prov),
                "an object with verified_before_edit=true, a non-empty source, and "
                "files/statuses maps covering %r" % key,
            ))
        else:
            files = pre_prov.get("files") if isinstance(pre_prov.get("files"), dict) else {}
            statuses = pre_prov.get("statuses") if isinstance(pre_prov.get("statuses"), dict) else {}
            if pre_sha is not None and files.get(key) != pre_sha:
                findings.append(_finding(
                    "UMP-PREEDIT-PROV-MISMATCH", lane, path,
                    "pre_edit_provenance.files[%r]" % key,
                    _shape(files.get(key)),
                    "the contract's pre_edit.sha256 (%s)" % pre_sha,
                ))
            if statuses.get(key) != "??":
                findings.append(_finding(
                    "UMP-PREEDIT-PROV-MISMATCH", lane, path,
                    "pre_edit_provenance.statuses[%r]" % key,
                    _shape(statuses.get(key)),
                    "exactly '??'",
                ))

        fh = final_hashes if isinstance(final_hashes, dict) else {}
        if fin_sha is not None and fh.get(key) != fin_sha:
            findings.append(_finding(
                "UMP-FINAL-HASH-MISMATCH", lane, path,
                "final_source_hashes[%r]" % key,
                _shape(fh.get(key)),
                "the contract's final.sha256 (%s)" % fin_sha,
            ))


# --- schema validation ----------------------------------------------------


def _load_schema(script_dir):
    candidate = os.path.join(os.path.dirname(script_dir), SCHEMA_REL)
    with open(candidate, "r", encoding="utf-8") as fh:
        return json.load(fh), candidate


def _load_validator(schema):
    """Build the schema validator, mapping a missing jsonschema to exit 2.

    Previously `import jsonschema` sat inside the per-document check, so an
    environment without it raised ImportError out of main() and exited 1 with no
    output -- the same silent-failure-wearing-a-verdict shape as the missing git.
    """
    try:
        import jsonschema
    except ImportError as exc:
        raise InfrastructureError(
            "jsonschema is not importable (%s); the structural half of the contract "
            "cannot be evaluated, so no verdict can be issued" % exc
        )
    return jsonschema.Draft202012Validator(schema)


def _check_schema(validator, doc, lane, path, findings):
    for error in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        pointer = "".join(
            "[%r]" % part if isinstance(part, str) else "[%d]" % part
            for part in error.absolute_path
        ) or "<document root>"
        # The top-level anyOf is the "carries a ledger at all" constraint. Left as a
        # generic SCHEMA finding it reads as jsonschema's useless "is not valid under
        # any of the given schemas"; named, it tells the operator the document simply
        # has no ledger, which is a different act than emitting a malformed one.
        if pointer == "<document root>" and error.validator == "anyOf":
            findings.append(_finding(
                "LEDGER-ABSENT", lane, path, "<document root>",
                "no ledger to check: owned_edits=%s, pre_edit_snapshots=%s, "
                "untracked_modified_provenance=%s"
                % (_shape(doc.get("owned_edits"), 40),
                   _shape(doc.get("pre_edit_snapshots"), 40),
                   _shape(doc.get("untracked_modified_provenance"), 40)),
                "a non-empty owned_edits WITH a non-empty pre_edit_snapshots, or a "
                "non-empty untracked_modified_provenance. A report carrying neither "
                "gives the consumer nothing to stage; counting it as conforming is "
                "what made a corpus pass-rate look like discrimination.",
            ))
            continue
        findings.append(_finding(
            "SCHEMA", lane, path, pointer,
            _shape(error.instance),
            error.message,
        ))


# --- lane discovery -------------------------------------------------------


def _task_id(doc, path):
    for field in ("task_id", "request_id"):
        value = doc.get(field)
        if isinstance(value, str) and value:
            return value
    stem = os.path.basename(path)
    if stem.startswith("dev-report-") and stem.endswith(".json"):
        return stem[len("dev-report-"):-len(".json")]
    return None


def _discover(path, task_id):
    """Return [(path, lane_label, is_canonical)] for the whole cycle."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    canonical_name = "dev-report-%s.json" % task_id
    found = []
    for name in sorted(os.listdir(directory)):
        if not (name.startswith("dev-report") and name.endswith(".json")):
            continue
        if task_id not in name:
            continue
        stem = name[len("dev-report-"):-len(".json")] if name.startswith("dev-report-") else name
        is_canonical = name == canonical_name
        if is_canonical:
            label = "canonical"
        else:
            label = stem.replace(task_id, "").strip("-") or stem
        found.append((os.path.join(directory, name), label, is_canonical))
    return found


def _validate_one(validator, path, lane, is_canonical, git_root, findings,
                  consumer, input_errors):
    """Validate one report. Appends to `findings` (exit 1) or `input_errors` (exit 2).

    An unreadable or unparseable file is an INPUT error, not a contract violation.
    It used to be recorded as a SCHEMA finding, which meant the two real
    unparseable reports in this corpus exited 1 -- telling the operator a lane had
    emitted a bad ledger when in truth no ledger had been read at all. The
    documented exit-2 case was therefore unreachable for the very case it names.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except OSError as exc:
        input_errors.append({
            "file": path, "lane": lane, "kind": "unreadable",
            "detail": "%s: %s" % (type(exc).__name__, exc),
        })
        return
    except ValueError as exc:
        input_errors.append({
            "file": path, "lane": lane, "kind": "unparseable-json",
            "detail": "%s: %s" % (type(exc).__name__, exc),
        })
        return
    if not isinstance(doc, dict):
        input_errors.append({
            "file": path, "lane": lane, "kind": "not-a-json-object",
            "detail": "top level is %s" % _shape(doc, 60),
        })
        return
    _check_schema(validator, doc, lane, path, findings)
    _check_copresence(doc, lane, path, findings)
    _check_replay(doc, lane, path, git_root, findings, consumer)
    _check_untracked_modified(doc, lane, path, is_canonical, findings)


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("reports", nargs="*")
    ap.add_argument("--git-root")
    ap.add_argument("--no-discover", action="store_true")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--show-consumer", action="store_true")
    ns = ap.parse_args(argv)

    if ns.show_consumer:
        for rule_id in sorted(RULES):
            requirement, source = RULES[rule_id]
            sys.stdout.write("%-28s %s\n%-28s   imposed by: %s\n"
                             % (rule_id, requirement, "", source))
        return OK
    if not ns.reports:
        sys.stderr.write("error: at least one dev-report path is required\n")
        return HARD

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    try:
        schema, schema_path = _load_schema(script_dir)
    except (OSError, ValueError) as exc:
        raise InfrastructureError("cannot load %s: %s" % (SCHEMA_REL, exc))

    validator = _load_validator(schema)
    _module, count_occurrences, empty_old_error = _load_consumer(repo_root)
    consumer = (count_occurrences, empty_old_error)
    if ns.git_root:
        _require_usable_git(ns.git_root)

    targets, seen = [], set()
    for report in ns.reports:
        if not os.path.isfile(report):
            raise InfrastructureError("not a file: %s" % report)
        try:
            with open(report, "r", encoding="utf-8") as fh:
                task_id = _task_id(json.load(fh), report)
        except (OSError, ValueError):
            task_id = None
        # Canonicality is a property of the filename vs the task id, so it must be
        # computed even when discovery is off -- otherwise a canonical report checked
        # on its own would be mis-reported as a lane-only UMP contract.
        is_canonical = bool(task_id) and os.path.basename(report) == "dev-report-%s.json" % task_id
        entries = [(report, "canonical" if is_canonical else "given", is_canonical)]
        if not ns.no_discover and task_id:
            entries = _discover(report, task_id) or entries
        for entry in entries:
            key = os.path.abspath(entry[0])
            if key not in seen:
                seen.add(key)
                targets.append(entry)

    findings, input_errors = [], []
    for path, lane, is_canonical in targets:
        _validate_one(validator, path, lane, is_canonical, ns.git_root, findings,
                      consumer, input_errors)

    if ns.as_json:
        sys.stdout.write(json.dumps({
            "schema": schema_path,
            "checked": [{"file": p, "lane": l, "canonical": c} for p, l, c in targets],
            "violation_count": len(findings),
            "findings": findings,
            "input_errors": input_errors,
        }, indent=2, sort_keys=True) + "\n")
        if input_errors:
            _report_input_errors(input_errors)
            return HARD
        return VIOLATION if findings else OK

    sys.stdout.write("checked %d report(s) against %s\n" % (len(targets), schema_path))
    for path, lane, is_canonical in targets:
        sys.stdout.write("  [%s]%s %s\n"
                         % (lane, " (canonical)" if is_canonical else "", path))
    if not findings and not input_errors:
        sys.stdout.write("\nOK: owned-edits ledger contract satisfied.\n")
        return OK
    if findings:
        sys.stdout.write("\n%d contract violation(s):\n" % len(findings))
    for n, item in enumerate(findings, 1):
        sys.stdout.write(
            "\n%d. %s  [lane: %s]\n"
            "   file:     %s\n"
            "   field:    %s\n"
            "   found:    %s\n"
            "   required: %s\n"
            "   rule:     %s\n"
            "   imposed by: %s\n"
            % (n, item["rule"], item["lane"], item["file"], item["field"],
               item["found"], item["required"], item["requirement"],
               item["consumer_source"])
        )
    if input_errors:
        _report_input_errors(input_errors)
        return HARD
    return VIOLATION


def _report_input_errors(input_errors):
    """Announce unreadable input on stderr under an unmistakable banner."""
    sys.stderr.write(
        "\nINPUT ERROR: %d report(s) could not be read or parsed. This is exit 2, "
        "NOT a contract violation -- no ledger was judged for these files, so no "
        "lane may be blamed for them.\n" % len(input_errors)
    )
    for err in input_errors:
        sys.stderr.write("  [%s] %s\n      %s: %s\n"
                         % (err["lane"], err["file"], err["kind"], err["detail"]))


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except InfrastructureError as exc:
        # The environment, not the reports. Exit 2 so no caller can mistake this
        # for "a lane's ledger is wrong" and re-dispatch an innocent lane.
        sys.stderr.write("\nINFRASTRUCTURE FAILURE: %s\n" % exc)
        sys.stderr.write(
            "This is exit 2. No contract verdict was reached; do NOT treat it as a "
            "violation and do NOT re-dispatch any lane on the strength of it.\n")
        sys.exit(HARD)
    except KeyboardInterrupt:
        sys.stderr.write("\nINFRASTRUCTURE FAILURE: interrupted\n")
        sys.exit(HARD)
    except Exception as exc:  # nothing may escape as a bare exit 1
        import traceback
        sys.stderr.write("\nINFRASTRUCTURE FAILURE: unhandled %s: %s\n"
                         % (type(exc).__name__, exc))
        traceback.print_exc()
        sys.stderr.write(
            "This is exit 2. An uncaught exception would otherwise have terminated "
            "the interpreter with status 1, which the documented wire-in reads as "
            "'a lane's ledger violates the contract' -- a silent failure wearing "
            "the costume of a reasoned verdict.\n")
        sys.exit(HARD)
