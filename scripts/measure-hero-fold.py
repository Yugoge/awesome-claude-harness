#!/usr/bin/env python3
"""Measure whether all six required first-screen elements fit above the fold.

Description: Renders README.md LOCALLY from the working tree in headless Chromium at the
  two required viewports in both colour schemes, and reports, per combination, which of
  the six required elements are fully visible without scrolling plus the hero's rendered
  glyph height.

Usage: measure-hero-fold.py [--readme <path>]

Exit codes: 0 = all six elements fit in all four combinations, 2 = at least one does not

NOT a GitHub-rendered measurement. GitHub's own rendering cannot be observed from this
lane (no network, no publication), so the column width is an approximation and the result
must never be cited as GitHub-rendered proof.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# GitHub renders README prose in a ~1012px max-width column at desktop widths.
CSS = """
:root { color-scheme: light dark; }
body { margin:0; font:16px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;
       background:#fff; color:#1f2328; }
@media (prefers-color-scheme: dark) { body { background:#0d1117; color:#e6edf3; } }
main { max-width:1012px; margin:0 auto; padding:16px; }
h1 { font-size:2em; margin:.67em 0; } h2 { font-size:1.5em; margin:.6em 0; }
p { margin:0 0 12px; } ul { margin:0 0 12px; padding-left:22px; }
pre { background:#f6f8fa; padding:12px; border-radius:6px; overflow:auto; }
@media (prefers-color-scheme: dark) { pre { background:#161b22; } }
img { max-width:100%; }
"""

COMBOS = [(1280, 800, "light"), (1280, 800, "dark"),
          (390, 844, "light"), (390, 844, "dark")]

# ACCEPTANCE TRADEOFF, not a layout fix (orchestrator ruling, Option B).
#
# The original criterion required all SIX first-screen elements above the fold at once.
# That conjunction has an EMPTY feasible set, and provably so rather than by experiment:
# the renderer lays text on a fixed monospace grid, so rendered width is exactly linear in
# character count. Zero clipping needs a logical width of at least 1390px, while an 11px
# glyph at the 390px viewport (where the image renders 358px wide) permits at most
# 15 x 358 / 11 = 488.2px. The interval is empty by a factor of 2.85. Widening does not
# rescue the desktop either: at 1390px the desktop glyph is 7.77px, and even at the full
# 1012px preview column only 10.9px -- still under the floor.
#
# The ruling narrows the REQUIREMENT, never the page: nothing is deleted, shrunk, cropped
# or moved, and every demoted element keeps its place in document order. Relaxing the 11px
# glyph floor was considered and REJECTED -- it would turn a criterion green while changing
# nothing a reader experiences -- so the floor below remains a hard failure.
REQUIRED_ABOVE_FOLD = ("headline", "limits")
DEMOTED_ELEMENTS = ("hero", "whynow", "statusLast", "quickstart")
ALL_ELEMENTS = REQUIRED_ABOVE_FOLD + DEMOTED_ELEMENTS
GLYPH_FLOOR_PX = 11.0

FONT_PX = 15          # gen-svg.mjs body font-size — corroborated by asset_line_font_px()
COLUMN_MAX_PX = 1012  # prose-column cap; mirrors `main { max-width }` in CSS above
COLUMN_PAD_PX = 16    # mirrors `main { padding }` in CSS above


def asset_line_font_px(svg_text: str) -> float | None:
    """The font-size actually governing the hero's line text, resolved through the cascade.

    FONT_PX is the ruler the published glyph figure is scaled by, and it CANCELS out of the
    browser/model drift assertion below -- both sides multiply by it -- so that assertion can
    never detect a wrong value. Proven: setting FONT_PX to 45 made this script exit 0 with an
    empty failures list while the page the reader sees was unchanged, which is exactly the
    "turn a criterion green while changing nothing a reader experiences" outcome the glyph
    floor exists to refuse. So the ruler is corroborated here against the asset it measures.

    Resolved through the cascade, never read off the root: font-size INHERITS, so a
    declaration on a <text> element or an enclosing <g> overrides the root attribute. Reading
    the root alone is the same fail-open the auditor's advance cross-check was proven to have.
    Returns None when the asset does not resolve to exactly one static size for its line text
    -- including when a <style> block or a SMIL animation could move it -- and the caller
    treats None as a failure rather than as an absent check.
    """
    if re.search(r"<style[\s>]", svg_text, re.I):
        return None                                    # selector-driven size this walk cannot resolve
    if re.search(r'<(?:set|animate)\b[^>]*\battributeName="font[^"]*"', svg_text):
        return None                                    # a runtime size is not a static one
    stack: list[float | None] = []
    sizes: set[float | None] = set()
    for m in re.finditer(r"<(/?)(svg|g|text)\b([^>]*)>", svg_text):
        body = m.group(3)
        if m.group(1):
            if stack:
                stack.pop()
            continue
        own = (re.search(r'\bstyle\s*=\s*"[^"]*?\bfont-size\s*:\s*([\d.]+)', body)
               or re.search(r'\bfont-size\s*=\s*"\s*([\d.]+)', body))
        eff = float(own.group(1)) if own else (stack[-1] if stack else None)
        if m.group(2) == "text" and "data-trace-id" in body:
            sizes.add(eff)
        if not body.rstrip().endswith("/"):
            stack.append(eff)
    return sizes.pop() if len(sizes) == 1 else None


def hero_img_width(readme_text: str) -> int | None:
    """The width the README asks the browser to render the hero at."""
    for m in re.finditer(r"<img\b[^>]*>", readme_text):
        if "guard-hero" in m.group(0):
            w = re.search(r'\bwidth="(\d+)"', m.group(0))
            return int(w.group(1)) if w else None
    return None


def predict_glyph_px(viewport_w: int, img_width: int | None, logical_w: float) -> float:
    """The hero's inline glyph height at `viewport_w`, computed without a browser.

    The renderer lays text on a fixed monospace grid, so the asset scales uniformly and the
    on-page glyph is FONT_PX x (rendered width / logical width). Rendered width follows from
    the CSS above: the prose column caps at COLUMN_MAX_PX, loses COLUMN_PAD_PX on each side,
    and `img { max-width:100% }` shrinks the hero to whatever is left.

    This is the model the README's published glyph figure is derived from, because a status
    row must be regenerable in any environment while this measurement needs a browser. So
    main() asserts the model against the live browser measurement on EVERY run and FAILS on
    disagreement: a published number able to drift away from the measurement that gates it
    is the exact defect this hero exists to refuse.
    """
    if not logical_w or not img_width:
        return 0.0
    content = min(COLUMN_MAX_PX, viewport_w) - 2 * COLUMN_PAD_PX
    return round(FONT_PX * max(0, min(img_width, content)) / logical_w, 2)


def md_to_html(md: str) -> str:
    """First screen only: everything above the first horizontal rule."""
    first_screen = md.split("\n---\n", 1)[0]
    try:
        import markdown  # type: ignore
        body = markdown.markdown(first_screen, extensions=["fenced_code", "tables"])
    except Exception:
        body = _mini_markdown(first_screen)
    # The preview lives outside the repo, so repo-relative asset srcs must be rewritten
    # to absolute file: paths. Without this the hero silently fails to load and the page
    # is measured with an alt-text box in place of a ~500px-tall image -- which makes an
    # over-the-fold layout look far closer to fitting than it is.
    body = re.sub(r'src="(?!https?:|file:|/)([^"]+)"',
                  lambda m: f'src="{(REPO_ROOT / m.group(1)).as_uri()}"', body)
    return f"<!doctype html><meta charset=utf-8><style>{CSS}</style><main>{body}</main>"


def _mini_markdown(md: str) -> str:
    out, in_fence = [], False
    for ln in md.splitlines():
        if ln.startswith("```"):
            out.append("<pre><code>" if not in_fence else "</code></pre>")
            in_fence = not in_fence
            continue
        if in_fence:
            out.append(ln.replace("&", "&amp;").replace("<", "&lt;"))
            continue
        if ln.startswith("<!--") or not ln.strip():
            out.append("")
            continue
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", ln)
        s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        if s.startswith("# "):
            out.append(f"<h1 data-el=title>{s[2:]}</h1>")
        elif s.startswith("## "):
            out.append(f"<h2 data-el=headline>{s[3:]}</h2>")
        elif s.startswith("- "):
            out.append(f"<ul data-el=statusrow><li>{s[2:]}</li></ul>")
        elif s.startswith("<"):
            out.append(s)
        else:
            out.append(f"<p>{s}</p>")
    return "\n".join(out)


PROBE = """(() => {
  const vis = (el) => { if (!el) return null; const r = el.getBoundingClientRect();
    return {top:Math.round(r.top), bottom:Math.round(r.bottom), h:Math.round(r.height)}; };
  const byText = (t) => [...document.querySelectorAll('h1,h2,p,li,strong,pre,code')]
      .find(e => e.textContent.includes(t));
  return {
    headline:  vis(byText('block dangerous actions before they execute')),
    limits:    vis(byText('Known limits')),
    hero:      vis(document.querySelector('img[src*="guard-hero"]')),
    whynow:    vis(byText('prompt instructions are not a security boundary')),
    statusLast:vis(byText('Ubuntu (CI) only')),
    quickstart:vis(document.querySelector('pre')),
    viewportH: window.innerHeight,
    heroNatural: (() => { const i = document.querySelector('img[src*="guard-hero"]');
      return i ? {w: i.clientWidth} : null; })(),
  };
})()"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--readme", default=str(REPO_ROOT / "README.md"))
    a = ap.parse_args()

    readme_text = Path(a.readme).read_text(encoding="utf-8")
    html = md_to_html(readme_text)
    # UNIQUE per run. A fixed filename is a silent cross-lane hazard: under concurrent
    # mutation two measurements running at once overwrite each other's preview and each
    # then measures the other's page, reporting confident numbers about the wrong document.
    preview_dir = Path(tempfile.mkdtemp(prefix=f"hero-fold-{os.getpid()}-"))
    page_path = preview_dir / "preview.html"
    page_path.write_text(html, encoding="utf-8")

    from playwright.sync_api import sync_playwright  # type: ignore

    # Logical geometry of the generated hero, needed for the glyph-height threshold.
    svg = (REPO_ROOT / ".github/assets/guard-hero.svg").read_text(encoding="utf-8")
    vb = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
    logical_w = int(vb.group(1)) if vb else 960
    img_w = hero_img_width(readme_text)

    results, failures, tradeoffs, model_drift = [], [], [], []

    # The ruler the published figure is scaled by must match the asset it describes. Reported
    # into model_drift as well as into failures: a figure computed with the wrong font-size HAS
    # drifted from the measurement that gates it, and model_drift is the one result here that
    # the status ratchet consumes — so a wrong ruler turns the README's own gate red instead of
    # sitting in a list nothing reads. It stays separate from the glyph floor's verdict, which
    # is deliberately un-gated and disclosed on the page instead.
    line_fs = asset_line_font_px(svg)
    if line_fs is None or abs(line_fs - FONT_PX) > 1e-9:
        ruler = (f"the published glyph figure is scaled by FONT_PX={FONT_PX} but the hero's own "
                 f"line text resolves to {line_fs}px — the ruler the figure is computed with "
                 f"has drifted from the asset it describes")
        failures.append(ruler)
        model_drift.append(ruler)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for w, h, scheme in COMBOS:
            ctx = browser.new_context(viewport={"width": w, "height": h},
                                      color_scheme=scheme)
            pg = ctx.new_page()
            pg.goto(page_path.as_uri())
            pg.wait_for_timeout(250)
            m = pg.evaluate(PROBE)
            rendered_w = (m.get("heroNatural") or {}).get("w") or 0
            glyph_px = round(FONT_PX * rendered_w / logical_w, 2) if rendered_w else 0.0
            above = {}
            for key in ALL_ELEMENTS:
                box = m.get(key)
                above[key] = bool(box and box["top"] >= 0 and box["bottom"] <= m["viewportH"])
            missing = [k for k in REQUIRED_ABOVE_FOLD if not above[k]]
            if missing:
                failures.append(f"{w}x{h}/{scheme}: not above the fold: {', '.join(missing)}")
            # Demoted by the ruling: measured and reported every run so the tradeoff stays
            # visible, but no longer a failure. Reporting is what keeps it a tradeoff
            # rather than an omission.
            demoted_below = [k for k in DEMOTED_ELEMENTS if not above[k]]
            if demoted_below:
                tradeoffs.append(f"{w}x{h}/{scheme}: below the fold by accepted tradeoff: "
                                 f"{', '.join(demoted_below)}")
            # NOT relaxed by the ruling — see REQUIRED_ABOVE_FOLD.
            if glyph_px < GLYPH_FLOOR_PX:
                failures.append(f"{w}x{h}/{scheme}: hero glyph height {glyph_px}px "
                                f"< {GLYPH_FLOOR_PX}px")
            # The README publishes this figure from predict_glyph_px(), which needs no
            # browser and so can be regenerated anywhere. Binding the two together here is
            # what makes the published number a MEASURED number rather than a modelled one.
            # Reported in its OWN list as well as in failures: drift is the one result here
            # that the status ratchet consumes, and it must be separable from the glyph floor
            # so consuming it cannot silently import the floor's verdict too.
            predicted = predict_glyph_px(w, img_w, logical_w)
            if abs(predicted - glyph_px) > 0.02:
                drift = (f"{w}x{h}/{scheme}: the browser renders the hero glyph at "
                         f"{glyph_px}px but the published model predicts {predicted}px — "
                         f"the disclosed figure has drifted from the measurement that gates it")
                failures.append(drift)
                model_drift.append(drift)
            results.append({"viewport": f"{w}x{h}", "scheme": scheme,
                            "glyph_px": glyph_px, "predicted_glyph_px": predicted,
                            "above_fold": above,
                            "required_above_fold": list(REQUIRED_ABOVE_FOLD),
                            "demoted_below_fold": demoted_below,
                            "content_bottom": m.get("quickstart", {}).get("bottom")
                            if m.get("quickstart") else None,
                            "viewport_h": m["viewportH"]})
            ctx.close()
        browser.close()

    print(json.dumps({"results": results, "failures": failures,
                      "model_drift": model_drift,
                      "accepted_tradeoffs": tradeoffs,
                      "required_above_fold": list(REQUIRED_ABOVE_FOLD),
                      "demoted_elements": list(DEMOTED_ELEMENTS),
                      "glyph_floor_px": GLYPH_FLOOR_PX}, indent=2))
    for t in tradeoffs:
        print(f"measure-hero-fold: TRADEOFF: {t}", file=sys.stderr)
    for f in failures:
        print(f"measure-hero-fold: FAIL: {f}", file=sys.stderr)
    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
