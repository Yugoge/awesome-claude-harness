# P14-1 parser audit: shell_parse.py at 49cb7105 against real bash

Method: one finder per grammar class (quoting, expansions, compounds, redirections/heredocs, wrappers, git argv). Each finder ran every input under bash 5.2.21 in a sandbox with stub binaries that log argv, and compared that with parse/walk/resolve/write_targets/git_invocations. A second agent reproduced each candidate independently.

Result: 131 verified defects; 27 candidates were not reproduced or were not defects.

| impact | count |
|---|---|
| under-read-high | 88 |
| under-read-medium | 26 |
| over-read-low | 13 |
| accepts-invalid-low | 4 |

The full records (exact input, view, what the parser says, what bash does, evidence and the verifier's note) are in P14-parser-audit.json, ordered by impact.

## Index

| # | impact | view | class | input |
|---|---|---|---|---|
| 1 | under-read-high | walk | $(( fallback to $( ( .. | `echo $((rm q) )` |
| 2 | under-read-high | walk | (( compound misread when the text ends in )) | `((rm q);(rm t))` |
| 3 | under-read-high | walk | array literal ( .. | `arr=($(rm q))` |
| 4 | under-read-high | walk | brace part swallows substitutions | `echo {$(rm q),x}` |
| 5 | under-read-high | walk | bracket glob part swallows backtick substitutions | `echo [`rm${IFS}q`]` |
| 6 | under-read-high | walk | extglob pattern swallows substitutions | `[[ x == @($(rm q)\|y) ]]` |
| 7 | under-read-high | walk | ${ } / array-literal extent mismatched (swallows later commands) | `echo ${X:-$'\''}; rm q; echo \'}` |
| 8 | under-read-high | resolve | ANSI-C NUL truncation | `$'rm\0zz' q` |
| 9 | under-read-high | walk | arithmetic evaluation of quoted data executes subscripts | `let 'a[$(rm q)]=1'` |
| 10 | under-read-high | write_targets | projected variable not word-split / globbed | `X='q t'; rm $X` |
| 11 | under-read-high | write_targets | env projection ignores scope and control flow | `X=p; X=ok \| cat; echo hi > $X` |
| 12 | under-read-high | walk | variants of known (1): substitutions inside parameter expansion | `echo ${X:=$(rm q)}` |
| 13 | under-read-high | walk | variants of known (2): substitutions inside arithmetic | `echo $[$(rm q)]` |
| 14 | under-read-high | walk | line continuation removed inside comment / quoted heredoc (outside my class, distinct from | `echo hi # c \\nrm q` |
| 15 | under-read-high | parse/walk | arith command vs nested subshell disambiguation | `((echo a) ; (rm b))` |
| 16 | under-read-high | parse/walk | $(( arithmetic expansion vs $( (subshell) ) command substitution | `echo $((echo a); rm b)` |
| 17 | under-read-high | parse/walk | heredoc operator lexed inside (( )) and for (( )) | `((x=1<<true))\nrm -rf y\ntrue` |
| 18 | under-read-high | parse/walk/resolve | pipeline negation glued to a subshell | `!(rm a)` |
| 19 | under-read-high | parse/resolve/git_invocations | time reserved word options | `time -- rm a` |
| 20 | under-read-high | parse/walk/git_invocations/write_targets | brace group read as brace expansion | `f() { rm -rf x; echo "a, b"; }; f` |
| 21 | under-read-high | walk/executable_view/git_invocations | case pattern ')' inside $( ) / <( ) | `echo "$(case x in x) rm b;; esac)"` |
| 22 | under-read-high | resolve/walk | compound stdin not propagated to inner shells | `{ bash; } <<< 'rm x'` |
| 23 | under-read-high | walk | heredoc expansions on compound redirects (shell_parse.py:1730-1731 vs 1744-1748 for simple | `{ cat; } <<EOF\n$(rm x)\nEOF` |
| 24 | under-read-high | write_targets | write_targets assignment projection ignores subshell scope and control flow (shell_parse.p | `X=protected; (X=harmless); echo hi > $X` |
| 25 | under-read-high | write_targets | New variants of known (7) for the other compound kinds and redirect operators (if/while/un | `if true; then :; fi > o1` |
| 26 | under-read-high | walk | array assignment literal (out of class, found incidentally) | `X=($(rm a))` |
| 27 | under-read-high | resolve (heredoc_shell payload) / walk / write_targets / git_invocations | heredoc-shell payload is parsed from the raw body without the heredoc's backslash processi | `bash <<EOF\necho "\$(rm f1)"\nEOF` |
| 28 | under-read-high | parse / walk | Src.from_raw removes backslash-newline everywhere before lexing, including in quoted-delim | `cat <<'EOF'\nfoo\\nEOF\nrm f1\nEOF` |
| 29 | under-read-high | parse / walk | heredoc delimiter quote removal is wrong (double-quote backslash escapes, $'...' and $"... | `cat <<"E\$F"\nE$F\nrm f1\nE\$F` |
| 30 | under-read-high | parse / walk | `<<` inside an arithmetic command or arithmetic for is lexed as a heredoc | `(( x <<true ))\nrm f1\ntrue` |
| 31 | under-read-high | walk | heredoc inside $( ) / <( ): _match_pair counts ( ) ' " in the heredoc body | `x=$(cat <<'EOF'\n(\nEOF)\nrm f1\nEOF\n# )` |
| 32 | under-read-high | walk | heredoc body substitutions on a compound command's redirect are never walked (walk view; k | `while read l; do :; done <<EOF\n$(rm f1)\nEOF` |
| 33 | under-read-high | walk / resolve | a compound's stdin heredoc or here-string is not propagated to the shells inside it (fed o | `{ bash; } <<'EOF'\nrm f1\nEOF` |
| 34 | under-read-high | resolve | forms in which a shell reads its script from stdin are not recognised | `bash -s x <<'EOF'\nrm f1\nEOF` |
| 35 | under-read-high | resolve / executable_view / git_invocations | source or  | `source /dev/stdin <<'EOF'\ngit push --force\nEOF` |
| 36 | under-read-high | executable_view / git_invocations / walk | a heredoc piped into a shell is blanked as data by executable_view and never parsed as a p | `cat <<'EOF' \| bash\ngit push --force\nEOF` |
| 37 | under-read-high | walk / resolve | an inherited stdin heredoc reaches a shell that has no redirect of its own | `exec <<'EOF'\nrm f1\nEOF\nbash` |
| 38 | under-read-high | resolve (heredoc_shell payload) / walk | the <<- tab stripping is not applied to the body before it is parsed as a payload | `bash <<-EOF\n	cat <<X\n	X\n	rm f1\nX\nEOF` |
| 39 | under-read-high | walk / write_targets / executable_view / git_invocations | Unicode digits accepted by str.isdigit() in fd, dup and count handling | `rm f1 ²>/dev/null` |
| 40 | under-read-high | write_targets | tee option spec: --output-error treated as taking a separate value | `tee --output-error o1 < f1` |
| 41 | under-read-high | resolve | shell option cluster ending in o/O (-eo, -euo, -xO, +eo): _resolve_shell (shell_parse.py:2 | `bash -eo pipefail -c 'rm x'` |
| 42 | under-read-high | resolve | shell -c clustered with o/O: the option value is taken as the -c payload (shell_parse.py:2 | `bash -co pipefail 'rm x'` |
| 43 | under-read-high | resolve | lone '-' option terminator not honoured in _resolve_shell (len(v)>1 check at shell_parse.p | `bash -c - 'rm x'` |
| 44 | under-read-high | resolve | stdin-fed shell with operands: _resolve_shell returns before the heredoc/herestring check  | `bash -s a b <<< 'rm x'` |
| 45 | under-read-high | walk | shell fed by an inherited stdin redirect (compound, function call, outer -c shell, exec):  | `{ bash; } <<< 'rm x'` |
| 46 | under-read-high | walk | new variant of known (4): a here-string (not a heredoc) on another fd duplicated to stdin | `bash 3<<<'rm x' 0<&3` |
| 47 | under-read-high | resolve | source/ | `source /dev/stdin <<< 'rm x'` |
| 48 | under-read-high | walk | trap command strings are not a payload (no eval-like descent) | `trap 'rm x' EXIT` |
| 49 | under-read-high | resolve | BASH_ENV startup file fed from stdin or a procsub | `BASH_ENV=/dev/stdin bash -c : <<< 'rm x'` |
| 50 | under-read-high | walk | shell aliases defined in the same text | `shopt -s expand_aliases\nalias x=rm\nx f` |
| 51 | under-read-high | resolve | command-hash rebinding (hash -p, BASH_CMDS) | `hash -p /usr/bin/rm ls; ls x` |
| 52 | under-read-high | resolve | env lone '-' (split_options treats '-' as the first operand, shell_parse.py:1028) | `env - rm x` |
| 53 | under-read-high | resolve | env assignments limited to identifier names (_ASSIGN_RE at shell_parse.py:46/2015) | `env 'X-Y=1' rm x` |
| 54 | under-read-high | resolve | sudo VAR=value prefix after option parsing | `sudo VAR=1 rm x` |
| 55 | under-read-high | resolve | env -S split string is parsed as a command line, not re-fed to env's own option parser (sh | `env -S '-i rm x'` |
| 56 | under-read-high | resolve | env -S string read with bash grammar instead of env's escape/comment rules: wrong head or  | `env -S 'rm\_x'` |
| 57 | under-read-high | resolve | eval '--' not stripped (shell_parse.py:2037-2044) | `eval -- rm x` |
| 58 | under-read-high | resolve | optional-argument options typed as required-value in PEEL['xargs'] (shell_parse.py:1902-19 | `echo x \| xargs -i rm {}` |
| 59 | under-read-high | resolve | xargs replace-string inside a shell payload treated as static code | `echo 'rm x' \| xargs -I{} sh -c {}` |
| 60 | under-read-high | resolve | find -exec/-execdir/-ok/-okdir not peeled (find excluded at shell_parse.py:2096) | `find . -name x -exec rm {} \;` |
| 61 | under-read-high | resolve | watch not peeled (excluded at shell_parse.py:2097) | `watch -n 1 rm x` |
| 62 | under-read-high | resolve | runuser without -c excluded from peeling even though PEEL has its spec (shell_parse.py:209 | `runuser -u root -- rm x` |
| 63 | under-read-high | resolve | su payload forms: -c after '--', --session-command, -s shell | `su -- root -c 'rm x'` |
| 64 | under-read-high | resolve | sg not peeled | `sg root -c 'rm x'` |
| 65 | under-read-high | resolve | script -c not peeled | `script -qc 'rm x' /dev/null` |
| 66 | under-read-high | resolve | wrapper missing from WRAPPERS/PEEL (setpriv) | `setpriv --reuid=0 rm x` |
| 67 | under-read-high | resolve | boolean option typed as value in WRAPPERS['chroot'] (shell_parse.py:1792) | `chroot --skip-chdir / rm x` |
| 68 | under-read-high | resolve | optional-argument options typed as required-value in WRAPPERS['nsenter'] (shell_parse.py:1 | `nsenter -t $$ -m rm x` |
| 69 | under-read-high | resolve | taskset fixed-operand count 0 instead of 1, and -c/--cpu-list missing (shell_parse.py:1796 | `taskset 1 rm x` |
| 70 | under-read-high | walk | time keyword '--' terminator (grammar handles only -p, shell_parse.py:1284-1288) | `time -- rm x` |
| 71 | under-read-high | parse/git_invocations | empty-quoted-word-dropped | `git -C '' push origin main` |
| 72 | under-read-high | resolve/git_invocations | empty-quoted-word-dropped (wrapper option value) | `exec -a '' git push origin main` |
| 73 | under-read-high | git_invocations | alias-chain-config-not-propagated | `git -c alias.a=b -c alias.b=push a origin main` |
| 74 | under-read-high | git_invocations | config-precedence-order | `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.x GIT_CONFIG_VALUE_0=status git -c ali` |
| 75 | under-read-high | walk/write_targets | alias-body-not-walked | `git -c alias.x='!rm -rf f' x` |
| 76 | under-read-high | resolve/walk/git_invocations | wrapper-not-peeled (find -exec) | `find . -maxdepth 0 -exec git push origin main \;` |
| 77 | under-read-high | resolve/git_invocations | wrapper-not-peeled (runuser/sg/script) | `runuser -u root -- git push origin main` |
| 78 | under-read-high | resolve/git_invocations | wrapper-operand-count | `taskset 1 git push origin main` |
| 79 | under-read-high | resolve/git_invocations | wrapper-option-misread (env -) | `env - git push origin main` |
| 80 | under-read-high | resolve/git_invocations | xargs-optional-arg-options | `xargs -i git push origin main` |
| 81 | under-read-high | git_invocations | xargs-stdin-args-not-flagged | `echo --force \| xargs git push origin main` |
| 82 | under-read-high | resolve/walk/git_invocations | eval-double-dash | `eval -- 'git push origin main'` |
| 83 | under-read-high | resolve/git_invocations | env-S-escape-semantics | `env -S'git push origin main \c --dry-run'` |
| 84 | under-read-high | walk/git_invocations/write_targets | array-literal-substitution-not-walked | `a=( $(git push origin main) )` |
| 85 | under-read-high | resolve/walk | heredoc_shell variants (stdin script with operands / source) | `bash -s x <<< 'git push origin main'` |
| 86 | under-read-high | git_invocations | dashed-git-builtin | `/usr/lib/git-core/git-push origin main` |
| 87 | under-read-high | write_targets | git-write-target-base-dir | `git -C sub rm g` |
| 88 | under-read-high | git_invocations/walk | git-option-runs-shell (exec payloads) | `git rebase --exec='git push origin main' HEAD~1` |
| 89 | under-read-medium | walk | ! ( subshell read as extglob | `!(rm q)` |
| 90 | under-read-medium | walk | re-expansion of a statically assigned variable | `X='$(rm q)'; : ${X@P}` |
| 91 | under-read-medium | resolve | static brace expansion in command position not resolved | `{rm,q}` |
| 92 | under-read-medium | walk | $( ) body extent wrong; only nested errors() flags it | `echo $(echo ${X:-(}) ; rm q #)` |
| 93 | under-read-medium | parse (Script.errors) | _nested_scripts (shell_parse.py:1639-1653) iterates only walk() SimpleCommand sites, so Co | `[[ "$(case x in x) rm b;; esac)" ]]` |
| 94 | under-read-medium | executable_view | executable_view heredoc blanking ignores expansions (out of class, found incidentally) | `cat <<EOF\n$(rm x)\nEOF` |
| 95 | under-read-medium | resolve | a shell script read from a procsub, /dev/fd/N or a fd-variable heredoc is not parsed (incl | `bash <(cat <<'EOF'\nrm f1\nEOF\n)` |
| 96 | under-read-medium | parse (Redir.io) / walk / resolve / git_invocations / argv_split | quoted, escaped or out-of-range digit words before a redirect operator are taken as the fd | `rm "1">o19` |
| 97 | under-read-medium | git_invocations / resolve / executable_view | argv supplied to an xargs command from a static heredoc or here-string is not read | `xargs git <<< 'push --force origin main'` |
| 98 | under-read-medium | resolve | pipe-fed shell has no payload and no unresolved marker | `echo 'rm x' \| bash` |
| 99 | under-read-medium | resolve | shell running a process-substitution file or stdin | `bash <(echo rm x)` |
| 100 | under-read-medium | walk | prompt variables (PS4 with xtrace, PROMPT_COMMAND with -i) evaluated as code | `PS4='$(rm x)'; set -x; :` |
| 101 | under-read-medium | write_targets | xargs-supplied operands: a literal replace-string is reported as a decidable path, and std | `echo f \| xargs -I{} rm {}` |
| 102 | under-read-medium | write_targets | find write actions (-delete, -fprint/-fprintf/-fls) not in VERBS | `find . -name x -delete` |
| 103 | under-read-medium | resolve | real wrapper options missing from the specs, so the head is unresolved (flagged, but the c | `nice -5 rm x` |
| 104 | under-read-medium | write_targets | split_options: optional-argument long options (--interactive[=WHEN], --output-error[=MODE] | `yes \| rm --interactive x` |
| 105 | under-read-medium | write_targets | permute=True in _verb_targets ignores POSIXLY_CORRECT in the command's assignments, so the | `POSIXLY_CORRECT=1 cp f out -v` |
| 106 | under-read-medium | walk | command execution inside a sed script (e command, s///e) | `sed -n '1e rm x' f` |
| 107 | under-read-medium | walk/write_targets | git-config-runs-shell | `git -c core.editor='rm -f f' commit --allow-empty` |
| 108 | under-read-medium | write_targets | git-write-target-missing-forms | `git checkout HEAD~1 f` |
| 109 | under-read-medium | write_targets | git-write-target-dashdash | `git rm -- -f` |
| 110 | under-read-medium | resolve/git_invocations | wrapper-option-spec-incomplete | `nice -5 git push origin main` |
| 111 | under-read-medium | walk/git_invocations | deferred-or-aliased-code (trap/alias/hash) | `trap 'git push origin main' EXIT` |
| 112 | under-read-medium | walk/resolve | shell-runs-generated-code (procsub/pipe) | `. <(echo git push origin main)` |
| 113 | under-read-medium | git_invocations | git-config-state-across-commands | `git config alias.x push; git x origin main` |
| 114 | under-read-medium | git_invocations/walk | config-env-alias | `E='!git push origin main' git --config-env=alias.x=E x` |
| 115 | over-read-low | resolve | ANSI-C unknown escape decoded | `$'r\m' q` |
| 116 | over-read-low | resolve | reserved word after coproc | `coproc time rm a` |
| 117 | over-read-low | write_targets / Redir.writes | the >&N- / N>&M- move form is read as a file write | `echo a 3>o13 >&3-` |
| 118 | over-read-low | parse (Redir.io) / walk | fd number or {var} separated from its operator by a backslash-newline, and {arr[i]}> forms | `rm 1\\n>o1` |
| 119 | over-read-low | resolve | payload taken from a heredoc that a later stdin redirect overrides | `bash <<A 0<f1\nrm src\nA` |
| 120 | over-read-low | walk | heredoc operator inside a single-line $( ) whose body follows the line | `x=$(cat <<EOF) ; rm f1\nbody\nEOF\n` |
| 121 | over-read-low | resolve | over-reads in wrapper readings | `flock -c 'rm x' l` |
| 122 | over-read-low | git_invocations | git-help-version-rewrite | `git --help push` |
| 123 | over-read-low | git_invocations | git-query-options | `git --exec-path push origin main` |
| 124 | over-read-low | git_invocations | alias-resolution-over-read | `git -c alias.status=push status` |
| 125 | over-read-low | git_invocations | git-attached-global-option | `git -calias.x=push x origin main` |
| 126 | over-read-low | resolve | empty-quoted-word-dropped | `bash -c '' 'git push origin main'` |
| 127 | over-read-low | write_targets | git-option-abbreviation (write_targets) | `git rm --cach f` |
| 128 | accepts-invalid-low | parse | accepts text bash rejects | `echo x &>(rm q)` |
| 129 | accepts-invalid-low | parse | invalid compound and negation syntax accepted | `true \| ! rm a` |
| 130 | accepts-invalid-low | parse | redirect or heredoc operator followed by '#' or by another operator is accepted | `echo x >#o7` |
| 131 | accepts-invalid-low | parse | function body not required to be compound; bare coproc accepted | `f() rm x` |
