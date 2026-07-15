# Trace manifest schema

The hero generator (`gen-svg.mjs`) is content-agnostic. It renders whatever a
**trace manifest** describes. This file documents that manifest so real content
can be swapped in later without touching the generator.

A manifest is a single JSON object:

```jsonc
{
  "meta": {
    "session_title": "claude — awesome-claude-harness",   // string, centered in the window chrome
    "rail": ["context", "safe-tools", "provenance"],       // optional string[]; the ordered rail labels.
                                                            //   Omit to derive the rail from the distinct
                                                            //   `stage` values in first-appearance order.
    "footer": "composed from a real /spec→…→/push run · stylized, condensed · not realtime"
                                                            // string, persistent dim footer (verbatim)
  },
  "lines": [ /* one object per transcript line, see below */ ]
}
```

## `lines[]` object

| field            | type    | required            | meaning |
|------------------|---------|---------------------|---------|
| `id`             | string  | yes                 | Stable, unique. Becomes the `data-trace-id` on the rendered `<text>` node. |
| `ordinal`        | integer | yes                 | Global render order. Must be **nondecreasing** across the array. |
| `stage`          | string  | yes                 | A rail label. The rail is **data-driven**: the `meta.rail` list, or (when absent) the distinct `stage` values in first-appearance order. Every line's stage must be in the rail, and stage rank must be **nondecreasing** across the array (lines are grouped by rail order). |
| `kind`           | enum    | yes                 | One of `input` \| `attempt` \| `artifact` \| `verdict` \| `condensation` \| `adaptation`. Controls prefix + reveal (see below). |
| `text`           | string  | yes                 | The **verbatim** content line, WITHOUT the prefix glyph. The generator prepends the prefix; the rendered `<text>` node contains exactly this string (NFC-normalized). |
| `block`          | boolean | only `verdict`      | When `true`, a `verdict` renders as a hook-BLOCK: the `⊘` glyph in the warm accent. Omit or `false` for a normal verdict. |
| `count`          | integer | only `condensation` | How many items were condensed. Must also appear inside `text`, next to a literal `…` (U+2026). |
| `source_ref`     | string  | recommended         | Provenance: a file path or a commit SHA the line was extracted from. |
| `source_locator` | string  | recommended         | Finer provenance, e.g. `path:line`. |
| `extract_hash`   | string  | recommended         | `sha256(NFC(text))` in lowercase hex. When present, the auditor recomputes and enforces it. |

## `kind` → prefix + reveal

| kind                | prefix | color emphasis                          | animation |
|---------------------|:------:|-----------------------------------------|-----------|
| `input`             | `›`    | ink                                     | **typed** char-by-char (clip reveal), transient caret |
| `attempt`           | `›`    | ink (the thing the agent tried)         | **typed** char-by-char (clip reveal), transient caret |
| `artifact`          | `✓`    | ink (marker muted)                      | whole-line fade + slight rise |
| `verdict`           | `✓`    | strong ink (slightly darker = "stronger")| whole-line fade + slight rise |
| `verdict` + `block` | `⊘`    | warm-accent glyph + strong-ink text (hook BLOCK; never red/green) | whole-line fade + slight rise |
| `condensation`      | `·`    | muted; MUST show `count` + literal `…`  | whole-line fade + slight rise |
| `adaptation`        | `→`    | muted, indented one column (what the agent did instead) | whole-line fade + slight rise |

Only `input` and `attempt` are typed (a mid-type frame is a *prefix* of `text`); every
other kind renders the FULL `text` in one reveal. The prefix glyph is rendered as a
**separate** marker element (`data-role="marker"`),
so the content `<text data-trace-id>` node equals `text` exactly — this is what the
auditor checks.

## Color discipline (paper substrate)

One restrained warm accent (`#B07C2C`) is used **only** on (a) the active stage
marker on the rail, (b) the final line (the commit-SHA / publish line = highest
`ordinal`), and (c) the `⊘` glyph of a hook-BLOCK (`verdict` + `block`). No green/red
verdict colors. Ordinary verdicts are emphasized with darker ink, not the accent.

## Guarantees

- Deterministic: identical manifest → byte-identical SVG. No wall-clock, no randomness.
- Self-contained: no `<script>`, no `<style>` block, no external refs, no webfonts.
- Loops indefinitely (`repeatCount="indefinite"`): plays the reveal, holds the final frame ~2.5s, then restarts.

## Auditing (`audit.mjs`)

Beyond structure/order/self-containment, the auditor enforces:

- **Source spans**: each line's `source_ref` is resolved and its `text` must genuinely
  appear there — a verbatim substring of a present, non-gitignored file, or found via
  `git show <sha>` / subject / short-sha for a commit source. A resolvable source that
  does NOT contain the text is a **hard fail**; a gitignored/missing/unreadable source
  **warns** (a clean clone lacks gitignored sources).
- **Role / footer**: the in-SVG footer equals `meta.footer`, the chrome title equals
  `meta.session_title`, and the rail labels are **exactly** the manifest-derived stages.
- **Prefix match**: a partial (prefix) rendered text is tolerated ONLY for the typed
  kinds (`input`, `attempt`); every other kind must match the FULL `text` (a truncation
  like `CLOSE` for `CLOSE: YES` fails).

See `sample-trace.json` for a 5-stage pipeline **placeholder** manifest, and
`sample-hook-trace.json` for a 3-stage hook / context-engineering demo exercising the
`attempt` / `verdict`+`block` / `adaptation` kinds and an explicit `meta.rail`. Both use
obviously illustrative values that must be replaced with real extracted content.
