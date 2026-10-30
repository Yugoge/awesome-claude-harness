"""/push, played compliantly from commands/push.md and agents/push-analyst.md of the tree under test,
after a /commit that landed (drivers/commit.py, after drivers/do.py or drivers/dev.py and drivers/close.py).

The cycle, its /close and its /commit run first, each by its own driver, as drivers/commit.py composes
/close with the cycle: the /commit lands its commit on the toy's branch and its changelog-analyst
writes the push-gate token where the tree's text puts it. Then the main agent types `/push` (bare;
`--arg remote=<name>` types `/push <name>`, `--arg auto=1` adds `--auto`) and does what each step of
the tree's "Agentic dispatch protocol" says, read at run time:

* Step 0: the step's block (the fork-prefer-origin remote); a typed remote overrides it, as the
  block's own comment says.
* Step 1: where the text has the orchestrator validate the token itself (the base), the scan it
  describes: the repo hash and branch by Step 2's own lines, the `find` the Session commit
  prerequisite's READ side gives over the token directory Step 1 names, each candidate Read and its
  `commit_sha` tested with the `git merge-base --is-ancestor` the step names; no candidate passing
  ends the turn with the step's instruction to run /commit first. Where the text says the step
  reads nothing (push.sh is the token's one decider), no call.
* Step 2: the step's block, its variables kept; an empty SESSION_ID ends the turn with the text's
  message.
* Step 3: the dispatch the step names (`Dispatch the `<role>` subagent`) with the step's context block
  as its prompt, placeholders bound to Step 2's values and the obligation, where the block has one,
  instantiated (dispatched_at the current UTC time).
* The push-analyst, played from its agent file (merge.Analyst's helpers, the phases below): each
  Workflow phase's blocks in order, the prompt's values bound: the git root and the range (its
  `git log`; an empty range writes the `approved` grant the text words and ends the analysis); the
  file list of the range against the basename patterns the text lists (a match read with `git show`
  for credential content); the branch-protection and divergence rules as the text words their risks;
  the verdict as Phase 5 ranks the levels; where the text keeps an audit log, its directory and the
  entry Written with the Write tool; the grant directory and path as the text computes them (one Bash
  call with its mkdir), expires_at from the text's own python, the grant Written from the text's JSON
  template, and the closing `grant written` line (the response line the obligation declares where
  the dispatch carries one).
* Step 4: nothing: the text forbids the orchestrator to read, validate or unlink the grant.
* Step 5: the form of the step's block the typed arguments select (`# Without --auto:` or `# With
  --auto`), its variables bound: execute-push.py validates and spends the grant, writes the chain-B
  sentinel and execs hooks/push.sh, which decides the push-gate token, pushes to the toy's local bare
  origin and deletes the token. The outcome (the origin's branch against HEAD, the token, grant and
  sentinel left) is recorded in facts.json; Stop.

Driver arguments (cli.py --arg K=V):
  after=do|dev|dev-command   the cycle /close and /commit follow (default do, the shortest)
  after=none                 no cycle: the owner commits in their own terminal and types /push, so no
                             push-gate token exists: the base text's Step 1 aborts before the dispatch,
                             the working tree's push.sh refuses (exit 3) after execute-push.py spent the
                             grant. Not a variant: its relations are a subset of the plain push's.
  session=same|later         /push typed in /commit's session (default) or a later one
  remote=<name>, auto=1      the typed arguments of /push
  statedir=respelled|strict  how Step 5 runs on a text whose sentinel path is a literal directory
                             (see "State dir" below; default respelled)
  kept=<JSON>                [[hook, step, normalised text], ...]: the blocks the base kit's replay of
                             the same arguments and settings recorded; given, a declared deviation passes
                             only a block in that list (drivers/dev.py KeptOnly)

State dir. Rule 8 sets CLAUDE_STATE_DIR to a directory other than /tmp in every replay. The base text
(2acc29b) names the push-analyst grant and the chain-B sentinel under a literal `/tmp/agentic-commit/
push-analyst/` (commands/push.md:189, :214; agents/push-analyst.md Phase 7), as its execute-push.py
writes them (`_SENTINEL_BASE`, scripts/execute-push.py:35), and its changelog-analyst writes the
push-gate token under `/tmp/agentic-commit/push/` (Phase 10), while its hooks/push.sh reads both
under `$(harness_state_dir)` (:106, :212). Run as written (`--arg statedir=strict`), Step 5's call
spends the grant and push.sh then refuses for a missing sentinel (exit 1): a failure, not a block, so
no DEVIATION passes it, and row 7's respellings name harness-script paths only. By default the driver
runs Step 5's call with CLAUDE_STATE_DIR set, in that call's environment only, to the directory the
step's text names for the sentinel (the way row 7 sets CLAUDE_PROJECT_DIR for a script that finds the
product root only through it), recorded in blocks.json "respellings" as "P-SD state dir" at each
application, so the replay reaches the push. A text that names `<state dir>` there (the working
tree) needs none and gets none. P1b's own row 12 owns these lines (execute-push.py:35 and the
analyst's grant path move under harness_state_dir(), like push.sh:106, :212); no later phase's row
does.

Respellings (row 7): none of the /push text's harness-script calls needs one (Step 5's `python3
~/.claude/scripts/execute-push.py` already names the harness copy). Step 2's session-id line already
falls back to CLAUDE_CODE_SESSION_ID (the binding drivers/merge.py borrows for merge.md:87).

Deviations: DEVIATIONS below, one entry per block the base tree's replay meets, each with a comment
quoting the hook's text; nothing else passes a block. On 2acc29b: bash-safety on the analyst's Phase 1
range block and Phase 4 divergence block (kept: the working tree records them too, on lines no row
changes), and the base's push-analyst grant guard on Step 5's call (base only: row 12 and E11 leave
execute-push.py the grant's one validator). The base text's Step 1 scan, as the text spells its `find`,
meets no block. A block no declared deviation passes pauses the agent that met it (Subagent Hook
Discipline): the main agent ends its turn reporting the hook and its text; a paused push-analyst writes
no grant, so Step 5's execute-push.py finds none.

Not replayed: a push to a `fork` remote, a blocked verdict, an expired grant and a token whose commit
left HEAD's history: each takes fewer relations than the plain push (no sentinel, no push, no token
spent) and a refused grant or token is a fault P1c injects at the step it names.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone

from .. import agents, cmdtext
from ..pipeline import _ASSIGN_RE, Deviations, Orchestrator, Respelling
from ..replay import Deviation
from . import close as closedrv
from . import merge as mergedrv

PIPELINE = "push"

# Blocks the base tree's replay meets, each passed by a deviation at the step it occurs on: the
# refused call is applied as if allowed, so every later step runs and is traced.
DEVIATIONS = Deviations([
    # DEVIATION: "BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:git rev-parse:"
    # pretool-bash-safety.sh refuses the push-analyst's Phase 1 range block and Phase 4 divergence block as
    # its agent text spells them (`if git rev-parse "refs/remotes/${REMOTE_NAME}/${BRANCH}" >/dev/null 2>&1;
    # then`, the prompt's values bound as shell variables), in both kits; the same test with the values
    # written literally passes.
    ("agent:push-analyst Bash Phase 1 #2", Deviation(
        "hooks/pretool-bash-safety.sh", "unproven_boundary_with_removal_reference:git rev-parse:",
        "Phase 1's range block as the agent text spells it")),
    ("agent:push-analyst Bash Phase 4", Deviation(
        "hooks/pretool-bash-safety.sh", "unproven_boundary_with_removal_reference:git rev-parse:",
        "Phase 4's divergence block as the agent text spells it")),
    # DEVIATION: "BLOCKED: push-analyst grant guard: no push-analyst grant found at
    # <state>/agentic-commit/push-analyst/<hex>/<sid>/${REQUEST_ID}.json."
    # The base's pretool-push-analyst-grant-guard.py, the grant's second validator (E11), refuses Step 5's
    # call as the text spells it: it looks the grant up under the hook's state dir, where the base text's
    # analyst does not write it, by the unexpanded `"${REQUEST_ID}"` of the command text.
    ("/push Step 5 Bash execute-push", Deviation(
        "hooks/pretool-push-analyst-grant-guard.py", "BLOCKED: push-analyst grant guard: no push-analyst grant found at",
        "Step 5's execute-push.py call as the text spells it")),
])

_STEP_RE = re.compile(r"^\*\*(Step \d+)\b[^\n]*\*\*[ \t]*$", re.M)
_LEVELS = ("approved", "warn", "blocked")


def steps(text: str) -> dict:
    """{"Step N": text} of the dispatch protocol: its bold step lines, each up to the next one (or its
    "### Step N" headings, on a text that uses headings)."""
    sec = cmdtext.section(text, "Agentic dispatch protocol")
    ms = list(_STEP_RE.finditer(sec))
    if not ms:
        return {m: cmdtext.section(text, m) for m in re.findall(r"^#{2,6}\s+(Step \d+)\b", text, re.M)}
    return {m.group(1): sec[m.start():(ms[k + 1].start() if k + 1 < len(ms) else len(sec))]
            for k, m in enumerate(ms)}


def item_codes(text: str, anchor: str) -> list:
    """Backtick spans of the one paragraph or list item of `text` that holds `anchor` (whitespace folded)."""
    items = [it for it in re.split(r"\n(?=\s*(?:[-*]|\d+\.)\s)|\n\s*\n", text) if anchor in it]
    if len(items) != 1:
        raise cmdtext.TextNotFound(f"item with {anchor!r}: {len(items)} matches")
    return [" ".join(c.split()) for c in re.findall(r"`([^`]+)`", items[0])]


def form(block: str, auto: bool) -> str:
    """The command of a block that gives one form per `# With ...` / `# Without ...` comment."""
    parts, cur = {}, None
    for line in block.split("\n"):
        m = re.match(r"^#\s*(With(?:out)? --auto)\b", line)
        if m:
            cur = m.group(1)
            parts[cur] = []
        elif cur is not None:
            parts[cur].append(line)
    want = "With --auto" if auto else "Without --auto"
    if want not in parts:
        raise cmdtext.TextNotFound(f"Step 5's block has no `# {want}` form")
    return "\n".join(parts[want]).strip("\n") + "\n"


def origin_state(rp) -> dict:
    """Driver diagnostics, no agent call: the toy's branch and HEAD, the bare origin's branches."""
    lay = rp.layout
    with rp.acting("driver"):
        def g(*a):
            r = subprocess.run(["git", *a], capture_output=True, text=True)
            return r.stdout.strip()
        branch = g("-C", lay.project, "branch", "--show-current")
        return {"branch": branch, "head": g("-C", lay.project, "rev-parse", "HEAD"),
                "origin": g("--git-dir", lay.origin, "for-each-ref", "--format=%(refname:short) %(objectname)",
                            "refs/heads"),
                "upstream": g("-C", lay.project, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")}


def _origin_tip(st: dict) -> str:
    return dict(l.split(" ", 1) for l in st.get("origin", "").split("\n") if " " in l).get(st.get("branch"), "")


def leftovers(rp) -> dict:
    """Driver diagnostics: what is left under each agentic-commit tree (state dir and /tmp)."""
    out = {}
    with rp.acting("driver"):
        for root in (rp.layout.state, "/tmp"):
            base = os.path.join(root, "agentic-commit")
            for dp, _, fs in os.walk(base):
                for f in fs:
                    out.setdefault(root, []).append(rp.norm_text(os.path.join(dp, f)))
    return {k: sorted(v) for k, v in out.items()}


class PushRun:
    """One /push turn of the main agent (Steps 0-5) with the push-analyst it dispatches."""

    def __init__(self, rp, session=None, devs: Deviations | None = None, args: str = "",
                 state_mode: str = "respelled", tag: str = "/push"):
        self.rp, self.args, self.tag = rp, args, tag
        self.devs = closedrv.kept_only(rp, devs or DEVIATIONS)
        rp.deviation_at = self.devs.at  # the analyst's own calls take the same deviations by label
        self.o = Orchestrator(rp, "push", session=session, deviations=self.devs, rules=self._rules())
        self.steps = steps(self.o.text)
        if state_mode == "respelled":
            self.o.respellings = self.state_respellings()
        self.analyst_text = self.o.tree.agent_text(self.role())
        toks = args.split()
        self.auto = "--auto" in toks
        self.typed_remote = next((t for t in toks if not t.startswith("-")), "")
        self.printed = ""
        self.outcome = ""
        self.before: dict = {}

    # ------------------------------------------------------------ text and values
    def _rules(self):
        return [(r"^([A-Z][A-Z_]*)$", lambda m: self.o.values.get(m.group(1), m.group(0)))]

    def label(self, text: str) -> str:
        return f"{self.tag} {text}"

    def step(self, name: str) -> str:
        if name not in self.steps:
            raise cmdtext.TextNotFound(f"commands/push.md has no {name}")
        return self.steps[name]

    def role(self) -> str:
        m = re.search(r"Dispatch the `([\w-]+)` subagent", self.step("Step 3"))
        if not m:
            raise cmdtext.TextNotFound("Step 3 names no `<role>` subagent to dispatch")
        return m.group(1)

    def state_respellings(self) -> list:
        """The text's Step 5 names the chain-B sentinel under a literal directory: Step 5's call runs with
        CLAUDE_STATE_DIR set to it in that call's environment (module docstring, "State dir")."""
        m = re.search(r"`(/[^`<$\s]*?)/agentic-commit/push-analyst/<REPO_HASH>/", self.step("Step 5"))
        if not m:
            return []
        named = m.group(1)
        if os.path.normpath(self.rp.bash_env.get("CLAUDE_STATE_DIR", "")) == os.path.normpath(named):
            return []
        return [Respelling("P-SD state dir", r"(?m)^python3 (~/\.claude/scripts/execute-push\.py)\b",
                           f"CLAUDE_STATE_DIR={named} python3 \\1",
                           "commands/push.md Step 5 (:214, :222-236 at 2acc29b): the sentinel directory the text "
                           "names, which execute-push.py writes and push.sh reads only through CLAUDE_STATE_DIR")]

    def say_stop(self, text: str) -> None:
        self.outcome = text
        self.o.s.stop(text, label=self.label("Stop"), deviation=self.devs.at(self.label("Stop")))

    def check(self, call):
        """A call a hook refused that no declared deviation passed: pause (the turn ends)."""
        if call.blocked:
            raise mergedrv.Paused(mergedrv.refusal(self.rp, call.label))
        return call

    def captured(self, text: str, label: str, desc: str, names=()):
        o = self.o
        text = o.shell_bind(o.bind(text))
        sets = set(_ASSIGN_RE.findall(text))
        return self.check(closedrv.run_captured(o, text, desc, label, [n for n in names if n in sets]))

    # ------------------------------------------------------------ Step 0
    def step0(self) -> None:
        block = cmdtext.block(self.step("Step 0"), lang="bash")
        self.captured(block, self.label("Step 0 Bash resolve remote"), "Step 0: resolve the push remote",
                      ("RESOLVED_REMOTE",))
        if self.typed_remote:  # "Explicit user-provided remote argument overrides the above"
            self.o.values["RESOLVED_REMOTE"] = self.typed_remote

    # ------------------------------------------------------------ Step 1
    def step1(self) -> bool:
        """The base text's own token validation; on a text where the step reads nothing, no call."""
        o, sec = self.o, self.step("Step 1")
        if re.search(r"reads nothing", sec):
            return True
        where = re.search(r"under `([^`]*<repo-hash>/?)`", sec)
        test = next((c for c in item_codes(sec, "--is-ancestor") if "--is-ancestor" in c), "")
        find = next((c for c in item_codes(o.section("Session commit prerequisite"), "READ side")
                     if c.startswith("find ")), "")
        if not (where and test and find):
            raise cmdtext.TextNotFound("Step 1 names no token directory, scan or ancestor test")
        # The repo hash and branch, as Step 2's own lines compute them.
        lines = [l for l in cmdtext.block(self.step("Step 2"), lang="bash").split("\n")
                 if re.match(r"^(REPO_ROOT|REPO_HASH|BRANCH)=", l)]
        self.captured("\n".join(lines), self.label("Step 1 Bash repo hash"), "Step 1: repo hash and branch",
                      ("REPO_ROOT", "REPO_HASH", "BRANCH"))
        v = o.values
        tdir = where.group(1).replace("<repo-hash>", v.get("REPO_HASH", "")).rstrip("/")
        cmd = (find.replace("<repo-hash-dir>", tdir)
               .replace("<branch-encoded>", v.get("BRANCH", "").replace("/", "__")))
        c = self.check(o.run(cmd, "Step 1: the push-gate token candidates", self.label("Step 1 Bash token scan")))
        cands = [l.strip() for l in (c.response.get("stdout") or "").split("\n") if l.strip()] if c.ok else []
        ok = ""
        for k, path in enumerate(cands):
            r = self.check(o.s.read(path, label=self.label(f"Step 1 Read token {k}"),
                                    deviation=self.devs.at(self.label(f"Step 1 Read token {k}"))))
            try:
                sha = json.loads(agents.peek(self.rp, "main", path)).get("commit_sha") if r.ok else ""
            except ValueError:
                sha = ""  # "Malformed/unparseable candidates are skipped"
            if not sha:
                continue
            t = self.check(o.run(test.replace("<commit_sha>", sha), "Step 1: is the token's commit an ancestor of HEAD",
                                 self.label(f"Step 1 Bash ancestor {k}")))
            if t.ok:
                ok = path
                break
        closedrv.fact(self.rp, "push step 1", {"candidates": [self.rp.norm_text(p) for p in cands],
                                               "accepted": self.rp.norm_text(ok)})
        if not ok:
            self.say_stop(f"/push aborted: no push-gate token under {tdir} names an ancestor of HEAD. "
                          "Run /commit (in any session) first.")
        return bool(ok)

    # ------------------------------------------------------------ Step 2
    def step2(self) -> bool:
        block = cmdtext.block(self.step("Step 2"), lang="bash")
        names = tuple(dict.fromkeys(_ASSIGN_RE.findall(block)))
        self.captured(block, self.label("Step 2 Bash snapshot"), "Step 2: pre-push snapshot", names)
        self.rp.rand(self.o.values.get("REQUEST_ID"))
        if not self.o.values.get("SESSION_ID"):
            m = re.search(r'abort immediately with:\s*"([^"]+)"', self.step("Step 2"))
            self.say_stop(m.group(1) if m else "Cannot dispatch the push-analyst: no session id")
            return False
        return True

    # ------------------------------------------------------------ Step 3 and the analyst
    def prompt(self) -> str:
        o = self.o
        fence = next(b.text for b in cmdtext.blocks(self.step("Step 3")) if "REQUEST_ID=" in b.text)
        left: list = []
        prompt = o.bind(o.instantiate(fence, None), unbound=left)
        if left:
            raise cmdtext.TextNotFound(f"Step 3 prompt: unbound placeholders {sorted(set(left))}")
        return prompt.rstrip("\n")

    def step3(self) -> None:
        o = self.o
        lab = self.label(f"Step 3 Agent({self.role()})")
        prompt = self.prompt()
        analyst = Analyst(self, prompt)
        player = agents.Player(o.tree, prompt, agents.Act(work=analyst.work, summary="pre-push analysis"),
                               role=self.role())
        analyst.player = player
        d = o.s.dispatch(self.role(), prompt, description="pre-push analysis", body=player.body,
                         result=analyst.final, label=lab, deviation=self.devs.at(lab))
        self.check(d)
        if d.stop is not None and d.stop.still_blocked:
            raise mergedrv.Paused(mergedrv.refusal(self.rp, lab + " stop"))
        text = ((d.response.get("content") or [{}])[0].get("text") or "") if d.response else ""
        m = re.findall(r"^push-analyst grant written: (\S+)$", text, re.M)
        self.printed = m[-1] if m else ""
        closedrv.fact(self.rp, "push-analyst", {"verdict": analyst.verdict, "risks": analyst.risks,
                                                "commits": analyst.commits, "grant_writes": analyst.writes,
                                                "printed": self.rp.norm_text(self.printed),
                                                "paused": analyst.paused})

    # ------------------------------------------------------------ Step 5
    def step5(self):
        o = self.o
        cmd = form(cmdtext.block(self.step("Step 5"), lang="bash"), self.auto)
        c = self.check(o.run(o.shell_bind(o.bind(cmd)), "Step 5: execute-push.py validates, spends the grant and "
                             "execs push.sh", self.label("Step 5 Bash execute-push")))
        out = (c.response.get("stdout") or "") + (c.response.get("stderr") or "") if c.ok else (c.error or "")
        rc = 0 if c.ok else int((re.match(r"Exit code (\d+)", c.error or "") or [0, -1])[1])
        st = origin_state(self.rp)
        tip = _origin_tip(st)
        # The terminal: the bare origin's branch equal to HEAD, moved there by this /push.
        pushed = c.ok and tip == st["head"] and _origin_tip(self.before) != tip
        closedrv.fact(self.rp, "push", {"rc": rc, "pushed": pushed, "origin_equals_head": tip == st["head"],
                                        "toy": st, "left": leftovers(self.rp), "output": self.rp.norm_text(out)[-1500:]})
        return c, rc, pushed, out

    # ------------------------------------------------------------ the turn
    def run(self) -> str:
        try:
            return self.turn()
        except mergedrv.Paused as p:
            self.say_stop(f"PAUSE: {p}. Pausing per the Subagent Hook Discipline: the refused operation is not "
                          "retried, wrapped or bypassed; it needs a human ruling.")
            closedrv.fact(self.rp, "push paused", str(p))
            return self.outcome

    def turn(self) -> str:
        self.before = origin_state(self.rp)
        self.o.slash(self.args, label=self.label("typed"))
        self.step0()
        if not self.step1():
            return self.outcome
        if not self.step2():
            return self.outcome
        self.step3()
        # Step 4: execute-push.py is the grant's validator and consumer; the orchestrator reads nothing.
        c, rc, pushed, out = self.step5()
        v = self.o.values
        if pushed:
            text = f"Pushed {v.get('BRANCH')} to {v.get('RESOLVED_REMOTE')}.\n" + "\n".join(
                l for l in out.split("\n") if l.strip().startswith(("•", "Remote URL")))
        else:
            meaning = {1: "detached HEAD, missing remote, a refused grant or sentinel, or a failed push",
                       2: "a blocked option or an infrastructure failure",
                       3: "no push-gate token names an ancestor of HEAD: run /commit (in any session) first"}
            text = f"/push did not push (exit {rc}: {meaning.get(rc, 'see the output')}).\n{out[-800:]}"
        self.say_stop(text)
        return self.outcome


class Analyst(mergedrv.Analyst):
    """The push-analyst's work, from its agent file's Workflow phases, in order."""

    def __init__(self, run: PushRun, prompt: str):
        super().__init__(run, prompt)
        self.empty = False
        self.summary = ""

    def raise_to(self, level: str, why: str) -> None:
        self.risks.append(why)
        if _LEVELS.index(level) > _LEVELS.index(self.verdict):
            self.verdict = level

    def phases(self):
        for title, sec in mergedrv._phases(self.text):
            fences = cmdtext.blocks(sec)
            if any(b.lang == "json" for b in fences):
                self.write_grant(title, sec, fences)
            elif self.empty:
                continue  # "If the range is empty ... write an `approved` grant ... and exit"
            elif "Write (append) to" in sec:
                self.audit(title, sec, fences)
            elif any("RANGE=" in b.text for b in fences):
                self.range_phase(title, sec, fences)
            elif any("--name-only" in b.text for b in fences):
                self.sensitive(title, sec, fences)
            elif any("AHEAD=" in b.text for b in fences):
                self.divergence(title, sec, fences)
            elif re.search(r"^If BRANCH is", sec, re.M):
                self.protection(sec)
            else:
                for k, b in enumerate(f for f in fences if f.lang == "bash"):
                    self.bash(b.text, title.split(":")[0] + (f" #{k + 1}" if k else ""), title)
        return None

    def range_phase(self, title: str, sec: str, fences) -> None:
        """Phase 1: the git root, the range, the commits in it."""
        ph = title.split(":")[0]
        for k, b in enumerate(f for f in fences if f.lang == "bash"):
            names = tuple(dict.fromkeys(_ASSIGN_RE.findall(b.text)))
            c, out = self.bash(b.text, ph + (f" #{k + 1}" if k else ""), title, names)
            if re.search(r"git log --oneline", b.text):
                self.commits = len([l for l in (c.response.get("stdout") or "").split("\n") if l.strip()]) if c.ok else 0
        if self.commits == 0:
            m = re.search(r'analysis_summary\s*"([^"]+)"', sec)
            self.empty, self.summary = True, m.group(1) if m else "Nothing to push."

    def sensitive(self, title: str, sec: str, fences) -> None:
        """Phase 2: the range's file names against the patterns the text lists; a match read with git show."""
        ph = title.split(":")[0]
        b = next(f for f in fences if "--name-only" in f.text)
        c, _ = self.bash(b.text, ph, title)
        files = [l.strip() for l in (c.response.get("stdout") or "").split("\n") if l.strip()] if c.ok else []
        after = sec.split("Flag any file", 1)[-1]
        pats = re.findall(r"^\s*-\s+`([^`]+)`", after, re.M)
        risk = re.search(r"`RISK:\s*([^`]*)<filename>`", sec)
        for f in files:
            if not any(fnmatch.fnmatch(os.path.basename(f).lower(), p.lower()) for p in pats):
                continue
            why = (risk.group(1) if risk else "sensitive file pattern in commits-to-push: ") + f
            s, _ = self.bash(f"git show HEAD:{shlex.quote(f)}", f"{ph} show {f}", "Credential content check")
            body = (s.response.get("stdout") or "") if s.ok else ""
            cred = re.search(r"(?i)(?:key|secret|password|credential|token)\w*\s*[:=]\s*[\"']?[A-Za-z0-9+/]{20,}=*", body)
            self.raise_to("blocked" if cred else "warn", why)

    def protection(self, sec: str) -> None:
        """Phase 3: the branch names the text protects."""
        line = next(l for l in sec.split("\n") if l.startswith("If BRANCH is"))
        names = re.findall(r"`([^`]+)`", line)
        if self.values.get("BRANCH") in names:
            m = re.search(r'Add RISK:\s*"([^"]+)"', sec)
            self.raise_to("warn", (m.group(1) if m else "Direct push to protected branch `<BRANCH>`")
                          .replace("<BRANCH>", self.values["BRANCH"]))

    def divergence(self, title: str, sec: str, fences) -> None:
        """Phase 4: ahead and behind the remote tracking ref."""
        b = next(f for f in fences if "AHEAD=" in f.text)
        self.bash(b.text, title.split(":")[0], title, ("AHEAD", "BEHIND"))
        behind = int(self.values.get("BEHIND") or 0)
        if behind > 0:
            m = re.search(r'add RISK "([^"]+)"', sec)
            self.raise_to("warn", (m.group(1) if m else "Remote has ${BEHIND} commits not in local")
                          .replace("${BEHIND}", str(behind)))

    def audit(self, title: str, sec: str, fences) -> None:
        """The base text's audit log: its directory, then the entry Written with the Write tool."""
        for k, b in enumerate(f for f in fences if f.lang == "bash"):
            self.bash(b.text, f"{title.split(':')[0]} #{k + 1}", title)
        m = re.search(r"Write \(append\) to `([^`]+)`", sec)
        line = next((b.text.strip() for b in fences if not b.lang and "<" in b.text), "")
        if not m or not line:
            return
        v = self.values
        line = (self.fill(line).replace("<ISO-8601 UTC>", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
                .replace("<PRE_HEAD[:8]>", v.get("PRE_HEAD", "")[:8]).replace("<verdict>", self.verdict)
                .replace("<count>", str(len(self.risks))))
        path, role = self.fill(m.group(1)), self.sub.role
        if os.path.exists(path):  # append: Read, then Edit (the harness refuses a wholesale Write over a file)
            self.checked(self.sub.read(path, label=f"{role} Read audit log"))
            old = agents.peek(self.rp, role, path)
            a, b = agents.edit_span(old, old + line + "\n")
            self.checked(self.sub.edit(path, a, b, label=f"{role} Edit audit log"))
        else:
            self.checked(self.sub.write(path, line + "\n", label=f"{role} Write audit log"))

    def grant_from(self, tpl: dict, expires: str) -> dict:
        v = self.values
        doc = {}
        for k, val in tpl.items():
            if isinstance(val, list):
                doc[k] = list(self.risks)
                continue
            m = re.fullmatch(r"<([A-Z_]+)>", str(val))
            alts = re.fullmatch(r"<(\w+(?:\|\w+)+)>", str(val))
            if m and m.group(1) in v:
                doc[k] = v[m.group(1)]
            elif alts:
                if self.verdict not in alts.group(1).split("|"):
                    raise agents.PlayError(f"grant template field {k}: verdict {self.verdict!r} not in {val!r}")
                doc[k] = self.verdict
            elif "summary" in str(val):
                doc[k] = self.summary or (
                    f"{self.commits} commit(s) on {v.get('BRANCH')} ahead of {v.get('REMOTE_NAME')}"
                    + ("; " + "; ".join(self.risks) if self.risks else "; no risks found") + ".")
            elif "ISO-8601" in str(val):
                doc[k] = expires
            else:
                raise agents.PlayError(f"grant template field {k}: no value for {val!r}")
        return doc


# ---------------------------------------------------------------- the scenario

def landed_commit(rp, after: str):
    """The cycle, its /close and its /commit, each by its own driver; returns the /commit run and the
    session it ran in."""
    from . import commit as commitdrv
    if after == "do":
        from . import do as dodrv
        turn = dodrv.DoTurn(rp)
        tid = turn.run()
        s = turn.o.s
        cr = closedrv.CloseRun(rp, s, tid, do_report=turn.report_rel, producer=closedrv.DoProducer(turn))
        cr.run()
        producer = cr.producer
    else:
        producer, tid, s, _ = closedrv.dev_cycle(rp, after)
        closedrv.CloseRun(rp, s, tid, producer=producer).run()
    cm = commitdrv.CommitRun(rp, s, tid, producer=producer)
    cm.run()
    return cm, s


def owner_commit(rp) -> None:
    """Before the session, in the owner's terminal (no hook sees it): one commit on the toy's branch, no
    /commit, so no push-gate token."""
    p = rp.layout.project
    with rp.acting("owner"):
        mergedrv._write(p, "README.md", mergedrv.README_MAIN)
        mergedrv._owner_git(p, "commit", "-qam", "docs: say what toy does", date="2026-01-01T00:02:00+0000")


def run(rp) -> None:
    after = rp.args.get("after", "do")
    if after not in ("do", "dev", "dev-command", "none"):
        raise ValueError(f"after must be do, dev, dev-command or none, not {after!r}")
    session_kind = rp.args.get("session", "same")
    state_mode = rp.args.get("statedir", "respelled")
    if state_mode not in ("respelled", "strict"):
        raise ValueError(f"statedir must be respelled or strict, not {state_mode!r}")
    typed = " ".join(x for x in (rp.args.get("remote", ""), "--auto" if rp.args.get("auto") else "") if x)
    rp.pipeline = (("push/no-token" if after == "none" else f"{after}+close+commit+push")
                   + ("/later" if session_kind == "later" and after != "none" else "")
                   + ("/statedir-strict" if state_mode == "strict" else ""))
    if after == "none":
        owner_commit(rp)
        s = rp.session()
        closedrv.fact(rp, "before /push", {"owner commit": True, "toy": origin_state(rp), "left": leftovers(rp)})
    else:
        cm, s = landed_commit(rp, after)
        closedrv.fact(rp, "before /push", {"commit_status": cm.status.get("commit_status"),
                                           "landed": [(rp.norm_text(r), sha) for r, sha in cm.landed],
                                           "toy": origin_state(rp), "left": leftovers(rp)})
    session = rp.later_session(s) if session_kind == "later" else s
    PushRun(rp, session, args=typed, state_mode=state_mode).run()
