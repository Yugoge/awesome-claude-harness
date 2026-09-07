"""The stager must enumerate EVERY declaration category, not just the derived two.

`agents/changelog-analyst.md` decides what a cycle commits by reading declaration
categories out of a dev-report. For as long as there were exactly two of them
(`files_created`, `files_modified`) the enumeration sites could hardcode that pair.
A third category, `files_required_to_ship`, records a path the cycle must ship
WITHOUT claiming the cycle authored it -- a file that pre-existed the cycle and that
the cycle's own change made load-bearing at runtime. The derived pair cannot express
that path: both are filled from git (`ls-files --others`, `diff --name-only`), so
putting it there asserts an authorship the git evidence contradicts.

While the enumeration sites named only the derived pair, a path declared under the
third category was silently absent from the staging whitelist: the commit would omit
it and the cycle would close believing it had shipped a file it had not.

STRENGTH OF THIS EVIDENCE -- read before trusting a green run. The component under
test is PROSE executed by a model, not code executed by an interpreter. These tests
verify that the DESCRIPTION the model reads is complete and self-consistent at every
enumeration site. They do NOT, and cannot, verify the model's runtime staging
behaviour; no assertion here proves a `git add` occurred. They are a regression guard
of exactly the strength that fits a described component: had they existed before the
third category was introduced, they would have failed the moment it was added to a
report without being added here.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGER_DOC = REPO_ROOT / "agents" / "changelog-analyst.md"

# The declaration vocabulary, as a set. The point of this test module is that this
# tuple -- not a hardcoded pair -- is what every enumeration site must cover, so a
# FOURTH category added later fails here until the sites are updated too.
DERIVED_CATEGORIES = ("files_created", "files_modified")
DECLARED_ONLY_CATEGORIES = ("files_required_to_ship",)
ALL_CATEGORIES = DERIVED_CATEGORIES + DECLARED_ONLY_CATEGORIES


@pytest.fixture(scope="module")
def doc():
    assert STAGER_DOC.is_file(), "stager description missing at %s" % STAGER_DOC
    return STAGER_DOC.read_text(encoding="utf-8")


def _window(text, anchor, before=0, after=1200):
    """Text around a stable prose anchor, so tests do not pin line numbers."""
    idx = text.find(anchor)
    assert idx != -1, "anchor vanished from the stager description: %r" % anchor
    return text[max(0, idx - before): idx + after]


def _missing(window):
    return [c for c in ALL_CATEGORIES if c not in window]


# --- the enumeration sites -------------------------------------------------


def test_staging_whitelist_enumerates_every_category(doc):
    """The whitelist IS the ship-set. A category absent here cannot be committed."""
    window = _window(doc, "The candidate set is restricted to a **staging whitelist**")
    assert not _missing(window), (
        "staging whitelist omits declaration categories %s -- a path declared under an "
        "omitted category is silently dropped from the commit" % _missing(window))


def test_staged_file_count_guard_budgets_every_category(doc):
    """A guard that budgets 2 of 3 categories aborts legitimate commits as overflow."""
    window = _window(doc, "**Staged-file count guard**")
    assert not _missing(window), (
        "count guard omits %s from its limit arithmetic" % _missing(window))


def test_report_extraction_reads_every_category(doc):
    """Nothing downstream can use a category the extraction step never reads."""
    window = _window(doc, "arrays from the resolved path", before=400)
    assert not _missing(window), (
        "dev-report extraction omits %s" % _missing(window))


def test_task_cycle_files_union_covers_every_category(doc):
    """This union answers 'was the ship-set already committed', so it needs all of it."""
    window = _window(doc, "Compute `task_cycle_files`")
    assert not _missing(window), (
        "task_cycle_files union omits %s" % _missing(window))


def test_untracked_required_path_has_a_staging_mechanism(doc):
    """Whitelist admission is inert unless a clause authorises the actual staging.

    The non-entangled clause is what permits a whole-file `git add`. It used to admit
    untracked paths only via `files_created`; a required-to-ship path is untracked and
    NOT in `files_created`, so without its own clause it would be admitted to the
    whitelist and then dropped at staging time -- a cosmetic fix.
    """
    window = _window(doc, "**Non-entangled files** use the existing whole-file path")
    assert "files_required_to_ship" in window, (
        "no staging mechanism for an untracked required-to-ship path; whitelist "
        "admission alone does not stage it")


# --- the two judgement calls -----------------------------------------------


def test_absent_required_file_is_a_hard_error_not_a_silent_skip(doc):
    """Silent skip is the failure mode this area has already been bitten by."""
    window = _window(doc, "All files listed in `dev.files_required_to_ship[]`")
    assert "ABORT" in window, "absence of a required-to-ship path must abort"
    assert re.search(r"never a silent skip", window), (
        "the no-silent-skip decision must be stated where the category is defined")


def test_required_to_ship_is_not_used_for_authorship_attribution(doc):
    """It asserts a requirement, not authorship; narrating it as a change misattributes."""
    window = _window(doc, "**Authorship asymmetry")
    for derived in DERIVED_CATEGORIES:
        assert derived in window, (
            "the authorship carve-out must name the derived categories that MAY be "
            "used for attribution; %s missing" % derived)
    assert "files_required_to_ship" in window


# --- the boundary that must NOT move ---------------------------------------


def test_undeclared_files_are_still_excluded(doc):
    """Extending the enumeration must not widen staging to whatever is in the tree."""
    assert "foreign_session_candidate" in doc, (
        "the undeclared-file exclusion disappeared; staging would no longer be "
        "bounded by the report")
    window = _window(doc, "Only files that appear in BOTH the git status output")
    assert "**excluded from" in window and "NOT in this" in window, (
        "the both-sets intersection that keeps undeclared files out was weakened")


def test_no_force_add_or_stage_all_path_was_introduced(doc):
    """A required-to-ship file must arrive by declaration, never by force-add."""
    # A mention inside a prohibition ("NEVER use `git add -A`") is the desired state;
    # only an unprohibited mention would be a new stage-all path.
    prohibitions = ("never", "not use", "forbidden", "refus")
    for forbidden in ("git add -A", "git add .", "add --force", "add -f "):
        for line in doc.splitlines():
            lowered = line.lower()
            if forbidden.lower() in lowered and not any(p in lowered for p in prohibitions):
                pytest.fail("a stage-all/force-add path appeared: %r" % line.strip())


def test_membership_still_requires_a_report(doc):
    """Presence in the working tree must never be sufficient on its own."""
    window = _window(doc, "it is an untracked path declared in `dev.files_required_to_ship`")
    assert "presence in the working tree alone" in window, (
        "the new clause must restate that the tree alone admits nothing, or it reads "
        "as a licence to stage any untracked file")
