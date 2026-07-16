#!/usr/bin/env python3
"""Per-evaluation Context object for the runtime_guard decision engine.

`_core.evaluate` computes a small set of per-EVALUATION inputs ONCE — the
pipeline-split simple commands, the pipeline groups, the base cwd seed, and
(after STEP1) the loaded config — then threads them POSITIONALLY through the
`_step*` / `_p0..p9` decision layers. This module bundles those inputs into ONE
explicit, frozen `Context` so a layer can read its inputs from a shared object
and `_core` reads as a thin ordering engine rather than a hand-threaded
parameter chain. See docs/reference/core-context-refactor-plan.md.

Context carries ONLY the per-EVALUATION inputs. The per-COMMAND cwd/cwd_det
values are DERIVED inside each layer (via `_effective_cwd_after` +
`_fold_wrapper_cwd`, keyed on the simple-command index) and are NOT stored here
— they vary per simple command, not per evaluation. `cwd_base` is the seed those
derivations start from and is constant across the whole evaluation.

Immutable by design: the front-end peel and the STEP1 config load each produce a
NEW Context (a fresh snapshot of the updated working set), never a mutation of an
existing one — so a Context always faithfully describes one evaluation stage.

Pure data + stdlib only: ZERO project identifiers, zero engine imports (no
import cycle back into _core). This is a lib module, mirroring the shell_lex /
constants / pathmatch / config / find_cmds / git_cmds / anchor siblings.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Context:
    """Immutable snapshot of the per-evaluation inputs threaded through the
    decision layers. Each field mirrors EXACTLY a positional parameter the layers
    take today — adopting the Context is a pure relocation of how those values
    travel, never a change to what they hold.

    ALL FOUR FIELDS ARE MANDATORY — there are NO defaults. This is the
    fail-CLOSED completeness guarantee: a construction that OMITS any field
    raises TypeError at build time (so the guard engine errors out and the
    surrounding hook denies conservatively), rather than silently producing a
    guard-DISABLING empty working set. This closes the INV-6 fail-OPEN hazard
    unique to the Context refactor: unlike a module split (which fails CLOSED on
    a missing import), a mis-built Context whose `groups` defaulted to `[]` would
    make the cross-segment guards `_p5_endpoint` (endpoint / raw-socket) and
    `_p6_prockill` (process-kill) ABSTAIN (return None) and flip a modeled BLOCK
    to a final ALLOW. Mandatory fields make that incomplete construction
    impossible. `cfg` keeps its `Optional[dict]` type — it may LEGITIMATELY be
    None for the pre-config STEP0 stage — but must still be passed EXPLICITLY.

      cwd_base    — base cwd seed (payload/process cwd); constant across the whole
                    evaluation. Per-command cwd/cwd_det are derived from it.
      simple_cmds — the pipeline-split simple commands (the current working set;
                    the front-end peel yields a new Context over the peeled forms).
      groups      — the pipeline GROUPS preserving `|` connectivity for the
                    cross-segment primitives (P5 endpoint, P6 prockill).
      cfg         — the loaded config dict, or None before the STEP1 config load
                    (STEP0 self-protection passes cfg=None EXPLICITLY by design —
                    it must not depend on the very file it protects).
    """

    cwd_base: Optional[str]
    simple_cmds: list
    groups: list
    cfg: Optional[dict]
