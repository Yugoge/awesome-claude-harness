"""Regression fixture: a hero asset must not be able to blind the clipping detector.

tools/demo/audit.mjs measures a line's rendered right edge on a fixed monospace grid, using
a character advance DERIVED FROM THE ASSET UNDER TEST. That is fail-open on its own: an
asset which declares a too-small advance reports itself un-clipped. It was proven end to
end -- a 16-line asset cutting 9 lines, 4 of them kind "verdict", declared an advance of 1
instead of 9 and audited clean with exit 0 and zero clipping diagnostics.

The auditor now corroborates the declared advance against the root font-size, the stage-rail
pitch and (when present) the first typing-reveal clip step, and refuses a declaration that
disagrees with any of them. These tests hold that closed, and hold the checks around it
intact: the committed assets must still pass, and a genuinely clipped asset with an HONEST
advance must still fail. A cross-check that passed by suppressing the clipping check would
satisfy the first test and fail the last.
"""

from __future__ import annotations

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
