---
description: Single-use break-glass — bypass safety blocks for the next matching bash command this turn; requires an explicit narrow selector. Forms — /allow <command...> (literal, upgraded to regex only when it contains true regex metacharacters), /allow --tool <literal> (always literal, regex off), or /allow re:<anchored-regex> (explicit regex, must be anchored). Bare /allow with no argument is refused. Trailing tokens become an audit-log comment. Auto-expires at stop.
disable-model-invocation: true
---

(hook-only command; body is not injected because of `disable-model-invocation: true`. This line exists so the body is never empty — see commands/dev-command.md for the empty-body API-400 lesson.)
