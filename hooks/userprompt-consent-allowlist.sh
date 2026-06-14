#!/usr/bin/env bash
# UserPromptSubmit Hook: parse `/allow <pattern>` and write a single-use
# bypass flag for developer-class git blocks in pretool-bash-safety.sh.
#
# Step 0: if agent_id is present in the hook JSON input, exit 0 without writing
#         (subagent write-firewall — defense in depth with consume-path check).
# Step 1: extract prompt + session_id; detect `/allow ` prefix (case-sensitive).
# Step 2: derive an EXPLICIT, NARROWLY-scoped grant pattern from the argument.
#         REFUSE-BY-DEFAULT: when no explicit command pattern can be derived
#         (empty arg, no leading-ASCII command token, missing/empty flag operand,
#         empty/vacuous re: body) OR the derived regex is effectively universal
#         (matches commands unrelated to a named token), the hook writes NO grant
#         on EITHER channel, removes any stale grant, prints a usage error, and
#         exits 0 without wedging the session. There is NO wildcard fallback.
#         Pattern passed via env var — never shell-interpolated into Python source.
# Step 3: on an explicit narrow grant only: write the legacy flag
#         /tmp/claude-bash-allowlist-<sid>.json with {pattern, is_regex} AND the
#         structured per-task sentinel; log to ~/.claude/logs/bash-consent.log.
#
# Exit 0 always. Stop hook (stop-cleanup-allowlist.sh) wipes any unconsumed flag.
set -u

INPUT=$(cat)

# ── Step 0: subagent write firewall ─────────────────────────────────
IS_SUBAGENT=$(echo "$INPUT" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print('1' if d.get('agent_id') else '0')" \
  2>/dev/null)
if [ "$IS_SUBAGENT" = "1" ]; then
  exit 0
fi

# ── Step 1: extract prompt + session_id ────────────────────────────
PROMPT=$(echo "$INPUT" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(d.get('prompt',''))" \
  2>/dev/null)
SID=$(echo "$INPUT" | python3 -c \
  "import json,sys,os; d=json.load(sys.stdin); print(d.get('session_id','') or os.environ.get('CLAUDE_SESSION_ID','default'))" \
  2>/dev/null)
[ -z "$SID" ] && SID="default"

# ── Stale-grant cleanup (AC15) ──────────────────────────────────────
# Remove EVERY pre-existing grant file the consumer's loader would honor for
# this SID/TASK_ID: the legacy per-session flag, the canonical per-task
# sentinel, AND every suffixed '<task_id>-*.json' sentinel (the full loader
# glob — hooks/lib/allowlist.py _enumerate_sentinel_grant_files). Invoked on
# EVERY refusal path so no stale broad grant can survive an /allow that does
# not result in a written narrow grant. Defining property: on ANY /allow that
# does not write a narrow grant, no stale grant may survive.
_remove_stale_grants() {
  local task_id="${CLAUDE_TASK_ID:-${SID}}"
  rm -f "/tmp/claude-bash-allowlist-${SID}.json" 2>/dev/null
  rm -f "/tmp/claude-grants/${task_id}.json" 2>/dev/null
  rm -f "/tmp/claude-grants/${task_id}"-*.json 2>/dev/null
}

# Only fire on `/allow ` prefix (case-sensitive). Trailing space required so
# `/allow-something-else` does not trigger.
case "$PROMPT" in
  "/allow "*|"/allow") ;;
  *) exit 0 ;;
esac

# ── Step 2: parse flags + optional comment; derive an EXPLICIT narrow grant ──
# REFUSE-BY-DEFAULT: there is NO wildcard fallback anywhere below. When an
# explicit, narrowly-scoped command pattern cannot be derived, the parser emits
# STATUS=REFUSE and the shell writes no grant, removes any stale grant, prints a
# usage error, and exits 0 (non-wedging).
#
# Syntax (explicit-command forms only — each must name a concrete command):
#   /allow --tool rm                        -> literal pattern "rm"
#   /allow --tool rm 删冗余文件             -> literal "rm" + CJK comment
#   /allow git stash                        -> literal pattern "git stash"
#   /allow re:^git\s+stash                  -> anchored narrow regex
#   /allow Write /abs/path                  -> path-scoped Write grant
#   /allow Write                            -> bare Write carve-out (any target)
# Refused (no grant written): /allow (no arg); /allow <CJK-only> (no leading
#   ASCII command token); /allow --tool (missing/empty operand); /allow re:
#   (empty/quote-only regex body); any effectively-universal regex (e.g. .*, ^,
#   a?, [\s\S]*, re:git unanchored) that would match commands unrelated to a
#   concrete named command token.
#
# Output protocol (5 lines): STATUS(GRANT|REFUSE) / PATTERN / IS_REGEX / COMMENT
#   / REFUSE_REASON. The pattern value is passed back via this protocol, never
#   shell-interpolated into Python source.
PARSED=$(PROMPT="$PROMPT" python3 -c "
import os, shlex
import re as _re
p = os.environ.get('PROMPT','')
body = ''
if p.startswith('/allow '):
    body = p[len('/allow '):]
elif p == '/allow':
    body = ''

REFUSE_REASON = ''

def emit(status, pattern='', is_regex=False, comment='', reason=''):
    print(status)
    print(pattern)
    print('true' if is_regex else 'false')
    print((comment or '').strip())
    print(reason or '')
    raise SystemExit(0)

def has_true_regex_meta(s):
    # Signals regex INTENT for a bare (non-re:) token. Deliberately EXCLUDES a
    # bare '.' so legitimate dotted commands (foo.bar, ./x.sh, python3.11) are
    # treated as LITERAL grants, not regexes (otherwise they would be wrongly
    # refused as unanchored regexes). KIND-C universals (.*, a?, a*, ^, \$,
    # [..]) all carry a TRUE metacharacter and are still routed to the regex
    # universal gate.
    return bool(_re.search(r'[\^\$*+?\[\]\(\){}|\\\\]', s))

def has_alnum_command_char(s):
    # A concrete command token must contain at least one alphanumeric character.
    return bool(_re.search(r'[A-Za-z0-9]', s))

def is_forbidden_regex(pat):
    # Returns (forbidden: bool, reason: str). reason in {'vacuous','universal',''}.
    #
    # AC13 PART-2 — SUFFICIENT static anchor-and-bounded-literal rule that
    # validates the WHOLE pattern, not only the command head. A regex grant is
    # allowed ONLY if it (1) starts with ^ (or \\A), (2) exposes a finite literal
    # command-head terminated by a REAL boundary (\$ | \\s+ | \\s | (?:\\s|\$) |
    # end — NOT the zero-width \\s* / \\s? / \\s{0,..}), and (3) the ENTIRE
    # remaining body contains NO over-breadth construct anywhere: no top-level
    # alternation (|), no unescaped any-char (.), no DOTALL flag, no catch-all
    # char-class ([\\s\\S]/[\\d\\D]/[\\w\\W] or one containing a newline), and no
    # \\S/\\D/\\W or zero-width-quantified \\s/\\d/\\w. This blocks a valid prefix
    # that ALSO carries a universal branch, e.g. ^git\\s+stash\$|.* (B1). A
    # bounded anchored literal+class pattern such as
    # ^git\\s+stash\\s+--message=[A-Za-z0-9_-]+\$ stays GRANTED because none of
    # those breadth constructs appear. Defining property: a grant is forbidden
    # iff its matcher would accept commands unrelated to a concrete command token
    # the user named. A literal denylist or corpus-only oracle is insufficient.
    if pat is None or pat == '' or pat.strip() == '':
        return True, 'vacuous'
    if pat in (chr(0x27)*2, chr(0x22)*2):   # '' or \"\" — quote-only vacuous body
        return True, 'vacuous'
    if pat.startswith('\\\\A'):
        rest = pat[2:]
    elif pat.startswith('^'):
        rest = pat[1:]
    else:
        return True, 'universal'            # unanchored -> over-broad (KIND-B)
    n = len(rest)
    # (1) literal command-head must exist immediately after the anchor.
    i = 0
    head_len = 0
    while i < n:
        c = rest[i]
        if c == '\\\\':
            if i + 1 >= n:
                return True, 'universal'    # trailing backslash, malformed
            nxt = rest[i+1]
            if nxt in ('s','S','d','D','w','W','b','B','A','Z','n','r','t'):
                break                       # class/boundary ends the head
            head_len += 1                   # \\. \\- \\/ -> literal escaped char
            i += 2
            continue
        if c in set('.*+?[]()|{}^\$') or c == ' ':
            break
        head_len += 1
        i += 1
    if head_len == 0:
        return True, 'universal'            # no concrete literal command-head
    # (2) the char right after the head must begin a REAL boundary.
    tail = rest[i:]
    if tail != '':
        if tail[0] == '\$' or tail.startswith('(?:\\\\s|\$)'):
            pass
        elif tail.startswith('\\\\s'):
            q = tail[2:3]
            if q in ('*', '?'):
                return True, 'universal'    # \\s* / \\s? are NOT boundaries
            if q == '{':
                m = _re.match(r'\{(\d+)', tail[2:])
                if m and int(m.group(1)) == 0:
                    return True, 'universal' # \\s{0,..} zero lower bound
        else:
            return True, 'universal'        # something non-boundary follows head
    # (3) whole-body breadth scan; (?:\\s|\$) is an atomic boundary token.
    j = 0
    while j < n:
        if rest[j:j+8] == '(?:\\\\s|\$)':
            j += 8
            continue
        c = rest[j]
        if c == '\\\\':
            if j + 1 >= n:
                return True, 'universal'
            nxt = rest[j+1]
            if nxt in ('S', 'D', 'W'):
                return True, 'universal'    # negated classes are catch-alls
            if nxt in ('s', 'd', 'w'):
                q = rest[j+2:j+3]
                if q in ('*', '?'):
                    return True, 'universal'
                if q == '{':
                    m = _re.match(r'\{(\d+)', rest[j+2:])
                    if m and int(m.group(1)) == 0:
                        return True, 'universal'
            j += 2
            continue
        if c == '.':
            return True, 'universal'        # unescaped any-char
        if c == '|':
            return True, 'universal'        # alternation -> over-broad branch
        if c == '[':
            k = rest.find(']', j + 1)
            if k == -1:
                return True, 'universal'    # unterminated class
            cls = rest[j+1:k]
            if ('\\\\s' in cls and '\\\\S' in cls) or ('\\\\d' in cls and '\\\\D' in cls) \
               or ('\\\\w' in cls and '\\\\W' in cls) or ('\n' in cls):
                return True, 'universal'    # catch-all char-class
            j = k + 1
            continue
        if c == '(':
            if rest[j:j+3].startswith('(?s'):
                return True, 'universal'    # DOTALL flag broadens matching
            j += 1
            continue
        j += 1
    return False, ''

try:
    raw_tokens = shlex.split(body, posix=False) if body else []
except ValueError:
    raw_tokens = body.split() if body else []
tokens = []
for t in raw_tokens:
    if len(t) >= 2 and t[0] == t[-1] and t[0] in (chr(0x22), chr(0x27)):
        t = t[1:-1]
    # Protocol-injection guard: a token carrying a newline / carriage-return
    # would desync the line-oriented STATUS/PATTERN/IS_REGEX/COMMENT protocol
    # (a crafted token could forge STATUS=GRANT or smuggle a wildcard PATTERN).
    # Such tokens never name a legitimate command -> REFUSE.
    if ('\n' in t) or ('\r' in t):
        emit('REFUSE', reason='control_char_in_token')
    tokens.append(t)

flag_pattern = None
bare = []
i = 0
while i < len(tokens):
    t = tokens[i]
    if t == '--tool':
        # AC10: recognized flag with a missing operand -> REFUSE.
        if i + 1 >= len(tokens):
            emit('REFUSE', reason='missing_flag_operand')
        operand = tokens[i+1]
        # AC10: recognized flag with an empty/whitespace-only operand -> REFUSE.
        if operand == '' or operand.strip() == '':
            emit('REFUSE', reason='empty_flag_operand')
        flag_pattern = operand
        i += 2
    else:
        bare.append(t)
        i += 1

if flag_pattern is not None:
    # --tool declares an explicit literal pattern; force is_regex=False
    # unconditionally (dotted filenames must not be misclassified as regex).
    emit('GRANT', pattern=flag_pattern, is_regex=False, comment=' '.join(bare))
elif bare:
    first = bare[0]
    if first.startswith('re:'):
        pat = first[3:]
        # AC14: empty / vacuous re: body names no concrete command -> REFUSE
        # BEFORE any wildcard fallback could re-coerce it.
        forbidden, reason = is_forbidden_regex(pat)
        if forbidden:
            emit('REFUSE', reason=reason)
        emit('GRANT', pattern=pat, is_regex=True, comment=' '.join(bare[1:]))
    elif first == 'Write' and len(bare) >= 2 and bare[1].startswith('/'):
        # Bare /allow Write /path form: second token is a path argument, not a
        # comment. Emit a path-scoped grant (sentinel target=path).
        emit('GRANT', pattern='Write ' + bare[1], is_regex=False,
             comment=' '.join(bare[2:]))
    else:
        # Bare command form: take leading ASCII tokens as the command; the
        # first non-ASCII token (e.g. a CJK comment) ends the command.
        ascii_bare = []
        for t in bare:
            if any(ord(c) >= 128 for c in t):
                break
            ascii_bare.append(t)
        comment_bare = bare[len(ascii_bare):]
        # AC2/AC3: no leading-ASCII command token derivable -> REFUSE (no
        # wildcard fallback).
        if not ascii_bare:
            emit('REFUSE', reason='no_command_token')
        pattern = ' '.join(ascii_bare)
        # Auto-detect regex from a TRUE regex metacharacter only (a bare '.' does
        # NOT count, so legitimate dotted commands like foo.bar / ./x.sh /
        # python3.11 stay LITERAL — codex finding 4). KIND-C universals (.*, a?,
        # a*, ^, \$, [..]) carry a true meta and are routed to the universal gate.
        is_regex = has_true_regex_meta(pattern)
        if is_regex:
            # AC5/AC13 KIND-C: a bare auto-detected regex that is effectively
            # universal -> REFUSE.
            forbidden, reason = is_forbidden_regex(pattern)
            if forbidden:
                emit('REFUSE', reason=reason)
        elif not has_alnum_command_char(pattern):
            # A bare LITERAL with no alphanumeric command character (e.g. a lone
            # '.') names no concrete command and would substring-match almost any
            # command -> REFUSE as vacuous (AC13 KIND-C lone '.').
            emit('REFUSE', reason='vacuous')
        emit('GRANT', pattern=pattern, is_regex=is_regex,
             comment=' '.join(comment_bare))
else:
    # AC1: bare /allow with no argument -> REFUSE (no wildcard fallback).
    emit('REFUSE', reason='no_argument')
" 2>/dev/null)
PARSED_STATUS=$(echo "$PARSED" | sed -n '1p')
PATTERN=$(echo "$PARSED" | sed -n '2p')
PARSED_IS_REGEX=$(echo "$PARSED" | sed -n '3p')
COMMENT=$(echo "$PARSED" | sed -n '4p')
IS_REGEX="$PARSED_IS_REGEX"

# ── Refuse gate (AC1-AC5, AC10, AC13, AC14): no explicit narrow command was
# derivable, OR the derived regex is effectively universal. Write NO grant on
# EITHER channel, remove any stale grant for this SID/TASK_ID across the full
# loader glob (AC15), print a usage error, and exit 0 (non-wedging). This runs
# BEFORE the nested-quantifier check, the audit log, and both grant writes. If
# the Python parser failed to emit a recognized status, fail closed (REFUSE).
if [ "$PARSED_STATUS" != "GRANT" ]; then
  _remove_stale_grants
  echo "[allow] ERROR: refused — you must name an explicit command to allow." >&2
  echo "[allow] /allow records a NARROW single-use bypass; it has no wildcard default." >&2
  echo "[allow] Examples: '/allow --tool rm', '/allow git stash', '/allow re:^git\\s+stash', '/allow Write /abs/path'." >&2
  echo "[allow] Refused because no explicit, narrowly-scoped command pattern could be derived (empty/under-specified argument or an effectively-universal regex)." >&2
  exit 0
fi

# ── V1b: structural rejection of catastrophic-backtracking regex shapes ──
# Defense-in-depth for V1 (SIGALRM consumer-side timeout). Reject nested-quantifier
# patterns like (a+)+, (a*)*, (a|b)+ at WRITE time so they never reach the consumer.
# Heuristic: body contains '(...)' with '+' or '*' inside the group AND the group is
# followed by '+' or '*' — structural shape of catastrophic backtracking.
if [ "$IS_REGEX" = "true" ]; then
  STRUCT_CHECK=$(ALLOW_PATTERN="$PATTERN" python3 -c "
import os, re, sys
p = os.environ['ALLOW_PATTERN']
# Nested-quantifier detector: group containing + or *, followed by + or *
if re.search(r'\([^)]*[+*][^)]*\)[+*]', p):
    print('REJECT')
else:
    print('OK')
" 2>/dev/null)
  if [ "$STRUCT_CHECK" = "REJECT" ]; then
    # AC15 uniformity: the nested-quantifier rejection is a REFUSAL too — it
    # writes no narrow grant — so it MUST remove any pre-existing stale grant
    # across the full loader glob before exiting, exactly like the refuse gate.
    # The distinct nested-quantifier stderr message (required by AC11) is kept.
    _remove_stale_grants
    echo "[allow] ERROR: pattern rejected — contains nested quantifier (e.g., (a+)+, (a*)*) which risks catastrophic backtracking." >&2
    echo "[allow] Use a more specific literal pattern or a bounded-quantifier regex instead." >&2
    exit 0
  fi
fi

# ── Step 3: write flag via env-var Python (no shell interpolation) ──
FLAG="/tmp/claude-bash-allowlist-${SID}.json"
ALLOW_PATTERN="$PATTERN" ALLOW_IS_REGEX="$IS_REGEX" FLAG_PATH="$FLAG" python3 -c "
import json, os
data = {
    'pattern': os.environ['ALLOW_PATTERN'],
    'is_regex': os.environ['ALLOW_IS_REGEX'] == 'true',
}
with open(os.environ['FLAG_PATH'], 'w') as f:
    json.dump(data, f)
" 2>/dev/null

# ── Audit log ───────────────────────────────────────────────────────
CONSENT_LOG="$HOME/.claude/logs/bash-consent.log"
mkdir -p "$(dirname "$CONSENT_LOG")"
if [ -n "$COMMENT" ]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) sid=$SID GRANTED pattern='$PATTERN' is_regex=$IS_REGEX comment='$COMMENT'" >> "$CONSENT_LOG"
else
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) sid=$SID GRANTED pattern='$PATTERN' is_regex=$IS_REGEX" >> "$CONSENT_LOG"
fi

if [ -n "$COMMENT" ]; then
  echo "[allow] Grant recorded: pattern='$PATTERN' is_regex=$IS_REGEX comment='$COMMENT'. Valid for ONE matching bash call this turn."
else
  echo "[allow] Grant recorded: pattern='$PATTERN' is_regex=$IS_REGEX. Valid for ONE matching bash call this turn."
fi

# ── Step 4: write sentinel grant (task 20260519-211515 R2 / AC2) ──
# Sentinel-file grant lifecycle: /tmp/claude-grants/<task_id>.json contains
# {task_id, session_id, allowed_operations[], created_at, expires_at}.
# The legacy pattern-string grant (above) remains for back-compat; the new
# sentinel is a STRUCTURED grant that hooks/lib/allowlist.py reads via
# load_sentinel_grant_for_task() — predicate never substring-matches against
# the command line.
#
# Literal patterns: single {op, target?, args_contain?} entry.
# Regex patterns: {op:"*", regex:<pattern>} entry. match_sentinel_grant_for_bash_command()
#   tests re.search(regex, subcommand) for op="*" entries, enabling regex grants to
#   reach subagents (which cannot use the legacy grant path).
#   S1 early-exit removed (task 20260524-133650 gap-1 fix): regex grants now write a
#   sentinel so subagents are covered. CF-1 (sentinel-exists-but-no-match suppresses
#   legacy path) no longer applies because the matcher now returns a match for regex.
#
# Atomic write-temp+rename so partial files never appear.
TASK_ID="${CLAUDE_TASK_ID:-${SID}}"
SENTINEL_DIR="/tmp/claude-grants"
mkdir -p "$SENTINEL_DIR" 2>/dev/null
SENTINEL_FILE="${SENTINEL_DIR}/${TASK_ID}.json"
SENTINEL_TMP="${SENTINEL_FILE}.tmp.$$"
ALLOW_PATTERN="$PATTERN" \
  ALLOW_IS_REGEX="$IS_REGEX" \
  SENTINEL_TMP="$SENTINEL_TMP" \
  SID="$SID" \
  TASK_ID="$TASK_ID" \
  python3 -c "
import json, os, time
pattern = os.environ['ALLOW_PATTERN']
is_regex = os.environ.get('ALLOW_IS_REGEX') == 'true'
now = time.time()
# Default sentinel TTL: 300s. Aligns with bash-safety grant window.
ttl = 300
if is_regex:
    # Regex sentinel: op='*' with 'regex' field. The matcher (allowlist.py
    # match_sentinel_grant_for_bash_command) runs re.search(regex, subcommand)
    # for op='*' entries, allowing regex grants to reach subagents.
    entry = {'op': '*', 'regex': pattern}
else:
    # Literal patterns produce a single structured op entry.
    parts = pattern.split(None, 1)
    op = parts[0] if parts else pattern
    rest = parts[1] if len(parts) >= 2 else ''
    entry = {'op': op}
    if op == 'Write' and rest:
        # Write ops use 'target' for exact-path scoping (not args_contain).
        # Matcher key-presence logic requires this field name. (ORIGINAL fix)
        entry['target'] = rest
    elif rest:
        entry['args_contain'] = rest.split()
ops = [entry]
grant = {
    'task_id': os.environ['TASK_ID'],
    'session_id': os.environ['SID'],
    'allowed_operations': ops,
    'created_at': now,
    'expires_at': now + ttl,
}
with open(os.environ['SENTINEL_TMP'], 'w') as f:
    json.dump(grant, f)
" 2>/dev/null && mv -f "$SENTINEL_TMP" "$SENTINEL_FILE" 2>/dev/null

exit 0
