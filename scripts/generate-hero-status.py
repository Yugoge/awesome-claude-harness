#!/usr/bin/env python3
"""Generate and ratchet the canonical regions of README.md and docs/status.md from repository state.

Description: One source of truth emits SIX marker-delimited canonical regions in two documents and
  re-derives them on demand to byte-compare against what is committed. README.md holds two count
  regions, markdown tables whose every cell comes from scripts/readme_facts.py: `commands` (under
  "The command surface") and `agents` (under "The cast of agents"). docs/status.md holds the third
  count region, `proof` (the measured proof, under "Measured proof"), and the three claim regions,
  in this order, under "Status and known limits": `limits`, `disclosure` and `status`. No row's
  visible text is ever hand-written; every claim row is computed from a named predicate, and every
  command and agent row is the file's own frontmatter `summary`, never cut.

Usage: generate-hero-status.py --write [--readme <path>] [--status <path>]   # regenerate the regions
       generate-hero-status.py --check [--readme <path>] [--status <path>]   # the CI ratchet
       generate-hero-status.py --check --no-fold           # skip the glyph-model measurement

Exit codes: 0 = ok, 1 = usage/IO error (--write: also a count region that cannot be computed),
  2 = one or more ratchet assertions failed

WHAT IS ASSERTED, in each document for the regions it holds. Content (per-row and whole-region
byte-compare, closed state enum, predicate agreement in both directions), POSITION (each region in
its own document, inside its H2 section, the claim regions in order, none missing or duplicated),
NUMBERS (no numeral typed by hand in the prose of either document) and, in README.md, NAMES (no
internal name: an optional module's own name, a borrowed tool name or a model id). Every violation
names the document it is in.

THE POSITION RULE REPLACED THE HEADLINE RULE. This script used to assert that the limits statement
sat next to the headline, in the first screen, and that "headline" and "limits" were fully above
the fold (scripts/measure-hero-fold.py). The owner moved the claim rows (limits, disclosure, status)
out of the top of the README to a section near its end, "Status and known limits", and later out of
the README into docs/status.md with the proof table and the hero recording; the headline text that
measurement looks up no longer exists, so neither assertion can hold or mean anything there.
Dropping them without a replacement would have let the limits move anywhere unseen, so what
replaced them is assert_region_positions: every region must sit in its document (DOC_REGIONS),
inside the H2 section named for it in SECTION_OF, the three claim regions must appear in the order
limits, disclosure, status, and a region that is outside its section or its document, duplicated,
missing or out of order is a violation that names the region. The fold measurement is still run,
over docs/status.md where the hero now is, and only its report of glyph-model drift is consumed
(assert_glyph_model); the glyph floor and the old above-the-fold elements are not gated.

NUMBERS ARE DERIVED, NEVER TRANSCRIBED. Inside the regions every number is computed: the hero's
recorded duration, loop period, first-proof offset and rendered glyph height from committed
artifacts, and every count in the proof, commands and agents tables from scripts/readme_facts.py.
The recorded duration is cross-validated against the capture's own first and last timestamps, so a
coordinated edit of the status page and the evidence file together still cannot agree. OUTSIDE the
regions a numeral in the prose is a violation (assert_no_hand_typed_numbers) unless it is an
ordered-list marker, sits in a code span, fenced block, HTML comment, HTML tag or attribute (a
title or alt among them), link target or title, or image, or is one of the externally cited
figures declared once in CITED_FIGURES with the URL it comes from; those are README.md's, the
document that cites them, and are no exemption in docs/status.md. A declared figure that no longer
appears in the README's prose, or whose URL is absent from it, also fails. Numbers written as words
are out of scope. Known false positives, left as they are: version-like words (UTF-8, SHA-256,
HTTP/2), footnote markers and any other word with a digit after a non-letter. The escape is a code
span.

THE NUMBER RULE FAILS CLOSED WHEN IT CANNOT READ THE PROSE. Whatever hides text from it must be
visible in the rendered page too, or the rule would be bypassed by the hiding: a code fence that is
never closed (the rest of the file would be hidden), an HTML comment that is never closed, and a
backtick run with no closing run (an unbalanced code span) are each a violation that names the
line. A code span never pairs across list items, table rows or cells, headings or paragraphs, so
a stray backtick in one line cannot hide a numeral in another. A comment opener or closer inside a
code span or a fenced block does not start or end a comment; inside a comment, as in the rendered
page, the first closer ends it, a code span or not.

WITHOUT A BROWSER THE HERO FIGURES ARE MODEL PREDICTIONS, NOT MEASUREMENTS. The glyph sizes in the
disclosure region (and the legibility row built on them) are computed from the hero asset's
viewBox, the image width docs/status.md asks for and the model in scripts/measure-hero-fold.py.
They become measurements only when that script runs and finds the model equal to a live browser,
which needs the Python `playwright` package and a Chromium (assert_glyph_model consumes its
model_drift). Neither a default checkout nor the baseline CI job installs them: there the check
prints a NOTE that the glyph figure is UNVERIFIED, and its last line says that the glyph model was
not measured. Only a run whose last line says "glyph model asserted" measured anything.

WRITE MODE REFUSES BEFORE IT WRITES. It verifies both documents first: each region present once in
its own document, disjoint, in the required order and inside its section, and no carriage return
in either file (the regions are byte-compared as LF text; a CRLF document is refused, never
rewritten). Any problem is named and neither document is touched. The new text of each goes to a
temporary file in its own directory and is renamed over it, so a kill or a full disk cannot leave
it empty or partial, and a document that changed while the facts were derived is refused rather
than overwritten.

FAIL-CLOSED IN ONE DIRECTION ONLY. A predicate input that is missing, unreadable, unparseable, or
not committed makes its claim row FALSE (state not-yet, no figure published): the failure mode of
a broken predicate is continued honest disclosure, never a silent pass. A count region has no such
fallback: when a fact it needs cannot be derived, or a command's or agent's summary breaks the
rules of scripts/readme_facts.py (missing, more than one line, too long, an internal name), --check
fails naming the input, and --write refuses to touch either document rather than print a value
from an earlier run or a cut summary.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# This script, the fact module and the fold measurement are loaded by path, and a run must leave
# no __pycache__ behind in the tree it checks.
sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parent.parent

ROW_IDS = ["known-limits", "hero-recording", "hero-legibility", "hero-glyph",
           "supported-builds", "capability-check", "blackbox-tests", "release", "os",
           "enforcement-strength", "dead-end-sites"]

# The two documents under evaluation. Rebound by cmd_write and cmd_check so a --readme or --status
# copy is measured against its OWN content (the hero width is read from the status page) rather than
# the repository's; a predicate that silently read the checked-in page while checking a copy would
# report confident numbers about the wrong document.
README_PATH = REPO_ROOT / "README.md"
STATUS_PATH = REPO_ROOT / "docs" / "status.md"

# Canonical regions. COUNT_REGIONS are tables built from scripts/readme_facts.py; CLAIM_REGIONS
# hold the claim rows and MUST appear in this order (limits, then disclosure, then status).
COUNT_REGIONS = ("proof", "commands", "agents")
CLAIM_REGIONS = ("limits", "disclosure", "status")
REGION_IDS = COUNT_REGIONS + CLAIM_REGIONS
STATES = {"passed", "not-yet", "partial"}

# The document each region lives in, and the name a violation in it carries.
DOC_NAME = {"readme": "README.md", "status": "docs/status.md"}
DOC_REGIONS = {"readme": ("commands", "agents"), "status": ("proof", "limits", "disclosure", "status")}
DOCUMENT_OF = {rid: doc for doc, rids in DOC_REGIONS.items() for rid in rids}

# The H2 section each region must sit inside (heading text, exact).
STATUS_SECTION = "Status and known limits"
SECTION_OF = {"proof": "Measured proof", "commands": "The command surface", "agents": "The cast of agents",
              "limits": STATUS_SECTION, "disclosure": STATUS_SECTION, "status": STATUS_SECTION}

# Figures the README prose may quote from outside this repository: the numeral exactly as the
# prose writes it, and the URL it comes from. The ONLY place such a number is declared. The check
# fails when a source URL is absent from the README or a figure no longer appears in its prose.
# They belong to README.md: in docs/status.md they are numerals like any other.
CITED_FIGURES = (
    ("37,623", "https://arxiv.org/pdf/2609.17598"),
    ("12.6", "https://arxiv.org/pdf/2609.17598"),
)

BEGIN = "<!-- BEGIN canonical-region id={rid} — generated by scripts/generate-hero-status.py; do not hand-edit -->"
END = "<!-- END canonical-region id={rid} -->"
MARKER_RE = re.compile(
    r"^<!-- claim-row id=(?P<id>[a-z-]+) state=(?P<state>[a-z-]+) "
    r"evidence=(?P<evidence>\S+) tracked=(?P<tracked>\S+) -->$"
)


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, check=True,
                              capture_output=True, text=True).stdout
    except Exception:
        return ""


def is_committed(rel: str) -> bool:
    """Tracked by git AND present on disk.

    Tracked-ness is load-bearing, not pedantry: the reader's vantage point is a fresh
    clone, and an untracked file is simply absent there. A predicate that resolved true
    against an uncommitted working-tree file would flip a row to `passed` for a reader
    who can never see the evidence.
    """
    if not (REPO_ROOT / rel).exists():
        return False
    r = subprocess.run(["git", "ls-files", "--error-unmatch", "--", rel],
                       cwd=REPO_ROOT, capture_output=True, text=True)
    return r.returncode == 0


# --------------------------------------------------------------------------------------
# The repository's facts. Every count in the proof, commands and agents tables, and in the two claim
# rows built on them, comes from scripts/readme_facts.py -- the single producer of those figures. The
# module is loaded by path (its name is not importable from a --readme copy's directory) and each
# fact is computed ONCE per process: the blocking-site enumeration alone takes several seconds and
# more than one region reads it. A failure is remembered too, so a missing input is reported once
# and never retried into a different answer.
# --------------------------------------------------------------------------------------

FACTS_SCRIPT = "scripts/readme_facts.py"


class FactUnavailable(RuntimeError):
    """A fact could not be derived. The message names the missing or unusable input."""


_FACT_MODULE = None
_FACTS: dict[str, object] = {}


def facts_module():
    global _FACT_MODULE
    if _FACT_MODULE is None:
        path = REPO_ROOT / FACTS_SCRIPT
        if not path.is_file():
            raise FactUnavailable(f"missing input {FACTS_SCRIPT} (looked in {REPO_ROOT})")
        try:
            spec = importlib.util.spec_from_file_location("readme_facts_for_generator", path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module  # a dataclass in the module looks its own module up
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 - whatever it did, the facts are not usable
            raise FactUnavailable(f"cannot load {FACTS_SCRIPT}: {type(exc).__name__}: {exc}") from exc
        _FACT_MODULE = module
    return _FACT_MODULE


def fact(name: str):
    """The value of the named fact of scripts/readme_facts.py for this repository, or FactUnavailable."""
    if name not in _FACTS:
        try:
            module = facts_module()
            _FACTS[name] = module.FACTS[name](REPO_ROOT)
        except FactUnavailable as exc:
            _FACTS[name] = exc
        except Exception as exc:  # noqa: BLE001 - FactError, or a fact that crashed
            _FACTS[name] = FactUnavailable(f"{name}: {exc}")
    value = _FACTS[name]
    if isinstance(value, FactUnavailable):
        raise value
    return value


# --------------------------------------------------------------------------------------
# Derived hero facts. Every number the disclosure region publishes is COMPUTED here from a
# committed artifact, never transcribed. The caption previously carried a hand-typed
# session length that disagreed with every artifact by ~1 s and sat outside the canonical
# fence, so nothing regenerated it and nothing compared it. Deriving it here puts it under
# the same whole-region byte-compare as every other published claim.
# --------------------------------------------------------------------------------------

HERO_CAPTURE = ".github/assets/hero-capture.txt"
HERO_EVIDENCE = ".github/assets/hero-capture-evidence.json"
HERO_MANIFEST = ".github/assets/guard-hero.json"
HERO_ASSET = ".github/assets/guard-hero.svg"

CAPTURE_TS_RE = re.compile(r"^\[\s*(\d+\.\d+)\]\s")
CONSUMPTION_MARKER = "[ALLOW-SENTINEL] grant CONSUMED for task_id="


def _read(rel: str) -> str | None:
    p = REPO_ROOT / rel
    try:
        return p.read_text(encoding="utf-8") if p.is_file() else None
    except OSError:
        return None


def hero_facts() -> dict:
    """Derive every published hero number from committed artifacts.

    Returns {} when an input is missing or unparseable, and {'duration_conflict': ...}
    when the recorded duration disagrees with the capture's own timestamps. Both make the
    consuming row disclose the failure instead of publishing a number -- the fail-closed
    direction. The cross-validation is the point: a coordinated edit of the status page's region
    AND the evidence file still cannot agree with the capture's first and last timestamps.
    """
    inputs = _hero_inputs()
    recomputed = _capture_seconds(inputs[0]) if inputs else None
    if recomputed is None:
        return {}
    _cap, evidence, manifest, svg = inputs
    declared = evidence.get("raw_duration_s")
    if not isinstance(declared, (int, float)) or abs(float(declared) - recomputed) > 1e-6:
        return {"duration_conflict": (declared, recomputed)}
    durations = {float(d) for d in re.findall(r'\bdur="([\d.]+)s"', svg)}
    loop_s = max(durations) if durations else None
    lines = manifest.get("lines", [])
    proof_s = _proof_seconds(svg, lines, loop_s)
    logical_w, clipped = _clipping(svg, {str(ln.get("id")): ln for ln in lines})
    if loop_s is None or proof_s is None or logical_w is None:
        return {}
    return {
        "duration_s": f"{recomputed:g}",
        "loop_s": f"{loop_s:g}",
        "ratio": f"{loop_s / recomputed:.2f}",
        "proof_s": f"{proof_s:g}",
        "proof_pct": f"{100.0 * proof_s / loop_s:.1f}",
        "logical_w": f"{logical_w:g}",
        "clipped_n": len(clipped),
        "total_n": len(lines),
        "worst_lost": max((c for _, c in clipped), default=0),
    }


def _hero_inputs() -> tuple[str, dict, dict, str] | None:
    """(the capture, the evidence, the manifest, the asset), or None when one is missing or does not parse."""
    cap, ev_raw, man_raw, svg = (_read(HERO_CAPTURE), _read(HERO_EVIDENCE), _read(HERO_MANIFEST), _read(HERO_ASSET))
    if not all((cap, ev_raw, man_raw, svg)):
        return None
    try:
        return cap, json.loads(ev_raw), json.loads(man_raw), svg
    except Exception:
        return None


def _capture_seconds(cap: str) -> float | None:
    """The recorded session's length from the capture's own first and last timestamps."""
    stamps = [float(m.group(1)) for m in (CAPTURE_TS_RE.match(ln) for ln in cap.splitlines()) if m]
    return round(stamps[-1] - stamps[0], 3) if len(stamps) >= 2 else None


def _proof_seconds(svg: str, lines: list, loop_s: float | None) -> float | None:
    """When the grant-consumed proof line's reveal begins, read from the asset's own animation schedule."""
    marker_id = next((str(ln["id"]) for ln in lines
                      if str(ln.get("text", "")).startswith(CONSUMPTION_MARKER)), None)
    if not (marker_id and loop_s):
        return None
    chunk = next((c for c in svg.split('<g data-role="line"')[1:] if f'data-trace-id="{marker_id}"' in c), None)
    km = re.search(r'attributeName="opacity"[^>]*keyTimes="([^"]+)"', chunk) if chunk is not None else None
    kt = [float(x) for x in km.group(1).split(";") if x.strip()] if km else []
    return round(kt[1] * loop_s, 2) if len(kt) >= 2 else None


def _clipping(svg: str, by_id: dict) -> tuple[float | None, list[tuple[str, int]]]:
    """(the panel's logical width, [(line id, characters cut off at its right edge)]), on the renderer's own
    fixed monospace grid: both constants are read from the asset rather than assumed, so this stays correct
    if the renderer's geometry changes."""
    vb = re.search(r'viewBox="0 0 (\d+(?:\.\d+)?) ', svg)
    logical_w = float(vb.group(1)) if vb else None
    am = re.search(r'<animate attributeName="width"[^>]*values="([^"]+)"', svg)
    vals = [float(v) for v in am.group(1).split(";") if v.strip()] if am else []
    adv = next((b - a for a, b in zip(vals, vals[1:]) if b - a > 0), None)
    if not (logical_w and adv):
        return logical_w, []
    clipped = []
    for t in re.finditer(r'<text data-trace-id="([^"]+)" x="([\d.]+)"', svg):
        ln = by_id.get(t.group(1))
        x, n = (float(t.group(2)), len(str(ln.get("text", "")))) if ln else (0.0, 0)
        if ln and x + n * adv > logical_w:
            clipped.append((t.group(1), n - max(0, int((logical_w - x) // adv))))
    return logical_w, clipped


MEASURE_SCRIPT = "scripts/measure-hero-fold.py"


def _fold_module():
    """Load the fold measurement as a module (its filename is not a Python identifier).

    Importing it rather than restating its constants is the point: the glyph figure the
    status page publishes and the floor the fold gate measures against must be incapable of
    drifting apart. Returns None when it cannot be loaded, which fails the row closed.
    """
    import importlib.util
    p = REPO_ROOT / MEASURE_SCRIPT
    if not p.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("measure_hero_fold", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def glyph_facts() -> dict:
    """The hero's rendered inline glyph height at each covered viewport, and its floor.

    Truncation used to be the whole of what a phone reader could not see, and it is gone --
    the panel was widened until every line fits. But the page then scales that wider panel
    DOWN to fit the column, so the limit moved from "cut off" to "too small to read", and a
    disclosure that still reported only truncation had become vacuous. This derives the
    replacement figure.

    Derived at build time from committed artifacts and NEVER transcribed: the asset's own
    viewBox, the status page's own width attribute, and the model + floor imported from the fold
    measurement, which asserts that model against a real browser on every run.

    Returns {} when any input is missing, unreadable or uncommitted -- fail-closed, so the
    consuming rows disclose that they could not measure instead of publishing a pass.
    """
    mod = _fold_module()
    svg = _read(HERO_ASSET)
    if mod is None or svg is None or not is_committed(MEASURE_SCRIPT):
        return {}
    try:
        page = STATUS_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}
    vb = re.search(r'viewBox="0 0 (\d+(?:\.\d+)?) ', svg)
    img_w = mod.hero_img_width(page)
    if not vb or not img_w:
        return {}
    logical_w = float(vb.group(1))
    widths = sorted({w for w, _h, _s in mod.COMBOS}, reverse=True)
    per_viewport = [(w, mod.predict_glyph_px(w, img_w, logical_w)) for w in widths]
    if not per_viewport or any(g <= 0 for _w, g in per_viewport):
        return {}
    return {"floor_px": f"{mod.GLYPH_FLOOR_PX:g}",
            "per_viewport": per_viewport,
            "below_floor": [(w, g) for w, g in per_viewport if g < mod.GLYPH_FLOOR_PX],
            "n_covered": len(per_viewport)}


# --------------------------------------------------------------------------------------
# Named predicates. Each returns (state, visible_text, evidence, tracked).
# --------------------------------------------------------------------------------------

def tracked_settings_text() -> str:
    """settings.json as the git index holds it, by the one reader every fact uses (scripts/readme_facts.py).

    The working file on a machine may carry machine-only additions that no commit holds, and the
    reader of a fresh clone sees none of them; a row computed from the working file would differ
    between the two."""
    try:
        return facts_module()._tracked_settings_text(REPO_ROOT)
    except FactUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - FactError, or the reader gone
        raise FactUnavailable(f"the tracked settings.json cannot be read: {exc}") from exc


def measure_deny_rules() -> tuple[int, int, str] | None:
    """(total_deny, git_related_deny, source). None when the tracked settings.json is not readable."""
    try:
        deny = json.loads(tracked_settings_text()).get("permissions", {}).get("deny", [])
    except Exception:  # noqa: BLE001 - missing, not in the index, not JSON, not an object
        return None
    if not isinstance(deny, list):
        return None
    return len(deny), sum(1 for r in deny if "git" in str(r).lower()), "settings.json"


def pred_known_limits() -> tuple[str, str, str, str]:
    """Conjunction of two RE-EXECUTED measurements over committed, non-ignored inputs.

    Limb (ii) -- the permission layer carries at least one git-related deny rule -- is
    evaluated FIRST because it is cheap, safe and definitive. When it is false the
    conjunction is already false, so limb (i) (re-running the probe corpus) is NOT
    executed. That short-circuit can only hold the row AT not-yet; it can never flip it
    to passed, because `passed` additionally requires limb (i) to have been positively
    observed. Deletion of evidence is never positive evidence.
    """
    m = measure_deny_rules()
    corpus = "hooks/tests/fixtures/adversarial_corpus.json"
    corpus_committed = is_committed(corpus)

    if m is None:
        return ("not-yet",
                "**Known limits** — the permission surface could not be measured at "
                "build time, so this control is reported as unverified, not as passing.",
                "none", "spec-item-D")

    total, git_related, source = m
    limb_ii = git_related >= 1
    if not limb_ii:
        return (
            "not-yet",
            "**Known limits — this guard does not cover everything.** Wrapper- and "
            "redirection-prefixed `git` forms (`env -u VAR git …`, "
            "`2>/dev/null /usr/bin/git …`) are **not matched** by the Bash "
            "pre-execution gate's classifier: it returns a *successful-but-empty* "
            "parse, which counts as a healthy status and therefore suppresses the "
            "regex backstop meant to catch them. Nothing backs that up at the "
            f"permission layer either — **no deny rule mentions git** ({git_related} "
            f"of {total} deny entries contain the string `git`, recomputed from "
            f"`{source}`). These are **detection-layer measurements**: the forms were "
            "inspected, never executed, and no bypass was demonstrated end-to-end.",
            source, "spec-item-D",
        )
    # limb (ii) holds -- only now is limb (i) reachable, and it must be a live re-run.
    if not corpus_committed:
        return ("not-yet",
                "**Known limits** — the probe corpus is not committed, so coverage was "
                "not re-measured at build time and this control stays unverified.",
                "none", "spec-item-D")
    return ("not-yet",
            "**Known limits** — probe corpus present and the permission layer now "
            "carries git-related deny rules; re-running the corpus at build time is not "
            "yet wired, so this control stays unverified rather than claiming a pass.",
            corpus, "spec-item-D")


def pred_supported_builds() -> tuple[str, str, str, str]:
    art = "docs/reference/install-compatibility-matrix.md"
    if is_committed(art):
        return ("passed", "**Supported builds** — declared and committed.", art, "none")
    return ("not-yet",
            "**Supported builds** — not yet: none committed (spec item A).",
            "none", "spec-item-A")


def pred_capability_check() -> tuple[str, str, str, str]:
    doctor = REPO_ROOT / "scripts/doctor"
    has_strict = doctor.is_file() and "--strict" in doctor.read_text(
        encoding="utf-8", errors="replace")
    handshake = "scripts/capability-handshake.py"
    if has_strict and is_committed(handshake):
        # Structural presence only. Saying "passes on this host" would assert an
        # execution this predicate never performs.
        return ("passed",
                "**Strict capability check** — handshake committed and "
                "`scripts/doctor --strict` available (not executed here).",
                handshake, "none")
    return ("not-yet",
            "**Strict capability check** — not yet: handshake not committed "
            "(spec item A).", "none", "spec-item-A")


def pred_blackbox() -> tuple[str, str, str, str]:
    d = REPO_ROOT / "tests/blackbox"
    files = [p for p in d.glob("**/*") if p.is_file()] if d.is_dir() else []
    committed = [p for p in files if is_committed(str(p.relative_to(REPO_ROOT)))]
    if committed:
        # "passing" would assert a test run this predicate never performs.
        return ("passed",
                f"**Black-box guard tests** — {len(committed)} committed test file(s) "
                f"(presence only; not executed here).",
                "tests/blackbox", "none")
    return ("not-yet",
            "**Black-box guard tests** — not yet: none committed (spec item D).",
            "none", "spec-item-D")


def pred_release() -> tuple[str, str, str, str]:
    tags = [t for t in git("tag").splitlines() if t.strip()]
    if tags:
        return ("passed", f"**Release** — {tags[-1]}.", "none", "none")
    return ("not-yet", "**Release** — unreleased (no tags).", "none", "spec-item-B")


def pred_os() -> tuple[str, str, str, str]:
    runners: set[str] = set()
    wfs = sorted(list((REPO_ROOT / ".github/workflows").glob("*.yml"))
                 + list((REPO_ROOT / ".github/workflows").glob("*.yaml")))
    for wf in wfs:
        for m in re.finditer(r"runs-on:\s*(\S+)", wf.read_text(encoding="utf-8",
                                                               errors="replace")):
            runners.add(m.group(1).strip().strip("\"'"))
    if runners == {"ubuntu-latest"}:
        return ("partial",
                "**OS** — Ubuntu (CI) only; macOS unverified.",
                ".github/workflows", "none")
    return ("partial", f"**OS** — CI runners: {', '.join(sorted(runners)) or 'none'}.",
            ".github/workflows", "none")


def pred_hero_recording() -> tuple[str, str, str, str]:
    """The recorded session length and the replay's divergence from it (QF-8 disclosure).

    The replay's cadence is the RENDERER's, not the recording's, and the proof beat lands
    well into the loop rather than at landing. That divergence is disclosed with measured
    numbers instead of being closed by a renderer rewrite -- the recorded QF-8 tradeoff.
    """
    f = hero_facts()
    if "duration_conflict" in f:
        declared, recomputed = f["duration_conflict"]
        return ("not-yet",
                f"**Hero recording** — no session length is published: the capture evidence "
                f"records `{declared}` s but the capture's own first and last timestamps "
                f"give `{recomputed}` s, so the figure is withheld until they agree.",
                HERO_EVIDENCE, "hero-disclosure")
    if not f:
        return ("not-yet",
                "**Hero recording** — the hero artifacts could not be read or re-derived at "
                "build time, so no figure is published.", "none", "hero-disclosure")
    return ("passed",
            f"**Hero recording** — the recorded session ran **{f['duration_s']} s**; the "
            f"replay loops every **{f['loop_s']} s** ({f['ratio']}x the recording), and the "
            f"grant-consumed proof line first appears **{f['proof_s']} s** in — "
            f"{f['proof_pct']} % through the loop, not at landing.",
            HERO_EVIDENCE, "none")


def pred_hero_legibility() -> tuple[str, str, str, str]:
    """Whether a reader of the rendered hero can actually READ it, with measured numbers.

    Legibility is a CONJUNCTION and this row asserts both limbs: no line may be cut off at
    the panel's right edge, AND the panel must render at or above the readability floor.

    It previously asserted only the first limb. Widening the panel until nothing was
    truncated therefore turned the row green while the published text shrank and became
    LESS readable -- a row reporting one limb under the name of both. Reporting a criterion
    green while changing nothing a reader experiences is the outcome the glyph floor exists
    to refuse; reaching it by narrowing what the row measures reaches it anyway. So
    `passed` now requires both limbs, and the floor itself is untouched.
    """
    f, g = hero_facts(), glyph_facts()
    if not f or "duration_conflict" in f:
        return ("not-yet",
                "**Hero legibility** — the hero artifacts could not be measured at build "
                "time, so truncation is not reported.", "none", "hero-disclosure")
    if f["clipped_n"]:
        return ("partial",
                f"**Hero legibility** — **{f['clipped_n']} of {f['total_n']}** replayed "
                f"lines run past the {f['logical_w']} px panel and are cut off at its right "
                f"edge; the worst loses **{f['worst_lost']}** characters. The full, "
                f"untruncated text of every line is in the linked capture.",
                HERO_ASSET, "hero-clipping")
    if not g:
        return ("not-yet",
                f"**Hero legibility** — every replayed line fits inside the "
                f"{f['logical_w']} px panel, but the rendered glyph height could not be "
                f"derived at build time, so legibility is reported as unverified rather "
                f"than as passing.", HERO_ASSET, "hero-disclosure")
    if g["below_floor"]:
        n, total = len(g["below_floor"]), g["n_covered"]
        where = "every" if n == total else f"{n} of {total}"
        return ("partial",
                f"**Hero legibility** — nothing is cut off: every replayed line fits inside "
                f"the {f['logical_w']} px panel. But fitting them took a panel that wide, "
                f"and the page scales it down to fit the column, so the inline text lands "
                f"below the {g['floor_px']} px readability floor at {where} measured "
                f"viewport. Un-truncated is not the same as readable, so this is reported "
                f"as partial, with the measured sizes below.",
                HERO_ASSET, "hero-glyph-floor")
    return ("passed",
            f"**Hero legibility** — every replayed line fits inside the {f['logical_w']} px "
            f"panel, nothing is cut off, and the inline text clears the {g['floor_px']} px "
            f"readability floor at every measured viewport.", HERO_ASSET, "none")


def pred_hero_glyph() -> tuple[str, str, str, str]:
    """The measured size the hero actually renders at — what a phone reader cannot see.

    The first screen must state with MEASURED NUMBERS what a phone reader cannot make out.
    While the hero was truncated, the truncation count carried that obligation; once the
    panel was widened the count went to zero and the obligation was left with nothing
    discharging it. This row discharges it, inside the same byte-compared canonical fence,
    derived at build time exactly as the recorded duration is.
    """
    g = glyph_facts()
    if not g:
        return ("not-yet",
                "**Hero inline size** — the replay's rendered glyph height could not be "
                "derived at build time, so no figure is published.",
                "none", "hero-disclosure")
    sizes = " and ".join(f"**{px:g} px** at a {w} px viewport"
                         for w, px in g["per_viewport"])
    if not g["below_floor"]:
        return ("passed",
                f"**Hero inline size** — the replay's text renders at {sizes}, clearing the "
                f"{g['floor_px']} px readability floor at every measured viewport.",
                MEASURE_SCRIPT, "none")
    n, total = len(g["below_floor"]), g["n_covered"]
    where = "every" if n == total else f"{n} of {total}"
    return ("partial",
            f"**Hero inline size** — the replay's text renders at {sizes}, against the "
            f"**{g['floor_px']} px** readability floor it misses at {where} measured "
            f"viewport. Below that floor the transcript is on the page but too small to "
            f"read there — on a phone it is roughly a third of readable size. Nothing is "
            f"cut off; it is scaled down. Read it at full size in the linked capture.",
            MEASURE_SCRIPT, "hero-glyph-floor")


def _counts(by: dict) -> str:
    """'50 advisory, 28 detected, 0 enforced': every value of a closed set, with its count."""
    return ", ".join(f"**{n}** {label}" for label, n in by.items())


def pred_enforcement_strength() -> tuple[str, str, str, str]:
    """How far the ledger's rows are proven: their behavior labels and proof layers, counted.

    partial while any row is short of host-observed (today: none is). The text always says what
    an exit code is evidence of, because a reader who sees `enforced` or `detected` next to a hook
    would otherwise take it for a measurement of a Claude Code host.
    """
    ledger = "docs/ENFORCEMENT-LEDGER.md"
    try:
        e = fact("enforcement_strength")
    except FactUnavailable:
        return ("not-yet",
                f"**Enforcement strength** — `{ledger}` could not be read and reconciled with the "
                f"tracked `settings.json` at build time, so no figure is published.",
                "none", "none")
    rows, observed = e["rows"], e["by_proof_layer"].get("host-observed", 0)
    detail = (f"Behavior labels: {_counts(e['by_behavior'])}. "
              f"Proof layers: {_counts(e['by_proof_layer'])}.")
    if observed == rows:
        return ("passed",
                f"**Enforcement strength** — all **{rows}** ledger rows are host-observed. {detail}",
                ledger, "none")
    seen = ("No row is host-observed." if observed == 0
            else f"**{observed}** of the {rows} rows are host-observed.")
    return ("partial",
            f"**Enforcement strength** — the ledger has **{rows}** rows, one per registered hook. "
            f"{detail} {seen} A script that exits 2 is evidence about the script, not about a "
            f"Claude Code host honouring it.",
            ledger, "none")


def _reasons(by_reason: dict) -> str:
    """'**19** × <reason>; **1** × <reason>': the enumerator's own reasons, most frequent first."""
    ranked = sorted(by_reason.items(), key=lambda kv: (-kv[1], kv[0]))
    return "; ".join(f"**{n}** × {reason}" for reason, n in ranked)


def pred_dead_end_sites() -> tuple[str, str, str, str]:
    """How many blocking sites have no clearing class, why, and what the suite does and does not assert.

    The row id says dead-end because the suite's own word for such a site is a dead end, but a site
    the enumerator cannot class is not thereby a stranding: its stated reasons are counted here
    (most are a hook refusing because it cannot decide), and nothing here calls it one. The suite
    fails when a REPLAY reaches such a site; it does not fail because one exists. So zero replays
    reaching one is not a proof that no flow can, and the row says so. It reads `passed` only if
    there is no such site AND the suite asserts there can be none.
    """
    test = "tests/replay/test_no_dead_end.py"
    label = "**Blocking sites with no clearing class**"
    try:
        b, ci = fact("blocking_sites"), fact("ci_enforces")
    except FactUnavailable:
        return ("not-yet",
                f"{label} — the blocking sites of the registered hooks could not be "
                "enumerated at build time, so no figure is published.", "none", "none")
    n, total = b["no_class"], b["sites"]
    asserted = ci["no_site_without_class"]["holds"]
    if n == 0 and asserted:
        return ("passed",
                f"{label} — none of the **{total}** blocking sites of the registered "
                f"hooks lacks a clearing class, and the suite fails if one does.", test, "none")
    if n == 0:
        return ("partial",
                f"{label} — none of the **{total}** blocking sites of the registered "
                f"hooks lacks a clearing class as counted here, but the suite does not assert "
                f"that; it fails only when a replay reaches one. This is a known limit, not a "
                f"proof that there are none.", test, "none")
    reasons = b.get("no_class_reasons") or {}
    why = f" The enumerator's reasons: {_reasons(reasons)}." if reasons else ""
    return ("partial",
            f"{label} — **{n} of {total}** blocking sites of the registered hooks have no "
            f"clearing class.{why} The suite fails only when a replay reaches one, so this is a "
            f"known limit and not a proof that there are none.", test, "none")


PREDICATES = {
    "known-limits": pred_known_limits,
    "hero-recording": pred_hero_recording,
    "hero-legibility": pred_hero_legibility,
    "hero-glyph": pred_hero_glyph,
    "supported-builds": pred_supported_builds,
    "capability-check": pred_capability_check,
    "blackbox-tests": pred_blackbox,
    "release": pred_release,
    "os": pred_os,
    "enforcement-strength": pred_enforcement_strength,
    "dead-end-sites": pred_dead_end_sites,
}

# Which canonical region each row renders into.
REGION_OF = {"known-limits": "limits", "hero-recording": "disclosure",
             "hero-legibility": "disclosure", "hero-glyph": "disclosure"}
for _r in ROW_IDS:
    REGION_OF.setdefault(_r, "status")

# Regions whose rows render as prose rather than list items.
PROSE_REGIONS = {"limits", "disclosure"}


def render_rows() -> dict[str, list[tuple[str, str]]]:
    """-> {region_id: [(marker_line, visible_line), ...]} in ROW_IDS order."""
    out: dict[str, list[tuple[str, str]]] = {rid: [] for rid in CLAIM_REGIONS}
    for rid in ROW_IDS:
        state, text, evidence, tracked = PREDICATES[rid]()
        if state not in STATES:
            raise SystemExit(f"generator emitted an out-of-enum state for {rid}: {state}")
        marker = (f"<!-- claim-row id={rid} state={state} "
                  f"evidence={evidence} tracked={tracked} -->")
        visible = text if REGION_OF[rid] in PROSE_REGIONS else f"- {text}"
        out[REGION_OF[rid]].append((marker, visible))
    return out


# --------------------------------------------------------------------------------------
# The count regions: markdown tables, every figure from scripts/readme_facts.py. A fact that
# cannot be derived raises FactUnavailable out of the renderer, naming the input; nothing is
# defaulted, because a stale value printed in its place is exactly what these regions exist to
# refuse. The words around the figures (a row's label, what CI fails on) are prose; the sentence
# that says a CI check holds is printed only when readme_facts' ci_enforces says the check's
# assertion is there, and otherwise the cell says what is NOT asserted.
# --------------------------------------------------------------------------------------

PROOF_HEADER = ("Counted from the repository", "Now", "CI fails when")
COMMANDS_HEADER = ("Command", "Group", "Typed by", "What it does")
AGENTS_HEADER = ("Agent", "What it does")

_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)


def _escape_prose(text: str) -> str:
    return (text.replace("\\", "\\\\").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace("|", "\\|"))


def md_cell(text: object) -> str:
    """`text` made safe for one cell of a pipe table.

    A pipe is escaped everywhere, inside a code span too (a table splits on it first); angle
    brackets and the ampersand are escaped outside code spans so that a summary can be neither
    read as HTML nor decode an entity; inside a code span they are literal already. Line breaks
    become spaces, because a cell is one line.
    """
    text = " ".join(str(text).split())
    out, last = [], 0
    for m in _CODE_SPAN.finditer(text):
        out.append(_escape_prose(text[last:m.start()]))
        out.append(m.group(0).replace("|", "\\|"))
        last = m.end()
    out.append(_escape_prose(text[last:]))
    return "".join(out)


def code_span(text: str) -> str:
    """`text` as an inline code span (a fence longer than any backtick run inside it)."""
    longest = max((len(r) for r in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def table(header: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _n(value: int) -> str:
    return f"{value:,}"


def _not_asserted(verdict: dict) -> str:
    return f"not asserted: {verdict['claim']} (`{verdict['file']}`)"


def render_proof() -> str:
    versions, replay = fact("ci_python_versions"), fact("replay_suite_size")
    sites, arts = fact("blocking_sites"), fact("static_artifacts")
    tests, hooks, ci = fact("count_tests"), fact("hook_registrations"), fact("ci_enforces")
    rf = facts_module()

    compliant = ci["compliant_replays_clean"]
    pipelines_ci = (f"a compliant replay that meets a gate block or a hook error, or does not reach "
                    f"its terminal, fails CI (`{compliant['file']}`)"
                    if compliant["holds"] else _not_asserted(compliant))

    faults = ci["faults_returned_and_repaired"]
    regressions = f"; the regression replays are in `{rf.REPLAY_REGRESSIONS_TEST}`"
    faults_ci = (f"a fault that no gate returns to its producer, or that its producer does not repair "
                 f"without human action, fails CI for {len(faults['ids'])} of the "
                 f"{replay['fault_ids']} variants (`{faults['file']}`)"
                 if faults["holds"] else _not_asserted(faults)) + regressions

    by = sites["by_class"]
    unreachable = f", {by['U']} unreachable" if by.get("U") else ""
    sites_now = (f"{sites['sites']} sites: {by['G']} own-obligation gates, {by['D']} denials of a "
                 f"forbidden operation, {by['H']} time-lock{unreachable}; {sites['no_class']} "
                 f"with no clearing class")
    strong, weaker = ci["no_site_without_class"], ci["no_site_without_class"]["weaker"]
    if strong["holds"]:
        sites_ci = f"a blocking site with no clearing class fails CI (`{strong['file']}`)"
    elif weaker["holds"]:
        # The weaker claim is the one the suite makes. That no such site exists is not asserted.
        sites_ci = (f"a replay that reaches a blocking site with no clearing class fails CI "
                    f"(`{weaker['file']}`)")
    else:
        sites_ci = _not_asserted({"claim": weaker["claim"], "file": weaker["file"]})

    artifact = ci["artifact_check_clean"]
    artifacts_ci = ("an artifact without one producer or without a deciding reader fails the check, "
                    f"which keeps no exception list (`{artifact['file']}`)"
                    if artifact["holds"] else _not_asserted(artifact))

    h, t = tests["hooks_tests"], tests["tests"]
    unit = ci["unit_suite_on_every_version"]
    left_out = ", ".join(f"`{p}`" for p in unit.get("ignored", []))
    tests_ci = (f"the unit suite fails on any of {', '.join(unit['versions'])}"
                + (f" (it leaves out {left_out})" if left_out else "")
                if unit["holds"] else _not_asserted(unit))

    events = ", ".join(f"{e} {n}" for e, n in sorted(hooks["by_event"].items(), key=lambda kv: (-kv[1], kv[0])))

    rows = [
        ("Python versions CI runs the baseline job on", ", ".join(versions),
         f"a step of the baseline job fails on any of them (`{rf.BASELINE_WORKFLOW}`)"),
        ("Pipelines replayed",
         f"{replay['pipelines']} pipelines, {replay['compliant_scenarios']} compliant scenarios, "
         f"{len(replay['settings_modes'])} settings modes ({', '.join(replay['settings_modes'])}), "
         f"{replay['compliant_replays']} compliant replays", pipelines_ci),
        ("Faults injected",
         f"{replay['fault_classes']} fault classes in {replay['fault_ids']} variants; "
         f"{replay['regression_replays']} regression replays ({', '.join(replay['regression_ids'])})",
         faults_ci),
        ("Blocking sites of the registered hooks", sites_now, sites_ci),
        (arts["label"],
         f"{arts['declared_file_artifacts']} (distinct path patterns, from {arts['artifact_declarations']} "
         f"declarations in {arts['obligation_templates']} obligation templates)", artifacts_ci),
        ("Tests, counted statically (parametrization not expanded)",
         f"{_n(h['test_functions'] + t['test_functions'])} test functions in {h['files'] + t['files']} files: "
         f"`hooks/tests` {_n(h['test_functions'])} in {h['files']} files, `tests` "
         f"{_n(t['test_functions'])} in {t['files']} files", tests_ci),
        ("Hook registrations in the tracked `settings.json`",
         f"{hooks['entries']} entries in {hooks['events']} events ({events})",
         f"ledger rows that differ from the registered hooks fail `{rf.GATE_SCRIPT}`"),
    ]
    return table(PROOF_HEADER, [tuple(md_cell(c) for c in r) for r in rows])


def render_commands() -> str:
    """The command surface: every command but an optional module's own, by group (in the order of
    readme_facts' COMMAND_GROUPS) and then by name, each with its frontmatter summary as written."""
    rows = fact("command_rows")
    order = {g: i for i, g in enumerate(facts_module().COMMAND_GROUPS)}
    shown = sorted((c for c in rows if not c["module"]), key=lambda c: (order[c["group"]], c["name"]))
    lines = []
    for c in shown:
        usage = f"/{c['name']}" + (f" {c['argument_hint']}" if c["argument_hint"] else "")
        lines.append((md_cell(code_span(usage)), c["group"], "owner only" if c["human_only"] else "owner or agent",
                      md_cell(c["summary"])))
    note = f"{len(shown)} commands, generated from the frontmatter of `commands/*.md`."
    if len(shown) < len(rows):
        note += (" An optional module's own commands are described with the module in the "
                 "[installation guide](docs/installation.md).")
    return table(COMMANDS_HEADER, lines) + "\n\n" + note


def render_agents() -> str:
    """The cast of agents, by name, each with its frontmatter summary as written."""
    rows = fact("agent_rows")
    lines = [(md_cell(code_span(a["name"])), md_cell(a["summary"])) for a in rows]
    return (table(AGENTS_HEADER, lines) + "\n\n"
            + f"{len(rows)} agents, generated from the frontmatter of `agents/*.md`.")


COUNT_RENDERERS = {"proof": render_proof, "commands": render_commands, "agents": render_agents}


def render_region(rid: str, body: object) -> str:
    """The region as it must read in its document: BEGIN marker, body, END marker. `body` is the table
    of a count region, or a claim region's [(marker_line, visible_line), ...]."""
    if not isinstance(body, str):
        body = "\n".join(f"{m}\n{v}" for m, v in body)
    return f"{BEGIN.format(rid=rid)}\n{body}\n{END.format(rid=rid)}"


def region_span(text: str, rid: str) -> tuple[int, int] | None:
    b, e = BEGIN.format(rid=rid), END.format(rid=rid)
    i, j = text.find(b), text.find(e)
    if i < 0 or j < 0 or j < i:
        return None
    return i, j + len(e)


def parse_committed_rows(region_text: str) -> list[tuple[str, str, dict]]:
    """-> [(marker_line, visible_line, parsed_marker_fields)] for each claim-row."""
    lines = region_text.splitlines()
    out = []
    for idx, ln in enumerate(lines):
        m = MARKER_RE.match(ln.strip())
        if m:
            visible = lines[idx + 1] if idx + 1 < len(lines) else ""
            out.append((ln.strip(), visible, m.groupdict()))
    return out


# --------------------------------------------------------------------------------------
# Reading the markdown: what is a fence, a comment, a code span. One sequential scan, in the order
# a renderer reads: blocks first (a fence or an HTML comment that starts a line), then, inside one
# paragraph, list item, table cell or heading at a time, whichever of a code span and an inline
# comment comes first. The position rule needs the blocks; the number rule needs all of it.
# --------------------------------------------------------------------------------------

_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_LIST_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)")
_HEADING_LINE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
_BREAK_LINE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_TABLE_DELIM = re.compile(r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")

UNCLOSED_FENCE = ("the code fence opened here is never closed, so the rest of the file is hidden from "
                  "the no-hand-typed-number rule")
UNCLOSED_COMMENT = ("the HTML comment opened here is never closed, so the rest of the file is hidden "
                    "from the no-hand-typed-number rule")
UNCLOSED_INLINE_COMMENT = ("the HTML comment opened here is not closed in the same paragraph, so the "
                           "page shows it as text; close it or remove it")
UNBALANCED_SPAN = ("the backtick run here has no closing run of the same length in its paragraph, list "
                   "item, table cell or heading (a code span never pairs across them), so it hides "
                   "nothing; close it, or escape the backtick with a backslash")


def _blank(match: re.Match) -> str:
    """The matched text with every character but a line break replaced by a space: offsets and line
    numbers survive."""
    return re.sub(r"[^\n]", " ", match.group(0))


def _table_lines(lines: list[str]) -> set[int]:
    """Indexes of the lines of GFM tables: a header, a delimiter row, and the rows up to a blank line."""
    marked: set[int] = set()
    for k in range(len(lines) - 1):
        head, delim = lines[k], lines[k + 1]
        if head.strip() and "|" in head + delim and _TABLE_DELIM.match(delim):
            j = k
            while j < len(lines) and lines[j].strip():
                marked.add(j)
                j += 1
    return marked


def _scan_inline(text: str, a: int, b: int, blank, problems: list, lineno) -> None:
    """Blank the code spans and inline comments of text[a:b], one paragraph, list item, table cell or
    heading. A backtick run without a closing run of its own length, and a comment without a closer
    in the same unit, are problems and hide nothing."""
    i = a
    while i < b:
        c = text[i]
        if c == "\\":
            i += 2
        elif c == "`":
            j = i
            while j < b and text[j] == "`":
                j += 1
            n, k, close = j - i, j, None
            while k < b:
                if text[k] != "`":
                    k += 1
                    continue
                m = k
                while m < b and text[m] == "`":
                    m += 1
                if m - k == n:
                    close = k
                    break
                k = m
            if close is None:
                problems.append((lineno(i), UNBALANCED_SPAN))
                i = j
            else:
                blank(i, close + n)
                i = close + n
        elif text.startswith("<!--", i):
            k = text.find("-->", i + 2, b)
            if k < 0:
                problems.append((lineno(i), UNCLOSED_INLINE_COMMENT))
                i += 4
            else:
                blank(i, k + 3)
                i = k + 3
        else:
            i += 1


def _scan(text: str, inline: bool = True) -> tuple[str, list[tuple[int, str]]]:
    """-> (text with the hidden parts blanked, [(line number, problem)]).

    Hidden: fenced code blocks, HTML comments, and with `inline` the code spans (and comments that
    start mid-line). A fence or a comment that is never closed is a problem, and so is an inline
    construct that cannot be read as one (see _scan_inline)."""
    masked = list(text)
    problems: list[tuple[int, str]] = []

    def blank(a: int, b: int) -> None:
        for k in range(a, b):
            if masked[k] != "\n":
                masked[k] = " "

    def lineno(offset: int) -> int:
        return text.count("\n", 0, offset) + 1

    lines = text.split("\n")
    starts, offset = [], 0
    for ln in lines:
        starts.append(offset)
        offset += len(ln) + 1
    in_table = _table_lines(lines) if inline else set()
    fence = None            # (character, length, line number) while inside a fenced block
    comment_line = None     # line number of a comment that starts a line and is still open
    unit = None             # [start, end) of the paragraph or list item being collected

    def flush() -> None:
        nonlocal unit
        if unit is not None and inline:
            _scan_inline(text, unit[0], unit[1], blank, problems, lineno)
        unit = None

    def add(a: int, b: int) -> None:
        nonlocal unit
        unit = [a, b] if unit is None else [unit[0], b]

    for k, line in enumerate(lines):
        s = starts[k]
        e = s + len(line)
        if fence is not None:
            blank(s, e)
            closing = _FENCE_OPEN.match(line)
            if (closing and closing.group(1)[0] == fence[0] and len(closing.group(1)) >= fence[1]
                    and not closing.group(2).strip()):
                fence = None
            continue
        begin = s                       # where the part of this line that is still text begins
        if comment_line is not None:
            end = text.find("-->", s, e)
            if end < 0:
                blank(s, e)
                continue
            blank(s, end + 3)
            comment_line, begin = None, end + 3
        else:
            opener = _FENCE_OPEN.match(line)
            if opener and not (opener.group(1)[0] == "`" and "`" in opener.group(2)):
                flush()
                blank(s, e)
                fence = (opener.group(1)[0], len(opener.group(1)), k + 1)
                continue
            lead = re.match(r" {0,3}<!--", line)
            if lead:  # an HTML block: it may run over blank lines, to the first closer
                flush()
                end = text.find("-->", s + lead.end() - 2, e)
                if end < 0:
                    blank(s, e)
                    comment_line = k + 1
                    continue
                blank(s, end + 3)
                begin = end + 3
        if not text[begin:e].strip():
            flush()
            continue
        if begin == s and inline:
            if k in in_table:
                flush()
                if not _TABLE_DELIM.match(line):
                    cell, cut = s, [m.end() for m in _UNESCAPED_PIPE.finditer(line)]
                    for stop in [c + s - 1 for c in cut] + [e]:
                        _scan_inline(text, cell, stop, blank, problems, lineno)
                        cell = stop + 1
                continue
            if _HEADING_LINE.match(line):
                flush()
                _scan_inline(text, s, e, blank, problems, lineno)
                continue
            if _BREAK_LINE.match(line):
                flush()
                continue
            if _LIST_ITEM.match(line):
                flush()
        add(begin, e)
    flush()
    if fence is not None:
        problems.append((fence[2], UNCLOSED_FENCE))
    if comment_line is not None:
        problems.append((comment_line, UNCLOSED_COMMENT))
    return "".join(masked), sorted(problems)


# --------------------------------------------------------------------------------------
# Position: where each region sits, not only what it says.
# --------------------------------------------------------------------------------------

_MARKER_ANY = re.compile(r"<!-- (BEGIN|END) canonical-region id=(\S+)")


def headings(text: str) -> list[tuple[int, str, int]]:
    """-> [(level, title, offset of the heading line)] for the ATX headings that are real headings:
    not inside a fenced block or an HTML comment."""
    visible, _problems = _scan(text, inline=False)
    out = []
    for m in re.finditer(r"(?m)^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$", visible):
        out.append((len(m.group(1)), m.group(2).strip(), m.start()))
    return out


def assert_region_positions(text: str, doc: str) -> list[str]:
    """Each region's POSITION, not merely its bytes, in document `doc` ("readme" or "status").

    The byte-compare refuses any edit to a region's CONTENT but is blind to the region being MOVED:
    a limits statement lifted out of "Status and known limits" into a section nobody reads still
    passes every byte-level assertion. So, per region of this document (DOC_REGIONS): exactly one
    BEGIN/END pair, lying inside the H2 section named for it in SECTION_OF; the regions disjoint
    (one's END below another's BEGIN would make write mode delete what lies between); and the claim
    regions in the order limits, disclosure, status. A marker that names no region, or a region of
    the other document, is a violation too. Every violation names the region.
    """
    out = _stray_markers(text, doc)
    heads = headings(text)
    spans: dict[str, tuple[int, int]] = {}
    for rid in DOC_REGIONS[doc]:
        span, problem = _one_span(text, rid)
        problem = problem or _section_problem(text, heads, rid, span)
        if span is not None:
            spans[rid] = span
        if problem:
            out.append(f"[region-position] region {rid!r}{problem}")
    return out + _overlaps(spans) + _out_of_order(spans)


def _stray_markers(text: str, doc: str) -> list[str]:
    """A marker that names no region, or a region of the other document."""
    out = []
    for kind, rid in sorted({(m.group(1), m.group(2)) for m in _MARKER_ANY.finditer(text)}):
        if rid not in REGION_IDS:
            out.append(f"[region-position] a {kind} marker names region {rid!r}, which is none of "
                       f"{', '.join(REGION_IDS)}")
        elif rid not in DOC_REGIONS[doc]:
            out.append(f"[region-position] a {kind} marker of region {rid!r} is in {DOC_NAME[doc]}; the region "
                       f"belongs in {DOC_NAME[DOCUMENT_OF[rid]]}")
    return out


def _one_span(text: str, rid: str) -> tuple[tuple[int, int] | None, str | None]:
    """(the region's one span, None), or (None, why it has no single span, as it follows the region's name)."""
    begins, ends = text.count(BEGIN.format(rid=rid)), text.count(END.format(rid=rid))
    if begins == 0 and ends == 0:
        return None, " is missing: no BEGIN/END marker pair in the document"
    if begins > 1 or ends > 1:
        return None, f" is duplicated: {begins} BEGIN and {ends} END markers, expected one of each"
    span = region_span(text, rid)
    if span is None:
        return None, f" has {begins} BEGIN and {ends} END markers, but not a BEGIN followed by an END"
    return span, None


def _section_problem(text: str, heads: list, rid: str, span: tuple[int, int]) -> str | None:
    """Why the region's span is not inside its one H2 section (SECTION_OF), as it follows the region's name; or None."""
    title = SECTION_OF[rid]
    sections = [(i, h) for i, h in enumerate(heads) if h[0] == 2 and h[1] == title]
    if not sections:
        return f" has no H2 section {title!r} to sit in"
    if len(sections) > 1:
        return f": the H2 heading {title!r} appears {len(sections)} times; its section is ambiguous"
    i, (_level, _title, start) = sections[0]
    stop = next((h[2] for h in heads[i + 1:] if h[0] <= 2), len(text))
    if start <= span[0] and span[1] <= stop:
        return None
    where = next((h[1] for h in reversed(heads) if h[0] == 2 and h[2] <= span[0]), "no H2 section")
    return f" lies outside the H2 section {title!r} (it sits under {where!r})"


def _overlaps(spans: dict[str, tuple[int, int]]) -> list[str]:
    ordered = sorted(spans, key=lambda rid: spans[rid][0])
    return [f"[region-position] region {before!r} overlaps region {after!r}: its END marker lies below the BEGIN "
            f"marker of {after!r}, so rewriting one would delete the other and what lies between"
            for before, after in zip(ordered, ordered[1:]) if spans[before][1] > spans[after][0]]


def _out_of_order(spans: dict[str, tuple[int, int]]) -> list[str]:
    present = [rid for rid in CLAIM_REGIONS if rid in spans]
    found = sorted(present, key=lambda rid: spans[rid][0])
    return [f"[region-position] region {rid!r} is out of order: the claim regions appear as {', '.join(found)}, "
            f"expected {', '.join(present)}" for rid in present if found.index(rid) != present.index(rid)]


# --------------------------------------------------------------------------------------
# Numbers: none typed by hand in the prose.
# --------------------------------------------------------------------------------------

_REGION_BLOCK = re.compile(r"<!-- BEGIN canonical-region id=[a-z-]+ .*?-->.*?<!-- END canonical-region id=[a-z-]+ -->", re.S)
_HTML_CODE = re.compile(r"<(code|pre|kbd|samp)\b[^>]*>.*?</\1\s*>", re.S | re.I)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)|!\[[^\]]*\]\[[^\]]*\]")
_LINK_TARGET = re.compile(r"\]\((?:[^()\s]|\([^()]*\))*(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
_REFERENCE = re.compile(r"(?m)^ {0,3}\[[^\]]+\]:[ \t]*\S.*$")
_BARE_URL = re.compile(r"https?://[^\s<>\]\)]+")
_HTML_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9:-]*(?:\"[^\"<]*\"|'[^'<]*'|[^'\"<>])*>")
_ENTITY = re.compile(r"&#?[A-Za-z0-9]+;")
_LIST_MARKER = re.compile(r"(?m)^[ \t>]*\d{1,9}[.)](?=[ \t]|$)")
# A numeral: digits, with . or , between digit groups. Not one when a letter, a digit, a dot or a
# comma comes right before it (python3, L8, v1.2.3, R-E1 are names, not numbers). An underscore does
# not shield it: `_6_` is emphasis around a number, and a name with a number in it belongs in a code span.
_NUMERAL = re.compile(r"(?<![^\W_]|[.,])\d+(?:[.,]\d+)*")


def _prose(text: str) -> tuple[str, list[tuple[int, str]]]:
    """-> (the prose of `text`, the places where it could not be told from what is hidden).

    Blanked, offsets and lines kept: the canonical regions, fenced blocks, HTML comments, code
    (spans, and <code>/<pre> elements), images, link targets and titles, reference definitions,
    URLs, HTML tags with their attributes, entities and ordered-list markers."""
    view, problems = _scan(_REGION_BLOCK.sub(_blank, text))
    view = _HTML_CODE.sub(_blank, view)
    for pattern in (_IMAGE, _LINK_TARGET, _REFERENCE, _HTML_TAG, _BARE_URL, _ENTITY):
        view = pattern.sub(_blank, view)
    return _LIST_MARKER.sub(_blank, view), problems


def prose_view(text: str) -> str:
    """`text` with everything the number rule does not read blanked, offsets and lines kept."""
    return _prose(text)[0]


def prose_numerals(text: str) -> list[tuple[int, str]]:
    """-> [(line number, numeral)] for every numeral in the prose of `text`, in order."""
    view = prose_view(text)
    return [(view.count("\n", 0, m.start()) + 1, m.group(0)) for m in _NUMERAL.finditer(view)]


def assert_no_hand_typed_numbers(text: str, doc: str) -> list[str]:
    """A numeral in the prose of document `doc` outside the canonical regions is a violation, unless
    the document is README.md and the numeral is one of the CITED_FIGURES. Also a violation, in the
    README: a source URL missing from it, and a declared figure that its prose no longer holds (a
    stale entry would excuse a number that is gone, and quietly keep a hole open for the next one);
    and, in either document, every place where the prose cannot be read as prose (a fence or comment
    never closed, a backtick that closes nothing), because the rule would then be blind to what that
    hides. Every violation names the line, and a stray numeral its number."""
    out: list[str] = []
    lines = text.splitlines()
    cited = CITED_FIGURES if doc == "readme" else ()
    declared = {figure for figure, _url in cited}
    view, problems = _prose(text)
    for number, why in problems:
        out.append(f"[number-rule] line {number}: {why}")
    numerals = [(view.count("\n", 0, m.start()) + 1, m.group(0)) for m in _NUMERAL.finditer(view)]
    for number, numeral in numerals:
        if numeral not in declared:
            out.append(f"[hand-typed-number] line {number}: the numeral {numeral!r} is typed by hand in "
                       f"the prose ({lines[number - 1].strip()[:80]!r}); derive it in a canonical region, "
                       f"or declare it in CITED_FIGURES with the URL it comes from")
    present = {numeral for _number, numeral in numerals}
    for figure, url in cited:
        if url not in text:
            out.append(f"[cited-figure] the source of {figure!r}, {url}, is absent from the README")
        if figure not in present:
            out.append(f"[cited-figure] the declared figure {figure!r} (source {url}) no longer appears "
                       f"in the prose; remove it from CITED_FIGURES")
    return out


def assert_no_internal_names(text: str) -> list[str]:
    """README.md, the front page, names no internal name (readme_facts' INTERNAL_NAME: an optional
    module's own name, a borrowed tool name, a model id) anywhere, regions and markup included. Every
    violation names the line and the name."""
    try:
        pattern = facts_module().INTERNAL_NAME
    except FactUnavailable as exc:
        return [f"[internal-name] the internal names cannot be read, so they cannot be checked: {exc}"]
    return [f"[internal-name] line {n}: the front page names {m.group(0)!r}, an internal name; describe it "
            f"without the name or move it off the front page"
            for n, line in enumerate(text.splitlines(), 1) for m in pattern.finditer(line)]


# --------------------------------------------------------------------------------------
# The fold measurement: only its report of glyph-model drift is consumed.
# --------------------------------------------------------------------------------------

def assert_glyph_model(page: Path, script: Path | None = None) -> tuple[list[str], list[str], bool]:
    """-> (violations, notes, measured). Run the fold measurement and fail on its report of glyph-model drift.

    `measured` is True only when the measurement ran and compared the model with a browser. When it
    could not run (the Python playwright package and a Chromium are not installed by a default
    checkout or by the baseline CI job) the published glyph figures are model predictions, and the
    caller must not say otherwise.

    The disclosure region publishes a glyph height derived from the fold script's model rather
    than from a browser, because a status row must regenerate anywhere while that measurement needs
    Chromium. `model_drift` is the fold script's own report that its model and its live
    measurement disagree, and consuming it here is what makes the published figure MEASURED rather
    than merely modelled.

    Deliberately NOT the whole returncode or the whole failures list: those also carry the
    glyph-floor verdict and the old above-the-fold assertions on a headline that no longer exists,
    and importing them here would make them block this ratchet -- a scope change no ruling has
    made, arrived at as a side effect. The floor stays disclosed and un-gated; only the honesty of
    the published number is enforced.

    `page` is the document that holds the hero (docs/status.md, or a --status copy). The script
    runs from the repository root, so a relative path is made absolute first.
    """
    script = script or REPO_ROOT / MEASURE_SCRIPT
    if not script.is_file():
        return ([], [f"[fold] {script.name} is absent; the glyph-model measurement did NOT run"], False)
    try:
        r = subprocess.run([sys.executable, str(script), "--doc", str(Path(page).resolve())],
                           cwd=REPO_ROOT, capture_output=True, text=True, timeout=600)
    except Exception as exc:  # noqa: BLE001 - it could not even start
        return ([], [f"[fold] the fold measurement could not be executed ({type(exc).__name__}: {exc}); "
                     f"the published glyph figure is a model prediction, UNVERIFIED in this environment"], False)
    try:
        data = json.loads(r.stdout)
    except ValueError:
        tail = next((l.strip() for l in reversed(r.stderr.splitlines()) if l.strip()), "no output")
        return ([], [f"[fold] the fold measurement produced no report (exit {r.returncode}: {tail[:160]}); "
                     f"the published glyph figure is a model prediction, UNVERIFIED in this environment"], False)
    results = data.get("results") or []
    if not results:
        return (["[fold] the fold measurement produced no combinations to compare the glyph model with"], [], False)
    out = [f"[fold] {drift}" for drift in data.get("model_drift") or []]
    return (out, [f"[fold] glyph model compared with the browser over {len(results)} combinations "
                  f"(local preview, not GitHub's rendering)"], True)


# --------------------------------------------------------------------------------------
# The two commands.
# --------------------------------------------------------------------------------------

def expected_regions() -> tuple[dict[str, str], dict[str, str], dict[str, list[tuple[str, str]]]]:
    """-> ({region_id: its regenerated text}, {region_id: why it cannot be computed}, the claim rows).

    A claim region always can be (its rows degrade to not-yet). A count region whose facts cannot
    be derived is reported with the reason and has no expected text: nothing stands in for it."""
    rows = render_rows()
    regions = {rid: render_region(rid, rows[rid]) for rid in CLAIM_REGIONS}
    failed: dict[str, str] = {}
    for rid in COUNT_REGIONS:
        try:
            regions[rid] = render_region(rid, COUNT_RENDERERS[rid]())
        except FactUnavailable as exc:
            failed[rid] = str(exc)
    return regions, failed, rows


def read_doc(path: Path) -> tuple[bytes, str]:
    """A document's bytes and its text, with no newline translation: what is compared is what is on disk."""
    raw = path.read_bytes()
    return raw, raw.decode("utf-8")


def carriage_return_line(text: str) -> int | None:
    """The line of the first carriage return in `text`, or None."""
    at = text.find("\r")
    return None if at < 0 else text.count("\n", 0, at) + 1


def line_ending_problem(text: str, doc: str) -> str | None:
    row = carriage_return_line(text)
    if row is None:
        return None
    return (f"[line-endings] line {row} of {DOC_NAME[doc]} has a carriage return; the regions are "
            f"byte-compared as LF text, so a CRLF document is refused, not rewritten: convert it to LF first")


def write_atomic(path: Path, data: bytes) -> None:
    """Replace `path` with `data` so that no reader, and no kill or full disk, ever sees it empty or
    partial: the bytes go to a temporary file in the same directory (same file system), are flushed
    to disk, take the old file's permissions, and are renamed over it. A symbolic link is followed,
    so the link stays."""
    target = Path(os.path.realpath(path))
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        shutil.copymode(target, tmp)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:  # make the rename durable too; best effort, not every file system allows it
        dfd = os.open(str(target.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def refuse(paths, reasons: list[str]) -> int:
    for why in reasons:
        print(f"generate-hero-status: FAIL: {why}", file=sys.stderr)
    for path in paths:
        print(f"generate-hero-status: write refused; {path} was NOT touched", file=sys.stderr)
    return 1


def bind(readme: Path, status: Path) -> dict[str, Path]:
    """Point the predicates at the documents under evaluation, so the rows' numbers come from the same
    documents the comparison reads. Bound by every command rather than only by main(), so an importer
    that calls cmd_write or cmd_check directly measures what it compares."""
    global README_PATH, STATUS_PATH
    README_PATH, STATUS_PATH = readme, status
    return {"readme": readme, "status": status}


def splice(text: str, regions: dict[str, str], doc: str) -> str:
    """`text` with each of the document's regions replaced by its regenerated text."""
    spans = sorted((region_span(text, rid), rid) for rid in DOC_REGIONS[doc])
    pieces, at = [], 0
    for (begin, end), rid in spans:
        pieces += [text[at:begin], regions[rid]]
        at = end
    return "".join(pieces + [text[at:]])


def cmd_write(readme: Path, status: Path) -> int:
    paths = bind(readme, status)
    loaded = {doc: read_doc(path) for doc, path in paths.items()}
    # The cheap preconditions first, before the facts (several seconds of work) are derived, and
    # before anything is replaced: replacing a span that overlaps another, or that is not where it
    # was taken to be, deletes the prose between them.
    problems = []
    for doc, (_raw, text) in loaded.items():
        crlf = line_ending_problem(text, doc)
        problems += [crlf] if crlf else [f"{DOC_NAME[doc]}: {v}" for v in assert_region_positions(text, doc)]
    if problems:
        return refuse(paths.values(), problems)
    regions, failed, _rows = expected_regions()
    if failed:
        return refuse(paths.values(), [f"region {rid!r} cannot be computed: {why}" for rid, why in failed.items()])
    new = {doc: splice(text, regions, doc) for doc, (_raw, text) in loaded.items()}
    for doc, path in paths.items():  # the facts took a while; someone may have saved a document meanwhile
        if path.read_bytes() != loaded[doc][0]:
            return refuse(paths.values(), [f"{DOC_NAME[doc]} changed while the regions were being derived; "
                                           f"run it again"])
    for doc, path in paths.items():
        write_atomic(path, new[doc].encode("utf-8"))
    print(f"generate-hero-status: wrote the {len(REGION_IDS)} canonical regions into {readme} and {status}")
    return 0


def check_claim_rows(status_text: str, expected_rows: dict[str, list[tuple[str, str]]]) -> list[str]:
    """The claim rows of the status page: (a) every row id present exactly once across the claim
    regions, (b) every state in the closed enum, (c) state=passed iff the named predicate holds, in
    both directions, so a stale not-yet left behind after an artifact appears also fails, and (d) each
    row byte-compared, so every violation can name its row."""
    committed = [row for rid in CLAIM_REGIONS if (span := region_span(status_text, rid))
                 for row in parse_committed_rows(status_text[span[0]:span[1]])]
    expected = {m.group("id"): (marker, visible, m.groupdict())
                for pairs in expected_rows.values() for marker, visible in pairs
                if (m := MARKER_RE.match(marker))}
    return _row_census(committed) + _row_agreement(committed, expected)


def _row_census(committed: list[tuple[str, str, dict]]) -> list[str]:
    """(a) every row id exactly once across the claim regions and (b) every state in the closed enum."""
    seen: dict[str, int] = {}
    for _, _, f in committed:
        seen[f["id"]] = seen.get(f["id"], 0) + 1
    out = [f"[completeness] row {rid!r} is missing from the canonical regions" for rid in ROW_IDS if rid not in seen]
    out += [f"[completeness] row {rid!r} appears {n} times; expected exactly once" for rid, n in seen.items() if n > 1]
    out += [f"[completeness] row {rid!r} is not in the closed row enum" for rid in seen if rid not in ROW_IDS]
    return out + [f"[enum] row {f['id']!r} carries state={f['state']!r}, outside {sorted(STATES)}"
                  for _, _, f in committed if f["state"] not in STATES]


def _row_agreement(committed: list[tuple[str, str, dict]], expected: dict) -> list[str]:
    """(c) each row's state agrees with its predicate and (d) each row equals its regeneration, byte for byte."""
    out = [f"[predicate] row {f['id']!r} claims state={f['state']!r} but its named predicate evaluates to "
           f"{expected[f['id']][2]['state']!r}"
           for _, _, f in committed if f["id"] in expected and f["state"] != expected[f["id"]][2]["state"]]
    for rid in ROW_IDS:
        got = next((r for r in committed if r[2]["id"] == rid), None)
        if got is not None and got[0] != expected[rid][0]:
            out.append(f"[byte-compare] row {rid!r}: marker line differs from regenerated")
        if got is not None and got[1] != expected[rid][1]:
            out.append(f"[byte-compare] row {rid!r}: visible text differs from regenerated")
    return out


def check_document(doc: str, text: str, expected: dict[str, str], failed: dict[str, str]) -> list[str]:
    """Every assertion about one document but the claim rows: line endings; (e) the WHOLE-REGION
    byte-compare of its regions; no claim-row marker outside them; (f) their position; (g) no
    numeral typed by hand in its prose; and, for README.md, no internal name.

    The per-row compare only inspects recognized marker/visible pairs, so free-standing authored
    prose inserted INSIDE a canonical region -- an extra fabricated bullet, a second copy of a
    region -- was invisible to it and exited 0. Comparing the entire region against its
    regeneration leaves no unreviewed bytes inside the fence. A count region that cannot be
    regenerated fails here, with the reason."""
    out = [p for p in [line_ending_problem(text, doc)] if p]
    for rid in DOC_REGIONS[doc]:
        span = region_span(text, rid)
        if rid in failed:
            out.append(f"[region:{rid}] cannot be computed, so it cannot be verified: {failed[rid]}")
        elif span is not None and text[span[0]:span[1]] != expected[rid]:
            out.append(f"[region-byte-compare] region {rid!r} does not match the regenerated region exactly "
                       f"(content inside the canonical fence was added, removed or reordered)")
    inside = "".join(text[a:b] for a, b in filter(None, (region_span(text, r) for r in DOC_REGIONS[doc])))
    out += [f"[region-byte-compare] claim-row marker outside any canonical region: {ln.strip()[:80]}"
            for ln in text.splitlines() if MARKER_RE.match(ln.strip()) and ln not in inside]
    out += assert_region_positions(text, doc)
    out += assert_no_hand_typed_numbers(text, doc)
    if doc == "readme":
        out += assert_no_internal_names(text)
    return out


def cmd_check(readme: Path, status: Path, check_fold: bool = True) -> int:
    """Every assertion, evaluated on EVERY run, over both documents. Never short-circuits; every
    violation names its document and the offending region or row id."""
    paths = bind(readme, status)
    texts = {doc: read_doc(path)[1] for doc, path in paths.items()}
    expected, failed, expected_rows = expected_regions()
    violations = [f"{DOC_NAME[doc]}: {v}" for doc, text in texts.items()
                  for v in check_document(doc, text, expected, failed)]
    violations += [f"{DOC_NAME['status']}: {v}" for v in check_claim_rows(texts["status"], expected_rows)]

    # (h) the published glyph figure still equals what a browser measures. Without a browser it is
    # a model prediction, and the last line below must not say it was asserted.
    notes: list[str] = []
    measured = False
    if check_fold:
        fold_violations, notes, measured = assert_glyph_model(status)
        violations += [f"{DOC_NAME['status']}: {v}" for v in fold_violations]

    for n in notes:
        print(f"generate-hero-status: NOTE: {n}")
    for v in violations:
        print(f"generate-hero-status: FAIL: {v}", file=sys.stderr)
    if violations:
        return 2
    if measured:
        scope = "position, hand-typed numbers, internal names and glyph model asserted"
    else:
        why = "was NOT measured, so the hero figures are model predictions" if check_fold else \
            "was not measured (--no-fold), so the hero figures are model predictions"
        scope = f"position, hand-typed numbers and internal names asserted; the glyph model {why}"
    print(f"generate-hero-status: OK  {len(ROW_IDS)} rows and {len(REGION_IDS)} canonical regions "
          f"verified in {DOC_NAME['readme']} and {DOC_NAME['status']} ({scope})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--readme", default=str(REPO_ROOT / "README.md"), help="the README (default: README.md)")
    ap.add_argument("--status", default=str(REPO_ROOT / "docs" / "status.md"),
                    help="the status page (default: docs/status.md)")
    ap.add_argument("--no-fold", action="store_true",
                    help="skip the glyph-model measurement (it needs a headless browser)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    a = ap.parse_args()
    readme, status = Path(a.readme), Path(a.status)
    try:
        return cmd_write(readme, status) if a.write else cmd_check(readme, status, check_fold=not a.no_fold)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"generate-hero-status: cannot read or write {readme} or {status}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
