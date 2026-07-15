#!/usr/bin/env node
// gen-svg.mjs — deterministic paper-substrate animated-SVG generator for the README hero.
//
// Reads a trace manifest JSON (see manifest.schema.md) and writes a self-contained,
// animated SVG. PURE + DETERMINISTIC: no wall-clock, no randomness, no network, no
// external assets. Identical input => byte-identical output.
//
// Usage:  node gen-svg.mjs <manifest.json> [out.svg]
// Exit:   0 ok, 1 error.

import { readFileSync, writeFileSync } from 'node:fs';

const KINDS = new Set(['input', 'attempt', 'artifact', 'verdict', 'condensation', 'adaptation']);

// Per-kind render config: single source of truth for prefix glyph, fill keys (into C),
// reveal mode, and indent (in marker-columns). No scattered per-kind conditionals.
// `input`/`artifact`/`verdict`/`condensation` reproduce the original renderer byte-for-byte.
const KIND_CFG = {
  input:        { glyph: '›', marker: 'ink',       content: 'ink',       typing: true,  indent: 0 },
  attempt:      { glyph: '›', marker: 'ink',       content: 'ink',       typing: true,  indent: 0 },
  artifact:     { glyph: '✓', marker: 'muted',     content: 'ink',       typing: false, indent: 0 },
  verdict:      { glyph: '✓', marker: 'inkStrong', content: 'inkStrong', typing: false, indent: 0 },
  condensation: { glyph: '·', marker: 'muted',     content: 'muted',     typing: false, indent: 0 },
  adaptation:   { glyph: '→', marker: 'muted',     content: 'muted',     typing: false, indent: 1 },
};
// A `verdict` line with `block:true` renders a hook-BLOCK: a prohibition glyph in the warm
// accent (never red/green). `⊘` (U+2298) is a monochrome text symbol that honors `fill` —
// unlike a color-emoji such as ⛔, which browsers paint red/white regardless of fill. Accent
// is otherwise reserved for the active rail marker and the final line; the block is the one
// sanctioned extra use.
const BLOCK_CFG = { glyph: '⊘', marker: 'accent', content: 'inkStrong', typing: false, indent: 0 };
const cfgFor = (ln) => (ln.kind === 'verdict' && ln.block === true ? BLOCK_CFG : KIND_CFG[ln.kind]);

// ---------- layout (fixed monospace grid; we place by column*advance, never measure) ----------
const W = 960;          // logical width (px)
const PAD_X = 40;
const FS = 15;          // body font-size
const ADV = 9;          // monospace advance (~0.6 * FS)
const LH = 24;          // line-height (~1.6 * FS)
const MARKER_COLS = 2;  // prefix glyph occupies 2 columns
const CONTENT_X = PAD_X + MARKER_COLS * ADV;
const CHROME_H = 48;    // window-chrome band height (separator sits here)
const RAIL_BASE = 74;   // baseline of the stage-rail labels
const RAIL_UNDER_Y = 82; // top of the moving underline marker
const BODY_TOP = 104;
const BL0 = BODY_TOP + 16; // baseline of the first transcript line

// ---------- timing (seconds) — tuned so a ~15-line manifest lands near ~28s ----------
const T_FIRST = 1.0;    // first line begins after chrome/rail settle
const PER_CHAR = 0.05;  // typing cadence
const INPUT_TAIL = 0.8; // pause after a typed line
const MACHINE_STEP = 1.6; // cadence between machine lines
const MACHINE_FADE = 0.5; // fade+rise duration
const TAIL_HOLD = 1.2;  // trailing hold before the frozen end

// ---------- palette (warm paper; restraint = premium) ----------
const C = {
  bg: '#F7F4EC', ink: '#33302A', inkStrong: '#211F1B', muted: '#A9A295',
  accent: '#B07C2C', dot: '#D8D2C4', sep: '#ECE7DB', title: '#A9A295', footer: '#B8B0A0'
};

const nfc = (s) => String(s).normalize('NFC');
const esc = (s) => nfc(s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const num = (x) => { const r = Math.round(Number(x) * 1000) / 1000; return Object.is(r, -0) ? '0' : String(r); };
const kt = (x) => (x <= 0 ? '0' : x >= 1 ? '1' : String(Math.round(x * 10000) / 10000));

function fail(msg) { process.stderr.write('gen-svg: ' + msg + '\n'); process.exit(1); }

// ---------- read manifest ----------
const manifestPath = process.argv[2];
if (!manifestPath) fail('missing manifest path. Usage: node gen-svg.mjs <manifest.json> [out.svg]');
const outPath = process.argv[3] || manifestPath.replace(/\.json$/, '.svg');

let manifest;
try { manifest = JSON.parse(readFileSync(manifestPath, 'utf8')); }
catch (e) { fail('cannot read/parse manifest: ' + e.message); }

const meta = manifest.meta || {};
const title = nfc(meta.session_title || 'claude');
const footer = nfc(meta.footer || '');
if (!Array.isArray(manifest.lines) || manifest.lines.length === 0) fail('manifest.lines must be a non-empty array');

// stable sort by ordinal (ties keep authored order)
const lines = manifest.lines
  .map((l, i) => ({ l, i }))
  .sort((a, b) => (a.l.ordinal - b.l.ordinal) || (a.i - b.i))
  .map((x) => x.l);

for (const ln of lines) {
  if (!KINDS.has(ln.kind)) fail(`line ${ln.id}: invalid kind "${ln.kind}"`);
  if (typeof ln.text !== 'string' || ln.text.length === 0) fail(`line ${ln.id}: text must be a non-empty string`);
}

// ---------- data-driven rail ----------
// Rail labels come from the manifest, never hard-coded: an explicit `meta.rail` list wins;
// otherwise the distinct `stage` values in first-appearance (render) order. ONE generator
// thus renders the 5-stage pipeline demo and a 3-stage hook demo from data alone.
let RAIL;
if (Array.isArray(meta.rail) && meta.rail.length) {
  RAIL = meta.rail.map((s) => nfc(s));
} else {
  RAIL = [];
  const seen = new Set();
  for (const ln of lines) { if (!seen.has(ln.stage)) { seen.add(ln.stage); RAIL.push(ln.stage); } }
}
const RANK = Object.fromEntries(RAIL.map((s, i) => [s, i]));
for (const ln of lines) {
  if (!(ln.stage in RANK)) fail(`line ${ln.id}: stage "${ln.stage}" not in rail [${RAIL.join(', ')}]`);
}
const finalId = lines[lines.length - 1].id; // highest ordinal => the publish/commit-SHA line

// ---------- timeline (deterministic, content-driven) ----------
const stageStart = {};
const beats = [];
let t = T_FIRST;
for (const ln of lines) {
  if (!(ln.stage in stageStart)) stageStart[ln.stage] = t;
  const begin = t;
  const cfg = cfgFor(ln);
  if (cfg.typing) {
    const n = [...nfc(ln.text)].length;         // code-point count
    const dur = Math.max(0.4, n * PER_CHAR);
    beats.push({ ln, cfg, begin, dur, n, typing: true });
    t = begin + dur + INPUT_TAIL;
  } else {
    beats.push({ ln, cfg, begin, dur: MACHINE_FADE, typing: false });
    t = begin + MACHINE_STEP;
  }
}
const TOTAL = t + TAIL_HOLD;

// ---------- geometry ----------
const nLines = lines.length;
const BL = (i) => BL0 + i * LH;
const footerBL = BL(nLines - 1) + 40;
const H = footerBL + 20;

const rail = [];
{ let rx = PAD_X; for (const s of RAIL) { const w = s.length * ADV; rail.push({ s, x: rx, w }); rx += w + 3 * ADV; } }
const railBy = Object.fromEntries(rail.map((r) => [r.s, r]));
const presentStages = RAIL.filter((s) => s in stageStart);

// ---------- per-line styling (fills resolve through the kind config; the final line and
// the hook-block are the only accent users besides the rail marker) ----------
const markerFill = (ln, cfg) => C[ln.id === finalId ? 'accent' : cfg.marker];
const contentFill = (ln, cfg) => C[ln.id === finalId ? 'accent' : cfg.content];

// ---------- build ----------
const defs = [];
const body = [];

// background + window chrome
body.push(`<rect x="0" y="0" width="${W}" height="${H}" fill="${C.bg}"/>`);
body.push(`<circle cx="24" cy="24" r="5" fill="${C.dot}"/>`);
body.push(`<circle cx="42" cy="24" r="5" fill="${C.dot}"/>`);
body.push(`<circle cx="60" cy="24" r="5" fill="${C.dot}"/>`);
body.push(`<text data-role="chrome-title" x="${W / 2}" y="28" text-anchor="middle" fill="${C.title}" font-size="13">${esc(title)}</text>`);
body.push(`<line x1="0" y1="${CHROME_H}" x2="${W}" y2="${CHROME_H}" stroke="${C.sep}" stroke-width="1"/>`);

// stage-rail underline marker (accent) — advances discretely along the rail
{
  const base = presentStages[0];
  let anim = '';
  if (presentStages.length > 1) {
    const xs = presentStages.map((s) => railBy[s].x).join(';');
    const ws = presentStages.map((s) => railBy[s].w).join(';');
    const kts = presentStages.map((s, idx) => (idx === 0 ? '0' : kt(stageStart[s] / TOTAL))).join(';');
    anim =
      `<animate attributeName="x" begin="0s" dur="${num(TOTAL)}s" calcMode="discrete" values="${xs}" keyTimes="${kts}" fill="freeze"/>` +
      `<animate attributeName="width" begin="0s" dur="${num(TOTAL)}s" calcMode="discrete" values="${ws}" keyTimes="${kts}" fill="freeze"/>`;
  }
  body.push(`<rect data-role="stage-marker" x="${railBy[base].x}" y="${RAIL_UNDER_Y}" width="${railBy[base].w}" height="2" fill="${C.accent}">${anim}</rect>`);
}

// stage-rail labels (active = accent, others muted; recolor as beats advance)
for (const r of rail) {
  const present = r.s in stageStart;
  const idx = present ? presentStages.indexOf(r.s) : -1;
  const baseFill = idx === 0 ? C.accent : C.muted;
  let sets = '';
  if (idx > 0) sets += `<set attributeName="fill" to="${C.accent}" begin="${num(stageStart[r.s])}s" fill="freeze"/>`;
  if (idx >= 0 && idx < presentStages.length - 1) {
    const next = presentStages[idx + 1];
    sets += `<set attributeName="fill" to="${C.muted}" begin="${num(stageStart[next])}s" fill="freeze"/>`;
  }
  body.push(`<text data-role="stage" x="${r.x}" y="${RAIL_BASE}" fill="${baseFill}" font-size="13">${esc(r.s)}${sets}</text>`);
}

// transcript lines
beats.forEach((b, i) => {
  const ln = b.ln;
  const cfg = b.cfg;
  const y = BL(i);
  const glyph = esc(cfg.glyph);
  const mf = markerFill(ln, cfg);
  const cf = contentFill(ln, cfg);
  const indent = cfg.indent || 0;              // extra marker-columns (0 for pipeline kinds)
  const xMarker = PAD_X + indent * ADV;
  const xContent = CONTENT_X + indent * ADV;

  if (b.typing) {
    // typed reveal via an animated clip (discrete char-by-char) + transient caret
    const n = b.n;
    // discrete char-by-char reveal widths; pad ONLY the final step so real glyph-advance
    // drift (~0.03px/char) can never clip the last character once fully typed.
    const wArr = Array.from({ length: n + 1 }, (_, k) => k * ADV);
    wArr[n] = n * ADV + 6 * ADV;
    const wVals = wArr.join(';');
    const xVals = Array.from({ length: n + 1 }, (_, k) => xContent + k * ADV).join(';');
    const keyT = Array.from({ length: n + 1 }, (_, k) => kt(k / n)).join(';');
    const clipId = 'clip-' + ln.id;
    defs.push(
      `<clipPath id="${esc(clipId)}"><rect x="${xContent}" y="${y - 13}" width="0" height="18">` +
      `<animate attributeName="width" begin="${num(b.begin)}s" dur="${num(b.dur)}s" calcMode="discrete" values="${wVals}" keyTimes="${keyT}" fill="freeze"/>` +
      `</rect></clipPath>`
    );
    body.push(
      `<g data-role="line">` +
        `<text data-role="marker" x="${xMarker}" y="${y}" fill="${mf}" opacity="0">${glyph}<set attributeName="opacity" to="1" begin="${num(b.begin)}s" fill="freeze"/></text>` +
        `<g clip-path="url(#${esc(clipId)})"><text data-trace-id="${esc(ln.id)}" x="${xContent}" y="${y}" fill="${cf}" xml:space="preserve">${esc(ln.text)}</text></g>` +
        `<rect data-role="caret" x="${xContent}" y="${y - 13}" width="1.5" height="16" fill="${C.ink}" opacity="0">` +
          `<set attributeName="opacity" to="1" begin="${num(b.begin)}s" fill="freeze"/>` +
          `<animate attributeName="x" begin="${num(b.begin)}s" dur="${num(b.dur)}s" calcMode="discrete" values="${xVals}" keyTimes="${keyT}" fill="freeze"/>` +
          `<set attributeName="opacity" to="0" begin="${num(b.begin + b.dur)}s" fill="freeze"/>` +
        `</rect>` +
      `</g>`
    );
  } else {
    // machine line: whole-line fade + slight rise, in ordinal order
    body.push(
      `<g data-role="line" opacity="0" transform="translate(0 6)">` +
        `<animate attributeName="opacity" begin="${num(b.begin)}s" dur="${num(b.dur)}s" from="0" to="1" fill="freeze"/>` +
        `<animateTransform attributeName="transform" type="translate" begin="${num(b.begin)}s" dur="${num(b.dur)}s" from="0 6" to="0 0" fill="freeze"/>` +
        `<text data-role="marker" x="${xMarker}" y="${y}" fill="${mf}">${glyph}</text>` +
        `<text data-trace-id="${esc(ln.id)}" x="${xContent}" y="${y}" fill="${cf}" xml:space="preserve">${esc(ln.text)}</text>` +
      `</g>`
    );
  }
});

// persistent dim footer
body.push(`<text data-role="footer" x="${PAD_X}" y="${footerBL}" fill="${C.footer}" font-size="12">${esc(footer)}</text>`);

// ---------- emit ----------
const svg =
`<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="${FS}">
<defs>
${defs.join('\n')}
</defs>
${body.join('\n')}
</svg>
`;
const out = nfc(svg);
writeFileSync(outPath, out, 'utf8');
process.stdout.write(`gen-svg: wrote ${outPath} (${Buffer.byteLength(out, 'utf8')} bytes, ${nLines} lines, total ~${num(TOTAL)}s)\n`);
