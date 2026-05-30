#!/usr/bin/env python3
"""Regression suite for scripts/resolve-spec-artifacts.py (the canonical spec-id
resolver) + the static centralization lint (AC-B4 cases 1-12, task 20260530-092123).

Runnable two ways:
  pytest tests/test_resolve_spec_artifacts.py
  python3 tests/test_resolve_spec_artifacts.py        # self-contained fallback

All resolver fixtures are built in a tempfile sandbox (no shell `rm`; tempfile
cleans itself). The static-lint cases run against the live command files in the
nested .claude repo.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

HERE = os.path.dirname(os.path.abspath(__file__))
DOT_CLAUDE = os.path.dirname(HERE)
RESOLVER = os.path.join(DOT_CLAUDE, "scripts", "resolve-spec-artifacts.py")
LINT = os.path.join(DOT_CLAUDE, "scripts", "lint-spec-id-centralization.py")

EXIT_OK = 0
EXIT_INVALID = 3
EXIT_AMBIGUOUS = 4


# --------------------------------------------------------------------------- #
# fixture builders
# --------------------------------------------------------------------------- #
def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _make_split(root, candidate, monolith_rel, view_value_style="new",
                schema_version=1, write_marker=True, write_views=True,
                write_manifest=True, monolith_path_override=None,
                record_hash=False):
    """Create a split artifact set for `candidate` under root.

    view_value_style: "new" -> "views/<role>.md" ; "old" -> "<id>/views/<role>.md"
    """
    specs_root = os.path.join(root, "docs", "dev", "specs")
    spec_dir = os.path.join(specs_root, candidate)
    views_dir = os.path.join(spec_dir, "views")
    os.makedirs(views_dir, exist_ok=True)
    roles = ["architect", "ba", "dev", "orchestrator", "product-owner", "qa", "ui-specialist"]
    views = {}
    for r in roles:
        if write_views:
            _write(os.path.join(views_dir, r + ".md"), "# %s view\n" % r)
        if view_value_style == "old":
            views[r] = "%s/views/%s.md" % (candidate, r)
        else:
            views[r] = "views/%s.md" % r
    if write_manifest:
        manifest = {
            "schema_version": schema_version,
            "spec_id": candidate,
            "monolith_path": monolith_path_override if monolith_path_override is not None else monolith_rel,
            "views": views,
        }
        if record_hash:
            mono_abs = os.path.join(root, monolith_rel)
            if os.path.exists(mono_abs):
                manifest["sha256"] = _sha256(mono_abs)
        _write(os.path.join(views_dir, "manifest.json"), json.dumps(manifest, indent=2))
    if write_marker:
        _write(os.path.join(spec_dir, ".split-complete"), "split done\n")
        # make marker NOT stale: marker mtime >= monolith mtime
        mono_abs = os.path.join(root, monolith_rel)
        if os.path.exists(mono_abs):
            t = os.path.getmtime(mono_abs) + 5
            os.utime(os.path.join(spec_dir, ".split-complete"), (t, t))
    return spec_dir, views_dir


def _make_monolith(root, stem):
    rel = os.path.join("docs", "dev", "specs", stem + ".md")
    _write(os.path.join(root, rel), "# monolith %s\n\nSection 7 design.\n" % stem)
    return rel


def _run(spec_rel, project_dir):
    proc = subprocess.run(
        [sys.executable, RESOLVER, "--spec-path", spec_rel, "--project-dir", project_dir],
        capture_output=True, text=True,
    )
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        out = {"_raw": proc.stdout}
    return proc.returncode, out, proc.stderr


# --------------------------------------------------------------------------- #
# Case 1: de-prefixed new spec -> artifact_id == <ts>, views_available, exit 0
# --------------------------------------------------------------------------- #
def test_case01_deprefixed_new_spec():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260529-212341")
        _make_split(root, "20260529-212341", rel, view_value_style="new")
        code, out, _ = _run(rel, root)
        assert code == EXIT_OK, out
        assert out["artifact_id"] == "20260529-212341", out
        assert out["views_available"] is True, out


# --------------------------------------------------------------------------- #
# Case 2: old prefixed spec -> artifact_id == spec-<ts>, exit 0
# --------------------------------------------------------------------------- #
def test_case02_old_prefixed_spec():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260505-221501")
        _make_split(root, "spec-20260505-221501", rel, view_value_style="old")
        code, out, _ = _run(rel, root)
        assert code == EXIT_OK, out
        assert out["artifact_id"] == "spec-20260505-221501", out
        assert out["views_available"] is True, out


# --------------------------------------------------------------------------- #
# Case 3: legacy no-view spec -> views_available False, exit 0 (ABSENT)
# --------------------------------------------------------------------------- #
def test_case03_legacy_no_views():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260412-141227")
        code, out, _ = _run(rel, root)
        assert code == EXIT_OK, out
        assert out["views_available"] is False, out
        assert out["artifact_id"] == "20260412-141227", out


# --------------------------------------------------------------------------- #
# Case 4: two PRESENT-AND-VALID for one monolith -> fail loud (ambiguous)
# --------------------------------------------------------------------------- #
def test_case04_ambiguous_two_valid():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260601-000000")
        _make_split(root, "20260601-000000", rel, view_value_style="new")
        _make_split(root, "spec-20260601-000000", rel, view_value_style="old")
        code, out, err = _run(rel, root)
        assert code == EXIT_AMBIGUOUS, (out, err)
        assert out.get("error") == "ambiguous", out


# --------------------------------------------------------------------------- #
# Case 5: manifest.monolith_path -> different monolith -> fail loud
# --------------------------------------------------------------------------- #
def test_case05_monolith_path_mismatch():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260602-000000")
        other = _make_monolith(root, "spec-OTHER-monolith")
        _make_split(root, "20260602-000000", rel, view_value_style="new",
                    monolith_path_override=other)
        code, out, err = _run(rel, root)
        assert code == EXIT_INVALID, (out, err)
        assert "DIFFERENT monolith" in (out.get("failed_predicate") or ""), out


# --------------------------------------------------------------------------- #
# Case 6: /spec finalizer resolved path == /dev consumer resolved path
# --------------------------------------------------------------------------- #
def test_case06_producer_consumer_agree():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260603-000000")
        _make_split(root, "20260603-000000", rel, view_value_style="new")
        # producer passes absolute, consumer passes relative -> must agree
        code_a, out_a, _ = _run(os.path.join(root, rel), root)
        code_b, out_b, _ = _run(rel, root)
        assert code_a == EXIT_OK and code_b == EXIT_OK
        for k in ("artifact_id", "manifest_path", "split_marker", "cp_dir", "views_available"):
            assert out_a[k] == out_b[k], (k, out_a[k], out_b[k])


# --------------------------------------------------------------------------- #
# Case 7: PRESENT-BUT-INVALID manifest -> fail loud (NOT silent monolith)
# --------------------------------------------------------------------------- #
def test_case07a_malformed_json():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260604-000000")
        spec_dir, views_dir = _make_split(root, "20260604-000000", rel)
        _write(os.path.join(views_dir, "manifest.json"), "{ not valid json ]")
        code, out, _ = _run(rel, root)
        assert code == EXIT_INVALID, out
        assert out["state_per_candidate"]["20260604-000000"] == "PRESENT_BUT_INVALID"


def test_case07b_wrong_schema_version():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260605-000000")
        _make_split(root, "20260605-000000", rel, schema_version=2)
        code, out, _ = _run(rel, root)
        assert code == EXIT_INVALID, out
        assert "schema_version" in (out.get("failed_predicate") or "")


def test_case07c_split_complete_missing_while_manifest_present():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260606-000000")
        _make_split(root, "20260606-000000", rel, write_marker=False)
        code, out, _ = _run(rel, root)
        assert code == EXIT_INVALID, out
        assert ".split-complete" in (out.get("failed_predicate") or "")


# --------------------------------------------------------------------------- #
# Case 8: relative-vs-absolute canonicalization + symlink (no false mismatch/match)
# --------------------------------------------------------------------------- #
def test_case08a_relative_manifest_path_both_caller_directions():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260607-000000")
        # manifest.monolith_path is RELATIVE (default)
        _make_split(root, "20260607-000000", rel, view_value_style="new")
        # caller passes ABSOLUTE
        code_abs, out_abs, _ = _run(os.path.join(root, rel), root)
        # caller passes RELATIVE
        code_rel, out_rel, _ = _run(rel, root)
        assert code_abs == EXIT_OK and code_rel == EXIT_OK, (out_abs, out_rel)
        assert out_abs["artifact_id"] == out_rel["artifact_id"] == "20260607-000000"
        assert out_abs["views_available"] and out_rel["views_available"]


def test_case08b_symlinked_monolith_resolves_via_realpath():
    with tempfile.TemporaryDirectory() as root:
        # real monolith at a different on-disk name; manifest + caller use a symlink
        real_rel = _make_monolith(root, "spec-REAL-target")
        specs = os.path.join(root, "docs", "dev", "specs")
        link_rel = os.path.join("docs", "dev", "specs", "spec-20260608-000000.md")
        os.symlink(os.path.join(root, real_rel), os.path.join(root, link_rel))
        # manifest.monolith_path points at the symlink path; samefile must still match
        _make_split(root, "20260608-000000", link_rel, view_value_style="new")
        code, out, err = _run(link_rel, root)
        assert code == EXIT_OK, (out, err)
        assert out["views_available"] is True, out


# --------------------------------------------------------------------------- #
# Case 9: orphan cp-state under non-selected candidate does NOT trigger ambiguity
# --------------------------------------------------------------------------- #
def test_case09_orphan_cpstate_not_evidence():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260529-212341")
        _make_split(root, "20260529-212341", rel, view_value_style="new")
        # plant an orphan prefixed cp-state (NOT artifact evidence)
        cp = os.path.join(root, ".claude", "specs", "spec-20260529-212341")
        _write(os.path.join(cp, "cp-state-ba.json"), "{}")
        code, out, _ = _run(rel, root)
        assert code == EXIT_OK, out
        assert out["artifact_id"] == "20260529-212341", out
        assert out["views_available"] is True, out


# --------------------------------------------------------------------------- #
# Case 10: static lint detects planted inline derivation; clean files pass
# --------------------------------------------------------------------------- #
def test_case10a_lint_detects_planted_inline_derivation():
    with tempfile.TemporaryDirectory() as root:
        bad = os.path.join(root, "commands", "evil.md")
        _write(bad, "Compute SPEC_ID=$(basename \"$SPEC_PATH\" .md) then read docs/dev/specs/$SPEC_ID/views/manifest.json\n")
        proc = subprocess.run([sys.executable, LINT, "--paths", bad],
                              capture_output=True, text=True)
        assert proc.returncode != 0, proc.stdout + proc.stderr


def test_case10b_lint_passes_clean_command_files():
    # the live, post-fix command files must pass the lint
    targets = [
        os.path.join(DOT_CLAUDE, "commands", "dev.md"),
        os.path.join(DOT_CLAUDE, "commands", "dev-command.md"),
        os.path.join(DOT_CLAUDE, "commands", "dev-overnight.md"),
        os.path.join(DOT_CLAUDE, "commands", "close.md"),
        os.path.join(DOT_CLAUDE, "commands", "spec.md"),
    ]
    targets = [t for t in targets if os.path.isfile(t)]
    proc = subprocess.run([sys.executable, LINT, "--paths"] + targets,
                          capture_output=True, text=True)
    assert proc.returncode == 0, "lint flagged clean command files:\n" + proc.stdout + proc.stderr


# --------------------------------------------------------------------------- #
# Case 11: partial/broken artifact set is PRESENT-BUT-INVALID, not ABSENT
# --------------------------------------------------------------------------- #
def test_case11a_empty_views_dir():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260609-000000")
        os.makedirs(os.path.join(root, "docs", "dev", "specs", "20260609-000000", "views"))
        code, out, _ = _run(rel, root)
        assert code == EXIT_INVALID, out


def test_case11b_split_complete_without_views():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260610-000000")
        sd = os.path.join(root, "docs", "dev", "specs", "20260610-000000")
        os.makedirs(sd)
        _write(os.path.join(sd, ".split-complete"), "x\n")
        code, out, _ = _run(rel, root)
        assert code == EXIT_INVALID, out


def test_case11c_manifest_without_split_complete():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260611-000000")
        _make_split(root, "20260611-000000", rel, write_marker=False)
        code, out, _ = _run(rel, root)
        assert code == EXIT_INVALID, out


def test_case11d_dangling_symlink_at_manifest():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260612-000000")
        vd = os.path.join(root, "docs", "dev", "specs", "20260612-000000", "views")
        os.makedirs(vd)
        # dangling symlink at manifest.json -> must be detected as evidence (lexists)
        os.symlink(os.path.join(root, "nonexistent-target.json"),
                   os.path.join(vd, "manifest.json"))
        code, out, _ = _run(rel, root)
        assert code == EXIT_INVALID, out
        assert out["state_per_candidate"]["20260612-000000"] == "PRESENT_BUT_INVALID", out


def test_case11d_dangling_symlink_at_marker():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260613-000000")
        sd = os.path.join(root, "docs", "dev", "specs", "20260613-000000")
        os.makedirs(sd)
        os.symlink(os.path.join(root, "nope.marker"), os.path.join(sd, ".split-complete"))
        code, out, _ = _run(rel, root)
        assert code == EXIT_INVALID, out


# --------------------------------------------------------------------------- #
# Case 12: candidate derivation strips EXACTLY ONE leading spec- from stem only
# --------------------------------------------------------------------------- #
def test_case12_over_strip_guard():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-spec-foo")
        code, out, _ = _run(rel, root)
        assert out["candidates"] == ["spec-foo", "spec-spec-foo"], out
        # no views anywhere -> ABSENT/monolith, exit 0
        assert code == EXIT_OK, out


def test_case12_no_path_component_strip():
    # a monolith whose dir path contains 'spec-' must not have the PATH stripped,
    # only the stem.
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260614-000000")
        code, out, _ = _run(rel, root)
        assert out["raw_id"] == "spec-20260614-000000", out
        assert out["candidates"][0] == "20260614-000000", out


# --------------------------------------------------------------------------- #
# codex-hardening cases (issue 1: loose view path; issue 2: dict view entries)
# --------------------------------------------------------------------------- #
def test_codex1_view_path_outside_views_dir_is_invalid():
    # a manifest view path pointing OUTSIDE views/ (absolute or escaping) must NOT
    # falsely validate even if a same-basename file exists under views/.
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260620-000000")
        spec_dir, views_dir = _make_split(root, "20260620-000000", rel)
        _write(os.path.join(root, "external", "dev.md"), "external\n")
        manifest = {
            "schema_version": 1, "spec_id": "20260620-000000",
            "monolith_path": rel,
            "views": {"dev": "../../../../external/dev.md"},
        }
        _write(os.path.join(views_dir, "manifest.json"), json.dumps(manifest))
        code, out, _ = _run(rel, root)
        assert code == EXIT_INVALID, out


def test_codex2_dict_view_entries_accepted():
    # old schema_version==1 manifests may store dict view entries; they must still
    # validate (else old prefixed specs regress).
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260621-000000")
        spec_dir, views_dir = _make_split(root, "20260621-000000", rel, write_manifest=False)
        manifest = {
            "schema_version": 1, "spec_id": "20260621-000000",
            "monolith_path": rel,
            "views": {
                "dev": {"file": "views/dev.md", "line_count": 12},
                "qa": {"line_count": 5},   # metadata-only -> infer views/qa.md
            },
        }
        _write(os.path.join(views_dir, "manifest.json"), json.dumps(manifest))
        # ensure marker not stale
        t = os.path.getmtime(os.path.join(root, rel)) + 5
        os.utime(os.path.join(spec_dir, ".split-complete"), (t, t))
        code, out, _ = _run(rel, root)
        assert code == EXIT_OK, out
        assert out["views_available"] is True, out


# --------------------------------------------------------------------------- #
# hash-aware staleness (strengthens, does not weaken, the mtime guard)
# --------------------------------------------------------------------------- #
def test_hashfresh_matching_hash_accepts_despite_newer_mtime():
    # manifest records the monolith sha256; even if the monolith mtime is NEWER
    # than the marker (no-op touch / git-checkout / auto-checkpoint artifact),
    # a MATCHING hash proves freshness -> PRESENT-AND-VALID, exit 0.
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260630-000000")
        spec_dir, _ = _make_split(root, "20260630-000000", rel, record_hash=True)
        # force monolith mtime NEWER than marker (would be "stale" under pure mtime)
        marker = os.path.join(spec_dir, ".split-complete")
        mono = os.path.join(root, rel)
        t_marker = os.path.getmtime(marker)
        os.utime(mono, (t_marker + 100, t_marker + 100))
        code, out, _ = _run(rel, root)
        assert code == EXIT_OK, out
        assert out["views_available"] is True, out


def test_hashstale_mismatched_hash_fails_loud():
    # manifest records a sha256 that does NOT match the current monolith content
    # -> genuinely stale -> PRESENT-BUT-INVALID, fail loud.
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260631-000000")
        spec_dir, views_dir = _make_split(root, "20260631-000000", rel, write_manifest=False)
        manifest = {
            "schema_version": 1, "spec_id": "20260631-000000",
            "monolith_path": rel, "views": {"dev": "views/dev.md"},
            "sha256": "0" * 64,   # deliberately wrong
        }
        _write(os.path.join(views_dir, "manifest.json"), json.dumps(manifest))
        code, out, _ = _run(rel, root)
        assert code == EXIT_INVALID, out
        assert "stale" in (out.get("failed_predicate") or ""), out


def test_no_hash_falls_back_to_mtime_guard():
    # when no hash is recorded, the original mtime staleness guard still applies.
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260632-000000")
        spec_dir, _ = _make_split(root, "20260632-000000", rel)  # record_hash=False
        marker = os.path.join(spec_dir, ".split-complete")
        mono = os.path.join(root, rel)
        # monolith NEWER than marker, no hash -> mtime guard fires -> stale
        t_marker = os.path.getmtime(marker)
        os.utime(mono, (t_marker + 100, t_marker + 100))
        code, out, _ = _run(rel, root)
        assert code == EXIT_INVALID, out
        assert "stale" in (out.get("failed_predicate") or ""), out


# --------------------------------------------------------------------------- #
# F-QA-1 (task 20260530-092123 R2): the M9 lint must catch the LOWERCASE
# parameter-expansion inline derivation (${spec_path##*/} / %.md / #spec-) that
# slipped past the original uppercase-only patterns at commands/spec.md:238.
# --------------------------------------------------------------------------- #
def test_fqa1_lint_detects_lowercase_spec_path_param_expansion():
    with tempfile.TemporaryDirectory() as root:
        bad = os.path.join(root, "commands", "evil-lower.md")
        # the exact shape that was at commands/spec.md:238
        _write(bad,
               'EXPECT_ID="${spec_path##*/}"; EXPECT_ID="${EXPECT_ID%.md}"; '
               'EXPECT_ID="${EXPECT_ID#spec-}"  # de-prefixed\n')
        proc = subprocess.run([sys.executable, LINT, "--paths", bad],
                              capture_output=True, text=True)
        assert proc.returncode != 0, (
            "lint MISSED the lowercase ${spec_path##*/} inline derivation:\n"
            + proc.stdout + proc.stderr)


def test_fqa1_lint_detects_lowercase_basename_and_strip_forms():
    # each lowercase form independently flagged
    with tempfile.TemporaryDirectory() as root:
        for i, line in enumerate([
            'id=$(basename "$spec_path" .md)\n',
            'id="${spec_path%.md}"\n',
            'id="${spec_id#spec-}"\n',
        ]):
            bad = os.path.join(root, "commands", "evil%d.md" % i)
            _write(bad, line)
            proc = subprocess.run([sys.executable, LINT, "--paths", bad],
                                  capture_output=True, text=True)
            assert proc.returncode != 0, "lint missed lowercase form %r:\n%s%s" % (
                line, proc.stdout, proc.stderr)


def test_fqa1_lint_passes_resolver_consumption_line():
    # consuming candidates[0] from the resolver JSON is the CORRECT pattern and
    # must NOT be flagged (it is the post-fix spec.md:238 form).
    with tempfile.TemporaryDirectory() as root:
        good = os.path.join(root, "commands", "good.md")
        _write(good, 'EXPECT_ID=$(jq -r \'.candidates[0]\' <<<"$RESOLVED_JSON")\n')
        proc = subprocess.run([sys.executable, LINT, "--paths", good],
                              capture_output=True, text=True)
        assert proc.returncode == 0, (
            "lint wrongly flagged the resolver-consumption line:\n"
            + proc.stdout + proc.stderr)


# --------------------------------------------------------------------------- #
# F-QA-2 (task 20260530-092123 R2): when BOTH sha256 and monolith_sha256 are
# present, a matching sha256 must NOT mask a MISMATCHING monolith_sha256 — both
# must equal the current monolith hash, else PRESENT-BUT-INVALID (stale).
# --------------------------------------------------------------------------- #
def test_fqa2_matching_sha256_does_not_mask_mismatching_monolith_sha256():
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260640-000000")
        _, views_dir = _make_split(root, "20260640-000000", rel, write_manifest=False)
        mono_abs = os.path.join(root, rel)
        good = _sha256(mono_abs)               # matches current monolith
        manifest = {
            "schema_version": 1, "spec_id": "20260640-000000",
            "monolith_path": rel, "views": {"dev": "views/dev.md"},
            "sha256": good,            # MATCHES (would short-circuit accept)
            "monolith_sha256": "d" * 64,  # MISMATCHES current monolith
        }
        _write(os.path.join(views_dir, "manifest.json"), json.dumps(manifest))
        code, out, _ = _run(rel, root)
        assert code == EXIT_INVALID, (
            "matching sha256 masked the mismatching monolith_sha256: %s" % out)
        assert out["state_per_candidate"]["20260640-000000"] == "PRESENT_BUT_INVALID", out
        assert "stale" in (out.get("failed_predicate") or ""), out


def test_fqa2_both_hashes_present_and_matching_is_valid():
    # control: both hash fields present AND matching -> PRESENT-AND-VALID exit 0
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260641-000000")
        _, views_dir = _make_split(root, "20260641-000000", rel, write_manifest=False)
        good = _sha256(os.path.join(root, rel))
        manifest = {
            "schema_version": 1, "spec_id": "20260641-000000",
            "monolith_path": rel, "views": {"dev": "views/dev.md"},
            "sha256": good, "monolith_sha256": good,
        }
        _write(os.path.join(views_dir, "manifest.json"), json.dumps(manifest))
        code, out, _ = _run(rel, root)
        assert code == EXIT_OK, out
        assert out["views_available"] is True, out


def test_fqa2_present_but_malformed_hash_fails_loud():
    # a present hash field that is not 64-hex cannot validate freshness -> stale
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260642-000000")
        _, views_dir = _make_split(root, "20260642-000000", rel, write_manifest=False)
        manifest = {
            "schema_version": 1, "spec_id": "20260642-000000",
            "monolith_path": rel, "views": {"dev": "views/dev.md"},
            "monolith_sha256": "not-a-real-hash",
        }
        _write(os.path.join(views_dir, "manifest.json"), json.dumps(manifest))
        code, out, _ = _run(rel, root)
        assert code == EXIT_INVALID, out


def test_fqa2_explicit_null_hash_does_not_fall_through_to_mtime():
    # codex F-QA-2 follow-up: a manifest that EXPLICITLY carries "sha256": null is
    # asserting a hash it failed to record — it must NOT silently fall through to the
    # mtime guard (re-opening the short-circuit). Key PRESENCE (not non-null value)
    # marks the field recorded; the 64-hex check then rejects null as malformed.
    with tempfile.TemporaryDirectory() as root:
        rel = _make_monolith(root, "spec-20260643-000000")
        spec_dir, views_dir = _make_split(root, "20260643-000000", rel, write_manifest=False)
        # marker mtime NEWER than monolith so a pure-mtime fallback WOULD pass
        marker = os.path.join(spec_dir, ".split-complete")
        mono = os.path.join(root, rel)
        t = os.path.getmtime(mono) + 100
        os.utime(marker, (t, t))
        manifest = {
            "schema_version": 1, "spec_id": "20260643-000000",
            "monolith_path": rel, "views": {"dev": "views/dev.md"},
            "sha256": None,   # explicitly present-but-null
        }
        _write(os.path.join(views_dir, "manifest.json"), json.dumps(manifest))
        code, out, _ = _run(rel, root)
        assert code == EXIT_INVALID, out


# --------------------------------------------------------------------------- #
# codex F-QA-1 follow-up: lint must catch the remaining lowercase forms AND must
# NOT honor the allow-marker on a CODE line (only comment-only lines).
# --------------------------------------------------------------------------- #
def test_fqa1_lint_catches_remaining_lowercase_forms():
    forms = [
        'id="${spec_id##spec-}"\n',          # strip prefix off spec_id directly
        'id="${spec_path%%.md}"\n',          # double-% suffix strip
        'id=$(basename -- "$spec_path" .md)\n',  # basename with option token
        'id="${spec_path#spec-}"\n',         # single-# prefix strip off spec_path
    ]
    with tempfile.TemporaryDirectory() as root:
        for i, line in enumerate(forms):
            bad = os.path.join(root, "commands", "ev%d.md" % i)
            _write(bad, line)
            proc = subprocess.run([sys.executable, LINT, "--paths", bad],
                                  capture_output=True, text=True)
            assert proc.returncode != 0, "lint missed %r:\n%s%s" % (
                line, proc.stdout, proc.stderr)


def test_fqa1_lint_allow_marker_does_not_excuse_code_line():
    # a REAL inline derivation on a CODE line cannot be hidden by appending the marker
    with tempfile.TemporaryDirectory() as root:
        bad = os.path.join(root, "commands", "sneaky.md")
        _write(bad, 'EXPECT_ID="${spec_path##*/}"  # spec-id-lint: allow\n')
        proc = subprocess.run([sys.executable, LINT, "--paths", bad],
                              capture_output=True, text=True)
        assert proc.returncode != 0, (
            "allow-marker wrongly excused a code-line derivation:\n"
            + proc.stdout + proc.stderr)


def test_fqa1_lint_allow_marker_honored_on_comment_only_line():
    # the legit use: a comment-only counter-example carrying the marker passes
    with tempfile.TemporaryDirectory() as root:
        ok = os.path.join(root, "commands", "doc.md")
        _write(ok, '# never write "${spec_path%.md}" inline  # spec-id-lint: allow\n')
        proc = subprocess.run([sys.executable, LINT, "--paths", ok],
                              capture_output=True, text=True)
        assert proc.returncode == 0, (
            "allow-marker not honored on comment-only line:\n"
            + proc.stdout + proc.stderr)


# --------------------------------------------------------------------------- #
# self-contained runner
# --------------------------------------------------------------------------- #
def _run_all():
    fns = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    passed, failed = 0, 0
    for name, fn in fns:
        try:
            fn()
            passed += 1
            print("PASS %s" % name)
        except AssertionError as exc:
            failed += 1
            print("FAIL %s: %s" % (name, exc))
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("ERROR %s: %s" % (name, exc))
    print("\n%d passed, %d failed (of %d)" % (passed, failed, len(fns)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
