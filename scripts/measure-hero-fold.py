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
import re
import subprocess
import sys
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


def md_to_html(md: str) -> str:
    """First screen only: everything above the first horizontal rule."""
    first_screen = md.split("\n---\n", 1)[0]
    try:
        import markdown  # type: ignore
        body = markdown.markdown(first_screen, extensions=["fenced_code", "tables"])
    except Exception:
        body = _mini_markdown(first_screen)
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

    html = md_to_html(Path(a.readme).read_text(encoding="utf-8"))
    page_path = Path("/tmp/hero-fold-preview.html")
    page_path.write_text(html, encoding="utf-8")

    from playwright.sync_api import sync_playwright  # type: ignore

    # Logical geometry of the generated hero, needed for the glyph-height threshold.
    svg = (REPO_ROOT / ".github/assets/guard-hero.svg").read_text(encoding="utf-8")
    vb = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
    logical_w = int(vb.group(1)) if vb else 960
    FONT_PX = 15  # gen-svg.mjs body font-size

    results, failures = [], []
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
            for key in ("headline", "limits", "hero", "whynow", "statusLast", "quickstart"):
                box = m.get(key)
                above[key] = bool(box and box["top"] >= 0 and box["bottom"] <= m["viewportH"])
            missing = [k for k, ok in above.items() if not ok]
            if missing:
                failures.append(f"{w}x{h}/{scheme}: not above the fold: {', '.join(missing)}")
            if glyph_px < 11.0:
                failures.append(f"{w}x{h}/{scheme}: hero glyph height {glyph_px}px < 11px")
            results.append({"viewport": f"{w}x{h}", "scheme": scheme,
                            "glyph_px": glyph_px, "above_fold": above,
                            "content_bottom": m.get("quickstart", {}).get("bottom")
                            if m.get("quickstart") else None,
                            "viewport_h": m["viewportH"]})
            ctx.close()
        browser.close()

    print(json.dumps({"results": results, "failures": failures}, indent=2))
    for f in failures:
        print(f"measure-hero-fold: FAIL: {f}", file=sys.stderr)
    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
