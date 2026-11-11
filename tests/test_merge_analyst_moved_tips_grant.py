"""agents/merge-analyst.md Phase 1's blocked grant for moved tips is one hooks/lib/merge_grant.py keeps.

Phase 1 blocks when a tip moved between /merge Step 1 and the analysis, and writes the Phase 8 grant
with that risk. merge_grant.fault() removes a grant whose `source_tip` or `default_tip` is not the live
tip, so a grant carrying the dispatched tips (Step 1's SOURCE_TIP and DEFAULT_TIP) can never be kept
in that case: the analyst ends with no grant and /merge Step 3 refuses "no grant" instead of showing
the blocked verdict and its risk. Each test plays the text as written (Phase 1's fence run, Phase 8's
JSON template bound) against a scratch repository and asks merge_grant.fault() about the result.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
import merge_grant  # noqa: E402

ANALYST = (ROOT / "agents" / "merge-analyst.md").read_text(encoding="utf-8")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def phase(n: int) -> str:
    m = re.search(rf"^### Phase {n}:.*?(?=^### |^## )", ANALYST, re.M | re.S)
    assert m, f"agents/merge-analyst.md has no Phase {n}"
    return m.group(0)


def fence(text: str, lang: str) -> str:
    m = re.search(rf"^```{lang}\n(.*?)^```", text, re.M | re.S)
    assert m, f"no ```{lang} fence"
    return m.group(1)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path / "state"))
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "master")
    git(r, "config", "user.email", "t@example.invalid")
    git(r, "config", "user.name", "test")
    (r / "f.txt").write_text("x\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "base")
    git(r, "checkout", "-q", "-b", "feat")
    (r / "g.txt").write_text("y\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "feat")
    git(r, "checkout", "-q", "master")
    return r


def dispatch(r) -> dict:
    """The lines /merge Step 1 prints, as the analyst's dispatch carries them."""
    root = os.path.realpath(git(r, "rev-parse", "--show-toplevel"))
    return {"RESOLVED_REF": "feat", "SOURCE_TIP": git(r, "rev-parse", "feat"), "DEFAULT_BRANCH": "master",
            "DEFAULT_TIP": git(r, "rev-parse", "master"), "REQUEST_ID": "req1", "SESSION_ID": "sid-merge",
            "REPO_HASH": hashlib.sha256(root.encode()).hexdigest()[:16], "REPO_ROOT": root}


def phase1(r, values: dict) -> dict:
    """Phase 1's fence, run in the repository: the tips it reads."""
    script = fence(phase(1), "bash") + 'printf "%s\\n" "CURRENT_SOURCE_TIP=$CURRENT_SOURCE_TIP" ' \
                                       '"CURRENT_DEFAULT_TIP=$CURRENT_DEFAULT_TIP"\n'
    out = subprocess.run(["bash", "-c", script], cwd=r, env={**os.environ, **values}, capture_output=True,
                         text=True, check=True).stdout
    return dict(re.findall(r"^([A-Z_]+)=(\S*)$", out, re.M))


def write_grant(values: dict, verdict: str, risks: list) -> Path:
    """Phase 8's JSON template, its placeholders bound, at the path Phase 8 gives."""
    doc = {}
    for key, val in json.loads(fence(phase(8), "json")).items():
        name = re.fullmatch(r"<([A-Z_]+)>", str(val))
        if isinstance(val, list):
            doc[key] = risks
        elif name:
            doc[key] = values[name.group(1)]
        elif val == "<approved|blocked>":
            doc[key] = verdict
        elif "ISO-8601" in str(val):
            doc[key] = (datetime.now(timezone.utc) + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            doc[key] = "summary"
    path = Path(merge_grant.grant_root(), values["REPO_HASH"], values["SESSION_ID"], values["REQUEST_ID"] + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))
    return path


def test_the_moved_tips_blocked_grant_is_kept(repo):
    values = dispatch(repo)
    (repo / "h.txt").write_text("z\n")  # the owner's commit on the source after Step 1, before Phase 1
    git(repo, "checkout", "-q", "feat")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "more")
    git(repo, "checkout", "-q", "master")
    values.update(phase1(repo, values))
    assert values["CURRENT_SOURCE_TIP"] != values["SOURCE_TIP"], "the source tip did not move"
    risk = re.search(r'^- Tip differs.*?risks=\["([^"]+)"\]', phase(1), re.M)
    assert risk, "Phase 1 names no moved-tips case"
    path = write_grant(values, "blocked", [risk.group(1)])
    assert merge_grant.fault(str(path)) == "", "Phase 1's blocked grant for moved tips is one merge_grant.py removes"


def test_the_approved_grant_is_kept(repo):
    values = dispatch(repo)
    values.update(phase1(repo, values))
    path = write_grant(values, "approved", [])
    assert merge_grant.fault(str(path)) == ""
    assert json.loads(path.read_text())["source_tip"] == values["SOURCE_TIP"]
