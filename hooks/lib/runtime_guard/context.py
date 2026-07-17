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

    ALL FOUR FIELDS ARE MANDATORY — there are NO defaults. This closes the INV-6
    fail-OPEN hazard unique to the Context refactor: unlike a module split (which
    fails CLOSED on a missing import), a mis-built Context whose `groups`
    defaulted to `[]` would make the cross-segment guards `_p5_endpoint`
    (endpoint / raw-socket) and `_p6_prockill` (process-kill) ABSTAIN (return
    None) and flip a modeled BLOCK to a final ALLOW. Mandatory fields make that
    incomplete construction impossible. `cfg` keeps its `Optional[dict]` type —
    it may LEGITIMATELY be None for the pre-config STEP0 stage — but must still be
    passed EXPLICITLY.

    WHAT IS AND IS NOT GUARANTEED (audited + reproduced 2026-07-17; every clause
    below was executed, not assumed). Mandatory fields alone do NOT produce a
    fail-CLOSED outcome — they only convert a silent empty working set into a
    raised TypeError. The deny is produced by a THREE-link chain, all three of
    which must hold:
      1. construction of an INCOMPLETE Context raises TypeError at build time;
      2. `_core.main` wraps THE `evaluate()` CALL — and only that call — in a
         `BaseException` catch-all, converting any exception that escapes the
         DECISION ENGINE (including direct BaseException subclasses such as
         SystemExit) into an explicit INDETERMINATE verdict on stdout + a
         best-effort diagnostic on stderr. The sentinel is emitted and FLUSHED
         before the diagnostic is rendered, so an exception whose own `__str__`
         raises cannot prevent it. SCOPE — this is NOT blanket protection for every
         failure of the entry point, and must not be read as one:
           * Payload field access (`payload.get("tool_name")` / `tool_input`) runs
             BEFORE that protected region. Parseable-but-NON-OBJECT JSON (`"hello"`,
             `[1,2]`, `42`, `null`) therefore raises at field access and DOES exit
             with EMPTY stdout and a bare traceback (verified). Only UNPARSEABLE
             payloads are handled — by a separate earlier `except (ValueError,
             OSError)` that prints the same sentinel.
           * A genuine stdout write/flush failure cannot be repaired from inside the
             handler: the verdict channel is the thing that has failed.
         The narrow claim that IS true and verified: an exception escaping the
         `evaluate()` call cannot produce an empty verdict;
      3. the surrounding hook (`pretool-bash-safety.sh`) treats any non-ALLOW
         verdict as a signal to run `_runtime_guard_fail_closed`, which denies
         conservatively for the protected verb families it COVERS: service-control,
         process-termination (`constants.KILL_VERBS` + the `fuser` file-user
         front-end), package-manager, build-tool, runtime-launcher, and the endpoint
         / raw-socket client family (the full `_core.NET_HEADS`: nc/ncat/netcat/
         socat/telnet/curl/wget/http/https/httpie). For the P5 and P6 families it
         also tolerates the path-qualified (`/usr/bin/curl`) and quoted (`"curl"`)
         forms the engine normalizes.
    Therefore, for the two cross-segment primitives an empty `groups` would disable
    — P5 (endpoint / raw-socket) and P6 (process-kill) — a crash resolves to a DENY
    ACROSS THE FOUR INVOCATION FORMS THAT ARE TESTED: bare (`curl …`), quoted-whole
    (`"curl" …`), path-qualified (`/usr/bin/curl …`), and path-qualified+quoted.
    That is the whole of the claim.

    THIS IS NOT A FAMILY-WIDE GUARANTEE, AND CANNOT BE MADE INTO ONE. Link 3 is a
    REGEX over raw text; the engine recognizes a head via real LEXING (`shlex`),
    which normalizes forms a regex does not see. A regex can never be semantically
    equivalent to a lexer, so engine-BLOCK / fallback-ALLOW forms exist for P5 and
    P6 and always will. Reproduced against the real engine and the real helper
    (2026-07-17), each yielding engine=BLOCK but fallback=ALLOW:
      * quote-concatenation, where a name is split across a quote boundary and the
        lexer rejoins it — `"cu"rl <loopback-url>`, `cu"rl" …`, `'cu'rl …`,
        `c"u"rl …`, and the P6 forms `"pk"ill -f <ident>`, `ki"ll" -9 …`;
      * backslash-escaped names — `\curl <loopback-url>`;
      * `$(…)` command substitution and variable/alias indirection, where the name
        never appears at a position the regex accepts.
    Do NOT attempt to close these by extending the regex — chasing lexical
    equivalence with a lexer is a treadmill, and the fix direction is explicitly out
    of scope. The correct reading of link 3 is BEST-EFFORT DEFENSE-IN-DEPTH over
    specific tested forms, NOT a guarantee for any family.

    Link 3 is a hand-maintained bash approximation of token sets that live in Python,
    and it silently fell behind the engine TWICE. `hooks/tests/test_fail_closed_drift.py`
    now imports `_core.NET_HEADS` / `constants.KILL_VERBS` and mechanically asserts the
    shell helper denies every token in them; adding a front-end to the engine without
    widening the fallback fails that test instead of quietly re-opening this hole.

    COVERAGE IS NOT BLANKET — do NOT read link 3 as "the hook denies conservatively"
    for ALL commands. Three distinct limits, each verified:
      a. FAMILIES NOT COVERED AT ALL. The filesystem-MUTATION family is NOT in the
         fallback set, so a crashed guard still ALLOWs a mutation of a protected
         statefile / hotfile / global bin (verified: `cp`/`tee`/`truncate`/`sed -i`/
         `>`-redirect targeting a protected path each yield ALLOW when the engine
         raises). The primitives whose families remain UNCOVERED are STEP0 (config
         self-protection), P3 (hotfile), P4 (statefile), and P7 (global bin); they
         rely on the engine itself being healthy, not on the fallback. A future
         construction site that forgets a field is therefore fail-OPEN for those four
         outright, and for P5/P6 is fail-CLOSED only across the four tested invocation
         forms (never family-wide — see the scope note above) — widening the fallback
         to the mutation family is tracked as follow-up in
         docs/reference/core-context-refactor-plan.md, NOT as a claim made here.
      b. NORMALIZATION TOLERANCE IS P5/P6-ONLY. The path-qualified / quoted tolerance
         noted in link 3 was added to the P5 and P6 lines only; the service-control,
         package-manager, build-tool and runtime-launcher families keep their original
         bare-token anchoring (so `/usr/bin/systemctl restart …` is not matched by the
         fallback). Recorded, not fixed.
      c. THE FALLBACK APPROXIMATES THE ENGINE'S LEXING; IT DOES NOT REIMPLEMENT IT.
         It greps raw command TEXT — no tokenization, expansion, or resolution. What
         that means precisely (measured, not assumed — the coarse reading in BOTH
         directions was wrong):
           * NOT MATCHED (engine resolves them, regex does not): quote-concatenation
             (`"cu"rl …`), backslash-escaped names (`\curl …`), `$(…)` command
             substitution, variable/alias indirection, base64-encoded text.
           * MATCHED TODAY, BUT NOT PARSED AND NOT GUARANTEED: privileged- and
             environment-wrapper prefixes (`sudo curl …`, `env FOO=1 curl …`),
             `xargs`-wrapped verbs, and simple quoted-`eval` forms
             (`eval 'curl …'`, `eval "curl …"`) all DO match — but only incidentally,
             because the family name still appears literally at a position the
             patterns accept. Nothing parses the wrapper or the eval string, so this
             must NOT be recorded as coverage: a variant that breaks the literal
             (e.g. eval over a substitution) is not matched.
         The drift guard asserts token-set coverage and
         invocation-form tolerance, NOT semantic equivalence. The approximation is also
         deliberately coarser than the engine in the DENY direction (a bare
         `kill <pid>`, or an endpoint client aimed at a benign path, is denied by the
         fallback though the healthy engine ALLOWs it) — acceptable because this path
         runs only when the engine has already failed to decide.

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
