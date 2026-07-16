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

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Context:
    """Immutable snapshot of the per-evaluation inputs threaded through the
    decision layers. Each field mirrors EXACTLY a positional parameter the layers
    take today — adopting the Context is a pure relocation of how those values
    travel, never a change to what they hold.

      cwd_base    — base cwd seed (payload/process cwd); constant across the whole
                    evaluation. Per-command cwd/cwd_det are derived from it.
      simple_cmds — the pipeline-split simple commands (the current working set;
                    the front-end peel yields a new Context over the peeled forms).
      groups      — the pipeline GROUPS preserving `|` connectivity for the
                    cross-segment primitives (P5 endpoint, P6 prockill).
      cfg         — the loaded config dict, or None before the STEP1 config load
                    (STEP0 self-protection runs with cfg=None by design — it must
                    not depend on the very file it protects).
    """

    cwd_base: Optional[str] = None
    simple_cmds: list = field(default_factory=list)
    groups: list = field(default_factory=list)
    cfg: Optional[dict] = None
