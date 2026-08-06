"""Regression fixture: a hero asset must not be able to blind the clipping detector.

tools/demo/audit.mjs measures a line's rendered right edge on a fixed monospace grid, using
a character advance DERIVED FROM THE ASSET UNDER TEST. That is fail-open on its own: an
asset which declares a too-small advance reports itself un-clipped. It was proven end to
end -- a 16-line asset cutting 9 lines, 4 of them kind "verdict", declared an advance of 1
instead of 9 and audited clean with exit 0 and zero clipping diagnostics.

The auditor now corroborates the declared advance against the font-size IN EFFECT ON THE
MEASURED LINE TEXT, the stage-rail pitch and (when present) the first typing-reveal clip
step, and refuses a declaration that disagrees with any of them. These tests hold that
closed, and hold the checks around it intact: the committed assets must still pass, and a
genuinely clipped asset with an HONEST advance must still fail. A cross-check that passed by
suppressing the clipping check would satisfy the first test and fail the last.

The font-size corroborator was itself proven fail-open once, and the two tests that follow
the original one are that regression. It read the ROOT <svg font-size> attribute, but
font-size INHERITS, so a declaration on the <text> element -- or on an enclosing <g>, or via
SMIL at runtime -- overrides it. An asset could therefore declare a root font-size of 1.667
to satisfy the corroborator while pinning its lines back to 15px, leaving the type fully
readable and 9 of 16 lines genuinely overflowing, and still audit clean. Browser-measured,
not argued: those forgeries render the byte-identical clipping set that the honest control
below is correctly refused for.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "tools/demo/audit.mjs"
MANIFEST = ROOT / ".github/assets/hook-trace.json"
ASSET = ROOT / ".github/assets/hook-hero.svg"

# hook-hero is the asset the proven attack used, and it is the hard case on purpose: it has
# no typed line, so the typing-clip corroborator cannot fire and the defence must come from
# a source every asset carries.
NARROW_VIEWBOX = 400
TRUE_ADVANCE = 9
FALSE_ADVANCE = 1

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not AUDIT.is_file(),
    reason="node or tools/demo/audit.mjs unavailable",
)


def audit(svg: Path) -> subprocess.CompletedProcess:
    """Run the auditor in --strict from the repository root (it resolves sources via git)."""
    return subprocess.run(
        ["node", str(AUDIT), str(MANIFEST), str(svg), "--strict"],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )


def narrowed(width: int = NARROW_VIEWBOX) -> str:
    """The committed asset, narrowed until real lines genuinely overflow it."""
    return re.sub(r'viewBox="0 0 (\d+(?:\.\d+)?) ',
                  f'viewBox="0 0 {width} ', ASSET.read_text(encoding="utf-8"), count=1)


def test_the_fixture_really_does_clip_verdict_lines() -> None:
    """Guard the fixture itself: a test that asserts on a non-clipping asset proves nothing."""
    svg = narrowed()
    kinds = {ln["id"]: ln["kind"] for ln in json.loads(MANIFEST.read_text())["lines"]}
    texts = {ln["id"]: ln["text"] for ln in json.loads(MANIFEST.read_text())["lines"]}
    over = [i for i, x in re.findall(r'<text data-trace-id="([^"]+)" x="([\d.]+)"', svg)
            if float(x) + len(texts[i]) * TRUE_ADVANCE > NARROW_VIEWBOX]
    assert len(over) >= 5, f"fixture must clip several lines, clips {len(over)}"
    assert any(kinds[i] == "verdict" for i in over), "fixture must clip a verdict line"


def test_false_small_advance_cannot_hide_real_clipping(tmp_path: Path) -> None:
    """The proven attack, held closed. This is the regression this file exists for."""
    honest = narrowed()
    blinded = honest.replace(f'values="0;{TRUE_ADVANCE}" keyTimes="0;0.5"',
                             f'values="0;{FALSE_ADVANCE}" keyTimes="0;0.5"', 1)
    assert blinded != honest, "grid-advance declaration not found; fixture is stale"
    svg = tmp_path / "blinded-hook-hero.svg"
    svg.write_text(blinded, encoding="utf-8")

    r = audit(svg)
    assert r.returncode != 0, (
        "an asset that declares a false character advance audited CLEAN — the detector is "
        f"blindable again.\n{r.stdout}\n{r.stderr}")
    assert "declared character advance" in (r.stdout + r.stderr), (
        "the asset was refused, but not for its false advance; the regression this test "
        f"guards may be masked by an unrelated failure.\n{r.stdout}\n{r.stderr}")


def _blinded() -> str:
    """The narrowed asset with every corroborator rescaled to agree with a FALSE advance of 1.

    Root font-size 1.667 brackets an advance of 1 (0.45*1.667 .. 0.80*1.667), and moving the
    second rail label to x=50 makes the rail pitch exactly 1. Both corroborators then agree,
    so the only thing left to catch the forgery is the size the text really renders at.
    """
    s = narrowed()
    s = s.replace(f'values="0;{TRUE_ADVANCE}" keyTimes="0;0.5"',
                  f'values="0;{FALSE_ADVANCE}" keyTimes="0;0.5"', 1)
    s = re.sub(r'(<svg\b[^>]*\bfont-size=")15(")', r"\g<1>1.667\g<2>", s, count=1)
    return s.replace('<text data-role="stage" x="130"', '<text data-role="stage" x="50"', 1)


@pytest.mark.parametrize("name,restored,expect", [
    # the type pinned back to full size on the measured element itself
    ("per-element attribute", ('<text data-trace-id="', '<text font-size="15" data-trace-id="'),
     "declared character advance"),
    # ... on the enclosing group, which the text inherits from
    ("enclosing group", ('<g data-role="line"', '<g font-size="15" data-role="line"'),
     "declared character advance"),
    # ... through an inline style, which beats the attribute
    ("inline style", ('<text data-trace-id="', '<text style="font-size:15px" data-trace-id="'),
     "declared character advance"),
    # ... or at runtime, where no static attribute states it at all
    ("SMIL animation", ('<g data-role="line" opacity="0" transform="translate(0 6)">',
                        '<g data-role="line" opacity="0" transform="translate(0 6)">'
                        '<set attributeName="font-size" to="15" begin="0s"/>'),
     'animates "font-size"'),
    # ... or in a unit, where reading the leading digits would resolve the WRONG size:
    # 9em of the inherited 1.667px is 15px on screen
    ("unit-bearing size", ('<text data-trace-id="', '<text font-size="9em" data-trace-id="'),
     "units this cross-check will not resolve"),
    # and the advance itself can be seized directly, leaving font-size honest and tiny
    ("textLength", ('<text data-trace-id="',
                    '<text textLength="600" lengthAdjust="spacingAndGlyphs" data-trace-id="'),
     "states its own width"),
    # a child element can carry the readable size while the parent stays tiny
    ("tspan child", ('xml:space="preserve">', 'xml:space="preserve"><tspan font-size="15">'),
     "rendered text != manifest text"),
])
def test_readable_type_cannot_hide_real_clipping(name: str, restored: tuple[str, str],
                                                 expect: str, tmp_path: Path) -> None:
    """Every route by which the rendered size can diverge from the root declaration.

    Each of these renders at 15px with 9 of 16 lines overflowing -- 4 of them kind "verdict"
    -- while every static corroborator agrees with an advance of 1. Before the effective-size
    walk they audited CLEAN: exit 0, "16 source-verified, 0 warned", zero clipping
    diagnostics. The forger was not forced to shrink anything.
    """
    old, new = restored
    blinded = _blinded()
    assert old in blinded, f"fixture is stale: {old!r} not found"
    svg = tmp_path / "blinded.svg"
    svg.write_text(blinded.replace(old, new), encoding="utf-8")

    r = audit(svg)
    assert r.returncode != 0, (
        f"an asset that keeps its type at a fully readable size via {name} audited CLEAN "
        f"while genuinely clipping verdict lines — the detector is blindable again.\n"
        f"{r.stdout}\n{r.stderr}")
    assert ("declared character advance" in (r.stdout + r.stderr)
            or "animates" in (r.stdout + r.stderr)), (
        f"the asset was refused, but not for the size its text actually renders at; the "
        f"regression this test guards may be masked by an unrelated failure.\n{r.stdout}\n{r.stderr}")


def test_honest_advance_still_reports_the_clipping(tmp_path: Path) -> None:
    """The width assertion must still do its own job.

    Without this, a cross-check that simply refused every asset would pass the test above.
    """
    svg = tmp_path / "honest-hook-hero.svg"
    svg.write_text(narrowed(), encoding="utf-8")

    r = audit(svg)
    assert r.returncode != 0
    assert "overflows the asset's logical width" in (r.stdout + r.stderr), (
        f"clipping was not itemised on an asset that genuinely clips.\n{r.stdout}\n{r.stderr}")


@pytest.mark.parametrize("manifest,asset", [
    (".github/assets/demo-trace.json", ".github/assets/pipeline-hero.svg"),
    (".github/assets/hook-trace.json", ".github/assets/hook-hero.svg"),
    (".github/assets/guard-hero.json", ".github/assets/guard-hero.svg"),
])
def test_committed_assets_corroborate_their_own_advance(manifest: str, asset: str) -> None:
    """The cross-check must not be so tight that honest assets trip it."""
    r = subprocess.run(
        ["node", str(AUDIT), str(ROOT / manifest), str(ROOT / asset), "--strict"],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )
    assert r.returncode == 0, f"{asset} no longer audits clean.\n{r.stdout}\n{r.stderr}"


def test_the_published_figures_ruler_is_corroborated_against_the_asset() -> None:
    """The same defect, in the script that publishes the README's glyph figure.

    scripts/measure-hero-fold.py scales that figure by FONT_PX, and FONT_PX cancels out of its
    browser/model drift assertion -- both sides multiply by it -- so that assertion can never
    catch a wrong value. Setting it to 45 once made the legibility gate exit 0 with an empty
    failures list while the page the reader sees was unchanged. It is now corroborated against
    the size the hero's own line text resolves to, by the same cascade walk and with the same
    fail-closed treatment of sizes a static read cannot see.
    """
    spec = importlib.util.spec_from_file_location("fold", ROOT / "scripts/measure-hero-fold.py")
    fold = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fold)
    svg = (ROOT / ".github/assets/guard-hero.svg").read_text(encoding="utf-8")

    assert fold.asset_line_font_px(svg) == fold.FONT_PX, (
        "the constant the published glyph figure is scaled by no longer matches the font-size "
        "the hero's own line text resolves to")

    pinned = svg.replace('<text data-trace-id="', '<text font-size="9" data-trace-id="')
    assert fold.asset_line_font_px(pinned) == 9.0, (
        "a per-element font-size is not being resolved — this is the root-attribute read that "
        "was proven fail-open in the auditor")

    animated = svg.replace('<g data-role="line">',
                           '<g data-role="line"><set attributeName="font-size" to="9" begin="0s"/>', 1)
    assert animated != svg, "fixture is stale: no plain line group found"
    assert fold.asset_line_font_px(animated) is None, (
        "a font-size the asset moves at runtime must not resolve to a static value")
