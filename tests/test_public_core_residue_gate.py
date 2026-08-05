"""Behavioural gate tests for scripts/check-public-core.sh residue sections.

These are the discriminating controls for the "Make CI FAIL (not advisory) on
/root, author-home paths, the tmpfs workspace path, and other personal residue
in public-core" requirement:

  * the maintainer workspace/tmpfs marker HARD-FAILS (it was advisory-only);
  * generic author-home classes (/root/, /home/<user>/, /Users/<User>/) hard-fail;
  * the exemption mechanism is a SET, not an aggregate count — the delete-one /
    add-one constant-count scenario must still fail;
  * an exemption CLASS is re-derived from the source structure, so relabelling an
    operational literal as a comment does not buy an exemption;
  * stale / dangling allowlist entries are reported.

Every scenario runs against an isolated throwaway copy of the tracked tree; the
real working tree is never mutated. A baseline exit-0 control runs first in each
scenario so a later non-zero exit is causally attributable to the injection.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CHECKER = "scripts/check-public-core.sh"
ALLOWLIST = "policies/public-core-residue-allowlist.v1.json"
WS_MARKER = "/dev/shm/" + "dev-workspace/dot-claude"  # split so this file is not itself residue


def _tracked_files() -> list[str]:
    """Tracked files PLUS untracked-but-not-ignored ones.

    The fixture must mirror the tree as it would be COMMITTED, not merely what is
    already in the index: a newly added, not-yet-staged file (the residue
    allowlist itself, on the cycle that introduces it) is part of the state the
    gate has to run against.
    """
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files"],
                             capture_output=True, text=True).stdout.split()
    untracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "--others", "--exclude-standard"],
                               capture_output=True, text=True).stdout.split()
    return sorted(set(tracked) | set(untracked))


@pytest.fixture(scope="module")
def pristine(tmp_path_factory) -> Path:
    """An isolated git repo holding the current tracked working-tree content."""
    dest = tmp_path_factory.mktemp("pc-pristine")
    for rel in _tracked_files():
        src = REPO / rel
        if not src.is_file():
            continue
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / rel)
    subprocess.run(["git", "-C", str(dest), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(dest), "add", "-A"], check=True)
    return dest


def _copy(pristine: Path, tmp_path: Path) -> Path:
    """Hardlink-farm copy into a pytest-MANAGED dir.

    Hardlinks keep each case at inode cost rather than a full tree copy, and
    pytest prunes its own basetemps, so a full parametrized run does not fill the
    scratch filesystem. `_mutable()` breaks the link before any file is written,
    so a case can never write through into the shared pristine tree.
    """
    dest = tmp_path / "r"
    shutil.copytree(pristine, dest, symlinks=True, copy_function=os.link)
    _mutable(dest / ".git" / "index")          # git rewrites this during staging
    return dest


def _mutable(path: Path) -> Path:
    """Break the hardlink so writing to `path` cannot affect the pristine copy."""
    if path.is_file() and path.stat().st_nlink > 1:
        data = path.read_bytes()
        path.unlink()
        path.write_bytes(data)
    return path


def _append(path: Path, text: str) -> None:
    _mutable(path)
    with path.open("a", encoding="utf8") as fh:
        fh.write(text)


def _write(path: Path, text: str) -> None:
    _mutable(path)
    path.write_text(text, encoding="utf8")


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", CHECKER, *args], cwd=root, capture_output=True, text=True)


def _stage(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)


def _ledger_public_core(root: Path) -> list[str]:
    txt = (root / "PUBLIC-CORE.md").read_text(encoding="utf8")
    blk = txt.split("<!-- BEGIN:public-core-manifest -->")[1].split("<!-- END:public-core-manifest -->")[0]
    out = []
    for line in blk.splitlines():
        if not line.startswith("|"):
            continue
        cells = line.split("`")
        if len(cells) >= 4 and cells[1] and cells[3] == "public-core":
            out.append(cells[1].rstrip("/"))
    return sorted(set(out))


def _public_core_files(root: Path) -> set[str]:
    """Tracked files in the ledger-derived public-core set — the CHECKOUT-mode scan scope.

    The allowlist deliberately spans TWO scopes: checkout mode scans public-core,
    archive mode scans the wider release-membership set. A control that mutates an
    allowlist entry must therefore pick an entry THIS mode actually looks at —
    mutating an archive-only entry (PUBLIC-CORE.md is `shared/infra`) exercises
    nothing and reads as a false gate failure.
    """
    prefixes = _ledger_public_core(root)
    return set(subprocess.run(["git", "-C", str(root), "ls-files", "--", *prefixes],
                              capture_output=True, text=True).stdout.split())


def _in_scope_entries(root: Path) -> list[dict]:
    """Allowlist entries whose path is inside the checkout-mode scan scope."""
    scope = _public_core_files(root)
    doc = json.loads((root / ALLOWLIST).read_text(encoding="utf8"))
    return [e for e in doc["entries"] if e["path"] in scope]


def _victim(root: Path, prefix: str) -> Path:
    """An EXISTING already-classified public-core file under `prefix`.

    Injecting into an existing classified file is required: creating a NEW
    top-level path would make section 2 hard-fail for an unrelated reason and
    the test would pass even against the un-promoted checker.
    """
    target = root / prefix
    if target.is_file():
        return target
    for cand in sorted(target.rglob("*.md")) + sorted(target.rglob("*")):
        if cand.is_file() and cand.stat().st_size > 0:
            return cand
    pytest.skip(f"no file under {prefix}")


def test_baseline_is_clean(pristine):
    """Causal control: the unmodified isolated copy exits 0."""
    r = _run(pristine)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("prefix", _ledger_public_core(REPO))
def test_workspace_marker_hard_fails_per_ledger_prefix(pristine, tmp_path, prefix):
    """AC5: the tmpfs marker hard-fails, in EVERY public-core ledger prefix."""
    root = _copy(pristine, tmp_path)
    victim = _victim(root, prefix)
    assert _run(root).returncode == 0, "baseline control must be clean"
    marker_line = f"\n# injected marker {WS_MARKER}/x\n"
    _append(victim, marker_line)
    _stage(root)
    r = _run(root)
    assert r.returncode != 0, f"tmpfs marker not gated in {prefix}"
    rel = str(victim.relative_to(root))
    assert rel in r.stdout, "failure output must name the injected file"
    assert "workspace-path residue" in r.stdout, "failure must identify the marker class"
    _write(victim, victim.read_text(encoding="utf8").replace(marker_line, ""))
    _stage(root)
    assert _run(root).returncode == 0, "removing the injection must restore exit 0"


@pytest.mark.parametrize(
    "literal, label",
    [("/root/injected/leak", "root"),
     ("/home/authorname/injected/leak", "home"),
     ("/Users/AuthorName/injected/leak", "users")],
)
def test_each_author_home_class_hard_fails(pristine, tmp_path, literal, label):
    """AC6 b1/b2 + e: every DEFINED author-home class has its own control."""
    root = _copy(pristine, tmp_path)
    assert _run(root).returncode == 0
    _append(root / "agents" / "dev.md", f"\nInjected {label} residue: {literal}\n")
    _stage(root)
    r = _run(root)
    assert r.returncode != 0, f"{label} class not gated"
    assert "agents/dev.md" in r.stdout
    assert "un-allowlisted author-path residue" in r.stdout


def test_constant_count_replacement_still_fails(pristine, tmp_path):
    """AC6 c: THE discriminating test — delete one allowlisted occurrence and add
    one new occurrence elsewhere so the aggregate count is unchanged. A
    count-based ratchet exits 0 here; a set-based gate must exit non-zero."""
    root = _copy(pristine, tmp_path)
    assert _run(root).returncode == 0
    entries = json.loads((root / ALLOWLIST).read_text(encoding="utf8"))["entries"]
    doomed = next(e for e in entries if e["path"].endswith(".md"))
    victim = root / doomed["path"]
    lines = victim.read_text(encoding="utf8").splitlines(keepends=True)
    removed = None
    for i, line in enumerate(lines):
        if hashlib.sha256(line.rstrip("\n").encode()).hexdigest()[:16] == doomed["fingerprint"]:
            removed = lines.pop(i)
            break
    assert removed is not None, "could not locate the allowlisted line to delete"
    _write(victim, "".join(lines))
    # add exactly ONE new, unallowlisted occurrence elsewhere -> net count unchanged
    _append(root / "agents" / "qa.md", "\nSwapped-in residue: /root/somewhere/else\n")
    _stage(root)
    r = _run(root)
    assert r.returncode != 0, "constant-count swap escaped the gate (ratchet, not a set)"
    assert "un-allowlisted author-path residue" in r.stdout


def test_duplicate_of_allowlisted_identical_line_is_detected(pristine, tmp_path):
    """AC6 d: the key is a multiset (path, fingerprint, ordinal) — duplicating an
    already-allowlisted identical line must NOT inherit its exemption."""
    root = _copy(pristine, tmp_path)
    assert _run(root).returncode == 0
    entries = _in_scope_entries(root)
    for e in entries:
        if not e["path"].endswith(".md"):
            continue
        victim = root / e["path"]
        for line in victim.read_text(encoding="utf8").splitlines():
            if hashlib.sha256(line.encode()).hexdigest()[:16] == e["fingerprint"]:
                _append(victim, "\n" + line + "\n")
                _stage(root)
                r = _run(root)
                assert r.returncode != 0, "duplicated allowlisted line silently exempted"
                return
    pytest.skip("no markdown allowlist entry available")


def test_stale_and_dangling_allowlist_entries_are_reported(pristine, tmp_path):
    """AC6 d: a fingerprint that no longer matches, and a path that no longer
    exists, must each be reported rather than silently covering new content."""
    root = _copy(pristine, tmp_path)
    doc = json.loads((root / ALLOWLIST).read_text(encoding="utf8"))
    doc["entries"].append({"path": "agents/dev.md", "fingerprint": "0" * 16, "ordinal": 1,
                           "class": "comment_or_narrative_doc", "rationale": "synthetic stale entry"})
    doc["entries"].append({"path": "agents/does-not-exist.md", "fingerprint": "1" * 16, "ordinal": 1,
                           "class": "comment_or_narrative_doc", "rationale": "synthetic dangling entry"})
    _write(root / ALLOWLIST, json.dumps(doc, indent=2))
    _stage(root)
    r = _run(root)
    assert r.returncode != 0
    assert "STALE residue-allowlist entry" in r.stdout
    assert "path that no longer exists" in r.stdout


def test_operational_literal_cannot_be_relabelled_as_a_comment(pristine, tmp_path):
    """AC12: the class is re-derived from source STRUCTURE. Injecting a live code
    literal and hand-labelling it `comment_or_narrative_doc` must still fail —
    otherwise the classification audit is circular."""
    root = _copy(pristine, tmp_path)
    assert _run(root).returncode == 0
    line = 'SNEAKY_OPERATIONAL_PATH = "/root/.claude/secret"'
    _append(root / "hooks" / "lib" / "claude_home.py", "\n" + line + "\n")
    doc = json.loads((root / ALLOWLIST).read_text(encoding="utf8"))
    doc["entries"].append({
        "path": "hooks/lib/claude_home.py",
        "fingerprint": hashlib.sha256(line.encode()).hexdigest()[:16],
        "ordinal": 1,
        "class": "comment_or_narrative_doc",
        "rationale": "claimed to be narrative documentation",
    })
    _write(root / ALLOWLIST, json.dumps(doc, indent=2))
    _stage(root)
    r = _run(root)
    assert r.returncode != 0, "an operational literal bought an exemption by relabelling"
    assert "operational, NOT allowlistable" in r.stdout


def test_placeholder_rationale_is_rejected(pristine, tmp_path):
    """AC6 d: every entry needs a real per-entry rationale."""
    root = _copy(pristine, tmp_path)
    doc = json.loads((root / ALLOWLIST).read_text(encoding="utf8"))
    # Must be an entry this mode actually scans: the rationale is validated per
    # LIVE occurrence, so blanking an archive-only entry proves nothing here.
    scope = _public_core_files(root)
    victim = next(i for i, e in enumerate(doc["entries"]) if e["path"] in scope)
    doc["entries"][victim]["rationale"] = "TBD"
    _write(root / ALLOWLIST, json.dumps(doc, indent=2))
    _stage(root)
    r = _run(root)
    assert r.returncode != 0
    assert "no per-entry rationale" in r.stdout


@pytest.mark.parametrize("marker", ["git@github.com:" + "Yugoge", "/root/.claude" + ".bak", "/root/sync-" + "backup.sh"])
def test_preexisting_hard_markers_still_gate(pristine, tmp_path, marker):
    """AC6 e: the three pre-existing HARD_MARKERS must not be regressed by the
    new section — one behavioural control per marker."""
    root = _copy(pristine, tmp_path)
    assert _run(root).returncode == 0
    _append(root / "agents" / "dev.md", f"\nInjected hard marker {marker}\n")
    _stage(root)
    r = _run(root)
    assert r.returncode != 0, f"pre-existing hard marker {marker} regressed"
    assert "hard residue marker" in r.stdout


def test_scan_set_equals_full_ledger_public_core_set(pristine):
    """AC5: the detector's enumerated scan set EQUALS the ledger-derived
    public-core set — asserted as a set equality, not inferred from one hit."""
    prefixes = _ledger_public_core(pristine)
    expected = set(subprocess.run(["git", "-C", str(pristine), "ls-files", "--", *prefixes],
                                  capture_output=True, text=True).stdout.split())
    r = _run(pristine)
    scanned = int(r.stdout.split("residue audit:")[1].split("occurrence")[0].strip())
    # Every allowlist entry corresponds to a file the gate scans in SOME mode:
    # checkout mode scans public-core, archive mode scans the release-membership
    # set. An entry outside BOTH would grant an exemption nothing ever validates.
    doc = json.loads((pristine / ALLOWLIST).read_text(encoding="utf8"))
    membership = set(subprocess.run(
        ["python3", "scripts/lib/release_membership.py", "--from-git", "--root", ".",
         "--manifest", "release-membership.v1.json"],
        cwd=pristine, capture_output=True, text=True).stdout.split())
    assert {e["path"] for e in doc["entries"]} <= (expected | membership)
    # In THIS (checkout) mode, every scanned occurrence must be exempted and every
    # in-scope entry must be live — an exact 1:1, not merely "no failures".
    in_scope = [e for e in doc["entries"] if e["path"] in expected]
    assert scanned == len(in_scope), "scanned occurrences must equal the in-scope exempted set on a clean tree"


# ---------------------------------------------------------------------------
# Boundary-aware matching (backlog item 1) — AC-REL-1 / AC-REL-2 / AC-REL-3.
#
# The previous pattern anchored every alternative on a TRAILING "/", so it caught
# a home directory's DESCENDANTS but never the directory ROOT. These controls fail
# on that pattern: the exact-root half of the matrix exits 0 against it.
# ---------------------------------------------------------------------------

RESIDUE_MATRIX = [
    ("root",  'EXACT_ROOT="/root"',                     'DESC_ROOT="/root/.claude/x"'),
    ("home",  'EXACT_HOME="/home/authorname"',          'DESC_HOME="/home/authorname/x"'),
    ("users", 'EXACT_MAC="/Users/AuthorName"',          'DESC_MAC="/Users/AuthorName/x"'),
]


def _staged_tree(repo: Path, dest: Path) -> Path:
    """Stage the release-membership set exactly as release.yml does.

    shutil.copy2 mirrors `cp -p`: metadata-preserving and symlink-DEREFERENCING,
    which is why no symlink reaches the archive (see AC-REL-8).
    """
    dest.mkdir(parents=True, exist_ok=True)
    members = subprocess.run(
        ["python3", "scripts/lib/release_membership.py", "--from-git", "--root", ".",
         "--manifest", "release-membership.v1.json"],
        cwd=repo, capture_output=True, text=True).stdout.split()
    assert members, "release-membership resolved an empty path set"
    for rel in members:
        src = repo / rel
        if not src.is_file():
            continue
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / rel)
    return dest


@pytest.fixture(scope="module")
def staged(pristine, tmp_path_factory) -> Path:
    return _staged_tree(pristine, tmp_path_factory.mktemp("pc-staged") / "stage")


def _run_archive(repo: Path, stage: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", CHECKER, "--scan-root", str(stage),
         "--release-manifest", str(stage / "release-membership.v1.json")],
        cwd=repo, capture_output=True, text=True)


def _copy_stage(staged: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "stage"
    shutil.copytree(staged, dest, symlinks=True)
    return dest


@pytest.mark.parametrize("label, exact, descendant", RESIDUE_MATRIX)
@pytest.mark.parametrize("form", ["exact", "descendant"])
def test_author_home_root_and_descendant_gate_in_checkout_mode(
        pristine, tmp_path, label, exact, descendant, form):
    """AC-REL-1 (checkout limb): both the ROOT form and the DESCENDANT form of every
    author-home class hard-fail. The exact-root half is the half that used to pass."""
    root = _copy(pristine, tmp_path)
    assert _run(root).returncode == 0, "baseline control must be clean"
    literal = exact if form == "exact" else descendant
    _append(root / "agents" / "dev.md", f"\nInjected {label}/{form}: {literal}\n")
    _stage(root)
    r = _run(root)
    assert r.returncode != 0, f"{label}/{form} residue escaped the checkout gate"
    assert "agents/dev.md" in r.stdout, "failure must name the injected file"
    assert "un-allowlisted author-path residue" in r.stdout


@pytest.mark.parametrize("label, exact, descendant", RESIDUE_MATRIX)
@pytest.mark.parametrize("form", ["exact", "descendant"])
def test_author_home_root_and_descendant_gate_in_archive_mode(
        pristine, staged, tmp_path, label, exact, descendant, form):
    """AC-REL-1 (archive limb): the same matrix over an extracted staged tree.

    Exercised through the ARCHIVE path specifically — the prior cycle's archive-mode
    gap survived undetected because only the checkout path was ever exercised."""
    stage = _copy_stage(staged, tmp_path)
    assert _run_archive(pristine, stage).returncode == 0, "baseline control must be clean"
    literal = exact if form == "exact" else descendant
    victim = stage / "agents" / "dev.md"
    assert victim.is_file(), "agents/dev.md must be a release member"
    with victim.open("a", encoding="utf8") as fh:
        fh.write(f"\nInjected {label}/{form}: {literal}\n")
    r = _run_archive(pristine, stage)
    assert r.returncode != 0, f"{label}/{form} residue escaped the ARCHIVE gate"
    assert "agents/dev.md" in r.stdout


def test_clean_tree_is_green_in_both_modes(pristine, staged):
    """AC-REL-2: widening the pattern was landed by RESOLVING every newly surfaced
    occurrence, not by leaving the gate permanently red."""
    co = _run(pristine)
    assert co.returncode == 0, co.stdout + co.stderr
    assert "0 failure(s)" in co.stdout
    ar = _run_archive(pristine, staged)
    assert ar.returncode == 0, ar.stdout + ar.stderr
    assert "0 failure(s)" in ar.stdout


def test_operational_literal_stays_non_allowlistable(pristine, tmp_path):
    """AC-REL-3: a live author-home code literal fails BEFORE and AFTER an allowlist
    entry is added for its exact (path, fingerprint, ordinal) key.

    Without this, AC-REL-2 could have been satisfied by making everything
    allowlistable instead of by extending occurrence CLASSIFICATION."""
    root = _copy(pristine, tmp_path)
    assert _run(root).returncode == 0
    line = 'OPERATIONAL_AUTHOR_HOME = "/home/authorname"'
    _append(root / "hooks" / "lib" / "claude_home.py", "\n" + line + "\n")
    _stage(root)
    before = _run(root)
    assert before.returncode != 0, "operational literal was not gated before the entry"
    assert "operational, NOT allowlistable" in before.stdout
    doc = json.loads((root / ALLOWLIST).read_text(encoding="utf8"))
    doc["entries"].append({
        "path": "hooks/lib/claude_home.py",
        "fingerprint": hashlib.sha256(line.encode()).hexdigest()[:16],
        "ordinal": 1,
        "class": "system_path_constant_enumeration",
        "rationale": "claimed to be a protected-system-directory table element",
    })
    _write(root / ALLOWLIST, json.dumps(doc, indent=2))
    _stage(root)
    after = _run(root)
    assert after.returncode != 0, "an allowlist entry bought an operational exemption"
    assert "operational, NOT allowlistable" in after.stdout


def test_system_path_enumeration_class_cannot_launder_a_real_author_home(pristine, tmp_path):
    """AC-REL-3 corollary: the new structurally-derived class is bounded.

    A BARE top-level directory ("/root") inside a table of bare directories is a
    protected-root constant. A path carrying a user component ("/home/authorname")
    disqualifies the whole enumeration, so the occurrence stays operational."""
    root = _copy(pristine, tmp_path)
    assert _run(root).returncode == 0
    _append(root / "hooks" / "lib" / "claude_home.py",
            '\nSNEAKY_ROOTS = ("/", "/home/authorname", "/etc")\n')
    _stage(root)
    r = _run(root)
    assert r.returncode != 0, "a user-specific path was laundered as a system-dir table"
    assert "operational, NOT allowlistable" in r.stdout


def test_trailing_comment_does_not_launder_a_live_literal_on_the_same_line(pristine, tmp_path):
    """Occurrence-level, not line-level: one commented occurrence must never exempt a
    second, LIVE occurrence sharing the line (mirrors param_line_ok's discipline)."""
    root = _copy(pristine, tmp_path)
    assert _run(root).returncode == 0
    _append(root / "hooks" / "lib" / "claude_home.py",
            '\nLIVE = "/root/.claude/secret"  # documented default under /root\n')
    _stage(root)
    r = _run(root)
    assert r.returncode != 0, "a trailing comment exempted a live literal on the same line"
    assert "operational, NOT allowlistable" in r.stdout


# ---------------------------------------------------------------------------
# Archive-mode hard markers (backlog item 2) — AC-REL-4.
#
# The HARD_MARKERS loop used to sit AFTER the archive branch's `exit "$rc"`, so it
# was unreachable over a release artifact: every injection below exits 0 against
# that arrangement.
# ---------------------------------------------------------------------------

HARD_MARKERS = ["git@github.com:" + "Yugoge", "/root/.claude" + ".bak", "/root/sync-" + "backup.sh"]


@pytest.mark.parametrize("marker", HARD_MARKERS)
def test_hard_marker_in_a_non_exempt_archive_member_fails(pristine, staged, tmp_path, marker):
    """AC-REL-4 limb a: a maintainer identifier inside a released artifact is caught."""
    stage = _copy_stage(staged, tmp_path)
    assert _run_archive(pristine, stage).returncode == 0, "baseline control must be clean"
    victim = stage / "agents" / "dev.md"
    exempt = json.loads((stage / "release-membership.v1.json").read_text(encoding="utf8"))
    assert "agents/dev.md" not in exempt["hard_marker_exempt_paths"], "victim must be non-exempt"
    with victim.open("a", encoding="utf8") as fh:
        fh.write(f"\nInjected hard marker {marker}\n")
    r = _run_archive(pristine, stage)
    assert r.returncode != 0, f"hard marker {marker} shipped undetected in the archive"
    assert "hard residue marker in released archive" in r.stdout
    assert "agents/dev.md" in r.stdout


def test_unmodified_staged_tree_does_not_false_fail_on_legitimate_carriers(pristine, staged):
    """AC-REL-4 limb b (anti-vacuity): the two legitimate carriers must NOT fail.

    Without this, limb a could be satisfied by failing every release."""
    r = _run_archive(pristine, staged)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no un-exempted hard residue markers" in r.stdout


def test_emptying_the_hard_marker_exemption_turns_the_archive_gate_red(pristine, staged, tmp_path):
    """AC-REL-4 limb c: the exemption is load-bearing, not decorative."""
    stage = _copy_stage(staged, tmp_path)
    assert _run_archive(pristine, stage).returncode == 0
    manifest = stage / "release-membership.v1.json"
    doc = json.loads(manifest.read_text(encoding="utf8"))
    doc["hard_marker_exempt_paths"] = []
    manifest.write_text(json.dumps(doc, indent=2), encoding="utf8")
    r = _run_archive(pristine, stage)
    assert r.returncode != 0, "emptying the exemption did not turn the gate red"
    assert "hard residue marker in released archive" in r.stdout


def test_hard_marker_exemption_is_its_own_key_with_its_own_rationale(pristine):
    """AC-REL-4 limb d: the consulted key is hard-marker-scoped, and its rationale is
    not a copy of the workspace-marker rationale (which describes another class)."""
    doc = json.loads((pristine / "release-membership.v1.json").read_text(encoding="utf8"))
    assert "hard_marker_exempt_paths" in doc, "hard markers need their own exemption key"
    assert "hard_marker_exempt_rationale" in doc
    checker = (pristine / CHECKER).read_text(encoding="utf8")
    assert "hard_marker_exempt_paths" in checker, "the gate must read the hard-marker key"
    ws_texts = set(doc["workspace_marker_exempt_rationale"].values())
    for path, text in doc["hard_marker_exempt_rationale"].items():
        assert text.strip(), f"{path} exemption carries no rationale"
        assert text not in ws_texts, (
            f"{path}: hard-marker rationale is byte-identical to a workspace-marker "
            "rationale — an exemption whose justification describes a different class")
    for path in doc["hard_marker_exempt_paths"]:
        assert path in doc["hard_marker_exempt_rationale"], f"{path} exempted without a rationale"


# ---------------------------------------------------------------------------
# Symlink comment (backlog item 7) — AC-REL-8.
# ---------------------------------------------------------------------------

def test_symlink_comment_states_what_actually_happens(pristine):
    """AC-REL-8: the false load-bearing claim is gone, the replacement states the
    measured behaviour, and `-type l` is RETAINED as defence in depth."""
    src = (pristine / CHECKER).read_text(encoding="utf8")
    assert "would drop it from the ACTUAL set" not in src, \
        "the false `-type f` load-bearing claim is still present"
    assert "-type f -o -type l" in src, \
        "the -type l predicate must be retained as defence in depth"
    assert "cp -p" in src and "DEREFERENCE" in src.upper(), \
        "the comment must state that the staging copy dereferences symlinks"


def test_staging_copy_dereferences_symlinks(pristine, tmp_path):
    """AC-REL-8 (OA-3 closed empirically): `cp -p` produces a regular file, so no
    symlink reaches tar and `-type l` cannot be the load-bearing predicate."""
    src_dir = tmp_path / "src"
    (src_dir / "templates").mkdir(parents=True)
    (src_dir / "real.md").write_text("body\n", encoding="utf8")
    link = src_dir / "templates" / "spec.md"
    link.symlink_to(Path("..") / "real.md")
    assert link.is_symlink(), "fixture must start as a symlink"
    out = tmp_path / "stage" / "templates" / "spec.md"
    out.parent.mkdir(parents=True)
    subprocess.run(["cp", "-p", str(link), str(out)], check=True)
    assert out.is_file() and not out.is_symlink(), "cp -p did not dereference the symlink"
    found = subprocess.run(["find", ".", "-type", "l"], cwd=tmp_path / "stage",
                           capture_output=True, text=True).stdout.split()
    assert found == [], "a symlink survived staging; the comment's premise would change"
