"""Behavioural gate tests for scripts/check-public-core.sh residue sections.

These are the discriminating controls for the "Make CI FAIL (not advisory) on
/root, author-home paths, the tmpfs workspace path, and other personal residue
in public-core" requirement:

  * a maintainer workspace/tmpfs path HARD-FAILS (it was advisory-only). The gate
    no longer hard-codes that personal value (R7b): the machine owner lists it in
    the untracked private-literal list, so these controls write a synthetic stand-in
    into a list inside their own copied tree;
  * generic author-home classes (/root/, /home/<user>/, /Users/<User>/) and e-mail
    addresses outside the classes allowed by rule hard-fail, in EVERY tracked file;
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
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CHECKER = "scripts/check-public-core.sh"
ALLOWLIST = "policies/public-core-residue-allowlist.v1.json"
PRIVATE_LIST = "private-literals.txt"   # machine-local private-literal list (R7b), never tracked
# A SYNTHETIC workspace path standing in for the maintainer's real one (a personal value
# that belongs only in a machine's private list). Split so this file never carries it
# whole: the private-literal rule scans every tracked file, this one included.
WORKSPACE_STANDIN = "/dev/shm/" + "demo-workspace/demo-harness"
# Synthetic stand-ins for the kinds of value a machine lists (a remote, a mirror path, a
# sync script), split for the same reason. Test ids name the kind, never the value.
STANDINS = {"remote": "standin-" + "q7x-1", "mirror": "/srv/standin-" + "q7x-2",
            "sync": "/srv/standin-" + "q7x-3.sh"}


def _tracked_files() -> list[str]:
    """Tracked files PLUS untracked-but-not-ignored ones.

    The fixture must mirror the tree as it would be COMMITTED, not merely what is
    already in the index: a newly added, not-yet-staged file (the residue
    allowlist itself, on the cycle that introduces it) is part of the state the
    gate has to run against. The machine's own private-literal list is never part
    of that tree, ignored or not.
    """
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files"],
                             capture_output=True, text=True).stdout.split()
    untracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "--others", "--exclude-standard"],
                               capture_output=True, text=True).stdout.split()
    return sorted((set(tracked) | set(untracked)) - {PRIVATE_LIST})


def _filtered(root: Path) -> set[str]:
    """Tracked files git filters (a `filter` attribute; settings.json today)."""
    names = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                           capture_output=True, text=True, check=True).stdout
    out = subprocess.run(["git", "-C", str(root), "check-attr", "-z", "--stdin", "filter"],
                         input=names, capture_output=True, text=True, check=True).stdout.split("\0")
    return {out[i] for i in range(0, len(out) - 2, 3) if out[i + 2] not in ("unspecified", "unset")}


@pytest.fixture(scope="module")
def pristine(tmp_path_factory) -> Path:
    """An isolated git repo holding the current tracked working-tree content. A file git
    filters holds its index blob instead: on a home that ran init, settings.json's working
    copy is the machine form (the owner's overlay merged in), never what is committed."""
    dest = tmp_path_factory.mktemp("pc-pristine")
    filtered = _filtered(REPO)
    for rel in _tracked_files():
        src = REPO / rel
        if not src.is_file():
            continue
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        if rel in filtered:
            (dest / rel).write_bytes(subprocess.run(["git", "-C", str(REPO), "cat-file", "blob", f":{rel}"],
                                                    capture_output=True, check=True).stdout)
        else:
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


def _private_list(root: Path, *literals: str) -> None:
    """Write a private-literal list into the copied tree (literals from list line 2 on),
    excluded from staging exactly as the harness .gitignore keeps the real one untracked."""
    exclude = root / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    _append(exclude, f"\n/{PRIVATE_LIST}\n")
    (root / PRIVATE_LIST).write_text(
        "# private values of this machine (synthetic)\n" + "".join(f"{lit}\n" for lit in literals),
        encoding="utf8")


def _private_literal_hits(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if line.startswith("FAIL: private literal")]


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


def _tracked(root: Path) -> set[str]:
    """Every tracked file — the CHECKOUT-mode scan scope (archive mode scans the
    release-membership subset)."""
    return set(subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                              capture_output=True, text=True).stdout.split("\0")) - {""}


def _in_scope_entries(root: Path) -> list[dict]:
    """Allowlist entries whose path is inside the checkout-mode scan scope."""
    scope = _tracked(root)
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
    """AC5, re-homed by R7b: the tmpfs workspace path hard-fails, in EVERY public-core
    ledger prefix, once it is listed in the machine's private-literal list (the gate
    no longer hard-codes it). The failure names the file and the list line, never the
    literal. The controls key on the rule's own FAIL lines, so the verdict is causally
    attributable to the injection whatever else the tree carries."""
    root = _copy(pristine, tmp_path)
    _private_list(root, WORKSPACE_STANDIN)
    victim = _victim(root, prefix)
    before = _run(root)
    assert not _private_literal_hits(before.stdout), "baseline control: no listed literal before the injection"
    marker_line = f"\n# injected marker {WORKSPACE_STANDIN}/x\n"
    _append(victim, marker_line)
    _stage(root)
    r = _run(root)
    assert r.returncode != 0, f"listed workspace marker not gated in {prefix}"
    rel = str(victim.relative_to(root))
    hits = _private_literal_hits(r.stdout)
    assert any(f"-> {rel}:" in h for h in hits), "failure output must name the injected file"
    assert all(f"({PRIVATE_LIST} line 2)" in h for h in hits), "failure must name the list line"
    assert WORKSPACE_STANDIN not in r.stdout + r.stderr, "the listed literal must never be printed"
    _write(victim, victim.read_text(encoding="utf8").replace(marker_line, ""))
    _stage(root)
    after = _run(root)
    assert not _private_literal_hits(after.stdout), "removing the injection must clear the rule"
    assert after.returncode == before.returncode, "removing the injection must restore the prior verdict"


def test_listed_workspace_marker_fails_in_archive_mode_without_exemption(pristine, staged, tmp_path):
    """R7b archive limb: with a list present the same rule runs over every archive
    member. The retired workspace-marker gate exempted the ledger; the private-literal
    rule exempts no path, so a listed literal in PUBLIC-CORE.md is caught as well."""
    root = _copy(pristine, tmp_path)
    _private_list(root, WORKSPACE_STANDIN)
    stage = _copy_stage(staged, tmp_path)
    assert not _private_literal_hits(_run_archive(root, stage).stdout), "baseline control"
    victims = ("agents/dev.md", "PUBLIC-CORE.md")
    for rel in victims:
        with (stage / rel).open("a", encoding="utf8") as fh:
            fh.write(f"\nInjected marker {WORKSPACE_STANDIN}/x\n")
    r = _run_archive(root, stage)
    assert r.returncode != 0, "listed workspace marker shipped undetected in the archive"
    hits = _private_literal_hits(r.stdout)
    for rel in victims:
        assert any(f"-> {rel}:" in h for h in hits), f"{rel} not reported"
    assert WORKSPACE_STANDIN not in r.stdout + r.stderr, "the listed literal must never be printed"


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
    scope = _tracked(root)
    victim = next(i for i, e in enumerate(doc["entries"]) if e["path"] in scope)
    doc["entries"][victim]["rationale"] = "TBD"
    _write(root / ALLOWLIST, json.dumps(doc, indent=2))
    _stage(root)
    r = _run(root)
    assert r.returncode != 0
    assert "no per-entry rationale" in r.stdout


@pytest.mark.parametrize("kind", sorted(STANDINS))
def test_preexisting_hard_markers_still_gate(pristine, tmp_path, kind):
    """AC6 e, re-homed onto the private-literal rule: the kinds of value the retired
    published marker list named (a remote, a mirror path, a sync script) still gate once
    a machine lists them — one behavioural control per kind, with synthetic stand-ins."""
    root = _copy(pristine, tmp_path)
    _private_list(root, *STANDINS.values())
    assert _run(root).returncode == 0
    _append(root / "agents" / "dev.md", f"\nInjected listed value {STANDINS[kind]}\n")
    _stage(root)
    r = _run(root)
    assert r.returncode != 0, f"listed {kind} value regressed"
    assert any("-> agents/dev.md:" in h for h in _private_literal_hits(r.stdout))
    assert STANDINS[kind] not in r.stdout + r.stderr, "the listed literal must never be printed"


def test_scan_set_equals_every_tracked_file(pristine):
    """AC5, widened: the checkout-mode scan set is EVERY tracked file (the ledger class
    no longer narrows it), so every allowlist entry names a tracked file and, on a clean
    tree, scanned occurrences and entries correspond 1:1 — not merely "no failures"."""
    expected = _tracked(pristine)
    r = _run(pristine)
    scanned = int(r.stdout.split("residue audit:")[1].split("occurrence")[0].strip())
    doc = json.loads((pristine / ALLOWLIST).read_text(encoding="utf8"))
    assert {e["path"] for e in doc["entries"]} <= expected
    assert scanned == len(doc["entries"]), "scanned occurrences must equal the exempted set on a clean tree"
    assert "tests/" in "".join(e["path"] for e in doc["entries"]), "the test tree is scanned too"


@pytest.mark.parametrize("victim, line", [
    (".github/CODEOWNERS", "# owner: " + "maint" + "@" + "acct-b.dev"),
    ("tests/conftest_stub.md", "contact " + "maint" + "@" + "acct-b.dev"),
])
def test_email_outside_the_allowed_classes_fails_in_any_tracked_file(pristine, tmp_path, victim, line):
    """The e-mail rule: an address with a non-reserved domain fails wherever it is tracked."""
    root = _copy(pristine, tmp_path)
    path = root / victim
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _append(path, "\n" + line + "\n")
    else:
        path.write_text(line + "\n", encoding="utf8")
    _stage(root)
    r = _run(root)
    assert r.returncode != 0
    assert f"NEW un-allowlisted e-mail address -> {victim}:" in r.stdout
    assert "acct-b.dev" not in r.stdout, "a FAIL line never prints the address"


def test_emails_allowed_by_rule_pass(pristine, tmp_path):
    """Allowed by rule, no allowlist entry needed: a systemd template unit, the git SSH
    user form, reserved example/test domains and a no-reply address."""
    root = _copy(pristine, tmp_path)
    _append(root / "agents" / "dev.md", "\n" + "\n".join((
        "systemctl restart " + "worker" + "@" + "blue.service",
        "git clone " + "git" + "@" + "git.acct-b.dev:org/repo.git",
        "mail " + "maint" + "@" + "example.invalid",
        "mail " + "maint" + "@" + "corp.example.com",
        "Co-Authored-By: bot <" + "noreply" + "@" + "acct-b.dev>")) + "\n")
    _stage(root)
    r = _run(root)
    assert r.returncode == 0, r.stdout + r.stderr


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
# Archive-mode listed values (backlog item 2) — AC-REL-4, re-homed onto the
# private-literal rule: the published hard-marker list and its exemption keys are
# gone; a machine lists such values and the same rule gates every archive member.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", sorted(STANDINS))
def test_hard_marker_in_a_non_exempt_archive_member_fails(pristine, staged, tmp_path, kind):
    """AC-REL-4 limb a: a listed maintainer value inside a released artifact is caught."""
    root = _copy(pristine, tmp_path)
    _private_list(root, *STANDINS.values())
    stage = _copy_stage(staged, tmp_path)
    assert _run_archive(root, stage).returncode == 0, "baseline control must be clean"
    with (stage / "agents" / "dev.md").open("a", encoding="utf8") as fh:
        fh.write(f"\nInjected listed value {STANDINS[kind]}\n")
    r = _run_archive(root, stage)
    assert r.returncode != 0, f"listed {kind} value shipped undetected in the archive"
    assert any("-> agents/dev.md:" in h for h in _private_literal_hits(r.stdout))
    assert STANDINS[kind] not in r.stdout + r.stderr, "the listed literal must never be printed"


def test_unmodified_staged_tree_does_not_false_fail_on_legitimate_carriers(pristine, staged, tmp_path):
    """AC-REL-4 limb b (anti-vacuity): with a list present, the unmodified staged tree
    passes — the ledger, the engine and the allowlist carry no listed value.

    Without this, limb a could be satisfied by failing every release."""
    root = _copy(pristine, tmp_path)
    _private_list(root, *STANDINS.values())
    r = _run_archive(root, staged)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS: no listed private literal (scope: archive)" in r.stdout


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


# ---------------------------------------------------------------------------
# A filtered file is gated from its index blob, not its smudged checkout.
#
# On a home that ran init, the claude-settings filter smudges the overlay into the
# working settings.json (the machine form) while git stores the clean form. Read from
# the checkout, the default run reported the owner's machine values as residue.
# ---------------------------------------------------------------------------

def test_filtered_settings_are_gated_from_the_index_not_the_smudged_checkout(pristine, tmp_path):
    """A stand-in machine form (one entry per content check: author-path residue, listed
    private literal, e-mail address) smudged into the checkout changes nothing in the default run;
    an unstaged change to an unfiltered file is still read from the checkout; the same
    machine form in the index (filter bypassed) still fails on every entry."""
    root = _copy(pristine, tmp_path)
    _private_list(root, STANDINS["sync"])
    git = ["git", "-C", str(root)]
    assert "settings.json" in _filtered(root), "settings.json carries the filter attribute"
    fresh = _run(root)
    assert "settings.json" not in fresh.stdout, "control: the clean form carries no residue"
    entries = ("Bash(/home/" + "acct-test-123/bin/sync.sh:*)", f"Bash({STANDINS['sync']}:*)",
               "Bash(mail " + "maint" + "@" + "acct-b.dev:*)")
    added = tmp_path / "machine-entries"
    added.write_text("".join(f'      "{e}",\n' for e in entries), encoding="utf8")
    # A stand-in filter shaped like init's: smudge adds the entries, clean removes them.
    _mutable(root / ".git" / "config")
    subprocess.run([*git, "config", "filter.claude-settings.smudge",
                    f"sed '/\"allow\": \\[/r {shlex.quote(str(added))}'"], check=True)
    subprocess.run([*git, "config", "filter.claude-settings.clean",
                    f"grep -vxF -f {shlex.quote(str(added))}"], check=True)
    (root / "settings.json").unlink()
    subprocess.run([*git, "checkout", "--", "settings.json"], check=True)
    machine = (root / "settings.json").read_text(encoding="utf8")
    assert all(e in machine for e in entries), "the checkout is the machine form"
    assert subprocess.run([*git, "diff", "--quiet", "--", "settings.json"]).returncode == 0, \
        "git sees the machine form as the indexed clean form"
    smudged = _run(root)
    assert (smudged.returncode, smudged.stdout) == (fresh.returncode, fresh.stdout), \
        [line for line in smudged.stdout.splitlines() if "settings.json" in line or "residue audit:" in line]

    victim = root / "agents" / "dev.md"
    original = victim.read_text(encoding="utf8")
    _append(victim, "\nunstaged /home/" + "acct-test-123/x\n")
    unstaged = _run(root)
    assert "NEW un-allowlisted author-path residue -> agents/dev.md:" in unstaged.stdout, \
        "an unfiltered file is still read from the checkout"
    _write(victim, original)

    oid = subprocess.run([*git, "hash-object", "-w", "--no-filters", "settings.json"],
                         capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run([*git, "update-index", "--cacheinfo", f"100644,{oid},settings.json"], check=True)
    committed = _run(root)
    assert committed.returncode != 0
    for needle in ("NEW un-allowlisted author-path residue -> settings.json:",
                   f"FAIL: private literal ({PRIVATE_LIST} line 2) -> settings.json:",
                   "NEW un-allowlisted e-mail address -> settings.json:"):
        assert needle in committed.stdout, f"a machine form in the index is not caught: {needle}"
