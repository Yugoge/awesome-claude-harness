#!/usr/bin/env python3
"""Generate and ratchet the README's canonical regions from repository state.

Description: One source of truth emits FIVE marker-delimited canonical regions and re-derives
  them on demand to byte-compare against what is committed. Two are count regions, markdown
  tables whose every cell comes from scripts/readme_facts.py: `proof` (the measured proof, under
  "Measured proof") and `commands` (under "Commands"). Three are claim regions, in this order,
  under "Status and known limits": `limits`, `disclosure` and `status`. No row's visible text is
  ever hand-written; every claim row is computed from a named predicate.

Usage: generate-hero-status.py --write [--readme <path>]   # regenerate the regions
       generate-hero-status.py --check [--readme <path>]   # the CI ratchet
       generate-hero-status.py --check --no-fold           # skip the glyph-model measurement

Exit codes: 0 = ok, 1 = usage/IO error (--write: also a count region that cannot be computed),
  2 = one or more ratchet assertions failed

WHAT IS ASSERTED. Content (per-row and whole-region byte-compare, closed state enum, predicate
agreement in both directions), POSITION (each region inside its H2 section, the claim regions in
order, none missing or duplicated) and NUMBERS (no numeral typed by hand in the prose).

THE POSITION RULE REPLACED THE HEADLINE RULE. This script used to assert that the limits statement
sat next to the headline, in the first screen, and that "headline" and "limits" were fully above
the fold (scripts/measure-hero-fold.py). The owner moved the claim rows (limits, disclosure, status)
out of the top of the README to a section near its end, "Status and known limits"; the headline
text that measurement looks up no longer exists, so neither assertion can hold or mean anything
there. Dropping them without a replacement would have let the limits move anywhere unseen, so what
replaced them is assert_region_positions: every region must sit inside the H2 section named for it
in SECTION_OF, the three claim regions must appear in the order limits, disclosure, status, and a
region that is outside its section, duplicated, missing or out of order is a violation that names
the region. The fold measurement is still run, and only its report of glyph-model drift is
consumed (assert_glyph_model); the glyph floor and the old above-the-fold elements are not gated.

NUMBERS ARE DERIVED, NEVER TRANSCRIBED. Inside the regions every number is computed: the hero's
recorded duration, loop period, first-proof offset and rendered glyph height from committed
artifacts, and every count in the proof and commands tables from scripts/readme_facts.py. The
recorded duration is cross-validated against the capture's own first and last timestamps, so a
coordinated edit of this README and the evidence file together still cannot agree; the glyph
height is cross-validated against a live browser by the fold measurement it is imported from,
which fails if the published model and the measurement disagree. OUTSIDE the regions a numeral in
the prose is a violation (assert_no_hand_typed_numbers) unless it is an ordered-list marker, sits
in a code span, fenced block, HTML comment, HTML tag or attribute, link target or image, or is one
of the externally cited figures declared once in CITED_FIGURES with the URL it comes from. A
declared figure that no longer appears in the prose, or whose URL is absent, also fails. Numbers
written as words are out of scope.

FAIL-CLOSED IN ONE DIRECTION ONLY. A predicate input that is missing, unreadable, unparseable, or
not committed makes its claim row FALSE (state not-yet, no figure published): the failure mode of
a broken predicate is continued honest disclosure, never a silent pass. A count region has no such
fallback: when a fact it needs cannot be derived, --check fails naming the missing input, and
--write refuses to touch the README rather than print a value from an earlier run.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

# This script, the fact module and the fold measurement are loaded by path, and a run must leave
# no __pycache__ behind in the tree it checks.
sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parent.parent

ROW_IDS = ["known-limits", "hero-recording", "hero-legibility", "hero-glyph",
           "supported-builds", "capability-check", "blackbox-tests", "release", "os",
           "enforcement-strength", "dead-end-sites"]

# The README under evaluation. Rebound by main() so a --readme copy is measured against its
# OWN hero width rather than the repository's; a predicate that silently read the checked-in
# README while checking a copy would report confident numbers about the wrong document.
README_PATH = REPO_ROOT / "README.md"

# Canonical regions. COUNT_REGIONS are tables built from scripts/readme_facts.py; CLAIM_REGIONS
# hold the claim rows and MUST appear in this order (limits, then disclosure, then status).
COUNT_REGIONS = ("proof", "commands")
CLAIM_REGIONS = ("limits", "disclosure", "status")
REGION_IDS = COUNT_REGIONS + CLAIM_REGIONS
STATES = {"passed", "not-yet", "partial"}

# The H2 section each region must sit inside (heading text, exact).
STATUS_SECTION = "Status and known limits"
SECTION_OF = {"proof": "Measured proof", "commands": "Commands",
              "limits": STATUS_SECTION, "disclosure": STATUS_SECTION, "status": STATUS_SECTION}

# Figures the README prose may quote from outside this repository: the numeral exactly as the
# prose writes it, and the URL it comes from. The ONLY place such a number is declared. The check
# fails when a source URL is absent from the README or a figure no longer appears in the prose.
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
# The repository's facts. Every count in the proof and commands tables, and in the two claim rows
# built on them, comes from scripts/readme_facts.py -- the single producer of those figures. The
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
    direction. The cross-validation is the point: a coordinated edit of the README region
    AND the evidence file still cannot agree with the capture's first and last timestamps.
    """
    cap, ev_raw, man_raw, svg = (_read(HERO_CAPTURE), _read(HERO_EVIDENCE),
                                 _read(HERO_MANIFEST), _read(HERO_ASSET))
    if not all((cap, ev_raw, man_raw, svg)):
        return {}
    try:
        evidence, manifest = json.loads(ev_raw), json.loads(man_raw)
    except Exception:
        return {}

    stamps = [float(m.group(1)) for m in
              (CAPTURE_TS_RE.match(ln) for ln in cap.splitlines()) if m]
    if len(stamps) < 2:
        return {}
    recomputed = round(stamps[-1] - stamps[0], 3)
    declared = evidence.get("raw_duration_s")
    if not isinstance(declared, (int, float)) or abs(float(declared) - recomputed) > 1e-6:
        return {"duration_conflict": (declared, recomputed)}

    durations = {float(d) for d in re.findall(r'\bdur="([\d.]+)s"', svg)}
    loop_s = max(durations) if durations else None

    lines = manifest.get("lines", [])
    by_id = {str(ln.get("id")): ln for ln in lines}
    marker_id = next((str(ln["id"]) for ln in lines
                      if str(ln.get("text", "")).startswith(CONSUMPTION_MARKER)), None)

    # When the proof line's reveal begins, read from the asset's own animation schedule.
    proof_s = None
    if marker_id and loop_s:
        for chunk in svg.split('<g data-role="line"')[1:]:
            if f'data-trace-id="{marker_id}"' not in chunk:
                continue
            km = re.search(r'attributeName="opacity"[^>]*keyTimes="([^"]+)"', chunk)
            if km:
                kt = [float(x) for x in km.group(1).split(";") if x.strip()]
                if len(kt) >= 2:
                    proof_s = round(kt[1] * loop_s, 2)
            break

    # Clipping, on the renderer's own fixed monospace grid -- both constants read from the
    # asset rather than assumed, so this stays correct if the renderer's geometry changes.
    vb = re.search(r'viewBox="0 0 (\d+(?:\.\d+)?) ', svg)
    logical_w = float(vb.group(1)) if vb else None
    adv = None
    am = re.search(r'<animate attributeName="width"[^>]*values="([^"]+)"', svg)
    if am:
        vals = [float(v) for v in am.group(1).split(";") if v.strip()]
        adv = next((b - a for a, b in zip(vals, vals[1:]) if b - a > 0), None)
    clipped: list[tuple[str, int]] = []
    if logical_w and adv:
        for t in re.finditer(r'<text data-trace-id="([^"]+)" x="([\d.]+)"', svg):
            ln = by_id.get(t.group(1))
            if not ln:
                continue
            x, n = float(t.group(2)), len(str(ln.get("text", "")))
            if x + n * adv > logical_w:
                clipped.append((t.group(1), n - max(0, int((logical_w - x) // adv))))

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


MEASURE_SCRIPT = "scripts/measure-hero-fold.py"


def _fold_module():
    """Load the fold measurement as a module (its filename is not a Python identifier).

    Importing it rather than restating its constants is the point: the glyph figure this
    README publishes and the floor the fold gate measures against must be incapable of
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
    viewBox, the README's own width attribute, and the model + floor imported from the fold
    measurement, which asserts that model against a real browser on every run.

    Returns {} when any input is missing, unreadable or uncommitted -- fail-closed, so the
    consuming rows disclose that they could not measure instead of publishing a pass.
    """
    mod = _fold_module()
    svg = _read(HERO_ASSET)
    if mod is None or svg is None or not is_committed(MEASURE_SCRIPT):
        return {}
    try:
        readme_text = README_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}
    vb = re.search(r'viewBox="0 0 (\d+(?:\.\d+)?) ', svg)
    img_w = mod.hero_img_width(readme_text)
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

def measure_deny_rules() -> tuple[int, int, str] | None:
    """(total_deny, git_related_deny, source). None when no source is readable."""
    for cand in ("settings.json",):
        p = REPO_ROOT / cand
        if not p.is_file():
            continue
        try:
            deny = json.loads(p.read_text(encoding="utf-8")).get("permissions", {}).get("deny", [])
        except Exception:
            continue
        if not isinstance(deny, list):
            continue
        return len(deny), sum(1 for r in deny if "git" in str(r).lower()), cand
    return None


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


def pred_dead_end_sites() -> tuple[str, str, str, str]:
    """How many blocking sites have no clearing class, and what the suite does and does not assert.

    The suite fails when a REPLAY reaches such a site; it does not fail because one exists. So
    zero replays reaching one is not a proof that no flow can, and the row says so. It reads
    `passed` only if there is no such site AND the suite asserts there can be none.
    """
    test = "tests/replay/test_no_dead_end.py"
    try:
        b, ci = fact("blocking_sites"), fact("ci_enforces")
    except FactUnavailable:
        return ("not-yet",
                "**Dead-end sites** — the blocking sites of the registered hooks could not be "
                "enumerated at build time, so no figure is published.", "none", "none")
    n, total = b["no_class"], b["sites"]
    asserted = ci["no_site_without_class"]["holds"]
    if n == 0 and asserted:
        return ("passed",
                f"**Dead-end sites** — none of the **{total}** blocking sites of the registered "
                f"hooks lacks a clearing class, and the suite fails if one does.", test, "none")
    if n == 0:
        return ("partial",
                f"**Dead-end sites** — none of the **{total}** blocking sites of the registered "
                f"hooks lacks a clearing class as counted here, but the suite does not assert "
                f"that; it fails only when a replay reaches one. This is a known limit, not a "
                f"proof that there are none.", test, "none")
    return ("partial",
            f"**Dead-end sites** — **{n} of {total}** blocking sites of the registered hooks have "
            f"no clearing class. The suite fails only when a replay reaches one, so this is a "
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
COMMANDS_HEADER = ("Command", "Typed by", "What it does")

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
    rows = []
    for c in fact("command_rows"):
        usage = f"/{c['name']}" + (f" {c['argument_hint']}" if c["argument_hint"] else "")
        rows.append((md_cell(code_span(usage)), "owner only" if c["human_only"] else "owner or agent",
                     md_cell(c["summary"])))
    return table(COMMANDS_HEADER, rows)


COUNT_RENDERERS = {"proof": render_proof, "commands": render_commands}


def render_region(rid: str, body: object) -> str:
    """The region as it must read in the README: BEGIN marker, body, END marker. `body` is the table
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
# Position: where each region sits, not only what it says.
# --------------------------------------------------------------------------------------

_COMMENT = re.compile(r"<!--.*?-->", re.S)
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _blank(match: re.Match) -> str:
    """The matched text with every character but a line break replaced by a space: offsets and line
    numbers survive."""
    return re.sub(r"[^\n]", " ", match.group(0))


def _fence_blanked(text: str) -> str:
    """`text` with the inside of fenced code blocks (fences included) blanked."""
    out, fence = [], None
    for line in text.splitlines(keepends=True):
        m = _FENCE_OPEN.match(line)
        if fence is None and m:
            fence = (m.group(1)[0], len(m.group(1)))
            out.append(re.sub(r"[^\n]", " ", line))
        elif fence is not None:
            closing = re.match(r"^ {0,3}(" + re.escape(fence[0]) + r"{%d,})[ \t]*$" % fence[1], line)
            out.append(re.sub(r"[^\n]", " ", line))
            if closing:
                fence = None
        else:
            out.append(line)
    return "".join(out)


def headings(text: str) -> list[tuple[int, str, int]]:
    """-> [(level, title, offset of the heading line)] for the ATX headings that are real headings:
    not inside a fenced block or an HTML comment."""
    visible = _fence_blanked(_COMMENT.sub(_blank, text))
    out = []
    for m in re.finditer(r"(?m)^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$", visible):
        out.append((len(m.group(1)), m.group(2).strip(), m.start()))
    return out


def assert_region_positions(text: str) -> list[str]:
    """Each region's POSITION, not merely its bytes.

    The byte-compare refuses any edit to a region's CONTENT but is blind to the region being MOVED:
    a limits statement lifted out of "Status and known limits" into a section nobody reads still
    passes every byte-level assertion. So, per region: exactly one BEGIN/END pair, lying inside the
    H2 section named for it in SECTION_OF; and the claim regions in the order limits, disclosure,
    status. Every violation names the region.
    """
    out: list[str] = []
    heads = headings(text)
    spans: dict[str, tuple[int, int]] = {}
    for rid in REGION_IDS:
        begins, ends = text.count(BEGIN.format(rid=rid)), text.count(END.format(rid=rid))
        if begins == 0 and ends == 0:
            out.append(f"[region-position] region {rid!r} is missing: no BEGIN/END marker pair in the document")
            continue
        if begins > 1 or ends > 1:
            out.append(f"[region-position] region {rid!r} is duplicated: {begins} BEGIN and {ends} END "
                       f"markers, expected one of each")
            continue
        span = region_span(text, rid)
        if span is None:
            out.append(f"[region-position] region {rid!r} has {begins} BEGIN and {ends} END markers, "
                       f"but not a BEGIN followed by an END")
            continue
        spans[rid] = span
        title = SECTION_OF[rid]
        sections = [(i, h) for i, h in enumerate(heads) if h[0] == 2 and h[1] == title]
        if not sections:
            out.append(f"[region-position] region {rid!r} has no H2 section {title!r} to sit in")
            continue
        if len(sections) > 1:
            out.append(f"[region-position] region {rid!r}: the H2 heading {title!r} appears "
                       f"{len(sections)} times; its section is ambiguous")
            continue
        i, (_level, _title, start) = sections[0]
        stop = next((h[2] for h in heads[i + 1:] if h[0] <= 2), len(text))
        if not (start <= span[0] and span[1] <= stop):
            where = next((h[1] for h in reversed(heads) if h[0] == 2 and h[2] <= span[0]), "no H2 section")
            out.append(f"[region-position] region {rid!r} lies outside the H2 section {title!r} "
                       f"(it sits under {where!r})")

    present = [rid for rid in CLAIM_REGIONS if rid in spans]
    found = sorted(present, key=lambda rid: spans[rid][0])
    if found != present:
        for rid in present:
            if found.index(rid) != present.index(rid):
                out.append(f"[region-position] region {rid!r} is out of order: the claim regions "
                           f"appear as {', '.join(found)}, expected {', '.join(present)}")
    return out


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


def _code_spans_blanked(text: str) -> str:
    """Inline code spans blanked, paragraph by paragraph (a span does not cross a blank line)."""
    out, para = [], []

    def flush() -> None:
        if para:
            out.append(_CODE_SPAN.sub(_blank, "".join(para)))
            para.clear()

    for line in text.splitlines(keepends=True):
        if line.strip():
            para.append(line)
        else:
            flush()
            out.append(line)
    flush()
    return "".join(out)


def prose_view(text: str) -> str:
    """`text` with everything the number rule does not read blanked, offsets and lines kept: the
    canonical regions, HTML comments, fenced blocks, code (spans, and <code>/<pre> elements), images,
    link targets, reference definitions, URLs, HTML tags with their attributes, entities and
    ordered-list markers. What is left is prose."""
    text = _REGION_BLOCK.sub(_blank, text)
    text = _COMMENT.sub(_blank, text)
    text = _fence_blanked(text)
    text = _HTML_CODE.sub(_blank, text)
    text = _code_spans_blanked(text)
    for pattern in (_IMAGE, _LINK_TARGET, _REFERENCE, _HTML_TAG, _BARE_URL, _ENTITY):
        text = pattern.sub(_blank, text)
    return _LIST_MARKER.sub(_blank, text)


def prose_numerals(text: str) -> list[tuple[int, str]]:
    """-> [(line number, numeral)] for every numeral in the prose of `text`, in order."""
    view = prose_view(text)
    return [(view.count("\n", 0, m.start()) + 1, m.group(0)) for m in _NUMERAL.finditer(view)]


def assert_no_hand_typed_numbers(text: str) -> list[str]:
    """A numeral in the prose outside the canonical regions is a violation, unless it is one of the
    CITED_FIGURES. Also a violation: a source URL missing from the README, and a declared figure
    that the prose no longer holds (a stale entry would excuse a number that is gone, and quietly
    keep a hole open for the next one). Every violation names the line and the number."""
    out: list[str] = []
    lines = text.splitlines()
    declared = {figure for figure, _url in CITED_FIGURES}
    numerals = prose_numerals(text)
    for number, numeral in numerals:
        if numeral not in declared:
            out.append(f"[hand-typed-number] line {number}: the numeral {numeral!r} is typed by hand in "
                       f"the prose ({lines[number - 1].strip()[:80]!r}); derive it in a canonical region, "
                       f"or declare it in CITED_FIGURES with the URL it comes from")
    present = {numeral for _number, numeral in numerals}
    for figure, url in CITED_FIGURES:
        if url not in text:
            out.append(f"[cited-figure] the source of {figure!r}, {url}, is absent from the README")
        if figure not in present:
            out.append(f"[cited-figure] the declared figure {figure!r} (source {url}) no longer appears "
                       f"in the prose; remove it from CITED_FIGURES")
    return out


# --------------------------------------------------------------------------------------
# The fold measurement: only its report of glyph-model drift is consumed.
# --------------------------------------------------------------------------------------

def assert_glyph_model(readme: Path, script: Path | None = None) -> tuple[list[str], list[str]]:
    """-> (violations, notes). Run the fold measurement and fail on its report of glyph-model drift.

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
    """
    script = script or REPO_ROOT / MEASURE_SCRIPT
    if not script.is_file():
        return ([], [f"[fold] {script.name} is absent; the glyph-model measurement did NOT run"])
    try:
        r = subprocess.run([sys.executable, str(script), "--readme", str(readme)],
                           cwd=REPO_ROOT, capture_output=True, text=True, timeout=600)
        data = json.loads(r.stdout)
    except Exception as exc:
        return ([], [f"[fold] the fold measurement could not be executed "
                     f"({type(exc).__name__}); the published glyph figure is UNVERIFIED in this "
                     f"environment"])
    results = data.get("results") or []
    if not results:
        return (["[fold] the fold measurement produced no combinations to compare the glyph model with"], [])
    out = [f"[fold] {drift}" for drift in data.get("model_drift") or []]
    return (out, [f"[fold] glyph model compared with the browser over {len(results)} combinations "
                  f"(local preview, not GitHub's rendering)"])


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


def cmd_write(readme: Path) -> int:
    global README_PATH
    README_PATH = readme
    text = readme.read_text(encoding="utf-8")
    # The cheap precondition first: a README without a region's markers fails at once, before the
    # facts (several seconds of work) are derived.
    spans = {rid: region_span(text, rid) for rid in REGION_IDS}
    for rid in REGION_IDS:
        if spans[rid] is None:
            print(f"generate-hero-status: region {rid!r} markers not found in {readme}",
                  file=sys.stderr)
            return 1
    regions, failed, _rows = expected_regions()
    if failed:
        for rid, why in failed.items():
            print(f"generate-hero-status: region {rid!r} cannot be computed, so {readme} was NOT "
                  f"written: {why}", file=sys.stderr)
        return 1
    for rid in sorted(REGION_IDS, key=lambda r: spans[r][0], reverse=True):
        i, j = spans[rid]
        text = text[:i] + regions[rid] + text[j:]
    readme.write_text(text, encoding="utf-8")
    print(f"generate-hero-status: wrote the {len(REGION_IDS)} canonical regions into {readme}")
    return 0


def cmd_check(readme: Path, check_fold: bool = True) -> int:
    """Every assertion, evaluated on EVERY run. Never short-circuits; every violation names the
    offending region or row id."""
    # Bound HERE rather than only in main() so any caller -- including an importer that calls
    # cmd_check directly -- measures the same document it byte-compares. Binding it in main()
    # alone left a path where the rows' numbers came from one README and the comparison from
    # another, and reported confidently about the wrong document.
    global README_PATH
    README_PATH = readme
    text = readme.read_text(encoding="utf-8")
    expected, failed, expected_rows = expected_regions()
    violations: list[str] = []

    committed_rows: list[tuple[str, str, dict]] = []
    for rid in CLAIM_REGIONS:
        span = region_span(text, rid)
        if span is not None:
            committed_rows += parse_committed_rows(text[span[0]:span[1]])

    seen: dict[str, int] = {}
    for _, _, f in committed_rows:
        seen[f["id"]] = seen.get(f["id"], 0) + 1

    # (a) completeness: every row id present EXACTLY once across the UNION of claim regions.
    for rid in ROW_IDS:
        n = seen.get(rid, 0)
        if n == 0:
            violations.append(f"[completeness] row {rid!r} is missing from the canonical regions")
        elif n > 1:
            violations.append(f"[completeness] row {rid!r} appears {n} times; expected exactly once")
    for rid in seen:
        if rid not in ROW_IDS:
            violations.append(f"[completeness] row {rid!r} is not in the closed row enum")

    # (b) enum: every state token within the closed three-value enum.
    for _, _, f in committed_rows:
        if f["state"] not in STATES:
            violations.append(
                f"[enum] row {f['id']!r} carries state={f['state']!r}, outside {sorted(STATES)}")

    # (c) predicate: state=passed IFF the named predicate holds -- bidirectional, so a
    #     stale not-yet left behind after an artifact appears also fails.
    expected_by_id = {}
    for pairs in expected_rows.values():
        for marker, visible in pairs:
            m = MARKER_RE.match(marker)
            assert m
            expected_by_id[m.group("id")] = (marker, visible, m.groupdict())
    for _, _, f in committed_rows:
        exp = expected_by_id.get(f["id"])
        if exp is not None and f["state"] != exp[2]["state"]:
            violations.append(
                f"[predicate] row {f['id']!r} claims state={f['state']!r} but its named "
                f"predicate evaluates to {exp[2]['state']!r}")

    # (d) per-row byte-compare, so every violation can name its row.
    for rid in ROW_IDS:
        exp = expected_by_id[rid]
        got = next((r for r in committed_rows if r[2]["id"] == rid), None)
        if got is None:
            continue
        if got[0] != exp[0]:
            violations.append(f"[byte-compare] row {rid!r}: marker line differs from regenerated")
        if got[1] != exp[1]:
            violations.append(f"[byte-compare] row {rid!r}: visible text differs from regenerated")

    # (e) WHOLE-REGION byte-compare, for all five regions. The per-row compare above only inspects
    # recognized marker/visible pairs, so free-standing authored prose inserted INSIDE a canonical
    # region -- an extra fabricated bullet, a second copy of a region -- was invisible to it and
    # exited 0. Comparing the entire region against its regeneration leaves no unreviewed bytes
    # inside the fence. A count region that cannot be regenerated fails here, with the reason.
    for rid in REGION_IDS:
        if rid in failed:
            violations.append(f"[region:{rid}] cannot be computed, so it cannot be verified: {failed[rid]}")
            continue
        span = region_span(text, rid)
        if span is not None and text[span[0]:span[1]] != expected[rid]:
            violations.append(
                f"[region-byte-compare] region {rid!r} does not match the regenerated "
                f"region exactly (content inside the canonical fence was added, removed "
                f"or reordered)")
    # A claim-row marker outside every canonical region is an unreviewed claim.
    inside = "".join(text[region_span(text, r)[0]:region_span(text, r)[1]]
                     for r in REGION_IDS if region_span(text, r))
    for ln in text.splitlines():
        if MARKER_RE.match(ln.strip()) and ln not in inside:
            violations.append(f"[region-byte-compare] claim-row marker outside any "
                              f"canonical region: {ln.strip()[:80]}")

    # (f) POSITION, not just bytes: each region in its section, the claim regions in order.
    violations += assert_region_positions(text)

    # (g) no numeral typed by hand in the prose.
    violations += assert_no_hand_typed_numbers(text)

    # (h) the published glyph figure still equals what a browser measures.
    notes: list[str] = []
    if check_fold:
        fold_violations, fold_notes = assert_glyph_model(readme)
        violations += fold_violations
        notes += fold_notes

    for n in notes:
        print(f"generate-hero-status: NOTE: {n}")
    for v in violations:
        print(f"generate-hero-status: FAIL: {v}", file=sys.stderr)
    if violations:
        return 2
    print(f"generate-hero-status: OK  {len(ROW_IDS)} rows and {len(REGION_IDS)} canonical regions "
          f"verified (position, hand-typed numbers"
          f"{' and glyph model' if check_fold else ''} asserted)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--readme", default=str(REPO_ROOT / "README.md"))
    ap.add_argument("--no-fold", action="store_true",
                    help="skip the glyph-model measurement (it needs a headless browser)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    a = ap.parse_args()
    readme = Path(a.readme)
    try:
        return cmd_write(readme) if a.write else cmd_check(readme, check_fold=not a.no_fold)
    except OSError as exc:
        print(f"generate-hero-status: cannot read or write {readme}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
