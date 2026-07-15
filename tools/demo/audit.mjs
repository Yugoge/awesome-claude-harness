#!/usr/bin/env node
// audit.mjs — verifies a generated hero SVG against its trace manifest.
//
// Asserts:
//   - every content <text> carries a data-trace-id present in the manifest, and its
//     rendered string matches the manifest line's text. A prefix (partial) match is
//     tolerated ONLY for typing-reveal kinds (`input`, `attempt`); every other kind must
//     match the FULL manifest text (a truncation like `CLOSE` for `CLOSE: YES` fails).
//   - every non-content <text> carries a known data-role.
//   - trace nodes appear in ordinal order; ordinals and stage ranks are nondecreasing.
//   - condensation lines carry an integer count and their text shows the count + a literal '…'.
//   - manifest extract_hash (when present) equals sha256(NFC(text)).
//   - SOURCE SPANS: each line's `source_ref` is resolved and the line `text` is shown to be
//     genuinely present there — a verbatim substring of a present, non-gitignored file, or
//     found in `git show <sha>` / subject / short-sha for a commit source. A resolvable
//     source that does NOT contain the text is a HARD FAIL; gitignored/missing/unreadable WARNS.
//   - ROLE/FOOTER: the in-SVG footer equals meta.footer, the chrome title equals
//     meta.session_title, and the rail labels are EXACTLY the manifest-derived stages
//     (no un-manifested visible role text slips through).
//   - SVG is self-contained: no <script>, no <style> block, no @font-face, no external refs.
//   - tag balance (svg/g/text/clipPath).
//
// Usage:  node audit.mjs <manifest.json> <file.svg>
// Exit:   0 pass (may include non-fatal warnings), 1 on any violation.

import { readFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { resolve, isAbsolute } from 'node:path';

const KINDS = new Set(['input', 'attempt', 'artifact', 'verdict', 'condensation', 'adaptation']);
const TYPING_KINDS = new Set(['input', 'attempt']); // the only kinds where a prefix reveal is allowed
const ROLES = new Set(['chrome-title', 'footer', 'stage', 'marker']);
const ELLIPSIS = '…';

const nfc = (s) => String(s).normalize('NFC');
const sha256 = (s) => createHash('sha256').update(nfc(s), 'utf8').digest('hex');

const manifestPath = process.argv[2];
const svgPath = process.argv[3];
if (!manifestPath || !svgPath) { console.error('Usage: node audit.mjs <manifest.json> <file.svg>'); process.exit(1); }

const violations = [];
const warnings = [];
const verified = [];
const V = (m) => violations.push(m);
const W = (m) => warnings.push(m);

const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
const svg = readFileSync(svgPath, 'utf8');
const meta = manifest.meta || {};
const lines = Array.isArray(manifest.lines) ? manifest.lines : [];

// ---------- data-driven rail (mirrors gen-svg exactly) ----------
// Explicit `meta.rail` wins; otherwise distinct `stage` values in first-appearance
// (ordinal) order. This is the authoritative list the SVG's rail labels must match.
const sorted = lines
  .map((l, i) => ({ l, i }))
  .sort((a, b) => (a.l.ordinal - b.l.ordinal) || (a.i - b.i))
  .map((x) => x.l);
let RAIL;
if (Array.isArray(meta.rail) && meta.rail.length) {
  RAIL = meta.rail.map((s) => nfc(s));
} else {
  RAIL = [];
  const seen = new Set();
  for (const ln of sorted) { if (ln && !seen.has(ln.stage)) { seen.add(ln.stage); RAIL.push(nfc(ln.stage)); } }
}
const RANK = Object.fromEntries(RAIL.map((s, i) => [s, i]));

// ---------- manifest self-consistency ----------
if (lines.length === 0) V('manifest.lines is empty');
let prevOrd = -Infinity, prevRank = -Infinity;
const ids = new Set();
for (const ln of lines) {
  if (ids.has(ln.id)) V(`duplicate manifest id "${ln.id}"`);
  ids.add(ln.id);
  if (!KINDS.has(ln.kind)) V(`${ln.id}: bad kind "${ln.kind}"`);
  if (!(nfc(ln.stage) in RANK)) V(`${ln.id}: stage "${ln.stage}" not in rail [${RAIL.join(', ')}]`);
  if (typeof ln.ordinal !== 'number') V(`${ln.id}: ordinal is not a number`);
  else if (ln.ordinal < prevOrd) V(`${ln.id}: ordinal ${ln.ordinal} < previous ${prevOrd}`);
  const rank = RANK[nfc(ln.stage)] ?? -1;
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

// ---------- source-span verification (#3) ----------
// A line's text must genuinely trace to its declared source. File sources are hard-checked
// when present-and-not-gitignored; a clean clone lacks gitignored sources, so those WARN.
let repoRoot = null;
try {
  repoRoot = execFileSync('git', ['rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim();
} catch { repoRoot = null; }
const runGit = (args) =>
  execFileSync('git', args, {
    encoding: 'utf8', cwd: repoRoot || process.cwd(),
    stdio: ['ignore', 'pipe', 'ignore'], maxBuffer: 128 * 1024 * 1024,
  });

function verifySource(ln) {
  const ref = ln.source_ref;
  const text = nfc(ln.text);
  if (!ref || typeof ref !== 'string') { W(`${ln.id}: no source_ref (provenance unverified)`); return; }

  if (/^[0-9a-f]{7,40}$/i.test(ref)) {
    // ----- commit SHA source -----
    if (!repoRoot) { W(`${ln.id}: source ${ref} is a commit but git is unavailable (unverified)`); return; }
    let full;
    try { full = runGit(['rev-parse', '--verify', '--quiet', `${ref}^{commit}`]).trim(); }
    catch { W(`${ln.id}: source ${ref} is not a resolvable commit in this clone (unverified)`); return; }
    let haystack = '';
    try { haystack = runGit(['show', '--no-color', full]); } catch { haystack = ''; }
    const short = full.slice(0, 7);
    // verified iff the text appears in the commit (subject/body/diff/full-sha line) OR the
    // text references the commit by its short sha (e.g. a push refspec `a..62957b35`).
    if (nfc(haystack).includes(text) || text.includes(short)) verified.push(`${ln.id} → commit ${short}`);
    else V(`${ln.id}: text not found in commit ${short} (git show / subject / short-sha): "${text.slice(0, 64)}"`);
    return;
  }

  // ----- file-path source -----
  if (!repoRoot) { W(`${ln.id}: source ${ref} (git unavailable, unverified)`); return; }
  let ignored = false;
  try { runGit(['check-ignore', '-q', '--', ref]); ignored = true; } catch { ignored = false; }
  if (ignored) { W(`${ln.id}: source ${ref} is gitignored (absent from a clean clone) — unverified`); return; }
  const abs = isAbsolute(ref) ? ref : resolve(repoRoot, ref);
  if (!existsSync(abs)) { W(`${ln.id}: source ${ref} missing on disk — unverified`); return; }
  let content;
  try { content = readFileSync(abs, 'utf8'); } catch { W(`${ln.id}: source ${ref} unreadable — unverified`); return; }
  if (nfc(content).includes(text)) verified.push(`${ln.id} → ${ref}`);
  else V(`${ln.id}: text is not a verbatim substring of source ${ref}: "${text.slice(0, 64)}"`);
}
for (const ln of lines) verifySource(ln);

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

// ---------- animation loops (intended state) ----------
// The hero now LOOPS: the reveal plays, holds the final frame (~2.5s so the end-state stays
// readable), then restarts forever — this replaced the earlier animate-once-freeze model, so a
// looping SVG is the valid target. Assert the loop driver is present; this catches a regression
// back to a one-shot frozen animation while self-containment above still forbids <script>/<style>.
if (!/\brepeatCount="indefinite"/.test(svg)) V('SVG animation does not loop — expected repeatCount="indefinite" (animate-once-freeze is no longer the intended state)');

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
const stripChildren = (s) => s.replace(/<[^>]*>/g, ''); // drop nested <set>/<animate> before reading label text
const byId = new Map(lines.map((l) => [l.id, l]));

const traceSeq = [];
const stageLabels = [];
let footerText = null, titleText = null;
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
    if (TYPING_KINDS.has(ln.kind)) {
      // typing reveal: full text, or an exact prefix captured mid-type
      if (txt !== want && !want.startsWith(txt)) V(`${id}: rendered text is not an exact prefix of manifest text`);
    } else {
      // every other kind must render the FULL manifest text — no truncation
      if (txt !== want) V(`${id}: rendered text != manifest text (full match required for kind "${ln.kind}")`);
    }
    if (ln.kind === 'condensation') {
      if (!txt.includes(ELLIPSIS)) V(`${id}: rendered condensation missing '…'`);
      if (Number.isInteger(ln.count) && !txt.includes(String(ln.count))) V(`${id}: rendered condensation missing count ${ln.count}`);
    }
  } else {
    const role = a['data-role'];
    if (!ROLES.has(role)) V(`<text> lacks data-trace-id and has unknown data-role="${role}"`);
    const label = nfc(unesc(stripChildren(m[2])));
    if (role === 'stage') stageLabels.push(label);
    else if (role === 'footer') footerText = label;
    else if (role === 'chrome-title') titleText = label;
  }
}

// ---------- role/footer verification (#4) ----------
const wantFooter = nfc(meta.footer || '');
if (footerText === null) V('SVG has no data-role="footer" text');
else if (footerText !== wantFooter) V(`footer text mismatch: SVG "${footerText}" != meta.footer "${wantFooter}"`);

const wantTitle = nfc(meta.session_title || 'claude');
if (titleText === null) V('SVG has no data-role="chrome-title" text');
else if (titleText !== wantTitle) V(`chrome-title mismatch: SVG "${titleText}" != meta.session_title "${wantTitle}"`);

if (stageLabels.length !== RAIL.length) V(`rail label count ${stageLabels.length} != manifest-derived rail ${RAIL.length} [${RAIL.join(', ')}]`);
for (let i = 0; i < Math.min(stageLabels.length, RAIL.length); i++) {
  if (stageLabels[i] !== RAIL[i]) V(`rail label[${i}] "${stageLabels[i]}" != manifest-derived stage "${RAIL[i]}"`);
}

// ---------- ordering + coverage ----------
const expected = sorted.map((l) => l.id);

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
  if (warnings.length) {
    console.error(`  (${warnings.length} non-fatal warning${warnings.length === 1 ? '' : 's'}:)`);
    for (const w of warnings) console.error('  ~ ' + w);
  }
  process.exit(1);
}
console.log(`AUDIT PASS — ${lines.length} manifest lines, ${traceSeq.length} trace nodes, ${(bytes / 1024).toFixed(1)} KB, 0 <script>, 0 external refs.`);
console.log(`  rail: [${RAIL.join(' › ')}]  ·  footer ✓  ·  ${verified.length} source-verified, ${warnings.length} warned`);
if (verified.length) { console.log('  source-verified:'); for (const v of verified) console.log('    ✓ ' + v); }
if (warnings.length) { console.log('  warned (non-fatal — clean-clone / gitignored sources):'); for (const w of warnings) console.log('    ~ ' + w); }
process.exit(0);
