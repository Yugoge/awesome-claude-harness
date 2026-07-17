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
    r"""Immutable snapshot of the per-evaluation inputs threaded through the
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
                    (STEP0 self-protection passes cfg=None EXPLICITLY by design —
                    it must not depend on the very file it protects).

    ALL FOUR FIELDS ARE MANDATORY — there are NO defaults, and the dataclass is
    frozen. Mandatory closes the INV-6 fail-OPEN hazard unique to this refactor:
    unlike a module split (which fails CLOSED on a missing import), a mis-built
    Context whose `groups` defaulted to `[]` would make the cross-segment guards
    `_p5_endpoint` and `_p6_prockill` ABSTAIN and flip a modeled BLOCK to a final
    ALLOW. Removing every default makes that incomplete construction raise
    TypeError. Frozen makes each Context an immutable snapshot of one evaluation
    stage: the front-end peel and the STEP1 config load each build a NEW Context,
    never mutate one. `cfg` stays `Optional[dict]` (legitimately None pre-config)
    but must still be passed EXPLICITLY.

    That TypeError is only the FIRST LINK of the fail-CLOSED chain, NOT the
    guarantee: an incomplete construction raises, but the raise becomes a DENY only
    where the surrounding hook's shell fallback covers the command's family — for
    P5/P6 across four tested invocation forms, NEVER family-wide; STEP0/P3/P4/P7
    stay fail-OPEN on a crashed engine. `_core.main()` wraps only the `evaluate()`
    call in a BaseException catch-all that converts an escaped exception into an
    INDETERMINATE verdict — see `_core.py` main() for its exact (non-blanket) scope.

    The single authoritative treatment of the shell fallback's coverage AND its
    limits — which invocation forms it covers, which lexical forms (quote-
    concatenation, backslash-escape, command substitution, variable/alias
    indirection, encoded execution) a regex CANNOT cover, and why it is best-effort
    defense-in-depth, not semantic equivalence with the engine's shlex lexer — lives
    in `hooks/pretool-bash-safety.sh::_runtime_guard_fail_closed` (header comment),
    mechanically asserted by `hooks/tests/test_fail_closed_drift.py`. The residual-
    gap record lives in `docs/reference/core-context-refactor-plan.md`. Do not
    restate either here.
    """

    cwd_base: Optional[str]
    simple_cmds: list
    groups: list
    cfg: Optional[dict]
