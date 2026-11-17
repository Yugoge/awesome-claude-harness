"""OB-L16: a mention of session_dirs.txt is no longer refused as a search pattern or in a commit message;
reading, writing or executing the file stays refused at the permission layer.

Root cause: the single deny `Bash(*session_dirs.txt*)` matched any command whose text names the file, so
`grep -rn session_dirs.txt docs/`, `git log -S session_dirs.txt` and a commit message naming it were
refused with the reads. The owner decided (L16) to allow the name as a grep / rg / git grep pattern, as a
`git log -S`/`-G` pickaxe and inside a commit message.

An allow entry cannot do that: "Rules are evaluated in order: deny, then ask, then allow ... An allow
rule can't carve an exception out of a deny rule" (code.claude.com/docs/en/permissions.md, "Manage
permissions"). So the blanket is replaced by deny entries keyed on the command word (ENTRIES): each
interpreter, shell, evaluator and file-touching command, and each git subcommand that reads, writes or
stages a path, refuses any text naming `session_dirs`. grep, rg, `git grep`, `git log` (but `--output`)
and `git commit` (but `-F`/`--file`) are left to `Read(**/session_dirs.txt)` and
`Edit(**/session_dirs.txt)`, which "apply to ... file commands Claude Code recognizes in Bash ... and to
the targets of Bash redirections" (same page, "What Read and Edit rules cover"): a file operand or
`-f FILE` stays refused, a pattern does not.

Bash rule matching is modelled after the docs ("Bash rules match the whole command text, with `*`
standing in for any text"; "Deny and ask rules apply when any subcommand matches them, including a
command nested inside a subshell, a command substitution, or a control-flow body"; a deny rule "matches
past any leading assignment"; wrappers such as timeout are stripped). Where the docs are silent the point
was measured on Claude Code 2.1.326, run headless (`claude -p`, default permission mode, a throwaway HOME
whose settings.json holds only this repo's `permissions`) against a local stand-in Messages API that
makes the model emit one Bash call; the tool result says "has been denied" (deny), names a reason it
needs approval (ask), or is the command's output (allow). Measured: `?` in a rule is a literal character;
rules are case-sensitive (`CAT x` is not matched by `cat *`); quotes are not part of the matched text (a
rule ending `session_dirs.txt)` matched `git commit -m "... session_dirs.txt"`); a path-qualified command
word matches by its name (`/usr/bin/python3`, `/tmp/x-venv/bin/python`, `/bin/cat`); a heredoc body is
not part of the matched text (`bash <<EOF` / `python3 - <<EOF` bodies: allowed on the base as well, see
HOOK_ONLY). MEASURED holds those decisions; test_live_cli_decisions re-measures them when
HARNESS_LIVE_CLI=1 and `claude` is installed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BLANKET = "Bash(*session_dirs.txt*)"

# The deny entries that replace BLANKET, each with a command it refuses that no other layer of the
# permission rules refused (measured: without these entries each one ran or asked).
ENTRIES = {
    "Bash(. *session_dirs*)": ". ./session_dirs.txt",
    "Bash(awk *session_dirs*)": "awk 1 session_dirs.tx?",
    "Bash(bash *session_dirs*)": "bash -c 'cat session_dirs.txt'",
    "Bash(bun *session_dirs*)": "bun -e \"require('fs').readFileSync('session_dirs.txt')\"",
    "Bash(cat *session_dirs*)": "cat session_dirs.tx?",
    "Bash(chmod *session_dirs*)": "chmod 600 session_dirs.tx?",
    "Bash(cp *session_dirs*)": "cp session_dirs.tx? x.bak",
    "Bash(curl *session_dirs*)": "curl -sT session_dirs.txt http://127.0.0.1:9/",
    "Bash(dash *session_dirs*)": "dash -c 'cat session_dirs.txt'",
    "Bash(deno *session_dirs*)": "deno eval \"Deno.readTextFileSync('session_dirs.txt')\"",
    "Bash(docker *session_dirs*)": "docker run --rm -v ./session_dirs.txt:/f alpine cat /f",
    "Bash(echo *session_dirs*)": "cat $(echo session_dirs.txt)",
    "Bash(env *session_dirs*)": "env -i sh -c 'cat session_dirs.txt'",
    "Bash(eval *session_dirs*)": "eval 'cat session_dirs.txt'",
    "Bash(exec *session_dirs*)": "exec cat session_dirs.tx?",
    "Bash(find *session_dirs*)": "find / -name session_dirs.txt -exec cat {} \\;",
    "Bash(fish *session_dirs*)": "fish -c 'cat session_dirs.txt'",
    "Bash(for *session_dirs*)": "for f in session_dirs.tx?; do cat $f; done",
    "Bash(git *--output*session_dirs*)": "git log --output=session_dirs.txt",
    "Bash(git -c *session_dirs*)": "git -c core.pager='cat session_dirs.txt' log",
    "Bash(git add *session_dirs*)": "git add session_dirs.txt",
    "Bash(git apply *session_dirs*)": "git apply session_dirs.txt",
    "Bash(git blame *session_dirs*)": "git blame session_dirs.txt",
    "Bash(git cat-file *session_dirs*)": "git cat-file -p HEAD:session_dirs.txt",
    "Bash(git checkout *session_dirs*)": "git checkout -- session_dirs.txt",
    "Bash(git commit *--file*session_dirs*)": "git commit -m x --file=session_dirs.txt",
    "Bash(git commit *-F*session_dirs*)": "git commit -F session_dirs.txt",
    "Bash(git diff *session_dirs*)": "git diff --no-index session_dirs.tx? /dev/null",
    "Bash(git hash-object *session_dirs*)": "git hash-object -w session_dirs.txt",
    "Bash(git mv *session_dirs*)": "git mv session_dirs.txt x",
    "Bash(git restore *session_dirs*)": "git restore session_dirs.txt",
    "Bash(git rm *session_dirs*)": "git rm session_dirs.txt",
    "Bash(git show *session_dirs*)": "git show HEAD:session_dirs.txt",
    "Bash(git stash *session_dirs*)": "git stash push session_dirs.txt",
    "Bash(git update-index *session_dirs*)": "git update-index --add session_dirs.txt",
    "Bash(head *session_dirs*)": "head session_dirs.tx?",
    "Bash(ksh *session_dirs*)": "ksh -c 'cat session_dirs.txt'",
    "Bash(ln *session_dirs*)": "ln -s session_dirs.txt x",
    "Bash(md5sum *session_dirs*)": "md5sum session_dirs.tx?",
    "Bash(mv *session_dirs*)": "mv session_dirs.tx? x",
    "Bash(node *session_dirs*)": "node -e \"require('fs').writeFileSync('session_dirs.txt','x')\"",
    "Bash(npm *session_dirs*)": "npm exec -- cat session_dirs.txt",
    "Bash(npx *session_dirs*)": "npx -y cowsay -f session_dirs.txt",
    "Bash(perl *session_dirs*)": "perl -pe1 session_dirs.tx?",
    "Bash(php *session_dirs*)": "php -r \"readfile('session_dirs.txt');\"",
    "Bash(printf *session_dirs*)": "cat $(printf session_dirs.txt)",
    "Bash(python*session_dirs*)": "python3 -c \"open('session_dirs.txt','w')\"",
    "Bash(rm *session_dirs*)": "rm -f session_dirs.tx?",
    "Bash(ruby *session_dirs*)": "ruby -e \"File.read('session_dirs.txt')\"",
    "Bash(sed *session_dirs*)": "sed -n p session_dirs.tx?",
    "Bash(sh *session_dirs*)": "sh -c 'cat session_dirs.txt'",
    "Bash(sort *session_dirs*)": "sort session_dirs.tx?",
    "Bash(source *session_dirs*)": "source ./session_dirs.txt",
    "Bash(tail *session_dirs*)": "tail session_dirs.tx?",
    "Bash(tee *session_dirs*)": "tee session_dirs.tx? < /dev/null",
    "Bash(touch *session_dirs*)": "touch session_dirs.tx?",
    "Bash(truncate *session_dirs*)": "truncate -s0 session_dirs.tx?",
    "Bash(uniq *session_dirs*)": "uniq session_dirs.tx?",
    "Bash(wget *session_dirs*)": "wget -q --post-file=session_dirs.txt http://127.0.0.1:9/",
    "Bash(xargs *session_dirs*)": "xargs -a session_dirs.txt echo",
    "Bash(zsh *session_dirs*)": "zsh -c 'cat session_dirs.txt'",
}

READ_RULE, EDIT_RULE = "Read(**/session_dirs.txt)", "Edit(**/session_dirs.txt)"

# The owner's must-pass forms (L16), and more of the same kind.
MUST_PASS = [
    "grep -rn session_dirs.txt docs/",
    "rg -n 'session_dirs.txt' hooks/",
    "git grep -n session_dirs.txt",
    "git log --oneline -S session_dirs.txt",
    'git commit -m "docs: mention session_dirs.txt"',
    "git log --oneline -G 'session_dirs\\.txt'",
    "git log -S session_dirs.txt --oneline -- hooks/",
    'grep -rn "session_dirs.txt" docs/ hooks/ | head -5',
    "git commit -m 'docs: session_dirs.txt mention'",
]

# The audit's must-still-refuse examples (L16) and the layer that refuses each after the change: a Bash
# entry (matched on the text form given), or the Read/Edit rule on a file operand, `-f FILE` or a
# redirect target (measured: the CLI refuses these with the blanket removed and no Bash entry added).
MUST_REFUSE = {
    "cat session_dirs.txt": [READ_RULE, "Bash(cat *session_dirs*)"],
    "grep -f session_dirs.txt x": [READ_RULE],
    "python3 -c \"open('session_dirs.txt','w')\"": ["Bash(python*session_dirs*)"],
    "bash -c 'cat session_dirs.txt'": ["Bash(bash *session_dirs*)"],
    "find / -name session_dirs.txt -exec cat {} \\;": ["Bash(find *session_dirs*)"],
    "cat $(echo session_dirs.txt)": ["Bash(cat *session_dirs*)", "Bash(echo *session_dirs*)"],
    "cat session_dirs.tx?": ["Bash(cat *session_dirs*)"],
    "echo x > session_dirs.txt": [EDIT_RULE, "Bash(echo *session_dirs*)"],
    "rg -f session_dirs.txt x": [READ_RULE],
    "grep pat session_dirs.txt": [READ_RULE],
}

# Forms the permission layer lets through on the base and after the change alike; only
# hooks/pretool-bash-safety.sh refuses them (its session_dirs\.txt rule; it is not this lane's file).
# The glob operand to grep is not refused by any layer, before or after.
HOOK_ONLY = [
    "bash <<'EOF'\ncat session_dirs.txt\nEOF",
    "python3 - <<'EOF'\nopen('session_dirs.txt','w')\nEOF",
]
NO_LAYER = ["grep pat session_dirs.tx?"]

# Claude Code 2.1.326's decisions (method in the module docstring): base = origin/claude/train-c's
# settings.json, after = this one.
MEASURED = {  # command: (base, after)
    "grep -rn session_dirs.txt docs/": ("deny", "allow"),
    "rg -n 'session_dirs.txt' hooks/": ("deny", "allow"),
    "git grep -n session_dirs.txt": ("deny", "allow"),
    "git log --oneline -S session_dirs.txt": ("deny", "allow"),
    'git commit -m "docs: mention session_dirs.txt"': ("deny", "allow"),
    "git log --oneline -G 'session_dirs\\.txt'": ("allow", "allow"),
    "git log -S session_dirs.txt --oneline -- hooks/": ("deny", "allow"),
    'grep -rn "session_dirs.txt" docs/ hooks/ | head -5': ("deny", "allow"),
    "git commit -m 'docs: session_dirs.txt mention'": ("deny", "allow"),
    "cat session_dirs.txt": ("deny", "deny"),
    "grep -f session_dirs.txt x": ("deny", "deny"),
    "python3 -c \"open('session_dirs.txt','w')\"": ("deny", "deny"),
    "bash -c 'cat session_dirs.txt'": ("deny", "deny"),
    "find / -name session_dirs.txt -exec cat {} \\;": ("deny", "deny"),
    "cat $(echo session_dirs.txt)": ("deny", "deny"),
    "cat session_dirs.tx?": ("allow", "deny"),
    "echo x > session_dirs.txt": ("deny", "deny"),
    "rg -f session_dirs.txt x": ("deny", "deny"),
    "grep pat session_dirs.txt": ("deny", "deny"),
    "cat session_dirs.t*": ("allow", "deny"),
    "/usr/bin/python3 -c \"open('session_dirs.txt','w')\"": ("deny", "deny"),
    "/tmp/x-venv/bin/python -c \"open('session_dirs.txt','w')\"": ("deny", "deny"),
    "env python3 -c \"open('session_dirs.txt','w')\"": ("deny", "deny"),
    "timeout 5 python3 -c \"open('session_dirs.txt','w')\"": ("deny", "deny"),
    "FOO=1 python3 -c \"open('session_dirs.txt','w')\"": ("deny", "deny"),
    "cd docs && python3 -c \"open('session_dirs.txt','w')\"": ("deny", "deny"),
    "sh -c 'cat session_dirs.txt'": ("deny", "deny"),
    "awk '{print}' session_dirs.txt": ("deny", "deny"),
    "xargs -a session_dirs.txt echo": ("deny", "deny"),
    "git add session_dirs.txt": ("deny", "deny"),
    "git show HEAD:session_dirs.txt": ("deny", "deny"),
    "git log --output=session_dirs.txt": ("deny", "deny"),
    "git commit -F session_dirs.txt": ("deny", "deny"),
    "git commit -m x --file=session_dirs.txt": ("deny", "deny"),
    "cp session_dirs.txt /tmp/x": ("deny", "deny"),
    "md5sum session_dirs.txt": ("deny", "deny"),
    "for f in session_dirs.tx?; do cat $f; done": ("ask", "deny"),
    HOOK_ONLY[0]: ("allow", "allow"),
    HOOK_ONLY[1]: ("allow", "allow"),
    NO_LAYER[0]: ("allow", "allow"),
}

WRAPPERS = {"timeout", "time", "nice", "nohup", "stdbuf", "command", "builtin", "noglob"}


def _deny(settings: Path = REPO / "settings.json") -> list[str]:
    return json.loads(settings.read_text(encoding="utf-8"))["permissions"]["deny"]


def bash_rule_matches(entry: str, text: str) -> bool:
    """`*` is any text; everything else, `?` included, is literal and case-sensitive (measured)."""
    rule = entry[5:-1]
    if rule.endswith(":*"):
        rule = rule[:-2] + " *"
    return re.fullmatch(".*".join(re.escape(p) for p in rule.split("*")), text, re.S) is not None


def texts(cmd: str) -> list[str]:
    """The texts a deny rule is checked against, as modelled: the whole command, each subcommand at the
    documented separators, each `$(...)` body, leading assignments and wrappers stripped, a path-qualified
    command word reduced to its name; each with and without quotes. A superset of what the CLI matches,
    so a must-pass command that no entry matches here is matched by none there."""
    out, todo = [], [cmd] + re.findall(r"\$\(([^()]*)\)", cmd)
    for t in todo:
        for part in re.split(r"\|\||&&|\|&|[;|&\n]", t):
            words = part.split()
            while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or words[0] in WRAPPERS):
                words = words[1:] if words[0] not in ("timeout",) else words[2:]
            if not words:
                continue
            words[0] = words[0].rsplit("/", 1)[-1] or words[0]
            s = " ".join(words)
            out += [part.strip(), s, s.replace('"', "").replace("'", "")]
    return out + [cmd, cmd.replace('"', "").replace("'", "")]


def bash_denies(deny: list[str], cmd: str) -> list[str]:
    return [e for e in deny if e.startswith("Bash(") and any(bash_rule_matches(e, t) for t in texts(cmd))]


# ------------------------------------------------------------------ the entries
def test_the_blanket_mention_deny_is_gone_and_the_file_rules_stay():
    deny = _deny()
    assert BLANKET not in deny
    assert READ_RULE in deny and EDIT_RULE in deny


def test_the_session_dirs_bash_entries_are_exactly_these():
    assert sorted(e for e in _deny() if "session_dirs" in e and e.startswith("Bash(")) == sorted(ENTRIES)


@pytest.mark.parametrize("entry", sorted(ENTRIES))
def test_each_entry_refuses_its_example_and_no_search_or_commit_form(entry):
    assert entry in _deny()
    assert any(bash_rule_matches(entry, t) for t in texts(ENTRIES[entry])), ENTRIES[entry]
    hit = [c for c in MUST_PASS if any(bash_rule_matches(entry, t) for t in texts(c))]
    assert not hit, f"{entry} matches allowed forms {hit}"


# ------------------------------------------------------------------ must pass / must refuse
@pytest.mark.parametrize("cmd", MUST_PASS)
def test_a_mention_as_search_pattern_or_commit_message_passes(cmd):
    assert not bash_denies(_deny(), cmd)
    assert MEASURED[cmd][1] == "allow"


def test_the_blanket_is_what_refused_the_mentions():
    """Red side: on the base the blanket matched every must-pass form except the `-G` regex spelling."""
    for cmd in MUST_PASS:
        assert bash_rule_matches(BLANKET, cmd) == (MEASURED[cmd][0] == "deny"), cmd


@pytest.mark.parametrize("cmd", sorted(MUST_REFUSE))
def test_reading_writing_or_executing_stays_refused(cmd):
    deny = _deny()
    for layer in MUST_REFUSE[cmd]:
        assert layer in deny, layer
        if layer.startswith("Bash("):
            assert any(bash_rule_matches(layer, t) for t in texts(cmd)), (layer, cmd)
    assert MEASURED[cmd][1] == "deny"


def test_measured_after_decisions_agree_with_the_model():
    deny = _deny()
    for cmd, (_, after) in MEASURED.items():
        if cmd in HOOK_ONLY or cmd in NO_LAYER:
            continue
        file_rule = {READ_RULE, EDIT_RULE} & set(MUST_REFUSE.get(cmd, []))
        if after == "allow":
            assert not bash_denies(deny, cmd), cmd
        else:  # refused by a Bash entry, or by the Read/Edit rule on a file operand (measured)
            assert after == "deny" and (bash_denies(deny, cmd) or file_rule), cmd


def test_hook_only_forms_are_not_matched_by_any_entry():
    """A heredoc body is not in the text the CLI matches (measured), so these stay with the bash-safety
    hook; they were allowed at the permission layer on the base too."""
    for cmd in HOOK_ONLY + NO_LAYER:
        assert MEASURED[cmd] == ("allow", "allow"), cmd


# ------------------------------------------------------------------ live re-measurement (opt-in)
_MOCK = textwrap.dedent('''
    import json, sys
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    CMD = sys.argv[2]
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _json(self, o):
            b = json.dumps(o).encode(); self.send_response(200)
            self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b)))
            self.end_headers(); self.wfile.write(b)
        def do_GET(self): self._json({"data": [], "has_more": False})
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
            if not self.path.startswith("/v1/messages") or "count_tokens" in self.path:
                return self._json({"input_tokens": 1})
            last = (body.get("messages") or [{}])[-1].get("content")
            done = isinstance(last, list) and any(isinstance(c, dict) and c.get("type") == "tool_result" for c in last)
            tools = any(t.get("name") == "Bash" for t in body.get("tools", []))
            if tools and not done:
                blocks, stop = [{"type": "tool_use", "id": "toolu_1", "name": "Bash",
                                 "input": {"command": open(CMD).read(), "description": "probe"}}], "tool_use"
            else:
                blocks, stop = [{"type": "text", "text": "done"}], "end_turn"
            msg = {"id": "msg_1", "type": "message", "role": "assistant", "model": body.get("model", "m"),
                   "content": blocks, "stop_reason": stop, "stop_sequence": None,
                   "usage": {"input_tokens": 1, "output_tokens": 1}}
            if not body.get("stream"):
                return self._json(msg)
            self.send_response(200); self.send_header("content-type", "text/event-stream"); self.end_headers()
            def ev(t, d): self.wfile.write(("event: %s\\ndata: %s\\n\\n" % (t, json.dumps(d))).encode())
            ev("message_start", {"type": "message_start", "message": dict(msg, content=[], stop_reason=None)})
            for i, b in enumerate(blocks):
                if b["type"] == "text":
                    ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}})
                    ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": b["text"]}})
                else:
                    ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": dict(b, input={})})
                    ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "input_json_delta", "partial_json": json.dumps(b["input"])}})
                ev("content_block_stop", {"type": "content_block_stop", "index": i})
            ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 1}})
            ev("message_stop", {"type": "message_stop"})
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
''')


def _cli_decision(perms: dict, cmd: str, work: Path, port: int, cmdfile: Path) -> str:
    home = Path(tempfile.mkdtemp(dir=work))
    proj = home / "proj"
    (proj / "docs").mkdir(parents=True)
    (proj / "hooks").mkdir()
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text(json.dumps({"permissions": perms}))
    (home / ".claude.json").write_text(json.dumps({"hasCompletedOnboarding": True,
                                                   "projects": {str(proj): {"hasTrustDialogAccepted": True}}}))
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    cmdfile.write_text(cmd)
    env = {"HOME": str(home), "PATH": os.environ["PATH"], "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}",
           "ANTHROPIC_API_KEY": "sk-ant-placeholder", "NO_PROXY": "127.0.0.1,localhost",
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1", "TERM": "dumb"}
    r = subprocess.run(["claude", "-p", "go", "--output-format", "stream-json", "--verbose",
                        "--permission-mode", "default", "--max-turns", "3"],
                       cwd=proj, env=env, capture_output=True, text=True, timeout=180)
    for line in r.stdout.splitlines():
        try:
            o = json.loads(line)
        except ValueError:
            continue
        for c in (o.get("message") or {}).get("content", []) if o.get("type") == "user" else []:
            if isinstance(c, dict) and c.get("type") == "tool_result":
                res = c.get("content")
                res = res if isinstance(res, str) else json.dumps(res)
                if "has been denied" in res:
                    return "deny"
                return "allow" if res.startswith("Exit code") or not c.get("is_error") else "ask"
    raise AssertionError(f"no tool result for {cmd!r}: {r.stderr[-400:]}")


@pytest.mark.skipif(os.environ.get("HARNESS_LIVE_CLI") != "1" or not shutil.which("claude"),
                    reason="live CLI re-measurement is opt-in: HARNESS_LIVE_CLI=1 with `claude` installed")
def test_live_cli_decisions(tmp_path):
    perms = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))["permissions"]
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    (tmp_path / "mock.py").write_text(_MOCK)
    cmdfile = tmp_path / "cmd"
    cmdfile.write_text("true")
    srv = subprocess.Popen([sys.executable, "-I", str(tmp_path / "mock.py"), str(port), str(cmdfile)])
    try:
        time.sleep(1)
        cases = dict(MEASURED)
        cases.update({ex: (None, "deny") for ex in ENTRIES.values()})
        got = {cmd: _cli_decision(perms, cmd, tmp_path, port, cmdfile) for cmd in cases}
    finally:
        srv.kill()
    wrong = {c: (got[c], cases[c][1]) for c in cases if got[c] != cases[c][1]}
    assert not wrong, wrong
