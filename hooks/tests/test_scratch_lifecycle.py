"""Tests for the Scratch Lifecycle Contract (task 20260907-015935).

Covers:
  - AC2: hooks/session-scratch-init.sh registers <root>/<sid>/.owner with the
    documented fields (sid, pid, pid_start_time, boot_id, created_at).
  - AC3: hooks/sessionend-scratch-sweep.sh removes ONLY the own-session dir;
    a sibling dir with a live .owner survives byte-untouched.
  - AC4: scripts/install/tmpfiles-claude-scratch.conf ages entries on the
    mtime-only ("mM:") basis -- immune to fresh atime AND fresh ctime (ctime
    cannot be backdated by any user API; utimensat(2) sets only atime+mtime
    and itself bumps ctime).
  - AC7: an orphan session dir (aged beyond the 3d floor) is reaped by the
    same declarative rule while a live-owner dir (fresh mtime) survives.
  - AC9: scripts/install/tmpfiles-var-tmp-override.conf (30d) and the nested
    claude-scratch rule (3d) coexist in one clean pass without conflict.

All tests run against synthetic, sandboxed roots (tempfile.mkdtemp() under
$TMPDIR, or systemd-tmpfiles --root=<throwaway>) -- never against the real
/tmp, /var/tmp or /dev/shm/claude-tmp. Tests that need the systemd-tmpfiles
binary skip gracefully when it is absent (portability -- CI containers may
lack it).
"""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

HOOKS_DIR = Path(__file__).parent.parent
REPO_ROOT = HOOKS_DIR.parent
INSTALL_DIR = REPO_ROOT / "scripts" / "install"

SESSION_INIT_HOOK = HOOKS_DIR / "session-scratch-init.sh"
SESSION_SWEEP_HOOK = HOOKS_DIR / "sessionend-scratch-sweep.sh"
CLAUDE_SCRATCH_CONF = INSTALL_DIR / "tmpfiles-claude-scratch.conf"
VAR_TMP_OVERRIDE_CONF = INSTALL_DIR / "tmpfiles-var-tmp-override.conf"

SYSTEMD_TMPFILES = shutil.which("systemd-tmpfiles")


def _run_hook(hook_path, env_overrides):
    env = dict(os.environ)
    env.update(env_overrides)
    return subprocess.run(
        ["bash", str(hook_path)],
        input="{}",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _write_owner(path, sid, pid="1", pid_start_time="1", boot_id="test-boot-id"):
    path.mkdir(parents=True, exist_ok=True)
    with open(path / ".owner", "w") as fh:
        json.dump(
            {
                "sid": sid,
                "pid": pid,
                "pid_start_time": pid_start_time,
                "boot_id": boot_id,
                "created_at": "2026-09-07T00:00:00Z",
            },
            fh,
        )


def _file_hashes(root):
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            p = Path(dirpath) / name
            out[str(p.relative_to(root))] = p.read_bytes()
    return out


class SessionScratchInitTests(unittest.TestCase):
    """AC2."""

    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix="scratch-lifecycle-init-"))

    def test_registers_owner_with_documented_fields(self):
        result = _run_hook(
            SESSION_INIT_HOOK,
            {
                "TMPDIR": str(self.sandbox),
                "CLAUDE_CODE_SESSION_ID": "ac2-sid",
                "CLAUDE_PID": str(os.getpid()),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        owner_path = self.sandbox / "ac2-sid" / ".owner"
        self.assertTrue(owner_path.is_dir() is False and owner_path.exists())
        data = json.loads(owner_path.read_text())
        self.assertEqual(data["sid"], "ac2-sid")
        self.assertEqual(data["pid"], str(os.getpid()))
        self.assertTrue(data["boot_id"])
        self.assertTrue(data["pid_start_time"])
        self.assertTrue(data["created_at"])

    def test_rejects_unsafe_session_id(self):
        result = _run_hook(
            SESSION_INIT_HOOK,
            {
                "TMPDIR": str(self.sandbox),
                "CLAUDE_CODE_SESSION_ID": "../escape",
                "CLAUDE_PID": str(os.getpid()),
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertFalse((self.sandbox / ".." / "escape").resolve().exists())
        self.assertEqual(list(self.sandbox.iterdir()), [])


class SessionEndScratchSweepTests(unittest.TestCase):
    """AC3."""

    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(prefix="scratch-lifecycle-sweep-"))

    def test_removes_own_dir_sibling_survives_byte_untouched(self):
        own = self.sandbox / "own-sid"
        _write_owner(own, "own-sid")
        (own / "scratch.txt").write_text("own scratch content")

        sibling = self.sandbox / "sibling-sid"
        _write_owner(sibling, "sibling-sid", pid=str(os.getpid()))
        (sibling / "keep.txt").write_text("do not touch")
        before = _file_hashes(sibling)

        result = _run_hook(
            SESSION_SWEEP_HOOK,
            {"TMPDIR": str(self.sandbox), "CLAUDE_CODE_SESSION_ID": "own-sid"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(own.exists(), "own session dir must be removed")
        self.assertTrue(sibling.is_dir(), "sibling must survive")
        self.assertEqual(before, _file_hashes(sibling), "sibling bytes must be unchanged")

    def test_refuses_dir_with_no_owner_record(self):
        # Undecidable ownership (missing .owner) must leave the dir alone,
        # mirroring the "undecidable means leave alone" discipline of
        # hooks/stop-cleanup-allowlist.sh.
        target = self.sandbox / "no-owner-sid"
        target.mkdir(parents=True)
        result = _run_hook(
            SESSION_SWEEP_HOOK,
            {"TMPDIR": str(self.sandbox), "CLAUDE_CODE_SESSION_ID": "no-owner-sid"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue(target.exists())

    def test_refuses_sid_owner_mismatch(self):
        target = self.sandbox / "mismatched-sid"
        _write_owner(target, "someone-else")
        result = _run_hook(
            SESSION_SWEEP_HOOK,
            {"TMPDIR": str(self.sandbox), "CLAUDE_CODE_SESSION_ID": "mismatched-sid"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue(target.exists())


@unittest.skipUnless(SYSTEMD_TMPFILES, "systemd-tmpfiles binary not available")
class TmpfilesAgeByTests(unittest.TestCase):
    """AC4, AC7, AC9 -- sandboxed systemd-tmpfiles --root=<throwaway> --clean."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="scratch-lifecycle-tmpfiles-"))

    def _clean(self, *conf_paths):
        result = subprocess.run(
            [SYSTEMD_TMPFILES, f"--root={self.root}", "--clean"]
            + [str(p) for p in conf_paths],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result

    def test_ac4_aged_entry_removed_despite_fresh_atime_and_ctime(self):
        scratch = self.root / "var" / "tmp" / "claude-scratch"
        scratch.mkdir(parents=True)
        os.chmod(scratch, 0o1777)

        aged = scratch / "aged-entry"
        fresh = scratch / "fresh-entry"
        aged.touch()
        fresh.touch()
        # Backdate mtime ONLY (utimensat sets atime+mtime; we re-set atime to
        # now immediately after so it stays fresh; ctime is bumped to "now"
        # by the very act of calling touch and CANNOT be backdated by any
        # user API -- this is the condition AC4 requires).
        four_days_ago = time.time() - 4 * 86400
        os.utime(aged, (time.time(), four_days_ago))

        result = self._clean(CLAUDE_SCRATCH_CONF)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(aged.exists(), "aged entry (mM:3d) must be removed")
        self.assertTrue(fresh.exists(), "fresh entry must survive")

    def test_ac7_orphan_removed_live_owner_survives(self):
        scratch = self.root / "var" / "tmp" / "claude-scratch"
        scratch.mkdir(parents=True)
        os.chmod(scratch, 0o1777)

        orphan = scratch / "orphan-sid"
        _write_owner(orphan, "orphan-sid", pid="999999999", boot_id="stale-boot-id")
        live = scratch / "live-sid"
        _write_owner(live, "live-sid", pid=str(os.getpid()))

        # Sandbox aging constraint: backdate mtimes only, and the directory's
        # OWN mtime LAST (populating a dir bumps its mtime back to "now").
        # Content (.owner) must ALSO age -- a directory whose contents are
        # still fresh is not reaped by systemd-tmpfiles even if the
        # directory's own mtime is old.
        four_days_ago = time.time() - 4 * 86400
        os.utime(orphan / ".owner", (time.time(), four_days_ago))
        os.utime(orphan, (time.time(), four_days_ago))
        # live-sid is left fully fresh (simulates a still-running session).

        result = self._clean(CLAUDE_SCRATCH_CONF)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(orphan.exists(), "orphan dir must be reaped by the age floor")
        self.assertTrue(live.exists(), "live-owner dir must survive")

    def test_ac9_var_tmp_bound_and_nested_scratch_rule_coexist(self):
        var_tmp = self.root / "var" / "tmp"
        scratch = var_tmp / "claude-scratch"
        scratch.mkdir(parents=True)
        os.chmod(var_tmp, 0o1777)
        os.chmod(scratch, 0o1777)

        aged_vartmp = var_tmp / "aged-vartmp-entry"
        fresh_vartmp = var_tmp / "fresh-vartmp-entry"
        aged_vartmp.touch()
        fresh_vartmp.touch()
        os.utime(aged_vartmp, (time.time(), time.time() - 35 * 86400))

        aged_scratch = scratch / "aged-scratch-entry"
        fresh_scratch = scratch / "fresh-scratch-entry"
        aged_scratch.touch()
        fresh_scratch.touch()
        os.utime(aged_scratch, (time.time(), time.time() - 4 * 86400))

        result = self._clean(VAR_TMP_OVERRIDE_CONF, CLAUDE_SCRATCH_CONF)
        self.assertEqual(result.returncode, 0, result.stderr)

        self.assertFalse(aged_vartmp.exists(), "35d /var/tmp entry must be removed by the 30d bound")
        self.assertTrue(fresh_vartmp.exists())
        self.assertFalse(aged_scratch.exists(), "4d claude-scratch entry must be removed by the nested 3d rule")
        self.assertTrue(fresh_scratch.exists())


class CheckpointCoreTmpdirFallbackTests(unittest.TestCase):
    """AC8: hooks/lib/checkpoint-core.sh mktemp fallback honors ${TMPDIR}."""

    def test_no_literal_tmp_checkpoint_result_remains(self):
        source = (REPO_ROOT / "hooks" / "lib" / "checkpoint-core.sh").read_text()
        self.assertNotIn(
            '"/tmp/checkpoint-result',
            source,
            "hard-coded /tmp fallback must be gone",
        )
        self.assertIn("${TMPDIR:-/tmp}/checkpoint-result", source)

    def test_fallback_resolves_under_sandbox_tmpdir_when_mktemp_missing(self):
        sandbox = Path(tempfile.mkdtemp(prefix="scratch-lifecycle-checkpoint-"))
        # Exercise just the fallback expression in isolation (mirrors line
        # 435 of checkpoint-core.sh) with a PATH that hides mktemp, so the
        # `||` branch is what actually runs.
        script = (
            'result_file=$(mktemp 2>/dev/null || printf \'%s\' "${TMPDIR:-/tmp}/checkpoint-result.$$.ns")\n'
            'echo "$result_file"\n'
        )
        bash_path = shutil.which("bash") or "/usr/bin/bash"
        result = subprocess.run(
            [bash_path, "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "TMPDIR": str(sandbox), "PATH": "/nonexistent"},
            timeout=10,
        )
        self.assertTrue(result.stdout.strip().startswith(str(sandbox) + "/checkpoint-result."))


if __name__ == "__main__":
    unittest.main()
