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
// Usage:  node audit.mjs <manifest.json> <file.svg> [--strict]
// Exit:   0 pass (may include non-fatal warnings), 1 on any violation.
//         --strict (opt-in): escalate EVERY provenance downgrade (a non-fatal warning —
//         no source_ref / unreadable / missing / gitignored / unresolvable-commit /
//         git-unavailable) to a hard violation. Default behavior is unchanged without it.

import { readFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { resolve, isAbsolute, dirname, basename, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const KINDS = new Set(['input', 'attempt', 'artifact', 'verdict', 'condensation', 'adaptation']);
const TYPING_KINDS = new Set(['input', 'attempt']); // the only kinds where a prefix reveal is allowed
const ROLES = new Set(['chrome-title', 'footer', 'stage', 'marker']);
const ELLIPSIS = '…';

const nfc = (s) => String(s).normalize('NFC');
const sha256 = (s) => createHash('sha256').update(nfc(s), 'utf8').digest('hex');

// Parse args: strip the opt-in --strict flag, then require EXACTLY two positionals so the
// default `node audit.mjs <manifest> <svg>` signature is preserved for existing callers.
const rawArgs = process.argv.slice(2);
const STRICT = rawArgs.includes('--strict');
const positionals = rawArgs.filter((a) => a !== '--strict');
const [manifestPath, svgPath, ...extra] = positionals;
if (!manifestPath || !svgPath || extra.length) {
  console.error('Usage: node audit.mjs <manifest.json> <file.svg> [--strict]');
  process.exit(1);
}

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
const traceGeom = []; // {id, x, text, kind} — feeds the rendered-width/clipping assertion
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
    const xAttr = parseFloat(a['x']);
    traceGeom.push({ id, x: Number.isFinite(xAttr) ? xAttr : null, text: want, kind: nfc(ln.kind) });
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

// ---------- rendered-width / clipping detection ----------
// The renderer lays every transcript line on a FIXED MONOSPACE GRID, so a line's rendered
// right edge is exactly linear in its character count and is computable here without a
// browser. Anything past the asset's own viewBox width is cut off by the SVG viewport.
// Nothing else in this file could see that: the manifest text and the SVG text still match
// byte-for-byte, so a load-bearing proof line was published cut mid-path while this auditor
// reported "17 source-verified, 0 warned". Provenance was intact; the RENDERING was not.
//
// The ledger below records clipping that is known, itemised and accepted for now — never
// clipping that is hidden. A line the manifest classifies as `verdict` carries the
// demonstration's proof and may NEVER be ledgered: that is the difference between
// disclosing a defect and blessing one.
const vbMatch = svg.match(/viewBox="0 0 (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)"/);
const LOGICAL_W = vbMatch ? parseFloat(vbMatch[1]) : null;

// Character advance is DERIVED from the asset, not assumed: a typing clip reveals its line
// in whole-character steps, so the first positive step is exactly one character advance.
const deriveAdvance = () => {
  const m2 = svg.match(/<animate attributeName="width"[^>]*values="([^"]+)"/);
  if (!m2) return null;
  const vals = m2[1].split(';').map(Number).filter((v) => Number.isFinite(v));
  for (let i = 1; i < vals.length; i++) if (vals[i] - vals[i - 1] > 0) return vals[i] - vals[i - 1];
  return null;
};
const ADV = deriveAdvance();

// ---------- advance cross-check: the asset must not supply the ruler that measures it ----------
// The clipping assertion below measures with a unit READ FROM THE ASSET UNDER TEST, so an asset
// that declares a too-small advance reports itself un-clipped. That is fail-OPEN, and it was
// proven end-to-end: a 16-line asset cutting 9 lines, 4 of them kind "verdict", declaring an
// advance of 1 instead of 9, audited clean — exit 0, zero clipping diagnostics. A detector an
// asset can blind is not a detector.
//
// The declared advance is therefore corroborated against sources the asset cannot restate
// without visibly destroying itself, none of which is the declaration:
//   (a) the font-size IN EFFECT ON THE MEASURED LINE TEXT — a monospace advance is a fixed
//       fraction of the em, so shrinking the advance means shrinking the type to match, to a
//       size no one can read. Resolved through the cascade, never read off the root: see
//       lineFontSizes() below for the proven attack that reading the root alone let through;
//   (b) the stage-rail pitch — consecutive rail label x positions divided by the label's own
//       character count, where the label TEXT is already pinned to the manifest above. Present
//       in every asset, including those with no typed line, which is exactly the case the
//       proven attack used;
//   (c) the first typing-reveal clip step, when the asset has a typed line.
// Disagreement with any corroborator is a HARD violation: it is an attack signature, not a
// degradation. Having NO corroborator is a provenance downgrade, so --strict escalates it.
// This validates the assertion's INPUT; the assertion itself is untouched.
const MONO_RATIO_MIN = 0.45, MONO_RATIO_MAX = 0.80; // ui-monospace/Menlo/Consolas sit at ~0.6
const RAIL_GUTTER_COLS = 3;                         // gen-svg: rx += label.length*ADV + 3*ADV
const firstStep = (csv) => {
  const vals = String(csv).split(';').map(Number).filter((v) => Number.isFinite(v));
  for (let i = 1; i < vals.length; i++) if (vals[i] - vals[i - 1] > 0) return vals[i] - vals[i - 1];
  return null;
};
// The font-size governing the text the clipping check MEASURES, resolved through the SVG
// cascade rather than read off the root. font-size INHERITS, so a declaration on a <text>
// element — or on any enclosing <g> — overrides the root attribute. Reading the root alone
// was fail-OPEN and was proven so: an asset declaring a root font-size of 1.667 while pinning
// its 16 line elements back to font-size 15 satisfied this corroborator with its type at full
// readable size, and audited clean — exit 0, "0 warned", zero clipping diagnostics — while a
// browser measured that same text at 15px and 9 of 16 lines, 4 of them kind "verdict",
// genuinely overflowed the panel. The forger was NOT forced to shrink anything: the root
// attribute is a declaration about nothing, and the corroborator has to read the size the
// measured text actually renders at.
const FS_ATTR = /\bfont-size\s*=\s*"\s*([\d.]+)(?:px)?\s*"/;
const FS_STYLE = /\bstyle\s*=\s*"[^"]*?\bfont-size\s*:\s*([\d.]+)(?:px)?/;
const declaredFS = (tag) => {
  const s = tag.match(FS_STYLE); if (s) return parseFloat(s[1]); // an inline style beats the attribute
  const a = tag.match(FS_ATTR); if (a) return parseFloat(a[1]);
  return null;
};
const lineFontSizes = () => {
  const out = [], stack = [];
  const tagRe = /<(\/?)(svg|g|text)\b([^>]*)>/g;
  let t;
  while ((t = tagRe.exec(svg))) {
    if (t[1]) { stack.pop(); continue; }
    const own = declaredFS(t[3]);
    const eff = own === null ? (stack.length ? stack[stack.length - 1] : null) : own;
    if (t[2] === 'text' && /\bdata-trace-id\s*=/.test(t[3])) out.push(eff);
    if (!/\/\s*$/.test(t[3])) stack.push(eff);
  }
  return out;
};
const advanceCorroborators = () => {
  const out = [];
  // A <style> block can re-size the measured text through selectors the walk above does not
  // resolve, so it is REFUSED rather than silently under-read — the same fail-closed choice
  // the disagreement branch makes below.
  if (/<style\b[\s\S]*?font-size/i.test(svg))
    V('the asset declares a font-size inside a <style> block, which the advance cross-check ' +
      'cannot resolve against the measured line text — refused rather than measured with a ' +
      'ruler the asset can move out from under it');
  const fsAll = lineFontSizes().filter((v) => Number.isFinite(v) && v > 0);
  const fsUniq = [...new Set(fsAll)];
  if (fsUniq.length > 1)
    V(`the measured line text does not share a single font-size (${fsUniq.join('px, ')}px), so ` +
      `no one character advance can describe this asset and the clipping check below would ` +
      `measure most of its lines with the wrong ruler`);
  const rootM = svg.match(/<svg\b[^>]*>/);
  // Lines present ⇒ their own effective size is the only honest ruler. No lines at all ⇒ the
  // clipping check is vacuous anyway, so the root declaration is all there is to corroborate.
  const fs = fsUniq.length === 1 ? fsUniq[0] : (fsAll.length ? null : (rootM ? declaredFS(rootM[0]) : null));
  if (fs > 0) out.push({ src: `the font-size in effect on the measured line text (${fs}px)`,
                         lo: fs * MONO_RATIO_MIN, hi: fs * MONO_RATIO_MAX,
                         implies: `${(fs * MONO_RATIO_MIN).toFixed(2)}–${(fs * MONO_RATIO_MAX).toFixed(2)}px` });
  const xs = [...svg.matchAll(/<text data-role="stage" x="([\d.]+)"/g)].map((r) => parseFloat(r[1]));
  if (xs.length >= 2 && RAIL.length >= 2 && xs[1] > xs[0]) {
    const pitch = (xs[1] - xs[0]) / (RAIL[0].length + RAIL_GUTTER_COLS);
    if (pitch > 0) out.push({ src: `the stage-rail pitch (labels "${RAIL[0]}" at x=${xs[0]}, "${RAIL[1]}" at x=${xs[1]})`,
                              lo: pitch - 1e-6, hi: pitch + 1e-6, implies: `${pitch}px` });
  }
  const clipM = svg.match(/<clipPath\b[^>]*>[\s\S]*?<animate attributeName="width"[^>]*values="([^"]+)"/);
  const clipStep = clipM ? firstStep(clipM[1]) : null;
  if (clipStep > 0) out.push({ src: 'the first typing-reveal clip step',
                               lo: clipStep - 1e-6, hi: clipStep + 1e-6, implies: `${clipStep}px` });
  return out;
};
if (ADV) {
  const corroborators = advanceCorroborators();
  if (!corroborators.length) {
    W(`the declared character advance (${ADV}px) could not be corroborated by any independent ` +
      `source in this asset, so clipping below is measured with an un-cross-checked ruler`);
  }
  for (const c of corroborators) {
    if (ADV < c.lo || ADV > c.hi) {
      V(`declared character advance ${ADV}px disagrees with ${c.src}, which implies ` +
        `${c.implies}. The clipping check measures with the advance the asset declares, so a ` +
        `false advance hides real clipping — a disagreeing declaration is refused, not used`);
    }
  }
}

const ledgerPath = join(dirname(fileURLToPath(import.meta.url)), 'known-clipped-ledger.json');
let ledgerEntries = [];
if (existsSync(ledgerPath)) {
  try {
    const all = JSON.parse(readFileSync(ledgerPath, 'utf8'));
    ledgerEntries = ((all.assets || {})[basename(svgPath)]) || [];
    if (!Array.isArray(ledgerEntries)) { V('known-clipped ledger: asset entry is not an array'); ledgerEntries = []; }
  } catch (e) { V(`known-clipped ledger is unreadable or invalid JSON: ${e.message}`); }
}

const clipped = [];
if (LOGICAL_W === null) W("asset logical width (viewBox) could not be parsed — clipping NOT checked");
else if (!ADV) W('character advance could not be derived from the asset — clipping NOT checked');
else {
  for (const g of traceGeom) {
    if (g.x === null) { W(`${g.id}: text node has no numeric x — clipping NOT checked for this line`); continue; }
    const right = g.x + g.text.length * ADV;
    if (right <= LOGICAL_W) continue;
    const visible = Math.max(0, Math.floor((LOGICAL_W - g.x) / ADV));
    clipped.push({ id: g.id, kind: g.kind, chars: g.text.length, right,
                   lost: g.text.slice(visible), visibleEndsAt: g.text.slice(0, visible).slice(-6) });
  }
}

// (1) Every ledger entry must itself be legitimate.
const clippedById = new Map(clipped.map((c) => [c.id, c]));
for (const e of ledgerEntries) {
  const id = e && e.trace_id;
  const ln = byId.get(id);
  if (!ln) { V(`known-clipped ledger names "${id}", which is absent from the manifest`); continue; }
  if (nfc(ln.kind) === 'verdict') {
    V(`known-clipped ledger contains "${id}", which the manifest classifies as kind "verdict" — ` +
      `a verdict line carries the demonstration's proof and may never be ledgered as acceptably clipped`);
  }
  if (typeof e.lost_text !== 'string') V(`known-clipped ledger entry "${id}" has no lost_text`);
  if (!e.restoration_condition || !String(e.restoration_condition).trim())
    V(`known-clipped ledger entry "${id}" has no restoration_condition`);
  const c = clippedById.get(id);
  if (!c) V(`known-clipped ledger entry "${id}" is stale: that line no longer overflows the logical width`);
  else if (typeof e.lost_text === 'string' && nfc(e.lost_text) !== nfc(c.lost))
    V(`known-clipped ledger entry "${id}": lost_text does not match what is actually cut off ` +
      `(ledger "${e.lost_text.slice(0, 48)}", measured "${c.lost.slice(0, 48)}")`);
}

// (2) Every clipped line is itemised with the exact substring it loses. Unledgered ones are
//     provenance downgrades, so --strict escalates them into hard violations centrally below.
const ledgerIds = new Set(ledgerEntries.map((e) => e && e.trace_id));
for (const c of clipped) {
  const detail = `${c.id}: rendered text overflows the asset's logical width ` +
    `(${c.chars} chars, right edge ${Math.round(c.right)}px > ${LOGICAL_W}px); ` +
    `${c.lost.length} characters are cut off after "…${c.visibleEndsAt}": "${c.lost}"`;
  if (ledgerIds.has(c.id)) continue;
  if (c.kind === 'verdict') {
    W(`${detail} — this line is kind "verdict", so it can NEVER be ledgered away; the ` +
      `clipping itself must be removed (shorten the emitting source, or give the renderer ` +
      `room for ${Math.ceil(c.right)}px) before this asset can pass --strict`);
  } else {
    W(`${detail} — and it is ABSENT from the known-clipped ledger`);
  }
}

// ---------- strict-mode escalation (opt-in) ----------
// In --strict, EVERY provenance downgrade (any warning recorded by W(), present OR future)
// becomes a hard violation. Implemented centrally here at the verdict — the individual W()
// call sites are never enumerated, so new warning sites inherit strictness automatically.
// This only ADDS to violations; it never removes or weakens an existing V() check, and the
// default (no --strict) path is untouched.
if (STRICT && warnings.length) {
  for (const w of warnings) violations.push(`[strict] ${w}`);
  warnings.length = 0;
}

// ---------- verdict ----------
const bytes = Buffer.byteLength(svg, 'utf8');
// Clipping is ALWAYS itemised, on pass and on fail alike — a counted-but-unnamed defect is
// how this went unnoticed before. Each line names the exact substring the reader never sees.
if (clipped.length) {
  const say = violations.length ? console.error : console.log;
  say(`  clipped (${clipped.length} of ${traceGeom.length} lines exceed the ${LOGICAL_W}px logical width):`);
  for (const c of clipped) {
    const led = ledgerIds.has(c.id) ? 'ledgered' : 'NOT ledgered';
    say(`    ! ${c.id} [${c.kind}] loses ${c.lost.length} chars (${led}): "${c.lost}"`);
  }
}
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
