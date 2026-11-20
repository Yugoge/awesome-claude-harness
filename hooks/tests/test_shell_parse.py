"""Unit tests of hooks/lib/shell_parse.py: one class per node type and view."""

import os
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
        text = text if isinstance(text, str) else ""
        script = sp.parse(text)  # every view reads it without raising
        for site in sp.walk(script):
            res = sp.resolve(site.cmd)
            site.cmd.argv(), res.name, res.argv(), [w[0] for w in res.wrappers], sorted(site.fed)
            [a.static_value() for a in site.cmd.assignments]
            [r.target.value() for r in site.cmd.redirects if r.target is not None]
        [e.as_dict() for e in script.errors()]
        [t.as_dict() for t in sp.write_targets(script)]
        [g.as_dict() for g in sp.git_invocations(script)]
        sp.executable_view(text)

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
        assert r.hd.body == "body $x\n"  # <<- strips the leading tabs as the command reads it
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


class TestConsumerDefects:
    """Each row is a reading a consumer lane found missing; the commands bash runs are all reached."""

    @pytest.mark.parametrize("text,inner", [
        ("echo ${X:-$(rm t)}", ["rm", "t"]),
        ("cat <<E\n${X:-$(rm x)}\nE\n", ["rm", "x"]),
        ("echo $(( $(rm q) + 1 ))", ["rm", "q"]),
        ("cat <<E\n$(( $(rm q) + 1 ))\nE\n", ["rm", "q"]),
        ("(( $(rm n) + 1 ))", ["rm", "n"]),
        ("A=($(rm z)) ls", ["rm", "z"]),
        ("echo ${X:-${Y:-`rm b`}}", ["rm", "b"]),
    ])
    def test_substitution_nested_in_expansion_or_arithmetic(self, text, inner):
        assert inner in argvs(text)

    def test_brace_group_whose_first_word_is_a_path(self):
        s = sp.parse("{ ../sbin/rm qa-target-4.txt; }")
        assert s.items[0][0].stages[0].kind == "group"
        assert argvs("{ ../sbin/rm qa-target-4.txt; }") == [["../sbin/rm", "qa-target-4.txt"]]
        assert any(p.kind == "brace" for p in sp.parse("echo {a,b}").items[0][0].stages[0].words[1].parts)

    def test_shell_fed_through_an_fd_dup(self):
        assert ["rm", "x"] in argvs("bash 3<<'EOF' <&3\nrm x\nEOF\n")

    @pytest.mark.parametrize("text,count", [
        ("a \\\\\nb", 2), ("a \\\nb", 1), ("echo 'a\\\nb'", 1), ("echo a # c \\\nls", 2),
        ("cat <<'E'\nx\\\nE\nls", 2),
    ])
    def test_continuation_only_where_the_backslash_is_bare(self, text, count):
        assert len(cmds(text)) == count

    @pytest.mark.parametrize("text", ["a &&", "a||", "-m|&||", "a && )", "if a &&; then b; fi"])
    def test_list_ending_in_and_or_is_an_error(self, text):
        assert sp.parse(text).error is not None

    @pytest.mark.parametrize("text,path", [
        ("{ echo x; } > a", "a"), ("( echo x ) > b", "b"), ("for i in 1; do :; done > c", "c"),
        ("while false; do :; done >> c2", "c2"), ("until true; do :; done > c3", "c3"),
        ("if true; then :; fi > c4", "c4"), ("case x in x) :;; esac > c5", "c5"),
        ("f() { :; } > e", "e"), ("bash -c \"{ :; } > d\"", "d"), ("echo $( { :; } > g )", "g"),
        ("bash <<'E'\n( : ) > h\nE\n", "h"), ("[[ -n x ]] > i", "i"),
    ])
    def test_redirection_on_a_compound(self, text, path):
        assert path in [t.path for t in sp.write_targets(text)]

    @pytest.mark.parametrize("text", [
        '"$CP" cp-01 /srv/data/out', "$CP -r mv-tool /srv/data/out", "c$X -- mv-tool /srv/data/out",
        'case x in y) "$MV" mv-tool /srv/data/out ;; esac',
    ])
    def test_computed_command_word_names_its_last_operand_undecidably(self, text):
        t = [t for t in sp.write_targets(text) if t.path == "/srv/data/out"]
        assert [x.decidable for x in t] == [False]

    def test_computed_command_word_names_every_operand(self):
        t = sp.write_targets('"$V" a /p/b')
        assert [(x.path, x.mechanism, x.decidable) for x in t] == [
            ("a", "computed-command", False), ("/p/b", "computed-command", False)]

    @pytest.mark.parametrize("text", ["taskset -c 0 git push", "taskset 0x1 git push",
                                      "taskset -a 0x3 git push", "numactl -N 0 git push",
                                      "chrt -f 10 git push"])
    def test_wrappers_with_a_mandatory_operand_reach_git(self, text):
        assert [g.subcommand for g in sp.git_invocations(text)] == ["push"]

    def test_wrapper_option_it_cannot_read_is_unresolved_not_skipped(self):
        g = sp.git_invocations("nice -10 git push")
        assert [x.subcommand for x in g] == ["push"] and g[0].unresolved.startswith("wrapper:")

    @pytest.mark.parametrize("text", ["git -C/p status", "git -cuser.name=x commit"])
    def test_attached_c_options_are_not_git_options(self, text):
        g = sp.git_invocations(text)[0]
        assert g.unresolved.startswith("invalid_global_option") and g.subcommand is None

    @pytest.mark.parametrize("text,paths", [
        ("chmod -x hooks/h.py", ["hooks/h.py"]), ("chmod u+x,go-w a b", ["a", "b"]),
        ("chmod --reference=r a", ["a"]), ("chown -R u:g d", ["d"]), ("chgrp g f", ["f"]),
        ("chattr +i -R f", ["f"]), ("chattr -i f g", ["f", "g"]),
        ("setfacl -m u:x:r f", ["f"]), ("setfacl -b a b", ["a", "b"]),
    ])
    def test_permission_verbs(self, text, paths):
        t = sp.write_targets(text)
        assert [x.path for x in t] == paths and {x.mode for x in t} == {"in-place"}

    @pytest.mark.parametrize("text,word", [
        ("cp${IFS}/etc/hostname${IFS}out.txt", "cp${IFS}/etc/hostname${IFS}out.txt"),
        ("printf x | tee${IFS}out.txt", "tee${IFS}out.txt"),
    ])
    def test_ifs_split_command_word_is_an_undecidable_target(self, text, word):
        t = [x for x in sp.write_targets(text) if x.mechanism == "computed-command"]
        assert [(x.path, x.decidable, x.word.text) for x in t] == [(None, False, word)]

    @pytest.mark.parametrize("text", ["setpriv --reuid 1 git push", "choom -n 5 git push",
                                      "runcon u:r:t:s0 git push", "runcon -t t git push",
                                      "systemd-inhibit --why x git push"])
    def test_more_wrappers_reach_git(self, text):
        assert [g.subcommand for g in sp.git_invocations(text)] == ["push"]

    def test_git_rm_cached_after_double_dash_is_a_path(self):
        assert [t.path for t in sp.write_targets("git rm -- --cached x")] == ["--cached", "x"]

    def test_compound_redirections_are_a_redirect_only_site(self):
        sites = list(sp.walk(sp.parse("{ echo x; } > a")))
        assert [s.cmd.argv() for s in sites] == [[], ["echo", "x"]]
        assert [r.target.value() for r in sites[0].cmd.redirects] == ["a"]

    @pytest.mark.parametrize("text,expected", [
        ('T=/x; bash -c "echo x | tee $T"', [("/x", True)]),
        ("T=/x; bash -c 'echo x | tee $T'", [(None, False)]),
    ])
    def test_c_string_is_expanded_by_its_outer_quoting(self, text, expected):
        assert [(t.path, t.decidable) for t in sp.write_targets(text)] == expected

    def test_every_operand_of_an_xargs_run_move_is_undecidable(self):
        t = sp.write_targets("echo y | xargs mv /elsewhere/a d/sid")
        assert {(x.path, x.mode) for x in t} == {("d/sid", "move-dest"), ("/elsewhere/a", "delete"),
                                                 ("d/sid", "delete"), (None, "move-dest")}
        assert not any(x.decidable for x in t)

    @pytest.mark.parametrize("text", ["T=$HOME/settings.json; echo x | tee $T",
                                      "T=$HOME/settings.json; echo x > ${T}"])
    def test_a_computed_assignment_keeps_its_word(self, text):
        t = sp.write_targets(text)
        assert [(x.path, x.decidable, x.word.text) for x in t] == [(None, False, "$HOME/settings.json")]


class TestAuditViews:
    def test_fd_move_writes_no_file(self):
        assert [t.path for t in sp.write_targets("echo a 3>o13 >&3-")] == ["o13"]

    def test_git_rm_abbreviated_cached_removes_nothing(self):
        assert sp.write_targets("git rm --cach f") == []

    def test_exec_path_is_unresolved(self):
        g = sp.git_invocations("git --exec-path=/x push")[0]
        assert (g.subcommand, g.unresolved) == ("push", "exec_path")

    def test_alias_chain_keeps_the_config(self):
        subs = [g.subcommand for g in sp.git_invocations("git -c alias.a=b -c alias.b=push a o m")]
        assert subs[-1] == "push"

    def test_alias_loop_stops(self):
        g = sp.git_invocations("git -c alias.a=b -c alias.b=a a")
        assert g[-1].unresolved == "alias_loop" and len(g) == 3

    def test_xargs_appends_its_static_input(self):
        g = sp.git_invocations("xargs git <<< 'push --force origin main'")
        assert [(x.subcommand, x.args) for x in g] == [("push", ("--force", "origin", "main"))]

    def test_xargs_with_unknown_input_writes_undecidably(self):
        t = sp.write_targets("ls | xargs rm")
        assert [(x.path, x.mode, x.decidable) for x in t] == [(None, "delete", False)]

    @pytest.mark.parametrize("text", ["echo x &>(rm q)", "true | ! rm a", "echo x >#o7", "f() rm x"])
    def test_what_bash_rejects_is_an_error(self, text):
        assert sp.parse(text).error is not None


class TestComputedShellOptions:
    @pytest.mark.parametrize("text,path", [
        ('bash $OPT -c "rm -f /r/.git/hooks/pre-commit"', "/r/.git/hooks/pre-commit"),
        ('sh "$X" -xc "rm a"', "a"), ('zsh $O -c "rm b"', "b"),
    ])
    def test_a_computed_option_before_c_still_reads_the_string(self, text, path):
        assert path in [t.path for t in sp.write_targets(text)]
        shell = [s for s in sp.walk(sp.parse(text)) if s.context == ("top",)][0]
        assert sp.resolve(shell.cmd).unresolved == "computed-shell-option"

    @pytest.mark.parametrize("text", ['ksh93 -c "rm b"', 'mksh -c "rm b"', 'yash -c "rm b"'])
    def test_more_shells(self, text):
        assert ["rm", "b"] in argvs(text)

    @pytest.mark.parametrize("shell", ["ksh93", "mksh", "yash"])
    def test_a_named_shell_reads_its_c_payload_as_bash_does(self, shell):
        """A shell SHELLS names reads like bash: the same sites, write targets and executable
        view, and a resolved reading. The `*sh` fallback finds the same sites, so only the
        unknown_shell mark and the view, which blanks the payload as data, tell them apart."""
        def reading(sh):
            text = '%s -c "rm b" > o' % sh
            sites = [s.cmd.argv()[1:] if s.context == ("top",) else (s.context, s.cmd.argv())
                     for s in sp.walk(sp.parse(text))]
            targets = [(t.path, t.mode, t.decidable) for t in sp.write_targets(text)]
            view = sp.executable_view(text)[len(sh):]
            top = sp.resolve(cmds(text)[0])
            return sites, targets, view, (top.payload_kind, top.unresolved)
        assert reading(shell) == reading("bash")
        assert reading(shell)[3] == ("shell_c", None)

    def test_an_unknown_shell_given_c_is_read_and_unresolved(self):
        assert ["rm", "c"] in argvs('foosh -c "rm c"')
        assert sp.resolve(cmds('foosh -c "rm c"')[0]).unresolved == "unknown_shell"
        assert sp.resolve(cmds("hash -r")[0]).unresolved is None

    def test_env_computed_option_before_split_string(self):
        site = cmds('env $O -S "rm d"')[0]
        r = sp.resolve(site)
        assert (r.name, r.unresolved) == ("rm", "computed-env-option")
