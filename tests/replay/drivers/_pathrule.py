"""P1b acceptance 9 (path rule): the hook-state files a writer and its reader must find in one directory,
replayed at the hooks that read them, in the kit of the tree under test (`--driver _pathrule`).

Not a pipeline: the artifact check (tests/artifact_graph/runtime.py `drivers()`) leaves this module out, as
it leaves out every module whose name starts with `_`. Its calls are PreToolUse probes that are not
performed, and its strace wrapping of the hooks cannot run under the check's own strace.

Cases (`--arg case=...`):

consent    The main agent's calls each /do consent reader gates, before and after the owner types `/do <task>`
           (hooks/prompt-workflow.py writes the consent flag at that UserPromptSubmit; after it the main agent
           passes the hook's checklist to its first TodoWrite, as commands/do.md's hook asks): a `git commit`
           (Bash: the privilege guard and pretool-bash-safety.sh, with the readers every tool reaches: the
           orchestrator gate, the background-task block, the /do subagent block, the read-size guard, the
           subagent enforcement), a `git checkout -b` (pretool-block-branch-pr-worktree.py), an Agent(qa)
           dispatch (pretool-aggregate-check.py's QA branch, pretool-subagent-enforce.py,
           pretool-do-block-subagents.py), a Read of a file over 600 lines (pretool-read-size-guard.py), an
           EnterWorktree (pretool-block-enterworktree.sh) and a Write (pretool-write-guard.sh).
pushgrant  A main-agent `git push -u origin <branch>` with CLAUDE_PUSH_COMMAND_ACTIVE=1 in the hooks'
           environment, before and after the push grant hooks/push.sh writes: its Step 8.5 block, taken from
           the kit's hooks/push.sh and run as is (after the helper push.sh sources at its top) with the
           session's id as CLAUDE_SESSION_ID and the branch and remote push.sh resolves for the toy.
preflight  /commit's Step 6 and Step 7 changelog-analyst dispatches through the Agent PreToolUse hooks. The
           harness home holds a singular /dev cycle's dev report of a task (no gitignore_waiver, one
           files_created path the harness's .gitignore matches, under tests/generated/) and its close-report,
           as that cycle and its /close left them. The owner types `/commit <task>` (the user-intent sentinel);
           the main agent runs Step 5 as the text spells its pieces: the repository plan
           (resolve-commit-repos.py, the harness home as control root and supported repository), the
           dispatch-snapshot manifest Written at the state dir Bash resolves, and the text's grant-writer
           block (row 7's M3 respelling where the text activates a venv): the kit's write-commit-grant.py
           writes the grant where it writes it and prints its path. Then, for each text (`texts=own` or
           `texts=own,<path>`: another tree's commands/commit.md, a path under the sandbox root, for
           acceptance 17's in-flight form), each step (6: DRYRUN=true, QA_APPROVED_FILES empty; 7: DRYRUN=false,
           the plan's files) and with and without a grant line, the dispatch built from that text's Step 7
           template (its obligation instantiated for the task; its plan roots, where the text declares them,
           are the plan's repo_root values in order), with the dev report named on a line of its
           own (`Read the dev report yourself and classify files for staging: docs/dev/dev-report-<task>.json`,
           hooks/tests/test_gitignore_preflight_close_contract.py `commit_step7_prompt`) and, in the grant
           variant, `Commit grant: <the path the writer printed>` on another.
           Last, a control: this tree's Step 7 dispatch without its obligation block and without a grant line.
           Run once with CLAUDE_STATE_DIR set (the replay's default) and once with `--env CLAUDE_STATE_DIR=`
           (unset; mode ns only).

Each tool call is a PreToolUse probe: the tool_use is appended to the transcript, its PreToolUse hooks run
and their verdicts are recorded, and the call is not performed (an error tool_result where a hook refused it,
else a result saying the replay does not perform it); no PostToolUse follows. Step 5's calls in preflight are
performed (tool calls of the CLI model). No deviation is declared: what a hook refuses is the evidence.

The events of consent and pushgrant run their hooks under `strace -f` (each registered command prefixed,
its behaviour unchanged); facts.json lists, per hook, the opens, stats and removals of a path whose name
holds the case's needle (claude-orchestrator-consent, claude-push-grant), with each syscall's result.

Facts (facts.json): per event, each hook's exit code and the first line of its output (stderr, else stdout).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from contextlib import contextmanager

from .. import cmdtext, hookrun
from ..pipeline import Orchestrator, utc_now
from ..replay import MODEL
from . import close as closedrv
from .commit import RESPELLINGS as COMMIT_RESPELLINGS

PIPELINE = "pathrule"
TASK = "make toy.add raise TypeError naming the offending argument when an argument is not a number"
STRACE = ["strace", "-f", "-qq", "-e",
          "trace=open,openat,stat,lstat,newfstatat,statx,access,faccessat,faccessat2,unlink,unlinkat,rename,renameat2"]
# syscall, its first path, its result ("= 0", "= 3", "= -1 ENOENT"): the last ") = " of the line (a stat's
# struct holds "=" signs of its own)
_SYSCALL_RE = re.compile(r'^(?:\d+\s+)?(\w+)\((?:AT_FDCWD, )?"([^"]*)".*\)\s+=\s+(-?\d+(?: [A-Z]+)?)')


def first_line(h: dict) -> str:
    for stream in (h.get("stderr") or "", h.get("stdout") or ""):
        for line in stream.splitlines():
            if line.strip():
                return line.strip()[:220]
    return ""


def verdicts(rp, ev) -> list:
    return [{"hook": h["hook"], "rc": h["rc"], "first": rp.norm_text(first_line(h))} for h in ev.hooks]


@contextmanager
def traced(rp, events, needle: str, env: dict | None = None):
    """Inside: the hooks of `events` run under strace (and with `env` added to the hooks' environment);
    after: rec["probes"] = {hook: [syscall path = result, ...]} for paths whose name holds `needle`."""
    rec: dict = {"probes": {}}
    orig_settings, orig_env = rp.settings, rp.env
    settings = json.loads(json.dumps(orig_settings))
    out = os.path.join(rp.layout.out, "strace")
    os.makedirs(out, exist_ok=True)
    wrapped, files = {}, {}
    for event in events:
        for grp in (settings.get("hooks") or {}).get(event, []):
            for h in grp.get("hooks", []):
                cmd = h.get("command")
                if h.get("type", "command") != "command" or not cmd:
                    continue
                if cmd not in wrapped:
                    f = os.path.join(out, f"{len(os.listdir(out)) + len(files):04d}.txt")
                    files[f] = hookrun.hook_name(cmd)
                    wrapped[cmd] = " ".join(STRACE) + f" -o {shlex.quote(f)} " + cmd
                h["command"] = wrapped[cmd]
    rp.settings = settings
    if env:
        rp.env = dict(orig_env, **env)
    try:
        yield rec
    finally:
        rp.settings, rp.env = orig_settings, orig_env
        with rp.acting("driver"):
            for f, hook in files.items():
                hits = []
                try:
                    with open(f, errors="replace") as fh:
                        for line in fh:
                            m = _SYSCALL_RE.match(line.strip())
                            if m and needle in m.group(2):
                                hit = rp.norm_text(f"{m.group(1)} {m.group(2)} = {m.group(3)}")
                                if hit not in hits:
                                    hits.append(hit)
                    os.unlink(f)
                except OSError:
                    pass
                if hits:
                    rec["probes"][hook] = hits


def probe(rp, s, name: str, tinput: dict, label: str, needle: str = "", env: dict | None = None):
    """One PreToolUse probe of a main-agent call (module docstring); its verdicts kept as a fact."""
    rp.step("tool", label, {"name": name, "input": tinput})
    tid = rp.new_tool_id()
    s.append({"type": "assistant", "message": {"role": "assistant", "model": MODEL, "content": [
        {"type": "tool_use", "id": tid, "name": name, "input": tinput}]}})
    payload = {"tool_name": name, "tool_input": tinput, "tool_use_id": tid}
    if needle:
        with traced(rp, ("PreToolUse",), needle, env) as t:
            ev = s.fire("PreToolUse", label, payload)
        probes = t["probes"]
    else:
        orig = rp.env
        rp.env = dict(orig, **(env or {}))
        try:
            ev = s.fire("PreToolUse", label, payload)
        finally:
            rp.env = orig
        probes = {}
    blocked = rp.settle(ev, label)
    if blocked:
        text = "\n".join(hookrun.refusal(b) for b in ev.blocks)
        block = {"type": "tool_result", "tool_use_id": tid, "content": f"PreToolUse:{name} hook error: {text}",
                 "is_error": True}
    else:
        block = {"type": "tool_result", "tool_use_id": tid,
                 "content": "(PreToolUse probe: the replay does not perform this call)"}
    s.append({"type": "user", "message": {"role": "user", "content": [block]}})
    closedrv.fact(rp, label, {"event": "PreToolUse", "tool": name, "blocked": blocked,
                              "hooks": verdicts(rp, ev), "probes": probes})
    return ev


# ---------------------------------------------------------------- consent

CONSENT = "claude-orchestrator-consent"


def consent(rp) -> None:
    s = rp.session()
    p = rp.layout.project
    calls = [
        ("Bash", {"command": 'git commit -m "toy: add rejects non-numbers"', "description": "Commit the change"},
         "git commit"),
        ("Agent", {"description": "qa", "prompt": "Review toy/__init__.py against the request.",
                   "subagent_type": "qa", "run_in_background": False}, "Agent(qa)"),
        ("Bash", {"command": "git checkout -b probe-branch", "description": "Create a branch"},
         "git checkout -b"),
        ("Read", {"file_path": os.path.join(rp.layout.harness, "agents", "changelog-analyst.md")},
         "Read (over 600 lines)"),
        ("EnterWorktree", {}, "EnterWorktree"),
        ("Write", {"file_path": os.path.join(p, "toy", "notes.md"), "content": "# notes\n"}, "Write"),
    ]
    for phase in ("before /do", "after /do"):
        if phase == "after /do":
            o = Orchestrator(rp, "do", session=s)
            with traced(rp, ("UserPromptSubmit",), CONSENT) as t:
                ev = o.slash(TASK, label="/do")
            closedrv.fact(rp, "/do", {"event": "UserPromptSubmit", "hooks": verdicts(rp, ev), "probes": t["probes"]})
            o.todo_start(label="/do TodoWrite canonical list")  # the checklist the hook hands the main agent
        for name, tinput, short in calls:
            probe(rp, s, name, tinput, f"{phase}: {short}", CONSENT)
    s.end()


# ---------------------------------------------------------------- pushgrant

PUSH_GRANT = "claude-push-grant"


def _grants(rp) -> list:
    found = []
    with rp.acting("driver"):
        for root in (rp.layout.state, "/tmp"):
            if os.path.isdir(root):
                found += [rp.norm_text(os.path.join(root, f)) for f in sorted(os.listdir(root)) if PUSH_GRANT in f]
    return found


def pushgrant(rp) -> None:
    s = rp.session()
    lay = rp.layout
    branch = subprocess.run(["git", "-C", lay.project, "branch", "--show-current"], capture_output=True,
                            text=True).stdout.strip()
    env = {"CLAUDE_PUSH_COMMAND_ACTIVE": "1"}
    cmd = {"command": f"git push -u origin {branch}", "description": "Push to origin"}
    probe(rp, s, "Bash", cmd, "push before any grant", PUSH_GRANT, env)
    with rp.acting("driver"):
        with open(os.path.join(lay.harness, "hooks", "push.sh"), encoding="utf-8") as fh:
            text = fh.read()
    block = text[text.index("# Step 8.5"):text.index("# Step 8.6")]
    script = (". ~/.claude/hooks/lib/harness_state_dir.sh\n"
              f"BRANCH={shlex.quote(branch)}\nREMOTE=origin\n" + block + 'printf "%s\\n" "$GRANT_PATH"\n')
    rp.step("script", "push.sh Step 8.5", {})
    with rp.acting("hooks/push.sh"):
        r = subprocess.run(["bash", "-c", script], cwd=lay.project, capture_output=True, text=True,
                           env=dict(rp.bash_env, CLAUDE_SESSION_ID=s.sid))
    closedrv.fact(rp, "push.sh Step 8.5", {"rc": r.returncode, "printed": rp.norm_text(r.stdout.strip()),
                                           "stderr": rp.norm_text(r.stderr.strip())[-400:],
                                           "grants on disk": _grants(rp)})
    probe(rp, s, "Bash", cmd, "push after push.sh's grant", PUSH_GRANT, env)
    closedrv.fact(rp, "grants left", _grants(rp))
    s.end()


# ---------------------------------------------------------------- preflight

def _report(tid: str, created: str) -> dict:
    return {"report_version": 1, "task_id": tid, "source": "dev",
            "dev": {"status": "completed", "summary": "A generated test of the path rule.",
                    "files_modified": [], "files_created": [created]}}


def _analyst_prompt(o, text: str, tid: str, plan: dict, dryrun: bool, approved: dict, report_rel: str,
                    grant: str) -> str:
    """The Step 7 template of `text` (drivers/commit.py analyst_prompt's binding), the dev report line and,
    given, the grant line."""
    tpl = next(b.text for b in cmdtext.blocks(cmdtext.section(text, "Step 7")) if "CONTROL_ROOT=<" in b.text)
    tpl = re.sub(r'<"([^"]*)" when BULK=false, else [^>]*>',
                 lambda m: json.dumps(m.group(1).replace("$TASK_ID", tid)), tpl)
    # The obligation's plan roots, where the text declares them: the plan's repo_root values in order.
    roots = [e["repo_root"] for e in plan.get("repositories") or []]
    tpl = re.sub(r"<the JSON array of REPOSITORY_PLAN\.repositories\[\]\.repo_root\b[^>]*>",
                 lambda m: json.dumps(roots), tpl)
    root = plan.get("control_root", "")
    values = {"CONTROL_ROOT": root, "NESTED_REPO": root, "REPOSITORY_PLAN": json.dumps(plan),
              "ARTIFACT_CHAIN": "", "ATTRIBUTION_LOG": json.dumps({"results": [], "no_events": [],
                                                                   "discarded_lines": []}),
              "TASK_ID": tid, "BULK": "false", "DRYRUN": "true" if dryrun else "false", "FORCE": "false",
              "QA_APPROVED_FILES": json.dumps(approved) if approved else ""}
    lines = []
    for line in tpl.split("\n"):
        m = re.match(r"^([A-Z_]+)=<.*>$", line)
        lines.append(f"{m.group(1)}={values[m.group(1)]}" if m and m.group(1) in values else line)
    prompt = o.instantiate("\n".join(lines), tid)
    prompt = o.bind(prompt, [(r"^(?:TASK_ID|task-id)$", tid)])
    prompt += f"\nRead the dev report yourself and classify files for staging: {report_rel}\n"
    if grant:
        prompt += f"Commit grant: {grant}\n"
    return prompt


def preflight(rp) -> None:
    lay = rp.layout
    h = lay.harness
    tid = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    rp.task(tid)
    report_rel, created = f"docs/dev/dev-report-{tid}.json", f"tests/generated/{tid}/test_path_rule.py"
    with rp.acting("driver"):  # the harness home as the task's singular /dev cycle and its /close left it
        for rel, body in ((report_rel, json.dumps(_report(tid, created), indent=2) + "\n"),
                          (f"docs/dev/close-report-{tid}.md", f"# Close report {tid}\n\nCLOSE: YES\n"),
                          (created, "def test_path_rule():\n    assert True\n")):
            os.makedirs(os.path.dirname(os.path.join(h, rel)), exist_ok=True)
            with open(os.path.join(h, rel), "w") as fh:
                fh.write(body)
        ignored = subprocess.run(["git", "check-ignore", "--no-index", "-v", "--", created], cwd=h,
                                 capture_output=True, text=True).stdout.strip()
    closedrv.fact(rp, "harness home", {"task": tid, "report": report_rel, "files_created": [created],
                                       "check-ignore": ignored,
                                       "CLAUDE_STATE_DIR": rp.env.get("CLAUDE_STATE_DIR", "(unset)")})
    s = rp.session()
    o = Orchestrator(rp, "commit", session=s, respellings=COMMIT_RESPELLINGS)
    ev = o.slash(tid, label="/commit")
    closedrv.fact(rp, "/commit", {"event": "UserPromptSubmit", "hooks": verdicts(rp, ev)})
    # Step 5: the plan, the manifest, the grant.
    cmd = ("python3 ~/.claude/scripts/resolve-commit-repos.py --task-id {t} --control-root ~/.claude "
           "--report ~/.claude/{r} --supported-repo ~/.claude").format(t=tid, r=report_rel)
    c = o.run(cmd, "Step 5: the repository plan", "/commit Step 5 Bash resolve-commit-repos.py")
    plan = json.loads(c.response.get("stdout", "")) if c.ok else {}
    c = o.run(". ~/.claude/hooks/lib/harness_state_dir.sh\nharness_state_dir\n"
              'echo "${CLAUDE_CODE_SESSION_ID:-$CLAUDE_SESSION_ID}"\n'
              f"git -C {shlex.quote(h)} status --porcelain=v1",
              "State dir, session id and status per plan entry", "/commit Step 5 Bash manifest inputs")
    out = (c.response.get("stdout") or "").split("\n") if c.ok else []
    state, sid = (out + ["", ""])[:2]
    doc = {"session_id": sid, "task_id": tid, "dispatched_at": utc_now(), "repository_plan": plan,
           "artifact_chain": None, "files_at_dispatch": {h: [l[3:] for l in out[2:] if l.strip()]}}
    s.write(os.path.join(state, f"claude-commit-manifest-{sid}.json"), json.dumps(doc, indent=2) + "\n",
            label="/commit Step 5 Write manifest")
    writer = next(b.text for b in cmdtext.blocks(o.section("Step 5"), None, "bash")
                  if "write-commit-grant.py" in b.text and "PLANNED_REPO_ROOT" in b.text)
    o.values.update(TASK_ID=tid, PLANNED_REPO_ROOT=(plan.get("repositories") or [{}])[0].get("repo_root", h))
    c = o.run_text(writer, "/commit Step 5 Bash mint 0", "Mint the repository's commit grant")
    grant = (c.response.get("stdout") or "").strip().split("\n")[-1] if c.ok else ""
    closedrv.fact(rp, "Step 5", {"plan admits": [e.get("repo_root") for e in plan.get("repositories") or []],
                                 "manifest": rp.norm_text(os.path.join(state, f"claude-commit-manifest-{sid}.json")),
                                 "mint ok": c.ok, "grant": rp.norm_text(grant),
                                 "mint error": rp.norm_text(c.error)[:400]})
    texts = [("own", o.text)]
    for extra in [t for t in rp.args.get("texts", "own").split(",") if t and t != "own"]:
        with rp.acting("driver"):
            with open(os.path.join(lay.sb, extra), encoding="utf-8") as fh:
                texts.append((extra, fh.read()))
    files = {h: list((plan.get("repositories") or [{}])[0].get("owned_paths") or [])}
    for name, text in texts:
        for step in (6, 7):
            for with_grant in (False, True):
                label = f"text {name}: Step {step} Agent(changelog-analyst) {'with' if with_grant else 'without'} grant line"
                prompt = _analyst_prompt(o, text, tid, plan, step == 6, files if step == 7 else {}, report_rel,
                                         grant if with_grant else "")
                probe(rp, s, "Agent", {"description": "changelog-analyst", "prompt": prompt,
                                       "subagent_type": "changelog-analyst", "run_in_background": False}, label)
    # Control: the same Step 7 dispatch of this tree's text with its obligation block removed (the report is
    # found and its files_created path is ignored, so a preflight that admits only by the obligation refuses it).
    prompt = re.sub(r'<obligation v="1">.*?</obligation>\n?', "",
                    _analyst_prompt(o, o.text, tid, plan, False, files, report_rel, ""), flags=re.S)
    probe(rp, s, "Agent", {"description": "changelog-analyst", "prompt": prompt, "subagent_type": "changelog-analyst",
                           "run_in_background": False}, "control: text own, Step 7 without its obligation block")
    s.end()


def run(rp) -> None:
    case = rp.args.get("case", "consent")
    fn = {"consent": consent, "pushgrant": pushgrant, "preflight": preflight}.get(case)
    if fn is None:
        raise ValueError(f"case must be consent, pushgrant or preflight, not {case!r}")
    state = "unset" if "CLAUDE_STATE_DIR" not in rp.env else "set"
    rp.pipeline = f"pathrule/{case}/state-{state}"
    fn(rp)
