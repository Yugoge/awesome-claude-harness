# Trace manifest schema

The hero generator (`gen-svg.mjs`) is content-agnostic. It renders whatever a
**trace manifest** describes. This file documents that manifest so real content
can be swapped in later without touching the generator.

A manifest is a single JSON object:

```jsonc
{
  "meta": {
    "session_title": "claude — awesome-claude-harness",   // string, centered in the window chrome
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
| `stage`          | enum    | yes                 | One of `spec` \| `dev` \| `close` \| `commit` \| `push`. Stage rank must be **nondecreasing** across the array (lines are grouped by the 5 stages in this fixed order). |
| `kind`           | enum    | yes                 | One of `input` \| `artifact` \| `verdict` \| `condensation`. Controls prefix + reveal (see below). |
| `text`           | string  | yes                 | The **verbatim** content line, WITHOUT the prefix glyph. The generator prepends the prefix; the rendered `<text>` node contains exactly this string (NFC-normalized). |
| `count`          | integer | only `condensation` | How many items were condensed. Must also appear inside `text`, next to a literal `…` (U+2026). |
| `source_ref`     | string  | recommended         | Provenance: a file path or a commit SHA the line was extracted from. |
| `source_locator` | string  | recommended         | Finer provenance, e.g. `path:line`. |
| `extract_hash`   | string  | recommended         | `sha256(NFC(text))` in lowercase hex. When present, the auditor recomputes and enforces it. |

## `kind` → prefix + reveal

| kind           | prefix | color emphasis                          | animation |
|----------------|:------:|-----------------------------------------|-----------|
| `input`        | `›`    | ink                                     | **typed** char-by-char (clip reveal), transient caret |
| `artifact`     | `✓`    | ink (marker muted)                      | whole-line fade + slight rise |
| `verdict`      | `✓`    | strong ink (slightly darker = "stronger")| whole-line fade + slight rise |
| `condensation` | `·`    | muted; MUST show `count` + literal `…`  | whole-line fade + slight rise |

The prefix glyph is rendered as a **separate** marker element (`data-role="marker"`),
so the content `<text data-trace-id>` node equals `text` exactly — this is what the
auditor checks.

## Color discipline (paper substrate)

One restrained warm accent (`#B07C2C`) is used **only** on (a) the active stage
marker on the rail and (b) the final line (the commit-SHA / publish line = highest
`ordinal`). No green/red verdict colors. Verdicts are emphasized with darker ink,
not with the accent (the accent is reserved).

## Guarantees

- Deterministic: identical manifest → byte-identical SVG. No wall-clock, no randomness.
- Self-contained: no `<script>`, no `<style>` block, no external refs, no webfonts.
- Animate once, then freeze (`fill="freeze"`) — no infinite loop.

See `sample-trace.json` for a schema-valid **placeholder** manifest (values are
obviously illustrative and must be replaced with real extracted content).
