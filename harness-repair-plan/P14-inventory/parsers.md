# Bash-command readers: survey, corpus and a shared-module API

Repository: <repo> at master 1ace5ee4. This was read-only: no repo file was changed, nothing was installed, and nothing ran against the real HOME. Scratch work is in `$SCRATCH/parser/`:

- `exp1.py`: the `$'…'` experiment.
- `probe.py`, `probe_lex.py`: failure-mode probes.
- `extract_corpus.py` → `corpus.json`: the differential corpus.
- `diff_census.py` → `diff_census.json`: the corpus run against `bash -n` and against the census and lexer.
- `linecount.py` → `linecount.json`, plus `histblocks.json`: line breakdowns.

---

## 1. Reader matrix

Feature key: Y = handled correctly, P = partial or heuristic, N = not handled, - = not applicable.

| Reader (entry) | split ; && \|\| \| & \n | words | '…' | "…" | $'…' | $"…" | \ esc | $( ) | ` ` | <( ) >( ) | heredoc | redirects fd/mode | VAR=x prefix | wrappers | bash -c / eval | subshell / group / compound | comments | \\\n |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bash_execution_boundary `lex` / `Analyzer` | Y (no `&>`) | Y, segment kinds | Y | Y | Y (kept raw as an `ansi` seg; `ansi_decode` exists) | Y | Y | Y, recursive | Y, recursive | Y, recursive | Y, body Src; delimiter compare uses `.strip()` | Y io+op, no `&>`, no `{fd}` | Y + exec-vector vars | Y, table-driven, ~100 programs | Y (shells, eval, su, ssh, find -exec, xargs, git alias …) | P (keywords dropped, `[[ ]]` aware) | P (only right after an operator) | Y |
| bash_active_syntax_census `census` | - (does not segment) | - | Y | Y (state flag) | **N** | P | Y | Y | Y | Y | Y | - | - | - | - | - | **N** | Y |
| bash_context_strip `strip_non_executable_contexts` | P (no single `&`; `(` not split) | P | Y | Y | N | N | P | P (paren match) | P (treated as a quote) | N | P (regex, identifier delimiter only) | N | Y | P (9 names, sudo opts) | P (`-…c` of 4 shells) | N | **P (`#` mid-word strips the rest)** | N |
| bash_write_targets `extract_bash_write_targets_with_modes` | P (masked-text regex) | P | P (span blanked) | P (span blanked) | N | N | **N** (`'it'\''s'` swallows the line) | N | N | P (excluded) | P (identifier delimiters) | P (`>`, `>>`, `>\|`; `&>` dropped; fd skipped) | - | P (prefix neutraliser) | N | P (`(` neutralised) | P (`#` after a lead-in) | N |
| git_command_classifier `iter_git_invocations` / `classify_git_command` | Y quote-blind by design | **N** (`seg.split()`) | N in tokens | N in tokens | N | N | P (residual) | Y as a boundary | Y as a boundary | Y as a boundary | P | P (leading only) | Y | Y (`_WRAPPERS`, value flags, positionals) | Y (`_shell_layers` via `_shell_words`) | P | N | Y (in `_segments_with_kind`) |
| git_command_classifier `_shell_words` (layer lexer) | Y | Y | Y | Y | N | N | Y | Y (as RUNTIME) | Y | Y | Y with feed info | Y ops | - | - | Y | P | Y | Y |
| grep-backtrack-guard `_find_searches` | P (shlex punctuation plus a newline pre-split) | shlex | Y | Y | Y (pre-decode) | N | Y | Y (body scan) | Y (body scan) | Y (body scan) | via grepguard_context_strip | N | P | P (two wrapper sets) | Y (eval, bare-shell -c) | P (reserved words transparent) | shlex | P |
| harness-switch-guard `_segments` / `writes_settings_file` | P (shlex `;&\|`, splitlines) | shlex | Y | Y | N | N | Y | N | N | N | P (regex, `\w+` delimiter) | **P (`>` not punctuation: `x>f` is one token)** | Y | N | P (`-…c`, eval) | N | shlex | N |
| stop-command-gate `_typed`, `close_stalled` | - | shlex.split of slash-command args; substring test on Bash commands | | | | | | | | | | | | | | | | |
| userprompt-usage-snapshot `_adapter_command` | - | shlex.split of an env override (argv, not a Bash tool command) | | | | | | | | | | | | | | | | |
| userprompt-consent-allowlist.sh (inline py) | - | `shlex.split(posix=False)` of the `/allow` argument, then fnmatch against deny rules | | | | | | | | | | | | | | | | |

### 1.1 bash_execution_boundary.py (4,499 lines)

Entry points:

- `analyze(raw)` (:4314) runs `census_mod.census(raw)` first. Any census `fatal` is UNRESOLVED.
- `Analyzer(raw).analyze_code(Src.from_raw(raw), Env(), cond=True)` (:2609) → `lex()` (:623) → `walk()` (:2649) → `flush()` (:2691) → `eval_command()` (:2795) → `eval_argv()` (:2837) → `_h_<name>` handlers / `_shell` (:3630) / `_interpreter` (:3746) / `_prefix_wrapper` (:3135) / `_inert_consumer` (:2905).
- CLI `main()` (:4476) reads `CMD_INPUT` and stdin `CMD_PAYLOAD`.

What the lexer produces (:192-711):

- **Src**: text plus a per-char map back to raw offsets. `Src.from_raw` removes `\<nl>` first (:215).
- **Word**: `segs` = list of (kind, Src, abs_off). Kinds: `lit`, `sub`, `arith`, `param`, `procsub`, `ansi`, `glob`, `brace`, `arraylit`. `literal()` returns None if any part is computed. `content()` gives the offset-preserving literal for `-c` payloads.
- **Redir**: `op` (`<<-` `<<<` `<<` `>>` `<>` `>&` `<&` `>|` `>` `<`), `io` (a digit-only word glued to the op), `target` Word, and `heredoc = (delim, quoted, body Src)`.
- Token stream: `('W', Word)`, `('OP', text, off)`, `('R', Redir)`.
- Errors: `LexError` codes `single_quote`, `double_quote`, `ansi_quote`, `cmdsub`, `backtick`, `param`, `arith_bracket`, `procsub`, `array_assign`, `extglob`, `heredoc_delim`, `unterminated_heredoc`, `redirect_missing_target`.

The walk:

- Splits on OP tokens, with `[[ … ]]` folding (:2649).
- Drops the reserved words `DROP`/`HEADER` (:2791).
- Skips leading assignments, and treats `EXEC_ASSIGNMENT_VARS` such as `GIT_EXTERNAL_DIFF=…` as code (:2754).
- Resolves aliases defined in the same command (`alias`, `hash -p`, Env).
- Recurses into sub, procsub, backtick, heredoc body (when unquoted), `-c` payloads, eval, git `-c alias.x=` bodies (`_h_git` :3896), ssh, su, find -exec, and similar.
- `split_opts` (:744) with `_spec` / `_resolve_long` is a generic getopt-style splitter over tables. The tables run :713-1563: about 850 lines of per-program option specs (`_ic(...)`) and the WRAPPERS, SHELLS, INTERPRETERS and INERT_ARGV_CONSUMERS sets.

Known failure modes, measured in `probe_lex.py`:

- `&>` and `&>>` lex as background `&` followed by `>`. That is a spurious segment split.
- `{fd}>file`: `{fd}` stays an ordinary word.
- A `#` comment after a word raises a LexError: `echo a # don't` gives `single_quote`. The comment rule only fires when the previous token is an OP (:633).
- The heredoc terminator is matched with `.strip() == delim` (:651). For `<<`, a line `  EOF` ends the body early, and bash would not end it there. That over-reads the rest of the body as commands.
- `;;&` and `;&` split into `;;`/`;` plus `&`.
- No quote provenance per literal chunk: `"a"'b'c` comes out as one `lit:abc`.
- No public tree. Consumers get only the verdict JSON.
- `_cond_disabled` is set whenever the text merely contains "alias" (:2104).

Callers:

- `hooks/pretool-bash-safety.sh:1830-1835` runs it as a subprocess (`_EB_PY`).
- Tests: `test_bash_execution_boundary*.py`, `test_pol_generative_sweeps.py`, `pol_sweep_generators.py`, `test_runtime_guard.py`, `test_bash_safety_channel_script_operand.py`, and `tests/test_steps_{push,pull,merge}*.py`.

### 1.2 bash_active_syntax_census.py (399 lines)

Entry point: `census(raw)` (:148) returns `{"obligations":[{kind,offset}], "fatal":[...]}`.

- Helpers: `_join_continuations` (:93), `_skip_matching` (:53), `_scan_removal_references` (:115).
- Obligation kinds: `substitution`, `procsub`, `heredoc`, `param_reexpand`, `removal_reference`.
- Heredoc bodies and backtick bodies are re-censused recursively.
- Its contract is deliberate independence: it must not import the analyzer (docstring :18-23).

Failure modes, measured:

- **No `$'…'` state.** Details in §2.
- **No comment state.** An apostrophe in a comment is fatal: `git commit -m a # don't` gives `unbalanced:single_quote`.
- Heredoc terminator `.strip()` (:331), same as the lexer.
- An unterminated heredoc is fatal, while bash accepts it with a warning. This looks deliberate.

Callers: only `bash_execution_boundary.py:55` and `test_bash_execution_boundary.py`.

### 1.3 bash_context_strip.py (440 lines)

Entry point: `strip_non_executable_contexts(cmd)` (:44) = `_process_compound(_process_heredocs(cmd))`. It is also a CLI (`CMD_INPUT`).

- Produces a text view, not a structure. Quoted args of non-shell commands are blanked. `bash|sh|zsh|dash -…c` payloads are exposed. The args of DANGER_COMMANDS are unquoted. Script-interpreter argv is dropped. Heredoc bodies are blanked unless a shell reads them.
- Tokens: (text, kind ∈ space, comment, single, double, subst, word) (:179).
- Command word: `_find_command_word` (:219) skips assignments and 9 wrappers, plus sudo option values.

Failure modes, measured:

- `printf %s a#b rm` → `printf %s a`. A mid-word `#` is taken as a comment, which strips the tail. That is under-reporting.
- `echo $'it\'s' rm -rf x` → `echo $'it\ rm -rf x` (mangled).
- `cat <<'E O'` → heredoc not recognised (delimiter regex `[A-Za-z_]\w*`). The opener is mangled and the body is kept.
- A single `&` and a `(` do not separate segments.
- Backticks are consumed as a quote.
- It falls back to the raw input on exception or oversize.

Callers:

- `pretool-bash-safety.sh:1167-1171` (`COMMAND_CONTEXT_STRIPPED`, which feeds every grep rule and the classifier).
- `pretool-bash-safety.sh:326` imports `_process_heredocs`.
- `pretool-block-branch-pr-worktree.py:271`.
- `git_command_classifier.py:1876` uses it as the CLI normaliser.
- Tests: `test_bash_safety_context*.py` and `test_bash_safety_git_clean.py`.

### 1.4 bash_write_targets.py (1,277 lines; parsing part)

Entry points:

- `extract_bash_write_paths` (:803). Frozen.
- `extract_bash_write_targets_with_modes` (:1117) → `WriteTarget(path, mode, mechanism, source)`. Modes: `truncating`, `appending`, `rename_into_place`, `destroying`, `in_place_edit`.
- `extract_bash_touched_paths` (:1242) → (path, removed).
- `command_without_heredoc_bodies` (:136).

How it parses: regex over a *masked* copy, reading tokens from the original.

- `_strip_quoted_regions` (:361) blanks quotes and comments. `_strip_reason_payload` (:403). `_neutralize_command_word_prefixes` (:596) handles `\cp`, `/bin/cp` and `(`.
- Verb regexes: `_REDIRECT_MODE_OP_RE`, `_TEE_WORD_RE`, `_CP_MV_WORD_RE`, `install`, `truncate`, `dd`, `curl`, `wget`, `unlink`, `sed -i`.
- Tokens come from `_next_token_from_original` (:266). It handles one quoted span, with no concatenation and no escapes.

Failure modes, measured:

- `echo 'it'\''s' > /tmp/f` → `[]`. The masker opens a quote at the `'` after `\`, which swallows the redirect.
- `echo x >/tmp/a\ b` → `/tmp/a\`.
- `> $'/tmp/q'` → the literal `$'/tmp/q'`.
- `echo x &>/tmp/a` → `[]` (declared uncovered).
- `2>/dev/null` is reported as a truncate target. That is correct but noisy.
- Not covered: `cp -t`, `ln`, `rsync`, `tee >(…)`.
- `"$f"` is reported as the literal `$f`.
- Nothing inside `$( )`, `bash -c` or `eval` is seen.

Callers:

- `pretool-tool-policy.py:158,1479`
- `pretool-overnight-hook-guard.py:35`
- `pretool-cp-state-write-guard.py:28`
- `pretool-wrapper-userintent.py:48` (`command_without_heredoc_bodies`)
- `lib/attribution_journal.py:148`
- Tests: `test_overwrite_guard.py`, `test_bash_write_targets_policy.py`, `test_c_layer_protected_targets.py`, `tests/test_bash_write_targets_verb_narrowing.py`, `tests/test_commit_multi_repo_plan.py` and others.

### 1.5 git_command_classifier.py (1,892 lines; parsing part)

Entry points:

- `iter_git_invocations(text)` (:1702) and `classify_git_command(text)` (:1835) → (invocations, residuals).
- `GitInvocation(cmd_token, path_qualified, subcommand, args)`.
- `iter_shell_texts` (:1605) and `_shell_layers` (:1566).
- CLI (:1868) with `CMD_RAW=stdin` (stripped view NUL raw).

Finding the git invocation:

1. `_segments_with_kind` (:138) is a quote-blind splitter. It splits on `; \n | & && || ` ( )`, `$(`, `<(` and `>(`. It folds `\<nl>` and tags each segment with `in_quote` and `subst_close`.
2. `_invocation(seg)` (:1686) does `seg.split()` (whitespace only) and then `_command_token_index` (:345). That skips `NAME=`, the reserved words `if elif then else while until do ! { coproc`, leading redirects (`_REDIRECT_RE`, including `&>` and `{fd}`), `_WRAPPERS` (sudo doas env xargs time nohup setsid stdbuf ionice command builtin nice exec eval timeout flock chrt taskset unbuffer), their value flags (`_WRAPPER_VALUE_FLAGS`, keyed per wrapper) and their positionals (timeout, flock).
3. `_unquote_token` strips balanced outer quotes before the basename check.
4. `_git_subcommand` (:439) skips `GIT_GLOBAL_VALUE_OPTS` (`-C -c --git-dir --work-tree --namespace --super-prefix --config-env --attr-source --shallow-file`, each taking the next word) and any other `-…`.
5. `-c` is not interpreted: no alias.\*, core.\* or hooksPath reading here. Callers re-scan the args.

Layer lexer: `_shell_words` (:898) is a real quoting lexer with RUNTIME placeholders, heredoc bodies and feed info (pipe, here-document, here-string, file). It is used for `-c` layers and residuals, but not for the top-level invocation tokens.

Failure modes, measured:

- `git -C "my dir" push --force` → subcommand `dir"`, args `['push','--force']`. A rule keyed on `subcommand == 'push'` misses it.
- `git -c alias.x='!rm -rf y' x` → subcommand `y'`.
- `git commit -m 'a b c'` → args `["'a","b","c'"]`.
- The classifier has no alias awareness (`_h_git` in the boundary analyzer has it).
- `$'…'` is not handled.

Callers:

- `pretool-bash-safety.sh:1195` (CLI) and `:2371` and `:326`.
- `pretool-git-privilege-guard.py:276,284`
- `pretool-block-branch-pr-worktree.py:279`
- `pretool-bulk-commit-detector.py:44`
- `pretool-tool-policy.py:235`
- `pretool-overnight-hook-guard.py:41`
- `lib/git_clean_guard.py:132`, `lib/runtime_guard/git_cmds.py:37`, `lib/allowlist.py` (its own `_strip_git_global_opts`)
- `scripts/write-git-residual-override.py:40`, `scripts/check-enforcement-evidence.py`
- About 15 test files.

### 1.6 pretool-grep-backtrack-guard.py (1,253 lines)

Entry point: `_find_searches(command, _depth)` (:665) → [(pattern, mode)]. Order of work:

1. `_decode_ansi_c_quotes` (:123): its own escape table.
2. `_strip_contexts` → `lib/grepguard_context_strip.strip_non_executable_contexts` (a separate 231-line stripper: heredoc bodies and standalone comments).
3. Recurse into the bodies from `_extract_backtick_bodies` (:411), `_extract_dollar_paren_bodies` (:468) and `_extract_process_substitution_bodies` (:601). These are three near-duplicate quote scanners.
4. `_split_unquoted_newlines` (:763), then `_tokenize_segments` (:215): `shlex(posix, punctuation_chars=True, whitespace_split)`, grouped at `_SEP_TOKENS`.
5. Per segment: `_eval_args` (:540), `_shell_c_script` (:565; bare shells only, because function-shadow semantics), then `_normalise_search_tokens` (:826; wrappers split into function-preserving and function-bypassing sets), then grep flag parsing (`_mode_from_flags` :271, `_extract_patterns` :316).

Failure modes:

- shlex ValueError → `[]` (fail-open by design).
- shlex comment handling.
- `$"…"` is not handled.
- The three body scanners ignore `$'…'` inside the body, which their own decoding has already rewritten.

Callers: the hook itself only.

### 1.7 pretool-harness-switch-guard.py (274 lines)

Entry point: `writes_settings_file(command)` (:178) → `_segments(_without_message_bodies(cmd), shell_text_only=True)` (:96).

- Per `splitlines()` line: `shlex(posix, punctuation_chars=";&|")`. ValueError falls back to `str.split`.
- Nested `-…c` and eval words are re-segmented (depth 3).
- `_written_words` (:155) looks at redirect targets via `REDIRECT=^(?:\d*|&)>>?\|?(.*)` and at every word of a non-read-only command.

Failure modes, measured:

- **`echo x>settings.json` → False.** `>` is not in punctuation_chars, so `x>settings.json` is one token and the REDIRECT regex is anchored at the start. This is an under-block.
- Line splitting breaks multi-line quotes.
- There is no `$( )` descent.

Caller: the hook itself (`check_bash` :186).

### 1.8 stop-command-gate.py, userprompt-usage-snapshot.py, userprompt-consent-allowlist.sh

None of these three parses a Bash tool command in the shell-grammar sense:

- **stop-command-gate**: `_typed` (:327) and `_targets` (:346) run `shlex.split` on *slash-command arguments*. `close_stalled` (:461) tests Bash `tool_input.command` by substring (`STALL_CALL = ("resolve-dev-artifact-chain.py","--disposition")`, :457).
- **usage-snapshot**: `_adapter_command` (:140) runs `shlex.split(CLAUDE_USAGE_ADAPTER_CMD)` to build an argv for subprocess.
- **consent-allowlist.sh** (inline python :123-363): `shlex.split(body, posix=False)` of the `/allow` argument (:266), outer quotes stripped. Later (:453-560) `fnmatch` checks that pattern against the settings `permissions.deny` rules. The grant is matched against real commands elsewhere, in `lib/allowlist.py` (`_bash_subcommands` :286, `_strip_git_global_opts` :377, `match_sentinel_grant_for_bash_command` :418). That code is another private reader and is in scope for migration.

Shared-module needs:

- stop-gate: a `argv_split(str)` helper, and optionally `iter_simple_commands` to replace the substring test.
- snapshot: nothing.
- allowlist: `split_simple_commands` + `git_invocations`.

### 1.9 pretool-bash-safety.sh: parsing entry points only

| line | reader | how it is called |
|---|---|---|
| 301 | `lib/runtime_guard.py` (`runtime_guard/shell_lex.py`, 237 lines: `_split_pipeline`, `_safe_shlex`, `_write_redirect_targets`) | `_runtime_guard_fail_closed "$COMMAND"` |
| 326-337 | `bash_context_strip._process_heredocs`, `git_command_classifier._command_token_index`, `_git_subcommand`, plus inline `shlex.shlex(punctuation_chars=';&\|()\`')` | inline python heredoc (commit/config guard) |
| 705 | `lib/git_clean_guard.py` (its own `_lex` :212 with ANSI-C decode, `_split_segments`, `_resolve_command`) | `CMD_INPUT=… timeout python3` |
| 817-821 | `lib/allowlist.match_sentinel_grant_for_bash_command` | inline python |
| 862 | regex grep on the raw `$COMMAND` | shell |
| 1167-1171 | `bash_context_strip.py` CLI → `COMMAND_CONTEXT_STRIPPED` | subprocess, `ulimit -v`, timeout 2s |
| 1195-1215 | `git_command_classifier.py` CLI, `CMD_RAW=stdin` (stripped NUL raw) → `CLASSIFIER_JSON` | subprocess, plus a schema check |
| 1296-1440 | inline python: `shlex.shlex(posix, punctuation_chars=True)`, COMPOUND_TOKENS, RECURSIVE_SHELLS (bulk-commit sentinel) | inline |
| 1830-1835 | `bash_execution_boundary.py` CLI (`CMD_INPUT`, stdin payload `CMD_PAYLOAD=stdin`) | subprocess, `ulimit -v`, timeout 5s |
| 2365-2380 | `git_command_classifier._segments`, `_command_token_index`, `_git_subcommand`, `_unquote_token`, `_basename` | inline python (git clean fallback) |
| many | about 100 grep -E rules over `$COMMAND_CONTEXT_STRIPPED` / `$COMMAND` | shell |

Readers outside the requested list that the plan should also absorb:

- `lib/runtime_guard/shell_lex.py` (237 lines)
- `lib/git_clean_guard.py` `_lex` and segments (about 450 of 835 lines)
- `lib/allowlist.py` `_bash_subcommands` and `_strip_git_global_opts` (about 140 lines)
- `lib/grepguard_context_strip.py` (231 lines)
- the inline python blocks in bash-safety.sh (:326, :1296)
- `pretool-overnight-hook-guard.py` and `pretool-git-privilege-guard.py`, which use `shlex` directly

---

## 2. Experiment: `` echo $'a\'b' "$(echo x)" ``

Script: `parser/exp1.py`. It runs with HOME and GIT_CONFIG_GLOBAL pointed at the scratchpad.

```
CMD: echo $'a\'b' "$(echo x)"
 census: {"obligations": [], "fatal": ["unbalanced:single_quote"]}
 analyze: UNRESOLVED census_fatal:unbalanced:single_quote
 lex ok: [('W','echo'), ('W',"$'a\\'b'"), ('W','"$(echo x)"')]
CMD: echo $'ab' "$(echo x)"      -> census ok (substitution@12), analyze PROVEN_INERT
CMD: echo 'a'\''b' "$(echo x)"   -> census ok, analyze PROVEN_INERT
bash: a'b x
```

The census rejects the command; the analyzer's own lexer accepts it. The failing function is `census()` in `hooks/lib/bash_active_syntax_census.py`:

1. At `$` (:235) the next char is `'`. That matches none of `( [ {`, so the code takes `i += 1` (:275).
2. The `'` branch (:184) then does `text.find("'", i+1)`, which knows nothing about ANSI-C `\'`. It closes at the escaped quote.
3. The final `'` opens a quote that never closes, which gives `FATAL_UNBALANCED+":single_quote"` (:188).
4. `analyze()` (:4329) turns any fatal into UNRESOLVED before the lexer runs. The lexer does handle this case (`_find_ansi_end` :344).

**Over-block confirmed.** The differential run found other members of the same class:

- `git commit -m $'fix(x): it\'s a; b'` and `echo $'a\' #'; …` fail the same way.
- A comment holding an apostrophe, `git commit -m a # don't`, fails in **both** the census and `lex()`. The census has no comment state, and `lex()` only treats `#` as a comment right after an operator.

---

## 3. Pure-Python bash parser availability

- `bashlex`, `tree_sitter`, `tree_sitter_bash`, `tree_sitter_languages`, `lark` and `parsimonious` are **not installed** (ModuleNotFoundError under Python 3.13.18).
- No vendored copy exists anywhere in the repo (`find /` and grep for bashlex, tree-sitter, mvdan and shfmt).
- No `shfmt`, `gosh` or `osh` binary is on PATH.
- `pyparsing 3.1.1` is in the system dist-packages, but it is not a shell grammar.
- `requirements/py310.txt`, `py311.txt`, `py312.txt` and `tests/replay/requirements.txt` pin only the test stack: pytest 8.4.2, pytest-xdist, pyyaml, jsonschema, pygments, attrs and the like. No parser.
- **GNU bash 5.2.21** is at `/usr/bin/bash`. It can serve as an oracle in tests, never at hook runtime. `bash -n -c CMD` checks syntax only and executes nothing (used in `diff_census.py`). `declare -f` on a wrapping function gives a canonical re-serialisation, which would work for structural differential checks.

Conclusion: a shared module is hand-written, stdlib only, which matches the existing constraint that hooks import only the stdlib.

---

## 4. Corpus

Files holding Bash command test cases:

- `hooks/tests/fixtures/adversarial_corpus.json` (39 `payload`s; `docs/ADVERSARIAL-CORPUS.md` is only a human index, and nothing reads it). It is loaded by `test_blackbox_integration.py`, `test_privilege_guard_fails_closed.py`, `test_block_branch_pr_worktree_fails_closed.py`, `scripts/check-enforcement-evidence.py`, `scripts/generate-hero-status.py` and `tests/test_readme_regions.py`.
- `hooks/tests/fixtures/pol_iteration5_qa_matrix.v1.json` (416 commands), `pol_primary_laxity_ledger.json`, `pol_benign_strictness_exceptions.json`, `pol_installed_program_allow_set.json`. Loaded by `test_pol_generative_sweeps.py`, `pol_replay_harness.py` and `pol_sweep_generators.py`.
- 175 `hooks/tests/*.py` and 123 `tests/*.py` (including `tests/replay/*`). The heaviest are `test_runtime_guard.py`, `test_commit_hook_bypass_deny.py`, `test_bash_safety_git_clean.py`, `test_git_shell_c_strings.py`, `test_bash_safety_context_rules.py`, `test_block_branch_pr_worktree.py`, `tests/test_git_clean_guard_vectors.py` and `test_bash_execution_boundary.py`.
- `pol_sweep_generators.py` *generates* sweeps at runtime from the programs installed on PATH. The analyzer's comments cite 27,036 multi-position commands. Those depend on the host and were not expanded, because that would mean running repo code.

**Extraction:** `parser/extract_corpus.py` → `parser/corpus.json`. It is AST- and JSON-based and never imports or runs repo code.

- **strong**: values under the keys command, cmd, payload, raw or CMD_INPUT (in JSON or Python dicts and kwargs); first arguments of calls whose callee looks like a reader or hook runner; assignments to `*cmd*` or `*command*` names.
- **weak**: elements of lists, tuples and sets (parametrize rows, module tables). These are kept only when the command word is one used by a strong string, a program on PATH, a shell keyword, a path, or a dynamic head.
- f-strings are rendered with `PH` in place of each placeholder and flagged `template`.

**Result: 3,829 distinct command strings.**

- 1,002 strong, 2,827 weak, 330 templates, 209 multi-line.
- They come from 264 files, 124 of them under tests/replay.
- A sample put about 10% of the weak set as noise (prose, labels), so roughly **3,500 real commands**.

Differential against `bash -n` (`parser/diff_census.json`):

| bash -n | census | lex() | count |
|---|---|---|---|
| ok | ok | ok | 3,636 |
| ok | fatal | ok | 4 (all `$'…\'…'`) |
| ok | fatal | err | 13 (7 unterminated heredoc that bash accepts with a warning, 6 comments holding `'` or `"`) |
| err | * | * | 176 (mostly templates and fragments) |

---

## 5. Proposed shared module

Working name: `hooks/lib/shell_parse.py`. It is stdlib only, never executes anything, and every offset maps back to the raw input.

### 5.1 Data model

```python
Span = tuple[int, int]                     # raw offsets (continuations mapped back)

class Quote(Enum): BARE, SINGLE, DOUBLE, ANSI_C, LOCALE, ESCAPED    # ESCAPED = backslash-quoted char

@dataclass(frozen=True)
class Part:                                # one chunk of a word, with quote provenance
    kind: Literal["lit","param","cmdsub","backtick","arith","procsub_in","procsub_out",
                  "glob","extglob","brace","tilde","arraylit"]
    text: str                              # lit: decoded value (ANSI-C decoded, escapes removed); else raw body
    raw: str; quote: Quote; span: Span
    body: "Script | None" = None           # parsed nested commands: cmdsub/backtick/procsub
    reexpand: bool = False                 # ${!x} ${x@P|E|A}

@dataclass(frozen=True)
class Word:
    parts: tuple[Part, ...]; raw: str; span: Span
    def literal(self) -> str | None        # static value or None (any computed part)
    def static_prefix(self) -> str
    def quoted(self) -> bool               # any non-BARE part
    def substitutions(self) -> list["Script"]

@dataclass(frozen=True)
class Heredoc:
    delim: str; quoted: bool; strip_tabs: bool
    body: str; body_span: Span; expansions: tuple[Part, ...]   # empty when quoted
    terminated: bool                       # False = ended at EOF (bash warns, still runs)

@dataclass(frozen=True)
class Redirect:
    fd: int | None; fd_var: str | None     # 2>  /  {fd}>
    op: Literal["<",">",">>",">|","<>","<<","<<-","<<<",">&","<&","&>","&>>"]
    target: Word | None; dup: int | None; close: bool   # >&2 / >&-
    heredoc: Heredoc | None; span: Span

@dataclass(frozen=True)
class Assignment: name: str; index: Word | None; append: bool; value: Word | None; array: tuple[Word, ...] | None

@dataclass(frozen=True)
class SimpleCommand:
    assignments: tuple[Assignment, ...]; words: tuple[Word, ...]; redirects: tuple[Redirect, ...]
    span: Span; negated: bool; timed: bool
    def head(self) -> Word | None
    def argv(self) -> list[str | None]

@dataclass(frozen=True)
class Compound:
    kind: Literal["subshell","group","if","while","until","for","select","case","cond","arith","function"]
    header: tuple[Word, ...]               # for-list, case word/patterns, [[ ]] operands, function name
    body: tuple["Script", ...]; redirects: tuple[Redirect, ...]; span: Span

@dataclass(frozen=True)
class Pipeline: stages: tuple[SimpleCommand | Compound, ...]; pipes: tuple[Literal["|","|&"], ...]; negated: bool

@dataclass(frozen=True)
class Script:                              # a command list
    items: tuple[tuple[Pipeline, Literal[";","&","&&","||","\n",""]], ...]
    source: str; span: Span
    error: "ParseError | None"             # explicit; items hold what parsed before it

@dataclass(frozen=True)
class ParseError:
    code: Literal["single_quote","double_quote","ansi_quote","cmdsub","backtick","param","arith",
                  "procsub","heredoc_delim","redirect_missing_target","unbalanced_group",
                  "unexpected_token","depth_limit","size_limit"]
    offset: int; context: str
```

Rules for the model:

- `parse(text, *, max_depth=24, max_len=262_144) -> Script` never raises.
- When `error` is set, the parse is partial and every consumer must fail closed. The model never guesses a repair.
- Comments become part of no word. They follow bash's rule: `#` at the start of a word.

### 5.2 Derived views (pure functions)

| function | returns | replaces |
|---|---|---|
| `walk(script, *, into=("cmdsub","backtick","procsub","heredoc_shell","shell_c","eval","alias")) -> Iterator[Site]` | `Site(cmd: SimpleCommand, context, depth, fed: frozenset{"pipe","heredoc","herestring","file"}, dynamic: bool)` | Analyzer recursion, `_shell_layers`, grep-guard body scanners, harness `_segments` nesting |
| `resolve(cmd, tables=WRAPPERS) -> Resolved` | `head: Word`, `args`, `wrappers: list[(name, opts)]`, `payload: Script \| None` (bash/sh -c, eval, su -c, ssh, find -exec, xargs sh -c, a shell fed a heredoc or herestring), `unresolved: str \| None` | `_command_token_index`, `_find_command_word`, `_normalise_search_tokens`, `_prefix_wrapper`, the `_h_*` wrappers |
| `split_options(words, spec) -> (opts, operands, error)` | getopt-style, from `split_opts` | `split_opts`, `_positionals`, grep `_VALUE_FLAGS` |
| `write_targets(script) -> list[WriteTarget]` | `WriteTarget(path: Word, mode ∈ {truncate, append, create, link, copy_dest, move_dest, delete, in_place}, mechanism, source: Word \| None, fd, span, decidable: bool, nested_context)` | `extract_bash_write_targets_with_modes`, `extract_bash_touched_paths`, `_written_words`, `runtime_guard._write_redirect_targets` |
| `git_invocations(script) -> list[GitInvocation]` | `GitInvocation(word, path_qualified, globals: list[(opt, value: Word)], dirs: list[Word] (-C in order), config: list[(key, value)] (-c, --config-env), env: list[Assignment] (GIT_*), subcommand: Word \| None, args: tuple[Word], alias_body: Script \| None, context, unresolved: str \| None)` | `iter_git_invocations`, `classify_git_command` residuals, `_git_subcommand`, `_h_git`, `git_clean_guard._git_invocation`, `allowlist._strip_git_global_opts` |
| `active_sites(script) -> list[(kind, offset)]` | substitution, procsub, heredoc, param_reexpand | the analyzer's discharge bookkeeping |
| `executable_view(script) -> str` | the `strip_non_executable_contexts` text, rebuilt from the tree, for the about 100 grep rules in bash-safety.sh during migration | `bash_context_strip`, `grepguard_context_strip`, `command_without_heredoc_bodies` |
| `argv_split(text) -> list[str]` | shlex-compatible argv for config or argument strings | stop-gate `_typed`, usage-snapshot, consent-allowlist |
| CLI `python3 shell_parse.py --json` | the tree as JSON, plus any of the views by flag | the 3 subprocess call sites in bash-safety.sh |

### 5.3 Mapping each reader onto the API

| reader | needs | from the API |
|---|---|---|
| bash_execution_boundary | offset-exact words and parts, heredoc bodies, recursion with cond/alias Env, option splitting, a hard error | `parse`, `walk` (the alias Env stays analyzer state), `split_options`, `Script.error`, `active_sites`. Its handler and table logic (about 2,000 lines) stays as policy. |
| census | stays an **independent** scanner by contract | Keep it separate (about 250 lines), but fix `$'…'` and comments. Test it against `active_sites` and the bash oracle on the corpus. |
| bash_context_strip | quoted vs bare argument, command word, shell -c payload, heredoc owner | `executable_view` (Part.quote, `resolve().payload`) |
| bash_write_targets | redirect op and fd, verb plus positionals, quoted path value | `write_targets`. `_resolve_path` and `_resolve_sink` stay as path policy. |
| git_command_classifier | git word past wrappers, globals, -C/-c, subcommand, args, nested -c layers, runtime-feed info, residual kinds | `git_invocations` (unresolved → residual kinds), `walk().fed` |
| grep guard | grep argv with decoded patterns in every context that inherits the function shadow; bare vs path shell | `walk(into=…)`, `resolve()` (it keeps its own two wrapper sets as policy), `Word.literal()` (ANSI-C decoded) |
| harness-switch guard | redirect targets and write-capable argv, nested -c and eval, message heredocs excluded | `write_targets` plus `resolve` (fixes `x>settings.json`) |
| stop-command-gate | slash-command arg split; Bash command test | `argv_split`; optionally `walk` |
| usage-snapshot, consent-allowlist | argv split of a non-Bash string | `argv_split` (leave them as they are, or switch to the alias) |
| allowlist, runtime_guard/shell_lex, git_clean_guard, inline py in bash-safety | simple commands, git invocation, write redirects | `walk`, `git_invocations`, `write_targets` |

### 5.4 Base to keep

The base should be **bash_execution_boundary.py :192-711**: `Src` (the offset map), `Word`/segments, `Redir`, `_match_pair`, `_lex_dollar`, `_lex_backtick` (with the one-level unescape), `_lex_word` (array assignments, extglob, procsub, ANSI-C end, brace and glob segments), `_read_heredoc_delim` and `lex`. Also keep `split_opts`/`_spec`/`_resolve_long` (:713-944) and `ansi_decode` (:1597).

It is the only reader that is offset-exact, recursive, explicit about errors and already run against tens of thousands of sweep inputs. On top of it the work is:

- Add per-part quote provenance.
- Add the `&>`, `&>>`, `{fd}>`, `>&-`, `;;&` and `;&` operators.
- Make `#` start a comment at the start of any word.
- Match heredoc terminators exactly, with tabs stripped only for `<<-`.
- Add a real grammar layer that builds Pipeline, Compound and Script from the token stream, in place of keyword dropping.

The feed bookkeeping in `git_command_classifier._shell_words` (pipe, here-document, here-string, file, body_fed) is the model for `Site.fed`. The wrapper tables should merge from `_WRAPPER_VALUE_FLAGS` and `_WRAPPER_POSITIONALS` (classifier) and from WRAPPERS and the `_h_*` specs (analyzer).

### 5.5 Size estimate

| part | lines (code + about 15% comments) |
|---|---|
| lexer (ported, with quote provenance, operators, comments, heredocs, ANSI-C decode) | 650 |
| grammar layer (lists, pipelines, compounds, `[[ ]]`, `(( ))`, functions, case) | 400 |
| data model, errors, JSON CLI | 200 |
| `walk` + `resolve` + wrapper/payload tables | 400 |
| `split_options` | 150 |
| `write_targets` | 300 |
| `git_invocations` | 200 |
| `executable_view` + `argv_split` | 150 |
| **total** | **about 2,450 (range 2,100-2,800)** |

For comparison, the parse code in the listed readers is about 3,100 lines today (table below), not counting the readers listed in 1.9. After migration the policy code stays in each hook. The big win is in git_command_classifier, bash_write_targets, bash_context_strip, grepguard_context_strip and the grep guard's scanners, which drop to thin views.

---

## 6. Line breakdown per file

Method: `parser/linecount.py` (AST and tokenize). "Parse" counts the code lines of the functions listed in its `PARSE` table; "rule" is every other code line, including option tables. "Hist (marker)" counts comment or docstring lines that themselves hold a history marker: a date, task or spec id, `#NNN`, PR, "previously", "was added", "before this fix", iteration, QA Fn, codex#n, "measured", "no longer", "NOW handled", CLOSED, RISK-n, AC-n and similar. "Hist (para)" counts every line of each comment block or docstring paragraph that holds such a marker. That is the narrative a cleanup could move to git history.

| file | total | blank | comment/doc | parse code | rule code | hist (marker) | hist (para) |
|---|---|---|---|---|---|---|---|
| hooks/lib/bash_execution_boundary.py | 4,499 | 338 | 951 | 1,215 ¹ | 1,995 ² | 53 | 263 |
| hooks/lib/bash_active_syntax_census.py | 399 | 43 | 71 | 249 | 36 | 3 | 16 |
| hooks/lib/bash_context_strip.py | 440 | 49 | 34 | 222 | 135 | 0 | 0 |
| hooks/lib/bash_write_targets.py | 1,277 | 202 | 415 ³ | 296 | 364 | 13 | 70 |
| hooks/lib/git_command_classifier.py | 1,892 | 186 | 713 | 498 | 495 | 26 | 221 |
| hooks/pretool-grep-backtrack-guard.py | 1,253 | 106 | 362 | 439 | 346 | 15 | 62 |
| hooks/lib/grepguard_context_strip.py | 231 | 26 | 61 | 137 | 7 | 7 | 15 |
| hooks/pretool-harness-switch-guard.py | 274 | 43 | 33 | 60 | 138 | 0 | 0 |
| hooks/stop-command-gate.py | 942 | 127 | 261 | 4 | 550 | 3 | 28 |
| hooks/userprompt-usage-snapshot.py | 262 | 43 | 45 | 5 | 169 | 0 | 0 |
| hooks/userprompt-consent-allowlist.sh | 691 | 32 | 204 | (about 15 lines: shlex at :266) | 455 code | 13 | 50 |
| hooks/pretool-bash-safety.sh | 2,709 | 119 | 1,153 | (entry points only, §1.9) | 1,437 code | 91 | 594 |

¹ Includes `_shell`, `_prefix_wrapper` and `_ic_canonicalize`, which are half parsing and half policy. The pure lexer (:192-711) is about 430 code lines.
² Includes about 850 lines of option and wrapper tables (:713-1563).
³ About 120 of the 415 are doctest lines, which work as tests.

Largest history narratives:

- the `analyze()` overflow essay, bash_execution_boundary :4344-4405
- the classifier module header :15-75
- the `_segments_with_kind` docstring :138-183
- the "iteration N" notes throughout the analyzer
- bash-safety.sh: 594 paragraph lines
