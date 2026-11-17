"""hooks/lib/harness_temp_state.py: which resolved paths are harness temp state.

Each inventoried temp location classifies, symlink-safely, under every root spelling.

Every inventoried location (docs/reference/harness-temp-state.md) is classified
under the state dir, a temp root and its override directory; symlinks into and
out of state, `..`, non-temp paths and every TMPDIR spelling are judged on the
resolved path. The system temp roots are swapped for directories under tmp_path,
so no test reads or writes the real /tmp or /var/tmp.
"""

import os
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1] / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

import harness_temp_state as hts  # noqa: E402

ENV_VARS = ("CLAUDE_STATE_DIR", "TMPDIR", "CLAUDE_TMPDIR", "CLAUDE_CODE_TMPDIR",
            "XDG_RUNTIME_DIR") + hts.NAME_ROOT_VARS + tuple(
    var for loc in hts.LOCATIONS for var in loc.tree_vars)


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Fake /tmp and /var/tmp; every variable the module reads starts unset."""
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    tmp = tmp_path / "tmp"
    var_tmp = tmp_path / "var" / "tmp"
    tmp.mkdir()
    var_tmp.mkdir(parents=True)
    monkeypatch.setattr(hts, "SYSTEM_TEMP_ROOTS", (str(tmp), str(var_tmp)))
    # harness_state_dir() defaults to the literal /tmp; point it at the fake one.
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp))
    return tmp, var_tmp


# (location name, path below a name root) -- one or more per inventoried location.
CASES = [
    ("sentinel-grants", "claude-grants"),
    ("sentinel-grants", "claude-grants/20261117-101010.json"),
    ("do-consent-flag", "claude-orchestrator-consent-sid1.flag"),
    ("tool-streak", "claude-tool-streak-sid1.json"),
    ("do-reservation", "claude-do-resv-20261117-101010"),
    ("do-task-sidecar", "claude-do-task-sid1.json"),
    ("userintent-flag", "claude-commit-userintent-sid1.flag"),
    ("userintent-flag", "claude-stop-userintent-sid1.flag"),
    ("helper-auth", "claude-stop-helper-auth-sid1.json"),
    ("git-grant", "claude-commit-grant-sid1-abc.json"),
    ("git-grant", "claude-push-grant-sid1-abc.json"),
    ("commit-dispatch-attest", "claude-commit-dispatch-sid1-abc.json"),
    ("commit-manifest", "claude-commit-manifest-sid1.json"),
    ("bulk-commit-sentinel", "claude-bulk-commit-sentinel-sid1-abc.json"),
    ("commit-event-pointer", "claude-commit-event-k1.json"),
    ("agentic-commit", "agentic-commit"),
    ("agentic-commit", "agentic-commit/commit-events/x.jsonl"),
    ("agentic-commit", "agentic-commit/push/abc/main.token"),
    ("agentic-commit", "agentic-commit/push-analyst/abc/main-chainB.validated.sentinel.json"),
    ("agentic-commit", "agentic-commit/merge-analyst/g.json"),
    ("agentic-commit", "agentic-commit/locks/abc.lock"),
    ("git-residual-override", "claude-git-residual-override/o.json"),
    ("runcode-watchdog-pid", ".runcode-watchdog-sid1.pid"),
    ("usage-snapshot-cache", "claude-usage-snapshot-cache.json"),
    ("usage-snapshot-cache", ".usage-cache-x1y2"),
    ("worktree-guard-cache", "worktree-guard-cache"),
    ("git-fswatch-lock", "git-fswatch-user-repo.lock"),
    ("tmpfs-pressure-counter", "claude-pressure-warn-sid1"),
    ("tmpfs-pressure-counter", "claude-pressure-warn-sid1.lock"),
    ("checkpoint-push-stamp", ".checkpoint-push-abc123.ts"),
    ("capability-state", "claude-capability-0/sid1.json"),
    ("git-blessed-grants", "claude-git-blessed/tok.grant"),
    ("daemon-restart-grant", "claude-allow-daemon-restart-web.flag"),
    ("scratch-owner", "sid1/.owner"),
    ("scratch-owner", "sid1/.owner.123.tmp"),
    ("scratch-owner", "claude-scratch/sid1/.owner"),
    ("doc-sync-notices", "sid1/doc-sync-notices-main.json"),
    ("doc-sync-notices", "sid1/.doc-sync-notices-x.tmp"),
    ("doc-sync-notices", "claude-scratch/sid1/doc-sync-notices-agent-ab.json"),
    ("claude-scratch", "claude-scratch/qa/report.json"),
    ("claude-scratch", "claude-scratch/changelog-analyst/commit-msg-1.txt"),
    ("claude-scratch", "claude-scratch/sid1/tmp.abc"),
    ("codex-outputs", "codex-outputs/codex-output-1-2.txt"),
    ("graphify-cache", "claude-graphify/repo/graph.json"),
    ("orchestrator-output", "dev-output-1.json"),
    ("orchestrator-output", "qa-output-1.json"),
    ("orchestrator-output", "iteration-context-1.json"),
    ("orchestrator-output", "cleanliness-output-1.json"),
    ("orchestrator-output", "style-output-1.json"),
    ("orchestrator-output", "cleaner-output-1.json"),
    ("orchestrator-output", "rule-output-1.json"),
    ("runtime-guard-err", "runtime-guard-AbC123"),
    ("grepguard-probe", "grepguard-probe-x1/probe.txt"),
    ("checkpoint-result", "checkpoint-result.123.ns"),
    ("hero-fixture", "claude-hero-fixture-x1/repo/file"),
    ("tmp-cleanup-candidates", "tmp-cleanup-cands-AbC123"),
]


def test_every_location_has_a_case():
    assert {loc.name for loc in hts.LOCATIONS} == {name for name, _ in CASES}


def test_location_names_are_unique_and_kinds_known():
    names = [loc.name for loc in hts.LOCATIONS]
    assert len(names) == len(set(names))
    assert {loc.kind for loc in hts.LOCATIONS} == {hts.CONTROL, hts.SCRATCH}


@pytest.mark.parametrize("name,rel", CASES)
def test_location_classified_under_the_state_dir(roots, name, rel):
    tmp, _ = roots
    loc = hts.classify(str(tmp / rel))
    assert loc is not None and loc.name == name
    assert hts.is_harness_state(str(tmp / rel), include_scratch=True)
    assert hts.is_harness_state(str(tmp / rel)) == (loc.kind == hts.CONTROL)


@pytest.mark.parametrize("name,rel", CASES)
def test_location_classified_under_var_tmp(roots, name, rel):
    _, var_tmp = roots
    loc = hts.classify(str(var_tmp / rel))
    assert loc is not None and loc.name == name


@pytest.mark.parametrize("name,rel", CASES)
def test_location_classified_under_tmpdir(roots, tmp_path, monkeypatch, name, rel):
    scratch = tmp_path / "scratch-root"
    scratch.mkdir()
    monkeypatch.setenv("TMPDIR", str(scratch))
    loc = hts.classify(str(scratch / rel))
    assert loc is not None and loc.name == name


@pytest.mark.parametrize("name,rel", CASES)
def test_location_classified_under_an_absolute_state_dir_outside_temp(roots, tmp_path, monkeypatch,
                                                                     name, rel):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(state))
    loc = hts.classify(str(state / rel))
    assert loc is not None and loc.name == name


def test_control_wins_over_scratch_for_a_session_owner_file(roots):
    _, var_tmp = roots
    assert hts.classify(str(var_tmp / "claude-scratch" / "sid1" / ".owner")).name == "scratch-owner"


@pytest.mark.parametrize("rel", [
    "foo", "notes.txt", "claude-grants-old", "xclaude-grants/a.json",
    "claude-commit-grant.json", "claude-orchestrator-consent-sid1.flag.bak",
    "dev-output-1.txt", "codex-outputs-old/x", "claude-scratch",
    "a/b/.owner", "sub/claude-grants/x.json", "sub/claude-commit-grant-a-b.json",
])
def test_ordinary_temp_files_are_not_state(roots, rel):
    tmp, _ = roots
    assert hts.classify(str(tmp / rel)) is None
    assert hts.is_in_temp_root(str(tmp / rel))


@pytest.mark.parametrize("path", [
    "/etc/passwd", "/srv/project/claude-grants/x.json", "/opt/claude-commit-grant-a-b.json",
    "/", "", "rel\x00path",
])
def test_non_temp_paths_are_neither(roots, path):
    assert hts.classify(path) is None
    assert not hts.is_harness_state(path, include_scratch=True)
    assert not hts.is_in_temp_root(path)


def test_state_name_outside_every_root_is_not_state(roots, tmp_path):
    elsewhere = tmp_path / "project"
    elsewhere.mkdir()
    assert hts.classify(str(elsewhere / "claude-grants" / "x.json")) is None


def test_dotdot_is_resolved(roots):
    tmp, _ = roots
    (tmp / "work").mkdir()
    assert hts.classify(str(tmp / "work" / ".." / "claude-do-task-s.json")).name == "do-task-sidecar"
    assert hts.classify(str(tmp / "claude-grants" / ".." / "foo")) is None
    assert hts.classify(str(tmp / ".." / "tmp" / "claude-grants" / "a.json")).name == "sentinel-grants"
    # `..` climbing out of a temp root is outside it.
    assert not hts.is_in_temp_root(str(tmp / ".." / "elsewhere"))


def test_dotdot_through_a_symlink_follows_the_link(roots, tmp_path):
    tmp, _ = roots
    deep = tmp / "claude-grants" / "inner"
    deep.mkdir(parents=True)
    hop = tmp_path / "hop"
    hop.symlink_to(deep)
    # Lexically hop/.. is tmp_path; really it is <tmp>/claude-grants.
    assert hts.classify(str(hop / ".." / "g.json")).name == "sentinel-grants"


def test_relative_path_resolved_against_cwd(roots):
    tmp, _ = roots
    assert hts.classify("claude-tool-streak-s.json", cwd=str(tmp)).name == "tool-streak"
    assert hts.classify("x.json", cwd=str(tmp)) is None


def test_symlink_from_outside_into_state_counts(roots, tmp_path):
    tmp, _ = roots
    (tmp / "claude-grants").mkdir()
    link = tmp_path / "innocent.json"
    link.symlink_to(tmp / "claude-grants" / "t.json")  # dangling is fine
    assert hts.classify(str(link)).name == "sentinel-grants"
    dir_link = tmp_path / "dirlink"
    dir_link.symlink_to(tmp / "agentic-commit", target_is_directory=True)
    assert hts.classify(str(dir_link / "push" / "x")).name == "agentic-commit"


def test_symlink_in_temp_into_state_counts(roots):
    tmp, _ = roots
    (tmp / "claude-git-residual-override").mkdir()
    link = tmp / "plain-looking"
    link.symlink_to(tmp / "claude-git-residual-override")
    assert hts.classify(str(link / "o.json")).name == "git-residual-override"


def test_symlink_out_of_state_target_is_not_state_but_the_link_is(roots, tmp_path):
    tmp, _ = roots
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp / "claude-grants").symlink_to(outside, target_is_directory=True)
    # A write through the link lands outside every root.
    assert hts.classify(str(outside / "a.json")) is None
    assert hts.classify(str(tmp / "claude-grants" / "a.json")) is None
    assert not hts.is_in_temp_root(str(tmp / "claude-grants" / "a.json"))
    # The directory entry itself is still the state name.
    assert hts.classify(str(tmp / "claude-grants")).name == "sentinel-grants"
    file_link = tmp / "claude-do-task-s.json"
    file_link.symlink_to(outside / "f.json")
    assert hts.classify(str(file_link)).name == "do-task-sidecar"


def test_temp_root_alias_like_private_tmp(tmp_path, monkeypatch):
    """/tmp -> /private/tmp: a path spelled through either name is the same root."""
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    real = tmp_path / "private" / "tmp"
    real.mkdir(parents=True)
    alias = tmp_path / "tmp"
    alias.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(hts, "SYSTEM_TEMP_ROOTS", (str(alias),))
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(alias))
    assert hts.temp_roots() == (str(real),)
    for base in (alias, real):
        assert hts.classify(str(base / "claude-push-grant-s-n.json")).name == "git-grant"
        assert hts.temp_root_of(str(base / "anything")) == str(real)


def test_temp_roots_tmpdir_unset_empty_relative(roots, tmp_path, monkeypatch):
    """Fail closed: an unset, empty, relative or "/" TMPDIR never widens what is temp."""
    tmp, var_tmp = roots
    expected = (str(tmp), str(var_tmp))
    assert hts.temp_roots() == expected
    (tmp_path / "relative" / "dir").mkdir(parents=True)
    for value in ("", "relative/dir", "/", "//"):
        monkeypatch.setenv("TMPDIR", value)
        assert hts.temp_roots() == expected
        assert not hts.is_in_temp_root("/etc/x")
        assert not hts.is_in_temp_root("x", cwd=str(tmp_path / "relative" / "dir"))
    # A relative TMPDIR still counts for state detection, against the cwd.
    monkeypatch.setenv("TMPDIR", "relative/dir")
    cwd = str(tmp_path)
    target = "relative/dir/claude-git-blessed/t.grant"
    assert hts.classify(target, cwd=cwd).name == "git-blessed-grants"
    assert hts.temp_root_of(target, cwd=cwd) is None
    assert str(tmp_path / "relative" / "dir") in hts.name_roots(cwd=cwd)
    assert str(tmp_path / "relative" / "dir") not in hts.temp_roots()


def test_temp_roots_tmpdir_set_trailing_slash_and_duplicate(roots, tmp_path, monkeypatch):
    tmp, var_tmp = roots
    scratch = var_tmp / "claude-scratch"
    scratch.mkdir()
    monkeypatch.setenv("TMPDIR", str(scratch) + "/")
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(scratch))
    monkeypatch.setenv("CLAUDE_TMPDIR", str(tmp))
    assert hts.temp_roots() == (str(tmp), str(var_tmp), str(scratch))
    # The deepest root wins when roots nest.
    assert hts.temp_root_of(str(scratch / "x")) == str(scratch)
    assert hts.temp_root_of(str(var_tmp / "x")) == str(var_tmp)


def test_temp_roots_tmpdir_is_a_symlink(roots, tmp_path, monkeypatch):
    real = tmp_path / "real-scratch"
    real.mkdir()
    link = tmp_path / "scratch-link"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("TMPDIR", str(link))
    assert str(real) in hts.temp_roots()
    assert hts.classify(str(link / "claude-git-blessed" / "t.grant")).name == "git-blessed-grants"
    assert hts.classify(str(real / "runtime-guard-AAA")).name == "runtime-guard-err"


def test_temp_root_itself_is_not_inside_a_temp_root(roots):
    tmp, var_tmp = roots
    assert not hts.is_in_temp_root(str(tmp))
    assert not hts.is_in_temp_root(str(tmp) + "/")
    assert hts.is_in_temp_root(str(tmp / "x"))
    assert hts.classify(str(tmp)) is None


def test_whole_directory_overrides(roots, tmp_path, monkeypatch):
    for var, rel, name in (
        ("CLAUDE_GIT_BLESSED_GRANT_DIR", "t.grant", "git-blessed-grants"),
        ("CLAUDE_CAPABILITY_STATE_DIR", "s.json", "capability-state"),
        ("CLAUDE_GRAPHIFY_CACHE_ROOT", "repo/graph.json", "graphify-cache"),
    ):
        directory = tmp_path / var.lower()
        directory.mkdir()
        assert hts.classify(str(directory / rel)) is None
        monkeypatch.setenv(var, str(directory))
        assert hts.classify(str(directory / rel)).name == name
        assert hts.classify(str(directory)).name == name
    # A relative override names no directory.
    monkeypatch.setenv("CLAUDE_GRAPHIFY_CACHE_ROOT", "relative")
    assert hts.classify(str(tmp_path / "claude_graphify_cache_root" / "repo" / "graph.json")) is None


def test_xdg_runtime_capability_dir(roots, tmp_path, monkeypatch):
    xdg = tmp_path / "run-user"
    xdg.mkdir()
    target = xdg / "claude-capability" / "s.json"
    assert hts.classify(str(target)) is None
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(xdg))
    assert hts.classify(str(target)).name == "capability-state"
    assert hts.classify(str(xdg / "other")) is None


@pytest.mark.parametrize("var,rel,name", [
    ("CLAUDE_USERINTENT_SENTINEL_DIR", "claude-commit-userintent-s.flag", "userintent-flag"),
    ("CLAUDE_DAEMON_RESTART_GRANT_DIR", "claude-allow-daemon-restart-web.flag", "daemon-restart-grant"),
    ("CLAUDE_DOC_SYNC_STATE_ROOT", "sid1/doc-sync-notices-main.json", "doc-sync-notices"),
])
def test_name_root_overrides(roots, tmp_path, monkeypatch, var, rel, name):
    directory = tmp_path / "override"
    directory.mkdir()
    assert hts.classify(str(directory / rel)) is None
    monkeypatch.setenv(var, str(directory))
    assert hts.classify(str(directory / rel)).name == name
    assert hts.classify(str(directory / "unrelated.txt")) is None
    monkeypatch.setenv(var, "relative")
    assert hts.classify(str(directory / rel)) is None


def test_relative_state_dir_falls_back_to_default(roots, monkeypatch):
    monkeypatch.setenv("CLAUDE_STATE_DIR", "relative/state")
    assert hts.state_dir() == os.path.realpath("/tmp")


def test_pathlike_and_bad_input(roots):
    tmp, _ = roots
    assert hts.classify(tmp / "claude-do-task-s.json").name == "do-task-sidecar"
    assert hts.resolved_views("") == ()
    # Not a path at all: an error, never a silent "not state".
    for bad in (None, 123, 1.5, object()):
        with pytest.raises(TypeError):
            hts.classify(bad)
        with pytest.raises(TypeError):
            hts.is_harness_state(bad)
        with pytest.raises(TypeError):
            hts.is_in_temp_root(bad)


def test_bytes_paths_are_decoded_not_failed_open(roots):
    tmp, _ = roots
    raw = os.fsencode(str(tmp / "claude-commit-grant-s-n.json"))
    assert hts.classify(raw).name == "git-grant"
    assert hts.is_harness_state(raw)
    assert hts.is_in_temp_root(raw)
    assert hts.classify(os.fsencode("claude-grants/x.json"), cwd=str(tmp)).name == "sentinel-grants"
    # Undecodable bytes survive through surrogateescape and still match.
    odd = os.fsencode(str(tmp / "claude-grants")) + b"/\xff\xfe.json"
    assert hts.classify(odd).name == "sentinel-grants"


def test_root_slash_is_a_name_root_but_never_a_temp_root(roots, monkeypatch):
    monkeypatch.setenv("TMPDIR", "/")
    assert os.sep not in hts.temp_roots()
    assert not hts.is_in_temp_root("/etc/passwd")
    assert hts.temp_root_of("/claude-git-blessed/t.grant") is None
    assert hts.classify("/claude-git-blessed/t.grant").name == "git-blessed-grants"
    assert hts.classify("/etc/passwd") is None
    monkeypatch.delenv("TMPDIR")
    assert hts.classify("/claude-allow-daemon-restart-web.flag") is None
    monkeypatch.setenv("CLAUDE_TMPDIR", "/")
    assert hts.classify("/claude-allow-daemon-restart-web.flag").name == "daemon-restart-grant"
    assert not hts.is_in_temp_root("/claude-allow-daemon-restart-web.flag")


@pytest.mark.parametrize("var,rel,name", [
    ("TMPDIR", "claude-git-blessed/t.grant", "git-blessed-grants"),
    ("CLAUDE_TMPDIR", "claude-allow-daemon-restart-web.flag", "daemon-restart-grant"),
    ("CLAUDE_DAEMON_RESTART_GRANT_DIR", "claude-allow-daemon-restart-web.flag", "daemon-restart-grant"),
    ("TMP", "sid1/doc-sync-notices-main.json", "doc-sync-notices"),
    ("TEMP", "sid1/doc-sync-notices-main.json", "doc-sync-notices"),
])
def test_relative_name_root_vars_resolve_against_cwd(roots, tmp_path, monkeypatch, var, rel, name):
    work = tmp_path / "work"
    (work / "rel-root").mkdir(parents=True)
    monkeypatch.setenv(var, "rel-root")
    assert hts.classify(f"rel-root/{rel}", cwd=str(work)).name == name
    assert hts.classify(str(work / "rel-root" / rel), cwd=str(work)).name == name
    # Without cwd= the process cwd is used.
    monkeypatch.chdir(work)
    assert hts.classify(str(work / "rel-root" / rel)).name == name
    # Never a temp root.
    assert not hts.is_in_temp_root(str(work / "rel-root" / rel), cwd=str(work))


@pytest.mark.parametrize("var,rel,name", [
    ("CLAUDE_GIT_BLESSED_GRANT_DIR", "t.grant", "git-blessed-grants"),
    ("CLAUDE_CAPABILITY_STATE_DIR", "s.json", "capability-state"),
    ("XDG_RUNTIME_DIR", "claude-capability/s.json", "capability-state"),
])
def test_relative_tree_vars_resolve_against_cwd(roots, tmp_path, monkeypatch, var, rel, name):
    work = tmp_path / "work"
    (work / "rel-dir").mkdir(parents=True)
    monkeypatch.setenv(var, "rel-dir")
    assert hts.classify(str(work / "rel-dir" / rel), cwd=str(work)).name == name
    monkeypatch.chdir(work)
    assert hts.classify(f"rel-dir/{rel}").name == name
    assert not hts.is_in_temp_root(f"rel-dir/{rel}")


@pytest.mark.parametrize("rel", [
    "CLAUDE-GRANTS/x.json", "Claude-Commit-Grant-s-n.json", "claude-orchestrator-CONSENT-s.flag",
    "AGENTIC-COMMIT/push/x", "sid1/.OWNER",
])
def test_control_names_match_case_insensitively(roots, rel):
    tmp, _ = roots
    loc = hts.classify(str(tmp / rel))
    assert loc is not None and loc.kind == hts.CONTROL


def test_control_root_matches_case_insensitively(roots, tmp_path, monkeypatch):
    state = tmp_path / "State"
    state.mkdir()
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(state))
    # On a case-insensitive filesystem /…/state names the same directory.
    assert hts.classify(str(tmp_path / "state" / "claude-tool-streak-s.json")).name == "tool-streak"
    # Temp roots stay case-sensitive: case folding never widens what is temp.
    tmp, _ = roots
    upper = str(tmp).upper()
    if upper != str(tmp):
        assert not hts.is_in_temp_root(upper + "/x")


def test_the_module_writes_nothing(roots):
    tmp, var_tmp = roots
    before = sorted(os.listdir(tmp)) + sorted(os.listdir(var_tmp))
    hts.classify(str(tmp / "claude-grants" / "x.json"))
    hts.is_in_temp_root(str(var_tmp / "codex-outputs" / "y"))
    assert sorted(os.listdir(tmp)) + sorted(os.listdir(var_tmp)) == before


def test_real_default_roots_without_fakes(monkeypatch):
    """With nothing faked, the literal /tmp and /var/tmp are the roots and state names under them classify."""
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    assert hts.temp_roots()[:2] == (os.path.realpath("/tmp"), os.path.realpath("/var/tmp"))
    assert hts.classify("/tmp/claude-commit-grant-s-n.json").name == "git-grant"
    assert hts.classify("/var/tmp/codex-outputs/codex-output-1-2.txt").name == "codex-outputs"
    assert hts.classify("/tmp/claude-scratch/qa/x").kind == hts.SCRATCH
    assert not hts.is_harness_state("/tmp/claude-scratch/qa/x")


# --- crosses_mount / mount_points -------------------------------------------

def _mountinfo(tmp_path, *points, name="mountinfo"):
    """A mountinfo file listing `points` (already escaped as the kernel writes them).
    A point is a path (its own dev, root "/") or a (path, dev, root) tuple."""
    lines = []
    for i, point in enumerate(points):
        path, dev, root = point if isinstance(point, tuple) else (point, "0:%d" % (100 + i), "/")
        lines.append("%d 1 %s %s %s rw,relatime - ext4 /dev/x rw" % (20 + i, dev, root, path))
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def test_parse_mountinfo_unescapes_octal():
    text = ("36 35 98:0 /mnt1 /mnt/with\\040space rw - ext3 /dev/sda1 rw\n"
            "37 35 98:0 / /a\\011tab\\012nl\\134bs rw shared:1 - ext3 /dev/sda1 rw\n")
    assert hts.parse_mountinfo(text) == ("/mnt/with space", "/a\ttab\nnl\\bs")


def test_parse_mountinfo_rejects_a_short_line():
    with pytest.raises(ValueError):
        hts.parse_mountinfo("1 2 3\n")


def test_mount_points_realpaths_and_dedupes(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "alias").symlink_to(real, target_is_directory=True)
    info = _mountinfo(tmp_path, "/", str(real), str(tmp_path / "alias"))
    assert hts.mount_points(info) == ("/", str(real))


def test_mount_points_unreadable_or_empty_raises(tmp_path):
    with pytest.raises(OSError):
        hts.mount_points(str(tmp_path / "missing"))
    empty = tmp_path / "empty"
    empty.write_text("")
    with pytest.raises(ValueError):
        hts.mount_points(str(empty))


def test_crosses_mount_ignores_the_slash_mount_and_a_tmpfs_at_tmp(roots, tmp_path):
    tmp, var_tmp = roots
    info = _mountinfo(tmp_path, ("/", "254:0", "/"), (str(tmp), "0:50", "/"),
                      (str(var_tmp), "0:51", "/"), ("/proc", "0:21", "/"))
    assert not hts.crosses_mount(str(tmp / "a" / "b"), mountinfo=info)
    assert not hts.crosses_mount(str(tmp / "a"), below=True, mountinfo=info)
    assert not hts.crosses_mount(str(var_tmp / "x"), mountinfo=info)


def test_crosses_mount_a_mount_above_a_system_temp_root_is_not_ignored(roots, tmp_path):
    tmp, _ = roots
    # The parent of /tmp is neither "/" nor a temp root: a bind there carries /tmp.
    info = _mountinfo(tmp_path, "/", str(tmp.parent))
    assert hts.crosses_mount(str(tmp / "a"), mountinfo=info)


def test_crosses_mount_bind_at_tmp_with_a_subdirectory_root(roots, tmp_path):
    tmp, _ = roots
    # `mount --bind /home/x /tmp`: field 4 names the bound directory, not "/".
    info = _mountinfo(tmp_path, ("/", "254:0", "/"), (str(tmp), "254:0", "/srv/victim"))
    assert hts.crosses_mount(str(tmp / "x"), mountinfo=info)


def test_crosses_mount_bind_at_tmp_sharing_a_dev_outside_temp(roots, tmp_path):
    tmp, _ = roots
    # `mount --bind / /tmp`: root "/", but the dev is the root filesystem's.
    info = _mountinfo(tmp_path, ("/", "254:0", "/"), (str(tmp), "254:0", "/"))
    assert hts.crosses_mount(str(tmp / "x"), mountinfo=info)
    # Another filesystem's dev, also mounted outside temp: still a bind.
    info = _mountinfo(tmp_path, ("/", "254:0", "/"), ("/srv", "0:60", "/"),
                      (str(tmp), "0:60", "/"), name="mi2")
    assert hts.crosses_mount(str(tmp / "x"), mountinfo=info)
    # The same dev mounted again inside the temp roots does not make it a bind.
    info = _mountinfo(tmp_path, ("/", "254:0", "/"), (str(tmp), "0:61", "/"),
                      (str(tmp / "sub"), "0:61", "/"), name="mi3")
    assert not hts.crosses_mount(str(tmp / "x"), mountinfo=info)


def test_crosses_mount_at_tmpdir_and_between(roots, tmp_path, monkeypatch):
    tmp, _ = roots
    inner = tmp / "a" / "b"
    inner.mkdir(parents=True)
    monkeypatch.setenv("TMPDIR", str(inner))
    for point in (str(inner), str(tmp / "a")):
        info = _mountinfo(tmp_path, ("/", "254:0", "/"), (point, "0:70", "/"),
                          name="mi-" + os.path.basename(point))
        assert hts.crosses_mount(str(inner / "x"), mountinfo=info)
        assert hts.crosses_mount(str(inner / "x"), below=True, mountinfo=info)
    # A bind at /tmp itself, seen from a path under TMPDIR.
    info = _mountinfo(tmp_path, ("/", "254:0", "/"), (str(tmp), "254:0", "/"), name="mi-tmp")
    assert hts.crosses_mount(str(inner / "x"), mountinfo=info)
    # Plain: only "/" and a tmpfs at /tmp.
    info = _mountinfo(tmp_path, ("/", "254:0", "/"), (str(tmp), "0:71", "/"), name="mi-ok")
    assert not hts.crosses_mount(str(inner / "x"), mountinfo=info)


def test_parse_mountinfo_entries_fields():
    text = "36 35 98:0 /mnt\\0401 /mnt/with\\040space rw - ext3 /dev/sda1 rw\n"
    (entry,) = hts.parse_mountinfo_entries(text)
    assert (entry.dev, entry.root, entry.point) == ("98:0", "/mnt 1", "/mnt/with space")


def test_crosses_mount_at_the_target(roots, tmp_path):
    tmp, _ = roots
    info = _mountinfo(tmp_path, "/", str(tmp), str(tmp / "b3"))
    assert hts.crosses_mount(str(tmp / "b3"), mountinfo=info)
    assert hts.crosses_mount(str(tmp / "b3") + "/", mountinfo=info)


def test_crosses_mount_on_the_path(roots, tmp_path):
    tmp, _ = roots
    info = _mountinfo(tmp_path, "/", str(tmp / "b3"))
    assert hts.crosses_mount(str(tmp / "b3" / "settings.json"), mountinfo=info)
    assert hts.crosses_mount(str(tmp / "b3" / "x" / ".." / "y"), mountinfo=info)
    assert not hts.crosses_mount(str(tmp / "b31" / "x"), mountinfo=info)


def test_crosses_mount_below_the_target_only_with_below(roots, tmp_path):
    tmp, _ = roots
    info = _mountinfo(tmp_path, "/", str(tmp / "work" / "deep" / "b3"))
    assert not hts.crosses_mount(str(tmp / "work"), mountinfo=info)
    assert hts.crosses_mount(str(tmp / "work"), below=True, mountinfo=info)
    assert not hts.crosses_mount(str(tmp / "other"), below=True, mountinfo=info)


def test_crosses_mount_escaped_mount_point(roots, tmp_path):
    tmp, _ = roots
    info = _mountinfo(tmp_path, "/", str(tmp / "b") + "\\040c")
    assert hts.crosses_mount(str(tmp / "b c" / "f"), mountinfo=info)
    assert not hts.crosses_mount(str(tmp / "b" / "f"), mountinfo=info)


def test_crosses_mount_uses_the_deepest_temp_root(roots, tmp_path, monkeypatch):
    _, var_tmp = roots
    scratch = var_tmp / "claude-scratch"
    scratch.mkdir()
    monkeypatch.setenv("TMPDIR", str(scratch))
    # A mount under TMPDIR is judged against TMPDIR, the deepest root.
    info = _mountinfo(tmp_path, "/", str(scratch / "m"))
    assert hts.crosses_mount(str(scratch / "m" / "x"), mountinfo=info)
    assert not hts.crosses_mount(str(scratch / "other"), mountinfo=info)


def test_crosses_mount_fails_closed(roots, tmp_path):
    tmp, _ = roots
    assert hts.crosses_mount(str(tmp / "x"), mountinfo=str(tmp_path / "missing"))
    bad = tmp_path / "bad"
    bad.write_text("garbage\n")
    assert hts.crosses_mount(str(tmp / "x"), mountinfo=str(bad))
    info = _mountinfo(tmp_path, "/")
    assert hts.crosses_mount("/etc/passwd", mountinfo=info)   # in no temp root
    assert hts.crosses_mount(str(tmp), mountinfo=info)         # the root itself
    assert hts.crosses_mount("", mountinfo=info)
    assert hts.crosses_mount(None, mountinfo=info)              # error -> True


def test_crosses_mount_symlink_out_of_temp_fails_closed(roots, tmp_path):
    tmp, _ = roots
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp / "link").symlink_to(outside, target_is_directory=True)
    info = _mountinfo(tmp_path, "/")
    assert hts.crosses_mount(str(tmp / "link" / "f"), mountinfo=info)


def test_crosses_mount_never_widens(roots, tmp_path):
    tmp, _ = roots
    info = _mountinfo(tmp_path, "/", str(tmp / "b3"))
    target = str(tmp / "claude-grants" / "x.json")
    hts.crosses_mount(target, mountinfo=info)
    assert hts.is_harness_state(target)
    assert not hts.is_in_temp_root("/etc/passwd")


def test_crosses_mount_reads_the_real_mountinfo(roots):
    tmp, _ = roots
    if not os.path.exists(hts.MOUNTINFO_PATH):
        pytest.skip("no /proc/self/mountinfo on this platform")
    assert "/" in hts.mount_points()
    assert hts.crosses_mount(str(tmp / "x")) is False


def test_real_host_lets_plain_tmp_pass(monkeypatch):
    """On this host's real mountinfo and the real /tmp, /var/tmp, a plain temp path
    is not disqualified, so temp allows built on crosses_mount keep working."""
    if not os.path.exists(hts.MOUNTINFO_PATH):
        pytest.skip("no /proc/self/mountinfo on this platform")
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    assert hts.crosses_mount("/tmp/harness-temp-state-probe/x") is False
    assert hts.crosses_mount("/var/tmp/harness-temp-state-probe", below=True) is False


@pytest.fixture
def bind_mount(tmp_path):
    """Bind-mount a throwaway dir into the fake /tmp; skip where mounting is not permitted."""
    import shutil
    import subprocess
    if not (shutil.which("mount") and shutil.which("umount")) or not os.path.exists(hts.MOUNTINFO_PATH):
        pytest.skip("mount(8) or mountinfo unavailable")
    source = tmp_path / "outside-home"
    source.mkdir()
    (source / "settings.json").write_text("{}")
    target = tmp_path / "tmp" / "work" / "b3"
    target.mkdir(parents=True)
    done = subprocess.run(["mount", "--bind", str(source), str(target)],
                          capture_output=True, timeout=20)
    if done.returncode != 0:
        pytest.skip("bind mount not permitted here")
    try:
        yield target
    finally:
        subprocess.run(["umount", str(target)], capture_output=True, timeout=20)


def test_live_bind_mount_is_detected(roots, bind_mount):
    target = bind_mount
    # realpath sees nothing: the path resolves to itself.
    assert os.path.realpath(str(target / "settings.json")) == str(target / "settings.json")
    assert hts.is_in_temp_root(str(target / "settings.json"))
    assert hts.crosses_mount(str(target / "settings.json"))
    assert hts.crosses_mount(str(target))
    assert hts.crosses_mount(str(target.parent), below=True)   # rm -rf <tmp>/work
    assert not hts.crosses_mount(str(target.parent))
    assert not hts.crosses_mount(str(target.parent / "sibling"), below=True)
