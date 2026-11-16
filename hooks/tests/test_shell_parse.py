"""Unit tests of hooks/lib/shell_parse.py: one class per node type and view."""

import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(os.path.dirname(HERE), "lib")
sys.path.insert(0, LIB)

import shell_parse as sp  # noqa: E402


def cmds(text, **kw):
    return [s.cmd for s in sp.walk(sp.parse(text), **kw)]


def argvs(text, **kw):
    return [c.argv() for c in cmds(text, **kw)]


class TestNeverRaises:
    @pytest.mark.parametrize("text", [
        "", "'", '"', "$(", "`", "${", "$((", "<(", "cat <<", "cat <<EOF", "echo >",
        "if true", "for", "case x in", "((", "[[ a", "f() {", "}", "fi", ")", ";;",
        "\\", "$'", "a=(", "@(", None, 12, "x" * 300_000, "$(" * 40 + ")" * 40,
    ])
    def test_garbage_gives_a_script(self, text):
        s = sp.parse(text)
        assert isinstance(s, sp.Script)
        sp.facts(text if isinstance(text, str) else "")

    def test_error_keeps_commands_before_it(self):
        s = sp.parse("ls; echo 'open")
        assert s.error.code == "single_quote"
        assert s.error.offset == 9
        assert [c.argv() for c in sp.iter_commands(s)] == [["ls"], ["echo"]]

    @pytest.mark.parametrize("text,code", [
        ("echo 'a", "single_quote"), ('echo "a', "double_quote"), ("echo $'a", "ansi_quote"),
        ("echo $(a", "cmdsub"), ("echo `a", "backtick"), ("echo ${a", "param"),
        ("cat <(a", "procsub"), ("echo >", "redirect_missing_target"),
        ("cat <<EOF\nx\n", "unterminated_heredoc"), ("if true; then x", "unbalanced_group"),
        ("( ls", "unbalanced_group"), ("{ ls", "unbalanced_group"), ("fi", "unexpected_token"),
        ("ls )", "unexpected_token"), ("ls | ", "unexpected_token"),
    ])
    def test_error_codes(self, text, code):
        assert sp.parse(text).error.code == code

    def test_depth_limit(self):
        s = sp.parse("$(" * 30 + "ls" + ")" * 30)
        errs = [e.code for e in s.errors()]
        assert "depth_limit" in errs

    def test_size_limit(self):
        assert sp.parse("x" * (sp.MAX_LEN + 1)).error.code == "size_limit"


class TestWords:
    def part(self, text, k=1):
        return sp.parse(text).items[0][0].stages[0].words[k].parts

    @pytest.mark.parametrize("text,quote,value", [
        ("echo a", sp.BARE, "a"), ("echo 'a b'", sp.SINGLE, "a b"),
        ('echo "a b"', sp.DOUBLE, "a b"), ("echo $'a\\tb'", sp.ANSI_C, "a\tb"),
        ('echo $"a"', sp.LOCALE, "a"), ("echo \\a", sp.ESCAPED, "a"),
    ])
    def test_quote_kinds(self, text, quote, value):
        parts = self.part(text)
        assert [p.quote for p in parts] == [quote]
        assert parts[0].text == value

    def test_mixed_word_keeps_each_quote(self):
        parts = self.part("echo a'b'\"c\"$'d'")
        assert [(p.text, p.quote) for p in parts] == [
            ("a", sp.BARE), ("b", sp.SINGLE), ("c", sp.DOUBLE), ("d", sp.ANSI_C)]

    def test_ansi_c_escaped_quote(self):
        s = sp.parse("echo $'a\\'b' \"$(echo x)\"")
        assert s.error is None
        assert argvs("echo $'a\\'b' \"$(echo x)\"") == [["echo", "a'b", None], ["echo", "x"]]

    def test_literal_keeps_ansi_as_computed_value_decodes(self):
        w = sp.parse("$'rm' x").items[0][0].stages[0].words[0]
        assert w.literal() is None
        assert w.value() == "rm"

    @pytest.mark.parametrize("text,kind", [
        ("echo $(id)", "cmdsub"), ("echo `id`", "backtick"), ("echo $((1+2))", "arith"),
        ("echo ${x}", "param"), ("echo $x", "param"), ("cat <(id)", "procsub_in"),
        ("tee >(id)", "procsub_out"), ("echo *", "glob"), ("echo {a,b}", "brace"),
        ("echo @(a|b)", "glob"),
    ])
    def test_part_kinds(self, text, kind):
        assert any(p.kind == kind for p in self.part(text))

    def test_nested_script_of_substitution(self):
        p = [p for p in self.part("echo $(git status; ls)") if p.kind == "cmdsub"][0]
        assert [c.argv() for c in sp.iter_commands(p.body)] == [["git", "status"], ["ls"]]

    def test_spans_map_to_raw_offsets_across_continuations(self):
        text = "ec\\\nho 'x'"
        w = sp.parse(text).items[0][0].stages[0].words[1]
        a, b = w.span
        assert text[a:b] == "'x'"

    def test_param_reexpand(self):
        assert [p.reexpand for p in self.part("echo ${!x}")] == [True]
        assert [p.reexpand for p in self.part("echo ${x@P}")] == [True]

    def test_comment_starts_only_at_word_start(self):
        assert argvs("echo a#b # it's") == [["echo", "a#b"]]
        assert argvs("echo hi #x\nls") == [["echo", "hi"], ["ls"]]


class TestRedirects:
    def red(self, text):
        return sp.parse(text).items[0][0].stages[0].redirects

    @pytest.mark.parametrize("text,op,fd", [
        ("ls > f", ">", 1), ("ls >> f", ">>", 1), ("ls 2> f", ">", 2), ("ls >| f", ">|", 1),
        ("ls &> f", "&>", None), ("ls &>> f", "&>>", None), ("cat < f", "<", 0),
        ("cat <<< w", "<<<", 0), ("cat <> f", "<>", 0),
    ])
    def test_ops(self, text, op, fd):
        r = self.red(text)[0]
        assert (r.op, r.fd) == (op, fd)

    def test_and_greater_is_one_redirect_not_background(self):
        s = sp.parse("ls &> f")
        assert len(s.items) == 1 and s.items[0][1] == ""

    def test_fd_var(self):
        r = self.red("exec {fd}> f")[0]
        assert (r.fd_var, r.target.value()) == ("fd", "f")

    def test_dup_and_close(self):
        r1, r2 = self.red("ls >&2 3>&-")
        assert r1.dup == 2 and not r1.writes()
        assert r2.close

    def test_heredoc(self):
        r = self.red("cat <<-'E'\n\tbody $x\n\tE\nls")[0]
        assert (r.hd.delim, r.hd.quoted, r.hd.strip_tabs, r.hd.terminated) == ("E", True, True, True)
        assert r.hd.body == "\tbody $x\n"
        assert r.hd.expansions == ()

    def test_heredoc_end_matches_exactly(self):
        s = sp.parse("cat <<EOF\n  EOF\nit's\nEOF\nls")
        assert s.error is None
        assert s.items[0][0].stages[0].redirects[0].hd.body == "  EOF\nit's\n"
        assert argvs("cat <<EOF\n  EOF\nit's\nEOF\nls") == [["cat"], ["ls"]]

    def test_unquoted_heredoc_expansions(self):
        r = self.red("cat <<EOF\nit's $(id)\nEOF\n")[0]
        assert [p.kind for p in r.hd.expansions] == ["cmdsub"]


class TestCompounds:
    def first(self, text):
        return sp.parse(text).items[0][0].stages[0]

    @pytest.mark.parametrize("text,kind", [
        ("( ls )", "subshell"), ("{ ls; }", "group"), ("if a; then b; elif c; then d; else e; fi", "if"),
        ("while a; do b; done", "while"), ("until a; do b; done", "until"),
        ("for x in a b; do c; done", "for"), ("for ((i=0;i<2;i++)); do c; done", "for"),
        ("select x in a; do b; done", "select"), ("case x in a|b) c;; *) d;& e) f;;& esac", "case"),
        ("[[ -n $x && a < b ]]", "cond"), ("(( x > 1 ))", "arith"),
        ("f() { ls; }", "function"), ("function f { ls; }", "function"),
        ("coproc { ls; }", "coproc"),
    ])
    def test_kinds(self, text, kind):
        s = sp.parse(text)
        assert s.error is None, s.error
        assert isinstance(self.first(text), sp.Compound)
        assert self.first(text).kind == kind

    def test_if_commands_are_walked(self):
        assert argvs("if a; then b; elif c; then d; else e; fi") == [["a"], ["b"], ["c"], ["d"], ["e"]]

    def test_case_patterns_are_not_commands(self):
        assert argvs("case $x in rm) ls;; esac") == [["ls"]]

    def test_for_list_words_are_not_commands(self):
        assert argvs("for git in a b; do echo; done") == [["echo"]]

    def test_cond_operands_are_not_commands(self):
        assert argvs("[[ -f x ]] && ls") == [["ls"]]

    def test_pipeline_negation_and_time(self):
        pl = sp.parse("! time -p a | b |& c").items[0][0]
        assert pl.negated and pl.timed and pl.pipes == ("|", "|&")

    def test_assignments(self):
        c = cmds("A=1 B+=x C[1]=y D=(a b) ls")[0]
        assert [(a.name, a.append, a.index) for a in c.assignments] == [
            ("A", False, None), ("B", True, None), ("C", False, "1"), ("D", False, None)]
        assert c.assignments[0].static_value() == "1"
        assert c.argv() == ["ls"]

    def test_reserved_word_only_at_command_position(self):
        assert argvs("echo if then fi") == [["echo", "if", "then", "fi"]]


class TestWalk:
    def test_contexts(self):
        sites = list(sp.walk(sp.parse("echo $(a) `b` <(c); bash -c 'd'; eval e")))
        got = [(s.cmd.argv()[0], "/".join(s.context)) for s in sites]
        assert ("a", "top/cmdsub") in got and ("b", "top/backtick") in got
        assert ("c", "top/procsub") in got and ("d", "top/shell_c") in got
        assert ("e", "top/eval") in got

    def test_feeds(self):
        sites = {s.cmd.argv()[0]: s.fed for s in sp.walk(sp.parse(
            "a | b; c < f; d <<< w; e <<X\ny\nX\n"))}
        assert sites["b"] == {"pipe"} and sites["c"] == {"file"}
        assert sites["d"] == {"herestring"} and sites["e"] == {"heredoc"}

    def test_heredoc_fed_shell(self):
        got = argvs("bash <<'EOF'\ngit push\nEOF\n")
        assert ["git", "push"] in got

    def test_into_limits_descent(self):
        assert argvs("echo $(a)", into=()) == [["echo", None]]

    def test_dynamic_head(self):
        assert [s.dynamic for s in sp.walk(sp.parse("$X a"))] == [True]


class TestResolve:
    @pytest.mark.parametrize("text,name,argv", [
        ("sudo -u x git push", "git", ["push"]),
        ("env -i A=1 nice -n 5 timeout 10 git status", "git", ["status"]),
        ("command -p ls", "ls", []), ("builtin echo x", "echo", ["x"]),
        ("xargs -n1 rm", "rm", []), ("flock /l ls", "ls", []),
        ("chrt 10 ls", "ls", []), ("stdbuf -o0 ls", "ls", []),
        ("nohup setsid ls", "ls", []), ("command -v rm", "command", ["-v", "rm"]),
    ])
    def test_peels(self, text, name, argv):
        r = sp.resolve(cmds(text)[0])
        assert (r.name, r.argv()) == (name, argv)

    @pytest.mark.parametrize("text,inner", [
        ("bash -c 'git push'", ["git", "push"]), ("sh -xc \"rm -f a\"", ["rm", "-f", "a"]),
        ("eval 'ls -l'", ["ls", "-l"]), ("su -c 'id' root", ["id"]),
        ("runuser -u x -c 'id'", ["id"]), ("ssh -p 22 host ls /", ["ls", "/"]),
        ("flock /l -c 'id'", ["id"]), ("bash <<< 'git push'", ["git", "push"]),
        ("env -S 'bash -c id'", ["id"]),
    ])
    def test_payloads(self, text, inner):
        assert inner in argvs(text)

    def test_dynamic_payload_is_unresolved(self):
        assert sp.resolve(cmds('bash -c "$X"')[0]).unresolved == "shell_c_dynamic"


class TestSplitOptions:
    SPEC = sp._spec(("-a", "-b", "--all"), ("-o", "--output"))

    def words(self, text):
        return list(cmds(text)[0].words)

    def test_cluster_and_attached(self):
        opts, ops, err = sp.split_options(self.words("x -ab -ofile --out=g --al y"), self.SPEC, 1)
        assert err is None
        assert [(o, v.value() if v else None) for o, v in opts] == [
            ("-a", None), ("-b", None), ("-o", "file"), ("--output", "g"), ("--all", None)]
        assert [w.value() for w in ops] == ["y"]

    def test_unknown(self):
        assert sp.split_options(self.words("x -z"), self.SPEC, 1)[2] == "unknown_option:-z"

    def test_permute(self):
        opts, ops, _ = sp.split_options(self.words("x y -a z"), self.SPEC, 1, permute=True)
        assert [o for o, _v in opts] == ["-a"] and [w.value() for w in ops] == ["y", "z"]


class TestExecutableView:
    @pytest.mark.parametrize("text,kept,blanked", [
        ("echo 'rm -rf /' # kill it", "echo", "rm"),
        ("git commit -m \"kill $(id)\"", "$(id)", "kill"),
        ("bash -c 'kill -9 1'", "kill -9 1", "'"),
        ("kill \"-9\" 1", "kill  -9  1", '"'),
        ("cat <<EOF\nkill 1\nEOF\n", "cat", "kill"),
        ("bash <<EOF\nkill 1\nEOF\n", "kill 1", None),
        ("python3 x.py kill", "python3", "kill"),
    ])
    def test_view(self, text, kept, blanked):
        v = sp.executable_view(text)
        assert len(v) == len(text)
        assert kept in v
        if blanked:
            assert blanked not in v

    def test_unparsable_is_unchanged(self):
        assert sp.executable_view("echo 'x") == "echo 'x"


class TestWriteTargets:
    @pytest.mark.parametrize("text,expected", [
        ("echo x > /a", [("/a", "truncate")]), ("echo x >> /a", [("/a", "append")]),
        ("echo x &> /a", [("/a", "truncate")]), ("echo x >| /a", [("/a", "truncate")]),
        ("echo x>settings.json", [("settings.json", "truncate")]),
        ("ls | tee -a /a /b", [("/a", "append"), ("/b", "append")]),
        ("cp s /a", [("/a", "copy-dest")]), ("mv s /a", [("/a", "move-dest"), ("s", "delete")]),
        ("ln -sf s /a", [("/a", "link")]), ("rsync -a s /a", [("/a", "copy-dest")]),
        ("truncate -s 0 /a", [("/a", "truncate")]), ("dd if=s of=/a", [("/a", "truncate")]),
        ("curl -sSo/a u", [("/a", "truncate")]), ("wget -O /a u", [("/a", "truncate")]),
        ("unlink /a", [("/a", "delete")]), ("rm -f /a /b", [("/a", "delete"), ("/b", "delete")]),
        ("sed -i s/a/b/ /a", [("/a", "in-place")]), ("install -m 644 s /a", [("/a", "copy-dest")]),
        ("git checkout -- /a", [("/a", "truncate")]), ("git restore /a", [("/a", "truncate")]),
        ("git rm --cached /a", []), ("git rm /a", [("/a", "delete")]),
        ("X=/p; echo > $X", [("/p", "truncate")]), ("echo 'a > b'", []),
        ("echo x > >(cat)", []), ("echo x >&2", []), ("pip install x", []),
        ("bash -c 'echo > /a'", [("/a", "truncate")]), ("echo $(echo > /a)", [("/a", "truncate")]),
        ("echo x > \"/tmp/report (1).txt\"", [("/tmp/report (1).txt", "truncate")]),
        ("'it'\\''s' > f", [("f", "truncate")]), (">a\\ b", [("a b", "truncate")]),
    ])
    def test_targets(self, text, expected):
        assert [(t.path, t.mode) for t in sp.write_targets(text)] == expected

    def test_undecidable(self):
        t = sp.write_targets("echo > $UNSET")[0]
        assert t.path is None and not t.decidable


class TestGitInvocations:
    def inv(self, text):
        return sp.git_invocations(text)

    def test_globals(self):
        g = self.inv("git -C 'my dir' -c a.b=c --config-env x.y=E --no-pager push --dry o")[0]
        assert g.C_dirs == ["my dir"]
        assert g.config_pairs == [("a.b", "c"), ("x.y", "$E")]
        assert g.subcommand == "push" and g.args == ("--dry-run", "o")

    def test_abbreviation(self):
        assert self.inv("git reset --har")[0].args == ("--hard",)
        assert self.inv("git push --forc")[0].args == ("--forc",)  # ambiguous, as git reads it
        assert self.inv("git branch --del x")[0].args == ("--delete", "x")

    def test_env_config(self):
        g = self.inv("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/x git commit")[0]
        assert ("core.hooksPath", "/x") in g.config_pairs

    def test_nested_and_wrapped(self):
        subs = [g.subcommand for g in self.inv("sudo bash -c \"cd x; git push\" && $(git status)")]
        assert subs == ["status", "push"] or sorted(subs) == ["push", "status"]

    def test_alias_body(self):
        g = self.inv("git -c alias.p='!git push --force' p")
        assert [x.subcommand for x in g] == ["p", "push"]

    def test_message_is_not_an_invocation(self):
        assert [g.subcommand for g in self.inv('git commit -m "x; git push origin"')] == ["commit"]

    def test_path_qualified(self):
        assert self.inv("/usr/bin/git status")[0].path_qualified


class TestArgvSplit:
    def test_like_shlex(self):
        assert sp.argv_split("a 'b c' \"d\\\"e\" f\\ g") == ["a", "b c", 'd"e', "f g"]


class TestCli:
    def test_facts(self):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push > /tmp/x"}})
        out = subprocess.run([sys.executable, os.path.join(LIB, "shell_parse.py"), "--facts"],
                             input=payload, text=True, capture_output=True, check=True).stdout
        facts = json.loads(out)
        assert facts["error"] is None
        assert facts["git_invocations"][0]["subcommand"] == "push"
        assert facts["write_targets"][0]["path"] == "/tmp/x"
