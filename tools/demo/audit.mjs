#!/usr/bin/env node
// audit.mjs — verifies a generated hero SVG against its trace manifest.
//
// Asserts:
//   - every content <text> carries a data-trace-id present in the manifest, and its
//     rendered string equals the manifest line's text (or an exact prefix, for a
//     typing reveal); every non-content <text> carries a known data-role.
//   - trace nodes appear in ordinal order; ordinals and stage ranks are nondecreasing.
//   - condensation lines carry an integer count and their text shows the count + a literal '…'.
//   - manifest extract_hash (when present) equals sha256(NFC(text)).
//   - SVG is self-contained: no <script>, no <style> block, no @font-face, no external refs.
//   - tag balance (svg/g/text/clipPath).
//
// Usage:  node audit.mjs <manifest.json> <file.svg>
// Exit:   0 pass, 1 on any violation.

import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

const STAGES = ['spec', 'dev', 'close', 'commit', 'push'];
const RANK = Object.fromEntries(STAGES.map((s, i) => [s, i]));
const KINDS = new Set(['input', 'artifact', 'verdict', 'condensation']);
const ROLES = new Set(['chrome-title', 'footer', 'stage', 'marker']);
const ELLIPSIS = '…';

const nfc = (s) => String(s).normalize('NFC');
const sha256 = (s) => createHash('sha256').update(nfc(s), 'utf8').digest('hex');

const manifestPath = process.argv[2];
const svgPath = process.argv[3];
if (!manifestPath || !svgPath) { console.error('Usage: node audit.mjs <manifest.json> <file.svg>'); process.exit(1); }

const violations = [];
const V = (m) => violations.push(m);

const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
const svg = readFileSync(svgPath, 'utf8');
const lines = Array.isArray(manifest.lines) ? manifest.lines : [];

// ---------- manifest self-consistency ----------
if (lines.length === 0) V('manifest.lines is empty');
let prevOrd = -Infinity, prevRank = -Infinity;
const ids = new Set();
for (const ln of lines) {
  if (ids.has(ln.id)) V(`duplicate manifest id "${ln.id}"`);
  ids.add(ln.id);
  if (!KINDS.has(ln.kind)) V(`${ln.id}: bad kind "${ln.kind}"`);
  if (!(ln.stage in RANK)) V(`${ln.id}: bad stage "${ln.stage}"`);
  if (typeof ln.ordinal !== 'number') V(`${ln.id}: ordinal is not a number`);
  else if (ln.ordinal < prevOrd) V(`${ln.id}: ordinal ${ln.ordinal} < previous ${prevOrd}`);
  const rank = RANK[ln.stage] ?? -1;
  if (rank < prevRank) V(`${ln.id}: stage "${ln.stage}" rank < previous`);
  if (typeof ln.ordinal === 'number') prevOrd = ln.ordinal;
  if (rank >= 0) prevRank = rank;

  if ('extract_hash' in ln) {
    const h = sha256(ln.text);
    if (h !== ln.extract_hash) V(`${ln.id}: extract_hash mismatch (manifest ${ln.extract_hash}, actual ${h})`);
  }
  if (ln.kind === 'condensation') {
    if (!Number.isInteger(ln.count)) V(`${ln.id}: condensation missing integer "count"`);
    else if (!nfc(ln.text).includes(String(ln.count))) V(`${ln.id}: condensation text missing count ${ln.count}`);
    if (!nfc(ln.text).includes(ELLIPSIS)) V(`${ln.id}: condensation text missing literal '…'`);
  }
}

// ---------- SVG self-containment ----------
if (/<script[\s>]/i.test(svg)) V('SVG contains <script>');
if (/<style[\s>]/i.test(svg)) V('SVG contains a <style> block (animation must be SMIL)');
if (/@font-face/i.test(svg)) V('SVG contains @font-face (no webfonts allowed)');
if (/<foreignObject/i.test(svg)) V('SVG contains <foreignObject>');
if (/<image[\s>]/i.test(svg)) V('SVG contains <image>');
if (/\bhref\s*=/i.test(svg)) V('SVG contains an href attribute (external ref)');
if (/url\((?!#)/i.test(svg)) V('SVG contains a non-internal url() reference');
const svgNoNs = svg.replace(/xmlns(:\w+)?="http:\/\/www\.w3\.org\/[^"]*"/g, '');
if (/https?:\/\//i.test(svgNoNs)) V('SVG contains an external http(s) reference');

// ---------- tag balance ----------
for (const tag of ['svg', 'g', 'text', 'clipPath']) {
  const open = (svg.match(new RegExp(`<${tag}\\b`, 'g')) || []).length;
  const close = (svg.match(new RegExp(`</${tag}>`, 'g')) || []).length;
  if (open !== close) V(`unbalanced <${tag}>: ${open} open vs ${close} close`);
}

// ---------- text-node walk ----------
const textRe = /<text\b([^>]*)>([\s\S]*?)<\/text>/g;
const attrRe = /([a-zA-Z_:][\w:.\-]*)\s*=\s*"([^"]*)"/g;
const attrs = (s) => { const o = {}; let m; while ((m = attrRe.exec(s))) o[m[1]] = m[2]; return o; };
const unesc = (s) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&amp;/g, '&');
const byId = new Map(lines.map((l) => [l.id, l]));

const traceSeq = [];
let m;
while ((m = textRe.exec(svg))) {
  const a = attrs(m[1]);
  if ('data-trace-id' in a) {
    const id = a['data-trace-id'];
    traceSeq.push(id);
    const ln = byId.get(id);
    if (!ln) { V(`SVG text data-trace-id="${id}" not present in manifest`); continue; }
    const txt = nfc(unesc(m[2]));
    const want = nfc(ln.text);
    if (txt !== want && !want.startsWith(txt)) V(`${id}: rendered text != manifest text (and not an exact prefix)`);
    if (ln.kind === 'condensation') {
      if (!txt.includes(ELLIPSIS)) V(`${id}: rendered condensation missing '…'`);
      if (Number.isInteger(ln.count) && !txt.includes(String(ln.count))) V(`${id}: rendered condensation missing count ${ln.count}`);
    }
  } else {
    const role = a['data-role'];
    if (!ROLES.has(role)) V(`<text> lacks data-trace-id and has unknown data-role="${role}"`);
  }
}

// ---------- ordering + coverage ----------
const expected = lines
  .map((l, i) => ({ l, i }))
  .sort((x, y) => (x.l.ordinal - y.l.ordinal) || (x.i - y.i))
  .map((x) => x.l.id);

if (traceSeq.length !== expected.length) V(`trace-node count ${traceSeq.length} != manifest line count ${expected.length}`);
for (let i = 0; i < Math.min(traceSeq.length, expected.length); i++) {
  if (traceSeq[i] !== expected[i]) V(`render order mismatch at index ${i}: SVG "${traceSeq[i]}" vs expected "${expected[i]}"`);
}
for (const id of ids) if (!traceSeq.includes(id)) V(`manifest id "${id}" has no <text data-trace-id> in SVG`);

// ---------- verdict ----------
const bytes = Buffer.byteLength(svg, 'utf8');
if (violations.length) {
  console.error(`AUDIT FAIL (${violations.length} violation${violations.length === 1 ? '' : 's'}):`);
  for (const v of violations) console.error('  - ' + v);
  process.exit(1);
}
console.log(`AUDIT PASS — ${lines.length} manifest lines, ${traceSeq.length} trace nodes, ${(bytes / 1024).toFixed(1)} KB, 0 <script>, 0 external refs.`);
process.exit(0);
