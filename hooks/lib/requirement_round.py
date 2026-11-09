"""The requirement round (D28, D29, D32): BA, or panel QA for a BA panel's round 1, writes the owner questions;
the main agent asks them verbatim with one AskUserQuestion; the PostToolUse AskUserQuestion hook (``handle``) is
the one writer of the owner's answers. ``asked`` is the one "asked" predicate (close_rating's too): asked, never
answered (D9b), so Skip, AFK, a denial or an error result count and record nothing. The checks G1 (``ask_first``),
G2 (``check_round``, ``stand_in``, ``check_analysis``) and the Stop gate (``ends_with_question``) decide by live here."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import time
from pathlib import Path

ASK_COMMANDS = frozenset({"spec", "dev", "redev", "dev-command"})
DIMENSIONS = ("acceptance", "edge_cases", "intent", "scope")
SOURCE_RE = re.compile(r"^(requirement-round|producer-question):([A-Za-z0-9][A-Za-z0-9_-]{2,80}):(r[1-9][0-9]*|ba|dev)$")
ROUND = "docs/dev/requirement-round-{task}-r{n}.json"
PANEL = "docs/dev/ba-panel-{task}-r1.json"
ANSWERS = "docs/dev/requirement-answers-{task}-r{n}.json"
QUESTION = "docs/dev/producer-question-{task}-{role}.json"
PRODUCER_ANSWER = "docs/dev/producer-answer-{task}-{role}-{q8}.json"
# Written by the AskUserQuestion hook alone; the write gate refuses every agent's write to them (R6).
HOOK_OWNED = re.compile(r"(^|/)docs/dev/(requirement-answers|producer-answer)-[^/]+\.json$")
_ROUND_FILE = re.compile(r"(?:^|/)docs/dev/(?:requirement-round-(.+)-r([1-9][0-9]*)|ba-panel-(.+)-r(1))\.json$")
_PRE_ASK = re.compile(r"(?:^|/)docs/dev/(?:requirement-round-(.+)-r1\.json|ba-panel-(.+)-(?:r1\.json|[ABC]\.md))$")
# The D18 lint: it catches code tokens only (a backtick, a path with an extension, "()", "::"), never a technical
# choice written in plain words.
_CODE_TOKEN = re.compile(r"`|::|\(\)|(?:[\w.-]+/)+[\w-]+\.\w+|\b[\w-]+\.(?:py|js|ts|tsx|jsx|json|md|sh|ya?ml|toml"
                         r"|txt|html|css|go|rs|java|rb|sql|ini|cfg)\b")


def _lib(name: str):
    return importlib.import_module(f".{name}" if __package__ else name, __package__ or None)


def task_of(task_id) -> str | None:
    """The id round, answer and question files are named with (obligation.canonical_task_id)."""
    return _lib("obligation").canonical_task_id(task_id)


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _norm(text) -> str:
    return " ".join(str(text).split()).casefold()


def _load(path) -> dict | None:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return doc if isinstance(doc, dict) else None


def ask_view(doc: dict) -> list:
    """The file's questions as AskUserQuestion takes them: id, dimension, assume, spec_ref and each option's ba removed."""
    return [{**{k: v for k, v in q.items() if k not in ("id", "dimension", "assume", "spec_ref")},
             "options": [{k: v for k, v in o.items() if k != "ba"} for o in q.get("options") or []]}
            for q in doc.get("questions") or [] if isinstance(q, dict)]


def question_file(project, task: str, n: int) -> Path | None:
    """Round n's question file: BA's requirement-round file, else for round 1 a BA panel's file; None when absent."""
    for rel in (ROUND.format(task=task, n=n),) + ((PANEL.format(task=task),) if n == 1 else ()):
        if (Path(project) / rel).is_file():
            return Path(project) / rel
    return None


def rounds(project, task: str) -> list:
    """(n, question file) for every round 1, 2, ... of the task on disk, stopping at the first gap."""
    out, n = [], 1
    while (path := question_file(project, task, n)) is not None:
        out.append((n, path))
        n += 1
    return out


def _source_key(source, canon):
    if not isinstance(source, str):
        return None
    kind, _, rest = source.partition(":")
    task, _, tail = rest.partition(":")
    return kind, canon(task), tail


def asked(span, source: str, file=None, after: int = 0) -> bool:
    """The span holds a main-agent AskUserQuestion after line ``after`` whose metadata.source is ``source`` (task ids
    compared canonically) and that has a tool_result of any content, is_error included. With a round ``file`` its
    questions must also equal the file's ask_view as canonical JSON, so a paraphrased round is not asked."""
    if span is None:
        return False
    canon = _lib("obligation").canonical_task_id
    want, view = _source_key(source, canon), None
    if file is not None:
        doc = _load(file)
        if doc is None:
            return False
        view = canonical(ask_view(doc))
    for call in span.calls("AskUserQuestion"):
        meta = call.input.get("metadata")
        if call.line > after and call.result_line and isinstance(meta, dict) \
                and _source_key(meta.get("source"), canon) == want \
                and (view is None or canonical(call.input.get("questions")) == view):
            return True
    return False


def ba_round_paths(task_id) -> list:
    """The round files a BA dispatch of the task may write in place of its declared artifacts (the write gate's
    stand-in paths beside the producer question): the next round, and the latest when it is BA's own (a round G2
    refused is written again)."""
    task = task_of(task_id)
    if not task:
        return []
    found = rounds(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd(), task)
    n = found[-1][0] if found else 0
    own = [ROUND.format(task=task, n=n)] if found and found[-1][1].name.startswith("requirement-round-") else []
    return own + ([ROUND.format(task=task, n=n + 1)] if found else [])


def round_asked(span, project, task: str, n: int) -> bool:
    file = question_file(project, task, n)
    return file is not None and asked(span, f"requirement-round:{task}:r{n}", file)


def _write_once(target: Path, record: dict) -> None:
    """The first matching ask per file wins: a hard link never replaces an existing file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.link(tmp, target)
    except FileExistsError:
        pass
    finally:
        tmp.unlink(missing_ok=True)


def handle(payload: dict):
    """PostToolUse(AskUserQuestion) for requirement-round and producer-question sources: writes the answer file (the
    call's questions equal the round file's ask_view) or the producer answer (the source names an existing question
    file), from the CLI's tool_input and tool_response verbatim. Main agent only; the response must hold the owner's
    content and no afkTimeoutMs; Skip, AFK, a decline or an error write nothing. Never blocks: returns None."""
    tin, resp = payload.get("tool_input"), payload.get("tool_response")
    if payload.get("tool_name") != "AskUserQuestion" or payload.get("agent_id") or not isinstance(tin, dict) \
            or not isinstance(resp, dict) or resp.get("afkTimeoutMs") \
            or not any(resp.get(k) for k in ("answers", "response", "annotations")):
        return None
    source = (tin.get("metadata") or {}).get("source") if isinstance(tin.get("metadata"), dict) else None
    match = SOURCE_RE.fullmatch(source) if isinstance(source, str) else None
    if not match:
        return None
    kind, task, tail = match.groups()
    task = task_of(task)
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd())
    if kind == "requirement-round":
        if not tail.startswith("r"):
            return None
        n = int(tail[1:])
        qfile = question_file(project, task, n)
        doc = _load(qfile) if qfile else None
        if doc is None or canonical(tin.get("questions")) != canonical(ask_view(doc)):
            return None
    else:
        if tail.startswith("r"):
            return None
        n, qfile = None, project / QUESTION.format(task=task, role=tail)
        if not qfile.is_file():
            return None
    sha = hashlib.sha256(qfile.read_bytes()).hexdigest()
    target = project / (ANSWERS.format(task=task, n=n) if n else PRODUCER_ANSWER.format(task=task, role=tail, q8=sha[:8]))
    _write_once(target, {"task_id": task, "round": n, "source": source, "tool_use_id": payload.get("tool_use_id"),
                         "asked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         "question_file_sha256": sha, "questions": tin.get("questions"),
                         "answers": resp.get("answers"), "response": resp.get("response"),
                         "annotations": resp.get("annotations")})
    return None


def _asked_questions(project, task: str) -> list:
    """(ref "r<n>.<id>", question, answered) for every question of the task's rounds; answered when the round's
    answer file holds a non-empty answer to it."""
    out = []
    for n, path in rounds(project, task) if task else ():
        doc = _load(path) or {}
        answers = (_load(Path(project) / ANSWERS.format(task=task, n=n)) or {}).get("answers")
        answers = answers if isinstance(answers, dict) else {}
        out += [(f"r{n}.{q.get('id')}", q, bool(answers.get(q.get("question"))))
                for q in doc.get("questions") or [] if isinstance(q, dict)]
    return out


def check_round(project, ob: dict, rel: str, span) -> list:
    """What JSON Schema cannot say about a schema-valid round file ``rel`` of the obligation's task (R1, D29, D32)."""
    doc, task = _load(Path(project) / rel) or {}, task_of(ob.get("task_id"))
    match = _ROUND_FILE.search(rel)
    n, errors = doc.get("round"), []
    if task_of(doc.get("task_id")) != task:
        errors.append(f"task_id: obligation declares {task!r}, file has {doc.get('task_id')!r}")
    if not match or int(match.group(2) or match.group(4)) != n:
        errors.append(f"round {n!r} is not the round the file name carries")
    elif n > 1 and not round_asked(span, project, task, n - 1):
        errors.append(f"round r{n - 1} has not been asked; a round follows the asked one before it")
    spec = doc.get("spec_id")
    if spec and not (Path(project) / f"docs/dev/specs/spec-{spec}.md").is_file():
        errors.append(f"spec_id {spec!r} names no spec (docs/dev/specs/spec-{spec}.md)")
    questions = [q for q in doc.get("questions") or [] if isinstance(q, dict)]
    if n == 1 and not spec and sorted(q.get("dimension") for q in questions) != list(DIMENSIONS):
        errors.append("a round 1 without a spec asks exactly four questions, one per dimension: " + ", ".join(DIMENSIONS))
    # Answered in an earlier round of the task or in its spec's rounds; never this round's own (D29).
    done = {_norm(q.get("question")): (t, ref) for t in {task, spec} - {None}
            for ref, q, answered in _asked_questions(project, t) if answered and (t, ref.split(".")[0]) != (task, f"r{n}")}
    verified = {r.get("ba") for r in (doc.get("panel") or {}).get("reports") or [] if r.get("root_cause") == "verified"}
    for q in questions:
        options = [o for o in q.get("options") or [] if isinstance(o, dict)]
        if _norm(q.get("question")) in done:
            owner, ref = done[_norm(q.get("question"))]
            errors.append(f"{q.get('id')}: already answered as {owner} {ref}; never ask it again")
        if q.get("assume") not in [o.get("label") for o in options]:
            errors.append(f"{q.get('id')}: assume {q.get('assume')!r} is not one of its option labels")
        for text in [q.get("question"), q.get("header")] + [o.get(k) for o in options for k in ("label", "description")]:
            token = _CODE_TOKEN.search(str(text or ""))
            if token:
                errors.append(f"{q.get('id')}: code token {token.group(0)!r}; ask the owner what to build, "
                              "never a technical choice (D18)")
        for o in options:
            if o.get("ba") and o["ba"] not in verified:
                errors.append(f"{q.get('id')}: option {o.get('label')!r} is BA {o['ba']}'s, whose root cause panel "
                              "QA did not verify; an unsupported or refuted root cause is never an option")
    return errors


def stand_in(project, ob: dict, span):
    """A BA dispatch's latest round file, written since its dispatch and not declared by it, stands in for its
    declared artifacts (D29: no round cap): "valid", a failure, or None when there is none."""
    declared = {a.get("path") for a in ob.get("artifacts") or [] if isinstance(a, dict)}
    task = task_of(ob.get("task_id"))
    found = rounds(project, task) if ob.get("role") == "ba" and task else []
    if not found:
        return None
    n, path = found[-1]
    rel = ROUND.format(task=task, n=n)
    obligation = _lib("obligation")
    if rel in declared or not path.name.startswith("requirement-round-") or round_asked(span, project, task, n) \
            or obligation.artifact_freshness_satisfied("json", path.stat().st_mtime, ob.get("dispatched_at")) is not True:
        return None  # a stand-in is a new round: never one already asked, nor one from before this dispatch
    result = _lib("contract_runtime").validate_artifact_for_obligation(str(path), "requirement-round.v1")
    errors = list(result.get("errors") or [])[:10] if result.get("status") == "fail" else []
    errors += check_round(project, ob, rel, span) if not errors else []
    return "valid" if not errors else {"path": rel, "reason": "requirement_round_invalid", "errors": errors}


def check_analysis(project, ob: dict, context: dict) -> list:
    """BA analysis maps every answered question into requirement.contract_refs and lists every unanswered one under
    assumptions with its assume label (R2)."""
    req = context.get("requirement") if isinstance(context.get("requirement"), dict) else {}
    refs = {r.get("answer_ref") for r in req.get("contract_refs") or [] if isinstance(r, dict) and r.get("criterion_ids")}
    assumed = {a.get("question_ref"): a.get("assume") for a in context.get("assumptions") or [] if isinstance(a, dict)}
    errors = []
    for ref, q, answered in _asked_questions(project, task_of(ob.get("task_id"))):
        if answered and ref not in refs:
            errors.append(f"requirement.contract_refs maps no criterion_ids to the answered question {ref}")
        if not answered and assumed.get(ref) != q.get("assume"):
            errors.append(f"assumptions lacks {{question_ref: {ref!r}, assume: {q.get('assume')!r}}} for the unanswered {ref}")
    return errors


def _question_files(project, task: str) -> list:
    """(path, source, round file or None, producer role) of every question file of the task: its rounds and the
    producer questions of its family (lanes included)."""
    family = _lib("obligation").task_family
    out = [(p, f"requirement-round:{task}:r{n}", p, "qa" if p.name.startswith("ba-panel-") else "ba")
           for n, p in rounds(project, task)]
    for p in sorted((Path(project) / "docs/dev").glob("producer-question-*-*.json")):
        owner, _, role = p.name[len("producer-question-"):-len(".json")].rpartition("-")
        if family(owner) == family(task):
            out.append((p, f"producer-question:{owner}:{role}", None, role))
    return out


def ask_first(span, project, ob: dict | None, current: str | None = None) -> str | None:
    """G1 inside an ask span (R5), for the span's task: the refusal of a dispatch made before an owner question was
    asked, else None. A dispatch that declares the question file itself (its repair) or carries no obligation passes.
    ``current`` is the tool_use id of the dispatch being decided, never counted as its role's latest dispatch."""
    if span is None or span.command not in ASK_COMMANDS or not isinstance(ob, dict):
        return None
    task = task_of(ob.get("task_id") if span.command == "spec" else span.minted_id())
    if not task:
        return None
    declared = {a.get("path") for a in ob.get("artifacts") or [] if isinstance(a, dict)}
    obligation = _lib("obligation")
    latest = {}  # (role, task) -> (call, obligation) of that producer's latest dispatch in the span
    for call in span.calls("Agent", "Task"):
        found = obligation.parse_obligation(call.input.get("prompt")) if call.id != current else None
        doc = getattr(found, "obligation", None)
        if isinstance(doc, dict):
            latest[(doc.get("role"), task_of(doc.get("task_id")))] = (call, doc)
    contract = _lib("contract_runtime")
    for path, source, round_file, role in _question_files(project, task):
        rel = path.relative_to(project).as_posix()
        if rel in declared:
            return None
        owner = task if round_file else task_of(source.split(":")[1])
        call, doc = latest.get((role, owner), (None, {}))
        if call is None or not (call.result_line and call.ok):
            continue  # its producer's latest dispatch has not come back ok: the question is not yet its to ask
        # A producer question is its producer's latest dispatch's own (written since it was dispatched) and is
        # asked after that dispatch came back: an earlier question at the same path was relayed already.
        if round_file is None and obligation.artifact_freshness_satisfied(
                "json", path.stat().st_mtime, doc.get("dispatched_at")) is not True:
            continue
        schema = "requirement-round.v1" if round_file else "producer-question.v1"
        # A round G2 refuses (an answered question again, a refuted BA's option) is never asked: its producer
        # writes it again, so it holds no dispatch back.
        if contract.validate_artifact_for_obligation(str(path), schema).get("status") == "pass" \
                and not (round_file and check_round(project, {"task_id": task}, rel, span)) \
                and not asked(span, source, round_file, after=0 if round_file else call.result_line):
            return (f"ASK_FIRST: ask {rel} with one AskUserQuestion, metadata.source \"{source}\", questions exactly "
                    "as written; then dispatch.")
    if declared and not all(_PRE_ASK.search(p or "") for p in declared) and not round_asked(span, project, task, 1):
        return (f"ASK_FIRST: no requirement round r1 of task {task} has been asked; dispatch BA intake for "
                f"{ROUND.format(task=task, n=1)} (or the BA panel and its panel QA), ask it with one AskUserQuestion, "
                "then dispatch.")
    return None


def ends_with_question(text) -> bool:
    """R7: the last non-empty line of the turn's last main-agent text ends with "?" or a full-width one."""
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return bool(lines) and lines[-1].endswith(("?", "？"))
