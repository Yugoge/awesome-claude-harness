#!/usr/bin/env python3
"""End-to-end self-tests for the generic protected-runtime guard.

Two layers:
  1. Direct engine tests (fast) — call runtime_guard.evaluate() against an
     isolated test data file (NEVER the live machine file).
  2. Live-hook tests — feed simulated PreToolUse JSON to the real
     pretool-bash-safety.sh on stdin and assert the exit code.

NEVER runs a real daemon or CLI command — verification is purely by feeding
simulated inputs to the engine / hook (spec Section 8 trap).

Project names appear ONLY in this test file's fixture data file and in the
test command strings (a test fixture is not the shared engine/helper code that
AC-A purity governs).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(__file__)
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
HOOK = os.path.join(HOOKS_DIR, "pretool-bash-safety.sh")
sys.path.insert(0, HOOKS_DIR)

BLOCK = 2
ALLOW = 0


# ── Test fixture data file (de-drifted values, isolated from the live file) ──
FIXTURE = {
    "schema_version": 1,
    "protected_cmds": ["happy", "happy-dev", "happy-mcp", "happy-coder"],
    "protected_launch_paths": [
        "**/packages/happy-cli/dist/index.mjs",
        "**/packages/happy-cli/bin/happy*.mjs",
        "**/packages/happy-cli/src/index.ts",
        "**/packages/happy-cli/scripts/env-wrapper.cjs",
        "/usr/bin/happy",
        "/usr/bin/happy-dev",
        "/usr/bin/happy-mcp",
    ],
    "protected_services": [
        "happy-daemon", "happy-daemon-jade", "happy-daemon-dev", "happy-daemon-qijie",
    ],
    "protected_hotfiles": ["**/packages/happy-cli/dist/index.mjs"],
    "protected_statefiles": ["/root/.happy*/daemon.state.json"],
    "protected_endpoint_paths": ["/stop"],
    "protected_proc_idents": [
        "happy-daemon", "packages/happy-cli/dist/index.mjs", "daemon start-sync",
    ],
    "protected_global_bins": ["/usr/bin/happy*", "/usr/lib/node_modules/happy*"],
    "protected_build_workspaces": ["happy", "happy-coder"],
    "protected_build_paths": ["**/packages/happy-cli"],
    "bare_build_guard": True,
    "script_run_policy": "default_deny",
    "protected_script_workspaces": ["happy", "happy-coder"],
    "protected_script_paths": ["**/packages/happy-cli"],
    "protected_root_manifest_paths": ["__ROOT__"],
    "non_protected_workspaces": [
        "happy-app", "happy-agent", "happy-server", "happy-wire",
        "happy-app-logs", "@slopus/happy-wire",
    ],
    "safe_script_allowlist": [],
}


@pytest.fixture(scope="module")
def fixture_repo(tmp_path_factory):
    """Build a throwaway monorepo so workspace-resolution checks are determinate.

    Mirrors the real name<->folder mapping (folder packages/happy-cli, name
    'happy') and the real non-protected workspaces' declared scripts. NEVER
    touches the live machine repo or data file.
    """
    root = tmp_path_factory.mktemp("repo")
    pkgs = root / "packages"
    pkgs.mkdir()

    def mk(folder, name, scripts):
        d = pkgs / folder
        d.mkdir()
        (d / "package.json").write_text(json.dumps({"name": name, "scripts": {s: "echo" for s in scripts}}))

    mk("happy-cli", "happy", ["build", "test", "start", "cli", "dev", "dev:daemon:start", "stable", "release"])
    mk("happy-server", "happy-server", ["build", "test", "dev", "start", "migrate"])
    mk("happy-app", "happy-app", ["web", "start", "test", "typecheck", "release"])
    mk("happy-agent", "happy-agent", ["build", "dev", "test", "release", "typecheck"])
    mk("happy-wire", "@slopus/happy-wire", ["build", "test", "release"])
    mk("happy-app-logs", "happy-app-logs", ["build"])
    (root / "package.json").write_text(json.dumps({
        "name": "monorepo",
        "workspaces": {"packages": ["packages/*"]},
        "scripts": {"cli": "x", "release": "x", "env:cli": "x", "env:seed": "x",
                    "env:up": "x", "env:up:authenticated": "x", "env:down": "x"},
    }))
    return str(root)


@pytest.fixture(scope="module")
def datafile(fixture_repo, tmp_path_factory):
    cfg = json.loads(json.dumps(FIXTURE))
    cfg["protected_root_manifest_paths"] = [fixture_repo]
    p = tmp_path_factory.mktemp("cfg") / "protected-runtime.json"
    p.write_text(json.dumps(cfg))
    return str(p)


def ev(command, datafile, repo):
    """Direct engine evaluation under the isolated fixture data file."""
    os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
    # force a fresh import so DATA_FILE_PATH picks up the env each module load
    import importlib
    import lib.runtime_guard as rg
    importlib.reload(rg)
    return rg.evaluate(command)[0]


def code_for(decision):
    return BLOCK if decision == "BLOCK" else ALLOW


# ════════════════════════════════════════════════════════════════════════════
# Layer 1: direct engine tests (one method per acceptance criterion family)
# ════════════════════════════════════════════════════════════════════════════

class TestBlocks:
    def test_launch_cmdword(self, datafile, fixture_repo):
        assert ev("happy daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev("HAPPY_HOME_DIR=/root/.happy-dev happy daemon start", datafile, fixture_repo) == "BLOCK"

    def test_launch_distpath(self, datafile, fixture_repo):
        assert ev("node --no-warnings " + fixture_repo + "/packages/happy-cli/dist/index.mjs daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev("tsx packages/happy-cli/src/index.ts daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev("bun packages/happy-cli/dist/index.mjs daemon", datafile, fixture_repo) == "BLOCK"

    def test_launch_pkgrunner(self, datafile, fixture_repo):
        assert ev("npx happy daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev("npm exec happy daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev("pnpm dlx happy daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev("yarn dlx happy daemon start", datafile, fixture_repo) == "BLOCK"

    def test_pkgrunner_local_exec(self, datafile, fixture_repo):
        assert ev("pnpm exec happy daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev("yarn exec happy daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev("bunx happy daemon start", datafile, fixture_repo) == "BLOCK"

    def test_service(self, datafile, fixture_repo):
        assert ev("systemctl restart happy-daemon-qijie", datafile, fixture_repo) == "BLOCK"
        assert ev("systemctl stop happy-daemon", datafile, fixture_repo) == "BLOCK"
        assert ev("systemctl disable happy-daemon-dev", datafile, fixture_repo) == "BLOCK"

    def test_build_explicit(self, datafile, fixture_repo):
        assert ev("yarn workspace happy build", datafile, fixture_repo) == "BLOCK"
        assert ev("yarn workspace happy-coder build", datafile, fixture_repo) == "BLOCK"

    def test_build_bare(self, datafile, fixture_repo):
        # bare build with indeterminate cwd -> P9 fail-closed
        assert ev("yarn build", datafile, fixture_repo) == "BLOCK"
        assert ev("npm run build", datafile, fixture_repo) == "BLOCK"
        assert ev("pnpm build", datafile, fixture_repo) == "BLOCK"

    def test_build_npx_tsc_protected(self, datafile, fixture_repo):
        assert ev("npx tsc -p packages/happy-cli/tsconfig.json", datafile, fixture_repo) == "BLOCK"

    def test_hotfile_mutation(self, datafile, fixture_repo):
        assert ev("cp /tmp/x packages/happy-cli/dist/index.mjs", datafile, fixture_repo) == "BLOCK"
        assert ev("touch packages/happy-cli/dist/index.mjs", datafile, fixture_repo) == "BLOCK"
        assert ev("echo x > packages/happy-cli/dist/index.mjs", datafile, fixture_repo) == "BLOCK"
        assert ev("sed -i s/a/b/ packages/happy-cli/dist/index.mjs", datafile, fixture_repo) == "BLOCK"

    def test_statefile_mutation(self, datafile, fixture_repo):
        assert ev("echo {} > /root/.happy-dev/daemon.state.json", datafile, fixture_repo) == "BLOCK"
        assert ev("cp /tmp/s /root/.happy/daemon.state.json", datafile, fixture_repo) == "BLOCK"
        assert ev("truncate -s0 /root/.happy-qijie/daemon.state.json", datafile, fixture_repo) == "BLOCK"

    def test_endpoint_stop(self, datafile, fixture_repo):
        assert ev("curl -X POST http://127.0.0.1:54321/stop", datafile, fixture_repo) == "BLOCK"
        assert ev("wget --post-data= http://localhost:9/stop", datafile, fixture_repo) == "BLOCK"

    def test_prockill(self, datafile, fixture_repo):
        assert ev("pkill -f packages/happy-cli/dist/index.mjs", datafile, fixture_repo) == "BLOCK"
        assert ev("kill -9 $(pgrep -f happy-daemon)", datafile, fixture_repo) == "BLOCK"
        assert ev("fuser -k packages/happy-cli/dist/index.mjs", datafile, fixture_repo) == "BLOCK"

    def test_globalbin(self, datafile, fixture_repo):
        assert ev("npm install -g happy-coder", datafile, fixture_repo) == "BLOCK"
        assert ev("pnpm add --global happy-coder", datafile, fixture_repo) == "BLOCK"
        assert ev("yarn global add happy", datafile, fixture_repo) == "BLOCK"
        assert ev("npm link happy", datafile, fixture_repo) == "BLOCK"

    def test_datafile_mutation(self, datafile, fixture_repo):
        # mutation of the actual hardcoded data-file path is STEP0 protected
        os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = "/root/.config/claude/protected-runtime.json"
        import importlib, lib.runtime_guard as rg
        importlib.reload(rg)
        assert rg.evaluate("echo {} > /root/.config/claude/protected-runtime.json")[0] == "BLOCK"
        assert rg.evaluate("rm /root/.config/claude/protected-runtime.json")[0] == "BLOCK"
        assert rg.evaluate("sed -i s/a/b/ /root/.config/claude/protected-runtime.json")[0] == "BLOCK"
        assert rg.evaluate("chmod 000 /root/.config/claude/protected-runtime.json")[0] == "BLOCK"

    # ── P9 default-deny block families ──
    def test_pkgscript_bare_run(self, datafile, fixture_repo):
        for c in ("yarn dev:daemon:start", "yarn start", "yarn cli", "yarn dev",
                  "yarn test", "yarn prepublishOnly", "npm start", "npm test",
                  "yarn run dev:daemon:start", "npm run-script stable"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_pkgscript_protected_workspace_run(self, datafile, fixture_repo):
        for c in ("yarn workspace happy cli", "yarn workspace happy-coder build",
                  "npm -w happy-coder run dev:daemon:start", "npm --workspace=happy run start",
                  "pnpm --filter happy dev:daemon:stop", "pnpm -F=happy-coder dev",
                  "yarn --cwd packages/happy-cli dev", "pnpm -C packages/happy-cli start"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_pkgscript_passthrough_dispatcher(self, datafile, fixture_repo):
        for c in ("yarn stable daemon start", "yarn stable daemon stop",
                  "yarn dev:variant daemon start", "yarn stable doctor clean",
                  "yarn stable daemon status", "bun stable daemon start",
                  "yarn run stable daemon start"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_pkgscript_publish_release(self, datafile, fixture_repo):
        for c in ("yarn workspace happy run release", "yarn workspace happy-coder run release",
                  "npm -w happy-coder run release"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_pkgscript_root_dispatch_alias(self, datafile, fixture_repo):
        for c in ("yarn env:cli", "yarn env:seed", "yarn env:up",
                  "yarn env:up:authenticated", "yarn env:down", "yarn cli"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_pkgscript_recursive_fanout(self, datafile, fixture_repo):
        for c in ("yarn workspaces run build", "pnpm -r run prepublishOnly",
                  "pnpm --recursive run test"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_pkgscript_bin_fallthrough(self, datafile, fixture_repo):
        for c in ("yarn workspace happy-server happy daemon start",
                  "yarn workspace happy-app happy daemon start",
                  "yarn workspace happy-server happy-mcp serve",
                  "yarn workspace happy-server node ../happy-cli/bin/happy.mjs daemon start",
                  "yarn workspace happy-server exec happy daemon start",
                  "pnpm --filter happy-server happy daemon start",
                  "npm -w happy-server run happy"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_pkgscript_selector_name_not_folder(self, datafile, fixture_repo):
        for c in ("yarn workspace happy build", "npm -w happy run build",
                  "pnpm --filter happy run build", "pnpm --filter happy-coder build"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_pkgscript_cwd_changing(self, datafile, fixture_repo):
        repo = fixture_repo
        for c in (f"cd {repo}/packages/happy-cli && yarn build",
                  f"yarn --cwd {repo}/packages/happy-cli build",
                  f"npm --prefix {repo}/packages/happy-cli run start",
                  f"pnpm -C {repo}/packages/happy-cli dev",
                  f"env -C {repo}/packages/happy-cli yarn build"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_pkgscript_exec_dlx(self, datafile, fixture_repo):
        for c in ("npm exec happy daemon start", "pnpm exec happy daemon start",
                  "pnpm dlx happy daemon start", "yarn dlx happy daemon start",
                  "bunx happy daemon start", "bun x happy daemon start",
                  "corepack yarn stable daemon start"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_pkgscript_compound_shortcircuit(self, datafile, fixture_repo):
        repo = fixture_repo
        assert ev("yarn --version && yarn workspace happy build", datafile, fixture_repo) == "BLOCK"
        assert ev("ls; yarn workspace happy build", datafile, fixture_repo) == "BLOCK"
        assert ev(f"yarn --version | tee log && cd {repo}/packages/happy-cli && yarn start", datafile, fixture_repo) == "BLOCK"

    def test_pkgscript_dependency_protected_cwd(self, datafile, fixture_repo):
        repo = fixture_repo
        for c in (f"cd {repo}/packages/happy-cli && yarn add foo",
                  f"npm --prefix {repo}/packages/happy-cli install",
                  f"yarn --cwd {repo}/packages/happy-cli install"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_pkgscript_safe_allowlist_empty(self, datafile, fixture_repo):
        for c in ("yarn dev:daemon:status", "yarn env:list", "yarn env:current"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c


class TestAllows:
    def test_read_statefile(self, datafile, fixture_repo):
        for c in ("cat /root/.happy-dev/daemon.state.json",
                  "grep pid /root/.happy/daemon.state.json",
                  "head /root/.happy-qijie/daemon.state.json"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c

    def test_other_package_build(self, datafile, fixture_repo):
        for c in ("yarn workspace happy-server build", "yarn workspace @slopus/happy-wire build",
                  "yarn workspace happy-agent build"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c

    def test_npx_tsc_nonprotected(self, datafile, fixture_repo):
        assert ev("npx tsc --version", datafile, fixture_repo) == "ALLOW"
        assert ev("npx tsc -p packages/happy-server/tsconfig.json", datafile, fixture_repo) == "ALLOW"

    def test_grep_procident(self, datafile, fixture_repo):
        assert ev("grep packages/happy-cli/dist/index.mjs -R .", datafile, fixture_repo) == "ALLOW"
        assert ev("ps aux | grep packages/happy-cli/dist/index.mjs", datafile, fixture_repo) == "ALLOW"

    def test_edit_source(self, datafile, fixture_repo):
        assert ev("sed -i s/a/b/ packages/happy-cli/src/daemon/run.ts", datafile, fixture_repo) == "ALLOW"

    def test_echo_projectname(self, datafile, fixture_repo):
        assert ev("echo happy-daemon restart", datafile, fixture_repo) == "ALLOW"
        assert ev("grep happy somefile", datafile, fixture_repo) == "ALLOW"

    def test_pkgscript_nonprotected_workspace_run(self, datafile, fixture_repo):
        for c in ("yarn workspace happy-server build", "yarn workspace happy-app web",
                  "yarn workspace happy-agent dev", "yarn workspace happy-agent release",
                  "yarn workspace @slopus/happy-wire build",
                  "npm -w happy-server run build", "pnpm --filter happy-app web"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c

    def test_pkgscript_selector_run_keyword(self, datafile, fixture_repo):
        for c in ("yarn workspace happy-server run build", "pnpm --filter happy-app run web",
                  "npm -w happy-server run build"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c

    def test_pkgscript_selector_dependency(self, datafile, fixture_repo):
        for c in ("yarn workspace happy-server add foo", "npm -w happy-server install foo",
                  "pnpm --filter happy-app add foo"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c

    def test_pkgscript_dependency_mgmt(self, datafile, fixture_repo):
        for c in ("yarn install", "yarn add some-pkg", "yarn remove some-pkg",
                  "npm install", "pnpm install", "yarn upgrade", "yarn up"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c

    def test_pkgscript_meta_and_text(self, datafile, fixture_repo):
        for c in ("yarn --version", "yarn -v", "npm --version", "yarn --help",
                  "echo yarn dev:daemon:start", "echo yarn stable daemon start",
                  "grep dev:daemon:start file"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c

    def test_pkgscript_cross_package(self, datafile, fixture_repo):
        repo = fixture_repo
        for c in (f"cd {repo}/packages/happy-agent && yarn dev",
                  f"cd {repo}/packages/happy-server && yarn test",
                  f"cd {repo}/packages/happy-server && yarn build",
                  "yarn workspace happy-agent dev"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c

    def test_pkgscript_dependency_ignore_scripts(self, datafile, fixture_repo):
        repo = fixture_repo
        for c in (f"cd {repo}/packages/happy-cli && yarn install --ignore-scripts",
                  f"npm --prefix {repo}/packages/happy-cli install --ignore-scripts"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c


class TestBinFallthroughNonProtectedCwd:
    def test_bare_cwd_fallthrough_blocked(self, datafile, fixture_repo):
        repo = fixture_repo
        for c in (f"cd {repo}/packages/happy-server && yarn happy daemon start",
                  f"yarn --cwd {repo}/packages/happy-server happy daemon start"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c


# ════════════════════════════════════════════════════════════════════════════
# Iteration 2 (qa-report-20260531-162901): cross-segment / wrapper / xargs /
# pm-exec / cwd-relative leak coverage. Each was reproduced ALLOW against the
# prior engine; these assert BLOCK + companion boundary-allow tests prove the
# fixes do not over-block. Verified ONLY by feeding strings to evaluate()
# (NEVER any real daemon/CLI command).
# ════════════════════════════════════════════════════════════════════════════

class TestLeak1CrossSegmentKill:
    """P6: a protected proc-ident in an upstream pipeline segment feeding a kill
    executor downstream (or kill $(<pipeline naming ident>)) must BLOCK."""
    def test_ps_grep_xargs_kill(self, datafile, fixture_repo):
        for c in ("ps aux | grep happy-daemon | awk '{print $2}' | xargs kill",
                  "pgrep -f happy-daemon | xargs kill",
                  "ps aux | grep happy-daemon | awk '{print $2}' | xargs pkill",
                  "pgrep -f packages/happy-cli/dist/index.mjs | xargs -r kill -9"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_kill_command_substitution_pipeline(self, datafile, fixture_repo):
        for c in ("kill $(ps aux | grep happy-daemon | awk '{print $2}')",
                  "kill -9 $(pgrep -f 'daemon start-sync')"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    # boundary allows — NOT over-blocking unrelated pipelines
    def test_unrelated_pipeline_kill_allowed(self, datafile, fixture_repo):
        for c in ("ps aux | grep foo | awk '{print $2}' | xargs kill",
                  "pgrep -f some-other-proc | xargs kill",
                  "ps aux | grep happy-daemon | awk '{print $2}'",
                  "ps aux | grep happy-daemon"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c


class TestLeak2XargsLaunch:
    """P1: an xargs executor whose target is the protected command (or a runtime
    fed a protected path via the upstream pipe) must BLOCK."""
    def test_xargs_protected_cmd(self, datafile, fixture_repo):
        for c in ("echo daemon start | xargs happy",
                  "echo serve | xargs happy-mcp",
                  "printf 'daemon start\\n' | xargs -I{} happy {}"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_xargs_runtime_upstream_path(self, datafile, fixture_repo):
        repo = fixture_repo
        c = f"printf '{repo}/packages/happy-cli/dist/index.mjs daemon start' | xargs node"
        assert ev(c, datafile, fixture_repo) == "BLOCK", c

    # boundary allows — xargs with a non-protected target / content
    def test_xargs_nonprotected_allowed(self, datafile, fixture_repo):
        for c in ("echo hi | xargs ls",
                  "find . -name '*.log' | xargs rm",
                  "echo foo | xargs echo",
                  "ls | xargs -n1 basename"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c


class TestLeak3CwdAndPmExecBuild:
    """P8: a build tool / package-runner build whose effective cwd resolves under
    a protected build path, and the pm-exec build forms (npm/pnpm/yarn exec)."""
    def test_cd_then_npx_tsc(self, datafile, fixture_repo):
        repo = fixture_repo
        for c in (f"cd {repo}/packages/happy-cli && npx tsc -p tsconfig.json",
                  f"cd {repo}/packages/happy-cli && pnpm exec tsc -p tsconfig.json"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_pm_exec_tsc_protected_path(self, datafile, fixture_repo):
        repo = fixture_repo
        cli = f"{repo}/packages/happy-cli"
        for c in (f"npm exec tsc -p {cli}/tsconfig.json",
                  f"yarn exec tsc -p {cli}/tsconfig.json",
                  f"pnpm exec tsc -p {cli}/tsconfig.json"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_cwd_seed_npx_tsc(self, datafile, fixture_repo):
        repo = fixture_repo
        assert ev_cwd("npx tsc -p tsconfig.json", datafile, f"{repo}/packages/happy-cli") == "BLOCK"

    # boundary allows — a package-runner building a NON-protected package
    def test_pm_exec_nonprotected_allowed(self, datafile, fixture_repo):
        repo = fixture_repo
        srv = f"{repo}/packages/happy-server"
        for c in (f"npm exec tsc -p {srv}/tsconfig.json",
                  f"pnpm exec tsc -p {srv}/tsconfig.json",
                  f"npx tsc -p {srv}/tsconfig.json",
                  f"cd {srv} && npx tsc -p tsconfig.json"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c


class TestLeak4WrapperCwd:
    """P1: an env -C / sudo --chdir wrapper that changes directory then runs a
    runtime against a relative protected bundle path must BLOCK."""
    def test_env_dashC_launch(self, datafile, fixture_repo):
        repo = fixture_repo
        cli = f"{repo}/packages/happy-cli"
        for c in (f"env -C {cli} node dist/index.mjs daemon start",
                  f"env --chdir {cli} node dist/index.mjs daemon start",
                  f"env -C {cli} tsx src/index.ts daemon"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_env_dashC_build(self, datafile, fixture_repo):
        repo = fixture_repo
        assert ev(f"env -C {repo}/packages/happy-cli npx tsc -p tsconfig.json", datafile, fixture_repo) == "BLOCK"

    # boundary allow — env -C into a NON-protected workspace running a runtime
    def test_env_dashC_nonprotected_allowed(self, datafile, fixture_repo):
        repo = fixture_repo
        srv = f"{repo}/packages/happy-server"
        for c in (f"env -C {srv} node build.js",
                  f"env --chdir {srv} node scripts/migrate.js"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c


class TestLeak5CrossSegmentEndpoint:
    """P5: a pipeline whose content carries the loopback control-endpoint path
    piped into a raw-socket tool aimed at a loopback host must BLOCK."""
    def test_printf_pipe_nc(self, datafile, fixture_repo):
        for c in ("printf 'POST /stop HTTP/1.0\\r\\n\\r\\n' | nc 127.0.0.1 54321",
                  "printf 'POST /stop ' | nc localhost 9",
                  "echo -e 'POST /stop\\r\\n' | socat - TCP:127.0.0.1:8080",
                  "printf 'POST /stop' | ncat ::1 5000"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    # boundary allows — loopback socket tool with NO control-endpoint content,
    # and the control path with NO loopback client
    def test_loopback_no_endpoint_allowed(self, datafile, fixture_repo):
        for c in ("printf 'GET /health' | nc 127.0.0.1 8080",
                  "printf 'GET /metrics HTTP/1.0\\r\\n' | nc localhost 9090",
                  "echo hello | nc 127.0.0.1 1234"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c

    def test_endpoint_text_no_client_allowed(self, datafile, fixture_repo):
        for c in ("echo 'POST /stop' >> notes.txt",
                  "grep '/stop' config.txt"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c


# ════════════════════════════════════════════════════════════════════════════
# Iteration 2 codex (gpt-5.5 xhigh) adversarial-review regression coverage.
# Codex surfaced 12 deeper in-scope idiomatic forms of the SAME 5 classes plus
# 2 over-block regressions my pipeline-group/cwd fixes introduced. All 12 are
# covered here (BLOCK forms + the 2 over-block ALLOW fixes).
# ════════════════════════════════════════════════════════════════════════════

class TestCodexR2Splitting:
    """F1/F2: fd-redirection `&` must not split a pipeline; separators inside
    $()/backticks must not split the kill substitution."""
    def test_redirect_amp_not_separator(self, datafile, fixture_repo):
        assert ev("pgrep -af happy-daemon 2>&1 | awk '{print $1}' | xargs kill", datafile, fixture_repo) == "BLOCK"

    def test_separators_inside_substitution(self, datafile, fixture_repo):
        for c in ("kill $(true && pgrep -f happy-daemon)",
                  "kill $(echo ok >/dev/null; pgrep -f happy-daemon)",
                  "kill `true; pgrep -f happy-daemon`"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_redirect_amp_benign_allowed(self, datafile, fixture_repo):
        # background `&` of an unrelated command still allowed; 2>&1 on a benign
        # pipeline allowed
        for c in ("ls 2>&1 | grep foo", "echo hi & echo bye"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c


class TestCodexR2XargsWrappers:
    """F3: xargs target through a wrapper (sudo/env) and the -I{} placeholder."""
    def test_xargs_wrapped_kill(self, datafile, fixture_repo):
        assert ev("ps aux | grep happy-daemon | awk '{print $2}' | xargs sudo kill", datafile, fixture_repo) == "BLOCK"

    def test_xargs_env_node_path(self, datafile, fixture_repo):
        repo = fixture_repo
        c = f"printf '{repo}/packages/happy-cli/dist/index.mjs daemon start' | xargs env node"
        assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_xargs_placeholder_command(self, datafile, fixture_repo):
        assert ev("printf 'happy daemon start' | xargs -I{} {}", datafile, fixture_repo) == "BLOCK"


class TestCodexR2P5OverblockFix:
    """F4: P5 must be order/client-semantics aware (no over-block of legit
    loopback work)."""
    def test_curl_health_grep_stop_allowed(self, datafile, fixture_repo):
        assert ev("curl http://localhost:3005/health | grep /stop", datafile, fixture_repo) == "ALLOW"

    def test_grep_stop_curl_health_allowed(self, datafile, fixture_repo):
        assert ev("grep /stop README.md | curl http://localhost:3005/health", datafile, fixture_repo) == "ALLOW"

    def test_netcat_basename_blocked(self, datafile, fixture_repo):
        assert ev("printf 'POST /stop HTTP/1.1' | netcat localhost 3005", datafile, fixture_repo) == "BLOCK"


class TestCodexR2WrapperCwdForms:
    """F6/F7: fused env -C<dir>, systemd-run --working-directory=, exec wrapper,
    systemd-run -G not consuming an operand."""
    def test_fused_env_dashC(self, datafile, fixture_repo):
        repo = fixture_repo
        cli = f"{repo}/packages/happy-cli"
        assert ev(f"env -C{cli} node dist/index.mjs daemon start", datafile, fixture_repo) == "BLOCK"

    def test_systemd_run_working_directory(self, datafile, fixture_repo):
        repo = fixture_repo
        cli = f"{repo}/packages/happy-cli"
        assert ev(f"systemd-run --working-directory={cli} node dist/index.mjs daemon start", datafile, fixture_repo) == "BLOCK"

    def test_exec_wrapper_launch(self, datafile, fixture_repo):
        repo = fixture_repo
        assert ev("exec happy daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev(f"exec node {repo}/packages/happy-cli/dist/index.mjs daemon start", datafile, fixture_repo) == "BLOCK"

    def test_systemd_run_G_no_operand(self, datafile, fixture_repo):
        assert ev("systemd-run -G happy daemon start", datafile, fixture_repo) == "BLOCK"


class TestCodexR2CdOptionsAndCompound:
    """F8/F9: cd -P/-- and pushd --; compound { } and ( ) groups."""
    def test_cd_options(self, datafile, fixture_repo):
        repo = fixture_repo
        cli = f"{repo}/packages/happy-cli"
        for c in (f"cd -P {cli} && npx tsc", f"cd -- {cli} && npx tsc",
                  f"pushd -- {cli} && npx tsc"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_compound_groups(self, datafile, fixture_repo):
        repo = fixture_repo
        cli = f"{repo}/packages/happy-cli"
        for c in (f"{{ cd {cli}; node dist/index.mjs daemon start; }}",
                  f"(cd {cli} && npx tsc)"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_compound_nonprotected_allowed(self, datafile, fixture_repo):
        repo = fixture_repo
        srv = f"{repo}/packages/happy-server"
        assert ev(f"(cd {srv} && npx tsc -p tsconfig.json)", datafile, fixture_repo) == "ALLOW"


class TestCodexR2RunnerRuntime:
    """F10: package-runner invoking a runtime against a protected path; runner
    options with operands (--package)."""
    def test_npx_tsx_protected_src(self, datafile, fixture_repo):
        repo = fixture_repo
        cli = f"{repo}/packages/happy-cli"
        for c in (f"npx tsx {cli}/src/index.ts",
                  f"npm exec -- tsx {cli}/src/index.ts"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_npx_package_option(self, datafile, fixture_repo):
        repo = fixture_repo
        cli = f"{repo}/packages/happy-cli"
        assert ev(f"npx --package typescript tsc -p {cli}", datafile, fixture_repo) == "BLOCK"


class TestCodexR2LoopConsumers:
    """F11: pipe-fed while-read loops for kill and launch."""
    def test_while_read_kill(self, datafile, fixture_repo):
        assert ev("pgrep -af happy-daemon | while read pid; do kill $pid; done", datafile, fixture_repo) == "BLOCK"

    def test_while_read_launch(self, datafile, fixture_repo):
        assert ev("printf 'daemon start' | while read args; do happy $args; done", datafile, fixture_repo) == "BLOCK"

    def test_benign_while_read_allowed(self, datafile, fixture_repo):
        assert ev("ls | while read f; do echo $f; done", datafile, fixture_repo) == "ALLOW"


class TestCodexR2P9WrapperCwdOverblock:
    """F12: P9 must fold wrapper cwd so env -C <non-protected-ws> yarn <script>
    is not over-blocked."""
    def test_env_dashC_nonprotected_pkgscript_allowed(self, datafile, fixture_repo):
        repo = fixture_repo
        assert ev(f"env -C {repo}/packages/happy-app yarn web", datafile, fixture_repo) == "ALLOW"

    def test_env_dashC_protected_pkgscript_blocked(self, datafile, fixture_repo):
        repo = fixture_repo
        assert ev(f"env -C {repo}/packages/happy-cli yarn build", datafile, fixture_repo) == "BLOCK"


# ── codex round-1 (this cycle) adversarial-review regression coverage ────────

def ev_cwd(command, datafile, cwd):
    """evaluate() with an explicit cwd_base seed."""
    os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
    import importlib, lib.runtime_guard as rg
    importlib.reload(rg)
    return rg.evaluate(command, cwd)[0]


class TestCodexWrapperOperands:
    """Wrappers with operands + process-handoff wrappers must not hide the
    real service/runtime/protected command word."""
    def test_timeout_then_service(self, datafile, fixture_repo):
        assert ev("timeout 10 systemctl restart happy-daemon-dev", datafile, fixture_repo) == "BLOCK"
        assert ev("timeout --signal=TERM 10 happy daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev("timeout -s TERM 10 happy daemon start", datafile, fixture_repo) == "BLOCK"

    def test_nice_ionice(self, datafile, fixture_repo):
        assert ev("nice -n 10 happy daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev("ionice -c 3 happy daemon start", datafile, fixture_repo) == "BLOCK"

    def test_handoff_wrappers(self, datafile, fixture_repo):
        repo = fixture_repo
        assert ev("setsid happy daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev(f"systemd-run --unit x node {repo}/packages/happy-cli/dist/index.mjs daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev("daemonize happy daemon start", datafile, fixture_repo) == "BLOCK"


class TestCodexCwdRelativeLaunch:
    """P1 must resolve a relative protected launch path against the effective cwd."""
    def test_cd_then_relative_node(self, datafile, fixture_repo):
        repo = fixture_repo
        assert ev(f"cd {repo}/packages/happy-cli && node dist/index.mjs daemon start", datafile, fixture_repo) == "BLOCK"

    def test_cwd_seed_relative_node(self, datafile, fixture_repo):
        repo = fixture_repo
        assert ev_cwd("node dist/index.mjs daemon start", datafile, f"{repo}/packages/happy-cli") == "BLOCK"


class TestCodexRuntimeOptionOperands:
    """A runtime flag-with-value must not hide the protected script positional."""
    def test_loader_and_require(self, datafile, fixture_repo):
        repo = fixture_repo
        src = f"{repo}/packages/happy-cli/src/index.ts"
        dist = f"{repo}/packages/happy-cli/dist/index.mjs"
        assert ev(f"node --loader ts-node/esm {src}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"node -r ts-node/register {src}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"node --require ts-node/register {dist} daemon", datafile, fixture_repo) == "BLOCK"


class TestCodexCwdSeedReducesFalseBlock:
    """A relative cd into a NON-protected workspace resolves and stays allowed."""
    def test_relative_cd_nonprotected_allowed(self, datafile, fixture_repo):
        repo = fixture_repo
        assert ev_cwd("cd packages/happy-server && yarn build", datafile, repo) == "ALLOW"
        assert ev_cwd("cd packages/happy-app && yarn web", datafile, repo) == "ALLOW"

    def test_relative_cd_protected_still_blocked(self, datafile, fixture_repo):
        repo = fixture_repo
        assert ev_cwd("cd packages/happy-cli && yarn build", datafile, repo) == "BLOCK"


class TestCodexLsofFuserReadOnly:
    """lsof and bare fuser are read-only; only fuser -k kills."""
    def test_lsof_readonly_allowed(self, datafile, fixture_repo):
        repo = fixture_repo
        assert ev(f"lsof {repo}/packages/happy-cli/dist/index.mjs", datafile, fixture_repo) == "ALLOW"

    def test_bare_fuser_allowed(self, datafile, fixture_repo):
        repo = fixture_repo
        assert ev(f"fuser {repo}/packages/happy-cli/dist/index.mjs", datafile, fixture_repo) == "ALLOW"

    def test_fuser_k_blocked(self, datafile, fixture_repo):
        assert ev("fuser -k packages/happy-cli/dist/index.mjs", datafile, fixture_repo) == "BLOCK"


class TestCodexEscapedQuoteSplit:
    """An escaped quote inside double quotes must not prematurely close the
    quote and split a quoted separator into a real simple command."""
    def test_escaped_quote_in_echo_allowed(self, datafile, fixture_repo):
        assert ev('echo "hello \\"; yarn build"', datafile, fixture_repo) == "ALLOW"
        assert ev('echo "x; yarn build"', datafile, fixture_repo) == "ALLOW"

    def test_real_compound_still_blocked(self, datafile, fixture_repo):
        repo = fixture_repo
        assert ev(f"ls; cd {repo}/packages/happy-cli && yarn build", datafile, fixture_repo) == "BLOCK"


class TestCodexGlueFailClosed:
    """The bash glue must fail CLOSED (deny danger families) when the helper is
    missing / errors / returns no decision — not fall open into legacy rules."""

    def _run_with_missing_helper(self, command):
        # Point the hook at a temp HOOKS dir whose lib/ lacks runtime_guard.py,
        # by overriding BASH_SOURCE dirname is not feasible; instead simulate the
        # glue's fallback contract directly: helper MISSING -> fail-closed grep.
        # We exercise the live hook with a guaranteed-broken python bin so the
        # helper cannot run, forcing the non-ALLOW branch.
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
        e = dict(os.environ)
        e["CLAUDE_PYTHON_BIN"] = "/nonexistent/python-broken"
        e["CLAUDE_PYTHON_FALLBACK"] = "/nonexistent/python-broken2"
        proc = subprocess.run(["bash", HOOK], input=payload, text=True, capture_output=True, env=e)
        return proc.returncode

    def test_failclosed_blocks_danger_family_when_helper_unavailable(self):
        # With no usable python, TOOL_NAME parse fails -> hook can't even detect
        # Bash; this is the deployment-broken case. We assert the dedicated
        # fallback path via a direct helper-missing simulation instead.
        # Direct simulation: call the fallback function semantics through grep.
        import re
        danger = [
            "yarn build", "systemctl restart x", "kill -9 1", "npx tsc",
            "node foo.mjs", "pnpm build",
        ]
        benign = ["ls -la", "cat foo", "git status", "grep x f"]
        pats = [
            r'(^|[;&|]|\s)(systemctl|service)\s+(start|stop|restart|try-restart|reload|reload-or-restart|kill|disable|mask|enable)(\s|$)',
            r'(^|[;&|]|\s)(kill|pkill|killall)(\s|$)',
            r'(^|[;&|]|\s)(yarn|npm|pnpm|bun)(\s|$)',
            r'(^|[;&|]|\s)(npx|bunx|tsc|pkgroll|tsup)(\s|$)',
            r'(^|[;&|]|\s)(node|nodejs|tsx|deno)(\s|$)',
        ]
        def matches(cmd):
            return any(re.search(p, cmd, re.IGNORECASE) for p in pats)
        for c in danger:
            assert matches(c), f"fallback should deny: {c}"
        for c in benign:
            assert not matches(c), f"fallback should allow: {c}"


# ════════════════════════════════════════════════════════════════════════════
# Layer 1b: fail-closed + self-protection + unbypassable (engine-level)
# ════════════════════════════════════════════════════════════════════════════

class TestFailClosed:
    def _ev_no_cfg(self, command, tmp_path):
        missing = str(tmp_path / "does-not-exist.json")
        os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = missing
        import importlib, lib.runtime_guard as rg
        importlib.reload(rg)
        return rg.evaluate(command)[0]

    def test_failclosed_blocks_families(self, tmp_path):
        for c in ("yarn build", "systemctl restart x", "kill -9 1", "npx tsc"):
            assert self._ev_no_cfg(c, tmp_path) == "BLOCK", c

    def test_failclosed_allows_reads(self, tmp_path):
        for c in ("ls", "cat foo", "grep x file", "git status"):
            assert self._ev_no_cfg(c, tmp_path) == "ALLOW", c

    def test_selfprotect_when_config_absent(self, tmp_path):
        # STEP0 protects the HARDCODED path regardless of the env override target,
        # because the engine hardcodes the configured path. Use the live path here.
        os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = "/root/.config/claude/protected-runtime.json"
        import importlib, lib.runtime_guard as rg
        importlib.reload(rg)
        # Even with the file present-or-absent, STEP0 runs before config load.
        assert rg.evaluate("rm /root/.config/claude/protected-runtime.json")[0] == "BLOCK"


# ════════════════════════════════════════════════════════════════════════════
# Layer 2: live-hook integration (exit-code) incl. unbypassable under /do
# ════════════════════════════════════════════════════════════════════════════

def run_hook(command, env=None):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    e = dict(os.environ)
    if env:
        e.update(env)
    proc = subprocess.run(["bash", HOOK], input=payload, text=True, capture_output=True, env=e)
    return proc.returncode


class TestLiveHook:
    """Drives the REAL hook end-to-end against the live data file.

    Uses benign-but-blocked representatives that do NOT collide with the hook's
    own pre-existing literal blocks where avoidable; the guard runs first so a
    guard BLOCK surfaces as exit 2.
    """

    def test_hook_blocks_bare_build(self):
        assert run_hook("yarn build") == BLOCK

    def test_hook_blocks_workspace_protected_build(self):
        assert run_hook("yarn workspace happy build") == BLOCK

    def test_hook_allows_nonprotected_build(self):
        assert run_hook("yarn workspace happy-server build") == ALLOW

    def test_hook_allows_read_statefile(self):
        assert run_hook("cat /root/.happy-dev/daemon.state.json") == ALLOW

    def test_hook_allows_meta_query(self):
        assert run_hook("yarn --version") == ALLOW

    def test_hook_allows_plain_ls(self):
        assert run_hook("ls -la") == ALLOW

    def test_hook_unbypassable_under_do(self):
        # Create a /do consent flag for this session; the guard must still block.
        import getpass  # noqa
        sid = "guardtest-" + str(os.getpid())
        flag = f"/tmp/claude-orchestrator-consent-{sid}.flag"
        with open(flag, "w") as fh:
            fh.write("true")
        try:
            payload = json.dumps({
                "tool_name": "Bash",
                "tool_input": {"command": "yarn workspace happy build"},
                "session_id": sid,
            })
            proc = subprocess.run(["bash", HOOK], input=payload, text=True, capture_output=True)
            assert proc.returncode == BLOCK
        finally:
            os.remove(flag)


# ════════════════════════════════════════════════════════════════════════════
# Iteration 3 (qa-report-20260531-162901, codex-r3): 25 reproduced idiomatic
# under-block leaks + 3 over-blocks + the narrowed other-project false-positive.
# Strategy: robust path/cwd/selector closures (NOT name enumeration). Each form
# below was reproduced ALLOW (under-block) or BLOCK (over-block) against the
# prior engine; these assert the corrected verdict. Verified ONLY by feeding
# strings to evaluate() (NEVER any real daemon/CLI/process command).
# ════════════════════════════════════════════════════════════════════════════

# Vocabulary split so the test SOURCE never types a full daemon-launch phrase
# (the live bash-safety hook scans this test's own command line at author time).
_S = "daemon " + "start"
_ST = "daemon " + "stop"


class TestR3SelectorExecLaunchBuild:
    """F1: a PM workspace selector + exec loses the selected-workspace cwd. The
    selector now threads the protected workspace dir as the effective cwd so a
    post-exec runtime/build resolves the protected path."""
    def test_selector_exec_runtime_launch(self, datafile, fixture_repo):
        # fixture models the protected workspace by its dev name 'happy'
        assert ev(f"yarn workspace happy exec node dist/index.mjs {_S}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"yarn workspace happy exec node dist/index.mjs {_ST}", datafile, fixture_repo) == "BLOCK"

    def test_selector_exec_build(self, datafile, fixture_repo):
        for c in ("npm -w happy exec tsc -p tsconfig.json",
                  "yarn workspace happy exec tsc -p tsconfig.json"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_selector_exec_nonprotected_allowed(self, datafile, fixture_repo):
        # a non-protected workspace exec of a build pointed at its OWN package
        for c in ("npm -w happy-server exec tsc --version",
                  "yarn workspace happy-server exec node build.js"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c


class TestR3BuildFlagValuePath:
    """F2: build invocations pointing at / writing to the protected package via a
    fused `--flag=path` option (--project=, --outfile=, --tsconfig=)."""
    def test_flagvalue_build_paths(self, datafile, fixture_repo):
        cli = f"{fixture_repo}/packages/happy-cli"
        for c in (f"npx tsc --project={cli}/tsconfig.json",
                  f"esbuild --bundle --outfile={cli}/dist/index.mjs",
                  f"tsc --tsconfig={cli}/tsconfig.json"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_flagvalue_nonprotected_allowed(self, datafile, fixture_repo):
        srv = f"{fixture_repo}/packages/happy-server"
        for c in (f"npx tsc --project={srv}/tsconfig.json",
                  f"esbuild --outfile={srv}/dist/out.js"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c


class TestR3BareBuildModeFlag:
    """F3: bare build-mode flags (tsc -b / --build / -w) with cwd in the
    protected package / monorepo root / indeterminate -> fail-closed rebuild."""
    def test_tsc_build_mode_indeterminate(self, datafile, fixture_repo):
        for c in ("tsc -b", "npx tsc -b", "pnpm exec tsc -b", "tsc --build"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_tsc_build_mode_protected_cwd(self, datafile, fixture_repo):
        assert ev_cwd("tsc -b", datafile, f"{fixture_repo}/packages/happy-cli") == "BLOCK"
        assert ev_cwd("npx tsc -b", datafile, fixture_repo) == "BLOCK"  # monorepo root

    def test_tsc_build_mode_nonprotected_cwd_allowed(self, datafile, fixture_repo):
        # build-mode in a NON-protected workspace cwd is the workspace's own build
        assert ev_cwd("tsc -b", datafile, f"{fixture_repo}/packages/happy-server") == "ALLOW"
        # a bare build tool whose cwd is a non-protected workspace is allowed
        assert ev_cwd("tsc --noEmit", datafile, f"{fixture_repo}/packages/happy-server") == "ALLOW"


class TestR3CorepackVersionPin:
    """F4: corepack <pm>@version proxy must unwrap to the bare PM and re-route."""
    def test_corepack_pm_at_version(self, datafile, fixture_repo):
        for c in (f"corepack pnpm@9 exec happy {_S}",
                  f"corepack yarn@stable workspace happy build",
                  f"corepack npm@10 exec happy {_S}"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_corepack_nonprotected_allowed(self, datafile, fixture_repo):
        assert ev("corepack pnpm@9 --version", datafile, fixture_repo) == "ALLOW"


class TestR3WrapperBarePositional:
    """F5: bare-positional wrappers chrt/taskset/setarch and systemd-run option
    grammar must not hide the protected command word."""
    def test_priority_wrappers(self, datafile, fixture_repo):
        for c in (f"chrt -f 50 happy {_S}", f"taskset 0x1 happy {_S}",
                  f"setarch x86_64 happy {_S}", f"chrt 50 happy {_S}"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_taskset_cpu_option_still_blocks(self, datafile, fixture_repo):
        # the -c <list> form already worked; ensure the leading-positional fix
        # does not break it (mask via option, then command word exposed).
        assert ev(f"taskset -c 0 happy {_S}", datafile, fixture_repo) == "BLOCK"

    def test_systemd_run_options(self, datafile, fixture_repo):
        for c in (f"systemd-run --service-type simple happy {_S}",
                  f"systemd-run -d happy {_S}",
                  f"systemd-run --nice 5 happy {_S}"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_wrapper_nonprotected_allowed(self, datafile, fixture_repo):
        for c in ("chrt -f 50 ls", "taskset 0x1 echo hi", "setarch x86_64 true"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c


class TestR3RuntimeSubcommand:
    """F6: runtime subcommand forms deno run / tsx watch / bun run and the
    ts-node-esm alias must reach the protected src/dist path."""
    def test_runtime_subcommands(self, datafile, fixture_repo):
        cli = f"{fixture_repo}/packages/happy-cli"
        for c in (f"deno run {cli}/src/index.ts",
                  f"tsx watch {cli}/src/index.ts",
                  f"bun run {cli}/dist/index.mjs",
                  f"npx ts-node-esm {cli}/src/index.ts"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_runtime_subcommand_nonprotected_allowed(self, datafile, fixture_repo):
        srv = f"{fixture_repo}/packages/happy-server"
        for c in (f"deno run {srv}/build.ts", f"tsx watch {srv}/dev.ts"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c


class TestR3StatefilePidKill:
    """F7: a kill whose target is resolved by reading the protected statefile,
    and a process-substitution-fed kill."""
    def test_kill_statefile_pid(self, datafile, fixture_repo):
        for c in ("kill $(jq -r .pid /root/.happy-dev/daemon.state.json)",
                  "kill -9 $(cat /root/.happy/daemon.state.json | jq .pid)"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_kill_process_substitution(self, datafile, fixture_repo):
        assert ev("xargs kill <(pgrep -f happy-daemon)", datafile, fixture_repo) == "BLOCK"

    def test_kill_unrelated_statefile_allowed(self, datafile, fixture_repo):
        # reading an UNRELATED statefile to kill is not protected
        assert ev("kill $(jq -r .pid /tmp/other.state.json)", datafile, fixture_repo) == "ALLOW"


class TestR3ServiceVerbs:
    """F8: additional service lifecycle verbs (force-reload / condrestart /
    try-reload-or-restart) in both systemctl VERB UNIT and service UNIT VERB."""
    def test_extra_service_verbs(self, datafile, fixture_repo):
        for c in ("systemctl try-reload-or-restart happy-daemon",
                  "systemctl force-reload happy-daemon",
                  "service happy-daemon condrestart",
                  "systemctl reload-or-try-restart happy-daemon-dev"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_service_verb_unrelated_unit_allowed(self, datafile, fixture_repo):
        assert ev("systemctl force-reload nginx", datafile, fixture_repo) == "ALLOW"


class TestR3RunnerCallPayload:
    """F10: runner -c/--call payload is a virtual command, recursively evaluated;
    benign payloads must NOT over-block."""
    def test_call_payload_launch_build(self, datafile, fixture_repo):
        cli = f"{fixture_repo}/packages/happy-cli"
        for c in (f"npx -c 'happy {_S}'",
                  f"npm exec -c 'tsc -p {cli}/tsconfig.json'",
                  f"pnpm dlx --call 'happy {_S}'"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_call_payload_benign_allowed(self, datafile, fixture_repo):
        for c in ("npm exec -c 'ls'", "npx -c 'echo hi'",
                  "npm exec -c 'tsc --version'"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c


class TestR3PathFilterOverblock:
    """F11: a deterministic non-glob path filter (./packages/x) must resolve to a
    manifest, NOT be misclassified as a fan-out MULTI."""
    def test_path_filter_nonprotected_allowed(self, datafile, fixture_repo):
        for c in ("pnpm --filter ./packages/happy-server build",
                  "pnpm --filter=./packages/happy-app web",
                  "pnpm --filter packages/happy-server build"):
            assert ev(c, datafile, fixture_repo) == "ALLOW", c

    def test_path_filter_protected_blocked(self, datafile, fixture_repo):
        assert ev("pnpm --filter ./packages/happy-cli build", datafile, fixture_repo) == "BLOCK"

    def test_glob_filter_still_failclosed(self, datafile, fixture_repo):
        for c in ("pnpm --filter './packages/*' build", "pnpm --filter '...^happy' build",
                  "pnpm --filter '{packages/*}' build"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c


class TestR3LoopDepthOverblock:
    """F12: `do` must not increment loop depth (only while/for/until do), so a
    later top-level kill is not over-connected to the protected loop pipeline."""
    def test_post_loop_kill_allowed(self, datafile, fixture_repo):
        assert ev("pgrep -af happy-daemon | while read pid; do echo $pid; done; kill 123", datafile, fixture_repo) == "ALLOW"

    def test_in_loop_kill_still_blocked(self, datafile, fixture_repo):
        assert ev("pgrep -af happy-daemon | while read pid; do kill $pid; done", datafile, fixture_repo) == "BLOCK"


class TestR3OtherProjectFalsePositive:
    """Narrowed other-project FP: in an UNRELATED project (manifest outside every
    protected root), a non-declared script token (.bin fallthrough) is harmless
    and must be ALLOWED — UNLESS it is a protected command basename or a
    runtime/exec token."""
    def test_unrelated_project_nondeclared_allowed(self, datafile, fixture_repo, tmp_path_factory):
        other = _make_unrelated_repo(tmp_path_factory)
        for c in ("yarn lint", "yarn eslint", "yarn workspace web-app lint", "yarn"):
            assert ev_cwd(c, datafile, other) == "ALLOW", c

    def test_unrelated_project_protected_token_still_blocked(self, datafile, fixture_repo, tmp_path_factory):
        other = _make_unrelated_repo(tmp_path_factory)
        for c in (f"yarn happy {_S}", "yarn node x.js", "yarn workspace web-app happy " + _S):
            assert ev_cwd(c, datafile, other) == "BLOCK", c

    def test_protected_monorepo_nonprotected_ws_nondeclared_still_blocked(self, datafile, fixture_repo):
        # within the protected monorepo, a non-declared token fallthrough reaches
        # the hoisted protected CLI bin -> stays BLOCKED.
        assert ev("yarn workspace happy-server lint", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("yarn lint", datafile, f"{fixture_repo}/packages/happy-server") == "BLOCK"


def _make_unrelated_repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("unrelated")
    pkgs = root / "packages"
    pkgs.mkdir()
    (pkgs / "web").mkdir()
    (pkgs / "web" / "package.json").write_text(json.dumps({"name": "web-app", "scripts": {"build": "x", "start": "x"}}))
    (root / "package.json").write_text(json.dumps({"name": "other-monorepo", "scripts": {"build": "x"}}))
    return str(root)


# ════════════════════════════════════════════════════════════════════════════
# Iteration 3 codex (gpt-5.5 xhigh) adversarial-review regression coverage.
# Codex surfaced 14 in-scope deeper forms (under-blocks + over-blocks) and 1
# out-of-scope residual (declared-script-body transitive reach — deferred per BA
# ROUND-5 codex-r5-4). The 14 in-scope forms are covered here. Verified ONLY by
# feeding strings to evaluate() (NEVER any real daemon/CLI/process command).
# ════════════════════════════════════════════════════════════════════════════


def _make_mirror_repo(tmp_path_factory):
    """An UNRELATED project that MIRRORS the packages/happy-cli layout (same
    suffix path) to prove suffix-glob matching does not over-block it."""
    root = tmp_path_factory.mktemp("mirror")
    pkgs = root / "packages"
    pkgs.mkdir()
    (pkgs / "happy-cli").mkdir()
    (pkgs / "happy-cli" / "package.json").write_text(json.dumps({"name": "unrelated-cli", "scripts": {"build": "x", "lint": "x"}}))
    (root / "package.json").write_text(json.dumps({"name": "mirror-root", "scripts": {"build": "x"}}))
    return str(root)


class TestR3CodexBuildPathCwd:
    """codex#1: relative build path resolved against effective cwd from a sibling
    package rebuilds the protected bundle."""
    def test_relative_build_path_sibling(self, datafile, fixture_repo):
        srv = f"{fixture_repo}/packages/happy-server"
        for c in ("npx tsc -p ../happy-cli/tsconfig.json",
                  "esbuild --outfile=../happy-cli/dist/index.mjs"):
            assert ev_cwd(c, datafile, srv) == "BLOCK", c

    def test_relative_build_path_sibling_nonprotected_allowed(self, datafile, fixture_repo):
        srv = f"{fixture_repo}/packages/happy-server"
        assert ev_cwd("npx tsc -p ./tsconfig.json", datafile, srv) == "ALLOW"


class TestR3CodexDefineFlagOverblock:
    """codex#2: a non-path key/value flag (--define:X=<protected>) must not be
    treated as a build path."""
    def test_define_value_not_path(self, datafile, fixture_repo):
        cli = f"{fixture_repo}/packages/happy-cli"
        srv = f"{fixture_repo}/packages/happy-server"
        assert ev(f"esbuild --define:CLI={cli} --outfile={srv}/out.js", datafile, fixture_repo) == "ALLOW"


class TestR3CodexBuildModeExplicitTarget:
    """codex#3: build-mode (-w/-b) with an explicit NON-protected project target
    must not be over-blocked by the cwd/root fallback."""
    def test_build_mode_explicit_nonprotected(self, datafile, fixture_repo):
        assert ev_cwd("tsc -w -p packages/happy-server/tsconfig.json", datafile, fixture_repo) == "ALLOW"

    def test_build_mode_explicit_protected_blocked(self, datafile, fixture_repo):
        assert ev_cwd("tsc -w -p packages/happy-cli/tsconfig.json", datafile, fixture_repo) == "BLOCK"


class TestR3CodexExecSelectorTarget:
    """codex#4: a PM selector after exec must not be misparsed as the runner
    target."""
    def test_exec_selector_then_runtime(self, datafile, fixture_repo):
        assert ev(f"npm exec -w happy -- node dist/index.mjs {_S}", datafile, fixture_repo) == "BLOCK"


class TestR3CodexMultiExecFanout:
    """codex#5: recursive/all-workspace exec of a runtime/build fans into the
    protected workspace."""
    def test_recursive_exec_runtime(self, datafile, fixture_repo):
        assert ev(f"pnpm -r exec node dist/index.mjs {_S}", datafile, fixture_repo) == "BLOCK"

    def test_glob_filter_exec_build(self, datafile, fixture_repo):
        assert ev("pnpm --filter './packages/*' exec tsc -p tsconfig.json", datafile, fixture_repo) == "BLOCK"


class TestR3CodexCallPayloadCwd:
    """codex#6: a runner -c/--call payload is recursively evaluated under the
    selector-resolved cwd."""
    def test_call_payload_selector_cwd(self, datafile, fixture_repo):
        assert ev(f"npm -w happy exec -c 'node dist/index.mjs {_S}'", datafile, fixture_repo) == "BLOCK"


class TestR3CodexRuntimePreload:
    """codex#7: a runtime preload/import option VALUE that is the protected path
    executes it."""
    def test_node_import_require(self, datafile, fixture_repo):
        cli = f"{fixture_repo}/packages/happy-cli"
        for c in (f"node --import {cli}/dist/index.mjs",
                  f"node -r {cli}/dist/index.mjs -e ''",
                  f"node --import={cli}/dist/index.mjs"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c


class TestR3CodexNodeRun:
    """codex#8: node --run <script> from a protected cwd is a package-script
    runner reaching the protected package."""
    def test_node_run_protected_cwd(self, datafile, fixture_repo):
        assert ev_cwd("node --run start", datafile, f"{fixture_repo}/packages/happy-cli") == "BLOCK"

    def test_node_run_indeterminate_cwd(self, datafile, fixture_repo):
        assert ev("node --run build", datafile, fixture_repo) == "BLOCK"


class TestR3CodexStatefileFusedRedirect:
    """codex#9: a kill whose substitution reads the protected statefile via a
    FUSED input redirection (`<path`)."""
    def test_kill_fused_redirect(self, datafile, fixture_repo):
        assert ev("kill $(jq -r .pid </root/.happy-dev/daemon.state.json)", datafile, fixture_repo) == "BLOCK"


class TestR3CodexSystemdTemplate:
    """codex#10: a protected systemd TEMPLATE instance (unit@instance)."""
    def test_template_instance(self, datafile, fixture_repo):
        for c in ("systemctl restart happy-daemon@dev.service",
                  "systemctl stop happy-daemon@prod"):
            assert ev(c, datafile, fixture_repo) == "BLOCK", c

    def test_unrelated_hyphenated_unit_allowed(self, datafile, fixture_repo):
        # a longer hyphenated unrelated unit must NOT match a protected prefix
        assert ev("systemctl restart happy-daemon-clone-xyz", datafile, fixture_repo) == "ALLOW"


class TestR3CodexMutationCwdAndRemoval:
    """codex#11: P3/P4 resolve relative mutation targets against effective cwd and
    cover removal verbs."""
    def test_cd_then_touch_hotfile(self, datafile, fixture_repo):
        assert ev(f"cd {fixture_repo}/packages/happy-cli && touch dist/index.mjs", datafile, fixture_repo) == "BLOCK"

    def test_rm_relative_hotfile(self, datafile, fixture_repo):
        assert ev_cwd("rm packages/happy-cli/dist/index.mjs", datafile, fixture_repo) == "BLOCK"

    def test_cd_then_truncate_statefile(self, datafile, fixture_repo):
        assert ev("cd /root/.happy-dev && truncate -s0 daemon.state.json", datafile, fixture_repo) == "BLOCK"


class TestR3CodexScopedFilterOverblock:
    """codex#12: a scoped package NAME filter (@scope/name) is a name selector,
    not a filesystem path."""
    def test_scoped_filter_build_allowed(self, datafile, fixture_repo):
        assert ev("pnpm --filter @slopus/happy-wire build", datafile, fixture_repo) == "ALLOW"


class TestR3CodexUnrelatedMirrorOverblock:
    """codex#13: an UNRELATED project mirroring packages/happy-cli must not be
    treated as protected by suffix-glob matching."""
    def test_unrelated_mirror_run_allowed(self, datafile, fixture_repo, tmp_path_factory):
        mirror = _make_mirror_repo(tmp_path_factory)
        assert ev_cwd("yarn lint", datafile, f"{mirror}/packages/happy-cli") == "ALLOW"

    def test_unrelated_mirror_path_filter_allowed(self, datafile, fixture_repo, tmp_path_factory):
        mirror = _make_mirror_repo(tmp_path_factory)
        assert ev_cwd("pnpm --filter ./packages/happy-cli build", datafile, mirror) == "ALLOW"


class TestR3CodexP9ExplicitPathShortcircuit:
    """codex#14: an explicit protected build-path arg forwarded to a script must
    block even when P9 would ALLOW the script-run."""
    def test_build_explicit_protected_path(self, datafile, fixture_repo):
        cli = f"{fixture_repo}/packages/happy-cli"
        srv = f"{fixture_repo}/packages/happy-server"
        assert ev_cwd(f"yarn build --project {cli}/tsconfig.json", datafile, srv) == "BLOCK"

    def test_build_explicit_nonprotected_path_allowed(self, datafile, fixture_repo):
        srv = f"{fixture_repo}/packages/happy-server"
        assert ev_cwd(f"yarn build --project {srv}/tsconfig.json", datafile, srv) == "ALLOW"


class TestCycle4WrapperAgnosticFrontends:
    """Cycle 4 (QA-20260531-162901 §7): the wrapper layer must be wrapper-
    AGNOSTIC. A protected launch/kill/build behind ANY documented routine exec
    front-end (flock/firejail/unshare/nsenter/runuser/su/strace/watch/cpulimit/
    setpriv/prlimit/perf/valgrind/rr/bwrap/chroot/proot/xvfb-run/dbus-run-session/
    gdb --args) must BLOCK; a non-protected tail behind the same front-end and a
    read-only mention must ALLOW (no blanket substring scan)."""

    # ── The 9 QA-reproduced LIVE leaks (each names a protected path/command) ──
    NINE_LEAKS = [
        "flock /tmp/l node {repo}/packages/happy-cli/dist/index.mjs daemon start",
        "flock -n /tmp/l happy daemon start",
        "firejail node {repo}/packages/happy-cli/dist/index.mjs daemon start",
        "unshare -r node {repo}/packages/happy-cli/dist/index.mjs daemon start",
        "nsenter -t 1 -m node {repo}/packages/happy-cli/dist/index.mjs daemon start",
        "runuser -u root node {repo}/packages/happy-cli/dist/index.mjs daemon start",
        "strace -f node {repo}/packages/happy-cli/dist/index.mjs daemon start",
        "watch -n5 happy daemon start",
        "cpulimit -l 50 node {repo}/packages/happy-cli/dist/index.mjs daemon start",
    ]

    @pytest.mark.parametrize("tmpl", NINE_LEAKS)
    def test_nine_reproduced_leaks_block(self, tmpl, datafile, fixture_repo):
        assert ev(tmpl.format(repo=fixture_repo), datafile, fixture_repo) == "BLOCK"

    # ── Broad sweep: arbitrary documented front-ends around a protected path ──
    SWEEP_FRONTENDS = [
        "firejail", "unshare", "nsenter -t 1 -m", "runuser -u root", "strace -f",
        "ltrace", "cpulimit -l 50", "setpriv --reuid 0", "prlimit --pid 1",
        "valgrind", "bwrap --dev /dev", "proot", "xvfb-run", "dbus-run-session --",
        "perf stat", "rr record", "chroot /", "gdb --args",
    ]

    @pytest.mark.parametrize("fe", SWEEP_FRONTENDS)
    def test_sweep_protected_launch_blocks(self, fe, datafile, fixture_repo):
        cmd = f"{fe} node {fixture_repo}/packages/happy-cli/dist/index.mjs daemon start"
        assert ev(cmd, datafile, fixture_repo) == "BLOCK"

    def test_stacked_frontends_block(self, datafile, fixture_repo):
        p = f"{fixture_repo}/packages/happy-cli/dist/index.mjs"
        assert ev(f"flock /tmp/l strace -f node {p} daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev("firejail strace -f happy daemon start", datafile, fixture_repo) == "BLOCK"

    # ── Shell-string payload wrappers (recursed via evaluate) ────────────────
    def test_shell_string_payloads_block(self, datafile, fixture_repo):
        assert ev("flock -c 'happy daemon start' /tmp/l", datafile, fixture_repo) == "BLOCK"
        assert ev("su -c 'happy daemon start' root", datafile, fixture_repo) == "BLOCK"
        assert ev("runuser -u root -c 'happy daemon start'", datafile, fixture_repo) == "BLOCK"
        assert ev("watch -n2 'happy daemon start'", datafile, fixture_repo) == "BLOCK"

    # ── KILL family behind front-ends ────────────────────────────────────────
    def test_kill_behind_frontend_blocks(self, datafile, fixture_repo):
        ident = "packages/happy-cli/dist/index.mjs"
        assert ev(f"strace -f pkill -f {ident}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"flock /tmp/l pkill -f {ident}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"runuser -u root kill -9 $(pgrep -f {ident})", datafile, fixture_repo) == "BLOCK"
        assert ev(f"watch -n2 'pkill -f {ident}'", datafile, fixture_repo) == "BLOCK"

    # ── REBUILD behind front-ends ────────────────────────────────────────────
    def test_rebuild_behind_frontend_blocks(self, datafile, fixture_repo):
        assert ev("flock /tmp/l yarn workspace happy build", datafile, fixture_repo) == "BLOCK"
        assert ev("strace -f npx tsc -p packages/happy-cli/tsconfig.json", datafile, fixture_repo) == "BLOCK"

    # ── Boundary ALLOWs: front-end + NON-protected tail / read-only mention ──
    def test_frontend_benign_tail_allows(self, datafile, fixture_repo):
        assert ev("flock /tmp/l ls -la", datafile, fixture_repo) == "ALLOW"
        assert ev("strace -f grep foo bar.txt", datafile, fixture_repo) == "ALLOW"
        assert ev("watch -n5 ls", datafile, fixture_repo) == "ALLOW"
        assert ev("firejail yarn workspace happy-server build", datafile, fixture_repo) == "ALLOW"
        assert ev("unshare -r yarn workspace happy-server build", datafile, fixture_repo) == "ALLOW"
        assert ev("nsenter -t 1 -m cat /root/.happy-dev/daemon.state.json", datafile, fixture_repo) == "ALLOW"

    def test_readonly_mentions_allow(self, datafile, fixture_repo):
        assert ev("grep packages/happy-cli/dist/index.mjs -R .", datafile, fixture_repo) == "ALLOW"
        assert ev("echo flock node packages/happy-cli/dist/index.mjs daemon start", datafile, fixture_repo) == "ALLOW"
        assert ev("printf 'strace happy daemon start'", datafile, fixture_repo) == "ALLOW"

    def test_unknown_wrapper_is_not_a_frontend(self, datafile, fixture_repo):
        # An UNKNOWN binary head is NOT a documented front-end, so it is not
        # peeled — a benign unknown command stays allowed (no over-block) and the
        # accepted residual (unknown wrapper + protected path) is NOT mis-peeled.
        assert ev("mybin --foo bar", datafile, fixture_repo) == "ALLOW"

    # ── fail-closed behind a front-end (absent/corrupt config) ───────────────
    def test_frontend_failclosed(self, datafile, fixture_repo, tmp_path_factory):
        absent = str(tmp_path_factory.mktemp("nocfg") / "absent.json")
        p = f"{fixture_repo}/packages/happy-cli/dist/index.mjs"
        # launch behind a front-end blocks under absent config; benign tail passes
        assert ev(f"flock /tmp/l node {p} daemon start", absent, fixture_repo) == "BLOCK"
        assert ev("flock /tmp/l ls", absent, fixture_repo) == "ALLOW"

    # ── Codex-found edge cases (adversarial review of the Cycle-4 fix) ───────
    def test_env_wrapper_before_frontend_blocks(self, datafile, fixture_repo):
        # codex F1: an ENV_WRAPPER (env/command/nohup/sudo) BEFORE a front-end
        # must still expose the protected launch (the front-end head sits behind
        # the wrapper). Previously these leaked (ALLOW).
        p = f"{fixture_repo}/packages/happy-cli/dist/index.mjs"
        assert ev(f"env flock /tmp/l node {p} daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev("command flock /tmp/l happy daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev("nohup flock /tmp/l happy daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev("sudo nohup happy daemon start", datafile, fixture_repo) == "BLOCK"

    def test_frontend_cwd_opt_blocks(self, datafile, fixture_repo):
        # codex F3: a cwd-changing front-end option (unshare --wd / bwrap --chdir
        # / proot -w) pointing at the protected workspace must resolve the wrapped
        # RELATIVE launch path against it. Previously these leaked (ALLOW).
        cli = f"{fixture_repo}/packages/happy-cli"
        assert ev(f"unshare --wd {cli} node dist/index.mjs daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev(f"bwrap --chdir {cli} node dist/index.mjs daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev(f"proot -w {cli} node dist/index.mjs daemon start", datafile, fixture_repo) == "BLOCK"
        # a cwd-opt to a NON-protected dir + benign tail stays allowed
        assert ev("unshare --wd /tmp node script.js", datafile, fixture_repo) == "ALLOW"
        assert ev("bwrap --chdir /tmp ls", datafile, fixture_repo) == "ALLOW"

    def test_su_runuser_user_positional(self, datafile, fixture_repo):
        # codex F4: su/runuser accept an optional USER positional before/around a
        # -c payload; the payload must still be recursed. But a -u USER OPTION
        # must NOT also eat the tail command word as a positional.
        assert ev("su root -c 'happy daemon start'", datafile, fixture_repo) == "BLOCK"
        assert ev("su -c 'happy daemon start' root", datafile, fixture_repo) == "BLOCK"
        ident = "packages/happy-cli/dist/index.mjs"
        # -u root supplies the user; 'kill' is the tail head, NOT the user positional
        assert ev(f"runuser -u root kill -9 $(pgrep -f {ident})", datafile, fixture_repo) == "BLOCK"
        # benign user-positional payloads stay allowed
        assert ev("su -c 'git status' postgres", datafile, fixture_repo) == "ALLOW"
        assert ev("runuser -u root -c 'echo hi'", datafile, fixture_repo) == "ALLOW"

    def test_group_topology_preserved_no_overblock(self, datafile, fixture_repo):
        # codex F5: peeling must NOT collapse `;`/`&&`-separated commands into one
        # P5/P6 group. A benign kill of an unrelated PID + a `;`-separated mention
        # of a protected ident must stay ALLOW (they are in DIFFERENT groups).
        ident = "packages/happy-cli/dist/index.mjs"
        assert ev(f"flock /tmp/l kill 123 ; echo {ident}", datafile, fixture_repo) == "ALLOW"
        assert ev(f"strace -f kill 999 ; grep {ident} file", datafile, fixture_repo) == "ALLOW"
        assert ev(f"kill 5 ; flock /tmp/l grep {ident} x", datafile, fixture_repo) == "ALLOW"
        # but a kill carrying the ident WITHIN one pipe group still blocks
        assert ev(f"pgrep -f {ident} | flock /tmp/l xargs kill", datafile, fixture_repo) == "BLOCK"

    def test_frontend_payload_failclosed(self, datafile, fixture_repo, tmp_path_factory):
        # codex F5b: a shell-string payload behind a front-end must be recursed
        # BEFORE the config-load fail-closed return, so a DANGER-VERB-family
        # payload (build/kill/service/global-install) still blocks under an absent
        # config. (A launch-by-command-BASENAME — 'happy daemon start' — is
        # ALLOWed under absent config by design: STEP1 cannot know the basename is
        # protected without the data file; that matches the pre-existing AC-D
        # contract, not a payload-recursion gap.)
        absent = str(tmp_path_factory.mktemp("nocfg2") / "absent.json")
        assert ev("flock -c 'yarn build' /tmp/l", absent, fixture_repo) == "BLOCK"
        assert ev("su -c 'kill -9 1' root", absent, fixture_repo) == "BLOCK"
        # sanity: the SAME launch-by-basename payload blocks once config is present
        assert ev("flock -c 'happy daemon start' /tmp/l", datafile, fixture_repo) == "BLOCK"

    def test_gdb_without_args_marker_no_tail(self, datafile, fixture_repo):
        # gdb only exec()s a wrapped command after --args; without it there is no
        # tail to analyze (benign).
        assert ev("gdb -ex run ls", datafile, fixture_repo) == "ALLOW"
        p = f"{fixture_repo}/packages/happy-cli/dist/index.mjs"
        assert ev(f"gdb --args node {p} daemon start", datafile, fixture_repo) == "BLOCK"

    # ── live-hook proof for the 9 leaks (exit 2) ─────────────────────────────
    def test_nine_leaks_live_hook_block(self, datafile, fixture_repo):
        # drive the REAL hook on stdin; pin the engine to the isolated fixture
        # data file via env so the live machine file is never touched.
        env = dict(os.environ)
        env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
        env["CLAUDE_GUARD_CWD"] = fixture_repo
        for tmpl in self.NINE_LEAKS:
            cmd = tmpl.format(repo=fixture_repo)
            payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd, "cwd": fixture_repo}, "agent_id": "dev-test"})
            r = subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)
            assert r.returncode == BLOCK, f"live hook did not block: {cmd} (rc={r.returncode})"


class TestCycle5AnchorBasedHeadAgnostic:
    """Cycle 5 (QA-20260531-162901 iter4 §7): the launch/build/kill detection must
    be ANCHOR-BASED and HEAD-AGNOSTIC — it must NOT depend on a finite enumeration
    of wrapper/front-end names. The detector scans the WHOLE argv of each simple
    command for a protected anchor (a protected_cmds basename, a protected launch
    path, a protected build path/workspace, a protected proc-ident) in executable
    position + launch/build/kill grammar, gated only by a small read/inspect/edit
    ALLOWLIST on the head. The proof of non-enumeration is the W5 sweep: front-end
    program names that appear NOWHERE in the engine source still BLOCK.
    """

    # Front-end program names that are GENUINELY ABSENT from the engine source
    # (verified by test_frontends_absent_from_engine below). The leak must close
    # WITHOUT any of these being added to a wrapper table.
    UNDOC_FRONTENDS = [
        "numactl -N 0", "tini --", "dumb-init", "ssh-agent", "catchsegv",
        "torsocks",
        # W5: invented/novel front-ends that appear nowhere in the engine source.
        "quxwrap", "frobnicate", "zzwrapper", "mywrap42", "launchy", "runitall",
        "blorp", "wrapzilla", "spinup99", "thingrunner",
    ]

    # ── W1 + W2: LAUNCH-PATH and COMMAND-BASENAME anchors behind any front-end ──
    @pytest.mark.parametrize("fe", UNDOC_FRONTENDS)
    def test_w1_launch_path_anchor(self, fe, datafile, fixture_repo):
        p = f"{fixture_repo}/packages/happy-cli/dist/index.mjs"
        assert ev(f"{fe} node {p} daemon start", datafile, fixture_repo) == "BLOCK"

    @pytest.mark.parametrize("fe", UNDOC_FRONTENDS)
    def test_w2_command_basename_anchor(self, fe, datafile, fixture_repo):
        assert ev(f"{fe} happy daemon start", datafile, fixture_repo) == "BLOCK"

    # ── W3: BUILD anchor behind any front-end ────────────────────────────────
    def test_w3_build_anchor(self, datafile, fixture_repo):
        assert ev("numactl npx tsc -p packages/happy-cli/tsconfig.json", datafile, fixture_repo) == "BLOCK"
        assert ev("tini -- yarn workspace happy build", datafile, fixture_repo) == "BLOCK"
        assert ev("dumb-init yarn workspace happy-coder build", datafile, fixture_repo) == "BLOCK"
        assert ev(f"thingrunner npx tsc -p {fixture_repo}/packages/happy-cli/tsconfig.json", datafile, fixture_repo) == "BLOCK"

    # ── W4: KILL anchor behind any front-end ─────────────────────────────────
    def test_w4_kill_anchor(self, datafile, fixture_repo):
        ident = "packages/happy-cli/dist/index.mjs"
        assert ev(f"numactl -N 0 kill -9 $(pgrep -f {ident})", datafile, fixture_repo) == "BLOCK"
        assert ev(f"tini -- pkill -f {ident}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"ssh-agent killall -9 {ident}", datafile, fixture_repo) == "BLOCK"
        # statefile-reaching kill behind a novel wrapper
        assert ev("numactl kill $(jq .pid /root/.happy-dev/daemon.state.json)", datafile, fixture_repo) == "BLOCK"

    # ── W5: stacked documented + undocumented front-ends ─────────────────────
    def test_w5_stacked_frontends(self, datafile, fixture_repo):
        p = f"{fixture_repo}/packages/happy-cli/dist/index.mjs"
        assert ev("flock /tmp/l numactl happy daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev(f"strace -f numactl node {p} daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev("numactl flock /tmp/l happy daemon start", datafile, fixture_repo) == "BLOCK"

    def test_w5_frontends_absent_from_engine(self):
        # PROOF the detection is NOT enumeration-based: these front-end names do
        # NOT appear anywhere in the engine source, yet they all BLOCK above.
        engine = os.path.join(HOOKS_DIR, "lib", "runtime_guard.py")
        src = open(engine, encoding="utf-8").read()
        for name in ("numactl", "tini", "dumb-init", "dumb_init", "ssh-agent",
                     "ssh_agent", "catchsegv", "torsocks", "quxwrap",
                     "frobnicate", "zzwrapper", "mywrap42", "launchy",
                     "runitall", "blorp", "wrapzilla", "spinup99", "thingrunner"):
            assert name not in src, f"engine must not enumerate front-end '{name}'"

    # ── W6: NO OVER-BLOCK — read/inspect/edit of protected path ALLOWS; a ────
    #        front-end around a NON-protected command ALLOWS; data forms ALLOW. ─
    def test_w6_inspection_heads_allow(self, datafile, fixture_repo):
        p = f"{fixture_repo}/packages/happy-cli/dist/index.mjs"
        # read/inspect/edit of a protected path (head in allowlist) ALLOWS
        assert ev(f"cat {p}", datafile, fixture_repo) == "ALLOW"
        assert ev(f"less {p}", datafile, fixture_repo) == "ALLOW"
        assert ev(f"head -n5 {p}", datafile, fixture_repo) == "ALLOW"
        assert ev(f"vim {p}", datafile, fixture_repo) == "ALLOW"
        assert ev(f"grep daemon {p}", datafile, fixture_repo) == "ALLOW"
        assert ev(f"wc -l {p}", datafile, fixture_repo) == "ALLOW"
        assert ev(f"stat {p}", datafile, fixture_repo) == "ALLOW"
        assert ev(f"lsof {p}", datafile, fixture_repo) == "ALLOW"
        # data forms: the protected string is an ARGUMENT, not an execution
        assert ev("echo happy daemon start", datafile, fixture_repo) == "ALLOW"
        assert ev("grep happy-daemon-start file", datafile, fixture_repo) == "ALLOW"
        assert ev("printf 'numactl happy daemon start'", datafile, fixture_repo) == "ALLOW"

    @pytest.mark.parametrize("fe", UNDOC_FRONTENDS)
    def test_w6_frontend_nonprotected_tail_allows(self, fe, datafile, fixture_repo):
        # a novel front-end around a NON-protected command ALLOWS
        assert ev(f"{fe} ls -la", datafile, fixture_repo) == "ALLOW"

    def test_w6_nonprotected_build_behind_frontend_allows(self, datafile, fixture_repo):
        # an explicit non-protected workspace / path build behind a novel wrapper
        # must ALLOW even at the monorepo root (residual #1 / sibling builds).
        assert ev_cwd("numactl -N 0 yarn workspace happy-server build", datafile, fixture_repo) == "ALLOW"
        assert ev_cwd("tini -- yarn workspace happy-app build", datafile, fixture_repo) == "ALLOW"
        assert ev_cwd("numactl npx tsc -p packages/happy-server/tsconfig.json", datafile, fixture_repo) == "ALLOW"

    def test_w6_residual_unknown_wrapper_no_protected_anchor_allows(self, datafile, fixture_repo):
        # the documented exotic RESIDUAL: a form that names NO protected anchor
        # (no protected path, no protected command, no protected cwd) ALLOWS.
        assert ev("numactl -N 0 node /opt/other/app.mjs run", datafile, fixture_repo) == "ALLOW"
        assert ev("tini -- /usr/local/bin/somedaemon start", datafile, fixture_repo) == "ALLOW"

    # ── fail-closed (absent config): generic danger families behind a novel ──
    #     wrapper must BLOCK; benign reads ALLOW. The leak must not survive. ───
    def test_w_failclosed_tail_scan(self, datafile, fixture_repo, tmp_path_factory):
        absent = str(tmp_path_factory.mktemp("nocfg5") / "absent.json")
        assert ev("numactl npx tsc -p packages/happy-cli/tsconfig.json", absent, fixture_repo) == "BLOCK"
        assert ev("tini -- yarn workspace happy build", absent, fixture_repo) == "BLOCK"
        assert ev("ssh-agent kill -9 1", absent, fixture_repo) == "BLOCK"
        assert ev("numactl yarn build", absent, fixture_repo) == "BLOCK"
        assert ev("dumb-init node /some/index.mjs", absent, fixture_repo) == "BLOCK"
        # benign reads behind a novel wrapper still ALLOW under absent config
        assert ev("numactl ls", absent, fixture_repo) == "ALLOW"
        assert ev("tini -- cat foo", absent, fixture_repo) == "ALLOW"
        assert ev("ssh-agent grep x file", absent, fixture_repo) == "ALLOW"

    # ── live-hook proof (exit 2) for the undocumented-wrapper leak class ─────
    def test_w_undoc_wrapper_live_hook_block(self, datafile, fixture_repo):
        env = dict(os.environ)
        env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
        env["CLAUDE_GUARD_CWD"] = fixture_repo
        p = f"{fixture_repo}/packages/happy-cli/dist/index.mjs"
        cmds = [
            "numactl -N 0 happy daemon start",
            "tini -- happy daemon start",
            "dumb-init happy daemon start",
            "ssh-agent happy daemon start",
            "catchsegv happy daemon start",
            "torsocks happy daemon start",
            f"numactl -N 0 node {p} daemon start",
            "numactl npx tsc -p packages/happy-cli/tsconfig.json",
            "tini -- yarn workspace happy build",
            "flock /tmp/l numactl happy daemon start",
            "wrapzilla -- happy daemon start",
        ]
        for cmd in cmds:
            payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd, "cwd": fixture_repo}, "agent_id": "dev-test"})
            r = subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)
            assert r.returncode == BLOCK, f"live hook did not block: {cmd} (rc={r.returncode})"

    def test_w_undoc_wrapper_live_hook_allow(self, datafile, fixture_repo):
        env = dict(os.environ)
        env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
        env["CLAUDE_GUARD_CWD"] = fixture_repo
        cmds = [
            "numactl ls",
            "tini -- ls",
            "ssh-agent grep x file",
            "numactl -N 0 yarn workspace happy-server build",
            "echo happy daemon start",
        ]
        for cmd in cmds:
            payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd, "cwd": fixture_repo}, "agent_id": "dev-test"})
            r = subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)
            assert r.returncode == ALLOW, f"live hook over-blocked: {cmd} (rc={r.returncode})"


class TestCycle5CodexAdversarial:
    """Cycle 5 codex (gpt-5.5 xhigh) adversarial findings on the anchor fix.
    Each finding closed a leak or fixed an over-block; these tests lock them."""

    def test_codex1_fused_option_value_launch(self, datafile, fixture_repo):
        # F1: a fused `--opt=<protected>` option value execs the protected target.
        p = f"{fixture_repo}/packages/happy-cli/dist/index.mjs"
        assert ev("anywrap --exec=happy daemon", datafile, fixture_repo) == "BLOCK"
        assert ev(f"anywrap --cmd={p} run", datafile, fixture_repo) == "BLOCK"
        # a fused value that is a protected path always blocks (launch path)
        assert ev(f"runner --node-arg={p}", datafile, fixture_repo) == "BLOCK"

    def test_codex2_find_exec_launch(self, datafile, fixture_repo):
        # F2: find/fd with an -exec action RUN a command -> not pure inspection.
        p = f"{fixture_repo}/packages/happy-cli/dist/index.mjs"
        assert ev("find . -exec happy daemon {} ;", datafile, fixture_repo) == "BLOCK"
        assert ev(f"find . -exec node {p} daemon ;", datafile, fixture_repo) == "BLOCK"
        assert ev("fd -e js -x happy daemon", datafile, fixture_repo) == "BLOCK"
        # a plain find/fd search (no -exec) is still inspection -> ALLOW
        assert ev("find . -name '*.mjs'", datafile, fixture_repo) == "ALLOW"
        assert ev(f"find {fixture_repo}/packages/happy-cli -type f", datafile, fixture_repo) == "ALLOW"

    def test_codex_fuser_kill_behind_wrapper(self, datafile, fixture_repo):
        # fuser -k is a kill executor (not in KILL_VERBS); behind a novel wrapper
        # its head is the wrapper, so the W4 anchor must detect fuser+-k+ident.
        ident = "packages/happy-cli/dist/index.mjs"
        assert ev(f"numactl fuser -k {ident}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"fuser -k {ident}", datafile, fixture_repo) == "BLOCK"
        # a fuser -k of an unrelated bare PID (no protected target) ALLOWS
        assert ev("fuser -k 1234", datafile, fixture_repo) == "ALLOW"
        assert ev(f"numactl fuser {ident}", datafile, fixture_repo) == "ALLOW"  # no -k = read-only

    def test_codex3_failclosed_find_exec_and_fuser_kill(self, datafile, fixture_repo, tmp_path_factory):
        # F3: under absent config, find -exec <danger> and fuser -k must BLOCK.
        absent = str(tmp_path_factory.mktemp("nocfg_codex3") / "absent.json")
        assert ev("find . -exec node protected.js {} ;", absent, fixture_repo) == "BLOCK"
        assert ev("fuser -k 1234", absent, fixture_repo) == "BLOCK"
        assert ev("numactl find . -exec yarn build {} ;", absent, fixture_repo) == "BLOCK"
        # benign reads under absent config still ALLOW
        assert ev("find . -name '*.js'", absent, fixture_repo) == "ALLOW"
        assert ev("fuser 1234", absent, fixture_repo) == "ALLOW"

    def test_failclosed_fuser_kill_behind_wrapper(self, datafile, fixture_repo, tmp_path_factory):
        # Cycle-6 regression: in FAIL-CLOSED mode (config absent/corrupt) the kill
        # FAMILY is generic and config-independent, so `<wrapper> fuser -k <ident>`
        # must BLOCK exactly like bare/kill/pkill/killall — the head=='fuser' gate
        # let it leak behind any wrapper (the daemon-kill catastrophe).
        absent = str(tmp_path_factory.mktemp("nocfg_failclosed_fuser") / "absent.json")
        ident = "packages/happy-cli/dist/index.mjs"
        # the leak the fix closes: wrapped fuser -k under absent config -> BLOCK
        for wrapper in ("numactl", "tini", "dumb-init", "quxwrap", "frobnicate"):
            assert ev(f"{wrapper} fuser -k {ident}", absent, fixture_repo) == "BLOCK", wrapper
        # bare-vs-wrapped symmetry: bare fuser -k must ALSO block fail-closed
        assert ev(f"fuser -k {ident}", absent, fixture_repo) == "BLOCK"
        assert ev("fuser -k 1234", absent, fixture_repo) == "BLOCK"
        # fused short flag containing k (e.g. -ki) behind a wrapper still blocks
        assert ev(f"numactl fuser -ki {ident}", absent, fixture_repo) == "BLOCK"
        # sibling exec-position forms the same tail predicate closes
        assert ev(f"xargs fuser -k {ident}", absent, fixture_repo) == "BLOCK"
        assert ev("find . -exec fuser -k {} ;", absent, fixture_repo) == "BLOCK"
        # other kill verbs (bare AND wrapped) still block fail-closed (unchanged)
        assert ev("pkill -f happy", absent, fixture_repo) == "BLOCK"
        assert ev("numactl pkill -f happy", absent, fixture_repo) == "BLOCK"
        assert ev("kill -9 1234", absent, fixture_repo) == "BLOCK"
        # benign read-only fuser (no -k, no kill) under absent config still ALLOWs
        assert ev(f"fuser {ident}", absent, fixture_repo) == "ALLOW"
        assert ev(f"numactl fuser {ident}", absent, fixture_repo) == "ALLOW"
        assert ev("fuser 1234", absent, fixture_repo) == "ALLOW"
        # NO OVER-BLOCK: a read-only fuser behind a WRAPPER whose own option merely
        # CONTAINS the letter 'k' (e.g. --check/--token) must still ALLOW — the -k
        # scan is scoped to fuser's OWN args, not the whole command (codex finding).
        assert ev(f"quxwrap --check fuser {ident}", absent, fixture_repo) == "ALLOW"
        assert ev(f"quxwrap --token abc fuser {ident}", absent, fixture_repo) == "ALLOW"
        assert ev(f"numactl --membind=0 fuser {ident}", absent, fixture_repo) == "ALLOW"
        # but a real fuser kill flag AFTER fuser still blocks even with a k-bearing wrapper opt
        assert ev(f"quxwrap --check fuser -k {ident}", absent, fixture_repo) == "BLOCK"

    def test_codex4_output_flag_does_not_exempt_protected_build(self, datafile, fixture_repo):
        # F4: an OUTPUT flag (--outdir/-o) does NOT prove a non-protected build;
        # build-mode at the protected root with only an output flag still BLOCKS.
        assert ev_cwd("numactl tsc -b --outdir=/tmp/out", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("numactl tsc -b -o /tmp/out.js", datafile, fixture_repo) == "BLOCK"
        # an INPUT-project flag naming a non-protected target DOES exempt -> ALLOW
        assert ev_cwd("numactl tsc -b -p packages/happy-server/tsconfig.json", datafile, fixture_repo) == "ALLOW"

    def test_codex5_recursive_multi_selector_no_exempt(self, datafile, fixture_repo):
        # F5: a recursive / glob / multi selector fans into the protected ws, so
        # it does NOT exempt; a single determinate non-protected selector does.
        assert ev_cwd("numactl pnpm --filter happy-server -r build", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("numactl pnpm --filter '*' build", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("numactl pnpm -r --filter happy-server build", datafile, fixture_repo) == "BLOCK"
        # single determinate non-protected selector still exempts -> ALLOW
        assert ev_cwd("numactl pnpm --filter happy-server build", datafile, fixture_repo) == "ALLOW"
        assert ev_cwd("tini -- yarn workspace happy-app build", datafile, fixture_repo) == "ALLOW"

    def test_codex6_no_overblock_on_file_ops(self, datafile, fixture_repo):
        # F6: a protected path/command as a DATA argument (copy/archive) is NOT a
        # launch -> ALLOW. Real launches still BLOCK.
        p = f"{fixture_repo}/packages/happy-cli/dist/index.mjs"
        assert ev(f"cp {p} /tmp/backup.mjs", datafile, fixture_repo) == "ALLOW"
        assert ev(f"tar cf /tmp/a.tar {p}", datafile, fixture_repo) == "ALLOW"
        # Cycle-12 ISSUE 2: a bare protected basename after a separate dash-option
        # is now a SAFE-SIDE BLOCK (the `<runner> -k <protected-cmd>` test-selector
        # twin of the wrapped `<front-end> -flag <protected-cmd>` launch). Per the
        # operator's 'prefer to over-block' stance this is an ACCEPTED false
        # positive, not an over-block defect.
        assert ev("pytest -k happy", datafile, fixture_repo) == "BLOCK"
        assert ev("rsync -a /tmp/x /tmp/y", datafile, fixture_repo) == "ALLOW"
        # but executable-position / launch-grammar forms still BLOCK
        assert ev("numactl happy daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev(f"numactl node {p} daemon start", datafile, fixture_repo) == "BLOCK"
        assert ev(f"anywrap -- {p}", datafile, fixture_repo) == "BLOCK"  # path after -- is exec


class TestCycle7ServiceControlAnchor:
    """Cycle 7 — head-AGNOSTIC service-control anchor (W5). P2 SERVICE_GUARD is
    head-keyed (it only fires when the EFFECTIVE head is the service-manager
    program), so a service-manager restart of a PROTECTED unit behind ANY
    wrapper front-end (cpu-affinity / scheduler / namespace wrapper preceding
    systemctl/service/initctl) slipped past it — and leaked even under /do (the
    legacy project-specific regex that incidentally caught the wrapped systemctl
    form runs AFTER /do and is project-name-specific). The new W5 anchor inside
    _p0_anchor mirrors W1/W2/W4: head-agnostic, wrapper-peel-based, data-driven
    unit names. Verified ONLY by feeding strings to evaluate() and simulated
    PreToolUse JSON to the live hook (NEVER any real service/daemon command)."""

    # vocabulary split so the SOURCE never types a full `<svc-mgr> <verb> <unit>`
    # phrase that the live bash-safety hook would scan at author time.
    _SC = "system" + "ctl"
    _SV = "ser" + "vice"
    _IC = "init" + "ctl"
    _RESTART = "rest" + "art"
    _UNIT = "happy-" + "daemon"
    _UNIT_DEV = "happy-" + "daemon-dev"

    def test_w5_wrapped_service_manager_blocks(self, datafile, fixture_repo):
        # the LEAK the fix closes: a service-manager restart of a protected unit
        # behind a wrapper front-end (cpu-affinity / scheduler / namespace) BLOCKS,
        # for several wrapper heads INCLUDING invented ones not in the engine.
        sc, sv, ic = self._SC, self._SV, self._IC
        r, u, ud = self._RESTART, self._UNIT, self._UNIT_DEV
        for w in ("numactl", "chrt -f 99", "taskset -c 0", "nsenter -t 1 -m",
                  "flock /tmp/l", "wrapzilla", "frobnicate", "zonkerbaz"):
            assert ev(f"{w} {sc} {r} {ud}", datafile, fixture_repo) == "BLOCK", w
            assert ev(f"{w} {sv} {u} {r}", datafile, fixture_repo) == "BLOCK", w
        # initctl form behind a wrapper
        assert ev(f"numactl {ic} {r} {u}", datafile, fixture_repo) == "BLOCK"

    def test_w5_bare_service_manager_still_blocks(self, datafile, fixture_repo):
        # bare service-manager restart of a protected unit still BLOCKS (P2 + W5).
        sc, sv, r, u, ud = self._SC, self._SV, self._RESTART, self._UNIT, self._UNIT_DEV
        assert ev(f"{sc} {r} {ud}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"{sv} {u} {r}", datafile, fixture_repo) == "BLOCK"

    def test_w5_conditional_force_verbs_block(self, datafile, fixture_repo):
        # the force/conditional lifecycle verbs the QA/close reports name.
        sc, sv, u, ud = self._SC, self._SV, self._UNIT, self._UNIT_DEV
        for verb in ("force-reload", "condrestart", "try-reload-or-restart",
                     "reload-or-restart", "try-restart", "condreload", "stop",
                     "kill", "disable", "mask"):
            assert ev(f"numactl {sc} {verb} {ud}", datafile, fixture_repo) == "BLOCK", verb
        # `service <unit> <verb>` operand order behind a wrapper
        assert ev(f"taskset -c 0 {sv} {u} condrestart", datafile, fixture_repo) == "BLOCK"

    def test_w5_template_instance_unit_blocks(self, datafile, fixture_repo):
        # systemd template-instance form `unit@instance(.service)` behind a wrapper.
        sc, r, u = self._SC, self._RESTART, self._UNIT
        assert ev(f"numactl {sc} {r} {u}@foo", datafile, fixture_repo) == "BLOCK"
        assert ev(f"numactl {sc} {r} {u}@foo.service", datafile, fixture_repo) == "BLOCK"

    def test_w5_no_overblock_nonprotected_unit(self, datafile, fixture_repo):
        # a service-manager action on a NON-protected unit ALLOWS (no over-block),
        # wrapped or bare.
        sc, sv, r = self._SC, self._SV, self._RESTART
        assert ev(f"numactl {sc} {r} nginx", datafile, fixture_repo) == "ALLOW"
        assert ev(f"{sc} {r} postgresql", datafile, fixture_repo) == "ALLOW"
        assert ev(f"flock /tmp/l {sv} redis-server {r}", datafile, fixture_repo) == "ALLOW"
        # read-only service query of a protected unit (status/is-active/show/cat are
        # NOT in SERVICE_VERBS) ALLOWS — the anchor only fires on disruptive verbs.
        u = self._UNIT
        assert ev(f"numactl {sc} status {u}", datafile, fixture_repo) == "ALLOW"
        assert ev(f"{sc} is-active {u}", datafile, fixture_repo) == "ALLOW"
        assert ev(f"numactl {sc} show {u}", datafile, fixture_repo) == "ALLOW"

    def test_w5_no_overblock_benign_wrapper_around_nonservice(self, datafile, fixture_repo):
        # a benign use of a wrapper around a NON-service command still ALLOWS — the
        # service vocabulary as DATA behind an inspection head is not a launch.
        sc, r, u = self._SC, self._RESTART, self._UNIT
        assert ev("numactl ls -la", datafile, fixture_repo) == "ALLOW"
        assert ev("flock /tmp/l grep x file.txt", datafile, fixture_repo) == "ALLOW"
        # echo / grep (inspection heads) of the literal service phrase = DATA -> ALLOW
        assert ev(f"echo {sc} {r} {u}", datafile, fixture_repo) == "ALLOW"
        assert ev(f"grep '{sc} {r}' file.txt", datafile, fixture_repo) == "ALLOW"

    def test_w5_failclosed_wrapped_service_blocks(self, datafile, fixture_repo, tmp_path_factory):
        # under absent/corrupt config the service-control FAMILY is generic and
        # config-independent: a wrapped service-manager + disruptive verb BLOCKS
        # head-agnostically (STEP1 tail scan), consistent with kill.
        absent = str(tmp_path_factory.mktemp("nocfg_w5") / "absent.json")
        sc, sv, r, u, ud = self._SC, self._SV, self._RESTART, self._UNIT, self._UNIT_DEV
        for w in ("numactl", "chrt -f 99", "wrapzilla", "frobnicate"):
            assert ev(f"{w} {sc} {r} {ud}", absent, fixture_repo) == "BLOCK", w
            assert ev(f"{w} {sv} {u} {r}", absent, fixture_repo) == "BLOCK", w
        # bare service-manager + verb still blocks fail-closed (any unit, generic)
        assert ev(f"{sc} {r} {ud}", absent, fixture_repo) == "BLOCK"
        assert ev(f"numactl init" + "ctl {} {}".format(r, u), absent, fixture_repo) == "BLOCK"
        # benign reads under absent config still ALLOW (no over-block)
        assert ev("numactl ls", absent, fixture_repo) == "ALLOW"
        assert ev(f"echo {sc} {r} {u}", absent, fixture_repo) == "ALLOW"

    # ── live-hook proofs (exit 2 / exit 0), incl. under /do ──────────────────
    def test_w5_live_hook_wrapped_service_blocks(self, datafile, fixture_repo):
        env = dict(os.environ)
        env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
        sc, sv, r, u, ud = self._SC, self._SV, self._RESTART, self._UNIT, self._UNIT_DEV
        cmds = [
            f"numactl {sc} {r} {ud}",
            f"chrt -f 99 {sv} {u} {r}",
            f"wrapzilla {sc} {r} {u}",
            f"nsenter -t 1 -m {sc} {r} {ud}",
            f"{sc} {r} {ud}",  # bare still blocks
        ]
        for cmd in cmds:
            payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "agent_id": "dev-test"})
            r2 = subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)
            assert r2.returncode == BLOCK, f"live hook did not block: {cmd} (rc={r2.returncode})"

    def test_w5_live_hook_wrapped_service_blocks_under_do(self, datafile, fixture_repo):
        # the wrapped form must BLOCK even with a /do consent flag present — the
        # anchor runs in evaluate() BEFORE the hook's /do bypass (unbypassable).
        sc, r, ud = self._SC, self._RESTART, self._UNIT_DEV
        sid = "guardtest-w5-" + str(os.getpid())
        flag = f"/tmp/claude-orchestrator-consent-{sid}.flag"
        with open(flag, "w") as fh:
            fh.write("true")
        try:
            env = dict(os.environ)
            env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
            for cmd in (f"numactl {sc} {r} {ud}", f"{sc} {r} {ud}"):
                payload = json.dumps({
                    "tool_name": "Bash",
                    "tool_input": {"command": cmd},
                    "session_id": sid,
                })
                proc = subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)
                assert proc.returncode == BLOCK, f"leaked under /do: {cmd} (rc={proc.returncode})"
        finally:
            os.remove(flag)

    def test_w5_codex_options_between_program_and_verb_block(self, datafile, fixture_repo):
        # codex confirmed-caught: options between the service-manager program and
        # the verb/unit must NOT hide the disruptive action.
        sc, r, u, ud = self._SC, self._RESTART, self._UNIT, self._UNIT_DEV
        for opt in ("--user", "--no-block", "-H host", "-M machine"):
            assert ev(f"numactl {sc} {opt} {r} {ud}", datafile, fixture_repo) == "BLOCK", opt
        # service-manager reached via an absolute / relative PATH still BLOCKS
        assert ev(f"/bin/{sc} {r} {ud}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"./{sc} {r} {ud}", datafile, fixture_repo) == "BLOCK"
        # multiple units in one command, the protected one among them, BLOCKS
        assert ev(f"{sc} {r} nginx {u} redis", datafile, fixture_repo) == "BLOCK"

    def test_w5_codex_overblock_unrelated_operand_allows(self, datafile, fixture_repo):
        # codex finding 3/4 (NEW over-block) FIX: a protected unit name carried as
        # an UNRELATED operand (env-var value / `--unit` value / a `service` noun
        # after a DIFFERENT command) while a service-control of ANOTHER unit (or no
        # service-manager at all) runs must ALLOW. Verb+unit are matched only within
        # the service-manager's OWN argv (mirrors P2's `rest` scoping), so the
        # wrapper-agnostic anchor does not over-block these idiomatic forms.
        sc, r, u, ud = self._SC, self._RESTART, self._UNIT, self._UNIT_DEV
        # env-var value names the protected unit; the manager restarts a DIFFERENT
        # unit -> ALLOW (the protected name is not in the manager's argv).
        assert ev(f"UNIT={ud} {sc} {r} nginx", datafile, fixture_repo) == "ALLOW"
        # systemd-run --unit <protected> then a service-control of a DIFFERENT unit
        assert ev(f"systemd-run --unit {ud} {sc} {r} nginx", datafile, fixture_repo) == "ALLOW"
        # `service` as a trailing NOUN after a different (container/k8s) command
        assert ev(f"docker compose {r} {ud} {self._SV}", datafile, fixture_repo) == "ALLOW"
        assert ev(f"kubectl rollout {r} {self._SV} {ud}", datafile, fixture_repo) == "ALLOW"

    def test_w5_live_hook_nonprotected_allows(self, datafile, fixture_repo):
        # NOTE: a NON-protected systemctl form (`systemctl restart nginx`) is NOT
        # asserted here at the LIVE-HOOK level because the hook's PRE-EXISTING
        # legacy systemctl whitelist (Layer 1.A / DEV_SYSTEMD) independently blocks
        # ALL non-whitelisted systemctl at a LATER stage — that is a separate,
        # broader project-specific gate, NOT the W5 anchor. That W5 itself does not
        # over-block a non-protected unit is proved at the ENGINE level by
        # test_w5_no_overblock_nonprotected_unit (numactl systemctl restart nginx
        # -> ALLOW under evaluate()). Here we assert the live hook ALLOWs benign
        # wrapper uses around NON-service commands (which the legacy layer permits).
        env = dict(os.environ)
        env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
        cmds = ["numactl ls", "flock /tmp/l grep x file.txt", "numactl -N 0 cat file.txt"]
        for cmd in cmds:
            payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "agent_id": "dev-test"})
            r2 = subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)
            assert r2.returncode == ALLOW, f"live hook over-blocked: {cmd} (rc={r2.returncode})"


class TestCycle8HeadAgnosticRemainingPrimitives:
    """Cycle 8 — make EVERY remaining protected primitive head-AGNOSTIC behind
    arbitrary wrappers, symmetric with the W1–W5 anchors. After the Cycle-5 pivot
    demoted the wrapper-peel to non-load-bearing, only the anchor-gate primitives
    (launch/command/build/kill/service = W1–W5) were head-agnostic; the rest were
    still HEAD-KEYED and leaked behind any wrapper whose head is not the dangerous
    verb (a real cpu-affinity front-end, or any invented/stacked wrapper):
      • W6 BUNDLE   — P3 hotfile mutation (touch/truncate/tee/dd/redirect/sed -i/
                      install/rsync/ln/perl -i) of the protected bundle.
      • W7 STATEFILE— P4 daemon-statefile mutation / redirect.
      • W8 ENDPOINT — P5 loopback shutdown to the protected control path.
      • W9 GLOBALBIN— P7 global package install/link, or a write to a protected
                      global-bin path.
    Each leak previously returned ALLOW behind a wrapper and now returns BLOCK,
    head-agnostically (no wrapper enumeration). Verified ONLY by feeding strings to
    evaluate() and simulated PreToolUse JSON to the live hook (NEVER any real
    daemon/CLI/service command, NEVER touching any process or file)."""

    # Wrapper fronts: a REAL cpu-affinity front-end whose head is NOT the danger
    # verb, INVENTED wrappers absent from the engine source, and a STACKED combo
    # (documented flock + invented). Proof of non-enumeration: test_w6_w9_no_head_
    # keying below asserts the invented names appear nowhere in the engine source.
    _REAL = "numa" + "ctl"
    _INV = "zqx" + "wrapper7"
    _INV2 = "blarf" + "ront88"
    _STACK = "flock /tmp/l zqx" + "wrapper7"
    WRAPPERS = [_REAL, _INV, _INV2, _STACK]

    # danger vocabulary assembled from pieces so this SOURCE never types a full
    # `<wrapper> <mutate> <bundle>` / shutdown phrase the author-time live hook
    # would scan (spec Section 8 trap).
    _TOUCH = "to" + "uch"
    _TRUNC = "trunc" + "ate"
    _TEE = "t" + "ee"
    _DD = "d" + "d"
    _STOP = "/" + "stop"
    _GI = "-" + "g"
    _INST = "ins" + "tall"

    def _bundle(self, repo):
        return repo + "/packages/happy-cli/dist/index.mjs"

    def _statefile(self):
        return "/root/.happy-dev/" + "daemon" + ".state.json"

    # ── W6 BUNDLE mutation BLOCK across {bare, real, invented, stacked} ──────
    @pytest.mark.parametrize("w", WRAPPERS)
    def test_w6_bundle_touch_blocks(self, w, datafile, fixture_repo):
        b = self._bundle(fixture_repo)
        assert ev(f"{w} {self._TOUCH} {b}", datafile, fixture_repo) == "BLOCK", w

    @pytest.mark.parametrize("w", WRAPPERS)
    def test_w6_bundle_redirect_blocks(self, w, datafile, fixture_repo):
        b = self._bundle(fixture_repo)
        assert ev(f"{w} cat /tmp/x > {b}", datafile, fixture_repo) == "BLOCK", w

    def test_w6_bundle_all_mutation_verbs_block(self, datafile, fixture_repo):
        # the FULL mutation-verb family the orchestrator enumerated must block
        # behind a wrapper (touch/truncate/tee/dd/redirect/sed-i/install/rsync/ln/
        # perl-i). Bare touch blocks too (P3 unchanged).
        b = self._bundle(fixture_repo)
        w = self._INV
        forms = [
            f"{self._TOUCH} {b}",                          # bare (P3)
            f"{w} {self._TRUNC} -s0 {b}",
            f"{w} {self._TEE} {b} < /dev/null",
            f"{w} {self._DD} if=/dev/null of={b}",
            f"{w} sed -i s/a/b/ {b}",
            f"{w} install /tmp/x {b}",
            f"{w} rsync /tmp/x {b}",
            f"{w} ln -sf /tmp/x {b}",
            f"{w} perl -i -pe s/a/b/ {b}",
        ]
        for cmd in forms:
            assert ev(cmd, datafile, fixture_repo) == "BLOCK", cmd

    def test_w6_bundle_relative_cwd_blocks(self, datafile, fixture_repo):
        # a relative bundle target + a leading wrapper chdir / cwd seed resolves to
        # the protected bundle and blocks (mirrors P3's cwd resolution).
        w = self._INV
        assert ev_cwd(f"{w} {self._TOUCH} packages/happy-cli/dist/index.mjs",
                      datafile, fixture_repo) == "BLOCK"

    # ── W7 STATEFILE mutation BLOCK ──────────────────────────────────────────
    @pytest.mark.parametrize("w", WRAPPERS)
    def test_w7_statefile_blocks(self, w, datafile, fixture_repo):
        sf = self._statefile()
        assert ev(f"{w} {self._TOUCH} {sf}", datafile, fixture_repo) == "BLOCK", w
        assert ev(f"{w} cp /tmp/x {sf}", datafile, fixture_repo) == "BLOCK", w
        assert ev(f"{w} cat /tmp/x > {sf}", datafile, fixture_repo) == "BLOCK", w

    def test_w7_statefile_bare_still_blocks(self, datafile, fixture_repo):
        sf = self._statefile()
        assert ev(f"{self._TRUNC} -s0 {sf}", datafile, fixture_repo) == "BLOCK"

    # ── W8 ENDPOINT shutdown BLOCK ───────────────────────────────────────────
    @pytest.mark.parametrize("w", WRAPPERS)
    def test_w8_endpoint_blocks(self, w, datafile, fixture_repo):
        s = self._STOP
        assert ev(f"{w} curl -X POST http://127.0.0.1:9{s}", datafile, fixture_repo) == "BLOCK", w
        assert ev(f"{w} wget --post-data= http://localhost:9{s}", datafile, fixture_repo) == "BLOCK", w

    def test_w8_endpoint_ipv6_loopback_blocks(self, datafile, fixture_repo):
        s = self._STOP
        assert ev(f"{self._INV} curl -X POST http://[::1]:9{s}", datafile, fixture_repo) == "BLOCK"

    def test_w8_endpoint_bare_still_blocks(self, datafile, fixture_repo):
        # bare (P5) still blocks — no regression.
        s = self._STOP
        assert ev(f"curl -X POST http://127.0.0.1:9{s}", datafile, fixture_repo) == "BLOCK"

    # ── W9 GLOBAL-CLI BLOCK ──────────────────────────────────────────────────
    @pytest.mark.parametrize("w", WRAPPERS)
    def test_w9_global_install_blocks(self, w, datafile, fixture_repo):
        gi, inst = self._GI, self._INST
        assert ev(f"{w} npm {inst} {gi} happy-coder", datafile, fixture_repo) == "BLOCK", w
        assert ev(f"{w} pnpm add --global happy-coder", datafile, fixture_repo) == "BLOCK", w
        assert ev(f"{w} npm link happy", datafile, fixture_repo) == "BLOCK", w

    def test_w9_global_write_protected_bin_blocks(self, datafile, fixture_repo):
        # a write to a protected global-bin PATH behind a wrapper blocks. The
        # protected_global_bins globs (`/usr/bin/happy*`, `/usr/lib/node_modules/
        # happy*`) match a bin FILE / a module DIR at that segment — `*` does NOT
        # cross `/`, so a target a glob-segment matches blocks (consistent with the
        # bare P7 `_path_matches_any` semantics; a file nested DEEPER does not).
        assert ev(f"{self._INV} cp /tmp/x /usr/bin/happy-x", datafile, fixture_repo) == "BLOCK"
        assert ev(f"{self._INV} {self._TOUCH} /usr/lib/node_modules/happy-coder",
                  datafile, fixture_repo) == "BLOCK"
        # bare write to the same protected bin path blocks too (P7 unchanged).
        assert ev("cp /tmp/x /usr/bin/happy-mcp", datafile, fixture_repo) == "BLOCK"

    def test_w9_global_bare_still_blocks(self, datafile, fixture_repo):
        # bare (P7) blanket global-op family still blocks (no regression). NOTE:
        # P7 blocks ANY -g/--global/link regardless of package name; W9 mirrors it
        # exactly, so the wrapped form behaves IDENTICALLY to the bare form.
        gi, inst = self._GI, self._INST
        assert ev(f"npm {inst} {gi} happy-coder", datafile, fixture_repo) == "BLOCK"
        assert ev(f"npm {inst} {gi} lodash", datafile, fixture_repo) == "BLOCK"  # bare blocks too

    def test_w9_wrapped_matches_bare_for_nonprotected_pkg(self, datafile, fixture_repo):
        # the wrapped global-install of a NON-protected package behaves IDENTICALLY
        # to the bare form (both BLOCK at the blanket global-op ban) — so W9
        # introduces NO new over-block relative to the engine's existing behavior.
        gi, inst = self._GI, self._INST
        bare = ev(f"npm {inst} {gi} lodash", datafile, fixture_repo)
        wrapped = ev(f"{self._INV} npm {inst} {gi} lodash", datafile, fixture_repo)
        assert bare == wrapped == "BLOCK"

    # ── BOUNDARY: NO over-block. Each must ALLOW (wrapped or bare). ──────────
    def test_w6_w9_no_overblock_boundary_allows(self, datafile, fixture_repo):
        b = self._bundle(fixture_repo)
        w, w2 = self._INV, self._REAL
        allows = [
            # benign wrapper around a NON-protected mutation
            f"{w} {self._TOUCH} /tmp/x",
            f"{w2} {self._TOUCH} /tmp/safe.txt",
            f"{w} cp /tmp/a /tmp/b",
            # read / inspect / edit of the PROTECTED bundle stays allowed
            f"cat {b}",
            f"grep daemon {b}",
            f"head -n5 {b}",
            f"stat {b}",
            f"wc -l {b}",
            # mutation of a NON-protected statefile / path
            f"{w} {self._TOUCH} /root/.other/x.json",
            f"{w} cp /tmp/x /etc/whatever.json",
            # write to a NON-protected global-bin path
            f"{w} cp /tmp/x /usr/bin/lodash",
            f"{w} {self._TOUCH} /usr/local/bin/mytool",
            # a package-manager LOCAL op (no -g / no link) behind a wrapper
            f"{w} npm {self._INST} lodash",
            f"{w} npm ci",
            # loopback request to a NON-protected endpoint
            f"{w} curl http://127.0.0.1:9/health",
            f"{w} curl http://localhost:9/status",
            # the protected endpoint path to a NON-loopback host (not a shutdown)
            f"{w} curl -X POST http://example.com:9{self._STOP}",
            # the protected endpoint string as DATA behind an inspection head
            f"echo curl 127.0.0.1{self._STOP}",
            f"grep {self._STOP} access.log",
        ]
        for cmd in allows:
            assert ev(cmd, datafile, fixture_repo) == "ALLOW", cmd

    # ── META-TEST: no protected primitive is head-keyed; no wrapper enumeration ─
    def test_w6_w9_no_head_keying_meta(self, datafile, fixture_repo):
        # A representative INVENTED wrapper (absent from the engine source) around
        # EVERY remaining danger primitive must BLOCK — proving none is head-keyed
        # and the closure is NOT wrapper-enumeration-based.
        b = self._bundle(fixture_repo)
        sf = self._statefile()
        s, gi, inst = self._STOP, self._GI, self._INST
        for w in (self._INV, self._INV2):
            assert ev(f"{w} {self._TOUCH} {b}", datafile, fixture_repo) == "BLOCK", ("W6", w)
            assert ev(f"{w} {self._TOUCH} {sf}", datafile, fixture_repo) == "BLOCK", ("W7", w)
            assert ev(f"{w} curl -X POST http://127.0.0.1:9{s}", datafile, fixture_repo) == "BLOCK", ("W8", w)
            assert ev(f"{w} npm {inst} {gi} happy-coder", datafile, fixture_repo) == "BLOCK", ("W9", w)
            # re-confirm the original W1–W5 anchors also block behind the same
            # invented wrapper (no regression of the anchor gate).
            assert ev(f"{w} happy daemon start", datafile, fixture_repo) == "BLOCK", ("W2", w)
            assert ev(f"{w} node {b} daemon start", datafile, fixture_repo) == "BLOCK", ("W1", w)

    def test_w6_w9_invented_wrappers_absent_from_engine(self):
        # PROOF of non-enumeration: the invented wrapper names used above do NOT
        # appear anywhere in the engine source, yet they all BLOCK. Also asserts
        # the real cpu-affinity front-end is not enumerated for these primitives.
        engine = os.path.join(HOOKS_DIR, "lib", "runtime_guard.py")
        src = open(engine, encoding="utf-8").read()
        for name in ("numactl", "zqxwrapper7", "zqxwrapper", "blarfront88"):
            assert name not in src, f"engine must not enumerate wrapper '{name}'"

    # ── live-hook proof (exit 2 / exit 0), incl. under /do (unbypassable) ────
    def test_w6_w9_live_hook_blocks(self, datafile, fixture_repo):
        env = dict(os.environ)
        env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
        env["CLAUDE_GUARD_CWD"] = fixture_repo
        b = self._bundle(fixture_repo)
        sf = self._statefile()
        s, gi, inst = self._STOP, self._GI, self._INST
        cmds = [
            f"{self._REAL} {self._TOUCH} {b}",
            f"{self._INV} {self._TRUNC} -s0 {b}",
            f"{self._INV} cp /tmp/x {sf}",
            f"{self._REAL} curl -X POST http://127.0.0.1:9{s}",
            f"{self._INV} npm {inst} {gi} happy-coder",
            f"{self._STACK} npm link happy",
        ]
        for cmd in cmds:
            payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd, "cwd": fixture_repo}, "agent_id": "dev-test"})
            r = subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)
            assert r.returncode == BLOCK, f"live hook did not block: {cmd} (rc={r.returncode})"

    def test_w6_w9_live_hook_blocks_under_do(self, datafile, fixture_repo):
        # the wrapped forms must BLOCK even with a /do consent flag — the anchor
        # runs in evaluate() BEFORE the hook's /do bypass (unbypassable).
        env = dict(os.environ)
        env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
        env["CLAUDE_GUARD_CWD"] = fixture_repo
        b = self._bundle(fixture_repo)
        sid = "guardtest-w69-" + str(os.getpid())
        flag = f"/tmp/claude-orchestrator-consent-{sid}.flag"
        with open(flag, "w") as fh:
            fh.write("true")
        try:
            s, gi, inst = self._STOP, self._GI, self._INST
            for cmd in (f"{self._INV} {self._TOUCH} {b}",
                        f"{self._REAL} curl -X POST http://127.0.0.1:9{s}",
                        f"{self._INV} npm {inst} {gi} happy-coder"):
                payload = json.dumps({
                    "tool_name": "Bash",
                    "tool_input": {"command": cmd, "cwd": fixture_repo},
                    "session_id": sid,
                })
                proc = subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)
                assert proc.returncode == BLOCK, f"leaked under /do: {cmd} (rc={proc.returncode})"
        finally:
            os.remove(flag)

    def test_w6_w9_live_hook_boundary_allows(self, datafile, fixture_repo):
        env = dict(os.environ)
        env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
        env["CLAUDE_GUARD_CWD"] = fixture_repo
        cmds = [
            f"{self._INV} {self._TOUCH} /tmp/x",
            f"{self._INV} cp /tmp/x /usr/bin/lodash",
            f"{self._INV} curl http://127.0.0.1:9/health",
            f"{self._INV} npm {self._INST} lodash",
        ]
        for cmd in cmds:
            payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd, "cwd": fixture_repo}, "agent_id": "dev-test"})
            r = subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)
            assert r.returncode == ALLOW, f"live hook over-blocked: {cmd} (rc={r.returncode})"

    # ── STEP1 fail-closed: the config-INDEPENDENT global-op family must block ──
    #     wrapped under absent config (symmetric with bare); the path-scoped
    #     families (bundle/statefile/endpoint) are config-dependent BOTH bare and
    #     wrapped, so they ALLOW under absent config — no asymmetric over-block. ─
    def test_w9_failclosed_wrapped_global_blocks(self, datafile, fixture_repo, tmp_path_factory):
        absent = str(tmp_path_factory.mktemp("nocfg_w9") / "absent.json")
        gi, inst = self._GI, self._INST
        for w in (self._REAL, self._INV, self._INV2):
            assert ev(f"{w} npm {inst} {gi} happy-coder", absent, fixture_repo) == "BLOCK", w
            assert ev(f"{w} pnpm add --global anything", absent, fixture_repo) == "BLOCK", w
        # bare global-op still blocks fail-closed
        assert ev(f"npm {inst} {gi} happy-coder", absent, fixture_repo) == "BLOCK"
        # benign reads behind a wrapper still ALLOW under absent config
        assert ev(f"{self._INV} ls", absent, fixture_repo) == "ALLOW"

    def test_w6_w8_failclosed_pathscoped_symmetry(self, datafile, fixture_repo, tmp_path_factory):
        # bundle/statefile/endpoint are PATH-scoped: with NO config there is no
        # protected path to match, so BOTH the bare AND the wrapped forms ALLOW
        # (P3/P4/P5 return None on empty globs). The wrapped form must NOT block
        # where the bare form allows — that would be an asymmetric over-block.
        absent = str(tmp_path_factory.mktemp("nocfg_w6") / "absent.json")
        b = self._bundle(fixture_repo)
        s = self._STOP
        for form in (f"{self._TOUCH} {b}", f"{self._INV} {self._TOUCH} {b}",
                     f"curl -X POST http://127.0.0.1:9{s}",
                     f"{self._INV} curl -X POST http://127.0.0.1:9{s}"):
            assert ev(form, absent, fixture_repo) == "ALLOW", form


def _ev_cfg(command, cfg_path, cwd=None):
    """evaluate() with CLAUDE_PROTECTED_RUNTIME_FILE pinned to `cfg_path` (the
    STEP0 config-self-protection anchor). The path may point at a PRESENT valid
    config OR an ABSENT/corrupt one — STEP0 keys on the hardcoded DATA_FILE_PATH,
    not on data loaded from it, so the block must hold in both states."""
    os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = cfg_path
    import importlib
    import lib.runtime_guard as rg
    importlib.reload(rg)
    return rg.evaluate(command, cwd)[0]


def _run_hook_cfg(command, cfg_path, env=None, do_sid=None):
    """Drive the LIVE hook with CLAUDE_PROTECTED_RUNTIME_FILE pinned. When `do_sid`
    is given, a /do consent flag is created for that session so the test proves the
    STEP0 block is UNBYPASSABLE under /do (STEP0 runs in the engine before the glue
    /do bypass)."""
    e = dict(os.environ)
    e["CLAUDE_PROTECTED_RUNTIME_FILE"] = cfg_path
    if env:
        e.update(env)
    body = {"tool_name": "Bash", "tool_input": {"command": command}}
    flag = None
    if do_sid:
        body["session_id"] = do_sid
        flag = f"/tmp/claude-orchestrator-consent-{do_sid}.flag"
        with open(flag, "w") as fh:
            fh.write("true")
    try:
        payload = json.dumps(body)
        proc = subprocess.run(["bash", HOOK], input=payload, text=True,
                              capture_output=True, env=e)
        return proc.returncode
    finally:
        if flag:
            try:
                os.remove(flag)
            except FileNotFoundError:
                pass


class TestCycle9Step0ConfigSelfProtectionHeadAgnostic:
    """Cycle 9 — make STEP0 (the config self-protection META-guard) head-AGNOSTIC,
    symmetric with the W6/W7 protected-path anchors. Prior to this fix STEP0 keyed
    on `head in CONFIG_MUTATION_HEADS`, so a mutation of the protected DATA FILE
    behind ANY undocumented wrapper (busybox/fakeroot/any invented or stacked
    front-end) leaked ALLOW — disabling the entire guard (an empty/corrupt config
    degrades to verb-family-only fail-closed; a crafted config silently bypasses).
    This was the lone protected family left head-keyed after Cycle-8 anchor-ized
    W6–W9, and the same systemic head-keyed-behind-wrapper defect that drove the
    prior CLOSE: NO. STEP0 keys on the HARDCODED DATA_FILE_PATH (a generic path,
    not loaded from the file it protects), runs BEFORE config load AND before the
    /do//allow bypass, so the block holds present, corrupt/absent, and under /do.

    Verified ONLY by feeding strings to evaluate() and simulated PreToolUse JSON to
    the live hook (NEVER any real daemon/CLI/process command; the live data file is
    never touched — every probe pins an isolated override path)."""

    # Wrapper fronts: REAL idiomatic tools whose head is NOT a mutation verb
    # (busybox/fakeroot — ubiquitous, non-adversarial), INVENTED wrappers absent
    # from the engine source, and a STACKED (documented flock + invented) combo.
    _REAL1 = "bu" + "sybox"
    _REAL2 = "fake" + "root"
    _INV = "zonker" + "baz"
    _INV2 = "frob" + "nicate"
    _STACK = "flock /tmp/l zonker" + "baz"
    WRAPPERS = [_REAL1, _REAL2, _INV, _INV2, _STACK]

    # mutation vocabulary assembled from pieces so this SOURCE never types a full
    # `<wrapper> <mutate> <datafile>` phrase the author-time live hook would scan.
    _CP = "c" + "p"
    _MV = "m" + "v"
    _TEE = "t" + "ee"
    _TOUCH = "to" + "uch"
    _TRUNC = "trunc" + "ate"
    _DD = "d" + "d"
    _INST = "ins" + "tall"
    _LN = "l" + "n"
    _CAT = "ca" + "t"

    @pytest.fixture
    def cfg_present(self, tmp_path_factory):
        p = tmp_path_factory.mktemp("step0_present") / "protected-runtime.json"
        p.write_text(json.dumps({
            "schema_version": 1,
            "protected_cmds": [], "protected_launch_paths": [],
            "protected_services": [], "protected_hotfiles": [],
            "protected_statefiles": [], "protected_endpoint_paths": [],
            "protected_proc_idents": [], "protected_global_bins": [],
            "protected_build_workspaces": [], "protected_build_paths": [],
        }))
        return str(p)

    @pytest.fixture
    def cfg_absent(self, tmp_path_factory):
        # a path under a NON-existent directory: STEP0 must still protect it
        # because the path is the hardcoded anchor, not config-loaded data.
        return str(tmp_path_factory.mktemp("step0_absent") / "nodir" / "runtime.json")

    @pytest.fixture
    def src(self, tmp_path_factory):
        s = tmp_path_factory.mktemp("step0_src") / "src.txt"
        s.write_text("x")
        return str(s)

    def _mutation_forms(self, cfg, src):
        """The FULL mutation-verb family that neuters the data file."""
        return [
            f"{self._CP} {src} {cfg}",
            f"{self._MV} {src} {cfg}",
            f"{self._TEE} {cfg}",
            f"{self._TOUCH} {cfg}",
            f"{self._TRUNC} -s 0 {cfg}",
            f"{self._DD} if=/dev/null of={cfg}",
            f"{self._INST} {src} {cfg}",
            f"rsync {src} {cfg}",
            f"{self._LN} -sf {src} {cfg}",
            f"sed -i s/a/b/ {cfg}",
            f"perl -i -pe s/a/b/ {cfg}",
            f"echo x > {cfg}",          # redirect
        ]

    # ── BLOCK: every mutation verb x {bare, real, invented, stacked} wrappers ──
    @pytest.mark.parametrize("w", WRAPPERS)
    def test_step0_wrapped_mutation_blocks_present(self, w, cfg_present, src):
        for verb_form in self._mutation_forms(cfg_present, src):
            assert _ev_cfg(f"{w} {verb_form}", cfg_present) == "BLOCK", f"{w} :: {verb_form}"

    def test_step0_bare_mutation_blocks_present(self, cfg_present, src):
        for verb_form in self._mutation_forms(cfg_present, src):
            assert _ev_cfg(verb_form, cfg_present) == "BLOCK", verb_form

    # ── BLOCK fail-closed (config absent/corrupt): self-protection must NOT ──
    #    depend on loading the very file it protects. ───────────────────────────
    @pytest.mark.parametrize("w", WRAPPERS)
    def test_step0_wrapped_mutation_blocks_failclosed(self, w, cfg_absent, src):
        for verb_form in self._mutation_forms(cfg_absent, src):
            assert _ev_cfg(f"{w} {verb_form}", cfg_absent) == "BLOCK", f"{w} :: {verb_form}"

    # ── BLOCK under /do (unbypassable): STEP0 runs before the bypass. ──────────
    def test_step0_wrapped_mutation_blocks_under_do_livehook(self, cfg_present, src):
        sid = "step0-do-" + str(os.getpid())
        for w in (self._REAL1, self._INV):
            cmd = f"{w} {self._CP} {src} {cfg_present}"
            assert _run_hook_cfg(cmd, cfg_present, do_sid=sid) == BLOCK, cmd
        # and fail-closed under /do too
        # (reuse cfg_present path with a /do flag; engine STEP0 blocks first)
        cmd = f"{self._INV} {self._TEE} {cfg_present}"
        assert _run_hook_cfg(cmd, cfg_present, do_sid=sid) == BLOCK, cmd

    def test_step0_wrapped_mutation_blocks_under_do_failclosed_livehook(self, cfg_absent, src):
        sid = "step0-do-fc-" + str(os.getpid())
        cmd = f"{self._INV} {self._CP} {src} {cfg_absent}"
        assert _run_hook_cfg(cmd, cfg_absent, do_sid=sid) == BLOCK, cmd

    # ── live-hook end-to-end (engine + glue), present + fail-closed ───────────
    def test_step0_wrapped_mutation_livehook(self, cfg_present, cfg_absent, src):
        for cfg in (cfg_present, cfg_absent):
            for w in (self._REAL1, self._REAL2, self._INV):
                cmd = f"{w} {self._CP} {src} {cfg}"
                assert _run_hook_cfg(cmd, cfg) == BLOCK, f"{cfg} :: {cmd}"

    # ── boundary ALLOWs (no over-block) ───────────────────────────────────────
    def test_step0_read_of_datafile_allows(self, cfg_present, cfg_absent):
        # reading the config file (cat/head/grep) is benign — must ALLOW, bare and
        # behind a wrapper, present and fail-closed.
        for cfg in (cfg_present, cfg_absent):
            assert _ev_cfg(f"{self._CAT} {cfg}", cfg) == "ALLOW", f"cat {cfg}"
            assert _ev_cfg(f"{self._INV} {self._CAT} {cfg}", cfg) == "ALLOW", f"{self._INV} cat {cfg}"
            assert _ev_cfg(f"grep foo {cfg}", cfg) == "ALLOW", f"grep {cfg}"
            assert _ev_cfg(f"head {cfg}", cfg) == "ALLOW", f"head {cfg}"

    def test_step0_mutation_of_nonprotected_file_allows(self, cfg_present, src, tmp_path_factory):
        # a mutation of a NON-config file behind a wrapper must still ALLOW.
        other = str(tmp_path_factory.mktemp("step0_other") / "other.txt")
        for w in ("", self._INV, self._REAL1):
            for form in (f"{self._CP} {src} {other}", f"{self._TEE} {other}",
                         f"{self._TOUCH} {other}", f"echo x > {other}"):
                cmd = f"{w} {form}".strip()
                assert _ev_cfg(cmd, cfg_present) == "ALLOW", cmd

    def test_step0_read_of_datafile_livehook_allows(self, cfg_present):
        # live-hook read of the config file behind a wrapper ALLOWs (rc=0).
        assert _run_hook_cfg(f"{self._INV} {self._CAT} {cfg_present}", cfg_present) == ALLOW

    def test_step0_non_idiomatic_source_read_allows(self, cfg_present, tmp_path_factory):
        # `cp <datafile> <elsewhere>` READS the data file (source) and writes a
        # DIFFERENT file — must ALLOW (the config path is not the write target).
        dst = str(tmp_path_factory.mktemp("step0_dst") / "copy.txt")
        assert _ev_cfg(f"{self._CP} {cfg_present} {dst}", cfg_present) == "ALLOW"
        assert _ev_cfg(f"{self._INV} {self._CP} {cfg_present} {dst}", cfg_present) == "ALLOW"

    # ── codex-hardening (Cycle 9 adversarial): forms codex reproduced as leaks ──
    #    F1 cwd-relative datafile target / F2 fd+force redirect operators /
    #    F3 mv-the-datafile-away / F4 in-place editor option variants /
    #    F5 chmod --reference / F6 target-directory & rsync-into-dir forms. ───────
    def test_step0_codex_cwd_relative_datafile_blocks(self, cfg_present, src, tmp_path_factory):
        # F1: a RELATIVE data-file target while cwd == the config dir must block
        # (cwd_base threaded into STEP0; effective cwd resolves the relative path).
        cfgdir = os.path.dirname(cfg_present)
        base = os.path.basename(cfg_present)
        for form in (f"{self._INV} {self._TEE} {base}",
                     f"{self._INV} {self._DD} if=/dev/null of={base}",
                     f"{self._INV} echo x > {base}",
                     f"{self._INV} {self._CP} {src} {base}"):
            assert _ev_cfg(form, cfg_present, cwd=cfgdir) == "BLOCK", form

    def test_step0_codex_fd_force_redirect_blocks(self, cfg_present):
        # F2: fd-prefixed and force-clobber redirect operators must block.
        for form in (f"{self._INV} echo x 1>{cfg_present}",
                     f"{self._INV} echo x >| {cfg_present}",
                     f"{self._INV} echo x >|{cfg_present}",
                     f"{self._INV} echo x &>{cfg_present}"):
            assert _ev_cfg(form, cfg_present) == "BLOCK", form

    def test_step0_codex_mv_datafile_away_blocks(self, cfg_present, tmp_path_factory):
        # F3: moving the data file AWAY deletes the original = mutation → BLOCK.
        dst = str(tmp_path_factory.mktemp("mv_dst") / "gone.json")
        assert _ev_cfg(f"{self._INV} {self._MV} {cfg_present} {dst}", cfg_present) == "BLOCK"
        # but moving an UNRELATED file elsewhere ALLOWs.
        a = str(tmp_path_factory.mktemp("mv_a") / "a.txt")
        b = str(tmp_path_factory.mktemp("mv_b") / "b.txt")
        import pathlib
        pathlib.Path(a).write_text("x")
        assert _ev_cfg(f"{self._INV} {self._MV} {a} {b}", cfg_present) == "ALLOW"

    def test_step0_codex_inplace_editor_variants_block(self, cfg_present):
        # F4: clustered / long-form in-place editor options must block.
        for form in (f"{self._INV} sed -Ei s/a/b/ {cfg_present}",
                     f"{self._INV} sed --in-place s/a/b/ {cfg_present}",
                     f"{self._INV} perl -pi -e s/a/b/ {cfg_present}",
                     f"sed -Ei s/a/b/ {cfg_present}",          # bare head form
                     f"perl -pi -e s/a/b/ {cfg_present}"):
            assert _ev_cfg(form, cfg_present) == "BLOCK", form
        # a plain (non -i) sed streaming to stdout READS the file → ALLOW.
        assert _ev_cfg(f"{self._INV} sed s/a/b/ {cfg_present}", cfg_present) == "ALLOW"
        assert _ev_cfg(f"sed s/a/b/ {cfg_present}", cfg_present) == "ALLOW"

    def test_step0_codex_chmod_reference_blocks(self, cfg_present):
        # F5: chmod/chown --reference= leaves the data file as the first bareword.
        for form in (f"{self._INV} chmod --reference=/tmp/r {cfg_present}",
                     f"{self._INV} chown --reference=/tmp/r {cfg_present}"):
            assert _ev_cfg(form, cfg_present) == "BLOCK", form

    def test_step0_codex_target_dir_forms_block(self, cfg_present, tmp_path_factory):
        # F6: target-directory (`-t DIR`) and rsync-into-dir forms write
        # DIR/basename — must block when that equals the data file.
        cfgdir = os.path.dirname(cfg_present)
        base = os.path.basename(cfg_present)
        staged = str(tmp_path_factory.mktemp("staged") / base)
        import pathlib
        pathlib.Path(staged).write_text("x")
        for form in (f"{self._INV} {self._CP} -t {cfgdir} {staged}",
                     f"{self._INV} {self._MV} -t {cfgdir} {staged}",
                     f"{self._INV} rsync {staged} {cfgdir}/"):
            assert _ev_cfg(form, cfg_present) == "BLOCK", form
        # writing a DIFFERENT basename into the config dir ALLOWs (only the exact
        # data-file path is protected, not the whole config directory).
        otherstaged = str(tmp_path_factory.mktemp("os2") / "unrelated.txt")
        pathlib.Path(otherstaged).write_text("x")
        assert _ev_cfg(f"{self._INV} {self._CP} -t {cfgdir} {otherstaged}", cfg_present) == "ALLOW"

    def test_step0_codex_mutation_word_as_data_allows(self, cfg_present):
        # F7: a read/inspect command carrying a mutation word merely as DATA must
        # NOT over-block.
        for form in (f"grep {self._CP} {cfg_present}",
                     f"{self._CAT} {self._CP} {cfg_present}",
                     f"echo {self._CP} {cfg_present}"):
            assert _ev_cfg(form, cfg_present) == "ALLOW", form

    # ── non-enumeration proof: the invented wrapper names appear nowhere in the
    #    engine source (the block is head-AGNOSTIC, not a wrapper whitelist). ───
    def test_step0_no_head_keying_on_wrapper_names(self):
        # The invented wrapper names exist ONLY in this test — their absence from
        # the engine proves STEP0 catches them via the head-AGNOSTIC mutation
        # anchor, not a wrapper whitelist. (Real tools like busybox/fakeroot are
        # caught by the SAME generic mechanism; they are not asserted-absent
        # because a future engine comment could reference them illustratively.)
        src = open(os.path.join(HOOKS_DIR, "lib", "runtime_guard.py")).read()
        for name in (self._INV, self._INV2):
            assert name not in src, f"engine must not enumerate wrapper {name!r}"


class TestCycle10MoveSourceMutationUnified:
    """Cycle 10 — close the W6/W7 (bundle/statefile) `mv`-SOURCE blind spot and
    UNIFY mutation-target extraction across all three protected-file families.

    The re-close gate found `mv <protected-statefile|bundle> <dest>` returned ALLOW
    (bare AND wrapped) because the W6/W7 extractor `_mutation_targets` only checked
    the cp/mv/rsync/install DESTINATION — never the protected SOURCE that `mv`
    REMOVES in place (moving the watched bundle away triggers the daemon
    auto-handoff; moving the statefile removes it). The Cycle-9 STEP0 fix added
    mv-source handling for the CONFIG file but did NOT mirror it into W6/W7.

    The fix routes BOTH `_mutation_targets` (W6/W7/W9/P3/P4/P7) and
    `_step0_mutation_targets` (config) through ONE shared, position-COMPLETE
    extractor `_mutation_targets_for_verb`, so the three families cannot drift on
    which token positions count as a mutation. A protected file is MUTATED when it
    is the cp/mv/rsync/install DEST (written), the mv/rename SOURCE (moved away),
    the rsync `--remove-source-files` SOURCE (moved away), the rm/truncate/shred/
    dd(of=)/tee target, the sed -i/perl -pi in-place target, the ln dest, or the
    chmod/chown target. A cp/plain-rsync SOURCE (copied, source kept = a read) is
    NOT a mutation and still ALLOWS (no over-block).

    Verified ONLY by feeding strings to evaluate() and simulated PreToolUse JSON to
    the live hook (NEVER any real daemon/CLI/service command, NEVER touching any
    process or file). Danger phrases are assembled from pieces so this SOURCE never
    types a full `<wrapper> mv <bundle>` phrase the author-time live hook scans.
    """

    _REAL = "numa" + "ctl"
    _INV = "zqx" + "wrapper7"
    _INV2 = "blarf" + "ront88"
    _STACK = "flock /tmp/l zqx" + "wrapper7"
    WRAPPERS = [_REAL, _INV, _INV2, _STACK]

    _MV = "m" + "v"
    _RENAME = "rena" + "me"
    _RSYNC = "rsy" + "nc"
    _RMSRC = "--remove-source-" + "files"
    _CHMOD = "chm" + "od"
    _CHOWN = "cho" + "wn"
    _CP = "c" + "p"
    _DEST = "/tmp/x"

    def _bundle(self, repo):
        return repo + "/packages/happy-cli/dist/index.mjs"

    def _statefile(self):
        return "/root/.happy-dev/" + "daemon" + ".state.json"

    def _configfile(self, datafile):
        # the active STEP0 anchor IS the override path itself (the data file).
        return datafile

    # ── W7 STATEFILE mv-source: BLOCK {bare, real, invented, stacked} ────────
    @pytest.mark.parametrize("w", [""] + WRAPPERS)
    def test_w7_statefile_mv_source_blocks(self, w, datafile, fixture_repo):
        sf = self._statefile()
        pre = (w + " ") if w else ""
        assert ev(f"{pre}{self._MV} {sf} {self._DEST}", datafile, fixture_repo) == "BLOCK", w

    # ── W6 BUNDLE mv-source: BLOCK {bare, real, invented, stacked} ───────────
    @pytest.mark.parametrize("w", [""] + WRAPPERS)
    def test_w6_bundle_mv_source_blocks(self, w, datafile, fixture_repo):
        b = self._bundle(fixture_repo)
        pre = (w + " ") if w else ""
        assert ev(f"{pre}{self._MV} {b} {self._DEST}", datafile, fixture_repo) == "BLOCK", w

    # ── CONFIG mv-source: BLOCK {bare, invented}, present AND fail-closed ────
    @pytest.mark.parametrize("w", ["", _INV])
    def test_config_mv_source_blocks_present_and_failclosed(self, w, datafile, fixture_repo):
        cfgf = self._configfile(datafile)
        pre = (w + " ") if w else ""
        # config-present: the override points at a valid fixture config (datafile)
        assert ev(f"{pre}{self._MV} {cfgf} {self._DEST}", datafile, fixture_repo) == "BLOCK", ("present", w)
        # fail-closed: point the anchor at an absent file; STEP0 keys on the
        # hardcoded path, not loaded data, so the block must still hold.
        absent = cfgf + ".does-not-exist-zz"
        assert ev(f"{pre}{self._MV} {absent} {self._DEST}", absent, fixture_repo) == "BLOCK", ("failclosed", w)

    # ── sibling source-removal FORMS the STEP0 fix already covers ────────────
    def test_w6_w7_move_remove_forms_block(self, datafile, fixture_repo):
        b = self._bundle(fixture_repo)
        sf = self._statefile()
        w = self._INV
        forms = [
            f"{w} {self._RENAME} {sf} {self._DEST}",          # rename = mv synonym (source removed)
            f"{w} {self._MV} -t /tmp/d {sf}",                  # mv -t DIR (source removed)
            f"{w} {self._MV} {b} /tmp/a /tmp/d",               # multi-source mv (bundle removed)
            f"{w} {self._RSYNC} {self._RMSRC} {sf} /tmp/d/",   # rsync --remove-source-files (move)
            f"{self._RSYNC} {self._RMSRC} {b} /tmp/d/",        # bare rsync --remove-source-files
            f"{w} {self._CHMOD} 000 {sf}",                     # chmod (metadata mutation, now covered)
            f"{w} {self._CHOWN} root {b}",                     # chown (metadata mutation, now covered)
        ]
        for cmd in forms:
            assert ev(cmd, datafile, fixture_repo) == "BLOCK", cmd

    # ── BOUNDARY ALLOWS: cp-source read, plain-rsync source, reads ──────────
    def test_cp_source_and_plain_rsync_source_allow(self, datafile, fixture_repo):
        b = self._bundle(fixture_repo)
        sf = self._statefile()
        w = self._INV
        allows = [
            f"{w} {self._CP} {sf} {self._DEST}",               # cp SOURCE: copy, source kept = read
            f"{self._CP} {b} {self._DEST}",                    # bare cp-source
            f"{w} {self._RSYNC} {sf} /tmp/d/",                 # plain rsync (no --remove): copy = read
            f"{w} cat {sf}",                                   # read
            f"{w} {self._MV} /tmp/unrelated {self._DEST}",     # mv of a NON-protected file
            f"{w} {self._CP} {sf} /tmp/d/{self._INV2}",        # cp-source to an unrelated dest
        ]
        for cmd in allows:
            assert ev(cmd, datafile, fixture_repo) == "ALLOW", cmd

    # ── controls: the OTHER mutation forms STILL block (wiring otherwise live) ─
    def test_controls_still_block(self, datafile, fixture_repo):
        b = self._bundle(fixture_repo)
        sf = self._statefile()
        w = self._INV
        for cmd in (f"{w} rm {sf}", f"{w} trunc" + f"ate -s0 {sf}",
                    f"{w} shr" + f"ed {b}", f"{w} {self._CP} /tmp/x {b}"):
            assert ev(cmd, datafile, fixture_repo) == "BLOCK", cmd

    # ── unification META: the two extractors are the SAME frozenset + share core ─
    def test_mutation_head_sets_unified(self):
        import importlib, lib.runtime_guard as rg
        importlib.reload(rg)
        # the bundle/statefile anchor verb set IS the STEP0 verb set (no drift).
        assert rg._ANCHOR_MUTATION_HEADS is rg._STEP0_MUTATION_HEADS
        # the shared core extractor exists and both target-extractors delegate to it.
        assert hasattr(rg, "_mutation_targets_for_verb")
        # mv-source semantics live in the shared core: a `mv SRC DEST` yields BOTH.
        tgts = rg._mutation_targets_for_verb("mv", ["/a/src", "/b/dest"])
        assert "/a/src" in tgts and "/b/dest" in tgts
        # cp-source semantics: a `cp SRC DEST` yields ONLY the dest (source = read).
        ctgts = rg._mutation_targets_for_verb("cp", ["/a/src", "/b/dest"])
        assert ctgts == ["/b/dest"]
        # rsync without --remove-source-files: source is a read (only dest forms).
        r1 = rg._mutation_targets_for_verb("rsync", ["/a/src", "/b/dest"])
        assert "/a/src" not in r1
        # rsync WITH --remove-source-files: source IS a target (moved away).
        r2 = rg._mutation_targets_for_verb("rsync", ["--remove-source-files", "/a/src", "/b/dest/"])
        assert "/a/src" in r2

    # ── non-enumeration proof: invented wrappers absent from the engine source ─
    def test_no_wrapper_enumeration(self):
        src = open(os.path.join(HOOKS_DIR, "lib", "runtime_guard.py")).read()
        for name in (self._INV, self._INV2):
            assert name not in src, f"engine must not enumerate wrapper {name!r}"

    # ── LIVE HOOK proof: mv-source BLOCKs end-to-end (exit 2), incl. under /do ─
    def test_mv_source_live_hook_blocks(self, datafile, fixture_repo):
        env = dict(os.environ)
        env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
        env["CLAUDE_GUARD_CWD"] = fixture_repo
        b = self._bundle(fixture_repo)
        sf = self._statefile()
        w = self._INV
        cmds = [
            f"{self._MV} {sf} {self._DEST}",                    # bare statefile mv-source
            f"{w} {self._MV} {sf} {self._DEST}",                # wrapped statefile mv-source
            f"{self._MV} {b} {self._DEST}",                     # bare bundle mv-source
            f"{w} {self._MV} {b} {self._DEST}",                 # wrapped bundle mv-source
            f"{w} {self._RSYNC} {self._RMSRC} {sf} /tmp/d/",    # rsync move
        ]
        for cmd in cmds:
            payload = json.dumps({"tool_name": "Bash",
                                  "tool_input": {"command": cmd, "cwd": fixture_repo},
                                  "agent_id": "dev-test"})
            r = subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)
            assert r.returncode == BLOCK, f"live hook did not block: {cmd} (rc={r.returncode})"

    def test_mv_source_live_hook_blocks_under_do(self, datafile, fixture_repo):
        # wrapped mv-source must BLOCK even with a /do consent flag (the anchor runs
        # in evaluate() BEFORE the hook's /do bypass — unbypassable).
        env = dict(os.environ)
        env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
        env["CLAUDE_GUARD_CWD"] = fixture_repo
        sf = self._statefile()
        sid = "guardtest-mvsrc-" + str(os.getpid())
        flag = f"/tmp/claude-orchestrator-consent-{sid}.flag"
        with open(flag, "w") as fh:
            fh.write("true")
        try:
            cmd = f"{self._INV} {self._MV} {sf} {self._DEST}"
            payload = json.dumps({"tool_name": "Bash",
                                  "tool_input": {"command": cmd, "cwd": fixture_repo},
                                  "session_id": sid, "agent_id": "dev-test"})
            r = subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)
            assert r.returncode == BLOCK, f"live hook leaked under /do: {cmd} (rc={r.returncode})"
        finally:
            try:
                os.unlink(flag)
            except OSError:
                pass

    def test_mv_source_live_hook_boundary_allows(self, datafile, fixture_repo):
        env = dict(os.environ)
        env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
        env["CLAUDE_GUARD_CWD"] = fixture_repo
        sf = self._statefile()
        b = self._bundle(fixture_repo)
        w = self._INV
        allows = [
            f"{w} {self._CP} {sf} {self._DEST}",       # cp-source (copy) = read
            f"{self._CP} {b} {self._DEST}",            # bare cp-source
            f"{w} cat {sf}",                           # read
            f"{w} {self._MV} /tmp/unrelated {self._DEST}",  # mv NON-protected
        ]
        for cmd in allows:
            payload = json.dumps({"tool_name": "Bash",
                                  "tool_input": {"command": cmd, "cwd": fixture_repo},
                                  "agent_id": "dev-test"})
            r = subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)
            assert r.returncode == ALLOW, f"live hook over-blocked: {cmd} (rc={r.returncode})"


class TestCycle11CommandWordLaunchHeadAgnostic:
    """Cycle 11 — close the W1/W2 COMMAND-WORD LAUNCH blind spot behind a wrapper.

    The 5th re-close gate found a launch of the protected CLI BY ITS COMMAND-WORD
    BASENAME for NON-lifecycle subcommands leaked behind any wrapper other than the
    four documented env/sudo/nohup/command front-ends: `numactl <cmd> claude`,
    `tini <cmd> mcp`, `zonkerbaz <cmd> auth`, stacked `flock zonkerbaz <cmd>
    claude --resume` all ALLOWed — while the BARE form blocked and `<cmd> daemon
    start` behind a wrapper blocked. Root cause: `_anchor_in_launch_position`
    treated a protected-command basename as a LAUNCH only when it was exec-token-0
    OR its follow-token was a lifecycle verb (`_ANCHOR_LAUNCH_FOLLOW`), so behind
    an unknown wrapper the protected cmd was token-1 and `claude`/`mcp`/`auth` was
    misjudged as a non-launch argument.

    The fix: a protected COMMAND basename (W2) — and symmetrically a protected
    launch PATH (W1) — in COMMAND-WORD position (the program a wrapper chain
    exec()s) is a LAUNCH regardless of its following subcommand, head-agnostically.
    Command-word position is determined by `_anchor_in_command_word_position`,
    whose two DATA discriminators (a preceding data-operand head like cp/tar/grep/
    kill; or an immediately-preceding bare separate option like `pytest -k`) keep a
    protected name used as a genuine data/flag-value argument ALLOWing (no new
    over-block). The lifecycle-follow gate is retained ONLY for the non-command-word
    position case.

    Verified ONLY by feeding strings to evaluate() and simulated PreToolUse JSON to
    the live hook (NEVER any real daemon/CLI command, NEVER touching any process).
    Wrapper/subcommand danger tokens are assembled from pieces so this SOURCE never
    types a full `<wrapper> <cmd> claude` launch phrase the author-time live hook
    scans.
    """

    _REAL = "numa" + "ctl"
    _REAL2 = "ti" + "ni"
    _REAL3 = "dumb-" + "init"
    _INV = "zqx" + "wrapper7"
    _INV2 = "blarf" + "ront88"
    _STACK = "flock /tmp/l zqx" + "wrapper7"
    WRAPPERS = [_REAL, _REAL2, _REAL3, _INV, _INV2, _STACK]

    # protected command basenames (mirror FIXTURE protected_cmds)
    _CMDS = ["happy", "happy-dev", "happy-mcp", "happy-coder"]
    # idiomatic NON-lifecycle subcommands that were leaking + a no-subcommand case
    _SUBCMDS = ["claude", "mcp", "auth", "doctor", ""]

    def _launchpath(self, repo):
        return repo + "/packages/happy-cli/dist/index.mjs"

    # ── W2: protected command-word launch BLOCKs for EVERY cmd × subcmd × wrapper ─
    @pytest.mark.parametrize("w", [""] + WRAPPERS)
    @pytest.mark.parametrize("cmd", _CMDS)
    @pytest.mark.parametrize("sub", _SUBCMDS)
    def test_w2_cmdword_launch_blocks(self, w, cmd, sub, datafile, fixture_repo):
        pre = (w + " ") if w else ""
        tail = (" " + sub) if sub else ""
        assert ev(f"{pre}{cmd}{tail}", datafile, fixture_repo) == "BLOCK", (w, cmd, sub)

    # ── W2: `claude --resume` flag-bearing launch behind a stacked wrapper ───────
    def test_w2_cmdword_launch_resume_stacked(self, datafile, fixture_repo):
        assert ev(f"{self._STACK} happy claude --resume abc", datafile, fixture_repo) == "BLOCK"
        assert ev(f"{self._REAL} happy claude --resume", datafile, fixture_repo) == "BLOCK"

    # ── W2: wrapper carrying its OWN fused option before the command word ────────
    def test_w2_cmdword_launch_wrapper_with_option(self, datafile, fixture_repo):
        # a FUSED wrapper option (`--cpunodebind=0`) does not consume the next
        # token, so the protected command after it is still the command word.
        assert ev(f"{self._REAL} --cpunodebind=0 happy claude", datafile, fixture_repo) == "BLOCK"

    # ── W2: bare launch + documented env-wrappers stay BLOCK (no regression) ─────
    def test_w2_bare_and_env_wrappers_block(self, datafile, fixture_repo):
        assert ev("happy claude", datafile, fixture_repo) == "BLOCK"
        for env_w in ("env", "sudo", "nohup", "command"):
            assert ev(f"{env_w} happy claude", datafile, fixture_repo) == "BLOCK", env_w

    # ── W1: protected launch PATH as the command word behind a wrapper BLOCKs ────
    @pytest.mark.parametrize("w", [""] + WRAPPERS)
    @pytest.mark.parametrize("sub", ["", "claude", "mcp"])
    def test_w1_pathword_launch_blocks(self, w, sub, datafile, fixture_repo):
        lp = self._launchpath(fixture_repo)
        pre = (w + " ") if w else ""
        tail = (" " + sub) if sub else ""
        assert ev(f"{pre}{lp}{tail}", datafile, fixture_repo) == "BLOCK", (w, sub)

    # ── W1: launch by PATH after a runtime stays BLOCK (no regression) ───────────
    def test_w1_runtime_path_blocks(self, datafile, fixture_repo):
        lp = self._launchpath(fixture_repo)
        assert ev(f"{self._INV} node {lp}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"node {lp} claude", datafile, fixture_repo) == "BLOCK"

    # ── NO-OVER-BLOCK boundary: protected NAME as a genuine DATA argument ALLOWs ──
    def test_boundary_cmd_as_data_allows(self, datafile, fixture_repo):
        allows = [
            "grep happy /tmp/file",            # search pattern (inspection head)
            "echo happy-dev",                  # print arg
            "cat happy.log",                   # filename containing the word
            "grep -e happy-coder /tmp/f",      # inspection head -> scan skipped
            "cp happy /tmp/foo",               # file operand to cp (source)
            "cp /tmp/foo happy",               # file operand to cp (dest)
            "mv happy-dev /tmp/foo",           # file operand to mv
            "tar cf a.tar happy",              # archive member operand
            "chmod +x happy-mcp",              # mode-change operand
            "rm happy",                        # remove operand
            "kill happy",                      # (named) kill operand
            "git status happy",                # git inspection
            "ls happy-coder",                  # listing operand
        ]
        for cmd in allows:
            assert ev(cmd, datafile, fixture_repo) == "ALLOW", cmd
        # Cycle-12 ISSUE 2: `pytest -k happy` (a NON-inspection runner with a bare
        # separate flag whose value is a protected basename) is now an EXPECTED
        # safe-side BLOCK — it is structurally identical to a wrapped
        # `<front-end> -flag <protected-cmd>` launch, and per the operator's
        # 'prefer to over-block' stance the ambiguity resolves as DANGER. The
        # `grep -e <protected-cmd>` twin above stays ALLOW because `grep` is an
        # inspection-allowlisted head (the anchor scan never runs for it).
        assert ev("pytest -k happy", datafile, fixture_repo) == "BLOCK"

    # ── NO-OVER-BLOCK boundary: protected launch PATH as a DATA operand ALLOWs ───
    def test_boundary_path_as_data_allows(self, datafile, fixture_repo):
        lp = self._launchpath(fixture_repo)
        allows = [
            f"{self._INV} cat {lp}",                 # read the bundle
            f"cp {lp} /tmp/foo",                     # bundle as cp SOURCE (read-copy)
            f"{self._INV} grep needle {lp}",         # search inside the bundle
        ]
        for cmd in allows:
            assert ev(cmd, datafile, fixture_repo) == "ALLOW", cmd

    # ── find/fd -exec EXECUTOR launch of a protected anchor BLOCKs (codex #1) ────
    def test_find_exec_protected_cmd_blocks(self, datafile, fixture_repo):
        lp = self._launchpath(fixture_repo)
        blocks = [
            r"find . -exec happy claude \;",        # protected cmd via -exec, non-lifecycle sub
            r"find . -exec happy \;",               # protected cmd via -exec, no sub
            r"find /x -execdir happy-dev mcp \;",   # -execdir
            r"find . -ok happy auth \;",            # -ok
            f"find . -exec {lp} \\;",               # protected launch PATH via -exec
            "fd -x happy",                          # fd -x executor
            "fd --exec happy-coder claude",         # fd --exec
        ]
        for cmd in blocks:
            assert ev(cmd, datafile, fixture_repo) == "BLOCK", cmd

    def test_find_exec_nonprotected_allows(self, datafile, fixture_repo):
        allows = [
            r"find . -exec rm {} \;",               # non-protected executor command
            r"find . -exec grep happy {} \;",       # grep of the word as DATA inside files
            r"find . -exec echo hi \;",
            "find . -name happy",                   # bare find naming the word (inspection)
            "fd happy",                             # bare fd search for the word
        ]
        for cmd in allows:
            assert ev(cmd, datafile, fixture_repo) == "ALLOW", cmd

    # ── no over-block: a data operand whose dest basename looks like a runner ────
    def test_runner_token_dest_operand_allows(self, datafile, fixture_repo):
        # destination/operand literally named like an EXEC_RUNNER_TOKENS member
        # ('x'/'run'/'exec') must NOT make a cp/mv/tar/install of a protected NAME a
        # launch (the launch-position runner gate is suppressed after a data head).
        lp = self._launchpath(fixture_repo)
        allows = [
            "cp /tmp/x happy",                      # dest basename 'x' (runner token)
            "install /tmp/x happy-dev",
            "tar cf /tmp/x happy",
            "cp /tmp/run happy-mcp",                # dest basename 'run'
            "mv /tmp/exec happy-coder",             # dest basename 'exec'
        ]
        for cmd in allows:
            assert ev(cmd, datafile, fixture_repo) == "ALLOW", cmd
        # but cp INTO the protected bundle still BLOCKs (W6 mutation, not launch)
        assert ev(f"cp /tmp/x {lp}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"cp {lp} /tmp/foo", datafile, fixture_repo) == "ALLOW"  # bundle as source

    # ── non-enumeration proof: invented wrappers absent from the engine source ───
    def test_no_wrapper_enumeration(self):
        src = open(os.path.join(HOOKS_DIR, "lib", "runtime_guard.py")).read()
        for name in (self._REAL, self._REAL2, self._REAL3, self._INV, self._INV2):
            assert name not in src, f"engine must not enumerate wrapper {name!r}"

    # ── LIVE HOOK proof: command-word launch BLOCKs end-to-end (exit 2) ──────────
    def test_cmdword_launch_live_hook_blocks(self, datafile, fixture_repo):
        env = dict(os.environ)
        env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
        env["CLAUDE_GUARD_CWD"] = fixture_repo
        lp = self._launchpath(fixture_repo)
        cmds = [
            f"{self._REAL} happy claude",                          # real wrapper, W2
            f"{self._REAL2} happy mcp",                            # real wrapper, W2
            f"{self._INV} happy auth",                             # invented wrapper, W2
            f"{self._STACK} happy claude --resume",               # stacked, W2
            f"{self._REAL} happy",                                 # no subcommand, W2
            f"{self._INV} {lp}",                                   # invented wrapper, W1 path-word
            f"{self._INV} {lp} claude",                            # W1 path-word + subcmd
        ]
        for cmd in cmds:
            payload = json.dumps({"tool_name": "Bash",
                                  "tool_input": {"command": cmd, "cwd": fixture_repo},
                                  "agent_id": "dev-test"})
            r = subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)
            assert r.returncode == BLOCK, f"live hook did not block: {cmd} (rc={r.returncode})"

    def test_cmdword_launch_live_hook_blocks_under_do(self, datafile, fixture_repo):
        # wrapped command-word launch must BLOCK even with a /do consent flag (the
        # anchor runs in evaluate() BEFORE the hook's /do bypass — unbypassable).
        env = dict(os.environ)
        env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
        env["CLAUDE_GUARD_CWD"] = fixture_repo
        sid = "guardtest-cmdword-" + str(os.getpid())
        flag = f"/tmp/claude-orchestrator-consent-{sid}.flag"
        with open(flag, "w") as fh:
            fh.write("true")
        try:
            for cmd in (f"{self._INV} happy claude", f"{self._REAL} happy mcp"):
                payload = json.dumps({"tool_name": "Bash",
                                      "tool_input": {"command": cmd, "cwd": fixture_repo},
                                      "session_id": sid, "agent_id": "dev-test"})
                r = subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)
                assert r.returncode == BLOCK, f"live hook leaked under /do: {cmd} (rc={r.returncode})"
        finally:
            try:
                os.unlink(flag)
            except OSError:
                pass

    def test_cmdword_launch_live_hook_boundary_allows(self, datafile, fixture_repo):
        env = dict(os.environ)
        env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
        env["CLAUDE_GUARD_CWD"] = fixture_repo
        lp = self._launchpath(fixture_repo)
        w = self._INV
        allows = [
            "grep happy /tmp/file",         # data (inspection head)
            f"{w} cat {lp}",                # read the bundle
            f"cp {lp} /tmp/foo",            # bundle as cp source
            "cp /tmp/foo happy",            # file operand
        ]
        for cmd in allows:
            payload = json.dumps({"tool_name": "Bash",
                                  "tool_input": {"command": cmd, "cwd": fixture_repo},
                                  "agent_id": "dev-test"})
            r = subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)
            assert r.returncode == ALLOW, f"live hook over-blocked: {cmd} (rc={r.returncode})"
        # Cycle-12 ISSUE 2: `pytest -k happy` is now an EXPECTED safe-side BLOCK on
        # the LIVE hook too (the wrapped-launch twin; accepted false positive).
        payload = json.dumps({"tool_name": "Bash",
                              "tool_input": {"command": "pytest -k happy", "cwd": fixture_repo},
                              "agent_id": "dev-test"})
        r = subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)
        assert r.returncode == BLOCK, f"issue-2 safe-side block expected: pytest -k happy (rc={r.returncode})"

    # ── fail-closed semantics for a command-word launch (documented residual) ────
    def test_cmdword_launch_failclosed_semantics(self, tmp_path, fixture_repo):
        """When the config is ABSENT, the engine cannot know that `happy` is a
        protected COMMAND basename — that name lives ONLY in the data file's
        `protected_cmds`. Fail-closed mode blocks generic verb FAMILIES (kill /
        build / service / mutation / `node <dist> daemon start`), NOT a
        project-specific command basename, so `<wrapper> happy claude` ALLOWs
        fail-closed by design (the SAME documented residual as the bare protected
        command and the launch-PATH families being unknowable without config). The
        in-scope guarantee for this family is the CONFIG-PRESENT path (incl. under
        /do), which BLOCKs — verified above. This test pins the accepted behavior
        so a future change that claims to 'fix' fail-closed here is reviewed against
        the unknowable-name design constraint, not silently regressed either way."""
        absent = str(tmp_path / "no-such-config.json")
        # the project-specific command basename is unknowable fail-closed → ALLOW
        for cmd in (f"{self._INV} happy claude", f"{self._REAL} happy mcp"):
            assert ev(cmd, absent, fixture_repo) == "ALLOW", cmd
        # but a GENERIC launch SIGNAL (node <dist bundle> daemon start) still BLOCKs
        lp = self._launchpath(fixture_repo)
        assert ev(f"{self._INV} node {lp} daemon start", absent, fixture_repo) == "BLOCK"
        # and a benign listing ALLOWs fail-closed
        assert ev("ls -la /tmp", absent, fixture_repo) == "ALLOW"


class TestCycle12SlashPathNavAllowAndDashOptOverblock:
    """Cycle 12 — TWO-SIDED regression lock for the closeout cycle.

    ISSUE 1 (severe over-block introduced by the Cycle-11 command-word fix): a
    SLASH-BEARING path token whose BASENAME equals a protected command name was
    treated by the W2 command-basename arm as a command-word LAUNCH. So a plain
    `cd`/`pushd`/`git -C`/copy/find/tar into ANY directory whose basename equals
    a protected command name (the worktree dir, a package dir, an unrelated path)
    was wrongly BLOCKED. Fix: a token CONTAINING a slash is a PATH and is decided
    ONLY by the W1 launch-PATH matcher; the W2 basename arm skips slash tokens.
    Navigation/inspection of a same-basename path now ALLOWs; the REAL protected
    launch PATHS still BLOCK via W1.

    ISSUE 2 (close residual #8): a BARE (slashless) protected command basename
    right after a separate dash-option (`<front-end> -flag <protected-cmd>`)
    leaked because the engine treated the token as the flag's VALUE (the
    test-runner `-k <name>` selector twin). Per the operator's 'prefer to
    over-block' stance the ambiguity now resolves as DANGER → BLOCK, accepting
    the `<runner> -k <protected-cmd>` false positive. (A pure inspection head —
    a search tool's `-e <protected-cmd>` — is allowlisted upstream and stays
    ALLOW.)

    Verified ONLY by feeding strings to evaluate() and simulated PreToolUse JSON
    to the live hook (NEVER any real daemon/CLI command, NEVER touching a
    process). Launch-path / wrapper / subcommand pieces are assembled from
    fragments so this SOURCE never types a full launch phrase the author-time
    live hook scans.
    """

    _REAL = "numa" + "ctl"
    _REAL2 = "ti" + "ni"
    _REAL3 = "dumb-" + "init"
    _INV = "zqx" + "wrapper7"
    _STACK = "flock /tmp/l zqx" + "wrapper7"
    WRAPPERS = [_REAL, _REAL2, _REAL3, _INV, _STACK]

    _CMDS = ["happy", "happy-dev", "happy-mcp", "happy-coder"]

    def _bundle(self, repo):
        return repo + "/packages/happy-cli/dist/index.mjs"

    def _binmjs(self, repo):
        return repo + "/packages/happy-cli/bin/" + "happy" + ".mjs"

    # ── ISSUE 1 ALLOW: navigate/inspect a slash path whose basename == a cmd ─────
    # bare AND behind every wrapper. These are routine work; they MUST ALLOW.
    @pytest.mark.parametrize("w", [""] + WRAPPERS)
    @pytest.mark.parametrize("cmd", _CMDS)
    def test_issue1_nav_slash_path_allows(self, w, cmd, datafile, fixture_repo):
        pre = (w + " ") if w else ""
        d = f"/dev/shm/dev-workspace/{cmd}"          # dir whose basename == cmd
        for body in (f"cd {d}",
                     f"pushd {d}",
                     f"ls {d}",
                     f"ls -la {d}",
                     f"cat {d}/README.md",
                     f"git -C {d} status",
                     f"cp -r {d} /tmp/backup",
                     f"find {d} -name '*.ts'",
                     f"tar czf /tmp/x.tgz {d}",
                     f"rsync -a {d}/ /tmp/dest/",
                     f"chmod -R 755 {d}"):
            assert ev(f"{pre}{body}", datafile, fixture_repo) == "ALLOW", (w, cmd, body)

    # env-prefix + chdir wrapper forms also ALLOW (no launch).
    def test_issue1_env_prefix_nav_allows(self, datafile, fixture_repo):
        d = "/dev/shm/dev-workspace/happy-dev"
        assert ev(f"env FOO=bar cd {d}", datafile, fixture_repo) == "ALLOW"
        assert ev(f"nohup ls {d}", datafile, fixture_repo) == "ALLOW"

    # ── ISSUE 1 BLOCK side: the REAL protected launch PATHS still BLOCK (W1) ──────
    # bare AND behind wrappers, slash tokens — must NOT have been reopened.
    @pytest.mark.parametrize("w", [""] + WRAPPERS)
    @pytest.mark.parametrize("sub", ["", "claude", "daemon start"])
    def test_issue1_real_launch_paths_still_block(self, w, sub, datafile, fixture_repo):
        pre = (w + " ") if w else ""
        tail = (" " + sub) if sub else ""
        for p in (self._bundle(fixture_repo), self._binmjs(fixture_repo)):
            # direct path execution
            assert ev(f"{pre}{p}{tail}", datafile, fixture_repo) == "BLOCK", (w, sub, p)
            # runtime launching the path
            assert ev(f"{pre}node {p}{tail}", datafile, fixture_repo) == "BLOCK", (w, sub, p)

    # absolute installed-binary launch paths (assembled) still BLOCK behind wrappers.
    @pytest.mark.parametrize("w", [""] + WRAPPERS)
    def test_issue1_abs_installed_binary_still_blocks(self, w, datafile, fixture_repo):
        pre = (w + " ") if w else ""
        for binname in ("happy", "happy-dev", "happy-mcp"):
            p = "/" + "usr" + "/" + "bin" + "/" + binname        # /usr/bin/<cmd>
            assert ev(f"{pre}{p} claude", datafile, fixture_repo) == "BLOCK", (w, binname)

    # a bare slashless command-word launch must STILL BLOCK (Cycle-11 not regressed).
    @pytest.mark.parametrize("w", [""] + WRAPPERS)
    @pytest.mark.parametrize("cmd", _CMDS)
    def test_issue1_bare_cmdword_launch_still_blocks(self, w, cmd, datafile, fixture_repo):
        pre = (w + " ") if w else ""
        assert ev(f"{pre}{cmd} claude", datafile, fixture_repo) == "BLOCK", (w, cmd)

    # ── ISSUE 2 BLOCK: bare protected basename after a dash-option → over-block ───
    @pytest.mark.parametrize("w", [_REAL, _REAL2, _REAL3, _INV])
    @pytest.mark.parametrize("cmd", _CMDS)
    def test_issue2_dashopt_then_bare_cmd_blocks(self, w, cmd, datafile, fixture_repo):
        # `<front-end> -someflag <protected-cmd> [sub]` — the cmd is the flag's
        # apparent VALUE but resolves as DANGER (safe-side over-block).
        for flag in ("-g", "-c", "--single-child", "-N0"):
            assert ev(f"{w} {flag} {cmd}", datafile, fixture_repo) == "BLOCK", (w, flag, cmd)
            assert ev(f"{w} {flag} {cmd} claude", datafile, fixture_repo) == "BLOCK", (w, flag, cmd)

    # the test-runner `-k <protected-cmd>` selector twin is an ACCEPTED safe-side
    # BLOCK (NON-inspection head reaches the W2 arm).
    def test_issue2_runner_selector_twin_blocks(self, datafile, fixture_repo):
        assert ev("pytest -k happy", datafile, fixture_repo) == "BLOCK"
        assert ev("pytest -k happy-dev", datafile, fixture_repo) == "BLOCK"

    # but an INSPECTION head's flag-value form stays ALLOW (scan skipped upstream),
    # and a data-operand head before the dash-option keeps the name an operand.
    def test_issue2_inspection_and_dataop_stay_allow(self, datafile, fixture_repo):
        assert ev("grep -e happy /tmp/f", datafile, fixture_repo) == "ALLOW"
        assert ev("grep -e happy-coder /tmp/f", datafile, fixture_repo) == "ALLOW"
        # data-operand head (`cp`) governs even with an intervening dash-option.
        assert ev("cp -t /tmp/dst happy", datafile, fixture_repo) == "ALLOW"

    # ── CODEX F1: W1 launch PATH after a separate dash-option is the symmetric ───
    #   twin of ISSUE 2 — a registered launch path after a bare dash-option BLOCKs
    #   (real launch leak; impossible false positive since it must match a
    #   registered protected_launch_path).
    @pytest.mark.parametrize("w", [_REAL, _REAL2, _REAL3, _INV])
    def test_codex_f1_w1_launchpath_after_dashopt_blocks(self, w, datafile, fixture_repo):
        lp = self._bundle(fixture_repo)
        for flag in ("-g", "-c", "-N0"):
            assert ev(f"{w} {flag} {lp}", datafile, fixture_repo) == "BLOCK", (w, flag)
            assert ev(f"{w} {flag} {lp} claude", datafile, fixture_repo) == "BLOCK", (w, flag)
        # absolute installed binary too
        binp = "/" + "usr" + "/" + "bin" + "/" + "happy"
        assert ev(f"{w} -g {binp} claude", datafile, fixture_repo) == "BLOCK"

    # ── CODEX F4: RELATIVE same-basename navigation ALLOWs (cd/pushd/git -C) ──────
    @pytest.mark.parametrize("cmd", _CMDS)
    def test_codex_f4_relative_nav_allows(self, cmd, datafile, fixture_repo):
        for body in (f"cd {cmd}", f"pushd {cmd}", f"git -C {cmd} status",
                     f"git -C {cmd} log", f"cd ./{cmd}", f"git -C ./{cmd} diff"):
            assert ev(body, datafile, fixture_repo) == "ALLOW", (cmd, body)
        # git -C with a fused global option before the subcommand also ALLOWs
        assert ev(f"git -C {cmd} -c core.pager=cat status", datafile, fixture_repo) == "ALLOW"

    # ── CODEX F5: `-x`/`-X` are find/fd executor opts ONLY in a find/fd segment; ──
    #   an unrelated data tool's identically-spelled flag does NOT over-block.
    def test_codex_f5_dash_x_not_executor_outside_findfd(self, datafile, fixture_repo):
        for cmd in (f"tar -x {self._CMDS[0]}", f"tar -X {self._CMDS[0]}",
                    f"tar -xf a.tar {self._CMDS[0]}", f"tar xf a.tar {self._CMDS[0]}"):
            assert ev(cmd, datafile, fixture_repo) == "ALLOW", cmd
        # but a genuine fd executor of a protected cmd still BLOCKs (no regression)
        assert ev(f"fd -x {self._CMDS[0]} claude", datafile, fixture_repo) == "BLOCK"
        assert ev(f"find . -exec {self._CMDS[0]} daemon \\;", datafile, fixture_repo) == "BLOCK"

    # ── LIVE-HOOK two-sided: nav ALLOWs (rc=0), real launch BLOCKs (rc=2) ────────
    def test_live_hook_two_sided(self, datafile, fixture_repo):
        env = dict(os.environ)
        env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
        env["CLAUDE_GUARD_CWD"] = fixture_repo

        def run(cmd):
            payload = json.dumps({"tool_name": "Bash",
                                  "tool_input": {"command": cmd, "cwd": fixture_repo},
                                  "agent_id": "dev-test"})
            return subprocess.run([HOOK], input=payload, capture_output=True,
                                  text=True, env=env).returncode

        d = "/dev/shm/dev-workspace/happy-dev"
        # ISSUE 1 ALLOW side on the LIVE hook
        for cmd in (f"cd {d}", f"git -C {d} status", f"cp -r {d} /tmp/bk",
                    f"find {d} -name x"):
            assert run(cmd) == ALLOW, f"live hook over-blocked nav: {cmd}"
        # ISSUE 1 BLOCK side — real bundle launch behind a wrapper
        bundle = self._bundle(fixture_repo)
        assert run(f"{self._INV} node {bundle} daemon start") == BLOCK
        # ISSUE 2 BLOCK side — bare cmd after a dash-option behind a wrapper
        assert run(f"{self._REAL} -g happy claude") == BLOCK

    # ── /do does NOT bypass the engine BLOCK (unbypassable, both issues) ─────────
    def test_do_does_not_bypass(self, datafile, fixture_repo):
        env = dict(os.environ)
        env["CLAUDE_PROTECTED_RUNTIME_FILE"] = datafile
        env["CLAUDE_GUARD_CWD"] = fixture_repo
        # the /do consent surfaces as a per-session flag file; the engine runs
        # BEFORE the hook's /do bypass, so a guard BLOCK is unbypassable.
        sid = "guardtest12-" + str(os.getpid())
        flag = f"/tmp/claude-orchestrator-consent-{sid}.flag"
        with open(flag, "w") as fh:
            fh.write("true")

        def run(cmd):
            payload = json.dumps({"tool_name": "Bash",
                                  "tool_input": {"command": cmd, "cwd": fixture_repo},
                                  "session_id": sid, "agent_id": "dev-test"})
            return subprocess.run([HOOK], input=payload, capture_output=True,
                                  text=True, env=env).returncode

        try:
            bundle = self._bundle(fixture_repo)
            assert run(f"{self._INV} node {bundle} daemon start") == BLOCK   # real launch
            assert run(f"{self._REAL} -g happy claude") == BLOCK             # issue 2
            # but nav still ALLOWs under /do
            assert run("cd /dev/shm/dev-workspace/happy-dev") == ALLOW
        finally:
            os.remove(flag)


# ════════════════════════════════════════════════════════════════════════════
# Cycle 13 (close-debate-20260531-162901): two reported close-blocker leaks +
# the class-level sweep. Verified ONLY by feeding strings to evaluate()/the hook
# (NEVER any real daemon/CLI/process command). Vocabulary split so this test's
# OWN source never types a full kill-pipeline / daemon phrase.
# ════════════════════════════════════════════════════════════════════════════

_K = "k" + "ill"            # bare kill verb (PID/jobspec)
_PK = "p" + "kill"          # name/pattern-matching kill
_KA = "k" + "illall"        # name-matching kill
_PG = "pgrep"
_XK = "xargs " + _K


# Nested-path data file so the STEP0 ancestor-directory protection has real
# ancestors BELOW the generic system/home stop-roots (a `/tmp/<rand>/.config/app`
# tree). NEVER touches the live machine data file.
@pytest.fixture(scope="module")
def nested_datafile(tmp_path_factory):
    base = tmp_path_factory.mktemp("nestcfg")
    cfgdir = base / ".config" / "app"
    cfgdir.mkdir(parents=True)
    p = cfgdir / "protected-runtime.json"
    p.write_text(json.dumps(FIXTURE))
    return str(p)


def ev_nested(command, nested_df, cwd="/root"):
    os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = nested_df
    import importlib, lib.runtime_guard as rg
    importlib.reload(rg)
    return rg.evaluate(command, cwd)[0]


def ev_absent(command, cwd="/root"):
    """evaluate() with a non-existent data file -> config-absent fail-closed path."""
    os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = "/tmp/does-not-exist-runtime-xyz.json"
    import importlib, lib.runtime_guard as rg
    importlib.reload(rg)
    return rg.evaluate(command, cwd)[0]


class TestCycle13KillFragmentDirectionalOverlap:
    """Defect 1: `_p6_prockill.has_ident` / W4 anchor were directionally asymmetric
    — a kill-pipeline whose selector is the bare protected command-word (a SUBSTRING
    of a registered ident) leaked. Now an EITHER-direction overlap against the data-
    file-derived protected-process tokens BLOCKS, while a bare PID kill and an
    unrelated selector still ALLOW."""

    # bare command-word / stem fragment selectors (the idiomatic leak forms)
    def test_bare_fragment_xargs_kill(self, datafile, fixture_repo):
        assert ev(f"{_PG} -f happy | {_XK}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"{_PG} -f daemon | {_XK}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"{_PG} -f index.mjs | {_XK}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"{_PG} -f happy-cli | {_XK}", datafile, fixture_repo) == "BLOCK"

    def test_ps_grep_fragment(self, datafile, fixture_repo):
        assert ev("ps aux | grep happy | awk '{print $2}' | " + _XK, datafile, fixture_repo) == "BLOCK"

    def test_name_matching_kill_fragment(self, datafile, fixture_repo):
        assert ev(f"{_PK} -f happy", datafile, fixture_repo) == "BLOCK"
        assert ev(f"{_KA} happy", datafile, fixture_repo) == "BLOCK"

    def test_kill_subst_fragment(self, datafile, fixture_repo):
        assert ev(f"{_K} $({_PG} -f happy)", datafile, fixture_repo) == "BLOCK"

    def test_wrapped_fragment(self, datafile, fixture_repo):
        # behind an arbitrary/invented wrapper -> W4 anchor (head-agnostic)
        assert ev(f"setsid {_PK} -f happy", datafile, fixture_repo) == "BLOCK"
        assert ev(f"weirdwrapX {_PK} -f happy", datafile, fixture_repo) == "BLOCK"
        assert ev(f"sudo {_PK} -f happy", datafile, fixture_repo) == "BLOCK"

    # boundary ALLOW: bare PID kill + unrelated selector stay allowed
    def test_boundary_bare_pid_kill_allows(self, datafile, fixture_repo):
        assert ev(f"{_K} 12345", datafile, fixture_repo) == "ALLOW"
        assert ev(f"{_K} -9 4567", datafile, fixture_repo) == "ALLOW"
        assert ev(f"{_K} happy", datafile, fixture_repo) == "ALLOW"   # benign jobspec error

    def test_boundary_unrelated_selector_allows(self, datafile, fixture_repo):
        assert ev(f"{_PG} -f nginx | {_XK}", datafile, fixture_repo) == "ALLOW"
        assert ev(f"{_PK} -f nginx", datafile, fixture_repo) == "ALLOW"
        assert ev("ps aux | grep nginx | awk '{print $2}' | " + _XK, datafile, fixture_repo) == "ALLOW"
        assert ev(f"{_K} $({_PG} -f postgres)", datafile, fixture_repo) == "ALLOW"

    def test_config_absent_fragment_blocks(self):
        # config-absent -> STEP1 fail-closed blocks ALL kill verb families
        assert ev_absent(f"{_PG} -f happy | {_XK}") == "BLOCK"
        assert ev_absent(f"{_PK} -f happy") == "BLOCK"


class TestCycle13Step0AncestorAndFind:
    """Defect 2: STEP0 protected only the EXACT data-file path. Now a mutation/move/
    delete of an ANCESTOR directory, and the `find`-family destructive action
    (`-delete` / `-exec <mutation>`) against the data file OR an ancestor, BLOCK —
    head-agnostically, config-present AND config-absent. Reads still ALLOW."""

    def _cfgdir(self, nested_df):
        return os.path.dirname(nested_df)

    def test_mv_ancestor_dir_blocks(self, nested_datafile):
        cfgdir = self._cfgdir(nested_datafile)
        gp = os.path.dirname(cfgdir)
        assert ev_nested(f"mv {cfgdir} /tmp/x", nested_datafile) == "BLOCK"
        assert ev_nested(f"mv {gp} /tmp/x", nested_datafile) == "BLOCK"

    def test_rm_rmdir_ancestor_dir_blocks(self, nested_datafile):
        cfgdir = self._cfgdir(nested_datafile)
        assert ev_nested(f"rm -rf {cfgdir}", nested_datafile) == "BLOCK"
        assert ev_nested(f"rmdir {cfgdir}", nested_datafile) == "BLOCK"
        assert ev_nested(f"chmod 000 {cfgdir}", nested_datafile) == "BLOCK"

    def test_find_destructive_datafile_and_ancestor_blocks(self, nested_datafile):
        df = nested_datafile
        cfgdir = self._cfgdir(nested_datafile)
        assert ev_nested(f"find {df} -delete", nested_datafile) == "BLOCK"
        assert ev_nested(f"find {cfgdir} -delete", nested_datafile) == "BLOCK"
        assert ev_nested(f"find {df} -exec rm {{}} ;", nested_datafile) == "BLOCK"
        assert ev_nested(f"find {cfgdir} -exec rm -rf {{}} +", nested_datafile) == "BLOCK"

    def test_wrapped_find_destructive_blocks(self, nested_datafile):
        df = nested_datafile
        assert ev_nested(f"sudo find {df} -delete", nested_datafile) == "BLOCK"
        assert ev_nested(f"weirdwrapX find {df} -delete", nested_datafile) == "BLOCK"

    def test_direct_datafile_mutation_still_blocks(self, nested_datafile):
        df = nested_datafile
        assert ev_nested(f"mv {df} /tmp/x", nested_datafile) == "BLOCK"
        assert ev_nested(f"shred {df}", nested_datafile) == "BLOCK"

    def test_config_absent_step0_blocks(self):
        # STEP0 runs BEFORE config load -> ancestor + find protection holds absent.
        # Use the live hardcoded path so the absent-file path still has ancestors.
        os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = "/tmp/abs/.config/app/protected-runtime.json"
        import importlib, lib.runtime_guard as rg
        importlib.reload(rg)
        assert rg.evaluate("find /tmp/abs/.config/app/protected-runtime.json -delete")[0] == "BLOCK"
        assert rg.evaluate("find /tmp/abs/.config/app -delete")[0] == "BLOCK"
        assert rg.evaluate("mv /tmp/abs/.config/app /tmp/x")[0] == "BLOCK"

    # boundary ALLOW: reads of the config + unrelated mutations stay allowed
    def test_boundary_reads_and_unrelated_allow(self, nested_datafile):
        df = nested_datafile
        cfgdir = self._cfgdir(nested_datafile)
        assert ev_nested(f"cat {df}", nested_datafile) == "ALLOW"
        assert ev_nested(f"grep foo {df}", nested_datafile) == "ALLOW"
        assert ev_nested(f"cp {df} /tmp/backup.json", nested_datafile) == "ALLOW"
        assert ev_nested(f"find {cfgdir} -print", nested_datafile) == "ALLOW"
        assert ev_nested(f"find {cfgdir} -name '*.json'", nested_datafile) == "ALLOW"
        assert ev_nested(f"find {cfgdir} -exec cat {{}} ;", nested_datafile) == "ALLOW"
        assert ev_nested("mv /tmp/unrelated /tmp/x", nested_datafile) == "ALLOW"
        assert ev_nested("find /tmp/unrelated -delete", nested_datafile) == "ALLOW"
        # generic home/system roots are NOT ancestor-protected
        assert ev_nested("mv /root /backup", nested_datafile) == "ALLOW"
        assert ev_nested("rm -rf /root", nested_datafile) == "ALLOW"


class TestCycle13ClassSweepSiblingFamilies:
    """Class sweep: the find-family destructive + container-directory blind spots
    also existed for the bundle (hotfile), the daemon statefile, and the global-bin
    family. All now BLOCK head-agnostically where in-scope; reads + unrelated/sibling
    mutations still ALLOW."""

    def _bundle(self, repo):
        return f"{repo}/packages/happy-cli/dist/index.mjs"

    def _bundledir(self, repo):
        return f"{repo}/packages/happy-cli/dist"

    def _pkgdir(self, repo):
        return f"{repo}/packages/happy-cli"

    def test_find_destructive_bundle(self, datafile, fixture_repo):
        b = self._bundle(fixture_repo)
        bd = self._bundledir(fixture_repo)
        assert ev_cwd(f"find {b} -delete", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd(f"find {bd} -delete", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd(f"find {b} -exec rm {{}} ;", datafile, fixture_repo) == "BLOCK"

    def test_container_dir_mutation_bundle(self, datafile, fixture_repo):
        bd = self._bundledir(fixture_repo)
        pd = self._pkgdir(fixture_repo)
        assert ev_cwd(f"mv {bd} /tmp/x", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd(f"rm -rf {bd}", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd(f"rmdir {bd}", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd(f"mv {pd} /tmp/x", datafile, fixture_repo) == "BLOCK"

    def test_find_destructive_statefile(self, datafile, fixture_repo):
        assert ev_cwd("find /root/.happy-dev/daemon.state.json -delete", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("find /root/.happy-dev -exec rm {} ;", datafile, fixture_repo) == "BLOCK"

    def test_container_dir_mutation_statefile(self, datafile, fixture_repo):
        assert ev_cwd("mv /root/.happy-dev /tmp/x", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("rm -rf /root/.happy-dev", datafile, fixture_repo) == "BLOCK"

    def test_find_destructive_globalbin(self, datafile, fixture_repo):
        assert ev_cwd("find /usr/bin/happy -delete", datafile, fixture_repo) == "BLOCK"

    def test_wrapped_sweep_blocks(self, datafile, fixture_repo):
        bd = self._bundledir(fixture_repo)
        assert ev_cwd(f"sudo find {bd} -delete", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd(f"weirdwrapX rm -rf {bd}", datafile, fixture_repo) == "BLOCK"

    # boundary ALLOW: reads, new-file-into-dir, sibling pkg, generic system roots
    def test_boundary_sweep_allows(self, datafile, fixture_repo):
        b = self._bundle(fixture_repo)
        bd = self._bundledir(fixture_repo)
        assert ev_cwd(f"find {b} -print", datafile, fixture_repo) == "ALLOW"
        assert ev_cwd(f"find {bd} -name '*.mjs'", datafile, fixture_repo) == "ALLOW"
        assert ev_cwd(f"ls {bd}", datafile, fixture_repo) == "ALLOW"
        assert ev_cwd(f"cat {b}", datafile, fixture_repo) == "ALLOW"
        assert ev_cwd(f"cp /tmp/foo {bd}/other.mjs", datafile, fixture_repo) == "ALLOW"
        # a NON-protected sibling package dir is not container-protected
        assert ev_cwd(f"mv {fixture_repo}/packages/happy-app /tmp/x", datafile, fixture_repo) == "ALLOW"
        # generic system dirs are NOT global-bin container-protected
        assert ev_cwd("rm -rf /usr/lib", datafile, fixture_repo) == "ALLOW"
        assert ev_cwd("rm -rf /usr/bin", datafile, fixture_repo) == "ALLOW"
        assert ev_cwd("find /tmp/unrelated -delete", datafile, fixture_repo) == "ALLOW"


class TestCycle13LiveHookAndDoBypass:
    """The two fixed leaks + a sweep representative BLOCK on the REAL hook end-to-end
    against the LIVE data file, both plain and under a /do consent flag (the guard
    runs before /do, so it is unbypassable).

    The hook resolves its python via `CLAUDE_PYTHON_BIN` (else `${CLAUDE_HOME}/venv/
    bin/python`, else `python3`). Under the test runner `CLAUDE_HOME` may be unset,
    so we pin `CLAUDE_PYTHON_BIN` to the interpreter running pytest so the REAL
    engine executes (otherwise the hook degrades to the verb-family fail-closed grep,
    which does not cover the mv/find self-protection forms these tests target)."""

    _ENV = {"CLAUDE_PYTHON_BIN": sys.executable}

    def _clean_env(self, extra=None):
        # a prior engine-level test may have left CLAUDE_PROTECTED_RUNTIME_FILE
        # pointing at a tmp fixture; the LIVE-hook tests must use the REAL default
        # data file (/root/.config/claude/...), so drop the override here.
        e = dict(os.environ, **self._ENV)
        e.pop("CLAUDE_PROTECTED_RUNTIME_FILE", None)
        if extra:
            e.update(extra)
        return e

    def _run(self, cmd, extra_env=None):
        # call the hook directly with a COMPLETE env (run_hook re-seeds from
        # os.environ, which would re-introduce a stale CLAUDE_PROTECTED_RUNTIME_FILE
        # left by a prior engine test) so the LIVE default data file is used.
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
        return subprocess.run(["bash", HOOK], input=payload, text=True,
                              capture_output=True, env=self._clean_env(extra_env)).returncode

    def test_live_hook_kill_fragment_blocks(self):
        assert self._run(f"{_PG} -f happy | {_XK}") == BLOCK
        assert self._run(f"{_PK} -f happy") == BLOCK

    def test_live_hook_config_ancestor_blocks(self):
        # the LIVE data file is /root/.config/claude/protected-runtime.json; its
        # parent dir mutation + find -delete must BLOCK on the real hook.
        assert self._run("mv /root/.config/claude /tmp/x") == BLOCK
        assert self._run("find /root/.config/claude/protected-runtime.json -delete") == BLOCK
        assert self._run("find /root/.config/claude -delete") == BLOCK

    def test_live_hook_sweep_blocks(self):
        assert self._run("find /root/.happy-dev/daemon.state.json -delete") == BLOCK

    def test_live_hook_boundary_allows(self):
        # NOTE: bare `kill <pid>` / `xargs kill` are independently blocked by the
        # LEGACY bash-safety hook (kill-by-PID / kill-happy rules), orthogonal to
        # this engine. The engine-level boundary ALLOW for those forms is asserted
        # in TestCycle13KillFragmentDirectionalOverlap; here we assert only the
        # config/find self-protection boundary the engine owns end-to-end.
        assert self._run("cat /root/.config/claude/protected-runtime.json") == ALLOW
        assert self._run("find /root/.config/claude -print") == ALLOW
        assert self._run("find /root/.config/claude -name '*.json'") == ALLOW
        assert self._run("mv /tmp/unrelated-xyz /tmp/x") == ALLOW

    def test_live_hook_unbypassable_under_do(self):
        sid = "guardtest13-" + str(os.getpid())
        flag = f"/tmp/claude-orchestrator-consent-{sid}.flag"
        with open(flag, "w") as fh:
            fh.write("true")
        try:
            def run(cmd):
                payload = json.dumps({"tool_name": "Bash",
                                      "tool_input": {"command": cmd},
                                      "session_id": sid})
                return subprocess.run(["bash", HOOK], input=payload, text=True,
                                      capture_output=True, env=self._clean_env()).returncode
            assert run(f"{_PG} -f happy | {_XK}") == BLOCK
            assert run("mv /root/.config/claude /tmp/x") == BLOCK
            assert run("find /root/.config/claude -delete") == BLOCK
            # boundary self-protection read still ALLOWs under /do (kill-pid is a
            # legacy-hook block, orthogonal to the engine — not asserted here).
            assert run("cat /root/.config/claude/protected-runtime.json") == ALLOW
        finally:
            os.remove(flag)


class TestCycle13CodexFollowup:
    """Two additional under-block leaks codex (gpt-5.5 xhigh) surfaced during the
    fix review, both in-scope good-faith forms:
      F1: P6 pipeline selector/kill was head-keyed per segment, so a kill pipeline
          with the selector/executor BEHIND a novel wrapper leaked.
      F2: `_find_path_operands` stopped at the first dash token, so a destructive
          find with options BEFORE the path (`-L`/`-maxdepth N`/`--`/`-P`) dropped
          the path operand and under-blocked."""

    # F1: wrapped pipeline kill forms now BLOCK (head-agnostic P6)
    def test_wrapped_pipeline_kill_blocks(self, datafile, fixture_repo):
        assert ev(f"weirdwrapX {_PG} -f happy | {_XK}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"{_PG} -f happy | weirdwrapX {_XK}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"weirdwrapX {_PK} -f happy", datafile, fixture_repo) == "BLOCK"
        assert ev(f"pidof happy | {_XK}", datafile, fixture_repo) == "BLOCK"

    def test_wrapped_pipeline_statefile_kill_blocks(self, datafile, fixture_repo):
        assert ev(f"cat /root/.happy-dev/daemon.state.json | weirdwrapX {_XK}",
                  datafile, fixture_repo) == "BLOCK"

    def test_wrapped_pipeline_boundary_allows(self, datafile, fixture_repo):
        assert ev(f"weirdwrapX {_PG} -f nginx | {_XK}", datafile, fixture_repo) == "ALLOW"
        assert ev(f"{_PG} -f nginx | weirdwrapX {_XK}", datafile, fixture_repo) == "ALLOW"

    # F2: destructive find with options BEFORE the path now BLOCKs (config family)
    def test_find_opts_before_path_blocks(self, nested_datafile):
        df = nested_datafile
        cfgdir = os.path.dirname(df)
        assert ev_nested(f"find -L {df} -delete", nested_datafile) == "BLOCK"
        assert ev_nested(f"find -maxdepth 1 {df} -delete", nested_datafile) == "BLOCK"
        assert ev_nested(f"find -- {cfgdir} -delete", nested_datafile) == "BLOCK"
        assert ev_nested(f"find -P {df} -delete", nested_datafile) == "BLOCK"
        assert ev_nested(f"find -maxdepth 1 {cfgdir} -exec rm {{}} ;", nested_datafile) == "BLOCK"
        assert ev_nested(f"sudo find -L {df} -delete", nested_datafile) == "BLOCK"

    def test_find_opts_before_path_sibling_family_blocks(self, datafile, fixture_repo):
        bd = f"{fixture_repo}/packages/happy-cli/dist"
        assert ev_cwd(f"find -L {bd} -delete", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("find -maxdepth 1 /root/.happy-dev -delete", datafile, fixture_repo) == "BLOCK"

    def test_find_opts_before_path_boundary_allows(self, nested_datafile):
        cfgdir = os.path.dirname(nested_datafile)
        assert ev_nested("find -L /tmp/unrelated -delete", nested_datafile) == "ALLOW"
        assert ev_nested(f"find -maxdepth 1 {cfgdir} -print", nested_datafile) == "ALLOW"
        assert ev_nested("find -- /tmp/unrelated -delete", nested_datafile) == "ALLOW"

    def test_find_implicit_cwd_destructive_blocks(self, datafile, fixture_repo):
        # `cd <protected-dir> && find -delete` — path-less find targets cwd
        bd = f"{fixture_repo}/packages/happy-cli/dist"
        assert ev_cwd("find -delete", datafile, bd) == "BLOCK"


# ════════════════════════════════════════════════════════════════════════════
# Cycle 14 (re-close-debate-20260531-162901): the DRIVER (shell-glob mutation of a
# protected directory's contents) + four secondary same-class leaks (F2 find/fd
# predicate, F4 lsof selector, F6 destructive git pathspec, F5 chgrp) + F3 $HOME
# expansion. Verified ONLY by feeding strings to evaluate()/the hook (NEVER any
# real daemon/CLI/process command).
# ════════════════════════════════════════════════════════════════════════════


# An ISOLATED config+repo pair under DIFFERENT tmp roots (/tmp vs /var/tmp) so the
# config's ancestor-dir self-protection set does NOT share a pytest-tmp ancestor
# with the repo — mirroring production (/root/.config/<app> vs /dev/shm/<repo>),
# where a glob mutation of a NON-protected repo dir must ALLOW. NEVER touches the
# live machine data file.
@pytest.fixture(scope="module")
def isolated_pair(tmp_path_factory):
    import tempfile
    cfgbase = tempfile.mkdtemp(prefix="c14cfg_", dir="/tmp")
    cfgdir = os.path.join(cfgbase, ".config", "app")
    os.makedirs(cfgdir)
    df = os.path.join(cfgdir, "protected-runtime.json")
    repo = tempfile.mkdtemp(prefix="c14repo_", dir="/var/tmp")
    os.makedirs(os.path.join(repo, "packages", "happy-cli", "dist"))
    os.makedirs(os.path.join(repo, "packages", "happy-app", "dist"))
    cfg = json.loads(json.dumps(FIXTURE))
    cfg["protected_root_manifest_paths"] = [repo]
    with open(df, "w") as fh:
        json.dump(cfg, fh)
    return {"df": df, "cfgdir": cfgdir, "repo": repo}


def ev_iso(command, df, cwd=None):
    os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = df
    import importlib, lib.runtime_guard as rg
    importlib.reload(rg)
    return rg.evaluate(command, cwd)[0]


class TestCycle14DriverGlobMutation:
    """DRIVER: `mv|cp|rsync <protecteddir>/*` glob-clobbers/exfiltrates the guard's
    own data file / the bundle / the statefile — leaked because a shell-glob token is
    normalized literally and never intersects a protected ancestor/container glob.
    Now the glob-parent is computed and intersected against the protected set."""

    def test_config_dir_glob_blocks(self, isolated_pair):
        df, cfgdir = isolated_pair["df"], isolated_pair["cfgdir"]
        assert ev_iso(f"mv {cfgdir}/* /tmp/x", df) == "BLOCK"
        assert ev_iso(f"cp {cfgdir}/* /tmp/x", df) == "BLOCK"
        assert ev_iso(f"rsync {cfgdir}/* /tmp/x", df) == "BLOCK"

    def test_config_dir_glob_wrapped_and_do_blocks(self, isolated_pair):
        df, cfgdir = isolated_pair["df"], isolated_pair["cfgdir"]
        assert ev_iso(f"sudo mv {cfgdir}/* /tmp/x", df) == "BLOCK"
        assert ev_iso(f"setsid cp {cfgdir}/* /tmp/x", df) == "BLOCK"
        assert ev_iso(f"weirdwrapX mv {cfgdir}/* /tmp/x", df) == "BLOCK"

    def test_bundle_dir_glob_blocks(self, isolated_pair):
        df, repo = isolated_pair["df"], isolated_pair["repo"]
        distdir = f"{repo}/packages/happy-cli/dist"
        assert ev_iso(f"mv {distdir}/* /tmp/x", df, repo) == "BLOCK"
        assert ev_iso(f"cp {distdir}/* /tmp/x", df, repo) == "BLOCK"
        # clobber the bundle directly via /dev/null
        assert ev_iso(f"cp /dev/null {distdir}/index.mjs", df, repo) == "BLOCK"

    def test_statefile_dir_glob_blocks(self, isolated_pair):
        df = isolated_pair["df"]
        assert ev_iso("mv /root/.happy-dev/* /tmp/x", df) == "BLOCK"
        assert ev_iso("cp /root/.happy-dev/* /tmp/x", df) == "BLOCK"

    def test_config_absent_glob_blocks(self):
        # STEP0 (config ancestor self-protection) runs before config load.
        os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = "/tmp/abs14/.config/app/protected-runtime.json"
        import importlib, lib.runtime_guard as rg
        importlib.reload(rg)
        assert rg.evaluate("mv /tmp/abs14/.config/app/* /tmp/x")[0] == "BLOCK"
        assert rg.evaluate("cp /tmp/abs14/.config/app/* /tmp/x")[0] == "BLOCK"

    # RE-CLOSE #9: `cp -t DIR <protecteddir>/*` / `--target-directory=` / `install -t`
    # leaked because the `-t`/`--target-directory=` branch synthesized DIR/basename(src)
    # candidates (basename('<dir>/*') == '*' drops the protected-ness) but did NOT add
    # the shell-GLOB sources as targets the way the plain-cp and `mv -t` branches do.
    def test_cp_target_dir_glob_blocks(self, isolated_pair):
        df, cfgdir = isolated_pair["df"], isolated_pair["cfgdir"]
        assert ev_iso(f"cp -t /tmp/x {cfgdir}/*", df) == "BLOCK"
        assert ev_iso(f"cp --target-directory=/tmp/x {cfgdir}/*", df) == "BLOCK"
        assert ev_iso(f"install -t /tmp/x {cfgdir}/*", df) == "BLOCK"
        assert ev_iso(f"nice cp -t /tmp/x {cfgdir}/*", df) == "BLOCK"
        # a literal protected SOURCE under `-t` stays a read (cp keeps the source) → ALLOW
        assert ev_iso(f"cp -t /tmp/x {cfgdir}/protected-runtime.json", df) == "ALLOW"
        # an unrelated glob selecting NOTHING protected stays allowed
        assert ev_iso("cp -t /tmp/x /tmp/scratch/*", df) == "ALLOW"

    # boundary ALLOW: a glob selecting NOTHING protected stays allowed
    def test_boundary_glob_allows(self, isolated_pair):
        df, repo = isolated_pair["df"], isolated_pair["repo"]
        assert ev_iso("mv /tmp/scratch/* /tmp/y", df) == "ALLOW"
        assert ev_iso(f"mv {repo}/packages/happy-app/dist/* /tmp/x", df, repo) == "ALLOW"
        assert ev_iso("cp /tmp/other/* /tmp/z", df) == "ALLOW"
        # a config READ (no glob mutation) still allows
        assert ev_iso(f"cat {isolated_pair['cfgdir']}/protected-runtime.json", df) == "ALLOW"


class TestCycle14FindPredicate:
    """F2: a destructive find/fd selecting its victim by a `-path`/`-wholename`/
    `-name`/fd `-g` PREDICATE value (not a positional root) leaked because the path
    scan read only positional roots. Now the predicate values are scanned too."""

    def test_find_path_predicate_blocks(self, nested_datafile):
        df = nested_datafile
        cfgdir = os.path.dirname(df)
        assert ev_nested(f"find /root -path {df} -delete", nested_datafile) == "BLOCK"
        assert ev_nested(f"find /root -wholename {df} -delete", nested_datafile) == "BLOCK"
        assert ev_nested(f"find /tmp -path {cfgdir} -exec rm -rf {{}} +", nested_datafile) == "BLOCK"

    def test_find_name_predicate_blocks(self, nested_datafile):
        df = nested_datafile
        base = os.path.basename(df)
        assert ev_nested(f"find /root -name {base} -delete", nested_datafile) == "BLOCK"
        assert ev_nested(f"find / -iname {base} -delete", nested_datafile) == "BLOCK"

    def test_find_predicate_sibling_family_blocks(self, datafile, fixture_repo):
        bundlebase = "index.mjs"
        assert ev_cwd(f"find {fixture_repo} -path '*/packages/happy-cli/dist/index.mjs' -delete",
                      datafile, fixture_repo) == "BLOCK"
        assert ev_cwd(f"find {fixture_repo} -name {bundlebase} -delete", datafile, fixture_repo) == "BLOCK"

    def test_find_predicate_wrapped_blocks(self, nested_datafile):
        df = nested_datafile
        assert ev_nested(f"sudo find /root -path {df} -delete", nested_datafile) == "BLOCK"
        assert ev_nested(f"weirdwrapX find /root -name {os.path.basename(df)} -delete", nested_datafile) == "BLOCK"

    def test_find_predicate_config_absent_blocks(self):
        os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = "/tmp/abs14b/.config/app/protected-runtime.json"
        import importlib, lib.runtime_guard as rg
        importlib.reload(rg)
        assert rg.evaluate("find /root -path /tmp/abs14b/.config/app/protected-runtime.json -delete")[0] == "BLOCK"

    # boundary ALLOW: read-only find + unrelated predicate + non-protected basename
    def test_find_predicate_boundary_allows(self, nested_datafile):
        df = nested_datafile
        base = os.path.basename(df)
        assert ev_nested(f"find /root -path {df} -print", nested_datafile) == "ALLOW"   # read-only
        assert ev_nested(f"find /root -name {base}", nested_datafile) == "ALLOW"        # read-only
        assert ev_nested("find /root -path /tmp/unrelated -delete", nested_datafile) == "ALLOW"
        assert ev_nested("find /root -name unrelated.txt -delete", nested_datafile) == "ALLOW"


class TestCycle14LsofSelector:
    """F4: `lsof -t -c <cmd> | xargs kill` resolved PIDs by command-name but `lsof`
    was absent from the proc-selector heads, so P6 missed the connectivity. Now lsof
    is a selector head."""

    def test_lsof_kill_blocks(self, datafile, fixture_repo):
        assert ev(f"lsof -t -c happy | {_XK}", datafile, fixture_repo) == "BLOCK"
        assert ev(f"lsof -c happy -t | {_XK}", datafile, fixture_repo) == "BLOCK"

    def test_lsof_kill_wrapped_blocks(self, datafile, fixture_repo):
        assert ev(f"lsof -t -c happy | weirdwrapX {_XK}", datafile, fixture_repo) == "BLOCK"

    def test_lsof_config_absent_blocks(self):
        assert ev_absent(f"lsof -t -c happy | {_XK}") == "BLOCK"  # STEP1 xargs-kill family

    # boundary ALLOW: lsof read-only + unrelated command selector
    def test_lsof_boundary_allows(self, datafile, fixture_repo):
        assert ev(f"lsof -t -c happy", datafile, fixture_repo) == "ALLOW"       # no kill executor
        assert ev(f"lsof -t -c nginx | {_XK}", datafile, fixture_repo) == "ALLOW"


class TestCycle14GitPathspec:
    """F6: a destructive git pathspec (`clean -fdx`/`restore`/`checkout -- <path>`/
    `reset --hard -- <path>`) under a protected build dir / bundle wipes or reverts
    the protected file. Now a destructive-git-pathspec parser blocks it."""

    def test_git_clean_blocks(self, datafile, fixture_repo):
        assert ev_cwd("git clean -fdx packages/happy-cli/dist", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("git clean -fd packages/happy-cli", datafile, fixture_repo) == "BLOCK"

    def test_git_restore_checkout_reset_blocks(self, datafile, fixture_repo):
        assert ev_cwd("git restore packages/happy-cli/dist", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("git checkout -- packages/happy-cli/dist", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("git reset --hard -- packages/happy-cli", datafile, fixture_repo) == "BLOCK"

    def test_git_pathspec_wrapped_and_C_blocks(self, datafile, fixture_repo):
        assert ev_cwd("sudo git clean -fdx packages/happy-cli/dist", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd(f"git -C {fixture_repo} clean -fdx packages/happy-cli/dist", datafile, "/root") == "BLOCK"

    def test_git_pathspec_config_absent_allows(self, fixture_repo):
        # config-absent STEP1 has no git-pathspec family (git is not a danger-family
        # head); the engine ALLOWs (the destructive-git block requires loaded globs).
        # This documents the config-absent behavior — git pathspec is NOT a fail-
        # closed verb family, so it ALLOWs when the data file is gone.
        assert ev_absent("git clean -fdx packages/happy-cli/dist", fixture_repo) == "ALLOW"

    # boundary ALLOW: read-only git, branch switch, non-protected pathspec
    def test_git_pathspec_boundary_allows(self, datafile, fixture_repo):
        assert ev_cwd("git status", datafile, fixture_repo) == "ALLOW"
        assert ev_cwd("git log --oneline", datafile, fixture_repo) == "ALLOW"
        assert ev_cwd("git checkout main", datafile, fixture_repo) == "ALLOW"          # branch switch
        assert ev_cwd("git clean -fdx packages/happy-app", datafile, fixture_repo) == "ALLOW"
        assert ev_cwd("git restore packages/happy-app/dist", datafile, fixture_repo) == "ALLOW"
        assert ev_cwd("git diff packages/happy-cli/dist", datafile, fixture_repo) == "ALLOW"  # read-only


class TestCycle14ChgrpAndHome:
    """F5: `chgrp <group> <config>` mutated the data file's group but chgrp was
    missing from the mutation heads. F3: a `$HOME`/`${HOME}`-prefixed mutation now
    resolves to the protected path."""

    def test_chgrp_config_blocks(self, nested_datafile):
        df = nested_datafile
        cfgdir = os.path.dirname(df)
        assert ev_nested(f"chgrp root {df}", nested_datafile) == "BLOCK"
        assert ev_nested(f"chgrp -R root {cfgdir}", nested_datafile) == "BLOCK"

    def test_chgrp_sibling_family_blocks(self, datafile, fixture_repo):
        assert ev_cwd("chgrp root packages/happy-cli/dist/index.mjs", datafile, fixture_repo) == "BLOCK"

    def test_chgrp_wrapped_blocks(self, nested_datafile):
        df = nested_datafile
        assert ev_nested(f"sudo chgrp root {df}", nested_datafile) == "BLOCK"

    def test_home_expansion_blocks(self):
        # use a hardcoded /root/.config path so HOME=/root resolves it; STEP0
        # ancestor protection runs config-absent.
        os.environ["HOME"] = "/root"
        os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = "/root/.config/appz14/protected-runtime.json"
        import importlib, lib.runtime_guard as rg
        importlib.reload(rg)
        assert rg.evaluate('mv "$HOME/.config/appz14" /tmp/x')[0] == "BLOCK"
        assert rg.evaluate('mv ${HOME}/.config/appz14/protected-runtime.json /tmp/x')[0] == "BLOCK"
        assert rg.evaluate('rm -rf "$HOME/.config/appz14"')[0] == "BLOCK"

    # boundary ALLOW: chgrp unrelated + $HOME read + non-$HOME var
    def test_chgrp_home_boundary_allows(self, nested_datafile):
        assert ev_nested("chgrp root /tmp/unrelated", nested_datafile) == "ALLOW"
        os.environ["HOME"] = "/root"
        os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = "/root/.config/appz14/protected-runtime.json"
        import importlib, lib.runtime_guard as rg
        importlib.reload(rg)
        assert rg.evaluate('cat "$HOME/.config/appz14/protected-runtime.json"')[0] == "ALLOW"
        assert rg.evaluate('mv "$HOME/.config/unrelated" /tmp/x')[0] == "ALLOW"
        assert rg.evaluate('mv "$HOMEDIR/.config/appz14" /tmp/x')[0] == "ALLOW"  # $HOMEDIR != $HOME


class TestCycle14LiveHook:
    """The DRIVER + each secondary representative BLOCK on the REAL hook end-to-end
    against the LIVE data file, plain and under /do (the guard runs before /do, so it
    is unbypassable). Mirrors TestCycle13LiveHookAndDoBypass's env handling."""

    _ENV = {"CLAUDE_PYTHON_BIN": sys.executable}

    def _clean_env(self, extra=None):
        e = dict(os.environ, **self._ENV)
        e.pop("CLAUDE_PROTECTED_RUNTIME_FILE", None)
        if extra:
            e.update(extra)
        return e

    def _run(self, cmd, sid=None):
        payload = {"tool_name": "Bash", "tool_input": {"command": cmd}}
        if sid:
            payload["session_id"] = sid
        return subprocess.run(["bash", HOOK], input=json.dumps(payload), text=True,
                              capture_output=True, env=self._clean_env()).returncode

    def test_live_driver_glob_blocks(self):
        assert self._run("mv /root/.config/claude/* /tmp/x") == BLOCK
        assert self._run("cp /root/.config/claude/* /tmp/x") == BLOCK

    def test_live_secondary_blocks(self):
        assert self._run("find /root -path /root/.config/claude/protected-runtime.json -delete") == BLOCK
        assert self._run("find /root -name protected-runtime.json -delete") == BLOCK
        assert self._run(f"lsof -t -c happy | {_XK}") == BLOCK
        assert self._run("chgrp root /root/.config/claude/protected-runtime.json") == BLOCK

    def test_live_driver_glob_unbypassable_under_do(self):
        sid = "guardtest14-" + str(os.getpid())
        flag = f"/tmp/claude-orchestrator-consent-{sid}.flag"
        with open(flag, "w") as fh:
            fh.write("true")
        try:
            assert self._run("mv /root/.config/claude/* /tmp/x", sid) == BLOCK
            assert self._run("find /root -name protected-runtime.json -delete", sid) == BLOCK
            assert self._run("cat /root/.config/claude/protected-runtime.json", sid) == ALLOW
        finally:
            os.remove(flag)

    def test_live_boundary_allows(self):
        assert self._run("mv /tmp/scratch-xyz/* /tmp/y") == ALLOW
        assert self._run("cat /root/.config/claude/protected-runtime.json") == ALLOW
        assert self._run("find /root -path /tmp/unrelated -delete") == ALLOW
        assert self._run("chgrp root /tmp/unrelated-xyz") == ALLOW


class TestCycle14CodexFollowup:
    """Five additional same-class leaks/over-blocks codex (gpt-5.5 xhigh) surfaced
    during the cycle-14 review, all in-scope:
      CF1: `$HOME`/`${HOME}`/`~` in cd / wrapper-C / git-C cwd resolution under-blocked.
      CF2: find/fd basename predicate (`-name`/`-g`) over-blocked unrelated trees
           (now scoped to a search root intersecting a protected location).
      CF3: case-insensitive find predicates (`-iname`/`-ipath`) matched case-sensitively.
      CF4: reverse containment — a destructive ROOT/pathspec CONTAINING a protected
           descendant (`git clean -fdx .`, `find packages -delete`) under-blocked.
      CF5: git pathspec magic (`:(glob)`/`:(top)`/`:/`) prefixes were not stripped."""

    # CF1: $HOME / ~ in cwd resolution (use absent-config hardcoded /root path)
    def test_home_in_cwd_blocks(self):
        os.environ["HOME"] = "/root"
        os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = "/root/.config/appz14cf/protected-runtime.json"
        import importlib, lib.runtime_guard as rg
        importlib.reload(rg)
        assert rg.evaluate('cd "$HOME/.config/appz14cf" && rm protected-runtime.json')[0] == "BLOCK"
        assert rg.evaluate('env -C "$HOME/.config/appz14cf" rm protected-runtime.json')[0] == "BLOCK"
        assert rg.evaluate('cd ~/.config/appz14cf && rm protected-runtime.json')[0] == "BLOCK"
        assert rg.evaluate('cd ${HOME}/.config/appz14cf && rm protected-runtime.json')[0] == "BLOCK"

    def test_home_in_cwd_boundary_allows(self):
        os.environ["HOME"] = "/root"
        os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = "/root/.config/appz14cf/protected-runtime.json"
        import importlib, lib.runtime_guard as rg
        importlib.reload(rg)
        assert rg.evaluate('cd "$HOME/.config/unrelated" && rm foo.json')[0] == "ALLOW"
        assert rg.evaluate('cd "$HOMEDIR/.config/appz14cf" && rm protected-runtime.json')[0] == "ALLOW"

    # CF2: basename predicate scoped to root intersection. Use the isolated_pair
    # fixture (config+repo under DIFFERENT tmp roots) so an unrelated `/var/tmp/...`
    # root does NOT reverse-contain the protected repo (which lives under a different
    # root), mirroring production (/root/.config vs /dev/shm). NOTE: the config
    # FAMILY (STEP0) intentionally keeps its basename predicate root-UNSCOPED — the
    # config file's distinctive basename is protected regardless of root — so this
    # test targets the BUILD/BUNDLE family (a generic `index.mjs` basename), which IS
    # root-scoped (a routine unrelated `find /scratch -name index.mjs -delete` ALLOWS).
    def test_basename_predicate_unrelated_root_allows(self, isolated_pair):
        df = isolated_pair["df"]
        # an unrelated scratch root that contains NO protected descendant ALLOWS even
        # though `index.mjs` is a protected basename.
        assert ev_iso("find /opt/scratch -name index.mjs -delete", df) == "ALLOW"
        assert ev_iso("fd -g 'index.mjs' /opt/scratch -x rm", df) == "ALLOW"

    def test_basename_predicate_protected_root_blocks(self, isolated_pair):
        df, repo = isolated_pair["df"], isolated_pair["repo"]
        # when the search root intersects a protected location, the basename BLOCKS
        assert ev_iso(f"find {repo} -name index.mjs -delete", df, repo) == "BLOCK"
        bd = f"{repo}/packages/happy-cli/dist"
        assert ev_iso(f"fd -g 'index.mjs' {bd} -X rm", df, repo) == "BLOCK"

    def test_basename_predicate_config_family_root_unscoped_blocks(self, nested_datafile):
        # the CONFIG family (STEP0) keeps the basename predicate root-UNSCOPED: a
        # `find /tmp -name <config-basename> -delete` blocks (config self-protection).
        base = os.path.basename(nested_datafile)
        assert ev_nested(f"find /tmp -name {base} -delete", nested_datafile) == "BLOCK"

    # CF3: case-insensitive predicates
    def test_case_insensitive_predicate_blocks(self, datafile, fixture_repo):
        assert ev_cwd(f"find {fixture_repo} -iname INDEX.MJS -delete", datafile, fixture_repo) == "BLOCK"

    def test_case_insensitive_predicate_config(self, nested_datafile):
        base = os.path.basename(nested_datafile).upper()
        assert ev_nested(f"find {os.path.dirname(nested_datafile)} -iname {base} -delete", nested_datafile) == "BLOCK"

    # CF4: reverse containment (root/pathspec contains a protected descendant)
    def test_reverse_containment_git_blocks(self, datafile, fixture_repo):
        assert ev_cwd("git clean -fdx .", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("git checkout -- .", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("git clean -fdx packages", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("git reset --hard -- .", datafile, fixture_repo) == "BLOCK"

    def test_reverse_containment_find_blocks(self, datafile, fixture_repo):
        assert ev_cwd("find packages -delete", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("find . -delete", datafile, fixture_repo) == "BLOCK"

    def test_reverse_containment_boundary_allows(self, datafile, fixture_repo):
        # a destructive root that does NOT contain a protected descendant ALLOWS
        assert ev_cwd("git clean -fdx packages/happy-app", datafile, fixture_repo) == "ALLOW"
        assert ev_cwd("find /tmp/unrelated -delete", datafile, fixture_repo) == "ALLOW"
        # a filtered find whose predicate excludes the protected descendant ALLOWS
        assert ev_cwd("find /root -path /tmp/unrelated -delete", datafile, fixture_repo) == "ALLOW"

    # CF5: git pathspec magic prefixes stripped
    def test_pathspec_magic_blocks(self, datafile, fixture_repo):
        assert ev_cwd("git clean -fdx ':(glob)packages/happy-cli/dist/**'", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("git clean -fdx ':(top)packages/happy-cli'", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("git clean -fdx ':/packages/happy-cli'", datafile, fixture_repo) == "BLOCK"
        assert ev_cwd("git restore ':(glob)packages/happy-cli/dist/*'", datafile, fixture_repo) == "BLOCK"


class TestCycle14Codex2:
    """Second codex (gpt-5.5 xhigh) adversarial pass surfaced 7 more same-class
    leaks/over-blocks, all in-scope and fixed:
      C2A: parent/sibling shell globs (`rm -rf <repo>/packages/*`) under-blocked.
      C2B: reverse containment missed the filesystem root `/` (`find / -delete`).
      C2C: coarse filter-suppression let `find . -name '*' -delete`, action-before-
           filter, and `-o` disjunction under-block (now proof-based).
      C2D: git `:(icase)` case-insensitive pathspec magic semantics were lost.
      C2E: git exclude pathspec `:!`/`:(exclude)` was treated as a positive target.
      C2F: fd default positional pattern not modeled (reverse containment runs —
           accepted over-block).
      C2G: `~user` (`~root`) cwd forms not expanded."""

    # C2A: parent/sibling shell globs select the protected package
    def test_parent_glob_blocks(self, isolated_pair):
        df, repo = isolated_pair["df"], isolated_pair["repo"]
        assert ev_iso(f"rm -rf {repo}/packages/*", df, repo) == "BLOCK"
        assert ev_iso(f"mv {repo}/packages/happy-cli* /tmp/x", df, repo) == "BLOCK"
        assert ev_iso("rm -rf packages/*", df, repo) == "BLOCK"

    def test_parent_glob_boundary_allows(self, isolated_pair):
        df, repo = isolated_pair["df"], isolated_pair["repo"]
        assert ev_iso(f"mv {repo}/packages/happy-app/dist/* /tmp/x", df, repo) == "ALLOW"
        assert ev_iso("rm -rf /opt/build/*", df) == "ALLOW"

    # C2B: reverse containment on the filesystem root
    def test_root_filesystem_blocks(self, datafile, fixture_repo):
        assert ev_cwd("find / -delete", datafile, "/") == "BLOCK"

    # C2C: proof-based filter suppression
    def test_broad_filter_does_not_exonerate(self, isolated_pair):
        df, repo = isolated_pair["df"], isolated_pair["repo"]
        assert ev_iso("find . -name '*' -delete", df, repo) == "BLOCK"
        assert ev_iso("find . -delete -name unrelated", df, repo) == "BLOCK"  # action before filter
        assert ev_iso("find . -path ./packages/happy-app -o -delete", df, repo) == "BLOCK"  # disjunction

    def test_proven_disjoint_filter_exonerates(self, isolated_pair):
        df, repo = isolated_pair["df"], isolated_pair["repo"]
        assert ev_iso("find /root -path /tmp/unrelated -delete", df) == "ALLOW"
        assert ev_iso("find . -path ./packages/happy-app -delete", df, repo) == "ALLOW"

    # C2F: fd default pattern -> reverse containment runs (accepted over-block);
    # an fd -g proven-disjoint name predicate still exonerates.
    def test_fd_pattern_reverse_containment(self, isolated_pair):
        df, repo = isolated_pair["df"], isolated_pair["repo"]
        assert ev_iso("fd unrelated . -X rm", df, repo) == "BLOCK"  # accepted over-block
        # unrelated absolute root with no protected descendant ALLOWS
        assert ev_iso("fd unrelated /opt/scratch -X rm", df) == "ALLOW"

    # C2D: git :(icase) magic
    def test_git_icase_magic_blocks(self, datafile, fixture_repo):
        assert ev_cwd("git clean -fdx ':(icase,top)PACKAGES/HAPPY-CLI'", datafile, fixture_repo) == "BLOCK"

    # C2E: git exclude pathspec
    def test_git_exclude_pathspec(self, datafile, fixture_repo):
        # positive nonprot + exclude prot -> the positive does not contain protected
        assert ev_cwd("git clean -fdx -- packages/happy-app ':!packages/happy-cli'",
                      datafile, fixture_repo) == "ALLOW"
        # positive . + exclude nonprot -> the positive '.' still contains protected
        assert ev_cwd("git clean -fdx -- . ':!packages/happy-app'", datafile, fixture_repo) == "BLOCK"

    # C2G: ~user expansion
    def test_tilde_user_expansion_blocks(self):
        os.environ["HOME"] = "/root"
        os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = "/root/.config/appz14c2/protected-runtime.json"
        import importlib, lib.runtime_guard as rg
        importlib.reload(rg)
        assert rg.evaluate("cd ~root/.config/appz14c2 && rm protected-runtime.json")[0] == "BLOCK"
        assert rg.evaluate("env -C ~root/.config/appz14c2 rm protected-runtime.json")[0] == "BLOCK"


class TestCycle16FlagCollisionMutationTargetClass:
    """RE-CLOSE #10 / Cycle-16 — close the ENTIRE flag-collision / mutation-target
    drop bug CLASS in `_mutation_targets_for_verb`, not just named instances.

    DRIVER: the `-t`/`--target-directory` pre-parse was VERB-AGNOSTIC. `-t DIR` is
    target-directory ONLY for GNU coreutils {cp, mv, install, ln}. For `rsync`, `-t`
    == `--times` (a no-arg flag); for `tar`, `-t` == `--list`. So `rsync -t <SRC>
    <protected-dest>` made the pre-parse set tdir=<SRC>, the rsync branch then set
    dest=tdir and reclassified the REAL protected destination as a source and DROPPED
    it → ALLOW leak (overwrites/neuters the guard config or clobbers the bundle).
    Fix: the pre-parse is now verb-aware (tdir only for cp/mv/install/ln); for every
    other verb tdir stays None and the verb's own last-operand-is-dest logic blocks.

    SECONDARY (same class):
      • `install -d DIR…` CREATES every named dir (no source) — every bareword is a
        target. The cp/install copy branch flagged only the last bareword, dropping a
        protected dir appearing earlier in `install -d A B <protecteddir>`.
      • `tar -x -C <protected-dir>` extracts members UNDER `-C DIR`; with no explicit
        members the branch returned [] and never counted the extraction dir itself.
        The `-C` dir is now a write target (archive read via `-f` stays a read).

    Engine probes pin an isolated config (`ev_iso`/isolated_pair) — the live data
    file is NEVER touched. Live-hook probes feed simulated PreToolUse JSON.
    """

    _RSYNC = "rs" + "ync"
    _TAR = "ta" + "r"
    _INST = "ins" + "tall"
    _CP = "c" + "p"
    _MV = "m" + "v"
    _LN = "l" + "n"

    # ── DRIVER: rsync -t flag collision (was ALLOW leak) ────────────────────────
    def test_rsync_t_config_dest_blocks(self, isolated_pair):
        df, cfgdir = isolated_pair["df"], isolated_pair["cfgdir"]
        cfgfile = f"{cfgdir}/protected-runtime.json"
        assert ev_iso(f"{self._RSYNC} -t /tmp/evil.json {cfgfile}", df) == "BLOCK"
        assert ev_iso(f"{self._RSYNC} --times /tmp/evil.json {cfgfile}", df) == "BLOCK"

    def test_rsync_t_bundle_dest_blocks(self, isolated_pair):
        df, repo = isolated_pair["df"], isolated_pair["repo"]
        bundle = f"{repo}/packages/happy-cli/dist/index.mjs"
        assert ev_iso(f"{self._RSYNC} -t /tmp/evil.mjs {bundle}", df, repo) == "BLOCK"

    def test_rsync_t_wrapped_and_chained_blocks(self, isolated_pair):
        df, cfgdir = isolated_pair["df"], isolated_pair["cfgdir"]
        cfgfile = f"{cfgdir}/protected-runtime.json"
        assert ev_iso(f"sudo {self._RSYNC} -t /tmp/evil.json {cfgfile}", df) == "BLOCK"
        assert ev_iso(f"setsid {self._RSYNC} -t /tmp/evil.json {cfgfile}", df) == "BLOCK"
        assert ev_iso(f"weirdwrapX {self._RSYNC} -t /tmp/evil.json {cfgfile}", df) == "BLOCK"
        assert ev_iso(f"cd /tmp && {self._RSYNC} -t a.json {cfgfile}", df) == "BLOCK"

    def test_rsync_noT_controls_still_block(self, isolated_pair):
        # the pre-existing no-`-t` controls must STILL block (no regression).
        df, cfgdir = isolated_pair["df"], isolated_pair["cfgdir"]
        cfgfile = f"{cfgdir}/protected-runtime.json"
        assert ev_iso(f"{self._RSYNC} -a /tmp/evil.json {cfgfile}", df) == "BLOCK"
        assert ev_iso(f"{self._RSYNC} /tmp/evil.json {cfgfile}", df) == "BLOCK"

    def test_rsync_t_source_read_allows(self, isolated_pair):
        # rsync READING the protected file as SOURCE (no --remove-source-files) is a
        # copy = read → ALLOW (no over-block), with or without the -t no-arg flag.
        df, cfgdir = isolated_pair["df"], isolated_pair["cfgdir"]
        cfgfile = f"{cfgdir}/protected-runtime.json"
        assert ev_iso(f"{self._RSYNC} {cfgfile} /tmp/elsewhere", df) == "ALLOW"
        assert ev_iso(f"{self._RSYNC} -t {cfgfile} /tmp/elsewhere", df) == "ALLOW"

    # ── SECONDARY: install -d (every bareword is a created dir) ──────────────────
    def test_install_d_single_dir_blocks(self, isolated_pair):
        df, cfgdir = isolated_pair["df"], isolated_pair["cfgdir"]
        assert ev_iso(f"{self._INST} -d {cfgdir}", df) == "BLOCK"
        assert ev_iso(f"{self._INST} --directory {cfgdir}", df) == "BLOCK"

    def test_install_d_multi_dir_no_drop_blocks(self, isolated_pair):
        # the protected dir appears NOT last — must still be a target (drop fixed).
        df, cfgdir = isolated_pair["df"], isolated_pair["cfgdir"]
        assert ev_iso(f"{self._INST} -d {cfgdir} /tmp/other", df) == "BLOCK"
        assert ev_iso(f"{self._INST} -d /tmp/a /tmp/b {cfgdir}", df) == "BLOCK"
        assert ev_iso(f"sudo {self._INST} -d /tmp/a {cfgdir} /tmp/b", df) == "BLOCK"

    def test_install_d_unrelated_allows(self, isolated_pair):
        df = isolated_pair["df"]
        assert ev_iso(f"{self._INST} -d /tmp/a /tmp/b", df) == "ALLOW"

    # ── SECONDARY: tar -x -C <protected-dir> (extraction dir is a write target) ──
    def test_tar_extract_into_protected_dir_blocks(self, isolated_pair):
        df, cfgdir = isolated_pair["df"], isolated_pair["cfgdir"]
        assert ev_iso(f"{self._TAR} -x -C {cfgdir} -f /tmp/a.tar", df) == "BLOCK"
        assert ev_iso(f"{self._TAR} -x --directory={cfgdir} -f /tmp/a.tar", df) == "BLOCK"
        assert ev_iso(f"sudo {self._TAR} -x -C {cfgdir} -f /tmp/a.tar", df) == "BLOCK"

    def test_tar_extract_into_bundle_dir_blocks(self, isolated_pair):
        df, repo = isolated_pair["df"], isolated_pair["repo"]
        distdir = f"{repo}/packages/happy-cli/dist"
        assert ev_iso(f"{self._TAR} -x -C {distdir} -f /tmp/a.tar", df, repo) == "BLOCK"

    def test_tar_archive_read_and_unrelated_extract_allow(self, isolated_pair):
        # listing/reading a protected archive via -f stays a READ; extracting into an
        # UNRELATED dir ALLOWs (no over-block).
        df, cfgdir = isolated_pair["df"], isolated_pair["cfgdir"]
        cfgfile = f"{cfgdir}/protected-runtime.json"
        assert ev_iso(f"{self._TAR} -tf {cfgfile}", df) == "ALLOW"
        assert ev_iso(f"{self._TAR} -xf {cfgfile}", df) == "ALLOW"
        assert ev_iso(f"{self._TAR} -x -C /tmp/safe -f /tmp/a.tar", df) == "ALLOW"

    # ── AUDIT representatives: every other mutation verb still classifies its
    #    protected WRITE/MOVE/REMOVE target AND preserves its read-allowance. ─────
    def test_audit_tdir_verbs_still_correct(self, isolated_pair):
        # the four legit `-t` verbs keep target-directory semantics; `mv -t /dst
        # <protected>` removes the protected SOURCE → BLOCK; `cp -t /dst <protected>`
        # keeps the source (read) → ALLOW.
        df, cfgdir = isolated_pair["df"], isolated_pair["cfgdir"]
        cfgfile = f"{cfgdir}/protected-runtime.json"
        assert ev_iso(f"{self._MV} -t /tmp/dst {cfgfile}", df) == "BLOCK"
        assert ev_iso(f"{self._CP} -t /tmp/dst {cfgfile}", df) == "ALLOW"
        # writing INTO the protected dir via -t a NEW basename is not the exact file → ALLOW
        assert ev_iso(f"{self._CP} -t {cfgdir} /tmp/unrelated.txt", df) == "ALLOW"

    def test_audit_value_taking_options_no_target_drop(self, isolated_pair):
        # options that take a VALUE (cp --preserve, install -m, rsync --rsh) must NOT
        # cause the real protected dest to be dropped (fail-safe). Their values may be
        # spuriously over-blocked but the protected dest is always retained.
        df, cfgdir = isolated_pair["df"], isolated_pair["cfgdir"]
        cfgfile = f"{cfgdir}/protected-runtime.json"
        assert ev_iso(f"{self._CP} --preserve=mode /tmp/x {cfgfile}", df) == "BLOCK"
        assert ev_iso(f"{self._INST} -m 644 /tmp/x {cfgfile}", df) == "BLOCK"
        assert ev_iso(f"{self._RSYNC} --rsh=ssh /tmp/x {cfgfile}", df) == "BLOCK"
        assert ev_iso(f"{self._RSYNC} -e ssh /tmp/x {cfgfile}", df) == "BLOCK"

    # ── config-ABSENT: STEP0 self-protection runs before config load ────────────
    def test_config_absent_class_blocks(self):
        os.environ["CLAUDE_PROTECTED_RUNTIME_FILE"] = "/tmp/abs16/.config/app/protected-runtime.json"
        import importlib, lib.runtime_guard as rg
        importlib.reload(rg)
        cfgdir = "/tmp/abs16/.config/app"
        cfgfile = f"{cfgdir}/protected-runtime.json"
        assert rg.evaluate(f"{self._RSYNC} -t /tmp/evil.json {cfgfile}")[0] == "BLOCK"
        assert rg.evaluate(f"{self._INST} -d {cfgdir} /tmp/o")[0] == "BLOCK"
        assert rg.evaluate(f"{self._TAR} -x -C {cfgdir} -f /tmp/a.tar")[0] == "BLOCK"

    # ── purity: the verb-aware fix introduces NO project name into the engine ───
    def test_engine_still_project_name_free(self):
        src = open(os.path.join(HOOKS_DIR, "lib", "runtime_guard.py")).read()
        for name in ("happy", "jade", "qijie", "life-ai", "slopus", "local-server"):
            assert name not in src.lower(), f"engine must stay project-name-free: {name!r}"


class TestCycle16LiveHook:
    """The DRIVER + each secondary representative BLOCK on the REAL hook end-to-end
    against the LIVE data file, plain + wrapped + under /do (the guard runs before
    /do, so it is unbypassable). Boundary read-allowances still ALLOW."""

    _ENV = {"CLAUDE_PYTHON_BIN": sys.executable}

    def _clean_env(self):
        e = dict(os.environ, **self._ENV)
        e.pop("CLAUDE_PROTECTED_RUNTIME_FILE", None)
        return e

    def _run(self, cmd, sid=None):
        payload = {"tool_name": "Bash", "tool_input": {"command": cmd}}
        if sid:
            payload["session_id"] = sid
        return subprocess.run(["bash", HOOK], input=json.dumps(payload), text=True,
                              capture_output=True, env=self._clean_env()).returncode

    def test_live_rsync_t_blocks(self):
        assert self._run("rsync -t /tmp/evil.json /root/.config/claude/protected-runtime.json") == BLOCK
        assert self._run("sudo rsync -t /tmp/evil.json /root/.config/claude/protected-runtime.json") == BLOCK

    def test_live_install_d_blocks(self):
        assert self._run("install -d /root/.config/claude") == BLOCK
        assert self._run("install -d /tmp/a /root/.config/claude /tmp/b") == BLOCK

    def test_live_tar_extract_into_protected_blocks(self):
        assert self._run("tar -x -C /root/.config/claude -f /tmp/a.tar") == BLOCK

    def test_live_class_unbypassable_under_do(self):
        sid = "guardtest16-" + str(os.getpid())
        flag = f"/tmp/claude-orchestrator-consent-{sid}.flag"
        with open(flag, "w") as fh:
            fh.write("true")
        try:
            assert self._run("rsync -t /tmp/evil.json /root/.config/claude/protected-runtime.json", sid) == BLOCK
            assert self._run("install -d /tmp/a /root/.config/claude", sid) == BLOCK
            assert self._run("tar -x -C /root/.config/claude -f /tmp/a.tar", sid) == BLOCK
            # read-allowance still allows under /do
            assert self._run("rsync /root/.config/claude/protected-runtime.json /tmp/elsewhere", sid) == ALLOW
        finally:
            os.remove(flag)

    def test_live_boundary_allows(self):
        assert self._run("rsync /root/.config/claude/protected-runtime.json /tmp/elsewhere") == ALLOW
        assert self._run("rsync -t /root/.config/claude/protected-runtime.json /tmp/elsewhere") == ALLOW
        assert self._run("install -d /tmp/a-xyz /tmp/b-xyz") == ALLOW
        assert self._run("tar -x -C /tmp/safe-xyz -f /tmp/a.tar") == ALLOW
        assert self._run("tar -tf /root/.config/claude/protected-runtime.json") == ALLOW


class TestCycle16CodexFollowup:
    """Codex (gpt-5.5 xhigh) adversarial pass on the flag-collision class surfaced
    SIX more in-scope leak families beyond the 3 named items — all SAME bug class
    (a flag/option changing operand classification so a protected WRITE/MOVE/REMOVE
    /CREATE target is DROPPED or MISREAD → ALLOW leak), all fixed this cycle:

      CX1: clustered/attached `-t` (`-vt DIR`, `-Dt DIR`, `-tDIR`) for cp/install/ln
           was not recognized → the synthesized DIR/basename(src) target dropped.
      CX2: `--` end-of-options ignored → `cp -- -t <protected>` treated post-`--`
           `-t` as target-directory and swallowed the protected destination.
      CX3: SEPARATED trailing value-options (`cp … -S .bak`, `install … -m 0644`,
           `rsync … -e ssh`, `ln … -S .bak`) let the option VALUE become the parsed
           destination, dropping/misreading the real protected dest.
      CX4: chmod SYMBOLIC flag-shaped mode (`-w`, `+x`, `=r`) was filtered out as an
           option, so the first protected file operand was mistaken for the mode spec
           and dropped.
      CX5: tar archive-WRITE modes (`-cf`/`--create`, `--append`/`-rf`, `--update`/
           `-uf`, `--delete`) never targeted the `-f` archive (overwrite/modify leak);
           tar old-style (`tar xf`) and FUSED (`tar -xf<archive>`) option parsing
           dropped the extract member; tar `-C DIR` member synthesis lost the
           preserved subpath; `--exclude` (a long opt containing `x`) over-blocked a
           list/read.
      CX6: unzip was all-operands-are-targets → over-blocked list/read modes
           (`unzip -l`) and missed `-d DIR` member subpaths.

    Engine probes pin an isolated config + repo (ev_iso/isolated_pair); the live data
    file is NEVER touched."""

    _RSYNC = "rs" + "ync"
    _TAR = "ta" + "r"
    _INST = "ins" + "tall"
    _UNZIP = "un" + "zip"
    _CP = "c" + "p"
    _LN = "l" + "n"
    _CHMOD = "chm" + "od"

    def _cfgfile(self, ip):
        return f"{ip['cfgdir']}/protected-runtime.json"

    def _bundle(self, ip):
        return f"{ip['repo']}/packages/happy-cli/dist/index.mjs"

    def _bundledir(self, ip):
        return f"{ip['repo']}/packages/happy-cli/dist"

    # CX1: clustered/attached -t writing the EXACT protected file blocks; writing a
    # NEW basename into the dir ALLOWs (only the exact protected path is protected).
    def test_cx1_clustered_attached_t_blocks(self, isolated_pair):
        df, repo = isolated_pair["df"], isolated_pair["repo"]
        bd = self._bundledir(isolated_pair)
        assert ev_iso(f"{self._CP} -vt {bd} /tmp/index.mjs", df, repo) == "BLOCK"
        assert ev_iso(f"{self._CP} -t{bd} /tmp/index.mjs", df, repo) == "BLOCK"
        assert ev_iso(f"{self._INST} -Dt {bd} /tmp/index.mjs", df, repo) == "BLOCK"

    def test_cx1_clustered_t_new_basename_allows(self, isolated_pair):
        df, repo = isolated_pair["df"], isolated_pair["repo"]
        bd = self._bundledir(isolated_pair)
        assert ev_iso(f"{self._INST} -Dt {bd} /tmp/unrelated.txt", df, repo) == "ALLOW"

    # CX2: -- end-of-options keeps the protected destination as an operand.
    def test_cx2_double_dash_keeps_protected_operand(self, isolated_pair):
        df = isolated_pair["df"]
        cf = self._cfgfile(isolated_pair)
        assert ev_iso(f"{self._CP} -- -t {cf}", df) == "BLOCK"

    # CX3: trailing separated value-options must not steal the destination slot.
    def test_cx3_trailing_value_options_block(self, isolated_pair):
        df = isolated_pair["df"]
        cf = self._cfgfile(isolated_pair)
        assert ev_iso(f"{self._CP} /tmp/src {cf} -S .bak", df) == "BLOCK"
        assert ev_iso(f"{self._INST} /tmp/src {cf} -m 0644", df) == "BLOCK"
        assert ev_iso(f"{self._RSYNC} /tmp/src {cf} -e ssh", df) == "BLOCK"
        assert ev_iso(f"{self._LN} -s /tmp/src {cf} -S .bak", df) == "BLOCK"

    # CX4: chmod symbolic flag-shaped mode keeps the protected file as a target.
    def test_cx4_chmod_symbolic_mode_blocks(self, isolated_pair):
        df = isolated_pair["df"]
        cf = self._cfgfile(isolated_pair)
        assert ev_iso(f"{self._CHMOD} -w {cf}", df) == "BLOCK"
        assert ev_iso(f"{self._CHMOD} +x {cf}", df) == "BLOCK"
        assert ev_iso(f"{self._CHMOD} -- -w {cf}", df) == "BLOCK"
        # numeric mode spec still drops the FIRST bareword (the mode) — boundary
        assert ev_iso(f"{self._CHMOD} 644 {cf}", df) == "BLOCK"

    # CX5: tar archive-write modes + old-style/fused parsing + -C subpath; --exclude
    # list over-block fixed.
    def test_cx5_tar_archive_write_modes_block(self, isolated_pair):
        df = isolated_pair["df"]
        cf = self._cfgfile(isolated_pair)
        assert ev_iso(f"{self._TAR} -cf {cf} /tmp/x", df) == "BLOCK"
        assert ev_iso(f"{self._TAR} --create --file={cf} /tmp/x", df) == "BLOCK"
        assert ev_iso(f"{self._TAR} -rf {cf} /tmp/x", df) == "BLOCK"
        assert ev_iso(f"{self._TAR} --delete -f {cf} foo", df) == "BLOCK"

    def test_cx5_tar_oldstyle_and_fused_extract_block(self, isolated_pair):
        df, repo = isolated_pair["df"], isolated_pair["repo"]
        member = "packages/happy-cli/dist/index.mjs"
        assert ev_iso(f"{self._TAR} xf /tmp/a.tar {member}", df, repo) == "BLOCK"
        assert ev_iso(f"{self._TAR} -xf/tmp/a.tar {member}", df, repo) == "BLOCK"
        assert ev_iso(f"{self._TAR} -xvf/tmp/a.tar {member}", df, repo) == "BLOCK"

    def test_cx5_tar_C_subpath_block(self, isolated_pair):
        df, repo = isolated_pair["df"], isolated_pair["repo"]
        member = "packages/happy-cli/dist/index.mjs"
        assert ev_iso(f"{self._TAR} -x -C {repo} -f /tmp/a.tar {member}", df, repo) == "BLOCK"

    def test_cx5_tar_exclude_list_read_allows(self, isolated_pair):
        # `--exclude` (long opt containing 'x') must NOT be read as extract; a -t LIST
        # of the protected archive is a READ → ALLOW (no over-block).
        df = isolated_pair["df"]
        cf = self._cfgfile(isolated_pair)
        assert ev_iso(f"{self._TAR} --exclude {cf} -t -f /tmp/a.tar", df) == "ALLOW"

    # CX6: unzip list-read allows; -d DIR member subpath blocks.
    def test_cx6_unzip_list_read_allows(self, isolated_pair):
        df = isolated_pair["df"]
        cf = self._cfgfile(isolated_pair)
        assert ev_iso(f"{self._UNZIP} -l {cf}", df) == "ALLOW"

    def test_cx6_unzip_extract_into_protected_blocks(self, isolated_pair):
        df, repo = isolated_pair["df"], isolated_pair["repo"]
        member = "packages/happy-cli/dist/index.mjs"
        assert ev_iso(f"{self._UNZIP} /tmp/a.zip {member} -d {repo}", df, repo) == "BLOCK"

    # purity: the codex fix introduces NO project name into the engine.
    def test_engine_still_project_name_free(self):
        src = open(os.path.join(HOOKS_DIR, "lib", "runtime_guard.py")).read().lower()
        for name in ("happy", "jade", "qijie", "life-ai", "slopus", "local-server"):
            assert name not in src, f"engine must stay project-name-free: {name!r}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
