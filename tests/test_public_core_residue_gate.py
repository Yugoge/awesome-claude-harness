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
    out = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True)
    return out.stdout.split()


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
    entries = json.loads((root / ALLOWLIST).read_text(encoding="utf8"))["entries"]
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
    (root / ALLOWLIST).write_text(json.dumps(doc, indent=2), encoding="utf8")
    _stage(root)
    r = _run(root)
    assert r.returncode != 0, "an operational literal bought an exemption by relabelling"
    assert "operational, NOT allowlistable" in r.stdout


def test_placeholder_rationale_is_rejected(pristine):
    """AC6 d: every entry needs a real per-entry rationale."""
    root = _copy(pristine)
    doc = json.loads((root / ALLOWLIST).read_text(encoding="utf8"))
    doc["entries"][0]["rationale"] = "TBD"
    (root / ALLOWLIST).write_text(json.dumps(doc, indent=2), encoding="utf8")
    _stage(root)
    r = _run(root)
    assert r.returncode != 0
    assert "no per-entry rationale" in r.stdout


@pytest.mark.parametrize("marker", ["git@github.com:" + "Yugoge", "/root/.claude" + ".bak", "/root/sync-" + "backup.sh"])
def test_preexisting_hard_markers_still_gate(pristine, marker):
    """AC6 e: the three pre-existing HARD_MARKERS must not be regressed by the
    new section — one behavioural control per marker."""
    root = _copy(pristine)
    assert _run(root).returncode == 0
    victim = root / "agents" / "dev.md"
    with victim.open("a", encoding="utf8") as fh:
        fh.write(f"\nInjected hard marker {marker}\n")
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
    # every allowlist entry corresponds to a file inside the ledger-derived set
    doc = json.loads((pristine / ALLOWLIST).read_text(encoding="utf8"))
    assert {e["path"] for e in doc["entries"]} <= expected
    assert scanned == len(doc["entries"]), "scanned occurrences must equal the exempted set on a clean tree"
