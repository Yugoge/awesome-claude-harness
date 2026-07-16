#!/usr/bin/env python3
"""Generic protected-runtime guard engine for pretool-bash-safety.sh.

This module contains ZERO project identifiers. Every project-specific name
(command basenames, workspace names, service units, file globs, monorepo roots)
lives ONLY in the machine-local data file whose path is the single hardcoded
constant below — a generic filesystem path, not a project name.

Decision contract:
  evaluate(command) -> ("BLOCK", primitive, reason) | ("ALLOW", None, None)

The hook invokes evaluate() BEFORE its /do, /allow, and sentinel bypass logic,
so a BLOCK here is unbypassable.

Ordering (mandatory):
  STEP 0  config self-protection  — runs BEFORE config load (hardcoded path patterns)
  STEP 1  load config; on missing/unreadable/malformed/wrong-schema -> indeterminate
          policy (fail-closed verb-family block)
  STEP 2  P1..P9 generic primitives, patterns sourced from the data file

Self-contained: does NOT depend on any context-stripped command form computed
later in the hook. It performs its own conservative tokenization.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from typing import Optional, Tuple

# Shell-command lexing primitives (_split_pipeline / _strip_quotes / _safe_shlex
# / redirect scanners) → shell_lex.py (phase-1). Re-imported here to keep _core's
# public surface unchanged. See docs/reference/monolith-split-plan.md.
#
# Dual-context import (INV-3) — REPRESENTATIVE CAUTION for every re-import block
# below: _core runs BOTH as the `lib.runtime_guard._core` submodule (relative
# import) AND as a direct script via the runtime_guard.py shim (`os.execv`),
# which has no parent package so a BARE relative import raises ImportError and
# the live hook fail-closes. The absolute-fallback form (sys.path[0] is this
# file's dir) resolves the sibling; keeping both preserves the standalone-script
# entrypoint pretool-bash-safety.sh depends on. Every block below repeats this
# same try/except idiom.
try:  # noqa: F401  — names re-exported for backward compatibility
    from .shell_lex import (
        _WRITE_REDIRECT_RE,
        _has_redirect_to,
        _is_redirect_amp,
        _safe_shlex,
        _split_pipeline,
        _strip_compound_delims,
        _strip_quotes,
        _write_redirect_targets,
    )
except ImportError:  # executed as a top-level script (no package context)
    from shell_lex import (  # type: ignore[no-redef]
        _WRITE_REDIRECT_RE,
        _has_redirect_to,
        _is_redirect_amp,
        _safe_shlex,
        _split_pipeline,
        _strip_compound_delims,
        _strip_quotes,
        _write_redirect_targets,
    )


MAX_COMMAND_CHARS = int(os.environ.get("CLAUDE_GUARD_MAX_CHARS", "262144"))

Verdict = Tuple[str, Optional[str], Optional[str]]
ALLOW: Verdict = ("ALLOW", None, None)


def _block(primitive: str, reason: str) -> Verdict:
    return ("BLOCK", primitive, reason)


# ── Generic verb / keyword / exec-front-end data tables → constants.py ───────
# The ~19 pure frozenset/dict vocabularies (PKG_MANAGERS, ENV_WRAPPERS,
# RUNTIMES, MUTATION_VERBS, KILL_VERBS, EXEC_FRONTEND_PROFILES, …) re-imported
# here (phase-2). The `_block`/`Verdict`/`ALLOW` decision anchors stay in _core
# by design. Dual-context import (INV-3, see phase-1 block above) --
# docs/reference/monolith-split-plan.md.
try:  # noqa: F401  — names re-exported for backward compatibility
    from .constants import (
        BUILD_TOOL_BASENAMES,
        DEP_BUILTINS,
        DEP_SHORTHAND_NPM,
        ENV_WRAPPERS,
        EXEC_FRONTEND_PROFILES,
        EXEC_RUNNER_TOKENS,
        KILL_VERBS,
        MUTATION_VERBS,
        PKG_MANAGERS,
        READ_INSPECT_EDIT_ALLOWLIST,
        RUNTIMES,
        SERVICE_VERBS,
        _EXEC_OPTS_WITH_ARG,
        _GIT_READONLY_SUBCMDS,
        _RUNTIME_OPTS_WITH_ARG,
        _RUNTIME_SUBCOMMANDS,
        _WRAPPER_LEADING_POSITIONAL,
        _WRAPPER_OPTS_WITH_ARG,
        _WRAPPER_POSITIONAL_OPTIONAL,
    )
except ImportError:  # executed as a top-level script (no package context)
    from constants import (  # type: ignore[no-redef]
        BUILD_TOOL_BASENAMES,
        DEP_BUILTINS,
        DEP_SHORTHAND_NPM,
        ENV_WRAPPERS,
        EXEC_FRONTEND_PROFILES,
        EXEC_RUNNER_TOKENS,
        KILL_VERBS,
        MUTATION_VERBS,
        PKG_MANAGERS,
        READ_INSPECT_EDIT_ALLOWLIST,
        RUNTIMES,
        SERVICE_VERBS,
        _EXEC_OPTS_WITH_ARG,
        _GIT_READONLY_SUBCMDS,
        _RUNTIME_OPTS_WITH_ARG,
        _RUNTIME_SUBCOMMANDS,
        _WRAPPER_LEADING_POSITIONAL,
        _WRAPPER_OPTS_WITH_ARG,
        _WRAPPER_POSITIONAL_OPTIONAL,
    )


# ── Path/glob matching primitives → pathmatch.py ────────────────────────────
# The path-normalization + segment-boundary glob-matching family
# (_normalize_path, _glob_to_segment_regex, _glob_parent, _path_matches_any,
# _path_under_any, the _any_token_* scanners, ...) re-imported here (phase-3);
# `_mutation_cand_hits` stays in _core (see its def below). Dual-context import
# (INV-3, see phase-1 block above) -- docs/reference/monolith-split-plan.md.
try:  # noqa: F401  — names re-exported for backward compatibility
    from .pathmatch import (
        _SHELL_GLOB_METACHARS,
        _any_token_path_matches,
        _any_token_under,
        _dir_equal_or_under,
        _expand_leading_home,
        _glob_literal_prefix,
        _glob_parent,
        _glob_to_segment_regex,
        _glob_token_selects_protected,
        _has_shell_glob,
        _normalize_path,
        _path_matches_any,
        _path_under_any,
    )
except ImportError:  # executed as a top-level script (no package context)
    from pathmatch import (  # type: ignore[no-redef]
        _SHELL_GLOB_METACHARS,
        _any_token_path_matches,
        _any_token_under,
        _dir_equal_or_under,
        _expand_leading_home,
        _glob_literal_prefix,
        _glob_parent,
        _glob_to_segment_regex,
        _glob_token_selects_protected,
        _has_shell_glob,
        _normalize_path,
        _path_matches_any,
        _path_under_any,
    )


# ── Config-loading cluster → config.py ────────────────────────────
# The config-file loader + STEP0 self-protection cluster (DATA_FILE_PATH,
# REQUIRED_KEYS, _load_config, _home_tilde_variant, _config_path_variants,
# _ANCESTOR_STOP_ROOTS, _config_ancestor_dirs, _config_or_ancestor_variants,
# _targets_config_file) re-imported here (phase-4). Dual-context import
# (INV-3, see phase-1 block above) -- docs/reference/monolith-split-plan.md.
#
# DATA_FILE_PATH reload caution (CANONICAL code-site): DATA_FILE_PATH is read
# from the env at config's MODULE-IMPORT time. The package __init__ reloads _core
# (NOT its siblings), so a plain `from .config import DATA_FILE_PATH` on an _core
# reload would re-bind the STALE cached value. The `_importlib.reload(_config)`
# below re-runs config's module-level env read on every _core (re)load, keeping
# it an import-time (NOT lazy) read. See docs/reference/monolith-split-plan.md.
import importlib as _importlib
try:
    from . import config as _config
except ImportError:  # executed as a top-level script (no package context)
    import config as _config  # type: ignore[no-redef]
_importlib.reload(_config)  # re-read DATA_FILE_PATH from the env on each _core load
try:  # noqa: F401  — names re-exported for backward compatibility
    from .config import (
        DATA_FILE_PATH,
        REQUIRED_KEYS,
        _ANCESTOR_STOP_ROOTS,
        _config_ancestor_dirs,
        _config_or_ancestor_variants,
        _config_path_variants,
        _home_tilde_variant,
        _load_config,
        _targets_config_file,
    )
except ImportError:  # executed as a top-level script (no package context)
    from config import (  # type: ignore[no-redef]
        DATA_FILE_PATH,
        REQUIRED_KEYS,
        _ANCESTOR_STOP_ROOTS,
        _config_ancestor_dirs,
        _config_or_ancestor_variants,
        _config_path_variants,
        _home_tilde_variant,
        _load_config,
        _targets_config_file,
    )


# ── find/fd destructive-command parsing leaves → find_cmds.py ────────────
# The pure find/fd argv PARSERS (path-operand / fd search-dir collection, PATH/
# NAME predicate-value extraction, and the protected-basename matcher
# `_name_value_matches_protected`) plus their generic option/predicate tables
# re-imported here (phase-5); the forward-referencing orchestrators
# (`_find_destructive_target_hits` / `_find_filter_exonerates_reverse`) stay in
# _core. Dual-context import (INV-3, see phase-1 block above) --
# docs/reference/monolith-split-plan.md.
try:  # noqa: F401  — names re-exported for backward compatibility
    from .find_cmds import (
        _FD_OPTS_WITH_ARG,
        _FIND_CASE_INSENSITIVE_PREDS,
        _FIND_GLOBAL_ARG_OPTS,
        _FIND_GLOBAL_NOARG_OPTS,
        _FIND_NAME_PREDICATES,
        _FIND_PATH_PREDICATES,
        _FIND_PREPATH_ARG_OPTS,
        _fd_positional_roots,
        _find_path_operands,
        _find_predicate_values,
        _glob_basenames,
        _name_value_matches_protected,
    )
except ImportError:  # executed as a top-level script (no package context)
    from find_cmds import (  # type: ignore[no-redef]
        _FD_OPTS_WITH_ARG,
        _FIND_CASE_INSENSITIVE_PREDS,
        _FIND_GLOBAL_ARG_OPTS,
        _FIND_GLOBAL_NOARG_OPTS,
        _FIND_NAME_PREDICATES,
        _FIND_PATH_PREDICATES,
        _FIND_PREPATH_ARG_OPTS,
        _fd_positional_roots,
        _find_path_operands,
        _find_predicate_values,
        _glob_basenames,
        _name_value_matches_protected,
    )


# ── git destructive-subcommand parsing leaves → git_cmds.py ─────────────
# The pure git argv PARSERS (subcommand location, `-C` chdir folding, pathspec-
# magic stripping, destructive-pathspec collection, destructive-mode predicate)
# plus their generic verb/option tables re-imported here (phase-5); the STAYING
# `_git_inspection_head` and the forward-referencing `_git_destructive_pathspec_hits`
# remain in _core. Dual-context import (INV-3, see phase-1 block above) --
# docs/reference/monolith-split-plan.md.
try:  # noqa: F401  — names re-exported for backward compatibility
    from .git_cmds import (
        _GIT_DESTRUCTIVE_SUBCMDS,
        _GIT_GLOBAL_OPTS_WITH_ARG,
        _git_destructive_pathspecs,
        _git_effective_cwd,
        _git_is_destructive_invocation,
        _git_subcommand_index,
        _strip_git_pathspec_magic,
    )
except ImportError:  # executed as a top-level script (no package context)
    from git_cmds import (  # type: ignore[no-redef]
        _GIT_DESTRUCTIVE_SUBCMDS,
        _GIT_GLOBAL_OPTS_WITH_ARG,
        _git_destructive_pathspecs,
        _git_effective_cwd,
        _git_is_destructive_invocation,
        _git_subcommand_index,
        _strip_git_pathspec_magic,
    )


# ── P0 anchor helper predicates (leaf subset) → anchor.py ────────────────────
# The cleanly-extractable P0-anchor helper predicates -- the exec-token scanner,
# the launch-position and fused-option-value primitives, the head-agnostic
# service-control hit-detector, and the non-protected-workspace-selector
# exemption -- re-imported here (phase-6). The P0 decision ENGINE `_p0_anchor`
# and every forward-referencing anchor helper stay in _core. Dual-context import
# (INV-3, see phase-1 block above) -- docs/reference/monolith-split-plan.md.
try:  # noqa: F401  — names re-exported for backward compatibility
    from .anchor import (
        _ANCHOR_LAUNCH_FOLLOW,
        _LAUNCH_SUBCMDS,
        _RECURSIVE_WS_FLAGS,
        _SERVICE_MANAGER_PROGRAMS,
        _anchor_exec_tokens,
        _anchor_in_launch_position,
        _anchor_nonprotected_workspace_selector,
        _anchor_service_hits_protected,
        _fused_option_values,
    )
except ImportError:  # executed as a top-level script (no package context)
    from anchor import (  # type: ignore[no-redef]
        _ANCHOR_LAUNCH_FOLLOW,
        _LAUNCH_SUBCMDS,
        _RECURSIVE_WS_FLAGS,
        _SERVICE_MANAGER_PROGRAMS,
        _anchor_exec_tokens,
        _anchor_in_launch_position,
        _anchor_nonprotected_workspace_selector,
        _anchor_service_hits_protected,
        _fused_option_values,
    )


# ── Per-evaluation Context object → context.py ───────────────────────────────
# The frozen dataclass bundling the per-evaluation inputs (cwd_base / simple_cmds
# / groups / cfg) the decision layers thread positionally. Re-imported here
# (dual-context, INV-3, see phase-1 block above) so _core's public surface is a
# superset — no existing name removed. Internal engine plumbing: `evaluate` /
# `main` signatures are unchanged. See docs/reference/core-context-refactor-plan.md.
try:  # noqa: F401  — Context re-exported for engine plumbing
    from .context import Context
except ImportError:  # executed as a top-level script (no package context)
    from context import Context  # type: ignore[no-redef]


# ── Tokenization primitives → shell_lex.py (re-imported at top of file) ──────
# ── Path/glob primitives → pathmatch.py (re-imported just above) ─────────────

# `_mutation_cand_hits` stays in _core: it forward-references
# `_destructive_root_contains_protected` (defined later in the decision engine),
# so relocating it into pathmatch would create an import cycle. Its callees
# (`_path_matches_any`, `_has_shell_glob`, `_glob_parent`, `_strip_quotes`) are
# all re-imported above, so every reference still resolves.
def _mutation_cand_hits(cand: str, globs: list, cfg: Optional[dict],
                        cwd: Optional[str] = None, cwd_det: bool = False) -> bool:
    """Unified mutation-target → protected match: forward (`_path_matches_any`: the
    target IS / is UNDER a protected glob) PLUS, for a shell-GLOB target token, a
    cfg-aware REVERSE check (the glob's parent CONTAINS a concrete protected dir, so
    `rm -rf <repo>/packages/*` selecting the protected package BLOCKS). Without cfg
    the reverse check is skipped (relative `**` protected globs have no concrete
    location to resolve). A non-glob target keeps the existing forward-only
    semantics, so literal-path matching is unchanged."""
    if _path_matches_any(cand, globs):
        return True
    if cfg is not None and _has_shell_glob(_strip_quotes(cand)):
        gp = _glob_parent(cand)
        if gp is not None and _destructive_root_contains_protected(gp, globs, cfg, cwd, cwd_det):
            return True
    return False


# Build-tool option flags whose VALUE is a path the build reads/writes. Only
# these path-valued flags have their RHS inspected for protected paths — a
# generic key/value flag (`--define:X=...`, `--mode`, `--env.X=...`) carries an
# arbitrary value, not a build target, and must NOT trigger a path match.
_PATH_VALUED_BUILD_FLAGS = frozenset({
    "--project", "-p", "--tsconfig", "--config", "-c", "--outfile", "-o",
    "--outdir", "--out-dir", "--out", "--build", "-b", "--rootdir", "--rootDir",
    "--declarationDir", "--tsBuildInfoFile",
})


def _flagvalue_path_candidates(tokens: list) -> list:
    """Yield path RHS values of a `--flag=value` option ONLY when the flag is a
    known path-valued build flag (so `--project=<path>`, `--outfile=<path>`,
    `--tsconfig=<path>` are inspected, but `--define:X=<anything>` is not)."""
    out = []
    for tok in tokens:
        st = _strip_quotes(tok)
        if st.startswith("-") and "=" in st:
            flag, val = st.split("=", 1)
            if val and flag in _PATH_VALUED_BUILD_FLAGS:
                out.append(val)
    return out


def _resolve_rel(val: str, cwd: Optional[str], cwd_det: bool) -> list:
    """Return path candidates for a token: itself, plus its resolution against a
    determinate effective cwd (so a relative `../<pkg>/tsconfig.json` from a
    sibling package resolves to the protected build path)."""
    cands = [val]
    st = _strip_quotes(val)
    if cwd and cwd_det and st and not os.path.isabs(st):
        cands.append(os.path.normpath(os.path.join(cwd, st)))
    return cands


def _path_is_protected_build(path: str, cfg: dict) -> bool:
    """True if `path` is under a protected build path. A RELATIVE build-path glob
    (`**/packages/<pkg>`) is suffix-matching and would also match an UNRELATED
    project's identically-named dir, so it is honored only when the resolved path
    is under a protected monorepo root. An ABSOLUTE glob is honored as-is."""
    bpaths = cfg.get("protected_build_paths", [])
    abs_globs = [g for g in bpaths if g.startswith("/")]
    rel_globs = [g for g in bpaths if not g.startswith("/")]
    if abs_globs and (_path_under_any(path, abs_globs) or _path_matches_any(path, abs_globs)):
        return True
    if rel_globs and (_path_under_any(path, rel_globs) or _path_matches_any(path, rel_globs)):
        # A relative-glob match on an ABSOLUTE path could be an unrelated
        # project's same-named dir → require it under a protected root. A
        # RELATIVE path (cwd unknown / repo-relative) cannot be disambiguated →
        # fail CLOSED (treat as protected); only an ABSOLUTE path OUTSIDE every
        # protected root is exonerated.
        if os.path.isabs(os.path.normpath(path)):
            return _dir_under_any_root(path, cfg)
        return True
    return False


def _any_token_under_incl_flagvalue(tokens: list, cfg: dict,
                                    cwd: Optional[str] = None, cwd_det: bool = False) -> bool:
    """Match any bare path token OR known path-valued `--flag=value` RHS against
    the (root-qualified) protected build paths, resolving relative paths against
    the effective cwd (covers `tsc -p ../<pkg>/tsconfig.json` from a sibling
    package) while NOT matching an unrelated project's same-named dir."""
    for tok in tokens:
        st = _strip_quotes(tok)
        if not st or st.startswith("-"):
            continue
        for cand in _resolve_rel(st, cwd, cwd_det):
            if _path_is_protected_build(cand, cfg):
                return True
    for val in _flagvalue_path_candidates(tokens):
        for cand in _resolve_rel(val, cwd, cwd_det):
            if _path_is_protected_build(cand, cfg):
                return True
    return False


def _explicit_nonprotected_build_target(tokens: list, cfg: dict,
                                        cwd: Optional[str], cwd_det: bool) -> bool:
    """True if a path-valued build flag points DETERMINATELY at a target OUTSIDE
    every protected build path (so a build-mode fallback must not over-block a
    `tsc -w -p packages/<non-protected>/tsconfig.json` at the monorepo root)."""
    vals = list(_flagvalue_path_candidates(tokens))
    # also the space-separated `-p <path>` / `--project <path>` form
    i = 0
    while i < len(tokens):
        t = _strip_quotes(tokens[i])
        if t in _PATH_VALUED_BUILD_FLAGS and i + 1 < len(tokens):
            nv = _strip_quotes(tokens[i + 1])
            if not nv.startswith("-"):
                vals.append(nv)
            i += 2
            continue
        i += 1
    if not vals:
        return False
    for v in vals:
        # if ANY explicit target resolves under a protected path -> not exempt
        for cand in _resolve_rel(v, cwd, cwd_det):
            if _path_is_protected_build(cand, cfg):
                return False
        # an unresolvable relative target -> cannot prove non-protected
        if not os.path.isabs(_strip_quotes(v)) and not (cwd and cwd_det):
            return False
    return True


# ── Command-word position scanning ───────────────────────────────────────────

def _command_words(tokens: list) -> list:
    """Return the effective command-word of a simple command after consuming
    VAR=val env-prefixes and wrapper commands.
    Returns a list with one tuple (head_index, head_basename, args_after_head)
    where args_after_head EXCLUDES the head token itself.
    """
    i = 0
    n = len(tokens)
    # Skip leading shell keywords that introduce a command (`do`, `then`,
    # `else`, `;`-separated loop bodies) so the real command word in a loop /
    # conditional body is reached (`do kill $pid` → head 'kill').
    while i < n and _strip_quotes(tokens[i]) in ("do", "then", "else", "{", "!"):
        i += 1
    # Skip VAR=val env assignments.
    while i < n and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[i]):
        i += 1
    # Skip wrapper commands (env/sudo/command/nohup/timeout/setsid/...), each
    # with its own operand schema, until the real command word is reached.
    while i < n:
        base = os.path.basename(_strip_quotes(tokens[i]))
        if base not in ENV_WRAPPERS:
            break
        opts_with_arg = _WRAPPER_OPTS_WITH_ARG.get(base, frozenset())
        i += 1
        value_opt_seen = False
        # consume this wrapper's options (and their operands) and env VAR=val.
        while i < n:
            t = tokens[i]
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
                i += 1
                continue
            if t == "--":
                i += 1
                break
            if t in opts_with_arg:
                value_opt_seen = True
                i += 2
                continue
            if "=" in t and t.startswith("-"):
                # --opt=value form: single token
                i += 1
                continue
            if t.startswith("-"):
                i += 1
                continue
            break
        # consume a single leading positional operand for wrappers that take one
        # (timeout DURATION, chrt PRIORITY, taskset MASK, setarch ARCH). For the
        # optional-positional wrappers (chrt/taskset) skip the consumption when a
        # value option already supplied the operand, so `taskset -c 0 <cmd>`
        # still exposes <cmd> as the command word.
        if base in _WRAPPER_LEADING_POSITIONAL and i < n:
            if not (base in _WRAPPER_POSITIONAL_OPTIONAL and value_opt_seen):
                i += 1
    if i >= n:
        return []
    return [(i, os.path.basename(_strip_quotes(tokens[i])), tokens[i + 1:])]


# Wrapper options that set the working directory (chdir) for the wrapped command.
# env -C/--chdir, sudo -D/--chdir, doas -C, systemd-run --working-directory.
_WRAPPER_CWD_OPTS = frozenset({"-C", "--chdir", "-D", "--working-directory"})
# Short cwd opts that may FUSE their value (env -C<dir>, sudo -D<dir>).
_WRAPPER_CWD_SHORT_FUSABLE = ("-C", "-D")


def _wrapper_cwd(tokens: list):
    """Extract a chdir directory set by a leading env/sudo/doas wrapper.

    Returns (dir|None, determinate). `env -C <dir>`, `env --chdir <dir>`,
    `sudo -D <dir>`, `sudo --chdir <dir>`, `doas -C <dir>` all change the
    working directory of the wrapped command. A dynamic operand ($/`/glob)
    yields (None, False) so callers fail closed for protected verb families.
    """
    i = 0
    n = len(tokens)
    while i < n and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[i]):
        i += 1
    found = None
    determinate = True
    while i < n:
        base = os.path.basename(_strip_quotes(tokens[i]))
        if base not in ENV_WRAPPERS:
            break
        i += 1
        value_opt_seen = False
        while i < n:
            t = tokens[i]
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):
                i += 1
                continue
            if t == "--":
                i += 1
                break
            if t in _WRAPPER_CWD_OPTS and i + 1 < n:
                val = _expand_leading_home(_strip_quotes(tokens[i + 1]))
                if any(ch in val for ch in ("$", "`", "*", "?")):
                    determinate = False
                else:
                    found = val
                i += 2
                continue
            _fused = None
            for opt in _WRAPPER_CWD_OPTS:
                if t.startswith(opt + "="):
                    _fused = t.split("=", 1)[1]
                    break
            if _fused is None:
                # short fused form: env -C<dir> / sudo -D<dir> (no separator)
                for opt in _WRAPPER_CWD_SHORT_FUSABLE:
                    if t.startswith(opt) and len(t) > len(opt) and not t[len(opt)] == "=":
                        _fused = t[len(opt):]
                        break
            if _fused is not None:
                val = _expand_leading_home(_strip_quotes(_fused))
                if any(ch in val for ch in ("$", "`", "*", "?")):
                    determinate = False
                else:
                    found = val
                i += 1
                continue
            opts_with_arg = _WRAPPER_OPTS_WITH_ARG.get(base, frozenset())
            if t in opts_with_arg:
                value_opt_seen = True
                i += 2
                continue
            if "=" in t and t.startswith("-"):
                i += 1
                continue
            if t.startswith("-"):
                i += 1
                continue
            break
        if base in _WRAPPER_LEADING_POSITIONAL and i < n:
            if not (base in _WRAPPER_POSITIONAL_OPTIONAL and value_opt_seen):
                i += 1
    return (found, determinate)


def _fold_wrapper_cwd(cwd: Optional[str], cwd_det: bool, tokens: list):
    """Fold a leading wrapper chdir (env -C/sudo --chdir) into the effective cwd."""
    wdir, wdet = _wrapper_cwd(tokens)
    if not wdet:
        return (cwd, False)
    if wdir is None:
        return (cwd, cwd_det)
    if os.path.isabs(wdir):
        return (os.path.normpath(wdir), True)
    if cwd:
        return (os.path.normpath(os.path.join(cwd, wdir)), cwd_det)
    return (os.path.normpath(wdir), False)


# ── command-substitution extraction ──────────────────────────────────────────

def _command_substitutions(text: str) -> list:
    """Return the inner text of every $(...) command substitution (top level and
    nested, flattened) and every `...` backtick substitution found in `text`.

    Used so a kill executor whose argument list is computed by an embedded
    pipeline — e.g. `kill $(ps aux | grep <ident> | awk '{print $2}')` — can be
    inspected for a protected identifier inside the substitution.
    """
    out = []
    n = len(text)
    i = 0
    while i < n:
        # $(...) command substitution and <(...) / >(...) process substitution
        if (text[i] in ("$", "<", ">")) and i + 1 < n and text[i + 1] == "(":
            depth = 1
            j = i + 2
            start = j
            while j < n and depth > 0:
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            inner = text[start:j]
            out.append(inner)
            # recurse for nested $(...) inside this one
            out.extend(_command_substitutions(inner))
            i = j + 1
            continue
        if text[i] == "`":
            j = i + 1
            while j < n and text[j] != "`":
                j += 1
            out.append(text[i + 1:j])
            i = j + 1
            continue
        i += 1
    return out


# ── pipeline-group splitting (preserve | connectivity) ───────────────────────

def _pipeline_groups(command: str) -> list:
    """Split a command into pipeline GROUPS.

    Segments joined by `|` / `|&` belong to the SAME group (data flows between
    them); `;`, `&&`, `||`, `&`, and newlines separate groups. Each group is a
    list of its raw simple-command strings, in order. This preserves the
    upstream→downstream connectivity that cross-segment primitives (P5 endpoint,
    P6 prockill) need, which the flat `_split_pipeline` discards.
    """
    groups = []
    cur = []
    buf = []
    i = 0
    n = len(command)
    quote = None
    loop_depth = 0  # inside a do..done loop body fed by an upstream pipe
    subst_depth = 0
    backtick = False

    def flush_simple():
        nonlocal loop_depth
        s = "".join(buf).strip()
        if s:
            cur.append(s)
            # track loop nesting so `;`/newline inside a do..done body do NOT
            # break the pipe connectivity (`pgrep … | while read x; do kill x;
            # done` must stay ONE group for P6).
            words = s.split()
            for w in words:
                # increment ONLY on a loop OPENER (while/for/until); `do` is the
                # body marker of the SAME loop, not a new nesting level, so
                # counting it double-closes late and over-connects a later
                # top-level command (e.g. a trailing `; kill 123`) to the group.
                if w in ("while", "for", "until"):
                    loop_depth += 1
                elif w == "done":
                    loop_depth = max(0, loop_depth - 1)

    def flush_group():
        flush_simple()
        if cur:
            groups.append(list(cur))

    while i < n:
        c = command[i]
        if quote == "'":
            buf.append(c)
            if c == "'":
                quote = None
            i += 1
            continue
        if quote == '"':
            if c == "\\" and i + 1 < n and command[i + 1] in ('"', "\\", "$", "`", "\n"):
                buf.append(c); buf.append(command[i + 1]); i += 2; continue
            buf.append(c)
            if c == '"':
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            buf.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            buf.append(c); buf.append(command[i + 1]); i += 2; continue
        # command-substitution: keep `$(...)`/`` `...` `` intact within ONE
        # simple command so a kill-substitution's pipeline isn't split.
        if c == "`":
            backtick = not backtick
            buf.append(c); i += 1; continue
        if command[i:i + 2] in ("$(", "<(", ">("):
            subst_depth += 1
            buf.append(command[i:i + 2]); i += 2; continue
        if c == ")" and subst_depth > 0:
            subst_depth -= 1
            buf.append(c); i += 1; continue
        if subst_depth > 0 or backtick:
            buf.append(c); i += 1; continue
        # fd-redirection `&` is not a group separator.
        if c == "&" and _is_redirect_amp(command, i):
            buf.append(c); i += 1; continue
        two = command[i:i + 2]
        if two in ("&&", "||", "|&"):
            if two == "|&":
                # |& pipes stdout+stderr: stays within the SAME group
                flush_simple(); buf = []; i += 2; continue
            if loop_depth > 0:
                # &&/|| inside a loop body do not break pipe connectivity
                flush_simple(); buf = []; i += 2; continue
            flush_group(); cur = []; buf = []; i += 2; continue
        if c == "|":
            flush_simple(); buf = []; i += 1; continue
        if c in (";", "\n", "&"):
            flush_simple()
            if loop_depth <= 0:
                # outside a loop body: a real group separator
                if cur:
                    groups.append(list(cur)); cur = []
            buf = []; i += 1; continue
        buf.append(c)
        i += 1
    flush_group()
    return groups


# ── effective cwd tracking across a pipeline ──────────────────────────────────

def _cd_target(args: list) -> Optional[str]:
    """First real directory operand of a cd/pushd, skipping options.

    `cd [-L|-P|-e|-@] [--] DIR`. Returns None when no directory operand is
    present (e.g. bare `cd`, or `pushd +N`/`-N` stack rotation which is not a
    path change we model). The `--` terminator forces the next token as the dir.
    """
    i = 0
    n = len(args)
    while i < n:
        t = _strip_quotes(args[i])
        if t == "--":
            return _strip_quotes(args[i + 1]) if i + 1 < n else None
        if t.startswith("-") and re.match(r"^-[LPe@]+$", t):
            i += 1
            continue
        if t.startswith("-"):
            # pushd +N / -N stack rotation or an unknown flag: not a dir change
            return None
        return t
    return None


def _effective_cwd_after(simple_cmds: list, upto_index: int, cwd_base: Optional[str] = None):
    """Compute effective cwd from a known base cwd plus leading cd/pushd in the
    SAME chain.

    `cwd_base` seeds the resolution from the payload's reported cwd (or the
    process cwd). If a cd target is dynamic/unresolvable, determinate=False
    (caller fails closed). With a known base, a relative cd is resolvable.
    """
    cwd = os.path.normpath(cwd_base) if cwd_base else None
    determinate = True
    for j in range(upto_index):
        toks = _safe_shlex(simple_cmds[j])
        if not toks:
            continue
        base = os.path.basename(_strip_quotes(toks[0]))
        if base in ("cd", "pushd"):
            target = _cd_target(toks[1:])
            if target is None:
                continue
            # expand a LEADING $HOME/~ first so `cd "$HOME/.config/<app>"` resolves
            # determinately instead of failing the dynamic-token check below.
            target = _expand_leading_home(target)
            if any(ch in target for ch in ("$", "`", "*", "?")):
                determinate = False
                continue
            if os.path.isabs(target):
                cwd = os.path.normpath(target)
            elif cwd:
                cwd = os.path.normpath(os.path.join(cwd, target))
            else:
                # relative cd with unknown base cwd -> best-effort, indeterminate
                cwd = os.path.normpath(target)
                determinate = False
    return cwd, determinate


CONFIG_MUTATION_HEADS = frozenset({
    "cp", "mv", "rm", "tee", "truncate", "dd", "install", "ln", "chmod",
    "chown", "chgrp", "rename", "rsync", "shred", "unlink",
})


# Config-self-protection mutation-verb basenames recognized in EXECUTABLE
# position behind ANY wrapper. The SAME filesystem-mutation family the W6/W7
# anchors use (`_ANCHOR_MUTATION_HEADS`, defined later in the file) plus the
# metadata-mutation verbs `chmod`/`chown` that neuter the data file's
# permissions/ownership. Listed here directly (not derived from the later global)
# so STEP0 has no load-order dependency on the anchor section. All generic POSIX
# tools — NOT project names.
_STEP0_MUTATION_HEADS = frozenset({
    "cp", "mv", "rsync", "install", "touch", "truncate", "dd", "tee",
    "unzip", "rename", "rm", "unlink", "shred", "rmdir", "sed", "perl", "ln",
    "tar", "chmod", "chown", "chgrp",
})


def _is_inplace_editor_args(head: str, args: list) -> bool:
    """True if a sed/perl invocation edits its file IN PLACE (mutating it).
    Covers GNU sed `-i`/`-i.bak`/`--in-place[=SUFFIX]`/clustered short opts that
    contain `i` (`-Ei`, `-ri`, `-nei`), and Perl `-i`/`-iSUFFIX`/clustered
    `-pi`/`-0pi`/`-Tpi`. A plain `sed s/a/b/ file` (stream to stdout, no -i) is
    NOT in-place and must not match (it reads, does not mutate)."""
    if head not in ("sed", "perl"):
        return False
    for a in args:
        if a == "--in-place" or a.startswith("--in-place"):
            return True
        if a == "-i" or a.startswith("-i"):
            return True
        # clustered short-option bundle containing the `i` flag (`-Ei`, `-ri`,
        # `-pi`, `-0pi`). A single-dash token whose option letters include `i`,
        # but NOT a long `--xxx` option.
        if a.startswith("-") and not a.startswith("--") and "i" in a[1:]:
            return True
    return False


# Value-taking options PER coreutils/rsync verb whose ARGUMENT is the NEXT token
# (separated form) — that argument is NOT an operand and must be consumed so it
# neither pollutes the operand list NOR is mistaken for the destination. Fused
# `--opt=VAL` / `-oVAL` forms carry their value in the same token (already handled
# by the bareword `startswith("-")` filter), so only the SEPARATED forms need the
# next-token skip. This is the GENERAL fix for the flag-value-collision class: a
# trailing `cp SRC <protected-dest> -S .bak` must not let `.bak` become the dest.
_VALUE_OPTS = {
    "cp": {"-S", "--suffix", "-t", "--target-directory", "--preserve",
           "-Z", "--context", "--sparse", "--reflink"},
    "mv": {"-S", "--suffix", "-t", "--target-directory"},
    "rename": {"-S", "--suffix", "-t", "--target-directory"},
    "install": {"-S", "--suffix", "-t", "--target-directory", "-m", "--mode",
                "-o", "--owner", "-g", "--group", "-Z", "--context",
                "--strip-program", "-D"},
    "ln": {"-S", "--suffix", "-t", "--target-directory"},
    "rsync": {"-e", "--rsh", "--files-from", "--include", "--exclude",
              "--include-from", "--exclude-from", "--filter", "--log-file",
              "--password-file", "--backup-dir", "--temp-dir", "--partial-dir",
              "--compare-dest", "--copy-dest", "--link-dest", "--rsync-path",
              "--chmod", "--out-format", "--bwlimit", "--timeout",
              "--modify-window", "--max-size", "--min-size", "--block-size",
              "--sockopts", "--protocol", "--checksum-choice", "--info", "--debug"},
}


def _operands_and_tdir(head: str, args: list):
    """Return (operands, tdir) splitting `args` (the tokens AFTER the verb) into
    positional OPERANDS vs OPTIONS, fail-safe against the whole flag-value-collision
    class. Handles:
      • `--` end-of-options: EVERY token after `--` is an operand even if it begins
        with `-` (so `cp -- -t <protected>` keeps `<protected>` as an operand, and
        a post-`--` `-t` is NOT a target-directory).
      • verb-aware target-directory `-t DIR` / `--target-directory[=DIR]` and the
        clustered/attached short forms (`-vt DIR`, `-Dt DIR`, `-tDIR`) for the only
        verbs that define them: {cp, mv, install, ln}. The consumed DIR is removed
        from operands; `tdir` is returned so the caller synthesizes DIR/basename(src).
      • separated value-options (`-S SUF`, install `-m MODE`, rsync `-e CMD`, …):
        the option's ARGUMENT is consumed so it is neither an operand nor mistaken
        for the destination.
    Unknown single-dash tokens are treated as no-arg flags (dropped) — the fail-safe
    direction: a flag we do not model never STEALS an operand slot, so a real
    protected operand is never dropped because of an unmodeled flag."""
    tdir_verbs = ("cp", "mv", "install", "rename", "ln")
    val_opts = _VALUE_OPTS.get(head, set())
    operands = []
    tdir = None
    after_ddash = False
    i = 0
    n = len(args)
    while i < n:
        a = args[i]
        if after_ddash:
            operands.append(a)
            i += 1
            continue
        if a == "--":
            after_ddash = True
            i += 1
            continue
        if not a.startswith("-") or a == "-":
            operands.append(a)
            i += 1
            continue
        # a is an option token.
        # fused long form --opt=VAL (value carried in token) — consume, no operand.
        if a.startswith("--") and "=" in a:
            if a.split("=", 1)[0] in ("--target-directory",) and head in tdir_verbs:
                tdir = a.split("=", 1)[1]
            i += 1
            continue
        # exact long/short option taking a SEPARATED value.
        if a in val_opts and i + 1 < n:
            if a in ("-t", "--target-directory") and head in tdir_verbs:
                tdir = args[i + 1]
            i += 2
            continue
        # clustered/attached SHORT option bundle (single dash, not `--…`).
        if not a.startswith("--"):
            letters = a[1:]
            if head in tdir_verbs and "t" in letters:
                pos = letters.index("t")
                rest = letters[pos + 1:]
                if rest:
                    # `-tDIR` / `-vtDIR`: DIR is attached in the same token.
                    tdir = rest
                    i += 1
                    continue
                # `-vt DIR`: trailing `t`, DIR is the next token.
                if i + 1 < n:
                    tdir = args[i + 1]
                    i += 2
                    continue
            # an attached short value-option whose value is fused (e.g. `-S.bak`,
            # install `-m644`): the value rides in this token → consume, no skip.
            # A bare cluster with no recognized value letter is a no-arg flag bundle.
            i += 1
            continue
        # unknown exact long option: assume no-arg (fail-safe drop).
        i += 1
        continue
    return operands, tdir


def _mutation_targets_for_verb(head: str, args: list) -> list:
    """THE SINGLE position-COMPLETE mutation-target extractor for a mutation verb's
    OWN argv (the tokens AFTER the verb). This is the ONE shared helper used by
    STEP0 (config self-protection), W6 (hot-watched bundle), W7 (state file), and
    the head-keyed P3/P4/P7 paths via `_mutation_targets` — so the three protected-
    file families (config / bundle / statefile) can never DRIFT in which positions
    count as a mutation.

    A protected file counts as MUTATED when it appears in ANY position that
    writes / overwrites / removes / replaces / MOVES it, for every relevant verb:

      • cp / install DEST (and `-t DIR` → DIR/basename(src)): written. The SRC of a
        plain `cp` is a READ, NOT a mutation (cp keeps the source) → NOT a target.
      • mv / rename SRC and DEST: mv WRITES the dest AND REMOVES the source in place,
        so BOTH source(s) and dest are targets (moving the watched bundle / statefile
        / config away deletes it from its watched path). `-t DIR` → DIR/basename(src)
        plus the sources.
      • rsync DEST (file or DIR/ → DIR/basename(src)): written. The SRC is a target
        ONLY when `--remove-source-files` is given (then rsync MOVES = removes the
        source); a plain rsync COPIES and the source is a READ → NOT a target.
      • rm / unlink / shred / truncate / touch / dd(of=) / tee / unzip: the operand
        file(s) (or `of=` for dd) are written / removed / overwritten.
      • sed -i / perl -pi (in-place edit) operand file(s): overwritten in place.
      • ln / ln -sf DEST (and `-t DIR`): symlinked-over.
      • chmod / chown FILE… (mode/owner change; `--reference=REF` skips the ref
        operand): metadata-mutated.
      • tar -x [-C DIR] members: extracted/written.

    Read-only / inspection appearances of a protected file (a cp/rsync SOURCE that
    is copied not moved, a token merely read) yield NO target so they still ALLOW —
    the over-block boundary the threat model requires. The synthesized `-t DIR`
    candidates are DIR/basename so a write via `-t <dir>` matches the exact protected
    path (and a write to an UNRELATED file in that dir does not). The redirect-target
    form (`> path`) is handled by the callers, not here."""
    # Split args into positional OPERANDS vs OPTIONS, fail-safe against the whole
    # flag-value-collision class (verb-aware `-t`, clustered/attached short `-t`,
    # `--` end-of-options, and SEPARATED value-options whose argument must not be
    # mistaken for the destination). `tdir` is the target-directory ONLY for the
    # coreutils that define it ({cp, mv, install, ln}); for every other verb it is
    # None and the verb's own last-operand-is-dest logic runs unchanged.
    barewords, tdir = _operands_and_tdir(head, args)
    if head in ("cp", "install"):
        # `install -d DIR…` / `install --directory DIR…` (incl. clustered `-Dd`)
        # CREATES every named directory (there is NO source operand). So EVERY
        # operand is a target — creating/`mkdir -p`-ing a protected ancestor/config
        # dir (or touching a protected dir) is a mutation. The plain cp/install copy
        # logic below would only flag the last operand (dest), dropping a protected
        # dir that appears earlier in a multi-dir `install -d A B <protecteddir>`.
        if head == "install" and any(
            a == "-d" or a == "--directory"
            or (a.startswith("-") and not a.startswith("--") and "d" in a[1:])
            for a in args
        ):
            return list(barewords)
        if tdir is not None:
            # every source maps to tdir/basename(source)
            srcs = [b for b in barewords]
            out = [os.path.join(_strip_quotes(tdir), os.path.basename(_strip_quotes(s))) for s in srcs]
            # a shell-GLOB source selecting a protected dir's contents is the SAME
            # exfil/clobber op the non `-t` branch blocks (basename(<dir>/*) == '*'
            # would otherwise drop the protected-ness) — add glob sources as targets so
            # `cp -t /tmp/x <protecteddir>/*` / `install -t /tmp/x <protecteddir>/*`
            # BLOCK, while a literal protected source stays a read (ALLOW).
            out += [s for s in srcs if _has_shell_glob(_strip_quotes(s))]
            return out
        # `cp SRC… DEST`: the DEST (last operand) is written. SRC is read — EXCEPT a
        # shell-GLOB source (`cp <dir>/* DEST`) over-blocked like the cp glob source.
        # If DEST ends with '/' (an explicit destination DIRECTORY) the written file
        # is DEST/basename(SRC) for each source, so emit those too (a protected exact
        # file inside that dir must not be dropped).
        out = barewords[-1:] if barewords else []
        srcs = barewords[:-1]
        if barewords:
            dest = _strip_quotes(barewords[-1])
            if dest.endswith("/"):
                out += [os.path.join(dest, os.path.basename(_strip_quotes(s))) for s in srcs]
        out += [s for s in srcs if _has_shell_glob(_strip_quotes(s))]
        return out
    if head in ("mv", "rename"):
        if tdir is not None:
            srcs = list(barewords)
            out = [os.path.join(_strip_quotes(tdir), os.path.basename(_strip_quotes(s))) for s in srcs]
            out.extend(barewords)  # the SOURCEs are removed (mutated) by mv
            return out
        # `mv SRC… DEST`: the DEST is written AND the SRC(s) are removed — both are
        # mutation targets (moving the protected file away deletes it from its
        # watched path → daemon auto-handoff / statefile removal / config neuter).
        # If DEST ends with '/' (explicit dir) also emit DEST/basename(SRC) so a
        # protected exact file inside that dir is not dropped.
        out = list(barewords)
        if barewords:
            dest = _strip_quotes(barewords[-1])
            if dest.endswith("/"):
                out += [os.path.join(dest, os.path.basename(_strip_quotes(s))) for s in barewords[:-1]]
        return out
    if head == "rsync":
        # `rsync SRC… DEST` — DEST may be a file or a dir. If DEST ends with '/'
        # (or is an existing dir) the written file is DEST/basename(SRC); else DEST.
        # The SRC is a mutation target ONLY with `--remove-source-files` (rsync then
        # MOVES = removes the source); a plain rsync COPIES → source is a read.
        # `tdir` is ALWAYS None for rsync (verb-aware): rsync `-t` == `--times`, a
        # no-arg flag, so it never re-routes the destination.
        removes_src = any(a == "--remove-source-files" for a in args)
        if len(barewords) >= 2:
            dest = _strip_quotes(barewords[-1])
            srcs = barewords[:-1]
            if dest.endswith("/"):
                out = [os.path.join(dest, os.path.basename(_strip_quotes(s))) for s in srcs] + [dest]
            else:
                # dest could be file OR existing dir — emit both interpretations.
                out = [dest]
                out += [os.path.join(dest, os.path.basename(_strip_quotes(s))) for s in srcs]
            if removes_src:
                out.extend(srcs)  # the SOURCEs are removed (moved away)
            # a shell-GLOB source (`rsync <protecteddir>/* DEST`) selects the
            # protected dir's contents — over-blocked like the cp glob source.
            out += [s for s in srcs if _has_shell_glob(_strip_quotes(s))]
            return out
        # single operand: only `--remove-source-files` removes it (a move). A plain
        # one-arg `rsync <path>` is a list/read of the source — NOT a mutation, so it
        # must yield no target (else it over-blocks a benign read).
        return list(barewords) if (removes_src and barewords) else []
    if head == "ln":
        if tdir is not None:
            return [os.path.join(_strip_quotes(tdir), os.path.basename(_strip_quotes(s))) for s in barewords]
        # `ln [SRC…] DEST` / `ln -s TARGET LINKNAME`: the last operand is the
        # written link name. If it ends with '/' (a dir) the link is DEST/basename.
        out = barewords[-1:] if barewords else []
        if barewords:
            dest = _strip_quotes(barewords[-1])
            if dest.endswith("/"):
                out += [os.path.join(dest, os.path.basename(_strip_quotes(s))) for s in barewords[:-1]]
        return out
    if head == "dd":
        # dd writes to its `of=<path>` operand (the `if=<path>` is the read
        # source — not a mutation target).
        return [t[len("of="):] for t in args if t.startswith("of=")]
    if head in ("touch", "truncate", "tee",
                "rm", "unlink", "shred", "rmdir"):
        # `rmdir DIR…` removes (mutates) each directory operand — the same all-
        # operands-are-targets shape as rm/unlink (a removal of an ancestor config
        # dir neuters the guard exactly like a delete of the file).
        return barewords
    if head == "unzip":
        # `unzip [opts] ARCHIVE [members…] [-d DIR]`. ARCHIVE is a READ input. With
        # `-d DIR` extraction writes members UNDER DIR (DIR/member); without `-d`,
        # extraction writes into cwd → each member operand. List/test/pipe modes
        # (`-l`, `-v`, `-t`, `-p`, `-c`, `-z`) WRITE nothing → no target (read-only,
        # ALLOW). Fail-safe: an unrecognized form falls back to all-operands.
        ddir = None
        for i, a in enumerate(args):
            if a == "-d" and i + 1 < len(args):
                ddir = args[i + 1]
        list_mode = any(a.startswith("-") and not a.startswith("--")
                        and any(c in a[1:] for c in ("l", "v", "p", "c", "z", "t"))
                        for a in args)
        # operands: archive is the FIRST operand (read); members are the rest; the
        # `-d DIR` value was already removed from barewords by the option scanner is
        # NOT true here (unzip not in _VALUE_OPTS) — so strip ddir explicitly.
        ops = [b for b in barewords if _strip_quotes(b) != _strip_quotes(ddir or "\0")]
        if list_mode:
            return []
        members = ops[1:] if len(ops) >= 1 else []
        if ddir is not None:
            out = [_strip_quotes(ddir)]
            out += [os.path.join(_strip_quotes(ddir), _strip_quotes(m).lstrip("/")) for m in members]
            out += [os.path.join(_strip_quotes(ddir), os.path.basename(_strip_quotes(m))) for m in members]
            return out
        # no -d: members extracted into cwd; with no explicit members the whole
        # archive is unpacked into cwd (caller's cwd resolution handles relative).
        return members
    if head in ("sed", "perl") and _is_inplace_editor_args(head, args):
        return barewords
    if head in ("chmod", "chown", "chgrp"):
        # chmod MODE FILE… / chown OWNER FILE… / chgrp GROUP FILE… — the first
        # bareword is the mode/owner/group spec; the rest are target files. BUT with
        # `--reference=REF` (or `--reference REF`) there is NO spec bareword, so EVERY
        # bareword is a target file.
        has_ref = any(a == "--reference" or a.startswith("--reference=") for a in args)
        if has_ref:
            # `--reference REF` (separated) consumes the next bareword as REF.
            out = list(barewords)
            for i, a in enumerate(args):
                if a == "--reference" and i + 1 < len(args):
                    ref = args[i + 1]
                    if ref in out:
                        out.remove(ref)
                    break
            return out
        # A SYMBOLIC chmod mode (`-w`, `+x`, `=r`, `u-rwx`, `a+rX`) starting with
        # `-`/`+`/`=` is the MODE SPEC, not a discarded option — it was filtered out
        # of `barewords` by the `startswith("-")` rule. Detect the FIRST such
        # `-`/`+`/`=`-prefixed mode token in raw args; if present, EVERY bareword is a
        # target file (the mode lives in the option-shaped token). Otherwise the
        # first bareword is the numeric/owner spec and the rest are targets.
        _MODE_RE = ("r", "w", "x", "X", "s", "t", "u", "g", "o", "a", "0", "1",
                    "2", "3", "4", "5", "6", "7", "-", "+", "=", ",")
        sym_mode = any(
            (a.startswith(("-", "+", "=")) and len(a) >= 2
             and all(c in _MODE_RE for c in a[1:]))
            for a in args
        )
        if sym_mode:
            return list(barewords)
        return barewords[1:] if len(barewords) > 1 else []
    if head == "tar":
        # Determine tar OPERATION MODE from the flags. Extraction/list READ the
        # archive (`-f`) and WRITE the extracted members; create/append/update/
        # concatenate/delete WRITE the ARCHIVE itself (overwrite/modify).
        #
        # CRITICAL flag-value-collision guard: a tar mode letter must be scanned
        # ONLY in the OPTION-LETTER portion of a short cluster — NOT in a fused
        # value suffix. In `-xf/tmp/a.tar` the `f` consumes the rest of the token as
        # the archive value (`/tmp/a.tar`), so the letters of that path (the `r` in
        # `.tar`, etc.) are NOT mode letters. Scanning them led to a false
        # `is_append` (the `r` of `.tar`) which mis-routed an EXTRACT as an
        # archive-overwrite and dropped the real extracted-member target → leak.
        # `_tar_mode_letters(tok)` returns only the cluster prefix up to (and not
        # including) the first VALUE-taking letter (`f`/`b`/`C`/`X`/`T`/`L`/…); the
        # value rides after it in the same token or the next argv.
        _TAR_VALUE_LETTERS = set("fbCXTLgGHIKNVowW")

        def _tar_mode_letters(tok):
            # tok is a short cluster (leading '-' already stripped, or an old-style
            # bare first token). Return the prefix of option letters before the first
            # value-taking letter (inclusive of that value-letter itself, which is a
            # mode-IRRELEVANT option, but exclusive of everything after it).
            out = []
            for ch in tok:
                if ch in _TAR_VALUE_LETTERS:
                    break  # this letter and the rest are option-value, not mode
                out.append(ch)
            return "".join(out)

        def _has_mode_letter(letter, long_names):
            for idx, a in enumerate(args):
                if a in long_names:
                    return True
                if a.startswith("-") and not a.startswith("--"):
                    if letter in _tar_mode_letters(a[1:]):
                        return True
                elif idx == 0 and not a.startswith("-"):
                    # old-style first token without a leading dash (`tar xf …`).
                    if letter in _tar_mode_letters(a):
                        return True
            return False
        is_extract = _has_mode_letter("x", ("--extract", "--get"))
        is_create = _has_mode_letter("c", ("--create",))
        is_append = (_has_mode_letter("r", ("--append",))
                     or _has_mode_letter("u", ("--update",))
                     or _has_mode_letter("A", ("--concatenate", "--catenate")))
        is_delete = any(a == "--delete" for a in args)
        # parse -C/--directory -> cdir, -f/--file/clustered|fused -f -> archive.
        cdir = None
        archive = None
        skip = set()
        old_style = bool(args) and not args[0].startswith("-")
        for i, a in enumerate(args):
            if a in ("-C", "--directory") and i + 1 < len(args):
                cdir = args[i + 1]; skip.add(i + 1)
            elif a.startswith("--directory="):
                cdir = a.split("=", 1)[1]
            elif a in ("-f", "--file") and i + 1 < len(args):
                archive = args[i + 1]; skip.add(i + 1)
            elif a.startswith("--file="):
                archive = a.split("=", 1)[1]
            elif a.startswith("-") and not a.startswith("--") and "f" in a[1:]:
                # clustered short bundle containing `f`. If chars FOLLOW `f` in the
                # same token (`-xf<archive>` fused), the archive rides in this token;
                # else (`-xf`, `-xvf`) the NEXT token is the archive.
                pos = a.index("f", 1)
                rest = a[pos + 1:]
                if rest:
                    archive = rest
                elif i + 1 < len(args):
                    archive = args[i + 1]; skip.add(i + 1)
            elif old_style and i == 0 and "f" in a:
                # old-style first cluster `xf`/`cf`/`xvf`: the NEXT token is archive.
                if i + 1 < len(args):
                    archive = args[i + 1]; skip.add(i + 1)
        if is_create or is_append or is_delete:
            # the ARCHIVE is OVERWRITTEN / MODIFIED → it is a mutation target. The
            # member operands are READ inputs (sources packed into the archive).
            return [archive] if archive else []
        if is_extract:
            # extraction WRITES the extracted members under the extraction dir
            # (`-C DIR`, default cwd). The ARCHIVE (`-f`) is a READ input.
            members = [args[i] for i, t in enumerate(args)
                       if not t.startswith("-") and i not in skip
                       and not (old_style and i == 0)
                       and _strip_quotes(t) != _strip_quotes(archive or "\0")]
            if cdir is not None:
                cd = _strip_quotes(cdir)
                # tar PRESERVES member subpaths: extracting `pkg/dist/x` into DIR
                # writes DIR/pkg/dist/x. Emit the subpath-preserving join (primary),
                # the basename join (conservative), the raw member, and DIR itself
                # (so extracting INTO a protected dir with NO explicit members blocks).
                out = [cd]
                out += [os.path.join(cd, _strip_quotes(m).lstrip("/")) for m in members]
                out += [os.path.join(cd, os.path.basename(_strip_quotes(m))) for m in members]
                out += members
                return out
            return members
    return []


def _step0_mutation_targets(head: str, args: list) -> list:
    """STEP0 config-self-protection mutation-target extractor. Delegates to the ONE
    shared, position-complete `_mutation_targets_for_verb` so STEP0, W6, and W7 can
    never drift on which token positions count as a mutation (mv-source, rsync
    --remove-source-files source, target-dir, dd of=, chmod/chown --reference,
    in-place editors, tar -C, ln dest)."""
    return _mutation_targets_for_verb(head, args)


def _step0_redirect_target(sc: str) -> Optional[str]:
    """Return a write-redirect target in a simple command, covering the fd-prefixed
    and force forms `_has_redirect_to` misses: `>`, `>>`, `1>`, `2>`, `&>`, `&>>`,
    `>|`, `N>|`. Best-effort (matches the first write redirect target). Read
    redirects (`<`) are NOT returned. Used ONLY by STEP0 self-protection so a
    `<wrapper> echo x 1>|<datafile>` neuter is caught."""
    m = re.search(r"(?:^|[\s;&|])(?:&|\d+)?>>?\|?\s*([^\s;&|<>]+)", sc)
    if m:
        return _strip_quotes(m.group(1))
    return None


def _step0_targets_config_redirect(sc: str, cwd: Optional[str], cwd_det: bool) -> bool:
    """True if `sc` write-redirects to the config path via ANY write-redirect form
    (bare/force/fd-prefixed/stdout+stderr) in ANY position, resolving a relative
    target against the effective cwd. Uses the SAME shared `_write_redirect_targets`
    scanner as the bundle/statefile path so redirect coverage cannot drift."""
    variants = list(_config_path_variants())
    for rt in _write_redirect_targets(sc):
        for cand in _resolve_rel(rt, cwd, cwd_det):
            if _path_matches_any(cand, variants):
                return True
    return False


def _step0_mutation_anchor_hits(ctx: "Context", idx: int, sc: str,
                                tokens: list) -> bool:
    """HEAD-AGNOSTIC: True if this simple command MUTATES the hardcoded config
    data file, regardless of the leading wrapper/front-end head.

    Reads the per-evaluation inputs (`simple_cmds`, `cwd_base`) from the shared
    `ctx`; `idx`/`sc`/`tokens` are the per-command coordinates. This is a pure
    relocation of how those two inputs travel — the values are identical.

    This is the config-self-protection mirror of the W6/W7 protected-path anchors
    (`_anchor_mutation_hits`): it scans EVERY mutation-verb basename in EXECUTABLE
    position (so the verb is found even when a NOVEL/undocumented front-end — any
    real, invented, or stacked process/exec wrapper — is the simple command's head,
    and a benign mutation-looking earlier token does not mask a later real mutator),
    reconstructs each verb's OWN argv, extracts the write/metadata target(s),
    resolves each against the effective cwd (cd chain + wrapper chdir, seeded from
    the payload cwd_base so a relative data-file target under the config dir is
    caught), and matches against the config-path variants. The redirect-target form
    is handled separately by the caller. The config path is the hardcoded
    `DATA_FILE_PATH` (a generic path, not a project name), NOT loaded from the data
    file — the self-protection must not depend on the very file it protects, so this
    holds even when the config is absent/corrupt (STEP0 runs before config load),
    and it runs before the /do//allow bypass (which lives in the bash glue, not
    here). Returns False when no mutation verb is in executable position OR no target
    matches — so a mutation of a NON-config file behind a wrapper still ALLOWS (no
    over-block). The CALLER gates this behind `_is_inspection_command` so a read/
    inspect command carrying a mutation word as DATA (`grep cp <datafile>`) ALLOWS."""
    # the data file AND its protected ANCESTOR directories (a mutation/move/delete
    # of the parent config dir neuters the guard exactly like a delete of the file).
    variants = list(_config_or_ancestor_variants())
    exec_toks = _anchor_exec_tokens(tokens)
    cwd, cwd_det = _effective_cwd_after(ctx.simple_cmds, idx, ctx.cwd_base)
    cwd, cwd_det = _fold_wrapper_cwd(cwd, cwd_det, tokens)
    # find/fd with a destructive action (`-delete` / `-exec <mutation>`) against the
    # data file or an ancestor dir — `find` is in the read/inspect allowlist, so the
    # caller's inspection gate would skip it; STEP0 inspects it here HEAD-AGNOSTICALLY
    # (the find head may itself be behind a wrapper).
    if _step0_find_destructive_hits(tokens, exec_toks, variants, cwd, cwd_det):
        return True
    # scan ALL mutation verbs in exec position (not just the first), so a leading
    # benign mutation-named data token cannot mask a later real mutator.
    for (i, st) in exec_toks:
        verb_base = os.path.basename(_strip_quotes(st))
        if verb_base not in _STEP0_MUTATION_HEADS:
            continue
        verb_args = tokens[i + 1:]
        for tgt in _step0_mutation_targets(verb_base, verb_args):
            for cand in _resolve_rel(tgt, cwd, cwd_det):
                if _path_matches_any(cand, variants):
                    return True
    return False


# find/fd actions that MUTATE the matched entries (destroy a protected file/dir).
# `-delete` removes; the exec-family runs an arbitrary command per match (a
# mutation when that command is a filesystem-mutation verb). Generic find grammar,
# no project names.
_FIND_DELETE_ACTIONS = frozenset({"-delete", "--delete"})
# include fd's short exec flags `-x`/`-X` (only reached when the head is actually
# find/fd via `_FIND_EXEC_HEADS`, so they never collide with `tar -x`/`-X`).
_FIND_EXEC_ACTIONS = frozenset({"-exec", "-execdir", "-ok", "-okdir", "--exec", "--exec-batch", "-x", "-X"})
# Mutation verbs that, when run by `find … -exec <verb>`, destroy/alter the match.
_FIND_EXEC_MUTATION_VERBS = (
    _STEP0_MUTATION_HEADS | frozenset({"rm", "rmdir", "unlink", "shred"})
)


def _find_is_destructive(tokens: list, find_idx: int) -> bool:
    """True if the find/fd invocation starting at `find_idx` carries a DESTRUCTIVE
    action: `-delete`, OR an `-exec`/`-execdir`/`-ok`/`-okdir` whose executed
    command basename is a filesystem-mutation verb. A read-only `find … -exec cat`
    / `find … -print` is NOT destructive."""
    rest = tokens[find_idx + 1:]
    for j, t in enumerate(rest):
        st = _strip_quotes(t)
        if st in _FIND_DELETE_ACTIONS:
            return True
        if st in _FIND_EXEC_ACTIONS and j + 1 < len(rest):
            execd = os.path.basename(_strip_quotes(rest[j + 1]))
            if execd in _FIND_EXEC_MUTATION_VERBS:
                return True
    return False


# find expression tokens that make a filter NON-exonerating: a disjunction (`-o`/
# `-or`), a negation (`!`/`-not`), or a grouping paren — any of these means a
# positive path/name filter cannot PROVE the protected descendant is excluded, so
# reverse containment must still run. Generic find grammar.
_FIND_NONEXONERATING = frozenset({"-o", "-or", "!", "-not", "(", ")"})
_FIND_DELETE_AND_ACTIONS = frozenset({"-delete", "--delete", "-exec", "-execdir",
                                      "-ok", "-okdir", "--exec", "--exec-batch", "-x", "-X"})


def _find_filter_exonerates_reverse(tokens: list, fi: int, globs: list,
                                    cwd: Optional[str], cwd_det: bool) -> bool:
    """PROOF-BASED: True only if the find expression carries a POSITIVE, CONJUNCTIVE
    path/name FILTER predicate, appearing BEFORE the destructive action, that is
    PROVEN DISJOINT from every protected target — so reverse containment on the root
    may be safely suppressed (`find /root -path /tmp/unrelated -delete`). Returns
    FALSE (do NOT suppress) for any non-exonerating shape: a disjunction (`-o`), a
    negation (`!`/`-not`), a grouping paren, a broad wildcard predicate (`-name '*'`),
    an action that PRECEDES the filter (`find . -delete -name x` deletes everything
    first), the absence of any positive path/name filter, or a filter that could
    still match a protected target. Conservative — when in doubt, do NOT exonerate
    (reverse containment runs, over-block accepted)."""
    rest = tokens[fi + 1:]
    saw_positive_filter = False
    saw_action = False
    for j, t in enumerate(rest):
        st = _strip_quotes(t)
        if st in _FIND_NONEXONERATING:
            return False  # disjunction / negation / grouping -> cannot prove disjoint
        # a destructive action token: any positive filter must have come BEFORE it.
        if st in _FIND_DELETE_AND_ACTIONS:
            saw_action = True
            continue
        flag = st
        val = None
        if "=" in st and st.startswith("-"):
            flag, val = st.split("=", 1)
        if flag in _FIND_PATH_PREDICATES or flag in _FIND_NAME_PREDICATES:
            if val is None and j + 1 < len(rest):
                val = _strip_quotes(rest[j + 1])
            if val is None:
                return False
            if saw_action:
                return False  # filter AFTER the action: the action already ran broad
            # a broad wildcard filter does not exclude the protected target.
            if set(val) <= set("*?[]{}./"):
                return False
            ic = flag in _FIND_CASE_INSENSITIVE_PREDS
            if flag in _FIND_PATH_PREDICATES:
                disjoint = True
                for cand in _resolve_rel(val, cwd, cwd_det):
                    if _path_matches_any(cand, globs):
                        disjoint = False
                    if ic and _path_matches_any(cand.casefold(), [g.casefold() for g in globs]):
                        disjoint = False
                # a RELATIVE path filter with no resolvable cwd cannot be proven
                # disjoint (it might match a protected target) -> do not exonerate.
                if not os.path.isabs(_strip_quotes(val)) and not (cwd and cwd_det):
                    return False
                if disjoint:
                    saw_positive_filter = True
                else:
                    return False  # the filter MATCHES a protected target
            else:  # name filter
                if _name_value_matches_protected(val, globs, ic):
                    return False  # the name filter could match a protected basename
                saw_positive_filter = True
    # exonerate only if a proven-disjoint positive filter was seen (any filter that
    # appeared after the action already returned False inside the loop).
    return saw_positive_filter


def _find_destructive_target_hits(tokens: list, exec_toks: list, globs: list,
                                  cwd: Optional[str], cwd_det: bool,
                                  cfg: Optional[dict] = None) -> bool:
    """HEAD-AGNOSTIC: True if a find/fd invocation (anywhere in the exec tokens,
    possibly behind a wrapper) performs a DESTRUCTIVE action (`-delete` /
    `-exec <mutation>`) on a PATH operand OR a PATH/NAME PREDICATE value that matches
    `globs` — the file itself, an ancestor directory of it, OR a CONTAINER root that
    holds a protected descendant. `find <protected-or-ancestor> -delete`,
    `find /root -path <protected> -delete`, `find <repo> -name <basename> -delete`,
    and `find packages -delete` (a root CONTAINING the protected package) BLOCK; a
    read-only `find <…> -print` (no destructive action) ALLOWS, and a destructive
    find on a genuinely UNRELATED path/name ALLOWS (no over-block).

    Two containment directions:
      • FORWARD: a positional root / `-path` predicate value resolves UNDER a
        protected glob (`_path_matches_any`).
      • REVERSE (cfg-driven): a positional root CONTAINS a concrete protected dir
        (`_destructive_root_contains_protected`) — closes `find packages -delete`.
    The `-name`/`-g` BASENAME predicate is SCOPED to a search root that intersects a
    protected location (root under/over a protected dir), so a routine
    `find /tmp -name <basename> -delete` on an unrelated tree ALLOWS (codex F2)."""
    for fi, st in exec_toks:
        if os.path.basename(_strip_quotes(st)) not in _FIND_EXEC_HEADS:
            continue
        if not _find_is_destructive(tokens, fi):
            continue
        operands = _find_path_operands(tokens, fi)
        # a path-LESS destructive find (`find -delete` / `cd <dir> && find -delete`)
        # targets the effective cwd implicitly — resolve `.` against it.
        if not operands:
            operands = ["."]
        preds = list(_find_predicate_values(tokens, fi))
        is_fd = os.path.basename(_strip_quotes(st)) in ("fd", "fdfind")
        # forward: a root resolves UNDER a protected glob.
        for p in operands:
            for cand in _resolve_rel(p, cwd, cwd_det):
                if _path_matches_any(cand, globs):
                    return True
        # fd's search dirs are positionals AFTER the pattern, missed by
        # `_find_path_operands`; collect them so a `fd -g <glob> <protecteddir> -X rm`
        # root-intersection / reverse-containment is recognized.
        fd_roots = _fd_positional_roots(tokens, fi) if is_fd else []
        all_roots = list(operands) + fd_roots
        # PROOF-BASED suppression of reverse containment: only a positive, conjunctive,
        # pre-action path/name filter PROVEN disjoint from protected targets exonerates
        # the root (`find /root -path /tmp/unrelated -delete`). A broad `-name '*'`, a
        # `-o`/`!`, an action-before-filter, or an fd default regex pattern that could
        # still match a protected target does NOT exonerate — reverse containment runs.
        if is_fd:
            # fd's pattern is a regex/glob filter; exonerate ONLY when an fd `-g`/`-p`
            # predicate is proven disjoint (the find-expression proof does not model
            # fd's default regex, so a bare fd pattern is treated as non-exonerating —
            # reverse containment runs, an accepted over-block on the dedicated host).
            exonerated = all(
                (kind == "name" and not _name_value_matches_protected(val, globs, ic)
                 and not (set(_strip_quotes(val)) <= set("*?[]{}./")))
                or (kind == "path" and os.path.isabs(_strip_quotes(val))
                    and not any(_path_matches_any(c, globs)
                                for c in _resolve_rel(val, cwd, cwd_det)))
                for kind, val, ic in preds) and bool(preds)
        else:
            exonerated = _find_filter_exonerates_reverse(tokens, fi, globs, cwd, cwd_det)
        # reverse (cfg-driven): an UN-exonerated destructive find whose root CONTAINS a
        # concrete protected dir wipes the protected descendant (`find packages
        # -delete`, `find . -name '*' -delete`).
        if cfg is not None and not exonerated:
            for p in all_roots:
                if _destructive_root_contains_protected(p, globs, cfg, cwd, cwd_det):
                    return True
        # whether ANY search root intersects a protected location — required to scope
        # the BASENAME predicate (a bare `-name <basename>` on an unrelated tree must
        # not over-block). A root intersects when it is under a protected glob OR it
        # contains a concrete protected dir (reverse). With no cfg (STEP0 config
        # variants) the basename predicate stays root-unscoped (the config file's
        # basename is distinctive enough), preserving config self-protection.
        def _root_intersects_protected() -> bool:
            for p in all_roots:
                for cand in _resolve_rel(p, cwd, cwd_det):
                    if _path_matches_any(cand, globs) or _path_under_any(cand, globs):
                        return True
                if cfg is not None and _destructive_root_contains_protected(p, globs, cfg, cwd, cwd_det):
                    return True
            return False
        name_scoped_ok = (cfg is None) or _root_intersects_protected()
        # PREDICATE-selected victims: `-path <protected>` (full-path) matches the
        # protected glob directly; `-name <basename>` matches the protected glob's
        # basename — but ONLY when a search root intersects a protected location.
        for kind, val, ic in preds:
            if kind == "path":
                for cand in _resolve_rel(val, cwd, cwd_det):
                    if _path_matches_any(cand, globs):
                        return True
                    if ic and _path_matches_any(cand.casefold(), [g.casefold() for g in globs]):
                        return True
            elif kind == "name" and name_scoped_ok and _name_value_matches_protected(val, globs, ic):
                return True
    return False


def _step0_find_destructive_hits(tokens: list, exec_toks: list, variants: list,
                                 cwd: Optional[str], cwd_det: bool) -> bool:
    """STEP0 wrapper around the shared find-destructive scanner for the config
    data-file + ancestor-dir variant set. No cfg → basename predicate stays root-
    unscoped (the config basename is distinctive; config self-protection is broad)."""
    return _find_destructive_target_hits(tokens, exec_toks, variants, cwd, cwd_det)


def _container_glob_too_broad(parent: str) -> bool:
    """True if a derived container-dir glob is too broad to protect — a bare
    wildcard (`**`/`*`/`**/*`), an empty string, OR an ABSOLUTE path that resolves
    to one of the generic too-broad system/home roots (`/root`, `/usr`, …). A glob
    bottoming out at one of these would over-block routine ops on the home/system
    roots, so it is dropped. A RELATIVE / `**`-prefixed glob (`**/packages/<pkg>`)
    is a segment-suffix match and is NOT a system root, so it is kept. Generic —
    the stop-roots are POSIX system/home dirs, no project names."""
    if not parent or set(parent) <= {"*", "/"}:
        return True
    if parent in ("**", "*", "/", "**/*", "*/*"):
        return True
    # an ABSOLUTE container glob with NO wildcard is dropped when it is a generic
    # root OR a SHALLOW (depth < 3) system dir (`/usr/bin`, `/usr/lib`, `/etc/x`) —
    # a shared system directory whose blanket protection would over-block routine
    # ops. A wildcard-bearing absolute glob (`/home/.appd*`) is a SPECIFIC per-home
    # dir and is kept; a deep absolute dir (depth ≥ 3) is specific enough to keep.
    if parent.startswith("/") and "*" not in parent:
        norm = os.path.normpath(parent)
        if norm in _ANCESTOR_STOP_ROOTS:
            return True
        depth = len([s for s in norm.split("/") if s])
        if depth < 3:
            return True
    return False


def _container_dir_globs(file_globs: list) -> list:
    """Derive the protected CONTAINER-directory globs from protected FILE globs —
    the directories whose move/delete destroys the protected file. For
    `**/packages/<pkg>/dist/<bundle>` the containers are `**/packages/<pkg>/dist`
    (the immediate dir, e.g. removing the whole `dist`) and `**/packages/<pkg>`, so
    `mv|rm|rmdir|find -delete` of either BLOCKS. For `/home/.appd*/<statefile>`
    the container is `/home/.appd*` (the per-home dir) — but NOT `/home` (a generic
    home root, dropped by `_container_glob_too_broad`). A derived glob that is a bare
    wildcard or a generic system/home root is dropped (no over-block). A glob with no
    usable parent yields nothing. Generic — driven entirely by the data-file globs."""
    out = set()
    for fg in file_globs:
        if not fg or ("/" not in fg):
            continue
        parent = fg.rsplit("/", 1)[0]
        # climb up to TWO directory levels (the immediate container + its parent).
        for _ in range(2):
            if not parent:
                break
            if not _container_glob_too_broad(parent):
                out.add(parent)
            nxt = parent.rsplit("/", 1)[0] if "/" in parent else ""
            if nxt == parent:
                break
            parent = nxt
    return [g for g in out if not _container_glob_too_broad(g)]


def _anchor_family_destructive_hits(sc: str, tokens: list, exec_toks: list,
                                    file_globs: list, cwd: Optional[str],
                                    cwd_det: bool, cfg: Optional[dict] = None) -> bool:
    """Class-sweep companion to `_anchor_mutation_hits` for a protected FILE-glob
    family (hotfile bundle / statefile / global-bin). Closes the two blind spots the
    direct-mutation anchor misses:
      (1) find/fd DESTRUCTIVE action (`-delete` / `-exec <mutation>`) against the
          protected file OR its derived container directory, and
      (2) an ANCESTOR/CONTAINER-directory mutation (`mv|rm|rmdir <containerdir>`)
          that destroys the protected file by removing/moving its directory.
    Head-agnostic (works behind any wrapper). A read-only find, or a destructive op
    on an UNRELATED path, does not hit (no over-block)."""
    container_globs = _container_dir_globs(file_globs)
    all_globs = list(file_globs) + container_globs
    # (1) find/fd destructive against the file OR a container dir (cfg-driven reverse
    # containment also catches a destructive root CONTAINING the protected file).
    if _find_destructive_target_hits(tokens, exec_toks, all_globs, cwd, cwd_det, cfg):
        return True
    # (2) a mutation verb whose target is a CONTAINER directory (the file itself is
    # already covered by `_anchor_mutation_hits`; here we add the container dirs).
    if container_globs and _anchor_mutation_hits(sc, tokens, exec_toks, container_globs, cwd, cwd_det, cfg):
        return True
    return False


def _step0_self_protection(ctx: "Context") -> Optional[Verdict]:
    # Read the per-evaluation inputs from the shared Context. Local aliases keep
    # the body below a byte-for-byte behavior match (identical values, identical
    # per-command cwd derivation) — the Context adoption is a pure relocation of
    # how simple_cmds / cwd_base arrive, nothing else.
    simple_cmds = ctx.simple_cmds
    cwd_base = ctx.cwd_base
    for idx, sc in enumerate(simple_cmds):
        tokens = _safe_shlex(sc)
        if not tokens:
            continue
        cw = _command_words(tokens)
        if not cw:
            continue
        _tok_idx, head, rest = cw[0]
        # effective cwd for relative data-file resolution (seeded from the payload
        # cwd so a relative `<datafile>` while cwd==<config dir> is caught).
        cwd, cwd_det = _effective_cwd_after(simple_cmds, idx, cwd_base)
        cwd, cwd_det = _fold_wrapper_cwd(cwd, cwd_det, tokens)
        # redirect write to the config path (any head — head-agnostic; covers
        # fd-prefixed / force forms `1>`/`>|`/`&>` and relative targets).
        if _step0_targets_config_redirect(sc, cwd, cwd_det):
            return _block("STEP0", "config self-protection: redirect to data file")
        # in-place sed/perl editing the config path. Checked BEFORE the inspection
        # gate because sed/perl are in the read/inspect/edit allowlist, but `sed -i`/
        # `perl -i` MUTATE the file in place — the inspection gate would wrongly skip
        # them. (Behind a wrapper the head is the wrapper, so the head-agnostic
        # anchor below also catches it; this branch covers the bare head form.)
        if head in ("sed", "perl") and _is_inplace_editor_args(head, list(rest)):
            for tgt in [t for t in rest if not t.startswith("-")]:
                for cand in _resolve_rel(tgt, cwd, cwd_det):
                    if _path_matches_any(cand, list(_config_path_variants())):
                        return _block("STEP0", "config self-protection: in-place edit of data file")
        # find/fd DESTRUCTIVE action (`-delete` / `-exec <mutation>`) against the
        # data file OR an ancestor dir — checked BEFORE the inspection gate because
        # `find` is in the read/inspect allowlist (the gate would skip the bare-head
        # `find <datafile> -delete` form). Head-agnostic: also catches the find
        # behind any wrapper. A read-only `find <datafile> -print` is NOT destructive
        # and a destructive find on an UNRELATED path does not match — both ALLOW.
        _exec_toks_step0 = _anchor_exec_tokens(tokens)
        if _step0_find_destructive_hits(tokens, _exec_toks_step0,
                                        list(_config_or_ancestor_variants()), cwd, cwd_det):
            return _block("STEP0", "config self-protection: find destructive action on data file or ancestor")
        # GATE: a read/inspect/edit command carrying a mutation word merely as DATA
        # (`grep cp <datafile>`, `echo cp <datafile>`, `cat <datafile>`) is NOT a
        # mutation — skip the mutation-verb anchor so it ALLOWS (no over-block). The
        # redirect check above already ran (a read command with a write redirect to
        # the config path IS a mutation and is caught), and the in-place sed/perl
        # mutation case is handled just above. find/fd -exec and fuser -k are
        # treated as executors by `_is_inspection_command`, so they are NOT skipped.
        if _is_inspection_command(head, rest):
            continue
        # HEAD-AGNOSTIC mutation of the config file behind ANY wrapper (documented,
        # undocumented, invented, or stacked). Mirrors W6/W7: find a mutation verb
        # in executable position and match its (cwd-resolved) target against the
        # config path — so `<any-wrapper> cp|mv|tee|truncate|dd|install|rsync|ln|
        # sed -i|perl -i|chmod|chown <datafile>` BLOCKS even though the leading head
        # is the wrapper, not the mutation verb. (The bare-head form is the
        # position-0 special case of the same scan; the legacy head-keyed
        # CONFIG_MUTATION_HEADS check is subsumed by this and removed.)
        if _step0_mutation_anchor_hits(ctx, idx, sc, tokens):
            return _block("STEP0", "config self-protection: mutation of data file")
    return None


# ── STEP 1: fail-closed indeterminate-policy verb families ───────────────────

def _step1_indeterminate(simple_cmds: list) -> Verdict:
    """When config is unavailable, block protected verb FAMILIES generically.
    Allow commands clearly outside those families.
    """
    for sc in simple_cmds:
        tokens = _safe_shlex(sc)
        if not tokens:
            continue
        cw = _command_words(tokens)
        if not cw:
            continue
        _, head, rest = cw[0]
        rest_bases = [os.path.basename(_strip_quotes(t)) for t in rest]
        # service control
        if head in ("systemctl", "service", "initctl"):
            if any(v in rest_bases for v in SERVICE_VERBS) or any(v in tokens for v in SERVICE_VERBS):
                return _block("STEP1", "indeterminate policy: service-control verb")
        # kill / proc control
        if head in KILL_VERBS:
            return _block("STEP1", "indeterminate policy: process-kill verb")
        if head == "xargs" and any(b in KILL_VERBS for b in rest_bases):
            return _block("STEP1", "indeterminate policy: xargs kill")
        # package-manager script-run / build / global install
        if head in PKG_MANAGERS:
            if any("-g" == t or "--global" == t for t in rest):
                return _block("STEP1", "indeterminate policy: global package op")
            # any non-meta pm invocation is fail-closed (build/launch family)
            if not _is_meta_query(head, rest):
                return _block("STEP1", "indeterminate policy: package-manager invocation")
        # bare build tools
        if head in BUILD_TOOL_BASENAMES:
            return _block("STEP1", "indeterminate policy: build tool")
        # runtime launch (node/tsx/bun ... .mjs/.ts) — ambiguous launch
        if head in RUNTIMES:
            return _block("STEP1", "indeterminate policy: runtime launch")
        # package runners
        if head in ("npx", "bunx"):
            return _block("STEP1", "indeterminate policy: package runner")
        # ── HEAD-AGNOSTIC fail-closed tail scan ──────────────────────────────
        # Behind a novel exec front-end (an undocumented process/exec wrapper) the
        # head is the wrapper, so the head-keyed checks above miss the danger
        # family in the tail. When the head is NOT a read/inspect/edit operation,
        # scan ALL exec-position tokens for the generic danger families so a
        # front-end-wrapped build/runtime/kill/service/pm invocation still blocks
        # under an absent/corrupt config (the leak must not survive fail-closed).
        if not _is_inspection_command(head, rest):
            exec_bases = [os.path.basename(_strip_quotes(t)) for _i, t in _anchor_exec_tokens(tokens)]
            if any(b in KILL_VERBS for b in exec_bases):
                return _block("STEP1", "indeterminate policy: process-kill verb (tail)")
            # `fuser -k` is a kill executor the head-keyed scan misses (fuser is
            # not in KILL_VERBS). Behind any wrapper its head is the wrapper, so
            # detect fuser among the exec-token basenames HEAD-AGNOSTICALLY, then
            # scan only the tokens AFTER that fuser for its OWN -k/--kill flag.
            # Scoping to fuser's own args (not the whole simple command) avoids
            # over-blocking a read-only `<wrapper> --opt fuser <path>` where a
            # WRAPPER long option merely contains the letter k (e.g. --check).
            # Closes the xargs / find -exec / fd -x fuser -k siblings too.
            if "fuser" in exec_bases:
                _fi = next((i for i, t in enumerate(tokens)
                            if os.path.basename(_strip_quotes(t)) == "fuser"), None)
                if _fi is not None and any(
                        _strip_quotes(t) in ("-k", "--kill") or
                        (_strip_quotes(t).startswith("-") and not _strip_quotes(t).startswith("--")
                         and "k" in _strip_quotes(t)[1:])
                        for t in tokens[_fi + 1:]):
                    return _block("STEP1", "indeterminate policy: fuser -k process-kill (tail)")
            if any(b in ("systemctl", "service", "initctl") for b in exec_bases) and (
                    any(v in [os.path.basename(_strip_quotes(t)) for t in tokens] for v in SERVICE_VERBS)):
                return _block("STEP1", "indeterminate policy: service-control verb (tail)")
            if any(b in PKG_MANAGERS for b in exec_bases):
                return _block("STEP1", "indeterminate policy: package-manager invocation (tail)")
            if any(b in BUILD_TOOL_BASENAMES for b in exec_bases):
                return _block("STEP1", "indeterminate policy: build tool (tail)")
            if any(b in RUNTIMES for b in exec_bases):
                return _block("STEP1", "indeterminate policy: runtime launch (tail)")
            if any(b in ("npx", "bunx") for b in exec_bases):
                return _block("STEP1", "indeterminate policy: package runner (tail)")
    return ALLOW


# ── P1 LAUNCH_GUARD ──────────────────────────────────────────────────────────

def _is_meta_query(pm_head: str, rest: list) -> bool:
    """A meta query has ONLY a version/help flag and no script token/subcommand."""
    nonflag = [t for t in rest if not t.startswith("-")]
    flags = [t for t in rest if t.startswith("-")]
    if nonflag:
        return False
    meta = {"--version", "-v", "--help", "-h", "-V"}
    return all(f in meta for f in flags) and len(flags) >= 1


def _path_matches_cwd(raw: str, globs: list, cwd: Optional[str], cwd_det: bool) -> bool:
    """Match a token against globs as itself AND, if relative and cwd known,
    resolved against the effective cwd. Drops a leading ./ for the relative case.
    """
    if _path_matches_any(raw, globs):
        return True
    st = _strip_quotes(raw)
    if cwd and cwd_det and not os.path.isabs(st):
        resolved = os.path.normpath(os.path.join(cwd, st))
        if _path_matches_any(resolved, globs):
            return True
    return False


def _runtime_target(rest: list) -> Optional[str]:
    """Find the first real script positional after a runtime's options.
    Skips runtime flags that consume a value (--loader X, -r X, etc.) and a
    single leading runtime subcommand (deno run / tsx watch / bun run) that
    precedes the script positional."""
    i = 0
    n = len(rest)
    subcmd_skipped = False
    while i < n:
        t = rest[i]
        if t == "--":
            i += 1
            continue
        if t in _RUNTIME_OPTS_WITH_ARG:
            i += 2
            continue
        if t.startswith("-"):
            # --opt=value or a value-less flag: single token
            i += 1
            continue
        st = _strip_quotes(t)
        # Skip ONE leading runtime subcommand (run/watch) — a bare word with no
        # path separator/extension — so the protected script positional after it
        # is reached. Never skips a real filename.
        if (not subcmd_skipped and st in _RUNTIME_SUBCOMMANDS
                and i + 1 < n and "/" not in st and "." not in st):
            subcmd_skipped = True
            i += 1
            continue
        return st
    return None


# Runtime options whose VALUE is a module that is preloaded/executed (so the
# protected bundle/src can run without being the script positional).
_RUNTIME_PRELOAD_OPTS = frozenset({"-r", "--require", "--import", "--loader", "--experimental-loader"})


def _runtime_preload_hits(rest: list, launch_paths: list, cwd: Optional[str], cwd_det: bool) -> bool:
    i = 0
    n = len(rest)
    while i < n:
        t = rest[i]
        if t in _RUNTIME_PRELOAD_OPTS and i + 1 < n:
            if _path_matches_cwd(_strip_quotes(rest[i + 1]), launch_paths, cwd, cwd_det):
                return True
            i += 2
            continue
        for opt in _RUNTIME_PRELOAD_OPTS:
            if t.startswith(opt + "="):
                if _path_matches_cwd(_strip_quotes(t.split("=", 1)[1]), launch_paths, cwd, cwd_det):
                    return True
        i += 1
    return False


def _node_run_script(rest: list) -> Optional[str]:
    """Return the script token of `node --run <script>` / `node --run=<script>`
    (Node 22+ package-script runner), else None."""
    for i, t in enumerate(rest):
        st = _strip_quotes(t)
        if st == "--run" and i + 1 < len(rest):
            return _strip_quotes(rest[i + 1])
        if st.startswith("--run="):
            return _strip_quotes(st.split("=", 1)[1])
    return None


def _upstream_text_in_group(groups: list, sc: str) -> str:
    """Return the concatenated text of segments UPSTREAM of `sc` within the
    pipeline group that contains it (empty if not found or first in group).

    An xargs/while-read consumer's argv is sourced from the upstream segments'
    stdout, so a protected launch path or command emitted upstream feeds the
    consumer even though it never appears in the consumer's own tokens.
    """
    target = sc.strip()
    for group in groups:
        for k, seg in enumerate(group):
            if seg.strip() == target:
                return " ".join(group[:k])
    return ""


def _selector_cwd(head: str, rest: list, cfg: dict, cwd: Optional[str], cwd_det: bool):
    """If a PM workspace selector (yarn workspace <ws> / -w / --filter / pnpm -C)
    is present, resolve it to the selected workspace's manifest dir so a
    subsequent exec'd runtime/build resolves relative protected paths against the
    SELECTED workspace (not the shell cwd). Returns (cwd, cwd_det) updated.

    A determinate resolution to a known workspace dir threads that dir as the
    effective cwd. An unresolvable selector leaves cwd_det False (fail-closed for
    relative-path families). Non-PM heads or no selector return cwd unchanged.
    """
    if head not in PKG_MANAGERS:
        return (cwd, cwd_det)
    sel = _explicit_workspace_selector(head, rest)
    if sel is None or sel == "<MULTI>":
        return (cwd, cwd_det)
    man_dir, _is_protected, _scripts, det = _resolve_workspace_manifest(sel, cfg, cwd)
    if det and man_dir:
        return (os.path.normpath(man_dir), True)
    # selector named but unresolvable -> indeterminate for relative resolution
    return (cwd, False)


def _exec_subcommand_after_selector(head: str, rest: list):
    """For a PM `<sel> exec <runner> [args]` form, return (runner_basename,
    args_after_runner) so the post-exec launch can be routed through P1 with the
    selector-resolved cwd. Returns (None, []) if there is no exec/runner form."""
    # find an exec/dlx/x keyword AFTER the selector token; the selector value was
    # already consumed by _explicit_workspace_selector, so scan all of rest.
    i = 0
    while i < len(rest):
        if rest[i] in ("exec", "dlx", "x"):
            toks = rest[i + 1:]
            j = 0
            while j < len(toks):
                t = toks[j]
                if t == "--":
                    j += 1
                    continue
                if t in ("-w", "--workspace", "--filter", "-F", "--prefix", "-C", "--dir", "--cwd") and j + 1 < len(toks):
                    j += 2
                    continue
                if any(t.startswith(f + "=") for f in ("--workspace", "--filter", "-F", "--prefix", "-C", "--dir", "--cwd", "-w")):
                    j += 1
                    continue
                if t in _RUNNER_OPTS_WITH_ARG:
                    j += 2
                    continue
                if t.startswith("-"):
                    j += 1
                    continue
                return (os.path.basename(_strip_quotes(t)), toks[j + 1:])
            return (None, [])
        i += 1
    return (None, [])


def _p1_launch(simple_cmds: list, cfg: dict, cwd_base: Optional[str] = None,
               groups: Optional[list] = None) -> Optional[Verdict]:
    cmds = set(cfg.get("protected_cmds", []))
    launch_paths = cfg.get("protected_launch_paths", [])
    groups = groups or []
    for idx, sc in enumerate(simple_cmds):
        tokens = _safe_shlex(sc)
        if not tokens:
            continue
        cw = _command_words(tokens)
        if not cw:
            continue
        tok_idx, head, rest = cw[0]
        # effective cwd for relative-path resolution (cd/pushd in the chain),
        # then fold any leading wrapper chdir (env -C/sudo --chdir) into it.
        cwd, cwd_det = _effective_cwd_after(simple_cmds, idx, cwd_base)
        cwd, cwd_det = _fold_wrapper_cwd(cwd, cwd_det, tokens)
        # fold a PM workspace selector's resolved dir into the effective cwd so a
        # `yarn workspace <ws> exec node dist/index.mjs ...` resolves the relative
        # protected path against the SELECTED workspace.
        cwd, cwd_det = _selector_cwd(head, rest, cfg, cwd, cwd_det)
        # PM `<selector> exec <runtime> <path> …` — route the post-exec runner
        # through the launch logic with the selector-resolved cwd.
        ex_runner, ex_args = _exec_subcommand_after_selector(head, rest)
        if ex_runner is not None:
            if ex_runner in cmds:
                return _block("P1", f"workspace-selected exec of protected command '{ex_runner}'")
            # a recursive/all-workspace (`-r`/`--filter '*'`) exec fans out into
            # EVERY workspace incl. the protected one — fail closed when the exec
            # target is a runtime / build tool (it would run in the protected pkg).
            if (head in PKG_MANAGERS and _explicit_workspace_selector(head, rest) == "<MULTI>"
                    and (ex_runner in RUNTIMES or ex_runner in BUILD_TOOL_BASENAMES)):
                return _block("P1", "recursive/all-workspace exec of a runtime/build (fans into protected workspace)")
            if ex_runner in RUNTIMES:
                ex_pos = _runtime_target(ex_args)
                if ex_pos is not None and _path_matches_cwd(ex_pos, launch_paths, cwd, cwd_det):
                    return _block("P1", "workspace-selected exec runtime launch of protected path")
            if _path_matches_cwd(ex_runner, launch_paths, cwd, cwd_det):
                return _block("P1", "workspace-selected exec of protected launch path")
        # direct basename launch
        if head in cmds:
            return _block("P1", f"launch of protected command '{head}'")
        # runtime launching a protected path: node [opts] <path>
        if head in RUNTIMES:
            tgt = _runtime_target(rest)
            if tgt is not None and _path_matches_cwd(tgt, launch_paths, cwd, cwd_det):
                return _block("P1", "runtime launch of protected path")
            # a preload/execute option VALUE (`--import <path>`, `-r <path>`,
            # `--require=<path>`) executes the protected module even without a
            # script positional (`node --import <protected> -e ""`).
            if _runtime_preload_hits(rest, launch_paths, cwd, cwd_det):
                return _block("P1", "runtime preload/import of protected path")
            # `node --run <script>` (Node script runner) routes to the package
            # script of the effective cwd — treat as a bare script-run via P9/P8.
            nrun = _node_run_script(rest)
            if nrun is not None and head in ("node", "nodejs"):
                if _cwd_in_protected_build_scope(cwd, cwd_det, cfg) or cwd is None or not cwd_det:
                    return _block("P1", "node --run in a protected/indeterminate cwd")
        # direct path execution (./...mjs) — the head IS the path
        full_head = _strip_quotes(tokens[tok_idx]) if tok_idx < len(tokens) else head
        if _path_matches_cwd(full_head, launch_paths, cwd, cwd_det):
            return _block("P1", "direct execution of protected launch path")
        # package-runner exec targets: npx/bunx <cmd>; npm exec/pnpm dlx/etc.
        runner_target, runner_args = _package_runner_invocation(head, rest)
        if runner_target is not None:
            if runner_target in cmds:
                return _block("P1", f"package-runner launch of protected command '{runner_target}'")
            # runner invoking a RUNTIME against a protected path:
            # `npx tsx packages/<cli>/src/index.ts`, `npm exec -- tsx <src>`.
            if runner_target in RUNTIMES:
                rpos = _runtime_target(runner_args)
                if rpos is not None and _path_matches_cwd(rpos, launch_paths, cwd, cwd_det):
                    return _block("P1", "package-runner runtime launch of protected path")
        # xargs executor: `... | xargs [opts] <cmd> [args]` runs <cmd> with the
        # piped input appended as arguments. Treat <cmd> as a virtual launch
        # command-word (basename against protected_cmds; runtime → protected
        # path positional). Covers `echo <subcmd> | xargs <protected-cmd>` and
        # `printf '<protected-path> <subcmd>' | xargs node`.
        if head == "xargs":
            xbase, xargs_after, uses_ph, _det = _xargs_effective_command(rest)
            upstream = _upstream_text_in_group(groups, sc)
            # `xargs -I{} {}` (or bare placeholder): the command is whatever the
            # upstream segment emits — scan upstream for a protected command or
            # launch path.
            if uses_ph:
                if upstream and (_text_carries_protected_cmd(upstream, cmds)
                                 or _text_carries_launch_path(upstream, launch_paths, cwd, cwd_det)):
                    return _block("P1", "xargs placeholder launch of an upstream-piped protected command/path")
            if xbase is not None:
                if xbase in cmds:
                    return _block("P1", f"xargs launch of protected command '{xbase}'")
                if xbase in RUNTIMES:
                    xpos = _runtime_target(xargs_after)
                    if xpos is not None and _path_matches_cwd(xpos, launch_paths, cwd, cwd_det):
                        return _block("P1", "xargs runtime launch of protected path")
                    # `printf '<protected-path> ...' | xargs [env] node` — path
                    # arrives via stdin from the upstream segment.
                    if upstream and _text_carries_launch_path(upstream, launch_paths, cwd, cwd_det):
                        return _block("P1", "xargs runtime launch of an upstream-piped protected path")
                # the xargs target itself is a protected launch path
                if _path_matches_cwd(xbase, launch_paths, cwd, cwd_det):
                    return _block("P1", "xargs execution of protected launch path")
                for a in xargs_after:
                    if _path_matches_cwd(_strip_quotes(a), launch_paths, cwd, cwd_det):
                        return _block("P1", "xargs execution of protected launch path arg")
    return None


def _text_carries_protected_cmd(text: str, cmds: set) -> bool:
    """True if any whitespace token of `text` is a protected command basename."""
    for raw in re.split(r"\s+", text):
        st = os.path.basename(_strip_quotes(raw.strip("'\"")))
        if st in cmds:
            return True
    return False


def _text_carries_launch_path(text: str, launch_paths: list, cwd: Optional[str], cwd_det: bool) -> bool:
    """True if any whitespace-delimited token inside `text` matches a protected
    launch path (absolute, or relative resolved against the effective cwd)."""
    for raw in re.split(r"\s+", text):
        st = _strip_quotes(raw.strip("'\""))
        if not st or st.startswith("-"):
            continue
        if _path_matches_cwd(st, launch_paths, cwd, cwd_det):
            return True
    return False


def _xargs_target(rest: list):
    """Return (index_in_rest, target_command) for `xargs [opts] <cmd> ...`.

    Skips xargs's own options, consuming the operand of those that take one
    (-I/-n/-P/-d/-E/-s/--max-args/etc.). Returns (None, None) if no target
    command word follows (then xargs defaults to echo — not a launch).
    """
    opts_with_arg = frozenset({
        "-I", "-i", "--replace", "-n", "--max-args", "-L", "--max-lines",
        "-P", "--max-procs", "-d", "--delimiter", "-E", "-e", "--eof",
        "-s", "--max-chars", "-a", "--arg-file",
    })
    i = 0
    n = len(rest)
    while i < n:
        t = rest[i]
        st = _strip_quotes(t)
        if t == "--":
            i += 1
            continue
        if t in opts_with_arg:
            i += 2
            continue
        if t.startswith("-") and "=" in t:
            i += 1
            continue
        if t.startswith("-"):
            # bareword flags like -r, -t, -0, -I{} (replace-str fused), -p
            # -I may fuse its replstr: -I{} ; treat as single token
            i += 1
            continue
        return (i, st)
    return (None, None)


_XARGS_REPLSTR_RE = re.compile(r"\{\}")


def _xargs_effective_command(rest: list):
    """Resolve the EFFECTIVE command an `xargs` segment runs.

    Returns (head_basename|None, args_after_head, uses_placeholder, det) where:
      • head_basename is the real command after unwrapping wrapper prefixes
        (sudo/env/nice/…) on the xargs TARGET (so `xargs sudo kill` → 'kill',
        `xargs env node <path>` → 'node');
      • args_after_head EXCLUDES the head;
      • uses_placeholder is True when the target IS the `-I` replacement string
        (e.g. `xargs -I{} {}`) — the command then comes entirely from upstream
        stdin content, so callers must scan the upstream pipeline text.
    """
    xidx, xtgt = _xargs_target(rest)
    if xtgt is None:
        return (None, [], False, True)
    # `-I{}` replacement placeholder used as the command word.
    if _XARGS_REPLSTR_RE.fullmatch(xtgt) or xtgt in ("{}",):
        return (None, [], True, True)
    target_tokens = rest[xidx:]
    cw = _command_words(target_tokens)
    if not cw:
        return (os.path.basename(_strip_quotes(xtgt)), [], False, True)
    _, head, args = cw[0]
    return (head, args, False, True)


# Package-runner options that consume one following operand (so the runner's
# target command is not mistaken for the operand).
_RUNNER_OPTS_WITH_ARG = frozenset({
    "-p", "--package", "-c", "--call", "--node-options", "--node-arg",
})


def _package_runner_invocation(head: str, rest: list):
    """Resolve a package-runner exec/dlx form to (target_basename, args_after).

    Handles npx/bunx and `npm exec`/`pnpm exec|dlx`/`yarn exec|dlx`/`bun x`.
    Consumes runner options that take an operand (e.g. `--package <pkg>`) and the
    `--` terminator, so `npx --package typescript tsc -p x` resolves target=tsc
    (not 'typescript'). Returns (None, []) if not a runner form / no target.
    """
    toks = None
    if head in ("npx", "bunx"):
        toks = rest
    elif head in PKG_MANAGERS:
        i = 0
        while i < len(rest):
            t = rest[i]
            if t in ("exec", "dlx", "x"):
                toks = rest[i + 1:]
                break
            if t in ("run", "run-script"):
                return (None, [])
            i += 1
    if toks is None:
        return (None, [])
    i = 0
    n = len(toks)
    while i < n:
        t = toks[i]
        if t == "--":
            i += 1
            continue
        # PM selector / cwd flags AFTER exec (`npm exec -w cli -- node …`) take a
        # value and are NOT the runner target — consume the flag and its operand.
        if t in ("-w", "--workspace", "--filter", "-F", "--prefix", "-C", "--dir", "--cwd") and i + 1 < n:
            i += 2
            continue
        if any(t.startswith(f + "=") for f in ("--workspace", "--filter", "-F", "--prefix", "-C", "--dir", "--cwd", "-w")):
            i += 1
            continue
        if t in _RUNNER_OPTS_WITH_ARG:
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return (os.path.basename(_strip_quotes(t)), toks[i + 1:])
    return (None, [])


def _package_runner_target(head: str, rest: list) -> Optional[str]:
    """Return the first real command after a package-runner keyword, else None."""
    tgt, _args = _package_runner_invocation(head, rest)
    return tgt


# ── P2 SERVICE_GUARD ─────────────────────────────────────────────────────────

def _p2_service(simple_cmds: list, cfg: dict) -> Optional[Verdict]:
    services = cfg.get("protected_services", [])
    if not services:
        return None
    # match `unit`, `unit.service`, and the template-instance form
    # `unit@instance` / `unit@instance.service` (without matching a longer
    # hyphenated unrelated unit name — the boundary after the instance enforces).
    svc_re = [re.compile(r"(^|[\s=])" + re.escape(s) + r"(@[^\s.=/]*)?(\.service)?(\s|$|\.|=)") for s in services]
    for sc in simple_cmds:
        tokens = _safe_shlex(sc)
        if not tokens:
            continue
        cw = _command_words(tokens)
        if not cw:
            continue
        _, head, rest = cw[0]
        if head not in ("systemctl", "service", "initctl"):
            continue
        if not (any(v in rest for v in SERVICE_VERBS)):
            continue
        joined = " " + " ".join(_strip_quotes(t) for t in rest) + " "
        for rx in svc_re:
            if rx.search(joined):
                return _block("P2", "service-control of a protected unit")
    return None


# ── P3 / P4 mutation guards ──────────────────────────────────────────────────

def _mutation_targets(simple_cmd: str, tokens: list) -> list:
    """Return candidate mutation TARGET paths in a simple command (the bundle /
    statefile / global-bin path families W6/W7/W9/P3/P4/P7 protect). Delegates the
    verb-argv parse to the ONE shared, position-COMPLETE `_mutation_targets_for_verb`
    so this path and STEP0 (config) can never DRIFT — a protected file that is the
    cp/mv/rsync/install DESTINATION (written), the mv/rename SOURCE (moved away /
    removed in place), the rsync `--remove-source-files` SOURCE (moved away), the
    rm/truncate/shred/dd(of=)/tee target, the sed -i/perl -pi in-place target, the
    ln dest, the chmod/chown target, or a `> path` redirect target is ALL caught.
    A cp/plain-rsync SOURCE (copied, source preserved → a read) yields NO target so
    it still ALLOWS (no over-block)."""
    targets = []
    # ALL write-redirect targets (bare/force/fd-prefixed/stdout+stderr, every
    # position) — a non-first or fd-prefixed redirect to a protected path counts.
    targets.extend(_write_redirect_targets(simple_cmd))
    if not tokens:
        return targets
    cw = _command_words(tokens)
    if not cw:
        return targets
    _, head, rest = cw[0]
    targets.extend(_mutation_targets_for_verb(head, list(rest)))
    return targets


def _mutation_target_hits(simple_cmds: list, idx: int, sc: str, tokens: list,
                          globs: list, cwd_base: Optional[str],
                          cfg: Optional[dict] = None) -> bool:
    """True if any mutation target of `sc` matches a protected glob, resolving a
    relative target against the effective cwd (cd chain + wrapper chdir) so
    `cd <protected> && touch dist/index.mjs` and `rm <rel>/dist/index.mjs` hit. A
    shell-GLOB target whose parent CONTAINS a concrete protected dir (cfg-aware) also
    hits (`rm -rf <repo>/packages/*` selecting the protected package)."""
    cwd, cwd_det = _effective_cwd_after(simple_cmds, idx, cwd_base)
    cwd, cwd_det = _fold_wrapper_cwd(cwd, cwd_det, tokens)
    for tgt in _mutation_targets(sc, tokens):
        for cand in _resolve_rel(tgt, cwd, cwd_det):
            if _mutation_cand_hits(cand, globs, cfg, cwd, cwd_det):
                return True
    return False


def _p3_hotfile(simple_cmds: list, cfg: dict, cwd_base: Optional[str] = None) -> Optional[Verdict]:
    hot = cfg.get("protected_hotfiles", [])
    if not hot:
        return None
    for idx, sc in enumerate(simple_cmds):
        tokens = _safe_shlex(sc)
        if _mutation_target_hits(simple_cmds, idx, sc, tokens, hot, cwd_base, cfg):
            return _block("P3", "mutation of protected hot-watched bundle")
    return None


def _p4_statefile(simple_cmds: list, cfg: dict, cwd_base: Optional[str] = None) -> Optional[Verdict]:
    state = cfg.get("protected_statefiles", [])
    if not state:
        return None
    for idx, sc in enumerate(simple_cmds):
        tokens = _safe_shlex(sc)
        if _mutation_target_hits(simple_cmds, idx, sc, tokens, state, cwd_base, cfg):
            return _block("P4", "mutation of protected state file")
    return None


# ── P5 ENDPOINT_GUARD ────────────────────────────────────────────────────────

LOOPBACK_RE = re.compile(r"(127\.0\.0\.1|localhost|\[::1\]|::1)", re.IGNORECASE)
# Raw byte-stream clients: the request line (incl. the control path) is supplied
# on STDIN, so the path legitimately arrives from an UPSTREAM pipeline segment.
RAW_SOCKET_HEADS = frozenset({"nc", "ncat", "netcat", "socat", "telnet"})
# Structured HTTP clients: the request path is part of the client's OWN argv (a
# URL or a stdin-body flag), NOT merely co-present somewhere in the pipeline.
HTTP_CLIENT_HEADS = frozenset({"curl", "wget", "http", "https", "httpie"})
NET_HEADS = RAW_SOCKET_HEADS | HTTP_CLIENT_HEADS


def _endpoint_path_in(text: str, paths: list) -> bool:
    for ep in paths:
        if re.search(re.escape(ep) + r"(\b|/|\"|'|\s|$)", text):
            return True
    return False


def _http_reads_stdin_body(sc: str) -> bool:
    """True if an HTTP client is told to read its request body from stdin, so a
    control path piped in upstream would actually be sent."""
    return bool(re.search(r"(--data-binary|--data|-d)\s+@-|--data-binary\s+@/dev/stdin", sc))


def _p5_endpoint(ctx: "Context") -> Optional[Verdict]:
    """Pipeline-group + segment-ORDER aware control-endpoint guard.

    A loopback control shutdown can be split across pipeline segments — the
    control path travels in one segment's content (e.g. `printf 'POST /stop'`)
    and a raw byte-stream client (nc/ncat/netcat/socat/telnet) in a connected
    DOWNSTREAM segment (`| nc 127.0.0.1 <port>`) sends it via stdin. BLOCK when,
    within ONE pipeline group:
      • a RAW socket client to a loopback host has the protected endpoint path
        in ITS OWN segment OR in an UPSTREAM segment (stdin source), OR
      • an HTTP client to a loopback host carries the protected endpoint path in
        its OWN argv, OR is told to read its body from stdin while the path is
        present upstream.
    This is order-aware so a benign `curl …/health | grep /stop` (endpoint text
    only DOWNSTREAM, never sent) and `grep /stop file | curl …/health` (endpoint
    text in an unrelated upstream filter, HTTP client argv clean) stay ALLOWED.
    """
    # Read the per-evaluation inputs from the shared Context. Local aliases keep
    # the body below a byte-for-byte behavior match — the Context adoption is a
    # pure relocation of how groups / cfg arrive, nothing else.
    groups = ctx.groups
    cfg = ctx.cfg
    paths = cfg.get("protected_endpoint_paths", [])
    if not paths:
        return None
    for group in groups:
        if not _endpoint_path_in(" ".join(group), paths):
            continue
        for k, sc in enumerate(group):
            tokens = _safe_shlex(sc)
            if not tokens:
                continue
            cw = _command_words(tokens)
            if not cw:
                continue
            _, head, _rest = cw[0]
            if head not in NET_HEADS or not LOOPBACK_RE.search(sc):
                continue
            upstream_text = " ".join(group[:k])
            own_has_ep = _endpoint_path_in(sc, paths)
            upstream_has_ep = _endpoint_path_in(upstream_text, paths)
            if head in RAW_SOCKET_HEADS:
                # stdin-fed: endpoint in this segment or any upstream segment
                if own_has_ep or upstream_has_ep:
                    return _block("P5", "loopback request to a protected control path")
            else:  # HTTP client
                if own_has_ep:
                    return _block("P5", "loopback request to a protected control path")
                if upstream_has_ep and _http_reads_stdin_body(sc):
                    return _block("P5", "loopback request to a protected control path (stdin body)")
    return None


# ── P6 PROCKILL_GUARD ────────────────────────────────────────────────────────

# Minimum length for a derived process-selector token. A 1-2 char fragment is too
# generic (it would overlap unrelated process names), so derived tokens shorter
# than this are dropped. Full registered idents are kept regardless of length.
_PROC_TOKEN_MIN_LEN = 3

# Generic PID-selection program basenames: a pipeline carrying one of these next
# to a kill executor resolves PIDs by name/pattern (the selector mechanism). NO
# project names — generic POSIX/utility process-listing tools.
_PROC_SELECTOR_HEADS = frozenset({"pgrep", "grep", "egrep", "fgrep", "rg", "ps",
                                  "pidof", "pgrep", "ag", "ack", "lsof"})


def _protected_proc_tokens(cfg: dict) -> list:
    """Generic, project-name-FREE set of process-selector fragments a good-faith
    kill-pipeline selector (`pgrep -f X`, `grep X`, `pkill -f X`, `ps … | grep X`,
    `kill $(… X)`) would use to find the protected daemon. ALL values are read from
    the data file — the engine enumerates none. Derived from:
      • each registered `protected_proc_idents` entry (full + each distinctive
        path/whitespace/dash-delimited segment, e.g. `entry.mjs`, `<pkg>-cli`,
        `<svc>`, `daemon` from `packages/<pkg>-cli/dist/entry.mjs` / `<svc>-daemon`),
      • each `protected_cmds` basename (the bare command word an operator types),
      • each `protected_launch_paths` basename + its non-glob path segments (so the
        bundle basename `entry.mjs` and the package stem are derivable).
    Short (<3 char) derived fragments are dropped to avoid overlapping unrelated
    process names; the FULL registered idents are always kept. This is the data the
    kill guard matches a selector against (substring overlap, EITHER direction)."""
    toks = set()

    def _add(raw: str, *, allow_short: bool = False):
        s = _strip_quotes(str(raw)).strip()
        if not s or s.startswith("-"):
            return
        if allow_short or len(s) >= _PROC_TOKEN_MIN_LEN:
            toks.add(s)

    def _segments(raw: str):
        # split a path/ident into distinctive segments on /, whitespace, and dash;
        # drop pure-glob and generic structural segments (`**`, `*`, `dist`, `src`,
        # `bin`, `packages`, `node_modules`) that are not process-distinctive.
        generic = {"dist", "src", "bin", "lib", "packages", "node_modules",
                   "scripts", "build", "out", "", "*", "**"}
        for part in re.split(r"[\s/]+", _strip_quotes(str(raw))):
            part = part.strip()
            if not part or part in generic or set(part) <= {"*"}:
                continue
            yield part
            # further split a dash-joined name (`<svc>-daemon` -> `<svc>`,`daemon`,
            # `<svc>-daemon`) so the stem fragments are derivable too.
            if "-" in part:
                for sub in part.split("-"):
                    if sub and sub not in generic:
                        yield sub

    for ident in cfg.get("protected_proc_idents", []):
        _add(ident, allow_short=True)  # keep the FULL ident regardless of length
        for seg in _segments(ident):
            _add(seg)
    for cmd in cfg.get("protected_cmds", []):
        _add(os.path.basename(_strip_quotes(str(cmd))))
    for lp in cfg.get("protected_launch_paths", []):
        base = os.path.basename(_strip_quotes(str(lp)))
        if base and "*" not in base:
            _add(base)
        for seg in _segments(lp):
            _add(seg)
    return [t for t in toks if t]


def _selector_overlaps_protected(text: str, ptokens: list, cmds: set) -> bool:
    """True if `text` (a kill-pipeline selector / group text / command-substitution)
    OVERLAPS any protected process token — a substring match in EITHER direction
    (the operator's fragment is a substring OF a token, or a token is a substring of
    the operator's fragment) — OR contains a protected command basename as a
    whitespace/boundary-delimited word. The either-direction overlap closes the
    directional asymmetry that let `pgrep -f <stem> | xargs kill` leak while the
    full-ident form blocked. A selector naming an UNRELATED process (`pgrep -f
    nginx`) overlaps nothing, and a bare `kill <pid>` carries no selector text, so
    both stay ALLOWED."""
    if not text:
        return False
    for tok in ptokens:
        if not tok:
            continue
        # either-direction substring overlap: token in text OR text-fragment in
        # token. The whitespace/quote-delimited words of the text are tested so a
        # bare selector word that is itself a substring of a longer registered
        # ident (`<stem>` ⊂ `<stem>-daemon`) overlaps.
        if tok in text:
            return True
    # word-level: any selector word that overlaps a protected token in EITHER
    # direction, or equals a protected command basename.
    for raw in re.split(r"[\s'\"|;&()$<>]+", text):
        w = _strip_quotes(raw).strip().lstrip("-")
        if not w or len(w) < _PROC_TOKEN_MIN_LEN:
            continue
        if w in cmds:
            return True
        for tok in ptokens:
            if not tok:
                continue
            # `w` is a fragment OF a registered token (`<stem>` ⊂ `<stem>-daemon`),
            # or a registered token is a fragment of `w` (already covered above,
            # but kept for the word-scoped path).
            if w in tok or tok in w:
                return True
    return False


def _is_kill_executor(head: str, rest: list) -> bool:
    """True if this simple command terminates processes."""
    if head in KILL_VERBS:
        return True
    # `xargs [opts] [wrapper] kill|pkill|killall ...` — unwrap wrappers on the
    # xargs target so `xargs sudo kill` / `xargs env kill` resolve to 'kill'.
    if head == "xargs":
        xbase, _xa, uses_ph, _det = _xargs_effective_command(rest)
        if xbase is not None and xbase in KILL_VERBS:
            return True
        # `xargs -I{} kill {}` style placeholder kill — the literal kill verb is
        # in the args even when the target parse lands on the placeholder.
        if uses_ph and any(os.path.basename(_strip_quotes(t)) in KILL_VERBS for t in rest):
            return True
    # `fuser -k`
    if head == "fuser" and ("-k" in rest or any(t.startswith("-") and "k" in t for t in rest)):
        return True
    return False


def _p6_prockill(groups: list, cfg: dict) -> Optional[Verdict]:
    """Pipeline-group + command-substitution aware process-kill guard.

    The canonical daemon-kill idioms split the protected identifier and the kill
    executor across pipeline segments or a command substitution:
      ps aux | grep <ident> | awk '{print $2}' | xargs kill
      pgrep -f <ident> | xargs pkill
      kill $(ps aux | grep <ident> | awk '{print $2}')
    BLOCK when, within ONE pipeline group, a kill executor is present AND a
    protected identifier appears anywhere connected to it — in any segment of
    the same group, or inside a kill's $()/`` command substitution.
    """
    idents = cfg.get("protected_proc_idents", [])
    statefiles = cfg.get("protected_statefiles", [])
    cmds = set(cfg.get("protected_cmds", []))
    ptokens = _protected_proc_tokens(cfg)
    if not idents and not statefiles and not ptokens:
        return None

    def has_ident(text: str) -> bool:
        # EITHER-direction overlap against the data-file-derived protected-process
        # tokens (closes the directional asymmetry: a kill whose selector is a bare
        # protected command-word / a fragment of a registered ident now BLOCKS),
        # plus the original full-ident substring match as a subset.
        return _selector_overlaps_protected(text, ptokens, cmds)

    def reads_statefile(text: str) -> bool:
        """True if any whitespace token of `text` resolves to a protected
        statefile path. A kill target derived from `$(jq .pid <statefile>)` is a
        protected-PID kill even though the statefile path is not a proc-ident."""
        if not statefiles:
            return False
        for raw in re.split(r"\s+", text):
            st = _strip_quotes(raw.strip("'\""))
            # strip a leading input-redirection prefix (`<path`, `0<path`, `<<<`)
            # so `jq .pid <PROTECTED_STATEFILE` (fused redirect) is recognized.
            st = re.sub(r"^\d*<+", "", st)
            if not st or st.startswith("-"):
                continue
            if _path_matches_any(st, statefiles):
                return True
        return False

    def full_ident_in(text: str) -> bool:
        # the ORIGINAL exact full-ident substring match (the conservative subset),
        # used for a plain literal-`kill`-only group so a bare `kill <bareword>`
        # (no PID, no name-selector mechanism) does NOT over-block — `kill` takes a
        # PID/jobspec, not a process name, so its bareword is a benign operand.
        return any(ident in text for ident in idents)

    for group in groups:
        kill_present = False
        # a SELECTION MECHANISM is present when the group resolves PIDs by name /
        # pattern: a name-matching kill verb (`pkill`/`killall`/`fuser -k`), a
        # `pgrep`/`grep`/`ps` selector segment, OR a command substitution feeding
        # the kill. Plain literal `kill <bareword>` with NO such mechanism is a
        # PID/jobspec kill (`kill <name>` is a benign error), so the broadened
        # either-direction overlap is applied ONLY when a selector mechanism exists.
        has_selector_mechanism = False
        kill_subst_carries_ident = False
        for sc in group:
            tokens = _safe_shlex(sc)
            if not tokens:
                continue
            cw = _command_words(tokens)
            if not cw:
                continue
            _, head, rest = cw[0]
            hbase = os.path.basename(_strip_quotes(head))
            # HEAD-AGNOSTIC: scan ALL exec-position token basenames so a selector /
            # kill executor BEHIND a novel wrapper (`weirdwrap pgrep -f X`,
            # `… | weirdwrap xargs kill`) is still seen — UNLESS the segment is a
            # pure read/inspect command (then its tokens are DATA, not executors).
            exec_bases = ([os.path.basename(_strip_quotes(t)) for _i, t in _anchor_exec_tokens(tokens)]
                          if not _is_inspection_command(hbase, rest) else [hbase])
            if (hbase in _PROC_SELECTOR_HEADS
                    or any(b in _PROC_SELECTOR_HEADS for b in exec_bases)
                    or _command_substitutions(sc)):
                has_selector_mechanism = True
            # a kill executor as the segment head OR anywhere in exec position
            # (head-agnostic), so a wrapped `weirdwrap pkill`/`weirdwrap xargs kill`
            # is detected. `xargs … kill` is recognized by `_is_kill_executor`.
            seg_kill = _is_kill_executor(head, rest) or any(b in KILL_VERBS for b in exec_bases)
            if seg_kill:
                kill_present = True
                # name/pattern-matching kill verbs select BY NAME — the kill verb
                # itself is the selector mechanism (head OR exec-position).
                if (hbase in ("pkill", "killall", "fuser")
                        or any(b in ("pkill", "killall", "fuser") for b in exec_bases)):
                    has_selector_mechanism = True
                # `kill $(<pipeline naming ident>)` / `kill $(jq .pid
                # <statefile>)` — inspect this command's substitutions for a
                # protected identifier OR a read of a protected statefile.
                for sub in _command_substitutions(sc):
                    if has_ident(sub) or reads_statefile(sub):
                        kill_subst_carries_ident = True
        if not kill_present:
            continue
        group_text = " ".join(group)
        # selector mechanism present -> broadened either-direction overlap;
        # otherwise fall back to the conservative full-ident substring match so a
        # bare `kill <bareword>` stays ALLOWED.
        ident_hit = has_ident(group_text) if has_selector_mechanism else full_ident_in(group_text)
        if ident_hit or kill_subst_carries_ident or reads_statefile(group_text):
            return _block("P6", "process kill carrying a protected identifier")
    return None


# ── P7 GLOBALBIN_GUARD ───────────────────────────────────────────────────────

def _p7_globalbin(simple_cmds: list, cfg: dict) -> Optional[Verdict]:
    gbins = cfg.get("protected_global_bins", [])
    for sc in simple_cmds:
        tokens = _safe_shlex(sc)
        if not tokens:
            continue
        cw = _command_words(tokens)
        if not cw:
            continue
        _, head, rest = cw[0]
        if head in PKG_MANAGERS:
            is_global = any(t in ("-g", "--global") for t in rest)
            is_link = any(t in ("link", "unlink") for t in rest)
            if is_global or is_link:
                return _block("P7", "global package install/link")
        # writes to protected global bin paths (any mutation head)
        for tgt in _mutation_targets(sc, tokens):
            if gbins and _path_matches_any(tgt, gbins):
                return _block("P7", "write to a protected global bin path")
    return None


# ── P8 BUILD_GUARD ───────────────────────────────────────────────────────────

def _cwd_under_build_path(cwd: Optional[str], cwd_det: bool, bpaths: list) -> bool:
    """True if a determinate effective cwd resolves under a protected build dir."""
    if not cwd or not cwd_det:
        return False
    return _path_under_any(cwd, bpaths)


def _cwd_in_protected_build_scope(cwd: Optional[str], cwd_det: bool, cfg: dict) -> bool:
    """True if a determinate effective cwd is inside a protected build package OR
    at/under a protected monorepo root manifest. A bare build-mode invocation
    (tsc -b) in either scope rebuilds the protected bundle (directly or via
    project references), so it is in-scope for the build guard."""
    if not cwd or not cwd_det:
        return False
    if _path_under_any(cwd, cfg.get("protected_build_paths", [])):
        return True
    # the monorepo ROOT exactly (where a project-referenced `tsc -b` rebuilds the
    # protected package); a non-protected sub-package's own cwd is NOT in scope.
    cwd_n = os.path.normpath(cwd)
    for root in cfg.get("protected_root_manifest_paths", []):
        if cwd_n == os.path.normpath(root):
            return True
    return False


def _p8_build(simple_cmds: list, cfg: dict, cwd_base: Optional[str] = None) -> Optional[Verdict]:
    ws = set(cfg.get("protected_build_workspaces", []))
    bpaths = cfg.get("protected_build_paths", [])
    for idx, sc in enumerate(simple_cmds):
        tokens = _safe_shlex(sc)
        if not tokens:
            continue
        cw = _command_words(tokens)
        if not cw:
            continue
        _, head, rest = cw[0]
        # effective cwd: cd/pushd in the chain + a leading wrapper chdir + a PM
        # workspace selector's resolved dir (so `npm -w <ws> exec tsc -p
        # tsconfig.json` resolves the protected build cwd).
        cwd, cwd_det = _effective_cwd_after(simple_cmds, idx, cwd_base)
        cwd, cwd_det = _fold_wrapper_cwd(cwd, cwd_det, tokens)
        cwd, cwd_det = _selector_cwd(head, rest, cfg, cwd, cwd_det)
        cwd_in_build = _cwd_under_build_path(cwd, cwd_det, bpaths)
        # (a) explicit: build naming a protected workspace
        if head in PKG_MANAGERS and "build" in rest:
            sel = _explicit_workspace_selector(head, rest)
            if sel is not None and sel in ws:
                return _block("P8", "explicit build of a protected workspace")
        # (a) build tool co-occurring with a protected build path (token, fused
        # --flag=path value, or cwd) — relative paths resolved against cwd.
        if head in BUILD_TOOL_BASENAMES:
            if _any_token_under_incl_flagvalue(rest, cfg, cwd, cwd_det) or cwd_in_build:
                return _block("P8", "build tool co-occurring with a protected build path")
            if (_build_mode_flag_present(rest)
                    and not _explicit_nonprotected_build_target(rest, cfg, cwd, cwd_det)
                    and (cwd is None or not cwd_det
                         or _cwd_in_protected_build_scope(cwd, cwd_det, cfg))):
                # bare build-mode (tsc -b / --build / -w) with cwd in a protected
                # package/root or indeterminate cwd -> fail-closed rebuild, UNLESS
                # an explicit project target proves a non-protected build.
                return _block("P8", "build-mode flag with protected/indeterminate cwd")
        if head in PKG_MANAGERS and "build" in rest:
            if _any_token_under_incl_flagvalue(_strip_selector_tokens(rest), cfg, cwd, cwd_det):
                return _block("P8", "build co-occurring with a protected build path")
        # package-runner build: npx/bunx AND npm exec/pnpm exec/yarn exec/bun x
        # running a build tool, against a protected build path (token or cwd).
        rtgt = _package_runner_target(head, rest)
        if rtgt is not None and os.path.basename(rtgt) in BUILD_TOOL_BASENAMES:
            # tokens AFTER the build-tool target (e.g. `-p <path>` for tsc)
            after = _tokens_after_runner_target(head, rest)
            if (_any_token_under_incl_flagvalue(after, cfg, cwd, cwd_det)
                    or _any_token_under_incl_flagvalue(rest, cfg, cwd, cwd_det) or cwd_in_build):
                return _block("P8", "package-runner build co-occurring with a protected build path")
            if (_build_mode_flag_present(after)
                    and not _explicit_nonprotected_build_target(after, cfg, cwd, cwd_det)
                    and (cwd is None or not cwd_det
                         or _cwd_in_protected_build_scope(cwd, cwd_det, cfg))):
                return _block("P8", "package-runner build-mode flag with protected/indeterminate cwd")
    return None


# Build-mode flags that produce/refresh the bundle without an explicit path
# argument (incremental project build / watch). When present, the effective cwd
# decides whether the protected bundle is the target.
_BUILD_MODE_FLAGS = frozenset({"-b", "--build", "-w", "--watch"})


def _build_mode_flag_present(tokens: list) -> bool:
    for t in tokens:
        st = _strip_quotes(t)
        if st in _BUILD_MODE_FLAGS:
            return True
    return False


def _strip_selector_tokens(rest: list) -> list:
    """Drop workspace/filter/cwd SELECTOR flags and their values from a PM arg
    list, so a selector value (`--filter ./packages/<pkg>`) is not mis-scanned as
    a build-path target (the selector dir is folded into the effective cwd
    separately)."""
    out = []
    i = 0
    sel_flags = ("-w", "--workspace", "--filter", "-F", "--prefix", "-C", "--dir", "--cwd")
    while i < len(rest):
        t = rest[i]
        if t in ("workspace", "workspaces") and i + 1 < len(rest):
            i += 2
            continue
        if t in sel_flags and i + 1 < len(rest):
            i += 2
            continue
        if any(t.startswith(f + "=") for f in sel_flags):
            i += 1
            continue
        out.append(t)
        i += 1
    return out


def _p8_explicit_protected_path(simple_cmds: list, cfg: dict, cwd_base: Optional[str] = None) -> Optional[Verdict]:
    """The explicit-path subset of P8: BLOCK only when a build invocation's path
    token or path-valued flag RHS resolves DETERMINATELY under a protected build
    path. No bare-verb / cwd fallback (so this can run after a P9 ALLOW without
    re-introducing over-blocks)."""
    bpaths = cfg.get("protected_build_paths", [])
    if not bpaths:
        return None
    for idx, sc in enumerate(simple_cmds):
        tokens = _safe_shlex(sc)
        if not tokens:
            continue
        cw = _command_words(tokens)
        if not cw:
            continue
        _, head, rest = cw[0]
        cwd, cwd_det = _effective_cwd_after(simple_cmds, idx, cwd_base)
        cwd, cwd_det = _fold_wrapper_cwd(cwd, cwd_det, tokens)
        cwd, cwd_det = _selector_cwd(head, rest, cfg, cwd, cwd_det)
        is_build = (head in BUILD_TOOL_BASENAMES
                    or (head in PKG_MANAGERS and "build" in rest)
                    or (_package_runner_target(head, rest) is not None
                        and os.path.basename(_package_runner_target(head, rest) or "") in BUILD_TOOL_BASENAMES)
                    or "build" in [_strip_quotes(t) for t in rest])
        if not is_build:
            continue
        if _any_token_under_incl_flagvalue(_strip_selector_tokens(rest), cfg, cwd, cwd_det):
            return _block("P8", "explicit protected build-path argument")
    return None


def _tokens_after_runner_target(head: str, rest: list) -> list:
    """Tokens following the package-runner's target command word (e.g. after
    `tsc` in `pnpm exec tsc -p <path>`)."""
    if head in ("npx", "bunx"):
        toks = rest
    elif head in PKG_MANAGERS:
        toks = None
        for i, t in enumerate(rest):
            if t in ("exec", "dlx", "x"):
                toks = rest[i + 1:]
                break
        if toks is None:
            return []
    else:
        return []
    # skip flags before the target command word, then return everything after it
    i = 0
    while i < len(toks):
        st = _strip_quotes(toks[i])
        if st.startswith("-") or st == "--":
            i += 1
            continue
        return toks[i + 1:]
    return []


def _p8_bare_build(simple_cmds: list, cfg: dict) -> Optional[Verdict]:
    """Bare-build arm — only reached when P9 has not already DENIED/ALLOWED.
    Kept separate so P9's allow-set (explicit non-protected workspace) wins first.
    """
    bare = bool(cfg.get("bare_build_guard", False))
    if not bare:
        return None
    for sc in simple_cmds:
        tokens = _safe_shlex(sc)
        if not tokens:
            continue
        cw = _command_words(tokens)
        if not cw:
            continue
        _, head, rest = cw[0]
        if head in BUILD_TOOL_BASENAMES and not any(t.startswith("-") and t not in ("-p",) for t in rest):
            # bare pkgroll/tsup/tsc with no explicit non-protected path
            return _block("P8b", "bare build tool")
    return None


# Sentinel prefix marking a selector that is a DETERMINATE filesystem PATH
# filter (`--filter ./packages/x`), resolved to a manifest dir at use sites.
_PATH_FILTER_PREFIX = "<PATH>"


def _classify_filter_value(val: str) -> str:
    """Classify a pnpm/yarn `--filter` value.

    • A genuine glob / ellipsis / brace selector (`*`, `?`, `{`, `...`, trailing
      `^`/`~` dependency selectors) fans out → `<MULTI>` (fail-closed).
    • A deterministic filesystem PATH filter (`./packages/x`, `packages/x`, `.`)
      → `<PATH>./packages/x` so the use site resolves it to a manifest dir.
    • A bare package-NAME filter (`some-pkg`) → returned as-is for name
      resolution.
    """
    if any(ch in val for ch in ("*", "?", "{", "}")) or val.startswith("...") or val.endswith("...") or "..." in val:
        return "<MULTI>"
    # a scoped package NAME (`@scope/name`) contains a slash but is a name, not a
    # filesystem path — classify it as a name selector (resolved via metadata).
    if val.startswith("@") and val.count("/") == 1 and not val.startswith("@/"):
        return val
    # path-like: contains a slash, or is '.'/'..', or starts with './' or '../'
    if "/" in val or val in (".", ".."):
        return _PATH_FILTER_PREFIX + val
    # otherwise a package name (or name with a leading scope '@org/...' which
    # contains '/' and is handled above). A trailing dependency selector ('^'/'~')
    # is a fan-out -> MULTI.
    if val.endswith("^") or val.endswith("~") or val.startswith("^") or val.startswith("~"):
        return "<MULTI>"
    return val


def _explicit_workspace_selector(pm_head: str, rest: list) -> Optional[str]:
    """Return the workspace SELECTOR token if an explicit selector is present.
    Returns None if no explicit single-workspace selector. Returns a sentinel
    '<MULTI>' for recursive/all-workspace forms, or '<PATH>...' for a
    deterministic path filter.
    """
    i = 0
    while i < len(rest):
        t = rest[i]
        if t == "workspace" and i + 1 < len(rest):
            return _strip_quotes(rest[i + 1])
        if t == "workspaces":
            return "<MULTI>"
        if t in ("-w", "--workspace") and i + 1 < len(rest):
            return _strip_quotes(rest[i + 1])
        if t.startswith("--workspace="):
            return _strip_quotes(t.split("=", 1)[1])
        if t in ("--filter", "-F") and i + 1 < len(rest):
            return _classify_filter_value(_strip_quotes(rest[i + 1]))
        if t.startswith("--filter=") or t.startswith("-F="):
            return _classify_filter_value(_strip_quotes(t.split("=", 1)[1]))
        if t in ("--workspaces", "-ws"):
            return "<MULTI>"
        if t in ("-r", "--recursive"):
            return "<MULTI>"
        i += 1
    return None


# ── P9 PKGSCRIPT_GUARD (default-deny) ────────────────────────────────────────

def _resolve_path_filter_manifest(path_val: str, cfg: dict, effective_cwd: Optional[str]):
    """Resolve a `<PATH>` filter value (a directory) to (manifest_dir,
    is_protected, scripts_set, determinate). The directory is resolved against
    the known monorepo roots and the effective cwd, then its package.json is
    read. A protected dir (or one with no resolvable manifest) fails closed."""
    if any(ch in path_val for ch in ("$", "`")):
        return (None, None, None, False)
    # Resolve a relative path filter against the INVOKING cwd FIRST (so `/other`
    # running `--filter ./packages/<pkg>` resolves to /other/..., not a protected
    # root). Fall back to the protected roots only when there is no cwd.
    candidate_bases = []
    if effective_cwd:
        candidate_bases.append(effective_cwd)
    candidate_bases.extend(cfg.get("protected_root_manifest_paths", []))
    tried = []
    if os.path.isabs(path_val):
        tried.append(os.path.normpath(path_val))
    else:
        for base in candidate_bases:
            tried.append(os.path.normpath(os.path.join(base, path_val)))
    for d in tried:
        man = os.path.join(d, "package.json")
        is_protected = (
            _dir_is_protected_pkg(d, cfg)
            or os.path.normpath(d) in [os.path.normpath(p) for p in cfg.get("protected_root_manifest_paths", [])]
        )
        if os.path.isfile(man):
            try:
                with open(man, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                data = {}
            name = data.get("name")
            if name is not None:
                is_protected = is_protected or name in set(cfg.get("protected_script_workspaces", []))
            scripts = set((data.get("scripts") or {}).keys())
            return (d, is_protected, scripts, True)
        if is_protected:
            # protected dir even if manifest unreadable -> deny determinately
            return (d, True, set(), True)
    return (None, None, None, False)


def _resolve_workspace_manifest(selector: str, cfg: dict, effective_cwd: Optional[str]):
    """Resolve a workspace selector to (manifest_dir, is_protected, scripts_set,
    determinate). Uses workspace metadata by reading package.json files under the
    known monorepo roots. Returns (None, None, None, False) if unresolvable.
    """
    if selector.startswith(_PATH_FILTER_PREFIX):
        return _resolve_path_filter_manifest(selector[len(_PATH_FILTER_PREFIX):], cfg, effective_cwd)
    roots = cfg.get("protected_root_manifest_paths", [])
    search_roots = list(roots)
    if effective_cwd:
        search_roots.append(effective_cwd)
    seen = set()
    for root in search_roots:
        try:
            pkgs_dir = os.path.join(root, "packages")
            if not os.path.isdir(pkgs_dir):
                continue
            for entry in os.listdir(pkgs_dir):
                man = os.path.join(pkgs_dir, entry, "package.json")
                if man in seen:
                    continue
                seen.add(man)
                try:
                    with open(man, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                except (OSError, ValueError):
                    continue
                name = data.get("name")
                if name == selector:
                    is_protected = (
                        name in set(cfg.get("protected_script_workspaces", []))
                        or _dir_is_protected_pkg(os.path.dirname(man), cfg)
                    )
                    scripts = set((data.get("scripts") or {}).keys())
                    return (os.path.dirname(man), is_protected, scripts, True)
        except OSError:
            continue
    # selector did not resolve to any known workspace -> indeterminate
    return (None, None, None, False)


def _effective_manifest_for_cwd(cwd: Optional[str], cfg: dict):
    """Walk up from cwd to find the nearest package.json. Returns
    (manifest_dir, is_protected_or_root, scripts_set, determinate)."""
    if not cwd:
        return (None, None, None, False)
    proots = [os.path.normpath(p) for p in cfg.get("protected_root_manifest_paths", [])]
    spaths = cfg.get("protected_script_paths", [])
    d = os.path.normpath(cwd)
    while True:
        man = os.path.join(d, "package.json")
        scripts = None
        exists = os.path.isfile(man)
        if exists:
            try:
                with open(man, "r", encoding="utf-8") as fh:
                    scripts = set((json.load(fh).get("scripts") or {}).keys())
            except (OSError, ValueError):
                scripts = set()
        is_protected_root = d in proots
        is_protected_path = _dir_is_protected_pkg(d, cfg)
        if exists or is_protected_root:
            return (d, (is_protected_root or is_protected_path), scripts or set(), True)
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return (None, None, None, False)


def _p9_pkgscript(simple_cmds: list, cfg: dict, cwd_base: Optional[str] = None) -> Optional[Verdict]:
    if cfg.get("script_run_policy") != "default_deny":
        return None
    non_protected = set(cfg.get("non_protected_workspaces", []))
    safe_allow = set(cfg.get("safe_script_allowlist", []))
    protected_cmds = set(cfg.get("protected_cmds", []))

    for idx, sc in enumerate(simple_cmds):
        tokens = _safe_shlex(sc)
        if not tokens:
            continue
        cw = _command_words(tokens)
        if not cw:
            continue
        _, head, rest = cw[0]
        if head not in PKG_MANAGERS:
            continue
        # (A) head-level meta query -> allow this invocation
        if _is_meta_query(head, rest):
            continue
        # exec/dlx/runner forms -> P1 owns them (resolve protected basename)
        runner_target = _package_runner_target(head, rest)
        if runner_target is not None:
            if runner_target in protected_cmds:
                return _block("P9", "package-runner reaching a protected command")
            # non-protected exec target: not a script-run; allow
            continue
        # A runner keyword (exec/dlx/x) with NO resolvable target (e.g. only a
        # `-c <payload>` form, or selector+exec already handled by P1) is a
        # runner form, NOT a bare script-run — P9 abstains so it is not
        # mis-classified as a protected-cwd script (the `-c` payload is
        # recursively evaluated separately).
        if _first_subcommand(head, rest) in ("exec", "dlx", "x"):
            continue

        # compute effective cwd from cd/pushd in the chain, then fold a leading
        # wrapper chdir (env -C/sudo --chdir) so it participates in manifest
        # resolution like cd/--cwd (else legitimate `env -C <non-protected-ws>
        # yarn <script>` would over-block), then apply pm --cwd flags.
        cwd, cwd_det = _effective_cwd_after(simple_cmds, idx, cwd_base)
        cwd, cwd_det = _fold_wrapper_cwd(cwd, cwd_det, tokens)
        pm_cwd, pm_cwd_det = _pm_cwd_flag(head, rest)
        if pm_cwd is not None:
            if pm_cwd_det:
                if os.path.isabs(pm_cwd):
                    cwd = os.path.normpath(pm_cwd)
                else:
                    cwd = os.path.normpath(os.path.join(cwd, pm_cwd)) if cwd else os.path.normpath(pm_cwd)
            else:
                cwd_det = False

        selector = _explicit_workspace_selector(head, rest)

        # (D) explicit selector present
        if selector is not None:
            if selector == "<MULTI>":
                return _block("P9", "recursive/all-workspace run (no single selector)")
            man_dir, is_protected, scripts, det = _resolve_workspace_manifest(selector, cfg, cwd)
            if not det:
                # selector did not resolve -> fail closed
                return _block("P9", "unresolvable workspace selector")
            if is_protected:
                return _block("P9", "run naming a protected workspace")
            # non-protected workspace: classify the post-selector subcommand
            post = _post_selector_tokens(head, rest)
            verdict = _classify_post_selector(post, scripts, safe_allow, protected_cmds,
                                              _under_protected_monorepo(man_dir, cfg))
            if verdict is not None:
                return verdict
            # allowed
            continue

        # (B)/(E) no explicit selector. Dependency built-in?
        sub = _first_subcommand(head, rest)
        if sub in DEP_BUILTINS:
            # dependency op: allowed unless effective manifest is protected w/o --ignore-scripts
            man_dir, is_protected, scripts, det = _effective_manifest_for_cwd(cwd, cfg)
            if not det:
                # default (repo) cwd unknown — dependency ops at unknown cwd are allowed
                # (they manage node_modules; build/dist rewrite owned by P8, global by P7)
                continue
            if is_protected and "--ignore-scripts" not in rest:
                return _block("P9", "dependency op in a protected manifest without --ignore-scripts")
            continue
        # npm lifecycle shorthand: npm start/stop/restart/test
        if head == "npm" and sub in DEP_SHORTHAND_NPM:
            return _resolve_bare_script(sub, cwd, cwd_det, cfg, safe_allow, protected_cmds)
        # explicit run / run-script keyword
        script_tok = None
        if sub in ("run", "run-script"):
            script_tok = _token_after(rest, sub)
        elif sub is not None and sub not in DEP_BUILTINS and not sub.startswith("-"):
            # bare form: `yarn <script>` / `pnpm <script>` / `bun <script>`
            script_tok = sub
        if script_tok is None:
            # `yarn` alone with no script -> runs default? treat as bare script-run -> fail closed if protected cwd
            return _resolve_bare_script(None, cwd, cwd_det, cfg, safe_allow, protected_cmds)
        return _resolve_bare_script(script_tok, cwd, cwd_det, cfg, safe_allow, protected_cmds)
    return None


def _pm_cwd_flag(head: str, rest: list):
    """Extract a PM cwd flag value. Returns (path|None, determinate)."""
    flags_one = {
        "yarn": ("--cwd",),
        "npm": ("--prefix", "-C"),
        "bun": ("--cwd",),
        "pnpm": ("-C", "--dir"),
    }.get(head, ())
    i = 0
    while i < len(rest):
        t = rest[i]
        for f in flags_one:
            if t == f and i + 1 < len(rest):
                val = _strip_quotes(rest[i + 1])
                if any(ch in val for ch in ("$", "`", "*", "?")):
                    return (None, False)
                return (val, True)
            if t.startswith(f + "="):
                val = _strip_quotes(t.split("=", 1)[1])
                if any(ch in val for ch in ("$", "`", "*", "?")):
                    return (None, False)
                return (val, True)
        i += 1
    return (None, True)


_PM_FLAGS_WITH_VALUE = frozenset({
    "--prefix", "--cwd", "-C", "--dir", "-w", "--workspace", "--filter", "-F",
})


def _first_subcommand(head: str, rest: list) -> Optional[str]:
    i = 0
    n = len(rest)
    while i < n:
        t = rest[i]
        if t in _PM_FLAGS_WITH_VALUE:
            i += 2  # skip the flag and its value
            continue
        if t.startswith("-"):
            i += 1
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_.:-]*=", t):
            i += 1
            continue
        return _strip_quotes(t)
    return None


def _token_after(rest: list, keyword: str) -> Optional[str]:
    for i, t in enumerate(rest):
        if t == keyword:
            for j in range(i + 1, len(rest)):
                if not rest[j].startswith("-"):
                    return _strip_quotes(rest[j])
    return None


def _post_selector_tokens(head: str, rest: list) -> list:
    """Tokens following an explicit workspace/filter selector (its value consumed)."""
    i = 0
    out_start = None
    while i < len(rest):
        t = rest[i]
        if t == "workspace" and i + 1 < len(rest):
            out_start = i + 2
            break
        if t in ("-w", "--workspace", "--filter", "-F") and i + 1 < len(rest):
            out_start = i + 2
            break
        if t.startswith("--workspace=") or t.startswith("--filter=") or t.startswith("-F="):
            out_start = i + 1
            break
        i += 1
    if out_start is None:
        return []
    return rest[out_start:]


def _classify_post_selector(post: list, scripts: set, safe_allow: set, protected_cmds: set,
                            under_monorepo: bool = True) -> Optional[Verdict]:
    """Classify the post-selector subcommand on a NON-protected workspace.
    Returns a BLOCK verdict, or None to ALLOW.

    `under_monorepo` indicates the selected workspace lives inside the protected
    monorepo (where the protected CLI bin is hoisted and a `.bin` fallthrough is
    reachable). When False (an UNRELATED project's workspace) a non-declared
    token fallthrough cannot reach the protected daemon and is allowed.
    """
    # find first meaningful token
    first = None
    for t in post:
        if t.startswith("-"):
            continue
        first = _strip_quotes(t)
        break
    if first is None:
        return None  # nothing to run; allow (e.g. selector + flags only)
    # dependency built-in -> allowed (handled by dependency rule, non-protected ws)
    if first in DEP_BUILTINS:
        return None
    # runtime/exec/runner token -> route through P1 semantics -> DENY
    if first in EXEC_RUNNER_TOKENS:
        return _block("P9", "runtime/exec token after a workspace selector (P1)")
    # consume optional run/run-script keyword
    script_tok = first
    if first in ("run", "run-script"):
        script_tok = None
        for t in post:
            if t in ("run", "run-script"):
                continue
            if t.startswith("-"):
                continue
            script_tok = _strip_quotes(t)
            break
        if script_tok is None:
            return None
    # protected command basename -> DENY (.bin fallthrough)
    if script_tok in protected_cmds:
        return _block("P9", "protected command basename after a workspace selector")
    if script_tok in EXEC_RUNNER_TOKENS:
        return _block("P9", "runtime/exec token after a workspace selector (P1)")
    # declared-script-key gate: token MUST be a declared script of this workspace
    if script_tok in scripts:
        return None  # ALLOW
    if script_tok in safe_allow:
        return None
    # non-declared token: a yarn .bin fallthrough reaches the hoisted protected
    # CLI bin ONLY inside the protected monorepo -> deny there; an unrelated
    # project's tool fallthrough carries no daemon risk -> allow.
    if under_monorepo:
        return _block("P9", "token is not a declared script of the selected workspace (.bin fallthrough)")
    return None


def _dir_under_any_root(d: Optional[str], cfg: dict) -> bool:
    """True if directory `d` is at/under any protected monorepo root."""
    if not d:
        return False
    dn = os.path.normpath(d)
    for root in cfg.get("protected_root_manifest_paths", []):
        rn = os.path.normpath(root)
        if dn == rn or dn.startswith(rn + "/"):
            return True
    return False


def _resolved_protected_dirs(globs: list, cfg: dict) -> list:
    """Resolve each protected GLOB to the CONCRETE protected directory/file path(s)
    its literal prefix denotes — so a destructive ROOT that CONTAINS them can be
    detected (reverse containment). An ABSOLUTE glob (`/usr/bin/<cmd>*`) contributes
    its literal directory prefix as-is. A RELATIVE `**`-prefixed glob
    (`**/packages/<pkg>/dist/index.mjs`) is suffix-matching and could match an
    UNRELATED repo; it is qualified by JOINING its post-`**` literal segment-prefix
    onto each protected monorepo ROOT (`<root>/packages/<pkg>/dist`), so only the
    genuine protected location is produced. Returns absolute concrete dirs."""
    out = []
    roots = [os.path.normpath(r) for r in cfg.get("protected_root_manifest_paths", [])]
    for g in globs:
        if g.startswith("/"):
            lit = _glob_literal_prefix(g)
            if lit:
                out.append(os.path.normpath(lit))
            continue
        # relative glob: drop a leading `**/` then take the literal segment-prefix.
        body = g[3:] if g.startswith("**/") else g
        segs = []
        for seg in body.split("/"):
            if _has_shell_glob(seg) or seg == "**":
                break
            segs.append(seg)
        rel = "/".join(segs)
        if not rel:
            continue
        for root in roots:
            out.append(os.path.normpath(os.path.join(root, rel)))
    return out


def _destructive_root_contains_protected(root_path: str, globs: list, cfg: dict,
                                          cwd: Optional[str], cwd_det: bool) -> bool:
    """REVERSE CONTAINMENT: True if a destructive operation on the directory/pathspec
    `root_path` would wipe/revert a protected descendant — i.e. a protected glob
    resolves to a concrete path AT or UNDER `root_path`. Closes the leak where a
    destructive op names a CONTAINER of the protected file (the repo root, the
    `packages` dir, `.`) instead of the protected path itself
    (`git clean -fdx .`, `find packages -delete`, `git checkout -- .`). The forward
    direction (target UNDER protected) is handled by `_path_matches_any`/
    `_path_under_any`; this adds the reverse. A relative `root_path` is resolved
    against the effective cwd; an unresolvable relative root cannot be proven safe →
    treated as the cwd-qualified candidate only (no blanket block)."""
    cands = []
    for c in _resolve_rel(root_path, cwd, cwd_det):
        cands.append(_normalize_path(c))
    for prot_dir in _resolved_protected_dirs(globs, cfg):
        for rc in cands:
            if _dir_equal_or_under(prot_dir, rc):
                return True
    return False


def _dir_is_protected_pkg(d: Optional[str], cfg: dict) -> bool:
    """True if `d` is a protected package dir. A relative `protected_script_paths`
    glob (e.g. `**/packages/<pkg>`) is suffix-matching and would also match an
    UNRELATED project's identically-named dir; qualify it by requiring `d` to be
    under a protected monorepo root (an absolute glob is honored as-is)."""
    if not d:
        return False
    spaths = cfg.get("protected_script_paths", [])
    abs_globs = [g for g in spaths if g.startswith("/")]
    rel_globs = [g for g in spaths if not g.startswith("/")]
    if abs_globs and _path_matches_any(d, abs_globs):
        return True
    if rel_globs and _path_matches_any(d, rel_globs) and _dir_under_any_root(d, cfg):
        return True
    return False


def _under_protected_monorepo(man_dir: Optional[str], cfg: dict) -> bool:
    """True if `man_dir` is at/under a protected monorepo root (where the
    protected CLI bin is hoisted into node_modules/.bin and thus reachable as a
    `.bin` fallthrough). A manifest OUTSIDE every protected root belongs to an
    UNRELATED project — a non-declared-token fallthrough there cannot reach the
    protected daemon, so it must not be blocked."""
    if not man_dir:
        return False
    if _dir_under_any_root(man_dir, cfg):
        return True
    # also: a protected package dir reached via an ABSOLUTE glob (root-qualified
    # for relative globs to avoid matching an unrelated project's same-named dir)
    if _dir_is_protected_pkg(man_dir, cfg):
        return True
    return False


def _resolve_bare_script(script_tok: Optional[str], cwd: Optional[str], cwd_det: bool,
                         cfg: dict, safe_allow: set, protected_cmds: set) -> Verdict:
    """Resolve a bare (no-selector) script-run against the effective manifest."""
    if not cwd_det or cwd is None:
        # indeterminate cwd -> fail closed for the script-run family
        return _block("P9", "script-run with indeterminate cwd (fail-closed)")
    man_dir, is_protected, scripts, det = _effective_manifest_for_cwd(cwd, cfg)
    if not det:
        return _block("P9", "script-run with unresolvable effective manifest (fail-closed)")
    if is_protected:
        if script_tok is not None and script_tok in safe_allow:
            return ALLOW
        return _block("P9", "bare script-run reaching a protected workspace/root")
    # non-protected effective manifest: declared-script-key gate
    if script_tok is None:
        # bare PM run with no token in a manifest OUTSIDE the protected monorepo
        # is harmless (an unrelated project's default script); only fail-closed
        # inside the protected monorepo.
        if _under_protected_monorepo(man_dir, cfg):
            return _block("P9", "bare script-run with no script token (fail-closed)")
        return ALLOW
    if script_tok in protected_cmds:
        return _block("P9", "protected command basename in non-protected cwd (.bin fallthrough)")
    if script_tok in EXEC_RUNNER_TOKENS:
        return _block("P9", "runtime/exec token in non-protected cwd (P1)")
    if script_tok in scripts:
        return ALLOW
    if script_tok in safe_allow:
        return ALLOW
    # token is not a declared script of this manifest. Inside the protected
    # monorepo a yarn .bin fallthrough could reach the hoisted protected CLI bin
    # -> deny. In an UNRELATED project (outside every protected root) a tool
    # fallthrough carries no risk to the protected daemon -> allow.
    if _under_protected_monorepo(man_dir, cfg):
        return _block("P9", "token is not a declared script of the non-protected manifest (.bin fallthrough)")
    return ALLOW


# ── corepack re-routing ──────────────────────────────────────────────────────

def _runner_call_payloads(simple_cmds: list, cfg: Optional[dict] = None,
                          cwd_base: Optional[str] = None) -> list:
    """Return (payload, effective_cwd, cwd_det) tuples for any package-runner
    `-c`/`--call` form (`npx -c '<cmd>'`, `npm exec -c '<cmd>'`,
    `pnpm -w <ws> dlx --call '<cmd>'`).

    The payload string is itself a shell command the runner executes, so it is
    recursively evaluated under the SAME effective cwd (cd chain + wrapper chdir +
    PM workspace selector), so a relative daemon-launch / protected build inside
    the payload resolves. A benign payload re-evaluates to ALLOW.
    """
    payloads = []
    for idx, sc in enumerate(simple_cmds):
        toks = _safe_shlex(sc)
        if not toks:
            continue
        cw = _command_words(toks)
        if not cw:
            continue
        _, head, rest = cw[0]
        # locate the runner argv (after npx/bunx, or after exec/dlx/x for a PM)
        runner_args = None
        if head in ("npx", "bunx"):
            runner_args = rest
        elif head in PKG_MANAGERS:
            for i, t in enumerate(rest):
                if t in ("exec", "dlx", "x"):
                    runner_args = rest[i + 1:]
                    break
        if runner_args is None:
            continue
        # effective cwd for the payload: cd chain + wrapper chdir + selector
        cwd, cwd_det = _effective_cwd_after(simple_cmds, idx, cwd_base)
        cwd, cwd_det = _fold_wrapper_cwd(cwd, cwd_det, toks)
        if cfg is not None:
            cwd, cwd_det = _selector_cwd(head, rest, cfg, cwd, cwd_det)
        i = 0
        while i < len(runner_args):
            t = runner_args[i]
            if t in ("-c", "--call") and i + 1 < len(runner_args):
                payloads.append((_strip_quotes(runner_args[i + 1]), cwd, cwd_det))
                i += 2
                continue
            if t.startswith("--call="):
                payloads.append((_strip_quotes(t.split("=", 1)[1]), cwd, cwd_det))
                i += 1
                continue
            i += 1
    return payloads


# ── Generic exec-front-end recursion (wrapper-AGNOSTIC tail analysis) ────────

def _peel_exec_frontend(toks: list):
    """Given the tokens of ONE simple command, if its head (after VAR=val
    env-prefixes and any ENV_WRAPPERS folding) is a DOCUMENTED exec front-end,
    consume the front-end's own options/operands per its profile and return:

        (kind, value)

      kind == "tail"    -> value is the trailing argv list (the wrapped command
                           the front-end exec()s). Re-tokenized as a simple cmd.
      kind == "payload" -> value is a SHELL-STRING the front-end runs via a shell
                           (flock -c / su -c / runuser -c / watch joined-tail).
                           The caller recurses it through evaluate().
      None              -> head is not a documented front-end (leave unchanged).

    Pure parsing; no project names. An unknown head is never a front-end, so a
    benign command with a non-front-end head is untouched (no over-block).
    """
    # Locate the front-end head. A front-end may itself sit behind ENV_WRAPPERS
    # (`env flock …`, `sudo flock …`, `nohup flock …`) and/or VAR=val prefixes —
    # reuse _command_words, which already folds env-prefixes + ENV_WRAPPERS per
    # their own grammar, so the head it reports is the FIRST real command word.
    cw = _command_words(toks)
    if not cw:
        return None
    head_idx, head, _rest = cw[0]
    profile = EXEC_FRONTEND_PROFILES.get(head)
    if profile is None:
        return None
    # the ENV_WRAPPER prefix (everything before the front-end head) is preserved
    # on the rewritten tail so `env -C <dir> flock … node <rel>` keeps its chdir.
    prefix = toks[:head_idx]
    opts_with_arg = profile.get("opts_with_arg", frozenset())
    payload_opts = profile.get("payload_opts", frozenset())
    cwd_opts = profile.get("cwd_opts", frozenset())
    joins = profile.get("joins_tail_as_shell", False)
    args_marker = profile.get("args_marker")
    leading_pos = profile.get("leading_positionals", 0)
    consume_user = profile.get("consume_user_positional", False)
    # options that SUPPLY the user (so no leading user positional is expected).
    _USER_OPTS = frozenset({"-u", "--user"})
    n = len(toks)
    i = head_idx + 1  # consume the front-end head
    consumed_pos = 0
    user_consumed = False
    marker_seen = False
    cwd_dir = None        # chdir directory set by a cwd_opt
    cwd_dynamic = False   # cwd_opt value was dynamic ($/`/glob) -> fail closed
    while i < n:
        t = toks[i]
        if args_marker is not None and not marker_seen:
            # gdb-style: the tail begins ONLY after the explicit --args marker.
            if t == args_marker:
                marker_seen = True
                i += 1
                break
            if t in opts_with_arg and i + 1 < n:
                i += 2
                continue
            i += 1
            continue
        if t == "--":
            i += 1
            break
        # shell-string payload option (flock -c 'str', su -c 'str', --command=)
        if payload_opts:
            if t in payload_opts and i + 1 < n:
                return ("payload", _strip_quotes(toks[i + 1]), prefix, None, False)
            matched = False
            for po in payload_opts:
                if t.startswith(po + "="):
                    return ("payload", _strip_quotes(t.split("=", 1)[1]), prefix, None, False)
            del matched
        # cwd-changing option (unshare --wd, bwrap --chdir, proot -w): capture
        # the directory so the wrapped relative tail resolves against it.
        if cwd_opts:
            if t in cwd_opts and i + 1 < n:
                val = _strip_quotes(toks[i + 1])
                if any(ch in val for ch in ("$", "`", "*", "?")):
                    cwd_dynamic = True
                else:
                    cwd_dir = val
                i += 2
                continue
            fused = None
            for co in cwd_opts:
                if t.startswith(co + "="):
                    fused = t.split("=", 1)[1]
                    break
            if fused is not None:
                val = _strip_quotes(fused)
                if any(ch in val for ch in ("$", "`", "*", "?")):
                    cwd_dynamic = True
                else:
                    cwd_dir = val
                i += 1
                continue
        # value-taking option (separated form)
        if t in opts_with_arg and i + 1 < n:
            if t in _USER_OPTS:
                user_consumed = True  # -u USER supplies the user; no positional
            i += 2
            continue
        # fused long option --opt=value
        if t.startswith("--") and "=" in t:
            if t.split("=", 1)[0] in _USER_OPTS:
                user_consumed = True
            i += 1
            continue
        # any other option flag (no operand)
        if t.startswith("-") and len(t) > 1:
            i += 1
            continue
        # a bare positional operand the front-end consumes before its tail
        if consumed_pos < leading_pos:
            consumed_pos += 1
            i += 1
            continue
        # an optional leading USER positional (su/runuser without -u): consume ONE
        # bare word, then keep scanning for a trailing -c payload or argv tail.
        if consume_user and not user_consumed:
            user_consumed = True
            i += 1
            continue
        # first non-option, non-positional token: the tail starts here.
        break
    if args_marker is not None and not marker_seen:
        # gdb without --args runs no wrapped command tail.
        return None
    tail = toks[i:]
    if not tail:
        return None
    if joins:
        # watch joins its trailing argv into a single shell-evaluated string.
        return ("payload", " ".join(_strip_quotes(x) for x in tail), prefix, cwd_dir, cwd_dynamic)
    return ("tail", tail, prefix, cwd_dir, cwd_dynamic)


def _peel_one(sc: str):
    """Peel a SINGLE simple-command string through documented exec front-ends.

    Returns (rewritten_sc, payloads_for_this_sc) where rewritten_sc is the
    argv-tail form (empty string if the command reduced to a shell-string
    payload) and payloads_for_this_sc is a list of (payload_str, cwd_dir,
    cwd_dynamic) tuples to recurse. Front-ends stack (`flock /l strace node …`),
    so peeling iterates with a bounded depth. A cwd-changing front-end option
    (unshare --wd / bwrap --chdir / proot -w) is folded into the rewritten tail
    as an `env -C <dir> …` prefix so the existing cwd machinery resolves the
    wrapped relative protected path; a DYNAMIC cwd value is rendered as an
    UNRESOLVABLE `env -C <dynamic>` so relative launch/build tails fail closed.
    """
    cur = sc
    payloads = []
    for _ in range(8):
        toks = _safe_shlex(cur)
        if not toks:
            break
        res = _peel_exec_frontend(toks)
        if res is None:
            break
        kind, val, prefix, cwd_dir, cwd_dyn = res
        # render any front-end cwd-opt as an env -C prefix on the rewritten tail.
        cwd_prefix = []
        if cwd_dyn:
            # an unresolvable chdir: emit a value the env -C cwd extractor flags
            # as dynamic ($-bearing) so relative protected-path resolution stays
            # indeterminate (fail-closed for relative launch/build tails).
            cwd_prefix = ["env", "-C", "${__GUARD_DYNAMIC_CWD__}"]
        elif cwd_dir is not None:
            cwd_prefix = ["env", "-C", cwd_dir]
        if kind == "payload":
            payloads.append((val, cwd_dir, cwd_dyn))
            cur = ""
            break
        # kind == "tail": rebuild the simple command, preserving the ENV_WRAPPER
        # prefix (env -C/sudo --chdir cwd handling) + any front-end cwd-opt.
        cur = " ".join(prefix + cwd_prefix + val)
    return (cur, payloads)


def _unwrap_exec_frontends(groups: list, cwd_base: Optional[str] = None):
    """Recursively peel DOCUMENTED exec front-ends off every simple command,
    PRESERVING pipeline-group topology so cross-segment primitives (P5 endpoint,
    P6 prockill) are not falsely connected across `;`/`&&` boundaries.

    Input `groups` is the _pipeline_groups() output (a list of groups, each a
    list of simple-command strings). Returns (peeled_groups, peeled_flat,
    shell_payloads, changed):
      peeled_groups  : same topology with each segment replaced by its argv-tail
                       form (empty-string segments dropped).
      peeled_flat    : the flat list of all non-empty peeled segments (for the
                       segment-oriented primitives P1/P2/P3/P4/P7/P8/P9).
      shell_payloads : (payload_str, cwd, cwd_det) for shell-string forms.
      changed        : True iff any segment was actually rewritten.

    An UNKNOWN head is never a front-end, so a benign tail stays untouched (no
    blanket substring scan, no over-block).
    """
    peeled_groups = []
    peeled_flat = []
    payloads_out = []
    changed = False
    # a flat index over all segments to resolve each segment's effective cwd
    # against the FULL original ordering (cd chains span groups).
    flat_original = [seg for g in groups for seg in g]
    flat_pos = 0
    for g in groups:
        new_g = []
        for seg in g:
            rewritten, seg_payloads = _peel_one(seg)
            if rewritten != seg:
                changed = True
            # resolve effective cwd for any shell-string payload of this segment
            for pval, pcwd_dir, pcwd_dyn in seg_payloads:
                cwd, cwd_det = _effective_cwd_after(flat_original, flat_pos, cwd_base)
                if pcwd_dyn:
                    cwd, cwd_det = (cwd, False)
                elif pcwd_dir is not None:
                    cwd = os.path.normpath(os.path.join(cwd, pcwd_dir)) if (cwd and not os.path.isabs(pcwd_dir)) else os.path.normpath(pcwd_dir)
                    cwd_det = cwd_det if not os.path.isabs(pcwd_dir) else True
                payloads_out.append((pval, cwd, cwd_det))
            flat_pos += 1
            if rewritten:
                new_g.append(rewritten)
                peeled_flat.append(rewritten)
        if new_g:
            peeled_groups.append(new_g)
    return (peeled_groups, peeled_flat, payloads_out, changed)


_PM_AT_VERSION_RE = re.compile(r"^(yarn|pnpm|npm)(@.+)?$")


def _unwrap_corepack(simple_cmds: list) -> list:
    """Rewrite `corepack <pm>[@version] ...` simple commands to `<pm> ...` so
    P1/P8/P9 re-parse. The corepack proxy front-end accepts a pinned version
    (`corepack pnpm@9 exec …`); normalize the proxy token to the bare PM
    basename and preserve the remaining args."""
    out = []
    for sc in simple_cmds:
        toks = _safe_shlex(sc)
        cw = _command_words(toks) if toks else []
        if cw and cw[0][1] == "corepack" and len(cw[0][2]) >= 1:
            rest = cw[0][2]  # args after 'corepack' (head excluded)
            proxy = os.path.basename(_strip_quotes(rest[0]))
            m = _PM_AT_VERSION_RE.match(proxy)
            if m:
                pm = m.group(1)
                out.append(" ".join([pm] + rest[1:]))
                continue
        out.append(sc)
    return out


# ── P0 ANCHOR scan (HEAD-AGNOSTIC, wrapper-name-independent) ─────────────────


def _git_inspection_head(head: str, rest: list) -> bool:
    """True if this is a `git <readonly-subcmd> …` inspection command, honoring
    git GLOBAL options that take an argument (`git -C <dir> status`)."""
    if head != "git":
        return False
    skip_next = False
    for t in rest:
        st = _strip_quotes(t)
        if skip_next:
            skip_next = False
            continue
        if not st:
            continue
        if st in _GIT_GLOBAL_OPTS_WITH_ARG:
            skip_next = True          # its operand is NOT the subcommand
            continue
        if st.startswith("-"):
            continue                  # bare/fused global flag (no separate arg)
        return st in _GIT_READONLY_SUBCMDS
    # bare `git` (or only global options) with no subcommand: treat as inspection
    return True


# Options that turn an otherwise-inspection head into a COMMAND-EXECUTOR:
#   find/fd `-exec`/`-execdir`/`-ok`/`-okdir` run a command per match;
#   fuser `-k` kills. When present, the head is NOT inspection — its tail must
#   be scanned for a protected launch/kill.
_FIND_EXEC_OPTS = frozenset({"-exec", "-execdir", "-ok", "-okdir", "--exec", "--exec-batch", "-x", "-X"})
_KILL_FLAG_HEADS = {"fuser": frozenset({"-k", "--kill"})}


def _is_inspection_command(head: str, rest: list) -> bool:
    """A simple command is an inspection/data command (anchor scan skipped) when
    its HEAD basename is in the small read/inspect/edit allowlist, OR it is a
    read-only git invocation — UNLESS it carries an option that turns it into a
    command-executor (find/fd `-exec`, fuser `-k`), in which case it is NOT
    inspection and its tail is scanned. This is the ONLY fixed head list."""
    if head in READ_INSPECT_EDIT_ALLOWLIST:
        # find/fd with an -exec action actually RUN a command -> not inspection.
        if head in ("find", "fd"):
            if any(_strip_quotes(t) in _FIND_EXEC_OPTS for t in rest):
                return False
        # fuser -k KILLS -> not inspection (the kill is caught downstream by P6
        # and the W4 anchor); a bare fuser/lsof is read-only.
        kill_flags = _KILL_FLAG_HEADS.get(head)
        if kill_flags and any(_strip_quotes(t) in kill_flags or
                              (_strip_quotes(t).startswith("-") and "k" in _strip_quotes(t).lstrip("-"))
                              for t in rest):
            return False
        return True
    if _git_inspection_head(head, rest):
        return True
    return False


# Shell directory-navigation builtins whose positional is ALWAYS a directory
# operand, never a command to exec (`cd <dir>`, `pushd <dir>`). A protected
# command basename appearing as their operand is a same-named directory, not a
# launch — so a routine `cd <dir>` / `pushd <dir>` into a directory whose basename
# equals a protected command name must ALLOW. Generic shell builtins, NO project
# names.
_NAV_OPERAND_HEADS = frozenset({"cd", "pushd", "popd", "chdir"})

# Heads that consume their trailing positionals as DATA operands (a path/name
# argument), NOT as a command to exec. A protected anchor appearing AFTER one of
# these heads is its operand, never a launch — so the command-word launch test
# must NOT fire (`cp <name> dst`, `tar cf a.tar <name>`, `chmod +x <name>`,
# `grep <name>`, `kill <name>`, `cd <dir>`). Union of the read/inspect allowlist,
# the filesystem-mutation verbs, the process-kill verbs, and the directory-nav
# builtins — all GENERIC tool basenames, NO project names. (Mutation of a
# protected path is handled by the W6/W7 mutation anchors; a kill by the W4 kill
# anchor; this set only suppresses the LAUNCH classification so those data ops are
# not mis-blocked as launches.)
_DATA_OPERAND_HEADS = (
    READ_INSPECT_EDIT_ALLOWLIST | _STEP0_MUTATION_HEADS | KILL_VERBS
    | _NAV_OPERAND_HEADS
)


# heads for which `_FIND_EXEC_OPTS` options are genuine command EXECUTORS (run a
# command per match). The same option spellings (`-x`/`-X`/`--exec`) collide with
# UNRELATED tools' data flags (`tar -x` extract, `tar -X <exclude-file>`), so the
# executor-boundary interpretation must be SCOPED to a segment that actually
# invokes one of these heads — otherwise `tar -x <protected-name>` would be
# mis-read as `tar` exec-ing the protected name. Generic tool basenames.
_FIND_EXEC_HEADS = frozenset({"find", "fd", "fdfind"})


def _find_exec_boundary_at(prev: str, exec_toks: list) -> bool:
    """True only when `prev` is a find/fd executor option AND a find/fd head is
    actually present among the segment's exec tokens — so the executor-boundary
    interpretation does not collide with an unrelated tool's identically-spelled
    data flag (`tar -x`/`tar -X`)."""
    if prev not in _FIND_EXEC_OPTS:
        return False
    return any(os.path.basename(_strip_quotes(st)) in _FIND_EXEC_HEADS
               for _i, st in exec_toks)


def _anchor_preceded_by_data_head(exec_toks: list, pos: int, tokens: list) -> bool:
    """True if the token at `pos` is governed by a data-consuming head
    (`_DATA_OPERAND_HEADS`) — i.e. it is that head's DATA operand. When True, the
    `_anchor_in_launch_position` follow/runner gate must NOT be OR-ed in at the
    W1/W2 call sites: it would mis-fire when a preceding operand's basename
    coincidentally looks like a runtime/runner token (e.g. a destination literally
    named `x` in `cp /tmp/x <name>` — `x` is in EXEC_RUNNER_TOKENS — wrongly
    flagging the operand as a launch).

    A find/fd EXECUTOR option (`_FIND_EXEC_OPTS`, an OPTION token filtered out of
    `exec_toks`) between the data head and `pos` CANCELS the data head's
    governance: after `find … -exec <cmd> …` the tokens belong to the EXECUTED
    command, not to find's path operands. So a data head is only counted when NO
    (find/fd-scoped) executor boundary separates it from `pos` (keeps
    `find -exec node <bundle> daemon` reaching the launch-position runner gate)."""
    pos_orig = exec_toks[pos][0]
    # an executor boundary anywhere in the raw tokens before `pos` cancels any
    # earlier find/fd data head — the tokens after it are the executed command.
    # Scoped to find/fd heads so `tar -x <name>` keeps its data-head governance.
    if any(_find_exec_boundary_at(_strip_quotes(tokens[k]), exec_toks) for k in range(pos_orig)):
        return False
    return any(os.path.basename(_strip_quotes(exec_toks[j][1])) in _DATA_OPERAND_HEADS
               for j in range(pos))


def _anchor_in_command_word_position(exec_toks: list, pos: int, tokens: list) -> bool:
    """True if the exec token at exec-position `pos` is the COMMAND WORD (the
    program being exec()'d) of its simple command, behind ANY chain of wrapper
    front-ends — head-agnostically, with NO wrapper enumeration.

    The whole `_p0_anchor` premise is that any head NOT in the read/inspect
    allowlist is a possible exec front-end / launcher, so a protected COMMAND
    basename that ends up as the program a front-end runs is a LAUNCH no matter
    which subcommand follows it (`<wrapper> <protected-cmd> claude|mcp|auth|…`).
    This closes the follow-token gate that let `<wrapper> <protected-cmd> claude`
    leak while `<protected-cmd> daemon start` blocked.

    TWO discriminators keep a protected name used as a genuine DATA argument from
    being mis-classified as a launch (no new over-block):

    (1) DATA-OPERAND HEAD: if ANY exec token at a position BEFORE `pos` (the
        command segment is a single simple command — pipeline/`;` already split
        upstream) is a data-consuming head (`cp`/`mv`/`tar`/`chmod`/`grep`/`kill`
        /… in `_DATA_OPERAND_HEADS`), the protected token is that head's file/name
        OPERAND, not a program — NOT command word. (`cp <name> dst`,
        `tar cf a.tar <name>`, `chmod +x <name>`, `kill <name>`.)

    (2) BARE SEPARATE OPTION: if the IMMEDIATELY-PRECEDING raw token is a bare
        separate option (`-k`, `--flag` with no `=`), it MAY consume the protected
        token as a value (`pytest -k <name>`) — NOT command word. A FUSED option
        (`--opt=val`) self-contains its value, so the next token is still a
        positional command word.

    EXCEPTION — a `find`/`fd` EXECUTOR option (`-exec`/`-execdir`/`-ok`/`-okdir`/
    `--exec`/`-x`/`-X` in `_FIND_EXEC_OPTS`) immediately before the protected token
    makes that token the COMMAND find/fd RUNS per match (`find . -exec <protected>
    …`) — a real launch. The executor option overrides BOTH discriminators: the
    `find`/`fd` head is a data-operand head for its OWN path args, but the token
    after `-exec` crosses the executor boundary into command position.

    Otherwise the token is the command word a wrapper chain exec()s → launch.
    The `_anchor_in_launch_position` follow-gate still independently catches the
    rare `… -k <protected-cmd> daemon start` lifecycle form.
    """
    orig_idx = exec_toks[pos][0]
    prev = _strip_quotes(tokens[orig_idx - 1]) if orig_idx > 0 else ""
    # EXECUTOR BOUNDARY (find/fd -exec …): the token after the executor option is
    # the command run per match — a launch — REGARDLESS of the find/fd data head.
    # Scoped to a segment that actually invokes find/fd, so an unrelated tool's
    # identically-spelled data flag (`tar -x <name>`) is NOT a boundary.
    if _find_exec_boundary_at(prev, exec_toks):
        return True
    # (1) any earlier exec token in this segment is a data-consuming head → operand.
    for j in range(pos):
        if os.path.basename(_strip_quotes(exec_toks[j][1])) in _DATA_OPERAND_HEADS:
            return False
    if orig_idx <= 0:
        return True
    if prev == "--":
        return True
    # redirect operators / pipe / list separators introduce a new command word.
    if prev in (">", ">>", "<", "2>", "&>", "1>", "2>>", "|", "&", ";", "&&", "||"):
        return True
    # (2) a BARE separate option may consume the next token as a VALUE → not a
    # command word. A FUSED option (`--opt=val`) does not.
    if prev.startswith("-"):
        return "=" in prev
    return True


def _anchor_after_dashopt_danger(exec_toks: list, pos: int, tokens: list) -> bool:
    """Over-block-as-danger: True when a protected ANCHOR token (a command
    basename for W2, or a registered launch path for W1) sits immediately after a
    separate dash-option in an exec-operand-plausible position
    (`<front-end> -someflag <protected-anchor> …`).

    Under the head-agnostic + no-option-grammar-enumeration constraint this
    position is genuinely UNDECIDABLE: a front-end's value-consuming flag
    (`<front-end> -g <anchor>`) is structurally indistinguishable from a tool's
    value-consuming flag (a test runner's `-k <name>` selector). The
    `_anchor_in_command_word_position` discriminator (2) resolves the ambiguity
    as a flag VALUE (ALLOW), which leaks the wrapped command-word / path launch.

    Per the operator's explicit 'prefer to over-block' stance, this predicate
    resolves the SAME ambiguity as DANGER for BOTH the W1 launch-path arm and the
    W2 command-basename arm: a protected anchor after a separate dash-option
    BLOCKS. For W2 this is a deliberate safe-side over-block that ALSO blocks the
    test-runner-selector twin (`<runner> -k <protected-cmd>`) — an accepted false
    positive, since a protected CLI basename is an unusual selector/pattern value
    and the operator prefers that false positive over the launch leak. (A pure
    inspection head — a search/read tool — is allowlisted upstream and never
    reaches this arm, so its `-e <protected-cmd>` data form stays ALLOWed.) For
    W1 the anchor is a REGISTERED launch path, so a false positive is impossible —
    only a real protected entrypoint after a dash-option can match.

    It keys ONLY on (the caller has already matched the protected anchor;
    immediately preceded by a separate dash-option — not `--`, no fused `=`; NOT a
    find/fd executor option; NOT governed by a data-operand head). NO
    front-end/tool option grammar is enumerated. A data-operand head still
    suppresses it (`<copy-verb> -t /dst <name>` keeps the name a copy operand)."""
    orig_idx = exec_toks[pos][0]
    if orig_idx <= 0:
        return False
    prev = _strip_quotes(tokens[orig_idx - 1])
    # a find/fd EXECUTOR option already makes the next token a command word via
    # the command-word check; here we only handle the GENERIC dash-option case.
    if _find_exec_boundary_at(prev, exec_toks):
        return False
    if not (prev.startswith("-") and prev not in ("--",) and "=" not in prev):
        return False
    # a data-consuming head governing the token keeps it a data operand, not a
    # launch (`<copy-verb> -t /dst <name>`); do not over-block those.
    if _anchor_preceded_by_data_head(exec_toks, pos, tokens):
        return False
    return True


def _p0_anchor(simple_cmds: list, cfg: dict, cwd_base: Optional[str] = None,
               groups: Optional[list] = None) -> Optional[Verdict]:
    """HEAD-AGNOSTIC anchor scan. For ANY simple command whose head is NOT in the
    small read/inspect/edit allowlist, scan the WHOLE argv for a protected anchor
    in executable position and BLOCK on launch/build/kill grammar — INDEPENDENT of
    the wrapper/front-end head name. This is the load-bearing wrapper-agnostic
    gate: it does NOT enumerate wrappers; a head that is not an inspection command
    is treated as a possible launcher, so the trailing protected launch/build/kill
    can never hide behind a novel front-end of ANY name (no wrapper enumeration).
    """
    cmds = set(cfg.get("protected_cmds", []))
    launch_paths = cfg.get("protected_launch_paths", [])
    bpaths = cfg.get("protected_build_paths", [])
    ws = set(cfg.get("protected_build_workspaces", []))
    idents = cfg.get("protected_proc_idents", [])
    statefiles = cfg.get("protected_statefiles", [])
    services = cfg.get("protected_services", [])
    hotfiles = cfg.get("protected_hotfiles", [])
    endpoint_paths = cfg.get("protected_endpoint_paths", [])
    global_bins = cfg.get("protected_global_bins", [])
    # data-file-derived process-selector fragments for the W4 kill anchor (same
    # set P6 uses — either-direction overlap closes the directional asymmetry).
    kill_tokens = _protected_proc_tokens(cfg)
    groups = groups or []
    for idx, sc in enumerate(simple_cmds):
        tokens = _safe_shlex(sc)
        if not tokens:
            continue
        cw = _command_words(tokens)
        if not cw:
            continue
        _tok_idx, head, rest = cw[0]
        # effective cwd for relative-path resolution + leading wrapper chdir.
        cwd, cwd_det = _effective_cwd_after(simple_cmds, idx, cwd_base)
        cwd, cwd_det = _fold_wrapper_cwd(cwd, cwd_det, tokens)
        exec_toks = _anchor_exec_tokens(tokens)
        exec_vals = [st for _i, st in exec_toks]

        # ── CLASS-SWEEP find/fd DESTRUCTIVE (runs BEFORE the inspection gate) ────
        # `find` is in the read/inspect allowlist, so a `find <protected-file-or-
        # container> -delete` / `-exec rm` would be skipped by the gate below. Run
        # the find-destructive scan FIRST for every protected FILE-glob family
        # (bundle / statefile / global-bin) so the destructive find BLOCKS head-
        # agnostically. A read-only find (`-print`/`-name`) or a destructive find on
        # an UNRELATED path does NOT hit (the scanner requires a destructive action
        # AND a matching protected/container path).
        for fam in (hotfiles, statefiles, global_bins):
            if fam and _find_destructive_target_hits(
                    tokens, exec_toks, list(fam) + _container_dir_globs(fam), cwd, cwd_det, cfg):
                return _block("P0", "find destructive action on a protected file or its container dir")
        # build-path family: a destructive find whose root CONTAINS the protected
        # package (`find packages -delete` at the repo root) wipes the bundle — caught
        # by reverse containment against the build paths.
        if bpaths and _find_destructive_target_hits(tokens, exec_toks, list(bpaths), cwd, cwd_det, cfg):
            return _block("P0", "find destructive action containing a protected build path")

        # ── DESTRUCTIVE GIT PATHSPEC (runs BEFORE the inspection gate) ───────────
        # `git status`/`log`/… are inspection (gated below), but `git clean -fdx`/
        # `git restore`/`git checkout -- <path>`/`git reset --hard -- <path>` WIPE or
        # REVERT working-tree files. A pathspec under a protected build dir / bundle /
        # statefile (or its container) destroys the protected file. Head-agnostic so a
        # wrapped git is caught; an unrelated pathspec / read-only git / branch switch
        # does NOT hit. The target set is the protected FILE families + their
        # container dirs (a `git clean` of the package dir removes the dist bundle).
        _git_globs = (list(bpaths) + list(hotfiles) + list(statefiles)
                      + _container_dir_globs(list(hotfiles) + list(statefiles)))
        if _git_globs and _git_destructive_pathspec_hits(tokens, exec_toks, _git_globs, cwd, cwd_det, cfg):
            return _block("P0", "destructive git pathspec under a protected build/bundle/state path")

        # GATE: inspection/data commands (the allowlist heads) are skipped so a
        # protected path/command named as DATA (grep pattern, echo arg, cat target,
        # diff operand, sed/awk script) still ALLOWS — no blanket substring scan.
        if _is_inspection_command(head, rest):
            continue

        # ── W1 LAUNCH-PATH ANCHOR ────────────────────────────────────────────
        # A protected launch PATH is inherently executable (a script/bundle). It
        # is a LAUNCH (not a data/file op) when it is in EXECUTABLE / COMMAND-WORD
        # POSITION:
        #   • the COMMAND WORD a wrapper chain exec()s (`<wrapper> <path> [sub]`,
        #     regardless of the trailing subcommand — head-agnostic), OR
        #   • the FIRST exec token (`<path> …`), OR
        #   • immediately AFTER a `--` end-of-options marker, OR
        #   • immediately AFTER a runtime (`node`/`tsx`/…) — `node <path>`, OR
        #   • FOLLOWED by a launch subcommand (`<path> daemon start`).
        # A protected path as a mere ARGUMENT to a copy/read/mutation head (e.g.
        # `cp <path> /tmp`, `tar cf a.tar <path>`) is NOT a launch — the
        # command-word test's DATA-OPERAND-HEAD discriminator keeps those ALLOWing
        # (mutation of a protected hotfile is handled by W6/P3). Also scan fused
        # `--opt=<path>` RHS values (a wrapper option whose VALUE is a protected
        # launch path execs it: `--exec=<path>` / `--cmd=<path>`).
        for pos, (_i, st) in enumerate(exec_toks):
            if _path_matches_cwd(st, launch_paths, cwd, cwd_det) and (
                    _anchor_in_command_word_position(exec_toks, pos, tokens)
                    or _anchor_after_dashopt_danger(exec_toks, pos, tokens)
                    or (not _anchor_preceded_by_data_head(exec_toks, pos, tokens)
                        and _anchor_in_launch_position(exec_vals, pos))):
                return _block("P0", "protected launch-path anchor in executable position behind a front-end")
        for fv in _fused_option_values(tokens):
            if _path_matches_cwd(fv, launch_paths, cwd, cwd_det):
                return _block("P0", "protected launch-path anchor as a fused option value behind a front-end")

        # ── W2 COMMAND-BASENAME ANCHOR ───────────────────────────────────────
        # A protected COMMAND basename is a LAUNCH whenever it is the COMMAND WORD
        # (the program a front-end exec()s) — head-agnostically, behind ANY wrapper
        # chain — REGARDLESS of which subcommand follows it. This is the primary,
        # idiomatic launch form (`<wrapper> <protected-cmd> claude|mcp|auth|…`); the
        # follow-token must NOT gate the command-word case (the prior gate let
        # `<wrapper> <protected-cmd> claude` leak while `<protected-cmd> daemon start`
        # blocked). The follow-token/exec-position gate (`_anchor_in_launch_position`)
        # is RETAINED only to disambiguate a protected name that is NOT in command-
        # word position — a genuine non-command-word data/flag-value argument to an
        # unrelated tool (`pytest -k <name>`, `grep <name>`) — so it still ALLOWS.
        # Also scan fused `--opt=<protected-cmd>` RHS when a launch subcommand follows.
        for pos, (_i, st) in enumerate(exec_toks):
            # A token CONTAINING a slash is a PATH, never a command-word BASENAME
            # launch. Its basename coincidentally matching a protected command
            # name (a directory/file literally NAMED that basename — e.g. the
            # worktree dir, a package dir, or any unrelated path) must NOT make a
            # plain navigate/list/read/`-C`/copy/find/tar of that path a launch.
            # Slash-bearing tokens are decided ONLY by the W1 launch-PATH matcher
            # above (which BLOCKS the real protected entrypoints — the installed
            # binaries and the dist/bin bundle paths — and ALLOWS unrelated paths
            # that merely share a basename).
            if "/" in st:
                continue
            base = st  # slashless ⇒ basename == token
            if base in cmds and (_anchor_in_command_word_position(exec_toks, pos, tokens)
                                 or _anchor_after_dashopt_danger(exec_toks, pos, tokens)
                                 or (not _anchor_preceded_by_data_head(exec_toks, pos, tokens)
                                     and _anchor_in_launch_position(exec_vals, pos))):
                return _block("P0", f"protected command anchor '{base}' in executable position behind a front-end")
        # fused `--opt=<protected-cmd>` whose value is a protected command and the
        # NEXT original token is a launch subcommand (`--exec=<cmd> daemon`).
        for ti, raw in enumerate(tokens):
            st = _strip_quotes(raw)
            if st.startswith("-") and "=" in st:
                val = _strip_quotes(st.split("=", 1)[1])
                if val and os.path.basename(val) in cmds and ti + 1 < len(tokens) and _strip_quotes(tokens[ti + 1]) in _ANCHOR_LAUNCH_FOLLOW:
                    return _block("P0", f"protected command anchor '{os.path.basename(val)}' as a fused option value behind a front-end")

        # ── W3 BUILD ANCHOR: build grammar co-occurring with a protected build ──
        # A build is indicated by a build-tool basename / package-manager `build` /
        # a package-runner running a build tool, ANYWHERE in the exec tokens. When
        # so, BLOCK if a protected build path / workspace / cwd is named.
        if _anchor_build_hits_protected(tokens, exec_toks, cfg, cwd, cwd_det, ws, bpaths):
            return _block("P0", "build anchor co-occurring with a protected build target behind a front-end")

        # ── W4 KILL ANCHOR: a kill verb in exec position + protected proc-ident ──
        # P6 already scans pipeline groups by text, but a kill behind an unknown
        # wrapper has head != kill so _is_kill_executor misses it. Detect a kill
        # verb anywhere in the exec tokens + a protected ident/statefile in the sc.
        if idents or statefiles or kill_tokens:
            kill_in_tail = any(os.path.basename(st) in KILL_VERBS for _i, st in exec_toks)
            # `fuser -k` is a kill executor too (not in KILL_VERBS). Behind a novel
            # wrapper its head is the wrapper, so detect a fuser + -k in the tail.
            if not kill_in_tail and any(os.path.basename(st) == "fuser" for _i, st in exec_toks):
                if any(_strip_quotes(t) in ("-k", "--kill") or
                       (_strip_quotes(t).startswith("-") and "k" in _strip_quotes(t).lstrip("-")) for t in tokens):
                    kill_in_tail = True
            if kill_in_tail:
                sc_text = sc
                # A SELECTION MECHANISM (name/pattern-matching kill verb
                # `pkill`/`killall`/`fuser`, or a command substitution feeding the
                # kill) gates the broadened either-direction overlap, so a plain
                # `<wrapper> kill <bareword>` PID/jobspec kill stays ALLOWED while a
                # `<wrapper> pkill -f <fragment>` BLOCKS. Mirrors P6's gate.
                exec_bases = [os.path.basename(_strip_quotes(st)) for _i, st in exec_toks]
                name_kill = any(b in ("pkill", "killall", "fuser") for b in exec_bases)
                has_selector = name_kill or bool(_command_substitutions(sc))
                ident_hit = (_selector_overlaps_protected(sc_text, kill_tokens, cmds)
                             if has_selector
                             else any(ident in sc_text for ident in idents))
                # EITHER-direction overlap against the data-file-derived protected-
                # process tokens (closes the same directional asymmetry P6 had: a
                # wrapped kill whose selector is a bare protected command-word or a
                # fragment of a registered ident now BLOCKS).
                if ident_hit:
                    return _block("P0", "process-kill anchor carrying a protected identifier behind a front-end")
                for raw in re.split(r"\s+", sc_text):
                    s2 = _strip_quotes(raw.strip("'\""))
                    s2 = re.sub(r"^\d*<+", "", s2)
                    if s2 and not s2.startswith("-") and statefiles and _path_matches_any(s2, statefiles):
                        return _block("P0", "process-kill anchor reaching a protected statefile behind a front-end")
                # kill target via command substitution naming the ident OR
                # reading a protected statefile (`kill $(jq .pid <statefile>)`).
                for sub in _command_substitutions(sc):
                    if _selector_overlaps_protected(sub, kill_tokens, cmds):
                        return _block("P0", "process-kill anchor (subst) carrying a protected identifier behind a front-end")
                    if statefiles:
                        for raw in re.split(r"\s+", sub):
                            s2 = _strip_quotes(raw.strip("'\"()"))
                            s2 = re.sub(r"^\d*<+", "", s2)
                            if s2 and not s2.startswith("-") and _path_matches_any(s2, statefiles):
                                return _block("P0", "process-kill anchor (subst) reaching a protected statefile behind a front-end")

        # ── W5 SERVICE-CONTROL ANCHOR: a service-manager + disruptive verb + ────
        # a protected unit, behind any wrapper. P2 is HEAD-KEYED (it only fires
        # when the effective head is the service-manager program), so a wrapped
        # service-manager restart (`<wrapper> systemctl restart <unit>` /
        # `<wrapper> service <unit> restart`) slips past it exactly like the
        # launch/build/kill leaks did before the anchor redesign. Detect a
        # service-manager program basename anywhere in the exec tokens
        # (head-agnostic) + a disruptive lifecycle verb (SERVICE_VERBS) + a
        # protected unit, INDEPENDENT of the wrapper head. Data-driven: the unit
        # names live in `protected_services` (the engine stays project-name-free).
        if services and _anchor_service_hits_protected(tokens, exec_toks, services):
            return _block("P0", "service-control of a protected unit behind a front-end")

        # ── W6 BUNDLE-WRITE ANCHOR: a mutation verb + a protected hotfile path ──
        # P3 HOTFILE_GUARD is head-keyed (`_mutation_targets` reads the EFFECTIVE
        # head, folding only documented ENV_WRAPPERS), so a bundle mutation behind
        # a NOVEL front-end (`<wrapper> touch/truncate/tee/dd/sed -i/install/rsync/
        # ln/perl -i <bundle>` or `<wrapper> … > <bundle>`) leaks past it exactly
        # like the launch/build/kill/service leaks did. Detect a mutation verb in
        # EXECUTABLE position (head-agnostic) whose target — resolved against the
        # effective cwd incl. the wrapper chdir — is a protected hotfile, OR a
        # redirect to a protected hotfile, INDEPENDENT of the wrapper head.
        if hotfiles and _anchor_mutation_hits(sc, tokens, exec_toks, hotfiles, cwd, cwd_det, cfg):
            return _block("P0", "mutation of a protected bundle behind a front-end")
        # class-sweep: a mutation/move/delete of the bundle's CONTAINER directory
        # (`mv|rm|rmdir <…>/dist`) destroys the bundle just as a direct delete does.
        if hotfiles and _anchor_family_destructive_hits(sc, tokens, exec_toks, hotfiles, cwd, cwd_det, cfg):
            return _block("P0", "destruction of a protected bundle's container dir behind a front-end")

        # ── W7 STATEFILE-WRITE ANCHOR: a mutation verb / redirect + a protected ──
        # daemon statefile, behind any wrapper. Mirrors W6; P4 STATEFILE_GUARD is
        # head-keyed the same way P3 is.
        if statefiles and _anchor_mutation_hits(sc, tokens, exec_toks, statefiles, cwd, cwd_det, cfg):
            return _block("P0", "mutation of a protected state file behind a front-end")
        # class-sweep: a mutation/move/delete of the statefile's CONTAINER directory
        # (`mv|rm|rmdir <home>`) removes the statefile just as a direct delete does.
        if statefiles and _anchor_family_destructive_hits(sc, tokens, exec_toks, statefiles, cwd, cwd_det, cfg):
            return _block("P0", "destruction of a protected state file's container dir behind a front-end")

        # ── W8 CONTROL-ENDPOINT ANCHOR: a loopback net-client + the protected ────
        # shutdown endpoint path in its OWN argv, behind any wrapper. P5
        # ENDPOINT_GUARD is head-keyed (it only fires when a pipeline segment's
        # effective head is a net-client in NET_HEADS), so a wrapped client
        # (`<wrapper> curl -X POST http://127.0.0.1:PORT/stop`) slips past it. The
        # cross-segment / stdin-fed split forms remain P5's job (it scans pipeline
        # groups); this anchor closes the single-command wrapped form: a net-client
        # basename in EXECUTABLE position + a loopback host + the protected endpoint
        # path present in this simple command, INDEPENDENT of the wrapper head.
        if endpoint_paths and _anchor_endpoint_hits(sc, exec_toks, endpoint_paths):
            return _block("P0", "loopback request to a protected control path behind a front-end")

        # ── W9 GLOBAL-CLI ANCHOR: a package-manager global-install/link, or a ────
        # write to a protected global-bin path, behind any wrapper. P7
        # GLOBALBIN_GUARD is head-keyed (it only fires when the effective head is a
        # package manager), so a wrapped global op (`<wrapper> npm install -g <pkg>`
        # / `<wrapper> npm link <pkg>`) leaks past it. Mirror P7 exactly: a
        # package-manager basename in EXECUTABLE position carrying `-g`/`--global`
        # or `link`/`unlink` (the SAME blanket global-op family P7 blocks bare,
        # regardless of package name), OR a mutation write whose target is under a
        # protected global-bin path — INDEPENDENT of the wrapper head.
        if _anchor_globalbin_hits(sc, tokens, exec_toks, global_bins, cwd, cwd_det):
            return _block("P0", "global package install/link behind a front-end")
    return None


# Mutation-verb basenames the bundle/statefile/global-bin anchors recognize in
# EXECUTABLE position behind a wrapper. This is the SAME family `_mutation_targets`
# parses as a head; listing it here lets the anchor find the verb head-agnostically
# (the verb is no longer the simple command's head once a wrapper precedes it).
# UNIFIED with `_STEP0_MUTATION_HEADS` (THE SAME frozenset object, defined earlier
# in the file) so the three protected-file families (config / bundle / statefile)
# cannot DRIFT on which mutation verbs are recognized behind a wrapper. Generic
# filesystem-mutation tools — NOT project names.
_ANCHOR_MUTATION_HEADS = _STEP0_MUTATION_HEADS


def _anchor_mutation_hits(sc: str, tokens: list, exec_toks: list,
                          globs: list, cwd: Optional[str], cwd_det: bool,
                          cfg: Optional[dict] = None) -> bool:
    """True if this simple command (head-agnostic) MUTATES a path matching `globs`.

    Locates the FIRST mutation-verb basename in executable position (so the verb is
    found even when a novel front-end is the simple command's head), reconstructs
    EACH mutation verb's OWN argv (the tokens FROM that verb onward) and reuses
    `_mutation_targets_for_verb` on it — then resolves each target against the
    effective cwd (cd chain + wrapper chdir, already folded by the caller) and
    matches it against the protected globs. A write redirect (`> path`, incl.
    fd-prefixed / force / non-first forms) belongs to the whole simple command, so
    all redirect targets are scanned once via `_write_redirect_targets`.

    Scans EVERY mutation verb in executable position (not just the first) — mirroring
    STEP0 — so a leading benign mutation-looking token cannot MASK a later real
    mutator (`<wrapper> cp mv <protected> dst`: the `cp`-arg parse sees `<protected>`
    only as a SOURCE = read, but the later `mv` parse sees it as a moved-away SOURCE
    = mutation → BLOCK). The cp-source ALLOW boundary is preserved because each
    verb's targets are extracted from its OWN argv: a real `cp <protected> dst`
    (head=cp, the only mutation verb) yields only the dest, so it still ALLOWS.

    Returns False when no mutation verb / redirect is present OR no target matches —
    so a read/inspect of a protected path, or a mutation of a NON-protected path,
    still ALLOWS."""
    # write-redirect targets apply to the whole simple command (after the wrapper
    # exec) regardless of head — scan them once (all forms, every position).
    for tgt in _write_redirect_targets(sc):
        for cand in _resolve_rel(tgt, cwd, cwd_det):
            if _mutation_cand_hits(cand, globs, cfg, cwd, cwd_det):
                return True
    # scan ALL mutation verbs in executable position (head-agnostic), each parsed
    # against its OWN argv (the tokens from that verb onward).
    for (i, st) in exec_toks:
        if os.path.basename(_strip_quotes(st)) not in _ANCHOR_MUTATION_HEADS:
            continue
        verb_base = os.path.basename(_strip_quotes(st))
        verb_args = tokens[i + 1:]
        for tgt in _mutation_targets_for_verb(verb_base, verb_args):
            for cand in _resolve_rel(tgt, cwd, cwd_det):
                if _mutation_cand_hits(cand, globs, cfg, cwd, cwd_det):
                    return True
    return False


def _git_destructive_pathspec_hits(tokens: list, exec_toks: list, globs: list,
                                   cwd: Optional[str], cwd_det: bool,
                                   cfg: Optional[dict] = None) -> bool:
    """HEAD-AGNOSTIC: True if a destructive git subcommand (`clean -f`/`restore`/
    `checkout -- <path>`/`reset --hard`) targets a pathspec under a protected glob, OR
    a pathspec that CONTAINS a protected descendant (`git clean -fdx .` /
    `git checkout -- .` at the repo root). `git clean -fdx packages/<pkg>/dist`,
    `git restore packages/<pkg>/dist`, `git checkout -- .`, `git reset --hard --
    <protected>` BLOCK; an unrelated `git clean -fdx packages/<other>`, a read-only
    `git status`, and a plain branch `git checkout main` ALLOW. Resolves a
    `git -C <dir>` chdir + relative pathspecs against the effective cwd; a repo-root-
    relative pathspec (`:/` / `:(top)`) is resolved against the protected monorepo
    root. Reverse containment (a pathspec CONTAINING a protected dir) is cfg-driven."""
    if not globs:
        return False
    for gi, st in exec_toks:
        if os.path.basename(_strip_quotes(st)) != "git":
            continue
        subcmd, sub_idx = _git_subcommand_index(tokens, gi)
        if subcmd not in _GIT_DESTRUCTIVE_SUBCMDS:
            continue
        if not _git_is_destructive_invocation(tokens, sub_idx, subcmd):
            continue
        gcwd, gcwd_det = _git_effective_cwd(tokens, gi, cwd, cwd_det)
        for p, repo_rel, ic, is_exclude in _git_destructive_pathspecs(tokens, sub_idx, subcmd):
            # an EXCLUDE pathspec (`:!`/`:(exclude)`) REMOVES entries — it is never a
            # positive destructive target, so it must NOT be scanned as one.
            if is_exclude:
                continue
            # a repo-root-relative pathspec (`:/`/`:(top)`) resolves against the
            # protected monorepo root(s) when the cwd is under one; else the cwd.
            bases = []
            if repo_rel and cfg is not None:
                for root in cfg.get("protected_root_manifest_paths", []):
                    rn = os.path.normpath(root)
                    if gcwd and gcwd_det and (os.path.normpath(gcwd) == rn
                                              or os.path.normpath(gcwd).startswith(rn + "/")):
                        bases.append(rn)
            cands = []
            for b in bases:
                cands.append(_normalize_path(os.path.join(b, p)) if not os.path.isabs(p) else _normalize_path(p))
            cands.extend(_normalize_path(c) for c in _resolve_rel(p, gcwd, gcwd_det))
            # case-insensitive magic (`:(icase)`) folds both sides of the match.
            match_globs = [g.casefold() for g in globs] if ic else globs
            for cand in cands:
                cc = cand.casefold() if ic else cand
                if _path_matches_any(cc, match_globs) or _path_under_any(cc, match_globs):
                    return True
            # reverse: the pathspec CONTAINS a concrete protected dir (`clean -fdx .`).
            if cfg is not None:
                for cand in cands:
                    if _destructive_root_contains_protected(cand, globs, cfg, None, False):
                        return True
    return False


def _anchor_endpoint_hits(sc: str, exec_toks: list, endpoint_paths: list) -> bool:
    """True if this simple command (head-agnostic) issues a loopback request whose
    own argv carries a protected control-endpoint path. Detects a net-client
    basename (curl/wget/http/httpie/nc/ncat/netcat/socat/telnet) in EXECUTABLE
    position behind any wrapper + a loopback host (127.0.0.1/localhost/::1) + the
    protected endpoint path present in the simple command. P5 still handles the
    cross-segment / stdin-fed split forms on pipeline groups; this closes the
    single-command wrapped form. A loopback request to a NON-protected endpoint, or
    a benign mention of the endpoint string behind an inspection head, does not hit
    here (the endpoint path must match a protected path AND a net-client must be in
    executable position)."""
    net_present = any(os.path.basename(_strip_quotes(st)) in NET_HEADS
                      for (_i, st) in exec_toks)
    if not net_present:
        return False
    if not LOOPBACK_RE.search(sc):
        return False
    return _endpoint_path_in(sc, endpoint_paths)


def _anchor_globalbin_hits(sc: str, tokens: list, exec_toks: list,
                           global_bins: list, cwd: Optional[str], cwd_det: bool) -> bool:
    """True if this simple command (head-agnostic) performs a protected global-bin
    operation behind any wrapper. Mirrors P7 exactly: a package-manager basename in
    EXECUTABLE position carrying a global flag (`-g`/`--global`) or a `link`/
    `unlink` subcommand (the SAME blanket global-op family P7 blocks bare,
    regardless of package name), OR a mutation write whose target is under a
    protected global-bin path. A package-manager LOCAL op (no global flag/link), or
    a write to a NON-protected path, does not hit here."""
    pm_pos = next((i for (i, st) in exec_toks
                   if os.path.basename(_strip_quotes(st)) in PKG_MANAGERS),
                  None)
    if pm_pos is not None:
        # the package-manager's OWN argv (from the pm token onward), so a `-g`/
        # `link` that belongs to the pm — not an unrelated wrapper option — is what
        # is matched (mirrors P7 reading the pm's `rest`).
        own = [_strip_quotes(t) for t in tokens[pm_pos + 1:]]
        is_global = any(t in ("-g", "--global") for t in own)
        is_link = any(t in ("link", "unlink") for t in own)
        if is_global or is_link:
            return True
    # write to a protected global-bin path via a mutation verb / redirect.
    if global_bins and _anchor_mutation_hits(sc, tokens, exec_toks, global_bins, cwd, cwd_det):
        return True
    return False


def _anchor_build_hits_protected(tokens: list, exec_toks: list, cfg: dict,
                                  cwd: Optional[str], cwd_det: bool,
                                  ws: set, bpaths: list) -> bool:
    """True if the simple command (head-agnostic) indicates a BUILD that targets a
    protected package: a build-tool basename OR a package-manager `build` verb OR
    a package-runner build tool appears in the exec tokens, AND a protected build
    path / workspace selector / protected cwd is named. Conservative: requires an
    explicit protected anchor (path token, fused --flag=path value, workspace
    selector, or a protected effective cwd) — a build naming NO protected target
    is NOT blocked here (residual #1 / non-protected builds stay allowed)."""
    bases = [os.path.basename(st) for _i, st in exec_toks]
    pm_present = any(b in PKG_MANAGERS for b in bases)
    buildtool_present = any(b in BUILD_TOOL_BASENAMES for b in bases)
    runner_present = any(b in ("npx", "bunx") for b in bases)
    has_build_verb = any(st == "build" for _i, st in exec_toks)
    # A build is indicated by: a bare build tool, OR a pm/runner with a 'build'
    # verb, OR a package-runner invoking a build tool.
    build_indicated = (
        buildtool_present
        or (pm_present and has_build_verb)
        or (runner_present and buildtool_present)
        or (runner_present and has_build_verb)
    )
    if not build_indicated:
        return False
    # protected target: explicit workspace selector naming a protected workspace
    for i, raw in enumerate(tokens):
        st = _strip_quotes(raw)
        if st in ("workspace", "workspaces", "--filter", "-F", "-w", "--workspace") and i + 1 < len(tokens):
            sel = os.path.basename(_strip_quotes(tokens[i + 1]).rstrip("/"))
            if sel in ws:
                return True
        for f in ("--filter", "-F", "-w", "--workspace"):
            if st.startswith(f + "="):
                sel = os.path.basename(st.split("=", 1)[1].rstrip("/"))
                if sel in ws:
                    return True
    # protected target: a build path token (bare or fused --flag=path) under a
    # protected build path → always blocks (explicit protected target). Strip the
    # workspace/filter SELECTOR flags only for this path-token scan (so a selector
    # VALUE is not mis-scanned as a build target).
    raw_tokens = [_strip_quotes(x) for x in tokens]
    scan_tokens = _strip_selector_tokens(raw_tokens)
    if bpaths and _any_token_under_incl_flagvalue(scan_tokens, cfg, cwd, cwd_det):
        return True
    # protected target via the effective cwd (build-mode in a protected pkg /
    # monorepo root) — but an EXPLICIT non-protected INPUT-PROJECT target (e.g.
    # `-p packages/<non-protected>/tsconfig.json`) proves the build is NOT of the
    # protected bundle, so a sibling-package build under a wrapper at the repo
    # root still ALLOWS (no over-block). ONLY input-project flags (`-p`/`--project`
    # /`--tsconfig`/`--config`) exempt — an OUTPUT flag (`--outdir`/`-o`) names
    # where output goes, NOT what is built, so it must NOT exempt (codex finding).
    if _anchor_explicit_nonprotected_input(raw_tokens, cfg, cwd, cwd_det):
        return False
    # An EXPLICIT workspace selector naming a KNOWN non-protected workspace proves
    # the build targets that workspace (not the protected bundle), so the
    # cwd-based fallback must not over-block `<wrapper> yarn workspace <non-prot>
    # build` at the monorepo root. A RECURSIVE/MULTI/glob selector fans into EVERY
    # workspace (incl. the protected one), so it does NOT exempt (codex finding).
    if _anchor_nonprotected_workspace_selector(tokens, cfg):
        return False
    if _cwd_in_protected_build_scope(cwd, cwd_det, cfg):
        return True
    if bpaths and _cwd_under_build_path(cwd, cwd_det, bpaths):
        return True
    return False


# Build INPUT-project flags (what is built) — distinct from OUTPUT flags (where
# output lands). Only input-project flags can prove a build is non-protected.
_INPUT_PROJECT_FLAGS = frozenset({"-p", "--project", "--tsconfig", "-c", "--config"})


def _anchor_explicit_nonprotected_input(tokens: list, cfg: dict,
                                        cwd: Optional[str], cwd_det: bool) -> bool:
    """True if an INPUT-project flag (`-p`/`--project`/`--tsconfig`/`-c`/`--config`)
    names a target that resolves DETERMINATELY OUTSIDE every protected build path.
    Output flags (`--outdir`/`-o`/`--outfile`) are NOT considered (an output path
    does not prove the build INPUT is non-protected). An unresolvable relative
    target fails CLOSED (cannot prove non-protected)."""
    vals = []
    i = 0
    n = len(tokens)
    while i < n:
        t = _strip_quotes(tokens[i])
        if t in _INPUT_PROJECT_FLAGS and i + 1 < n:
            nv = _strip_quotes(tokens[i + 1])
            if not nv.startswith("-"):
                vals.append(nv)
            i += 2
            continue
        if t.startswith("-") and "=" in t:
            flag, val = t.split("=", 1)
            if flag in _INPUT_PROJECT_FLAGS and val:
                vals.append(_strip_quotes(val))
        i += 1
    if not vals:
        return False
    for v in vals:
        for cand in _resolve_rel(v, cwd, cwd_det):
            if _path_is_protected_build(cand, cfg):
                return False
        if not os.path.isabs(_strip_quotes(v)) and not (cwd and cwd_det):
            return False  # unresolvable relative -> cannot prove non-protected
    return True


# ── Top-level evaluate ───────────────────────────────────────────────────────

def evaluate(command: str, cwd_base: Optional[str] = None) -> Verdict:
    if command is None:
        return ALLOW
    if len(command) > MAX_COMMAND_CHARS:
        # oversized -> fail closed conservatively (treat as indeterminate)
        return _block("STEP1", "oversized command (fail-closed)")
    # Normalize the bash force-clobber redirect `>|` to plain `>` BEFORE pipeline
    # splitting. `>|` is a WRITE redirect (noclobber-override), NOT a pipe, but the
    # `|` would otherwise make `_split_pipeline` mis-split `echo x >| <path>` into
    # two segments and lose the redirect target — letting a clobber-write to a
    # protected bundle / statefile / data file leak past every redirect-based
    # guard (W6/W7/STEP0). Covers fd-prefixed forms (`1>|`, `2>|`, `&>|`). Generic
    # bash syntax normalization — no project names.
    command = re.sub(r"((?:&|\d+)?>>?)\|", r"\1", command)
    # Neutralize compound-group delimiters `( ) { }` so grouped launches/builds
    # decompose into ordinary simple commands (bare `$(`/`${` are preserved).
    norm_command = _strip_compound_delims(command)
    simple_cmds = _split_pipeline(norm_command)
    if not simple_cmds:
        return ALLOW
    simple_cmds = _unwrap_corepack(simple_cmds)
    # Pipeline GROUPS preserve `|` connectivity for cross-segment primitives
    # (P5 endpoint, P6 prockill). Command-substitution contents are retained for
    # inspection (the compound-strip leaves `$(...)` intact).
    groups = _pipeline_groups(norm_command)

    # STEP 0 — config self-protection FIRST (before config load). Run against the
    # ORIGINAL simple commands so a self-protection mutation hidden behind a
    # front-end is still seen by STEP0's own path-pattern scan, and additionally
    # against any front-end-peeled tails below.
    # cfg is intentionally None here — STEP0 runs BEFORE the config load and must
    # not depend on the very file it protects. groups is carried for a faithful
    # snapshot though STEP0 does not read it.
    v = _step0_self_protection(Context(cwd_base=cwd_base, simple_cmds=simple_cmds, groups=groups))
    if v is not None:
        return v

    # ── Generic exec-front-end recursion (wrapper-AGNOSTIC) ──────────────────
    # Peel DOCUMENTED routine exec front-ends (flock/firejail/unshare/nsenter/
    # runuser/su/strace/watch/cpulimit/setpriv/perf/valgrind/...) off each simple
    # command so the protected launch/kill/build they exec() is exposed to the
    # primitive set, regardless of the front-end's NAME — and even behind an
    # ENV_WRAPPER (`env flock …`, `sudo flock …`). Group topology is PRESERVED so
    # P5/P6 are not falsely connected across `;`/`&&`. An UNKNOWN head is NOT a
    # front-end, so a benign tail stays allowed (no blanket substring scan).
    peeled_groups, peeled_flat, frontend_payloads, fe_changed = _unwrap_exec_frontends(groups, cwd_base)
    if fe_changed:
        # re-derive STEP0 against the peeled forms so a self-protection mutation
        # behind a front-end is also analyzed by STEP0's path-pattern scan.
        v = _step0_self_protection(Context(cwd_base=cwd_base, simple_cmds=peeled_flat, groups=peeled_groups))
        if v is not None:
            return v
        simple_cmds = peeled_flat
        groups = peeled_groups

    # Recurse front-end shell-string payloads (flock -c / su -c / runuser -c /
    # watch joined-tail) through evaluate() under the front-end's effective cwd.
    # Done BEFORE the config-load fail-closed return so a payload-wrapped danger
    # family still blocks even when the data file is absent/corrupt (a benign
    # payload re-evaluates to ALLOW, so this never over-blocks).
    for payload, pcwd, pcwd_det in frontend_payloads:
        if payload and payload not in (command, norm_command):
            pv = evaluate(payload, pcwd if pcwd_det else None)
            if pv[0] == "BLOCK":
                return pv

    # STEP 1 — load config; fail closed if unavailable.
    cfg = _load_config()
    if cfg is None:
        # fail-closed must also see the peeled tails (a front-end-wrapped danger
        # family under an absent/corrupt config still blocks).
        return _step1_indeterminate(simple_cmds)

    # Runner `-c`/`--call` payloads are shell commands the runner executes —
    # recursively evaluate each under the same cwd so a daemon launch / protected
    # build hidden inside the payload is caught (a benign payload re-evaluates to
    # ALLOW, so this does not over-block).
    for payload, pcwd, pcwd_det in _runner_call_payloads(simple_cmds, cfg, cwd_base):
        if payload and payload not in (command, norm_command):
            # recurse under the runner's effective cwd (None when indeterminate,
            # which makes relative launch/build payloads fail closed downstream)
            pv = evaluate(payload, pcwd if pcwd_det else None)
            if pv[0] == "BLOCK":
                return pv

    # STEP 2 — P0 HEAD-AGNOSTIC ANCHOR scan FIRST. This is the load-bearing
    # wrapper-agnostic gate: for any simple command whose head is NOT a read/
    # inspect/edit operation, it scans the WHOLE argv for a protected anchor in
    # executable position + launch/build/kill grammar, INDEPENDENT of the wrapper
    # head name. It catches a protected launch/build/kill behind ANY front-end —
    # documented (peeled above for precision) OR novel (any undocumented wrapper) —
    # without enumerating wrappers. The documented-front-end peel above still runs
    # for cwd/shell-payload precision, but it is no longer the load-bearing gate.
    v = _p0_anchor(simple_cmds, cfg, cwd_base, groups)
    if v is not None:
        return v

    # P1..P9 (order: launch, service, hotfile, statefile, endpoint,
    # prockill, globalbin, then package-script default-deny, then build arms).
    v = _p1_launch(simple_cmds, cfg, cwd_base, groups)
    if v is not None:
        return v
    v = _p2_service(simple_cmds, cfg)
    if v is not None:
        return v
    v = _p3_hotfile(simple_cmds, cfg, cwd_base)
    if v is not None:
        return v
    v = _p4_statefile(simple_cmds, cfg, cwd_base)
    if v is not None:
        return v
    # cross-segment primitives operate on pipeline GROUPS
    v = _p5_endpoint(groups, cfg)
    if v is not None:
        return v
    v = _p6_prockill(groups, cfg)
    if v is not None:
        return v
    v = _p7_globalbin(simple_cmds, cfg)
    if v is not None:
        return v

    # P9 default-deny package-script policy. If it returns a verdict (BLOCK or
    # ALLOW), honor it; only fall through to P8 build arms when P9 abstained.
    v = _p9_pkgscript(simple_cmds, cfg, cwd_base)
    if v is not None:
        if v[0] == "BLOCK":
            return v
        # Even when P9 ALLOWs a (non-protected) script-run, an EXPLICIT protected
        # build-path argument forwarded to that script still rebuilds the
        # protected bundle (`yarn build --project <protected>/tsconfig.json` from
        # a non-protected cwd). Run only the explicit-path subset of P8 before
        # honoring the ALLOW; the bare/cwd build-mode fallback is intentionally
        # skipped (it caused prior over-blocks).
        ev = _p8_explicit_protected_path(simple_cmds, cfg, cwd_base)
        if ev is not None:
            return ev
        return ALLOW

    v = _p8_build(simple_cmds, cfg, cwd_base)
    if v is not None:
        return v
    v = _p8_bare_build(simple_cmds, cfg)
    if v is not None:
        return v
    return ALLOW


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        # No parseable payload -> emit an INDETERMINATE sentinel so the bash
        # glue can fail closed for danger families (the glue, not us, decides).
        print("INDETERMINATE")
        return 0
    if payload.get("tool_name") != "Bash":
        print("ALLOW")
        return 0
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command", "")
    # Seed cwd resolution from the payload's reported cwd if present, else the
    # process cwd, so a relative `cd packages/<x>` is resolvable (reduces
    # false-blocks while preserving fail-closed for genuinely-unknown cwds).
    cwd_base = tool_input.get("cwd") or os.environ.get("CLAUDE_GUARD_CWD")
    if not cwd_base:
        try:
            cwd_base = os.getcwd()
        except OSError:
            cwd_base = None
    decision, primitive, reason = evaluate(command, cwd_base)
    if decision == "BLOCK":
        sys.stderr.write(f"[protected-runtime-guard] BLOCK {primitive}: {reason}\n")
        print("BLOCK")
        return 0
    print("ALLOW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
