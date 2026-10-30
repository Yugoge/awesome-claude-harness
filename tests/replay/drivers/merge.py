"""/merge, played compliantly from commands/merge.md and agents/merge-analyst.md of the tree under test.

Before the session the owner, in their own terminal (no hook sees it), commits on the toy's main
line and on a feature branch cut from the commit before it, and leaves the feature branch checked
out in the toy's main checkout (an in_place merge; the origin stays the local bare repository the
sandbox made). Then, in one session, the main agent types `/merge` (bare, as the Usage calls typical;
`--arg ref=<ref>` types `/merge <ref>`) and does what each step of the tree's text says, read at run
time:

* Step 0: the worktree-shape judgment from the read-only git the step names (its inline codes: the
  first entry of `git worktree list` against `git rev-parse --show-toplevel`), one Bash call; the
  source from the first tier that resolves: the typed argument, an overnight-state record in the
  conversation (none in this session), or, in place, the tier's own `git branch --show-current`.
* Step 1: the step's block, `<the-resolved-merge-source>` bound, its variables kept; the aborts the
  step lists (an empty SESSION_ID, a MISSING tip, a self-merge) end the turn with the text's message.
* Step 2: the dispatch the step names (`Dispatch the `<role>` subagent`) with the step's context block
  as its prompt, placeholders bound to Step 1's values and the obligation, where the block has one,
  instantiated (dispatched_at the current UTC time).
* The merge-analyst, played from its agent file (agents.Player with the work below): each Workflow
  phase's blocks in order, the shell variables the prompt passes bound: the two live tips and their
  checks; the divergence and diff-stat reads; the conflict-marker checks and the MERGE_HEAD probe; the
  overnight-state listing (a record Read when one exists); the verdict as Phase 6 states it; where the
  text keeps an audit log, its directory and the appended line; the grant directory and path as the
  text computes them (one Bash call with its mkdir), expires_at from the text's own python, the grant
  Written from the text's JSON template; its closing line, the response line the obligation declares
  where the dispatch carries one. A grant the PostToolUse check removes (`MERGE_GRANT_INVALID`) is
  written again from the analysis, as the text says.
* Step 3: the grant Read at the path the step gives (its state dir as the step's parenthesis says,
  taken from the path the analyst's closing line names when that is the same path); where the text
  validates the grant itself (the base), its field list checked and the grant consumed with the step's
  `rm -f` block, and an expired grant sent back to Step 2 with a fresh REQUEST_ID (Step 1's own line);
  then the verdict acted on.
* Step 4: the tip re-read block; tips that moved since the grant end the turn with the text's message.
* Step 5: the wrapper call the step gives, `<resolved-ref>` bound; its outcome recorded (the merge
  commit and its parents, the toy's branch and tips) in facts.json; Stop.

Driver arguments (cli.py --arg K=V):
  variant=plain      the feature branch merges cleanly (default)
  variant=conflict   the feature branch and the main line change the same line: the wrapper's merge
                     stops on the conflict and exits non-zero ("the user resolves manually"); the
                     owner resolves and commits in their terminal, and the second `/merge` of the same
                     ref (the wrapper's "re-run via slash command to finish cleanup") goes through
                     Steps 0-5 again on the merged history (git's "Already up to date" path)
  ref=<ref>          type `/merge <ref>` (tier 1) instead of a bare `/merge` (tier 3)
  sid=respelled|cli  how Step 1 binds SESSION_ID (see "Session id" below; default respelled)
  kept=<JSON>        [[hook, step, normalised text], ...]: the blocks the base kit's replay of the same
                     variant and settings recorded; given, a declared deviation passes only a block in
                     that list (drivers/dev.py KeptOnly); without it every declared deviation passes

Session id. Step 1 binds `SESSION_ID="${CLAUDE_SESSION_ID}"` (commands/merge.md:87 on both trees) and
aborts when it is empty; the CLI's Bash exports CLAUDE_CODE_SESSION_ID and no CLAUDE_SESSION_ID
(landscape B-breakages.md:45; prompts/P1c.md X4's sub-measure, which P1c owns), so a replay of the
text as written ends at Step 1's abort on either tree (`--arg sid=cli`). That is a failure, not a
block: no DEVIATION passes it, and row 7's respellings name harness-script paths only. By default the
driver binds Step 1's line as commands/push.md:158 spells the same binding,
`SESSION_ID="${CLAUDE_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-}}"`, recorded in blocks.json
"respellings" as "M-S session id" at each application, so the replay reaches the merge; the report
lists it as a defect of both trees' text, not as a row 7 respelling.

Respellings (row 7): none of the /merge text's harness-script calls needs one (Step 1's
`bash ~/.claude/scripts/derive-default-branch.sh` and Step 5's `bash ~/.claude/hooks/merge.sh` already
name the harness copy); the analyst's text names no harness script on the base, and its working-tree
state-dir helper is already `~/.claude/hooks/lib/harness_state_dir.sh`.

Deviations: DEVIATIONS below, one entry per block the base tree's (2acc29b) replay meets, each with a
comment quoting the hook's text; nothing else passes a block. A block no declared deviation passes
pauses the agent that met it (Subagent Hook Discipline): the main agent ends its turn reporting the
hook and its text; a paused merge-analyst writes no grant, so Step 3 aborts.

Not replayed: a linked (registered_worktree) worktree, and /merge after a pipeline that left files in
the toy (the in_place clean-tree refusal prompts/P1c.md lists); the feature branch here is the owner's.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone

from .. import agents, cmdtext
from ..pipeline import _ASSIGN_RE, _FOR_RE, _SHELL_SPECIAL, _VAR_RE, Deviations, Orchestrator, Respelling, parse_declare
from ..replay import Deviation
from . import close as closedrv

PIPELINE = "merge"
# The artifact check's cost of each variant (tests/artifact_graph/shards.py balances its CI shards by it):
# CPU seconds of the shipped and armed traced replays and their differential runs, measured at b8e34f4
COST = {"plain": 104, "conflict": 177}

FEATURE = "feature/toy-sub-format"
# The owner's files: the feature commit's toy/util.py, and the main line's commit after the branch
# point (README.md, or in variant conflict the same line of toy/util.py), so the merge is a
# three-way merge with a merge commit.
SUB_NEW = "def sub(a, b):\n    return a - b\n"
SUB_MAIN = "def sub(a,b): return a - b\n"   # variant conflict: the main line changes the same line
README_MAIN = "# toy\n\nAdd and subtract numbers.\n"
SUB_RESOLVED = SUB_NEW

SID_RESPELLING = Respelling(
    "M-S session id", r'SESSION_ID="\$\{CLAUDE_SESSION_ID\}"',
    'SESSION_ID="${CLAUDE_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-}}"',
    "commands/merge.md Step 1 (:87): the CLI's Bash exports CLAUDE_CODE_SESSION_ID only (P1c X4)")

# Blocks the base tree's replay meets, each passed by a deviation at the step it occurs on: the
# refused call is applied as if allowed, so every later step runs and is traced.
DEVIATIONS = Deviations([
    # DEVIATION: "BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm"
    # pretool-bash-safety.sh refuses the base text's Step 3 consume of the grant
    # (`rm -f "/tmp/agentic-commit/merge-analyst/${REPO_HASH}/${SESSION_ID}/${REQUEST_ID}.json"`).
    ("/merge* Step 3 Bash consume grant", Deviation(
        "hooks/pretool-bash-safety.sh", "FORBIDDEN_REMOVAL filesystem_removal:rm",
        "Step 3's consume (unlink) of the grant as the base text spells it")),
])


class Paused(Exception):
    """A hook refused a call no declared deviation passes: the agent pauses and reports (Subagent Hook
    Discipline); the turn ends there."""


def refusal(rp, label: str) -> str:
    """The block that stopped the step `label` (hook and normalised text), for the pause message."""
    b = next((b for b in reversed(rp.blocks) if b["step"] == label and not b["passed_by_deviation"]), None)
    return f"{b['hook']} refused {label!r}: {b['text'][:300]}" if b else f"a hook refused {label!r}"


def _owner_git(project: str, *args, date: str = "") -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    p = subprocess.run(["git", "-C", project, *args], capture_output=True, text=True, env=env)
    if p.returncode:
        raise RuntimeError(f"owner git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout.strip()


def _write(project: str, rel: str, text: str) -> None:
    with open(os.path.join(project, rel), "w") as fh:
        fh.write(text)


def _shell_bind(text: str, values: dict) -> str:
    """Assignments for the variables `text` reads but does not set (each Bash call is a new shell)."""
    used = list(dict.fromkeys(_VAR_RE.findall(text)))
    assigned = set(_ASSIGN_RE.findall(text)) | set(_FOR_RE.findall(text))
    lines = [f"{v}={shlex.quote(str(values[v]))}" for v in used
             if v in values and v not in assigned and v not in _SHELL_SPECIAL]
    return "\n".join(lines + [text]) if lines else text


def _capture_tail(names) -> str:
    """Print the listed variables after the block with `declare -p`, keeping the block's exit status."""
    return ("\n__rc=$?\nfor __v in " + " ".join(names) + '; do declare -p "$__v" 2>/dev/null; done\nexit $__rc\n')


def _is_assignments(text: str) -> bool:
    lines = [l for l in text.split("\n") if l.strip()]
    return bool(lines) and all(re.match(r"^[A-Z_][A-Z0-9_]*=", l) for l in lines)


def _phases(text: str) -> list:
    """(title, section text) of the agent file's `### Phase N: ...` headings, in file order."""
    out = []
    for m in re.finditer(r"^###\s+(Phase \d+:[^\n]*)$", text, re.M):
        out.append((m.group(1).strip(), cmdtext.section(text, m.group(1).strip())))
    return out


class MergeRun:
    """One /merge turn of the main agent (Steps 0-5) with the merge-analyst it dispatches."""

    def __init__(self, rp, session=None, devs: Deviations | None = None, typed_ref: str = "", sid_mode: str = "respelled",
                 tag: str = "/merge"):
        self.rp, self.typed_ref, self.sid_mode, self.tag = rp, typed_ref, sid_mode, tag
        self.devs = closedrv.kept_only(rp, devs or DEVIATIONS)
        rp.deviation_at = self.devs.at  # the analyst's own calls take the same deviations by label
        respellings = [SID_RESPELLING] if sid_mode == "respelled" else []
        self.o = Orchestrator(rp, "merge", session=session, deviations=self.devs, respellings=respellings,
                              rules=self._rules())
        self.analyst_text = self.o.tree.agent_text(self.role())
        self.grant: dict = {}
        self.grant_path = ""
        self.outcome = ""
        self.round = 0
        self.printed = ""

    # ------------------------------------------------------------ text and values
    def _rules(self):
        return [(r"^the-resolved-merge-source$", lambda m: self.o.values["RESOLVED_REF"]),
                (r"^resolved-ref$", lambda m: self.o.values["RESOLVED_REF"]),
                (r"^([A-Z][A-Z_]*)$", lambda m: self.o.values.get(m.group(1), m.group(0)))]

    def label(self, text: str) -> str:
        return f"{self.tag} {text}"

    def role(self) -> str:
        m = re.search(r"Dispatch the `([\w-]+)` subagent", cmdtext.section(self.o.text, "Step 2"))
        if not m:
            raise cmdtext.TextNotFound("Step 2 names no `<role>` subagent to dispatch")
        return m.group(1)

    def quoted_after(self, heading: str, anchor: str) -> str:
        """The first double-quoted message after `anchor` in a step (the text's abort message)."""
        sec = cmdtext.section(self.o.text, heading)
        i = sec.find(anchor)
        m = re.search(r'"([^"\n]+(?:\n[^"\n]+)*)"', sec[i:]) if i >= 0 else None
        if not m:
            raise cmdtext.TextNotFound(f"{heading}: no quoted message after {anchor!r}")
        return " ".join(m.group(1).split())

    def say_stop(self, text: str) -> None:
        self.outcome = text
        self.o.s.stop(text, label=self.label("Stop"), deviation=self.devs.at(self.label("Stop")))

    def captured(self, text: str, label: str, desc: str, names=(), actor=None):
        """One Bash call of a block; the listed variables it sets kept in the orchestrator's values."""
        o = self.o
        text = o.shell_bind(o.bind(text))
        sets = set(_ASSIGN_RE.findall(text))
        names = [n for n in names if n in sets]
        call = self.check(o.run(text.rstrip("\n") + (_capture_tail(names) if names else "\n"), desc, label, actor=actor))
        out = (call.response.get("stdout") or "") if call.ok else (call.error or "")
        o.values.update(parse_declare(out))
        return call

    def check(self, call):
        """A call a hook refused that no declared deviation passed: pause (the turn ends)."""
        if call.blocked:
            raise Paused(refusal(self.rp, call.label))
        return call

    # ------------------------------------------------------------ Step 0
    def step0(self) -> str:
        o = self.o
        para = cmdtext.inline_codes(o.text, "Step 0", "actual read-only check")
        gits = [" ".join(c.split()) for c in para if c.split()[:1] == ["git"]]
        if len(gits) < 2:
            raise cmdtext.TextNotFound("Step 0 names no read-only git for the worktree-shape judgment")
        c = self.check(o.run("\n".join(gits), "Step 0: worktree shape (read-only)", self.label("Step 0 Bash worktree shape")))
        out = (c.response.get("stdout") or "").split("\n") if c.ok else []
        first = next((l.split()[0] for l in out if l.strip()), "")
        top = next((l.strip() for l in out[1:] if l.startswith("/") and not re.search(r"\s", l.strip())), "")
        in_place = bool(first) and os.path.realpath(first) == os.path.realpath(top or "/nonexistent")
        o.values["IS_IN_PLACE"] = "true" if in_place else "false"
        closedrv.fact(self.rp, "merge worktree shape", {"is_in_place": in_place})
        if self.typed_ref:
            return self.typed_ref  # tier 1: the explicit argument
        # tier 2: an overnight-state record in the conversation's context: this session has none.
        if not in_place:
            return ""
        tier3 = [" ".join(c.split()) for c in cmdtext.inline_codes(o.text, "Step 0", "IS_IN_PLACE` is true")
                 if c.startswith("git ")]
        if not tier3:
            raise cmdtext.TextNotFound("Step 0's tier 3 names no git call")
        c = self.check(o.run(tier3[0], "Step 0: tier 3, the current branch", self.label("Step 0 Bash current branch")))
        return (c.response.get("stdout") or "").strip() if c.ok else ""

    # ------------------------------------------------------------ Step 1
    def step1(self, ref: str) -> bool:
        o = self.o
        o.values["RESOLVED_REF"] = ref
        block = o.block("Step 1", lang="bash")
        names = ("RESOLVED_REF", "SOURCE_TIP", "DEFAULT_BRANCH", "DEFAULT_TIP", "REPO_ROOT", "REPO_HASH",
                 "REQUEST_ID", "SESSION_ID")
        self.captured(block, self.label("Step 1 Bash snapshot"), "Step 1: pre-merge snapshot", names)
        self.rp.rand(o.values.get("REQUEST_ID"))
        v = o.values
        if not v.get("SESSION_ID"):
            self.say_stop(self.quoted_after("Step 1", "abort immediately with"))
            return False
        missing = [k for k in ("SOURCE_TIP", "DEFAULT_TIP") if v.get(k, "MISSING") == "MISSING"]
        if missing:
            self.say_stop(f"/merge aborted: {', '.join(missing)} not found "
                          f"({v.get('RESOLVED_REF')} / {v.get('DEFAULT_BRANCH')} does not resolve to a commit)")
            return False
        if v["SOURCE_TIP"] == v["DEFAULT_TIP"]:
            msg = self.quoted_after("Step 1", "abort with \"refusing self-merge")
            self.say_stop(msg)
            return False
        return True

    def fresh_request_id(self, k: int) -> None:
        """Step 1's REQUEST_ID line again (the base text's "return to Step 2 with a fresh REQUEST_ID")."""
        line = next(l for l in self.o.block("Step 1", lang="bash").split("\n") if l.startswith("REQUEST_ID="))
        self.captured(line, self.label(f"Step 1 Bash fresh REQUEST_ID {k}"), "A fresh REQUEST_ID", ("REQUEST_ID",))
        self.rp.rand(self.o.values.get("REQUEST_ID"))

    # ------------------------------------------------------------ Step 2 and the analyst
    def prompt(self) -> str:
        o = self.o
        sec = o.section("Step 2")
        fence = next(b.text for b in cmdtext.blocks(sec) if "REQUEST_ID=" in b.text)
        prompt = o.instantiate(fence, None)
        left: list = []
        prompt = o.bind(prompt, unbound=left)
        if left:
            raise cmdtext.TextNotFound(f"Step 2 prompt: unbound placeholders {sorted(set(left))}")
        return prompt.rstrip("\n")

    def step2(self) -> None:
        o = self.o
        self.round += 1
        lab = self.label("Step 2 Agent(merge-analyst)") + (f" round {self.round}" if self.round > 1 else "")
        prompt = self.prompt()
        analyst = Analyst(self, prompt)
        player = agents.Player(o.tree, prompt, agents.Act(work=analyst.work, summary="pre-merge analysis"),
                               role=self.role())
        analyst.player = player
        d = o.s.dispatch(self.role(), prompt, description="pre-merge analysis", body=player.body,
                         result=analyst.final, label=lab, deviation=self.devs.at(lab))
        self.check(d)
        if d.stop is not None and d.stop.still_blocked:
            raise Paused(refusal(self.rp, lab + " stop"))
        text = ((d.response.get("content") or [{}])[0].get("text") or "") if d.response else ""
        m = re.findall(r"^merge-analyst grant written: (\S+)$", text, re.M)
        self.printed = m[-1] if m else ""
        closedrv.fact(self.rp, "merge-analyst", {"round": self.round, "verdict": analyst.verdict,
                                                 "risks": analyst.risks, "grant_writes": analyst.writes,
                                                 "printed": self.rp.norm_text(self.printed)})

    # ------------------------------------------------------------ Step 3
    def grant_location(self) -> str:
        """The path Step 3 gives, its placeholders bound; `<state dir>` as the step's parenthesis says."""
        o = self.o
        sec = o.section("Step 3")
        path = next(b.text for b in cmdtext.blocks(sec) if "agentic-commit/merge-analyst" in b.text).strip()
        path = o.bind(path, [(r"^state dir$", lambda m: "<state dir>")])
        if "<state dir>" in path:
            suffix = path.split("<state dir>", 1)[1]
            if self.printed.endswith(suffix):
                state = self.printed[:-len(suffix)]
            else:
                env = self.rp.bash_env.get("CLAUDE_STATE_DIR", "")
                state = env if os.path.isabs(env) else "/tmp"
            path = state + suffix
        return path

    def step3(self) -> str:
        """"approved", "blocked", "missing", "invalid" or "expired"."""
        o = self.o
        self.grant_path = path = self.grant_location()
        c = self.check(o.s.read(path, label=self.label("Step 3 Read grant"),
                                deviation=self.devs.at(self.label("Step 3 Read grant"))))
        if not c.ok:
            self.say_stop(self.quoted_after("Step 3", "abort with"))
            return "missing"
        try:
            self.grant = json.loads(agents.peek(self.rp, "main", path))
        except ValueError:
            self.grant = None
        sec = o.section("Step 3")
        if "Validate the following fields" in sec:  # the text validates the grant itself (the base)
            fault = self.validate(sec)
            if fault == "expired":
                return "expired"
            if fault:
                self.say_stop(f"/merge aborted: merge-analyst grant {fault}")
                return "invalid"
            consume = next((b.text for b in cmdtext.blocks(sec, None, "bash") if "rm -f" in b.text), None)
            if consume:
                self.captured(consume, self.label("Step 3 Bash consume grant"), "Consume (unlink) the grant")
        verdict = (self.grant or {}).get("verdict")
        if verdict == "blocked":
            risks = "\n".join(f"- {r}" for r in self.grant.get("risks") or [])
            self.say_stop(f"merge-analyst blocked the merge; nothing merged.\n{risks}")
        return verdict or "invalid"

    def validate(self, sec: str) -> str:
        """The base text's field list: '' when every check holds, else the failing field ("expired")."""
        g = self.grant
        if not isinstance(g, dict):
            return "is not valid JSON"
        v = self.o.values
        for field, var in re.findall(r"^- `(\w+)` field matches `(\w+)`", sec, re.M):
            if g.get(field) != v.get(var):
                return f"field `{field}` does not match {var}"
        m = re.search(r"`verdict` field is one of: ([^\n(]+)", sec)
        allowed = re.findall(r'"(\w+)"', m.group(1)) if m else ["approved", "blocked"]
        if g.get("verdict") not in allowed:
            return "field `verdict` is not one of " + "/".join(allowed)
        if not isinstance(g.get("risks"), list):
            return "field `risks` is not a JSON array"
        try:
            exp = datetime.fromisoformat(str(g.get("expires_at")).replace("Z", "+00:00"))
        except ValueError:
            return "field `expires_at` is not ISO-8601"
        if exp.tzinfo is None or exp <= datetime.now(timezone.utc):
            return "expired"
        return ""

    # ------------------------------------------------------------ Steps 4 and 5
    def step4(self) -> bool:
        o = self.o
        self.captured(o.block("Step 4", lang="bash"), self.label("Step 4 Bash revalidate tips"),
                      "Step 4: re-read the branch tips", ("CURRENT_SOURCE_TIP", "CURRENT_DEFAULT_TIP"))
        v, g = o.values, self.grant or {}
        if v.get("CURRENT_SOURCE_TIP") != g.get("source_tip") or v.get("CURRENT_DEFAULT_TIP") != g.get("default_tip"):
            self.say_stop(self.quoted_after("Step 4", "abort with"))
            return False
        return True

    def step5(self):
        o = self.o
        block = o.block("Step 5", lang="bash")
        c = self.check(o.run(o.bind(block), "Step 5: call merge.sh", self.label("Step 5 Bash merge.sh")))
        closedrv.fact(self.rp, "merge.sh", {"ok": c.ok, "blocked": c.blocked,
                                           "output": self.rp.norm_text((c.response.get("stdout") or "") if c.ok
                                                                       else (c.error or ""))[-1500:],
                                           "toy": toy_state(self.rp)})
        return c

    # ------------------------------------------------------------ the turn
    def run(self, args: str = "") -> str:
        try:
            return self.turn(args)
        except Paused as p:
            self.say_stop(f"PAUSE: {p}. Pausing per the Subagent Hook Discipline: the refused operation is not "
                          "retried, wrapped or bypassed; it needs a human ruling.")
            closedrv.fact(self.rp, "merge paused", str(p))
            return self.outcome

    def turn(self, args: str) -> str:
        o = self.o
        o.slash(args, label=self.label("typed"))
        ref = self.step0()
        if not ref:
            self.say_stop("/merge: no tier resolved a merge source; pass an explicit ref: /merge <ref>")
            return self.outcome
        if not self.step1(ref):
            return self.outcome
        for k in range(3):
            self.step2()
            verdict = self.step3()
            if verdict != "expired":
                break
            o.s.say("The merge-analyst grant expired before it was read; a fresh analysis is running.")
            self.fresh_request_id(k + 1)
        else:
            self.say_stop("/merge aborted: the merge-analyst grant expired on every round")
            return self.outcome
        if verdict != "approved":
            return self.outcome
        if not self.step4():
            return self.outcome
        c = self.step5()
        if c.ok:
            text = f"Merged {o.values['RESOLVED_REF']} into {o.values['DEFAULT_BRANCH']}.\n" + \
                   "\n".join(l for l in (c.response.get("stdout") or "").split("\n") if l.startswith("merge.sh:"))
        else:
            text = ("merge.sh exited non-zero; the merge did not complete. Resolve it manually as the wrapper "
                    "says, then re-run /merge " + o.values["RESOLVED_REF"] + ".\n" + (c.error or "")[-800:])
        self.say_stop(text)
        return self.outcome


class Analyst:
    """The merge-analyst's work, from its agent file's Workflow phases, in order."""

    def __init__(self, run: MergeRun, prompt: str):
        self.run, self.rp = run, run.rp
        self.text = run.analyst_text
        self.values = dict(re.findall(r"^([A-Z_]+)=(\S*)$", prompt, re.M))
        self.verdict = "approved"
        self.risks: list = []
        self.notes: list = []
        self.writes = 0
        self.player = None
        self.sub = None
        self.grant_doc: dict = {}
        self.commits = None
        self.paused = ""

    # ------------------------------------------------------------ helpers
    def fill(self, text: str) -> str:
        return cmdtext.fill(text, {f"<{k}>": v for k, v in self.values.items()})

    def bash(self, text: str, label: str, desc: str, names=()):
        text = _shell_bind(self.fill(text), self.values)
        sets = set(_ASSIGN_RE.findall(text))
        names = [n for n in names if n in sets]
        lab = f"{self.sub.role} Bash {label}"
        c = self.checked(self.sub.bash(text.rstrip("\n") + (_capture_tail(names) if names else "\n"), desc, label=lab))
        out = (c.response.get("stdout") or "") if c.ok else (c.error or "")
        self.values.update(parse_declare(out))
        return c, out

    def block(self, why: str):
        """A blocking risk: the verdict Phase 6 computes is `blocked`."""
        self.verdict = "blocked"
        self.risks.append(why)

    # ------------------------------------------------------------ the phases
    def work(self, sub, brief, player):
        self.sub = sub
        try:
            self.phases()
        except Paused as p:
            self.paused = str(p)
        return None

    def final(self, sub=None) -> str:
        """The analyst's closing message; a paused analyst wrote no grant and prints no grant line."""
        if self.paused:
            return (f"PAUSE: {self.paused}. Pausing per the Subagent Hook Discipline; no grant written "
                    "(agents/merge-analyst.md Error handling: the orchestrator detects the missing grant).")
        return self.player.final(sub)

    def checked(self, call):
        if call.blocked:
            raise Paused(refusal(self.rp, call.label))
        return call

    def phases(self):
        phases = _phases(self.text)
        stopped = False
        for title, sec in phases:
            fences = cmdtext.blocks(sec)
            if any(b.lang == "json" for b in fences):
                self.write_grant(title, sec, fences)
                continue
            if stopped:
                continue
            if any("CURRENT_SOURCE_TIP=" in b.text for b in fences):
                stopped = self.tips(title, sec, fences)
            elif any("--check" in b.text for b in fences):
                self.markers(title, sec, fences)
            elif any("overnight-state" in b.text for b in fences):
                self.overnight(title, fences)
            elif "Write (append) to" in sec:
                self.audit(title, sec, fences)
            else:
                for k, b in enumerate(f for f in fences if f.lang == "bash"):
                    c, _ = self.bash(b.text, f"{title.split(':')[0]}" + (f" #{k + 1}" if k else ""), title)
                    if "git log --oneline" in b.text and c.ok:
                        self.commits = len([l for l in (c.response.get("stdout") or "").split("\n") if l.strip()])
        return None

    def tips(self, title: str, sec: str, fences) -> bool:
        """Phase 1: the live tips; True when the text says to write a blocked grant and stop."""
        b = next(b for b in fences if "CURRENT_SOURCE_TIP=" in b.text)
        self.bash(b.text, title.split(":")[0], title, ("CURRENT_SOURCE_TIP", "CURRENT_DEFAULT_TIP"))
        v = self.values
        risks = re.findall(r'risks=\["([^"]+)"\]', sec)
        cur_s, cur_d = v.get("CURRENT_SOURCE_TIP", "MISSING"), v.get("CURRENT_DEFAULT_TIP", "MISSING")
        if "MISSING" in (cur_s, cur_d):
            self.block((risks[0] if risks else "ref does not resolve").replace(
                "<ref>", v["RESOLVED_REF"] if cur_s == "MISSING" else v["DEFAULT_BRANCH"]))
            return True
        if cur_s == cur_d:
            self.block(self.fill(risks[1] if len(risks) > 1 else "self-merge").replace(
                "<RESOLVED_REF>", v["RESOLVED_REF"]).replace("<DEFAULT_BRANCH>", v["DEFAULT_BRANCH"]))
            return True
        if cur_s != v.get("SOURCE_TIP") or cur_d != v.get("DEFAULT_TIP"):
            self.block(risks[-1] if risks else "tips changed")
            return True
        return False

    def markers(self, title: str, sec: str, fences) -> None:
        """Phase 4: `git diff --check`, the raw marker scan, the MERGE_HEAD probe."""
        risks = re.findall(r'add RISK "([^"]+)"', sec)
        for k, b in enumerate(f for f in fences if f.lang == "bash"):
            c, _ = self.bash(b.text, f"{title.split(':')[0]} #{k + 1}", title, ("CONFLICT_MARKER_FOUND",))
            if "--check" in b.text and (self.values.get("CONFLICT_MARKER_FOUND") == "true" or not c.ok):
                self.block(next((r for r in risks if "Conflict markers" in r), "conflict markers"))
            elif "grep -E" in b.text and c.ok and (c.response.get("stdout") or "").strip():
                self.block("conflict marker lines in the diff")
            elif "MERGE_HEAD" in b.text and "MERGE_HEAD_EXISTS" in ((c.response.get("stdout") or "") if c.ok else ""):
                self.block(next((r for r in risks if "MERGE_HEAD" in r), "MERGE_HEAD exists"))

    def overnight(self, title: str, fences) -> None:
        """Phase 5: the listing; the first record Read when one exists (validation only)."""
        b = next(b for b in fences if "overnight-state" in b.text)
        c, _ = self.bash(b.text, title.split(":")[0], title)
        files = [l for l in ((c.response.get("stdout") or "") if c.ok else "").split("\n") if l.strip()]
        if files:
            path = os.path.join(self.rp.layout.project, files[0])
            self.checked(self.sub.read(path, label=f"{self.sub.role} Read overnight state"))
            try:
                branch = json.loads(agents.peek(self.rp, self.sub.role, path)).get("worktree_branch")
            except (OSError, ValueError):
                branch = None
            if branch and branch != self.values["RESOLVED_REF"]:
                self.notes.append(f"overnight-state references a different branch (`{branch}`)")

    def audit(self, title: str, sec: str, fences) -> None:
        """The base text's audit log: its directory, then the line appended to the file it names."""
        for k, b in enumerate(f for f in fences if f.lang == "bash"):
            self.bash(b.text, f"{title.split(':')[0]} #{k + 1}", title)
        m = re.search(r"Write \(append\) to `([^`]+)`", sec)
        line = next((b.text.strip() for b in fences if not b.lang and "<" in b.text), "")
        if not m or not line:
            return
        target = self.fill(m.group(1))
        line = self.fill(line).replace("<ISO-8601 UTC>", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        line = line.replace("<SOURCE_TIP[:8]>", self.values.get("SOURCE_TIP", "")[:8]).replace("<verdict>", self.verdict)
        self.bash(f"printf '%s\\n' {shlex.quote(line)} >> {shlex.quote(target)}", f"{title.split(':')[0]} append",
                  "Append the audit entry")

    def write_grant(self, title: str, sec: str, fences) -> None:
        """Phase 8: the grant path (the text's assignments, with its mkdir), expires_at from the text's
        python, the grant Written from its JSON template, the closing line."""
        ph = title.split(":")[0]
        assign = next((b.text for b in fences if not b.lang and _is_assignments(b.text)), "")
        mkdir = next((b.text for b in fences if b.lang == "bash" and "mkdir" in b.text), "")
        names = tuple(dict.fromkeys(_ASSIGN_RE.findall(assign)))
        self.bash((assign.rstrip("\n") + "\n" if assign else "") + mkdir, f"{ph} grant dir", "Grant directory and path",
                  names)
        py = next((b.text for b in fences if b.lang == "python"), "")
        var = (re.findall(r"^([A-Za-z_]\w*)\s*=", py, re.M) or ["expires_at"])[-1]
        c, out = self.bash(f"python3 -c {shlex.quote(py.rstrip() + chr(10) + f'print({var})')}", f"{ph} expires_at",
                           "Compute expires_at (60 s)")
        expires = ((c.response.get("stdout") or "").strip().split("\n") or [""])[-1] if c.ok else ""
        tpl = json.loads(next(b.text for b in fences if b.lang == "json"))
        self.grant_doc = self.grant_from(tpl, expires)
        path = self.values.get("GRANT_PATH") or ""
        if not path:
            raise agents.PlayError(f"{ph}: the text's assignments give no GRANT_PATH")
        self.put_grant(path)
        line = next((b.text.strip() for b in fences if not b.lang and "grant written" in b.text), "")
        line = line.replace("<GRANT_PATH>", path) if line else f"merge-analyst grant written: {path}"
        self.player.act.terminal["response_line"] = line
        self.player.act.final_line = line
        summary = self.grant_doc.get("analysis_summary", "")
        self.player.act.summary = summary

    def grant_from(self, tpl: dict, expires: str) -> dict:
        v = self.values
        commits = "" if self.commits is None else str(self.commits)
        doc = {}
        for k, val in tpl.items():
            if isinstance(val, list):
                doc[k] = list(self.risks)
                continue
            m = re.fullmatch(r"<([A-Z_]+)>", str(val))
            if m and m.group(1) in v:
                doc[k] = v[m.group(1)]
            elif re.fullmatch(r"<approved\|blocked>", str(val)):
                doc[k] = self.verdict
            elif "summary" in str(val):
                doc[k] = (f"{v['RESOLVED_REF']} brings {commits or 'its'} commit(s) onto {v['DEFAULT_BRANCH']}; "
                          + ("no conflict markers, no unresolved merge state." if self.verdict == "approved"
                             else "blocked: " + "; ".join(self.risks))
                          + "".join(f" Note: {n}." for n in self.notes))
            elif "ISO-8601" in str(val):
                doc[k] = expires
            else:
                raise agents.PlayError(f"grant template field {k}: no value for {val!r}")
        return doc

    def put_grant(self, path: str) -> None:
        sub = self.sub
        text = json.dumps(self.grant_doc, indent=2) + "\n"
        w = self.checked(sub.write(path, text, label=f"{sub.role} Write grant"))
        self.writes += 1
        refused = [h for h in ((w.post.hooks if w.post else []) or []) if h["verdict"] == "block"]
        if w.ok and refused and not os.path.exists(path):
            # MERGE_GRANT_INVALID: the PostToolUse check removed it; Write it again from the analysis.
            sub.write(path, text, label=f"{sub.role} Write grant again")
            self.writes += 1


def toy_state(rp) -> dict:
    """Driver diagnostics, no agent call: the toy's branch, tips, last commits and status."""
    p = rp.layout.project
    with rp.acting("driver"):
        def g(*a):
            r = subprocess.run(["git", "-C", p, *a], capture_output=True, text=True)
            return r.stdout.strip()
        return {"branch": g("branch", "--show-current"),
                "log": g("log", "--format=%s | parents=%p", "-4").split("\n"),
                "status": g("status", "--porcelain").split("\n") if g("status", "--porcelain") else [],
                "branches": g("branch", "--format=%(refname:short)").split("\n")}


def owner_setup(rp, variant: str) -> None:
    """Before the session, in the owner's terminal: a feature commit and a main-line commit after
    the branch point; the feature branch checked out in the main checkout."""
    p = rp.layout.project
    with rp.acting("owner"):
        _owner_git(p, "checkout", "-q", "-b", FEATURE)
        _write(p, "toy/util.py", SUB_NEW)
        _owner_git(p, "commit", "-qam", "toy: format sub", date="2026-01-01T00:01:00+0000")
        _owner_git(p, "checkout", "-q", "master")
        if variant == "conflict":
            _write(p, "toy/util.py", SUB_MAIN)
            _owner_git(p, "commit", "-qam", "toy: spaces in sub", date="2026-01-01T00:02:00+0000")
        else:
            _write(p, "README.md", README_MAIN)
            _owner_git(p, "commit", "-qam", "docs: say what toy does", date="2026-01-01T00:02:00+0000")
        _owner_git(p, "checkout", "-q", FEATURE)


def owner_resolve(rp) -> None:
    """The conflict variant: the owner resolves the merge merge.sh left and commits it (their terminal)."""
    p = rp.layout.project
    with rp.acting("owner"):
        _write(p, "toy/util.py", SUB_RESOLVED)
        _owner_git(p, "add", "toy/util.py")
        _owner_git(p, "commit", "-q", "--no-edit", date="2026-01-01T00:03:00+0000")
    closedrv.fact(rp, "owner resolved the conflict", toy_state(rp))


VARIANTS = ("plain", "conflict")


def run(rp) -> None:
    variant = rp.args.get("variant", "plain")
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    sid_mode = rp.args.get("sid", "respelled")
    if sid_mode not in ("respelled", "cli"):
        raise ValueError(f"sid must be respelled or cli, not {sid_mode!r}")
    ref = rp.args.get("ref", "")
    rp.pipeline = "merge" + (f"/{variant}" if variant != "plain" else "") + ("/sid-cli" if sid_mode == "cli" else "")
    owner_setup(rp, variant)
    closedrv.fact(rp, "owner setup", toy_state(rp))
    mr = MergeRun(rp, typed_ref=ref, sid_mode=sid_mode)
    mr.run(ref)
    if variant == "conflict" and mr.o.values.get("RESOLVED_REF"):
        st = toy_state(rp)
        if any(s[:2] in ("UU", "AA") for s in st["status"]):
            owner_resolve(rp)
            again = MergeRun(rp, session=mr.o.s, typed_ref=ref or mr.o.values["RESOLVED_REF"], sid_mode=sid_mode,
                             tag="/merge (2)")
            again.run(ref or mr.o.values["RESOLVED_REF"])
